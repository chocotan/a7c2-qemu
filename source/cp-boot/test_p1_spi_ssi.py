# SPDX-License-Identifier: GPL-2.0-or-later
"""Synthetic P1 SSI checks only; no QEMU, firmware or physical device."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize('sanitized', [False, True], ids=['strict', 'asan-ubsan'])
@pytest.mark.parametrize('case', ['test-p1-spi-ssi.c', 'test-p1-spi-ssi-extra.c'],
                         ids=['protocol', 'checksum-and-wrap'])
def test_p1_spi_ssi_host_selftest(tmp_path, sanitized, case):
    compiler = shutil.which('cc')
    if compiler is None:
        pytest.skip('cc not available: environment gap')
    tmpdir = os.environ.get('TMPDIR')
    if not tmpdir:
        pytest.fail('set a project-local TMPDIR; do not use host /tmp')
    root = Path(tmpdir).resolve()
    if root.is_relative_to(Path('/tmp')) or not tmp_path.resolve().is_relative_to(root):
        pytest.fail('project-local TMPDIR must contain the pytest basetemp')
    flags = ['-std=c11', '-UNDEBUG', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g']
    if sanitized:
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
    executable = tmp_path / 'test-p1-spi-ssi'
    build = subprocess.run(
        [compiler, *flags, str(HERE / 'p1-spi-monitor.c'), str(HERE / 'p1-spi-ssi.c'),
         str(HERE / case), '-o', str(executable)], capture_output=True, text=True, timeout=120,
    )
    (tmp_path / 'build.stdout').write_text(build.stdout)
    (tmp_path / 'build.stderr').write_text(build.stderr)
    if build.returncode != 0:
        pytest.fail(build.stdout + build.stderr)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=120)
    (tmp_path / 'run.stdout').write_text(result.stdout)
    (tmp_path / 'run.stderr').write_text(result.stderr)
    if result.returncode != 0:
        pytest.fail(result.stdout + result.stderr)
