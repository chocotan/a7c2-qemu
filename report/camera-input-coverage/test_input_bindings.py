"""No VM, display, sockets, firmware/private assets or physical media are opened."""
import ast
import ctypes
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import types

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNTIME = ROOT / 'runtime/analysis'
sys.path.insert(0, str(RUNTIME))
sys.path.insert(0, str(HERE))
from input_bindings import (HOST_KEYS, MAX_TICKS, PHYSICAL_CONTROLS, UNSUPPORTED,
                            InputBindings, InputSession, attach_gtk, validate_request)
from menu_live import control_catalog, key_definition

PINS = json.loads((HERE / 'source-pins.json').read_text())
CONTACTS = [name for name in PINS['raw_to_canonical']
            if key_definition(name)['status'] is None and not key_definition(name)['positions']]


def request(op, **fields):
    return {'action': 'camera_input', 'op': op, **fields}


@pytest.fixture(scope='session')
def encoder(tmp_path_factory):
    compiler = shutil.which('cc')
    assert compiler, 'The existing native C encoder check requires the host C compiler'
    directory = tmp_path_factory.mktemp('camera-input-encoder')
    source = directory / 'queue.c'
    source.write_text(r'''
#include <assert.h>
#include <string.h>
#define INJECT_KEY_HOST_TEST
#define printf quiet_printf
#include "''' + str(RUNTIME / 'inject-key.c') + r'''"
#undef printf
int quiet_printf(const char *fmt, ...){(void)fmt;return 0;}
static unsigned int data[8],history[4096][12],count,bytes,source_id,freed,fail_at;
int osal_valloc_msg_wait(unsigned int q,void **p,unsigned int n,int wait){
 assert(q && wait==1 && (n==20 || n==32));bytes=n;memset(data,0xaa,sizeof data);*p=data;return 0;
}
void osal_set_msg_src(void *p,unsigned int src){assert(p==data);source_id=src;}
int osal_snd_msg(unsigned int q,void *p){
 assert(p==data && count<4096);unsigned int *event=history[count++];
 event[0]=q;event[1]=source_id;event[2]=bytes;
 memcpy(event+3,data,bytes);return count==fail_at?7:0;
}
int osal_free_msg(unsigned int q,void *p){assert(q && p==data);freed++;return 0;}
int invoke(int argc,char **argv){return run(argc,argv);}
void reset(void){count=freed=fail_at=0;}
void fail(unsigned int n){fail_at=n;}
unsigned int sends(void){return count;}
unsigned int frees(void){return freed;}
unsigned int word(unsigned int event,unsigned int index){assert(event<count && index<12);return history[event][index];}
''')
    library = directory / 'queue.so'
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                    str(source), '-o', str(library)], check=True, capture_output=True, text=True)
    lib = ctypes.CDLL(str(library))
    lib.invoke.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
    lib.invoke.restype = ctypes.c_int
    lib.word.argtypes = [ctypes.c_uint, ctypes.c_uint]
    lib.word.restype = ctypes.c_uint
    return lib


