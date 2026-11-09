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


def test_default_cold_environment_does_not_enable_usb():
    import original_cold_boot as cold
    assert 'PRODUCT_SONY_USB_DEVICE' not in cold.guest_environment({})
    assert cold.guest_environment({'A7C2_SONY_USB_DEVICE':device.PROFILE})['PRODUCT_SONY_USB_DEVICE']=='1'
    text=(cold.SOURCE/'insmod.sh').read_text()
    assert text.index('PRODUCT_SONY_USB_DEVICE')<text.index('PRODUCT_COLD_USB_MODULE_IDENTITY_FAILED')
    assert 'usb_portMonitor|usbg_sen)' in text and 'usb_extcmd)' not in text
    with pytest.raises(ValueError):cold.guest_environment({'A7C2_USB_SENSER':'original-init2-v1'})
    assert cold.guest_environment({'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_SENSER':'original-init2-v1'})['PRODUCT_USB_SENSER']=='original-init2-v1'
    assert text.index('/simulation/usb-senser-mode prepare')<text.index('init2-observed ||')
