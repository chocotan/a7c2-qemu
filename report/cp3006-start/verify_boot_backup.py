#!/usr/bin/env python3
"""Verify Backup boot-transfer bytes and a public-seed layout projection.

Read-only stdout evidence: never loads firmware, starts a VM, or creates a CP
image. The caller must explicitly supply the separately sourced decoded boot0.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile

from verify_public_seed import require, verify as verify_seed

ROOT = Path(__file__).resolve().parents[2] / 'runtime/analysis/menu-root'
BOOT0_SHA = '9ad6bc5822a1a22e600e20a3b7b1dc42ffbfc9f7f9d90f7f3717b994c24d5ccf'
NOR_SHA = '5887ce4e6ca5fe1acdf6b675457f70e9798c61686f1d62c95190158855c96b22'
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
BACKUP_SHA = '167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b'


def read_pinned(path, size, digest):
    with path.open('rb') as stream:
        data = stream.read(size + 1)
    require(len(data) == size and hashlib.sha256(data).hexdigest() == digest,
            'unsupported original asset: ' + path.name)
    return data


def pins(data, base, expected):
    for address, value in expected.items():
        raw = bytes.fromhex(value)
        require(data[address - base:address - base + len(raw)] == raw,
                f'original instruction mismatch at {address:#x}')


def reset_projection(record, repeat_count):
    """Compare reset destinations with the sources used by the pinned loader."""
    sections, properties, header_size, data_size = struct.unpack_from('<4I', record, 0x10)
    require(header_size + data_size == len(record), 'reset record length mismatch')
    table = 0x100 + sections * 6
    require(table + properties * 6 <= header_size, 'reset metadata outside header')
    compared = repeated = 0
    changed = []
    for section in range(sections):
        count, first = struct.unpack_from('<HI', record, 0x100 + section * 6)
        require(first + count <= properties, 'reset section outside property table')
        for index in range(count):
            attr, pointer = struct.unpack_from('<HI', record, table + (first + index) * 6)
            if pointer == 0xffffffff or not attr & 0x74:
                continue
            size, at = pointer >> 24, pointer & 0xffffff
            variable = size == 0
            maximum = size
            require(header_size <= at < len(record), 'reset pointer outside data')
            if size in (0, 255):
                prefix = 4 if variable else 2
                require(at + prefix <= len(record), 'truncated reset length')
                size = maximum = struct.unpack_from('<H', record, at)[0]
                if variable:
                    maximum = struct.unpack_from('<H', record, at + 2)[0]
                at += prefix
            copies = repeat_count if attr & 0x80 else 1
            require(copies > 0 and size <= maximum and size % copies == 0,
                    'unsupported reset repetition size')
            require(not (attr & 0x80 and variable), 'unsupported repeated variable item')
            one = size // copies
            require(at + maximum + one <= len(record), 'reset source outside data')
            source = record[at + maximum:at + maximum + one]
            if any(record[at + n * one:at + (n + 1) * one] != source for n in range(copies)):
                changed.append(f'{section:04x}{index:04x}')
            compared += 1
            repeated += bool(attr & 0x80)
    return {'compared_items': compared, 'repeated_items': repeated,
            'repeat_count': repeat_count, 'changed_keys': changed,
            'unchanged_by_reset': not changed}


def public_layout(seed_path):
    review = verify_seed(seed_path, keys=(0x00fa0006, 0x003e000c, 0x00510052, 0x00510053))
    data = read_pinned(seed_path, 2390264, review['sha256'])
    roots = review['records']
    addresses = []
    sizes = []
    for record in roots:
        item = record['keys']['00fa0006']
        require(item['present'] and item['bytes'] == 8, 'fa0006 is not u64')
        addresses.append(int.from_bytes(bytes.fromhex(item['data']), 'little'))
        sizes.append(sum(struct.unpack_from('<II', data, record['offset'] + 0x18)))
    first_span = (sizes[0] + 0xfff) & ~0xfff
    require(first_span == roots[1]['offset'], 'next record differs from original getter')
    # fe04cfe4 uses the root header's first u32 and the following record's size.
    second_target = ((addresses[1] & 0xffffffff00000000) |
                     (struct.unpack_from('<I', data)[0] + ((sizes[1] + 0xfff) & ~0xfff)))
    resets = []
    for record, size in zip(roots, sizes):
        repeat = record['keys']['003e000c']
        require(repeat['present'] and repeat['bytes'] == 1, 'reset repeat count is not u8')
        repeats = int.from_bytes(bytes.fromhex(repeat['data']), 'little') + 1
        reset = reset_projection(data[record['offset']:record['offset'] + size], repeats)
        reset['record_offset'] = hex(record['offset'])
        reset['version_values'] = [record['keys'][key]['data']
                                   for key in ('00510052', '00510053')]
        resets.append(reset)
    return {
        'seed_sha256': review['sha256'],
        'reset_projection': resets,
        'ap_root': hex(addresses[0]),
        'ap_next_record': hex(addresses[0] + first_span),
        'next_record_file_offset': hex(first_span),
        'root_data_bytes': sizes[0],
        'root_padded_span': first_span,
        'next_record_data_bytes': sizes[1],
        'pci_primary_target_before_context_bias': hex(addresses[1]),
        'pci_secondary_target_before_context_bias': hex(second_target),
        'raw_second_record_is_final_boot_content_verified': False,
    }


def verify(boot0_path, nor_path, root=ROOT):
    boot0 = read_pinned(boot0_path, 190464, BOOT0_SHA)
    nor = read_pinned(nor_path, 94176, NOR_SHA)
    cp = read_pinned(root / 'cp/cpapp-b.bin', 18090880, CP_SHA)
    module = (root / 'usr/kmod/backup.ko').read_bytes()
    require(hashlib.sha256(module).hexdigest() == BACKUP_SHA, 'unsupported backup.ko')
    elf = ELFFile(io.BytesIO(module))
    text = elf.get_section_by_name('.text').data()
    symbols = elf.get_section_by_name('.symtab')
    relocations = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
                   for r in elf.get_section_by_name('.rela.text').iter_relocations()}
    base = 0xfe040000
    require(boot0[:4] == b'EXBL', 'missing EXBL header')
    require(struct.unpack_from('<I', boot0, 0x68)[0] * 512 == 0x800 and
            struct.unpack_from('<I', boot0, 0x6c)[0] - 0x800 == base and
            struct.unpack_from('<II', boot0, 0x74) == (0x2e000, 0xfe049000),
            'boot0 address derivation changed')
    pins(boot0, base, {
        0xfe050638: '620a0094',                 # Trans Backup CP -> fe052fc0
        0xfe04ef10: 'e1030032e00314aa6ef6ff97', # Data_getAdrs(root,1)
        0xfe04ef20: '600e00f9',                # context+18 = next record
        0xfe04ef38: '681200f9',                # context+20 = next size
        0xfe04ef54: 'e00316aa681a00f969f6ff97', # root size; bind next
        0xfe04efb8: '487c6092',                # preserve next fa0006 high32
        0xfe04efd4: '620201f9681600f9',        # context+200/+28 targets
        0xfe04f1bc: 'e00314aad0f5ff97',         # restore original root binding
        0xfe04f128: '66310094',                 # register allocated copy, not BK4 write
        0xfe05b71c: '13580129141000b9150000f91f0c00f9',
        0xfe04c9c4: 'e8030032f75b01a9e80f00b9', # u32 scratch initialized before u8 copy
        0xfe04c9e8: '880e80521f00086ac0020054b73e001240033837',
        0xfe04ca18: 'e00313aade000094e10300aae00314aae20315aa86faff97',
        0xfe04ca98: 'e80f40b916050011f60f00b9', # repeat count = 003e000c + 1
        0xfe04cac8: 'f50ad61aa8de161b68000034', # exact division into repeated items
        0xfe04cb90: 'e00030370b000014a0002037090000146000283707000014c0001036',
        0xfe063af8: '030085010200850101008501000085010400850105008501040028000f002800'
                    '0d0028000a002800060028000b005d000c005d0011005d0012005d00',
        0xfe04cf98: '082443290801098b08fd3f91085574920801008b',
        0xfe04d01c: '092143290801090b1f050031a0010054090040b9',
        0xfe04d034: '08fd3f9108cd74920001098b',
        0xfe052fd8: '010041f9028c41a9',        # target +200, source/length +18/+20
        0xfe052ff0: '972c0094',
        0xfe052ff4: '08e28fd20802a0f20801c0f201210091',
        0xfe053010: '8f2c0094',                # publish u64 pointer first
        0xfe053014: '01e28fd20102a0f20101c0f2',
        0xfe05302c: '882c0094',                # publish BKUP before root transfer
        0xfe053030: '620a40f9618e42a9e00314aa842c0094',
        0xfe05e314: 'e82e40f9e0031f2ae20315aae30313aa0101168b10010094',
        0xfe05e374: '7d03009460fe0736',        # poll DMA done; not enqueue-only
        0xfe05e3f8: 'e82e40f9e10315aae20313aa0001168b0b050094',
        0xfe06024c: '0040019102158052e1031f2a86acff97', # initially clear BAR list
        0xfe05e5b0: '680240b9e98240f90a4d189b0805001149d900a9', # then store BAR base
        0xfe05f1a4: '8809805208e7be72080140b9', # write-direction status F738004C
        0xfe0612fc: '02bc70920000bb52e1030532e3030032e4031f2a',
    })
    for offset in (0x2a680, 0x2aac0):
        require(struct.unpack_from('<Q', boot0, offset)[0] == 0xfe050630 and
                boot0[offset + 16:offset + 32] == b'Trans Backup CP\0',
                'original boot sequence record changed')
    pins(nor, 0xfe049000, {
        0xfe052874: '08e28fd20802a0f20801c0f2', # 800107f10, not 807107f10
        0xfe052884: '4a688952aa0aaa72',         # BKUP
        0xfe052894: '080540f9',
        0xfe0528a0: '080800f9',                 # context+10 receives mailbox+8
        0xfe056fa0: 'c0008052401fa072',         # independent fa0006 lookup
        0xfe056fe4: 'e00313aaabd5ff97e00313aabad5ff97',
    })
    pins(cp, 0x108000, {
        0x55dcc2: '4ff0806000f069f9',          # primary04000000
        0x55dcde: '4ff0806000218bf276f7',      # probe secondary size, arg0
        0x55dcf0: '8bf2b8f700f08ef9',          # next address -> secondary binder
        0x55e218: 'c96902294ad003294dd1012047e0', # stage3 passes1, skips stage2 MOV0
        0x55e2b4: '00208bf272f401212162',      # stage2 clear/shared setter; normalize stage1
        0xbe9ba8: '4872',                      # primary header byte9
        0x55e3d0: '4ff480522846c0f01ae9',      # reply copy4096
        0x55e48e: '4ff48052012341ea004004a906f0b3fe', # reply alloc4096
    })
    pins(text, 0, {
        0x12c0: 'e0fe3f111f0000711bfc3f117bb3801a7b7f0c13',
        0x13b0: 'e06e0229',                    # +14 = computed block count
        0x168c: 'a10f4aa91705805233008052',    # opcode30:40B, one scalar
        0x2c08: '040080d2',                    # unlock stage0
        0x2c90: 'd7ffff17',                    # first status error still reaches DMA
        0x2c74: 'e0ffff17',                    # DMA error still reaches unlock
    })
    for address, name in {0x12ec: 'osal_valloc_msg_wait', 0x2bec: 'backupfile_get_cp_data',
                          0x70bc: 'pcidma_transfer_async', 0x7198: 'backupfile_cb_getcp'}.items():
        require(relocations.get(address) == name, f'relocation mismatch {address:#x}')
    layout = public_layout(root / 'seed-backup.bin')
    require((layout['ap_root'], layout['ap_next_record'],
             layout['pci_primary_target_before_context_bias'],
             layout['pci_secondary_target_before_context_bias']) ==
            ('0x404000000', '0x4040ed000', '0x804000000', '0x80415b000'),
            'public address projection mismatch')
    return {
        'scope': 'original-byte static verification and public seed projection only',
        'boot0_sha256': BOOT0_SHA, 'boot0_base': hex(base),
        'nor_sha256': NOR_SHA, 'cp_sha256': CP_SHA, 'backup_module_sha256': BACKUP_SHA,
        'layout': layout,
        'boot_transfer_order': ['next_record', 'mailbox_pointer_u64', 'BKUP_u32', 'root_record'],
        'mailbox_target_before_context_bias': '0x800107f10',
        'pci_transaction_address_rule': 'first_allocated_BAR_base + configured_target',
        'bar_base_runtime_value_verified': False,
        'BKUP_marker_proves_secondary_transfer': False,
        'cp_primary_virtual_address': '0x04000000',
        'cp_secondary_address_if_public_next_is_primary': '0x0415b000',
        'ap_first_request_bytes': 40, 'ap_first_request_word_14': (40 + 0xfff) >> 12,
        'cp_reply_allocation_and_copy_bytes': 4096,
        'backup_status_zero_alone_proves_dma': False,
        'boot0_executed': False, 'cp_address_alias_verified': False,
        'current_cp_initial_bytes_verified': False, 'dma_completed': False,
        'backup_sync_completed': False, 'camera_capture_verified': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--boot0', type=Path, required=True,
                        help='explicit decoded boot0 comparison asset; never copied into ALLLANG assets')
    parser.add_argument('--nor', type=Path, required=True, help='original loader_nor.bin')
    args = parser.parse_args()
    print(json.dumps(verify(args.boot0, args.nor), indent=2))
