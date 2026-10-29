# SPDX-License-Identifier: MIT
# gpt-6.1-sol, thinking=max. Host-focused execution authorized for central fixes.
"""The new C adapter + real bridge/model; SDK methods are explicit host fixtures."""
import hashlib
import io
import importlib.util
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import struct
import subprocess

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REPORT = ROOT / "report"
PINS = REPORT / "functional-jpeg-codec/source-pins.json"
STRICT = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
ENV = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1:quarantine_size_mb=64",
           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_bytes(raw, segments, address, size):
    assert size > 0 and address >= 0
    matches = [s for s in segments if s["vaddr"] <= address and
               address + size <= s["vaddr"] + s["filesz"]]
    assert len(matches) == 1
    segment, = matches
    offset = segment["offset"] + address - segment["vaddr"]
    result = raw[offset:offset + size]
    assert len(result) == size
    return result


def test_exact_public_source_abi_and_interposition_pins():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from elftools.elf.elffile import ELFFile
    pins = json.loads(PINS.read_text())
    assets = {}
    for name, asset in pins["assets"].items():
        path = HERE / "menu-root" / asset["path"]
        if not path.exists():
            pytest.skip("public ALLLANG assets are not prepared")
        raw = path.read_bytes()
        assert len(raw) == asset["size"] and sha(raw) == asset["sha256"]
        if asset["kind"].startswith("ELF"):
            elf = ELFFile(io.BytesIO(raw))
            actual = [{k: s["p_" + k] for k in ("offset", "vaddr", "filesz", "memsz", "flags")}
                      for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"]
            assert actual == asset["segments"]
            symbols = elf.get_section_by_name(".dynsym")
            for symbol in asset["symbols"]:
                found, = symbols.get_symbol_by_name(symbol["name"])
                assert (found["st_value"], found["st_size"]) == (symbol["address"], symbol["bytes"])
            for anchor in asset["relocations"]:
                section = elf.get_section_by_name(anchor["section"])
                found = [r for r in section.iter_relocations() if r["r_offset"] == anchor["offset"]]
                relocation, = found
                assert relocation["r_info_type"] == anchor["type"]
                assert relocation["r_addend"] == anchor["addend"]
                assert symbols.get_symbol(relocation["r_info_sym"]).name == anchor["symbol"]
        assets[name] = raw
    disassembler = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for pin in pins["windows"]:
        asset = pins["assets"][pin["asset"]]
        if asset["kind"] == "raw":
            value = assets[pin["asset"]][pin["address"]:pin["address"] + pin["bytes"]]
        else:
            value = source_bytes(assets[pin["asset"]], asset["segments"], pin["address"], pin["bytes"])
        assert len(value) == pin["bytes"] and sha(value) == pin["sha256"]
    for pin in pins["instructions"]:
        asset = pins["assets"][pin["asset"]]
        value = source_bytes(assets[pin["asset"]], asset["segments"], pin["address"], 4)
        instruction, = disassembler.disasm(value, pin["address"])
        assert [instruction.mnemonic, instruction.op_str] == pin["instruction"]
    # Check the runtime's complete function fingerprints against actual public code,
    # including the common caller functions; a changed instruction cannot reuse a pin.
    runtime = (HERE / "functional-jpeg-codec.c").read_text()
    runtime_pins = re.findall(
        r"PIN\(\w+, (a->base|dataflow), (0x[0-9a-f]+), (0x[0-9a-f]+|\d+), (0x[0-9a-f]+)\)", runtime)
    assert len(runtime_pins) == 17
    for module, address, count, expected in runtime_pins:
        asset = "I" if module == "a->base" else "D"
        value = source_bytes(assets[asset], pins["assets"][asset]["segments"], int(address, 0), int(count, 0))
        fingerprint = 14695981039346656037
        for byte in value:
            fingerprint = ((fingerprint ^ byte) * 1099511628211) & ((1 << 64) - 1)
        assert fingerprint == int(expected, 0)
    contract = pins["main_contract"]
    for pin in contract["runtime_scheduler_pins"]:
        value = source_bytes(assets["I"], pins["assets"]["I"]["segments"], pin["address"], pin["bytes"])
        fingerprint = 14695981039346656037
        for byte in value:
            fingerprint = ((fingerprint ^ byte) * 1099511628211) & ((1 << 64) - 1)
        assert fingerprint == int(pin["runtime_fnv1a64"], 16)
        assert f"UINT64_C(0x{fingerprint:016x})" in runtime
    assert contract["ack_expected_result"] == 0 and contract["ack_terminal"] is False
    assert contract["original_main_object_bytes"] == contract["original_comp_object_bytes"] == 0x28
    assert [(s["selector"], s["add_soi"]) for s in contract["selectors"]] == [(0, 0), (1, 1), (2, 0)]
    assert contract["native_reply_free_rc_tracked"] is False
    assert contract["main_state_geometry_fallback"] is False
    assert contract["cross_selector_same_sensor_frame_verified"] is False
    assert contract["comp_previous_ack_same_argument_address"] is True
    assert contract["original_main_execution_verified"] is False
    command = pins["bounded_kuna"]["command"]
    assert command.count("--addr") == 5 and "--raw-image" not in command and "--no-vars" in command
    assert int(command[command.index("--max-fn-seconds") + 1]) <= 8
    assert pins["capture_verified"] is False and pins["physical_asic_compatible"] is False


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("functional-jpeg-codec")
    cc = shlex.split(os.environ.get("CC", "cc"))
    libraries = shlex.split(subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=10))
    dependencies = [REPORT / name for name in (
        "functional-camera-core/functional-camera-core.c", "virtual-optics/optics.c",
        "virtual-optical-frame-owner/optical-frame-owner.c", "virtual-jpeg-hardware/jpeg-hardware.c",
        "virtual-jpeg-hardware/jpeg-hardware-codec.c", "virtual-jpeg-sos/jpeg-sos.c",
        "virtual-video-engine/video-engine.c", "virtual-camera-pipeline/camera-pipeline.c")]
    subprocess.run(cc + STRICT + ["-fsyntax-only", str(HERE / "functional-jpeg-codec.c")],
                   check=True, capture_output=True, timeout=30)
    cross = shutil.which("aarch64-linux-gnu-gcc")
    if cross:
        subprocess.run([cross] + STRICT + ["-fPIC", "-c", str(HERE / "functional-jpeg-codec.c"),
                       "-o", str(directory / "functional-jpeg-codec-aarch64.o")],
                       check=True, capture_output=True, timeout=30)
    result = {}
    for mode, options in (
            ("normal", ["-O2"]),
            ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                           "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"])):
        executable = directory / mode
        subprocess.run(cc + STRICT + options + ["-DFJPEG_HOST_TEST",
                       str(HERE / "functional-jpeg-codec.c"), str(HERE / "test-functional-jpeg-codec.c")] +
                       list(map(str, dependencies)) + libraries + ["-pthread", "-ldl", "-lm", "-o", str(executable)],
                       check=True, capture_output=True, timeout=90)
        result[mode] = executable
    return result


