"""Fifth BB/VEF control edge; real predecessor providers, no VM/capture claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import subprocess

import pytest

from test_adf_set_output_device import BACKENDS as BB_BACKENDS
from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'unrelated', 'short', 'long', 'other-BB-type0', 'uninitialized',
         'fork', 'invalid-source', 'bad-wire', 'no-prior', 'missing-transport', 'missing-guard']
SUCCESS = ['normal', 'peek-status', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held', 'repeat']
CASES = [*SUCCESS, 'no-fourth-AP-free', 'live-peer-get', 'no-source-get', 'no-peer-get', 'recursive-free',
         'queued-fault', 'in-flight-send-fail', 'in-flight-free-fail',
         'resource-busy', 'send-fail', 'inline-send-fail', 'request-free-fail',
         'reply-free-fail', 'wrong-owner', 'cleanup-fail', 'concurrent-peer-get',
         *[f'alloc-{n}-{kind}' for n in range(1, 4) for kind in range(1, 6)],
         'alloc-2-6', *[f'source-{n}' for n in range(1, 4)],
         *[f'wire-{n}-{offset}' for n, offsets in [
             (1, [0, 4, 8, 10, 12, 16, 24, 26, 28, 30, 32, 33, 36, 40, 44, 48, 52, 56, 60]),
             (2, [0, 4, 8, 10, 12, 16, 24, 26, 28, 30, 32, 36, 40, 44, 48, 52, 56, 60, 64, 68]),
             (3, [0, 4, 8, 10, 12, 16, 24, 26, 28, 30, 32, 36, 40, 44, 48, 52])]
          for offset in offsets]]


@pytest.fixture(scope='module')
def fifth_edge_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('infrabb-vef-control-connection')
    binary = directory / 'model'
    production = subprocess.run(FLAGS + [
        '-c', str(MODEL / 'infrabb-vef-control-connection.c'),
        '-o', str(directory / 'production.o')],
        capture_output=True, text=True, timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'pin-connection', 'vef-path-device', 'infraimaging-format',
                'imaging-pin-connection', 'imaging-control-connection',
                'imaging-adf-connection', 'infrabb-vef-format', 'infrabb-vef-connection',
                'infrabb-vef-control-connection']
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST', '-DFULL_ADF_SET_OUTPUT_TEST',
        '-DFULL_VEF_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-infrabb-vef-control-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_fifth_control_edge_composed_contract(fifth_edge_binary, public_adf_input_seed,
                                             tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(fifth_edge_binary), case, str(seed)],
        capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'INFRABB_VEF_CONTROL_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in SUCCESS:
        prefix = 'FULL_INFRABB_VEF_CONTROL_CONNECT_'
        tags = ['PEER_REQUEST ', 'PEER_REPLY ', 'SOURCE_POSTHOOK ',
                'POSTHOOK_NO_FORMAT ', 'REPLY_QUEUED ', 'COMMIT ']
        positions = [result.stdout.index(prefix + tag) for tag in tags]
        assert positions == sorted(positions)
        assert result.stdout.count(prefix + 'REPLY_QUEUED ') == 1
        assert result.stdout.count(prefix + 'REPLY_FREE ') == 1
        assert 'peer_ordinal=14 selected_ordinals=1,2,3 selected=0' in result.stdout
        assert 'DMM_allocations=0 notifications=0 cache_writes=0 marker_writes=0' in result.stdout
        assert 'FULL_INFRABB_VEF_CONNECT_COMMAND_RETURNED ' in result.stdout
        assert 'FULL_INFRABB_VEF_CONNECT_REPLY_FREE ' in result.stdout
        assert 'FULL_IMAGING_ADF_CONNECT_REPLY_FREE ' in result.stdout
        assert 'FULL_PIN_FORMAT_COMMIT ' in result.stdout
        assert 'FULL_VEF_PATH_REPLY_FREE ' in result.stdout
        assert 'capture_verified=0' in result.stdout
