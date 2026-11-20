"""Host-only inherited-FD fixtures; no QEMU, device, or successful FAT/guest claim."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import functional_camera_runner as runner


class InheritedRamCardTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root.chmod(0o700)
        self.environment = {'A7C2_RAM_CARD_LAUNCH_PROFILE': runner.RAM_CONSUMER_PROFILE}
        self.paths = {}
        self.fds = {}
        for name, filename in (('SEED', 'media-camera.fat'), ('RECEIPT', 'backup-profile.json'),
                               ('INITRAMFS', 'archive.cpio'), ('QEMU', 'qemu')):
            path = self.root / filename
            raw = name.encode()
            path.write_bytes(raw)
            path.chmod(0o700 if name == 'QEMU' else 0o600)
            fd = os.open(path, os.O_RDONLY)
            self.stack.callback(os.close, fd)
            self.paths[name] = path
            self.fds[name] = fd
            self.environment['A7C2_RAM_CARD_' + name + '_FD'] = str(fd)
            self.environment['A7C2_RAM_CARD_' + name + '_SHA256'] = hashlib.sha256(raw).hexdigest()
        self.pending = self.root / '.backup-profile.pending.json'
        # Real hardlinks reproduce _RamOutput.publish's pending + public names.
        os.link(self.paths['RECEIPT'], self.pending)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        self.stack.callback(os.close, directory)
        self.fds['DIRECTORY'] = directory
        self.environment['A7C2_RAM_CARD_DIRECTORY_FD'] = str(directory)
        self.stack.enter_context(mock.patch.object(runner, 'QEMU_SHA256',
                                                   self.environment['A7C2_RAM_CARD_QEMU_SHA256']))
        self.stack.enter_context(mock.patch.object(runner.ram_initramfs, 'fat16'))

    def verify(self):
        return runner.verify_ram_card_inherited(self.environment)

    def test_real_two_name_receipt_is_accepted_without_moving_offset(self):
        self.assertEqual(os.fstat(self.fds['RECEIPT']).st_nlink, 2)
        os.lseek(self.fds['RECEIPT'], 0, os.SEEK_END)
        self.assertEqual(self.verify(), max(self.fds.values()))
        self.assertEqual(os.lseek(self.fds['RECEIPT'], 0, os.SEEK_CUR), len(b'RECEIPT'))

    def test_writeback_profile_accepts_only_its_exact_inherited_qemu(self):
        actual = self.environment['A7C2_RAM_CARD_QEMU_SHA256']
        self.environment['QEMU_A7PF_WRITEBACK_FLUSH'] = '1'
        with mock.patch.object(runner, 'WRITEBACK_FLUSH_QEMU_SHA256', actual):
            self.assertEqual(self.verify(), max(self.fds.values()))
            with mock.patch.object(runner, 'WRITEBACK_FLUSH_QEMU_SHA256', '0' * 64), \
                    self.assertRaisesRegex(ValueError, 'accepted functional-camera build'):
                self.verify()

    def test_single_name_and_third_link_receipts_are_rejected(self):
        self.pending.unlink()
        with self.assertRaisesRegex(ValueError, 'link count/type differs: RECEIPT'):
            self.verify()
        os.link(self.paths['RECEIPT'], self.pending)
        os.link(self.paths['RECEIPT'], self.root / 'third-receipt')
        with self.assertRaisesRegex(ValueError, 'link count/type differs: RECEIPT'):
            self.verify()

    def test_both_names_must_resolve_to_held_receipt_even_when_contents_match(self):
        for replaced in (self.pending, self.paths['RECEIPT']):
            with self.subTest(replaced=replaced.name):
                replaced.unlink()
                replaced.write_bytes(b'RECEIPT')
                replaced.chmod(0o600)
                retained = self.paths['RECEIPT'] if replaced == self.pending else self.pending
                os.link(retained, self.root / 'unpublished-receipt')
                with self.assertRaisesRegex(ValueError, 'receipt publication differs'):
                    self.verify()
                replaced.unlink()
                os.link(retained, replaced)
                (self.root / 'unpublished-receipt').unlink()

    def test_receipt_symlink_is_rejected(self):
        self.pending.unlink()
        os.link(self.paths['RECEIPT'], self.root / 'unpublished-receipt')
        self.pending.symlink_to(self.paths['RECEIPT'].name)
        with self.assertRaises(OSError):
            self.verify()

    def test_receipt_digest_is_required(self):
        self.environment['A7C2_RAM_CARD_RECEIPT_SHA256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'readback differs: RECEIPT'):
            self.verify()

    def test_other_input_files_remain_single_link(self):
        for name in ('SEED', 'INITRAMFS', 'QEMU'):
            with self.subTest(name=name):
                extra = self.root / ('extra-' + name)
                os.link(self.paths[name], extra)
                with self.assertRaisesRegex(ValueError, 'link count/type differs: ' + name):
                    self.verify()
                extra.unlink()


if __name__ == '__main__':
    unittest.main()
