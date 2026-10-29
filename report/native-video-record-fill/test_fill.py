"""HOST_TEST source S88 bytes + original 011c values; no native IO or VM."""
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
MODES = ("mapping", "matrix", "arguments", "alias", "plan", "paramsets", "composed")
STRICT = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def fill_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-video-record-fill") / "selfcheck"
    command = STRICT + ["-ffunction-sections", "-fdata-sections"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command += [str(HERE / "native-fill.c"), str(HERE / "test-native-fill.c")]
    command += [str(HERE.parent / path) for path in (
        "native-video-producer-contract/native-producer.c", "native-video-binding/native-video.c",
        "native-video-au-contract/native-au.c", "native-video-paramsets/native-paramsets.c",
        "native-video-ring-contract/native-ring.c", "native-video-length-format/native-lengths.c")]
    command += ["-Wl,--gc-sections", "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return exe


@pytest.mark.parametrize("mode", MODES)
def test_fill_contract(fill_exe, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(fill_exe), mode], capture_output=True, text=True,
                            env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
    assert result.stdout == "HOST_TEST actual S88 fill and pure original 011c plan passed\n"
    assert not result.stderr


def test_all_modes_with_original_aarch64_libc(tmp_path):
    root = HERE.parents[1]
    guest = root/'runtime/analysis/menu-root'
    qemu = root/'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not shutil.which('clang') or not qemu.is_file():
        pytest.skip('original-libc execution needs clang and prepared QEMU user mode')
    exe = tmp_path/'fill-original-libc'
    sources = [HERE.parent/'lif-capability-owner/original-abi-entry.c',
               HERE/'native-fill.c', HERE/'test-native-fill.c']
    sources += [HERE.parent/path for path in ('native-video-producer-contract/native-producer.c',
        'native-video-binding/native-video.c', 'native-video-au-contract/native-au.c',
        'native-video-paramsets/native-paramsets.c', 'native-video-ring-contract/native-ring.c',
        'native-video-length-format/native-lengths.c')]
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
        assert result.stdout == 'HOST_TEST actual S88 fill and pure original 011c plan passed\n'
        assert not result.stderr, mode


class Record(C.Structure):
    _fields_ = [("wire", C.c_uint8 * 88), ("semantic_written_bits", C.c_uint8 * 88)]


class Plan(C.Structure):
    _fields_ = [("record_address", C.c_uint64), ("index", C.c_uint32),
                ("next_index", C.c_uint32), ("destination", C.c_uint32),
                ("wire", C.c_uint8 * 24)]


@pytest.fixture(scope="session")
def fill_lib(tmp_path_factory):
    libpath = tmp_path_factory.mktemp("native-video-record-fill-library") / "fill.so"
    result = subprocess.run(STRICT + ["-shared", "-fPIC", str(HERE / "native-fill.c"),
        "-o", str(libpath)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    lib = C.CDLL(str(libpath), use_errno=True)
    bytep = C.POINTER(C.c_uint8)
    lib.nfill_assemble.argtypes = [bytep, C.c_size_t, C.c_uint32, C.c_uint32,
        bytep, C.c_size_t, bytep, C.c_size_t, C.POINTER(Record), C.c_size_t]
    lib.nfill_assemble.restype = C.c_int
    lib.nfill_plan_notify.argtypes = [C.c_uint32] * 6 + [C.c_uint64, C.POINTER(Plan), C.c_size_t]
    lib.nfill_plan_notify.restype = C.c_int
    return lib


def explicit_fixture():
    work = bytearray([0xf3] * 0xe90)
    work[8] = 3
    work[0x5b0:0x5e4] = bytes(range(0x10, 0x44))
    work[0x5e4:0x618] = bytes(range(0x90, 0xc4))
    struct.pack_into("<H", work, 0x5b0 + 0x28, 0x17c6)
    struct.pack_into("<I", work, 0x5b0 + 0x10, 0xffffffff)
    struct.pack_into("<II", work, 0x618, 0x89abcdef, 0x01234567)
    for j, length in enumerate((1, 0x123, 7)):
        struct.pack_into("<I", work, 0x620 + j * 0x10 + 8, length)
        work[0x620 + j * 0x10 + 0xc] = 0x80 if j == 2 else 0
        work[0x620 + j * 0x10 + 0xd] = j & 1
    struct.pack_into("<Q", work, 0xbc0, 0xfedcba9876540001)
    struct.pack_into("<Q", work, 0xbc0 + 16, 0x1111222233334444)
    return ((C.c_uint8 * len(work)).from_buffer_copy(work),
            (C.c_uint8 * 24)(*range(0xa0, 0xb8)),
            (C.c_uint8 * 88)(*range(88)))


def test_independent_literal_wire_and_mask(fill_lib):
    work, node, baseline = explicit_fixture()
    before = bytes(work), bytes(node), bytes(baseline)
    out = Record()
    C.set_errno(731)
    assert fill_lib.nfill_assemble(work, len(work), 0, 2, node, 24, baseline, 88,
                                  C.byref(out), C.sizeof(out)) == 0
    assert C.get_errno() == 731
    expected = bytes.fromhex(
        "0100547698badcfe2b01000000000f01"
        "14151617101112131c1d1e1f18191a1b"
        "ffffffffffffffff28292a2b24252627"
        "3435302c2d0e363732332e2fefcdab89"
        "67452301a8a9aaabacadaeafb0b1b2b3"
        "0000000054555657")
    assert len(expected) == 88
    assert bytes(out.wire) == expected
    assert bytes(out.semantic_written_bits) == b"\xff" * 84 + b"\0" * 4
    assert (bytes(work), bytes(node), bytes(baseline)) == before


def test_second_metadata_and_explicit_baseline(fill_lib):
    work, node, baseline = explicit_fixture()
    work[0x620 + 2 * 0x10 + 0xd] = 1
    # Supply D1's exact source fields independently of D0.
    work[0x5e4 + 0x28], work[0x5e4 + 0x29] = 0x40, 0
    struct.pack_into("<I", work, 0x5e4 + 0x10, 0x7fffffff)
    work[8] = 2
    out = Record()
    assert fill_lib.nfill_assemble(work, len(work), 0, 2, node, 24, baseline, 88,
                                  C.byref(out), C.sizeof(out)) == 0
    assert bytes(out.wire[0x10:0x20]) == bytes.fromhex("94959697909192939c9d9e9f98999a9b")
    assert bytes(out.wire[0x20:0x30]) == bytes.fromhex("ffffff7f00000000a8a9aaaba4a5a6a7")
    assert out.wire[0x0e] == 1 and out.wire[0x35] == 0x80
    assert bytes(out.wire[0x50:]) == bytes.fromhex("b4b5b6b754555657")
    baseline[0x54:0x58] = [0xa5, 0, 0xff, 0x5a]
    assert fill_lib.nfill_assemble(work, len(work), 0, 2, node, 24, baseline, 88,
                                  C.byref(out), C.sizeof(out)) == 0
    assert bytes(out.wire[0x54:]) == b"\xa5\0\xff\x5a"
    assert bytes(out.semantic_written_bits[0x54:]) == bytes(4)


def test_original_index_and_full_u64_notify_plan(fill_lib):
    out = Plan()
    C.set_errno(731)
    assert fill_lib.nfill_plan_notify(0x80000000, 0x80000002, 0x11223344,
        0xfedcba98, 0x12345678, 0x9abcdef0, 0x1234000000000000,
        C.byref(out), C.sizeof(out)) == 0
    assert C.get_errno() == 731
    assert out.record_address == 0x1234002c00000000
    assert out.index == 0x80000000 and out.next_index == 0x80000001
    assert out.destination == 0x11223344
    assert bytes(out.wire) == bytes.fromhex(
        "03211c011800000098badcfe0000008078563412f0debc9a")


def test_completed_public_source3cd_pins():
    pins = json.loads((HERE / "source-pins.json").read_text())
    artifact = pins["artifact"]
    data = (HERE / pins["source_root"] / artifact["path"]).read_bytes()
    assert len(data) == artifact["size"] == 13797088
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    assert pins["native_capture"] is False and pins["native_gaps"] == 63
    assert pins["engine_input_closed"] is False and pins["actual_notification_sent"] is False
    assert len(pins["windows"]) == pins["window_count"] == 12
    assert sum(pin["length_bytes"] for pin in pins["windows"]) == pins["total_window_bytes"] == 5348
    for pin in pins["windows"]:
        offset, length = int(pin["file_offset"], 16), pin["length_bytes"]
        assert 0 <= offset < offset + length <= len(data)
        assert hashlib.sha256(data[offset:offset + length]).hexdigest() == pin["sha256"], pin["id"]
