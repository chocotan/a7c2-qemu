"""Joint host-only EE diagnostic checks; native cohort mocks prove no CP business state."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent / "device-models"
COMMON_CASES = """
    normal opaque default-off enabled-two unknown wrong-type other-destination short-header
    3003 preinit all-wrong-types all-bad-lengths missing-io missing-guard no-predecessors wrong-source reserve-refused
    lost-guard mutated-request requestfail reentrant inspect-reentrant reentrant-free fork-lock
    double-free
""".split()
REPLY_CASES = """
    allocfail null-allocation short-allocation long-allocation alias overlap overlap-before
    bad-reply-source bad-reply-copy allocation-error-pointer cleanupfail
    sendfail send-cleanupfail replyfail inline-free fast-free-reuse async-inflight async-success
    foreign wrong-waiter wrong-owner altered-wire altered-source altered-size cross-fault
""".split()


@pytest.fixture(scope="module")
def sanitized_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("ee-controls-diagnostic") / "ee-controls"
    command = [
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g", "-pthread",
        "-DNATIVE_CP_EE_CONTROLS_DIAGNOSTIC_TEST", "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer", "-no-pie", str(HERE / "cp-ee-controls-diagnostic.c"),
        str(HERE / "test-cp-ee-controls-diagnostic.c"), "-o", str(binary),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def run_case(binary, index, case):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    run = subprocess.run([str(binary), str(index), case], env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, f"opcode index={index} case={case}:\n{run.stdout}{run.stderr}"
    assert "oneway has no ACK; business/CP/EE/frame/capture remain0" in run.stdout


def test_joint_ee_controls_sanitized_matrix(sanitized_binary):
    # Fresh processes preserve the one-attempt lifecycle without reset/import.
    cases = [(index, case) for index in range(3) for case in COMMON_CASES]
    cases += [(index, case) for index in (0, 2) for case in REPLY_CASES]
    cases += [(0, case) for case in ("sequence", "sequence-inline", "sequence-thread")]
    cases += [(1, "order"), (2, "order"), (2, "order-after409d"), (1, "oneway-minimal-io")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = [pool.submit(run_case, sanitized_binary, index, case) for index, case in cases]
        failures = []
        for run in runs:
            try:
                run.result()
            except (AssertionError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
    assert not failures, "\n\n".join(failures)
    print(f"{len(cases)} C sanitizer scenarios passed jointly for409d/4072/3012;3003 unhandled")
