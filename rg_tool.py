#!/usr/bin/env python3

import argparse
import subprocess
import shutil
import glob
import math
import sys
import re
import os
import struct
import time
import zlib


DEFAULT_TARGET = os.getenv("RG_TOOL_TARGET", "odroid-go")
DEFAULT_BAUD = os.getenv("RG_TOOL_BAUD", "1152000")
DEFAULT_PORT = os.getenv("RG_TOOL_PORT", "COM3")
DEFAULT_APPS = os.getenv(
    "RG_TOOL_APPS",
    "launcher retro-core prboom-go gwenesis fmsx"
)

PROJECT_NAME = os.getenv("PROJECT_NAME", "Retro-Go")
PROJECT_ICON = os.getenv("PROJECT_ICON", "assets/icon.raw")

PROJECT_APPS = {
    "launcher":     [0, 16, 1048576],
    "retro-core":   [0, 16, 1048576],
    "prboom-go":    [0, 16, 786432],
    "gwenesis":     [0, 16, 1048576],
    "fmsx":         [0, 16, 589824],
}

try:
    PROJECT_VER = os.getenv("PROJECT_VER") or subprocess.check_output(
        "git describe --tags --abbrev=5 --dirty --always",
        shell=True
    ).decode().rstrip()
except:
    PROJECT_VER = "unknown"

FW_FORMAT = "none"

TARGETS = []

for t in glob.glob("components/retro-go/targets/*/config.h"):
    TARGETS.append(os.path.basename(os.path.dirname(t)))

IDF_TARGET = os.getenv("IDF_TARGET", "esp32")
IDF_PATH = os.getenv("IDF_PATH")

if not IDF_PATH:
    exit("IDF_PATH is not defined. Are you running inside esp-idf environment?")

if os.name == "nt":
    IDF_PY = os.path.join(IDF_PATH, "tools", "idf.py")
    IDF_MONITOR_PY = os.path.join(IDF_PATH, "tools", "idf_monitor.py")
    ESPTOOL_PY = os.path.join(
        IDF_PATH,
        "components",
        "esptool_py",
        "esptool",
        "esptool.py"
    )
    PARTTOOL_PY = os.path.join(
        IDF_PATH,
        "components",
        "partition_table",
        "parttool.py"
    )
    GEN_ESP32PART_PY = os.path.join(
        IDF_PATH,
        "components",
        "partition_table",
        "gen_esp32part.py"
    )
else:
    IDF_PY = "idf.py"
    IDF_MONITOR_PY = "idf_monitor.py"
    ESPTOOL_PY = "esptool.py"
    PARTTOOL_PY = "parttool.py"
    GEN_ESP32PART_PY = "gen_esp32part.py"

MKFW_PY = os.path.join("tools", "mkfw.py")


def run(cmd, cwd=None, check=True):
    print("Running command: %s" % " ".join(cmd))

    if os.name == "nt" and cmd[0].endswith(".py"):
        return subprocess.run(
            ["python", *cmd],
            shell=True,
            cwd=cwd,
            check=check
        )

    return subprocess.run(
        cmd,
        shell=False,
        cwd=cwd,
        check=check
    )


def parse_size(value):
    """
    Convert sizes such as:

        8M
        8MB
        500K
        500KB
        1048576

    into an integer number of bytes.
    """

    if value is None:
        return 0

    if isinstance(value, int):
        return value

    value = str(value).strip().upper()

    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)\s*([KMG]?)B?",
        value
    )

    if not match:
        raise ValueError(
            "Invalid FAT size: %s" % value
        )

    number = float(match.group(1))
    unit = match.group(2)

    multipliers = {
        "": 1,
        "K": 1024,
        "M": 1024 * 1024,
        "G": 1024 * 1024 * 1024,
    }

    return int(number * multipliers[unit])


def build_image(
    apps,
    output_file,
    img_type="odroid",
    fatsize=0,
    target="unknown",
    version="unknown"
):

    print(
        "Building firmware image with: %s\n"
        % " ".join(apps)
    )

    args = [
        MKFW_PY,
        "--type",
        img_type,
        "--name",
        PROJECT_NAME,
        "--icon",
        PROJECT_ICON,
        "--version",
        PROJECT_VER
    ]

    if img_type not in ["odroid", "esplay"]:

        print("Building bootloader...")

        bootloader_file = os.path.join(
            os.getcwd(),
            list(apps)[0],
            "build",
            "bootloader",
            "bootloader.bin"
        )

        if not os.path.exists(bootloader_file):
            run(
                [IDF_PY, "bootloader"],
                cwd=os.path.join(
                    os.getcwd(),
                    list(apps)[0]
                )
            )

        args += [
            "--target",
            target,
            "--bootloader",
            bootloader_file
        ]

    args += [output_file]

    ota_next_id = 16

    for app in apps:

        part = PROJECT_APPS[app]

        subtype = part[1]

        if (
            part[0] == 0
            and (part[1] & 0xF0) == 0x10
        ):
            subtype = ota_next_id
            ota_next_id += 1

        args += [
            str(part[0]),
            str(subtype),
            str(part[2]),
            app,
            os.path.join(
                app,
                "build",
                app + ".bin"
            )
        ]

    # ---------------------------------------------------------
    # Add VFS partition ONCE, after all applications
    # ---------------------------------------------------------

    if fatsize:

        fatsize_bytes = parse_size(fatsize)

        vfs_file = "vfs.img"

        if not os.path.exists(vfs_file):
            print(
                "WARNING: vfs.img not found. "
                "Creating empty VFS partition."
            )
            vfs_file = "none"
        else:
            actual_vfs_size = os.path.getsize(vfs_file)

            print(
                "Using VFS image: %s"
                % os.path.abspath(vfs_file)
            )

            print(
                "VFS requested size: %d bytes"
                % fatsize_bytes
            )

            print(
                "VFS actual image size: %d bytes"
                % actual_vfs_size
            )

            if actual_vfs_size > fatsize_bytes:
                raise RuntimeError(
                    "vfs.img is larger than the requested "
                    "FAT partition size: %d > %d"
                    % (
                        actual_vfs_size,
                        fatsize_bytes
                    )
                )

        args += [
            "1",
            "129",
            str(fatsize_bytes),
            "vfs",
            vfs_file
        ]

    print(
        "Running mkfw with VFS size in bytes."
    )

    run(args)


