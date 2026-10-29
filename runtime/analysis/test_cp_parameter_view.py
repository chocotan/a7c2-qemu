"""Owned CP bank0 and separate config/bank3/FLAGB events; no VM/device access."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
MODELS = BASE / "device-models"
REPORT = BASE.parents[1] / "report/cp-parameter-publication-contract"
CONFIG_REPORT = BASE.parents[1] / "report/lif-enable-input-contract"
CONFIG_PINS = [
    (0xb2a374, 1248, "576b006fda3845045c0db81311ae26ad3ef78be6b590893300d190a9a4cc10ab"),
    (0x4c1078, 72, "efa571cbf7ae80f87b884ad44d9afc8d464ccb43f574e32c4e84966a76df0547"),
    (0xb2e140, 1368, "e3f8df2890faa006d39c03b82bf1c77b6daca1f555646bacc4ccb38aab56b8f9"),
    (0xb2ed24, 242, "95b3dc4e39072500408335d152c6261b22e2d35a324b2bb3f198287045f1f052"),
    (0x99b86e, 66, "c0a60550364e8b55604d8859d7abc9d61e35010219f8526a6efd074b1dd139b7"),
    (0xa4dfc6, 14, "ca423102bbab7b7f7dcf605f915b1601a2c915fb5fced89250e61722a5f41c21"),
    (0x3a9d48, 8, "a4fc4ce698bf3bc0aa440dd053edaa6a47d1b5fd0803759680764895a460eebd"),
]
CP_HASH = "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"
PINS = [
    (0x4b7028, 102, "adf3f6389e7996f859a95fdcf3c162d92bbd63da7ae159cc6032d58b4c0d78e3"),
    (0xb2e140, 1324, "5b2c9109102407e53fde5d47f1a781ca9fbe6e74d3fa3c202d6fa0b82f111791"),
    (0xb2e8e0, 852, "af85dd1d68146f40073e9acbbf1a26bb0b37ed434dc8d0b11d8e7042aa66398b"),
    (0x4d79e2, 138, "a73e79de1f21765a5e3ad5c890efd635d03bf6d398f4000112b37f9d9411ac5f"),
    (0x8dad4a, 128, "cacc283507161e568c1a8a06309b8fac864ac424087f1c3308a2268318add701"),
    (0x992710, 2710, "869624fdfdf6d2b4732e623ddf1b517addd64ad821bdaa2460127c6c68a16e3e"),
    (0x99affc, 22, "59d462f23ffd9d9dc10b71beee7eb64590f2f505bcea2ec138331e5bce85ad0c"),
    (0x99e250, 16, "ed954a4dba06e0d68796b120fc58f8e79370412e487d2a29febca2070e489058"),
    (0x3abc42, 86, "4ab28c4b7cc63471a220cf6b969436fd76c6336cb443c76621850e44c2827d69"),
    (0xb224a8, 102, "1d375ad0808dcb68deec70192eb7064427529693a41a52968df424077edf40bf"),
]


def test_owned_initial_copy_bank_binding_and_lif_consumer(tmp_path):
    binary = tmp_path / "cp-parameter-view"
    command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g",
               "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie",
               *[str(MODELS / name) for name in (
                   "cp-parameter-batch.c", "cp-parameter-state.c",
                   "cp-start-state-data.c", "cp-parameter-view.c",
                   "test-cp-parameter-view.c")], "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(binary)], capture_output=True, text=True,
                            env=environment, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_source_contract_metadata():
    data = json.loads((REPORT / "source-pins.json").read_text())
    assert data["asset"]["bytes"] == 18090880
    assert data["asset"]["sha256"] == CP_HASH
    assert [(int(pin["va"], 16), pin["bytes"], pin["sha256"])
            for pin in data["windows"]] == PINS
    assert data["windows_bytes"] == sum(size for _, size, _ in PINS) == 5480
    assert data["data_flow"]["image_bytes"] == 0xd64
    assert data["data_flow"]["pointer_table_bytes"] == 50 * 4
    assert data["data_flow"]["override_span_bytes"] == 0x1c9
    assert data["copy_events_modeled"] and data["separate_bank0_binding_modeled"]
    for flag in ("complete_constructor_applied", "native_boot_executed",
                 "native_publication_verified", "periodic_copy_modeled",
                 "full_76_block_snapshot", "ack", "business_ready",
                 "configuration_ready", "ap_applied", "capture_verified"):
        assert data[flag] is False


def test_separate_config_word_source_contract_metadata():
    data = json.loads((CONFIG_REPORT / "source-pins.json").read_text())
    assert data["CP_bytes"] == 18090880 and data["CP_sha256"] == CP_HASH
    assert [(int(pin["CP_VA"], 16), pin["bytes"], pin["sha256"])
            for pin in data["windows"][:7]] == CONFIG_PINS
    assert data["initial_config_word"] == {
        "offset_hex": "1c", "value": 2, "published_address": "17312b4",
        "collector_predicate": "word == 0", "FLAGB_after_collector_projection": 0,
    }
    assert data["later_recopy_CP_VA"] == "b2ee12"
    assert not data["worker_call_gate_known"]
    assert not data["published_zero_projection_verified"]
    assert not data["capture_verified"]


def test_public_cp_raw_source_windows():
    path = BASE / "menu-root/cp/cpapp-b.bin"
    if not path.is_file():
        pytest.skip("public CP asset is prepared separately; no image is redistributed")
    raw = path.read_bytes()
    assert len(raw) == 18090880 and hashlib.sha256(raw).hexdigest() == CP_HASH
    for va, size, digest in (*PINS, *CONFIG_PINS):
        assert 0x108000 <= va < va + size <= 0x1248b80
        offset = va - 0x108000
        assert hashlib.sha256(raw[offset:offset + size]).hexdigest() == digest
    assert raw[0xb2ebd2 - 0x108000:0xb2ebd4 - 0x108000] == bytes.fromhex("0860")
