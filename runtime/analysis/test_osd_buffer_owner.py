"""Standalone mutable OSD FORMAT ownership; synthetic host backing, no VM claim."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_osd_buffer_owner(tmp_path):
    binary = tmp_path / 'osd-buffer-owner'
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-no-pie', '-Wl,--wrap=pthread_mutex_lock',
        str(MODEL / 'osd-buffer-owner.c'), str(MODEL / 'test-osd-buffer-owner.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary), '--self-check'], capture_output=True,
        text=True, timeout=20,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    markers = [line for line in result.stdout.splitlines()
               if line.startswith('OSD_POOL_') and line.endswith('_PASS')]
    assert len(markers) == 19 and len(set(markers)) == 19, result.stdout
    assert ('OSD_BUFFER_OWNER_SELF_CHECK_PASS checks=19 allocations=34 '
            'releases=51 live=0 faults=0') in result.stdout
