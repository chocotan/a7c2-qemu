#!/usr/bin/env python3
"""Offline pin, instruction-byte, and PCIe control-table verifier; no execution."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = ROOT / "runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin"
PIN = "620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2"


def require(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)


def main():
    data = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    require(len(data) == 6610952 and digest == PIN, "kernel size/hash")
    # Exact bytes bind the reported paths to the pinned image, without a VM.
    checks = {
        0x31A910: "211c00533f040071",  # uxtb; cmp selector,1
        0x31A920: "9f3e03d5031040b921008052020440f92020c31a400000b9",
        0x31A950: "9f3e03d5031040b921008052020040f92020c31a400000b9",
        0x31AA18: "211c00533f040071",
        0x31AA74: "9f3e03d5622a40b920008052610e40f90020c21a200000b9",
        0x31AAA8: "9f3e03d5622a40b920008052611240f90020c21a200000b9",
    }
    for offset, expected in checks.items():
        raw = bytes.fromhex(expected)
        require(data[offset:offset + len(raw)] == raw, f"instructions @{offset:#x}")
    rows = []
    for channel, (reset_bit, clock_bit, wrapper) in enumerate(zip(
        [1, 7, 13, 19, 25], [3, 11, 7, 15, 19],
        [0xF11C0000, 0xF1140000, 0xF1180000, 0xF1200000, 0xF1100000],
    )):
        offset = 0x63E8C8 + channel * 0x98
        u64 = lambda k: struct.unpack_from("<Q", data, offset + k)[0]
        u32 = lambda k: struct.unpack_from("<I", data, offset + k)[0]
        require(u64(0x18) == 0xFFFFFFFF00000000 | wrapper, "wrapper")
        require([u64(k) for k in [0x50, 0x58, 0x68, 0x70]] == [
            0xFFFFFFFFF1388084, 0xFFFFFFFFF1388088,
            0xFFFFFFFFF1388314, 0xFFFFFFFFF1388318,
        ], "SET/CLEAR pointers")
        require([u32(k) for k in [0x60, 0x64, 0x78, 0x7C]] ==
                [reset_bit, 1, clock_bit, 1], "bits/adjacent fields")
        require(data[offset + 0x80:offset + 0x98] == bytes(0x18), "optional fields zero")
        rows.append(dict(channel=channel, wrapper=hex(wrapper),
                         group1_bit=reset_bit, group1_mask=hex(1 << reset_bit),
                         group2_bit=clock_bit, group2_mask=hex(1 << clock_bit)))
    strings = {}
    for offset in [0x4770B0, 0x4770C8, 0x560C18, 0x560C28, 0x560C58, 0x560C88]:
        end = data.index(b"\0", offset)
        strings[hex(offset)] = data[offset:end].decode("ascii", errors="backslashreplace")
    print(json.dumps(dict(result="PASS", size=len(data), sha256=digest,
                          byte_checks=len(checks), channels=rows, strings=strings,
                          scope="static bytes/data only; no hardware reset or runtime claim"),
                     indent=2))


if __name__ == "__main__":
    main()
