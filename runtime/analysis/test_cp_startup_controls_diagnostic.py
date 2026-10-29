"""Joint host-only startup transport matrix; mocked guards prove no CP business state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent / "device-models"
CASES = """
    normal opaque default-off enabled-two unknown wrong-type other-destination short-header
    preinit all-bad-lengths missing-io missing-guard no-predecessors wrong-source reserve-refused
    allocfail alloc-retry null-allocation short-allocation long-allocation alias overlap overlap-before
    bad-reply-source bad-reply-copy allocation-error-pointer lost-guard mutated-request cleanupfail
    sendfail send-cleanupfail requestfail replyfail inline-free fast-free-reuse reentrant
    inspect-reentrant reentrant-free async-inflight before-send-fault fork-lock foreign
    wrong-waiter wrong-owner altered-wire altered-source altered-size double-free cross-fault
""".split()


@pytest.fixture(scope="module")
def sanitized_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("startup-controls-diagnostic") / "startup-controls"
    command = [
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g", "-pthread",
        "-DNATIVE_CP_STARTUP_CONTROLS_DIAGNOSTIC_TEST", "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer", "-no-pie", str(HERE / "cp-startup-controls-diagnostic.c"),
        str(HERE / "test-cp-startup-controls-diagnostic.c"), "-o", str(binary),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def run_case(binary, index, case):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    run = subprocess.run([str(binary), str(index), case], env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, f"opcode index={index} case={case}:\n{run.stdout}{run.stderr}"
    assert "business/CP/EE/frame/capture remain0" in run.stdout


def test_joint_three_command_sanitized_matrix(sanitized_binary):
    # Each fresh process owns one finite lifetime; no reset or dropped replies.
    cases = [(index, case) for index in range(3) for case in CASES]
    cases += [(0, case) for case in ("sequence", "sequence-inline", "sequence-reverse")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = [pool.submit(run_case, sanitized_binary, index, case) for index, case in cases]
        failures = []
        for run in runs:
            try:
                run.result()
            except (AssertionError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
    assert not failures, "\n\n".join(failures)
    print(f"{len(cases)} C sanitizer scenarios passed jointly for4014/40c8/4057")
