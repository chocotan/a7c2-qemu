"""Actual core STATE128 controls only explicit functional optics admission; no CP execution."""
from pathlib import Path
import ctypes
import importlib.util
import struct
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('functional_imaging_existing_frame_fixture', HERE.parents[1] / 'report/functional-capture-input/test_capture_input.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
actual_frame = fixture.actual_frame


@pytest.fixture(scope='module')
def model_state(actual_frame):
    raw, result = actual_frame['request'](2, capacity=128)
    assert len(raw) == result.used == 128 and result.token == result.total == result.offset == 0
    return raw


@pytest.fixture(scope='module')
def focus_receipt(actual_frame):
    library = actual_frame['library']
    model = library.fcam_model_create(0x403f403f403f403f)
    assert model

    def call(op, data=b'', capacity=128):
        source = ctypes.create_string_buffer(data, max(1, len(data)))
        output = ctypes.create_string_buffer(max(1, capacity))
        result = fixture.Result()
        assert library.fcam_model_request(model, op, source, len(data), output, capacity, ctypes.byref(result)) == 0
        assert result.used == capacity and not result.token and not result.total and not result.offset
        return bytes(output.raw[:result.used])

    try:
        call(1)
        call(3, struct.pack('<IIIIIIQQII', 640, 480, 30, 95, 400, 100, 2500, 1000000, 0, 0))
        call(5, bytes([1, 5, 5, 0xa9, 2, 0, 0, 0, 0x67]) + bytes(7), 160)
        before = call(2)
        canonical = struct.pack('<HH', 0x403f, 8) + bytes(20) + struct.pack('<Q', fixture.fnv(before[8:48]))
        result = call(14, canonical, 192)
        after = call(2)
        for offset in (56, 64, 72, 112):
            assert int.from_bytes(after[offset:offset + 8], 'little') == int.from_bytes(before[offset:offset + 8], 'little') + 1
        assert result[160:] == canonical and result[48:56] == result[56:64] and any(result[48:56])
        assert int.from_bytes(result[64:72], 'little') == 921600 and struct.unpack_from('<2I', result, 112) == (1, 1)
        original = struct.pack('<4I', 0x403f0005, 0x1234, 0, 0)
        receipt = struct.pack('<Q', fixture.fnv(original)) + before + canonical + result
        assert len(receipt) == 360
        call(5, bytes([1, 5, 5, 0xa9, 2, 0, 0, 0, 0x67]) + bytes(7), 160)
        advanced = call(2)
        assert int.from_bytes(advanced[56:64], 'little') > int.from_bytes(after[56:64], 'little')
        yield after, receipt, advanced
    finally:
        library.fcam_model_destroy(model)


@pytest.fixture(scope='module', params=[False, True], ids=['strict', 'asan-ubsan'])
def imaging_binary(request, tmp_path_factory):
    work = tmp_path_factory.mktemp('functional-imaging-admission')
    argv = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g', '-pthread',
            str(HERE / 'device-models/test-functional-imaging.c'), '-o', str(work / 'test')]
    if request.param:
        argv += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    built = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return work / 'test'


@pytest.mark.parametrize('mode', range(160))
def test_actual_model_state_and_same_owner_interlocks(imaging_binary, model_state, focus_receipt, tmp_path, mode):
    path = tmp_path / 'state128.bin'
    path.write_bytes(focus_receipt[2] if mode == 156 else focus_receipt[0] if mode >= 97 else model_state)
    argv = [str(imaging_binary), str(path), str(mode)]
    if mode >= 97:
        receipt = tmp_path / 'actual-focus-reset.bin'
        receipt.write_bytes(focus_receipt[1])
        argv.append(str(receipt))
    ran = subprocess.run(argv, capture_output=True, text=True, timeout=10,
                         env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
                                  UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert not ran.stderr
    if mode:
        assert 'actual-State128-functional-admission strict-cold-04000000-preserved' in ran.stdout
        assert 'original_CP_D012=0 capture_verified=0' in ran.stdout
