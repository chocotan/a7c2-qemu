"""Strict and ASAN/UBSAN functional-control tests; no VM or capture evidence.

Building these fixtures does not initialize the production bridge or contact a
broker. The C matrix includes the real receive-event ticket adapter.
"""
import errno
import importlib.util
import json
from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
SCENARIOS = (
    "success", "start-3000", "inline-free", "receive-other-thread", "state-advanced",
    "disabled", "unrelated", "wrong-type", "wrong-destination", "mode0", "mode2",
    "unknown-mode", "mode-wide-value", "mode-before-start", "short-mode", "long-mode",
    "short-start", "long-start", "start-tail", "bad-source", "missing-callback", "missing-guard",
    "pending-start-ack", "missing-broker", "bridge-error", "checksum-error", "wrong-abi",
    "missing-cap", "unknown-cap", "zero-instance", "instance-metadata", "zero-generation",
    "wide-generation", "zero-width", "wide-width", "zero-height", "wide-height", "bad-fps",
    "bad-quality", "bad-aperture", "zero-iso", "zero-shutter", "bad-focus", "reserved-state",
    "no-render", "no-frame", "bad-counter", "model-busy", "model-streaming", "model-fault",
    "short-result", "long-result", "long-required", "token-state", "output-guard",
    "state-instance", "state-regression", "state-changed-same-generation",
    "state-counter-regression", "state-checksum-error", "alloc-start-fail", "alloc-mode-fail",
    "alloc-notice-fail", "alloc-dirty-failure", "alloc-short", "alloc-long",
    "alloc-alias-request", "alloc-alias-ack", "send-start-fail", "send-mode-fail",
    "send-notice-fail", "inline-send-fail", "request-free-fail", "ack-free-fail",
    "notice-free-fail", "bad-ack-tid", "bad-notice-tid", "free-before-receive",
    "receive-wrong-source", "receive-wrong-destination", "receive-wrong-length",
    "receive-metadata-source", "receive-metadata-size", "free-metadata-source", "free-metadata-size",
    "receive-wrong-pointer", "corrupt-before-receive", "corrupt-before-free", "corrupt-ack",
    "duplicate-receive", "fork-held-lock", "reentrant-dispatch", "reentrant-free",
    "guard-fail", "predecessor-fail", "predecessor-lost", "mutated-request", "strict-owner-unchanged",
    "repeat-unchanged", "repeat-generation", "repeat-busy-ack", "repeat-busy-notice",
    "repeat-free-inflight", "repeat-send-inflight", "repeat-foreign-ack",
    "repeat-backward-generation", "repeat-bridge-failure", "repeat-wrong-instance",
    "repeat-lost-capability", "repeat-lost-predecessor", "repeat-lost-source",
    "repeat-address-reuse", "repeat-post-send-failure", "repeat-events-adapter",
    "native-ack-handoff", "native-ack-after-send", "native-ack-address-reuse",
    "native-ack-receiver-free", "native-ack-duplicate", "native-ack-corrupt",
    "native-ack-wrong-source", "native-ack-wrong-size", "native-ack-free-fail", "native-ack-send-fail",
    "xsync-generation", "xsync-exposure", "xsync-zero-shutter-state", "xsync-same-generation-fps",
    "xsync-refuse-after-full-3", "xsync-refuse-after-full-61", "xsync-refuse-after-full-120",
) + tuple(f"xsync-fps-{fps}" for fps in range(122))

