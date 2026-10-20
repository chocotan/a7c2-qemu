#!/usr/bin/env python3
"""Check profile isolation, result provenance and the build/runtime lock handoff."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

base = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('start_menu', base / 'start-menu.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
env = launcher.profile_environment({'PATH': '/usr/bin', 'MENU_BB_READY_INJECT': '1',
                                    'MENU_EXTRA_MODULES': 'all', 'QEMU_BOOT_TYPE': '8',
                                    'SONY_DMM_SERVICE': '1', 'SKIP_REBUILD': '1',
                                    'SEED_BACKUP': 'real', 'PRELOAD_ALL': '1', 'CPIO_PAD_BYTES': '65536'})
assert env['PATH'] == '/usr/bin' and env['QEMU_BOOT_TYPE'] == '1'
assert env['MENU_HEADLESS_OSD'] == '1' and env['MENU_SETTLE_SECONDS'] == '8'
assert all(name not in env for name in ('MENU_BB_READY_INJECT', 'MENU_EXTRA_MODULES', 'SONY_DMM_SERVICE', 'SKIP_REBUILD'))
assert 'MENU_KEY_INJECT' not in env
assert all(name not in env for name in ('SEED_BACKUP', 'PRELOAD_ALL', 'CPIO_PAD_BYTES'))
assert launcher.profile_environment({}, True)['MENU_KEY_INJECT'] == '0x1ab,0,1,0,1,0.05,0'
natural=launcher.profile_environment({'DISPLAY':':0','MENU_APPLY_MENU':'1','MENU_INJECT_KEY':'language-pressrelease',
                                     'MENU_KEY_INJECT':'bad','MENU_EXTRA_MODULES':'all'},natural_boot=True)
assert natural['DISPLAY']==':0' and natural['MENU_RM_FILE']=='1' and natural['MENU_DMM_UNIT_CONFIG']=='1'
assert natural['MENU_CP_RELEASE_SERVICE']=='1' and natural['MENU_DATE_SERVICE']=='1'
assert natural['MENU_LIVE_APP_INPUT']=='1' and natural['MENU_GUI_MODELS']=='virtual-inline-v1'
assert 'MENU_LIVE_KEY_FILE' not in natural
assert all(name not in natural for name in ('MENU_APPLY_MENU','MENU_INJECT_KEY','MENU_KEY_INJECT','MENU_OPEN_SET','MENU_EXTRA_MODULES'))
assert 'MENU_CP_BACKGROUND' not in launcher.profile_environment(
    {'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1'},natural_boot=True)
cp_profile=launcher.profile_environment({'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
                                        'MENU_BB_READY_INJECT':'1'},natural_boot=True)
assert cp_profile['MENU_CP_BACKGROUND']=='virtual-mode3-cold-v1' and 'MENU_BB_READY_INJECT' not in cp_profile
# The single-slot RM1 diagnostic is opt-in and must survive the MENU_ scrub,
# while staying absent unless explicitly requested.
assert 'MENU_RM_SLOT1' not in cp_profile
slot_profile=launcher.profile_environment({'MENU_RM_SLOT1':'1'},natural_boot=True)
assert slot_profile['MENU_RM_SLOT1']=='1'
assert 'MENU_RM_SLOT1' not in launcher.profile_environment({'MENU_RM_SLOT1':'0'},natural_boot=True)
assert 'MENU_RM_SLOT1' not in launcher.profile_environment({'MENU_RM_SLOT1':'1'},natural_boot=False)
# The isolated-USB run must reach its candidate QEMU build even though QEMU_* is scrubbed.
usb_profile=launcher.profile_environment({'MENU_USB_NET':'1','QEMU_SYSTEM_DIR':'/opt/candidate'},natural_boot=True)
assert usb_profile['QEMU_SYSTEM_DIR']=='/opt/candidate'
assert usb_profile['QEMU_SYSTEM_BINARY']=='qemu-system-aarch64'
assert 'QEMU_SYSTEM_DIR' not in launcher.profile_environment({'QEMU_SYSTEM_DIR':'/opt/x'},natural_boot=True)
for current,is_natural in (({'A7C2_CP_BACKGROUND':'bad'},True),
                           ({'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1'},False)):
    try:launcher.profile_environment(current,natural_boot=is_natural)
    except ValueError as error:assert 'A7C2_CP_BACKGROUND' in str(error)
    else:raise AssertionError('unsupported CP feature/profile accepted')

source = (base / 'qemu-menu-probe.py').read_text()
start = source.index('lock_path = base /')
lock_code = compile(source[start:source.index("runs = base /", start)], 'actual-probe-lock', 'exec')
with tempfile.TemporaryDirectory(prefix='menu-launch-test-') as directory:
    root = Path(directory)
    runs = root / 'menu-runs'; runs.mkdir()
    valid = 'build output\n' + json.dumps({'run': str(runs / 'run-test'), 'probe_collected': True}, indent=2) + '\nCapture complete'
    assert launcher.result_directory(valid, runs) == runs / 'run-test'
    for output in ('failed before summary', json.dumps({'run': str(root), 'probe_collected': True}),
                   json.dumps({'run': str(runs / 'run-test'), 'probe_collected': False})):
        try:
            launcher.result_directory(output, runs)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid result accepted')
    lock_path = root / '.menu-probe.lock'
    for inherited in (False, True):
        held = lock_path.open('a') if inherited else None
        if held:
            fcntl.flock(held, fcntl.LOCK_EX)
        lock_env = {} if held is None else {'MENU_PROBE_LOCK_FD': str(os.dup(held.fileno()))}
        namespace = {'base': root, 'os': os, 'fcntl': fcntl}
        with patch.dict(os.environ, lock_env, clear=True):
            exec(lock_code, namespace)
        assert subprocess.run(['flock', '-n', str(lock_path), 'true']).returncode != 0
        namespace['lock'].close()
        if held:
            held.close()
        assert subprocess.run(['flock', '-n', str(lock_path), 'true']).returncode == 0
    with (root / 'wrong-file').open('a') as wrong:
        namespace = {'base': root, 'os': os, 'fcntl': fcntl}
        with patch.dict(os.environ, {'MENU_PROBE_LOCK_FD': str(os.dup(wrong.fileno()))}, clear=True):
            try:
                exec(lock_code, namespace)
            except RuntimeError:
                namespace['lock'].close()
            else:
                raise AssertionError('unrelated inherited descriptor accepted')
    moved = root / 'moved runtime with spaces' / 'analysis'
    moved.mkdir(parents=True)
    (moved / 'run-menu-probe.sh').write_bytes((base / 'run-menu-probe.sh').read_bytes())
    (moved / 'qemu-menu-probe.py').write_text('''import os, pathlib, subprocess
base = pathlib.Path(__file__).resolve().parent
fd = int(os.environ['MENU_PROBE_LOCK_FD'])
assert os.fstat(fd).st_ino == (base / '.menu-probe.lock').stat().st_ino
assert subprocess.run(['flock', '-n', str(base / '.menu-probe.lock'), 'true']).returncode != 0
print('PORTABLE_WRAPPER_PASS')
''')
    result = subprocess.run(['bash', str(moved / 'run-menu-probe.sh')], cwd='/',
                            env=dict(os.environ, SKIP_REBUILD='1'), text=True, capture_output=True)
    assert result.returncode == 0 and 'PORTABLE_WRAPPER_PASS' in result.stdout, result.stderr
print('PASS: isolated launch profile, exact run result and exclusive build/runtime lock handoff')
