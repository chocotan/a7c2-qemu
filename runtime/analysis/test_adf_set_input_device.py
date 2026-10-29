"""Composed 0323 -> 0336 host Linux timers; no VM/native AP/capture claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
BACKENDS = [
    'adf-proc-device', 'adf-public-config', 'adf-idle-resources', 'adf-hdmi-monitor',
    'adf-input-state', 'adf-set-input-cold-owners', 'adf-aip-coefficients',
    'adf-aip-gates', 'adf-aip-commands', 'adf-aip-disable', 'adf-avio-output',
    'adf-source7-clock', 'adf-set-input-device', 'adf-aip-input-config',
]
NO_SEED = [
    'disabled', 'unrelated', 'invalid-envelope', 'invalid-caller',
    'missing-transport', 'missing-guard', 'no-prior', 'fork-first', 'fork-locked',
]
WITH_SEED = [
    'normal', 'dynamic-caller', 'no-ap-free', 'reservation-refused',
    'seed-missing', 'seed-bad', 'event0', 'event2',
    'alloc-rc', 'alloc-rc-pointer', 'alloc-null', 'alloc-size', 'alloc-original',
    'set-source', 'send-fail', 'cleanup-fail', 'request-free-fail',
    'reply-free-fail', 'wrong-owner', 'recursive',
    'kiki-alloc-rc', 'kiki-alloc-rc-pointer', 'kiki-alloc-null',
    'kiki-alloc-size', 'kiki-alloc-original', 'kiki-send-fail', 'kiki-cleanup-fail',
]


@pytest.fixture(scope='module')
def public_adf_input_seed():
    seed = HERE / 'menu-root/seed-backup.bin'
    if not seed.is_file():
        return None
    data = seed.read_bytes()
    assert len(data) == 2390264
    assert hashlib.sha256(data).hexdigest() == (
        '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47')
    assert data[0x132F7D] == 1
    return seed


@pytest.fixture(scope='module')
def adf_set_input_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('adf-set-input-device')
    binary = directory / 'model'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-pthread']
    built = subprocess.run(flags + [
        '-c', str(MODEL / 'adf-set-input-device.c'), '-o', str(directory / 'production.o'),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(['nm', '-g', str(directory / 'production.o')],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert 'full_adf_set_input_test_' not in symbols.stdout
    built = subprocess.run(flags + [
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        *[str(MODEL / (name + '.c')) for name in BACKENDS],
        str(MODEL / 'test-adf-set-input-device.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', NO_SEED + WITH_SEED)
def test_adf_set_input_composed_host_contract(
        adf_set_input_binary, public_adf_input_seed, tmp_path, case):
    if case in WITH_SEED and public_adf_input_seed is None:
        pytest.skip('provision the original pinned ALLLANG public seed first')
    prior_seed = public_adf_input_seed
    if case in NO_SEED:
        prior_seed = tmp_path / 'absent-seed.bin'
        assert not prior_seed.exists()
    seed = prior_seed
    if case == 'seed-missing':
        seed = tmp_path / 'absent-seed.bin'
        assert not seed.exists()
    elif case == 'seed-bad':
        seed = tmp_path / 'corrupt-public-seed.bin'
        data = bytearray(prior_seed.read_bytes())
        data[0x132F7D] ^= 1
        seed.write_bytes(data)
    result = subprocess.run([str(adf_set_input_binary), case, str(prior_seed), str(seed)],
        capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'ADF_SET_INPUT_HOST_TEST_PASS: {case};' in result.stdout
