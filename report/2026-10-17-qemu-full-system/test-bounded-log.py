#!/usr/bin/env python3
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading

HERE = Path(__file__).resolve().parent


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        exe = root / 'bounded-log'
        subprocess.run(['clang', '-O2', '-Wall', '-Wextra', '-Werror', '-DBOUNDED_LOG_TEST', str(HERE / 'bounded-log.c'), '-o', str(exe)], check=True)
        path = root / 'growing.log'
        path.write_bytes(bytes(range(256)) * 256)
        stop = threading.Event()

        def writer():
            with path.open('ab', buffering=0) as stream:
                while not stop.is_set():
                    stream.write(b'x' * 4096)
                    stop.wait(.0005)

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            result = subprocess.run([str(exe), str(path), '8192'], capture_output=True, timeout=3, check=True)
        finally:
            stop.set()
            thread.join()
        header, data = result.stdout.split(b'\n', 1)
        for stage in (b'open',b'fstat',b'close',b'done'):
            assert b'FULLSYSTEM_LOG_STAGE stage='+stage+b' path=' in result.stderr
        match = re.search(rb'size=(\d+) offset=(\d+) count=(\d+)$', header)
        assert match and len(data) == int(match[3]) == 8192
        with path.open('rb') as stream:
            stream.seek(int(match[2]))
            assert stream.read(8192) == data
        for value in ('0', '65537', 'bad'):
            assert subprocess.run([str(exe), str(path), value], capture_output=True).returncode == 2
        fifo = root / 'fifo'
        os.mkfifo(fifo)
        assert subprocess.run([str(exe), str(fifo), '100'], capture_output=True, timeout=2).returncode == 4
        assert subprocess.run([str(exe), str(root / 'missing'), '100'], capture_output=True).returncode == 3
        empty = root / 'empty'
        empty.touch()
        result = subprocess.run([str(exe), str(empty), '100'], capture_output=True, check=True)
        assert result.stdout.endswith(b'count=0\n')
    print('BOUNDED_LOG_GROWING_FILE_SNAPSHOT_LIMIT_ERRORS_PASS')


if __name__ == '__main__':
    main()
