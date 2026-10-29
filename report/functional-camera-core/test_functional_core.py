# SPDX-License-Identifier: MIT
"""Parent-run joined checks: strict builds, sanitizers, real codecs, no media files."""
import ctypes
import errno
import io
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess

from PIL import Image
import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parent
DATA_BYTES = 65024
STATE_BYTES = 128
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1:quarantine_size_mb=64",
           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("functional-camera-core-build")
    cc = shlex.split(os.environ.get("CC", "cc"))
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=10))
    dependencies = [REPORT / path for path in (
        "virtual-optics/optics.c", "virtual-optical-frame-owner/optical-frame-owner.c",
        "virtual-jpeg-hardware/jpeg-hardware.c", "virtual-jpeg-hardware/jpeg-hardware-codec.c",
        "virtual-jpeg-sos/jpeg-sos.c", "virtual-video-engine/video-engine.c",
        "virtual-camera-pipeline/camera-pipeline.c")]
    subprocess.run(cc + CFLAGS + ["-O2", "-fsyntax-only", str(HERE / "functional-camera-core.c")] +
                   libraries, check=True, capture_output=True, timeout=30)
    result = {}
    for name, flags in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]),
    ):
        executable = directory / name
        subprocess.run(cc + CFLAGS + flags + [str(HERE / "test-functional-camera-core.c")] +
                       list(map(str, dependencies)) + libraries + ["-lm", "-o", str(executable)],
                       check=True, capture_output=True, timeout=90)
        result[name] = executable
        vdf = directory / ("vdf-" + name)
        subprocess.run(cc + CFLAGS + flags + [str(HERE / "test-functional-camera-vdf.c")] +
                       list(map(str, dependencies)) + libraries + ["-lm", "-o", str(vdf)],
                       check=True, capture_output=True, timeout=90)
        result["vdf-" + name] = vdf
        startup = directory / ("startup-" + name)
        subprocess.run(cc + CFLAGS + flags + [str(HERE / "test-functional-camera-startup.c")] +
                       list(map(str, dependencies)) + libraries + ["-lm", "-o", str(startup)],
                       check=True, capture_output=True, timeout=90)
        result["startup-" + name] = startup
    library = directory / "libfunctional-camera-core.so"
    subprocess.run(cc + CFLAGS + ["-O2", "-fPIC", "-shared", "-Wl,-z,defs",
                   str(HERE / "functional-camera-core.c")] + list(map(str, dependencies)) +
                   libraries + ["-lm", "-o", str(library)],
                   check=True, capture_output=True, timeout=90)
    result["library"] = library
    return result


def run(builds, mode, *arguments):
    process = subprocess.run([str(builds[mode]), *map(str, arguments)], env=ENV,
                             capture_output=True, timeout=120)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    return process.stdout


def blobs(data):
    stream = io.BytesIO(data)
    result = {}
    while line := stream.readline():
        tag, name, count = line.split()
        assert tag == b"BLOB"
        value = stream.read(int(count))
        assert len(value) == int(count)
        result.setdefault(name.decode(), []).append(value)
    return result


def jpeg(data):
    image = Image.open(io.BytesIO(data))
    image.load()
    assert image.format == "JPEG"
    return image


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def error(actual, expected):
    assert len(actual) == len(expected)
    return sum(abs(a - b) for a, b in zip(actual, expected)) / len(actual)


def nals(data):
    starts = list(re.finditer(b"\x00\x00\x00\x01|\x00\x00\x01", data))
    assert starts and starts[0].start() == 0
    return [data[item.end()] & 31 for item in starts]


