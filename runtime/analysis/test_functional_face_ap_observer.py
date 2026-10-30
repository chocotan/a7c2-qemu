# SPDX-License-Identifier: MIT
"""Passive original-AP metadata only; never a pin or native byte provider."""
import os
from pathlib import Path
import re
import shlex
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def observer_binary(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("face-ap-observer")
    binary = root / "observer"
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    if request.param:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command = [*shlex.split(os.environ.get("CC", "cc")), *flags, "-I", str(HERE),
               str(HERE / "functional-face-ap-observer.c"), str(HERE / "test-functional-face-ap-observer.c"),
               "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("mode", ["lifecycle", "gates", "retained", "reply", "sendfail", "freefail", "fork", "sequence", "births"])
def test_passive_metadata_and_original_lifetime(observer_binary, mode):
    result = subprocess.run([str(observer_binary), mode], capture_output=True, text=True, timeout=20,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"AP_OBSERVER_HOSTTEST_PASS mode={mode}" in result.stdout
    assert "native_pin=0 byte_access=0 capture_verified=0" in result.stdout


def test_aarch64_original_libc225_link_only(tmp_path):
    library = tmp_path / "observer.so"
    firmware = HERE / "menu-root/lib"
    command = ["clang", "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib", "-shared", "-fPIC",
               "-O2", "-mno-outline-atomics", "-DFULL_IMAGING_GUEST", "-std=c11", "-Wall", "-Wextra",
               "-Werror", "-pedantic", "-isystem", "/usr/aarch64-linux-gnu/include", "-Wl,--no-undefined",
               str(HERE / "functional-face-ap-observer.c"), str(firmware / "libc-2.25.so"),
               str(firmware / "ld-2.25.so"), "-o", str(library)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    versions = subprocess.run(["readelf", "--version-info", str(library)], capture_output=True, text=True, check=True)
    assert set(re.findall(r"GLIBC_\d+\.\d+", versions.stdout)) <= {"GLIBC_2.17"}
