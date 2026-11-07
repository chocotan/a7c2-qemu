#!/usr/bin/env python3
"""Guard tests for the destroy-and-reinitialise entry.

Only the refusal paths are tested here; the restore itself needs mtools and a real
runtime, so it is exercised by an actual dry-run plus apply against a scratch runtime.
"""
import importlib.util
import json
import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('reset_derived', HERE / 'reset-derived-state.py')
RESET = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RESET)


def fake_runtime(root, *, protected=None):
    analysis = root / 'analysis'
    (analysis / 'root/partitions').mkdir(parents=True)
    (analysis / 'full-system.json').write_text(json.dumps({'initrd_sha256': 'x'}))
    (analysis / 'root/partitions/nflasha2.img').write_bytes(b'image')
    (analysis / 'official-pp.bin').write_bytes(b'not the pp')
    (analysis / '.run.lock').touch()
    if protected:
        (root / protected).mkdir()
    return root


class Guard(unittest.TestCase):
    def run_main(self, argv):
        import sys
        saved = sys.argv
        sys.argv = ['reset-derived-state.py', *argv]
        try:
            return RESET.main()
        finally:
            sys.argv = saved

    def test_rejects_path_that_is_not_a_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SystemExit) as raised:
                self.run_main(['--runtime', directory])
            self.assertIn('not a full-system runtime', str(raised.exception))

    def test_rejects_protected_directories_inside_the_runtime(self):
        for name in ('bodydata', 'overwrite', 'SD'):
            with tempfile.TemporaryDirectory() as directory:
                root = fake_runtime(Path(directory), protected=name)
                with self.assertRaises(SystemExit) as raised:
                    self.run_main(['--runtime', str(root)])
                self.assertIn(name, str(raised.exception))

    def test_rejects_a_live_run_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_runtime(Path(directory))
            with (root / 'analysis/.run.lock').open('a') as live:
                fcntl.flock(live, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(RuntimeError, 'runtime is busy'):
                    self.run_main(['--runtime', str(root), '--apply', '--confirm', 'reset'])

    def test_apply_needs_the_confirmation_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_runtime(Path(directory))
            with self.assertRaises(SystemExit) as raised:
                self.run_main(['--runtime', str(root), '--apply'])
            self.assertIn('--confirm', str(raised.exception))
            with self.assertRaises(SystemExit):
                self.run_main(['--runtime', str(root), '--apply', '--confirm', 'yes'])

    def test_rejects_a_reference_that_is_not_the_official_pp(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_runtime(Path(directory))
            with self.assertRaises(SystemExit) as raised:
                self.run_main(['--runtime', str(root), '--apply', '--confirm', 'reset'])
            self.assertIn('official ALLLANG PP', str(raised.exception))

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = fake_runtime(Path(directory))
            before = (root / 'analysis/root/partitions/nflasha2.img').read_bytes()
            files_before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with mock.patch.dict(RESET.STATE, {'extract': lambda *args: b'current'}):
                self.run_main(['--runtime', str(root)])
            self.assertEqual((root / 'analysis/root/partitions/nflasha2.img').read_bytes(), before)
            self.assertFalse((root / 'analysis/reset-record.json').exists())
            files_after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(files_before, files_after)


if __name__ == '__main__':
    unittest.main()
