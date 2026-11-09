"""Product USB device integration guards; synthetic fixtures never prove enumeration."""
import importlib.util
import json
from pathlib import Path
import pytest
import sony_usb_device as device


def test_explicit_profile_and_candidate_scope_fail_closed(tmp_path):
    assert device.selected({}) is False
    assert device.selected({'A7C2_SONY_USB_DEVICE':device.PROFILE})
    for value in ('1','',True,'sony-device'):
        with pytest.raises(ValueError):device.selected({'A7C2_SONY_USB_DEVICE':value})
    with pytest.raises(ValueError,match='product build'):device.candidate(tmp_path/'receipt.json')


def test_stage_preserves_board_and_requires_fresh_source(tmp_path):
    path=device.PRODUCT/'source/usb-device/stage.py'
    spec=importlib.util.spec_from_file_location('usb_stage',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    board=tmp_path/'hw/arm/virt.c';board.parent.mkdir(parents=True)
    board.write_text('#include "hw/arm/virt.h"\nstatic void board(void) {\n    create_msi_controller(vms);\n}\n')
    meson=tmp_path/'hw/usb/meson.build';meson.parent.mkdir();meson.write_text('# existing USB sources\n')
    before=board.read_text();proof=module.stage(tmp_path)
    assert proof['source_before']['hw/arm/virt.c']!=proof['source_after']['hw/arm/virt.c']
    assert board.read_text().count('create_msi_controller(vms);')==1
    assert '#include "hw/arm/virt.h"' in before and 'QEMU_SONY_USB_DEVICE' in board.read_text()
    assert (tmp_path/'hw/usb/sony-dwc3.c').read_text().startswith('#define SONY_DWC3_QEMU 1\n')
    assert proof['firmware_descriptors_in_model'] is False and proof['host_enumerated'] is False
    snapshot={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match='already staged'):module.stage(tmp_path)
    assert all(Path(name).read_bytes()==data for name,data in snapshot.items())


def test_usb_context_and_restore_are_private_and_checked(tmp_path,monkeypatch):
    import usb_ui
    assert device.require_disconnected(tmp_path) is None
    (tmp_path/'usb-context.json').write_text('{}')
    monkeypatch.setattr(usb_ui,'action',lambda run,op:dict(phase='recovery_required',preload_recovery_required=True))
    with pytest.raises(RuntimeError,match='retain'):device.require_disconnected(tmp_path)
    monkeypatch.setattr(usb_ui,'action',lambda run,op:dict(phase='disconnected',preload_recovery_required=False,owned_port=None))
    assert device.require_disconnected(tmp_path)['phase']=='disconnected'


def test_phy_tuning_consumes_actual_writes_and_keeps_clock_and_address_guards(tmp_path):
    import subprocess
    text=(device.PRODUCT/'source/usb-device/sony-usb-platform.inc').read_text().split('/* Functional Sony USB clock/reset/PHY/GPIO;')[0]
    test=tmp_path/'power.c'
    test.write_text(text+'''\n#include <assert.h>
int main(void) {
 SonyUsbPower p;uint32_t value=0;
 sony_usb_power_init(&p);
 assert(sony_usb_power_write(&p,0xf1080000,4,0x700)==-EAGAIN);
 assert(!sony_usb_power_write(&p,0xf1388004,4,0xf000));
 assert(!sony_usb_power_write(&p,0xf1388304,4,0xf00));
 assert(!sony_usb_power_write(&p,0xf1388308,4,0x200));
 assert(!sony_usb_power_write(&p,0xf1080000,4,0x0a000700));
 assert(!sony_usb_power_read(&p,0xf1080000,4,&value)&&value==0x0a000700);
 assert(sony_usb_power_write(&p,0xf1080000,4,1)==-EOPNOTSUPP);
 assert(!sony_usb_power_write(&p,0xf1080004,4,0x67));
 assert(!sony_usb_power_read(&p,0xf1080004,4,&value)&&value==0x67);
 assert(!sony_usb_power_write(&p,0xf1080020,4,0));
 assert(!sony_usb_power_write(&p,0xf1080020,4,0));
 assert(!sony_usb_power_write(&p,0xf1080020,4,0x100000));
 assert(!sony_usb_power_write(&p,0xf1388308,4,0xf00));
 assert(sony_usb_sram_initialized(&p));
 assert(!sony_usb_power_write(&p,0xf10a470c,4,1));
 assert(!sony_usb_power_read(&p,0xf10a470c,4,&value)&&value==1);
 for(unsigned lane=0;lane<4;lane++) {
  uint32_t address=0xf10ac004+lane*0x400;
  assert(!sony_usb_power_write(&p,address,2,0x1234+lane));
  assert(!sony_usb_power_read(&p,address,2,&value)&&value==0x1234+lane);
 }
 assert(sony_usb_power_write(&p,0xf10ac004,2,0x10000)==-EOPNOTSUPP);
 assert(sony_usb_power_read(&p,0xf10ac006,2,&value)==-EOPNOTSUPP);
 assert(sony_usb_power_write(&p,0xf10a1234,4,0)==-EOPNOTSUPP);
 assert(!sony_usb_power_write(&p,0xf1388008,4,0x1000));
 assert(!sony_usb_sram_initialized(&p));
 assert(sony_usb_power_read(&p,0xf10ac004,2,&value)==-EAGAIN);
 return 0;
}
''')
    for flags,name in ((['-O2'],'strict'),(['-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer'],'sanitized')):
        binary=tmp_path/name
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',*flags,str(test),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)


def test_authentication_manifest_needs_no_archived_write_scripts(tmp_path):
    from usb_jiritsu import Sources
    vendor=tmp_path/'vendor'
    names=('pmca/usb/sony.py','pmca/usb/crypto.py','pmca/usb/constants.py','pmca/usb/driver/generic/__init__.py','pmca/usb/driver/generic/libusb.py')
    for name in names:
        path=vendor/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'# synthetic source identity only\n')
    sources=Sources(tmp_path/'absent-archived-tools',vendor)
    manifest=sources.manifest('authenticate')
    assert all('absent-archived-tools' not in name for name in manifest)
    assert str((vendor/names[0]).resolve()) in manifest
    with pytest.raises(FileNotFoundError):sources.manifest('version')


