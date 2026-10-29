"""Mode0 coefficient consumption is separate from AIP reset/gate/delay completion."""
from pathlib import Path
import hashlib
import os
import subprocess
import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


def test_adf_aip_mode0_coefficient_register_rmw(tmp_path):
    binary = tmp_path / 'adf-aip-coefficients'
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-aip-coefficients.c'), str(MODEL / 'test-adf-aip-coefficients.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_AIP_MODE0_16_ACTUAL_RMW_READBACK_UPPER_BITS_PRESERVED_PASS' in result.stdout


def test_adf_aip_original_mode0_coefficient_constructor_window():
    path = HERE / 'menu-root/cp/cpapp-b.bin'
    if not path.exists():
        pytest.skip('provision the original pinned ALLLANG CP image first')
    blob = path.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    start = 0xb6c904 - 0x108000
    assert hashlib.sha256(blob[start:start + 0xd6]).hexdigest() == (
        'd2772a1244288fdd4102d140785eeb7bd680de8746a477d505a6baf53a1961dd')