def segments(data):
    assert data[:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"
    offset, values = 2, []
    while True:
        assert data[offset] == 255
        kind = data[offset + 1]
        size = int.from_bytes(data[offset + 2:offset + 4], "big")
        assert size >= 2 and offset + 2 + size <= len(data)
        values.append((kind, offset, data[offset + 4:offset + 2 + size]))
        if kind == 0xDA:
            return values
        offset += 2 + size


def decode_h264(data):
    process = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-threads", "1",
        "-f", "h264", "-i", "pipe:0", "-map", "0:v:0", "-threads", "1",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"], input=data,
        capture_output=True, timeout=30)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    return process.stdout


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("group", ["contracts", "proof", "fault", "empty", "long"])
def test_contracts_and_real_stream_lifecycle(builds, mode, group):
    assert run(builds, mode, group) == b""


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
def test_vdf_real_rgb_sink_receipt_and_failures(builds, mode):
    data = blobs(run(builds, "vdf-" + mode))
    source, = data["SOURCE"]
    sink, = data["SINK"]
    canonical, = data["INPUT"]
    assert source == sink and len(source) == 128 * 64 * 3
    assert len(set(source)) > 10
    assert len(set(zip(source[0::3], source[1::3], source[2::3]))) > 1
    assert any(r != g or g != b for r, g, b in zip(source[0::3], source[1::3], source[2::3]))
    assert canonical[:5] == bytes([1, 5, 5, 0xA5, 2]) and canonical[13:] == bytes(3)
    for name, frame, generation, before_frame, before_config, active in (
            ("ENABLED", 1, 3, 0, 2, True), ("REPEAT", 2, 4, 1, 3, True),
            ("DISABLED", 2, 5, 2, 4, False)):
        response, = data[name]
        config_body = canonical if active else bytes([0, 1, 1]) + bytes(13)
        expected = bytearray(160)
        struct.pack_into("<IIQQQQQQQQ", expected, 0,
                         1, 160, 77, generation, frame, frame if active else 0, fnv(config_body),
                         fnv(source) if active else 0, fnv(sink) if active else 0,
                         len(source) if active else 0)
        struct.pack_into("<14I", expected, 72, 128, 64, 384, 0x90590819, 1, 1,
                         int(active), int(active), 1, 1, int(active), int(active), 0, 0)
        expected[128:144] = config_body
        struct.pack_into("<QQ", expected, 144, before_frame, before_config)
        assert response == expected


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
def test_zebra_real_rgb_sink_and_saved_config_readback(builds, mode):
    data = blobs(run(builds, "vdf-" + mode, "zebra"))
    source, = data["ZEBRA_SOURCE"]
    sink, = data["ZEBRA_SINK"]
    zebra_body, = data["ZEBRA_INPUT"]
    route_active, = data["ZEBRA_ROUTE_ACTIVE"]
    route_inactive, = data["ZEBRA_ROUTE_INACTIVE"]
    initial_route = bytes([0, 1, 1]) + bytes(13)
    assert zebra_body == bytes([3, 0, 0x20, 75, 65, 0, 0, 0])
    assert source == sink and len(source) == 128 * 64 * 3 and len(set(source)) > 10
    assert any(r != g or g != b for r, g, b in zip(source[0::3], source[1::3], source[2::3]))
    for name, frame, generation, before_frame, before_config, active, route in (
            ("ZEBRA_INITIAL", 0, 3, 0, 2, False, initial_route),
            ("ZEBRA_INITIAL_REPEAT", 0, 4, 0, 3, False, initial_route),
            ("ZEBRA_ACTIVE", 3, 6, 2, 5, True, route_active),
            ("ZEBRA_REPEAT", 4, 7, 3, 6, True, route_active),
            ("ZEBRA_INACTIVE", 4, 9, 4, 8, False, route_inactive)):
        response, = data[name]
        expected = bytearray(168)
        struct.pack_into("<IIQQQQQQQQ", expected, 0,
                         1, 168, 77, generation, frame, frame if active else 0, fnv(zebra_body),
                         fnv(source) if active else 0, fnv(sink) if active else 0,
                         len(source) if active else 0)
        struct.pack_into("<14I", expected, 72, 128, 64, 384, 0x90590819, 1, 1,
                         int(active), int(active), 1, 1, int(active), int(active), 0, 0)
        expected[128:144] = route
        struct.pack_into("<QQ", expected, 144, before_frame, before_config)
        expected[160:168] = zebra_body
        assert response == expected


