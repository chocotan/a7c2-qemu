"""Strict virtual DFS selector; the original clock rates are not emulated."""
from pathlib import Path
import hashlib
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
HARDWARE = HERE / 'hardware'


def test_selector_core_under_sanitizers(tmp_path):
    binary = tmp_path / 'dfs'
    built = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(HARDWARE / 'dfs.c'), str(HARDWARE / 'test_dfs.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DFS_SELECTOR_CORE_PASS' in result.stdout


def test_original_upm_selector_instruction_contract():
    path = HERE / '../../runtime/analysis/menu-root/usr/kmod/upm.ko'
    if not path.is_file():
        pytest.skip('Original public ALLLANG assets not prepared')
    from elftools.elf.elffile import ELFFile
    assert hashlib.sha256(path.read_bytes()).hexdigest() == 'a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb'
    with path.open('rb') as stream:
        text = ELFFile(stream).get_section_by_name('.text').data()
    pins = {
        0xaff4:'61158e92202080520127bef2200000b9',  # init f1388f54 = 101
        0xb05c:'e1158e92202080520127bef2200000b9',  # request f1388f50 = 101
        0xb07c:'600240b9', 0xb08c:'60ff4737',      # old CK_STATUS busy bit8
        0xb090:'9422152a', 0xb0a8:'200000b9',      # mode | arg1<<8, write target
        0xb0b0:'e1148e92200080520127bef2200000b9',  # trigger f1388f58 = 1
        0xb114:'a20240b9', 0xb13c:'0000140a1f04007161feff54',
        0x2358c:'9f02136b',                      # whole target enum comparison
    }
    for address, expected in pins.items():
        value = bytes.fromhex(expected)
        assert text[address:address+len(value)] == value, hex(address)
