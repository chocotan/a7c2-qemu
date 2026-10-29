"""Guarded CP4001 configuration/free host tests; no guest, DSO, or optical claims."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODELS = HERE / "device-models"
REPORT = HERE.parents[1] / "report/functional-cp-zoom"
SCENARIOS = (
    "success", "opaque", "default-off", "enabled-two", "destination", "type", "command",
    "short", "tiny", "long", "source", "zero-source", "caller", "drive", "trigger",
    "missing-source", "missing-free", "missing-guard", "missing-data-guard", "missing-owner",
    "guard-fail", "guard-miss", "guard-lost", "guard-owner", "guard-torn", "guard-odd",
    "guard-quiescent", "guard-origin", "missing-common", "missing-bootstrap", "missing-bulk",
    "owner-pid", "alias", "alias-guard", "alias-result", "mutated-wire", "mutated-size",
    "mutated-source", "post-store-wire", "post-store-guard", "free-fail", "duplicate", "repeat", "foreign-reuse",
    "reentrant-free", "reentrant-dispatch", "fork", "fork-in-free", "init-repeat",
    "alias-io-guard", "alias-data-guard",
)


def build(tmp_path, name, sources, sanitized):
    binary = tmp_path / name
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    result = subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread", *flags,
        *(str(MODELS / source) for source in sources), "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


def run(binary, *args):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    result = subprocess.run([str(binary), *args], capture_output=True, text=True, env=env, timeout=15)
    assert result.returncode == 0, f"case={args}\n{result.stdout}{result.stderr}"
    return result.stdout


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_zoom_idle_original_request_owner(tmp_path, sanitized):
    binary = build(tmp_path, "zoom", ("cp-parameter-state.c", "cp-parameter-batch.c",
                   "functional-cp-zoom.c", "test-functional-cp-zoom.c"), sanitized)
    for scenario in SCENARIOS:
        text = run(binary, scenario)
        if scenario == "success":
            assert "source=0x80020002 destination=0x90030001 caller=0x8000004c bytes=12" in text
            assert "raw=050001404c00008000020002" in text
            assert "readback=00000000020000000002 knownmask=0x3ff" in text
            assert "config_consumed=1 oneway_consumed=1 data_rc=0" in text
            assert "original_free_attempted=1 original_free_rc=0 original_freed=1" in text
            wire = bytes.fromhex("050001404c00008000020002")
            value = 14695981039346656037
            for byte in wire:
                value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
            assert f"wire_fnv1a={value:016x}" in text


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_shared_state_byte_domains_and_preservation(tmp_path, sanitized):
    binary = build(tmp_path, "state", ("cp-parameter-state.c", "cp-parameter-batch.c",
                   "test-cp-parameter-state.c"), sanitized)
    assert run(binary) == ""


def test_source_pins_and_independent_field_table():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    actual = pins["actual"]
    wire = bytes.fromhex(actual["raw"])
    assert len(wire) == 12 and hashlib.sha256(wire).hexdigest() == actual["packet_sha256"]
    assert actual["transport_source"] == 0x80020002
    assert int.from_bytes(wire[4:8], "little") == actual["wire_caller"] == 0x8000004c
    assert not pins["claims"]["success_ack_required"] and not pins["claims"]["ordinary_common_apply"]
    images = {}
    for image, row in pins["source"].items():
        path = HERE.parents[1] / row["path"]
        if path.is_file():
            raw = path.read_bytes()
            assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
            images[image] = raw
    assert len(pins["windows"]) == 8
    for row in pins["windows"]:
        raw = bytes.fromhex(row["hex"])
        assert len(raw) == row["bytes"] and hashlib.sha256(raw).hexdigest() == row["sha256"]
        if row["image"] in images:
            assert images[row["image"]][row["raw"]:row["raw"] + row["bytes"]] == raw
    source = (MODELS / "cp-parameter-state.c").read_text()
    table = re.search(r"static const struct field zoom_fields\[\] = \{\n(.*?)\n\};", source, re.S).group(1)
    rows = re.findall(r"\{[^\n]+", table)
    expected = re.findall(r"\{[^\n]+", (REPORT / "cp4001-fields.inc").read_text())
    assert [row.strip() for row in rows] == expected
    old_generated = (HERE.parents[1] / "report/cp-parameter-state/generated-table.inc").read_text()
    assert old_generated in source
    batch = (MODELS / "cp-parameter-batch.c").read_text()
    assert len(re.findall(r"\{0x[0-9a-f]+,0x[0-9a-f]+,0x[0-9a-f]+\}", batch)) == 190
    assert "{0x4001," not in batch


def test_production_owner_has_no_constructor_or_broker_dependency(tmp_path):
    obj = tmp_path / "zoom.o"
    result = subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread", "-c",
        str(MODELS / "functional-cp-zoom.c"), "-o", str(obj),
    ], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(["nm", str(obj)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert " U cp_parameter_state_consume_zoom" in result.stdout
    assert " U cp_parameter_state_read_zoom" in result.stdout
    assert "fcam_bridge" not in result.stdout and "HOST_TEST" not in result.stdout
