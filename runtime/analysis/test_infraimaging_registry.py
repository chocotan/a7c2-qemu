"""Independent constructor-cold InfraImaging Get owner; no Connect/capture claim."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess
import pytest

HERE=Path(__file__).resolve().parent

@pytest.mark.parametrize('owner',['infraimaging','infrabb'])
def test_owned_full_key_registry(tmp_path,owner):
    binary=tmp_path/owner
    built=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-g','-pthread',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie','-I',str(HERE),
        str(HERE/'infrabb-registry.c'),str(HERE/'device-models/pin-registry-core.c'),
        str(HERE/f'test-{owner}-registry.c'),'-o',str(binary)],capture_output=True,text=True,timeout=25)
    assert built.returncode==0,built.stdout+built.stderr
    checked=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
    assert checked.returncode==0,checked.stdout+checked.stderr
    assert ('INFRAIMAGING_SIX_FULL_KEYS_DYNAMIC_CALLERS_COLD_GET_ONLY_PASS' if owner=='infraimaging'
            else 'INFRABB_21_FULL_KEYS_OWN_REPLY_SID_GET_ONLY_PASS') in checked.stdout

def test_pinned_public_constructor_attributes_and_state_getter():
    public=HERE/'menu-root/cp/cpapp-b.bin'
    if not public.is_file():pytest.skip('pinned public ALLLANG CP image required for source-byte test')
    raw=public.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    assert [struct.unpack_from('<4I',raw,0x1001ee4+16*i) for i in range(6)]==[
        (0,2,0,0x90050004),(0,2,1,0x90050004),(0,2,2,0x90050004),
        (0,2,3,0x90050004),(3,2,0,0x90050004),(8,2,0,0x90050004)]
    assert struct.unpack_from('<6I',raw,0x1001f44)==tuple(0x1a3a428+0x38*i for i in range(6))
    assert raw[0x5843a4:0x5843aa].hex()=='806a08607047'
    assert raw[0x58359e:0x5835a6].hex()=='01214260ff228162'

def test_runtime_trace_is_console_mirrored():
    observer=(HERE/'menu-observe.c').read_text()
    mirrored=observer.split('mirrored[]',1)[1].split('};',1)[0]
    assert '"FULL_INFRAIMAGING_"' in mirrored
