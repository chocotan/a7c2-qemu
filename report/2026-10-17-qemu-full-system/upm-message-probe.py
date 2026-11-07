#!/usr/bin/env python3
"""Read-only QEMU breakpoint observer of original kernel UPM receive/use/free.

The producer is explicitly diagnostic. Nothing here executes CP code, patches
firmware bytes, or substitutes for the fourth connection's native acceptance.
"""
import hashlib
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent
Base=runpy.run_path(str(HERE/'boot-fatal-probe.py'))['BootFatalProbe']
UPM_SHA='a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb'
POINTS=(0x138,0x140,0x14c)
GUARDS={0xe0:bytes.fromhex('fd7bbda9fd030091f30b00f953ae8052'),
        0x138:bytes.fromhex('a01340f9'),0x140:bytes.fromhex('a11340f9'),
        0x14c:bytes.fromhex('eaffff17')}


def target_boundary(console):
    return re.search(rb'OBS FULL_HDMIPIN_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*bytes=56 rc=0\b',console)


class RecordingSocket:
    """Bounded private wire diagnostics; semantic evidence uses decoded data."""
    def __init__(self,socket,path):self.socket=socket;self.path=path;self.count=0
    def note(self,direction,data):
        self.count+=1
        if self.count>4000:return
        item={'sequence':self.count,'direction':direction,'bytes':len(data),
              'head_hex':data[:2048].hex(),'sha256':hashlib.sha256(data).hexdigest()}
        if self.count==4000:item['trace_limit_reached']=True
        with self.path.open('a') as out:out.write(json.dumps(item)+'\n')
    def sendall(self,data):self.note('send',data);return self.socket.sendall(data)
    def recv(self,size):
        data=self.socket.recv(size);self.note('receive',data);return data
    def fileno(self):return self.socket.fileno()
    def close(self):return self.socket.close()


def verified_effect(record):
    """Strict receive/API/free and exact first-matching-node semantics."""
    before=bytes.fromhex(record['received_raw']);after=bytes.fromhex(record['processed_raw'])
    if len(before)!=16 or len(after)!=16:return False
    words=lambda b:[int.from_bytes(b[i:i+4],'little') for i in range(0,16,4)]
    command,selector,qid,padding=words(before)
    if command!=0x920117 or selector not in (0,2) or qid!=0x9a0000 or padding:return False
    effective=3 if selector==2 and record['config_after']!=0 else selector
    if words(after)!=[command,effective,qid,padding]:return False
    if 'message_refs_before_free' in record and not 1<=record['message_refs_before_free']<=0xffff:return False
    expected=list(record['ng_before'])
    for index,node in enumerate(expected):
        if node['qid']==qid and node['selector']==effective:
            del expected[index];break
    return (record['ng_after']==expected and record['free_rc']==0 and
            record['receive_frame']==record['process_frame']==record['free_frame'] and
            record['received_pointer']==record['processed_pointer']==record['freed_pointer'])


