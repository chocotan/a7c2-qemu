#!/usr/bin/env python3
"""Observe the original factor7 command read; never inject an activity message."""
import hashlib
import json
from pathlib import Path
import re
import runpy
import time

Base = runpy.run_path(str(Path(__file__).with_name('panel-tick-probe.py')))['PanelTickProbe']
MODULE_SHA = 'a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb'


def locations(console):
    section = re.findall(rb'(?m)^UPM_ACTIVITY_SECTIONS text=(0x[0-9a-f]+)\r?$', console)
    memory = re.findall(rb'memory\s+: (0x[0-9a-f]+) - (0x[0-9a-f]+)', console)
    if not section or not memory:
        return None
    if len(set(section)) != 1 or len(set(memory)) != 1:
        raise ValueError('ambiguous UPM sections or kernel RAM declaration')
    text = int(section[0], 16)
    low, high = (int(x, 16) for x in memory[0])
    if not (0xffffff8000000000 <= text < 0xffffff8008000000 and text % 4096 == 0):
        raise ValueError('UPM module text outside the selected kernel module region')
    if not (low == 0xffffffc000000000 < high <= 0xffffffc200000000):
        raise ValueError('unexpected kernel linear RAM declaration')
    return text, low, high


class UpmActivityProbe(Base):
    OFFSET = 0xa668
    INSTRUCTION = bytes.fromhex('000440b9')  # ldr w0,[x0,#4]
    KIND = 'upm-activity'
    LIMIT = 128
    ARMED_FILE = 'upm-activity-armed.json'
    HITS_FILE = 'upm-activity-observation.json'

    def __init__(self, run, connect, module):
        if hashlib.sha256(Path(module).read_bytes()).hexdigest() != MODULE_SHA:
            raise ValueError('UPM activity requires the exact original module')
        self.install_request = None
        self.install_reply = None
        self.ram = None
        self.audit = []
        self.audit_count = 0
        self.last_command = None
        super().__init__(run, connect)

    def note(self, kind, **fields):
        self.audit_count += 1
        if self.audit_count > 1024:
            return
        record = dict(sequence=self.audit_count, kind=kind, **fields)
        self.audit.append(record)
        with (self.run / 'upm-activity-debugger.jsonl').open('a') as output:
            output.write(json.dumps(record) + '\n')

    def send(self, text):
        self.last_command = text
        super().send(text)

    def receive(self, timeout):
        response = super().receive(timeout)
        if response and response.startswith(('T', 'S', 'E')):
            self.note('stop-or-error', command=self.last_command, response=response,
                      raw_hex=response.encode('ascii').hex())
        return response

    def request(self, text, stop=False):
        breakpoint = text.startswith(('Z1,', 'z1,'))
        if breakpoint and (self.install_request is None or text[1:] != self.install_request[1:]):
            self.note('rejected-local-breakpoint-request', request=text)
            raise ValueError('UPM activity request differs from original install identity')
        try:
            response = super().request(text, stop=stop)
        except (OSError, TimeoutError, RuntimeError) as error:
            if breakpoint:
                self.note('breakpoint-request-error', request=text, error=str(error))
            raise
        if breakpoint:
            self.note('breakpoint-receipt', request=text, response=response,
                      raw_hex=response.encode('ascii').hex())
        return response

    def _pause(self):
        self.last_command = 'interrupt-0x03'
        return super()._pause()

    def _memory(self, address, size):
        code = self.target is not None and address == self.target and size == 4
        ram = self.ram is not None and size == 8 and self.ram[0] <= address <= self.ram[1] - size
        if not (code or ram):
            raise ValueError('UPM activity refuses a read outside declared code/RAM')
        return super()._memory(address, size)

    def _arm(self):
        found = locations((self.run / 'console.log').read_bytes())
        if found is None:
            return False
        self.base, low, high = found
        self.ram = (low, high)
        self.pid = None
        self.target = self.base + self.OFFSET
        self._pause()
        if 's' not in self.request('vCont?').split(';')[1:]:
            raise RuntimeError('UPM activity requires directed single step')
        if self._memory(self.target, 4) != self.INSTRUCTION:
            raise ValueError('original UPM activity instruction differs')
        self.install_request = f'Z1,{self.target:x},4'
        self.install_reply = self.request(self.install_request)
        if self.install_reply != 'OK':
            raise RuntimeError('UPM activity breakpoint rejected')
        self.breakpoint_installed = True
        (self.run / self.ARMED_FILE).write_text(json.dumps({
            'module_sha256': MODULE_SHA, 'module_text': hex(self.base),
            'text_offset': hex(self.OFFSET), 'instruction_hex': self.INSTRUCTION.hex(),
            'kernel_linear_ram': [hex(low), hex(high)],
            'install_request': self.install_request, 'install_reply': self.install_reply,
            'console_bytes_at_arm': (self.run / 'console.log').stat().st_size,
            'message_injected': False}, indent=2) + '\n')
        self.armed_at = time.monotonic()
        self.pending = None
        self.request('Hc-1')
        self.send('c')
        self.stopped = False
        return True

    def capture_entry(self, registers):
        address = registers['x0']
        raw = self._memory(address, 8)
        return {'argument': hex(address), 'raw_hex': raw.hex(),
                'source_sid': hex(int.from_bytes(raw[:4], 'little')),
                'command': hex(int.from_bytes(raw[4:], 'little')),
                'lr': hex(registers['x30']), 'frame': hex(registers['x29']),
                'console_bytes_at_hit': (self.run / 'console.log').stat().st_size}

    def _finish(self, reason):
        if self.breakpoint_installed and self.install_request != f'Z1,{self.target:x},4':
            raise RuntimeError('UPM activity target no longer matches original installation')
        super()._finish(reason)

    def format_summary(self, payload):
        payload.update(schema='upm-activity-original-command-read-v1',
                       module_text=payload.pop('app_base'), text_offset=payload.pop('elf_va'),
                       module_sha256=MODULE_SHA, install_request=self.install_request,
                       install_reply=self.install_reply, events=self.hits,
                       debugger_receipts=self.audit,
                       debugger_receipt_count=self.audit_count,
                       debugger_receipts_truncated=self.audit_count > 1024,
                       arm_boundary='after original kernel sections and RAM declaration',
                       interpretation='Original factor7 command reads only; not delivery to MSS, timer effect, or wake-up.',
                       message_injected=False, wake_verified=False)
        payload.pop('counters')
        payload.pop('pid')
        return payload
