#!/usr/bin/env python3
"""Synthetic enum/ownership and archived protocol tests; no libusb/device/VM access.

Real enumeration, Sony authentication and guest root remain unverified by these
fixtures. ReplayDriver is a fixed byte stream for the existing jiritsu exchange
parser, not an alternate USB backend or a production consumer provider.
"""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usb_jiritsu as jiritsu


def archive_module(name):
    spec = importlib.util.spec_from_file_location('test_archive_' + name, jiritsu.SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERSION = (archive_module('jiritsu_version_read')
           if (jiritsu.SCRIPTS / 'jiritsu_version_read.py').is_file() else None)


class OwnedFixture:
    """Explicit synthetic control snapshot; approves no real sysfs or USB."""
    def __init__(self, root):
        self.sysfs = root / 'synthetic-sys'
        self.controller = self.sysfs / 'devices/platform/vhci_hcd.0'
        self.path = self.controller / 'usb7/7-1'
        self.path.mkdir(parents=True)
        self.context = SimpleNamespace(run_id='synthetic-run', lease_id='synthetic-lease',
                                       run_dir=root, qmp_path=root / 'qmp.sock',
                                       backend_path=root / 'backend.sock', lease='z' * 48,
                                       vm_pid=os.getpid())
        self.target = {'sysfs_path': str(self.path), 'vhci_controller': str(self.controller),
                       'local_busid': '7-1', 'busnum': 7, 'devnum': 2, 'vendor_id': 0x054c,
                       'product_id': 0x0e8a, 'virtual_ancestor_verified': True,
                       'run_id': 'synthetic-run', 'lease_id': 'synthetic-lease'}
        self.record = {'run_id': 'synthetic-run', 'lease_id': 'synthetic-lease',
                       'owner_id': 'synthetic-owner', 'preload_recovery_required': False,
                       'owned_port': {'controller': str(self.controller), 'port': 0,
                                      'local_busid': '7-1'}}
        self.enumerated = True
        self.validations = []
        self.record_preload_recovery = Mock(side_effect=self.clear)
        self.disconnect = Mock(side_effect=AssertionError('consumer must never detach'))

    def _load(self):
        return copy.deepcopy(self.record)

    def status(self):
        return {'host_enumerated': self.enumerated, 'target': copy.deepcopy(self.target),
                'blocked_reason': None}

    def jiritsu_target(self, path, *, allow_recovery=False):
        self.validations.append((path, allow_recovery))
        if self.record['preload_recovery_required'] and not allow_recovery:
            raise jiritsu.blocked('preload_recovery_required', 'synthetic pending recovery')
        return copy.deepcopy(self.target)

    def mark_recovery_required(self, reason):
        self.record['preload_recovery_required'] = True

    def clear(self, raw):
        if raw != jiritsu.NEUTRAL:
            raise AssertionError('caller passed unverified content')
        self.record['preload_recovery_required'] = False

    def device(self, **changes):
        fields = dict(bus=self.target['busnum'], address=self.target['devnum'],
                      port_numbers=(1,), idVendor=self.target['vendor_id'], idProduct=self.target['product_id'])
        return SimpleNamespace(**{**fields, **changes})


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='jiritsu-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.control = OwnedFixture(self.root)

    def assert_blocked(self, code, call):
        with self.assertRaises(jiritsu.ControlBlocked) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_physical_sony_even_with_identical_vid_pid_refused(self):
        physical = self.control.sysfs / 'devices/pci0000:00/usb7/7-1'
        physical.mkdir(parents=True)
        self.control.target['sysfs_path'] = str(physical)
        self.assert_blocked('physical_usb_refused', lambda: jiritsu.TargetGuard(self.control))

    def test_physical_controller_refused_even_if_fixture_claims_ownership(self):
        physical = self.control.sysfs / 'devices/platform/xhci_hcd.0'
        path = physical / 'usb7/7-1'
        path.mkdir(parents=True)
        self.control.target.update(vhci_controller=str(physical), sysfs_path=str(path))
        self.control.record['owned_port']['controller'] = str(physical)
        self.assert_blocked('physical_usb_refused', lambda: jiritsu.TargetGuard(self.control))

    def test_other_run_vhci_and_wrong_lease_refused(self):
        for name in ('run_id', 'lease_id'):
            with self.subTest(name=name):
                old = self.control.target[name]
                self.control.target[name] = 'another-' + name
                self.assert_blocked('target_owner_mismatch', lambda: jiritsu.TargetGuard(self.control))
                self.control.target[name] = old

    def test_unenumerated_never_calls_real_find(self):
        guard = jiritsu.TargetGuard(self.control)
        self.control.enumerated = False
        real_find = Mock()
        self.assert_blocked('virtual_target_unverified', lambda: guard.find(real_find))
        real_find.assert_not_called()

    def test_filter_returns_original_objects_only_and_rechecks_on_find_and_open(self):
        guard = jiritsu.TargetGuard(self.control)
        owned = self.control.device()
        physical = self.control.device(bus=1, port_numbers=(4,))
        foreign_port = self.control.device(port_numbers=(2,))
        real_find = Mock(return_value=[physical, foreign_port, owned])
        before = len(self.control.validations)
        self.assertIs(guard.find(real_find), owned)
        self.assertGreaterEqual(len(self.control.validations), before + 2)
        real_find.assert_called_once_with(find_all=True, idVendor=0x054c)
        self.assert_blocked('foreign_usb_device', lambda: guard.check_device(physical))
        self.assert_blocked('foreign_usb_device', lambda: guard.check_device(foreign_port))

    def test_same_port_reenumeration_allows_new_pid_and_address(self):
        guard = jiritsu.TargetGuard(self.control)
        old = self.control.device()
        self.control.target.update(product_id=0x0336, devnum=9)
        service = self.control.device()
        self.assertIs(guard.find(Mock(return_value=[old, service]), 0x0336), service)
        self.assert_blocked('foreign_usb_device', lambda: guard.check_device(old))
        self.assertEqual(guard.current()['product_id'], 0x0336)

    def test_changed_owner_or_vhci_port_cannot_be_followed(self):
        for key, value in (('owner_id', 'other-owner'), ('port', 1)):
            with self.subTest(key=key):
                guard = jiritsu.TargetGuard(self.control)
                where = self.control.record if key == 'owner_id' else self.control.record['owned_port']
                old = where[key]
                where[key] = value
                self.assert_blocked('target_owner_changed', guard.current)
                where[key] = old

    def test_reenumeration_at_foreign_controller_rejected(self):
        guard = jiritsu.TargetGuard(self.control)
        other = self.control.sysfs / 'devices/platform/vhci_hcd.1'
        path = other / 'usb8/8-1'
        path.mkdir(parents=True)
        self.control.target.update(vhci_controller=str(other), sysfs_path=str(path), local_busid='8-1', busnum=8)
        self.control.record['owned_port'].update(controller=str(other), local_busid='8-1')
        self.assert_blocked('target_owner_changed', guard.current)

    def test_duplicates_rejected_and_no_pid_fallback(self):
        guard = jiritsu.TargetGuard(self.control)
        device = self.control.device()
        self.assert_blocked('ambiguous_virtual_device', lambda: guard.find(Mock(return_value=[device, device])))
        self.assertIsNone(guard.find(Mock(return_value=[device]), 0x0336))

    def test_legacy_recovery_api_blocks_root_before_subprocess(self):
        self.control.jiritsu_target = lambda path: copy.deepcopy(self.control.target)
        with patch.object(jiritsu.subprocess, 'run') as launch:
            result = jiritsu.JiritsuConsumer(self.control).run('root')
        launch.assert_not_called()
        self.assertEqual(result['blocked_reason']['code'], 'control_recovery_api_missing')
        self.assertFalse(result['guest_root_verified'])
        self.assertFalse(self.control.record['preload_recovery_required'])

    def test_child_isolation_and_source_identity_validation(self):
        manifest = {'synthetic-bound-source': 'a' * 64}
        result = jiritsu.result_base(self.control, 'authenticate')
        result.update(sources=manifest, phase='complete', authentication_verified=True,
                      events=[{'event': 'authentication_exchange', 'pid': 0x0336, 'command': 5,
                               'result': 6, 'success_byte': 1, 'reply_size': 512}])
        source = Mock(pmca=self.root, scripts=self.root)
        source.manifest.return_value = manifest
        completed = SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr='')
        with patch.object(jiritsu, 'Sources', return_value=source), \
                patch.object(jiritsu.subprocess, 'run', return_value=completed) as launch:
            actual = jiritsu.JiritsuConsumer(self.control).run()
        self.assertEqual(actual, result)
        args, kwargs = launch.call_args
        self.assertEqual(args[0][1:3], ['-I', '-B'])
        self.assertNotIn(self.control.context.lease, ' '.join(args[0]))
        self.assertEqual(json.loads(kwargs['input'])['lease'], self.control.context.lease)
        self.assertTrue(kwargs['capture_output'])
        result['events'] = []
        completed.stdout = json.dumps(result)
        with patch.object(jiritsu, 'Sources', return_value=source), \
                patch.object(jiritsu.subprocess, 'run', return_value=completed):
            no_result = jiritsu.JiritsuConsumer(self.control).run()
        self.assertEqual(no_result['blocked_reason']['code'], 'authentication_result_missing')
        self.assertFalse(no_result['authentication_verified'])
        result['sources'] = {}
        completed.stdout = json.dumps(result)
        with patch.object(jiritsu, 'Sources', return_value=source), \
                patch.object(jiritsu.subprocess, 'run', return_value=completed):
            refused = jiritsu.JiritsuConsumer(self.control).run()
        self.assertEqual(refused['blocked_reason']['code'], 'consumer_result_invalid')
        self.assertFalse(refused['authentication_verified'])

    def test_second_consumer_never_loads_usb_or_touches_connection(self):
        sources = Mock()
        with jiritsu.consumer_lock(self.control):
            result = jiritsu.consume(self.control, sources, 'authenticate', {})
        self.assertEqual(result['blocked_reason']['code'], 'consumer_busy')
        self.assertFalse(result['authentication_verified'])
        sources.load.assert_not_called()
        self.control.disconnect.assert_not_called()

    def test_missing_consumer_dependency_stays_false_with_explicit_reason(self):
        sources = Mock()
        sources.load.side_effect = ModuleNotFoundError("No module named 'usb'")
        result = jiritsu.consume(self.control, sources, 'authenticate', {})
        self.assertEqual(result['blocked_reason']['code'], 'consumer_dependency_missing')
        self.assertFalse(result['authentication_verified'])
        self.assertFalse(result['guest_root_verified'])
        self.control.disconnect.assert_not_called()

    def test_authenticate_existing_service_keeps_mode_and_does_not_read_hasp(self):
        from types import ModuleType
        self.control.target['product_id']=0x0336
        device=self.control.device()
        class Backend:
            def __init__(self,dev):self.dev=dev
            def getId(self):return 0x054c,0x0336
            def reset(self):pass
            def getEndpoints(self):return []
            def clearHalt(self,*args):pass
            def read(self,*args):raise AssertionError('no raw fixture transport')
            def write(self,*args):raise AssertionError('no raw fixture transport')
            def classInterfaceRequestOut(self,*args):raise AssertionError('no mode change')
            def vendorRequestOut(self,*args):raise AssertionError('no mode change')
        starts=[]
        class Auth:
            def __init__(self,driver):self.driver=driver
            def start(self):starts.append(True)
            def stop(self):raise AssertionError('existing service mode must be retained')
            def _sendAuthPacket(self,command,data=b''):
                return ({1:8,3:4,5:6}[command],b'\x01'+bytes(511))
            def authenticate(self):
                for command in (1,3,1,3,1,3,5):self._sendAuthPacket(command)
        sony=SimpleNamespace(SonySenserAuthDevice=Auth,SonySenserDevice=lambda driver:object(),
                             SonySenserCamera=Mock(side_effect=AssertionError('authenticate does not read HASP')))
        core=ModuleType('usb.core');core.find=Mock(return_value=[device])
        util=ModuleType('usb.util');util.claim_interface=Mock();util.dispose_resources=Mock()
        package=ModuleType('usb');package.core=core;package.util=util
        sources=Mock();sources.load.return_value=(None,sony,SimpleNamespace(GenericUsbDriver=lambda backend:backend),SimpleNamespace(UsbBackend=Backend),None,None,None)
        with patch.dict(sys.modules,{'usb':package,'usb.core':core,'usb.util':util}):
            result=jiritsu.consume(self.control,sources,'authenticate',{})
        self.assertEqual(result['phase'],'complete');self.assertEqual(starts,[True])
        self.assertTrue(result['authentication_verified']);self.assertFalse(result['guest_root_verified'])
        self.assertEqual([event['command'] for event in result['events'] if event['event']=='authentication_exchange'],[1,3,1,3,1,3,5])
        self.assertTrue(any(event['event']=='existing_service_mode_retained' for event in result['events']))
        self.assertFalse(any(event['event']=='stop_senser_requested' for event in result['events']))
        sony.SonySenserCamera.assert_not_called();util.dispose_resources.assert_called_once_with(device)
        self.control.disconnect.assert_not_called()

    def test_extra_root_commands_bound_across_isolated_consumer(self):
        commands=['echo virtual-file-readback']
        raw=json.dumps([{'command':command,'exit_status':0,'output':'Uid: 0 0 0 0\nGid: 0 0 0 0\n' if command==jiritsu.ROOT_COMMAND else 'readback'}
                        for command in [jiritsu.ROOT_COMMAND,*commands,jiritsu.ROOT_CLEANUP_COMMAND]])
        manifest={'fixture':'a'*64};result=jiritsu.result_base(self.control,'root')
        result.update(sources=manifest,phase='complete',authentication_verified=True,guest_root_verified=True,
                      requested_commands_verified=True,commands_json=raw,
                      events=[{'event':'authentication_exchange','pid':0x0336,'command':5,'result':6,'success_byte':1,'reply_size':512}])
        source=Mock(pmca=self.root,scripts=self.root);source.manifest.return_value=manifest
        completed=SimpleNamespace(returncode=0,stdout=json.dumps(result),stderr='')
        with patch.object(jiritsu,'Sources',return_value=source),patch.object(jiritsu.subprocess,'run',return_value=completed) as launch:
            actual=jiritsu.JiritsuConsumer(self.control).run('root',commands=commands)
        self.assertTrue(actual['requested_commands_verified'])
        self.assertEqual(json.loads(launch.call_args.kwargs['input'])['commands'],commands)
        result['commands_json']=raw.replace('echo virtual-file-readback','echo another-command');completed.stdout=json.dumps(result)
        with patch.object(jiritsu,'Sources',return_value=source),patch.object(jiritsu.subprocess,'run',return_value=completed):
            refused=jiritsu.JiritsuConsumer(self.control).run('root',commands=commands)
        self.assertEqual(refused['blocked_reason']['code'],'worker_command_failed')
        with patch.object(jiritsu.subprocess,'run') as launch:
            refused=jiritsu.JiritsuConsumer(self.control).run('version',commands=commands)
        launch.assert_not_called();self.assertEqual(refused['blocked_reason']['code'],'invalid_worker_commands')

    def test_large_out_check_is_bounded_and_bound_across_consumer(self):
        self.assertEqual(len(jiritsu.LARGE_OUT_CONTENT),70912)
        self.assertEqual(jiritsu.LARGE_OUT_CONTENT,bytes(range(256))*277)
        transport=object();version=Mock();deploy=Mock()
        deploy.OUT_PATH='/tmp/jiritsu/a7c2-out.txt';deploy._select.return_value=b'select';deploy._READ=b'read'
        deploy._write.return_value=b'write';deploy._read_path.return_value=jiritsu.LARGE_OUT_CONTENT
        row=jiritsu.check_large_out(transport,version,deploy,Mock())
        self.assertEqual(row['bytes'],70912);self.assertEqual(row['sha256'],jiritsu.LARGE_OUT_SHA256)
        deploy._write.assert_called_once_with(deploy.OUT_PATH,jiritsu.LARGE_OUT_CONTENT)
        deploy._read_path.return_value=jiritsu.LARGE_OUT_CONTENT+b'x'
        with self.assertRaises(jiritsu.ControlBlocked):jiritsu.check_large_out(transport,version,deploy,Mock())
        manifest={'fixture':'a'*64};result=jiritsu.result_base(self.control,'root')
        raw=json.dumps([{'command':command,'exit_status':0,'output':'Uid: 0 0 0 0\nGid: 0 0 0 0\n' if command==jiritsu.ROOT_COMMAND else ''}
                        for command in (jiritsu.ROOT_COMMAND,jiritsu.ROOT_CLEANUP_COMMAND)])
        result.update(sources=manifest,phase='complete',authentication_verified=True,guest_root_verified=True,commands_json=raw,
                      large_out_verified=True,large_out=row,
                      events=[{'event':'authentication_exchange','pid':0x0336,'command':5,'result':6,'success_byte':1,'reply_size':512}])
        source=Mock(pmca=self.root,scripts=self.root);source.manifest.return_value=manifest
        completed=SimpleNamespace(returncode=0,stdout=json.dumps(result),stderr='')
        with patch.object(jiritsu,'Sources',return_value=source),patch.object(jiritsu.subprocess,'run',return_value=completed) as launch:
            actual=jiritsu.JiritsuConsumer(self.control).run('root',large_out_check=True)
        self.assertTrue(actual['large_out_verified']);self.assertTrue(json.loads(launch.call_args.kwargs['input'])['large_out_check'])
        result['large_out']['sha256']='0'*64;completed.stdout=json.dumps(result)
        with patch.object(jiritsu,'Sources',return_value=source),patch.object(jiritsu.subprocess,'run',return_value=completed):
            refused=jiritsu.JiritsuConsumer(self.control).run('root',large_out_check=True)
        self.assertEqual(refused['blocked_reason']['code'],'large_out_readback_failed')
        with patch.object(jiritsu.subprocess,'run') as launch:
            refused=jiritsu.JiritsuConsumer(self.control).run('version',large_out_check=True)
        launch.assert_not_called();self.assertEqual(refused['blocked_reason']['code'],'invalid_large_out_check')

    def test_root_uses_version_not_hasp_and_keeps_direct_service(self):
        from types import ModuleType
        import hashlib
        self.control.target['product_id']=0x0336
        device=self.control.device();guard=Mock();guard.recovery=False;guard.capability=None
        guard.find.return_value=device;guard.check_device.return_value=self.control.target
        class Backend:
            def __init__(self,dev):self.dev=dev
            def getId(self):return 0x054c,0x0336
            def reset(self):pass
            def getEndpoints(self):return []
            def clearHalt(self,*args):pass
            def read(self,*args):raise AssertionError('no raw fixture transport')
            def write(self,*args):raise AssertionError('no raw fixture transport')
            def classInterfaceRequestOut(self,*args):raise AssertionError('no mode change')
            def vendorRequestOut(self,*args):raise AssertionError('no mode change')
        starts=[]
        class Auth:
            def __init__(self,driver):self.driver=driver
            def start(self):starts.append(True)
            def stop(self):raise AssertionError('direct Senser must not be stopped')
            def _sendAuthPacket(self,command,data=b''):
                return ({1:8,3:4,5:6}[command],b'\x01'+bytes(511))
            def authenticate(self):
                for command in (1,3,1,3,1,3,5):self._sendAuthPacket(command)
        sony=SimpleNamespace(SonySenserAuthDevice=Auth,SonySenserDevice=lambda driver:object(),
                             SonySenserCamera=Mock(side_effect=AssertionError('root must not read HASP')))
        version=SimpleNamespace(read_version=Mock(return_value=b'32014_05.2025101101'))
        raw=json.dumps([{'command':jiritsu.ROOT_COMMAND,'exit_status':0,
                         'output':'Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'}]).encode()
        deploy=SimpleNamespace(APPROVAL_TOKEN='arm-preload-once',
                               deploy_and_run=Mock(return_value=(raw,{'payload_ran':True,'mailbox_ok':True})))
        runner=SimpleNamespace(command_runner_driver=Mock(return_value='driver'))
        sources=Mock();sources.load.return_value=(None,sony,SimpleNamespace(GenericUsbDriver=lambda backend:backend),
                                                   SimpleNamespace(UsbBackend=Backend),version,deploy,runner)
        payload=b'\x7fELFworker'
        sources.payload.return_value=payload
        core=ModuleType('usb.core');core.find=Mock(return_value=[device])
        util=ModuleType('usb.util');util.claim_interface=Mock();util.dispose_resources=Mock()
        package=ModuleType('usb');package.core=core;package.util=util
        def neutralize(_transport,_control,_guard,_version,_log):
            self.control.record_preload_recovery(jiritsu.NEUTRAL)
        with patch.dict(sys.modules,{'usb':package,'usb.core':core,'usb.util':util}), \
                patch.object(jiritsu,'TargetGuard',return_value=guard), \
                patch.object(jiritsu,'PAYLOAD_SHA256',hashlib.sha256(payload).hexdigest()), \
                patch.object(jiritsu,'neutralize_preload',side_effect=neutralize):
            result=jiritsu.consume(self.control,sources,'root',{})
        self.assertEqual(result['phase'],'complete');self.assertTrue(result['guest_root_verified'])
        self.assertEqual(result['version']['content_hex'],b'32014_05.2025101101'.hex())
        self.assertEqual(starts,[True]);sony.SonySenserCamera.assert_not_called()
        runner.command_runner_driver.assert_called_once_with([jiritsu.ROOT_COMMAND,jiritsu.ROOT_CLEANUP_COMMAND],interactive=False)
        self.assertFalse(any(event['event']=='stop_senser_requested' for event in result['events']))
        self.assertFalse(result['preload_recovery_required']);util.dispose_resources.assert_called_once_with(device)

    @unittest.skipUnless(VERSION is not None, 'optional jiritsu protocol scripts not installed')
    def test_source_manifest_contains_original_worker_and_pmca(self):
        sources = jiritsu.Sources()
        if not (sources.pmca / 'pmca/usb/sony.py').exists():
            self.skipTest('local PMCA checkout unavailable')
        manifest = sources.manifest('version')
        for path in (sources.scripts / 'jiritsu_run_command.py',
                     sources.scripts / 'jiritsu_preload_deploy.py', sources.pmca / 'pmca/usb/sony.py'):
            self.assertIn(str(path.resolve()), manifest)
        self.assertNotIn(str((sources.scripts / 'usb_service_probe.py').resolve()), manifest)
        changed = dict(manifest)
        changed[str(sources.scripts / 'jiritsu_version_read.py')] = '0' * 64
        self.assert_blocked('consumer_source_changed', lambda: sources.verify(changed, 'version'))

    @unittest.skipUnless(VERSION is not None, 'optional jiritsu protocol scripts not installed')
    def test_version_import_keeps_bound_pmca_without_research_probe(self):
        import subprocess
        code = '''import sys
from pathlib import Path
sys.path.insert(0, %r)
import usb_jiritsu as j
s=j.Sources();m=s.manifest("version");probe,*_=s.load(m,"version")
assert probe is None and "usb_service_probe" not in sys.modules
assert Path(sys.modules["pmca"].__file__).resolve().is_relative_to(s.pmca)
''' % str(Path(jiritsu.__file__).resolve().parent)
        subprocess.run([sys.executable, '-I', '-B', '-c', code], check=True, capture_output=True)


