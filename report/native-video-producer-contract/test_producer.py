"""HOST_TEST finite source124 metadata production; no native capture or IO."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = ("mapping", "matrix", "arguments", "alias", "plan", "existing", "composed")
STRICT = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def producer_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-video-producer-contract") / "selfcheck"
    command = STRICT + ["-ffunction-sections", "-fdata-sections"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    # Actual pure consumers; discard unrelated encoder functions, without stubs/libav.
    command += [str(HERE / "native-producer.c"), str(HERE / "test-native-producer.c")]
    command += [str(HERE.parent / path) for path in (
        "native-video-binding/native-video.c", "native-video-au-contract/native-au.c",
        "native-video-paramsets/native-paramsets.c", "native-video-ring-contract/native-ring.c",
        "native-video-length-format/native-lengths.c")]
    command += ["-Wl,--gc-sections", "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return exe


@pytest.mark.parametrize("mode", MODES)
def test_producer_contract(producer_exe, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(producer_exe), mode], capture_output=True,
                            text=True, env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
    assert result.stdout == "HOST_TEST producer metadata and pure publication plan passed\n"


def test_all_modes_with_original_aarch64_libc(tmp_path):
    root = HERE.parents[1]
    guest = root/'runtime/analysis/menu-root'
    qemu = root/'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not shutil.which('clang') or not qemu.is_file():
        pytest.skip('original-libc execution needs clang and prepared QEMU user mode')
    exe = tmp_path/'producer-original-libc'
    sources = [HERE.parent/'lif-capability-owner/original-abi-entry.c',
               HERE/'native-producer.c', HERE/'test-native-producer.c']
    sources += [HERE.parent/path for path in ('native-video-binding/native-video.c',
        'native-video-au-contract/native-au.c', 'native-video-paramsets/native-paramsets.c',
        'native-video-ring-contract/native-ring.c', 'native-video-length-format/native-lengths.c')]
    libraries = [guest/'lib'/name for name in ('libc-2.25.so', 'libdl-2.25.so',
        'libpthread-2.25.so', 'ld-2.25.so')]
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib',
        '-O2', '-mno-outline-atomics', '-ffunction-sections', '-fdata-sections',
        '-Wall', '-Wextra', '-Werror', '-pedantic', '-Wl,--no-undefined', '-Wl,--gc-sections',
        '-isystem', '/usr/aarch64-linux-gnu/include', '-Wl,-e,_start',
        '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
        *(str(p) for p in sources + libraries), '-o', str(exe)],
        check=True, capture_output=True, text=True, timeout=30)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_', 'LD_'))}
    for mode in MODES:
        result = subprocess.run([str(qemu), '-L', str(guest), str(exe), mode],
            check=True, capture_output=True, text=True, env=env, timeout=30)
        assert result.stdout == 'HOST_TEST producer metadata and pure publication plan passed\n'
        assert not result.stderr, mode


class Record(C.Structure):
    _fields_ = [("wire", C.c_uint8 * 96), ("semantic_written_bits", C.c_uint8 * 96)]


@pytest.fixture(scope="session")
def producer_lib(tmp_path_factory):
    libpath = tmp_path_factory.mktemp("native-video-producer-library") / "producer.so"
    result = subprocess.run(STRICT + ["-shared", "-fPIC", str(HERE / "native-producer.c"),
                                     "-o", str(libpath)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    lib = C.CDLL(str(libpath), use_errno=True)
    lib.nproducer_convert.argtypes = [C.POINTER(C.c_uint8), C.c_size_t,
        C.c_uint8, C.c_uint8, C.c_uint8, C.c_uint32,
        C.POINTER(C.c_uint8), C.c_size_t, C.POINTER(Record), C.c_size_t]
    lib.nproducer_convert.restype = C.c_int
    return lib


def test_independent_literal_wire_and_mask(producer_lib):
    source = (C.c_uint8 * 88)(*range(1, 89))
    baseline = (C.c_uint8 * 96)(*range(96))
    out = Record()
    C.set_errno(731)
    assert producer_lib.nproducer_convert(source, 88, 0x80, 0, 1, 0xabcdef12,
                                          baseline, 96, C.byref(out), C.sizeof(out)) == 0
    assert C.get_errno() == 731
    # Independent full-wire fixture with a different baseline from the C fixture.
    expected = bytes.fromhex(
        "04030d82040506070102030405060708"
        "090a0b0c141516171112131415161718"
        "191a1b1c1d1e1f203b3c3534393a0113"
        "3738323151525354446484a43c3d3e3f"
        "4041424347454647494a4b4c4d4e4f50"
        "3d3e3f40414243440059ffff5c5d5e5f")
    mask = bytes.fromhex(
        "ff07ff0100000000ffffffffffffffff"
        "ffffffff00000000ffffffffffffffff"
        "ffffffffffffffffffffffffffffffff"
        "ffffffffffffffffffffffff00000000"
        "0000000003000000ffffffffffffffff"
        "ffffffffffffffffff00ffff00000000")
    assert bytes(out.wire) == expected
    assert bytes(out.semantic_written_bits) == mask
    assert bytes(source) == bytes(range(1, 89))
    assert bytes(baseline) == bytes(range(96))
    assert out.wire[3] & ~mask[3] != baseline[3] & ~mask[3]


def test_explicit_zero_caller_baseline_is_separate(producer_lib):
    source = (C.c_uint8 * 88)(*range(1, 89))
    source[0x0e] = 0
    poison = (C.c_uint8 * 96)(*[0xa5] * 96)
    zero = (C.c_uint8 * 96)()  # An explicit HOST caller clear, not an ABI default.
    a, b = Record(), Record()
    for baseline, out in ((poison, a), (zero, b)):
        assert producer_lib.nproducer_convert(source, 88, 0x80, 0x80, 1, 0x10059,
            baseline, 96, C.byref(out), C.sizeof(out)) == 0
    assert bytes(a.semantic_written_bits) == bytes(b.semantic_written_bits)
    assert a.semantic_written_bits[2] == 0 and a.wire[2] == 0xa5 and b.wire[2] == 0
    assert bytes(a.wire[0x3c:0x44]) == b"\xa5" * 8
    assert bytes(b.wire[0x3c:0x44]) == bytes(8)
    assert b.wire[3] == 0x80 and b.semantic_written_bits[3] == 1
    assert bytes(b.wire[0x5a:0x5c]) == b"\x59\x00"  # u32 -> u16, not range rejection.
    assert bytes(a.wire[0x5c:]) == b"\xa5" * 4
    assert bytes(b.wire[0x5c:]) == bytes(4)


def _branch_target(data, offset):
    instruction = struct.unpack_from("<I", data, offset)[0]
    assert instruction >> 26 == 0b100101  # AArch64 BL.
    immediate = instruction & ((1 << 26) - 1)
    if immediate & (1 << 25):
        immediate -= 1 << 26
    return offset + immediate * 4


def test_completed_public_source124_pins():
    pins = json.loads((HERE / "source-pins.json").read_text())
    artifact = pins["artifact"]
    data = (HERE / pins["source_root"] / artifact["path"]).read_bytes()
    assert len(data) == artifact["size"] == 13797088
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    assert pins["native_capture"] is False and pins["native_gaps"] == 63
    assert len(pins["windows"]) == pins["window_count"] == 8
    assert sum(int(p["length"], 16) for p in pins["windows"]) == pins["total_window_bytes"] == 2248
    for pin in pins["windows"]:
        offset, length = int(pin["file_offset"], 16), int(pin["length"], 16)
        assert 0 <= offset < offset + length <= len(data)
        assert hashlib.sha256(data[offset:offset + length]).hexdigest() == pin["sha256"], pin["id"]
    for check in pins["instruction_checks"]:
        offset = int(check["file_offset"], 16)
        assert data[offset:offset + 4].hex() == check["bytes_le"]
        if "branch_target" in check:
            assert _branch_target(data, offset) == int(check["branch_target"], 16)
    assert data[0x1609c8:0x1609cc].hex() == "c0035fd6"
    assert _branch_target(data, 0x160670) == 0x279e64
    assert pins["caller_baseline_event"]["length"] == 96
    assert pins["caller_baseline_event"]["value"] == 0
