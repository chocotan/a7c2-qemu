#!/usr/bin/env python3
"""Revalidate changed host observation code; preserve the tested guest baseline."""
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
    reg_path = BASE / 'scratch/hdmi-kernel-receipt-host-regression.json'
    abi_path = BASE / 'scratch/hdmi-kernel-receipt-abi.json'
    reg, abi = json.loads(reg_path.read_text()), json.loads(abi_path.read_text())
    assert not reg['returncode'] and not abi['returncode']
    assert abi['host_regression_sha256'] == sha(reg_path)
    for name, digest in {**reg['production_sources_before'], **reg['host_profile_sources_before']}.items():
        assert sha(Path(name)) == digest, name
    assert sha(BASE / 'menu-observe.so') == abi['observer_sha256']
    observed = {name: sha(Path(name)) for name in reg['observer_sources_before']}
    command = ['python3', '-B', '-m', 'pytest', '--color=no', '-q', '--tb=short',
               'scratch/test_run_hdmi_observed.py', 'test_hdmi_upm_watch.py']
    test = subprocess.run(command, cwd=BASE, text=True, capture_output=True)
    print(test.stdout, end='', flush=True)
    assert not test.returncode, test.stdout + test.stderr
    match = re.search(r'(\d+) passed', test.stdout)
    assert match and int(match[1]) >= 76
    assert observed == {name: sha(Path(name)) for name in observed}, 'host sources changed during validation'
    stamp = str(time.time_ns())
    log = BASE / 'scratch' / ('hdmi-host-validation-' + stamp + '.log')
    log.write_text(test.stdout + test.stderr)
    proof = {'scope': 'host observer-only validation; complete guest regression remains unchanged',
             'base_regression_sha256': sha(reg_path), 'command': command, 'returncode': 0,
             'tests_passed': int(match[1]), 'observer_sources_after': observed,
             'changed_observer_sources': [name for name in observed if observed[name] != reg['observer_sources_before'][name]],
             'log': str(log), 'log_sha256': sha(log), 'capture_verified': False}
    validation = BASE / 'scratch/hdmi-kernel-host-socket-validation.json'
    if validation.exists():
        validation.rename(validation.with_name('hdmi-host-validation-' + stamp + '.json'))
    with validation.open('x') as output:
        output.write(json.dumps(proof, indent=2) + '\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}
    env['MENU_OBSERVE_SELFTEST'] = '1'
    result = subprocess.run(abi['command'], cwd=BASE, env=env, text=True, capture_output=True, timeout=30)
    assert not result.returncode and 'PASS: constructor thread and application-init wrapper preserved behavior' in result.stdout
    abi_path.rename(abi_path.with_name('hdmi-host-abi-' + stamp + '.json'))
    abi.update(host_socket_validation_sha256=sha(validation), returncode=result.returncode,
               stdout=result.stdout, stderr=result.stderr)
    with abi_path.open('x') as output:
        output.write(json.dumps(abi, indent=2) + '\n')
    print('HOST_OBSERVER_AND_ORIGINAL_ABI_VALIDATED', proof['tests_passed'], flush=True)
    return subprocess.run(['python3', '-B', str(BASE / 'scratch/run-hdmi-observed.py')], cwd=BASE).returncode


if __name__ == '__main__':
    raise SystemExit(main())
