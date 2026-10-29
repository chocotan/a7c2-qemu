# SPDX-License-Identifier: MIT
"""Parent-run functional MPR batch; no VM, devices or media files.

The C executable includes the actual adapter and links the existing real
parameter-set, AU, length and read-list consumers and guarded MPR memory.
Only bridge/OSAL/original-library boundaries and explicit failure gates are
HOST_TEST fixtures. Do not run until the parent joins the batch.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REPORT = ROOT / "report"
MODES = (
    "lifecycle", "validation", "binding", "backpressure", "wrap", "es-full",
    "corruption", "instance", "size", "backend-error", "stop-join", "early-reply",
    "fork", "free-error", "reply-corrupt", "reply-size", "reply-source", "send-error",
    "allocator-error", "quarantine", "original-secondary", "secondary-validation",
    "unowned-buffer", "mixed-generation", "retire-es", "retire-info", "retire-cursor",
    "retire-counter", "retire-model", "memory-release-error", "fixed-release-error",
    "shutdown-active", "deferred-close-event", "receipt-wire", "receipt-avcc",
    "receipt-wrap", "receipt-malformed-read", "receipt-stop",
)
SOURCES = (
    HERE / "test-functional-mpr-codec.c",
    HERE / "functional-mpr-memory.c",
    REPORT / "native-video-binding/native-video.c",
    REPORT / "native-video-paramsets/native-paramsets.c",
    REPORT / "native-video-au-contract/native-au.c",
    REPORT / "native-video-length-format/native-lengths.c",
    REPORT / "native-video-ring-contract/native-ring.c",
)


def compile_command(output, *, sanitize=False):
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-pthread", "-ffunction-sections", "-fdata-sections", "-DFMPR_MEMORY_HOST_TEST"]
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            *map(str, SOURCES), "-Wl,--gc-sections",
            "-Wl,--wrap=functional_mpr_memory_write",
            "-Wl,--wrap=functional_mpr_memory_release", "-ldl", "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-mpr-codec") / "test-codec"
    subprocess.run(compile_command(output, sanitize=request.param), check=True, timeout=60,
                   capture_output=True, text=True)
    return output


@pytest.mark.parametrize("mode", MODES)
def test_actual_adapter(executable, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    completed = subprocess.run([str(executable), mode], env=env, timeout=15,
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_production_codec_memory_link(tmp_path):
    compiler = shlex.split(os.environ.get("CC", "cc"))
    flags = ["-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-pthread", "-fPIC", "-ffunction-sections", "-fdata-sections"]
    sources = [HERE / "functional-mpr-codec.c", HERE / "functional-mpr-memory.c",
               HERE / "functional-camera-bridge.c", *SOURCES[2:-1]]
    objects = []
    for index, source in enumerate(sources):
        output = tmp_path / f"production-{index}.o"
        visibility = ["-fvisibility=hidden"] if index >= 3 else []
        subprocess.run([*compiler, *flags, *visibility, "-c", str(source), "-o", str(output)],
                       check=True, timeout=60, capture_output=True, text=True)
        objects.append(str(output))
    library = tmp_path / "codec-memory.so"
    subprocess.run([*compiler, "-shared", "-pthread", *objects,
                    "-Wl,--gc-sections,--no-undefined", "-ldl", "-o", str(library)],
                   check=True, timeout=60, capture_output=True, text=True)
    undefined = subprocess.run(["nm", "-u", str(library)], check=True, timeout=10,
                               capture_output=True, text=True).stdout
    assert "video_engine_" not in undefined and "fmpr_test_" not in undefined
    assert "__wrap_" not in undefined and "fmpr_memory_test_" not in undefined


def test_guest_libc_abi_link(tmp_path):
    library_dir = HERE / "menu-root/lib"
    libraries = [library_dir / name for name in
                 ("libc-2.25.so", "libdl-2.25.so", "libpthread-2.25.so", "ld-2.25.so")]
    assert hashlib.sha256(libraries[0].read_bytes()).hexdigest() == (
        "f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9")
    flags = ["--target=aarch64-linux-gnu", "-O2", "-fPIC", "-mno-outline-atomics",
             "-isystem", "/usr/aarch64-linux-gnu/include"]
    sources = [HERE / "functional-mpr-codec.c", HERE / "functional-mpr-memory.c",
               HERE / "functional-camera-bridge.c", *SOURCES[2:-1]]
    objects = []
    for index, source in enumerate(sources):
        output = tmp_path / f"guest-{index}.o"
        metadata = ["-fvisibility=hidden", "-ffunction-sections", "-fdata-sections"] if index >= 3 else []
        subprocess.run(["clang", *flags, *metadata, "-c", str(source), "-o", str(output)],
                       check=True, timeout=60, capture_output=True, text=True)
        objects.append(str(output))
    undefined = subprocess.run(["llvm-nm", "-u", objects[0]], check=True, timeout=10,
                               capture_output=True, text=True).stdout
    assert "__isoc99_sscanf" in undefined and "__isoc23_sscanf" not in undefined
    output = tmp_path / "codec-memory-libc225.so"
    subprocess.run(["clang", "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib",
                    "-shared", "-fPIC", "-mno-outline-atomics", "-Wl,--no-undefined,--gc-sections",
                    *objects, *map(str, libraries), "-o", str(output)],
                   check=True, timeout=60, capture_output=True, text=True)
    symbols = subprocess.run(["llvm-readelf", "--dyn-syms", "--wide", str(output)],
                             check=True, timeout=10, capture_output=True, text=True).stdout
    assert "__isoc99_sscanf@GLIBC_2.17" in symbols and "__isoc23_sscanf" not in symbols
    for row in symbols.splitlines():
        if " UND " in row and "@GLIBC_" in row:
            version = row.split("@GLIBC_", 1)[1].split()[0]
            assert tuple(map(int, version.split("."))) <= (2, 25), row


def test_original_source_windows():
    pins = json.loads((REPORT / "functional-mpr-codec/source-pins.json").read_text())
    binary = (HERE / "menu-root/usr/lib/libmpr.so").read_bytes()
    assert len(binary) == pins["artifact"]["size"]
    assert hashlib.sha256(binary).hexdigest() == pins["artifact"]["sha256"]
    for window in pins["windows"]:
        offset, length = window["file_offset"], window["length"]
        raw = binary[offset:offset + length]
        assert len(raw) == length
        assert hashlib.sha256(raw).hexdigest() == window["sha256"], window["name"]
    assert pins["strict_gap_mask"] == 63 and pins["capture_verified"] is False