def test_real_isolated_auth_import_uses_prepared_crypto_without_research_scripts():
    import subprocess,sys
    path=device.ANALYSIS/'vendor/host-python/Cryptodome'
    if not path.is_dir():pytest.skip('optional prepared host Crypto dependency is absent')
    if not (device.ANALYSIS/'vendor/pmca-adamwuqwq/pmca/usb/sony.py').is_file():pytest.skip('optional PMCA dependency is absent')
    code='import sys;sys.path.insert(0,'+repr(str(device.ANALYSIS))+');import usb_jiritsu;from Cryptodome.Hash import SHA256;assert SHA256.new(b"abc").hexdigest()=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";s=usb_jiritsu.Sources();m=s.manifest("authenticate");s.load(m,"authenticate");assert "usb_service_probe" not in sys.modules'
    subprocess.run([sys.executable,'-I','-B','-c',code],check=True,capture_output=True)


@pytest.mark.parametrize('status,data,actual,accepted',[(0,b'',0,True),(-32,b'',0,False),(0,b'extra',0,False),(0,b'',1,False)])
def test_usbip_requires_actual_ep0_address_completion(status,data,actual,accepted):
    import asyncio,struct
    from types import SimpleNamespace
    from usb_control import usbip
    class Backend(usbip.Bridge):
        def __init__(self):self.submitted=[]
        async def begin(self,operation,payload=b'',**fields):
            self.submitted.append((operation,payload,fields));future=asyncio.get_running_loop().create_future()
            future.set_result((dict(status=status,actual_length=actual),data));return 7,future
    backend=Backend();device=SimpleNamespace(metadata={'devnum':6},devid=0x10006)
    async def check():
        if accepted:await backend.assign_address(device)
        else:
            with pytest.raises((usbip.Blocked,usbip.ProtocolError)):await backend.assign_address(device)
    asyncio.run(check())
    assert len(backend.submitted)==1
    operation,payload,fields=backend.submitted[0]
    assert operation=='submit' and payload==b'' and bytes.fromhex(fields['setup'])==struct.pack('<BBHHH',0,5,6,0,0)
    assert fields['endpoint']==0 and fields['direction']==0 and fields['transfer_length']==0


