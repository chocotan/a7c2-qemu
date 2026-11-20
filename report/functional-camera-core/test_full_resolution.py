"""Full photo dimensions through the real model/input owner; no VM or card writes."""
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess

from PIL import Image
import pytest

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[1]
BASE = PRODUCT / 'runtime/analysis'


@pytest.mark.parametrize('raw', [False, True], ids=['jpeg', 'raw-rle'])
@pytest.mark.parametrize('sanitized', [False, True])
def test_full_photo_and_independent_display_geometry(tmp_path, sanitized, raw):
    spec = importlib.util.spec_from_file_location('full_photo_model_build', BASE / 'build-functional-camera-model.py')
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    executable = tmp_path / 'full-photo'
    flags = ['-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'] if sanitized else ['-O2']
    libraries = shlex.split(subprocess.check_output([
        'pkg-config', '--cflags', '--libs', 'libjpeg', 'libavcodec', 'libavformat',
        'libavutil', 'libswscale'], text=True, timeout=15))
    sources = [HERE / 'test-full-resolution.c',
               *[PRODUCT / 'report' / path for path in build.SOURCES],
               BASE / 'device-models/cp-parameter-batch.c',
               PRODUCT / 'report/functional-capture-input/capture-input.c']
    subprocess.run(shlex.split(os.environ.get('CC', 'cc')) + [
        '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', *flags,
        *map(str, sources), '-o', str(executable), *libraries, '-lm'],
        check=True, capture_output=True, timeout=90)
    output = tmp_path / 'full-photo.jpg'
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:quarantine_size_mb=32',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    env.pop('A7C2_VIRTUAL_CMOS_PROFILE', None)
    ran = subprocess.run([str(executable), str(output), *(['raw'] if raw else [])], env=env, capture_output=True, timeout=150)
    (tmp_path / 'model.stdout').write_bytes(ran.stdout)
    (tmp_path / 'model.stderr').write_bytes(ran.stderr)
    assert ran.returncode == 0, ran.stderr.decode(errors='replace')
    if raw:
        assert b'RAW_FRAME_TRANSFER rgb_bytes=98224128 ' in ran.stdout
    assert b'FULL_RESOLUTION_PHOTO_AND_DISPLAY_SEPARATION_PASS' in ran.stdout
    with Image.open(output) as image:
        assert image.format == 'JPEG' and image.size == (7008, 4672) and image.mode == 'RGB'
        image.load()
        white = image.getpixel((7008 // 12, 4672 // 8))
        black = image.getpixel((7008 * 11 // 12, 4672 * 13 // 16))
        assert white[0] == white[1] == white[2]
        assert min(white) > max(black)
