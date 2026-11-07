from types import SimpleNamespace
import json,signal
from unittest.mock import patch
from host_sd_guard import guard_shutdown


def test_unsaved_host_parent_waits_without_quit_term_or_kill(tmp_path):
    events=[]
    proc=SimpleNamespace(poll=lambda:None,wait=lambda:events.append('observed VM exit'))
    with patch('host_sd_guard.signal.signal',side_effect=lambda n,h:events.append((n,h)) or signal.SIG_DFL):
        guard_shutdown(proc,tmp_path,False)
    assert events[2]=='observed VM exit'
    assert events[:2]==[(signal.SIGTERM,signal.SIG_IGN),(signal.SIGINT,signal.SIG_IGN)]
    assert events[-2:]==[(signal.SIGTERM,signal.SIG_DFL),(signal.SIGINT,signal.SIG_DFL)]
    result=json.loads((tmp_path/'host-sd-retained-owner.json').read_text())
    assert result['retain_parent_until_vm_exit'] and not result['force_kill_authorized']


def test_verified_or_independently_exited_vm_needs_no_retention(tmp_path):
    for verified,code in ((True,None),(False,0)):
        proc=SimpleNamespace(poll=lambda:code,wait=lambda:(_ for _ in ()).throw(AssertionError('unexpected wait')))
        guard_shutdown(proc,tmp_path,verified)
    assert not (tmp_path/'host-sd-retained-owner.json').exists()


def actual_log_harness(run, command, *, live_fd=False):
    import ast
    import copy
    from contextlib import ExitStack
    from pathlib import Path
    import hashlib
    import os
    import subprocess
    source = Path(__file__).with_name('qemu-menu-probe.py')
    tree = ast.parse(source.read_text())
    start = next(index for index, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                 and any(ast.unparse(target) == "manifest['qemu_log_streams']" for target in node.targets))
    block = next(node for node in tree.body[start + 1:] if isinstance(node, ast.With)
                 and any(isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == 'console'
                         for item in node.items))
    assert isinstance(block.body[0], ast.Assign)
    popen = block.body[0]
    assert ast.unparse(popen.value.func) == 'subprocess.Popen'
    cleanup = next(node for node in block.body if isinstance(node, ast.Try))
    final = [node for node in cleanup.finalbody if isinstance(node, ast.If)
             and ast.unparse(node.test) == 'not qemu_stderr.closed']
    assert len(final) == 1 and len(final[0].body) == 7
    body = [copy.deepcopy(popen)] + ast.parse("proc.wait(timeout=10)\ncurrent = json.loads((out / 'runtime-manifest.json').read_text())\ncurrent['later_runtime_state'] = 'preserved'\n(out / 'runtime-manifest.json').write_text(json.dumps(current))\n").body + copy.deepcopy(final)
    harness = ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(tree.body[start]),
        copy.deepcopy(tree.body[start + 1]), ast.With(items=copy.deepcopy(block.items), body=body)], type_ignores=[]))
    scope = dict(out=run, live_fd=live_fd, manifest={'files': {}}, command=command, subprocess=subprocess,
                 env=dict(os.environ), host_sd_fd=None, directory_sd_fd=None, ExitStack=ExitStack,
                 json=json, os=os, sha256_file=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
    return harness, scope, source


def test_actual_qemu_launch_keeps_interrupted_guest_line_and_host_diagnostics_separate(tmp_path):
    import sys
    from directory_snapshot import read_commit_status
    child = "import os; os.write(1,b'OBS HOST_TEST value='); os.write(2,b'qemu-system-aarch64: warning: vvfat: directory commit tracking ready\\nqemu-system-aarch64: warning: vvfat: host directory commit pending\\n'); os.write(1,b'23\\r\\n')"
    harness, scope, source = actual_log_harness(tmp_path, [sys.executable, '-c', child])
    exec(compile(harness, str(source), 'exec'), scope)
    assert scope['proc'].returncode == 0
    assert (tmp_path / 'console.log').read_bytes() == b'OBS HOST_TEST value=23\r\n'
    diagnostics = tmp_path / 'qemu-stderr.log'
    assert diagnostics.read_bytes() == b'qemu-system-aarch64: warning: vvfat: directory commit tracking ready\nqemu-system-aarch64: warning: vvfat: host directory commit pending\n'
    assert read_commit_status(diagnostics) == {'available': True, 'pending': True, 'closed_pending': False, 'transitions': 1}
    assert not read_commit_status(tmp_path / 'console.log')['available']
    manifest = json.loads((tmp_path / 'runtime-manifest.json').read_text())
    assert manifest['later_runtime_state'] == 'preserved'
    assert manifest['qemu_log_streams'] == dict(schema='qemu-separated-host-stderr-v1',
        guest_serial=str(tmp_path / 'console.log'), host_stderr=str(diagnostics), merged=False,
        host_stderr_bytes=diagnostics.stat().st_size, host_stderr_sha256=scope['sha256_file'](diagnostics))
    assert manifest['files'][str(diagnostics)] == scope['sha256_file'](diagnostics)
    assert scope['console'].closed and scope['qemu_stderr'].closed
    sealed = (tmp_path / 'runtime-manifest.json').read_bytes()
    import ast
    tree = ast.parse(source.read_bytes())
    repeated = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                    and ast.unparse(node.test) == 'not qemu_stderr.closed')
    exec(compile(ast.Module(body=[repeated], type_ignores=[]), str(source), 'exec'), scope)
    assert (tmp_path / 'runtime-manifest.json').read_bytes() == sealed


