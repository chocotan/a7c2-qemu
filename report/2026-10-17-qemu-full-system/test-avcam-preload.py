#!/usr/bin/env python3
import ast
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'avcam-preload.py'))
TOKEN = 'memrsv=0x01000000@0x401000000:ex'
LOADS = [('kernel', 0x400080000, 6610952), ('initrd', 0x440000000, 0x60000000)]


class Plan(unittest.TestCase):
    def test_original_adjacent_sound_ranges_and_entry_are_preserved(self):
        result = API['validate_plan'](TOKEN + ' memrsv=0x400000@0x402000000 memrsv=0x20000@0x41d000000:uc', LOADS)
        self.assertEqual(result['physical'], 0x401000000)
        self.assertEqual(result['bytes'], 0xd286e0)
        self.assertFalse(result['sets_cpu_entry'])
        self.assertFalse(result['initializes_LIRO'])

    def test_ambiguous_or_overlapping_reservations_refused(self):
        for value in ('', 'memrsv=0x1000000@0x401000000:uc', TOKEN + ' ' + TOKEN,
                      TOKEN + ' memrsv=0x100@0x401000100', TOKEN + ' memrsv=broken',
                      TOKEN + ' memrsv=0@0x500000000', TOKEN + ' memrsv=0xffffffffffffffff@0x100'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                API['validate_plan'](value, LOADS)

    def test_declared_load_cannot_overlap_image_window(self):
        for load in [('large kernel', 0x400080000, 0x2000000), ('foreign loader', 0x401100000, 0x100),
                     ('invalid extent', 0x440000000, 0)]:
            with self.subTest(load=load), self.assertRaises(ValueError):
                API['validate_plan'](TOKEN, [load])

    def test_unverified_and_symlink_images_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'bad.bin';file.write_bytes(b'not the original image')
            link = file.with_name('link.bin');link.symlink_to(file)
            for path in (file, link):
                with self.assertRaises(ValueError):
                    API['validate_image'](path)

    def test_adapter_is_explicit_readonly_and_never_changes_entry(self):
        original = (HERE / 'runtime/analysis/qemu-kernel-probe.sh').read_text()
        adapted = API['adapt_script'](original)
        self.assertEqual(API['adapt_script'](adapted), adapted)
        line = next(line for line in adapted.splitlines() if 'loader,file=/av-cam-preload.bin' in line)
        self.assertNotIn('cpu-num', line)
        self.assertIn('QEMU_FULL_AVCAM_PRELOAD:-0', adapted)
        self.assertIn('--ro-bind "$QEMU_FULL_AVCAM_IMAGE"', adapted)
        with tempfile.TemporaryDirectory() as temporary:
            file = Path(temporary) / 'script.sh';file.write_text(adapted)
            self.assertEqual(subprocess.run(['bash', '-n', str(file)], capture_output=True).returncode, 0)

    def test_preload_without_native_observers_is_refused_before_runtime_lock(self):
        import sys
        result = subprocess.run([sys.executable, '-B', str(HERE / 'run-full-system.py'), '--preload-avcam'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Original av-cam data preload requires', result.stderr)

    def test_ambient_qemu_preload_environment_is_removed(self):
        import os
        tree = ast.parse((HERE / 'run-full-system.py').read_text())
        expression = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Assign) and
                          any(isinstance(target, ast.Name) and target.id == 'env' for target in node.targets) and
                          isinstance(node.value, ast.DictComp))
        code = compile(ast.Expression(body=expression), '<env guard>', 'eval')
        from unittest.mock import patch
        with patch.dict(os.environ, {'QEMU_FULL_AVCAM_PRELOAD': '1', 'QEMU_FULL_AVCAM_IMAGE': '/unexpected/input'}, clear=True):
            self.assertEqual(eval(code, {'os': os}), {})


if __name__ == '__main__':
    unittest.main()
