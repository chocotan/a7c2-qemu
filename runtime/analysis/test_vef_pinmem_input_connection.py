"""Sixth edge: actual five-provider chain, mapped SSYN forwarding, no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'unrelated', 'short', 'long', 'old-edge', 'uninitialized',
         'fork', 'invalid-source', 'no-prior', 'missing-transport']
SUCCESS = ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'fork-held', 'repeat']
CASES = [*SUCCESS, 'no-fifth-AP-free', 'live-peer-get', 'no-source-get', 'no-peer-get',
         *[f'status-{n}' for n in range(1, 6)], 'resource-busy',
         'recursive-free', 'queued-fault', 'in-flight-send-fail', 'in-flight-free-fail',
         'send-fail', 'inline-send-fail', 'request-free-fail', 'reply-free-fail',
         'wrong-owner', 'cleanup-fail',
         *[f'alloc-{n}-{kind}' for n in range(1, 16) for kind in range(1, 6)],
         'alloc-2-6', *[f'source-{n}-1' for n in range(1, 16)],
         *[f'source-{n}-2' for n in [3, 4, 5, 7, 8, 10, 11, 13, 14]],
         *[f'wire-{n}-1-{offset}' for n, offsets in [
             (1, [0, 26, 32, 44]), (2, [26, 64, 68]),
             (3, [4, 12, 22]), (4, [4, 8, 22]), (5, [8, 22]),
             (6, [0, 26, 32, 44, 48, 60, 64, 68, 72, 76]),
             (7, [8, 12, 20, 22]), (8, [8, 20]),
             (9, [26, 32, 44, 48, 60, 64, 68, 72]),
             (10, [8, 12, 20, 22]), (11, [8, 20]),
             (12, [26, 32, 44, 48, 60, 64, 68, 72]),
             (13, [8, 12, 20, 22]), (14, [8, 20, 22]),
             (15, [0, 26, 32, 44, 48, 52])]
          for offset in offsets],
         *[f'wire-{n}-2-{offset}' for n in [3, 4, 5, 7, 8, 10, 11, 13, 14]
          for offset in [0, 6, 12]],
         *[f'backing-{hop}-{offset}' for hop in range(1, 4)
          for offset in [0, 4, 40, 64, 65, 66, 72, 76]]]


@pytest.fixture(scope='module')
def sixth_edge_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('vef-pinmem-input-connection')
    binary = directory / 'model'
    production = subprocess.run(FLAGS + [
        '-c', str(MODEL / 'vef-pinmem-input-connection.c'),
        '-o', str(directory / 'production.o')],
        capture_output=True, text=True, timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'pin-connection', 'vef-path-device', 'infraimaging-format',
                'imaging-pin-connection', 'imaging-control-connection',
                'imaging-adf-connection', 'infrabb-vef-format', 'infrabb-vef-connection',
                'infrabb-vef-control-connection', 'vef-pinmem-input-connection']
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST', '-DFULL_ADF_SET_OUTPUT_TEST',
        '-DFULL_VEF_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        '-Wl,--wrap=full_vef_path_snapshot',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-vef-pinmem-input-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_sixth_edge_same_handle_composed_contract(sixth_edge_binary,
                                                 public_adf_input_seed,
                                                 tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(sixth_edge_binary), case, str(seed)],
        capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VEF_PINMEM_INPUT_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in SUCCESS:
        prefix = 'FULL_VEF_PINMEM_INPUT_CONNECT_'
        assert result.stdout.count(prefix + 'REPLY_QUEUED ') == 1
        assert result.stdout.count(prefix + 'REPLY_FREE ') == 1
        assert result.stdout.count(prefix + 'DMM_REQUEST ') == 9
        assert result.stdout.count(prefix + 'DMM_REPLY ') == 9
        assert result.stdout.count(prefix + 'FORMAT_NOTIFY ') == 3
        assert result.stdout.count(prefix + 'FORMAT_NOTIFY_CONSUMED ') == 3
        assert result.stdout.count(prefix + 'FORMAT_CONSUMED ') == 3
        assert result.stdout.count(prefix + 'REFERENCE_READBACK ') == 9
        for tag in ['FULL_INFRABB_VEF_FORWARD_VEF_FORMAT_CONSUMED ',
                    'FULL_INFRABB_VEF_FORWARD_BB_FORMAT_CONSUMED ',
                    'FULL_IMAGING_PIN_CONNECT_FORWARD_FORMAT_CONSUMED ']:
            assert result.stdout.count(tag) == 1
        lines = [line for line in result.stdout.splitlines()
                 if line.startswith(prefix + 'DMM_REQUEST ')]
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in lines]
        assert [len(p) for p in packets] == [152] * 5 + [216] * 4
        assert [int.from_bytes(p[:2], 'little') for p in packets] == [
            0x20, 0x21, 0x23, 0x24, 0x25, 0x24, 0x25, 0x24, 0x23]
        assert [int.from_bytes(p[20:22], 'little') for p in packets] == [0] * 5 + [0x55] * 4
        handles = [int.from_bytes(p[8:12], 'little') for p in packets[1:]]
        assert len(set(handles)) == 1 and handles[0] != 0
        notifications = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                         for line in result.stdout.splitlines()
                         if line.startswith(prefix + 'FORMAT_NOTIFY ')]
        assert all(int.from_bytes(p[68:72], 'little') == handles[0]
                   and p[72:80] == bytes(8) for p in notifications)
        assert 'payload_fnv64=37228cd728b41c0d' in result.stdout
        assert 'prior_five_histories_NoMem_AB_failure_S0_clocks_banks_preserved=1' in result.stdout
        assert result.stdout.index(prefix + 'BUFFER_RETIRED ') < result.stdout.index(prefix + 'REPLY_QUEUED ')
        assert 'capture_verified=0' in result.stdout
