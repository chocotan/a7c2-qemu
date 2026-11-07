#!/usr/bin/env python3
"""Boundary tests for the property-level configuration comparator."""
import importlib.util
from pathlib import Path
import runpy
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('compare_config',HERE/'compare-config.py')
COMPARE=importlib.util.module_from_spec(spec);spec.loader.exec_module(COMPARE)
STATE=runpy.run_path(str(HERE/'backup-state.py'))
PP=Path('/tmp/pp.bin')


@unittest.skipUnless(PP.is_file(),'the extracted official PP is not available in this workspace')
class Comparator(unittest.TestCase):
    def test_identical_files_report_no_changes(self):
        data=PP.read_bytes()
        result=COMPARE.compare(data,data)
        self.assertEqual(result['changed'],0)
        self.assertEqual(result['setting_changes'],[])

    def test_diff_isolates_a_single_property(self):
        a={(0,0x2cf,0x50):b'\x04',(0,0x2cf,0x51):b'\x01'}
        b={(0,0x2cf,0x50):b'\x05',(0,0x2cf,0x51):b'\x01'}
        result=COMPARE.diff_properties(a,b)
        self.assertEqual(result['changed'],1)
        self.assertEqual(result['setting_changes'],[(0,0x2cf,0x50)])

    def test_boot_set_subtracts_bookkeeping(self):
        a={(0,0x2cf,0x50):b'\x04',(0,0x2cf,0x51):b'\x01'}
        b={(0,0x2cf,0x50):b'\x05',(0,0x2cf,0x51):b'\x02'}
        result=COMPARE.diff_properties(a,b,[[0,0x2cf,0x51]])
        self.assertEqual(result['changed'],2)
        self.assertEqual(result['setting_changes'],[(0,0x2cf,0x50)])
        self.assertEqual(result['boot_bookkeeping_changes'],1)

    def test_mismatched_property_sets_are_refused(self):
        with self.assertRaises(ValueError):
            COMPARE.diff_properties({(0,1,1):b'a'},{(0,1,2):b'a'})


if __name__=='__main__':unittest.main()
