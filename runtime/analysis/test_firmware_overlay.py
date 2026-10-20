import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import firmware_overlay as overlay
from initramfs_identity import verify_image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(name, data=b'', mode=stat.S_IFREG | 0o640, links=1, inode=1):
    raw = name.encode() + b'\0'
    fields = [inode, mode, 123, 456, links, 17, len(data), 0, 0, 0, 0, len(raw), 0]
    header = b'070701' + b''.join(f'{v:08x}'.encode() for v in fields) + raw
    return header + b'\0' * (-len(header) % 4) + data + b'\0' * (-len(data) % 4)


def archive(entries):
    return b''.join(entries) + record('TRAILER!!!', mode=0) + b'\0' * 32


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'overwrite'
        self.source.mkdir()
        self.base = self.root / 'base.cpio'
        self.output = self.root / 'derived.cpio'
        self.original = archive([record('./usr/lib/appFw.so', b'official'),
                                 record('keep', b'unchanged', inode=2)])
        self.base.write_bytes(self.original)

    def put(self, name, data=b'custom', mode=0o751):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def build(self):
        return overlay.build_overlay_initramfs(self.base, self.source, self.output)

    def no_artifact(self):
        self.assertFalse(os.path.lexists(self.output))
        self.assertFalse(list(self.root.glob('.*.partial')))
        self.assertEqual(self.base.read_bytes(), self.original)

    def test_replace_add_modes_hashes_and_original_verifier(self):
        self.put('usr/lib/appFw.so')
        self.put('arbitrary/new/file.bin', b'anything', 0o6751)
        result = self.build()
        expected = {'usr/lib/appFw.so': sha(b'custom'), 'arbitrary/new/file.bin': sha(b'anything'),
                    'keep': sha(b'unchanged')}
        self.assertEqual(verify_image(self.output, expected), expected)
        with self.assertRaisesRegex(ValueError, 'content differs'):
            verify_image(self.output, {'usr/lib/appFw.so': sha(b'official')})
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertIn(record('keep', b'unchanged', inode=2), self.output.read_bytes())
        self.assertEqual(result['output_cpio_sha256'], sha(self.output.read_bytes()))
        self.assertEqual(result['base_cpio_sha256'], sha(self.original))
        self.assertFalse(result['original_libraries_unchanged'])
        items = {item['path']: item for item in result['entries']}
        self.assertEqual(items['usr/lib/appFw.so']['old_sha256'], sha(b'official'))
        self.assertIsNone(items['arbitrary/new/file.bin']['old_sha256'])
        self.assertEqual(items['usr/lib/appFw.so']['mode'], stat.S_IFREG | 0o640)
        self.assertEqual(items['usr/lib/appFw.so']['uid'], 123)
        self.assertEqual(items['arbitrary/new/file.bin']['mode'], stat.S_IFREG | 0o751)
        self.assertEqual(items['arbitrary/new/file.bin']['source_class'], 'user_overwrite')
        self.assertEqual(json.loads(json.dumps(result)), result)
        with self.output.open('rb') as image:
            names = [entry[0] for entry in overlay._entries(image, self.output.stat().st_size)]
        self.assertLess(names.index('usr'), names.index('usr/lib'))
        self.assertLess(names.index('usr/lib'), names.index('usr/lib/appFw.so'))

    def test_empty_and_only_empty_directories_are_byte_identical(self):
        for kind in ('empty', 'directories'):
            with self.subTest(kind=kind):
                if kind == 'directories':
                    (self.source / 'empty' / 'nested').mkdir(parents=True)
                result = self.build()
                self.assertEqual(self.output.read_bytes(), self.original)
                self.assertEqual(result['entries'], [])
                verify_image(self.output, {'usr/lib/appFw.so': sha(b'official')})
                self.output.unlink()

    def test_zero_length_file(self):
        self.put('zero', b'')
        result = self.build()
        verify_image(self.output, {'zero': sha(b'')})
        self.assertEqual(result['entries'][0]['size'], 0)

    def test_reserved_trailer_source(self):
        self.put('TRAILER!!!')
        with self.assertRaises(ValueError):
            self.build()
        self.no_artifact()

    def test_source_symlink_and_fifo_and_directory_symlink(self):
        outside = self.root / 'outside'
        outside.write_bytes(b'outside')
        for kind in ('file-link', 'dir-link', 'fifo'):
            with self.subTest(kind=kind):
                path = self.source / 'unsafe'
                if kind == 'fifo':
                    os.mkfifo(path)
                else:
                    path.symlink_to(outside if kind == 'file-link' else self.root, target_is_directory=kind == 'dir-link')
                with self.assertRaises(ValueError):
                    self.build()
                self.no_artifact()
                path.unlink()

    def test_symlink_source_root_or_host_ancestor(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            overlay.build_overlay_initramfs(self.base, alias, self.output)
        self.put('nested/file')
        with self.assertRaises(OSError):
            overlay.build_overlay_initramfs(self.base, alias / 'nested', self.output)
        self.no_artifact()

    def test_parent_traversal_argument(self):
        with self.assertRaisesRegex(ValueError, 'contains ..'):
            overlay.build_overlay_initramfs(self.base, self.source / '..' / 'overwrite', self.output)
        self.no_artifact()

    def test_output_inside_source_rejected(self):
        with self.assertRaises(ValueError):
            overlay.build_overlay_initramfs(self.base, self.source, self.source / 'derived.cpio')
        self.no_artifact()

    def test_existing_output_and_broken_output_link_never_overwritten(self):
        self.output.write_bytes(b'user data')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.output.read_bytes(), b'user data')
        self.output.unlink()
        self.output.symlink_to('missing')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(os.readlink(self.output), 'missing')

    def test_duplicate_truncated_escape_and_base_symlink_ancestors(self):
        cases = [archive([record('a'), record('./a')]), self.original[:130],
                 archive([record('../escape')]), archive([record('/absolute')]),
                 archive([record('x', b'dir', stat.S_IFLNK | 0o777), record('x/file')]),
                 archive([record('x/file'), record('x', b'dir', stat.S_IFLNK | 0o777)]),
                 self.original + self.original,
                 self.original[:-35]]
        for data in cases:
            with self.subTest(data=data[:32]):
                self.base.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.build()
                self.assertFalse(self.output.exists())
                self.assertFalse(list(self.root.glob('.*.partial')))
                self.assertEqual(self.base.read_bytes(), data)

    def test_base_symlink_destination_and_hardlink_replacement_rejected(self):
        cases = [(record('x', b'target', stat.S_IFLNK | 0o777), 'x'),
                 (record('x', mode=stat.S_IFDIR | 0o755), 'x'),
                 (record('x', links=2), 'x'),
                 (record('x', b'target', stat.S_IFLNK | 0o777), 'x/file'),
                 (record('x/file'), 'x'),
                 (record('x'), 'x/file')]
        for entry, name in cases:
            with self.subTest(name=name, entry=entry[:32]):
                with tempfile.TemporaryDirectory(dir=self.root) as temp:
                    root = Path(temp)
                    base = root / 'base'
                    base.write_bytes(archive([entry]))
                    source = root / 'overwrite'
                    (source / name).parent.mkdir(parents=True)
                    (source / name).write_bytes(b'replacement')
                    with self.assertRaises(ValueError):
                        overlay.build_overlay_initramfs(base, source, root / 'out')
                    self.assertFalse((root / 'out').exists())

    def test_low_space_and_unknown_space_fail_closed(self):
        for available, blocksize in ((0, 4096), (10**12, 0)):
            with self.subTest(available=available), mock.patch.object(overlay.os, 'fstatvfs',
                    return_value=mock.Mock(f_bavail=available, f_frsize=blocksize)):
                with self.assertRaises(OSError):
                    self.build()
                self.no_artifact()

    def test_source_inode_swap_during_read(self):
        source = self.put('payload', b'before')
        original_copy = overlay._copy
        changed = False

        def change(stream, output, length, digest=None):
            nonlocal changed
            original_copy(stream, output, length, digest)
            if output is not None and digest is not None and not changed:
                changed = True
                source.unlink()
                source.write_bytes(b'after!')

        with mock.patch.object(overlay, '_copy', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                self.build()
        self.assertTrue(changed)
        self.no_artifact()

    def test_source_content_edit_during_read(self):
        source = self.put('payload', b'before')
        original_copy = overlay._copy

        def change(stream, output, length, digest=None):
            original_copy(stream, output, length, digest)
            if output is not None and digest is not None:
                source.write_bytes(b'after!')

        with mock.patch.object(overlay, '_copy', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'source changed'):
                self.build()
        self.no_artifact()

    def test_base_mutation_fails(self):
        original_copy = overlay._copy
        changed = False

        def change(stream, output, length, digest=None):
            nonlocal changed
            original_copy(stream, output, length, digest)
            if output is not None and not changed:
                changed = True
                with self.base.open('ab') as base:
                    base.write(b'\0')

        with mock.patch.object(overlay, '_copy', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'Base image changed'):
                self.build()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.*.partial')))

    def test_output_publication_race_never_clobbers(self):
        original_link = overlay.os.link

        def race(*args, **kwargs):
            self.output.write_bytes(b'winner')
            return original_link(*args, **kwargs)

        with mock.patch.object(overlay.os, 'link', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(self.output.read_bytes(), b'winner')
        self.assertFalse(list(self.root.glob('.*.partial')))

    def test_fsync_failure_after_publication_removes_output(self):
        original_fsync = overlay.os.fsync
        count = 0

        def fail(descriptor):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('directory fsync failure')
            return original_fsync(descriptor)

        with mock.patch.object(overlay.os, 'fsync', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'directory fsync failure'):
                self.build()
        self.no_artifact()

    def test_base_root_symlink_rejected(self):
        self.base.write_bytes(archive([record('.', b'elsewhere', stat.S_IFLNK | 0o777)]))
        with self.assertRaisesRegex(ValueError, 'root is not a directory'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_byte_exact_unmodified_nonzero_padding(self):
        entry = bytearray(record('keep', b'z'))
        entry[-3:] = b'XYZ'
        self.original = archive([bytes(entry)])
        self.base.write_bytes(self.original)
        self.put('new', b'new')
        self.build()
        self.assertIn(bytes(entry), self.output.read_bytes())
        verify_image(self.output, {'keep': sha(b'z'), 'new': sha(b'new')})

    def test_multichunk_reads_are_bounded(self):
        self.put('large', b'abcdef' * 10000)
        with mock.patch.object(overlay, 'CHUNK', 17):
            self.build()
        verify_image(self.output, {'large': sha(b'abcdef' * 10000)})

    def test_source_ancestor_rename_fails(self):
        self.put('nested/payload', b'content')
        original_copy = overlay._copy
        changed = False

        def change(stream, output, length, digest=None):
            nonlocal changed
            original_copy(stream, output, length, digest)
            if output is not None and digest is not None and not changed:
                changed = True
                (self.source / 'nested').rename(self.source / 'renamed')
                (self.source / 'nested').mkdir()

        with mock.patch.object(overlay, '_copy', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'directory changed'):
                self.build()
        self.no_artifact()

    def test_read_error_cleans_private_output(self):
        self.put('payload')
        original_copy = overlay._copy

        def fail(stream, output, length, digest=None):
            if output is not None and digest is not None:
                raise OSError('injected read failure')
            original_copy(stream, output, length, digest)

        with mock.patch.object(overlay, '_copy', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'read failure'):
                self.build()
        self.no_artifact()

    def test_derived_verifier_failure_prevents_publication(self):
        original_verify = overlay.verify_image
        calls = 0

        def fail(path, expected):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError('injected verification failure')
            return original_verify(path, expected)

        with mock.patch.object(overlay, 'verify_image', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'verification failure'):
                self.build()
        self.no_artifact()


if __name__ == '__main__':
    unittest.main()
