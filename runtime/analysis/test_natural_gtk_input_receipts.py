"""Exercise the real checker/GTK bindings/VM receipt branch and native encoder, without a VM."""
import ast
import base64
import hashlib
import zlib
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load('natural_input_receipts', HERE / 'check-natural-gtk-input.py')
coverage = load('natural_input_fixture', HERE.parents[1] / 'report/camera-input-coverage/test_input_bindings.py')
encoder, wire, gtk_ui = coverage.encoder, coverage.wire, coverage.gtk_ui


def compile_nodes(nodes, namespace):
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
                 str(HERE / 'check-natural-gtk-input.py'), 'exec'), namespace)


@pytest.fixture
def route(monkeypatch, tmp_path, gtk_ui, wire):
    import menu_control
    from menu_control import VM
    ui, bindings, _, session, _, Gdk = gtk_ui
    vm = VM()
    vm.state, vm.input_lifecycle = 'running', True
    vm.event('ready')
    ui.vm, bindings.enqueue = vm, vm.enqueue
    incoming, clock, calls = [], [0.0], []
    monkeypatch.setattr(menu_control, 'receive_message', lambda *_args, **_kwargs: incoming.pop(0))
    # These two assignments are made by the actual embedded DRIVER; undo them after each test.
    monkeypatch.setattr(VM, 'event', VM.event)
    namespace = dict(vars(checker), VM=VM, menu_control=menu_control, threading=threading,
                     geometry=tmp_path / 'geometry.json', ui_instance=ui,
                     main_thread=threading.get_ident(), original_status=VM.status)
    tree = ast.parse(checker.DRIVER)
    names = {'receipt_context', 'original_receive', 'original_event', 'observed_reply', 'observed_event'}
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name in names or
             isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id in names or
                 isinstance(target, ast.Attribute) and target.attr in ('receive_message', 'event')
                 for target in node.targets)]
    compile_nodes(nodes, namespace)
    compile_nodes([next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == 'observed_status')], namespace)
    for index, button in enumerate(ui.buttons.values()):
        button.translate_coordinates = lambda *_args, i=index: (10 + i * 50, 17)
        button.get_allocated_width = button.get_allocated_height = lambda: 44
        button.get_mapped = lambda: True

    # Run the real VM._run response branch, including its command/reply equality guard.
    vm_tree = ast.parse((HERE / 'menu_control.py').read_text())
    vm_class = next(node for node in vm_tree.body if isinstance(node, ast.ClassDef) and node.name == 'VM')
    run = next(node for node in vm_class.body if isinstance(node, ast.FunctionDef) and node.name == '_run')
    branch = next(node for node in ast.walk(run) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.BoolOp)
                  and any(isinstance(item, ast.Constant) and item.value == 'camera_input'
                          for item in ast.walk(node.test)))
    accept = ast.FunctionDef(name='accept', args=ast.arguments(
        posonlyargs=[], args=[ast.arg(arg=name) for name in ('self', 'command', 'reply')],
        kwonlyargs=[], kw_defaults=[], defaults=[]), decorator_list=[], body=[ast.If(
            test=branch.test, body=branch.body, orelse=[ast.Raise(exc=ast.Call(
                func=ast.Name(id='RuntimeError', ctx=ast.Load()),
                args=[ast.Constant(value='mismatched command reply')], keywords=[]))])])
    compile_nodes([accept], namespace)

    def sample():
        namespace['observed_status'](vm)
        return json.loads(namespace['geometry'].read_text())

    def publish(command, reply):
        incoming.append(reply)
        received = menu_control.receive_message(None)
        namespace['accept'](vm, command, received)

    def step(seconds):
        clock[0] += seconds
        if not vm.commands.empty():
            command = vm.commands.get_nowait()
            vm.busy = command['action']
            publish(command, session.handle(command))
            vm.busy = ''
        sample()

    mouse_name = [None]
    def xdo(*args):
        calls.append(args)
        if args[0] == 'mousemove':
            points = sample()['button_positions']
            mouse_name[0] = next(name for name, point in points.items() if point == list(args[-2:]))
        elif args[0] == 'click':
            button = ui.buttons[mouse_name[0]]
            pressed=button.emit('button-press-event', coverage.event(Gdk.EventType.BUTTON_PRESS))
            released=button.emit('button-release-event', coverage.event(Gdk.EventType.BUTTON_RELEASE))
            if not pressed and not released:
                button.emit('clicked')
        elif args[0] in ('mousedown', 'mouseup'):
            button = ui.buttons[mouse_name[0]]
            pressed = args[0] == 'mousedown'
            button.emit('button-press-event' if pressed else 'button-release-event',
                        coverage.event(Gdk.EventType.BUTTON_PRESS if pressed else Gdk.EventType.BUTTON_RELEASE))
        elif args[0] == 'key':
            key = coverage.event(1, key=args[1], code=116)
            ui.window.emit('key-press-event', key)
            ui.window.emit('key-release-event', key)
        return ''

    namespace.update(time=SimpleNamespace(monotonic=lambda: clock[0], sleep=step),
                     child=SimpleNamespace(poll=lambda: None), queue_watch=None,
                     new_ui=True, native='owned-window', xdo=xdo)
    main = next(node for node in ast.parse((HERE / 'check-natural-gtk-input.py').read_text()).body
                if isinstance(node, ast.FunctionDef) and node.name == 'main')
    for name in ('wait', 'idle', 'action'):
        compile_nodes([next(node for node in ast.walk(main) if isinstance(node, ast.FunctionDef)
                            and node.name == name)], namespace)
    sample()
    return SimpleNamespace(vm=vm, ui=ui, bindings=bindings, session=session, sample=sample,
                           publish=publish, step=step, calls=calls, clock=clock,
                           wait=namespace['wait'], action=namespace['action'], namespace=namespace)


@pytest.mark.parametrize('mouse,prefix', [(True, 'pointer:'), (False, 'keyboard:')])
def test_actual_firstboot_action_waits_for_matching_press_and_release(route, wire, mouse, prefix):
    before = route.vm.event_id
    route.action('DOWN', mouse)
    state = route.sample()
    assert checker.input_submission(state, before, 'DOWN', mouse)
    assert not any(event.get('message','').startswith('DOWN：') for event in state['events'])
    assert wire.statuses == [(0x30, 1), (0x30, 0)]
    assert [event['words'] for event in wire.events] == [
        [0x30, 0, 1, 0, 0, 0, 0, 0], [0x30, 0, 0, 0, 0, 0, 0, 0]]
    assert all(event['queue'] == event['source'] == 0x5503e0 for event in wire.events)
    receipts = state['input_receipts']
    assert [receipt['request']['op'] for receipt in receipts] == ['press', 'release']
    assert receipts[0]['request']['source'].startswith(prefix)
    assert receipts[1]['request']['source'] == receipts[0]['request']['source']
    assert receipts[0]['id'] > before and receipts[1]['id'] > receipts[0]['id']
    assert not route.session.status()['held'] and route.clock[0] >= .2
    if mouse:
        assert ('mousemove', '--window', 'owned-window', *state['button_positions']['DOWN']) in route.calls
    assert not checker.input_submission(state, before, 'UP', mouse)
    assert not checker.input_submission(state, before, 'DOWN', not mouse)
    assert not checker.input_submission(state, receipts[-1]['id'], 'DOWN', mouse)


