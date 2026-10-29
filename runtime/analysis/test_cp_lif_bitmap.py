"""Source-closed owned virtual bitmap fixtures; no native CP transport proof."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
MODELS = BASE / "device-models"
REPORT = BASE.parent.parent / "report" / "lif-bitmap-producer"


def test_bitmap_builder_owner_receive_with_sanitizers(tmp_path):
    obj, binary = tmp_path / "bitmap.o", tmp_path / "bitmap"
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
    for command in (
        flags + ["-c", str(MODELS / "cp-lif-bitmap.c"), "-o", str(obj)],
        flags + [str(obj), str(MODELS / "cp-lif-frame.c"),
                 str(MODELS / "test-cp-lif-bitmap.c"), "-o", str(binary)],
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
        "owned_virtual_data=1 source_build_consumed=1 owned_transport_consumed=1 "
        "receive_snapshot_decoded=1 native_delivery=0 cp_state=0 ready=0 ack=0")
    symbols = subprocess.run(["nm", "-g", "--defined-only", str(obj)],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stderr
    assert {line.split()[-1] for line in symbols.stdout.splitlines()} == {
        "cp_lif_bitmap_build", "cp_lif_bitmap_owner_init", "cp_lif_bitmap_request",
        "cp_lif_bitmap_gate_clear", "cp_lif_bitmap_observe_transport_consumed",
        "cp_lif_bitmap_receive_decode",
    }
    undefined = subprocess.run(["nm", "-u", str(obj)], capture_output=True,
                               text=True, timeout=10)
    assert undefined.returncode == 0, undefined.stderr
    assert "cp_lif_frame_decode" in undefined.stdout
    imports = {line.split()[-1] for line in undefined.stdout.splitlines()}
    imports = {name for name in imports if not name.startswith(("__asan_", "__ubsan_"))}
    assert imports <= {"cp_lif_frame_decode", "getpid", "memcmp", "memcpy", "memset", "__stack_chk_fail"}


def test_public_bitmap_builder_source_pins():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    assert pins["CP_sha256"] == "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"
    assert pins["CP_bytes"] == 18090880
    assert pins["file_backed_CP_VA"] == [0x108000, 0x1248b80]
    assert pins["BSS_read_as_file"] is False
    assert pins["native_producer_wired"] is False
    assert pins["dma_span"] == 32 and pins["dma_known_bytes"] == 25
    assert pins["constructor_bitmap_known_mask"] == 0
    assert len(pins["pins"]) == 10
    assert sum(window["bytes"] for window in pins["pins"]) == 3886
    for window in pins["pins"]:
        va, size = window["CP_VA"], window["bytes"]
        assert size > 0 and 0x108000 <= va < va + size <= 0x1248b80
        assert window["raw_offset"] == va - 0x108000
    source = BASE / "menu-root" / "cp" / "cpapp-b.bin"
    if not source.is_file():
        pytest.skip("public ALLLANG assets absent; host owner tests remain independent")
    blob = source.read_bytes()
    assert len(blob) == pins["CP_bytes"]
    assert hashlib.sha256(blob).hexdigest() == pins["CP_sha256"]
    for window in pins["pins"]:
        offset, size = window["raw_offset"], window["bytes"]
        data = blob[offset:offset + size]
        assert len(data) == size
        assert hashlib.sha256(data).hexdigest() == window["sha256"], window["label"]
    row = pins["command_table_row"]
    assert blob[row["raw_offset"]:row["raw_offset"] + 6] == bytes.fromhex(row["expected_hex"])
