"""Virtual AVIO first stages and same-owner NoOp; no real vsync or capture claim."""
from pathlib import Path
import os
import subprocess

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_avio_three_event_rmw_preservation_and_terminal_ownership(tmp_path):
    binary = tmp_path / 'adf-avio-output'
    result = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-avio-output.c'), str(MODEL / 'test-adf-avio-output.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_AVIO_THREE_DISTINCT_EVENTS_RMW_CHANGED_TOUCHED_PRESERVATION_PASS' in result.stdout
    assert 'ADF_AVIO_CALLBACK_EARLY_DUPLICATE_REENTRY_CROSS_GENERATION_PASS' in result.stdout
    assert 'ADF_AVIO_SAME_OWNER_CONTROL3_POP_BEFORE_CALLBACK_NOOP_STALE_DESCRIPTOR_PASS' in result.stdout
    assert 'ADF_AVIO_SAME_MASK_POWER_SLOT_EVENT_METADATA_REJECTIONS_PRESERVED_PASS' in result.stdout
    assert 'ADF_AVIO_SAME_POPPED_CALLBACK_REENTRY_TAMPER_FAILURE_EVIDENCE_PASS' in result.stdout
    assert 'ADF_AVIO_OUTPUT_PASS' in result.stdout
    assert 'output_only=1 idle_complete=0 capture_verified=0' in result.stdout
