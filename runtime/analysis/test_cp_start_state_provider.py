"""Host-only property binding. No VM, device, private settings or native-ready claim."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

BASE = Path(__file__).resolve().parents[2]
MODELS = BASE / "runtime/analysis/device-models"
REPORT = BASE / "report/cp-start-state-provider"
PINS = json.loads((REPORT / "source-pins.json").read_text())
spec = importlib.util.spec_from_file_location("cp_start_state_public_loader", REPORT / "load_public.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


@pytest.fixture(params=[False, True], ids=["strict", "asan-ubsan"])
def executable(request, tmp_path):
    out = tmp_path / "provider-test"
    cmd = [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
    if request.param:
        cmd += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    cmd += [str(MODELS / name) for name in
            ["cp-start-state-provider.c", "cp-start-state-data.c", "test-cp-start-state-provider.c"]]
    subprocess.run(cmd + ["-o", str(out)], check=True, capture_output=True, text=True)
    return out


def run(executable, *args):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    return subprocess.run([str(executable), *map(str, args)], env=env, check=True,
                          capture_output=True, text=True).stdout


def test_provider_matrix(executable):
    assert "PASS cp-start-state-provider" in run(executable)


def assets():
    if not (BASE / "runtime/analysis/menu-root/cp/cpapp-b.bin").is_file():
        pytest.skip("public CP image not installed")
    seed = BASE / "runtime/analysis/unpacked/firmware.tar_unpacked/0110_backup/SYSIPSX-DSLR/PP/CX89701_ALLLANG.bin"
    if not seed.is_file():
        pytest.skip("public ALLLANG seed not installed")


def test_authenticated_public_banks(executable, tmp_path):
    assets()
    for policy in loader.POLICIES:
        bank, metadata = loader.load_public_bank(BASE, policy)
        path = tmp_path / (loader.POLICIES[policy] + ".bin")
        path.write_bytes(bank)
        primary = policy == "primary"
        stdout = run(executable, path, "primary" if primary else "secondary-virtual")
        assert metadata["native_repository_selected"] is False
        assert metadata["runtime_consumed"] is False
        if primary:
            assert "ENODATA, profile unknown, no fallback" in stdout
        else:
            context = bytes.fromhex(re.search(r"context=([0-9a-f]+)", stdout)[1])
            assert len(context) == 256
            assert hashlib.sha256(context).hexdigest() == metadata["payload_sha256"]
            assert "prefetch=256 profile=0" in stdout
            assert context[:16].hex() == "00000000000000000500000000000009"
    with pytest.raises(ValueError, match="explicit"):
        loader.load_public_bank(BASE, "fallback")


def test_new_backend_source_pins():
    assets()
    cp = (BASE / "runtime/analysis/menu-root/cp/cpapp-b.bin").read_bytes()
    assert len(cp) == PINS["CP_bytes"]
    assert hashlib.sha256(cp).hexdigest() == PINS["CP_sha256"]
    lo, hi = PINS["file_backed_CP_VA"]
    for pin in PINS["pins"]:
        va, size = pin["CP_VA"], pin["size"]
        assert lo <= va < va + size <= hi
        offset = va - PINS["CP_VA_equals_raw_plus"]
        assert offset == pin["raw_offset"]
        assert hashlib.sha256(cp[offset:offset + size]).hexdigest() == pin["sha256"], pin["name"]


def test_same_run_4063_content_audit():
    audit = json.loads((REPORT / "same-run-4063.json").read_text())
    path = BASE / "runtime/analysis/menu-runs" / audit["run"] / audit["audit_file"]
    if not path.is_file():
        pytest.skip("local original-run evidence absent")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == audit["audit_sha256"]
    pattern = (rb"NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES pid=258 tid=381 sequence=49 "
               rb"offset=(\d+) bytes=(\d+) raw=([0-9a-f]+)")
    wire = bytearray()
    chunks = re.findall(pattern, raw)
    assert len(chunks) == audit["chunks"] == 21
    for offset, size, payload in chunks:
        assert int(offset) == len(wire)
        chunk = bytes.fromhex(payload.decode())
        assert len(chunk) == int(size)
        wire += chunk
    assert len(wire) == audit["bytes"] == 2564
    assert hashlib.sha256(wire).hexdigest() == audit["sha256"]
    assert wire[:8].hex() == "0500634027000080"
    assert len(audit["slots"]) == 190
    end = 8
    for slot in audit["slots"]:
        offset, size = slot["offset"], slot["size"]
        assert offset == end and size >= 8
        assert wire[offset] == 5
        assert int.from_bytes(wire[offset + 2:offset + 4], "little") == int(slot["opcode"], 16)
        assert wire[offset + 8:offset + size].hex() == slot["payload_hex"]
        end += size
    assert end == len(wire)
    assert audit["semantic_consumed_claimed"] is False
    assert audit["override_setter_closed"] is False