def test_enqueue_and_press_ack_are_insufficient_and_focus_cleanup_releases(route, wire):
    before = route.vm.event_id
    route.bindings.press('DOWN', 'pointer:1')
    assert not checker.input_submission(route.sample(), before, 'DOWN', True)
    assert not wire.events
    route.step(.1)
    assert wire.statuses == [(0x30, 1)]
    assert not checker.input_submission(route.sample(), before, 'DOWN', True)
    route.ui.window.emit('focus-out-event', coverage.event(0))
    assert route.session.status()['held']
    route.step(.1)
    assert wire.statuses == [(0x30, 1), (0x30, 0)] and not route.session.status()['held']
    assert not checker.input_submission(route.sample(), before, 'DOWN', True)


@pytest.mark.parametrize('failed_send', [1, 2])
def test_actual_serial_failure_raises_and_never_completes_action(route, wire, failed_send):
    wire.fail(failed_send)
    with pytest.raises(RuntimeError, match='机身输入未完成'):
        route.action('DOWN', True)
    assert not checker.input_submission(route.sample(), 1, 'DOWN', True)
    wire.fail(0)
    while not route.vm.commands.empty():
        route.step(.1)
    route.bindings.cleanup()
    route.step(.1)
    assert not route.session.status()['held']


def test_actual_wait_times_out_without_a_reply_and_detects_launcher_failure(route, wire):
    before = route.vm.event_id
    route.bindings.press('DOWN', 'pointer:1')
    route.vm.commands.get_nowait()  # Submitted, with no checked serial reply.
    with pytest.raises(TimeoutError, match='GTK action timed out'):
        route.wait(lambda state: checker.input_submission(state, before, 'DOWN', True), .3)
    assert not wire.events
    route.namespace['child'] = SimpleNamespace(poll=lambda: 7, returncode=7)
    with pytest.raises(RuntimeError, match='GTK launcher exited: 7'):
        route.wait(lambda _: True)


def test_mismatched_reply_cannot_publish_a_receipt(route):
    command = {'action': 'camera_input', 'op': 'tap', 'key': 'DOWN', 'source': 'activation'}
    reply = route.session.handle({**command, 'key': 'UP'})
    before = route.vm.event_id
    with pytest.raises(RuntimeError, match='mismatched command reply'):
        route.publish(command, reply)
    assert route.vm.event_id == before and not route.sample()['input_receipts']


@pytest.mark.parametrize('name', ['DOWN', 'SHUTTER'])
@pytest.mark.parametrize('change', ['wrong-key', 'wrong-id', 'old-id', 'wrong-kind', 'wrong-label',
                                  'failed-reply', 'missing-release', 'other-source', 'reversed-edges'])
def test_receipt_matching_rejects_unrelated_or_incomplete_evidence(route, change, name):
    route.action(name, True)
    state = copy.deepcopy(route.sample())
    press, release = state['input_receipts']
    event = next(event for event in state['events'] if event['id'] == release['id'])
    if change == 'wrong-key': press['request']['key'] = 'UP'
    elif change == 'wrong-id': release['id'] += 100
    elif change == 'old-id': press['id'] = 1
    elif change == 'wrong-kind': event['kind'] = 'status'
    elif change == 'wrong-label': event['message'] = 'DOWN：输入已提交'
    elif change == 'failed-reply': release['ok'] = False
    elif change == 'missing-release': state['input_receipts'].pop()
    elif change == 'other-source': release['request']['source'] = 'pointer:other'
    elif change == 'reversed-edges':
        press['id'], release['id'] = release['id'], press['id']
        for event in state['events']:
            if event['kind'] == 'input':
                event['message'] = ('press' if event['id'] == press['id'] else 'release') + '：输入已提交；消费结果以固件为准'
    assert not checker.input_submission(state, 1, name, True)


def test_natural_shutter_rejects_cycle_event_activation_and_keyboard_receipts(route):
    before = route.vm.event_id
    route.vm.event('自然快门序列已提交；消费者与拍照结果待独立证据', kind='input')
    state = route.sample()
    assert not checker.input_submission(state, before, 'SHUTTER', True)
    state['input_lifecycle'] = False
    state['events'][-1]['message'] = 'SHUTTER：输入已提交'
    assert not checker.input_submission(state, before, 'SHUTTER', True)
    route.bindings.activate('SHUTTER')
    route.step(.1)
    assert not checker.input_submission(route.sample(), before, 'SHUTTER', True)
    route.bindings.key_press('s', 39)
    route.bindings.key_release(39)
    route.step(.1)
    route.step(.1)
    state = route.sample()
    assert checker.input_submission(state, before, 'SHUTTER', False)
    assert not checker.input_submission(state, before, 'SHUTTER', True)


@pytest.mark.parametrize('name,position', [('FRONT_RIGHT', None), ('MODE_STILL', None), ('MODE', 'MR2')])
def test_tap_and_position_receipts_keep_existing_controls_and_exact_choice(route, wire, name, position):
    before = route.vm.event_id
    route.bindings.activate(name, position=position)
    assert not checker.input_submission(route.sample(), before, name, True, position)
    route.step(.1)
    state = route.sample()
    assert checker.input_submission(state, before, name, True, position)
    assert len(wire.events) == 1 and not route.session.status()['held']
    if position:
        assert not checker.input_submission(state, before, name, True, 'P')


def test_legacy_frontend_keeps_key_events_even_when_backend_supports_lifecycle(route):
    route.namespace['ui_instance'] = None
    before = route.vm.event_id
    route.namespace['original_event'](route.vm, 'DOWN：输入已提交', kind='input')
    state = route.sample()
    assert route.vm.input_lifecycle and not state['input_lifecycle']
    assert checker.input_submission(state, before, 'DOWN', True)


def test_driver_close_calls_public_window_and_preserves_actual_release_guard(route, monkeypatch, wire):
    ui, vm = route.ui, route.vm
    camera_close = type(ui)._close
    old_close = ui._close
    ui.window.disconnect_by_func(old_close)
    ui.window.connect('delete-event', lambda *_: camera_close(ui))
    ui.window.close = lambda: ui.window.emit('delete-event')
    ui.reset_dialog, ui.drag, ui.input_bindings = None, None, route.bindings
    ui.root = SimpleNamespace(set_sensitive=lambda *_: None)
    pending_workers = []
    module_globals = camera_close.__globals__
    monkeypatch.setitem(module_globals, 'threading', SimpleNamespace(Thread=lambda **kwargs:
        SimpleNamespace(start=lambda: pending_workers.append(kwargs['target']))))
    monkeypatch.setitem(module_globals, 'GLib', SimpleNamespace(idle_add=lambda *_: None))
    vm.close = mock.Mock()
    route.bindings.press('DOWN', 'pointer:close')
    route.step(.1)
    assert route.session.status()['held']
    geometry = route.namespace['geometry']
    geometry.with_suffix('.action').write_text(json.dumps({'action':'close'}))
    route.sample()
    # The real delete callback queues contact cleanup before vm.close/SD save.
    assert ui.closing and not geometry.with_suffix('.action').exists()
    assert len(pending_workers) == 1
    vm.close.assert_not_called()
    route.step(.1)
    assert not route.session.status()['held']
    assert wire.statuses == [(0x30, 1), (0x30, 0)]
    pending_workers[0]()
    vm.close.assert_called_once_with()


