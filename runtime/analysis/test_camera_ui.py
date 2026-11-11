"""Host-only tests; this module deliberately never imports menu_control or launches QEMU."""
import copy
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from camera_ui import CameraUI, Gdk, GLib, Gtk, KEY_NAMES, SnapshotPoller


class StubVM:
    def __init__(self):
        self.lock = threading.RLock()
        self.png = None
        self.calls = []
        self.positions = []
        self.failure = None
        self.value = dict(state='disconnected', error='', busy='', pending=0, snapshot=None,
                          stale=True, mock=True, events=[], can_start=True, can_stop=False,
                          controls={name: dict(label=text, available=name in ('MENU', 'ENTER', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'DELETE'),
                                               verified=name in ('MENU', 'ENTER', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'DELETE'),
                                               verification='host fixture', note='仅测试控件接线',
                                               unavailable_reason='host fixture: 原生键码未知', shortcuts=[])
                                    for name, text in KEY_NAMES.items()})
        shortcuts = dict(MENU=['m', 'Escape'], ENTER=['Enter'], UP=['ArrowUp'], DOWN=['ArrowDown'],
                         LEFT=['ArrowLeft'], RIGHT=['ArrowRight'], DELETE=['Delete'])
        for name, keys in shortcuts.items():
            self.value['controls'][name]['shortcuts'] = keys

    def status(self):
        with self.lock:
            return copy.deepcopy(self.value)

    def event(self, message):
        events = self.value['events']
        events.insert(0, dict(id=(events[0]['id'] if events else 0) + 1, message=message))

    def start(self):
        self.calls.append('start')
        self.value.update(state='running', can_start=False, can_stop=True)
        self.event('HOST STUB 已启动，无固件')

    def enqueue(self, command):
        if self.failure:
            raise ValueError(self.failure)
        if self.value['state'] != 'running':
            raise ValueError('not running')
        if command.get('action') == 'position':
            entry = self.value['controls'].get(command.get('key'), {})
            if not entry.get('available') or command.get('position') not in entry.get('positions', {}):
                raise ValueError('position unavailable')
            self.positions.append((command['key'], command['position']))
        self.calls.append(command)
        self.value['pending'] += 1

    def complete(self, *, error='', png=None):
        self.value.update(pending=0, busy='', error=error)
        if png is not None:
            self.png = png
            self.value['snapshot'] = dict(number=(self.value['snapshot'] or {}).get('number', 0) + 1,
                                          sequence=1, sha256='host-fixture', captured_at=time.time(), pixel_source_seq=1)
            self.value['stale'] = False
        self.event('HOST STUB command complete: ' + error)

    def configure_storage(self,enabled):
        if self.value['state']=='running':raise ValueError('stop first')
        self.value['persistent_storage']=enabled;self.calls.append(('storage',enabled))

    def configure_ram(self,enabled):
        if self.value['state']=='running':raise ValueError('stop first')
        self.value['ram_enabled']=enabled;self.calls.append(('ram_mode',enabled))

    def save_ram(self):
        self.calls.append('ram_save')
        self.value.update(state='exited',can_start=True,can_stop=False,ram_snapshot={'stream':'host-fixture-only'})
        return self.value['ram_snapshot']

    def restore_ram(self):
        self.calls.append('ram_restore');self.start();self.value['ram_restored']=True

    def select_firmware_test(self,source=None,destination='/usr/lib/appFw.so'):
        self.calls.append(('firmware_select',source,destination))
        value=dict(guest_path=destination,original=source is None,guest_readback_verified=False)
        self.value['firmware_selection']=value
        return value

    def check_firmware_test(self):
        self.enqueue(dict(action='firmware_readback'))

    def stop(self):
        self.calls.append('stop')
        self.value.update(state='exited', can_start=True, can_stop=False, stale=True, pending=0)

    def close(self):
        self.calls.append('close')
        self.value.update(state='exited', can_start=True, can_stop=False, stale=True, pending=0)


class PollerTests(unittest.TestCase):
    def setUp(self):
        self.vm = StubVM()
        self.vm.start()
        self.poller = SnapshotPoller(10)

    def test_one_outstanding_even_if_longer_than_interval(self):
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 0))
        self.poller.observe(self.vm.status(), 1)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), 999))
        self.assertEqual(self.vm.value['pending'], 1)
        self.vm.complete(png=b'fixture')
        self.poller.observe(self.vm.status(), 1000)
        self.assertFalse(self.poller.inflight)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), 1001))
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 1011))

    def test_fast_repeated_errors_complete_and_backoff(self):
        for now, expected in ((0, 20), (21, 40), (62, 60)):
            self.assertTrue(self.poller.request(self.vm, self.vm.status(), now))
            self.vm.complete(error='same failure')
            self.poller.observe(self.vm.status(), now + .1)
            self.assertFalse(self.poller.inflight)
            self.assertEqual(self.poller.delay, expected)

    def test_busy_off_and_disabled_interval(self):
        self.vm.value['busy'] = 'key'
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), 0, force=True))
        self.vm.value['busy'] = ''
        self.poller.set_interval(0, 0)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), 999))
        self.poller.after_input(999, delay=0)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), 999))
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 999, force=True))
        self.vm.stop()
        self.poller.observe(self.vm.status(), 1000)
        self.assertFalse(self.poller.inflight)

    def test_enqueue_rejection_backs_off_without_inflight(self):
        self.vm.failure = 'queue full'
        with self.assertRaises(ValueError):
            self.poller.request(self.vm, self.vm.status(), 0)
        self.assertFalse(self.poller.inflight)
        self.assertEqual(self.poller.next_at, 20)

    def test_input_followup_waits_for_render_and_latest_input(self):
        self.poller.after_input(1)
        self.poller.after_input(1.1)
        # A pending follow-up also suppresses an already-due periodic capture.
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), 1.2))
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 1.3))
        self.assertIsNone(self.poller.follow_up_at)

    def test_input_during_inflight_snapshot_is_not_lost(self):
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 0))
        self.poller.after_input(.1)
        self.vm.complete(png=b'fixture')
        self.poller.observe(self.vm.status(), .2)
        self.assertFalse(self.poller.inflight)
        self.assertEqual(self.poller.next_at, 10.2)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), .29))
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), .31))
        self.assertIsNone(self.poller.follow_up_at)

    def test_input_ack_starts_the_render_window(self):
        self.poller.after_input(0)
        self.vm.value['events'] = [dict(id=1, kind='input', message='MENU：输入已提交')]
        self.poller.observe(self.vm.status(), .15)
        self.assertAlmostEqual(self.poller.follow_up_at, .35)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), .34))
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), .36))

    def test_input_followup_respects_snapshot_error_backoff(self):
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 0))
        self.vm.complete(error='snapshot failure')
        self.poller.observe(self.vm.status(), .1)
        self.poller.after_input(.1)
        self.assertFalse(self.poller.request(self.vm, self.vm.status(), .31))
        self.assertTrue(self.poller.request(self.vm, self.vm.status(), 20.11))


