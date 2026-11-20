#!/usr/bin/env python3
"""Actual paired GPIO MMIO/qtest on isolated QEMU devices, not original AP code."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import struct
import subprocess
import runpy
import time

PROFILE='virtual-ap-cp-gpio-lines-v1'
RETAINED=[]


class QtestTransportError(ConnectionError):
    """QMP/qtest transport is invalid or desynchronized; stop the whole batch."""


def require(value,message):
    if not value:raise ValueError(message)


def contract(binary,require_peripherals=False):
    binary=Path(binary).resolve(strict=True)
    proof_path=binary.parent/'cp-notify-build.json'
    proof=json.loads(proof_path.read_text())
    stage_path=binary.parent.parent/'cp-notify-stage.json'
    require(proof.get('profile')==PROFILE and proof.get('binary_sha256')==hashlib.sha256(binary.read_bytes()).hexdigest(),'Notification binary identity differs')
    require(proof.get('stage_sha256')==hashlib.sha256(stage_path.read_bytes()).hexdigest(),'Notification stage identity differs')
    stage=json.loads(stage_path.read_text());require(stage.get('profile')==PROFILE and stage.get('default_off') is True,'Notification stage admission differs')
    outputs={**stage['inherited_sources'],**stage['outputs']}
    child_digest=proof.get('peripherals_stage_sha256')
    if require_peripherals:require(bool(child_digest),'Peripheral build stage missing')
    if child_digest:
        child_path=stage_path.parent/'cp-peripherals-stage.json'
        require(hashlib.sha256(child_path.read_bytes()).hexdigest()==child_digest,'Peripheral stage identity differs')
        child=json.loads(child_path.read_text())
        recipe=runpy.run_path(str(Path(__file__).with_name('stage-peripherals.py')))
        require(child.get('schema')==recipe['SCHEMA'] and child.get('profile')==recipe['PROFILE'] and child.get('default_off') is True,'Peripheral stage admission differs')
        require(child.get('parent_stage_sha256')==proof['stage_sha256'] and proof['stage_sha256'] in recipe['PARENT_SHAS'],'Peripheral parent identity differs')
        require(child.get('base_sha256')==recipe['BASES'],'Peripheral input recipe differs')
        expected_inherited={name:digest for name,digest in {**outputs,**recipe['UPSTREAM']}.items() if name not in recipe['BASES']}
        recipe['validate_receipt'](child,expected_inherited)
        for name,digest in child['base_sha256'].items():
            if name in outputs:require(outputs[name]==digest,'Peripheral override not based on accepted parent')
        outputs.update(child['inherited_sources']);outputs.update(child['outputs'])
    for name,digest in outputs.items():
        path=stage_path.parent/name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and not path.is_symlink(),'Unsafe notification source path')
        require(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Notification source identity differs: '+name)
    return proof


class Endpoint:
    def __init__(self,binary,out,side):
        self.side=side;self.out=out;self.process=None;self.qmp=None;self.qt=None;self.qmp_socket=None;self.qt_socket=None
        self.records=[];self.counter=0;self._shutdown=None;self.log=(out/(side+'.stderr')).open('xb')
        peer='socket,id=notify-peer,path=notify.sock'+(',server=on,wait=off' if side=='ap' else ',server=off')
        machine='virt,gic-version=2' if side=='ap' else 'none'
        command=[str(binary),'-M',machine,'-cpu','cortex-a53','-m','64M','-S','-display','none','-nodefaults','-nic','none',
                 '-qmp','unix:'+side+'-qmp.sock,server=on,wait=off','-qtest','unix:'+side+'-qt.sock,server=on,wait=off','-chardev',peer]
        self.records.append(dict(command=command,side=side))
        env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_CP_','QEMU_SONY_','QEMU_AP_CP_'))}
        env.update(QEMU_AP_CP_GPIO_LINES=PROFILE,QEMU_AP_CP_GPIO_SIDE=side)
        self.process=subprocess.Popen(command,cwd=out,env=env,stdin=subprocess.DEVNULL,stdout=self.log,stderr=self.log)
        try:
            self.qmp_socket=self.connect(side+'-qmp.sock');self.qmp=self.qmp_socket.makefile('rwb',buffering=0)
            require('QMP' in self.receive(),'QMP greeting missing')
            self.command('qmp_capabilities')
            self.qt_socket=self.connect(side+'-qt.sock');self.qt=self.qt_socket.makefile('rwb',buffering=0)
        except BaseException:
            try:self.close()
            except BaseException:
                if self.process is not None and self not in RETAINED:RETAINED.append(self)
            raise

    def connect(self,name):
        connection=socket.socket(socket.AF_UNIX);connection.settimeout(5)
        deadline=time.monotonic()+5
        while True:
            try:connection.connect(name);return connection
            except (FileNotFoundError,ConnectionRefusedError):
                if self.process.poll() is not None or time.monotonic()>deadline:connection.close();raise RuntimeError('Owned GPIO QEMU startup failed')
                time.sleep(.01)

    def receive(self):
        raw=self.qmp.readline(16385)
        if not raw or len(raw)>16384 or not raw.endswith(b'\n'):
            raise QtestTransportError('Bounded QMP receive failed')
        try:
            value=json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise QtestTransportError('Malformed QMP response') from error
        if type(value) is not dict:
            raise QtestTransportError('QMP response is not an object')
        self.records.append(dict(qmp=value));return value

    def command(self,name):
        require(name in ('qmp_capabilities','query-status','system_reset','quit'),'Unexpected test QMP mutation')
        self.counter+=1;identity=self.counter
        self.qmp.write((json.dumps(dict(execute=name,id=identity))+'\n').encode())
        for _ in range(64):
            value=self.receive()
            if 'event' in value:continue
            if value.get('id')!=identity or 'return' not in value or 'error' in value:
                raise QtestTransportError('QMP command did not succeed')
            return value['return']
        raise QtestTransportError('QMP reply exceeded event budget')

    def qtest(self,command):
        self.qt.write((command+'\n').encode());raw=self.qt.readline(1025)
        if (len(raw)>1024 or not raw.endswith(b'\n') or
                not (raw == b'OK\n' or raw.startswith(b'OK '))):
            raise QtestTransportError('qtest failed: '+repr(raw))
        try:
            reply=raw.decode('ascii').strip()
        except UnicodeDecodeError as error:
            raise QtestTransportError('Non-ASCII qtest response') from error
        self.records.append(dict(qtest=command,reply=reply))
        return reply.split()[1:]

    def read(self,address):
        values=self.qtest('readl '+hex(address))
        if (len(values)!=1 or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}',values[0]) or
                int(values[0],16)>0xffffffff):
            raise QtestTransportError('Malformed qtest readl response: '+repr(values))
        return int(values[0],16)
    def write(self,address,value):self.qtest('writel '+hex(address)+' '+hex(value))

    def close(self):
        if self.process is None:return self._shutdown
        result=dict(self._shutdown or {},pid=self.process.pid,signals_sent=[])
        result.pop('error',None)
        error=None
        try:
            if self.process.poll() is None:
                require(self.qmp is not None,'QMP missing; owned process retained')
                self.command('quit');result['qmp_quit_confirmed']=True
            self.process.wait(timeout=10)
            result['returncode']=self.process.returncode
            require(result.get('qmp_quit_confirmed') and self.process.returncode==0,'GPIO QEMU did not exit normally')
        except BaseException as caught:
            error=caught
        result['alive']=self.process.poll() is None
        result['retained']=result['alive']
        if error is not None:result['error']=repr(error)
        self._shutdown=result
        path=self.out/(self.side+'-owner.json')
        if path.exists():path=self.out/(self.side+'-owner-retry-'+str(time.time_ns())+'.json')
        raw=(json.dumps(dict(shutdown=result,records=self.records),indent=2)+'\n').encode()
        try:
            with path.open('xb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            require(path.read_bytes()==raw,'GPIO owner receipt readback differs')
        except BaseException:
            if result['alive'] and self not in RETAINED:RETAINED.append(self)
            raise
        if result['alive']:
            if self not in RETAINED:RETAINED.append(self)
            raise RuntimeError('GPIO QEMU owner retained: '+repr(error)) from error
        for stream in (self.qt,self.qmp,self.qt_socket,self.qmp_socket,self.log):
            if stream is not None:stream.close()
        self.qt=self.qmp=self.qt_socket=self.qt_socket=self.log=None
        self.process=None
        if self in RETAINED:RETAINED.remove(self)
        if error is not None:raise RuntimeError('GPIO QEMU exited without normal quit: '+repr(error)) from error
        return result


def wait_log(endpoint,text,start=0):
    deadline=time.monotonic()+5
    while text not in (endpoint.out/(endpoint.side+'.stderr')).read_text()[start:]:
        require(time.monotonic()<deadline,'GPIO device event missing: '+text)
        endpoint.command('query-status');time.sleep(.01)


def frame_negative(binary,out):
    out.mkdir();os.chdir(out)
    endpoint=Endpoint(binary,out,'ap');client=None
    cases=[('sequence-gap',0x31475043,2,3,1),('wrong-side',0x31475041,1,3,1),
           ('unknown-mask',0x31475043,1,4,0),('undriven-level',0x31475043,1,1,2)]
    try:
        for name,magic,sequence,known,levels in cases:
            client=socket.socket(socket.AF_UNIX);client.settimeout(5);client.connect('notify.sock')
            raw=b''
            while len(raw)<16:
                chunk=client.recv(16-len(raw));require(chunk,'Initial output snapshot disconnected');raw+=chunk
            require(struct.unpack('<4I',raw)==(0x31475041,0,3,0),'AP snapshot did not describe actual reset output')
            frame=struct.pack('<4I',0x31475043,0,3,1)
            start=len((out/'ap.stderr').read_text())
            client.sendall(frame[:3]);endpoint.read(0xf102e010)
            wait_log(endpoint,'op=read port=17 offset=0x10 value=0x0 result=-1',start)
            client.sendall(frame[3:]);wait_log(endpoint,'op=receive port=17 offset=0x3 value=0x1 result=0',start)
            require(endpoint.read(0xf102e010)==16,'Fragmented peer snapshot was not consumed')
            start=len((out/'ap.stderr').read_text())
            client.sendall(struct.pack('<4I',magic,sequence,known,levels))
            wait_log(endpoint,'op=invalid-peer-frame',start)
            endpoint.read(0xf102e010)
            wait_log(endpoint,'op=read port=17 offset=0x10 value=0x0 result=-1',start)
            start=len((out/'ap.stderr').read_text())
            client.close();client=None
            wait_log(endpoint,'op=disconnected',start)
        return dict(fragmented_frame_consumed=True,rejected=[case[0] for case in cases],stale_input_rejected=True)
    finally:
        if client is not None:client.close()
        endpoint.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();binary=args.binary.resolve(strict=True);proof=contract(binary)
    out=args.out.resolve();out.mkdir();os.chmod(out,0o700)
    # Linux Unix-socket names are bounded even when the evidence directory is long.
    os.chdir(out);out=Path.cwd()
    ap=cp=None;result=dict(profile=PROFILE,binary_sha256=proof['binary_sha256'],passed=False,
        physical_compatible=False,ap_gpio_irq_verified=False,cp_irq_supported=False,original_ap_consumption_verified=False,
        original_cp_consumption_verified=False,full_boot_verified=False,capture_verified=False)
    try:
        ap=Endpoint(binary,out,'ap');cp=Endpoint(binary,out,'cp')
        wait_log(cp,'op=receive port=17 offset=0x3 value=0x0 result=0')
        wait_log(ap,'op=receive port=17 offset=0x3 value=0x0 result=0')
        require(ap.read(0xf102f000)==0xb41 and cp.read(0xf102f000)==15,'Original REG-derived direction state differs')
        require(ap.read(0xf102e010)==0 and cp.read(0xf102e010)==0,'Paired initial outputs were not consumed')
        ap.write(0x08000000,1)
        ap.write(0x08000108,0x18000000)
        ap.write(0x08000c14,(1<<25)|(1<<23))
        require(ap.read(0x08000208)&0x18000000==0,'Initial GPIO IRQ is not idle')
        ap.write(0xf102f044,0x200)
        wait_log(cp,'op=receive port=17 offset=0x3 value=0x1 result=0')
        require(cp.read(0xf102e010)==4,'AP output SET did not reach CP input')
        ap.write(0xf102f048,0x200)
        wait_log(cp,'op=receive port=17 offset=0x3 value=0x0 result=0')
        deadline=time.monotonic()+5
        while cp.read(0xf102e010)!=0:
            require(time.monotonic()<deadline,'AP output CLR did not reach CP');time.sleep(.01)
        cp.write(0xf102f044,8)
        wait_log(ap,'op=receive port=17 offset=0x3 value=0x1 result=0')
        require(ap.read(0xf102e010)==16,'CP output SET did not reach AP input')
        require(ap.read(0x08000208)&0x10000000,'GPIO17/4 did not reach actual GIC INTID92')
        cp.write(0xf102f044,4)
        wait_log(ap,'op=receive port=17 offset=0x3 value=0x3 result=0')
        require(ap.read(0xf102e010)==24,'CP channel1 output did not reach AP input bit3')
        require(ap.read(0x08000208)&0x18000000==0x18000000,'GPIO17/3 did not reach actual GIC INTID91')
        result['ap_gpio_irq_verified']=True
        cp.command('system_reset')
        require(cp.read(0xf102f040)==2,'Local reset did not restore output latch')
        require(cp.read(0xf102e010)==0,'Local reset lost valid external input')
        result.update(ap_set_clr_to_cp=True,cp_both_outputs_to_ap=True,local_reset_keeps_external_input=True)
        ap.close();ap=None
        wait_log(cp,'op=disconnected')
        cp.read(0xf102e010)  # qtest itself discards MemTxResult; use device error evidence below.
        wait_log(cp,'op=read port=17 offset=0x10 value=0x0 result=-1')
        result['disconnect_rejects_input']=True
        cp.close();cp=None
        result['frame_guards']=frame_negative(binary,out/'frame-negative')
        result['passed']=True
    except BaseException as error:
        result['error']=repr(error);raise
    finally:
        errors=[]
        for owner in (cp,ap):
            if owner is not None:
                try:owner.close()
                except BaseException as error:errors.append(repr(error))
        result['shutdown_errors']=errors
        if errors:result['passed']=False
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        if errors:raise RuntimeError('GPIO owner cleanup failed: '+repr(errors))
    print('GPIO_PAIRED_QEMU_PASS',out)


if __name__=='__main__':main()
