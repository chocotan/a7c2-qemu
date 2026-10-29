"""Native edges8/9 reuse the seven real host providers; no VM/frame claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
BACKENDS = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
            'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
            'pin-connection', 'vef-path-device', 'infraimaging-format',
            'imaging-pin-connection', 'imaging-control-connection',
            'imaging-adf-connection', 'infrabb-vef-format', 'infrabb-vef-connection',
            'infrabb-vef-control-connection', 'vef-pinmem-input-connection',
            'vef-pinmem-control-connection', 'scalar-device', 'scalar-connection',
            'adf-connection', '../dmm-service']
DEFINES = ['-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
           '-DFULL_ADF_SET_OUTPUT_TEST', '-DFULL_VEF_TEST',
           '-Wl,--wrap=full_adf_set_input_claim_output',
           '-Wl,--wrap=full_vef_path_snapshot']
CASES = ['normal', 'dynamic-caller', 'uninitialized', 'predecessor-no-ap-free',
         'disabled-or-unrelated', 'bad-wire',
         'live-source-get', 'live-peer-get', 'resource-busy', 'guard-recheck', 'inline-free',
         'send-fail', 'inline-send-fail', 'request-free-fail', 'reply-free-fail',
         'wrong-owner', 'foreign-thread-free', 'recursive', 'recursive-free',
         'queued-fault', 'fork-held', 'in-flight-send-fail', 'in-flight-free-fail',
         'cleanup-fail', 'duplicate-event', 'request-mutated',
         *[f'alloc-fail-{n}' for n in range(1, 4)],
         *[f'alloc-short-{n}' for n in range(1, 4)],
         'alloc-alias-1', 'alloc-alias-2', 'alloc-alias-3',
         *[f'event-{n}' for n in range(1, 12)]]


@pytest.fixture(scope='module')
def native_peer_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('pinmem-native-peers')
    for source in ['scalar-connection', 'adf-connection']:
        built = subprocess.run(FLAGS + ['-c', str(MODEL / (source + '.c')),
            '-o', str(directory / (source + '.o'))], capture_output=True,
            text=True, timeout=30)
        assert built.returncode == 0, built.stdout + built.stderr
    binary = directory / 'model'
    built = subprocess.run(FLAGS + DEFINES + [
        *[str(MODEL / (name + '.c')) for name in BACKENDS],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-pinmem-native-peer-connections.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('edge', ['scalar', 'adf'])
def test_native_pinmem_peer_connections(native_peer_binary, public_adf_input_seed,
                                       edge, case):
    if public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    argument = ('adf-' if edge == 'adf' else '') + case
    result = subprocess.run([str(native_peer_binary), argument,
                             str(public_adf_input_seed)], capture_output=True,
                            text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_NATIVE_PEER_CONNECTIONS_HOST_TEST_PASS' in result.stdout
    if case in ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held']:
        prefix = 'FULL_' + edge.upper() + '_CONNECT_'
        tags = ['REQUEST ', 'PEER_REQUEST ', 'PEER_REPLY ', 'EVENT6_ENQUEUED ',
                'EVENT6_CONSUMED ', 'YC_DIRECTION_CHECK ', 'REPLY_QUEUED ',
                'REQUEST_FREE ', 'STATE_READBACK ']
        positions = [result.stdout.index(prefix + tag) for tag in tags]
        assert positions == sorted(positions)
        lines = [line for line in result.stdout.splitlines()
                 if any(line.startswith(prefix + tag) for tag in
                        ['PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED '])]
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in lines]
        assert [len(packet) for packet in packets] == [64, 72, 56]
        source = [0, 2, 1 if edge == 'scalar' else 2, 0x90590818]
        peer = [0, 1, 4 if edge == 'scalar' else 0,
                0x91670464 if edge == 'scalar' else 0x9058003f]
        key = lambda values: b''.join(v.to_bytes(4, 'little') for v in values)
        assert packets[0][32:] == packets[1][32:64] == key(source + peer)
        assert packets[1][64:] == bytes(8)
        assert packets[2][32:] == key(source) + bytes(8)
        assert all(packet[:4] == bytes(4) for packet in packets)
        assert 'parameter_bytes=12 cleared_bytes=12' in result.stdout
        assert 'original_CP_event_pointer_identity_verified=0' in result.stdout
        assert 'original_RTOS_scheduling_verified=0' in result.stdout


def test_foreign_seventh_reply_free_cannot_admit_eighth(native_peer_binary, public_adf_input_seed):
    test_native_pinmem_peer_connections(native_peer_binary,public_adf_input_seed,
                                       'scalar','predecessor-foreign-thread-free')


@pytest.mark.parametrize('source', ['scalar', 'adf'])
def test_existing_legacy_dispatchers(tmp_path, source):
    binary = tmp_path / source
    files = ['pin-registry-core', 'vef-device', 'pinmem-device', 'scalar-device',
             'adf-device', 'pin-buffer-owner', 'pin-buffer-wire', 'pin-connection',
             'pin-format', 'scalar-connection', 'adf-connection',
             'test-' + source + '-connection']
    # Legacy fixtures predate the native strict formatting; production files
    # and all new tests compile separately without suppressions above.
    built = subprocess.run(FLAGS + ['-Wno-misleading-indentation',
        '-DFULL_VEF_TEST', '-DPIN_CONTROL_TEST', '-DFULL_PIN_CONNECTION_TEST',
        *[str(MODEL / (name + '.c')) for name in files], '-o', str(binary)],
        capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            timeout=20, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert ('SECOND_EDGE_' if source == 'scalar' else 'THIRD_EDGE_') in result.stdout
