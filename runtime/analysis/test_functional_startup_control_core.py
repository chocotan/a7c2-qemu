# SPDX-License-Identifier: MIT
"""Finite actual Core startup-control checks; no native/physical capture claim."""
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
def startup_build(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("functional-startup-control-core-" + request.param)
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15))
    dependencies = [REPORT / path for path in (
        "virtual-optics/optics.c", "virtual-optical-frame-owner/optical-frame-owner.c",
        "virtual-jpeg-hardware/jpeg-hardware.c", "virtual-jpeg-hardware/jpeg-hardware-codec.c",
        "virtual-jpeg-sos/jpeg-sos.c", "virtual-video-engine/video-engine.c",
        "virtual-camera-pipeline/camera-pipeline.c")]
    sanitize = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    binary = directory / "startup-control"
    command = shlex.split(os.environ.get("CC", "cc")) + FLAGS + sanitize + [
        str(HERE / "test-functional-startup-control-core.c")
    ] + list(map(str, dependencies)) + libraries + ["-lm", "-o", str(binary)]
    process = subprocess.run(command, capture_output=True, timeout=90)
    (directory / "compile.log").write_bytes(process.stdout + process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    return binary


def run(binary, scenario):
    process = subprocess.run([str(binary), scenario], env=ENV, capture_output=True, timeout=90)
    (binary.parent / (scenario + ".stdout.bin")).write_bytes(process.stdout)
    (binary.parent / (scenario + ".stderr.log")).write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    return process.stdout


def test_actual_full192_state_and_independent_rgb(startup_build):
    data = blobs(run(startup_build, "success"))
    previous = data["BEFORE"]
    for name in ("MODE", "SETTINGS", "MODE_REPEAT", "SETTINGS_REPEAT"):
        source, sink, canonical = data[name + "_SOURCE"], data[name + "_SINK"], data[name + "_INPUT"]
        assert source == sink and len(source) == 921600
        assert len(set(zip(source[0::3], source[1::3], source[2::3]))) > 1
        command = 0x4014 if name.startswith("MODE") else 0x4057
        body = bytes.fromhex("00000100010000000100000000000000") if command == 0x4014 else bytes(16)
        assert canonical == struct.pack("<HH", command, 16 if command == 0x4014 else 4) + body + bytes(4) + struct.pack("<Q", fnv(previous[8:48]))
        generation, frame = u64(previous, 56) + 1, u64(previous, 112) + 1
        expected = bytearray(192)
        struct.pack_into("<IIQQQQQQQQ", expected, 0, 1, 192, 77, generation, frame, frame,
                         fnv(canonical), fnv(source), fnv(sink), len(source))
        struct.pack_into("<14I", expected, 72, 640, 480, 1920, 0x90590819,
                         1, 1, 9, 1, 1, 1, 1, 1, 0, 0)
        expected[128:144] = data["ROUTE"]
        struct.pack_into("<QQ", expected, 144, frame - 1, generation - 1)
        expected[160:] = canonical
        assert data[name] == expected
        expected_state = bytearray(previous)
        for offset in (56, 64, 72, 112):
            struct.pack_into("<Q", expected_state, offset, u64(previous, offset) + 1)
        assert data[name + "_STATE"] == expected_state
        assert struct.unpack_from("<8I", expected_state) == (1, 15, 640, 480, 117, 13, 800, 640)
        assert (u64(expected_state, 32), u64(expected_state, 40)) == (8642, (1 << 64) - 1)
        assert all(u64(expected_state, offset) == 0 for offset in (80, 88, 96, 120))
        previous = data[name + "_STATE"]
    assert data["CHECKPOINT"] == previous[8:48]
    assert data["MODE_INPUT"] == data["MODE_REPEAT_INPUT"]
    assert data["SETTINGS_INPUT"] == data["SETTINGS_REPEAT_INPUT"]


@pytest.mark.parametrize("scenario", ("validation", "faults", "reload"))
def test_rejections_faults_and_legal_configuration_reload(startup_build, scenario):
    assert run(startup_build, scenario) == b""


def test_saved_banks_checkpoint_and_real_codec_boundaries(startup_build):
    from PIL import Image
    data = blobs(run(startup_build, "consumers"))
    image = Image.open(io.BytesIO(data["JPEG"]))
    image.load()
    assert image.format == "JPEG" and image.size == (128, 64)
    rgb = image.convert("RGB").tobytes()
    assert len(set(zip(rgb[0::3], rgb[1::3], rgb[2::3]))) > 1
    annex_b = bytearray()
    for name in ("H264_FRAME", "H264_END"):
        packet, offset = data.get(name, b""), 0
        while offset < len(packet):
            assert len(packet) - offset >= 96
            assert struct.unpack_from("<II", packet, offset) == (128, 64)
            payload_bytes, config_bytes = u64(packet, offset + 48), struct.unpack_from("<I", packet, offset + 64)[0]
            assert struct.unpack_from("<I", packet, offset + 68)[0] == 0x61766331
            end = offset + 96 + config_bytes + payload_bytes
            assert end <= len(packet)
            annex_b.extend(packet[offset + 96:end])
            offset = end
    assert annex_b and b"\x00\x00\x00\x01" in annex_b
    process = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-threads", "1", "-f", "h264",
                              "-i", "pipe:0", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                             input=annex_b, capture_output=True, timeout=20)
    (startup_build.parent / "h264-independent-decoder.stderr.log").write_bytes(process.stderr)
    (startup_build.parent / "h264-independent-decoder.stdout.bin").write_bytes(process.stdout)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert len(process.stdout) == 128 * 64 * 3
    assert len(set(zip(process.stdout[0::3], process.stdout[1::3], process.stdout[2::3]))) > 1