class UpmMessageProbe(Base):
    def __init__(self,run,connect,module):
        if hashlib.sha256(Path(module).read_bytes()).hexdigest()!=UPM_SHA:
            raise ValueError('UPM observer requires the exact original module')
        self.sections=None;self.current=None;self.records=[];self.completed=False
        self.skipped=0;self.breakpoints=[]
        super().__init__(run,connect)
        self.socket=RecordingSocket(self.socket,self.run/'upm-rsp-wire.jsonl')

    def save(self):
        (self.run/'upm-message-observation.json').write_text(json.dumps({
            'module_sha256':UPM_SHA,'sections':self.sections,'records':self.records,
            'in_flight':self.current,'unrelated_received':self.skipped,
            'two_notifications_consumed':self.completed,'original_cp_task_running':False,
            'fourth_connection_verified':False,'camera_startup_verified':False,
            'method':'QEMU-read-only-execution-breakpoints-original-kernel-module'},indent=2)+'\n')

    def memory(self,address,size):
        if not 0xffffff8000000000<=address or not 0<size<=4096 or address+size>0xffffffffffffffff:
            raise ValueError('UPM observer refuses a non-kernel or unbounded read')
        raw=bytes.fromhex(self.request(f'm{address:x},{size:x}'))
        if len(raw)!=size:raise ValueError('UPM short kernel memory read')
        return raw

    def word(self,address,size=8):return int.from_bytes(self.memory(address,size),'little')

    def ng(self):
        head=self.sections['bss']+0x7c0+0xa0
        current,tail=self.word(head),self.word(head+8);previous=head;rows=[];visited=set()
        while current!=head:
            if current in visited or len(visited)>=128:raise ValueError('UPM NG list invalid or exceeds explicit bound')
            visited.add(current);raw=self.memory(current,24)
            following=int.from_bytes(raw[:8],'little');back=int.from_bytes(raw[8:16],'little')
            if back!=previous:raise ValueError('UPM NG backlink mismatch')
            rows.append({'address':hex(current),'qid':int.from_bytes(raw[16:20],'little'),
                         'selector':int.from_bytes(raw[20:24],'little')})
            previous,current=current,following
        if tail!=previous:raise ValueError('UPM NG head tail mismatch')
        return rows

    def stop_registers(self,reason):
        thread=re.search(r'thread:([^;]+)',reason)
        if thread:
            self.request('Hg'+thread[1]);self.request('Hc'+thread[1])
        raw=bytes.fromhex(self.request('g'))
        if len(raw)<268:raise ValueError('UPM short AArch64 registers')
        return [int.from_bytes(raw[i:i+8],'little') for i in range(0,264,8)]

    def resume_hit(self,pc,frame):
        if self.request(f'z0,{pc:x},4')!='OK':raise RuntimeError('Cannot remove UPM step breakpoint')
        self.send('s');reason=self.receive(5)
        if not reason or reason[:3] not in ('T05','S05'):raise RuntimeError('UPM single step did not produce a debug stop')
        registers=self.stop_registers(reason)
        expected={0x138:0x13c,0x140:0x144,0x14c:0xf4}[pc-self.sections['text']]+self.sections['text']
        if registers[32]!=expected or registers[29]!=frame or registers[19]!=0x80920572:
            raise ValueError('UPM single step changed receiver identity or did not reach the exact original successor')
        if self.request(f'Z0,{pc:x},4')!='OK':raise RuntimeError('Cannot restore UPM breakpoint')
        self.pending=None;self.send('c')

    def check(self):
        if self.completed:return
        if self.sections is None:
            data=(self.run/'console.log').read_bytes()
            match=re.search(rb'(?:^|\n)UPM_PROBE_SECTIONS text=(0x[0-9a-f]+) bss=(0x[0-9a-f]+) data=(0x[0-9a-f]+)\r?(?:\n|$)',data)
            boundary=target_boundary(data)
            if not match or not boundary:return
            self.socket.sendall(b'\x03')
            reason=self.receive(5)
            if not reason or not reason.startswith(('T','S')):raise RuntimeError('Cannot pause UPM observation')
            self.sections=dict(zip(('text','bss','data'),(int(v,16) for v in match.groups())))
            registers=self.stop_registers(reason)
            (self.run/'upm-arm-context.json').write_text(json.dumps({
                'stop_reason':reason,'registers':{('x'+str(i)) if i<31 else ('sp' if i==31 else 'pc'):hex(v)
                    for i,v in enumerate(registers)},'sections':self.sections,
                'original_hdmi_pin_free_offset':boundary.end(),
                'original_cp_task_running':False},indent=2)+'\n')
            for offset,expected in GUARDS.items():
                if self.memory(self.sections['text']+offset,len(expected))!=expected:
                    raise ValueError('Original UPM instruction identity mismatch at '+hex(offset))
            self.breakpoints=[self.sections['text']+offset for offset in POINTS]
            for pc in self.breakpoints:
                if self.request(f'Z0,{pc:x},4')!='OK':raise RuntimeError('QEMU refused original UPM breakpoint')
            self.save();self.pending=None;self.send('c');return
        reason=self.pending or self.receive(0);self.pending=None
        if not reason:return
        if reason[:3] not in ('T05','S05'):raise RuntimeError('Unexpected UPM debugger signal')
        registers=self.stop_registers(reason);pc=registers[32];offset=pc-self.sections['text']
        if offset not in POINTS:raise RuntimeError('QEMU stopped outside original UPM observation points')
        frame=registers[29]
        if registers[19]!=0x80920572:raise ValueError('UPM receiver SID register mismatch')
        pointer=self.word(frame+0x20)
        if offset==0x138:
            raw=self.memory(pointer,16)
            if raw[:4]!=bytes.fromhex('17019200') or raw[8:12]!=bytes.fromhex('00009a00'):
                if self.current:raise ValueError('UPM interleaved receive before previous free')
                self.skipped+=1
            else:
                if self.current:raise ValueError('UPM duplicate receive without original free')
                self.current={'received_raw':raw.hex(),'received_pointer':hex(pointer),
                              'receive_frame':hex(frame),'ng_before':self.ng(),
                              'config_before':self.word(self.sections['data']+0x278,4)}
        elif self.current:
            record=self.current
            if hex(pointer)!=record['received_pointer'] or hex(frame)!=record['receive_frame']:
                raise ValueError('UPM message or original receiver frame changed')
            if offset==0x140:
                if 'processed_raw' in record:raise ValueError('UPM duplicate API return')
                record.update(processed_raw=self.memory(pointer,16).hex(),processed_pointer=hex(pointer),
                              process_frame=hex(frame),ng_after=self.ng(),
                              config_after=self.word(self.sections['data']+0x278,4),
                              message_refs_before_free=self.word(pointer-0xe,2))
            else:
                if 'processed_raw' not in record:raise ValueError('UPM original message free preceded API return')
                rc=registers[0]&0xffffffff;rc=rc-(1<<32) if rc&(1<<31) else rc
                record.update(freed_pointer=hex(pointer),free_frame=hex(frame),free_rc=rc)
                record['effect_verified']=verified_effect(record)
                self.records.append(record);self.current=None
                if not record['effect_verified']:
                    self.save();raise ValueError('Original UPM side effect or message-free verification failed')
                selectors=[int.from_bytes(bytes.fromhex(r['received_raw'])[4:8],'little') for r in self.records]
                if selectors==[0,2]:
                    self.completed=True
                    for address in self.breakpoints:
                        if self.request(f'z0,{address:x},4')!='OK':raise RuntimeError('Cannot disarm UPM breakpoints')
                    self.save();self.send('c');return
                if selectors!=[0]:raise ValueError('Unexpected original UPM diagnostic message sequence')
        self.save();self.resume_hit(pc,frame)
