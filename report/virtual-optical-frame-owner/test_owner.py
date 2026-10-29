"""Host memory tests; no VM, network, camera, disk photos, or private inputs."""

import io
import os
from pathlib import Path
import selectors
import shlex
import subprocess
import time

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parent
GROUPS = ("lifecycle", "configuration", "bounds", "copies", "consumers",
          "exhaustion", "renderer-identity", "autofocus", "autofocus-flat",
          "autofocus-bounds")


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("optical-frame-owner")
    compiler = shlex.split(os.environ.get("CC", "cc"))
    jpeg = ROOT.parent / "virtual-jpeg-engine"
    optics = ROOT.parent / "virtual-optics"
    libraries = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libjpeg"], text=True, timeout=10
    ))
    sources = [ROOT / "optical-frame-owner.c", ROOT / "test_owner.c",
               optics / "optics.c", jpeg / "jpeg-engine.c"]
    common = compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    for name, flags in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        subprocess.run(common + flags + list(map(str, sources)) +
                       ["-o", str(directory / name), "-lm"] + libraries,
                       check=True, capture_output=True, timeout=60)
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    return directory, environment


@pytest.mark.parametrize("name", ("normal", "sanitized"))
@pytest.mark.parametrize("group", GROUPS)
def test_contract(builds, name, group):
    directory, environment = builds
    result = subprocess.run([str(directory / name), group], env=environment,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
    assert result.stdout == f"PASS {group}\n".encode()


class PipeReader:
    """Unbuffered test pipe with a deadline so a failed handshake cannot hang."""

    def __init__(self, stream):
        self.stream = stream
        self.pending = bytearray()
        self.deadline = time.monotonic() + 60
        self.selector = selectors.DefaultSelector()
        self.selector.register(stream, selectors.EVENT_READ)

    def fill(self):
        remaining = self.deadline - time.monotonic()
        assert remaining > 0 and self.selector.select(remaining), "encoder pipe timed out"
        data = os.read(self.stream.fileno(), 65536)
        assert data, "encoder closed pipe before decode/retirement handshake finished"
        self.pending.extend(data)

    def exact(self, size):
        while len(self.pending) < size:
            self.fill()
        data = bytes(self.pending[:size])
        del self.pending[:size]
        return data

    def line(self):
        while b"\n" not in self.pending:
            assert len(self.pending) < 512
            self.fill()
        return self.exact(self.pending.index(b"\n") + 1)

    def close(self):
        self.selector.close()


def decode(raw, encoded, width, height, stride, digest, textured=True):
    assert len(raw) == stride * height
    for y in range(height):
        assert raw[y * stride + width * 3:(y + 1) * stride] == b"\xa5" * 13
    pixels = b"".join(raw[y * stride:y * stride + width * 3] for y in range(height))
    checksum = 14695981039346656037
    for byte in pixels:
        checksum = ((checksum ^ byte) * 1099511628211) & ((1 << 64) - 1)
    assert checksum == digest
    # Generation stays out of band; the optical scene retains its periodic row 0.
    assert raw[:width * 3] == raw[8 * stride:8 * stride + width * 3]
    with Image.open(io.BytesIO(encoded)) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        assert image.size == (width, height)
        image.load()
        decoded = image.tobytes()
    errors = [abs(a - b) for a, b in zip(pixels, decoded, strict=True)]
    assert max(errors) <= 24 and sum(errors) / len(errors) < 3
    spread = max(pixels[::3]) - min(pixels[::3])
    assert spread > 10 if textured else spread <= 2
    return width, height, pixels, decoded


def mean(frame, channel):
    width, height, raw, decoded = frame
    pixels = (raw, decoded)[channel]
    values = [pixels[(y * width + x) * 3]
              for y in range(height) for x in range(8, width // 2 - 8)]
    return sum(values) / len(values)


def gradient(frame, channel, layer):
    width, height, raw, decoded = frame
    pixels = (raw, decoded)[channel]
    start, stop = layer * (width // 2) + 20, (layer + 1) * (width // 2) - 20
    values = []
    for y in range(16, height - 16):
        for x in range(start, stop):
            offset = (y * width + x) * 3
            values.extend((abs(pixels[offset + 3] - pixels[offset]),
                           abs(pixels[offset + width * 3] - pixels[offset])))
    return sum(values) / len(values)


@pytest.mark.parametrize("name", ("normal", "sanitized"))
def test_owned_rgb_encoder_pillow_before_retire(builds, name):
    directory, environment = builds
    process = subprocess.Popen([str(directory / name), "encode"], env=environment,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0)
    reader = PipeReader(process.stdout)
    frames = {}
    try:
        for generation, expected in enumerate(("base", "stopped", "far", "shutter", "iso", "odd",
                                               "defocused", "af-near", "af-far"), 1):
            marker, frame_name, w, h, stride, token, digest, used = reader.line().decode("ascii").split()
            w, h, stride, token, digest, used = map(int, (w, h, stride, token, digest, used))
            assert marker == "FRAME" and frame_name == expected and token == generation
            assert w == (1025 if expected == "odd" else 1024)
            assert h == (65 if expected == "odd" else 64) and stride == w * 3 + 13
            assert 0 < used <= stride * h + 4096
            frames[expected] = decode(reader.exact(stride * h), reader.exact(used),
                                      w, h, stride, digest, textured=expected != "defocused")
            # Only the independent, fully loaded Pillow image permits retirement.
            reply = f"decoded {generation} {digest}\n".encode("ascii")
            assert process.stdin.write(reply) == len(reply)
            process.stdin.flush()
        assert reader.line() == b"PASS decoded-before-retire 9\n"
        assert reader.pending == b""
        remaining, errors = process.communicate(timeout=10)
        assert process.returncode == 0 and remaining == errors == b""
    finally:
        reader.close()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()

    for channel in (0, 1):
        base = mean(frames["base"], channel)
        assert mean(frames["stopped"], channel) / base == pytest.approx(0.25, abs=0.035)
        assert mean(frames["shutter"], channel) / base == pytest.approx(2.0, abs=0.04)
        assert mean(frames["iso"], channel) / base == pytest.approx(2.0, abs=0.04)
        for layer in (0, 1):
            pair = [gradient(frames[key], channel, layer) for key in ("base", "far")]
            assert pair[layer] > 2 * pair[1 - layer] and pair[layer] > 5
            focused = gradient(frames[("af-near", "af-far")[layer]], channel, layer)
            assert focused > 5 * gradient(frames["defocused"], channel, layer) + 5
            assert focused >= 0.95 * pair[layer]
            wrong_roi = gradient(frames[("af-far", "af-near")[layer]], channel, layer)
            assert focused > 2 * wrong_roi
    assert frames["odd"][:2] == (1025, 65)
    assert frames["shutter"][2:] == frames["iso"][2:]
