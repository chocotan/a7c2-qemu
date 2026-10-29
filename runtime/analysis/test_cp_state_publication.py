"""Owned virtual data and native-receive-shaped host fixtures, not VM evidence."""
from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent


def test_publication_data_and_original_receive_lifecycle(tmp_path):
    source = HERE / 'device-models'
    files = [source / name for name in ('test-cp-state-publication.c', 'cp-state-publication.c',
             'cp-start-state-data.c', 'cp-full-state-snapshot.c', 'cp-state-snapshot.c')]
    binary = tmp_path / 'publication'
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-pthread',
                            *map(str, files), '-o', str(binary)], capture_output=True, text=True, timeout=40)
    assert built.returncode == 0, built.stdout + built.stderr
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
           'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1'}
    for case in range(19):
        result = subprocess.run([str(binary), str(case)], env=env, capture_output=True,
                                text=True, timeout=10)
        assert result.returncode == 0, f'case={case}\n{result.stdout}\n{result.stderr}'
