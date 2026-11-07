#!/usr/bin/env python3
"""Host-only explicit trim admission, native provenance, shell argv and CPIO."""
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
U = runpy.run_path(str(HERE / 'update-boot.py'))
I = runpy.run_path(str(HERE / 'newp1-virtual-install.py'))
D = runpy.run_path(str(HERE / 'p1-dev-install.py'))
E = runpy.run_path(str(HERE / 'p1-update-execution.py'))
RECEIPT = HERE.parents[1] / 'analysis/scratch/p1-alfred-trim-batch-20261106/build-v2/alfred-trim-module.json'


class Selection(unittest.TestCase):
    def test_opt_in_requires_exact_install_write_contract_for_both_modes(self):
        for install in (I['PROFILE'], D['PROFILE']):
            options = dict(install_profile=install, read_only=False, allow_updater_writes=True)
            U['storage_selection'](U['TRIM_STORAGE_PROFILE'], **options)
            for name, value in (('install_profile', None), ('install_profile', 'original-p1-sd-readonly-v1'),
                                ('read_only', True), ('read_only', 0), ('allow_updater_writes', False),
                                ('allow_updater_writes', 1)):
                with self.subTest(install=install, name=name, value=value), self.assertRaises(ValueError):
                    U['storage_selection'](U['TRIM_STORAGE_PROFILE'], **dict(options, **{name: value}))
            for selected in (None, 'unknown'):
                with self.assertRaises(ValueError):
                    U['storage_selection'](selected, module={'storage_profile': U['TRIM_STORAGE_PROFILE']}, **options)
            with self.assertRaises(ValueError):
                U['storage_selection'](U['TRIM_STORAGE_PROFILE'], module={}, **options)
        U['storage_selection'](None, install_profile=None, read_only=True, allow_updater_writes=False, module={})

    def test_invalid_selection_rejected_before_builder_or_executor_creates_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'unused'
            for selected in ('unknown', U['TRIM_STORAGE_PROFILE']):
                with self.assertRaises(ValueError):
                    U['build']('/absent', '/runtime', output, mode='official', storage_profile=selected)
                with self.assertRaises(ValueError):
                    E['build']('/absent', output, storage_profile=selected)
                self.assertFalse(output.exists())

    def test_old_baseline_remains_admitted_for_stock_and_dev_with_exact_modes(self):
        module = dict(protocol=U['PROTOCOL'], build_bound=True, large_io_fix_bound=True,
                      updater_write_eligible=True, module_sha256=U['CURRENT_MODULE_SHA'],
                      kernel_sha256=U['KERNEL_SHA'], driver={'sha256': U['CURRENT_DRIVER_SHA']})
        options = dict(read_only=False, allow_updater_writes=True, media={'bound': True}, sd={'image': True}, module=module)
        I['admit'](I['PROFILE'], mode='official', **options)
        D['admit'](D['PROFILE'], mode=D['MODE'], allow_dev_signature_bypass=True, **options)
        with self.assertRaises(ValueError):
            I['admit'](I['PROFILE'], mode=D['MODE'], **options)
        with self.assertRaises(ValueError):
            D['admit'](D['PROFILE'], mode='official', allow_dev_signature_bypass=True, **options)
        for bad in (dict(module, module_sha256=U['TRIM_MODULE_SHA']),
                    dict(module, driver={'sha256': U['TRIM_DRIVER_SHA']}),
                    dict(module, storage_profile=U['TRIM_STORAGE_PROFILE'])):
            with self.assertRaises(ValueError):
                I['module_admission'](bad)

    def test_trim_collector_requires_unique_native_parameter_and_real_alias_evidence(self):
        fixtures = runpy.run_path(str(HERE / 'test-p1-update-execution.py'))
        manifest = dict(fixtures['manifest'](), storage_profile=U['TRIM_STORAGE_PROFILE'])
        markers = ('UPDATE_STORAGE_PARAMETER profile=' + U['TRIM_STORAGE_PROFILE'] +
                   ' name=functional_alfred_trim_zero value=Y\nUPDATE_STORAGE_ALIAS nflasha4=cnflasha4 verified=1\n').encode()
        raw = fixtures['serial']()
        self.assertTrue(E['collect'](raw + markers, manifest)['storage_profile_verified'])
        for suffix in (b'', markers.replace(b'value=Y', b'value=N'), markers + markers,
                       markers.replace(b'nflasha4=cnflasha4', b'nflasha4=pnflasha4')):
            self.assertFalse(E['collect'](raw + suffix, manifest)['storage_profile_verified'])

    def test_dev_file_and_version_bootstrap_derive_from_current_shim(self):
        base = (HERE / 'guest/update-storage-bootstrap').read_text(encoding='ascii')
        for kind in ('fixed-system-file-v1', 'version-only-2.02'):
            text = D['bootstrap_source'](install_kind=kind)
            self.assertIn('export A7C2_P1_DEV_INSTALL=' + kind, text)
            self.assertIn('persistent_load\nrc=$?', text)
            self.assertIn(U['storage_parameter_text']().strip(), text)
            self.assertIn('    if [ -e /simulation/pmbp-runtime/profile ]; then\n'
                          '        /simulation/pmbp-runtime/bootstrap /simulation/pmbp-runtime manifest.bin module-load\n'
                          '    else\n'
                          '        $bb insmod /simulation/sony_persistent_flash.ko functional_alfred_trim_zero=1\n'
                          '    fi\n'
                          '    rc=$?\n'
                          '    [ "$rc" -eq 0 ] || return "$rc"\n', text)
            subprocess.run(['/bin/sh', '-n'], input=text.encode('ascii'), check=True)
        self.assertIn('original-p1-virtual-install-v1', base)
        source = inspect.getsource(E['build'])
        self.assertIn("install_api['install_environment'](update['virtual_install'])", source)
        self.assertIn("install_kind=environment['A7C2_P1_DEV_INSTALL']", source)
        builder = (HERE / 'update-boot.py').read_text()
        self.assertIn("'p1-dev-file-package.py'", builder)
        self.assertIn("'analysis/build_sony_info.py'", builder)