LAYOUT_BODY = bytes.fromhex("07010100000000008002e0010000000000000000000000000300000000000000")
PEAKING_INPUT = struct.pack("<II", 0x0152, 8) + bytes.fromhex("0300010000eb8080")
FLAG_INPUT = struct.pack("<II", 0x0162, 2) + bytes(8)


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
def test_layout_real_rgb_sink_golden_and_transaction_failures(builds, mode):
    data = blobs(run(builds, "vdf-" + mode, "layout"))
    source, = data["LAYOUT_SOURCE"]
    sink, = data["LAYOUT_SINK"]
    body, = data["LAYOUT_INPUT"]
    route, = data["LAYOUT_ROUTE"]
    assert body == LAYOUT_BODY
    assert route == bytes([1, 5, 5, 0xA9, 2, 0, 0, 0, 0x67]) + bytes(7)
    assert source == sink and len(source) == 640 * 480 * 3 and len(set(source)) > 10
    assert any(r != g or g != b for r, g, b in zip(source[0::3], source[1::3], source[2::3]))
    for name, frame, generation, before_frame, before_config in (
            ("LAYOUT", 4, 5, 3, 4), ("LAYOUT_REPEAT", 5, 6, 4, 5)):
        response, = data[name]
        expected = bytearray(192)
        struct.pack_into("<IIQQQQQQQQ", expected, 0, 1, 192, 77, generation, frame,
                         frame, fnv(LAYOUT_BODY), fnv(source), fnv(sink), len(source))
        struct.pack_into("<14I", expected, 72, 640, 480, 1920, 0x90590819,
                         1, 1, 1, 1, 1, 1, 1, 1, 0, 0)
        expected[128:144] = route
        struct.pack_into("<QQ", expected, 144, before_frame, before_config)
        expected[160:] = LAYOUT_BODY
        assert response == expected
    state, = data["LAYOUT_STATE"]
    expected = bytearray(128)
    struct.pack_into("<8I", expected, 0, 1, 15, 640, 480, 117, 13, 800, 640)
    struct.pack_into("<9Q", expected, 32, 8642, (1 << 64) - 1, 77, 6, 5, 4, 0, 0, 0)
    struct.pack_into("<IIQ", expected, 104, 0, 0, 5)
    assert state == expected


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
def test_display_real_rgb_golden_feature_isolation_and_transaction_failures(builds, mode):
    data = blobs(run(builds, "vdf-" + mode, "display"))
    assert data["PEAKING_INPUT"] == [PEAKING_INPUT] and data["FLAG_INPUT"] == [FLAG_INPUT]
    route, = data["DISPLAY_ROUTE"]
    assert route == bytes([1, 5, 5, 0xA9, 2, 0, 0, 0, 0x67]) + bytes(7)
    for name, body, frame, generation, source_name in (
            ("PEAKING", PEAKING_INPUT, 5, 5, "PEAKING"),
            ("FLAG", FLAG_INPUT, 6, 6, "FLAG"),
            ("PEAKING_REPEAT", PEAKING_INPUT, 7, 7, "PEAKING")):
        source, = data[source_name + "_SOURCE"]
        sink, = data[source_name + "_SINK"]
        assert source == sink and len(source) == 640 * 480 * 3
        assert len(set(zip(source[0::3], source[1::3], source[2::3]))) > 1
        assert any(r != g or g != b for r, g, b in zip(source[0::3], source[1::3], source[2::3]))
        response, = data[name]
        expected = bytearray(176)
        struct.pack_into("<IIQQQQQQQQ", expected, 0, 1, 176, 77, generation, frame,
                         frame, fnv(body), fnv(source), fnv(sink), len(source))
        struct.pack_into("<14I", expected, 72, 640, 480, 1920, 0x90590819,
                         1, 1, 1, 1, 1, 1, 1, 1, 0, 0)
        expected[128:144] = route
        struct.pack_into("<QQ", expected, 144, frame - 1, generation - 1)
        expected[160:] = body
        assert response == expected
    state, = data["DISPLAY_STATE"]
    expected = bytearray(128)
    struct.pack_into("<8I", expected, 0, 1, 15, 640, 480, 30, 90, 400, 100)
    struct.pack_into("<9Q", expected, 32, 16667, 3000000, 77, 6, 6, 5, 0, 0, 0)
    struct.pack_into("<IIQ", expected, 104, 0, 0, 6)
    assert state == expected


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("chunk", [1, 63, DATA_BYTES])
def test_sequential_chunks_are_actual_decodable_bytes(builds, mode, chunk):
    data = blobs(run(builds, mode, "chunks", chunk))
    image = jpeg(data["JPEG"][0])
    assert image.size == (128, 64)
    assert len(set(image.convert("RGB").tobytes())) > 10


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("quality", [1, 50, 100])
def test_libjpeg_quality_policy_and_decode(builds, mode, quality):
    image = jpeg(blobs(run(builds, mode, "quality", quality))["JPEG"][0])
    assert image.size == (128, 64)
    if quality == 1:
        assert all(value == 255 for table in image.quantization.values() for value in table)
    elif quality == 100:
        assert all(value == 1 for table in image.quantization.values() for value in table)
    else:
        assert image.quantization[0][:8] == [16, 11, 10, 16, 24, 40, 51, 61]
        assert image.quantization[1][:8] == [17, 18, 24, 47, 99, 99, 99, 99]


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("count", [2, 4])
def test_real_af_jpeg_scans_and_native_packet_metadata(builds, mode, count):
    data = blobs(run(builds, mode, "products", count))
    assert len(data["JPEG"]) == len(data["SCAN"]) == len(data["AF"]) == 2
    for variant, (full, scan, raw, af) in enumerate(zip(
            data["JPEG"], data["SCAN"], data["STILL_RGB"], data["AF"])):
        focus, score, coarse, refine = struct.unpack_from("<QQII", af)
        assert abs(focus / 1e6 - (4 if variant else 1)) < (0.25 if variant else 0.08)
        assert score > 0 and coarse == 17 and 0 < refine <= 12 and af[24:] == bytes(8)
        parts = segments(full)
        assert [part[0] for part in parts] == [0xDB, 0xC4, 0xC0, 0xDA]
        assert parts[-1][1] == 575
        assert full == full[:575] + scan and scan[:2] == b"\xff\xda" and scan[-2:] == b"\xff\xd9"
        if variant:
            assert parts[0][2] == b"".join(
                bytes([table]) + bytes(3 + table + z % 13 for z in range(64)) for table in range(2))
        image = jpeg(full)
        reassembled = jpeg(full[:575] + scan)
        assert image.size == (128, 64) and image.tobytes() == reassembled.tobytes()
        assert error(image.convert("RGB").tobytes(), raw) < 8
    assert data["JPEG"][0] != data["JPEG"][1]
    assert data["STILL_RGB"][0] != data["STILL_RGB"][1]
    assert jpeg(data["WIDE"][0]).size == (2048, 16)

    assert len(data["PACKET"]) == len(data["VIDEO_RGB"]) == count
    elementary = bytearray()
    config = None
    for index, record in enumerate(data["PACKET"]):
        (width, height, pts, dts, duration, tb_num, tb_den, key, flags,
         packet_size, generation, config_size, codec) = struct.unpack_from("<IIqqqIIIIQQII", record)
        assert (width, height, pts, dts, duration, tb_num, tb_den) == (128, 64, index, index, 1, 1, 25)
        assert generation == index + 7 and flags == 0 and codec == 0x61766331
        assert record[72:96] == bytes(24)
        assert packet_size > 0 and config_size > 0 and len(record) == 96 + config_size + packet_size
        actual_config = record[96:96 + config_size]
        assert nals(actual_config) == [7, 8]
        if config is None:
            config = actual_config
            assert key == 1
        assert actual_config == config
        packet = record[96 + config_size:]
        assert nals(packet)
        elementary.extend(packet)
    eos, = data["EOS"]
    assert len(eos) == 96 and u32(eos, 44) == 1 and u64(eos, 48) == u32(eos, 64) == 0
    decoded = decode_h264(bytes(elementary))
    frame_bytes = 128 * 64 * 3
    assert len(decoded) == count * frame_bytes
    for index, raw in enumerate(data["VIDEO_RGB"]):
        frame = decoded[index * frame_bytes:(index + 1) * frame_bytes]
        assert error(frame, raw) < 12
        assert error(frame, raw) < error(frame, bytes([0xCC]) * frame_bytes)
    state, = data["STATE"]
    assert len(state) == STATE_BYTES and u32(state, 108) == 2 and u32(state, 104) == 0
    assert [u64(state, offset) for offset in (64, 72, 80, 88, 112)] == [count + 6, count + 5, 5, count, count + 6]
    assert u64(state, 96) == sum(map(len, data["JPEG"] + data["SCAN"] + data["WIDE"] +
                                     data["PACKET"] + data["EOS"]))


