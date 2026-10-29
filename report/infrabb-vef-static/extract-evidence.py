"""Extract bounded original CP evidence; does not execute or modify firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
WINDOWS = {
    'vef_connect_postprocess': (0x10c7e8,0x80),
    'infrabb_consume_match_close_release': (0xce1e8,0x7c),
    'infrabb_descriptor_open216': (0xd38b4,0xee),
    'infrabb_descriptor_close216': (0xd3a48,0x42),
    'infrabb_owner_release216': (0xd373c,0x48),
    'vef_descriptor_allocate152': (0x5eab40,0x62),
    'vef_format_producer': (0x10ddb4,0xec),
    'vef_creator_close152': (0x5ea88c,0x44),
    'ssyn_append_first_payload': (0x5e0dce,0xe8),
    'infrabb_cold_expected_payload': (0xfe79ac,16),
}


def evidence(cp,wrapper):
    data=cp.read_bytes()
    if hashlib.sha256(data).hexdigest()!=SHA:
        raise ValueError('Original CP identity differs')
    elf=wrapper.read_bytes()
    if elf[:6]!=b'\x7fELF\x01\x01':
        raise ValueError('Expected little-endian ELF32 wrapper')
    shoff=struct.unpack_from('<I',elf,32)[0]
    entsize,count=struct.unpack_from('<HH',elf,46)
    text=[]
    for i in range(count):
        _,kind,flags,_,offset,size,*_=struct.unpack_from('<10I',elf,shoff+i*entsize)
        if kind==1 and flags&4:
            text.append(elf[offset:offset+size])
    if text!=[data]:
        raise ValueError('Wrapper executable section differs from original CP')
    checks={0xd38e6:'d823',0xd38f0:'049d',0xd38f6:'5520',
            0xd38f8:'c5e90264',0xd38fc:'a882',
            0xd3a70:'d823',0xd3a7c:'2520',0xd3a80:'5520',
            0xd3768:'d823',0xd3774:'2320',0xd3778:'5520'}
    # Check only opcodes independently decoded in the corresponding Thumb windows.
    for address,expected in checks.items():
        if data[address:address+len(bytes.fromhex(expected))]!=bytes.fromhex(expected):
            raise ValueError(f'Instruction assertion differs at raw {address:#x}')
    payload=bytes.fromhex('01000000000000008007000038040000')
    if data[0xfe79ac:0xfe79bc]!=payload:
        raise ValueError('Original cold expected payload differs')
    return {'cp_sha256':SHA,'wrapper_text_matches_original':True,
            'address_convention':'CP raw; CPVA=raw+0x108000',
            'cold_expected_payload_hex':payload.hex(),
            'windows':{name:{'raw':hex(offset),'cpva':hex(offset+0x108000),
                            'bytes':size,'hex':data[offset:offset+size].hex()}
                       for name,(offset,size) in WINDOWS.items()},
            'evidence_scope':'original-static-only',
            'connection_runtime_verified':False,'buffer_consumer_runtime_verified':False,
            'pixels_consumed':False,'camera_startup_verified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',required=True,type=Path)
    parser.add_argument('--wrapper',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    result=evidence(args.cp,args.wrapper)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print('ORIGINAL_CP_WRAPPER_AND_COLD_PAYLOAD_STATIC_ASSERTIONS_PASS')
