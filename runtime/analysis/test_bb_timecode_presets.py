# SPDX-License-Identifier: MIT
"""Preset owner state, request bounds, original lifecycle, and failure scenarios."""
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
CASES = (
    'preset-preconditions', 'preset-tight-bounds', 'preset-validation',
    'preset-pair-independent', 'preset-raw-domain', 'preset-overflow',
    'preset-readback', 'preset-selector-readback', 'preset-generation-readback',
    'preset-request-alias', 'preset-allocation-null', 'preset-allocation-error',
    'preset-allocation-short', 'preset-source-drift', 'preset-cleanup-fail',
    'preset-guard-first', 'preset-guard-second', 'preset-reserve-fail',
    'preset-request-free-fail', 'preset-send-fail', 'preset-inline',
    'preset-inline-send-fail', 'preset-inline-free-fail', 'preset-wrong-free-thread',
    'preset-retained-alias', 'preset-receive-content', 'preset-receive-metadata',
    'preset-free-before-receive', 'preset-live-alias', 'preset-history-capacity',
)


@pytest.fixture(scope='module', params=['strict', 'asan-ubsan'])
def preset_binary(tmp_path_factory, request):
    binary = tmp_path_factory.mktemp('preset-owner-' + request.param) / 'owner'
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-O1', '-pthread']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    built = subprocess.run(['cc', *flags, '-I', str(HERE / 'device-models'),
                            str(HERE / 'device-models/test-bb-timecode-presets.c'), '-o', str(binary)],
                           capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', CASES)
def test_new_preset_owner(preset_binary, case):
    result = subprocess.run([str(preset_binary), case], capture_output=True, text=True, timeout=12,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1', LC_ALL='C'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f'BB_TIMECODE_PRESET_CASE_PASS case={case} capture_verified=0 physical_verified=0'
    assert not result.stderr
