# SPDX-License-Identifier: MIT
"""Bounded software RGB888 bus policy, exercised through the actual Core.

No native/physical bit-depth or original capture acceptance is established here.
"""
import io
import os
from pathlib import Path
import shlex
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parent.parent / "report"
CORE = REPORT / "functional-camera-core"
FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
         "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1:quarantine_size_mb=64",
           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def blobs(data):
    stream, result = io.BytesIO(data), {}
    while line := stream.readline():
        tag, name, count = line.split()
        assert tag == b"BLOB" and name.decode() not in result
        value = stream.read(int(count))
        assert len(value) == int(count)
        result[name.decode()] = value
    return result


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def bit_width_builds(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("functional-bit-width-core-" + request.param)
    cc = shlex.split(os.environ.get("CC", "cc"))
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
    for name, source in (("bit-width", HERE / "test-functional-bit-width-core.c"),
                         ("vdf", CORE / "test-functional-camera-vdf.c"),
                         ("startup", CORE / "test-functional-camera-startup.c")):
        binary = directory / name
        command = cc + FLAGS + sanitize + [str(source)] + list(map(str, dependencies)) + libraries + ["-lm", "-o", str(binary)]
        process = subprocess.run(command, capture_output=True, timeout=90)
        (directory / (name + ".compile.log")).write_bytes(process.stdout + process.stderr)
        assert process.returncode == 0, process.stderr.decode(errors="replace")
        result[name] = binary
    return result


def run(builds, binary, *arguments):
    executable = builds[binary]
    process = subprocess.run([str(executable), *arguments], env=ENV, capture_output=True, timeout=45)
    stem = binary + "-" + "-".join(arguments or ("default",))
    (executable.parent / (stem + ".stdout.bin")).write_bytes(process.stdout)
    (executable.parent / (stem + ".stderr.log")).write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    return process.stdout


def test_actual_rgb_consumption_full_typed_receipt_and_independent_readback(bit_width_builds):
    data = blobs(run(bit_width_builds, "bit-width", "success"))
    source, sink = data["SOURCE"], data["SINK"]
    assert source == sink and len(source) == 640 * 480 * 3
    assert len(set(zip(source[0::3], source[1::3], source[2::3]))) > 1
    assert any(r != g or g != b for r, g, b in zip(source[0::3], source[1::3], source[2::3]))
    assert data["INPUT"] == bytes(8)
    assert data["ROUTE"] == bytes([1, 5, 5, 0xA9, 2, 0, 0, 0, 0x67]) + bytes(7)
    previous = data["BEFORE"]
    source_fnv, sink_fnv = fnv(source), fnv(sink)
    for name, state_name in (("RECEIPT", "STATE"), ("REPEAT", "STATE_REPEAT")):
        receipt, state = data[name], data[state_name]
        generation, frame = u64(previous, 56) + 1, u64(previous, 112) + 1
        expected = bytearray(168)
        struct.pack_into("<IIQQQQQQQQ", expected, 0, 1, 168, 77, generation, frame, frame,
                         fnv(data["INPUT"]), source_fnv, sink_fnv, len(source))
        struct.pack_into("<14I", expected, 72, 640, 480, 1920, 0x90590819,
                         1, 1, 7, 1, 1, 1, 1, 1, 0, 0)
        expected[128:144] = data["ROUTE"]
        struct.pack_into("<QQ", expected, 144, frame - 1, generation - 1)
        expected[160:168] = data["INPUT"]
        assert receipt == expected
        expected_state = bytearray(previous)
        for offset in (56, 64, 72, 112):
            struct.pack_into("<Q", expected_state, offset, u64(previous, offset) + 1)
        assert state == expected_state and state[120:] == bytes(8)
        assert struct.unpack_from("<8I", state) == (1, 15, 640, 480, 117, 13, 800, 640)
        assert (u64(state, 32), u64(state, 40)) == (8642, (1 << 64) - 1)
        assert all(u64(state, offset) == 0 for offset in (80, 88, 96))
        previous = state


@pytest.mark.parametrize("scenario", ("validation", "faults"))
def test_rejections_and_real_boundary_failures_preserve_uncommitted_work(bit_width_builds, scenario):
    assert run(bit_width_builds, "bit-width", scenario) == b""


@pytest.mark.parametrize("scenario", ("", "zebra", "layout", "display"))
def test_existing_vdf_banks_and_actual_frame_consumers_remain_valid(bit_width_builds, scenario):
    assert blobs(run(bit_width_builds, "vdf", *([scenario] if scenario else [])))


@pytest.mark.parametrize("scenario", ("mixed", "validation", "faults"))
def test_existing_five_bb_banks_and_histogram_remain_valid(bit_width_builds, scenario):
    output = run(bit_width_builds, "startup", scenario)
    assert bool(output) == (scenario == "mixed")
