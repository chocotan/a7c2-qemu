# SPDX-License-Identifier: MIT
"""Host-only actual Core/optics/sink + unchanged legacy diagnostic + new owner.

Only transport/OSAL envelopes are fixtures. Parent owns guard31/all13/current
still-format composition, mailbox integration and actual original AP hooks.
"""
from pathlib import Path
import hashlib
import json
import os
import shlex
import struct
import subprocess
import tempfile

import pytest

from test_functional_still_format import SOURCES

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / "report"
LOGS = HERE / "scratch/functional-startup-control-owner/logs"
MODE_BODY = bytes.fromhex("00000100010000000100000000000000")
SCENARIOS = (
    "normal", "repeat", "same-cookie", "address-reuse", "inline", "opaque", "fresh-config", "ticket", "reentrant",
    "settings-while-live", "default-off", "unsupported", "predecessor", "no-init", "no-active", "settings-first",
    "state-mutations", "state-torn", "torn-consumed", "guard-torn", "stale-configfp", "bad-receipt", "bad-descriptor",
    "bridge-error", "canary", "old-proof", "fork", "pointer-boundaries", "io-faults", "receive-faults",
    "wrong-free-thread", "no-receive", "inline-send-error", "repeat-state-fail", "send-error",
)
assert len(SCENARIOS) == len(set(SCENARIOS)) == 35
# Opaque route bytes3/5..12 and lease high bytes cannot be inferred from STATE.
# Test all exact-valued receipt bytes and all32 independently read-back bytes.
MUTATIONS = (*range(32), 32, *range(40, 128), 128, 129, 130, 132, 141, 142, 143, *range(144, 192))
VARIANTS = {"normal": range(2), "unsupported": range(40), "predecessor": range(2), "state-mutations": range(33),
            "stale-configfp": range(2), "bad-receipt": MUTATIONS, "bad-descriptor": range(6), "canary": range(2),
            "io-faults": range(16), "receive-faults": range(5)}