class ExecResult(ctypes.Structure):
    _fields_ = [("token", ctypes.c_uint64), ("total", ctypes.c_uint64),
                ("offset", ctypes.c_uint64), ("used", ctypes.c_size_t)]


class Model:
    def __init__(self, library):
        self.lib = ctypes.CDLL(str(library), use_errno=True)
        self.lib.fcam_model_create.argtypes = [ctypes.c_uint64]
        self.lib.fcam_model_create.restype = ctypes.c_void_p
        self.lib.fcam_model_destroy.argtypes = [ctypes.c_void_p]
        self.lib.fcam_model_destroy.restype = None
        self.lib.fcam_model_request.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t, ctypes.POINTER(ExecResult)]
        self.lib.fcam_model_request.restype = ctypes.c_int
        self.handle = self.lib.fcam_model_create(7)
        assert self.handle, ctypes.get_errno()
        state, _ = self.request(1)
        assert u64(state, 64) == u64(state, 112) == 1
        assert [u64(state, offset) for offset in (72, 80, 88)] == [0, 0, 0]

    def close(self):
        self.lib.fcam_model_destroy(self.handle)
        self.handle = None

    def request(self, opcode, data=b"", capacity=STATE_BYTES, expected=0):
        source = (ctypes.c_uint8 * len(data)).from_buffer_copy(data) if data else None
        destination = (ctypes.c_uint8 * capacity)(*([0xA5] * capacity)) if capacity else None
        result = ExecResult.from_buffer_copy(bytes([0x59]) * ctypes.sizeof(ExecResult))
        before = bytes(result)
        code = self.lib.fcam_model_request(self.handle, opcode, source, len(data), destination,
                                           capacity, ctypes.byref(result))
        assert code == expected
        if code:
            assert bytes(result) == before
            assert destination is None or bytes(destination) == bytes([0xA5]) * capacity
            return None
        assert result.used <= capacity
        return bytes(destination)[:result.used] if destination is not None else b"", result

    def encoded(self, opcode, data=b"", chunk=63):
        first, info = self.request(opcode, data, chunk)
        assert info.token and info.total
        token, total = info.token, info.total
        output = bytearray(first)
        while len(output) < total:
            value, info = self.request(64, struct.pack("<QQII", token, len(output), chunk, 0), chunk)
            assert info.token == token and info.total == total and info.offset == len(output)
            assert value
            output.extend(value)
        self.request(65, struct.pack("<QQ", token, fnv(output)), 0)
        return bytes(output)


