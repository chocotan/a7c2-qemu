"""Host test for the synthetic imager frame source (no guest, no sensor).

`cmos-source.c` generates a deterministic TEST PATTERN into a buffer that a pin
consumer can read. It is never described as lens/CMOS data, and it does not make
the original firmware consider the imager ready; those stay open until a real
frame-completion event exists.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODELS = HERE/'device-models'
SOURCES = [MODELS/'cmos-source.c', MODELS/'test-cmos-source.c']


class CmosSource(unittest.TestCase):
    def test_pattern_contract_under_sanitizers(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary)/'test-cmos-source'
            compiled = subprocess.run(
                ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 *map(str, SOURCES), '-o', str(binary)],
                text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60,
                                 env={'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                      'UBSAN_OPTIONS': 'halt_on_error=1',
                                      'PATH': '/usr/bin:/bin'})
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            self.assertIn('PASS', run.stdout)

    def test_source_is_labelled_synthetic(self):
        """The header must keep saying this is a test pattern, not sensor data."""
        header = (HERE/'device-models'/'cmos-source.h').read_text()
        self.assertIn('TEST PATTERN', header)
        self.assertIn('never be', header)


if __name__ == '__main__':
    unittest.main()