def test_actual_commit_callback_uses_host_stream_and_closed_failure_keeps_bytes(tmp_path):
    import ast
    from pathlib import Path
    import sys
    from directory_snapshot import read_commit_status
    guest = b'OBS HOST_TEST failure=0\r\n'
    diagnostics = b'vvfat: directory commit tracking ready\nvvfat: host directory commit pending\nvvfat: host directory commit complete\nstartup failed\n'
    command = [sys.executable, '-c', 'import os; os.write(1,' + repr(guest) + '); os.write(2,' + repr(diagnostics) + '); raise SystemExit(7)']
    harness, scope, source = actual_log_harness(tmp_path, command, live_fd=True)
    (tmp_path / 'console.log').write_bytes(b'HOST_TEST retained guest prefix\n')
    exec(compile(harness, str(source), 'exec'), scope)
    assert scope['proc'].returncode == 7
    assert (tmp_path / 'qemu-stderr.log').read_bytes() == diagnostics
    assert (tmp_path / 'console.log').read_bytes() == b'HOST_TEST retained guest prefix\n' + guest
    tree = ast.parse(source.read_bytes())
    callback = [node for node in ast.walk(tree) if isinstance(node, ast.Lambda)
                and isinstance(node.body, ast.Call) and isinstance(node.body.func, ast.Name)
                and node.body.func.id == 'read_commit_status']
    assert len(callback) == 1
    check = eval(compile(ast.Expression(callback[0]), str(source), 'eval'), dict(out=tmp_path, read_commit_status=read_commit_status))
    assert check() == {'available': True, 'pending': False, 'closed_pending': False, 'transitions': 2}
    assert json.loads((tmp_path / 'runtime-manifest.json').read_text())['qemu_log_streams']['host_stderr_sha256'] == scope['sha256_file'](tmp_path / 'qemu-stderr.log')


