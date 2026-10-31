# SPDX-License-Identifier: MIT
"""Actual Core OP13 software full-frame/FINE policy; no native capture claim."""
import io
import os
from pathlib import Path
import shlex
import struct
import subprocess

import pytest

from test_functional_bit_width_core import FLAGS, ENV, fnv, u64, blobs

HERE = Path(__file__).resolve().parent
REPORT = HERE.parent.parent / "report"


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def still_format_builds(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("functional-still-format-core-" + request.param)
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15))
    dependencies = [REPORT / path for path in (
        "virtual-optics/optics.c", "virtual-optical-frame-owner/optical-frame-owner.c",
        "virtual-jpeg-hardware/jpeg-hardware.c", "virtual-jpeg-hardware/jpeg-hardware-codec.c",
        "virtual-jpeg-sos/jpeg-sos.c", "virtual-video-engine/video-engine.c",
        "virtual-camera-pipeline/camera-pipeline.c")]
    sanitize = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    result = {}
    for name in ("still-format", "bit-width"):
        binary = directory / name
        command = shlex.split(os.environ.get("CC", "cc")) + FLAGS + sanitize + [
            str(HERE / ("test-functional-" + name + "-core.c"))
        ] + list(map(str, dependencies)) + libraries + ["-lm", "-o", str(binary)]
        process = subprocess.run(command, capture_output=True, timeout=90)
        (directory / (name + ".compile.log")).write_bytes(process.stdout + process.stderr)
        assert process.returncode == 0, process.stderr.decode(errors="replace")
        result[name] = binary
    return result


def run(builds, binary, scenario):
    executable = builds[binary]
    process = subprocess.run([str(executable), scenario], env=ENV, capture_output=True, timeout=90)
    (executable.parent / (binary + "-" + scenario + ".stdout.bin")).write_bytes(process.stdout)
    (executable.parent / (binary + "-" + scenario + ".stderr.log")).write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    return process.stdout


def test_actual_still_format_full176_golden_and_independent_sink(still_format_builds):
    data = blobs(run(still_format_builds, "still-format", "success"))
    assert data["INPUT"] == bytes.fromhex("02000001000100000001000100000000")
    assert data["ROUTE"] == bytes([1, 5, 5, 0xA9, 2, 0, 0, 0, 0x67]) + bytes(7)
    previous = data["BEFORE"]
    for name, state_name, suffix in (("RECEIPT", "STATE", ""), ("REPEAT", "STATE_REPEAT", "_REPEAT")):
        source, sink = data["SOURCE" + suffix], data["SINK" + suffix]
        assert source == sink and len(source) == 640 * 480 * 3
        assert len(set(zip(source[0::3], source[1::3], source[2::3]))) > 1
        assert any(r != g or g != b for r, g, b in zip(source[0::3], source[1::3], source[2::3]))
        generation, frame = u64(previous, 56) + 1, u64(previous, 112) + 1
        expected = bytearray(176)
        struct.pack_into("<IIQQQQQQQQ", expected, 0, 1, 176, 77, generation, frame, frame,
                         fnv(data["INPUT"]), fnv(source), fnv(sink), len(source))
        struct.pack_into("<14I", expected, 72, 640, 480, 1920, 0x90590819,
                         1, 1, 8, 1, 1, 1, 1, 1, 0, 0)
        expected[128:144] = data["ROUTE"]
        struct.pack_into("<QQ", expected, 144, frame - 1, generation - 1)
        expected[160:] = data["INPUT"]
        assert data[name] == expected
        expected_state = bytearray(previous)
        for offset in (56, 64, 72, 112):
            struct.pack_into("<Q", expected_state, offset, u64(previous, offset) + 1)
        assert data[state_name] == expected_state and data[state_name][120:] == bytes(8)
        assert struct.unpack_from("<8I", data[state_name]) == (1, 15, 640, 480, 117, 13, 800, 640)
        assert (u64(data[state_name], 32), u64(data[state_name], 40)) == (8642, (1 << 64) - 1)
        assert all(u64(data[state_name], offset) == 0 for offset in (80, 88, 96))
        previous = data[state_name]


@pytest.mark.parametrize("scenario", ("validation", "faults"))
def test_still_format_rejection_and_real_boundary_failures(still_format_builds, scenario):
    assert run(still_format_builds, "still-format", scenario) == b""


def test_saved_still_format_constrains_actual_rgb_and_encoders(still_format_builds):
    from PIL import Image
    data = blobs(run(still_format_builds, "still-format", "consumers"))
    image = Image.open(io.BytesIO(data["JPEG"]))
    image.load()
    assert image.format == "JPEG" and image.size == (128, 64)
    rgb = image.convert("RGB").tobytes()
    assert len(set(zip(rgb[0::3], rgb[1::3], rgb[2::3]))) > 1


@pytest.mark.parametrize("scenario", ("success", "validation", "faults"))
def test_existing_bit_width_core_regression(still_format_builds, scenario):
    output = run(still_format_builds, "bit-width", scenario)
    assert bool(output) == (scenario == "success")
