"""Strict source boundary and explicit reply-only 402d diagnostic; no VM."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
ACTUAL_WIRE = bytes.fromhex('05002d402700008002000101010101000101010101000000')


@pytest.fixture(scope='module')
def sanitized_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('capture-format') / 'cp-capture-format'
    command = [
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-pthread', '-DNATIVE_CP_CAPTURE_FORMAT_TEST',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(HERE / 'cp-capture-format.c'), str(HERE / 'test-cp-capture-format.c'),
        '-o', str(binary),
    ]
    built = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


def run_sanitized(binary, *args):
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1')
    run = subprocess.run([str(binary), *args], env=env, capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stdout + run.stderr
    return run.stdout


def test_actual_wire_sanitized(sanitized_binary):
    assert 'no ACK/CP/EE/frame/capture' in run_sanitized(sanitized_binary)


@pytest.mark.parametrize('case', '''
    normal opaque default-off unrelated wrong-type other-destination short-header
    preinit missing-io missing-guard guard-incomplete badlen long wrong-source
    notification-missing diag-missing all13-missing staging-missing reserve-refused
    allocfail null-allocation short-allocation long-allocation alias overlap overlap-before
    bad-reply-source bad-reply-copy allocation-error-pointer lost-guard mutated-request cleanupfail
    sendfail send-cleanupfail requestfail replyfail inline-free fast-free-reuse reentrant
    inspect-reentrant reentrant-free async-inflight before-send-fault fork-lock foreign
    wrong-waiter wrong-owner altered-wire altered-source altered-size
'''.split())
def test_diagnostic_transport_sanitized(sanitized_binary, case):
    assert 'diagnostic402d transport only' in run_sanitized(sanitized_binary, case)


def test_actual_wire_literal():
    assert len(ACTUAL_WIRE) == 24
    assert struct.unpack_from('<I', ACTUAL_WIRE, 4) == (0x80000027,)
    assert ACTUAL_WIRE[8:10] == b'\x02\x00'
    assert struct.unpack_from('<6H', ACTUAL_WIRE, 10) == (257, 257, 1, 257, 257, 1)


def test_public_cp_source_boundary():
    candidates = [BASE / 'menu-root/cp/cpapp-b.bin']
    # Historical public image is read only for comparison, never runtime code.
    if len(BASE.parents) > 5:
        candidates.append(BASE.parents[5] / 'analysis/qemu-runtime/analysis/menu-root/cp/cpapp-b.bin')
    path = next((path for path in candidates if path.is_file()), None)
    if path is None:
        pytest.skip('public ALLLANG CP image unavailable; host C self-test still runs')
    cp = path.read_bytes()
    assert len(cp) == 18090880 and hashlib.sha256(cp).hexdigest() == CP_SHA
    raw_base = 0x108000
    pins = (
        (0x10faec0, 0x14, 'cc3c776b3fd580ffc519d4e31e6a4a2c5b501e2fa42fe05be70feb918b3cc479'),
        (0x3561cc, 0x112, 'e5f44a6a510ec09617cf0cc595b74cda40673a4b29c419b11035b77117962fca'),
        (0x35f4b0, 0x18a, 'f28756d1226f24c2982d588ff9266466cdbfcfc2638786537647ad9630c2fe93'),
        (0x353ea4, 0x148, '6e652939fe0f4ebb5e4bdcc6c78beb6d8b5dbb90dd251b04b682071a78d9a28e'),
        (0x353fec, 0x180, '4760e60f8c09a5fe463f6b91f5490a6ff8d2a781ba5c9a0d24ac9b3d023df04f'),
        (0xb0de20, 0x30, 'c5e5ef22689288b82160abdda20929d15d1e6337af97a123dd5f1591418a2918'),
        (0xb0e99e, 0x180, 'de8b7516e7f71467df82258f0305d23ff2d5866e67acc0816f77c1458a5a15e2'),
        (0xb0eb2c, 0x54, '1cc8da6831c25a918af9802e77c0b5bb073002dd9abf1d8af00931c2f0389be2'),
    )
    for address, size, digest in pins:
        window = cp[address-raw_base:address-raw_base+size]
        assert len(window) == size and hashlib.sha256(window).hexdigest() == digest
    records = [struct.unpack_from('<5I', cp, 0x10fab8c-raw_base+n*20) for n in range(350)]
    assert [(n, row) for n, row in enumerate(records) if row[0] == 0x402d] == [
        (41, (0x402d, 0x3561cd, 0, 0, 0x35f4b1))]
    # Mandatory first reads cannot be satisfied by the 402d request fields.
    assert cp[0x353eac-raw_base:0x353eb0-raw_base] == bytes.fromhex('dcf80001')
    assert cp[0x353ed2-raw_base:0x353ed6-raw_base] == bytes.fromhex('dcf81011')
    # Every post-copy dependency precedes the response construction.
    assert cp[0x35629a-raw_base:0x3562a2-raw_base] == bytes.fromhex('fdf703fefdf7a5fe')
    assert cp[0x3562aa-raw_base:0x3562ae-raw_base] == bytes.fromhex('b7f3b9f5')
    assert cp[0x3562ae-raw_base:0x3562b4-raw_base] == bytes.fromhex('01208df82800')
    assert cp[0x3562be-raw_base:0x3562c4-raw_base] == bytes.fromhex('4ff470400c90')
