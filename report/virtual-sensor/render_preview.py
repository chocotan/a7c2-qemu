#!/usr/bin/env python3
"""Generate a native 33MP host-only colour chart from the shared Bayer/RGB core."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from PIL import Image, PngImagePlugin

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
OUTPUT = PROJECT / 'docs/images/virtual-cmos-color-chart.png'
PREVIEW = OUTPUT.with_stem(OUTPUT.stem + '-preview')
LABEL = '33MP虚拟CMOS色卡（宿主模型生成）'


class Config(C.Structure):
    _fields_ = [('width', C.c_uint), ('height', C.c_uint), ('generation', C.c_uint32)]


def main():
    temporary = Path(os.environ['TMPDIR']).resolve(strict=True)
    if not temporary.is_relative_to(PROJECT):
        raise ValueError('TMPDIR must be a task directory inside this project')
    with tempfile.TemporaryDirectory(prefix='colour-chart-', dir=temporary) as work:
        library = Path(work) / 'sensor.so'
        subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + [
            '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2',
            '-shared', '-fPIC', str(HERE / 'sensor-core.c'), '-o', str(library),
        ], check=True, capture_output=True, timeout=45)
        temporary_stat = library.stat()
        core = C.CDLL(str(library))
        core.sensor_config_parse.argtypes = [C.c_char_p, C.POINTER(Config)]
        core.sensor_config_parse.restype = C.c_int
        core.sensor_token_next.argtypes = [C.POINTER(Config), C.c_uint64]
        core.sensor_token_next.restype = C.c_uint64
        core.sensor_frame_rgb.argtypes = [C.POINTER(Config), C.c_uint64]
        core.sensor_frame_rgb.restype = C.c_void_p
        config = Config()
        if core.sensor_config_parse(b'7008x4672', C.byref(config)) != 0:
            raise RuntimeError('sensor_config_parse rejected the full-resolution profile')
        assert (config.width, config.height) == (7008, 4672)
        token = core.sensor_token_next(C.byref(config), 0)
        pixels = core.sensor_frame_rgb(C.byref(config), token)
        if not pixels:
            raise RuntimeError('sensor_frame_rgb rejected the full-resolution frame')
        try:
            scene = Image.frombytes('RGB', (config.width, config.height),
                                    C.string_at(pixels, config.width * config.height * 3))
        finally:
            allocator = C.CDLL(None)
            allocator.free.argtypes = [C.c_void_p]
            allocator.free(pixels)
    assert scene.getpixel((config.width // 12, config.height // 8)) == (255, 255, 255)
    assert all(abs(actual - expected) <= 1 for actual, expected in
               zip(scene.getpixel((config.width * 11 // 12, config.height // 8)),
                   (224, 48, 32)))
    assert scene.getpixel((config.width * 11 // 12, config.height * 13 // 16)) == (0, 0, 0)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Description', LABEL + '; not a camera/card capture')
    metadata.add_text('Source', 'report/virtual-sensor/sensor-core.c; original synthetic palette')
    metadata.add_text('SensorProfile', '7008x4672')
    metadata.add_text('Producer', 'host sensor_config_parse -> sensor_frame_rgb; GRBG Bayer -> RGB')
    scene.save(OUTPUT, pnginfo=metadata)
    with Image.open(OUTPUT) as readback:
        readback.load()
        assert readback.size == (7008, 4672)
        assert readback.tobytes() == scene.tobytes()
        assert readback.info['Description'].startswith(LABEL)
        assert readback.info['SensorProfile'] == '7008x4672'
        assert 'not a camera/card capture' in readback.info['Description']
    preview = scene.resize((600, 400), Image.Resampling.LANCZOS)
    preview_metadata = PngImagePlugin.PngInfo()
    preview_metadata.add_text('Description', '600x400 preview downsampled from ' + LABEL)
    preview_metadata.add_text('Source', OUTPUT.name)
    preview.save(PREVIEW, pnginfo=preview_metadata)
    with Image.open(PREVIEW) as readback:
        readback.load()
        assert readback.size == (600, 400)
        assert readback.tobytes() == preview.tobytes()
        assert readback.info['Source'] == OUTPUT.name
    print(json.dumps({'path': str(OUTPUT.relative_to(PROJECT)),
                      'bytes': OUTPUT.stat().st_size,
                      'sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                      'sensor_source_sha256': hashlib.sha256(
                          (HERE / 'sensor-core.c').read_bytes()).hexdigest(),
                      'width': scene.width, 'height': scene.height,
                      'preview_path': str(PREVIEW.relative_to(PROJECT)),
                      'preview_bytes': PREVIEW.stat().st_size,
                      'preview_sha256': hashlib.sha256(PREVIEW.read_bytes()).hexdigest(),
                      'label': LABEL, 'producer': 'host sensor_frame_rgb',
                      'camera_card_capture': False,
                      'temporary_library_reclaimed_bytes': temporary_stat.st_blocks * 512
                      }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
