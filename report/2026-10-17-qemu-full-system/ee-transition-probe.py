#!/usr/bin/env python3
"""Bounded original EE-path observation; no model writes or replacement replies."""
import hashlib
import json
from pathlib import Path
import re
import runpy

Base=runpy.run_path(str(Path(__file__).with_name('shutdown-watch.py')))['ShutdownWriteProbe']
POINTS={
    0x305e9c8:('boot-original-after-replayed-prologue',bytes.fromhex('81fa2e91')),
    0x305b5a0:('boot-work-callback-created',bytes.fromhex('e00313aa')),
    0x34b9134:('boot-work-worker-selected',bytes.fromhex('e103162a')),
    0x34b9524:('boot-work-worker-condition-wait',bytes.fromhex('db948697')),
    0x3062e3c:('boot-work-callback-entered',bytes.fromhex('ff0319d1')),
    0x34b9568:('boot-work-callback-returned',bytes.fromhex('601a40f9')),
    0x34b9578:('boot-work-completion-call-returned',bytes.fromhex('7f820039')),
    0x305e9e8:('boot-run-i-returned',bytes.fromhex('600a40f9')),
    0x305e9f0:('boot-publish-returned',bytes.fromhex('617640b9')),
    0x305ea4c:('boot-ee-cap-read-call',bytes.fromhex('cfcb1194')),
    0x305ea50:('boot-ee-cap-read-returned',bytes.fromhex('e10313aa')),
    0x305eb84:('boot-alternate-query-call',bytes.fromhex('f1ca1194')),
    0x305eb88:('boot-alternate-query-returned',bytes.fromhex('e00316aa')),
    0x305eaf0:('boot-final-checks-entered',bytes.fromhex('80138052')),
    0x305eb40:('boot-sequence-return-instruction',bytes.fromhex('c0035fd6')),
    0x3535a64:('boot-local-query-send-call',bytes.fromhex('1ba48497')),
    0x3535a68:('boot-local-query-send-returned',bytes.fromhex('80040034')),
    0x3531574:('boot-local-query-reply-source',bytes.fromhex('9f02006b')),
    0x248ff44:('mode-request-2f-dispatch',bytes.fromhex('fd7bbea9')),
    0x2483104:('osd-request-4df-dispatch',bytes.fromhex('fd7bbea9')),
    0x320d77c:('mode-transition-constructor',bytes.fromhex('ffc303d1')),
    0x3228c98:('mode-transition-constructor-returned',bytes.fromhex('f71b40f9')),
    0x3228cbc:('mode-transition-scheduler-transfer',bytes.fromhex('85e7ff17')),
    0x3222c34:('mode-transition-enqueued-and-notified',bytes.fromhex('a06740b9')),
    0x33aa0d0:('mode-transition-run',bytes.fromhex('fd7bb6a9')),
    0x33aa9e8:('mode-transition-entry-gate',bytes.fromhex('a00a43b9')),
    0x339d44c:('enter-rec-still',bytes.fromhex('ff033ad1')),
    0x339fc70:('rec-still-ee-commit',bytes.fromhex('4ab7ff97')),
    0x33a5b08:('alternate-ee-commit',bytes.fromhex('a49fff97')),
    0x3546040:('start-ee-3003-request',bytes.fromhex('fd7bbba9')),
}
OBJECT_POINTS={
    0xee358:('camera-background-local-query-consumed',bytes.fromhex('fd7bbda9')),
    0xed9c4:('camera-background-cp-control-entered',bytes.fromhex('fd7bbaa9')),
    0xeda4c:('camera-background-cp-send-call',bytes.fromhex('39b3fd97')),
    0xeda50:('camera-background-cp-send-returned',bytes.fromhex('20fdff35')),
    0xeda88:('camera-background-cp-receive-call',bytes.fromhex('a2b3fd97')),
    0xed4ec:('camera-background-local-reply-entered',bytes.fromhex('fd7bbba9')),
}


