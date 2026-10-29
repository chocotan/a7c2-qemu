#!/usr/bin/env python3
"""Recover only constant local stores in the pinned CP common initializer.

This is a finite straight-line source check, not a CP emulator. It stops before
8db980's AE tail call and models only the source-verified zero helper 61ed00.
"""
import argparse
import hashlib
import json
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_SP

OWN = Path(__file__).resolve().parent
BASE = 0x108000
START, END = 0x8db6a2, 0x8db980
SOURCE_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
WINDOW_SHA = '66c4be97db5c9d3296965f6ab47881e0c18160b125a0079af202c62cf66d3944'
ROOT, IMAGE_BYTES = 0x165a720, 0xd64
STACK = 0x70000000


def require(ok, why):
    if not ok:
        raise ValueError(why)


def extract(path):
    raw = path.read_bytes()
    require(len(raw) == 18090880 and hashlib.sha256(raw).hexdigest() == SOURCE_SHA,
            'not the pinned public CP image')
    code = raw[START-BASE:END-BASE]
    require(hashlib.sha256(code).hexdigest() == WINDOW_SHA, 'common initializer window mismatch')
    require(hashlib.sha256(raw[0x61ed00-BASE:0x61ed00-BASE+312]).hexdigest() ==
            '08db00a35b3411ecffd440d6af222556dbb9f6f386d0fabac7be91a5b6d9281b',
            'source zero-helper semantics changed')
    machine = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    machine.detail = True
    instructions = list(machine.disasm(code, START))
    require(len(instructions) == 195 and instructions[-1].address + instructions[-1].size == END,
            'initializer instruction coverage mismatch')
    registers = {ARM_REG_R0: ROOT, ARM_REG_SP: STACK}
    memory, writes = {}, []
    pc = START

    def value(operand):
        require(not operand.shift.type, 'unexpected shifted operand')
        if operand.type == ARM_OP_IMM:
            return operand.imm & 0xffffffff
        require(operand.type == ARM_OP_REG, 'unsupported operand')
        return registers.get(operand.reg)

    def location(operand):
        require(operand.type == ARM_OP_MEM and not operand.mem.index, 'unsupported indexed memory')
        address = registers.get(operand.mem.base)
        require(address is not None and 0 <= address + operand.mem.disp <= 0xffffffff,
                'unknown or wrapped address')
        return address + operand.mem.disp

    def store(address, size, number):
        require((ROOT <= address and address + size <= ROOT + IMAGE_BYTES) or
                STACK - 128 <= address <= address + size <= STACK, 'write outside root/stack')
        if ROOT <= address < ROOT + IMAGE_BYTES:
            require(number is not None, 'root store depends on an unknown input')
            writes.append({'pc': hex(pc), 'offset': address-ROOT, 'bytes': size,
                           'data': (number & ((1 << (8*size))-1)).to_bytes(size, 'little').hex()})
        for index in range(size):
            memory[address+index] = None if number is None else (number >> (8*index)) & 255

    def read(address, size):
        require((ROOT <= address and address + size <= ROOT + IMAGE_BYTES) or
                STACK - 128 <= address <= address + size <= STACK, 'read outside root/stack')
        parts = [memory.get(address+i) for i in range(size)]
        return None if any(p is None for p in parts) else sum(p << (8*i) for i, p in enumerate(parts))

    for instruction in instructions:
        pc = instruction.address
        op = instruction.operands
        name = instruction.mnemonic.split('.')[0]
        if name in ('push', 'pop'):
            require(all(o.type == ARM_OP_REG for o in op), 'unexpected stack operand')
            address = registers[ARM_REG_SP]
            if name == 'push':
                address -= 4*len(op)
                for i, operand in enumerate(op):
                    store(address+4*i, 4, registers.get(operand.reg))
            else:
                for i, operand in enumerate(op):
                    registers[operand.reg] = read(address+4*i, 4)
                address += 4*len(op)
            registers[ARM_REG_SP] = address
        elif name in ('mov', 'movs', 'movw'):
            registers[op[0].reg] = value(op[1])
        elif name in ('add', 'adds', 'addw'):
            a, b = value(op[1]), value(op[2])
            registers[op[0].reg] = None if a is None or b is None else (a+b) & 0xffffffff
        elif name in ('str', 'strb', 'strh', 'strd', 'ldr', 'ldrd'):
            double = name in ('strd', 'ldrd')
            mem = op[2] if double else op[1]
            address = location(mem)
            size = 1 if name == 'strb' else 2 if name == 'strh' else 4
            if name.startswith('str'):
                store(address, size, value(op[0]))
                if double:
                    store(address+4, 4, value(op[1]))
            else:
                registers[op[0].reg] = read(address, size)
                if double:
                    registers[op[1].reg] = read(address+4, 4)
            if instruction.writeback:
                registers[mem.mem.base] = address if op[-1].type != ARM_OP_IMM else address+op[-1].imm
        elif name == 'blx':
            require(op[0].type == ARM_OP_IMM and op[0].imm == 0x61ed00,
                    'unclosed call in local store phase')
            address, size = registers.get(ARM_REG_R0), registers.get(ARM_REG_R1)
            require(address is not None and size is not None and 0 < size <= IMAGE_BYTES,
                    'unknown zero-helper range')
            store(address, size, 0)
            for register in (ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3):
                registers[register] = None
        else:
            raise ValueError(f'unclosed instruction {pc:x}: {instruction.mnemonic} {instruction.op_str}')
    known = sorted(address-ROOT for address, number in memory.items()
                   if ROOT <= address < ROOT+IMAGE_BYTES and number is not None)
    require(known and all(memory[ROOT+i] == 0 for i in range(0x1c8, 0x1d0)), 'reset store not closed')
    ranges, data = [], []
    for offset in known:
        if ranges and ranges[-1]['offset'] + ranges[-1]['bytes'] == offset:
            ranges[-1]['bytes'] += 1
        else:
            ranges.append({'offset': offset, 'bytes': 1, 'data_offset': len(data)})
        data.append(memory[ROOT+offset])
    return {'scope': 'constant local writes before AE tail call; not complete initialization/publication',
            'source_sha256': SOURCE_SHA, 'window_start': hex(START), 'window_end': hex(END),
            'window_sha256': WINDOW_SHA, 'instructions': len(instructions),
            'known_bytes': len(known), 'ranges': ranges, 'data': bytes(data).hex(), 'writes': writes,
            'initialization_complete': False, 'published': False, 'capture_verified': False}


def render(trace):
    data = bytes.fromhex(trace['data'])
    lines = ['/* Generated from CP8db6a2..8db980; AE tail call excluded. */',
             'struct common_init_range { uint16_t offset, bytes, data; };',
             'static const unsigned char common_init_values[] = {']
    lines += ['    '+','.join(f'0x{b:02x}' for b in data[i:i+16])+',' for i in range(0, len(data), 16)]
    lines += ['};', 'static const struct common_init_range common_init_ranges[] = {']
    lines += [f"    {{0x{r['offset']:x},{r['bytes']},{r['data_offset']}}}," for r in trace['ranges']]
    lines += ['};', f'_Static_assert(sizeof(common_init_values)=={trace["known_bytes"]}u,"source local-store coverage");', '']
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
    print(json.dumps({k: trace[k] for k in ('instructions','known_bytes','initialization_complete','published','capture_verified')}))


if __name__ == '__main__':
    main()
