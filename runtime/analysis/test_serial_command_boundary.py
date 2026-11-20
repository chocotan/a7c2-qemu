import ast
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
from types import SimpleNamespace

import pytest

import menu_live as live
from media_state_readback import CELLS, command, parse


def test_long_line_rejected_before_writing_even_cleanup(tmp_path):
    console = tmp_path/'console'
    console.write_bytes(b'')
    writes = []
    proc = SimpleNamespace(stdin=SimpleNamespace(write=writes.append, flush=lambda: None))
    with pytest.raises(ValueError, match='1000-byte'):
        live.serial_command(proc, console, 'x'*1001, allow_faulted_cleanup=True)
    assert not writes


def test_timeout_blocks_all_followups_including_cleanup(tmp_path):
    console = tmp_path/'console'
    console.write_bytes(b'')
    writes = []
    proc = SimpleNamespace(stdin=SimpleNamespace(write=writes.append, flush=lambda: None), poll=lambda: None)
    with pytest.raises(TimeoutError):
        live.serial_command(proc, console, 'true', timeout=0, allow_faulted_cleanup=True)
    assert len(writes) == 1 and proc._menu_serial_desynchronized
    with pytest.raises(RuntimeError, match='boundary lost'):
        live.serial_command(proc, console, 'cleanup must not be sent', allow_faulted_cleanup=True)
    assert len(writes) == 1


def test_output_overflow_poison_retains_log_and_never_pauses_again(tmp_path,monkeypatch):
    console=tmp_path/'console';console.write_bytes(b'original\n')
    monkeypatch.setattr(live,'MAX_SERIAL_OUTPUT',32)
    writes=[];pauses=[]
    def send(wire):
        writes.append(wire)
        with console.open('ab') as output:output.write(b'x'*33)
    proc=SimpleNamespace(stdin=SimpleNamespace(write=send,flush=lambda:None),poll=lambda:None)
    with pytest.raises(RuntimeError,match='输出超过限制'):
        live.serial_command(proc,console,'true',timeout=5,allow_faulted_cleanup=True)
    assert proc._menu_serial_desynchronized and console.read_bytes()==b'original\n'+b'x'*33
    proc._app_input_transport=SimpleNamespace(pause=lambda:pauses.append(True))
    with pytest.raises(RuntimeError,match='boundary lost'):
        live.serial_command(proc,console,'cleanup',allow_faulted_cleanup=True)
    assert len(writes)==1 and pauses==[]


def test_oversized_console_is_preserved_before_any_command(tmp_path,monkeypatch):
    console=tmp_path/'console';content=b'x'*65;console.write_bytes(content)
    monkeypatch.setattr(live,'MAX_CONSOLE',64)
    writes=[];pauses=[]
    proc=SimpleNamespace(stdin=SimpleNamespace(write=writes.append,flush=lambda:None),
                         _app_input_transport=SimpleNamespace(pause=lambda:pauses.append(True)))
    with pytest.raises(RuntimeError,match='保留原日志'):
        live.serial_command(proc,console,'true',allow_faulted_cleanup=True)
    assert not writes and not pauses and console.read_bytes()==content
    assert proc._menu_serial_desynchronized


def test_serial_write_error_blocks_followup(tmp_path):
    console=tmp_path/'console';console.write_bytes(b'')
    def broken(_wire):raise OSError('partial write unknown')
    proc=SimpleNamespace(stdin=SimpleNamespace(write=broken,flush=lambda:None),poll=lambda:None)
    with pytest.raises(OSError,match='partial write'):
        live.serial_command(proc,console,'true',allow_faulted_cleanup=True)
    assert proc._menu_serial_desynchronized
    with pytest.raises(RuntimeError,match='boundary lost'):
        live.serial_command(proc,console,'cleanup',allow_faulted_cleanup=True)


def test_nonzero_completed_marker_allows_new_command(tmp_path):
    console=tmp_path/'console';console.write_bytes(b'');calls=[]
    def send(wire):
        marker=re.search(rb'MENU_DIAG_COMMAND_DONE_[0-9a-f]+',wire).group()
        calls.append(wire)
        with console.open('ab') as output:output.write(b'\n'+marker+(b':7\n' if len(calls)==1 else b':0\n'))
    proc=SimpleNamespace(stdin=SimpleNamespace(write=send,flush=lambda:None),poll=lambda:None)
    with pytest.raises(RuntimeError,match='返回码 7'):
        live.serial_command(proc,console,'false',timeout=5,allow_faulted_cleanup=True)
    assert not proc._menu_serial_desynchronized
    assert b':0' in live.serial_command(proc,console,'true',timeout=5,allow_faulted_cleanup=True)
    assert len(calls)==2


