"""One real host backing across old sharing and closed-consumer lifetimes; no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_pin_buffer_closed_consumer(tmp_path):
    binary = tmp_path / 'pin-buffer-closed-consumer'
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-no-pie', '-DPIN_CONTROL_TEST', str(MODEL / 'pin-buffer-owner.c'),
        str(MODEL / 'test-pin-buffer-closed-consumer.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        'CLOSED_CONSUMER_OLD_TWO_OWNER_CLOSE_REOPEN_AUTO_FREE_UNCHANGED_PASS',
        'CLOSED_CONSUMER_PID_GUARD_PRECEDES_INHERITED_LOCK_PASS',
        'CLOSED_CONSUMER_SECOND_GENERATION_80B_SSYN_READ_CLOSE_FREE_NO_EXTRA_CLOSE_PASS',
        'CLOSED_CONSUMER_NEVER_OPENED_OPTION0_FREE_PRESERVES_BYTES_AND_COUNTS_PASS',
    ):
        assert marker in result.stdout
