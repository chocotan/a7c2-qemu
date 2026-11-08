#!/usr/bin/env python3
"""Bounded original-kernel component check; this does not boot the camera AP."""
from pathlib import Path
import argparse,fcntl,hashlib,json,os,secrets,socket,stat,struct,subprocess,time
ROOT=Path(__file__).resolve().parents[1];A=ROOT/'runtime/analysis'

def need(ok,message):
    if not ok:raise ValueError(message)

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def save(path,value):
    temporary=path.with_suffix('.new')
    with temporary.open('x') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)

def cpio(files):
    import sys
    sys.path.insert(0,str(A))
    from firmware_overlay import _write_header
    import io
    stream=io.BytesIO();inode=1
    for name,(mode,data) in sorted(files.items()):
        fields=[inode,mode,0,0,1,0,len(data),0,0,0,0,len(name)+1,0];_write_header(stream,fields,name);stream.write(data);stream.write(b'\0'*((-stream.tell())%4));inode+=1
    _write_header(stream,[0]*13,'TRAILER!!!');stream.write(b'\0'*((-stream.tell())%512));return stream.getvalue()

def identity(pid):
    fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
    return dict(pid=pid,starttime=fields[19],boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--qemu',type=Path,required=True);parser.add_argument('--module',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    qemu=args.qemu.resolve(strict=True);module=args.module.resolve(strict=True);out=args.output.absolute();need('..' not in out.parts and not any(p.is_symlink() for p in (*out.parents,out)),'Ordinary non-linked product output required');need(qemu.is_relative_to(ROOT) and module.is_relative_to(ROOT),'Product build inputs required');need(not out.exists() and out.is_relative_to(ROOT),'Fresh product-owned output required');out.mkdir(parents=True,mode=0o700)
    source=A/'menu-root';files={name:(stat.S_IFDIR|0o755,b'') for name in ('bin','lib','usr','usr/lib','usr/bin','proc','sys','dev','tmp','simulation')}
    files['bin/busybox']=(stat.S_IFREG|0o755,(source/'bin/busybox').read_bytes());files['bin/sh']=(stat.S_IFLNK|0o777,b'busybox')
    for parent in ('lib','usr/lib'):
        for path in (source/parent).iterdir():
            if not path.is_file() or (parent=='usr/lib' and path.name not in ('libcrypto.so.1.1','libcrypto.so.3','libssl.so.3')):continue
            real=path.resolve(strict=True);need(real.is_relative_to(source.resolve()),'Original library escaped product root');files[parent+'/'+path.name]=(stat.S_IFREG|0o755,real.read_bytes())
    files['usr/bin/openssl']=(stat.S_IFREG|0o755,(source/'usr/bin/openssl').read_bytes())
    payload=bytes(range(256))*4096;files['simulation/payload.bin']=(stat.S_IFREG|0o600,payload);files['simulation/sony_persistent_flash.ko']=(stat.S_IFREG|0o600,module.read_bytes())
    init=b'''#!/bin/sh
bb=/bin/busybox
fail() { echo PERSIST_COMPONENT_FAIL=$1; while :; do $bb sleep 60; done; }
$bb mount -t proc proc /proc || fail proc
$bb mount -t sysfs sysfs /sys || fail sys
$bb mount -t devtmpfs devtmpfs /dev || fail dev
exec </dev/console >/dev/console 2>&1
$bb grep -E '^(Uid|Gid):' /proc/1/status
$bb uname -r
$bb insmod /simulation/sony_persistent_flash.ko mmio_base=0x0b010000 || fail insmod
echo PERSIST_COMPONENT_WRITE_BEGIN
( $bb sleep 8; echo PERSIST_COMPONENT_STACKS_BEGIN; for p in /proc/[0-9]*; do echo PERSIST_COMPONENT_TASK=${p##*/}; $bb cat "$p/comm" "$p/stack" 2>/dev/null; done; echo PERSIST_COMPONENT_STACKS_END ) &
$bb dd if=/simulation/payload.bin of=/dev/pnflasha bs=131072 count=8 || fail write
echo PERSIST_COMPONENT_SYNC_BEGIN
$bb sync || fail sync
echo PERSIST_COMPONENT_READ_BEGIN
$bb dd if=/dev/pnflasha of=/simulation/readback.bin bs=131072 count=8 || fail read
echo PERSIST_COMPONENT_SMALL_IO_BEGIN
$bb dd if=/simulation/payload.bin of=/simulation/small-payload.bin bs=4096 count=16 || fail small-source
$bb dd if=/simulation/small-payload.bin of=/dev/pnflasha bs=4096 count=16 seek=512 || fail small-write
$bb sync || fail small-sync
$bb dd if=/dev/pnflasha of=/simulation/small-readback.bin bs=4096 count=16 skip=512 || fail small-read
/usr/bin/openssl dgst -sha256 /simulation/payload.bin /simulation/readback.bin /simulation/small-payload.bin /simulation/small-readback.bin || fail hash
echo PERSIST_COMPONENT_COMPLETE
while :; do $bb sleep 60; done
'''
    files['init']=(stat.S_IFREG|0o755,init);initrd=out/'component.cpio';initrd.write_bytes(cpio(files));geometry=out/'persistent-geometry.bin';geometry.write_bytes(struct.pack('<8sIIQ',b'A7PFGE01',1,0,4*1024*1024));disk=out/'component.emmc'
    with disk.open('xb') as stream:stream.truncate(4*1024*1024)
    env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','MENU_','A7C2_'))};env.update(QEMU_PREPARE_ONLY='1',QEMU_OUTPUT_DIR=str(out/'prepared'),QEMU_SYSTEM_DIR=str(qemu.parent),QEMU_SYSTEM_BINARY=qemu.name,QEMU_EXTRA_CMDLINE='rdinit=/init panic=-1')
    prep=subprocess.run(['bash',A/'qemu-kernel-probe.sh','4096',A/'qemu-virt-board/virt-packed.dtb','1','1',initrd],capture_output=True,env=env,timeout=30);(out/'prepare.stdout').write_bytes(prep.stdout);(out/'prepare.stderr').write_bytes(prep.stderr);need(prep.returncode==0,'Original board preparation failed')
    kernel=A/'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin';fd=os.open(disk,os.O_RDWR|os.O_NOFOLLOW);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);info=os.fstat(fd);name='persistent-component-'+secrets.token_hex(8);process=None;peer=stream=None;result=dict(schema='a7c2-product-original-kernel-persistent-component-v1',original_ap_executed=False,physical_devices_used=False,signals_sent=[],verified=False,module_sha256=sha(module),qemu_sha256=sha(qemu),kernel_sha256=sha(kernel),deadline_seconds=90)
    preserve=[]
    if '--preserve-fds' in subprocess.run(['bwrap','--help'],capture_output=True,text=True).stdout:preserve=['--preserve-fds',str(fd-2)]
    command=['bwrap','--unshare-all','--new-session','--clearenv',*preserve,'--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(qemu.parent),'/tools','--ro-bind',str(kernel),'/kernel.img','--ro-bind',str(initrd),'/initrd.img','--bind',str(out),'/out','--bind',str(out),'/instance','--setenv','QEMU_A7PF_PROFILE','persistent-flash-cold-v1','--setenv','QEMU_A7PF_FD',str(fd),'--setenv','QEMU_A7PF_DEV',str(info.st_dev),'--setenv','QEMU_A7PF_INO',str(info.st_ino),'/tools/'+qemu.name,'-name',name,'-machine','virt,secure=off,gic-version=2','-cpu','cortex-a35','-smp','1','-m','24576','-nodefaults','-display','none','-monitor','none','-serial','stdio','-nic','none','-no-reboot','-sandbox','on','-qmp','unix:/out/qmp.sock,server=on,wait=off','-device','loader,file=/out/prepared/virt.dtb,addr=0x400002000','-device','loader,file=/kernel.img,addr=0x400080000,force-raw=on','-device','loader,file=/initrd.img,addr=0x440000000,force-raw=on','-device','loader,addr=0x400080000,cpu-num=0','-kernel','/kernel.img','-initrd','/initrd.img']
    try:
        with (out/'serial.log').open('xb') as serial,(out/'qemu.stderr').open('xb') as error:
            process=subprocess.Popen(command,pass_fds=(fd,),stdin=subprocess.DEVNULL,stdout=serial,stderr=error);result['owner_identity']=identity(process.pid);save(out/'result.json',result);deadline=time.monotonic()+90
            while time.monotonic()<deadline and process.poll() is None:
                raw=(out/'serial.log').read_bytes()
                if b'PERSIST_COMPONENT_COMPLETE\r\n' in raw or b'PERSIST_COMPONENT_FAIL=' in raw:break
                time.sleep(.1)
            result['deadline_reached']=time.monotonic()>=deadline
    finally:
        if process is not None and process.poll() is None:
            try:
                need(identity(process.pid)==result['owner_identity'],'Component owner identity changed')
                descendants=[];pending=[process.pid]
                while pending:
                    parent=pending.pop()
                    for child in Path('/proc',str(parent),'task',str(parent),'children').read_text().split():
                        row=identity(int(child));descendants.append(row);pending.append(row['pid'])
                result['owner_descendants']=descendants
                peer=socket.socket(socket.AF_UNIX);peer.settimeout(10);directory=os.open(out,os.O_RDONLY|os.O_DIRECTORY)
                try:peer.connect('/proc/self/fd/'+str(directory)+'/qmp.sock')
                finally:os.close(directory)
                peer_pid,peer_uid,peer_gid=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                need(peer_uid==os.geteuid() and peer_gid==os.getegid() and peer_pid in [process.pid,*[x['pid'] for x in descendants]],'QMP peer is outside exact component owner tree')
                result['qmp_peer_identity']=identity(peer_pid)
                stream=peer.makefile('rwb',buffering=0);greeting=json.loads(stream.readline());need('QMP' in greeting,'QMP greeting absent')
                def cmd(execute,number):
                    need(identity(peer_pid)==result['qmp_peer_identity'],'QMP peer identity changed')
                    request=dict(execute=execute,id=number)
                    with (out/'qmp-events.jsonl').open('a') as events:events.write(json.dumps(dict(request=request))+'\n');events.flush();os.fsync(events.fileno())
                    stream.write((json.dumps(request)+'\n').encode())
                    while True:
                        reply=json.loads(stream.readline())
                        with (out/'qmp-events.jsonl').open('a') as events:events.write(json.dumps(dict(response=reply))+'\n');events.flush();os.fsync(events.fileno())
                        if reply.get('id')==number:need('return' in reply and 'error' not in reply,'QMP refused '+execute);return reply['return']
                cmd('qmp_capabilities',1);need(cmd('query-name',2)=={'name':name},'Wrong registered QMP owner');result['qmp_quit_confirmed']=cmd('quit',3)=={};process.wait(timeout=20)
            except BaseException as error:
                result.update(shutdown_error=type(error).__name__+': '+str(error),owner_retained=True)
                save(out/'result.json',result)
                process.wait()
        if stream:stream.close()
        if peer:peer.close()
        if process is not None:
            reap_deadline=time.monotonic()+2
            while any(Path('/proc',str(x['pid'])).exists() for x in result.get('owner_descendants',[])) and time.monotonic()<reap_deadline:time.sleep(.01)
            result['owner_returncode']=process.returncode;result['owner_absent']=not Path('/proc',str(process.pid)).exists();result['descendants_absent']=all(not Path('/proc',str(x['pid'])).exists() for x in result.get('owner_descendants',[]))
        if process is not None and process.poll() is None:
            save(out/'result.json',dict(result,owner_retained=True));process.wait()
        os.fsync(fd);readback=os.pread(fd,4*1024*1024,0);os.close(fd)
        raw=(out/'serial.log').read_bytes();text=raw.decode(errors='replace').replace('\r','');expected=hashlib.sha256(payload).hexdigest();small=payload[:65536];small_sha=hashlib.sha256(small).hexdigest();result.update(guest_payload_sha256_matches=text.count('= '+expected)==2 and text.count('= '+small_sha)==2,host_full_disk_matches_actual_guest_write=readback==payload+bytes(1024*1024)+small+bytes(2*1024*1024-len(small)),root_four_zero_fields='Uid:\t0\t0\t0\t0' in text and 'Gid:\t0\t0\t0\t0' in text,raw_serial_sha256=sha(out/'serial.log'),disk_sha256=sha(disk))
        result['verified']=all(result.get(k) is True for k in ('qmp_quit_confirmed','owner_absent','descendants_absent','guest_payload_sha256_matches','host_full_disk_matches_actual_guest_write','root_four_zero_fields')) and result.get('owner_returncode')==0 and not result.get('shutdown_error') and not result.get('owner_retained') and not result.get('deadline_reached') and 'PERSIST_COMPONENT_COMPLETE' in text and 'PERSIST_COMPONENT_FAIL=' not in text
        save(out/'result.json',result)
    print('PERSISTENT_NATIVE_COMPONENT',result['verified'],out);return 0 if result['verified'] else 1

if __name__=='__main__':raise SystemExit(main())
