"""Tracked native resource admission, not whole-guest DMM idleness."""
from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


def test_resource_domains_lifecycle_atomic_gate_cleanup_and_fork(tmp_path):
    binary = tmp_path / 'vef-resource-guard'
    built = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-pthread',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        '-DFULL_VEF_RESOURCE_TEST', str(MODEL / 'vef-resource-guard.c'),
        str(MODEL / 'test-vef-resource-guard.c'), str(HERE / 'dmm-service.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VEF_DMM_DOMAIN_PASS' in result.stdout
    assert 'VEF_DMM_LIFECYCLE_PASS' in result.stdout
    assert 'VEF_RESOURCE_GUARD_PASS' in result.stdout
