"""Bounded AIP 03/02 public-data consumption, owned MMIO and fail-closed sequence."""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import subprocess
import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
PROOFS = HERE / 'menu-runs/tcin-tests-20261025'
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
SEED_SHA = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
SOURCE = MODEL / 'adf-aip-input-config.c'


def _numbers(name):
    body = re.search(r'static const unsigned int ' + re.escape(name) +
                     r'\[[^=]+?=\s*\{(.*?)\};', SOURCE.read_text(), re.S)
    assert body is not None, name
    return [int(n, 0) for n in re.findall(r'0x[0-9a-fA-F]+|\b[0-9]+\b', body[1])]


@pytest.mark.parametrize('name,va,size,fmt,projection', [
    ('merge_rows', 0xe900c4, 216, 'I', 'all'),
    ('gate_masks', 0xe8ff2c, 256, 'I', 'row8'),
    ('filter9_register_offsets', 0xe9002c, 36, 'I', 'register'),
    ('filter11_register_offsets', 0xe90050, 44, 'I', 'register'),
    ('filter9_offsets', 0xf28fd4, 8, 'H', 'all'),
    ('filter9_shifts', 0xfd35c5, 18, 'B', 'every2'),
    ('filter11_shifts', 0xfd35d7, 22, 'B', 'every2'),
    ('selector_offsets', 0x51c488, 12, 'H', 'all'),
    ('route_table3', 0xf2906e, 48, 'H', 'all'),
    ('side_tone', 0xe900ac, 24, 'I', 'all'),
    ('input02', 0x1116fd0, 36, 'I', 'all'),
])
def test_embedded_aip_tables_match_original_cp(name, va, size, fmt, projection):
    cp = HERE / 'menu-root/cp/cpapp-b.bin'
    if not cp.is_file():
        pytest.skip('provision the pinned public F5 CP asset first')
    data = cp.read_bytes()
    assert hashlib.sha256(data).hexdigest() == CP_SHA
    raw = data[va - 0x108000:va - 0x108000 + size]
    values = list(struct.unpack('<' + fmt * (size // struct.calcsize(fmt)), raw))
    if projection == 'row8':
        values = values[::8]
        assert sum(values) == 0xfffff
    elif projection == 'register':
        values = [value - 0xf48a2000 for value in values]
    elif projection == 'every2':
        values = values[::2]
    assert _numbers(name) == values


def test_original_route_classifier_and_critical_branch_bytes():
    cp = HERE / 'menu-root/cp/cpapp-b.bin'
    if not cp.is_file():
        pytest.skip('provision the pinned public F5 CP asset first')
    data = cp.read_bytes()
    assert hashlib.sha256(data).hexdigest() == CP_SHA
    # The model's unsigned route ranges, 2360/2060 reads, and first-byte route stores.
    pins = {
        0xb63a6c: '0168142901d103207047',
        0xb63a76: 'a1f10e00062801d202207047',
        0xb63a82: '21f003020120042a20d0a1f11502062a1cd3',
        0xb63a94: '42f260020839cff28a420629d2f800031268',
        0xb63aa8: 'a0f1080105290fd9',
        0xb63ab0: '142806d801210f228140c0f210021142d7d1',
        0xb63ad0: '082aced00220042a38bf00207047',
        0x51bf0a: 'aef10300042818d3',
        0x51bf28: '029a00231044c65c09f803600133042bf9d1',
        0x51bfa2: '1af800100beb8002013004281166',
        0x51c146: '7678b04025fa03f624ea4606013e7043',
        0x51c21e: 'b1f9fc20b1f97c11',
    }
    for address, expected_hex in pins.items():
        expected = bytes.fromhex(expected_hex)
        assert data[address - 0x108000:address - 0x108000 + len(expected)] == expected


def test_public_fixture_both_applies_full_bank_and_failure_paths(tmp_path):
    seed = HERE / 'menu-root/seed-backup.bin'
    if not seed.is_file():
        pytest.skip('provision the original pinned ALLLANG seed first')
    assert hashlib.sha256(seed.read_bytes()).hexdigest() == SEED_SHA
    binary = tmp_path / 'adf-aip-input-config'
    built = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-public-config.c'), str(SOURCE),
        str(MODEL / 'test-adf-aip-input-config.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary), str(seed)], capture_output=True, text=True,
        timeout=30, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                            UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        'ADF_AIP_INPUT_CONFIG_ORIGINAL_SEED_BOTH_APPLIES_GOLDEN_ALL_REGISTERS_PASS',
        'ADF_AIP_INPUT_CONFIG_SEQUENCE_PACKET_FAULT_PRESERVATION_PASS',
        'ADF_AIP_INPUT_CONFIG_PUBLIC_OWNER_REGISTER_TAMPER_REJECTED_PASS',
        'ADF_AIP_INPUT_CONFIG_PARTIAL_WRITE_FAILURE_LATCHED_NOT_COMPLETED_PASS',
    ):
        assert marker in result.stdout
    values = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    # Original masked public-data read sequence, independently derived from the ROM contract.
    assert values['AIP_INPUT_PUBLIC_HASH'] == '9fea4813aa05a5bd'
    assert values['AIP_INPUT_REGISTER_HASH'] == 'eaf5228455264ff1'
    assert values['AIP_INPUT_WRITE_HASH'] == '5426b1385bec3f14'


def test_pinned_public_view_selector_and_template_proof():
    proof = PROOFS / 'adf-input-backup-view-static.json'
    if not proof.is_file():
        pytest.skip('static private-workdir receipt is optional for readers')
    data = json.loads(proof.read_bytes())
    assert data['cp_sha256'] == CP_SHA and data['seed_sha256'] == SEED_SHA
    assert data['selector_key'] == '00690227' and data['selector_key_value'] == 0
    assert data['capability_word8'] == 1 and data['derived_init_selector'] == 2
    assert data['opcode02_payload_u32'] == _numbers('input02')
    assert bytes.fromhex(data['opcode02_hex']) == struct.pack('<11I', 2, 44, *_numbers('input02'))
    view, known = bytes.fromhex(data['masked_view_hex']), bytes.fromhex(data['known_mask_hex'])
    assert len(view) == len(known) == 393 and known.count(255) == 362
    selected = list(range(0x44, 0x51)) + list(range(0x54, 0x78))
    assert all(known[i] == 255 and view[i] == 0 for i in selected)
    assert known[0x52] == known[0x53] == 0
    assert known[0x40] == 255 and view[0x40] == 1
