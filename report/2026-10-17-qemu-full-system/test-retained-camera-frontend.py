"""Source/host transport contracts with synthetic PPM and fake owners; NO VM/GUI evidence."""
import copy
import io
import os
from pathlib import Path
import runpy
import threading
import time
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'retained-camera-live.py'))
F = runpy.run_path(str(HERE / 'retained-camera-frontend.py'))
RUN = runpy.run_path(str(HERE / 'run-retained-camera.py'))
DEV, R = API['DEV'], API['R']
PPM = b'P6\n640 480\n255\n' + bytes((1, 2, 3)) * (640 * 480)
OTHER_PPM = b'P6\n640 480\n255\n' + bytes((4, 5, 6)) * (640 * 480)


def edge(code, status):
    return f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {status:#x} 0 1'


def pulse(code=0x1ac):
    return edge(code, 1) + '; pressed=$?; sleep 0.05; ' + edge(code, 0) + '; released=$?; test "$pressed" = 0 && test "$released" = 0\n'


def shutter():
    return ''.join(edge(code, status) + f'; step{i}=$?; sleep 0.05; ' for i, (code, status) in enumerate(
        ((0x1f1, 1), (0xa7, 1), (0xa7, 0), (0x1f1, 0)))) + 'test "$step0" = 0 && test "$step1" = 0 && test "$step2" = 0 && test "$step3" = 0\n'


class Owner:
    def __init__(self, pid):
        self.pid, self.returncode, self.stdin = pid, None, io.BytesIO()

    def poll(self):
        return self.returncode


class Session:
    def __init__(self, output, events):
        self.output, self.events = output, events
        self.output.mkdir(mode=0o700)
        self.instance = dict(id='host-only-frontend', generation=0)
        self.owner = Owner(101)
        self.used = self.closed = False
        self.content = None
        directory = self.output / 'source'
        directory.mkdir(mode=0o700)
        self.log = directory / 'console.log'
        self.log.write_bytes(b'host fixture, no VM\n')
        self.launch = dict(dtb=str(directory / 'virt.dtb'))
        self.tx = SimpleNamespace(_output=output / 'transaction', children=[self.owner])
        self.tx._output.mkdir(mode=0o700)
        self.qmp = self.qmp_for('source', directory)
        self.execution = SimpleNamespace(target=None, target_qmp=None, continued=False, failed=False)

    def qmp_for(self, side, directory):
        def qmp(command, args=None):
            self.events.append(('qmp', side, command, args, threading.get_ident()))
            if command == 'query-status':
                return dict(running=True, status='running')
            assert command == 'screendump' and args == dict(filename='/out/gui-frame.next.ppm')
            (directory / 'gui-frame.next.ppm').write_bytes(PPM if side == 'source' else OTHER_PPM)
            return {}
        return qmp

    def state(self):
        owner = self.execution.target or self.owner
        live = sorted(child.pid for child in self.tx.children if child.poll() is None)
        return dict(phase='closed' if self.closed else 'target-owned' if self.execution.target else 'source-owned',
                    owner_pid=owner.pid if not self.closed else None, live_owner_pids=live, gui_owner_switch_verified=False)

    def hot(self):
        assert self.frontend.paused and not self.frontend.inflight
        self.events.append(('hot', threading.get_ident()))
        before = list(self.events)
        self.frontend.pump()
        assert before == self.events
        self.used = True
        self.owner.returncode = 0
        directory = self.tx._output / 'target'
        directory.mkdir(mode=0o700)
        (directory / 'console.log').write_bytes(b'host target, no VM\n')
        self.execution.target = Owner(201)
        self.tx.children.append(self.execution.target)
        self.execution.target_qmp = self.qmp_for('target', directory)
        self.execution.continued = True
        self.content = dict(host_only=True, actual_content_verified=False)
        R['save'](self.output / 'hot-result.json', self.content)
        return dict(artifact=API['binding'](self.output / 'hot-result.json'), state=self.state())

    def close(self):
        assert self.frontend.paused
        self.events.append(('close', threading.get_ident()))
        for child in self.tx.children:
            child.returncode = 0
        self.closed = True
        R['save'](self.output / 'result.json', dict(host_only=True, actual_content_verified=False))
        return dict(artifact=API['binding'](self.output / 'result.json'), state=self.state())


@pytest.fixture
def frontend(tmp_path, monkeypatch):
    events = []
    session = Session(tmp_path / 'live', events)
    f = F['Frontend'](session, R, DEV)
    session.frontend = f

    def shell(owner, log, script, phase, token):
        events.append(('shell', owner.pid, log, script, threading.get_ident()))
        count = script.count('/simulation/inject-key ')
        return ('INJECT_KEY_SEND queue=0x807a0020 result=0\n' * count +
                'MENU_DIAG_COMMAND_DONE_' + token + ':0\nRETAINED_DONE_' + phase + '=' + token + '\n')
    monkeypatch.setitem(R, 'shell', shell)
    try:
        yield SimpleNamespace(f=f, session=session, events=events)
    finally:
        f.dispose()


def queued(f, command=pulse(), name='ui-123-000001.cmd'):
    path = f.input_dir / name
    temporary = path.with_suffix('.tmp')
    temporary.write_text(command)
    temporary.replace(path)
    return path


def output(path):
    return path.with_suffix('.out').read_text()


@pytest.mark.parametrize('command', [*(pulse(code) for code in sorted(F['INPUT']['CONTACTS'])), shutter(),
    *(edge(code, status) for code in sorted(F['INPUT']['DIALS']) for status in (1, 0xffffffff)),
    edge(0x71c9, 1), edge(0x71c9, 3), edge(0x7025, 6), edge(0x7025, 20)])
def test_original_syntax_delivery_complete_pair_and_real_marker_only(frontend, command):
    f = frontend.f
    path = queued(f, command)
    f.pump()
    assert not path.exists() and not f.fault and not f.inflight
    receipt = output(path)
    assert 'MENU_DIAG_COMMAND_DONE_' in receipt and ':0\n' in receipt and 'INJECT_KEY_SEND ' in receipt
    assert path.with_suffix('.out').stat().st_mode & 0o777 == 0o600
    script = [event[3] for event in frontend.events if event[0] == 'shell'][0]
    assert command.strip() in script
    assert script.count('sleep 0.05') == command.count('sleep 0.05')
    assert f.frame.read_bytes() == PPM
    status = DEV['read_json'](f.output / 'status.json')
    assert all(status[k] is False for k in F['LIMITS'])


@pytest.mark.parametrize('command', ['echo arbitrary', 'quit', '/simulation/inject-key 1 2 3',
    pulse() + 'rm -rf /\n', edge(0x1ac, 1), edge(0x1ac, 0), edge(0x71c9, 4),
    pulse().replace('sleep 0.05', 'sleep 0.01'), 'x' * 4097, pulse().replace('0x807a0020', '0x80000000'), '中文'])
def test_untrusted_command_has_no_shell_fallback(frontend, command):
    path = queued(frontend.f, command)
    frontend.f.pump()
    assert 'REFUSED' in output(path)
    assert not any(event[0] == 'shell' for event in frontend.events)
    assert not frontend.f.inflight and not frontend.f.fault


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'oversize'])
def test_owned_regular_single_link_budget_and_safe_unlink(frontend, tmp_path, kind):
    f = frontend.f
    sentinel = tmp_path / 'sentinel'
    sentinel.write_text(pulse())
    path = f.input_dir / 'ui-123-000001.cmd'
    if kind == 'symlink':
        path.symlink_to(sentinel)
    elif kind == 'hardlink':
        os.link(sentinel, path)
    elif kind == 'fifo':
        os.mkfifo(path)
    else:
        path.write_bytes(b'x' * 4097)
    f.pump()
    assert not os.path.lexists(path) and 'REFUSED' in output(path)
    assert sentinel.read_text() == pulse()
    assert not any(event[0] == 'shell' for event in frontend.events)


