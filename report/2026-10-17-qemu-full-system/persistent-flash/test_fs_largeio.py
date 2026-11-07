#!/usr/bin/env python3
"""Bounded synthetic filesystem probe on the original Sony kernel; no host mounts/modules.

--actual requires an unused fresh scratch directory and explicit read-only boot inputs.
The QEMU executable is copied, never rebuilt; only this probe's synthetic disk is writable.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import socket
import struct
import subprocess
import time

import pytest

HERE = Path(__file__).resolve().parent
SIZES = (512, 16384, 131072, 639458, 1048576)
MIB = 1024**2
GUEST = r'''
#include <stddef.h>
typedef unsigned char u8;
extern int open(const char *, int, ...), close(int), fsync(int), rename(const char *,const char *), unlink(const char *);
extern long write(int,const void *,size_t), pread(int,void *,size_t,long);
extern int printf(const char *,...), snprintf(char *,size_t,const char *,...), memcmp(const void *,const void *,size_t), strcmp(const char *,const char *);
extern unsigned long strtoul(const char *,char **,int);
extern int *__errno_location(void);
extern void *malloc(size_t);
extern void free(void *);
extern int ioctl(int,unsigned long,...);
extern int hosd_persist(const char *,const unsigned char *,unsigned long);
static int trace_on;
static long trace(const char *step,int fd,unsigned long off,unsigned long want,long rc,int error) {
    if(trace_on) printf("FS_STEP step=%s fd=%d offset=%lu requested=%lu rc=%ld errno=%d\n",step,fd,off,want,rc,error);
    *__errno_location()=error; return rc;
}
int probe_open(const char *p,int flags,...) {
    *__errno_location()=0; int rc=open(p,flags,0600),e=*__errno_location();
    return trace("open",rc,0,flags,rc,e);
}
long probe_write(int fd,const void *b,size_t n) {
    *__errno_location()=0; long rc=write(fd,b,n); int e=*__errno_location();
    return trace("write",fd,0,n,rc,e);
}
int probe_fsync(int fd) {
    *__errno_location()=0; int rc=fsync(fd),e=*__errno_location();
    return trace("fsync",fd,0,0,rc,e);
}
long probe_pread(int fd,void *b,size_t n,long off) {
    *__errno_location()=0; long rc=pread(fd,b,n,off); int e=*__errno_location();
    return trace("pread",fd,off,n,rc,e);
}
int probe_close(int fd) {
    *__errno_location()=0; int rc=close(fd),e=*__errno_location();
    return trace("close",fd,0,0,rc,e);
}
int probe_rename(const char *p,const char *q) {
    *__errno_location()=0; int rc=rename(p,q),e=*__errno_location();
    return trace("rename",-1,0,0,rc,e);
}
int probe_unlink(const char *p) {
    *__errno_location()=0; int rc=unlink(p),e=*__errno_location();
    return trace("unlink",-1,0,0,rc,e);
}
int probe_memcmp(const void *a,const void *b,size_t n) {
    int rc=memcmp(a,b,n);
    if(rc) { const u8 *x=a,*y=b; size_t i=0; while(i<n&&x[i]==y[i]) i++;
        printf("FS_MISMATCH local_offset=%lu expected=%u actual=%u\n",i,y[i],x[i]); }
    return rc;
}
static int run(int argc,char **argv) {
    if(argc!=4) return 2;
    unsigned long n=strtoul(argv[3],0,10); if(!n||n>1048576) return 2;
    u8 *p=malloc(n); if(!p) return 3;
    for(unsigned long i=0;i<n;i++) p[i]=(u8)((i*73+(i>>8)*19+0xa7)^((i>>16)*31));
    trace_on=1;
    if(!strcmp(argv[1],"write")) {
        int rc=hosd_persist(argv[2],p,n),e=*__errno_location();
        printf("FS_RESULT op=write path=%s size=%lu rc=%d errno=%d\n",argv[2],n,rc,e);
        free(p); return rc?1:0;
    }
    if(!strcmp(argv[1],"read")) {
        int fd=probe_open(argv[2],0); int ok=fd>=0; u8 buf[4096];
        for(unsigned long off=0;ok&&off<n;) {
            unsigned long want=n-off; if(want>sizeof buf) want=sizeof buf;
            long got=probe_pread(fd,buf,want,off);
            ok=got>0&&(unsigned long)got<=want&&!probe_memcmp(buf,p+off,got);
            if(ok) off+=got;
        }
        if(fd>=0&&probe_close(fd)) ok=0;
        printf("FS_RESULT op=read path=%s size=%lu rc=%d\n",argv[2],n,ok?0:1);
        free(p); return ok?0:1;
    }
    if(!strcmp(argv[1],"flush")) {
        int fd=probe_open(argv[2],2); if(fd<0) return 1;
        int rc=probe_fsync(fd); int c=probe_close(fd); free(p); return rc||c;
    }
    free(p);return 2;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((used,noreturn)) void entry(unsigned long *s) {
    __libc_start_main(run,(int)s[0],(char **)(s+1),0,0,0,s);__builtin_unreachable();
}
'''
INIT = '''#!/bin/busybox sh
bb=/bin/busybox
$bb mount -t proc proc /proc
$bb mount -t sysfs sysfs /sys
$bb grep -E '^(Uid|Gid):' /proc/$$/status
$bb cat /proc/version
$bb insmod /qemu/sony_persistent_flash.ko
rc=$?
echo FS_MODULE_RC=$rc
[ "$rc" = 0 ] || exec $bb sh
$bb mkdir -p /mnt/fs-probe
phases=write
case " $($bb cat /proc/cmdline) " in *" fs.probe.read=1 "*) phases='read cleanup';; esac
for phase in $phases; do
    for entry in '10:vfat:rw,sync' '11:vfat:rw,batch_sync' '7:ext2:rw,sync'; do
        oldifs=$IFS; IFS=:; set -- $entry; IFS=$oldifs
        part=$1; type=$2; options=$3
        [ "$phase" = write ] || options=ro
        $bb mount -t "$type" -o "$options" "/dev/cnflasha$part" /mnt/fs-probe
        rc=$?; echo "FS_MOUNT phase=$phase part=$part opts=$options rc=$rc"
        [ "$rc" = 0 ] || continue
        if [ "$phase" = read ]; then
            /qemu/fs-probe write /mnt/fs-probe/ro-denied.bin 512
            echo "FS_RO_DENIED part=$part rc=$?"
        fi
        for size in 512 16384 131072 639458 1048576; do
            file=/mnt/fs-probe/probe-$size.bin
            if [ "$phase" = cleanup ]; then
                [ ! -e "$file" ]; echo "FS_ABSENT part=$part size=$size rc=$?"
            else
                /qemu/fs-probe "$phase" "$file" "$size"
                rc=$?; echo "FS_CASE phase=$phase part=$part size=$size rc=$rc"
            fi
        done
        $bb sync
        /qemu/fs-probe flush "/dev/cnflasha$part" 512
        echo "FS_BLOCK_FSYNC part=$part rc=$?"
        $bb umount /mnt/fs-probe
        rc=$?; echo "FS_UMOUNT phase=$phase part=$part rc=$rc"
    done
    echo "FS_CHECKPOINT phase=$phase"
    [ "$phase" = read ] || continue
    read -r permit
    [ "$permit" = continue ] || break
    if [ "$phase" = read ]; then
        for part in 10 11 7; do
            case "$part" in 7) type=ext2;; *) type=vfat;; esac
            $bb mount -t "$type" -o rw "/dev/cnflasha$part" /mnt/fs-probe || continue
            $bb rm -f /mnt/fs-probe/probe-*.bin /mnt/fs-probe/probe-*.bin.part
            $bb sync
            $bb umount /mnt/fs-probe
            echo "FS_DELETE part=$part rc=$?"
        done
    fi
done
echo FS_COMPLETE
exec $bb sh
'''


def payload(size):
    return bytes(((i*73+(i>>8)*19+0xa7)^((i>>16)*31)) & 255 for i in range(size))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2)+'\n')


def command(args, **kw):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, **kw)
    if result.returncode:
        raise RuntimeError(repr(args)+': '+result.stdout+result.stderr)
    return result


def extract_hosd(source):
    text = Path(source).read_text()
    start = text.index('int hosd_persist(')
    end = text.index('\nint hosd_claim(', start)
    body = text[start:end]
    for symbol in ('open', 'write', 'fsync', 'pread', 'close', 'rename', 'unlink', 'memcmp'):
        body = re.sub(r'\b'+symbol+r'\(', 'probe_'+symbol+'(', body)
    return '#define HOSD_NOFOLLOW 0x8000\n'+body


def make_disk(root):
    rows = [(7, 65536, 16*MIB), (10, 65536+16*MIB, 12*MIB), (11, 65536+28*MIB, 12*MIB)]
    disk = root/'camera.emmc'
    with disk.open('xb') as f:
        f.truncate(65536+40*MIB)
    disk.chmod(0o600)
    for part, offset, length in rows:
        image = root/f'p{part}.img'
        with image.open('xb') as f:
            f.truncate(length)
        if part == 7:
            command(['mkfs.ext2', '-F', '-b', '1024', '-O', '^metadata_csum,^64bit', image])
        else:
            command(['mkfs.fat', '-F', '12', '-s', '32', image])
        with disk.open('r+b') as out, image.open('rb') as source:
            out.seek(offset)
            shutil.copyfileobj(source, out)
    wire = root/'persistent-geometry.bin'
    wire.write_bytes(struct.pack('<8sIIQ', b'A7PFGE01', 1, len(rows), disk.stat().st_size)+b''.join(
        struct.pack('<IIQQ', p, 0, o, n) for p,o,n in rows))
    wire.chmod(0o600)
    return rows


def fs_snapshot(root, rows, label):
    result = []
    with (root/'camera.emmc').open('rb') as disk:
        for part, offset, length in rows:
            image = root/f'{label}-p{part}.img'
            disk.seek(offset)
            image.write_bytes(disk.read(length))
            result.append(dict(part=part,path=str(image),sha256=sha(image)))
    return result


def host_readback(root, snapshots, label):
    read_fat=runpy.run_path(str(HERE.parent/'prepare-full-system.py'))['readFat']
    rows=[]
    for snapshot in snapshots:
        part=snapshot['part'];image=Path(snapshot['path']);contents={}
        if part==7:
            for size in SIZES:
                out=root/f'{label}-host-p{part}-{size}.bin'
                command(['debugfs','-R',f'dump /probe-{size}.bin {out}',image])
                if out.exists():contents[f'probe-{size}.bin']=out.read_bytes()
        else:
            with image.open('rb') as stream:
                for entry in read_fat(stream):
                    if entry.path.lstrip('/') in {f'probe-{size}.bin' for size in SIZES}:
                        contents[entry.path.lstrip('/')]=entry.contents.read()
        for size in SIZES:
            data=contents.get(f'probe-{size}.bin');expected=payload(size)
            actual=hashlib.sha256(data).hexdigest() if data is not None else None
            match=data==expected
            first=None
            if data is not None and not match:
                offset=next((i for i,(a,b) in enumerate(zip(expected,data)) if a!=b),min(len(data),size))
                first=dict(offset=offset,expected=expected[offset] if offset<size else None,
                           actual=data[offset] if offset<len(data) else None)
            rows.append(dict(part=part,size=size,expected_sha256=hashlib.sha256(expected).hexdigest(),
                             actual_sha256=actual,actual_bytes=len(data) if data is not None else None,
                             match=match,first_mismatch=first))
    save(root/(label+'-host-readback.json'),rows)
    return rows


def patch_dtb(source, target, libpath, ram0_bytes, read_phase=False):
    lib=ctypes.CDLL(str(libpath))
    lib.fdt_path_offset.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
    raw=ctypes.create_string_buffer(Path(source).read_bytes());buf=ctypes.create_string_buffer(131072)
    assert lib.fdt_open_into(raw,buf,len(buf))==0
    chosen=lib.fdt_path_offset(buf,b'/chosen');assert chosen>=0
    args=('console=ttyAMA0 earlycon=pl011,0x09000000 loglevel=7 root=/dev/ram0 rootfstype=ext2 rw '
          'init=/qemu/fs-init ramdisk_size=32768 initcall_blacklist=__boottime___udif_init_udif_wdt,'
          '__boottime___udif_init_udif_pcie,__boottime___udif_init_udif_ddrc,__boottime___udif_init_pcidma')
    if read_phase:
        args += ' fs.probe.read=1'
    for key,value in {b'bootargs':args.encode()+b'\0',b'linux,initrd-start':struct.pack('>Q',0x440000000),
                      b'linux,initrd-end':struct.pack('>Q',0x440000000+ram0_bytes)}.items():
        assert lib.fdt_setprop(buf,chosen,key,value,len(value))==0
    assert lib.fdt_pack(buf)==0
    Path(target).write_bytes(buf.raw[:int.from_bytes(buf.raw[4:8],'big')])
    return args


def connect(path, process):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);s.settimeout(5)
        try:
            s.connect(str(path));return s
        except (FileNotFoundError,ConnectionRefusedError):
            s.close()
            if process.poll() is not None:raise RuntimeError('QEMU exited '+str(process.returncode))
            time.sleep(.1)
    raise TimeoutError(str(path))


def actual(args):
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=False,mode=0o700)
    for key in ('qemu','kernel','ram0','dtb','handoff','libfdt','libc','module','hosd'):
        source=getattr(args,key).resolve(strict=True)
        if not source.is_file() or source.is_relative_to(root):raise ValueError(key)
        setattr(args,key,source)
    bindings={key:dict(path=str(getattr(args,key)),sha256=sha(getattr(args,key))) for key in
              ('qemu','kernel','ram0','dtb','handoff','libfdt','libc','module','hosd')}
    save(root/'inputs.json',bindings)
    shutil.copy2(args.qemu,root/'qemu-system-aarch64')
    shutil.copy2(args.ram0,root/'ram0.ext2')
    shutil.copy2(args.module,root/'sony_persistent_flash.ko')
    rows=make_disk(root)
    source=root/'fs-probe.c';source.write_text(GUEST+'\n'+extract_hosd(args.hosd))
    command(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld',
             '-nostdlib','-O2','-fno-stack-protector','-Wl,--no-undefined','-Wl,-e,_start',
             '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',source,args.libc,'-o',root/'fs-probe'])
    init=root/'fs-init';init.write_text(INIT)
    commands=root/'debugfs.commands'
    commands.write_text('rm /qemu/sony_persistent_flash.ko\n'+'\n'.join(f'write {root/name} /qemu/{dest}\nset_inode_field /qemu/{dest} mode 0100755'
        for name,dest in [('fs-probe','fs-probe'),('fs-init','fs-init'),('sony_persistent_flash.ko','sony_persistent_flash.ko')])+'\n')
    command(['debugfs','-w','-f',commands,root/'ram0.ext2'])
    cmdline=patch_dtb(args.dtb,root/'virt.dtb',args.libfdt,(root/'ram0.ext2').stat().st_size)
    diskfd=os.open(root/'camera.emmc',os.O_RDWR);st=os.fstat(diskfd)
    cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
         '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64','--proc','/proc','--dev','/dev',
         '--bind',str(root),'/instance','--ro-bind',str(args.kernel),'/kernel.img','--ro-bind',str(args.handoff),'/boot-handoff.bin',
         '--setenv','QEMU_SONY_TIMERS','1',
         '--setenv','QEMU_A7PF_PROFILE','persistent-flash-cold-v1','--setenv','QEMU_A7PF_FD',str(diskfd),
         '--setenv','QEMU_A7PF_DEV',str(st.st_dev),'--setenv','QEMU_A7PF_INO',str(st.st_ino),
         '/instance/qemu-system-aarch64','-accel','tcg,thread=multi','-machine','virt,secure=off',
         '-cpu','cortex-a35,cntfrq=2000000','-smp','1','-m','24576','-nodefaults','-display','none','-monitor','none',
         '-serial','stdio','-nic','none','-no-reboot','-sandbox','on','-qmp','unix:/instance/qmp.sock,server=on,wait=off',
         '-device','loader,file=/instance/virt.dtb,addr=0x400002000',
         '-device','loader,file=/kernel.img,addr=0x400080000,force-raw=on',
         '-device','loader,file=/instance/ram0.ext2,addr=0x440000000,force-raw=on',
         '-device','loader,file=/boot-handoff.bin,addr=0x400010000,force-raw=on',
         '-device','loader,addr=0x400010000,cpu-num=0','-kernel','/kernel.img','-append',cmdline]
    result=dict(command=cmd,vm_signals=[],verified=False,phases=[],same_backend_inode=st.st_ino)
    try:
        for boot_phase in ('write','read'):
            cmd[-1]=patch_dtb(args.dtb,root/'virt.dtb',args.libfdt,(root/'ram0.ext2').stat().st_size,boot_phase=='read')
            record=dict(phase=boot_phase,command=list(cmd),vm_signals=[],verified=False)
            serial=root/(boot_phase+'-serial.log');sock=stream=None;process=None
            def qmp(name):
                stream.write((json.dumps({'execute':name})+'\n').encode())
                while True:
                    response=json.loads(stream.readline())
                    if 'return' in response:return response
                    if 'error' in response:raise RuntimeError(response)
            try:
                with serial.open('xb') as log:
                    process=subprocess.Popen(cmd,pass_fds=(diskfd,),stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
                record['owner_pid']=process.pid;save(root/(boot_phase+'-owner.json'),record)
                sock=connect(root/'qmp.sock',process);stream=sock.makefile('rwb',buffering=0)
                assert 'QMP' in json.loads(stream.readline());qmp('qmp_capabilities')
                deadline=time.monotonic()+180;seen=False
                while time.monotonic()<deadline:
                    text=serial.read_text(errors='replace').replace('\r','')
                    if 'Kernel panic' in text or 'Internal error: Oops' in text:raise RuntimeError('Guest fault')
                    if process.poll() is not None:raise RuntimeError('QEMU exited before completion')
                    if 'FS_CHECKPOINT phase='+boot_phase in text and not seen:
                        snapshots=fs_snapshot(root,rows,boot_phase)
                        record['snapshots']=snapshots
                        record['host_readback']=host_readback(root,snapshots,boot_phase)
                        seen=True
                        if boot_phase=='read':
                            process.stdin.write(b'continue\n');process.stdin.flush()
                    if 'FS_COMPLETE' in text:
                        record['completed']=True;break
                    time.sleep(.1)
                else:raise TimeoutError('Probe deadline; retained serial')
            finally:
                if process is not None and process.poll() is None:
                    if stream is None:raise RuntimeError('QMP unavailable; owner retained without signal')
                    record['qmp_quit']=qmp('quit');process.wait(timeout=20)
                if process is not None:
                    record['returncode']=process.returncode
                    record['vm_signals']=[] if process.returncode is not None and process.returncode>=0 else [process.returncode]
                    process.stdin.close()
                if stream:stream.close()
                if sock:sock.close()
                save(root/(boot_phase+'-owner.json'),record)
                result['phases'].append(record)
                save(root/'result.json',result)
            text=serial.read_text(errors='replace').replace('\r','')
            record['guest_cases']=re.findall(r'^FS_CASE phase='+boot_phase+r' part=(\d+) size=(\d+) rc=(\d+)$',text,re.M)
            record['root_status']=bool(re.search(r'^Uid:\s+0\s+0\s+0\s+0$',text,re.M) and re.search(r'^Gid:\s+0\s+0\s+0\s+0$',text,re.M))
            record['verified']=record.get('completed',False) and record['returncode']==0 and record['root_status'] and (
                len(record['guest_cases'])==15 and all(r[2]=='0' for r in record['guest_cases']) and
                len(record.get('host_readback',[]))==15 and all(r['match'] for r in record['host_readback']))
            if boot_phase=='read':
                record['readonly_rejected']=all(f'FS_RO_DENIED part={part} rc=1' in text for part in (7,10,11)) and text.count('FS_STEP step=open fd=-1 offset=0 requested=32962 rc=-1 errno=30')==3
                record['cleanup_remount_absent']=all(f'FS_ABSENT part={part} size={size} rc=0' in text for part in (7,10,11) for size in SIZES) and all(
                    f'FS_DELETE part={part} rc=0' in text and f'FS_UMOUNT phase=cleanup part={part} rc=0' in text for part in (7,10,11))
                record['verified'] &= record['readonly_rejected'] and record['cleanup_remount_absent']
            record['verified'] &= all(f'FS_UMOUNT phase={boot_phase} part={part} rc=0' in text for part in (7,10,11))
            save(root/(boot_phase+'-owner.json'),record)
        result['verified']=all(r['verified'] for r in result['phases']) and len(result['phases'])==2
        result['vm_signals']=[signal for r in result['phases'] for signal in r['vm_signals']]
    finally:
        os.close(diskfd)
        for key,binding in bindings.items():
            assert sha(getattr(args,key))==binding['sha256'],key+' changed'
        save(root/'result.json',result)
    return result


def test_payload_changes_across_pages():
    p=payload(1048576)
    assert len(p)==1048576 and p[:4096]!=p[4096:8192] and p[:65536]!=p[65536:131072]


def test_synthetic_geometry_and_fat_cluster_size(tmp_path):
    rows=make_disk(tmp_path)
    assert [r[0] for r in rows]==[7,10,11]
    assert (tmp_path/'p10.img').read_bytes()[13]*512==16384
    assert (tmp_path/'camera.emmc').stat().st_size==65536+40*MIB


def test_host_readback_rejects_corruption_and_truncation(tmp_path,monkeypatch):
    import io
    from types import SimpleNamespace
    image=tmp_path/'fat.img';image.write_bytes(b'fixture')
    data=payload(512);damaged=bytes([data[0]^1])+data[1:]
    entries=[SimpleNamespace(path='/probe-512.bin',contents=io.BytesIO(damaged)),
             SimpleNamespace(path='/probe-16384.bin',contents=io.BytesIO(payload(16384)[:-1]))]
    monkeypatch.setattr(runpy,'run_path',lambda path:{'readFat':lambda stream:iter(entries)})
    result=host_readback(tmp_path,[dict(part=10,path=str(image))],'fault')
    assert all(not row['match'] for row in result)
    assert result[0]['first_mismatch']==dict(offset=0,expected=data[0],actual=damaged[0])
    assert result[1]['first_mismatch']['offset']==16383
    assert result[2]['actual_sha256'] is None


def test_hosd_instrumentation_keeps_complete_readback(tmp_path):
    source=tmp_path/'hosd.c'
    source.write_text('int hosd_persist(void) { write(1, p, n); fsync(1); pread(1, p, n, 0); memcmp(p, q, n); close(1); rename(p, q); unlink(p); }\nint hosd_claim(void) {}')
    instrumented=extract_hosd(source)
    for symbol in ('write','fsync','pread','memcmp','close','rename','unlink'):
        assert 'probe_'+symbol+'(' in instrumented
    assert 'hosd_claim' not in instrumented


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--actual',action='store_true',required=True)
    for name in ('qemu','kernel','ram0','dtb','handoff','libfdt','libc','module','hosd','output'):
        p.add_argument('--'+name,type=Path,required=True)
    result=actual(p.parse_args())
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['verified'] else 1)
