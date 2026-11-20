from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent / 'device-models'


def test_source_bound_4023_retirement(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=40)
        if result.returncode:
            raise RuntimeError(f'{argv}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')

    binary = tmp_path / 'cp-4023'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'test_cp_4023.c')], '-o', binary])
    for case in ('sequence', 'reuse', 'bounded', 'semantics', 'unknown-crossing',
                 'reentrant', 'minimal', 'free-failure', 'reject', 'fork',
                 'aliases', 'overflow', 'concurrent'):
        run([binary, case])
