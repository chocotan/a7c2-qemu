"""HOST_TEST owner/OSAL lifecycle only; no VM, broker, CMOS, or capture evidence."""
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
RESULT_FIELDS = (
    "abi", "length", "instance", "zero-instance", "config-generation", "before-config",
    "config-overflow", "frame-generation", "before-frame", "frame-overflow", "lease-generation",
    "input-hash", "source-hash", "sink-hash", "active-bytes", "width", "height", "stride",
    "endpoint", "selected-mask", "completed-mask", "class", "enabled", "readback", "commit",
    "consumed", "retired", "status", "reserved", "config", "canonical-tail", "short", "long",
    "required", "token", "metadata-instance", "canary", "mutated-input",
)
SCENARIOS = (
    "success", "opaque", "disable", "repeat", "repeat-disable", "address-reuse", "foreign-reuse", "repeat-busy",
    "no-ticket", "old-ticket", "default-off", "enabled-two", "unrelated", "wrong-type",
    "wrong-destination", "invalid-path", "invalid-pins", "invalid-body4", "invalid-flags",
    "invalid-header-size", "short-request", "long-request", "bad-source", "missing-callback",
    "missing-guard", "guard-fail", "guard-miss", "guard-lost", "init-error", "init-short",
    "init-instance", "init-abi", "init-token", "init-reserved", "bridge-error", "bridge-positive",
    "mutated-request", "mutated-source", "mutated-size", "alloc-fail", "alloc-dirty-fail",
    "alloc-short", "alloc-long", "alloc-alias", "alloc-alias-interior", "set-source-fail",
    "ack-write-corrupt", "request-free-fail", "send-fail", "inline-free", "inline-send-fail",
    "receive-source", "receive-size", "receive-destination", "receive-meta-source",
    "receive-meta-size", "receive-wire", "foreign-receive", "foreign-free", "duplicate-receive",
    "free-before-receive", "free-meta-source", "free-meta-size", "free-wire", "ack-free-fail",
    "reentrant-free", "reentrant-dispatch", "fork-held-lock", "disable-forged-frame",
    "disable-forged-consumed", "disable-forged-hash", "disable-forged-bytes",
    "disable-forged-lease", "repeat-old-lease",
) + tuple(f"result-{name}" for name in RESULT_FIELDS)


