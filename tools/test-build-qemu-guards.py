"""Host-only checks for the actual QEMU build source identity guard."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build-qemu.sh'
START = 'python3 - "$here/source/qemu-directory-sd.json" "$src" "$here/source" <<\'PY\'\n'


@pytest.mark.parametrize('valid', [True, False], ids=['matching-patch', 'changed-patch'])
def test_directory_sd_patch_guard_survives_python_optimization(tmp_path, valid):
    source = BUILD.read_text()
    assert source.count(START) == 2
    guard = source.split(START, 1)[1].split('\nPY\n', 1)[0] + '\n'
    assert "Directory-SD patch identity differs" in guard
    assert "record['before']" in guard
    script = tmp_path / 'source_guard.py'
    script.write_text(guard)
    assert script.read_text() == guard
    source_dir = tmp_path / 'synthetic-source'
    source_dir.mkdir()
    patch = source_dir / 'fixture.patch'
    patch.write_bytes(b'known synthetic patch\n')
    expected = hashlib.sha256(patch.read_bytes()).hexdigest()
    manifest = tmp_path / 'manifest.json'
    manifest_raw = json.dumps(dict(patch='fixture.patch', patch_sha256=expected, source_files={}))
    manifest.write_text(manifest_raw)
    assert manifest.read_text() == manifest_raw
    if not valid:
        patch.write_bytes(b'changed synthetic patch\n')
    assert patch.read_bytes() == (b'known synthetic patch\n' if valid else b'changed synthetic patch\n')
    command = [sys.executable, '-I', '-B', '-O', str(script), str(manifest), str(tmp_path), str(source_dir)]
    with (tmp_path / 'stdout.raw').open('xb') as stdout, (tmp_path / 'stderr.raw').open('xb') as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   env=dict(PATH='/usr/bin:/bin', TMPDIR=str(tmp_path), LC_ALL='C'))
        try:
            try:
                code = process.wait()
            except BaseException as error:
                while True:
                    try:
                        process.wait()
                        break
                    except BaseException as wait_error:
                        error.add_note('waiting for owned guard: ' + repr(wait_error))
                raise
        finally:
            stdout.flush(); stderr.flush()
            os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
    (tmp_path / 'result.json').write_text(json.dumps(dict(command=command, returncode=code)) + '\n')
    output, error = (tmp_path / 'stdout.raw').read_bytes(), (tmp_path / 'stderr.raw').read_bytes()
    assert json.loads((tmp_path / 'result.json').read_text())['returncode'] == code
    if valid:
        assert code == 0 and output == b'' and error == b''
    else:
        assert code != 0 and output == b'' and b'Directory-SD patch identity differs' in error


def test_build_script_uses_explicit_libfdt_symbol_guard():
    source = BUILD.read_text()
    assert "if not library.fdt_open_into or not library.fdt_setprop:" in source
    assert "raise SystemExit('Required host libfdt symbols are missing')" in source


@pytest.mark.parametrize('script', [BUILD, ROOT / 'runtime/analysis/qemu-kernel-probe.sh'],
                         ids=['build', 'usb-launcher'])
def test_shell_syntax_without_execution(tmp_path, script):
    with (tmp_path / 'syntax.stdout').open('xb') as stdout, (tmp_path / 'syntax.stderr').open('xb') as stderr:
        process = subprocess.Popen(['/bin/bash', '-n', str(script)], stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr,
                                   env=dict(PATH='/usr/bin:/bin', TMPDIR=str(tmp_path), LC_ALL='C'))
        try:
            try:
                code = process.wait()
            except BaseException as error:
                while True:
                    try:
                        process.wait()
                        break
                    except BaseException as wait_error:
                        error.add_note('waiting for owned shell: ' + repr(wait_error))
                raise
        finally:
            stdout.flush(); stderr.flush()
            os.fsync(stdout.fileno()); os.fsync(stderr.fileno())
    assert code == 0 and (tmp_path / 'syntax.stdout').read_bytes() == b''
    assert (tmp_path / 'syntax.stderr').read_bytes() == b''
