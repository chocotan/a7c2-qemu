# SPDX-License-Identifier: MIT
"""API40 functional callback frontend; actual host CP model and NativeAP fixture.

No Sony callback/native bytecode, VM, physical IO or capture runs in this suite.
"""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

import pytest

from test_functional_face_native_ap import FLAGS, SOURCES as NATIVE_SOURCES

HERE = Path(__file__).resolve().parent
SOURCES = ("functional-face-sdk.c", *NATIVE_SOURCES)
MODES = (
    "missing", "api40", "descriptors", "source-binding", "destination-stale",
    "three-units", "source-failures", "cp-faults", "source-release",
    "callback-failure", "caller-sender", "thread-reentry",
)


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    # Preserve the original fixture; main alone is renamed in this temp include.
    fixture = (HERE / "test-functional-face-native-ap.c").read_text()
    original = "int main(int argc, char **argv)"
    assert fixture.count(original) == 1
    (output.parent / "sdk-native-fixture.inc").write_text(
        fixture.replace(original, "int sdk_fixture_native_main(int argc, char **argv)"))
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            "-I", str(output.parent), "-I", str(HERE), str(HERE / "test-functional-face-sdk.c"),
            *(str(HERE / name) for name in SOURCES if name != "functional-face-runtime.c"),
            str(HERE / "dmm-service.c"),
            "-Wl,--wrap=functional_face_dmm_release_borrow",
            "-Wl,--wrap=functional_face_dmm_write", "-Wl,--wrap=functional_face_dmm_read",
            "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-face-sdk") / "test-sdk"
    result = subprocess.run(compile_command(output, sanitize=request.param),
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


@pytest.mark.parametrize("mode", MODES)
def test_api40_callback_frontend(executable, mode):
    result = subprocess.run([str(executable), mode], capture_output=True, text=True, timeout=20,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert (f"FACE_SDK_HOST_PASS mode={mode} native_io_bound=0 "
            "physical_verified=0 capture_verified=0") in result.stdout
    if mode == "three-units":
        assert ("SDK_HOST_COUNTS units=3 source_read=514304 cp_write=514304 "
                "cp_internal_read=514304 independent_read=514304 write_leases=3 read_leases=3 "
                "extra_owner=3 open=3 close=3 balance=3 typed_callback=3 speech_bytes=1048576 "
                "speech_unchanged=1 native_io_bound=0") in result.stdout
        for i, size in enumerate((409600, 51200, 53504)):
            digest = 14695981039346656037
            for j in range(size):
                byte = ((j * 37 + i * 53 + 11) ^ (j >> 7)) & 255
                digest = ((digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
            assert (f"SDK_HOST_BYTES unit={0x1d9 + i:x} bytes={size} digest={digest:016x} "
                    "status=0 original_context=1 callback_order=1 source_balance=0 cp_leases=0") in result.stdout


def test_aarch64_guest_libc_225_link_only(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires installed clang/lld and AArch64 readelf")
    library = HERE / "menu-root/lib"
    names = ("libc-2.25.so", "libpthread-2.25.so", "ld-2.25.so")
    if not all((library / name).is_file() for name in names):
        pytest.skip("guest libc 2.25 link libraries unavailable")
    output = tmp_path / "face-sdk-aarch64.so"
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
