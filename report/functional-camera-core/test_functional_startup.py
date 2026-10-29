# SPDX-License-Identifier: MIT
"""Strict host checks for the bounded BB policies and first real-sink histogram."""
import errno
import importlib.util
from pathlib import Path
import struct

import pytest

_spec = importlib.util.spec_from_file_location(
    'functional_core_startup_helpers', Path(__file__).with_name('test_functional_core.py'))
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)
Model, PEAKING_INPUT = _core.Model, _core.PEAKING_INPUT
blobs, builds, config = _core.blobs, _core.builds, _core.config
fnv, jpeg, run, u32, u64 = _core.fnv, _core.jpeg, _core.run, _core.u32, _core.u64

BB_INPUTS = [
    struct.pack("<HH", command, len(body)) + body + bytes(28 - len(body))
    for command, body in (
        (0x0111, bytes.fromhex("00000f02") + bytes(24)),
        (0x0166, bytes([0, 1]) + bytes(26)),
        (0x0167, bytes([1, 0])),
        (0x015F, bytes(4)),
        (0x0128, bytes([0, 1, 0, 0]) + struct.pack("<I", 60) + bytes(4)),
    )]
BB_0166_INITIAL = bytes.fromhex('66011c0000010000000000000000000008000000070000000100000001000000')
HIST_INPUT = struct.pack("<HH", 0x0148, 4) + bytes([1, 1, 0, 0])


