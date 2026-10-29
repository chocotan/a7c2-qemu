# SPDX-License-Identifier: MIT
"""Component-only real core + real guest owner; capture_verified=false.

HOST_TEST substitutes only the bridge transport and independent OSAL allocations.
State128, Vdf160/Zebra168/Layout192/Display176/BB192/Hist1192, RGB rendering/copy/readback/retirement and owner ACK validation
come from the real components. This does not verify original AP, mailbox/RSP,
CP/ASIC, VM, encoding acceptance, MPR/Fsys, or end-to-end capture. The readiness
guard returns host-fixture 1; it does not prove the native all13/resource guard.
No media files are written; the pending-JPEG rejection case encodes only in RAM.
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


LEGACY_SCENARIOS = ("enabled-opaque", "disable-enable", "corrupt-result", "zebra-mixed", "corrupt-zebra")
LAYOUT_SCENARIOS = (
    "layout-mixed", "layout-mixed-address-reuse", "layout-fresh-request-lease", "layout-no-route", "layout-disabled",
    "layout-geometry-width", "layout-geometry-height", "layout-result-used", "layout-result-length",
    "layout-result-instance", "layout-result-metadata-instance", "layout-result-input-fnv",
) + tuple(f"layout-body-{offset}" for offset in range(32)) + tuple(
    f"layout-tail-{offset}" for offset in range(32)
)
LAYOUT_BODY = bytes.fromhex("07010100000000008002e0010000000000000000000000000300000000000000")
DISPLAY_SCENARIOS = (
    "display-mixed", "display-mixed-address-reuse", "display-fresh-request-lease", "display-small-frame", "display-palette-variants",
    "display-no-active", "display-disabled", "display-unsupported", "display-malformed-envelope",
    "display-peaking-result-tail", "display-peaking-result-input-fnv",
    "display-flag-result-tail", "display-flag-result-input-fnv", "display-flag-result-length",
    "display-flag-result-borrowed", "refresh-global-queue", "refresh-legacy-queue",
)
DISPLAY_ACKS = {"0141": "0d2041110c00018000005900", "0152": "0d2052110c00018000005900", "0162": "0d2062110c00018000005900"}
DISPLAY_PALETTES = (bytes((81, 90, 240)), bytes((210, 16, 146)), bytes((29, 255, 83)), bytes((235, 128, 128)))


BB_SCENARIOS = (
    "bb-mixed", "bb-observed-initial", "bb-mixed-address-reuse", "bb-fresh-request-lease", "bb-repeated-banks",
    "bb-no-route", "bb-sq-enabled", "bb-look-nonneutral", "bb-input-domain", "bb-gain-nonzero",
    "bb-interval-enabled", "bb-wrong-source", "bb-small-capacity", "bb-no-frame",
    "bb-result-canonical", "bb-result-class", "bb-pending-jpeg", "bb-active-video",
)
HISTOGRAM_SCENARIOS = (
    "hist-mixed", "hist-address-reuse", "hist-arbitrary-queue", "hist-reenable", "hist-no-queue",
    "hist-wrong-source", "hist-no-route", "hist-mode0", "hist-disable", "hist-small-capacity",
    "hist-result-canonical", "hist-result-class", "hist-no-receive", "hist-free-before-receive",
    "hist-no-notification-free", "hist-request-free-fail", "hist-ack-free-fail", "hist-notification-free-fail",
)
BB_COMMANDS = ("0111", "0166", "0167", "015f", "0128")
BB_INPUTS = tuple(bytes.fromhex(value).ljust(32, b"\0") for value in (
    "11011c0000000f02", "66011c000001", "670102000100", "5f010400", "28010c00000100003c00000000000000",
))
BB_REQUESTS = tuple(bytes.fromhex(value).ljust(size, b"\0") for value, size in (
    ("0d2011012400018000000f02", 36), ("0d206601240001800001", 36),
    ("0d2067010a0001800100", 10), ("0d205f010c00018000000000", 12),
    ("0d20280114000180000100003c00000000000000", 20),
))
MIXED_ROUTE = bytes.fromhex("010505ab02adaeafb0b1b2b3b4000000")


@pytest.fixture(scope="module", params=("normal", "sanitized"))
def integration_binary(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("functional-vdf-integration-" + request.param)
    binary = directory / "functional-vdf-integration"
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=10))
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "sanitized" else []
    built = subprocess.run([
        *shlex.split(os.environ.get("CC", "cc")), "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra",
        "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-pthread", *flags, str(HERE / "device-models/functional-vdf-path.c"),
        str(HERE / "device-models/functional-vdf-layout-stage.c"),
        str(HERE / "device-models/functional-histogram.c"),
        str(HERE / "device-models/test-functional-vdf-integration.c"),
        *(str(REPORT / source) for source in SOURCES), *libraries, "-lm", "-o", str(binary),
    ], cwd=directory, capture_output=True, text=True, timeout=90)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def check_allocation_lifetimes(stdout, scenario):
    row, = (dict(item.split("=", 1) for item in line.split()[1:])
            for line in stdout.splitlines() if line.startswith("allocation_lifetimes "))
    assert row["allocations"] == row["request_frees"] == row["ack_frees"]
    assert row["arena_allocations"] == row["arena_frees"]
    if scenario.endswith("fresh-request-lease"):
        expected = 18 if scenario.startswith("bb-") else 6 if scenario.startswith("display-") else 2
        assert int(row["arena_allocations"]) == expected
        assert int(row["retired_request_reuses"]) >= expected // 2


def test_early_stage_real_layout_integration(integration_binary):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    result = subprocess.run([str(integration_binary), "early-stage-real-layout"], cwd=integration_binary.parent,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"component-only early stage + real layout\n{result.stdout}\n{result.stderr}"
    assert "capture_verified=false" in result.stdout
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    check_allocation_lifetimes(result.stdout, "early-stage-real-layout")
    stages = [dict(item.split("=", 1) for item in line.split()[1:])
              for line in result.stdout.splitlines() if line.startswith("early_stage generation=")]
    assert [int(row["generation"]) for row in stages] == [1, 2, 3]
    layout_fnv = 14695981039346656037
    for byte in LAYOUT_BODY:
        layout_fnv = ((layout_fnv ^ byte) * 1099511628211) & 0xffffffffffffffff
    for row in stages:
        assert row["source"] == "81cf0012"
        assert row["bank_fnv"] == row["readback_fnv"] == f"{layout_fnv:016x}"
        assert all(row[field] == "1" for field in (
            "stage_only", "core_state_unchanged", "proof_unchanged", "same_tid", "actual_request_free", "actual_ack_free"))
        assert row["semantic_applied"] == row["frame_consumed"] == row["bridge_calls"] == "0"
    assert "layout_ack_stage_matches=0 staged_bank_unchanged=1 applied_before_bind=0" in result.stdout
    applied, = (dict(item.split("=", 1) for item in line.split()[1:])
                for line in result.stdout.splitlines() if line.startswith("early_stage_applied "))
    assert applied["stage_generation"] == applied["config"] == applied["frame"] == "3"
    assert applied["instance"] == "00000000009a1701" and int(applied["lease"]) > 0
    assert applied["input_fnv"] == f"{layout_fnv:016x}"
    assert applied["source_fnv"] == applied["sink_fnv"] and int(applied["source_fnv"], 16)
    assert int(applied["active_bytes"]) == 640 * 480 * 3
    assert applied["stage_only"] == applied["applied_verified"] == applied["applied_semantic"] == applied["applied_frame"] == "1"
    assert applied["semantic_applied"] == applied["frame_consumed"] == "0"
    assert applied["bind_rejections"] == "4" and applied["staged_bank_unchanged"] == "1"
    assert applied["init_calls"] == "1" and applied["path_calls"] == "2"
    model192 = bytes.fromhex(applied["result192"])
    assert len(model192) == 192 and model192[160:] == LAYOUT_BODY
    result_fnv = 14695981039346656037
    for byte in model192:
        result_fnv = ((result_fnv ^ byte) * 1099511628211) & 0xffffffffffffffff
    assert applied["result_fnv"] == f"{result_fnv:016x}"
    assert int.from_bytes(model192[40:48], "little") == layout_fnv


@pytest.mark.parametrize("scenario", LEGACY_SCENARIOS + LAYOUT_SCENARIOS)
def test_real_core_guest_vdf_integration(integration_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    result = subprocess.run([str(integration_binary), scenario], cwd=integration_binary.parent,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"component-only scenario={scenario}\n{result.stdout}\n{result.stderr}"
    assert "capture_verified=false" in result.stdout
    check_allocation_lifetimes(result.stdout, scenario)
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    if scenario.startswith("layout-"):
        rejected_before_completion = scenario.startswith("layout-body-") or scenario in (
            "layout-no-route", "layout-disabled", "layout-geometry-width", "layout-geometry-height",
        )
        if rejected_before_completion:
            assert "core_state_unchanged=1 proof_unchanged=1 ack_delta=0" in result.stdout
            assert f"guest_unchanged={int(not scenario.startswith('layout-geometry-'))}" in result.stdout
        else:
            assert "layout192 " in result.stdout
            assert "config=4 frame=4 rendered=4 consumed=3 retired=4 init_calls=1" in result.stdout
            layout_fnv = 14695981039346656037
            for byte in LAYOUT_BODY:
                layout_fnv = ((layout_fnv ^ byte) * 1099511628211) & 0xffffffffffffffff
            assert f"input_fnv={layout_fnv:016x}" in result.stdout
            completed = 3 if scenario in ("layout-mixed", "layout-mixed-address-reuse", "layout-fresh-request-lease") else 2
            assert f"requests={completed} completed_cycles={completed}" in result.stdout
            assert f"same_ack_address={int(scenario == 'layout-mixed-address-reuse')}" in result.stdout
            if completed == 2:
                assert "core_bytes=192 guest_rc=-71 ack_delta=0" in result.stdout


@pytest.mark.parametrize("scenario", DISPLAY_SCENARIOS)
def test_real_core_guest_display_integration(integration_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    result = subprocess.run([str(integration_binary), scenario], cwd=integration_binary.parent,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"component-only scenario={scenario}\n{result.stdout}\n{result.stderr}"
    assert "capture_verified=false" in result.stdout
    check_allocation_lifetimes(result.stdout, scenario)
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    receipts = [dict(item.split("=", 1) for item in line.split()[1:])
                for line in result.stdout.splitlines() if line.startswith("display176 ")]
    for receipt in receipts:
        command = receipt["command"]
        assert receipt["ack_wire"] == DISPLAY_ACKS[command]
        typed = bytes.fromhex(receipt["canonical_display16"])
        assert len(typed) == 16 and int.from_bytes(typed[:4], "little") == int(command, 16)
        body_bytes = 8 if command == "0152" else 2 if command == "0162" else 0
        assert int.from_bytes(typed[4:8], "little") == body_bytes
        if command == "0152":
            assert typed[8:10] == b"\x03\x00" and typed[10] <= 2
            assert typed[11] in (0, 10, 40) and typed[12] == 0 and typed[13:] in DISPLAY_PALETTES
        else:
            assert typed[8:] == bytes(8)
        input_fnv = 14695981039346656037
        for byte in typed:
            input_fnv = ((input_fnv ^ byte) * 1099511628211) & 0xffffffffffffffff
        assert receipt["input_fnv"] == f"{input_fnv:016x}"
        assert int(receipt["source_fnv"], 16) and receipt["source_fnv"] == receipt["sink_fnv"]
        width, height = (96, 64) if scenario == "display-small-frame" else (640, 480)
        assert int(receipt["active_bytes"]) == width * height * 3
        assert receipt["same_tid"] == receipt["actual_free"] == receipt["stale_ticket_rejected"] == "1"
    if "-result-" in scenario:
        assert "core_bytes=176 guest_rc=-71 ack_delta=0" in result.stdout
        assert "core_commits=1 extra_config=0 extra_frame=0 extra_proof=0" in result.stdout
        assert len(receipts) == int("-flag-" in scenario)
        generation = 6 if "-flag-" in scenario else 5
        assert f"config={generation} frame={generation} ack_delta=0" in result.stdout
    elif scenario in ("display-no-active", "display-disabled", "display-unsupported", "display-malformed-envelope"):
        assert not receipts
        assert result.stdout.count("guest_unchanged=1 ack_delta=0") == 2
        assert result.stdout.count("core_state_unchanged=1 proof_unchanged=1") >= 2
        if scenario == "display-unsupported":
            assert result.stdout.count("core_rc=-95 guest_rc=-22") == 2
        elif scenario == "display-malformed-envelope":
            assert result.stdout.count("core_rc=-22 guest_rc=-61") == 2
            assert "typed_envelope_rejections=5" in result.stdout
        else:
            assert result.stdout.count("core_rc=-61 guest_rc=-61") == 2
    elif scenario in ("refresh-global-queue", "refresh-legacy-queue"):
        queue_source = "80946189" if scenario == "refresh-global-queue" else "81cf0012"
        assert len(receipts) == 2 and all(receipt["command"] == "0141" for receipt in receipts)
        assert all(receipt["canonical_display16"] == "41010000000000000000000000000000" for receipt in receipts)
        assert all(receipt["refresh_queue_bound"] == "1" and
                   receipt["origin_source"] == receipt["refresh_queue_source"] == queue_source for receipt in receipts)
        assert "refresh global_D_reused=1 paired_wait_delayed_by_INIT=1 config=4 rendered=4 consumed=3" in result.stdout
        assert (f"refresh_queue_bound=1 refresh_queue_source={queue_source} unbound_rejections=2 bound_source_rejections=3 "
                "bind_core_state_unchanged=1 bind_proof_unchanged=1") in result.stdout
    else:
        extra = 3 if scenario == "display-palette-variants" else 0
        frames = 6 + extra
        configs = frames + int(scenario == "display-small-frame")
        assert len(receipts) == 2 + extra
        assert [receipt["command"] for receipt in receipts[:2]] == ["0152", "0162"]
        assert receipts[0]["canonical_display16"] == "52010000080000000300010000eb8080"
        assert receipts[1]["canonical_display16"] == "62010000020000000000000000000000"
        if extra:
            assert {bytes.fromhex(receipt["canonical_display16"])[13:] for receipt in receipts
                    if receipt["command"] == "0152"} == set(DISPLAY_PALETTES)
        assert (f"display_sequence config={configs} frame={frames} rendered={frames} consumed={frames - 1} "
                f"retired={frames} proof_serial={frames} init_calls=1 requests={5 + extra} completed_cycles={5 + extra}") in result.stdout
        assert f"same_ack_address={int(scenario == 'display-mixed-address-reuse')} stale_across_commands=1" in result.stdout
        assert "instance=00000000009a1701" in result.stdout
        assert "physical_asic_verified=false original_ap_verified=false" in result.stdout


def fnv64(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def rows(stdout, prefix):
    return [dict(item.split("=", 1) for item in line.split()[1:])
            for line in stdout.splitlines() if line.startswith(prefix + " ")]


def check_fixed_bytes(data, typed, receipt_class, config, frame):
    expected = bytearray(len(data))
    struct.pack_into("<IIQQQQQ", expected, 0, 1, len(data), 0x9a1701, config, frame,
                     int.from_bytes(data[32:40], "little"), fnv64(typed))
    source_hash = int.from_bytes(data[48:56], "little")
    assert source_hash and data[48:56] == data[56:64]
    struct.pack_into("<QQQ14I", expected, 48, source_hash, source_hash, 921600,
                     640, 480, 1920, 0x90590819, 1, 1, receipt_class, 1, 1, 1, 1, 1, 0, 0)
    expected[128:144] = MIXED_ROUTE
    struct.pack_into("<QQ", expected, 144, frame - 1, config - 1)
    expected[160:160 + len(typed)] = typed
    assert int.from_bytes(data[32:40], "little") > 0
    if len(data) == 1192:
        expected[168:] = data[168:]
    assert data == expected


@pytest.mark.parametrize("scenario", BB_SCENARIOS + HISTOGRAM_SCENARIOS)
def test_real_core_guest_bb_histogram_integration(integration_binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    result = subprocess.run([str(integration_binary), scenario], cwd=integration_binary.parent,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, f"component-only scenario={scenario}\n{result.stdout}\n{result.stderr}"
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    assert "capture_verified=false" in result.stdout
    check_allocation_lifetimes(result.stdout, scenario)
    bb_receipts = rows(result.stdout, "bb192")
    expected_bb = 0 if scenario in ("bb-no-route", "hist-no-route") else 10 if scenario == "bb-repeated-banks" else 5
    assert len(bb_receipts) == expected_bb
    for index, receipt in enumerate(bb_receipts):
        slot = index % 5
        assert receipt["command"] == BB_COMMANDS[slot]
        typed, wire = bytearray(BB_INPUTS[slot]), bytearray(BB_REQUESTS[slot])
        if scenario == "bb-observed-initial" and slot == 1:
            body = bytes.fromhex("00010000000000000000000008000000070000000100000001000000")
            typed[4:] = wire[8:] = body
        if index >= 5 and slot == 2:
            typed[4] = wire[8] = 0
        if index >= 5 and slot == 4:
            typed[8] = wire[12] = 9
        assert bytes.fromhex(receipt["canonical32"]) == typed
        assert bytes.fromhex(receipt["request_wire"]) == wire
        assert receipt["ack_wire"] == f"0d20{BB_COMMANDS[slot][2:]}110c00018000000000"
        assert receipt["input_fnv"] == f"{fnv64(typed):016x}"
        assert receipt["class"] == receipt["proof_kind"] == "5"
        assert receipt["origin_source"].startswith("81cf") and receipt["active_bytes"] == "921600"
        assert all(receipt[key] == "1" for key in (
            "actual_request_free", "actual_ack_free", "same_tid", "independent_lease", "full_result_verified"))
        assert int(receipt["cycle"]) == 7 + index
        assert int(receipt["config"]) == int(receipt["frame"]) == int(receipt["proof_serial"]) == 8 + index
        check_fixed_bytes(bytes.fromhex(receipt["result192"]), typed, 5, 8 + index, 8 + index)
    if scenario.startswith("bb-"):
        if scenario in ("bb-pending-jpeg", "bb-active-video"):
            assert "BB_and_histogram_refused=1 pending_work_preserved=1 media_disk_writes=0" in result.stdout
            assert "reason=hist-core-busy guest_rc=-16 reached_core=1" in result.stdout
        elif scenario.startswith("bb-result-"):
            assert "core_bytes=192 guest_rc=-71 ack_delta=0" in result.stdout
        elif scenario not in ("bb-mixed", "bb-observed-initial", "bb-mixed-address-reuse", "bb-fresh-request-lease", "bb-repeated-banks"):
            assert len(rows(result.stdout, "bb_refused")) == 1
            assert "core_state_unchanged=1 proof_unchanged=1" in result.stdout
        else:
            summary, = rows(result.stdout, "bb_sequence")
            total = 17 if scenario == "bb-repeated-banks" else 12
            assert all(int(summary[key]) == total for key in ("config", "frame", "rendered", "retired", "proof_serial"))
            assert int(summary["consumed"]) == total - 1
            assert int(summary["requests"]) == int(summary["completed_cycles"]) == total - 1
        return
    hist_receipts = rows(result.stdout, "histogram1192")
    refused = scenario in ("hist-no-queue", "hist-wrong-source", "hist-no-route", "hist-mode0", "hist-disable",
                           "hist-small-capacity", "hist-result-canonical", "hist-result-class")
    if refused:
        assert not hist_receipts and len(rows(result.stdout, "histogram_refused")) == 1
        assert "ack_delta=0" in result.stdout and "AP_consumed=0" in result.stdout
        return
    receipt, = hist_receipts
    core = bytes.fromhex(receipt["result1192"])
    notification = bytes.fromhex(receipt["notification1034"])
    assert len(core) == 1192 and len(notification) == 1034
    assert receipt["request_wire"] == "0d2048010c00018001010000"
    assert receipt["canonical8"] == "4801040001010000" and receipt["ack_wire"] == "0d2048110c00018000005900"
    assert notification[:10] == bytes.fromhex("0d200c210a0401800100") and notification[10:] == core[168:]
    assert core[160:168] == bytes.fromhex(receipt["canonical8"])
    assert receipt["proof_kind"] == receipt["class"] == "6" and receipt["selector"] == "1"
    assert receipt["full_result_verified"] == receipt["full_notification_verified"] == "1"
    assert receipt["source_fnv"] == receipt["sink_fnv"] == receipt["reference_fnv"]
    assert int(receipt["source_fnv"], 16) and receipt["active_bytes"] == "921600"
    assert receipt["result_fnv"] == f"{fnv64(core):016x}" and receipt["notification_fnv"] == f"{fnv64(notification):016x}"
    for index, channel in enumerate(("Y", "R", "G", "B")):
        bins = notification[10 + 256 * index:10 + 256 * (index + 1)]
        assert max(bins) == 255 and receipt[channel + "_fnv"] == f"{fnv64(bins):016x}"
    assert receipt["config"] == receipt["frame"] == receipt["proof_serial"] == receipt["rendered"] == receipt["retired"] == "13"
    assert receipt["consumed"] == "12"
    assert receipt["queue_source"] == ("7351a2b7" if scenario == "hist-arbitrary-queue" else "8094a2b7")
    check_fixed_bytes(core, bytes.fromhex(receipt["canonical8"]), 6, 13, 13)
    life, = rows(result.stdout, "histogram_lifetimes")
    cleanup, = rows(result.stdout, "histogram_cleanup")
    retained = {
        "hist-no-receive": 2, "hist-free-before-receive": 2, "hist-no-notification-free": 1,
        "hist-request-free-fail": 1, "hist-ack-free-fail": 1, "hist-notification-free-fail": 2,
    }.get(scenario, 0)
    assert int(life["retained_leases"]) == int(cleanup["retained_allocations_explicitly_destroyed"]) == retained
    assert int(life["AP_consumed"]) == int(cleanup["owner_consumption_unchanged"]) == int(retained == 0)
    assert all(int(life[key]) <= 1 for key in ("request_free_calls", "ack_free_calls", "notification_free_calls"))
    assert int(life["allocations"]) == int(life["sends"]) == (0 if scenario == "hist-request-free-fail" else 2)
    if scenario == "hist-address-reuse":
        assert life["request_ack_same_address"] == "1"
    if retained == 0:
        assert life["request_freed"] == life["ack_freed"] == life["notification_freed"] == "1"
        assert life["ticket_ack"] == life["ticket_notification"] == "1"
        thread, = rows(result.stdout, "histogram_threads")
        assert all(value == "1" for value in thread.values())
    if scenario == "hist-reenable":
        assert "reenable_disable_mode0_rejections=3 core_state_unchanged=1 proof_unchanged=1 extra_ACK=0" in result.stdout


