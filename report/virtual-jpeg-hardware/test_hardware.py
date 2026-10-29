"""Isolated host C tests and public source pins; no VM, network or media files."""
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shlex
import subprocess

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT.parent.parent / "runtime/analysis/menu-root/system/av-cam.bin"


class Coding(ctypes.Structure):
    _fields_ = [("contract", ctypes.c_int), ("width", ctypes.c_uint32),
                ("height", ctypes.c_uint32), ("quant", (ctypes.c_uint8 * 64) * 2)]


class AIF(ctypes.Structure):
    _fields_ = [("high", ctypes.c_uint32), ("low", ctypes.c_uint32)]


class Output(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint64), ("aligned", ctypes.c_uint64),
                ("aif", AIF), ("skip", ctypes.c_uint16),
                ("dma_capacity", ctypes.c_uint32), ("threshold", ctypes.c_uint32)]


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    dest = tmp_path_factory.mktemp("virtual-jpeg-hardware")
    cc = shlex.split(os.environ.get("CC", "cc"))
    flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libjpeg"], text=True))
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    sources = [str(ROOT / "jpeg-hardware.c"), str(ROOT / "jpeg-hardware-codec.c"),
               str(ROOT.parent / "virtual-jpeg-sos/jpeg-sos.c")]
    for name, options in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        subprocess.run(cc + strict + options + sources +
                       [str(ROOT / "test-hardware.c"), "-o", str(dest / name)] +
                       flags, check=True)
    shared = dest / "hardware.so"
    subprocess.run(cc + strict + ["-O2", "-fPIC", "-shared"] + sources +
                   ["-o", str(shared)] + flags, check=True)
    lib = ctypes.CDLL(str(shared))
    lib.vjpeg_source_prefix.argtypes = [ctypes.POINTER(Coding), ctypes.c_void_p]
    lib.vjpeg_source_prefix.restype = ctypes.c_int
    lib.vjpeg_source_address.argtypes = [ctypes.c_uint64] + [ctypes.c_uint32] * 5 + [
        ctypes.POINTER(ctypes.c_uint64)]
    lib.vjpeg_source_address.restype = ctypes.c_int
    lib.vjpeg_phys_to_aif.argtypes = [ctypes.c_uint64, ctypes.POINTER(AIF)]
    lib.vjpeg_phys_to_aif.restype = ctypes.c_int
    lib.vjpeg_aif_to_phys.argtypes = [AIF, ctypes.c_size_t,
                                    ctypes.POINTER(ctypes.c_uint64)]
    lib.vjpeg_aif_to_phys.restype = ctypes.c_int
    lib.vjpeg_output_layout.argtypes = [ctypes.c_uint64, ctypes.c_uint32,
                                       ctypes.c_uint32, ctypes.POINTER(Output)]
    lib.vjpeg_output_layout.restype = ctypes.c_int
    return dest, lib


@pytest.mark.parametrize("name", ["normal", "sanitized"])
def test_c_device_selftests(builds, name):
    dest, _ = builds
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(dest / name)], env=env, capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "6 device self-test groups passed\n"


