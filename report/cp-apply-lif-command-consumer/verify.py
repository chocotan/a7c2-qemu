#!/usr/bin/env python3
"""Read-only public-CP checks; this does not execute CP tasks or emulate a lens."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

HERE = Path(__file__).resolve().parent
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
BASE = 0x108000


def verify(cp_path):
    blob = cp_path.read_bytes()
    pins = json.loads((HERE / 'source-pins.json').read_text())
    if len(blob) != 18090880 or hashlib.sha256(blob).hexdigest() != CP_SHA:
        raise ValueError('expected the pinned public CP app image')

    def read(va, size):
        offset = va - BASE
        if offset < 0 or size > len(blob) - offset:
            raise ValueError('window is outside file-backed CP addresses')
        return blob[offset:offset + size]

    for pin in pins['pins']:
        raw = read(int(pin['cpva'], 16), pin['length'])
        assert raw.hex() == pin['bytes'], pin['name']
        assert hashlib.sha256(raw).hexdigest() == pin['sha256'], pin['name']

    thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

    def instruction(va):
        return next(thumb.disasm(read(va, 4), va))

    def call(va, destination):
        ins = instruction(va)
        assert ins.mnemonic in ('bl', 'b.w'), (hex(va), ins.mnemonic)
        assert ins.op_str == '#' + hex(destination), (hex(va), ins.op_str)

    def exact(va, mnemonic, operands):
        ins = instruction(va)
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands), hex(va)

    # Object registration is array storage, not a direct command executor.
    exact(0xa918ca, 'cmp', 'r1, #3')
    exact(0xa918d6, 'str.w', 'r0, [r2, r1, lsl #2]')
    exact(0xa5c022, 'movw', 'r3, #0x9585')
    exact(0xa5c030, 'movt', 'r3, #0x3e')
    exact(0xa5c03c, 'movs', 'r1, #3')
    call(0xa5c03e, 0xa918ca)
    call(0x3e98ea, 0xa5c422)
    call(0xa5c4b4, 0xa94502)
    exact(0x40608e, 'ldr', 'r0, [r0, #0xc]')
    exact(0x406090, 'ldr', 'r1, [r0, #0xc]')
    exact(0x406094, 'blx', 'r1')
    call(0x4060b4, 0xa90758)
    call(0x4060c4, 0xa91e54)

    # APPLY sets A; the worker reads A & (B==0), then snapshots B=A.
    exact(0x9d30ee, 'movw', 'r0, #0x63d4')
    exact(0x9d30f2, 'movs', 'r1, #1')
    exact(0x9d30f8, 'strb', 'r1, [r0]')
    exact(0x9d3100, 'movs', 'r1, #0')
    exact(0x9d3106, 'strb', 'r1, [r0]')
    exact(0x9d3108, 'movw', 'r0, #0x63d5')
    exact(0x9d3110, 'strb', 'r1, [r0]')
    exact(0x9d3120, 'movw', 'r0, #0x63d4')
    exact(0x9d3124, 'movw', 'r1, #0x63d5')
    exact(0x9d3130, 'ldrb', 'r0, [r0]')
    exact(0x9d3132, 'strb', 'r0, [r1]')
    exact(0x9d3136, 'movw', 'r0, #0x63d5')
    exact(0x9d3140, 'ldrb', 'r0, [r0]')
    exact(0x9d3142, 'cmp', 'r0, #0')
    exact(0x9d3144, 'movw', 'r0, #0x63d4')
    exact(0x9d314c, 'it', 'eq')
    exact(0x9d314e, 'movs', 'r1, #1')
    exact(0x9d3150, 'ldrb', 'r0, [r0]')
    exact(0x9d3152, 'ands', 'r0, r1')
    call(0x9cfca4, 0x9d3136)
    exact(0x9cfca8, 'cmp', 'r0, #1')
    call(0x9cfe5a, 0xa4abc0)
    call(0x9cfe6a, 0x9d3120)
    exact(0x98eca8, 'mov', 'r4, r1')
    exact(0x98ecdc, 'cbz', 'r4, #0x98ecee')
    call(0x98ecee, 0x9a7ffe)
    exact(0x98ecf2, 'cbz', 'r0, #0x98ed38')
    call(0x98ecfe, 0x9cf8c6)
    call(0x98ed12, 0x9cf8c6)
    for a in range(256):
        for b in range(256):
            r1 = 0
            if b == 0:
                r1 = 1
            result = a & r1
            assert (result == 1) == (bool(a & 1) and b == 0)

    # Direct callers prove literal writes, not their startup execution order.
    exact(0x9a7edc, 'push', '{r4, r5, r7, lr}')
    exact(0x9a7ee0, 'movw', 'r5, #0xd2a8')
    exact(0x9a7ee4, 'mov', 'r4, r0')
    exact(0x9a7ee6, 'movt', 'r5, #0x165')
    exact(0x9a7ef4, 'movs', 'r0, #0xff')
    exact(0x9a7efa, 'str', 'r0, [r5, #0x20]')
    exact(0x9a7f06, 'strb', 'r4, [r5, #0x19]')
    exact(0x9a8006, 'ldrb', 'r0, [r0, #0x19]')
    flag_calls = [(0x3b04d8, 0x3b04da, 0), (0x3b05ba, 0x3b05bc, 0),
                  (0x990f28, 0x990f30, 1), (0x990f48, 0x990f4c, 0),
                  (0x9d211a, 0x9d211c, 0), (0x9d24b6, 0x9d24b8, 0),
                  (0x9d2512, 0x9d2514, 1), (0x9d26d4, 0x9d26d6, 0),
                  (0x9d273e, 0x9d2740, 0), (0x9d2b8c, 0x9d2b8e, 1)]
    for load, site, value in flag_calls:
        exact(load, 'movs', 'r0, #' + str(value))
        call(site, 0x9a7edc)
    exact(0x9cff9a, 'ldr.w', 'r1, [r1, r0, lsl #2]')
    exact(0x9cffa0, 'blx', 'r1')
    assert struct.unpack('<I', read(0xdecd58 + 5 * 4, 4))[0] == 0x9d222f
    assert struct.unpack('<I', read(0xdecd58 + 7 * 4, 4))[0] == 0x9d1ff5

    # Clearing one gate can coexist with setting the other gate's source to 1.
    exact(0x3afc00, 'movw', 'sl, #0xf418')
    exact(0x3afc06, 'movt', 'sl, #0x10f')
    exact(0x3b04c8, 'movs', 'r0, #1')
    exact(0x3b04ca, 'ldr.w', 'r1, [sl]')
    exact(0x3b04ce, 'str.w', 'r0, [r1, #0x198]')
    exact(0x3b04d8, 'movs', 'r0, #0')
    call(0x3b04da, 0x9a7edc)
    exact(0x3b0b66, 'movw', 'r8, #0xf418')
    exact(0x3b0b6c, 'movt', 'r8, #0x10f')
    exact(0x3b0c54, 'ldr.w', 'r0, [r8]')
    exact(0x3b0c68, 'ldr.w', 'r1, [r0, #0x198]')
    call(0x3b0c78, 0x98ec9c)
    assert struct.unpack('<I', read(0x10ff418, 4))[0] == 0x18b8fd8

    # Release indices are their own state domain, with a full-r1 sentinel.
    exact(0x9d09b6, 'cmp', 'r1, #0xff')
    exact(0x9d09c0, 'ldrb.w', 'r4, [r0, #0x17c]')
    exact(0x9d09c4, 'it', 'eq')
    exact(0x9d09c6, 'adds', 'r1, r4, #1')
    exact(0x9d09c8, 'uxtb', 'r6, r1')
    exact(0x9d09ca, 'strb.w', 'r1, [r0, #0x17c]')
    exact(0x9d09fa, 'cmp.w', 'sb, #1')
    exact(0x9d0a0a, 'strb', 'r1, [r0]')
    exact(0x9d0a14, 'strb', 'r1, [r0]')
    exact(0x3b09ce, 'cmp', 'r0, #7')
    exact(0x3b09d0, 'bne', '#0x3b0a14')
    exact(0x3b09f8, 'movs', 'r1, #0xff')
    exact(0x3b0a00, 'strb.w', 'r1, [r0, #0x17c]')
    call(0x3b0b9c, 0x9df0e2)
    exact(0x9df0ec, 'mov', 'r5, r0')
    exact(0x9df0ee, 'mov', 'r6, r2')
    exact(0x9df0f0, 'mov', 'r4, r3')
    exact(0x9df0f2, 'mov', 'r8, r1')
    exact(0x9df1bc, 'eor', 'r1, r4, #1')
    exact(0x9df1c0, 'bic.w', 'r0, r5, r6')
    exact(0x9df1c4, 'and.w', 'r1, r1, r8')
    exact(0x9df1c8, 'ands', 'r0, r1')
    exact(0x9df1d2, 'strb', 'r0, [r1]')
    exact(0x9cfdbc, 'bl', '#0x9a7fe2')
    exact(0x9cfdc0, 'cbz', 'r0, #0x9cfdf2')
    call(0x9cfdf2, 0x9df0d6)
    exact(0x9cfdf6, 'cmp', 'r0, #1')
    exact(0x9cfe08, 'cmp', 'r0, #4')
    exact(0x9cfe0a, 'bhi', '#0x9cfe6a')
    exact(0x9cfe0c, 'movs', 'r0, #0xd')
    exact(0x9cfe0e, 'b', '#0x9cfe62')
    exact(0x9cfe62, 'movs', 'r1, #5')
    exact(0x9cfe64, 'movs', 'r2, #1')
    call(0x9cfe66, 0x9d09a8)
    exact(0x9cfe76, 'ldrb', 'r0, [r0, #9]')
    exact(0x9cfe78, 'cbz', 'r0, #0x9cfe84')
    exact(0x9cfe7c, 'movs', 'r1, #7')
    call(0x9cfe80, 0x9d09a8)
    release_cases = 0
    for old in range(256):
        for requested in (0, 1, 2, 5, 7, 254, 255, 256, 511, 0xffffffff):
            value = old + 1 if requested == 255 else requested
            stored = value & 0xff
            assert 0 <= stored <= 255
            if requested == 255:
                assert stored == (old + 1) % 256
            if requested == 511:
                assert stored == 255
            release_cases += 1

    # A 15B queue slot has one bookkeeping byte plus 14B command payload.
    exact(0xa5c706, 'movs', 'r0, #0x1c')
    exact(0xa5c708, 'strb.w', 'r0, [sp]')
    call(0xa5c70e, 0xa5c366)
    exact(0xa5c3c2, 'movs', 'r2, #0')
    exact(0xa5c3c6, 'rsb', 'r0, r0, r0, lsl #4')
    exact(0xa5c3ca, 'strb', 'r2, [r1, r0]')
    exact(0xa5c3cc, 'movs', 'r2, #0xe')
    exact(0xa5c3d4, 'adds', 'r0, #1')
    exact(0xa5c3d6, 'blx', '#0x61e60c')

    # Slot count retirement and later list consumption are different events.
    exact(0x3e98f2, 'cbz', 'r1, #0x3e991c')
    exact(0x3e990c, 'strb', 'r0, [r4]')
    call(0x3e990e, 0xa5ca5c)
    exact(0xa5ca64, 'movs', 'r1, #0x2d')
    call(0xa5ca66, 0xa51984)
    exact(0xa5ca80, 'movw', 'r0, #0x4c48')
    exact(0xa5ca88, 'ldrb', 'r1, [r0, #3]')
    exact(0xa5ca8a, 'subs', 'r1, #1')
    exact(0xa5ca8c, 'strb', 'r1, [r0, #3]')
    call(0xa5ca92, 0xa519b0)
    exact(0x3e9920, 'movw', 'r4, #0x87ca')
    exact(0x3e9924, 'movs', 'r2, #0xe')
    exact(0x3e9926, 'movt', 'r4, #0x1b1')
    exact(0x3e992c, 'adds', 'r1, r0, #1')
    exact(0x3e9930, 'blx', '#0x61e60c')
    exact(0x3e99e2, 'movw', 'r0, #0x87e6')
    exact(0x3e99e6, 'movs', 'r5, #0')
    exact(0x3e99ec, 'strb', 'r5, [r0]')

    # This is the original file's table pointer. Its runtime binding is separate.
    table = struct.unpack('<I', read(0x1107030, 4))[0]
    assert table == 0x120553c
    metadata = struct.unpack('<3H', read(table + 0x1c * 6, 6))
    assert metadata == (0x1c, 1, 2)
    exact(0xa90764, 'movt', 'r1, #0x171')
    exact(0xa90768, 'ldrb', 'r0, [r1, r0]')
    call(0xa90794, 0xa90f42)
    call(0xa90f42, 0xa90758)
    exact(0xa9079e, 'add.w', 'r1, r5, r5, lsl #1')
    exact(0xa907a2, 'ldrh.w', 'r2, [r0, r1, lsl #1]')
    exact(0xa907ac, 'ldrh', 'r1, [r0, #2]')
    exact(0xa907ae, 'strh', 'r1, [r4, #2]')
    call(0xa91e6e, 0xa90772)
    exact(0xa91e76, 'ldrh.w', 'r4, [sp, #2]')
    exact(0xa91e82, 'mov', 'r2, r4')
    exact(0xa91e84, 'blx', '#0x61e60c')

    # Copying a command is followed by the real framing/queue entrypoint.
    call(0xa91144, 0x405eec)
    exact(0xa9115a, 'mov', 'r0, sb')
    exact(0xa91160, 'blx', '#0x61e60c')
    call(0xa911aa, 0xa9366c)
    call(0xa93684, 0xa48382)
    exact(0xa483a0, 'movs', 'r1, #0xf0')
    exact(0xa483a8, 'add.w', 'r1, r6, #8')
    exact(0xa483c0, 'strb', 'r4, [r0, #4]')
    exact(0xa483ca, 'uxth', 'r5, r6')
    exact(0xa483ce, 'adds', 'r0, #1')
    exact(0xa483d8, 'uxtah', 'r1, r6, r1')
    exact(0xa483ec, 'movs', 'r0, #0x55')
    call(0xa483f8, 0xa478c4)
    call(0xa911ba, 0xa9688c)

    # Dequeue indexes records; the original pool record retires after staging.
    exact(0xa4799e, 'ldr.w', 'r4, [r2, r1, lsl #2]')
    call(0xa47c32, 0xa47962)
    exact(0xa47c3a, 'mov.w', 'r1, #0x324')
    exact(0xa47c5e, 'blx', '#0x61e60c')
    exact(0xa47c76, 'it', 'eq')
    exact(0xa47c78, 'str', 'r3, [r2]')
    exact(0x406be6, 'ldrh.w', 'r0, [sp, #0xe]')
    call(0x406d76, 0xa9368c)

    # UART1 init and DMA1 submission are source gates, not observed completion.
    exact(0x3e1c58, 'movs', 'r0, #1')
    call(0x3e1c5e, 0xbfc2a8)
    call(0xbfc2b6, 0xbfbe9a)
    exact(0xbfbe9a, 'mov.w', 'r2, #-0xf000000')
    exact(0xbfbe9e, 'add.w', 'r0, r2, r0, lsl #12')
    assert (0xf1000000 + (1 << 12)) == 0xf1001000
    assert struct.unpack('<I', read(0xcec214, 4))[0] == 1
    assert struct.unpack('<I', read(0xcec254, 4))[0] == 0
    exact(0x3e1ac6, 'movs', 'r0, #5')
    exact(0x3e1ad0, 'movs', 'r0, #8')
    exact(0x3e1ae0, 'movs', 'r0, #1')
    call(0x3e1ae2, 0x5810bc)
    exact(0x3e1b08, 'strd', 'r1, r2, [sp]')
    call(0x3e1b36, 0x581240)
    exact(0xbf69c2, 'movw', 'r2, #0x8000')
    exact(0xbf69c8, 'movt', 'r2, #0xf105')
    exact(0xbf69f6, 'str.w', 'r2, [r0, #0x100]')
    exact(0xbf69fc, 'str.w', 'r2, [r0, #0x104]')
    exact(0xbf6a02, 'str.w', 'r1, [r0, #0x10c]')
    assert 0xf1058000 + (1 << 5) + 0x100 == 0xf1058120
    exact(0xbf6c94, 'dsb', 'sy')
    exact(0xbf6cac, 'str.w', 'r2, [r0, #0x110]')

    # The interrupt passes an error flag, but a48acc overwrites incoming r0.
    exact(0xbf6a50, 'ldr', 'r2, [r2, #0xc]')
    exact(0xbf6a58, 'str', 'r0, [r1, #4]')
    exact(0xbf70a6, 'ldr', 'r0, [sp, #4]')
    exact(0xbf70a8, 'blx', 'r1')
    exact(0xa48ad2, 'movw', 'r0, #0x2078')
    call(0xa48af6, 0xbfaf4c)
    exact(0xa48b2c, 'mov.w', 'r0, #0x12c')
    call(0xa48b3c, 0xbfaf4c)
    exact(0xbfb0a4, 'bx', 'r1')
    exact(0xa91b66, 'movs', 'r0, #3')
    call(0xa91b68, 0xa9688c)
    exact(0xa912f0, 'strb.w', 'r0, [r4, #0x21]')

    # The independent 44B path has reset/queue effects before any dequeue.
    exact(0xa4a3fa, 'movs', 'r1, #0x2c')
    exact(0xa4a3fe, 'blx', '#0x61ed00')
    exact(0xa4a404, 'movs', 'r1, #1')
    call(0xa4a406, 0xa4a430)
    exact(0xa4a464, 'movw', 'r1, #0xe710')
    exact(0xa4a472, 'strb.w', 'ip, [r1]')
    exact(0xa4a476, 'movw', 'r1, #0xe70c')
    exact(0xa4a47e, 'ldrb.w', 'sl, [r1]')
    exact(0xa4a482, 'movw', 'r1, #0xe708')
    exact(0xa4a48a, 'strb.w', 'sl, [r1]')
    exact(0xa4a4c2, 'add.w', 'sl, sl, #1')
    exact(0xa4a4c6, 'movw', 'r2, #0xe5a8')
    exact(0xa4a4d2, 'cmp', 'r1, #8')
    exact(0xa4a4d4, 'it', 'eq')
    exact(0xa4a4d6, 'mov.w', 'sl, #0')
    exact(0xa4a4da, 'movs', 'r3, #0x2c')
    exact(0xa4a4e0, 'smlabb', 'lr, r1, r3, r2')
    exact(0xa4a4f4, 'movw', 'r0, #0xe70c')
    exact(0xa4a4f8, 'movw', 'r1, #0xe710')
    exact(0xa4a504, 'strb.w', 'sl, [r0]')
    exact(0xa4a508, 'add.w', 'r0, ip, #1')
    exact(0xa4a50c, 'strb', 'r0, [r1]')
    exact(0xa4a41e, 'cmp', 'r2, #5')
    exact(0xa4a420, 'strb', 'r0, [r3, #4]')
    call(0xa4a426, 0xa51d98)
    exact(0xa51da4, 'adds', 'r1, #0x24')
    exact(0xa51da6, 'cmp.w', 'r1, #0x900')
    exact(0xa51daa, 'strb', 'r0, [r3, #0x1e]')
    assert len(range(0, 0x900, 0x24)) == 64
    exact(0x991ffa, 'movs', 'r0, #3')
    call(0x991ffc, 0x9b78f8)
    exact(0xa4a77e, 'strb', 'r1, [r0, #0x1d]')
    for old_tail in range(8):
        next_tail = (old_tail + 1) % 8
        assert 0 <= next_tail < 8
        assert 0x19ee5a8 + 44 * next_tail + 44 <= 0x19ee708

    # Conditional byte arithmetic oracle; not a runtime packet/publication claim.
    frames = []
    for seq in range(256):
        payload = bytes([metadata[0]])
        prefix = bytes([0xf0, 9, 0, 1, seq]) + payload
        checksum = sum(prefix[1:]) & 0xffff
        frame = prefix + struct.pack('<H', checksum) + b'\x55'
        assert len(frame) == 9
        assert struct.unpack_from('<H', frame, 1)[0] == len(frame)
        assert struct.unpack_from('<H', frame, 6)[0] == 0x26 + seq
        assert frame[5] == 0x1c
        frames.append(frame)
    assert frames[0].hex() == 'f0090001001c260055'
    assert frames[255].hex() == 'f0090001ff1c250155'
    dma_span = (metadata[1] + 0x17) & 0xfff0
    assert dma_span == 16 and dma_span - len(frames[0]) == 7

    return {
        'scope': 'static source/table/callsite verification; packet arithmetic is conditional',
        'cp_sha256': CP_SHA, 'windows_verified': len(pins['pins']),
        'window_bytes': sum(pin['length'] for pin in pins['pins']),
        'command_1c_table': list(metadata), 'conditional_packet_cases': len(frames),
        'queue_slot_bytes': 15, 'queue_bookkeeping_bytes': 1,
        'queued_command_bytes': 14, 'command_tail_source_bytes_unknown': 13,
        'borrowed_command_stability_verified': False,
        'queue_retirement_implies_output_consumed': False,
        'conditional_replacement_slot_cases': 8, 'reset_flag_count': 64,
        'conditional_two_flag_cases': 65536,
        'delayed_work_inactive_before_prefix_verified': False,
        'direct_flag_setter_calls_checked': len(flag_calls),
        'direct_flag_zero_calls_checked': sum(value == 0 for _, _, value in flag_calls),
        'direct_flag_one_calls_checked': sum(value == 1 for _, _, value in flag_calls),
        'flag_setter_changed_word': 0xff,
        'first_flag_writer_execution_known': False,
        'cleared_flag_guarantees_inactive_work': False,
        'conditional_release_setter_cases': release_cases,
        'first_release_handler_execution_known': False,
        'release_state5_write_implies_handler5_consumed': False,
        'zero44_layout': {'head': '0x19ee708', 'last_written_slot': '0x19ee70c',
                          'count': '0x19ee710', 'replacement_flag': '0x19ee714'},
        'conditional_dma_span_bytes': dma_span, 'frame_padding_source_bytes_unknown': 7,
        'zero44_dequeue_verified': False, 'uart1_transmit_verified': False,
        'dma1_error_free_verified': False,
        'runtime_table_binding_verified': False, 'runtime_support_verified': False,
        'original_lens_consumption_verified': False,
        'central_history_complete': False, 'capture_verified': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path,
                        default=HERE.parents[1] / 'runtime/analysis/menu-root/cp/cpapp-b.bin')
    args = parser.parse_args()
    print(json.dumps(verify(args.cp), indent=2))
