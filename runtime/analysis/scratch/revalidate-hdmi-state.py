#!/usr/bin/env python3
"""Validate a finite HDMI lifetime fix and run its original-consumer experiment."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import time

BASE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rp = BASE / 'scratch/hdmi-kernel-receipt-host-regression.json'
    ap = BASE / 'scratch/hdmi-kernel-receipt-abi.json'
    old, abi = json.loads(rp.read_text()), json.loads(ap.read_text())
    assert not old['returncode'] and not abi['returncode']
    sources = {name: sha(Path(name)) for name in old['production_sources_before']}
    changed = [name for name in sources if sources[name] != old['production_sources_before'][name]]
    assert {Path(name).name for name in changed} <= {'hdmi-video-state.c', 'test-hdmi-video-state.c'}, changed
    host = {name: sha(Path(name)) for name in old['host_profile_sources_before']}
    assert host == old['host_profile_sources_before']
    observers = {name: sha(Path(name)) for name in old['observer_sources_before']}
    modules = ['test_hdmi_video_state.py', 'test_pinmem_hdmi_video_connection.py', 'test_hdmi_upm_receipt.py',
               'test_hdmi_upm_watch.py', 'scratch/test_run_hdmi_observed.py']
    result = subprocess.run(['python3', '-B', '-m', 'pytest', '--color=no', '-q', '--tb=short', *modules],
                            cwd=BASE, text=True, capture_output=True)
    print(result.stdout, end='', flush=True)
    assert not result.returncode, result.stdout + result.stderr
    count = re.search(r'(\d+) passed', result.stdout)
    assert count and sources == {name: sha(Path(name)) for name in sources}
    assert observers == {name: sha(Path(name)) for name in observers}
    stamp = str(time.time_ns())
    base_reg = rp.with_name('hdmi-state-base-regression-' + stamp + '.json')
    rp.rename(base_reg)
    ap.rename(ap.with_name('hdmi-state-base-abi-' + stamp + '.json'))
    log = BASE / 'scratch' / ('hdmi-state-validation-' + stamp + '.log')
    log.write_text(result.stdout + result.stderr)
    reg = {'scope': 'targeted HDMI message-lifetime root fix; preceding full/targeted baselines retained',
           'base_regression': str(base_reg), 'base_regression_sha256': sha(base_reg),
           'modules': modules, 'module_count': len(modules), 'returncode': 0,
           'tests_passed': int(count[1]), 'subtests_passed': 0, 'changed_production_sources': changed,
           'production_sources_before': sources, 'host_profile_sources_before': host,
           'observer_sources_before': observers, 'production_sources_changed': [],
           'host_profile_sources_changed': [], 'observer_sources_changed': [],
           'log': str(log), 'log_sha256': sha(log), 'capture_verified': False}
    with rp.open('x') as output:
        output.write(json.dumps(reg, indent=2) + '\n')
    built = subprocess.run(['bash', str(BASE / 'build-observers.sh')], cwd=BASE, text=True, capture_output=True)
    (BASE / 'scratch' / ('hdmi-state-build-' + stamp + '.log')).write_text(built.stdout + built.stderr)
    assert not built.returncode, (built.stdout + built.stderr)[-8000:]
    build = json.loads((BASE / 'observer-build-inputs.json').read_text())
    assert {name: entry['sha256'] for name, entry in build['sources'].items()} == sources
    env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}
    env['MENU_OBSERVE_SELFTEST'] = '1'
    check = subprocess.run(abi['command'], cwd=BASE, env=env, text=True, capture_output=True, timeout=30)
    assert not check.returncode and 'PASS: constructor thread and application-init wrapper preserved behavior' in check.stdout
    abi = {'scope': 'original libc2.25 ABI after finite HDMI lifetime fix',
           'observer_sha256': build['observer_sha256'], 'source_archive_sha256': build['source_archive_sha256'],
           'source_count': len(sources), 'host_tests_passed': reg['tests_passed'], 'host_subtests_passed': 0,
           'host_regression_sha256': sha(rp), 'all_compiled_source_bytes_equal_tested_inputs': True,
           'command': abi['command'], 'environment': {'MENU_OBSERVE_SELFTEST': '1'},
           'returncode': 0, 'stdout': check.stdout, 'stderr': check.stderr, 'capture_verified': False}
    with ap.open('x') as output:
        output.write(json.dumps(abi, indent=2) + '\n')
    print('HDMI_STATE_TESTED_AND_ORIGINAL_ABI_PASS', reg['tests_passed'], build['observer_sha256'], flush=True)
    return subprocess.run(['python3', '-B', str(BASE / 'scratch/run-hdmi-observed.py')], cwd=BASE).returncode


if __name__ == '__main__':
    raise SystemExit(main())
