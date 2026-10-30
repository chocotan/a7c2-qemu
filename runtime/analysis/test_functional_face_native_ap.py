# SPDX-License-Identifier: MIT
"""HOST native-AP contract semantics; no native backend, VM or device IO."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = (
    "positive", "owner-life", "birth", "missing", "ticket", "transport",
    "query-fail", "mapping-fail", "close-fail", "free-fail", "consistency", "alias",
    "extent", "reads", "tokens", "reentry", "fork-thread", "observation",
    "scatter", "scatter-maps", "scatter-invalid", "scatter-alias", "scatter-change",
)
SOURCES = ("functional-face-native-ap.c", "functional-face-ap-observer.c",
           "functional-face-runtime.c", "functional-face-registry.c",
           "functional-face-dmm.c", "functional-face-transfer.c")
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    # The unchanged runtime fixture includes runtime.c; real DMM/registry and
    # transfer are linked separately. Count successful real CP lease releases.
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            str(HERE / "test-functional-face-native-ap.c"),
            *(str(HERE / name) for name in SOURCES if name != "functional-face-runtime.c"),
            str(HERE / "dmm-service.c"), "-Wl,--wrap=functional_face_dmm_release_borrow",
            "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-face-native-ap") / "test-native-ap"
    result = subprocess.run(compile_command(output, sanitize=request.param),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("mode", MODES)
def test_native_ap_host_contract(executable, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), mode], capture_output=True, text=True,
                            env=env, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FACE_NATIVE_AP_HOST_PASS mode={mode} native_io_bound=0" in result.stdout
    if mode in ("positive", "scatter"):
        assert ("NATIVE_HOST_COUNTS units=3 source_read=514304 cp_write=514304 "
                "cp_internal_read=514304 independent_read=514304 write_leases=3 read_leases=3 "
                "extra_owner=3 open=3 close=3 balance=3 producer_free=3 backing_free=3 "
                "cp_receive=6 cp_request_free=6 cp_reply_free=6 speech_bytes=1048576 "
                "speech_unchanged=1 native_io_bound=0") in result.stdout
        for i, size in enumerate((409600, 51200, 53504)):
            digest = 14695981039346656037
            for j in range(size):
                byte = ((j * 37 + i * 53 + 11) ^ (j >> 7)) & 255
                digest = ((digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
            assert (f"NATIVE_HOST_BYTES unit={0x1d9 + i:x} bytes={size} digest={digest:016x} "
                    "owner=1:2:1:0") in result.stdout
        if mode == "scatter":
            for unit, pages in ((0x1d9, 100), (0x1da, 13), (0x1db, 14)):
                assert (f"NATIVE_HOST_SCATTER unit={unit:x} cp_pages={pages} mapped_bytes={pages * 4096} "
                        "sdk_ranges=3 mailer_ranges=16 host_canonical_only=1") in result.stdout
    if mode == "scatter-maps":
        assert ("NATIVE_HOST_SCATTER_MAPS coalesced=1 distinct_backings=1 cp_holes=1 "
                "mailer_holes=1 endpoint=1 max128=1") in result.stdout
    if mode == "scatter-invalid":
        assert "NATIVE_HOST_SCATTER_INVALID rejected=30 caller_unchanged=1 cp_unchanged=1" in result.stdout
    if mode == "scatter-alias":
        assert "NATIVE_HOST_SCATTER_ALIAS pairs=6 nonfirst=1 final_rounded_cp_page=1" in result.stdout
    if mode == "scatter-change":
        assert ("NATIVE_HOST_SCATTER_CHANGE mutations=14 paths=2 cp_mutations=18 cp_paths=2 "
                "ordered_identity=1 no_retry=1 caller_unchanged=1") in result.stdout


def test_aarch64_guest_libc_225_link_only(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires installed clang/lld and AArch64 readelf")
    library = HERE / "menu-root/lib"
    names = ("libc-2.25.so", "libpthread-2.25.so", "ld-2.25.so")
    if not all((library / name).is_file() for name in names):
        pytest.skip("guest libc 2.25 link libraries unavailable")
    output = tmp_path / "face-native-ap-aarch64.so"
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
    assert re.search(r"\bsyscall@GLIBC_2\.17\b", imported)
    versions = subprocess.run([reader, "--version-info", "-W", str(output)], check=True,
                              capture_output=True, text=True, timeout=10).stdout
    assert set(re.findall(r"Name: (GLIBC_\d+\.\d+)", versions)) == {"GLIBC_2.17"}
