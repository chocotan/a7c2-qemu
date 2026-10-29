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
@define-color bg #111517;
@define-color body #1d2427;
@define-color panel #242d30;
@define-color key #2d383c;
@define-color edge #4c5b60;
@define-color ink #f2f5f3;
@define-color muted #b4c0bc;
@define-color accent #efbd72;
@define-color silver #cbd2cd;
@define-color black #070a0b;
@define-color danger #f28f87;
window { background: @bg; color: @ink; font: 14px sans-serif; }
.camera { background: @body; border: 1px solid @edge; border-radius: 18px; padding: 12px 16px; }
.top { background: @silver; color: @body; border-radius: 12px; padding: 8px 16px; }
.brand { font: bold 26px serif; }
.title { font: 24px sans-serif; }
.hint { color: @muted; font: 13px sans-serif; }
.top .hint { color: #35413c; }
.section { color: @muted; font: bold 13px sans-serif; }
.status { background: @panel; color: @ink; border: 1px solid @edge; border-radius: 18px; padding: 7px 12px; font: bold 13px monospace; }
button, combobox button { background-image: none; background-color: @key; color: @ink; border: 1px solid @edge; border-radius: 9px; padding: 8px 14px; min-height: 28px; min-width: 18px; box-shadow: none; text-shadow: none; }
button:hover { background-color: #3a474b; border-color: #718086; }
button:active { background-color: #172023; border-color: @accent; color: #ffffff; }
button:disabled { background-color: #222a2d; color: #a9b4b0; border-color: #3d494d; }
button:focus, combobox:focus, expander:focus, switch:focus { outline: 3px solid @accent; outline-offset: 2px; }
.top button:focus { outline-color: @body; }
button.direction { font: 18px sans-serif; }
.round { border-radius: 50px; }
.mode { border-radius: 60px; border: 4px double #718079; }
popover.mode-positions { background: @body; color: @ink; }
.record { border-color: @danger; color: #ffb0a8; }
.power { border-color: @accent; }
.danger { border-color: #9f5f5b; color: @danger; }
.wheel { border: 7px solid #617075; border-radius: 140px; background: #141b1e; padding: 8px; }
.wheel-off { border-color: #3d494d; }
.wheel-drag { border-color: @accent; }
.controls-panel { background: @panel; border: 1px solid #364448; border-radius: 12px; padding: 8px; }
.lcd { border: none; background: transparent; padding: 0 8px; }
.lcd-screen { background: @black; border: 1px solid #66747a; border-radius: 4px; }
.lcd-stale { border-color: @accent; }
.frame-meta { color: @muted; font: 12px monospace; }
.toolbar { background: @panel; border: 1px solid #364448; border-radius: 10px; padding: 4px 8px; }
.feedback { background: @panel; border-left: 3px solid @accent; padding: 10px 12px; color: @muted; }
.error { color: @danger; }
.warning { color: @accent; }
expander { color: @muted; }
textview, textview text { background: @panel; color: @muted; }
'''

STATE_NAMES = dict(disconnected='已关闭', exited='已关闭', starting='正在启动',
                   running='运行中',faulted='固件异常·可保存/关闭', stopping='正在关闭', error='运行错误')
KEY_NAMES = dict(MENU='MENU', C1='C1', AF_ON='AF-ON', FN='Fn', UP='上', DOWN='下',
                 LEFT='左', RIGHT='右', ENTER='ENTER', DISP='DISP', ISO='ISO',
                 EXPOSURE_COMP='± 曝光', PLAYBACK='播放', C2='C2', DELETE='删除',
                 REC='REC', SHUTTER_HALF='半按', SHUTTER='全按快门', MODE='MODE', FRONT_LEFT='前拨轮左转',
                 FRONT_RIGHT='前拨轮右转', REAR_LEFT='后拨轮左转',
                 REAR_RIGHT='后拨轮右转', CONTROL_LEFT='控制轮左转',
                 CONTROL_RIGHT='控制轮右转',MODE_STILL='照片',MODE_MOVIE='录像',MODE_SQ='S&Q')


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
        self.provider = Gtk.CssProvider()
        self.provider.load_from_data(CSS)
        self.window = Gtk.Window(title='α7C II · 单窗口相机控制')
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
        self.root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.root.set_border_width(18)
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
            self.source_id = GLib.timeout_add(50, self.tick)

    def _build_header(self):
        row = Gtk.Box(spacing=18)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        titles.pack_start(label('NATIVE QEMU  /  ILCE-7CM2', 'hint'), False, False, 0)
        titles.pack_start(label('α7C II  相机控制台', 'title'), False, False, 0)
        row.pack_start(titles, True, True, 0)
        self.status_label = label('', 'status')
        row.pack_end(self.status_label, False, False, 0)
        self.spinner = Gtk.Spinner()
        row.pack_end(self.spinner, False, False, 0)
        self.root.pack_start(row, False, False, 0)

    def _build_top(self):
        top = Gtk.Box(spacing=24)
        top.get_style_context().add_class('top')
        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        brand.pack_start(label('SONY', 'brand'), False, False, 0)
        modes=Gtk.Box(spacing=6)
        modes.set_halign(Gtk.Align.START)
        for name in ('MODE_STILL','MODE_MOVIE','MODE_SQ'):modes.pack_start(self._button(name),False,False,0)
        brand.pack_start(modes,False,False,0)
        top.pack_start(brand, False, False, 0)
        mode = self._button('MODE', 'MODE', 'mode')
        mode.set_size_request(84, 84)
        top.pack_start(mode, False, False, 0)
        top.pack_start(self._dial('前拨轮', 'FRONT'), False, False, 0)
        top.pack_start(self._button('REC', 'REC', 'record'), False, False, 0)
        shutter = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        shutter.pack_start(self._button('SHUTTER_HALF', '半按'), False, False, 0)
        shutter.pack_start(self._button('SHUTTER', '全按', 'round'), False, False, 0)
        top.pack_start(shutter, False, False, 0)
        power = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        row = Gtk.Box(spacing=6)
        self.on = Gtk.Button(label='ON')
        self.off = Gtk.Button(label='OFF')
        for button, enabled in ((self.on, True), (self.off, False)):
            button.set_size_request(58, 44)
            button.connect('clicked', lambda _, value=enabled: self.power(value))
            button.get_accessible().set_name(('ON 启动' if enabled else 'OFF 停止') + '本窗口拥有的 VM')
            row.pack_start(button, False, False, 0)
        self.on.get_style_context().add_class('power')
        power.pack_start(row, False, False, 0)
        net = Gtk.Box(spacing=6)
        self.wifi_label = label('Wi-Fi 关', 'hint')
        net.pack_start(self.wifi_label, False, False, 0)
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.set_active(False)
        self.wifi_switch.get_accessible().set_name(
            '隔离 Wi-Fi 开关：开启后宿主应能 ping 通，关闭后不通')
        self.wifi_switch.connect('notify::active',
                                 lambda widget, _: self.wifi(widget.get_active()))
        net.pack_start(self.wifi_switch, False, False, 0)
        power.pack_start(net, False, False, 0)
        power.pack_start(label('owned VM / 真实电源未模拟', 'hint'), False, False, 0)
        top.pack_end(power, False, False, 0)
        self.camera.pack_start(top, False, False, 0)
        self.shoulder = Gtk.Box(spacing=12)
        self.shoulder.pack_start(label('LCD  /  原固件画面', 'section'), True, True, 0)
        self.shoulder.pack_start(self._button('MENU'), False, False, 0)
        self.shoulder.pack_start(self._button('C1'), False, False, 0)
        self.shoulder.pack_start(self._dial('后拨轮', 'REAR', horizontal=True), False, False, 0)
        self.camera.pack_start(self.shoulder, False, False, 0)

    def _button(self, name, text=None, style=None):
        button = Gtk.Button(label=text or KEY_NAMES.get(name, name))
        if text in ('‹', '›', '⌃', '⌄'):
            button.get_style_context().add_class('direction')
        button.set_size_request(44, 44)
        button.set_valign(Gtk.Align.CENTER)
        if style:
            button.get_style_context().add_class(style)
        button.connect('clicked', lambda _: self.send(name))
        prefix = name.rsplit('_', 1)[0]
        if prefix in ('FRONT', 'REAR', 'CONTROL'):
            button.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
            button.connect('scroll-event', self._scroll, prefix)
        self.buttons[name] = button
        return button

    def _dial(self, title, prefix, horizontal=False):
        group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL, spacing=5)
        group.pack_start(label(title, 'hint'), False, False, 0)
        row = Gtk.Box(spacing=6)
        row.pack_start(self._button(prefix + '_LEFT', '‹'), False, False, 0)
        row.pack_start(self._button(prefix + '_RIGHT', '›'), False, False, 0)
        group.pack_start(row, False, False, 0)
        surface = Gtk.EventBox()
        surface.set_visible_window(False)
        surface.add(group)
        self._scrollable(surface, prefix)
        return surface

    def _build_back(self):
        back = Gtk.Box(spacing=18)
        lcd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
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
        controls.set_size_request(300, -1)
        controls.set_valign(Gtk.Align.CENTER)
        row = Gtk.Box(spacing=12, homogeneous=True)
        for name in ('AF_ON', 'FN'):
            row.pack_start(self._button(name, style='round'), True, True, 0)
        controls.pack_start(row, False, False, 0)
        wheel_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.ring = Gtk.EventBox()
        self.ring.set_halign(Gtk.Align.CENTER)
        self.ring.set_size_request(200, 200)
        self.ring.get_style_context().add_class('wheel')
        self.ring.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                             Gdk.EventMask.POINTER_MOTION_MASK)
        self.ring.connect('button-press-event', self._drag_start)
        self.ring.connect('motion-notify-event', self._drag_move)
        self.ring.connect('button-release-event', self._drag_end)
        self.ring.connect('grab-broken-event', self._cancel_drag)
        grid = Gtk.Grid(column_spacing=5, row_spacing=5)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_valign(Gtk.Align.CENTER)
        for name, text, x, y in (('UP', '⌃', 1, 0), ('LEFT', '‹', 0, 1), ('ENTER', 'ENTER', 1, 1),
                                 ('RIGHT', '›', 2, 1), ('DOWN', '⌄', 1, 2)):
            grid.attach(self._button(name, text, 'round'), x, y, 1, 1)
        self.ring.add(grid)
        self._scrollable(self.ring, 'CONTROL')
        wheel_area.pack_start(self.ring, False, False, 0)
        row = Gtk.Box(spacing=8, homogeneous=True)
        row.pack_start(self._button('CONTROL_LEFT', '‹ 控制轮'), True, True, 0)
        row.pack_start(self._button('CONTROL_RIGHT', '控制轮 ›'), True, True, 0)
        wheel_area.pack_start(row, False, False, 0)
        self.wheel_note = label('外圈可拖动 / 独立控制轮', 'hint')
        self.wheel_note.set_halign(Gtk.Align.CENTER)
        wheel_area.pack_start(self.wheel_note, False, False, 0)
        controls.pack_start(wheel_area, False, False, 0)
        for names in (('DISP', 'ISO', 'EXPOSURE_COMP'), ('PLAYBACK', 'C2', 'DELETE')):
            row = Gtk.Box(spacing=8, homogeneous=True)
            for name in names:
                row.pack_start(self._button(name), True, True, 0)
            controls.pack_start(row, False, False, 0)
        back.pack_end(controls, False, False, 0)
        self.camera.pack_start(back, True, True, 0)
        self.frame_label = label('尚无本次 VM 图像', 'frame-meta', wrap=True)
        lcd.pack_start(self.frame_label, False, False, 0)

    def _build_footer(self):
        row = Gtk.Box(spacing=12)
        row.get_style_context().add_class('toolbar')
        self.refresh = Gtk.Button(label='刷新 LCD')
        self.refresh.set_size_request(100, 44)
        self.refresh.connect('clicked', lambda _: self.capture())
        row.pack_start(self.refresh, False, False, 0)
        row.pack_start(label('自动快照', 'hint'), False, False, 0)
        self.interval = Gtk.ComboBoxText()
        for seconds in (0, 3, 10, 30):
            self.interval.append(str(seconds), '关闭' if not seconds else f'{seconds} 秒')
        self.interval.set_active_id('10')
        self.interval.get_accessible().set_name('自动 LCD 快照间隔')
        self.interval.connect('changed', self._interval_changed)
        row.pack_start(self.interval, False, False, 0)
        self.capture_status = label('', 'hint')
        self.capture_status.set_size_request(150, -1)
        row.pack_start(self.capture_status, False, False, 0)
        self.sd_action = Gtk.Button(label='安全拔出 SD')
        self.sd_action.connect('clicked', lambda _: self.change_sd())
        self.sd_action.get_accessible().set_name('虚拟 SD 插入或安全拔出')
        row.pack_start(self.sd_action, False, False, 0)
        self.sd_label = label('SD 未确认', 'hint')
        row.pack_start(self.sd_label, False, False, 0)
        self.reset_button = Gtk.Button(label='销毁并重新初始化')
        self.reset_button.get_style_context().add_class('danger')
        self.reset_button.get_accessible().set_name('销毁当前相机配置并重新初始化，保留 SD')
        self.reset_button.connect('clicked', lambda _: self.request_reinitialize())
        row.pack_end(self.reset_button, False, False, 0)
        self.root.pack_start(row, False, False, 0)
        self.feedback = label('ON 启动本窗口拥有的 VM，等待真实固件图像。', 'feedback', wrap=True)
        self.feedback.get_accessible().set_role(Atk.Role.STATUSBAR)
        self.root.pack_start(self.feedback, False, False, 0)
        self.error_label = label('', 'error', wrap=True)
        self.error_label.set_no_show_all(True)
        self.error_label.get_accessible().set_role(Atk.Role.ALERT)
        self.root.pack_start(self.error_label, False, False, 0)
        self.details = Gtk.Expander(label='快捷键 / 操作记录 / 按键可用性')
        self.detail_text = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.detail_text.get_accessible().set_name('最近操作记录和每个控件的禁用原因')
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 180)
        scroll.add(self.detail_text)
        self.details.add(scroll)
        self.root.pack_start(self.details, False, False, 0)

    def reason(self, name):
        entry = self.state.get('controls', {}).get(name)
        if not entry:
            return '后端 registry 未提供此控件'
        if not entry.get('available'):
            return entry.get('unavailable_reason') or '键码未知或当前通道不可用'
        if self.closing or self.reinitializing:
            return '正在关闭本窗口拥有的 VM'
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

    def power(self, on):
        if self.closing or self.reinitializing:
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
        if self.reinitializing:return False
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
        self.status_label.set_text(prefix + name)
        activity = state.get('busy') or ('排队中' if state.get('pending') else '')
        self.spinner.start() if activity or state.get('state') in ('starting', 'stopping') else self.spinner.stop()
        self.on.set_sensitive(not self.closing and state.get('can_start', state.get('state') in ('disconnected', 'exited', 'error')))
        self.off.set_sensitive(not self.closing and state.get('can_stop', state.get('state') in ('starting', 'running')))
        self.reset_button.set_sensitive(not(self.closing or self.reinitializing)
            and state.get('settings_persistent') is True and bool(state.get('settings_generation'))
            and state.get('state') in ('disconnected','exited') and bool(state.get('can_start')))
        self.reset_button.set_tooltip_text('请先 OFF 并等待配置和 SD 保存完成；仅重置当前实例，默认保留 SD')
        wifi = state.get('wifi') or {}
        if state.get('state') != 'running':
            self.wifi_confirmed = False
        elif wifi.get('ok') is True:
            self.wifi_confirmed = wifi.get('enabled') is True
        wifi_pending = bool(state.get('pending') or state.get('busy'))
        self.wifi_label.set_text('Wi-Fi …' if wifi_pending else ('Wi-Fi 开' if self.wifi_confirmed else 'Wi-Fi 关'))
        self.wifi_switch.set_sensitive(not self.closing and state.get('state') == 'running'
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
        self.on.set_tooltip_text('启动本窗口拥有的 VM；真实机身电源事件未模拟')
        self.off.set_tooltip_text('关闭本窗口拥有的 VM；保留最近 LCD 并标明旧画面')
        card=state.get('sd_card') or {}
        card_state=card.get('state','unavailable')
        self.sd_label.set_text({'present':'SD 已插入','absent':'SD 已拔出','ejecting':'SD 正在拔出',
                                'inserting':'SD 正在插入','uncertain':'SD 状态未确认',
                                'unavailable':'SD 未确认'}.get(card_state,'SD 未确认'))
        self.sd_action.set_label('插入 SD' if card_state=='absent' else '安全拔出 SD')
        self.sd_action.set_sensitive(not self.closing and state.get('state')=='running' and
                                     not(state.get('busy') or state.get('pending')) and
                                     card.get('ok') is True and card_state in ('present','absent'))
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
        if self.poller.inflight:
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
        stale = False
        if self.pixbuf:
            stale = (state.get('stale', False) or state.get('state') != 'running' or bool(error)
                     or self.frame_token != SnapshotPoller.token(state))
            frame = self.display_frame
            freshness = '旧画面 / 当前画面未确认' if stale else '本次后端已校验快照'
            source=('模拟灰度预览 / AP已消费 / 非CP面板' if str(frame.get('source','')).startswith('AP VDT luma mirror') else
                    '显示帧' if frame.get('source')=='QMP ramfb display' else
                    '像素提交 '+str(frame.get('pixel_source_seq','?')))
            self.frame_label.set_text(prefix + freshness + f' / #{frame.get("number", "?")} / {source} / 640 x 480')
        else:
            self.frame_label.set_text(prefix + ('等待后端首幅图像' if state.get('state') == 'running' else '尚无本次 VM 图像 / ON 启动'))
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
            layout = widget.create_pango_layout('等待本次固件画面\nON 启动 owned VM 后获取真实 LCD')
            layout.set_alignment(Pango.Alignment.CENTER)
            tw, th = layout.get_pixel_size()
            cr.set_source_rgb(.73, .77, .74)
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


def main(autostart=True):
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
    vm = VM(native_display='none', natural_boot=True,
            usb_net=not bool(os.environ.get('A7C2_PREVIEW_PNG') or
                             os.environ.get('A7C2_NATURAL_IMAGING_PROFILE') == '1'), instance=instance)
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
    raise SystemExit(main())
