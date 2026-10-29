"""Actual run_live loop, host-only transport faults; no socket/VM is opened."""
from types import SimpleNamespace

import pytest
import menu_live as live


class EndOfFixture(Exception):
    pass


@pytest.mark.parametrize('failure',[TimeoutError('command still in flight'),OSError('transport failed'),RuntimeError('guest command failed')])
@pytest.mark.parametrize('input_profile',['','virtual-input-s0-v1'])
def test_SD_input_transport_fault_latches_and_keeps_export_channel(tmp_path,monkeypatch,failure,input_profile):
    monkeypatch.setenv('MENU_ADF_SET_INPUT',input_profile)
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


def test_gui_model_presence_timeout_latches_before_followups_and_blocks_cleanup(tmp_path,monkeypatch):
    import re
    console=tmp_path/'console.log';console.write_bytes(b'')
    commands=[];writes=[];responses=[];captures=[];exports=[]
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel()
    requests=iter([{'action':'snapshot'},{'action':'snapshot'},
                   {'action':'key','key':'MENU'},{'action':'position','key':'MODE','position':'P'},
                   {'action':'shutter_cycle'},{'action':'export_sd'},
                   {'action':'key','key':'ENTER'},{'action':'export_sd'}])
    def receive(*args,**kwargs):
        try:return next(requests)
        except StopIteration:raise EndOfFixture()
    def write(wire):
        writes.append(wire)
        if wire.startswith(b'true;'):
            marker=re.search(rb'MENU_DIAG_COMMAND_DONE_[0-9a-f]+',wire)[0]
            with console.open('ab') as stream:stream.write(b'\n'+marker+b':0\n')
    proc=SimpleNamespace(stdin=SimpleNamespace(write=write,flush=lambda:None),poll=lambda:None)
    serial_command=live.serial_command
    def serial(proc,out,command,**kwargs):
        commands.append(command)
        timeout=0 if command.startswith('if [ -e /tmp/gui-model-state.bin ]') else 1
        return serial_command(proc,out,command,timeout=timeout,**kwargs)
    def capture():
        captures.append(True)
        return {'type':'snapshot','png':'real-lcd'}
    def export():
        exports.append(True)
        live.serial_command(proc,console,'cleanup must not be sent',allow_faulted_cleanup=True)
        raise AssertionError('desynchronized cleanup must not succeed')
    monkeypatch.setenv('MENU_GUI_MODELS','virtual-inline-v1')
    monkeypatch.delenv('A7C2_MEDIA_INIT_WATCH',raising=False)
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',receive)
    monkeypatch.setattr(live,'send_message',lambda control,message:responses.append(message))
    monkeypatch.setattr(live,'serial_command',serial)
    with pytest.raises(EndOfFixture):
        live.run_live(proc,tmp_path,99,display_capture=capture,sd_export=export)
    fault=responses[1]['error']
    assert fault.startswith('TimeoutError:')
    assert [reply['type'] for reply in responses]==[
        'ready','error','error','error','error','error','sd_export','error','sd_export']
    assert all(reply['error']==fault for reply in responses if reply['type']=='error')
    assert len(captures)==1 and len(exports)==2
    assert commands[0]=='true' and commands[1].startswith('if [ -e /tmp/gui-model-state.bin ]')
    assert commands[2:]==['cleanup must not be sent']*2
    assert len(writes)==2 and proc._menu_serial_desynchronized and proc.poll() is None
    assert all(not reply['ok'] and 'boundary lost' in reply['error']
               for reply in responses if reply['type']=='sd_export')


def test_missing_gui_model_does_not_hide_real_lcd(tmp_path,monkeypatch):
    (tmp_path/'console.log').write_bytes(b'')
    commands=[];responses=[]
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel()
    requests=iter([{'action':'snapshot'}])
    def receive(*args,**kwargs):
        try:return next(requests)
        except StopIteration:raise EndOfFixture()
    def serial(proc,out,command,**kwargs):
        commands.append(command)
        if command=='true':return b''
        if command.startswith('if [ -e /tmp/gui-model-state.bin ]'):
            return b'GUI_MODEL_STATE_ABSENT\n'
        raise AssertionError('missing model must not invoke export: '+command)
    monkeypatch.setenv('MENU_GUI_MODELS','virtual-inline-v1')
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',receive)
    monkeypatch.setattr(live,'send_message',lambda control,message:responses.append(message))
    monkeypatch.setattr(live,'serial_command',serial)
    with pytest.raises(EndOfFixture):
        live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,99,
                      display_capture=lambda:{'type':'snapshot','png':'real-lcd'})
    snapshot=responses[-1]
    assert snapshot['type']=='snapshot' and snapshot['png']=='real-lcd'
    assert snapshot['gui_model_available'] is False
    assert snapshot['gui_model_publication_verified'] is False
    assert not any('/simulation/gui-model-export' in command for command in commands)
    import json
    model=json.loads((tmp_path/'gui-model-latest.json').read_text())
    assert model['ok'] is False and model['available'] is False and model['publication_verified'] is False


