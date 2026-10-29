#!/usr/bin/env python3
"""Verify static lens pins on original files; stdlib only, no firmware execution."""
import hashlib
from pathlib import Path
import struct

def _find_base():
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / 'runtime/analysis/menu-root'
        if (candidate / 'usr/lib/appFw.so').exists():
            return candidate
    raise FileNotFoundError('runtime/analysis/menu-root with appFw.so not found above this script')
BASE = _find_base()
FILES = {
    'AP': ('usr/lib/appFw.so', 99960744, '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
    'CP': ('cp/cpapp-b.bin', 18090880, 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'),
    'OBJ': ('usr/lib/libObj.so', 2997608, 'c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc'),
}
IMAGES, LOADS = {}, {}
checks = 0


def check(ok, label):
    global checks
    if not ok:
        raise AssertionError(label)
    checks += 1


def get(kind, va, n):
    for base, raw, size in LOADS[kind]:
        if base <= va and va + n <= base + size:
            off = raw + va - base
            return IMAGES[kind][off:off+n]
    raise AssertionError(f'{kind} not file-backed: {va:x}+{n:x}')


def pin(kind, va, text):
    expected = bytes.fromhex(text)
    check(get(kind, va, len(expected)) == expected, f'{kind} byte pin {va:x}')


def window(kind, va, n, digest):
    check(hashlib.sha256(get(kind, va, n)).hexdigest() == digest, f'{kind} window {va:x}:{n:x}')


def mov_imm(va):
    a, b = struct.unpack('<HH', get('CP', va, 4))
    check(a & 0xfbf0 in (0xf240, 0xf2c0) and not b & 0x8000, f'Thumb MOVW/T {va:x}')
    return ((a & 15) << 12) | (((a >> 10) & 1) << 11) | (((b >> 12) & 7) << 8) | (b & 255)


def main():
    for kind, (rel, size, digest) in FILES.items():
        data = (BASE / rel).read_bytes()
        check(len(data) == size and hashlib.sha256(data).hexdigest() == digest, f'{kind} identity')
        IMAGES[kind] = data
        if kind == 'CP':
            LOADS[kind] = [(0x108000, 0, len(data))]
        else:
            check(data[:6] == b'\x7fELF\x02\x01', f'{kind} ELF64 LE')
            ph = struct.unpack_from('<Q', data, 32)[0]
            ent, count = struct.unpack_from('<HH', data, 54)
            LOADS[kind] = []
            for i in range(count):
                p = struct.unpack_from('<IIQQQQQQ', data, ph + ent*i)
                if p[0] == 1:
                    LOADS[kind].append((p[3], p[2], p[5]))
        print(f'PASS {kind} size={size} SHA256={digest}')

    # CP builds an immediate byte map; AP performs conditional branches.
    window('CP', 0xa494e4, 0x48, 'a21ca6ed19b5888dfc85d322b7fff69af000c3f8051535d0613714986df6aec6')
    window('AP', 0x351fdb8, 0xd0, '4fb7561962c302d178f007b212d8e6db9960d1fccb5b4740535136b0aa5caebd')
    pin('AP', 0x351fdd4, '00204039 1f040071 20050054 e0040034 1f100071 200a0054')
    pin('AP', 0x351fe7c, '40008052 600600b9')
    pin('AP', 0x351ff2c, '3f0400b9 d5ffff17')
    pin('CP', 0xa4950e, 'c000')
    pin('CP', 0xa49514, '21fa00f0 00e0 0420')
    mapping = mov_imm(0xa4950a) | mov_imm(0xa49510) << 16
    check(mapping == 0x00040100, 'CP immediate map')
    check(tuple((mapping >> (8*i)) & 255 for i in range(3)) == (0, 1, 4), 'CP API->wire map')
    print('PASS AP351fdb8 wire0/1/4 -> model2/1/0; CP immediate bytes=00 01 04 00')

    # Distinct identity lookup, not a three-valued state enum.
    window('CP', 0xa97838, 0xb6, '18d498024fc76d8006d48ff99ffb20ec293b7fd5ae0d3fc2519472ea3488df47')
    window('CP', 0xa99862, 0x1c0, 'a5278594b6345b7b49f7ba8697459693a37832624a550fefa10a35c65cc56aaa')
    pin('CP', 0xa97860, '90f86720 90f86830 8df80010 42ea0322')
    pin('CP', 0xa978ac, '02f030f8')
    pin('CP', 0xa99910, 'fff7a7bf')
    pin('CP', 0xa99886, 'b0eb153f 18bf cd08')
    pin('CP', 0xa998a0, '0130 1036 6128 f7dd')
    check(mov_imm(0xa9988e) | mov_imm(0xa99892) << 16 == 0x1107184, 'CP lookup base')
    window('CP', 0x1107184, 98*16, 'e5f0565712a2250799ebb35bcb4fea219d94d890772519ad5eb137cf881328e4')
    keys = [struct.unpack('<I', get('CP', 0x1107184+16*i, 4))[0] for i in range(98)]
    check(len(set(keys)) == 98 and keys[:3] == [0x9f6, 0x9f7, 0x9f8] and keys[-1] == 0x2f, '98 distinct lookup keys')
    print('PASS CP P+67 LEu16 -> normalized identity lookup; 98 distinct keys, not complete product-enum proof')

    # Actual formatter data flow and referenced formats establish mm / F-number units.
    window('CP', 0xa497fa, 0x72, 'e698a88c4a541c958b5a63ffdd89d9da3f7aa4aa471e6486ebca41092e9ddea3')
    pin('CP', 0xa9994e, '7078 b178 00f044f8 0546 f078 3179 00f03ff8')
    pin('CP', 0xa999b8, 'c4e90032 c4e90202 04f11000 46c0 e261')
    pin('CP', 0xa999fa, '4fea101c 4ff47a70 0909 1cfb00fc 6420 01eb8101 12fb00c0 1844 00eb410c 1ffa8cf0 7047')
    pin('CP', 0xa4981e, '6861 0198 a861 0298 e861 0398 2862 0498 6862 0598 a862 0698 e862 0798 2863')
    pin('AP', 0x3520a48, '801640b9 605e00b9 801e40b9 606200b9')
    window('CP', 0x40cbd8, 0x328, 'ffc8c6dfbcce1f9e4de3410df60dc568c469277ff7e85ae76fe94abe27b88c4d')
    pin('CP', 0x40cc84, '98f80100 98f80210 8cf2a7f6 0646 98f80300 98f80410 8cf2a0f6')
    pin('CP', 0x40cf14, '25642d25646d6d00 25646d6d00')
    pin('CP', 0x40cf30, '4625732d25730000 46257300')
    for source, target in ((0x40ccb4, 0x40cf14), (0x40ccbc, 0x40cf1c), (0x40cd6e, 0x40cf30)):
        ins = struct.unpack('<H', get('CP', source, 2))[0]
        check(ins & 0xf800 == 0xa000 and (ins >> 8) & 7 == 2 and
              ((source + 4) & ~3) + (ins & 255)*4 == target, f'formatter ADR {source:x}')
    print('PASS focal range pairs {mm*10,10} at L+14/+1c; aperture range pairs at +24/+2c; AP takes focal numerators')

    window('CP', 0x8d6cc6, 0xb0, 'b4f8833efa8e4eeb250b28c44180d0f4a152ff86c036dabcb6b8dc7155dbeae7')
    window('CP', 0x8d6d6e, 0x11a, '0a0faa57ef54638042ba99fb31bc5c1a22ec529b630afb4f3acfe75779182d76')
    window('CP', 0xa49898, 0x48, '45e2295c658c2c62e32bf0a1f9398935160645d0044b9025346b496219abf760')
    pin('CP', 0x61ed00, '0120a0e1 0010a0e3 ffffffea')  # ARM zero-fill wrapper
    pin('CP', 0xa498e4, '80b5 6f46 0f21 d5f70ae2 80bd')
    check(mov_imm(0x8d6d0e) | mov_imm(0x8d6d12) << 16 == 0x10faaec, 'state4 template pointer')
    pin('CP', 0x8d6d16, '85f88800 85f88d10')
    default = bytes.fromhex('''
        00000000000000000402010100020301
        00000000000000000a00000000000000
        0a000000000000000a00000000000000
        0a0000002d2d2d2d0000000000000000
        00000000000000000000000000000000
        00000000000000000000000000000000
        00000000000000000000000000000000
        00000000000001020001010000000000
        00000000000000010000000000000100
        00000000000000000000000000000000
    ''')
    check(get('CP', 0x10faaec, 0xa0) == default, 'byte-exact default template')
    check(get('CP', 0x10e2e80, 0xa0) == default, 'initial cache equals template')
    check(struct.unpack_from('<8I', default, 0x14) == (0, 10)*4 and default[0x34:0x39] == b'----\0', 'default rationals/name')
    print('PASS state4 template/cache a0B, four {0,10}, ----; +88/+8d dynamic; first8 bytes zero, not a complete wire frame')
    print(f'PASS {checks} static assertions; runtime/product meanings/current focal length NOT VERIFIED')


if __name__ == '__main__':
    main()
