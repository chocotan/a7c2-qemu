"""Explicit initial-stage source binding; host only, no native CP startup claim."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

BASE = Path(__file__).resolve().parents[2]
MODELS = BASE / "runtime/analysis/device-models"
REPORT = BASE / "report/cp-property-repository-contract"
PINS = json.loads((REPORT / "source-pins.json").read_text())
ALH_PINS = json.loads((BASE / "report/lif-enable-input-contract/source-pins.json").read_text())


@pytest.fixture(params=[False, True], ids=["strict", "asan-ubsan"])
def executable(request, tmp_path):
    out = tmp_path / "cp-property-stage-test"
    cmd = [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
           "-pedantic", "-O1", "-g"]
    if request.param:
        cmd += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    cmd += [str(MODELS / name) for name in ["cp-property-stage.c",
            "cp-start-state-provider.c", "cp-start-state-data.c", "test-cp-property-stage.c"]]
    subprocess.run(cmd + ["-o", str(out)], check=True, capture_output=True, text=True)
    return out


def run(executable, *args):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    return subprocess.run([str(executable), *map(str, args)], check=True, env=env,
                          capture_output=True, text=True).stdout


def authenticated_assets():
    """Authenticate WHOLE files before selecting either source span."""
    paths = [BASE / PINS["CP_path"], BASE / PINS["public_seed_path"]]
    if not all(path.is_file() for path in paths):
        pytest.skip("public CP/ALLLANG assets not installed")
    cp, seed = (path.read_bytes() for path in paths)
    assert len(cp) == PINS["CP_bytes"]
    assert hashlib.sha256(cp).hexdigest() == PINS["CP_sha256"]
    assert len(seed) == PINS["public_seed_bytes"]
    assert hashlib.sha256(seed).hexdigest() == PINS["public_seed_sha256"]
    stage_pin = PINS["initial_stage"]
    stage = seed[stage_pin["ALLLANG_file_offset"]:]
    assert len(stage) == stage_pin["bytes"]
    assert hashlib.sha256(stage).hexdigest() == stage_pin["sha256"]
    return cp, seed, stage


def fnv1a64(blob):
    value = 14695981039346656037
    for byte in blob:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"{value:016x}"


def u32(blob, offset):
    return int.from_bytes(blob[offset:offset + 4], "little")


def test_guard_default_and_capacity_matrix(executable):
    assert "PASS cp-property-stage" in run(executable)


def test_authenticated_initial_stage_and_legacy_primary(executable, tmp_path):
    _, seed, stage = authenticated_assets()
    stage_path, primary_path = tmp_path / "initial-stage.bin", tmp_path / "file-zero-primary.bin"
    stage_path.write_bytes(stage)
    primary_path.write_bytes(seed[:968981])
    output = run(executable, stage_path, primary_path)
    assert "source=CP_INITIAL_STAGE repository=CP_PRIMARY mode=1 profile=0" in output
    context = bytes.fromhex(re.search(r"context=([0-9a-f]+)", output)[1])
    profile = PINS["initial_stage"]["profile"]
    assert len(context) == profile["bytes"] == 256
    assert context == stage[profile["payload_offset"]:profile["payload_offset"] + 256]
    assert hashlib.sha256(context).hexdigest() == profile["sha256"]
    alh = bytes.fromhex(re.search(r"alh=([0-9a-f]+)", output)[1])
    prop = ALH_PINS["public_property"]
    offset = int(prop["payload_stage_offset_hex"], 16)
    assert len(alh) == prop["payload_bytes"] == 256
    assert alh == stage[offset:offset + len(alh)]
    assert hashlib.sha256(alh).hexdigest() == prop["payload_sha256"]
    assert alh[int(prop["gate_byte_offset_hex"], 16)] == prop["gate_byte_value"] == 0xff
    assert "legacy_file_zero_primary=ENODATA no_fallback=1" in output
    assert "no_ready=1 native_CP=0" in output
    assert "PASS cp-property-stage" in output


def test_all_eight_original_source_windows():
    cp, _, _ = authenticated_assets()
    lo, hi = PINS["file_backed_CP_VA"]
    assert hi - lo == len(cp)
    assert len(PINS["pins"]) == 8
    assert sum(pin["size"] for pin in PINS["pins"]) == PINS["source_window_bytes"] == 726
    for pin in PINS["pins"]:
        va, end = pin["CP_VA"], pin["end_CP_VA"]
        assert lo <= va < end <= hi and end - va == pin["size"]
        offset = va - PINS["CP_VA_equals_raw_plus"]
        assert hashlib.sha256(cp[offset:offset + pin["size"]]).hexdigest() == pin["sha256"], pin["name"]


def test_exact_bk4_and_three_full_property_entries():
    cp, _, stage = authenticated_assets()
    pin = PINS["initial_stage"]
    assert stage[12:16] == b"BK4\0" and stage[9] == 0
    assert [u32(stage, offset) for offset in [16, 20, 24, 28]] == [
        pin["section_count"], pin["property_count"], pin["data_offset"], pin["data_bytes"]]
    assert pin["property_table_offset"] == 0x100 + 6 * pin["section_count"]
    assert sum(stage[:32]) + sum(stage[36:]) == u32(stage, 32) == int(pin["stored_checksum"], 16)
    assert fnv1a64(stage) == pin["fnv1a64"]
    section = pin["section_0125"]
    assert section["offset"] == 0x100 + (0x01250003 >> 16) * 6
    assert int.from_bytes(stage[section["offset"]:section["offset"] + 2], "little") == section["count"]
    assert u32(stage, section["offset"] + 2) == section["first_property"]
    for name in ["mode", "profile"]:
        prop = pin[name]
        full_id = int(prop["full_id"], 16)
        assert full_id >> 16 == 0x125
        assert prop["entry_offset"] == pin["property_table_offset"] + (section["first_property"] + (full_id & 0xffff)) * 6
        assert stage[prop["entry_offset"]:prop["entry_offset"] + 6].hex() == prop["entry_hex"]
        payload = stage[prop["payload_offset"]:prop["payload_offset"] + prop["bytes"]]
        assert len(payload) == prop["bytes"]
        assert hashlib.sha256(payload).hexdigest() == prop["sha256"]
    profile = pin["profile"]
    assert int.from_bytes(stage[profile["length_offset"]:profile["length_offset"] + 2], "little") == 256
    assert stage[profile["payload_offset"] + profile["profile_byte_offset"]] == 0
    prop = ALH_PINS["public_property"]
    assert prop["stage_sha256"] == pin["sha256"]
    full_id = int(prop["full_ID_hex"], 16)
    section_offset = 0x100 + (full_id >> 16) * 6
    count = int.from_bytes(stage[section_offset:section_offset + 2], "little")
    first = u32(stage, section_offset + 2)
    assert section_offset == 0x14e and count == 108 and first == 4238
    assert (full_id & 0xffff) < count
    entry = pin["property_table_offset"] + (first + (full_id & 0xffff)) * 6
    assert entry == int(prop["entry_stage_offset_hex"], 16)
    assert stage[entry:entry + 6].hex() == prop["entry_hex"]
    assert int.from_bytes(stage[entry:entry + 2], "little") == 8
    encoded = u32(stage, entry + 2)
    assert encoded >> 24 == 0xff
    offset = encoded & 0xffffff
    length = int.from_bytes(stage[offset:offset + 2], "little")
    assert length == prop["payload_bytes"] == 256
    assert offset + 2 == int(prop["payload_stage_offset_hex"], 16)
    assert hashlib.sha256(stage[offset + 2:offset + 2 + length]).hexdigest() == prop["payload_sha256"]
    base = ALH_PINS["CP_VA_equals_raw_plus"]
    assert u32(cp, 0x1106a5c - base + 0x29 * 4) == int(prop["target_CP_address"], 16)
    assert u32(cp, 0x1106b98 - base + 0x29 * 4) == full_id


def test_freeze_is_a_different_invalid_initial_stage():
    _, _, stage = authenticated_assets()
    frozen = bytearray(stage)
    frozen[9] = 1
    pin = PINS["freeze_hazard"]
    assert u32(frozen, 32) == int(pin["stored_checksum_unchanged"], 16)
    assert sum(frozen[:32]) + sum(frozen[36:]) == int(pin["actual_checksum"], 16)
    assert fnv1a64(frozen) == pin["frozen_fnv1a64"]
    assert pin["original_post_freeze_parser_behavior"].startswith("unknown")


def test_source_policy_is_explicit_and_limited():
    contract = PINS["source_contract"]
    assert contract["mode_and_profile_use_same_primary"] is True
    for key in ["secondary_is_missing_key_fallback", "ALLLANG_file_zero_is_CP_primary_proven",
                "native_PCI_to_CP_04000000_alias_verified", "native_CP_startup_verified",
                "ready_or_publication_claimed"]:
        assert contract[key] is False
    assert PINS["initial_stage"]["source"] == "CP_INITIAL_STAGE"
    assert PINS["initial_stage"]["repository"] == "CP_PRIMARY"
    assert PINS["initial_stage"]["fnv_is_authentication"] is False
