"""Compose the completed first edge with one type8 control handshake; no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

import pytest

from test_adf_set_output_device import BACKENDS as BB_BACKENDS
from test_adf_set_input_device import public_adf_input_seed

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
NO_SEED = ['disabled', 'unrelated', 'short', 'first-type0', 'bad-wire',
           'invalid-source', 'missing-transport', 'missing-guard',
           'uninitialized', 'fork', 'no-first']
WITH_SEED = [
    'normal', 'dynamic-caller', 'no-get', 'live-source-get', 'live-peer-get',
    'resource-busy', 'source-error', 'peer-wire', 'peer-reply-wire', 'send-fail',
    'request-free-fail', 'reply-free-fail', 'wrong-owner', 'inline-free',
    'inline-send-fail', 'recursive', 'fork-held', 'repeat', 'recursive-free',
    'queued-fault', 'concurrent-peer-get', 'in-flight-send-fail', 'in-flight-free-fail',
    'internal-free-fail', 'alloc-cleanup-fail', 'alloc-live-alias',
    *[f'alloc-{nth}-{kind}' for nth in range(1, 4) for kind in range(1, 6)],
    *[f'source-{nth}' for nth in range(1, 4)],
    *[f'wire-{nth}-{offset}' for nth in (1, 2)
      for offset in (0, 4, 8, 10, 12, 16, 24, 26, 28, 30,
                     32, 36, 40, 44, 48, 52, 56, 60)],
    'wire-2-64', 'wire-2-68',
    *[f'wire-3-{offset}' for offset in
      (0, 4, 8, 10, 12, 16, 24, 26, 28, 30, 32, 36, 40, 44, 48, 52)],
]


@pytest.fixture(scope='module')
def imaging_control_connection_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('imaging-control-connection')
    binary = directory / 'model'
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-registry-core',
                'infraimaging-format', 'imaging-pin-connection',
                'imaging-control-connection']
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-no-pie', '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        '-DFULL_ADF_SET_OUTPUT_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-imaging-control-connection.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('case', NO_SEED + WITH_SEED)
def test_imaging_control_connection_composed_host_contract(
        imaging_control_connection_binary, public_adf_input_seed, tmp_path, case):
    if case in WITH_SEED and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed
    if case in NO_SEED:
        seed = tmp_path / 'absent-public-seed.bin'
        assert not seed.exists()
    result = subprocess.run([str(imaging_control_connection_binary), case, str(seed)],
        capture_output=True, text=True, timeout=25,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'IMAGING_CONTROL_CONNECTION_HOST_TEST_PASS:' in result.stdout
    if case in {'normal', 'dynamic-caller', 'inline-free', 'recursive',
                'fork-held', 'repeat'}:
        tags = ['FULL_IMAGING_CONTROL_CONNECT_PEER_REQUEST ',
                'FULL_IMAGING_CONTROL_CONNECT_PEER_REPLY ',
                'FULL_IMAGING_CONTROL_CONNECT_PEER_MARKER_WRITTEN ',
                'FULL_IMAGING_CONTROL_CONNECT_POSTHOOK_NO_FORMAT ',
                'FULL_IMAGING_CONTROL_CONNECT_REPLY_QUEUED ',
                'FULL_IMAGING_CONTROL_CONNECT_COMMIT ']
        positions = [result.stdout.index(tag) for tag in tags]
        assert positions == sorted(positions)
        assert result.stdout.count('FULL_IMAGING_CONTROL_CONNECT_REPLY_QUEUED ') == 1
        assert result.stdout.count('FULL_IMAGING_CONTROL_CONNECT_REPLY_FREE ') == 1
        assert 'DMM_allocations=0 notifications=0 cache_writes=0' in result.stdout
        assert 'FULL_IMAGING_PIN_CONNECT_REPLY_FREE ' in result.stdout
        assert 'FULL_IMAGING_PIN_CONNECT_FORMAT_CONSUMED ' in result.stdout
        assert 'FULL_BB_SET_MODE_REPLY_FREE ' in result.stdout
