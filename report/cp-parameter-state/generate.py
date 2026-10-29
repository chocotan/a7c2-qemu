#!/usr/bin/env python3
"""Offline, bounded Thumb proof for the fixed CP4063 setters. No guest execution."""
from pathlib import Path
import hashlib
import json
import re
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from capstone.arm import ARM_OP_IMM, ARM_OP_REG, ARM_OP_MEM

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'runtime/analysis'
REPORT = Path(__file__).resolve().parent
CP_HASH = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
P = 0x165a720
VA_BASE = 0x108000
VA_END = 0x1248b80
IMAGE_BYTES = 0xd64


def generate(cp):
    assert len(cp) == 18090880 and hashlib.sha256(cp).hexdigest() == CP_HASH
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    decoder.detail = True
    schema = [tuple(int(v, 16) for v in row) for row in re.findall(
        r'\{(0x[0-9a-f]+),(0x[0-9a-f]+),(0x[0-9a-f]+)\}',
        (BASE / 'device-models/cp-parameter-batch.c').read_text())]
    assert len(schema) == 190
    table = [struct.unpack_from('<5I', cp, 0x10fab8c - VA_BASE + i * 20)
             for i in range(0x15e)]
    fields, slots, pins, assembly = [], [], [], []
    for index, (opcode, wire_offset, wire_size) in enumerate(schema):
        rows = [r for r in table if r[0] == opcode]
        assert len(rows) == 1 and rows[0][1] & 1
        address = rows[0][1] & ~1
        assert VA_BASE <= address < VA_END
        # Follow every local edge, including branches after an early return.
        pending, insns = [address], {}
        while pending:
            cursor = pending.pop()
            while cursor not in insns:
                assert address <= cursor < min(address + 0x2000, VA_END)
                inst = next(decoder.disasm(cp[cursor - VA_BASE:cursor - VA_BASE + 4], cursor, count=1))
                insns[cursor] = inst
                mn = inst.mnemonic.split('.')[0]
                if (mn == 'bx' and inst.op_str == 'lr') or (mn in ('pop', 'ldm') and 'pc' in inst.op_str):
                    break
                if mn == 'b' or mn in ('beq', 'bne', 'bhi', 'bls', 'bge', 'bgt', 'blt', 'ble', 'bhs', 'blo', 'bmi', 'bpl', 'cbz', 'cbnz'):
                    target = inst.operands[-1].imm
                    if address <= target < address + 0x2000:
                        pending.append(target)
                    if mn == 'b':
                        break
                cursor += inst.size
        end = max(a + ins.size for a, ins in insns.items())
        raw = cp[address - VA_BASE:end - VA_BASE]
        pins.append({'slot': index, 'opcode': opcode, 'va': address, 'size': len(raw),
                     'sha256': hashlib.sha256(raw).hexdigest()})
        assembly.append(f'\nSLOT {index} OP {opcode:04x} WIRE {wire_offset:x} HANDLER {address:x}\n')
        assembly.extend(f'{a:08x}: {ins.bytes.hex():10} {ins.mnemonic} {ins.op_str}\n'
                        for a, ins in sorted(insns.items()))
        registers = {'r0': ('wireptr', 0), 'sp': ('stackptr', 0)}
        writes, old_reads, unsupported, calls = [], [], [], []
        comparison = None
        debug_guard = False
        tail = []
        cursor = address

        def value(op):
            if op.type == ARM_OP_IMM:
                return ('const', op.imm & 0xffffffff)
            if op.type == ARM_OP_REG:
                return registers.get(inst.reg_name(op.reg), ('unknown',))
            return ('unknown',)

        def memory(op):
            base = registers.get(inst.reg_name(op.mem.base), ('unknown',))
            if op.mem.index:
                return ('unknown',)
            if base[0] in ('const', 'wireptr', 'stackptr'):
                return (base[0], base[1] + op.mem.disp)
            return ('unknown',)

        while cursor in insns:
            inst = insns[cursor]
            cursor += inst.size
            m = inst.mnemonic.split('.')[0]
            ops = inst.operands
            if m in ('bx', 'pop') and ('pc' in inst.op_str or inst.op_str == 'lr'):
                break
            if m in ('push', 'pop', 'nop'):
                continue
            if m in ('mov', 'movs', 'movw'):
                registers[inst.reg_name(ops[0].reg)] = value(ops[1])
            elif m == 'movt':
                reg = inst.reg_name(ops[0].reg)
                old = registers.get(reg, ('unknown',))
                registers[reg] = ('const', (old[1] & 0xffff) | (ops[1].imm << 16)) if old[0] == 'const' else ('unknown',)
            elif m in ('add', 'adds', 'addw', 'sub', 'subs', 'subw'):
                reg = inst.reg_name(ops[0].reg)
                left, right = (value(ops[1]), value(ops[2])) if len(ops) == 3 else (registers.get(reg, ('unknown',)), value(ops[1]))
                if left[0] in ('const', 'wireptr', 'stackptr') and right[0] == 'const':
                    registers[reg] = (left[0], left[1] + (-right[1] if m.startswith('sub') else right[1]))
                else:
                    unsupported.append(f'{inst.address:x}: {inst.mnemonic} {inst.op_str}')
                    break
            elif m in ('ldrb', 'ldrsb', 'ldrh', 'ldrsh', 'ldr'):
                reg = inst.reg_name(ops[0].reg)
                if ops[1].type != ARM_OP_MEM:
                    unsupported.append(f'{inst.address:x}: literal load')
                    break
                source = memory(ops[1])
                width = 1 if m in ('ldrb', 'ldrsb') else 2 if m in ('ldrh', 'ldrsh') else 4
                if source[0] == 'wireptr':
                    assert 8 <= source[1] and source[1] + width <= wire_size
                    registers[reg] = ('wire', source[1], width, int(m in ('ldrsb', 'ldrsh')))
                elif source == ('const', 0x1a533d6):
                    registers[reg] = ('debug',)
                elif source[0] == 'const' and P <= source[1] < P + IMAGE_BYTES:
                    old_reads.append([source[1] - P, width])
                    registers[reg] = ('old', source[1] - P, width)
                else:
                    registers[reg] = ('unknown',)
            elif m.startswith(('ldm', 'stm')):
                reg = inst.reg_name(ops[0].reg)
                pointer = registers.get(reg, ('unknown',))
                if pointer[0] not in ('wireptr', 'stackptr', 'const'):
                    unsupported.append(f'{inst.address:x}: unknown bulk pointer')
                    break
                for item in ops[1:]:
                    target_reg = inst.reg_name(item.reg)
                    if m.startswith('ldm') and pointer[0] == 'wireptr':
                        assert 8 <= pointer[1] and pointer[1] + 4 <= wire_size
                        registers[target_reg] = ('wire', pointer[1], 4, 0)
                    elif m.startswith('stm') and pointer[0] == 'const' and P <= pointer[1] <= P + IMAGE_BYTES - 4:
                        expression = registers.get(target_reg, ('unknown',))
                        if expression[0] != 'wire':
                            unsupported.append(f'{inst.address:x}: unknown bulk data')
                            break
                        writes.append((pointer[1] - P, 4, expression))
                    elif pointer[0] != 'stackptr':
                        unsupported.append(f'{inst.address:x}: unsupported bulk direction')
                        break
                    pointer = (pointer[0], pointer[1] + 4)
                if inst.writeback:
                    registers[reg] = pointer
                if unsupported:
                    break
            elif m in ('strb', 'strh', 'str'):
                destination, expression = memory(ops[1]), value(ops[0])
                width = 1 if m == 'strb' else 2 if m == 'strh' else 4
                if destination[0] == 'const' and P <= destination[1] < P + IMAGE_BYTES:
                    assert destination[1] + width <= P + IMAGE_BYTES
                    if expression[0] not in ('wire', 'const', 'bool', 'eq', 'orbool'):
                        unsupported.append(f'{inst.address:x}: unknown write value {expression}')
                        break
                    writes.append((destination[1] - P, width, expression))
                elif destination[0] != 'stackptr':
                    unsupported.append(f'{inst.address:x}: unknown write address')
                    break
            elif m in ('orr', 'orrs') and len(ops) == 3:
                left, right = value(ops[1]), value(ops[2])
                if left[0] == right[0] == 'wire' and left[2:] == right[2:] == (1, 0):
                    expression = ('or', left[1], right[1])
                    registers[inst.reg_name(ops[0].reg)] = expression
                    comparison = (expression, ('const', 0))
                else:
                    unsupported.append(f'{inst.address:x}: unclosed OR')
                    break
            elif m in ('cmp', 'cmn'):
                comparison = (value(ops[0]), value(ops[1]))
            elif m == 'it':
                # The only admitted IT before the log guard is exact bool/eq
                # normalization of one unsigned input byte.
                condition = inst.op_str
                following = insns[cursor]
                dst = following.reg_name(following.operands[0].reg)
                before = registers.get(dst, ('unknown',))
                if comparison and comparison[0] == before and before[0] == 'or' and comparison[1] == ('const', 0) and condition == 'ne' and following.operands[1].type == ARM_OP_IMM and following.operands[1].imm == 1:
                    registers[dst] = ('orbool', before[1], before[2])
                    cursor += following.size
                elif comparison and comparison[0] == before and before[0] == 'wire' and before[2:] == (1, 0) and comparison[1][0] == 'const' and condition in ('ne', 'eq') and following.mnemonic in ('movne', 'moveq', 'movs', 'mov') and following.operands[1].type == ARM_OP_IMM:
                    c, replacement = comparison[1][1], following.operands[1].imm
                    if condition == 'ne' and c == 0 and replacement == 1:
                        registers[dst] = ('bool', before[1])
                    elif condition == 'ne' and c == 1 and replacement == 0:
                        registers[dst] = ('eq', before[1], 1)
                    else:
                        unsupported.append(f'{inst.address:x}: unclosed IT')
                        break
                    cursor += following.size
                else:
                    unsupported.append(f'{inst.address:x}: unclosed IT')
                    break
            elif m in ('lsls', 'lsl') and value(ops[1]) == ('debug',) and ops[-1].type == ARM_OP_IMM and ops[-1].imm == 31:
                registers[inst.reg_name(ops[0].reg)] = ('debug-test',)
            elif m == 'tst' and value(ops[0]) == ('debug',) and ops[1].type == ARM_OP_IMM and ops[1].imm == 1:
                registers['debug_flags'] = ('debug-test',)
            elif m in ('beq', 'bne') and any(v == ('debug-test',) for v in registers.values()):
                debug_guard = True
                tail = [x for a, x in sorted(insns.items()) if a >= inst.address]
                break
            elif m in ('bl', 'blx'):
                calls.append(ops[0].imm if ops[0].type == ARM_OP_IMM else 0)
                for reg in ('r0', 'r1', 'r2', 'r3', 'ip', 'lr'):
                    registers.pop(reg, None)
            else:
                unsupported.append(f'{inst.address:x}: {inst.mnemonic} {inst.op_str}')
                break
        # Closed tails permit only logger calls and no parameter/global writes.
        # Stack argument writes and restored frame registers are observational.
        tail_bad = []
        for ins in tail:
            m = ins.mnemonic.split('.')[0]
            if m in ('bl', 'blx', 'b'):
                if m in ('bl', 'blx') and (ins.operands[0].type != ARM_OP_IMM or ins.operands[0].imm != 0xb4457a):
                    calls.append(ins.operands[0].imm if ins.operands[0].type == ARM_OP_IMM else 0)
            stack_bulk = (ins.address == 0x8db024 and ins.mnemonic == 'stm.w' and ins.op_str == 'r0, {r5, r6, ip}' and insns[0x8db022].mnemonic == 'add' and insns[0x8db022].op_str == 'r0, sp, #0x28')
            if m.startswith(('str', 'stm')) and '[sp' not in ins.op_str and '[r7' not in ins.op_str and not stack_bulk:
                tail_bad.append(f'{ins.address:x}: {ins.mnemonic} {ins.op_str}')
        # Exact branch-only local setter: retain P+2f4 for nonzero input;
        # no read of retained bytes and no invented initial value.
        retain_zero = address == 0x35aa04
        if retain_zero:
            assert hashlib.sha256(raw).hexdigest() == '87f779539b72a88d038d4fb9bea6dac9c9c03f6862c7d307eb38fb05b030ad38'
            writes = [(0x2f8, 4, ('wire', 8, 1, 0)), (0x2f4, 4, ('const', 0))]
            unsupported, tail_bad, calls, old_reads = [], [], [], []
        # A failed proof contributes no stores; partial local write sets are
        # never presented as complete source-local consumption.
        valid = not unsupported and not tail_bad and bool(writes)
        noop = raw == bytes.fromhex('01207047')
        debug_only = debug_guard and not writes and not unsupported and not tail_bad and not calls and not old_reads
        semantic = (valid and not calls and not old_reads) or noop or debug_only
        if not valid:
            writes = []
        start = len(fields)
        for destination, width, expression in writes:
            if expression[0] == 'wire':
                _, source, source_width, signed = expression
                mode, argument = ('SIGN' if signed else 'COPY'), 0
            elif expression[0] == 'const':
                source, source_width, mode, argument = 0, 0, 'CONST', expression[1]
            else:
                source, source_width, mode = expression[1], 1, expression[0].upper()
                argument = expression[2] if len(expression) > 2 else 0
            fields.append({'slot': index, 'wire_offset': source, 'image_offset': destination,
                           'width': width, 'source_width': source_width,
                           'mode': mode, 'argument': argument,
                           'condition_zero': bool(retain_zero and destination == 0x2f4)})
        slots.append({'slot': index, 'opcode': opcode, 'handler_va': address,
                      'first': start, 'count': len(writes), 'config_closed': valid,
                      'semantic_closed': semantic, 'noop': noop, 'calls': sorted(set(calls)),
                      'old_reads': old_reads, 'unclosed': unsupported + tail_bad,
                      'debug_guard': debug_guard})
    return {'cp_sha256': CP_HASH, 'cp_bytes': len(cp), 'fields': fields, 'slots': slots,
            'pins': pins}, ''.join(assembly)


