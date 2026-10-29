"""HOST-only opaque-slot checks; no VM, media output, or hardware access."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = (
    "copy-order", "copy-empty", "copy-invalid", "copy-alias", "copy-overflow",
    "advance-min", "advance-count", "advance-users", "advance-spans", "host-flow",
)


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def ring_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-video-ring") / "selfcheck"
    command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command += [str(HERE / "native-ring.c"), str(HERE / "test-native-ring.c"), "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


@pytest.mark.parametrize("mode", MODES)
def test_consumer_slots(ring_exe, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(ring_exe), mode], capture_output=True, text=True, env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)


def test_source_pins():
    manifest = json.loads((HERE / "source-pins.json").read_text())
    base = HERE / manifest["source_root"]
    assert manifest["native_gaps"] == 63 and manifest["native_execution"] == "unsupported"
    assert len(manifest["windows"]) == manifest["window_count"] == 10
    assert sum(int(p["length"], 0) for p in manifest["windows"]) == manifest["total_window_bytes"] == 4760
    assert len({p["id"] for p in manifest["windows"]}) == 10
    cache = {}
    for relative, artifact in manifest["artifacts"].items():
        data = (base / relative).read_bytes()
        assert len(data) == artifact["size"]
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
        cache[relative] = data
    for pin in manifest["windows"]:
        offset, length = int(pin["file_offset"], 0), int(pin["length"], 0)
        assert offset >= 0 and length > 0
        if pin["artifact"] == "usr/lib/libmpr.so":
            assert offset + length <= 0x2E4534
        raw = cache[pin["artifact"]][offset:offset + length]
        assert len(raw) == length
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], pin["id"]
