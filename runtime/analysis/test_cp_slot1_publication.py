from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent / 'device-models'


class Slot1Publication(unittest.TestCase):
    def test_actual_c_snapshot_queue_and_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'slot1'
            built = subprocess.run([
                'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
                str(HERE / 'cp-slot1-publication.c'), str(HERE / 'test-cp-slot1-publication.c'),
                '-o', str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                               UBSAN_OPTIONS='halt_on_error=1')
            for case in ('normal', 'missing-effects', 'prefix-failure', 'post-failure',
                         'invalid', 'fork', 'concurrent'):
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
