"""BB's first mode job needs two real work returns, not just empty queues."""
from pathlib import Path
import os
import re
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_bb_mode_work_queue_owned_records_and_two_providers(tmp_path):
    binary = tmp_path / 'bb-mode-work-queue'
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'bb-mode-work-queue.c'),
        str(MODEL / 'test-bb-mode-work-queue.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([
        str(binary),
    ], capture_output=True, text=True, timeout=10, env=dict(
        os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
        UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        'BB_MODE_WORK_QUEUE_REAL_COPY_TWO_RETURNS_SHARED_TASKS_OPAQUE_GAP_PASS',
        'BB_MODE_WORK_QUEUE_MASKED_READ_UNKNOWN_GAP_REJECT_PASS',
        'BB_MODE_WORK_QUEUE_ORDER_GENERATION_TARGET_TASK_ADMISSION_REJECT_PASS',
        'BB_MODE_WORK_QUEUE_CTOR_ZERO_ONLY_COPY_IDENTITY_TAMPER_REJECT_PASS',
        'BB_MODE_WORK_QUEUE_PROVIDER_FAILURE_REENTRY_TAMPER_RETAINED_PASS',
        'BB_MODE_WORK_QUEUE_EMPTY_INFLIGHT_OR_WRAPPER0_NEVER_FINISHED_PASS',
    ):
        assert marker + '\n' in result.stdout
    count = re.search(r'^BB_MODE_WORK_QUEUE_CASES=(\d+)$', result.stdout, re.MULTILINE)
    assert count and int(count[1]) >= 900, result.stdout
