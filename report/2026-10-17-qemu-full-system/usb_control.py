#!/usr/bin/env python3
"""Own one VM's loopback USB/IP connection; never discover physical USB devices."""
import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import subprocess
import sys
import time
import uuid

CONTROL_SOURCE = Path(__file__).resolve()


class _GenerationCapability:
    def __init__(self, control, record, recovery):
        self.control = control
        self.record = json.loads(json.dumps(record))
        self.recovery = recovery


def _descriptor_offsets(raw):
    offset = 18
    while offset < len(raw):
        yield offset
        offset += raw[offset]


BRIDGE_SOURCE = Path(__file__).resolve().parent / 'usb-gadget' / 'usbip_server.py'
_SPEC = importlib.util.spec_from_file_location('a7c2_usbip_server', BRIDGE_SOURCE)
usbip = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = usbip
_SPEC.loader.exec_module(usbip)


class ControlBlocked(usbip.Blocked):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code


def read_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 16384:
            raise ControlBlocked('unsafe_owner_file', 'owner file must be owned, mode 0600 and bounded')
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ControlBlocked('unsafe_owner_file', 'owner file exceeds budget')
    try:
        result = json.loads(raw, object_pairs_hook=usbip._object)
    except (ValueError, UnicodeError) as error:
        raise ControlBlocked('invalid_owner_file', str(error)) from error
    if not isinstance(result, dict):
        raise ControlBlocked('invalid_owner_file', 'owner record is not an object')
    return result


def empty_status(run_id=None, lease_id=None):
    return {'schema': 'a7c2.usb-control.v1', 'run_id': run_id, 'lease_id': lease_id,
            'phase': 'disconnected', 'blocked_reason': None, 'backend_ready': False,
            'cable_connected': False, 'exported': False, 'host_enumerated': False,
            'authentication_verified': False, 'guest_root_verified': False,
            'preload_recovery_required': False, 'target': None, 'owned_port': None}


def process_start(pid):
    try:
        return Path('/proc', str(pid), 'stat').read_text().rpartition(')')[2].split()[19]
    except (OSError, IndexError):
        return None


def vhci_rows(text):
    lines = text.splitlines()
    if not lines or lines[0].split() != ['hub', 'port', 'sta', 'spd', 'dev', 'sockfd', 'local_busid']:
        raise ControlBlocked('vhci_status_format', 'unsupported VHCI status columns')
    if len(lines) > 257:
        raise ControlBlocked('vhci_status_format', 'too many VHCI ports')
    result = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 7 or fields[0] not in ('hs', 'ss'):
            raise ControlBlocked('vhci_status_format', 'invalid VHCI row')
        try:
            result.append({'hub': fields[0], 'port': int(fields[1], 10), 'status': int(fields[2], 10),
                           'speed': int(fields[3], 10), 'devid': int(fields[4], 16),
                           'sockfd': int(fields[5], 10), 'local_busid': fields[6]})
        except ValueError as error:
            raise ControlBlocked('vhci_status_format', str(error)) from error
    if len({row['port'] for row in result}) != len(result):
        raise ControlBlocked('vhci_status_format', 'duplicate VHCI port')
    return result