def test_hot_switches_current_popen_qmp_console_and_frame_without_replaying_paused_input(frontend):
    f, s = frontend.f, frontend.session
    f.pump()
    assert f.frame.read_bytes() == PPM
    before = queued(f, name='before.cmd')
    with f.transition('hot'):
        assert 'REFUSED' in output(before)
        during = queued(f, name='during.cmd')
        delayed = f.input_dir / 'delayed.tmp'
        delayed.write_text(pulse())
        s.hot()
    assert 'REFUSED' in output(during)
    delayed.replace(delayed.with_suffix('.cmd'))
    f.pump()
    assert 'REFUSED' in output(delayed.with_suffix('.cmd'))
    assert f.frame.read_bytes() == OTHER_PPM
    assert f.frame.stat().st_mode & 0o777 == 0o600
    after = queued(f, name='after.cmd')
    f.pump()
    assert 'INJECT_KEY_SEND ' in output(after)
    calls = [event for event in frontend.events if event[0] == 'shell']
    assert len(calls) == 1 and calls[0][1] == 201 and calls[0][2] == s.tx._output / 'target/console.log'
    marker = next(i for i, event in enumerate(frontend.events) if event[0] == 'hot')
    assert all(event[1] == 'target' for event in frontend.events[marker + 1:] if event[0] == 'qmp')
    with pytest.raises(ValueError, match='exactly one'):
        with f.transition('hot'):
            pytest.fail('second hot must not run')
    assert not f.fault
    f.next_frame = 0
    f.pump()
    assert f.frame.read_bytes() == OTHER_PPM


