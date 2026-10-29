"""Bounded fixed-command diagnostic owner: public assets and host C only."""
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
PINS = json.loads((HERE / "source-pins.json").read_text())
STAGE_PINS = json.loads((HERE.parent / "cp-property-repository-contract/source-pins.json").read_text())
CASES = ["ordered", "prez", "refresh", "selectors", "zvalues", "zrefusal", "dbit",
         "export", "kind-store", "guards", "init", "lengths", "bytes", "types", "commands",
         "aliases", "spans", "errno", "frozen", "immutable", "public-stage",
         "handshake-resets", "handshake-chain", "handshake-dynamic-order",
         "handshake-unknown", "handshake-kinds", "handshake-refusals",
         "handshake-dynamic-failures"]


def fnv(blob):
    value = 14695981039346656037
    for byte in blob:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return f"{value:016x}"


@pytest.fixture(scope="session")
def public_assets(tmp_path_factory):
    cp_path, seed_path = ROOT / PINS["CP_path"], ROOT / STAGE_PINS["public_seed_path"]
    if not cp_path.is_file() or not seed_path.is_file():
        pytest.skip("authenticated public CP/ALLLANG assets are not installed")
    cp, seed = cp_path.read_bytes(), seed_path.read_bytes()
    assert len(cp) == PINS["CP_bytes"] == 18090880
    assert hashlib.sha256(cp).hexdigest() == PINS["CP_sha256"]
    assert len(seed) == STAGE_PINS["public_seed_bytes"]
    assert hashlib.sha256(seed).hexdigest() == STAGE_PINS["public_seed_sha256"]
    stage_pin = STAGE_PINS["initial_stage"]
    stage = seed[stage_pin["ALLLANG_file_offset"]:]
    assert len(stage) == stage_pin["bytes"]
    assert hashlib.sha256(stage).hexdigest() == stage_pin["sha256"]
    assert fnv(stage) == stage_pin["fnv1a64"]
    profile = stage_pin["profile"]
    context = stage[profile["payload_offset"]:profile["payload_offset"] + 256]
    assert len(context) == 256 and context[0x17] == 0 and context[0x20] == 1
    assert context[17] == context[20] == 0  # Decimal indices are different source bytes.
    assert hashlib.sha256(context).hexdigest() == profile["sha256"]
    output = tmp_path_factory.mktemp("lif-capability-public") / "initial-stage.bin"
    output.write_bytes(stage)
    return cp, output


def compile_test(path, sanitize=False):
    cmd = [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
           "-pedantic", "-O1", "-g", "-I", str(MODELS)]
    if sanitize:
        cmd += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    cmd += [str(HERE / "lif-capabilities.c"), str(HERE / "test-lif-capabilities.c")]
    cmd += [str(MODELS / name) for name in ["cp-property-stage.c", "cp-start-state-provider.c",
            "cp-start-state-data.c", "cp-lif-bitmap.c", "cp-lif-frame.c"]]
    subprocess.run(cmd + ["-o", str(path)], check=True, capture_output=True, text=True)
    return path


@pytest.fixture(scope="session")
def executable(tmp_path_factory):
    return compile_test(tmp_path_factory.mktemp("lif-capability-strict") / "test-owner")


def run_case(executable, case, stage_path):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), case, str(stage_path)], check=True,
                            capture_output=True, text=True, env=env)
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("case", CASES)
def test_owned_fixed_command_behavior(executable, public_assets, case):
    run_case(executable, case, public_assets[1])


def test_all_behaviors_with_asan_ubsan(tmp_path, public_assets):
    executable = compile_test(tmp_path / "test-owner-sanitized", sanitize=True)
    for case in CASES:
        run_case(executable, case, public_assets[1])


def test_all_behaviors_with_original_aarch64_libc(tmp_path, public_assets):
    qemu = ROOT/'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not shutil.which('clang') or not qemu.is_file():
        pytest.skip('original-libc execution needs clang and prepared QEMU user mode')
    guest = ROOT/'runtime/analysis/menu-root'
    exe = tmp_path/'test-owner-original-libc'
    sources = [HERE/'original-abi-entry.c', HERE/'lif-capabilities.c', HERE/'test-lif-capabilities.c']
    sources += [MODELS/name for name in ('cp-property-stage.c', 'cp-start-state-provider.c',
        'cp-start-state-data.c', 'cp-lif-bitmap.c', 'cp-lif-frame.c')]
    libraries = [guest/'lib'/name for name in ('libc-2.25.so', 'libdl-2.25.so',
        'libpthread-2.25.so', 'ld-2.25.so')]
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib',
        '-O2', '-mno-outline-atomics', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-Wl,--no-undefined', '-isystem', '/usr/aarch64-linux-gnu/include', '-I', str(MODELS),
        '-Wl,-e,_start', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
        *(str(path) for path in sources + libraries), '-o', str(exe)],
        check=True, capture_output=True, text=True, timeout=30)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_', 'LD_'))}
    for case in CASES:
        result = subprocess.run([str(qemu), '-L', str(guest), str(exe), case, str(public_assets[1])],
            check=True, capture_output=True, text=True, env=env, timeout=20)
        assert result.stdout == 'ok\n' and not result.stderr, case


