#!/usr/bin/env python3
"""Pinned original ADF record access/writes; does not execute or claim playback."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SHA='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
BASE=0x108000


def verify(path):
    raw=path.read_bytes()
    if len(raw)!=18090880 or hashlib.sha256(raw).hexdigest()!=SHA:
        raise ValueError('Original CP identity differs')
    def read(address,size):
        offset=address-BASE
        if offset<0 or offset+size>len(raw):raise ValueError('Address outside CP image')
        return raw[offset:offset+size]
    for address,hx in {
        0x6807fe:'40f27070c0f223107047',
        0x6809ce:'00f1140c00239cf80200012803d19cf80000884207d0',
        0x6809e4:'01330cf1280c1e2bf2d34ef202007047',
        0x67f2f4:'b1782a4601f069fb',
        0x67f31e:'0898e060029901f14002c4e9042008440021a061',
        0x67f334:'70682062',
        0x6808dc:'02a9484600f02ff8012810d1',
        0x6808e8:'d8f8002002a948461cf7e4f1',
        0x19ccc4:'00f11605904600202a7832b1283501301e28f9d3',
        0x19ccde:'0a46a5f10e0c59caace85900',
        0x19ccfc:'d1e90001d2e900c6',
        0x19cd3e:'c5f81200',
    }.items():
        if read(address,len(bytes.fromhex(hx)))!=bytes.fromhex(hx):
            raise ValueError(f'Original code differs at CPVA {address:#x}')
    for address,target in ((0xd14a98,0x67f24f),(0xd14aa4,0x67f2d7),(0xd14ab8,0xcd0d90)):
        if struct.unpack('<I',read(address,4))[0]!=target:
            raise ValueError('Static virtual method or RTTI reference differs')
    return {'static_record_access_verified':True,'static_registration_copy_verified':True,
            'cp_sha256':SHA,'registration_object':'0x01230770','slot_count':30,'slot_stride':'0x28',
            'kind_offset_in_slot':'0x0c','active_offset_in_slot':'0x0e',
            'lookup_result_word_0x20':'four-region address mapping of candidate u64 at +0',
            'constructed_fields':{'+0c':'A','+10':'W+0x40','+14':'A','+18':'W+A','+20':'payload+4:u32'},
            'A':'lookup result+0x20','W':'lookup result+8, semantic domain unresolved',
            'wire0203_dispatch_verified':False,'format_verified':False,'loop_unit_verified':False,
            'ownership_completion_verified':False,'playback_verified':False,'host_audio_verified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--cp',type=Path,required=True)
    try:print(json.dumps(verify(parser.parse_args().cp),indent=2))
    except (OSError,ValueError) as error:parser.exit(1,str(error)+'\n')
