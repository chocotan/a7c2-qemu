"""Synthetic HOST protocol/lease fixtures; media is confined to anonymous pipes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODES = ("wire", "encopen", "ok", "acquire", "release", "write", "read", "corrupt", "key", "layout", "small")


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def native_video_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-video-binding") / "selfcheck"
    flags = subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libavcodec", "libavformat", "libavutil", "libswscale"], text=True
    ).split()
    command = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command += [str(HERE / "native-video.c"), str(HERE / "test-native-video-binding.c"),
                str(HERE.parent / "virtual-video-engine/video-engine.c"), "-o", str(exe), *flags]
    subprocess.run(command, check=True, capture_output=True)
    return exe


def run_selfcheck(exe, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(exe), mode], capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, (mode, result.returncode, result.stderr.decode(errors="replace"))
    return result


@pytest.mark.parametrize("mode", MODES)
def test_native_video_binding_checks(native_video_exe, mode):
    run_selfcheck(native_video_exe, mode)


def test_native_video_binding_pipe_decode(native_video_exe):
    assert shutil.which("ffmpeg"), "installed ffmpeg is required for independent decoding"
    packet = run_selfcheck(native_video_exe, "emit").stdout
    assert packet.startswith((b"\x00\x00\x00\x01", b"\x00\x00\x01"))
    decoded = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "h264", "-i", "pipe:0",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        input=packet, capture_output=True, check=True, timeout=30,
    ).stdout
    frame_size = 64 * 48 * 3
    assert len(decoded) == 2 * frame_size
    expected = bytearray()
    for y in range(48):
        for x in range(64):
            expected.extend((230 if x < 32 else 12, 180 if y < 24 else 24, x * 3))
    error = sum(abs(a - b) for a, b in zip(decoded[:frame_size], expected)) / frame_size
    inverted = sum(abs(a - (255 - b)) for a, b in zip(decoded[frame_size:], expected)) / frame_size
    assert error < 8 and inverted < 8
    assert sum(abs(a - b) for a, b in zip(decoded[:frame_size], decoded[frame_size:])) / frame_size > 60


def test_original_encopen_parameter_producer_source_pins():
    runpy.run_path(str(HERE.parent / "native-video-open-parameter-producer/verify.py"))


def test_native_video_binding_source_pins():
    base = HERE.parent.parent / "runtime/analysis/menu-root"
    manifest = json.loads((HERE / "source-pins.json").read_text())
    cache = {}
    for pin in manifest["windows"]:
        relative = pin["artifact"]
        if relative not in cache:
            cache[relative] = (base / relative).read_bytes()
        data = cache[relative]
        assert hashlib.sha256(data).hexdigest() == pin["artifact_sha256"]
        raw = data[pin["file_offset"]:pin["file_offset"] + pin["length"]]
        assert len(raw) == pin["length"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
