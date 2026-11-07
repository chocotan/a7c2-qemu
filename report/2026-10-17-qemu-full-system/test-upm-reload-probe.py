#!/usr/bin/env python3
"""Original reload requests are copied before send; no delivery is inferred."""
from pathlib import Path
import runpy
import tempfile
import unittest

Probe = runpy.run_path(str(Path(__file__).with_name('upm-reload-probe.py')))['UpmReloadProbe']


class OriginalRequest(unittest.TestCase):
    def probe(self, command=0x920204, padding=0):
        probe = Probe.__new__(Probe)
        probe.base = 0x400000
        probe.hits = []
        probe.reads = []
        probe.breakpoint_installed = False
        probe.arm_instruction_error = None
        probe.run = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (probe.run / 'console.log').write_bytes(b'owned console')
        raw = b''.join(word.to_bytes(4, 'little') for word in
                       (command, 2, 0x802a0116, padding))
        def memory(address, size):
            probe.reads.append((address, size))
            self.assertEqual((address, size), (0x1000, 16))
            return raw
        probe._memory = memory
        return probe

    def registers(self, destination=0x80920572):
        return {'x0': destination, 'x1': 0x1000, 'x29': 0x2000}

    def test_reads_exact_native_request(self):
        probe = self.probe()
        record = probe.capture_entry(self.registers())
        self.assertEqual(record['command'], '0x920204')
        self.assertEqual(record['selector'], 2)
        self.assertEqual(record['owner_field'], '0x802a0116')
        self.assertEqual(probe.reads, [(0x1000, 16)])

    def test_wrong_destination_is_rejected_before_pointer_read(self):
        probe = self.probe()
        with self.assertRaises(ValueError):
            probe.capture_entry(self.registers(0x90030001))
        self.assertEqual(probe.reads, [])

    def test_wrong_command_or_padding_is_rejected(self):
        for command, padding in ((0x920117, 0), (0x920204, 1)):
            with self.subTest(command=command, padding=padding):
                with self.assertRaises(ValueError):
                    self.probe(command, padding).capture_entry(self.registers())

    def test_bl_successor_is_plt_not_next_instruction(self):
        probe = self.probe()
        self.assertEqual(probe.successor(probe.base + probe.OFFSET), probe.base + 0x165ead0)
        self.assertNotEqual(probe.successor(probe.base + probe.OFFSET), probe.base + probe.OFFSET + 4)

    def test_summary_does_not_claim_delivery_or_wake(self):
        probe = self.probe()
        probe.hits = [probe.capture_entry(self.registers())]
        summary = probe.format_summary({'counters': [None], 'hits': 1})
        self.assertEqual(summary['schema'], 'upm-reload-original-send-v1')
        self.assertEqual(len(summary['requests']), 1)
        self.assertNotIn('counters', summary)
        self.assertFalse(summary['wake_verified'])
        self.assertIn('No observation of send return', summary['interpretation'])

    def test_send_entry_steps_bl_without_reading_transferred_message(self):
        probe = self.probe()
        probe.finished = False
        probe.target = probe.base + probe.OFFSET
        probe.pending = 'T05thread:01;'
        probe.armed_at = 1.0
        probe.stopped = False
        commands = []
        stepped = False
        before_send_memory = probe._memory
        def memory(address, size):
            if address == probe.target:
                return probe.INSTRUCTION
            self.assertFalse(stepped, 'message accessed after the original send instruction')
            return before_send_memory(address, size)
        def request(command, stop=False):
            commands.append(command)
            if command == 'g':
                data = bytearray(268)
                for index, value in ((0, 0x80920572), (1, 0x1000), (29, 0x2000)):
                    data[index * 8:index * 8 + 8] = value.to_bytes(8, 'little')
                pc = probe.successor(probe.target) if stepped else probe.target
                data[256:264] = pc.to_bytes(8, 'little')
                return data.hex()
            return 'OK'
        def send(command):
            nonlocal stepped
            commands.append(command)
            if command == 'vCont;s:01':
                stepped = True
        probe._memory = memory
        probe.request = request
        probe.send = send
        probe.receive = lambda timeout: 'T05thread:01;'
        probe.check()
        self.assertEqual(len(probe.hits), 1)
        self.assertEqual(probe.reads, [(0x1000, 16)])
        self.assertEqual(probe.hits[0]['stepped_pc'], hex(probe.base + 0x165ead0))
        self.assertIn('vCont;s:01', commands)


if __name__ == '__main__':
    unittest.main()