ZEBRA_SCENARIOS = (
    "active", "inactive", "cold-inactive", "opaque", "route-opaque", "padding", "dynamic-source", "repeat",
    "mixed", "address-reuse", "generation-gap", "invalid-enable", "invalid-enable255",
    "invalid-flags", "invalid-header-size", "invalid-header-high", "short-request", "long-request",
    "bad-source", "bridge-error", "bridge-positive", "mutated-request", "mutated-source", "mutated-size",
    "alloc-fail", "alloc-dirty-fail", "alloc-short", "alloc-long", "alloc-alias", "alloc-alias-interior",
    "set-source-fail", "ack-write-corrupt", "request-free-fail", "send-fail", "inline-free",
    "inline-send-fail", "receive-source", "receive-size", "receive-destination", "receive-meta-source",
    "receive-meta-size", "receive-wire", "foreign-receive", "foreign-free", "duplicate-receive",
    "free-before-receive", "free-meta-source", "free-meta-size", "free-wire", "ack-free-fail", "no-ticket",
    "old-ticket", "ack-path-wire", "reentrant-free", "reentrant-dispatch", "result-path-fnv",
    "result-old-length", "result-old-used", "result-route-class", "result-duplicate-generation", "result-stale-lease",
    "inactive-disable-forged-frame", "inactive-disable-forged-consumed", "inactive-disable-forged-hash",
    "inactive-disable-forged-bytes", "inactive-disable-forged-lease",
) + tuple(f"result-{name}" for name in RESULT_FIELDS) + tuple(f"result-tail-{i}" for i in range(8))
OLD_SCENARIOS = SCENARIOS + tuple(f"zebra-{name}" for name in ZEBRA_SCENARIOS)
LAYOUT_SCENARIOS = (
    "active", "inactive", "cold-inactive", "route-opaque", "dynamic-source", "repeat", "mixed",
    "mixed-address-reuse", "address-reuse", "generation-gap", "default-off", "enabled-two",
    "unrelated", "wrong-type", "wrong-destination", "invalid-flags", "invalid-header-size",
    "invalid-header-high", "short-request", "long-request", "bad-source", "bridge-error", "bridge-positive",
    "mutated-request", "mutated-padding", "mutated-source", "mutated-size", "alloc-fail", "alloc-dirty-fail",
    "alloc-short", "alloc-long", "alloc-alias", "alloc-alias-interior", "alloc-snapshot-tail",
    "set-source-fail", "ack-write-corrupt", "request-free-fail", "send-fail", "inline-free", "inline-send-fail",
    "receive-source", "receive-size", "receive-destination", "receive-meta-source", "receive-meta-size",
    "receive-wire", "foreign-receive", "foreign-free", "duplicate-receive", "free-before-receive",
    "free-meta-source", "free-meta-size", "free-wire", "ack-free-fail", "no-ticket", "old-ticket",
    "ack-path-wire", "ack-zebra-wire", "reentrant-free", "reentrant-dispatch", "result-path-fnv",
    "result-old-length", "result-old-used", "result-zebra-length", "result-zebra-used", "result-route-class",
    "result-duplicate-generation", "result-stale-lease", "result-wrong-geometry", "result-wrong-height",
) + tuple(f"result-{name}" for name in RESULT_FIELDS) + tuple(f"result-tail-{i}" for i in range(32)) + tuple(
    f"invalid-body-{i}" for i in range(32)
)
EXISTING_SCENARIOS = OLD_SCENARIOS + tuple(f"layout-{name}" for name in LAYOUT_SCENARIOS)
DISPLAY_SCENARIOS = (
    "active", "inactive", "cold-inactive", "route-opaque", "dynamic-source", "repeat", "mixed",
    "mixed-address-reuse", "address-reuse", "generation-gap", "default-off", "enabled-two",
    "unrelated", "wrong-type", "wrong-native", "wrong-destination", "invalid-command-shape",
    "invalid-flags", "invalid-header-size", "invalid-header-high", "short-request", "long-request", "bad-source",
    "bridge-error", "bridge-positive", "mutated-request", "mutated-source", "mutated-size",
    "alloc-fail", "alloc-dirty-fail", "alloc-short", "alloc-long", "alloc-alias", "alloc-alias-interior",
    "alloc-snapshot-tail", "alloc-display-tail", "alloc-max-span", "set-source-fail", "ack-write-corrupt",
    "request-free-fail", "send-fail", "inline-free", "inline-send-fail", "receive-source", "receive-size",
    "receive-destination", "receive-meta-source", "receive-meta-size", "receive-wire", "foreign-receive",
    "foreign-free", "duplicate-receive", "free-before-receive", "free-meta-source", "free-meta-size", "free-wire",
    "ack-free-fail", "no-ticket", "old-ticket", "ack-path-wire", "ack-zebra-wire", "ack-other-display",
    "reentrant-free", "reentrant-dispatch", "result-path-fnv", "result-original-body-fnv",
    "result-old-length", "result-old-used", "result-zebra-length", "result-zebra-used", "result-layout-length",
    "result-layout-used", "result-other-display-command", "result-inactive-receipt", "result-route-class",
    "result-duplicate-generation", "result-stale-lease",
) + tuple(f"result-{name}" for name in RESULT_FIELDS) + tuple(f"result-tail-{i}" for i in range(16))
PEAKING_SCENARIOS = DISPLAY_SCENARIOS + (
    "invalid-enable", "invalid-enable255", "invalid-selector", "invalid-level", "invalid-magnification",
    "invalid-color-type", "invalid-palette-y", "invalid-palette-cb", "invalid-palette-cr", "invalid-opaque",
) + tuple(f"palette-{i}" for i in range(4)) + tuple(f"level-{i}" for i in range(3)) + tuple(
    f"magnification-{i}" for i in range(3)
)
FLAG_SCENARIOS = DISPLAY_SCENARIOS + ("invalid-off", "invalid-padding", "invalid-opaque")
SOURCE_PINNED_SCENARIOS = EXISTING_SCENARIOS + tuple(f"peaking-{name}" for name in PEAKING_SCENARIOS) + tuple(
    f"flag-{name}" for name in FLAG_SCENARIOS
)
LEASE_SCENARIOS = tuple(
    f"{prefix}fresh-request-lease{suffix}"
    for prefix in ("layout-", "peaking-", "flag-")
    for suffix in ("", "-inline-free", "-inline-send-fail", "-alloc-dirty-fail", "-alloc-short", "-alloc-long",
                   "-set-source-fail", "-ack-write-corrupt", "-send-fail", "-ack-free-fail", "-mixed", "-no-ticket", "-old-ticket")
) + tuple(f"{prefix}alloc-constant-{index}" for prefix in ("", "zebra-", "layout-", "peaking-", "flag-") for index in range(3))
BIND_SCENARIOS = (
    "bind-before-init", "bind-invalid", "bind-once", "bind-busy", "bind-busy-bound", "bind-pending", "bind-fault",
    "bind-retired", "bind-source-zero", "bind-unbound", "bind-unbound-81cf", "bind-wrong-source", "bind-wrong-81cf",
) + tuple(f"bind-domain-{command}" for command in ("0138", "0153", "014c", "0152", "0162"))
REFRESH_SCENARIOS = ("refresh-legacy-source-repeat",) + tuple(f"refresh-{name}" for name in DISPLAY_SCENARIOS) + tuple(
    f"refresh-fresh-request-lease{suffix}"
    for suffix in ("", "-inline-free", "-inline-send-fail", "-alloc-dirty-fail", "-alloc-short", "-alloc-long",
                   "-set-source-fail", "-ack-write-corrupt", "-send-fail", "-ack-free-fail", "-mixed", "-no-ticket", "-old-ticket")
) + tuple(f"refresh-alloc-constant-{index}" for index in range(3))
PRE_BB_SCENARIOS = SOURCE_PINNED_SCENARIOS + LEASE_SCENARIOS + BIND_SCENARIOS + REFRESH_SCENARIOS
BB_COMMANDS = ("0111", "0166", "0167", "015f", "0128")
BB_BODY_BYTES = (28, 28, 2, 4, 12)
BB_COMMON_SCENARIOS = (
    "active", "inactive", "cold-inactive", "route-opaque", "dynamic-source", "repeat", "repeat-busy",
    "mixed", "banks-mixed", "mixed-address-reuse", "address-reuse", "generation-gap", "default-off", "enabled-two",
    "unrelated", "wrong-type", "wrong-native", "wrong-destination", "invalid-flags", "invalid-header-size",
    "invalid-header-high", "short-request", "long-request", "bad-source", "bound-global-source",
    "source-zero", "source-other-domain", "missing-callback", "missing-guard",
    "guard-fail", "guard-miss", "guard-lost", "bridge-error", "bridge-positive",
    "mutated-request", "mutated-source", "mutated-size", "alloc-fail", "alloc-dirty-fail", "alloc-short", "alloc-long",
    "alloc-snapshot-tail", "alloc-display-tail", "alloc-bb-tail", "alloc-max-span", "set-source-fail", "ack-write-corrupt",
    "request-free-fail", "send-fail", "inline-free", "inline-send-fail", "receive-source", "receive-size",
    "receive-destination", "receive-meta-source", "receive-meta-size", "receive-wire", "foreign-receive", "foreign-free",
    "duplicate-receive", "free-before-receive", "free-meta-source", "free-meta-size", "free-wire", "ack-free-fail",
    "no-ticket", "old-ticket", "ack-path-wire", "ack-zebra-wire", "ack-other-bb", "reentrant-free", "reentrant-dispatch",
    "result-path-fnv", "result-original-body-fnv", "result-full-wire-fnv", "result-old-length", "result-old-used",
    "result-zebra-length", "result-zebra-used", "result-inactive-receipt", "result-route-class",
    "result-duplicate-generation", "result-stale-lease", "result-wrong-geometry", "result-wrong-height",
) + tuple(f"result-{name}" for name in RESULT_FIELDS) + tuple(f"result-tail-{i}" for i in range(32)) + tuple(
    f"fresh-request-lease{suffix}" for suffix in (
        "", "-inline-free", "-inline-send-fail", "-alloc-dirty-fail", "-alloc-short", "-alloc-long",
        "-set-source-fail", "-ack-write-corrupt", "-send-fail", "-ack-free-fail", "-mixed", "-no-ticket", "-old-ticket"
    )
) + tuple(f"alloc-constant-{i}" for i in range(3))
BB_SCENARIOS = tuple(
    f"bb{command}-{case}"
    for index, (command, body_bytes) in enumerate(zip(BB_COMMANDS, BB_BODY_BYTES))
    for case in BB_COMMON_SCENARIOS + tuple(f"invalid-body-{i}" for i in range(body_bytes)) + tuple(
        f"result-input-tail-{i}" for i in range(4 + body_bytes, 32)
    ) + tuple(f"result-borrowed-bank-{i}" for i in range(5) if i != index) + (
        ("alloc-alias", "alloc-alias-interior") if command != "015f" else ()
    ) + (("gamut1",) if command == "0167" else ()) + (
        tuple(f"period-{p}" for p in (60, 50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)) +
        ("invalid-period", "invalid-period-high") if command == "0128" else ()
    )
)
BB_0166_INITIAL_SCENARIOS = tuple(case.replace('bb0166-', 'bb0166-initial-', 1)
                                 for case in BB_SCENARIOS if case.startswith('bb0166-'))
