"""HOST_TEST only: bounded memory parsing, real x264 NAL roundtrip and decode."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = (
    "avc", "hevc", "changes", "opaque", "declared", "types", "missing",
    "counts", "spans", "lengths", "headers", "ranges", "capacity", "alias",
    "arguments", "pointer-wrap", "exact-bounds",
)
ES_BASE = 0x100000000
CORRECTION = 0x4000
FIRST_OFFSET = 17


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def paramsets_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-paramsets") / "selfcheck"
    command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command += [str(HERE / "native-paramsets.c"), str(HERE / "test-native-paramsets.c"), "-o", str(exe)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return exe


def run_selfcheck(exe, mode, data=None):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(exe), mode], input=data, capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stderr.decode(errors="replace"))
    assert not result.stderr, result.stderr.decode(errors="replace")
    return result.stdout


@pytest.mark.parametrize("mode", MODES)
def test_native_paramsets_selfchecks(paramsets_exe, mode):
    assert run_selfcheck(paramsets_exe, mode) == b""


@pytest.fixture(scope="session")
def host_avc():
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "installed FFmpeg/ffprobe are required"
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         "color=c=red:s=16x16:r=1:d=1", "-frames:v", "1", "-c:v", "libx264",
         "-threads", "1", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p",
         "-x264-params", "repeat-headers=1:annexb=1:keyint=1", "-f", "h264", "pipe:1"],
        check=True, capture_output=True, timeout=30,
    )
    # Annex-B splitting is exclusively a HOST fixture producer, never parser logic.
    starts = list(re.finditer(rb"\x00\x00(?:\x00)?\x01", result.stdout))
    assert starts and starts[0].start() == 0
    nals = [result.stdout[start.end():starts[i + 1].start() if i + 1 < len(starts) else len(result.stdout)]
            for i, start in enumerate(starts)]
    assert all(nals)
    sps = [nal for nal in nals if nal[0] & 31 == 7]
    pps = [nal for nal in nals if nal[0] & 31 == 8]
    assert len(sps) == len(pps) == 1
    assert any(nal[0] & 31 == 5 for nal in nals)
    return nals, sps[0], pps[0]


def test_native_paramsets_real_avc_roundtrip_decode(paramsets_exe, host_avc):
    nals, sps, pps = host_avc
    info = bytearray([0xD3] * 96)
    info[0:2] = bytes((4, 0xE6))
    struct.pack_into("<Q", info, 8, ES_BASE + FIRST_OFFSET - CORRECTION)
    struct.pack_into("<I", info, 0x10, 0)  # Informational, deliberately not the group size.
    struct.pack_into("<HBB", info, 0x28, 0, 0, 0xF1)
    struct.pack_into("<HBB", info, 0x2C, 4 + len(sps), 1, 0xF2)
    struct.pack_into("<HBB", info, 0x30, 4 + len(pps), 1, 0xF3)
    es = b"\xAD" * FIRST_OFFSET + struct.pack(">I", len(sps)) + sps + struct.pack(">I", len(pps)) + pps
    result = run_selfcheck(paramsets_exe, "host-roundtrip", bytes(info) + es)
    sps_len, = struct.unpack_from(">I", result)
    parsed_sps = result[4:4 + sps_len]
    pps_len, = struct.unpack_from(">I", result, 4 + sps_len)
    parsed_pps = result[8 + sps_len:]
    assert len(parsed_sps) == sps_len and len(parsed_pps) == pps_len
    assert parsed_sps == sps and parsed_pps == pps  # Full bytes, including emulation-prevention bytes.
    replacements = {7: parsed_sps, 8: parsed_pps}
    stream = b"".join(b"\x00\x00\x00\x01" + replacements.get(nal[0] & 31, nal) for nal in nals)
    metadata = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-f", "h264", "-i", "pipe:0", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height:frame=width,height,key_frame",
         "-show_frames", "-of", "json"],
        input=stream, check=True, capture_output=True, timeout=30,
    ).stdout)
    assert metadata["streams"][0]["codec_name"] == "h264"
    assert metadata["streams"][0]["width"] == metadata["streams"][0]["height"] == 16
    assert len(metadata["frames"]) == 1 and metadata["frames"][0]["key_frame"] == 1
    decoded = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", "1", "-f", "h264",
         "-i", "pipe:0", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=stream, check=True, capture_output=True, timeout=30,
    ).stdout
    assert len(decoded) == 16 * 16 * 3
    assert min(decoded[0::3]) > 240 and max(decoded[1::3]) < 10 and max(decoded[2::3]) < 10


def test_native_paramsets_public_source_pins():
    manifest = json.loads((HERE / "source-pins.json").read_text())
    assert manifest["native_capture"] is False
    assert manifest["window_bytes"] == sum(int(pin["length"], 16) for pin in manifest["windows"]) == 3296
    assert len(manifest["windows"]) == 8
    base = HERE.parent.parent / "runtime/analysis/menu-root"
    artifact = manifest["artifacts"][0]
    path = base / artifact["path"]
    if not path.is_file():
        pytest.skip("public ALLLANG menu-root asset required for original libmpr pin verification")
    data = path.read_bytes()
    assert len(data) == artifact["size"]
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    assert data[:6] == b"\x7fELF\x02\x01"  # ELF64 little endian.
    phoff, = struct.unpack_from("<Q", data, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    loads = []
    for index in range(phnum):
        position = phoff + index * phentsize
        kind, = struct.unpack_from("<I", data, position)
        if kind == 1:
            offset, address = struct.unpack_from("<QQ", data, position + 8)
            length, = struct.unpack_from("<Q", data, position + 32)
            loads.append((offset, address, length))
    assert loads == [(int(load["file_offset"], 16), int(load["virtual_address"], 16),
                      int(load["file_size"], 16)) for load in artifact["pt_load"]]
    for pin in manifest["windows"]:
        assert pin["artifact"] == artifact["path"]
        address, offset, length = (int(pin[field], 16) for field in ("virtual_address", "file_offset", "length"))
        matching = [(fo, va) for fo, va, n in loads if va <= address and address + length <= va + n]
        assert len(matching) == 1
        assert offset == matching[0][0] + address - matching[0][1]
        raw = data[offset:offset + length]
        assert len(raw) == length and hashlib.sha256(raw).hexdigest() == pin["sha256"]
