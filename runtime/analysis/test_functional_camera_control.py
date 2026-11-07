"""Strict and ASAN/UBSAN functional-control tests; no VM or capture evidence.

Building these fixtures does not initialize the production bridge or contact a
broker. The C matrix includes the real receive-event ticket adapter.
"""
import errno
import importlib.util
import json
from pathlib import Path
import os
import shlex
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
        "cp-start-state-data.c", "cp-parameter-batch.c",
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


SELECTOR0_SCENARIOS = (
    "cold0", "strict", "before-mode1", "pending-mode1", "success", "notice-first",
    "wrong-owner", "wrong-source", "probe-failure", "pending-result", "same-generation",
    "unknown", "guard-failure", "predecessor-failure", "request-mutation",
    "selector-readback-failure", "epoch-overflow", "counter-overflow", "send-failure",
    "notice-free-failure",
)


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def selector0_real_core_binary(tmp_path_factory, request):
    from test_functional_background_integration import CORE_SOURCES

    native = HERE.parents[1]
    source = HERE / "device-models"
    files = [source / name for name in (
        "test-functional-camera-control.c", "cp-full-state-snapshot.c", "cp-state-snapshot.c",
        "cp-state-publication.c", "cp-start-state-data.c", "cp-parameter-batch.c",
    )] + [HERE / "functional-camera-events.c"]
    files += [native / "report" / name for name in CORE_SOURCES]
    files = list(dict.fromkeys(path.resolve() for path in files))
    binary = tmp_path_factory.mktemp("selector0-real-core-" + request.param) / "control"
    libraries = subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-DFCAM_SELECTOR0_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, *map(str, files), *shlex.split(libraries), "-lm", "-o", str(binary),
    ], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("scenario", SELECTOR0_SCENARIOS)
