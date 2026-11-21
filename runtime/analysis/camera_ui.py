#!/usr/bin/env python3
"""Single GTK3 camera window. Importing this module never creates or starts a VM."""
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Atk', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Atk, Gdk, GdkPixbuf, GLib, Gtk, Pango, PangoCairo


CSS = b'''
@define-color bg #0e1214;
@define-color body #181e21;
@define-color panel #1f272b;
@define-color key #293338;
@define-color edge #3f4e54;
@define-color ink #f0f4f2;
@define-color muted #9ba9a5;
@define-color accent #eba04e;
@define-color ok #5ec28f;
@define-color silver #d2d7d4;
@define-color black #060809;
@define-color danger #ef7d75;
window { background: @bg; color: @ink; font: 13px sans-serif; }
.camera { background: @body; border: 1px solid @edge; border-radius: 16px; padding: 12px 14px; }
.top { background: @silver; color: #161b1d; border: 1px solid #aeb5b1; border-radius: 12px; padding: 8px 14px; }
.top-cluster { background: rgba(20, 26, 28, 0.08); border: 1px solid rgba(20, 26, 28, 0.16); border-radius: 10px; padding: 4px 8px; }
.brand { font: bold 22px serif; color: #111517; }
.title { font: bold 16px sans-serif; color: #222a2d; }
.hint { color: @muted; font: 12px sans-serif; }
.top .hint { color: #36423e; font: bold 11px sans-serif; }
.section { color: @muted; font: bold 12px sans-serif; }
.status { background: #1e2629; color: @ink; border: 1px solid #3f4e54; border-radius: 14px; padding: 5px 12px; font: bold 12px monospace; }
.status-running { background: #152e22; color: #88e6b4; border-color: #2f6b4e; }
.status-busy { background: #332615; color: #f5c784; border-color: #75562c; }
.status-error { background: #381919; color: #f7a29b; border-color: #7d3636; }
button, combobox button { background-image: none; background-color: @key; color: @ink; border: 1px solid @edge; border-radius: 8px; padding: 6px 10px; min-height: 28px; min-width: 18px; box-shadow: none; text-shadow: none; font: bold 12px sans-serif; }
button:hover { background-color: #364349; border-color: #6c7d84; }
button:active { background-color: #151c1f; border-color: @accent; color: #ffffff; }
button:disabled { background-color: #20282b; color: #7f8c88; border-color: #323e42; }
.top button:disabled { background-color: #2a3336; color: #9aa6a2; border-color: #465357; }
button:focus, combobox:focus, expander:focus, switch:focus { outline: 2px solid @accent; outline-offset: 2px; }
.top button:focus { outline-color: #181e21; }
button.direction { font: bold 15px sans-serif; }
button.dpad { font: bold 11px sans-serif; padding: 2px 4px; }
button.wheel-step { font: bold 16px sans-serif; background-color: #1c2529; border-color: #4a5a60; color: @accent; }
button.wheel-step:hover { background-color: #2b383e; border-color: @accent; }
button.wheel-step:disabled { background-color: #171e21; border-color: #2c363a; color: #5c6865; }
.round { border-radius: 44px; }
.mode { border-radius: 50px; border: 3px double #79888e; background-color: #1c2427; font: bold 13px sans-serif; }
.shutter-full { border-radius: 50px; border: 2px solid #9ba9a5; background-color: #354146; color: #ffffff; }
popover.mode-positions { background: @body; color: @ink; border: 1px solid @edge; }
.record { border-radius: 44px; border: 2px solid @danger; color: #ffb4ac; }
.power { border-color: @ok; color: #a3ecc5; }
.danger { border-color: #8f4f4b; color: @danger; }
.wheel { border: 6px solid #56666c; border-radius: 140px; background: #13191c; padding: 8px; }
.wheel-off { border-color: #333f43; }
.wheel-drag { border-color: @accent; }
.controls-panel { background: @panel; border: 1px solid #313e43; border-radius: 12px; padding: 12px; }
.lcd { background: #111619; border: 1px solid #2f3c41; border-radius: 12px; padding: 10px; }
.lcd-screen { background: @black; border: 1px solid #48575d; border-radius: 4px; }
.lcd-stale { border-color: @accent; }
.frame-meta { color: @muted; font: 12px monospace; }
.pill-badge { background: #151b1e; border: 1px solid #324045; border-radius: 12px; padding: 4px 10px; color: @muted; font: 12px sans-serif; }
.toolbar { background: @panel; border: 1px solid #313e43; border-radius: 10px; padding: 6px 12px; }
.feedback { background: @panel; border: 1px solid #313e43; border-left: 3px solid @accent; border-radius: 8px; padding: 8px 12px; color: @ink; }
.error { background: #2b1617; border: 1px solid #6e3030; border-left: 3px solid @danger; border-radius: 8px; padding: 8px 12px; color: @danger; }
.warning { color: @accent; }
.drawer-card { background: @panel; border: 1px solid #313e43; border-radius: 10px; padding: 6px 12px; }
expander { color: @ink; font: bold 12px sans-serif; }
textview, textview text { background: #161c1f; color: @muted; font: 12px monospace; }
'''

STATE_NAMES = dict(disconnected='已关闭', exited='已关闭', starting='正在启动',
                   running='运行中', faulted='固件异常', stopping='正在关闭', error='运行错误')
KEY_NAMES = dict(MENU='MENU', C1='C1', AF_ON='AF-ON', FN='Fn',
                 UP='▲\nDISP', DOWN='▼\n曝光', LEFT='◀\n连拍', RIGHT='▶\nISO', ENTER='ENTER',
                 PLAYBACK='播放', DELETE='删除 / C2',
                 REC='REC', SHUTTER_HALF='半按', SHUTTER='全按', MODE='MODE',
                 FRONT_LEFT='前拨轮左转', FRONT_RIGHT='前拨轮右转',
                 REAR_LEFT='后拨轮左转', REAR_RIGHT='后拨轮右转',
                 TOP_LEFT='右上拨轮左转', TOP_RIGHT='右上拨轮右转',
                 CONTROL_LEFT='控制轮左转', CONTROL_RIGHT='控制轮右转',
                 MODE_STILL='照片', MODE_MOVIE='录像', MODE_SQ='S&Q')


def label(text='', style=None, wrap=False):
    widget = Gtk.Label(label=text, xalign=0)
    if style:
        widget.get_style_context().add_class(style)
    if wrap:
        widget.set_line_wrap(True)
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_max_width_chars(80)
    return widget