def histogram_expected(rgb):
    assert rgb and len(rgb) % 3 == 0
    counts = [[0] * 256 for _ in range(4)]
    for r, g, b in zip(rgb[0::3], rgb[1::3], rgb[2::3]):
        y = (77 * r + 150 * g + 29 * b + 128) // 256
        for channel, value in enumerate((y, r, g, b)):
            counts[channel][value] += 1
    heights = bytearray()
    for channel in counts:
        peak = max(channel)
        assert peak
        heights.extend((count * 255 + peak // 2) // peak for count in channel)
    return bytes(heights)


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
def test_startup_real_cmos_histogram_and_independent_full_receipts(builds, mode):
    data = blobs(run(builds, "startup-" + mode, "mixed"))
    source, = data["ACTUAL_SOURCE"]
    sink, = data["ACTUAL_SINK"]
    assert source == sink and len(source) == 640 * 480 * 3
    assert len(set(zip(source[0::3], source[1::3], source[2::3]))) > 1
    route = bytes([1, 5, 5, 0xA9, 2, 0, 0, 0, 0x67]) + bytes(7)
    bins = histogram_expected(sink)
    source_hash, sink_hash = fnv(source), fnv(sink)
    calls = [(name, BB_INPUTS[index], index + 5, index + 4, 5)
             for index, name in enumerate(("BB_0111", "BB_0166", "BB_0167", "BB_015F", "BB_0128"))]
    calls += [("HISTOGRAM", HIST_INPUT, 10, 9, 6),
              ("BB_TAG_ZERO", BB_INPUTS[2][:4] + bytes(28), 11, 10, 5),
              ("BB_PERIOD_ONE", BB_INPUTS[4][:8] + struct.pack("<I", 1) + bytes(20), 12, 11, 5),
              ("BB_GAIN_REPEAT", BB_INPUTS[3], 13, 12, 5),
              ("HISTOGRAM_REPEAT", HIST_INPUT, 14, 13, 6),
              ("BB_0166_INITIAL", BB_0166_INITIAL, 15, 14, 5),
              ("HISTOGRAM_INITIAL", HIST_INPUT, 16, 15, 6)]
    for name, canonical, generation, frame, receipt_class in calls:
        response, = data[name]
        size = 1192 if receipt_class == 6 else 192
        expected = bytearray(size)
        struct.pack_into("<IIQQQQQQQQ", expected, 0, 1, size, 77, generation, frame, frame,
                         fnv(canonical), source_hash, sink_hash, len(sink))
        struct.pack_into("<14I", expected, 72, 640, 480, 1920, 0x90590819,
                         1, 1, receipt_class, 1, 1, 1, 1, 1, 0, 0)
        expected[128:144] = route
        struct.pack_into("<QQ", expected, 144, frame - 1, generation - 1)
        expected[160:160 + len(canonical)] = canonical
        if receipt_class == 6:
            expected[168:] = bins
        assert response == expected
    state, = data["BB_STATE"]
    expected = bytearray(128)
    struct.pack_into("<8I", expected, 0, 1, 15, 640, 480, 117, 13, 800, 640)
    struct.pack_into("<9Q", expected, 32, 8642, (1 << 64) - 1, 77, 10, 9, 8, 0, 0, 0)
    struct.pack_into("<IIQ", expected, 104, 0, 0, 9)
    assert state == expected
    for name in ("SMALL", "GRADIENT", "FLAT"):
        rgb, = data[name + "_RGB"]
        actual, = data[name + "_BINS"]
        assert actual == histogram_expected(rgb)
        assert all(max(actual[i:i + 256]) == 255 for i in range(0, 1024, 256))
    small, = data["SMALL_BINS"]
    assert small[0] == 255 and small[77] == 85 and small[149] == 85 and small[29] == 85
    flat, = data["FLAT_BINS"]
    assert sum(value != 0 for value in flat) == 4


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("group", ["validation", "faults"])
def test_startup_rejections_and_transaction_faults_preserve_generations(builds, mode, group):
    assert run(builds, "startup-" + mode, group) == b""


@pytest.mark.parametrize("changes", [{}, dict(fps=117, quality=13, fnumber=800, iso=640,
                                            shutter=8642, focus=(1 << 64) - 1)])
def test_ctypes_startup_histogram_mixed_banks_and_config48(builds, changes):
    model = Model(builds["library"])
    try:
        settings = config(width=640, height=480, **changes)
        model.request(3, settings)
        before, _ = model.request(2)
        for op, body, size in ((9, BB_INPUTS[0], 192), (10, HIST_INPUT, 1192)):
            model.request(op, body, size, expected=-errno.ENODATA)
        assert model.request(2)[0] == before
        route = bytes([1, 5, 5, 0xA9, 2]) + bytes(11)
        calls = [(5, route, 160), (8, PEAKING_INPUT, 176)]
        calls += [(9, body, 192) for body in BB_INPUTS + [BB_0166_INITIAL]]
        calls += [(10, HIST_INPUT, 1192), (9, BB_INPUTS[2], 192), (10, HIST_INPUT, 1192)]
        for op, body, size in calls:
            previous, _ = model.request(2)
            model.request(op, body, size - 1, expected=-errno.ENOSPC)
            assert model.request(2)[0] == previous
            receipt, info = model.request(op, body, size)
            current, _ = model.request(2)
            assert current[8:48] == previous[8:48] == settings[:40]
            assert not info.token and not info.total and not info.offset and info.used == size
            assert u64(receipt, 16) == u64(current, 56) == u64(previous, 56) + 1
            assert u64(receipt, 24) == u64(current, 112) == u64(previous, 112) + 1
            assert all(u64(current, offset) == u64(previous, offset) + 1 for offset in (64, 72))
            assert all(u64(current, offset) == 0 for offset in (80, 88, 96))
            assert receipt[128:144] == route and u64(receipt, 40) == fnv(body)
            assert u64(receipt, 48) == u64(receipt, 56) != 0 and u64(receipt, 64) == 921600
            if op in (9, 10):
                assert u32(receipt, 96) == (5 if op == 9 else 6)
                assert receipt[160:160 + len(body)] == body
            if op == 10:
                assert len(receipt[168:]) == 1024
                assert all(max(receipt[i:i + 256]) == 255 for i in range(168, 1192, 256))
            assert model.request(1)[0] == current
        # A fixed first-frame cache does not occupy the encoded-result cursor.
        product = model.encoded(16, struct.pack("<IIII", 1, 128, 64, 90))
        assert jpeg(product).size == (128, 64)
        model.request(5, bytes([0, 1, 1]) + bytes(13), 160)
        previous, _ = model.request(2)
        model.request(10, HIST_INPUT, 1192, expected=-errno.ENODATA)
        assert model.request(2)[0] == previous
    finally:
        model.close()