def config(*, width=128, height=64, fps=25, quality=90, fnumber=400,
           iso=100, shutter=2500, focus=1000000):
    return struct.pack("<IIIIIIQQII", width, height, fps, quality, fnumber, iso,
                       shutter, focus, 0, 0)


def test_ctypes_vdf_fixed_reply_commits_and_preserves_encoded_counters(builds):
    model = Model(builds["library"])
    try:
        model.request(3, config())
        before, _ = model.request(2)
        active = bytes([1, 5, 5]) + bytes(13)
        for index, body in enumerate((active, active, bytes([0, 1, 1]) + bytes(13)), 1):
            receipt, info = model.request(5, body, 160)
            state, _ = model.request(2)
            frames = min(index, 2)
            assert len(receipt) == 160 and info.used == 160 and not info.token and not info.total
            assert receipt[128:144] == body and u64(receipt, 40) == fnv(body)
            assert u64(receipt, 16) == u64(before, 56) + index == u64(state, 56)
            assert u64(receipt, 24) == u64(before, 112) + frames == u64(state, 112)
            assert u64(state, 64) == u64(before, 64) + frames
            assert u64(state, 72) == u64(before, 72) + frames
            assert all(u64(state, offset) == u64(before, offset) for offset in (80, 88, 96))
            assert u32(state, 104) == 0 and u32(receipt, 92) == u32(receipt, 108) == 1
            if index <= 2:
                assert u64(receipt, 48) == u64(receipt, 56) != 0 and u64(receipt, 64) == 128 * 64 * 3
            else:
                assert u64(receipt, 48) == u64(receipt, 56) == u64(receipt, 64) == 0
                assert u32(receipt, 112) == u32(receipt, 116) == 0
    finally:
        model.close()


@pytest.mark.parametrize("changes", [{}, dict(width=64, height=32, fps=117, quality=13,
                         fnumber=1600, iso=640, shutter=8642, focus=(1 << 64) - 1)])
