#!/usr/bin/env python3
"""Pin the native c8 accessor addresses; no catalogue naming or guest execution."""
import hashlib
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile

target = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root/usr/lib/appFw.so'
assert target.stat().st_size == 99960744
assert hashlib.sha256(target.read_bytes()).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
with target.open('rb') as stream:
    elf = ELFFile(stream)
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']

    def read_va(address, size):
        segment = next(s for s in loads if s['p_vaddr'] <= address
                       and address+size <= s['p_vaddr']+s['p_filesz'])
        stream.seek(segment['p_offset']+address-segment['p_vaddr'])
        return stream.read(size)

    row = struct.unpack('<6Q', read_va(0x5584c38+0xc8*0x30, 0x30))
    assert row == (0x27f43a4, 0x2765454, 0x2765478, 0x2765460, 0x2765484, 0x276546c)
    cases = [(row[1], 'load', 0x7e59c20), (row[2], 'store', 0x7e59c10),
             (row[3], 'store', 0x7e59c08), (row[4], 'load', 0x7e59c10),
             (row[5], 'load', 0x7e59c08)]
    for pc, operation, expected in cases:
        page_op, memory_op, ret = struct.unpack('<3I', read_va(pc, 12))
        assert page_op & 0x9f000000 == 0x90000000
        immediate = ((page_op >> 29) & 3) | (((page_op >> 5) & 0x7ffff) << 2)
        if immediate & (1 << 20):
            immediate -= 1 << 21
        page = (pc & ~0xfff)+(immediate << 12)
        assert ((memory_op >> 5) & 31) == (page_op & 31)
        assert memory_op & 31 == 0  # w0 input/output
        assert memory_op & 0xffc00000 == (0xb9400000 if operation == 'load' else 0xb9000000)
        address = page+(((memory_op >> 10) & 0xfff) << 2)
        assert address == expected and ret == 0xd65f03c0
        print(f'PASS native c8 {operation} {pc:x} -> {address:x}')
print('PASS: native c8 +28 and proven setter holder agree; +20 reads a different address')