ALL_SCENARIOS = PRE_BB_SCENARIOS + BB_SCENARIOS + BB_0166_INITIAL_SCENARIOS


@pytest.mark.parametrize("sanitized", (False, True), ids=("strict", "asan-ubsan"))
def test_vdf_original_transport_owner(tmp_path, sanitized):
    sources = HERE / "device-models"
    binary = tmp_path / "functional-vdf-path"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread", *flags,
        str(sources / "functional-vdf-path.c"), str(sources / "test-functional-vdf-path.c"),
        "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    assert len(SCENARIOS) == 112 and len(OLD_SCENARIOS) == 224 and len(EXISTING_SCENARIOS) == 396
    assert len(SOURCE_PINNED_SCENARIOS) == 681 and len(LEASE_SCENARIOS) == 54
    assert len(PRE_BB_SCENARIOS) == 735 + len(BIND_SCENARIOS) + len(REFRESH_SCENARIOS) == 901
    assert len(BB_SCENARIOS) == 1041
    assert len(BB_0166_INITIAL_SCENARIOS) == 205
    assert len(ALL_SCENARIOS) == len(set(ALL_SCENARIOS))
    for case in ALL_SCENARIOS:
        result = subprocess.run([str(binary), case], capture_output=True, text=True, env=env, timeout=10)
        assert result.returncode == 0, f"HOST_TEST case={case}\n{result.stdout}\n{result.stderr}"


