#!/usr/bin/env python3
"""Guard tests for the panel tick probe: it must arm Z1, never Z0, and report a
counter series rather than guessing at the tick frequency."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('panel_tick_probe', HERE / 'panel-tick-probe.py')
PROBE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROBE)


class RecordingSocket:
    def __init__(self):
        self.sent = b''
    def sendall(self, data):
        self.sent += data
    def settimeout(self, *_):
        pass


def make_probe(run):
    probe = PROBE.PanelTickProbe.__new__(PROBE.PanelTickProbe)
    probe.run = run
    probe.hits = []
    probe.finished = False
    probe.stopped = False
    probe.stepped = False
    probe.breakpoint_installed = False
    probe.arm_instruction_error = None
    probe.target = None
    probe.pid = None
    probe.base = None
    probe.armed_at = None
    probe.pending = None
    probe.buffer = b''
    probe.socket = RecordingSocket()
    probe.requests = []
    probe.receives = iter(['T05thread:01;', 'T05thread:01;'])
    def fake_request(text, stop=False):
        probe.requests.append(text)
        if text == 'vCont?':
            return 'vCont;c;s'
        if text.startswith('m'):
            address = int(text[1:].partition(',')[0], 16)
            return (PROBE.PanelTickProbe.INSTRUCTION.hex() if address == probe.target
                    else (100).to_bytes(4, 'little').hex())
        if text == 'g':
            registers = bytearray(268)
            registers[:8] = (0x1000).to_bytes(8, 'little')
            registers[256:264] = (probe.target + (4 if probe.stepped else 0)).to_bytes(8, 'little')
            return registers.hex()
        return 'OK'
    def fake_receive(timeout=0):
        return next(probe.receives, None)
    probe.request = fake_request
    probe.receive = fake_receive
    def fake_send(text):
        if text.startswith('vCont;s:'):
            probe.stepped = True
        data = text.encode('ascii')
        probe.socket.sent += b'$' + data + b'#00'
    probe.send = fake_send
    return probe


class Behaviour(unittest.TestCase):
    def test_arm_uses_a_hardware_breakpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'console.log').write_bytes(b'OBS OBSERVER_READY pid=445 base=0x400000\n')
            probe = make_probe(run)
            probe._arm()
            installs = [entry for entry in probe.requests if entry.startswith(('Z', 'z'))]
            self.assertTrue(all(entry.startswith('Z1') for entry in installs),
                            f'expected only Z1 installs, got {installs}')
            self.assertNotIn('Z0', ' '.join(installs))
            armed = json.loads((run / probe.ARMED_FILE).read_text())
            self.assertEqual(armed['elf_va'], '0x20acae8')

    def test_counter_series_is_recorded_as_is(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            probe = make_probe(run)
            probe.hits = [
                {'t': 0.0, 'pc': '0x4020acae8', 'object': '0x1000', 'counter': 100},
                {'t': 1.0, 'pc': '0x4020acae8', 'object': '0x1000', 'counter': 99}]
            probe.target = 0x4020acae8
            probe.breakpoint_installed = True
            probe._finish('limit')
            payload = json.loads((run / probe.HITS_FILE).read_text())
            self.assertEqual(payload['hits'], 2)
            self.assertEqual(payload['counters'], [100, 99])
            self.assertIn('does not establish a missing hardware tick', payload['interpretation'])

    def test_each_entry_steps_original_instruction_before_rearming(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            probe = make_probe(run)
            probe.target = 0x400000 + probe.OFFSET
            probe.armed_at = 1.0
            probe.pending = 'T05thread:01;'
            probe.check()
            self.assertEqual(len(probe.hits), 1)
            self.assertEqual(probe.hits[0]['counter'], 100)
            self.assertEqual(probe.hits[0]['stepped_pc'], hex(probe.target + 4))
            self.assertLess(probe.requests.index(f'z1,{probe.target:x},4'),
                            probe.requests.index(f'Z1,{probe.target:x},4'))
            self.assertIn(b'vCont;s:01', probe.socket.sent)

    def test_stop_at_unrelated_pc_is_not_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = make_probe(Path(directory))
            probe.target = 0x400000 + probe.OFFSET
            probe.pending = 'T05thread:01;'
            probe.stepped = True
            with self.assertRaisesRegex(RuntimeError, 'away from the declared instruction'):
                probe.check()
            self.assertEqual(probe.hits, [])

    def test_original_bytes_must_match_before_install(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'console.log').write_bytes(b'OBS OBSERVER_READY pid=445 base=0x400000\n')
            probe = make_probe(run)
            original_request = probe.request
            probe.request = lambda text, stop=False: ('00000000' if text.startswith('m')
                                                      else original_request(text, stop))
            with self.assertRaisesRegex(RuntimeError, 'instruction differs'):
                probe._arm()
            self.assertFalse(any(command.startswith('Z1') for command in probe.requests))

    def test_runner_deadline_protocol_writes_summary_once(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            probe = make_probe(run)
            probe.target = 0x400000 + probe.OFFSET
            probe.breakpoint_installed = True
            probe.end_observation()
            saved = (run / probe.HITS_FILE).read_bytes()
            probe.end_observation()
            self.assertEqual((run / probe.HITS_FILE).read_bytes(), saved)
            payload = json.loads(saved)
            self.assertEqual(payload['reason'], 'observation-deadline')
            self.assertEqual(payload['hits'], 0)
            self.assertIsNone(payload['cleanup_error'])
            self.assertIn('Hc-1', probe.requests)

    def test_cleanup_failure_is_retained_and_fails_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            probe = make_probe(run)
            probe.target = 0x400000 + probe.OFFSET
            probe.breakpoint_installed = True
            probe.stopped = True
            probe.request = lambda text, stop=False: 'unsupported'
            with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                probe.end_observation()
            summary = json.loads((run / probe.HITS_FILE).read_text())
            self.assertIsNotNone(summary['cleanup_error'])
            self.assertEqual(probe.socket.sent, b'')

    def test_opted_in_e14_is_recorded_but_hits_still_require_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'console.log').write_bytes(b'OBS OBSERVER_READY pid=445 base=0x400000\n')
            probe = make_probe(run)
            probe.DEFER_E14_VALIDATION = True
            original = probe.request
            def request(command, stop=False):
                if command.startswith('m'):
                    raise RuntimeError('QEMU fatal-probe RSP error: E14')
                return original(command, stop)
            probe.request = request
            probe._arm()
            self.assertTrue(probe.breakpoint_installed)
            receipt = json.loads((run / probe.ARMED_FILE).read_text())
            self.assertFalse(receipt['runtime_instruction_verified_at_arm'])
            self.assertIn('E14', receipt['arm_instruction_error'])
            probe.pending = 'T05thread:01;'
            with self.assertRaisesRegex(RuntimeError, 'E14'):
                probe.check()
            self.assertEqual(probe.hits, [])

    def test_e14_deferral_does_not_hide_other_rsp_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / 'console.log').write_bytes(b'OBS OBSERVER_READY pid=445 base=0x400000\n')
            probe = make_probe(run)
            probe.DEFER_E14_VALIDATION = True
            original = probe.request
            def request(command, stop=False):
                if command.startswith('m'):
                    raise RuntimeError('QEMU fatal-probe RSP error: E22')
                return original(command, stop)
            probe.request = request
            with self.assertRaisesRegex(RuntimeError, 'E22'):
                probe._arm()
            self.assertFalse(probe.breakpoint_installed)

    def test_arm_failure_does_not_remove_a_never_installed_breakpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            probe = make_probe(run)
            probe.target = 0x400000 + probe.OFFSET
            probe.stopped = True
            probe._finish('arm-failed')
            self.assertFalse(any(command.startswith('z1') for command in probe.requests))
            payload = json.loads((run / probe.HITS_FILE).read_text())
            self.assertFalse(payload['armed'])
            self.assertIsNone(payload['cleanup_error'])


if __name__ == '__main__':
    unittest.main()
