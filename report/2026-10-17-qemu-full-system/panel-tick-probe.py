#!/usr/bin/env python3
"""Observe the original controller counter reader without changing model values.

The controller's relationship to the observed black screen and the event driving
it must be established separately. No hits only bounds this observation window.
"""
import json
import re
import time
from pathlib import Path
import runpy

BASE = runpy.run_path(str(Path(__file__).with_name('boot-fatal-probe.py')))['BootFatalProbe']


class PanelTickProbe(BASE):
    OFFSET = 0x20acae8          # ldr w2,[x0,#772]; sub; str - the decrement site
    COUNTER_OFFSET = 772        # +0x304
    INSTRUCTION = bytes.fromhex('020443b9')  # ldr w2,[x0,#772]
    KIND = 'panel-tick'
    LIMIT = 400
    ARMED_FILE = 'panel-tick-armed.json'
    HITS_FILE = 'panel-tick-hits.json'
    DEFER_E14_VALIDATION = False

    def __init__(self, run, connect):
        self.hits = []
        self.armed_at = None
        self.finished = False
        self.stopped = False
        self.breakpoint_installed = False
        self.arm_instruction_error = None
        super().__init__(run, connect)

    def _pause(self):
        self.socket.sendall(b'\x03')
        while True:
            reason = self.receive(5)
            if reason and reason.startswith(('T', 'S')):
                self.stopped = True
                self.pending = None
                return reason
            if reason is None:
                raise TimeoutError('cannot pause QEMU for the controller counter probe')

    def _memory(self, address, size):
        data = bytes.fromhex(self.request(f'm{address:x},{size:x}'))
        if len(data) != size:
            raise RuntimeError('short controller counter memory read')
        return data

    def capture_entry(self, registers):
        address = registers['x0']
        counter = None
        if address:
            try:
                counter = int.from_bytes(self._memory(address + self.COUNTER_OFFSET, 4), 'little')
            except (ValueError, RuntimeError):
                pass
        return {'object': hex(address), 'counter': counter}

    def successor(self, pc):
        return pc + 4

    def format_summary(self, payload):
        return payload

    def _arm(self):
        console = (self.run / 'console.log').read_bytes()
        match = re.search(rb'OBS OBSERVER_READY pid=(\d+) base=(0x[0-9a-f]+)', console)
        if not match:
            return False
        self.pid = int(match[1])
        self.base = int(match[2], 16)
        self.target = self.base + self.OFFSET
        self._pause()
        if 's' not in self.request('vCont?').split(';')[1:]:
            raise RuntimeError('controller probe requires directed vCont single step')
        try:
            if self._memory(self.target, 4) != self.INSTRUCTION:
                raise RuntimeError('original controller counter instruction differs')
        except RuntimeError as error:
            if not self.DEFER_E14_VALIDATION or str(error) != 'QEMU fatal-probe RSP error: E14':
                raise
            # Hardware execution breakpoints do not require the current CPU to map
            # this user VA. Every counted hit still validates its original bytes.
            self.arm_instruction_error = str(error)
        if self.request(f'Z1,{self.target:x},4') != 'OK':
            raise RuntimeError('QEMU rejected the panel tick execute breakpoint')
        self.breakpoint_installed = True
        (self.run / self.ARMED_FILE).write_text(json.dumps(
            {'pid': self.pid, 'app_base': hex(self.base), 'elf_va': hex(self.OFFSET),
             'instruction_hex': self.INSTRUCTION.hex(),
             'runtime_instruction_verified_at_arm': self.arm_instruction_error is None,
             'arm_instruction_error': self.arm_instruction_error,
             'breakpoint': 'Z1 hardware execute (no code patched)'}, indent=2) + '\n')
        self.armed_at = time.monotonic()
        self.pending = None
        self.request('Hc-1')
        self.send('c')
        self.stopped = False
        return True

    def check(self):
        if self.finished:
            return
        if self.target is None:
            if not self._arm():
                return
            return
        reason = self.pending or self.receive(0)
        self.pending = None
        if not reason:
            return
        if not reason.startswith(('T', 'S')):
            raise RuntimeError('unexpected debugger notification: ' + reason)
        self.stopped = True
        thread = re.search(r'thread:([^;]+)', reason)
        if not thread:
            raise RuntimeError('controller counter stop has no thread identity')
        self.request('Hg' + thread[1])
        raw = self.request('g')
        data = bytes.fromhex(raw)
        if len(data) < 268:
            raise RuntimeError('short AArch64 register snapshot')
        regs = {f'x{i}': int.from_bytes(data[8 * i:8 * i + 8], 'little') for i in range(31)}
        pc = int.from_bytes(data[256:264], 'little')
        if pc != self.target:
            raise RuntimeError('controller counter stopped away from the declared instruction')
        if self._memory(pc, 4) != self.INSTRUCTION:
            raise RuntimeError('controller counter instruction changed during observation')
        self.hits.append({'t': round(time.monotonic() - (self.armed_at or time.monotonic()), 3),
                          'pc': hex(pc), 'thread': thread[1], **self.capture_entry(regs)})
        if len(self.hits) >= self.LIMIT:
            self._finish('limit')
            return
        # Step over the real instruction before rearming, so one hit is one entry.
        if self.request(f'z1,{self.target:x},4') != 'OK':
            raise RuntimeError('cannot disarm controller counter breakpoint for stepping')
        self.breakpoint_installed = False
        self.send(f'vCont;s:{thread[1]}')
        step_reason = self.receive(5)
        if not step_reason or not step_reason.startswith(('T', 'S')):
            raise RuntimeError('controller counter step did not stop')
        step_thread = re.search(r'thread:([^;]+)', step_reason)
        if not step_thread or step_thread[1] != thread[1]:
            raise RuntimeError('controller counter single step changed thread')
        self.request('Hg' + thread[1])
        after = bytes.fromhex(self.request('g'))
        expected_pc = self.successor(pc)
        if len(after) < 268 or int.from_bytes(after[256:264], 'little') != expected_pc:
            raise RuntimeError('controller counter single step did not reach the original successor')
        self.hits[-1]['stepped_pc'] = hex(expected_pc)
        if self.request(f'Z1,{self.target:x},4') != 'OK':
            raise RuntimeError('cannot rearm controller counter breakpoint')
        self.breakpoint_installed = True
        self.pending = None
        self.request('Hc-1')
        self.send('c')
        self.stopped = False

    def _finish(self, reason):
        if self.finished:
            return
        self.finished = True
        cleanup_error = None
        if self.breakpoint_installed:
            try:
                if not self.stopped:
                    self._pause()
                if self.request(f'z1,{self.target:x},4') != 'OK':
                    raise RuntimeError('cannot remove controller counter breakpoint')
                self.breakpoint_installed = False
            except (OSError, TimeoutError, RuntimeError) as error:
                cleanup_error = str(error)
        payload = {'schema': 'panel-tick-probe-v1', 'reason': reason,
                   'pid': getattr(self, 'pid', None),
                   'app_base': hex(self.base) if getattr(self, 'base', None) else None,
                   'elf_va': hex(self.OFFSET), 'hits': len(self.hits),
                   'armed': self.armed_at is not None,
                   'arm_boundary': 'after OBSERVER_READY; original instruction validated at every counted hit',
                   'arm_instruction_error': self.arm_instruction_error,
                   'runtime_instruction_verified_at_arm': self.armed_at is not None and self.arm_instruction_error is None,
                   'hit_limit_reached': len(self.hits) >= self.LIMIT,
                   'debugger_changes_scheduling': True,
                   'counters': [hit.get('counter') for hit in self.hits][:40],
                   'first': self.hits[:5], 'last': self.hits[-5:],
                   'cleanup_error': cleanup_error,
                   'interpretation': ('Hits identify executions of this controller entry only. '
                                      'Counters belong to the recorded object instances. No hit does '
                                      'not exclude activity before arming or after the hit limit, and '
                                      'does not establish a missing hardware tick or a wake-up mechanism.')}
        payload = self.format_summary(payload)
        (self.run / self.HITS_FILE).write_text(json.dumps(payload, indent=2) + '\n')
        if cleanup_error is not None:
            raise RuntimeError('controller counter cleanup failed: ' + cleanup_error)
        if self.stopped and cleanup_error is None:
            self.request('Hc-1')
            self.send('c')
            self.stopped = False

    def close(self):
        self._finish('closed')
        super().close()

    def end_observation(self):
        self._finish('observation-deadline')
