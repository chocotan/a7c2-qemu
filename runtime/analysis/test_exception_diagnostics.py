import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
import exception_diagnostics as diagnostics


class Wire:
    def __init__(self,console,reply=True,content=True,replies=None):
        self.console=console;self.bytes=bytearray();self.current=bytearray();self.reply=reply;self.content=content
        self.replies=replies
    def write(self,data):
        assert len(data)==1
        self.bytes.extend(data);self.current.extend(data)
        if data==b'\r':
            command=bytes(self.current).strip();self.current.clear()
            if self.reply:
                value=(b'x0: 000000000000000b x20: 000000000000000b\n' if command==b'reg' else b'[0x0000007f1234d67c] original\n') if self.content else b''
                raw=(self.replies[command] if self.replies is not None else command+b'\r\r\n'+value+b'\r\nException> ')
                with self.console.open('ab') as stream:stream.write(raw)
        return len(data)
    def flush(self):pass


def test_original_reg_and_call_reply_content_and_no_resume(tmp_path,monkeypatch):
    console=tmp_path/'console.log';console.write_bytes(b'Entering exception monitor.\nException> ')
    wire=Wire(console);process=SimpleNamespace(stdin=wire,poll=lambda:None)
    monkeypatch.setattr(diagnostics.time,'sleep',lambda n:None)
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.1)
    assert result['available'] and not result['firmware_resumed'] and not result['memory_or_registers_written']
    assert bytes(wire.bytes)==b'reg\rcall\r' and b'exit' not in wire.bytes
    assert all(x['reply_complete'] and x['content_observed'] for x in result['commands'])
    assert process._menu_serial_desynchronized is False
    assert (tmp_path/'exception-reg.raw').read_bytes().startswith(b'reg\r\r\n')
    assert diagnostics.collect_exception(process,tmp_path)==result


@pytest.mark.parametrize('kind',['no-prompt','active-input','desynchronized','exited','empty-content','no-reply'])
def test_no_fake_monitor_success_and_no_input_owner_conflict(tmp_path,kind):
    console=tmp_path/'console.log';console.write_bytes(b'normal shell' if kind=='no-prompt' else b'Exception> ')
    wire=Wire(console,reply=kind!='no-reply',content=kind!='empty-content')
    process=SimpleNamespace(stdin=wire,poll=lambda:0 if kind=='exited' else None)
    if kind=='active-input':process._app_input_transport=object()
    if kind=='desynchronized':process._menu_serial_desynchronized=True
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.02)
    assert not result['available']
    if kind in ('no-prompt','active-input','desynchronized','exited'):assert not wire.bytes
    if kind in ('empty-content','no-reply'):
        assert process._menu_serial_desynchronized is True
        assert bytes(wire.bytes)==b'reg\r'
        assert len(result['commands'])==1
    assert not result['firmware_resumed']


def test_partial_monitor_write_blocks_all_followup_commands(tmp_path,monkeypatch):
    import menu_live
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    class BrokenWire:
        def __init__(self):self.writes=[]
        def write(self,data):
            self.writes.append(data)
            if len(self.writes)>1:raise OSError('partial monitor write')
            with console.open('ab') as stream:stream.write(data)
            return len(data)
        def flush(self):pass
    wire=BrokenWire();process=SimpleNamespace(stdin=wire,poll=lambda:None)
    monkeypatch.setattr(diagnostics.time,'sleep',lambda _seconds:None)
    with pytest.raises(OSError,match='partial monitor write'):
        diagnostics.collect_exception(process,tmp_path)
    assert process._menu_serial_desynchronized is True and len(wire.writes)==2
    assert (tmp_path/'exception-reg.raw').read_bytes()==b'r'
    assert console.read_bytes()==b'Exception> r'
    with pytest.raises(RuntimeError,match='boundary lost'):
        menu_live.serial_command(process,console,'true',allow_faulted_cleanup=True)
    assert len(wire.writes)==2


def test_short_monitor_write_never_unlocks(tmp_path):
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    process=SimpleNamespace(stdin=SimpleNamespace(write=lambda _data:0,flush=lambda:None),poll=lambda:None)
    with pytest.raises(OSError,match='Short exception-monitor write'):
        diagnostics.collect_exception(process,tmp_path)
    assert process._menu_serial_desynchronized is True
    assert (tmp_path/'exception-reg.raw').read_bytes()==b''


