"""Virtual CMOS component checks; no camera, VM, firmware, or card writes."""
import ctypes as C
import os
from pathlib import Path
import shlex
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


class Config(C.Structure):
    _fields_ = [('width', C.c_uint), ('height', C.c_uint), ('generation', C.c_uint32)]


@pytest.fixture(scope='module')
def sensor(tmp_path_factory):
    library = tmp_path_factory.mktemp('sensor-core') / 'sensor.so'
    subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + [
        '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
        '-fPIC', '-shared', str(HERE / 'sensor-core.c'), '-o', str(library),
    ], check=True, capture_output=True, timeout=45)
    core = C.CDLL(str(library))
    core.sensor_config_parse.argtypes = [C.c_char_p, C.POINTER(Config)]
    core.sensor_token_next.argtypes = [C.POINTER(Config), C.c_uint64]
    core.sensor_token_next.restype = C.c_uint64
    core.sensor_token_valid.argtypes = [C.POINTER(Config), C.c_uint64]
    core.sensor_frame_bayer_into.argtypes = [C.POINTER(Config), C.c_uint64,
                                            C.POINTER(C.c_uint16), C.c_size_t]
    core.sensor_demosaic_rgb.argtypes = [C.POINTER(C.c_uint16), C.c_uint,
                                       C.c_uint, C.POINTER(C.c_uint8)]
    core.sensor_cfa_color.argtypes = [C.c_uint, C.c_uint]
    return core


@pytest.mark.parametrize('sanitized', [False, True])
def test_default_sensor_optics_contract(tmp_path, sanitized):
    optics = HERE.parent / 'virtual-optics'
    executable = tmp_path / 'default-sensor'
    flags = ['-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
             '-fno-pie', '-no-pie'] if sanitized else ['-O2']
    subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + [
        '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', *flags,
        str(optics / 'test_default_sensor.c'), str(optics / 'optics.c'),
        str(HERE / 'sensor-core.c'), '-lm', '-o', str(executable),
    ], check=True, capture_output=True, timeout=45)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    env.pop('A7C2_VIRTUAL_CMOS_PROFILE', None)
    result = subprocess.run([str(executable)], env=env, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


def test_config_generation_and_frame_exhaustion(sensor):
    config = Config()
    assert sensor.sensor_config_parse(None, C.byref(config)) == 0
    assert (config.width, config.height, config.generation) == (640, 480, 1)
    token = sensor.sensor_token_next(C.byref(config), 0)
    assert token == (1 << 32) | 1
    assert sensor.sensor_token_valid(C.byref(config), token)
    config.generation = 2
    assert not sensor.sensor_token_valid(C.byref(config), token)
    assert sensor.sensor_token_next(C.byref(config), token) == (2 << 32) | 1
    assert sensor.sensor_token_next(C.byref(config), (2 << 32) | 0xffffffff) == 0
    assert sensor.sensor_token_next(None, 0) == 0
    config.generation = 0
    assert not sensor.sensor_token_valid(C.byref(config), 1)
    assert sensor.sensor_token_next(C.byref(config), 0) == 0


def test_full_profile_is_explicit_and_unknown_is_rejected(sensor):
    config = Config()
    assert sensor.sensor_config_parse(b'7008x4672', C.byref(config)) == 0
    assert (config.width, config.height) == (7008, 4672)
    assert sensor.sensor_config_parse(b'unknown', C.byref(config)) == -22
    assert not sensor.sensor_token_valid(C.byref(config), (1 << 32) | 1)


def test_bayer_grbg_packing_boundaries_and_atomic_short_buffer(sensor):
    config = Config(640, 480, 1)
    samples = config.width * config.height
    packed = (C.c_uint16 * (samples + 2))()
    packed[0] = packed[-1] = 0xa55a
    pixels = C.cast(C.byref(packed, 2), C.POINTER(C.c_uint16))
    token = (1 << 32) | 1
    before = bytes(packed)
    assert sensor.sensor_frame_bayer_into(C.byref(config), token, pixels, samples - 1) == -28
    assert bytes(packed) == before
    assert sensor.sensor_frame_bayer_into(C.byref(config), token, pixels, samples) == 0
    assert packed[0] == packed[-1] == 0xa55a
    for x, y, expected in ((5, 5, 16383), (600, 5, 0),
                           (5, 470, 8192), (600, 470, 4095),
                           (200, 100, 200 * 16383 // 639), (300, 32, 2048)):
        assert pixels[y * 640 + x] == expected << 2
    assert [sensor.sensor_cfa_color(x, y) for y in range(2) for x in range(2)] == [1, 0, 2, 1]


def test_demosaic_uses_actual_cfa_channels_at_edges(sensor):
    # Uniform colours in a GRBG mosaic, including all border neighbourhoods.
    raw = (C.c_uint16 * 16)(*[(16383, 8192, 4095)[(1, 0, 2, 1)[(y % 2) * 2 + x % 2]] << 2
                             for y in range(4) for x in range(4)])
    rgb = (C.c_uint8 * 48)()
    assert sensor.sensor_demosaic_rgb(raw, 4, 4, rgb) == 0
    assert bytes(rgb) == bytes((255, 127, 63)) * 16
