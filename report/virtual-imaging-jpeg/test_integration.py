"""Host component integration only; Capture_verified=false, no camera photos."""

from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import shlex
import subprocess

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parent


def unpack(payload):
    stream, frames = io.BytesIO(payload), {}
    for expected in ("base", "stopped", "far", "odd"):
        name, w, h, stride, used = stream.readline().decode("ascii").split()
        w, h, stride, used = map(int, (w, h, stride, used))
        assert name == expected and 0 < w <= 1025 and 0 < h <= 65
        assert stride == w * 3 + 13 and 0 < used <= stride * h + 4096
        raw = stream.read(stride * h)
        assert len(raw) == stride * h
        pixels = b"".join(raw[y * stride:y * stride + w * 3] for y in range(h))
        for y in range(h):
            assert raw[y * stride + w * 3:(y + 1) * stride] == b"\xa5" * 13
        encoded = stream.read(used)
        assert len(encoded) == used
        with Image.open(io.BytesIO(encoded)) as image:
            assert image.format == "JPEG" and image.mode == "RGB"
            assert image.size == (w, h)
            image.load()
            frames[name] = (w, h, pixels, image.tobytes())
    assert stream.read() == b""
    return frames


@pytest.fixture(scope="session")
def batches(tmp_path_factory):
    directory = tmp_path_factory.mktemp("host-optics-jpeg")
    compiler = shlex.split(os.environ.get("CC", "cc"))
    jpeg_flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libjpeg"], text=True
    ))
    optics, jpeg = ROOT.parent / "virtual-optics", ROOT.parent / "virtual-jpeg-engine"
    common = compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                         "-I", str(optics), "-I", str(jpeg), str(ROOT / "integration.c"),
                         str(optics / "optics.c"), str(jpeg / "jpeg-engine.c")]
    for name, flags in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        subprocess.run(common + flags + ["-o", str(directory / name), "-lm"] + jpeg_flags,
                       check=True, timeout=60)
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"

    def run(name):
        result = subprocess.run([str(directory / name)], env=environment,
                                capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        assert result.stderr == b""
        return result.stdout

    with ThreadPoolExecutor(max_workers=4) as pool:
        payloads = list(pool.map(run, ("normal", "sanitized", "normal", "sanitized")))
    return payloads, [unpack(payload) for payload in payloads]


def close_to_input(frame):
    _, _, raw, decoded = frame
    errors = [abs(a - b) for a, b in zip(raw, decoded, strict=True)]
    assert max(errors) <= 24 and sum(errors) / len(errors) < 3
    assert max(raw[::3]) - min(raw[::3]) > 10


def mean(frame, pixels):
    width, height, _, _ = frame
    values = [pixels[(y * width + x) * 3]
              for y in range(height) for x in range(8, width // 2 - 8)]
    return sum(values) / len(values)


def gradient(frame, pixels, layer):
    width, height, _, _ = frame
    start, stop = layer * (width // 2) + 20, (layer + 1) * (width // 2) - 20
    differences = []
    for y in range(16, height - 16):
        for x in range(start, stop):
            i = (y * width + x) * 3
            differences.extend((abs(pixels[i + 3] - pixels[i]),
                                abs(pixels[i + width * 3] - pixels[i])))
    return sum(differences) / len(differences)


def test_aperture_light_ratio_survives_jpeg(batches):
    frames = batches[1][0]
    base, stopped = frames["base"], frames["stopped"]
    for frame in (base, stopped):
        close_to_input(frame)
    raw_ratio = mean(stopped, stopped[2]) / mean(base, base[2])
    decoded_ratio = mean(stopped, stopped[3]) / mean(base, base[3])
    assert raw_ratio == pytest.approx(0.25, abs=0.02)
    assert decoded_ratio == pytest.approx(raw_ratio, abs=0.035)
    print(f"F4->F8 mean red ratio: raw={raw_ratio:.6f}, decoded={decoded_ratio:.6f}")


def test_near_far_focus_exchange_survives_jpeg(batches):
    frames = batches[1][0]
    near, far = frames["base"], frames["far"]
    close_to_input(far)
    for layer in (0, 1):
        raw = [gradient(frame, frame[2], layer) for frame in (near, far)]
        decoded = [gradient(frame, frame[3], layer) for frame in (near, far)]
        assert raw[layer] > 2 * raw[1 - layer] and raw[layer] > 5
        assert decoded[layer] > 2 * decoded[1 - layer] and decoded[layer] > 5
        assert decoded == pytest.approx(raw, abs=1.5)
        print(f"target {layer} gradients at 1m/4m focus: raw={raw}, decoded={decoded}")


def test_odd_size_padded_frame_decodes(batches):
    frame = batches[1][0]["odd"]
    assert frame[:2] == (1025, 65)
    close_to_input(frame)
    assert mean(frame, frame[3]) == pytest.approx(mean(frame, frame[2]), abs=1.5)


def test_parallel_batches_keep_bounds_and_ownership(batches):
    payloads, frames = batches
    assert len(payloads) == len(frames) == 4
    # Each child asserts capacity-1 rejection, canaries, immutable input and exact output bounds.
    assert all(payload == payloads[0] for payload in payloads[1:])
