#!/usr/bin/env python3
"""Host-only explicit dev composition boundaries; no QEMU/USB/device access."""
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-dev-install.py'))
U = M['api']()
I = M['api']('newp1-virtual-install.py')
DTEST = runpy.run_path(str(HERE / 'test-dev-update-profile.py'))


class DevInstall(unittest.TestCase):
    def valid(self):
        return dict(mode=M['MODE'], read_only=False, allow_updater_writes=True,
            allow_dev_signature_bypass=True, media={'bound': True}, sd={'image': 1},
            module=dict(protocol=U['PROTOCOL'], build_bound=True, large_io_fix_bound=True,
                updater_write_eligible=True, module_sha256=U['CURRENT_MODULE_SHA'],
                kernel_sha256=U['KERNEL_SHA'], driver={'sha256': U['CURRENT_DRIVER_SHA']}))

    def test_exact_dev_selection_and_existing_module_boundary(self):
        valid = self.valid(); M['admit'](M['PROFILE'], **valid)
        for key, value in [('mode', 'official'), ('mode', None), ('read_only', True), ('read_only', 0),
            ('allow_dev_signature_bypass', False), ('allow_dev_signature_bypass', 1),
            ('allow_updater_writes', False), ('allow_updater_writes', 1), ('media', None), ('sd', None)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                M['admit'](M['PROFILE'], **dict(valid, **{key: value}))
        for profile in (None, I['PROFILE'], 'original-p1-sd-readonly-v1', 'physical'):
            with self.assertRaises(ValueError): M['admit'](profile, **valid)
        for key in valid['module']:
            bad = copy.deepcopy(valid); bad['module'][key] = False
            with self.subTest(module=key), self.assertRaises(ValueError): M['admit'](M['PROFILE'], **bad)
        with self.assertRaises(ValueError): I['admit'](I['PROFILE'], **{k:v for k,v in valid.items() if k != 'allow_dev_signature_bypass'})

    def test_builder_requires_separate_explicit_authorization_before_any_output(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'absent'
            valid = dict(mode=M['MODE'], install_profile=M['PROFILE'], read_only=False, allow_updater_writes=True,
                allow_dev_signature_bypass=True, original_resources=True, media_resources='/media', bodydata='/body',
                install_receipt='/receipt', install_receipt_sha256='0' * 64)
            for changes in ({'allow_dev_signature_bypass': False}, {'mode': 'official'}, {'install_profile': I['PROFILE']},
                {'install_profile': None}, {'sd_read_profile': 'original-p1-sd-readonly-v1'}, {'read_only': True},
                {'allow_updater_writes': False}, {'original_resources': False}, {'media_resources': None},
                {'bodydata': None}, {'install_receipt': None}, {'install_receipt_sha256': None}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    U['build']('/not-instance', '/runtime', out, **dict(valid, **changes))
            self.assertFalse(out.exists())

    def test_full_plaintext_diff_refuses_arbitrary_new_abi_payload_or_length(self):
        old = bytearray(512); old[:8] = b'UDTRFIRM'; old[12:16] = b'0100'; old[32:34] = b'\x01\x02'
        after = bytearray(old); after[32] = 2; after[8:12] = b'CRC!'
        tail = bytes(range(256)) * 4300
        result = M['_plain_diff'](io.BytesIO(old + tail), io.BytesIO(after + tail), bytes(after))
        self.assertTrue(result['all_payload_bytes_identical'])
        self.assertEqual(result['original_sha256'], hashlib.sha256(old + tail).hexdigest())
        for data in (after + tail[:-1], after + tail + b'x', after + tail[:-1] + b'!', old + tail):
            with self.assertRaises(ValueError): M['_plain_diff'](io.BytesIO(old + tail), io.BytesIO(data), bytes(after))

    def test_encoded_diff_keeps_prefix_chunks_payload_iv_footer(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            paths = [Path(td) / n for n in ('old', 'new')]
            data = bytes(range(256)) * 9
            paths[0].write_bytes(data); changed = bytearray(data); changed[64:68] = b'NEW!'; changed[-4:] = b'CRC!'
            paths[1].write_bytes(changed)
            v = M['api']('virtual-update.py')
            with paths[0].open('rb') as a, paths[1].open('rb') as b:
                sources = [SimpleNamespace(fd=f.fileno(), info=os.fstat(f.fileno())) for f in (a,b)]
                chunks = {b'FDAT': (64, 2048 + 272), b'DEND': (len(data) - 4, 4)}
                M['_encoded_diff'](v, *sources, chunks)
                for offset in (0, 600, len(data) - 10):
                    bad = bytearray(changed); bad[offset] ^= 1; paths[1].write_bytes(bad)
                    with self.assertRaises(ValueError): M['_encoded_diff'](v, *sources, chunks)

    def test_receiver_readback_reconstructs_pinned_original_and_checks_receipt(self):
        d = DTEST['PROFILE']; data = DTEST['fixture']()
        with tempfile.TemporaryDirectory() as td, patch.object(d, '_SOURCE_FACTS', {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}):
            p = Path(td); source = p / 'stock'; target = p / 'dev'; source.write_bytes(data)
            receipt = d.derive_receiver(source, target)
            result = d.verify_derived_receiver(target, receipt)
            self.assertTrue(result['all_other_bytes_identical']); self.assertFalse(result['bypass_executed'])
            for field, value in [('mode', 'official'), ('bypass_executed', True), ('virtual_only', False)]:
                with self.assertRaises(ValueError): d.verify_derived_receiver(target, dict(receipt, **{field:value}))
            for field in ('length', 'file_offset', 'original_hex', 'following_original_hex', 'executable_load'):
                bad = copy.deepcopy(receipt); bad['patch'][field] = None
                with self.assertRaises(ValueError): d.verify_derived_receiver(target, bad)
            expected = target.read_bytes()
            for offset in (0x300, 0xae08, 0xae0c):
                bad = bytearray(expected); bad[offset] ^= 1; target.write_bytes(bad)
                with self.assertRaises(ValueError): d.verify_derived_receiver(target, receipt)
            target.write_bytes(expected); target.unlink(); target.symlink_to(source)
            with self.assertRaises(OSError): d.verify_derived_receiver(target, receipt)

    def package_fixture(self, root):
        old, new = root / 'stock', root / 'dev'; old.write_bytes(b'official bytes'); new.write_bytes(b'approved 2.02 bytes')
        value = dict(schema=M['PACKAGE_SCHEMA'], profile=M['PROFILE'], mode=M['MODE'], virtual_only=True,
            delta='version-only-2.02', supported_payload_changes=False, original=U['record'](old), derived=U['record'](new),
            signature={'status': 'invalid'}, original_signature={'status': 'valid'}, original_version='2.01',
            new_version='2.02', current_version='2.01', model=M['MODEL'], region=M['REGION'], physical_devices_used=False, installation_verified=False,
            guest_signature_verified=False, bypass_executed=False, outer_crc_valid=True,
            all_decrypted_block_checks_valid=True, header_crc_valid=True, original_core_elfs_unchanged=True,
            plain=dict(original_sha256=M['PLAIN_SHA'], all_payload_bytes_identical=True, only_header_version_and_crc_changed=True),
            encoded=dict(only_first_encrypted_header_and_dend_crc_changed=True, ufuprefix_chunks_iv_footer_preserved=True))
        # Same-sized fixture records, private test-only pinned identities.
        new.write_bytes(b'derived2.02!!!'); value['derived'] = U['record'](new)
        self.assertEqual(old.stat().st_size, new.stat().st_size)
        path = root / 'package.json'; path.write_text(json.dumps(value))
        return path, value, {'STOCK_SHA': value['original']['sha256'], 'DERIVED_SHA': value['derived']['sha256'], 'PACKAGE_BYTES': old.stat().st_size}

    def test_invalid_signature_admitted_only_for_exact_dev_package_and_diff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); path, value, facts = self.package_fixture(root)
            with patch.dict(M['package_contract'].__globals__, facts):
                expected = M['package_contract'](path, U['record'](path)['sha256'])
                for key, bad in [('profile', I['PROFILE']), ('signature', {'status':'valid'}), ('signature', {'status':'unknown'}),
                    ('original_signature', {'status':'invalid'}), ('supported_payload_changes', True), ('new_version', '2.03'),
                    ('current_version', '2.02'), ('model', M['MODEL'] + 1), ('region', 1),
                    ('outer_crc_valid', False), ('original_core_elfs_unchanged', False),
                    ('plain', dict(value['plain'], all_payload_bytes_identical=False))]:
                    path.write_text(json.dumps(dict(value, **{key: bad})))
                    with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                        M['package_contract'](path, U['record'](path)['sha256'])
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError): M['package_contract'](path, '0' * 64)
                Path(value['derived']['path']).write_bytes(b'arbitrary new')
                with self.assertRaises(ValueError): M['package_contract'](path, U['record'](path)['sha256'])
                self.assertEqual(expected['value']['signature']['status'], 'invalid')

    def clone_fixture(self, root):
        paths = [root / n for n in ('source', 'before', 'clone')]
        for p in paths: p.mkdir(); (p / 'camera.emmc').write_bytes(b'current validated features')
        (paths[2] / 'geometry.json').write_text('{}'); p2 = root / 'old-p2'; p2.write_bytes(b'old-p2')
        value = dict(schema=I['SCHEMA'], profile=I['PROFILE'], status='prepared', source_reseeded=False,
            physical_devices_used=False, readback_verified=True, source_instance=str(paths[0]), before_instance=str(paths[1]),
            instance=str(paths[2]), source=U['record'](paths[0] / 'camera.emmc'), before=U['record'](paths[1] / 'camera.emmc'),
            clone=U['record'](paths[2] / 'camera.emmc'), expected_source_sha256=U['record'](paths[0] / 'camera.emmc')['sha256'],
            geometry=U['record'](paths[2] / 'geometry.json'), p2_before=U['record'](p2))
        path = root / 'clone.json'; path.write_text(json.dumps(value))
        return paths, path

    def test_combined_receipt_retains_stock_clone_before_and_binds_dev_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); paths, clone = self.clone_fixture(root); pkg, value, facts = self.package_fixture(root)
            out = root / 'authorization.json'; original_api = M['api']
            def load(name='update-boot.py'):
                if name == 'p1-dev-install.py': return M
                return original_api(name)
            with patch.dict(M['package_contract'].__globals__, facts):
                kwargs = dict(profile=M['PROFILE'], mode=M['MODE'], allow_dev_signature_bypass=True)
                binding = M['authorize'](paths[2], clone, U['record'](clone)['sha256'], pkg, U['record'](pkg)['sha256'], out, **kwargs)
                self.assertEqual(binding['profile'], M['PROFILE'])
                self.assertEqual(binding['clone_contract']['profile'], I['PROFILE'])
                self.assertEqual(binding['value']['before_instance'], str(paths[1]))
                self.assertIn(binding['receipt']['sha256'], M['authorization'](binding))
                with self.assertRaises(FileExistsError):
                    M['authorize'](paths[2], clone, U['record'](clone)['sha256'], pkg, U['record'](pkg)['sha256'], out, **kwargs)
                Path(value['derived']['path']).write_bytes(b'changed image')
                with self.assertRaises(ValueError): M['clone_contract'](paths[2], out, U['record'](out)['sha256'])
                Path(value['derived']['path']).write_bytes(b'derived2.02!!!')
                (paths[1] / 'camera.emmc').write_bytes(b'changed before')
                with self.assertRaises(ValueError): M['clone_contract'](paths[2], out, U['record'](out)['sha256'])

    def test_virtual_restore_delegates_exact_original_before_contract_without_dev_package_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); called = []
            receipt = p / 'dev.json'; value = dict(schema=M['SCHEMA'], profile=M['PROFILE'], mode=M['MODE'],
                allow_dev_signature_bypass=True, clone_receipt={'path':'/before-receipt', 'sha256':'c' * 64})
            receipt.write_text(json.dumps(value)); original_api = M['api']
            def load(name='update-boot.py'):
                if name == 'newp1-virtual-install.py': return dict(restore=lambda *args: called.append(args) or p / 'restored')
                return original_api(name)
            with patch.dict(M['restore'].__globals__, api=load):
                self.assertEqual(M['restore'](receipt, U['record'](receipt)['sha256'], p / 'restored'), p / 'restored')
                self.assertEqual(called, [('/before-receipt', 'c' * 64, p / 'restored')])
                with self.assertRaises(ValueError): M['restore'](receipt, '0' * 64, p / 'bad')

    def test_dev_bootstrap_separate_exact_mode_env_backup_module_and_twenty_target_guards(self):
        original = (HERE / 'guest/update-storage-bootstrap').read_bytes()
        data = M['bootstrap_source']()
        self.assertIn('[ "$($bb cat /simulation/update-profile)" = ' + M['MODE'] + ' ]', data)
        self.assertIn('A7C2_P1_DEV_INSTALL=version-only-2.02', data)
        self.assertIn('[ "$A7C2_P1_DEV_INSTALL" = version-only-2.02 ] || return 125', data)
        self.assertIn('/simulation/install-target /dev/pnflasha /dev/cnflasha[0-9]* /dev/nflashaB0 /dev/nflashaB1 || return 125', data)
        self.assertIn('2390264:b863f8b61d1a979b964419a99c9a0f27169958f8f5cbb204b7a4eee3b127cdff', data)
        self.assertIn('for required in devno osal_utm osal_uipc utimer backup osal_ulogio dmm stream2 mcmn_drv mmc_drv nvme_core nvme', data)
        self.assertEqual(M['WRITE_GUARD'], I['WRITE_GUARD'])
        self.assertEqual(M['NODES'], I['NODES'])
        subprocess.run(['/bin/sh', '-n'], input=data.encode(), check=True, capture_output=True)
        self.assertEqual((HERE / 'guest/update-storage-bootstrap').read_bytes(), original)

    def test_cpio_api_is_reused_and_unselected_key_model_never_imports_provider(self):
        self.assertTrue(callable(M['cpio_readback']))
        self.assertIsNone(M['trusted_key_api'](None))
        self.assertIsNone(M['key_model_contract']('/unused', None, None))
        for value in ({}, {'profile': M['KEY_PROFILE']}, {'profile': 'official', 'receipt':'/missing', 'receipt_sha256':'0' * 64}):
            with self.assertRaises(ValueError): M['trusted_key_api'](value)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); receipt = p / 'trust.json'; receipt.write_text('{}')
            selection = dict(profile=M['KEY_PROFILE'], receipt=str(receipt), receipt_sha256='0' * 64)
            with self.assertRaisesRegex(ValueError, 'receipt hash'): M['trusted_key_api'](selection)
            with self.assertRaises(ValueError):
                U['build']('/not-instance', '/runtime', p / 'absent', mode='official', trusted_key_model=selection)
            self.assertFalse((p / 'absent').exists())
        with self.assertRaises(ValueError): M['key_model_contract']('/unused', None, {'signature_verified':True})

    def test_cpio_reader_rejects_env_drift_and_duplicate_model_assets(self):
        import gzip
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); root = p / 'root'; root.mkdir(); (root / 'env').write_text('A7C2_P1_DEV_INSTALL=version-only-2.02\n')
            item = root / 'env'; data = item.read_bytes()
            expected = {'env': dict(mode=item.stat().st_mode, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())}
            out = p / 'root.gz'; U['archive'](root, out)
            self.assertEqual(M['cpio_readback'](out, expected), expected)
            altered = copy.deepcopy(expected); altered['env']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'differs'): M['cpio_readback'](out, altered)
            with out.open('ab') as raw, gzip.GzipFile(fileobj=raw, mode='wb') as stream:
                U['cpio_entry'](stream, 'env', item.stat().st_mode, len(data), item)
            with self.assertRaisesRegex(ValueError, 'Duplicate'): M['cpio_readback'](out, expected)

    def test_versions_reject_missing_uud_or_same_and_lower_versions(self):
        for value in ('', None, '2.2', '2.01\n', 'NaN', 2.01):
            with self.assertRaises(ValueError): M['version'](value)
        for current in ('2.02', '2.03', '3.00'):
            with tempfile.TemporaryDirectory() as td, self.assertRaisesRegex(ValueError, 'strictly higher'):
                M['attest_package']('/stock', '/derived', Path(td) / 'absent', fwtool_dir='/fwtool',
                    current_version=current, profile=M['PROFILE'], mode=M['MODE'], allow_dev_signature_bypass=True)


if __name__ == '__main__': unittest.main(verbosity=2)
