from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parents[2] / 'report/virtual-cp/udate-distribution'


def test_source_bound_bb_remainder_ingress(tmp_path):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')

    def run(argv):
        result = subprocess.run(list(map(str, argv)), cwd=tmp_path, env=environment,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f'{argv}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')

    binary = tmp_path / 'bb-remainder'
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
         '-DNDEBUG', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
         '-no-pie', '-pthread', HERE / 'test_bb_remainder.c', '-o', binary])
    for command in ('011b', '0150'):
        for case in ('replay', 'values', 'invalid', 'all-opcodes', 'ownership', 'failure', 'reuse', 'concurrent'):
            run([binary, command, case])
