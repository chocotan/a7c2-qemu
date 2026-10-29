#!/usr/bin/env python3
"""Verify public firmware evidence; never execute firmware or claim capture."""
import argparse
import hashlib
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parents[1] / "runtime/analysis/menu-root"


def read_va(segments, address, size):
    if address < 0 or size <= 0:
        raise ValueError("invalid evidence range")
    for base, data in segments:
        offset = address - base
        if 0 <= offset and offset + size <= len(data):
            return data[offset:offset + size]
    raise ValueError(f"range is not wholly file-backed: {address:#x}+{size:#x}")


def self_test():
    segments = [(0x1000, b"abcd"), (0x8000, b"WXYZ")]
    assert read_va(segments, 0x8001, 2) == b"XY"
    for address, size in ((0x1003, 2), (0x1004, 1), (0, 1), (0x1000, 0)):
        try:
            read_va(segments, address, size)
        except ValueError:
            continue
        raise AssertionError("unmapped or crossing evidence range accepted")


def verify(root):
    pins = json.loads((HERE / "source-pins.json").read_text())
    images, symbols, plts, relocations = {}, {}, {}, {}
    for ident, pin in pins["assets"].items():
        path = root / pin["path"]
        raw = path.read_bytes()
        assert len(raw) == pin["size"], f"{ident}: size changed"
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], f"{ident}: SHA mismatch"
        if pin["kind"] == "raw":
            images[ident] = [(0, raw)]
            continue
        with path.open("rb") as stream:
            elf = ELFFile(stream)
            assert elf.elfclass == 64 and elf["e_machine"] == "EM_AARCH64"
            images[ident] = [(s["p_vaddr"], s.data()) for s in elf.iter_segments()
                             if s["p_type"] == "PT_LOAD"]
            table = elf.get_section_by_name(".dynsym")
            symbols[ident] = {s.name: (s["st_value"], s["st_size"])
                              for s in table.iter_symbols()}
            for name, expected in pin.get("symbols", {}).items():
                assert symbols[ident][name] == tuple(expected), name
            plt = elf.get_section_by_name(".plt")["sh_addr"]
            plts[ident] = {plt + 32 + 16 * i: table.get_symbol(r["r_info_sym"]).name
                           for i, r in enumerate(elf.get_section_by_name(".rela.plt").iter_relocations())}
            relocations[ident] = {r["r_offset"]: table.get_symbol(r["r_info_sym"]).name
                                  for r in elf.get_section_by_name(".rela.dyn").iter_relocations()
                                  if r["r_info_sym"]}
    for window in pins["windows"]:
        raw = read_va(images[window["asset"]], window["start"], window["size"])
        assert hashlib.sha256(raw).hexdigest() == window["sha256"], window["name"]
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for check in pins["instructions"]:
        raw = read_va(images[check["asset"]], check["address"], 4)
        instruction, = decoder.disasm(raw, check["address"])
        actual = (instruction.mnemonic, instruction.op_str)
        assert actual == tuple(check["expected"]), (check, actual)
        if "call_symbol" in check:
            target = int(instruction.op_str.removeprefix("#"), 16)
            assert plts[check["asset"]][target] == check["call_symbol"]
    vtable, _ = symbols["I"]["_ZTVN14AvbbcParamCtrl16ParameterControlE"]
    for slot, suffix in ((0x80, "EjRh"), (0xb0, "EjRPv")):
        assert relocations["I"][vtable + 16 + slot] == (
            "_ZN14AvbbcParamCtrl16ParameterControl8GetValue" + suffix)
    print(f"PASS: {len(pins['assets'])} public assets, {len(pins['windows'])} byte windows, "
          f"{len(pins['instructions'])} instruction/call checks, named getter ABI")
    print("WITHOUT_PIN_METADATA_VERIFIED true")
    print("PIXEL_LAYOUT_VERIFIED false")
    print("ORIGINAL_JPEG_BITSTREAM_DECODED false")
    print("CAPTURE_VERIFIED false")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="public menu-root containing the pinned firmware")
    parser.add_argument("--self-test", action="store_true",
                        help="also test segment mapping and fail-closed range handling")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("PASS: segment mapping and four rejected ranges")
    verify(args.root)


if __name__ == "__main__":
    main()
