#!/usr/bin/env python3
"""Freeze diagnostic-mode inputs, run host checks, build and check original ABI."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digests(paths):
    return {str(path): sha(path) for path in sorted(set(paths))}


def main():
    if sys.argv[1:] not in ([], ['--notification-control'], ['--capture-format'], ['--startup-controls'], ['--ee-controls'], ['--movie-format']):
        raise ValueError('choose --notification-control, --capture-format, --startup-controls, --ee-controls or --movie-format')
    notification = bool(sys.argv[1:])
    movie_format = sys.argv[1:] == ['--movie-format']
    ee_controls = sys.argv[1:] in (['--ee-controls'], ['--movie-format'])
    startup_controls = sys.argv[1:] in (['--startup-controls'], ['--ee-controls'], ['--movie-format'])
    capture_format = sys.argv[1:] in (['--capture-format'], ['--startup-controls'], ['--ee-controls'], ['--movie-format'])
    receipt_prefix = ('cp-movie-format' if movie_format else 'cp-ee-controls-v2' if ee_controls else 'cp-startup-controls' if startup_controls else 'cp-capture-format' if capture_format
                      else 'cp-notification' if notification else 'cp302c-diagnostic')
    old = json.loads((BASE / 'scratch/cp302c-noconvert-host-regression.json').read_text())
    old_abi = json.loads((BASE / 'scratch/cp302c-noconvert-abi.json').read_text())
    modules = list(dict.fromkeys([*old['modules'], 'test_cp302c_diagnostic_profile.py',
                                  'test_cp302c_diagnostic_constructor.py']))
    if notification:
        modules += ['test_cp_notification_control.py', 'test_cp_notification_profile.py',
                    'test_cp_notification_constructor.py']
        if (BASE / 'test_cp_parameter_batch.py').is_file():
            modules.append('test_cp_parameter_batch.py')
    if capture_format:
        modules += ['test_cp_capture_format.py', 'test_cp_capture_format_profile.py',
                    'test_cp_capture_format_constructor.py', 'test_cp_parameter_batch_observer.py']
        for module in ('test_cp_state_snapshot.py', 'test_jpeg_without_pin_input.py',
                       'test_cp_output_policy.py'):
            if (BASE / module).is_file():
                modules.append(module)
    if startup_controls:
        modules += ['test_cp_startup_controls_diagnostic.py', 'test_cp_startup_controls_profile.py',
                    '../../report/virtual-jpeg-engine/test_engine.py']
    if ee_controls:
        modules += ['test_cp_ee_controls_diagnostic.py', 'test_cp_ee_controls_profile.py',
                    '../../report/virtual-imaging-jpeg/test_integration.py', 'scratch/test_run_hdmi_observed.py']
    if movie_format:
        modules += ['test_cp_movie_format_diagnostic.py', 'test_cp_movie_format_profile.py',
                    '../../report/virtual-jpeg-sos/test_sos.py']
    modules = list(dict.fromkeys(modules))
    sources = digests(path for directory in (BASE, BASE / 'device-models')
                      for path in directory.iterdir() if path.suffix in ('.c', '.h', '.inc', '.sh'))
    host = digests(Path(name) for name in old['host_profile_sources_before'])
    observers = digests([*(Path(name) for name in old['observer_sources_before']),
                         *([BASE / 'scratch' / name for name in
                            ('run-last-graph.py', 'run-hdmi-observed.py', 'validate-cp302c-diagnostic.py')]
                           if ee_controls else [])])
    extra_directories = ['virtual-jpeg-engine'] if startup_controls else []
    if ee_controls:
        extra_directories += ['virtual-imaging-jpeg', 'virtual-optics']
    if movie_format:
        extra_directories.append('virtual-jpeg-sos')
    extra_test_inputs = [path for name in extra_directories for path in (BASE / '../../report' / name).glob('*')]
    tests = digests([*(Path(name) for name in old['test_sources_before']),
                     *(BASE / module for module in modules),
                     *(path for path in extra_test_inputs if path.is_file())])
    log = BASE / 'scratch' / (receipt_prefix + '-host-regression.log')
    with log.open('x') as output:
        result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '--color=no', '-q',
                                 '--tb=short', *modules], cwd=BASE, stdout=output,
                                stderr=subprocess.STDOUT, timeout=600)
    text = log.read_text()
    unchanged = all(digests(Path(name) for name in group) == group
                    for group in (sources, host, observers, tests))
    passed = re.search(r'(\d+) passed', text)
    subtests = re.search(r'(\d+) subtests passed', text)
    receipt = {'scope': 'diagnostic CP302c transport plus existing full host baseline; no native/capture claim',
               'modules': modules, 'module_count': len(modules), 'returncode': result.returncode,
               'tests_passed': int(passed[1]) if passed else 0,
               'subtests_passed': int(subtests[1]) if subtests else 0,
               'production_sources_before': sources, 'host_profile_sources_before': host,
               'observer_sources_before': observers, 'test_sources_before': tests,
               'production_sources_changed': [name for name, h in sources.items() if sha(Path(name)) != h],
               'host_profile_sources_changed': [name for name, h in host.items() if sha(Path(name)) != h],
               'observer_sources_changed': [name for name, h in observers.items() if sha(Path(name)) != h],
               'test_sources_changed': [name for name, h in tests.items() if sha(Path(name)) != h],
               'log': str(log), 'log_sha256': sha(log), 'capture_verified': False}
    rp = BASE / 'scratch' / (receipt_prefix + '-host-regression.json')
    with rp.open('x') as output:
        output.write(json.dumps(receipt, indent=2) + '\n')
    print(text[-6000:], flush=True)
    assert result.returncode == 0 and passed and unchanged, 'host regression failed or inputs changed'
    built = subprocess.run(['bash', str(BASE / 'build-observers.sh')], cwd=BASE,
                           capture_output=True, text=True, timeout=180)
    (BASE / 'scratch' / (receipt_prefix + '-build.log')).write_text(built.stdout + built.stderr)
    assert built.returncode == 0, (built.stdout + built.stderr)[-10000:]
    build = json.loads((BASE / 'observer-build-inputs.json').read_text())
    assert {name: entry['sha256'] for name, entry in build['sources'].items()} == sources
    assert all(digests(Path(name) for name in group) == group
               for group in (sources, host, observers, tests)), 'inputs changed during build'
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}
    env['MENU_OBSERVE_SELFTEST'] = '1'
    check = subprocess.run(old_abi['command'], cwd=BASE, env=env, capture_output=True,
                           text=True, timeout=30)
    abi = {'scope': 'original libc2.25 ABI for independent diagnostic CP302c profile; no native/capture claim',
           'observer_sha256': build['observer_sha256'],
           'source_archive_sha256': build['source_archive_sha256'], 'source_count': len(sources),
           'host_regression_sha256': sha(rp), 'host_tests_passed': receipt['tests_passed'],
           'host_subtests_passed': receipt['subtests_passed'],
           'all_compiled_source_bytes_equal_tested_inputs': True,
           'command': old_abi['command'], 'environment': {'MENU_OBSERVE_SELFTEST': '1'},
           'returncode': check.returncode, 'stdout': check.stdout, 'stderr': check.stderr,
           'capture_verified': False}
    with (BASE / 'scratch' / (receipt_prefix + '-abi.json')).open('x') as output:
        output.write(json.dumps(abi, indent=2) + '\n')
    assert check.returncode == 0, check.stdout + check.stderr
    assert 'PASS: constructor thread and application-init wrapper preserved behavior' in check.stdout
    print('CP302C_DIAGNOSTIC_TESTED_ORIGINAL_ABI_PASS', receipt['tests_passed'],
          build['observer_sha256'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