@unittest.skipUnless(RECEIPT.is_file(), 'exact private trim build receipt required')
class NativeEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(RECEIPT.read_text())
        base = json.loads(Path(cls.receipt['base_build_receipt']['path']).read_text())
        cls.module = U['record'](cls.receipt['module']['file']['path'])
        cls.kernel = U['record'](base['original_kernel']['path'])
        cls.contract = U['module_contract'](cls.module, cls.kernel, RECEIPT)

    def test_exact_native_contract_replayed_by_stock_and_dev(self):
        self.assertEqual(U['record'](RECEIPT)['sha256'], U['TRIM_RECEIPT_SHA'])
        self.assertEqual(self.contract['exports']['required_count'], 38)
        self.assertEqual(self.contract['abi']['struct_module_bytes'], 768)
        self.assertEqual(self.contract['abi']['vermagic'], ['4.9.186-scel SMP preempt mod_unload aarch64'])
        self.assertFalse(self.contract['physical_compatibility'])
        self.assertFalse(self.contract['guest_verified'])
        options = dict(read_only=False, allow_updater_writes=True, media={'bound': True}, sd={'image': True}, module=self.contract)
        I['admit'](I['PROFILE'], mode='official', **options)
        D['admit'](D['PROFILE'], mode=D['MODE'], allow_dev_signature_bypass=True, **options)

    def test_wrong_module_receipt_feature_and_actual_source_readback_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'receipt.json'
            changed = dict(self.receipt, guest_verified=True)
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'exact trim receipt'):
                U['module_contract'](self.module, self.kernel, path)
            with self.assertRaisesRegex(ValueError, 'actual module'):
                U['module_contract'](dict(self.module, sha256=U['CURRENT_MODULE_SHA']), self.kernel, RECEIPT)
            with self.assertRaises(ValueError):
                U['module_contract'](self.module, self.kernel, RECEIPT, path)
        for field, value in (('source_set_sha256', '0' * 64), ('required_module_parameters', {}),
                             ('abi', {}), ('storage_profile', None), ('module_sha256', U['CURRENT_MODULE_SHA'])):
            changed = copy.deepcopy(self.contract); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                I['module_admission'](changed)
        original_record = U['record']
        source = self.receipt['variant_source']['trim-zero.h']['path']
        def drift(path):
            value = original_record(path)
            return dict(value, sha256='0' * 64) if str(path) == source else value
        with patch.dict(U['alfred_trim_contract'].__globals__, record=drift):
            with self.assertRaisesRegex(ValueError, 'source/module input differs'):
                U['module_contract'](self.module, self.kernel, RECEIPT)

    def root(self, root, *, dev=False):
        simulation = root / 'simulation'; simulation.mkdir()
        (simulation / 'sony_persistent_flash.ko').write_bytes(Path(self.module['path']).read_bytes())
        (simulation / 'create-aliases').write_bytes((HERE / 'persistent-flash/create-aliases.sh').read_bytes())
        (simulation / 'storage-profile').write_text(U['storage_parameter_text']()); (simulation / 'storage-profile').chmod(0o600)
        (simulation / 'install-authorization').touch(); (simulation / 'backup-trusted-file-load').touch()
        (root / 'init').write_text(D['bootstrap_source'](install_kind='fixed-system-file-v1') if dev else
                                  (HERE / 'guest/update-storage-bootstrap').read_text())
        (root / 'init').chmod(0o755)
        return dict(install_profile=D['PROFILE'] if dev else I['PROFILE'], storage_profile=U['TRIM_STORAGE_PROFILE'],
                    module_contract=self.contract)

    def test_parameter_module_alias_and_cpio_readback_in_both_modes(self):
        sd = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
        for dev in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / 'root'; root.mkdir(); update = self.root(root, dev=dev)
                expected = U['storage_preflight'](update, root, U['TRIM_STORAGE_PROFILE'], read_only=False, allow_updater_writes=True)
                cpio = Path(temporary) / 'boot.cpio.gz'; U['archive'](root, cpio)
                self.assertEqual(sd['cpio_readback'](cpio, expected), expected)
                for marker in ('read-only-probe', 'sd-no-install', 'block-readonly-verified'):
                    p = root / 'simulation' / marker; p.touch()
                    with self.assertRaisesRegex(ValueError, 'read-only'):
                        U['storage_preflight'](update, root, U['TRIM_STORAGE_PROFILE'], read_only=False, allow_updater_writes=True)
                    p.unlink()
                parameter = root / 'simulation/storage-profile'; parameter.unlink()
                with self.assertRaises(ValueError):
                    U['storage_preflight'](update, root, U['TRIM_STORAGE_PROFILE'], read_only=False, allow_updater_writes=True)
                parameter.write_text('unknown\n'); parameter.chmod(0o600)
                with self.assertRaises(ValueError):
                    U['storage_preflight'](update, root, U['TRIM_STORAGE_PROFILE'], read_only=False, allow_updater_writes=True)
                parameter.write_text(U['storage_parameter_text']()); parameter.chmod(0o644)
                with self.assertRaises(ValueError):
                    U['storage_preflight'](update, root, U['TRIM_STORAGE_PROFILE'], read_only=False, allow_updater_writes=True)
                parameter.chmod(0o600)
                aliases = root / 'simulation/create-aliases'; aliases.write_bytes(aliases.read_bytes().replace(b'cnflasha$part', b'pnflasha$part'))
                with self.assertRaisesRegex(ValueError, 'alias mapping'):
                    U['storage_preflight'](update, root, U['TRIM_STORAGE_PROFILE'], read_only=False, allow_updater_writes=True)
                with self.assertRaisesRegex(ValueError, 'CPIO binding differs'):
                    sd['cpio_readback'](cpio, dict(expected, **{'simulation/storage-profile': dict(expected['simulation/storage-profile'], sha256='0'*64)}))

    def test_real_shell_load_argv_default_opt_in_ro_unknown_digest_and_returncode(self):
        for dev in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); self.root(root, dev=dev); simulation = root / 'simulation'
                audit = simulation / 'audit'
                audit.write_text('#!/usr/bin/python3\nimport hashlib,sys\n'
                    'p,_,size,digest,_=sys.argv[2:]\n'
                    'b=open(p,"rb").read()\n'
                    'sys.exit(0 if len(b)==int(size) and hashlib.sha256(b).hexdigest()==digest else 7)\n')
                audit.chmod(0o755)
                bb = root / 'busybox'
                bb.write_text('#!/usr/bin/python3\nimport json,os,sys\n'
                    'if sys.argv[1]=="cat": sys.stdout.buffer.write(open(sys.argv[2],"rb").read())\n'
                    'elif sys.argv[1]=="rm":\n'
                    ' for p in sys.argv[3:]:\n'
                    '  if os.path.exists(p): os.unlink(p)\n'
                    'elif sys.argv[1]=="insmod":\n'
                    ' open(os.environ["ARGV_LOG"],"w").write(json.dumps(sys.argv[2:]));sys.exit(int(os.environ.get("TEST_RC","17")))\n'
                    'else: sys.exit(99)\n'); bb.chmod(0o755)
                text = (root / 'init').read_text().split('install_guard()')[0]
                text = text.replace('/simulation/', str(simulation) + '/').replace('bb=/bin/busybox', 'bb=' + str(bb))
                parameter_state = root / 'native-parameter'
                text = text.replace('/sys/module/sony_persistent_flash/parameters/functional_alfred_trim_zero', str(parameter_state))
                script = root / 'load'; script.write_text(text + '\npersistent_load\n')
                log = root / 'argv.json'; env = dict(os.environ, ARGV_LOG=str(log))
                def run(expected_rc, expected_args=None):
                    log.unlink(missing_ok=True)
                    result = subprocess.run(['/bin/sh', str(script)], env=env, capture_output=True)
                    self.assertEqual(result.returncode, expected_rc, result.stderr)
                    if expected_args is None: self.assertFalse(log.exists())
                    else: self.assertEqual(json.loads(log.read_text()), expected_args)
                module_path = str(simulation / 'sony_persistent_flash.ko')
                run(17, [module_path, 'functional_alfred_trim_zero=1'])
                env['TEST_RC'] = '0'; parameter_state.write_text('Y\n')
                run(0, [module_path, 'functional_alfred_trim_zero=1'])
                parameter_state.write_text('N\n')
                run(125, [module_path, 'functional_alfred_trim_zero=1'])
                del env['TEST_RC']
                for marker in ('read-only-probe', 'sd-no-install', 'block-readonly-verified'):
                    p = simulation / marker; p.touch(); run(125); p.unlink()
                parameter = simulation / 'storage-profile'
                parameter.write_text('unknown\n'); run(125)
                parameter.write_text(U['storage_parameter_text']().replace(U['TRIM_MODULE_SHA'], U['CURRENT_MODULE_SHA'])); run(125)
                parameter.unlink(); run(17, [module_path])
                parameter.symlink_to(root / 'absent'); run(125); parameter.unlink()
                parameter.write_text(U['storage_parameter_text']())
                (simulation / 'sony_persistent_flash.ko').write_bytes(b'wrong module')
                run(125)


if __name__ == '__main__':
    unittest.main()
