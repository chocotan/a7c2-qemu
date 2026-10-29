"""Finite OSD metadata edge after real first ten edges; no native VM claim.

The composed host tests link the production core and the same exported OSD
registry directly, with no temporary admission edits or owner replacement.
"""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'unrelated', 'short', 'other-key', 'uninitialized', 'fork',
         'missing-guard', 'bad-wire', 'no-prior']
SUCCESS = ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held',
           'repeat', 'foreign-thread-free', 'recursive-free']
CASES = [*SUCCESS, 'resource-busy', 'guard-mutation', 'preexisting-pool',
         'full-pool', 'active-row', 'unknown-row', 'no-ten-AP-free', 'no-source-get',
         'no-peer-get', 'live-source-get', 'live-peer-get', 'wrong-source-get',
         'source-state', 'peer-state', 'send-fail', 'inline-send-fail',
         'thread-send-fail', 'thread-free-fail', 'request-free-fail',
         'reply-free-fail', 'wrong-owner', 'request-mutated', 'cleanup-fail',
         'active-mask', 'unknown-mask', 'stale-resource', 'opaque-mutated',
         *[f'event-{n}' for n in range(1, 12)],
         *[f'alloc-{n}-{kind}' for n in [1, 2, 9, 10, 15, 17, 60, 114, 115]
           for kind in range(1, 6) if not (kind == 4 and n == 1)],
         *[f'source-{n}' for n in [1, 2, 9, 10, 15, 17, 60, 114, 115]],
         *[f'dmm-request-{n}' for n in [1, 5, 8, 13, 24, 47, 48]],
         *[f'dmm-reply-{n}' for n in [1, 5, 8, 13, 24, 47, 48]],
         *[f'notice-{n}' for n in [1, 2, 8, 9, 16]],
         'wire-9-26', 'wire-10-64', 'wire-115-32', 'wire-115-48']
BACKENDS = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
            'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device', 'scalar-device',
            'pin-connection', 'vef-path-device', 'infraimaging-format',
            'imaging-pin-connection', 'imaging-control-connection',
            'imaging-adf-connection', 'infrabb-vef-format',
            'infrabb-vef-connection', 'infrabb-vef-control-connection',
            'vef-pinmem-input-connection', 'vef-pinmem-control-connection',
            'scalar-connection', 'adf-connection', 'pinmem-drawinfo-connection',
            'osd-buffer-owner', 'osd-pin-format', 'pinmem-osd-connection',
            '../dmm-service']


@pytest.fixture(scope='module')
def osd_connection_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('pinmem-osd-connection')
    binary = directory / 'model'
    production = directory / 'production.o'
    built = subprocess.run(FLAGS + ['-c', str(MODEL / 'pinmem-osd-connection.c'),
                                   '-o', str(production)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(['nm', '-g', str(production)], capture_output=True,
                             text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert 'full_pinmem_osd_connection_test_' not in symbols.stdout
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        '-DFULL_ADF_SET_OUTPUT_TEST', '-DFULL_VEF_TEST',
        '-Wl,--wrap=full_adf_set_input_claim_output',
        '-Wl,--wrap=full_vef_path_snapshot',
        *[str(MODEL / (name + '.c')) for name in BACKENDS],
        str(HERE / 'osdpin-registry.c'), str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-pinmem-osd-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_osd_owned_wire_formats_and_persistent_references(osd_connection_binary,
                                                         public_adf_input_seed,
                                                         tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(osd_connection_binary), case, str(seed)],
                            capture_output=True, text=True, timeout=40, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_OSD_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in SUCCESS:
        prefix = 'FULL_PINMEM_OSD_CONNECT_'
        assert result.stdout.count(prefix + 'DMM_REQUEST ') == 48
        assert result.stdout.count(prefix + 'DMM_REPLY ') == 48
        assert result.stdout.count(prefix + 'PEER_NOTIFY ') == 4
        assert result.stdout.count(prefix + 'SOURCE_NOTIFY ') == 12
        assert result.stdout.count(prefix + 'REPLY_QUEUED ') == 1
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in result.stdout.splitlines()
                   if any(line.startswith(prefix + kind) for kind in
                          ['PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED '])]
        assert [len(packet) for packet in packets] == [64, 72, 56]
        assert [int.from_bytes(packet[26:28], 'little') for packet in packets] == [
            0x100, 0x8100, 0x8001]
        pair = [1, 3, 0, 0x90590818, 1, 3, 0, 0x9080003b]
        key = b''.join(value.to_bytes(4, 'little') for value in pair)
        assert packets[0][32:64] == packets[1][32:64] == key
        assert packets[1][64:72] == bytes(8)
        assert packets[2][32:56] == key[:16] + bytes(8)
        assert 'ACTUAL_FIRST10_HISTORY_AND_OLD404_SPEECH_UNCHANGED' in result.stdout
        assert 'CACHE100_COUNT=1 BACKING100_COUNT=0 capture_verified=0' in result.stdout
