"""Source-backed camera input; the selected serial owner executes every wire send.

Import with runtime/analysis on sys.path. This module starts no UI, VM or transport.
"""
import math

from menu_live import control_catalog, key_command, key_definition, key_status_command

# Host shortcuts add no firmware codes; retain every shortcut in the house registry.
HOST_KEYS = {key: (name, None) for name, entry in control_catalog().items()
             for key in entry['shortcuts']}
HOST_KEYS.update({
    'F1': ('C1', None), 'F2': ('C2', None), 'a': ('AF_ON', None),
    'f': ('FN', None), 'p': ('PLAYBACK', None), 'r': ('REC', None),
    'h': ('SHUTTER_HALF', None), 's': ('SHUTTER', None),
    'q': ('FRONT_LEFT', None), 'e': ('FRONT_RIGHT', None),
    '[': ('REAR_LEFT', None), ']': ('REAR_RIGHT', None),
    ',': ('CONTROL_LEFT', None), '.': ('CONTROL_RIGHT', None),
    '1': ('MODE_STILL', None), '2': ('MODE_MOVIE', None), '3': ('MODE_SQ', None),
})
HOST_KEYS.update({f'F{number}': ('MODE', position)
                  for number, position in enumerate(('AUTO', 'P', 'A', 'S', 'M', 'MR1', 'MR2', 'MR3'), 5)})
PHYSICAL_CONTROLS = ('MENU', 'C1', 'C2', 'SHUTTER_HALF', 'SHUTTER', 'REC',
                     'AF_ON', 'FN', 'ENTER', 'UP', 'DOWN', 'LEFT', 'RIGHT',
                     'CONTROL_LEFT', 'CONTROL_RIGHT', 'FRONT_LEFT', 'FRONT_RIGHT',
                     'REAR_LEFT', 'REAR_RIGHT', 'MODE_STILL', 'MODE_MOVIE', 'MODE_SQ',
                     'MODE', 'PLAYBACK', 'DELETE')
UNSUPPORTED = {
    'EXPOSURE_COMP': 'No source-closed independent contact; do not substitute DOWN or a rear-dial event.',
    'AEL': 'No dedicated AEL control is established for this model; a configurable function is not a raw contact.',
}
MAX_TICKS = 32


def _entry(name):
    if not isinstance(name, str) or name not in control_catalog():
        raise ValueError('Unknown camera control')
    entry = key_definition(name)
    if not entry['code']:
        raise ValueError('Camera control has no source-backed raw code')
    return entry


def _contact(name):
    entry = _entry(name)
    if entry['status'] is not None or entry['positions']:
        raise ValueError('A dial/selector has no press/release contact')
    return int(entry['code'], 0)


def validate_request(request):
    """Admission validation shared by the host queue and the serial owner."""
    if not isinstance(request, dict) or request.get('action') != 'camera_input':
        raise ValueError('Invalid camera input request')
    op = request.get('op')
    fields = {
        'press': {'key', 'source'}, 'release': {'source'}, 'tap': {'key', 'source'},
        'rotate': {'dial', 'ticks'}, 'position': {'key', 'position'}, 'cleanup': set(),
    }
    if not isinstance(op, str) or op not in fields or set(request) != {'action', 'op'} | fields[op]:
        raise ValueError('Invalid camera input fields')
    if 'source' in request:
        source = request['source']
        if (not isinstance(source, str) or not 1 <= len(source) <= 96
                or not source.isascii() or not source.isprintable()):
            raise ValueError('Invalid input source')
    if op in ('press', 'tap'):
        entry = _entry(request['key'])
        if op == 'press':
            _contact(request['key'])
        elif entry['positions']:
            raise ValueError('Mode dial requires a position')
    elif op == 'rotate':
        if (request['dial'] not in ('FRONT', 'REAR', 'CONTROL')
                or type(request['ticks']) is not int or not 1 <= abs(request['ticks']) <= MAX_TICKS):
            raise ValueError('Rotation must contain 1..32 signed ticks of a known dial')
    elif op == 'position':
        entry = _entry(request['key'])
        if not isinstance(request['position'], str) or request['position'] not in entry['positions']:
            raise ValueError('Unknown source-backed selector position')
    return request


