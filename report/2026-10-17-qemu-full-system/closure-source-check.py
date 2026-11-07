#!/usr/bin/env python3
"""Offline original-ELF pins. Partial source proof deliberately cannot enable P1."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import capstone
from elftools.elf.elffile import ELFFile

HERE=Path(__file__).resolve().parent
MEDIA_SHA='efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec'


def check(original):
    ORIGINAL=Path(original)
    raw=ORIGINAL.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=MEDIA_SHA:raise ValueError('Wrong original MediaCommon ELF')
    with ORIGINAL.open('rb') as f:
        elf=ELFFile(f)
        if elf['e_machine']!='EM_AARCH64':raise ValueError('Wrong original ISA')
        loads=[(s['p_vaddr'],s['p_offset'],s['p_filesz']) for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
        dyn=elf.get_section_by_name('.dynsym')
        symbols={s.name:(s['st_value'],s['st_size']) for s in dyn.iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
        rel={}
        for name in ('.rela.dyn','.rela.plt'):
            sec=elf.get_section_by_name(name);sy=elf.get_section(sec['sh_link'])
            for r in sec.iter_relocations():rel[r['r_offset']]=dict(symbol=sy.get_symbol(r['r_info_sym']).name,addend=r['r_addend'])
        text=elf.get_section_by_name('.text');textva=text['sh_addr'];textdata=text.data()
    md=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_LITTLE_ENDIAN)
    def window(va,n,label):
        for base,offset,size in loads:
            if base<=va and va+n<=base+size:
                off=offset+va-base;data=raw[off:off+n]
                return dict(label=label,va=hex(va),bytes=n,file_offset=off,sha256=hashlib.sha256(data).hexdigest(),raw=data.hex(),
                    asm=[f'{x.address:x}: {x.mnemonic} {x.op_str}' for x in md.disasm(data,va)])
        raise ValueError('Original window not file-backed')
    windows=[window(0x177c0,0x120,'initial callback population and backend dispatch'),
        window(0x178e0,0x5c,'post-open decorator call sites'),window(0x19374,316,'actual flush dispatcher'),
        window(0x21824,2376,'dummy backend callback overrides'),window(0x1ebc0,8,'original no-op flush'),
        window(0x1ebe0,24,'original default format error'),window(0x2e858,0x750,'perf decorators saved callback forwarding'),
        window(0x2ee68,316,'perf decorator installation'),window(0x17f40,1276,'open and devctrl construction'),
        window(0x28280,96,'name to device-info lookup'),window(0x27f3c,296,'module table initialization')]
    expected=['17840: adrp x0, #0x85000','17844: ldr x0, [x0, #0xed8]','17848: str x0, [x19, #0x6e8]']
    if any(x not in windows[0]['asm'] for x in expected):raise ValueError('Original initial flush assignment differs')
    if rel[0x85ed8]!={'symbol':'mcmn_drv_default_flush','addend':0}:raise ValueError('Original flush GOT relocation differs')
    if windows[4]['raw']!='00008052c0035fd6':raise ValueError('Original no-op flush differs')
    if '194a4: ldr x1, [x0, #0x6e8]' not in windows[2]['asm'] or '194a8: blr x1' not in windows[2]['asm']:raise ValueError('Original flush dispatch differs')
    if any('#0x6e8]' in x and ': str ' in x for x in windows[3]['asm']):raise ValueError('Dummy backend now replaces flush')
    if any('#0x6e8]' in x and ': str ' in x for x in windows[7]['asm']):raise ValueError('Perf installer now replaces flush')
    initial=[]
    asm=windows[0]['asm']
    for i,line in enumerate(asm):
        if ': str x0, [x19, #0x6' not in line and ': str x0, [x19, #0x7' not in line:continue
        if i<2 or ': ldr x0, [x0, #' not in asm[i-1]:continue
        got=0x85000+int(asm[i-1].split('#')[1].split(']')[0],16)
        name=rel.get(got,{}).get('symbol')
        initial.append(dict(store=line,got=hex(got),target=name,target_va=hex(symbols[name][0]) if name in symbols else None))
    direct_flush_stores=[f'{x.address:x}: {x.mnemonic} {x.op_str}' for x in md.disasm(textdata,textva)
        if x.mnemonic in ('str','stp') and '#0x6e8]' in x.op_str]
    remaining=[
        'Prove fixed p23 device-info/root-type5 table row through mod_getdevinfo 0x28280 -> open 0x17f40 -> indirect backend 0x178d8, including any table mutation.',
        'Post-open 0x17918/0x17930 may install decorators: perf save/forward is pinned, but all installer targets and every saved callback/indirect terminal for fixed p23 are not yet exhaustively closed.',
        'Exclude all mmap64 call sites for the actual p23 FD using the resolved dispatcher/decorator graph, or add exact caller mediation; whole-library import presence/absence is insufficient.',
        'Host disk fsync and post-write/readback durability remain separate actual-execution evidence; original default_flush zero is not durability.'
    ]
    return dict(schema='pmbp-fixed-p23-source-coverage-v2-partial',original=dict(path=str(ORIGINAL),bytes=len(raw),sha256=MEDIA_SHA),
        windows=windows,initial_callbacks=initial,initial_flush_assignment_complete=True,
        default_flush=dict(target='0x1ebc0',original_noop=True,return_value=0,durability_claim=False),
        default_format=dict(target='0x1ebe0',original_error='0x80000002',modified=False),
        dummy_flush_override=False,perf_flush_override=False,direct_flush_stores=direct_flush_stores,
        complete_p23_dispatcher=False,complete_decorator_closure=False,mmap_p23_excluded=False,
        source_coverage_complete=False,enable_allowed=False,remaining=remaining)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Supply the explicitly selected original MediaCommon ELF path')
    result=check(sys.argv[1])
    print(json.dumps({k:result[k] for k in ('schema','initial_flush_assignment_complete','source_coverage_complete','enable_allowed','remaining')},indent=2))
