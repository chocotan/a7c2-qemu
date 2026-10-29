#!/usr/bin/env python3
"""Offline, read-only original Image ABI pins. JSON goes to stdout only."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

BASE = 0xffffff8008080000
SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
DEFAULT_IMAGE = Path(__file__).resolve().parents[3] / (
    'runtime/analysis/'
    'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin')

# name: (original export record, original name string, original Image target)
EXPORTS = {
    'pci_scan_root_bus': (0x57fd10, 0x59b790, 0x229148),
    'pci_create_root_bus': (0x58a190, 0x59b7a2, 0x228448),
    'pci_scan_child_bus': (0x58a610, 0x59b7b6, 0x228dd8),
    'pci_add_resource': (0x57f730, 0x59b71b, 0x225ab0),
    'pci_add_resource_offset': (0x57f740, 0x59b72c, 0x225a10),
    'pci_free_resource_list': (0x57faa0, 0x59b704, 0x225ac8),
    'pci_bus_size_bridges': (0x57f850, 0x59c269, 0x235b10),
    'pci_bus_assign_resources': (0x57f7b0, 0x59c250, 0x235d38),
    'pci_bus_add_devices': (0x57f790, 0x59b694, 0x226250),
    'pci_stop_root_bus': (0x58a670, 0x59b8e8, 0x229620),
    'pci_remove_root_bus': (0x58a5a0, 0x59b8d4, 0x229688),
    'pci_bus_put': (0x57f7f0, 0x59b66f, 0x225c78),
    'pci_dev_get': (0x57f8f0, 0x59c04c, 0x22fe10),
    'pci_dev_put': (0x57f910, 0x59c040, 0x22fe40),
    'pci_find_bus': (0x57fa10, 0x59c125, 0x231180),
    'pci_get_domain_bus_and_slot': (0x57fad0, 0x59c0ea, 0x231350),
    'pcidma_connect': (0x57fe40, 0x5a02e7, 0x2a2230),
    'pcidma_transfer_async': (0x57fe50, 0x5a02f6, 0x2a20c8),
    'resource_list_create_entry': (0x580cd0, 0x58e8e0, 0x26320),
    'iomem_resource': (0x57ccc0, 0x58e9f7, 0x613d58),
    'ioport_resource': (0x57cd10, 0x58ea06, 0x613d98),
}

PINS = {
    0x225a1c: ('f40300aa', 'resource list argument x0 saved in x20'),
    0x225a20: ('f30301aa', 'resource argument x1 saved in x19'),
    0x225a30: ('f50302aa', 'offset argument x2 saved in x21'),
    0x225a34: ('3b02f897', 'call exported resource_list_create_entry'),
    0x225a38: ('000300b4', 'allocation failure branches to log, no status result'),
    0x225a3c: ('610e40f9', 'resource flags at +0x18'),
    0x225a40: ('8101f037', 'flag bit30 selects embedded 64-byte resource copy'),
    0x225a44: ('130800f9', 'entry res pointer at +0x10'),
    0x225a48: ('150c00f9', 'entry offset at +0x18'),
    0x225a4c: ('810640f9', 'list head prev at +8'),
    0x225a50: ('800600f9', 'append updates head prev'),
    0x225a54: ('140400a9', 'entry next=head and prev=old tail'),
    0x225a58: ('200000f9', 'old tail next=entry'),
    0x225a74: ('620e40a9', 'copy resource bytes 0x00..0x0f'),
    0x225a7c: ('620e41a9', 'copy resource bytes 0x10..0x1f'),
    0x225a84: ('620e42a9', 'copy resource bytes 0x20..0x2f'),
    0x225a8c: ('620e43a9', 'copy resource bytes 0x30..0x3f'),
    0x228454: ('fa0300aa', 'create parent x0 saved in x26'),
    0x228464: ('f40302aa', 'create ops x2 saved in x20'),
    0x22846c: ('f503012a', 'create bus number w1 saved in w21'),
    0x228474: ('f70303aa', 'create sysdata x3 saved in x23'),
    0x228478: ('f60304aa', 'create resource list x4 saved in x22'),
    0x228488: ('a47e4093', 'signed bus number widened for bus resource start'),
    0x22848c: ('e1031aaa', 'parent forwarded as x1 to domain helper'),
    0x228490: ('64820339', 'bus number byte at +0xe0'),
    0x228494: ('644200f9', 'bus-number resource start at +0x80'),
    0x228498: ('146000f9', 'bus ops pointer at +0xc0'),
    0x22849c: ('176800f9', 'bus sysdata pointer at +0xd0'),
    0x2284a0: ('7c1d0094', 'internal domain helper at Image+0x22fa90'),
    0x2284a4: ('60e600b9', 'domain result stored as 32-bit value at bus+0xe4'),
    0x2284ac: ('35230094', 'duplicate domain/bus checked by exported pci_find_bus'),
    0x2284e0: ('14030b91', 'host bridge owns window list at +0x2c0'),
    0x228500: ('004f01f9', 'host bridge release callback installed at +0x298'),
    0x228508: ('1a0300f9', 'host bridge device parent may be NULL'),
    0x22850c: ('135f01f9', 'host bridge bus pointer at +0x2b8'),
    0x228538: ('609200f9', 'bus host bridge device at +0x120'),
    0x2285a0: ('7a0e00b4', 'root creation logging separately handles NULL parent'),
    0x22865c: ('670440f9', 'window prev at +8'),
    0x22866c: ('c70400f9', 'unlink window from caller resource list'),
    0x228670: ('e60000f9', 'unlink previous next'),
    0x228674: ('860640f9', 'host bridge window-list tail'),
    0x228678: ('840600f9', 'append window to host bridge list'),
    0x22867c: ('741800a9', 'set moved window next and prev'),
    0x228680: ('c40000f9', 'set host bridge old tail next'),
    0x228684: ('7c6841a9', 'entry resource +0x10 and translation offset +0x18'),
    0x228688: ('840f40f9', 'resource flags consumed at +0x18'),
    0x22868c: ('64fb6737', 'resource flag bit12 selects bus-number resource path'),
    0x229068: ('860040f9', 'scan requires a valid non-NULL list head x4'),
    0x229084: ('c10840f9', 'scan reads entry resource at +0x10'),
    0x229088: ('210c40f9', 'scan reads resource flags at +0x18'),
    0x2290b8: ('e4fcff97', 'scan delegate calls exported create_root_bus internally'),
    0x2290d4: ('756600f9', 'bus MSI pointer at +0xc8 set from wrapper x5=0'),
    0x2290e4: ('e21f8052', 'default bus-number upper bound 255'),
    0x2290f0: ('3affff97', 'scan delegate calls exported pci_scan_child_bus'),
    0x229118: ('e103142a', 'caller-supplied bus resource path retains bus number'),
    0x22911c: ('cbfcff97', 'bus-resource path calls create_root_bus'),
    0x22912c: ('2bffff97', 'bus-resource path scans child bus'),
    0x22914c: ('050080d2', 'public scan wrapper sets optional x5 to NULL'),
    0x229154: ('c3ffff97', 'public wrapper delegates to unexported Image+0x229060'),
    0x22fa9c: ('210300b4', 'NULL parent branches around parent dereference'),
    0x22faa0: ('201c41f9', 'non-NULL parent OF node at +0x238'),
    0x22fb04: ('01000591', 'domain-global base Image+0x627140'),
    0x22fb08: ('210c41b9', 'domain mode read at base+0x10c = 0x62724c'),
    0x22fb0c: ('3f040071', 'DT-assigned mode compared with 1'),
    0x22fb10: ('00feff54', 'mixed DT mode takes failure/log path'),
    0x22fb18: ('21200491', 'domain counter at base+0x108 = 0x627248'),
    0x22fb1c: ('3f0400b9', 'automatic mode set to zero'),
    0x22fb24: ('207c5f88', 'atomic counter load'),
    0x22fb28: ('00040011', 'increment counter, return allocated domain'),
    0x22fb2c: ('20fc0288', 'atomic counter store'),
    0x229688: ('010840f9', 'remove root checks bus parent at +0x10'),
    0x22968c: ('610000b4', 'only actual root enters removal'),
    0x2296b4: ('969240f9', 'remove retains host bridge from bus+0x120'),
    0x2296e4: ('df5e01f9', 'remove clears host bridge bus at +0x2b8'),
    0x2296ec: ('094a0194', 'remove invokes device-release path internally'),
}

WINDOWS = (
    ('pci_add_resource_offset', 0x225a10, 0x225ab0),
    ('pci_create_root_bus', 0x228448, 0x228788),
    ('pci_scan_root_bus', 0x229148, 0x229160),
    ('internal_scan_delegate', 0x229060, 0x229148),
    ('internal_domain_helper', 0x22fa90, 0x22fb60),
    ('pci_remove_root_bus', 0x229688, 0x229700),
)


def exact_exports(image, name):
    records = []
    needle = name.encode('ascii') + b'\0'
    start = 0
    while True:
        string = image.find(needle, start)
        if string < 0:
            return records
        start = string + 1
        if string and image[string - 1] != 0:
            continue
        pointer = struct.pack('<Q', BASE + string)
        position = 0
        while True:
            ref = image.find(pointer, position)
            if ref < 0:
                break
            position = ref + 1
            if 0x570000 <= ref < 0x590000:
                target = struct.unpack_from('<Q', image, ref - 8)[0] - BASE
                records.append((ref - 8, string, target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, default=DEFAULT_IMAGE)
    args = parser.parse_args()
    image = args.kernel.read_bytes()
    assert len(image) == 6610952
    assert hashlib.sha256(image).hexdigest() == SHA
    for name, expected in EXPORTS.items():
        assert exact_exports(image, name) == [expected], name
        record, string, target = expected
        assert struct.unpack_from('<QQ', image, record) == (BASE + target, BASE + string)
    for address, (raw, meaning) in PINS.items():
        assert image[address:address + 4] == bytes.fromhex(raw), (hex(address), meaning)
    assert struct.unpack_from('<ii', image, 0x627248) == (-1, -1)
    assert struct.unpack_from('<5Q', image, 0x628588) == (
        0, 0, 0, BASE + 0x2476a8, BASE + 0x247518)
    resources = {}
    for name, offset, end, flags, label in (
        ('iomem_resource', 0x613d58, 0xffffffffffffffff, 0x200, b'PCI mem\0'),
        ('ioport_resource', 0x613d98, 0xffffff, 0x100, b'PCI IO\0'),
    ):
        values = struct.unpack_from('<8Q', image, offset)
        assert values[0:2] == (0, end) and values[3:] == (flags, 0, 0, 0, 0)
        string = values[2] - BASE
        assert image[string:string + len(label)] == label
        resources[name] = {'offset': hex(offset), 'u64_fields': [hex(x) for x in values]}
    # Direct-target identity check: this address must never be advertised as an export.
    target = struct.pack('<Q', BASE + 0x229060)
    assert image.find(target, 0x570000, 0x590000) == -1
    extras = {}
    for name in ('pci_find_host_bridge', 'pci_set_host_bridge_release',
                 'pci_lock_rescan_remove', 'pci_unlock_rescan_remove', 'pci_bus_get'):
        extras[name] = [[hex(x) for x in entry] for entry in exact_exports(image, name)]
    result = {
        'status': 'PASS', 'kind': 'static original Image ABI pins only',
        'kernel_size': len(image), 'kernel_sha256': SHA, 'base': hex(BASE),
        'export_count': len(EXPORTS), 'instruction_pin_count': len(PINS),
        'exports': {name: {'record': hex(r), 'name': hex(n), 'target': hex(t)}
                    for name, (r, n, t) in EXPORTS.items()},
        'pins': {hex(a): {'bytes': raw, 'meaning': meaning}
                 for a, (raw, meaning) in PINS.items()},
        'windows': [{'name': name, 'start': hex(lo), 'end': hex(hi),
                     'sha256': hashlib.sha256(image[lo:hi]).hexdigest()}
                    for name, lo, hi in WINDOWS],
        'initial_domain_counter': -1, 'initial_domain_mode': -1,
        'pci_ops_table': ['0x0', '0x0', '0x0', hex(BASE + 0x2476a8), hex(BASE + 0x247518)],
        'resources': resources, 'additional_lifetime_export_records': extras,
        'remaining_gates': [
            'No runtime/module loading, callback invocation or live domain state check.',
            'Stop-root, host-release callback and synchronization bodies were not expanded.',
            'Resource tail fields +0x20..+0x3f are zeroed opaque storage; their individual labels are not recovered.',
            'No complete host-bridge deferred-release/module-unload proof.',
            'Export class, license and module-version CRC compatibility not established here.',
            'No claim that every internal platform hook accepts arbitrary own sysdata.',
        ],
    }
    # The callback functions are existing task-provided identities, not new target discovery.
    # Print short raw prologues as supplemental evidence for the fifth argument's representation.
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    except ImportError:
        result['existing_callback_prologues'] = 'Capstone unavailable; raw core pins still checked'
    else:
        cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        result['existing_callback_prologues'] = {
            label: [f'{i.address:#x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}'
                    for i in cs.disasm(image[start:start + 0x50], start)]
            for label, start in (('table_read', 0x2476a8), ('table_write', 0x247518))
        }
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
