"""Exact canonical Get retirement through the real shared registry transport."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import subprocess

import pytest

from test_infrabb_vef_connection import FLAGS, ENV

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
CASES = ['selected-key', 'low-byte-alias', 'hdmi-type-only', 'full-key',
         'wrong-destination', 'failed-free', 'foreign-thread', 'send-failed',
         'reset', 'invalid-owner', 'faulted-owner', 'wrong-registry']


@pytest.fixture(scope='module')
def key_retirement_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('pin-registry-key-retirement') / 'model'
    built = subprocess.run(FLAGS + ['-DFULL_VEF_TEST',
        str(MODEL / 'pin-registry-core.c'),
        str(MODEL / 'test-pin-registry-key-retirement.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', CASES)
def test_exact_canonical_key_get_retirement(key_retirement_binary, case):
    result = subprocess.run([str(key_retirement_binary), case],
                            capture_output=True, text=True, timeout=15, env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PIN_REGISTRY_EXACT_KEY_RETIREMENT_HOST_TEST_PASS' in result.stdout