@pytest.mark.parametrize('receipt_exists',[False,True])
def test_unknown_serial_retains_owner_until_natural_exit(tmp_path,receipt_exists):
    receipt=tmp_path/'serial-boundary-unknown.json'
    if receipt_exists:receipt.write_text('previous evidence')
    class Owner:
        pid=4321
        _menu_serial_desynchronized=True
        def __init__(self):self.alive=True;self.waits=0
        def poll(self):return None if self.alive else 0
        def wait(self):
            self.waits+=1
            if self.waits==1:raise InterruptedError('interrupted')
            self.alive=False;return 0
    owner=Owner()
    assert live.retain_serial_owner(owner,tmp_path,'bounded output failure') is True
    assert owner.waits==2 and not owner.alive
    if receipt_exists:assert receipt.read_text()=='previous evidence'
    else:
        proof=json.loads(receipt.read_text())
        assert proof['pid']==4321 and proof['signals_sent']==[]
        assert proof['serial_boundary_known'] is False and proof['owner_retention_intent'] is True
        assert proof['process_exit_observed'] is False


def test_qmp_owner_guard_waits_and_preserves_original_error(tmp_path):
    class Owner:
        pid=4322
        _menu_serial_desynchronized=False
        def __init__(self):self.alive=True;self.waits=0
        def poll(self):return None if self.alive else 0
        def wait(self):self.waits+=1;self.alive=False;return 1
    owner=Owner()
    with pytest.raises(RuntimeError,match='qmp reply unknown'):
        with live.guard_live_owner(owner,tmp_path):raise RuntimeError('qmp reply unknown')
    proof=json.loads((tmp_path/'qmp-exit-unknown.json').read_text())
    assert owner.waits==1 and proof['reason']=='qmp-exit' and proof['signals_sent']==[]
    assert proof['process_exit_observed'] is False


def test_process_group_guard_holds_after_probe_error(tmp_path,monkeypatch):
    class Owner:
        pid=4323
        def poll(self):return 1
    checks=[];sleeps=[]
    def probe(pid,signal):
        assert pid==4323 and signal==0;checks.append(True)
        if len(checks)==2:raise PermissionError('unknown group')
        if len(checks)==3:raise ProcessLookupError()
    def sleep(_seconds):
        sleeps.append(True)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
        signal.getsignal(signal.SIGINT)(signal.SIGINT,None)
        if len(sleeps)==1:raise KeyboardInterrupt()
    monkeypatch.setattr(live.os,'killpg',probe)
    monkeypatch.setattr(live.time,'sleep',sleep)
    with pytest.raises(ValueError,match='cleanup failed'):
        with live.guard_process_group(Owner(),tmp_path):raise ValueError('cleanup failed')
    assert len(checks)==3 and len(sleeps)==2


def test_qmp_late_reply_cannot_be_mistaken_for_quit(tmp_path):
    class Stream:
        def __init__(self):self.writes=[];self.replies=[]
        def write(self,data):self.writes.append(data);return len(data)
        def flush(self):pass
        def readline(self,_limit):
            if not self.replies:raise InterruptedError('response unavailable')
            return self.replies.pop(0)
    class Owner:
        pid=4325
        def __init__(self):self.alive=True
        def poll(self):return None if self.alive else 0
        def wait(self):self.alive=False;return 0
    stream=Stream();owner=Owner()
    with pytest.raises(InterruptedError):live.qmp_transaction(owner,stream,'screendump',{'filename':'/out/frame'})
    old_id=json.loads(stream.writes[0])['id']
    stream.replies.append((json.dumps({'return':{},'id':old_id})+'\n').encode())
    with pytest.raises(RuntimeError,match='boundary lost'):
        with live.guard_live_owner(owner,tmp_path):live.qmp_transaction(owner,stream,'quit')
    assert len(stream.writes)==1 and len(stream.replies)==1 and not owner.alive
    assert not (tmp_path/'qmp-quit.json').exists()
    proof=json.loads((tmp_path/'qmp-exit-unknown.json').read_text())
    assert proof['signals_sent']==[] and proof['qmp_last_wire_frame_available'] is False


