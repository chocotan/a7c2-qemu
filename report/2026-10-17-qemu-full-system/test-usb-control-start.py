#!/usr/bin/env python3
"""Exercise the real shell policy and current profile guards without a VM."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'usb-control-start.py'))
FIXTURES = runpy.run_path(str(HERE / 'test-persistent-camera-profile.py'))


class HelperOverlay(unittest.TestCase):
    def test_fresh_topology_copy_and_manifest_are_bound_without_changing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = root / 'runtime'; analysis = runtime / 'analysis'
            analysis.mkdir(parents=True)
            (runtime / 'sources').mkdir()
            paths = ('qemu-kernel-probe.sh', 'boot-handoff.bin', 'boards/virt-four.dtb',
                     'qemu-virt-board/virt-packed.dtb', API['AP']['PERSISTENT']['KERNEL_ASSET'],
                     'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt')
            for name in paths:
                path = analysis / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'bound helper fixture')
            for name in ('root/simulation', 'root/lib'):
                (analysis / name).mkdir(parents=True)
            original = b'{"schema": 1, "adapter_sources": {"unchanged": "value"}}\n'
            (analysis / 'full-system.json').write_bytes(original)
            with patch.dict(API['CAMERA'], expand=lambda profile, path: {'profile': profile}):
                output = API['prepare_helpers'](runtime, root / 'fresh')
            self.assertEqual((analysis / 'full-system.json').read_bytes(), original)
            self.assertFalse((analysis / 'usb-device-profile.py').exists())
            copied = output / 'analysis/usb-device-profile.py'
            self.assertEqual(copied.read_bytes(), (HERE / 'usb-device-profile.py').read_bytes())
            manifest = json.loads((output / 'analysis/full-system.json').read_text())
            receipt = json.loads((output / 'helper-receipt.json').read_text())
            self.assertEqual(manifest['adapter_sources']['unchanged'], 'value')
            self.assertEqual(manifest['adapter_sources']['usb-device-profile.py'], API['digest'](copied))
            self.assertEqual(receipt['topology_source_sha256'], API['digest'](copied))
            self.assertTrue(receipt['source_manifest_unchanged'])
            self.assertFalse(receipt['observer_rebuilt'])


class FunctionalEntry(unittest.TestCase):
    def test_complete_functional_launch_reaches_lower_guard_and_preserves_prepare_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            argv = [value for name in ('instance', 'runtime', 'module', 'qemu-build', 'output') for value in ('--' + name, str(root / name))]
            flags = [value for name in ('ee-normal-cold-model', 'ee-backup', 'ee-vendor', 'ee-cp') for value in ('--' + name, str(root / name))]
            prepare = Mock(return_value=root / 'helpers')
            lower = Mock(return_value=0)
            ap = dict(API['AP'], PERSISTENT={'fresh_output': lambda *a: root}, save=lambda *a: None, main=lower)
            with patch.dict(API['main'].__globals__, AP=ap, prepare_helpers=prepare):
                self.assertEqual(API['main']([*argv, *flags, '--seconds', '120', '--observe-start']), 0)
                expected = dict(model=root / 'ee-normal-cold-model', backup=root / 'ee-backup', vendor=root / 'ee-vendor', cp=root / 'ee-cp')
                self.assertEqual(prepare.call_args.kwargs, dict(observe_start=True, observe_ee=False, ee_normal_cold=expected))
                self.assertEqual(lower.call_args.kwargs, dict(camera_profile=API['START']['PROFILE'], select_msc=False, observe_start=True))
                self.assertIn(str(root / 'helpers'), lower.call_args.args[0])
                lower.side_effect = ValueError('full lower guard rejected private input drift')
                with self.assertRaisesRegex(ValueError, 'private input drift'):
                    API['main']([*argv, *flags, '--seconds', '120', '--observe-start'])
                lower.reset_mock()
                self.assertEqual(API['main']([*argv, *flags, '--seconds', '120', '--observe-start', '--prepare-only']), 0)
                lower.assert_not_called()
                prepare.reset_mock()
                for suffix, private in (([], flags), (['--observe-start', '--observe-ee'], flags),
                                        (['--observe-start', '--seconds', '121'], flags),
                                        (['--observe-start'], flags[:-2])):
                    with self.subTest(suffix=suffix), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                        API['main']([*argv, *private, '--seconds', '120', *suffix])
                prepare.assert_not_called()

    def test_lower_entry_passes_explicit_contract_and_all_bindings_inside_same_lease(self):
        ap = API['AP']
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            contract = {'ee_normal_cold': {'generation': 7}, 'ee_observer': {'profile': ap['FUNCTIONAL_MODE']}}
            # These are wiring fixtures; the verifier's real identity checks have separate negative cases.
            bindings = [dict(role=f'ee-binding-{n}', path=str(root / str(n)), bytes=1, sha256='a' * 64) for n in range(24)]
            cold = dict(partition_bindings=[dict(id='nflasha15', offset=0, bytes=1, sha256='b' * 64)])
            disk = root / 'disk'; disk.write_bytes(b'x')
            with disk.open('rb') as fd:
                active = [False]
                @contextlib.contextmanager
                def lease(launch):
                    active[0] = True
                    self.assertEqual(launch['template_inputs'], bindings)
                    try:
                        yield dict(launch, fd=fd.fileno(), children=[])
                    finally:
                        active[0] = False
                def execute(bound, supplied_cold, output, **options):
                    self.assertTrue(active[0]); self.assertEqual(bound['fd'], fd.fileno())
                    self.assertIs(supplied_cold, cold)
                    self.assertIs(options['observer_contract'], contract)
                    self.assertEqual(options['observer_mode_verified'], ap['FUNCTIONAL_MODE'])
                    self.assertTrue(options['observe_start']); self.assertEqual(options['seconds'], 120)
                    output.mkdir()
                    return dict(complete_readbacks=True, owner={'returncode': 0})
                original_run = runpy.run_path
                def run(path):
                    if Path(path).name == 'usb-start-observe.py':
                        return dict(API['START'], build_cold=lambda *a, **k: cold)
                    return original_run(path)
                launch = dict(env={}, template_inputs=[])
                persistent = dict(ap['PERSISTENT'], prepare_launch=lambda *a, **k: launch,
                    leased_launch=lease, DISK={'hashed': lambda descriptor, *a: self.assertEqual(descriptor, fd.fileno()) or 'b' * 64})
                with patch.dict(ap['main'].__globals__, PERSISTENT=persistent,
                        USB=dict(ap['USB'], prepare_launch=lambda value, **k: value), execute=execute,
                        verified_observer=lambda *a, **k: (ap['FUNCTIONAL_MODE'], contract, bindings)), patch.object(runpy, 'run_path', side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                    argv = [value for name in ('instance', 'runtime', 'module', 'qemu-build') for value in ('--' + name, str(root / name))]
                    result = ap['main']([*argv, '--output', str(root / 'probe'), '--seconds', '120'], camera_profile=API['START']['PROFILE'], observe_start=True)
                self.assertEqual(result, 0); self.assertFalse(active[0])
                self.assertTrue(json.loads((root / 'probe/evidence/result.json').read_text())['p15_readback']['unchanged'])


class MonitorPolicy(unittest.TestCase):
    def policy(self, *, gate='', policy='media-rm', name='usb_portMonitor', bad_sha=False, arguments=()):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cmdline = root / 'cmdline'; cmdline.write_text(gate + '\n')
            module = root / (name + '.ko'); module.write_bytes(b'original-module-fixture')
            sha = hashlib.sha256(module.read_bytes()).hexdigest()
            called = root / 'called'
            busybox = root / 'busybox'
            busybox.write_text('#!/bin/sh\n[ "$1" = insmod ] || exit 91\nshift\nfor arg in "$@"; do echo "$arg"; done > "' + str(called) + '"\nexit 23\n')
            busybox.chmod(0o700)
            text = (HERE / 'guest/insmod').read_text().replace('/proc/cmdline', str(cmdline))
            text = text.replace('/tmp/fullsystem-insmod-policy', str(root / 'no-marker'))
            text = text.replace('/bin/busybox', str(busybox))
            text = text.replace('/usr/kmod/usb_portMonitor.ko', str(root / 'usb_portMonitor.ko'))
            text = text.replace('/usr/kmod/usbg_sen.ko', str(root / 'usbg_sen.ko'))
            if not bad_sha:
                text = text.replace(API['SOURCE_CONTRACT']['module']['sha256'], sha)
                text = text.replace(API['START']['SEN']['sha256'], sha)
            script = root / 'insmod'; script.write_text(text)
            checked = subprocess.run(['/bin/sh', str(script), str(module), *arguments],
                env={**os.environ, 'FULLSYSTEM_INSMOD_POLICY': policy}, capture_output=True, text=True, timeout=5)
            return checked, called.read_text().splitlines() if called.exists() else None

    def test_default_and_near_match_gate_refuse_monitor(self):
        for gate in ('', 'fullsystem.usb-monitor=original-extra', 'fullsystem.usb-monitor=off'):
            result, called = self.policy(gate=gate)
            self.assertEqual(result.returncode, 78)
            self.assertIsNone(called)
        result, called = self.policy(gate='fullsystem.usb-monitor=original', policy='')
        self.assertEqual(result.returncode, 78); self.assertIsNone(called)

    def test_exact_gate_preserves_real_rc_and_all_arguments(self):
        result, called = self.policy(gate='fullsystem.usb-monitor=original', arguments=('circuit_type=0', 'literal=a b'))
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(called[1:], ['circuit_type=0', 'literal=a b'])
        self.assertIn('FULLSYSTEM_MODULE_RESULT usb_portMonitor result=23', result.stdout)
        self.assertIn('argc=2', result.stdout)

    def test_mismatched_module_refuses_before_insmod(self):
        result, called = self.policy(gate='fullsystem.usb-monitor=original', bad_sha=True)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(called)
        self.assertIn('FULLSYSTEM_USB_MONITOR_IDENTITY_FAILED', result.stdout)

    def test_gate_does_not_allow_other_unsupported_modules(self):
        for name in ('emmc', 'crypt-emmc', 'mmc_drv', 'usbg_sen', 'usb_extcmd'):
            result, called = self.policy(gate='fullsystem.usb-monitor=original', name=name)
            self.assertEqual(result.returncode, 78)
            self.assertIsNone(called)

    def test_sen_exact_gate_preserves_parameters_and_real_failure(self):
        gate = 'fullsystem.usb-service=original-sen-observe-v1'
        result, called = self.policy(gate=gate, name='usbg_sen', arguments=('literal=a b', 'value=9'))
        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        self.assertEqual(called[1:], ['literal=a b', 'value=9'])
        self.assertIn('FULLSYSTEM_MODULE_RESULT usbg_sen result=23', result.stdout)
        for near in ('', gate+'-extra', 'fullsystem.usb-service=off'):
            result, called = self.policy(gate=near, name='usbg_sen')
            self.assertEqual(result.returncode, 78)
            self.assertIsNone(called)
        result, called = self.policy(gate=gate, name='usbg_sen', bad_sha=True)
        self.assertEqual(result.returncode, 1)
        self.assertIsNone(called)
        self.assertIn('FULLSYSTEM_USB_SEN_IDENTITY_FAILED', result.stdout)
        for name in ('usb_extcmd', 'usb_gadgetcore', 'mmc_drv'):
            result, called = self.policy(gate=gate, name=name)
            self.assertEqual(result.returncode, 78)
            self.assertIsNone(called)

    def test_existing_media_rm_module_still_passes_unchanged(self):
        result, called = self.policy(name='mmc_core', arguments=('value=7',))
        self.assertEqual(result.returncode, 23)
        self.assertEqual(called[1:], ['value=7'])


class MonitorProfile(FIXTURES['PersistentCameraProfile']):
    def test_explicit_profile_requires_current_source_and_manifest(self):
        guest = self.source / 'guest'; guest.mkdir()
        text = (HERE / 'guest/insmod').read_bytes()
        (guest / 'insmod').write_bytes(text)
        house = self.analysis / 'root/sbin/insmod'; house.parent.mkdir()
        house.write_bytes(text)
        self.manifest['derived_files'] = {'sbin/insmod': hashlib.sha256(text).hexdigest()}; self.store()
        api = FIXTURES['API']
        result = api['expand'](api['USB_MONITOR_PROFILE'], self.analysis)
        self.assertIn('fullsystem.usb-monitor=original', result['cmdline'])
        self.assertEqual(result['insmod_policy'], 'media-rm')
        self.assertEqual(result['usb_monitor'], 'original')
        self.assertIn('fullsystem.gpio-c1=virtual', result['cmdline'])
        self.assertFalse(result['actual_persistent_ap_consumed'])
        default = api['expand'](api['PROFILE'], self.analysis)
        self.assertNotIn('fullsystem.usb-monitor=original', default['cmdline'])
        house.write_bytes(b'stale')
        with self.assertRaisesRegex(ValueError, 'fresh source-bound'):
            api['expand'](api['USB_MONITOR_PROFILE'], self.analysis)

    def test_control_contract_never_claims_original_consumption(self):
        self.assertFalse(API['SOURCE_CONTRACT']['direct_ioctl_requested'])
        self.assertFalse(API['SOURCE_CONTRACT']['original_ap_control_start_verified'])
        self.assertFalse(API['SOURCE_CONTRACT']['host_enumerated'])
        self.assertEqual(API['SOURCE_CONTRACT']['module']['bytes'], 44872)


if __name__ == '__main__':
    unittest.main()
