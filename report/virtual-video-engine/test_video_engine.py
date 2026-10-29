"""Host-only codec/mux checks. All media stays in memory or subprocess pipes."""

import ctypes as C
import io
import json
import math
import os
from pathlib import Path
import shlex
import subprocess

import pytest

ROOT = Path(__file__).resolve().parent
GUARD = 16
OK, INVALID, TOO_SMALL, OUTPUT_SMALL, OVERFLOW, OVERLAP, NO_MEMORY, CODEC = range(8)
STATE, SINK_ERROR = 8, 9
IDLE, ACTIVE, FINISHED, CANCELLED, FAULT = range(5)


class RGB(C.Structure):
    _fields_ = [("data", C.c_void_p), ("size", C.c_size_t), ("stride", C.c_size_t)]


class Packet(C.Structure):
    _fields_ = [("offset", C.c_size_t), ("size", C.c_size_t),
                ("pts", C.c_int64), ("dts", C.c_int64),
                ("duration", C.c_int64), ("keyframe", C.c_int)]


class Result(C.Structure):
    _fields_ = [("status", C.c_int), ("codec_error", C.c_int)] + [
        (name, C.c_size_t) for name in (
            "used", "required", "packet_count", "packets_required", "config_used",
            "config_required", "frames_consumed", "packets_flushed")]


class StreamPacket(C.Structure):
    _fields_ = [("data", C.c_void_p)] + Packet._fields_[1:]


class StreamInfo(C.Structure):
    _fields_ = [(name, C.c_int) for name in (
        "state", "status", "codec_error", "sink_error")] + [
        (name, C.c_uint64) for name in (
            "frames_consumed", "packets_received", "packets_published",
            "bytes_published", "packets_flushed")]


Sink = C.CFUNCTYPE(C.c_int, C.POINTER(StreamPacket), C.c_void_p)


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("host-video-engine")
    compiler = shlex.split(os.environ.get("CC", "cc"))
    flags = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True))
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    source = str(ROOT / "video-engine.c")
    test = str(ROOT / "test-video-engine.c")
    for name, options in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        subprocess.run(compiler + strict + options + [source, test,
                       "-Wl,--wrap=avcodec_send_frame", "-o",
                       str(directory / name)] + flags, check=True)
        subprocess.run(compiler + strict + options + [source,
                       str(ROOT / "test-video-stream.c"),
                       "-Wl,--wrap=avcodec_send_frame",
                       "-Wl,--wrap=avcodec_receive_packet",
                       "-Wl,--wrap=av_frame_make_writable",
                       "-Wl,--wrap=avcodec_open2", "-o",
                       str(directory / (name + "-stream"))] + flags, check=True)
        subprocess.run(compiler + strict + options + [source,
                       str(ROOT / "example-optical-stream.c"),
                       str(ROOT.parent / "virtual-optical-frame-owner" / "optical-frame-owner.c"),
                       str(ROOT.parent / "virtual-optics" / "optics.c"),
                       "-o", str(directory / (name + "-optical"))] + flags + ["-lm"], check=True)
    shared = directory / "libvideo-engine.so"
    subprocess.run(compiler + strict + ["-O2", "-shared", "-fPIC", source,
                   "-o", str(shared)] + flags, check=True)
    library = C.CDLL(str(shared))
    library.video_engine_encode_rgb888.argtypes = [
        C.POINTER(RGB), C.c_size_t, C.c_size_t, C.c_size_t, C.c_uint,
        C.c_void_p, C.c_size_t, C.POINTER(Packet), C.c_size_t,
        C.c_void_p, C.c_size_t]
    library.video_engine_encode_rgb888.restype = Result
    library.video_engine_mux_mp4.argtypes = [
        C.c_void_p, C.c_size_t, C.POINTER(Packet), C.c_size_t,
        C.c_void_p, C.c_size_t, C.c_size_t, C.c_size_t, C.c_uint,
        C.c_void_p, C.c_size_t]
    library.video_engine_mux_mp4.restype = Result
    library.video_engine_stream_create.argtypes = []
    library.video_engine_stream_create.restype = C.c_void_p
    library.video_engine_stream_destroy.argtypes = [C.c_void_p]
    library.video_engine_stream_destroy.restype = None
    library.video_engine_stream_begin.argtypes = [
        C.c_void_p, C.c_size_t, C.c_size_t, C.c_uint, C.c_size_t, Sink, C.c_void_p]
    library.video_engine_stream_begin.restype = C.c_int
    library.video_engine_stream_feed_rgb888.argtypes = [
        C.c_void_p, C.POINTER(RGB), C.c_int64, C.c_int64]
    library.video_engine_stream_feed_rgb888.restype = C.c_int
    for name in ("drain", "finish", "cancel"):
        operation = getattr(library, "video_engine_stream_" + name)
        operation.argtypes = [C.c_void_p]
        operation.restype = C.c_int
    library.video_engine_stream_snapshot.argtypes = [C.c_void_p]
    library.video_engine_stream_snapshot.restype = StreamInfo
    return directory, library


