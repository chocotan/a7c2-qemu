"""NoMem host contract, public byte anchors and profile admission; no VM."""
from pathlib import Path
import os
import hashlib
import subprocess

import pytest

MODEL = Path(__file__).resolve().parent / 'device-models'
CASES = [
    'normal', 'status22-copy-fork', 'status22-failed-next',
    'disabled', 'unrelated', 'invalid', 'missing-transport', 'missing-guard',
    'reservation-refused', 'owned-nonempty', 'stale-generation', 'generation-exhausted',
    'alloc-fail', 'alloc-null', 'duplicate', 'wrong-size', 'immutable-request',
    'resource-race', 'reply-readback', 'send-fail', 'request-free-fail',
    'reply-free-fail', 'wrong-owner', 'cleanup-retention', 'busy-recursive',
    'busy-concurrent', 'one-outstanding', 'unknown-or-double-free', 'fork-inherited', 'fork-first-call',
]


@pytest.fixture(scope='module')
def vef_path_binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('vef-path')
    binary = directory / 'model'
    flags = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-pthread']
    # Compile the actual non-test translation unit too; hooks must remain optional.
    subprocess.run(flags + ['-c', str(MODEL / 'vef-path-device.c'), '-o', str(directory / 'production.o')],
                   check=True, capture_output=True, text=True, timeout=30)
    subprocess.run(flags + [
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        '-DFULL_VEF_PATH_TEST', str(MODEL / 'vef-path-device.c'), str(MODEL / 'test-vef-path.c'),
        '-o', str(binary),
    ], check=True, capture_output=True, text=True, timeout=30)
    return binary


@pytest.mark.parametrize('case', CASES)
def test_vef_path_bounded_contract(vef_path_binary, case):
    result = subprocess.run([str(vef_path_binary), case], capture_output=True, text=True,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1'), timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'VEF_PATH_TEST_PASS:' in result.stdout


def test_original_nomem_selection_and_methods():
    original=MODEL.parent/'menu-root/cp/cpapp-b.bin'
    if not original.is_file():pytest.skip('Original public ALLLANG assets not prepared')
    data=original.read_bytes()
    assert hashlib.sha256(data).hexdigest()=='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    # These are raw offsets: the path-record state and S+0x22 have separate writers.
    assert hashlib.sha256(data[0x109c3c:0x109cde]).hexdigest()==\
        '8493b5afb66dc8f830406e00f292e924e9d9aec5e602bad3428e654f8eaa0df3'
    for raw,expected in {
        0x5f8e96:'40f8081bfff73cfa',  # accessor+8 -> the explicit backing constructor
        0x5f8324:'4ff00009c4f82090',  # zero the whole S+0x20 word, including status22
        0xc40f70:'23fe6f0033fe6f00',  # vptr d48ed8 slots +98/+9c: getter/setter
        0xc4114c:'05067000',  # accessor slot +274 returns backing+8
        0x5f8604:'08307047',
        0x5f7e22:'80b56f460168d1f874128847408c80bd',
        0x5f7e32:'d0b502af0c460168d1f8741288474484',
        0x109c66:'02214160298801603068d0f89c2030469047',
    }.items():
        expected=bytes.fromhex(expected)
        assert data[raw:raw+len(expected)]==expected,hex(raw)
    for address,expected in {
        0x1c547c:'6902',0x1c413c:'5d03',0x1cee62:'2389',
        0x10f5ff0:'70c97801',0x6ec0ae:'4798013019d0',0x6ec104:'4798013019d0',
        0x6ec13e:'0120c8f800000020',0x6ec14e:'0120186000207047',
        0x211c66:'0221416029880160',0x2134d0:'47f21831',0x2134d8:'c0f20f11',
        0x2134e2:'3821',
    }.items():
        raw=bytes.fromhex(expected)
        assert data[address-0x108000:address-0x108000+len(raw)]==raw,hex(address)


def test_observer_resource_wiring_and_pre_vm_rejection():
    native=MODEL.parent
    observer=(native/'menu-observe.c').read_text()
    build=(native/'build-observers.sh').read_text()
    probe=(native/'qemu-menu-probe.py').read_text()
    assert 'full_vef_resource_send_enter(id,vef_path_enabled)' in observer
    assert 'cleanup(full_vef_resource_send_leave)' in observer
    assert 'path_owner=full_vef_path_owner_init()' in observer
    assert 'vef_path_reserve_resources' in observer and 'full_vef_path_release_reply' in observer
    assert 'vef-path-device vef-resource-guard' in build
    assert 'export MENU_VEF_PATH=virtual-nomem-v1' in probe
    assert "'vef_path_global_dmm_idle_verified':False" in probe
    assert 'VEF_NOMEM_PROFILE_BOUND' in (native/'check-natural-gtk-input.py').read_text()
    clean={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','A7C2_','QEMU_','SONY_'))}
    result=subprocess.run(['python3',str(native/'qemu-menu-probe.py'),'--initramfs','--observe'],
        env=dict(clean,MENU_VEF_PATH='virtual-nomem-v1'),capture_output=True,text=True,timeout=10)
    assert result.returncode==2 and 'VEF NoMem requires the guarded' in result.stderr
