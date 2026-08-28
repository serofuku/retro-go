#!/usr/bin/env python3

import struct
import sys

IMAGE = sys.argv[1]
VFS = sys.argv[2]

PARTITION_TABLE_OFFSET = 0x8000
PARTITION_ENTRY_SIZE = 32

def read_partition_table(data):
    partitions = []

    offset = PARTITION_TABLE_OFFSET

    while offset < PARTITION_TABLE_OFFSET + 0xC00:
        entry = data[offset:offset + PARTITION_ENTRY_SIZE]

        if entry[0:2] != b"\xAA\x50":
            offset += PARTITION_ENTRY_SIZE
            continue

        part_type = entry[2]
        subtype = entry[3]
        part_offset = struct.unpack_from("<I", entry, 4)[0]
        part_size = struct.unpack_from("<I", entry, 8)[0]

        label = entry[12:28].split(b"\0", 1)[0].decode(
            "ascii",
            errors="ignore"
        )

        partitions.append(
            (part_type, subtype, label, part_offset, part_size)
        )

        offset += PARTITION_ENTRY_SIZE

    return partitions


with open(IMAGE, "rb") as f:
    image = bytearray(f.read())

with open(VFS, "rb") as f:
    vfs = f.read()

partitions = read_partition_table(image)

vfs_partition = None

for partition in partitions:
    part_type, subtype, label, offset, size = partition

    if label == "vfs":
        vfs_partition = partition
        break

if vfs_partition is None:
    raise SystemExit("ERROR: vfs partition not found")

_, _, label, offset, size = vfs_partition

print(
    f"VFS partition: offset=0x{offset:X}, "
    f"size=0x{size:X}"
)

print(
    f"VFS image size: 0x{len(vfs):X}"
)

if len(vfs) > size:
    raise SystemExit(
        "ERROR: VFS image is larger than the vfs partition"
    )

image[offset:offset + len(vfs)] = vfs

with open(IMAGE, "wb") as f:
    f.write(image)

print("VFS injected successfully.")
