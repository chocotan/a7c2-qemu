"""Host memory component checks; no camera, VM, network, or media files."""

import ctypes
import io
import os
from pathlib import Path
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parent
GUARD = 16
OK, OUTPUT_TOO_SMALL = 0, 3


class Result(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int), ("used", ctypes.c_size_t)]


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("host-jpeg-engine")
    compiler = shlex.split(os.environ.get("CC", "cc"))
    library_flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libjpeg"], text=True
    ))
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    engine = str(ROOT / "jpeg-engine.c")
    test = str(ROOT / "test-jpeg-engine.c")
    for name, flags in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        subprocess.run(compiler + strict + flags + [engine, test, "-o",
                       str(directory / name)] + library_flags, check=True)
    shared = directory / "libjpeg-engine.so"
    subprocess.run(compiler + strict + ["-O2", "-fPIC", "-shared", engine,
                   "-o", str(shared)] + library_flags, check=True)
    library = ctypes.CDLL(str(shared))
    function = library.jpeg_engine_encode_rgb888
    function.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,
                        ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int,
                        ctypes.c_void_p, ctypes.c_size_t]
    function.restype = Result
    return directory, function


def make_scene(width, height, stride, *, padding=0xA6, changed=False):
    pixels = bytearray([padding]) * ((height - 1) * stride + width * 3)
    for y in range(height):
        for x in range(width):
            checker = 24 if (x // 4 + y // 4) & 1 else 0
            rgb = (32 + 160 * x // width + checker,
                   32 + 160 * y // height + checker,
                   48 + 100 * (x + y) // (width + height) + checker)
            start = y * stride + x * 3
            pixels[start:start + 3] = bytes(255 - c if changed else c for c in rgb)
    return bytes(pixels)


def encode(function, pixels, width, height, stride, *, quality=95, capacity=65536):
    source = ctypes.create_string_buffer(pixels, len(pixels))
    dest = (ctypes.c_ubyte * (capacity + 2 * GUARD))()
    ctypes.memset(dest, 0xA5, ctypes.sizeof(dest))
    result = function(source, len(pixels), width, height, stride, quality,
                      ctypes.addressof(dest) + GUARD, capacity)
    assert source.raw == pixels
    raw = bytes(dest)
    assert raw[:GUARD] == bytes([0xA5]) * GUARD
    assert raw[GUARD + capacity:] == bytes([0xA5]) * GUARD
    assert result.used <= capacity
    if result.status != OK:
        assert result.used == 0
    return result, raw[GUARD:GUARD + result.used]


def decoded(payload, width, height):
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "JPEG"
        assert image.size == (width, height) and image.mode == "RGB"
        image.load()
        return image.tobytes()


def assert_close(actual, pixels, width, height, stride):
    expected = b"".join(pixels[y * stride:y * stride + width * 3]
                        for y in range(height))
    errors = [abs(a - b) for a, b in zip(actual, expected, strict=True)]
    assert max(errors) <= 35
    assert sum(errors) / len(errors) < 9


def assert_baseline_markers(payload, width, height):
    assert payload[:2] == b"\xff\xd8" and payload[-2:] == b"\xff\xd9"
    position, markers = 2, {}
    while True:
        assert payload[position] == 0xFF
        marker = payload[position + 1]
        assert marker not in (0x00, 0xD8, 0xD9)
        position += 2
        length = int.from_bytes(payload[position:position + 2], "big")
        assert length >= 2 and position + length <= len(payload)
        markers[marker] = payload[position + 2:position + length]
        position += length
        if marker == 0xDA:
            break
    assert 0xDB in markers and 0xC4 in markers
    sof = markers[0xC0]
    assert sof[0] == 8 and sof[5] == 3
    assert int.from_bytes(sof[1:3], "big") == height
    assert int.from_bytes(sof[3:5], "big") == width
    assert markers[0xDA][-3:] == b"\x00\x3f\x00"
    assert 0xC2 not in markers


@pytest.mark.parametrize("name", ["normal", "sanitized"])
def test_c_selftests(builds, name):
    directory, _ = builds
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    completed = subprocess.run([str(directory / name)], env=environment,
                               capture_output=True, text=True, check=True)
    assert "6 C self-test groups passed" in completed.stdout


@pytest.mark.parametrize("width,height", [
    (1, 1), (3, 5), (7, 9), (17, 19), (31, 23), (64, 33), (127, 65),
])
def test_pillow_roundtrip(builds, width, height):
    _, function = builds
    stride = width * 3 + 7
    pixels = make_scene(width, height, stride)
    result, payload = encode(function, pixels, width, height, stride)
    assert result.status == OK
    assert_baseline_markers(payload, width, height)
    assert_close(decoded(payload, width, height), pixels, width, height, stride)


def test_changed_pixels_change_decoded_content(builds):
    _, function = builds
    width, height, stride = 33, 21, 33 * 3
    originals = [make_scene(width, height, stride, changed=changed)
                 for changed in (False, True)]
    payloads, images = [], []
    for original in originals:
        result, payload = encode(function, original, width, height, stride)
        assert result.status == OK
        image = decoded(payload, width, height)
        assert_close(image, original, width, height, stride)
        payloads.append(payload)
        images.append(image)
    assert payloads[0] != payloads[1]
    delta = sum(abs(a - b) for a, b in zip(*images, strict=True)) / len(images[0])
    assert delta > 40


def test_padding_is_ignored(builds):
    _, function = builds
    width, height = 17, 13
    streams = []
    for stride, padding in ((width * 3, 0), (width * 3 + 11, 0x12),
                            (width * 3 + 11, 0xEF)):
        pixels = make_scene(width, height, stride, padding=padding)
        result, payload = encode(function, pixels, width, height, stride)
        assert result.status == OK
        streams.append(payload)
    assert streams[0] == streams[1] == streams[2]


@pytest.mark.parametrize("quality", [1, 50, 100])
def test_quality_range(builds, quality):
    _, function = builds
    pixels = make_scene(17, 19, 51)
    result, payload = encode(function, pixels, 17, 19, 51, quality=quality)
    assert result.status == OK
    assert_baseline_markers(payload, 17, 19)
    assert len(decoded(payload, 17, 19)) == 17 * 19 * 3


def test_exact_capacity_and_overflow(builds):
    _, function = builds
    pixels = make_scene(33, 17, 99)
    full, reference = encode(function, pixels, 33, 17, 99)
    assert full.status == OK
    for capacity in (0, 1, 127, full.used - 1, full.used, full.used + 1):
        result, payload = encode(function, pixels, 33, 17, 99, capacity=capacity)
        if capacity < full.used:
            assert result.status == OUTPUT_TOO_SMALL and payload == b""
        else:
            assert result.status == OK and payload == reference


def test_concurrent_calls(builds):
    _, function = builds

    def worker(index):
        width, height = 31 + index % 7, 17 + index % 5
        stride = width * 3 + index % 3
        pixels = make_scene(width, height, stride, changed=bool(index & 1))
        result, payload = encode(function, pixels, width, height, stride)
        assert result.status == OK
        assert_close(decoded(payload, width, height), pixels, width, height, stride)
        return payload

    with ThreadPoolExecutor(max_workers=4) as pool:
        payloads = list(pool.map(worker, range(12)))
    assert len(payloads) == 12
