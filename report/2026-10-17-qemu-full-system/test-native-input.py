#!/usr/bin/env python3
"""Dependency isolation and fail-closed snapshot identity, with tiny fixtures."""
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'native-input.py'))


class FrozenDependencies(unittest.TestCase):
    def test_upstream_edits_do_not_change_selected_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            here=Path(temporary);source=here/'upstream';source.mkdir();(source/'helper.py').write_text('ORIGINAL=1\n')
            storage=here/'runtime/native-source-snapshots'
            root=API['capture'](source,storage,{'helper.py':'public-source'})
            API['select'](here,root);(source/'helper.py').write_text('CHANGED=2\n')
            self.assertEqual(API['resolve'](here),root)
            self.assertEqual((root/'helper.py').read_text(),'ORIGINAL=1\n')
            self.assertNotEqual((root/'helper.py').stat().st_ino,(source/'helper.py').stat().st_ino)

    def test_changed_missing_extra_and_links_are_refused(self):
        for mutation in ('changed','missing','extra','link'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                here=Path(temporary);source=here/'upstream';source.mkdir();(source/'helper.py').write_text('ORIGINAL=1\n')
                root=API['capture'](source,here/'runtime/native-source-snapshots',{'helper.py':'public-source'});API['select'](here,root)
                target=root/'helper.py'
                if mutation=='changed':target.chmod(0o644);target.write_text('CHANGED=2\n')
                elif mutation=='missing':target.unlink()
                elif mutation=='extra':(root/'surprise.py').write_text('EXTRA=3\n')
                else:target.unlink();target.symlink_to(source/'helper.py')
                with self.assertRaises(ValueError):API['resolve'](here)

    def test_concurrent_source_change_is_not_selected(self):
        with tempfile.TemporaryDirectory() as temporary:
            here=Path(temporary);source=here/'upstream';source.mkdir();file=source/'helper.py';file.write_text('ORIGINAL=1\n')
            real=API['capture'].__globals__['shutil'].copyfile
            def changed(src,dst):
                result=real(src,dst);file.write_text('CONCURRENT=2\n');return result
            with patch.object(API['capture'].__globals__['shutil'],'copyfile',changed):
                with self.assertRaisesRegex(ValueError,'during capture'):
                    API['capture'](source,here/'runtime/native-source-snapshots',{'helper.py':'public-source'})
            self.assertFalse((here/'runtime/native-input.json').exists())


if __name__=='__main__':unittest.main()
