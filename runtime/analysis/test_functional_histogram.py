"""Histogram owner component fixtures only; no core, VM, native AP or capture proof."""
from pathlib import Path
import hashlib
import json
import os
import copy
import runpy
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / "report" / "functional-histogram"
# Route bytes3,5..12 remain opaque, exactly as in the existing VDF ABI.
OPAQUE_ROUTE = {131, *range(133, 141)}
RESULT_BYTES = tuple(i for i in range(168) if i not in OPAQUE_ROUTE and i not in range(32, 40))
SCENARIOS = (
    "success", "bins-last-byte", "request-address-reuse", "foreign-retired-reuse", "inline",
    "inline-send-fail", "inline-notify-send-fail", "reentrant-dispatch", "reentrant-free",
    "bind-before-init", "uninitialized", "unbound", "fork-held-lock", "disabled", "enabled-two",
    "unrelated", "wrong-command", "wrong-kind", "wrong-destination", "null-request", "null-io",
    "null-result", "short-header", "short-request", "long-request", "legacy-mode0-0x800", "mode0",
    "disable-request", "wrong-source", "source-Q", "missing-guard", "missing-callback", "null-guard",
    "guard-fail", "guard-positive", "guard-miss", "guard-lost", "bridge-error", "bridge-positive",
    "mutated-input", "mutated-request", "mutated-source", "mutated-size", "result-short", "result-long",
    "result-required", "result-instance", "result-zero-instance", "result-token", "result-zero-hashes",
    "result-zero-lease", "result-config-overflow", "result-frame-overflow", "result-config-zero", "result-canary",
    "result-alias-request", "result-alias-io", "result-alias-guard", "result-alias-state",
    "alloc-live-alias", "alloc-interior-alias", "alloc-state-alias", "alloc-constant-alias", "alloc-io-alias",
    "alloc-guard-alias", "alloc-result-alias", "probing-output-alias", "alloc-wrap", "request-free-fail", "ack-send-fail", "notify-send-fail",
    "ack-source-fail", "notify-source-fail", "ack-copy-corrupt", "notify-copy-corrupt", "ack-free-fail",
    "notify-free-fail", "no-receive", "free-before-receive", "receive-only", "no-ticket", "wrong-ticket",
    "duplicate-receive", "foreign-ack-free", "ack-only", "wrong-notify-free-thread", "bind-busy",
    "receive-null-ticket", "receive-alias-ticket", "snapshot-alias", "free-result-alias", "unknown-pointer",
    "no-second-sample", "duplicate-owned-dispatch", "free-null-callback",
) + tuple(f"request-byte-{i}" for i in range(4, 12)) + tuple(
    f"result-byte-{i}" for i in RESULT_BYTES
) + tuple(f"bins-{condition}-{c}" for condition in ("zero", "no-peak") for c in range(4)) + tuple(
    f"{role}-alloc-{condition}"
    for role in ("ack", "notify") for condition in ("fail", "dirty-fail", "short", "long")
) + tuple(
    f"receive-{role}-{condition}" for role in ("ack", "notify")
    for condition in ("bad-source", "bad-size", "destination", "meta-source", "meta-size", "wire")
) + tuple(f"free-{role}-{condition}" for role in ("ack", "notify") for condition in ("source", "size", "wire", "destination"))


