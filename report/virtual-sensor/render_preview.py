#!/usr/bin/env python3
"""Generate a labelled host-only preview from the actual shared Bayer/RGB core."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent.parent
OUTPUT = PROJECT / 'docs/images/virtual-cmos-color-chart.png'
LABEL = '虚拟CMOS色卡示意（宿主模型生成）'


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
        core.sensor_frame_rgb.argtypes = [C.POINTER(Config), C.c_uint64]
        core.sensor_frame_rgb.restype = C.c_void_p
        config = Config(640, 480, 1)
        pixels = core.sensor_frame_rgb(C.byref(config), (1 << 32) | 1)
        if not pixels:
            raise RuntimeError('sensor_frame_rgb rejected the preview frame')
        try:
            scene = Image.frombytes('RGB', (640, 480), C.string_at(pixels, 640 * 480 * 3))
        finally:
            allocator = C.CDLL(None)
            allocator.free.argtypes = [C.c_void_p]
            allocator.free(pixels)
    assert scene.getpixel((53, 60)) == (255, 255, 255)
    assert all(abs(actual - expected) <= 1 for actual, expected in
               zip(scene.getpixel((586, 60)), (224, 48, 32)))
    assert scene.getpixel((586, 390)) == (0, 0, 0)
    font_path = subprocess.check_output(
        ['fc-match', '-f', '%{file}', 'sans:lang=zh'], text=True, timeout=10).strip()
    image = Image.new('RGB', (640, 560), '#17202b')
    image.paste(scene, (0, 0))
    draw = ImageDraw.Draw(image)
    draw.text((16, 490), LABEL, font=ImageFont.truetype(font_path, 22), fill='white')
    draw.text((16, 525), '640 x 480 | GRBG Bayer -> RGB | not a camera/card capture',
              font=ImageFont.truetype(font_path, 15), fill='#c5d3e0')
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('Description', LABEL + '; not a camera/card capture')
    metadata.add_text('Source', 'report/virtual-sensor/sensor-core.c; original synthetic palette')
    image.save(OUTPUT, pnginfo=metadata)
    with Image.open(OUTPUT) as readback:
        readback.load()
        assert readback.size == image.size
        assert readback.tobytes() == image.tobytes()
        assert readback.info['Description'].startswith(LABEL)
    print(json.dumps({'path': str(OUTPUT.relative_to(PROJECT)),
                      'bytes': OUTPUT.stat().st_size,
                      'sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
                      'sensor_source_sha256': hashlib.sha256(
                          (HERE / 'sensor-core.c').read_bytes()).hexdigest(),
                      'label': LABEL, 'producer': 'host sensor_frame_rgb',
                      'camera_card_capture': False,
                      'temporary_library_reclaimed_bytes': temporary_stat.st_blocks * 512
                      }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
