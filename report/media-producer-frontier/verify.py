#!/usr/bin/env python3
"""Pinned read-only role checks; no live producer or recording claim."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def verify(path,seed=None):
    raw=path.read_bytes()
    if len(raw)!=99960744 or hashlib.sha256(raw).hexdigest()!='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b':
        raise ValueError('Original AP identity differs')
    offset=struct.unpack_from('<Q',raw,32)[0];stride,count=struct.unpack_from('<HH',raw,54)
    segments=[struct.unpack_from('<II6Q',raw,offset+i*stride) for i in range(count)]
    def read(va,n):
        for kind,flags,start,base,physical,length,memsize,align in segments:
            if kind==1 and base<=va and va+n<=base+length:return raw[start+va-base:start+va-base+n]
        raise ValueError('VA not file-backed')
    for va,hx in {
        0x28bbd0c:'417001b0761c0053007c029b216004912400008b236860f8e003142a821040b9810440f960003fd6',
        0x28bbaf4:'230040b9020080527f00006b0c020054240440b9020080521f00046b8c010054',
        0x28bbad4:'1f00026be303202ae2a79f1a437c436a4000005423c86038e003032ac0035fd6',
        0x2e292d8:'a1624bb9e203162a23008052a0058252784aea97',
        0x2e29304:'a1664bb9e203162a23008052c00582526d4aea97',
        0x2e1b068:'2200805222c8203885cbfd17',
        0x2e2e380:'ff0f40d1a2f386d2ff831ed1',
        0x2f55920:'820e84d220c7029000a02b91617e029b53ca02f073221b917302018b0100018be00313aaa71e9c97',
        0x2f50480:'a1822d91011000f9',
        0x2f50494:'37728152f759a072',
        0x2f504b4:'a1922d91011000f9',
        0x2ae00a8:'007c4093030680d2c26101d0428015910008039b021040f9e00301aa40001fd6',
    }.items():
        if read(va,len(bytes.fromhex(hx)))!=bytes.fromhex(hx):raise ValueError(f'Original role window differs at {va:#x}')
    properties={}
    for pid,expected in ((0x102d,(0x278c618,0x278c624,0x28483ec)),(0x102e,(0x278c648,0x278c654,0x28481dc))):
        row=struct.unpack('<6Q',read(0x5584c38+pid*48,48))
        if (row[1],row[2],row[3])!=expected:raise ValueError('Original property dispatch bindings differ')
        properties[hex(pid)]={'base_accessor_0x08':hex(row[1]),'value_accessor_0x20':hex(row[4]),
                              'value_accessor_0x28':hex(row[5]),'setter_entry_0x10':hex(row[2]),'setter_entry_0x18':hex(row[3])}
    initializers={}
    for address,pid,value,callback in ((0x4b39f30,0x102d,0,0x2b6ebcc),(0x4b49aa0,0x102e,30,0x2c3a010)):
        if struct.unpack('<II',read(address,8))!=(pid,value):raise ValueError('ROM initializer pair differs')
        data_row=struct.unpack('<6Q',read(0x571a560+pid*48,48))
        if data_row[4]!=callback:raise ValueError('Base-data callback binding differs')
        initializers[hex(pid)]={'rom_pair_va':hex(address),'rom_value':value,'base_data_callback':hex(callback)}
    values=None
    if seed is not None:
        backup=seed.read_bytes()
        if len(backup)!=2390264 or hashlib.sha256(backup).hexdigest()!='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47':
            raise ValueError('Not the pinned public seed')
        count,first=struct.unpack_from('<HI',backup,256+0x2cf*6);values={}
        for key in (0xf05,0xb91):
            if key>=count:raise ValueError('Public property absent')
            attr,pointer=struct.unpack_from('<HI',backup,256+819*6+(first+key)*6)
            size=pointer>>24;pos=pointer&0xffffff
            if not 0<size<=4 or pos+size>968981:raise ValueError('Public property outside bank0')
            values[hex(0x2cf0000|key)]={'bytes':size,'value':int.from_bytes(backup[pos:pos+size],'little'),'attr':hex(attr)}
    return {'original_snapshot_field_validation_mapping_verified':True,
            'snapshot_fields':{'+0xb60':'0x102d','+0xb64':'0x102e'},
            'settings_serialization_keys':{'+0xb60':'0x02cf0f05','+0xb64':'0x02cf0b91'},
            'public_seed_same_key_values_only':values,
            'old_apply_2e2232c_role':'the checked 102d/102e path validates values via 24-byte predicate table 0x56c4118; no live writer edge',
            'buffer_0x379d_role':'property-indexed byte status buffer, not snapshot length',
            'accessor_role_correction':'old +08 readings are reset/base layer; do not infer effective runtime values from them',
            'rom_base_initializers':initializers,
            'actual_property_dispatch':properties,'live_media_producer_verified':False,
            'runtime_probe_executed':False,'capture_verified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap',type=Path,default=Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root/usr/lib/appFw.so')
    parser.add_argument('--seed',type=Path,help='Optional pinned public seed; same values do not prove live source')
    args=parser.parse_args()
    try:print(json.dumps(verify(args.ap,args.seed),indent=2))
    except (OSError,ValueError,struct.error) as error:parser.exit(1,str(error)+'\n')
