# SPDX-License-Identifier: MIT
"""真实 Core + Guest owner HOST 组合测试；原 AP/VM/拍摄均未验。

只替代 bridge transport 和 malloc OSAL envelope。软件 selector0 定义为 RGB888，
不证明原物理 selector0 的位深；ACK 0x590000 仅在 Core RGB 消费和 request 释放后检验。
所有场景各启新进程，不写媒体文件。capture_verified=false。
"""
from pathlib import Path
import json
import os
import shlex
import struct
import subprocess
import tempfile

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / "report"
EVIDENCE = HERE.parents[1] / "validation/tmp/functional-bit-width-guest-tests"
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
PREFLIGHT = (
    "selector1", "selector2", "selector3", "byte9", "header", "short", "long",
    "unknown-source", "default-off", "disabled", "no-active",
)
CORRUPT = tuple("corrupt-" + name for name in ("class", "sink", "input", "tail", "instance", "used", "error"))
IO_FAILURES = ("send-fail", "request-free-fail", "ack-free-fail", "inline-send-fail", "wrong-thread")
SCENARIOS = ("normal", "repeat", "mixed-route", *PREFLIGHT, *CORRUPT,
             *IO_FAILURES, "inline", "no-ticket", "stale-ticket", "address-reuse")
assert len(SCENARIOS) == len(set(SCENARIOS)) == 30