class InputSession:
    """Serial-owner state. input_fn is synchronous serial_command, NOT VM.enqueue.

    A successful bytes return means the existing serial command checked rc=0; it
    does not assert that the firmware consumed the event or completed a capture.
    Failed/ambiguous contact sends retain their owner until a release succeeds.
    """
    def __init__(self, input_fn, *, app_input):
        if type(app_input) is not bool:
            raise ValueError('Select the existing App32 or Infra20 route explicitly')
        self.input_fn, self.app_input = input_fn, app_input
        self.held = {}  # source -> {key, contacts in acquisition order}
        self.uncertain = set()
        self.error = ''
        self.completed_ticks = 0

    def status(self):
        return {'held': [{'source': source, 'key': item['key'],
                          'contacts': list(item['contacts'])} for source, item in self.held.items()],
                'uncertain_codes': [f'0x{code:x}' for code in sorted(self.uncertain)],
                'error': self.error}

    def _send(self, command):
        # Reject accidentally wiring this to an asynchronous enqueue/empty ACK.
        if not isinstance(self.input_fn(command), bytes):
            raise RuntimeError('Selected serial input must return checked command bytes')

    def _contact_send(self, name, status):
        code = _contact(name)
        self.uncertain.add(code)
        self._send(key_status_command(name, status, self.app_input))
        self.uncertain.discard(code)

    def _owners(self, code):
        return sum(any(_contact(key) == code for key in item['contacts']) for item in self.held.values())

    def press(self, name, source):
        _contact(name)
        if self.uncertain:
            raise RuntimeError('A contact send is uncertain; release or cleanup before new input')
        if source in self.held:
            if self.held[source]['key'] != name:
                raise ValueError('Input source is already holding a different control')
            return False
        if len(self.held) >= 64:
            raise ValueError('Too many simultaneous input sources')
        self.held[source] = {'key': name, 'contacts': []}
        contacts = ('SHUTTER_HALF', 'SHUTTER') if name == 'SHUTTER' else (name,)
        for contact in contacts:
            shared = self._owners(_contact(contact))
            self.held[source]['contacts'].append(contact)
            if not shared:
                self._contact_send(contact, 1)
        return True

    def release(self, source):
        item = self.held.get(source)
        if item is None:
            return False
        while item['contacts']:
            name = item['contacts'][-1]
            if self._owners(_contact(name)) == 1:
                self._contact_send(name, 0)
            item['contacts'].pop()
        del self.held[source]
        return True

    def cleanup(self):
        errors = []
        # Full contacts leave before half contacts, including independent sources.
        sources = sorted(self.held, key=lambda source: 'SHUTTER' not in self.held[source]['contacts'])
        for source in sources:
            try:
                self.release(source)
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f'{source}: {error}')
        if errors:
            raise RuntimeError('; '.join(errors))

    def handle(self, request):
        validate_request(request)
        op = request['op']
        self.completed_ticks = 0
        try:
            if op == 'release':
                self.release(request['source'])
            elif op == 'cleanup':
                self.cleanup()
            else:
                if self.uncertain:
                    raise RuntimeError('A contact send is uncertain; release or cleanup before new input')
                if op == 'press':
                    self.press(request['key'], request['source'])
                elif op == 'tap':
                    name, source = request['key'], request['source']
                    if source in self.held:
                        raise ValueError('A tap must not release a held input source')
                    if key_definition(name)['status'] is not None:
                        self._send(key_command(name, self.app_input))
                    else:
                        failure = None
                        try:
                            self.press(name, source)
                        except (OSError, RuntimeError, ValueError) as error:
                            failure = error
                        try:
                            self.release(source)
                        except (OSError, RuntimeError, ValueError) as error:
                            if failure is not None:
                                raise RuntimeError(f'press: {failure}; release: {error}') from error
                            raise
                        if failure is not None:
                            raise failure
                elif op == 'rotate':
                    name = request['dial'] + ('_RIGHT' if request['ticks'] > 0 else '_LEFT')
                    for _ in range(abs(request['ticks'])):
                        self._send(key_command(name, self.app_input))
                        self.completed_ticks += 1
                elif op == 'position':
                    self._send(key_command(request['key'], self.app_input, request['position']))
        except (OSError, RuntimeError, ValueError) as error:
            self.error = str(error)
            return {'type': 'camera_input', 'ok': False, 'request': request,
                    'completed_ticks': self.completed_ticks, 'input_state': self.status()}
        if not self.uncertain:
            self.error = ''
        return {'type': 'camera_input', 'ok': True, 'request': request,
                'completed_ticks': self.completed_ticks, 'input_state': self.status()}