REPORT = HERE.parent.parent / "report" / "functional-camera-control"
SPEC = importlib.util.spec_from_file_location("verify_control_xsync", REPORT / "verify_xsync.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_functional_start_state_and_original_message_ownership(tmp_path, sanitized):
    source = HERE / "device-models"
    files = [source / name for name in (
        "test-functional-camera-control.c", "functional-camera-control.c",
        "cp-full-state-snapshot.c", "cp-state-snapshot.c", "cp-state-publication.c",
        "cp-start-state-data.c",
    )] + [HERE / "functional-camera-events.c"]
    binary = tmp_path / "functional-control"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-O1", "-g", *flags,
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread",
        *map(str, files), "-o", str(binary),
    ], capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    observations_by_case = {}
    for case in SCENARIOS:
        result = subprocess.run([str(binary), case], env=env, capture_output=True,
                                text=True, timeout=10)
        assert result.returncode == 0, f"case={case}\n{result.stdout}\n{result.stderr}"
        if case.startswith("xsync-"):
            observations = [json.loads(line) for line in result.stdout.splitlines()]
            assert observations, case
            observations_by_case[case] = observations
            for observation in observations:
                VERIFY.validate_fixture(observation)
            if case == "xsync-generation":
                assert [o["xsync_source_fps"] for o in observations] == [30, 25, 60]
            if case == "xsync-exposure":
                assert [o["xsync_word"] for o in observations] == [30, 30, 30]
            if case.startswith("xsync-fps-"):
                fps = int(case.removeprefix("xsync-fps-"))
                expected = 0 if fps in VERIFY.canonical_domain() else -errno.ENOTSUP if 1 <= fps <= 120 else -errno.ERANGE
                assert observations[0]["result"] == expected
    assert_xsync_negatives(observations_by_case["xsync-fps-30"][0])


def assert_xsync_negatives(actual):
    def rejected(changed):
        with pytest.raises(ValueError):
            VERIFY.validate_fixture(changed)

    for name in VERIFY.FIELDS:
        rejected({**actual, name: actual[name] + 1})
        rejected({**actual, name: True})
        rejected({**actual, "record": actual["record"].replace(name + "=", name + "_typo=")})
        changed = dict(actual)
        changed[name + "_typo"] = changed.pop(name)
        rejected(changed)
    for state_name in ("model_state", "probe_state"):
        for offset, width, value in ((0, 4, 2), (4, 4, 0), (8, 4, 0), (12, 4, 0),
                                     (16, 4, 0), (16, 4, 3), (16, 4, 61), (16, 4, 120),
                                     (16, 4, 121), (20, 4, 0), (24, 4, 401), (28, 4, 0),
                                     (32, 8, 0), (48, 8, 0), (56, 8, 0), (56, 8, 0x100000000),
                                     (64, 8, 0), (104, 4, 1), (108, 4, 1), (112, 8, 0), (120, 8, 1)):
            changed = bytearray.fromhex(actual[state_name])
            changed[offset:offset + width] = value.to_bytes(width, "little")
            rejected({**actual, state_name: changed.hex()})
        rejected({**actual, state_name: actual[state_name][:-2]})
    for offset in (0x664, 0x665, 0x666, 0x668, 0x66c, 0x670, 0x672, 0x673):
        wire = bytearray.fromhex(actual["wire"])
        wire[offset] ^= 1
        rejected({**actual, "wire": wire.hex()})
    rejected({**actual, "record": actual["record"][:-1]})
    rejected({**actual, "wire": actual["wire"][:-2]})
    rejected({**actual, "bridge_rc": -errno.EIO})
    rejected({**actual, "probe_rc": -errno.EIO})
    rejected({**actual, "xsync_source_generation": actual["xsync_source_generation"] - 1})


def test_xsync_original_table_exact_integer_clock_domain():
    app = HERE / "menu-root/usr/lib/appFw.so"
    checked = VERIFY.verify_source(app if app.exists() else None)
    assert checked["original_table_rows"] == 73
    assert not checked["physical_xsync_verified"] and not checked["flash_trigger_implemented"]
    _, _, tuples = VERIFY.original_table()
    for invalid in ((0, 0), (3, 1), (61, 1), (120, 1)):
        assert invalid not in tuples
    assert (30, 1) in tuples and (25, 1) in tuples and (60, 1) in tuples


def test_production_owner_requires_bridge_transport(tmp_path):
    source = HERE / "device-models" / "functional-camera-control.c"
    obj = tmp_path / "functional-control.o"
    built = subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread",
        "-c", str(source), "-o", str(obj),
    ], capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert " U fcam_bridge_call" in symbols.stdout
    assert "native_functional_camera_control_test_" not in symbols.stdout
