from pathlib import Path
import hashlib
import importlib.util
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


@pytest.fixture(scope='module')
def tcin_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('tcin') / 'model'
    subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
        '-DFULL_TCIN_TEST', str(MODEL / 'tcin-device.c'), str(MODEL / 'test-tcin.c'),
        '-o', str(binary),
    ], check=True, capture_output=True, text=True, timeout=30)
    return binary


@pytest.mark.parametrize('case', [
    'normal', 'disabled', 'invalid', 'noninactive', 'alloc-fail', 'alloc-null',
    'wrong-size', 'duplicate', 'send-fail', 'request-free-fail', 'reply-free-fail',
    'wrong-owner', 'busy', 'leases', 'request-snapshot', 'cleanup-retention', 'wrong-size-cleanup',
])
def test_tcin_bounded_contract(tcin_binary, case):
    result = subprocess.run([str(tcin_binary), case], capture_output=True, text=True,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'), timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'TCIN_TEST_PASS' in result.stdout


def test_original_cp_contract_pins():
    path = HERE / 'menu-root/cp/cpapp-b.bin'
    if not path.is_file():
        pytest.skip('Original public ALLLANG assets not prepared')
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    pins = {
        0xd16ba0: '2904000013ac6900', 0x69ac16: '027a', 0x69ac24: 'c0f88c26',
        0x1c5534: 'e702', 0x1c5ab0: '8320', 0x1c182c: '4108', 0x1c27b8: '1821',
        0x1d22c6: '40f22940', 0x1d22ca: '0021', 0x1d22cc: 'c7f043f1',
        0x1d22da: '41f08061', 0x1d230e: '0160', 0x1c5de4: '40f28220',
        0x1c3548: 'bc04', 0x69dc5e: '41f22940', 0x69dc80: '0395',
        0x1d3454: 'd6f88c06', 0x1d3460: '0860', 0x1d3462: 'ccf013f6',
        0x1d3468: '20f08060',
    }
    for address, expected in pins.items():
        raw = bytes.fromhex(expected)
        assert data[address-0x108000:address-0x108000+len(raw)] == raw, hex(address)


def test_explicit_profile_and_binding(tmp_path):
    spec = importlib.util.spec_from_file_location('tcin_start_menu', HERE / 'start-menu.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    env = {'A7C2_BACKUP_SYNC':'virtual-primary-v1', 'A7C2_BACKUP_BUILD':str(tmp_path),
           'A7C2_DIRECTORY_SD':str(tmp_path), 'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
           'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1', 'A7C2_TOUCH_PANEL':'virtual-config-v1'}
    assert 'MENU_TCIN_DETECT' not in module.profile_environment(env, natural_boot=True)
    env['A7C2_TCIN_DETECT'] = 'virtual-inactive-v1'
    assert module.profile_environment(env, natural_boot=True)['MENU_TCIN_DETECT'] == 'virtual-inactive-v1'
    with pytest.raises(ValueError):
        module.profile_environment({'A7C2_TCIN_DETECT':'virtual-inactive-v1'}, natural_boot=True)
    env['A7C2_TCIN_DETECT'] = 'virtual-enable-v1'
    with pytest.raises(ValueError):
        module.profile_environment(env, natural_boot=True)
    clean_env = {k:v for k,v in os.environ.items() if not k.startswith(('MENU_', 'A7C2_', 'QEMU_', 'SONY_'))}
    result = subprocess.run(['python3', str(HERE / 'qemu-menu-probe.py'), '--initramfs', '--observe'],
        env=dict(clean_env, MENU_TCIN_DETECT='virtual-inactive-v1'),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'explicit guarded Backup profile' in result.stderr
    result = subprocess.run(['python3', str(HERE / 'qemu-menu-probe.py'), '--initramfs', '--observe'],
        env=dict(clean_env, MENU_DFS_SELECTOR='virtual-selector-v1'),
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'explicit TCIN inactive profile' in result.stderr
    probe = (HERE / 'qemu-menu-probe.py').read_text()
    observer = (HERE / 'menu-observe.c').read_text()
    assert 'export MENU_TCIN_DETECT=virtual-inactive-v1' in probe
    assert "'tcin_hardware_verified':False" in probe
    assert 'full_tcin_dispatch' in observer and 'full_tcin_release_reply' in observer
    assert 'TCIN_PROFILE_BOUND' in (HERE / 'check-natural-gtk-input.py').read_text()
    assert 'tcin-device' in (HERE / 'build-observers.sh').read_text()
