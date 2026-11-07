#!/usr/bin/env python3
"""Reuse flash qtest DMA/restart with the production FD board plus USB checks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
FLASH=runpy.run_path(str(HERE/'test-qemu.py'))
USB_BASE=0xf10c0000
CAPABILITIES={0:0x01000040,4:0,0xc120:0x5533290a,0xc140:0x40404000,
              0xc144:1<<15,0xc14c:(16<<18)|(32<<12)|4,0xc15c:0x04000400}


class ProductionQTest(FLASH['QTest']):
    def __init__(self,binary,disk,geometry,out,label,*,controller='sony-device'):
        self.temp=tempfile.TemporaryDirectory(prefix='a7pf-usb-qt-')
        self.log=(out/(label+'.log')).open('x')
        self.transcript=[]
        short=Path(self.temp.name)
        args=[str(binary),'-machine','virt,gic-version=2','-cpu','cortex-a53',
              '-accel','tcg','-m','64M','-nodefaults','-display','none','-nic','none','-S',
              '-qtest','unix:'+str(short/'test')+',server=on,wait=off',
              '-qmp','unix:'+str(short/'qmp')+',server=on,wait=off']
        env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','MENU_','SONY_'))}
        fd=os.open(disk,os.O_RDWR|os.O_NOFOLLOW)
        info=os.fstat(fd)
        env.update(QEMU_A7PF_PROFILE='persistent-flash-cold-v1',QEMU_A7PF_FD=str(fd),
                   QEMU_A7PF_DEV=str(info.st_dev),QEMU_A7PF_INO=str(info.st_ino),QEMU_SONY_TIMERS='1')
        if controller=='sony-device':env['QEMU_SONY_USB_DEVICE']='1'
        elif controller=='upstream-host':env['QEMU_SONY_USB_DWC3']='1'
        elif controller!='off':raise ValueError('Unknown test controller')
        command=['bwrap','--unshare-all','--die-with-parent',
                 '--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64',
                 '--ro-bind',str(binary),str(binary),'--dev','/dev','--proc','/proc','--tmpfs','/tmp',
                 '--bind',str(short),str(short),'--dir','/instance',
                 '--ro-bind',str(geometry),'/instance/persistent-geometry.bin']
        # Older bubblewrap versions preserve Popen pass_fds without this option.
        if '--preserve-fds' in subprocess.run(['bwrap','--help'],capture_output=True,text=True,check=True).stdout:
            command+=['--preserve-fds',str(fd-2)]
        command+=args
        try:self.process=subprocess.Popen(command,stdout=self.log,stderr=subprocess.STDOUT,env=env,pass_fds=(fd,))
        finally:os.close(fd)
        self.owner_path=out/(label+'-owner.json')
        self.owner=dict(pid=self.process.pid,controller=controller,synthetic_backend=True,
                        geometry_sha256=hashlib.sha256(geometry.read_bytes()).hexdigest(),
                        signals_sent=[],guest_started=False)
        self.owner_path.write_text(json.dumps(self.owner,indent=2)+'\n')
        try:
            self.qmp=self.connect(short/'qmp')
            self.qmpfile=self.qmp.makefile('rwb',buffering=0)
            assert 'QMP' in json.loads(self.qmpfile.readline())
            self.qmpcommand('qmp_capabilities')
            self.socket=self.connect(short/'test')
            self.file=self.socket.makefile('rwb',buffering=0)
            types={row['name'] for row in self.query('qom-list-types')}
            required={'sony-persistent-flash','sony-dwc3-gadget','usb_dwc3','sony-hwtimer','sony-spacc-stub'}
            assert required<=types,required-types
            tree=self.query('human-monitor-command',{'command-line':'info qtree'})
            assert 'sony-persistent-flash' in tree and 'sony-hwtimer' in tree and 'sony-spacc-stub' in tree
            assert ('sony-dwc3-gadget' in tree)==(controller=='sony-device')
            assert ('usb_dwc3' in tree)==(controller=='upstream-host')
            values={}
            if controller=='sony-device':
                for offset,expected in CAPABILITIES.items():
                    value=int(self.cmd(f'readl {USB_BASE+offset:#x}'),0)
                    assert value==expected,(offset,value,expected)
                    values[hex(offset)]=hex(value)
                for lane in range(4):
                    value=int(self.cmd(f'readb {USB_BASE+0xc120+lane:#x}'),0)
                    assert value==((CAPABILITIES[0xc120]>>(8*lane))&255)
                assert int(self.cmd(f'readl {USB_BASE+0xc704:#x}'),0)==0
            self.owner.update(required_qdev_types=sorted(required),capabilities=values,
                              controller_realized=True,guest_descriptor_ready=False,exported=False)
        except BaseException:
            self.owner['initialization_failed']=True
            self.owner_path.write_text(json.dumps(self.owner,indent=2)+'\n')
            if hasattr(self,'qmpfile'):self.qmpcommand('quit')
            self.process.wait(timeout=10)
            self.owner.update(returncode=self.process.returncode,owner_exited=True,
                              normal_qmp_quit=hasattr(self,'qmpfile'))
            self.owner_path.write_text(json.dumps(self.owner,indent=2)+'\n')
            raise

    def query(self,name,arguments=None):
        request={'execute':name}
        if arguments is not None:request['arguments']=arguments
        self.qmpfile.write((json.dumps(request)+'\n').encode())
        while True:
            value=json.loads(self.qmpfile.readline())
            if 'return' in value:return value['return']
            if 'error' in value:raise RuntimeError(value)

    def close(self,out,label):
        super().close(out,label)
        self.owner.update(returncode=self.process.returncode,normal_qmp_quit=True,owner_exited=True)
        self.owner_path.write_text(json.dumps(self.owner,indent=2)+'\n')


def test(binary,out):
    receipt=json.loads((binary.parent.parent/'qemu-result.json').read_text())
    assert receipt['status']=='compiled' and receipt['board_profile']=='persistent-flash-cold-v1'
    assert receipt['test_fixture_only'] is False
    assert receipt['usb_device_profile']=='virtual-functional-sony-usb-device-v1'
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==receipt['qemu_binary_sha256']
    for name,want in receipt['usb_source_sha256'].items():
        assert hashlib.sha256((binary.parent.parent/'qemu-11.1.2'/name).read_bytes()).hexdigest()==want
    FLASH['test'].__globals__['QTest']=ProductionQTest
    FLASH['test'](binary,out)
    result=json.loads((out/'result.json').read_text())
    for controller in ('off','upstream-host'):
        probe=ProductionQTest(binary,out/'disk.raw',out/'geometry.bin',out,controller,controller=controller)
        try:assert probe.reg(0)==0x46503741
        finally:probe.close(out,controller)
    owners=[json.loads((out/(label+'-owner.json')).read_text()) for label in ('first','second','off','upstream-host')]
    assert all(row['returncode']==0 and row['signals_sent']==[] and row['owner_exited'] for row in owners)
    result.update(schema='a7c2.persistent-usb-qtest.v1',qemu_binary_sha256=receipt['qemu_binary_sha256'],
        processes=len(owners),normal_qmp_quit_returncodes=[row['returncode'] for row in owners],
        usb_device_realized_on_same_production_board=True,usb_capabilities_readback=owners[0]['capabilities'],
        capability_byte_reads_verified=True,controller_off_and_upstream_host_retained=True,
        inherited_fd_production_path=True,geometry_metadata_only=True,synthetic_backend_only=True,
        original_guest_driver_verified=False,guest_descriptor_ready=False,host_enumerated=False,
        jiritsu_authenticated=False,exported=False,guest_started=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    test(args.qemu.resolve(strict=True),args.output.resolve())
