"""Synthetic host/state/protocol checks; no real USB, VHCI, QMP or VM.

The original memory-only cases forbid sockets. Additional loopback cases use
private synthetic endpoint peers and fake sysfs with actual parser callbacks.
Fake TCP objects below only feed the existing USB/IP management parser; the
regular-file FD stands for a caller-owned FD in a fake sysfs write. It is never
passed to a host driver. Endpoint frames use the real encode/read_frame parser.
"""
import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import usb_control as c
import usb_jiritsu as j


def device(pid=0x0e8a, endpoint=1):
    raw = bytearray.fromhex('12010002000000404c058a0e000101020301')
    raw[10:12] = pid.to_bytes(2, 'little')
    config = (struct.pack('<BBHBBBBB', 9, 2, 32, 1, 1, 0, 0x80, 50) +
              bytes((9, 4, 0, 0, 2, 0xff, 0, 0, 0)) +
              struct.pack('<BBBBHB', 7, 5, endpoint, 2, 512, 0) +
              struct.pack('<BBBBHB', 7, 5, 0x80 | endpoint, 2, 512, 0))
    return c.usbip.GuestDevice.parse({'busid': 'dwc3-1', 'busnum': 1, 'devnum': 1,
                                     'speed': 3, 'configuration_value': 1,
                                     'descriptor_source': 'guest-ep0'}, bytes(raw) + config)


class MemoryTcp:
    def __init__(self, root, data):
        self.file = tempfile.TemporaryFile(dir=root)
        self.data = io.BytesIO(data)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.file.close()

    def fileno(self):
        return self.file.fileno()

    def recv(self, size):
        return self.data.read(size)

    def sendall(self, data):
        self.sent.append(data)

    def getsockname(self):
        return ('127.0.0.1', 43210)

    def getpeername(self):
        return ('127.0.0.1', 43211)


class HostFixture(c.UsbControl):
    def __init__(self, root):
        run = root / 'run-owned'
        run.mkdir(mode=0o700)
        super().__init__(run, qmp_path=run / 'qmp.sock', lease='k' * 48,
                         vm_pid=os.getpid(), sysfs_root=root / 'sys')
        self.root = root
        self.controller = self.sysfs / 'devices/platform/vhci_hcd.0'
        self.controller.mkdir(parents=True)
        for name in ('vhci_hcd', 'usbip_core'):
            (self.sysfs / 'module' / name).mkdir(parents=True)
        for name in ('attach', 'detach'):
            (self.controller / name).write_text('')
        self.alias = self.sysfs / 'bus/usb/devices/7-1'
        self.alias.parent.mkdir(parents=True)
        self.path = self.controller / 'usb7/7-1'
        self.path.mkdir(parents=True)
        self.alias.symlink_to(self.path)
        self.backend_device = device()
        self.socket_alive = True
        self.writes = []
        self.vm_error = None
        self.enumerate = True
        self.free_rows()
        record = self._new_owner()
        record.update(cable_connected=True, server_pid=54321, server_start='42', server_port=43211)
        self._save(record)

    def _check_vm(self):
        if self.vm_error:
            raise self.vm_error

    async def _backend(self, operation='describe', present=None):
        if operation != 'describe':
            raise AssertionError('generation transition must not toggle VBUS/reset')
        return self.backend_device

    def _server_alive(self, record):
        return record.get('server_pid') == 54321 and record.get('server_start') == '42'

    def _owns_socket(self, owned):
        return self.socket_alive

    def free_rows(self):
        (self.controller / 'status').write_text(
            'hub port sta spd dev sockfd local_busid\n'
            'hs 0 4 0 00000000 0 0-0\nhs 1 6 3 000a000b 99 8-8\n')

    def _write_sysfs(self, controller, attribute, text):
        self.writes.append((controller, attribute, text))
        if attribute != 'attach':
            raise AssertionError('reenumeration may only attach after original release')
        port, fd, devid, speed = map(int, text.split())
        if controller != self.controller or port != 0:
            raise AssertionError('reserved controller/port must stay fixed')
        os.fstat(fd)  # Actual caller-owned FD, never an integer sent to sudo.
        row = f'hs 0 {6 if self.enumerate else 5} {speed} {devid:08x} {fd} {"7-1" if self.enumerate else "0-0"}\n'
        (controller / 'status').write_text('hub port sta spd dev sockfd local_busid\n' + row +
                                          'hs 1 6 3 000a000b 99 8-8\n')
        raw = self.backend_device.descriptors
        for name, value in {'busnum': '7', 'devnum': str(len(self.writes) + 1),
                            'idVendor': '054c', 'idProduct': f'{int.from_bytes(raw[10:12], "little"):04x}'}.items():
            (self.path / name).write_text(value)
        (self.path / 'descriptors').write_bytes(raw)
        self.socket_alive = True
        self.receipt('active')

    def attach_initial(self):
        self.attach_fake(self._load(), self.backend_device, initial=True)
        self.receipt('active')

    def attach_fake(self, record, dev, initial=False):
        raw = c.usbip.COMMON.pack(c.usbip.VERSION, c.usbip.IMPORT & 0x7fff, 0) + dev.wire(self.context.run_id)
        with patch.object(c.socket, 'create_connection', return_value=MemoryTcp(self.root, raw)), \
                patch.object(self, '_free_port', side_effect=AssertionError('no arbitrary free port')):
            self._attach(record, dev, reserved=(self.controller, 0))

    def receipt(self, state, **changes):
        record = self._load()
        result = {key: record[key] for key in ('run_id', 'lease_id', 'owner_id', 'vm_pid', 'vm_start',
                                               'qmp_path', 'backend_path', 'server_pid', 'server_start',
                                               'attachment_id', 'device_key')}
        result.update({key: record['owned_port'][key] for key in ('client_address', 'server_address', 'socket_inode')})
        result.update(state=state, safe_to_rebind=state == 'retired',
                      release='generation_event_and_eof', event_kind='device_changed', **changes)
        c.usbip.write_owned_json(self.context.run_dir / 'usb-import.json', result)
        return result

    def retire(self, pid=0x0336, endpoint=2):
        self.receipt('retired')
        self.free_rows()
        self.socket_alive = False
        self.backend_device = device(pid, endpoint)

    def fake_transition(self, capability, pids=(0x0336,), seconds=0.1):
        original_attach = self._attach
        def attach(record, dev, *, reserved):
            raw = c.usbip.COMMON.pack(c.usbip.VERSION, c.usbip.IMPORT & 0x7fff, 0) + dev.wire(self.context.run_id)
            with patch.object(c.socket, 'create_connection', return_value=MemoryTcp(self.root, raw)):
                return original_attach(record, dev, reserved=reserved)
        # asyncio.run normally creates a self-pipe socketpair. Drive these immediate
        # in-memory backend coroutines directly, so even that is unnecessary here.
        with patch.object(c.asyncio, 'run', side_effect=immediate), \
                patch.object(self, '_attach', side_effect=attach), \
                patch.object(self, '_free_port', side_effect=AssertionError('arbitrary port selected')):
            return self._reenumerate(capability, pids, seconds=seconds)


