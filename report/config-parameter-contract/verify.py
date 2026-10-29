#!/usr/bin/env python3
"""Verify original language/date Backup identifiers via ELF load mapping."""
import argparse
import hashlib
import json
from pathlib import Path
from elftools.elf.elffile import ELFFile

SHA='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap',type=Path,required=True);args=parser.parse_args()
    with args.ap.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=SHA:raise ValueError('Original AP SHA differs')
        stream.seek(0);elf=ELFFile(stream)

        def read(va,n):
            for segment in elf.iter_segments():
                if (segment['p_type']=='PT_LOAD' and segment['p_vaddr']<=va
                        and va+n<=segment['p_vaddr']+segment['p_filesz']):
                    stream.seek(segment['p_offset']+va-segment['p_vaddr']);return stream.read(n)
            raise ValueError('Unbacked ELF VA')

        for va,hx in {
            0x35ab654:'22008052',
            0x35ab668:'20808052e059a072',
            0x35ab674:'ffca8297',
            0x35ab440:'22008052',
            0x35ab458:'608080523ffc1f38e059a07283cb8297',
            0x35ab590:'61808052e159a072e059805269cd8297',
            0x35ab6d4:'21808052e159a072e059805218cd8297',
            0x165e270:'102b02f011a244f91002259120021fd6',
            0x165eb40:'102b02f011d646f910a2369120021fd6',
        }.items():
            if read(va,len(bytes.fromhex(hx)))!=bytes.fromhex(hx):
                raise ValueError(f'Original instruction mismatch {va:#x}')
        # Decode the AArch64 PLT ADRP/LDR to bind the actual GOT relocation.
        import struct
        def plt_got(va):
            adrp,ldr=struct.unpack('<II',read(va,8))
            if adrp&0x9f00001f!=0x90000010 or ldr&0xffc003ff!=0xf9400211:
                raise ValueError('Unexpected PLT instruction pair')
            imm=(((adrp>>5)&0x7ffff)<<2)|((adrp>>29)&3)
            if imm&(1<<20):imm-=1<<21
            return (va&~0xfff)+(imm<<12)+(((ldr>>10)&0xfff)*8)
        read_got=plt_got(0x165e270);write_got=plt_got(0x165eb40)
        relocations=elf.get_section_by_name('.rela.plt');symbols=elf.get_section(relocations['sh_link'])
        bound={r['r_offset']:symbols.get_symbol(r['r_info_sym']).name for r in relocations.iter_relocations()}
        if bound.get(read_got)!='Backup_nread' or bound.get(write_got)!='Backup_write':
            raise ValueError('Original Backup PLT relocation differs')
        print(json.dumps({'static_parameters_verified':True,'ap_sha256':SHA,
            'sid':'0x02cf','language':{'id':'0x02cf0401','bytes':1,'get':'0x35ab650','set':'0x35ab690'},
            'date_format':{'id':'0x02cf0403','bytes':1,'get':'0x35ab43c','set':'0x35ab54c'},
            'get_got':hex(read_got),'set_got':hex(write_got),
            'menu_changes_observed':False,'saved_file_verified':False,
            'configuration_persistence_verified':False},indent=2))


if __name__=='__main__':main()
