"""HOST_TEST strict AU validation; source declarations are not encoder evidence."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess

from elftools.elf.elffile import ELFFile
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MODES = ("avc", "hevc", "wrap", "framing", "arguments", "arithmetic", "aliases", "metadata")


@pytest.fixture(scope="session", params=(False, True), ids=("c11", "asan-ubsan"))
def lengths_exe(request, tmp_path_factory):
    exe = tmp_path_factory.mktemp("native-video-lengths") / "selfcheck"
    cmd = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g",
           "-ffunction-sections", "-fdata-sections"]
    if request.param:
        cmd += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    cmd += [str(HERE / "native-lengths.c"), str(HERE / "test-native-lengths.c"),
            str(HERE.parent / "native-video-au-contract/native-au.c"),
            str(HERE.parent / "native-video-binding/native-video.c"),
            "-Wl,--gc-sections", "-o", str(exe)]
    built = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stderr
    return exe


def run_check(exe, *args, data=None):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(exe), *map(str, args)], input=data,
                            capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, (args, result.returncode, result.stdout, result.stderr)
    assert result.stdout == b"HOST_TEST strict BE32 lengths passed\n"


@pytest.mark.parametrize("mode", MODES)
def test_strict_lengths(lengths_exe, mode):
    run_check(lengths_exe, mode)


def ffmpeg(*args, data=None):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args],
                            input=data, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_real_avc_coded_bytes_preserved(lengths_exe):
    # TEST ONLY: generate one actual coded AU in memory, then supply BE32 bytes.
    annexb = ffmpeg("-f", "lavfi", "-i", "testsrc2=size=32x32:rate=1",
                   "-frames:v", "1", "-c:v", "libx264", "-threads", "1",
                   "-preset", "ultrafast", "-tune", "zerolatency",
                   "-x264-params", "aud=1:repeat-headers=1", "-f", "h264", "pipe:1")
    starts = list(re.finditer(b"\x00\x00\x00\x01|\x00\x00\x01", annexb))
    assert starts and starts[0].start() == 0
    nals = [annexb[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(annexb)]
            for i, m in enumerate(starts)]
    assert all(nals)
    kinds = {nal[0] & 31 for nal in nals}
    assert {5, 6, 7, 8, 9} <= kinds
    be32 = b"".join(len(nal).to_bytes(4, "big") + nal for nal in nals)
    recovered, position = [], 0
    while position < len(be32):
        length = int.from_bytes(be32[position:position + 4], "big")
        position += 4
        recovered.append(be32[position:position + length])
        position += length
    assert position == len(be32) and recovered == nals
    assert b"".join(recovered) == b"".join(nals)  # No coded byte is changed or filtered.
    # Prefix/body splits include each of the first four bytes at the ring tail.
    body_tail = 4 + len(nals[0]) + 4 + 1
    for tail in (0, 1, 2, 3, 4, body_tail):
        run_check(lengths_exe, "fixture", len(nals), tail, data=be32)
    # Independent decoder checks original and TEST ONLY reconstruction to null.
    reconstructed = b"".join(b"\x00\x00\x00\x01" + nal for nal in recovered)
    for stream in (annexb, reconstructed):
        assert ffmpeg("-xerror", "-f", "h264", "-i", "pipe:0", "-map", "0:v:0",
                      "-frames:v", "1", "-f", "null", "-", data=stream) == b""


def public_source():
    manifest = json.loads((HERE / "source-pins.json").read_text())
    artifact = manifest["artifact"]
    data = (ROOT / "runtime/analysis/menu-root" / artifact["path"]).read_bytes()
    assert len(data) == artifact["size"] == 3528576
    assert hashlib.sha256(data).hexdigest() == artifact["sha256"]
    elf = ELFFile(io.BytesIO(data))
    assert elf.elfclass == 64 and elf.little_endian
    assert elf["e_machine"] == "EM_AARCH64"
    return manifest, data, elf


def verify_windows(data, windows, segments):
    for pin in windows:
        va, length = int(pin["virtual_address"], 16), pin["length"]
        segment = next(s for s in segments if s["p_vaddr"] <= va and
                       va + length <= s["p_vaddr"] + s["p_filesz"])
        offset = segment["p_offset"] + va - segment["p_vaddr"]
        assert offset == pin["file_offset"]
        raw = data[offset:offset + length]
        assert len(raw) == length
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], pin["id"]


def test_new_staging_pins_and_actual_relocation():
    manifest, data, elf = public_source()
    segments = [s for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"]
    assert len(segments) == 2
    for actual, recorded in zip(segments, manifest["load_segments"]):
        assert actual["p_vaddr"] == int(recorded["virtual_address"], 16)
        assert actual["p_offset"] == recorded["file_offset"]
        assert actual["p_filesz"] == recorded["file_size"]
    assert manifest["positive_only"] is True
    assert manifest["native_capture"] is False and manifest["native_gaps"] == 63
    expected = manifest["expected_container_format"]
    assert expected["source_expectation_closed"] is True
    assert expected["length_bytes"] == 4 and expected["length_size_minus_one"] == 3
    assert expected["original_encoder_producer_closed"] is False
    assert expected["original_lifecycle_closed"] is False
    assert len(manifest["windows"]) == 11
    assert sum(p["length"] for p in manifest["windows"]) == manifest["total_window_bytes"] == 696
    verify_windows(data, manifest["windows"], segments)
    binding = manifest["relocation"]
    got_va = int(binding["virtual_address"], 16)
    second = segments[1]
    assert second["p_offset"] + got_va - second["p_vaddr"] == binding["file_offset"] == 0x2ED3C8
    relsec = elf.get_section_by_name(binding["section"])
    matches = [r for r in relsec.iter_relocations() if r["r_offset"] == got_va]
    assert len(matches) == 1
    relocation = matches[0]
    assert binding["type"] == "R_AARCH64_GLOB_DAT"
    assert relocation["r_info_type"] == binding["type_number"] == 1025
    assert relocation["r_addend"] == binding["addend"] == 0
    symbol = elf.get_section(relsec["sh_link"]).get_symbol(relocation["r_info_sym"])
    assert symbol.name == binding["symbol"] == "_Z14ff4_mpr_memcpyPvS_mPKvm"
    assert symbol["st_info"]["type"] == "STT_FUNC" and symbol["st_shndx"] != "SHN_UNDEF"
    assert symbol["st_value"] == int(binding["symbol_value"], 16) == 0x21E8A4
    assert symbol["st_size"] == binding["symbol_size"] == 20


def test_frozen_prior_pins_by_reference():
    manifest, data, elf = public_source()
    ref = manifest["prior_pins"]
    raw = (HERE / ref["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ref["manifest_sha256"]
    prior = json.loads(raw)
    assert prior["artifact"]["sha256"] == ref["same_artifact_sha256"] == manifest["artifact"]["sha256"]
    assert prior["artifact"]["path"] == manifest["artifact"]["path"]
    assert prior["artifact"]["size"] == manifest["artifact"]["size"]
    assert ref["verify_all_windows"] is True
    assert len(prior["windows"]) == ref["window_count"] == 14
    assert sum(p["length"] for p in prior["windows"]) == prior["total_window_bytes"] == ref["total_window_bytes"] == 1652
    ids = {p["id"] for p in prior["windows"]}
    assert set(ref["needed_configuration_ids"] + ref["transport_ids"]) <= ids
    verify_windows(data, prior["windows"],
                   [s for s in elf.iter_segments() if s["p_type"] == "PT_LOAD"])