@pytest.mark.parametrize('damage', ['timeout', 'nonzero', 'missing-send', 'duplicate', 'wrong-token'])
def test_uncertain_delivery_blocks_hot_and_next_input_preserves_owner_until_explicit_close(frontend, monkeypatch, damage):
    f, s = frontend.f, frontend.session
    def shell(owner, log, script, phase, token):
        if damage == 'timeout':
            raise TimeoutError('host fixture lost marker')
        text = 'INJECT_KEY_SEND result=0\n' * 2 + 'MENU_DIAG_COMMAND_DONE_' + token + ':0\n'
        if damage == 'nonzero':
            text = text.replace(':0', ':1')
        if damage == 'missing-send':
            text = text.replace('INJECT_KEY_SEND result=0\n', '')
        if damage == 'duplicate':
            text += 'MENU_DIAG_COMMAND_DONE_' + token + ':0\n'
        if damage == 'wrong-token':
            text = text.replace(token, 'wrong')
        return text
    monkeypatch.setitem(R, 'shell', shell)
    path = queued(f)
    f.pump()
    assert 'UNCERTAIN' in output(path) and ':0\n' not in output(path)
    assert f.fault and f.inflight and s.owner.poll() is None
    with pytest.raises(ValueError, match='uncertain'):
        with f.transition('hot'):
            pytest.fail('hot while input uncertain')
    next_input = queued(f, name='later.cmd')
    before = f.frame.stat().st_mtime_ns
    f.pump()
    assert 'REFUSED' in output(next_input) and f.frame.stat().st_mtime_ns == before
    assert list(f.output.glob('error-*.json')) and not s.closed
    with f.transition('close'):
        s.close()
    assert s.closed and DEV['read_json'](f.output / 'status.json')['phase'] == 'ended'


def test_hot_and_close_faults_do_not_automatically_close_or_resume_frontend(frontend):
    f, s = frontend.f, frontend.session
    for action in ('hot', 'close'):
        with pytest.raises(RuntimeError, match='original failure'):
            with f.transition(action):
                raise RuntimeError('original failure')
        assert s.owner.poll() is None and not s.closed
        assert f.fault and not f.paused
    path = queued(f)
    f.pump()
    assert 'REFUSED' in output(path)
    assert not any(event[0] in ('shell', 'close') for event in frontend.events)


def test_original_qmp_frame_must_be_new_and_complete_and_late_owner_must_be_running(frontend):
    f, s = frontend.f, frontend.session
    f.pump()
    before = f.frame.stat().st_mtime_ns
    s.qmp = lambda *a: dict(running=False, status='paused')
    f.next_frame = 0
    path = queued(f)
    f.pump()
    assert f.fault and s.owner.poll() is None
    assert f.frame.read_bytes() == PPM and f.frame.stat().st_mtime_ns == before
    assert not any(event[0] == 'shell' for event in frontend.events)
    f.pump()
    assert 'REFUSED' in output(path)


def test_screendump_no_new_bytes_never_publishes_old_frame(frontend):
    f, s = frontend.f, frontend.session
    f.pump()
    before = f.frame.stat().st_mtime_ns
    def no_dump(command, args=None):
        return dict(running=True, status='running') if command == 'query-status' else {}
    s.qmp = no_dump
    f.next_frame = 0
    f.pump()
    assert f.fault and f.frame.stat().st_mtime_ns == before and not s.closed


