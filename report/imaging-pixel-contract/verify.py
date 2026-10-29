#!/usr/bin/env python3
"""Read-only re-check of the pixel-input field contract (no firmware executed).

Each assertion is an original byte or original table fact that a virtual imager
would have to respect. Passing proves nothing about real capture: the component
byte order, plane layout, freshness and lease lifetime remain unproven.

Usage: python3 verify.py
"""
import hashlib
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1] / 'runtime/analysis/menu-root'
K = ROOT/'system/av-cam.bin'
D = ROOT/'usr/lib/dataflowInfraFramework.so'
A = ROOT/'usr/lib/appFw.so'
K_SHA = '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
D_SHA = '620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47'
A_SHA = '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'


def checks():
    for path, expected, label in ((K, K_SHA, 'av-cam.bin'), (D, D_SHA, 'dataflowInfraFramework.so'),
                                  (A, A_SHA, 'appFw.so')):
        if not path.is_file():
            raise SystemExit(f'missing artifact: {path}')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f'{label} mismatch: {actual}')
        yield f'{label} sha256 {expected}'


def main():
    out = list(checks())
    k = K.read_bytes()

    # The capacity formula multiplies the pixel area by 2 only when YcCompress==0.
    window = k[0x3dda0:0x3dde0]
    if bytes.fromhex('69be4039') not in window:
        raise ValueError('YcCompress load (ldrb w9,[x19,#0x2f]) not found')
    if bytes.fromhex('e8179f1a') not in window or bytes.fromhex('6a7d0a1b') not in window:
        raise ValueError('area multiply / conditional shift not found')
    out.append('K 0x3dda8: capacity uses YcCompress (0x2f), not bit depth')

    # Unsigned "capacity - offset >= required" comparison pair.
    if bytes.fromhex('0901046b62020054') not in k[0x3dc60:0x3dc80]:
        raise ValueError('first unsigned range check differs')
    if bytes.fromhex('3f01146b62030054') not in k[0x3dcb0:0x3dcd0]:
        raise ValueError('second unsigned range check differs')
    out.append('K 0x3dc70/0x3dcc0: unsigned remaining>=required checks')

    # DataSite -> driver parameter table is not a pixel-format enum.
    table = struct.unpack('<6I', k[0x30b400:0x30b418])
    if table != (0, 0, 1, 2, 2, 3):
        raise ValueError(f'DataSite table differs: {table}')
    out.append(f'K 0x30b400 DataSite table = {table} (driver parameter, not pixel format)')

    # Named codec enums exist, but in their own domain.
    def kva_name(offset):
        return k[offset:k.index(b'\0', offset)].decode('ascii', 'replace')
    chroma = [struct.unpack('<Q', k[0x32f8c0+i*8:0x32f8c0+i*8+8])[0] for i in range(4)]
    depth = [struct.unpack('<Q', k[0x32f8e0+i*8:0x32f8e0+i*8+8])[0] for i in range(3)]
    if [hex(v) for v in chroma] != ['0xffffffc001447078', '0xffffffc001447083',
                                    '0xffffffc00144708e', '0xffffffc001447099']:
        raise ValueError('chroma enum table differs')
    if [hex(v) for v in depth] != ['0xffffffc0014470a8', '0xffffffc0014470b4',
                                   '0xffffffc0014470c1']:
        raise ValueError('bit-depth enum table differs')
    names = (kva_name(0x447078), kva_name(0x447083), kva_name(0x44708e),
             kva_name(0x4470a8), kva_name(0x4470b4))
    if names != ('CHROMA_420', 'CHROMA_422', 'CHROMA_444', 'BIT_DEPTH_8', 'BIT_DEPTH_10'):
        raise ValueError(f'codec names differ: {names}')
    out.append('K 0x32f8c0/0x32f8e0 name CHROMA_420/422/444 and BIT_DEPTH_8/10 '
               '(separate codec domain; not bound to YC fields)')

    print('\n'.join('PASS '+line for line in out))
    print('CAPTURE_VERIFIED false — no pixel frame produced; 0x20/0x21/0x23/0x24 '
          'enumerations and freshness/lease remain unproven')
    return 0


if __name__ == '__main__':
    sys.exit(main())