def test_driver_legacy_close_uses_public_vm_stop(route):
    route.namespace['ui_instance'] = None
    route.vm.stop = mock.Mock()
    route.namespace['geometry'].with_suffix('.action').write_text(json.dumps({'action':'close'}))
    route.sample()
    route.vm.stop.assert_called_once_with()
    assert route.vm.commands.empty()


def test_functional_checker_finally_requests_public_close_and_keeps_resources_on_timeout(tmp_path):
    geometry = tmp_path/'geometry.json'
    child = mock.Mock(pid=456)
    child.poll.return_value = None
    child.wait.side_effect = subprocess.TimeoutExpired('functional-ui', 240)
    with mock.patch.object(checker.os, 'killpg') as group:
        with pytest.raises(subprocess.TimeoutExpired):
            checker.close_launcher(child, geometry, True)
    group.assert_not_called()
    child.terminate.assert_not_called()
    child.kill.assert_not_called()
    assert json.loads(geometry.with_suffix('.action').read_text()) == {'action':'close'}
    tree = ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
    finalbody = next(node.finalbody for node in ast.walk(main) if isinstance(node, ast.Try) and node.finalbody
                     and isinstance(node.finalbody[0], ast.FunctionDef) and node.finalbody[0].name == 'retain_resources')
    owner = SimpleNamespace(retain=False)
    proof = {'ok':False, 'automation_completed':True}
    xvfb = mock.Mock(pid=789)
    namespace = dict(vars(checker), child=child, geometry=geometry, proof=proof, temp_owner=owner,
                     temp=tmp_path, display=':owned', xvfb=xvfb, queue_watch=None, proof_path=None,
                     env={'A7C2_FUNCTIONAL_CAMERA':checker.FUNCTIONAL_CAMERA_PROFILE})
    with mock.patch.object(checker.os, 'killpg') as group:
        with pytest.raises(RuntimeError, match='Launcher shutdown not confirmed'):
            compile_nodes(finalbody, namespace)
    assert owner.retain and not proof['automation_completed']
    assert proof['retained_vm_resources']['launcher_pid'] == child.pid
    group.assert_not_called()
    xvfb.terminate.assert_not_called()


def test_checker_functional_exit_error_is_not_accepted_and_default_profile_keeps_its_route(tmp_path):
    geometry = tmp_path/'geometry.json'
    child = mock.Mock(pid=456, returncode=7)
    child.poll.return_value = 7
    with mock.patch.object(checker.os, 'killpg') as group:
        with pytest.raises(RuntimeError, match='without confirmed orderly close'):
            checker.close_launcher(child, geometry, True)
    group.assert_not_called()
    assert not geometry.with_suffix('.action').exists()
    child.poll.return_value = None
    with mock.patch.object(checker.os, 'killpg') as group:
        checker.close_launcher(child, geometry, False)
    group.assert_called_once_with(456, checker.signal.SIGTERM)
    child.wait.assert_called_once_with(timeout=240)


def test_legacy_event_path_still_requires_fresh_exact_control_name():
    state = {'events': [{'id': 5, 'kind': 'input', 'message': 'DOWN：输入已提交'}]}
    assert checker.input_submission(state, 4, 'DOWN', True)
    assert not checker.input_submission(state, 5, 'DOWN', True)
    assert not checker.input_submission(state, 4, 'UP', True)
    state['input_lifecycle'] = True
    assert not checker.input_submission(state, 4, 'DOWN', True)
    state = {'events': [{'id': 7, 'kind': 'input', 'message': 'MODE MR2：位置输入已提交'}]}
    assert checker.input_submission(state, 6, 'MODE', True, 'MR2')
    assert not checker.input_submission(state, 6, 'MODE', True, 'P')


@pytest.fixture
def language_route(route, wire):
    """Real input receipts complete before the simulated original LCD/font publisher."""
    font='OBS RESOURCE_OPEN call=47 result=1 errno=0 path=/tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt\r\n'
    state=SimpleNamespace(step=0, polls=0, settled=True, font_step=22, font=font,
                          console='SHA2-256(/tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt)= fixture\n',
                          captures=[], stalled=False, error=None)

    def press_down():
        assert state.settled, 'another DOWN overtook the original LCD'
        route.action('DOWN', True)
        state.step+=1
        state.polls=0
        state.settled=False

    def refresh(label):
        if state.error:
            raise RuntimeError(state.error)
        state.polls+=1
        state.captures.append((state.step, state.polls, label))
        if state.step==state.font_step:
            if state.polls==4:
                state.console+='/ # '+state.font[:-5]
            elif state.polls==5:
                state.console+=state.font[-5:]
        if state.stalled or state.polls<=2:
            pixels=f'language-{state.step-1}'
        elif state.polls==3:
            pixels=f'drawing-{state.step}'
        else:
            pixels=f'language-{state.step}'
        state.settled=not state.stalled and state.polls>=5
        return {'pixel_sha256':pixels}

    state.refresh, state.press_down=refresh, press_down
    state.run=lambda:checker.select_simplified_chinese(
        {'pixel_sha256':'language-0'},lambda:state.console,refresh,press_down,route.wait)
    return state


def test_language_navigation_waits_after_real_receipts_for_changed_stable_lcd_and_split_font(language_route, wire):
    result=language_route.run()
    assert result=={'navigation_steps':24,'font_open_call':47,'selection_frame_stable':True}
    assert language_route.step==24 and language_route.settled
    assert all(sum(step==number for step, _, _ in language_route.captures)==5
               for number in range(1,25))
    assert wire.statuses==[(0x30, status) for _ in range(24) for status in (1,0)]
    assert language_route.font in language_route.console


def test_language_navigation_checks_font_after_fortieth_settled_down(language_route, wire):
    language_route.font_step=40
    result=language_route.run()
    assert result['navigation_steps']==42 and language_route.step==42 and language_route.settled
    assert wire.statuses==[(0x30, status) for _ in range(42) for status in (1,0)]


@pytest.mark.parametrize('font',[
    'OBS RESOURCE_OPEN call=47 result=1 errno=0 path=/tmp/images/MYingHeiC-Big5-SJ_wIcon.ltt\n',
    'OBS RESOURCE_OPEN call=47 result=1 errno=0 path=/usr/share/app/UniversOTS-SJ_wIcon.ltt\n',
    'OBS RESOURCE_OPEN call=47 result=1 errno=0 path=/tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt.bak\n',
    'OBS RESOURCE_OPEN call=47 result=1 errno=0 path=/tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt',
])
def test_language_navigation_rejects_other_fonts_and_incomplete_records(language_route, wire, font):
    language_route.font=font
    with pytest.raises(RuntimeError,match='font was not selected'):
        language_route.run()
    assert language_route.step==40 and language_route.settled and len(wire.statuses)==80


