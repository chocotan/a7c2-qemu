"""Verify the original reset-store instruction and root-binding windows, not CP execution."""
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent


def test_original_explicit_reset_store_and_import_branches():
    pins = json.loads((HERE / 'source-pins.json').read_text())
    raw = (HERE.parents[1] / pins['asset']['path']).read_bytes()
    assert len(raw) == pins['asset']['bytes'] == 18090880
    assert hashlib.sha256(raw).hexdigest() == pins['asset']['sha256']
    base = pins['asset']['va_base']
    assert base == 0x108000 and base + len(raw) == pins['asset']['file_backed_va_end']
    for window in pins['windows']:
        va, length = int(window['va'], 16), window['bytes']
        assert base <= va < va + length <= base + len(raw)
        assert hashlib.sha256(raw[va-base:va-base+length]).hexdigest() == window['sha256']
    assert len(pins['windows']) == 5 and sum(w['bytes'] for w in pins['windows']) == 446
    for va, expected in ((0x8db6aa, '0446'), (0x8db6ac, '0025'), (0x8db6d6, 'c4e97255')):
        assert raw[va-base:va-base+len(expected)//2].hex() == expected
    assert pins['event']['bytes'] == 8 and pins['event']['offset'] == 0x1c8
    assert int(pins['event']['mutable_root'], 16) + 0x1c8 == int(pins['event']['mutable_field'], 16)
    assert int(pins['event']['published_root'], 16) + 0x1c8 == int(pins['event']['published_field'], 16)
    assert not any(pins[k] for k in ('complete_constructor_applied', 'native_constructor_executed',
                                    'published_override_value_verified', 'cp_reply_known_mask_promoted',
                                    'capture_verified'))

    seed = (HERE.parents[1] / 'runtime/analysis/menu-root/seed-backup.bin').read_bytes()
    assert len(seed) == 2390264
    assert hashlib.sha256(seed).hexdigest() == '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    bank = 0xed000
    sections, properties, data_offset, data_length, checksum = struct.unpack_from('<5I', seed, bank+16)
    record = seed[bank:bank+data_offset+data_length]
    assert record[12:16] == b'BK4\0'
    assert (sum(record[:32])+sum(record[36:])) & 0xffffffff == checksum
    values = {}
    for key in (0x00030160, 0x0092001c):
        count, first = struct.unpack_from('<HI', record, 0x100+(key>>16)*6)
        assert key & 0xffff < count and first + count <= properties
        _, pointer = struct.unpack_from('<HI', record, 0x100+sections*6+(first+(key&0xffff))*6)
        assert pointer != 0xffffffff
        size, offset = pointer>>24, pointer&0xffffff
        if size == 255:
            size = struct.unpack_from('<H', record, offset)[0]
            offset += 2
        elif size == 0:
            size, maximum = struct.unpack_from('<HH', record, offset)
            assert size <= maximum
            offset += 4
        assert data_offset <= offset and offset+size <= len(record)
        values[key] = record[offset:offset+size]
    assert values[0x00030160] == bytes(4096)
    assert values[0x0092001c] == bytes(4)
    assert int.from_bytes(values[0x00030160][:4], 'little') != 0xd68
    assert not int.from_bytes(values[0x0092001c], 'little') & 4
