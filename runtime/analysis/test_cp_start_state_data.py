"""Host-only CP3003/3000 source data owner; no runtime/VM readiness claim."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / "device-models"
REPORT = BASE.parent.parent / "report" / "cp-start-state-data"


def test_host_source_input_matrix_with_sanitizers(tmp_path):
    obj, binary = tmp_path / "data-owner.o", tmp_path / "data-owner"
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
    for command in (
        flags + ["-c", str(HERE / "cp-start-state-data.c"), "-o", str(obj)],
        flags + [str(obj), str(HERE / "test-cp-start-state-data.c"), "-o", str(binary)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(binary)], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "host_source_inputs_consumed=1 reply_built=1 native_history=0 publication=0 ap_applied=0")
    symbols = subprocess.run(["nm", "-g", "--defined-only", str(obj)],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stderr
    assert {line.split()[-1] for line in symbols.stdout.splitlines()} == {
        "cp_start_state_data_init", "cp_start_state_data_consume_lif",
        "cp_start_state_data_consume_property", "cp_start_state_data_consume_adj",
        "cp_start_state_data_consume_event", "cp_start_state_data_snapshot",
        "cp_start_state_data_build_reply",
    }


def test_public_source_pins():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    assert pins["CP_sha256"] == "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"
    assert pins["CP_bytes"] == 18090880
    assert pins["file_backed_CP_VA"] == [0x108000, 0x1248b80]
    assert pins["BSS_read_as_file"] is False
    assert pins["constructor_input_known_mask"] == 0
    for window in pins["pins"]:
        va, size = window["CP_VA"], window["bytes"]
        assert size > 0 and 0x108000 <= va < va + size <= 0x1248b80
        assert window["raw_offset"] == va - 0x108000
    source = BASE / "menu-root" / "cp" / "cpapp-b.bin"
    if not source.is_file():
        pytest.skip("public ALLLANG assets are optional; source validation alone is skipped")
    blob = source.read_bytes()
    assert len(blob) == pins["CP_bytes"]
    assert hashlib.sha256(blob).hexdigest() == pins["CP_sha256"]
    for window in pins["pins"]:
        offset, size = window["raw_offset"], window["bytes"]
        data = blob[offset:offset + size]
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == window["sha256"], window["label"]
        if "expected_hex" in window:
            assert data.hex() == window["expected_hex"]