class SnapshotPoller:
    """One outstanding capture; idle/error backoff never abandons a pending capture."""
    def __init__(self, interval=10.0):
        self.interval = interval
        self.next_at = 0.0
        self.inflight = False
        self.before = None
        self.saw_busy = False
        self.delay = interval
        self.error_before = ''
        self.event_before = None
        self.follow_up_at = None
        self.retry_at = 0.0
        self.input_event = None

    @staticmethod
    def token(state):
        frame = state.get('snapshot') or {}
        return tuple(frame.get(key) for key in ('number', 'sequence', 'sha256', 'captured_at'))

    def observe(self, state, now):
        if state.get('state') != 'running':
            self.inflight = False
            return
        events = state.get('events') or []
        submitted = next((event for event in events if event.get('kind') == 'input'), None)
        if submitted and submitted.get('id') != self.input_event:
            self.input_event = submitted.get('id')
            self.after_input(now)
        if not self.inflight:
            return
        busy = bool(state.get('busy') or state.get('pending'))
        self.saw_busy |= busy
        changed = self.token(state) != self.before
        failed = bool(state.get('error')) and state.get('error') != self.error_before
        completed_event = events and events[0].get('id') != self.event_before and not busy
        if changed or failed or completed_event or (self.saw_busy and not busy):
            self.inflight = False
            self.delay = min(60.0, max(self.interval, self.delay * 2)) if failed or not changed else self.interval
            self.next_at = now + self.delay
            self.retry_at = self.next_at if failed or not changed else 0.0

    def after_input(self, now, delay=.2):
        # Give the firmware a short render window; a newer input supersedes an older follow-up.
        self.follow_up_at = now + delay

    def request(self, vm, state, now, force=False):
        if state.get('continuous_display') and not force:
            return False
        follow_up = self.follow_up_at is not None and (force or now >= self.follow_up_at)
        waiting_for_input = self.follow_up_at is not None and now < self.follow_up_at
        periodic = bool(self.interval) and now >= self.next_at and not waiting_for_input
        allowed = force or (bool(self.interval) and (follow_up or periodic))
        if (state.get('state') != 'running' or self.inflight or state.get('busy')
                or state.get('pending') or not allowed or (not force and now < self.retry_at)):
            return False
        self.before = self.token(state)
        self.error_before = state.get('error', '')
        events = state.get('events') or []
        self.event_before = events[0].get('id') if events else None
        try:
            vm.enqueue({'action': 'snapshot'})
        except (ValueError, RuntimeError, OSError):
            self.delay = min(60.0, max(2.0, self.delay * 2))
            self.next_at = self.retry_at = now + self.delay
            if follow_up:
                self.follow_up_at = self.next_at
            raise
        if follow_up:
            self.follow_up_at = None
        self.inflight, self.saw_busy = True, False
        return True

    def set_interval(self, seconds, now):
        self.interval = self.delay = float(seconds)
        self.next_at = now + self.interval
        self.retry_at = 0.0
        self.follow_up_at = None


