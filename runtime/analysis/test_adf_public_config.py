"""Frozen original public CP configuration is read, never guessed from inputless caps."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


def test_adf_aip_layout_matches_pinned_static_proof():
    layout = (MODEL / 'adf-aip-backup-map.inc').read_bytes()
    assert hashlib.sha256(layout).hexdigest() == (
        'a16e23951cf9ef05cf2aac14722c9d55b680b994fcf09ab6d8690390d797d742')
    proof = HERE / 'menu-runs/tcin-tests-20261025/adf-input-backup-view-static.json'
    if proof.is_file():
        data = proof.read_bytes()
        assert hashlib.sha256(data).hexdigest() == (
            '6b05cfecc0a03363cc319e64cad8cb49090f8f493c2e14946bdc9c51e74ef50f')
        expected = [(item['source'], item['destination']) for item in json.loads(data)['source_map']]
        actual = [(int(source, 16), int(destination)) for source, destination in
                  re.findall(r'\{0x([0-9a-f]+)UL, ([0-9]+)U\}', layout.decode('ascii'))]
        assert actual == expected and len(actual) == 362


def test_adf_public_seed_runtime_config_readback_and_rejection(tmp_path):
    seed = HERE / 'menu-root/seed-backup.bin'
    if not seed.exists():
        pytest.skip('provision the original pinned ALLLANG seed first')
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == (
        '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47')
    binary = tmp_path / 'adf-public-config'
    built = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-public-config.c'), str(MODEL / 'test-adf-public-config.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary), str(seed), str(tmp_path / 'bad-seed.bin')],
        capture_output=True, text=True, timeout=15,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_PUBLIC_CONFIG_ORIGINAL_KEYS_ACTUAL_READBACK_PASS' in result.stdout
    assert 'ADF_PUBLIC_CONFIG_WRONG_CONTENT_LENGTH_OWNER_RELOAD_REJECTED_PASS' in result.stdout
    assert 'ADF_PUBLIC_CONFIG_AIP_MASKED_READ_TAMPER_BOUNDARIES_PASS' in result.stdout
    views = dict(line.split('=', 1) for line in result.stdout.splitlines() if line.startswith('ADF_AIP_'))
    values = bytes.fromhex(views['ADF_AIP_VALUES'])
    known = bytes.fromhex(views['ADF_AIP_KNOWN'])
    assert len(values) == len(known) == 393 and known.count(0xff) == 362 and known.count(0) == 31
    assert all(value == 0xa5 for value, mask in zip(values, known) if not mask)
    assert hashlib.sha256(bytes(value & mask for value, mask in zip(values, known))).hexdigest() == (
        '5fe2407b1cb4ac146f9a41bed474105a67c6ffd81b0ce26e9b03f620f1ef2059')
    assert hashlib.sha256(known).hexdigest() == (
        '576779efa55a01577e36524b9a4688ea1726e380c7228da88b9feb54c6886ba3')