class InputBindings:
    """Keyboard/mouse/controller callers enqueue validated requests, never ACK wire sends."""
    def __init__(self, enqueue):
        self.enqueue = enqueue
        self.sources = {}
        self.scroll_remainder = {}
        self.drag = None

    def post(self, op, **fields):
        request = validate_request({'action': 'camera_input', 'op': op, **fields})
        self.enqueue(request)
        return True

    def press(self, name, source):
        _contact(name)
        if source in self.sources:
            if self.sources[source] != name:
                raise ValueError('Input source cannot change control while held')
            return False
        self.post('press', key=name, source=source)
        self.sources[source] = name
        return True

    def release(self, source):
        if source not in self.sources:
            return False
        self.post('release', source=source)
        del self.sources[source]
        return True

    def activate(self, name, *, source='activation', position=None):
        if position is not None:
            return self.post('position', key=name, position=position)
        return self.post('tap', key=name, source=source)

    def key_press(self, shortcut, hardware_code):
        action = HOST_KEYS.get(shortcut)
        if action is None:
            return False
        name, position = action
        source = f'keyboard:{hardware_code}'
        if source in self.sources:
            return True  # OS key-repeat must not produce extra press/release pairs.
        entry = _entry(name)
        if entry['status'] is not None or position is not None:
            self.activate(name, source=source, position=position)
            self.sources[source] = None
        else:
            self.press(name, source)
        return True

    def key_release(self, hardware_code):
        source = f'keyboard:{hardware_code}'
        if source in self.sources and self.sources[source] is None:
            del self.sources[source]
            return True
        return self.release(source)

    def scroll(self, dial, delta):
        if dial not in ('FRONT', 'REAR', 'CONTROL') or not math.isfinite(delta):
            raise ValueError('Invalid dial scroll')
        total = self.scroll_remainder.get(dial, 0.0) + delta
        ticks = max(-MAX_TICKS, min(MAX_TICKS, math.trunc(total)))
        if ticks:
            self.post('rotate', dial=dial, ticks=ticks)
        # Keep only the fractional remainder; do not carry a huge scroll burst forward.
        self.scroll_remainder[dial] = total - math.trunc(total)
        return bool(ticks)

    def drag_start(self, source, angle):
        if not math.isfinite(angle) or self.drag is not None:
            return False
        self.drag = [source, angle, 0.0]
        return True

    def drag_move(self, source, angle):
        if self.drag is None or self.drag[0] != source or not math.isfinite(angle):
            return False
        self.drag[2] += (angle - self.drag[1] + math.pi) % (2 * math.pi) - math.pi
        self.drag[1] = angle
        return True

    def drag_end(self, source):
        if self.drag is None or self.drag[0] != source:
            return False
        ticks = max(-MAX_TICKS, min(MAX_TICKS, math.trunc(self.drag[2] / (math.pi / 12))))
        if ticks:
            self.post('rotate', dial='CONTROL', ticks=ticks)
        self.drag = None
        return True

    def cleanup(self):
        self.post('cleanup')
        self.sources.clear()  # Local physical sources only; backend held state remains authoritative.
        self.scroll_remainder.clear()
        self.drag = None
        return True


