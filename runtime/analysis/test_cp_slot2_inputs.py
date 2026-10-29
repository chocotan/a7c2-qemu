"""Unlinked finite source inputs only; no executor/publication/native success."""
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'
CASES = (
    'table-a', 'table-b', 'mode0-t-one', 'mode0-t-other', 'mode-nonzero',
    'exact-enums', 'unknown-read', 'conditional-unknown', 'token', 'short-span',
    'mask', 'alias', 'capacity-tail-alias', 'readonly-alias', 'overflow', 'missing', 'normal-0323',
    'normal-032c', 'normal-preserve', 'normal-exact-status', 'normal-unsupported',
    'normal-unknown', 'normal-invalid',
)


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    directory = tmp_path_factory.mktemp('cp-slot2-inputs')
    obj, binary = directory / 'inputs.o', directory / 'inputs'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    for command in (
        flags + ['-c', str(HERE / 'cp-slot2-inputs.c'), '-o', str(obj)],
        flags + [str(obj), str(HERE / 'test-cp-slot2-inputs.c'), '-o', str(binary)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    return obj, binary


@pytest.mark.parametrize('case', CASES)
def test_actual_finite_inputs(compiled, case):
    _, binary = compiled
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary), case], cwd=binary.parent, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        'inputs_staged_only=1 command_completed=0 original_CP_executed=0 publication=0')


def test_production_object_exports_only_finite_api(compiled):
    obj, _ = compiled
    result = subprocess.run(['nm', '-g', '--defined-only', str(obj)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert {line.split()[-1] for line in result.stdout.splitlines()} == {
        'cp_slot2_inputs_stage', 'cp_slot2_normal_word_032x'}


def test_public_cp_8a3bd8_source_window():
    cp = BASE / 'menu-root/cp/cpapp-b.bin'
    if not cp.is_file():
        pytest.skip('prepare the public ALLLANG CP separately; only this pin check is skipped')
    blob = cp.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == (
        'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')
    cpva, raw, length = 0x8a3bd8, 0x79bbd8, 134
    assert cpva - raw == 0x108000
    window = blob[raw:raw + length]
    assert len(window) == length
    assert hashlib.sha256(window).hexdigest() == (
        '5a5f0b4ffc489f04be1b4390a7e8e93e9933539d23f28e8e42c7bd89d2ba0929')
