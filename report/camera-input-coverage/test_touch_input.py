"""Host lifecycle tests; actual original AP consumption has its own receipt."""
import sys
import subprocess
from types import SimpleNamespace
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'runtime/analysis'))
sys.path.insert(0, str(HERE))
from input_bindings import InputBindings, InputSession, is_release, validate_request


def touch(phase, x=123, y=234, source='lcd:1'):
    return dict(action='camera_input', op='touch', phase=phase, x=x, y=y, source=source)


def test_original_touch_wire_coordinates_and_phases():
    import menu_live
    assert menu_live.touch_command('begin', 123, 234) == '/simulation/inject-key --app 0x005503e0 0x005503e0 0x270 8061162 1 0 0'
    assert menu_live.touch_command('move', 639, 479).endswith(f'0x270 {(639 << 16) | 479} 2 0 0')
    assert menu_live.touch_command('end', 0, 0).endswith('0x270 0 0 0 0')
    for args in (('tap', 1, 2), ('begin', True, 2), ('end', 640, 2), ('move', 0, -1)):
        with pytest.raises(ValueError):
            menu_live.touch_command(*args)


def test_production_persistent_sender_accepts_original_touch_fields(tmp_path):
    import menu_live
    from persistent_app_input import PersistentAppInput
    script = r'''
import re,sys
marker=re.search(r'APP_INPUT_SHELL_[a-f0-9]+',sys.stdin.readline()).group()
print('APP_INPUT_SERVER_READY',flush=True)
for line in sys.stdin:
 fields=line.split()
 if fields[0]=='STOP':
  print(marker+':0',flush=True);break
 sequence,code,packed,phase,finger,origin=map(int,fields)
 assert code==0x270 and packed==(123<<16)|234 and finger==origin==0
 print('TOUCH_WIRE phase=%d x=%d y=%d'%(phase,packed>>16,packed&65535),flush=True)
 print('APP_INPUT_RESULT %d 0'%sequence,flush=True)
'''
    console=tmp_path/'console.log'
    with console.open('wb') as output:
        proc=subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=output,stderr=output)
        sender=PersistentAppInput(proc,console,SimpleNamespace(check=lambda:None))
        try:
            for name,phase in (('begin',1),('move',2),('end',0)):
                reply=sender(menu_live.touch_command(name,123,234))
                assert f'TOUCH_WIRE phase={phase} x=123 y=234'.encode() in reply
            sender.pause()
            assert not sender.active and not getattr(proc,'_menu_serial_desynchronized',False)
        finally:
            proc.stdin.close();proc.wait(timeout=10)
        assert proc.returncode==0


@pytest.fixture
def session(monkeypatch):
    import menu_live
    monkeypatch.setattr(menu_live, 'touch_command', lambda phase, x, y: f'{phase} {x} {y}', raising=False)
    calls = []
    def send(command):
        calls.append(command)
        return b'checked return code'
    return InputSession(send, app_input=True), calls


def test_single_owner_moves_and_end(session):
    owner, calls = session
    assert owner.handle(touch('begin'))['ok']
    assert owner.status()['touch'] == dict(source='lcd:1', x=123, y=234, uncertain=False)
    assert not owner.handle(touch('begin', source='lcd:2'))['ok']
    assert not owner.handle(touch('end', source='lcd:2'))['ok']
    assert owner.handle(touch('move', 0, 479))['ok']
    assert owner.handle(touch('end', 639, 0))['ok']
    assert 'touch' not in owner.status()
    assert calls == ['begin 123 234', 'move 0 479', 'end 639 0']


def test_touch_end_preserves_independent_held_camera_key(session):
    owner, calls = session
    assert owner.handle(dict(action='camera_input', op='press', key='SHUTTER_HALF', source='key'))['ok']
    assert owner.handle(touch('begin'))['ok']
    assert owner.handle(touch('end'))['ok']
    assert owner.status()['held'][0]['key'] == 'SHUTTER_HALF'
    assert 'touch' not in owner.status()


def test_failed_begin_retains_contact_and_cleanup_is_real(session):
    owner, calls = session
    def fail(command):
        calls.append(command)
        raise RuntimeError('sender failed')
    owner.input_fn = fail
    result = owner.handle(touch('begin'))
    assert not result['ok'] and result['input_state']['touch']['uncertain']
    assert not owner.handle(touch('move'))['ok']
    assert not owner.handle(dict(action='camera_input', op='tap', key='MENU', source='key'))['ok']
    result = owner.handle(dict(action='camera_input', op='cleanup'))
    assert not result['ok'] and result['input_state']['touch']['uncertain']
    owner.input_fn = lambda command: calls.append(command) or b'checked release'
    result = owner.handle(dict(action='camera_input', op='cleanup'))
    assert result['ok'] and 'touch' not in result['input_state']
    assert calls == ['begin 123 234', 'end 123 234', 'end 123 234']


def test_infra_route_refuses_touch():
    calls = []
    owner = InputSession(lambda command: calls.append(command) or b'ok', app_input=False)
    assert not owner.handle(touch('begin'))['ok'] and not calls


@pytest.mark.parametrize('changes', [dict(phase='tap'), dict(x=-1), dict(x=640), dict(y=480),
                                    dict(x=True), dict(y=1.5), dict(source=''), dict(extra=1)])
def test_bad_touch_never_admitted(changes):
    with pytest.raises(ValueError):
        validate_request({**touch('begin'), **changes})


def test_controller_requires_ready_touch_route_and_accepts_faulted_release():
    from menu_control import VM
    vm = VM(command=['host-test-only'])
    vm.mock = False
    vm.state = 'running'
    vm.input_lifecycle = True
    with pytest.raises(ValueError, match='触屏'):
        vm.enqueue(touch('begin'))
    vm.touch_input = True
    vm.enqueue(touch('begin'))
    assert vm.commands.get_nowait() == touch('begin')
    vm.state = 'faulted'
    vm.sd_pending = 1
    vm.enqueue(touch('end'))
    assert vm.commands.get_nowait() == touch('end')
    with pytest.raises(ValueError):
        vm.enqueue(touch('move'))


def test_release_admission_and_local_owner_survive_queue_failure():
    assert is_release(touch('end')) and not is_release(touch('begin'))
    assert is_release(dict(action='camera_input', op='cleanup'))
    calls = []
    bindings = InputBindings(calls.append)
    assert bindings.touch('begin', 1, 2, 'mouse')
    assert not bindings.touch('begin', 3, 4, 'finger')
    assert not bindings.touch('move', 1, 2, 'mouse')
    assert bindings.touch('move', 4, 5, 'mouse')
    def fail(_):
        raise ValueError('queue full')
    bindings.enqueue = fail
    with pytest.raises(ValueError):
        bindings.touch('end', 4, 5, 'mouse')
    assert bindings.touch_source == 'mouse'
    bindings.enqueue = calls.append
    assert bindings.cleanup() and bindings.touch_source is None
    assert calls == [touch('begin', 1, 2, 'mouse'), touch('move', 4, 5, 'mouse'),
                     dict(action='camera_input', op='cleanup')]
