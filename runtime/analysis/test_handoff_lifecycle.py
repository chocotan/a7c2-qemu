"""Host-only lifetime/branch and independent cleanup-channel regressions."""
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import threading
from types import SimpleNamespace

import pytest
import request_queue_watch as q


def scenario(variant):
    base=0x7f00000000;request=0x5000;obj=0x6000;manager=base+0x910a108
    entry_sp=0x800000;frame=entry_sp-0x90;root=0x7000;node=0x7100
    memory={request:struct.pack('<I',0x100)+bytes(20),request+0x770:b'\1',
            root:struct.pack('<3Q',node,node,1),node+0x10:struct.pack('<Q',obj)}
    raw=bytearray(40);struct.pack_into('<Q',raw,0,base+0x5b3ace0);raw[0x18]=1
    memory[obj]=bytes(raw)
    frames=[(0x24ccaa8,{'x19':request}), (0x248db58,{'x0':request}),
            (0x3110694,{'x0':obj,'x1':request+0x10}), (0x32425b8,{'x20':obj}),
            (0x3222ad0,{'x0':manager,'x1':obj,'x2':0x100,'x30':base+0x24ccadc,'sp':entry_sp})]
    branch=(0x3222b5c,{'x19':manager,'x21':obj,'x29':frame,'x0':0})
    group=(0x3222c18,{'x19':manager,'x29':frame,'x21':root,'x24':0})
    run=(0x33dccb8,{'x0':obj})
    if variant=='null-branch':frames += [branch,group,run]
    elif variant=='destroy-reuse':frames += [(0x33dcc7c,{'x0':obj}),branch,group,run]
    elif variant=='frame-reuse':
        frames += [(branch[0],dict(branch[1],x29=frame-16)),(0x24ccadc,{'sp':entry_sp}),branch,group,run]
    elif variant=='request-freed':frames=[(0x165ec50,{'x0':request}),*frames]
    else:raise AssertionError(variant)
    bps=[];stops=[];current={};events=[];reads=[]
    class Breakpoint:
        def __init__(self,address,type,internal):
            assert type==2 and internal
            self.address=int(address.removeprefix('*'),16);self.number=len(bps)+1
            self.condition=None;self.deleted=False;bps.append(self)
        def delete(self):self.deleted=True
    class Inferior:
        def read_memory(self,address,size):
            reads.append(address);raw=memory[address];assert len(raw)>=size;return raw[:size]
    def execute(command,**kwargs):
        assert command=='continue' and frames
        offset,regs=frames.pop(0);current.clear();current.update(regs)
        matches=[bp for bp in bps if not bp.deleted and bp.address==base+offset]
        assert len(matches)==1,(hex(offset),[(hex(bp.address),bp.deleted) for bp in bps])
        stops.append({'breakpoints':[matches[0].number]})
    gdb=SimpleNamespace(Breakpoint=Breakpoint,BP_HARDWARE_BREAKPOINT=2,selected_inferior=lambda:Inferior(),execute=execute)
    result={'hits':0}
    q.sequence_handoff(gdb,{'app_base':base,'limit':16},{'requests':[{'address':request}]},
                       lambda kind,**data:events.append((kind,data)),result,stops,lambda:dict(current))
    assert all(bp.deleted for bp in bps)
    return result,events,frames,reads


def test_null_hash_branch_reaches_group_without_waiting_for_b64():
    result,events,remaining,_=scenario('null-branch')
    assert result['same_object_group_enqueue_observed'] and result['target_run_observed'] and not remaining
    branch=next(data for kind,data in events if kind=='manager_map_branch')
    assert branch['raw_lookup_node']==0


def test_original_destruction_ends_identity_before_same_address_reuse():
    result,events,remaining,_=scenario('destroy-reuse')
    assert result['target_destroyed_before_run'] and not result['target_run_observed']
    assert len(remaining)==3 and not result.get('same_object_group_enqueue_observed')


def test_manager_frame_and_return_bound_the_invocation():
    result,events,remaining,_=scenario('frame-reuse')
    assert result['manager_returned_before_group_handoff']
    assert not result.get('target_run_observed') and len(remaining)==3


def test_request_release_stops_before_reused_request_or_object_reads():
    result,events,remaining,reads=scenario('request-freed')
    assert result['request_released_before_handoff'] and reads==[] and remaining