def attach_gtk(ui):
    """Attach to the EXISTING CameraUI after construction; no new layout or window.

    The VM must admit camera_input requests and publish InputSession replies before
    calling this. Keep its input_state in status(); shutdown must call cleanup on
    the serial owner and refuse to claim success if any contact remains held.
    """
    from gi.repository import Gdk, Gtk
    bindings = InputBindings(ui.vm.enqueue)
    mouse_grabs = set()
    pointer_sources = {}
    pointer_number = 0

    def report(action):
        try:
            result = action()
            ui.local_error = ''
            ui.poller.after_input(ui.clock())
            return result
        except (OSError, RuntimeError, ValueError) as error:
            ui.local_error = 'Input not submitted: ' + str(error)
            ui.feedback.set_text(ui.local_error)
            return False

    def send(name, *, position=None):
        ui.state = ui.vm.status()
        reason = ui.reason(name)
        if reason:
            ui.feedback.set_text(reason)
            return False
        if name == 'MODE' and position is None:
            return ui._open_mode_positions()
        result = report(lambda: bindings.activate(name, position=position))
        if result:
            ui.feedback.set_text(name + ': queued; firmware response pending')
        return result

    def key_press(window, event):
        key = Gdk.keyval_name(event.keyval) or ''
        focus = window.get_focus()
        if (event.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK | Gdk.ModifierType.SUPER_MASK)
                or (ui.mode_popover is not None and ui.mode_popover.get_visible())
                or isinstance(focus, (Gtk.ComboBox, Gtk.Entry, Gtk.TextView))
                or key in ('Tab', 'ISO_Left_Tab', 'space')):
            return False
        if key in ('Return', 'KP_Enter') and focus is ui.buttons['MODE']:
            return send('MODE')
        if (key in ('Return', 'KP_Enter') and isinstance(focus, (Gtk.Button, Gtk.Expander))
                and focus not in ui.buttons.values()):
            return False
        shortcut = {'Up': 'ArrowUp', 'Down': 'ArrowDown', 'Left': 'ArrowLeft', 'Right': 'ArrowRight',
                    'Return': 'Enter', 'KP_Enter': 'Enter', 'Page_Up': 'PageUp', 'Page_Down': 'PageDown',
                    'bracketleft': '[', 'bracketright': ']', 'comma': ',', 'period': '.'}.get(key, key)
        if len(shortcut) == 1:
            shortcut = shortcut.lower()
        return report(lambda: bindings.key_press(shortcut, event.hardware_keycode))

    def key_release(_, event):
        return report(lambda: bindings.key_release(event.hardware_keycode))

    def pointer(button, event, name):
        nonlocal pointer_number
        device = event.get_device()
        sequence = event.get_event_sequence()
        if sequence is None and event.button != 1:
            return False
        identity = (device, sequence, None if sequence is not None else event.button)
        if event.type in (Gdk.EventType.BUTTON_PRESS, Gdk.EventType.TOUCH_BEGIN):
            if identity not in pointer_sources:
                pointer_number += 1
                pointer_sources[identity] = f'pointer:{pointer_number}'
            source = pointer_sources[identity]
            if report(lambda: bindings.press(name, source)) and sequence is None:
                button.grab_add()
                mouse_grabs.add(button)
            if source not in bindings.sources:
                pointer_sources.pop(identity, None)
        elif event.type in (Gdk.EventType.BUTTON_RELEASE, Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
            source = pointer_sources.get(identity)
            if source is not None:
                report(lambda: bindings.release(source))
                if source not in bindings.sources:
                    pointer_sources.pop(identity, None)
            if button in mouse_grabs:
                mouse_grabs.discard(button)
                button.grab_remove()
        return True

    def cleanup(*_):
        state = ui.vm.status().get('input_state') or {}
        if bindings.sources or state.get('held') or bindings.drag is not None:
            if not report(bindings.cleanup):
                return False
        pointer_sources.clear()
        for button in tuple(mouse_grabs):
            mouse_grabs.discard(button)
            button.grab_remove()
        return True

    def scroll(_, event, dial):
        if event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, dx, dy = event.get_scroll_deltas()
            if not ok:
                return True
            delta = dy if abs(dy) >= abs(dx) else dx
        else:
            delta = 1 if event.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT) else -1
        report(lambda: bindings.scroll(dial, delta))
        return True

    def drag(widget, event):
        source = (event.get_device(), event.button if event.type != Gdk.EventType.MOTION_NOTIFY else 1)
        if event.type == Gdk.EventType.BUTTON_PRESS:
            box = widget.get_allocation()
            x, y = event.x - box.width / 2, event.y - box.height / 2
            if event.button != 1 or math.hypot(x, y) < box.width * .36:
                return False
            if bindings.drag_start(source, math.atan2(y, x)):
                widget.grab_add()
                mouse_grabs.add(widget)
            return True
        if event.type == Gdk.EventType.MOTION_NOTIFY:
            box = widget.get_allocation()
            return bindings.drag_move(source, math.atan2(event.y - box.height / 2, event.x - box.width / 2))
        if event.type == Gdk.EventType.BUTTON_RELEASE:
            result = report(lambda: bindings.drag_end(source))
            if result and widget in mouse_grabs:
                widget.grab_remove()
                mouse_grabs.discard(widget)
            return result
        return False

    ui.window.disconnect_by_func(ui._key_press)
    ui.window.connect('key-press-event', key_press)
    ui.window.connect('key-release-event', key_release)
    ui.window.connect('focus-out-event', lambda *_: (cleanup(), False)[1])
    ui.send = send
    ui.release_inputs = cleanup
    for name, button in ui.buttons.items():
        entry = key_definition(name)
        if entry['code'] and entry['status'] is None and not entry['positions']:
            button.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.TOUCH_MASK)
            button.connect('button-press-event', pointer, name)
            button.connect('button-release-event', pointer, name)
            button.connect('touch-event', pointer, name)
            button.connect('grab-broken-event', lambda *_: (cleanup(), False)[1])
    scroll_widgets = dict(ui.wheel_widgets)
    for name, button in ui.buttons.items():
        dial = name.rsplit('_', 1)[0]
        if dial in ('FRONT', 'REAR', 'CONTROL'):
            scroll_widgets[button] = dial
    for widget, dial in scroll_widgets.items():
        widget.disconnect_by_func(ui._scroll)
        widget.connect('scroll-event', scroll, dial)
    for signal, old_handler in (('button-press-event', ui._drag_start),
                                ('motion-notify-event', ui._drag_move),
                                ('button-release-event', ui._drag_end)):
        ui.ring.disconnect_by_func(old_handler)
        ui.ring.connect(signal, drag)
    ui.ring.connect('grab-broken-event', lambda *_: (cleanup(), False)[1])
    return bindings
