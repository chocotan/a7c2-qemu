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
assert 'MENU_NATURAL_START_TRACE' not in natural
trace=launcher.profile_environment({'A7C2_NATURAL_START_TRACE':'1'},natural_boot=True)
assert trace['MENU_NATURAL_START_TRACE']=='1'
assert all(name not in trace for name in ('MENU_YC_INJECT','QEMU_CPU_COUNT','QEMU_SONY_RC','QEMU_SYSTEM_DIR'))
assert 'MENU_NATURAL_START_TRACE' not in launcher.profile_environment(
    {'MENU_NATURAL_START_TRACE':'1'},natural_boot=True)
try:launcher.profile_environment({'A7C2_NATURAL_START_TRACE':'bad'},natural_boot=True)
except ValueError:pass
else:raise AssertionError('invalid standalone natural-start observer accepted')
sparse=launcher.profile_environment({'A7C2_SD_SPARSE':'10g-empty'},natural_boot=True)
assert sparse['A7C2_SD_SPARSE']=='10g-empty'
host=launcher.profile_environment({'A7C2_HOST_SD':'256gb','A7C2_HOST_SD_FD':'99'},natural_boot=True)
assert host['A7C2_HOST_SD']=='256gb' and 'A7C2_HOST_SD_FD' not in host
assert 'MENU_YC_INJECT' not in host and 'QEMU_CPU_COUNT' not in host
directory=launcher.profile_environment({'A7C2_DIRECTORY_SD':'/tmp/owned-card','A7C2_DIRECTORY_SD_FD':'99'},natural_boot=True)
assert directory['A7C2_DIRECTORY_SD']=='/tmp/owned-card' and 'A7C2_DIRECTORY_SD_FD' not in directory
for invalid in ({'A7C2_DIRECTORY_SD':'relative'}, {'A7C2_DIRECTORY_SD':'/tmp/card','A7C2_HOST_SD':'256gb'},
                {'A7C2_DIRECTORY_SD':'/tmp/card','A7C2_NATURAL_IMAGING_PROFILE':'1'}):
    try:launcher.profile_environment(invalid,natural_boot=True)
    except ValueError:pass
    else:raise AssertionError('unsafe directory SD combination accepted')
for conflict in ({}, {'A7C2_SD_SPARSE':'10g-empty'},{'A7C2_SD_IMAGE':'seed'},
                 {'A7C2_NATURAL_IMAGING_PROFILE':'1'},{'A7C2_SD_HOTPLUG':'1'}):
    try:launcher.profile_environment({'A7C2_HOST_SD':'256gb',**conflict},natural_boot=bool(conflict))
    except ValueError:pass
    else:raise AssertionError('unsafe host SD combination accepted')
for invalid,is_natural in (({'A7C2_SD_SPARSE':'bad'},True),
                           ({'A7C2_SD_SPARSE':'10g-empty'},False),
                           ({'A7C2_SD_SPARSE':'10g-empty','A7C2_SD_IMAGE':'seed'},True),
                           ({'A7C2_SD_SPARSE':'10g-empty','A7C2_NATURAL_IMAGING_PROFILE':'1'},True)):
    try:launcher.profile_environment(invalid,natural_boot=is_natural)
    except ValueError:pass
    else:raise AssertionError('invalid sparse virtual SD profile accepted')
route=launcher.profile_environment({'A7C2_INPUT_ROUTE_TRACE':'1'},natural_boot=True)
assert route['MENU_INPUT_ROUTE_TRACE']=='1'
assert all(name not in route for name in ('MENU_YC_INJECT','QEMU_CPU_COUNT','QEMU_SONY_RC','QEMU_SYSTEM_DIR'))
assert 'MENU_INPUT_ROUTE_TRACE' not in natural
try:launcher.profile_environment({'A7C2_INPUT_ROUTE_TRACE':'bad'},natural_boot=True)
except ValueError:pass
else:raise AssertionError('invalid input-route observer accepted')
detail=launcher.profile_environment({'A7C2_INPUT_ROUTE_TRACE':'1','A7C2_INPUT_ROUTE_DETAIL':'target'},natural_boot=True)
assert detail['A7C2_INPUT_ROUTE_DETAIL']=='target' and 'MENU_INPUT_ROUTE_DETAIL' not in detail
for invalid in ({'A7C2_INPUT_ROUTE_DETAIL':'target'},
                {'A7C2_INPUT_ROUTE_TRACE':'1','A7C2_INPUT_ROUTE_DETAIL':'bad'}):
    try:launcher.profile_environment(invalid,natural_boot=True)
    except ValueError:pass
    else:raise AssertionError('unsafe input-route detail selection accepted')
assert 'MENU_CP_BACKGROUND' not in launcher.profile_environment(
    {'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1'},natural_boot=True)
cp_profile=launcher.profile_environment({'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
                                        'MENU_BB_READY_INJECT':'1'},natural_boot=True)
