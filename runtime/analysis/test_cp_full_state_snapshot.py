"""Host-only CP76 layout/assembly checks; no providers, transport or VM."""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'
ROOT = BASE.parent.parent
REPORT = ROOT / 'report' / 'cp-full-state-snapshot'
PINS = json.loads((REPORT / 'source-pins.json').read_text())


@pytest.mark.parametrize('build', ('sanitized', 'optimized'))
def test_full_layout_and_fragment_guards(tmp_path, build):
    obj, binary = tmp_path / 'full.o', tmp_path / 'full'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic']
    if build == 'sanitized':
        flags += ['-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    else:
        flags += ['-O2']
    for command in (
        flags + ['-c', str(HERE / 'cp-full-state-snapshot.c'), '-o', str(obj)],
        flags + [str(obj), str(HERE / 'cp-state-snapshot.c'),
                 str(HERE / 'test-cp-full-state-snapshot.c'), '-o', str(binary)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary)], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        'full_layout_assembled_only=1 blocks=76 providers_complete=0 publication=0 '
        'native_business=0 frame=0 capture=0')
    symbols = subprocess.run(['nm', '-g', '--defined-only', str(obj)],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stderr
    assert {line.split()[-1] for line in symbols.stdout.splitlines()
            if line.split()[-1] != '__odr_asan.cp_full_state_snapshot_blocks'} == {
        'cp_full_state_snapshot_blocks', 'cp_full_state_snapshot_copy',
        'cp_full_state_snapshot_assemble',
    }


def _successful_constants(body):
    values = {int(v, 0) for v in re.findall(r'\breturn\s+(0x[0-9a-f]+|[0-9]+)\s*;', body)}
    for value in re.findall(r'\breturn CONCAT44\([^,\n]+,([a-z0-9_]+)\);', body):
        if value.startswith('0x') or value.isdigit():
            values.add(int(value, 0))
        else:
            values.update(int(v, 0) for v in re.findall(
                r'\b' + value + r'\s*=\s*(0x[0-9a-f]+|[0-9]+)\s*;', body))
    return values - {0}


def test_schema_matches_independent_table_layout_and_all_getter_returns():
    layout = json.loads((ROOT / PINS['restored_sources'][0]['path']).read_text())
    source = (HERE / 'cp-full-state-snapshot.c').read_text()
    actual = [tuple(int(x, 16) for x in row) for row in re.findall(
        r'\{(0x[0-9a-f]+), (0x[0-9a-f]+), (0x[0-9a-f]+)\}', source)]
    rows = PINS['getter_rows']
    assert len(actual) == len(rows) == len(layout['blocks']) == 76
    assert actual == [(r[0], r[2], r[3]) for r in rows]
    assert actual == [(r['command'], r['offset'], r['bytes']) for r in layout['blocks']]
    assert [(r[0], r[1]) for r in rows] == [
        (r['command'], r['getter_CP_VA']) for r in layout['blocks']]
    assert PINS['CP_sha256'] == layout['CP_sha256']
    assert PINS['full_table_CP_VA'] == layout['full_table_CP_VA'] == 0xd93660
    assert PINS['full_table_sha256'] == layout['full_table_sha256']
    assert PINS['incremental_table_CP_VA'] == 0x10fa3e4 and PINS['incremental_table_count'] == 150
    assert len({r[0] for r in rows}) == 76
    assert sum(r[3] for r in rows) + 8 == layout['snapshot_bytes'] == 0x6d4
    assert actual[19] == (0x201b, 0x1c4, 20) and actual[32] == (0x2044, 0x2a8, 0xa0)
    offset = 8
    for command, getter, at, size, load, instruction in rows:
        assert at == offset and size >= 8 and load >= getter
        offset += size
        expected_register = {0x2004: 4, 0x2044: 5, 0x20af: 2}.get(command, 0)
        assert bytes.fromhex(instruction) == bytes((size, 0x20 + expected_register))
    assert PINS['unknown_permitted_offsets'] == [1, 0x1c5, 0x2a9]
    assert PINS['outer_virtual_reserved'] == {'offset': 1, 'value': 0, 'known': 0}
    assert PINS['layout_assembly_complete'] is True
    for claim in ('semantic_domains_complete', 'runtime_provider_complete',
                  'source_dependencies_closed', 'publication_claimed',
                  'generation_advance_claimed', 'success_ack_claimed',
                  'native_business_verified', 'frame_verified', 'capture_verified'):
        assert PINS[claim] is False

    # Restored research artifacts are optional outside the source workspace.
    for pin in PINS['restored_sources']:
        path = ROOT / pin['path']
        if path.is_file():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == pin['sha256']
    table = ROOT / PINS['restored_sources'][1]['path']
    if table.is_file():
        original = json.loads(table.read_text())
        assert [(r['command'], r['function'], r['extra']) for r in original['rows']] == [
            (r[0], r[1], 0) for r in rows]
    restored = ROOT / PINS['restored_sources'][2]['path']
    if restored.is_file():
        bodies = {int(va, 16): body for va, body in re.findall(
            r'// Function: sub_[0-9a-f]+ @ 0x([0-9a-f]+)\n(.*?)(?=\n// Function:|\Z)',
            restored.read_text(), re.S)}
        assert len(bodies) == 76
        manual = {0x2004: (0x8d53f2, 0x84), 0x20a0: (0x8d99c8, 0x9c)}
        parsed = 0
        for command, getter, _, size, load, _ in rows:
            values = _successful_constants(bodies[getter])
            if command in manual:
                assert not values and (load, size) == manual[command]
            else:
                assert values == {size}, (hex(command), values, size)
                parsed += 1
        assert parsed == 74


def test_public_cp_identity_fixed_thumb_pointers_and_all_76_return_loads():
    source = BASE / 'menu-root' / 'cp' / 'cpapp-b.bin'
    if not source.is_file():
        pytest.skip('prepare public ALLLANG assets separately; raw public-source check only is skipped')
    blob = source.read_bytes()
    assert len(blob) == PINS['CP_bytes'] == 18090880
    assert hashlib.sha256(blob).hexdigest() == PINS['CP_sha256']

    def raw(va, size):
        offset = va - PINS['CP_VA_equals_raw_plus']
        assert 0 <= offset <= len(blob) - size
        return blob[offset:offset + size]

    table = raw(PINS['full_table_CP_VA'], 76*12)
    assert hashlib.sha256(table).hexdigest() == PINS['full_table_sha256']
    for index, (command, getter, _, size, load, instruction) in enumerate(PINS['getter_rows']):
        assert struct.unpack_from('<III', table, index*12) == (command, getter | 1, 0)
        assert raw(load, 2).hex() == instruction
        assert raw(load, 1)[0] == size
    for pin in PINS['pins']:
        data = raw(pin['CP_VA'], pin['bytes'])
        if 'sha256' in pin:
            assert hashlib.sha256(data).hexdigest() == pin['sha256']
        if 'expected_hex' in pin:
            assert data.hex() == pin['expected_hex']
