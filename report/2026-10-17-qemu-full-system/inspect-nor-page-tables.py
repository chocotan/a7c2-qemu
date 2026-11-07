#!/usr/bin/env python3
"""Offline reconstruction of the selected original NOR EL3 table builder."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

BASE = 0xFE040000
SOURCE_SHA = "e74ee44e947e9bfd5cc60248ab13db8883449909ff63cbe8330b1e74462ea7c6"
L2 = 0xFE180000
ROOT36 = 0xFE200000
ROOT32 = 0xFE202000


def reconstruct(source):
    if len(source) != 417792 or hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("unexpected NOR source size/SHA256")

    def word(va):
        return struct.unpack_from("<Q", source, va - BASE)[0]

    assert [word(a) for a in (0xFE049218, 0xFE049220, 0xFE049228)] == [
        ROOT36, ROOT32, L2]
    assert (word(0xFE049630), word(0xFE049638)) == (0xFE049230, 0xFE049488)
    assert word(0xFE049628) == 0x122520
    assert word(0xFE05AF10) == 0x12251C
    memory = bytearray(0x84000)  # Original clear extents, starting at L2.

    def store(va, value):
        if va & 7 or not L2 <= va <= L2 + len(memory) - 8:
            raise ValueError("table store outside original clear extents")
        struct.pack_into("<Q", memory, va - L2, value)

    # fe049100..158: table descriptors only for these selected L1 indices.
    for index in range(64):
        table = index <= 3 or 16 <= index <= 19 or 32 <= index <= 51
        store(ROOT36 + 8 * index, (L2 + 4096 * index) | (3 if table else 1))
    # fe04917c..1a4: the initial 32-bit VA root has only index 3 as a table.
    for index in range(4):
        store(ROOT32 + 8 * index, (L2 + 4096 * index) | (3 if index == 3 else 1))
    regions = []
    for va in range(0xFE049230, 0xFE049488, 24):
        start, end, attrs = struct.unpack_from("<QQQ", source, va - BASE)
        if start & 0x1FFFFF or end & 0x1FFFFF or not start < end <= 1 << 36:
            raise ValueError("unexpected original region")
        regions.append({"record_va": hex(va), "start": hex(start),
                        "end_exclusive": hex(end), "attributes": hex(attrs)})
        # fe0491c8..1fc: 15-bit index and 2 MiB blocks, preserving high PA bits.
        for index in range((start >> 21) & 0x7FFF, ((end - 1) >> 21 & 0x7FFF) + 1):
            store(L2 + 8 * index, (start & ~0x1FFFFF) +
                  ((index - (start >> 21 & 0x7FFF)) << 21) | attrs)
    return bytes(memory), regions


def walk(memory, va, bits):
    if bits not in (32, 36) or not 0 <= va < 1 << bits:
        raise ValueError("VA outside selected T0SZ range")
    root = ROOT32 if bits == 32 else ROOT36

    def load(pa):
        if not L2 <= pa <= L2 + len(memory) - 8:
            raise ValueError("descriptor outside reconstructed memory")
        return struct.unpack_from("<Q", memory, pa - L2)[0]

    first_addr = root + 8 * (va >> 30)
    first = load(first_addr)
    result = {"va": hex(va), "va_bits": bits, "root_pa": hex(root),
              "l1_address": hex(first_addr), "l1_descriptor": hex(first)}
    if first & 3 != 3:
        return dict(result, status="l1_not_table_not_interpreted")
    second_addr = (first & 0xFFFFFFFFF000) + 8 * (va >> 21 & 0x1FF)
    second = load(second_addr)
    result.update(l2_address=hex(second_addr), l2_descriptor=hex(second))
    if second & 3 != 1:
        return dict(result, status="unmapped_or_not_l2_block")
    pa = (second & 0xFFFFFFE00000) | (va & 0x1FFFFF)
    return dict(result, status="mapped_l2_block", pa=hex(pa), identity=pa == va)


def inspect(source):
    memory, regions = reconstruct(source)
    probes = [0xFE049000, 0xF102F000, 0x403E42000, 0x803E42000,
              0x800107F10, 0x804000000, 0xBFE0B0400, 0x03E42000]
    walks = [walk(memory, va, 36) for va in probes]
    assert all(row["status"] == "mapped_l2_block" and row["identity"] for row in walks)
    initial = [walk(memory, va, 32) for va in (0xFE049000, 0xF102F000)]
    assert all(row["status"] == "mapped_l2_block" and row["identity"] for row in initial)
    return {
        "source_sha256": SOURCE_SHA,
        "builder_sha256": hashlib.sha256(source[0x90D8:0x9200]).hexdigest(),
        "region_table_sha256": hashlib.sha256(source[0x9230:0x9488]).hexdigest(),
        "table_memory_sha256": hashlib.sha256(memory).hexdigest(),
        "table_memory_extent": [hex(L2), hex(L2 + len(memory))],
        "regions": regions, "walks_36bit": walks, "walks_initial_32bit": initial,
        "scope": "Static reconstruction; no original loader execution, physical bus alias or GPIO state proved.",
        "unreviewed_l1_blocks": "Original non-table descriptors are retained verbatim, not interpreted as valid translations.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nor", type=Path, help="read-only original nor_ldr.img")
    args = parser.parse_args()
    print(json.dumps(inspect(args.nor.read_bytes()), indent=2))
