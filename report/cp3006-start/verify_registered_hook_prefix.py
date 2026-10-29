#!/usr/bin/env python3
"""Read-only original-CP checks; prefix evidence only, no transfer claim."""
import hashlib
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1]/'runtime/analysis/menu-root/cp/cpapp-b.bin'
BASE = 0x108000
SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
WINDOWS = ((0x56a994, 0x56aa76), (0xbee174, 0xbee180),
           (0xbec28e, 0xbec2a0), (0xbec02a, 0xbec030))
PINS = {
    0xbee174: '0022', 0xbee176: '7cf50db4',
    0xbee17a: '0122', 0xbee17c: '7cf50ab4',
    0x56a99e: '0446', 0x56a9a2: '9246', 0x56a9a4: '0d46',
    0x56a9b2: '002d', 0x56a9bc: '81f267f4',
    0x56a9c0: 'b0f5801f', 0x56a9c4: '52d8', 0x56a9cc: 'a5f14009',
    0x56a9e4: '05f83f1c', 0x56a9ea: '01f8025b',
    0x56a9ee: '4a70', 0x56a9f2: '0a70',
    0x56a9f8: '05f8371c', 0x56a9fe: '01f8380d',
    0x56aa04: 'ca70', 0x56aa06: '8870',
    0x56aa0c: '05f8330c', 0x56aa12: '00f8344d',
    0x56aa16: 'c170', 0x56aa1a: '8170', 0x56aa1e: '81f204f3',
    0x56aa22: 'a5f13001', 0x56aa28: '01f8020b',
    0x56aa2c: '4a70', 0x56aa32: '0a70', 0x56aa34: '05f82f0c',
    0x56aa38: '0120', 0x56aa3c: '01f82c0d',
    0xbec290: '50f8080c', 0xbec294: '7047',
    0xbec02a: '50f80c0c', 0xbec02e: '7047',
}
EDGES = {0xbee176: ('b.w', 0x56a994), 0xbee17c: ('b.w', 0x56a994),
         0x56a9bc: ('bl', 0xbec28e), 0x56a9c4: ('bhi', 0x56aa6c),
         0x56aa1e: ('bl', 0xbec02a)}


def main():
    data = SOURCE.read_bytes()
    assert len(data) == 18090880 and hashlib.sha256(data).hexdigest() == SHA
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    decoder.detail = True
    instructions = {}
    for start, end in WINDOWS:
        raw = data[start-BASE:end-BASE]
        decoded = list(decoder.disasm(raw, start))
        assert sum(i.size for i in decoded) == end-start
        instructions.update((i.address, i) for i in decoded)
    for address, encoded in PINS.items():
        assert instructions[address].bytes.hex() == encoded, hex(address)
    for address, (mnemonic, target) in EDGES.items():
        instruction = instructions[address]
        assert instruction.mnemonic == mnemonic and instruction.operands[-1].imm == target, hex(address)
    print(f'PASS original CP SHA, {sum(b-a for a,b in WINDOWS)} bounded bytes, '
          f'{len(PINS)} instruction pins and {len(EDGES)} typed edges')
    print('PASS two hooks preserve r0/r1 and select r2=0/1; common prefix uses r1-40h')
    print('OBSERVED helper reads u32[r1-8], rejects >100000h; second helper reads u32[r1-ch]')
    print('UNRESOLVED caller arguments, extent-field semantics, source->04000000, transfer/completion')


if __name__ == '__main__':
    main()
