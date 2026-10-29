"""Owned iris bank dataflow only: host fixtures never prove iris/capture completion."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / "device-models"
CASES = ("constructor", "lifecycle", "profiles", "source", "unknown", "invalid",
         "aliases", "overflow", "concurrent", "fork", "create-failures")


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def compiled(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("cp-iris-status-" + request.param)
    obj, binary = directory / "iris.o", directory / "iris"
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-g", "-pthread"]
    if request.param == "asan-ubsan":
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
    commands = (
        flags + ["-c", str(HERE / "cp-iris-status.c"), "-o", str(obj)],
        # The C harness includes the same production source for private limit
        # fixtures; no test mutation/export hooks are added to the actual API.
        flags + [str(HERE / "test-cp-iris-status.c"), "-Wl,--wrap=calloc",
                 "-Wl,--wrap=pthread_mutex_init", "-o", str(binary)],
    )
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    return obj, binary


@pytest.mark.parametrize("case", CASES)
def test_actual_c_bank_model(compiled, case):
    _, binary = compiled
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(binary), case], cwd=binary.parent, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "host_test=1 original_producer=0 source_runtime=0 original_atomicity=0 capture=0")


def test_production_exports_only_owned_bank_api(compiled):
    obj, _ = compiled
    result = subprocess.run(["nm", "-g", "--defined-only", str(obj)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert {line.split()[-1] for line in result.stdout.splitlines()} == {
        "cp_iris_status_create", "cp_iris_next_bank", "cp_iris_copy_current_to_next",
        "cp_iris_publish_next", "cp_iris_publish_initial_source",
        "cp_iris_sample_init_complete", "cp_iris_status_snapshot", "cp_iris_status_destroy"}


def test_public_cp_source_pins():
    cp = BASE / "menu-root/cp/cpapp-b.bin"
    if not cp.is_file():
        pytest.skip("prepare public ALLLANG CP separately; no private fallback")
    blob = cp.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == (
        "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428")
    pins = (
        (0xa76188, 44, "461d2cdc37c619ad0f55da675717105405697bd0f26ee40383f1801310ceee08"),
        (0xa75d8e, 356, "67feaf1799d9222ba86774fd55c961a9dbc271121fc033f719bf45d61a18f664"),
        (0xa76494, 302, "cf94d0703e14e8641aeeca887f05b104dfe9881c6c3a0a405b39de651b4c74ae"),
        (0xa780e6, 36, "4618508fd3d904916dfc26a69c3a49b5d224def9a8eae522a8fff4f28a72fd60"),
    )
    for cpva, size, digest in pins:
        raw = cpva - 0x108000
        window = blob[raw:raw + size]
        assert len(window) == size
        assert hashlib.sha256(window).hexdigest() == digest, hex(cpva)
    descriptor = 0xdf2938 - 0x108000
    assert struct.unpack_from("<IIII", blob, descriptor) == (0xf78208, 1, 0, 0x1717512)
    name = 0xf78208 - 0x108000
    assert blob[name:name + 16].split(b"\0", 1)[0] == b"uc_IrisInitComp"
    profile = 0xdf27f8 - 0x108000
    assert struct.unpack_from("<IIII", blob, profile) == (2, 0, 0, 2)
