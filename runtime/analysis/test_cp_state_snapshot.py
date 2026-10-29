"""Pure CP2040 layout foundation: no runtime snapshot/provider/publication."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
HERE = BASE / 'device-models'


def test_bounded_snapshot_copy_with_sanitizers(tmp_path):
    obj, binary = tmp_path / 'snapshot.o', tmp_path / 'snapshot'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    for command in (
        flags + ['-c', str(HERE / 'cp-state-snapshot.c'), '-o', str(obj)],
        flags + [str(obj), str(HERE / 'test-cp-state-snapshot.c'), '-o', str(binary)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary)], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        'layout_copied_only=1 semantic_applied=0 publication=0 runtime_snapshot_offered=0')
    symbols = subprocess.run(['nm', '-g', '--defined-only', str(obj)],
                             capture_output=True, text=True, timeout=10)
    assert symbols.returncode == 0, symbols.stderr
    assert {line.split()[-1] for line in symbols.stdout.splitlines()} == {'cp_state_snapshot_copy'}


@pytest.mark.parametrize('relative,identity,va,length,window', (
    # Existing lens-init-contract/README.md E4/E6 and verify_product_enum.py pins.
    ('cp/cpapp-b.bin', 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428',
     0x353c18, 0x198, '439e2cfc2857b7ab84f35ce18f9bd4e37b10f05d03d2db7f4e6bdaf3434e6aa8'),
    ('usr/lib/appFw.so', '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
     0x3549330, 0x340, '2c3058f3307b6d9d9888f7d9d0e21f133a52654b07363ec314a9c198ed9080c6'),
    ('usr/lib/appFw.so', '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
     0x351fdb8, 0xd0, '4fb7561962c302d178f007b212d8e6db9960d1fccb5b4740535136b0aa5caebd'),
))
def test_existing_public_source_pins(relative, identity, va, length, window):
    source = BASE / 'menu-root' / relative
    if not source.is_file():
        pytest.skip('prepare the public ALLLANG assets separately; source pin only is skipped')
    blob = source.read_bytes()
    assert hashlib.sha256(blob).hexdigest() == identity
    if relative.startswith('cp/'):
        offset = va - 0x108000
    else:
        assert blob[:6] == b'\x7fELF\x02\x01'
        ph = struct.unpack_from('<Q', blob, 32)[0]
        ent, count = struct.unpack_from('<HH', blob, 54)
        offsets = []
        for index in range(count):
            p = struct.unpack_from('<IIQQQQQQ', blob, ph + ent*index)
            if p[0] == 1 and p[3] <= va and va + length <= p[3] + p[5]:
                offsets.append(p[2] + va - p[3])
        assert len(offsets) == 1
        offset = offsets[0]
    data = blob[offset:offset + length]
    assert len(data) == length
    assert hashlib.sha256(data).hexdigest() == window
