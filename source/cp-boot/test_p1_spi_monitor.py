# SPDX-License-Identifier: GPL-2.0-or-later
"""Host-only standalone protocol tests; no QEMU/VM/firmware execution.

Run with an explicit project-local TMPDIR and pytest --basetemp under it.
The implementation task deliberately does not execute these tests. This wrapper
is provided for the parent's consolidated acceptance run.
"""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize("sanitized", [False, True], ids=["strict", "asan-ubsan"])
def test_p1_spi_monitor_host_selftest(tmp_path, sanitized):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("cc not available: environment gap")
    tmpdir = os.environ.get("TMPDIR")
    assert tmpdir, "set a project-local TMPDIR; do not use host /tmp"
    root = Path(tmpdir).resolve()
    assert not root.is_relative_to(Path("/tmp")), "host /tmp is not allowed"
    assert tmp_path.resolve().is_relative_to(root), "--basetemp must follow TMPDIR"
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g"]
    if sanitized:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
    executable = tmp_path / "test-p1-spi-monitor"
    build = subprocess.run(
        [compiler, *flags, str(HERE / "p1-spi-monitor.c"),
         str(HERE / "test-p1-spi-monitor.c"), "-o", str(executable)],
        capture_output=True, text=True, timeout=120,
    )
    (tmp_path / "build.stdout").write_text(build.stdout)
    (tmp_path / "build.stderr").write_text(build.stderr)
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True,
                            timeout=120)
    (tmp_path / "run.stdout").write_text(result.stdout)
    (tmp_path / "run.stderr").write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == (
        "ALL P1 SPI MONITOR HOST CHECKS PASSED (virtual protocol only)\n"
    )
