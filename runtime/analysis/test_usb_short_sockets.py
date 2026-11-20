"""Synthetic USB short-socket wiring checks; no QEMU, VHCI or physical USB."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import runpy
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import sony_usb_device as sony
import usb_control as control
import usb_jiritsu as jiritsu
import usb_ui


class FakeRoots:
    """Exercise consumer wiring only; does not replace runtime profile admission."""
    def __init__(self, run):
        self.files = run
        self.sockets = run / 'sockets'
        self.valid = True
        self.connections = []
        self.endpoints = {}

    def binding(self):
        if not self.valid:
            raise ValueError('binding changed')
        return {'profile': 'synthetic-only', 'files': str(self.files),
                'sockets': str(self.sockets), 'directories': {'synthetic': {'ino': 10}}}

    def child(self, path):
        if path.parent != self.sockets:
            raise ValueError('foreign endpoint')

    def endpoint(self, path):
        self.child(path)
        self.binding()
        return dict(ino=self.endpoints.get(path, 20), mode=0o600)

    @contextmanager
    def connect_path(self, path):
        self.endpoint(path)
        self.connections.append(path)
        yield 'synthetic-fd/' + path.name
        self.endpoint(path)


class UsbShortSocketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='usb-short-consumer-')
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.roots = FakeRoots(self.run)
        self.legacy = dict(run_id=self.run.name, qmp_path=str(self.run/'qmp.sock'),
                           backend_path=str(self.run/'usb-endpoint.sock'),
                           lease='s'*48, vm_pid=os.getpid())
        self.bound = dict(self.legacy, qmp_path=str(self.roots.sockets/'usb-qmp.sock'),
                          backend_path=str(self.roots.sockets/'usb-endpoint.sock'),
                          socket_root=str(self.roots.sockets), socket_profile='synthetic-only',
                          socket_binding=self.roots.binding())
        self.module = SimpleNamespace(roots_for_run=Mock(return_value=self.roots))

    def make_control(self, fields=None, roots=True):
        self.module.roots_for_run.return_value = self.roots if roots else None
        with patch.dict(sys.modules, single_ap_sockets=self.module):
            return control.UsbControl(self.run, **(self.bound if fields is None else fields))

    def test_context_accepts_complete_legacy_and_new_schemas(self):
        for fields in (self.legacy, self.bound):
            self.assertEqual(control.context_arguments(fields), fields)
            self.assertIsNot(control.context_arguments(fields), fields)

    def test_context_rejects_every_partial_new_schema_and_null(self):
        names = ('socket_root', 'socket_profile', 'socket_binding')
        for mask in range(1, 7):
            fields = dict(self.legacy, **{name: self.bound[name] for bit, name in enumerate(names) if mask & (1 << bit)})
            with self.subTest(mask=mask), self.assertRaises(control.ControlBlocked):
                control.context_arguments(fields)
        for name in names:
            fields = dict(self.bound, **{name: None})
            with self.subTest(name=name), self.assertRaises(control.ControlBlocked):
                control.context_arguments(fields)
        with self.assertRaises(control.ControlBlocked):
            control.context_arguments(dict(self.bound, sysfs_root='/dev'))

    def test_legacy_endpoint_contract_stays_available(self):
        instance = self.make_control(self.legacy, roots=False)
        self.assertEqual(instance.context.binding_fields(), {})
        self.assertEqual(instance.context.context_fields(), self.legacy)
        self.assertEqual(instance._socket_arguments(), [])

    def test_bound_endpoint_contract_and_child_arguments(self):
        instance = self.make_control()
        self.assertEqual(instance.context.context_fields(), self.bound)
        flags = instance._socket_arguments()
        self.assertEqual(flags[:4], ['--socket-root', self.bound['socket_root'], '--socket-profile', 'synthetic-only'])
        self.assertEqual(json.loads(flags[5]), self.bound['socket_binding'])
        record = instance._new_owner()
        self.assertEqual(record['socket_binding'], self.bound['socket_binding'])
        self.assertEqual(set(record['socket_endpoints']), {self.bound['qmp_path'], self.bound['backend_path']})

    def test_legacy_declarations_cannot_silently_follow_short_run(self):
        with self.assertRaises(control.usbip.Blocked):
            self.make_control(self.legacy)

    def test_short_declarations_require_admitted_roots(self):
        with self.assertRaises(control.usbip.Blocked):
            self.make_control(self.bound, roots=False)

    def test_wrong_binding_root_profile_and_foreign_endpoint_are_refused(self):
        variants = ({'socket_root': str(self.run/'other')}, {'socket_profile': 'other'},
                    {'socket_binding': {}}, {'qmp_path': self.legacy['qmp_path']},
                    {'backend_path': self.bound['qmp_path']})
        for changes in variants:
            with self.subTest(changes=changes), self.assertRaises((ValueError, control.usbip.Blocked)):
                self.make_control(dict(self.bound, **changes))

    def test_binding_is_rechecked_without_changing_original_bridge_hello(self):
        instance = self.make_control()
        self.assertEqual(instance.context.identity(), {key: self.bound[key] for key in ('run_id', 'lease', 'qmp_path', 'vm_pid')})
        self.roots.valid = False
        with self.assertRaises(ValueError):
            instance.context.identity()
        with self.assertRaises(ValueError):
            instance._socket_arguments()

    def test_owner_record_rechecks_binding_and_endpoint_identities(self):
        instance = self.make_control()
        record = instance._new_owner()
        record['socket_binding'] = {'changed': True}
        with patch.object(control, 'read_json', return_value=record), self.assertRaises(control.ControlBlocked):
            instance._load()
        record = instance._new_owner()
        record['socket_endpoints'][self.bound['qmp_path']]['ino'] = 99
        with patch.object(control, 'read_json', return_value=record), self.assertRaises(control.ControlBlocked):
            instance._load()

    def test_qmp_uses_bound_connection_and_retains_peer_pid_check(self):
        instance = self.make_control()
        peer = Mock()
        peer.__enter__ = Mock(return_value=peer)
        peer.__exit__ = Mock(return_value=False)
        peer.getsockopt.return_value = struct.pack('3i', os.getpid()+1, os.getuid(), os.getgid())
        with patch.object(control.usbip, 'check_unix'), patch.object(control.socket, 'socket', return_value=peer):
            with self.assertRaises(control.ControlBlocked) as caught:
                instance._check_vm()
        self.assertEqual(caught.exception.code, 'qmp_owner_mismatch')
        peer.connect.assert_called_once_with('synthetic-fd/usb-qmp.sock')
        peer.makefile.assert_not_called()

    def test_ui_dispatches_complete_new_context_and_refuses_mixed(self):
        fake = Mock()
        fake.status.return_value = {'phase': 'disconnected'}
        with patch.object(usb_ui, 'read_json', return_value=self.bound), patch.object(usb_ui, 'UsbControl', return_value=fake) as constructor:
            self.assertEqual(usb_ui.action(self.run, 'status'), {'phase': 'disconnected'})
            constructor.assert_called_once_with(self.run, **self.bound)
        with patch.object(usb_ui, 'read_json', return_value=dict(self.legacy, socket_root='unexpected')), patch.object(usb_ui, 'UsbControl') as constructor:
            with self.assertRaises(control.ControlBlocked):
                usb_ui.action(self.run, 'connect')
            constructor.assert_not_called()

    def test_sony_environment_routes_only_endpoints_to_short_root(self):
        current = {'A7C2_SONY_USB_DEVICE': sony.PROFILE, 'A7C2_ORIGINAL_COLD': 'original-init-v1',
                   'A7C2_USB_DEVICE_BUILD': 'synthetic-build'}
        with patch.dict(sys.modules, single_ap_sockets=self.module), patch.object(sony, 'candidate', return_value=Path('/synthetic/qemu')):
            env = sony.environment(current, self.run)
        self.assertEqual(env['QEMU_SONY_USB_QMP_HOST_PATH'], self.bound['qmp_path'])
        self.assertEqual(env['QEMU_SONY_USB_BACKEND_SOCKET'], '/sockets/usb-endpoint.sock')
        self.assertFalse((self.roots.sockets/'usb-context.json').exists())

    def test_sony_network_routes_are_refused_before_candidate_build(self):
        for name in ('A7C2_USB_NET','MENU_USB_NET','QEMU_SONY_USB_NET','A7C2_USB_NET_SELFTEST'):
            with patch.dict(sys.modules, single_ap_sockets=self.module), patch.object(sony, 'candidate') as candidate:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    sony.environment({name: '1'}, self.run)
                candidate.assert_not_called()

    def test_publish_context_keeps_file_in_run_and_checks_vm_before_write(self):
        env = {'A7C2_SONY_USB_DEVICE': sony.PROFILE, 'QEMU_SONY_USB_LEASE': self.bound['lease']}
        owner = Mock()
        with patch.dict(sys.modules, single_ap_sockets=self.module), patch.object(control, 'UsbControl', return_value=owner) as constructor, patch.object(control.usbip, 'write_owned_json') as output:
            sony.publish_context(env, self.run, os.getpid())
        constructor.assert_called_once_with(self.run, **self.bound)
        owner._check_vm.assert_called_once_with()
        output.assert_called_once_with(self.run/'usb-context.json', self.bound)

    def test_jiritsu_child_context_accepts_exact_schemas_and_rejects_extra_provider(self):
        metadata = dict(action='authenticate', sources={}, scripts='/synthetic', pmca='/synthetic', run_dir=str(self.run))
        for fields in (self.legacy, self.bound):
            self.assertEqual(jiritsu.consumer_context(dict(metadata, **fields)), fields)
        with self.assertRaises(control.ControlBlocked):
            jiritsu.consumer_context(dict(metadata, **self.bound, sysfs_root='/dev'))
        with self.assertRaises(control.ControlBlocked):
            jiritsu.consumer_context(dict(metadata, **self.legacy, socket_root='/run/user/other'))

    def test_context_creation_cannot_open_the_fixed_runtime_gate(self):
        import single_ap_sockets
        with patch.dict(os.environ, {single_ap_sockets.PROFILE_ENV: single_ap_sockets.PROFILE,
                                     single_ap_sockets.ROOT_ENV: '/run/user/'+str(os.geteuid())+'/synthetic-unallocated'}):
            with self.assertRaises(RuntimeError):
                control.UsbControl(self.run, **self.legacy)

    def test_jiritsu_parent_transmits_and_rechecks_child_binding(self):
        instance = self.make_control()
        received = jiritsu.result_base(instance, 'authenticate')
        sources = Mock(scripts=self.run, pmca=self.run)
        sources.manifest.return_value = {}
        completed = SimpleNamespace(returncode=2, stdout=json.dumps(received), stderr='')
        with patch.object(jiritsu, 'TargetGuard'), patch.object(jiritsu, 'Sources', return_value=sources), patch.object(jiritsu.subprocess, 'run', return_value=completed) as execute:
            self.assertEqual(jiritsu.JiritsuConsumer(instance).run(), received)
            request = json.loads(execute.call_args.kwargs['input'])
            for key, value in self.bound.items():
                self.assertEqual(request[key], value)
            self.assertNotIn(self.bound['lease'], ' '.join(execute.call_args.args[0]))
            received['socket_binding'] = {'changed': True}
            completed.stdout = json.dumps(received)
            result = jiritsu.JiritsuConsumer(instance).run()
            self.assertEqual(result['blocked_reason']['code'], 'consumer_result_invalid')

    def test_authentication_tool_passes_full_bound_context(self):
        path = Path(__file__).resolve().parents[2]/'tools/jiritsu-authenticate.py'
        entry = runpy.run_path(str(path))
        namespace = entry['main'].__globals__
        run = namespace['ANALYSIS']/'menu-runs/run-usb-short-synthetic'
        fake = Mock()
        fake.run.return_value = dict(phase='complete', authentication_verified=True)
        with patch.dict(namespace, read_json=Mock(return_value=self.bound), UsbControl=Mock(), JiritsuConsumer=Mock(return_value=fake)), patch.object(control.usbip, 'write_owned_json'), patch('builtins.print'):
            self.assertEqual(entry['main'](['--run', str(run)]), 0)
            namespace['UsbControl'].assert_called_once_with(run, **self.bound)


class BridgeShortSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_short_connection_still_rejects_wrong_vm_peer(self):
        roots = FakeRoots(Path('/synthetic'))
        context = control.usbip.Context(roots.files, roots.sockets/'qmp.sock', roots.sockets/'backend.sock', 's'*48, os.getpid(), 'synthetic', roots)
        writer = Mock()
        writer.wait_closed = AsyncMock()
        writer.get_extra_info.return_value.getsockopt.return_value = struct.pack('3i', os.getpid()+1, os.getuid(), os.getgid())
        with patch.object(control.usbip, 'check_unix'), patch.object(control.usbip.asyncio, 'open_unix_connection', AsyncMock(return_value=(Mock(), writer))):
            with self.assertRaises(control.usbip.Blocked):
                await control.usbip.Bridge.open(context, 'control')
        self.assertEqual(roots.connections, [context.backend_path])
        writer.close.assert_called_once_with()
        writer.wait_closed.assert_awaited_once_with()


if __name__ == '__main__':
    unittest.main()
