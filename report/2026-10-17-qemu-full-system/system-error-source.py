#!/usr/bin/env python3
"""Capture the original MODEL_SYSTEM_ERROR sender; no replacement event."""
import hashlib
import json
from pathlib import Path
import re
import runpy

Base=runpy.run_path(str(Path(__file__).with_name('shutdown-watch.py')))['ShutdownWriteProbe']


class SystemErrorSourceProbe(Base):
    OFFSET=0x24cb2d4  # Original send_event_to_main(const event&).
    KIND='system-error-source'
    BREAKPOINT_KIND=0

    def check(self):
        if self.finished:return
        if self.target is None:
            match=re.search(rb'OBS OBSERVER_READY pid=(\d+) base=(0x[0-9a-f]+)',(self.run/'console.log').read_bytes())
            if not match:return
            self.pid,self.base=int(match[1]),int(match[2],16)
            self.target=self.base+self.OFFSET
            self.stop_vm()
            if self.request(f'Z0,{self.target:x},4')!='OK':raise RuntimeError('Cannot arm original main-event sender observation')
            (self.run/'system-error-source-armed.json').write_text(json.dumps({
                'pid':self.pid,'appfw_base':hex(self.base),'entry':hex(self.OFFSET),
                'probe_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'writes_guest_model':False},indent=2)+'\n')
            self.pending=None;self.send('c')
        reason=self.pending or self.receive(0);self.pending=None
        if not reason:return
        if not reason.startswith(('T','S')):raise RuntimeError('Unexpected main-event debugger response: '+reason)
        thread=re.search(r'thread:([^;]+)',reason)
        if thread:self.request('Hg'+thread[1]);self.request('Hc'+thread[1])
        regs=self.registers()
        if regs['pc']!=self.target:raise RuntimeError('Main-event probe stopped away from original entry: '+reason)
        event=self.memory(regs['x0'],0x1c)
        code=int.from_bytes(event[:4],'little');self.writes+=1
        if self.request(f'z0,{self.target:x},4')!='OK':raise RuntimeError('Cannot remove main-event observation breakpoint')
        if code==0x0100012e:
            caller=regs['x30']-self.base
            record={'pid_from_observer':self.pid,'appfw_base':hex(self.base),'event_code':hex(code),
                    'original_event_hex':event.hex(),'caller_elf':hex(caller),'stop_reason':reason,
                    'registers':{k:hex(v) for k,v in regs.items()},'frames':self.frames(regs['x29']),
                    'events_examined':self.writes,'method':'QEMU-original-send-event-entry-no-replacement-event'}
            # Only this proven dispatcher branch guarantees x20 points to the
            # Infra notification whose first u32 it parsed. Do not guess pointers.
            if 0x2dbf3f8<=caller<=0x2dbf460:
                try:record['infra_notification_first_u32']=hex(int.from_bytes(self.memory(regs['x20'],4),'little'))
                except (RuntimeError,ValueError) as error:record['infra_notification_read_error']=str(error)
            (self.run/'original-system-error-source.json').write_text(json.dumps(record,indent=2)+'\n')
            self.captured=self.finished=True
            self.request('Hc-1');self.send('c');return
        if self.writes<=8 or not self.writes&(self.writes-1):
            with (self.run/'main-events-sampled.jsonl').open('a') as out:
                out.write(json.dumps({'count':self.writes,'event':hex(code),'caller_elf':hex(regs['x30']-self.base)})+'\n')
        if self.writes>=4096:
            self.finished=True
            (self.run/'system-error-source-limit.json').write_text(json.dumps({'events':self.writes,'cause_verified':False})+'\n')
            self.request('Hc-1');self.send('c');return
        # Execute the original first instruction before re-arming at its address.
        self.send('s');stepped=self.receive(5)
        if not stepped or not stepped.startswith(('T','S')):raise RuntimeError('Original event-entry single-step failed')
        if self.request(f'Z0,{self.target:x},4')!='OK':raise RuntimeError('Cannot re-arm original event sender')
        self.request('Hc-1');self.send('c')
