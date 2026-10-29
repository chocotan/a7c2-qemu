"""Finite owned cache admission: authenticated public assets and host C only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODELS = ROOT / "runtime/analysis/device-models"
CAPABILITIES = HERE.parent / "lif-capability-owner"
PINS = json.loads((HERE / "source-pins.json").read_text())
STAGE_PINS = json.loads((HERE.parent / "cp-property-repository-contract/source-pins.json").read_text())
CASES = ["init", "reset", "cycle", "order5", "order6", "empty-last", "empty-first",
         "all-empty", "copy", "history", "opaque", "previous", "byte-eviction",
         "metadata-reuse", "reset-aba", "support-zero", "support-unknown", "z-one",
         "z-unknown", "cap-guard", "bitmap-receipt", "bitmap-config", "guards",
         "aliases", "read-aliases", "spans", "overflow", "bad-rx", "dataflow", "fork",
         "combined-flow", "combined-order", "combined-failures", "combined-unknown"]


@pytest.fixture(scope="session")
def public_assets(tmp_path_factory):
    cp_path = ROOT / PINS["CP_path"]
    seed_path = ROOT / STAGE_PINS["public_seed_path"]
    if not cp_path.is_file() or not seed_path.is_file():
        pytest.skip("authenticated public CP and ALLLANG assets are not installed")
    cp, seed = cp_path.read_bytes(), seed_path.read_bytes()
    assert len(cp) == PINS["CP_bytes"] == 18090880
    assert hashlib.sha256(cp).hexdigest() == PINS["CP_sha256"]
    assert len(seed) == STAGE_PINS["public_seed_bytes"]
    assert hashlib.sha256(seed).hexdigest() == STAGE_PINS["public_seed_sha256"]
    stage_pin = STAGE_PINS["initial_stage"]
    stage = seed[stage_pin["ALLLANG_file_offset"]:]
    assert len(stage) == stage_pin["bytes"]
    assert hashlib.sha256(stage).hexdigest() == stage_pin["sha256"]
    profile = stage_pin["profile"]
    context = stage[profile["payload_offset"]:profile["payload_offset"] + profile["bytes"]]
    assert hashlib.sha256(context).hexdigest() == profile["sha256"]
    assert context[0x17] == 0 and context[0x20] == 1
    path = tmp_path_factory.mktemp("lif-cache-public") / "initial-stage.bin"
    path.write_bytes(stage)
    return cp, path


def compile_test(path, sanitize=False):
    command = [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
               "-pedantic", "-O1", "-g", "-I", str(MODELS), "-I", str(CAPABILITIES)]
    if sanitize:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command += [str(HERE / "lif-cache.c"), str(HERE / "test-lif-cache.c"),
                str(CAPABILITIES / "lif-capabilities.c")]
    command += [str(MODELS / name) for name in ("cp-property-stage.c", "cp-start-state-provider.c",
                "cp-start-state-data.c", "cp-lif-bitmap.c", "cp-lif-frame.c")]
    result = subprocess.run(command + ["-Wl,--wrap=cp_lif_bitmap_receive_decode", "-o", str(path)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture(scope="session")
def executable(tmp_path_factory):
    return compile_test(tmp_path_factory.mktemp("lif-cache-strict") / "test-cache")


def run_case(executable, case, stage):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), case, str(stage)], capture_output=True,
                            text=True, env=env, timeout=20)
    assert result.returncode == 0, f"{case}: rc={result.returncode}\n{result.stderr}"
    assert result.stdout == "ok\n" and not result.stderr


@pytest.mark.parametrize("case", CASES)
def test_owned_cache_behavior(executable, public_assets, case):
    run_case(executable, case, public_assets[1])


def test_all_behaviors_with_asan_ubsan(tmp_path, public_assets):
    executable = compile_test(tmp_path / "test-cache-sanitized", sanitize=True)
    for case in CASES:
        run_case(executable, case, public_assets[1])


def test_all_behaviors_with_original_aarch64_libc(tmp_path, public_assets):
    qemu = ROOT/'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not shutil.which('clang') or not qemu.is_file():
        pytest.skip('original-libc execution needs clang and prepared QEMU user mode')
    guest = ROOT/'runtime/analysis/menu-root'
    exe = tmp_path/'test-cache-original-libc'
    sources = [CAPABILITIES/'original-abi-entry.c', HERE/'lif-cache.c',
               HERE/'test-lif-cache.c', CAPABILITIES/'lif-capabilities.c']
    sources += [MODELS/name for name in ('cp-property-stage.c', 'cp-start-state-provider.c',
        'cp-start-state-data.c', 'cp-lif-bitmap.c', 'cp-lif-frame.c')]
    libraries = [guest/'lib'/name for name in ('libc-2.25.so', 'libdl-2.25.so',
        'libpthread-2.25.so', 'ld-2.25.so')]
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib',
        '-O2', '-mno-outline-atomics', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-Wl,--no-undefined', '-isystem', '/usr/aarch64-linux-gnu/include',
        '-I', str(MODELS), '-I', str(CAPABILITIES), '-Wl,-e,_start',
        '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
        *(str(p) for p in sources), '-Wl,--wrap=cp_lif_bitmap_receive_decode',
        *(str(p) for p in libraries), '-o', str(exe)],
        check=True, capture_output=True, text=True, timeout=30)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_', 'LD_'))}
    for case in CASES:
        result = subprocess.run([str(qemu), '-L', str(guest), str(exe), case, str(public_assets[1])],
            check=True, capture_output=True, text=True, env=env, timeout=20)
        assert result.stdout == 'ok\n' and not result.stderr, case


def test_all_16_exact_source_windows(public_assets):
    cp, _ = public_assets
    base = PINS["CP_VA_equals_raw_plus"]
    lo, hi = PINS["file_backed_CP_VA"]
    assert lo == base == 0x108000 and hi == 0x1248b80 and hi - lo == len(cp)
    assert len(PINS["pins"]) == 16
    assert sum(pin["size"] for pin in PINS["pins"][:10]) == PINS["main_source_window_bytes"] == 7262
    assert sum(pin["size"] for pin in PINS["pins"][10:]) == PINS["supplemental_source_window_bytes"] == 124
    assert sum(pin["size"] for pin in PINS["pins"]) == PINS["source_window_bytes"] == 7386
    for pin in PINS["pins"]:
        start, end = pin["CP_VA"], pin["end_CP_VA"]
        assert lo <= start < end <= hi and end - start == pin["size"]
        assert hashlib.sha256(cp[start - base:end - base]).hexdigest() == pin["sha256"], pin["name"]
    for address, literal in PINS["supplemental_exact_bytes"].items():
        offset = int(address, 16) - base
        assert cp[offset:offset + len(literal) // 2].hex() == literal
    for address, expected in ((0x1101f84, 0x1fc9f70), (0x1101f88, 0x40)):
        assert int.from_bytes(cp[address - base:address - base + 4], "little") == expected
    assert PINS["owned_policy"]["metadata_slots"] == 64
    assert PINS["owned_policy"]["whole_rx_max_bytes"] == 0x220
    assert not PINS["native_layout"]["RAM_addresses_are_file_offsets"]
    assert not PINS["owned_policy"]["actual_pool_runtime_B_S_known"]
    for key in ("original_cache_executed", "original_CP", "worker_published", "ack", "ready", "native_capture_verified"):
        assert PINS[key] is False
