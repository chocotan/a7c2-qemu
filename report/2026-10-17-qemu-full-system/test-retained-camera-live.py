"""Host IPC/owner orchestration and synthetic content review; NO VM evidence."""
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import runpy
import shlex
import socket
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest
from host_transport_fixture import upgrade_fixture, legacy_orchestration_fixture, proof_bytes, wire_bytes

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'retained-camera-live.py'))
G = API['serve'].__globals__
RFIX = runpy.run_path(str(HERE / 'test-retained-camera-test.py'))
BFIX = runpy.run_path(str(HERE / 'test-firmware-boot-request.py'))
@pytest.fixture(params=['direct', 'descendant'])
def anchor_peer(tmp_path, request):
    # Keep AF_UNIX addresses short even when --basetemp is in the evidence tree.
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        address = Path('/proc') / str(os.getpid()) / 'fd' / str(fd)
        yield from RFIX['owned_peer'].__wrapped__(address, request)
    finally:
        os.close(fd)


@pytest.mark.parametrize('attempt', [0, 1, 2])
def test_state_transport_tty_input_has_no_literal_protocol_prefix_but_stdout_is_exact(attempt, monkeypatch):
    spec = API['state_spec']('source', 'a' * 32, 'b' * 32)
    script = "echo RETAINED_LIVE_META host-fixture\necho 'RETAINED_LIVE_CLEAN host-fixture'\n"
    if attempt == 0:
        monkeypatch.setitem(G, 'state_transfer_script', lambda *args: script)
    command = API['state_command'](script, spec, attempt)
    assert 'RETAINED_LIVE_' not in command
    run = subprocess.run(['/bin/sh'], input=command.encode('ascii'), capture_output=True, timeout=5)
    assert run.returncode == 0
    assert run.stdout == (b'RETAINED_LIVE_META host-fixture\nRETAINED_LIVE_CLEAN host-fixture\n' +
                          (API['state_done'](spec, attempt) + '\n').encode('ascii'))


def test_real_state_producer_envelope_cannot_echo_a_protocol_record(tmp_path, monkeypatch):
    from types import SimpleNamespace
    log = tmp_path / 'console'
    log.write_bytes(b'')
    tags, sent = [], []
    envelope = API['E']['diagnostic_envelope']
    def diagnostic(script, tag):
        tags.append(tag)
        return envelope(script, tag)
    def stop_before_guest_input(stream, wire):
        sent.append(wire)
        raise BufferError('host-only stop before any guest input')
    monkeypatch.setitem(API['E'], 'diagnostic_envelope', diagnostic)
    monkeypatch.setitem(API['E'], 'write_console', stop_before_guest_input)
    monkeypatch.setitem(API['R'], 'authenticate_owner', lambda *args: None)
    owner = SimpleNamespace(pid=42, stdin=object(), poll=lambda: None)
    session = SimpleNamespace(token='a' * 32, tx=object(), unchanged=lambda: None)
    with pytest.raises(BufferError, match='host-only stop'):
        API['sample_live_state'](session, owner, object(), log, 'source')
    assert len(sent) == len(tags) == 1
    assert tags[0].startswith('A7C2_STATE_SCRIPT_')
    assert b'RETAINED_LIVE_' not in sent[0]
    assert log.read_bytes() == b''


