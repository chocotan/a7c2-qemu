# SPDX-License-Identifier: MIT
"""Parent batch only: actual low mappings, mock original writer, source binder pins.

No VM, Sony SDK execution, network, hardware, SD, or encoded media is involved.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REPORT = ROOT / "report/functional-mpr-memory"
MODES = (
    "layout", "info", "fixed", "retention", "masks", "leases", "validation",
    "rollback", "collision", "map-error", "high-map", "root", "binding",
    "disabled", "fork", "sds-output", "sds-refusal", "sds-retirement",
    "sds-capacity", "sds-publication", "still-modes",
)
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            str(HERE / "test-functional-mpr-memory.c"), "-ldl", "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-mpr-memory") / "test-memory"
    subprocess.run(compile_command(output, sanitize=request.param), check=True,
                   timeout=60, capture_output=True, text=True)
    return output


@pytest.mark.parametrize("mode", MODES)
def test_actual_mapping_provider(executable, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), mode], env=env, timeout=20,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def loads(binary):
    assert binary[:6] == b"\x7fELF\x02\x01"
    phoff = struct.unpack_from("<Q", binary, 32)[0]
    entsize, count = struct.unpack_from("<HH", binary, 54)
    result = []
    for index in range(count):
        typ, flags, offset, va, _physical, filesz, memsz, _align = struct.unpack_from(
            "<IIQQQQQQ", binary, phoff + index * entsize)
        if typ == 1:
            result.append((offset, va, filesz, memsz, flags))
    return result


def file_window(binary, va, length):
    for offset, start, filesz, _memsz, _flags in loads(binary):
        if start <= va and length <= filesz - (va - start):
            actual = offset + va - start
            raw = binary[actual:actual + length]
            assert len(raw) == length
            return actual, raw
    raise ValueError(f"ELF VA {va:#x}+{length:#x} has no file-backed PT_LOAD")


def sections(binary):
    offset = struct.unpack_from("<Q", binary, 40)[0]
    entsize, count = struct.unpack_from("<HH", binary, 58)
    return [struct.unpack_from("<IIQQQQIIQQ", binary, offset + index * entsize)
            for index in range(count)]


def symbols(binary):
    section = sections(binary)
    dynsym = next(row for row in section if row[1] == 11)
    strings = section[dynsym[6]]
    names = binary[strings[4]:strings[4] + strings[5]]
    result = []
    for offset in range(dynsym[4], dynsym[4] + dynsym[5], dynsym[9]):
        name, info, other, shndx, va, size = struct.unpack_from("<IBBHQQ", binary, offset)
        end = names.find(b"\0", name)
        result.append((names[name:end].decode("ascii"), va, size, info, other, shndx))
    return result


def fnv1a(raw):
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"{value:016x}"


@pytest.fixture(scope="module")
def original():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    binary = (ROOT / pins["artifact"]["path"]).read_bytes()
    assert len(binary) == pins["artifact"]["size"]
    assert hashlib.sha256(binary).hexdigest() == pins["artifact"]["sha256"]
    return binary, pins


def test_original_source_binder(original):
    binary, pins = original
    source = (HERE / "functional-mpr-memory.c").read_text()
    for pin in pins["windows"]:
        offset, raw = file_window(binary, pin["elf_va"], pin["length"])
        assert offset == pin["file_offset"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], pin["name"]
        assert fnv1a(raw) == pin["fnv1a64"], pin["name"]
        if pin["name"] in pins["runtime_binder_windows"]:
            pattern = (rf"\{{0x{pin['elf_va']:x},\s*0x0*{pin['length']:x},\s*"
                       rf"UINT64_C\(0x{pin['fnv1a64']}\)\}}")
            assert re.search(pattern, source), pin["name"]
    actual = {name: (va, size) for name, va, size, *_ in symbols(binary)}
    for expected in pins["symbols"]:
        assert actual[expected["name"]] == (expected["elf_va"], expected["size"])
    # The actual variable is BSS. Treating its VA as a raw file offset fails.
    with pytest.raises(ValueError, match="no file-backed"):
        file_window(binary, 0x3D82F8, 8)
    # Exercise the nonidentity file/VA relation on the second LOAD as well.
    assert file_window(binary, 0x36B8A8, 16)[0] == 0x35B8A8
    assert "dlsym(RTLD_NEXT, symbol)" in source
    assert "__attribute__((constructor" not in source
    assert pins["capture_verified"] is False and pins["strict_gap_mask"] == 63
    assert pins["physical_asic_verified"] is False and pins["original_cp_verified"] is False


def test_original_plt_and_variable_relocations(original):
    binary, _pins = original
    syms = symbols(binary)
    relocations = {}
    for section in sections(binary):
        if section[1] != 4:
            continue
        for offset in range(section[4], section[4] + section[5], section[9]):
            target, info, addend = struct.unpack_from("<QQq", binary, offset)
            relocations[target] = (info & 0xFFFFFFFF, syms[info >> 32][0], addend)
    assert relocations[0x2FE780] == (
        1026, "_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE", 0)
    assert relocations[0x2FCC28] == (
        1025, "_ZN3mpr10DmmMemInfo19mp_AreaExtListStartE", 0)
    assert relocations[0x301830][1] == "_ZN3mpr10DmmMemInfo11GetUnitInfoEPvPjS2_S2_PmS2_"
    assert relocations[0x301DD0][1] == "_ZN3mpr10DmmMemInfo9SetMemTblEjiPNS0_11BufferTableE"
    call = struct.unpack("<I", file_window(binary, 0xD975C, 4)[1])[0]
    displacement = (call & 0x3FFFFFF) << 2
    if displacement & (1 << 27):
        displacement -= 1 << 28
    assert call >> 26 == 0b100101 and 0xD975C + displacement == 0x7BFC0
    assert file_window(binary, 0x7BFC0, 16)[1].hex() == "101400f011c243f910021e9120021fd6"


def test_original_default_table_covers_all_mandatory_stores(original):
    binary, _pins = original
    offsets = set()
    # Source stores are decoded directly, without running the AArch64 methods.
    for va, size in ((0x2B2D68, 0x20), (0x2B3048, 0x280)):
        raw = file_window(binary, va, size)[1]
        for (instruction,) in struct.iter_unpack("<I", raw):
            if (instruction >> 5) & 31 != 2:
                continue
            opcode = instruction & 0xFFC00000
            if opcode in (0xF9000000, 0xB9000000):
                scale = 8 if opcode == 0xF9000000 else 4
                offsets.add(((instruction >> 10) & 0xFFF) * scale)
            elif opcode == 0xA9000000:
                displacement = (instruction >> 15) & 127
                if displacement & 64:
                    displacement -= 128
                offsets.update((displacement * 8, displacement * 8 + 8))
    areas = (0, 0x20, 0x40, 0x60, 0x140, 0x160, 0x260, 0x280, 0x2A0,
             0x2C0, 0x300, 0x320, 0x640, 0x660, 0x680, 0x6A0, 0x6C0,
             0x6E0, 0x700, 0x720)
    assert offsets == {area + field for area in areas for field in (0, 8, 16, 24)}
    # The remaining bytes are deliberate software-disabled entries initialized
    # by this provider; no source physical allocation defaults are imported.
    raw = file_window(binary, 0x2E0ED8, 46)[1]
    jumps = struct.unpack("<23h", raw)
    assert 0x2B2CF8 + jumps[3] * 4 == 0x2B2D68
    assert 0x2B2CF8 + jumps[4] * 4 == 0x2B2D78
    assert 0x2B2CF8 + jumps[6] * 4 == 0x2B2E00
    choices = file_window(binary, 0x2E0EB4, 35)[1]
    missing = {mode for mode, relative in enumerate(struct.unpack("<35b", choices))
               if 0x2B275C + relative * 4 == 0x2B28D0}
    assert missing == {5, 0xD}
    assert [2 if (1 << t) & 0x78807 else 4 if (1 << t) & 0x7821C0
            else 1 if (1 << t) & 0x638 else 0 for t in (3, 4, 6)] == [1, 1, 4]


def test_production_compiles_and_exports_exact_original_abi(tmp_path):
    output = tmp_path / "memory.so"
    subprocess.run([*shlex.split(os.environ.get("CC", "cc")), *FLAGS,
                    "-fPIC", "-shared", str(HERE / "functional-mpr-memory.c"),
                    "-ldl", "-o", str(output)], check=True, timeout=60,
                   capture_output=True, text=True)
    completed = subprocess.run(["nm", "-g", "--defined-only", str(output)],
                               check=True, timeout=10, capture_output=True, text=True)
    names = {line.split()[-1] for line in completed.stdout.splitlines()}
    required = {
        "_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE",
        "_ZN3mpr10DmmMemInfo13FreeDmmMemoryEij",
        "_ZN3mpr10DmmMemInfo13FreeDmmMemoryEi",
        "_ZN3mpr10DmmMemInfo11GetUnitInfoEPvPjS2_S2_PmS2_",
        "_ZN3mpr6memory12GetFixedAreaENS0_13FixedAreaTypeEPPvS3_Pj",
    }
    assert {name for name in names if name.startswith("_ZN3mpr")} == required
    assert "functional_mpr_memory_enable" in names
    assert "functional_mpr_memory_shutdown" in names
    assert "functional_mpr_memory_acquire_sds" in names


def test_original_sds_output_producer(original):
    binary, pins = original
    contract = pins["sds_binding"]
    assert contract["producer_closed"] is True
    assert contract["schema"] == "type0_direct_unit_handle"
    assets = {"M": binary}
    for key, artifact in contract["assets"].items():
        raw = (ROOT / artifact["path"]).read_bytes()
        assert len(raw) == artifact["size"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        assets[key] = raw
    for pin in contract["windows"]:
        offset, raw = file_window(assets[pin["asset"]], pin["elf_va"], pin["length"])
        assert offset == pin["file_offset"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], pin["name"]

    def words(key, va, *expected):
        raw = file_window(assets[key], va, len(expected) * 4)[1]
        assert struct.unpack(f"<{len(expected)}I", raw) == expected, (key, hex(va))

    # Original node producer keeps the unit and area separate, never packed.
    words("M", 0x2B26A0, 0xB9000B63, 0xB9000F60)
    words("M", 0x2B2B9C, 0xB94008C9, 0xB9000029, 0xB9400CC1, 0xB9000041)
    # GetUnitInfo: x1=unit@sp48, x2=area@sp44, x3=offset@sp4c.
    words("M", 0xCEE7C, 0x910143A4, 0x910133A3, 0x910113A2, 0x910123A1)
    words("M", 0xCEF04, 0x294903A2)  # w2=unit, w0=offset; area is unused
    words("M", 0xCEF18, 0x290A8662)  # config54=unit, config58=position
    words("M", 0xCEF40, 0x290B8A63)  # config5c=capacity, config60=same unit
    # Without_Pin copies that unit unchanged into a type0 output SDS at p28.
    words("I", 0x11B260, 0xB900267F)
    words("I", 0x11B268, 0xB94056A0, 0xB9405EA1, 0x29057E60, 0xB9405AA0)
    words("I", 0x11B27C, 0x29070660, 0x0B010000, 0xB9003660)
    words("I", 0x11B35C, 0xB94062A0, 0xB9406AA1, 0x29057E60, 0xB94066A0,
          0x29070660, 0x0B010000, 0xB9003660)
    # ParameterControl's actual typed set/get methods, rather than guessed slots.
    syms = symbols(assets["I"])
    relocations = {}
    for section in sections(assets["I"]):
        if section[1] != 4:
            continue
        for offset in range(section[4], section[4] + section[5], section[9]):
            target, info, addend = struct.unpack_from("<QQq", assets["I"], offset)
            relocations[target] = (info & 0xFFFFFFFF, syms[info >> 32][0], addend)
    for relocation in contract["parameter_control_relocations"]:
        assert relocations[relocation["elf_va"]] == (257, relocation["symbol"], 0)
    mode_table = file_window(binary, 0x2CE548, 15)[1]
    assert set(mode_table) == set(range(0x13, 0x23)) - {0x14}
    words("M", 0xCEDD8, 0x38F36813)
    words("M", 0xCEE24, 0x52800213)  # fallback mode0x10
    assert not ({6, 0x11} & set(mode_table))


def test_aarch64_original_libc_225_link_and_imports(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires already-installed clang/lld and AArch64 readelf")
    output = tmp_path / "memory-aarch64.so"
    library = HERE / "menu-root/lib"
    subprocess.run([compiler, "--target=aarch64-linux-gnu", "-fuse-ld=lld",
                    "-nostdlib", "-O2", "-mno-outline-atomics", "-std=c11",
                    "-Wall", "-Wextra", "-Werror", "-pedantic", "-shared", "-fPIC",
                    "-isystem", "/usr/aarch64-linux-gnu/include", "-Wl,--no-undefined",
                    str(HERE / "functional-mpr-memory.c"),
                    *(str(library / name) for name in ("libc-2.25.so", "libdl-2.25.so",
                      "libpthread-2.25.so", "ld-2.25.so")), "-o", str(output)],
                   check=True, timeout=60, capture_output=True, text=True)
    imported = subprocess.run([reader, "--dyn-syms", "-W", str(output)],
                              check=True, timeout=10, capture_output=True, text=True).stdout
    assert "__isoc99_sscanf@GLIBC_2.17" in imported
    assert "__isoc23" not in imported and "__aarch64_" not in imported
    assert "functional_mpr_memory_acquire_sds" in imported
    versions = subprocess.run([reader, "--version-info", "-W", str(output)],
                              check=True, timeout=10, capture_output=True, text=True).stdout
    assert set(re.findall(r"Name: (GLIBC_\d+\.\d+)", versions)) == {"GLIBC_2.17"}
