"""Cold HDMI monitor emits real AF/B0/B0 jobs and retains failed transactions."""
from pathlib import Path
import os
import re
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_adf_hdmi_monitor_real_queue_and_strict_owned_state(tmp_path):
    binary = tmp_path / 'adf-hdmi-monitor'
    result = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-hdmi-monitor.c'),
        str(MODEL / 'test-adf-hdmi-monitor.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([
        str(binary),
    ], capture_output=True, text=True, timeout=10, env=dict(
        os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
        UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        'ADF_HDMI_MONITOR_REAL_AF_B0_B0_SAME_FIRST8_OPAQUE243_PASS',
        'ADF_HDMI_MONITOR_FULL20B_FORMAT_ORDER_GENERATIONS_REJECT_PASS',
        'ADF_HDMI_MONITOR_CTOR_NO_RESET_COPIES_ALL_OWNED_TAMPER_REJECT_PASS',
        'ADF_HDMI_MONITOR_EMIT_FAILURE_NO_SUBMISSION_COUNT_RETAINED_PASS',
        'ADF_HDMI_MONITOR_REENTRY_CALLBACK_TAMPER_RETAINED_PASS',
    ):
        assert marker + '\n' in result.stdout
    count = re.search(r'^ADF_HDMI_MONITOR_CASES=(\d+)$', result.stdout, re.MULTILINE)
    assert count and int(count[1]) >= 300, result.stdout
