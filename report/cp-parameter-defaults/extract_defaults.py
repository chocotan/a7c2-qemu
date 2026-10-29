#!/usr/bin/env python3
"""Extract constant local writes from the pinned CP flag-0 default path only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
from capstone.arm import (ARM_CC_AL, ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,
                          ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3,
                          ARM_REG_IP, ARM_REG_LR, ARM_REG_PC, ARM_REG_SP)

OWN = Path(__file__).resolve().parent
BASE, ROOT, IMAGE_BYTES, STACK = 0x108000, 0x165a720, 0xd64, 0x70000000
START, SERIALIZER, END = 0x8db9bc, 0x8dc2c2, 0x8dc67e
SOURCE_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
WINDOWS = (
    (START, SERIALIZER, 606, '0a576899cd7391403b7508813ed7bad8bfe2a3d990f529554e429b6acc3d1188'),
    (SERIALIZER, END, 393, '7803843c7c4f2122c80eeda042eff77b5344d70ce4334bb0df6c18f92de3c32c'))
HELPERS = (
    (0x61ed00, 312, '08db00a35b3411ecffd440d6af222556dbb9f6f386d0fabac7be91a5b6d9281b'),
    (0x61e60c, 576, '0b43ce9d7e3069da0c5bd26e230220c422906140bf9988b85999e3a4c3de809b'))
VOLATILE = (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_IP)


def require(ok, why):
    if not ok:
        raise ValueError(why)


def decode(raw):
    require(len(raw) == 18090880 and hashlib.sha256(raw).hexdigest() == SOURCE_SHA,
            'not the pinned public CP image')
    machine = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    machine.detail = True
    instructions = []
    for start, end, count, digest in WINDOWS:
        code = raw[start-BASE:end-BASE]
        require(hashlib.sha256(code).hexdigest() == digest, 'default source window mismatch')
        part = list(machine.disasm(code, start))
        require(len(part) == count and sum(i.size for i in part) == end-start,
                'default instruction coverage mismatch')
        instructions.extend(part)
    for start, size, digest in HELPERS:
        require(hashlib.sha256(raw[start-BASE:start-BASE+size]).hexdigest() == digest,
                'source helper semantics changed')
    return instructions


def seed_common(path):
    spec = importlib.util.spec_from_file_location('cp_default_common_source',
             OWN.parent/'cp-parameter-initializer/extract_common.py')
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    trace = common.extract(path)
    cached = json.loads((OWN.parent/'cp-parameter-initializer/common-local-stores.json').read_text())
    require(trace == cached and trace['known_bytes'] == 694, 'common source/cache mismatch')
    data = bytes.fromhex(trace['data'])
    return {ROOT+r['offset']+i: data[r['data_offset']+i]
            for r in trace['ranges'] for i in range(r['bytes'])}


def pack(memory, offsets):
    ranges, data = [], []
    for offset in sorted(offsets):
        if ranges and ranges[-1]['offset']+ranges[-1]['bytes'] == offset:
            ranges[-1]['bytes'] += 1
        else:
            ranges.append({'offset': offset, 'bytes': 1, 'data_offset': len(data)})
        data.append(memory[ROOT+offset])
    return ranges, bytes(data).hex()


def trace_local(instructions, seed):
    """Finite constant propagation; unknown saved registers may only flow to stack."""
    require(all(ROOT <= a < ROOT+IMAGE_BYTES and isinstance(v, int) and 0 <= v <= 255
                for a, v in seed.items()), 'invalid common seed')
    registers = {ARM_REG_R0: ROOT, ARM_REG_SP: STACK}
    memory, writes, calls, touched, visited = dict(seed), [], [], set(), set()
    by_pc = {i.address: i for i in instructions}
    pc, return_pc, finished = START, None, False

    def checked(address, size):
        require(address is not None and size > 0 and 0 <= address <= address+size <= 0x100000000,
                f'unknown or wrapped address at {pc:x}')
        require((ROOT <= address < address+size <= ROOT+IMAGE_BYTES) or
                STACK-1024 <= address < address+size <= STACK, f'out-of-bounds memory at {pc:x}')
        return address

    def value(operand):
        require(not operand.shift.type and not operand.subtracted, 'unsupported operand shift')
        if operand.type == ARM_OP_IMM:
            return operand.imm & 0xffffffff
        require(operand.type == ARM_OP_REG, 'unsupported value operand')
        return registers.get(operand.reg)

    def location(operand):
        require(operand.type == ARM_OP_MEM and not operand.mem.index and not operand.shift.type
                and not operand.subtracted, 'unsupported indexed memory')
        base = registers.get(operand.mem.base)
        require(base is not None and 0 <= base+operand.mem.disp <= 0xffffffff,
                f'unknown or wrapped address at {pc:x}')
        return base+operand.mem.disp

    def read(address, size):
        checked(address, size)
        parts = [memory.get(address+i) for i in range(size)]
        return None if any(p is None for p in parts) else sum(p << (8*i) for i, p in enumerate(parts))

    def store(address, size, number):
        checked(address, size)
        if ROOT <= address < ROOT+IMAGE_BYTES:
            require(number is not None, f'root store depends on an unknown input at {pc:x}')
            data = (number & ((1 << (8*size))-1)).to_bytes(size, 'little')
            writes.append({'pc': hex(pc), 'offset': address-ROOT, 'bytes': size, 'data': data.hex()})
            touched.update(range(address-ROOT, address-ROOT+size))
        for i in range(size):
            memory[address+i] = None if number is None else (number >> (8*i)) & 255

    for _ in range(len(instructions)):
        require(pc in by_pc and pc not in visited, f'unclosed/repeated instruction {pc:x}')
        visited.add(pc)
        ins = by_pc[pc]
        require(ins.cc == ARM_CC_AL, f'conditional instruction at {pc:x}')
        op, name, next_pc = ins.operands, ins.mnemonic.split('.')[0], pc+ins.size
        if name in ('push', 'pop'):
            require(all(o.type == ARM_OP_REG for o in op), 'unsupported stack operands')
            address = registers[ARM_REG_SP] - (4*len(op) if name == 'push' else 0)
            for i, operand in enumerate(op):
                if name == 'push':
                    store(address+4*i, 4, registers.get(operand.reg))
                else:
                    registers[operand.reg] = read(address+4*i, 4)
            registers[ARM_REG_SP] = address if name == 'push' else address+4*len(op)
            if any(o.reg == ARM_REG_PC for o in op):
                require(pc == SERIALIZER-2 and return_pc is None and registers[ARM_REG_SP] == STACK,
                        'unexpected outer return')
                finished = True
                break
        elif name in ('mov', 'movs', 'movw', 'movt'):
            number = value(op[1])
            if name == 'movt':
                old = registers.get(op[0].reg)
                number = None if old is None or number is None else (old & 0xffff) | (number << 16)
            registers[op[0].reg] = number
        elif name in ('add', 'adds', 'addw', 'sub', 'subs', 'subw'):
            a, b = value(op[-2]), value(op[-1])
            result = None if a is None or b is None else a + (-b if name.startswith('sub') else b)
            require(result is None or 0 <= result <= 0xffffffff, f'wrapped arithmetic at {pc:x}')
            registers[op[0].reg] = result
        elif name in ('lsr', 'lsrs'):
            a, shift = value(op[1]), value(op[2])
            require(shift is not None and 0 <= shift <= 32, 'unsupported right shift')
            registers[op[0].reg] = None if a is None else a >> shift
        elif name in ('str', 'strb', 'strh', 'strd', 'ldr', 'ldrb', 'ldrh', 'ldrd'):
            double = name in ('strd', 'ldrd')
            mem = op[2] if double else op[1]
            address = location(mem)
            size = 1 if name.endswith('b') else 2 if name.endswith('h') else 4
            for i in range(2 if double else 1):
                if name.startswith('str'):
                    store(address+4*i, size, value(op[i]))
                else:
                    registers[op[i].reg] = read(address+4*i, size)
            if ins.writeback:
                updated = address + (value(op[-1]) if op[-1].type == ARM_OP_IMM else 0)
                require(0 <= updated <= 0xffffffff, 'wrapped writeback')
                registers[mem.mem.base] = updated
        elif name in ('bl', 'blx'):
            require(op[0].type == ARM_OP_IMM, 'unknown call target')
            target = op[0].imm
            registers[ARM_REG_LR] = next_pc | 1
            if name == 'bl' and target == SERIALIZER:
                require(return_pc is None and pc == 0x8dc2aa, 'unexpected serializer call')
                calls.append({'pc': hex(pc), 'target': hex(target), 'kind': 'serializer'})
                return_pc, next_pc = next_pc, SERIALIZER
            else:
                require(name == 'blx' and target in (0x61ed00, 0x61e60c), 'unclosed helper call')
                address = registers.get(ARM_REG_R0)
                size = registers.get(ARM_REG_R1 if target == 0x61ed00 else ARM_REG_R2)
                require(size is not None and 0 < size <= IMAGE_BYTES, 'unknown helper length')
                checked(address, size)
                call = {'pc': hex(pc), 'target': hex(target), 'offset': address-ROOT, 'bytes': size}
                if target == 0x61ed00:
                    call['kind'] = 'zero'
                    store(address, size, 0)
                else:
                    source = registers.get(ARM_REG_R1)
                    require(pc == 0x8dc2b6 and address == ROOT+0x870 and size == 0xb0,
                            'unexpected copy contract')
                    number = read(source, size)
                    require(number is not None, 'copy depends on unknown source bytes')
                    require(source+size <= address or address+size <= source, 'overlapping memcpy')
                    call.update(kind='copy', source_stack_offset=source-STACK)
                    store(address, size, number)
                calls.append(call)
                for reg in VOLATILE:
                    registers[reg] = None
        elif name == 'bx':
            require(pc == END-2 and op[0].type == ARM_OP_REG and op[0].reg == ARM_REG_LR
                    and return_pc is not None and registers.get(ARM_REG_LR) == return_pc | 1,
                    'unexpected serializer return')
            next_pc, return_pc = return_pc, None
            for reg in VOLATILE:
                registers[reg] = None
        else:
            raise ValueError(f'unclosed instruction {pc:x}: {ins.mnemonic} {ins.op_str}')
        pc = next_pc
    require(finished and len(visited) == len(instructions) == 999, 'incomplete default source traversal')
    require(sum(c['kind'] == 'zero' for c in calls) == 18 and len(calls) == 20,
            'helper coverage mismatch')
    known = {a-ROOT for a, v in memory.items() if ROOT <= a < ROOT+IMAGE_BYTES and v is not None}
    ranges, data = pack(memory, touched)
    unknown_ranges = []
    for offset in sorted(set(range(IMAGE_BYTES))-known):
        if unknown_ranges and unknown_ranges[-1]['offset']+unknown_ranges[-1]['bytes'] == offset:
            unknown_ranges[-1]['bytes'] += 1
        else:
            unknown_ranges.append({'offset': offset, 'bytes': 1})
    return {'scope': 'flag-0 constant default local writes; common AE tail and publication excluded',
            'source_sha256': SOURCE_SHA, 'root': hex(ROOT), 'image_bytes': IMAGE_BYTES,
            'windows': [{'start': hex(s), 'end': hex(e), 'instructions': n, 'sha256': h}
                        for s, e, n, h in WINDOWS],
            'helpers': [{'start': hex(s), 'bytes': n, 'sha256': h} for s, n, h in HELPERS],
            'instructions': len(visited), 'common_known_bytes': len(seed),
            'default_written_bytes': len(touched), 'composed_known_bytes': len(known),
            'composed_unknown_bytes': IMAGE_BYTES-len(known), 'composed_unknown_ranges': unknown_ranges,
            'ranges': ranges, 'data': data, 'writes': writes, 'calls': calls,
            'initialization_complete': False, 'business_ready': False, 'generation_ready': False,
            'published': False, 'capture_verified': False}


def extract(path):
    return trace_local(decode(path.read_bytes()), seed_common(path))


def render(trace):
    data = bytes.fromhex(trace['data'])
    lines = ['/* Generated from pinned CP flag-0 default initializer and serializer.',
             f' * {trace["instructions"]} instructions; {trace["default_written_bytes"]} default-written bytes;',
             f' * common + default: {trace["composed_known_bytes"]}/{IMAGE_BYTES} known bytes.',
             ' * Apply only to the verified flag-0 path after common local writes.',
             ' * AE callback, initialization completion, generation and publication excluded. */',
             'struct default_init_range { uint16_t offset, bytes, data; };',
             'static const unsigned char default_init_values[] = {']
    lines += ['    '+','.join(f'0x{b:02x}' for b in data[i:i+16])+',' for i in range(0, len(data), 16)]
    lines += ['};', 'static const struct default_init_range default_init_ranges[] = {']
    lines += [f"    {{0x{r['offset']:x},{r['bytes']},{r['data_offset']}}}," for r in trace['ranges']]
    lines += ['};', f'_Static_assert(sizeof(default_init_values)=={trace["default_written_bytes"]}u,"source default-store coverage");', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=OWN.parents[1]/'runtime/analysis/menu-root/cp/cpapp-b.bin')
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--include', type=Path)
    args = parser.parse_args()
    trace = extract(args.source)
    if args.trace:
        with args.trace.open('x') as out:
            out.write(json.dumps(trace, indent=2)+'\n')
    if args.include:
        with args.include.open('x') as out:
            out.write(render(trace))
    print(json.dumps({k: trace[k] for k in ('instructions', 'default_written_bytes',
          'composed_known_bytes', 'composed_unknown_bytes', 'initialization_complete', 'published')}))


if __name__ == '__main__':
    main()
