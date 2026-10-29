"""Bounded fourth edge: real first/control/audio/VEF/NoMem host owners, no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

from test_adf_set_output_device import BACKENDS as BB_BACKENDS
from test_adf_set_input_device import public_adf_input_seed

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
FLAGS = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
EARLY = ['disabled', 'fork', 'invalid-source', 'no-prior']
CASES = ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'repeat',
         'recursive-free', 'queued-fault', 'in-flight-send-fail', 'in-flight-free-fail',
         'resource-busy', 'send-fail', 'inline-send-fail', 'request-free-fail',
         'reply-free-fail', 'wrong-owner', 'mismatch', 'cleanup-fail',
         *[f'alloc-{n}-{kind}' for n in range(1, 11) for kind in range(1, 6)],
         'alloc-2-6', *[f'source-{n}' for n in range(1, 11)],
         'wire-1-26', 'wire-2-64', 'wire-3-16', 'wire-4-4',
         'wire-5-8', 'wire-6-68', 'wire-7-20', 'wire-8-8',
         'wire-9-22', 'wire-10-32']
ENV = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
           UBSAN_OPTIONS='halt_on_error=1')


def _connection_binary(tmp_path_factory, source, name):
    directory = tmp_path_factory.mktemp(name)
    binary = directory / 'model'
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-buffer-wire', 'pin-format',
                'pin-registry-core', 'adf-device', 'vef-device', 'pinmem-device',
                'pin-connection', 'vef-path-device', 'infraimaging-format',
                'imaging-pin-connection', 'imaging-control-connection',
                'imaging-adf-connection', 'infrabb-vef-format', 'infrabb-vef-connection']
    result = subprocess.run(FLAGS + [
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST', '-DFULL_ADF_SET_OUTPUT_TEST',
        '-DFULL_VEF_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / source), '-o', str(binary)],
        capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.fixture(scope='module')
def fourth_edge_binary(tmp_path_factory):
    return _connection_binary(tmp_path_factory, 'test-infrabb-vef-connection.c',
                              'infrabb-vef-connection')


@pytest.fixture(scope='module')
def forwarded_format_binary(tmp_path_factory):
    return _connection_binary(tmp_path_factory, 'test-infrabb-vef-forward-format.c',
                              'infrabb-vef-forward-format')


@pytest.fixture(scope='module')
def fourth_format_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('infrabb-vef-format') / 'format'
    result = subprocess.run(FLAGS + [str(MODEL / name) for name in
        ['infrabb-vef-format.c', 'pin-format.c', 'pin-buffer-owner.c', 'test-infrabb-vef-format.c']]
        + ['-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('case', ['normal', 'bad-internal', 'not-connected', 'bad-header',
                                  'code', 'component', 'flags-low', 'flags-high',
                                  'width', 'height', 'unconsumed'])
def test_same_format_real_backing(fourth_format_binary, case):
    result = subprocess.run([str(fourth_format_binary), case], capture_output=True,
                            text=True, timeout=10, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'INFRABB_VEF_FORMAT_HOST_TEST_PASS' in result.stdout


@pytest.mark.parametrize('case', EARLY + CASES)
def test_fourth_edge_composed_host_contract(fourth_edge_binary, public_adf_input_seed,
                                           tmp_path, case):
    if case not in EARLY and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case not in EARLY else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(fourth_edge_binary), case, str(seed)],
        capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'INFRABB_VEF_CONNECTION_HOST_TEST_PASS' in result.stdout
    if case in ['normal', 'dynamic-caller', 'inline-free', 'recursive', 'repeat']:
        tags = ['COMMAND_PREPARED ', 'FORMAT_WRITTEN ', 'FORMAT_CONSUMED ',
                'BUFFER_RETIRED ', 'COMMAND_RETURNED ', 'REPLY_QUEUED ', 'COMMIT ']
        positions = [result.stdout.index('FULL_INFRABB_VEF_CONNECT_' + tag) for tag in tags]
        assert positions == sorted(positions)
        assert result.stdout.count('FULL_INFRABB_VEF_CONNECT_REPLY_QUEUED ') == 1
        assert result.stdout.count('FULL_INFRABB_VEF_CONNECT_REPLY_FREE ') == 1
        assert 'Free23_option0=1 share21=0' in result.stdout
        assert 'FULL_IMAGING_ADF_CONNECT_REPLY_FREE ' in result.stdout
        assert 'FULL_PIN_FORMAT_COMMIT ' in result.stdout
        assert 'FULL_VEF_PATH_REPLY_FREE ' in result.stdout
        assert 'capture_verified=0' in result.stdout


@pytest.mark.parametrize('case', ['normal', 'same', 'no-prior', 'prior-fault',
                                  'fork', 'closed', 'freed', 'bad-packets',
                                  'creator-live', 'wrong-handle', 'changed-after-vef'])
def test_forwarded_format_updates_live_owner(forwarded_format_binary,
                                             public_adf_input_seed, tmp_path, case):
    if case != 'no-prior' and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case != 'no-prior' else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(forwarded_format_binary), case, str(seed)],
        capture_output=True, text=True, timeout=35, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'INFRABB_VEF_FORWARD_HOST_TEST_PASS' in result.stdout


def test_public_source_constructor_and_bb_table():
    cp = HERE.parents[5] / 'analysis/system/cpapp-b.bin'
    if not cp.exists():
        pytest.skip('pinned public CP original unavailable')
    data = cp.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    assert data[0xfe79ac:0xfe79bc].hex() == '01000000000000008007000038040000'
    assert data[0x5f846e:0x5f8476].hex() == '4ff4f0604ff48761'
    assert data[0x5f8488:0x5f84a4].hex() == 'c4f898a8c4f89c6884f8a0a884f8a168a4f8a268c4f8a408c4f8a818'
    assert data[0x5fa4e4:0x5fa4f6].hex() == '80b56f460868c26c084600219047002080bd'
    assert data[0x10a928:0x10a938].hex() == '01000000020000000200000002000000'
