"""Exact AP40f9 local configuration consumer; no transport or runtime launch."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
CP_BASE, CP_END = 0x108000, 0x1248b80


def test_sanitized_configuration_and_boundaries(tmp_path):
    binary = tmp_path / 'cp-output-policy'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    result = subprocess.run(flags + [str(HERE / 'cp-output-policy.c'),
        str(HERE / 'test-cp-output-policy.c'), '-o', str(binary)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary)], env=env, capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == result.stderr == ''


def window(cp, va, size):
    # CP RAM (e.g. 165a8a4) is outside this file; never zero-fill or wrap it.
    if size < 0 or not CP_BASE <= va < CP_END or size > CP_END - va:
        raise ValueError('outside source-backed CP raw image')
    raw = va - CP_BASE
    result = cp[raw:raw + size]
    assert len(result) == size
    return result


def test_exact_public_source_and_checker_bounds():
    image = BASE / 'menu-root/cp/cpapp-b.bin'
    if not image.is_file():
        pytest.skip('public ALLLANG CP image not prepared; consumer self-test still runs')
    cp = image.read_bytes()
    assert len(cp) == 18090880 == CP_END - CP_BASE
    assert hashlib.sha256(cp).hexdigest() == CP_SHA
    # Five small source windows: record, setter, checker, dispatcher, dirty setter.
    pins = (
        (0x10fbd0c, 0x14, 'c01682c978916671c5a8f22c9551fdbddbe5265150126a809165ec308e34a76b'),
        (0x35a134, 0x48, '5a871d19900a319d318f3a4ca82b63596824f5fca3937642a41cf524c20a45a5'),
        (0x364c68, 0x80, 'a5a14d994825858589994206d932d7d54dfc10c8649b1ea5237eb22663815adb'),
        (0x35cf70, 0x178, '25293eb453e7bee8a32224a1ec06715e26f0eb556740109ec425771dcedc1ae1'),
        (0x996fec, 0xb0, '81c30e34a25f9d99a45c84570325d8256a1eaed89960b0367a6836e83d00419e'),
    )
    for va, size, digest in pins:
        assert hashlib.sha256(window(cp, va, size)).hexdigest() == digest
    record = window(cp, 0x10fab8c + 224 * 20, 20)
    assert struct.unpack('<5I', record) == (0x40f9, 0x35a135, 0, 0, 0x364c69)
    for va, size in ((CP_BASE - 1, 1), (CP_END, 1), (CP_END - 1, 2),
                     (0x165a720 + 0x184, 4), (CP_BASE, -1)):
        with pytest.raises(ValueError, match='source-backed'):
            window(cp, va, size)
    assert window(cp, CP_BASE, 1) == cp[:1]
    assert window(cp, CP_END - 1, 1) == cp[-1:]

    import capstone
    decoder = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)

    def instructions(va, size):
        return {ins.address: (ins.mnemonic, ins.op_str)
                for ins in decoder.disasm(window(cp, va, size), va)}

    setter = instructions(0x35a134, 0x48)
    assert setter[0x35a13a] == ('ldrb', 'r1, [r0, #8]')
    assert setter[0x35a148] == ('ldrb', 'r2, [r0, #9]')
    assert setter[0x35a14e] == ('ldr', 'r3, [r0, #0xc]')
    assert setter[0x35a154] == ('ldr.w', 'lr, [r0, #0x10]')
    for va, register, offset in ((0x35a144, 'r1', 0x184),
            (0x35a14a, 'r2', 0x188), (0x35a150, 'r3', 0x18c),
            (0x35a164, 'lr', 0x190)):
        assert setter[va] == ('str.w', f'{register}, [ip, #{offset:#x}]')
    assert [(mn, arg) for mn, arg in setter.values() if mn in ('bl', 'blx')] == [
        ('bl', '#0xb4457a')]
    assert setter[0x35a176] == ('movs', 'r0, #1')
    checker = instructions(0x364c68, 0x80)
    assert checker[0x364c7a] == ('cmp', 'r6, #1')
    for va, offset in ((0x364c80, 0x184), (0x364c92, 0x188),
                       (0x364caa, 0x18c), (0x364cc2, 0x190)):
        assert checker[va] == ('ldr.w', f'r2, [r5, #{offset:#x}]')
    assert checker[0x364c7e] == ('ldrb', 'r3, [r4, #8]')
    assert checker[0x364c90] == ('ldrb', 'r3, [r4, #9]')
    assert checker[0x364ca8] == ('ldr', 'r3, [r4, #0xc]')
    assert checker[0x364cc0] == ('ldr', 'r3, [r4, #0x10]')
    # Successful dispatch calls the handler, then a local dirty setter only.
    dispatch = instructions(0x35d074, 0x1c)
    assert dispatch[0x35d074] == ('ldr', 'r1, [r5, #-0x4]')
    assert dispatch[0x35d07a] == ('blx', 'r1')
    assert dispatch[0x35d07c] == ('ldr', 'r0, [r5]')  # record+8, pinned zero
    assert dispatch[0x35d080] == ('bl', '#0x996fec')
    dirty = instructions(0x996fec, 0xe)
    assert dirty[0x996ff6] == ('strb', 'r1, [r0]')
    assert dirty[0x996ff8] == ('bx', 'lr')
    assert all(mn not in ('bl', 'blx') for mn, _ in dirty.values())
