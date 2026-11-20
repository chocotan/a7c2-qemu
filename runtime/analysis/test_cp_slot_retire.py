from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent / 'device-models'


def test_zero_reply_request_retirement(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'{argv}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')

    binary = tmp_path / 'cp-slot-retire'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-DSLOT_RETIRE_EMBEDDED', '-fsanitize=address,undefined',
         '-fno-omit-frame-pointer', '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'test_cp_slot_retire.c')], '-o', binary])
    for index in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        for case in ('sequence', 'same-value', 'reuse-address', 'free-failure',
                     'busy', 'reentrant', 'reject', 'overflow', 'concurrent'):
            run([binary, case, index])
    run([binary, 'preview-wire', 9])
    run([binary, 'fork', 9])
    run([binary, 'release-key-wire', 8])
    run([binary, 'fork', 8])
    run([binary, 'still-lock-wire', 7])
    run([binary, 'fork', 7])
    run([binary, 'capture-census', 7])
    run([binary, 'all-slots', 2])