def test_exact_source_windows_and_mode_binding(public_assets):
    cp, _ = public_assets
    base = PINS["CP_VA_equals_raw_plus"]
    lo, hi = PINS["file_backed_CP_VA"]
    assert base == lo == 0x108000 and hi == 0x1248b80
    assert hi - lo == len(cp)
    assert len(PINS["pins"]) == 15
    assert sum(pin["size"] for pin in PINS["pins"]) == PINS["source_window_bytes"] == 7796
    for pin in PINS["pins"]:
        va, end = pin["CP_VA"], pin["end_CP_VA"]
        assert lo <= va < end <= hi and end - va == pin["size"]
        assert hashlib.sha256(cp[va - base:end - base]).hexdigest() == pin["sha256"], pin["name"]
    mode = PINS["mode_binding"]
    existing = next(p for p in STAGE_PINS["pins"] if p["name"] == mode["existing_pin_name"])
    assert existing["CP_VA"] == mode["CP_VA"] == 0x40c278
    assert existing["size"] == mode["size"] == 48
    assert hashlib.sha256(cp[0x40c278 - base:0x40c2a8 - base]).hexdigest() == mode["sha256"] == existing["sha256"]
    assert STAGE_PINS["source_contract"]["mode_initializer"] == {
        "CP_VA": "eb5650", "target": "1107178", "value": 3}
    assert not PINS["original_cache_admission_verified"]
    assert not PINS["native_capture_verified"] and not PINS["original_CP"]
    assert PINS["native_constructor_property_known_bytes"] == 0
    assert not PINS["public_context"]["gate_state_byte_known"]
    assert PINS["public_context"]["actual_public_init_result"].startswith("0;")


def test_handshake_source_windows(public_assets):
    cp, _ = public_assets
    pins = json.loads((HERE.parent / "lif-handshake-contract/source-pins.json").read_text())
    assert (pins["CP_path"], pins["CP_bytes"], pins["CP_sha256"]) == (
        PINS["CP_path"], len(cp), hashlib.sha256(cp).hexdigest())
    base = pins["CP_VA_equals_raw_plus"]
    assert base == PINS["CP_VA_equals_raw_plus"]
    assert len(pins["pins"]) == 16
    assert sum(pin["size"] for pin in pins["pins"]) == pins["source_window_bytes"] == 4728
    for pin in pins["pins"]:
        start, end = pin["CP_VA"], pin["end_CP_VA"]
        assert end - start == pin["size"]
        assert hashlib.sha256(cp[start - base:end - base]).hexdigest() == pin["sha256"], pin["name"]
    row = pins["command9"]
    assert cp[row["table_CP_VA"] - base:row["table_CP_VA"] - base + 6].hex() == "090005000c00"
    assert row["body_bytes"] == 12 and row["logical_frame_bytes"] == 20
    enqueue = pins["boot_event9_enqueue"]
    assert enqueue["producer_closed"] and enqueue["descriptor_words"] == ["a96a0b", 0, "408d59", 0, 0]
    assert not enqueue["actual_message_delivery_known"] and not enqueue["dispatcher_execution_known"]
    # Thumb-2 BL/B.W signed immediate targets, independent of a disassembler.
    for address, target, opcode in [(0x4b7174, 0xa48f86, 0xd000),
                                    (0x4b71e0, 0xa48f86, 0xd000),
                                    (0xa48f86, 0xa96c7a, 0x9000),
                                    (0xa96c7e, 0xa9699c, 0x9000)]:
        raw = cp[address - base:address - base + 4]
        first, second = int.from_bytes(raw[:2], "little"), int.from_bytes(raw[2:], "little")
        assert first & 0xf800 == 0xf000 and second & 0xd000 == opcode
        sign = (first >> 10) & 1
        i1, i2 = 1 ^ ((second >> 13) & 1) ^ sign, 1 ^ ((second >> 11) & 1) ^ sign
        displacement = ((sign << 24) | (i1 << 23) | (i2 << 22) |
                        ((first & 0x3ff) << 12) | ((second & 0x7ff) << 1))
        assert address + 4 + displacement - (sign << 25) == target
    assert cp[0xa96c7a - base:0xa96c7e - base].hex() == "0920ff21"  # r0=9, r1=ff.
    assert pins["initial_handshake_state_known"] is False
    for key in ["original_cache_admission_verified", "original_event9_delivery_verified",
                "original_handler_executed", "native_capture_verified", "original_CP"]:
        assert pins[key] is False


def test_real_request_literals_and_fixed_rows(public_assets):
    cp, _ = public_assets
    base = PINS["CP_VA_equals_raw_plus"]
    for row in PINS["requests"]:
        offset = 0xf8f997 - base + row["row"] * 32
        mask = cp[offset:offset + 32]
        request = b"\x01" + mask
        assert mask.hex() == row["mask_hex"]
        assert request.hex() == row["request_hex"]
        assert fnv(request) == row["request_fnv1a64"]
    for row in PINS["fixed_rows"]:
        va = 0x120553c + row["command"] * 6
        actual = cp[va - base:va - base + 6]
        assert va == row["CP_VA"] and actual.hex() == row["hex"]
        assert int.from_bytes(actual[:2], "little") == row["command"]
        assert int.from_bytes(actual[4:], "little") == row["received_body_bytes"]
    assert PINS["four_command_destination_known_bytes"] == 33 + 35 * 2 + 202 + 64 == 369