assert cp_profile['MENU_CP_BACKGROUND']=='virtual-mode3-cold-v1' and 'MENU_BB_READY_INJECT' not in cp_profile
udate_profile=launcher.profile_environment({'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
    'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1'},natural_boot=True)
assert udate_profile['MENU_UDATE_DISTRIBUTION']=='virtual-roundtrip-v1'
assert 'MENU_UDATE_DISTRIBUTION' not in launcher.profile_environment(
    {'MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1'},natural_boot=True)
touch_profile=launcher.profile_environment({'A7C2_TOUCH_PANEL':'virtual-config-v1',
    'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1','A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1'},natural_boot=True)
assert touch_profile['MENU_TOUCH_PANEL']=='virtual-config-v1'
assert 'MENU_TOUCH_PANEL' not in cp_profile
for current,is_natural in (({'A7C2_TOUCH_PANEL':'bad'},True),
                           ({'A7C2_TOUCH_PANEL':'virtual-config-v1'},True),
                           ({'A7C2_TOUCH_PANEL':'virtual-config-v1','A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1'},True),
                           ({'A7C2_TOUCH_PANEL':'virtual-config-v1','A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
                             'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1'},False),
                           ({'A7C2_TOUCH_PANEL':'virtual-config-v1','A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
                             'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','A7C2_NATURAL_IMAGING_PROFILE':'1'},True)):
    try:launcher.profile_environment(current,natural_boot=is_natural)
    except ValueError:pass
    else:raise AssertionError('unsupported touch-panel profile accepted')
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
imaging=launcher.profile_environment({'A7C2_NATURAL_IMAGING_PROFILE':'1','QEMU_CPU_COUNT':'8',
                                      'QEMU_SONY_SA_DATA_ONLY':'1','MENU_YC_INJECT':'0'},natural_boot=True)
assert imaging['QEMU_CPU_COUNT']=='2' and imaging['QEMU_SONY_RC']=='1'
assert imaging['QEMU_SONY_GIC_HANDOFF']=='1' and imaging['QEMU_SONY_SA_REFERENCE_COMPLETE']=='1'
assert 'QEMU_SONY_SA_DATA_ONLY' not in imaging
assert imaging['MENU_YC_INJECT']=='1' and imaging['MENU_YC_UNCOMPRESSED']=='1'
assert imaging['A7C2_RESIZE_WATCH']=='1' and imaging['MENU_SETTLE_SECONDS']=='120'
assert imaging['MENU_NATURAL_START_TRACE']=='1' and imaging['MENU_JPEG_REQUEST_TRACE']=='1'
assert imaging['QEMU_SYSTEM_BINARY']=='qemu-system-aarch64'
assert (Path(imaging['QEMU_SYSTEM_DIR'])/'qemu-system-aarch64').is_file()
assert Path(imaging['MENU_DTB']).is_file()
for current,is_natural in (({'A7C2_NATURAL_IMAGING_PROFILE':'bad'},True),
                           ({'A7C2_NATURAL_IMAGING_PROFILE':'1'},False),
                           ({'A7C2_NATURAL_IMAGING_PROFILE':'1','A7C2_PREVIEW_PNG':'x'},True),
                           ({'A7C2_NATURAL_IMAGING_PROFILE':'1','MENU_USB_NET':'1'},True)):
    try:launcher.profile_environment(current,natural_boot=is_natural)
    except ValueError:pass
    else:raise AssertionError('invalid natural imaging profile accepted')
with tempfile.TemporaryDirectory(prefix='yc-preview-profile-') as preview_dir:
    from PIL import Image
    preview=Path(preview_dir)/'still.png'
    Image.new('RGB',(12,8),(255,0,0)).save(preview)
    preview_profile=launcher.profile_environment({'A7C2_PREVIEW_PNG':str(preview)},natural_boot=True)
    assert preview_profile['MENU_YC_INPUT_PNG']==str(preview)
    assert preview_profile['MENU_YC_INJECT']=='1' and preview_profile['QEMU_SONY_PCIDMA']=='1'
    assert preview_profile['MENU_EXTRA_MODULES']=='safe' and preview_profile['MENU_VPANEL']=='1'
    try:launcher.profile_environment({'A7C2_PREVIEW_PNG':str(preview),'MENU_USB_NET':'1'},natural_boot=True)
    except ValueError as error:assert 'USB network' in str(error)
    else:raise AssertionError('incompatible PCI DMA and USB network profile accepted')
for current,is_natural in (({'A7C2_CP_BACKGROUND':'bad'},True),
                           ({'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1'},False),
                           ({'A7C2_UDATE_DISTRIBUTION':'bad','A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1'},True),
                           ({'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1'},True),
                           ({'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1'},False)):
    try:launcher.profile_environment(current,natural_boot=is_natural)
    except ValueError as error:assert ('A7C2_CP_BACKGROUND' in str(error) or
                                      'A7C2_UDATE_DISTRIBUTION' in str(error))
    else:raise AssertionError('unsupported CP/UDATE feature/profile accepted')

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
