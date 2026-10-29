"""Unlinked AP4063 stager; fixtures are host constructions, never AP captures."""
from pathlib import Path
import hashlib
import os
import re
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'
CASES = ('copy', 'unaligned', 'opaque', 'each-pid', 'each-type', 'order', 'outer',
         'size', 'source', 'alias', 'overflow', 'missing', 'disabled', 'one-shot',
         'fork', 'zero')


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    directory = tmp_path_factory.mktemp('cp-parameter-batch')
    obj, binary = directory / 'batch.o', directory / 'batch'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    for command in (
        flags + ['-c', str(HERE / 'cp-parameter-batch.c'), '-o', str(obj)],
        flags + [str(obj), str(HERE / 'test-cp-parameter-batch.c'), '-o', str(binary)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    return obj, binary


def run(binary, *args):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary), *map(str, args)], env=environment,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize('case', CASES)
def test_stager_boundaries(compiled, case):
    assert run(compiled[1], case) == ''


def test_production_exports_and_dependencies(compiled):
    obj, _ = compiled
    result = subprocess.run(['nm', '-g', '--defined-only', str(obj)],
                            capture_output=True, text=True, timeout=10, check=True)
    exports = {line.split()[-1] for line in result.stdout.splitlines()}
    assert {name for name in exports if not name.startswith('__odr_asan.')} == {
        'cp_parameter_batch_init', 'cp_parameter_batch_stage', 'cp_parameter_batch_slots'}
    result = subprocess.run(['nm', '-u', str(obj)], capture_output=True, text=True,
                            timeout=10, check=True)
    dependencies = {line.split()[-1] for line in result.stdout.splitlines()}
    assert {s for s in dependencies if not s.startswith(('__asan_', '__ubsan_'))} <= {
        'getpid', 'memcpy', 'memset'}


def test_schema_is_complete_and_contiguous(compiled):
    schema = [tuple(int(v, 16) for v in line.split())
              for line in run(compiled[1], 'schema').splitlines()]
    assert len(schema) == 190 and len({pid for pid, _, _ in schema}) == 190
    end = 8
    for _, offset, size in schema:
        assert offset == end and size >= 8
        end += size
    assert end == 0xa04
    assert schema[1] == (0x4006, 0x14, 0x34)
    assert schema[-1] == (0x4177, 0x9f8, 0xc)


def public_image(relative, expected):
    path = BASE / relative
    if not path.is_file():
        pytest.skip('prepare public ALLLANG assets separately; only image checks skip')
    blob = path.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == expected
    return blob


def pin(blob, raw, size, expected):
    window = blob[raw:raw + size]
    assert len(window) == size and hashlib.sha256(window).hexdigest() == expected


def test_public_cp_fixed_dispatch_and_generation_pins(compiled):
    cp = public_image('menu-root/cp/cpapp-b.bin',
        'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')
    pin(cp, 0x8da08c - 0x108000, 0x8f2,
        '9dec451364f09aa70d660613efd32f627aa811ad09036aa0544cff7c42c3c107')
    pin(cp, 0x35ce2c - 0x108000, 0x144,
        '61d05e099e3ccebc39fdc58a4f0099a4efc3413e50fb663694005ec349bfea31')
    pin(cp, 0x10fab8c - 0x108000, 0x15e * 20,
        'c9c11a7c68b25950ad8946fc35f2796a670f7eb2f0e9a5063747fa35bfe48e18')
    assert cp[0x35ce46 - 0x108000:0x35ce46 - 0x108000 + 6] == bytes.fromhex(
        'd4f85c0d411c')
    assert cp[0x35ce50 - 0x108000:0x35ce54 - 0x108000] == bytes.fromhex('c4f85c1d')
    assert struct.unpack_from('<II', cp, 0x10fb294 - 0x108000) == (0x4063, 0x35ce2d)
    capstone = pytest.importorskip('capstone')
    decoder = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    original = []
    offset = pid = None
    for ins in decoder.disasm(cp[0x8da08c - 0x108000:0x8da97e - 0x108000], 0x8da08c):
        if ins.mnemonic in ('add.w', 'addw'):
            if match := re.fullmatch(r'r1, r4, #(0x[0-9a-f]+|\d+)', ins.op_str):
                offset = int(match[1], 0)
        if ins.mnemonic in ('movw', 'mov.w'):
            if match := re.fullmatch(r'r0, #(0x[0-9a-f]+|\d+)', ins.op_str):
                pid = int(match[1], 0)
        if ins.mnemonic == 'bl' and ins.op_str == '#0x35ced4':
            original.append((pid, offset))
    schema = [tuple(int(v, 16) for v in line.split())
              for line in run(compiled[1], 'schema').splitlines()]
    assert original == [(pid, offset) for pid, offset, _ in schema]
    table = [struct.unpack_from('<5I', cp, 0x10fab8c - 0x108000 + i * 20)
             for i in range(0x15e)]
    for pid, _, _ in schema:
        rows = [row for row in table if row[0] == pid]
        assert len(rows) == 1 and rows[0][1] & 1


def test_public_ap_header_fixture_and_envelope_pins(compiled, tmp_path):
    ap = public_image('menu-root/usr/lib/appFw.so',
        '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b')
    pin(ap, 0x3535ee4, 0x1a38,
        'da603e8dfdfa93c0608184353ac204378c76f4372fd3ae6b3bf956f503810fd6')
    pin(ap, 0x353784c, 0x2c,
        '08012c218b5c6e91de447e928533891aec32856c5983c60c7710408bf8fe8ebf')
    assert ap[0x3535a38:0x3535a44] == bytes.fromhex('43008052e00319aa4300b072')
    capstone = pytest.importorskip('capstone')
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    registers, writes = {}, {}
    # Only source-pinned immediate header stores, before any parameter helper.
    for ins in decoder.disasm(ap[0x3535ee4:0x3536854], 0x3535ee4):
        if ins.mnemonic == 'mov':
            if match := re.fullmatch(r'w(\d+), #(0x[0-9a-f]+|\d+)', ins.op_str):
                registers[match[1]] = int(match[2], 0)
        if ins.mnemonic in ('strb', 'strh'):
            if match := re.fullmatch(r'w(\d+), \[x29, #(0x[0-9a-f]+)\]', ins.op_str):
                assert match[1] in registers
                offset = int(match[2], 0) - 0xa8
                size = 1 if ins.mnemonic == 'strb' else 2
                value = registers[match[1]].to_bytes(size, 'little')
                writes.update({offset + i: v for i, v in enumerate(value)})
    schema = [tuple(int(v, 16) for v in line.split())
              for line in run(compiled[1], 'schema').splitlines()]
    # Explicit host fixture: original AP headers, opaque/payload host patterns.
    packet = bytearray((37 * i + 19) & 255 for i in range(0xa04))
    for pid, offset in [(0x4063, 0), *[(pid, off) for pid, off, _ in schema]]:
        assert writes[offset] == 5
        assert writes[offset + 2] | writes[offset + 3] << 8 == pid
        for index in (offset, offset + 2, offset + 3):
            packet[index] = writes[index]
    fixture = tmp_path / 'host-fixture-public-ap-headers.bin'
    fixture.write_bytes(packet)
    assert run(compiled[1], 'source-header-fixture', fixture) == ''
