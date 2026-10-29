"""Host-only 4000 diagnostic tests; unit guard stubs prove no native readiness."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent / "device-models"
CASES = """
    normal opaque-cookies default-off unrelated types header-byte1 lengths body-bits
    wrong-source missing-io missing-guard preinit reserve-refused predecessor-false
    allocfail null-allocation short-allocation long-allocation alias overlap overlap-before
    bad-reply-source bad-reply-copy allocation-error-pointer cleanupfail lost-guard
    mutated-request mutated-source initial-source-mutation sendfail send-cleanupfail
    requestfail replyfail foreign wrong-waiter wrong-owner altered-wire altered-source
    altered-size inline-free inline-sendfail-free fast-free-reuse async-sendfail async-success
    reentrant inspect-reentrant reentrant-free request-reentry fork-lock double-free
""".split()


@pytest.fixture(scope="module")
def sanitized_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("movie-format-diagnostic") / "movie-format"
    command = [
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g", "-pthread",
        "-DNATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_TEST", "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer", "-no-pie", str(HERE / "cp-movie-format-diagnostic.c"),
        str(HERE / "test-cp-movie-format-diagnostic.c"), "-o", str(binary),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def run_case(binary, case):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    run = subprocess.run([str(binary), case], env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, f"4000 case={case}:\n{run.stdout}{run.stderr}"
    assert "seven-field audit only; business/CP/EE/frame/capture remain0" in run.stdout


def test_joint_movie_format_sanitized_matrix(sanitized_binary):
    # Each process owns one immutable attempt; no reset/import/native-ready setter.
    with ThreadPoolExecutor(max_workers=6) as pool:
        runs = [pool.submit(run_case, sanitized_binary, case) for case in CASES]
        failures = []
        for run in runs:
            try:
                run.result()
            except (AssertionError, subprocess.TimeoutExpired) as error:
                failures.append(str(error))
    assert not failures, "\n\n".join(failures)
    print(f"{len(CASES)} C sanitizer scenarios passed jointly for exact20B4000; no native business claim")
