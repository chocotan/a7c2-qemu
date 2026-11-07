#!/usr/bin/env python3
"""Observe the application's original UPM reload request before it is handed off.

No message is injected. A hit establishes a call about to send, not delivery,
kernel consumption, timer rearming, or successful wake-up.
"""
from pathlib import Path
import runpy

Base = runpy.run_path(str(Path(__file__).with_name('panel-tick-probe.py')))['PanelTickProbe']


class UpmReloadProbe(Base):
    OFFSET = 0x35a1354
    INSTRUCTION = bytes.fromhex('dff58297')  # bl osal_snd_msg@plt
    KIND = 'upm-reload'
    LIMIT = 128
    ARMED_FILE = 'upm-reload-armed.json'
    HITS_FILE = 'upm-reload-observation.json'
    DEFER_E14_VALIDATION = True

    def capture_entry(self, registers):
        if registers['x0'] != 0x80920572:
            raise ValueError('original UPM reload destination differs')
        pointer = registers['x1']
        raw = self._memory(pointer, 16)
        words = [int.from_bytes(raw[i:i + 4], 'little') for i in range(0, 16, 4)]
        if words[0] != 0x00920204 or words[3] != 0:
            raise ValueError('original UPM reload request identity differs')
        # Snapshot only before the send: afterwards the original sender no longer owns it.
        return {'destination': hex(registers['x0']), 'request_pointer': hex(pointer),
                'request_hex': raw.hex(), 'command': hex(words[0]),
                'selector': words[1], 'owner_field': hex(words[2]),
                'caller_frame': hex(registers['x29']),
                'console_bytes_at_hit': (self.run / 'console.log').stat().st_size}

    def successor(self, pc):
        return self.base + 0x165ead0  # the original BL's PLT target, not pc+4

    def format_summary(self, payload):
        payload['schema'] = 'upm-reload-original-send-v1'
        payload.pop('counters')
        payload['requests'] = self.hits
        payload['interpretation'] = (
            'Original application reload send calls observed within this bounded window only. '
            'Request bytes were read before ownership transfer. No observation of send return, '
            'delivery, kernel consumption, timer effect, or wake-up is implied.')
        payload['wake_verified'] = False
        return payload
