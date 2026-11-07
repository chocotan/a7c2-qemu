#!/usr/bin/env python3
"""Fixed-file package host boundaries and actual deterministic ext2 replay."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-dev-file-package.py'))
DEV = runpy.run_path(str(HERE / 'p1-dev-install.py'))
V = runpy.run_path(str(HERE / 'virtual-update.py'))
M['SCRATCH'].mkdir(parents=True, exist_ok=True)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class FixedFile(unittest.TestCase):
    def temporary(self):
        return tempfile.TemporaryDirectory(prefix='host-test-', dir=M['SCRATCH'])

    def trees(self):
        common = dict(mode=stat.S_IFREG | 0o755, uid=0, gid=0, mtime=1)
        before = {'/': dict(mode=stat.S_IFDIR | 0o755, uid=0, gid=0, size=0, mtime=1),
                  '/bin': dict(mode=stat.S_IFDIR | 0o755, uid=0, gid=0, size=0, mtime=1)}
        before.update({p: dict(common, **copy.deepcopy(row)) for p, row in M['CORE'].items()})
        after = copy.deepcopy(before)
        after['/bin']['mtime'] = 3
        after[M['MARKER']] = dict(mode=stat.S_IFREG | 0o755, uid=0, gid=0,
            size=len(M['SCRIPT']), mtime=3, sha256=M['FILE_SHA'])
        return before, after

    def test_exact_ascii_marker_and_only_required_directory_metadata(self):
        self.assertEqual(M['SCRIPT'], b'#!/bin/sh\necho QEMU_PACKAGED_SYSTEM_FILE_V1\n'
            b"busybox grep -E '^(Uid|Gid):' /proc/$$/status\n")
        M['SCRIPT'].decode('ascii')
        before, after = self.trees()
        delta = M['_tree_delta'](before, after)
        self.assertEqual(delta['added'], [M['MARKER']])
        self.assertEqual(delta['before_nodes'] + 1, delta['after_nodes'])
        for key, value in [('mode', stat.S_IFREG | 0o777), ('uid', 1), ('gid', 1),
                           ('sha256', '0' * 64), ('size', len(M['SCRIPT']) + 1)]:
            bad = copy.deepcopy(after); bad[M['MARKER']][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): M['_tree_delta'](before, bad)
        for path, key, value in [('/bin', 'uid', 1), ('/', 'mtime', 3),
                                 ('/bin/bootin.elf', 'sha256', 'b' * 64),
                                 ('/lib/appFw.so', 'mode', stat.S_IFREG | 0o644)]:
            bad = copy.deepcopy(after); bad[path][key] = value
            with self.subTest(path=path, key=key), self.assertRaises(ValueError): M['_tree_delta'](before, bad)
        bad = copy.deepcopy(after); bad['/bin/extra'] = dict(after[M['MARKER']])
        with self.assertRaises(ValueError): M['_tree_delta'](before, bad)
        bad = copy.deepcopy(after); del bad['/bin/bootin.elf']
        with self.assertRaises(ValueError): M['_tree_delta'](before, bad)

    def test_whole_plaintext_comparison_rejects_unlisted_bytes_and_length(self):
        with self.temporary() as td:
            root = Path(td); a, b = root / 'old', root / 'new'
            a.write_bytes(bytes(range(256)) * 4)
            changed = bytearray(a.read_bytes()); changed[8:12] = b'CRC!'; changed[800:810] = b'markerfile'
            b.write_bytes(changed)
            with a.open('rb') as old, b.open('rb') as new, patch.dict(
                    M['_plain_regions'].__globals__, PLAIN_BYTES=1024):
                M['_plain_regions'](V, old.fileno(), new.fileno(), [(8,4), (800,10)])
                for offset in (0, 512, 799, 810, 1023):
                    bad = bytearray(changed); bad[offset] ^= 1; b.write_bytes(bad)
                    with self.assertRaises(ValueError):
                        M['_plain_regions'](V, old.fileno(), new.fileno(), [(8,4), (800,10)])
                b.write_bytes(changed + b'x')
                with self.assertRaises(ValueError):
                    M['_plain_regions'](V, old.fileno(), new.fileno(), [(8,4), (800,10)])

    @unittest.skipUnless(shutil.which('debugfs') and shutil.which('mke2fs'), 'e2fsprogs required')
    def test_real_copied_ext2_replay_and_cross_channel_readback(self):
        with self.temporary() as td:
            root = Path(td); source = root / 'official.ext2'; size = 16 * 1024**2
            with source.open('xb') as stream: stream.truncate(size)
            subprocess.run(['mke2fs', '-q', '-t', 'ext2', '-F', str(source)], check=True, capture_output=True)
            subprocess.run(['debugfs', '-w', '-R', 'mkdir /bin', str(source)], check=True, capture_output=True)
            old_sha = sha(source); digests = []
            for name in ('build', 'replay'):
                out = root / name; out.mkdir(); target = out / 'p15.ext2'
                with patch.dict(M['_edit_image'].__globals__, IMAGE_BYTES=size):
                    M['_edit_image'](source, target, out, {'sha_file': sha})
                digests.append(sha(target))
                self.assertEqual((out / 'marker.readback').read_bytes(), M['SCRIPT'])
                status = (out / 'debugfs-stat.stdout').read_text()
                self.assertRegex(status, r'User:\s+0\s+Group:\s+0')
            self.assertEqual(digests[0], digests[1])
            self.assertEqual(sha(source), old_sha)
            with (root / 'replay/p15.ext2').open('r+b') as stream:
                stream.seek(size - 1); stream.write(b'!')
            self.assertNotEqual(sha(root / 'replay/p15.ext2'), digests[0])

    def test_versions_output_location_and_host_space_fail_before_artifacts(self):
        for current in (None, '', '2.2', '2.02', '2.03', '3.00'):
            with self.subTest(current=current), self.assertRaises(ValueError): M['_version'](current)
        for output in ('/dev/sda', '/tmp/diagnostic-package', M['SCRATCH']):
            with self.assertRaises(ValueError): M['_output'](output)
        with self.temporary() as td:
            root = Path(td); output = root / 'absent'
            with patch.object(shutil, 'disk_usage', return_value=SimpleNamespace(free=1)):
                with self.assertRaisesRegex(ValueError, 'host space'): M['_output'](output)
            self.assertFalse(output.exists())
            scoped = root / 'scoped'; destination = scoped / 'verification'
            with patch.object(shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * M['PACKAGE_BYTES'])):
                M['_output'](destination, scratch=scoped)
            self.assertTrue((destination / 'host-space.json').is_file())
            with self.assertRaises(ValueError): M['_output'](Path('/tmp/not-allowed'), scratch='/tmp')
            with self.assertRaises(ValueError): M['_output'](root / 'scoped/../escape', scratch=root / 'scoped')

    def test_signature_contract_retains_all_crypto_fields_and_preserves_raw_input(self):
        row = dict(status='invalid', algorithm='RSA-2048-PKCS1-v1.5-SHA256', returncode=1,
                   signed_sha256='a' * 64, key_der_sha256='b' * 64,
                   stock_receiver_acceptance='unknown', stdout='', stderr='1111:error:bad signature')
        expected = M['_signature'](row)
        self.assertEqual(expected, M['_signature'](dict(row, stderr='2222:error:bad signature')))
        self.assertEqual(row['stderr'], '1111:error:bad signature')
        self.assertEqual(set(expected), set(row) - {'stdout', 'stderr'})
        for key in expected:
            changed = dict(row); changed[key] = None
            self.assertNotEqual(expected, M['_signature'](changed))

    def test_contract_recomputes_instead_of_trusting_receipt_flags_or_expected_sha(self):
        with self.temporary() as td:
            root = Path(td); receipt = root / 'receipt.json'
            actual = dict(schema=M['SCHEMA'], kind=M['KIND'], current_version='2.01',
                original={'path':'/official'}, derived={'path':'/derived'}, fwtool_dir='/fwtool',
                proof={'image_sha256':'pinned-recomputed'})
            receipt.write_text(json.dumps(actual))
            def execute(argv, **kwargs):
                out = Path(argv[argv.index('--output') + 1]); out.mkdir()
                (out / 'dev-file-package.json').write_text(json.dumps(actual))
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            u = DEV['api']()
            with patch.object(subprocess, 'run', side_effect=execute) as called:
                self.assertEqual(M['contract'](receipt, u['record'](receipt)['sha256'])['value'], actual)
                argv = called.call_args.args[0]
                scratch = Path(argv[argv.index('--scratch') + 1])
                self.assertTrue(scratch.is_relative_to(M['SCRATCH']))
                self.assertEqual(called.call_args.kwargs['env']['TMPDIR'], str(scratch))
                forged = copy.deepcopy(actual); forged['proof']['image_sha256'] = 'arbitrary-expected-sha'
                receipt.write_text(json.dumps(forged))
                with self.assertRaisesRegex(ValueError, 'recomputation'):
                    M['contract'](receipt, u['record'](receipt)['sha256'])
                with self.assertRaises(ValueError): M['contract'](receipt, '0' * 64)

    def test_explicit_contract_output_root_and_install_dispatch(self):
        with self.temporary() as td:
            root = Path(td); receipt = root / 'receipt.json'; selected = root / 'selected'
            actual = dict(schema=M['SCHEMA'], kind=M['KIND'], current_version='2.01',
                original={'path':'/official'}, derived={'path':'/derived'}, fwtool_dir='/fwtool')
            receipt.write_text(json.dumps(actual)); invocations = []
            def execute(argv, **kwargs):
                invocations.append((argv, kwargs))
                out = Path(argv[argv.index('--output') + 1]); out.mkdir()
                (out / 'dev-file-package.json').write_text(json.dumps(actual))
                return SimpleNamespace(returncode=0, stdout=b'', stderr=b'')
            u = DEV['api']()
            with patch.object(subprocess, 'run', side_effect=execute):
                M['contract'](receipt, u['record'](receipt)['sha256'], output_root=selected)
            argv, kwargs = invocations[0]; scratch = Path(argv[argv.index('--scratch') + 1])
            self.assertTrue(scratch.is_relative_to(selected));self.assertEqual(kwargs['env']['TMPDIR'], str(scratch))
            with self.assertRaises(ValueError):M['contract'](receipt, u['record'](receipt)['sha256'], output_root='/tmp')
            original_api = DEV['api']; calls = []
            def load(name='update-boot.py'):
                if name == 'p1-dev-file-package.py':
                    return dict(contract=lambda *args, **kwargs: calls.append((args, kwargs)) or {'verified':'fresh-recomputation'})
                return original_api(name)
            with patch.dict(DEV['package_contract'].__globals__, api=load):
                result = DEV['package_contract'](receipt, u['record'](receipt)['sha256'], output_root=selected)
            self.assertEqual(result, {'verified':'fresh-recomputation'})
            self.assertEqual(calls, [((receipt, u['record'](receipt)['sha256']), {'output_root':selected})])
            boot = (HERE / 'update-boot.py').read_text(); install = (HERE / 'p1-dev-install.py').read_text()
            self.assertEqual(boot.count("output_root=output / 'dev-preflight'"), 2)
            self.assertEqual(install.count("output_root=output / 'dev-preflight'"), 1)
            self.assertEqual(install.count("binding=binding, **output_options"), 1)
            self.assertIn("return clone_contract(instance, output, u['record'](output)['sha256'], **options)", install)

    def test_dev_dispatch_keeps_legacy_environment_and_selects_only_fixed_kind(self):
        legacy = dict(package_contract=dict(value=dict(schema=DEV['PACKAGE_SCHEMA'], delta='version-only-2.02')))
        self.assertEqual(DEV['install_environment'](legacy), DEV['ENV'])
        with self.assertRaises(ValueError):
            DEV['install_environment'](dict(package_contract=dict(value=dict(schema=DEV['PACKAGE_SCHEMA']))))
        fixed = dict(package_contract=dict(value=dict(schema=M['SCHEMA'], kind=M['KIND'])))
        env = DEV['install_environment'](fixed)
        self.assertEqual(env['A7C2_P1_DEV_INSTALL'], 'fixed-system-file-v1')
        self.assertEqual(DEV['ENV']['A7C2_P1_DEV_INSTALL'], 'version-only-2.02')
        text = DEV['bootstrap_source'](install_kind=env['A7C2_P1_DEV_INSTALL'])
        self.assertIn('[ "$A7C2_P1_DEV_INSTALL" = fixed-system-file-v1 ] || return 125', text)
        subprocess.run(['/bin/sh', '-n'], input=text.encode(), check=True, capture_output=True)
        with self.assertRaises(ValueError): DEV['bootstrap_source'](install_kind='anything')
        bad = copy.deepcopy(fixed); bad['package_contract']['value']['kind'] = 'arbitrary-files'
        with self.assertRaises(ValueError): DEV['install_environment'](bad)
        with self.temporary() as td:
            receipt = Path(td) / 'receipt.json'; receipt.write_text(json.dumps(dict(schema=M['SCHEMA'], kind=M['KIND'])))
            u = DEV['api'](); calls = []; original_api = DEV['api']
            def load(name='update-boot.py'):
                if name == 'p1-dev-file-package.py':
                    return dict(contract=lambda *args: calls.append(args) or {'verified':'fresh-recomputation'})
                return original_api(name)
            with patch.dict(DEV['package_contract'].__globals__, api=load):
                result = DEV['package_contract'](receipt, u['record'](receipt)['sha256'])
            self.assertEqual(result, {'verified':'fresh-recomputation'})
            self.assertEqual(calls, [(receipt, u['record'](receipt)['sha256'])])


if __name__ == '__main__':
    unittest.main(verbosity=2)
