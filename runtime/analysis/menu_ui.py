"""GTK companion controls. The owned QEMU native window remains the real LCD."""
import math

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gtk


CSS = b'''
window { background: #181c1e; color: #ecf0ec; }
.camera { background: #292f31; border: 1px solid #515957; border-radius: 22px; padding: 16px; }
.silver { background: #d0d3cd; color: #292f2e; border-radius: 14px; padding: 14px; }
.brand { font: bold 23px serif; }
.model { font: 20px sans-serif; }
button { background-image: none; background-color: #303638; color: #ecf0ec; border: 1px solid #66716c; border-radius: 12px; padding: 7px 11px; min-height: 28px; box-shadow: none; text-shadow: none; }
button:hover { background-color: #414b49; }
button:active { background-color: #131818; border-color: #e4a25d; }
button:disabled { background-color: #252b2d; color: #929b97; border-color: #414b49; }
button:focus { outline: 3px solid #f5bd7c; outline-offset: 2px; }
.round { border-radius: 40px; }
.wheel { border: 7px dashed #818d87; border-radius: 120px; background: #1c2223; }
.wheel-off { border-color: #4d5852; }
.hint { color: #b6bfba; font-size: 11px; }
.warning { color: #e6b77f; font-size: 11px; }
.status { font: 12px monospace; }
.feedback { background: #202729; padding: 12px; border-left: 2px solid #e4a25d; }
.error { color: #f5a198; }
'''


