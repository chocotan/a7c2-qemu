"""Lab IO/state/ownership checks only; no original AP, graph or capture claim.

Run after parent installs the four files into the native runtime tree. This
worker intentionally does not compile, import, collect, or execute this module.
"""
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / "device-models"
CASES = [
    "normal-three", "repeat", "dynamic-callers", "disabled-unrelated",
    "malformed-size", "malformed-header", "malformed-body", "source-boundary",
    "missing-io", "fork-before-mutex", "busy",
    "reserve-fail", "pred-first", "pred-second", "overflow", "allocation-error",
    "allocation-null", "allocation-short", "allocation-alias", "cleanup-fail",
    "set-source", "source-drift", "request-tamper", "reply-tamper", "state-readback",
    "send-fail", "request-free-fail", "receive-metadata", "receive-content", "receive-source-getter",
    "wrong-receiver-thread", "free-before-receive", "wrong-free-destination",
    "wrong-free-thread", "reply-free-fail", "duplicate", "inline-free",
    "inline-send-fail", "inline-free-fail", "release-reentry",
    "log-order", "log-reentry-new-generation", "reuse-after-retired",
    "live-alias-allocate", "retained-alias-allocate",
    "history-reserve-fail", "history-pred-fail", "history-allocation-fail",
    "history-multiple", "history-reallocate-one", "history-own-reallocate",
    "history-aliases", "history-inline-observation", "history-capacity",
    "history-fork-before-lock",
]


@pytest.fixture(scope="module", params=["normal", "sanitized"])
def bb_timecode_binary(tmp_path_factory, request):
    binary = tmp_path_factory.mktemp("bb-timecode-" + request.param) / "owner"
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g", "-O1", "-pthread"]
    if request.param == "sanitized":
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
    # Include-owner whitebox tests inject only quiescent counters/getter faults.
    built = subprocess.run(
        ["cc", *flags, str(MODEL / "test-bb-timecode-control.c"), "-o", str(binary)],
        capture_output=True, text=True, timeout=45,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("case", CASES)
def test_bb_timecode_control(bb_timecode_binary, case):
    result = subprocess.run(
        [str(bb_timecode_binary), case], capture_output=True, text=True, timeout=12,
        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                 UBSAN_OPTIONS="halt_on_error=1", LC_ALL="C"),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        f"BB_TIMECODE_LAB_CASE_PASS case={case} capture_verified=0 physical_verified=0"
    )
