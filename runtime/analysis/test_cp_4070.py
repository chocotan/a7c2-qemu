from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent / 'device-models'


def test_source_bound_4070_preservation(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'{argv}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')

    binary = tmp_path / 'cp-4070'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'cp-background-device.c', 'test_cp_4070.c')],
         '-o', binary])
    for case in ('normal', 'reentrant', 'reject', 'minimal-transport', 'busy',
                 'two-slots', 'reverse-slots', 'alias', 'alias-reverse', 'protected-free',
                 'fork', 'fault', 'sending', 'concurrent'):
        run([binary, case])
