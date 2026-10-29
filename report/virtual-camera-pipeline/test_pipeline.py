# SPDX-License-Identifier: MIT
"""One command: strict C + ASan/UBSan contracts + real in-memory media decoders."""
import io
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import zlib

from PIL import Image
import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parent
WIDTH, HEIGHT, STRIDE, FPS = 128, 64, 395, 25
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("camera-pipeline-build")
    cc = shlex.split(os.environ.get("CC", "cc"))
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=10))
    sources = [HERE / "test_pipeline.c",
               REPORT / "virtual-optics/optics.c",
               REPORT / "virtual-optical-frame-owner/optical-frame-owner.c",
               REPORT / "virtual-jpeg-hardware/jpeg-hardware.c",
               REPORT / "virtual-jpeg-hardware/jpeg-hardware-codec.c",
               REPORT / "virtual-jpeg-sos/jpeg-sos.c",
               REPORT / "virtual-video-engine/video-engine.c"]
    # Validate the public production translation unit independently of the
    # executable's private callback adversarial checks.
    subprocess.run(cc + flags + ["-O2", "-fsyntax-only", str(HERE / "camera-pipeline.c")],
                   check=True, capture_output=True, timeout=30)
    result = {}
    for name, options in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        executable = directory / name
        process = subprocess.run(cc + flags + options + list(map(str, sources)) +
                                 libraries + ["-lm", "-o", str(executable)],
                                 capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stderr
        result[name] = executable
    return result


def run(builds, mode, *arguments):
    result = subprocess.run([str(builds[mode]), *map(str, arguments)],
                            capture_output=True, env=ENV, timeout=45)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"Sanitizer" not in result.stderr and b"runtime error:" not in result.stderr
    return result.stdout


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("group", ["geometry", "lifecycle", "callbacks", "stale", "af", "jpeg_errors",
                                   "jpeg_cancel", "sink", "capacities", "cancel", "mutation", "mux"])
def test_controller_contracts(builds, mode, group):
    assert run(builds, mode, group) == b""


def products(wire):
    stream = io.BytesIO(wire)
    blobs, metadata = {}, []
    while line := stream.readline():
        if line.startswith(b"META "):
            metadata.append(json.loads(line[5:]))
            continue
        tag, kind, size = line.split()
        assert tag == b"BLOB"
        data = stream.read(int(size))
        assert len(data) == int(size)
        blobs.setdefault(kind.decode(), []).append(data)
    return blobs, metadata


def active_rgb(padded):
    assert len(padded) == STRIDE * HEIGHT
    for row in range(HEIGHT):
        assert padded[row * STRIDE + WIDTH * 3:(row + 1) * STRIDE] == b"\xa5" * 11
    return b"".join(padded[y * STRIDE:y * STRIDE + WIDTH * 3] for y in range(HEIGHT))


def fnv1a(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def mean_error(actual, expected):
    assert len(actual) == len(expected)
    return sum(abs(a - b) for a, b in zip(actual, expected)) / len(actual)


def jpeg_segments(jpeg):
    assert jpeg[:2] == b"\xff\xd8" and jpeg[-2:] == b"\xff\xd9"
    offset, segments = 2, []
    while True:
        assert jpeg[offset] == 255
        marker = jpeg[offset + 1]
        length = int.from_bytes(jpeg[offset + 2:offset + 4], "big")
        assert length >= 2 and offset + 2 + length <= len(jpeg)
        segments.append((marker, offset, jpeg[offset + 4:offset + 2 + length]))
        if marker == 0xDA:
            return segments
        offset += 2 + length


def decode(data, format_name):
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-threads", "1",
        "-f", format_name, "-i", "pipe:0", "-map", "0:v:0", "-threads", "1",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], input=data,
        capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def probe(data, format_name):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-f", format_name, "-i", "pipe:0", "-count_frames",
        "-show_streams", "-show_format", "-show_packets", "-of", "json"],
        input=data, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return json.loads(result.stdout)