def save_log(name, value):
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / (name + ".json")
    if value.get("returncode", 0):
        path = LOGS / f"{name}-failed-{len(list(LOGS.glob(name + '-failed-*.json'))) + 1}.json"
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.fixture(scope="module", params=("strict", "sanitized"))
def owner_binary(request):
    mode = request.param
    LOGS.mkdir(parents=True, exist_ok=True)
    pkg_command = ["pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat", "libavutil", "libswscale"]
    packages = subprocess.run(pkg_command, capture_output=True, text=True, timeout=10)
    save_log(f"pkg-config-{mode}", {"argv": pkg_command, "returncode": packages.returncode,
                                   "stdout": packages.stdout, "stderr": packages.stderr})
    assert packages.returncode == 0, packages.stdout + packages.stderr
    inputs = [HERE / "device-models" / name for name in (
        "functional-startup-control.c", "functional-startup-control.h", "test-functional-startup-control.c",
        "cp-startup-controls-diagnostic.c", "cp-startup-controls-diagnostic.h")]
    inputs += [HERE / "functional-startup-control-abi.h", HERE / "functional-camera-abi.h"]
    inputs += [REPORT / source for source in SOURCES]
    save_log(f"inputs-{mode}", {str(path.relative_to(HERE.parents[1])): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs})
    with tempfile.TemporaryDirectory(prefix=f"build-{mode}-", dir=LOGS) as directory:
        binary = Path(directory) / "functional-startup-control"
        sanitizer = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if mode == "sanitized" else []
        command = [*shlex.split(os.environ.get("CC", "cc")), "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                   "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread", *sanitizer,
                   *(str(HERE / "device-models" / name) for name in (
                       "functional-startup-control.c", "cp-startup-controls-diagnostic.c", "test-functional-startup-control.c")),
                   *(str(REPORT / source) for source in SOURCES), *shlex.split(packages.stdout), "-lm", "-o", str(binary)]
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=60)
        save_log(f"build-{mode}", {"argv": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == 0, result.stdout + result.stderr
        yield binary, mode


def rows(stdout, prefix):
    return [dict(item.split("=", 1) for item in line.split()[1:])
            for line in stdout.splitlines() if line.startswith(prefix + " ")]


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def verify_core(row):
    before, after, canonical, result = (bytes.fromhex(row[key]) for key in ("before128", "after128", "input32", "result192"))
    assert len(before) == len(after) == 128 and len(canonical) == 32 and len(result) == 192
    assert before[:56] == after[:56] and before[80:112] == after[80:112]
    command, body_bytes = struct.unpack_from("<HH", canonical)
    assert (command, body_bytes) in ((0x4014, 16), (0x4057, 4))
    expected_input = struct.pack("<HH", command, body_bytes) + (MODE_BODY if command == 0x4014 else bytes(16)) + bytes(4) + struct.pack("<Q", fnv(before[8:48]))
    assert canonical == expected_input
    cfg = int.from_bytes(before[56:64], "little") + 1
    frame = int.from_bytes(before[112:120], "little") + 1
    lease = int(row["lease"])
    assert cfg == int.from_bytes(after[56:64], "little") and frame == int.from_bytes(after[112:120], "little")
    assert lease > int(row["previous_lease"]) > 0 and int(row["serial"]) == int(row["previous_serial"]) + 1
    assert row["proof_consumer"] == "4" and row["proof_bytes"] == "192" and row["token"] == "0"
    assert row["proof_fnv"] == f"{fnv(result):016x}"
    source_hash = int(row["source_fnv"], 16)
    assert source_hash
    expected = bytearray(192)
    struct.pack_into("<IIQQQQQ", expected, 0, 1, 192, 0xa7401457, cfg, frame, lease, fnv(expected_input))
    struct.pack_into("<QQQ14I", expected, 48, source_hash, source_hash, 921600, 640, 480, 1920,
                     0x90590819, 1, 1, 9, 1, 1, 1, 1, 1, 0, 0)
    expected[128:144] = bytes((1, 5, 5, 0xad, 2, *range(0xb1, 0xb9), 0, 0, 0))
    struct.pack_into("<QQ", expected, 144, frame - 1, cfg - 1)
    expected[160:] = expected_input
    assert result == expected
    for offset in (64, 72):
        assert int.from_bytes(after[offset:offset + 8], "little") == int.from_bytes(before[offset:offset + 8], "little") + 1


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_core_startup_control_owner(owner_binary, scenario):
    binary, mode = owner_binary
    for variant in VARIANTS.get(scenario, (0,)):
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
               "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
        command = [str(binary), scenario, str(variant)]
        result = subprocess.run(command, cwd=binary.parent, env=env, capture_output=True, text=True, timeout=15)
        log = {"argv": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        name = f"{mode}-{scenario}-{variant}"
        save_log(name, log)
        assert result.returncode == 0, result.stdout + result.stderr
        try:
            assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
            diagnostic, = rows(result.stdout, "diagnostic")
            assert diagnostic == {"first4014_clean": "1", "first4057_clean": "1", "repeat4014": "-1022", "repeat4057": "-1022", "unchanged_one_shot": "1"}
            scope, = rows(result.stdout, "scope")
            assert scope["scenario"] == scenario and scope["variant"] == str(variant) and scope["media_writes"] == "0"
            assert int(scope["callbacks"]) > 0
            assert all(scope[key] == "false" for key in ("original_ap_verified", "vm_verified", "original_cp", "physical_asic_verified", "physical_cp_rtos_verified", "capture_verified"))
            core = rows(result.stdout, "core")
            assert len(core) == int(scope["commits"])
            for row in core:
                verify_core(row)
            lifecycle = rows(result.stdout, "lifecycle")
            for index, row in enumerate(lifecycle):
                assert int(row["requests"]) == index + 1
                assert int(row["completed"]) == index + int(row["consumed"])
                assert int(row["mode_requests"]) + int(row["settings_requests"]) == index + 1
                assert int(row["mode_completed"]) + int(row["settings_completed"]) == int(row["completed"])
                assert row["mode_applied"] == "1"
                wire, reply = bytes.fromhex(row["wire"]), bytes.fromhex(row["reply12"])
                command = int(row["command"], 16)
                assert len(wire) == (24 if command == 0x4014 else 12)
                assert wire[0] == 5 and wire[1] == (0xe7 if scenario == "opaque" else 0)
                assert wire[8:] == (MODE_BODY if command == 0x4014 else bytes(4))
                assert reply == b"\x01\0" + struct.pack("<H", command) + wire[4:8] + b"\0\xf0\0\0"
                if row["consumed"] == "1" or scenario == "inline-send-error":
                    assert row["request_free"] == row["reply_free"] == "1"
                    assert row["sender"] == row["free_tid"] != row["receiver"]
            if scenario in ("normal", "repeat", "same-cookie", "address-reuse", "inline", "opaque", "fresh-config", "ticket", "reentrant", "settings-while-live"):
                expected_cycles = 4 if scenario in ("repeat", "fresh-config", "same-cookie") else 2 if scenario not in ("reentrant", "settings-while-live") else 1
                assert len(lifecycle) == len(core) == expected_cycles
                assert all(row["consumed"] == "1" and row["faults"] == "0" and row["retained"] == "0" for row in lifecycle)
            if scenario == "same-cookie":
                assert lifecycle[0]["wire"] == lifecycle[1]["wire"] and lifecycle[2]["wire"] == lifecycle[3]["wire"] and len(core) == 4
            if scenario == "fresh-config":
                assert core[0]["input32"][-16:] != core[1]["input32"][-16:]
                assert bytes.fromhex(core[1]["before128"])[8:48] == bytes.fromhex(core[3]["before128"])[8:48]
            if rows(result.stdout, "refused"):
                refused, = rows(result.stdout, "refused")
                assert int(refused["rc"]) < 0 and refused["caller_owned"] == "1" and refused["ack_delta"] == refused["request_free_delta"] == "0"
                assert len(bytes.fromhex(refused["raw192"])) == 192
            if scenario in ("default-off", "unsupported", "predecessor", "settings-first"):
                assert rows(result.stdout, "preflight") == [{"core_delta": "0", "ownership_delta": "0", "ack_delta": "0", "caller_owned": "1"}]
            if scenario in ("bad-receipt", "bad-descriptor", "bridge-error", "canary", "old-proof", "torn-consumed", "guard-torn"):
                assert rows(result.stdout, "refused")[0]["actual_core_committed"] == "1"
            if scenario in ("state-mutations", "state-torn", "no-init", "no-active", "stale-configfp", "repeat-state-fail"):
                assert rows(result.stdout, "refused")[0]["actual_core_committed"] == "0"
            if scenario in ("inline", "inline-send-error"):
                assert len(rows(result.stdout, "inline")) == len(core)
            if scenario == "fork":
                assert rows(result.stdout, "fork") == [{"rejected_before_inherited_lock": "1"}]
            if scenario == "pointer-boundaries":
                assert rows(result.stdout, "boundaries") == [{"overflow_no_callback": "1", "alias_unchanged": "1"}]
        except Exception as error:
            save_log(name + "-python-check", {**log, "returncode": 1, "verification_error": repr(error)})
            raise
