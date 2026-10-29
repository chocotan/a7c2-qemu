"""Eleventh asynchronous edge, composed with ten real host owners; no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import re
import subprocess

import pytest

from test_adf_set_input_device import public_adf_input_seed
from test_infrabb_vef_connection import FLAGS, ENV, BB_BACKENDS

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
EARLY = ['disabled', 'unrelated', 'uninitialized', 'fork', 'bad-wire',
         'bad-source', 'bad-key', 'short', 'no-tenth']
SUCCESS = ['normal', 'dynamic-caller', 'dynamic-queue', 'recursive', 'fork-held',
           'audio-already-connected', 'resource-busy-while-pending',
           'inline-notifications', 'inline-AP-free', 'other-thread-progress',
           'foreign-AP-free', 'repeat', 'finish-window', 'finish-window-recursive']
CASES = [*SUCCESS, 'tenth-not-AP-free', 'foreign-Get-free',
         'no-source-get', 'no-peer-get', 'wrong-key-get',
         'live-source-get', 'live-peer-get', 'source-status', 'peer-status',
         'source-gate-unknown', 'resource-busy', 'missing-prefix', 'no-backup',
         'no-condition-free', 'no-upm-receive', 'direct-condition-free',
         'wrong-condition-source', 'wrong-condition-payload',
         'wrong-condition-thread', 'source-changed-while-pending',
         'registry-changed-while-pending',
         'request-mutated', 'answer-tail', 'send-fail', 'inline-send-fail',
         'inflight-send-fail', 'inflight-free-fail', 'request-free-fail',
         'AP-free-fail', 'wrong-AP-owner', 'cleanup-fail',
         *[f'{kind}-{n}' for kind in ('alloc', 'source', 'size', 'alias')
           for n in range(1, 4)], *[f'event-{n}' for n in range(1, 9)]]


@pytest.fixture(scope='module')
def video_connection_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('pinmem-hdmi-video-connection')
    binary = directory / 'model'
    production = subprocess.run(FLAGS + [
        '-c', str(MODEL / 'pinmem-hdmi-video-connection.c'),
        '-o', str(directory / 'production.o')], capture_output=True, text=True,
        timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    symbols = subprocess.run(['nm', '-g', str(directory / 'production.o')],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert 'full_pinmem_hdmi_video_connection_test_' not in symbols.stdout
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'scalar-device', 'pin-connection', 'vef-path-device',
                'infraimaging-format', 'imaging-pin-connection',
                'imaging-control-connection', 'imaging-adf-connection',
                'infrabb-vef-format', 'infrabb-vef-connection',
                'infrabb-vef-control-connection', 'vef-pinmem-input-connection',
                'vef-pinmem-control-connection', 'scalar-connection',
                'adf-connection', 'pinmem-drawinfo-connection',
                'hdmi-device', 'hdmi-pin-device', 'hdmi-video-state',
                'adf-hdmi-audio-connection',
                'pinmem-hdmi-video-connection', '../dmm-service']
    built = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST',
        '-DFULL_ADF_SET_OUTPUT_TEST', '-DFULL_VEF_TEST',
        '-DFULL_HDMI_VIDEO_STATE_TEST', '-DFULL_HDMI_TEST',
        '-Wl,--wrap=full_adf_set_input_claim_output',
        '-Wl,--wrap=full_vef_path_snapshot',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-pinmem-hdmi-video-connection.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', EARLY + CASES)
def test_type4_video_guarded_asynchronous_connection(video_connection_binary,
                                                     public_adf_input_seed,
                                                     tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(video_connection_binary), case, str(seed)],
                            capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_HDMI_VIDEO_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in SUCCESS:
        prefix = 'FULL_PINMEM_HDMI_VIDEO_CONNECT_'
        kinds = ['REQUEST ', 'PEER_REQUEST ', 'PEER_REPLY ', 'REPLY_QUEUED ']
        for kind in kinds:
            assert result.stdout.count(prefix + kind) == 1
        packets = [bytes.fromhex(re.search(r'raw=([0-9a-f]+)', line)[1])
                   for line in result.stdout.splitlines()
                   if any(line.startswith(prefix + kind) for kind in kinds)]
        assert [len(packet) for packet in packets] == [64, 64, 72, 56]
        assert [int.from_bytes(packet[26:28], 'little') for packet in packets] == [
            1, 0x100, 0x8100, 0x8001]
        key = b''.join(value.to_bytes(4, 'little') for value in [
            4, 2, 0, 0x90590818, 4, 1, 0, 0x909a015a])
        assert packets[0][32:64] == packets[1][32:64] == packets[2][32:64] == key
        assert packets[2][64:72] == bytes(8)
        assert packets[3][32:56] == key[:16] + bytes(8)
        assert result.stdout.count('FULL_HDMI_VIDEO_STATE_NATIVE_FREE ') == 26
        assert 'gate_reset_at_connect=0' in result.stdout
        assert 'PRIOR_TEN_PORTS_BACKING_DMM_CACHES_SPEECH_AND_HDMI_AUDIO_PRESERVED' in result.stdout
        assert 'actual_hdmi_notifications_consumed=26 frames=0 capture_verified=0' in result.stdout
        assert prefix + 'DMM_REQUEST ' not in result.stdout
        assert prefix + 'FORMAT_NOTIFY ' not in result.stdout
