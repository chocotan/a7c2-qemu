#!/usr/bin/env python3
"""Verify static CP NEXT-state evidence; never execute firmware or set state."""
import hashlib
import json
from pathlib import Path
import runpy
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

HERE = Path(__file__).resolve().parent
CP = HERE.parents[1] / 'runtime/analysis/menu-root/cp/cpapp-b.bin'
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
BASE = 0x108000


def verify():
    blob = CP.read_bytes()
    if len(blob) != 18090880 or hashlib.sha256(blob).hexdigest() != CP_SHA:
        raise ValueError('expected the pinned public CP app image')
    manifest = json.loads((HERE / 'source-pins.json').read_text())

    def read(va, size):
        offset = va - BASE
        if offset < 0 or size > len(blob) - offset:
            raise ValueError('window is outside file-backed CP addresses')
        return blob[offset:offset + size]

    for pin in manifest['pins']:
        raw = read(int(pin['cpva'], 16), pin['length'])
        assert raw.hex() == pin['bytes'], pin['name']
        assert hashlib.sha256(raw).hexdigest() == pin['sha256'], pin['name']

    engines = {'thumb': Cs(CS_ARCH_ARM, CS_MODE_THUMB),
               'arm': Cs(CS_ARCH_ARM, CS_MODE_ARM)}

    def exact(va, mnemonic, operands, isa='thumb'):
        ins = next(engines[isa].disasm(read(va, 4), va))
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands), hex(va)

    def call(va, target):
        exact(va, 'bl', '#' + hex(target))

    for entry in (0x4d6a98, 0x4d7484, 0x4d9ebc):
        exact(entry, 'push', '{r4, r5, r6, r7, lr}')
    exact(0x4b7268, 'movw', 'r0, #0x6a99')
    exact(0x4b7278, 'movt', 'r0, #0x4d')
    exact(0x4b7270, 'movs', 'r1, #0x16')
    call(0x4b7286, 0x7a73be)
    exact(0x4d6f9a, 'movw', 'r0, #0x7485')
    exact(0x4d6fae, 'movt', 'r0, #0x4d')
    call(0x4d6fc0, 0x50ff1c)
    exact(0x4d6fc4, 'movw', 'r0, #0x9ebd')
    exact(0x4d6fd4, 'movt', 'r0, #0x4d')
    call(0x4d6fde, 0x50ff1c)
    call(0x4dc5d6, 0x50ff1c)

    exact(0x4d7a90, 'movw', 'r0, #0xefe8')
    exact(0x4d7a94, 'movt', 'r0, #0x173')
    call(0x4d7a98, 0x4b29e0)
    exact(0x4b2a22, 'movw', 'r4, #0x2adc')
    exact(0x4b2a26, 'movw', 'r5, #0x2ae0')
    exact(0x4b2a3a, 'ldr', 'r2, [r4]')
    exact(0x4b2a3c, 'ldr', 'r1, [r5]')
    call(0x4b2a3e, 0xb1f45c)
    exact(0xb1f488, 'ldr', 'r1, [r5, #8]')
    exact(0xb1f48c, 'blx', 'r1')
    exact(0xb1f48e, 'str.w', 'r0, [r8, #8]')
    call(0x4b2a56, 0xb1f4ce)
    exact(0xb1f4ce, 'ldr', 'r0, [r0, #8]')
    exact(0xb1f4d0, 'cbz', 'r0, #0xb1f4da')
    exact(0xb1f4d2, 'ldrh', 'r1, [r0]')
    exact(0xb1f4d4, 'ldrh.w', 'r0, [r0, r1, lsl #1]')
    exact(0x4b2a5a, 'movw', 'r1, #0x2ae4')
    exact(0x4b2a5e, 'movt', 'r1, #0x1a5')
    exact(0x4b2a62, 'str', 'r0, [r1]')

    # A nonzero bypass byte reaches phase=1 without the NEXT assignment.
    exact(0x4b2a08, 'movw', 'r0, #0xdf9c')
    exact(0x4b2a0c, 'movt', 'r0, #0x1b1')
    exact(0x4b2a10, 'ldrb', 'r0, [r0]')
    exact(0x4b2a12, 'cmp', 'r0, #0')
    exact(0x4b2a14, 'bne', '#0x4b2acc')
    exact(0x4b2acc, 'movw', 'r0, #0xdf9d')
    exact(0x4b2ad0, 'movs', 'r1, #1')
    exact(0x4b2ad2, 'movt', 'r0, #0x1b1')
    exact(0x4b2ad6, 'strb', 'r1, [r0]')

    call(0x4dacf0, 0xb1f1cc)
    exact(0xb1f21e, 'movw', 'r0, #0x2ae4')
    exact(0xb1f222, 'movw', 'r1, #0x2ad4')
    exact(0xb1f236, 'ldr', 'r0, [r0]')
    exact(0xb1f238, 'str', 'r0, [r1]')

    # The concrete bank/channel follow from source initialization, not RAM zeros.
    exact(0x7a74f8, 'movw', 'r8, #0x8508')
    exact(0x7a74fc, 'movs', 'r4, #0')
    exact(0x7a74fe, 'movt', 'r8, #0x17a')
    exact(0x7a7502, 'movs', 'r5, #0')
    call(0x7a750c, 0x7a731a)
    exact(0x7a731a, 'strd', 'r1, r2, [r0]')
    exact(0x4b725a, 'movs', 'r4, #0')
    exact(0x4b7264, 'movw', 'r5, #0x7075')
    exact(0x4b7274, 'movt', 'r5, #0x63')
    exact(0x4b7272, 'movs', 'r2, #1')
    exact(0x4b7284, 'movs', 'r0, #0')
    exact(0x7a7400, 'bl', '#0x7a7320')
    exact(0x7a733a, 'stm', 'r0!, {r1, r2, r4, r5, r6}')
    call(0x7a7342, 0x2740fc)
    call(0x7a7350, 0x274190)
    exact(0x7a7360, 'b.w', '#0x7a7278')
    bank0 = struct.unpack('<I', read(0xd6feec, 4))[0]
    assert bank0 == 0xf4830000

    # Selected cases write source=0x16 and its configuration word=1.
    exact(0x274100, 'tbb', '[pc, r1]')
    assert 0x274104 + 2 * read(0x274104, 1)[0] == 0x27410c
    exact(0x274118, 'adds', 'r0, #0x40')
    exact(0x27418a, 'str', 'r2, [r0]')
    exact(0x274196, 'tbh', '[pc, r1, lsl #1]')
    jump = struct.unpack('<H', read(0x27419a + 0x16 * 2, 2))[0]
    assert 0x27419a + 2 * jump == 0x27433a
    exact(0x274346, 'adds', 'r0, #0xb8')
    exact(0x2743d8, 'str', 'r2, [r0]')
    exact(0x7a728c, 'bics', 'r2, r1')
    exact(0x7a728e, 'str', 'r2, [r0, #0xc]')
    exact(0x7a7292, 'orrs', 'r1, r2')
    exact(0x7a7294, 'str', 'r1, [r0, #0x10]')

    assert struct.unpack('<3I', read(0xeafb60, 12)) == (0x25, 0, 0x7a7541)
    exact(0x7a7522, 'movs', 'r0, #0x25')
    exact(0x7a7524, 'blx', '#0x5e4fd4')
    exact(0x7a7540, 'movs', 'r0, #0')
    call(0x7a7550, 0x7a72ca)
    exact(0x7a72d6, 'ldr', 'r0, [r0, #4]')
    call(0x7a755a, 0x7a7298)
    exact(0x7a72a4, 'str', 'r1, [r0, #8]')
    exact(0x7a7566, 'movs', 'r6, #0')
    exact(0x7a7568, 'mov.w', 'r8, #1')
    exact(0x7a7578, 'tst.w', 'r4, sb')
    exact(0x7a757c, 'beq', '#0x7a758e')
    call(0x7a7580, 0x7a737e)
    call(0x7a7398, 0x2743dc)
    assert 0x2743e4 + 2 * read(0x2743e4, 1)[0] == 0x2743ec
    exact(0x2743f8, 'adds', 'r0, #0x20')
    exact(0x27446e, 'ldr', 'r0, [r0]')
    exact(0x7a73b2, 'blx', 'r2')
    exact(0x637074, 'ldr', 'r2, [r0, #8]')
    exact(0x637076, 'mov', 'r0, r1')
    exact(0x637078, 'bx', 'r2')
    assert read(0x4d71dc, 8) == b'int_HS0\0'
    exact(0x4d6b24, 'addw', 'r0, pc, #0x6b4')
    assert 0x4d6b28 + 0x6b4 == 0x4d71dc
    assert read(0x2746ac, 23) == b'GetCaptureCounterValue\0'
    exact(0x274672, 'adr', 'r1, #0x38')
    assert 0x274674 + 0x38 == 0x2746ac
    exact(0x27466c, 'b.w', '#0x2743dc')

    # Global setup writes are explicit; their silicon function is unnamed.
    call(0x7a74a6, 0x7a725a)
    exact(0x7a74aa, 'movs', 'r0, #0')
    call(0x7a74ae, 0x7a723a)
    exact(0x7a74b2, 'movs', 'r0, #0x17')
    call(0x7a74b4, 0x7a7244)
    exact(0x7a723a, 'movs', 'r1, #0xe4')
    exact(0x7a723c, 'movt', 'r1, #0xf493')
    exact(0x7a7240, 'str', 'r0, [r1]')
    exact(0x7a7244, 'movs', 'r1, #0xe8')
    exact(0x7a724a, 'str', 'r0, [r1]')
    exact(0x7a724e, 'movs', 'r0, #0xec')
    exact(0x7a7250, 'movs', 'r1, #1')
    exact(0x7a7256, 'str', 'r1, [r0]')
    exact(0x7a725c, 'movs', 'r1, #0')
    exact(0x7a7262, 'str', 'r1, [r0]')
    exact(0x7a753c, 'b.w', '#0x7a724e')

    # Internal 3005 is a guarded capture producer, with observable rejection work.
    exact(0x4750e8, 'push', '{r4, r5, r6, r7, lr}')
    call(0xb0dc68, 0x4750e8)
    exact(0xb15e88, 'movw', 'r1, #0xdb5b')
    exact(0xb15e8e, 'movt', 'r1, #0xb0')
    call(0xb15e96, 0x50ff1c)
    exact(0x4751ec, 'movw', 'r0, #0x3005')
    call(0x4751f0, 0xb1f140)
    exact(0x4751f4, 'cbz', 'r0, #0x475222')
    exact(0x475508, 'movw', 'r0, #0x3005')
    exact(0x47550c, 'movs', 'r1, #0')
    call(0x47550e, 0x4b28d8)
    exact(0xb1f156, 'strb', 'r0, [r1]')
    exact(0xb1f170, 'b.w', '#0xb1f418')
    table = read(0xd97468, 320 * 16)
    assert hashlib.sha256(table).hexdigest() == manifest['command_table320_sha256']
    rows3005 = [row for row in struct.iter_unpack('<4I', table) if row[1] == 0x3005]
    assert rows3005 == [(0x4e, 0x3005, 0x8dd59b, 0x3021),
                        (8, 0x3005, 0x8dd5a5, 0x3021),
                        (0x4f, 0x3005, 0x8dd5af, 0x3021),
                        (9, 0x3005, 0x8dce13, 0x3021)]
    assert struct.unpack('<3H', read(0xeda3ae, 6)) == (2, 0x38, 0x4e)
    assert struct.unpack('<3H', read(0xeda3b4, 6)) == (2, 0x38, 8)
    assert struct.unpack('<3H', read(0xeda0de, 6)) == (2, 0x38, 9)
    exact(0x47522a, 'movs', 'r1, #0')
    exact(0x47522c, 'movs', 'r2, #1')
    call(0x47522e, 0xb20a4a)
    exact(0xb20a68, 'mov.w', 'r0, #0x8200')
    call(0xb20a8e, 0x4b5fe4)
    exact(0xb20a9e, 'cbnz', 'r0, #0xb20ac2')
    exact(0xb20aa8, 'movw', 'r0, #0x203')
    call(0xb20abe, 0x4b5fe4)
    call(0x475436, 0xb0dfea)
    exact(0x47543a, 'mov.w', 'r0, #0x40000')
    call(0x47543e, 0xae263a)

    startup = runpy.run_path(str(HERE.parent / 'verify_cp_central_startup.py'))['verify']()
    assert startup['source_initial_current_at_clear_return'] == 0
    start, end, next_address = 0x120a418, 0x1b85f5c, 0x1a52ae4
    assert start <= next_address and next_address + 4 <= end
    delta = next_address - start
    assert delta % 128 == 0x4c
    assert 0x61ed54 + ((delta % 128) // 8) * 4 == 0x61ed78
    exact(0x61ed04, 'mov', 'r1, #0', 'arm')
    exact(0x61ed44, 'mov', 'r2, r3', 'arm')
    exact(0x61ed78, 'strdge', 'r2, r3, [ip], #8', 'arm')

    return {'scope': 'static source and explicit-clear boundary only',
            'cp_sha256': CP_SHA, 'source_windows_verified': len(manifest['pins']),
            'window_bytes': sum(p['length'] for p in manifest['pins']),
            'startup_source_windows_verified': startup['source_windows_verified'],
            'source_next_at_clear_return': 0,
            'phase_one_guarantees_next_assignment': False,
            'post_constructor_next_known': False,
            'runtime_next_before_302c_known': False,
            'callback_execution_order_verified': False,
            'record_initialization_execution_verified': False,
            'irq_delivery_verified': False,
            'upstream_input_0x16_producer_known': False,
            'conditional_irq_id': '0x25', 'conditional_pending_bit': 0,
            'conditional_mmio_bank': hex(bank0),
            'native_table_3005_rows': len(rows3005),
            'native_table_allows_3005_at_current0': False,
            'capture_start_rejection_has_no_side_effects': False,
            'internal_3005_execution_before_prefix_known': False,
            'central_history_complete': False,
            '302c_native_verified': False, 'capture_verified': False}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
