"""Actual captured output ownership to Fsys trace join; AP/Fsys are explicit host fixtures."""
from pathlib import Path
import importlib.util
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent.parent
BASE = NATIVE / 'runtime/analysis'
spec = importlib.util.spec_from_file_location('capture_save_existing_encoded_fixture', HERE / 'test_original_exif.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
actual_frame = fixture.actual_frame
encoded_frame = fixture.encoded_frame


@pytest.fixture(scope='module', params=[False, True], ids=['strict', 'asan-ubsan'])
def save_binary(request, tmp_path_factory):
    root = tmp_path_factory.mktemp('capture-save-join')
    argv = ['cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic',
            '-I' + str(NATIVE / 'report/functional-capture-input'), str(HERE / 'test-capture-save.c'),
            str(HERE / 'capture-output-memory.c'), str(HERE / 'capture-dma.c'), str(NATIVE / 'report/functional-capture-input/capture-input.c'),
            str(BASE / 'fsys-write-trace.c'), '-o', str(root / 'test')]
    if request.param:
        argv += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    built = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return root / 'test'


@pytest.mark.parametrize('mode', range(32))
def test_save_requires_matching_whole_main_and_original_lifecycle(save_binary, encoded_frame, tmp_path, mode):
    for name, raw in zip(('frame.bin', 'main.jpg', 'thumb.jpg'), encoded_frame):
        (tmp_path / name).write_bytes(raw)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    ran = subprocess.run([str(save_binary), *(str(tmp_path / name) for name in ('frame.bin', 'main.jpg', 'thumb.jpg')), str(mode)],
                         capture_output=True, text=True, env=env, timeout=15)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert ran.stdout == 'PASS HOST_ONLY actual-source-owner real-trace-hooks callback-finished-readback-coverage capture_verified=0 original_AP=0 original_Fsys=0\n'
    assert not ran.stderr