def save_log(name, data):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture(scope="module", params=("normal", "sanitized"))
def bit_width_binary(request):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    mode = request.param
    package_command = ["pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec",
                       "libavformat", "libavutil", "libswscale"]
    packages = subprocess.run(package_command, capture_output=True, text=True, timeout=10)
    save_log(f"pkg-config-{mode}.json", {"argv": package_command, "returncode": packages.returncode,
                                      "stdout": packages.stdout, "stderr": packages.stderr})
    assert packages.returncode == 0, packages.stdout + packages.stderr
    with tempfile.TemporaryDirectory(prefix=f"build-{mode}-", dir=EVIDENCE) as directory:
        binary = Path(directory) / "functional-vdf-bit-width"
        flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if mode == "sanitized" else []
        command = [
            *shlex.split(os.environ.get("CC", "cc")), "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra",
            "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
            "-pthread", *flags, str(HERE / "device-models/functional-vdf-path.c"),
            str(HERE / "device-models/test-functional-vdf-bit-width.c"),
            *(str(REPORT / source) for source in SOURCES), *shlex.split(packages.stdout), "-lm", "-o", str(binary),
        ]
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=90)
        save_log(f"build-{mode}.json", {"argv": command, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == 0, result.stdout + result.stderr
        yield binary, mode


def rows(stdout, prefix):
    return [dict(item.split("=", 1) for item in line.split()[1:])
            for line in stdout.splitlines() if line.startswith(prefix + " ")]


def fnv64(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def verify_core_receipt(row, proof, variant):
    data = bytes.fromhex(row["result168"])
    before = bytes.fromhex(row["before128"])
    after = bytes.fromhex(row["after128"])
    assert len(data) == 168 and len(before) == len(after) == 128
    assert bytes.fromhex(row["input8"]) == bytes(8) and row["core_committed"] == "1"
    config, frame, lease = struct.unpack_from("<QQQ", data, 16)
    assert config == int.from_bytes(before[56:64], "little") + 1 == int.from_bytes(after[56:64], "little")
    assert frame == int.from_bytes(before[112:120], "little") + 1 == int.from_bytes(after[112:120], "little")
    assert before[8:56] == after[8:56] and before[80:112] == after[80:112]
    assert lease > int(row["previous_lease"]) > 0
    source_hash = int.from_bytes(data[48:56], "little")
    assert source_hash
    route = bytes((1, 5, 5, 0xab + variant, 2, *(i + variant for i in range(0xad, 0xb5)), 0, 0, 0))
    expected = bytearray(168)
    struct.pack_into("<IIQQQQQ", expected, 0, 1, 168, 0x9a1701, config, frame, lease, fnv64(bytes(8)))
    struct.pack_into("<QQQ14I", expected, 48, source_hash, source_hash, 921600, 640, 480, 1920,
                     0x90590819, 1, 1, 7, 1, 1, 1, 1, 1, 0, 0)
    expected[128:144] = route
    struct.pack_into("<QQ", expected, 144, frame - 1, config - 1)
    assert data == expected
    p = {key: int(value) for key, value in proof.items()}
    assert p["version"] == 1 and p["struct_bytes"] == 376 and p["model_instance"] == 0x9a1701
    assert p["serial"] == int(row["previous_serial"]) + 1 and p["model_lifetime"] > 0 and p["owner_pid"] > 0
    assert p["opcode"] == 12 and p["consumer_kind"] == 4
    assert (p["config_generation"], p["frame_generation"], p["lease_generation"]) == (config, frame, lease)
    assert p["packet_generation"] == int(row["previous_packet"])
    assert (p["width"], p["height"], p["stride"], p["active_bytes"]) == (640, 480, 1920, 921600)
    assert p["source_fnv1a64"] == p["consumer_before_fnv1a64"] == p["consumer_after_fnv1a64"] == source_hash
    assert all(p[key] == 1 for key in ("render_observed", "consumer_entered", "consumer_returned", "retired", "final_state"))
    assert (p["source_state"], p["consumer_before_state"], p["consumer_after_state"]) == (3, 4, 4)
    assert all(p[key] == 0 for key in ("encoder_consumed", "encoded_bytes", "result_token", "render_status",
                                      "consumer_status", "retire_status", "operation_status"))
    assert p["result_bytes"] == 168 and p["result_fnv1a64"] == fnv64(data)
    assert row["typed_fnv"] == f"{fnv64(data):016x}"
    assert p["encoded_fnv1a64"] == fnv64(b"")
    for field in ("rendered", "consumed", "retired"):
        assert p[f"after.{field}"] == p[f"before.{field}"] + 1
    for field in ("jpeg_encoded", "video_encoded"):
        assert p[f"after.{field}"] == p[f"before.{field}"] == 0
    assert p["before.rendered"] == int.from_bytes(before[64:72], "little")
    assert p["after.rendered"] == int.from_bytes(after[64:72], "little")
    assert p["before.consumed"] == int.from_bytes(before[72:80], "little")
    assert p["after.consumed"] == int.from_bytes(after[72:80], "little")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_real_core_guest_bit_width(bit_width_binary, scenario):
    binary, mode = bit_width_binary
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    command = [str(binary), scenario]
    result = subprocess.run(command, cwd=binary.parent, env=env, capture_output=True, text=True, timeout=30)
    save_log(f"{mode}-{scenario}.json", {"argv": command, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr})
    assert result.returncode == 0, f"真实 Core/guest owner，原 AP/VM/拍摄未验\n{result.stdout}\n{result.stderr}"
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    scope, = rows(result.stdout, "scope")
    assert scope["scenario"] == scenario
    assert int(scope["callbacks"]) == 0 if scenario == "default-off" else int(scope["callbacks"]) > 0
    assert all(scope[field] == "false" for field in ("capture_verified", "original_ap_verified", "vm_verified",
               "physical_asic_verified", "physical_cp_rtos_verified", "original_cp_fifo_verified", "original_selector_verified"))
    assert scope["functional_rgb888_only"] == "true" and scope["media_disk_writes"] == "0"
    assert scope["owner_cleanup_unchanged"] == "1"
    core, proofs, lifecycle = rows(result.stdout, "core"), rows(result.stdout, "proof"), rows(result.stdout, "lifecycle")
    expected_calls = 0 if scenario in PREFLIGHT else 2 if scenario in ("repeat", "mixed-route", "address-reuse") else 1
    assert len(core) == len(proofs) == int(scope["bit_calls"]) == expected_calls
    bridge_rows = rows(result.stdout, "bridge")
    assert len(bridge_rows) == expected_calls
    for bridge in bridge_rows:
        assert bridge == {"used": "168", "required": "168", "instance": "00000000009a1701", "token": "0"}
    assert int(scope["init_calls"]) == (0 if scenario in ("default-off", "no-active") else 1)
    for index, (receipt, proof) in enumerate(zip(core, proofs)):
        verify_core_receipt(receipt, proof, int(scenario == "mixed-route" and index == 1))
    if scenario in PREFLIGHT:
        rejected, = rows(result.stdout, "preflight")
        assert all(rejected[key] == "0" for key in ("bridge_delta", "init_delta", "frame_delta", "ownership_delta", "output_delta"))
        assert rejected["owner_unchanged"] == rejected["caller_owns"] == "1" and not lifecycle
        assert int(rejected["rc"]) == (999 if scenario == "default-off" else -95)
    elif scenario in CORRUPT:
        refused, = rows(result.stdout, "refused")
        assert refused["core_committed"] == refused["frame_delta"] == refused["caller_owns"] == "1"
        assert refused["ack_delta"] == refused["request_free_delta"] == "0" and not lifecycle
        assert int(refused["rc"]) == (-5 if scenario == "corrupt-error" else -71)
        assert len(rows(result.stdout, "sticky")) == 1
    else:
        assert len(lifecycle) == expected_calls
        for index, life in enumerate(lifecycle):
            failed = scenario in IO_FAILURES
            assert life["source"] == f"{0x81cf5e00 + index:08x}" and life["destination"] == "92840747"
            assert life["request_bytes"] == "10" and life["ack_bytes"] == "12"
            assert life["request_wire"] == "0d205e010a0001800000" and life["ack_wire"] == "0d205e110c00018000005900"
            assert int(life["consumed"]) == int(not failed) and int(life["faults"]) == int(failed)
            assert life["free_before_alloc"] == str(int(scenario != "request-free-fail"))
            assert life["request_free_calls"] == "1" and int(life["ack_free_calls"]) <= 1
            if not failed or scenario == "inline-send-fail":
                assert life["ack_frees"] == "1" and life["sender_tid"] == life["receiver_tid"] == life["free_tid"]
            if scenario == "address-reuse":
                assert life["same_address"] == "1"
        if scenario in IO_FAILURES:
            assert len(rows(result.stdout, "sticky")) == 1
        if scenario in ("inline", "inline-send-fail"):
            inline, = rows(result.stdout, "inline")
            assert inline == {"real_receive_free": "1", "consumed_before_send_return": "0"}
        if scenario in ("no-ticket", "stale-ticket", "address-reuse"):
            tickets = rows(result.stdout, "ticket")
            assert len(tickets) == expected_calls
            assert all(ticket["snapshot_unchanged"] == "1" for ticket in tickets)
    retained = int(scenario in ("send-fail", "request-free-fail", "ack-free-fail", "wrong-thread"))
    assert int(scope["retained_explicitly_destroyed"]) == retained
