# SPDX-License-Identifier: MIT
"""Real Core INIT/STATE and deferred 3006 owner, HOST_TEST transport only.

No VM, original AP, native all13/debugger handoff, mailbox/RSP or capture is
claimed. The readiness callback is a host fixture, never native evidence.
"""
from pathlib import Path
import os
import shlex
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / "report"
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
SCENARIOS = (
    "deferred-thread", "immediate", "dynamic-source", "cookie-zero", "cookie-max",
    "preinitialized", "address-reuse", "retired-source", "busy", "reentry", "parallel-progress", "inline",
    "declines", "unbound", "fork-before-mutex", "ready-no-data", "ready-error", "ready-invalid", "ready-regressed",
    "reserve-fail", "reserve-positive", "reserve-callback-fault", "probe-callback-fault", "bridge-init-fail", "bridge-state-fail", "bridge-positive",
    "allocate-fail", "allocate-null", "allocate-with-error", "allocate-length", "allocate-private-alias",
    "set-source-fail", "write-readback-fail", "request-free-fail", "send-fail", "inline-send-fail",
    "no-receive", "free-before-receive", "wrong-receive-tid", "wrong-free-tid", "reply-free-fail", "free-reentry",
    "receive-destination", "receive-source", "receive-length", "receive-wire",
    "receive-envelope-source", "receive-envelope-length", "free-source", "free-length", "free-wire",
    "request-source", "request-length", "request-external-free", "request-free-reentry",
    "receive-missing-ticket", "receive-duplicate", "free-missing-callback",
) + tuple(f"{stage}-{field}" for stage in ("init", "state")
          for field in ("used", "required", "nonce", "token", "overrun"))


@pytest.fixture(scope="module", params=("normal", "sanitized"))
def background_binary(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("functional-background-start-" + request.param)
    binary = directory / "functional-background-start"
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=10))
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "sanitized" else []
    built = subprocess.run([
        *shlex.split(os.environ.get("CC", "cc")), "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, str(HERE / "device-models/functional-background-start.c"),
        str(HERE / "device-models/test-functional-background-start.c"),
        *(str(REPORT / source) for source in SOURCES), *libraries, "-lm", "-o", str(binary),
    ], cwd=directory, capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def run_case(binary, scenario, *args):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    result = subprocess.run([str(binary), scenario, *map(str, args)], cwd=binary.parent,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"scenario={scenario} args={args}\n{result.stdout}\n{result.stderr}"
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    assert "native_predecessors_verified=false" in result.stdout
    assert "physical_asic_verified=false original_ap_verified=false capture_verified=false" in result.stdout
    return result.stdout


def rows(stdout, prefix):
    return [dict(item.split("=", 1) for item in line.split()[1:])
            for line in stdout.splitlines() if line.startswith(prefix + " ")]


def fnv64(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_background_start_real_core(background_binary, scenario):
    stdout = run_case(background_binary, scenario)
    completed = rows(stdout, "complete")
    for row in completed:
        state = bytes.fromhex(row["state128"])
        assert len(state) == 128 and state[120:] == bytes(8)
        assert struct.unpack_from("<II", state) == (1, 15)
        assert int.from_bytes(state[48:56], "little") == 0x9a17013006
        assert row["fnv"] == f"{fnv64(state):016x}"
        assert int.from_bytes(state[56:64], "little") == int(row["config"])
        assert int.from_bytes(state[64:72], "little") == int(row["rendered"])
        assert int.from_bytes(state[72:80], "little") == int(row["consumed"])
        assert int.from_bytes(state[112:120], "little") == int(row["frame"])
        assert row["same_sender_receive_free"] == "1"
        assert row["init_calls"] == row["state_calls"] == row["cycles"]
        assert row["actual_request_frees"] == row["actual_reply_frees"] == row["cycles"]
        assert row["source"] == ("8102a1b7" if scenario == "dynamic-source" or
                                 scenario == "retired-source" and row["cycles"] == "2" else "810261c4")
        reply = bytes.fromhex(row["reply12"])
        assert len(reply) == 12 and reply[:4] == bytes.fromhex("01000630")
        assert reply[4:8] == (bytes(4) if scenario == "cookie-zero" else
                             bytes([255]) * 4 if scenario == "cookie-max" else bytes.fromhex("abacadae"))
        assert reply[8:] == bytes.fromhex("00f00000")
    if scenario == "deferred-thread":
        assert len(completed) == 1 and completed[0]["producer_separate"] == "1"
    if scenario in ("preinitialized", "address-reuse"):
        assert len(completed) == 2
        assert "INIT_preserved_all_state=1 frame_counts_preserved=1 stale_ticket_rejected=1" in stdout
        if scenario == "preinitialized":
            assert all(row["config"] == "3" and row["rendered"] == "2" and row["consumed"] == "1"
                       for row in completed)
            assert all(bytes.fromhex(row["state128"])[8:16] == struct.pack("<II", 96, 64) for row in completed)
    if "fault " in stdout:
        fault, = rows(stdout, "fault")
        assert int(fault["error"]) < 0 and fault["pending"] == "1" and fault["retries"] == "0"
    if scenario == "ready-no-data":
        assert "pending no_mailbox=1 reservations=0 bridge_calls=0 no_ACK=1" in stdout
    if scenario == "no-receive":
        assert "pending queued_not_consumed=1" in stdout


@pytest.mark.parametrize("byte", range(24))
def test_pending_original_request_is_immutable_before_reserve(background_binary, byte):
    stdout = run_case(background_binary, "request-byte", byte)
    fault, = rows(stdout, "fault")
    assert fault["retained_original"] == "1" and fault["retained_reply"] == "0"
    summary, = rows(stdout, "HOSTTEST")
    assert all(summary[field] == "0" for field in ("init_calls", "state_calls", "allocations", "sends", "original_free_calls"))


@pytest.mark.parametrize("stage", ("init", "state"))
@pytest.mark.parametrize("byte", range(128))
def test_every_actual_state128_byte_is_checked(background_binary, stage, byte):
    stdout = run_case(background_binary, f"corrupt-{stage}-byte", byte)
    fault, = rows(stdout, "fault")
    assert fault["retained_original"] == "1" and fault["retained_reply"] == "0"
    summary, = rows(stdout, "HOSTTEST")
    assert summary["allocations"] == summary["sends"] == summary["original_free_calls"] == summary["reply_free_calls"] == "0"
    assert int(summary["init_calls"]) == 1
    assert int(summary["state_calls"]) in (0, 1)
    if stage == "state":
        assert int(summary["state_calls"]) == 1
