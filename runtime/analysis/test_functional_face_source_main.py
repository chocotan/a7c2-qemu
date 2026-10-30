# SPDX-License-Identifier: MIT
"""Extract production Main verbatim; run HOST ONLY strict and ASan/UBSan C checks.

Only HOST_TEST pagemap/bridge and typed original-command/current-metadata ABI
boundaries are fixtures. No Sony library, VM, QEMU, SD or physical device runs.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import pytest

HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parents[1] / "validation/tmp/functional-face-source-main"
MODES = (
    "three-units", "baseline", "preflight", "bridge", "metadata", "native-share", "native-open",
    "cleanup-close", "cleanup-free", "callback-pid", "callback-tid", "callback-code",
    "callback-code-short", "callback-code-drift", "callback-context", "callback-context-short",
    "callback-context-drift", "callback-extent", "callback-base", "callback-module", "callback-dladdr",
)
LINKED = (
    "functional-face-source-snapshot.c", "functional-face-ap-observer.c", "functional-face-runtime.c",
    "functional-face-registry.c", "functional-face-dmm.c", "functional-face-transfer.c",
    "functional-face-sdk.c", "dmm-service.c",
)


def _region(source, first, after):
    start = source.index(first)
    end = source.index(after, start)
    return source[start:end], {
        "start_marker": first, "end_marker_exclusive": after,
        "start_line": source.count("\n", 0, start) + 1,
        "end_line_exclusive": source.count("\n", 0, end) + 1,
        "sha256": hashlib.sha256(source[start:end].encode()).hexdigest(),
    }


def _receipt(path, command, result):
    path.write_text(json.dumps({"command": command, "returncode": result.returncode,
                               "stdout": result.stdout, "stderr": result.stderr}, indent=2) + "\n")


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def actual_main_executable(request, tmp_path_factory):
    raw = (HERE / "menu-observe.c").read_bytes()
    source = raw.decode()
    main, main_region = _region(source, "struct functional_face_source_transaction {",
                               "static int (*real_interchip_transfer_async)")
    births, births_region = _region(source, "struct functional_face_native_proc_birth {",
                                   "static unsigned int functional_face_native_proc_busy;")
    declarations, declarations_region = _region(source, "struct functional_face_sdk_origin {",
                                               "static int functional_face_sdk_origin(")
    assert main.count("static int functional_face_try_source_snapshot(") == 1
    assert main.count("((void (*)(int32_t,void *))callback)(0,(void *)context);") == 1
    assert "for(;;)usleep(10000);" in main
    assert "real_interchip_transfer_async" not in main
    assert main.count("functional_face_sdk_submit(&s->sdk,origin->api40,40,1,0,&transaction)") == 1
    template = (HERE / "test-functional-face-source-main.c").read_text()
    assert template.count("/* ACTUAL_MAIN_DECLARATIONS */") == template.count("/* ACTUAL_SOURCE_MAIN */") == 1
    mode = "asan-ubsan" if request.param else "c11"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-")
    evidence = Path(tempfile.mkdtemp(prefix=stamp + mode + "-", dir=SCRATCH))
    (evidence / "actual-source-main.log").write_text(main)
    (evidence / "actual-declarations.log").write_text(births + declarations)
    files = ("menu-observe.c", "test-functional-face-source-main.c", "test_functional_face_source_main.py",
             "functional-face-source-snapshot.h", "functional-face-source-snapshot-abi.h",
             "functional-face-sdk.h", "functional-face-transfer.h", "functional-face-runtime.h",
             "functional-face-ap-observer.h", "functional-face-proc.h", "functional-face-registry.h",
             "functional-face-dmm.h", "device-models/imaging-device.h", "dmm-service.h",
             "functional-camera-bridge.h", "functional-camera-abi.h", "functional-bb-startup-abi.h", *LINKED)
    manifest = {
        "kind": "actual-main-host-only", "build": mode,
        "regions": {"main": main_region, "births": births_region, "origin_reader": declarations_region},
        "source_hashes": {name: hashlib.sha256(raw if name == "menu-observe.c" else
                                               (HERE / name).read_bytes()).hexdigest() for name in files},
        "native_verified": False, "capture_verified": False, "physical_verified": False,
        "sony_code_executed": False, "vm_executed": False,
    }
    (evidence / "source-hashes.log").write_text(json.dumps(manifest, indent=2) + "\n")
    work = tmp_path_factory.mktemp("functional-face-source-main-" + mode)
    path, binary = work / "actual.c", work / "actual"
    path.write_text(template.replace("/* ACTUAL_MAIN_DECLARATIONS */", births + declarations)
                   .replace("/* ACTUAL_SOURCE_MAIN */", main))
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-pthread", "-DFCAM_HOST_TEST", "-fno-pie", "-no-pie", "-Wl,-Ttext-segment=0x10000000"]
    if request.param:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
    command = [*shlex.split(os.environ.get("CC", "cc")), *flags, "-I", str(HERE), str(path),
               *(str(HERE / name) for name in LINKED), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    _receipt(evidence / "compile.log", command, result)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary, evidence


@pytest.mark.parametrize("mode", MODES)
def test_actual_main_source_snapshot(actual_main_executable, mode):
    binary, evidence = actual_main_executable
    command = [str(binary), mode]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    _receipt(evidence / (mode + ".log"), command, result)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (f"FACE_SOURCE_MAIN_HOST_PASS mode={mode} actual_main=1 actual_sdk=1 actual_cp=1 "
            "host_only=1 native_verified=0 capture_verified=0 physical_verified=0") in result.stdout
    if mode == "three-units":
        assert ("MAIN_HOST_COUNTS units=3 snapshot=514304 cp_write=514304 cp_readback=514304 "
                "independent_read=514304 callbacks=3 speech_bytes=1048576 speech_unchanged=1") in result.stdout
        for index, length in enumerate((409600, 51200, 53504)):
            content = bytes(((n * 37 + index * 53 + 11) ^ (n >> 7)) & 255 for n in range(length))
            digest = 0xCBF29CE484222325
            for byte in content:
                digest = ((digest ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
            assert f"unit={0x1d9 + index:x} bytes={length} digest={digest:016x}" in result.stdout
    elif mode == "preflight":
        assert "MAIN_PREFLIGHT cases=23 unclaimed=1 output_unchanged=1 birthday_unchanged=1" in result.stdout
    elif mode != "baseline":
        assert ("first_sleep=1 result_unchanged=1 original_frame_alive=1 context_retained=1 "
                "callback=0 retry_commands=0 native_verified=0") in result.stdout
