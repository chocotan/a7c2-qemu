#!/usr/bin/env python3
"""Static public-CP callback and input-provenance checks; never send requests."""
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

HERE = Path(__file__).resolve().parent
CP = HERE.parents[1] / 'runtime/analysis/menu-root/cp/cpapp-b.bin'
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
BASE = 0x108000


def verify(cp_path=CP):
    blob = cp_path.read_bytes()
    if len(blob) != 18090880 or hashlib.sha256(blob).hexdigest() != CP_SHA:
        raise ValueError('expected the pinned public CP app image')
    manifest = json.loads((HERE / 'source-pins.json').read_text())

    def read(va, size):
        offset = va - BASE
        if offset < 0 or size > len(blob) - offset:
            raise ValueError('window is outside file-backed CP addresses')
        return blob[offset:offset + size]

    def word(va):
        return struct.unpack('<I', read(va, 4))[0]

    for pin in manifest['pins']:
        raw = read(int(pin['cpva'], 16), pin['length'])
        assert raw.hex() == pin['bytes'], pin['name']
        assert hashlib.sha256(raw).hexdigest() == pin['sha256'], pin['name']

    engines = {'thumb': Cs(CS_ARCH_ARM, CS_MODE_THUMB),
               'arm': Cs(CS_ARCH_ARM, CS_MODE_ARM)}

    def exact(va, mnemonic, operands, isa='thumb'):
        ins = next(engines[isa].disasm(read(va, 4), va))
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands), hex(va)

    def call(va, target, isa='thumb'):
        exact(va, 'bl', '#' + hex(target), isa)

    # Callback record 8 uses selector bytes; its incoming r0 is caller's r2.
    assert 0xdeb8bc + 8 * 16 == 0xdeb93c
    record = read(0xdeb93c, 16)
    assert struct.unpack_from('<I', record)[0] == 0x3b0675
    assert record[4:] == bytes([0, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
    assert word(0xdeb8bc) == 0x9a541d
    exact(0x3b0674, 'push', '{r4, r5, r6, r7, lr}')
    exact(0x3af500, 'push', '{r4, r5, r6, r7, lr}')
    exact(0x3af516, 'mov', 'r5, r2')
    exact(0x3af526, 'ldrb.w', 'r0, [r0, #0x1a4]')
    call(0x3af530, 0x9a7fe2)
    exact(0x3af54e, 'movs', 'r6, #3')
    exact(0x3af55e, 'ldr.w', 'r6, [r1, r0, lsl #2]')
    mapping = struct.unpack('<4I', read(0x3af818, 16))
    assert mapping == (5, 4, 6, 7)
    exact(0x3af5a4, 'movw', 'r4, #0xb8bc')
    exact(0x3af5b2, 'movt', 'r4, #0xde')
    exact(0x3af5be, 'adds', 'r0, r6, r4')
    exact(0x3af5c0, 'ldrb', 'r0, [r0, #4]')
    exact(0x3af5c2, 'cbz', 'r0, #0x3af5c8')
    exact(0x3af5c4, 'mov', 'r0, r5')
    exact(0x3af5c6, 'blx', 'r1')
    exact(0x3af5c8, 'ldr', 'r1, [r4, #0x10]!')

    selector_cases = 0
    for bank_byte in range(256):
        for local_nonzero in (False, True):
            for helper_nonzero in (False, True):
                if bank_byte == 0:
                    selector = 0
                elif bank_byte == 5:
                    selector = 2 if helper_nonzero else 1
                elif local_nonzero:
                    selector = 3
                elif bank_byte <= 4:
                    selector = mapping[bank_byte - 1]
                else:
                    selector = 8
                expected = bank_byte == 5 or (bank_byte == 2 and not local_nonzero)
                assert bool(record[4 + selector]) == expected
                selector_cases += 1

    # These direct drivers preserve their input pointer into walker r2.
    exact(0x99248a, 'mov', 'r6, r0')
    exact(0x99249e, 'ldr', 'r1, [r6, #0xc]')
    exact(0x9924aa, 'ldrb.w', 'r1, [r1, #0x328]')
    exact(0x9924ae, 'lsls', 'r5, r1, #8')
    exact(0x99251c, 'mov', 'r2, r6')
    call(0x992526, 0x3af500)
    exact(0x992568, 'mov', 'r2, r6')
    call(0x992572, 0x3af500)
    exact(0x993dba, 'mov', 'r5, r0')
    call(0x993df0, 0x99d494)
    exact(0x993df4, 'movs', 'r1, #0')
    exact(0x993df6, 'mov', 'r2, r5')
    call(0x993df8, 0x3af500)
    exact(0x3b09ce, 'cmp', 'r0, #7')
    exact(0x3b09d0, 'bne', '#0x3b0a14')
    exact(0x3b09f8, 'movs', 'r1, #0xff')
    exact(0x3b0a00, 'strb.w', 'r1, [r0, #0x17c]')

    # The copied context and submitted original pointer have distinct roles.
    exact(0x991e20, 'mov', 'r8, r0')
    exact(0x991e26, 'movs', 'r2, #0xc8')
    exact(0x991e2c, 'mov', 'r1, r8')
    exact(0x991e2e, 'mov', 'r0, sb')
    exact(0x991e30, 'blx', '#0x61e60c')
    exact(0x991efe, 'movw', 'r2, #0x3eed')
    exact(0x991f12, 'movw', 'r1, #0xe499')
    exact(0x991f16, 'mov', 'r2, r8')
    call(0x991f20, 0x50ff1c)
    exact(0x99424c, 'movw', 'r0, #0x8018')
    exact(0x994250, 'movt', 'r0, #0x18b')
    exact(0x994260, 'movw', 'r0, #0x8038')
    exact(0x994264, 'movt', 'r0, #0x18b')
    exact(0x39e4a2, 'mov', 'fp, r0')
    exact(0x39e5a0, 'mov', 'r0, fp')
    call(0x39e5a2, 0x99247c)
    exact(0x39ec92, 'mov', 'r0, fp')
    call(0x39ec94, 0x99247c)
    exact(0x39e372, 'mov', 'r4, r0')
    exact(0x39e458, 'movw', 'r2, #0x5dcd')
    exact(0x39e46c, 'movw', 'r1, #0x3db3')
    exact(0x39e470, 'mov', 'r2, r4')
    call(0x39e47a, 0x50ff1c)
    exact(0x993eec, 'ldr', 'r2, [r0, #8]')
    exact(0x993eee, 'mov', 'r0, r1')
    exact(0x993ef0, 'bx', 'r2')
    exact(0x805dcc, 'ldr', 'r3, [r0, #8]')
    exact(0x805dce, 'mov', 'r0, r1')
    exact(0x805dd0, 'mov', 'r1, r2')
    exact(0x805dd2, 'bx', 'r3')
    exact(0x50ff34, 'ldm.w', 'r2, {r0, r3, r4, r5, r6}')
    exact(0x50ff38, 'movs', 'r2, #0x1c')
    exact(0x50ff3a, 'stm.w', 'ip, {r0, r3, r4, r5, r6}')
    exact(0x50ff3e, 'strd', 'sl, r8, [sp, #0x24]')
    exact(0x50ff42, 'ldr.w', 'r0, [sb, #0x18]')
    exact(0x50ff46, 'blx', '#0x5ecb84')
    assert struct.calcsize('<7I') == 28
    exact(0x510046, 'ldr', 'r0, [r4, #0x18]')
    exact(0x51004a, 'mov.w', 'r2, #-1')
    exact(0x51004e, 'blx', '#0x5ed998')
    exact(0x51007c, 'ldrd', 'r3, r6, [sp, #4]')
    exact(0x510080, 'ldrd', 'r1, r2, [sp, #0x18]')
    exact(0x510094, 'blx', 'r3')
    exact(0x510096, 'b', '#0x510046')

    # Native message-buffer paths copy bytes, including the ring wrap case.
    exact(0x5ecb8c, 'mov', 'sb, r1', 'arm')
    exact(0x5ecb94, 'mov', 'fp, r2', 'arm')
    exact(0x5ecd10, 'mov', 'r2, fp', 'arm')
    call(0x5ecd28, 0x61e60c, 'arm')
    exact(0x5ece68, 'str', 'fp, [r3, r0]', 'arm')
    call(0x5ecea8, 0x61e60c, 'arm')
    exact(0x5ececc, 'mov', 'r2, fp', 'arm')
    call(0x5eced0, 0x61e60c, 'arm')
    call(0x5edbd0, 0x5ec480, 'arm')
    call(0x5ec4e4, 0x61e60c, 'arm')
    call(0x5ec544, 0x61e60c, 'arm')
    call(0x5edc18, 0x61e60c, 'arm')

    # One upstream passes a fixed original context, subject to a mask bit.
    call(0x4d9a7e, 0xb2e8e0)
    exact(0x4d9a82, 'movw', 'r4, #0x19ac')
    exact(0x4d9ac8, 'lsls', 'r1, r0, #0x1e')
    exact(0x4d9aca, 'bmi', '#0x4d9b0a')
    exact(0x4d9af6, 'movw', 'r0, #0xa85c')
    exact(0x4d9afc, 'movt', 'r0, #0x1a6')
    call(0x4d9b00, 0x991e12)

    # Registry type 4, request selector 5 and AP message type 5 are distinct.
    exact(0x131cb6, 'movw', 'r1, #0xedf0')
    exact(0x131cba, 'movs', 'r0, #4')
    exact(0x131cbc, 'mov.w', 'r2, #0x100')
    exact(0x131cc0, 'movt', 'r1, #0x10f')
    call(0x131cc4, 0xb22f1e)
    exact(0xb22f3a, 'strd', 'r1, r2, [r3, #4]')
    assert 0x110f7a4 + 4 * 12 == 0x110f7d4
    assert struct.unpack('<H', read(0x110f7d4, 2))[0] == 4
    assert 0x10fedf0 + 0xe0 * 4 == 0x10ff170
    assert word(0x10ff170) == 0x1b16270
    assert struct.unpack('<2I', read(0xe795b0, 8)) == (5, 0xb2491f)
    exact(0x4b7826, 'and', 'r0, r5, #0xfe')
    exact(0x4b782a, 'cmp', 'r0, #0xfe')
    call(0x4b7836, 0xb25aa8)
    exact(0x4b7972, 'ldr', 'r6, [r0, #4]')
    exact(0x4b797c, 'str', 'r0, [sp]')
    exact(0x4b797e, 'mov', 'r0, r4')
    exact(0x4b7980, 'blx', 'r6')
    exact(0xb24930, 'ldr', 'r5, [r7, #8]')
    exact(0xb24938, 'adds', 'r3, r2, r5')
    exact(0xb2493a, 'cmp', 'r3, r6')
    exact(0xb2493c, 'bls', '#0xb24964')
    exact(0xb2496a, 'cmp', 'r1, #0xff')
    exact(0xb2496c, 'ldr.w', 'r6, [r0, r2, lsl #2]')
    exact(0xb24974, 'add.w', 'r1, r4, #0x30')
    exact(0xb2497c, 'blx', '#0x61e60c')
    exact(0xb24980, 'mov', 'r0, r6')
    exact(0xb24986, 'blx', '#0x61e60c')
    call(0xb2499e, 0x9944f6)
    assert 0xe0 + 1 <= 0x100  # Only this bounded one-byte case is described.

    return {'scope': 'static selector, callback and one request-writer binding only',
            'cp_sha256': CP_SHA, 'source_windows_verified': len(manifest['pins']),
            'window_bytes': sum(pin['length'] for pin in manifest['pins']),
            'conditional_selector_classes_checked': selector_cases,
            'enabled_callback_selectors': [1, 2, 4],
            'direct_driver_calls_verified': 3, 'software_job_record_bytes': 28,
            'first_job_event_object': '0x18b8018',
            'second_job_event_object': '0x18b8038',
            'original_context_lifetime_verified': False,
            'runtime_job_delivery_verified': False,
            'first_callback_execution_known': False,
            'first_reset_byte_write_known': False,
            'runtime_root_binding_verified': False,
            'adjustment_request_observed': False,
            'adjustment_side_effects_fully_modeled': False,
            'history_complete': False, '302c_native_verified': False,
            'capture_verified': False}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
