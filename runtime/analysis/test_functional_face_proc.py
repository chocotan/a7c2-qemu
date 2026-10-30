"""Host synthetic format tests only; no proc/device/guest I/O."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


HERE = Path(__file__).resolve().parent


@pytest.mark.parametrize("mode", ["strict", "asan-ubsan"])
def test_functional_face_proc(mode, tmp_path):
    compiler = shutil.which("cc" if mode == "strict" else "clang")
    assert compiler, f"required {mode} compiler unavailable"
    executable = tmp_path / "test-functional-face-proc"
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    if mode == "asan-ubsan":
        flags += [
            "-O1", "-g", "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
        ]
    else:
        flags += ["-O2"]
    command = [
        compiler, *flags, str(HERE / "functional-face-proc.c"),
        str(HERE / "test-functional-face-proc.c"), "-o", str(executable),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    environment = dict(os.environ)
    environment["ASAN_OPTIONS"] = "detect_leaks=1:abort_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    checked = subprocess.run(
        [str(executable)], capture_output=True, text=True,
        env=environment, timeout=60,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert len([line for line in checked.stdout.splitlines()
                if line.startswith("PASS ")]) == 18
    assert "functional-face-proc: 18 scenarios PASS; parser_calls=" in checked.stdout
    assert checked.stdout.endswith("HOST synthetic; native flags false\n")
    assert not checked.stderr
    print(f"{mode}: {checked.stdout}", end="")
