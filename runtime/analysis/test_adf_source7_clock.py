"""Deterministic core checks; no claim about a real guest timer or original source7."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

import pytest

MODEL = Path(__file__).resolve().parent / 'device-models'


@pytest.fixture(scope='module')
def source7_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('adf-source7') / 'adf-source7-clock'
    result = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-source7-clock.c'), str(MODEL / 'adf-input-state.c'),
        str(MODEL / 'test-adf-source7-clock.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize(('case', 'marker'), [
    ('construction', 'ADF_SOURCE7_CONSTRUCTION_BIND_EPOCH0_PASS'),
    ('progress', 'ADF_SOURCE7_READS_WAIT_REAL_EVENT_DELAY129_DRAIN_PASS'),
    ('budget', 'ADF_SOURCE7_FOUR_DISTINCT_DUE_EVENTS_NO_CATCHUP_PASS'),
    ('fourth_pass', 'ADF_SOURCE7_FOURTH_PASS_INPUT_REQUIRES_EXPLICIT_PUMP_PASS'),
    ('wrap', 'ADF_SOURCE7_24BIT_WRAP_PHASE_PRESERVED_PASS'),
    ('continuation', 'ADF_SOURCE7_CONTINUE_SAME_OWNER_EPOCH4_THROUGH8_WRAP_PASS'),
    ('continuation_rejections', 'ADF_SOURCE7_CONTINUE_EARLY_CORRUPT_BACKWARD_OVERFLOW_REUSE_REJECTED'),
    ('continuation_ownership', 'ADF_SOURCE7_CONTINUE_OLD_GENERATION_GET_EVENT_DELAY_REJECTED'),
    ('continuation_cancellation', 'ADF_SOURCE7_CONTINUE_CANCEL_CURRENT_GENERATION_FAULT_PRESERVES_TOTAL_PASS'),
    ('continuation_overflow', 'ADF_SOURCE7_CONTINUE_MAX_DEADLINE_NO_OVERFLOW_EVENT_PASS'),
    ('output_continuation', 'ADF_SOURCE7_OUTPUT_CONTINUE_EPOCH8_SINGLE_EVENT9_WRAP_PHASE_PASS'),
    ('output_rejections', 'ADF_SOURCE7_OUTPUT_EARLY_CORRUPT_BACKWARD_OVERFLOW_DUPLICATE_REJECTED'),
    ('output_ownership', 'ADF_SOURCE7_OUTPUT_NO_RESET_REBIND_REARM_OLD_EVENT_DELAY_OR_GEN4_PASS'),
    ('output_cancellation', 'ADF_SOURCE7_OUTPUT_CANCEL_CURRENT_FAULT_PRESERVES_EVENT8_PASS'),
    ('output_overflow', 'ADF_SOURCE7_OUTPUT_MAX_DEADLINE_NO_OVERFLOW_EVENT_PASS'),
    ('clock_rejections', 'ADF_SOURCE7_UNKNOWN_ALIAS_GENERATION_REENTRY_STALE_REJECTED'),
    ('delay_rejections', 'ADF_SOURCE7_DELAY129_OWNERSHIP_DUPLICATE_INVALID_PROCESSING_REJECTED'),
    ('cancellation', 'ADF_SOURCE7_CANCELLATION_NEVER_NORMAL_COMPLETION_PASS'),
    ('overflow', 'ADF_SOURCE7_DEADLINE_OVERFLOW_NO_EVENT_PASS'),
])
def test_owned_virtual_source7_and_delay129(source7_binary, case, marker):
    result = subprocess.run([str(source7_binary), case], capture_output=True, text=True,
        timeout=10, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                            UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