def run(builds, mode, scenario):
    environment = dict(ENV)
    if 'free-reuse' in scenario:
        environment['ASAN_OPTIONS'] += ':quarantine_size_mb=0:thread_local_quarantine_size_kb=0'
    process = subprocess.run([str(builds[mode]), scenario], capture_output=True, env=environment, timeout=60)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    return process.stdout


def blobs(data):
    source = io.BytesIO(data)
    result = {}
    while line := source.readline():
        tag, name, size = line.split()
        assert tag == b"BLOB"
        value = source.read(int(size))
        assert len(value) == int(size)
        result[name.decode()] = value
    return result


def decoded(data):
    image = Image.open(io.BytesIO(data))
    image.load()
    assert image.format == "JPEG"
    return image


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
def test_actual_codec_stdout_free_receipts_and_real_model_bytes_join_checker(builds, mode, tmp_path):
    # HOST_TEST only: original SDK methods/caller PCs, broker and Fsys are fixtures.
    # Packet/free/lease bytes and RGB/encoder proof below come from the actual C run.
    process = subprocess.run([str(builds[mode]), 'main-stream'], capture_output=True,
                             env=dict(ENV, FJPEG_HOST_RECEIPTS='1'), timeout=60)
    assert process.returncode == 0, process.stderr.decode(errors='replace')
    records = blobs(process.stdout)
    path = REPORT / 'functional-camera-evidence/test_evidence.py'
    spec = importlib.util.spec_from_file_location('jpeg_host_evidence_fixture', path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    checker = fixture.checker
    rows = checker.parse_console(records['HOST_TEST_RECEIPTS'])
    request = next(row['fields'] for row in rows if row['fields']['operation'] == 'original-request')
    output = next(row['fields'] for row in rows if row['fields']['operation'] == 'output-readback')
    base = int(request['original_base'], 0)
    for row in rows:
        fields = row['fields']
        if fields['operation'] in ('enable', 'shutdown'):
            continue
        fields['caller'] = hex(base + 0x13b6ec)
        if 'callback_caller' in fields:
            fields['callback_caller'] = hex(base + 0x13b788)
        if 'comp_caller' in fields:
            fields['comp_caller'] = hex(base + 0x13b7e0)
    values = struct.unpack('<28Q4q15Q', records['HOST_TEST_FRAME_PROOF'])
    names = ('version struct_bytes serial model_instance model_lifetime owner_pid opcode consumer_kind '
             'config_generation frame_generation lease_generation packet_generation width height stride active_bytes '
             'source_fnv1a64 consumer_before_fnv1a64 consumer_after_fnv1a64 render_observed consumer_entered '
             'consumer_returned encoder_consumed retired source_state consumer_before_state consumer_after_state final_state '
             'render_status consumer_status retire_status operation_status').split()
    proof = dict(zip(names, values[:32]))
    counts = ('rendered', 'consumed', 'jpeg_encoded', 'video_encoded', 'retired')
    proof.update(before=dict(zip(counts, values[32:37])), after=dict(zip(counts, values[37:42])))
    proof.update(zip(('encoded_bytes', 'encoded_fnv1a64', 'result_bytes', 'result_fnv1a64', 'result_token'), values[42:]))
    assert proof['result_fnv1a64'] == checker.fnv(records['MODEL_JPEG'])
    origin = {key: int(request[key], 0) for key in ('source', 'destination', 'command')}
    origin.update(producer_tid=int(output['tid']), bytes=104, fnv1a64=int(request['trigger_fnv'], 16))
    operation = dict(op=16, data=struct.pack('<4I', 1, proof['width'], proof['height'], 90),
                     output=records['MODEL_JPEG'], origin=origin, proof=proof, token=proof['result_token'])
    init_state = bytearray(128)
    struct.pack_into('<2I', init_state, 0, 1, 15)
    struct.pack_into('<Q', init_state, 48, proof['model_instance'])
    args = fixture.host_test_transport(tmp_path, [dict(op=1, data=b'', output=bytes(init_state)), operation],
                                       guest_pid=int(request['pid']), model_instance=proof['model_instance'])
    transport = checker.check_transport(*args)
    tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 16)
    # The independent fixture transport line occupies the actual C worker lifetime.
    tx['line'] = next(row['line'] for row in rows if row['fields']['operation'] == 'output-readback')
    for row in rows:
        row['line'] *= 2
    tx['line'] = tx['line'] * 2 - 1
    storage_run, _ = fixture.host_test_storage(tmp_path, records['MODEL_JPEG'])
    storage = checker.writeback.inspect(storage_run)
    result = checker.check_jpeg(rows, transport, storage, args[0])
    assert result['verified'] and result['actual_reply_free_verified']
    assert args[1]['evidence_class'] == 'HOST_TEST'
    assert checker.finish_verdict(dict(evidence={}, missing=[], products={'JPEG': {}, 'MP4': {}}), args[1])['capture_verified'] is False


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", ["off", "fork", "missing", "request", "alias", "range"])
def test_default_off_original_delegation_and_request_ownership(builds, mode, scenario):
    assert run(builds, mode, scenario) == b""


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", ["readback", "stale", "backend", "length", "shape"])
def test_backend_or_lease_errors_reach_original_error_handler(builds, mode, scenario):
    records = blobs(run(builds, mode, scenario))
    assert set(records) == {"STATE"}
    assert len(records["STATE"]) == 128


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", ["callback", "source", "cookie", "duplicate", "unobserved", "send"])
def test_completion_requires_actual_queue_observation_and_native_caller(builds, mode, scenario):
    assert run(builds, mode, scenario) == b""


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", ["receipt-release", "receipt-request-release"])
def test_failed_native_lease_release_retains_ownership(builds, mode, scenario):
    assert run(builds, mode, scenario) == b""


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", ["stream", "full", "fallback", "busy", "wide", "chunks",
                                      "receipt-wire", "receipt-thread"])
