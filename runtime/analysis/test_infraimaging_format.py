"""Finite BB IN1 -> InfraImaging OUT1 SSYN format; no connection/frame claim."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
CASES = (
    'FRESH_EXPLICIT_FIVE_WORD_INIT_ONCE',
    'BUILD_CANONICAL_SSYN06_ETRY_TYPE1_80B',
    'ORIGINAL_PAYLOAD_OUT1_CACHE_READBACK_FNV',
    'FULL_BYTES_U16_FLAGS_AND_U32_DIMENSIONS',
    'UNCONSUMED_WORD_ONLY_CHANGES_PAYLOAD_DIGEST',
    'BAD_SIGNATURE_KEY_TYPE_DUPLICATES_BOUNDS_RETAIN',
    'TRUNCATED_OVERSIZE_NULL_RETAIN',
    'UNKNOWN_OWNER_AND_COUNTER_OVERFLOW_RETAIN',
    'UNALIGNED_INPUT_16B_COPY_NO_ALIAS',
    'DISTINCT_OWNERS_NO_SHARED_CACHE',
    'SSYN01_TYPE0_UPDATES_SAME_CACHE_CONSUMED_TWO',
    'SSYN01_UNCONSUMED_WORD_AND_FULL_U16_FLAGS',
    'SSYN_VARIANTS_REJECT_ASYMMETRIC_TYPES_AND_BOUNDS',
)
# Addresses below are raw file offsets; CPVA = raw + 0x108000.
PINS = (
    # BB posthook: literal SSYN06; calls writer(key=0, type=1, payload, 16).
    (0xced98, 0xcedc0, 'e5d7b7a39905aca46b0a7587af7c63a052f5535b8d9ad996e0f6d1c003cf6ce5'),
    # First ETRY: +20 tag/key, +28 type; +2c data40/+30 len16/+34 next0.
    (0x59aaa2, 0x59aadc, 'b0fffa0f816fb9f60e8a755ecdd5bfd0bd35e73aeb2759b3245397d00128e7a2'),
    # Source five-word cache store, including unmasked u16 flags.
    (0x36752c, 0x36754e, 'f312fbfee26a5ed35bdd6b77c4ce52d3eaf20c554671f4099b3134acf73f2409'),
    # 16B reader constructor and the five field getters.
    (0x581be8, 0x581c18, '3e72e994740e9ffd17f33849ffae7b586449e54b0a097dbefa97b70d9a46f79d'),
    (0x581c5a, 0x581c78, '2c574d054b54c739dfd49bd0a1c0e02bf6aca89554978fd134ff8cdcb2b0a879'),
    # SSYN/key0 lookup, reader adapter, and actual payload copy.
    (0x582abc, 0x582b5c, '93bb6d7166bcb76fc31e015af6a8b861dda9d7b09248863dbed3e73193b31e4e'),
    (0x582702, 0x582758, '5454e8a0d5259e83556ee82b7e2c1a06a6884f91d29ca2cff6d46af5ac3dca02'),
    (0x5808d8, 0x5808e6, '109d5f0d987c6e65724fe140feafdb89ba0d5eee0114456947c7db42b49971b1'),
    (0x582dc0, 0x582dc4, '501d153f5ff22b71e1f143301d4cf5b9b94065854581580d356c59a2f66d97a8'),
    # Hidden reader constructor chain and SS signature recognizer preserve the writer header.
    (0x9d6d8, 0x9d6f0, 'fb76c025087860ce0b633bdf75ec034d71e7d45e738d6998999da0b69f895cd6'),
    (0x5826d6, 0x582702, '21cfabd5ed496089fe812ea2caca09098b69db80761897585f01739ebcd9e5d5'),
    (0x58289e, 0x5828d0, '6d94d46f776d02784ddfdfb785bb8393ef7a447043f1db733b27fb696577e16e'),
    (0x9d5c8, 0x9d5e8, 'e9f15eebfe1ade317306ad75d15c818189442d2dc7b005c153632aa88b1657b8'),
    # OUT1 bypasses the OUT0-only code guard before the five-word cache stores.
    (0x367518, 0x36752c, 'dbbf5eae802c0778c559ff6d756f33338ab6f42609ce1a7bc8d825dc9a54e2f6'),
    # BB IN1 payload and InfraImaging OUT1 explicit initial cache.
    (0xfe79ac, 0xfe79bc, 'b0daa4b02f62bf8c616d685132adffd2116e206178c36a10ecb752fe73569b4c'),
    (0xfe1070, 0xfe1084, '21fc3f955c14305ed66b2f6064de082e8447f29048da3ab7c5c01090c1b722ab'),
)


@pytest.fixture(scope='module')
def executed(tmp_path_factory):
    binary = tmp_path_factory.mktemp('infraimaging-format') / 'self-test'
    built = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-O1',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'infraimaging-format.c'), str(MODEL / 'test-infraimaging-format.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr, result.stderr
    return result.stdout


@pytest.mark.parametrize('case', CASES)
def test_infraimaging_format_contract(executed, case):
    assert f'INFRAIMAGING_FORMAT_{case}_PASS' in executed.splitlines()
    assert f'INFRAIMAGING_FORMAT_CASES={len(CASES)}' in executed.splitlines()


def test_generated_packet_cache_and_payload_digest_independently(executed):
    fields = dict(line.split('=', 1) for line in executed.splitlines() if '=' in line)
    packet = bytes.fromhex(fields['INFRAIMAGING_FORMAT_PACKET'])
    expected = struct.pack('<20I', 0x4e595353, 0x06000000, 0, 1, 0x20, 0, 0, 0,
                           0x59525445, 0, 1, 0x40, 16, 0, 0, 0, 1, 0, 1920, 1080)
    assert packet == expected and len(packet) == 80
    assert packet[0x40:].hex() == '01000000000000008007000038040000'
    assert fields['INFRAIMAGING_FORMAT_CACHE'] == '0,1,1920,1080,0'
    fnv = 0xcbf29ce484222325
    for byte in packet[0x40:]:
        fnv = ((fnv ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    assert fnv == 0x1a3c540ebc5023bd
    assert int(fields['INFRAIMAGING_FORMAT_PAYLOAD_FNV64'], 16) == fnv


def test_forwarded_packet_cache_and_payload_digest_independently(executed):
    fields = dict(line.split('=', 1) for line in executed.splitlines() if '=' in line)
    packet = bytes.fromhex(fields['INFRAIMAGING_FORMAT_FORWARDED_PACKET'])
    payload = bytes.fromhex('01010300000000008007000038040000')
    expected = struct.pack('<16I', 0x4e595353, 0x01000000, 0, 1, 0x20, 0, 0, 0,
                           0x59525445, 0, 0, 0x40, 16, 0, 0, 0) + payload
    assert packet == expected and len(packet) == 80
    assert fields['INFRAIMAGING_FORMAT_FORWARDED_CACHE'] == '1,1,1920,1080,3'
    fnv = 0xcbf29ce484222325
    for byte in payload:
        fnv = ((fnv ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    assert fnv == 0x37228cd728b41c0d
    assert int(fields['INFRAIMAGING_FORMAT_FORWARDED_PAYLOAD_FNV64'], 16) == fnv


@pytest.fixture(scope='module')
def public_cp():
    original = HERE / 'menu-root/cp/cpapp-b.bin'
    if not original.is_file():
        pytest.skip('optional pinned public ALLLANG CP artifact not provisioned')
    raw = original.read_bytes()
    assert len(raw) == 18090880
    assert hashlib.sha256(raw).hexdigest() == (
        'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')
    return raw


@pytest.mark.parametrize(('start', 'end', 'digest'), PINS)
def test_original_public_cp_source_pins(public_cp, start, end, digest):
    assert hashlib.sha256(public_cp[start:end]).hexdigest() == digest


def test_original_payload_and_explicit_out1_constructor(public_cp):
    assert public_cp[0xfe79ac:0xfe79bc].hex() == '01000000000000008007000038040000'
    assert struct.unpack_from('<I', public_cp, 0xd6c294 + 4)[0] == 0x10e9070
    assert struct.unpack_from('<5I', public_cp, 0xfe1070) == (1, 0, 0, 0, 0)
    # movs r0,#0x21 before releasing the configuration synchronization object.
    assert public_cp[0x36754e:0x367550].hex() == '2120'
    # strb r1,[r2,r0] at CPVA1d614a sets the owned sink index marker to one.
    assert public_cp[0xce14a:0xce14c].hex() == '1154'
    # mov.w r2,#06000000; movs r0,#16/r1,#0/r2,#1 before writer.
    assert public_cp[0xced9c:0xceda0].hex() == '4ff0c062'
    assert public_cp[0xcedb0:0xcedb6].hex() == '102000210122'
    # Distinct component/code, full flags, width and height getters.
    assert public_cp[0x581c5a:0x581c78].hex() == (
        '007f08707047407f08707047c08b08807047406a08607047806a08607047')