def test_selector0_real_state_full_snapshot_and_original_message_lifecycle(selector0_real_core_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    ran = subprocess.run([str(selector0_real_core_binary), scenario], env=env,
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, f"case={scenario}\n{ran.stdout}\n{ran.stderr}"
    assert not ran.stderr


PARAMETER_BANK_SCENARIOS = (
    "success", "oneway-only-io", "live-state22", "repeat", "repeat-same", "cookie-wrap", "opaque-headers",
    "cold", "disabled", "unrelated", "wrong-type", "wrong-source", "wrong-destination", "short", "long",
    "missing-release", "missing-guard", "pending-start", "before-mode1", "pending-ack",
    "pending-notice", "notice-before-zero-ack", "foreign-sender", "fork-held-lock",
    "guard-fail", "predecessor-fail", "predecessor-lost-before", "predecessor-lost-after",
    "before-error", "before-error-retry", "before-abi", "before-capabilities", "before-instance", "before-pending",
    "before-streaming", "before-generation-overflow", "before-overrun", "before-request-mutation",
    "before-source-mutation", "bank-error", "commit-error", "commit-error-reentry", "bank-positive-error",
    "bank-overrun", "result-short", "result-required", "result-token", "result-instance",
    "result-version", "result-size", "result-bank-generation", "result-before-generation", "result-generation",
    "result-input-fnv", "result-fps", "result-slots", "result-input-size", "result-reserved",
    "result-frame", "result-embedded-config", "result-cookie", "result-tail", "input-mutation",
    "origin-mutation", "bank-request-mutation", "after-error", "after-overrun", "after-instance",
    "after-generation", "after-fps", "after-counter", "transaction-overflow", "bank-generation-overflow",
    "reentrant-dispatch", "reentrant-free", "guard-release-reentry", "free-fail",
    "free-metadata-mutation", "free-wire-mutation", "fps-zero", "fps-wide",
) + tuple(f"bad-slot-{slot}" for slot in range(190))


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def parameter_bank_real_core_binary(tmp_path_factory, request):
    from test_functional_background_integration import CORE_SOURCES

    native = HERE.parents[1]
    source = HERE / "device-models"
    files = [source / name for name in (
        "test-functional-camera-control.c", "cp-full-state-snapshot.c", "cp-state-snapshot.c",
        "cp-state-publication.c", "cp-start-state-data.c", "cp-parameter-batch.c",
    )] + [native / "report" / name for name in CORE_SOURCES]
    files = list(dict.fromkeys(path.resolve() for path in files))
    binary = tmp_path_factory.mktemp("parameter-bank-real-core-" + request.param) / "control"
    libraries = subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-DFCAM_PARAMETER_BANK_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, *map(str, files), *shlex.split(libraries), "-lm", "-o", str(binary),
    ], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def _parameter_bank_records(stdout):
    events, chunks = {}, {}
    for line in stdout.splitlines():
        if line.startswith("FUNCTIONAL_CP_PARAMETER_BANK_EVENT "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            events.setdefault(int(fields["transaction"]), []).append(fields)
        elif line.startswith("FUNCTIONAL_CP_PARAMETER_BANK_BYTES "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            key = int(fields["transaction"]), fields["kind"]
            parts = chunks.setdefault(key, {})
            offset = int(fields["offset"])
            assert offset not in parts
            raw = bytes.fromhex(fields["raw"])
            assert len(raw) == int(fields["bytes"]) and 0 < len(raw) <= 128
            assert offset % 128 == 0
            parts[offset] = int(fields["total"]), raw
    blobs = {}
    for key, parts in chunks.items():
        blob = bytearray()
        for offset, (total, raw) in sorted(parts.items()):
            assert offset == len(blob) and total == parts[0][0]
            blob.extend(raw)
        assert len(blob) == parts[0][0]
        blobs[key] = bytes(blob)
    return events, blobs


@pytest.mark.parametrize("scenario", PARAMETER_BANK_SCENARIOS)
def test_post_initial_parameter_bank_full_content_real_core_and_oneway_ownership(parameter_bank_real_core_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    ran = subprocess.run([str(parameter_bank_real_core_binary), scenario], env=env,
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, f"case={scenario}\n{ran.stdout}\n{ran.stderr}"
    assert not ran.stderr
    events, blobs = _parameter_bank_records(ran.stdout)
    for transaction, records in events.items():
        for record in records:
            assert record["oneway"] == "1" and record["ACK_sent"] == record["notification_sent"] == "0"
            assert record["capture_verified"] == record["physical_ASIC_verified"] == record["original_CP"] == "0"
        if not any(record["event"] == "COMMIT" for record in records):
            continue
        commit = next(record for record in reversed(records) if record["event"] == "COMMIT")
        assert commit["faults"] == "0" and commit["verified"] == commit["request_freed"] == "1"
        raw = blobs[transaction, "request"]
        before, after = (blobs[transaction, name] for name in ("before_state", "after_state"))
        receipt = blobs[transaction, "receipt"]
        assert len(raw) == 2564 and len(before) == len(after) == 128 and len(receipt) == 2756
        assert raw[0] == 5 and raw[2:4] == bytes.fromhex("6340")
        assert receipt[:8] == (1).to_bytes(4, "little") + (2756).to_bytes(4, "little")
        assert receipt[192:] == raw and receipt[64:192] == after
        generation = int.from_bytes(before[56:64], "little")
        assert int.from_bytes(receipt[24:32], "little") == generation
        assert int.from_bytes(receipt[32:40], "little") == generation + 1
        assert int.from_bytes(receipt[16:24], "little") == int(commit["bank_generation"])
        fps = int.from_bytes(raw[0x86c:0x870], "little")
        expected = bytearray(before)
        expected[16:20] = fps.to_bytes(4, "little")
        expected[56:64] = (generation + 1).to_bytes(8, "little")
        assert after == expected
        digest = 14695981039346656037
        for value in raw:
            digest = ((digest ^ value) * 1099511628211) & ((1 << 64) - 1)
        assert int.from_bytes(receipt[40:48], "little") == digest == int(commit["native_fnv1a"], 16)
        assert int.from_bytes(raw[4:8], "little") == int(commit["cookie"], 16)
        if scenario == "live-state22":
            assert generation == 22


CRANK_CONTROL_SCENARIOS = (
    "success", "opaque-byte1", "cookie-zero", "cookie-max", "inline-free", "new-sender",
    "allocation-param-reuse", "completed-reuse", "completed-reply-reuse", "duplicate-bank", "repeat-new-bank",
    "reentrant-dispatch", "reentrant-metadata", "reentrant-free", "reentrant-request-early", "guard-release-reentry",
    "cold", "disabled", "wrong-type", "unrelated", "wrong-source", "wrong-destination", "short", "long",
    "mode1", "mode-wide", "missing-release", "missing-allocate", "missing-send", "missing-guard",
    "bank-retained", "bank-not-freed", "bank-fault", "bank-not-verified", "bank-wrong-instance",
    "bank-receipt-mutation", "current-mode-live", "transaction-overflow", "crank-generation-overflow",
    "fork-held-lock", "guard-fail", "predecessor-fail",
    "before-error", "before-error-retry", "before-overrun", "before-result-instance", "before-request-mutation",
    "before-generation-overflow", "model-error", "model-overrun", "model-positive", "model-origin-mutation",
    "model-input-mutation", "model-bank-change", "result-short", "result-required", "result-token", "result-instance",
    "after-error", "after-overrun", "after-result-token", "allocation-fail", "allocation-dirty-fail", "allocation-alias",
    "allocation-alias-offset", "allocation-short", "allocation-long", "reply-source-set", "send-fail", "inline-send-fail",
    "request-free-fail", "request-free-wire", "request-free-source", "request-free-size", "reply-free-fail", "reply-free-wire",
    "stale-receive", "stale-free", "foreign-pointer", "receive-wrong-source", "receive-wrong-size", "receive-wrong-destination",
    "receive-wire", "receive-metadata-source", "receive-metadata-size", "free-before-receive",
    "duplicate-receive", "foreign-free", "transport-receive-sender-free", "transport-receive-foreign-free",
    "transport-inline-receive", "transport-during-request-free",
) + tuple(f"predecessor-lost-{i}" for i in range(1, 7)) + tuple(
    f"{kind}-byte-{i}" for kind, count in (("receipt", 208), ("before", 128), ("after", 128), ("request", 12))
    for i in range(count)
)

CRANK_EVENT_FIELDS = tuple((
    "event pid tid transaction sender_tid receiver_tid source destination command bytes native_fnv1a cookie busy guard faults error "
    "before_rc model_rc after_rc model_called model_committed verified owned complete retained_request retained_reply request_pointer reply_pointer "
    "allocation_pointer request_releasing request_freed request_free_rc request_free_tid reply_releasing reply_inspecting reply_allocated reply_valid "
    "reply_alias allocate_rc send_started send_inflight send_rc ACK_sent reply_received receive_rc reply_freed reply_cleanup_freed reply_free_rc "
    "reply_free_tid reply_consumed requests commits verified_commits completions model_instance bank_generation crank_generation last_bank_generation "
    "last_crank_generation before_config_generation config_generation frame_generation mode fps bank_transaction bank_commits bank_released bank_source "
    "bank_destination bank_command bank_bytes bank_native_fnv1a receipt_fnv1a reply_fnv1a before_used before_required before_token before_instance "
    "crank_used crank_required crank_token crank_instance after_used after_required after_token after_instance policy functional_model original_CP "
    "physical_ASIC_verified EE frame capture capture_verified"
).split())
CRANK_BYTES_FIELDS = tuple((
    "event pid tid transaction kind total offset bytes raw native_fnv1a content_fnv1a model_instance bank_generation crank_generation "
    "functional_model original_CP physical_ASIC_verified capture_verified"
).split())


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def crank_control_real_core_binary(tmp_path_factory, request):
    from test_functional_background_integration import CORE_SOURCES

    native = HERE.parents[1]
    source = HERE / "device-models"
    files = [source / name for name in (
        "test-functional-camera-control.c", "cp-full-state-snapshot.c", "cp-state-snapshot.c",
        "cp-state-publication.c", "cp-start-state-data.c", "cp-parameter-batch.c", "cp-ee-controls-diagnostic.c",
    )] + [native / "report" / name for name in CORE_SOURCES]
    files = list(dict.fromkeys(path.resolve() for path in files))
    binary = tmp_path_factory.mktemp("crank-control-real-core-" + request.param) / "control"
    libraries = subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-DFCAM_CRANK_CONTROL_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, *map(str, files), *shlex.split(libraries), "-lm", "-o", str(binary),
    ], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def _crank_fnv(raw):
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def _crank_control_records(stdout):
    events, chunks, seals = {}, {}, {}
    for line in stdout.splitlines():
        if line.startswith("FUNCTIONAL_CP_CRANK_CONTROL_EVENT "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            assert tuple(fields) == CRANK_EVENT_FIELDS
            events.setdefault(int(fields["transaction"]), []).append(fields)
        elif line.startswith("FUNCTIONAL_CP_CRANK_CONTROL_BYTES "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            assert tuple(fields) == CRANK_BYTES_FIELDS
            key = int(fields["transaction"]), fields["kind"]
            parts = chunks.setdefault(key, {})
            offset, total, size = (int(fields[name]) for name in ("offset", "total", "bytes"))
            assert offset not in parts and offset % 128 == 0
            raw = bytes.fromhex(fields["raw"])
            assert len(raw) == size and 0 < size <= 128 and len(fields["raw"]) == size * 2
            assert total == {"request": 12, "before_state": 128, "receipt": 208, "after_state": 128, "reply": 12}[fields["kind"]]
            parts[offset] = total, raw
            seal = int(fields["content_fnv1a"], 16)
            assert key not in seals or seals[key] == seal
            seals[key] = seal
    blobs = {}
    for key, parts in chunks.items():
        blob = bytearray()
        for offset, (total, raw) in sorted(parts.items()):
            assert offset == len(blob) and total == parts[0][0]
            blob.extend(raw)
        assert len(blob) == parts[0][0] and _crank_fnv(blob) == seals[key]
        blobs[key] = bytes(blob)
    return events, blobs


@pytest.mark.parametrize("scenario", CRANK_CONTROL_SCENARIOS)
def test_post_bank_crank_mode0_real_core_full_readback_and_event_bound_lifecycle(crank_control_real_core_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    ran = subprocess.run([str(crank_control_real_core_binary), scenario], env=env,
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, f"case={scenario}\n{ran.stdout}\n{ran.stderr}"
    assert not ran.stderr
    events, blobs = _crank_control_records(ran.stdout)
    for transaction, records in events.items():
        for record in records:
            assert record["policy"] == "active-config-crank-mode0-v1"
            assert record["functional_model"] == "1"
            assert all(record[name] == "0" for name in ("original_CP", "physical_ASIC_verified", "EE", "frame", "capture", "capture_verified"))
            assert int(record["source"], 16) == 0x80020002 and int(record["destination"], 16) == 0x90030001
            assert int(record["command"], 16) == 0x409D and record["bytes"] == "12"
            assert int(record["bank_source"], 16) == 0x80020002 and int(record["bank_destination"], 16) == 0x90030001
            assert int(record["bank_command"], 16) == 0x4063 and record["bank_bytes"] == "2564"
            if record["model_committed"] == "1":
                assert record["model_rc"] == "0" and int(record["commits"]) > 0
            if record["ACK_sent"] == "1":
                assert record["verified"] == record["model_committed"] == "1"
        names = [record["event"] for record in records]
        assert names[0] == "BEGIN"
        if "VERIFIED" not in names:
            assert all(record["ACK_sent"] == "0" and record["owned"] == "0" for record in records)
            assert (transaction, "reply") not in blobs
            continue
        assert names.index("BEFORE") < names.index("MODEL") < names.index("AFTER") < names.index("VERIFIED") < names.index("REPLY")
        verified = next(record for record in records if record["event"] == "VERIFIED")
        raw, before, receipt, after, reply = (blobs[transaction, kind] for kind in ("request", "before_state", "receipt", "after_state", "reply"))
        assert raw[0] == 5 and raw[2:4] == bytes.fromhex("9d40") and raw[8:] == bytes(4)
        assert reply == bytes.fromhex("01009d40") + raw[4:8] + bytes.fromhex("00f00000")
        assert receipt[:8] == (1).to_bytes(4, "little") + (208).to_bytes(4, "little")
        assert receipt[64:192] == after and receipt[192:204] == raw and receipt[204:] == bytes(4)
        number = lambda offset: int.from_bytes(receipt[offset:offset+8], "little")
        assert number(8) == int(verified["model_instance"])
        assert number(16) == int(verified["crank_generation"])
        assert number(24) == int(verified["bank_generation"])
        generation = int.from_bytes(before[56:64], "little")
        assert number(32) == generation and number(40) == generation + 1
        assert number(48) == _crank_fnv(raw) == int(verified["native_fnv1a"], 16)
        assert receipt[56:60] == bytes(4) and receipt[60:64] == before[16:20]
        expected = bytearray(before)
        expected[56:64] = (generation+1).to_bytes(8, "little")
        assert after == expected
        assert all(verified[name] == "0" for name in ("before_rc", "model_rc", "after_rc"))
        assert int(verified["receipt_fnv1a"], 16) == _crank_fnv(receipt)
        for record in records:
            if record["complete"] != "1":
                continue
            assert record["faults"] == record["error"] == "0"
            assert all(record[name] == "1" for name in ("verified", "request_freed", "reply_received", "reply_freed", "reply_consumed", "ACK_sent"))
            assert int(record["receiver_tid"]) > 0
            assert record["sender_tid"] == record["request_free_tid"] == record["reply_free_tid"]
            if scenario.startswith("transport-"):
                assert record["receiver_tid"] != record["sender_tid"]
            assert record["reply_cleanup_freed"] == "0"


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_crank_completed_event_keeps_the_snapshot_captured_before_unlock(tmp_path, sanitized):
    source = (HERE / "device-models/functional-camera-control.c").read_text()
    def actual_function(marker):
        start = source.index(marker)
        return source[start:source.index("\n}", start) + 2]
    functions = "\n".join(actual_function(marker) for marker in (
        "static uint32_t u32(", "static uint64_t hash(", "static void crank_record("))
    fixture = tmp_path / "crank-event-snapshot.c"
    fixture.write_text('#include <assert.h>\n#include <stdio.h>\n#include <string.h>\n#include "' +
        str(HERE / "device-models/functional-camera-control.h") + '"\n' + r'''
static unsigned int snapshots;
static struct native_functional_camera_crank_snapshot current;
static long tid(void) { return 93; }
void native_functional_camera_crank_snapshot(struct native_functional_camera_crank_snapshot *out) {
    snapshots++; *out = current;
}
static void record(const char *tag, const char *text) { fputs(tag, stdout); puts(text); }
''' + functions + r'''
int main(void) {
    struct native_functional_camera_crank_snapshot captured = {
        .owner_pid = 71, .initialized = 1, .transaction = 11, .sender_tid = 43,
        .receiver_tid = 92, .model_instance = 29, .bank_generation = 3,
        .crank_generation = 2, .config_generation = 41
    };
    const unsigned char request[12] = {5, 7, 0x9d, 0x40, 0x60, 0, 0, 0x80};
    const unsigned char reply[12] = {1, 0, 0x9d, 0x40, 0x60, 0, 0, 0x80, 0, 0xf0};
    memcpy(captured.request, request, 12); memcpy(captured.reply, reply, 12);
    current = captured; current.transaction = 12; current.bank_generation = 4;
    current.crank_generation = 3; current.config_generation = 42; current.request[4] = 0x61;
    crank_record(record, "REPLY_FREE", "reply", &captured);
    assert(snapshots == 0);
    crank_record(record, "BEGIN", "request", NULL);
    assert(snapshots == 1);
    return 0;
}
''')
    binary = tmp_path / "crank-event-snapshot"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
               *flags, "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(fixture), "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=35)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    assert result.returncode == 0, result.stdout + result.stderr
    events, blobs = _crank_control_records(result.stdout)
    assert set(events) == {11, 12}
    previous, following = events[11][0], events[12][0]
    assert (previous["event"], previous["bank_generation"], previous["crank_generation"], previous["config_generation"]) == (
        "REPLY_FREE", "3", "2", "41")
    assert (following["event"], following["bank_generation"], following["crank_generation"], following["config_generation"]) == (
        "BEGIN", "4", "3", "42")
    assert previous["sender_tid"] == following["sender_tid"] == "43"
    assert previous["receiver_tid"] == "92" and previous["tid"] == "93"
    assert previous["cookie"] == "0x80000060" and following["cookie"] == "0x80000061"
    assert blobs[11, "reply"] == bytes.fromhex("01009d406000008000f00000")
    assert blobs[12, "request"] == bytes.fromhex("05079d406100008000000000")


MOVIE_FORMAT_SCENARIOS = tuple(
    case for case in CRANK_CONTROL_SCENARIOS if case != "crank-generation-overflow"
) + (
    "opaque-byte11", "opaque-byte19", "opaque-all", "context-instance", "context-bank", "context-crank",
    "context-mutation", "missing-context", "missing-source", "missing-set-source", "missing-record", "movie-generation-overflow",
    "crank-stale-reserved", "crank-retirement-lost-reserved",
    "crank-retained", "crank-fault", "crank-unreceived", "crank-unfreed", "crank-foreign-free",
    "crank-receipt-mutation", "crank-lineage", "model-crank-change", "allocation-alias-tail",
    "allocation-alias-owner", "allocation-alias-crank", "post-c0-badproof", "live-config-newer",
) + tuple(f"selector-byte-{i}" for i in range(8, 19) if i != 11) + tuple(
    f"receipt-byte-{i}" for i in range(208, 240)
) + tuple(f"request-byte-{i}" for i in range(12, 20))

MOVIE_FORMAT_EVENT_FIELDS = tuple((
    "event pid tid transaction sender_tid receiver_tid source destination command bytes native_fnv1a cookie busy guard faults error "
    "before_rc model_rc after_rc validation_rc model_called model_committed verified owned complete retained_request retained_reply request_pointer reply_pointer "
    "allocation_pointer request_releasing request_freed request_free_rc request_free_tid reply_releasing reply_inspecting reply_allocated reply_valid "
    "reply_alias allocate_rc send_started send_inflight send_rc ACK_sent reply_received receive_rc reply_freed reply_cleanup_freed reply_free_rc "
    "reply_free_tid reply_consumed requests commits verified_commits completions model_instance bank_generation crank_generation movie_generation last_bank_generation "
    "last_crank_generation last_movie_generation before_config_generation config_generation frame_generation software_format software_rate_index fps software_codec "
    "bank_transaction bank_commits bank_released bank_source bank_destination bank_command bank_bytes bank_native_fnv1a "
    "crank_transaction crank_completions crank_source crank_destination crank_command crank_bytes crank_native_fnv1a "
    "receipt_fnv1a reply_fnv1a before_used before_required before_token before_instance movie_used movie_required movie_token movie_instance "
    "after_used after_required after_token after_instance policy functional_model original_CP physical_ASIC_verified EE frame capture capture_verified"
).split())
MOVIE_FORMAT_BYTES_FIELDS = tuple((
    "event pid tid transaction kind total offset bytes raw native_fnv1a content_fnv1a model_instance bank_generation crank_generation movie_generation "
    "functional_model original_CP physical_ASIC_verified capture_verified"
).split())


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def movie_format_real_core_binary(tmp_path_factory, request):
    from test_functional_background_integration import CORE_SOURCES

    native = HERE.parents[1]
    source = HERE / "device-models"
    files = [source / name for name in (
        "test-functional-camera-control.c", "cp-full-state-snapshot.c", "cp-state-snapshot.c",
        "cp-state-publication.c", "cp-start-state-data.c", "cp-parameter-batch.c", "cp-ee-controls-diagnostic.c",
        "cp-movie-format-diagnostic.c",
    )] + [native / "report" / name for name in CORE_SOURCES]
    files = list(dict.fromkeys(path.resolve() for path in files))
    binary = tmp_path_factory.mktemp("movie-format-real-core-" + request.param) / "control"
    libraries = subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-DFCAM_MOVIE_FORMAT_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, *map(str, files), *shlex.split(libraries), "-lm", "-o", str(binary),
    ], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def _movie_format_records(stdout):
    events, chunks, seals = {}, {}, {}
    for line in stdout.splitlines():
        if line.startswith("FUNCTIONAL_CP_MOVIE_FORMAT_EVENT "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            assert tuple(fields) == MOVIE_FORMAT_EVENT_FIELDS
            events.setdefault(int(fields["transaction"]), []).append(fields)
        elif line.startswith("FUNCTIONAL_CP_MOVIE_FORMAT_BYTES "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            assert tuple(fields) == MOVIE_FORMAT_BYTES_FIELDS
            key = int(fields["transaction"]), fields["kind"]
            parts = chunks.setdefault(key, {})
            offset, total, size = (int(fields[name]) for name in ("offset", "total", "bytes"))
            assert offset not in parts and offset % 128 == 0
            raw = bytes.fromhex(fields["raw"])
            assert len(raw) == size and 0 < size <= 128 and len(fields["raw"]) == size * 2
            assert total == {"request": 20, "before_state": 128, "receipt": 240, "after_state": 128, "reply": 12}[fields["kind"]]
            parts[offset] = total, raw
            seal = int(fields["content_fnv1a"], 16)
            assert key not in seals or seals[key] == seal
            seals[key] = seal
    blobs = {}
    for key, parts in chunks.items():
        blob = bytearray()
        for offset, (total, raw) in sorted(parts.items()):
            assert offset == len(blob) and total == parts[0][0]
            blob.extend(raw)
        assert len(blob) == parts[0][0] and _crank_fnv(blob) == seals[key]
        blobs[key] = bytes(blob)
    return events, blobs


@pytest.mark.parametrize("scenario", MOVIE_FORMAT_SCENARIOS)
def test_post_crank_movie_format_full240_readback_and_event_bound_lifecycle(movie_format_real_core_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    ran = subprocess.run([str(movie_format_real_core_binary), scenario], env=env,
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, f"case={scenario}\n{ran.stdout}\n{ran.stderr}"
    assert not ran.stderr
    events, blobs = _movie_format_records(ran.stdout)
    for transaction, records in events.items():
        for record in records:
            assert record["policy"] == "active-config-movie-format5-rate1-0-v1" and record["functional_model"] == "1"
            assert all(record[name] == "0" for name in ("original_CP", "physical_ASIC_verified", "EE", "frame", "capture", "capture_verified"))
            assert int(record["source"], 16) == 0x80020002 and int(record["destination"], 16) == 0x90030001
            assert int(record["command"], 16) == 0x4000 and record["bytes"] == "20"
            assert int(record["bank_source"], 16) == int(record["crank_source"], 16) == 0x80020002
            assert int(record["bank_destination"], 16) == int(record["crank_destination"], 16) == 0x90030001
            assert int(record["bank_command"], 16) == 0x4063 and record["bank_bytes"] == "2564"
            assert int(record["crank_command"], 16) == 0x409D and record["crank_bytes"] == "12"
            if record["model_committed"] == "1":
                assert record["model_rc"] == "0" and int(record["commits"]) > 0
            if record["ACK_sent"] == "1":
                assert record["verified"] == record["model_committed"] == "1"
        names = [record["event"] for record in records]
        assert names[0] == "BEGIN"
        if "VERIFIED" not in names:
            assert all(record["ACK_sent"] == "0" and record["owned"] == "0" for record in records)
            assert (transaction, "reply") not in blobs
            continue
        assert names.index("BEFORE") < names.index("MODEL") < names.index("AFTER") < names.index("VERIFIED") < names.index("REPLY")
        verified = next(record for record in records if record["event"] == "VERIFIED")
        raw, before, receipt, after, reply = (blobs[transaction, kind] for kind in ("request", "before_state", "receipt", "after_state", "reply"))
        assert raw[0] == 5 and raw[2:4] == bytes.fromhex("0040")
        assert raw[8:11] == bytes.fromhex("050100") and raw[12:19] == bytes.fromhex("00000000000001")
        assert reply == bytes.fromhex("01000040") + raw[4:8] + bytes.fromhex("00f00000")
        assert receipt[:8] == (1).to_bytes(4, "little") + (240).to_bytes(4, "little")
        assert receipt[80:208] == after and receipt[208:228] == raw and receipt[228:] == bytes(12)
        number = lambda offset: int.from_bytes(receipt[offset:offset+8], "little")
        assert number(8) == int(verified["model_instance"])
        assert number(16) == int(verified["movie_generation"])
        assert number(24) == int(verified["bank_generation"]) and number(32) == int(verified["crank_generation"])
        generation = int.from_bytes(before[56:64], "little")
        assert number(40) == generation and number(48) == generation + 1
        assert number(56) == _crank_fnv(raw) == int(verified["native_fnv1a"], 16)
        assert receipt[64:72] == bytes.fromhex("0500000000000000")
        assert receipt[72:76] == before[16:20] and receipt[76:80] == (1).to_bytes(4, "little")
        expected = bytearray(before)
        expected[56:64] = (generation+1).to_bytes(8, "little")
        assert after == expected
        assert all(verified[name] == "0" for name in ("before_rc", "model_rc", "after_rc", "validation_rc"))
        assert int(verified["receipt_fnv1a"], 16) == _crank_fnv(receipt)
        for record in records:
            if record["complete"] != "1":
                continue
            assert record["faults"] == record["error"] == "0"
            assert all(record[name] == "1" for name in ("verified", "request_freed", "reply_received", "reply_freed", "reply_consumed", "ACK_sent"))
            assert int(record["receiver_tid"]) > 0 and record["sender_tid"] == record["request_free_tid"] == record["reply_free_tid"]
            assert "RECEIVE" in names and "SENT" in names and "REQUEST_FREE" in names and "REPLY_FREE" in names
            if scenario.startswith("transport-"):
                assert record["receiver_tid"] != record["sender_tid"]
            assert record["reply_cleanup_freed"] == "0"


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_movie_format_event_uses_only_immutable_snapshot_captured_before_unlock(tmp_path, sanitized):
    source = (HERE / "device-models/functional-camera-control.c").read_text()
    def actual_function(marker):
        start = source.index(marker)
        return source[start:source.index("\n}", start) + 2]
    functions = "\n".join(actual_function(marker) for marker in (
        "static uint32_t u32(", "static uint64_t hash(", "static void movie_format_record("))
    fixture = tmp_path / "movie-event-snapshot.c"
    fixture.write_text('#include <assert.h>\n#include <stdio.h>\n#include <string.h>\n#include "' +
        str(HERE / "device-models/functional-camera-control.h") + '"\n' + r'''
static long tid(void) { return 93; }
static void record(const char *tag, const char *text) { fputs(tag, stdout); puts(text); }
''' + functions + r'''
int main(void) {
    struct native_functional_camera_movie_format_snapshot captured = {
        .owner_pid = 71, .initialized = 1, .transaction = 11, .sender_tid = 43,
        .receiver_tid = 92, .model_instance = 29, .bank_generation = 3,
        .crank_generation = 2, .movie_generation = 1, .config_generation = 41
    };
    const unsigned char request[20] = {5, 7, 0, 0x40, 0x60, 0, 0, 0x80, 5, 1, 0, 9, 0, 0, 0, 0, 0, 0, 1, 8};
    const unsigned char reply[12] = {1, 0, 0, 0x40, 0x60, 0, 0, 0x80, 0, 0xf0};
    memcpy(captured.request, request, 20); memcpy(captured.reply, reply, 12);
    struct native_functional_camera_movie_format_snapshot next = captured;
    next.transaction = 12; next.bank_generation = 4; next.crank_generation = 3;
    next.movie_generation = 2; next.config_generation = 42; next.request[4] = 0x61;
    movie_format_record(record, "REPLY_FREE", "reply", &captured);
    movie_format_record(record, "BEGIN", "request", &next);
    return 0;
}
''')
    binary = tmp_path / "movie-event-snapshot"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    built = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
        *flags, "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(fixture), "-o", str(binary)],
        capture_output=True, text=True, timeout=35)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    assert result.returncode == 0, result.stdout + result.stderr
    events, blobs = _movie_format_records(result.stdout)
    assert set(events) == {11, 12}
    previous, following = events[11][0], events[12][0]
    assert (previous["event"], previous["bank_generation"], previous["crank_generation"], previous["movie_generation"], previous["config_generation"]) == (
        "REPLY_FREE", "3", "2", "1", "41")
    assert (following["event"], following["bank_generation"], following["crank_generation"], following["movie_generation"], following["config_generation"]) == (
        "BEGIN", "4", "3", "2", "42")
    assert previous["sender_tid"] == following["sender_tid"] == "43" and previous["receiver_tid"] == "92" and previous["tid"] == "93"
    assert blobs[11, "reply"] == bytes.fromhex("010000406000008000f00000")
    assert blobs[12, "request"] == bytes.fromhex("0507004061000080050100090000000000000108")


OU_CRANK_CONTROL_SCENARIOS = (
    "success", "oneway-only-io", "opaque-byte1", "cookie-zero", "cookie-max", "context-mutation",
    "duplicate-tuple", "repeat-new-tuple", "completed-reuse", "cold", "disabled", "wrong-type", "unrelated",
    "wrong-source", "wrong-destination", "short", "long", "missing-source", "missing-size", "missing-release",
    "missing-record", "missing-context", "missing-guard", "context-instance", "context-bank", "context-crank", "context-movie",
    "bank-unfreed", "bank-seal", "crank-unreceived", "crank-unfreed", "crank-foreign-free", "crank-seal",
    "movie-unreceived", "movie-unfreed", "movie-foreign-free", "movie-seal", "movie-lineage", "current-mode-live",
    "bank-drift-reserved", "crank-drift-reserved", "movie-drift-reserved", "startup-live-reserved",
    "startup-live", "startup-unreceived", "startup-request-unfreed", "startup-foreign-free", "startup-fault",
    "startup-seal", "startup-result", "startup-config-seal", "startup-generation", "startup-command", "stale-live-config",
    "transaction-overflow", "counter-overflow", "ou-generation-overflow", "fork-held-lock", "guard-fail", "predecessor-fail",
    "before-error", "before-overrun", "before-generation-overflow", "model-error", "model-positive", "model-overrun",
    "model-origin", "model-input", "model-native-drift", "result-used", "result-required", "result-token", "result-instance",
    "c0-bad-receipt", "c0-posterror-retained", "after-error", "after-overrun", "post-verified-wire", "free-fail", "free-positive", "foreign-free",
    "reentrant-metadata", "reentrant-logger", "reentrant-bridge", "reentrant-free", "reentrant-early-free", "guard-release-reentry",
) + tuple(f"body-byte-{i}" for i in range(8, 12)) + tuple(f"alias-{i}" for i in range(5)) + tuple(
    f"predecessor-lost-{i}" for i in range(1, 5)
) + tuple(f"{kind}-byte-{i}" for kind, count in (("receipt", 224), ("before", 128), ("after", 128), ("request", 12)) for i in range(count))

OU_CRANK_EVENT_FIELDS = tuple((
    "event pid tid transaction sender_tid source destination command bytes native_fnv1a cookie busy guard guard_fault faults error "
    "before_rc model_rc after_rc validation_rc model_called model_committed verified owned complete retained_request request_pointer "
    "releasing request_freed free_rc free_tid requests commits verified_commits completions released model_instance bank_generation "
    "crank_generation movie_generation ou_generation last_bank_generation last_crank_generation last_movie_generation last_ou_generation "
    "before_config_generation config_generation frame_generation mode fps bank_transaction bank_commits bank_released bank_source bank_destination "
    "bank_command bank_bytes bank_native_fnv1a crank_transaction crank_completions crank_source crank_destination crank_command crank_bytes crank_native_fnv1a "
    "movie_transaction movie_completions movie_source movie_destination movie_command movie_bytes movie_native_fnv1a startup_cycle startup_completed_cycles "
    "startup_config_generation startup_frame_generation startup_lease_generation startup_result_fnv1a startup_config40_fnv1a startup_source startup_destination "
    "startup_command startup_bytes startup_native_fnv1a receipt_fnv1a before_used before_required before_token before_instance ou_used ou_required ou_token "
    "ou_instance after_used after_required after_token after_instance resource policy oneway ACK_sent notification_sent functional_model original_CP "
    "physical_ASIC_verified EE frame capture capture_verified"
).split())
OU_CRANK_BYTES_FIELDS = tuple((
    "event pid tid transaction kind total offset bytes raw native_fnv1a content_fnv1a model_instance bank_generation crank_generation movie_generation "
    "ou_generation functional_model original_CP physical_ASIC_verified capture_verified"
).split())


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def ou_crank_control_real_core_binary(tmp_path_factory, request):
    from test_functional_background_integration import CORE_SOURCES

    native = HERE.parents[1]
    source = HERE / "device-models"
    files = [source / name for name in (
        "test-functional-camera-control.c", "cp-full-state-snapshot.c", "cp-state-snapshot.c",
        "cp-state-publication.c", "cp-start-state-data.c", "cp-parameter-batch.c", "cp-ee-controls-diagnostic.c",
        "functional-startup-control.c",
    )] + [native / "report" / name for name in CORE_SOURCES]
    files = list(dict.fromkeys(path.resolve() for path in files))
    binary = tmp_path_factory.mktemp("ou-crank-control-real-core-" + request.param) / "control"
    libraries = subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-DFCAM_OU_CRANK_CONTROL_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, *map(str, files), "-Wl,--wrap=functional_startup_control_snapshot",
        *shlex.split(libraries), "-lm", "-o", str(binary),
    ], capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def _ou_crank_control_records(stdout):
    events, chunks, seals = {}, {}, {}
    for line in stdout.splitlines():
        if line.startswith("FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            assert tuple(fields) == OU_CRANK_EVENT_FIELDS
            events.setdefault(int(fields["transaction"]), []).append(fields)
        elif line.startswith("FUNCTIONAL_CP_OU_CRANK_CONTROL_BYTES "):
            fields = dict(part.split("=", 1) for part in line.split()[1:])
            assert tuple(fields) == OU_CRANK_BYTES_FIELDS
            key = int(fields["transaction"]), fields["kind"]
            parts = chunks.setdefault(key, {})
            offset, total, size = (int(fields[name]) for name in ("offset", "total", "bytes"))
            assert offset not in parts and offset % 128 == 0
            raw = bytes.fromhex(fields["raw"])
            assert len(raw) == size and 0 < size <= 128 and len(fields["raw"]) == size * 2
            assert total == {"request": 12, "before_state": 128, "receipt": 224, "after_state": 128}[fields["kind"]]
            parts[offset] = total, raw
            seal = int(fields["content_fnv1a"], 16)
            assert key not in seals or seals[key] == seal
            seals[key] = seal
    blobs = {}
    for key, parts in chunks.items():
        blob = bytearray()
        for offset, (total, raw) in sorted(parts.items()):
            assert offset == len(blob) and total == parts[0][0]
            blob.extend(raw)
        assert len(blob) == parts[0][0] and _crank_fnv(blob) == seals[key]
        blobs[key] = bytes(blob)
    return events, blobs


@pytest.mark.parametrize("scenario", OU_CRANK_CONTROL_SCENARIOS)
def test_late_ou_crank_oneway_full224_current_tuple_and_original_request_free(ou_crank_control_real_core_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    ran = subprocess.run([str(ou_crank_control_real_core_binary), scenario], env=env,
                         capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, f"case={scenario}\n{ran.stdout}\n{ran.stderr}"
    assert not ran.stderr
    events, blobs = _ou_crank_control_records(ran.stdout)
    for transaction, records in events.items():
        for record in records:
            assert record["policy"] == "active-config-ou-crank-mode0-v1" and record["resource"] == "36"
            assert record["functional_model"] == record["oneway"] == "1"
            assert all(record[name] == "0" for name in (
                "ACK_sent", "notification_sent", "original_CP", "physical_ASIC_verified", "EE", "frame", "capture", "capture_verified"))
            assert not any(name.startswith("reply_") for name in record)
            assert int(record["source"], 16) == 0x80020002 and int(record["destination"], 16) == 0x90030001
            assert int(record["command"], 16) == 0x4072 and record["bytes"] == "12"
            assert int(record["bank_command"], 16) == 0x4063 and record["bank_bytes"] == "2564"
            assert int(record["crank_command"], 16) == 0x409D and record["crank_bytes"] == "12"
            assert int(record["movie_command"], 16) == 0x4000 and record["movie_bytes"] == "20"
            assert int(record["startup_command"], 16) == 0x4057 and record["startup_bytes"] == "12"
            if record["model_committed"] == "1":
                assert record["model_rc"] == "0" and int(record["commits"]) > 0
        names = [record["event"] for record in records]
        assert names[0] == "BEGIN"
        if "VERIFIED" not in names:
            assert all(record["owned"] == record["request_freed"] == "0" for record in records)
            continue
        assert names.index("BEFORE") < names.index("MODEL") < names.index("AFTER") < names.index("VERIFIED")
        verified = next(record for record in records if record["event"] == "VERIFIED")
        raw, before, receipt, after = (blobs[transaction, kind] for kind in ("request", "before_state", "receipt", "after_state"))
        assert raw[0] == 5 and raw[2:4] == bytes.fromhex("7240") and raw[8:] == bytes(4)
        assert receipt[:8] == (1).to_bytes(4, "little") + (224).to_bytes(4, "little")
        assert receipt[80:208] == after and receipt[208:220] == raw and receipt[220:] == bytes(4)
        number = lambda offset: int.from_bytes(receipt[offset:offset+8], "little")
        assert number(8) == int(verified["model_instance"]) and number(16) == int(verified["ou_generation"])
        assert all(number(offset) == int(verified[field]) for offset, field in ((24, "bank_generation"), (32, "crank_generation"), (40, "movie_generation")))
        generation = int.from_bytes(before[56:64], "little")
        assert number(48) == generation == int(verified["startup_config_generation"]) and number(56) == generation+1
        assert int.from_bytes(before[112:120], "little") == int(verified["startup_frame_generation"])
        assert number(64) == _crank_fnv(raw) == int(verified["native_fnv1a"], 16)
        assert receipt[72:76] == bytes(4) and receipt[76:80] == before[16:20]
        assert int.from_bytes(raw[4:8], "little") == int(verified["cookie"], 16)
        expected = bytearray(before); expected[56:64] = (generation+1).to_bytes(8, "little")
        assert after == expected and int(verified["receipt_fnv1a"], 16) == _crank_fnv(receipt)
        assert all(verified[name] == "0" for name in ("before_rc", "model_rc", "after_rc", "validation_rc"))
        for record in records:
            if record["complete"] != "1":
                continue
            assert record["faults"] == record["error"] == record["guard_fault"] == "0"
            assert record["busy"] == record["guard"] == record["releasing"] == record["free_rc"] == "0"
            assert record["request_freed"] == record["verified"] == record["model_committed"] == "1"
            assert record["sender_tid"] == record["free_tid"] and int(record["free_tid"]) > 0
            assert record["requests"] == record["commits"] == record["verified_commits"] == record["completions"] == record["released"]
            assert record["retained_request"] == "(nil)" and "REQUEST_FREE" in names


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_ou_crank_event_keeps_the_immutable_snapshot_captured_before_unlock(tmp_path, sanitized):
    source = (HERE / "device-models/functional-camera-control.c").read_text()
    def actual_function(marker):
        start = source.index(marker)
        return source[start:source.index("\n}", start) + 2]
    functions = "\n".join(actual_function(marker) for marker in (
        "static uint32_t u32(", "static uint64_t hash(", "static void ou_crank_record("))
    fixture = tmp_path / "ou-event-snapshot.c"
    fixture.write_text('#include <assert.h>\n#include <stdio.h>\n#include <string.h>\n#include "' +
        str(HERE / "device-models/functional-camera-control.h") + '"\n' + r'''
static long tid(void) { return 93; }
static void record(const char *tag, const char *text) { fputs(tag, stdout); puts(text); }
void native_functional_camera_ou_crank_snapshot(struct native_functional_camera_ou_crank_snapshot *out) {
    (void)out; assert(0); /* Formatting may not fetch a later transaction. */
}
''' + functions + r'''
int main(void) {
    struct native_functional_camera_ou_crank_snapshot captured = {
        .owner_pid = 71, .initialized = 1, .transaction = 11, .sender_tid = 43,
        .free_tid = 43, .model_instance = 29, .bank_generation = 3,
        .crank_generation = 2, .movie_generation = 1, .ou_generation = 1, .config_generation = 41
    };
    const unsigned char original[12] = {5, 7, 0x72, 0x40, 0x60, 0, 0, 0x80};
    memcpy(captured.request, original, 12);
    struct native_functional_camera_ou_crank_snapshot next = captured;
    next.transaction = 12; next.bank_generation = 4; next.crank_generation = 3;
    next.movie_generation = 2; next.ou_generation = 2; next.config_generation = 42; next.request[4] = 0x61;
    ou_crank_record(record, "REQUEST_FREE", "request", &captured);
    ou_crank_record(record, "BEGIN", "request", &next);
    return 0;
}
''')
    binary = tmp_path / "ou-event-snapshot"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    built = subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
        *flags, "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(fixture), "-o", str(binary)],
        capture_output=True, text=True, timeout=35)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    assert result.returncode == 0, result.stdout + result.stderr
    events, blobs = _ou_crank_control_records(result.stdout)
    assert set(events) == {11, 12}
    previous, following = events[11][0], events[12][0]
    assert (previous["event"], previous["bank_generation"], previous["crank_generation"], previous["movie_generation"], previous["ou_generation"], previous["config_generation"]) == (
        "REQUEST_FREE", "3", "2", "1", "1", "41")
    assert (following["event"], following["bank_generation"], following["crank_generation"], following["movie_generation"], following["ou_generation"], following["config_generation"]) == (
        "BEGIN", "4", "3", "2", "2", "42")
    assert previous["sender_tid"] == previous["free_tid"] == "43" and previous["tid"] == "93"
    assert blobs[11, "request"] == bytes.fromhex("050772406000008000000000")
    assert blobs[12, "request"] == bytes.fromhex("050772406100008000000000")


