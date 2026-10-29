"""Owned command tests plus an optional pinned-source Thumb immediate check."""
from pathlib import Path
import os
import hashlib
import re
import struct
import subprocess

import pytest

MODEL = Path(__file__).resolve().parent / 'device-models'


def test_original_task_error_immediate():
    cp = MODEL.parent / 'menu-root/cp/cpapp-b.bin'
    if not cp.is_file():
        pytest.skip('provision the pinned public ALLLANG CP first')
    data = cp.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    raw = data[0xb6d1c4 - 0x108000:0xb6d1c4 - 0x108000 + 4]
    assert raw == bytes.fromhex('41f20400')
    first, second = struct.unpack('<HH', raw)
    immediate = ((first & 15) << 12) | ((first & 0x400) << 1) | ((second & 0x7000) >> 4) | (second & 255)
    definition = re.search(r'FULL_ADF_AIP_TASK_ERROR\s+(0x[0-9a-fA-F]+)u', (MODEL / 'adf-aip-commands.h').read_text())
    assert definition and int(definition.group(1), 16) == immediate == 0x1004


@pytest.fixture(scope='module')
def command_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('adf-aip-commands') / 'test-commands'
    result = subprocess.run([
        'cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        str(MODEL / 'adf-aip-commands.c'), str(MODEL / 'adf-aip-disable.c'),
        str(MODEL / 'test-adf-aip-commands.c'),
        '-o', str(binary),
    ], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('case', [
    'success', 'init', 'enqueue', 'state', 'events', 'provider', 'reentry', 'mutation', 'reuse',
    'input-success', 'input-begin', 'input-packets', 'input-events', 'input-provider',
    'input-mutation', 'input-state', 'input-clone-legacy',
    'output-success', 'output-begin', 'output-packets', 'output-events', 'output-state',
    'output-provider', 'output-clone-legacy',
])
def test_owned_af_b0_consumer(command_binary, case):
    result = subprocess.run([str(command_binary), case], capture_output=True, text=True,
        timeout=10, env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                            UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ADF_AIP_OWNED_AF_B0_CONSUMPTION_PASS' in result.stdout
