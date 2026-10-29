"""Tenth finite type6 edge after the actual nine-edge chain; no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'unrelated', 'short', 'other-key', 'uninitialized',
         'fork', 'no-prior', 'bad-wire', 'future-data', 'missing-guard']
SUCCESS = ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held',
           'repeat']
CASES = [*SUCCESS, 'no-ninth', 'no-ninth-AP-free', 'no-source-get', 'no-peer-get',
         'live-source-get', 'live-peer-get', 'source-status', 'peer-status',
         'resource-busy', 'send-fail', 'request-free-fail', 'reply-free-fail',
         'wrong-owner', 'request-mutated', 'cleanup-fail',
         *[f'alloc-{n}' for n in range(1, 4)],
         *[f'event-{n}' for n in range(1, 9)],
         *[f'source-{n}' for n in range(1, 4)],
         'wire-1-26', 'wire-1-44', 'wire-2-48', 'wire-2-64',
         'wire-2-68', 'wire-3-32', 'wire-3-48']


@pytest.fixture(scope='module')
def drawinfo_connection_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('pinmem-drawinfo-connection')
    binary = directory / 'model'
    production = subprocess.run(FLAGS + [
        '-c', str(MODEL / 'pinmem-drawinfo-connection.c'),
        '-o', str(directory / 'production.o')], capture_output=True, text=True,
        timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    symbols = subprocess.run(['nm', '-g', str(directory / 'production.o')],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert 'full_pinmem_drawinfo_connection_test_' not in symbols.stdout
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'scalar-device', 'pin-connection', 'vef-path-device',
                'infraimaging-format', 'imaging-pin-connection',
                'imaging-control-connection', 'imaging-adf-connection',
                'infrabb-vef-format', 'infrabb-vef-connection',
                'infrabb-vef-control-connection', 'vef-pinmem-input-connection',
                'vef-pinmem-control-connection', 'scalar-connection',
                'adf-connection', 'pinmem-drawinfo-connection', '../dmm-service']
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        '-DFULL_ADF_SET_OUTPUT_TEST', '-DFULL_VEF_TEST',
        '-Wl,--wrap=full_adf_set_input_claim_output',
        '-Wl,--wrap=full_vef_path_snapshot',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-pinmem-drawinfo-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_type6_drawinfo_guarded_metadata_connection(drawinfo_connection_binary,
                                                   public_adf_input_seed,
                                                   tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(drawinfo_connection_binary), case, str(seed)],
                            capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_DRAWINFO_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in SUCCESS:
        prefix = 'FULL_PINMEM_DRAWINFO_CONNECT_'
        for kind in ['REQUEST ', 'PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED ']:
            assert result.stdout.count(prefix + kind) == 1
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in result.stdout.splitlines()
                   if any(line.startswith(prefix + kind) for kind in
                          ['PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED '])]
        assert [len(packet) for packet in packets] == [64, 72, 56]
        assert [int.from_bytes(packet[26:28], 'little') for packet in packets] == [
            0x100, 0x8100, 0x8001]
        pair = [6, 2, 0, 0x90590818, 6, 1, 0, 0x928d0783]
        key = b''.join(value.to_bytes(4, 'little') for value in pair)
        assert packets[0][32:64] == packets[1][32:64] == key
        assert packets[1][64:72] == bytes(8)
        assert packets[2][32:56] == key[:16] + bytes(8)
        assert 'PRIOR_NINE_NATIVE_EDGES_BACKING_DMM_CACHES_HISTORY_PRESERVED' in result.stdout
        assert 'metadata_only=1 capture_verified=0' in result.stdout
        assert prefix + 'DMM_REQUEST ' not in result.stdout
        assert prefix + 'FORMAT_NOTIFY ' not in result.stdout
