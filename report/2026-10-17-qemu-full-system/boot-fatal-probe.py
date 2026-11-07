#!/usr/bin/env python3
"""Observe original fatal arguments using a QEMU execution breakpoint only."""
import json
import re
import select
import socket
import time


class BootFatalProbe:
    OFFSET=0x305b974

    def __init__(self,run,connect):
        self.run=run;self.target=None;self.captured=False;self.pending=None;self.buffer=b''
        self.socket=socket.socket(socket.AF_UNIX);self.socket.settimeout(5)
        connect(self.socket,run,'fatal-gdb.sock')
        self.request('?',stop=True)
        self.request('qC')
        self.pending=None
        self.send('c')

    def send(self,text):
        data=text.encode('ascii')
        self.socket.sendall(b'$'+data+b'#'+f'{sum(data)&255:02x}'.encode())

    def receive(self,timeout):
        until=time.monotonic()+timeout
        while True:
            start=self.buffer.find(b'$')
            if start>=0:
                end=self.buffer.find(b'#',start+1)
                if end>=0 and len(self.buffer)>=end+3:
                    packet=self.buffer[start+1:end];check=self.buffer[end+1:end+3]
                    self.buffer=self.buffer[end+3:]
                    if sum(packet)&255!=int(check,16):
                        self.socket.sendall(b'-');continue
                    self.socket.sendall(b'+');return packet.decode('ascii')
            elif self.buffer:self.buffer=b''  # RSP acknowledgements outside packets.
            left=max(0,until-time.monotonic())
            if not select.select([self.socket],[],[],left)[0]:return None
            chunk=self.socket.recv(65536)
            if not chunk:raise RuntimeError('QEMU fatal-probe debugger disconnected')
            self.buffer+=chunk

    def request(self,text,stop=False):
        self.send(text)
        until=time.monotonic()+5
        while time.monotonic()<until:
            response=self.receive(max(0,until-time.monotonic()))
            if response is None:break
            if response.startswith(('T','S')) and not stop:
                self.pending=response;continue
            if response.startswith('E'):raise RuntimeError('QEMU fatal-probe RSP error: '+response)
            return response
        raise TimeoutError('QEMU fatal-probe RSP request timed out: '+text)

    def check(self):
        if self.captured:return
        if self.target is None:
            console=(self.run/'console.log').read_bytes()
            match=re.search(rb'OBS OBSERVER_READY pid=(\d+) base=(0x[0-9a-f]+)',console)
            if not match:return
            self.pid=int(match[1]);self.base=int(match[2],16);self.target=self.base+self.OFFSET
            # RSP commands are installed while stopped. This pauses the whole
            # VM, not an individual guest thread or syscall with SIGSTOP.
            self.socket.sendall(b'\x03')
            while True:
                reason=self.receive(5)
                if reason and reason.startswith(('T','S')):break
                if reason is None:raise TimeoutError('Cannot pause QEMU to arm the fatal probe')
            if self.request(f'Z0,{self.target:x},4')!='OK':
                raise RuntimeError('QEMU rejected the original-fatal execution breakpoint')
            (self.run/'fatal-probe-armed.json').write_text(json.dumps(
                {'pid':self.pid,'app_base':hex(self.base),'original_elf_va':hex(self.OFFSET)},indent=2)+'\n')
            self.pending=None;self.send('c')
        reason=self.pending or self.receive(0)
        self.pending=None
        if not reason:return
        if not reason.startswith(('T','S')):
            raise RuntimeError('Unexpected QEMU debugger notification: '+reason)
        thread=re.search(r'thread:([^;]+)',reason)
        if thread:self.request('Hg'+thread[1])
        raw=self.request('g');data=bytes.fromhex(raw)
        if len(data)<268:raise RuntimeError('Short AArch64 core register snapshot')
        regs={f'x{i}':int.from_bytes(data[8*i:8*i+8],'little') for i in range(31)}
        regs.update(sp=int.from_bytes(data[248:256],'little'),pc=int.from_bytes(data[256:264],'little'),
                    pstate=int.from_bytes(data[264:268],'little'))
        if regs['pc']!=self.target:raise RuntimeError('QEMU stopped away from the armed original fatal point')
        record={'pid':self.pid,'app_base':hex(self.base),'elf_pc':hex(self.OFFSET),
                'source_line':regs['x2']&0xffffffff,'original_error':hex(regs['x3']&0xffffffff),
                'registers':{key:hex(value) for key,value in regs.items()},'stop_reason':reason,
                'camera_startup_verified':False,'method':'QEMU-execution-breakpoint-no-thread-attach'}
        (self.run/'original-boot-fatal.json').write_text(json.dumps(record,indent=2)+'\n')
        for key,register in (('source_file','x1'),('function','x19')):
            try:
                response=self.request(f'm{regs[register]:x},80')
                record[key]=bytes.fromhex(response).split(b'\0',1)[0].decode('utf-8',errors='replace')
            except (ValueError,RuntimeError):record[key]='unreadable'
        (self.run/'original-boot-fatal.json').write_text(json.dumps(record,indent=2)+'\n')
        if self.request(f'z0,{self.target:x},4')!='OK':raise RuntimeError('Cannot remove captured fatal breakpoint')
        self.captured=True
        self.send('c')  # Original logger/assert is deliberately allowed to run.

    def close(self):
        self.socket.close()


def adapt_script(text):
    if 'QEMU_FULL_FATAL_PROBE' in text:
        if 'QEMU_FULL_UPM_PROBE' not in text:
            anchor='observation_seconds="${QEMU_TIMEOUT_SECONDS:-15}"'
            if text.count(anchor)!=1:raise ValueError('Ambiguous UPM GDB trace insertion')
            text=text.replace(anchor,'if [[ "${QEMU_FULL_UPM_PROBE:-0}" == 1 ]]; then\n'
                '  fatal_debug_args+=(-trace "enable=gdbstub*")\nfi\n'+anchor,1)
        return text
    anchor='"${loader_args[@]}" -kernel /kernel.img'
    if text.count(anchor)!=1:raise ValueError('Ambiguous QEMU fatal-probe command insertion')
    text=text.replace(anchor,'"${fatal_debug_args[@]}" '+anchor,1)
    anchor='observation_seconds="${QEMU_TIMEOUT_SECONDS:-15}"'
    if text.count(anchor)!=1:raise ValueError('Ambiguous QEMU fatal-probe setup insertion')
    return adapt_script(text.replace(anchor,'fatal_debug_args=()\n'
        'if [[ "${QEMU_FULL_FATAL_PROBE:-0}" == 1 ]]; then\n'
        '  fatal_debug_args=(-gdb unix:/out/fatal-gdb.sock,server=on,wait=off)\nfi\n'+anchor,1))
