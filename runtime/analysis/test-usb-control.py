#!/usr/bin/env python3
"""Control tests use fake sysfs and synthetic endpoint/QMP peers, never host drivers."""
import asyncio
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import usb_control as control
import sys
sys.path.insert(0, str(Path(__file__).parent / 'usb-gadget'))
from test_support import DESCRIPTORS, DEVICE_BYTES, SyntheticBackend


class LocalPeers:
    def __init__(self, context):
        self.context = context
        self.loop = asyncio.new_event_loop()
        self.backend = SyntheticBackend(context)
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.qmp_requests = []
        self.call(self.backend.start())
        self.qmp = socket.socket(socket.AF_UNIX)
        self.qmp.bind(str(context.qmp_path))
        os.chmod(context.qmp_path, 0o600)
        self.qmp.listen()
        self.qmp.settimeout(0.1)
        self.stopping = threading.Event()
        self.qmp_thread = threading.Thread(target=self.qmp_loop, daemon=True)
        self.qmp_thread.start()

    def call(self, awaitable):
        return asyncio.run_coroutine_threadsafe(awaitable, self.loop).result(5)

    def qmp_loop(self):
        while not self.stopping.is_set():
            try:
                peer, _ = self.qmp.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with peer:
                peer.settimeout(1)
                try:
                    with peer.makefile('rwb', buffering=0) as stream:
                        stream.write(b'{"QMP":{"version":{},"capabilities":[]}}\n')
                        while raw := stream.readline(16385):
                            request = json.loads(raw)
                            self.qmp_requests.append(request['execute'])
                            stream.write((json.dumps({'return': {'status': 'running'} if request['execute'] == 'query-status' else {},
                                                      'id': request['id']}) + '\n').encode())
                except (ConnectionError, OSError):
                    pass

    def close(self):
        self.call(self.backend.close())
        self.stopping.set()
        self.qmp.close()
        self.qmp_thread.join(2)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(2)
        self.loop.close()