REG_BODY=b'\r\n[register dump]\r\n r0: 0x0000000000000000   r1: 0x0000007f5d418710\r\n'
REG_REPLY=b'reg\r\r\n'+REG_BODY+b'Exception> '


@pytest.mark.parametrize('raw',[
    b'Exception> ',
    b'Exception> '+REG_REPLY,
    b'\r\nException> \r\n'+REG_REPLY,
    b'late output\r\n'+REG_REPLY,
    b'call\r\r\n'+REG_BODY+b'Exception> ',
    b'reg\n'+REG_BODY+b'Exception> ',
    b'reg\r\r\n'+REG_BODY,
    b'reg\r\r\n'+REG_BODY+b'Exception>',
    b'reg\r\r\n'+REG_BODY+b'Exception> \r\nlate output',
    b'reg\r\r\nException> \r\n'+REG_BODY+b'Exception> ',
    b'reg\r\r\n'+REG_BODY+b'inline Exception> ',
    b'reg\r\r\nCommand not found\r\nException> ',
    b'reg\r\r\n'+REG_BODY+b'Bad data address\r\nException> ',
],ids=['late-prompt','prompt-before-echo','late-prompt-line','old-output','wrong-echo',
        'unobserved-echo-form','no-final-prompt','partial-final-prompt','trailing-output',
        'extra-prompt','inline-prompt','command-error','address-error'])
def test_unowned_partial_or_failed_reply_never_unlocks_or_sends_followup(tmp_path,monkeypatch,raw):
    console=tmp_path/'console.log';before=b'Entering exception monitor.\r\nException> ';console.write_bytes(before)
    wire=Wire(console,replies={b'reg':raw});process=SimpleNamespace(stdin=wire,poll=lambda:None)
    monkeypatch.setattr(diagnostics.time,'sleep',lambda _seconds:None)
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.005)
    assert not result['available'] and not result['commands'][0]['reply_complete']
    assert process._menu_serial_desynchronized is True and bytes(wire.bytes)==b'reg\r'
    assert len(result['commands'])==1
    assert console.read_bytes()==before+raw and (tmp_path/'exception-reg.raw').read_bytes()==raw
    assert result['commands'][0]['raw_sha256']==hashlib.sha256(raw).hexdigest()
    assert diagnostics.collect_exception(process,tmp_path)==result and bytes(wire.bytes)==b'reg\r'


@pytest.mark.parametrize('before',[b'Exception> stale output',b'Exception> \r\nnormal shell',b'Exception>'])
def test_historical_or_partial_initial_prompt_sends_nothing(tmp_path,before):
    console=tmp_path/'console.log';console.write_bytes(before)
    wire=Wire(console);process=SimpleNamespace(stdin=wire,poll=lambda:None)
    result=diagnostics.collect_exception(process,tmp_path)
    assert not result['available'] and not wire.bytes and console.read_bytes()==before


def test_split_echo_and_final_prompt_wait_for_entire_current_reply(tmp_path,monkeypatch):
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    wire=Wire(console,replies={b'reg':b're',b'call':b'call\r\r\n[call stack]\r\n0x0000007f1234d67c\r\nException> '})
    process=SimpleNamespace(stdin=wire,poll=lambda:None)
    chunks=[b'g\r',b'\r\n'+REG_BODY,b'Exception>',b' ']
    def receive(seconds):
        if seconds==.02 and chunks:
            assert bytes(wire.bytes)==b'reg\r' and process._menu_serial_desynchronized is True
            with console.open('ab') as stream:stream.write(chunks.pop(0))
    monkeypatch.setattr(diagnostics.time,'sleep',receive)
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.1)
    assert result['available'] and not chunks and bytes(wire.bytes)==b'reg\rcall\r'
    assert process._menu_serial_desynchronized is False
    assert (tmp_path/'exception-reg.raw').read_bytes()==REG_REPLY


