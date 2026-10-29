"""First cold HotShoe/Glee owners execute callbacks without clearing unknown work."""
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_adf_set_input_cold_owners_callback_order_and_fail_closed_state(tmp_path):
    binary = tmp_path / 'adf-set-input-cold-owners'
    result = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-set-input-cold-owners.c'),
        str(MODEL / 'test-adf-set-input-cold-owners.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([
        str(binary),
    ], capture_output=True, text=True, timeout=10, env=dict(
        os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
        UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_COLD_HOTSHOE_REAL_POP_CALLBACK_COMMIT_PASS' in result.stdout
    assert 'ADF_COLD_HOTSHOE_STALE_FOREIGN_ASYNC_REENTRY_RETAINED_PASS' in result.stdout
    assert 'ADF_COLD_GLEE_REAL_CALLBACK_NO_JOBS_NO_CACHE_POWER_WRITES_PASS' in result.stdout
    assert 'ADF_COLD_GLEE_MISSING_HISTORY_MUTATION_REENTRY_RETAINED_PASS' in result.stdout
    assert 'ADF_SET_INPUT_COLD_OWNERS_CASES=101\n' in result.stdout
