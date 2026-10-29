"""S0/K0 gate work only; original init F must be bound before runtime use."""
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_adf_aip_cold_gate_operations_and_init_parameter_preservation(tmp_path):
    binary = tmp_path / 'adf-aip-gates'
    built = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-aip-gates.c'), str(MODEL / 'test-adf-aip-gates.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_AIP_COLD_GATES_F0_F1_ORIGINAL_RMW_CLASSIFICATION_READBACK_PASS' in result.stdout
