#!/usr/bin/env python3
"""Verify bounded provider evidence from bytes; never execute kernel code."""
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
KERNEL = ROOT / "runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin"
PIN = "620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2"
BASE = 0xFFFFFF8008080000
FUNCTIONS = [
    ("cxd_clk_gate_is_enabled", 0x25FA78, 0x25FAC0,
     "f5fdbe264c8163b1414929cde7409668583641bb069ff08fa48325fc678d47f6"),
    ("cxd_clk_gate_disable", 0x25FAC0, 0x25FB38,
     "d6702979ecd454069a280a55a82a5ff84ce06f89f3ac0f9f4bf81e5ff76df84c"),
    ("cxd_clk_gate_enable", 0x25FB38, 0x25FBB8,
     "2dda0797eec2b263f1ba6a3614b0e68a0623c493afd019849c15caeae49147cb"),
]


def require(condition, description):
    if not condition:
        raise SystemExit("FAIL: " + description)


def main():
    data = Path(sys.argv[1] if len(sys.argv) > 1 else KERNEL).read_bytes()
    require(len(data) == 6610952, "kernel size")
    require(hashlib.sha256(data).hexdigest() == PIN, "kernel SHA-256")
    u64 = lambda offset: struct.unpack_from("<Q", data, offset)[0]
    u32 = lambda offset: struct.unpack_from("<I", data, offset)[0]

    def cstring(offset):
        return data[offset:data.index(b"\0", offset)].decode("ascii")

    require(u64(0x4AAA00) == BASE, "kallsyms relative base")
    count = u64(0x4AAB00)
    require(count == 41265, "kallsyms count")
    indexes = struct.unpack_from("<256H", data, 0x522700)
    tokens = [cstring(0x522300 + i) for i in indexes]
    for i in range(255):
        require(indexes[i + 1] == indexes[i] + len(tokens[i]) + 1,
                "token boundaries")
    symbols = {}
    cursor = 0x4AAC00
    markers = []
    previous = 0
    for index in range(count):
        if index % 256 == 0:
            markers.append(cursor - 0x4AAC00)
        length = data[cursor]
        require(length > 0, "nonempty compressed name")
        name = "".join(tokens[i] for i in data[cursor + 1:cursor + 1 + length])
        offset = u32(0x482500 + index * 4)
        require(offset >= previous, "ordered symbol offsets")
        previous = offset
        symbols[name[1:]] = offset
        cursor += 1 + length
    require(cursor == 0x521C25, "compressed names end")
    require(tuple(markers) == struct.unpack_from("<162Q", data, 0x521D00),
            "all 162 name markers")

    expected_symbols = {
        "__of_table_cxd_900xx": 0x5DDE50,
        "cxd_900xx_clks_init": 0x5C96C8,
        "cxd_clk_gate_ops": 0x629428,
        "cxd900xx_clk_gate": 0x629AB0,
        "cxd900xx_clks_syscore_ops": 0x62A370,
        "regmap_read": 0x294B80,
        "regmap_write": 0x295F68,
    }
    for name, offset in expected_symbols.items():
        require(symbols.get(name) == offset, "symbol " + name)
    require(cstring(0x5DDE90) == "cxd,900xx-clock", "OF compatible")
    require(u64(0x5DDF10) == BASE + 0x5C96C8, "OF init pointer")
    ops = {}
    for field, name, offset in [
        (0x20, "enable", 0x25FB38),
        (0x28, "disable", 0x25FAC0),
        (0x30, "is_enabled", 0x25FA78),
    ]:
        require(u64(0x629428 + field) == BASE + offset, "ops " + name)
        ops[name] = hex(offset)
    function_hashes = {}
    for name, start, end, expected in FUNCTIONS:
        require(symbols.get(name) == start, name + " symbol")
        actual = hashlib.sha256(data[start:end]).hexdigest()
        require(actual == expected, name + " complete bytes")
        function_hashes[name] = actual

    # Checks anchor the decoded read/non-inverted result and both write paths.
    instructions = {
        0x25FA8C: "012040b9000c40f93bd40094",
        0x25FA98: "62b24039200080d2a12f40b9",
        0x25FAAC: "0020c29a3f00006ae0079f1ac0035fd6",
        0x25FB10: "62b24039230080d2612a40b9600e40f96220c29a11d90094",
        0x25FB90: "62b24039230080d2612640b9600e40f96220c29af1d80094",
    }
    for offset, expected in instructions.items():
        raw = bytes.fromhex(expected)
        require(data[offset:offset + len(raw)] == raw, f"instructions {offset:#x}")

    all_offsets = set()
    pcie_rows = []
    for offset in range(0x629AB0, 0x62A370, 0x20):
        ident, name, parent, register, bit = struct.unpack_from("<QQQII", data, offset)
        name = cstring(name - BASE)
        all_offsets.add(register)
        if "pcie" in name:
            pcie_rows.append(dict(record=hex(offset), id=ident, name=name,
                                  register_offset=hex(register), bit=bit))
    require(all_offsets == {0, 0x20, 0x30, 0x40, 0x50, 0x80}, "gate offsets")
    require(len(pcie_rows) == 27, "PCIe gate record count")
    require({row["register_offset"] for row in pcie_rows} == {"0x30", "0x80"},
            "PCIe gate offsets")
    print(json.dumps(dict(
        result="PASS", size=len(data), sha256=PIN,
        kallsyms_count=count, verified_markers=len(markers),
        callbacks=ops, complete_function_hashes=function_hashes,
        instruction_checks=len(instructions), gate_record_count=70,
        gate_offsets=[hex(i) for i in sorted(all_offsets)], pcie_gates=pcie_rows,
        conclusion={
            "callback_status_test": "selected bit nonzero => is_enabled true",
            "F1388310_binding": "unresolved within three-function budget",
            "F1388314_8318_W1SET_W1CLEAR": "unresolved",
            "silicon_reset": "unknown", "current_hardware_state": "unknown",
        },
        scope="static byte/data verification only; no target execution",
    ), indent=2))


if __name__ == "__main__":
    main()