def nal_units(data):
    starts = list(re.finditer(b"\x00\x00\x00\x01|\x00\x00\x01", data))
    assert starts and starts[0].start() == 0
    return [(data[match.end()] & 31,
             data[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(data)])
            for i, match in enumerate(starts)]


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("count", [2, 4, 6])
def test_complete_pipeline_products_consumed_in_memory(builds, mode, count):
    blobs, metadata = products(run(builds, mode, "products", count))
    still_info = [item for item in metadata if item["kind"] == "still"]
    frame_info = [item for item in metadata if item["kind"] == "frame"]
    packet_info = [item for item in metadata if item["kind"] == "packet"]
    done, = [item for item in metadata if item["kind"] == "done"]
    assert len(still_info) == len(blobs["JPEG"]) == 2
    assert len(frame_info) == len(blobs["VIDEO_RGB"]) == len(packet_info) == count
    assert [info["generation"] for info in still_info + frame_info] == list(range(1, count + 3))
    assert done["irq"] == 2 and done["packets"] == count
    for stage in ("rendered", "source_read", "encoder_consumed", "encoded", "output_readback", "retired"):
        assert done[stage] == count + 2
    assert (done["width"], done["height"], done["stride"], done["fps"]) == (WIDTH, HEIGHT, STRIDE, FPS)

    for i, (jpeg, padded, info) in enumerate(zip(blobs["JPEG"], blobs["STILL_RGB"], still_info)):
        source = active_rgb(padded)
        assert fnv1a(source) == info["hash"]
        assert math.isclose(info["focus"], 4 if i else 1, abs_tol=0.2 if i else 0.08)
        assert info["blur"][i] < info["blur"][1 - i]
        segments = jpeg_segments(jpeg)
        assert [marker for marker, _, _ in segments] == [0xDB, 0xC4, 0xC0, 0xDA]
        quant = segments[0][2]
        expected = b"".join(bytes([t]) + bytes(3 + t + z % 13 for z in range(64)) for t in range(2))
        assert quant == expected  # Typed test snapshot preserved exactly.
        assert len(segments[1][2]) == 416  # Source-pinned DC/AC tables, both components.
        sof = segments[2][2]
        assert sof[:6] == bytes([8, 0, HEIGHT, 0, WIDTH, 3])
        assert sof[6:] == bytes([1, 0x21, 0, 2, 0x11, 1, 3, 0x11, 1])
        assert segments[3][2] == bytes([3, 1, 0, 2, 0x11, 3, 0x11, 0, 63, 0])
        prefix = info["prefix"]
        assert prefix == 0x23D + 2 == segments[-1][1]
        assert info["suffix"] == len(jpeg) - prefix
        assert zlib.crc32(jpeg[:prefix]) == info["prefix_crc"]
        assert zlib.crc32(jpeg[prefix:]) == info["suffix_crc"]
        assert zlib.crc32(jpeg) == info["jpeg_crc"]
        # Pillow owns its independently decoded bytes. No media is written out.
        image = Image.open(io.BytesIO(jpeg))
        image.load()
        assert image.format == "JPEG" and image.size == (WIDTH, HEIGHT)
        assert mean_error(image.convert("RGB").tobytes(), source) < 8
    assert blobs["JPEG"][0] != blobs["JPEG"][1]

    elementary, = blobs["H264"]
    extradata, = blobs["CONFIG"]
    mp4, = blobs["MP4"]
    assert [kind for kind, _ in nal_units(extradata)] == [7, 8]
    assert extradata == b"".join(data for kind, data in nal_units(
        elementary[:packet_info[0]["size"]]) if kind in (7, 8))
    offset = 0
    for i, packet in enumerate(packet_info):
        assert packet["offset"] == offset and packet["size"] > 0
        assert packet["pts"] == packet["dts"] == i and packet["duration"] == 1
        assert nal_units(elementary[offset:offset + packet["size"]])
        offset += packet["size"]
    assert offset == len(elementary) and packet_info[0]["keyframe"] == 1
    decoded_h264 = decode(elementary, "h264")
    decoded_mp4 = decode(mp4, "mov")
    assert decoded_mp4 == decoded_h264  # MP4 contains exactly the published packets.
    frame_bytes = WIDTH * HEIGHT * 3
    assert len(decoded_h264) == count * frame_bytes
    sources = [active_rgb(frame) for frame in blobs["VIDEO_RGB"]]
    for i, (source, info) in enumerate(zip(sources, frame_info)):
        assert fnv1a(source) == info["hash"] and info["pts"] == i
        decoded = decoded_h264[i * frame_bytes:(i + 1) * frame_bytes]
        assert mean_error(decoded, source) < 12
        assert mean_error(decoded, source) < mean_error(decoded, b"\xcc" * frame_bytes)
    assert sum(sources[-1]) > sum(sources[0])  # Actual exposure change consumed.
    assert mean_error(decoded_h264[-frame_bytes:], sources[-1]) < mean_error(
        decoded_h264[-frame_bytes:], sources[0])
    for data, name in ((elementary, "h264"), (mp4, "mov")):
        details = probe(data, name)
        stream, = details["streams"]
        assert stream["codec_name"] == "h264" and stream["pix_fmt"] == "yuv420p"
        assert (stream["width"], stream["height"]) == (WIDTH, HEIGHT)
        assert int(stream["nb_read_frames"]) == count
        assert len(details["packets"]) == count
        if name == "mov":
            assert math.isclose(float(stream["duration"]), count / FPS, abs_tol=1e-6)
            assert stream["avg_frame_rate"] == "25/1"
            for i, packet in enumerate(details["packets"]):
                assert math.isclose(float(packet["pts_time"]), i / FPS, abs_tol=1e-6)
                assert math.isclose(float(packet["dts_time"]), i / FPS, abs_tol=1e-6)
                assert math.isclose(float(packet["duration_time"]), 1 / FPS, abs_tol=1e-6)
