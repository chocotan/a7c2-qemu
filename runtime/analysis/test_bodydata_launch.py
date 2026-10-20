import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bodydata_launch', Path(__file__).with_name('bodydata-launch.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root/'BODYDATA.DAT'
        self.package.write_bytes(b'official test fixture')

    def test_discovery_ambiguity_missing_and_nonregular(self):
        self.assertEqual(m.discover(self.root), self.package)
        (self.root/'bodydata.dat').write_bytes(b'other')
        with self.assertRaises(ValueError): m.discover(self.root)
        (self.root/'bodydata.dat').unlink()
        self.package.unlink()
        with self.assertRaises(ValueError): m.discover(self.root)
        self.package.symlink_to('/dev/null')
        with self.assertRaises(ValueError): m.discover(self.root)
        with self.assertRaises(ValueError): m.discover(Path('/dev/null'))

    def test_default_search_and_symlink_parent(self):
        kit = self.root/'product/runtime/analysis'
        incoming = self.root/'product/incoming/bodydata'
        incoming.mkdir(parents=True)
        source = incoming/'BODYDATA.DAT'
        source.write_bytes(b'x')
        with patch.object(m.Path, 'cwd', return_value=self.root/'elsewhere'):
            self.assertEqual(m.discover(base=kit), source)
        alias = self.root/'alias'
        alias.symlink_to(incoming, target_is_directory=True)
        with self.assertRaises(ValueError): m.discover(alias/'BODYDATA.DAT')

    def test_space_boundary(self):
        with patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=m.RESERVE+10)):
            m.space(self.root, 10)
            with self.assertRaises(ValueError): m.space(self.root, 11)

    def fake_unpack(self, package, stage, sdk, sha):
        (stage/'firmware-root').mkdir()
        (stage/'firmware.fdat').write_bytes(b'fdat')
        (stage/'firmware-root/arbitrary-file').write_bytes(b'no filename whitelist')
        return {'model': 0x20030014, 'version': '2.01'}

    def test_cache_hit_tamper_and_unknown_file(self):
        cache = self.root/'cache'
        entry = m.cache_package(self.package, cache, self.root, self.fake_unpack)
        def unexpected(*args): self.fail('cache hit unpacked')
        self.assertEqual(m.cache_package(self.package, cache, self.root, unexpected), entry)
        (entry/'unknown').write_bytes(b'x')
        with self.assertRaises(ValueError): m.cache_package(self.package, cache, self.root, unexpected)
        self.assertEqual((entry/'unknown').read_bytes(), b'x')
        (entry/'unknown').unlink()
        (entry/'firmware.fdat').write_bytes(b'changed')
        with self.assertRaises(ValueError): m.verify_cache(entry, m.digest(self.package))

    def test_failure_has_no_success_or_published_entry(self):
        cache = self.root/'cache'
        def broken(*args): raise ValueError('injected failure')
        with self.assertRaises(ValueError): m.cache_package(self.package, cache, self.root, broken)
        self.assertFalse((cache/m.digest(self.package)).exists())
        stages = list(cache.glob('.*.staging-*'))
        self.assertEqual(len(stages), 1)
        self.assertFalse((stages[0]/'success.json').exists())
        self.assertIn('injected failure', (stages[0]/'failure.json').read_text())

    def test_unknown_cache_not_adopted(self):
        cache = self.root/'cache'
        cache.mkdir()
        unknown = cache/'unknown'
        unknown.write_bytes(b'keep')
        with self.assertRaises(FileNotFoundError): m.cache_package(self.package, cache, self.root, self.fake_unpack)
        self.assertEqual(unknown.read_bytes(), b'keep')

    def test_cache_special_entry_and_invalid_manifest(self):
        entry = m.cache_package(self.package, self.root/'cache', self.root, self.fake_unpack)
        (entry/'link').symlink_to('/dev/null')
        with self.assertRaises(ValueError): m.verify_cache(entry, m.digest(self.package))
        (entry/'link').unlink()
        manifest = entry/'success.json'
        data = json.loads(manifest.read_text())
        data['schema'] = 9
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError): m.verify_cache(entry, m.digest(self.package))

    def archive(self, entries):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as tar:
            for name, content, kind in entries:
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.size = len(content) if kind == tarfile.REGTYPE else 0
                entry.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                tar.addfile(entry, io.BytesIO(content) if entry.size else None)
        stream.seek(0)
        return stream

    def test_archive_arbitrary_names_and_skipped_link(self):
        stream = self.archive([('./folder/other.bin', b'hello', tarfile.REGTYPE), ('tmp/mtab', b'', tarfile.SYMTYPE)])
        root = self.root/'extract'
        skipped = m.extract_tar(stream, root, 5)
        self.assertEqual((root/'folder/other.bin').read_bytes(), b'hello')
        self.assertFalse((root/'tmp/mtab').exists())
        self.assertEqual(skipped[0]['path'], 'tmp/mtab')

    def test_archive_path_duplicates_and_expansion(self):
        for i, entries in enumerate([
            [('../escape', b'x', tarfile.REGTYPE)],
            [('x', b'x', tarfile.REGTYPE), ('x', b'x', tarfile.REGTYPE)],
            [('x', b'123456', tarfile.REGTYPE)],
            [('/', b'x', tarfile.REGTYPE)],
        ]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                m.extract_tar(self.archive(entries), self.root/f'extract{i}', 5)
        for name in ('/etc/passwd', 'a/../b', 'a//b', 'a\\b', 'a:b', 'x\n'):
            with self.subTest(name=name), self.assertRaises(ValueError): m.member_name(name)

    def test_version_rejection(self):
        good = dict(model=0x20030014, version='2.01', region=0, isAccessory=False)
        m.supported(SimpleNamespace(**good))
        for key, value in [('model', 1), ('version', '3.00'), ('region', 1), ('isAccessory', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError): m.supported(SimpleNamespace(**{**good, key:value}))

    def test_prepare_sequence_and_failure_propagation(self):
        runtime = self.root/'runtime'
        (runtime/'analysis').mkdir(parents=True)
        (self.root/'prepare-assets.py').write_text('')
        calls = []
        m.prepare(self.root/'entry', runtime, self.root, lambda args, **kw: calls.append(args))
        self.assertIn('--verify-inputs',calls[0])
        self.assertIn('--fdat', calls[1])
        self.assertIn('--install-language-fonts', calls[2])
        self.assertIn('--check-runtime', calls[3])
        (runtime/'analysis/native-assets.json').write_text('{}')
        calls.clear()
        m.prepare(self.root/'entry', runtime, self.root, lambda args, **kw: calls.append(args))
        self.assertIn('--verify-inputs',calls[0])
        self.assertIn('--check-runtime', calls[1])
        def broken(*args, **kw): raise subprocess.CalledProcessError(1, args[0])
        with self.assertRaises(subprocess.CalledProcessError): m.prepare(self.root/'entry', runtime, self.root, broken)

    def test_prepare_only_never_launches_vm(self):
        with patch.object(m, 'discover', return_value=self.package), patch.object(m, 'cache_package', return_value=self.root/'entry'), patch.object(m, 'prepare') as prep, patch.object(m.subprocess, 'run') as run:
            self.assertEqual(m.main(['--prepare-only']), 0)
            prep.assert_called_once()
            run.assert_not_called()

    def test_launch_dispatch_and_early_runtime_mismatch(self):
        runtime = self.root/'runtime'
        analysis = runtime/'analysis'
        analysis.mkdir(parents=True)
        (analysis/'camera_ui.py').write_text('')
        with patch.object(m, 'discover', return_value=self.package) as discover, patch.object(m, 'cache_package', return_value=self.root/'entry'), patch.object(m, 'prepare'), patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=7)) as run:
            self.assertEqual(m.main(['--runtime', str(runtime), '--runtime-analysis', str(analysis)]), 7)
            self.assertIn(str(analysis/'camera_ui.py'),run.call_args.args[0])
            discover.reset_mock()
            self.assertEqual(m.main(['--runtime', str(runtime), '--runtime-analysis', str(self.root)]), 1)
            discover.assert_not_called()

    def test_sd_image_forwarding_and_symlink_rejection(self):
        runtime=self.root/'runtime';analysis=runtime/'analysis';analysis.mkdir(parents=True)
        (analysis/'camera_ui.py').write_text('')
        card=self.root/'card.img';card.write_bytes(b'virtual card')
        args=['--runtime',str(runtime),'--runtime-analysis',str(analysis),'--sd-image',str(card)]
        with patch.object(m,'discover',return_value=self.package),patch.object(m,'cache_package',return_value=self.root/'entry'),patch.object(m,'prepare'),patch.object(m.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(m.main(args),0)
            self.assertEqual(run.call_args.kwargs['env']['A7C2_SD_IMAGE'],str(card))
            run.reset_mock();card.unlink();card.symlink_to(self.package)
            self.assertEqual(m.main(args),1);run.assert_not_called()

    def test_overwrite_forwarding_and_symlink_rejection(self):
        runtime = self.root/'runtime'
        analysis = runtime/'analysis'
        analysis.mkdir(parents=True)
        (analysis/'camera_ui.py').write_text('')
        overwrite = self.root/'overwrite'
        overwrite.mkdir()
        payload = overwrite/'replacement.bin'
        payload.write_bytes(b'user supplied firmware replacement')
        args = ['--runtime', str(runtime), '--runtime-analysis', str(analysis),
                '--overwrite-dir', str(overwrite)]
        with patch.object(m, 'discover', return_value=self.package), \
                patch.object(m, 'cache_package', return_value=self.root/'entry'), \
                patch.object(m, 'prepare'), \
                patch.object(m.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(m.main(args), 0)
            self.assertEqual(run.call_args.kwargs['env']['A7C2_OVERWRITE_DIR'], str(overwrite))
            self.assertEqual(payload.read_bytes(), b'user supplied firmware replacement')
            self.assertEqual(self.package.read_bytes(), b'official test fixture')
            run.reset_mock()
            alias = self.root/'overwrite-alias'
            alias.symlink_to(overwrite, target_is_directory=True)
            args[-1] = str(alias)
            self.assertEqual(m.main(args), 1)
            run.assert_not_called()

    def test_prepare_failure_never_launches_overwrite_runtime(self):
        runtime = self.root/'runtime'
        analysis = runtime/'analysis'
        analysis.mkdir(parents=True)
        (analysis/'camera_ui.py').write_text('')
        overwrite = self.root/'overwrite'
        overwrite.mkdir()
        with patch.object(m, 'discover', return_value=self.package), \
                patch.object(m, 'cache_package', return_value=self.root/'entry'), \
                patch.object(m, 'prepare', side_effect=ValueError('asset verification failed')), \
                patch.object(m.subprocess, 'run') as run:
            self.assertEqual(m.main(['--runtime', str(runtime), '--runtime-analysis', str(analysis),
                                     '--overwrite-dir', str(overwrite)]), 1)
            run.assert_not_called()

    def test_cache_lock_and_insufficient_space_publish_nothing(self):
        cache = self.root/'cache'
        m.cache_package(self.package, cache, self.root, self.fake_unpack)
        with (cache/'owner.json').open('rb') as lock:
            m.fcntl.flock(lock, m.fcntl.LOCK_EX | m.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError): m.cache_package(self.package, cache, self.root, self.fake_unpack)
        new = self.root/'new-cache'
        with patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaises(ValueError): m.cache_package(self.package, new, self.root, self.fake_unpack)
        self.assertFalse((new/m.digest(self.package)).exists())
        self.assertFalse(list(new.glob('.*.staging-*')))

    def test_missing_full_sdk_is_explicit(self):
        with self.assertRaises(FileNotFoundError): m.sdk_modules(self.root)


if __name__ == '__main__':
    unittest.main()