@pytest.mark.parametrize('result,errno',[(-1,2),(0,0),(1,5)])
def test_language_font_open_failure_remains_a_failure_without_extra_down(language_route, wire, result, errno):
    language_route.font=language_route.font.replace('result=1 errno=0',f'result={result} errno={errno}')
    with pytest.raises(RuntimeError,match='font open failed'):
        language_route.run()
    assert language_route.step==22 and len(wire.statuses)==44


def test_language_submission_without_lcd_consumption_times_out_without_retry(language_route, route, wire):
    language_route.stalled=True
    with pytest.raises(TimeoutError,match='Language DOWN 1: original LCD did not change and settle'):
        language_route.run()
    assert language_route.step==1 and wire.statuses==[(0x30,1),(0x30,0)]
    assert 45<=route.clock[0]<=46


def test_language_snapshot_failure_is_preserved_and_stops_navigation(language_route, wire):
    language_route.error='original snapshot validation failed'
    with pytest.raises(RuntimeError,match='original snapshot validation failed'):
        language_route.run()
    assert language_route.step==1 and wire.statuses==[(0x30,1),(0x30,0)]


def test_language_input_failure_does_not_refresh_or_advance(language_route, wire):
    wire.fail(1)
    with pytest.raises(RuntimeError,match='机身输入未完成'):
        language_route.run()
    assert language_route.step==0 and not language_route.captures


def test_actual_chinese_firstboot_branch_keeps_public_down_and_final_capture(language_route, route, tmp_path):
    console=tmp_path/'console.log'
    console.write_text(language_route.console)
    proof={'images':[{'pixel_sha256':'language-0'}]}

    def capture(label, expected_row):
        assert expected_row=='any'
        image=dict(language_route.refresh(label),label=label)
        console.write_text(language_route.console)
        proof['images'].append(image)
        return image

    def action(name, mouse):
        assert (name,mouse)==('DOWN',True)
        language_route.press_down()

    branch=next(node for node in ast.walk(ast.parse((HERE/'check-natural-gtk-input.py').read_text()))
                if isinstance(node,ast.If) and isinstance(node.test,ast.Compare)
                and isinstance(node.test.left,ast.Constant)
                and node.test.left.value=='--simplified-chinese')
    namespace=dict(vars(checker),sys=SimpleNamespace(argv=['--simplified-chinese']),
                   proof=proof,run=tmp_path,capture=capture,action=action,wait=route.wait)
    compile_nodes([branch],namespace)
    assert proof['language_navigation']['navigation_steps']==24
    assert proof['images'][-1]['label']=='simplified-chinese-selected'
    assert proof['images'][-1]['pixel_sha256']=='language-24'


# Original glyph-only crops, independent of saved runs, VM output directories or private assets.
# qzcokwhi: DELETE footer and shooting HUD; qqu0q5oe: visible system-error text.
GLYPH_FIXTURES = {
    # Original Arabic language title, right-aligned crop; compressed reviewed 1-bit pixels.
    'language-rtl': ((440,0,640,52),
        'eNrd0jEKwjAUBuAXHjSbuAsWvIG4uHmVFi9QcXAptCVQR69U6eDoIXoAuxlB+nyl20uKIA7iv4WPnxDyA/xlAgy+AosBMiIHpn44DBABOo31GHCj9ACMA/TQ+kBjqawDfNaKGxMJITx7iOYSNtj5IUNCxXc4sDcDzCQ0xqA6QrSSUBcjcC4uPSRLI+Ce3xiU3UmgvNPIEEvI8pQBokxCWFN40gy1AEUcrSy5cCV+oq0kAJlHh5BUjYRUtRYhrrb+0cW5Hzw/+Ab8K/kyuGv/GH45L7P/Vzc='),
    'temperature-cancel': ((170,100,460,235),
        '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'),
    'setup-on-camera': ((150,428,536,479),
        'eJzt1DGLE0EUB/A3tzJjsWbbFIv7FXLYpDjY+sAvYDfpLVJaBHeOgKXWguBXEPwArqwkgmKtKLhHDq4dsHDBsM//zIacJLNnWvGmCLuZ/THvvZl5RDfjfxyaqCQa4SmlIzGnowNAxXUHFIAiig8BRQkQAch8PVCtYLaHgLM5DfK1BFimo/D3BTNVpEfaAfF2jl9SUop5vA8UY10AswUEMCSKnoRBsgHJL9LjDjxjOwbACssguGQrDAFMuAMJ2ylmAEJJJ1xmOwBVqj2gMCCAMyOucgC4wMxA+urtgUawjQQAygqQtQ4sMJOqFXMTAHkADLi9e9IDXJVUB6YeKJQ1BhhHtc9lF6wpt1KYaEV65nNwIOVWuoqWQZDZAcAP0o83O11h4zRSxgnYFx7EANi4tqvSd7dxWmbcA56/sWnRyq+kf27BIw+MDsQEkNsT9uD19iz9FRRt/IEmr7agAZBRX0i5nQkTV3x+BT5fA9ovuX0oTFrxanM0qg4oScGQ2ge5vS/M7T9A5MsaXQNiB2gy0u8cWG7A056QOtBd0YUDnzowedEDTnvAedMT0mmxBaUD4psHqmx6VqBd8L4Dxh4IcKo9mK/DIbEDkXGN7Lj8iP6xnDpQq+RlD8AFuuMaGYCZASxyboZZLfMkeONcI6s34J6Z4R+cOjvMSppFl8zrPeCH69TI4di/3KKMhplB89+P52b8e+M3vopo0w=='),
    'still-scene-choice': ((125,0,400,130),
        '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'),
    'shooting': ((145,0,375,34),
        'eJzN07FqwzAQBmCLGzx08Fxicq/RwdBXircOgah48BavGfIw7pSxa6GFOPgFbLI4RFiReo4iuZHJ2H/9dPBznILg32QlVcoprDwoCRdMpHWhHgFP/BjypR8jGwUy+UF41IhjZBp5elwHelL48clF7NFCeBfxi8EI+1cHf+K3K3aFmTwTbh2USG3PhVojZA6CDAm/B5wbPBUMQGEr0j1hfMN2x0Avoe0GzC1scoSDRp7ufws5GGLWUNsB+3lnoewIPwfEL4PwB2cG6xplYyNPZhsbWcUajXQJsYO9wkrh7h6qDXmQzoSVFj6PMLifSZw86snv8EAu9+zp2w=='),
    # xnodlttg original LCD, crop (145,0,375,34); glyph SHA bc37def4...de31b18.
    'shooting-33m-afs': ((145,0,375,34),
        'eJzN07FuwjAQBuCcPEQsyQtU3ItU6qvwAAxkr9RIHbo1r5RMLJV4AAYcZe2QiMUIy67NYWMXsBi50Z/POtm/s+xp6kObalPI76AmXIGshsZsKmtxH7GTic4+QImgO8I9oYoRLNbV/tsu8CKBiwhRYYzFi8cS1Vt8bPHqUDS+82gR+DxCjTTtsTHXmLcyRKZzwi2huOChAcYMTrLanZDL0uO0BmYvYRIO1QXHL2S9xbranact3z3m+DnStISrGLUg3DhcemRXOPt1OAyoxxB5MfsJETiMFs9PFqEyyA2uT0noZdyZh9gFSDGB1qEJ2H/MblcSk6FOfocH6g/04O1v'),
    'system-error': ((255,155,385,200),
        'eJy90rFOwzAQBuCLLmoYkJPRiCjhEcLmIRI8ShAvELYOFbXUtWJm41XcFpUF8QyW+gIZO4Qc9jkQuiO83Sfl7vLbAP92rmIA1JDFZ1yWWgkGNZOuvCHSVcJQ/UDrqgkGgAZBoDbVLPctCoB7Gjwsl6Qd1ACHE5jHsBkhfNIJeM+5h+WmkS2idQDDgHoRrVUzQZp2mKvWwSZASRaPrQdDPCUlg8dGTSBSjZ1VKZFRYY8ig+td70GGMBYKHqj3PzdCV8MdDROgLcDKD4aS/B66ACNfPdALhYAiI8056oaekwCrfgSJftMBdyNIBhDR6qhOIEM9Ak9BoQCq3/DkQq22Hi4YEuFib988XHIPIVLIG4aSIReJ7u3eQ8FQC9x9mr0LyAaYD9HhYAaXh625advDFvWjhzD2tnd3A24XaDKZ/PFL/D5fJbuhEg=='),
}


