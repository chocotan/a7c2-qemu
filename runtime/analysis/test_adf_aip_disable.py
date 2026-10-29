"""Three proven AF/B0/Notify2 B0 disables on the same cold register bank."""
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_adf_aip_disable_routes_data_consumption_and_cold_guard(tmp_path):
    binary = tmp_path / 'adf-aip-disable'
    built = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-aip-disable.c'), str(MODEL / 'test-adf-aip-disable.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_AIP_AF_B0_SEVEN_REAL_WRITES_READBACK_ACTIVE_BIT_PRESERVED_PASS' in result.stdout