def test_pinned_public_vdf_source_ranges():
    report = HERE.parents[1] / 'report' / 'functional-vdf-path'
    pins = json.loads((report / 'source-pins.json').read_text())
    originals = {'cp': HERE / 'menu-root/cp/cpapp-b.bin', 'ap': HERE / 'menu-root/usr/lib/appFw.so'}
    images = {}
    for name, path in originals.items():
        raw = path.read_bytes()
        assert len(raw) == pins['artifacts'][name]['size']
        assert hashlib.sha256(raw).hexdigest() == pins['artifacts'][name]['sha256']
        images[name] = raw
    ap = images['ap']
    assert ap[:6] == b'\x7fELF\x02\x01'
    phoff = struct.unpack_from('<Q', ap, 32)[0]
    phsize, phcount = struct.unpack_from('<HH', ap, 54)
    segments = []
    for index in range(phcount):
        kind, flags, offset, va, _, filesz, memsz, _ = struct.unpack_from('<IIQQQQQQ', ap, phoff + index * phsize)
        if kind == 1:
            segments.append(dict(offset=offset, va=va, filesz=filesz, memsz=memsz, flags=flags))
    assert segments == pins['artifacts']['ap']['pt_load']
    layout = pins['layout_source']
    assert len(layout['ranges']) == layout['window_count'] == 42
    assert sum(row['size'] for row in layout['ranges']) == layout['window_bytes_with_overlap'] == 9934
    display = pins['display_source']
    assert len(display['ranges']) == display['window_count'] == 8
    assert sum(row['size'] for row in display['ranges']) == display['window_bytes_with_overlap'] == 3028
    for row in pins['reused_ranges'] + layout['ranges'] + display['ranges']:
        start, count = int(row['raw'], 16), row['size']
        assert start >= 0 and count > 0 and start + count <= len(images[row['artifact']])
        if row['artifact'] == 'cp':
            assert int(row['va'], 16) == start + 0x108000
        else:
            va = int(row['va'], 16)
            assert any(seg['va'] <= va and va + count <= seg['va'] + seg['filesz'] and
                       seg['offset'] + va - seg['va'] == start for seg in segments), row['name']
        actual = images[row['artifact']][start:start + count]
        assert hashlib.sha256(actual).hexdigest() == row['sha256'], row['name']
    packet = pins['layout_packet']
    wire = bytes.fromhex(packet['observed_original_hex'])
    body = bytes.fromhex(packet['exact_initial_case0_body32_hex'])
    assert len(wire) == 40 and struct.unpack_from('<4H', wire) == (0x200d, 0x014c, 40, 0x8001)
    assert len(body) == 32 and wire[8:] == body
    assert struct.unpack_from('<8H', body, 4) == (0, 0, 640, 480, 0, 0, 0, 0)
    assert body[22:24] == b'\0\0' and body[24:] == b'\3\0\0\0\0\0\0\0'
    assert struct.unpack('<4HI', bytes.fromhex(packet['success_hex'])) == (0x200d, 0x114c, 12, 0x8001, 0x00590000)
    display_packets = pins['display_packets']
    for name, command, body_bytes in (('peaking', 0x0152, 8), ('flag', 0x0162, 2)):
        packet = display_packets[name]
        key = 'inherited_parent_observed_hex' if name == 'peaking' else 'static_constructed_hex'
        wire = bytes.fromhex(packet[key])
        assert len(wire) == packet['request_bytes'] == body_bytes + 8
        assert struct.unpack_from('<4H', wire) == (0x200d, command, len(wire), 0x8001)
        assert packet['body_bytes'] == body_bytes
        body8 = wire[8:].ljust(8, b'\0')
        envelope16 = struct.pack('<II8s', command, body_bytes, body8)
        assert len(envelope16) == 16 and envelope16[8:8 + body_bytes] == wire[8:]
        assert envelope16[8 + body_bytes:] == b'\0' * (8 - body_bytes)
        assert struct.unpack('<4HI', bytes.fromhex(packet['success_hex'])) == (0x200d, command + 0x1000, 12, 0x8001, 0x00590000)
    peaking = bytes.fromhex(display_packets['peaking']['inherited_parent_observed_hex'])
    assert peaking[8:] == bytes((3, 0, 1, 0, 0, 235, 128, 128))
    assert len(display_packets['peaking']['body_fields']) == 8
    flag = bytes.fromhex(display_packets['flag']['static_constructed_hex'])
    assert flag[8:] == b'\0\0'
    # The source ledger records the original validation; additive lease regressions are separate.
    assert pins['implementation_validation']['scenario_count_per_build'] == len(SOURCE_PINNED_SCENARIOS)
    assert pins['implementation_validation']['source_ranges_verified'] == 70


