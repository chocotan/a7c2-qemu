#!/usr/bin/env python3
import ast
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import runpy
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


class ProbeWiring(unittest.TestCase):
    def test_probe_is_mounts_only_and_guard_is_before_lock(self):
        result = subprocess.run([sys.executable, '-B', str(HERE / 'run-full-system.py'), '--stage', 'init2', '--pin-control-probe'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('backing probe requires mounts', result.stderr)

    def test_default_handoff_has_no_control_reservation(self):
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        nodes = [node for node in ast.walk(tree) if isinstance(node, ast.If) and
                 ast.unparse(node.test) == 'pin_control_reservation' and 'handoff.extend' in ast.unparse(node)]
        self.assertEqual(len(nodes), 1)
        code = compile(ast.Module(body=nodes, type_ignores=[]), '<handoff>', 'exec')
        for reservation in (None, 'memrsv=0x00002000@0x500000000:uc'):
            scope = {'pin_control_reservation': reservation, 'handoff': []};exec(code, scope)
            self.assertEqual(scope['handoff'], [] if reservation is None else ['fullsystem.pin-control-memory=1', reservation])

    def test_board_hook_is_conditional_idempotent_and_valid_shell(self):
        tree = ast.parse((HERE / 'build-full-system.py').read_text())
        node = next(node for node in tree.body if isinstance(node, ast.If) and
                    ast.unparse(node.test) == "'FULLSYSTEM_PIN_CONTROL_RESERVATION' not in text")
        code = compile(ast.Module(body=[node], type_ignores=[]), '<DTB hook>', 'exec')
        source = (HERE / 'runtime/analysis/qemu-kernel-probe.sh').read_text()
        scope = {'text': source};exec(code, scope);first = scope['text'];exec(code, scope)
        self.assertEqual(first, scope['text'])
        self.assertIn('if "fullsystem.pin-control-memory=1" in sys.argv[3].split():', first)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'board.sh';path.write_text(first)
            result = subprocess.run(['bash', '-n', str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)


class ConnectionWiring(unittest.TestCase):
    def test_control_requires_explicit_both_registries_before_lock(self):
        result = subprocess.run([sys.executable, '-B', str(HERE / 'run-full-system.py'), '--pin-connection', 'control'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires original untraced init2', result.stderr)

    def test_cold_guest_environment_and_handoff(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_PIN_CONNECTION'), source.index('/simulation/seed-power-on'))
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        nodes = [node for node in ast.walk(tree) if isinstance(node, ast.If) and
                 'args.pin_connection' in ast.unparse(node.test) and 'handoff.append' in ast.unparse(node)]
        self.assertEqual(len(nodes), 1)
        code = compile(ast.Module(body=nodes, type_ignores=[]), '<control handoff>', 'exec')
        for profile in ('off', 'control'):
            scope = {'args': SimpleNamespace(pin_connection=profile), 'handoff': []};exec(code, scope)
            self.assertEqual(scope['handoff'], [] if profile == 'off' else ['fullsystem.pin-connect=control'])

    def test_boundary_waits_for_original_waiter_buffer_and_blocked_continuation(self):
        ready = runpy.run_path(str(HERE / 'run-full-system.py'))['pin_format_block_ready']
        freed = b'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE tid=55 sender=55 waiter=1 destination=0x81ab0001 bytes=56 command=0x8001 rc=0\n'
        buffer = b'OBS FULL_PIN_CONNECT_BUFFER_WRITTEN tid=55 physical=0x500000000\n'
        held = b'OBS FULL_PIN_CONNECT_FORMAT_BLOCKED_REQUEST tid=55 source=0x81ab0001 destination=0x90590818 pointer=0x100 bytes=48 raw=00\n'
        with patch.dict(ready.__globals__, {'boot_config_waiters_ready': lambda *args: False}):
            self.assertFalse(ready(freed + buffer + held))
        with patch.dict(ready.__globals__, {'boot_config_waiters_ready': lambda *args: True}):
            self.assertFalse(ready(buffer + held))
            self.assertFalse(ready(freed + held))
            self.assertFalse(ready(freed + buffer + held.replace(b'tid=55', b'tid=56')))
            self.assertTrue(ready(freed + buffer + held))


if __name__ == '__main__':
    unittest.main()
