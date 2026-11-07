#!/usr/bin/env python3
"""Product low-latency regression; host fixtures and guest compilation, never a VM."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / 'runtime/analysis'
OUT = ROOT / 'validation/tmp' / ('low-latency-' + str(time.time_ns()))


def main():
    OUT.mkdir(parents=True, mode=0o700)
    common = [sys.executable, '-B', '-m', 'pytest', '-q', '--color=no', '-p', 'no:cacheprovider', '--import-mode=importlib']
    commands = {
        'stream': common + ['runtime/analysis/test_low_latency_ui.py'],
        'window': common + ['runtime/analysis/test_camera_ui.py'],
        'control': common + ['runtime/analysis/test_menu_control.py'],
        'input': common + ['report/camera-input-coverage/test_input_bindings.py', 'runtime/analysis/test_app_input.py', 'runtime/analysis/test_key_injection.py'],
        'headless': ['bash', '-c', 'set -e; cc -O2 -Wall -Wextra -Werror "$1/headless-osd.c" "$1/test-headless-persist.c" -Wl,--wrap=pread -Wl,--wrap=fsync -Wl,--wrap=rename -o "$2/persist"; "$2/persist" "$2"', 'test', str(A), str(OUT)],
        'pixels': ['bash', '-c', 'set -e; cc -O2 -Wall -Wextra -Werror "$1/test-ramfb-viewer.c" -o "$2/pixels"; "$2/pixels"', 'test', str(A), str(OUT)],
        'guest-build': ['bash', str(A / 'build-observers.sh')],
        'bluetooth': common + ['runtime/analysis/test_virtual_hci.py'],
    }
    def one(pair):
        name, argv = pair
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', DISPLAY='',
                   PYTHONPATH=str(A), LC_ALL='C')
        if argv[:len(common)] == common:
            argv = argv + ['--junitxml=' + str(OUT / (name + '.xml')), '--basetemp', '/var/tmp/a7-low-' + str(os.getpid()) + '-' + name]
        temporary = OUT / (name + '-tmp'); temporary.mkdir(mode=0o700)
        env['TMPDIR'] = str(temporary)
        start = time.monotonic()
        with (OUT / (name + '.stdout')).open('xb') as stdout, (OUT / (name + '.stderr')).open('xb') as stderr:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        row = dict(name=name, returncode=result.returncode, elapsed_seconds=time.monotonic()-start, argv=argv)
        for stream in ('stdout', 'stderr'):
            row[stream + '_sha256'] = hashlib.sha256((OUT/(name+'.'+stream)).read_bytes()).hexdigest()
        (OUT/(name+'.json')).write_text(json.dumps(row, indent=2)+'\n')
        print(name, result.returncode, flush=True)
        return row
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(one, commands.items()))
    result = dict(schema='a7c2-product-low-latency-host-v1', workers=8, passed=all(r['returncode']==0 for r in rows),
                  results=rows, vm_executed=False, capture_verified=False)
    (OUT/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print('RESULT', OUT, flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
