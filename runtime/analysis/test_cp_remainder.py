from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent / 'device-models'


def test_source_bound_remainder_preservation(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'{argv}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')

    binary = tmp_path / 'cp-remainder'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'cp-background-device.c', 'test_cp_remainder.c')],
         '-o', binary])
    # 4023 retirement has its own sequence/fault fixture.
    for index in (1, 2, 3, 4, 5):
        for case in ('normal', 'reentrant', 'minimal', 'reject', 'busy', 'protected-free',
                     'fork', 'fault', 'sending', 'alias', 'reverse-alias', 'snapshot-errors'):
            run([binary, case, index])
    for case in ('all-slots', 'concurrent', 'capture-census'):
        run([binary, case, 1])
