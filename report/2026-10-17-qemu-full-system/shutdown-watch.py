#!/usr/bin/env python3
"""Observe original shutdown-factor writes; never change guest model values."""
import json
import hashlib
from pathlib import Path
import re
import runpy

RSP = runpy.run_path(str(Path(__file__).with_name('boot-fatal-probe.py')))['BootFatalProbe']


class ShutdownWriteProbe(RSP):
    OFFSET = 0x7e5dd88
    KIND = 'shutdown-write'
    BREAKPOINT_KIND = 2
    STOP_VALUE = 0x15
    LIMIT = 128
    ARMED_FILE = 'shutdown-watch-armed.json'
    WRITES_FILE = 'shutdown-writes.jsonl'
    CAPTURE_FILE = 'shutdown-factor-15.json'
    LIMIT_FILE = 'shutdown-watch-limit.json'
    CODE_OFFSETS = ()

    def __init__(self, run, connect):
        self.finished = False
        self.writes = 0
        super().__init__(run, connect)

    def stop_vm(self):
        self.socket.sendall(b'\x03')
        while True:
            reason = self.receive(5)
            if reason is None:
                raise TimeoutError('Cannot pause QEMU to arm shutdown write observation')
            if reason.startswith(('T', 'S')):
                return reason

    def memory(self, address, size):
        value = bytes.fromhex(self.request(f'm{address:x},{size:x}'))
        if len(value) != size:
            raise RuntimeError('Short shutdown watch memory read')
        return value

    def registers(self):
        value = bytes.fromhex(self.request('g'))
        if len(value) < 268:
            raise RuntimeError('Short shutdown watch register read')
        regs = {f'x{i}': int.from_bytes(value[8*i:8*i+8], 'little') for i in range(31)}
        regs['sp'] = int.from_bytes(value[248:256], 'little')
        regs['pc'] = int.from_bytes(value[256:264], 'little')
        return regs

    def frames(self, fp):
        result = []
        for _ in range(12):
            if not fp or fp & 15:
                break
            try:
                raw = self.memory(fp, 16)
            except (RuntimeError, ValueError):
                break
            parent, lr = int.from_bytes(raw[:8], 'little'), int.from_bytes(raw[8:], 'little')
            result.append({'fp': hex(fp), 'parent': hex(parent), 'lr': hex(lr),
                           'appfw_lr': hex(lr-self.base) if self.base <= lr < self.base+0x10000000 else None})
            if not fp < parent <= fp+0x100000:
                break
            fp = parent
        return result

    def app_event(self, frames):
        # Original main loop 1799e8c: x20=fp+258; for receive kind 2 it
        # builds a type-5 ds_event there and copies 168 bytes from fp+f0.
        # The caller frame of the proven 179a250 return owns both buffers.
        for frame in frames:
            if frame.get('appfw_lr')!='0x179a250':
                continue
            fp=int(frame['parent'],16)
            try:
                raw=self.memory(fp+0xe8,0x170)
                event=self.memory(fp+0x258,0x178)
            except (RuntimeError,ValueError) as error:
                return {'frame':hex(fp),'error':str(error)}
            return {'frame':hex(fp),'raw_receive_hex':raw.hex(),'ds_event_hex':event.hex(),
                    'ds_event_type':int.from_bytes(event[:4],'little'),
                    'ds_event_word2':hex(int.from_bytes(event[8:12],'little'))}
        return None

    def check(self):
        if self.finished:
            return
        if self.target is None:
            match = re.search(rb'OBS OBSERVER_READY pid=(\d+) base=(0x[0-9a-f]+)',
                              (self.run/'console.log').read_bytes())
            if not match:
                return
            self.pid, self.base = int(match[1]), int(match[2], 16)
            self.target = self.base+self.OFFSET
            self.stop_vm()
            initial=None;initial_error=None
            try:
                initial=self.memory(self.target,12)
            except RuntimeError as error:
                # The selected CPU may be in another process, or this BSS page
                # may not yet be faulted in. A virtual TCG watch can still be
                # armed; read the model after the actual writer CPU stops.
                if 'E14' not in str(error):raise
                initial_error=str(error)
            if self.request(f'Z2,{self.target:x},4') != 'OK':
                raise RuntimeError('QEMU rejected shutdown-factor write watchpoint')
            (self.run/self.ARMED_FILE).write_text(json.dumps({
                'pid': self.pid, 'appfw_base': hex(self.base), 'offset': hex(self.OFFSET),
                'initial_model_hex': initial.hex() if initial is not None else None,
                'initial_read_error':initial_error,'writes_guest_model': False,
                'probe_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'rsp_source_sha256': hashlib.sha256(Path(__file__).with_name('boot-fatal-probe.py').read_bytes()).hexdigest(),
            }, indent=2)+'\n')
            self.pending = None
            self.send('c')
        reason = self.pending or self.receive(0)
        self.pending = None
        if not reason:
            return
        if not reason.startswith(('T', 'S')) or 'watch:' not in reason:
            raise RuntimeError('Unexpected shutdown watch stop: '+reason)
        thread = re.search(r'thread:([^;]+)', reason)
        if thread:
            self.request('Hg'+thread[1])
            self.request('Hc'+thread[1])
        before = self.registers()
        frames = self.frames(before['x29'])
        app_event = self.app_event(frames)
        model_before = self.memory(self.target, 12)
        instruction = self.memory(before['pc'], 4)
        if self.request(f'z2,{self.target:x},4') != 'OK':
            raise RuntimeError('Cannot remove shutdown watchpoint for original store')
        # A TCG memory watchpoint can stop before the instruction. Let the
        # ORIGINAL instruction execute once, with no target-memory writes.
        self.send('s')
        stepped = self.receive(5)
        if stepped is None or not stepped.startswith(('T', 'S')):
            raise RuntimeError('Original shutdown store single-step did not stop')
        after = self.registers()
        model_after = self.memory(self.target, 12)
        self.writes += 1
        record = {'write': self.writes, 'stop_reason': reason, 'step_reason': stepped,
                  'pid_from_observer': self.pid, 'appfw_base': hex(self.base),
                  'pc_before': hex(before['pc']), 'pc_after': hex(after['pc']),
                  'appfw_pc': hex(before['pc']-self.base) if self.base <= before['pc'] < self.base+0x10000000 else None,
                  'instruction_hex': instruction.hex(), 'model_before_hex': model_before.hex(),
                  'model_after_hex': model_after.hex(),
                  'registers_before': {k: hex(v) for k, v in before.items()}, 'frames': frames,
                  'original_app_event':app_event,
                  'method': 'QEMU-write-watchpoint-original-store-no-model-write'}
        if self.CODE_OFFSETS:
            record['original_appfw_code_windows']={}
            for offset in self.CODE_OFFSETS:
                try:value=self.memory(self.base+offset,4).hex()
                except RuntimeError as error:
                    if 'E14' not in str(error):raise
                    value={'read_error':str(error)}
                record['original_appfw_code_windows'][hex(offset)]=value
        with (self.run/self.WRITES_FILE).open('a') as out:
            out.write(json.dumps(record)+'\n')
        factor = int.from_bytes(model_after[:4], 'little')
        if factor == self.STOP_VALUE:
            self.captured = self.finished = True
            (self.run/self.CAPTURE_FILE).write_text(json.dumps(record, indent=2)+'\n')
        elif self.writes >= self.LIMIT:
            self.finished = True
            (self.run/self.LIMIT_FILE).write_text(json.dumps({
                'writes': self.writes, 'reason': 'bounded diagnostic ended without target value '+hex(self.STOP_VALUE),
                'cause_verified': False,
            }, indent=2)+'\n')
        elif self.request(f'Z2,{self.target:x},4') != 'OK':
            raise RuntimeError('Cannot re-arm shutdown write observation')
        self.request('Hc-1')
        self.send('c')

    def end_observation(self):
        """Remove observation before final QMP stop/cont readbacks."""
        if self.target is not None and not self.finished:
            self.stop_vm()
            if self.request(f'z{self.BREAKPOINT_KIND},{self.target:x},4')!='OK':
                raise RuntimeError('Cannot remove unfinished shutdown watchpoint')
            self.pending=None
            self.request('Hc-1')
            self.send('c')
            self.finished=True
        self.close()