def scene(width=64, height=48, count=5, padding=7, padding_byte=0xA6):
    stride = width * 3 + padding
    frames = []
    for index in range(count):
        pixels = bytearray([padding_byte]) * ((height - 1) * stride + width * 3)
        for y in range(height):
            for x in range(width):
                target = 4 + 6 * index <= x < 20 + 6 * index and 12 <= y < 28
                color = ((210, 170, 180) if target else
                         (25 + x, 30 + y, 45 + (x + y) // 3))
                offset = y * stride + x * 3
                pixels[offset:offset + 3] = bytes(min(255, c + index * 7) for c in color)
        frames.append(bytes(pixels))
    return frames, stride


def guarded(capacity):
    buffer = C.create_string_buffer(capacity + GUARD * 2)
    C.memset(buffer, 0xA5, C.sizeof(buffer))
    return buffer, C.addressof(buffer) + GUARD


def guard_check(buffer, capacity):
    assert buffer.raw[:GUARD] == b"\xa5" * GUARD
    assert buffer.raw[GUARD + capacity:] == b"\xa5" * GUARD


def encode(library, images, width, height, stride, fps=25, capacities=None):
    sources = [C.create_string_buffer(image, len(image)) for image in images]
    views = (RGB * len(images))(*(RGB(C.addressof(src), len(image), stride)
                                for src, image in zip(sources, images, strict=True)))
    if capacities is None:
        query = library.video_engine_encode_rgb888(
            views, len(images), width, height, fps, None, 0, None, 0, None, 0)
        assert query.status == OUTPUT_SMALL and query.used == 0
        capacities = query.required, query.packets_required, query.config_required
    capacity, packet_capacity, config_capacity = capacities
    dest, address = guarded(capacity)
    metadata, meta_address = guarded(packet_capacity * C.sizeof(Packet))
    config, config_address = guarded(config_capacity)
    packets = C.cast(meta_address, C.POINTER(Packet))
    result = library.video_engine_encode_rgb888(
        views, len(images), width, height, fps, address, capacity,
        packets, packet_capacity, config_address, config_capacity)
    for source, image in zip(sources, images, strict=True):
        assert source.raw == image
    guard_check(dest, capacity)
    guard_check(metadata, packet_capacity * C.sizeof(Packet))
    guard_check(config, config_capacity)
    if result.status != OK:
        assert result.used == result.packet_count == result.config_used == 0
        assert dest.raw == b"\xa5" * C.sizeof(dest)
        assert metadata.raw == b"\xa5" * C.sizeof(metadata)
        assert config.raw == b"\xa5" * C.sizeof(config)
    # Copy metadata: callers must not retain a ctypes view into temporary storage.
    copied = (Packet * result.packet_count).from_buffer_copy(
        metadata.raw[GUARD:GUARD + result.packet_count * C.sizeof(Packet)])
    return result, dest.raw[GUARD:GUARD + result.used], copied, config.raw[
        GUARD:GUARD + result.config_used]


def mux(library, payload, packets, config, width, height, fps, capacity=None):
    source = C.create_string_buffer(payload, len(payload))
    settings = C.create_string_buffer(config, len(config))
    arguments = [source, len(payload), packets, len(packets), settings, len(config),
                 width, height, fps]
    if capacity is None:
        query = library.video_engine_mux_mp4(*arguments, None, 0)
        assert query.status == OUTPUT_SMALL and query.used == 0
        capacity = query.required
    dest, address = guarded(capacity)
    result = library.video_engine_mux_mp4(*arguments, address, capacity)
    guard_check(dest, capacity)
    assert source.raw == payload and settings.raw == config
    if result.status != OK:
        assert result.used == result.packet_count == result.config_used == 0
    if result.status == OUTPUT_SMALL:
        assert dest.raw == b"\xa5" * C.sizeof(dest)
    return result, dest.raw[GUARD:GUARD + result.used]


def decode(payload, format_name, width, height, count):
    completed = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-f", format_name,
        "-i", "pipe:0", "-map", "0:v:0", "-fps_mode", "passthrough", "-f", "rawvideo",
        "-pix_fmt", "rgb24", "pipe:1"], input=payload, capture_output=True, check=True,
        timeout=20)
    assert not completed.stderr
    size = width * height * 3
    assert len(completed.stdout) == size * count
    return [completed.stdout[i * size:(i + 1) * size] for i in range(count)]


