"""Bounded initial SSOS/OSD resources; no pixel, display-ready or capture claim."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
CASES = (
    'BUILDERS', 'BUILDER_REJECTIONS', 'COMPLETION_BUILDER', 'PARSER',
    'PARSER_BOUNDS', 'PARSER_KNOWN_MASK', 'NOTICES_BOTH_DIRECTIONS',
    'NOTICE_REJECTIONS', 'INITIALIZATION', 'INIT_BAD_DATA',
    'INITIAL100_102_NOT_READY', 'ALL16_PERSISTENT', 'MUTABLE100_COUNT0',
    'SOURCE100_ROW_GATES', 'EXPLICIT_COUNT0_NOTICE_STATUS13',
    'MUTABLE100_SAME_COUNT', 'DUPLICATE101', 'DUPLICATE102', 'ACTIVE100',
    'ACTIVE101', 'ACTIVE102', 'UNKNOWN100_INPUT', 'UNKNOWN101_INPUT',
    'UNKNOWN102_INPUT', 'BAD_COMPLETION_OWNER', 'DUPLICATE_COMPLETION_OWNER',
    'OPAQUE102_HOLES', 'CORRUPT_BUFFER_RETAINS', 'WRONG_MAPPING',
    'PACKET_NO_MUTATION', 'ENDPOINT_OPEN_NO_DUPLICATION', 'FOREIGN_PROCESS',
)
# Public CP raw file offsets, CPVA = raw + 0x108000. No private dump inputs.
PINS = (
    (0x5d606c, 0x5d6098, 'bd55761d8bb1aefe8f3d3c1eaa0df548bcdba5f032d8048061f6903a6df1fadf'),
    (0x5d6124, 0x5d6150, 'cb95bb10129ec03a6599ce36a2262dfba917185e7b26b48f7727bb1a28391443'),
    (0x9d578, 0x9d5ac, '93dbf5cdbe1eb421277234ac9c0f6cdcc9a7f5c6b9ddecc1fe1061102e7aa2e3'),
    (0x58289e, 0x5828e2, '327f7f5fc454ecf1804b2c885481038f8a3287ac8a7b114fa700e9e98ce7ca9d'),
    (0x46a0a8, 0x46a0e4, '8008921cb1ec40aa338bfc21c778ee0cc1fee2514ecea2f9b52517a250ffcb2a'),
    (0x469c1e, 0x469c30, 'ddbbe5a40359fd5517bc96375ebb9823259ffc065ca66d8240bfbff50447631a'),
    (0x5d65ce, 0x5d6608, '13bb2dd3c25f63142a49c4244ecb9aa5c0d6fc22a70071428b3a6a3d6a403a44'),
    (0x46b168, 0x46b198, '4eefddbf9b55ec1bb14a5547b47ad51a48c86322c0691dd25c821c10b8e0755d'),
    (0x46b33c, 0x46b34e, 'a704f62150da50803eb4ab543e1ac66f3a563290d395fb7a44d9cbf462f221e2'),
    (0x46b4c8, 0x46b4da, 'c94b527c5100b5c48f56bf2e64e914c0f10e5e2a29afd0f78951fe51f2ae023b'),
    (0x46b67a, 0x46b69a, '6b0b24fd5b9e3ea8d6648b2127e9ca1488dfcb52838ce9fb96027fed3e94f9e0'),
    (0xae9ec8, 0xae9efe, 'd69d9f34cff2744a34eb8d8b0757db796babfd963773dfb290b8af2a6a10a28a'),
    (0x583f5a, 0x583f96, '516bc786b2862ab7a8ca8410475ca4f25005de29e3375ced325edf3d0404bc00'),
    (0x5d5f30, 0x5d5fd8, '787aad68df9b7851cbfb26a3e99f847dbf38cb4bfb25667d90e21c10182e9927'),
    (0x5d61a2, 0x5d6296, '0500d14153b7fdf241a2a532aaebdf2d8d34b90da620c22eea7c81136db2bd6c'),
    (0x5d46f4, 0x5d474e, 'c4820874e96c0d5eef39915d32a159b38ba045ff7b592ba343609fa8915d97ce'),
)


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp('osd-pin-format')
    binary = root / 'model'
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-O1',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
        str(MODEL / 'osd-pin-format.c'), str(MODEL / 'osd-buffer-owner.c'),
        str(MODEL / 'test-osd-pin-format.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.fixture(scope='module')
def executed(compiled):
    results = {}
    for case in CASES:
        result = subprocess.run([str(compiled), case], capture_output=True, text=True,
            timeout=10, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                                UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
        assert result.returncode == 0, case + '\n' + result.stdout + result.stderr
        assert not result.stderr, result.stderr
        results[case] = result.stdout
    return results


@pytest.mark.parametrize('case', CASES)
def test_osd_format_sanitized_contract(executed, case):
    assert f'OSD_PIN_FORMAT_{case}_PASS' in executed[case].splitlines()


def fields(output):
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def expected_format(tag, payload):
    return struct.pack('<16I', 0x534f5353, 1 if tag == 0 else 0x01000000,
                       3 if tag == 0 else 0, 1, 32, 0, 0, 0,
                       0x59525445, tag, 0, 64, len(payload), 0, 0, 0) + payload


def test_exact_peer_source_headers_and_masked_payloads(executed):
    built = fields(executed['BUILDERS'])
    assert bytes.fromhex(built['KEY0']) == expected_format(0, bytes(64))
    assert bytes.fromhex(built['KEY0_KNOWN']) == bytes([1]) * 128
    source100 = bytearray([0xa5]) * 128
    source100[:4] = struct.pack('<I', 1)
    source100[8:10] = bytes(2)
    source100[12] = 0
    mask100 = bytearray(128)
    mask100[:4] = bytes([1]) * 4
    mask100[8:10] = bytes([1]) * 2
    mask100[12] = 1
    assert bytes.fromhex(built['TAG100']) == expected_format(0x100, source100)
    assert bytes.fromhex(built['TAG100_KNOWN']) == bytes([1]) * 64 + mask100
    source102 = bytearray([0xa5]) * 32
    source102[:4] = bytes([0xff]) * 4
    source102[4:6] = bytes(2)
    source102[8:28] = bytes([0xff]) * 20
    mask102 = bytearray(32)
    mask102[:6] = bytes([1]) * 6
    mask102[8:28] = bytes([1]) * 20
    assert bytes.fromhex(built['TAG102']) == expected_format(0x102, source102)
    assert bytes.fromhex(built['TAG102_KNOWN']) == bytes([1]) * 64 + mask102
    assert built['KEY0'][8:16] == '01000000'  # Numeric one, LE bytes.
    assert built['TAG100'][8:16] == '00000001'  # Numeric 01000000, LE bytes.


def test_completion_uses_full_peer_handle_and_preserves_two_unknown_bytes(executed):
    built = fields(executed['COMPLETION_BUILDER'])
    payload = struct.pack('<IIH', 0, 0xe1000012, 0) + b'\xa5\xa5' + bytes(4)
    assert bytes.fromhex(built['TAG101']) == expected_format(0x101, payload)
    assert bytes.fromhex(built['TAG101_KNOWN']) == bytes([1]) * 74 + bytes(2) + bytes([1]) * 4


def test_independent_80_byte_notice_layout_in_both_directions(executed):
    built = fields(executed['NOTICES_BOTH_DIRECTIONS'])
    for label, src, dst, handle in (
        ('NOTICE_PINMEM', 0x90590818, 0x9080003b, 0xe1000014),
        ('NOTICE_PEER', 0x9080003b, 0x90590818, 0xe1000010),
    ):
        outer = struct.pack('<IIHHIII', 0, 0xa0a0a0a0, 1, 80, 24, 80, 0x1e1e1e1e)
        frame = struct.pack('<4H', 0x1000, 0x102, 0x38, 1)
        peer = struct.pack('<4I', 1, 3, 0, dst)
        producer = struct.pack('<4I', 1, 3, 0, src)
        tail = struct.pack('<4I', 0xe1700, handle, 0, 0)
        assert bytes.fromhex(built[label]) == outer + frame + peer + producer + tail


def test_all16_resources_stay_owned_and_open_until_external_teardown(executed):
    result = fields(executed['ALL16_PERSISTENT'])
    assert result == {'PERSISTENT_RESOURCES': '16', 'PERSISTENT_OWNERS': '32', 'PERSISTENT_OPENS': '32'}


def test_production_translation_unit_compiles_without_test_macros(tmp_path):
    result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-c', str(MODEL / 'osd-pin-format.c'), '-o', str(tmp_path / 'production.o')],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope='module')
def public_cp():
    path = HERE / 'menu-root/cp/cpapp-b.bin'
    if not path.is_file():
        pytest.skip('optional public ALLLANG CP not provisioned')
    raw = path.read_bytes()
    assert len(raw) == 18090880
    assert hashlib.sha256(raw).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    return raw


@pytest.mark.parametrize(('start', 'end', 'digest'), PINS)
def test_original_public_cp_instruction_windows(public_cp, start, end, digest):
    assert hashlib.sha256(public_cp[start:end]).hexdigest() == digest


def test_original_numeric_version_and_initial_branch_opcodes(public_cp):
    assert public_cp[0x5d6078:0x5d607c].hex() == '4ff08071'  # mov.w r1,#01000000
    assert public_cp[0x5d6130:0x5d6134].hex() == '4ff08071'
    assert public_cp[0x5d65d4:0x5d65d8].hex() == '4ff08072'  # r2 for strd
    assert public_cp[0x9d592:0x9d596].hex() == '01210322'  # peer version1 / flags3
    assert public_cp[0x46b17a:0x46b180].hex() == 'bdf8100048b1'  # new101 mask load / cbz
    assert public_cp[0x46b194:0x46b198].hex() == '002563e0'  # no plane callback
    assert public_cp[0x46b4d2:0x46b4d6].hex() == '0d2533e0'  # existing100 count0 =>13
