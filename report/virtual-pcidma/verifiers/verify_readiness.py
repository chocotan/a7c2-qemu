#!/usr/bin/env python3
"""Offline original-Image pins; --capture writes excluded local evidence only."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import capstone
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[2]
KERNEL = WORK / 'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
BASE = 0xffffff8008080000
EXPECTED_SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'

# Function bodies or explicitly bounded xref excerpts, never whole-Image decode.
WINDOWS = {
    'run_gate_carry': (0x2a1ff0, 0x2a2014),
    'connected_clear_xref': (0x2a1e38, 0x2a1e80),
    'submission_xrefs': (0x2a2180, 0x2a21fc),
    'connect_xrefs': (0x2a22d8, 0x2a233c),
    'teardown_reset_xref': (0x2a24c4, 0x2a250c),
    'link_predicate': (0x2a3098, 0x2a3174),
    'wake_producer': (0x2a3178, 0x2a31d0),
    'worker_wait': (0x2a31d0, 0x2a32b4),
    'worker_hardware_poll': (0x2a32b4, 0x2a3354),
    'worker_ready_publish': (0x2a3354, 0x2a33e8),
    'worker_release': (0x2a3400, 0x2a34d8),
    'worker_timeout_end': (0x2a36b4, 0x2a36fc + 4),
    'request_count_producer': (0x2a3718, 0x2a37cc),
    'retire_carry_expanded_field_alias': (0x2a37d0, 0x2a38f0),
    'initial_ready_producer': (0x2a38f0, 0x2a3914),
    'pci_release_guard': (0x2a3918, 0x2a3974),
    'connect_resume': (0x2a39b8, 0x2a3a2c),
    'policy3_conditional_init_carry': (0x2a3a50, 0x2a3b38),
    'channel_init_carry': (0x5cbdc8, 0x5cbe00),
    'connection_callback_pointer_carry': (0x5cbea4, 0x5cbeb0),
}

PINS = [
    (0x2a2000, 'ldr w1, [x0, #0x14]'),
    (0x2a2004, 'cbz w1, #0x2a1ff8'),
    (0x2a2008, 'ldr w1, [x0, #0x18]'),
    (0x2a200c, 'cbz w1, #0x2a1ff8'),
    (0x2a2198, 'bl #0x2a3718'),
    (0x2a21f8, 'bl #0x2a1ff0'),
    (0x2a22e4, 'bl #0x2a39b8'),
    (0x2a2318, 'str w26, [x19, #0x14]'),
    (0x2a24e0, 'mov x0, x19'),
    (0x2a24e8, 'add x19, x19, #0x1d8'),
    (0x2a24ec, 'bl #0x2a38f0'),
    (0x2a2508, 'bl #0x2a3918'),
    (0x2a30a0, 'ldr x3, [x0, #0x1250]'),
    (0x2a30a4, 'add x3, x3, #0x20, lsl #12'),
    (0x2a30a8, 'add x3, x3, #0x268'),
    (0x2a30ac, 'ldr w3, [x3]'),
    (0x2a30c4, 'ubfx x6, x3, #0xf, #6'),
    (0x2a3114, 'sub w0, w6, #0x11'),
    (0x2a311c, 'cmp w0, #1'),
    (0x2a3124, 'cset w0, ls'),
    (0x2a3158, 'sub w0, w6, #0x11'),
    (0x2a3160, 'cmp w0, #1'),
    (0x2a3164, 'cset w0, ls'),
    (0x2a3198, 'str w1, [x19, #0x20]'),
    (0x2a319c, 'str w1, [x19, #0x50]'),
    (0x2a31a8, 'ldr x0, [x19, #0x48]'),
    (0x2a31b0, 'bl #0x457a8'),
    (0x2a3264, 'ldr w0, [x19, #0x50]'),
    (0x2a3268, 'cbz w0, #0x2a3220'),
    (0x2a329c, 'str wzr, [x19, #0x50]'),
    (0x2a32b4, 'ldr x0, [x19, #0x1240]'),
    (0x2a32b8, 'add x0, x0, #0x80'),
    (0x2a32bc, 'ldrh w3, [x0]'),
    (0x2a32c0, 'ldr x1, [x19, #0x1250]'),
    (0x2a32c8, 'strh w3, [x19, #0x24]'),
    (0x2a32cc, 'and w3, w3, w2'),
    (0x2a32d0, 'add x1, x1, x23'),
    (0x2a32d8, 'orr w2, w2, #0x20'),
    (0x2a32dc, 'str w2, [x1]'),
    (0x2a32e0, 'strh w3, [x0]'),
    (0x2a32f4, 'bl #0x31c950'),
    (0x2a3314, 'ldrsw x0, [x0, #0xf70]'),
    (0x2a334c, 'bl #0x2a3098'),
    (0x2a3350, 'cbz w0, #0x2a3330'),
    (0x2a3360, 'and w1, w1, #0xffffffdf'),
    (0x2a337c, 'add x26, x19, x3'),
    (0x2a3384, 'add x20, x19, #0x550'),
    (0x2a338c, 'mov w25, #1'),
    (0x2a33b0, 'str w25, [x20, #0x18]'),
    (0x2a33b4, 'add x20, x20, #0x1d8'),
    (0x2a33b8, 'bl #0x2a1ff0'),
    (0x2a33c8, 'cmp x20, x26'),
    (0x2a33cc, 'b.ne #0x2a339c'),
    (0x2a3438, 'ldr w0, [x19, #0x68]'),
    (0x2a343c, 'cbz w0, #0x2a3400'),
    (0x2a3460, 'str wzr, [x19, #0x68]'),
    (0x2a3478, 'ldr x0, [x19, #0x1240]'),
    (0x2a347c, 'ldrh w1, [x19, #0x24]'),
    (0x2a3484, 'strh w1, [x0]'),
    (0x2a349c, 'bl #0x31c950'),
    (0x2a34c0, 'str wzr, [x19, #0x20]'),
    (0x2a34cc, 'bl #0x2a3098'),
    (0x2a34d4, 'cbnz w0, #0x2a3354'),
    (0x2a36fc, 'brk #0x800'),
    (0x2a372c, 'ldr x20, [x0, #8]'),
    (0x2a3730, 'ldr w1, [x20, #0x18]'),
    (0x2a3734, 'cbz w1, #0x2a3774'),
    (0x2a3740, 'b.le #0x2a3774'),
    (0x2a3758, 'ldr w0, [x20, #0x1c]'),
    (0x2a375c, 'add w1, w0, #1'),
    (0x2a3760, 'str w1, [x20, #0x1c]'),
    (0x2a3764, 'cbz w0, #0x2a3788'),
    (0x2a3798, 'ldr w0, [x19, #0x18]'),
    (0x2a379c, 'cbnz w0, #0x2a37a8'),
    (0x2a37a0, 'ldr w0, [x19, #0x14]'),
    (0x2a37a4, 'cbnz w0, #0x2a37b8'),
    (0x2a37c0, 'bl #0x2a3178'),
    (0x2a381c, 'sub w3, w3, #1'),
    (0x2a3820, 'str w3, [x20, #0x1c]'),
    (0x2a3824, 'cbz w3, #0x2a3848'),
    (0x2a385c, 'add x19, x20, #0x560'),
    (0x2a3874, 'str wzr, [x19, #8]'),
    (0x2a3878, 'add x19, x19, #0x1d8'),
    (0x2a3884, 'b.ne #0x2a3864'),
    (0x2a3894, 'str w1, [x20, #0x68]'),
    (0x2a38a8, 'bl #0x457a8'),
    (0x2a38f0, 'ldr x2, [x0, #8]'),
    (0x2a38f4, 'mov w1, #1'),
    (0x2a38f8, 'ldr w2, [x2, #0x18]'),
    (0x2a38fc, 'cbz w2, #0x2a390c'),
    (0x2a3900, 'ldr w1, [x0]'),
    (0x2a3904, 'cmp w1, #0'),
    (0x2a3908, 'cset w1, le'),
    (0x2a390c, 'str w1, [x0, #0x18]'),
    (0x2a3938, 'ldr w3, [x19, #0x1c]'),
    (0x2a393c, 'cbnz w3, #0x2a3974'),
    (0x2a3940, 'ldr w3, [x19, #0x20]'),
    (0x2a3944, 'cbnz w3, #0x2a3998'),
    (0x2a3954, 'str xzr, [x19, #0x28]'),
    (0x2a39d4, 'ldr w0, [x0]'),
    (0x2a39d8, 'bl #0x231350'),
    (0x2a39dc, 'str x0, [x19, #0x28]'),
    (0x2a39e0, 'cbz x0, #0x2a3a2c'),
    (0x2a39e4, 'ldrb w1, [x0, #0x4c]'),
    (0x2a39f0, 'add w1, w1, #0x10'),
    (0x2a39f4, 'str w1, [x19, #0x30]'),
    (0x2a3a00, 'ldr w0, [x19, #0x1c]'),
    (0x2a3a04, 'cbz w0, #0x2a3a10'),
    (0x2a3a0c, 'bl #0x2a3178'),
    (0x2a3a68, 'cmp w0, #3'),
    (0x2a3a6c, 'cset w1, eq'),
    (0x2a3a74, 'stp w1, wzr, [x19, #0x18]'),
    (0x2a3aac, 'add x0, x0, #0x1d0'),
    (0x2a3abc, 'bl #0x3cf00'),
    (0x2a3aec, 'str x20, [x19, #0x38]'),
    (0x2a3b00, 'bl #0x457a8'),
    (0x5cbdd4, 'sub x27, x20, #0x20'),
    (0x5cbdec, 'stur x19, [x20, #-0x18]'),
    (0x5cbdf4, 'bl #0x2a38f0'),
    (0x5cbea4, 'adrp x0, #0x2a2000'),
    (0x5cbea8, 'add x0, x0, #0x538'),
    (0x5cbeac, 'bl #0x31c848'),
]

STRINGS = {
    0x54d8e8: 'L0timeout',
    0x54d8f8: '\x013ERROR:PCI%d:wait for L0 timeout(t1=%lld)\n',
    0x54d928: '\x013PCI%d:LTSSM:\n',
    0x54d9d0: '\x013ERROR:PCI%d:%s: pci_get_domain_bus_and_slot failed\n',
    0x54da08: 'pcidma%d',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def capture():
    data = KERNEL.read_bytes()
    assert len(data) == 6610952 and sha(data) == EXPECTED_SHA
    assert data[:4] != b'\x7fELF' and data[56:60] == b'ARMd'
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    result = {'identity': {'path': str(KERNEL.relative_to(WORK)),
                          'size': len(data), 'sha256': sha(data),
                          'format': 'raw AArch64 Image, not ELF',
                          'linked_base': hex(BASE)},
              'capstone': capstone.__version__, 'windows': {}, 'pins': [],
              'strings': [], 'derived': {}, 'checks': []}
    for name, (lo, hi) in WINDOWS.items():
        body = data[lo:hi]
        decoded = list(cs.disasm(body, lo))
        assert len(body) == hi-lo == sum(i.size for i in decoded), name
        result['windows'][name] = {'offset': hex(lo), 'end': hex(hi),
                                   'hex': body.hex(), 'sha256': sha(body)}
    for offset, expected in PINS:
        assert any(lo <= offset < hi for lo, hi in WINDOWS.values())
        decoded = list(cs.disasm(data[offset:offset+4], offset))
        assert len(decoded) == 1
        ins = decoded[0]
        actual = (ins.mnemonic + ' ' + ins.op_str).rstrip()
        assert actual == expected, (hex(offset), actual, expected)
        result['pins'].append({'offset': hex(offset), 'hex': ins.bytes.hex(),
                               'asm': actual})
    for offset, expected in STRINGS.items():
        raw = data[offset:data.index(b'\0', offset)+1]
        assert raw[:-1].decode('ascii') == expected
        result['strings'].append({'offset': hex(offset), 'hex': raw.hex(),
                                  'text': expected})
    # The unsigned SUB/CMP/LS predicate, including 32-bit underflow below 0x11.
    passing = [state for state in range(64)
               if ((state - 0x11) & 0xffffffff) <= 1]
    assert passing == [0x11, 0x12]
    assert 0x20*0x1000 + 0x268 == 0x20268
    assert 0x264 + (2 << 16) == 0x20264
    ready_channels = list(range(0x550, 0x1238, 0x1d8))
    cleared_lock_bases = list(range(0x560, 0x1248, 0x1d8))
    assert len(ready_channels) == len(cleared_lock_bases) == 7
    for channel_id, (channel, lock) in enumerate(zip(ready_channels, cleared_lock_bases), 1):
        assert channel == 0x378 + channel_id*0x1d8
        assert channel + 0x18 == lock + 8
    initial_policy3 = [int(channel_id <= 0) for channel_id in range(8)]
    assert initial_policy3 == [1, 0, 0, 0, 0, 0, 0, 0]
    timeout, priority = struct.unpack_from('<ii', data, 0x634f70)
    assert (timeout, priority) == (10000, 148)
    result['derived'] = {'wrapper_status_offset': '0x20268',
                         'wrapper_request_offset': '0x20264',
                         'state_bits': [15, 20], 'accepted_state_values': passing,
                         'initial_policy3_permission_ch0_to_ch7': initial_policy3,
                         'initial_other_policy_permission_ch0_to_ch7': [1]*8,
                         'controller_18_semantics': 'pcie_aspm_policy(id)==3; NOT a host/endpoint role',
                         'ready_channel_offsets': [hex(x) for x in ready_channels],
                         'clear_alias': 'controller+0x560+n*0x1d8+8 == channel(1+n)+0x18',
                         'timeout_data': {'offset': '0x634f70',
                                          'hex': data[0x634f70:0x634f78].hex(),
                                          'timeout_raw': timeout, 'thread_priority_raw': priority},
                         'callback_pointer': {'producer': ['0x5cbea4', '0x5cbea8'],
                                              'image_offset': '0x2a2538',
                                              'linked_va': hex(BASE+0x2a2538),
                                              'classification': 'function pointer passed in x0; not data at Image+0x62e538'},
                         'channel_18_classification': 'u32 software permission; not MMIO, counter or function pointer'}
    result['checks'] = ['pinned original raw Image identity and offset convention',
                        f'{len(PINS)} exact instruction pins in bounded windows',
                        'actual initial/publish/retire/reset channel+0x18 writers',
                        'request-count wake and original pcidma_run call edges',
                        'wrapper hardware state predicate and all 64 state values',
                        'seven-channel publish and retirement alias arithmetic',
                        'original L0/LTSSM diagnostics and callback pointer classification']
    result['limits'] = ['Static original-byte evidence only; no VM/GDB/network/device execution.',
                        'No ATU/fixed-I/O implementation or link-ready injection.',
                        'PCI access helpers, scheduler, mutex/spinlock primitives and silicon link FSM not expanded.',
                        'Timeout value pinned as raw data; timer conversion helper not expanded.',
                        'No claim that any current emulation naturally meets these prerequisites.']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true')
    args = parser.parse_args()
    result = capture()
    if args.capture:
        (HERE/'raw.json').write_text(json.dumps(result, indent=2)+'\n')
        print('CAPTURED raw.json after assertions')
    else:
        assert json.loads((HERE/'raw.json').read_text()) == result, 'capture differs from original'
        print('PASS: raw.json independently reproduces from pinned original')
    for check in result['checks']:
        print('PASS:', check)
    print('PASS: offline readiness-source evidence only; no runtime completion claim')


if __name__ == '__main__':
    main()
