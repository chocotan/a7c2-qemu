#!/usr/bin/env python3
from pathlib import Path
import runpy
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'liro-memory-probe.py'))


class MemoryProbe(unittest.TestCase):
    def fixture(self, root, running=True, bad_anchor=False, short=False):
        calls = []

        def qmp(name, args=None):
            calls.append((name, args))
            if name == 'query-status':
                return {'running': running}
            if name == 'human-monitor-command':
                value = 0 if bad_anchor else 0xf94036f4
                if '4005e99c8' in args['command-line']:
                    value = 0x400000000
                return f'00000000: 0x{value:x}\r\n'
            if name == 'pmemsave':
                self.assertEqual(args, {'val': API['ADDRESS'], 'size': API['CAPACITY'], 'filename': '/out/liro-reserved-memory.bin'})
                with (root / 'liro-reserved-memory.bin').open('wb') as stream:
                    stream.truncate(API['CAPACITY'] - int(short))
            return {}

        return qmp, calls

    def test_complete_zero_window_is_negative_image_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qmp, calls = self.fixture(root)
            proof = API['probe'](qmp, API['KERNEL_SHA256'], root, API['ADDRESS'])
            self.assertTrue(proof['liro_reserved_memory_observed'])
            self.assertTrue(proof['window_all_zero'])
            self.assertFalse(proof['image_matches_original'])
            self.assertTrue(proof['linked_address_compatible'])
            self.assertEqual(calls[-1][0], 'cont')
            self.assertFalse(proof['LIRO_initialized_verified'])

    def test_failures_restore_running_state(self):
        for kind in ('anchor', 'short'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                qmp, calls = self.fixture(root, bad_anchor=kind == 'anchor', short=kind == 'short')
                with self.assertRaises(ValueError):
                    API['probe'](qmp, API['KERNEL_SHA256'], root, API['ADDRESS'])
                self.assertEqual(calls[-1][0], 'cont')

    def test_paused_vm_stays_paused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qmp, calls = self.fixture(root, running=False)
            API['probe'](qmp, API['KERNEL_SHA256'], root, API['ADDRESS'])
            self.assertFalse(any(name in ('stop', 'cont') for name, _ in calls))

    def test_wrong_identity_address_or_existing_file_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qmp, calls = self.fixture(root)
            for sha, address in (('bad', API['ADDRESS']), (API['KERNEL_SHA256'], 0xffff0000)):
                with self.assertRaises(ValueError):
                    API['probe'](qmp, sha, root, address)
            self.assertFalse(calls)
            (root / 'liro-reserved-memory.bin').touch()
            with self.assertRaises(ValueError):
                API['probe'](qmp, API['KERNEL_SHA256'], root, API['ADDRESS'])
            self.assertFalse(calls)

    def test_insufficient_space_never_touches_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qmp, calls = self.fixture(root)
            with patch.object(API['shutil'], 'disk_usage', return_value=SimpleNamespace(free=0)):
                with self.assertRaisesRegex(ValueError, 'insufficient'):
                    API['probe'](qmp, API['KERNEL_SHA256'], root, API['ADDRESS'])
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