def test_actual_launch_refuses_old_host_log_and_retains_spawn_failure(tmp_path):
    from pathlib import Path
    import pytest
    for mode in ('stale', 'missing-executable'):
        run = tmp_path / mode
        run.mkdir()
        if mode == 'stale':
            (run / 'qemu-stderr.log').write_bytes(b'HOST_TEST old evidence')
        harness, scope, source = actual_log_harness(run, [str(run / 'missing-child')])
        with pytest.raises(FileExistsError if mode == 'stale' else FileNotFoundError):
            exec(compile(harness, str(source), 'exec'), scope)
        assert 'proc' not in scope
        assert (run / 'qemu-stderr.log').read_bytes() == (b'HOST_TEST old evidence' if mode == 'stale' else b'')
        assert scope['console'].closed
        if mode == 'missing-executable':
            assert scope['qemu_stderr'].closed
            assert json.loads((run / 'runtime-manifest.json').read_text())['qemu_log_streams']['merged'] is False


def test_actual_run_manifest_indexes_directory_lease_and_commit_parser_sources(tmp_path):
    import ast
    import copy
    import hashlib
    from pathlib import Path
    source = Path(__file__).with_name('qemu-menu-probe.py')
    tree = ast.parse(source.read_bytes())
    loops = [node for node in tree.body if isinstance(node, ast.For) and isinstance(node.iter, ast.List)
             and any(isinstance(item, ast.Call) and ast.unparse(item) == 'Path(command[-1])' for item in node.iter.elts)]
    assert len(loops) == 1
    required = ('directory_sd.py', 'directory_snapshot.py')
    nodes = [item for item in loops[0].iter.elts if ast.unparse(item) in {"base / '" + name + "'" for name in required}]
    assert len(nodes) == 2
    manifest = {'files': {}}
    for name in required:
        (tmp_path / name).write_bytes(('HOST_TEST dependency ' + name).encode())
    loop = copy.deepcopy(loops[0])
    loop.iter.elts = nodes
    scope = dict(base=tmp_path, manifest=manifest, sha256_file=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
    exec(compile(ast.Module(body=[loop], type_ignores=[]), str(source), 'exec'), scope)
    assert manifest['files'] == {str(tmp_path / name): scope['sha256_file'](tmp_path / name) for name in required}


def test_actual_central_quit_checks_host_disk_before_writing_wire(tmp_path, monkeypatch):
    import ast
    from contextlib import contextmanager, nullcontext
    from pathlib import Path
    import pytest
    import host_sd_guard
    source=Path(__file__).with_name('qemu-menu-probe.py')
    tree=ast.parse(source.read_text())
    function=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='qmp')
    for backing in ('raw','directory'):
        for mode in ('unsaved','verified','exited-during-retention'):
            events=[]
            proc=SimpleNamespace(code=None)
            proc.poll=lambda:proc.code
            class Camera:
                @contextmanager
                def qmp_command(self,name):
                    events.append(('broker',name))
                    yield
            class Stream:
                def write(self,data):events.append(('wire',json.loads(data)))
                def flush(self):events.append(('flush',))
                def readline(self):return b'{"return":{}}'
            def guard(actual_proc,run,verified):
                assert actual_proc is proc and run==tmp_path
                events.append(('disk',verified))
                if verified:return
                if mode=='exited-during-retention':proc.code=0;return
                raise RuntimeError('retained unsaved host disk')
            monkeypatch.setattr(host_sd_guard,'guard_shutdown',guard)
            scope=dict(functional_camera=Camera(),nullcontext=nullcontext,early_media_watch=None,
                       proc=proc,out=tmp_path,stream=Stream(),json=json,
                       host_sd_fd=40 if backing=='raw' else None,
                       directory_sd_fd=41 if backing=='directory' else None,
                       host_sd_export_verified=[mode=='verified'],qmp_quit_attempted=[False])
            exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),scope)
            if mode=='verified':
                assert scope['qmp']('quit')=={'return':{}}
                assert events==[('broker','quit'),('disk',True),('wire',{'execute':'quit'}),('flush',)]
            else:
                with pytest.raises(RuntimeError,match='retained|no quit command sent'):
                    scope['qmp']('quit')
                assert events==[('broker','quit'),('disk',False)]
            events.clear()
            assert scope['qmp']('query-status')=={'return':{}}
            assert events==[('broker','query-status'),('wire',{'execute':'query-status'}),('flush',)]