def test_prompt_arriving_after_deadline_is_preserved_without_unlock(tmp_path,monkeypatch):
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    wire=Wire(console,replies={b'reg':REG_REPLY[:-len(b'Exception> ')]})
    process=SimpleNamespace(stdin=wire,poll=lambda:None);clock=[0.]
    def receive(seconds):
        if seconds==.02:
            clock[0]+=.02
            with console.open('ab') as stream:stream.write(b'Exception> ')
    monkeypatch.setattr(diagnostics.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(diagnostics.time,'sleep',receive)
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.005)
    assert not result['available'] and not result['commands'][0]['reply_complete']
    assert process._menu_serial_desynchronized is True and bytes(wire.bytes)==b'reg\r'
    assert (tmp_path/'exception-reg.raw').read_bytes()==REG_REPLY


@pytest.mark.parametrize('memory_error',[False,True])
def test_each_memory_sample_requires_its_echo_content_and_final_prompt(tmp_path,monkeypatch,memory_error):
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    registers=REG_REPLY.replace(b'Exception> ',b' pc: 0x0000007f1234d67c sp: 0x0000007fff123ff8\r\nException> ')
    queries=diagnostics.memory_queries(registers)
    replies={b'reg':registers,b'call':b'call\r\r\n[call stack]\r\n0x0000007f1234d67c\r\nException> '}
    for label,command in queries:
        body=(b'Bad data address' if memory_error else b'0000007f1234d650 : d400000193407c60 540001a8b140041f')
        replies[command.encode()]=command.encode()+b'\r\r\n'+body+b'\r\nException> '
    wire=Wire(console,replies=replies);process=SimpleNamespace(stdin=wire,poll=lambda:None)
    monkeypatch.setattr(diagnostics.time,'sleep',lambda _seconds:None)
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.1)
    assert result['available']
    assert result['memory_samples_complete'] is (not memory_error)
    assert process._menu_serial_desynchronized is memory_error
    sent=b'reg\rcall\r'+b''.join(command.encode()+b'\r' for _,command in queries[:1 if memory_error else 2])
    assert bytes(wire.bytes)==sent
    assert [row['label'] for row in result['commands']]==(['reg','call','code'] if memory_error else ['reg','call','code','stack'])
    for row in result['commands']:
        assert (tmp_path/('exception-'+row['label']+'.raw')).read_bytes()==replies[row['command'].encode()]


def test_failed_call_stops_before_memory_queries(tmp_path,monkeypatch):
    console=tmp_path/'console.log';console.write_bytes(b'Exception> ')
    reg=REG_REPLY.replace(b'Exception> ',b' pc: 0x0000007f1234d67c sp: 0x0000007fff123ff8\r\nException> ')
    raw=b'call\r\r\nCommand not found\r\nException> '
    wire=Wire(console,replies={b'reg':reg,b'call':raw});process=SimpleNamespace(stdin=wire,poll=lambda:None)
    monkeypatch.setattr(diagnostics.time,'sleep',lambda _seconds:None)
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.1)
    assert not result['available'] and not result['memory_samples_complete']
    assert bytes(wire.bytes)==b'reg\rcall\r' and process._menu_serial_desynchronized is True
    assert (tmp_path/'exception-call.raw').read_bytes()==raw


def test_memory_queries_only_sample_original_user_pc_and_stack_same_page():
    rows=diagnostics.memory_queries(b'pc: 0x0000007f1234d67c sp: 0x0000007fff123ff8')
    assert [label for label,_ in rows]==['code','stack']
    for label,command in rows:
        name,start,units=command.split();start=int(start,16);size=int(units,16)*4
        assert name=='dq' and start%16==0 and 0<size<=128 and start//4096==(start+size-1)//4096
        assert size==(128 if label=='code' else 16)
    assert not diagnostics.memory_queries(b'pc: 0xffff000000001000 sp: 0x000000000000000b')
    assert not diagnostics.memory_queries(b'no saved PC or SP')


@pytest.mark.parametrize('value',[True,0,-1,6,float('inf'),float('nan'),'2'])
def test_diagnostic_timeout_is_strictly_bounded(tmp_path,value):
    with pytest.raises(ValueError):diagnostics.collect_exception(SimpleNamespace(),tmp_path,per_command_seconds=value)
