"""Real 0323 -> 0336 -> 032d host models; no VM/original AP/capture claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

import pytest

from test_adf_set_input_device import BACKENDS as INPUT_BACKENDS, public_adf_input_seed

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
BACKENDS = [*INPUT_BACKENDS, 'adf-set-output-device','bb-mode-config','bb-mode-work-queue','bb-set-mode-device']
NO_SEED = [
    'disabled', 'unrelated', 'invalid-envelope', 'short-allocation',
    'invalid-caller', 'missing-transport', 'missing-guard', 'uninitialized',
    'no-prior', 'fork-first', 'fork-locked',
]
WITH_SEED = [
    'normal', 'dynamic-caller', 'nonempty-handoff', 'release-pass-through',
    'no-input', 'early-1336-free', 'reservation-refused', 'resource-busy',
    'event0', 'unsupported-source', 'copied-monitor', 'power-active', 'commands-busy',
    'alloc-rc', 'alloc-rc-pointer', 'alloc-rc-cleanup-fail', 'alloc-null',
    'alloc-size', 'alloc-small', 'alloc-original', 'set-source', 'send-fail',
    'cleanup-fail', 'request-free-fail', 'reply-free-fail', 'wrong-owner', 'recursive',
]


@pytest.fixture(scope='module')
def adf_set_output_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('adf-set-output-device')
    binary = directory / 'model'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-pthread']
    built = subprocess.run(flags + [
        '-c', str(MODEL / 'adf-set-output-device.c'), '-o', str(directory / 'production.o'),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(['nm', '-g', str(directory / 'production.o')],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert 'full_adf_set_output_test_' not in symbols.stdout
    built = subprocess.run(flags + [
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST', '-DFULL_ADF_SET_OUTPUT_TEST',
        '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL / (name + '.c')) for name in BACKENDS],
        str(MODEL / 'test-adf-set-output-device.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', NO_SEED + WITH_SEED)
def test_adf_set_output_composed_host_contract(
        adf_set_output_binary, public_adf_input_seed, tmp_path, case):
    if case in WITH_SEED and public_adf_input_seed is None:
        pytest.skip('provision the original pinned ALLLANG public seed first')
    seed = public_adf_input_seed
    if case in NO_SEED:
        seed = tmp_path / 'absent-seed.bin'
        assert not seed.exists()
    result = subprocess.run([str(adf_set_output_binary), case, str(seed)],
        capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'ADF_SET_OUTPUT_HOST_TEST_PASS: {case};' in result.stdout
    if case in WITH_SEED:
        assert 'FULL_ADF_PROC_REPLY_FREE ' in result.stdout
    if case in WITH_SEED and case not in {'no-input', 'early-1336-free'}:
        assert 'FULL_ADF_SET_INPUT_REPLY_FREE ' in result.stdout
    if case in {'normal', 'dynamic-caller', 'nonempty-handoff', 'release-pass-through', 'recursive'}:
        assert 'FULL_ADF_SET_OUTPUT_EVENT ' in result.stdout
        assert 'FULL_ADF_SET_OUTPUT_AIP_CONSUMED ' in result.stdout
        assert 'FULL_ADF_SET_OUTPUT_REPLY_FREE ' in result.stdout