@pytest.mark.parametrize('before', ['absent', 'directory', 'symlink', 'foreign_mount'])
def test_senser_mountpoint_is_real_and_restores_only_its_empty_directory(tmp_path,before):
    import ast,subprocess
    tree=ast.parse(Path(device.__file__).read_text())
    text=next(node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and
              isinstance(node.value,str) and node.value.startswith('#!/bin/busybox sh\nset -e\nstate='))
    state=tmp_path/'state';setting=tmp_path/'setting';setting.mkdir();(setting/'sen').mkdir()
    mode=setting/'sen/smode';mode.write_bytes(b'ORIGINAL\n')
    target=tmp_path/'jiritsu';mounts=tmp_path/'mounts';mounts.write_text('')
    if before=='directory':target.mkdir();(target/'kept').write_bytes(b'original file')
    if before=='symlink':target.symlink_to(setting,target_is_directory=True)
    text=text.replace('/log/qemu/usb-senser-mode',str(state)).replace('/setting',str(setting)).replace('/tmp/jiritsu',str(target)).replace('/proc/mounts',str(mounts)).replace('/simulation/audit','true')
    text=text.replace('/bin/busybox sync','true').replace('/bin/busybox ','')
    script=tmp_path/'mode.sh';script.write_text(text)
    result=subprocess.run(['bash',str(script),'prepare'],capture_output=True)
    if before=='symlink':
        assert result.returncode==78 and mode.read_bytes()==b'ORIGINAL\n' and target.is_symlink()
        return
    assert result.returncode==0 and target.is_dir() and mode.read_bytes()==b'UU\n'
    if before=='foreign_mount':
        mounts.write_text('/dev/foreign '+str(target)+' vfat rw 0 0\n')
        result=subprocess.run(['bash',str(script),'restore'],capture_output=True)
        assert result.returncode==78 and target.is_dir() and mode.read_bytes()==b'UU\n'
        return
    for _ in range(2):
        result=subprocess.run(['bash',str(script),'restore'],capture_output=True)
        assert result.returncode==0 and mode.read_bytes()==b'ORIGINAL\n'
    if before=='absent':assert not target.exists()
    else:assert (target/'kept').read_bytes()==b'original file'


