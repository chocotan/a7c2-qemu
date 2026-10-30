# SPDX-License-Identifier: MIT
"""CP-only registry host byte tests. No VM, media, source-pin or private-state runs."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = ("units", "shape", "identity", "overlap", "generation", "ranges", "overflow", "threads", "fork")
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            str(HERE / "test-functional-face-registry.c"), str(HERE / "functional-face-dmm.c"),
            str(HERE / "dmm-service.c"), "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-face-registry") / "test-registry"
    result = subprocess.run(compile_command(output, sanitize=request.param),
                            timeout=60, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("mode", MODES)
def test_cp_registry_and_owned_bytes(executable, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), mode], env=env, timeout=20,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FACE_REGISTRY_PASS mode={mode}" in result.stdout
    if mode == "units":
        assert "COUNTS units=3 write=514304 read=514304 requests=21 replies=21 received=21 consumed=18 speech_unchanged=1" in result.stdout
        assert len(re.findall(r"BYTES unit=1d[9ab] bytes=\d+ digest=[0-9a-f]{16}", result.stdout)) == 3
        assert all(line in result.stdout for line in (
            "BYTES unit=1d9 bytes=409600 digest=1052ca7797d52e25",
            "BYTES unit=1da bytes=51200 digest=d5cf8c7478132325",
            "BYTES unit=1db bytes=53504 digest=b05da93981cdc4a5"))


def test_standalone_registry_exports(tmp_path):
    output = tmp_path / "face-registry.so"
    result = subprocess.run([*shlex.split(os.environ.get("CC", "cc")), *FLAGS, "-fPIC", "-shared",
                             str(HERE / "functional-face-registry.c"), "-o", str(output)],
                            timeout=60, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    symbols = subprocess.run(["nm", "-g", "--defined-only", str(output)], check=True,
                             timeout=10, capture_output=True, text=True).stdout
    assert {line.split()[-1] for line in symbols.splitlines()} == {
        "functional_face_registry_callbacks", "functional_face_registry_inspect_span"}


def test_aarch64_hand_declared_guest_libc_225(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires installed clang/lld and AArch64 readelf")
    library = HERE / "menu-root/lib"
    names = ("libc-2.25.so", "libpthread-2.25.so", "ld-2.25.so")
    if not all((library / name).is_file() for name in names):
        pytest.skip("guest libc 2.25 link libraries unavailable")
    output = tmp_path / "face-registry-dmm-aarch64.so"
    result = subprocess.run([compiler, "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib",
                             "-O2", "-mno-outline-atomics", "-std=c11", "-Wall", "-Wextra", "-Werror",
                             "-pedantic", "-DFULL_IMAGING_GUEST", "-isystem", "/usr/aarch64-linux-gnu/include",
                             "-shared", "-fPIC", "-Wl,--no-undefined",
                             str(HERE / "functional-face-registry.c"), str(HERE / "functional-face-dmm.c"),
                             *(str(library / name) for name in names), "-o", str(output)],
                            timeout=60, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    imported = subprocess.run([reader, "--dyn-syms", "-W", str(output)], check=True,
                              timeout=10, capture_output=True, text=True).stdout
    assert "__isoc23" not in imported and "__aarch64_" not in imported
    for name in ("pthread_mutex_trylock", "pthread_mutex_unlock", "mmap", "munmap", "getpid", "memcpy"):
        assert re.search(rf"\b{name}@GLIBC_2\.17\b", imported), name
    versions = subprocess.run([reader, "--version-info", "-W", str(output)], check=True,
                              timeout=10, capture_output=True, text=True).stdout
    assert set(re.findall(r"Name: (GLIBC_\d+\.\d+)", versions)) == {"GLIBC_2.17"}
