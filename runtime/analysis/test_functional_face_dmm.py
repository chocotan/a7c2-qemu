# SPDX-License-Identifier: MIT
"""Parent-batch face DMM checks; host byte consumers only, no VM or media."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
REPORT = ROOT / "report/functional-face-dmm"
MODES = (
    "units", "generation", "capacity", "rollback", "alloc-error", "alloc-null",
    "short-reply", "source-error", "register-error", "validate-error", "logical-alias",
    "request-free-error", "reply-free-error", "cleanup-error", "request-alias",
    "live-alias", "send-observed-error", "unregister-error", "malformed", "ticket",
    "inline", "threads", "fork", "missing", "overflow", "transport-guard",
    "wire-20", "wire-21", "wire-23", "wire-24", "wire-25",
)
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]


def compile_command(output, *, sanitize=False):
    flags = list(FLAGS)
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    return [*shlex.split(os.environ.get("CC", "cc")), *flags,
            str(HERE / "test-functional-face-dmm.c"), str(HERE / "dmm-service.c"),
            "-o", str(output)]


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp("functional-face-dmm") / "test-face-dmm"
    subprocess.run(compile_command(output, sanitize=request.param), check=True,
                   timeout=60, capture_output=True, text=True)
    return output


@pytest.mark.parametrize("mode", MODES)
def test_owned_cp_face_domain(executable, mode):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(executable), mode], env=env, timeout=20,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FACE_DMM_PASS mode={mode}" in result.stdout
    if mode == "units":
        assert "units=3 bytes=514304 queued=24 request_freed=24 reply_freed=24" in result.stdout
        assert "received=24 ap_consumed=18 speech_unchanged=1" in result.stdout
        assert all(value in result.stdout for value in (
            "6627b2aeec281325", "af458a1a6c4ccd25", "772e5ce0ed0d8b25"))
    if mode.startswith("wire-"):
        fixed, explicit = {"wire-20": (36, 14), "wire-21": (32, 14), "wire-23": (36, 15),
                           "wire-24": (36, 13), "wire-25": (36, 13)}[mode]
        assert (f"WIRE op={mode[5:]} golden_positive=1 fixed_byte_mutations={fixed} "
                f"explicit_negatives={explicit} unchanged_on_decline=1") in result.stdout


@pytest.mark.parametrize("caller", ["test-functional-face-dmm.c", "test-functional-face-registry.c"])
@pytest.mark.parametrize("op", [0x20, 0x21, 0x23, 0x24, 0x25], ids=lambda op: f"op-{op:02x}")
def test_caller_templates_are_original_goldens(op, caller):
    pins = json.loads((REPORT / "source-pins.json").read_text())["wire_contract"]
    goldens = [row for row in pins["golden_op40"] if not row.get("variant")]
    expected = next(row for row in goldens if int.from_bytes(bytes.fromhex(row["hex"])[:2], "little") == op)
    data = bytes.fromhex(expected["hex"])
    assert len(data) == expected["bodylen"] == 40
    assert hashlib.sha256(data).hexdigest() == expected["sha256"]
    source = (HERE / caller).read_text()
    block = re.search(r"request_goldens\[\]\s*=\s*\{(.*?)\n\};", source, re.S)
    assert block
    templates = {int(code, 16): bytes.fromhex(body) for code, body in re.findall(
        r'\{(0x[0-9a-f]+), "([0-9a-f]{80})"\}', block[1])}
    assert set(templates) == {0x20, 0x21, 0x23, 0x24, 0x25}
    assert templates[op] == data


def test_final_wire_source_pins():
    pins = json.loads((REPORT / "source-pins.json").read_text())["wire_contract"]
    assets = {}
    for key, artifact in pins["artifacts"].items():
        path = ROOT / artifact["path"]
        if not path.is_file():
            pytest.skip(f"original ALLLANG artifact required: {artifact['path']}")
        data = path.read_bytes()
        assert len(data) == artifact["size"]
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"], key
        assets[key] = data
    assert len(assets) == 3
    for pin in pins["windows"]:
        data = assets[pin["source"]]
        at = pin["file_offset"]
        raw = data[at:at + pin["bytes"]]
        assert len(raw) == pin["bytes"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"], pin["name"]
        if pin["section"] is None:
            assert window(data, pin["va"], pin["bytes"]) == (at, raw)
    assert len(pins["windows"]) == 8 and sum(pin["bytes"] for pin in pins["windows"]) == 5824
    assert pins["implemented_opcodes"] == [0x20, 0x21, 0x23, 0x24, 0x25]
    assert pins["source_only_opcodes"] == [0x2a]
    assert pins["face_mode"] == 0 and pins["new_decompiler_runs"] == 0
    assert pins["reply_policy"] == "existing dmm-service software policy; original CP producer unpinned"


def window(binary, va, length):
    assert binary[:6] == b"\x7fELF\x02\x01"
    phoff = struct.unpack_from("<Q", binary, 32)[0]
    stride, count = struct.unpack_from("<HH", binary, 54)
    for index in range(count):
        typ, _flags, offset, start, _pa, filesz, _memsz, _align = struct.unpack_from(
            "<IIQQQQQQ", binary, phoff + stride * index)
        if typ == 1 and start <= va and length <= filesz - (va - start):
            at = offset + va - start
            result = binary[at:at + length]
            assert len(result) == length
            return at, result
    raise ValueError("no file-backed PT_LOAD")


def test_inherited_original_source_and_config_pins():
    pins = json.loads((REPORT / "source-pins.json").read_text())
    assets = {}
    for key, artifact in pins["artifacts"].items():
        path = ROOT / artifact["path"]
        if not path.is_file():
            pytest.skip(f"private original artifact required: {artifact['path']}")
        data = path.read_bytes()
        assert len(data) == artifact["size"]
        assert hashlib.sha256(data).hexdigest() == artifact["sha256"], key
        assets[key] = data
    for pin in pins["windows"]:
        offset, data = window(assets["appfw"], int(pin["va"], 16), pin["bytes"])
        assert offset == int(pin["file_offset"], 16)
        assert hashlib.sha256(data).hexdigest() == pin["sha256"], pin["name"]
    assert len(pins["windows"]) == 10 and sum(pin["bytes"] for pin in pins["windows"]) == 6752
    for domain, rows in pins["config_records"].items():
        for row in rows:
            for field in ("unit", "extent"):
                at = row[f"{field}_offset"]
                raw = bytes.fromhex(row[f"{field}_raw"])
                assert assets[domain][at:at + len(raw)] == raw
            assert struct.unpack_from("<I", bytes.fromhex(row["extent_raw"]), 12)[0] == row["bytes"]
    source = (HERE / "functional-face-dmm.c").read_text()
    capacity_array = re.search(r"capacities\[FUNCTIONAL_FACE_DMM_UNITS\]\s*=\s*\{([^}]+)\}", source)
    assert capacity_array
    assert [int(value.strip(), 0) for value in capacity_array[1].split(",")] == [
        row["bytes"] for row in pins["config_records"]["cp"]]
    assert [row["unit"] for row in pins["config_records"]["cp"]] == [0x1D9, 0x1DA, 0x1DB]
    assert pins["claims"] == {
        "host_model": True, "native_ap_consumed": False, "physical_asic_verified": False,
        "original_cp_verified": False, "capture_verified": False,
    }


def test_strict_standalone_module_compiles(tmp_path):
    output = tmp_path / "functional-face-dmm.so"
    subprocess.run([*shlex.split(os.environ.get("CC", "cc")), *FLAGS, "-fPIC", "-shared",
                    str(HERE / "functional-face-dmm.c"), "-o", str(output)],
                   check=True, timeout=60, capture_output=True, text=True)
    symbols = subprocess.run(["nm", "-g", "--defined-only", str(output)],
                             check=True, timeout=10, capture_output=True, text=True).stdout
    names = {line.split()[-1] for line in symbols.splitlines()}
    assert {name for name in names if name.startswith("functional_face_dmm_")} == {
        "functional_face_dmm_enable", "functional_face_dmm_snapshot", "functional_face_dmm_shutdown",
        "functional_face_dmm_dispatch", "functional_face_dmm_receive", "functional_face_dmm_release_reply",
        "functional_face_dmm_borrowed_span", "functional_face_dmm_write", "functional_face_dmm_read",
        "functional_face_dmm_release_borrow",
    }


def test_aarch64_hand_declared_guest_libc_225(tmp_path):
    compiler = shutil.which("clang")
    reader = shutil.which("aarch64-linux-gnu-readelf")
    if not compiler or not reader:
        pytest.skip("requires installed clang/lld and AArch64 readelf")
    library = HERE / "menu-root/lib"
    names = ("libc-2.25.so", "libpthread-2.25.so", "ld-2.25.so")
    if not all((library / name).is_file() for name in names):
        pytest.skip("private guest libc 2.25 required")
    output = tmp_path / "face-dmm-aarch64.so"
    subprocess.run([compiler, "--target=aarch64-linux-gnu", "-fuse-ld=lld", "-nostdlib",
                    "-O2", "-mno-outline-atomics", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-pedantic", "-DFULL_IMAGING_GUEST", "-isystem", "/usr/aarch64-linux-gnu/include",
                    "-shared", "-fPIC", "-Wl,--no-undefined", str(HERE / "functional-face-dmm.c"),
                    *(str(library / name) for name in names), "-o", str(output)],
                   check=True, timeout=60, capture_output=True, text=True)
    imported = subprocess.run([reader, "--dyn-syms", "-W", str(output)],
                              check=True, timeout=10, capture_output=True, text=True).stdout
    assert "__isoc23" not in imported and "__aarch64_" not in imported
    for name in ("mmap", "munmap", "getpid", "syscall", "sysconf", "pthread_mutex_lock", "memcpy"):
        assert re.search(rf"\b{name}@GLIBC_2\.17\b", imported), name
    versions = subprocess.run([reader, "--version-info", "-W", str(output)],
                              check=True, timeout=10, capture_output=True, text=True).stdout
    assert set(re.findall(r"Name: (GLIBC_\d+\.\d+)", versions)) == {"GLIBC_2.17"}