def test_real_unix_owner_loop_serializes_pump_hot_and_normal_close(frontend, monkeypatch):
    f, s = frontend.f, frontend.session
    # Synthetic transport owners are intentionally not host PIDs; real PID checks
    # and inherited-FD checks have their separate full-content host fixture.
    def authenticate(tx, owner, qmp):
        assert tx is s.tx and owner is s.execution.target and qmp is s.execution.target_qmp
    monkeypatch.setitem(API['R'], 'authenticate_owner', authenticate)
    closes = []
    original_close = s.close
    def close():
        closes.append('close')
        return original_close()
    monkeypatch.setattr(s, 'close', close)
    control = API['OwnerControl'](s, f)
    row = API['binding'](s.output / 'live-owner.json')
    failures = []
    def serve():
        try:
            control.serve()
        except BaseException as error:
            failures.append(error)
    thread = threading.Thread(target=serve)
    thread.start()
    try:
        hot = API['request'](row, s.instance, 'hot')
        assert hot['result']['state']['owner_pid'] == 201 and closes == []
        assert API['inspect_owner'](row, s.instance)['frontend_enabled'] is True
        selected = DEV['read_json'](hot['result']['state']['frontend']['path'])
        assert selected['input_owner_pid'] == 201 and selected['frame'] == str(f.frame)
        command = queued(f)
        for _ in range(100):
            if command.with_suffix('.out').exists():
                break
            threading.Event().wait(.01)
        assert 'INJECT_KEY_SEND' in output(command)
        assert not f.fault and not s.closed and closes == []
        with pytest.raises(API['LiveRequestRefused'], match='exactly one'):
            API['request'](row, s.instance, 'hot')
        assert not f.fault
        API['request'](row, s.instance, 'close')
    finally:
        if not control.closed:
            API['request'](row, s.instance, 'close')
        thread.join(5)
    assert not thread.is_alive() and not failures
    assert {event[-1] for event in frontend.events} == {thread.ident}
    assert s.closed and [child.poll() for child in s.tx.children] == [0, 0]
    assert closes == ['close']


def test_bindings_include_frontend_parser_runner_and_adapter():
    paths = {Path(row['path']) for row in API['SOURCE_BINDINGS']}
    assert {HERE / name for name in ('retained-camera-frontend.py', 'low-latency-input.py',
            'run-retained-camera.py', 'firmware-boot-request.py')} <= paths
    API['COLD']['recheck'](API['SOURCE_BINDINGS'])


def test_gui_context_is_private_copy_hot_unavailable_and_explicit_validation_is_rechecked(monkeypatch):
    dev = RUN['DEV']
    base = dict(instance_identity=dict(id='synthetic'), available_capabilities=dict(sequence=dict(unchanged=True),
                hot=dict(available=True, foreign=True)), runtime_state=dict(wbi_state='unverified'))
    original = copy.deepcopy(base)
    monkeypatch.setitem(dev, 'bind_instance', lambda context: context['instance_identity'])
    monkeypatch.setitem(dev, 'sequence_capability', lambda context, instance: dict(retained_audit=dict(fixed=True)))
    context = RUN['gui_context'](base, dict(path='explicit', sha256='a' * 64))
    assert base == original and context['available_capabilities']['sequence'] == base['available_capabilities']['sequence']
    assert context['available_capabilities']['hot']['available'] is False
    with pytest.raises(Exception):
        RUN['gui_context'](base, dict(path='explicit', sha256='a' * 64), dict(path='/no-proof', sha256='b' * 64))
    checked = []
    monkeypatch.setitem(dev, 'hot_capability', lambda context, instance: checked.append(copy.deepcopy(context['available_capabilities']['hot'])))
    proof = dict(path='/explicit-main-reviewed/result.json', sha256='c' * 64)
    context = RUN['gui_context'](base, dict(path='explicit', sha256='a' * 64), proof)
    assert checked == [context['available_capabilities']['hot']] and checked[0]['live_validation'] == proof
    assert base == original


