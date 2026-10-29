"""Original CP DMM handle routing, generation and bounded provenance; no VM."""
from pathlib import Path
import hashlib
import os
import subprocess
import struct

import pytest

HERE=Path(__file__).resolve().parent


def test_native_cp_handle_and_generation_under_sanitizers(tmp_path):
    binary=tmp_path/'dmm'
    built=subprocess.run([
        'cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-g',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',
        '-DDMM_SERVICE_SELFTEST',str(HERE/'dmm-service.c'),'-o',str(binary),
    ],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode==0,result.stdout+result.stderr
    assert 'DMM_SERVICE_SELFTEST_PASS' in result.stdout
    assert 'DMM_PROVENANCE_SELFTEST_PASS' in result.stdout


def test_original_cp_marker_and_ap_route_byte_pins():
    ap=HERE/'menu-root/usr/lib/appFw.so'
    cp=HERE/'menu-root/cp/cpapp-b.bin'
    if not ap.is_file() or not cp.is_file():pytest.skip('Original public ALLLANG assets not prepared')
    from elftools.elf.elffile import ELFFile
    with ap.open('rb') as source:
        assert hashlib.file_digest(source,'sha256').hexdigest()=='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
        source.seek(0);elf=ELFFile(source)
        segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
        for address,expected in {
            0x35523d8:'94078052',0x35523e0:'340ca072',
            0x35523e4:'80078052',0x35523e8:'bf0271f2',0x35523ec:'200cb272',
            0x35523f4:'9402801a',0x3552470:'150800b9',
            0x35523a4:'a00e40b9',0x35523a8:'600600b9',
        }.items():
            segment=next(s for s in segments if s['p_vaddr']<=address<s['p_vaddr']+s['p_filesz'])
            source.seek(segment['p_offset']+address-segment['p_vaddr'])
            raw=bytes.fromhex(expected);assert source.read(len(raw))==raw,hex(address)
        for return_pc,target in ((0x35527b4,0x35521a0),(0x34d3614,0x3552790),(0x17b2c08,0x34d35e8)):
            address=return_pc-4
            segment=next(s for s in segments if s['p_vaddr']<=address<s['p_vaddr']+s['p_filesz'])
            source.seek(segment['p_offset']+address-segment['p_vaddr'])
            instruction=struct.unpack('<I',source.read(4))[0]
            assert instruction&0xfc000000==0x94000000,hex(address)
            displacement=(instruction&0x03ffffff)<<2
            if displacement&(1<<27):displacement-=1<<28
            assert address+displacement==target,hex(return_pc)
    data=cp.read_bytes()
    assert hashlib.sha256(data).hexdigest()=='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    for address,expected in {
        0xc1e50c:'6ff39f20',0xc1e51e:'40f40040',0xc1e526:'03f01f00',
        0xc1e52e:'22f4f842',0xc1e532:'42ea8020',0xc1e53a:'37f81e6c',
        0xc1e4aa:'c9f80060',0xc1ea90:'c0f38420',
    }.items():
        raw=bytes.fromhex(expected)
        assert data[address-0x108000:address-0x108000+len(raw)]==raw,hex(address)
