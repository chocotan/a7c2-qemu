#!/usr/bin/env python3
"""Source-pin self-check only; does not run firmware or integration tests."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile


here = Path(__file__).resolve().parent
root = here.parents[1]
pins = json.loads((here / "source-pins.json").read_text())
artifact = pins["artifacts"]["M"]
data = (root / artifact["path"]).read_bytes()
assert len(data) == artifact["bytes"]
assert sha256(data).hexdigest() == artifact["sha256"]
elf = ELFFile(BytesIO(data))
loads = [segment for segment in elf.iter_segments() if segment["p_type"] == "PT_LOAD"]
assert [
    {key: hex(segment[key]) for key in ("p_offset", "p_vaddr", "p_filesz", "p_memsz", "p_flags")}
    for segment in loads
] == pins["elf_loads"]


def offset(va, length):
    matches = [
        segment for segment in loads
        if segment["p_vaddr"] <= va
        and va + length <= segment["p_vaddr"] + segment["p_filesz"]
    ]
    assert len(matches) == 1, f"Not exactly one file-backed PT_LOAD: {va:#x}"
    return matches[0]["p_offset"] + va - matches[0]["p_vaddr"]


assert len(pins["windows"]) == pins["window_count"] == 12
assert sum(window["bytes"] for window in pins["windows"]) == pins["window_bytes"] == 7086
for window in pins["windows"]:
    va, length = int(window["elf_va_hex"], 16), window["bytes"]
    start = offset(va, length)
    assert start == int(window["file_offset_hex"], 16), window["id"]
    assert sha256(data[start:start + length]).hexdigest() == window["sha256"], window["id"]
for instruction in pins["instruction_assertions"]:
    va = int(instruction["elf_va_hex"], 16)
    start = offset(va, 4)
    assert data[start:start + 4].hex() == instruction["bytes_hex"], instruction["meaning"]
    assert any(
        int(window["elf_va_hex"], 16) <= va
        and va + 4 <= int(window["elf_va_hex"], 16) + window["bytes"]
        for window in pins["windows"]
    )

symbols = list(elf.get_section_by_name(".dynsym").iter_symbols())
for binding in pins["elf_relocation_bindings"]:
    relocations = elf.get_section_by_name(binding["relocation_section"]).iter_relocations()
    matches = [
        relocation for relocation in relocations
        if relocation["r_offset"] == int(binding["relocation_target_va_hex"], 16)
    ]
    assert len(matches) == 1
    relocation = matches[0]
    symbol = symbols[relocation["r_info_sym"]]
    assert relocation["r_info_type"] == binding["relocation_type"]
    assert relocation["r_addend"] == binding["addend"]
    assert symbol.name == binding["symbol"]
    assert symbol["st_value"] == int(binding["symbol_value_hex"], 16)

plt = elf.get_section_by_name(".plt")
relocations = list(elf.get_section_by_name(".rela.plt").iter_relocations())
index = next(i for i, relocation in enumerate(relocations) if relocation["r_offset"] == 0x2FE6B0)
assert plt["sh_addr"] + 32 + index * 16 == 0x7BE20
assert symbols[relocations[index]["r_info_sym"]]["st_value"] == 0x280BC8
assert data[offset(0x7BE20, 16):offset(0x7BE20, 16) + 16].hex() == "101400f0115a43f910c21a9120021fd6"
assert data[offset(0xD2D60, 4):offset(0xD2D60, 4) + 4].hex() == "7f220239"
for unit, target in ((3, 0x2B2D68), (4, 0x2B2D78), (6, 0x2B2E00)):
    start = offset(0x2E0ED8 + unit * 2, 2)
    assert 0x2B2CF8 + int.from_bytes(data[start:start + 2], "little", signed=True) * 4 == target
assert pins["single_open"]["byte88_value"] == 0
assert pins["single_open"]["parameter_count_w3"] == 1
assert pins["lease"]["execution_parameter_snapshot_owned_until_callback_returns"]
assert not pins["lease"]["per_frame_completion_release_proven"]
assert not pins["lease"]["fixed_area_0x98_lease_proven"]
assert not pins["backing_identity"]["physical_extent_contiguity_proven"]
assert not pins["capture_verified"] and pins["native_gap_mask"] == 63
print("source-pin self-check only: 12 windows / 7086 bytes, original byte88=0; capture=false, gaps=63")
