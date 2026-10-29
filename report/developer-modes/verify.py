#!/usr/bin/env python3
"""Pinned offline checks for Sony startup modes, not execution of mode switches."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

IDENTITIES={
    'usr/bin/bootin.elf':'dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2',
    'usr/bin/change_mode.sh':'0c277c24e503f214ebdb651ea1bec569ebd31d6c19c27156f3df29394621fc75',
    'sbin/init2':'45d3b907e6ef96c9a930cd3e6f919db700bffb5f18c386abfdb655f4d9954aeb',
}


def check(root):
    for name,sha in IDENTITIES.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=sha:raise ValueError('Original asset differs: '+name)
    raw=(root/'usr/bin/bootin.elf').read_bytes()
    if len(raw)!=23960 or raw[:6]!=b'\x7fELF\x02\x01':raise ValueError('Wrong original ELF')
    phoff=struct.unpack_from('<Q',raw,32)[0];phsize,count=struct.unpack_from('<HH',raw,54)
    segments=[struct.unpack_from('<II6Q',raw,phoff+i*phsize) for i in range(count)]
    def read(va,n):
        for kind,flags,offset,start,physical,length,memsize,align in segments:
            if kind==1 and start<=va and va+n<=start+length:return raw[offset+va-start:offset+va-start+n]
        raise ValueError('Unbacked VA')
    for va,hx in {
        0x402518:'83781a12631c00537f400171a100005421001a32',
        0x402c50:'60043036',
        0x402c74:'000000b00100805200e025911cfaff97',
        0x402cc4:'ff1200f1fa03172ac1140054',
        0x402f70:'e00319aa4ff9ff97e20300aae10314aae00319aaabf9ff97',
        0x402fb8:'000000b0e10319aa0020289122008052d2f9ff97',
        0x402ed4:'60ca41b980003036000000b000202891c7f9ff97',
        0x402910:'5fc4007181000054020000b042482a91e8feff17',
        0x402924:'5fc8007181000054020000b0426c2a91e3feff17',
        0x402938:'5fcc0071c1dbff54020000b042982a91defeff17',
    }.items():
        if read(va,len(bytes.fromhex(hx)))!=bytes.fromhex(hx):raise ValueError(f'Original branch differs at {va:#x}')
    paths=[]
    for va in range(0x403f08,0x403f48,16):
        pointer=struct.unpack('<Q',read(va,8))[0]
        paths.append(read(pointer,80).split(b'\0',1)[0].decode())
    if paths!=['/usr/tool/libLeakTracer.so','/usr/tool/libefence.so','/usr/lib/libjemalloc.so','/usr/tool/libasan.so']:
        raise ValueError('Original four-entry preload prefix table differs')
    return {'pinned_scripts_and_selected_bootin_branches_verified':True,
            'scope':'mode parse P flag, mode1/2/3 stage strings, four-entry preload-file match/setenv, conditional unsetenv',
            'preload_file_branch_known_paths':paths,
            'preload_file_branch_arbitrary_path_verified':False,
            'tools_at_exact_expected_paths':{p:(root/p.lstrip('/')).is_file() for p in paths+['/usr/bin/gdb','/usr/bin/gdbserver']},
            'all_modes_dynamically_verified':False,'mode_switch_executed':False,'capture_verified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root')
    args=parser.parse_args()
    try:print(json.dumps(check(args.root),indent=2))
    except (OSError,ValueError,struct.error) as error:parser.exit(1,str(error)+'\n')