@unittest.skipUnless(Gtk.init_check()[0], 'GTK display required: use xvfb-run')
class GTKTests(unittest.TestCase):
    def setUp(self):
        self.vm = StubVM()
        self.ui = CameraUI(self.vm, timer=False)
        self.ui.window.present()
        self.settle()

    def test_development_storage_selection_is_stopped_only(self):
        self.assertTrue(self.ui.development_storage.get_sensitive())
        self.ui.development_storage.set_active(True);self.settle()
        self.assertIn(('storage',True),self.vm.calls)
        self.assertTrue(self.ui.state['persistent_storage'])
        self.vm.start();self.ui.update(self.vm.status())
        self.assertFalse(self.ui.development_storage.get_sensitive())

    def test_development_original_selection_and_guest_check_use_existing_controller(self):
        self.assertTrue(self.ui.development_buttons['original'].get_sensitive())
        self.assertFalse(self.ui.development_buttons['readback'].get_sensitive())
        self.ui.development_buttons['original'].clicked();self.settle()
        self.assertIn(('firmware_select',None,'/usr/lib/appFw.so'),self.vm.calls)
        self.ui.development_target.set_text('/usr/bin/us_remove_modes.sh')
        self.ui.development_buttons['original'].clicked();self.settle()
        self.assertIn(('firmware_select',None,'/usr/bin/us_remove_modes.sh'),self.vm.calls)
        self.vm.start();self.ui.update(self.vm.status())
        self.assertFalse(self.ui.development_buttons['stage'].get_sensitive())
        self.ui.development_buttons['readback'].clicked();self.settle()
        self.assertIn(dict(action='firmware_readback'),self.vm.calls)

    def test_development_restart_closes_before_starting_same_controller(self):
        self.vm.start();self.ui.update(self.vm.status());self.vm.calls.clear()
        self.ui.development_buttons['restart'].clicked();self.settle()
        self.assertEqual(self.vm.calls[:2],['close','start'])
        self.assertFalse(self.ui.development_busy)

    def test_development_ram_mode_save_and_restore_use_controller_state(self):
        self.vm.value['boot_profile']='original-init-cold';self.ui.update(self.vm.status())
        self.assertTrue(self.ui.development_ram.get_sensitive())
        self.assertFalse(self.ui.development_buttons['ram_restore'].get_sensitive())
        self.ui.development_ram.set_active(True);self.settle()
        self.assertIn(('ram_mode',True),self.vm.calls)
        self.vm.start();self.ui.update(self.vm.status())
        self.assertFalse(self.ui.development_ram.get_sensitive())
        self.assertTrue(self.ui.development_buttons['ram_save'].get_sensitive())
        self.ui.development_buttons['ram_save'].clicked();self.settle()
        self.assertIn('ram_save',self.vm.calls)
        self.assertFalse(self.ui.development_buttons['ram_save'].get_sensitive())
        self.assertTrue(self.ui.development_buttons['ram_restore'].get_sensitive())
        self.ui.development_buttons['ram_restore'].clicked();self.settle()
        self.assertIn('ram_restore',self.vm.calls)
        self.assertIn('RAM 恢复通过',self.ui.development_status.get_text())

    def test_development_busy_keeps_owner_until_worker_finishes(self):
        self.ui.development_busy=True;self.ui.update(self.vm.status())
        self.assertFalse(self.ui.on.get_sensitive())
        self.assertTrue(self.ui._close());self.assertNotIn('close',self.vm.calls)
        self.ui.development_busy=False

    def test_failed_firmware_readback_is_not_displayed_as_passed(self):
        self.vm.value['firmware_verification']=dict(path='/usr/lib/appFw.so',guest_readback_verified=False,error='mismatch')
        self.ui.update(self.vm.status())
        self.assertIn('未通过',self.ui.development_status.get_text())

    def tearDown(self):
        if not self.ui.closed:
            self.ui._close()
            deadline = time.monotonic() + 2
            while not self.ui.closed and time.monotonic() < deadline:
                self.settle()
        self.assertTrue(self.ui.closed)
        self.assertIn('close', self.vm.calls)

    def settle(self):
        deadline = time.monotonic() + .08
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

    def click(self, widget):
        # Real XTest pointer click against an actual GTK window, never widget.emit().
        origin = self.ui.window.get_window().get_origin()
        x, y = widget.translate_coordinates(self.ui.window, 0, 0)
        subprocess.run(['xdotool', 'mousemove', '--sync',
                        str(origin[-2] + x + widget.get_allocated_width() // 2),
                        str(origin[-1] + y + widget.get_allocated_height() // 2), 'click', '1'], check=True)
        self.settle()

    def running(self):
        self.vm.start()
        self.ui.update(self.vm.status())
        self.settle()

    def focus_window(self):
        from gi.repository import GdkX11
        subprocess.run(['xdotool', 'windowfocus', '--sync', str(self.ui.window.get_window().get_xid())], check=True)
        self.settle()

    def test_real_pointer_power_menu_and_disabled_unknown(self):
        self.assertEqual(set(self.ui.buttons), set(KEY_NAMES))
        self.assertTrue(self.ui.on.get_sensitive())
        self.assertFalse(self.ui.buttons['MENU'].get_sensitive())
        self.click(self.ui.on)
        self.assertIn('start', self.vm.calls)
        self.assertTrue(self.ui.buttons['MENU'].get_sensitive())
        self.click(self.ui.buttons['MENU'])
        self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': 'MENU'})
        self.assertIsNotNone(self.ui.poller.follow_up_at)
        self.assertTrue(self.ui.buttons['MENU'].get_sensitive())
        self.vm.complete()
        self.ui.update(self.vm.status())
        self.click(self.ui.buttons['SHUTTER'])
        self.assertEqual(len([x for x in self.vm.calls if isinstance(x, dict)]), 1)
        self.assertIn('未知', self.ui.buttons['SHUTTER'].get_tooltip_text())
        self.click(self.ui.off)
        self.assertIn('stop', self.vm.calls)

    def test_keyboard_input_is_queued_during_lcd_polling(self):
        self.running()
        self.vm.value.update(busy='snapshot',pending=1)
        self.ui.update(self.vm.status());self.ui.window.set_focus(None);self.focus_window()
        subprocess.run(['xdotool','key','Down'],check=True);self.settle()
        self.assertEqual(self.vm.calls[-1],{'action':'key','key':'DOWN'})

    def test_cold_boot_keeps_internal_disk_and_reset_requires_saved_configuration(self):
        self.vm.value.update(boot_profile='original-init-cold',persistent_storage=True,state='exited',can_start=True,settings_persistent=True,settings_generation='saved')
        self.ui.update(self.vm.status())
        self.assertTrue(self.ui.development_storage.get_active())
        self.assertFalse(self.ui.development_storage.get_sensitive())
        self.assertTrue(self.ui.reset_button.get_sensitive())
        self.assertIn('固件修改和 SD',self.ui.reset_button.get_tooltip_text())
        self.assertIn('init2',self.ui.on.get_tooltip_text())
        self.vm.value['settings_generation']=None;self.ui.update(self.vm.status())
        self.assertFalse(self.ui.reset_button.get_sensitive())

    def test_stopped_reset_confirmation_cancel_success_and_retained_sd(self):
        self.vm.value.update(state='exited',settings_persistent=True,settings_generation='old')
        self.ui.update(self.vm.status())
        self.assertTrue(self.ui.reset_button.get_sensitive())
        self.assertTrue(self.ui.request_reinitialize())
        dialog=self.ui.reset_dialog
        self.assertIn('虚拟 SD',dialog.get_property('secondary-text'))
        dialog.response(Gtk.ResponseType.CANCEL);self.settle()
        self.assertIsNone(self.ui.reset_dialog)
        self.assertNotIn('start',self.vm.calls)
        card=object();self.vm.card_seed=card
        def reset(*,confirmed):
            self.assertIs(confirmed,True)
            self.vm.calls.append('reset')
        self.vm.reset_configuration=reset
        self.assertTrue(self.ui.request_reinitialize())
        self.ui.reset_dialog.response(Gtk.ResponseType.ACCEPT)
        deadline=time.monotonic()+2
        while 'start' not in self.vm.calls and time.monotonic()<deadline:self.settle()
        self.assertLess(self.vm.calls.index('reset'),self.vm.calls.index('start'))
        self.assertIs(self.vm.card_seed,card)
        self.assertFalse(self.ui.reinitializing)

    def test_reset_failure_never_restarts_and_live_vm_has_no_reset(self):
        self.running()
        self.vm.value.update(settings_persistent=True,settings_generation='old')
        self.ui.update(self.vm.status())
        self.assertFalse(self.ui.reset_button.get_sensitive())
        self.assertFalse(self.ui.request_reinitialize())
        self.vm.stop();self.ui.update(self.vm.status())
        def fail(*,confirmed):raise RuntimeError('injected CAS conflict')
        self.vm.reset_configuration=fail
        count=self.vm.calls.count('start')
        self.ui.request_reinitialize();self.ui.reset_dialog.response(Gtk.ResponseType.ACCEPT)
        deadline=time.monotonic()+2
        while self.ui.reinitializing and time.monotonic()<deadline:self.settle()
        self.assertEqual(self.vm.calls.count('start'),count)
        self.assertIn('CAS conflict',self.ui.local_error)

    def test_three_independent_wheel_symbols(self):
        self.running()
        for prefix in ('FRONT', 'REAR', 'CONTROL'):
            for direction in ('LEFT', 'RIGHT'):
                name = prefix + '_' + direction
                self.vm.value['controls'][name]['available'] = True
                self.ui.update(self.vm.status())
                self.click(self.ui.buttons[name])
                self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': name})
                self.vm.complete()
        self.assertFalse(self.ui.buttons['MODE'].get_sensitive())

    def test_half_full_and_custom_are_separate_queued_controls(self):
        self.running()
        for name in ('SHUTTER_HALF', 'SHUTTER', 'C1'):
            self.vm.value['controls'][name].update(available=True, verified=False,
                                                  note='仅输入通道 fixture；不证明拍摄')
        self.ui.update(self.vm.status())
        for name in ('SHUTTER_HALF', 'SHUTTER', 'C1'):
            self.click(self.ui.buttons[name])
            self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': name})
            self.vm.complete()
            self.ui.update(self.vm.status())

    def test_keyboard_uses_registry_and_respects_focused_button(self):
        self.running()
        self.ui.lcd.set_can_focus(True)
        self.ui.lcd.grab_focus()
        self.focus_window()
        subprocess.run(['xdotool', 'key', 'Down'], check=True)
        self.settle()
        self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': 'DOWN'})
        self.vm.complete()
        self.ui.update(self.vm.status())
        self.ui.off.grab_focus()
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        self.settle()
        self.settle()
        self.settle()
        self.settle()
        self.assertIn('stop', self.vm.calls)

    def test_lcd_only_backend_bytes_old_state_and_bad_png(self):
        self.running()
        self.assertIsNone(self.ui.pixbuf)
        # Solid test fixture is a decoder check, never a claimed firmware capture.
        from gi.repository import GdkPixbuf
        fixture = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 480)
        fixture.fill(0x415c4eff)
        ok, data = fixture.save_to_bufferv('png', [], [])
        self.assertTrue(ok)
        self.vm.complete(png=bytes(data))
        self.ui.update(self.vm.status())
        self.assertIs(self.ui.png_bytes, self.vm.png)
        self.settle()
        x, y = self.ui.lcd.translate_coordinates(self.ui.window, 0, 0)
        pixel = Gdk.pixbuf_get_from_window(self.ui.window.get_window(),
                                          x + self.ui.lcd.get_allocated_width() // 2,
                                          y + self.ui.lcd.get_allocated_height() // 2, 1, 1)
        self.assertEqual(tuple(pixel.get_pixels()[:3]), (65, 92, 78))
        previous = self.ui.pixbuf
        self.vm.complete(png=b'not PNG')
        self.ui.update(self.vm.status())
        self.assertIs(self.ui.pixbuf, previous)
        self.assertIn('解码失败', self.ui.error_label.get_text())
        self.assertIn('旧画面', self.ui.frame_label.get_text())
        self.assertIn('#1', self.ui.frame_label.get_text())
        self.vm.stop()
        self.ui.update(self.vm.status())
        self.assertIn('旧画面', self.ui.frame_label.get_text())

    def test_rapid_distinct_keyboard_shortcuts_are_not_dropped(self):
        self.running()
        self.ui.lcd.set_can_focus(True)
        self.ui.lcd.grab_focus()
        self.focus_window()
        subprocess.run(['xdotool', 'key', 'Down', 'Left'], check=True)
        self.settle()
        keys = [call['key'] for call in self.vm.calls if isinstance(call, dict) and call['action'] == 'key']
        self.assertEqual(keys[-2:], ['DOWN', 'LEFT'])

    def test_enter_after_camera_button_focus_remains_camera_confirm(self):
        self.running()
        self.ui.buttons['UP'].grab_focus()
        self.focus_window()
        subprocess.run(['xdotool','key','Return'],check=True)
        self.settle()
        self.assertEqual(self.vm.calls[-1],{'action':'key','key':'ENTER'})

    def test_real_scroll_routes_front_and_rear_separately(self):
        self.running()
        for prefix in ('FRONT', 'REAR'):
            self.vm.value['controls'][prefix + '_RIGHT']['available'] = True
            self.ui.update(self.vm.status())
            button = self.ui.buttons[prefix + '_RIGHT']
            origin = self.ui.window.get_window().get_origin()
            x, y = button.translate_coordinates(self.ui.window, 0, 0)
            subprocess.run(['xdotool', 'mousemove', '--sync', str(origin[-2] + x + 8),
                            str(origin[-1] + y + 8), 'click', '5'], check=True)
            self.settle()
            self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': prefix + '_RIGHT'})
            self.vm.complete()

    def test_capture_single_inflight_and_error_recovery(self):
        self.running()
        self.assertTrue(self.ui.capture())
        self.assertFalse(self.ui.capture())
        self.assertFalse(self.ui.refresh.get_sensitive())
        self.vm.complete(error='snapshot failure')
        self.ui.update(self.vm.status())
        self.assertFalse(self.ui.poller.inflight)
        self.assertTrue(self.ui.refresh.get_sensitive())
        self.assertIn('snapshot failure', self.ui.error_label.get_text())
        self.assertTrue(self.ui.capture())
        self.assertEqual(self.vm.value['pending'], 1)

    def test_unconfirmed_close_keeps_window_for_retry(self):
        self.running()
        real_close = self.vm.close
        self.vm.close = lambda: None
        self.ui._close()
        self.settle()
        self.assertFalse(self.ui.closed)
        self.assertFalse(self.ui.closing)
        self.assertTrue(self.ui.root.get_sensitive())
        self.assertIn('清理失败', self.ui.error_label.get_text())
        self.vm.close = real_close

    def test_real_control_ring_drag_and_cancel(self):
        self.running()
        for name in ('CONTROL_LEFT', 'CONTROL_RIGHT'):
            self.vm.value['controls'][name]['available'] = True
        self.ui.update(self.vm.status())
        self.settle()
        origin = self.ui.window.get_window().get_origin()
        ring = self.ui.ring
        x, y = ring.translate_coordinates(self.ui.window, 0, 0)
        cx = origin[-2] + x + ring.get_allocated_width() // 2
        cy = origin[-1] + y + ring.get_allocated_height() // 2
        radius = ring.get_allocated_width() // 2 - 4
        subprocess.run(['xdotool', 'mousemove', '--sync', str(cx + radius), str(cy), 'mousedown', '1'], check=True)
        self.settle()
        self.assertIsNotNone(self.ui.drag)
        subprocess.run(['xdotool', 'mousemove', '--sync', str(cx), str(cy + radius)], check=True)
        self.settle()
        subprocess.run(['xdotool', 'mouseup', '1'], check=True)
        self.settle()
        self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': 'CONTROL_RIGHT'})
        self.vm.complete()
        self.ui.update(self.vm.status())
        self.ui.drag = [0, 2]
        before = len(self.vm.calls)
        self.ui._cancel_drag()
        self.assertIsNone(self.ui.drag)
        self.assertEqual(len(self.vm.calls), before)

    def test_one_window_and_layout_at_desktop_sizes(self):
        evidence = Path(__file__).parent / 'evidence'
        evidence.mkdir(exist_ok=True)
        result = []
        for width, height in ((1280, 900), (1360, 930), (1920, 1080), (2560, 1440)):
            self.ui.window.resize(width, height)
            self.settle()
            actual_width, actual_height = self.ui.window.get_size()
            lcd_width, lcd_height = self.ui.lcd.get_allocated_width(), self.ui.lcd.get_allocated_height()
            self.assertAlmostEqual(lcd_width / lcd_height, 4 / 3, delta=.02)
            for name, widget in dict(self.ui.buttons, ON=self.ui.on, OFF=self.ui.off, REFRESH=self.ui.refresh).items():
                x, y = widget.translate_coordinates(self.ui.window, 0, 0)
                self.assertGreaterEqual(x, 0, name)
                self.assertGreaterEqual(y, 0, name)
                self.assertLessEqual(x + widget.get_allocated_width(), actual_width, name)
                self.assertLessEqual(y + widget.get_allocated_height(), actual_height, name)
                self.assertGreaterEqual(widget.get_allocated_width(), 44, name)
                self.assertGreaterEqual(widget.get_allocated_height(), 44, name)
                self.assertTrue(widget.get_accessible().get_name(), name)
            windows = [window for window in Gtk.Window.list_toplevels() if window.get_visible()]
            self.assertEqual(windows, [self.ui.window])
            pixbuf = Gdk.pixbuf_get_from_window(self.ui.window.get_window(), 0, 0, actual_width, actual_height)
            pixbuf.savev(str(evidence / f'gtk-stub-{width}x{height}.png'), 'png', [], [])
            result.append(dict(size=[actual_width, actual_height], lcd=[self.ui.lcd.get_allocated_width(), self.ui.lcd.get_allocated_height()], buttons=len(self.ui.buttons)))
        import json
        (evidence / 'gtk-layout.json').write_text(json.dumps(result, indent=2) + '\n')

    def test_faulted_vm_blocks_camera_input_but_keeps_off_available(self):
        self.running()
        self.vm.value.update(state='faulted',error='injected AP fault',can_start=False,can_stop=True)
        self.ui.update(self.vm.status())
        self.assertFalse(self.ui.buttons['UP'].get_sensitive())
        self.assertTrue(self.ui.off.get_sensitive());self.assertFalse(self.ui.on.get_sensitive())
        self.assertIn('固件异常',self.ui.status_label.get_text())
        self.assertFalse(self.ui.poller.request(self.vm,self.vm.status(),0,force=True))
        before=list(self.vm.calls);self.click(self.ui.buttons['UP']);self.assertEqual(self.vm.calls,before)
        self.click(self.ui.off);self.assertEqual(self.vm.calls[-1],'stop')

    def mode_available(self):
        # Deliberately includes an extra backend label and nonsequential values.
        self.vm.value['controls']['MODE'].update(
            available=True, positions={'P': 1, 'A': 3, 'S': 5, 'M': 4, 'AUTO': 6,
                                       'MR1': 7, 'MR2': 19, 'MR3': 20, 'LAB': 451})
        self.running()

    def mode_choices(self):
        return {button.get_label(): button for button in self.ui.mode_popover.get_child().get_children()}

    def mode_screenshot(self, name):
        evidence = Path(__file__).parent / 'evidence'
        evidence.mkdir(exist_ok=True)
        self.settle()
        width, height = self.ui.window.get_size()
        image = Gdk.pixbuf_get_from_window(self.ui.window.get_window(), 0, 0, width, height)
        image.savev(str(evidence / name), 'png', [], [])

    def test_mode_pointer_selects_registry_label_and_only_queues(self):
        self.mode_available()
        self.assertIn('host fixture', self.ui.buttons['MODE'].get_tooltip_text())
        before_frame = self.ui.pixbuf, self.ui.frame_token, self.ui.png_bytes, self.ui.frame_label.get_text()
        self.click(self.ui.buttons['MODE'])
        self.assertTrue(self.ui.mode_popover.get_visible())
        self.assertEqual(list(self.mode_choices()), list(self.vm.value['controls']['MODE']['positions']))
        self.assertEqual([w for w in Gtk.Window.list_toplevels() if w.get_visible()], [self.ui.window])
        self.assertEqual(tuple(self.ui.window.get_size()), (1360, 930))
        self.mode_screenshot('mode-popover-pointer.png')
        self.click(self.mode_choices()['MR2'])
        self.assertEqual(self.vm.calls[-1], {'action': 'position', 'key': 'MODE', 'position': 'MR2'})
        self.assertEqual(self.vm.positions, [('MODE', 'MR2')])
        self.assertEqual(self.ui.buttons['MODE'].get_label(), 'MODE')
        self.assertEqual((self.ui.pixbuf, self.ui.frame_token, self.ui.png_bytes, self.ui.frame_label.get_text()), before_frame)
        self.assertIn('已排队', self.ui.feedback.get_text())
        self.assertIn('固件新画面', self.ui.feedback.get_text())
        self.mode_screenshot('mode-position-queued.png')

    def test_mode_keyboard_tab_enter_arrows_confirm_escape_and_space(self):
        self.mode_available()
        self.ui.window.set_focus(None)
        self.focus_window()
        subprocess.run(['xdotool', 'key', 'Tab'], check=True)
        self.settle()
        self.assertIs(self.ui.window.get_focus(), self.ui.buttons['MODE'])
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        self.settle()
        self.assertTrue(self.ui.mode_popover.get_visible())
        subprocess.run(['xdotool', 'key', 'Down', 'Down', 'Up'], check=True)
        self.settle()
        self.assertIs(self.ui.window.get_focus(), self.mode_choices()['A'])
        self.mode_screenshot('mode-popover-keyboard.png')
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        self.settle()
        self.assertEqual(self.vm.calls[-1], {'action': 'position', 'key': 'MODE', 'position': 'A'})
        self.assertEqual(len(self.vm.positions), 1)
        self.settle()
        self.settle()
        self.assertFalse(self.ui.mode_popover.get_visible())
        self.assertIs(self.ui.window.get_focus(), self.ui.buttons['MODE'])
        subprocess.run(['xdotool', 'key', 'space'], check=True)
        self.settle()
        self.assertTrue(self.ui.mode_popover.get_visible())
        before = list(self.vm.calls)
        subprocess.run(['xdotool', 'key', 'm', 'Delete', 'Left', 'Right', 'Escape'], check=True)
        self.settle()
        self.settle()
        self.settle()
        self.assertFalse(self.ui.mode_popover.get_visible())
        self.assertEqual(self.vm.calls, before)
        subprocess.run(['xdotool', 'key', 'space'], check=True)
        self.settle()
        subprocess.run(['xdotool', 'key', 'Tab', 'space'], check=True)
        for _ in range(4):
            self.settle()
        self.assertEqual(self.vm.positions, [('MODE', 'A'), ('MODE', 'A')])
        self.assertFalse(self.ui.mode_popover.get_visible())
        self.ui.buttons['UP'].grab_focus()
        subprocess.run(['xdotool', 'key', 'Return'], check=True)
        self.settle()
        self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': 'ENTER'})

    def test_mode_missing_positions_and_unavailable_do_not_send(self):
        self.running()
        mode = self.vm.value['controls']['MODE']
        for positions in (None, {}, []):
            mode.update(available=True, positions=positions)
            self.ui.update(self.vm.status())
            self.assertFalse(self.ui.buttons['MODE'].get_sensitive())
            self.assertIn('未提供 MODE 选位', self.ui.buttons['MODE'].get_tooltip_text())
            before = list(self.vm.calls)
            self.click(self.ui.buttons['MODE'])
            self.assertFalse(self.ui.send('MODE'))
            self.assertIn('未提供 MODE 选位', self.ui.feedback.get_text())
            self.assertEqual(self.vm.calls, before)
        mode.update(available=False, positions={'P': 1}, unavailable_reason='registry test unavailable')
        self.ui.update(self.vm.status())
        self.click(self.ui.buttons['MODE'])
        self.assertFalse(self.ui.send('MODE', position='P'))
        self.assertIn('registry test unavailable', self.ui.feedback.get_text())
        self.assertIn('registry test unavailable', self.ui.buttons['MODE'].get_tooltip_text())
        self.assertEqual(self.vm.positions, [])

    def test_mode_confirmation_rechecks_registry_and_reports_queue_error(self):
        self.mode_available()
        for change, message in ((lambda: self.vm.value['controls']['MODE']['positions'].pop('A'), 'registry'),
                                (lambda: self.vm.value['controls']['MODE'].update(available=False), '未知'),
                                (lambda: setattr(self.vm, 'failure', 'queue full'), 'queue full')):
            self.vm.value['controls']['MODE'].update(available=True, positions={'P': 1, 'A': 3})
            self.ui.update(self.vm.status())
            self.click(self.ui.buttons['MODE'])
            change()
            before = list(self.vm.calls)
            self.click(self.mode_choices()['A'])
            self.assertEqual(self.vm.calls, before)
            self.assertIn(message, self.ui.feedback.get_text() + self.ui.error_label.get_text())
        self.assertEqual(self.vm.positions, [])

    def triplet_available(self):
        # Host registry fixture only; transport codes/statuses belong to the backend.
        for name in ('MODE_STILL', 'MODE_MOVIE', 'MODE_SQ'):
            self.vm.value['controls'][name].update(
                available=True, verified=False, verification='未验证 / host fixture',
                note='仅验证排队；真实状态看 LCD', unavailable_reason='')
        self.running()

    def test_triplet_pointer_queues_three_distinct_scalar_symbols(self):
        self.triplet_available()
        frame = self.ui.pixbuf, self.ui.frame_token, self.ui.png_bytes, self.ui.frame_label.get_text()
        for name, text in (('MODE_STILL', '照片'), ('MODE_MOVIE', '录像'), ('MODE_SQ', 'S&Q')):
            before = len(self.vm.calls)
            self.click(self.ui.buttons[name])
            self.assertEqual(self.vm.calls[before:], [{'action': 'key', 'key': name}])
            self.assertEqual(self.vm.positions, [])
            self.assertEqual(self.ui.buttons[name].get_label(), text)
            self.assertNotIsInstance(self.ui.buttons[name], Gtk.ToggleButton)
            self.assertIn('未验证', self.ui.buttons[name].get_tooltip_text())
            self.assertIn('已排队', self.ui.feedback.get_text())
            self.assertIn('固件新画面', self.ui.feedback.get_text())
            self.assertEqual((self.ui.pixbuf, self.ui.frame_token, self.ui.png_bytes,
                              self.ui.frame_label.get_text()), frame)
            self.vm.complete()
            self.ui.update(self.vm.status())
        self.vm.value['controls']['REC']['available'] = True
        self.ui.update(self.vm.status())
        self.click(self.ui.buttons['REC'])
        self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': 'REC'})
        self.assertEqual([call['key'] for call in self.vm.calls if isinstance(call, dict)],
                         ['MODE_STILL', 'MODE_MOVIE', 'MODE_SQ', 'REC'])
        self.mode_screenshot('triplet-queued.png')

    def test_triplet_keyboard_tab_space_and_original_mode(self):
        self.triplet_available()
        self.vm.value['controls']['MODE'].update(available=True, positions={'P': 91, 'M': 73})
        self.ui.update(self.vm.status())
        self.ui.window.set_focus(None)
        self.focus_window()
        for name in ('MODE_STILL', 'MODE_MOVIE', 'MODE_SQ'):
            subprocess.run(['xdotool', 'key', 'Tab'], check=True)
            self.settle()
            self.assertIs(self.ui.window.get_focus(), self.ui.buttons[name])
            subprocess.run(['xdotool', 'key', 'space'], check=True)
            for _ in range(4):
                self.settle()
            self.assertEqual(self.vm.calls[-1], {'action': 'key', 'key': name})
            self.vm.complete()
            self.ui.update(self.vm.status())
        self.assertEqual(self.vm.positions, [])
        self.mode_screenshot('triplet-keyboard-focus.png')
        subprocess.run(['xdotool', 'key', 'Tab', 'space'], check=True)
        for _ in range(4):
            self.settle()
        self.assertIsNotNone(self.ui.mode_popover)
        self.assertTrue(self.ui.mode_popover.get_visible())
        self.assertEqual(list(self.mode_choices()), ['P', 'M'])
        self.click(self.mode_choices()['M'])
        self.assertEqual(self.vm.calls[-1], {'action': 'position', 'key': 'MODE', 'position': 'M'})
        self.assertEqual(self.vm.positions, [('MODE', 'M')])

    def test_triplet_registry_missing_unavailable_and_queue_error(self):
        self.triplet_available()
        for name in ('MODE_STILL', 'MODE_MOVIE', 'MODE_SQ'):
            entry = self.vm.value['controls'].pop(name)
            self.ui.update(self.vm.status())
            self.assertFalse(self.ui.buttons[name].get_sensitive())
            before = list(self.vm.calls)
            self.click(self.ui.buttons[name])
            self.assertFalse(self.ui.send(name))
            self.assertIn('registry 未提供', self.ui.feedback.get_text())
            self.vm.value['controls'][name] = entry
            entry.update(available=False, unavailable_reason='host fixture blocked')
            self.ui.update(self.vm.status())
            self.click(self.ui.buttons[name])
            self.assertFalse(self.ui.send(name))
            self.assertIn('host fixture blocked', self.ui.feedback.get_text())
            self.assertEqual(self.vm.calls, before)
            entry['available'] = True
            self.ui.update(self.vm.status())
        self.vm.failure = 'queue full'
        self.click(self.ui.buttons['MODE_SQ'])
        self.assertEqual(self.vm.calls, before)
        self.assertIn('queue full', self.ui.error_label.get_text())

    def test_triplet_faulted_blocks_keys_and_keeps_off(self):
        self.triplet_available()
        self.vm.value.update(state='faulted', error='injected AP fault', can_start=False, can_stop=True)
        self.ui.update(self.vm.status())
        before = list(self.vm.calls)
        for name in ('MODE_STILL', 'MODE_MOVIE', 'MODE_SQ'):
            self.assertFalse(self.ui.buttons[name].get_sensitive())
            self.click(self.ui.buttons[name])
            self.assertFalse(self.ui.send(name))
        self.assertEqual(self.vm.calls, before)
        self.assertTrue(self.ui.off.get_sensitive())
        self.assertFalse(self.ui.on.get_sensitive())
        self.assertFalse(self.ui.refresh.get_sensitive())
        self.click(self.ui.off)
        self.assertEqual(self.vm.calls[-1], 'stop')

class TouchStubVM(StubVM):
    """StubVM plus the input lifecycle surface attach_gtk needs for LCD touch."""
    supports_input_lifecycle = True

    def __init__(self):
        super().__init__()
        self.touch_input = False
        self.input_state = {'held': [], 'uncertain_codes': [], 'error': ''}

    def status(self):
        state = super().status()
        state['touch_input'] = self.touch_input
        state['input_state'] = copy.deepcopy(self.input_state)
        return state

    def enqueue(self, command):
        if isinstance(command, dict) and command.get('action') == 'camera_input':
            self.calls.append(command)
            return
        super().enqueue(command)


@unittest.skipUnless(Gtk.init_check()[0], 'GTK display required: use xvfb-run')
class LCDTouchTests(unittest.TestCase):
    """LCD touch frontend: real GTK signals into the delivered InputBindings."""

    def setUp(self):
        self.vm = TouchStubVM()
        self.now = 100.0
        original_connect = Gtk.DrawingArea.connect
        def connect(widget, name, callback, *args):
            if name == 'touch-event':
                self.touch_handler = callback
            return original_connect(widget, name, callback, *args)
        with patch.object(Gtk.DrawingArea, 'connect', connect):
            self.ui = CameraUI(self.vm, timer=False, clock=lambda: self.now)
        self.touch_sequences = {1: object(), 2: object()}
        self.ui.window.present()
        self.settle()

    def tearDown(self):
        if not self.ui.closed:
            self.ui._close()
            deadline = time.monotonic() + 2
            while not self.ui.closed and time.monotonic() < deadline:
                self.settle()
        self.assertTrue(self.ui.closed)
        self.assertIn('close', self.vm.calls)

    def settle(self):
        deadline = time.monotonic() + .08
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

    def input_calls(self):
        return [call for call in self.vm.calls
                if isinstance(call, dict) and call.get('action') == 'camera_input']

    def new_session(self):
        from menu_live import camera_input_module
        return camera_input_module().InputSession(lambda command: b'host-stub', app_input=True)

    def drain(self, session):
        for request in self.input_calls():
            self.assertTrue(session.handle(request)['ok'], request)
        self.vm.calls[:] = [call for call in self.vm.calls
                            if not (isinstance(call, dict) and call.get('action') == 'camera_input')]

    def frame_png(self):
        from gi.repository import GdkPixbuf
        fixture = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 640, 480)
        fixture.fill(0x415c4eff)
        ok, data = fixture.save_to_bufferv('png', [], [])
        self.assertTrue(ok)
        return bytes(data)

    def ready(self, *, png=True):
        self.vm.start()
        self.vm.touch_input = True
        if png:
            self.vm.complete(png=self.frame_png())
        self.ui.update(self.vm.status())
        self.settle()

    def lcd_abs(self, x, y):
        origin = self.ui.window.get_window().get_origin()
        wx, wy = self.ui.lcd.translate_coordinates(self.ui.window, 0, 0)
        return origin[-2] + wx + x, origin[-1] + wy + y

    def lcd_center(self):
        return self.ui.lcd.get_allocated_width() // 2, self.ui.lcd.get_allocated_height() // 2

    def pointer(self, *arguments):
        subprocess.run(['xdotool'] + [str(argument) for argument in arguments], check=True)

    def press_lcd(self, x, y):
        ax, ay = self.lcd_abs(x, y)
        self.pointer('mousemove', '--sync', ax, ay, 'mousedown', '1')
        self.settle()

    def emit_touch(self, kind, x, y, sequence=1):
        # GdkEventSequence is opaque; invoke the callback connected to the real LCD
        # with distinct synthetic sequences. Mouse tests use actual X11 events.
        event = SimpleNamespace(type=kind, x=float(x), y=float(y),
                                get_event_sequence=lambda: self.touch_sequences[sequence])
        self.assertTrue(self.touch_handler(self.ui.lcd, event))

    def test_lcd_point_scale_black_bars_and_resize(self):
        self.ready()
        width, height = self.ui.lcd.get_allocated_width(), self.ui.lcd.get_allocated_height()
        # The mapping is the exact centered aspect-fit of _draw_lcd.
        scale = min(width / 640, height / 480)
        ex = (width / 2 - (width - 640 * scale) / 2) / scale
        ey = (height / 2 - (height - 480 * scale) / 2) / scale
        self.assertEqual(self.ui.lcd_point(width / 2, height / 2), (int(ex), int(ey)))
        self.assertAlmostEqual(ex, 320, delta=1.01)
        self.assertAlmostEqual(ey, 240, delta=1.01)
        self.assertEqual(self.ui.lcd_point(0, 0), (0, 0))
        self.assertIsNone(self.ui.lcd_point(-1, 0))
        self.assertIsNone(self.ui.lcd_point(width, height))
        self.assertEqual(self.ui.lcd_point(-4, -4, clamp=True), (0, 0))
        self.assertEqual(self.ui.lcd_point(width + 9, height + 9, clamp=True), (639, 479))
        for bad in (float('nan'), float('inf'), float('-inf')):
            self.assertIsNone(self.ui.lcd_point(bad, 0, clamp=True))
            self.assertIsNone(self.ui.lcd_point(0, bad))
        self.ui.window.resize(1920, 1080)
        self.settle()
        width, height = self.ui.lcd.get_allocated_width(), self.ui.lcd.get_allocated_height()
        px, py = self.ui.lcd_point(width / 2, height / 2)
        self.assertAlmostEqual(px, 320, delta=1)
        self.assertAlmostEqual(py, 240, delta=1)
        frame = self.ui.lcd.get_parent()
        frame.set_property('ratio', 16 / 9)  # real GTK allocation: the 4:3 image now letterboxes
        self.settle()
        width, height = self.ui.lcd.get_allocated_width(), self.ui.lcd.get_allocated_height()
        bar = (width - height * 4 / 3) / 2
        self.assertGreater(bar, 2)
        self.assertIsNone(self.ui.lcd_point(bar / 2, height / 2))
        self.assertAlmostEqual(self.ui.lcd_point(width / 2, height / 2)[1], 240, delta=1)
        self.assertEqual(self.ui.lcd_point(bar / 2, height / 2, clamp=True)[0], 0)
        frame.set_property('ratio', 4 / 3)
        self.settle()

    def test_mouse_pointer_touch_roundtrip(self):
        session = self.new_session()
        self.ready()
        cx, cy = self.lcd_center()
        self.press_lcd(cx, cy)
        [begin] = self.input_calls()
        self.assertEqual((begin['op'], begin['phase']), ('touch', 'begin'))
        self.assertEqual((begin['x'], begin['y']), self.ui.lcd_point(cx, cy))
        self.assertEqual(begin['source'], 'lcd-touch:1')
        self.assertEqual(self.ui.input_bindings.touch_source, 'lcd-touch:1')
        self.drain(session)
        self.assertEqual(session.status()['touch']['source'], 'lcd-touch:1')
        self.now += 1
        self.pointer('mousemove', '--sync', *self.lcd_abs(cx - 80, cy - 60))
        self.settle()
        moves = [call for call in self.input_calls() if call['op'] == 'touch' and call['phase'] == 'move']
        self.assertEqual(len(moves), 1)
        self.assertEqual((moves[0]['x'], moves[0]['y']), self.ui.lcd_point(cx - 80, cy - 60, clamp=True))
        self.pointer('mousemove', '--sync', *self.lcd_abs(cx - 80, cy - 60))
        self.settle()
        self.assertEqual(len([c for c in self.input_calls() if c['op'] == 'touch' and c['phase'] == 'move']), 1)
        self.drain(session)
        self.pointer('mouseup', '1')
        self.settle()
        [end] = self.input_calls()
        self.assertEqual((end['op'], end['phase']), ('touch', 'end'))
        self.assertEqual((end['x'], end['y']), self.ui.lcd_point(cx - 80, cy - 60, clamp=True))
        self.drain(session)
        self.assertNotIn('touch', session.status())
        self.assertIsNone(self.ui.input_bindings.touch_source)
        # A new gesture claims a fresh source after the release.
        self.press_lcd(cx, cy)
        self.assertEqual(self.input_calls()[0]['source'], 'lcd-touch:2')
        self.pointer('mouseup', '1')
        self.settle()

    def test_drag_outside_lcd_clamps_and_releases(self):
        session = self.new_session()
        self.ready()
        cx, cy = self.lcd_center()
        self.press_lcd(cx, cy)
        self.drain(session)
        self.now += 1
        outside = self.ui.lcd.get_allocated_width() + 30
        self.pointer('mousemove', '--sync', *self.lcd_abs(outside, cy), 'mouseup', '1')
        self.settle()
        calls = self.input_calls()
        self.assertTrue(calls)
        self.assertEqual(calls[-1]['phase'], 'end')
        self.assertEqual(calls[-1]['x'], 639)
        self.drain(session)
        self.assertNotIn('touch', session.status())
        self.assertIsNone(self.ui.input_bindings.touch_source)

    def test_begin_gates(self):
        cx, cy = self.lcd_center()
        for prepare in (lambda: None,
                        lambda: (self.vm.start(), self.ui.update(self.vm.status())),
                        lambda: (self.ready(png=False),),
                        lambda: (self.ready(), setattr(self.vm, 'input_state',
                                {'held': [], 'uncertain_codes': ['0x2a'], 'error': ''}))):
            prepare()
            self.press_lcd(cx, cy)
            self.pointer('mouseup', '1')
            self.settle()
            self.assertEqual(self.input_calls(), [])
        self.vm.input_state = {'held': [], 'uncertain_codes': [], 'error': ''}
        self.ready()
        self.ui.input_bindings.touch_source = 'other-host-tool'  # foreign owner blocks a new begin
        self.press_lcd(cx, cy)
        self.pointer('mouseup', '1')
        self.settle()
        self.assertEqual(self.input_calls(), [])
        self.ui.input_bindings.touch_source = None
        frame = self.ui.lcd.get_parent()
        frame.set_property('ratio', 16 / 9)
        self.settle()
        width, height = self.ui.lcd.get_allocated_width(), self.ui.lcd.get_allocated_height()
        self.press_lcd((width - height * 4 / 3) / 4, height / 2)
        self.pointer('mouseup', '1')
        self.settle()
        self.assertEqual(self.input_calls(), [])
        frame.set_property('ratio', 4 / 3)
        self.settle()
        self.assertIn('触控未发送', self.ui.feedback.get_text())

    def test_touch_events_single_point_merge_and_cancel(self):
        session = self.new_session()
        self.ready()
        cx, cy = self.lcd_center()
        self.emit_touch(Gdk.EventType.TOUCH_BEGIN, cx, cy)
        self.assertEqual([(c['op'], c['phase']) for c in self.input_calls()], [('touch', 'begin')])
        self.assertEqual(self.ui.input_bindings.touch_source, 'lcd-touch:1')
        self.drain(session)
        self.now += 1
        self.emit_touch(Gdk.EventType.TOUCH_UPDATE, cx - 60, cy - 40)
        self.emit_touch(Gdk.EventType.TOUCH_UPDATE, cx - 60, cy - 40)  # unchanged point: no traffic
        self.assertEqual(len(self.input_calls()), 1)
        self.drain(session)
        # Touchscreen emulated mouse duplicates must not open a second point.
        self.press_lcd(cx, cy)
        self.pointer('mouseup', '1')
        self.settle()
        self.assertEqual(len(self.input_calls()), 0)
        self.emit_touch(Gdk.EventType.TOUCH_BEGIN, cx + 40, cy + 30, sequence=2)
        self.emit_touch(Gdk.EventType.TOUCH_UPDATE, cx + 90, cy + 50, sequence=2)
        self.emit_touch(Gdk.EventType.TOUCH_END, cx + 90, cy + 50, sequence=2)
        self.assertEqual(self.input_calls(), [])
        self.assertEqual(self.ui.input_bindings.touch_source, 'lcd-touch:1')
        self.now += 1
        self.emit_touch(Gdk.EventType.TOUCH_UPDATE, cx + 20, cy + 10)
        moves = [c for c in self.input_calls() if c['phase'] == 'move']
        self.assertEqual(len(moves), 1)
        self.drain(session)
        self.emit_touch(Gdk.EventType.TOUCH_CANCEL, cx + 20, cy + 10)
        self.assertEqual([(c['op'], c.get('phase')) for c in self.input_calls()], [('touch', 'end')])
        self.drain(session)
        self.assertNotIn('touch', session.status())
        self.assertIsNone(self.ui.input_bindings.touch_source)

    def test_touch_end_does_not_release_independent_shutter(self):
        session = self.new_session()
        self.ready()
        self.ui.input_bindings.press('SHUTTER_HALF', 'keyboard:half')
        self.drain(session)
        cx, cy = self.lcd_center()
        self.emit_touch(Gdk.EventType.TOUCH_BEGIN, cx, cy)
        self.drain(session)
        self.emit_touch(Gdk.EventType.TOUCH_END, cx, cy)
        self.assertEqual([c['op'] for c in self.input_calls()], ['touch'])
        self.drain(session)
        self.assertEqual(session.status()['held'][0]['key'], 'SHUTTER_HALF')
        self.assertNotIn('touch', session.status())
        self.ui.input_bindings.release('keyboard:half')
        self.drain(session)

    def test_move_merge_rate_limit_and_end_flush(self):
        session = self.new_session()
        self.ready()
        cx, cy = self.lcd_center()
        self.press_lcd(cx, cy)
        self.drain(session)
        self.now += .005  # inside the 33ms window: both moves coalesce to the latest point
        self.pointer('mousemove', '--sync', *self.lcd_abs(cx - 120, cy - 90))
        self.pointer('mousemove', '--sync', *self.lcd_abs(cx + 100, cy + 70))
        self.settle()
        moves = [c for c in self.input_calls() if c['op'] == 'touch' and c['phase'] == 'move']
        self.assertEqual(len(moves), 1)
        self.assertEqual((moves[0]['x'], moves[0]['y']), self.ui.lcd_point(cx + 100, cy + 70, clamp=True))
        self.drain(session)
        self.now += .005
        self.pointer('mousemove', '--sync', *self.lcd_abs(cx - 40, cy - 30))  # flushed by the release
        self.pointer('mouseup', '1')
        self.settle()
        self.assertEqual([(c['op'], c.get('phase')) for c in self.input_calls()],
                         [('touch', 'move'), ('touch', 'end')])
        self.drain(session)
        self.assertNotIn('touch', session.status())

    def test_grab_broken_focus_out_release_and_backend_touch_cleanup(self):
        session = self.new_session()
        self.ready()
        cx, cy = self.lcd_center()
        self.emit_touch(Gdk.EventType.TOUCH_BEGIN, cx, cy)
        self.drain(session)
        self.assertIn('touch', session.status())
        self.ui.lcd.emit('grab-broken-event', Gdk.Event.new(Gdk.EventType.GRAB_BROKEN))
        self.settle()
        self.assertEqual([c['op'] for c in self.input_calls()], ['cleanup'])
        self.drain(session)
        self.assertNotIn('touch', session.status())
        self.emit_touch(Gdk.EventType.TOUCH_BEGIN, cx - 30, cy - 20)
        self.drain(session)
        self.ui.window.emit('focus-out-event', Gdk.Event.new(Gdk.EventType.FOCUS_CHANGE))
        self.settle()
        self.assertEqual([c['op'] for c in self.input_calls()], ['cleanup'])
        self.drain(session)
        # A backend-retained touch (e.g. another host tool) still forces the cleanup post.
        self.vm.input_state = {'held': [], 'uncertain_codes': [], 'error': '',
                               'touch': dict(source='other-host', x=1, y=2, uncertain=False)}
        self.ui.window.emit('focus-out-event', Gdk.Event.new(Gdk.EventType.FOCUS_CHANGE))
        self.settle()
        self.assertEqual([c['op'] for c in self.input_calls()], ['cleanup'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
