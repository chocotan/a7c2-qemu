import importlib.util
from pathlib import Path
import subprocess
import sys
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('upm_activity', Path(__file__).with_name('upm-activity-probe.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Probe = module.UpmActivityProbe


class UpmActivityTests(unittest.TestCase):
    def test_sections_and_declared_ram(self):
        declaration = b'memory  : 0xffffffc000000000 - 0xffffffc200000000\n'
        self.assertIsNone(module.locations(declaration))
        valid = declaration + b'UPM_ACTIVITY_SECTIONS text=0xffffff80008f6000\n'
        self.assertEqual(module.locations(valid), (0xffffff80008f6000, 0xffffffc000000000, 0xffffffc200000000))
        for bad in (valid + b'UPM_ACTIVITY_SECTIONS text=0xffffff80008f7000\n',
                    valid.replace(b'0xffffff80008f6000', b'0xf102f000'),
                    valid.replace(b'0xffffffc200000000', b'0xffffffd200000000')):
            with self.assertRaises(ValueError):
                module.locations(bad)

    def test_rejects_wrong_module_before_debugger(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'wrong.ko'
            p.write_bytes(b'wrong module')
            with self.assertRaises(ValueError):
                Probe(Path(tmp), lambda *a: self.fail('unexpected connect'), p)

    def test_capture_reads_only_eight_ram_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Probe.__new__(Probe)
            probe.run = Path(tmp)
            (probe.run / 'console.log').write_bytes(b'original input edge')
            probe.target = 0xffffff80008f6000 + Probe.OFFSET
            probe.ram = (0xffffffc000000000, 0xffffffc200000000)
            calls = []
            def request(text):
                calls.append(text)
                return '6008928031019200'
            probe.request = request
            regs = {'x0': 0xffffffc00000100c, 'x29': 0xffffffc000002000, 'x30': 0xffffff80000145d0}
            event = probe.capture_entry(regs)
            self.assertEqual(calls, ['mffffffc00000100c,8'])
            self.assertEqual(event['source_sid'], '0x80920860')
            self.assertEqual(event['command'], '0x920131')
            for address, size in ((0xf102f000, 8), (probe.ram[1] - 4, 8), (probe.ram[0], 64)):
                with self.assertRaises(ValueError):
                    probe._memory(address, size)
            self.assertEqual(len(calls), 1)

    def test_cleanup_refuses_changed_install_identity(self):
        probe = Probe.__new__(Probe)
        probe.breakpoint_installed = True
        probe.install_request = 'Z1,ffffff8000900668,4'
        probe.target = 0xffffff800090066c
        with self.assertRaisesRegex(RuntimeError, 'original installation'):
            probe._finish('closed')

    def test_breakpoint_success_failure_and_identity_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Probe.__new__(Probe)
            probe.run = Path(tmp)
            probe.audit = []
            probe.audit_count = 0
            probe.install_request = 'Z1,ffffff8000900668,4'
            with patch.object(module.Base, 'request', return_value='OK'):
                self.assertEqual(probe.request('z1,ffffff8000900668,4'), 'OK')
            self.assertEqual(probe.audit[-1]['request'], 'z1,ffffff8000900668,4')
            self.assertEqual(probe.audit[-1]['response'], 'OK')
            with patch.object(module.Base, 'request', return_value='E22'):
                self.assertEqual(probe.request(probe.install_request), 'E22')
            with patch.object(module.Base, 'request', side_effect=RuntimeError('RSP error: E22')):
                with self.assertRaises(RuntimeError):
                    probe.request('z1,ffffff8000900668,4')
            self.assertIn('E22', probe.audit[-1]['error'])
            with patch.object(module.Base, 'request') as remote:
                with self.assertRaises(ValueError):
                    probe.request('z1,ffffff800090066c,4')
                remote.assert_not_called()
            self.assertEqual(len((probe.run / 'upm-activity-debugger.jsonl').read_text().splitlines()), 4)

    def test_raw_stop_step_and_error_packets_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Probe.__new__(Probe)
            probe.run = Path(tmp)
            probe.audit = []
            probe.audit_count = 0
            for command, response in [('c', 'T05thread:01;'), ('vCont;s:01', 'T05thread:01;'), ('m123,4', 'E14')]:
                probe.last_command = command
                with patch.object(module.Base, 'receive', return_value=response):
                    self.assertEqual(probe.receive(0), response)
                self.assertEqual(probe.audit[-1]['command'], command)
                self.assertEqual(probe.audit[-1]['raw_hex'], response.encode('ascii').hex())
            probe.audit_count = 1024
            probe.note('beyond-explicit-limit')
            self.assertEqual(len(probe.audit), 3)
            self.assertEqual(probe.audit_count, 1025)

    def test_real_error_parser_preserves_raw_cleanup_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Probe.__new__(Probe)
            probe.run = Path(tmp)
            probe.audit = []
            probe.audit_count = 0
            probe.install_request = 'Z1,ffffff8000900668,4'
            with patch.object(module.Base, 'send'), patch.object(module.Base, 'receive', return_value='E22'):
                with self.assertRaisesRegex(RuntimeError, 'E22'):
                    probe.request('z1,ffffff8000900668,4')
            self.assertEqual(probe.audit[0]['response'], 'E22')
            self.assertEqual(probe.audit[0]['raw_hex'], '453232')
            self.assertEqual(probe.audit[1]['request'], 'z1,ffffff8000900668,4')

    def test_runner_rejects_shared_debuggers_before_launch(self):
        runner = Path(__file__).with_name('run-full-system.py')
        for flag, message in [('--observe-panel-tick', 'Select only one'),
                              ('--fatal-probe', 'without another debugger')]:
            result = subprocess.run([sys.executable, '-B', str(runner), '--stage', 'init2',
                                     '--observe-upm-activity', flag],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(message, result.stderr)
            self.assertNotIn('FULLSYSTEM_RUN', result.stdout)

    def test_runner_summarizes_activity_without_write_fields(self):
        summarize = runpy.run_path(str(Path(__file__).with_name('run-full-system.py')))['collect_observer_result']
        result = {'state': 'observation-completed'}
        summarize(SimpleNamespace(KIND='upm-activity', hits=[], armed_at=1.0), result)
        self.assertEqual(result['state'], 'observation-completed')
        self.assertTrue(result['upm_activity_probe_armed'])
        self.assertEqual(result['upm_activity_command_reads_observed'], 0)
        self.assertFalse(result['upm_activity_wake_verified'])
        self.assertNotIn('shutdown_factor_writes_observed', result)

    def test_summary_failure_leaves_cleanup_path_available(self):
        summarize = runpy.run_path(str(Path(__file__).with_name('run-full-system.py')))['collect_observer_result']
        result = {'state': 'observation-completed'}
        summarize(SimpleNamespace(KIND='shutdown-write', captured=False), result)
        self.assertEqual(result['state'], 'failed')
        self.assertIn('writes', result['diagnostic_summary_error'])
        self.assertIn('Diagnostic summary failed', result['error'])


if __name__ == '__main__':
    unittest.main()