def immediate(coro):
    try:
        value = coro.send(None)
    except StopIteration as stop:
        return stop.value
    finally:
        coro.close()
    raise AssertionError(f'in-memory operation unexpectedly suspended: {value!r}')


class NoNetwork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='synthetic-')
        self.addCleanup(self.tmp.cleanup)
        for name in ('socket', 'create_connection', 'socketpair'):
            block = patch.object(c.socket, name, side_effect=AssertionError('real socket operation forbidden'))
            block.start()
            self.addCleanup(block.stop)
        self.fast_async = patch.object(c.asyncio, 'run', side_effect=immediate)
        self.fast_async.start()
        self.addCleanup(self.fast_async.stop)


class GenerationTests(NoNetwork):
    def setUp(self):
        super().setUp()
        self.host = HostFixture(Path(self.tmp.name))
        self.host.attach_initial()

    def assert_blocked(self, code, call):
        with self.assertRaises(c.ControlBlocked) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_positive_old_guard_remains_invalid_fresh_endpoints_same_owner_port(self):
        old = j.TargetGuard(self.host)
        old_record = self.host._load()
        self.host.retire()
        self.host.fake_transition(old.capability)
        new = j.TargetGuard(self.host)
        self.assertEqual(old.pin, new.pin)
        self.assertNotEqual(old.generation, new.generation)
        self.assertEqual(old_record['owner_id'], self.host._load()['owner_id'])
        self.assertEqual(self.host._load()['previous_import']['owned_port'], old_record['owned_port'])
        self.assertEqual(self.host._load()['device_key'], self.host._device_key(device(0x0336, 2)))
        self.assertEqual(self.host.backend_device.endpoints, frozenset(((0, 2), (1, 2))))
        self.assertEqual(new.current()['product_id'], 0x0336)
        self.assert_blocked('target_generation_changed', old.current)
        self.assertTrue(all(item[0] == self.host.controller and item[2].split()[0] == '0' for item in self.host.writes))
        self.assertFalse(self.host.status()['authentication_verified'])
        self.assertFalse(self.host.status()['guest_root_verified'])

    def test_owner_lease_run_vm_and_same_uid_different_run_rejected(self):
        cap = self.host._generation_capability()
        original = self.host._load()
        for key in ('owner_id', 'lease_id', 'run_id', 'vm_start', 'server_start', 'attachment_id', 'device_key'):
            with self.subTest(key=key):
                altered = copy.deepcopy(original)
                altered[key] = ('a' * len(altered[key])) if key in ('attachment_id', 'device_key') else 'different'
                self.host._save(altered)
                with self.assertRaises((c.ControlBlocked, c.usbip.Blocked)):
                    self.host.fake_transition(cap)
                self.assertEqual(len(self.host.writes), 1)
        self.host._save(original)
        root = Path(self.tmp.name) / 'same-uid-another-run'
        root.mkdir()
        foreign = HostFixture(root)
        foreign.attach_initial()
        self.assert_blocked('generation_owner_changed', lambda: foreign.fake_transition(cap))

    def test_qmp_peer_failure_cannot_be_swallowed_during_transition(self):
        cap = self.host._generation_capability()
        self.host.retire()
        self.host.vm_error = c.ControlBlocked('qmp_owner_mismatch', 'different peer PID')
        self.assert_blocked('qmp_owner_mismatch', lambda: self.host.fake_transition(cap))
        self.assertEqual(len(self.host.writes), 1)

    def test_wrong_descriptor_and_invalid_endpoint_do_not_replace_old_record(self):
        cap = self.host._generation_capability()
        self.host.retire(pid=0x0e8a)
        old = self.host._load()
        self.assert_blocked('unexpected_generation_identity', lambda: self.host.fake_transition(cap))
        self.assertEqual(self.host._load(), old)
        bad = bytearray(device(0x0336).descriptors)
        bad[-4] = 1  # isochronous endpoint not supported by this profile
        self.host.backend_device = c.usbip.GuestDevice.parse(device(0x0336).metadata, bytes(bad))
        self.assert_blocked('invalid_endpoint', lambda: self.host.fake_transition(cap))
        self.assertEqual(self.host._load(), old)

    def test_foreign_port_occupied_is_never_detached_or_relocated(self):
        cap = self.host._generation_capability()
        self.host.retire()
        foreign_fd = os.open(self.host.owner_file, os.O_RDONLY)
        try:
            self.host._write_sysfs(self.host.controller, 'attach', f'0 {foreign_fd} 65537 3\n')
        finally:
            os.close(foreign_fd)
        # This row is foreign even if its device ID matches; sockfd must match too.
        row_text = (self.host.controller / 'status').read_text().replace('7-1', '9-9')
        (self.host.controller / 'status').write_text(row_text)
        self.assert_blocked('port_owner_mismatch', lambda: self.host.fake_transition(cap))
        self.assertEqual(len(self.host.writes), 2)

    def test_cancel_failed_receipt_and_late_completion_keep_old_owner(self):
        cap = self.host._generation_capability()
        for detail in ('cancel returned -5', 'late completion after generation boundary'):
            with self.subTest(detail=detail):
                self.host.receipt('failed', detail=detail)
                before = self.host._load()
                self.assert_blocked('import_retirement_failed', lambda: self.host.fake_transition(cap))
                self.assertEqual(self.host._load(), before)
                self.assertEqual(len(self.host.writes), 1)

    def test_tcp_inode_loss_without_retirement_is_fatal(self):
        cap = self.host._generation_capability()
        self.host.socket_alive = False
        self.assert_blocked('socket_owner_mismatch', lambda: self.host.fake_transition(cap))
        self.assertEqual(len(self.host.writes), 1)

    def test_receipt_with_wrong_socket_or_run_is_rejected(self):
        cap = self.host._generation_capability()
        for key in ('socket_inode', 'server_address', 'owner_id', 'lease_id', 'server_pid'):
            with self.subTest(key=key):
                receipt = self.host.receipt('retired')
                receipt[key] = 1 if isinstance(receipt[key], int) else 'foreign'
                c.usbip.write_owned_json(self.host.context.run_dir / 'usb-import.json', receipt)
                self.assert_blocked('import_owner_mismatch', lambda: self.host.fake_transition(cap))

    def test_timeout_keeps_record_and_never_calls_attach(self):
        cap = self.host._generation_capability()
        before = self.host._load()
        self.assert_blocked('reenumeration_timeout', lambda: self.host.fake_transition(cap, seconds=0.001))
        self.assertEqual(self.host._load(), before)
        self.assertEqual(len(self.host.writes), 1)

    def test_pending_new_sysfs_does_not_report_enumeration(self):
        cap = self.host._generation_capability()
        self.host.retire()
        self.host.enumerate = False
        self.assert_blocked('reenumeration_timeout', lambda: self.host.fake_transition(cap, seconds=0.001))
        self.assertFalse(self.host.status()['host_enumerated'])
        self.assertIsNotNone(self.host._load()['owned_port'])

    def test_preload_latch_refuses_public_actions_and_requires_prearmed_capability(self):
        old = j.TargetGuard(self.host)
        self.host.mark_recovery_required('synthetic deployment starts')
        for action in (self.host.connect, self.host.disconnect):
            result = action()
            self.assertEqual(result['blocked_reason']['code'], 'preload_recovery_required')
        self.assert_blocked('preload_recovery_required', lambda: self.host.fake_transition(old.capability))
        old._arm_recovery()
        self.host.retire()
        state = self.host.fake_transition(old.capability)
        self.assertTrue(state['preload_recovery_required'])
        self.assertEqual(state['phase'], 'recovery_required')
        new = j.TargetGuard(self.host, recovery=True)
        self.assertEqual(new.current()['product_id'], 0x0336)
        self.assertTrue(self.host._load()['preload_recovery_required'])
        self.assert_blocked('preload_recovery_required', lambda: self.host.record_preload_recovery(b' ' * 511))
        self.host.record_preload_recovery(b' ' * 512)
        self.assertFalse(self.host._load()['preload_recovery_required'])

    def test_old_guard_rejects_rebind_even_with_reused_bus_and_address(self):
        guard = j.TargetGuard(self.host)
        self.host.retire()
        self.host.fake_transition(guard.capability)
        self.assert_blocked('target_generation_changed', guard.current)

    def test_final_identity_is_independent_readback_not_stop_return(self):
        guard = j.TargetGuard(self.host)
        self.host.retire(pid=0x096f)
        original = self.host._reenumerate
        def transition(cap, pids, **_):
            with patch.object(self.host, '_reenumerate', original):
                return self.host.fake_transition(cap, pids)
        with patch.object(self.host, '_reenumerate', side_effect=transition):
            result = guard.final_identity()
        self.assertTrue(result['verified'])
        self.assertEqual(result['target']['product_id'], 0x096f)
        self.assertEqual(result['source'], 'owned-host-sysfs-readback')

    def test_consumer_follow_reopens_only_the_verified_new_generation(self):
        old = j.TargetGuard(self.host)
        self.host.retire()
        original = self.host._reenumerate
        def transition(cap, pids, **_):
            with patch.object(self.host, '_reenumerate', original):
                return self.host.fake_transition(cap, pids)
        service = SimpleNamespace(bus=7, address=3, port_numbers=(1,), idVendor=0x054c, idProduct=0x0336)
        foreign = SimpleNamespace(bus=1, address=3, port_numbers=(1,), idVendor=0x054c, idProduct=0x0336)
        finder = Mock(return_value=[foreign, service])
        with patch.object(self.host, '_reenumerate', side_effect=transition):
            fresh, actual = old.follow_generation(finder)
        self.assertIs(actual, service)
        self.assertEqual(fresh.current()['product_id'], 0x0336)
        self.assert_blocked('target_generation_changed', lambda: old.check_device(service))
        self.assert_blocked('foreign_usb_device', lambda: fresh.check_device(foreign))

    def test_stop_without_readback_records_independent_failure(self):
        guard = Mock()
        guard.final_identity.side_effect = c.ControlBlocked('reenumeration_timeout', 'no sysfs readback')
        events = []
        auth = Mock()
        pending = j.end_session(self.host, guard, auth, object(), Mock(),
                                lambda event, **fields: events.append({'event': event, **fields}))
        self.assertFalse(pending)
        auth.stop.assert_called_once()
        result = next(event for event in events if event['event'] == 'stop_identity_result')
        self.assertFalse(result['verified'])
        self.assertEqual(result['code'], 'reenumeration_timeout')

    def test_stop_is_never_attempted_with_pending_preload(self):
        self.host.mark_recovery_required('synthetic preload')
        auth = Mock()
        pending = j.end_session(self.host, Mock(), auth, object(), Mock(), lambda *a, **k: None)
        self.assertTrue(pending)
        auth.stop.assert_not_called()

    def test_status_matches_complete_configuration_not_only_vid_pid(self):
        raw = bytearray(self.host.backend_device.descriptors)
        raw[-3] ^= 1
        (self.host.path / 'descriptors').write_bytes(raw)
        result = self.host.status()
        self.assertEqual(result['blocked_reason']['code'], 'target_identity_mismatch')
        self.assertFalse(result['host_enumerated'])

    def test_actual_qmp_peer_parser_rejects_same_uid_other_pid(self):
        peer = Mock()
        peer.__enter__ = Mock(return_value=peer)
        peer.__exit__ = Mock(return_value=False)
        peer.getsockopt.return_value = struct.pack('3i', os.getpid() + 1, os.getuid(), os.getgid())
        with patch.object(c.usbip, 'check_unix'), patch.object(c.usbip, 'unix_path') as unix_path, \
                patch.object(c.socket, 'socket', return_value=peer):
            unix_path.return_value.__enter__.return_value = 'in-memory-peer'
            self.assert_blocked('qmp_owner_mismatch', lambda: c.UsbControl._check_vm(self.host))

    def test_server_pid_needs_exact_argv_not_embedded_source_names(self):
        record = self.host._load()
        ctx = self.host.context
        argv = [c.sys.executable, '-B', str(c.CONTROL_SOURCE), '--serve-owned', '--run-dir', str(ctx.run_dir),
                '--qmp', str(ctx.qmp_path), '--backend', str(ctx.backend_path), '--lease', ctx.lease,
                '--vm-pid', str(ctx.vm_pid), '--run-id', ctx.run_id]
        with patch.object(c, 'process_start', return_value=record['server_start']):
            for command, expected in ((argv, True), ([c.sys.executable, '-c', 'pass'] + argv[2:], False),
                                      (argv + ['--surprise'], False)):
                with patch.object(c.Path, 'read_bytes', return_value=b'\0'.join(arg.encode() for arg in command) + b'\0'):
                    self.assertEqual(c.UsbControl._server_alive(self.host, record), expected)

    def test_failed_retirement_blocks_disconnect_and_stop_before_resource_changes(self):
        self.host.receipt('failed', detail='old cancellation failed')
        with patch.object(c.os, 'kill', side_effect=AssertionError('failed owner cannot be signalled')):
            result = self.host.disconnect()
            self.assertEqual(result['blocked_reason']['code'], 'import_retirement_failed')
            self.assert_blocked('import_retirement_failed', lambda: self.host._stop_server(self.host._load()))
        self.assertEqual(len(self.host.writes), 1)
        self.assertIsNotNone(self.host._load()['owned_port'])

    def test_preload_also_blocks_private_server_stop(self):
        self.host.mark_recovery_required('synthetic preload')
        with patch.object(c.os, 'kill', side_effect=AssertionError('pending preload cannot stop server')):
            self.assert_blocked('preload_recovery_required', lambda: self.host._stop_server(self.host._load()))

    def test_original_tcp_guard_rejects_changed_inode(self):
        owned = self.host._load()['owned_port']
        def address(pair):
            return f'{int.from_bytes(c.socket.inet_aton(pair[0]), "little"):08X}:{pair[1]:04X}'
        row = f'0: {address(owned["client_address"])} {address(owned["server_address"])} 01 0 0 0 0 0 '
        with patch.object(c.Path, 'open', return_value=io.StringIO(row + str(owned['socket_inode'] + 1) + '\n')):
            self.assertFalse(c.UsbControl._owns_socket(self.host, owned))
        with patch.object(c.Path, 'open', return_value=io.StringIO(row + str(owned['socket_inode']) + '\n')):
            self.assertTrue(c.UsbControl._owns_socket(self.host, owned))


