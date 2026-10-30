# SPDX-License-Identifier: MIT
"""Execute the production AP command with host ABI stubs and the real observer.

Only dladdr, prologue reads and syscall(178) are fake trust boundaries. These
checks do not execute appFw.so or establish a native allocation pin.
"""
import os
from pathlib import Path
import shlex
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
SCENARIOS = [
    "share", "open", "close", "free", "gates", "birth", "prior", "library",
    "prologue", "helper-error", "receipt", "raw-kernel-error",
    "birth-provenance", "lifetime-facts", "fork", "sequence-edge",
]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def native_command_binary(tmp_path_factory, request):
    source = (HERE / "menu-observe.c").read_text()
    start = source.index("struct functional_face_native_dmm_input {")
    end = source.index("static unsigned int record_osd_transport(", start)
    primitive = source[start:end]
    assert primitive.count("static int functional_face_native_ap_command(") == 1
    fixture = (HERE / "test-functional-face-native-command.c").read_text()
    assert fixture.count("/* ACTUAL_NATIVE_COMMAND */") == 1
    work = tmp_path_factory.mktemp("functional-face-native-command")
    path, binary = work / "actual.c", work / "actual"
    path.write_text(fixture.replace("/* ACTUAL_NATIVE_COMMAND */", primitive))
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    if request.param:
        # Keep real host function addresses above the original SDK offsets.
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-Wl,-Ttext-segment=0x10000000"]
    command = [*shlex.split(os.environ.get("CC", "cc")), *flags, "-I", str(HERE),
               str(path), str(HERE / "functional-face-ap-observer.c"), "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_native_command_abi_and_evidence(native_command_binary, scenario):
    result = subprocess.run(
        [str(native_command_binary), scenario], capture_output=True, text=True, timeout=20,
        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                 UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"NATIVE_COMMAND_HOSTTEST_PASS scenario={scenario}" in result.stdout
    assert "actual_observer=1 native_pin=0 capture_verified=0" in result.stdout
