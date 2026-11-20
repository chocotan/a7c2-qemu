from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent / 'device-models'


def test_pid_key_clear_ownership(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, f'{argv}: {result.stdout}\n{result.stderr}'

    binary = tmp_path / 'cp-key-clear'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-DSLOT_RETIRE_EMBEDDED', '-DSLOT_INDEX=6',
         '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
         *[HERE / name for name in ('cp-sync-resources.c', 'cp-cold-control.c',
                                   'test_cp_slot_retire.c')], '-o', binary])
    for case in ('key-clear-wire', 'sequence', 'same-value', 'reuse-address',
                 'free-failure', 'busy', 'reentrant', 'reject', 'overflow',
                 'concurrent', 'fork', 'snapshot-errors', 'capture-census', 'all-slots'):
        run([binary, case])