class MemoryReader:
    def __init__(self, raw):
        self.raw = io.BytesIO(raw)

    async def readexactly(self, size):
        value = self.raw.read(size)
        if len(value) != size:
            raise asyncio.IncompleteReadError(value, size)
        return value


class MemoryWriter:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


class ProtocolTests(NoNetwork):
    def bridge(self, raw):
        fake_control = SimpleNamespace(context=SimpleNamespace(run_dir=Path(self.tmp.name)), _log=Mock())
        cls, _, holds, retained, _ = c._owned_server_types(fake_control)
        task = Mock()
        def create(coro):
            coro.close()
            return task
        with patch.object(c.asyncio, 'create_task', side_effect=create):
            bridge = cls(MemoryReader(raw), MemoryWriter())
        bridge.role = 'usbip'
        bridge.receipt = {'attachment_id': 'a' * 32, 'state': 'active', 'safe_to_rebind': False}
        retained['a' * 32] = bridge
        return bridge, retained

    def frame(self, op='event', **fields):
        return c.usbip.encode_frame({'version': 1, 'id': 1, 'op': op, 'ok': True,
                                    'kind': 'device_changed',
                                    'reason': 'guest controller cable generation changed', **fields})

    def read(self, bridge):
        async def no_schedule(awaitable, timeout=None):
            return await awaitable
        with patch.object(c.asyncio, 'wait_for', side_effect=no_schedule):
            immediate(bridge._read())

    def test_header_is_received_before_owner_lookup_and_wrong_tcp_peer_is_rejected(self):
        state = {'header_seen': False}
        context = SimpleNamespace(run_dir=Path(self.tmp.name))
        request = {'client_address': ['127.0.0.1', 1111], 'server_address': ['127.0.0.1', 2222]}
        def load():
            self.assertTrue(state['header_seen'])
            return {'server_pid': os.getpid(), 'import_request': request}
        fake_control = SimpleNamespace(context=context, _load=load, _server_alive=lambda record: True,
                                       _owns_socket=lambda request: True)
        _, server_cls, holds, _, _ = c._owned_server_types(fake_control)
        server = server_cls(context)
        class HeaderReader(MemoryReader):
            async def readexactly(self, size):
                data = await super().readexactly(size)
                state['header_seen'] = True
                return data
        writer = MemoryWriter()
        writer.get_extra_info = Mock(side_effect=lambda name: ('127.0.0.1', 9999))
        async def no_schedule(awaitable, timeout=None):
            return await awaitable
        with patch.object(c.asyncio, 'wait_for', side_effect=no_schedule):
            immediate(server.handle(HeaderReader(c.usbip.COMMON.pack(c.usbip.VERSION, c.usbip.IMPORT, 0)), writer))
        self.assertIn('not this owner', server.last_error)
        self.assertEqual(holds, {})
        self.assertTrue(writer.closed)

    def test_event_eof_retirement_includes_old_pending_ids(self):
        bridge, _ = self.bridge(self.frame())
        future = Mock()
        future.done.return_value = False
        bridge.requests[42] = (future, 'complete')
        self.read(bridge)
        self.assertEqual(bridge.receipt['state'], 'retired')
        self.assertEqual(bridge.receipt['pending_ids'], [42])
        self.assertTrue(bridge.receipt['safe_to_rebind'])
        future.set_exception.assert_called_once()

    def test_old_late_complete_fails_and_keeps_bridge_writer_and_requests(self):
        bridge, retained = self.bridge(self.frame() + self.frame('complete', status=0, actual_length=0))
        bridge.requests[42] = (Mock(), 'complete')
        self.read(bridge)
        self.assertEqual(bridge.receipt['state'], 'failed')
        self.assertFalse(bridge.receipt['safe_to_rebind'])
        self.assertFalse(bridge.writer.closed)
        self.assertIn(42, bridge.requests)
        self.assertIs(retained['a' * 32], bridge)

    def test_truncated_old_late_frame_is_not_eof(self):
        bridge, _ = self.bridge(self.frame() + b'partial')
        self.read(bridge)
        self.assertEqual(bridge.receipt['state'], 'failed')
        self.assertFalse(bridge.writer.closed)

    def test_transport_eof_without_generation_is_failure(self):
        bridge, _ = self.bridge(b'')
        self.read(bridge)
        self.assertEqual(bridge.receipt['state'], 'failed')
        self.assertFalse(bridge.receipt['safe_to_rebind'])

    def test_wrong_event_or_cancellation_inflight_never_releases(self):
        for raw, expected in ((self.frame(reason='unverified'), 'complete'),
                              (self.frame(), 'cancelled')):
            bridge, _ = self.bridge(raw)
            bridge.requests[42] = (Mock(), expected)
            self.read(bridge)
            self.assertEqual(bridge.receipt['state'], 'failed')
            self.assertFalse(bridge.writer.closed)

    def test_cancel_failure_is_sticky_preserves_errno_and_fds(self):
        bridge, _ = self.bridge(b'')
        async def failed(*args, **kwargs):
            raise OSError(5, 'cancel failure')
        bridge.ask = failed
        with self.assertRaises(OSError) as caught:
            immediate(bridge.cancel(42))
        self.assertEqual(caught.exception.errno, 5)
        self.assertEqual(bridge.receipt['errno'], 5)
        bridge.publish('retired', safe_to_rebind=True)
        self.assertEqual(bridge.receipt['state'], 'failed')
        self.assertFalse(bridge.receipt['safe_to_rebind'])
        self.assertFalse(bridge.writer.closed)

    def test_receipt_write_failure_does_not_replace_original_cancel_errno(self):
        bridge, _ = self.bridge(b'')
        async def failed(*args, **kwargs):
            raise OSError(5, 'original cancel failure')
        bridge.ask = failed
        original_publish = bridge.publish
        def publish(*args, **kwargs):
            with patch.object(c.usbip, 'write_owned_json', side_effect=OSError(28, 'receipt full')):
                return original_publish(*args, **kwargs)
        with patch.object(bridge, 'publish', side_effect=publish), self.assertRaises(OSError) as caught:
            immediate(bridge.cancel(42))
        self.assertEqual(caught.exception.errno, 5)
        self.assertEqual(caught.exception.__cause__.errno, 28)
        self.assertEqual(bridge.receipt['state'], 'failed')
        self.assertFalse(bridge.writer.closed)

    def test_failed_cancel_status_is_never_success(self):
        bridge, _ = self.bridge(b'')
        async def rejected(*args, **kwargs):
            return {'target': 42, 'status': -5}, b''
        bridge.ask = rejected
        with self.assertRaises(c.usbip.ProtocolError):
            immediate(bridge.cancel(42))
        self.assertEqual(bridge.receipt['state'], 'failed')

    def test_normal_generation_exception_does_not_reclassify_released_pending_urb_as_failure(self):
        bridge, _ = self.bridge(b'')
        bridge.event_seen = True
        bridge.error = c.usbip.Blocked('owned guest generation retired')
        bridge.receipt.update(state='retired', safe_to_rebind=True)
        fake_control = SimpleNamespace(context=SimpleNamespace(run_dir=Path(self.tmp.name)))
        *_, session_cls = c._owned_server_types(fake_control)
        session = session_cls(None, MemoryWriter(), bridge, device())
        error = bridge.error
        class Reply:
            def __await__(self):
                if False:
                    yield
                raise error
        entry = c.usbip.Pending((c.usbip.SUBMIT, 42, device().devid, 1, 1), 2, 1, Reply())
        session.pending[42] = entry
        session.reserved = 2
        async def no_schedule(awaitable, timeout=None):
            return await awaitable
        with patch.object(c.asyncio, 'wait_for', side_effect=no_schedule), \
                patch.object(c.asyncio, 'shield', side_effect=lambda value: value):
            immediate(session.complete(entry))
        self.assertIs(session.failure, bridge.error)
        self.assertEqual(bridge.receipt['state'], 'retired')
        self.assertTrue(bridge.receipt['safe_to_rebind'])

    def test_import_completion_validation_failure_latches_receipt(self):
        bridge, retained = self.bridge(b'')
        fake_control = SimpleNamespace(context=SimpleNamespace(run_dir=Path(self.tmp.name)))
        *_, session_cls = c._owned_server_types(fake_control)
        session = session_cls(None, MemoryWriter(), bridge, device())
        class Reply:
            def __await__(self):
                if False:
                    yield
                return {'status': -32, 'actual_length': 2}, b''  # IN length mismatch
        entry = c.usbip.Pending((c.usbip.SUBMIT, 42, device().devid, 1, 1), 2, 1, Reply())
        session.pending[42] = entry
        session.reserved = 2
        async def no_schedule(awaitable, timeout=None):
            return await awaitable
        with patch.object(c.asyncio, 'wait_for', side_effect=no_schedule), \
                patch.object(c.asyncio, 'shield', side_effect=lambda value: value):
            immediate(session.complete(entry))
        self.assertIsInstance(session.failure, c.usbip.ProtocolError)
        self.assertEqual(bridge.receipt['state'], 'failed')
        self.assertFalse(bridge.receipt['safe_to_rebind'])
        self.assertFalse(bridge.writer.closed)
        self.assertIn('a' * 32, retained)

    def test_original_completion_return_and_errno_are_unchanged(self):
        bridge, _ = self.bridge(self.frame('complete', status=-32, actual_length=0))
        future = Mock()
        future.done.return_value = False
        bridge.requests[1] = (future, 'complete')
        self.read(bridge)
        response, payload = future.set_result.call_args.args[0]
        self.assertEqual(response['status'], -32)
        self.assertEqual(payload, b'')
        # Subsequent EOF without generation remains independently unverified.
        self.assertEqual(bridge.receipt['state'], 'failed')


