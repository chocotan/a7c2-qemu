#!/usr/bin/env python3
"""Read-only raw Image pins; writes evidence only beside this script."""
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
IMAGE = ROOT / ('runtime/analysis/'
                'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin')
BASE = 0xffffff8008080000
SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
PINS = {
    0x245c44: '3f100071', 0x245c54: '3f080071', 0x245c5c: '3f040071',
    0x245c64: 'f3108052', 0x245c68: '5f0000b9',
    0x245c84: 'df4203d5', 0x245c90: '010040b9', 0x245c94: '9f3d03d5',
    0x245ca0: '24421bd5', 0x245ca8: '410000b9', 0x245cac: '13008052',
    0x245d04: 'df4203d5', 0x245d10: '01004079', 0x245d18: '9f3d03d5',
    0x245d28: '24421bd5', 0x245d34: 'df4203d5', 0x245d40: '01004039',
    0x245d48: '9f3d03d5', 0x245d54: '24421bd5',
    0x245eac: '04ac40f9', 0x245eb0: '840440f9', 0x245eb4: 'a40000b4',
    0x245eb8: '80003fd6', 0x245ed4: '2040228b', 0x245edc: '1f0003ea',
    0x245ee4: 'bf2f00b9', 0x245ee8: '600240f9', 0x245f10: '4cffff97',
    0x245f28: '05ac40f9', 0x245f2c: 'a50840f9', 0x245f30: '850000b4',
    0x245f34: 'a0003fd6', 0x245f54: 'e040288b', 0x245f58: '9cffff97',
    0x245f64: 'c00040f9', 0x245dd0: '1f0003ea', 0x245dd8: 'e1108052',
    0x245de8: '3f100071', 0x245df0: '3f080071', 0x245df8: '3f040071',
    0x245e04: '9f3e03d5', 0x245e08: '02000039',
    0x245e18: '9f3e03d5', 0x245e1c: '020000b9',
    0x245e28: '9f3e03d5', 0x245e2c: '02000079',
    0x31deb0: '1f100071', 0x31deb4: 'e8000054',
    0x31dec0: '21a00491', 0x31dec4: '20d860b8', 0x31ded0: '00008012',
    0x22d298: 'd8180094', 0x233608: 'f40300aa', 0x23360c: 'f303012a',
    0x233624: '83a20d91', 0x233648: '9f0478f2',
    0x233668: 'a5000032', 0x233674: 'a5001f32',
    0x23367c: '3f2c0071', 0x2336d4: 'b3028012',
    0x233734: '82008052', 0x233740: '1ac5ff97',
}
RANGES = (
    ('raw_MMIO_read', 0x245c40, 0x245d60),
    ('DBI_read_dispatch', 0x245ea0, 0x245f20),
    ('DBI_write_dispatch', 0x245f20, 0x245f74),
    ('raw_MMIO_write', 0x245dc8, 0x245e38),
    ('domain_IRQ_getter', 0x31deb0, 0x31ded8),
    ('resource_enable_wrapper', 0x22d290, 0x22d2a4),
    ('resource_enable', 0x2335f8, 0x23375c),
)


def main():
    data = IMAGE.read_bytes()
    assert len(data) == 6610952 and hashlib.sha256(data).hexdigest() == SHA
    for address, raw in PINS.items():
        assert data[address:address + 4] == bytes.fromhex(raw), hex(address)
    assert struct.unpack_from('<5i', data, 0x640ff0) == (-1,) * 5
    for target in (0x245ea0, 0x245f20, 0x245dc8, 0x31deb0, 0x22d290, 0x2335f8):
        assert data.find(struct.pack('<Q', BASE + target), 0x570000, 0x590000) == -1
    exports = {}
    for name, record, string, target in (
        ('pci_fixup_irqs', 0x58a450, 0x59c569, 0x2430d8),
        ('pci_common_swizzle', 0x58a180, 0x59bcd5, 0x229ad8),
        ('of_irq_parse_and_map_pci', 0x589d30, 0x5a3539, 0x310c68),
    ):
        assert struct.unpack_from('<QQ', data, record) == (BASE + target, BASE + string)
        assert data[string:string + len(name) + 1] == name.encode() + b'\0'
        exports[name] = dict(record=hex(record), name=hex(string), target=hex(target))
    disassembler = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    bodies = []
    for name, lo, hi in RANGES:
        lines = [f'{i.address:06x} {i.bytes.hex()} {i.mnemonic} {i.op_str}'
                 for i in disassembler.disasm(data[lo:hi], lo)]
        bodies.append(dict(name=name, start=hex(lo), end_exclusive=hex(hi),
                           sha256=hashlib.sha256(data[lo:hi]).hexdigest(),
                           raw=data[lo:hi].hex(), assembly=lines))
    result = dict(status='PASS', gate='Local helper ABI pinned; runtime and complete Sony host/PHY remain unverified',
                  scope='Static pins only; bounded helper bodies, no kernel execution',
                  kernel_sha256=SHA, kernel_size=len(data), base=hex(BASE),
                  instruction_pins={hex(a): raw for a, raw in PINS.items()},
                  initial_domain_irq_values=[-1] * 5, irq_table='0x640ff0',
                  exports=exports, functions=bodies,
                  unexpanded_frontiers=['0x640ff0 IRQ table initialization writers',
                                        'Bodies and callback ABI of IRQ-related exports'])
    (OUT / 'quirk-context-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    (OUT / 'quirk-context-functions.asm').write_text('\n\n'.join(
        item['name'] + '\n' + '\n'.join(item['assembly']) for item in bodies) + '\n')
    print(f"PASS: {len(PINS)} instruction pins; {len(bodies)} bounded functions; local ABI only, no runtime claim")
    for item in bodies:
        print(item['name'], item['start'], item['end_exclusive'], item['sha256'])
        print('\n'.join(item['assembly'][-4:]))


if __name__ == '__main__':
    main()