def test_real_bridge_chunks_original_stream_layout_and_independent_decode(builds, mode, scenario):
    records = blobs(run(builds, mode, scenario))
    full, stream = records["MODEL_JPEG"], records["SDK_STREAM"]
    assert full[:6] == b"\xff\xd8\xff\xdb\x00\x84"
    assert full[575:577] == b"\xff\xda" and full[-2:] == b"\xff\xd9"
    expected = {"fallback": (640, 480), "wide": (8192, 16), "chunks": (2048, 1536)}.get(scenario, (1280, 720))
    if scenario == "chunks":
        assert len(full) > 65024
    if scenario == "full":
        assert stream == full
    else:
        assert stream == full[2:] and stream[:2] == b"\xff\xdb"
        stream = b"\xff\xd8" + stream
    original, consumer = decoded(full), decoded(stream)
    assert original.size == consumer.size == expected
    assert original.tobytes() == consumer.tobytes()
    assert len(set(original.convert("RGB").tobytes())) > 20
    offset = 0x68 if scenario == "full" else 0x5C
    assert struct.unpack_from("<I", records["NATIVE_CONFIG"], offset)[0] == len(records["SDK_STREAM"])
    state = records["STATE"]
    assert struct.unpack_from("<QQQ", state, 64) == (2, 1, 1)
    assert struct.unpack_from("<Q", state, 96)[0] >= len(full)


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", [
    "main-off", "main-fork", "main-short-object", "main-dmm-failed", "main-dmm-short",
    "main-noaccess-object", "main-noaccess-trigger",
    "main-bad-trigger", "main-vptr", "main-selector", "main-caller", "main-range",
    "main-quality", "main-option", "main-option2", "main-soi", "main-zero", "main-primary",
    "main-screen-zero", "main-screen-primary", "main-primary-mismatch",
    "main-overflow", "main-malformed", "main-request-size", "main-missing", "main-alias",
    "main-lease-offset", "main-readonly", "main-request-release",
])
def test_main_preconditions_original_abi_and_no_frame_on_refusal(builds, mode, scenario):
    assert run(builds, mode, scenario) == b""


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", [
    "main-before-ack", "main-no-comp", "main-comp-vptr", "main-comp-selector", "main-comp-caller",
    "main-comp-context", "main-comp-manager", "main-comp-control", "main-previous", "main-previous-copy",
    "main-config-readonly", "main-config-alias", "main-config-fields", "main-comp-fields-after",
    "main-ack-source", "main-ack-body", "main-unobserved", "main-callback",
    "main-done-source", "main-done-body", "main-wrong-object", "main-send", "main-send-done", "main-release",
    "main-native-length", "main-free-none", "main-free-fail", "main-free-tid", "main-free-destination",
    "main-free-none-done", "main-free-fail-done", "main-free-tid-done", "main-free-destination-done",
])
def test_main_requires_distinct_associated_native_comp_and_retains_failed_leases(builds, mode, scenario):
    assert run(builds, mode, scenario) == b""


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", ["main-backend", "main-readback", "main-stale", "main-length"])
def test_main_error_ack_returns_zero_until_original_error_done_cleans_up(builds, mode, scenario):
    records = blobs(run(builds, mode, scenario))
    assert set(records) == {"STATE"} and len(records["STATE"]) == 128