def test_ctypes_zebra_preserves_config48_and_tracks_current_route(builds, changes):
    model = Model(builds["library"])
    try:
        settings = config(**changes)
        model.request(3, settings)
        route = bytes([0, 1, 1]) + bytes(13)
        zebra_body = bytes([0xF1, 0, 0x92, 0x73, 0xB4, 0, 0, 0])
        before, _ = model.request(2)
        model.request(6, zebra_body, 167, expected=-errno.ENOSPC)
        assert model.request(2)[0] == before
        for operation in (6, 5, 6, 6, 5, 6):
            if operation == 5:
                route = (bytes([1, 5, 5, 0xA9, 2]) + bytes(11) if route[0] == 0 else
                         bytes([0, 1, 1, 0x79, 1]) + bytes(11))
            active = bool(route[0])
            previous, _ = model.request(2)
            receipt, info = model.request(operation, zebra_body if operation == 6 else route,
                                          168 if operation == 6 else 160)
            current, _ = model.request(2)
            assert current[8:48] == previous[8:48] == settings[:40]
            assert u64(current, 56) == u64(previous, 56) + 1
            assert all(u64(current, offset) == u64(previous, offset) + int(active)
                       for offset in (64, 72, 112))
            assert all(u64(current, offset) == u64(before, offset) for offset in (80, 88, 96))
            assert receipt[128:144] == route and u32(receipt, 96) == u32(receipt, 100) == int(active)
            assert u64(receipt, 40) == fnv(zebra_body if operation == 6 else route)
            assert u64(receipt, 144) == u64(previous, 112) and u64(receipt, 152) == u64(previous, 56)
            assert u32(receipt, 88) == u32(receipt, 92) == u32(receipt, 104) == u32(receipt, 108) == 1
            assert not info.token and not info.total and not info.offset and info.used == len(receipt)
            if operation == 6:
                assert receipt[160:] == zebra_body
            if active:
                assert u64(receipt, 48) == u64(receipt, 56) != 0 and u64(receipt, 32) > 0
                assert u64(receipt, 64) == u32(settings, 0) * u32(settings, 4) * 3
            else:
                assert all(u64(receipt, offset) == 0 for offset in (32, 48, 56, 64))
            assert u32(receipt, 112) == u32(receipt, 116) == int(active)
            assert model.request(1)[0] == current
    finally:
        model.close()


@pytest.mark.parametrize("changes", [{}, dict(fps=117, quality=13, fnumber=800, iso=640,
                                            shutter=8642, focus=(1 << 64) - 1)])
def test_ctypes_layout_mixed_route_zebra_and_duplicate_init(builds, changes):
    model = Model(builds["library"])
    try:
        settings = config(width=640, height=480, **changes)
        model.request(3, settings)
        before, _ = model.request(2)
        model.request(7, LAYOUT_BODY, 192, expected=-errno.ENODATA)
        assert model.request(2)[0] == before
        zebra_body = bytes([3, 0, 0x20, 75, 65, 0, 0, 0])
        route = bytes([1, 5, 5, 0xA9, 2]) + bytes(11)
        model.request(5, route, 160)
        model.request(6, zebra_body, 168)
        for _ in range(2):
            previous, _ = model.request(2)
            model.request(7, LAYOUT_BODY, 191, expected=-errno.ENOSPC)
            malformed = bytearray(LAYOUT_BODY)
            malformed[22] = 1
            model.request(7, malformed, 192, expected=-errno.ENOTSUP)
            assert model.request(2)[0] == previous
            receipt, info = model.request(7, LAYOUT_BODY, 192)
            current, _ = model.request(2)
            assert info.used == 192 and not info.token and not info.total and not info.offset
            assert receipt[128:144] == route and receipt[160:] == LAYOUT_BODY
            assert u64(receipt, 40) == fnv(LAYOUT_BODY)
            assert current[8:48] == previous[8:48] == settings[:40]
            assert u64(receipt, 16) == u64(current, 56) == u64(previous, 56) + 1
            assert u64(receipt, 24) == u64(current, 112) == u64(previous, 112) + 1
            assert all(u64(current, offset) == u64(previous, offset) + 1 for offset in (64, 72))
            assert all(u64(current, offset) == u64(previous, offset) for offset in (80, 88, 96))
            assert u64(receipt, 48) == u64(receipt, 56) != 0 and u64(receipt, 64) == 640 * 480 * 3
            assert u64(receipt, 32) > 0 and (u32(receipt, 72), u32(receipt, 76), u32(receipt, 80)) == (640, 480, 1920)
            assert all(u32(receipt, offset) == 1 for offset in (88, 92, 96, 100, 104, 108, 112, 116))
            assert u64(receipt, 144) == u64(previous, 112) and u64(receipt, 152) == u64(previous, 56)
            assert model.request(1)[0] == current
        inactive = bytes([0, 1, 1]) + bytes(13)
        model.request(5, inactive, 160)
        previous, _ = model.request(2)
        model.request(7, LAYOUT_BODY, 192, expected=-errno.ENODATA)
        assert model.request(2)[0] == previous
        route = bytes([1, 5, 5, 0x79, 1]) + bytes(11)
        model.request(5, route, 160)
        receipt, _ = model.request(7, LAYOUT_BODY, 192)
        assert receipt[128:144] == route and receipt[160:] == LAYOUT_BODY
        model.request(3, config(width=640, height=479, **changes))
        previous, _ = model.request(2)
        model.request(7, LAYOUT_BODY, 192, expected=-errno.ENOTSUP)
        assert model.request(2)[0] == model.request(1)[0] == previous
    finally:
        model.close()


