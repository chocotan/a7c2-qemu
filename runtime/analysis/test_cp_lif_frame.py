"""Bounded LIF host fixtures; decoding is not native receipt or publication."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
MODELS = BASE / "device-models"
REPORT = BASE.parent.parent / "report" / "lif-runtime-input-contract"


def test_host_decoder_matrix_with_sanitizers(tmp_path):
    obj, binary = tmp_path / "lif-frame.o", tmp_path / "lif-frame"
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
    for command in (
        flags + ["-c", str(MODELS / "cp-lif-frame.c"), "-o", str(obj)],
        flags + [str(obj), str(MODELS / "test-cp-lif-frame.c"), "-o", str(binary)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        [str(binary)], cwd=tmp_path,
        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                 UBSAN_OPTIONS="halt_on_error=1"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "host_fixture_transport_decoded=1 native_receive=0 semantic_applied=0 published=0 ack=0")
    symbols = subprocess.run(["nm", "-g", "--defined-only", str(obj)],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stderr
    assert {line.split()[-1] for line in symbols.stdout.splitlines()} == {"cp_lif_frame_decode"}


def test_public_source_pins_and_schemas():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    assert pins["CP_sha256"] == "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"
    assert pins["CP_bytes"] == 18090880
    assert pins["file_backed_CP_VA"] == [0x108000, 0x1248b80]
    assert pins["BSS_read_as_file"] is False
    assert pins["constructor_bitmap_known_mask"] == 0
    assert pins["native_producer_wired"] is False
    assert len(pins["pins"]) == 12
    assert sum(p["bytes"] for p in pins["pins"]) == 5280
    windows = pins["pins"] + pins["type1_gate_evidence"]
    for window in windows:
        va, size = window["CP_VA"], window["bytes"]
        assert size > 0 and 0x108000 <= va < va + size <= 0x1248b80
        assert window["raw_offset"] == va - 0x108000
    source = BASE / "menu-root" / "cp" / "cpapp-b.bin"
    if not source.is_file():
        pytest.skip("public ALLLANG assets absent; host decoder tests remain independent")
    blob = source.read_bytes()
    assert len(blob) == pins["CP_bytes"]
    assert hashlib.sha256(blob).hexdigest() == pins["CP_sha256"]
    for window in windows:
        offset, size = window["raw_offset"], window["bytes"]
        data = blob[offset:offset + size]
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == window["sha256"], window["label"]
        if "expected_hex" in window:
            assert data.hex() == window["expected_hex"]

    def at(va, size):
        return blob[va - 0x108000:va - 0x108000 + size]

    assert int.from_bytes(at(0x1107030, 4), "little") == 0x120553c
    for command, pointer_va, schema_va, count, first_id in (
        (5, 0x1107034, 0x1206dfd, 28, 0),
        (6, 0x1107038, 0x1206e7f, 11, 0x40),
    ):
        assert int.from_bytes(at(pointer_va, 4), "little") == schema_va
        table_row = at(0x120553c + command * 6, 6)
        assert table_row == bytes((command, 0, 0, 0, 0xff, 0))
        data = at(schema_va, 2 * count + 2)
        assert list(data[:-2:2]) == list(range(first_id, first_id + count))
        assert data[-2:] == b"\x80\0"
        text = (MODELS / "cp-lif-frame.c").read_text()
        match = re.search(rf"schema{command}\[\]\s*=\s*\{{([^}}]+)\}}", text)
        assert match
        assert [int(n) for n in re.findall(r"\d+", match[1])] == list(data[1:-2:2])
