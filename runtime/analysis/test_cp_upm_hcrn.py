"""CP-local HCRN host tests; no original AP/CP/native302c runtime proof."""
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / "device-models"
CASES = ("normal", "invalid", "aliases", "concurrent", "fork", "create-failures")


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def compiled(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp("cp-upm-hcrn-" + request.param)
    obj, binary = directory / "hcrn.o", directory / "hcrn"
    flags = ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
             "-g", "-pthread"]
    if request.param == "asan-ubsan":
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
    commands = (
        flags + ["-c", str(HERE / "cp-upm-hcrn.c"), "-o", str(obj)],
        flags + [str(obj), str(HERE / "test-cp-upm-hcrn.c"),
                 "-Wl,--wrap=calloc", "-Wl,--wrap=pthread_mutex_init", "-o", str(binary)],
    )
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    return obj, binary


@pytest.mark.parametrize("case", CASES)
def test_actual_c_actor(compiled, case):
    _, binary = compiled
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(binary), case], cwd=binary.parent, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "host_test=1 original_registration=0 publication_runtime=0 AP_current=0 "
        "source_atomic=0 history_complete=0 native302c=0")


def test_production_exports_only_frozen_api(compiled):
    obj, _ = compiled
    result = subprocess.run(["nm", "-g", "--defined-only", str(obj)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert {line.split()[-1] for line in result.stdout.splitlines()} == {
        "cp_upm_hcrn_create", "cp_upm_hcrn_consume_publication",
        "cp_upm_hcrn_query_in_place", "cp_upm_hcrn_snapshot", "cp_upm_hcrn_destroy"}


def test_public_cp_source_pins():
    cp = BASE / "menu-root/cp/cpapp-b.bin"
    if not cp.is_file():
        pytest.skip("prepare public ALLLANG CP separately; no private fallback")
    blob = cp.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == (
        "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428")
    pins = (
        (0xc0dc50, 202, "167a7043fd1a624ffa6e004b60b8cbf6229357fd023b80727274f79b4c1d9249"),
        (0xc0dd1a, 40, "586f4f8263f90f0a394d8762aab7f6474f870d5b7af624b8ad440eecbeea8d59"),
        (0x596b60, 154, "e10a0052706e056d2078e4d2806a2d424d9b271d4fdd84b178627653b48c938e"),
        (0x596e30, 54, "128a17d233c713f24cf74db4e34383ff79e5132e30f5c6c0dd039f9ac2d9fbd5"),
    )
    for cpva, size, digest in pins:
        raw = cpva - 0x108000
        window = blob[raw:raw + size]
        assert len(window) == size
        assert hashlib.sha256(window).hexdigest() == digest, hex(cpva)
