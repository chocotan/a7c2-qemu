import hashlib
import json
import struct
from pathlib import Path

HERE=Path(__file__).resolve().parent

def test_original_rc_destination_contract():
    pins=json.loads((HERE/'source-pins.json').read_text())
    raw=(HERE.parents[1]/pins['asset']['path']).read_bytes()
    assert len(raw)==pins['asset']['bytes']==13797088
    assert hashlib.sha256(raw).hexdigest()==pins['asset']['sha256']
    total=0
    for w in pins['windows']:
        a,b=int(w['start'],16),int(w['end'],16)
        assert hashlib.sha256(raw[a:b]).hexdigest()==w['sha256'];total+=b-a
    assert len(pins['windows'])==12 and total==13880
    base=0xffffffc001000000; table=0x3883c8
    assert struct.unpack_from('<Q',raw,0xbfbcc8)[0]==base+table
    for off,fn in ((0,0x2d8c60),(0x18,0x2d835c),(0x20,0x2d86fc),(0x40,0x2d7958)):
        assert struct.unpack_from('<Q',raw,table+off)[0]==base+fn
    assert pins['selector']['value']==0
    assert pins['selected_destination']['stride_relation'].startswith('M14+M18=2*W with original arithmetic widths')
    assert pins['selector']['component_order_name'] is None
    for witness in pins['table_witnesses']:
        start = int(witness['offset'], 16)
        expected = bytes.fromhex(witness['hex'])
        assert raw[start:start + len(expected)] == expected
    for start, expected in ((0x561b0, '7f8a01b9'), (0x561c4, '7f8e01b9'),
                            (0x6315c, '7f0000b9'), (0x64a10, '21200091')):
        assert raw[start:start + 4].hex() == expected
    assert not pins['native_pixel_layout_known'] and not pins['actual_dma_lease_verified'] and not pins['guest_pixel_consumed'] and not pins['capture_verified']