def glyph_frame(name):
    from PIL import Image
    box,encoded=GLYPH_FIXTURES[name]
    glyphs=Image.frombytes('1',(box[2]-box[0],box[3]-box[1]),zlib.decompress(base64.b64decode(encoded)))
    image=Image.new('RGB',(640,480),'black')
    image.paste(glyphs.convert('RGB'),box)
    return image


def screen_log(*screens):
    return ''.join(f'OBS CREATE_SCREEN_ARGS call={number} id={hex(screen)} count={count} orientation=0\n'
                   for number,(screen,count) in enumerate(screens,1))


SHOOTING_CHAIN=((0x347,28),(0x343,0),(0x1e6,5),(0x343,0),(0,565))


def test_rtl_language_crop_is_normalized_without_relaxing_current_screen():
    image=glyph_frame('language-rtl')
    result=checker.firstboot_frame(image,screen_log((0x12d,6)))
    assert result['page']=='language' and result['content_page']=='language'
    assert checker.firstboot_frame(image,screen_log((0x999,6)))['page']=='pending'


@pytest.mark.parametrize('fixture', ['shooting', 'shooting-33m-afs'])
def test_shooting_requires_current_original_content_and_closed_tutorial_not_factory_history(fixture):
    from PIL import Image
    hud=glyph_frame(fixture)
    assert checker.firstboot_frame(hud,screen_log(*SHOOTING_CHAIN))['page']=='shooting'
    for screens in (((0x343,0),),SHOOTING_CHAIN[:-1],SHOOTING_CHAIN+((0x29b,4),),
                    SHOOTING_CHAIN+((0x431,10),),((0x347,28),(0x343,0),(0,565)),
                    SHOOTING_CHAIN[:-1]+((0,564),)):
        assert checker.firstboot_frame(hud,screen_log(*screens))['page']=='pending'
    # Even the full historical creation chain cannot make a modal/blank LCD a shooting HUD.
    assert checker.firstboot_frame(Image.new('RGB',(640,480)),screen_log(*SHOOTING_CHAIN))['page']=='pending'
    changed=hud.copy();changed.putpixel((160,10),(255,255,255) if hud.getpixel((160,10))==(0,0,0) else (0,0,0))
    assert checker.firstboot_frame(changed,screen_log(*SHOOTING_CHAIN))['page']=='pending'


def test_scene_choice_requires_reviewed_selected_glyph_and_current_screen_count():
    from PIL import Image
    scene=glyph_frame('still-scene-choice')
    assert checker.firstboot_frame(scene,screen_log((0xd4,98)))['page']=='still-scene-choice'
    for screens in (((0xd4,97),),((0xd4,99),),((0x343,98),),SHOOTING_CHAIN,
                    ((0xd4,98),(0x29b,4))):
        assert checker.firstboot_frame(scene,screen_log(*screens))['page']=='pending'
    assert checker.firstboot_frame(Image.new('RGB',(640,480)),screen_log((0xd4,98)))['page']=='pending'
    scene.putpixel((130,10),(255,255,255) if scene.getpixel((130,10))==(0,0,0) else (0,0,0))
    assert checker.firstboot_frame(scene,screen_log((0xd4,98)))['page']=='pending'


@pytest.mark.parametrize('result_page', ['shooting','unknown','missing-enter-release','wrong-count'])
def test_reenter_scene_uses_original_enter_edges_then_requires_shooting_before_full_press(tmp_path,result_page):
    state={'image':glyph_frame('still-scene-choice'),'console':screen_log(*SHOOTING_CHAIN,(0xd4,97 if result_page=='wrong-count' else 98))}
    actions=[];clock=[0.0]
    def frame(label):
        image=state['image']
        return dict(label=label,image='frame.png',pixel_sha256=hashlib.sha256(image.tobytes()).hexdigest(),
                    firstboot_ui=checker.firstboot_frame(image,state['console']))
    proof={'images':[frame('scene')],'reenter_still_mode':{}}
    def capture(label,expected_row):
        assert expected_row=='any'
        (tmp_path/'console.log').write_text(state['console'])
        value=frame(label);proof['images'].append(value);return value
    def wait(predicate):
        for _ in range(12):
            if predicate({}):return
        raise TimeoutError('fixture original page did not settle')
    def action(name,mouse):
        actions.append((name,mouse))
        if name=='ENTER':
            assert mouse is True
            state['console']+='OBS INPUT_EVENT32 n=11 tid=384 words=[0x1ac,0,1,0,0,0,0,0]\n'
            if result_page!='missing-enter-release':
                state['console']+='OBS INPUT_EVENT32 n=12 tid=384 words=[0x1ac,0,0,0,0,0,0,0]\n'
            state['console']+=screen_log(*SHOOTING_CHAIN)
            state['image']=glyph_frame('shooting') if result_page!='unknown' else glyph_frame('setup-on-camera')
        else:
            assert (name,mouse)==('SHUTTER',True)
    branch=next(n for n in ast.walk(ast.parse((HERE/'check-natural-gtk-input.py').read_text()))
        if isinstance(n,ast.If) and isinstance(n.test,ast.Compare) and isinstance(n.test.left,ast.Constant)
        and n.test.left.value=='--natural-shutter')
    namespace=dict(vars(checker),sys=SimpleNamespace(argv=['--natural-shutter','--reenter-still-mode']),
        proof=proof,run=tmp_path,proof_path=tmp_path/'proof.json',capture=capture,action=action,wait=wait,
        idle=lambda:None,time=SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n)))
    if result_page=='shooting':
        compile_nodes([branch],namespace)
        assert actions==[('ENTER',True),('SHUTTER',True)]
        step=proof['reenter_still_mode']['scene_choice']
        assert step['page']['page']=='still-scene-choice' and step['actions'][0]['original_input_edges']==[11,12]
        assert step['ready'] is step['capture_verified'] is False
        assert proof['natural_shutter']['still_capture_verified'] is False
    else:
        with pytest.raises(TimeoutError):compile_nodes([branch],namespace)
        assert actions==([] if result_page=='wrong-count' else [('ENTER',True)])
        assert 'natural_shutter' not in proof


