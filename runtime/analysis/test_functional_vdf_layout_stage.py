"""Bounded layout stage tests; mock OSAL/model192 is no native or capture proof."""
from pathlib import Path
import hashlib
import json
import os
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "device-models"
REPORT = HERE.parents[1] / "report" / "functional-vdf-layout-stage"
SCENARIOS = (
    "repeat", "inline-free", "inline-send-fail", "shape", "profile", "readback-fault",
    "request-mutation", "source-mutation", "live-alias", "span", "alloc-fail", "request-free-fail", "ack-free-fail",
    "ack-mutation", "stale-ticket-reuse", "send-fail", "foreign-receive", "foreign-free",
    "receive-source", "receive-size", "receive-wire", "reentry", "reentrant-free", "fork", "late-bind",
) + tuple(f"private-alias-{i}" for i in range(5))


@pytest.mark.parametrize("sanitized", (False, True), ids=("c11-strict", "asan-ubsan"))
def test_layout_stage_transport(tmp_path, sanitized):
    binary = tmp_path / "layout-stage"
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitized else []
    built = subprocess.run([
        "cc", "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
        "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread", *flags,
        str(SOURCES / "functional-vdf-layout-stage.c"), str(SOURCES / "test-functional-vdf-layout-stage.c"),
        "-o", str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    for case in SCENARIOS:
        result = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=10, env=env)
        assert result.returncode == 0, f"HOST_TEST {case}\n{result.stdout}\n{result.stderr}"


def test_production_stage_has_no_frame_rpc(tmp_path):
    obj = tmp_path / "layout-stage.o"
    built = subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread", "-c",
        str(SOURCES / "functional-vdf-layout-stage.c"), "-o", str(obj),
    ], capture_output=True, text=True, timeout=20)
    assert built.returncode == 0, built.stdout + built.stderr
    symbols = subprocess.run(["nm", str(obj)], capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stderr
    for forbidden in ("fcam_bridge_", "functional_vdf_path_", "functional_vdf_layout_stage_test_", "mailbox", "malloc"):
        assert forbidden not in symbols.stdout
    assert "functional_vdf_layout_stage_bind_applied" in symbols.stdout


def test_public_source_pins():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    images = {}
    for name, artifact in pins["artifacts"].items():
        raw = (HERE / artifact["runtime_relative_path"]).read_bytes()
        assert len(raw) == artifact["size"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        images[name] = raw
    ap = images["ap"]
    phoff = struct.unpack_from("<Q", ap, 32)[0]
    phsize, phcount = struct.unpack_from("<HH", ap, 54)
    segments = []
    for index in range(phcount):
        kind, flags, offset, va, _, filesz, memsz, _ = struct.unpack_from("<IIQQQQQQ", ap, phoff + index * phsize)
        if kind == 1:
            segments.append(dict(offset=offset, va=va, filesz=filesz, memsz=memsz, flags=flags))
    assert segments == pins["artifacts"]["ap"]["pt_load"]
    for row in pins["ranges"]:
        raw, va, count = int(row["raw_start"], 16), int(row["va_start"], 16), row["bytes"]
        actual = images[row["artifact"]][raw:raw + count]
        assert actual.hex() == row["raw_hex"]
        assert hashlib.sha256(actual).hexdigest() == row["sha256"]
        if row["artifact"] == "cp":
            assert va == raw + 0x108000
        else:
            assert any(s["va"] <= va and va + count <= s["va"] + s["filesz"] and
                       s["offset"] + va - s["va"] == raw for s in segments)
    policy = pins["software_policy"]
    wire = bytes.fromhex(policy["request40_hex"])
    assert struct.unpack_from("<4H", wire) == (0x200D, 0x014C, 40, 0x8001)
    assert wire[8:] == bytes.fromhex(policy["bank32_hex"])
    assert struct.unpack("<4HI", bytes.fromhex(policy["ack12_hex"])) == (0x200D, 0x114C, 12, 0x8001, 0x00590000)
    assert policy["stage_only"] == 1 and not policy["semantic_applied"] and not policy["frame_consumed"]
