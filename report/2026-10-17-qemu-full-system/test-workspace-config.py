#!/usr/bin/env python3
"""Storage/locking fault tests; real BK4 validation is a separate integration check."""
import fcntl
import hashlib
import json
import io
from contextlib import redirect_stdout
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'workspace-config.py'))


class WorkspaceConfiguration(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.reference = b'fixture PP'
        self.enterContext(mock.patch.dict(API['PUBLISH']['BACKUP'], {
            'FILE_BYTES': 3, 'OFFICIAL_PP_SHA256': hashlib.sha256(self.reference).hexdigest(),
            'validate': lambda data, reference: {'records': []}}))
        self.run = self.root / 'run'
        self.run.mkdir()
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.prepare(b'one', b'two')

    def prepare(self, first, second):
        items = []
        for name, data in [('Backup.bin', first), ('Backup.bak', second)]:
            (self.run / name).write_bytes(data)
            items.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        (self.run / 'console.log').write_bytes(b'closed real-run fixture')
        (self.run / 'inputs.json').write_text(json.dumps({'source': 'official-bodydata-derived',
                                                         'bodydata_sha256': API['BODYDATA_SHA']}))
        self.result = {'state': 'observation-completed', 'input_producer_stopped_verified': True,
                       'config_sync': {'subsystem': 719, 'verified': True},
                       'config_export': {'verified': True, 'files': items},
                       'config_export_trigger': 'observation-deadline',
                       'terminal_console_sha256': hashlib.sha256((self.run / 'console.log').read_bytes()).hexdigest()}
        (self.run / 'result.json').write_text(json.dumps(self.result))

    def test_save_and_reopen_use_immutable_verified_pair(self):
        with API['locked'](self.workspace) as store:
            self.assertIsNone(store.current(self.reference))
            pointer = store.save_run(self.run, self.reference)
            generation = store.current(self.reference)
            self.assertEqual(generation['identity'], pointer['generation'])
            self.assertEqual(generation['files'], {'BACKUP.BIN': b'one', 'BACKUP.BAK': b'two'})
            for name in ('Backup.bin', 'Backup.bak'):
                self.assertEqual((generation['directory'] / name).stat().st_mode & 0o777, 0o600)
        with API['locked'](self.workspace) as reopened:
            self.assertEqual(reopened.current(self.reference)['identity'], pointer['generation'])
        with self.assertRaisesRegex(RuntimeError, 'lock lifetime'):
            store.current(self.reference)

    def test_published_runtime_uses_verified_parent_cache_when_saving_again(self):
        runtime = self.root / 'published-runtime'
        (runtime / 'analysis/root/partitions').mkdir(parents=True)
        (runtime / 'analysis/official-pp.bin').write_bytes(self.reference)
        extract = mock.Mock(side_effect=AssertionError('published volume is not the PP reference'))
        with mock.patch.dict(API['STATE'], {'extract': extract}):
            self.assertEqual(API['official_reference'](runtime), self.reference)
        extract.assert_not_called()

    def test_invalid_parent_cache_is_refused_without_fallback(self):
        runtime = self.root / 'invalid-runtime'
        (runtime / 'analysis').mkdir(parents=True)
        (runtime / 'analysis/official-pp.bin').write_bytes(b'corrupt cache')
        extract = mock.Mock(return_value=self.reference)
        with mock.patch.dict(API['STATE'], {'extract': extract}):
            with self.assertRaisesRegex(ValueError, 'no verified official PP reference'):
                API['official_reference'](runtime)
        extract.assert_not_called()

    def test_first_runtime_without_cache_checks_the_actual_volume(self):
        runtime = self.root / 'factory-runtime'
        (runtime / 'analysis/root/partitions').mkdir(parents=True)
        image = runtime / 'analysis/root/partitions/nflasha2.img'
        image.write_bytes(b'FAT fixture')
        extract = mock.Mock(return_value=self.reference)
        with mock.patch.dict(API['STATE'], {'extract': extract}):
            self.assertEqual(API['official_reference'](runtime), self.reference)
        extract.assert_called_once_with(image, 'BACKUP.BIN')

    def test_offline_preview_returns_the_validated_current_token_without_reset(self):
        runtime = self.root / 'preview-runtime'
        (runtime / 'analysis').mkdir(parents=True)
        (runtime / 'analysis/official-pp.bin').write_bytes(self.reference)
        with API['locked'](self.workspace) as store:
            saved = store.save_run(self.run, self.reference)
        command = ['workspace-config.py','--workspace',str(self.workspace),'--runtime',str(runtime),'--preview']
        output = io.StringIO()
        with mock.patch.object(sys,'argv',command), redirect_stdout(output):
            self.assertEqual(API['main'](),0)
        self.assertEqual(output.getvalue(), 'WORKSPACE_CONFIG_PREVIEW '+saved['generation']+' backup\n')
        with API['locked'](self.workspace) as store:
            self.assertEqual(store.current(self.reference)['identity'],saved['generation'])

    def test_preview_cannot_bypass_an_active_runtime(self):
        runtime = self.root / 'busy-preview-runtime'
        (runtime / 'analysis').mkdir(parents=True)
        (runtime / 'analysis/official-pp.bin').write_bytes(self.reference)
        with (runtime / 'analysis/.run.lock').open('a') as active:
            fcntl.flock(active, fcntl.LOCK_EX | fcntl.LOCK_NB)
            command = ['workspace-config.py','--workspace',str(self.workspace),'--runtime',str(runtime),'--preview']
            with mock.patch.object(sys,'argv',command), self.assertRaisesRegex(RuntimeError,'runtime is busy'):
                API['main']()

    def test_pointer_failure_preserves_old_generation(self):
        with API['locked'](self.workspace) as store:
            old = store.save_run(self.run, self.reference)
            self.prepare(b'new', b'bak')
            real = os.replace
            def fail(source, target):
                if Path(target).name == 'current.json':
                    raise OSError('pointer write failed')
                return real(source, target)
            with mock.patch.object(os, 'replace', side_effect=fail):
                with self.assertRaisesRegex(OSError, 'pointer write failed'):
                    store.save_run(self.run, self.reference, old['generation'])
            self.assertEqual(store.current(self.reference)['identity'], old['generation'])

    def test_post_replace_sync_failure_is_uncertain_and_requires_reload(self):
        with API['locked'](self.workspace) as store:
            old = store.save_run(self.run, self.reference)
            self.prepare(b'new', b'bak')
            original = API['STATE']['sync_directory']
            root = self.workspace / '.a7c2/config'
            failed = []
            def fail_once(path):
                pointer = json.loads((root / 'current.json').read_text())
                if Path(path) == root and pointer['generation'] != old['generation'] and not failed:
                    failed.append(True)
                    raise OSError('directory sync failed')
                return original(path)
            with mock.patch.dict(API['STATE'], {'sync_directory': fail_once}):
                with self.assertRaisesRegex(API['PublicationUncertain'], 'durability unknown'):
                    store.save_run(self.run, self.reference, old['generation'])
            current = store.current(self.reference)
            self.assertNotEqual(current['identity'], old['generation'])
            self.assertEqual(current['files']['BACKUP.BIN'], b'new')
            self.assertTrue((root / 'generations' / old['generation']).exists())
            with self.assertRaises(API['Conflict']):
                store.save_run(self.run, self.reference, old['generation'])

    def test_cas_refuses_a_stale_generation_without_overwriting_new_values(self):
        with API['locked'](self.workspace) as store:
            first = store.save_run(self.run, self.reference)
            self.prepare(b'new', b'bak')
            with self.assertRaises(API['Conflict']):
                store.save_run(self.run, self.reference)
            second = store.save_run(self.run, self.reference, first['generation'])
            self.prepare(b'old', b'bad')
            with self.assertRaises(API['Conflict']):
                store.save_run(self.run, self.reference, first['generation'])
            self.assertEqual(store.current(self.reference)['identity'], second['generation'])

    def test_identical_bytes_after_reset_do_not_reuse_a_stale_cas_token(self):
        with API['locked'](self.workspace) as store:
            first = store.save_run(self.run, self.reference)
            reset = store.reset(self.reference, first['generation'], confirmed=True)
            again = store.save_run(self.run, self.reference, reset['generation'])
            self.assertNotEqual(first['generation'], again['generation'])
            self.assertEqual(store.current(self.reference)['files']['BACKUP.BIN'], b'one')
            with self.assertRaises(API['Conflict']):
                store.save_run(self.run, self.reference, first['generation'])

    def test_existing_content_named_generations_remain_readable(self):
        with API['locked'](self.workspace) as store:
            selected = store.save_run(self.run, self.reference)
            current = store.current(self.reference)
            legacy_name = store.identity(current['files'])
            legacy = current['directory'].with_name(legacy_name)
            current['directory'].rename(legacy)
            manifest_path = legacy / 'config-persistence.json'
            manifest = json.loads(manifest_path.read_text())
            manifest.pop('workspace_generation')
            manifest.pop('payload_identity')
            manifest_path.write_bytes(API['encode'](manifest))
            pointer = {'schema': 'workspace-config-pointer-v1', 'generation': legacy_name,
                       'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
            (self.workspace / '.a7c2/config/current.json').write_bytes(API['encode'](pointer))
            self.assertEqual(store.current(self.reference)['identity'], legacy_name)
            updated = store.save_run(self.run, self.reference, legacy_name)
            self.assertNotEqual(updated['generation'], legacy_name)
            self.assertEqual(store.current(self.reference)['files']['BACKUP.BIN'], b'one')

    def test_reset_is_an_explicit_cas_tombstone_and_preserves_history_and_sd(self):
        sd = self.workspace / 'SD'
        sd.mkdir()
        (sd / 'keep.jpg').write_bytes(b'user data')
        with API['locked'](self.workspace) as store:
            saved = store.save_run(self.run, self.reference)
            old = store.current(self.reference)
            with self.assertRaisesRegex(ValueError, 'confirmation'):
                store.reset(self.reference, saved['generation'], confirmed=False)
            reset = store.reset(self.reference, saved['generation'], confirmed=True)
            current = store.current(self.reference)
            self.assertEqual(current['state'], 'reset')
            self.assertIsNone(current['files'])
            self.assertEqual((old['directory'] / 'Backup.bin').read_bytes(), b'one')
            self.assertEqual((sd / 'keep.jpg').read_bytes(), b'user data')
            with self.assertRaises(API['Conflict']):
                store.reset(self.reference, saved['generation'], confirmed=True)
            self.prepare(b'new', b'bak')
            restored = store.save_run(self.run, self.reference, reset['generation'])
            self.assertEqual(store.current(self.reference)['state'], 'backup')
            self.assertEqual(store.current(self.reference)['identity'], restored['generation'])

    def test_reset_selection_keeps_factory_volume_without_publishing_old_backup(self):
        runtime = self.root / 'reset-target'
        (runtime / 'analysis/root/partitions').mkdir(parents=True)
        image = runtime / 'analysis/root/partitions/nflasha2.img'
        image.write_bytes(b'unchanged factory fixture')
        with API['locked'](self.workspace) as store:
            saved = store.save_run(self.run, self.reference)
            reset = store.reset(self.reference, saved['generation'], confirmed=True)
            publish = mock.Mock()
            with mock.patch.dict(API['STATE'], {'extract': mock.Mock(return_value=self.reference)}), \
                    mock.patch.dict(API['PUBLISH'], {'publish_locked': publish}):
                self.assertEqual(store.load_into(runtime), reset['generation'])
            publish.assert_not_called()
            self.assertEqual(image.read_bytes(), b'unchanged factory fixture')

    def test_low_or_unknown_space_does_not_select_a_new_generation(self):
        with API['locked'](self.workspace) as store:
            old = store.save_run(self.run, self.reference)
            self.prepare(b'new', b'bak')
            for probe in (mock.Mock(f_bavail=0, f_frsize=4096), OSError('space unknown')):
                with self.subTest(probe=probe):
                    options = {'side_effect': probe} if isinstance(probe, Exception) else {'return_value': probe}
                    with mock.patch.object(os, 'fstatvfs', **options):
                        with self.assertRaisesRegex(ValueError, 'free space'):
                            store.save_run(self.run, self.reference, old['generation'])
                    self.assertEqual(store.current(self.reference)['identity'], old['generation'])

    def test_missing_pointer_in_a_written_store_is_damage_not_factory_fallback(self):
        with API['locked'](self.workspace) as store:
            store.save_run(self.run, self.reference)
            (self.workspace / '.a7c2/config/current.json').unlink()
            with self.assertRaisesRegex(ValueError, 'missing current pointer'):
                store.current(self.reference)

    def test_changed_lock_identity_is_rejected_before_reading_or_writing(self):
        with API['locked'](self.workspace) as store:
            lock = self.workspace / '.a7c2/config.lock'
            lock.rename(lock.with_name('old-lock'))
            lock.touch(mode=0o600)
            with self.assertRaisesRegex(ValueError, 'lock identity changed'):
                store.current(self.reference)

    def test_tampered_export_or_console_does_not_replace_current(self):
        with API['locked'](self.workspace) as store:
            old = store.save_run(self.run, self.reference)
            (self.run / 'Backup.bin').write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'no longer match'):
                store.save_run(self.run, self.reference)
            self.assertEqual(store.current(self.reference)['identity'], old['generation'])
            self.prepare(b'new', b'bak')
            (self.run / 'console.log').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'console differs'):
                store.save_run(self.run, self.reference)

    def test_failed_or_private_source_run_is_refused(self):
        with API['locked'](self.workspace) as store:
            self.result['config_sync']['verified'] = False
            (self.run / 'result.json').write_text(json.dumps(self.result))
            with self.assertRaisesRegex(ValueError, 'lifecycle'):
                store.save_run(self.run, self.reference)
            (self.run / 'inputs.json').write_text('{"source":"private-full-dump"}')
            with self.assertRaisesRegex(ValueError, 'official BODYDATA'):
                store.save_run(self.run, self.reference)

    def test_lock_is_exclusive_and_inherited_child_does_not_unlock_parent(self):
        with API['locked'](self.workspace) as store:
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                with API['locked'](self.workspace):
                    self.fail('second session acquired the lock')
            code = ('import runpy,sys; m=runpy.run_path(sys.argv[1]); '
                    'c=m["locked"](sys.argv[2],int(sys.argv[3])); c.__enter__(); c.__exit__(None,None,None)')
            child = subprocess.run([sys.executable, '-B', '-c', code, str(HERE / 'workspace-config.py'),
                                    str(self.workspace), str(store.fd)], pass_fds=(store.fd,),
                                   capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                with API['locked'](self.workspace):
                    self.fail('child released the parent lock')

    def test_config_symlink_or_corrupt_current_does_not_fall_back_to_factory(self):
        with API['locked'](self.workspace) as store:
            old = store.save_run(self.run, self.reference)
            current = self.workspace / '.a7c2/config/current.json'
            current.write_text('{"schema":"wrong"}')
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                store.current(self.reference)
            current.unlink()
            current.symlink_to(self.run / 'result.json')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                store.current(self.reference)
            current.unlink()
            self.assertTrue((self.workspace / '.a7c2/config/generations' / old['generation']).exists())


if __name__ == '__main__':
    unittest.main()