# These additional cases exercise the owned server through real synthetic sockets.
import importlib.util
import time
import sys
sys.path.insert(0, str(Path(__file__).parent / 'usb-gadget'))
from test_support import DESCRIPTORS, METADATA, SyntheticBackend


def control_fixture():
    spec = importlib.util.spec_from_file_location('loopback_control_fixture', Path(__file__).with_name('test-usb-control.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ControlTests('test_explicit_reconnect_after_virtual_port_is_released')


class LoopbackControlTests(unittest.TestCase):
    def test_empty_client_eof_disconnect_fresh_connect_and_original_guards(self):
        fixture = control_fixture()
        fixture.setUp()
        try:
            fixture.modules()
            with patch.object(fixture.control, '_write_sysfs', side_effect=fixture.write_fake_sysfs):
                first = fixture.control.connect()
                self.assertTrue(first['host_enumerated'], first)
                cap = fixture.control._generation_capability()
                os.close(fixture.retained_socket)
                fixture.retained_socket = None
                fixture.set_rows()
                deadline = time.monotonic() + 2
                while True:
                    receipt = fixture.control._import_receipt(fixture.control._load())
                    if receipt.get('state') == 'disconnected' or time.monotonic() > deadline:
                        break
                    time.sleep(0.01)
                self.assertTrue(c._import_disconnected(receipt), receipt)
                self.assertFalse(receipt['safe_to_rebind'])
                with self.assertRaises(c.ControlBlocked) as caught:
                    fixture.control._reenumerate(cap, (0x0336,), seconds=0.05)
                self.assertEqual(caught.exception.code, 'reenumeration_timeout')
                fixture.control.mark_recovery_required('synthetic latch test')
                self.assertEqual(fixture.control.disconnect()['phase'], 'recovery_required')
                with self.assertRaises(c.ControlBlocked):
                    fixture.control._stop_server(fixture.control._load())
                self.assertEqual(len(fixture.writes), 1)
                fixture.control.record_preload_recovery(b' ' * 512)
                fixture.set_rows({'speed': 3, 'devid': 0x11112222, 'sockfd': 999})
                blocked = fixture.control.disconnect()
                self.assertEqual(blocked['blocked_reason']['code'], 'port_owner_mismatch')
                self.assertEqual(len(fixture.writes), 1)
                fixture.set_rows()
                self.assertEqual(fixture.control.disconnect()['phase'], 'disconnected')
                second = fixture.control.connect()
                self.assertTrue(second['host_enumerated'], second)
                self.assertEqual(fixture.control.disconnect()['phase'], 'disconnected')
                self.assertEqual([row[1] for row in fixture.writes], ['attach', 'attach', 'detach'])
        finally:
            fixture.tearDown()


class SocketEofTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='owned-eof-synthetic-')
        self.addCleanup(self.tmp.cleanup)
        run = Path(self.tmp.name)
        self.context = c.usbip.Context.create(run, run / 'qmp.sock', run / 'backend.sock', 'k' * 48,
                                            os.getpid(), 'synthetic-eof')
        self.backend = await SyntheticBackend(self.context).start()
        dev = c.usbip.GuestDevice.parse(dict(METADATA), DESCRIPTORS)
        self.record = {'run_id': self.context.run_id, 'lease_id': self.context.lease_id,
                       'owner_id': 'b' * 32, 'vm_pid': os.getpid(), 'vm_start': c.process_start(os.getpid()),
                       'qmp_path': str(self.context.qmp_path), 'backend_path': str(self.context.backend_path),
                       'server_pid': os.getpid(), 'server_start': c.process_start(os.getpid())}
        control = SimpleNamespace(context=self.context, _load=lambda: self.record, _server_alive=lambda record: True,
                                  _owns_socket=c.UsbControl._owns_socket,
                                  _validate_device=c.UsbControl._validate_device, _device_key=c.UsbControl._device_key)
        # Metadata ownership is synthetic; TCP inode/tuples, peer checks, parser and callbacks are real.
        control._owns_socket = lambda request: c.UsbControl._owns_socket(control, request)
        bridge_cls, server_cls, self.holds, self.retained, session_cls = c._owned_server_types(control)
        self.original_bridge = c.usbip.Bridge
        self.bridge_patch = patch.object(c.usbip, 'Bridge', bridge_cls)
        self.session_patch = patch.object(c.usbip, 'ImportSession', session_cls)
        self.bridge_patch.start()
        self.session_patch.start()
        self.server = await server_cls(self.context).start()
        self.reader, self.writer = await asyncio.open_connection('127.0.0.1', self.server.port)
        sock = self.writer.get_extra_info('socket')
        self.record['import_request'] = {'attachment_id': 'a' * 32, 'device_key': c.UsbControl._device_key(dev),
                                         'client_address': list(sock.getsockname()),
                                         'server_address': list(sock.getpeername()),
                                         'socket_inode': os.fstat(sock.fileno()).st_ino}
        self.writer.write(c.usbip.COMMON.pack(c.usbip.VERSION, c.usbip.IMPORT, 0) + dev.busid.encode().ljust(32, b'\0'))
        await self.writer.drain()
        reply = await asyncio.wait_for(self.reader.readexactly(8 + c.usbip.DEVICE.size), 2)
        self.assertEqual(c.usbip.COMMON.unpack(reply[:8]), (c.usbip.VERSION, c.usbip.IMPORT & 0x7fff, 0))
        self.bridge = self.retained['a' * 32]
        self.release_cancel = asyncio.Event()

    async def asyncTearDown(self):
        self.release_cancel.set()
        self.writer.close()
        await self.writer.wait_closed()
        await self.server.close()
        # Dispose only these synthetic fixture transports after asserting the fail-shut receipt.
        for bridge in tuple(self.retained.values()):
            await self.original_bridge.close(bridge)
        for hold, _ in tuple(self.holds.values()):
            hold.close()
        await self.backend.close()
        self.session_patch.stop()
        self.bridge_patch.stop()

    async def wait_state(self, state):
        async def wait():
            while self.bridge.receipt.get('state') != state:
                await asyncio.sleep(0.005)
        await asyncio.wait_for(wait(), 2)
        receipt = json.loads((self.context.run_dir / 'usb-import.json').read_text())
        self.assertEqual(receipt['state'], state)
        return receipt

    async def eof(self):
        self.writer.close()
        await self.writer.wait_closed()

    async def submit(self, direction=1, length=8, payload=b''):
        basic = (c.usbip.SUBMIT, 42, 7 << 16 | 9, direction, 1)
        self.writer.write(c.usbip.BASIC.pack(*basic) +
                          c.usbip.SUBMIT_BODY.pack(0, length, 0, 0, 0, bytes(8)) + payload)
        await self.writer.drain()

    async def held_submit(self):
        self.backend.hold.add(42)
        await self.submit()
        return await asyncio.wait_for(self.backend.submitted.get(), 2)

    def assert_retained_failure(self):
        self.assertEqual(self.bridge.receipt['state'], 'failed')
        self.assertFalse(self.bridge.receipt['safe_to_rebind'])
        self.assertFalse(c._import_disconnected(self.bridge.receipt))
        self.assertFalse(self.bridge.closed)
        self.assertFalse(self.bridge.writer.is_closing())
        self.assertIn('a' * 32, self.retained)
        self.assertIn('a' * 32, self.holds)

    async def test_empty_eof_is_separate_disconnect_receipt(self):
        await self.eof()
        receipt = await self.wait_state('disconnected')
        self.assertTrue(c._import_disconnected(receipt))
        self.assertFalse(receipt['safe_to_rebind'])
        self.assertEqual(receipt['release'], 'client_eof_and_quiescent')
        self.assertEqual(self.bridge.requests, {})
        self.assertEqual(self.bridge.import_session.pending, {})

    async def test_preload_latch_at_client_eof_retains_transports(self):
        self.record['preload_recovery_required'] = True
        await self.eof()
        await self.wait_state('failed')
        self.assert_retained_failure()
        self.assertFalse(any(op == 'cancel' for op, _, _ in self.backend.events))

    async def test_completed_urb_then_eof_is_quiescent(self):
        await self.submit()
        raw = await asyncio.wait_for(self.reader.readexactly(48 + 8), 2)
        self.assertEqual(c.usbip.BASIC.unpack(raw[:20])[0], c.usbip.RET_SUBMIT)
        await self.eof()
        self.assertTrue(c._import_disconnected(await self.wait_state('disconnected')))

    async def test_known_pending_urb_requires_actual_cancel_ack(self):
        await self.held_submit()
        await self.eof()
        self.assertTrue(c._import_disconnected(await self.wait_state('disconnected')))
        self.assertEqual(self.backend.active, {})
        self.assertTrue(any(op == 'cancel' for op, _, _ in self.backend.events))

    async def test_partial_client_header_is_poison(self):
        self.writer.write(b'partial')
        await self.writer.drain()
        await self.eof()
        await self.wait_state('failed')
        self.assert_retained_failure()

    async def test_empty_eof_inside_48_byte_out_payload_is_poison(self):
        await self.submit(direction=0, length=48)
        await self.eof()
        await self.wait_state('failed')
        self.assertFalse(self.bridge.import_session.reader.clean_eof)
        self.assert_retained_failure()

    async def test_partial_out_payload_is_poison(self):
        await self.submit(direction=0, length=48, payload=b'half')
        await self.eof()
        await self.wait_state('failed')
        self.assert_retained_failure()

    async def test_invalid_client_command_is_poison(self):
        self.writer.write(c.usbip.BASIC.pack(99, 42, 7 << 16 | 9, 1, 1) + bytes(28))
        await self.writer.drain()
        await self.wait_state('failed')
        self.assert_retained_failure()

    async def test_bad_completion_before_eof_remains_poison(self):
        self.backend.replies[42] = {'actual_length': 8, 'data': b'x'}
        await self.submit()
        await self.wait_state('failed')
        self.assertIsInstance(self.bridge.import_session.failure, c.usbip.ProtocolError)
        self.assert_retained_failure()

    async def test_bad_completion_and_client_eof_same_turn_remain_poison(self):
        owner, request, _ = await self.held_submit()
        self.backend.replies[42] = {'actual_length': 8, 'data': b'x'}
        await self.backend.complete(owner, request['id'])
        await self.eof()
        await self.wait_state('failed')
        self.assert_retained_failure()

    async def test_failed_cancel_remains_poison(self):
        await self.held_submit()
        self.backend.cancel_status = -5
        await self.eof()
        receipt = await self.wait_state('failed')
        self.assertIn('cancelled URB', receipt['detail'])
        self.assert_retained_failure()

    async def test_inflight_cancel_at_eof_is_poison(self):
        _, request, _ = await self.held_submit()
        original_send = self.backend.send
        async def send(writer, header, payload=b''):
            if header['op'] == 'cancelled':
                await self.release_cancel.wait()
            await original_send(writer, header, payload)
        self.backend.send = send
        task = asyncio.create_task(self.bridge.cancel(request['id']))
        while not any(op == 'cancel' for op, _, _ in self.backend.events):
            await asyncio.sleep(0.005)
        await self.eof()
        await self.wait_state('failed')
        self.assert_retained_failure()
        self.release_cancel.set()
        await asyncio.wait_for(task, 2)
        self.assertEqual(self.bridge.receipt['state'], 'failed')

    async def test_late_complete_after_cancel_ack_is_poison(self):
        await self.held_submit()
        original_send = self.backend.send
        async def send(writer, header, payload=b''):
            await original_send(writer, header, payload)
            if header['op'] == 'cancelled':
                await original_send(writer, {'version': 1, 'op': 'complete', 'id': header['target'],
                                             'ok': True, 'status': 0, 'actual_length': 0})
        self.backend.send = send
        await self.eof()
        await self.wait_state('failed')
        self.assert_retained_failure()

    async def test_partial_backend_frame_after_cancel_ack_is_poison(self):
        await self.held_submit()
        original_send = self.backend.send
        async def send(writer, header, payload=b''):
            await original_send(writer, header, payload)
            if header['op'] == 'cancelled':
                writer.write(b'x')
                await writer.drain()
        self.backend.send = send
        await self.eof()
        await self.wait_state('failed')
        self.assertTrue(self.bridge.frame_started)
        self.assert_retained_failure()

    async def test_backend_eof_is_not_client_eof_release(self):
        await self.backend.drop_data()
        await self.wait_state('failed')
        self.assert_retained_failure()

    async def test_generation_event_followed_by_only_frame_prefix_is_poison(self):
        writer = next(iter(self.backend.data_writers))
        event = c.usbip.encode_frame({'version': 1, 'op': 'event', 'id': 1, 'ok': True,
                                     'kind': 'device_changed',
                                     'reason': 'guest controller cable generation changed'})
        writer.write(event + struct.pack('!II', 8, 0))
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        await self.wait_state('failed')
        self.assert_retained_failure()


if __name__ == '__main__':
    unittest.main()