class EvidenceTests(unittest.TestCase):
    def test_root_session_budget_preserves_cleanup_reserve(self):
        self.assertEqual(jiritsu.session_budget_seconds(0),180)
        self.assertEqual(jiritsu.session_budget_seconds(4),300)
        self.assertEqual(jiritsu.session_budget_seconds(16),660)
        for invalid in (-1,17,True,1.5,'4'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):jiritsu.session_budget_seconds(invalid)

    def test_worker_command_bounds_and_actual_cleanup_receipts(self):
        commands=['echo virtual-only']
        self.assertEqual(jiritsu.validate_commands('root',commands),commands)
        for invalid in ('command',[''],['x'*7801],['echo x']*17,['echo 中文'],['echo\x00bad']):
            with self.subTest(commands=invalid),self.assertRaises(jiritsu.ControlBlocked):jiritsu.validate_commands('root',invalid)
        rows=[{'command':command,'exit_status':0} for command in [jiritsu.ROOT_COMMAND,*commands,jiritsu.ROOT_CLEANUP_COMMAND]]
        self.assertTrue(jiritsu.command_results_verified(json.dumps(rows),commands))
        for bad in (rows[:-1],list(reversed(rows)),[dict(row,exit_status=True) for row in rows],
                    [dict(row,exit_status=1) if index==1 else row for index,row in enumerate(rows)]):
            self.assertFalse(jiritsu.command_results_verified(json.dumps(bad),commands))

    def test_authentication_requires_real_final_result_and_success_byte(self):
        valid = [(1, 2, b'challenge'), (3, 4, b'')] * 3 + [(5, 6, b'\x01')]
        self.assertTrue(jiritsu.authentication_proven(valid))
        for bad in ([], valid[:-1], valid[:-1] + [(5, 6, b'')],
                    valid[:-1] + [(5, 6, b'\x00')], valid[:-1] + [(5, 0, b'\x01')],
                    valid[:-1] + [(5, 6, None)]):
            with self.subTest(bad=bad[-1:] if bad else bad):
                self.assertFalse(jiritsu.authentication_proven(bad))

    @unittest.skipUnless(VERSION is not None, 'optional jiritsu protocol scripts not installed')
    def test_original_command_runner_json_reaches_root_parser(self):
        with patch.dict(sys.modules, {'jiritsu_version_read': VERSION}):
            deploy = archive_module('jiritsu_preload_deploy')
            with patch.dict(sys.modules, {'jiritsu_preload_deploy': deploy}):
                runner = archive_module('jiritsu_run_command')
        def reply(_transport, _requests, command, marker, _log, **_kwargs):
            self.assertEqual(command, jiritsu.ROOT_COMMAND)
            return (f'A7C2-OUT-1\nCMD echo A7C2-{marker}; {command}\nA7C2-{marker}\n'
                    'Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\nEXIT 0\nA7C2-END\n').encode()
        driver = runner.command_runner_driver([jiritsu.ROOT_COMMAND], out_stream=io.StringIO())
        record = {}
        with patch.object(runner, 'submit_command', side_effect=reply) as submit:
            raw = driver(object(), {}, lambda *_a, **_k: None, record)
        self.assertEqual(jiritsu.root_from_commands(raw), {'uid': [0]*4, 'gid': [0]*4})
        self.assertTrue(record['payload_ran'])
        self.assertTrue(record['mailbox_ok'])
        submit.assert_called_once()

    def test_only_four_zero_uid_and_gid_columns_prove_root(self):
        def raw(output, status=0, command=jiritsu.ROOT_COMMAND):
            return json.dumps([{'command': command, 'exit_status': status, 'output': output}])
        valid = 'Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'
        self.assertEqual(jiritsu.root_from_commands(raw(valid)), {'uid': [0]*4, 'gid': [0]*4})
        for text in ('uid=0(root) gid=0(root)', 'Uid: 0 0 0 0', 'Gid: 0 0 0 0',
                     'Uid: 0 0 0\nGid: 0 0 0 0', 'Uid: 0 0 0 0\nGid: 0 0 1 0',
                     'Uid: 0 0 0 0 0\nGid: 0 0 0 0', valid + 'Uid: 0 0 0 0'):
            self.assertIsNone(jiritsu.root_from_commands(raw(text)))
        for kwargs in ({'status': 1}, {'status': None}, {'status': False}, {'command': 'id'}):
            self.assertIsNone(jiritsu.root_from_commands(raw(valid, **kwargs)))
        for malformed in ('null', '{}', '[true]', 'not json'):
            self.assertIsNone(jiritsu.root_from_commands(malformed))