class CameraUI:
    """Injected VM owns its own lifecycle; no shell, HTTP server, or second display."""
    def __init__(self, vm, *, timer=True, clock=time.monotonic):
        self.vm, self.clock = vm, clock
        self.closed = self.closing = False
        self.reinitializing = False
        self.development_busy = False
        self.reset_dialog = None
        self.state = vm.status()
        self.wifi_syncing = False
        self.wifi_confirmed = False
        self.buttons = {}
        self.mode_popover = None
        self.poller = SnapshotPoller()
        self.pixbuf = self.png_bytes = None
        self.frame_token = None
        self.display_frame = {}
        self.local_error = ''
        self.drag = None
        self.wheel_widgets = []
        self.last_input = {}
        self.last_status = self.last_details = None
        self.source_id = 0
        self.lcd_idle_pending = False
        self.vm.lcd_changed = self._notify_lcd
        self.provider = Gtk.CssProvider()
        self.provider.load_from_data(CSS)
        self.window = Gtk.Window(title='SONY α7C II')
        self.window.set_default_size(1360, 930)
        self.window.set_size_request(1024, 760)
        self.window.get_style_context().add_provider_for_screen(
            self.window.get_screen(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.connect('delete-event', self._close)
        self.window.connect('key-press-event', self._key_press)
        self.window.connect('focus-out-event', self._cancel_drag)
        self.outer = Gtk.ScrolledWindow()
        self.outer.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.window.add(self.outer)
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.root.set_border_width(14)
        self.outer.add(self.root)
        self._build_header()
        self.camera = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.camera.get_style_context().add_class('camera')
        self.root.pack_start(self.camera, True, True, 0)
        self._build_top()
        self._build_back()
        self._build_footer()
        self.input_bindings = None
        if getattr(vm, 'supports_input_lifecycle', False):
            from menu_live import camera_input_module
            self.input_bindings = camera_input_module().attach_gtk(self)
        self.window.show_all()
        self.update(self.state)
        if timer:
            self.source_id = GLib.timeout_add(16, self.tick)

    def _build_header(self):
        self.status_label = label('', 'status')
        self.spinner = Gtk.Spinner()
        self.capture_status = label('', 'pill-badge')
        self.frame_label = label('', 'frame-meta', wrap=True)
        self.wheel_note = label('', 'hint')
        self.feedback = label('', 'feedback', wrap=True)
        self.refresh = Gtk.Button(label='刷新 LCD')
        self.refresh.set_size_request(96, 44)
        self.refresh.get_accessible().set_name('手动刷新 LCD 快照')
        self.refresh.connect('clicked', lambda _: self.capture())
        self.interval = Gtk.ComboBoxText()
        for seconds in (0, 3, 10, 30):
            self.interval.append(str(seconds), '关闭' if not seconds else f'{seconds} 秒')
        self.interval.set_active_id('10')
        self.interval.connect('changed', self._interval_changed)

    def _build_top(self):
        top = Gtk.Box(spacing=12)
        top.get_style_context().add_class('top')
        title_row = Gtk.Box(spacing=10)
        title_row.set_valign(Gtk.Align.CENTER)
        title_row.pack_start(label('SONY', 'brand'), False, False, 0)
        title_row.pack_start(label('α7C II', 'title'), False, False, 0)
        title_row.pack_start(self.status_label, False, False, 0)
        title_row.pack_start(self.spinner, False, False, 0)
        top.pack_start(title_row, True, True, 0)

        mode_cluster = Gtk.Box(spacing=8)
        mode_cluster.get_style_context().add_class('top-cluster')
        mode_cluster.set_valign(Gtk.Align.CENTER)
        modes = Gtk.Box(spacing=5)
        modes.set_valign(Gtk.Align.CENTER)
        for name in ('MODE_STILL', 'MODE_MOVIE', 'MODE_SQ'):
            modes.pack_start(self._button(name), False, False, 0)
        mode_cluster.pack_start(modes, False, False, 0)
        mode = self._button('MODE', 'MODE', 'mode')
        mode.set_size_request(58, 58)
        mode_cluster.pack_start(mode, False, False, 0)
        top.pack_start(mode_cluster, False, False, 0)

        shutter_cluster = Gtk.Box(spacing=8)
        shutter_cluster.get_style_context().add_class('top-cluster')
        shutter_cluster.set_valign(Gtk.Align.CENTER)
        shutter_cluster.pack_start(self._dial('前拨轮', 'FRONT', horizontal=True), False, False, 0)
        shutter_cluster.pack_start(self._button('REC', 'REC', 'record'), False, False, 0)
        shutter_cluster.pack_start(self._button('SHUTTER_HALF', '半按'), False, False, 0)
        shutter_cluster.pack_start(self._button('SHUTTER', '全按', 'shutter-full'), False, False, 0)
        top.pack_start(shutter_cluster, False, False, 0)

        power = Gtk.Box(spacing=5)
        power.get_style_context().add_class('top-cluster')
        power.set_valign(Gtk.Align.CENTER)
        self.on = Gtk.Button(label='ON')
        self.off = Gtk.Button(label='OFF')
        for button, enabled in ((self.on, True), (self.off, False)):
            button.set_size_request(54, 44)
            button.connect('clicked', lambda _, value=enabled: self.power(value))
            button.get_accessible().set_name(('ON 启动' if enabled else 'OFF 停止') + '本窗口拥有的 VM')
            power.pack_start(button, False, False, 0)
        self.on.get_style_context().add_class('power')
        top.pack_start(power, False, False, 0)
        self.camera.pack_start(top, False, False, 0)

    def _button(self, name, text=None, style=None):
        button = Gtk.Button(label=text or KEY_NAMES.get(name, name))
        if text in ('‹', '›', '⌃', '⌄'):
            button.get_style_context().add_class('direction')
        if name in ('UP', 'DOWN', 'LEFT', 'RIGHT'):
            button.get_style_context().add_class('dpad')
            child = getattr(button, 'get_child', lambda: None)()
            if child is not None and hasattr(child, 'set_justify'):
                child.set_justify(Gtk.Justification.CENTER)
        button.set_size_request(44, 44)
        button.set_valign(Gtk.Align.CENTER)
        if style:
            button.get_style_context().add_class(style)
        button.connect('clicked', lambda _: self.send(name))
        prefix = name.rsplit('_', 1)[0]
        if prefix in ('FRONT', 'REAR', 'TOP', 'CONTROL'):
            button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            button.connect('scroll-event', self._scroll, prefix)
        self.buttons[name] = button
        return button

    def _dial(self, title, prefix, horizontal=False):
        group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL, spacing=3)
        group.set_valign(Gtk.Align.CENTER if horizontal else Gtk.Align.END)
        if title:
            lbl = label(title, 'hint')
            lbl.set_halign(Gtk.Align.CENTER)
            lbl.set_valign(Gtk.Align.CENTER)
            group.pack_start(lbl, False, False, 0)
        row = Gtk.Box(spacing=4)
        row.pack_start(self._button(prefix + '_LEFT', '‹'), False, False, 0)
        row.pack_start(self._button(prefix + '_RIGHT', '›'), False, False, 0)
        group.pack_start(row, False, False, 0)
        surface = Gtk.EventBox()
        surface.set_visible_window(False)
        surface.add(group)
        self._scrollable(surface, prefix)
        return surface

    def _build_back(self):
        back = Gtk.Box(spacing=14)
        lcd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lcd.get_style_context().add_class('lcd')
        self.lcd = Gtk.DrawingArea()
        self.lcd.set_size_request(480, 360)
        self.lcd.get_style_context().add_class('lcd-screen')
        self.lcd.get_accessible().set_role(Atk.Role.IMAGE)
        self.lcd.get_accessible().set_name('LCD 本次 VM 图像，尚无画面')
        self.lcd.connect('draw', self._draw_lcd)
        screen = Gtk.AspectFrame(xalign=.5, yalign=.5, ratio=4 / 3, obey_child=False)
        screen.set_shadow_type(Gtk.ShadowType.NONE)
        screen.add(self.lcd)
        lcd.pack_start(screen, True, True, 0)
        back.pack_start(lcd, True, True, 0)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        controls.get_style_context().add_class('controls-panel')
        controls.set_size_request(336, -1)

        # 第一行：MENU / C1 / 后拨轮 / 右上拨轮
        row1 = Gtk.Box(spacing=6)
        menu_btn = self._button('MENU', 'MENU')
        menu_btn.set_valign(Gtk.Align.END)
        c1_btn = self._button('C1', 'C1')
        c1_btn.set_valign(Gtk.Align.END)
        row1.pack_start(menu_btn, True, True, 0)
        row1.pack_start(c1_btn, False, False, 0)
        row1.pack_start(self._dial('后拨轮', 'REAR'), False, False, 0)
        row1.pack_start(self._dial('右上拨轮', 'TOP'), False, False, 0)
        controls.pack_start(row1, False, False, 0)

        # 第二行：AF-ON
        row2 = Gtk.Box(spacing=6)
        row2.pack_start(self._button('AF_ON', 'AF-ON', 'round'), True, True, 0)
        controls.pack_start(row2, False, False, 0)

        # 第三行：Fn
        row3 = Gtk.Box(spacing=6)
        row3.pack_start(self._button('FN', 'Fn'), True, True, 0)
        controls.pack_start(row3, False, False, 0)

        # 第四行：一体化五维控制轮（左上/右上=控制轮旋转，上=DISP、右=ISO、下=曝光、左=连拍、中=ENTER）
        wheel_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wheel_area.set_valign(Gtk.Align.CENTER)
        self.ring = Gtk.EventBox()
        self.ring.set_halign(Gtk.Align.CENTER)
        self.ring.set_size_request(216, 216)
        self.ring.get_style_context().add_class('wheel')
        self.ring.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK)
        self.ring.connect('button-press-event', self._drag_start)
        self.ring.connect('motion-notify-event', self._drag_move)
        self.ring.connect('button-release-event', self._drag_end)
        self.ring.connect('grab-broken-event', self._cancel_drag)
        grid = Gtk.Grid(column_spacing=4, row_spacing=4)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_valign(Gtk.Align.CENTER)
        for name, text, x, y, style in (('CONTROL_LEFT', '↶', 0, 0, 'round'),
                                        ('UP', '▲\nDISP', 1, 0, 'round'),
                                        ('CONTROL_RIGHT', '↷', 2, 0, 'round'),
                                        ('LEFT', '◀\n连拍', 0, 1, 'round'),
                                        ('ENTER', 'ENTER', 1, 1, 'round'),
                                        ('RIGHT', '▶\nISO', 2, 1, 'round'),
                                        ('DOWN', '▼\n曝光', 1, 2, 'round')):
            btn = self._button(name, text, style)
            if name in ('CONTROL_LEFT', 'CONTROL_RIGHT'):
                btn.get_style_context().add_class('wheel-step')
                btn.set_size_request(44, 44)
            else:
                btn.set_size_request(46, 46)
            grid.attach(btn, x, y, 1, 1)
        self.ring.add(grid)
        self._scrollable(self.ring, 'CONTROL')
        wheel_area.pack_start(self.ring, False, False, 0)
        controls.pack_start(wheel_area, True, False, 0)

        # 底部行：播放 / 删除 (C2)
        row6 = Gtk.Box(spacing=8, homogeneous=True)
        row6.pack_start(self._button('PLAYBACK', '播放'), True, True, 0)
        row6.pack_start(self._button('DELETE', '删除 / C2'), True, True, 0)
        controls.pack_end(row6, False, False, 0)

        back.pack_end(controls, False, False, 0)
        self.camera.pack_start(back, True, True, 0)

    def _build_footer(self):
        row = Gtk.Box(spacing=10)
        row.get_style_context().add_class('toolbar')

        self.sd_label = label('SD 未确认', 'pill-badge')
        self.sd_label.set_valign(Gtk.Align.CENTER)
        row.pack_start(self.sd_label, False, False, 0)
        self.sd_action = Gtk.Button(label='安全拔出 SD')
        self.sd_action.set_size_request(-1, 44)
        self.sd_action.connect('clicked', lambda _: self.change_sd())
        self.sd_action.get_accessible().set_name('虚拟 SD 插入或安全拔出')
        row.pack_start(self.sd_action, False, False, 0)

        row.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 2)

        self.usb_connected = False
        self.usb_run = None
        self.usb_busy = False
        self.usb_button = Gtk.Button(label='连接电脑')
        self.usb_button.set_size_request(-1, 44)
        self.usb_button.get_accessible().set_name('将虚拟相机通过 USB 连接本机电脑')
        self.usb_button.connect('clicked', lambda _: self.connect_computer())
        self.usb_button.set_tooltip_text('通过本机虚拟 USB 控制器连接；以宿主实际枚举和原相机响应为准')
        row.pack_start(self.usb_button, False, False, 0)

        net = Gtk.Box(spacing=6)
        net.set_valign(Gtk.Align.CENTER)
        self.wifi_label = label('Wi-Fi 关', 'hint')
        net.pack_start(self.wifi_label, False, False, 0)
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.set_valign(Gtk.Align.CENTER)
        self.wifi_switch.set_active(False)
        self.wifi_switch.get_accessible().set_name(
            '隔离 Wi-Fi 开关：开启后宿主应能 ping 通，关闭后不通')
        self.wifi_switch.connect('notify::active',
                                 lambda widget, _: self.wifi(widget.get_active()))
        net.pack_start(self.wifi_switch, False, False, 0)
        row.pack_start(net, False, False, 4)

        self.reset_button = Gtk.Button(label='重置设置')
        self.reset_button.set_size_request(-1, 44)
        self.reset_button.get_style_context().add_class('danger')
        self.reset_button.get_accessible().set_name('销毁当前相机配置并重新初始化，保留 SD')
        self.reset_button.connect('clicked', lambda _: self.request_reinitialize())
        row.pack_end(self.reset_button, False, False, 0)
        self.root.pack_start(row, False, False, 0)

        self.error_label = label('', 'error', wrap=True)
        self.error_label.set_no_show_all(True)
        self.error_label.get_accessible().set_role(Atk.Role.ALERT)
        self.root.pack_start(self.error_label, False, False, 0)

        self.drawers = Gtk.Box(spacing=12, homogeneous=True)
        details_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        details_card.get_style_context().add_class('drawer-card')
        self.details = Gtk.Expander(label='快捷键与日志')
        self.detail_text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.detail_text.get_accessible().set_name('最近操作记录和每个控件的禁用原因')
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 150)
        scroll.add(self.detail_text)
        self.details.add(scroll)
        details_card.pack_start(self.details, False, False, 0)
        self.drawers.pack_start(details_card, True, True, 0)
        self._build_development()
        self.root.pack_start(self.drawers, False, False, 0)

    def _build_development(self):
        dev_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        dev_card.get_style_context().add_class('drawer-card')
        panel = Gtk.Expander(label='固件开发')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_border_width(8)
        files = Gtk.Box(spacing=6)
        self.development_source = Gtk.FileChooserButton(title='选择测试文件', action=Gtk.FileChooserAction.OPEN)
        self.development_source.get_accessible().set_name('本机测试文件')
        files.pack_start(self.development_source, True, True, 0)
        files.pack_start(label('路径', 'hint'), False, False, 0)
        self.development_target = Gtk.Entry()
        self.development_target.set_text('/usr/lib/appFw.so')
        self.development_target.get_accessible().set_name('测试文件在相机内的绝对路径')
        files.pack_start(self.development_target, True, True, 0)
        box.pack_start(files, False, False, 0)
        row = Gtk.Box(spacing=6)
        self.development_buttons = {}
        for action, title in (('stage', '暂存测试文件'), ('original', '下次使用原版'), ('readback', '核对 guest 文件')):
            button = Gtk.Button(label=title)
            button.set_size_request(-1, 38)
            button.connect('clicked', lambda _, value=action: self.development_action(value))
            button.get_accessible().set_name(title)
            self.development_buttons[action] = button
            row.pack_start(button, False, False, 0)
        box.pack_start(row, False, False, 0)
        toggles = Gtk.Box(spacing=12)
        self.development_storage_sync = False
        self.development_storage = Gtk.CheckButton(label='使用内部持久磁盘')
        self.development_storage.set_tooltip_text('原启动使用持久内部盘；兼容启动可在停止后选择内存镜像或内部盘')
        self.development_storage.connect('toggled', self._development_storage_toggled)
        toggles.pack_start(self.development_storage, False, False, 0)
        self.development_ram_sync = False
        self.development_ram = Gtk.CheckButton(label='QEMU RAM 会话')
        self.development_ram.set_tooltip_text('先构建 RAM 候选；保存后从同一内部盘继续原程序。Sony WBI 独立未完成。')
        self.development_ram.connect('toggled', self._development_ram_toggled)
        toggles.pack_start(self.development_ram, False, False, 0)
        box.pack_start(toggles, False, False, 0)
        actions = Gtk.Box(spacing=6)
        restart = Gtk.Button(label='关闭后重新启动')
        restart.set_size_request(-1, 38)
        restart.connect('clicked', lambda _: self.development_action('restart'))
        self.development_buttons['restart'] = restart
        actions.pack_start(restart, False, False, 0)
        for action, title in (('ram_save', '保存 RAM 并退出'), ('ram_restore', '从 RAM 恢复')):
            button = Gtk.Button(label=title)
            button.set_size_request(-1, 38)
            button.connect('clicked', lambda _, value=action: self.development_action(value))
            button.get_accessible().set_name(title)
            self.development_buttons[action] = button
            actions.pack_start(button, False, False, 0)
        box.pack_start(actions, False, False, 0)
        self.development_status = label('', 'hint', wrap=True)
        self.development_status.get_accessible().set_role(Atk.Role.STATUSBAR)
        box.pack_start(self.development_status, False, False, 0)
        panel.add(box)
        dev_card.pack_start(panel, False, False, 0)
        self.drawers.pack_start(dev_card, True, True, 0)

    def _development_storage_toggled(self,widget):
        if self.development_storage_sync:return
        try:self.vm.configure_storage(widget.get_active());self.local_error=''
        except (ValueError,RuntimeError,OSError,AttributeError) as error:self.local_error='内部存储：'+str(error)
        self.update(self.vm.status())

    def _development_ram_toggled(self,widget):
        if not self.development_ram_sync:self.development_action('ram_mode')

    def development_action(self,action):
        if self.closing or self.reinitializing or self.development_busy:return False
        source=self.development_source.get_filename();target=self.development_target.get_text()
        ram_mode=self.development_ram.get_active()
        if action=='stage' and not source:
            self.local_error='请先选择本机测试文件';self.update(self.vm.status());return False
        if action in ('restart','ram_save') and self.input_bindings is not None and not self.release_inputs():return False
        self.development_busy=True;self.local_error='';self.update(self.vm.status())
        def worker():
            message='';error=''
            try:
                if action=='stage':
                    result=self.vm.select_firmware_test(source,target)
                    message='测试文件已暂存：'+result['guest_path']+'；启动后可核对 guest 文件'
                elif action=='original':
                    self.vm.select_firmware_test(destination=target);message='下次启动已选择原版固件'
                elif action=='readback':
                    self.vm.check_firmware_test();message='实际 guest 读回已排队，等待权限、摘要与长度结果'
                elif action=='restart':
                    self.vm.close();self.vm.start();message='原实例已保存并退出，新启动请求已提交'
                elif action=='ram_mode':
                    self.vm.configure_ram(ram_mode);message='下次启动启用 RAM 保存/恢复' if ram_mode else '下次启动使用普通冷启动'
                elif action=='ram_save':
                    self.vm.save_ram();message='RAM、设置与 SD 已保存，原 VM 已正常退出'
                elif action=='ram_restore':
                    self.vm.restore_ram();message='RAM 恢复已请求，等待原 AP 续行校验'
                else:raise ValueError('未知开发动作')
            except (OSError,ValueError,RuntimeError) as problem:error=str(problem)
            def finished():
                self.development_busy=False
                if self.closed:return False
                self.local_error=('固件开发：'+error) if error else ''
                if message:self.development_status.set_text(message)
                self.update(self.vm.status());return False
            GLib.idle_add(finished)
        threading.Thread(target=worker,name='camera-firmware-development',daemon=True).start();return True

    def reason(self, name):
        entry = self.state.get('controls', {}).get(name)
        if not entry:
            return '后端 registry 未提供此控件'
        if not entry.get('available'):
            return entry.get('unavailable_reason') or '键码未知或当前通道不可用'
        if self.closing or self.reinitializing or self.development_busy:
            return '正在关闭或切换本窗口拥有的 VM'
        if self.state.get('state') != 'running':
            return 'VM 尚未运行，请 ON 并等待启动完成'
        if name=='MODE' and (not isinstance(entry.get('positions'),dict) or not entry['positions']):
            return '后端 registry 未提供 MODE 选位'
        # The backend serializes its bounded queue; LCD polling must not discard camera keys.
        return ''

    def send(self, name,*,position=None):
        self.state = self.vm.status()
        reason = self.reason(name)
        if not reason and name=='MODE' and position is not None and position not in self.state['controls']['MODE']['positions']:
            reason='MODE 选位已不在后端 registry 中'
        if reason:
            self.feedback.set_text('未发送：' + reason)
            return False
        if name=='MODE' and position is None:return self._open_mode_positions()
        try:
            command=({'action':'position','key':name,'position':position} if name=='MODE' else {'action':'key','key':name})
            self.vm.enqueue(command)
            self.local_error = ''
            self.feedback.set_text(name + (f' / {position}' if name=='MODE' else '') + ' 已排队；实际响应以固件新画面为准。')
            self.poller.after_input(self.clock())
            self.update(self.vm.status())
            return True
        except (ValueError, RuntimeError, OSError) as error:
            self.local_error = '输入未发送：' + str(error)
            self.update(self.vm.status())
            return False

    def _open_mode_positions(self):
        if self.mode_popover is not None:self.mode_popover.destroy()
        self.mode_popover=Gtk.Popover.new(self.buttons['MODE'])
        self.mode_popover.get_style_context().add_class('mode-positions')
        self.mode_popover.set_position(Gtk.PositionType.BOTTOM)
        self.mode_popover.get_accessible().set_name('MODE 选位；确认仅排队，响应以固件 LCD 为准')
        choices=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=4)
        choices.set_border_width(8)
        for position in self.state['controls']['MODE']['positions']:
            button=Gtk.Button(label=position)
            button.connect('clicked',lambda _,value=position:self._choose_mode(value))
            choices.pack_start(button,False,False,0)
        self.mode_popover.add(choices)
        self.mode_popover.connect('key-press-event',self._mode_key_press)
        self.mode_popover.show_all();self.mode_popover.popup()
        choices.get_children()[0].grab_focus()
        return True

    def _choose_mode(self,position):
        self.mode_popover.popdown()
        return self.send('MODE',position=position)

    def _mode_key_press(self,popover,event):
        key=Gdk.keyval_name(event.keyval)
        if key=='Escape':popover.popdown();return True
        choices=popover.get_child().get_children();focus=self.window.get_focus()
        if key in ('Up','Down'):
            index=choices.index(focus) if focus in choices else 0
            choices[(index+(1 if key=='Down' else -1))%len(choices)].grab_focus();return True
        if key in ('Return','KP_Enter') and focus in choices:
            self._choose_mode(focus.get_label());return True
        return False

    def wifi(self, enabled):
        if self.closing or self.wifi_syncing:
            return False
        try:
            self.vm.enqueue({'action': 'wifi', 'enabled': bool(enabled)})
        except (ValueError, RuntimeError, OSError) as error:
            self.local_error = 'Wi-Fi 未发送：' + str(error)
            self.wifi_syncing = True
            try:
                self.wifi_switch.set_active(self.wifi_confirmed)
            finally:
                self.wifi_syncing = False
            self.update(self.vm.status())
            return False
        self.feedback.set_text('Wi-Fi 切换已排队；以实际接口状态与宿主 ping 结果为准。')
        self.update(self.vm.status())
        return True

    def change_sd(self):
        state=self.vm.status()
        card=state.get('sd_card') or {}
        if self.closing or state.get('state')!='running' or card.get('state') not in ('present','absent'):
            return False
        try:
            self.vm.enqueue({'action':'sd_card','present':card['state']=='absent'})
        except (ValueError,RuntimeError,OSError) as error:
            self.local_error='SD 操作未发送：'+str(error)
            self.update(self.vm.status());return False
        self.feedback.set_text('正在等待原固件处理 SD 变化；完成后才更新介质状态。')
        self.update(self.vm.status());return True

    def connect_computer(self):
        state = self.vm.status()
        if self.closing or self.usb_busy or state.get('state') != 'running' or not state.get('run'):
            return False
        self.usb_busy = True
        self.update(state)
        run = state['run']
        operation = 'disconnect' if self.usb_connected else 'connect'
        def worker():
            import runpy
            from pathlib import Path
            tool = Path(__file__).resolve().with_name('usb_ui.py')
            try:
                result = runpy.run_path(str(tool))['action'](run, operation)
            except Exception as error:
                result = {'phase':'blocked','blocked_reason':{'detail':str(error)},'host_enumerated':False}
            def completed():
                self.usb_busy = False
                if self.closed or self.vm.status().get('run') != run:
                    return False
                self.usb_connected = result.get('host_enumerated') is True
                if result.get('phase') in ('blocked','error','recovery_required'):
                    self.local_error = 'USB：' + str((result.get('blocked_reason') or {}).get('detail','连接未完成'))
                else:
                    self.local_error = ''
                    self.feedback.set_text('USB 已断开' if operation == 'disconnect' else
                                           'USB 宿主枚举已确认' if self.usb_connected else 'USB 正在等待宿主枚举')
                if not self.closed:
                    self.update(self.vm.status())
                return False
            GLib.idle_add(completed)
        threading.Thread(target=worker, name='camera-usb-computer', daemon=True).start()
        return True

    def power(self, on):
        if self.closing or self.reinitializing or self.development_busy:
            return
        self._cancel_drag()
        try:
            if not on and self.input_bindings is not None and not self.release_inputs():
                return
            if on:
                self.vm.start()
                self.pixbuf = self.png_bytes = self.frame_token = None
                self.display_frame = {}
                self.poller = SnapshotPoller(float(self.interval.get_active_id()))
                self.lcd.queue_draw()
            else:
                self.vm.stop()
            self.local_error = ''
        except (ValueError, RuntimeError, OSError) as error:
            self.local_error = 'VM 启停失败：' + str(error)
        self.update(self.vm.status())

    def capture(self, automatic=False):
        if self.reinitializing or self.development_busy:return False
        try:
            state = self.vm.status()
            now = self.clock()
            self.poller.observe(state, now)
            queued = self.poller.request(self.vm, state, now, force=not automatic)
            if queued and not automatic:
                self.feedback.set_text('LCD 快照已排队；等待后端校验。')
            self.update(state)
            return queued
        except (ValueError, RuntimeError, OSError) as error:
            self.local_error = 'LCD 快照请求失败：' + str(error)
            self.update(self.vm.status())
            return False

    def tick(self):
        if self.closed:
            return False
        if self.closing or self.reinitializing:
            return True
        try:
            self.capture(automatic=True)
        except (ValueError, RuntimeError, OSError) as error:
            self.local_error = '后端状态读取失败：' + str(error)
            self.error_label.set_text(self.local_error)
            self.error_label.show()
        return True

    def _interval_changed(self, combo):
        self.poller.set_interval(int(combo.get_active_id()), self.clock())

    def request_reinitialize(self):
        state=self.vm.status()
        if (self.closing or self.reinitializing or self.reset_dialog is not None
                or not state.get('settings_persistent') or not state.get('settings_generation')
                or state.get('state') not in ('disconnected','exited') or not state.get('can_start')):
            return False
        dialog=Gtk.MessageDialog(transient_for=self.window,modal=True,
            message_type=Gtk.MessageType.WARNING,buttons=Gtk.ButtonsType.NONE,
            text='重新初始化当前相机配置？')
        dialog.set_title('重新初始化当前相机配置')
        instance=getattr(getattr(self.vm,'instance',None),'path','当前相机实例')
        dialog.format_secondary_text('实例：'+instance+'\n当前配置将恢复默认，下次从首设开始。\n'
            '保留虚拟 SD、原固件、overwrite 源文件、历史配置代和运行资料。')
        dialog.add_button('取消',Gtk.ResponseType.CANCEL)
        dialog.add_button('重新初始化并启动',Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)
        self.reset_dialog=dialog
        def response(widget,choice):
            self.reset_dialog=None
            widget.destroy()
            if choice==Gtk.ResponseType.ACCEPT:self._reinitialize_confirmed()
        dialog.connect('response',response)
        dialog.show_all()
        return True

    def _reinitialize_confirmed(self):
        state=self.vm.status()
        if (self.closing or self.reinitializing or state.get('state') not in ('disconnected','exited')
                or not state.get('can_start')):
            return False
        self.reinitializing=True
        self.root.set_sensitive(False)
        self.feedback.set_text('正在重新初始化配置；虚拟 SD 和历史资料保留。')
        def reset():
            error=''
            try:self.vm.reset_configuration(confirmed=True)
            except (ValueError,RuntimeError,OSError) as failure:error=str(failure)
            GLib.idle_add(self._reinitialize_finished,error)
        threading.Thread(target=reset,name='camera-instance-reinitialize',daemon=True).start()
        return True

    def _reinitialize_finished(self,error):
        self.reinitializing=False
        self.root.set_sensitive(True)
        if error:
            self.local_error='配置重初始化失败；未启动新 VM：'+error
            self.update(self.vm.status())
        else:
            self.feedback.set_text('配置已重新初始化；正在从首设启动，SD 保留。')
            self.power(True)
        return False

    def _notify_lcd(self):
        if not self.closed and not self.lcd_idle_pending:
            self.lcd_idle_pending = True
            GLib.idle_add(self._present_lcd, priority=GLib.PRIORITY_HIGH_IDLE)

    def _present_lcd(self):
        self.lcd_idle_pending = False
        if not self.closed:
            self._read_frame(self.vm.status())
        return False

    def _read_frame(self, state):
        # Retry a changed metadata version instead of pairing a PNG with the wrong frame.
        with self.vm.lock:
            png = self.vm.png
        token = SnapshotPoller.token(state)
        if token != SnapshotPoller.token(self.vm.status()):
            return
        frame = state.get('snapshot')
        if not png or not frame:
            return
        if token == self.frame_token and png is self.png_bytes:
            return
        try:
            if not isinstance(png, bytes) or len(png) > 8 * 1024 * 1024 or not png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('PNG 数据无效或过大')
            loader = GdkPixbuf.PixbufLoader.new_with_type('png')
            loader.write(png)
            loader.close()
            pixbuf = loader.get_pixbuf()
            if not pixbuf or pixbuf.get_width() != 640 or pixbuf.get_height() != 480:
                raise ValueError('LCD 图像尺寸应为 640 x 480')
            self.pixbuf, self.png_bytes, self.frame_token = pixbuf, png, token
            self.display_frame = dict(frame)
            if self.local_error.startswith('LCD 解码失败'):
                self.local_error = ''
            self.lcd.queue_draw()
        except (GLib.Error, ValueError) as error:
            self.local_error = 'LCD 解码失败，保留上一幅画面：' + str(error)

    def update(self, state):
        self.state = state
        self.poller.observe(state, self.clock())
        self._read_frame(state)
        name = STATE_NAMES.get(state.get('state'), str(state.get('state', '未知')))
        prefix = 'HOST STUB / ' if state.get('mock') else ('自定义覆盖 / ' if state.get('custom_firmware') else '')
        self.status_label.set_text(name)
        activity = state.get('busy') or ('排队中' if state.get('pending') else '')
        status_style = self.status_label.get_style_context()
        for cls in ('status-running', 'status-busy', 'status-error'):
            status_style.remove_class(cls)
        if state.get('state') in ('faulted', 'error'):
            status_style.add_class('status-error')
        elif activity or state.get('state') in ('starting', 'stopping'):
            status_style.add_class('status-busy')
        elif state.get('state') == 'running':
            status_style.add_class('status-running')
        self.spinner.start() if activity or state.get('state') in ('starting', 'stopping') else self.spinner.stop()
        self.on.set_sensitive(not(self.closing or self.development_busy) and state.get('can_start', state.get('state') in ('disconnected', 'exited', 'error')))
        self.off.set_sensitive(not(self.closing or self.development_busy) and state.get('can_stop', state.get('state') in ('starting', 'running')))
        self.reset_button.set_sensitive(not(self.closing or self.reinitializing or self.development_busy)
            and state.get('settings_persistent') is True and bool(state.get('settings_generation'))
            and state.get('state') in ('disconnected','exited') and bool(state.get('can_start')))
        self.reset_button.set_tooltip_text('请先 OFF 并等待配置和 SD 保存完成；仅复位当前设置，保留原前像、固件修改和 SD')
        wifi = state.get('wifi') or {}
        if state.get('state') != 'running':
            self.wifi_confirmed = False
        elif wifi.get('ok') is True:
            self.wifi_confirmed = wifi.get('enabled') is True
        wifi_pending = bool(state.get('pending') or state.get('busy'))
        self.wifi_label.set_text('Wi-Fi …' if wifi_pending else ('Wi-Fi 开' if self.wifi_confirmed else 'Wi-Fi 关'))
        self.wifi_switch.set_sensitive(not(self.closing or self.development_busy) and state.get('state') == 'running'
                                       and bool(state.get('usb_net')) and not wifi_pending)
        if not wifi_pending:
            self.wifi_syncing = True
            try:
                self.wifi_switch.set_active(self.wifi_confirmed)
            finally:
                self.wifi_syncing = False
        self.wifi_switch.set_tooltip_text(
            '切换失败：' + str(wifi.get('error')) if wifi.get('ok') is False else
            '隔离网络：开启后校验宿主 ping，关闭后校验接口状态和不可达')
        self.on.set_tooltip_text('启动原 kernel → init → init2 → 相机界面' if state.get('boot_profile')=='original-init-cold' else '启动本窗口拥有的 VM；真实机身电源事件未模拟')
        self.off.set_tooltip_text('关闭本窗口拥有的 VM；保留最近 LCD 并标明旧画面')
        card=state.get('sd_card') or {}
        card_state=card.get('state','unavailable')
        self.sd_label.set_text({'present':'SD 已插入','absent':'SD 已拔出','ejecting':'SD 正在拔出',
                                'inserting':'SD 正在插入','uncertain':'SD 状态未确认',
                                'unavailable':'SD 未确认'}.get(card_state,'SD 未确认'))
        if self.usb_run != state.get('run'):
            self.usb_run = state.get('run')
            self.usb_connected = False
        self.usb_button.set_label('断开电脑' if self.usb_connected else '连接电脑')
        self.usb_button.set_sensitive(not(self.closing or self.development_busy) and not self.usb_busy and state.get('state') == 'running')
        self.sd_action.set_label('插入 SD' if card_state=='absent' else '安全拔出 SD')
        self.sd_action.set_sensitive(not(self.closing or self.development_busy) and state.get('state')=='running' and
                                     not(state.get('busy') or state.get('pending')) and
                                     card.get('ok') is True and card_state in ('present','absent'))
        idle=not(self.closing or self.reinitializing or self.development_busy)
        stopped=state.get('state') in ('disconnected','exited','error') and state.get('can_start') is True
        self.development_storage_sync=True
        try:self.development_storage.set_active(state.get('persistent_storage') is True)
        finally:self.development_storage_sync=False
        self.development_storage.set_sensitive(idle and stopped and state.get('boot_profile')!='original-init-cold' and hasattr(self.vm,'configure_storage'))
        self.development_ram_sync=True
        try:self.development_ram.set_active(state.get('ram_enabled') is True)
        finally:self.development_ram_sync=False
        self.development_ram.set_sensitive(idle and stopped and state.get('boot_profile')=='original-init-cold' and hasattr(self.vm,'configure_ram'))
        for action,button in self.development_buttons.items():
            available=hasattr(self.vm,'select_firmware_test') if action in ('stage','original') else True
            ready=stopped if action in ('stage','original') else state.get('state')=='running'
            if action=='ram_save':ready=state.get('state')=='running' and state.get('ram_enabled') is True and hasattr(self.vm,'save_ram')
            elif action=='ram_restore':ready=stopped and state.get('ram_enabled') is True and bool(state.get('ram_snapshot')) and hasattr(self.vm,'restore_ram')
            button.set_sensitive(idle and available and ready)
        verification=state.get('firmware_verification')
        if state.get('ram_restored') is True:
            self.development_status.set_text('RAM 恢复通过：同一原程序、内部盘和新菜单画面已核对')
        elif stopped and state.get('ram_snapshot'):
            self.development_status.set_text('RAM 已保存且原 VM 已退出；可从同一内部盘恢复')
        elif verification:
            self.development_status.set_text('原 guest 文件核对通过：'+verification['path'] if verification.get('guest_readback_verified') else '原 guest 文件核对未通过：'+str(verification.get('error','unknown')))
        input_error = (state.get('input_state') or {}).get('error', '')
        error = '\n'.join(filter(None, (state.get('error'), self.local_error, input_error)))
        self.error_label.set_text(error)
        self.error_label.set_visible(bool(error))
        registry = state.get('controls', {})
        for symbol, button in self.buttons.items():
            entry = registry.get(symbol, {})
            reason = self.reason(symbol)
            verified = entry.get('verification', '已验证' if entry.get('verified') else '未验证')
            text = ' / '.join(filter(None, (entry.get('label', KEY_NAMES.get(symbol, symbol)), symbol,
                                           verified, entry.get('note'), reason)))
            button.set_sensitive(not reason)
            button.set_tooltip_text(text)
            button.get_accessible().set_name(text)
        for widget, prefix_name in self.wheel_widgets:
            reason = self.reason(prefix_name + '_LEFT') or self.reason(prefix_name + '_RIGHT')
            widget.set_tooltip_text(reason or '滚轮或拖动外圈；每次手势发送一个独立拨轮符号')
        ring_style = self.ring.get_style_context()
        if self.reason('CONTROL_LEFT') and self.reason('CONTROL_RIGHT'):
            ring_style.add_class('wheel-off')
        else:
            ring_style.remove_class('wheel-off')
        self.wheel_note.set_text('控制轮 / ' + ('当前通道不可用' if self.reason('CONTROL_LEFT') else '外圈可拖动；语义以固件为准'))
        waiting = self.poller.inflight or bool(state.get('pending') or state.get('busy'))
        self.refresh.set_sensitive(not self.closing and state.get('state') == 'running' and not waiting)
        if state.get('continuous_display'):
            capture_text = ('LCD：' + state['lcd_stream_error']) if state.get('lcd_stream_error') else '实时 LCD · 独立显示通道'
        elif self.poller.inflight:
            capture_text = '正在校验新画面'
        elif self.poller.follow_up_at is not None and self.poller.interval:
            capture_text = '按键后刷新已计划'
        elif not self.poller.interval:
            capture_text = '自动快照已关闭'
        elif self.poller.delay > self.poller.interval:
            capture_text = f'快照失败退避 · {self.poller.delay:g}s'
        else:
            capture_text = ''
        self.capture_status.set_text(capture_text)
        self.capture_status.set_visible(bool(capture_text))
        stale = False
        if self.pixbuf:
            stale = (state.get('stale', False) or state.get('state') != 'running' or bool(error)
                     or self.frame_token != SnapshotPoller.token(state))
            frame = self.display_frame
            freshness = '旧画面 / 当前画面未确认' if stale else '本次后端已校验快照'
            source=('模拟灰度预览 / AP已消费 / 非CP面板' if str(frame.get('source','')).startswith('AP VDT luma mirror') else
                    '显示帧' if frame.get('source') in ('QMP ramfb display','continuous QEMU ramfb') else
                    '像素提交 '+str(frame.get('pixel_source_seq','?')))
            self.frame_label.set_text(prefix + freshness + f' / #{frame.get("number", "?")} / {source} / 640 x 480')
        else:
            self.frame_label.set_text(prefix + ('等待后端首幅图像' if state.get('state') == 'running' else '尚无本次 VM 图像 / ON 启动'))
            self.lcd.queue_draw()
        if stale:
            self.lcd.get_style_context().add_class('lcd-stale')
        else:
            self.lcd.get_style_context().remove_class('lcd-stale')
        self.lcd.get_accessible().set_name('LCD / ' + self.frame_label.get_text())
        events = state.get('events') or []
        event_key = events[0].get('id') if events else None
        if event_key is not None and event_key != self.last_status:
            self.last_status = event_key
            self.feedback.set_text(events[0].get('message', ''))
        input_hint = ('快捷键：方向键/Enter/M/Esc/Delete；F1=C1，F2=C2，A=AF-ON，F=Fn，P=播放，R=REC，H=半按，S=全按；'
                      'Q/E=前轮，[/]=后轮，,/.=控制轮；1/2/3=照片/录像/S&Q；F5–F12=AUTO/P/A/S/M/MR1/MR2/MR3。'
                      if self.input_bindings is not None else '快捷键：方向键 / Enter / M / Esc / Delete；')
        detail = '\n'.join([input_hint + 'Tab 切换控件，Space 激活焦点。',
                           'ON / OFF 仅管理 owned VM，真实电源未模拟。', '',
                           '最近操作（输入已提交不代表固件功能完成）'] +
                           [str(event.get('message', '')) for event in events[:12]] + ['\n全部按键 / registry'] +
                           [f'{symbol} / {entry.get("label", symbol)} / {entry.get("verification", "未验证")} / '
                            + (self.reason(symbol) or '可以排队，响应以固件为准') + ' / ' + entry.get('note', '')
                            for symbol, entry in registry.items()])
        if detail != self.last_details:
            self.detail_text.get_buffer().set_text(detail)
            self.last_details = detail

    def lcd_point(self, x, y, clamp=False):
        """Widget coordinates -> firmware 640x480 touch pixel via the _draw_lcd mapping.

        Returns None outside the drawn image unless clamp holds the point inside;
        begin must reject black bars, held move/end may clamp.
        """
        width, height = self.lcd.get_allocated_width(), self.lcd.get_allocated_height()
        if not (math.isfinite(x) and math.isfinite(y)):  # NaN/inf have no pixel; never clamp them
            return None
        scale = min(width / 640, height / 480)
        if scale <= 0:
            return None
        px = (x - (width - 640 * scale) / 2) / scale
        py = (y - (height - 480 * scale) / 2) / scale
        if abs(width - 640 * scale) < 1.0 and -0.5 <= px < 0:
            px = 0.0
        if abs(height - 480 * scale) < 1.0 and -0.5 <= py < 0:
            py = 0.0
        if not 0 <= px < 640 or not 0 <= py < 480:
            if not clamp:
                return None
            px, py = min(639.0, max(0.0, px)), min(479.0, max(0.0, py))
        return int(px), int(py)

    def _draw_lcd(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        cr.set_source_rgb(8 / 255, 11 / 255, 12 / 255)
        cr.paint()
        if self.pixbuf is not None:
            scale = min(width / 640, height / 480)
            cr.save()
            cr.translate((width - 640 * scale) / 2, (height - 480 * scale) / 2)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgba(0.28, 0.35, 0.37, 0.18)
            cr.set_line_width(1.0)
            for frac in (1 / 3, 2 / 3):
                cr.move_to(width * frac, 16)
                cr.line_to(width * frac, height - 16)
                cr.move_to(16, height * frac)
                cr.line_to(width - 16, height * frac)
            cr.stroke()
            vm_state = self.state.get('state')
            prompt = '正在启动…' if vm_state in ('running', 'starting') else '点击 ON 开机'
            layout = widget.create_pango_layout(prompt)
            layout.set_alignment(Pango.Alignment.CENTER)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgb(.68, .74, .72)
            cr.move_to((width - tw) / 2, (height - th) / 2)
            PangoCairo.show_layout(cr, layout)

    def _key_press(self, window, event):
        if event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        key = Gdk.keyval_name(event.keyval) or ''
        focus = window.get_focus()
        if self.mode_popover is not None and self.mode_popover.get_visible():return False
        if key in ('Tab', 'ISO_Left_Tab', 'space'):
            return False
        if isinstance(focus, (Gtk.ComboBox, Gtk.Entry, Gtk.TextView)):
            return False
        if key in ('Return','KP_Enter') and focus is self.buttons['MODE']:
            self.send('MODE');return True
        if (key in ('Return', 'KP_Enter') and isinstance(focus, (Gtk.Button, Gtk.Expander))
                and focus not in self.buttons.values()):
            return False
        shortcut = dict(Up='ArrowUp', Down='ArrowDown', Left='ArrowLeft', Right='ArrowRight',
                        Return='Enter', KP_Enter='Enter', Page_Up='PageUp', Page_Down='PageDown').get(key, key)
        if len(shortcut) == 1:
            shortcut = shortcut.lower()
        for name, entry in self.state.get('controls', {}).items():
            if shortcut in entry.get('shortcuts', []):
                now = self.clock()
                if now - self.last_input.get(name, -math.inf) >= .15:
                    self.last_input[name] = now
                    self.send(name)
                return True
        return False

    def _scrollable(self, widget, prefix):
        widget.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        widget.connect('scroll-event', self._scroll, prefix)
        self.wheel_widgets.append((widget, prefix))

    def _scroll(self, widget, event, prefix):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, dx, dy = event.get_scroll_deltas()
            delta = dy if abs(dy) >= abs(dx) else dx
            if not ok or abs(delta) < .1:
                return True
            right = delta > 0
        else:
            right = event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT)
        name = prefix + ('_RIGHT' if right else '_LEFT')
        now = self.clock()
        if now - self.last_input.get(name, -math.inf) >= .15:
            self.last_input[name] = now
            self.send(name)
        return True

    def _drag_start(self, widget, event):
        box = widget.get_allocation()
        x, y = event.x - box.width / 2, event.y - box.height / 2
        if (event.button != 1 or math.hypot(x, y) < box.width * .36
                or (self.reason('CONTROL_LEFT') and self.reason('CONTROL_RIGHT'))):
            return False
        self.drag = [math.atan2(y, x), 0]
        widget.grab_add()
        widget.get_style_context().add_class('wheel-drag')
        return True

    def _drag_move(self, widget, event):
        if self.drag is None:
            return False
        box = widget.get_allocation()
        angle = math.atan2(event.y - box.height / 2, event.x - box.width / 2)
        self.drag[1] += (angle - self.drag[0] + math.pi) % (2 * math.pi) - math.pi
        self.drag[0] = angle
        return True

    def _drag_end(self, widget, event):
        if self.drag is None:
            return False
        angle = self.drag[1]
        self._cancel_drag()
        if event.button == 1 and abs(angle) >= math.pi / 12:
            self.send('CONTROL_LEFT' if angle < 0 else 'CONTROL_RIGHT')
        return True

    def _cancel_drag(self, *_):
        if self.drag is not None:
            self.drag = None
            self.ring.grab_remove()
            self.ring.get_style_context().remove_class('wheel-drag')
        return False

    def _close(self, *_):
        if self.development_busy:
            self.local_error='固件开发动作正在完成；请等待后关闭'
            return True
        if self.reinitializing:
            self.local_error='配置重初始化正在发布；请等待完成后关闭'
            return True
        if self.reset_dialog is not None:
            self.reset_dialog.response(Gtk.ResponseType.CANCEL)
        if self.closing:
            return True
        if self.input_bindings is not None and not self.release_inputs():
            return True
        self.closing = True
        self._cancel_drag()
        self.feedback.set_text('正在保存虚拟SD并关闭本窗口拥有的 VM，请稍候。')
        self.root.set_sensitive(False)

        def cleanup():
            try:
                self.vm.close()
                state = self.vm.status()
                if state.get('state') in ('starting', 'running', 'stopping') or state.get('can_start') is False:
                    raise RuntimeError('VM 尚未确认退出')
            except (ValueError, RuntimeError, OSError) as error:
                GLib.idle_add(self._close_failed, str(error))
                return
            GLib.idle_add(self._finish_close)
        threading.Thread(target=cleanup, name='camera-owned-vm-cleanup', daemon=True).start()
        return True

    def _close_failed(self, message):
        self.closing = False
        self.root.set_sensitive(True)
        self.local_error = 'VM 清理失败；窗口保留，可再次关闭窗口重试：' + message
        self.update(self.vm.status())
        return False

    def _finish_close(self):
        self.closed = True
        if self.source_id:
            GLib.source_remove(self.source_id)
            self.source_id = 0
        self.window.destroy()
        if Gtk.main_level():
            Gtk.main_quit()
        return False

    def pump(self):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        return not self.closed

    def run(self):
        Gtk.main()