def encoded(builds, option):
    dest, _ = builds
    result = subprocess.run([str(dest / "normal"), option],
                            capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
    return result.stdout


def controls(payload):
    assert payload[:2] == b"\xff\xd8"
    p, segments = 2, []
    while True:
        assert payload[p] == 0xFF
        marker = payload[p + 1]
        n = int.from_bytes(payload[p + 2:p + 4], "big")
        assert n >= 2 and p + 2 + n <= len(payload)
        if marker == 0xDA:
            assert p == 0x23D + 2
            assert payload[p:p + 2] == b"\xff\xda"
            assert payload[-2:] == b"\xff\xd9"
            return segments
        segments.append((marker, payload[p + 4:p + 2 + n]))
        p += 2 + n


def expected_pixels(invert=False):
    pixels = bytes(c for y in range(21) for x in range(33) for c in
                   (32 + 160 * x // 33, 32 + 160 * y // 21,
                    48 + 100 * (x + y) // 54))
    return bytes(255 - c for c in pixels) if invert else pixels


@pytest.mark.parametrize("option,invert,varied", [
    ("--jpeg", False, False), ("--jpeg-invert", True, False),
    ("--jpeg-tables", False, True),
])
def test_actual_source_profile_pillow_decode(builds, option, invert, varied):
    payload = encoded(builds, option)
    segments = controls(payload)
    assert [m for m, _ in segments] == [0xDB, 0xC4, 0xC0]
    q = segments[0][1]
    assert len(q) == 130 and q[0] == 0 and q[65] == 1
    for t in range(2):
        assert q[t * 65 + 1:(t + 1) * 65] == bytes(
            1 + (i * 3 + t * 7) % 17 if varied else 2 for i in range(64))
    sof = segments[2][1]
    assert sof == bytes([8, 0, 21, 0, 33, 3, 1, 0x21, 0, 2, 0x11, 1, 3, 0x11, 1])
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "JPEG" and image.mode == "RGB" and image.size == (33, 21)
        image.load()
        errors = [abs(a - b) for a, b in zip(image.tobytes(), expected_pixels(invert),
                                            strict=True)]
    assert max(errors) <= 12 and sum(errors) / len(errors) < 3


def test_actual_pixels_and_quantization_change_output(builds):
    payloads = [encoded(builds, o) for o in
                ("--jpeg", "--jpeg-invert", "--jpeg-tables")]
    assert len(set(payloads)) == 3
    assert payloads[0][575:] != payloads[1][575:] != payloads[2][575:]


def test_public_source_pins_and_immutable_prefix(builds):
    _, lib = builds
    pins = json.loads((ROOT / "source-pins.json").read_text())
    binary = PUBLIC.read_bytes()
    assert len(binary) == pins["asset"]["size"]
    assert hashlib.sha256(binary).hexdigest() == pins["asset"]["sha256"]
    for pin in pins["pins"]:
        lo, n = pin["raw_offset"], pin["size"]
        assert lo >= 0 and n > 0 and lo <= len(binary) - n
        assert hashlib.sha256(binary[lo:lo + n]).hexdigest() == pin["sha256"], pin["label"]
    for pin in pins["instructions"]:
        lo, raw = pin["raw_offset"], bytes.fromhex(pin["bytes"])
        assert binary[lo:lo + len(raw)] == raw
    c = Coding(1, 33, 21)
    for t in range(2):
        for i in range(64): c.quant[t][i] = 1 + (i * 3 + t * 7) % 17
    out = (ctypes.c_uint8 * 575)()
    assert lib.vjpeg_source_prefix(ctypes.byref(c), out) == 0
    prefix = bytes(out)
    # Prefix bytes derive from original table addresses, not libjpeg headers.
    huff = binary[0x4512ED:0x45130A] + binary[0x451327:0x4513DA] + \
        binary[0x45130A:0x451327] + binary[0x4513DA:0x45148D]
    assert prefix[140:556] == huff
    sof = bytearray(binary[0x30A0C0:0x30A0D1])
    sof[3:7] = b"\x00\x15\x00\x21"
    sof[9] = 0x21
    assert prefix[558:] == sof


def test_source_arithmetic_against_independent_integers(builds):
    _, lib = builds
    rng = random.Random(29)
    for _ in range(200):
        base = rng.randrange(1 << 30)
        canvas = rng.randrange(1, 65536)
        vx, vy, tx, ty = [rng.randrange(65536) for _ in range(4)]
        address = ctypes.c_uint64()
        assert lib.vjpeg_source_address(base, canvas, vx, vy, tx, ty,
                                       ctypes.byref(address)) == 0
        assert address.value == base + 2 * ((vy + ty) * canvas + vx + tx)
        offset, cap = rng.randrange(1024), rng.randrange(0x800, 0x100000)
        layout = Output()
        assert lib.vjpeg_output_layout(base, offset, cap, ctypes.byref(layout)) == 0
        effective = base + offset + 0x23D
        aligned = effective & ~15
        assert (layout.effective, layout.aligned, layout.skip) == (
            effective, aligned, effective - aligned)
        assert layout.dma_capacity == (base - aligned + offset + cap) & 0xFFFFFFF0
        assert layout.threshold == cap - 0x63D
        aif = AIF()
        assert lib.vjpeg_phys_to_aif(base, ctypes.byref(aif)) == 0
        assert aif.high == ((base + 0x400000000) >> 24) & 0xFFFFFF00
        assert aif.low == base
        physical = ctypes.c_uint64()
        assert lib.vjpeg_aif_to_phys(aif, 1, ctypes.byref(physical)) == 0
        assert physical.value == base
