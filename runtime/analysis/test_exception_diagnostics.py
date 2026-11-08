from pathlib import Path
from types import SimpleNamespace

import pytest
import exception_diagnostics as diagnostics


class Wire:
    def __init__(self,console,reply=True,content=True):
        self.console=console;self.bytes=bytearray();self.current=bytearray();self.reply=reply;self.content=content
    def write(self,data):
        assert len(data)==1
        self.bytes.extend(data);self.current.extend(data)
        if data==b'\r':
            command=bytes(self.current).strip();self.current.clear()
            if self.reply:
                value=(b'x0: 000000000000000b x20: 000000000000000b\n' if command==b'reg' else b'[0x0000007f1234d67c] original\n') if self.content else b''
                with self.console.open('ab') as stream:stream.write(command+b'\n'+value+b'Exception> ')
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
    assert diagnostics.collect_exception(process,tmp_path)==result


@pytest.mark.parametrize('kind',['no-prompt','active-input','exited','empty-content','no-reply'])
def test_no_fake_monitor_success_and_no_input_owner_conflict(tmp_path,kind):
    console=tmp_path/'console.log';console.write_bytes(b'normal shell' if kind=='no-prompt' else b'Exception> ')
    wire=Wire(console,reply=kind!='no-reply',content=kind!='empty-content')
    process=SimpleNamespace(stdin=wire,poll=lambda:0 if kind=='exited' else None)
    if kind=='active-input':process._app_input_transport=object()
    result=diagnostics.collect_exception(process,tmp_path,per_command_seconds=.02)
    assert not result['available']
    if kind in ('no-prompt','active-input','exited'):assert not wire.bytes
    assert not result['firmware_resumed']


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