def clean_app(app):

    print(
        "Cleaning up app '%s'..."
        % app
    )

    try:
        os.unlink(
            os.path.join(
                app,
                "sdkconfig"
            )
        )

        os.unlink(
            os.path.join(
                app,
                "sdkconfig.old"
            )
        )

    except:
        pass

    try:
        shutil.rmtree(
            os.path.join(
                app,
                "build"
            )
        )

    except:
        pass

    print("Done.\n")


def build_app(
    app,
    device_type,
    with_profiling=False,
    no_networking=False,
    is_release=False
):

    print(
        "Building app '%s'"
        % app
    )

    args = [
        IDF_PY,
        "app"
    ]

    args.append(
        "-DRG_PROJECT_APP=%s"
        % app
    )

    args.append(
        "-DRG_PROJECT_VER=%s"
        % PROJECT_VER
    )

    args.append(
        "-DRG_BUILD_TARGET=RG_TARGET_%s"
        % re.sub(
            r"[^A-Z0-9]",
            "_",
            device_type.upper()
        )
    )

    args.append(
        "-DRG_BUILD_RELEASE=%d"
        % (1 if is_release else 0)
    )

    args.append(
        "-DRG_ENABLE_PROFILING=%d"
        % (1 if with_profiling else 0)
    )

    args.append(
        "-DRG_ENABLE_NETWORKING=%d"
        % (0 if no_networking else 1)
    )

    with open("partitions.csv", "w") as f:

        f.write(
            "# This table isn't used, "
            "it's just needed to avoid "
            "esp-idf build failures.\n"
        )

        f.write(
            "dummy, app, ota_0, 65536, 3145728\n"
        )

    run(
        args,
        cwd=os.path.join(
            os.getcwd(),
            app
        )
    )

    print("Done.\n")


def flash_app(
    app,
    port,
    baudrate=1152000
):

    os.putenv(
        "ESPTOOL_CHIP",
        IDF_TARGET
    )

    os.putenv(
        "ESPTOOL_BAUD",
        str(baudrate)
    )

    os.putenv(
        "ESPTOOL_PORT",
        port
    )

    if not os.path.exists(
        "partitions.bin"
    ):

        print(
            "Reading device's partition table..."
        )

        run(
            [
                ESPTOOL_PY,
                "read_flash",
                "0x8000",
                "0x1000",
                "partitions.bin"
            ],
            check=False
        )

        run(
            [
                GEN_ESP32PART_PY,
                "partitions.bin"
            ],
            check=False
        )

    app_bin = os.path.join(
        app,
        "build",
        app + ".bin"
    )

    print(
        "Flashing '%s' to port %s"
        % (
            app_bin,
            port
        )
    )

    run(
        [
            PARTTOOL_PY,
            "--partition-table-file",
            "partitions.bin",
            "write_partition",
            "--partition-name",
            app,
            "--input",
            app_bin
        ]
    )

    print("Done.\n")


def flash_image(
    image_file,
    port,
    baudrate=1152000
):

    os.putenv(
        "ESPTOOL_CHIP",
        IDF_TARGET
    )

    os.putenv(
        "ESPTOOL_BAUD",
        str(baudrate)
    )

    os.putenv(
        "ESPTOOL_PORT",
        port
    )

    print(
        "Flashing image file '%s' to %s"
        % (
            image_file,
            port
        )
    )

    run(
        [
            ESPTOOL_PY,
            "write_flash",
            "--flash_size",
            "detect",
            "0x0",
            image_file
        ]
    )

    print("Done.\n")


def monitor_app(
    app,
    port,
    baudrate=115200
):

    print(
        "Starting monitor for app %s"
        % app
    )

    elf_file = os.path.join(
        os.getcwd(),
        app,
        "build",
        app + ".elf"
    )

    if os.path.exists(elf_file):

        run(
            [
                IDF_MONITOR_PY,
                "--port",
                port,
                elf_file
            ]
        )

    else:

        run(
            [
                IDF_MONITOR_PY,
                "--port",
                port,
                "-d",
                sys.argv[0]
            ]
        )