def test_actual_temperature_confirmation_is_cancelable_but_0x343_is_never_ready():
    modal=glyph_frame('temperature-cancel')
    assert checker.firstboot_frame(modal,screen_log((0x431,10)))['page']=='temperature-cancel'
    for console in (screen_log((0x343,0)),screen_log(*SHOOTING_CHAIN),
                    screen_log(*SHOOTING_CHAIN,(0x343,0))):
        classified=checker.firstboot_frame(modal,console)
        assert classified['page']=='pending' and classified['content_page']=='temperature-cancel'


def test_delete_footer_is_content_bound_to_original_startup_candidate():
    phone=glyph_frame('setup-on-camera')
    assert checker.firstboot_frame(phone,screen_log((0x1dd,9)))['page']=='setup-on-camera'
    assert checker.firstboot_frame(phone,screen_log((0x21e,12)))['page']=='setup-on-camera'
    assert checker.firstboot_frame(phone,screen_log((0x343,0)))['page']=='pending'
    assert checker.firstboot_frame(phone,screen_log(*SHOOTING_CHAIN))['page']=='pending'


def test_original_system_error_is_failed_even_with_old_shooting_or_stale_modal_lcd():
    from PIL import Image
    error=glyph_frame('system-error')
    assert checker.firstboot_frame(error,screen_log(*SHOOTING_CHAIN))['page']=='failed'
    assert checker.firstboot_frame(error,screen_log(*SHOOTING_CHAIN,(0x30c,3)))['page']=='failed'
    assert checker.firstboot_frame(Image.new('RGB',(640,480)),screen_log(*SHOOTING_CHAIN,(0x30c,3)))['page']=='failed'
    assert checker.firstboot_frame(error,screen_log((0x309,0)))['page']=='failed'


@pytest.fixture
def firstboot_route(route, wire, tmp_path):
    """Real GTK/VM/InputEvent32 encoder, with independently delayed original receive and LCD."""
    from PIL import Image,ImageDraw
    state=SimpleNamespace(pages=['language','reader','privacy','setup-on-camera','area-prompt','area',
                                'date-format','date-time','temperature-prompt','temperature-cancel',
                                'creators-guide','touch-guide','shooting'],
                          index=0,selection='lower',pending=None,polls=0,console='',stalled=False,
                          no_receive=False,actions=[],captures=[],path=tmp_path/'firstboot-lcd.png')

    def refresh(label):
        if state.pending:
            state.polls+=1
            name,edges=state.pending
            if state.polls==3 and not state.no_receive:
                for number,edge in edges:
                    state.console+=f'OBS INPUT_EVENT32 n={number} tid=344 words=['+','.join(hex(n) for n in edge['words'])+']\n'
            if state.polls>=5 and not state.stalled:
                if name=='DOWN':state.selection='lower'
                else:state.index+=1
                state.pending=None
        page=state.pages[state.index]
        image=Image.new('RGB',(640,480),'black')
        image.putpixel((5,5),(state.index+1,0,0))
        if page in ('reader','temperature-prompt','temperature-cancel'):
            ImageDraw.Draw(image).rectangle((30,14,609,411),outline=(68,68,68))
            image.paste((180,64,0),(200,340,440,395) if state.selection=='lower' else (200,275,440,330))
        image.save(state.path)
        ui={'page':page,'screen_call':state.index+1,'reason':'original test page'}
        result={'pixel_sha256':hashlib.sha256(image.tobytes()).hexdigest(),'firstboot_ui':ui}
        state.captures.append((state.index,state.polls,label))
        return result

    def action(name,mouse):
        assert state.pending is None, 'another input overtook the original LCD'
        before=len(wire.events)
        route.action(name,mouse)
        state.actions.append((state.pages[state.index],name))
        state.pending=(name,list(enumerate(wire.events[before:],before+1)))
        state.polls=0

    state.refresh=refresh
    state.run=lambda:checker.firstboot_step(refresh('initial'),lambda:state.console,refresh,action,
                                             route.wait,lambda:state.path,'setup')
    return state


def test_firstboot_serializes_pending_enters_reader_delete_date_and_temperature_cancel(firstboot_route, wire):
    state=firstboot_route;results=[]
    for _ in state.pages:
        results.append(state.run())
    assert results[-1]['ready'] and all(not result['ready'] for result in results[:-1])
    assert [name for _,name in state.actions]==['ENTER']*3+['DELETE']+['ENTER']*8
    assert state.actions[3]==('setup-on-camera','DELETE')
    assert state.actions[9]==('temperature-cancel','ENTER')
    assert all(result['capture_verified'] is False for result in results)
    assert all(action['original_input_edges'] and action['lcd_changed_and_stable']
               for result in results[:-1] for action in result['actions'])
    assert all(result['selection']['highlight_verified'] for result in results[:-1]
               if result['page']['page'] in ('reader','temperature-prompt','temperature-cancel'))
    assert not any(code in (0x1f1,0xa7) for code,_ in wire.statuses)
    assert all(sum(index==number and polls>=5 for index,polls,_ in state.captures)>=2
               for number in range(1,len(state.pages)))


def test_temperature_and_reader_upper_selection_wait_for_consumed_down_once(firstboot_route, wire):
    state=firstboot_route
    state.pages=['reader','temperature-prompt','temperature-cancel','shooting'];state.selection='upper'
    results=[state.run() for _ in state.pages]
    assert state.actions==[('reader','DOWN'),('reader','ENTER'),('temperature-prompt','ENTER'),
                           ('temperature-cancel','ENTER')]
    assert results[0]['selection']['down_sent'] and results[-1]['ready']
    assert wire.statuses[:2]==[(0x30,1),(0x30,0)]
    assert sum(code==0x30 for code,_ in wire.statuses)==2


@pytest.mark.parametrize('page',['reader','temperature-prompt','temperature-cancel'])
def test_each_lower_choice_waits_for_original_down_before_enter(firstboot_route, wire, page):
    state=firstboot_route;state.pages=[page,'shooting'];state.selection='upper'
    result=state.run()
    assert state.actions==[(page,'DOWN'),(page,'ENTER')]
    assert result['selection']['down_sent'] and not result['ready']
    assert wire.statuses==[(0x30,1),(0x30,0),(0x1ac,1),(0x1ac,0)]


@pytest.mark.parametrize('failure',['lcd-stalled','receive-missing'])
def test_firstboot_cannot_queue_a_second_enter_on_same_lcd_or_host_ack_only(firstboot_route, wire, failure):
    state=firstboot_route
    state.stalled=failure=='lcd-stalled';state.no_receive=failure=='receive-missing'
    with pytest.raises(TimeoutError,match='setup-enter'):
        for _ in range(2):state.run()
    assert state.actions==[('language','ENTER')]
    assert wire.statuses==[(0x1ac,1),(0x1ac,0)]


def test_unknown_modal_never_receives_enter_and_never_becomes_ready(firstboot_route, wire):
    state=firstboot_route;state.pages=['pending']
    with pytest.raises(TimeoutError,match='setup-page'):
        state.run()
    assert not state.actions and not wire.statuses


