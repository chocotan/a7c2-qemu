"""Bounded owned-empty ADF resource prep, not whole Idle or pixel completion."""
from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


def test_cold_resource_preparation_readback_and_fail_closed_ownership(tmp_path):
    binary = tmp_path / 'adf-idle-resources'
    built = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-idle-resources.c'),
        str(MODEL / 'test-adf-idle-resources.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_IDLE_PREPARATION_PASS' in result.stdout
    assert 'ADF_IDLE_RESOURCES_PASS' in result.stdout
    assert 'preparation_only=1 adf_complete=0 pixel_work=0' in result.stdout