# ============================================================
# ARGUMENT PARSER
# ============================================================

parser = argparse.ArgumentParser(
    description="Retro-Go build tool"
)

parser.add_argument(
    "command",
    choices=[
        "build-fw",
        "build-img",
        "release",
        "build",
        "clean",
        "flash",
        "monitor",
        "run",
        "profile",
        "install"
    ]
)

parser.add_argument(
    "apps",
    nargs="*",
    default="all",
    choices=[
        "all"
    ] + list(PROJECT_APPS.keys())
)

parser.add_argument(
    "--target",
    default=DEFAULT_TARGET,
    choices=set(TARGETS),
    help="Device to target"
)

parser.add_argument(
    "--no-networking",
    action="store_const",
    const=True,
    help="Build without networking support"
)

parser.add_argument(
    "--port",
    default=DEFAULT_PORT,
    help="Serial port to use for flash and monitor"
)

parser.add_argument(
    "--baud",
    default=DEFAULT_BAUD,
    help="Serial baudrate to use for flashing"
)

parser.add_argument(
    "--fatsize",
    help=(
        "Add FAT storage partition "
        "of provided size "
        "(500K, 5M,...) to the built image."
    )
)

args = parser.parse_args()


# ============================================================
# TARGET ENVIRONMENT
# ============================================================

if os.path.exists(
    "components/retro-go/targets/%s/env.py"
    % args.target
):

    with open(
        "components/retro-go/targets/%s/env.py"
        % args.target,
        "rb"
    ) as f:

        prev_idf_target = os.getenv(
            "IDF_TARGET"
        )

        exec(f.read())

        if os.getenv(
            "IDF_TARGET"
        ) != prev_idf_target:

            IDF_TARGET = os.getenv(
                "IDF_TARGET"
            )


if os.path.exists(
    "components/retro-go/targets/%s/sdkconfig"
    % args.target
):

    os.putenv(
        "SDKCONFIG_DEFAULTS",
        os.path.abspath(
            "components/retro-go/targets/%s/sdkconfig"
            % args.target
        )
    )


os.putenv(
    "IDF_TARGET",
    IDF_TARGET
)


command = args.command

apps = (
    DEFAULT_APPS.split()
    if "all" in args.apps
    else args.apps
)

apps = [
    app
    for app in PROJECT_APPS.keys()
    if app in apps
]


# ============================================================
# MAIN
# ============================================================

try:

    if command in [
        "clean",
        "release"
    ]:

        print(
            "=== Step: Cleaning ===\n"
        )

        for app in apps:
            clean_app(app)


    if command in [
        "build",
        "build-fw",
        "build-img",
        "release",
        "run",
        "profile",
        "install"
    ]:

        print(
            "=== Step: Building ===\n"
        )

        for app in apps:

            build_app(
                app,
                args.target,
                command == "profile",
                args.no_networking,
                command == "release"
            )


    if command in [
        "build-fw",
        "release"
    ]:

        print(
            "=== Step: Packing ===\n"
        )

        if FW_FORMAT in [
            "odroid",
            "esplay"
        ]:

            fw_file = (
                "%s_%s_%s.fw"
                % (
                    PROJECT_NAME,
                    PROJECT_VER,
                    args.target
                )
            ).lower()

            build_image(
                apps,
                fw_file,
                FW_FORMAT,
                args.fatsize,
                args.target,
                PROJECT_VER
            )

        else:

            print(
                "Device doesn't support fw format, "
                "try build-img!"
            )


    if command in [
        "build-img",
        "release",
        "install"
    ]:

        print(
            "=== Step: Packing ===\n"
        )

        img_file = (
            "%s_%s_%s.img"
            % (
                PROJECT_NAME,
                PROJECT_VER,
                args.target
            )
        ).lower()

        build_image(
            apps,
            img_file,
            IDF_TARGET,
            args.fatsize,
            args.target,
            PROJECT_VER
        )


    if command in [
        "install"
    ]:

        print(
            "=== Step: Flashing entire image "
            "to device ===\n"
        )

        img_file = (
            "%s_%s_%s.img"
            % (
                PROJECT_NAME,
                PROJECT_VER,
                args.target
            )
        ).lower()

        flash_image(
            img_file,
            args.port,
            args.baud
        )


    if command in [
        "flash",
        "run",
        "profile"
    ]:

        print(
            "=== Step: Flashing ===\n"
        )

        try:
            os.unlink(
                "partitions.bin"
            )
        except:
            pass

        for app in apps:

            flash_app(
                app,
                args.port,
                args.baud
            )


    if command in [
        "monitor",
        "run",
        "profile"
    ]:

        print(
            "=== Step: Monitoring ===\n"
        )

        monitor_app(
            apps[0]
            if len(apps)
            else "none",
            args.port
        )


    print("All done!")


except KeyboardInterrupt:

    exit("\n")


except Exception as e:

    print(
        "\nTask failed: %s"
        % e
    )

    raise
