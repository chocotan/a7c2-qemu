import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
SPEC = importlib.util.spec_from_file_location('hdmi_observed_runner', HERE / 'run-hdmi-observed.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
LEAF_SPEC = importlib.util.spec_from_file_location('graph_leaf_runner', HERE / 'run-last-graph.py')
LEAF = importlib.util.module_from_spec(LEAF_SPEC)
LEAF_SPEC.loader.exec_module(LEAF)


def test_leaf_rejects_unknown_before_any_launch(monkeypatch):
    monkeypatch.setattr(LEAF.sys, 'argv', ['leaf', 'unknown'])
    with pytest.raises(ValueError):
        LEAF.main()


@pytest.mark.parametrize('arguments,target', [([], 'hdmi'), (['--all'], 'all'), (['--cp-audit'], 'cp-audit'), (['--cp302c'], 'cp302c'), (['--cp302c-diagnostic'], 'cp302c-diagnostic'), (['--cp-notification'], 'cp-notification'), (['--cp-capture-format'], 'cp-capture-format'), (['--cp-startup-controls'], 'cp-startup-controls'), (['--cp-ee-controls'], 'cp-ee-controls'), (['--cp-movie-format'], 'cp-movie-format')])
def test_main_routes_only_fixed_owned_experiment(arguments, target, monkeypatch):
    calls = []
    class Child:
        stdout = []
        def wait(self): return 17
    def launch(command, **kwargs):
        calls.append(command)
        assert command == ['python3', '-B', str(M.BASE / 'scratch/run-last-graph.py'), target]
        assert kwargs['cwd'] == M.BASE
        return Child()
    monkeypatch.setattr(M.sys, 'argv', ['observed', *arguments])
    monkeypatch.setattr(M.subprocess, 'Popen', launch)
    assert M.main() == 17 and len(calls) == 1
    monkeypatch.setattr(M.sys, 'argv', ['observed', '--unknown'])
    with pytest.raises(ValueError):
        M.main()
    assert len(calls) == 1


@pytest.mark.parametrize('startup_failure', [False, True])
@pytest.mark.parametrize('scope_profile', [None, 'qemu-readonly-scope-v1', 'qemu-readonly-scope-v2', 'qemu-readonly-scope-v3'])
def test_coordinator_waits_for_mailbox_delivery_and_retains_unsafe_start(tmp_path, monkeypatch, startup_failure, scope_profile):
    scope_enabled = scope_profile is not None
    (tmp_path / 'console.log').write_text('OBS FULL_HDMI_UPM_MAILBOX_INIT pid=258 physical=0x50d7ff000 nonce=0x123 upm_text=0xffffff800095b000 osal_text=0xffffff80004be000\n')
    manifest = {'host_control_owner_pid': 1234}
    receipt = tmp_path / 'scope-build.json'
    receipt.write_text(json.dumps({'schema': scope_profile or 'qemu-readonly-scope-v1'}))
    if scope_enabled:
        manifest['readonly_scope_observer'] = {
            'profile': scope_profile, 'build_receipt': str(receipt),
            'build_receipt_sha256': M.hdmi_upm_watch.hashlib.sha256(receipt.read_bytes()).hexdigest()}
    (tmp_path / 'runtime-manifest.json').write_text(json.dumps(manifest))
    class Finished:
        def is_set(self): return False
        def wait(self, timeout): return False
    class Process:
        pid = 777
        polls = 0
        delivered = 1
        def poll(self):
            self.polls += 1
            if self.polls >= 3:
                self.delivered = 2
                return 0
            return None
    class Watch:
        process = Process()
        config = {'running_QEMU_sha256': M.hdmi_upm_watch.READONLY_SCOPE_QEMU_SHA if scope_enabled else M.hdmi_upm_watch.QEMU_SHA,
                  'readonly_scope_observer': manifest.get('readonly_scope_observer')}
        def stop(self):
            assert self.process.delivered == 2, 'coordinator interrupted the second mailbox commit'
            return {'safe_to_close': True, 'detached': True}
    watcher = Watch()
    unsafe = {'safe_to_close': False, 'detached': False, 'debugger_stopped': False}
    calls = []
    def start(*args, **kwargs):
        calls.append((args, kwargs))
        assert args == (tmp_path, 1234, {'upm': 0xffffff800095b000, 'osal_uipc': 0xffffff80004be000})
        assert kwargs == {'mailbox': {'phys': 0x50d7ff000, 'nonce': 0x123, 'pid': 258},
                          'scope_build_receipt': str(receipt) if scope_enabled else None}
        if startup_failure:
            error = TimeoutError('startup timeout')
            error.hdmi_upm_watcher = watcher
            error.hdmi_upm_cleanup = unsafe
            raise error
        return watcher
    monkeypatch.setattr(M, 'gdbserver', lambda run: 'owned')
    monkeypatch.setattr(M.hdmi_upm_watch, 'start', start)
    monkeypatch.setattr(M.hdmi_upm_watch, 'read_receipts', lambda run: [{'published': 1}, {'published': 2}])
    monkeypatch.setattr(M.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('observe must use its single owned watcher'))
    result = {}
    M.observe(tmp_path, Finished(), result)
    assert len(calls) == 1
    saved = json.loads((tmp_path / 'hdmi-upm-coordinator.json').read_text())
    if startup_failure:
        assert result['retained_watcher'] is watcher and result['startup_cleanup'] is unsafe
        assert saved['retained_debugger_pid'] == 777 and saved['cleanup']['safe_to_close'] is False
    else:
        assert watcher.process.polls >= 3 and result['cleanup']['safe_to_close'] is True
        assert saved['running_QEMU_sha256'] == watcher.config['running_QEMU_sha256']
        assert saved['readonly_scope_observer'] == watcher.config['readonly_scope_observer']


@pytest.mark.parametrize('scope', [True, {}, {'profile': 'other', 'build_receipt': '/unbound'},
                                  {'profile': 'qemu-readonly-scope-v4', 'build_receipt': '/unbound'},
                                  {'profile': [], 'build_receipt': '/unbound'},
                                  {'profile': 'qemu-readonly-scope-v3', 'build_receipt': True},
                                  {'profile': 'qemu-readonly-scope-v1', 'build_receipt': True}])
def test_coordinator_records_bad_scope_binding_without_starting_a_debugger(tmp_path, monkeypatch, scope):
    (tmp_path / 'console.log').write_text('OBS FULL_HDMI_UPM_MAILBOX_INIT pid=258 physical=0x50d7ff000 nonce=0x123 upm_text=0xffffff800095b000 osal_text=0xffffff80004be000\n')
    (tmp_path / 'runtime-manifest.json').write_text(json.dumps({
        'host_control_owner_pid': 1234, 'readonly_scope_observer': scope}))
    finished = threading.Event()
    monkeypatch.setattr(M, 'gdbserver', lambda *args: pytest.fail('invalid scope must fail before GDB'))
    monkeypatch.setattr(M.hdmi_upm_watch, 'start', lambda *args, **kwargs: pytest.fail('unbound watcher'))
    result = {'armed': False, 'capture_verified': False}
    M.observe(tmp_path, finished, result)
    saved = json.loads((tmp_path / 'hdmi-upm-coordinator.json').read_text())
    assert saved['error'] == 'invalid manifest-bound scope observer receipt'
    assert saved['armed'] is False and saved['capture_verified'] is False


@pytest.mark.parametrize('bad', [False, True])
@pytest.mark.parametrize('long_path', [False, True])
def test_owned_qmp_listener_command_and_failure(tmp_path, bad, long_path):
    if long_path:
        tmp_path = tmp_path / ('long-camera-run-' * 12)
        tmp_path.mkdir()
    directory = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    short = f'/proc/self/fd/{directory}/'
    server = socket.socket(socket.AF_UNIX)
    server.bind(short + 'hdmi-upm-control.sock')
    server.listen(1)
    errors = []

    def serve():
        gdb = None
        try:
            client, _ = server.accept()
            with client, client.makefile('rwb') as stream:
                stream.write(b'{"QMP":{}}\n')
                stream.flush()
                first = json.loads(stream.readline())
                assert first == {'execute': 'qmp_capabilities', 'id': 1}
                stream.write(b'{"event":"RESUME"}\n{"id":1,"return":{}}\n')
                stream.flush()
                second = json.loads(stream.readline())
                assert second == {'execute': 'human-monitor-command', 'id': 2, 'arguments': {
                    'command-line': 'gdbserver unix:/out/' + M.hdmi_upm_watch.SOCKET + ',server=on,wait=off'}}
                if bad:
                    stream.write(b'{"id":2,"error":{"desc":"denied"}}\n')
                else:
                    gdb = socket.socket(socket.AF_UNIX)
                    gdb.bind(short + M.hdmi_upm_watch.SOCKET)
                    gdb.listen(1)
                    stream.write(b'{"id":2,"return":"started"}\n')
                stream.flush()
        except BaseException as error:
            errors.append(error)
        finally:
            if gdb is not None:
                gdb.close()
            server.close()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        if bad:
            with pytest.raises(ValueError, match='denied'):
                M.gdbserver(tmp_path)
        else:
            assert M.gdbserver(tmp_path) == 'started'
            assert (tmp_path / M.hdmi_upm_watch.SOCKET).stat().st_mode & 0o777 == 0o600
    finally:
        thread.join(timeout=5)
    os.close(directory)
    assert not thread.is_alive() and not errors