def test_cold_final_quit_failure_preserves_unknown_boundary(tmp_path):
    path=Path(live.__file__).resolve().parents[2]/'tools/run-original-cold.py'
    tree=ast.parse(path.read_text())
    closing=next(node for node in ast.walk(tree) if isinstance(node,ast.Try) and node.handlers and
                 any(isinstance(item,ast.Assign) and isinstance(item.value,ast.Call) and
                     isinstance(item.value.func,ast.Name) and item.value.func.id=='qmp' and
                     item.value.args and isinstance(item.value.args[0],ast.Constant) and item.value.args[0].value=='quit'
                     for item in node.body))
    body=closing.handlers[0].body
    raw=b'{"return":{},"id":"late"}\n'
    owner=SimpleNamespace(pid=4329,poll=lambda:0,_menu_qmp_desynchronized=True,
                          _menu_qmp_request_id='pending',_menu_qmp_last_raw=raw)
    snapshots=[];result={'verified':True}
    scope=dict(error=ValueError('wrong id'),process=owner,runtime=tmp_path,result=result,
               save=lambda:snapshots.append(dict(result)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=body,type_ignores=[])),str(path),'exec'),scope)
    assert snapshots and snapshots[0]['qmp_boundary_unknown'] and snapshots[0]['owner_retention_requested']
    assert result['verified'] is False and 'wrong id' in result['close_error']
    proof=json.loads((tmp_path/'qmp-exit-unknown.json').read_text())
    assert proof['qmp_request_id']=='pending' and proof['process_exit_observed'] is True
    assert (tmp_path/'qmp-unknown-last-frame.raw').read_bytes()==raw


def test_qmp_raw_frame_is_preserved_after_owner_already_exited(tmp_path):
    raw=b'{"return":{},"id":"stale"}\n'
    owner=SimpleNamespace(pid=4328,poll=lambda:0,_menu_qmp_desynchronized=True,
                          _menu_qmp_request_id='current',_menu_qmp_last_raw=raw)
    assert live.retain_running_owner(owner,tmp_path,'wrong id',reason='qmp-exit') is False
    proof=json.loads((tmp_path/'qmp-exit-unknown.json').read_text())
    assert proof['process_exit_observed'] is True and proof['owner_retention_intent'] is False
    assert proof['qmp_request_id']=='current' and proof['qmp_last_wire_frame_sha256']==hashlib.sha256(raw).hexdigest()
    assert (tmp_path/'qmp-unknown-last-frame.raw').read_bytes()==raw


def test_wrong_qmp_id_preserves_raw_frame_before_owner_exit(tmp_path):
    raw=b'{"return":{},"id":"stale"}\n'
    class Stream:
        def write(self,data):return len(data)
        def flush(self):pass
        def readline(self,_limit):return raw
    class Owner:
        pid=4326
        def __init__(self):self.alive=True
        def poll(self):return None if self.alive else 0
        def wait(self):self.alive=False;return 0
    owner=Owner()
    with pytest.raises(ValueError,match='does not match'):
        with live.guard_live_owner(owner,tmp_path):live.qmp_transaction(owner,Stream(),'query-status')
    assert (tmp_path/'qmp-unknown-last-frame.raw').read_bytes()==raw
    proof=json.loads((tmp_path/'qmp-exit-unknown.json').read_text())
    assert proof['qmp_last_wire_frame_available'] is True and proof['qmp_last_wire_frame_sha256']==hashlib.sha256(raw).hexdigest()


def test_owner_retention_masks_repeated_cooperative_exit_requests(tmp_path):
    previous=signal.getsignal(signal.SIGTERM)
    def exiting(_number,_frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,exiting)
    class Owner:
        pid=4327
        def __init__(self):self.alive=True
        def poll(self):return None if self.alive else 0
        def wait(self):
            for _ in range(2):
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
                signal.getsignal(signal.SIGINT)(signal.SIGINT,None)
            self.alive=False
            return 0
    try:
        assert live.retain_running_owner(Owner(),tmp_path,reason='qmp-exit') is True
        assert signal.getsignal(signal.SIGTERM) is exiting
    finally:signal.signal(signal.SIGTERM,previous)


def test_qmp_event_then_matching_reply_is_accepted():
    class Stream:
        def __init__(self):self.request=None;self.reads=0
        def write(self,data):self.request=json.loads(data);return len(data)
        def flush(self):pass
        def readline(self,_limit):
            self.reads+=1
            value={'event':'RESET'} if self.reads==1 else {'return':{'running':True},'id':self.request['id']}
            return (json.dumps(value)+'\n').encode()
    stream=Stream();owner=SimpleNamespace()
    assert live.qmp_transaction(owner,stream,'query-status')=={'return':{'running':True}}
    assert owner._menu_qmp_desynchronized is False and stream.reads==2


