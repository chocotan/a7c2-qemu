import importlib.util
from pathlib import Path
import struct
import unittest

spec = importlib.util.spec_from_file_location(
    "nor_page_tables", Path(__file__).with_name("inspect-nor-page-tables.py"))
nor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nor)


class PageTableTests(unittest.TestCase):
    def test_rejects_wrong_source(self):
        with self.assertRaisesRegex(ValueError, "size/SHA256"):
            nor.reconstruct(b"not the original NOR")

    def test_walk_preserves_high_physical_bits(self):
        memory = bytearray(0x84000)
        va = 0x803E42000
        root_slot = nor.ROOT36 - nor.L2 + (va >> 30) * 8
        struct.pack_into("<Q", memory, root_slot, 0xFE1A0003)
        struct.pack_into("<Q", memory, 0x20000 + (va >> 21 & 511) * 8, 0x803E00F05)
        result = nor.walk(memory, va, 36)
        self.assertEqual(result["pa"], hex(va))
        self.assertTrue(result["identity"])
        self.assertNotEqual(result["pa"], hex(va & 0xFFFFFFFF))

    def test_unmapped_block_is_not_zero_translation(self):
        memory = bytearray(0x84000)
        struct.pack_into("<Q", memory, nor.ROOT36 - nor.L2, nor.L2 | 3)
        result = nor.walk(memory, 0x108000, 36)
        self.assertEqual(result["status"], "unmapped_or_not_l2_block")
        self.assertNotIn("pa", result)

    def test_unreviewed_l1_block_and_t0sz_fail_closed(self):
        memory = bytearray(0x84000)
        result = nor.walk(memory, 0x108000, 36)
        self.assertEqual(result["status"], "l1_not_table_not_interpreted")
        self.assertNotIn("pa", result)
        for va, bits in ((0x800107F10, 32), (-1, 36), (1 << 36, 36), (0, 40)):
            with self.assertRaises(ValueError):
                nor.walk(memory, va, bits)


if __name__ == "__main__":
    unittest.main()