@pytest.fixture
def failed_state_host(tmp_path, monkeypatch):
    """Real sh/openssl with synthetic state/input helpers; never guest or VM evidence."""
    output = tmp_path / 'output'
    output.mkdir(mode=0o700)
    log = output / 'console'
    prefix = b'original console prefix\n'
    log.write_bytes(prefix)
    helpers = tmp_path / 'bin'
    helpers.mkdir()
    busybox = helpers / 'busybox'
    busybox.write_text('#!/bin/sh\nif [ "$1" = sleep ]; then exit 0; fi\nexec "$@"\n')
    busybox.chmod(0o700)
    inputs, runs = tmp_path / 'input-edges', tmp_path / 'materializations'
    inject = helpers / 'inject-key'
    inject.write_text('#!/bin/sh\necho "$*" >> ' + shlex.quote(str(inputs)) + '\n')
    inject.chmod(0o700)
    ap = tmp_path / 'host-ap'
    ap.write_bytes(b'synthetic host AP hash input')
    monkeypatch.setenv('PATH', str(helpers) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('LC_ALL', 'C')
    monkeypatch.setitem(API['R'], 'MENU', API['R']['MENU'].replace('/simulation/inject-key', str(inject)))
    diagnostic = 'HOST_FALSE_DIAGNOSTIC: deliberate false in original state script'
    f = SimpleNamespace(output=output, log=log, prefix=prefix, inputs=inputs, runs=runs,
                        commands=[], completed=[], proof=tmp_path / 'fixed.proof', diagnostic=diagnostic)
    f.materialize = 'set -e\necho once >> ' + shlex.quote(str(runs)) + '\n'
    f.body = f.materialize + "echo '" + diagnostic + "' >&2\nfalse\necho UNREACHABLE_STATE_SUCCESS\n"
    monkeypatch.setitem(API['R'], 'state_script', lambda *args: f.body)
    original_spec, original_sample = API['state_spec'], API['state_sample_script']
    def host_spec(*args):
        f.spec = dict(original_spec(*args), guest_file=str(f.proof))
        return f.spec
    monkeypatch.setitem(G, 'state_spec', host_spec)
    monkeypatch.setitem(G, 'state_sample_script', lambda s: original_sample(s).replace('/usr/lib/appFw.so', str(ap)))
    monkeypatch.setitem(API['R'], 'authenticate_owner', lambda *args: None)
    monkeypatch.setitem(API['R'], 'wait_for', lambda owner, path, condition, seconds:
        condition(API['R']['console'](path)) or (_ for _ in ()).throw(TimeoutError('host incomplete')))
    def write(stream, envelope):
        f.commands.append(envelope)
        run = subprocess.run(['/bin/sh'], input=envelope, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        f.completed.append(run)
        with log.open('ab') as out:
            out.write(run.stdout)
    monkeypatch.setitem(API['E'], 'write_console', write)
    f.owner = SimpleNamespace(pid=42, stdin=object(), poll=lambda: None)
    f.session = SimpleNamespace(output=output, token='a' * 32, tx=object(), state_transports={},
                                state_deadline=time.monotonic() + 60, unchanged=lambda: None)
    return f


def assert_failed_state_host(f, rc):
    assert len(f.commands) == len(f.completed) == 1
    assert b'RETAINED_LIVE_' not in f.commands[0]
    assert len(f.inputs.read_text().splitlines()) == 2
    assert f.runs.read_text() == 'once\n'
    assert not f.session.state_transports and f.owner.poll() is None
    assert f.completed[0].returncode == 0  # The outer shell reports the original status in DONE.
    raw = f.log.read_bytes()[len(f.prefix):]
    assert raw.endswith((API['state_done'](f.spec, 0).removesuffix('0') + str(rc) + '\n').encode())
    assert sum(line.startswith(b'RETAINED_LIVE_DONE ') for line in raw.splitlines()) == 1
    diagnostic = json.loads((f.output / 'menu-state-failed-diagnostic.json').read_bytes())
    assert diagnostic['original_rc'] == rc and diagnostic['spec'] == f.spec
    assert diagnostic['valid_for_state'] is diagnostic['actual_content_verified'] is False
    assert diagnostic['begin'] == len(f.prefix) and diagnostic['end'] == f.log.stat().st_size
    assert (f.output / 'menu-state-failed-diagnostic.raw').read_bytes() == raw
    assert diagnostic['trace'] == API['binding'](f.output / 'menu-state-failed-diagnostic.raw')
    assert not list(f.output.glob('menu-state-transport.*'))
    with pytest.raises(ValueError):
        API['decode_state_transfer'](raw, f.spec, 0)
    return raw


def test_real_errexit_failed_file_recovered_once_but_online_and_offline_reject(failed_state_host):
    f = failed_state_host
    with pytest.raises(ValueError, match='State command completion/code differs'):
        API['sample_live_state'](f.session, f.owner, None, f.log, 'menu')
    raw = assert_failed_state_host(f, 1)
    proof = f.proof.read_bytes()
    assert proof.endswith((f.diagnostic + '\n').encode())
    assert b'UNREACHABLE_STATE_SUCCESS' not in proof
    assert b'RETAINED_DONE_menu=' not in proof and b'RETAINED_STATE_END=' not in proof
    assert API['state_file_markers'](f.spec)[1].encode() not in proof
    assert f.spec['code_sha256'] == hashlib.sha256(f.body.encode('ascii')).hexdigest()
    expected = wire_bytes(API, f.spec, proof).replace(b'attempt=0 rc=0\n', b'attempt=0 rc=1\n')
    assert raw == expected  # Real before/after SHA, size, nonce, file, and every transferred byte.
    assert f.proof.read_bytes() == proof  # No cleanup or regeneration of the failed file.
    with pytest.raises(ValueError):
        API['review_state_file'](proof, f.spec)
    # Even a freshly bound forged success receipt must fail at the original nonzero DONE.
    stem = 'menu-state-transport'
    API['R']['save_bytes'](f.output / (stem + '.raw'), raw)
    API['R']['save_bytes'](f.output / (stem + '.proof'), proof)
    receipt = dict(schema=API['STATE_DOMAIN'], spec=f.spec, owner_pid=42,
        log='transaction/target/console.log', begin=len(f.prefix), end=f.log.stat().st_size,
        attempts=[dict(begin=len(f.prefix), end=f.log.stat().st_size,
            command_sha256=hashlib.sha256(API['state_command'](G['state_sample_script'](f.spec), f.spec, 0).encode()).hexdigest())],
        cleanup_begin=f.log.stat().st_size, trace=API['binding'](f.output / (stem + '.raw')),
        sample=API['binding'](f.output / (stem + '.proof')))
    API['R']['save'](f.output / (stem + '.json'), receipt)
    with pytest.raises(ValueError, match='State END/hash/completion identity differs'):
        API['replay_live_state'](f.output, 'menu', f.session.token, f.log.read_bytes(), 42,
            API['binding'](f.output / (stem + '.json')), lambda name: (f.output / name).read_bytes())
    assert len(f.commands) == 1 and f.runs.read_text() == 'once\n'


def test_failed_readonly_transfer_preserves_original_rc_and_raw(failed_state_host):
    f = failed_state_host
    f.body = f.materialize + 'busybox dd if=/dev/zero bs=65536 count=1 2>/dev/null\nfalse\n'
    with pytest.raises(ValueError, match='State command completion/code differs'):
        API['sample_live_state'](f.session, f.owner, None, f.log, 'menu')
    raw = assert_failed_state_host(f, 1)
    assert f.proof.stat().st_size > API['STATE_LIMIT']
    assert b'RETAINED_LIVE_META ' not in raw and b'RETAINED_LIVE_END ' not in raw


@pytest.mark.parametrize('save_function', ['save_bytes', 'save'])
def test_failed_diagnostic_local_save_cannot_replace_original_error(failed_state_host, monkeypatch, save_function):
    f = failed_state_host
    def cannot_save(*args):
        raise OSError('host diagnostic storage unavailable')
    monkeypatch.setitem(API['R'], save_function, cannot_save)
    with pytest.raises(ValueError, match='State command completion/code differs') as caught:
        API['sample_live_state'](f.session, f.owner, None, f.log, 'menu')
    assert any('host diagnostic storage unavailable' in note for note in caught.value.__notes__)
    assert f.proof.read_bytes().endswith((f.diagnostic + '\n').encode())
    assert f.log.read_bytes().endswith(b'attempt=0 rc=1\n') and len(f.commands) == 1
    assert not f.session.state_transports


def test_controlled_proc_fd_diagnostic_error_retains_required_observations_but_cannot_pass(failed_state_host):
    f = failed_state_host
    frame = f.proof.parent / 'headless-osd-frame.bin'
    frame.write_bytes(b'host-only frame FD target')
    body = RFIX['state_text']('menu').removesuffix('RETAINED_STATE_END=menu\n')
    f.body = (f.materialize + "cat <<'HOST_STATE'\n" + body + 'HOST_STATE\n' +
        'exec 8<' + shlex.quote(str(frame)) + '\n' +
        'ls -l /proc/self/fd /proc/self/fd/2147483647\necho UNREACHABLE_STATE_SUCCESS\n')
    with pytest.raises(ValueError, match='State command completion/code differs'):
        API['sample_live_state'](f.session, f.owner, None, f.log, 'menu')
    raw = assert_failed_state_host(f, 2)
    proof = f.proof.read_bytes()
    assert str(frame).encode() in proof and b'No such file or directory' in proof
    assert b'/fd/2147483647' in proof and b'RETAINED_FRAME_HEADER=' in proof
    assert b'RETAINED_VIEWER_PID=32' in proof and proof.count(b'FLOCK  ADVISORY') == 2
    assert b'UNREACHABLE_STATE_SUCCESS' not in proof
    assert raw == wire_bytes(API, f.spec, proof).replace(b'attempt=0 rc=0\n', b'attempt=0 rc=2\n')
    with pytest.raises(ValueError):
        API['review_state_file'](proof, f.spec)


@pytest.mark.parametrize('missing', [None, 'Uid:', 'RETAINED_VIEWER_PID=', 'FLOCK',
                                    'RETAINED_FRAME_HEADER=', 'RETAINED_BOOT_ID=', 'RETAINED_CANARY='])
def test_optional_diagnostic_noise_never_substitutes_for_required_content(missing):
    spec = API['state_spec']('menu', 'a' * 32, 'b' * 32)
    body = RFIX['state_text']('menu')
    if missing:
        body = '\n'.join(line for line in body.splitlines() if missing not in line) + '\n'
    # Synthetic complete content only: no production optional-error adapter is installed.
    body = body.replace('RETAINED_STATE_END=menu\n',
        'ls: /proc/32/fd/6: No such file or directory\nRETAINED_VIEWER_FD_LS_RC=1\nRETAINED_STATE_END=menu\n')
    proof = proof_bytes(API, spec, body)
    if missing:
        with pytest.raises(ValueError):
            API['review_state_file'](proof, spec)
    else:
        assert API['review_state_file'](proof, spec)['viewer_pids'] == ['32']
    nonzero = wire_bytes(API, spec, proof).replace(b'attempt=0 rc=0\n', b'attempt=0 rc=1\n')
    with pytest.raises(ValueError, match='State END/hash/completion identity differs'):
        API['decode_state_transfer'](nonzero, spec, 0)


def unfactored_state_command(script, spec, attempt):
    """Frozen pre-candidate wire reference; execute it with the same host file."""
    done = API['state_done'](spec, attempt).removesuffix('0')
    recovery = ('if test "$a7c2_state_rc" -ne 0; then\n(\n' + API['state_transfer_script'](spec, 0) +
                '\n)\nfi\n') if attempt == 0 else ''
    return ('(\n' + script + '\n)\na7c2_state_rc=$?\n' + recovery +
            'echo \'' + done + '\'"$a7c2_state_rc"\n').replace('RETAINED_LIVE_', "RETAINED_''LIVE_")


@pytest.mark.parametrize('size', [1, 191, 192, 193, 65535])
def test_factored_real_producer_is_byte_equal_to_unfactored(tmp_path, size):
    payload = bytes(index % 256 for index in range(size))
    proof = tmp_path / 'fixed.proof'
    proof.write_bytes(payload)
    materializations = tmp_path / 'materializations'
    spec = dict(API['state_spec']('source', 'a' * 32, 'b' * 32), guest_file=str(proof))
    transfer = API['state_transfer_script'](spec, 0)
    script = 'set -e\necho once >> ' + shlex.quote(str(materializations)) + '\n' + transfer
    outputs = []
    for generator in (unfactored_state_command, API['state_command']):
        command = generator(script, spec, 0)
        envelope = API['E']['diagnostic_envelope'](command, 'A7C2_STATE_SCRIPT_' + spec['nonce'] + '_0')
        assert 'RETAINED_LIVE_' not in envelope
        assert max(len(line.encode('ascii')) for line in envelope.splitlines()) <= 512
        result = subprocess.run(['/bin/sh', '-x'], input=('busybox() { "$@"; }\n' + command).encode('ascii'),
                                capture_output=True, timeout=10)
        assert result.returncode == 0, result.stderr
        assert result.stderr.count(b'/usr/bin/openssl enc -base64 -in ') == 1
        assert result.stderr.count(b'/usr/bin/openssl dgst -sha256 ') == 2
        assert result.stdout == wire_bytes(API, spec, payload)
        assert API['decode_state_transfer'](result.stdout, spec, 0) == payload
        assert proof.read_bytes() == payload
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] and materializations.read_text() == 'once\nonce\n'
    for attempt in (1, 2):
        assert API['state_command'](transfer, spec, attempt) == unfactored_state_command(transfer, spec, attempt)


def test_factoring_requires_one_exact_transfer_suffix():
    spec = API['state_spec']('source', 'a' * 32, 'b' * 32)
    transfer = API['state_transfer_script'](spec, 0)
    for script in ('echo unrelated\n', transfer + 'echo after\n', transfer + transfer):
        with pytest.raises(ValueError, match='transfer suffix differs'):
            API['state_command'](script, spec, 0)
    command = API['state_command'](API['state_sample_script'](spec), spec, 0)
    assert command.count(transfer.replace('RETAINED_LIVE_', "RETAINED_''LIVE_")) == 1
    assert 'a7c2_state_transfer() (\nset -e\n' in command
    assert API['state_spec']('source', 'a' * 32, 'b' * 32)['code_sha256'] == spec['code_sha256']


@pytest.mark.parametrize('completion', ['zero', 'nonzero', 'duplicate'])
@pytest.mark.parametrize('foreign', ['nonce', 'phase', 'attempt'])
def test_done_fragments_wait_for_newline_before_strict_decode(failed_state_host, monkeypatch, completion, foreign):
    f = failed_state_host
    rc = 7 if completion == 'nonzero' else 0
    f.body = f.materialize + ('echo HOST_EXIT_SEVEN >&2\nexit 7\n' if rc else 'echo HOST_SUCCESS\n')
    pending, statuses, decoded = [], [], []
    def write(stream, envelope):
        f.commands.append(envelope)
        result = subprocess.run(['/bin/sh'], input=envelope, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
        f.completed.append(result)
        head, tail = result.stdout.rsplit(b' rc=', 1)
        assert tail == str(rc).encode() + b'\n'
        done = head.split(b'\n')[-1] + b' rc=' + tail
        wrong = done.replace(f.spec['nonce'].encode(), b'c' * 32) if foreign == 'nonce' else (
            done.replace(b'phase=menu', b'phase=source') if foreign == 'phase' else done.replace(b'attempt=0', b'attempt=1'))
        with f.log.open('ab') as out:
            out.write(wrong + head + b' rc=')
        pending.extend([str(rc).encode(), b'\r', b'\n' + (done if completion == 'duplicate' else b'')])
    def wait(owner, path, condition, seconds):
        statuses.append(condition(API['R']['console'](path)))
        for fragment in pending:
            with path.open('ab') as out:
                out.write(fragment)
            statuses.append(condition(API['R']['console'](path)))
        assert statuses == [False, False, False, True]
    def decode(raw, spec, attempt):
        decoded.append(raw)
        raise BufferError('host stop after complete DONE before semantic review')
    monkeypatch.setitem(API['E'], 'write_console', write)
    monkeypatch.setitem(API['R'], 'wait_for', wait)
    monkeypatch.setitem(G, 'decode_state_transfer', decode)
    with pytest.raises(BufferError if completion == 'zero' else ValueError,
                       match='complete DONE' if completion == 'zero' else 'completion/code differs'):
        API['sample_live_state'](f.session, f.owner, None, f.log, 'menu')
    assert len(decoded) == (1 if completion == 'zero' else 0)
    assert len(f.commands) == 1 and f.runs.read_text() == 'once\n'
    assert f.inputs.read_text().splitlines() == ['0x807a0020 0x92840747 0x1ab 0 1 0 1',
                                               '0x807a0020 0x92840747 0x1ab 0 0 0 1']
    assert not f.session.state_transports and f.proof.exists()
    if rc:
        row = json.loads((f.output / 'menu-state-failed-diagnostic.json').read_bytes())
        assert row['original_rc'] == 7 and row['valid_for_state'] is row['actual_content_verified'] is False
    else:
        assert not (f.output / 'menu-state-failed-diagnostic.json').exists()


class HostSession:
    """Only the IPC fixture, never passed to production serve()."""
    def __init__(self, directory):
        self.output, self.instance = directory, dict(id='host-only', generation=0)
        self.used = self.closed = False

    def state(self):
        return dict(phase='closed' if self.closed else 'source-owned',
                    owner_pid=None if self.closed else os.getpid(),
                    live_owner_pids=[] if self.closed else [os.getpid()],
                    capture_returned=False, controller_pid=os.getpid(), hot_consumed=self.used,
                    gui_owner_switch_verified=False,
                    display='none' if self.closed else 'host-only fixture',
                    input='none' if self.closed else 'host-only fixture')

    def hot(self):
        if self.used:
            raise ValueError('one hot only')
        self.used = True
        API['R']['save'](self.output / 'hot-result.json', dict(host_only=True, actual_content_verified=False))
        return dict(artifact=API['binding'](self.output / 'hot-result.json'), state=self.state())

    def close(self):
        self.closed = True
        API['R']['save'](self.output / 'result.json', dict(host_only=True, actual_content_verified=False))
        return dict(artifact=API['binding'](self.output / 'result.json'), state=self.state())


def host_controller(directory, pipe):
    control = API['OwnerControl'](HostSession(directory))
    pipe.send(API['binding'](directory / 'live-owner.json'))
    pipe.close()
    control.serve()


@pytest.fixture
def daemon(tmp_path):
    # This exceeds sockaddr_un.sun_path; the API pins/uses its own directory FD.
    output = tmp_path / ('private-' + 'x' * 100)
    output.mkdir(mode=0o700)
    receive, send = multiprocessing.Pipe(duplex=False)
    owner = multiprocessing.get_context('fork').Process(target=host_controller, args=(output, send))
    owner.start()
    send.close()
    assert receive.poll(10), 'host-only socket controller failed to start'
    row = receive.recv()
    receive.close()
    try:
        yield SimpleNamespace(owner=owner, binding=row, output=output, instance=dict(id='host-only', generation=0))
    finally:
        if owner.is_alive():
            API['request'](row, dict(id='host-only', generation=0), 'close')
        owner.join(10)
        assert not owner.is_alive() and owner.exitcode == 0, 'No host test controller may remain alive'
        owner.close()


def test_real_unix_peer_identity_one_hot_then_normal_typed_close(daemon):
    descriptor = API['inspect_owner'](daemon.binding, daemon.instance)
    assert descriptor['frontend_enabled'] is False
    assert descriptor['controller_identity']['pid'] == daemon.owner.pid != os.getpid()
    assert descriptor['controller_identity']['start_ticks'] > 0
    hot = API['request'](daemon.binding, daemon.instance, 'hot')
    assert hot['result']['state']['hot_consumed'] is True
    assert API['DEV']['read_json'](hot['result']['artifact']['path'])['actual_content_verified'] is False
    assert set(hot['result']) == {'artifact', 'state'}
    with pytest.raises(API['LiveRequestRefused'], match='one hot only') as refused:
        API['request'](daemon.binding, daemon.instance, 'hot')
    assert refused.value.state['live_owner_pids'] == [daemon.owner.pid]
    assert refused.value.state['hot_consumed'] is True
    assert daemon.owner.is_alive() and not (daemon.output / 'result.json').exists()
    API['request'](daemon.binding, daemon.instance, 'close')
    daemon.owner.join(10)
    assert daemon.owner.exitcode == 0
    with pytest.raises(FileNotFoundError):
        API['inspect_owner'](daemon.binding, daemon.instance)


@pytest.mark.parametrize('damage', ['nonce', 'instance', 'pid', 'start_ticks', 'socket', 'command', 'path', 'action', 'frontend'])
def test_malformed_or_unbound_requests_cannot_consume_source(daemon, damage):
    with API['endpoint'](daemon.binding, daemon.instance) as (descriptor, path), socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(path))
        message = dict(schema=API['SCHEMA'], action='hot', nonce=descriptor['nonce'], instance_identity=daemon.instance,
                       socket_identity=descriptor['socket_identity'], client_identity=API['process'](os.getpid()),
                       frontend_enabled=descriptor['frontend_enabled'])
        if damage == 'frontend':
            message['frontend_enabled'] = True
        elif damage == 'nonce':
            message['nonce'] = '0' * 64
        elif damage == 'instance':
            message['instance_identity'] = dict(daemon.instance, generation=1)
        elif damage == 'pid':
            message['client_identity']['pid'] = daemon.owner.pid
        elif damage == 'start_ticks':
            message['client_identity']['start_ticks'] += 1
        elif damage == 'socket':
            message['socket_identity'] = dict(descriptor['socket_identity'], ino=0)
        elif damage == 'action':
            message['action'] = 'exec'
        else:
            message[damage] = '/tmp/do-not-execute'
        API['send'](connection, message)
        response = API['receive'](connection)
        assert response['status'] == 'refused' and set(response['result']) == {'error'}
    assert not (daemon.output / 'hot-result.json').exists()
    API['request'](daemon.binding, daemon.instance, 'hot')


@pytest.mark.parametrize('damage', ['echo', 'controller', 'peer', 'endpoint', 'state'])
def test_refusal_state_is_exposed_only_after_all_response_authentication(daemon, monkeypatch, damage):
    API['request'](daemon.binding, daemon.instance, 'hot')
    original_receive, original_peer, original_endpoint = API['receive'], API['peer'], API['endpoint']
    with monkeypatch.context() as patcher:
        def receive(connection):
            response = original_receive(connection)
            assert response['status'] == 'refused' and 'state' in response['result']
            if damage == 'echo':
                response['request']['nonce'] = '0' * 64
            elif damage == 'controller':
                response['controller_identity']['start_ticks'] += 1
            elif damage == 'peer':
                def changed_peer(connection):
                    value = original_peer(connection)
                    value['start_ticks'] += 1
                    return value
                patcher.setitem(G, 'peer', changed_peer)
            elif damage == 'state':
                response['result']['state']['live_owner_pids'] = [True]
            return response
        if damage == 'endpoint':
            @contextmanager
            def changed_endpoint(*args, **kwargs):
                with original_endpoint(*args, **kwargs) as value:
                    yield value
                    raise ValueError('endpoint changed at exit')
            patcher.setitem(G, 'endpoint', changed_endpoint)
        patcher.setitem(G, 'receive', receive)
        with pytest.raises(ValueError) as refused:
            API['request'](daemon.binding, daemon.instance, 'hot')
        assert not isinstance(refused.value, API['LiveRequestRefused'])
        assert not hasattr(refused.value, 'state')
    assert daemon.owner.is_alive() and not (daemon.output / 'result.json').exists()


def test_refusal_without_state_is_explicitly_unconfirmed(daemon, monkeypatch):
    API['request'](daemon.binding, daemon.instance, 'hot')
    original = API['receive']
    def receive(connection):
        response = original(connection)
        response['result'].pop('state')
        return response
    with monkeypatch.context() as patcher:
        patcher.setitem(G, 'receive', receive)
        with pytest.raises(API['LiveRequestRefused']) as refused:
            API['request'](daemon.binding, daemon.instance, 'hot')
        assert refused.value.state is None


def test_server_impersonation_and_descriptor_replay_refused(daemon):
    path = daemon.output / 'live-owner.json'
    original = path.read_bytes()
    descriptor = json.loads(original)
    descriptor['controller_identity'] = API['process'](os.getpid())
    API['DEV']['write_json'](path, descriptor)
    try:
        with pytest.raises(ValueError, match='not the declared'):
            API['request'](API['binding'](path), daemon.instance, 'hot')
        with pytest.raises(ValueError, match='SHA256 differs'):
            API['request'](daemon.binding, daemon.instance, 'hot')
    finally:
        path.write_bytes(original)
    assert not (daemon.output / 'hot-result.json').exists()


def test_socket_inode_and_private_directory_are_pinned(tmp_path):
    output = tmp_path / 'control'
    output.mkdir(mode=0o700)
    control = API['OwnerControl'](HostSession(output))
    row = API['binding'](output / 'live-owner.json')
    control.close_socket()
    original = output / 'control.sock'
    original.rename(output / 'old.sock')
    with socket.socket(socket.AF_UNIX) as replacement:
        fd = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            replacement.bind('/proc/self/fd/' + str(fd) + '/control.sock')
        finally:
            os.close(fd)
        original.chmod(0o600)
        with pytest.raises(ValueError, match='inode changed'):
            API['inspect_owner'](row, dict(id='host-only', generation=0))
    output.chmod(0o755)
    with pytest.raises(ValueError, match='0700'):
        API['inspect_owner'](row, dict(id='host-only', generation=0))


@pytest.mark.parametrize('raw', [b'{"x":1,"x":2}\n', b'{}\n{}\n', b'{"x":NaN}\n', b'x' * (API['WIRE_LIMIT'] + 1)])
def test_bounded_single_record_duplicate_keys_and_nonfinite_refused(raw):
    left, right = socket.socketpair()
    with left, right:
        worker = threading.Thread(target=lambda: (right.sendall(raw), right.shutdown(socket.SHUT_WR)))
        worker.start()
        with pytest.raises(ValueError):
            API['receive'](left)
        worker.join(5)
        assert not worker.is_alive()


def page_line(page):
    if page == 'prefixed-off':
        return b'/ # '+page_line('off')
    main = (RFIX['input_text']('shooting').splitlines()[-1]+'\n').encode()
    if page == 'unknown':
        return b'host-only source without original screen evidence\n'
    if page == 'malformed':
        return b'OBS CREATE_SCREEN_ARGS call=5 id=0 count=565\n'
    if page == 'partial':
        return main.rstrip(b'\n')
    screen, count = {'shooting': ('0', 565), 'off': ('0x309', 0),
                     'menu': ('0x2c9', 46), 'warning': ('0x308', 28)}[page]
    return main.replace(b'call=6', b'call=7').replace(b'id=0 count=565', f'id={screen} count={count}'.encode())


@pytest.fixture
def session(tmp_path, monkeypatch, request):
    output = tmp_path / 'live'
    (output / 'transaction').mkdir(parents=True, mode=0o700)
    (output / 'launch/run').mkdir(parents=True, mode=0o700)
    output.chmod(0o700)
    events = []
    disk = output / 'host-disk-identity'
    disk.write_bytes(b'host-only mutable disk')
    disk.chmod(0o600)
    fd = os.open(disk, os.O_RDWR)
    request.addfinalizer(lambda: os.close(fd))
    qmp = RFIX['ActiveDiskQMP'](disk, fd, events)
    source = RFIX['Owner'](101)
    tx = SimpleNamespace(_output=output / 'transaction', guest_sync_nonce='f' * 32, children=[source])
    log = tx._output / 'source-console.log'
    log.write_bytes(b'original source running\n'+page_line('shooting'))
    log.chmod(0o600)
    owned = dict(owner=dict(parent_pid=os.getpid()), peer=dict(pid=102))
    class Execution:
        identity = owned
        target = None
        def capture(self, evidence, *, timeout):
            assert source.poll() is None and evidence['owner_pid'] == source.pid
            assert evidence['nonce'] == tx.guest_sync_nonce
            qmp.check_identity()
            assert 'guest-sync' in events
            events.append('capture-existing-source')
            source.returncode = 0
            return dict(host_only=True)
        def restore(self, *, target_run, timeout):
            assert source.poll() == 0
            self.target = RFIX['Owner'](201)
            tx.children.append(self.target)
            directory = tx._output / 'target'
            directory.mkdir(mode=0o700)
            (directory / 'console.log').write_bytes(b'')
            events.append('restore-paused')
            self.target_qmp = RFIX['ActiveDiskQMP'](disk, fd, events)
            self.target_qmp.running = False
            return self.target, self.target_qmp, dict(host_only=True)
        def continue_target(self):
            self.target_qmp('cont')
            events.append('cont-verified-target')
        def close(self):
            for child in tx.children:
                child.returncode = 0
            events.append('normal-close')
            return dict(host_only=True, owners_closed=True)
    obj = API['LiveSession'](None, dict(instance_identity=dict(id='host-fixture', generation=0)), {}, output, tx,
        dict(dtb=str(output / 'launch/run/virt.dtb'), profile=API['L']['UPSTREAM_PROFILE'],
             qemu_sha256=API['L']['UPSTREAM_BINARY_SHA'], combo_binding=dict(source_tree_sha256=API['L']['UPSTREAM_SOURCE_SHA'])),
        {}, {}, {}, {})
    monkeypatch.setitem(G, 'sample_live_state', lambda *a, **kw: legacy_orchestration_fixture(API, *a, **kw))
    obj.instance = dict(id='host-fixture', generation=0)
    obj.owner, obj.execution, obj.qmp = source, Execution(), qmp
    obj.token = 'a' * 32
    obj.ready_state = API['R']['parse_state'](RFIX['state_text']('source', obj.token), 'source')
    obj.source_run, obj.target_run = 'retained-source-' + obj.token, 'retained-target-' + obj.token
    obj.transfer_timeout = 1
    monkeypatch.setattr(obj, 'unchanged', lambda: events.append('check-current-context'))
    def authenticate_owner(transaction, owner, current_qmp):
        assert transaction is tx and any(child is owner for child in tx.children) and owner.poll() is None
        events.append('preauth')
    monkeypatch.setitem(API['R'], 'authenticate_owner', authenticate_owner)
    monkeypatch.setitem(API['R']['paused'].__wrapped__.__globals__, 'authenticate_owner', authenticate_owner)
    def owned_identity(transaction, launch, owner, current_qmp):
        current_qmp.check_identity()
        return owned
    monkeypatch.setitem(API['C'], '_owned_identity', owned_identity)
    def shell(owner, log, script, phase, token):
        current_qmp = qmp if owner is source else obj.execution.target_qmp
        assert current_qmp.running, 'No guest shell command may be issued while paused'
        events.append('shell-'+phase)
        return (RFIX['input_text'](phase) if phase in ('menu', 'shooting') else '') + RFIX['state_text'](phase, token)
    monkeypatch.setitem(API['R'], 'shell', shell)
    monkeypatch.setitem(API['R'], 'wait_for', lambda *a: None)
    def write_console(stdin, raw):
        assert qmp.running, 'Guest sync must finish before outer pause'
        events.append('guest-sync')
        with log.open('ab') as f:
            f.write(raw + raw.split(b"'")[1] + b'\n')
    monkeypatch.setitem(API['E'], 'write_console', write_console)
    monkeypatch.setitem(API['R'], 'snapshot', lambda qmp, directory, phase: API['R']['pixel_review'](*RFIX['pixels'](phase)))
    monkeypatch.setitem(G, 'verify_result', lambda *a: dict(host_only=True))
    return SimpleNamespace(obj=obj, events=events, tx=tx, output=output, qmp=qmp)


@pytest.fixture
def anchor_session(tmp_path, monkeypatch, anchor_peer):
    """Real peer preauthentication and FD/path stamps; no VM or guest commands."""
    disk = tmp_path / 'anchor-disk'
    disk.write_bytes(b'unchanged host-only disk')
    disk.chmod(0o600)
    fd = os.open(disk, os.O_RDWR)
    qmp = anchor_peer.qmp
    qmp.disk, qmp.fd = disk, fd
    context = dict(runtime='host-runtime', workspace='host-workspace',
                   instance_identity=dict(id='host-anchor', generation=0), routes={})
    current, cap = copy.deepcopy(context), dict(host_only=True)
    tx = anchor_peer.tx
    tx._output = tmp_path
    obj = API['LiveSession'](None, context, cap.copy(), tmp_path, tx, {}, {}, {}, {}, {})
    obj.owner, obj.qmp = anchor_peer.owner, qmp
    monkeypatch.setitem(API['DEV'], 'load_context', lambda path: copy.deepcopy(current))
    monkeypatch.setitem(API['DEV'], 'sequence_capability', lambda context, instance: cap)
    def bind(context):
        qmp.check_identity()
        qmp.events.append('bind-instance')
        return obj.instance
    def anchor():
        qmp.check_identity()
        qmp.events.append('anchor')
    monkeypatch.setitem(API['DEV'], 'bind_instance', bind)
    tx._check_anchor = anchor
    try:
        yield SimpleNamespace(obj=obj, qmp=qmp, current=current, cap=cap, peer=anchor_peer)
    finally:
        os.close(fd)


@pytest.mark.parametrize('selected', ['source', 'target'])
def test_unchanged_quiesces_selected_owner_for_strict_fd_path_checks(anchor_session, selected):
    f = anchor_session
    if selected == 'target':
        f.obj.execution = SimpleNamespace(target=f.obj.owner, target_qmp=f.qmp)
        f.obj.owner = RFIX['Owner'](101)  # Target takes priority even if source still polls live.
        f.obj.qmp = RFIX['ActiveDiskQMP'](f.qmp.disk, f.qmp.fd, [])
    else:
        f.obj.execution = SimpleNamespace(target=None)
    content = f.qmp.disk.read_bytes()
    with pytest.raises(ValueError, match='stamp drift'):
        f.obj.tx._check_anchor()
    before, after = f.qmp.samples.pop()['before'], API['DS']['_record'](f.qmp.fd)
    assert before['stamp'] != after['stamp'] and f.qmp.disk.read_bytes() == content
    for _ in range(2):
        f.obj.unchanged()
        assert f.qmp.running and f.peer.owner.poll() is None
    assert len(f.qmp.samples) == 4
    assert all(not row['running'] and row['before'] == row['after'] for row in f.qmp.samples)
    assert f.qmp.disk.read_bytes() == content
    assert f.qmp.events.count('stop') == f.qmp.events.count('cont') == 2
    if selected == 'target':
        assert f.obj.qmp.events == []
    evidence = list(f.obj.output.glob('anchor-identity-quiesce-*.jsonl'))
    assert len(evidence) == 2 and len({path.name for path in evidence}) == 2
    for path in evidence:
        assert path.stat().st_mode & 0o777 == 0o600
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert rows[0] == dict(event='owner-authenticated', owner_pid=f.peer.owner.pid)
        assert rows[-1]['event'] == 'completed'


@pytest.mark.parametrize('phase', ['startup', 'pre-qmp', 'source-exited', 'target-exited'])
def test_unchanged_without_active_qmp_keeps_original_direct_checks(anchor_session, monkeypatch, phase):
    f = anchor_session
    f.qmp.running = False  # An inert host file has no writer in these lifecycle stages.
    if phase == 'startup':
        f.obj.owner = f.obj.qmp = None
    elif phase == 'pre-qmp':
        f.obj.qmp = None
    else:
        retired = RFIX['Owner'](101)
        retired.returncode = 0
        f.obj.owner = retired
        if phase == 'target-exited':
            f.obj.execution = SimpleNamespace(target=retired, target_qmp=f.qmp)
    def forbidden(*args, **kwargs):
        raise AssertionError('No active QMP owner may be paused')
    monkeypatch.setitem(API['R'], 'paused', forbidden)
    f.obj.unchanged()
    assert f.qmp.events == ['bind-instance', 'anchor']
    assert not list(f.obj.output.glob('anchor-identity-quiesce-*.jsonl'))
    assert len(f.qmp.samples) == 2


def test_unchanged_nested_in_running_never_continues_before_outer_identity(anchor_session, monkeypatch):
    f = anchor_session
    expected = dict(host_only=True)
    f.obj.execution = SimpleNamespace(target=None, identity=expected)
    def owned_identity(tx, launch, owner, qmp):
        assert tx is f.obj.tx and owner is f.obj.owner and qmp is f.qmp
        assert not qmp.running and 'cont' not in qmp.events
        qmp.check_identity()
        qmp.events.append('outer-owned-identity')
        return expected
    monkeypatch.setitem(API['C'], '_owned_identity', owned_identity)
    assert f.obj.running(f.obj.owner, f.qmp) == expected
    assert f.qmp.events.count('stop') == 2 and f.qmp.events.count('cont') == 1
    assert f.qmp.events.index('anchor') < f.qmp.events.index('outer-owned-identity') < f.qmp.events.index('cont')
    assert f.qmp.running and all(not row['running'] for row in f.qmp.samples)
    inner, = f.obj.output.glob('anchor-identity-quiesce-*.jsonl')
    rows = [json.loads(line) for line in inner.read_text().splitlines()]
    responses = [row for row in rows if row['event'] == 'response']
    assert responses[0]['response'] == dict(status='paused', running=False)
    assert not any(row.get('command') == 'cont' for row in rows)


def test_unchanged_foreign_peer_is_refused_before_any_qmp_or_disk_check(anchor_session):
    f = anchor_session
    local, remote = socket.socketpair()
    with local, remote:
        f.qmp.sock = local  # The real peer is this controller, outside the owner's ancestry.
        with pytest.raises(ValueError, match='not owned'):
            f.obj.unchanged()
    assert f.qmp.events == [] and f.qmp.samples == [] and f.qmp.running
    assert f.peer.owner.poll() is None and not f.obj.closed
    evidence, = f.obj.output.glob('anchor-identity-quiesce-*.jsonl')
    rows = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert [row['event'] for row in rows] == ['failed']


@pytest.mark.parametrize('failure', ['instance', 'anchor', 'sourcehash'])
def test_unchanged_identity_failure_keeps_owner_paused_without_retry(anchor_session, monkeypatch, failure):
    f = anchor_session
    def fail(*args):
        assert not f.qmp.running
        raise ValueError('original ' + failure + ' mismatch')
    if failure == 'instance':
        monkeypatch.setitem(API['DEV'], 'bind_instance', fail)
    elif failure == 'anchor':
        f.obj.tx._check_anchor = fail
    else:
        rows = copy.deepcopy(API['SOURCE_BINDINGS'])
        rows[0]['sha256'] = '0' * 64
        monkeypatch.setitem(G, 'SOURCE_BINDINGS', rows)
    with pytest.raises(ValueError):
        f.obj.unchanged()
    assert not f.qmp.running and f.peer.owner.poll() is None and not f.obj.closed
    assert f.qmp.events.count('stop') == 1 and 'cont' not in f.qmp.events and 'quit' not in f.qmp.events
    assert f.obj.tx.children == [f.peer.owner]
    evidence, = f.obj.output.glob('anchor-identity-quiesce-*.jsonl')
    rows = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert rows[-1]['event'] == 'failed' and not any(row['event'] == 'completed' for row in rows)


@pytest.mark.parametrize('changed', ['runtime', 'workspace', 'instance_identity', 'routes', 'capability'])
def test_unchanged_retains_context_and_capability_refusal_before_qmp(anchor_session, changed):
    f = anchor_session
    if changed == 'capability':
        f.cap['host_only'] = False
    else:
        f.current[changed] = 'changed'
    with pytest.raises(ValueError, match='[Cc]ontext changed|capability changed'):
        f.obj.unchanged()
    assert f.qmp.events == [] and f.qmp.samples == [] and f.qmp.running
    assert not list(f.obj.output.glob('anchor-identity-quiesce-*.jsonl'))


@pytest.mark.parametrize('latest', ['shooting', 'off', 'prefixed-off', 'menu', 'warning', 'unknown', 'malformed', 'partial', 'off-after-diag',
                                  'pause-failure', 'construct-failure', 'resume-failure', 'auth-failure'])
def test_start_registers_original_popen_before_ready_without_migration(session, monkeypatch, latest):
    obj, tx = session.obj, session.tx
    source = obj.owner
    tx.children.clear()
    disk = session.output / 'host-disk'
    disk.write_bytes(b'host fixture')
    disk.chmod(0o600)
    tx.fd = os.open(disk, os.O_RDWR)
    tx.pass_fds = (tx.fd,)
    tx._leased = dict(path=session.output)
    obj.private = dict(host_only=True)
    obj.cold = dict(source='official-bodydata-derived')
    obj.launch.update(instance=str(session.output), command=['host-fixture-not-executed'], env={},
                      template_inputs=[], launch_inputs=[], qmp_socket='host-only', cmdline='host-only')
    obj.log.unlink()
    monkeypatch.setitem(API['R'], 'metadata', lambda *a: obj.private)
    monkeypatch.setitem(API['P'], 'verify_firmware', lambda *a: None)
    monkeypatch.setitem(API['COLD'], 'recheck', lambda *a: None)
    def popen(command, **kw):
        assert command == ['host-fixture-not-executed'] and kw['pass_fds'] == tx.pass_fds
        assert kw['env']['PERSISTENT_DISK_FD'] == str(tx.fd)
        assert not tx.children
        session.events.append('source-popen')
        initial = b'' if latest == 'unknown' else page_line('shooting')
        extra = b'' if latest in ('shooting', 'off-after-diag', 'pause-failure', 'construct-failure', 'resume-failure', 'auth-failure') else page_line(latest)
        kw['stdout'].write(initial+extra)
        return source
    monkeypatch.setattr(API['subprocess'], 'Popen', popen)
    monkeypatch.setitem(API['E'], 'qmp_connect', lambda *a, **kw: (io.BytesIO(), io.BytesIO(), None))
    def startup_qmp(command, arguments=None):
        if latest == 'resume-failure' and command == 'cont':
            session.events.append('cont')
            raise RuntimeError('original source resume failed')
        response = session.qmp(command, arguments)
        if latest == 'pause-failure' and command == 'query-status' and not session.qmp.running:
            return dict(status='running', running=True)
        return response
    monkeypatch.setitem(API['C']['R'], 'FDQMP', lambda *a: startup_qmp if latest.endswith('-failure') else session.qmp)
    def shell(owner, log, script, phase, token):
        assert session.qmp.running, 'Constructor must resume before ready shell'
        session.events.append('shell-'+phase)
        if phase == 'diag':
            if latest == 'off-after-diag':
                with log.open('ab') as stream:
                    stream.write(page_line('off'))
            return ''
        return RFIX['state_text']('source', token).replace('=source', '=ready')
    monkeypatch.setitem(API['R'], 'shell', shell)
    monkeypatch.setitem(API['R'], 'retain_cold_proof', lambda *a: session.output / 'host-proof')
    monkeypatch.setitem(API['E'], 'collect', lambda *a: dict(ap_verified=True, cold_guest_chain_verified=True))
    execution = obj.execution
    def construct(transaction, launch, owner, qmp, **kw):
        assert transaction is tx and tx.children == [source]
        session.qmp.check_identity()
        session.events.append('construct-owned-execution')
        if latest == 'construct-failure':
            raise RuntimeError('original source constructor failed')
        return execution
    monkeypatch.setitem(API['C'], 'CameraExecution', construct)
    if latest == 'auth-failure':
        def refused(tx_arg, owner, qmp):
            assert tx_arg is tx and owner is source
            raise ValueError('QMP is not owned: original source peer refused')
        monkeypatch.setitem(API['R'], 'authenticate_owner', refused)
        monkeypatch.setitem(API['R']['paused'].__wrapped__.__globals__, 'authenticate_owner', refused)
    try:
        if latest.endswith('-failure'):
            with pytest.raises((ValueError, RuntimeError)):
                obj.start(1)
            assert tx.children == [source] and source.poll() is None
            assert session.qmp.running is (latest == 'auth-failure')
            assert not obj.closed and not obj.used
            assert 'capture-existing-source' not in session.events and 'normal-close' not in session.events
            assert 'shell-ready' not in session.events and not (session.output / 'source-ready.json').exists()
            assert session.events.count('cont') == (1 if latest == 'resume-failure' else 0)
            rows = [json.loads(line) for line in (session.output / 'source-constructor-quiesce.jsonl').read_text().splitlines()]
            assert rows[-1]['event'] == 'failed'
            if latest == 'auth-failure':
                assert [row['event'] for row in rows] == ['failed']
                assert not {'query-status', 'stop', 'cont', 'quit'}.intersection(session.events)
            obj.close()
            assert source.poll() == 0
            return
        assert obj.start(1) is (latest == 'shooting')
        assert tx.children == [source] and source.poll() is None
        assert session.events.index('source-popen') < session.events.index('stop') < session.events.index('construct-owned-execution')
        assert session.events.index('construct-owned-execution') < session.events.index('cont') < session.events.index('shell-ready')
        assert session.qmp.samples and all(not row['running'] and row['before'] == row['after'] for row in session.qmp.samples)
        assert 'capture-existing-source' not in session.events and 'normal-close' not in session.events
        assert not (session.output / 'live-owner.json').exists()
        if latest == 'shooting':
            ready = API['DEV']['read_json'](session.output / 'source-ready.json')
            assert ready['ui_hot_enabled'] is False and ready['current_page']['original_shooting_main'] is True
        else:
            assert not (session.output / 'source-ready.json').exists()
            refusal, = session.output.glob('source-unready-*.json')
            row = API['DEV']['read_json'](refusal)
            assert row['status'] == 'source-unready' and row['state']['live_owner_pids'] == [101]
            assert row['current_page']['original_shooting_main'] is False
            assert row['current_page']['source_console']['sha256'] == hashlib.sha256(obj.log.read_bytes()).hexdigest()
            assert row['lease_retained_until_owner_exit'] and not row['actual_content_verified']
        assert not obj.used and not obj.closed
        obj.close()
    finally:
        os.close(tx.fd)


@pytest.mark.parametrize('page', ['off', 'prefixed-off', 'menu', 'warning', 'unknown', 'malformed', 'partial'])
def test_hot_current_page_refusal_precedes_used_latch_and_preserves_owner(session, page):
    obj = session.obj
    raw = (b'' if page == 'unknown' else page_line('shooting'))+page_line(page)
    obj.log.write_bytes(raw)
    for _ in range(2):
        with pytest.raises(ValueError, match='Source unready'):
            obj.hot()
    assert not obj.used and not obj.closed and obj.owner.poll() is None
    assert 'capture-existing-source' not in session.events and 'normal-close' not in session.events
    assert obj.log.read_bytes() == raw and len(list(session.output.glob('source-unready-*.json'))) == 2
    assert not (session.output / 'hot-failure.json').exists()
    obj.close()


def test_unready_source_keeps_authenticated_typed_close_available(session):
    obj = session.obj
    obj.log.write_bytes(page_line('shooting')+page_line('off'))
    control = API['OwnerControl'](obj)
    row = API['binding'](session.output / 'live-owner.json')
    worker = threading.Thread(target=control.serve)
    worker.start()
    try:
        with pytest.raises(API['LiveRequestRefused'], match='Source unready') as refused:
            API['request'](row, obj.instance, 'hot')
        assert refused.value.state['live_owner_pids'] == [101]
        assert refused.value.state['hot_consumed'] is False and obj.owner.poll() is None
        assert not (session.output / 'source-ready.json').exists()
    finally:
        if not obj.closed:
            API['request'](row, obj.instance, 'close')
        worker.join(10)
        assert not worker.is_alive() and obj.closed and obj.owner.poll() == 0


def test_source_turning_off_during_state_read_is_rejected_before_capture(session, monkeypatch):
    obj = session.obj
    original = API['R']['shell']
    def shell(owner, log, script, phase, token):
        text = original(owner, log, script, phase, token)
        if phase == 'source':
            with log.open('ab') as stream:
                stream.write(page_line('off'))
        return text
    monkeypatch.setitem(API['R'], 'shell', shell)
    with pytest.raises(ValueError, match='Source unready before capture'):
        obj.hot()
    assert obj.used and obj.owner.poll() is None and 'capture-existing-source' not in session.events
    failure = API['DEV']['read_json'](session.output / 'hot-failure.json')
    assert failure['state']['phase'] == 'source-owned' and not failure['actual_content_verified']
    obj.close()


def test_hot_consumes_existing_owner_without_prepare_cold_or_new_transaction(session):
    response = session.obj.hot()
    assert response['state']['hot_consumed'] is True and response['state']['owner_pid'] == 201
    assert response['state']['phase'] == 'target-owned'
    assert response['state']['live_owner_pids'] == [201] and response['state']['capture_returned'] is True
    assert session.events.index('capture-existing-source') < session.events.index('restore-paused') < session.events.index('cont-verified-target')
    assert [owner.poll() for owner in session.tx.children] == [0, None]
    before = list(session.events)
    with pytest.raises(ValueError, match='exactly one'):
        session.obj.hot()
    assert session.events == before
    session.obj.close()
    assert [owner.poll() for owner in session.tx.children] == [0, 0]
    assert session.obj.state()['phase'] == 'closed'
    assert session.obj.state()['live_owner_pids'] == []
    assert session.obj.state()['owner_pid'] is None
    assert session.obj.state()['display'] == session.obj.state()['input'] == 'none'
    assert API['DEV']['read_json'](session.output / 'result.json')['capture_verified'] is False


def test_source_identity_change_after_ready_is_refused_before_capture(session):
    session.obj.ready_state['boot_id'] = 'not-the-running-source'
    with pytest.raises(ValueError, match='since ready'):
        session.obj.hot()
    assert session.obj.owner.poll() is None and 'capture-existing-source' not in session.events
    session.obj.close()


def test_failed_hot_keeps_owner_and_original_artifacts_until_typed_close(session, monkeypatch):
    original = (session.output / 'transaction/source-console.log').read_bytes()
    def fail(*a, **kw):
        session.qmp.check_identity()
        session.events.append('capture-failure')
        raise RuntimeError('original migration error')
    monkeypatch.setattr(session.obj.execution, 'capture', fail)
    with pytest.raises(RuntimeError, match='original migration error'):
        session.obj.hot()
    assert session.obj.owner.poll() is None and not session.obj.closed
    failure = API['DEV']['read_json'](session.output / 'hot-failure.json')
    assert failure['lease_retained_until_owner_exit'] is True and failure['vm_signals_sent'] == []
    assert failure['state']['phase'] == 'source-owned' and failure['state']['live_owner_pids'] == [101]
    assert failure['state']['capture_returned'] is False and 'normal-close' not in session.events
    assert not session.qmp.running and 'cont' not in session.events[session.events.index('capture-failure'):]
    transcript = [json.loads(line) for line in (session.output / 'source-capture-quiesce.jsonl').read_text().splitlines()]
    assert transcript[-1]['event'] == 'failed' and transcript[-1]['error'] == 'RuntimeError: original migration error'
    assert (session.output / 'transaction/source-console.log').read_bytes().startswith(original)
    with pytest.raises(ValueError, match='exactly one'):
        session.obj.hot()
    session.obj.close()
    assert session.obj.owner.poll() == 0
    assert API['DEV']['read_json'](session.output / 'result.json')['actual_content_verified'] is False


def test_capture_return_then_restore_failure_reports_exited_source(session, monkeypatch):
    def fail(**kwargs):
        assert session.obj.owner.poll() == 0
        assert session.obj.capture_returned is True
        raise RuntimeError('restore failed after source QMP quit')
    monkeypatch.setattr(session.obj.execution, 'restore', fail)
    with pytest.raises(RuntimeError, match='after source QMP quit'):
        session.obj.hot()
    state = API['DEV']['read_json'](session.output / 'hot-failure.json')['state']
    assert state['phase'] == 'captured-source-exited' and state['capture_returned'] is True
    assert state['live_owner_pids'] == [] and state['owner_pid'] is None
    assert state['display'] == state['input'] == 'none'
    assert (session.output / 'capture-result.json').exists()
    assert not session.obj.closed and 'normal-close' not in session.events
    assert not (session.output / 'result.json').exists()
    session.obj.close()


@pytest.mark.parametrize('selected', [False, True])
def test_restore_failure_keeps_all_registered_live_children_visible(session, monkeypatch, selected):
    target = RFIX['Owner'](201)
    def fail(**kwargs):
        session.tx.children.append(target)
        if selected:
            session.obj.execution.target = target
        raise RuntimeError('target admission failed')
    monkeypatch.setattr(session.obj.execution, 'restore', fail)
    with pytest.raises(RuntimeError, match='target admission failed'):
        session.obj.hot()
    state = API['DEV']['read_json'](session.output / 'hot-failure.json')['state']
    assert state['phase'] == ('target-owned' if selected else 'transition-owned')
    assert state['live_owner_pids'] == [201] and state['owner_pid'] == (201 if selected else None)
    if not selected:
        assert state['display'] == state['input'] == 'none'
    assert session.obj.owner.poll() == 0 and target.poll() is None
    assert not session.obj.closed and 'normal-close' not in session.events
    session.obj.close()


def test_state_uses_liveness_and_capture_return_instead_of_artifact_presence(session):
    obj = session.obj
    API['R']['save'](session.output / 'capture-result.json', dict(host_only=True))
    obj.owner.returncode = 0
    state = obj.state()
    assert state['phase'] == 'source-exited' and state['capture_returned'] is False
    assert state['live_owner_pids'] == [] and state['owner_pid'] is None
    assert state['display'] == state['input'] == 'none'
    obj.execution.target = RFIX['Owner'](201)
    assert obj.state()['live_owner_pids'] == [201]  # Selected owner is polled even before registration.
    obj.execution.target.returncode = 7
    extra = RFIX['Owner'](301)
    session.tx.children.append(extra)
    assert obj.state()['phase'] == 'transition-owned' and obj.state()['live_owner_pids'] == [301]
    obj.closed = True
    assert obj.state()['phase'] == 'transition-owned' and obj.state()['owner_pid'] is None
    extra.returncode = 0
    assert obj.state()['phase'] == 'closed' and obj.state()['live_owner_pids'] == []


@pytest.mark.parametrize('exited', [False, True])
def test_failed_close_reports_current_liveness_without_retry(session, monkeypatch, exited):
    obj = session.obj
    obj.hot()
    close = obj.execution.close
    def fail():
        session.events.append('original-close-error')
        if exited:
            for child in session.tx.children:
                child.returncode = 0
        raise RuntimeError('original close error')
    monkeypatch.setattr(obj.execution, 'close', fail)
    with pytest.raises(RuntimeError, match='original close error'):
        obj.close()
    assert not obj.closed and session.events.count('original-close-error') == 1
    failure, = session.output.glob('owner-retained-*.json')
    row = API['DEV']['read_json'](failure)
    assert row['state']['phase'] == ('target-exited' if exited else 'target-owned')
    assert row['live_owner_pids'] == row['state']['live_owner_pids'] == ([] if exited else [201])
    assert row['lease_retained_until_owner_exit'] is True and 'normal-close' not in session.events
    if exited:
        assert row['state']['owner_pid'] is None and row['state']['display'] == row['state']['input'] == 'none'
    monkeypatch.setattr(obj.execution, 'close', close)
    obj.close()


@pytest.mark.parametrize('prefix, expected', [(b'/ # ', True), (b'camera# ', False)])
def test_latest_shooting_accepts_only_the_known_busybox_prompt(session, prefix, expected):
    session.obj.log.write_bytes(prefix+page_line('shooting'))
    ready, page = session.obj.shooting_source('fixture')
    assert ready is expected and page['original_shooting_main'] is expected


def test_live_source_bindings_pin_the_boot_request_adapter():
    row, = [row for row in API['SOURCE_BINDINGS'] if Path(row['path']) == HERE / 'firmware-boot-request.py']
    assert row['sha256'] == hashlib.sha256((HERE / 'firmware-boot-request.py').read_bytes()).hexdigest()


@pytest.fixture
def content_fixture():
    # Existing synthetic sequence evidence, transformed only for this live API's
    # authenticated parent contract. This is not a saved/loadable real VM.
    case = BFIX['SequenceRequestTests']('test_sequence_dispatch_and_all_content_stages_host_contract_only')
    case.setUp()
    try:
        output = case.job / 'retained'
        result = case.run_retained(case.runtime / 'analysis', case.cold_path, output,
                                   combo_manifest=case.combo_path, origin_qemu_build=case.build_dir)
        stream = output / 'transaction/snapshot.partial'
        stream.write_bytes(b'QEVM\0\0\0\3host fixture, never real RAM')
        with stream.open('rb') as f:
            record = API['DS']['_record'](f.fileno())
        for name in ('capture-result.json', 'restore-paused-result.json', 'transaction/restore-paused.json',
                     'transaction/continued.json', 'normal-close.json', 'transaction/execution-closed.json'):
            path = output / name
            value = API['DEV']['read_json'](path)
            value.update(snapshot_sha256=hashlib.sha256(stream.read_bytes()).hexdigest(),
                         snapshot_bytes=stream.stat().st_size, snapshot_file_record=record)
            API['DEV']['write_json'](path, value)
        upgrade_fixture(API, output, result, RFIX)
        result.update(schema=API['SCHEMA'], instance_identity=case.identity, controller_identity=API['process'](os.getpid()),
                      source_bindings=API['SOURCE_BINDINGS'], hot_consumed=True,
                      closed=API['DEV']['read_json'](output / 'normal-close.json'), **API['LIMITS'])
        API['DEV']['write_json'](output / 'result.json', result)
        yield SimpleNamespace(output=output, instance=case.identity, controller=API['process'](os.getpid()), case=case)
    finally:
        case.doCleanups()


def test_offline_live_content_review_uses_real_parsers_on_synthetic_host_evidence(content_fixture):
    fixture = content_fixture
    reviewed = API['verify_result'](API['binding'](fixture.output / 'result.json'), fixture.instance, fixture.controller)
    assert reviewed['actual_content_verified'] is True  # Synthetic parser outcome only.
    assert reviewed['owners_closed'] is True and reviewed['capture_verified'] is False
    assert not reviewed['gui_owner_switch_verified']


@pytest.mark.parametrize('later_gui', [False, True])
def test_offline_review_anchors_executed_markers_and_bounds_later_gui(content_fixture, later_gui):
    fixture = content_fixture
    result = API['DEV']['read_json'](fixture.output / 'result.json')
    token = result['source_run'].removeprefix('retained-source-')
    log = fixture.output / 'transaction/target/console.log'
    echoes = ''.join(f"> echo 'RETAINED_DONE_{phase}={token}'\n" for phase in ('menu', 'shooting')).encode()
    suffix = RFIX['input_text']('menu').encode() if later_gui else b''
    log.write_bytes(log.read_bytes() + echoes + suffix)
    reviewed = API['verify_result'](API['binding'](fixture.output / 'result.json'), fixture.instance, fixture.controller)
    assert reviewed['actual_content_verified'] is True  # Host fixture, not original AP acceptance.
    log.write_bytes(log.read_bytes() + f'RETAINED_DONE_shooting={token}\n'.encode())
    with pytest.raises(ValueError, match='[Ss]tate receipt'):
        API['verify_result'](API['binding'](fixture.output / 'result.json'), fixture.instance, fixture.controller)


@pytest.mark.parametrize('damage', ['parent', 'phase', 'close', 'state', 'stream', 'stream_inode', 'input', 'old_pixels'])
def test_offline_review_rejects_tampered_content(content_fixture, damage):
    fixture = content_fixture
    if damage in ('stream', 'stream_inode'):
        path = fixture.output / 'transaction/snapshot.partial'
        if damage == 'stream':
            path.write_bytes(b'QEVM\0\0\0\3corrupt')
        else:
            raw = path.read_bytes()
            path.rename(path.with_name('saved-stream'))
            path.write_bytes(raw)
            path.chmod(0o600)
    elif damage == 'old_pixels':
        (fixture.output / 'transaction/target/menu.ppm').write_bytes((fixture.output / 'transaction/target/shooting.ppm').read_bytes())
    elif damage == 'input':
        path = fixture.output / 'transaction/target/console.log'
        path.write_bytes(path.read_bytes().replace(b'FULL_INPUT_FREE_ENTER', b'FULL_INPUT_BAD_RETURN'))
    else:
        relative = {'parent': 'transaction/disk-binding.json', 'phase': 'transaction/disk-post-restore.json',
                    'close': 'normal-close.json', 'state': 'menu-state.json'}[damage]
        path = fixture.output / relative
        value = API['DEV']['read_json'](path)
        if damage == 'parent':
            value['transaction']['parent_pid'] += 1
        elif damage == 'phase':
            value['qmp'][0]['response']['status'] = 'running'
        elif damage == 'close':
            value['owners'][1]['signals_sent'] = ['SIGTERM']
        else:
            value['canary'] = 'b' * 32
        API['DEV']['write_json'](path, value)
    with pytest.raises((ValueError, KeyError)):
        API['verify_result'](API['binding'](fixture.output / 'result.json'), fixture.instance, fixture.controller)


def test_frozen_execution_and_disk_phase_machine_are_reused_without_reset():
    source = (HERE / 'retained-camera-live.py').read_text()
    for forbidden in ('._next_phase =', '._binding =', '._failed =', 'send_signal(', '.terminate(', '.kill('):
        assert forbidden not in source
    assert "C['CameraExecution']" in source and "DS['transaction']" in source


def test_live_hot_checks_anchor_and_captures_only_after_actual_qmp_pause(session, monkeypatch):
    def unchanged():
        session.qmp.check_identity()
        session.events.append('check-current-context')
    monkeypatch.setattr(session.obj, 'unchanged', unchanged)
    session.obj.hot()
    assert all(not row['running'] and row['before'] == row['after'] for row in session.qmp.samples)
    events = session.events
    sync, capture = events.index('guest-sync'), events.index('capture-existing-source')
    assert events.index('preauth') < events.index('query-status') < events.index('stop')
    assert sync < events.index('preauth', sync) < events.index('stop', sync) < capture
    transcript = [json.loads(line) for line in (session.output / 'source-capture-quiesce.jsonl').read_text().splitlines()]
    assert [row['command'] for row in transcript if row['event'] == 'response'] == ['query-status', 'stop', 'query-status']
    assert not session.qmp.running  # Source is retired; only the restored target is resumed.
    session.obj.close()


@pytest.mark.parametrize('failure', ['sync', 'pause', 'anchor'])
def test_live_hot_quiesce_failure_retains_original_owner_without_capture_or_auto_resume(session, monkeypatch, failure):
    obj = session.obj
    if failure == 'sync':
        def wait(*args):
            raise TimeoutError('original guest sync failed')
        monkeypatch.setitem(API['R'], 'wait_for', wait)
    elif failure == 'anchor':
        def unchanged():
            session.qmp.check_identity()
            raise ValueError('original anchor mismatch')
        monkeypatch.setattr(obj, 'unchanged', unchanged)
    else:
        original = session.qmp.__call__
        def qmp(command, arguments=None):
            response = original(command, arguments)
            if command == 'query-status' and not session.qmp.running:
                return dict(status='running', running=True)
            return response
        obj.qmp = qmp
    with pytest.raises((ValueError, TimeoutError)):
        obj.hot()
    row = API['DEV']['read_json'](session.output / 'hot-failure.json')
    assert row['state']['live_owner_pids'] == [101] and row['state']['phase'] == 'source-owned'
    assert obj.owner.poll() is None and not obj.capture_returned and not obj.closed
    assert 'capture-existing-source' not in session.events and 'normal-close' not in session.events
    assert session.qmp.running is (failure == 'sync')
    if failure != 'sync':
        assert 'cont' not in session.events
    obj.close()


def test_live_running_rejects_unregistered_owner_before_first_qmp(session, monkeypatch):
    obj = session.obj
    monkeypatch.setitem(API['R'], 'authenticate_owner', RFIX['API']['authenticate_owner'])
    session.tx.children.clear()
    try:
        with pytest.raises(ValueError, match='not owned'):
            obj.running(obj.owner, obj.qmp)
        assert session.events == [] and session.qmp.running and obj.owner.poll() is None
    finally:
        session.tx.children.append(obj.owner)
        obj.close()


def test_live_capture_reauthenticates_after_guest_sync_before_any_new_qmp(session, monkeypatch):
    original = API['R']['paused'].__wrapped__.__globals__['authenticate_owner']
    def authenticate_owner(tx, owner, qmp):
        assert tx is session.tx and owner is session.obj.owner and qmp is session.qmp
        if 'guest-sync' in session.events:
            raise ValueError('QMP is not owned: capture peer changed after sync')
        return original(tx, owner, qmp)
    monkeypatch.setitem(API['R']['paused'].__wrapped__.__globals__, 'authenticate_owner', authenticate_owner)
    with pytest.raises(ValueError, match='capture peer changed'):
        session.obj.hot()
    sync = session.events.index('guest-sync')
    assert not {'query-status', 'stop', 'cont', 'quit', 'capture-existing-source'}.intersection(session.events[sync:])
    assert session.qmp.running and session.obj.owner.poll() is None and not session.obj.closed
    rows = [json.loads(line) for line in (session.output/'source-capture-quiesce.jsonl').read_text().splitlines()]
    assert [row['event'] for row in rows] == ['failed']
    session.obj.close()


def active_host_owner(pipe, stopped):
    """Two ordinary Python host processes; never QEMU or a guest."""
    child = multiprocessing.get_context('fork').Process(target=stopped.wait)
    child.start()
    pipe.send(child.pid)
    pipe.close()
    stopped.wait()
    child.join(10)
    assert child.exitcode == 0


@pytest.fixture
def active_content(content_fixture):
    f = content_fixture
    fd = os.open(f.case.disk, os.O_RDWR)
    stopped = multiprocessing.get_context('fork').Event()
    receive, send = multiprocessing.Pipe(duplex=False)
    owner = multiprocessing.get_context('fork').Process(target=active_host_owner, args=(send, stopped))
    owner.start()
    send.close()
    assert receive.poll(10)
    peer_pid = receive.recv()
    receive.close()
    control = None
    try:
        def load(name):
            return API['DEV']['read_json'](f.output / name)
        def save(name, value):
            API['DEV']['write_json'](f.output / name, value)
        disk = load('transaction/disk-binding.json')
        disk['transaction']['fd'] = fd
        save('transaction/disk-binding.json', disk)
        digest = API['C']['R']['_digest'](disk)
        for phase in API['DS']['PHASES']:
            name = 'transaction/disk-' + phase + '.json'
            value = load(name)
            value['binding_sha256'] = digest
            save(name, value)
        for name in ('capture-result.json', 'restore-paused-result.json', 'transaction/restore-paused.json',
                     'transaction/continued.json', 'normal-close.json', 'transaction/execution-closed.json'):
            value = load(name)
            value['disk_binding_sha256'] = digest
            value['source_identity']['environment']['QEMU_A7PF_FD'] = str(fd)
            if 'target_identity' in value:
                target = value['target_identity']
                target.update(owner=API['process'](owner.pid), peer=API['process'](peer_pid))
                target['environment']['QEMU_A7PF_FD'] = str(fd)
                target['qmp_name'] = dict(name=value['target_run'])
            if name in ('normal-close.json', 'transaction/execution-closed.json'):
                value['owners'][1]['pid'] = owner.pid
            save(name, value)
        admission = load('transaction/target-admission.json')
        admission.update(transaction=disk['transaction'], disk_binding_sha256=digest,
                         snapshot_sha256=load('transaction/continued.json')['snapshot_sha256'])
        save('transaction/target-admission.json', admission)
        result = load('result.json')
        for phase in ('restored', 'menu', 'shooting'):
            name = phase + '-state-transport.json'
            receipt = load(name)
            receipt['owner_pid'] = owner.pid
            save(name, receipt)
            result['state_transports'][phase] = API['binding'](f.output / name)
        result.update(status='restored-live', owners_closed=False)
        result.pop('closed')
        save('hot-result.json', result)
        closed_result = dict(result, status='passed', owners_closed=True, closed=load('normal-close.json'))
        for name in ('result.json', 'normal-close.json', 'transaction/execution-closed.json'):
            (f.output / name).unlink()
        host = HostSession(f.output)
        host.instance = f.instance
        control = API['OwnerControl'](host, object())
        descriptor = control.descriptor
        state = dict(phase='target-owned', owner_pid=owner.pid, live_owner_pids=[owner.pid], capture_returned=True,
                     controller_pid=os.getpid(), hot_consumed=True, gui_owner_switch_verified=False,
                     display='QMP at target', input='owned target stdin')
        frontend = f.output / 'frontend'
        frontend.mkdir(mode=0o700)
        (frontend / 'input').mkdir(mode=0o700)
        frame = frontend / 'live-frame.ppm'
        frame.write_bytes((f.output / 'transaction/target/shooting.ppm').read_bytes())
        frame.chmod(0o600)
        status = dict(phase='target-running', error='', frame=str(frame), input_dir=str(frontend / 'input'),
                      source_directory=str(f.output / 'transaction/target'), owner_pid=owner.pid,
                      state=state, pixels_sha256=result['frames']['shooting']['pixels_sha256'], gui_owner_switch_verified=False)
        save('frontend/status.json', status)
        save('frontend-hot.json', dict(owner_pid=owner.pid, input_owner_pid=owner.pid,
            source_directory=str(f.output / 'transaction/target'), source_log=str(f.output / 'transaction/target/console.log'),
            frame=str(frame), input_dir=str(frontend / 'input'), status=status))
        response = dict(schema=API['SCHEMA'], status='completed', controller_identity=descriptor['controller_identity'],
            request=dict(schema=API['SCHEMA'], action='hot', nonce=descriptor['nonce'], instance_identity=f.instance,
                socket_identity=descriptor['socket_identity'], client_identity=API['process'](os.getpid()), frontend_enabled=True),
            result=dict(artifact=API['binding'](f.output / 'hot-result.json'),
                        state=dict(state, frontend=API['binding'](f.output / 'frontend-hot.json'))))
        yield SimpleNamespace(**vars(f), response=response, owner=owner, peer_pid=peer_pid, stopped=stopped, fd=fd,
                              owner_binding=API['binding'](f.output / 'live-owner.json'), closed_result=closed_result)
    finally:
        if control is not None:
            control.close_socket()
        stopped.set()
        owner.join(10)
        assert owner.exitcode == 0
        owner.close()
        os.close(fd)


def test_active_host_content_then_normal_close_keeps_closed_default_strict(active_content):
    f = active_content
    reviewed = API['verify_active_result'](f.owner_binding, f.instance, f.response)
    assert reviewed['lifecycle'] == 'live-target-owned' and reviewed['runtime_transport_verified']
    assert reviewed['actual_content_verified'] and not reviewed['owners_closed']
    assert reviewed['lease_retained_until_owner_exit'] and not reviewed['gui_owner_switch_verified']
    assert f.owner.is_alive() and not (f.output / 'normal-close.json').exists()
    with pytest.raises(ValueError):
        API['verify_result'](f.response['result']['artifact'], f.instance, f.controller)
    closed = f.closed_result['closed']
    for name, data in (('normal-close.json', closed), ('transaction/execution-closed.json', closed),
                       ('result.json', f.closed_result)):
        API['DEV']['write_json'](f.output / name, data)
    with pytest.raises(ValueError, match='still alive'):
        API['verify_result'](API['binding'](f.output / 'result.json'), f.instance, f.controller)
    f.stopped.set()
    f.owner.join(10)
    assert f.owner.exitcode == 0
    assert API['verify_result'](API['binding'](f.output / 'result.json'), f.instance, f.controller)['owners_closed']


@pytest.mark.parametrize('damage', ['owner', 'pid-reuse', 'uid', 'stream', 'inode', 'sourcehash', 'disk', 'oldframe',
    'promise', 'messagefree', 'status', 'selected-input', 'descriptor', 'response-state', 'admission', 'lease-fd'])
def test_active_host_content_rejects_tampering_without_owner_close(active_content, damage):
    f = active_content
    def change(name, mutate):
        path = f.output / name
        row = API['DEV']['read_json'](path)
        mutate(row)
        API['DEV']['write_json'](path, row)
    if damage in ('owner', 'pid-reuse', 'uid'):
        field = {'owner': 'pid', 'pid-reuse': 'start_ticks', 'uid': 'uid'}[damage]
        for name in ('restore-paused-result.json', 'transaction/continued.json'):
            change(name, lambda row: row['target_identity']['owner'].__setitem__(field,
                row['target_identity']['owner'][field] + 1))
    elif damage in ('stream', 'inode'):
        path = f.output / 'transaction/snapshot.partial'
        if damage == 'stream':
            path.write_bytes(b'corrupt RAM stream')
        else:
            raw = path.read_bytes()
            path.rename(path.with_name('original-stream'))
            path.write_bytes(raw)
            path.chmod(0o600)
    elif damage in ('sourcehash', 'promise'):
        def mutate(row):
            if damage == 'sourcehash':
                row['source_bindings'][0]['sha256'] = '0' * 64
            else:
                row['gui_owner_switch_verified'] = True
        change('hot-result.json', mutate)
        f.response['result']['artifact'] = API['binding'](f.output / 'hot-result.json')
    elif damage == 'disk':
        change('transaction/disk-post-restore.json', lambda row: row['qmp'][0]['response'].__setitem__('running', True))
    elif damage == 'oldframe':
        (f.output / 'transaction/target/menu.ppm').write_bytes((f.output / 'transaction/target/shooting.ppm').read_bytes())
    elif damage == 'messagefree':
        path = f.output / 'transaction/target/console.log'
        path.write_bytes(path.read_bytes().replace(b'FULL_INPUT_FREE_ENTER', b'FULL_INPUT_FALSE_FREE'))
    elif damage == 'status':
        change('frontend/status.json', lambda row: row.__setitem__('phase', 'source-running'))
    elif damage == 'selected-input':
        change('frontend-hot.json', lambda row: row.__setitem__('input_owner_pid', row['input_owner_pid'] + 1))
        f.response['result']['state']['frontend'] = API['binding'](f.output / 'frontend-hot.json')
    elif damage == 'descriptor':
        change('live-owner.json', lambda row: row.__setitem__('frontend_enabled', False))
        f.owner_binding = API['binding'](f.output / 'live-owner.json')
    elif damage == 'response-state':
        f.response['result']['state']['phase'] = 'closed'
    elif damage == 'admission':
        change('transaction/target-admission.json', lambda row: row['transaction'].__setitem__('token', '0' * 64))
    else:
        change('transaction/disk-binding.json', lambda row: row['transaction'].__setitem__('fd', 2147483647))
    with pytest.raises((ValueError, FileNotFoundError)):
        API['verify_active_result'](f.owner_binding, f.instance, f.response)
    assert f.owner.is_alive() and not (f.output / 'normal-close.json').exists()


@pytest.mark.parametrize('bad_frame', [False, True])
def test_panel_frontend_hot_real_active_verifier_never_typed_closes(active_content, monkeypatch, bad_frame):
    f, calls = active_content, []
    boot, case = BFIX['API'], active_content.case
    dev = boot['DEV']
    case.request.update(action='hot', target='hot', boot_profile='qemu-live-retained-roundtrip',
                        required_stages=list(dev['STAGES']['hot']))
    case.save_request()
    def request(owner, instance, action):
        calls.append(action)
        assert owner == f.owner_binding and instance == f.instance and action == 'hot'
        return f.response
    monkeypatch.setitem(dev, 'hot_capability', lambda *a: dict(live_owner=f.owner_binding))
    monkeypatch.setitem(dev, 'live_module', lambda: SimpleNamespace(**dict(API, request=request)))
    snapshots = case.job / 'stage-evidence'
    snapshots.mkdir(mode=0o700)
    result = dict(stages={})
    if bad_frame:
        (f.output / 'transaction/target/menu.ppm').write_bytes(b'bad actual frame')
        with pytest.raises(ValueError):
            boot['execute_hot'](case.job, case.request, case.context, snapshots, result)
        assert result['owner_retained'] and result['owner_state_confirmed']
        assert result['live_state'] == f.response['result']['state']
        assert (snapshots / 'live-active-review-error.json').exists()
    else:
        boot['execute_hot'](case.job, case.request, case.context, snapshots, result)
        assert result['status'] == 'completed' and result['lifecycle'] == 'live-target-owned'
        assert not result['owners_closed'] and result['runtime_transport_verified']
        assert not result['gui_owner_switch_verified']
        for stage in dev['STAGES']['hot']:
            row = dev['read_json'](result['stages'][stage]['path'])
            assert row['lifecycle'] == 'live-target-owned' and row['live_review']['actual_content_verified']
            assert not row['owners_closed'] and row['lease_retained_until_owner_exit']
    assert calls == ['hot'] and f.owner.is_alive()
    assert not (snapshots / 'live-close-response.json').exists()