def test_qmp_empty_success_preserves_legacy_shape():
    class Stream:
        def write(self,data):self.request=json.loads(data);return len(data)
        def flush(self):pass
        def readline(self,_limit):return (json.dumps({'return':{},'id':self.request['id']})+'\n').encode()
    owner=SimpleNamespace()
    assert live.qmp_transaction(owner,Stream(),'pmemsave',{})=={'return':{}}
    assert owner._menu_qmp_desynchronized is False


def test_qmp_matching_error_keeps_boundary_and_wrong_id_poisons():
    class Stream:
        def __init__(self):self.requests=[];self.mode='error'
        def write(self,data):self.requests.append(json.loads(data));return len(data)
        def flush(self):pass
        def readline(self,_limit):
            request=self.requests[-1]
            reply={'error':{'desc':'refused'},'id':request['id']} if self.mode=='error' else {'return':{},'id':'stale'}
            return (json.dumps(reply)+'\n').encode()
    stream=Stream();owner=SimpleNamespace()
    with pytest.raises(RuntimeError,match='refused'):live.qmp_transaction(owner,stream,'query-status')
    assert owner._menu_qmp_desynchronized is False
    stream.mode='wrong'
    with pytest.raises(ValueError,match='does not match'):live.qmp_transaction(owner,stream,'query-status')
    assert owner._menu_qmp_desynchronized is True
    with pytest.raises(RuntimeError,match='boundary lost'):live.qmp_transaction(owner,stream,'quit')
    assert len(stream.requests)==2


@pytest.mark.parametrize('reply',[b'{"return":{},"id":"x"}',b'{"return":{},"return":{},"id":"x"}\n'])
def test_qmp_malformed_reply_never_allows_retry(reply):
    class Stream:
        def write(self,data):return len(data)
        def flush(self):pass
        def readline(self,_limit):return reply
    owner=SimpleNamespace()
    with pytest.raises((OSError,ValueError)):live.qmp_transaction(owner,Stream(),'query-status')
    assert owner._menu_qmp_desynchronized is True
    with pytest.raises(RuntimeError,match='boundary lost'):live.qmp_transaction(owner,Stream(),'quit')


def test_qmp_partial_fd_send_poisoned_without_retry():
    owner=SimpleNamespace();sent=[]
    def partial(data):sent.append(data);return len(data)-1
    with pytest.raises(OSError,match='Short QMP'):
        live.qmp_transaction(owner,SimpleNamespace(),'getfd',{'fdname':'a'},send=partial)
    assert owner._menu_qmp_desynchronized is True
    with pytest.raises(RuntimeError,match='boundary lost'):
        live.qmp_transaction(owner,SimpleNamespace(),'quit')
    assert len(sent)==1


def test_qmp_quit_rechecks_serial_after_exception_diagnostics(tmp_path,monkeypatch):
    import exception_diagnostics
    path=Path(live.__file__).with_name('qemu-menu-probe.py')
    tree=ast.parse(path.read_text())
    function=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='qmp_unlocked')
    scope={}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(path),'exec'),scope)
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    writes=[]
    class Owner:
        pid=4324
        _menu_serial_desynchronized=False
        def __init__(self):self.alive=True
        def poll(self):return None if self.alive else 0
        def wait(self):self.alive=False;return 0
    owner=Owner();scope.update(proc=owner,out=tmp_path,stream=SimpleNamespace(write=writes.append))
    def incomplete(process,_run):process._menu_serial_desynchronized=True
    monkeypatch.setattr(exception_diagnostics,'collect_exception',incomplete)
    with pytest.raises(RuntimeError,match='became unknown'):
        with live.guard_live_owner(owner,tmp_path):scope['qmp_unlocked']('quit')
    assert not writes and not owner.alive
    assert json.loads((tmp_path/'qmp-exit-unknown.json').read_text())['signals_sent']==[]


