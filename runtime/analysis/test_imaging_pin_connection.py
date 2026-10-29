"""Real prior BB/ADF providers and mapped byte-array DMM; no VM/capture claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

import pytest

from test_adf_set_output_device import BACKENDS as BB_BACKENDS
from test_adf_set_input_device import public_adf_input_seed

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
NO_SEED = ['disabled', 'unrelated', 'short', 'bad-wire', 'invalid-source',
           'missing-transport', 'missing-guard', 'uninitialized', 'fork', 'no-prior']
WITH_SEED = [
    'normal', 'dynamic-caller', 'no-get', 'no-pool', 'live-source-get',
    'live-peer-get', 'virgin-pool', 'resource-busy', 'source-error', 'peer-wire',
    'peer-reply-wire', 'corrupt-notify', 'corrupt-backing', 'send-fail',
    'request-free-fail', 'reply-free-fail', 'wrong-owner', 'inline-free',
    'inline-send-fail', 'in-flight-send-fail', 'in-flight-free-fail',
    'recursive', 'fork-held', 'repeat',
    'alloc-cleanup-fail', 'internal-free-fail', 'alloc-live-alias',
    *[f'alloc-{nth}-{kind}' for nth in range(1, 9) for kind in range(1, 6)],
    *[f'source-{nth}-1' for nth in range(2, 9)],
    *[f'source-{nth}-2' for nth in (3, 4, 6, 7)],
    *[f'dmm-reply-{nth}-{offset}' for nth in (3, 6)
      for offset in (0, 2, 6, 8, 12, 24, 28, 32)],
]


@pytest.fixture(scope='module')
def imaging_pin_connection_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('imaging-pin-connection')
    binary = directory / 'model'
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-registry-core',
                'infraimaging-format', 'imaging-pin-connection']
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-no-pie', '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        '-DFULL_ADF_SET_OUTPUT_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-imaging-pin-connection.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('case', NO_SEED + WITH_SEED)
def test_imaging_pin_connection_composed_host_contract(
        imaging_pin_connection_binary, public_adf_input_seed, tmp_path, case):
    if case in WITH_SEED and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed
    if case in NO_SEED:
        seed = tmp_path / 'absent-public-seed.bin'
        assert not seed.exists()
    result = subprocess.run([str(imaging_pin_connection_binary), case, str(seed)],
        capture_output=True, text=True, timeout=20,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'IMAGING_PIN_CONNECTION_HOST_TEST_PASS:' in result.stdout
    if case in {'in-flight-send-fail', 'in-flight-free-fail'}:
        first_rc, attempts = (-59, 2) if case == 'in-flight-free-fail' else (0, 1)
        assert (f'IMAGING_PIN_CONNECTION_IN_FLIGHT_PASS: first_free_rc={first_rc} '
                f'attempts={attempts} ap_consumed=1 clean_completion=0 '
                'caller_request_freed=1') in result.stdout
        assert 'FULL_IMAGING_PIN_CONNECT_REPLY_QUEUED ' not in result.stdout
        assert 'FULL_IMAGING_PIN_CONNECT_COMMIT ' not in result.stdout
    if case in {'normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held', 'repeat'}:
        tags = ['FULL_IMAGING_PIN_CONNECT_PEER_REQUEST ',
                'FULL_IMAGING_PIN_CONNECT_PEER_REPLY ',
                'FULL_IMAGING_PIN_CONNECT_PEER_MARKER_WRITTEN ',
                'FULL_IMAGING_PIN_CONNECT_FORMAT_WRITTEN ',
                'FULL_IMAGING_PIN_CONNECT_FORMAT_NOTIFY ',
                'FULL_IMAGING_PIN_CONNECT_FORMAT_CONSUMED ',
                'FULL_IMAGING_PIN_CONNECT_BUFFER_RETIRED ',
                'FULL_IMAGING_PIN_CONNECT_REPLY_QUEUED ',
                'FULL_IMAGING_PIN_CONNECT_COMMIT ']
        positions = [result.stdout.index(tag) for tag in tags]
        assert positions == sorted(positions)
        assert result.stdout.count('FULL_IMAGING_PIN_CONNECT_REPLY_QUEUED ') == 1
        assert 'FULL_IMAGING_PIN_CONNECT_REPLY_FREE ' in result.stdout
        assert 'original_CP_page_tables_verified=0' in result.stdout
        assert 'FULL_BB_SET_MODE_REPLY_FREE ' in result.stdout
        assert 'FULL_INFRAIMAGING_NATIVE_REPLY_FREE ' in result.stdout
        assert 'FULL_INFRABB_NATIVE_REPLY_FREE ' in result.stdout
