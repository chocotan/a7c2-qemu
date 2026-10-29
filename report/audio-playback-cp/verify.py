#!/usr/bin/env python3
"""Read-only verification of CP wire 032b mapping; no target execution."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

BASE=0x108000
SIZE=18090880
SHA='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'


def verify(path):
    image=path.read_bytes()
    if len(image)!=SIZE or hashlib.sha256(image).hexdigest()!=SHA:
        raise ValueError('Original CP identity differs')

    def read(address,size):
        offset=address-BASE
        if offset<0 or offset+size>len(image):raise ValueError('CPVA outside image')
        return image[offset:offset+size]

    def exact(address,hexadecimal):
        expected=bytes.fromhex(hexadecimal)
        if read(address,len(expected))!=expected:
            raise ValueError(f'Original bytes differ at CPVA {address:#x}')

    for address,expected in {
        0x1c5300:'f0b503af2de900078eb098460e460446',
        0x1c5326:'6388',                 # wire command = u16[M+2]
        0x1c533a:'a3f54070472800f2c283dfe810f0',
        0x1c59e0:'0020b8f1010f0690089608bf0a94',
        0x1c59f2:'40f2487106aa1c23c9f28421fef7b1fa',
        0x1c3ffc:'e6683046',             # E+c -> original message
        0x1c4004:'23680546a3f12000c02800f2f380dfe810f0',
        0x1c4942:'304605f0f8fe',
        0x1c322e:'088846f604520021c0f2d10252f82130984210d001315529f8d3',
        0xd16de0:'c3000000',
        0x1bee34:'f0b503af2de9000f87b040f2477403aec9f28424',
        0x1bee48:'204631464ff0ff32a6f3aafa',
        0xbec28e:'10b150f8080c7047',
        0x1beefa:'e8b2082800f23482dfe810f0',
        0x1beff4:'039851460022012306f080f9',
        0x1bef3e:'039851460022002306f0dbf9',
    }.items():exact(address,expected)

    def tbh(table,index):
        entry=table+2*index
        displacement=struct.unpack('<H',read(entry,2))[0]
        return entry,table+2*displacement

    controls=[]
    for wire,event,target in ((0x32a,0xc2,0x1c5608),(0x32b,0xc3,0x1c560e),(0x32c,0xc4,0x1c5614)):
        entry,actual=tbh(0x1c5348,wire-0x300)
        if actual!=target:raise ValueError('Wire TBH target differs')
        exact(target,bytes((event,0x20,0x07,0x90)).hex())
        branch=struct.unpack('<H',read(target+4,2))[0]
        if branch&0xf800!=0xe000:raise ValueError('Expected unconditional Thumb branch')
        displacement=(branch&0x7ff)<<1
        if displacement&0x800:displacement-=0x1000
        if target+8+displacement!=0x1c59e0:raise ValueError('Envelope continuation differs')
        controls.append({'wire':hex(wire),'event':hex(event),'entry':hex(entry),'target':hex(actual)})

    entry,target=tbh(0x1c4016,0xc3-0x20)
    if target!=0x1c4942:raise ValueError('Event TBH target differs')
    # Thumb-2 BL immediate: independently decode the pinned original call.
    first,second=struct.unpack('<HH',read(0x1c4944,4))
    sign=(first>>10)&1
    i1=1^((second>>13)&1)^sign
    i2=1^((second>>11)&1)^sign
    displacement=(sign<<24)|(i1<<23)|(i2<<22)|((first&0x3ff)<<12)|((second&0x7ff)<<1)
    if sign:displacement-=1<<25
    if 0x1c4948+displacement!=0x1ca738:raise ValueError('Original relay BL target differs')
    event_table=struct.unpack('<85I',read(0xd16d04,85*4))
    if [i for i,event in enumerate(event_table) if event==0xc3]!=[55]:
        raise ValueError('Internal event membership differs')
    for category,expected in ((1,0x1bef3e),(8,0x1beff4)):
        _,actual=tbh(0x1bef06,category)
        if actual!=expected:raise ValueError('Converter caller-category table differs')
    return {'static_mapping_verified':True,'cp_sha256':SHA,'controls':controls,
            'event_entry':hex(entry),'relay':'0x1ca738',
            'internal_membership_table_count':85,'c3_membership_index_decimal':55,
            'pointer_condition':'converter entry r3 == 1',
            'static_receiver_id':'0x92840747',
            'receiver_category_8_converter_r3':1,
            'receiver_category_1_converter_r3':0,
            'actual_received_category_verified':False,
            'actual_entry_arguments_verified':False,'queue_receive_path_verified':False,
            'completion_contract_verified':False,'playback_verified':False,'host_audio_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    args=parser.parse_args()
    try:result=verify(args.cp)
    except (OSError,ValueError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