@pytest.mark.parametrize("changes", [{}, dict(fps=117, quality=13, fnumber=800, iso=640,
                                            shutter=8642, focus=(1 << 64) - 1)])
def test_ctypes_display_mixed_path_zebra_layout_and_duplicate_init(builds, changes):
    model = Model(builds["library"])
    try:
        settings = (config(width=640, height=480, **changes) if changes else
                    config(width=640, height=480, fps=30, shutter=16667, focus=3000000))
        if changes:
            model.request(3, settings)
        initial, _ = model.request(2)
        assert u64(initial, 56) == (2 if changes else 1)
        for body in (PEAKING_INPUT, FLAG_INPUT):
            model.request(8, body, 176, expected=-errno.ENODATA)
        assert model.request(2)[0] == initial
        route = bytes([1, 5, 5, 0xA9, 2]) + bytes(11)
        zebra_body = bytes([3, 0, 0x20, 75, 65, 0, 0, 0])
        for index, (operation, body, size) in enumerate((
                (5, route, 160), (6, zebra_body, 168), (7, LAYOUT_BODY, 192),
                (8, PEAKING_INPUT, 176), (8, FLAG_INPUT, 176)), 1):
            previous, _ = model.request(2)
            if operation == 8:
                model.request(8, body, 175, expected=-errno.ENOSPC)
                assert model.request(2)[0] == previous
            receipt, info = model.request(operation, body, size)
            current, _ = model.request(2)
            assert len(receipt) == info.used == size and not info.token and not info.total and not info.offset
            assert current[8:48] == previous[8:48] == settings[:40]
            assert u64(current, 48) == u64(receipt, 8) == u64(initial, 48)
            assert u64(current, 56) == u64(receipt, 16) == u64(initial, 56) + index
            assert u64(current, 64) == u64(current, 112) == u64(receipt, 24) == index + 1
            assert u64(current, 72) == index and all(u64(current, offset) == 0 for offset in (80, 88, 96))
            assert receipt[128:144] == route and u64(receipt, 40) == fnv(body)
            assert u64(receipt, 48) == u64(receipt, 56) != 0 and u64(receipt, 64) == 640 * 480 * 3
            assert u64(receipt, 32) == index + 1
            assert all(u32(receipt, offset) == 1 for offset in (88, 92, 96, 100, 104, 108, 112, 116))
            assert u64(receipt, 144) == u64(previous, 112) and u64(receipt, 152) == u64(previous, 56)
            if operation != 5:
                assert receipt[160:] == body
        assert u64(current, 56) == (7 if changes else 6)
        assert model.request(1)[0] == model.request(2)[0] == current
        # Read each saved feature again after the other feature's transaction.
        for body in (PEAKING_INPUT, FLAG_INPUT):
            receipt, _ = model.request(8, body, 176)
            assert receipt[160:] == body and receipt[128:144] == route
        model.request(5, bytes([0, 1, 1]) + bytes(13), 160)
        previous, _ = model.request(2)
        for body in (PEAKING_INPUT, FLAG_INPUT):
            model.request(8, body, 176, expected=-errno.ENODATA)
        assert model.request(2)[0] == previous
    finally:
        model.close()


