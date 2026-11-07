#!/usr/bin/env python3
"""Storage safety, including a real process exit halfway through a commit."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
STATE = runpy.run_path(str(HERE / 'config-state.py'))
Transaction = STATE['Transaction']


def snapshot(root):
    return {str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink()
            else ('file', hashlib.sha256(p.read_bytes()).hexdigest())
            for p in root.rglob('*') if p.is_symlink() or p.is_file()}


class Safety(unittest.TestCase):
    def runtime(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        base = root / 'analysis'
        (base / 'root/partitions').mkdir(parents=True)
        (base / 'root/partitions/nflasha2.img').write_bytes(b'old image')
        (base / 'root/guest-link').symlink_to('/ordinary/guest/path')
        (base / 'full-system.json').write_text('{"initrd_sha256":"old"}')
        (base / 'full-system.cpio').write_bytes(b'old archive')
        (base / '.run.lock').touch()
        (base / 'runs').mkdir()
        (base / 'runs/log').write_bytes(b'old log')
        return root

    def prepare(self, transaction):
        transaction.image.write_bytes(b'new image')
        digest = transaction.repack()
        self.assertEqual(digest, hashlib.sha256((transaction.stage / 'full-system.cpio').read_bytes()).hexdigest())
        return {'root/partitions/nflasha2.img': transaction.image,
                'full-system.cpio': transaction.stage / 'full-system.cpio',
                'full-system.json': transaction.stage / 'full-system.json'}

    def test_staging_failure_leaves_all_formal_files_unchanged(self):
        root = self.runtime()
        before = snapshot(root)
        with self.assertRaisesRegex(OSError, 'packing failed'):
            with Transaction(root) as transaction:
                transaction.image.write_bytes(b'changed only in stage')
                with mock.patch.object(subprocess, 'run', side_effect=OSError('packing failed')):
                    transaction.repack()
        self.assertEqual(snapshot(root), before)

    def test_success_archive_contains_the_new_image_and_preserves_guest_links(self):
        root = self.runtime()
        with Transaction(root) as transaction:
            replacements = self.prepare(transaction)
            transaction.commit(replacements)
        base = root / 'analysis'
        packed = subprocess.run(['cpio', '-i', '--to-stdout', 'partitions/nflasha2.img'],
                                input=(base / 'full-system.cpio').read_bytes(), capture_output=True, check=True)
        self.assertEqual(packed.stdout, b'new image')
        self.assertEqual((base / 'root/partitions/nflasha2.img').read_bytes(), b'new image')
        self.assertEqual(os.readlink(base / 'root/guest-link'), '/ordinary/guest/path')
        self.assertFalse((base / STATE['MARKER']).exists())

    def test_failed_second_replace_rolls_back_already_replaced_image(self):
        root = self.runtime()
        before = snapshot(root)
        real_replace = os.replace
        with self.assertRaisesRegex(OSError, 'injected commit failure'):
            with Transaction(root) as transaction:
                replacements = self.prepare(transaction)
                def fail(source, target):
                    if Path(source) == transaction.stage / 'full-system.cpio':
                        raise OSError('injected commit failure')
                    return real_replace(source, target)
                with mock.patch.object(os, 'replace', side_effect=fail):
                    transaction.commit(replacements)
        self.assertEqual(snapshot(root), before)

    def test_abrupt_exit_blocks_operations_and_explicit_recovery_restores_old_generation(self):
        root = self.runtime()
        before = snapshot(root)
        pid = os.fork()
        if pid == 0:
            try:
                with STATE['exclusive_runtime'](root), Transaction(root) as transaction:
                    replacements = self.prepare(transaction)
                    real_replace = os.replace
                    def die(source, target):
                        if Path(source) == transaction.stage / 'full-system.cpio':
                            os._exit(77)
                        return real_replace(source, target)
                    with mock.patch.object(os, 'replace', side_effect=die):
                        transaction.commit(replacements)
            finally:
                os._exit(78)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 77)
        self.assertEqual((root / 'analysis/root/partitions/nflasha2.img').read_bytes(), b'new image')
        with self.assertRaisesRegex(RuntimeError, 'unfinished configuration transaction'):
            with STATE['exclusive_runtime'](root):
                self.fail('pending transaction was ignored')
        with STATE['exclusive_runtime'](root, allow_pending=True):
            self.assertEqual(STATE['recover_locked'](root), 'rolledback')
        self.assertEqual(snapshot(root), before)

    def test_committed_cleanup_failure_is_recoverable_without_rolling_back_success(self):
        root = self.runtime()
        with self.assertRaisesRegex(OSError, 'cleanup failed'):
            with Transaction(root) as transaction:
                replacements = self.prepare(transaction)
                with mock.patch.object(STATE['shutil'], 'rmtree', side_effect=OSError('cleanup failed')):
                    transaction.commit(replacements)
        self.assertEqual(json.loads((root / 'analysis' / STATE['MARKER']).read_text())['phase'], 'committed')
        with STATE['exclusive_runtime'](root, allow_pending=True):
            self.assertEqual(STATE['recover_locked'](root), 'committed')
        self.assertEqual((root / 'analysis/root/partitions/nflasha2.img').read_bytes(), b'new image')

    def test_rejects_mutable_parent_and_leaf_symlinks_before_any_stage(self):
        for name in ('root/partitions/nflasha2.img', 'runs', 'full-system.json'):
            root = self.runtime()
            external = Path(self.enterContext(tempfile.TemporaryDirectory()))
            target = external / 'untouched'
            target.write_bytes(b'keep')
            path = root / 'analysis' / name
            if path.is_dir():
                (path / 'log').unlink()
                path.rmdir()
            else:
                path.unlink()
            path.symlink_to(target)
            before = snapshot(root)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                with Transaction(root):
                    self.fail('followed mutable symlink')
            self.assertEqual(snapshot(root), before)
            self.assertEqual(target.read_bytes(), b'keep')

    def test_rejects_symlinked_partition_parent(self):
        root = self.runtime()
        external = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = root / 'analysis/root/partitions'
        (path / 'nflasha2.img').unlink()
        path.rmdir()
        path.symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            with Transaction(root):
                self.fail('followed partition parent')

    def test_runner_and_builder_refuse_pending_journal_before_creating_a_run_or_build(self):
        root = self.runtime()
        (root / 'analysis' / STATE['MARKER']).write_text('pending')
        before = snapshot(root)
        for name in ('run-full-system.py', 'build-full-system.py'):
            result = subprocess.run([sys.executable, '-B', str(HERE / name), '--runtime', str(root)],
                                    capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unfinished configuration transaction', result.stderr)
            self.assertEqual(snapshot(root), before)


if __name__ == '__main__':
    unittest.main()