class EeTransitionProbe(Base):
    KIND='ee-transition'
    LIMIT=64

    def __init__(self,run,connect):
        self.breakpoints={}
        self.enqueue_origins={}
        self.boot_callbacks={}
        self.boot_workers={}
        self.boot_sequences=set()
        self.local_query_sends={}
        self.points=dict(POINTS)
        self.object_offsets={}
        self.libobj_base=None
        self.background_objects=set()
        self.current_stop=None
        self.probe_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.armed=False
        super().__init__(run,connect)

    def memory(self,address,size):
        try:return super().memory(address,size)
        except (RuntimeError,ValueError) as error:
            with (self.run/'ee-transition-memory-errors.jsonl').open('a') as out:
                out.write(json.dumps({'address':hex(address),'bytes':size,'error':str(error),
                    'last_stop':self.current_stop,'appfw_base':hex(self.base) if hasattr(self,'base') else None,
                    'libobj_base':hex(self.libobj_base) if self.libobj_base else None,
                    'note':'Failed read preserved; caller may handle the error. This record alone is not a fatal guest event.'})+'\n')
            raise

    def save(self):
        (self.run/'ee-transition-summary.json').write_text(json.dumps({
            'pid_from_observer':getattr(self,'pid',None),'hits':self.writes,
            'armed':self.armed,'arm_boundary':'first observed OBSERVER_READY',
            'limit':self.LIMIT,'limit_reached':self.writes>=self.LIMIT,
            'pending_enqueue_origins':len(self.enqueue_origins),
            'pending_local_query_sends':len(self.local_query_sends),
            'libobj_base':hex(self.libobj_base) if self.libobj_base else None,
            'camera_background_points_armed':bool(self.object_offsets),
            'probe_source_sha256':self.probe_source_sha256,
            'writes_guest_model':False,'capture_verified':False,
            'method':'QEMU-original-instruction-execution-breakpoints',
            'coverage_note':'No hit does not exclude execution before arming or after the explicit hit limit'},indent=2)+'\n')

    def sequence_snapshot(self,obj):
        header=self.memory(obj,16)
        descriptor=int.from_bytes(header[8:16],'little')
        raw=self.memory(descriptor,0x1b8)
        begin,end,capacity=(int.from_bytes(raw[i:i+8],'little') for i in (0x1a0,0x1a8,0x1b0))
        if not (begin<=end<=capacity) or (end-begin)%24 or (capacity-begin)%24 or (not begin and capacity):
            raise ValueError('Original dependency vector has invalid bounds')
        result={'pointer':hex(obj),'header_hex':header.hex(),'descriptor_pointer':hex(descriptor),
                'descriptor_hex':raw.hex(),'dependencies':[],'dependencies_truncated':end-begin>4*24}
        for entry in range(begin,min(end,begin+4*24),24):
            data=self.memory(entry,24);state=int.from_bytes(data[:8],'little')
            if not state:raise ValueError('Original dependency state pointer is null')
            status=int.from_bytes(self.memory(state+0x10,4),'little')
            result['dependencies'].append({'entry_pointer':hex(entry),'entry_hex':data.hex(),
                'state_pointer':hex(state),'predecessor_tag':hex(int.from_bytes(data[16:20],'little')),
                'state_word':hex(status),'ready':status&0x7fffffff==1})
        return result

    def check(self):
        if self.finished:return
        if self.target is None:
            match=re.search(rb'OBS OBSERVER_READY pid=(\d+) base=(0x[0-9a-f]+)',
                            (self.run/'console.log').read_bytes())
            if not match:return
            self.pid,self.base=int(match[1]),int(match[2],16)
            self.stop_vm()
            if 's' not in self.request('vCont?').split(';')[1:]:
                raise RuntimeError('EE observation requires directed vCont single step')
            obj=re.search(rb'OSD_PROBES_ARMED libObj=(0x[0-9a-f]+)',(self.run/'console.log').read_bytes())
            if obj:
                self.libobj_base=int(obj[1],16)
                for offset,definition in OBJECT_POINTS.items():
                    relative=self.libobj_base+offset-self.base
                    if relative in self.points:raise ValueError('Cross-image observation addresses overlap')
                    self.points[relative]=definition;self.object_offsets[relative]=offset
            for offset in self.points:
                if offset==0x3222c34:continue
                address=self.base+offset
                if self.request(f'Z0,{address:x},4')!='OK':raise RuntimeError('Cannot arm EE execution observation')
                self.breakpoints[address]=offset
            self.target=self.base
            self.armed=True;self.save()
            self.pending=None;self.request('Hc-1');self.send('c');return
        reason=self.pending or self.receive(0);self.pending=None
        if not reason:return
        if not reason.startswith(('T','S')):raise RuntimeError('Unexpected EE debugger response')
        thread=re.search(r'thread:([^;]+)',reason)
        if thread:self.request('Hg'+thread[1]);self.request('Hc'+thread[1])
        registers=self.registers();pc=registers['pc']
        self.current_stop={'reason':reason,'pc':hex(pc),'registers':{k:hex(v) for k,v in registers.items()}}
        if pc not in self.breakpoints:raise RuntimeError('EE probe stopped away from declared instructions')
        offset=self.breakpoints[pc];name,expected=self.points[offset]
        object_offset=self.object_offsets.get(offset)
        if self.memory(pc,4)!=expected:raise ValueError('Original EE instruction identity differs')
        origin_key=(thread[1] if thread else None,registers['x19'],registers['x29'])
        selected=offset!=0x3222c34 or (origin_key in self.enqueue_origins and int.from_bytes(self.memory(registers['x29']+0x64,4),'little')==0x2f)
        if offset==0x34b9134:selected=registers['x20'] in self.boot_callbacks
        if offset in (0x34b9524,0x34b9568,0x34b9578):selected=registers['x19'] in self.boot_workers
        if offset==0x3062e3c:selected=registers['x0'] in self.boot_sequences
        send_key=(thread[1] if thread else None,registers['x29'])
        if offset==0x3535a64:
            selected=registers['x0']==0x8102021f
            if selected:
                query=self.memory(registers['x1'],20)
                selected=query==bytes.fromhex('1000000020000000'+'00'*12)
        if offset==0x3535a68:selected=send_key in self.local_query_sends
        if offset==0x3531574:selected=registers['x20']==0x8102021f
        if object_offset==0xee358:
            selected=registers['x2']==0x80020002
            if selected:selected=self.memory(registers['x1'],8)==bytes.fromhex('1000000020000000')
        if object_offset==0xed9c4:selected=registers['x0'] in self.background_objects and registers['x1'] in (0x3006,0x3007)
        if object_offset in (0xeda4c,0xeda50,0xeda88):selected=registers['x21'] in self.background_objects and registers['x20'] in (0x3006,0x3007)
        if object_offset==0xed4ec:selected=registers['x0'] in self.background_objects and registers['x1']==0x20 and registers['x3']==0x80020002
        if offset==0x305b5a0:
            raw_callback=self.memory(registers['x1'],32)
            if int.from_bytes(raw_callback[:8],'little')!=self.base+0x5b30e48:
                raise ValueError('Original boot callback vptr differs')
            self.boot_callbacks.pop(registers['x1'],None)
            selected=int.from_bytes(raw_callback[16:24],'little')==self.base+0x3062e3c
        if selected:self.writes+=1
        record={'hit':self.writes,'point':name,'elf_pc':hex(offset),'stop_reason':reason,
                'registers':{key:hex(value) for key,value in registers.items()},
                'frames':self.frames(registers['x29']),'instruction_hex':expected.hex(),
                'ee_before':int.from_bytes(self.memory(self.base+0x7e67700,4),'little')}
        if object_offset is not None:
            record['image']='libObj.so';record['elf_pc']=hex(object_offset)
        if object_offset==0xee358 and selected:
            self.background_objects.add(registers['x0'])
            record['camera_background']={'self':hex(registers['x0']),
                'state':int.from_bytes(self.memory(registers['x0']+8,4),'little'),
                'source':hex(registers['x2']),'request_header_hex':self.memory(registers['x1'],8).hex()}
        if object_offset==0xed9c4 and selected:
            record['camera_background']={'self':hex(registers['x0']),'cp_command':hex(registers['x1'])}
        if object_offset==0xeda4c and selected:
            record['camera_background']={'self':hex(registers['x21']),'destination':hex(registers['x0']),
                'cp_request_pointer':hex(registers['x1']),'cp_request_hex':self.memory(registers['x1'],24).hex(),
                'reply_sid':hex(int.from_bytes(self.memory(registers['x29']+0x4c,4),'little'))}
        if object_offset==0xeda50 and selected:
            rc=registers['x0']&0xffffffff
            record['camera_background']={'self':hex(registers['x21']),'original_cp_send_rc':rc if rc<0x80000000 else rc-0x100000000,'transport_only':True}
        if object_offset==0xeda88 and selected:
            record['camera_background']={'self':hex(registers['x21']),'receive_sid':hex(registers['x0']),
                'timeout':hex(registers['x2']&0xffffffff),'cp_command':hex(registers['x20'])}
        if object_offset==0xed4ec and selected:
            record['camera_background']={'self':hex(registers['x0']),'opcode':hex(registers['x1']),
                'original_reply_value':hex(registers['x2']),'destination':hex(registers['x3'])}
        if offset==0x305e9c8:
            if registers['x20']!=self.base+0x4c14000:
                raise ValueError('Original boot prologue page address differs')
            record['original_boot_page_address']=hex(registers['x20'])
            record['original_saved_x19_x20_hex']=self.memory(registers['sp']+0x10,16).hex()
            record['boot_entry_hex']=self.memory(self.base+0x305e9b8,16).hex()
            record['boot_entry_matches_unpatched_original']=record['boot_entry_hex']=='fd7bb7a9fd030091f35301a9b4dd00d0'
        if offset==0x305b5a0 and selected:
            callback=registers['x1'];raw=raw_callback
            sequence=int.from_bytes(raw[8:16],'little')
            self.boot_callbacks[callback]=sequence
            self.boot_sequences.add(sequence)
            record['boot_callback']={'pointer':hex(callback),'sequence_pointer':hex(sequence),'header_hex':raw.hex()}
        if offset==0x34b9134 and selected:
            worker=registers['x0'];sequence=self.boot_callbacks.pop(registers['x20'])
            self.boot_workers[worker]={'callback_pointer':hex(registers['x20']),
                'sequence_pointer':hex(sequence),'completion_pointer':hex(registers['x21'])}
            record['boot_worker']={'pointer':hex(worker),'callback_pointer':hex(registers['x20']),
                'sequence_pointer':hex(sequence),'header_hex':self.memory(worker,0x38).hex(),
                'completion_pointer':hex(registers['x21']),'completion_header_hex':self.memory(registers['x21'],0x28).hex()}
        if offset==0x34b9524 and selected:
            worker=registers['x19'];raw=self.memory(worker,0x38)
            if raw[0x20]!=0:raise ValueError('Original worker wait gate differs')
            record['boot_worker']={'pointer':hex(worker),'header_hex':raw.hex(),'wait_object':hex(worker+0x68)}
        if offset==0x3062e3c and selected:
            record['boot_callback_sequence_pointer']=hex(registers['x0'])
        if offset in (0x34b9568,0x34b9578) and selected:
            worker=registers['x19'];raw=self.memory(worker,0x38);origin=self.boot_workers[worker]
            if int.from_bytes(raw[0x28:0x30],'little')!=int(origin['callback_pointer'],16) or int.from_bytes(raw[0x30:0x38],'little')!=int(origin['completion_pointer'],16):
                raise ValueError('Original worker callback ownership differs')
            record['boot_worker']={'pointer':hex(worker),'header_hex':raw.hex(),'origin':origin,
                'completion_header_hex':self.memory(int(origin['completion_pointer'],16),0x28).hex()}
            if offset==0x34b9578:self.boot_workers.pop(worker)
        if offset in (0x305e9e8,0x305e9f0):
            record['boot_sequence_pointer']=hex(registers['x19'])
            raw=self.memory(registers['x19']+0x68,28)
            record['boot_branch_fields_68_to_80_hex']=raw.hex()
            cap,attribute,reason=(int.from_bytes(raw[i:i+4],'little') for i in (0,12,24))
            record['original_ee_cap_read_branch']={'field_68':cap,'field_74':attribute,'field_80':reason,
                'condition_matches':attribute!=1 and cap in (1,2) and reason==0x1b}
        if offset in (0x305ea4c,0x305ea50):
            record['ee_cap_call_frame']=hex(registers['x29'])
            record['ee_cap_control_hex']=self.memory(registers['x29']+0x48,8).hex()
            if offset==0x305ea50:
                record['original_ee_cap_returned_value']=int.from_bytes(self.memory(registers['x29']+0x50,4),'little')
        if offset in (0x305eb84,0x305eb88):
            record['alternate_query_frame']=hex(registers['x29'])
            if offset==0x305eb88:
                record['original_alternate_query_value']=int.from_bytes(self.memory(registers['x29']+0x58,4),'little')
        if offset==0x305eb40:
            record['original_boot_return_address']=hex(registers['x30'])
        if offset==0x3535a64 and selected:
            self.local_query_sends[send_key]=registers['x1']
            record['local_query']={'destination':'0x8102021f','request_pointer':hex(registers['x1']),
                'request_hex':query.hex(),'scheduler_frame':hex(registers['x29'])}
        if offset==0x3535a68 and selected:
            rc=registers['x0']&0xffffffff
            record['local_query']={'request_pointer':hex(self.local_query_sends.pop(send_key)),
                'original_send_rc':rc if rc<0x80000000 else rc-0x100000000,'transport_only':True}
        if offset==0x3531574 and selected:
            raw=self.memory(registers['x19'],8)
            record['local_query_reply']={'source':'0x8102021f','message_pointer':hex(registers['x19']),
                'header_8_hex':raw.hex(),'key_20_type_11':raw[0]==0x11 and int.from_bytes(raw[4:6],'little')==0x20,
                'actual_message_size_verified':False}
        if offset==0x33aa9e8:
            record['entry_gate_value']=int.from_bytes(self.memory(registers['x21']+0x308,4),'little')
            raw=self.memory(registers['x19']+0x724,16)
            record['original_transition_words_724_to_730']=[int.from_bytes(raw[i:i+4],'little') for i in range(0,16,4)]
        if offset in (0x248ff44,0x2483104):
            raw=self.memory(registers['x0'],24)
            tag=int.from_bytes(raw[:4],'little')
            if tag!=(0x2f if offset==0x248ff44 else 0x4df):
                raise ValueError('Original request tag differs from its dispatch entry')
            record['request']={'pointer':hex(registers['x0']),'tag':hex(tag),'header_hex':raw.hex(),
                               'accepted_byte_770':self.memory(registers['x0']+0x770,1).hex()}
            record['batch_collection_enabled']=int.from_bytes(self.memory(self.base+0x7e4e608,1),'little')
            record['pending_request_batch_queue_hex']=self.memory(self.base+0x7e4e5d0,24).hex()
        if offset in (0x3228c98,0x3228cbc) or (offset==0x3222c34 and selected):
            if offset!=0x3222c34:
                obj=registers['x20'] if offset==0x3228c98 else registers['x1']
                record['sequence']=self.sequence_snapshot(obj)
                if int.from_bytes(bytes.fromhex(record['sequence']['header_hex'])[:8],'little')!=self.base+0x5b38978:
                    raise ValueError('Original mode sequence vptr differs')
            if offset!=0x3228c98:
                manager=registers['x0'] if offset==0x3228cbc else registers['x19']
                queue=manager+0x320;raw=self.memory(queue,24)
                record['queue0']={'manager':hex(manager),'header_hex':raw.hex(),'nodes':[]}
                active=int.from_bytes(self.memory(queue+0x78,8),'little')
                record['queue0']['active']=self.sequence_snapshot(active) if active else None
                node=int.from_bytes(raw[:8],'little');seen=set()
                for _ in range(4):
                    if node==queue:break
                    if not node or node in seen:raise ValueError('Original sequence queue has invalid sampled links')
                    seen.add(node);data=self.memory(node,24);task=int.from_bytes(data[16:24],'little')
                    record['queue0']['nodes'].append({'pointer':hex(node),'header_hex':data.hex(),
                        'sequence':self.sequence_snapshot(task)})
                    node=int.from_bytes(data[:8],'little')
                record['queue0']['sample_truncated']=node!=queue
            if offset==0x3228cbc:
                if not thread:raise RuntimeError('Mode scheduler origin has no debugger thread')
                self.enqueue_origins[thread[1],manager,registers['sp']-0x90]=obj
                follow=self.base+0x3222c34
                if follow not in self.breakpoints:
                    if self.request(f'Z0,{follow:x},4')!='OK':raise RuntimeError('Cannot arm original enqueue followup')
                    self.breakpoints[follow]=0x3222c34
            if offset==0x3222c34:
                record['origin']={'thread':origin_key[0],'manager':hex(origin_key[1]),
                    'scheduler_frame':hex(origin_key[2]),'sequence_pointer':hex(self.enqueue_origins.pop(origin_key))}
        if selected:
            with (self.run/'ee-transition-hits.jsonl').open('a') as out:out.write(json.dumps(record)+'\n')
        if self.request(f'z0,{pc:x},4')!='OK':raise RuntimeError('Cannot remove EE hit breakpoint')
        self.breakpoints.pop(pc)
        if self.writes>=self.LIMIT:
            self.remove_all();self.finished=True
        else:
            if not thread:raise RuntimeError('Original EE step has no debugger thread')
            self.send('vCont;s:'+thread[1]);step=self.receive(5)
            successor=0x338d998 if offset in (0x339fc70,0x33a5b08) else 0x3222ad0 if offset==0x3228cbc else 0x165e890 if offset==0x34b9524 else 0x34d1988 if offset==0x305ea4c else 0x34d1748 if offset==0x305eb84 else offset+4
            if offset==0x3535a64:successor=0x165ead0
            if offset==0x3535a68:successor=0x3535af8 if registers['x0']&0xffffffff==0 else offset+4
            if object_offset==0xeda4c:successor=self.libobj_base+0x5a730-self.base
            if object_offset==0xeda50:successor=self.libobj_base+0xed9f4-self.base if registers['x0']&0xffffffff else offset+4
            if object_offset==0xeda88:successor=self.libobj_base+0x5a910-self.base
            expected_pc=registers['x30'] if offset==0x305eb40 else self.base+successor
            after=self.registers() if step and step[:3] in ('T05','S05') else None
            stepped_thread=re.search(r'thread:([^;]+)',step or '')
            trace={'hit':self.writes,'point':name,'original_stop':reason,'step_stop':step,
                'selected_thread':thread[1],'expected_pc':hex(expected_pc),
                'registers_before':record['registers'],'registers_after':{k:hex(v) for k,v in after.items()} if after else None}
            if after is None or after['pc']!=expected_pc or (stepped_thread and stepped_thread[1]!=thread[1]):
                (self.run/'ee-transition-step-failure.json').write_text(json.dumps(trace,indent=2)+'\n')
                raise RuntimeError('Original EE step did not reach its verified successor')
            if selected:
                with (self.run/'ee-transition-steps.jsonl').open('a') as out:out.write(json.dumps(trace)+'\n')
            if offset!=0x3222c34 or self.enqueue_origins:
                if self.request(f'Z0,{pc:x},4')!='OK':raise RuntimeError('Cannot re-arm EE observation')
                self.breakpoints[pc]=offset
        self.save();self.request('Hc-1');self.send('c')

    def remove_all(self):
        for address in list(self.breakpoints):
            if self.request(f'z0,{address:x},4')!='OK':raise RuntimeError('Cannot remove EE observation')
            self.breakpoints.pop(address)

    def end_observation(self):
        if self.breakpoints:
            self.stop_vm();self.remove_all();self.pending=None
            self.request('Hc-1');self.send('c')
        self.finished=True;self.save();self.close()