def probe(payload, format_name, *, packets=False):
    completed = subprocess.run([
        "ffprobe", "-v", "error", "-f", format_name, "-i", "pipe:0", "-count_frames",
        "-show_streams", "-show_packets" if packets else "-show_frames", "-of", "json"],
        input=payload, capture_output=True, check=True, timeout=20)
    assert not completed.stderr
    return json.loads(completed.stdout)


def correlation(a, b):
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    variance_a = sum((x - mean_a) ** 2 for x in a)
    variance_b = sum((y - mean_b) ** 2 for y in b)
    return covariance / math.sqrt(variance_a * variance_b)


def assert_content(decoded, images, width, height, stride):
    for actual, image in zip(decoded, images, strict=True):
        expected = b"".join(image[y * stride:y * stride + width * 3]
                            for y in range(height))
        assert sum(abs(a - b) for a, b in zip(actual, expected, strict=True)) / len(actual) < 7
        for channel in range(3):
            assert correlation(actual[channel::3], expected[channel::3]) > 0.94
    assert decoded[0] != decoded[-1]


def packet_values(packets):
    return [tuple(getattr(packet, name) for name, _ in Packet._fields_)
            for packet in packets]


def nal_types(payload):
    types = []
    index = 0
    while index + 3 < len(payload):
        if payload[index:index + 3] == b"\x00\x00\x01":
            types.append(payload[index + 3] & 31)
            index += 4
        else:
            index += 1
    return types


