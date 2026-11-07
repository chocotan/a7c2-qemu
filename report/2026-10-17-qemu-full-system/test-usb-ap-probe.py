#!/usr/bin/env python3
"""Owned USB/AP probe tests; protocol peers are local Unix socket fixtures."""
import asyncio
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
import struct
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'usb-ap-probe.py'))
NONCE = 'abcdef0123456789abcdef01'


class ProbeContracts(unittest.TestCase):
    def test_failed_observer_capture_is_private_readonly_diagnostic(self):
        from types import SimpleNamespace
        owner = SimpleNamespace(stdin=object(), poll=lambda: None)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); console = root / 'console.log'; console.write_bytes(b'original failure\n')
            raw = ('USB_AP_BEGIN_' + NONCE + '_baseline\nUSB_AP_START_TRACE_BEGIN\n'
                   'USB_START GUARD_FAILED reason=known original\nUSB_AP_START_TRACE_END\n'
                   'USB_AP_END_' + NONCE + '_baseline\n').encode()
            writes = []
            def write(_stream, wire):
                writes.append(wire)
                self.assertNotIn(b'inject-key', wire)
                with console.open('ab') as stream: stream.write(raw)
            with patch.object(API['secrets'], 'token_hex', return_value=NONCE), patch.dict(API['EXECUTOR'], write_console=write):
                result = API['capture_failure_observer'](owner, console, root)
            self.assertTrue(result['diagnostic_only']); self.assertTrue(result['received'])
            self.assertFalse(result['diagnostic_skipped_monitor']); self.assertEqual(len(writes), 1)
            self.assertEqual(Path(result['path']).read_bytes(), raw)
            self.assertEqual(Path(result['path']).stat().st_mode & 0o777, 0o600)
            self.assertTrue(console.read_bytes().startswith(b'original failure\n'))

    def test_failed_observer_monitor_preserves_boundary_without_shell_or_capture_success(self):
        from types import SimpleNamespace
        for body in (b'original abort\r\nEntering exception monitor.\r\nException> ',
                     b'original abort\nException> ',
                     b'Exception> first\nEntering exception monitor.\n'):
            for returncode in (None, 0, 2):
                with self.subTest(body=body, returncode=returncode), tempfile.TemporaryDirectory() as td:
                    root = Path(td); console = root / 'console.log'; console.write_bytes(body)
                    owner = SimpleNamespace(pid=941, stdin=object(), poll=Mock(return_value=returncode))
                    write = Mock(side_effect=AssertionError('No shell at Sony monitor'))
                    script = Mock(side_effect=AssertionError('No diagnostic script at Sony monitor'))
                    with patch.dict(API['EXECUTOR'], write_console=write), patch.dict(API['capture_failure_observer'].__globals__, capture_script=script):
                        result = API['capture_failure_observer'](owner, console, root)
                    write.assert_not_called(); script.assert_not_called(); owner.poll.assert_called_once()
                    self.assertTrue(result['diagnostic_only']); self.assertTrue(result['diagnostic_skipped_monitor'])
                    self.assertFalse(result['received']); self.assertNotIn('path', result)
                    self.assertEqual(result['console_sha256'], hashlib.sha256(body).hexdigest())
                    self.assertEqual(result['console_bytes'], len(body))
                    offset = min(body.find(marker) for marker in (b'Entering exception monitor', b'Exception>') if marker in body)
                    self.assertEqual(result['first_monitor']['byte_offset'], offset)
                    self.assertEqual(result['first_monitor']['line'], body.count(b'\n', 0, offset) + 1)
                    self.assertEqual(result['owner_state'], dict(pid=941, returncode=returncode, process_still_running=returncode is None))
                    saved = root / 'observer-failure-skipped-monitor.json'
                    self.assertEqual(json.loads(saved.read_text()), result)
                    self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(console.read_bytes(), body)
                    self.assertFalse((root / 'observer-failure.log').exists())

    def test_failed_observer_capture_timeout_or_dead_owner_does_not_mask_failure(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); console = root / 'console.log'; console.write_bytes(b'original failure\n')
            with patch.dict(API['EXECUTOR'], write_console=lambda *_: None), patch.object(API['time'], 'monotonic', side_effect=[0, 6]):
                result = API['capture_failure_observer'](SimpleNamespace(stdin=object(), poll=lambda: None), console, root)
            self.assertFalse(result['received']); self.assertIn('deadline', result['capture_error'])
            self.assertFalse((root / 'observer-failure.log').exists())
            self.assertFalse(API['capture_failure_observer'](None, console, root)['received'])
            self.assertEqual(console.read_bytes(), b'original failure\n')

    def test_phase_markers_require_actual_guest_output(self):
        script = API['capture_script']('baseline', NONCE).encode()
        self.assertIsNone(API['phase_bytes'](script, 'baseline', NONCE))
        begin = b'USB_AP_BEGIN_' + NONCE.encode() + b'_baseline\r\n'
        end = b'USB_AP_END_' + NONCE.encode() + b'_baseline\r\n'
        raw = begin + b'  100: 0 2 0 0 GICv2 100 Edge vbus0\r\n' + end
        self.assertEqual(API['phase_bytes'](script + raw, 'baseline', NONCE), raw.replace(b'\r', b''))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            API['phase_bytes'](raw + raw, 'baseline', NONCE)
        with self.assertRaisesRegex(ValueError, 'Reversed'):
            API['phase_bytes'](end + begin, 'baseline', NONCE)
        for phase, nonce in [('on', NONCE), ('baseline', 'bad\nvalue')]:
            with self.assertRaises(ValueError):
                API['capture_script'](phase, nonce)

    def test_original_interrupt_domain_and_failed_function_read_are_preserved(self):
        raw = b'''USB_AP_INTERRUPTS
  28: 0 0 3 0 GIC-0 100 Edge vbus0
  29: 0 0 0 0 GICv2 99 Edge vbus1
USB_AP_UDC_FIELD=state
not attached
USB_AP_FIELD_RC=0
USB_AP_UDC_FIELD=function
USB_AP_FIELD_RC=0
USB_AP_UDC_FIELD=maximum_speed
cat: permission denied
USB_AP_FIELD_RC=1
USB_HOST=0
USB=1
'''
        result = API['inspect_phase'](raw)
        self.assertEqual(result['irq']['vbus0'], dict(linux_irq=28, counts=[0, 0, 3, 0]))
        self.assertEqual(result['udc_fields']['function'], dict(value='', rc=0))
        self.assertEqual(result['udc_fields']['maximum_speed']['rc'], 1)
        self.assertEqual(result['extcon_states'], ['USB_HOST=0', 'USB=1'])
        self.assertIsNone(result['bound_driver'])
        driver = b'USB_AP_UDC_FIELD=uevent\nUSB_UDC_DRIVER=usb_gadgetcore\nUSB_AP_FIELD_RC=0\n'
        with_driver = API['inspect_phase'](raw + driver)
        self.assertEqual(with_driver['bound_driver'], 'usb_gadgetcore')
        self.assertIsNone(API['inspect_phase'](raw + driver.replace(b'FIELD_RC=0', b'FIELD_RC=1'))['bound_driver'])
        self.assertIsNone(API['inspect_phase'](raw + b'OBS USB_UDC_DRIVER=fake\n')['bound_driver'])
        self.assertIsNone(API['inspect_phase'](raw + driver.replace(b'USB_AP_FIELD_RC', b'USB_UDC_DRIVER=a\nUSB_AP_FIELD_RC'))['bound_driver'])

    def test_function_bound_requires_exact_original_function_and_driver(self):
        for function in ('', 'OBS fake', 'OBS note\nusb_gadgetcore', 'usb_gadgetcore\nOBS note', 'unknown'):
            phase = dict(udc_fields={'function': dict(value=function, rc=0)}, bound_driver='usb_gadgetcore')
            self.assertFalse(API['original_function_bound'](phase))
        phase = dict(udc_fields={'function': dict(value='usb_gadgetcore', rc=0)}, bound_driver='usb_gadgetcore')
        self.assertTrue(API['original_function_bound'](phase))
        for driver in (None, 'OBS usb_gadgetcore', 'unknown'):
            self.assertFalse(API['original_function_bound'](dict(phase, bound_driver=driver)))
        phase['udc_fields']['function']['rc'] = 1
        self.assertFalse(API['original_function_bound'](phase))

    def test_baseline_reads_real_ap_sha_and_pid_for_strict_collector(self):
        script = API['capture_script']('baseline', NONCE)
        self.assertIn('/usr/bin/openssl dgst -sha256 /usr/lib/appFw.so', script)
        self.assertIn('COLD_AP_MAP pid=${p##*/} sha256=' + API['EXECUTOR']['APPFW_SHA256'], script)
        self.assertIn('grep -q /usr/lib/appFw.so "$p/maps"', script)
        self.assertIn('cat "$p/maps"', script)
        self.assertNotIn('COLD_AP_MAP', API['capture_script']('vbus_on', NONCE))

    def test_msc_selection_uses_normal_press_and_release_with_fixed_delay(self):
        script = API['capture_script']('msc_selected', NONCE)
        self.assertEqual(script.count('/simulation/inject-key '), 2)
        self.assertIn('0x1ac 0 1 0 1\npressed=$?\nsleep 0.05\n', script)
        self.assertIn('0x1ac 0 0 0 1\nreleased=$?', script)
        self.assertIn('USB_AP_ENTER_RELEASE_RC=$released', script)
        self.assertNotIn('inject-key', API['capture_script']('vbus_on', NONCE))
        self.assertNotIn('--app', script)
        self.assertNotIn('ioctl', script)

    def test_driver_requires_successful_exact_uevent_and_symlink(self):
        raw = b'''USB_AP_UDC_FIELD=function
usb_gadgetcore
USB_AP_FIELD_RC=0
USB_AP_GADGET_UEVENT
DRIVER=usb_gadgetcore
USB_AP_GADGET_UEVENT_RC=0
USB_AP_GADGET_DRIVER
../../../../bus/gadget/drivers/usb_gadgetcore
USB_AP_GADGET_DRIVER_RC=0
'''
        self.assertTrue(API['original_function_bound'](API['inspect_phase'](raw)))
        both = raw + b'USB_AP_UDC_FIELD=uevent\nUSB_UDC_DRIVER=usb_gadgetcore\nUSB_AP_FIELD_RC=0\n'
        self.assertTrue(API['original_function_bound'](API['inspect_phase'](both)))
        for changed in (
                raw.replace(b'UEVENT_RC=0', b'UEVENT_RC=1'),
                raw.replace(b'DRIVER_RC=0', b'DRIVER_RC=1'),
                raw.replace(b'DRIVER=usb_gadgetcore', b'DRIVER=usb_gadgetcore-extra'),
                raw.replace(b'../../../../bus', b'OBS noise\n../../../../bus'),
                raw.replace(b'../../../../bus/gadget/drivers', b'../../../../bus/platform/drivers'),
                raw.replace(b'../../../../bus/gadget/drivers', b'/fake'),
                raw + raw):
            self.assertFalse(API['original_function_bound'](API['inspect_phase'](changed)))

    def test_pm_readback_requires_real_sysfs_and_same_canonical_udc_device(self):
        device = '/sys/devices/platform/soc/f1080000.usbs/f10c0000.usb'
        fields = {'USB_AP_SERVICE_POWER_CONTROL': 'auto',
                  'USB_AP_SERVICE_SYSFS_MOUNT': 'none /sys sysfs rw,relatime 0 0',
                  'USB_AP_UDC_CLASS_LINK': '../../devices/platform/soc/f1080000.usbs/f10c0000.usb/udc/f10c0000.usb'}
        raw = ''.join(marker + '\n' + value + '\n' + marker + '_RC=0\n' for marker, value in fields.items()).encode()
        self.assertTrue(API['service_pm_path_verified'](API['inspect_phase'](raw)))
        for bad in (raw.replace(b'auto', b'on'), raw.replace(b' sysfs ', b' tmpfs '),
                    raw.replace(b'/soc/', b'/wrong/'), raw.replace(b'_RC=0', b'_RC=1'),
                    raw + raw, b'OBS ' + raw, b''):
            self.assertFalse(API['service_pm_path_verified'](API['inspect_phase'](bad)))
        failed = b'USB_AP_SERVICE_POWER_CONTROL\ncat: missing\nUSB_AP_SERVICE_POWER_CONTROL_RC=1\n'
        self.assertEqual(API['inspect_phase'](failed)['service_power_control']['value'],
                         [dict(value='cat: missing', rc=1)])
        script = API['capture_script']('msc_selected', NONCE)
        self.assertIn('cat ' + device + '/power/control', script)
        self.assertIn(' /sys sysfs ', script)
        self.assertIn('$bb readlink "$p"', script)
        self.assertNotIn('readlink -f', script)
        self.assertNotIn('$bb stat', script)
        self.assertNotIn('echo auto', script)

    def test_monitor_readbacks_keep_failed_rc_and_exact_fd_owners(self):
        raw = b'''usb_portMonitor 65536 0 - Live 0x0000 (PO)
USB_AP_MONITOR_FIELD=initstate
live
USB_AP_MONITOR_RC=0
USB_AP_MONITOR_FIELD=parameters/update_type
cat: permission denied
USB_AP_MONITOR_RC=1
USB_AP_FD=/proc/622/fd/12:/dev/usb/portMonitor
OBS USB_AP_FD=/proc/1/fd/7:/dev/usb/event
'''
        result = API['inspect_phase'](raw)
        self.assertTrue(result['monitor_module_loaded'])
        self.assertEqual(result['monitor_fields']['initstate'], dict(value='live', rc=0))
        self.assertEqual(result['monitor_fields']['parameters/update_type']['rc'], 1)
        self.assertEqual(result['usb_fds'], [dict(pid=622, fd=12, target='/dev/usb/portMonitor')])
        self.assertFalse(API['inspect_phase'](b'OBS usb_portMonitor 65536 0 - Live')['monitor_module_loaded'])

    def test_collector_drift_is_rejected_before_owner_start(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(API['execute'].__globals__, EXECUTOR_SHA256='0' * 64):
                with self.assertRaisesRegex(ValueError, 'collector changed'):
                    API['execute']({}, {}, Path(folder) / 'evidence')
            self.assertFalse((Path(folder) / 'evidence').exists())

    def test_receipt_updates_are_private_and_complete(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'result.json'
            API['save'](path, {'stage': 1})
            API['save'](path, {'stage': 2})
            self.assertEqual(json.loads(path.read_text()), {'stage': 2})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(root).iterdir()), [path])

    def test_paced_heredoc_is_ascii_and_does_not_write_gadget_sysfs(self):
        for phase in API['PHASES']:
            script = API['capture_script'](phase, NONCE)
            script.encode('ascii')
            self.assertLessEqual(max(map(len, script.splitlines())), 512)
            self.assertNotIn(' >', script)
            self.assertNotIn('chmod', script)
            self.assertNotIn('insmod', script)
            self.assertNotIn('/proc/usb_otg', script)
            self.assertIn('/proc/udm/fusb', script)
            wire = API['EXECUTOR']['diagnostic_envelope'](script, 'PROBE')
            self.assertTrue(wire.startswith("busybox sh <<'PROBE'\n"))

    def test_original_fusb_callback_sequence_active_high_and_spi68(self):
        usb = API['USB']
        platform = usb['PLATFORM_C']
        callbacks = platform.split('#include "hw/core/irq.h"\n', 1)[1].split('#define SONY_USB_POWER_CALLBACKS', 1)[0]
        request = 'static void sony_usb_vbus_request' + platform.split('static void sony_usb_vbus_request', 1)[1].split('static void sony_usb_platform_create', 1)[0]
        prefix = r'''
#include <assert.h>
#include <stdio.h>
#include <inttypes.h>
typedef uint64_t hwaddr;
typedef int MemTxResult;
typedef int MemTxAttrs;
typedef int MemoryRegion;
typedef struct Irq { int level; unsigned pulses; } Irq;
typedef Irq *qemu_irq;
#define HWADDR_PRIx PRIx64
#define MEMTX_OK 0
#define MEMTX_ERROR 1
#define LOG_GUEST_ERROR 1
#define qemu_log_mask(...) ((void)0)
static void qemu_set_irq(qemu_irq irq, int level) { irq->level = level; }
static void qemu_irq_pulse(qemu_irq irq) { irq->pulses++; }
#pragma GCC diagnostic ignored "-Wunused-parameter"
#pragma GCC diagnostic ignored "-Wunused-function"
'''
        fixture = r'''
int main(void) {
    Irq irq = {0}, controller = {0};
    SonyUsbPlatform p = {.vbus_irq=&irq, .controller_vbus=&controller};
    const uint32_t bit=1u<<12;
    /* Original gpio-sn input/peripheral configuration; VBUS is not active-low. */
    assert(sony_usb_gpio_write(&p, 0x24, bit, 4, 0) == MEMTX_OK);
    assert(sony_usb_gpio_write(&p, 0x08, bit, 4, 0) == MEMTX_OK);
    assert(sony_usb_gpio_write(&p, 0x38, bit, 4, 0) == MEMTX_OK);
    sony_usb_vbus_request(&p, 0, 1);
    assert(!irq.pulses && controller.level == 1);
    sony_usb_vbus_request(&p, 0, 0);
    /* Original fusb_setup_gpioint: positive, edge, high and low enabled. */
    assert(sony_usb_int_write(&p, 0x08, bit, 4, 0) == MEMTX_OK);
    assert(sony_usb_int_write(&p, 0x18, bit, 4, 0) == MEMTX_OK);
    assert(sony_usb_int_write(&p, 0x24, bit, 4, 0) == MEMTX_OK);
    assert(sony_usb_int_write(&p, 0x34, bit, 4, 0) == MEMTX_OK);
    uint64_t value;
    sony_usb_vbus_request(&p, 0, 1);
    assert(sony_usb_gpio_read(&p, 0x10, &value, 4, 0) == MEMTX_OK && value == bit);
    assert(irq.pulses == 1 && controller.level == 1);
    sony_usb_vbus_request(&p, 0, 1);
    assert(irq.pulses == 1);
    assert(sony_usb_gpio_write(&p, 0x10, bit | (1u<<18), 4, 0) == MEMTX_OK);
    assert(irq.pulses == 1 && p.present);
    sony_usb_vbus_request(&p, 0, 0);
    assert(irq.pulses == 2 && controller.level == 0);
    assert(sony_usb_gpio_read(&p, 0x10, &value, 4, 0) == MEMTX_OK && value == (1u<<18));
    assert(sony_usb_int_write(&p, 0x28, bit, 4, 0) == MEMTX_OK);
    sony_usb_vbus_request(&p, 0, 1);
    assert(irq.pulses == 2); /* Rising edge really disabled. */
    assert(sony_usb_int_write(&p, 0x38, bit, 4, 0) == MEMTX_OK);
    sony_usb_vbus_request(&p, 0, 0);
    assert(irq.pulses == 2); /* Falling edge really disabled. */
    return 0;
}
'''
        host = runpy.run_path(str(HERE / 'test-usb-device-profile.py'))['HostCModels']()
        host.compile_run(prefix + usb['PHY_MODEL_C'] + callbacks + request + fixture)
        # Original non-FPGA IRQ_GPIO_BASE88 + GPIO17.12 = INTID100 / SPI68.
        self.assertIn('qdev_get_gpio_in(gic, 68)', platform)

    def test_debugger_snapshot_excludes_cpu_context_dependent_gic(self):
        self.assertTrue(all(not 0x08000000 <= address < 0x08020000 for address in API['REGISTERS']))
        self.assertIn('$bb devmem 0x0800010c 32', API['capture_script']('baseline', NONCE))

    def test_qmp_owner_requires_current_uid_and_real_pid(self):
        class Connection:
            def __init__(self, pid, uid):
                self.pid, self.uid = pid, uid
            def getsockopt(self, *args):
                self.args = args
                return struct.pack('3i', self.pid, self.uid, 0)
        self.assertEqual(API['peer_pid'](Connection(os.getpid(), os.getuid())), os.getpid())
        for pid, uid in [(0, os.getuid()), (os.getpid(), os.getuid() + 1)]:
            with self.assertRaisesRegex(ValueError, 'owner'):
                API['peer_pid'](Connection(pid, uid))


