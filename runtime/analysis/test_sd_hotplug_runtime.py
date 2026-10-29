"""Host queue/lifecycle tests; no guest or actual media notifications."""
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def test_single_worker_protocol_and_observation_requirements():
    for case in ('cycle', 'unbound', 'flush-fail', 'not-sent', 'uncertain', 'unretired',
                 'overrun', 'unrelated', 'stale-fsys'):
        with tempfile.TemporaryDirectory(prefix='sd-runtime-', dir='/var/tmp') as tmp:
            binary = Path(tmp)/'test-runtime'
            env = {**os.environ, 'TMPDIR': tmp, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                   'UBSAN_OPTIONS': 'halt_on_error=1'}
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-g', '-O1',
                            '-pthread', '-no-pie', '-fsanitize=address,undefined',
                            '-fno-sanitize-recover=all', '-I', str(HERE),
                            '-DSD_HOTPLUG_DIRECTORY="'+tmp+'"', str(HERE/'sd-state.c'),
                            str(HERE/'sd-hotplug-runtime.c'), str(HERE/'test-sd-hotplug-runtime.c'),
                            '-o', str(binary)], env=env, check=True)
            subprocess.run([str(binary), case], env=env, check=True, timeout=10)
