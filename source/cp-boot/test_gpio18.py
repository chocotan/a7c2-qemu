# SPDX-License-Identifier: GPL-2.0-or-later
"""Pytest wrapper for the cp_gpio18 host self-test (no VM, no QEMU).

Builds gpio18.c + test-gpio18.c with strict flags plus ASan/UBSan and runs
the resulting binary. All build artifacts go to pytest's tmp_path; pytest
derives its temp root from the current TMPDIR (via tempfile.gettempdir()),
so nothing here defaults to /tmp. When TMPDIR is explicitly set, we assert
the tmp_path really lives under it.
"""
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = [os.path.join(HERE, "gpio18.c"), os.path.join(HERE, "test-gpio18.c")]
CFLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror",
          "-fsanitize=address,undefined"]


def test_gpio18_host_selftest(tmp_path):
    if shutil.which("cc") is None:
        pytest.skip("cc not available")
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir:
        assert os.path.realpath(tmp_path).startswith(
            os.path.realpath(tmpdir) + os.sep), (
            "tmp_path must follow the current TMPDIR, not /tmp")
    exe = tmp_path / "test-gpio18"
    build = ["cc", *CFLAGS, "-o", str(exe), *SOURCES]
    compiled = subprocess.run(build, capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run([str(exe)], capture_output=True, text=True,
                         timeout=120)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "ALL" in ran.stdout and "CHECKS PASSED" in ran.stdout, ran.stdout
