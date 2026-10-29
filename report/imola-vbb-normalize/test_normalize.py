"""HOST_TEST numeric bytes only; source verification and existing user-mode ABI runner."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODES = ("vectors", "matrix", "arguments", "alias", "unaligned", "composed")
MESSAGE = "HOST_TEST owned VBB numeric normalization passed\n"
STRICT = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def normalize_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("imola-vbb-normalize") / "selfcheck"
    command = STRICT.copy()
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    result = subprocess.run(command + [str(HERE / "vbb-normalize.c"),
        str(HERE / "test-vbb-normalize.c"), "-o", str(exe)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return exe


@pytest.mark.parametrize("mode", MODES)
def test_normalize_contract(normalize_exe, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(normalize_exe), mode], capture_output=True,
                            text=True, env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
    assert result.stdout == MESSAGE
    assert not result.stderr


def test_all_modes_with_original_aarch64_libc(tmp_path):
    guest = ROOT / "runtime/analysis/menu-root"
    qemu = ROOT / "runtime/sources/qemu-11.1.2/build-user/qemu-aarch64"
    if not shutil.which("clang") or not qemu.is_file():
        pytest.skip("original-libc execution needs clang and prepared QEMU user mode")
    exe = tmp_path / "vbb-normalize-original-libc"
    sources = [HERE.parent / "lif-capability-owner/original-abi-entry.c",
               HERE / "vbb-normalize.c", HERE / "test-vbb-normalize.c"]
    libraries = [guest / "lib" / name for name in
                 ("libc-2.25.so", "libdl-2.25.so", "libpthread-2.25.so", "ld-2.25.so")]
    subprocess.run(["clang", "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib",
        "-std=c11", "-O2", "-mno-outline-atomics", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-Wl,--no-undefined", "-isystem", "/usr/aarch64-linux-gnu/include", "-Wl,-e,_start",
        "-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1",
        *(str(p) for p in sources + libraries), "-o", str(exe)],
        check=True, capture_output=True, text=True, timeout=30)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MENU_", "QEMU_", "SONY_", "A7C2_", "LD_"))}
    for mode in MODES:
        result = subprocess.run([str(qemu), "-L", str(guest), str(exe), mode],
            capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
        assert result.stdout == MESSAGE
        assert not result.stderr, mode


@pytest.fixture(scope="session")
def authenticated_source():
    pins = json.loads((HERE / "source-pins.json").read_text())
    source_root = (HERE / pins["source_root"]).resolve()
    reader_path = source_root / pins["authenticated_reader"]["path"]
    assert hashlib.sha256(reader_path.read_bytes()).hexdigest() == pins["authenticated_reader"]["sha256"]
    spec = importlib.util.spec_from_file_location("vbb_authenticated_image", reader_path)
    image = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(image)
    data = image.load_image(source_root / pins["artifact"])
    return pins, image, data


def test_authenticated_pins_and_raw_control_flow(authenticated_source):
    pins, image, data = authenticated_source
    assert len(data) == pins["bytes"] == 10934476
    assert hashlib.sha256(data).hexdigest() == pins["sha256"]
    assert len(pins["windows"]) == pins["window_count"] == 4
    assert sum(p["bytes"] for p in pins["windows"]) == pins["window_bytes"] == 604
    assert pins["native_gaps"] == 63 and pins["native_capture"] is False
    for name in ("source_pixel_format_closed", "hardware_backend_field_roles_closed",
                 "actual_CMOS_producer_closed", "MCU_executed", "registers_programmed",
                 "engine_started", "ACK_sent", "IRQ_raised", "engine_completed", "capture_verified"):
        assert pins[name] is False
    for pin in pins["windows"]:
        va, raw, length = int(pin["VA_hex"], 16), int(pin["raw_hex"], 16), pin["bytes"]
        assert pin["bank"] == "ram0" and 0x9000 <= raw < raw + length <= 0x714000
        assert va == 0x80000000 + raw
        window = image.read_window(data, "ram0", va, length)
        assert hashlib.sha256(window).hexdigest() == pin["sha256"], pin["name"]
    for fn, length in zip(pins["functions"], (320, 96)):
        va = int(fn["VA_hex"], 16)
        assert fn["bytes"] == length == int(fn["end_exclusive_hex"], 16) - va
        window = image.read_window(data, "ram0", va, length)
        assert hashlib.sha256(window).hexdigest() == fn["sha256"]
        assert fn["instructions"] * 4 == length

    def word(va):
        return struct.unpack("<I", image.read_window(data, "ram0", va, 4))[0]

    anchors = {
        0x801bfda8: 0x8c860018, 0x801bfdb0: 0x00461023, 0x801bfdb4: 0xace20000,
        0x801bfdb8: 0x30a600ff, 0x801bfdc4: 0x00621823, 0x801bfdcc: 0xace30004,
        0x801bfe08: 0x03e00008, 0x801bfe0c: 0x27bd0020,
        0x801bfe1c: 0x00640019, 0x801bfe24: 0x00001810,
        0x801bfe70: 0x246301ff, 0x801bfed0: 0x0806ff7f, 0x801bfed4: 0x00021040,
        0x801bfee8: 0x1060000e, 0x801bfeec: 0x30a800ff,
        0x801bff28: 0x03e00008, 0x801bff2c: 0x27bd0020,
        0x801bff30: 0x0806ffc9, 0x801bff34: 0xad230008,
        0x801c2398: 0x8c620018, 0x801c239c: 0x0040f809,
        0x801c23c4: 0x0040f809, 0x801c23c8: 0x24a5004c,
    }
    for va, expected in anchors.items():
        assert word(va) == expected, hex(va)
    table = struct.unpack("<16I", image.read_window(data, "ram0", 0x80216260, 64))
    assert table == (0x801bfe04, 0x801bfe04, 0x801bfdec, 0x801bfe10,
        0x801bfe4c, 0x801bfe4c, 0x801bfec4, 0x801bfec4, 0x801bfea0,
        0x801bfe04, 0x801bfea0, 0x801bfea0, 0x801bfea0, 0x801bfe4c,
        0x801bfea0, 0x801bfec4)
    binding = struct.unpack("<11I", image.read_window(data, "ram0", 0x801be400, 44))
    assert binding == (0x9205001c, 0x02002021, 0x0c06ff66, 0x02203021,
        0x9205001d, 0x02203021, 0x0c06ffb6, 0x02002021,
        0x02002021, 0x0c06ffce, 0x02202821)


def test_complete_normalizers_decode_as_ordinary_mips32(authenticated_source):
    pins, image, data = authenticated_source
    capstone = pytest.importorskip("capstone", reason="static decoder is optional outside the prepared lab")
    decoder = capstone.Cs(capstone.CS_ARCH_MIPS,
                         capstone.CS_MODE_MIPS32 | capstone.CS_MODE_LITTLE_ENDIAN)
    ordinary = {"addiu", "sw", "move", "lw", "subu", "andi", "sltiu", "beqz", "lui",
                "sll", "addu", "jr", "nop", "srl", "ori", "multu", "mfhi", "j", "jal", "beq"}
    for fn in pins["functions"]:
        va, length = int(fn["VA_hex"], 16), fn["bytes"]
        window = image.read_window(data, "ram0", va, length)
        instructions = list(decoder.disasm(window, va))
        assert len(instructions) == fn["instructions"]
        assert sum(i.size for i in instructions) == length
        assert all(i.size == 4 and i.mnemonic in ordinary for i in instructions)
        assert instructions[-1].address + 4 == int(fn["end_exclusive_hex"], 16)
