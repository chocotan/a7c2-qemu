"""Seventh edge: actual six-provider history and finite event8; no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'unrelated', 'short', 'long', 'other-edge', 'uninitialized',
         'fork', 'invalid-source', 'no-prior', 'missing-transport', 'missing-guard',
         'unsupported-controls', 'bad-wire']
SUCCESS = ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held', 'repeat']
CASES = [*SUCCESS, 'no-sixth', 'no-sixth-AP-free', 'no-source-get', 'no-peer-get',
         'live-source-get', 'live-peer-get', 'resource-busy',
         'recursive-free', 'queued-fault', 'foreign-thread-free', 'in-flight-send-fail', 'in-flight-free-fail',
         'send-fail', 'inline-send-fail', 'request-free-fail', 'reply-free-fail',
         'wrong-owner', 'cleanup-fail', 'duplicate-event', 'request-mutated',
         *[f'event-{n}' for n in range(1, 10)],
         *[f'alloc-{n}-{kind}' for n in range(1, 4) for kind in range(1, 6)],
         'alloc-2-6', *[f'source-{n}' for n in range(1, 4)],
         'wire-1-26', 'wire-1-44', 'wire-2-48', 'wire-2-64',
         'wire-2-68', 'wire-3-32', 'wire-3-48']


@pytest.fixture(scope='module')
def seventh_edge_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('vef-pinmem-control-connection')
    binary = directory / 'model'
    production = subprocess.run(FLAGS + [
        '-c', str(MODEL / 'vef-pinmem-control-connection.c'),
        '-o', str(directory / 'production.o')],
        capture_output=True, text=True, timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'pin-connection', 'vef-path-device', 'infraimaging-format',
                'imaging-pin-connection', 'imaging-control-connection',
                'imaging-adf-connection', 'infrabb-vef-format', 'infrabb-vef-connection',
                'infrabb-vef-control-connection', 'vef-pinmem-input-connection',
                'vef-pinmem-control-connection']
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST', '-DFULL_ADF_SET_OUTPUT_TEST',
        '-DFULL_VEF_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        '-Wl,--wrap=full_vef_path_snapshot',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-vef-pinmem-control-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_seventh_edge_finite_event8_and_preservation(seventh_edge_binary,
                                                    public_adf_input_seed,
                                                    tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(seventh_edge_binary), case, str(seed)],
        capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VEF_PINMEM_CONTROL_CONNECTION_HOST_TEST_PASS' in result.stdout
    prefix = 'FULL_VEF_PINMEM_CONTROL_CONNECT_'
    if case in SUCCESS:
        tags = ['REQUEST ', 'PEER_REQUEST ', 'SINK_MANAGER ', 'PEER_REPLY ',
                'EVENT8_ENQUEUED ', 'EVENT8_CONSUMED ', 'POSTHOOK_NO_FORMAT ',
                'REPLY_QUEUED ', 'COMMIT ']
        positions = [result.stdout.index(prefix + tag) for tag in tags]
        assert positions == sorted(positions)
        for tag in tags + ['REPLY_FREE ']:
            assert result.stdout.count(prefix + tag) == 1
        lines = [line for line in result.stdout.splitlines() if any(
            line.startswith(prefix + kind) for kind in
            ['PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED '])]
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in lines]
        assert [len(p) for p in packets] == [64, 72, 56]
        assert [int.from_bytes(p[26:28], 'little') for p in packets] == [
            0x100, 0x8100, 0x8001]
        s = [8, 2, 0, 0x905a0048]
        p = [8, 1, 0, 0x90590818]
        key = lambda values: b''.join(v.to_bytes(4, 'little') for v in values)
        assert all(packet[:4] == bytes(4) for packet in packets)
        assert packets[0][32:64] == packets[1][32:64] == key(s + p)
        assert packets[1][64:72] == bytes(8)
        assert packets[2][32:56] == key(s) + bytes(8)
        assert 'source_ordinal=15 owned_table_readback=1' in result.stdout
        assert 'typed_callback_called=1 rc=0' in result.stdout
        assert 'original_CP_event_pointer_identity_verified=0' in result.stdout
        assert 'prior_six_edges_live_caches_DMM_NoMem_AB_failure_S0_preserved=1' in result.stdout
        assert 'capture_verified=0' in result.stdout
    if case.startswith('event-') or case in ['duplicate-event', 'request-mutated']:
        assert prefix + 'REPLY_QUEUED ' not in result.stdout
