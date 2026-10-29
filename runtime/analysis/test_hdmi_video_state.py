"""Finite Initializing -> HPD_Lo owner; real receive/free is required for ready."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
FLAGS = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
ENV = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
           UBSAN_OPTIONS='halt_on_error=1')
CASES = [
    'disabled', 'uninitialized', 'late-init', 'fork', 'fork-held', 'metadata', 'unknown-dataflow', 'unknown-input',
    'missing-io', 'malformed', 'prefix-normalization', 'invalid0109',
    'request-alias', 'prefix-source-fail', 'prefix-request-free-fail',
    'prefix-reply-free-fail', 'incomplete-prefix', 'live-shared-reply',
    'no-backup', 'missing-required', 'failed-required', 'missing-upm',
    'normal', 'dynamic-queue', 'delegated-preserves', 'default-config',
    'full-config', 'upm-no-remap', 'reenter-connect', 'inline', 'inline-reuse', 'alloc-fail', 'alloc-partial',
    'alloc-short', 'cleanup-fail', 'early-free', 'send-fail',
    'inline-send-fail', 'inflight-send-fail', 'inflight-free-fail',
    'wrong-source', 'wrong-length', 'wrong-payload', 'no-receive', 'wrong-owner',
    'wrong-thread', 'free-fail', 'mutated-after-receive', 'repeat-receive',
    'bad-upm-remap', 'kernel-receipt', 'kernel-receipt-prepare-fail', 'kernel-receipt-incomplete',
]


@pytest.fixture(scope='module')
def state_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('hdmi-video-state')
    binary = directory / 'state'
    production = subprocess.run(FLAGS + ['-c', str(MODEL / 'hdmi-video-state.c'),
        '-o', str(directory / 'production.o')], capture_output=True, text=True,
        timeout=30)
    assert production.returncode == 0, production.stdout + production.stderr
    built = subprocess.run(FLAGS + ['-DFULL_HDMI_VIDEO_STATE_TEST', '-DFULL_HDMI_TEST',
        str(MODEL / 'hdmi-video-state.c'), str(MODEL / 'hdmi-device.c'),
        str(MODEL / 'test-hdmi-video-state.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', CASES)
def test_finite_state_and_observed_notification_ownership(state_binary, case):
    result = subprocess.run([str(state_binary), case], env=ENV, capture_output=True,
                            text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'HDMI_VIDEO_STATE_HOST_TEST_PASS' in result.stdout


def test_pinned_public_cp_constants_and_bounded_source_windows():
    cp = HERE.parents[5] / 'analysis/system/cpapp-b.bin'
    if not cp.exists():
        pytest.skip('pinned public CP original unavailable')
    data = cp.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    assert data[0xe4fc5e:0xe4fc5e + 28] == bytes.fromhex('929b52f48d72968cc292') + bytes(18)
    assert data[0xeec7d1] == 0  # fresh row0, slot4 / column8
    # Constructor, prefix setters, exit, HPD entry and non-deduplicating setter.
    for offset, expected in [
        (0x6299fe, 'b0b502af04469420'),
        (0x623c66, '0a780026'),
        (0x624c8e, '01280ed8'),
        (0x624f80, '2968'),
        (0x62547e, 'f0b503af'),
        (0x6255ee, 'f0b503af'),
        (0x126eba, '41f6e8602c70'),
        (0x126fe4, '40f61601'),
    ]:
        wanted = bytes.fromhex(expected)
        assert data[offset:offset + len(wanted)] == wanted, hex(offset)