@pytest.fixture
def natural_shutter_route(route, tmp_path):
    branch = next(node for node in ast.walk(ast.parse((HERE/'check-natural-gtk-input.py').read_text()))
                  if isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                  and isinstance(node.test.left, ast.Constant)
                  and node.test.left.value == '--natural-shutter' and len(node.body) > 5)
    frame = {'pixel_sha256':'shooting', 'firstboot_ui':checker.firstboot_frame(
        glyph_frame('shooting'), screen_log(*SHOOTING_CHAIN))}
    proof = {'ok':False, 'capture_verified':False, 'images':[frame]}
    namespace = dict(route.namespace, proof=proof, proof_path=tmp_path/'proof.json',
                     capture=lambda *_:frame, sys=SimpleNamespace(argv=['--natural-shutter']))
    return SimpleNamespace(proof=proof, run=lambda:compile_nodes([branch], namespace))


def test_natural_shutter_uses_button_pointer_hold_release_and_checked_same_source_receipts(
        natural_shutter_route, route, wire, monkeypatch):
    original_xdo = route.namespace['xdo']
    edges = []

    def xdo(*args):
        if args[0] in ('mousedown', 'mouseup'):
            assert 'natural_shutter' not in natural_shutter_route.proof
            edges.append((args[0], route.clock[0]))
        return original_xdo(*args)

    monkeypatch.setitem(route.namespace, 'xdo', xdo)
    natural_shutter_route.run()
    state = route.sample()
    assert route.calls == [('windowraise', 'owned-window'),
                           ('windowfocus', '--sync', 'owned-window'),
                           ('mousemove', '--window', 'owned-window', *state['button_positions']['SHUTTER']),
                           ('mousedown', 1), ('mouseup', 1)]
    assert [name for name, _ in edges] == ['mousedown', 'mouseup']
    assert edges[1][1] - edges[0][1] == pytest.approx(.1)
    press, release = state['input_receipts']
    assert press['request']['key'] == 'SHUTTER' and press['request']['op'] == 'press'
    assert press['ok'] is release['ok'] is True and press['id'] < release['id']
    source = press['request']['source']
    assert source.startswith('pointer:') and release['request'] == {
        'action':'camera_input', 'op':'release', 'source':source}
    assert wire.statuses == [(0x1f1,1), (0xa7,1), (0xa7,0), (0x1f1,0)]
    assert all(event['queue'] == event['source'] == 0x5503e0 and event['bytes'] == 32 for event in wire.events)
    assert not route.session.status()['held'] and not route.bindings.sources
    assert natural_shutter_route.proof['natural_shutter'] == {
        'input_submission_event_verified':True, 'gesture_source':'GTK SHUTTER pointer press/hold/release',
        'consumer_verified':False, 'still_capture_verified':False}
    assert natural_shutter_route.proof['capture_verified'] is False
    assert not route.namespace['geometry'].with_suffix('.action').exists()


def test_shutter_pointer_waits_for_existing_busy_and_pending_input_before_mousedown(route, wire, monkeypatch):
    route.bindings.press('DOWN', 'pointer:earlier')
    route.bindings.release('pointer:earlier')
    route.vm.busy = 'snapshot'
    route.sample()
    original_xdo = route.namespace['xdo']

    def xdo(*args):
        assert not route.vm.busy and not route.vm.status()['pending']
        return original_xdo(*args)

    monkeypatch.setitem(route.namespace, 'xdo', xdo)
    route.action('SHUTTER', True)
    assert wire.statuses == [(0x30,1), (0x30,0), (0x1f1,1), (0xa7,1), (0xa7,0), (0x1f1,0)]


@pytest.mark.parametrize('failure', ['mousedown', 'hold-timeout', 'receipt-timeout'])
def test_natural_shutter_pointer_failures_release_without_promoting_proof(
        natural_shutter_route, route, wire, monkeypatch, failure):
    original_xdo = route.namespace['xdo']

    def xdo(*args):
        result = original_xdo(*args)
        if failure == 'mousedown' and args[0] == 'mousedown':
            raise subprocess.CalledProcessError(1, ['xdotool', 'mousedown', '1'])
        return result

    def sleep(seconds):
        route.step(seconds)
        if ('mousedown', 1) in route.calls and ('mouseup', 1) not in route.calls:
            raise TimeoutError('pointer hold interrupted')

    monkeypatch.setitem(route.namespace, 'xdo', xdo)
    if failure == 'hold-timeout':
        monkeypatch.setattr(route.namespace['time'], 'sleep', sleep)
    elif failure == 'receipt-timeout':
        monkeypatch.setattr(type(route.vm), 'event', route.namespace['original_event'])
    with pytest.raises(subprocess.CalledProcessError if failure == 'mousedown' else TimeoutError):
        natural_shutter_route.run()
    assert [call for call in route.calls if call[0] in ('mousedown', 'mouseup')] == [
        ('mousedown', 1), ('mouseup', 1)]
    while not route.vm.commands.empty():
        route.step(.1)
    assert not route.session.status()['held'] and not route.bindings.sources
    assert 'natural_shutter' not in natural_shutter_route.proof
    assert natural_shutter_route.proof['ok'] is natural_shutter_route.proof['capture_verified'] is False
    assert not route.namespace['geometry'].with_suffix('.action').exists()


@pytest.mark.parametrize('failed_send', [1, 2, 3, 4])
def test_natural_shutter_failed_contact_receipt_cannot_verify_pointer_or_capture(
        natural_shutter_route, route, wire, failed_send):
    wire.fail(failed_send)
    with pytest.raises(RuntimeError, match='机身输入未完成'):
        natural_shutter_route.run()
    assert route.calls.count(('mousedown', 1)) == route.calls.count(('mouseup', 1)) == 1
    assert 'natural_shutter' not in natural_shutter_route.proof
    assert natural_shutter_route.proof['ok'] is natural_shutter_route.proof['capture_verified'] is False
    wire.fail(0)
    while not route.vm.commands.empty():
        route.step(.1)
    route.bindings.cleanup()
    route.step(.1)
    assert not route.session.status()['held']


def test_current_system_error_stops_actual_natural_shutter_branch_before_mailbox(route, tmp_path):
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    branch=next(node for node in ast.walk(tree) if isinstance(node,ast.If)
                and isinstance(node.test,ast.Compare) and isinstance(node.test.left,ast.Constant)
                and node.test.left.value=='--natural-shutter' and len(node.body)>5)
    failed={'pixel_sha256':'error','firstboot_ui':checker.firstboot_frame(
        glyph_frame('system-error'),screen_log(*SHOOTING_CHAIN,(0x30c,3)))}
    proof={'ok':False,'capture_verified':False,'images':[failed]}
    action = mock.Mock(side_effect=AssertionError('system error must block pointer input'))
    namespace=dict(vars(checker),proof=proof,geometry=tmp_path/'geometry.json',wait=route.wait,
                   capture=lambda *_:failed,action=action,
                   sys=SimpleNamespace(argv=['--natural-shutter']),run=tmp_path)
    with pytest.raises(RuntimeError,match='Original UI failed'):
        compile_nodes([branch],namespace)
    action.assert_not_called()
    assert not route.calls and not namespace['geometry'].with_suffix('.action').exists()
    assert 'natural_shutter' not in proof and proof['ok'] is proof['capture_verified'] is False


