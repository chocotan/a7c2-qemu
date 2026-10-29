"""Four-event ADF control backend on host Linux; no VM, AP or capture claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
BACKENDS = [
    'adf-proc-device', 'adf-public-config', 'adf-idle-resources',
    'adf-input-state', 'adf-set-input-cold-owners', 'adf-hdmi-monitor', 'adf-aip-coefficients', 'adf-aip-gates',
    'adf-aip-commands', 'adf-aip-disable', 'adf-avio-output', 'adf-source7-clock',
]
NO_SEED = [
    'disabled', 'unrelated', 'invalid-envelope', 'invalid-caller',
    'missing-transport', 'missing-guard', 'reservation-refused',
    'seed-missing', 'fork-first', 'fork-locked',
]
WITH_SEED = [
    'normal', 'dynamic-caller', 'event0', 'event2', 'event3', 'alloc-rc',
    'alloc-rc-pointer', 'alloc-null', 'alloc-size', 'alloc-original',
    'set-source', 'send-fail', 'cleanup-fail', 'request-free-fail',
    'reply-free-fail', 'wrong-owner', 'recursive', 'input-handoff',
]


@pytest.fixture(scope='module')
def public_adf_seed():
    seed = HERE / 'menu-root/seed-backup.bin'
    if not seed.is_file():
        return None
    data = seed.read_bytes()
    assert len(data) == 2390264
    assert hashlib.sha256(data).hexdigest() == (
        '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47')
    assert data[0x132F7D] == 1  # CP01 key 0x58007b: the public prelude flag.
    return seed


@pytest.fixture(scope='module')
def adf_proc_binary(tmp_path_factory, public_adf_seed):
    directory = tmp_path_factory.mktemp('adf-proc-device')
    binary = directory / 'model'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-pthread']
    built = subprocess.run(flags + [
        '-c', str(MODEL / 'adf-proc-device.c'), '-o', str(directory / 'production.o'),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(['nm', '-g', str(directory / 'production.o')],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert 'full_adf_proc_test_' not in symbols.stdout
    built = subprocess.run(flags + [
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        '-DFULL_ADF_PROC_TEST',
        *[str(MODEL / (name + '.c')) for name in BACKENDS],
        str(MODEL / 'test-adf-proc-device.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', NO_SEED + WITH_SEED)
def test_adf_proc_composed_host_contract(adf_proc_binary, public_adf_seed, tmp_path, case):
    if case in WITH_SEED and public_adf_seed is None:
        pytest.skip('provision the original pinned ALLLANG public seed first')
    seed = public_adf_seed
    if case in NO_SEED:
        seed = tmp_path / 'absent-seed.bin'
        assert not seed.exists()
    result = subprocess.run([str(adf_proc_binary), case, str(seed)],
        capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_PROC_HOST_TEST_PASS:' in result.stdout
