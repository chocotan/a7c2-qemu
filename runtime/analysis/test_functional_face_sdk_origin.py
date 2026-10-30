# SPDX-License-Identifier: MIT
"""Run the unmodified main API40 origin/export against real decoder/AP/CP code.

Only host ABI boundaries are mocked: dladdr, /proc/self/mem, syscall(178),
logging, resolver and SDK entry. The return-PC macro supplies a logical native
caller; no Sony code, VM, native provider or capture pipeline is executed.
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
VALIDATION = HERE.parents[1] / "validation/tmp/functional-face-sdk-origin"
SCENARIOS = (
    "units", "gates", "modules", "call-code", "callback-code", "api-prefix",
    "descriptors", "schema", "pointers", "context", "cp-lifetime", "ap-facts",
    "metadata", "fork-pid-tid", "wrapper-returns", "wrapper-rejections", "wrapper-resolver", "wrapper-handled",
)
LINKED = (
    "functional-face-transfer.c", "functional-face-ap-observer.c", "functional-face-dmm.c",
    "functional-face-registry.c", "dmm-service.c",
)


def receipt(path, command, result):
    path.write_text(json.dumps({"command": command, "returncode": result.returncode,
                                "stdout": result.stdout, "stderr": result.stderr},
                               indent=2) + "\n")


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def sdk_origin_binary(tmp_path_factory, request):
    source_bytes = (HERE / "menu-observe.c").read_bytes()
    source = source_bytes.decode()
    start = source.index("struct functional_face_sdk_origin {")
    end = source.index("static void native_hdmi_video_received(", start)
    glue = source.index("struct functional_face_source_transaction {", start)
    wrapper = source.index("static int (*real_interchip_transfer_async)", glue)
    primitive = source[start:glue] + source[wrapper:end]
    assert primitive.count("static int functional_face_sdk_origin(") == 1
    assert primitive.count("int interchip_transfer_async(") == 1
    fixture = (HERE / "test-functional-face-sdk-origin.c").read_text()
    assert fixture.count("/* ACTUAL_SDK_ORIGIN */") == 1
    mode = "asan-ubsan" if request.param else "c11"
    VALIDATION.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-")
    evidence = Path(tempfile.mkdtemp(prefix=f"{stamp}{mode}-", dir=VALIDATION))
    evidence.joinpath("actual-origin.c").write_text(primitive)
    files = ("menu-observe.c", "test_functional_face_sdk_origin.py", "test-functional-face-sdk-origin.c",
             "test-functional-face-runtime.c", "functional-face-runtime.c", "functional-face-transfer.h",
             "functional-face-ap-observer.h", "functional-face-proc.h", *LINKED)
    hashes = {name: hashlib.sha256(source_bytes if name == "menu-observe.c" else
                                   (HERE / name).read_bytes()).hexdigest() for name in files}
    hashes["actual-origin.c"] = hashlib.sha256(primitive.encode()).hexdigest()
    evidence.joinpath("source-hashes.json").write_text(json.dumps(hashes, indent=2) + "\n")
    work = tmp_path_factory.mktemp(f"functional-face-sdk-origin-{mode}")
    path, binary = work / "actual.c", work / "actual"
    path.write_text(fixture.replace("/* ACTUAL_SDK_ORIGIN */", primitive))
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]
    if request.param:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command = [*shlex.split(os.environ.get("CC", "cc")), *flags, "-I", str(HERE), str(path),
               *(str(HERE / name) for name in LINKED), "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    receipt(evidence / "compile.json", command, built)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary, evidence


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_actual_sdk_origin_and_original_abi(sdk_origin_binary, scenario):
    binary, evidence = sdk_origin_binary
    command = [str(binary), scenario]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    receipt(evidence / f"{scenario}.json", command, result)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SDK_ORIGIN_HOSTTEST_PASS scenario={scenario}" in result.stdout
    assert "actual_decoder=1 actual_ap_observer=1 actual_cp_runtime=1 provider_bound=0 capture_verified=0" in result.stdout
    if scenario == "units":
        for unit, size in (("1d9", 409600), ("1da", 51200), ("1db", 53504)):
            for metadata in (0, 1):
                assert (f"ORIGIN_UNIT unit={unit} bytes={size} native_metadata={metadata} descriptor_reads=4 "
                        "provider_bound=0 source_memory_ready=0 capture_verified=0") in result.stdout
