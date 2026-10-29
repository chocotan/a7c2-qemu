"""Actual-receive ticket adapter lab fixtures; parent runs after joined freeze.

The bounded backend double and malloc-backed recycled slots exercise transport
ownership only. They do not establish native OSAL delivery, CP state, or capture.
"""
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
SCENARIOS = (
    "stale-ticket", "address-reuse", "repeat-free", "foreign-thread",
    "duplicate-receive", "wrong-source", "wrong-size", "wrong-destination",
    "backend-reject", "backend-unhandled", "wire-reject", "free-fail",
    "backend-unowned-free", "free-wrong-destination", "unowned", "disabled", "uninitialized",
    "uninitialized-then-init", "fork-uninitialized", "fork-held-lock",
    "fork-before-capture", "ledger-bound", "legacy-first", "null-arguments", "errno",
    "ack-handoff", "ack-handoff-recycled", "ack-handoff-duplicate", "ack-handoff-wrong-free", "pending-ticket",
)


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_actual_receive_event_tickets(tmp_path, sanitized):
    binary = tmp_path / "functional-camera-events"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    built = subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-O1", "-g", *flags,
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread",
        str(HERE / "functional-camera-events.c"),
        str(HERE / "test-functional-camera-events.c"), "-o", str(binary),
    ], capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    for case in SCENARIOS:
        result = subprocess.run([str(binary), case], env=env, capture_output=True,
                                text=True, timeout=10)
        assert result.returncode == 0, f"case={case}\n{result.stdout}\n{result.stderr}"


def test_adapter_compiles_against_production_control(tmp_path):
    objects = []
    for source in (HERE / "functional-camera-events.c",
                   HERE / "device-models" / "functional-camera-control.c"):
        obj = tmp_path / f"{source.stem}.o"
        built = subprocess.run([
            "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread",
            "-c", str(source), "-o", str(obj),
        ], capture_output=True, text=True, timeout=20)
        assert built.returncode == 0, built.stdout + built.stderr
        objects.append(obj)
    linked = subprocess.run([
        "cc", "-r", *map(str, objects), "-o", str(tmp_path / "functional-events-owner.o"),
    ], capture_output=True, text=True, timeout=20)
    assert linked.returncode == 0, linked.stdout + linked.stderr