class UsbControl:
    def __init__(self, run_dir, *, qmp_path, lease, vm_pid, backend_path=None, run_id=None,
                 sysfs_root='/sys'):
        run = Path(run_dir)
        self.context = usbip.Context.create(run, qmp_path, backend_path or run / 'usb-endpoint.sock',
                                            lease, vm_pid, run_id)
        # Dependency injection for tests; the CLI never accepts an alternate host sysfs.
        self.sysfs = Path(sysfs_root).resolve()
        self.owner_file = self.context.run_dir / 'usb-owner.json'
        self.server_process = None

    def _base(self):
        return empty_status(self.context.run_id, self.context.lease_id)

    def _failure(self, result, error):
        result['phase'] = 'recovery_required' if result['preload_recovery_required'] else 'blocked'
        code = 'host_permission_denied' if isinstance(error, PermissionError) else 'backend_unavailable'
        result['blocked_reason'] = {'code': getattr(error, 'code', code), 'detail': str(error)}
        return result

    def _load(self):
        try:
            record = read_json(self.owner_file)
        except FileNotFoundError:
            return {}
        expected = {'run_id': self.context.run_id, 'lease_id': self.context.lease_id,
                    'qmp_path': str(self.context.qmp_path), 'vm_pid': self.context.vm_pid,
                    'backend_path': str(self.context.backend_path)}
        if any(record.get(k) != v for k, v in expected.items()):
            raise ControlBlocked('lease_mismatch', 'USB owner belongs to a different run/VM/lease')
        for name in ('cable_connected', 'preload_recovery_required'):
            if type(record.get(name)) is not bool:
                raise ControlBlocked('invalid_owner_file', 'owner flags must be booleans')
        current_start = process_start(self.context.vm_pid)
        if record.get('vm_start') and current_start and record['vm_start'] != current_start:
            raise ControlBlocked('vm_owner_changed', 'VM PID was reused; original USB ownership is retained')
        if record.get('attachment_id') is not None:
            for key in ('attachment_id', 'device_key'):
                value = record.get(key)
                if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}' if key == 'attachment_id' else r'[0-9a-f]{64}', value):
                    raise ControlBlocked('invalid_owner_file', 'invalid managed import binding')
        request = record.get('import_request')
        if request is not None:
            if (not isinstance(request, dict) or set(request) !=
                    {'attachment_id', 'device_key', 'client_address', 'server_address', 'socket_inode'}):
                raise ControlBlocked('invalid_owner_file', 'incomplete managed import request')
            for key, pattern in (('attachment_id', r'[0-9a-f]{32}'), ('device_key', r'[0-9a-f]{64}')):
                if not isinstance(request[key], str) or not re.fullmatch(pattern, request[key]):
                    raise ControlBlocked('invalid_owner_file', 'invalid managed import request identity')
            usbip.integer(request['socket_inode'], 1, 0xffffffffffffffff, 'import socket inode')
            for key in ('client_address', 'server_address'):
                address = request[key]
                if (not isinstance(address, list) or len(address) != 2 or address[0] != '127.0.0.1' or
                        type(address[1]) is not int or not 1 <= address[1] <= 65535):
                    raise ControlBlocked('invalid_owner_file', 'import socket must be IPv4 loopback')
        owned = record.get('owned_port')
        if owned is not None:
            required = {'controller', 'port', 'devid', 'speed', 'sockfd', 'socket_inode',
                        'local_busid', 'client_address', 'server_address'}
            if not isinstance(owned, dict) or not required <= owned.keys() or not isinstance(owned['controller'], str):
                raise ControlBlocked('invalid_owner_file', 'incomplete virtual port ownership record')
            for name in ('port', 'devid', 'speed', 'sockfd', 'socket_inode'):
                usbip.integer(owned[name], 0, 0xffffffffffffffff, 'owned ' + name)
            for name in ('client_address', 'server_address'):
                address = owned[name]
                if (not isinstance(address, list) or len(address) != 2 or address[0] != '127.0.0.1' or
                        type(address[1]) is not int or not 1 <= address[1] <= 65535):
                    raise ControlBlocked('invalid_owner_file', 'owner socket must be IPv4 loopback')
        return record

    def _save(self, record):
        usbip.write_owned_json(self.owner_file, record)

    def _log(self, event, **fields):
        path = self.context.run_dir / 'usb-owner.jsonl'
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as output:
            info = os.fstat(output.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ControlBlocked('unsafe_owner_log', 'refusing unsafe owner log')
            output.write(json.dumps({'time': time.time(), 'event': event, 'run_id': self.context.run_id,
                                     'lease_id': self.context.lease_id, **fields}, allow_nan=False) + '\n')

    @contextmanager
    def _lock(self):
        path = self.context.run_dir / 'usb-control.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ControlBlocked('unsafe_lock', 'refusing unsafe control lock')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ControlBlocked('control_busy', 'another USB action owns this run') from error
            yield
        finally:
            os.close(fd)

    def _check_vm(self):
        usbip.check_unix(self.context.qmp_path, private=False)
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(2)
            with usbip.unix_path(self.context.qmp_path, private=False) as path:
                peer.connect(path)
            pid, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if pid != self.context.vm_pid or uid != os.getuid():
                raise ControlBlocked('qmp_owner_mismatch', 'QMP peer is not the bound VM PID/UID')
            with peer.makefile('rwb', buffering=0) as stream:
                def receive(expected=None):
                    for _ in range(32):
                        line = stream.readline(16385)
                        if not line or len(line) > 16384 or not line.endswith(b'\n'):
                            raise ControlBlocked('qmp_protocol', 'invalid/bounded QMP response')
                        response = json.loads(line)
                        if expected is None or response.get('id') == expected:
                            return response
                    raise ControlBlocked('qmp_protocol', 'too many unrelated QMP events')
                if 'QMP' not in receive():
                    raise ControlBlocked('qmp_protocol', 'missing QMP greeting')
                for command, request in (('qmp_capabilities', 1), ('query-status', 2)):
                    stream.write((json.dumps({'execute': command, 'id': request}) + '\n').encode())
                    response = receive(request)
                    if 'return' not in response:
                        raise ControlBlocked('qmp_protocol', 'QMP did not accept read-only status query')
                if response['return'].get('status') in ('shutdown', 'internal-error', 'guest-panicked'):
                    raise ControlBlocked('vm_not_running', 'bound VM cannot provide USB')

    async def _backend(self, operation='describe', present=None):
        bridge = await usbip.Bridge.open(self.context, 'control')
        try:
            if operation == 'vbus':
                response, payload = await bridge.ask('vbus', present=present)
                if payload or response.get('present') is not present:
                    raise usbip.ProtocolError('VBUS transition was not acknowledged')
                return None
            if operation == 'hello':
                return None
            return await bridge.describe()
        finally:
            await bridge.close()

    def _controllers(self):
        if not (self.sysfs / 'module/vhci_hcd').is_dir() or not (self.sysfs / 'module/usbip_core').is_dir():
            raise ControlBlocked('vhci_module_not_loaded', 'vhci_hcd/usbip_core are not loaded; no module load was attempted')
        platform = self.sysfs / 'devices/platform'
        controllers = sorted(platform.glob('vhci_hcd.*'))
        if not controllers:
            raise ControlBlocked('vhci_controller_missing', 'no virtual VHCI controller is available')
        for controller in controllers:
            if (controller.is_symlink() or controller.resolve().parent != platform.resolve() or
                    not re.fullmatch(r'vhci_hcd\.[0-9]+', controller.name)):
                raise ControlBlocked('unsafe_vhci_path', 'VHCI controller path is not explicit virtual sysfs')
        return controllers

    def _rows(self, controller):
        path = controller / 'status'
        with path.open() as source:
            text = source.read(65537)
        if len(text) > 65536:
            raise ControlBlocked('vhci_status_format', 'VHCI status budget exceeded')
        return vhci_rows(text)

    def _free_port(self, speed):
        saw_denied = False
        for controller in self._controllers():
            if not os.access(controller / 'attach', os.W_OK) or not os.access(controller / 'detach', os.W_OK):
                saw_denied = True
                continue
            for row in self._rows(controller):
                if row['status'] == 4 and row['hub'] == ('ss' if speed >= 5 else 'hs'):
                    return controller, row
        code = 'vhci_permission_denied' if saw_denied else 'vhci_no_free_port'
        raise ControlBlocked(code, 'explicit attach needs a writable, free virtual VHCI port; no privilege helper was invoked')

    def _owned_row(self, owned):
        controller = Path(owned['controller'])
        if controller not in self._controllers():
            raise ControlBlocked('port_owner_mismatch', 'recorded controller is not the current explicit VHCI controller')
        for row in self._rows(controller):
            if row['port'] == owned['port']:
                if row['status'] == 4:
                    return controller, None
                if any(row[k] != owned[k] for k in ('devid', 'speed', 'sockfd')) or row['status'] not in (5, 6, 7):
                    raise ControlBlocked('port_owner_mismatch', 'VHCI port identity changed; refusing to detach')
                if owned.get('local_busid') and row['local_busid'] != owned['local_busid']:
                    raise ControlBlocked('port_owner_mismatch', 'VHCI local busid changed; refusing to detach')
                return controller, row
        raise ControlBlocked('port_owner_mismatch', 'recorded VHCI port disappeared')

    def _virtual_target(self, usb_syspath, owned, row, descriptor):
        path = Path(usb_syspath).resolve(strict=True)
        controller = Path(owned['controller']).resolve(strict=True)
        try:
            path.relative_to(controller)
        except ValueError as error:
            raise ControlBlocked('physical_usb_refused', 'target has no owned VHCI sysfs ancestor') from error
        if path.name != row['local_busid'] or not re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*', path.name):
            raise ControlBlocked('target_owner_mismatch', 'target is not the exact owned VHCI port device')
        def number(name, base):
            raw = (path / name).read_text().strip()
            if len(raw) > 8:
                raise ControlBlocked('target_identity_mismatch', 'USB identity attribute exceeds budget')
            return int(raw, base)
        with (path / 'descriptors').open('rb') as source:
            actual = source.read(len(descriptor) + 1)
        if actual != descriptor:
            raise ControlBlocked('target_identity_mismatch', 'enumerated descriptors differ from guest backend')
        vendor, product = number('idVendor', 16), number('idProduct', 16)
        if vendor != int.from_bytes(descriptor[8:10], 'little') or product != int.from_bytes(descriptor[10:12], 'little'):
            raise ControlBlocked('target_identity_mismatch', 'enumerated VID/PID differ from guest descriptors')
        return {'sysfs_path': str(path), 'vhci_controller': str(controller), 'local_busid': path.name,
                'busnum': number('busnum', 10), 'devnum': number('devnum', 10),
                'vendor_id': vendor, 'product_id': product, 'virtual_ancestor_verified': True}

    def status(self):
        result = self._base()
        try:
            record = self._load()
            for name in ('cable_connected', 'preload_recovery_required', 'owned_port'):
                if name in record:
                    result[name] = record[name]
            self._check_vm()
            device = self._validate_device(asyncio.run(self._backend()))
            result['backend_ready'] = True
            result['device'] = {**device.metadata, 'descriptor_sha256': hashlib.sha256(device.descriptors).hexdigest()}
            if record.get('attachment_id'):
                self._import_receipt(record)
            if record.get('owned_port'):
                _, row = self._owned_row(record['owned_port'])
                if row is not None:
                    result['phase'] = 'attached'
                    result['exported'] = self._server_alive(record) and self._owns_socket(record['owned_port'])
                    if not result['exported']:
                        raise ControlBlocked('server_owner_lost', 'owned USB/IP server/socket is no longer alive')
                    if (record.get('descriptor_sha256') != hashlib.sha256(device.descriptors).hexdigest() or
                            (record.get('device_key') and record['device_key'] != self._device_key(device))):
                        raise ControlBlocked('guest_device_changed', 'guest descriptors changed; owner must reconnect')
                    if row['status'] == 6 and row['local_busid'] != '0-0':
                        path = self.sysfs / 'bus/usb/devices' / row['local_busid']
                        result['target'] = self._virtual_target(path, record['owned_port'], row, device.descriptors)
                        result['host_enumerated'] = True
                        result['phase'] = 'enumerated'
            else:
                self._free_port(device.metadata['speed'])
            if result['preload_recovery_required']:
                return self._failure(result, ControlBlocked('preload_recovery_required', 'recover guest preload before disconnect'))
            return result
        except (usbip.Blocked, usbip.ProtocolError, OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as error:
            return self._failure(result, error)

    check = status

    @staticmethod
    def _device_key(device):
        raw = json.dumps(device.metadata, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        return hashlib.sha256(raw + b'\0' + device.descriptors).hexdigest()

    @staticmethod
    def _validate_device(device):
        # Match the USB2 bulk/interrupt contract of the bound guest bridge.
        device = usbip.GuestDevice.parse(device.metadata, device.descriptors)
        if device.descriptors[17] != 1:
            raise ControlBlocked('unsupported_configuration', 'only the discovered complete single configuration is supported')
        seen = set()
        for offset in _descriptor_offsets(device.descriptors):
            part = device.descriptors[offset:offset + device.descriptors[offset]]
            if part[1] == 4:
                seen = set()
            elif part[1] == 5:
                address, attributes = part[2:4]
                packet = int.from_bytes(part[4:6], 'little')
                if (address in seen or attributes not in (2, 3) or
                        not 1 <= packet <= (512 if attributes == 2 else 1024)):
                    raise ControlBlocked('invalid_endpoint', 'invalid/duplicate or unsupported endpoint metadata')
                seen.add(address)
        return device

    def _generation_capability(self, *, recovery=False):
        state = self.status()
        if not state.get('host_enumerated'):
            raise ControlBlocked('virtual_target_unverified', 'generation capability needs a verified host device')
        self.jiritsu_target(state['target']['sysfs_path'], allow_recovery=recovery)
        record = self._load()
        if not record.get('attachment_id') or not record.get('device_key'):
            raise ControlBlocked('generation_api_missing', 'legacy import has no generation retirement evidence')
        return _GenerationCapability(self, record, recovery)

    def _check_capability(self, capability, record):
        if (not isinstance(capability, _GenerationCapability) or capability.control is not self or
                any(record.get(k) != capability.record.get(k) for k in
                    ('run_id', 'lease_id', 'owner_id', 'qmp_path', 'vm_pid', 'vm_start', 'backend_path',
                     'server_pid', 'server_start', 'server_port', 'attachment_id', 'device_key')) or
                record.get('owned_port') != capability.record.get('owned_port')):
            raise ControlBlocked('generation_owner_changed', 'generation capability no longer owns this run/VM/port/import')
        if record.get('preload_recovery_required') and not capability.recovery:
            raise ControlBlocked('preload_recovery_required', 'only the already-bound recovery consumer may continue')
        self._check_vm()
        if not self._server_alive(record):
            raise ControlBlocked('server_owner_lost', 'original owned server is not alive')

    def _import_receipt(self, record):
        receipt = read_json(self.context.run_dir / 'usb-import.json')
        fields = ('run_id', 'lease_id', 'owner_id', 'vm_pid', 'vm_start', 'qmp_path', 'backend_path',
                  'server_pid', 'server_start', 'attachment_id', 'device_key')
        owned = record.get('owned_port') or {}
        if (any(receipt.get(k) != record.get(k) for k in fields) or
                any(receipt.get(k) != owned.get(k) for k in
                    ('client_address', 'server_address', 'socket_inode'))):
            raise ControlBlocked('import_owner_mismatch', 'retirement receipt is not the exact old owner/socket')
        if receipt.get('state') == 'failed':
            raise ControlBlocked('import_retirement_failed', str(receipt.get('detail', 'old import failed')))
        return receipt

    def _reenumerate(self, capability, pids, *, seconds=20):
        if (type(seconds) not in (int, float) or not 0 < seconds <= 30 or
                not isinstance(pids, tuple) or not pids or
                any(type(pid) is not int or pid not in (0x0336, 0x096f) for pid in pids)):
            raise ValueError('bounded Sony service/final identity transition required')
        deadline = time.monotonic() + seconds
        with self._lock():
            while True:
                record = self._load()
                self._check_capability(capability, record)
                owned = record['owned_port']
                controller, row = self._owned_row(owned)
                receipt = self._import_receipt(record)
                # While active, the exact original TCP inode must still be live.
                if receipt.get('state') == 'active' and not self._owns_socket(owned):
                    raise ControlBlocked('socket_owner_mismatch', 'old TCP inode disappeared without retirement evidence')
                retired = (receipt.get('state') == 'retired' and receipt.get('safe_to_rebind') is True and
                           receipt.get('release') == 'generation_event_and_eof')
                if retired and row is None:
                    if self._owns_socket(owned):
                        raise ControlBlocked('old_socket_retained', 'released port still has a live original TCP socket')
                    try:
                        device = asyncio.run(self._backend())
                    except usbip.GadgetNotReady:
                        device = None
                    if device is not None:
                        self._validate_device(device)
                        if (int.from_bytes(device.descriptors[8:10], 'little') != 0x054c or
                                int.from_bytes(device.descriptors[10:12], 'little') not in pids):
                            raise ControlBlocked('unexpected_generation_identity', 'new guest descriptor is not the expected Sony identity')
                        # Preserve the old record until the new import has been accepted.
                        self._attach(record, device, reserved=(controller, owned['port']))
                        current_capability = _GenerationCapability(self, record, capability.recovery)
                        break
                if time.monotonic() >= deadline:
                    raise ControlBlocked('reenumeration_timeout', 'old import/port or new guest descriptor did not retire/enumerate')
                time.sleep(0.02)  # Bounded polling of verified state; errors above propagate.
            while True:
                state = self.status()
                record = self._load()
                self._check_capability(current_capability, record)
                if (record.get('owner_id') != capability.record['owner_id'] or
                        any(record['owned_port'][k] != owned[k] for k in ('controller', 'port'))):
                    raise ControlBlocked('generation_owner_changed', 'new enumeration changed owner/controller/port')
                if state.get('host_enumerated'):
                    reason = (state.get('blocked_reason') or {}).get('code')
                    if reason and not (capability.recovery and reason == 'preload_recovery_required'):
                        raise ControlBlocked(reason, state['blocked_reason']['detail'])
                    return state
                reason = state.get('blocked_reason')
                if reason and reason['code'] not in ('virtual_target_unverified', 'gadget_not_ready'):
                    raise ControlBlocked(reason['code'], reason['detail'])
                if time.monotonic() >= deadline:
                    raise ControlBlocked('reenumeration_timeout', 'new import has no matching real host sysfs enumeration')
                time.sleep(0.02)

    def _new_owner(self):
        return {'run_id': self.context.run_id, 'lease_id': self.context.lease_id,
                'qmp_path': str(self.context.qmp_path), 'backend_path': str(self.context.backend_path),
                'vm_pid': self.context.vm_pid, 'vm_start': process_start(self.context.vm_pid),
                'owner_id': uuid.uuid4().hex, 'cable_connected': False, 'owned_port': None,
                'preload_recovery_required': False}

    def _server_alive(self, record):
        pid = record.get('server_pid')
        if type(pid) is not int or record.get('server_start') != process_start(pid):
            return False
        try:
            command = Path('/proc', str(pid), 'cmdline').read_bytes().split(b'\0')
        except OSError:
            return False
        arguments = [b'--run-dir', str(self.context.run_dir).encode(),
                     b'--qmp', str(self.context.qmp_path).encode(),
                     b'--backend', str(self.context.backend_path).encode(),
                     b'--lease', self.context.lease.encode(), b'--vm-pid', str(self.context.vm_pid).encode(),
                     b'--run-id', self.context.run_id.encode()]
        prefix = [sys.executable.encode(), b'-B']
        return command == prefix + [str(BRIDGE_SOURCE).encode()] + arguments + [b''] or command == (
            prefix + [str(CONTROL_SOURCE).encode(), b'--serve-owned'] + arguments + [b''])

    def _owns_socket(self, owned):
        def address(value):
            host, port = value
            if host != '127.0.0.1' or type(port) is not int:
                raise ControlBlocked('socket_owner_mismatch', 'owned transport is not IPv4 loopback')
            return f"{int.from_bytes(socket.inet_aton(host), 'little'):08X}:{port:04X}"
        local, remote = address(owned['client_address']), address(owned['server_address'])
        with Path('/proc/net/tcp').open() as source:
            for line in source:
                fields = line.split()
                if (len(fields) >= 10 and fields[1:4] == [local, remote, '01'] and
                        fields[9] == str(owned['socket_inode'])):
                    return True
        return False

    def _start_server(self, record):
        ready = self.context.run_dir / 'usb-server.json'
        if ready.exists() or ready.is_symlink():
            old = read_json(ready)
            if old.get('run_id') != self.context.run_id or old.get('lease_id') != self.context.lease_id:
                raise ControlBlocked('server_lease_mismatch', 'existing server record belongs to another lease')
            if process_start(old.get('pid')) is not None:
                raise ControlBlocked('server_already_running', 'existing USB/IP server must be disconnected by its owner')
            ready.unlink()
        log_path = self.context.run_dir / 'usb-server.log'
        fd = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ControlBlocked('unsafe_server_log', 'server log is not an owned private regular file')
            command = [sys.executable, '-B', str(CONTROL_SOURCE), '--serve-owned', '--run-dir', str(self.context.run_dir),
                       '--qmp', str(self.context.qmp_path), '--backend', str(self.context.backend_path),
                       '--lease', self.context.lease, '--vm-pid', str(self.context.vm_pid),
                       '--run-id', self.context.run_id]
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, start_new_session=True)
            self.server_process = process
        finally:
            os.close(fd)
        record.update(server_pid=process.pid, server_start=process_start(process.pid))
        self._save(record)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ControlBlocked('server_start_failed', 'owned USB/IP server exited; see usb-server.log')
            if ready.exists():
                data = read_json(ready)
                if (data.get('pid') != process.pid or data.get('lease_id') != self.context.lease_id or
                        data.get('run_id') != self.context.run_id or data.get('host') != '127.0.0.1'):
                    raise ControlBlocked('server_lease_mismatch', 'server readiness identity mismatch')
                record['server_port'] = usbip.integer(data.get('port'), 1, 65535, 'server port')
                self._save(record)
                return
            time.sleep(0.02)
        raise ControlBlocked('server_start_timeout', 'server did not publish bounded loopback readiness')

    def _write_sysfs(self, controller, attribute, text):
        if attribute not in ('attach', 'detach') or controller not in self._controllers():
            raise ControlBlocked('physical_usb_refused', 'only explicit virtual VHCI attach/detach is allowed')
        path = controller / attribute
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW)
        try:
            if os.write(fd, text.encode('ascii')) != len(text):
                raise ControlBlocked('vhci_short_write', 'VHCI ownership action was incomplete')
        finally:
            os.close(fd)

    def _attach(self, record, device, *, reserved=None):
        self._validate_device(device)
        if reserved is None:
            controller, row = self._free_port(device.metadata['speed'])
        else:
            controller, port = reserved
            if controller not in self._controllers() or type(port) is not int:
                raise ControlBlocked('port_owner_mismatch', 'reserved virtual controller/port is invalid')
            row = next((r for r in self._rows(controller) if r['port'] == port), None)
            if not row or row['status'] != 4 or row['hub'] != ('ss' if device.metadata['speed'] >= 5 else 'hs'):
                raise ControlBlocked('port_owner_mismatch', 'the original reserved port is not free/compatible')
            if not all(os.access(controller / name, os.W_OK) for name in ('attach', 'detach')):
                raise ControlBlocked('vhci_permission_denied', 'original reserved port is not writable')
        with socket.create_connection(('127.0.0.1', record['server_port']), timeout=5) as peer:
            attachment_id = uuid.uuid4().hex
            record['import_request'] = {'attachment_id': attachment_id, 'device_key': self._device_key(device),
                                        'client_address': list(peer.getsockname()),
                                        'server_address': list(peer.getpeername()),
                                        'socket_inode': os.fstat(peer.fileno()).st_ino}
            self._save(record)
            def exact(count):
                result = bytearray()
                while len(result) < count:
                    block = peer.recv(count - len(result))
                    if not block:
                        raise ControlBlocked('usbip_import_failed', 'server disconnected during import')
                    result.extend(block)
                return bytes(result)
            peer.sendall(usbip.COMMON.pack(usbip.VERSION, usbip.IMPORT, 0) + device.busid.encode().ljust(32, b'\0'))
            if usbip.COMMON.unpack(exact(8)) != (usbip.VERSION, usbip.IMPORT & 0x7fff, 0):
                raise ControlBlocked('usbip_import_failed', 'actual backend refused import')
            if exact(usbip.DEVICE.size) != device.wire(self.context.run_id):
                raise ControlBlocked('usbip_identity_mismatch', 'import differs from guest discovery')
            if next((r for r in self._rows(controller) if r['port'] == row['port']), None) != row:
                raise ControlBlocked('vhci_port_race', 'free VHCI port changed before attach')
            owned = {'controller': str(controller), 'port': row['port'], 'devid': device.devid,
                     'speed': device.metadata['speed'], 'sockfd': peer.fileno(),
                     'socket_inode': os.fstat(peer.fileno()).st_ino, 'local_busid': None,
                     'client_address': list(peer.getsockname()), 'server_address': list(peer.getpeername())}
            if record.get('attachment_id'):
                record['previous_import'] = {key: record.get(key) for key in
                                             ('attachment_id', 'device_key', 'owned_port')}
            record.update(attachment_id=attachment_id, device_key=self._device_key(device),
                          descriptor_sha256=hashlib.sha256(device.descriptors).hexdigest())
            record.pop('detach_requested', None)
            record['owned_port'] = owned
            record['attach_pending'] = True
            self._save(record)
            self._log('attach_requested', owned_port=owned)
            self._write_sysfs(controller, 'attach', f"{owned['port']} {peer.fileno()} {device.devid} {device.metadata['speed']}\n")
            actual = next((r for r in self._rows(controller) if r['port'] == owned['port']), None)
            if (not actual or actual['status'] not in (5, 6) or
                    actual['devid'] != device.devid or actual['speed'] != device.metadata['speed']):
                raise ControlBlocked('attach_readback_failed', 'VHCI did not retain the requested virtual device')
            owned['sockfd'] = actual['sockfd']
            if actual['local_busid'] != '0-0':
                owned['local_busid'] = actual['local_busid']
            record['attach_pending'] = False
            self._save(record)
            self._log('attach_written', owned_port=owned)
            # VHCI takes its own socket reference; closing this userspace fd is required.

    def connect(self):
        result = self._base()
        try:
            with self._lock():
                record = self._load()
                if record.get('preload_recovery_required'):
                    result['preload_recovery_required'] = True
                    raise ControlBlocked('preload_recovery_required', 'recover guest preload before reconnect')
                if record.get('owned_port'):
                    _, current = self._owned_row(record['owned_port'])
                    if current is not None:
                        return self.status()
                    self._stop_server(record)
                    record['owned_port'] = None
                    record['attach_pending'] = False
                    self._save(record)
                    self._log('released_virtual_port_reconnected')
                self._check_vm()
                asyncio.run(self._backend('hello'))
                # Check host permissions before changing virtual cable state or starting a server.
                controllers = self._controllers()
                if not any(os.access(c / 'attach', os.W_OK) and os.access(c / 'detach', os.W_OK) for c in controllers):
                    raise ControlBlocked('vhci_permission_denied', 'virtual attach needs explicit host permission; no helper invoked')
                if not record:
                    record = self._new_owner()
                self._save(record)
                asyncio.run(self._backend('vbus', True))
                record['cable_connected'] = True
                self._save(record)
                self._log('vbus_on')
                async def wait_ready():
                    deadline = time.monotonic() + 3
                    while True:
                        try:
                            return await self._backend()
                        except usbip.Blocked:
                            if time.monotonic() >= deadline:
                                raise
                            await asyncio.sleep(0.05)
                device = asyncio.run(wait_ready())
                record['descriptor_sha256'] = hashlib.sha256(device.descriptors).hexdigest()
                self._free_port(device.metadata['speed'])
                self._start_server(record)
                self._attach(record, device)
            return self.status()
        except (usbip.Blocked, usbip.ProtocolError, OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as error:
            try:
                record = self._load()
                result['cable_connected'] = record.get('cable_connected', False)
                result['owned_port'] = record.get('owned_port')
                self._log('connect_blocked', code=getattr(error, 'code', 'backend_unavailable'), detail=str(error))
            except (OSError, ValueError, usbip.Blocked):
                pass
            return self._failure(result, error)

    def _stop_server(self, record):
        if record.get('preload_recovery_required'):
            raise ControlBlocked('preload_recovery_required', 'preload recovery must finish before stopping the server')
        if not record.get('server_pid'):
            return
        if record.get('attachment_id'):
            deadline = time.monotonic() + 3
            while True:
                receipt = self._import_receipt(record)
                if ((receipt.get('state') == 'retired' and receipt.get('safe_to_rebind') is True) or
                        _import_disconnected(receipt)):
                    break
                if time.monotonic() >= deadline:
                    raise ControlBlocked('import_release_pending', 'server retains unverified old URBs/FDs')
                time.sleep(0.02)
        if self._server_alive(record):
            os.kill(record['server_pid'], signal.SIGTERM)
        elif process_start(record['server_pid']) is not None:
            raise ControlBlocked('server_owner_mismatch', 'server PID now belongs to another process; no signal sent')
        if self.server_process and self.server_process.pid == record['server_pid']:
            try:
                self.server_process.wait(timeout=3)
            except subprocess.TimeoutExpired as error:
                raise ControlBlocked('server_stop_timeout', 'owned server did not exit; ownership record retained') from error
            self.server_process = None
        deadline = time.monotonic() + 3
        while process_start(record['server_pid']) is not None:
            # A child owned by this instance is reaped above; never signal a reused PID.
            if time.monotonic() >= deadline:
                raise ControlBlocked('server_stop_timeout', 'owned server exit not confirmed; record retained')
            time.sleep(0.02)
        record.pop('server_pid', None)
        record.pop('server_start', None)
        record.pop('server_port', None)

    def disconnect(self):
        result = self._base()
        try:
            with self._lock():
                record = self._load()
                if not record:
                    return result
                result['preload_recovery_required'] = record.get('preload_recovery_required', False)
                result['cable_connected'] = record.get('cable_connected', False)
                result['owned_port'] = record.get('owned_port')
                if result['preload_recovery_required']:
                    raise ControlBlocked('preload_recovery_required', 'guest preload recovery must finish before detach')
                if record.get('attachment_id'):
                    self._import_receipt(record)
                owned = record.get('owned_port')
                if owned:
                    controller, row = self._owned_row(owned)
                    if row is not None:
                        if not self._server_alive(record) or not self._owns_socket(owned):
                            raise ControlBlocked('server_owner_lost', 'cannot prove current port/socket belongs to the original server')
                        if record.get('attachment_id'):
                            record['detach_requested'] = record['attachment_id']
                            self._save(record)
                        self._write_sysfs(controller, 'detach', str(owned['port']) + '\n')
                        deadline = time.monotonic() + 1
                        while True:
                            current = next((r for r in self._rows(controller) if r['port'] == owned['port']), None)
                            if current and current['status'] == 4:
                                break
                            if (current is None or time.monotonic() >= deadline or
                                    any(current[k] != owned[k] for k in ('devid', 'speed', 'sockfd'))):
                                raise ControlBlocked('detach_pending', 'VHCI has not released the owned port; record retained')
                            time.sleep(0.02)
                        self._log('detach_written', owned_port=owned)
                    # Keep the exact import/socket fields until server release is proven.
                    self._stop_server(record)
                    record['owned_port'] = None
                    self._save(record)
                else:
                    self._stop_server(record)
                self._save(record)
                if record.get('cable_connected'):
                    self._check_vm()
                    asyncio.run(self._backend('vbus', False))
                    record['cable_connected'] = False
                    self._save(record)
                    self._log('vbus_off')
                self._log('disconnected')
                return self._base()
        except (usbip.Blocked, usbip.ProtocolError, OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as error:
            return self._failure(result, error)

    def jiritsu_target(self, usb_syspath, *, allow_recovery=False):
        if type(allow_recovery) is not bool:
            raise ValueError('allow_recovery must be bool')
        result = self.status()
        recovering = (allow_recovery and result['phase'] == 'recovery_required' and
                      result.get('preload_recovery_required') is True and
                      (result.get('blocked_reason') or {}).get('code') == 'preload_recovery_required')
        if not result['host_enumerated'] or (result['phase'] != 'enumerated' and not recovering):
            raise ControlBlocked('virtual_target_unverified', 'enumerate and verify the owned VHCI device before jiritsu')
        requested = Path(usb_syspath).resolve(strict=True)
        if requested != Path(result['target']['sysfs_path']):
            raise ControlBlocked('physical_usb_refused', 'jiritsu may consume only the exact owned VHCI target')
        return {**result['target'], 'run_id': self.context.run_id, 'lease_id': self.context.lease_id,
                'authentication_verified': False, 'guest_root_verified': False}

    def mark_recovery_required(self, reason):
        with self._lock():
            record = self._load()
            if not record.get('owned_port'):
                raise ControlBlocked('virtual_target_unverified', 'no owned guest connection for recovery')
            record['preload_recovery_required'] = True
            self._save(record)
            self._log('preload_recovery_required', reason=str(reason)[:512])

    def record_preload_recovery(self, readback):
        # The real USB consumer supplies the readback; this verifies the required neutral bytes only.
        if not isinstance(readback, bytes) or readback != b' ' * 512:
            raise ControlBlocked('preload_recovery_required', '512 space bytes must be read back from the guest')
        with self._lock():
            record = self._load()
            if not record.get('owned_port') or not record.get('preload_recovery_required'):
                raise ControlBlocked('recovery_owner_mismatch', 'no pending recovery for this owned connection')
            record['preload_recovery_required'] = False
            self._save(record)
            self._log('preload_neutralized_readback', sha256=hashlib.sha256(readback).hexdigest())


def _import_disconnected(receipt):
    return (receipt.get('state') == 'disconnected' and receipt.get('safe_to_disconnect') is True and
            receipt.get('safe_to_rebind') is False and receipt.get('release') == 'client_eof_and_quiescent')


# Private instrumentation for the existing server, installed only in its child.
# No alternate endpoint provider or second attachment owner is introduced.
def _owned_server_types(control):
    from contextvars import ContextVar
    current_import = ContextVar('owned_usb_import', default=None)
    original_bridge = usbip.Bridge
    holds = {}
    retained_bridges = {}

    class OwnedBridge(original_bridge):
        def __init__(self, reader, writer):
            self.receipt = current_import.get()
            self.role = None
            self.event_seen = False
            self.closed = False
            self.import_session = None
            self.frame_started = False
            super().__init__(reader, writer)

        def publish(self, state, **fields):
            if self.receipt is not None and self.role == 'usbip':
                # A failed cancellation/late completion is sticky for this import.
                if self.receipt.get('state') == 'failed' and state != 'failed':
                    return
                self.receipt.update(state=state, **fields)
                usbip.write_owned_json(control.context.run_dir / 'usb-import.json', self.receipt)

        @classmethod
        async def open(cls, context, role):
            bridge = await super().open(context, role)
            bridge.role = role
            if role == 'usbip':
                if bridge.receipt is None:
                    await original_bridge.close(bridge)
                    raise ControlBlocked('import_owner_mismatch', 'import has no bound owner request')
                retained_bridges[bridge.receipt['attachment_id']] = bridge
                bridge.publish('active', safe_to_rebind=False)
            return bridge

        async def describe(self):
            device = await super().describe()
            if self.role == 'usbip':
                control._validate_device(device)
                if control._device_key(device) != self.receipt['device_key']:
                    self.publish('failed', detail='import descriptor/endpoint metadata changed')
                    raise ControlBlocked('guest_device_changed', 'import descriptor/endpoint metadata changed')
            return device

        async def _read(self):
            try:
                while True:
                    first = await self.reader.readexactly(1)
                    self.frame_started = True
                    header, payload = await usbip.read_frame(PrefixReader(first, self.reader), timeout=None)
                    self.frame_started = False
                    if header['op'] == 'event':
                        if (self.role != 'usbip' or header['id'] != 1 or payload or header.get('ok') is not True or
                                header.get('kind') not in ('disconnect', 'device_changed') or
                                header.get('reason') != 'guest controller cable generation changed' or
                                any(expected != 'complete' for _, expected in self.requests.values())):
                            raise usbip.ProtocolError('unverified generation/cancellation boundary')
                        self.event_seen = True
                        self.publish('retiring', pending_ids=sorted(self.requests),
                                     event_kind=header['kind'], safe_to_rebind=False)
                        # The source-bound guest invalidates/cancels before this event.
                        # EOF is required too: bytes after the boundary are a failure.
                        try:
                            await asyncio.wait_for(self.reader.readexactly(1), 2)
                        except asyncio.IncompleteReadError as error:
                            if error.partial:
                                raise usbip.ProtocolError('partial late generation frame') from error
                        else:
                            raise usbip.ProtocolError('late completion after generation boundary')
                        self.publish('retired', safe_to_rebind=True, release='generation_event_and_eof')
                        raise usbip.Blocked('owned guest generation retired')
                    if (self.import_session and self.import_session.reader.clean_eof and
                            header['op'] == 'complete'):
                        raise usbip.ProtocolError('late completion during client EOF release')
                    request = self.requests.get(header['id'])
                    if request is None:
                        if header['id'] in self.retired and header['op'] == 'complete':
                            self.retired.remove(header['id'])
                            continue
                        raise usbip.ProtocolError('unsolicited or duplicate backend completion')
                    future, expected = request
                    if header['op'] != expected or header.get('ok') is not True:
                        raise usbip.ProtocolError('backend rejected or mismatched response')
                    del self.requests[header['id']]
                    if not future.done():
                        future.set_result((header, payload))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.error = error
                if not (self.receipt and self.receipt.get('safe_to_rebind') is True):
                    self.publish('failed', safe_to_rebind=False, detail=str(error),
                                 errno=getattr(error, 'errno', None))
                for future, _ in self.requests.values():
                    if not future.done():
                        future.set_exception(error)
                # Keep requests and both transport FDs after an unproven release.

        async def cancel(self, request_id):
            try:
                await super().cancel(request_id)
            except BaseException as error:
                try:
                    self.publish('failed', safe_to_rebind=False, detail=str(error),
                                 errno=getattr(error, 'errno', None))
                except Exception as receipt_error:
                    raise error from receipt_error
                raise

        async def close(self):
            if self.closed:
                return
            if self.role != 'usbip':
                self.closed = True
                return await super().close()
            if self.event_seen:
                await asyncio.wait_for(asyncio.shield(self.task), 3)
            elif not self.error:
                record = control._load()
                detached = record.get('detach_requested') == self.receipt['attachment_id']
                session = self.import_session
                clean_eof = (session is not None and session.reader.clean_eof and session.failure is None and
                             not record.get('preload_recovery_required') and
                             not session.pending and session.reserved == 0 and
                             all(task.done() for task in session.tasks))
                if detached or clean_eof:
                    if any(expected != 'complete' for _, expected in self.requests.values()):
                        self.publish('failed', safe_to_rebind=False, detail='cancellation still pending')
                        return
                    for request_id in tuple(self.requests):
                        await self.cancel(request_id)
                    # Let the real backend reader consume already-arriving late bytes/errors.
                    await asyncio.sleep(0)
                    if (self.error or self.frame_started or self.requests or self.task.done() or
                            self.receipt.get('state') == 'failed' or
                            (clean_eof and not detached and control._load().get('preload_recovery_required'))):
                        self.publish('failed', safe_to_rebind=False, detail='import is not quiescent')
                        return
                    if clean_eof and not detached:
                        self.publish('disconnected', safe_to_disconnect=True, safe_to_rebind=False,
                                     release='client_eof_and_quiescent')
                    else:
                        self.publish('retired', safe_to_rebind=True, release='owned_detach_and_cancel_ack')
            if self.receipt.get('safe_to_rebind') is not True and not _import_disconnected(self.receipt):
                self.publish('failed', safe_to_rebind=False, detail='import close without release evidence')
                return
            self.closed = True
            await super().close()
            retained_bridges.pop(self.receipt['attachment_id'], None)

    class ClientReader:
        def __init__(self, reader):
            self.reader = reader
            self.at_header = True
            self.clean_eof = False

        async def readexactly(self, size):
            at_header, self.at_header = self.at_header, False
            try:
                raw = await self.reader.readexactly(size)
            except asyncio.IncompleteReadError as error:
                self.clean_eof = at_header and size == 48 and not error.partial
                raise
            if at_header:
                command, _, _, direction, _ = usbip.BASIC.unpack(raw[:20])
                self.at_header = command != usbip.SUBMIT or direction != 0
            else:
                self.at_header = True
            return raw

    class OwnedImportSession(usbip.ImportSession):
        def __init__(self, reader, writer, bridge, device, urb_timeout=30):
            super().__init__(ClientReader(reader), writer, bridge, device, urb_timeout)
            bridge.import_session = self

        async def _watch_backend(self):
            # Session teardown cancels its watcher, while close still needs the real cancel replies.
            await asyncio.shield(self.bridge.task)
            self.writer.close()

        async def complete(self, entry):
            try:
                await super().complete(entry)
            except asyncio.CancelledError:
                if (self.reader.clean_eof and not entry.completed and entry.future.done() and
                        not entry.future.cancelled()):
                    self.bridge.publish('failed', safe_to_rebind=False,
                                        detail='unconsumed completion at client EOF')
                raise
            expected_retirement = (self.bridge.event_seen and self.bridge.receipt.get('safe_to_rebind') is True and
                                   self.failure is self.bridge.error)
            if self.failure is not None and not expected_retirement:
                self.bridge.publish('failed', safe_to_rebind=False, detail=str(self.failure),
                                    errno=getattr(self.failure, 'errno', None))

    class PrefixReader:
        def __init__(self, prefix, reader):
            self.prefix, self.reader = prefix, reader

        async def readexactly(self, size):
            prefix = self.prefix[:size]
            self.prefix = self.prefix[len(prefix):]
            return prefix + (await self.reader.readexactly(size - len(prefix)) if len(prefix) < size else b'')

    class OwnedServer(usbip.UsbIpServer):
        async def handle(self, reader, writer):
            hold = None
            receipt = None
            token = None
            try:
                # The owner persists import_request before sending this header.
                # TCP accept alone races the owner's post-connect record write.
                prefix = await asyncio.wait_for(reader.readexactly(8), 5)
                record = control._load()
                request = record.get('import_request') or {}
                if (not control._server_alive(record) or record.get('server_pid') != os.getpid() or
                        not control._owns_socket(request) or
                        list(writer.get_extra_info('peername')) != request.get('client_address') or
                        list(writer.get_extra_info('sockname')) != request.get('server_address')):
                    raise ControlBlocked('import_owner_mismatch', 'TCP peer is not this owner attachment request')
                receipt = {key: record[key] for key in ('run_id', 'lease_id', 'owner_id', 'vm_pid', 'vm_start',
                                                       'qmp_path', 'backend_path', 'server_pid', 'server_start')}
                receipt.update(request, state='opening', safe_to_rebind=False)
                hold = writer.get_extra_info('socket').dup()
                holds[request['attachment_id']] = (hold, receipt)
                token = current_import.set(receipt)
                await super().handle(PrefixReader(prefix, reader), writer)
            except (OSError, ValueError, usbip.Blocked) as error:
                self.last_error = str(error)
            finally:
                if token is not None:
                    current_import.reset(token)
                if receipt is not None and (receipt.get('safe_to_rebind') is True or _import_disconnected(receipt)):
                    hold.close()
                    holds.pop(receipt['attachment_id'], None)
                writer.close()
                await writer.wait_closed()

    return OwnedBridge, OwnedServer, holds, retained_bridges, OwnedImportSession


async def _serve_owned(control):
    original_bridge, original_session = usbip.Bridge, usbip.ImportSession
    OwnedBridge, OwnedServer, holds, retained_bridges, OwnedImportSession = _owned_server_types(control)
    # These references are private to this isolated owned-server child.
    usbip.Bridge, usbip.ImportSession = OwnedBridge, OwnedImportSession
    lock = os.open(control.context.run_dir / 'usb-server.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ControlBlocked('unsafe_lock', 'server lock must be an owned private regular file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        server = await OwnedServer(control.context).start()
        usbip.write_owned_json(control.context.run_dir / 'usb-server.json',
                               {'run_id': control.context.run_id, 'lease_id': control.context.lease_id,
                                'pid': os.getpid(), 'port': server.port, 'host': server.host})
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        while True:
            await stop.wait()
            if any(receipt.get('safe_to_rebind') is not True and not _import_disconnected(receipt)
                   for _, receipt in holds.values()):
                control._log('server_retained', reason='import release is unverified')
                stop.clear()
                continue
            await server.close()
            break
    finally:
        usbip.Bridge, usbip.ImportSession = original_bridge, original_session
        os.close(lock)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve-owned', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('action', nargs='?', choices=('status', 'connect', 'disconnect'), default='status')
    parser.add_argument('--check', action='store_true')
    for name in ('run-dir', 'qmp', 'lease'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--backend')
    parser.add_argument('--vm-pid', type=int, required=True)
    parser.add_argument('--run-id')
    args = parser.parse_args(argv)
    try:
        control = UsbControl(args.run_dir, qmp_path=args.qmp, backend_path=args.backend,
                             lease=args.lease, vm_pid=args.vm_pid, run_id=args.run_id)
        if args.serve_owned:
            if args.check or args.action != 'status':
                raise ControlBlocked('server_action_invalid', 'owned server accepts no control action')
            asyncio.run(_serve_owned(control))
            return 0
        if args.check and args.action != 'status':
            raise ControlBlocked('check_is_read_only', '--check cannot be combined with a mutating action')
        result = getattr(control, args.action)()
    except (ValueError, RuntimeError, OSError) as error:
        result = empty_status()
        result.update(phase='blocked', blocked_reason={'code': getattr(error, 'code', 'invalid_context'),
                                                     'detail': str(error)})
    print(json.dumps(result, sort_keys=True))
    return 2 if result['phase'] in ('blocked', 'error', 'recovery_required') else 0


if __name__ == '__main__':
    sys.exit(main())
