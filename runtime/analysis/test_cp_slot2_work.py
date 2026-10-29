"""Unlinked host scaffold tests; no native CP/302c/capture success evidence."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'
CASES = (
    'normal', 'sparse-bank', 'invalid', 'fork', 'concurrent', 'no-executor',
    'enqueue-zero', 'enqueue-error', 'unknown-root', 'root-mismatch', 'root-span',
    'mode', 'execute-error', 'short-mask', 'unconsumed', 'wrong-bank',
    'invalid-mask', 'lost-during-execute', 'complete-error',
    'failure-callback-error', 'lost-generation',
)


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    directory = tmp_path_factory.mktemp('cp-slot2-work')
    obj, binary = directory / 'slot2.o', directory / 'slot2'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread']
    commands = (
        flags + ['-c', str(HERE / 'cp-slot2-work.c'), '-o', str(obj)],
        flags + [str(obj), str(HERE / 'test-cp-slot2-work.c'), '-o', str(binary)],
    )
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    return obj, binary


@pytest.mark.parametrize('case', CASES)
def test_actual_c_scaffold(compiled, case):
    _, binary = compiled
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary), case], cwd=binary.parent, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'original_worker=0 schedule_verified=0 completion_publish=0 capture=0' in result.stdout


def test_production_object_exports_only_public_api(compiled):
    obj, _ = compiled
    result = subprocess.run(['nm', '-g', '--defined-only', str(obj)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    symbols = {line.split()[-1] for line in result.stdout.splitlines()}
    assert symbols == {'cp_slot2_create', 'cp_slot2_destroy', 'cp_slot2_bind',
                       'cp_slot2_begin', 'cp_slot2_tick', 'cp_slot2_snapshot'}


def test_public_cp_source_pins_and_hex_stride():
    pins = json.loads((BASE.parent.parent / 'report/cp302c-module-source-pins.json').read_text())
    cp = BASE / 'menu-root/cp/cpapp-b.bin'
    if not cp.is_file():
        pytest.skip('public ALLLANG CP must be prepared separately; no private fallback')
    blob = cp.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == pins['CP_sha256'] == (
        'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')
    for pin in pins['pins']:
        raw = int(pin['raw'], 16)
        assert int(pin['CPVA'], 16) - raw == 0x108000
        window = blob[raw:raw + pin['length']]
        assert window == bytes.fromhex(pin['bytes']), pin['name']
        assert hashlib.sha256(window).hexdigest() == pin['sha256'], pin['name']
    assert blob[0x8c6d96 - 0x108000:0x8c6d9a - 0x108000].hex() == '4ff41262'
    contract = pins['module2_contract']
    assert int(contract['bank_stride'], 16) == 0x920
    assert contract['completion_record_hex'] == '757063000000000091e14d000000000000000000'
    assert not contract['bank_command_effects_closed'] and not contract['native_verified']
