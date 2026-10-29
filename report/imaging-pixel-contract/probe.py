#!/usr/bin/env python3
"""Read-only byte probe. AP/D/M/F=ELF VA; K=av-cam raw; CP=raw+0x108000.
Usage: probe.py pins | asm AP 0x34f6324 0x180 [thumb] | data K 0x30b400 0x18
Only writes evidence beside this script. Requires installed capstone/pyelftools.
"""
from pathlib import Path
import argparse, hashlib, json
from capstone import Cs, CS_ARCH_ARM64, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile
ROOT = Path(__file__).resolve().parents[2]
MENU = ROOT/'runtime/analysis/menu-root'
OUT = Path(__file__).resolve().parent
AP = MENU/'usr/lib/appFw.so'
PINS = {'AP': (AP, '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
 'D': (MENU/'usr/lib/dataflowInfraFramework.so', '620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47'),
 'M': (MENU/'usr/lib/libmpr.so', '4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9'),
 'F': (MENU/'usr/lib/libInfraFsys.so', '33451a884b65f946ac8aca44b620cd3cec677d05752c52f2ff0e212a01824bfa'),
 'K': (MENU/'system/av-cam.bin', '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'),
 'CP': (MENU/'cp/cpapp-b.bin', 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')}

def load(kind):
    p, expected = PINS[kind]
    b = p.read_bytes()
    sha = hashlib.sha256(b).hexdigest()
    if sha != expected: raise RuntimeError(f'pin mismatch {p}: {sha}')
    return p,b,sha

def fileoff(kind, addr, length):
    if kind == 'CP': return (addr & ~1)-0x108000
    if kind == 'K': return addr
    with PINS[kind][0].open('rb') as f:
        for s in ELFFile(f).iter_segments():
            if s['p_type']=='PT_LOAD' and s['p_vaddr']<=addr and addr+length<=s['p_vaddr']+s['p_filesz']:
                return s['p_offset']+addr-s['p_vaddr']
    raise ValueError(f'{kind} VA outside file-backed PT_LOAD: {addr:x}')

def window(kind, addr, n, mode='data'):
    p,b,sha = load(kind)
    if n <= 0: raise ValueError('window length must be positive')
    off = fileoff(kind,addr,n)
    if off<0 or off+n>len(b): raise ValueError('out of range')
    w=b[off:off+n]
    meta={'artifact':str(p.relative_to(ROOT)), 'sha256':sha,'address':hex(addr),'fileoff':hex(off),
          'length':n,'window_sha256':hashlib.sha256(w).hexdigest(),'bytes':w.hex(),'mode':mode}
    text=[json.dumps(meta,ensure_ascii=False)]
    if mode=='data':
        for i in range(0,n,16):text.append(f'{addr+i:08x} {w[i:i+16].hex(" ")}')
    else:
        engine=Cs(CS_ARCH_ARM if kind=='CP' else CS_ARCH_ARM64, CS_MODE_THUMB if mode=='thumb' else CS_MODE_ARM)
        for i in engine.disasm(w,addr & ~1):
            text.append(f'{i.address:08x} {i.bytes.hex():<10} {i.mnemonic:8} {i.op_str}')
    name=f'{kind}-{addr:x}-{n:x}-{mode}'
    (OUT/(name+'.json')).write_text(json.dumps(meta,indent=2)+'\n')
    (OUT/(name+'.txt')).write_text('\n'.join(text)+'\n')
    print('\n'.join(text))

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('op',choices=['pins','asm','data'])
    a.add_argument('kind',nargs='?',choices=list(PINS))
    a.add_argument('address',nargs='?',type=lambda s:int(s,0))
    a.add_argument('length',nargs='?',type=lambda s:int(s,0))
    a.add_argument('mode',nargs='?',default='arm',choices=['arm','thumb'])
    args=a.parse_args()
    if args.op=='pins':
        for k in PINS:
            p,b,h=load(k);print(k,p,len(b),h)
    else:window(args.kind,args.address,args.length,'data' if args.op=='data' else args.mode)
