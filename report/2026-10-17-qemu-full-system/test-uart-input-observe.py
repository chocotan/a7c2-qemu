#!/usr/bin/env python3
"""Host PTY only: the observer must leave input and terminal settings untouched."""
import os
import ast
import io
import json
from pathlib import Path
import pty
import runpy
import subprocess
import tempfile
import termios
import unittest
from unittest.mock import patch
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent


class ReadOnlyTerminalObserver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='uart-observer-host-pty-')
        cls.binary = Path(cls.workspace.name) / 'observer'
        subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(HERE / 'uart-input-observe.c'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def test_input_and_termios_are_not_consumed_or_modified(self):
        master, slave = pty.openpty()
        try:
            attrs = termios.tcgetattr(slave)
            data = b'host-pty-input-must-remain\n'
            self.assertEqual(os.write(master, data), len(data))
            result = subprocess.run([str(self.binary), 'host'], stdin=slave, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'UART_TERMIOS rc=0', result.stdout)
            self.assertIn(b'UART_FOREGROUND ', result.stdout)
            self.assertEqual(termios.tcgetattr(slave), attrs)
            os.set_blocking(slave, False)
            self.assertEqual(os.read(slave, 4096), data)
        finally:
            os.close(master);os.close(slave)

    def test_unavailable_terminal_is_explicit_negative_evidence(self):
        result = subprocess.run([str(self.binary), 'host'], stdin=subprocess.DEVNULL, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'UART_TERMIOS rc=-1', result.stdout)
        self.assertIn(b'UART_INPUT_SNAPSHOT_END phase=host rc=0', result.stdout)

    def test_saved_descriptor_survives_background_stdin_redirection(self):
        master, slave = pty.openpty()
        try:
            script='exec 8<&0; "$1" background <&8 & child=$!; exec 8<&-; wait "$child"'
            result=subprocess.run(['/bin/sh','-c',script,'host-fixture',str(self.binary)],stdin=slave,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(b'UART_INHERITED_FD0 target=/dev/pts/',result.stdout)
            self.assertIn(b'UART_TERMIOS rc=0',result.stdout)
        finally:
            os.close(master);os.close(slave)

    def test_invalid_phase_does_not_start_observation(self):
        result = subprocess.run([str(self.binary), 'bad;phase'], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'')

    def test_rx_readback_does_not_consume_uart_data_or_acknowledge_irq(self):
        function=runpy.run_path(str(HERE/'run-full-system.py'))['uart_rx_readback']
        commands=[]
        def qmp(name,args):
            self.assertEqual(name,'human-monitor-command')
            commands.append(args['command-line']);return 'HOST_QMP_FIXTURE'
        values=function(qmp)
        self.assertEqual(set(values),{'0x9000018'})
        self.assertTrue(all('0x8000' not in value for value in commands))
        self.assertNotIn('xp /1wx 0x9000000',commands)
        self.assertTrue(all('0x801000c' not in value and '0x8010010' not in value for value in commands))


class SerialInputJournal(unittest.TestCase):
    def test_exact_envelope_and_complete_write_are_recorded(self):
        api=runpy.run_path(str(HERE/'run-full-system.py'));stream=io.BytesIO()
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'serial.jsonl';writer=api['PacedInput'](stream,path)
            payload=b"echo probe; printf '\\nMARKER:0\\n'\n"
            with patch.object(api['PacedInput'].write.__globals__['time'],'sleep'):
                self.assertEqual(writer.write(payload),len(payload))
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(stream.getvalue(),payload)
            self.assertEqual(bytes.fromhex(rows[0]['hex']),payload)
            self.assertEqual(rows[-1],{'write':1,'event':'complete','bytes':len(payload)})

    def test_short_write_is_not_reported_as_completed(self):
        api=runpy.run_path(str(HERE/'run-full-system.py'))
        class ShortStream(io.BytesIO):
            def write(self,data):return 0
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'serial.jsonl';writer=api['PacedInput'](ShortStream(),path)
            with self.assertRaisesRegex(RuntimeError,'Short host UART pipe write'):
                writer.write(b'no-complete')
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([row['event'] for row in rows],['begin'])


class IndependentDiagnostics(unittest.TestCase):
    def test_missing_uart_phase_does_not_gate_requested_census(self):
        tree=ast.parse((HERE/'run-full-system.py').read_text())
        node=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
                  ast.unparse(node.test)=='args.observe_uart_input' and
                  'uart_input_observation_error' in ast.unparse(node))
        code=compile(ast.Module(body=[node],type_ignores=[]),'<actual UART gate>','exec')
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)
            (out/'console.log').write_bytes(b'UART_INPUT_SNAPSHOT_END phase=before rc=0\n')
            result={};scope={'out':out,'result':result,
                'args':SimpleNamespace(probe_uart_rx=True,stacks=True,observe_uart_input=True),
                'uart_probe':{'after':{'0x9000018':'0x90'}}}
            exec(code,scope)
            self.assertIn('incomplete',result['uart_input_observation_error'])
            self.assertNotIn('no post-boot',result['uart_input_observation_error'])
            self.assertEqual(result['uart_input_snapshot_phases'],['before'])
            scope['args'].stacks=False
            with self.assertRaisesRegex(RuntimeError,'incomplete'):exec(code,scope)

    def test_pending_uart_failure_is_not_erased_after_census(self):
        tree=ast.parse((HERE/'run-full-system.py').read_text())
        node=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
                  ast.unparse(node.test)=="result.get('uart_input_observation_error')")
        code=compile(ast.Module(body=[node],type_ignores=[]),'<actual final UART check>','exec')
        result={'thread_census_completed':True,'uart_input_observation_error':'incomplete retained'}
        with self.assertRaisesRegex(RuntimeError,'incomplete retained'):exec(code,{'result':result})
        self.assertTrue(result['thread_census_completed'])


if __name__ == '__main__':
    unittest.main()