def render(data):
    out = ['/* BEGIN GENERATED SOURCE TABLE: report/cp-parameter-state/generate.py */\n',
           'enum field_mode { COPY, SIGN, CONST, BOOL, EQ, ORBOOL };\n',
           'struct field { uint16_t wire, image; uint8_t width, source_width, mode, condition_zero; uint32_t argument; };\n',
           'struct slot_model { uint16_t first, count; bool semantic; };\n',
           'static const struct field fields[] = {\n']
    for f in data['fields']:
        out.append('    {0x%x,0x%x,%u,%u,%s,%u,UINT32_C(0x%x)}, /* slot %u */\n' %
                   (f['wire_offset'], f['image_offset'], f['width'], f['source_width'], f['mode'], int(f['condition_zero']), f['argument'], f['slot']))
    out.append('};\nstatic const struct slot_model models[CP_PARAMETER_BATCH_SLOTS] = {\n')
    for s in data['slots']:
        out.append('    {%u,%u,%s}, /* %u: %04x -> %x */\n' %
                   (s['first'], s['count'], 'true' if s['semantic_closed'] else 'false', s['slot'], s['opcode'], s['handler_va']))
    out.append('};\n/* END GENERATED SOURCE TABLE */\n')
    return ''.join(out)


if __name__ == '__main__':
    data, asm = generate((BASE / 'menu-root/cp/cpapp-b.bin').read_bytes())
    (REPORT / 'source-map.json').write_text(json.dumps(data, indent=2) + '\n')
    (REPORT / 'handlers.asm').write_text(asm)
    (REPORT / 'generated-table.inc').write_text(render(data))
    print('slots', len(data['slots']), 'config', sum(s['config_closed'] for s in data['slots']),
          'semantic', sum(s['semantic_closed'] for s in data['slots']), 'fields', len(data['fields']))
