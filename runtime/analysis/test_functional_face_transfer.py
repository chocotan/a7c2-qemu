# SPDX-License-Identifier: MIT
"""Actual face content consumer: owned test AP bytes and the real CP ledger/model."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = (
    "positive", "repeat", "sdk48", "api40", "init", "binding", "acquire", "malformed", "disjoint",
    "source-read", "long-errors", "stale-source", "destination-blocked", "stale-creator",
    "partial", "reentry", "fork", "source-release", "partial-source-release", "destination-write-release",
    "destination-read-release",
)
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]
SOURCES = ("functional-face-runtime.c", "functional-face-registry.c",
           "functional-face-dmm.c", "functional-face-transfer.c")
WRAPS = ("functional_face_dmm_write", "functional_face_dmm_read", "functional_face_dmm_release_borrow")


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    # The reused fixture includes runtime.c; every CP byte operation below still
    # calls the separately linked real DMM. Wrappers count or submit a bad nonce.
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            str(HERE / "test-functional-face-transfer.c"),
            *(str(HERE / name) for name in SOURCES[1:]), str(HERE / "dmm-service.c"),
            *(f"-Wl,--wrap={name}" for name in WRAPS), "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-face-transfer") / "test-transfer"
    result = subprocess.run(compile_command(output, sanitize=request.param),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("mode", MODES)
def test_actual_content_and_lease_lifecycle(executable, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), mode], env=env, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FACE_TRANSFER_PASS mode={mode}" in result.stdout
    if mode == "positive":
        assert ("COUNTS units=3 source_read=514304 write=514304 internal_readback=514304 "
                "independent_read=514304 full_verified=514304 write_release=3 read_release=3 "
                "source_release=3 actual_receive=6 request_free=6 reply_free=6 ledger_commit=6 "
                "speech_bytes=1048576 speech_unchanged=1") in result.stdout
        for i, size in enumerate((409600, 51200, 53504)):
            digest = 14695981039346656037
            for j in range(size):
                byte = ((j * 37 + (i + 1) * 53 + 11) ^ (j >> 7)) & 255
                digest = ((digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
            assert (f"POSITIVE unit={0x1d9 + i:x} result=0 operation=0 write={size} read={size} "
                    f"source_digest={digest:016x} destination_digest={digest:016x} releases=1/1 complete=1") in result.stdout
    if mode == "sdk48":
        assert "SDK48 goldens=3 reads_per_decode=4 rejected=31 exact48=1" in result.stdout
        assert "output_unchanged=1 wire_unchanged=1 tail_preserved=1 callbacks=0" in result.stdout
    if mode == "binding":
        assert re.search(r"BINDING rejected=34 acquired=0 unchanged=1", result.stdout)
    if mode == "partial":
        assert "suffix_untouched=1 actual_free_busy=1 actual_open_close=1" in result.stdout
    if mode == "repeat":
        assert "fresh_allocation=1 fresh_epoch=1 fresh_nonce=1 original_source_unchanged=1" in result.stdout
    if mode.endswith("-release") and mode.startswith("destination-"):
        assert "actual_stale_rejections=1 retained_full_token=1 live_borrow=1 retry_calls=0" in result.stdout


def test_aarch64_guest_libc_225_link_only(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires installed clang/lld and AArch64 readelf")
    library = HERE / "menu-root/lib"
    names = ("libc-2.25.so", "libpthread-2.25.so", "ld-2.25.so")
    if not all((library / name).is_file() for name in names):
        pytest.skip("guest libc 2.25 link libraries unavailable")
    output = tmp_path / "face-transfer-aarch64.so"
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
    assert re.search(r"\bgetpid@GLIBC_2\.17\b", imported)
    versions = subprocess.run([reader, "--version-info", "-W", str(output)], check=True,
                              capture_output=True, text=True, timeout=10).stdout
    assert set(re.findall(r"Name: (GLIBC_\d+\.\d+)", versions)) == {"GLIBC_2.17"}
