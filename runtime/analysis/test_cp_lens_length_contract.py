"""Pin the bounded maintenance reply wrapper; no lens state is inferred."""
import hashlib
from pathlib import Path
import struct

import pytest

CP = Path(__file__).resolve().parent / 'menu-root/cp/cpapp-b.bin'


@pytest.mark.skipif(not CP.is_file(), reason='optional original firmware asset not installed')
def test_original_maintenance_reply_lengths():
    data = CP.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    def at(va, size):
        return data[va - 0x108000:va - 0x108000 + size]
    assert at(0x4084e2, 2) == bytes.fromhex('2168')
    assert at(0x4084e6, 4) == bytes.fromhex('052903d2')
    assert at(0x4084ec, 4) == bytes.fromhex('50f82120')
    assert at(0x4084fe, 2) == bytes.fromhex('0822')
    assert struct.unpack('<5I', at(0x40850c, 20)) == (20, 12, 40, 8, 8)
    assert at(0xbec02a, 6) == bytes.fromhex('50f80c0c7047')