@pytest.fixture
def wire(encoder):
    encoder.reset()

    class Wire:
        def __call__(self, command):
            args = shlex.split(command)
            assert args[0] == '/simulation/inject-key'
            values = [arg.encode('ascii') for arg in args]
            argv = (ctypes.c_char_p * len(values))(*values)
            rc = encoder.invoke(len(values), argv)
            if rc:
                raise RuntimeError(f'actual encoder/send rc={rc}')
            return b'checked serial command rc=0'

        def fail(self, number):
            encoder.fail(number)

        @property
        def events(self):
            result = []
            for event in range(encoder.sends()):
                words = [encoder.word(event, i) for i in range(11)]
                result.append({'queue': words[0], 'source': words[1], 'bytes': words[2],
                               'words': words[3:3 + words[2] // 4]})
            return result

        @property
        def statuses(self):
            return [(event['words'][0], event['words'][2]) for event in self.events]

        @property
        def freed(self):
            return encoder.frees()

    return Wire()


def assert_event(event, name, status, app):
    route = PINS['routes']['app32' if app else 'infra20']
    raw = int(PINS['raw_to_canonical'][name]['raw'], 0)
    expected = [raw, 0, status, 0, 0, 0, 0, 0] if app else [raw, 0, status, 0, 1]
    assert event == {'queue': int(route['queue'], 0), 'source': int(route['source'], 0),
                     'bytes': route['bytes'], 'words': expected}


def test_pinned_source_contracts_and_complete_host_inventory():
    for pin in PINS['sources']:
        source = (ROOT / pin['path']).read_text()
        if 'symbol' in pin:
            nodes = {}
            for node in ast.parse(source).body:
                if isinstance(node, ast.FunctionDef):
                    nodes[node.name] = node
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            nodes[target.id] = node
            source = ast.get_source_segment(source, nodes[pin['symbol']])
        assert hashlib.sha256(source.encode()).hexdigest() == pin['sha256'], pin
    catalog = control_catalog()
    assert set(PHYSICAL_CONTROLS) <= set(PINS['raw_to_canonical'])
    assert set(catalog) == set(PINS['raw_to_canonical']) | {'EXPOSURE_COMP'}
    assert set(UNSUPPORTED) == set(PINS['unsupported']) == {'AEL', 'EXPOSURE_COMP'}
    assert not catalog['EXPOSURE_COMP']['available'] and 'AEL' not in catalog
    assert set(PHYSICAL_CONTROLS) - {'DISP', 'ISO', 'DELETE'} <= {value[0] for value in HOST_KEYS.values()}
    assert dict(key_definition('MODE')['positions']) == PINS['mode_positions']
    for name, pin in PINS['raw_to_canonical'].items():
        assert int(key_definition(name)['code'], 0) == int(pin['raw'], 0)
    for name, entry in catalog.items():
        for shortcut in entry['shortcuts']:
            assert HOST_KEYS[shortcut] == (name, None)


@pytest.mark.parametrize('app', [False, True])
@pytest.mark.parametrize('name', CONTACTS)
def test_all_contacts_use_actual_encoder_and_original_queue(wire, app, name):
    session = InputSession(wire, app_input=app)
    reply = session.handle(request('tap', key=name, source='mouse:1'))
    assert reply['ok'] and not reply['input_state']['held']
    contacts = [('SHUTTER_HALF', 1), ('SHUTTER', 1), ('SHUTTER', 0), ('SHUTTER_HALF', 0)] if name == 'SHUTTER' else [(name, 1), (name, 0)]
    assert len(wire.events) == len(contacts)
    for event, (key, status) in zip(wire.events, contacts):
        assert_event(event, key, status, app)


@pytest.mark.parametrize('app', [False, True])
@pytest.mark.parametrize('dial', ['FRONT', 'REAR', 'CONTROL'])
@pytest.mark.parametrize('ticks', [-32, -1, 1, 32])
def test_all_dials_send_signed_u32_increments_without_release(wire, app, dial, ticks):
    session = InputSession(wire, app_input=app)
    reply = session.handle(request('rotate', dial=dial, ticks=ticks))
    assert reply['ok'] and reply['completed_ticks'] == abs(ticks)
    assert len(wire.events) == abs(ticks)
    direction = 'RIGHT' if ticks > 0 else 'LEFT'
    for event in wire.events:
        assert_event(event, dial + '_' + direction, int(PINS['dial_status'][direction.lower()], 0), app)


@pytest.mark.parametrize('app', [False, True])
@pytest.mark.parametrize('position,status', list(PINS['mode_positions'].items()))
def test_all_mode_positions_use_original_wire_values(wire, app, position, status):
    session = InputSession(wire, app_input=app)
    assert session.handle(request('position', key='MODE', position=position))['ok']
    assert len(wire.events) == 1
    assert_event(wire.events[0], 'MODE', status, app)


@pytest.mark.parametrize('app', [False, True])
@pytest.mark.parametrize('name,status', [('MODE_STILL', 1), ('MODE_MOVIE', 2), ('MODE_SQ', 3)])
def test_three_position_selector_has_no_fake_release(wire, app, name, status):
    session = InputSession(wire, app_input=app)
    assert session.handle(request('tap', key=name, source='controller:mode'))['ok']
    assert len(wire.events) == 1
    assert_event(wire.events[0], name, status, app)


def test_duplicate_press_aliases_and_distinct_pointer_owners(wire):
    session = InputSession(wire, app_input=True)
    for key, source in [('DELETE', 'touch:1'), ('DELETE', 'touch:1'), ('C2', 'touch:2')]:
        assert session.handle(request('press', key=key, source=source))['ok']
    assert len(wire.events) == 1
    assert not session.handle(request('press', key='MENU', source='touch:1'))['ok']
    assert not session.handle(request('tap', key='C2', source='touch:1'))['ok']
    assert session.handle(request('release', source='touch:unrelated'))['ok']
    assert session.handle(request('release', source='touch:1'))['ok']
    assert len(wire.events) == 1
    assert session.handle(request('release', source='touch:2'))['ok']
    assert wire.statuses == [(0x1f8, 1), (0x1f8, 0)]


@pytest.mark.parametrize('release_first', ['half', 'full'])
def test_half_full_contacts_share_ownership_and_release_in_order(wire, release_first):
    session = InputSession(wire, app_input=True)
    assert session.handle(request('press', key='SHUTTER_HALF', source='half'))['ok']
    assert session.handle(request('press', key='SHUTTER', source='full'))['ok']
    assert session.handle(request('release', source=release_first))['ok']
    assert session.handle(request('cleanup'))['ok']
    assert wire.statuses == [(0x1f1, 1), (0xa7, 1), (0xa7, 0), (0x1f1, 0)]


@pytest.mark.parametrize('failed_send', [1, 2, 3, 4])
def test_every_full_tap_failure_preserves_errors_and_cleanup_truth(wire, failed_send):
    wire.fail(failed_send)
    session = InputSession(wire, app_input=True)
    reply = session.handle(request('tap', key='SHUTTER', source='s'))
    assert not reply['ok'] and 'rc=4' in reply['input_state']['error'] and wire.freed == 1
    if failed_send in (3, 4):
        assert reply['input_state']['held'] and reply['input_state']['uncertain_codes']
        if failed_send == 3:
            assert wire.statuses[-1] == (0xa7, 0)  # Half must stay held after failed full release.
        assert session.handle(request('release', source='unrelated'))['input_state']['error']
        assert not session.handle(request('press', key='MENU', source='new'))['ok']
    wire.fail(0)
    result = session.handle(request('cleanup'))
    assert result['ok'] and result['input_state'] == {'held': [], 'uncertain_codes': [], 'error': ''}
    assert wire.statuses[-1][1] == 0


def test_failed_press_does_not_send_full_and_release_failure_remains_visible(wire):
    session = InputSession(wire, app_input=False)
    wire.fail(1)
    reply = session.handle(request('press', key='SHUTTER', source='mouse'))
    assert not reply['ok'] and wire.statuses == [(0x1f1, 1)]
    assert reply['input_state']['held'][0]['contacts'] == ['SHUTTER_HALF']
    wire.fail(2)
    reply = session.handle(request('cleanup'))
    assert not reply['ok'] and reply['input_state']['held']
    wire.fail(0)
    assert session.handle(request('cleanup'))['ok']


def test_cleanup_releases_independent_contacts_after_one_failure(wire):
    session = InputSession(wire, app_input=True)
    session.handle(request('press', key='SHUTTER', source='full'))
    session.handle(request('press', key='MENU', source='menu'))
    wire.fail(4)
    result = session.handle(request('cleanup'))
    assert not result['ok']
    assert [item['source'] for item in result['input_state']['held']] == ['full']
    assert wire.statuses[-2:] == [(0xa7, 0), (0x1ab, 0)]
    wire.fail(0)
    assert session.handle(request('cleanup'))['ok']


def test_both_press_and_release_failures_are_reported():
    def broken(_):
        raise RuntimeError('selected serial owner failed')
    result = InputSession(broken, app_input=True).handle(request('tap', key='MENU', source='x'))
    assert not result['ok'] and 'press:' in result['input_state']['error'] and 'release:' in result['input_state']['error']
    assert result['input_state']['held'] and result['input_state']['uncertain_codes'] == ['0x1ab']


def test_async_enqueue_cannot_be_misreported_as_wire_ack():
    session = InputSession(lambda _: None, app_input=True)
    reply = session.handle(request('press', key='REC', source='controller:7'))
    assert not reply['ok'] and reply['input_state']['held']
    assert reply['input_state']['uncertain_codes'] == ['0x1f0']


def test_partial_rotation_reports_exact_sent_prefix_without_automatic_replay(wire):
    wire.fail(3)
    session = InputSession(wire, app_input=True)
    result = session.handle(request('rotate', dial='CONTROL', ticks=-8))
    assert not result['ok'] and result['completed_ticks'] == 2 and len(wire.events) == 3
    assert not result['input_state']['held']


@pytest.mark.parametrize('bad', [
    None, [], {}, {'action': 'camera_input', 'op': []},
    request('press', key='AEL', source='x'), request('press', key='EXPOSURE_COMP', source='x'),
    request('press', key='REAR_LEFT', source='x'), request('press', key='MODE', source='x'),
    request('press', key='MENU', source=''), request('press', key='MENU', source='x\n'),
    request('press', key='MENU', source='x' * 97), request('press', key='MENU', source='触屏'),
    request('release', source='x', key='MENU'), request('cleanup', source='x'),
    request('rotate', dial='REAR', ticks=True), request('rotate', dial='REAR', ticks=0),
    request('rotate', dial='REAR', ticks=33), request('rotate', dial='REAR', ticks=-33),
    request('rotate', dial='REAR', ticks=1.5), request('rotate', dial='AEL', ticks=1),
    request('position', key='MODE', position='MOVIE'), request('position', key='MODE', position=3),
    request('tap', key='MODE', source='x'), request('position', key='MENU', position='P'),
])
def test_untrusted_requests_are_rejected_before_any_send(wire, bad):
    session = InputSession(wire, app_input=True)
    with pytest.raises(ValueError):
        session.handle(bad)
    assert not wire.events


def test_keyboard_mouse_controller_repeat_and_failed_enqueue(wire):
    session = InputSession(wire, app_input=True)
    queued = []
    bindings = InputBindings(queued.append)
    assert bindings.key_press('h', 43)
    assert bindings.key_press('h', 43)
    assert bindings.press('SHUTTER', 'controller:trigger')
    assert not bindings.release('touch:unrelated')
    assert bindings.key_release(43)
    assert bindings.release('controller:trigger')
    assert len(queued) == 4 and not wire.events
    for message in queued:
        assert session.handle(message)['ok']
    assert wire.statuses == [(0x1f1, 1), (0xa7, 1), (0xa7, 0), (0x1f1, 0)]
    bindings.press('MENU', 'mouse:1')
    def full(_):
        raise ValueError('queue full')
    bindings.enqueue = full
    with pytest.raises(ValueError, match='queue full'):
        bindings.release('mouse:1')
    assert bindings.sources == {'mouse:1': 'MENU'}
    with pytest.raises(ValueError, match='queue full'):
        bindings.cleanup()
    assert bindings.sources == {'mouse:1': 'MENU'}


@pytest.mark.parametrize('shortcut', list(HOST_KEYS))
def test_every_host_shortcut_reaches_source_backed_backend_without_repeat(wire, shortcut):
    session = InputSession(wire, app_input=True)
    replies = []
    bindings = InputBindings(lambda message: replies.append(session.handle(message)))
    assert bindings.key_press(shortcut, 17)
    count = len(wire.events)
    assert bindings.key_press(shortcut, 17) and len(wire.events) == count
    assert bindings.key_release(17)
    assert all(reply['ok'] for reply in replies)
    assert not session.status()['held']


def test_scroll_fraction_sign_bounds_and_failure_retention():
    queued = []
    bindings = InputBindings(queued.append)
    assert not bindings.scroll('FRONT', .4)
    assert not bindings.scroll('REAR', -.75)
    assert bindings.scroll('FRONT', .7) and queued[-1]['ticks'] == 1
    assert bindings.scroll('REAR', -.5) and queued[-1]['ticks'] == -1
    assert bindings.scroll('CONTROL', 10000.5) and queued[-1]['ticks'] == MAX_TICKS
    assert not bindings.scroll('CONTROL', 0)
    for delta in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            bindings.scroll('CONTROL', delta)
    before = dict(bindings.scroll_remainder)
    def full(_):
        raise ValueError('full')
    bindings.enqueue = full
    with pytest.raises(ValueError):
        bindings.scroll('CONTROL', 1)
    assert bindings.scroll_remainder == before


def test_angular_wrap_is_signed_bounded_and_ignores_other_touches():
    queued = []
    bindings = InputBindings(queued.append)
    assert bindings.drag_start('touch:1', math.radians(170))
    assert not bindings.drag_start('touch:2', 0)
    assert not bindings.drag_move('touch:2', 1)
    assert not bindings.drag_end('touch:2')
    assert bindings.drag_move('touch:1', math.radians(-170))
    assert bindings.drag_end('touch:1') and queued[-1]['ticks'] == 1
    assert bindings.drag_start('mouse', math.radians(-170))
    bindings.drag_move('mouse', math.radians(170))
    bindings.drag_end('mouse')
    assert queued[-1]['ticks'] == -1
    bindings.drag_start('mouse', 0)
    for tick in range(100):
        bindings.drag_move('mouse', tick * math.pi / 2)
    bindings.drag_end('mouse')
    assert queued[-1]['ticks'] == MAX_TICKS


class Widget:
    def __init__(self, **_):
        self.signals = {}
        self.grabbed = False
        self.text = ''
    def connect(self, name, callback, *args):
        self.signals.setdefault(name, []).append((callback, args))
    def disconnect_by_func(self, callback):
        for name in self.signals:
            self.signals[name] = [(fn, args) for fn, args in self.signals[name] if fn != callback]
    def emit(self, name, *args):
        for callback, extra in self.signals.get(name, []):
            if callback(self, *args, *extra):
                return True
        return False
    def get_style_context(self): return self
    def add_class(self, _): pass
    def set_size_request(self, *_): pass
    def set_valign(self, *_): pass
    def add_events(self, *_): pass
    def grab_add(self): self.grabbed = True
    def grab_remove(self): self.grabbed = False
    def set_text(self, value): self.text = value
    def get_focus(self): return None
    def get_allocation(self): return types.SimpleNamespace(width=200, height=200)


@pytest.fixture
def gtk_ui(monkeypatch, wire):
    class Button(Widget): pass
    class Entry(Widget): pass
    class ComboBox(Widget): pass
    class TextView(Widget): pass
    class Expander(Widget): pass
    Gtk = types.SimpleNamespace(Button=Button, Entry=Entry, ComboBox=ComboBox, TextView=TextView,
                                Expander=Expander, Align=types.SimpleNamespace(CENTER=0))
    Gdk = types.SimpleNamespace(
        EventMask=types.SimpleNamespace(BUTTON_PRESS_MASK=1, BUTTON_RELEASE_MASK=2, TOUCH_MASK=4, SCROLL_MASK=8, SMOOTH_SCROLL_MASK=16),
        EventType=types.SimpleNamespace(BUTTON_PRESS=1, BUTTON_RELEASE=2, TOUCH_BEGIN=3, TOUCH_END=4, TOUCH_CANCEL=5, MOTION_NOTIFY=6),
        ModifierType=types.SimpleNamespace(CONTROL_MASK=1, MOD1_MASK=2, SUPER_MASK=4),
        ScrollDirection=types.SimpleNamespace(SMOOTH=0, DOWN=1, RIGHT=2, UP=3, LEFT=4), keyval_name=lambda key: key)
    gi = types.ModuleType('gi')
    gi.require_version = lambda *_: None
    repo = types.ModuleType('gi.repository')
    for name, value in {'Gtk': Gtk, 'Gdk': Gdk, 'Atk': object(), 'GdkPixbuf': object(),
                        'GLib': object(), 'Pango': object(), 'PangoCairo': object()}.items():
        setattr(repo, name, value)
    monkeypatch.setitem(sys.modules, 'gi', gi)
    monkeypatch.setitem(sys.modules, 'gi.repository', repo)
    spec = importlib.util.spec_from_file_location('offline_camera_ui', RUNTIME / 'camera_ui.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    session = InputSession(wire, app_input=True)
    queued = []
    class VM:
        def enqueue(self, message):
            validate_request(message)
            queued.append(message)
        def status(self):
            return {'state': 'running', 'controls': control_catalog(), 'input_state': session.status()}
    ui = module.CameraUI.__new__(module.CameraUI)
    ui.vm, ui.buttons, ui.window, ui.ring = VM(), {}, Widget(), Widget()
    ui.closing = ui.reinitializing = False
    ui.mode_popover = None
    ui.feedback, ui.local_error = Widget(), ''
    ui.clock = lambda: 0
    ui.poller = types.SimpleNamespace(after_input=lambda *_: None)
    ui.state = ui.vm.status()
    ui._close = lambda *_: setattr(ui, 'close_called', True) or True
    ui._open_mode_positions = lambda: True
    ui.window.connect('key-press-event', ui._key_press)
    ui.window.connect('delete-event', ui._close)
    for name in control_catalog():
        ui._button(name)
    ui.wheel_widgets = [(Widget(), prefix) for prefix in ('FRONT', 'REAR', 'CONTROL')]
    for widget, prefix in ui.wheel_widgets:
        widget.connect('scroll-event', ui._scroll, prefix)
    for signal, callback in (('button-press-event', ui._drag_start), ('motion-notify-event', ui._drag_move), ('button-release-event', ui._drag_end)):
        ui.ring.connect(signal, callback)
    bindings = attach_gtk(ui)
    def drain():
        while queued:
            assert session.handle(queued.pop(0))['ok']
    return ui, bindings, queued, session, drain, Gdk


def event(kind, *, key='', code=7, device=1, sequence=None, button=1, x=199, y=100):
    return types.SimpleNamespace(type=kind, keyval=key, hardware_keycode=code, state=0, button=button,
                                 x=x, y=y, get_device=lambda: device, get_event_sequence=lambda: sequence)


def test_existing_gtk_button_keyboard_and_touch_callers_reach_original_encoder(gtk_ui, wire):
    ui, bindings, queued, session, drain, Gdk = gtk_ui
    ui.buttons['C1'].emit('clicked')  # Actual CameraUI._button closure resolves installed send.
    assert len(queued) == 1 and not wire.events
    drain()
    assert wire.statuses == [(0x66, 1), (0x66, 0)]
    key = event(1, key='s')
    ui.window.emit('key-press-event', key)
    ui.window.emit('key-press-event', key)
    drain()
    assert session.status()['held'][0]['key'] == 'SHUTTER'
    key.keyval, key.state = 'S', 1  # Release still works after modifiers/focus change.
    ui.window.emit('key-release-event', key)
    drain()
    assert wire.statuses[-4:] == [(0x1f1, 1), (0xa7, 1), (0xa7, 0), (0x1f1, 0)]
    ui.buttons['DELETE'].emit('touch-event', event(Gdk.EventType.TOUCH_BEGIN, sequence=1))
    ui.buttons['C2'].emit('touch-event', event(Gdk.EventType.TOUCH_BEGIN, sequence=2))
    drain()
    assert len(session.status()['held']) == 2
    ui.buttons['DELETE'].emit('touch-event', event(Gdk.EventType.TOUCH_END, sequence=1))
    drain()
    assert wire.statuses[-1] == (0x1f8, 1)
    ui.buttons['C2'].emit('touch-event', event(Gdk.EventType.TOUCH_CANCEL, sequence=2))
    drain()
    assert not session.status()['held'] and wire.statuses[-1] == (0x1f8, 0)


def test_touch_hash_collisions_do_not_release_another_finger(gtk_ui, wire):
    ui, bindings, queued, session, drain, Gdk = gtk_ui
    class Sequence:
        def __hash__(self): return 1
    first, second = Sequence(), Sequence()
    ui.buttons['MENU'].emit('touch-event', event(Gdk.EventType.TOUCH_BEGIN, sequence=first))
    ui.buttons['REC'].emit('touch-event', event(Gdk.EventType.TOUCH_BEGIN, sequence=second))
    drain()
    assert len(session.status()['held']) == 2
    ui.buttons['MENU'].emit('touch-event', event(Gdk.EventType.TOUCH_END, sequence=first))
    drain()
    assert session.status()['held'][0]['key'] == 'REC'
    ui.buttons['REC'].emit('touch-event', event(Gdk.EventType.TOUCH_CANCEL, sequence=second))
    drain()
    assert not session.status()['held']


def test_gtk_mouse_capture_focus_cleanup_and_all_existing_scroll_surfaces(gtk_ui, wire):
    ui, bindings, queued, session, drain, Gdk = gtk_ui
    button = ui.buttons['AF_ON']
    button.emit('button-press-event', event(Gdk.EventType.BUTTON_PRESS))
    assert button.grabbed
    drain()
    ui.window.emit('focus-out-event', event(0))
    assert not button.grabbed
    assert session.status()['held']  # Enqueue is not a release acknowledgement.
    drain()
    assert not session.status()['held']
    surfaces = list(ui.wheel_widgets) + [(ui.buttons[prefix + '_LEFT'], prefix) for prefix in ('FRONT', 'REAR', 'CONTROL')]
    for widget, dial in surfaces:
        scroll = types.SimpleNamespace(direction=Gdk.ScrollDirection.DOWN)
        widget.emit('scroll-event', scroll)
        assert queued[-1] == request('rotate', dial=dial, ticks=1)
    drain()
    assert len(wire.events) == 2 + len(surfaces)
    button.emit('button-press-event', event(Gdk.EventType.BUTTON_PRESS))
    drain()
    button.emit('grab-broken-event', event(0))
    assert queued[-1] == request('cleanup') and session.status()['held']
    drain()
    assert not session.status()['held']


def test_actual_vm_admission_bounded_queue_route_and_release_during_fault():
    from menu_control import VM
    vm = VM()
    assert vm.supports_input_lifecycle
    vm.state = 'running'
    with pytest.raises(ValueError):
        vm.enqueue(request('press', key='MENU', source='m'))
    vm.input_lifecycle = True
    command = request('press', key='MENU', source='m')
    vm.enqueue(command)
    command['key'] = 'bad'
    assert vm.commands.get_nowait() == request('press', key='MENU', source='m')
    vm.sd_card = {'state': 'uncertain'}
    with pytest.raises(ValueError):
        vm.enqueue(request('press', key='MENU', source='m'))
    assert not vm._admit_queued(request('press', key='MENU', source='m'))
    assert vm._admit_queued(request('release', source='m'))
    vm.state = 'faulted'
    vm.enqueue(request('release', source='m'))
    vm.enqueue(request('cleanup'))
    with pytest.raises(ValueError):
        vm.enqueue(request('cleanup', key='MENU'))
    assert vm.status()['input_state'] == {'held': [], 'uncertain_codes': [], 'error': ''}
    for _ in range(6):
        vm.enqueue(request('cleanup'))
    with pytest.raises(ValueError, match='队列已满'):
        vm.enqueue(request('cleanup'))


@pytest.mark.parametrize('app', [False, True])
def test_actual_live_owner_handles_queue_and_shutdown_cleanup_without_vm(monkeypatch, tmp_path, wire, app):
    import menu_live
    messages = [request('press', key='SHUTTER_HALF', source='keyboard:1'),
                request('press', key='SHUTTER', source='controller:trigger'),
                request('release', source='keyboard:1'),
                {'action': 'key', 'key': 'MENU'},  # Must not disturb shared contacts.
                request('rotate', dial='FRONT', ticks=-2),
                request('position', key='MODE', position='MR2'),
                {'action': 'export_sd'}]
    replies, exported = [], []
    for name in ('MENU_LIVE_KEY_FILE', 'MENU_LIVE_APP_INPUT', 'MENU_GUI_MODELS',
                 'A7C2_EE_PASSIVE_ON_STILL_ENTRY', 'A7C2_EE_PASSIVE_AFTER_SHUTTER'):
        monkeypatch.delenv(name, raising=False)
    if app:
        monkeypatch.setenv('MENU_LIVE_APP_INPUT', '1')
    (tmp_path / 'console.log').write_bytes(b'')
    class Proc:
        def poll(self):
            return 0 if not messages and len(replies) == 8 else None
        returncode = 0
    class Control:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
    monkeypatch.setattr(menu_live, 'socket', types.SimpleNamespace(socket=Control))
    monkeypatch.setattr(menu_live, 'select', types.SimpleNamespace(select=lambda *_: ([1], [], [])))
    monkeypatch.setattr(menu_live, 'send_message', lambda _, message: replies.append(message))
    monkeypatch.setattr(menu_live, 'receive_message', lambda *_args, **_kwargs: messages.pop(0))
    def serial(_proc, _console, command, **_):
        return b'' if command == 'true' else wire(command)
    monkeypatch.setattr(menu_live, 'serial_command', serial)
    def export():
        exported.append(list(wire.statuses))
        return {'ok': True}
    menu_live.run_live(Proc(), tmp_path, 999, sd_export=export)
    assert replies[0]['input_lifecycle'] is True
    assert replies[4]['type'] == 'error' and 'legacy tap' in replies[4]['error']
    assert replies[-1]['ok'] and not replies[-1]['input_state']['held']
    assert exported and exported[0][-2:] == [(0xa7, 0), (0x1f1, 0)]
    assert wire.statuses == [(0x1f1, 1), (0xa7, 1), (0x1000001c, 0xfffffc00),
                             (0x1000001c, 0xfffffc00), (0x7025, 19), (0xa7, 0), (0x1f1, 0)]
    assert_event(wire.events[0], 'SHUTTER_HALF', 1, app)


def test_actual_live_owner_failed_cleanup_prevents_export(monkeypatch, tmp_path, wire):
    import menu_live
    messages = [request('press', key='MENU', source='x'), {'action': 'export_sd'}]
    replies = []
    for name in ('MENU_LIVE_KEY_FILE', 'MENU_LIVE_APP_INPUT', 'MENU_GUI_MODELS', 'A7C2_EE_PASSIVE_ON_STILL_ENTRY'):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / 'console.log').write_bytes(b'')
    class Proc:
        returncode = 0
        def poll(self): return 0 if len(replies) == 3 else None
    class Control:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
    monkeypatch.setattr(menu_live, 'socket', types.SimpleNamespace(socket=Control))
    monkeypatch.setattr(menu_live, 'select', types.SimpleNamespace(select=lambda *_: ([1], [], [])))
    monkeypatch.setattr(menu_live, 'send_message', lambda _, value: replies.append(value))
    monkeypatch.setattr(menu_live, 'receive_message', lambda *_args, **_kwargs: messages.pop(0))
    monkeypatch.setattr(menu_live, 'serial_command', lambda proc, console, command, **_: b'' if command == 'true' else wire(command))
    wire.fail(2)
    def export():
        raise AssertionError('Failed release must not reach SD export')
    menu_live.run_live(Proc(), tmp_path, 999, sd_export=export)
    assert replies[-1]['type'] == 'sd_export' and not replies[-1]['ok']
    assert replies[-1]['input_state']['held'] and replies[-1]['input_state']['uncertain_codes']


def test_actual_vm_response_branch_publishes_failed_and_retried_state():
    from menu_control import VM
    tree = ast.parse((RUNTIME / 'menu_control.py').read_text())
    vm_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'VM')
    run = next(node for node in vm_class.body if isinstance(node, ast.FunctionDef) and node.name == '_run')
    branch = next(node for node in ast.walk(run) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.BoolOp)
                  and any(isinstance(item, ast.Constant) and item.value == 'camera_input' for item in ast.walk(node.test)))
    function = ast.FunctionDef(name='reply', args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=name) for name in ('self', 'command', 'reply')],
                        kwonlyargs=[], kw_defaults=[], defaults=[]), body=[ast.If(test=branch.test, body=branch.body,
                        orelse=[ast.Raise(exc=ast.Call(func=ast.Name(id='ValueError', ctx=ast.Load()), args=[], keywords=[]))])],
                        decorator_list=[])
    namespace = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), 'actual VM._run response branch', 'exec'), namespace)
    vm = VM()
    command = request('cleanup')
    held = {'held': [{'source': 'mouse', 'key': 'MENU', 'contacts': ['MENU']}], 'error': 'release failed', 'uncertain_codes': ['0x1ab']}
    namespace['reply'](vm, command, {'type': 'camera_input', 'ok': False, 'request': command, 'input_state': held})
    assert vm.status()['input_state'] == held and 'release failed' in vm.error and vm.stale
    clean = {'held': [], 'error': '', 'uncertain_codes': []}
    namespace['reply'](vm, command, {'type': 'camera_input', 'ok': True, 'request': command, 'input_state': clean})
    assert not vm.error and vm.status()['input_state'] == clean
    with pytest.raises(ValueError):
        namespace['reply'](vm, command, {'type': 'camera_input', 'ok': True, 'request': request('release', source='other'), 'input_state': clean})