class FunctionalContracts(unittest.TestCase):
    def setUp(self):
        self.start = runpy.run_path(str(HERE / 'usb-start-observe.py'))
        self.model = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
        self.contract = dict(ee_observer=dict(self.model['CONTRACT'], source_sha256=hashlib.sha256((HERE / 'usb-ee-zero-observe.inc').read_bytes()).hexdigest()),
            ee_normal_cold=dict(profile=API['FUNCTIONAL_MODE'], generation=7,
                private_inputs=[dict(role='ee-private-envelope', sha256='a' * 64), dict(role='ee-private-model', sha256='b' * 64)]))

    def trace(self):
        mode = API['FUNCTIONAL_MODE']
        lines = ['USB_START INITIALIZED tid=11 pid=11 passive=0 functional_model=1 mode=' + mode]
        def ee(event, body, tid=11):
            if event != 'PREINIT':
                body = 'pid=11 ' + body
            lines.append(f'USB_EE {event} tid={tid} mono=1.{len(lines):09d} clock_ok=1 {body}')
        ee('PREINIT', f'pid=11 app_base=0x100000 uipc_base=0x200000 installed=8 ee_can_publish=0 functional_model=1 mode={mode}')
        lines.append('USB_START AP_PREINIT_CONFIRMED tid=11 pid=11 base=0x100000 resolved=0x300000 both_entries=1')
        ee('QUEUE_ENTER', 'queue=0x80020002 handle_out=0x7000 callback=0 context=0 caller=0x1000')
        ee('QUEUE_RETURN', 'queue=0x80020002 handle_out=0x7000 handle=0 handle_read=1 callback=0 context=0 caller=0x1000 rc=0 errno=0')
        ee('RECV_ENTER', 'queue=0x80020002 output=0x8000 timeout=-1 caller=0x1000', 22)
        ee('FUNCTIONAL_GATE', f'mode={mode} handle=0 callback=0 context=0 receiver_tid=0x16 promise=0x3344 reader=0x3649218 registration_event=1 unlock_event=2 original_rc=0 original_20a3_return=1 original_wait_unlocked=1 envelope_sha256=' + 'a' * 64 + ' model_sha256=' + 'b' * 64)
        prefix = f'mode={mode} generation=7 '
        ee('FUNCTIONAL_ALLOCATE_ENTER', prefix + 'destination=0x80020002 bytes=12 flags=1')
        ee('FUNCTIONAL_ALLOCATE_RETURN', prefix + 'destination=0x80020002 message=0x123400 rc=0 errno=0')
        ee('FUNCTIONAL_SEND_ENTER', prefix + 'destination=0x80020002 message=0x123400')
        ee('RECV_RETURN', 'queue=0x80020002 output=0x8000 message=0x123400 message_read=1 caller=0x1000 rc=0 errno=0', 22)
        ee('SOURCE', 'queue=0x80020002 message=0x123400 source=0x90bf0274 caller=0x1000', 22)
        ee('SIZE', 'queue=0x80020002 message=0x123400 source=0x90bf0274 source_known=1 size=12 copy12=1 raw=0600a3200000000000000000 caller=0x1000', 22)
        def snapshot(event, tid, **changes):
            state = dict(rc=0, attempted=1, allocated=1, send_called=1, send_returned=0, send_rc=0,
                received=1, reader=0, output=0, free=0, free_rc=0, retired=0, pending=1, fault=0,
                strict_can_publish=0, functional_model=1, message='0x123400', current='3,6', reason=1, raw=0,
                actual_wire='0600a3200000000000000000', actual_source='0x90bf0274', actual_bytes=12,
                actual_consumer='0x16', free_owner=0, stage_actual=0)
            state.update(changes)
            ee('FUNCTIONAL_' + event, prefix + ' '.join(f'{k}={v}' for k, v in state.items()), tid)
        snapshot('RECEIVE', 22)
        ee('FREE_ENTER', 'owner=0x80020002 message=0x123400 recv_match=1 source=0x90bf0274 source_known=1 size=12 size_known=1 caller=0x1000', 22)
        ee('FREE_RETURN', 'owner=0x80020002 message=0x123400 recv_match=1 caller=0x1000 rc=0 errno=0', 22)
        snapshot('FREE', 22, free=1, free_owner='0x80020002')
        ee('FUNCTIONAL_SEND_RETURN', prefix + 'destination=0x80020002 message=0x123400 rc=0 errno=0')
        snapshot('TRIGGER', 11, send_returned=1, free=1, free_owner='0x80020002')
        ee('PROMISE_REGISTER', 'id=0x20a3 id_source=guarded_caller map=0x123 key=0x456 caller=0x36492bc return_x0=1 return_x1=1 deferred_until_unlock=1')
        ee('WAIT_ENTER', 'id=0x20a3 future=0x3344 caller=0x36492cc first=1 after_original_unlock=1')
        ee('WAIT_RETURN', 'id=0x20a3 future=0x3344 caller=0x36492cc return_x0=1 errno=0')
        snapshot('READER', 11, send_returned=1, reader=1, output=1, free=1, free_owner='0x80020002', retired=1, pending=0)
        return ('\n'.join(lines) + '\n').encode()

    def capture(self, trace, *, cat_rc=0):
        sha = hashlib.sha256(trace).hexdigest()
        path = '/dev/qemu-simulation/usb-start-observe.log'
        return (f'USB_AP_START_TRACE_SHA_BEFORE\nSHA256({path})= {sha}\nUSB_AP_START_TRACE_SHA_BEFORE_RC=0\n'.encode() +
            b'USB_AP_START_TRACE_BEGIN\n' + trace + f'USB_AP_START_TRACE_RC={cat_rc}\nUSB_AP_START_TRACE_END\n'.encode() +
            f'USB_AP_START_TRACE_SHA_AFTER\nSHA256({path})= {sha}\nUSB_AP_START_TRACE_SHA_AFTER_RC=0\n'.encode())

    def summary(self, trace=None, **kwargs):
        return API['functional_trace_summary'](self.capture(self.trace() if trace is None else trace), self.contract, **kwargs)

    def test_explicit_functional_and_zero_guards(self):
        def mode(contract=None, **changes):
            options = dict(observe_start=True, camera_profile=self.start['PROFILE'], seconds=120)
            options.update(changes)
            return API['observer_mode'](self.contract if contract is None else contract, **options)
        self.assertEqual(mode(), API['FUNCTIONAL_MODE'])
        zero = dict(ee_observer=dict(self.start['EE_CONTRACT'], source_sha256=self.contract['ee_observer']['source_sha256']))
        self.assertEqual(mode(zero), API['ZERO_MODE'])
        self.assertEqual(mode({}), 'passive')
        self.assertEqual(mode({}, observe_start=False), 'off')
        for change in (dict(observe_start=False), dict(seconds=121), dict(seconds=9), dict(camera_profile='virtual-functional-camera-v1')):
            with self.subTest(change=change), self.assertRaises(ValueError): mode(**change)
        for bad in (dict(self.contract, ee_normal_cold=None), dict(self.contract, ee_observer=None),
                    dict(self.contract, ee_observer=dict(self.contract['ee_observer'], profile=API['FUNCTIONAL_MODE']+'-extra')),
                    dict(self.contract, ee_observer=dict(self.contract['ee_observer'], ee_can_publish=True)),
                    dict(zero, ee_normal_cold=self.contract['ee_normal_cold'])):
            with self.assertRaises(ValueError): mode(bad)
        with self.assertRaisesRegex(ValueError, 'Explicit validated'):
            API['execute']({}, {}, '/not-created', observe_start=True)
        with self.assertRaisesRegex(ValueError, 'differs'):
            API['execute']({'camera_profile': self.start['PROFILE']}, {}, '/not-created', observe_start=True,
                           observer_mode_verified=API['ZERO_MODE'], observer_contract=self.contract)

    def test_complete_private_bindings_reach_launch_recheck_and_drift_refuses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / 'full-system.json'; manifest.write_text(json.dumps(dict(usb_start_observe=self.contract)))
            inputs = []
            for n in range(24):
                path = root / str(n); path.write_bytes(b'host binding fixture')
                inputs.append(dict(role=f'private-or-source-{n}', path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            original_run = runpy.run_path
            def run(path):
                if Path(path).name == 'usb-start-observe.py':
                    return dict(self.start, validate=lambda _: inputs)
                return original_run(path)
            with patch.object(API['runpy'], 'run_path', side_effect=run):
                mode, contract, bindings = API['verified_observer'](root, observe_start=True, camera_profile=self.start['PROFILE'], seconds=120)
                self.assertEqual(mode, API['FUNCTIONAL_MODE']); self.assertEqual(contract, self.contract)
                self.assertEqual(len(bindings), 25)
                self.assertTrue(all('bytes' in b for b in bindings))
                Path(inputs[12]['path']).write_bytes(b'changed private input')
                with self.assertRaisesRegex(ValueError, 'binding changed'):
                    API['verified_observer'](root, observe_start=True, camera_profile=self.start['PROFILE'], seconds=120)

    def test_native_send_receive_reader_and_free_match_same_lease(self):
        result = self.summary()
        self.assertTrue(result['business_complete'], result)
        self.assertTrue(result['native_message_released']); self.assertTrue(result['resource_safe_to_close'])
        self.assertEqual(result['message'], '0x123400'); self.assertEqual(result['generation'], 7)
        for name in ('stage_actual', 'original_cp_history_verified', 'physical_compatibility_verified', 'full_boot_verified', 'capture_verified'):
            self.assertFalse(result[name])
        self.assertEqual(result['strict_can_publish'], 0)
        diagnostic = self.summary(diagnostic_only=True)
        self.assertTrue(diagnostic['native_content_verified']); self.assertFalse(diagnostic['business_complete'])
        self.assertTrue(diagnostic['native_message_released'])
        # Native source and size callbacks may legitimately be observed in either order.
        lines = self.trace().splitlines(keepends=True)
        source = next(i for i, line in enumerate(lines) if line.startswith(b'USB_EE SOURCE '))
        size = next(i for i, line in enumerate(lines) if line.startswith(b'USB_EE SIZE '))
        lines[source], lines[size] = lines[size].replace(b'source=0x90bf0274 source_known=1', b'source=0 source_known=0').replace(b'copy12=1 raw=0600a3200000000000000000', b'copy12=0 raw=unavailable'), lines[source]
        self.assertTrue(self.summary(b''.join(lines))['business_complete'])

    def test_retired_or_send_zero_does_not_replace_original_content_and_free(self):
        trace = self.trace()
        for changed in (trace.replace(b'USB_EE FREE_RETURN ', b'OBS FREE_RETURN '),
                        trace.replace(b'USB_EE FREE_ENTER ', b'OBS FREE_ENTER '),
                        trace.replace(b'owner=0x80020002 message=0x123400 recv_match=1 caller=0x1000 rc=0', b'owner=0x80020002 message=0x123400 recv_match=1 caller=0x1000 rc=-28'),
                        trace.replace(b'FUNCTIONAL_ALLOCATE_RETURN ', b'OBS_ALLOCATE_RETURN '),
                        trace.replace(b'generation=7', b'generation=8'),
                        trace.replace(b'USB_EE FREE_RETURN', b'USB_EE FREE_RETURN garbage'),
                        trace + b'USB_EE CAP bounded=1\n', trace + b'USB_START CAP bounded=1\n'):
            with self.subTest(changed=hashlib.sha256(changed).hexdigest()):
                summary = self.summary(changed)
                self.assertFalse(summary['business_complete']); self.assertFalse(summary['resource_safe_to_close'])
        for fragment in (b'FUNCTIONAL_ALLOCATE_ENTER ', b'FUNCTIONAL_SEND_ENTER ', b'FREE_RETURN '):
            row = next(line for line in trace.splitlines(keepends=True) if b'USB_EE ' + fragment in line)
            self.assertFalse(self.summary(trace + row)['business_complete'])
        send_return = next(line for line in trace.splitlines() if line.startswith(b'USB_EE FUNCTIONAL_SEND_RETURN '))
        for before, after in ((b'actual_wire=0600a3200000000000000000', b'actual_wire=0600a3200000000001000000'),
                              (b'actual_source=0x90bf0274', b'actual_source=0x90bf0275'),
                              (b'actual_bytes=12', b'actual_bytes=13'),
                              (b'actual_consumer=0x16', b'actual_consumer=0x17'),
                              (b'registration_event=1 unlock_event=2', b'registration_event=2 unlock_event=1'),
                              (b'reader=1 output=1', b'reader=1 output=2'),
                              (b'retired=1 pending=0', b'retired=0 pending=1'),
                              (send_return, send_return.replace(b'rc=0', b'rc=-28'))):
            summary = self.summary(trace.replace(before, after))
            self.assertFalse(summary['business_complete'], (before, summary))
            self.assertTrue(summary['native_message_released'], (before, summary))

    def test_private_input_drift_rejected_by_real_lower_validator(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            model = dict(schema=1, profile=API['FUNCTIONAL_MODE'], generation=7, force_e0=0,
                         be9bae_byte9=0, stable_state_hex='00' * 16, adc_hex='00' * 48)
            paths = dict(backup=root / 'backup', cp=root / 'cp', model=root / 'model.json',
                         envelope=root / 'private-ee-normal-cold-input.json', header=root / 'private-ee-normal-cold-input.h')
            bindings = []
            for role, path in paths.items():
                path.write_bytes(json.dumps(model).encode() if role == 'model' else b'private host fixture')
                path.chmod(0o600)
                bindings.append(dict(role='ee-private-' + role, path=str(path), bytes=path.stat().st_size,
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            private = dict(profile=API['FUNCTIONAL_MODE'], generation=7, admission_source='callback',
                admission_version=1, kernel_uipc=None, strict_can_publish=False,
                native_allocation_log_commit_required=True, native_allocation_log_commit_version=1, diagnostic_checkpoints=False,
                stage_actual=False, model_defined=15, original_cp_history_verified=False, rows_bytes=64,
                public_sources={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in self.model['PUBLIC']},
                private_inputs=bindings, private_header=str(paths['header']))
            contract = dict(self.contract, ee_normal_cold=private,
                loader_map_sha256=self.start['digest'](HERE / 'usb-start-observe.map'),
                command=['-Wl,--version-script=' + str(HERE / 'usb-start-observe.map')])
            (root / 'full-system.json').write_text(json.dumps(dict(usb_start_observe=contract)))
            paths['cp'].write_bytes(b'drifted private host fixture')
            with self.assertRaisesRegex(ValueError, 'private input identity drift: ee-private-cp'):
                API['verified_observer'](root, observe_start=True, camera_profile=self.start['PROFILE'], seconds=120)

    def test_original_event_aliases_and_missing_wait_are_business_failures(self):
        trace = self.trace()
        for event in ('RECV_ENTER', 'QUEUE_ENTER', 'PROMISE_REGISTER', 'WAIT_ENTER', 'WAIT_RETURN'):
            changed = b'\n'.join(line for line in trace.splitlines() if not line.startswith(('USB_EE ' + event + ' ').encode())) + b'\n'
            result = self.summary(changed)
            self.assertFalse(result['business_complete'], (event, result))
            self.assertTrue(result['native_message_released'], (event, result))
        for before, after in ((b'reader=0x3649218', b'reader=0x364921c'),
                              (b'future=0x3344', b'future=0x3345'),
                              (b'caller=0x36492bc', b'caller=0x36492b8'),
                              (b'recv_match=1', b'recv_match=0')):
            result = self.summary(trace.replace(before, after))
            self.assertFalse(result['business_complete'], (before, result))
        free = next(line for line in trace.splitlines() if line.startswith(b'USB_EE FREE_RETURN '))
        self.assertFalse(self.summary(trace.replace(free, free.replace(b'message=0x123400', b'message=0x123408')))['resource_safe_to_close'])

    def test_complete_trace_digests_required_for_no_allocation_or_content(self):
        no_allocation = b'\n'.join(line for line in self.trace().splitlines() if not line.startswith(b'USB_EE ') or line.startswith(b'USB_EE PREINIT ')) + b'\n'
        summary = self.summary(no_allocation)
        self.assertFalse(summary['no_allocation_proven'], summary); self.assertFalse(summary['resource_safe_to_close']); self.assertFalse(summary['business_complete'])
        self.assertIn('full-write contract is unproven', summary['error'])
        for trace in (self.trace(), no_allocation):
            raw = self.capture(trace)
            for bad in (raw.replace(b'USB_AP_START_TRACE_SHA_BEFORE\n', b'OBS\n'),
                        raw.replace(b'SHA_AFTER_RC=0', b'SHA_AFTER_RC=1'), raw + raw,
                        raw.replace(b'USB_START INITIALIZED', b'USB_START XNITIALIZED'),
                        self.capture(trace, cat_rc=1), raw.replace(b'ee_can_publish=0', b'ee_can_publish=1')):
                result = API['functional_trace_summary'](bad, self.contract)
                self.assertFalse(result['resource_safe_to_close'], result)
                self.assertFalse(result['business_complete'])
        self.assertFalse(self.summary(b'')['no_allocation_proven'])
        guard = self.trace().splitlines(keepends=True)[0] + b'USB_START GUARD_FAILED tid=11 reason=EE UIPC original path/size/SHA256\n'
        self.assertFalse(self.summary(guard)['no_allocation_proven'])
        self.assertFalse(self.summary(guard.replace(b'EE UIPC original path/size/SHA256', b'unknown later failure'))['no_allocation_proven'])
        script = API['capture_script']('baseline', NONCE, observe_start=True)
        self.assertEqual(script.count('openssl dgst -sha256 /dev/qemu-simulation/usb-start-observe.log'), 2)
        self.assertNotIn('inject-key', script)

    def execute_failure(self, diagnostic, *, functional=True):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            disk = root / 'disk'; disk.write_bytes(b'exclusively leased local fixture')
            with disk.open('rb') as leased, disk.open('rb') as contender:
                fcntl.flock(leased, fcntl.LOCK_EX | fcntl.LOCK_NB)
                alive = [True]; waits = []; commands = []
                owner = SimpleNamespace(pid=os.getpid(), returncode=None, stdin=Mock(), kill=Mock(), terminate=Mock(), send_signal=Mock())
                owner.poll = lambda: None if alive[0] else owner.returncode
                def wait(*args, **kwargs):
                    waits.append((args, kwargs))
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    if not kwargs:
                        retained = json.loads((root / 'evidence/owner-retained.json').read_text())
                        self.assertEqual(retained['owner']['owner_identity']['pid'], os.getpid())
                        self.assertTrue(retained['owner']['disk_lease_held'])
                        self.assertEqual(commands, [])
                        self.assertFalse((root / 'evidence/owner-exit.json').exists())
                    alive[0] = False; owner.returncode = 0
                    return 0
                owner.wait = wait
                def popen(*args, **kwargs):
                    kwargs['stdout'].write(b'USB_START_GUARD_FAILED reason=primary original error\n')
                    kwargs['stdout'].flush()
                    return owner
                def capture(*args):
                    if diagnostic is None:
                        return dict(diagnostic_only=True, received=False, capture_error='failure diagnostic timed out')
                    path = root / 'evidence/observer-failure.log'; path.write_bytes(diagnostic)
                    return dict(diagnostic_only=True, received=True, path=str(path))
                def command(name):
                    commands.append(name); return {'return': {}}
                handles = (Mock(), Mock())
                launch = dict(command=['never-start-a-VM'], env={}, children=[], fd=leased.fileno(),
                    qmp_socket=str(root / 'no-qmp.sock'), camera_profile=self.start['PROFILE'],
                    script_sha256='c' * 64, dtb_sha256='d' * 64, cmdline='host fixture')
                cold = dict(source='host fixture', ram0_sha256='e' * 64, script_identity={})
                with patch.object(API['subprocess'], 'Popen', side_effect=popen), patch.dict(API['EXECUTOR'], qmp_connect=Mock(return_value=(*handles, command)), new_receipt=lambda *a, **k: {}, collect=lambda *a: {}), patch.dict(API['execute'].__globals__, capture_failure_observer=capture, peer_pid=lambda _: os.getpid()):
                    with self.assertRaises(RuntimeError) as caught:
                        API['execute'](launch, cold, root / 'evidence', observe_start=True,
                            observer_mode_verified=API['FUNCTIONAL_MODE'] if functional else 'passive',
                            observer_contract=self.contract if functional else {})
                    self.assertIn('Original guest failure', str(caught.exception.__cause__))
                result = json.loads((root / 'evidence/result.json').read_text())
                self.assertIn('Original guest failure', result['error'])
                self.assertEqual(result['phases'], {})
                self.assertFalse(result['owner']['signals_sent'])
                owner.kill.assert_not_called(); owner.terminate.assert_not_called(); owner.send_signal.assert_not_called()
                self.assertEqual(launch['children'], [owner])
                self.assertFalse(leased.closed)
                external = root / 'evidence/external-owner-close.json'
                if external.exists():
                    self.assertFalse(json.loads(external.read_text())['dispatch_success'])
                return result, waits, commands

    def test_unknown_or_allocated_unfreed_owner_holds_disk_without_quit_or_signals(self):
        missing_free = b'\n'.join(line for line in self.trace().splitlines() if not line.startswith(b'USB_EE FREE_RETURN ')) + b'\n'
        for diagnostic in (None, self.capture(missing_free), self.capture(self.trace() + b'USB_EE CAP bounded=1\n')):
            result, waits, commands = self.execute_failure(diagnostic)
            self.assertTrue(result['owner']['owner_retained']); self.assertFalse(result['owner']['qmp_quit_confirmed'])
            self.assertEqual(waits, [((), {})]); self.assertEqual(commands, [])
            self.assertFalse(result['complete_readbacks'])

    def test_retained_peer_is_waited_after_wrapper_exit_without_quit_or_signal(self):
        from types import SimpleNamespace
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            disk = root / 'disk'; disk.write_bytes(b'local disk lease fixture')
            with disk.open('rb') as leased, disk.open('rb') as contender:
                fcntl.flock(leased, fcntl.LOCK_EX | fcntl.LOCK_NB)
                peer = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.buffer.read()'], stdin=subprocess.PIPE)
                owner = SimpleNamespace(pid=os.getpid(), poll=lambda: 0, returncode=0, wait=Mock())
                terminal = dict(qmp_peer_pid=peer.pid, signals_sent=[], qmp_quit_confirmed=False)
                result = dict(error='primary original failure')
                bad_handle = Mock(); bad_handle.close.side_effect = OSError('host QMP already disconnected')
                def disconnect_peer():
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    retained = json.loads((root / 'owner-retained.json').read_text())
                    self.assertEqual(retained['owner']['qmp_peer_identity']['pid'], peer.pid)
                    peer.stdin.close()
                handle = Mock(); handle.close.side_effect = disconnect_peer
                try:
                    API['hold_functional_owner'](owner, dict(qmp_socket=str(root / 'qmp.sock'), fd=leased.fileno()),
                                                 terminal, result, root, (bad_handle, handle))
                    self.assertTrue(terminal['retained_peer_exited'])
                    self.assertIn('already disconnected', terminal['host_connection_close_errors'][0])
                    self.assertEqual(peer.wait(timeout=3), 0)
                    owner.wait.assert_not_called()
                    self.assertFalse(terminal['qmp_quit_confirmed']); self.assertEqual(terminal['signals_sent'], [])
                    self.assertFalse(json.loads((root / 'external-owner-close.json').read_text())['dispatch_success'])
                    self.assertEqual(result['error'], 'primary original failure')
                    self.assertFalse(leased.closed)
                finally:
                    if not peer.stdin.closed:
                        peer.stdin.close()
                    peer.wait(timeout=3)

    def test_positive_native_free_keeps_primary_failure_but_allows_normal_quit(self):
        # A real native free proves release even when the business retirement failed.
        trace = self.trace().replace(b'retired=1 pending=0', b'retired=0 pending=1')
        result, waits, commands = self.execute_failure(self.capture(trace))
        self.assertEqual(commands, ['quit']); self.assertEqual(waits, [((), {'timeout': 30})])
        self.assertFalse(result['failure_functional_trace']['business_complete'])
        self.assertTrue(result['failure_functional_trace']['native_message_released'])
        self.assertTrue(result['owner']['qmp_quit_confirmed'])
        for diagnostic in (None, self.capture(self.trace())):
            result, waits, commands = self.execute_failure(diagnostic, functional=False)
            self.assertEqual(commands, ['quit']); self.assertEqual(waits, [((), {'timeout': 30})])


class OriginalBridgeProtocol(unittest.TestCase):
    def exchange(self, present=None, *, wrong_owner=False, wrong_identity=False, unready_payload=False):
        protocol = API['protocol']
        async def scenario(root):
            root.chmod(0o700)
            expected = os.getpid() + 1 if wrong_owner else os.getpid()
            context = protocol.Context.create(root, root / 'qmp.sock', root / 'usb-endpoint.sock', 'a' * 64, expected)
            observed = []
            async def handle(reader, writer):
                try:
                    header, payload = await protocol.read_frame(reader)
                    observed.append(header)
                    identity = dict(header, ok=True)
                    if wrong_identity:
                        identity['lease'] = 'b' * 64
                    writer.write(protocol.encode_frame(identity))
                    await writer.drain()
                    if wrong_identity:
                        return
                    header, payload = await protocol.read_frame(reader)
                    observed.append(header)
                    response = dict(header, ok=True)
                    if present is None:
                        response.update(ready=False, reason='original gadget is not bound')
                    writer.write(protocol.encode_frame(response, b'bad' if unready_payload else b''))
                    await writer.drain()
                    await reader.read()
                except (asyncio.IncompleteReadError, ConnectionError):
                    pass
                finally:
                    writer.close()
                    await writer.wait_closed()
            server = await asyncio.start_unix_server(handle, path=str(context.backend_path))
            context.backend_path.chmod(0o600)
            try:
                result = await API['bridge_request'](context, present)
                return result, observed
            finally:
                server.close()
                await server.wait_closed()
        with tempfile.TemporaryDirectory(prefix='usb-ap-') as root:
            return asyncio.run(scenario(Path(root)))

    def test_descriptor_readback_saves_validated_raw_bytes_and_keeps_failed_attempt(self):
        protocol = API['protocol']
        raw = bytes.fromhex('1201000200000040341278560001000000010902120001010080320904000000ff000000')
        metadata = dict(descriptor_source='guest-ep0', busid='dwc3-1', busnum=1,
                        devnum=1, speed=3, configuration_value=1)
        async def scenario(root, payload):
            bridge = AsyncMock()
            bridge.ask.side_effect = [({'ready': False, 'reason': 'pending'}, b''),
                                      ({'ready': True, 'device': metadata}, payload)]
            with patch.object(protocol.Bridge, 'open', AsyncMock(return_value=bridge)):
                return await API['descriptor_readback'](None, root)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = asyncio.run(scenario(root, raw))
            self.assertTrue(result['guest_ep0_bytes_verified'])
            self.assertFalse(result['export_allowed'])
            self.assertEqual(len(result['attempts']), 2)
            self.assertEqual((root / 'guest-ep0-descriptors.bin').read_bytes(), raw)
            (root / 'guest-ep0-descriptors.bin').unlink()
            with self.assertRaises(protocol.ProtocolError):
                asyncio.run(scenario(root, b'bad'))
            self.assertFalse((root / 'guest-ep0-descriptors.bin').exists())

    def test_vbus_true_false_use_actual_hello_run_lease_qmp_peer_protocol(self):
        for present in (True, False):
            result, observed = self.exchange(present)
            self.assertEqual([v['op'] for v in observed], ['hello', 'vbus'])
            self.assertEqual(observed[0]['role'], 'control')
            self.assertEqual(observed[0]['vm_pid'], os.getpid())
            self.assertEqual(observed[0]['lease'], 'a' * 64)
            self.assertIs(observed[1]['present'], present)
            self.assertEqual(result['payload_bytes'], 0)

    def test_unready_has_no_export_or_descriptor_payload(self):
        result, _ = self.exchange()
        self.assertIs(result['response']['ready'], False)
        self.assertEqual(result['payload_bytes'], 0)
        with self.assertRaisesRegex(API['protocol'].ProtocolError, 'Unready'):
            self.exchange(unready_payload=True)

    def test_wrong_peer_or_lease_fails_without_vbus_request(self):
        with self.assertRaisesRegex(API['protocol'].Blocked, 'peer'):
            self.exchange(True, wrong_owner=True)
        with self.assertRaisesRegex(API['protocol'].Blocked, 'identity'):
            self.exchange(True, wrong_identity=True)


if __name__ == '__main__':
    unittest.main()