class ReplayDriver:
    """Four fixed replies to the original framed select/write/select/read calls."""
    def __init__(self, after, read_failure=False):
        self.writes = []
        self.replies = []
        for sequence in range(4):
            payload = struct.pack('<I', 0) + (after if sequence == 3 else b'')
            self.replies += [VERSION.HEADER.pack(len(payload), 0x40, sequence, 0, 0, 0, 0), payload]
        if read_failure:
            self.replies[-1] = b''

    def getId(self):
        return 0x054c, 0x0336

    def write(self, data):
        self.writes.append(data)

    def read(self, count):
        return self.replies.pop(0)


@unittest.skipUnless(VERSION is not None, 'optional jiritsu protocol scripts not installed')
class RecoveryTests(unittest.TestCase):
    setUp = GuardTests.setUp

    def transport(self, after, read_failure=False):
        return SimpleNamespace(driver=ReplayDriver(after, read_failure), _sequence=0)

    def test_recovery_clear_requires_exact_bytes_from_real_exchange_parser(self):
        self.control.mark_recovery_required('synthetic deployment begun')
        guard = jiritsu.TargetGuard(self.control, recovery=True)
        transport = self.transport(jiritsu.NEUTRAL)
        jiritsu.neutralize_preload(transport, self.control, guard, VERSION, lambda *_a, **_k: None)
        self.control.record_preload_recovery.assert_called_once_with(jiritsu.NEUTRAL)
        self.assertFalse(self.control.record['preload_recovery_required'])
        self.assertEqual(len(transport.driver.writes), 4)
        write = transport.driver.writes[1][VERSION.HEADER.size:]
        self.assertEqual(write, struct.pack('<HH', 0x1001, 0x10) + b'\x00\xff\x00' + b' '*512)
        self.control.disconnect.assert_not_called()

    def test_ack_absent_newlines_wrong_size_and_short_read_never_clear(self):
        for after, broken in ((b'', False), (b'\n'*512, False), (b' '*511, False),
                              (b'foreign-library.so', False), (jiritsu.NEUTRAL, True)):
            with self.subTest(after_size=len(after), broken=broken):
                self.control.record_preload_recovery.reset_mock()
                self.control.mark_recovery_required('synthetic pending')
                guard = jiritsu.TargetGuard(self.control, recovery=True)
                with self.assertRaises((jiritsu.ControlBlocked, ValueError)):
                    jiritsu.neutralize_preload(self.transport(after, broken), self.control, guard,
                                               VERSION, lambda *_a, **_k: None)
                self.control.record_preload_recovery.assert_not_called()
                self.assertTrue(self.control.record['preload_recovery_required'])
                self.control.disconnect.assert_not_called()

    def test_recovery_required_and_owner_read_failure_never_stop_or_detach(self):
        for owner_lost in (False, True):
            with self.subTest(owner_lost=owner_lost):
                self.control.mark_recovery_required('PreloadRecoveryRequired')
                auth, dispose, guard = Mock(), Mock(), Mock()
                with patch.object(self.control, '_load', side_effect=OSError('owner lost')) if owner_lost else \
                        patch.object(self.control, '_load', wraps=self.control._load):
                    pending = jiritsu.end_session(self.control, guard, auth, object(), dispose,
                                                  lambda *_a, **_k: None)
                self.assertTrue(pending)
                auth.stop.assert_not_called()
                guard.check_device.assert_not_called()
                dispose.assert_called_once()
                self.control.disconnect.assert_not_called()
                self.control.record_preload_recovery.assert_not_called()

    def test_preload_recovery_exception_remains_structured_and_latched(self):
        deploy = archive_module('jiritsu_preload_deploy') if 'jiritsu_version_read' in sys.modules else None
        if deploy is None:
            with patch.dict(sys.modules, {'jiritsu_version_read': VERSION}):
                deploy = archive_module('jiritsu_preload_deploy')
        sources = Mock()
        sources.load.side_effect = deploy.PreloadRecoveryRequired('synthetic cleanup readback failed')
        result = jiritsu.consume(self.control, sources, 'root', {'synthetic': 'not an enumeration claim'})
        self.assertEqual(result['phase'], 'recovery_required')
        self.assertTrue(result['preload_recovery_required'])
        self.assertFalse(result['authentication_verified'])
        self.assertFalse(result['guest_root_verified'])
        self.control.disconnect.assert_not_called()
        self.control.record_preload_recovery.assert_not_called()

    def test_exception_keeps_connection_when_persisting_latch_failed(self):
        auth, guard, dispose = Mock(), Mock(), Mock()
        self.assertFalse(self.control.record['preload_recovery_required'])
        pending = jiritsu.end_session(self.control, guard, auth, object(), dispose,
                                      lambda *_a, **_k: None, recovery_required=True)
        self.assertTrue(pending)
        auth.stop.assert_not_called()
        self.control.disconnect.assert_not_called()
        self.control.record_preload_recovery.assert_not_called()

    def test_successful_cleanup_rechecks_target_before_original_stop(self):
        guard, auth, dispose = Mock(), Mock(), Mock()
        device = object()
        self.assertFalse(jiritsu.end_session(self.control, guard, auth, device, dispose, lambda *_a, **_k: None))
        guard.check_device.assert_called_once_with(device)
        auth.stop.assert_called_once()
        dispose.assert_called_once_with(device)
        self.control.disconnect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
