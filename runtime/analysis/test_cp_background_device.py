from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent / 'device-models'


class CpBackgroundDevice(unittest.TestCase):
    def test_control_reply_ownership_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'background'
            built = subprocess.run([
                'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
                '-Wl,--wrap=pthread_mutex_lock',
                *[str(HERE / name) for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                  'cp-background-device.c', 'test-cp-background-device.c')], '-o', str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                               UBSAN_OPTIONS='halt_on_error=1')
            for case in ('normal', 'fast-free', 'fast-reuse', 'allocfail', 'sendfail',
                         'request-free-fail', 'wrong-free', 'reply-free-fail', 'leases-full',
                         'observe-unhandled', 'real-backing-busy', 'bad-size', 'bad-source', 'bad-command',
                         'unused-bytes', 'bad-type', 'legacy-40b8', 'fork-initialization'):
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
