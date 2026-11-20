"""Functional-owner 4037 ingress and virtual intent; no original CP execution."""
from pathlib import Path
import os
import subprocess
import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module', params=[False, True], ids=['strict', 'asan-ubsan'])
def still_unlock_binary(request, tmp_path_factory):
    work = tmp_path_factory.mktemp('functional-still-unlock')
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g',
             '-pthread', '-DFULL_IMAGING_TEST', '-DNDEBUG']
    if request.param:
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    binary = work / 'test'
    result = subprocess.run(['cc', *flags, str(HERE / 'device-models/imaging-device.c'),
                             str(HERE / 'device-models/test-functional-still-unlock.c'),
                             '-o', str(binary)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return binary


@pytest.mark.parametrize('mode', range(44))
def test_functional_still_unlock(still_unlock_binary, mode):
    result = subprocess.run([str(still_unlock_binary), str(mode)], capture_output=True,
                            text=True, timeout=10, env=dict(os.environ,
                            ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
                            UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    if result.returncode or result.stderr or f'PASS functional-still-unlock mode={mode} ' not in result.stdout:
        raise RuntimeError(f'rc={result.returncode}\n{result.stdout}{result.stderr}')