def main(autostart=True, argv=None):
    if argv is not None:
        import argparse
        parser = argparse.ArgumentParser(description='Sony A7C II QEMU native control UI')
        parser.add_argument('--cold-flag', choices=('force', 'clear', 'strict'), default=None,
                            help='how the virtual loader handles p5 WBI2 magic (default: A7C2_COLD_FLAG or force)')
        verify_group = parser.add_mutually_exclusive_group()
        verify_group.add_argument('--verify-sha', dest='verify_sha', action='store_true', default=None,
                                  help='enable startup SHA verification (or set A7C2_VERIFY_SHA=1)')
        verify_group.add_argument('--no-verify-sha', dest='verify_sha', action='store_false',
                                  help='disable startup SHA verification (default; or set A7C2_VERIFY_SHA=0)')
        args = parser.parse_args(argv)
        if args.cold_flag is not None:
            os.environ['A7C2_COLD_FLAG'] = args.cold_flag
        if args.verify_sha is not None:
            os.environ['A7C2_VERIFY_SHA'] = '1' if args.verify_sha else '0'
    os.environ.setdefault('A7C2_COLD_FLAG', 'force')
    os.environ.setdefault('A7C2_VERIFY_SHA', '0')
    if 'A7C2_SINGLE_AP_SOCKETS' in os.environ or 'A7C2_SINGLE_AP_SOCKET_ROOT' in os.environ:
        from single_ap_sockets import admit
        admit()
    # The production entry point needs only this VM construction and this window.
    if not Gtk.init_check()[0]:
        print('GTK display initialization failed',file=sys.stderr)
        return 1
    from menu_control import VM
    from settings_instance import default_instance
    instance=default_instance(Path(os.environ.get('A7C2_INSTANCE_DIR',
        str(Path(__file__).resolve().parent/'camera-instances'))))
    # shortcut: both imaging profiles use the PCI DMA QEMU build without USB networking;
    # combine them after a single build models both devices together.
    boot_profile=os.environ.get('A7C2_BOOT_PROFILE','original-init-cold')
    vm = VM(native_display='none', natural_boot=True,boot_profile=boot_profile,
            usb_net=boot_profile=='direct-bootin' and not bool(os.environ.get('A7C2_PREVIEW_PNG') or
                             os.environ.get('A7C2_NATURAL_IMAGING_PROFILE') == '1' or
                             os.environ.get('A7C2_FUNCTIONAL_CAMERA_MEDIA')), instance=instance,
            persistent_storage=os.environ.get('A7C2_USE_PERSISTENT_STORAGE')=='1')
    ui = CameraUI(vm)
    def interrupted(*_):
        ui._close()
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    if autostart:
        GLib.idle_add(lambda: ui.power(True))
    try:
        ui.run()
    finally:
        if not ui.closed:
            vm.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main(argv=sys.argv[1:]))
