# SPDX-License-Identifier: MIT
"""Startup face facade: real DMM/registry, host transport only; no VM or GUI."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = (
    "units", "queued", "ticket", "receive-failure", "reply-source", "reply-wire",
    "request-free-failure", "reply-free-failure", "send-failure", "send-after-inline",
    "inline", "inline-operations", "open-queued", "share-queued", "close-queued", "free-queued",
    "metadata", "ambiguity", "threads", "tid", "fork", "pointer", "reentry", "wire",
)
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]
SOURCES = ("functional-face-runtime.c", "functional-face-dmm.c", "functional-face-registry.c")


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    # Harness includes only facade for its private fork-lock check. Models are
    # separately linked original implementations, never substituted callbacks.
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            str(HERE / "test-functional-face-runtime.c"), str(HERE / SOURCES[1]),
            str(HERE / SOURCES[2]), str(HERE / "dmm-service.c"), "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-face-runtime") / "test-runtime"
    result = subprocess.run(compile_command(output, sanitize=request.param),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("mode", MODES)
def test_actual_receipt_ledger(executable, mode):
    options = "detect_leaks=1:halt_on_error=1"
    if mode == "pointer":
        options += ":quarantine_size_mb=0:thread_local_quarantine_size_kb=0"
    env = dict(os.environ, ASAN_OPTIONS=options,
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), mode], env=env, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FACE_RUNTIME_PASS mode={mode}" in result.stdout
    if mode == "units":
        assert ("COUNTS units=3 write=514304 read=514304 actual_receive=21 "
                "request_free=21 reply_free=21 ledger_commit=18 speech_unchanged=1") in result.stdout
        assert all(line in result.stdout for line in (
            "BYTES unit=1d9 bytes=409600 digest=1052ca7797d52e25",
            "BYTES unit=1da bytes=51200 digest=d5cf8c7478132325",
            "BYTES unit=1db bytes=53504 digest=b05da93981cdc4a5"))
    if mode == "wire":
        assert "WIRE fixed_mutations=150 exact40=1 free_source_low16=1" in result.stdout
    if mode == "pointer":
        assert "POINTER real_malloc_reuse=1 fresh_message_unclaimed=1" in result.stdout
    if mode == "reentry":
        assert re.search(r"REENTRY logs=\d+ callback_snapshots=\d+ real_model_busy=\d+", result.stdout)


def test_standalone_facade_exports(tmp_path):
    output = tmp_path / "face-runtime.so"
    result = subprocess.run([*shlex.split(os.environ.get("CC", "cc")), *FLAGS,
                             "-shared", "-fPIC", *(str(HERE / name) for name in SOURCES),
                             "-o", str(output)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    symbols = subprocess.run(["nm", "-g", "--defined-only", str(output)],
                             check=True, capture_output=True, text=True, timeout=10).stdout
    names = {line.split()[-1] for line in symbols.splitlines()}
    assert {name for name in names if name.startswith("functional_face_runtime_")} == {
        "functional_face_runtime_prepare", "functional_face_runtime_dispatch",
        "functional_face_runtime_observe", "functional_face_runtime_release",
        "functional_face_runtime_lookup_creator", "functional_face_runtime_borrow_destination",
        "functional_face_runtime_snapshot",
    }


def test_aarch64_guest_libc_225_no_undefined(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires installed clang/lld and AArch64 readelf")
    library = HERE / "menu-root/lib"
    names = ("libc-2.25.so", "libpthread-2.25.so", "ld-2.25.so")
    if not all((library / name).is_file() for name in names):
        pytest.skip("guest libc 2.25 link libraries unavailable")
    output = tmp_path / "face-runtime-aarch64.so"
    result = subprocess.run([
        compiler, "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib", "-O2",
        "-mno-outline-atomics", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-DFULL_IMAGING_GUEST", "-isystem", "/usr/aarch64-linux-gnu/include", "-shared",
        "-fPIC", "-Wl,--no-undefined", *(str(HERE / name) for name in SOURCES),
        *(str(library / name) for name in names), "-o", str(output),
    ], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    imported = subprocess.run([reader, "--dyn-syms", "-W", str(output)], check=True,
                              capture_output=True, text=True, timeout=10).stdout
    assert "__isoc23" not in imported and "__aarch64_" not in imported
    for name in ("getpid", "syscall", "malloc", "free", "memset", "memcpy",
                 "pthread_mutex_lock", "pthread_mutex_unlock", "pthread_mutex_trylock", "mmap", "munmap"):
        assert re.search(rf"\b{name}@GLIBC_2\.17\b", imported), name
    assert re.search(r"\b(?:memcmp|bcmp)@GLIBC_2\.17\b", imported)
    versions = subprocess.run([reader, "--version-info", "-W", str(output)], check=True,
                              capture_output=True, text=True, timeout=10).stdout
    assert set(re.findall(r"Name: (GLIBC_\d+\.\d+)", versions)) == {"GLIBC_2.17"}
