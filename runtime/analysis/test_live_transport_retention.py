"""Actual run_live loop, host-only transport faults; no socket/VM is opened."""
from types import SimpleNamespace

import pytest
import menu_live as live


class EndOfFixture(Exception):
    pass


@pytest.mark.parametrize('failure',[TimeoutError('command still in flight'),OSError('transport failed'),RuntimeError('guest command failed')])
def test_SD_input_transport_fault_latches_and_keeps_export_channel(tmp_path,monkeypatch,failure):
    (tmp_path/'console.log').write_bytes(b'')
    commands=[];responses=[];exports=[]
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel()
    requests=iter([{'action':'key','key':'MENU'},{'action':'key','key':'DOWN'},
                   {'action':'snapshot'},{'action':'export_sd'},{'action':'key','key':'ENTER'},
                   {'action':'export_sd'}])
    def receive(*args,**kwargs):
        try:return next(requests)
        except StopIteration:raise EndOfFixture()
    def serial(proc,out,command,**kwargs):
        commands.append(command)
        if command!='true':raise failure
        return b''
    def export():
        exports.append(True)
        return {'ok':len(exports)>1,'error':'CPU not restored' if len(exports)==1 else None}
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',receive)
    monkeypatch.setattr(live,'send_message',lambda control,message:responses.append(message))
    monkeypatch.setattr(live,'serial_command',serial)
    with pytest.raises(EndOfFixture):
        live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,99,sd_export=export)
    assert len(commands)==2 and commands[0]=='true'
    assert [reply['type'] for reply in responses]==['ready','error','error','error','sd_export','error','sd_export']
    assert type(failure).__name__ in responses[1]['error']
    assert len(exports)==2 and not responses[4]['ok'] and responses[6]['ok']


def test_non_SD_input_timeout_still_raises_instead_of_continuing_serial(tmp_path,monkeypatch):
    (tmp_path/'console.log').write_bytes(b'')
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel();commands=[]
    def serial(proc,out,command,**kwargs):
        commands.append(command)
        if command!='true':raise TimeoutError('legacy timeout')
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',lambda *args,**kwargs:{'action':'key','key':'MENU'})
    monkeypatch.setattr(live,'send_message',lambda *args:None)
    monkeypatch.setattr(live,'serial_command',serial)
    with pytest.raises(TimeoutError,match='legacy timeout'):
        live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,99)
    assert len(commands)==2


def test_driver_rechecks_debugger_on_each_wait_iteration():
    import ast
    import json
    from pathlib import Path
    source=Path(__file__).with_name('check-natural-gtk-input.py')
    wait=next(node for node in ast.walk(ast.parse(source.read_text()))
              if isinstance(node,ast.FunctionDef) and node.name=='wait')
    ticks=iter(range(20));checks=[]
    def check():
        checks.append(True)
        if len(checks)==2:raise RuntimeError('resume failed; retain')
    namespace=dict(time=SimpleNamespace(monotonic=lambda:next(ticks),sleep=lambda value:None),
                   queue_watch=SimpleNamespace(check_exited=check),child=SimpleNamespace(poll=lambda:None),json=json,
                   geometry=SimpleNamespace(exists=lambda:True,read_text=lambda:'{"state":"running"}'))
    exec(compile(ast.Module(body=[wait],type_ignores=[]),str(source),'exec'),namespace)
    with pytest.raises(RuntimeError,match='retain'):namespace['wait'](lambda state:False)
    assert len(checks)==2