def test_present_gui_model_still_requires_export(tmp_path,monkeypatch):
    (tmp_path/'console.log').write_bytes(b'')
    commands=[]
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel()
    def serial(proc,out,command,**kwargs):
        commands.append(command)
        if command=='true':return b''
        if command.startswith('if [ -e /tmp/gui-model-state.bin ]'):
            return b'GUI_MODEL_STATE_PRESENT\n'
        if command=='/simulation/gui-model-export':
            raise RuntimeError('guest 命令失败，返回码 1')
        raise AssertionError(command)
    monkeypatch.setenv('MENU_GUI_MODELS','virtual-inline-v1')
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',lambda *args,**kwargs:{'action':'snapshot'})
    monkeypatch.setattr(live,'send_message',lambda *args:None)
    monkeypatch.setattr(live,'serial_command',serial)
    with pytest.raises(RuntimeError,match='返回码 1'):
        live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,99,
                      display_capture=lambda:{'type':'snapshot','png':'real-lcd'})
    assert '/simulation/gui-model-export' in commands


@pytest.mark.parametrize('observation_fails',[False,True])
@pytest.mark.parametrize('input_profile',['','virtual-input-s0-v1'])
def test_post_shutter_observation_precedes_export_without_blocking_recovery(tmp_path,monkeypatch,observation_fails,input_profile):
    import ee_entry_snapshot,json
    monkeypatch.setenv('MENU_ADF_SET_INPUT',input_profile)
    (tmp_path/'console.log').write_bytes(b'')
    events=[];responses=[]
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel()
    requests=iter([{'action':'export_sd'},{'action':'shutter_cycle'},
                   {'action':'export_sd'},{'action':'export_sd'}])
    def receive(*args,**kwargs):
        try:return next(requests)
        except StopIteration:raise EndOfFixture()
    def observe(serial,out):
        events.append('observe')
        if observation_fails:raise ValueError('incomplete passive evidence')
        return {'available':True,'snapshot_dir':str(tmp_path),'app_pid':42,'app_base':'0x7f00000000'}
    def export():events.append('export');return {'ok':True}
    monkeypatch.setenv('MENU_LIVE_APP_INPUT','1')
    monkeypatch.delenv('MENU_LIVE_KEY_FILE',raising=False)
    monkeypatch.setenv('A7C2_EE_PASSIVE_AFTER_SHUTTER','1')
    monkeypatch.setattr(ee_entry_snapshot,'collect_passive',observe)
    monkeypatch.setattr(ee_entry_snapshot,'collect_group0',lambda *args:{'available':True,'current_id':'0x1b2','atomic_snapshot':False})
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',receive)
    monkeypatch.setattr(live,'send_message',lambda control,message:responses.append(message))
    monkeypatch.setattr(live,'serial_command',lambda *args,**kwargs:b'')
    with pytest.raises(EndOfFixture):live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,99,sd_export=export)
    assert events==['export','observe','export','export']
    exports=[r for r in responses if r['type']=='sd_export']
    assert 'post_shutter_observation' not in exports[0]
    assert all(r['ok'] for r in exports)
    assert exports[1]['post_shutter_observation']['ok'] is not observation_fails
    assert exports[1]['post_shutter_observation']==exports[2]['post_shutter_observation']
    proof=json.loads((tmp_path/'natural-shutter-request.json').read_text())
    assert proof['input_submission_accepted'] is True
    assert proof['consumer_verified'] is False and proof['still_capture_verified'] is False


@pytest.mark.parametrize('observation_fails',[False,True])
def test_still_entry_observation_is_once_after_actual_marker_and_before_export(tmp_path,monkeypatch,observation_fails):
    import ee_entry_snapshot,json
    (tmp_path/'console.log').write_bytes(b'')
    events=[];responses=[]
    class Channel:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    channel=Channel();requests=iter([{'action':'snapshot'},{'action':'export_sd'},{'action':'export_sd'}])
    def receive(*args,**kwargs):
        try:return next(requests)
        except StopIteration:raise EndOfFixture()
    def capture():
        events.append('snapshot')
        (tmp_path/'console.log').write_bytes(b'/ # OBS ENTER_REC_STILL n=1 tid=44 object=0x7f70001000\n')
        return {'type':'snapshot','png':'real-lcd'}
    def observe(serial,out,*,common_only):
        assert common_only;events.append('observe')
        if observation_fails:raise ValueError('incomplete Common evidence')
        return {'available':True,'snapshot_dir':str(tmp_path),'app_pid':42,'app_base':'0x7f00000000'}
    def export():events.append('export');return {'ok':True}
    monkeypatch.setenv('A7C2_EE_PASSIVE_ON_STILL_ENTRY','1')
    monkeypatch.delenv('MENU_GUI_MODELS',raising=False)
    monkeypatch.setattr(ee_entry_snapshot,'collect_passive',observe)
    monkeypatch.setattr(ee_entry_snapshot,'collect_group0',lambda *args:{'available':True,'current_id':'0x2f','atomic_snapshot':False})
    monkeypatch.setattr(live.socket,'socket',lambda **kwargs:channel)
    monkeypatch.setattr(live.select,'select',lambda *args:([channel],[],[]))
    monkeypatch.setattr(live,'receive_message',receive)
    monkeypatch.setattr(live,'send_message',lambda control,message:responses.append(message))
    monkeypatch.setattr(live,'serial_command',lambda *args,**kwargs:b'')
    with pytest.raises(EndOfFixture):
        live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,99,display_capture=capture,sd_export=export)
    assert events==['snapshot','observe','export','export']
    result=json.loads((tmp_path/'ee-still-entry.json').read_text())
    assert result['ok'] is not observation_fails and result['threads_not_stopped']
    assert not result['capture_verified'] and not result['current_blocker_proven']
    assert result['phase']=='after observed Still entry, before next live command'
    assert all(item['ok'] for item in responses if item['type']=='sd_export')


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
