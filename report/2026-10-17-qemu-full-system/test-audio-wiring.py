#!/usr/bin/env python3
"""Host-only boot-profile wiring checks; never start a VM or touch its inputs."""
import ast
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent


class AudioWiring(unittest.TestCase):
    def test_boot_requires_owner_before_runtime_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'),
                                 '--stage', 'init2', '--audio-service', 'boot'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires --system-sound-memory', result.stderr)

    def test_owner_requires_init2_before_runtime_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'),
                                 '--audio-service', 'boot', '--system-sound-memory'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires the explicit init2 boot wrapper', result.stderr)

    def test_actual_handoff_statement(self):
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        statements = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and 'args.audio_service' in ast.unparse(node.test)
                      and 'handoff.append' in ast.unparse(node)]
        self.assertEqual(len(statements), 1)
        statement = compile(ast.Module(body=statements, type_ignores=[]), '<handoff>', 'exec')
        for profile in ('off', 'volume', 'boot'):
            scope = {'args': SimpleNamespace(audio_service=profile), 'handoff': []}
            exec(statement, scope)
            self.assertEqual(scope['handoff'], [] if profile == 'off' else ['fullsystem.audio=' + profile])

    def test_wrapper_syntax_and_environment_gate(self):
        wrapper = HERE / 'guest/bootin-wrapper'
        subprocess.run(['sh', '-n', str(wrapper)], check=True)
        source = wrapper.read_text()
        self.assertLess(source.index('unset FULLSYSTEM_AUDIO_SERVICE'),
                        source.index('/simulation/seed-power-on'))
        boot = source[source.index('*" fullsystem.audio=boot "*'):source.index('*" fullsystem.audio=volume "*')]
        self.assertLess(boot.index('FULLSYSTEM_AUDIO_OWNER_REQUIRED'),
                        boot.index('export FULLSYSTEM_AUDIO_SERVICE=boot'))


class HdmiWiring(unittest.TestCase):
    def test_definition_requires_init2_before_runtime_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'),
                                 '--hdmi-service', 'definition'], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('HDMI definition configuration requires', result.stderr)

    def test_explicit_handoff_only(self):
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        statements = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and 'args.hdmi_service' in ast.unparse(node.test)
                      and 'handoff.append' in ast.unparse(node)]
        self.assertEqual(len(statements), 1)
        statement = compile(ast.Module(body=statements, type_ignores=[]), '<hdmi-handoff>', 'exec')
        for profile in ('off', 'definition', 'boot'):
            scope = {'args': SimpleNamespace(hdmi_service=profile), 'handoff': []}
            exec(statement, scope)
            self.assertEqual(scope['handoff'], [] if profile == 'off' else ['fullsystem.hdmi='+profile])

    def test_no_inherited_enable(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_HDMI_SERVICE'), source.index('/simulation/seed-power-on'))
        self.assertLess(source.index('*" fullsystem.hdmi=definition "*'),
                        source.index('export FULLSYSTEM_HDMI_SERVICE=definition'))


class PinMemWiring(unittest.TestCase):
    def test_registry_requires_init2_before_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'), '--pinmem-service', 'registry'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('PinMemMgr registry requires', result.stderr)

    def test_owner_handoff_is_independent(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_PINMEM_SERVICE'), source.index('/simulation/seed-power-on'))
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        statements = [node for node in ast.walk(tree) if isinstance(node, ast.If) and
                      'args.pinmem_service' in ast.unparse(node.test) and 'handoff.append' in ast.unparse(node)]
        self.assertEqual(len(statements), 1)
        code = compile(ast.Module(body=statements, type_ignores=[]), '<pinmem>', 'exec')
        for profile in ('off', 'registry'):
            scope = {'args': SimpleNamespace(pinmem_service=profile), 'handoff': []}
            exec(code, scope)
            self.assertEqual(scope['handoff'], [] if profile == 'off' else ['fullsystem.pinmem=registry'])


class VefWiring(unittest.TestCase):
    def test_registry_requires_init2_before_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'), '--vef-service', 'registry'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('VEF registry requires', result.stderr)

    def test_environment_and_handoff_are_explicit(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_VEF_SERVICE'), source.index('/simulation/seed-power-on'))
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        statements = [node for node in ast.walk(tree) if isinstance(node, ast.If) and
                      'args.vef_service' in ast.unparse(node.test) and 'handoff.append' in ast.unparse(node)]
        self.assertEqual(len(statements), 1)
        code = compile(ast.Module(body=statements, type_ignores=[]), '<vef>', 'exec')
        for profile in ('off', 'registry'):
            scope = {'args': SimpleNamespace(vef_service=profile), 'handoff': []}
            exec(code, scope)
            self.assertEqual(scope['handoff'], [] if profile == 'off' else ['fullsystem.vef=registry'])


class LiroObserverWiring(unittest.TestCase):
    def test_requires_original_init2_before_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'), '--observe-liro-loader'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('LIRO loader observation requires original init2', result.stderr)

    def test_memory_requires_explicit_native_observer(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'), '--probe-liro-memory'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires --observe-liro-loader', result.stderr)

    def test_module_is_separate_and_explicit(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_LIRO_OBSERVE'), source.index('/simulation/seed-power-on'))
        self.assertLess(source.index('*" fullsystem.liro-observe=1 "*'),
                        source.index('LD_PRELOAD=/simulation/liro-observe.so:'))


class CapabilityWiring(unittest.TestCase):
    def test_owner_requires_boot_profile_before_lock(self):
        result = subprocess.run([sys.executable, str(HERE / 'run-full-system.py'),
                                 '--stage', 'init2', '--audio-capabilities', 'inputless'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Audio capability owner requires', result.stderr)

    def test_handoff_is_explicit(self):
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        statements = [node for node in ast.walk(tree) if isinstance(node, ast.If)
                      and 'args.audio_capabilities' in ast.unparse(node.test)
                      and 'handoff.append' in ast.unparse(node)]
        self.assertEqual(len(statements), 1)
        code = compile(ast.Module(body=statements, type_ignores=[]), '<caps>', 'exec')
        for profile in ('off', 'inputless'):
            scope = {'args': SimpleNamespace(audio_capabilities=profile), 'handoff': []}
            exec(code, scope)
            self.assertEqual(scope['handoff'], [] if profile == 'off' else ['fullsystem.audio-caps=inputless'])

    def test_wrapper_drops_inherited_owner(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_AUDIO_CAPABILITIES'), source.index('/simulation/seed-power-on'))
        self.assertIn('FULLSYSTEM_AUDIO_CAPABILITIES_REQUIRE_BOOT', source)


if __name__ == '__main__':
    unittest.main()
