#!/usr/bin/env python3
"""Run actual qtest DMA against an ordinary isolated raw file, then reopen QEMU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

BASE=0x0b000000
RAM=0x40000000


class QTest:
    def __init__(self, binary, disk, geometry, out, label):
        self.temp=tempfile.TemporaryDirectory(prefix='a7pf-qt-')
        self.log=(out/(label+'.log')).open('x')
        self.transcript=[]
        short=Path(self.temp.name)
        command=[str(binary),'-machine','virt,gic-version=2','-cpu','cortex-a53',
                 '-accel','tcg','-m','64M','-nodefaults','-display','none','-nic','none','-S',
                 '-bios',str(disk),'-dtb',str(geometry),
                 '-qtest','unix:'+str(short/'test')+',server=on,wait=off',
                 '-qmp','unix:'+str(short/'qmp')+',server=on,wait=off']
        env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','MENU_','SONY_'))}
        self.process=subprocess.Popen(command,stdout=self.log,stderr=subprocess.STDOUT,env=env)
        (out/(label+'-owner.json')).write_text(json.dumps(dict(pid=self.process.pid,command=command),indent=2)+'\n')
        self.socket=self.connect(short/'test')
        self.file=self.socket.makefile('rwb',buffering=0)
        self.qmp=self.connect(short/'qmp')
        self.qmpfile=self.qmp.makefile('rwb',buffering=0)
        greeting=json.loads(self.qmpfile.readline());assert 'QMP' in greeting
        self.qmpcommand('qmp_capabilities')

    def connect(self,path):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(5)
            try:s.connect(str(path));return s
            except (FileNotFoundError,ConnectionRefusedError):
                s.close()
                if self.process.poll() is not None:
                    raise RuntimeError('QEMU exited: '+str(self.process.returncode))
                time.sleep(.02)
        raise TimeoutError('QEMU socket not ready')

    def qmpcommand(self,name):
        self.qmpfile.write((json.dumps({'execute':name})+'\n').encode())
        while True:
            value=json.loads(self.qmpfile.readline())
            if 'return' in value:return value
            if 'error' in value:raise RuntimeError(value)

    def cmd(self,text):
        self.file.write((text+'\n').encode())
        while True:
            result=self.file.readline().decode().strip()
            if result.startswith('IRQ '):continue
            assert result.startswith('OK'),(text,result)
            self.transcript.append([text[:100],result[:100]])
            return result[2:].strip()

    def reg(self,off,value=None):
        if value is None:return int(self.cmd(f'readl {BASE+off:#x}'),0)
        self.cmd(f'writel {BASE+off:#x} {value:#x}')

    def io(self,op,selector=0,sector=0,count=1,address=RAM,error=0):
        self.reg(0x10,selector);self.reg(0x18,sector&0xffffffff);self.reg(0x1c,sector>>32)
        self.reg(0x20,count);self.reg(0x24,address&0xffffffff);self.reg(0x28,address>>32);self.reg(0x14,op)
        assert self.reg(0x2c)==(2 if error else 1)
        assert self.reg(0x34)==error
        assert self.reg(0x30)==(0 if error or op in (1,4) else count*512)

    def write_ram(self,data):self.cmd(f'write {RAM:#x} {len(data):#x} 0x'+data.hex())
    def read_ram(self,count):return bytes.fromhex(self.cmd(f'read {RAM:#x} {count:#x}')[2:])

    def close(self,out,label):
        self.qmpcommand('quit')
        self.process.wait(timeout=10)
        assert self.process.returncode==0
        self.file.close();self.socket.close();self.qmpfile.close();self.qmp.close();self.log.close();self.temp.cleanup()
        (out/(label+'-transcript.json')).write_text(json.dumps(self.transcript,indent=2)+'\n')


def test(binary,out):
    out.mkdir(parents=True,exist_ok=False)
    disk=out/'disk.raw';geometry=out/'geometry.bin'
    user=1048576
    with disk.open('xb') as f:f.truncate(user+8388608)
    disk.chmod(0o600)
    rows=[(1,65536,131072),(7,196608,131072),(31,user,4194304),(32,user+4194304,4194304)]
    geometry.write_bytes(struct.pack('<8sIIQ',b'A7PFGE01',1,len(rows),user)+
                         b''.join(struct.pack('<IIQQ',n,0,off,size) for n,off,size in rows))
    geometry.chmod(0o600)
    payload=hashlib.sha256(b'persistent flash genuine qtest DMA').digest()*16
    bootpayload=hashlib.sha256(b'boot area separate address space').digest()*16
    first=QTest(binary,disk,geometry,out,'first')
    try:
        assert first.reg(0)==0x46503741 and first.reg(4)==1
        assert first.reg(0xc)==2 and first.reg(0x48)==2
        first.io(1);assert first.reg(0x38)==2048
        first.io(1,7);assert first.reg(0x38)==256 and first.reg(0x40)==384
        first.write_ram(payload);first.io(3,7,3);first.io(4)
        with disk.open('rb') as f:f.seek(196608+3*512);assert f.read(512)==payload
        first.write_ram(bootpayload);first.io(3,31,2)
        first.io(2,7,256,error=22)
        first.io(3,7,0,address=0x09000000,error=14)
        first.io(2,0,2048,error=22)
        first.io(1,9,error=19)
        first.io(3,7,0,count=257,error=22)
        first.io(2,7,0,address=0xfffffffffffffe00,error=14)
    finally:first.close(out,'first')
    second=QTest(binary,disk,geometry,out,'second')
    try:
        second.write_ram(bytes(512));second.io(2,0,384+3);assert second.read_ram(512)==payload
        second.write_ram(bytes(512));second.io(2,7,3);assert second.read_ram(512)==payload
        second.io(2,31,2);assert second.read_ram(512)==bootpayload
        second.io(2,32,2);assert second.read_ram(512)==bytes(512)
        with disk.open('r+b') as f:f.truncate(user)
        second.io(2,7,3,error=116)
        with disk.open('r+b') as f:f.truncate(user+8388608)
    finally:second.close(out,'second')
    result=dict(status='passed',processes=2,normal_qmp_quit_returncodes=[0,0],
                real_qemu_dma_to_single_file=True,reopen_next_process_readback=True,
                partition_whole_alias_verified=True,independent_boot_views=True,
                invalid_dma_bounds_and_truncated_backend_rejected=True,
                payload_sha256=hashlib.sha256(payload).hexdigest(),disk_sha256=hashlib.sha256(disk.read_bytes()).hexdigest(),
                physical_compatibility=False,guest_module_loaded=False,original_ap_boot_verified=False)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();test(a.qemu.resolve(),a.output.resolve())
