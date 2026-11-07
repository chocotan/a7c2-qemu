#!/usr/bin/env python3
"""Match the real runner/build flock, not PID text in a different lock path."""
import fcntl
import os
from pathlib import Path
import runpy
import tempfile
import unittest

exclusive = runpy.run_path(str(Path(__file__).with_name('runtime-lock.py')))['exclusive_runtime']


class RuntimeLock(unittest.TestCase):
    def runtime(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / 'analysis').mkdir()
        return root

    def test_refuses_the_actual_runner_lock(self):
        root = self.runtime()
        with (root / 'analysis/.run.lock').open('a') as runner:
            fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'runtime is busy'):
                with exclusive(root):
                    self.fail('reset/publish entered while the runner held its lock')

    def test_holds_lock_for_the_entire_operation_then_releases(self):
        root = self.runtime()
        with exclusive(root):
            with (root / 'analysis/.run.lock').open('a') as builder:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(builder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (root / 'analysis/.run.lock').open('a') as builder:
            fcntl.flock(builder, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_does_not_guess_activity_from_stale_pid_text(self):
        root = self.runtime()
        (root / '.run.lock').write_text(str(os.getpid()))
        (root / 'analysis/.run.lock').write_text('stale text')
        with exclusive(root):
            pass

    def test_keeps_the_lock_inode_after_release(self):
        root = self.runtime()
        with exclusive(root):
            inode = (root / 'analysis/.run.lock').stat().st_ino
        self.assertEqual((root / 'analysis/.run.lock').stat().st_ino, inode)

    def test_rejects_symlinked_analysis_and_lock(self):
        root = self.runtime()
        outside = Path(self.enterContext(tempfile.TemporaryDirectory()))
        target = outside / 'protected'
        target.write_bytes(b'keep')
        (root / 'analysis/.run.lock').symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlinked runtime lock'):
            with exclusive(root):
                self.fail('followed symlink')
        self.assertEqual(target.read_bytes(), b'keep')
        (root / 'analysis/.run.lock').unlink()
        (root / 'analysis').rmdir()
        (root / 'analysis').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'ordinary directory'):
            with exclusive(root):
                self.fail('followed analysis symlink')

    def test_rejects_nonregular_and_hardlinked_lock(self):
        root = self.runtime()
        lock = root / 'analysis/.run.lock'
        os.mkfifo(lock)
        with self.assertRaisesRegex(ValueError, 'private regular file'):
            with exclusive(root):
                self.fail('locked a FIFO')
        lock.unlink()
        lock.write_bytes(b'keep')
        os.link(lock, root / 'alias')
        with self.assertRaisesRegex(ValueError, 'private regular file'):
            with exclusive(root):
                self.fail('locked a hardlink')
        self.assertEqual(lock.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
