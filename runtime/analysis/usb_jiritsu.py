#!/usr/bin/env python3
"""Real jiritsu consumer for one UsbControl-owned virtual USB connection.

UI integration: JiritsuConsumer(control, pmca=PATH).run('authenticate'|'version'|
'root'|'recover'). Run outside the UI thread. Each call starts a fresh isolated
Python process. No usb.core/PMCA imports or global USB patches occur in the UI.
The child uses the archived usb_service_probe helpers and the unmodified PMCA
SonySenserAuthDevice.authenticate, GenericUsbDriver/UsbBackend, version reader,
deploy_and_run and command_runner_driver. It owns session cleanup because the old
probe's unconditional Stop Senser is unsafe after PreloadRecoveryRequired.

Only real usb.core.find results are filtered. Sysfs is an ownership check, never
a libusb backend. Each enumeration, open and bulk/control operation revalidates
jiritsu_target(), run/lease, owner and exact VHCI controller/port. Reenumeration
may change PID/address on that port; it cannot switch runs, leases or ports.
UsbControl must independently validate the new guest descriptors/attachment.

Root/recover require jiritsu_target(path, allow_recovery=True), which must verify
all the normal ownership checks while admitting ONLY the pending preload latch.
Older control implementations are blocked BEFORE authentication/writes. The
existing mark_recovery_required(reason) is set before deployment and only
record_preload_recovery(actual_readback_bytes) can clear it. Cleanup writes and
reads exactly 512 spaces through the SAME authenticated USB transport. Missing
readback, a missing authentication result or missing Uid/Gid evidence fails shut.
No consumer action calls connect/disconnect, VHCI detach or a privilege helper.
Generation transitions use the existing controller's private, owner-bound
capability. The old TargetGuard stays invalid after rebinding; the new guard
checks fresh real sysfs/libusb enumeration before the next original operation.

Source paths and SHA-256 hashes (including the adapter, control, bridge, archived
scripts, PMCA and root payload) are bound across the subprocess boundary and
rechecked before imports/use. Root uses the archived reviewed payload digest and
its original arm-preload-once approval token, authorized for this virtual scope.
Missing payload/dependencies/control ABI is a structured blocked result.

This module's synthetic unit tests prove guards and call wiring only. Until the
real host enumerates and the original guest responds, authentication/root remain
false. Neither a fake USB library nor fabricated replies are supplied here.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import signal
import stat
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from usb_control import ControlBlocked, UsbControl, usbip

SCRIPTS = Path(os.environ.get('A7C2_VIRTUAL_JIRITSU_SCRIPTS', str(HERE.parents[1] / 'external/sony-pmca-tools')))
ROOT_COMMAND = "busybox grep -E '^(Uid|Gid):' /proc/$$/status"
PAYLOAD_NAME = 'a7c2_shell.arm64.so'
PAYLOAD_SHA256 = 'd261855eb1ea461a77c7847fefef7e6960d4495433d245a9eeb458eef0b35e6e'
NEUTRAL = b' ' * 512
ACTIONS = ('authenticate', 'version', 'root', 'recover')


def blocked(code, detail):
    return ControlBlocked(code, detail)


def result_base(control, action):
    return {'schema': 'a7c2.usb-jiritsu.v1', 'run_id': control.context.run_id,
            'lease_id': control.context.lease_id, 'action': action, 'phase': 'blocked',
            'blocked_reason': None, 'authentication_verified': False,
            'guest_root_verified': False, 'preload_recovery_required': False,
            'target': None, 'sources': {}, 'events': []}


def recovery_target_supported(control):
    return 'allow_recovery' in inspect.signature(control.jiritsu_target).parameters


class TargetGuard:
    """Pin one owner/port, accepting only matching actual enumeration returns."""
    def __init__(self, control, *, recovery=False):
        self.control = control
        self.recovery = recovery
        self.pin = None
        self.generation = None
        self.capability = None
        self.current()

    def current(self):
        state = self.control.status()
        target = state.get('target')
        if not state.get('host_enumerated') or not isinstance(target, dict):
            reason = state.get('blocked_reason') or {}
            raise blocked(reason.get('code', 'virtual_target_unverified'),
                          reason.get('detail', 'owned VHCI device is not enumerated'))
        if self.recovery:
            if not recovery_target_supported(self.control):
                raise blocked('control_recovery_api_missing',
                              'jiritsu_target must support allow_recovery=True')
            target = self.control.jiritsu_target(target['sysfs_path'], allow_recovery=True)
        else:
            target = self.control.jiritsu_target(target['sysfs_path'])
        record = self.control._load()
        owned = record.get('owned_port') or {}
        controller = Path(target['vhci_controller']).resolve(strict=True)
        expected_parent = (self.control.sysfs / 'devices/platform').resolve(strict=True)
        path = Path(target['sysfs_path']).resolve(strict=True)
        if (controller.parent != expected_parent or
                not re.fullmatch(r'vhci_hcd\.[0-9]+', controller.name) or
                not path.is_relative_to(controller)):
            raise blocked('physical_usb_refused', 'target is not below the explicit VHCI controller')
        if (target.get('virtual_ancestor_verified') is not True or
                target.get('run_id') != self.control.context.run_id or
                target.get('lease_id') != self.control.context.lease_id or
                record.get('run_id') != target['run_id'] or
                record.get('lease_id') != target['lease_id'] or
                owned.get('controller') != str(controller) or
                owned.get('local_busid') not in (None, target['local_busid']) or
                path.name != target['local_busid'] or
                not re.fullmatch(r'[0-9]+-[0-9]+(?:\.[0-9]+)*', path.name) or
                not record.get('owner_id') or type(owned.get('port')) is not int):
            raise blocked('target_owner_mismatch', 'run/lease/ancestor/port verification disagrees')
        pin = (target['run_id'], target['lease_id'], record['owner_id'], str(controller),
               owned['port'], target['local_busid'])
        if self.pin is not None and pin != self.pin:
            raise blocked('target_owner_changed', 'consumer cannot follow a different owner/run/lease/port')
        generation = record.get('attachment_id')
        if self.generation is not None and generation != self.generation:
            raise blocked('target_generation_changed', 'old guard cannot consume a rebound import')
        self.pin = pin
        self.generation = generation
        if generation and self.capability is None:
            self.capability = self.control._generation_capability(recovery=self.recovery)
        if target['vendor_id'] != 0x054c or target['product_id'] not in (0x0e8a, 0x0336):
            raise blocked('unsupported_usb_identity', 'real guest has not exposed a supported Sony service identity')
        return target

    def _arm_recovery(self):
        self.recovery = True
        self.current()
        if self.generation is not None:
            self.capability = self.control._generation_capability(recovery=True)

    def follow_generation(self, real_find, pid=0x0336):
        if self.capability is None:
            raise blocked('generation_api_missing', 'controller cannot prove old import retirement')
        self.control._reenumerate(self.capability, (pid,))
        fresh = TargetGuard(self.control, recovery=self.recovery)
        if fresh.pin != self.pin or fresh.generation == self.generation:
            raise blocked('target_owner_changed', 'new guard must keep owner/controller/port and change import')
        return fresh, fresh.wait_for(real_find, pid)

    def final_identity(self):
        if self.capability is None:
            raise blocked('generation_api_missing', 'stop requires independent owned host identity readback')
        state = self.control._reenumerate(self.capability, (0x096f, 0x0336), seconds=5)
        return {'verified': True, 'target': state['target'], 'source': 'owned-host-sysfs-readback'}

    @staticmethod
    def matches(device, target):
        ports = tuple(int(part) for part in target['local_busid'].split('-', 1)[1].split('.'))
        return (device.bus == target['busnum'] and device.address == target['devnum'] and
                tuple(device.port_numbers or ()) == ports and
                device.idVendor == target['vendor_id'] and device.idProduct == target['product_id'])

    def check_device(self, device):
        target = self.current()
        if not self.matches(device, target):
            raise blocked('foreign_usb_device', 'libusb device is not the current owned VHCI target')
        return target

    def find(self, real_find, pid=None):
        target = self.current()
        # Never synthesize devices or mutate the real backend's responses.
        devices = [dev for dev in real_find(find_all=True, idVendor=0x054c)
                   if self.matches(dev, target) and (pid is None or dev.idProduct == pid)]
        if len(devices) > 1:
            raise blocked('ambiguous_virtual_device', 'multiple real returns match one owned target')
        if devices:
            self.check_device(devices[0])
            return devices[0]
        return None

    def wait_for(self, real_find, pid, seconds=20):
        deadline = time.monotonic() + seconds
        while True:
            try:
                device = self.find(real_find, pid)
                if device is not None:
                    return device
            except ControlBlocked as error:
                # Reenumeration must be admitted by control, never guessed by VID/PID.
                if error.code not in ('virtual_target_unverified', 'gadget_not_ready'):
                    raise
            if time.monotonic() >= deadline:
                raise blocked('reenumeration_unverified', 'owned virtual service identity did not enumerate')
            time.sleep(0.1)


def authentication_proven(exchanges):
    if len(exchanges) != 7:
        return False
    for index, (command, result, reply) in enumerate(exchanges):
        expected = (1, 3, 1, 3, 1, 3, 5)[index]
        if command != expected or not isinstance(reply, bytes):
            return False
        if command == 1 and result not in (2, 8):
            return False
        if command == 3 and result != 4:
            return False
        if command == 5 and (result != 6 or not reply or reply[0] != 1):
            return False
    return True


def root_from_commands(raw):
    """Parse original command-runner JSON, requiring the exact /proc command."""
    try:
        rows = json.loads(raw, object_pairs_hook=usbip._object)
    except (TypeError, ValueError, UnicodeError):
        return None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    found = [row for row in rows if row.get('command') == ROOT_COMMAND]
    if len(found) != 1 or type(found[0].get('exit_status')) is not int or found[0]['exit_status'] != 0:
        return None
    output = found[0].get('output')
    if not isinstance(output, str):
        return None
    ids = {}
    for line in output.splitlines():
        match = re.fullmatch(r'(Uid|Gid):\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s*', line)
        if match:
            key = match[1].lower()
            if key in ids:
                return None
            ids[key] = [int(part) for part in match.groups()[1:]]
        elif line.startswith(('Uid:', 'Gid:')):
            return None
    return ids if ids == {'uid': [0, 0, 0, 0], 'gid': [0, 0, 0, 0]} else None


def neutralize_preload(transport, control, guard, version, log):
    """Actual same-USB write + read, never a deployment record or a made-up blob."""
    path = b'/tmp/jiritsu/../../etc/ld.so.preload'
    select = struct.pack('<HH', 0x1001, 0x0f) + b'\0' + path + b'\0'
    write = struct.pack('<HH', 0x1001, 0x10) + b'\x00\xff\x00' + NEUTRAL
    read = struct.pack('<HH', 0x1001, 0x11) + b'\x00\xff\x00'
    version.authorize(transport, (select, write, read))
    version.exchange(transport, select, 4, log)
    version.exchange(transport, write, 4, log)
    version.exchange(transport, select, 4, log)
    after = version.exchange(transport, read, 4 + version.AUTHORIZED_MAX_BYTES, log)
    if not isinstance(after, bytes) or after != NEUTRAL:
        raise blocked('preload_recovery_required', 'USB readback was not exactly 512 spaces')
    guard.current()
    control.record_preload_recovery(after)
    log('preload_recovery_readback', bytes=len(after), sha256=hashlib.sha256(after).hexdigest())


class Sources:
    def __init__(self, scripts=SCRIPTS, pmca=None):
        self.scripts = Path(scripts).resolve(strict=True)
        candidates = [self.scripts / 'vendor/pmca-adamwuqwq',
                      HERE.parents[1] / 'analysis/vendor/pmca-adamwuqwq']
        self.pmca = Path(pmca).resolve(strict=True) if pmca else next(
            (path.resolve() for path in candidates if (path / 'pmca/usb/sony.py').is_file()), candidates[0])

    def manifest(self, action):
        required = [HERE / 'usb_jiritsu.py', HERE / 'usb_control.py',
                    HERE / 'usb-gadget/usbip_server.py']
        required += [self.scripts / name for name in ('usb_service_probe.py', 'jiritsu_version_read.py',
                     'jiritsu_preload_deploy.py', 'jiritsu_run_command.py', 'jiritsu_preload_clear.py')]
        required += [self.pmca / name for name in ('pmca/usb/sony.py', 'pmca/usb/crypto.py',
                     'pmca/usb/constants.py', 'pmca/usb/driver/generic/__init__.py',
                     'pmca/usb/driver/generic/libusb.py')]
        required += sorted(self.scripts.glob('*.py')) + sorted((self.pmca / 'pmca').rglob('*.py'))
        if action == 'root':
            payload = next((path for path in (self.scripts / PAYLOAD_NAME,
                           self.scripts / 'payload' / PAYLOAD_NAME,
                           self.scripts.parent / 'payload' / PAYLOAD_NAME) if path.is_file()), None)
            if payload is None:
                raise blocked('root_payload_missing', 'reviewed a7c2_shell.arm64.so is not installed')
            if hashlib.sha256(payload.read_bytes()).hexdigest() != PAYLOAD_SHA256:
                raise blocked('root_payload_mismatch', 'shell payload differs from the reviewed artifact')
            required.append(payload)
        return {str(path.resolve(strict=True)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in required}

    def verify(self, manifest, action):
        if self.manifest(action) != manifest:
            raise blocked('consumer_source_changed', 'consumer source/payload hashes changed across launch')

    def load(self, manifest, action):
        self.verify(manifest, action)
        sys.path.insert(0, str(self.scripts))
        sys.path.insert(0, str(self.pmca))
        probe = importlib.import_module('usb_service_probe')
        sony = importlib.import_module('pmca.usb.sony')
        generic = importlib.import_module('pmca.usb.driver.generic')
        libusb = importlib.import_module('pmca.usb.driver.generic.libusb')
        version = importlib.import_module('jiritsu_version_read')
        deploy = importlib.import_module('jiritsu_preload_deploy')
        runner = importlib.import_module('jiritsu_run_command')
        for name, module in tuple(sys.modules.items()):
            if name == 'usb_service_probe' or name.startswith(('pmca', 'jiritsu_')):
                filename = getattr(module, '__file__', None)
                if filename is None or str(Path(filename).resolve()) not in manifest:
                    raise blocked('unbound_consumer_module', f'unbound module {name}')
                if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != manifest[str(Path(filename).resolve())]:
                    raise blocked('consumer_source_changed', f'module changed during import: {name}')
        return probe, sony, generic, libusb, version, deploy, runner


def end_session(control, guard, auth, device, dispose, log, *, recovery_required=False):
    try:
        pending = recovery_required or control._load().get('preload_recovery_required', False)
    except Exception:
        pending = True
    if pending:
        log('connection_retained', reason='preload recovery is not verified; no Stop Senser/detach')
    elif auth is not None and device is not None:
        try:
            guard.check_device(device)
            auth.stop()
            log('stop_senser_requested')
            try:
                log('stop_identity_result', **guard.final_identity())
            except Exception as error:
                log('stop_identity_result', verified=False, code=getattr(error, 'code', 'stop_identity_unverified'),
                    detail=str(error))
        except Exception as error:
            log('stop_not_verified', detail=str(error))
    if device is not None and dispose is not None:
        try:
            dispose(device)  # Close only the libusb handle; never detach VHCI.
        except Exception as error:
            log('usb_handle_close_failed', detail=str(error))
    return pending


@contextmanager
def consumer_lock(control):
    path = control.context.run_dir / 'usb-jiritsu.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise blocked('unsafe_consumer_lock', 'consumer lock must be owned, private and regular')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise blocked('consumer_busy', 'another jiritsu consumer owns this run') from error
        yield
    finally:
        os.close(fd)


def consume(control, sources, action, manifest):
    """Child entry. Tests inject bounded fixtures, production always uses PyUSB."""
    try:
        with consumer_lock(control):
            return _consume(control, sources, action, manifest)
    except Exception as error:
        result = result_base(control, action)
        result['sources'] = manifest
        result['blocked_reason'] = {'code': getattr(error, 'code', 'consumer_failed'), 'detail': str(error)}
        try:
            result['preload_recovery_required'] = control._load().get('preload_recovery_required', False)
        except Exception:
            result['preload_recovery_required'] = True
        if result['preload_recovery_required']:
            result['phase'] = 'recovery_required'
        return result


def _consume(control, sources, action, manifest):
    result = result_base(control, action)
    result['sources'] = manifest
    current = backend = auth = None
    started = False
    usb_core = usb_util = None
    guard = None
    old_alarm = None

    def log(event, **fields):
        result['events'].append({'event': event, **fields})

    def deadline(*_):
        raise TimeoutError('real jiritsu consumer deadline exceeded')

    try:
        if action not in ACTIONS:
            raise blocked('unsupported_action', str(action))
        if action in ('root', 'recover') and not recovery_target_supported(control):
            raise blocked('control_recovery_api_missing', 'root/recover require jiritsu_target(..., allow_recovery=True)')
        guard = TargetGuard(control, recovery=action == 'recover')
        result['target'] = guard.current()
        if action == 'recover' and not control._load().get('preload_recovery_required'):
            raise blocked('no_recovery_required', 'no pending recovery for this owned connection')
        probe, sony, generic, libusb, version, deploy, runner = sources.load(manifest, action)
        import usb.core as usb_core
        import usb.util as usb_util

        class GuardedBackend(libusb.UsbBackend):
            def __init__(self, device):
                guard.check_device(device)
                super().__init__(device)
                self.dev.default_timeout = 30000

        # Calls and return values remain the real PMCA bulk/control operations.
        for name in ('reset', 'getEndpoints', 'getId', 'clearHalt', 'read', 'write',
                     'classInterfaceRequestOut', 'vendorRequestOut'):
            original = getattr(libusb.UsbBackend, name)
            def checked(self, *args, _method=original, **kwargs):
                guard.check_device(self.dev)
                return _method(self, *args, **kwargs)
            setattr(GuardedBackend, name, checked)

        class ObservedAuth(sony.SonySenserAuthDevice):
            def __init__(self, driver):
                super().__init__(driver)
                self.exchanges = []
                self.authentication_pid = driver.getId()[1]

            def _sendAuthPacket(self, command, data=b''):
                response = super()._sendAuthPacket(command, data)
                code, reply = response
                self.exchanges.append((command, code, reply))
                log('authentication_exchange', command=command, result=code, pid=self.authentication_pid,
                    reply_size=len(reply), success_byte=reply[0] if command == 5 and reply else None)
                return response

        def open_driver(device):
            guard.check_device(device)
            instance = GuardedBackend(device)
            instance.reset()  # Original PMCA: detach only this interface, no USB bus reset.
            guard.check_device(device)
            usb_util.claim_interface(device, 0)
            return instance, generic.GenericUsbDriver(instance)

        def authenticate(driver):
            nonlocal auth, started
            auth = ObservedAuth(driver)
            started = True
            auth.start()
            auth.authenticate()
            if not authentication_proven(auth.exchanges):
                raise blocked('authentication_result_missing', 'real final Senser result 6/success byte 1 was not observed')

        current = guard.find(usb_core.find)
        if current is None:
            raise blocked('libusb_target_missing', 'libusb returned no matching owned VHCI device')
        if action in ('version', 'root') and current.idProduct == 0x0e8a:
            guard.check_device(current)
            product = usb_util.get_string(current, current.iProduct)
            if product != 'ILCE-7CM2':
                raise blocked('unsupported_camera_product', repr(product))
        old_alarm = signal.signal(signal.SIGALRM, deadline)
        signal.alarm(180)
        backend, driver = open_driver(current)
        if current.idProduct == 0x0e8a:
            authenticate(driver)
            log('mass_storage_authentication_verified')
            usb_util.dispose_resources(current)
            current = None
            backend = None
            auth = None
            started = False
            guard, current = guard.follow_generation(usb_core.find, 0x0336)
            backend, driver = open_driver(current)
        authenticate(driver)
        result['authentication_verified'] = True
        result['target'] = guard.check_device(current)
        transport = sony.SonySenserDevice(driver)
        info = sony.SonySenserCamera(transport).readHasp()
        result['product_info'] = {'bytes': len(info), 'sha256': hashlib.sha256(info).hexdigest()}
        if action == 'version':
            content = version.read_version(transport, log)
            result['version'] = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
                                 'content_hex': content.hex()}
        if action == 'root':
            sources.verify(manifest, action)
            payload = probe.read_payload(PAYLOAD_NAME)
            if hashlib.sha256(payload).hexdigest() != PAYLOAD_SHA256:
                raise blocked('root_payload_mismatch', 'payload changed after preflight')
            control.mark_recovery_required('virtual jiritsu worker deployment starting')
            guard._arm_recovery()
            guard.check_device(current)
            commands = [probe.MOUNT_CARD_COMMAND, ROOT_COMMAND, probe.CLEANUP_COMMAND]
            value, record = deploy.deploy_and_run(
                transport, payload, log, approval=deploy.APPROVAL_TOKEN,
                payload_kind='shell', expected_sha256=PAYLOAD_SHA256,
                driver=runner.command_runner_driver(commands, interactive=False))
            result['deployment'] = record
            # Keep the original failure and latch; a record saying disarmed is insufficient.
            neutralize_preload(transport, control, guard, version, log)
            guard.recovery = False
            result['commands_json'] = value.decode('utf-8')
            result['root_status'] = root_from_commands(value)
            result['guest_root_verified'] = result['root_status'] is not None
            if not result['guest_root_verified']:
                raise blocked('guest_root_unverified', 'same-USB worker did not return four zero Uid and Gid columns')
        elif action == 'recover':
            neutralize_preload(transport, control, guard, version, log)
            guard.recovery = False
        result['phase'] = 'complete'
    except Exception as error:
        code = 'consumer_dependency_missing' if isinstance(error, ModuleNotFoundError) else 'consumer_failed'
        result['blocked_reason'] = {'code': getattr(error, 'code', code),
                                    'detail': f'{type(error).__name__}: {error}'}
        # The latch is armed BEFORE deployment; retain it even if cleanup raises.
        if type(error).__name__ == 'PreloadRecoveryRequired':
            try:
                control.mark_recovery_required(str(error))
            except Exception as latch_error:
                log('recovery_latch_error', detail=str(latch_error))
            result['preload_recovery_required'] = True
        # A capability armed before deployment may continue recovery after the
        # guest itself changes generation. It never detaches an active import.
        if guard is not None and guard.recovery and guard.capability is not None:
            try:
                record = control._load()
                if record.get('preload_recovery_required'):
                    receipt = control._import_receipt(record)
                    if (receipt.get('state') in ('retiring', 'retired') and
                            receipt.get('event_kind') in ('disconnect', 'device_changed')):
                        guard, current = guard.follow_generation(usb_core.find)
                        backend, driver = open_driver(current)
                        authenticate(driver)
                        transport = sony.SonySenserDevice(driver)
                        neutralize_preload(transport, control, guard, version, log)
                        guard.recovery = False
                        result['preload_recovery_required'] = False
                        log('generation_recovery_completed', original_error=result['blocked_reason'])
            except Exception as recovery_error:
                result['preload_recovery_required'] = True
                log('generation_recovery_failed', code=getattr(recovery_error, 'code', 'recovery_failed'),
                    detail=str(recovery_error))
    finally:
        if old_alarm is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_alarm)
        pending = end_session(control, guard, auth if started else None, current,
                              usb_util.dispose_resources if usb_util else None, log,
                              recovery_required=result['preload_recovery_required'])
        result['preload_recovery_required'] |= pending
        if result['preload_recovery_required']:
            result['phase'] = 'recovery_required'
    return result


class JiritsuConsumer:
    def __init__(self, control, *, scripts=SCRIPTS, pmca=None):
        self.control = control
        self.scripts = scripts
        self.pmca = pmca

    def run(self, action='authenticate'):
        result = result_base(self.control, action)
        try:
            if action not in ACTIONS:
                raise blocked('unsupported_action', str(action))
            if action in ('root', 'recover') and not recovery_target_supported(self.control):
                raise blocked('control_recovery_api_missing', 'root/recover require recovery-safe target validation')
            # The parent performs no enumeration and imports no USB consumer libraries.
            TargetGuard(self.control, recovery=action == 'recover')
            sources = Sources(self.scripts, self.pmca)
            manifest = sources.manifest(action)
            context = self.control.context
            request = {'action': action, 'sources': manifest, 'scripts': str(sources.scripts),
                       'pmca': str(sources.pmca), 'run_dir': str(context.run_dir),
                       'qmp_path': str(context.qmp_path), 'backend_path': str(context.backend_path),
                       'lease': context.lease, 'vm_pid': context.vm_pid, 'run_id': context.run_id}
            # -I ignores user PYTHONPATH/site customizations; secret lease travels on stdin.
            completed = subprocess.run([sys.executable, '-I', '-B', str(HERE / 'usb_jiritsu.py'), '--consumer'],
                                       input=json.dumps(request), capture_output=True, text=True,
                                       cwd=str(HERE), check=False)
            result['consumer_returncode'] = completed.returncode
            result['consumer_stdout'] = completed.stdout[-16384:]
            result['consumer_stderr'] = completed.stderr[-16384:]
            received = json.loads(completed.stdout, object_pairs_hook=usbip._object)
            if (not isinstance(received, dict) or received.get('schema') != result['schema'] or
                    any(received.get(name) != result[name] for name in ('run_id', 'lease_id', 'action')) or
                    received.get('sources') != manifest or completed.returncode not in (0, 2)):
                raise blocked('consumer_result_invalid', 'isolated consumer identity/source/result mismatch')
            events = received.get('events')
            if (type(received.get('authentication_verified')) is not bool or
                    type(received.get('guest_root_verified')) is not bool or not isinstance(events, list)):
                raise blocked('consumer_result_invalid', 'consumer verification flags/events are missing')
            if received['authentication_verified'] or received.get('phase') == 'complete':
                final = [event for event in events if isinstance(event, dict) and
                         event.get('event') == 'authentication_exchange' and event.get('pid') == 0x0336 and
                         event.get('command') == 5 and event.get('result') == 6 and
                         event.get('success_byte') == 1 and type(event.get('reply_size')) is int and
                         event['reply_size'] > 0]
                if not received['authentication_verified'] or not final:
                    raise blocked('authentication_result_missing', 'no actual final service authentication evidence')
            if received['guest_root_verified'] and (action != 'root' or not received['authentication_verified'] or
                    root_from_commands(received.get('commands_json')) is None):
                raise blocked('guest_root_unverified', 'no matching worker JSON /proc credentials')
            return received
        except Exception as error:
            result['blocked_reason'] = {'code': getattr(error, 'code', 'consumer_unavailable'),
                                        'detail': f'{type(error).__name__}: {error}'}
            try:
                result['preload_recovery_required'] = self.control._load().get('preload_recovery_required', False)
            except Exception:
                result['preload_recovery_required'] = True
            if result['preload_recovery_required']:
                result['phase'] = 'recovery_required'
            return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--consumer', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('action', nargs='?', choices=ACTIONS, default='authenticate')
    for name in ('run-dir', 'qmp', 'lease', 'backend', 'run-id', 'pmca'):
        parser.add_argument('--' + name)
    parser.add_argument('--vm-pid', type=int)
    args = parser.parse_args(argv)
    if args.consumer:
        # Never accept alternate sysfs/backend providers through the child protocol.
        request = json.loads(sys.stdin.read(1024 * 1024), object_pairs_hook=usbip._object)
        control = UsbControl(request['run_dir'], qmp_path=request['qmp_path'], lease=request['lease'],
                             vm_pid=request['vm_pid'], backend_path=request['backend_path'],
                             run_id=request['run_id'])
        result = consume(control, Sources(request['scripts'], request['pmca']),
                         request['action'], request['sources'])
    else:
        if not all((args.run_dir, args.qmp, args.lease, args.vm_pid)):
            parser.error('--run-dir, --qmp, --lease and --vm-pid are required')
        control = UsbControl(args.run_dir, qmp_path=args.qmp, lease=args.lease,
                             vm_pid=args.vm_pid, backend_path=args.backend, run_id=args.run_id)
        result = JiritsuConsumer(control, pmca=args.pmca).run(args.action)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['phase'] == 'complete' else 2


if __name__ == '__main__':
    sys.exit(main())
