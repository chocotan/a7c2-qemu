"""HOST_TEST opaque bytes and original public-libmpr provenance, no media files."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = ("metadata", "opaque", "ring", "arguments", "arithmetic", "alias", "existing")


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def au_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-video-au-contract") / "selfcheck"
    command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
               "-ffunction-sections", "-fdata-sections"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    # Keep the actual parser; discard unrelated encoder functions, with no stubs.
    command += [str(HERE / "native-au.c"), str(HERE / "test-native-au.c"),
                str(HERE.parent / "native-video-binding/native-video.c"),
                "-Wl,--gc-sections", "-o", str(exe)]
    built = subprocess.run(command, capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return exe


@pytest.mark.parametrize("mode", MODES)
def test_opaque_au_contract(au_exe, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(au_exe), mode], capture_output=True, text=True,
                            env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr)
    assert result.stdout == "HOST_TEST opaque AU contract passed\n"


def test_public_source_pins():
    manifest = json.loads((HERE / "source-pins.json").read_text())
    artifact = manifest["artifact"]
    data = (HERE.parent.parent / "runtime/analysis/menu-root" / artifact["path"]).read_bytes()
    assert len(data) == artifact["size"] == 3528576
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    assert data[:6] == b"\x7fELF\x02\x01"
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 54)
    loads = [struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
             for i in range(phnum)]
    first = next(p for p in loads if p[0] == 1)
    assert first[2] == first[3] == 0 and first[5] == 0x2E4534
    assert manifest["positive_only"] is True
    assert manifest["native_capture"] is False and manifest["native_gaps"] == 63
    assert len(manifest["windows"]) == 14
    assert sum(pin["length"] for pin in manifest["windows"]) == manifest["total_window_bytes"] == 1652
    for pin in manifest["windows"]:
        assert pin["file_offset"] == int(pin["virtual_address"], 16)
        assert 0 <= pin["file_offset"] < pin["file_offset"] + pin["length"] <= first[5]
        raw = data[pin["file_offset"]:pin["file_offset"] + pin["length"]]
        assert len(raw) == pin["length"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], pin["id"]