class NativeControls:
    def __init__(self, vm):
        self.vm, self.closed, self.drag = vm, False, None
        self.buttons = {}
        self.state = vm.status()
        self.window = Gtk.Window(title='α7C II · 机身控制 / owned VM')
        self.window.set_default_size(540, 760)
        self.window.set_border_width(18)
        self.window.connect('delete-event', self._close)
        provider = Gtk.CssProvider(); provider.load_from_data(CSS)
        self.window.get_style_context().add_provider_for_screen(
            self.window.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.window.add(root)
        heading = Gtk.Label(label=('HOST MOCK / ' if self.state['mock'] else 'LOCAL CAMERA LAB / ') + '原生窗口控制', xalign=0)
        heading.get_style_context().add_class('hint'); root.pack_start(heading, False, False, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        body.get_style_context().add_class('camera'); root.pack_start(body, False, False, 0)
        top = Gtk.Box(spacing=18); top.get_style_context().add_class('silver')
        body.pack_start(top, False, False, 0)
        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        for text, style in [('SONY', 'brand'), ('α7C II', 'model')]:
            label = Gtk.Label(label=text, xalign=0); label.get_style_context().add_class(style)
            brand.pack_start(label, False, False, 0)
        top.pack_start(brand, True, True, 0)
        power = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        switch = Gtk.Box(spacing=6)
        self.on, self.off = Gtk.Button(label='ON'), Gtk.Button(label='OFF')
        self.on.connect('clicked', lambda _: self._power(True))
        self.off.connect('clicked', lambda _: self._power(False))
        self.on.set_tooltip_text('启动本次 owned VM；真实固件电源事件未模拟')
        self.off.set_tooltip_text('关闭本次 owned VM；只清理本控制台拥有的进程组')
        for button in (self.on, self.off): switch.pack_start(button, True, True, 0)
        power.pack_start(switch, False, False, 0)
        self.power_state = Gtk.Label(label='disconnected'); self.power_state.get_style_context().add_class('status')
        power.pack_start(self.power_state, False, False, 0); top.pack_start(power, False, False, 0)
        modes=Gtk.Box(spacing=6)
        for name in ('MODE_STILL','MODE_MOVIE','MODE_SQ'):modes.pack_start(self._button(name),True,True,0)
        body.pack_start(modes,False,False,0)
        wheels = Gtk.Box(spacing=18)
        for title, left, right in [('前拨轮', 'FRONT_LEFT', 'FRONT_RIGHT'), ('后拨轮', 'REAR_LEFT', 'REAR_RIGHT')]:
            group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            text = Gtk.Label(label=title + ' · 未验证'); text.get_style_context().add_class('warning')
            group.pack_start(text, False, False, 0)
            row = Gtk.Box(spacing=6)
            row.pack_start(self._button(left, '‹ 左转'), True, True, 0)
            row.pack_start(self._button(right, '右转 ›'), True, True, 0)
            group.pack_start(row, False, False, 0); wheels.pack_start(group, True, True, 0)
        body.pack_start(wheels, False, False, 0)
        primary = Gtk.Box(spacing=7)
        for name in ('MENU', 'C1', 'AF_ON', 'FN'):
            primary.pack_start(self._button(name), True, True, 0)
        body.pack_start(primary, False, False, 0)
        self.ring = Gtk.EventBox(); self.ring.set_size_request(228, 228)
        self.ring.set_halign(Gtk.Align.CENTER); self.ring.get_style_context().add_class('wheel')
        self.ring.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        self.ring.connect('button-press-event', self._drag_start)
        self.ring.connect('motion-notify-event', self._drag_move)
        self.ring.connect('button-release-event', self._drag_end)
        self.ring.connect('grab-broken-event', self._cancel_drag)
        grid = Gtk.Grid(column_spacing=6, row_spacing=6)
        grid.set_halign(Gtk.Align.CENTER); grid.set_valign(Gtk.Align.CENTER)
        for name, text, x, y in [('UP', '⌃', 1, 0), ('LEFT', '‹', 0, 1), ('ENTER', 'ENTER', 1, 1),
                                 ('RIGHT', '›', 2, 1), ('DOWN', '⌄', 1, 2)]:
            button = self._button(name, text); button.set_size_request(51, 49)
            grid.attach(button, x, y, 1, 1)
        self.ring.add(grid); body.pack_start(self.ring, False, False, 0)
        rotation = Gtk.Box(spacing=8); rotation.set_halign(Gtk.Align.CENTER)
        for name, text in [('CONTROL_LEFT', '↶ 控制轮左转'), ('CONTROL_RIGHT', '控制轮右转 ↷')]:
            rotation.pack_start(self._button(name, text), False, False, 0)
        body.pack_start(rotation, False, False, 0)
        wheel_note = Gtk.Label(label='外圈可拖动 · 单次 ±1024 · 控制轮语义未验证')
        wheel_note.get_style_context().add_class('warning'); body.pack_start(wheel_note, False, False, 0)
        secondary = Gtk.Grid(column_spacing=7, row_spacing=7, column_homogeneous=True)
        for i, name in enumerate(('DISP', 'ISO', 'EXPOSURE_COMP', 'PLAYBACK', 'C2', 'DELETE', 'REC', 'SHUTTER', 'MODE')):
            secondary.attach(self._button(name), i % 3, i // 3, 1, 1)
        body.pack_start(secondary, False, False, 0)
        native_note = Gtk.Label(label='LCD：真实固件画面在 QEMU 原生窗口\n此面板与原生窗口共用本次 VM；输入结果以固件画面为准。')
        native_note.set_line_wrap(True); native_note.get_style_context().add_class('hint')
        root.pack_start(native_note, False, False, 0)
        self.feedback = Gtk.Label(xalign=0); self.feedback.set_line_wrap(True)
        self.feedback.set_max_width_chars(65); self.feedback.get_style_context().add_class('feedback')
        root.pack_start(self.feedback, False, False, 0)
        self.error = Gtk.Label(xalign=0); self.error.set_line_wrap(True); self.error.set_max_width_chars(65)
        self.error.get_style_context().add_class('error'); root.pack_start(self.error, False, False, 0)
        footer = Gtk.Label(label='ON / OFF 启停 owned VM；真实机身电源事件未模拟。')
        footer.get_style_context().add_class('hint'); root.pack_start(footer, False, False, 0)
        self.window.show_all(); self.update(self.state)

    def _button(self, name, text=None):
        entry = self.state['controls'][name]
        label = text or entry['label']
        if not entry['verified']: label += '\n未验证'
        button = Gtk.Button(label=label)
        button.set_sensitive(False)
        button.get_accessible().set_name(entry['label'] + ' · ' + entry['verification'])
        button.connect('clicked', lambda _: self.send(name))
        self.buttons[name] = button
        return button

    def _reason(self, name):
        entry = self.state['controls'][name]
        if not entry['available']: return entry['unavailable_reason']
        if entry.get('positions'):return '位置拨盘请使用新版单窗口；此历史面板未实现选位'
        if self.state['state'] != 'running': return 'VM 尚未就绪'
        if self.state['busy'] or self.state['pending']: return '正在处理上一条操作，请稍候'
        return ''

    def send(self, name):
        if self._reason(name): return
        try:
            self.vm.enqueue({'action': 'key', 'key': name})
            self.feedback.set_text('输入已排队；响应以原生窗口中的固件画面变化为准。')
        except ValueError as error:
            self.feedback.set_text('按键未发送：' + str(error))
        self.update(self.vm.status())

    def _power(self, on):
        try:
            self.vm.start() if on else self.vm.stop()
        except ValueError as error:
            self.feedback.set_text(str(error))
        self.update(self.vm.status())

    def update(self, state):
        self.state = state
        power = state.get('power_state', state['state'])
        self.power_state.set_text(power)
        self.on.get_accessible().set_name('ON 启动本次 VM，当前 ' + power)
        self.off.get_accessible().set_name('OFF 关闭本次 VM，当前 ' + power)
        self.on.set_sensitive(state['can_start']); self.off.set_sensitive(state['can_stop'])
        self.error.set_text(state['error']); self.error.set_visible(bool(state['error']))
        for name, button in self.buttons.items():
            entry, reason = state['controls'][name], self._reason(name)
            button.set_sensitive(not reason)
            button.set_tooltip_text(' · '.join(filter(None, [entry['label'], entry['verification'], entry['note'], reason])))
        self.ring.set_tooltip_text(self._reason('CONTROL_LEFT') or '拖动外圈左右旋转；控制轮语义未验证')
        style = self.ring.get_style_context()
        style.add_class('wheel-off') if self._reason('CONTROL_LEFT') else style.remove_class('wheel-off')
        if state['events']:
            self.feedback.set_text(state['events'][0]['message'])

    def _drag_start(self, widget, event):
        box = widget.get_allocation()
        x, y = event.x - box.width / 2, event.y - box.height / 2
        if event.button != 1 or self._reason('CONTROL_LEFT') or math.hypot(x, y) < 88: return False
        self.drag = [math.atan2(y, x), 0]
        widget.grab_add()
        return True

    def _drag_move(self, widget, event):
        if self.drag is None: return False
        box = widget.get_allocation(); angle = math.atan2(event.y - box.height / 2, event.x - box.width / 2)
        delta = (angle - self.drag[0] + math.pi) % (math.pi * 2) - math.pi
        self.drag = [angle, self.drag[1] + delta]
        return True

    def _drag_end(self, widget, event):
        if self.drag is None: return False
        angle = self.drag[1]; self.drag = None; widget.grab_remove()
        if abs(angle) >= math.pi / 12: self.send('CONTROL_LEFT' if angle < 0 else 'CONTROL_RIGHT')
        return True

    def _cancel_drag(self, widget, event):
        if self.drag is not None: self.drag = None; widget.grab_remove()
        return False

    def _close(self, *_):
        self.closed = True
        return False

    def pump(self):
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        return not self.closed