def test_debug_cleanup_uses_private_independent_QMP_channel(tmp_path):
    fd=os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY);server=socket.socket(socket.AF_UNIX)
    server.bind(f'/proc/self/fd/{fd}/{q.CONTROL_SOCKET}');server.listen(1);seen=[];errors=[]
    def peer():
        try:
            client,_=server.accept()
            with client,client.makefile('rwb') as stream:
                stream.write(b'{"QMP":{}}\n');stream.flush();running=False
                for _ in range(4):
                    message=json.loads(stream.readline());command=message['execute'];seen.append(command)
                    if command=='cont':running=True
                    result={} if command!='query-status' else {'running':running,'status':'running' if running else 'debug'}
                    stream.write((json.dumps({'return':result,'id':message['id']})+'\n').encode());stream.flush()
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=peer,daemon=True);thread.start()
    try:
        assert q.resume_owned_debug_cpu(fd)['cpu_running_verified']
        thread.join(5);assert not thread.is_alive() and errors==[]
        assert seen==['qmp_capabilities','query-status','cont','query-status']
    finally:server.close();os.close(fd)


def test_failed_CPU_resume_retains_lease_and_can_retry(tmp_path,monkeypatch):
    instance=q.QueueWatch.__new__(q.QueueWatch)
    instance.process=SimpleNamespace(poll=lambda:0);instance.fd=os.open(tmp_path,os.O_RDONLY|os.O_DIRECTORY)
    instance.log=None;instance.cleanup=None;fd=instance.fd
    def fail(_):raise OSError('cleanup channel unavailable')
    monkeypatch.setattr(q,'resume_owned_debug_cpu',fail)
    result=instance.stop();assert result['debugger_stopped'] and not result['safe_to_close']
    assert os.fstat(fd).st_ino==tmp_path.stat().st_ino
    with pytest.raises(RuntimeError,match='retain'):instance.check_exited()
    monkeypatch.setattr(q,'resume_owned_debug_cpu',lambda _:{'cpu_running_verified':True})
    assert instance.stop()['safe_to_close'] and instance.fd is None
    with pytest.raises(OSError):os.fstat(fd)


def test_private_control_mailbox_retained_only_when_requested():
    with q.RetainableTestDirectory() as lease:
        path=lease.path;(path/'geometry').write_text('{}')
    assert not path.exists()
    with q.RetainableTestDirectory() as lease:
        path=lease.path;(path/'geometry').write_text('{}');lease.retain=True
    try:assert path.is_dir() and (path/'geometry').is_file()
    finally:shutil.rmtree(path)


def test_current_queue_head_identity_is_read_at_the_owned_borrow():
    base=0x7f00000000;node=0x1000;obj=0x2000;meta=0x3000;manager=base+0x910a108
    vptr=base+0x5b3ad30;rtti=base+0x5b3ad08;name=base+0x4c3d3a0
    text=b'N5model17sequence_power_onE\0'
    memory={node+0x10:struct.pack('<Q',obj),obj:struct.pack('<QQ',vptr,meta),
            vptr-8:struct.pack('<Q',rtti),rtti+8:struct.pack('<Q',name),name:text.ljust(160,b'\0'),
            meta+8:struct.pack('<I4x3Q',0x10,0x100000005,0x555,manager)}
    reads=[]
    class Inferior:
        def read_memory(self,address,size):
            reads.append(address);raw=memory[address];assert len(raw)==size;return raw
    result=q.queued_head_identity(Inferior(),node,base,manager)
    assert result['sequence_id']==0x10 and result['type_name']=='N5model17sequence_power_onE'
    assert result['metadata_manager_matches'] and result['queued_head_only']
    memory[0x9000+0x78]=struct.pack('<Q',obj)
    active=q.group_active_identity(Inferior(),0x9000,base,manager)
    assert active['type_name']==result['type_name'] and active['group_lock_borrow']
    memory[0x9000+0x78]=bytes(8);reads.clear()
    assert q.group_active_identity(Inferior(),0x9000,base,manager)['active_slot_empty']
    assert reads==[0x9000+0x78]
    memory[obj]=struct.pack('<QQ',0,meta);reads.clear()
    assert q.queued_head_identity(Inferior(),node,base,manager)['type_unresolved']
    assert reads==[node+0x10,obj]