def test_gui_environment_discards_foreign_usb_reset_and_config_targets(monkeypatch):
    monkeypatch.setenv('CAMUI_USB_RUN', '/foreign')
    monkeypatch.setenv('CAMUI_RESET_RUNTIME', '/foreign')
    monkeypatch.setenv('CAMUI_FIRMWARE_CONTEXT', '/foreign')
    env = RUN['gui_environment'](Path('/explicit/gui-context.json'))
    assert set(key for key in env if key.startswith('CAMUI_')) == {
        'CAMUI_FIRMWARE_CONTEXT', 'CAMUI_FIRMWARE_BACKEND', 'CAMUI_FIRMWARE_PYTHON'}
    assert env['CAMUI_FIRMWARE_CONTEXT'] == '/explicit/gui-context.json'


@pytest.mark.parametrize('kind', ['authenticated', 'unknown', 'normal', 'ended'])
def test_runner_close_failure_preserves_owner_no_signal_or_retry(tmp_path, monkeypatch, kind):
    directory = tmp_path / 'runner'
    directory.mkdir(mode=0o700)
    owner = Owner(101)
    calls = []
    owner.wait = lambda: calls.append('wait') or 0
    if kind == 'ended':
        owner.returncode = 0
    def request(*args):
        calls.append(args[2])
        if kind == 'authenticated':
            raise RUN['LIVE']['LiveRequestRefused']('original close refused', dict(live_owner_pids=[201]))
        if kind == 'unknown':
            error = RuntimeError('wire lost')
            error.state = dict(live_owner_pids=[])
            raise error
        return dict(host_only=True)
    monkeypatch.setitem(RUN['LIVE'], 'request', request)
    if kind in ('authenticated', 'unknown'):
        with pytest.raises(ValueError if kind == 'authenticated' else RuntimeError):
            RUN['close_owned'](owner, {}, {}, directory)
        record = DEV['read_json'](directory / 'owner-preserved.json')
        assert record['owner_retained'] is (True if kind == 'authenticated' else None)
        assert calls == ['close'] and owner.poll() is None
    else:
        assert RUN['close_owned'](owner, {}, {}, directory) == 0
        assert calls == (['close', 'wait'] if kind == 'normal' else [])


def test_runner_starts_one_serve_and_existing_ui_then_typed_close_only(tmp_path, monkeypatch):
    dev = RUN['DEV']
    assets = tmp_path / 'assets'
    runtime, workspace = assets / 'runtime', assets / 'workspace'
    runtime.mkdir(parents=True)
    workspace.mkdir()
    base = dict(schema=dev['CONTEXT_SCHEMA'], runtime=str(runtime), workspace=str(workspace),
                instance_identity=dict(disk=str(assets / 'camera.emmc')), available_capabilities=dict(sequence=dict(retained=True)))
    context = tmp_path / 'context.json'
    dev['write_json'](context, base)
    original = context.read_bytes()
    ui = tmp_path / 'existing-ui'
    ui.write_text('host fixture; must never execute')
    ui.chmod(0o700)
    monkeypatch.setitem(dev, 'bind_instance', lambda context: context['instance_identity'])
    monkeypatch.setitem(dev, 'sequence_capability', lambda *a: dict(retained_audit=dict(fixed=True)))
    daemon, gui = Owner(101), Owner(202)
    gui.returncode = 0
    daemon.wait = lambda: 0
    launched = []
    def popen(argv, **kwargs):
        launched.append((argv, kwargs))
        return daemon if len(launched) == 1 else gui
    monkeypatch.setattr(RUN['subprocess'], 'Popen', popen)
    monkeypatch.setitem(RUN['run'].__globals__, 'wait_ready', lambda *a: ({'path': '/explicit/live-owner.json', 'sha256': 'a' * 64},
                                                                    dict(controller_identity=dict(pid=101))))
    actions = []
    monkeypatch.setitem(RUN['LIVE'], 'request', lambda owner, instance, action: actions.append(action) or dict(host_only=True))
    args = SimpleNamespace(context=context, output=tmp_path / 'runner', ui=ui, live_validation=None, live_validation_sha256=None)
    assert RUN['run'](args) == 0
    assert context.read_bytes() == original and actions == ['close']
    assert len(launched) == 2 and '--frontend' in launched[0][0] and 'serve' in launched[0][0]
    assert '--live' in launched[1][0] and '--input-dir' in launched[1][0] and '--frame' not in launched[1][0]
    assert launched[1][1]['umask'] == 0o077
    copied = dev['read_json'](args.output / 'gui-context.json')
    assert copied['available_capabilities']['hot']['available'] is False
    assert copied['available_capabilities']['sequence'] == base['available_capabilities']['sequence']
