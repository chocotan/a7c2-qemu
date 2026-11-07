import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import tarfile
import tempfile
import unittest

API = runpy.run_path(str(Path(__file__).with_name('snapshot-observer-sources.py')))


class SourceSnapshot(unittest.TestCase):
    @staticmethod
    def seed_metadata(native):
        for name in API['METADATA_INPUTS']:
            path = native.parents[1] / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('metadata fixture ' + name + '\n')

    def test_local_only_immutable_sources_and_archive_identity(self):
        with tempfile.TemporaryDirectory(prefix='native-snapshot-test-') as temp:
            root = Path(temp)
            native, work = root / API['NATIVE'], root / 'work'
            (native / 'device-models').mkdir(parents=True)
            self.seed_metadata(native)
            work.mkdir()
            (native / 'menu-observe.c').write_text('local observer\n')
            (native/'start-bt-virtual.sh').write_text('original virtual profile\n')
            (native / 'device-models/model.h').write_text('local header\n')
            (native / 'device-models/firmware.bin').write_bytes(b'not source')
            (native / 'unreviewed.py').write_bytes(b'not a declared runtime contract')
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
                self.assertFalse(any(name.endswith(('.bin', '.so', '/unreviewed.py')) for name in tar.getnames()))
                data = tar.extractfile(str(API['SHARED'] / 'model.h')).read()
                self.assertEqual(data, b'local header\n')
                for name in API['METADATA_INPUTS']:
                    relative = API['NATIVE'].parents[1] / name
                    self.assertEqual(tar.extractfile(str(relative)).read(),
                                     ('metadata fixture ' + name + '\n').encode())
                    self.assertIn(str(native.parents[1] / name), proof['sources'])

    def test_qr5_runtime_contract_bytes_survive_build_index_and_archive(self):
        spec = importlib.util.spec_from_file_location('snapshot_qr5_condition_fixture',
            Path(__file__).parent / 'scratch/verify_hdmi_edge.py')
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        reviewed = helper.YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES
        original = {name: (helper.BASE / name).read_bytes() for name in reviewed}
        self.assertEqual({name: hashlib.sha256(data).hexdigest() for name, data in original.items()}, reviewed)
        with tempfile.TemporaryDirectory(prefix='native-snapshot-qr5-test-') as temp:
            root = Path(temp)
            native, work = root / API['NATIVE'], root / 'work'
            (native / 'device-models').mkdir(parents=True)
            self.seed_metadata(native)
            for name, data in original.items():
                (native / name).write_bytes(data)
            (native / 'menu-observe.so').write_bytes(b'test-only binary fixture')
            (native / 'menu-root/simulation').mkdir(parents=True)
            (native / 'menu-root/simulation/pin-control-probe').write_bytes(b'test-only probe fixture')
            (native / 'menu-root/simulation/system-sound-owner').write_bytes(b'test-only sound fixture')
            production = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in API['source_paths'](native)}
            API['snapshot'](native, work)
            for name in ('functional_camera_broker.py', 'backup_profile.py'):
                (native / name).write_bytes(b'later edit must not replace frozen contract bytes\n')
            API['finish'](native, work)
            proof = json.loads((native / 'observer-build-inputs.json').read_bytes())
            self.assertEqual({name: entry['sha256'] for name, entry in proof['sources'].items()}, production)
            archive = native / 'observer-build-sources.tar.gz'
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), proof['source_archive_sha256'])
            archived = {}
            with tarfile.open(archive) as tar:
                self.assertEqual(json.loads(tar.extractfile('source-inputs.json').read()), proof['sources'])
                for name in reviewed:
                    path = str(native / name)
                    entry = proof['sources'][path]
                    self.assertEqual(entry['archive_path'], str(API['NATIVE'] / name))
                    data = tar.extractfile(entry['archive_path']).read()
                    self.assertEqual(data, original[name])
                    archived[path] = dict(sha256=hashlib.sha256(data).hexdigest())
                    self.assertEqual(archived[path]['sha256'], entry['sha256'])
            helper.BASE = native
            self.assertEqual(helper._condition_source_set(proof['sources']), reviewed)
            self.assertEqual(helper._condition_source_set(archived), reviewed)
            for name in ('functional_camera_broker.py', 'backup_profile.py'):
                path = str(native / name)
                with self.subTest(member=name, damage='missing'):
                    missing = dict(archived)
                    del missing[path]
                    with self.assertRaisesRegex(ValueError, 'missing YVO BB-timecode preset condition source member'):
                        helper._condition_source_set(missing)
                with self.subTest(member=name, damage='changed'):
                    changed = dict(archived)
                    changed[path] = dict(sha256='0' * 64)
                    with self.assertRaisesRegex(ValueError, 'unreviewed YVO BB-timecode preset condition source tuple'):
                        helper._condition_source_set(changed)

    def test_required_runtime_contracts_are_not_omitted_or_followed_as_symlinks(self):
        for name in ('functional_camera_broker.py', 'backup_profile.py'):
            for damage in ('missing', 'symlink'):
                with self.subTest(member=name, damage=damage), tempfile.TemporaryDirectory(prefix='native-snapshot-contract-test-') as temp:
                    root = Path(temp)
                    native, work = root / API['NATIVE'], root / 'work'
                    (native / 'device-models').mkdir(parents=True)
                    self.seed_metadata(native)
                    path = native / name
                    data = b'required runtime contract fixture\n'
                    path.unlink(missing_ok=True)
                    if damage == 'symlink':
                        outside = root / name
                        outside.write_bytes(data)
                        path.symlink_to(outside)
                    with self.assertRaisesRegex(ValueError, 'ordinary source'):
                        API['snapshot'](native, work)
                    self.assertFalse((work / 'source-inputs.json').exists())

    def test_missing_metadata_is_not_silently_omitted(self):
        with tempfile.TemporaryDirectory(prefix='native-snapshot-test-') as temp:
            root = Path(temp); native = root / API['NATIVE']
            (native / 'device-models').mkdir(parents=True)
            self.seed_metadata(native)
            (native.parents[1] / API['METADATA_INPUTS'][-1]).unlink()
            with self.assertRaisesRegex(ValueError, 'ordinary source'):
                API['snapshot'](native, root / 'work')

    def test_source_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory(prefix='native-snapshot-test-') as temp:
            root = Path(temp); native = root / API['NATIVE']
            (native / 'device-models').mkdir(parents=True)
            (root / 'outside.h').write_text('outside\n')
            (native / 'model.h').symlink_to(root / 'outside.h')
            with self.assertRaisesRegex(ValueError, 'ordinary source'):
                API['snapshot'](native, root / 'work')


if __name__ == '__main__':
    unittest.main()
