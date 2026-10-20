"""Host-only SD lifecycle, failure evidence, RM configuration and cpio tests."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('sd_image', HERE / 'sd-image.py')
SD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SD)
PINNED_SHA = 'f9f321b5c4768fe9c703cbac8b17b94aaa78b59a5e7da8497b7cdc2020f62b1e'


class SdImage(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / 'run'
        self.card = self.run / 'SD/card.img'
        self.report = self.run / 'SD/card.json'

    def invoke(self, command='ensure', run=None, env=None, success=True):
        result = subprocess.run([sys.executable, str(HERE / 'sd-image.py'), command,
                                 str(run or self.run)], capture_output=True, text=True,
                                env=env, timeout=40)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['ok'], success, data)
        return data

    def assert_failure_report(self, command='verify', **kwargs):
        self.report.write_text('{"ok":true,"stale":true}\n')
        result = self.invoke(command, success=False, **kwargs)
        self.assertEqual(json.loads(self.report.read_text()), result)
        self.assertNotIn('stale', result)
        self.assertTrue(result['error'])
        return result

    def test_template_sha_constant(self):
        self.assertEqual(SD.TEMPLATE_SHA256, PINNED_SHA)
        raw = SD.TEMPLATE.read_bytes()
        self.assertEqual(len(raw), 4194304)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PINNED_SHA)

    def test_ensure_create_and_idempotent_preserve_existing_card(self):
        first = self.invoke()
        self.assertTrue(first['created'])
        self.assertEqual(first['bytes'], 4194304)
        self.assertEqual(first['sha256'], PINNED_SHA)
        self.assertEqual(first['fsck_rc'], 0)
        self.assertEqual(json.loads(self.report.read_text()), first)
        # Change unallocated space: ensure must preserve a valid non-template card.
        with self.card.open('r+b') as stream:
            stream.seek(-1, os.SEEK_END)
            stream.write(b'!')
        before = self.card.stat()
        second = self.invoke()
        self.assertFalse(second['created'])
        self.assertNotEqual(second['sha256'], PINNED_SHA)
        self.assertEqual(self.card.stat().st_ino, before.st_ino)
        self.assertEqual(self.card.stat().st_mtime_ns, before.st_mtime_ns)

    def test_verify_readonly(self):
        self.invoke()
        before = self.card.stat()
        raw = self.card.read_bytes()
        result = self.invoke('verify')
        self.assertEqual(result['bpb']['sector_bytes'], 512)
        self.assertEqual(result['bpb']['total_sectors'], 8192)
        self.assertEqual(result['fsck_rc'], 0)
        self.assertFalse(result['created'])
        self.assertEqual(raw, self.card.read_bytes())
        self.assertEqual(before.st_mtime_ns, self.card.stat().st_mtime_ns)

    def test_ensure_refuses_to_replace_invalid_existing_card(self):
        self.card.parent.mkdir(parents=True)
        self.card.write_bytes(b'keep my bytes')
        before = self.card.stat()
        self.assert_failure_report('ensure')
        self.assertEqual(self.card.read_bytes(), b'keep my bytes')
        self.assertEqual(self.card.stat().st_ino, before.st_ino)

    def test_verify_truncation_overwrites_stale_success(self):
        self.invoke()
        with self.card.open('r+b') as stream:
            stream.truncate(512)
        result = self.assert_failure_report()
        self.assertEqual(result['bytes'], 512)
        self.assertIsNone(result['fsck_rc'])

    def test_verify_bad_bpb_overwrites_stale_success(self):
        self.invoke()
        for offset, value in ((510, b'\x00'), (11, b'\x00\x04'), (13, b'\x03'),
                              (14, b'\x00\x00'), (16, b'\x00'), (22, b'\x00\x00')):
            with self.subTest(offset=offset):
                raw = bytearray(SD.TEMPLATE.read_bytes())
                raw[offset:offset + len(value)] = value
                self.card.write_bytes(raw)
                result = self.assert_failure_report()
                self.assertIn('BPB', result['error'])
                self.assertIsNone(result['fsck_rc'])

    def test_verify_real_fsck_corruption_overwrites_stale_success(self):
        self.invoke()
        # The FAT media byte must agree with the intact BPB (0xf8).
        with self.card.open('r+b') as stream:
            stream.seek(512)
            stream.write(b'\x00')
        before = self.card.read_bytes()
        result = self.assert_failure_report()
        self.assertNotEqual(result['fsck_rc'], 0)
        self.assertIn('fsck.fat', result['error'])
        self.assertEqual(before, self.card.read_bytes())

    def test_missing_or_failed_fsck_never_succeeds(self):
        self.invoke()
        tools = self.root / 'tools'
        tools.mkdir()
        env = dict(os.environ, PATH=str(tools))
        result = self.assert_failure_report(env=env)
        self.assertIsNone(result['fsck_rc'])
        fsck = tools / 'fsck.fat'
        fsck.write_text('#!/bin/sh\n[ "$1" = "-n" ] || exit 99\necho deliberate-failure\nexit 4\n')
        fsck.chmod(0o700)
        result = self.assert_failure_report(env=env)
        self.assertEqual(result['fsck_rc'], 4)
        self.assertIn('deliberate-failure', result['fsck_output'])

    def test_symlink_ancestors_and_card_are_rejected(self):
        self.invoke()
        alias = self.root / 'alias'
        alias.symlink_to(self.run, target_is_directory=True)
        for command in ('ensure', 'verify'):
            self.invoke(command, run=alias, success=False)
            self.invoke(command, run=alias / '../run', success=False)
        self.card.rename(self.run / 'real.img')
        for target in (self.run / 'real.img', self.run / 'missing.img'):
            self.card.symlink_to(target)
            for command in ('ensure', 'verify'):
                self.assert_failure_report(command)
            self.card.unlink()
        self.card.parent.rename(self.run / 'real-SD')
        self.card.parent.symlink_to(self.run / 'real-SD', target_is_directory=True)
        self.invoke(success=False)
        self.assertEqual(hashlib.sha256((self.run / 'real.img').read_bytes()).hexdigest(), PINNED_SHA)

    def test_nonregular_card_rejected_without_blocking(self):
        self.card.parent.mkdir(parents=True)
        self.card.mkdir()
        self.assert_failure_report('ensure')
        self.card.rmdir()
        os.mkfifo(self.card)
        self.assert_failure_report('ensure')

    def test_verify_missing_card_records_failure(self):
        self.invoke('verify', success=False)
        self.assertFalse(self.run.exists())
        self.card.parent.mkdir(parents=True)
        self.assert_failure_report()
        self.assertFalse(self.card.exists())

    def test_report_symlink_is_not_followed(self):
        self.invoke()
        outside = self.root / 'outside.json'
        outside.write_text('untouched')
        self.report.unlink()
        self.report.symlink_to(outside)
        self.invoke('verify', success=False)
        self.assertEqual(outside.read_text(), 'untouched')

    def test_publish_exclusivity_and_failed_template_never_clobber(self):
        self.invoke()
        with SD.directory(self.card.parent) as parent:
            with self.assertRaises(FileExistsError):
                SD.publish(parent, 'card.img', b'overwrite', False)
        self.assertEqual(hashlib.sha256(self.card.read_bytes()).hexdigest(), PINNED_SHA)
        self.card.unlink()
        fake = self.root / 'template.fat'
        fake.write_bytes(b'bad template')
        with patch.object(SD, 'TEMPLATE', fake), patch('builtins.print'):
            self.assertEqual(SD.run('ensure', self.run), 1)
        self.assertFalse(self.card.exists())
        self.assertFalse(json.loads(self.report.read_text())['ok'])

    def test_strict_cli(self):
        for args in ([], ['ensure'], ['format', str(self.run)],
                     ['ensure', str(self.run), '--force'], ['verify', str(self.run), 'extra']):
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, str(HERE / 'sd-image.py'), *args],
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
        self.assertFalse(self.run.exists())

    def test_rm_environment_paths_override_caller_without_weakening_checks(self):
        # Reuse the existing full protocol harness with deliberately absent defaults.
        harness = (HERE / 'test-rm-file-device.c').read_text()
        original = 'native_rm_file_start("card","claim",&io,reg,unreg,statq)'
        self.assertEqual(harness.count(original), 1)
        source = self.root / 'rm-env.c'
        source.write_text(harness.replace(original,
                          'native_rm_file_start("absent-card","absent-claim",&io,reg,unreg,statq)'))
        binary = self.root / 'rm-env'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread',
                        '-I', str(HERE), str(HERE / 'rm-file-device.c'), str(source),
                        '-o', str(binary)], check=True, capture_output=True)
        for case in ('normal', 'symlink'):
            working = self.root / case
            working.mkdir()
            result = subprocess.run([str(binary), case], cwd=working, timeout=10,
                                    capture_output=True, text=True,
                                    env=dict(os.environ, MENU_RM_FILE_IMAGE='card',
                                             MENU_RM_FILE_CLAIM='selected.claim'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((working / 'selected.claim').is_file())
            self.assertFalse((working / 'absent-claim').exists())

    def test_cpio_sd_inclusion_is_optional_and_does_not_modify_source(self):
        # Execute the full builder against tiny temporary inputs, never real menu-root.
        builder = self.root / 'builder'
        builder.mkdir()
        shutil.copyfile(HERE / 'prepare-menu-initramfs.sh', builder / 'prepare-menu-initramfs.sh')
        root = builder / 'menu-root'
        (root / 'system').mkdir(parents=True)
        (root / 'usr/lib').mkdir(parents=True)
        (root / 'usr/lib/libIMDB.so').write_bytes(b'old')
        boot = builder / 'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked'
        boot.mkdir(parents=True)
        (boot / 'one.bin').write_bytes(b'bin')
        (boot / 'one.hcd').write_bytes(b'hcd')
        for name in ('libIMDB-menu.so', 'menu-observe.so', 'native-assets.json'):
            (builder / name).write_bytes(b'test')
        self.invoke()
        script = ['bash', str(builder / 'prepare-menu-initramfs.sh')]
        env = dict(os.environ)
        env.pop('MENU_SD_IMAGE', None)
        env.update(PRELOAD_ALL='0', CPIO_PAD_BYTES='0')
        for include in (False, True, False):
            if include:
                env['MENU_SD_IMAGE'] = str(self.card)
            else:
                env.pop('MENU_SD_IMAGE', None)
            result = subprocess.run(script, env=env, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archive = builder / 'menu-initramfs.cpio'
            listing = subprocess.run(['cpio', '-it', '-F', str(archive)],
                                     capture_output=True, text=True, check=True)
            self.assertEqual('simulation/sd-card.fat' in listing.stdout.splitlines(), include,
                             listing.stdout + listing.stderr + result.stdout + result.stderr)
            self.assertFalse((root / 'simulation/sd-card.fat').exists())
            if include:
                self.assertIn(f'SD_IMAGE_SHA256={PINNED_SHA}', result.stdout)
                extracted = subprocess.run(['cpio', '-i', '--to-stdout', '-F', str(archive),
                                            'simulation/sd-card.fat'], capture_output=True, check=True)
                self.assertEqual(hashlib.sha256(extracted.stdout).hexdigest(), PINNED_SHA)
        env['MENU_SD_IMAGE'] = str(self.card.parent)
        self.assertNotEqual(subprocess.run(script, env=env, capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