@pytest.mark.parametrize('kind',['temperature-modal','system-error'])
def test_actual_firstboot_loop_stops_without_candidate_or_shutter_on_pending_or_failed_ui(route, tmp_path, capsys, kind):
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    loop=next(node for node in ast.walk(tree) if isinstance(node,ast.For)
              and isinstance(node.iter,ast.Call) and isinstance(node.iter.func,ast.Name)
              and node.iter.func.id=='range' and [getattr(arg,'value',None) for arg in node.iter.args]==[1,31])
    console=screen_log(*SHOOTING_CHAIN)
    content=glyph_frame('temperature-cancel' if kind=='temperature-modal' else 'system-error')
    frame={'pixel_sha256':hashlib.sha256(content.tobytes()).hexdigest(),
           'firstboot_ui':checker.firstboot_frame(content,console),'image':'unused.png'}
    (tmp_path/'console.log').write_text(console)
    actions=[]
    proof={'ok':False,'capture_verified':False,'shooting_screen_created':False,'images':[frame],
           'firstboot_readiness':{'ready':False}}
    namespace=dict(vars(checker),proof=proof,run=tmp_path,proof_path=tmp_path/'proof.json',
                   wait=route.wait,capture=lambda *_:frame,action=lambda *args:actions.append(args))
    with pytest.raises((TimeoutError,RuntimeError)):
        compile_nodes([loop],namespace)
    assert not actions and not proof['firstboot_readiness']['ready']
    assert proof['ok'] is proof['shooting_screen_created'] is proof['capture_verified'] is False
    assert 'natural_shutter' not in proof and 'CANDIDATE' not in capsys.readouterr().out


def test_original_receive_requires_complete_fresh_ordered_inputevent32_edges():
    press='OBS INPUT_EVENT32 n=51 tid=344 words=[0x1ac,0,0x1,0,0,0,0,0]\n'
    release='OBS INPUT_EVENT32 n=52 tid=344 words=[0x1ac,0,0,0,0,0,0,0]\n'
    assert checker.original_input_edges(press+release,'ENTER')==[51,52]
    for text in (press,release+press,press+release.rstrip(),press+release.replace('n=52','n=50'),
                 (press+release).replace('0x1ac','0x30'),(press+release).replace('0x1ac','broken')):
        assert checker.original_input_edges(text,'ENTER')==[]


def movie_after_shutter_branch():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    return next(node for node in ast.walk(tree) if isinstance(node,ast.If)
                and isinstance(node.test,ast.Compare) and isinstance(node.test.left,ast.Constant)
                and node.test.left.value=='--natural-movie-after-shutter' and len(node.body)>2)


def test_movie_after_shutter_requires_the_isolated_natural_shutter_flow():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    guard=next(node for node in ast.walk(tree) if isinstance(node,ast.If)
               and isinstance(node.test,ast.BoolOp)
               and any(isinstance(item,ast.Constant) and item.value=='--natural-movie-after-shutter'
                       for item in ast.walk(node.test)))
    for argv in ([],['--natural-shutter'],['--natural-shutter','--natural-movie-after-shutter']):
        compile_nodes([guard],dict(sys=SimpleNamespace(argv=argv)))
    with pytest.raises(ValueError,match='requires --natural-shutter'):
        compile_nodes([guard],dict(sys=SimpleNamespace(argv=['--natural-movie-after-shutter'])))


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_movie_sequence_uses_original_selector_and_checked_rec_contacts(route,wire,tmp_path,enabled):
    proof={'ok':False,'capture_verified':False}
    captures=[]
    namespace=dict(route.namespace,proof=proof,proof_path=tmp_path/'proof.json',
                   capture=lambda label,*_:captures.append(label),
                   sys=SimpleNamespace(argv=['--natural-movie-after-shutter'] if enabled else []))
    compile_nodes([movie_after_shutter_branch()],namespace)
    if not enabled:
        assert not wire.events and not captures and 'natural_movie' not in proof
        return
    assert wire.statuses==[(0x71c9,2),(0x1f0,1),(0x1f0,0),(0x1f0,1),(0x1f0,0)]
    assert captures==['natural-movie-mode','natural-movie-rec-first','natural-movie-rec-second']
    assert route.clock[0]>=20 and not route.session.status()['held']
    movie=proof['natural_movie']
    assert movie=={'input_sequence_completed':True,'mode_input_submission_event_verified':True,
                  'rec_input_submissions':2,'recording_started_verified':False,
                  'recording_stopped_verified':False,'movie_saved_verified':False}
    assert json.loads(namespace['proof_path'].read_text())==proof
    assert proof['ok'] is proof['capture_verified'] is False


@pytest.mark.parametrize('failed_send',[1,2,3,4,5])
def test_actual_movie_contact_failure_preserves_partial_proof_without_later_gestures(route,wire,tmp_path,failed_send):
    wire.fail(failed_send)
    proof={'ok':False,'capture_verified':False}
    captures=[]
    namespace=dict(route.namespace,proof=proof,proof_path=tmp_path/'proof.json',
                   capture=lambda label,*_:captures.append(label),
                   sys=SimpleNamespace(argv=['--natural-movie-after-shutter']))
    with pytest.raises(RuntimeError,match='机身输入未完成'):
        compile_nodes([movie_after_shutter_branch()],namespace)
    movie=proof['natural_movie']
    assert not movie['input_sequence_completed']
    assert movie['mode_input_submission_event_verified']==(failed_send>1)
    assert movie['rec_input_submissions']==(1 if failed_send>3 else 0)
    assert len(captures)==(0 if failed_send==1 else 1 if failed_send<4 else 2)
    assert not movie['recording_started_verified'] and not movie['recording_stopped_verified']
    assert not movie['movie_saved_verified'] and not proof['capture_verified'] and not proof['ok']
    assert json.loads(namespace['proof_path'].read_text())==proof
    wire.fail(0)
    while not route.vm.commands.empty():route.step(.1)
    route.bindings.cleanup()
    route.step(.1)
    assert not route.session.status()['held']


def test_movie_frame_failure_stops_before_second_rec_submission(route,wire,tmp_path):
    proof={'ok':False,'capture_verified':False}
    def capture(label,*_):
        if label=='natural-movie-rec-first':raise RuntimeError('original frame failed')
    namespace=dict(route.namespace,proof=proof,proof_path=tmp_path/'proof.json',capture=capture,
                   sys=SimpleNamespace(argv=['--natural-movie-after-shutter']))
    with pytest.raises(RuntimeError,match='original frame failed'):
        compile_nodes([movie_after_shutter_branch()],namespace)
    assert wire.statuses==[(0x71c9,2),(0x1f0,1),(0x1f0,0)]
    assert proof['natural_movie']['rec_input_submissions']==1
    assert not proof['natural_movie']['input_sequence_completed']
    assert not proof['natural_movie']['movie_saved_verified'] and not proof['capture_verified']