def compile_component(binary, *, sanitized=False, object_only=False):
    sources = HERE / "device-models"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    command = [
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
        "-fno-omit-frame-pointer", "-fno-pie", "-pthread", *flags,
        str(sources / "functional-histogram.c"),
    ]
    if object_only:
        command += ["-c"]
    else:
        command += ["-DHOST_TEST", "-no-pie", str(sources / "test-functional-histogram.c")]
    built = subprocess.run([*command, "-o", str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_first_enabled_histogram_owner(tmp_path, sanitized):
    binary = tmp_path / "functional-histogram"
    compile_component(binary, sanitized=sanitized)
    assert len(SCENARIOS) == len(set(SCENARIOS))
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    for case in SCENARIOS:
        ran = subprocess.run([str(binary), case], capture_output=True, text=True, env=env, timeout=10)
        assert ran.returncode == 0, f"component scenario={case}\n{ran.stdout}\n{ran.stderr}"


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_production_histogram_stdout_content_join(tmp_path, sanitized):
    helpers = runpy.run_path(str(REPORT.parent / "functional-camera-evidence/test_evidence.py"))
    checker, capture = helpers["checker"], helpers["host_test_capture"]
    seed = tmp_path / "seed"
    seed.mkdir()
    seed_args = capture(seed, (True,), configuration_only=True, histogram=True)
    seed_transport = checker.check_transport(*seed_args)
    payload = checker.transfer_output(seed_args[0], next(tx for tx in seed_transport["transfers"] if tx["opcode"] == 10))
    binary = tmp_path / "histogram-stdout"
    compile_component(binary, sanitized=sanitized)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    for case in ("evidence-interleaved", "evidence-inline", "evidence-overlap", "evidence-no-receive"):
        ran = subprocess.run([str(binary), case], input=payload, capture_output=True, env=env, timeout=10)
        assert ran.returncode == 0, (case, ran.stdout, ran.stderr)
        log = ran.stdout.decode("ascii")
        root = tmp_path / case
        root.mkdir()
        args = capture(root, (True,), configuration_only=True, histogram=True, histogram_log=log)
        if case == "evidence-no-receive":
            with pytest.raises(ValueError):
                checker.check_transport(*args)
            continue
        transport = checker.check_transport(*args)
        hist = transport["histogram"]
        assert hist["verified"] and hist["AP_consumed"]
        assert hist["ACK_receiver_tid"] != hist["ACK_free_tid"]
        assert hist["notification_receiver_tid"] == hist["notification_free_tid"]
        assert not hist["capture_verified"] and not hist["UI_applied"] and not hist["continuous_histogram"]
        assert bytes.fromhex(hist["result1192_hex"]) == payload
        assert bytes.fromhex(hist["notification1034_hex"])[10:] == payload[168:]
        logged = checker.parse_console(ran.stdout)
        ids = [int(r["fields"]["snapshot_id"]) for r in logged]
        assert set(ids) == set(range(1, 9)) and len(logged) == 32
        if case == "evidence-overlap":
            send = next(r for r in logged if r["tag"] == "FUNCTIONAL_HISTOGRAM_SEND" and r["fields"]["event_role"] == "2")
            pending = next(r["fields"] for r in logged if r["tag"] == "FUNCTIONAL_HISTOGRAM_LEASE" and
                           r["fields"]["snapshot_id"] == send["fields"]["snapshot_id"] and r["fields"]["role"] == "2")
            assert (pending["queued"], pending["received"], pending["releasing"]) == ("1", "0", "1")
        if case == "evidence-interleaved":
            assert ids != sorted(ids)
            ack_receive = next(r for r in logged if r["tag"] == "FUNCTIONAL_HISTOGRAM_RECEIVE" and r["fields"]["event_role"] == "2")
            ack_id = ack_receive["fields"]["snapshot_id"]
            ack_leases = [r for r in logged if r["tag"] == "FUNCTIONAL_HISTOGRAM_LEASE" and r["fields"]["snapshot_id"] == ack_id]
            notification_send = next(r for r in logged if r["tag"] == "FUNCTIONAL_HISTOGRAM_SEND" and r["fields"]["event_role"] == "3")
            assert ack_receive["line"] < notification_send["line"] < ack_leases[0]["line"]

        def event(rows, name, role):
            return next(r for r in rows if r["tag"] == "FUNCTIONAL_HISTOGRAM_" + name and r["fields"]["event_role"] == str(role))

        def lease(rows, name, event_role, role):
            snapshot_id = event(rows, name, event_role)["fields"]["snapshot_id"]
            return next(r for r in rows if r["tag"] == "FUNCTIONAL_HISTOGRAM_LEASE" and
                        r["fields"]["snapshot_id"] == snapshot_id and r["fields"]["role"] == str(role))

        main_mutations = (("SEND", 2, "snapshot_id", "99"), ("SEND", 2, "snapshot_id", "0"),
            ("SEND", 2, "event_role", "3"), ("RECEIVE", 2, "event_role", "1"),
            ("AP_FREE", 2, "event_role", "3"), ("COMPLETE", 0, "event_role", "2"),
            ("COMPLETE", 0, "busy", "1"), ("REQUEST_FREE", 1, "busy", "0"),
            ("REQUEST_FREE", 1, "AP_consumed", "1"), ("REQUEST_FREE", 1, "ACK_AP_consumed", "1"),
            ("SEND", 2, "notification_fnv1a64", "0000000000000000"),
            ("SEND", 2, "model_result_fnv1a64", "0000000000000000"),
            ("SEND", 3, "B_fnv1a64", "0000000000000000"))
        for name, role, key, wrong in main_mutations:
            rows = copy.deepcopy(args[2])
            event(rows, name, role)["fields"][key] = wrong
            with pytest.raises(ValueError):
                checker.check_histogram(args[0], rows, transport)
        lease_mutations = (("RECEIVE", 2, 2, "pid", "1"), ("RECEIVE", 2, 2, "cycle", "2"),
            ("RECEIVE", 2, 2, "snapshot_id", "8"), ("RECEIVE", 2, 2, "role", "3"),
            ("RECEIVE", 2, 2, "pointer", "(nil)"), ("RECEIVE", 2, 2, "freed", "1"),
            ("RECEIVE", 2, 2, "received", "0"), ("RECEIVE", 2, 2, "send_started", "0"),
            ("SEND", 2, 2, "allocation_returned", "0x1234"),
            ("SEND", 2, 2, "allocate_attempted", "0"), ("REQUEST_FREE", 1, 2, "allocate_attempted", "1"),
            ("AP_FREE", 2, 2, "free_rc", "1"), ("AP_FREE", 2, 2, "free_tid", str(hist["ACK_receiver_tid"])),
            ("AP_FREE", 3, 3, "free_tid", str(hist["ACK_free_tid"])),
            ("AP_FREE", 3, 3, "free_attempted", "0"), ("SEND", 2, 2, "send_rc", "1"),
            ("SEND", 2, 2, "wire_fnv1a64", "0000000000000000"))
        for name, trigger_role, role, key, wrong in lease_mutations:
            rows = copy.deepcopy(args[2])
            lease(rows, name, trigger_role, role)["fields"][key] = wrong
            with pytest.raises(ValueError):
                checker.check_histogram(args[0], rows, transport)
        for role in (1, 2, 3):
            rows = copy.deepcopy(args[2])
            rows.remove(lease(rows, "SEND", 2, role))
            with pytest.raises(ValueError):
                checker.check_histogram(args[0], rows, transport)
        for name, role in (("RECEIVE", 2), ("AP_FREE", 3)):
            rows = copy.deepcopy(args[2])
            duplicate = copy.deepcopy(event(rows, name, role))
            rows.append(duplicate)
            with pytest.raises(ValueError):
                checker.check_histogram(args[0], rows, transport)


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_histogram_log_serial_boundaries(tmp_path, sanitized):
    binary = tmp_path / "histogram-serial"
    compile_component(binary, sanitized=sanitized)
    for case in ("alloc-serial-alias", "serial-exhaustion"):
        ran = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=10,
                             env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                  "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
        assert ran.returncode == 0, (case, ran.stdout, ran.stderr)
        if case == "serial-exhaustion":
            assert ran.stdout and all(line == "FUNCTIONAL_HISTOGRAM_RECORD_FAILED snapshot_id_exhausted=1"
                                      for line in ran.stdout.splitlines())
            assert "snapshot_id=" not in ran.stdout


def test_production_requires_real_histogram_bridge(tmp_path):
    obj = tmp_path / "functional-histogram.o"
    compile_component(obj, object_only=True)
    symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert " U fcam_bridge_histogram" in symbols.stdout
    assert "fcam_bridge_init" not in symbols.stdout and "fcam_bridge_call" not in symbols.stdout
    assert "functional_histogram_test_" not in symbols.stdout


def test_pinned_source_and_packet_contract():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    images = {}
    for name, asset in pins["assets"].items():
        path = HERE / ("menu-root/usr/lib/appFw.so" if name == "ap" else "menu-root/cp/cpapp-b.bin")
        raw = path.read_bytes()
        assert len(raw) == asset["size"] and hashlib.sha256(raw).hexdigest() == asset["sha256"]
        images[name] = raw
    for name, row in pins["windows"].items():
        start, size = int(row["raw"], 16), row["bytes"]
        va = int(row["va"], 16)
        if row["kind"] == "ap":
            assert any(seg["va"] <= va and va + size <= seg["va"] + seg["filesz"] and
                       start == seg["raw"] + va - seg["va"] for seg in pins["assets"]["ap"]["mapping"])
        else:
            assert va == start + 0x108000
        actual = images[row["kind"]][start:start + size]
        assert len(actual) == size and hashlib.sha256(actual).hexdigest() == row["sha256"], name
        assert actual.hex() == row["raw_hex"], name
    wire = bytes.fromhex(pins["implementation"]["request_hex"])
    assert len(wire) == 12 and struct.unpack_from("<4H", wire) == (0x200d, 0x0148, 12, 0x8001)
    assert wire[8:] == b"\1\1\0\0"
    ack = bytes.fromhex(pins["implementation"]["ack_hex"])
    assert struct.unpack("<4HI", ack) == (0x200d, 0x1148, 12, 0x8001, 0x00590000)
    header = bytes.fromhex(pins["implementation"]["notification_header_hex"])
    assert struct.unpack("<5H", header) == (0x200d, 0x210c, 1034, 0x8001, 1)
    assert pins["implementation"]["scenario_count_per_build"] == len(SCENARIOS)
    assert pins["implementation"]["core_combination_verified"] is False
