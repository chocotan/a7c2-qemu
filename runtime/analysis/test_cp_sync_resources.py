from pathlib import Path
import os
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent / 'device-models'


class CpSyncResources(unittest.TestCase):
    def compile_and_run(self, sources):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'cp-sync-resources'
            compiled = subprocess.run([
                'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                '-pthread', str(HERE / 'cp-sync-resources.c'),
                *[str(HERE / source) for source in sources], '-o', str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                               UBSAN_OPTIONS='halt_on_error=1')
            result = subprocess.run([str(binary)], cwd=directory, env=environment,
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_backing_and_lease_lifecycle(self):
        self.compile_and_run(['test-cp-sync-resources.c'])

    def test_selected_control_boundaries_with_real_backing(self):
        self.compile_and_run(['cp-cold-control.c', 'test-cp-cold-control.c'])


if __name__ == '__main__':
    unittest.main()