@pytest.mark.parametrize("name", ["normal", "sanitized"])
def test_c_selfchecks(builds, name):
    directory, _ = builds
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    completed = subprocess.run([str(directory / name)], env=environment,
                               capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert b"6 C self-test groups passed" in completed.stdout


@pytest.mark.parametrize("count", [2, 6])
def test_elementary_real_rgb_decode(builds, count):
    _, library = builds
    width, height = 64, 48
    images, stride = scene(width, height, count)
    result, payload, packets, config = encode(library, images, width, height, stride)
    assert result.status == OK and result.frames_consumed == count
    assert result.packet_count == count and result.packets_flushed == 0
    assert 7 in nal_types(config) and 8 in nal_types(config)
    assert {1, 5, 7, 8}.issubset(nal_types(payload))
    offset = 0
    for index, packet in enumerate(packets):
        assert packet.offset == offset and packet.size > 0
        assert packet.pts == packet.dts == index and packet.duration == 1
        assert nal_types(payload[offset:offset + packet.size])
        offset += packet.size
    assert offset == len(payload)
    information = probe(payload, "h264")
    stream = information["streams"][0]
    assert stream["codec_name"] == "h264" and stream["profile"] == "Constrained Baseline"
    assert (stream["width"], stream["height"]) == (width, height)
    assert stream["pix_fmt"] == "yuv420p" and stream["color_space"] == "bt709"
    assert int(stream["nb_read_frames"]) == len(information["frames"]) == count
    assert_content(decode(payload, "h264", width, height, count), images, width, height, stride)


def test_mp4_actual_packets_and_timestamps(builds):
    _, library = builds
    width, height, fps, count = 64, 48, 24, 5
    images, stride = scene(width, height, count)
    result, payload, packets, config = encode(library, images, width, height, stride, fps)
    assert result.status == OK
    result, movie = mux(library, payload, packets, config, width, height, fps)
    assert result.status == OK and result.used == result.required
    assert movie[4:8] == b"ftyp" and b"mdat" in movie and b"moov" in movie
    information = probe(movie, "mov")
    assert len(information["streams"]) == 1
    stream = information["streams"][0]
    assert stream["codec_name"] == "h264" and stream["codec_type"] == "video"
    assert (stream["width"], stream["height"]) == (width, height)
    assert int(stream["nb_read_frames"]) == int(stream["nb_frames"]) == count
    assert float(stream["duration"]) == pytest.approx(count / fps, abs=0.000001)
    frame_pts = [float(frame["best_effort_timestamp_time"]) for frame in information["frames"]]
    packet_info = probe(movie, "mov", packets=True)["packets"]
    assert len(packet_info) == count
    for index, packet in enumerate(packet_info):
        assert float(packet["pts_time"]) == pytest.approx(index / fps, abs=0.000001)
        assert float(packet["dts_time"]) == pytest.approx(index / fps, abs=0.000001)
        assert float(packet["duration_time"]) == pytest.approx(1 / fps, abs=0.000001)
    assert all(a < b for a, b in zip(frame_pts, frame_pts[1:]))
    assert frame_pts == pytest.approx([i / fps for i in range(count)], abs=0.000001)
    decoded = decode(movie, "mov", width, height, count)
    assert_content(decoded, images, width, height, stride)
    assert decoded == decode(payload, "h264", width, height, count)


def test_exact_short_and_metadata_capacities(builds):
    _, library = builds
    images, stride = scene(count=3)
    good, payload, packets, config = encode(library, images, 64, 48, stride)
    assert good.status == OK
    for capacities in ((0, 0, 0), (good.used - 1, 3, len(config)),
                       (good.used, 2, len(config)), (good.used, 3, len(config) - 1)):
        result, empty, metadata, settings = encode(library, images, 64, 48, stride,
                                                   capacities=capacities)
        assert result.status == OUTPUT_SMALL
        assert (result.required, result.packets_required, result.config_required) == (
            good.used, 3, len(config))
        assert empty == settings == b"" and len(metadata) == 0
    exact, actual, metadata, settings = encode(library, images, 64, 48, stride,
                                               capacities=(good.used, 3, len(config)))
    assert exact.status == OK and actual == payload and settings == config
    assert packet_values(metadata) == packet_values(packets)


def test_stride_padding_does_not_change_bitstream(builds):
    _, library = builds
    results = []
    for padding, byte in ((0, 0), (11, 0x13), (11, 0xEF)):
        images, stride = scene(count=3, padding=padding, padding_byte=byte)
        result, payload, packets, config = encode(library, images, 64, 48, stride)
        assert result.status == OK
        results.append((payload, packet_values(packets), config))
    assert results[0] == results[1] == results[2]


def test_last_input_frame_is_consumed_before_eos(builds):
    _, library = builds
    images, stride = scene(count=4)
    result, payload, _, _ = encode(library, images, 64, 48, stride)
    assert result.status == OK
    original = decode(payload, "h264", 64, 48, 4)
    changed = images[:-1] + [bytes(255 - value for value in images[-1])]
    result, payload, _, _ = encode(library, changed, 64, 48, stride)
    assert result.status == OK and result.frames_consumed == 4
    decoded = decode(payload, "h264", 64, 48, 4)
    assert decoded[:3] == original[:3]
    assert sum(abs(a - b) for a, b in zip(decoded[-1], original[-1], strict=True)) / len(decoded[-1]) > 60


def test_memory_mux_short_and_invalid_packet_boundaries(builds):
    _, library = builds
    images, stride = scene(count=3)
    encoded, payload, packets, config = encode(library, images, 64, 48, stride)
    assert encoded.status == OK
    success, reference = mux(library, payload, packets, config, 64, 48, 25)
    assert success.status == OK
    for capacity in (0, 1, success.used - 1, success.used):
        result, movie = mux(library, payload, packets, config, 64, 48, 25, capacity)
        assert result.required == success.used
        if capacity < success.used:
            assert result.status == OUTPUT_SMALL and movie == b""
        else:
            assert result.status == OK and movie == reference
    for field, value in (("offset", 1), ("size", len(payload)), ("pts", 0),
                         ("dts", 0), ("duration", 0), ("keyframe", 2)):
        changed = (Packet * len(packets)).from_buffer_copy(bytes(packets))
        setattr(changed[1], field, value)
        result, _ = mux(library, payload, changed, config, 64, 48, 25, 0)
        assert result.status == INVALID and result.used == 0
    result, _ = mux(library, payload[:-1], packets, config, 64, 48, 25, 0)
    assert result.status == INVALID


def test_component_framecount_and_rate_policy_bounds(builds):
    _, library = builds
    # Exercise the declared maximum counters without allocating a large scene.
    image = bytes((80, 120, 160)) * 4
    result, payload, packets, config = encode(library, [image] * 600, 2, 2, 6, fps=120)
    assert result.status == OK and result.frames_consumed == result.packet_count == 600
    assert packets[-1].pts == packets[-1].dts == 599 and packets[-1].duration == 1
    assert result.packets_flushed == 0 and payload and config


@pytest.mark.parametrize("name", ["normal", "sanitized"])
def test_streaming_c_selfchecks(builds, name):
    directory, _ = builds
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    completed = subprocess.run([str(directory / (name + "-stream"))],
                               env=environment, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert b"8 streaming C self-test groups passed" in completed.stdout


def stream_encode(library, images, width, height, stride, fps=25, times=None):
    records = []
    callback_errors = []

    @Sink
    def sink(pointer, _context):
        try:
            packet = pointer.contents
            payload = C.string_at(packet.data, packet.size)
            records.append((payload, packet.pts, packet.dts, packet.duration, packet.keyframe))
            return 0
        except BaseException as error:
            callback_errors.append(error)
            return -1

    stream = library.video_engine_stream_create()
    assert stream
    source, source_address = guarded(max(map(len, images)))
    try:
        assert library.video_engine_stream_begin(stream, width, height, fps,
                                                65536, sink, None) == OK
        for index, image in enumerate(images):
            C.memmove(source_address, image, len(image))
            view = RGB(source_address, len(image), stride)
            pts, duration = times[index] if times else (index, 1)
            assert library.video_engine_stream_feed_rgb888(
                stream, C.byref(view), pts, duration) == OK
            assert not callback_errors
            assert source.raw[GUARD:GUARD + len(image)] == image
            # Reuse the same producer buffer immediately, before drain/finish.
            C.memset(source_address, 0xDC, len(image))
            guard_check(source, len(image))
            info = library.video_engine_stream_snapshot(stream)
            assert info.state == ACTIVE and info.status == OK
            assert info.frames_consumed == info.packets_received == info.packets_published == index + 1
            assert info.bytes_published == sum(len(record[0]) for record in records)
            assert info.codec_error == info.sink_error == info.packets_flushed == 0
            saved = tuple(records)
            assert library.video_engine_stream_drain(stream) == OK
            assert tuple(records) == saved
        assert library.video_engine_stream_finish(stream) == OK
        assert library.video_engine_stream_finish(stream) == OK
        info = library.video_engine_stream_snapshot(stream)
        assert info.state == FINISHED and info.status == OK
        assert info.frames_consumed == info.packets_received == info.packets_published == len(images)
        assert info.packets_flushed == 0
        assert library.video_engine_stream_feed_rgb888(stream, C.byref(view), 100, 1) == STATE
        assert library.video_engine_stream_drain(stream) == STATE
    finally:
        library.video_engine_stream_destroy(stream)
    return records


def stream_bytes_and_packets(records):
    payload = b"".join(record[0] for record in records)
    packets = (Packet * len(records))()
    offset = 0
    for index, (data, pts, dts, duration, keyframe) in enumerate(records):
        packets[index] = Packet(offset, len(data), pts, dts, duration, keyframe)
        offset += len(data)
    return payload, packets


def parameter_sets(payload):
    # Extract only actual SPS/PPS NALs from the stream's first access unit.
    import re
    units = re.split(b"\x00\x00(?:\x00)?\x01", payload)
    return b"".join(b"\x00\x00\x00\x01" + unit for unit in units
                    if unit and unit[0] & 31 in (7, 8))


@pytest.mark.parametrize("count", [2, 6])
def test_streaming_per_feed_decode_and_no_retained_rgb(builds, count):
    _, library = builds
    width, height, fps = 64, 48, 25
    images, stride = scene(width, height, count)
    records = stream_encode(library, images, width, height, stride, fps)
    payload, packets = stream_bytes_and_packets(records)
    assert all(nal_types(record[0]) for record in records)
    assert records[0][-1] == 1
    one_shot, reference, metadata, _ = encode(library, images, width, height, stride, fps)
    assert one_shot.status == OK and payload == reference
    assert packet_values(packets) == packet_values(metadata)
    information = probe(payload, "h264")
    assert int(information["streams"][0]["nb_read_frames"]) == count
    assert len(information["frames"]) == count
    assert_content(decode(payload, "h264", width, height, count), images, width, height, stride)


def test_streaming_actual_packet_mux_timestamps(builds):
    _, library = builds
    width, height, fps, count = 64, 48, 24, 6
    images, stride = scene(width, height, count)
    records = stream_encode(library, images, width, height, stride, fps)
    payload, packets = stream_bytes_and_packets(records)
    config = parameter_sets(records[0][0])
    assert set(nal_types(config)) == {7, 8}
    result, movie = mux(library, payload, packets, config, width, height, fps)
    assert result.status == OK
    information = probe(movie, "mov", packets=True)
    assert int(information["streams"][0]["nb_read_frames"]) == count
    assert len(information["packets"]) == count
    for index, packet in enumerate(information["packets"]):
        assert float(packet["pts_time"]) == pytest.approx(index / fps, abs=0.000001)
        assert float(packet["dts_time"]) == pytest.approx(index / fps, abs=0.000001)
        assert float(packet["duration_time"]) == pytest.approx(1 / fps, abs=0.000001)
    decoded = decode(movie, "mov", width, height, count)
    assert_content(decoded, images, width, height, stride)
    assert decoded == decode(payload, "h264", width, height, count)


def test_streaming_irregular_pts_and_duration(builds):
    _, library = builds
    images, stride = scene(count=6)
    times = [(0, 1), (2, 3), (7, 1), (8, 2), (12, 4), (18, 1)]
    records = stream_encode(library, images, 64, 48, stride, times=times)
    assert [(record[1], record[3]) for record in records] == times
    assert all(record[1] == record[2] for record in records)
    payload, _ = stream_bytes_and_packets(records)
    # Raw Annex-B has no container PTS; its metadata is validated at the callback.
    assert_content(decode(payload, "h264", 64, 48, 6), images, 64, 48, stride)


@pytest.mark.parametrize("failure", [19, -28])
def test_streaming_sink_backpressure_is_sticky_without_duplicate(builds, failure):
    _, library = builds
    records, attempts = [], []

    @Sink
    def sink(pointer, _context):
        packet = pointer.contents
        attempts.append(packet.pts)
        if len(attempts) == 2:
            return failure
        records.append(C.string_at(packet.data, packet.size))
        return 0

    stream = library.video_engine_stream_create()
    assert stream
    images, stride = scene(count=3)
    source = C.create_string_buffer(images[0], len(images[0]))
    frame = RGB(C.addressof(source), len(images[0]), stride)
    try:
        assert library.video_engine_stream_begin(stream, 64, 48, 25, 65536, sink, None) == OK
        assert library.video_engine_stream_feed_rgb888(stream, C.byref(frame), 0, 1) == OK
        assert library.video_engine_stream_feed_rgb888(stream, C.byref(frame), 1, 1) == SINK_ERROR
        info = library.video_engine_stream_snapshot(stream)
        assert info.state == FAULT and info.status == SINK_ERROR
        assert info.sink_error == failure and info.codec_error == 0
        assert (info.frames_consumed, info.packets_received, info.packets_published) == (2, 2, 1)
        assert info.bytes_published == len(records[0])
        for operation in (library.video_engine_stream_drain, library.video_engine_stream_finish):
            assert operation(stream) == SINK_ERROR
        assert library.video_engine_stream_feed_rgb888(stream, C.byref(frame), 2, 1) == SINK_ERROR
        assert attempts == [0, 1] and len(records) == 1
        assert len(decode(records[0], "h264", 64, 48, 1)) == 1
        assert library.video_engine_stream_begin(stream, 64, 48, 25, 65536, sink, None) == STATE
        assert library.video_engine_stream_cancel(stream) == OK
        assert library.video_engine_stream_snapshot(stream).sink_error == failure
        assert library.video_engine_stream_begin(stream, 64, 48, 25, 65536, sink, None) == OK
        info = library.video_engine_stream_snapshot(stream)
        assert info.state == ACTIVE and info.status == OK and info.sink_error == 0
        assert info.frames_consumed == info.packets_published == 0
        assert library.video_engine_stream_finish(stream) == OK
    finally:
        library.video_engine_stream_destroy(stream)


@pytest.mark.parametrize("name", ["normal", "sanitized"])
@pytest.mark.parametrize("count", [2, 6])
def test_paced_optical_borrowed_consumer_to_stream(builds, name, count):
    directory, _ = builds
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    completed = subprocess.run([str(directory / (name + "-optical")), str(count)],
                               env=environment, capture_output=True, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert not completed.stderr
    wire = io.BytesIO(completed.stdout)
    images, records = [], []
    for index in range(count):
        kind, size, width, height, stride = wire.readline().split()
        assert kind == b"RGB" and (int(width), int(height)) == (64, 48)
        images.append(wire.read(int(size)))
        kind, size, pts, dts, duration, keyframe = wire.readline().split()
        assert kind == b"H264" and int(pts) == int(dts) == index and int(duration) == 1
        records.append((wire.read(int(size)), int(pts), int(dts), int(duration), int(keyframe)))
    assert wire.readline() == f"DONE {count} {count} {count} {count}\n".encode()
    assert wire.read() == b""
    payload, _ = stream_bytes_and_packets(records)
    information = probe(payload, "h264")
    assert int(information["streams"][0]["nb_read_frames"]) == count
    assert len(information["frames"]) == count
    assert_content(decode(payload, "h264", 64, 48, count), images, 64, 48, int(stride))