class ControlTests(unittest.TestCase):
    def setUp(self):
        # AF_UNIX paths must fit even when the runner's TMPDIR is a long checkout path.
        self.tmp = tempfile.TemporaryDirectory(prefix='usb-control-synthetic-', dir='/tmp')
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run-test'
        self.run.mkdir(mode=0o700)
        self.sysfs = self.root / 'sys'
        self.sysfs.mkdir()
        self.control = control.UsbControl(self.run, qmp_path=self.run / 'qmp.sock', lease='k' * 48,
                                          vm_pid=os.getpid(), sysfs_root=self.sysfs)
        self.peers = LocalPeers(self.control.context)
        self.controller = self.sysfs / 'devices/platform/vhci_hcd.0'
        self.writes = []
        self.retained_socket = None
        self.header = 'hub port sta spd dev sockfd local_busid\n'

    def tearDown(self):
        try:
            try:
                record = self.control._load()
            except (OSError, control.usbip.Blocked):
                record = {}
            if record.get('server_pid'):
                self.control._stop_server(record)
        finally:
            if self.retained_socket is not None:
                os.close(self.retained_socket)
            self.peers.close()
            self.tmp.cleanup()

    def modules(self):
        for name in ('vhci_hcd', 'usbip_core'):
            (self.sysfs / 'module' / name).mkdir(parents=True)
        self.controller.mkdir(parents=True)
        for name in ('attach', 'detach'):
            (self.controller / name).write_text('')
        self.set_rows()

    def set_rows(self, active=None):
        rows = ['hs 0 4 0 00000000 0 0-0', 'ss 1 4 0 00000000 0 0-0',
                'hs 2 6 3 000a000b 99 3-3']
        if active:
            rows[0] = f"hs 0 6 {active['speed']} {active['devid']:08x} {active['sockfd']} 7-1"
        (self.controller / 'status').write_text(self.header + '\n'.join(rows) + '\n')

    def write_fake_sysfs(self, controller, attribute, value):
        self.writes.append((controller, attribute, value))
        if attribute == 'attach':
            port, fd, devid, speed = map(int, value.split())
            self.assertEqual(port, 0)
            self.retained_socket = os.dup(fd)
            self.set_rows({'devid': devid, 'speed': speed, 'sockfd': fd})
            device = self.controller / 'usb7/7-1'
            device.mkdir(parents=True, exist_ok=True)
            for name, content in (('busnum', '7'), ('devnum', '2'), ('idVendor', '1234'), ('idProduct', '5678')):
                (device / name).write_text(content)
            (device / 'descriptors').write_bytes(DESCRIPTORS)
            aliases = self.sysfs / 'bus/usb/devices'
            aliases.mkdir(parents=True, exist_ok=True)
            (aliases / '7-1').unlink(missing_ok=True)
            (aliases / '7-1').symlink_to(device)
        else:
            self.assertEqual(value, '0\n')
            os.close(self.retained_socket)
            self.retained_socket = None
            self.set_rows()

    def test_check_missing_modules_clear_reason_no_host_mutation(self):
        state = self.control.status()
        self.assertTrue(state['backend_ready'])
        self.assertEqual(state['blocked_reason']['code'], 'vhci_module_not_loaded')
        self.assertFalse(state['host_enumerated'])
        self.assertFalse(self.control.owner_file.exists())
        self.assertEqual(self.peers.qmp_requests, ['qmp_capabilities', 'query-status'])
        self.assertFalse(any(e[0] == 'vbus' for e in self.peers.backend.events))

    def test_connect_missing_modules_does_not_apply_vbus(self):
        result = self.control.connect()
        self.assertEqual(result['blocked_reason']['code'], 'vhci_module_not_loaded')
        self.assertFalse(result['cable_connected'])
        self.assertFalse(self.control.owner_file.exists())
        self.assertFalse(any(e[0] == 'vbus' for e in self.peers.backend.events))

    def test_permission_denied_reported_before_connect(self):
        self.modules()
        with patch.object(control.os, 'access', return_value=False):
            for action in (self.control.status, self.control.connect):
                result = action()
                self.assertEqual(result['blocked_reason']['code'], 'vhci_permission_denied')
        self.assertFalse(any(e[0] == 'vbus' for e in self.peers.backend.events))

    def test_unknown_backend_never_starts_server_or_exports(self):
        self.peers.backend.bad_identity = True
        self.modules()
        with patch.object(self.control, '_start_server') as start:
            state = self.control.connect()
            start.assert_not_called()
        self.assertEqual(state['phase'], 'blocked')
        self.assertFalse(state['exported'])
        self.assertFalse(state['authentication_verified'])
        self.assertFalse(state['guest_root_verified'])

    def test_not_ready_no_fake_enumeration(self):
        self.peers.backend.ready = False
        state = self.control.status()
        self.assertEqual(state['phase'], 'blocked')
        self.assertFalse(state['backend_ready'])
        self.assertIsNone(state['target'])

    def test_qmp_default_permissions_and_unsafe_socket(self):
        self.modules()
        self.control.context.qmp_path.chmod(0o755)
        self.assertIsNone(self.control.status()['blocked_reason'])
        self.control.context.qmp_path.chmod(0o777)
        self.assertEqual(self.control.status()['phase'], 'blocked')
        self.control.context.qmp_path.chmod(0o600)
        self.control.context.backend_path.chmod(0o666)
        self.assertEqual(self.control.status()['phase'], 'blocked')

    def test_qmp_wrong_pid_rejected(self):
        bad = control.UsbControl(self.run, qmp_path=self.run / 'qmp.sock', lease='k' * 48,
                                 vm_pid=os.getpid() + 10000, sysfs_root=self.sysfs)
        self.assertEqual(bad.status()['blocked_reason']['code'], 'qmp_owner_mismatch')

    def test_control_refuses_world_writable_run_and_socket_symlink(self):
        self.run.chmod(0o777)
        with self.assertRaises(control.usbip.Blocked):
            control.UsbControl(self.run, qmp_path=self.run / 'qmp.sock', lease='k' * 48, vm_pid=os.getpid())
        self.run.chmod(0o700)
        (self.run / 'alias.sock').symlink_to(self.run / 'qmp.sock')
        with self.assertRaises(control.usbip.Blocked):
            control.UsbControl(self.run, qmp_path=self.run / 'alias.sock', lease='k' * 48, vm_pid=os.getpid())

    def test_attach_waits_for_actual_kernel_identity_without_second_attach(self):
        self.modules()
        original=self.control._rows
        transient=[False]
        def write(controller,attribute,value):
            self.write_fake_sysfs(controller,attribute,value)
            if attribute=='attach':transient[0]=True
        def rows(controller):
            values=original(controller)
            if transient[0]:
                transient[0]=False
                values[0]={**values[0],'status':5,'speed':0,'devid':0,'local_busid':'0-0'}
            return values
        with patch.object(self.control,'_write_sysfs',write),patch.object(self.control,'_rows',rows):
            result=self.control.connect()
            self.assertTrue(result['host_enumerated'])
            self.assertEqual(len([row for row in self.writes if row[1]=='attach']),1)
            self.assertEqual(self.control.disconnect()['phase'],'disconnected')
            self.assertEqual(self.control.disconnect()['phase'],'disconnected')
            self.assertNotIn('attachment_id',self.control._load())
            self.assertTrue(self.control._load()['previous_import']['attachment_id'])

    def test_fresh_control_reaps_exact_exited_child_server(self):
        import subprocess
        process=subprocess.Popen([sys.executable,'-c','pass'])
        self.addCleanup(process.wait)
        start=control.process_start(process.pid)
        os.waitid(os.P_PID,process.pid,os.WEXITED|os.WNOWAIT)
        record={'server_pid':process.pid,'server_start':start,'preload_recovery_required':False}
        fresh=control.UsbControl(self.run,qmp_path=self.run/'qmp.sock',lease='k'*48,vm_pid=os.getpid(),sysfs_root=self.sysfs)
        fresh._stop_server(record)
        self.assertNotIn('server_pid',record)
        self.assertFalse(Path('/proc',str(process.pid)).exists())

    def test_connect_real_protocol_server_with_fake_vhci_then_only_own_detach(self):
        self.modules()
        with patch.object(self.control, '_write_sysfs', side_effect=self.write_fake_sysfs):
            state = self.control.connect()
            self.assertEqual(state['phase'], 'enumerated', state)
            self.assertTrue(state['host_enumerated'])
            self.assertFalse(state['authentication_verified'])
            target = self.control.jiritsu_target(state['target']['sysfs_path'])
            self.assertTrue(target['virtual_ancestor_verified'])
            self.assertEqual(target['vendor_id'], 0x1234)
            self.assertFalse(target['guest_root_verified'])
            disconnected = self.control.disconnect()
            self.assertEqual(disconnected['phase'], 'disconnected', disconnected)
        self.assertEqual([item[1] for item in self.writes], ['attach', 'detach'])
        self.assertEqual(self.writes[-1][2], '0\n')
        self.assertIn('hs 2 6 3 000a000b 99 3-3', (self.controller / 'status').read_text())
        self.assertIsNone(self.control._load()['owned_port'])
        log = (self.run / 'usb-owner.jsonl').read_text()
        self.assertIn('detach_written', log)
        self.assertNotIn('k' * 48, log)

    def test_explicit_reconnect_after_virtual_port_is_released(self):
        self.modules()
        with patch.object(self.control, '_write_sysfs', side_effect=self.write_fake_sysfs):
            first = self.control.connect()
            self.assertTrue(first['host_enumerated'], first)
            original_pid = self.control._load()['server_pid']
            os.close(self.retained_socket)
            self.retained_socket = None
            self.set_rows()
            second = self.control.connect()
            self.assertTrue(second['host_enumerated'], second)
            self.assertNotEqual(original_pid, self.control._load()['server_pid'])
            self.assertEqual(self.control.disconnect()['phase'], 'disconnected')
        self.assertEqual([item[1] for item in self.writes], ['attach', 'attach', 'detach'])
        self.assertFalse(second['authentication_verified'])

    def test_jiritsu_refuses_physical_sysfs_and_other_vhci_device(self):
        self.modules()
        with patch.object(self.control, '_write_sysfs', side_effect=self.write_fake_sysfs):
            state = self.control.connect()
            self.assertTrue(state['host_enumerated'], state)
            physical = self.sysfs / 'devices/pci0000:00/usb1/1-4'
            physical.mkdir(parents=True)
            with self.assertRaises(control.ControlBlocked) as caught:
                self.control.jiritsu_target(physical)
            self.assertEqual(caught.exception.code, 'physical_usb_refused')
            row = self.control._owned_row(self.control._load()['owned_port'])[1]
            with self.assertRaises(control.ControlBlocked):
                self.control._virtual_target(physical, self.control._load()['owned_port'], row, DEVICE_BYTES)
            self.control.disconnect()

    def test_changed_owner_port_never_detached(self):
        self.modules()
        record = self.control._new_owner()
        record['owned_port'] = {'controller': str(self.controller), 'port': 2, 'devid': 0x11112222,
                                'speed': 3, 'sockfd': 10, 'local_busid': None, 'socket_inode': 123,
                                'client_address': ['127.0.0.1', 12345], 'server_address': ['127.0.0.1', 12346]}
        self.control._save(record)
        with patch.object(self.control, '_write_sysfs') as writer:
            state = self.control.disconnect()
            writer.assert_not_called()
        self.assertEqual(state['blocked_reason']['code'], 'port_owner_mismatch')
        self.assertIsNotNone(self.control._load()['owned_port'])

    def test_recovery_required_blocks_detach_and_checks_neutral_readback(self):
        self.modules()
        with patch.object(self.control, '_write_sysfs', side_effect=self.write_fake_sysfs):
            state = self.control.connect()
            self.assertTrue(state['host_enumerated'], state)
            self.control.mark_recovery_required('actual consumer reported PreloadRecoveryRequired')
            result = self.control.disconnect()
            self.assertEqual(result['phase'], 'recovery_required')
            self.assertEqual([item[1] for item in self.writes], ['attach'])
            with self.assertRaises(control.ControlBlocked):
                self.control.record_preload_recovery(b'not read back')
            self.control.record_preload_recovery(b' ' * 512)
            self.assertEqual(self.control.disconnect()['phase'], 'disconnected')

    def test_malformed_owner_cannot_request_host_action(self):
        record = self.control._new_owner()
        record['owned_port'] = {'port': 0}
        self.control._save(record)
        with patch.object(self.control, '_write_sysfs') as write:
            result = self.control.disconnect()
            write.assert_not_called()
        self.assertEqual(result['blocked_reason']['code'], 'invalid_owner_file')
        self.control.owner_file.unlink()

    def test_lease_mismatch_and_symlink_state_refused(self):
        record = self.control._new_owner()
        record['lease_id'] = 'wrong'
        self.control._save(record)
        self.assertEqual(self.control.status()['blocked_reason']['code'], 'lease_mismatch')
        self.control.owner_file.unlink()
        target = self.run / 'another.json'
        target.write_text('{}')
        self.control.owner_file.symlink_to(target)
        self.assertEqual(self.control.status()['phase'], 'blocked')

    def test_cli_check_and_vhci_parser(self):
        argv = ['--run-dir', str(self.run), '--qmp', str(self.run / 'qmp.sock'), '--lease', 'k' * 48,
                '--vm-pid', str(os.getpid()), '--check', 'connect']
        output = io.StringIO()
        with patch('sys.stdout', output):
            code = control.main(argv)
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result['blocked_reason']['code'], 'check_is_read_only')
        schema = json.loads((Path(__file__).parent / 'usb-gadget/control-schema.json').read_text())
        self.assertEqual(set(result), set(schema['required']))
        self.assertFalse(result['host_enumerated'])
        self.assertFalse(result['authentication_verified'])
        self.assertFalse(result['guest_root_verified'])
        for raw in ('garbage', self.header + 'hs not-a-port 4 0 0 0 0-0',
                    self.header + 'hs 0 4 0 0 0 0-0\nhs 0 4 0 0 0 0-0'):
            with self.assertRaises(control.ControlBlocked):
                control.vhci_rows(raw)


if __name__ == '__main__':
    unittest.main()