def test_actual_launchers_guard_unknown_serial_before_qmp_quit():
    product=Path(live.__file__).resolve().parents[2]
    for path in (product/'tools/run-original-cold.py',Path(live.__file__).with_name('qemu-menu-probe.py')):
        tree=ast.parse(path.read_text())
        matches=[]
        for node in ast.walk(tree):
            if not isinstance(node,ast.Try) or not node.finalbody:continue
            calls=[part for item in node.finalbody for part in ast.walk(item)
                   if isinstance(part,ast.Call) and isinstance(part.func,ast.Name) and part.func.id=='retain_serial_owner']
            if calls:matches.append((node,calls))
        assert matches
        if path.name=='qemu-menu-probe.py':
            text=path.read_text()
            assert 'enter_context(guard_live_owner(proc,out))' in text
            assert text.index('enter_context(owner_signal_guard())')<text.index('proc = subprocess.Popen')
            assert "name=='quit' and getattr(proc,'_menu_serial_desynchronized',False)" in text
            assert 'proc.stdin.write' not in text and 'proc.stdin.flush' not in text
        else:
            text=path.read_text()
            assert 'enter_context(guard_process_group(process,runtime))' in text
            assert text.index('enter_context(owner_signal_guard())')<text.index('process=subprocess.Popen')
            assert "Serial boundary unknown; QMP quit is not admitted" in text
        for node,calls in matches:
            quits=[part for item in node.finalbody for part in ast.walk(item)
                   if isinstance(part,ast.Call) and isinstance(part.func,ast.Name) and part.func.id=='qmp'
                   and part.args and isinstance(part.args[0],ast.Constant) and part.args[0].value=='quit']
            assert quits and calls[0].lineno<min(item.lineno for item in quits)


def test_ui_cleanup_never_routes_owner_through_signal_helpers():
    path=Path(live.__file__).with_name('menu_control.py')
    tree=ast.parse(path.read_text())
    vm=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='VM')
    for name in ('close','_run'):
        method=next(node for node in vm.body if isinstance(node,ast.FunctionDef) and node.name==name)
        calls=[node.func.id for node in ast.walk(method) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)]
        assert 'wait_functional_camera_owner' in calls
        assert 'terminate_owned' not in calls and 'terminate_host_disk_owner' not in calls
    for name in ('terminate_owned','terminate_host_disk_owner'):
        function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name)
        assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('kill','killpg','terminate','send_signal') for node in ast.walk(function))


def test_qemu_shell_forbids_signal_timeout_before_outputs():
    script=Path(live.__file__).with_name('qemu-kernel-probe.sh').read_text()
    checked=subprocess.run(['bash','-n'],input=script,text=True,capture_output=True,timeout=5)
    assert checked.returncode==0,checked.stderr
    guard=script.index('QEMU timeout signaling is disabled')
    assert guard<script.index('mkdir -p "$output_dir"')
    assert 'timeout --signal=TERM' not in script and 'kill-after' not in script
    assert 'runner=(exec)' in script


def test_multiline_actual_readback_finishes_each_field_and_real_sentinel(tmp_path):
    console = tmp_path/'console'
    console.write_bytes(b'')
    generated = command(b'OBS FRAME_DRAW_ENTER call=1 tid=302 x=1\n')
    # Host adapters only replace the guest mapping check and guest executable.
    generated = generated.replace('/bin/busybox grep -q /usr/lib/appFw.so /proc/302/maps', 'true')
    generated = generated.replace('/simulation/menu-readmem', 'echo HOST_READ_ONLY_STUB')
    writes = []

    def execute(wire):
        writes.append(wire)
        result = subprocess.run(['sh'], input=wire, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr
        with console.open('ab') as stream:
            stream.write(result.stdout)

    proc = SimpleNamespace(stdin=SimpleNamespace(write=execute, flush=lambda: None), poll=lambda: None)
    data = live.serial_command(proc, console, generated, timeout=5, allow_faulted_cleanup=True)
    assert len(writes) == 1
    assert max(map(len, writes[0].splitlines())) < 200
    result = parse(data)
    assert len(result['reads']) == len(CELLS) == 8
    assert all(row['returncode'] == 0 for row in result['reads'])
    assert b'MENU_DIAG_COMMAND_DONE_' in data


def test_early_debug_readiness_requires_actual_model_commit(tmp_path, monkeypatch):
    console = tmp_path/'console'
    console.write_bytes(b'/ #\nOBS GUI_MODEL_COMMITTED packets=0 types=0\n')
    monkeypatch.setattr(live, 'FirmwareMonitor', lambda path: SimpleNamespace(check=lambda: None))
    calls = []
    def publish(delay):
        calls.append('wait')
        with console.open('ab') as stream:
            stream.write(b'OBS GUI_MODEL_COMMITTED packets=1 types=0x3f changed=1\n')
    monkeypatch.setattr(live.time, 'sleep', publish)
    live.wait_initial_model_commit(SimpleNamespace(poll=lambda: None), console, timeout=1)
    assert calls == ['wait']
    console.write_bytes(b'/ #\n')
    with pytest.raises(TimeoutError, match='publication missing'):
        live.wait_initial_model_commit(SimpleNamespace(poll=lambda: None), console, timeout=0)
