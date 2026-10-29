"""Actual selector0 scheduler/control/callback consumption, not a ready ACK."""
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_adf_selector0_scheduler_control_callback_and_pending_order(tmp_path):
    binary = tmp_path / 'adf-input-state'
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-input-state.c'), str(MODEL / 'test-adf-input-state.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_INPUT_SCHEDULE_CONTROL_CALLBACK_DRAIN_PASS' in result.stdout
    assert 'ADF_INPUT_UNKNOWN_DUPLICATE_STALE_REENTRY_PASS' in result.stdout
    assert 'ADF_INPUT_PREMATURE_RECURSIVE_DUPLICATE_FANOUT_REJECTED' in result.stdout
    assert 'ADF_INPUT_PREMATURE_CLEAR_BAD_READBACK_CROSS_GENERATION_PASS' in result.stdout
