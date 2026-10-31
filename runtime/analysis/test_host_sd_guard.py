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