def test_usbif_initialize_wrapper_forwards_both_original_machine_arguments(tmp_path):
    import subprocess
    from elftools.elf.elffile import ELFFile
    import struct
    original=Path(__file__).parent/'menu-root/usr/lib/libInfraUsbCmn.so'
    if original.exists():
        with original.open('rb') as stream:
            elf=ELFFile(stream)
            for address,word in ((0x17db0,0xaa0003f6),(0x17dbc,0xaa0103f5),(0x17ea8,0xb4000435),(0x17eb8,0xaa1503e1),(0x17ebc,0xd2800f02),(0x17ec8,0x97ffd856)):
                segment=next(s for s in elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_vaddr']<=address<s['p_vaddr']+s['p_filesz'])
                stream.seek(segment['p_offset']+address-segment['p_vaddr'])
                assert struct.unpack('<I',stream.read(4))[0]==word
    source=Path(__file__).resolve().parents[2]/'source/usb-device/usb-start-observe.c'
    text=source.read_text();start=text.index('static uint32_t (*real_usbif_initialize)');end=text.index('\nstatic uint32_t (*real_openSvc)',start)
    test=tmp_path/'usbif-abi.c'
    test.write_text('''#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <assert.h>
static unsigned logs,blobs,calls; static uintptr_t expected_handle,expected_callbacks; static uint32_t reply;
static void emit(int error,const char *kind,const char *format,...){(void)error;assert(kind&&format);errno=999;logs++;}
static void blob(const char *kind,uintptr_t p,size_t n){assert(kind&&p==expected_callbacks&&n==120);errno=888;blobs++;}
static uint32_t original_call(uintptr_t handle,uintptr_t callbacks){assert(handle==expected_handle&&callbacks==expected_callbacks&&errno==27);calls++;errno=41;return reply;}
'''+text[start:end]+'''
int main(void){unsigned char table[120]={1,2,3};expected_handle=0x1234;expected_callbacks=(uintptr_t)table;real_usbif_initialize=original_call;errno=27;reply=0xabcdef01;assert(u_usbif_initialize(expected_handle,expected_callbacks)==reply);assert(errno==41&&table[0]==1&&table[1]==2&&table[2]==3&&calls==1&&blobs==1&&logs==2);expected_callbacks=0;errno=27;reply=0;assert(u_usbif_initialize(expected_handle,0)==0&&errno==41);assert(calls==2&&blobs==1&&logs==4);return 0;}
''')
    for flags,name in ((['-O2'],'strict'),(['-O1','-fsanitize=address,undefined'],'sanitized')):
        binary=tmp_path/name
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',*flags,str(test),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)


def test_callback_tree_observer_is_bounded_and_never_corrects_original_pointer(tmp_path):
    import subprocess
    source=Path(__file__).resolve().parents[2]/'source/usb-device/usb-start-observe.c'
    text=source.read_text();start=text.index('static void service_callbacks(');end=text.index('\n}',start)+2;function=text[start:end]
    test=tmp_path/'callback-observe.c'
    test.write_text('''#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
static uintptr_t root_value,ops_value,event_value;
static unsigned reads,root_blobs,ops_blobs,emitted;
static uintptr_t pointer(uintptr_t p){reads++; if(p==0x10d0)return root_value; if(p==0x2090)return ops_value; assert(p==0x3048); return event_value;}
static void emit(int error,const char *kind,const char *format,...){assert(!error&&strcmp(kind,"CALLBACK_TREE")==0&&format);emitted++;}
static void blob(const char *kind,uintptr_t p,size_t n){if(!strcmp(kind,"CALLBACK_ROOT")){assert(p==0x2000&&n==160);root_blobs++;}else{assert(!strcmp(kind,"CALLBACK_OPS")&&p==0x3000&&n==96);ops_blobs++;}}
'''+function+'''
int main(void){service_callbacks(0x1000,"empty");assert(reads==1&&emitted==1&&!root_blobs&&!ops_blobs);root_value=0x2000;service_callbacks(0x1000,"root-only");assert(reads==3&&root_blobs==1&&!ops_blobs);ops_value=0x3000;event_value=0x4001;service_callbacks(0x1000,"unaligned");assert(event_value==0x4001&&reads==6&&root_blobs==2&&ops_blobs==1);event_value=0x4000;service_callbacks(0x1000,"valid");assert(event_value==0x4000&&reads==9&&emitted==4&&root_blobs==3&&ops_blobs==2);return 0;}
''')
    for flags,name in ((['-O2'],'strict'),(['-O1','-fsanitize=address,undefined'],'sanitized')):
        binary=tmp_path/name
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',*flags,str(test),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True)


def test_default_cold_environment_does_not_enable_usb():
    import original_cold_boot as cold
    assert 'PRODUCT_SONY_USB_DEVICE' not in cold.guest_environment({})
    assert cold.guest_environment({'A7C2_SONY_USB_DEVICE':device.PROFILE})['PRODUCT_SONY_USB_DEVICE']=='1'
    text=(cold.SOURCE/'insmod.sh').read_text()
    assert text.index('PRODUCT_SONY_USB_DEVICE')<text.index('PRODUCT_COLD_USB_MODULE_IDENTITY_FAILED')
    assert 'usb_portMonitor|usbg_sen|usb_extcmd)' in text
    assert 'usb_extcmd) expected=63554be9f7bf7cbba3d9de16ce3d8675e3b60a323be1fa92839fa9eec0caa8c2;;' in text
    assert 'PRODUCT_COLD_USB_MODULE_IDENTITY_FAILED' in text
    with pytest.raises(ValueError):cold.guest_environment({'A7C2_USB_SENSER':'original-init2-v1'})
    assert cold.guest_environment({'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_SENSER':'original-init2-v1'})['PRODUCT_USB_SENSER']=='original-init2-v1'
    assert text.index('/simulation/usb-senser-mode prepare')<text.index('init2-observed ||')


def test_bridge_strips_host_sg_mapping_without_accepting_unknown_semantics(tmp_path):
    import subprocess
    text=(device.PRODUCT/'source/usb-device/sony-dwc3-bridge.c').read_text()
    start=text.index('static int bridge_semantic_flags(')
    function=text[start:text.index('\n}\n',start)+3]
    source=tmp_path/'flags.c'
    source.write_text('#include <assert.h>\n#include <errno.h>\n#include <stdint.h>\n'+function+'''
int main(void) {
 uint32_t semantic=99;
 assert(!bridge_semantic_flags(0x40000,&semantic)&&semantic==0);
 assert(!bridge_semantic_flags(0x40001,&semantic)&&semantic==1);
 assert(!bridge_semantic_flags(0x40040,&semantic)&&semantic==0x40);
 assert(bridge_semantic_flags(0x40002,&semantic)==-EOPNOTSUPP&&semantic==2);
 assert(bridge_semantic_flags(0x1000000,&semantic)==-EOPNOTSUPP&&semantic==0x1000000);
 return 0;
}
''')
    binary=tmp_path/'flags'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',str(source),'-o',str(binary)],check=True,capture_output=True)
    subprocess.run([str(binary)],check=True,capture_output=True)
