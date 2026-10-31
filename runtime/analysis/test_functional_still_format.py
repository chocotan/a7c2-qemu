# SPDX-License-Identifier: MIT
"""Actual Core + unchanged one-shot diagnostic + functional owner, host only.

The fixture replaces only the bridge transport and OSAL envelope. Parent owns
all13/current-VDF resource integration and the actual original receive hooks.
No VM, original AP, CP/RTOS, physical format or capture success is asserted.
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

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / "report"
EVIDENCE = HERE / "scratch/functional-still-format-owner"
SOURCES = (
    "functional-camera-core/functional-camera-core.c",
    "virtual-optics/optics.c",
    "virtual-optical-frame-owner/optical-frame-owner.c",
    "virtual-jpeg-hardware/jpeg-hardware.c",
    "virtual-jpeg-hardware/jpeg-hardware-codec.c",
    "virtual-jpeg-sos/jpeg-sos.c",
    "virtual-video-engine/video-engine.c",
    "virtual-camera-pipeline/camera-pipeline.c",
)
PREFLIGHT = ("old-M", "short", "long", "source", "type", "command", "destination",
             "default-off", "predecessor", "no-init", "no-active", "torn-preflight")
STATE_FAILURES = ("state-cap", "state-token", "state-max", "state-short", "state-canary", "state-instance", "state-torn")
# All 16 independent saved-format readback bytes and every meaningful fixed
# result field are tested; route3/5..12 remain opaque by the software contract.
MUTATIONS = (0, 4, 8, 16, 24, 32, 40, 48, 56, 64, 72, 76, 80, 84, 88, 92,
             96, 100, 104, 108, 112, 116, 120, 124, 128, 129, 130, 132,
             141, 142, 143, 144, 152, *range(160, 176))
CORRUPT = (*("mutate-" + str(offset) for offset in MUTATIONS), "class7", "result168", "token",
           "instance", "required", "bridge-error", "format-canary", "torn-consumed")
IO_FAILURES = ("request-free", "reply-free", "alloc-null", "alloc-alias", "alloc-overflow",
               "alloc-error-pointer", "reply-readback", "send-error", "inline-send-error",
               "wrong-free-thread", "no-receive", "receive-source", "receive-size", "receive-wire")
SCENARIOS = ("normal", "repeat", "repeat-state-fail", "same-cookie", "opaque", "inline", "stale", "address-reuse",
             "reentrant", "busy", "pointer-boundaries", "fork", *PREFLIGHT, *STATE_FAILURES, *CORRUPT, *IO_FAILURES,
             *("body-" + str(offset) for offset in range(14)))
assert len(SCENARIOS) == len(set(SCENARIOS))


def save_log(name, value):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@pytest.fixture(scope="module", params=("strict", "sanitized"))
def owner_binary(request):
    mode = request.param
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    package_command = ["pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat", "libavutil", "libswscale"]
    packages = subprocess.run(package_command, capture_output=True, text=True, timeout=10)
    save_log(f"pkg-config-{mode}.json", {"argv": package_command, "returncode": packages.returncode,
                                      "stdout": packages.stdout, "stderr": packages.stderr})
    assert packages.returncode == 0, packages.stdout + packages.stderr
    inputs = [HERE / "device-models" / name for name in (
        "functional-still-format.c", "functional-still-format.h", "test-functional-still-format.c",
        "cp-capture-format.c", "cp-capture-format.h")]
    inputs += [REPORT / source for source in SOURCES]
    save_log(f"inputs-{mode}.json", {str(path.relative_to(HERE.parents[1])): hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in inputs})
    with tempfile.TemporaryDirectory(prefix=f"build-{mode}-", dir=EVIDENCE) as directory:
        binary = Path(directory) / "functional-still-format"
        sanitizer = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if mode == "sanitized" else []
        command = [*shlex.split(os.environ.get("CC", "cc")), "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                   "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread", *sanitizer,
                   str(HERE / "device-models/functional-still-format.c"), str(HERE / "device-models/cp-capture-format.c"),
                   str(HERE / "device-models/test-functional-still-format.c"), *(str(REPORT / source) for source in SOURCES),
                   *shlex.split(packages.stdout), "-lm", "-o", str(binary)]
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=90)
        save_log(f"build-{mode}.json", {"argv": command, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr})
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
    before, after, result = (bytes.fromhex(row[key]) for key in ("before128", "after128", "result176"))
    assert len(before) == len(after) == 128 and len(result) == 176
    assert before[:56] == after[:56] and before[80:112] == after[80:112]
    cfg, frame, lease = struct.unpack_from("<QQQ", result, 16)
    assert cfg == int.from_bytes(before[56:64], "little") + 1 == int.from_bytes(after[56:64], "little")
    assert frame == int.from_bytes(before[112:120], "little") + 1 == int.from_bytes(after[112:120], "little")
    assert lease == int(row["lease"]) > int(row["previous_lease"]) > 0
    assert int(row["serial"]) == int(row["previous_serial"]) + 1
    assert row["proof_consumer"] == "4" and row["proof_bytes"] == "176" and row["token"] == "0"
    assert row["proof_fnv"] == f"{fnv(result):016x}"
    canonical = bytes.fromhex("02000001000100000001000100000000")
    route = bytes((1, 5, 5, 0xad, 2, *range(0xb1, 0xb9), 0, 0, 0))
    source_hash = int.from_bytes(result[48:56], "little")
    assert source_hash
    expected = bytearray(176)
    struct.pack_into("<IIQQQQQ", expected, 0, 1, 176, 0xa7402d, cfg, frame, lease, fnv(canonical))
    struct.pack_into("<QQQ14I", expected, 48, source_hash, source_hash, 921600, 640, 480, 1920,
                     0x90590819, 1, 1, 8, 1, 1, 1, 1, 1, 0, 0)
    expected[128:144] = route
    struct.pack_into("<QQ", expected, 144, frame - 1, cfg - 1)
    expected[160:] = canonical
    assert result == expected
    for offset in (64, 72):
        assert int.from_bytes(after[offset:offset+8], "little") == int.from_bytes(before[offset:offset+8], "little") + 1


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_core_still_format_owner(owner_binary, scenario):
    binary, mode = owner_binary
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    command = [str(binary), scenario]
    result = subprocess.run(command, cwd=binary.parent, env=env, capture_output=True, text=True, timeout=30)
    # Keep failures under unique names; later green reruns never overwrite them.
    name = f"{mode}-{scenario}"
    if result.returncode:
        name += f"-failed-{len(list(EVIDENCE.glob(name + '-failed-*.json'))) + 1}"
    save_log(name + ".json", {"argv": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    diagnostic, = rows(result.stdout, "diagnostic")
    assert diagnostic == {"first_M_clean": "1", "second_L_blocked": "-1021", "unchanged_one_shot": "1"}
    scope, = rows(result.stdout, "scope")
    assert scope["scenario"] == scenario and scope["media_writes"] == "0" and int(scope["callbacks"]) > 0
    assert all(scope[key] == "false" for key in ("original_ap_verified", "vm_verified", "original_cp",
                "physical_asic_verified", "physical_cp_rtos_verified", "capture_verified"))
    preflight = scenario in PREFLIGHT or scenario.startswith("body-")
    count = 0 if preflight or scenario in STATE_FAILURES or scenario in ("fork", "pointer-boundaries") else 2 if scenario in ("repeat", "same-cookie", "address-reuse") else 1
    core = rows(result.stdout, "core")
    assert len(core) == int(scope["calls"]) == count
    for row in core:
        verify_core(row)
    if preflight:
        assert rows(result.stdout, "preflight") == [{"frame_delta": "0", "ownership_delta": "0", "request_free_delta": "0", "ack_delta": "0", "caller_owned": "1"}]
    elif scenario in STATE_FAILURES:
        assert rows(result.stdout, "state_refused") == [{"op13_delta": "0", "ownership_delta": "0", "frame_delta": "0"}]
    elif scenario in CORRUPT:
        refused, = rows(result.stdout, "refused")
        assert all(refused[key] == "1" for key in ("actual_core_committed", "frame_delta", "caller_owned"))
        assert refused["ack_delta"] == refused["request_free_delta"] == "0" and int(refused["rc"]) < 0
    elif scenario == "pointer-boundaries":
        assert rows(result.stdout, "boundaries") == [{"overflow_no_callback": "1", "alias_unchanged": "1"}]
    elif scenario == "fork":
        assert rows(result.stdout, "fork") == [{"rejected_before_inherited_lock": "1"}]
    else:
        lifecycle = rows(result.stdout, "lifecycle")
        assert len(lifecycle) == count
        for index, row in enumerate(lifecycle):
            failed = scenario in IO_FAILURES
            assert row["consumed"] == str(int(not failed)) and row["faults"] == str(int(failed))
            assert int(row["requests"]) == index + 1 and int(row["completed"]) == (0 if failed else index + 1)
            wire = bytes.fromhex(row["wire24"])
            assert len(wire) == 24 and wire[:4] == (bytes.fromhex("05e72d40") if scenario == "opaque" else bytes.fromhex("05002d40"))
            assert wire[8:22] == bytes.fromhex("0200000100010000000100010000")
            assert wire[22:] == (b"\xab\xcd" if scenario == "opaque" else b"\0\0")
            assert bytes.fromhex(row["reply12"]) == b"\x01\0\x2d\x40" + wire[4:8] + b"\0\xf0\0\0"
            if not failed or scenario == "inline-send-error":
                assert row["request_free"] == row["reply_free"] == "1" and row["sender"] == row["free_tid"] != row["receiver"]
        if scenario == "repeat-state-fail":
            assert scope["state_calls"] == "2"
            assert rows(result.stdout, "state_refused") == [{"op13_delta": "0", "ownership_delta": "0", "frame_delta": "0"}]
        if scenario in ("inline", "inline-send-error"):
            assert rows(result.stdout, "inline") == [{"freed": "1", "consumed_before_send_return": "0"}]
    if scenario in CORRUPT or scenario in IO_FAILURES or scenario in STATE_FAILURES or scenario == "repeat-state-fail":
        assert rows(result.stdout, "sticky") == [{"implicit_retry": "0", "snapshot_unchanged": "1"}]
