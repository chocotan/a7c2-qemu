#!/usr/bin/env python3
"""P1 trust adapter, explicit executor selection and real derived ABI; no VM."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-trusted-key-model.py'))
E = runpy.run_path(str(HERE / 'p1-update-execution.py'))
U = E['UPDATE']
SD = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
DEV = 'original-p1-virtual-dev-install-v1'
STOCK = 'original-p1-virtual-install-v1'
REAL_UPDATE = Path(os.environ.get('P1_EXECUTOR_TEST_UPDATE', str(HERE.parents[1] /
    'analysis/scratch/p1-dev-install-batch-20261106/update-v2/update-boot.json')))


class Selection(unittest.TestCase):
    def test_exact_install_api_and_explicit_bool(self):
        self.assertEqual(E['install_api_for'](DEV)['PROFILE'], DEV)
        self.assertEqual(E['install_api_for'](STOCK)['PROFILE'], STOCK)
        for profile in ('dev', 'original-p1-virtual-install-v2', False):
            with self.assertRaises(ValueError): E['install_api_for'](profile)
        self.assertEqual(E['install_options'](STOCK, True, False), {'allow_updater_writes': True})
        self.assertEqual(E['install_options'](DEV, True, True),
                         {'allow_updater_writes': True, 'allow_dev_signature_bypass': True})
        for value in (1, 'true', None):
            with self.assertRaises(ValueError): E['install_options'](DEV, True, value)
        for profile in (None, STOCK):
            with self.assertRaises(ValueError): E['install_options'](profile, True, True)

    def test_explicit_trust_roundtrip_and_omitted_or_mixed_selection_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            pem = Path(folder) / 'pinned.pem'; pem.write_bytes(b'contract identity only')
            selection = dict(profile=SD['TRUST_PROFILE'], pinned_key=U['record'](pem))
            update = dict(trust_selection=selection, sd_read_observation=dict(trust_key=dict(profile=SD['TRUST_PROFILE'])))
            self.assertEqual(E['trust_selection'](update, install_profile=STOCK,
                trust_profile=SD['TRUST_PROFILE'], pinned_key=pem), selection)
            with self.assertRaisesRegex(ValueError, 'differs'):
                E['trust_selection'](update, install_profile=STOCK)
            with self.assertRaisesRegex(ValueError, 'exact official'):
                E['trust_selection'](update, install_profile=DEV, trust_profile=SD['TRUST_PROFILE'], pinned_key=pem)
            with self.assertRaisesRegex(ValueError, 'lacks built'):
                E['trust_selection'](dict(trust_selection=selection), install_profile=STOCK,
                    trust_profile=SD['TRUST_PROFILE'], pinned_key=pem)
            pem.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'differs'):
                E['trust_selection'](update, install_profile=STOCK, trust_profile=SD['TRUST_PROFILE'], pinned_key=pem)
        self.assertIsNone(E['trust_selection']({}, install_profile=None))
        dev = dict(profile=M['PROFILE'], receipt='/not-read', receipt_sha256='a' * 64)
        for update in ({'trusted_key_model_selection': dev}, {'trusted_key_model': {'profile': M['PROFILE']}}):
            with self.assertRaises(ValueError): E['trust_selection'](update, install_profile=DEV)

    def test_builder_refuses_unrequested_trust_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'absent'
            for options in (dict(trust_profile=SD['TRUST_PROFILE']), dict(pinned_key='/missing'),
                    dict(install_profile=DEV, trust_profile=SD['TRUST_PROFILE'], pinned_key='/missing'),
                    dict(trusted_key_model={'profile': M['PROFILE']})):
                with self.assertRaises(ValueError):
                    U['build'](folder, HERE / 'runtime/analysis', target, mode='official', **options)
            self.assertFalse(target.exists())

    def test_receipt_selection_rejects_missing_contract_and_untrusted_profile(self):
        for selected in (None, {}, {'profile': SD['TRUST_PROFILE'], 'receipt': '/missing', 'receipt_sha256': 'a' * 64},
                         {'profile': M['PROFILE'], 'receipt': '/missing', 'receipt_sha256': True}):
            with self.assertRaises(ValueError): M['selection_contract'](selected)


class Execution(unittest.TestCase):
    def test_actual_rechecks_same_profile_and_grants_under_the_lease(self):
        for profile, grant in ((STOCK, False), (DEV, True), (DEV, False)):
            with self.subTest(profile=profile, grant=grant), tempfile.TemporaryDirectory() as folder:
                folder = Path(folder); instance = folder / 'instance'; instance.mkdir()
                disk = instance / 'camera.emmc'; disk.write_bytes(b'isolated test disk')
                fd = os.open(disk, os.O_RDWR)
                try:
                    work = folder / 'build'; work.mkdir()
                    update = dict(mode='virtual-dev-sd-update-v1' if profile == DEV else 'official',
                                  allow_dev_signature_bypass=grant)
                    U['DISK']['save'](work / 'update.json', update)
                    row = U['record'](disk)
                    manifest = dict(schema=E['PROFILE'], status='built', output=str(work), instance=str(instance),
                        inputs=[], artifacts=[], state=row, geometry=row, disk_sha256=row['sha256'],
                        disk_device=row['device'], disk_inode=row['inode'], mode=update['mode'], read_only=False,
                        install_profile=profile, allow_updater_writes=True, allow_dev_signature_bypass=grant,
                        no_install=False, qemu=dict(sha256=SD['QEMU_SHA']), update_manifest=dict(path=str(work / 'update.json')),
                        media_resources='bound-media', sd_cpio_readback={},
                        p2=dict(flags=dict(mode=True, mode5=True, comp=False, uincomp=False), predicted_outer_mode=5),
                        original_files={}, original_audit=[])
                    E['save'](work / 'manifest.json', manifest)
                    import gzip
                    (work / 'probe.cpio.gz').write_bytes(gzip.compress(b''))
                    events = []
                    @contextmanager
                    def lease(path):
                        events.append('lease'); yield dict(fd=fd, geometry={}); events.append('release')
                    def preflight(update, root, read_only, media, selected, **kwargs):
                        events.append(('preflight', selected, kwargs))
                        self.assertEqual(selected, profile); self.assertFalse(read_only)
                        self.assertEqual(media, 'bound-media')
                        self.assertEqual(kwargs.get('allow_updater_writes'), True)
                        if profile == DEV:
                            if kwargs.get('allow_dev_signature_bypass') is not True: raise ValueError('dev grant missing')
                        else: self.assertNotIn('allow_dev_signature_bypass', kwargs)
                    def ranges(fd, geometry): events.append('ranges'); return {'test': 'bound'}
                    class Process:
                        pid = os.getpid(); returncode = None
                        def poll(self): return self.returncode
                        def wait(self, timeout=None): events.append('wait'); self.returncode = 0; return 0
                    def popen(argv, **kwargs):
                        events.append('launch'); kwargs['stdout'].write(b'UPDATE_SD_RECEIVER_EXIT pid=9 rc=1\n'); kwargs['stdout'].flush()
                        self.assertEqual(kwargs['pass_fds'], (fd,)); return Process()
                    class Stream:
                        def close(self): pass
                    def qmp(path):
                        def command(name, args=None):
                            events.append(name)
                            return {'return': {'name': 'p1-update-123'}} if name == 'query-name' else {'return': {}}
                        return Stream(), Stream(), command
                    def cpio(path, expected):
                        events.append('cpio'); return SD['cpio_readback'](path, expected)
                    implementation = dict(preflight=preflight, ranges=ranges, cpio_readback=cpio)
                    with patch.dict(E['DISK'], lease=lease), patch.dict(E['OWNER'], qmp_connect=qmp), \
                            patch.object(E['subprocess'], 'Popen', popen), \
                            patch.object(E['secrets'], 'token_hex', return_value='123'), \
                            patch.dict(E['actual'].__globals__, install_api_for=lambda selected: implementation,
                                       launch_command=lambda *args: ['bound-qemu']):
                        result = E['actual'](manifest, folder / 'guest', seconds=.01)
                    self.assertEqual(events[0], 'lease'); self.assertEqual(events[-1], 'release')
                    self.assertFalse(result['installation_verified'])
                    if profile == DEV and not grant:
                        self.assertNotIn('launch', events); self.assertIn('dev grant missing', result['first_host_error'])
                    else:
                        if profile == DEV: self.assertLess(events.index('cpio'), events.index('launch'))
                        self.assertLess(events.index('quit'), events.index('wait'))
                        self.assertLess(events.index('wait'), events.index('release'))
                        self.assertEqual(events.count('ranges'), 2)
                        self.assertTrue(result['normal_exit_verified']); self.assertEqual(result['vm_signals'], [])
                finally:
                    os.close(fd)


@unittest.skipUnless(REAL_UPDATE.is_file(), 'real derived P1 update fixture unavailable; set P1_EXECUTOR_TEST_UPDATE')
class RealAdapter(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='p1-trust-adapter-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.update = json.loads(REAL_UPDATE.read_text())
        self.original_root = Path(self.update['output']) / 'root'
        self.root = self.folder / 'root'
        shutil.copytree(self.original_root, self.root, symlinks=True)
        self.output = self.folder / 'output'; self.output.mkdir()
        self.update['output'] = str(self.output)
        self.update.pop('initrd', None)
        self.pinned = self.folder / 'independent.pem'
        self.pinned.write_bytes((self.root / SD['KEY'][0]).read_bytes()); self.pinned.chmod(0o444)
        self.selection = M['provision'](self.pinned, self.folder / 'trust-selection.json')
        self.update['trusted_key_model_selection'] = self.selection

    def test_provision_requires_independent_readonly_fixed_pem_and_binds_receipt(self):
        value, row, data = M['selection_contract'](self.selection)
        self.assertEqual(row['sha256'], self.selection['receipt_sha256'])
        self.assertEqual(len(data), 451); self.assertFalse(value['signature_verified'])
        self.pinned.chmod(0o644)
        with self.assertRaises(ValueError): M['selection_contract'](self.selection)
        self.pinned.chmod(0o444)
        alias = self.folder / 'alias.pem'; alias.symlink_to(self.pinned)
        with self.assertRaises((ValueError, OSError)): M['provision'](alias, self.folder / 'bad.json')
        with self.assertRaises(FileExistsError): M['provision'](self.pinned, self.folder / 'trust-selection.json')
        with self.assertRaises(ValueError): M['selection_contract'](dict(self.selection, receipt_sha256='0' * 64))

    def test_real_stock_activation_retains_strict_contract_and_preload(self):
        receiver = self.root / 'usr/lib/libsdfileinputupdaterapi.so'
        before = receiver.read_bytes()
        receiver.write_bytes(before[:0xae08] + bytes.fromhex('72f1ff97') + before[0xae0c:])
        signature = SD['trust_contract'](self.root)
        self.update.update(install_profile=STOCK, mode='official', allow_dev_signature_bypass=False,
            trust_selection=dict(profile=SD['TRUST_PROFILE'], pinned_key=U['record'](self.pinned)))
        trust = SD['install'](self.root, self.output, trust_profile=SD['TRUST_PROFILE'], pinned_key=self.pinned)
        (self.root / 'etc/ld.so.preload').write_text(SD['PRELOAD'])
        self.update['sd_read_observation'] = dict(trust_key=trust, initialize_contract=SD['initialize_contract'](self.root),
            observer=U['record'](self.root / 'simulation/p1-sd-observer.so'), bindings=[U['record'](self.root / 'simulation/p1-sd-observer.so')])
        result = M['configure_stock'](self.root, self.update, self.output)
        self.update['trust_execution'] = result
        self.assertEqual(M['preflight_stock'](self.update, self.root), result)
        self.assertEqual(SD['trust_contract'](self.root), signature)
        self.assertEqual((self.root / 'etc/ld.so.preload').read_text(), SD['PRELOAD'])
        self.assertEqual(result['environment'][SD['TRUST_ENV']], SD['TRUST_PROFILE'])
        (self.output / 'p1-sd-observer.c').write_text('wrong activation')
        with self.assertRaisesRegex(ValueError, 'activation source'):
            M['preflight_stock'](self.update, self.root)

    def test_real_service_build_native_pins_cpio_tamper_and_copied_execution_root(self):
        before = (self.root / 'usr/lib/libsdfileinputupdaterapi.so').read_bytes()
        with self.assertRaises(ValueError): SD['trust_contract'](self.root)
        model = M['configure'](self.root, self.update, self.output, selection=self.selection)
        self.update['trusted_key_model'] = model
        self.assertEqual(M['preflight'](self.update, self.root, selection=self.selection), model)
        pins = model['contract']['contract']['pins']
        self.assertEqual(pins[0]['size'], 584)
        self.assertEqual(pins[0]['text_sha256'], 'b1328d379f29881198d228c93d6bf5e472a206845275746b05cfda88de83e5ee')
        signature = bytes.fromhex(pins[1]['code'])
        self.assertEqual(signature[0xae08 - 0xace8:0xae0c - 0xace8], bytes.fromhex('20008052'))
        self.assertEqual((self.root / 'usr/lib/libsdfileinputupdaterapi.so').read_bytes(), before)
        self.assertTrue(model['preload'].startswith(SD['PRELOAD']))
        self.assertEqual(model['environment'][SD['TRUST_ENV']], SD['TRUST_PROFILE'])
        generated = (self.output / 'p1-trust-key-service.c').read_text()
        self.assertIn('init_identity && trust_identity && trust_marker()', generated)
        self.assertIn('setenv("A7C2_P1_TRUST_PROFILE",P1_TRUST_PROFILE,1)', generated)
        self.assertNotIn('int Fsys_Init(', generated)
        expected = {name: {k: row[k] for k in ('mode', 'bytes', 'sha256')} for name,row in model['assets'].items()}
        expected.update(model['original_bindings'])
        self.assertIn(SD['CRYPTO'][0], expected); self.assertIn(SD['SKD'][0], expected)
        archive = self.folder / 'trust.cpio.gz'; U['archive'](self.root, archive)
        self.update['initrd'] = U['record'](archive)
        self.assertEqual(SD['cpio_readback'](archive, expected), expected)
        copied = self.folder / 'execution-root'; shutil.copytree(self.root, copied, symlinks=True)
        self.assertEqual(M['preflight'](self.update, copied, selection=self.selection), model)
        for relative in ('etc/ld.so.preload', 'simulation/p1-trust-key/profile',
                         'simulation/p1-trust-key/dev-contract.json', M['SERVICE']):
            target = self.root / relative; old = target.read_bytes(); target.write_bytes(old + b'!')
            with self.assertRaises(ValueError): M['preflight'](self.update, self.root, selection=self.selection)
            target.write_bytes(old)
        receiver = self.root / 'usr/lib/libsdfileinputupdaterapi.so'
        receiver.write_bytes(bytes([before[0] ^ 1]) + before[1:])
        with self.assertRaises(ValueError): M['preflight'](self.update, self.root, selection=self.selection)
        receiver.write_bytes(before)
        with self.assertRaisesRegex(ValueError, 'allow_dev_signature_bypass=True'):
            M['preflight'](dict(self.update, allow_dev_signature_bypass=False), self.root, selection=self.selection)
        source = self.output / 'p1-trust-key-service.c'; source.write_text(generated + '\n/* drift */\n')
        with self.assertRaisesRegex(ValueError, 'emitted code'):
            M['preflight'](self.update, self.root, selection=self.selection)


if __name__ == '__main__':
    unittest.main(verbosity=2)
