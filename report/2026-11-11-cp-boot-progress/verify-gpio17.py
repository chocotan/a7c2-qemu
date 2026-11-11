#!/usr/bin/env python3
"""Verify fixed original CP GPIO17 consumer bytes and BK4 register writes offline."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
PP_SHA = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
PROPERTIES = (
    ('0', 0x6a874, 107, '75071d4fcb64a5c9842b7e0a0ac94e1ff8b91101921a5ca83a9b4756bcfe6286'),
    ('ed000', 0x152d10, 186, '03abbbe71a874a4a3a78d3fa9ab32104756e0f6ee0d00c1ab99dd808ac23fa70'),
)
WINDOWS = (
    (0x56a95a, '002083f240f7112002218cf268f7012801d101f0aafe02b080bd',
     'PCIEIF_INIT: notify ch0; get(17,2); if value==1 call56c6c4; return'),
    (0xbf7848, 'fff790fd38b128462146bde8b040fff7c2bd0020b0bd28462146bde8b040fff7adbd',
     'GPIO get: DIR value1 selects WDATA; value0 selects RDATA'),
    (0xbf73c4, '4df210020003cff201121058012202fa01f1084018bf01207047',
     'GPIO RDATA: read f101d010+(port<<12), return selected input bit'),
    (0xbee794, '7df596f7', 'IRQ handler bee790 also calls56c6c4'),
)
REGISTERS = {0x00: 'dir', 0x20: 'inen', 0x30: 'portsel', 0x40: 'wdata'}


def fold(rows, initial):
    """Apply evidenced register writes; does not invent RDATA or a reset value."""
    if type(initial) is not int or not 0 <= initial <= 0xffffffff:
        raise ValueError('Initial word must be uint32')
    state = dict.fromkeys(REGISTERS.values(), initial)
    for row in rows:
        offset, value = row['offset'], row['value']
        register = REGISTERS.get(offset & ~0xf)
        operation = offset & 0xf
        if register is None or operation not in (4, 8) or not 0 <= value <= 0xffffffff:
            raise ValueError('Unknown GPIO register-script write')
        if operation == 4:
            state[register] |= value
        else:
            state[register] &= ~value
    return state


def verify(cp_path, pp_path):
    blobs=[]
    for source,size in ((Path(cp_path),18090880),(Path(pp_path),2390264)):
        if not source.is_file() or source.stat().st_size!=size:
            raise ValueError('Original CP/PP size or identity differs')
        with source.open('rb') as stream:
            data=stream.read(size+1)
        if len(data)!=size:
            raise ValueError('Original CP/PP changed while reading')
        blobs.append(data)
    cp,pp=blobs
    if hashlib.sha256(cp).hexdigest() != CP_SHA or hashlib.sha256(pp).hexdigest() != PP_SHA:
        raise ValueError('Original CP/PP identity differs')
    instructions = []
    for address, expected, meaning in WINDOWS:
        raw = cp[address - 0x108000:address - 0x108000 + len(expected) // 2]
        if raw.hex() != expected:
            raise ValueError('Original consumer bytes differ')
        instructions.append(dict(address=hex(address),raw=expected,meaning=meaning))
    records = []
    for record, start, end, digest in PROPERTIES:
        prop = pp[start:start + 4608]
        if hashlib.sha256(prop).hexdigest() != digest or struct.unpack_from('<III', prop, end*12) != (0,0,0):
            raise ValueError('Original REG property boundary differs')
        rows = []
        for index in range(end):
            op, address, value = struct.unpack_from('<III', prop, index*12)
            if 0xf102e000 <= address < 0xf102e100:
                if op != 2:
                    raise ValueError('GPIO row is not original op32 write')
                rows.append(dict(index=index, offset=address - 0xf102e000, value=value))
        low, high = fold(rows,0), fold(rows,0xffffffff)
        if (low['dir'] & 4 or high['dir'] & 4 or not low['inen'] & high['inen'] & 4):
            raise ValueError('GPIO17 pin2 input projection differs')
        records.append(dict(record=record,property_sha256=digest,rows=rows,
                            projected_from_zero=low,projected_from_all_ones=high))
    return dict(schema='a7c2-gpio17-consumer-static-v1',cp_sha256=CP_SHA,pp_sha256=PP_SHA,
                instructions=instructions,records=records,
                input_address='0xf102e010',input_bit=2,peer_input_value=None,
                static_consumer_verified=True,gpio17_runtime_model_implemented=False,
                original_reg_script_executed=False,guest_rdata_consumption_verified=False,
                irq_to_physical_pin_mapping_verified=False,original_peer_consumption_verified=False)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--pp',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    result=verify(args.cp,args.pp)
    with args.out.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True)
        stream.write('\n')
    print('GPIO17_STATIC_CONSUMER_VERIFIED',args.out)
