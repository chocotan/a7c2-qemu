import hashlib
import json
from pathlib import Path
import runpy
import tarfile
import tempfile
import unittest

API = runpy.run_path(str(Path(__file__).with_name('snapshot-observer-sources.py')))


class SourceSnapshot(unittest.TestCase):
    def test_local_only_immutable_sources_and_archive_identity(self):
        with tempfile.TemporaryDirectory(prefix='native-snapshot-test-') as temp:
            root = Path(temp)
            native, work = root / 'native', root / 'work'
            (native / 'device-models').mkdir(parents=True)
            work.mkdir()
            (native / 'menu-observe.c').write_text('local observer\n')
            (native/'start-bt-virtual.sh').write_text('original virtual profile\n')
            (native / 'device-models/model.h').write_text('local header\n')
            (native / 'device-models/firmware.bin').write_bytes(b'not source')
            (native / 'menu-observe.so').write_bytes(b'test-only binary fixture')
            (native / 'menu-root/simulation').mkdir(parents=True)
            (native / 'menu-root/simulation/pin-control-probe').write_bytes(b'test-only probe fixture')
            (native / 'menu-root/simulation/system-sound-owner').write_bytes(b'test-only sound fixture')
            API['snapshot'](native, work)
            (native/'start-bt-virtual.sh').write_text('later shell edit\n')
            self.assertEqual((work/API['NATIVE']/'start-bt-virtual.sh').read_text(),'original virtual profile\n')
            (native / 'device-models/model.h').write_text('later edit\n')
            self.assertEqual((work / API['SHARED'] / 'model.h').read_text(), 'local header\n')
            API['finish'](native, work)
            proof = json.loads((native / 'observer-build-inputs.json').read_text())
            archive = native / 'observer-build-sources.tar.gz'
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), proof['source_archive_sha256'])
            self.assertEqual(hashlib.sha256((native / 'menu-observe.so').read_bytes()).hexdigest(), proof['observer_sha256'])
            self.assertEqual(hashlib.sha256((native / 'menu-root/simulation/pin-control-probe').read_bytes()).hexdigest(), proof['pin_control_probe_sha256'])
            with tarfile.open(archive) as tar:
                self.assertFalse(any(name.endswith('.bin') or name.endswith('.so') for name in tar.getnames()))
                data = tar.extractfile(str(API['SHARED'] / 'model.h')).read()
                self.assertEqual(data, b'local header\n')

    def test_source_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory(prefix='native-snapshot-test-') as temp:
            root = Path(temp); native = root / 'native'
            (native / 'device-models').mkdir(parents=True)
            (root / 'outside.h').write_text('outside\n')
            (native / 'model.h').symlink_to(root / 'outside.h')
            with self.assertRaisesRegex(ValueError, 'ordinary source'):
                API['snapshot'](native, root / 'work')


if __name__ == '__main__':
    unittest.main()
