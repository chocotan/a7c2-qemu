#!/usr/bin/env python3
"""Check original MPR/Fsys write-request pins. This does not execute capture."""
import struct

from probe import fileoff, load


def main():
    pins = {
        'M': {
            0xeb620: 0x97fe42bc,   # RecordStill -> _record_still PLT
            0xf186c: 0x9105a3b4,  # request = x29+0x168
            0xf1e7c: 0xd280a102,  # clear request bytes=0x508
            0xf1fe8: 0xf90333a0,  # callback -> request+0x4f8
            0xf1ffc: 0xf90337b6,  # cookie -> request+0x500
            0xf20ec: 0x97fe3fc9,  # Fsys_WriteDirectFileAsyncV2 PLT
            0xe8240: 0x97fe572c,  # original completion -> write_finished thread
        },
        'F': {
            0x32fb0: 0xd280a104,  # async request length=0x508
            0x2f82c: 0xf9427e60,  # request+0x4f8 callback
            0x2f840: 0xf9428260,  # request+0x500 cookie
            0x2f910: 0xb944f260,  # request+0x4f0 area count
            0x2d220: 0xf9406a63,  # copied callback context+0xd0
            0x2d228: 0xf9406e60,  # cookie as callback x0
            0x2d22c: 0x91039262,  # original result as callback x2
            0x2d230: 0x2a1403e1,  # actual status as callback w1
            0x2d234: 0xd63f0060,  # original callback, not a simulated ACK
        },
    }
    for kind, expected in pins.items():
        _, raw, sha = load(kind)
        for address, word in expected.items():
            actual = struct.unpack_from('<I', raw, fileoff(kind, address, 4))[0]
            if actual != word:
                raise ValueError(f'{kind}+{address:#x} instruction differs: {actual:#x}')
        print(f'PASS {kind} sha256={sha} instruction_pins={len(expected)}')
        if kind == 'M':
            for address in (0x2c8cd8, 0x2c8ce0, 0x2c8ce8, 0x2c8cf0, 0x2c8d00, 0x2c8d08):
                offset = fileoff(kind, address, 8)
                if struct.unpack_from('<2I', raw, offset) != (0x52800000, 0xd65f03c0):
                    raise ValueError('MprIf no-op interface bytes differ')
            print('PASS MprIf compatibility APIs are no-ops; do not use return0 as a write proof')
    print('CAPTURE_VERIFIED false; payload leases, actual writes and final files require runtime evidence')


if __name__ == '__main__':
    main()
