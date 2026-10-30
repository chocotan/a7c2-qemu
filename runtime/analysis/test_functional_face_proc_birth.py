# SPDX-License-Identifier: MIT
"""Host-only checks of the actual original-Birth proc diagnostic collector.

The complete production block is extracted unchanged. Only proc file IO,
AArch64 gettid(178), the record sink and counted real allocation are redirected;
the AP observer and complete-document proc parser are linked from production.
"""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
SCENARIOS = [
    "four-units", "repeat-sticky", "pre-io-gates", "birth-facts",
    "fork-owner", "open-error", "read-errors", "read-bounds",
    "close-error", "invalid-table", "changed-second", "offset-only",
    "birth-counters", "busy-errno", "raw-evidence", "semantic-fields", "allocation-tokens", "current-metadata",
]
START = "struct functional_face_native_proc_birth {"
END = "struct functional_face_native_dmm_input {"


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def proc_birth_binary(tmp_path_factory, request):
    source_path = HERE / "menu-observe.c"
    source = source_path.read_text()
    start = source.index(START)
    end = source.index(END, start)
    primitive = source[start:end]
    metadata_start = source.index("static int functional_face_source_current_metadata(")
    metadata_end = source.index("struct functional_face_sdk_origin {", metadata_start)
    primitive += source[metadata_start:metadata_end]
    assert primitive.count("static void functional_face_native_birth_observe(") == 1
    assert primitive.count("static int functional_face_native_proc_read(") == 1
    assert primitive.count("static int functional_face_native_proc_same(") == 1
    fixture = (HERE / "test-functional-face-proc-birth.c").read_text()
    assert fixture.count("/* ACTUAL_PROC_BIRTH */") == 1
    assert (HERE / "functional-face-proc.c").is_file()
    work = tmp_path_factory.mktemp("functional-face-proc-birth")
    path, binary = work / "actual.c", work / "actual"
    path.write_text(fixture.replace("/* ACTUAL_PROC_BIRTH */", primitive))
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    if request.param:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command = [*shlex.split(os.environ.get("CC", "cc")), *flags, "-I", str(HERE),
               str(path), str(HERE / "functional-face-ap-observer.c"),
               str(HERE / "functional-face-proc.c"), "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary, hashlib.sha256(primitive.encode()).hexdigest()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_original_birth_proc_collector(proc_birth_binary, scenario):
    binary, source_digest = proc_birth_binary
    result = subprocess.run(
        [str(binary), scenario], capture_output=True, text=True, timeout=30,
        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                 UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"),
    )
    assert result.returncode == 0, (
        f"source_block_sha256={source_digest}\n" + result.stdout + result.stderr
    )
    assert f"PROC_BIRTH_HOSTTEST_PASS scenario={scenario}" in result.stdout
    assert "actual_observer=1 actual_parser=1 host_proc_reads=0" in result.stdout
    assert ("diagnostic_only=1 native_birth_complete=0 source_memory_ready=0 "
            "allocation_pin_verified=0 competing_readers_excluded=0 native_operations=0") in result.stdout