def test_selected_ui_constructor_and_off_close_call_the_installed_bindings(gtk_ui, monkeypatch):
    ui, bindings, queued, session, drain, Gdk = gtk_ui
    # Use the existing production class loaded by the offline GTK fixture.
    camera_class = type(ui)
    import menu_live
    called = []
    monkeypatch.setattr(menu_live.camera_input_module(), 'attach_gtk', lambda instance: called.append(instance) or bindings)
    constructor = next(node for node in ast.parse((RUNTIME / 'camera_ui.py').read_text()).body if isinstance(node, ast.ClassDef) and node.name == 'CameraUI')
    init = next(node for node in constructor.body if isinstance(node, ast.FunctionDef) and node.name == '__init__')
    install = next(node for node in init.body if isinstance(node, ast.If) and any(isinstance(item, ast.Constant) and item.value == 'supports_input_lifecycle' for item in ast.walk(node.test)))
    body = ast.Module(body=install.body, type_ignores=[])
    exec(compile(ast.fix_missing_locations(body), 'actual CameraUI.__init__ installation', 'exec'), {'self': ui})
    assert called == [ui] and ui.input_bindings is bindings
    ui.release_inputs = lambda: False
    ui._cancel_drag = lambda: None
    ui.vm.stop = lambda: called.append('stop')
    camera_class.power(ui, False)
    assert called == [ui]
    ui.reset_dialog = None
    assert camera_class._close(ui) is True and not ui.closing
    ui.release_inputs = lambda: True
    ui.update = lambda state: None
    camera_class.power(ui, False)
    assert called[-1] == 'stop'