@pytest.mark.parametrize("geometry", [(1, 1), (127, 63)])
def test_ctypes_display_passthrough_uses_current_rgb_geometry(builds, geometry):
    model = Model(builds["library"])
    try:
        settings = config(width=geometry[0], height=geometry[1], fnumber=1600,
                          iso=640, shutter=8642, focus=(1 << 64) - 1)
        model.request(3, settings)
        route = bytes([1, 5, 5]) + bytes(13)
        model.request(5, route, 160)
        for body in (PEAKING_INPUT, FLAG_INPUT):
            previous, _ = model.request(2)
            receipt, info = model.request(8, body, 176)
            current, _ = model.request(2)
            assert info.used == 176 and receipt[160:] == body and receipt[128:144] == route
            assert current[8:48] == settings[:40] and u64(current, 56) == u64(previous, 56) + 1
            assert all(u64(current, offset) == u64(previous, offset) + 1 for offset in (64, 72, 112))
            assert u64(receipt, 48) == u64(receipt, 56) != 0
            assert u64(receipt, 64) == geometry[0] * geometry[1] * 3
            assert (u32(receipt, 72), u32(receipt, 76), u32(receipt, 80)) == (*geometry, geometry[0] * 3)
            assert model.request(1)[0] == current
    finally:
        model.close()


def test_ctypes_broker_exposure_focus_and_counter_lifetime(builds):
    model = Model(builds["library"])
    try:
        pixels = []
        for changes in ({}, {"focus": 4000000}, {"shutter": 5000}, {"iso": 50}, {"fnumber": 800}):
            model.request(3, config(**changes))
            product = model.encoded(16, struct.pack("<IIII", 1, 128, 64, 95))
            pixels.append(jpeg(product).convert("RGB").tobytes())
        assert pixels[0] != pixels[1] and error(pixels[0], pixels[1]) > 1
        assert sum(pixels[2]) > sum(pixels[0]) > sum(pixels[3]) > sum(pixels[4])
        state, _ = model.request(2)
        assert u64(state, 56) == 6
        assert [u64(state, offset) for offset in (64, 72, 80, 112)] == [6, 5, 5, 6]
        assert u64(state, 48) == 7 and u32(state, 4) == 15
        prior = state
        model.request(3, config(width=8193), expected=-errno.ERANGE)
        assert model.request(2)[0] == prior
        model.request(3, config(width=8192, height=8192))
        prior = model.request(2)[0]
        model.request(32, config(width=8192, height=8192), expected=-errno.ERANGE)
        assert model.request(2)[0] == prior
        model.request(66)
        assert u64(model.request(2)[0], 64) == 6
    finally:
        model.close()


def test_ctypes_live_pending_result_cancel_and_real_eos(builds):
    model = Model(builds["library"])
    try:
        model.request(32, config())
        model.request(3, config(), expected=-errno.EBUSY)
        first, info = model.request(33, capacity=1)
        assert len(first) == 1 and info.token and info.total > 96
        token = info.token
        model.request(34, capacity=DATA_BYTES, expected=-errno.EBUSY)
        model.request(65, struct.pack("<QQ", token, 0), 0, expected=-errno.EBUSY)
        model.request(66)
        model.request(64, struct.pack("<QQII", token, 1, 1, 0), 1, expected=-errno.ESTALE)
        state, _ = model.request(2)
        assert u32(state, 108) == 0 and u64(state, 72) == u64(state, 88) == 1
        model.request(32, config())
        packet = model.encoded(33, chunk=DATA_BYTES)
        size = u64(packet, 48)
        assert size > 0 and len(packet) == 96 + u32(packet, 64) + size
        eos = model.encoded(34, chunk=1)
        assert len(eos) == 96 and u32(eos, 44) == 1 and u64(eos, 48) == 0
        assert len(decode_h264(packet[96 + u32(packet, 64):])) == 128 * 64 * 3
        state, _ = model.request(2)
        assert u32(state, 108) == 2 and u64(state, 72) == u64(state, 88) == 2
    finally:
        model.close()