def test_bb_neutral_packets_and_inherited_source_contract():
    report = HERE.parents[1] / "report" / "functional-vdf-path"
    pins = json.loads((report / "source-pins.json").read_text())
    source = pins["bb_startup_source"]
    assert not source["new_survey_performed"] and not source["original_windows_rerun"]
    assert len(source["ranges"]) == source["window_count"] == 19
    assert sum(row["size"] for row in source["ranges"]) == source["window_bytes_with_overlap"] == 5596
    for row in source["ranges"]:
        assert len(bytes.fromhex(row["sha256"])) == 32
        if row["artifact"] == "cp":
            assert int(row["va"], 16) == int(row["raw"], 16) + 0x108000
        else:
            assert row["artifact"] == "ap" and row["va"] == row["raw"]
    expected_bodies = (
        bytes.fromhex("00000f02") + bytes(24), b"\0\1" + bytes(26), bytes(2), bytes(4),
        b"\0\1\0\0" + struct.pack("<I", 60) + bytes(4),
    )
    for command, body in zip(BB_COMMANDS, expected_bodies):
        row = pins["bb_startup_packets"][command]
        opcode = int(command, 16)
        wire = bytes.fromhex(row["static_neutral_hex"])
        assert wire == struct.pack("<4H", 0x200d, opcode, len(body) + 8, 0x8001) + body
        assert len(wire) == row["request_bytes"] == row["body_bytes"] + 8
        canonical = struct.pack("<HH", opcode, len(body)) + body
        assert bytes.fromhex(row["canonical32_hex"]) == canonical.ljust(32, b"\0")
        assert struct.unpack("<4HI", bytes.fromhex(row["success_hex"])) == (0x200d, opcode + 0x1000, 12, 0x8001, 0)
    policy = pins["bb_startup_policy"]
    assert (policy["opcode"], policy["input_bytes"], policy["result_bytes"], policy["tail_offset"],
            policy["class"], policy["proof_kind"]) == (9, 32, 192, 160, 5, 5)
    assert not policy["cp_mode1_prerequisite"] and not policy["status_or_590000"]
    assert pins["bb_startup_packets"]["015f"]["ap_parser"] == "0x034e4500"
    validation = pins["bb_startup_owner_validation"]
    assert validation["scenario_count_per_build"] == len(PRE_BB_SCENARIOS) + len(BB_SCENARIOS) == 1942
    initial = pins['bb_0166_observed_initial']
    body = bytes.fromhex('00010000000000000000000008000000070000000100000001000000')
    assert bytes.fromhex(initial['body28_hex']) == body
    assert bytes.fromhex(initial['stack_held_wire36_hex']) == struct.pack('<4H', 0x200d, 0x166, 36, 0x8001) + body
    assert bytes.fromhex(initial['canonical32_hex']) == struct.pack('<2H', 0x166, 28) + body
    assert struct.unpack('<BBH6I', body) == (0, 1, 0, 0, 0, 8, 7, 1, 1)
    assert initial['builder_va'] == '0x34ebb84' and initial['builder_bytes'] == 216
    with (HERE / 'menu-root/usr/lib/appFw.so').open('rb') as original:
        original.seek(int(initial['builder_va'], 16))
        builder = original.read(initial['builder_bytes'])
    assert len(builder) == 216 and hashlib.sha256(builder).hexdigest() == initial['builder_sha256']
    assert not initial['live_request_memory_read'] and not initial['native_AP_completion_verified']
    assert initial['software_identity_policy'] == 'explicit-neutral-or-exact-observed-initial-tuple-RGB-identity'
    assert initial['scenario_count_per_build'] == len(BB_0166_INITIAL_SCENARIOS)
    assert validation["new_bb_scenarios"] == len(BB_SCENARIOS)
    assert not validation["real_core_combination_verified_here"] and not validation["native_ap_vm_tested"]


def test_production_owner_keeps_real_bridge_dependency(tmp_path):
    obj = tmp_path / "functional-vdf-path.o"
    built = subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread", "-c",
        str(HERE / "device-models" / "functional-vdf-path.c"), "-o", str(obj),
    ], capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stdout + symbols.stderr
    assert " U fcam_bridge_call" in symbols.stdout
    assert " U fcam_bridge_bb_startup_config" in symbols.stdout
    assert "fcam_bridge_init" not in symbols.stdout
    assert "functional_vdf_path_test_" not in symbols.stdout
