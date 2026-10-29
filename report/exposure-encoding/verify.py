#!/usr/bin/env python3
"""Read-only ALLLANG 2.01 exposure byte checks; no device or snapshot creation."""
import hashlib
from pathlib import Path
import struct

N = Path(__file__).resolve().parents[2] / 'runtime/analysis'
ASSETS = {
    'ap': ('menu-root/usr/lib/appFw.so', '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
    'cp': ('menu-root/cp/cpapp-b.bin', 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'),
}


def main():
    blobs = {}
    for name, (relative, digest) in ASSETS.items():
        data = (N / relative).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name + ': identity mismatch'
        blobs[name] = data
    ap = blobs['ap']
    assert ap[:6] == b'\x7fELF\x02\x01'
    phoff = struct.unpack_from('<Q', ap, 32)[0]
    size, count = struct.unpack_from('<HH', ap, 54)
    assert size == 56 and 0 < count <= 64
    segments = [struct.unpack_from('<IIQQQQQQ', ap, phoff + i * size) for i in range(count)]

    def at(image, va, length):
        if image == 'cp':
            offset = va - 0x108000
        else:
            matches = [offset + va - address for kind, _, offset, address, _, filesz, _, _ in segments
                       if kind == 1 and address <= va and va + length <= address + filesz]
            assert len(matches) == 1, ('file-backed AP VA', hex(va))
            offset = matches[0]
        data = blobs[image]
        assert 0 <= offset and offset + length <= len(data)
        return data[offset:offset + length]

    def exact(image, va, hex_bytes):
        expected = bytes.fromhex(hex_bytes)
        assert at(image, va, len(expected)) == expected, (image, hex(va))

    # F4: original formatter scale AND normative candidate tables.
    exact('ap', 0x23dc2cc, '80424179')
    exact('ap', 0x23dc2e4, '970c8052')
    exact('ap', 0x23dc2fc, '140bd71a')
    assert struct.unpack('<H', at('ap', 0x5eedd6a, 2))[0] == 400
    assert struct.unpack('<H', at('ap', 0x5eeddba, 2))[0] == 400

    # Shutter: (numerator, denominator) maps to enum37 in this particular domain.
    exact('ap', 0x4c7da1c, '010000007d00000025000000')
    exact('ap', 0x352a098, '050840b9')
    exact('ap', 0x352a0b4, '67c05f7806184079')
    exact('ap', 0x352a0d0, '400840b9200400b9')
    exact('ap', 0x35190d0, '00104079')
    exact('ap', 0x35190e4, '810e40b9')
    exact('ap', 0x23aa34c, 'f40ad41a148800b9')
    exact('cp', 0x8d5c90, '0281b1f8dc204281d1f8e020c260')

    # ISO: distinct CP and AP encodings, including the conditional conversion.
    exact('ap', 0x41b0918, '0500000064000000')
    exact('ap', 0x3521314, '821c0051')
    displacement = struct.unpack('<b', at('ap', 0x4c7cda4 + 11 - 7, 1))[0]
    assert 0x3521338 + displacement * 4 == 0x3521364
    exact('ap', 0x3521364, 'a0008052')
    displacement = struct.unpack('<h', at('ap', 0x4b604c4 + 5 * 2, 2))[0]
    assert 0x2d4bf3c + displacement * 4 == 0x2d4bf5c
    exact('ap', 0x2d4bf5c, '800c8052')
    exact('ap', 0x3549688, 'a0774d3980000035a0734d39614215911e5fff97')
    exact('cp', 0x8d6980, '91f81321')
    exact('cp', 0x8d69a4, '027291f81411417290e80e000c200ec4')
    exact('cp', 0xb2ebe6, '42f6501202440a61')
    assert struct.unpack('<III', at('cp', 0xd93660 + 10 * 12, 12)) == (0x200e, 0x8d590b, 0)
    assert struct.unpack('<III', at('cp', 0xd93660 + 29 * 12, 12)) == (0x2036, 0x8d68d3, 0)
    print('PASS: original identities/bytes; F4=400; shutter=1/125; ISO CP0b->AP5->100')
    print('Static evidence only: no snapshot produced, runtime state supplied, or exposure completed.')


if __name__ == '__main__':
    main()
