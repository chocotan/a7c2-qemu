#!/usr/bin/env python3
"""Offline byte/corpus probe. Never executes firmware or opens a device.

python3 -B probe.py sha
python3 -B probe.py cp dis 357750:180 35ce2c:144
python3 -B probe.py ap corpus 351fdb8 3549330
All numeric arguments are hexadecimal. CP addresses are CPVA, AP addresses ELF VA.
"""
import hashlib
import importlib.util
from pathlib import Path
import struct
import sys

NATIVE = Path(__file__).resolve().parents[2]
ROOT = NATIVE
AP = NATIVE / 'runtime/analysis/menu-root/usr/lib/appFw.so'
CP = NATIVE / 'runtime/analysis/menu-root/cp/cpapp-b.bin'
PINS = {'ap': (AP, '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
        'cp': (CP, 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428')}


def load(kind):
    path, expected = PINS[kind]
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    print(f'{kind} path={path.relative_to(ROOT)} size={len(data)} sha256={digest}')
    if digest != expected:
        raise SystemExit('PIN MISMATCH')
    return data


def main():
    args = sys.argv[1:]
    if args == ['sha']:
        for kind in PINS:
            load(kind)
        return
    kind, op, *values = args
    data = load(kind)
    segments = []
    if kind == 'ap':
        phoff = struct.unpack_from('<Q', data, 32)[0]
        phsize, phnum = struct.unpack_from('<HH', data, 54)
        for i in range(phnum):
            p = struct.unpack_from('<IIQQQQQQ', data, phoff + phsize * i)
            if p[0] == 1:
                segments.append((p[3], p[2], p[5]))
        print('PT_LOAD (VA,fileoff,filesz)', [(hex(a), hex(b), hex(c)) for a,b,c in segments])
    else:
        segments = [(0x108000, 0, len(data))]

    def offset(a, n=1):
        for va, off, size in segments:
            if va <= a and a + n <= va + size:
                return off + a - va
        raise ValueError(f'not file backed: {a:x}+{n:x}')

    if op == 'corpus':
        if kind != 'ap':
            raise ValueError('corpus only supports AP')
        spec = importlib.util.spec_from_file_location('lens_corpus', NATIVE.parents[3] / 'analysis/appfw-decompile/corpus.py')
        corpus = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(corpus)
        for a in values:
            address = int(a,16)
            rows = [r for r in corpus.index() if r.get('size') and
                    int(r['addr'],16) <= address < int(r['addr'],16) + int(r['size'])]
            if not rows:
                print(f'NO CORPUS FUNCTION {a}')
                continue
            row = rows[-1]
            print(corpus.fmt_meta(row))
            print(corpus.function_block(row))
        return
    import capstone
    mode = capstone.CS_MODE_ARM if op == 'arm' else capstone.CS_MODE_THUMB
    cs = capstone.Cs(capstone.CS_ARCH_ARM64 if kind == 'ap' else capstone.CS_ARCH_ARM,
                     capstone.CS_MODE_LITTLE_ENDIAN if kind == 'ap' else mode)
    if op in ('dis', 'arm', 'bytes', 'words'):
        for value in values:
            a, _, length = value.partition(':')
            a, n = int(a,16) & ~1, int(length,16) if length else 0x100
            if not 0 < n <= 0x4000:
                raise ValueError('bounded extraction required')
            off = offset(a, n)
            block = data[off:off+n]
            print(f'WINDOW VA={a:x} raw={off:x} len={n:x} sha256={hashlib.sha256(block).hexdigest()}')
            if op in ('dis', 'arm'):
                for ins in cs.disasm(block,a):
                    print(f'{ins.address:08x} raw={offset(ins.address):08x} {ins.bytes.hex():10s} {ins.mnemonic:8s} {ins.op_str}')
            else:
                for j in range(0,n,16):
                    chunk = block[j:j+16]
                    text = chunk.hex(' ') if op == 'bytes' else ' '.join(f'{struct.unpack_from("<I",chunk,k)[0]:08x}' for k in range(0,len(chunk)-3,4))
                    print(f'{a+j:08x} raw={off+j:08x} {text}')
    elif op == 'word':
        for value in values:
            needle = struct.pack('<I',int(value,16))
            start = 0
            while True:
                pos = data.find(needle,start)
                if pos < 0:
                    break
                vas = [va + pos - off for va,off,n in segments if off <= pos < off+n]
                print(f'WORD {value} raw={pos:x} VAs={[hex(v) for v in vas]}')
                start = pos + 1
    elif op in ('bl','mov') and kind == 'cp':
        targets = {int(v,16) & ~1 if op == 'bl' else int(v,16) for v in values}
        for raw in range(0,len(data)-3,2):
            h,k = struct.unpack_from('<HH',data,raw)
            if op == 'mov':
                imm = ((h & 15)<<12) | (((h>>10)&1)<<11) | (((k>>12)&7)<<8) | (k&255)
                match = h & 0xfbf0 in (0xf240,0xf2c0) and not k & 0x8000 and imm in targets
            else:
                if h & 0xf800 != 0xf000 or k & 0xd000 not in (0x9000,0xd000):
                    continue
                s = h >> 10 & 1
                imm = (s<<24) | ((1 ^ (k>>13&1) ^ s)<<23) | ((1 ^ (k>>11&1) ^ s)<<22) | ((h&0x3ff)<<12) | ((k&0x7ff)<<1)
                if s:
                    imm -= 1 << 25
                match = raw + 0x108004 + imm in targets
            if match:
                for ins in cs.disasm(data[raw:raw+4],raw+0x108000):
                    print(f'{ins.address:08x} raw={raw:08x} {ins.bytes.hex()} {ins.mnemonic} {ins.op_str}')
    else:
        raise ValueError('unsupported operation')


if __name__ == '__main__':
    main()
