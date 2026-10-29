"""Run with python3 -B -m unittest discover -s report/cp-parameter-defaults -v."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from capstone.arm import (ARM_CC_EQ, ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG,
                          ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3,
                          ARM_REG_R4, ARM_REG_R6, ARM_REG_R8)

OWN = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('cp_default_source_test', OWN/'extract_defaults.py')
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)
SOURCE = OWN.parents[1]/'runtime/analysis/menu-root/cp/cpapp-b.bin'
INCLUDE = OWN.parents[1]/'runtime/analysis/device-models/cp-parameter-default-init.inc'


def unpack(trace):
    data = bytes.fromhex(trace['data'])
    return {r['offset']+i: data[r['data_offset']+i]
            for r in trace['ranges'] for i in range(r['bytes'])}


def operand(kind, number, displacement=0):
    fields = {'type': kind, 'shift': SimpleNamespace(type=0), 'subtracted': False}
    fields.update({'reg': number} if kind == ARM_OP_REG else {'imm': number} if kind == ARM_OP_IMM
                  else {'mem': SimpleNamespace(base=number, index=0, disp=displacement)})
    return SimpleNamespace(**fields)


class SourceDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest('pinned public CP image is not distributed; provide it at the documented path')
        cls.raw = SOURCE.read_bytes()
        cls.instructions = extractor.decode(cls.raw)
        cls.seed = extractor.seed_common(SOURCE)
        cls.trace = extractor.extract(SOURCE)

    def changed(self, address, instructions=None, **changes):
        instructions = list(self.instructions if instructions is None else instructions)
        index = next(i for i, ins in enumerate(instructions) if ins.address == address)
        old = instructions[index]
        fields = {key: getattr(old, key) for key in ('address', 'size', 'cc', 'mnemonic', 'op_str', 'operands', 'writeback')}
        fields.update(changes)
        instructions[index] = SimpleNamespace(**fields)
        return instructions

    def test_reproduce_entire_trace_and_include(self):
        self.assertEqual(self.trace, json.loads((OWN/'default-local-stores.json').read_text()))
        self.assertEqual(extractor.render(self.trace), INCLUDE.read_text())
        self.assertEqual((self.trace['instructions'], self.trace['default_written_bytes'],
                          self.trace['composed_known_bytes'], self.trace['composed_unknown_bytes']),
                         (999, 2223, 2913, 515))
        self.assertEqual((len(self.trace['ranges']), len(self.trace['writes'])), (157, 515))

    def test_source_and_each_code_helper_pin_reject_mutation(self):
        with self.assertRaisesRegex(ValueError, 'pinned public CP'):
            extractor.decode(self.raw[:-1])
        for address in (extractor.START, extractor.SERIALIZER, 0x61ed00, 0x61e60c):
            with self.subTest(address=hex(address)):
                mutated = bytearray(self.raw)
                mutated[address-extractor.BASE] ^= 1
                with self.assertRaisesRegex(ValueError, 'pinned public CP'):
                    extractor.decode(mutated)
                # Isolate each secondary pin after deliberately accepting the altered whole-image hash.
                with patch.object(extractor, 'SOURCE_SHA', hashlib.sha256(mutated).hexdigest()):
                    with self.assertRaisesRegex(ValueError, 'window mismatch|helper semantics changed'):
                        extractor.decode(mutated)

    def test_final_values_and_default_only_mask(self):
        defaults = unpack(self.trace)
        common = {a-extractor.ROOT: b for a, b in self.seed.items()}
        composed = common | defaults
        expected = {0x28: 5, 0x2c: 1, 0x30: 60, 0xd8: 0x0b101090, 0xdc: 0x0b101090,
                    0x668: 5, 0x670: 5, 0x678: 4, 0x67c: 8, 0x684: 1, 0xd5c: 0, 0xd60: 0}
        for offset, number in expected.items():
            self.assertEqual(bytes(composed[offset+i] for i in range(4)), number.to_bytes(4, 'little'))
        self.assertEqual(bytes(composed[0x1c8+i] for i in range(8)), bytes(8))
        self.assertTrue(all(0x1c8+i not in defaults for i in range(8)))
        self.assertEqual(bytes(defaults[0x870+i] for i in range(0xb0)), bytes(0xb0))
        self.assertEqual(set(common) & set(defaults), set(range(0xd5c, 0xd60)))
        unknown = {r['offset']+i for r in self.trace['composed_unknown_ranges'] for i in range(r['bytes'])}
        self.assertEqual(set(range(extractor.IMAGE_BYTES))-set(composed), unknown)
        self.assertTrue(all(not self.trace[key] for key in ('initialization_complete', 'business_ready',
                        'generation_ready', 'published', 'capture_verified')))

    def test_all_recorded_writes_reconstruct_exact_default_table(self):
        written = {}
        for write in self.trace['writes']:
            data = bytes.fromhex(write['data'])
            self.assertEqual(len(data), write['bytes'])
            self.assertTrue(extractor.START <= int(write['pc'], 16) < extractor.SERIALIZER)
            self.assertTrue(0 <= write['offset'] < write['offset']+len(data) <= extractor.IMAGE_BYTES)
            written.update({write['offset']+i: b for i, b in enumerate(data)})
        self.assertEqual(written, unpack(self.trace))
        self.assertEqual([c['kind'] for c in self.trace['calls']], ['zero']*18+['serializer', 'copy'])
        self.assertEqual(self.trace['calls'][-1]['source_stack_offset'], -216)

    def test_seed_unwritten_bytes_stay_unknown_and_poison_is_not_copied(self):
        empty = extractor.trace_local(self.instructions, {})
        poisoned = extractor.trace_local(self.instructions, {a: 0xa5 for a in self.seed})
        self.assertEqual(empty['data'], self.trace['data'])
        self.assertEqual(poisoned['data'], self.trace['data'])
        self.assertEqual(empty['ranges'], self.trace['ranges'])
        self.assertEqual(empty['composed_known_bytes'], 2223)
        self.assertEqual(empty['composed_unknown_bytes'], extractor.IMAGE_BYTES-2223)

    def test_unknown_root_read_is_not_zero(self):
        # Counterfactual source read consumes common's P+1c8; removing that seed must fail.
        instructions = self.changed(0x8db9e0, mnemonic='ldr',
                       operands=[operand(ARM_OP_REG, ARM_REG_R6), operand(ARM_OP_MEM, ARM_REG_R4, 0x1c8)])
        self.assertEqual(extractor.trace_local(instructions, self.seed)['instructions'], 999)
        with self.assertRaisesRegex(ValueError, 'root store depends on an unknown input'):
            extractor.trace_local(instructions, {})

    def test_unknown_incoming_register_is_not_zero(self):
        instructions = self.changed(0x8db9e0,
                       operands=[operand(ARM_OP_REG, ARM_REG_R1), operand(ARM_OP_MEM, ARM_REG_R4, 0x28)])
        with self.assertRaisesRegex(ValueError, 'root store depends on an unknown input'):
            extractor.trace_local(instructions, self.seed)

    def test_calls_clobber_volatile_registers(self):
        for address in (0x8dbaae, 0x8dc2ae, 0x8dc2ba):
            for reg in extractor.VOLATILE:
                with self.subTest(address=hex(address), register=reg):
                    instructions = self.changed(address, mnemonic='str',
                                   operands=[operand(ARM_OP_REG, reg), operand(ARM_OP_MEM, ARM_REG_R4, 0x28)])
                    with self.assertRaisesRegex(ValueError, 'root store depends on an unknown input'):
                        extractor.trace_local(instructions, self.seed)

    def test_serializer_unknown_stack_word_rejects_copy(self):
        instructions = self.changed(0x8dc254,
                       operands=[operand(ARM_OP_REG, extractor.ARM_REG_IP),
                                 operand(ARM_OP_MEM, extractor.ARM_REG_SP, 0xa0)])
        with self.assertRaisesRegex(ValueError, 'copy depends on unknown source bytes'):
            extractor.trace_local(instructions, self.seed)

    def test_strd_register_order_is_little_endian(self):
        instructions = self.changed(0x8db9ea,
                       operands=[operand(ARM_OP_REG, ARM_REG_R8), operand(ARM_OP_REG, ARM_REG_R6),
                                 operand(ARM_OP_MEM, ARM_REG_R4, 0x34)])
        image = unpack(extractor.trace_local(instructions, self.seed))
        self.assertEqual(bytes(image[0x34+i] for i in range(8)), bytes.fromhex('3c00000001000000'))

    def test_serializer_four_byte_arguments_and_stack_aliases(self):
        # Abstract operand counterfactuals exercise nonzero high bytes absent from the actual zero call.
        instructions = self.instructions
        words = (0x12345678, 0x89abcdef, 0xfedcba98)
        for address, reg, number in zip((0x8dc236, 0x8dc238, 0x8dc23a),
                                        (ARM_REG_R1, ARM_REG_R2, ARM_REG_R3), words):
            instructions = self.changed(address, instructions=instructions,
                           operands=[operand(ARM_OP_REG, reg), operand(ARM_OP_IMM, number)])
        instructions = self.changed(0x8dc254, instructions=instructions,
                       operands=[operand(ARM_OP_REG, ARM_REG_R2), operand(ARM_OP_MEM, extractor.ARM_REG_SP, 0xa0)])
        image = unpack(extractor.trace_local(instructions, self.seed))
        expected = b''.join(w.to_bytes(4, 'little') for w in words)+bytes(0xa0)+words[1].to_bytes(4, 'little')
        self.assertEqual(bytes(image[0x870+i] for i in range(0xb0)), expected)

    def test_unknown_wrapped_and_outside_memory_rejected(self):
        for base, displacement, message in ((ARM_REG_R1, 0, 'unknown or wrapped'),
                                            (ARM_REG_R4, 0xffffffff, 'unknown or wrapped'),
                                            (ARM_REG_R4, extractor.IMAGE_BYTES, 'out-of-bounds')):
            with self.subTest(displacement=displacement):
                instructions = self.changed(0x8db9e0, operands=[operand(ARM_OP_REG, ARM_REG_R8),
                                            operand(ARM_OP_MEM, base, displacement)])
                with self.assertRaisesRegex(ValueError, message):
                    extractor.trace_local(instructions, self.seed)

    def test_unsupported_condition_opcode_or_call_rejected(self):
        for changes, message in (({'cc': ARM_CC_EQ}, 'conditional instruction'),
                                 ({'mnemonic': 'b'}, 'unclosed instruction'),
                                 ({'mnemonic': 'blx', 'operands': [operand(ARM_OP_IMM, 0xc1aa3e)]}, 'unclosed helper')):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(ValueError, message):
                    extractor.trace_local(self.changed(0x8db9e0, **changes), self.seed)


if __name__ == '__main__':
    unittest.main()
