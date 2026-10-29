"""BB mode configuration: source-bound bytes, unknown masks and actual sem5 ownership."""
from pathlib import Path
import hashlib
import os
import re
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'
HOLES = (
    (0x000, 0x003), (0x025, 0x027), (0x058, 0x05b), (0x064, 0x067), (0x108, 0x17f),
    (0x181, 0x183), (0x1a8, 0x1ab), (0x1c1, 0x1c3), (0x1cd, 0x1cf), (0x239, 0x23b),
    (0x24e, 0x24f), (0x29d, 0x29f), (0x2a9, 0x2ab), (0x2d2, 0x2d3), (0x2de, 0x2df),
    (0x2e9, 0x2eb), (0x38e, 0x38f), (0x39e, 0x39f), (0x402, 0x403), (0x40e, 0x40f),
    (0x43e, 0x43f), (0x47a, 0x47b), (0x4ac, 0x4af), (0x4bc, 0x4bf), (0x4e5, 0x4e7),
    (0x5a2, 0x5a3), (0x61d, 0x61f), (0x657, 0x657),
)
VALUES_SHA = '4a54f05418fd81f15c85256277b0bb9af4cda585136fe7aa55cad3450cc84bb4'
KNOWN_SHA = 'e625bed55a2ea89239b64503d22f1fda0a23575e3f0b366e8731b92c0e5885d8'
CASES = (
    'CTOR_KNOWN1565_UNKNOWN195_SOURCE_PINS',
    'CTOR_ZERO_CANNOT_SUBSTITUTE_ACTUAL0110',
    'TWO_ACTUAL0118_IDEMPOTENT_VALUES_FRESH_SERIALS',
    'ACTUAL0110_SAVE_DISTINCT_WORD_READBACK',
    'SEM5_FULL1760_COPY_MASK_HASH_NO_ALIAS',
    'INVALIDATE_RETAINS_OPAQUE_BYTES_HISTORY_SNAPSHOT',
    'UNKNOWN_READ_UNTOUCHED_THEN_ONLY_REAL_UPDATES_RESTORE',
    'MASKED_READ_RANGES_PARTIAL_UNKNOWN_ALIAS_UNTOUCHED',
    'LIVE_COPY_OWNER_REJECTED_ORIGINAL_RETAINED',
    'DATA_MASK_TOKEN_HISTORY_SEAL_TAMPER_LATCHED',
    'DOUBLE_INIT_AND_FAULT_NEVER_RESET',
    'WRONG_LENGTH_0018_FLAGS_BODY_NULL_FAIL_RETAIN',
    'SEM5_ACQUIRE_FAIL_NO_COPY_OR_RELEASE',
    'SEM5_REENTRY_TAMPER_LATCH_BEFORE_RELEASE',
    'SEM5_RELEASE_FAILURE_REENTRY_RETAIN_COPY',
    'MISSING_SEM5_NEVER_COPY',
)


@pytest.fixture(scope='module')
def executed(tmp_path_factory):
    binary = tmp_path_factory.mktemp('bb-mode-config') / 'self-test'
    built = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-O1',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'bb-mode-config.c'), str(MODEL / 'test-bb-mode-config.c'),
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
def test_bb_mode_config_contract(executed, case):
    assert f'BB_MODE_{case}_PASS' in executed.splitlines()
    assert f'BB_MODE_CONFIG_CASES={len(CASES)}' in executed.splitlines()


def test_constructor_projection_and_coverage_are_frozen():
    data = bytearray([0xa5] * 1760)
    known = bytearray(1760)
    source = (MODEL / 'bb-mode-config-init.inc').read_bytes()
    assert hashlib.sha256(source).hexdigest() == (
        '44ea84414e8e14538016c98836277f35316e2ee77b3c81334144e68bc73ab81f')
    records = re.findall(rb'\{0x([0-9a-f]+)U, ([0-9]+)U, 0x([0-9a-f]+)U\}, /\* ([0-9a-f]+) \*/', source)
    assert len(records) == 234
    for offset, count, value, origin in records:
        offset, count, value, origin = int(offset, 16), int(count), int(value, 16), int(origin, 16)
        assert 0 <= offset < 1760 and 0 < count <= 1760 - offset
        assert 0x6996b0 <= origin < 0x699a30 and value <= 255
        assert not any(known[offset:offset + count])
        data[offset:offset + count] = bytes([value]) * count
        known[offset:offset + count] = b'\xff' * count
    expected_unknown = {x for start, end in HOLES for x in range(start, end + 1)}
    assert {i for i, mask in enumerate(known) if not mask} == expected_unknown
    assert known.count(255) == 1565 and len(expected_unknown) == 195
    assert hashlib.sha256(data).hexdigest() == VALUES_SHA
    assert hashlib.sha256(known).hexdigest() == KNOWN_SHA


def test_runtime_values_masks_and_invalidated_copy_independently(executed):
    fields = dict(line.split('=', 1) for line in executed.splitlines() if '=' in line)
    initial = bytes.fromhex(fields['BB_MODE_INITIAL_VALUES'])
    initial_known = bytes.fromhex(fields['BB_MODE_INITIAL_KNOWN'])
    copied = bytes.fromhex(fields['BB_MODE_INVALIDATED_COPY_VALUES'])
    copied_known = bytes.fromhex(fields['BB_MODE_INVALIDATED_COPY_KNOWN'])
    assert len(initial) == len(initial_known) == len(copied) == len(copied_known) == 1760
    assert hashlib.sha256(initial).hexdigest() == VALUES_SHA
    assert hashlib.sha256(initial_known).hexdigest() == KNOWN_SHA
    expected = bytearray(initial)
    expected[0x663], expected[0x664], expected[0x67c] = 3, 1, 1
    assert copied == expected
    restored = {0x663}
    for offset in (0x68, 0x664, 0x668, 0x66c, 0x670, 0x674, 0x678, 0x67c, 0x680, 0x298, 0x2a0):
        restored.update(range(offset, offset + 4))
    assert len(restored) == 45
    assert copied_known == bytes(255 if i in restored else 0 for i in range(1760))
    assert all(copied[i] == 0xa5 and copied_known[i] == 0
               for start, end in HOLES for i in range(start, end + 1))


def test_available_original_public_cp_pins():
    original = HERE / 'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha8_unpacked/cpapp-b.bin'
    if not original.is_file():
        pytest.skip('optional original public ALLLANG CP artifact not provisioned')
    data = original.read_bytes()
    assert len(data) == 18090880
    assert hashlib.sha256(data).hexdigest() == (
        'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')
    assert hashlib.sha256(data[0x6996b0-0x108000:0x699a30-0x108000]).hexdigest() == (
        '1414559b9533ca7767ec28b2b081f8e2a76e264c31d2b4438c03ffeaa7e32401')
    for address, expected in (
        (0x6996ec, 'a566'), (0x699ba6, '027a'), (0x699bb4, '8266'),
        (0x1aadfa, '4ff4dc62'), (0x1c1e8c, '806e'), (0x6986ee, '0860'),
    ):
        offset = address - 0x108000
        assert data[offset:offset + len(bytes.fromhex(expected))] == bytes.fromhex(expected)
