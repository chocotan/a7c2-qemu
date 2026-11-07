#!/usr/bin/env python3
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

API=runpy.run_path(str(Path(__file__).with_name('file-media-template.py')))


@unittest.skipUnless(shutil.which('fsck.fat'),'requires fsck.fat')
class Template(unittest.TestCase):
    def test_real_seed_copy_is_byte_identical_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'original.fat'
            target=Path(directory)/'copy.fat'
            API['create'](source)
            before=hashlib.sha256(source.read_bytes()).hexdigest()
            result=API['copy_seed'](source,target)
            self.assertEqual(result['sha256'],before)
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(),before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)
            self.assertTrue(result['source_unchanged'])

    def test_generated_metadata_uses_fixed_time_and_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            path=API['create'](Path(directory)/'generated.fat')
            with path.open('rb') as stream:
                boot=stream.read(512)
                root=(int.from_bytes(boot[14:16],'little')+boot[16]*int.from_bytes(boot[22:24],'little'))*512
                stream.seek(root)
                label=stream.read(32)
            self.assertEqual(int.from_bytes(boot[39:43],'little'),0xA7C20001)
            # FAT date 2000-01-01 and midnight, including the label created by mformat.
            self.assertEqual(label[22:26],b'\x00\x00\x21\x28')
            self.assertEqual(API['inspect'](path)['fsck_rc'],0)

    def test_symlinks_fifo_and_wrong_size_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            small=root/'small';small.write_bytes(b'small')
            link=root/'link';link.symlink_to(small)
            fifo=root/'fifo';os.mkfifo(fifo)
            for source in (small,link,fifo):
                with self.subTest(source=source),self.assertRaises((ValueError,OSError)):
                    API['copy_seed'](source,root/'target')
            self.assertFalse((root/'target').exists())


if __name__=='__main__':unittest.main()