@pytest.mark.parametrize("mode", ["normal", "sanitized"])
@pytest.mark.parametrize("scenario", [
    "main-stream", "main-thumb", "main-screen", "main-q0", "main-q1", "main-q2", "main-q6",
    "main-small-object", "main-readonly-object", "main-rx-object", "main-split-object",
    "main-reentry", "main-comp-duplicate", "main-expired", "main-free-duplicate",
    "main-free-reuse", "main-free-fork",
])
def test_main_actual_bridge_bytes_original_config_store_and_independent_decode(builds, mode, scenario):
    records = blobs(run(builds, mode, scenario))
    full, stream = records["MODEL_JPEG"], records["SDK_STREAM"]
    selector = {"main-thumb": 1, "main-screen": 2}.get(scenario, 0)
    assert stream == (full if selector == 1 else full[2:])
    # Source Main/Screen omit SOI. Add it only to this independent in-memory decoder input.
    consumer = decoded(stream if selector == 1 else b"\xff\xd8" + stream)
    producer = decoded(full)
    expected = {1: (160, 120), 2: (640, 360)}.get(selector, (1280, 720))
    assert producer.size == consumer.size == expected
    assert producer.tobytes() == consumer.tobytes()
    assert len(set(consumer.convert("RGB").tobytes())) > 20
    offset = 0x5c + 12 * selector
    config, stable = records["NATIVE_CONFIG"], records["CONFIG_COPY"]
    assert len(config) == len(stable) == 0x78
    assert struct.unpack_from("<I", config, offset)[0] == len(stream)
    assert struct.unpack_from("<I", stable, offset)[0] == 4 * 1024 * 1024 - 64
    assert config[:offset] == stable[:offset] and config[offset + 4:] == stable[offset + 4:]
    assert struct.unpack_from("<QQQ", records["STATE"], 64) == (2, 1, 1)
