"""Parent-only test source: requires owner/test routing edits already integrated.

This worker does not collect, compile, or execute this module.
"""
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
CASES = ["identity-foreign-receive", "identity-foreign-free"]


@pytest.fixture(scope="module", params=["strict", "asan-ubsan"])
def identity_binary(tmp_path_factory, request):
    model = HERE / "device-models"
    assert (model / "test-bb-timecode-control.c").is_file()
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g", "-O1", "-pthread"]
    mode = request.param
    if mode == "asan-ubsan":
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    binary = tmp_path_factory.mktemp("identity-" + mode) / "owner"
    built = subprocess.run(["cc", *flags, "-I", str(model), str(model / "test-identity-refused.c"), "-o", str(binary)],
                           capture_output=True, text=True, timeout=45)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", CASES)
def test_identity_refusal(identity_binary, case):
    result = subprocess.run([str(identity_binary), case], capture_output=True, text=True, timeout=12,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1", LC_ALL="C"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"BB_TIMECODE_IDENTITY_CASE_PASS case={case} capture_verified=0 formal_verified=0"
