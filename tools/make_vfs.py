#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys

VFS_SIZE_MB = int(os.environ.get("VFS_SIZE_MB", "8"))
SOURCE_DIR = os.environ.get("VFS_SOURCE", "vfs")
OUTPUT = os.environ.get("VFS_IMAGE", "vfs.img")

size = VFS_SIZE_MB * 1024 * 1024

print(f"Creating {OUTPUT}")
print(f"Size: {size} bytes")

# Create empty image
with open(OUTPUT, "wb") as f:
    f.truncate(size)

# Format FAT filesystem
subprocess.run([
    "mkfs.fat",
    "-F", "16",
    "-n", "RETROGO",
    OUTPUT
], check=True)

# Create directories
os.makedirs(SOURCE_DIR + "/roms/gbc", exist_ok=True)
os.makedirs(SOURCE_DIR + "/roms/gb", exist_ok=True)
os.makedirs(SOURCE_DIR + "/retro-go/config", exist_ok=True)
os.makedirs(SOURCE_DIR + "/retro-go/saves", exist_ok=True)

# Copy ROMs
for root, dirs, files in os.walk("roms"):
    for filename in files:
        src = os.path.join(root, filename)

        relative = os.path.relpath(src, "roms")
        destination = os.path.join(
            SOURCE_DIR,
            "roms",
            relative
        )

        os.makedirs(os.path.dirname(destination), exist_ok=True)

        shutil.copyfile(src, destination)

        print(f"Added ROM: {relative}")

print("VFS image created successfully.")
