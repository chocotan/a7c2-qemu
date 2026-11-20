"""RAW ownership/metadata host checks; no original AP, ARW or card-write claim."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

from test_functional_capture import HERE, PRODUCT, source


@pytest.mark.parametrize('name,files', [
    ('dma', ['report/functional-capture-output/test-dma.c', 'report/functional-capture-output/capture-dma.c']),
    ('frame-rle', ['runtime/analysis/test-frame-rle.c']),
    ('template', ['runtime/analysis/test-raw-template.c', 'runtime/analysis/raw-template.c']),
    ('blobs', ['runtime/analysis/test-raw-blobs.c', 'runtime/analysis/functional-capture-raw-blobs.c']),
    ('writer', ['runtime/analysis/test-raw-writer.c', 'runtime/analysis/raw-template.c']),
    ('mode-snapshot', ['runtime/analysis/test-raw-mode-snapshot.c']),
    ('save', ['report/functional-capture-output/test-capture-save-raw.c']),
])
def test_raw_host_contracts(name, files, tmp_path):
    binary = tmp_path / name
    command = ['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-fno-builtin-memset', '-I' + str(HERE),
               '-I' + str(HERE / 'device-models'),
               '-I' + str(PRODUCT / 'runtime/analysis'),
               '-I' + str(PRODUCT / 'runtime/analysis/device-models'),
               '-I' + str(HERE.parents[1] / 'report/functional-capture-output'),
               '-I' + str(PRODUCT / 'report/functional-capture-output'),
               *[str(source(f)) for f in files], '-pthread', '-ldl', '-o', str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
    assert ran.returncode == 0, ran.stdout + ran.stderr


spec = importlib.util.spec_from_file_location(
    'raw_capture_existing_encoded_fixture',
    PRODUCT / 'report/functional-capture-output/test_original_exif.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
actual_frame = fixture.actual_frame
encoded_frame = fixture.encoded_frame


@pytest.mark.parametrize('sanitized', [False, True], ids=['strict', 'sanitized'])
def test_raw_output_ownership(encoded_frame, tmp_path, sanitized):
    names = ('frame.bin', 'main.jpg', 'thumb.jpg')
    for name, data in zip(names, encoded_frame):
        (tmp_path / name).write_bytes(data)
    binary = tmp_path / 'raw-output'
    files = ['report/functional-capture-output/test-output-raw.c',
             'report/functional-capture-output/capture-output-memory.c',
             'report/functional-capture-output/capture-dma.c',
             'report/functional-capture-input/capture-input.c']
    command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
               '-O1', '-g', '-fno-pie', '-no-pie',
               '-I' + str(HERE.parents[1] / 'report/functional-capture-output'),
               '-I' + str(PRODUCT / 'report/functional-capture-output'),
               '-I' + str(PRODUCT / 'report/functional-capture-input'),
               *[str(source(f)) for f in files], '-o', str(binary)]
    if sanitized:
        command += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-fno-sanitize-recover=all']
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(binary), *[str(tmp_path / n) for n in names]],
                         capture_output=True, text=True, timeout=20)
    assert ran.returncode == 0, ran.stdout + ran.stderr
