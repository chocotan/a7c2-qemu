"""Host test for the SD hot-plug adapter bridge (no guest, no card).

The adapter only supplies the four hooks the tested state core needs. Its contract
is what this test pins: a guard denial, a backing change and a failed original
flush each stop the transition *before* anything is sent, and delivery outcomes
are classified rather than assumed from a return code.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODELS = HERE/'device-models'
SOURCES = [HERE/'sd-state.c', MODELS/'sd-hotplug-adapter.c', MODELS/'test-sd-hotplug-adapter.c']


class SdHotplugAdapter(unittest.TestCase):
    def test_bridge_contract_under_sanitizers(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary)/'test-sd-hotplug-adapter'
            compiled = subprocess.run(
                ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                 '-no-pie', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-I', str(HERE), *map(str, SOURCES), '-o', str(binary)],
                text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60,
                                 cwd=temporary,
                                 env={**os.environ,'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                      'UBSAN_OPTIONS': 'halt_on_error=1'})
            self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
            self.assertIn('PASS', run.stdout)

if __name__ == '__main__':
    unittest.main()
