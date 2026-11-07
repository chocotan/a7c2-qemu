#!/usr/bin/env python3
"""Small original p3 RAM0 -> durable functional flash -> untouched Sony init.

build(instance, prepared_runtime_analysis, output) prepares new artifacts only.
prepare_launch prepares a raw-ext2 board; leased_launch binds the live FD and
holds the instance lease until the caller has completed normal QMP shutdown.

Parent integration (no UI changes):
    built = build(instance, prepared_runtime_analysis, fresh_output)
    launch = prepare_launch(prepared_runtime_analysis, built, fresh_launch_output)
    with leased_launch(launch) as bound:
        boot_execution['run'](bound, built, fresh_evidence_output, seconds=90)

The owner runner must pass bound['pass_fds'] to Popen and append its process to
bound['children']. Main's runner supports both. No live FD is serialized into a
manifest. All evidence flags in the build manifest remain unset until observed.

Production QEMU build:
    python3 persistent-flash/build.py --production --stage <fresh-scratch> \\
        --qemu-template <independent-Sony-USB-source-and-build>
Pass its build/ directory as prepare_launch(..., qemu_build=...). The default is
the dedicated research production build; no fallback to fixture/unpatched QEMU.

Actual two-process original-kernel persistence proof:
    python3 test-persistent-boot.py --actual --manifest <build>/manifest.json \\
        --output <fresh-proof-output>
Only the declared instance is changed. Small RAM0 contains no volume images.
Official/private disk and helper provenance are separate. Physical encryption,
missing CP/WBI compatibility and complete AP startup are never inferred from
successful block IO, original kernel module loading or filesystem persistence.
"""
import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
PROFILE='persistent-flash-cold-v1'
COLD=runpy.run_path(str(HERE/'cold-init-chain.py'))
DISK=runpy.run_path(str(HERE/'camera-disk.py'))
GEOMETRY=runpy.run_path(str(HERE/'persistent-flash/geometry.py'))
DEFAULT_BUILD=PROJECT/'analysis/scratch/a7c2-persistent-flash-20261106'
MIB=1024**2
APP_SHA='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
KERNEL_ASSET='unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
FIRMWARE_SLICES=('nflasha3','nflasha7','nflasha15')
IDENTITY_FIELDS=('firmware_binding_schema','actual_kernel','partition_bindings','instance_generation',
                 'instance_source_manifest_sha256','instance_geometry','instance_wire_sha256')
DTB_PATCH=r'''from pathlib import Path
import ctypes,sys
path=Path(sys.argv[1]);lib=ctypes.CDLL(sys.argv[2])
raw=ctypes.create_string_buffer(path.read_bytes());buf=ctypes.create_string_buffer(65536)
if lib.fdt_open_into(raw,buf,len(buf)):raise ValueError('Cannot expand persistent DTB')
node=lib.fdt_add_subnode(buf,0,b'persistent-flash@b000000')
if node<0:raise ValueError('Persistent MMIO DTB node conflict')
for name,value in {b'compatible':b'project,a7c2-functional-persistent-flash-v1\0',b'reg':(0x0b000000).to_bytes(8,'big')+(4096).to_bytes(8,'big'),b'status':b'okay\0'}.items():
    if lib.fdt_setprop(buf,node,name,value,len(value)):raise ValueError('Cannot describe persistent MMIO')
if lib.fdt_pack(buf):raise ValueError('Cannot pack persistent DTB')
data=buf.raw;path.write_bytes(data[:int.from_bytes(data[4:8],'big')])
'''

BOOTSTRAP='''#!/bin/busybox sh
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
fail() { echo "PERSISTENT_BOOTSTRAP_FAILED stage=$1 rc=${2:-1}"; exec /bin/busybox sh </dev/console >/dev/console 2>&1; }
[ "$$" = 1 ] || fail not-pid1
proc_owned=0
if [ ! -r /proc/self/mountinfo ]; then
    /bin/busybox mount -t proc proc /proc || fail proc
    proc_owned=1
fi
case " $(/bin/busybox cat /proc/cmdline) " in
    *" persistent.profile=persistent-flash-cold-v1 "*) ;;
    *) fail profile;;
esac
[ ! -e /dev/qemu-simulation ] || fail simulation-exists
sys_owned=0
if [ ! -r /sys/kernel/uevent_seqnum ]; then
    /bin/busybox mount -t sysfs sysfs /sys || fail sysfs
    sys_owned=1
fi
/bin/busybox mkdir -m 700 /dev/qemu-simulation || fail simulation-directory
while read -r relative bytes sha mode; do
    parent=${relative%/*}
    if [ "$parent" != "$relative" ]; then /bin/busybox mkdir -p "/dev/qemu-simulation/$parent" || fail helper-directory; fi
    /qemu/cold-start-audit copy "/qemu-input/simulation/$relative" "/dev/qemu-simulation/$relative" "$bytes" "$sha" "$mode" || fail helper-copy
done < /qemu/simulation-list
/bin/busybox insmod /qemu/sony_persistent_flash.ko
rc=$?
echo "PERSISTENT_FLASH_INSMOD rc=$rc"
[ "$rc" = 0 ] || fail insmod "$rc"
/bin/busybox sh /qemu/create-aliases.sh || fail aliases
while read -r node sectors; do
    actual=$(/bin/busybox cat "/sys/block/$node/size") || fail capacity-read
    echo "PERSISTENT_CAPACITY node=$node expected=$sectors actual=$actual"
    [ "$actual" = "$sectors" ] || fail capacity-mismatch
done < /qemu/capacity-list
/bin/busybox cat /proc/modules /proc/partitions
case " $(/bin/busybox cat /proc/cmdline) " in
    *" persistent.proof=write "*) /bin/busybox sh /qemu/filesystem-proof write || fail proof-write; exec /bin/busybox sh </dev/console >/dev/console 2>&1;;
    *" persistent.proof=read "*) /bin/busybox sh /qemu/filesystem-proof read || fail proof-read; exec /bin/busybox sh </dev/console >/dev/console 2>&1;;
esac
[ "$sys_owned" = 0 ] || /bin/busybox umount /sys || fail sysfs-release
[ "$proc_owned" = 0 ] || /bin/busybox umount /proc || fail proc-release
echo COLD_BEFORE_ORIGINAL_INIT
echo PERSISTENT_BEFORE_ORIGINAL_INIT
cd / || fail cwd
exec /bin/busybox sh -x /sbin/init
'''
INSMOD='''#!/bin/busybox sh
# Explicit virtual storage adaptation; original init and helper bytes are unchanged.
case "$1" in
    /kmod/crypt-emmc.ko|/kmod/emmc.ko)
        echo "PERSISTENT_MODULE_UNSUPPORTED module=$1 storage=durable-mmio result=78"
        exit 78;;
    /usr/kmod/*)
        if [ ! -e /dev/qemu-simulation/persistent-init2-observed ]; then
            echo "COLD_INIT2_PROCESS parent=$PPID"
            /bin/busybox cat /proc/$PPID/cmdline /proc/$PPID/status /proc/1/mountinfo
            echo "COLD_EXPECTED_IM version=@IM_VERSION@ sha256=@IM_SHA@"
            digest=$(/usr/bin/openssl dgst -sha256 /usr/bin/bootin.elf) || exit 1
            case "$digest" in
                "SHA256(/usr/bin/bootin.elf)= @BOOTIN_SHA@"|"SHA2-256(/usr/bin/bootin.elf)= @BOOTIN_SHA@") ;;
                *) echo PERSISTENT_BOOTIN_BIND_FAILED_SHA; exit 1;;
            esac
            /bin/busybox mount --bind /usr/bin/bootin.elf /dev/qemu-simulation/bootin-original || exit 1
            /bin/busybox mount --bind /dev/qemu-simulation/bootin-wrapper /usr/bin/bootin.elf || exit 1
            /bin/busybox mkdir -p /log/qemu || exit 1
            for name in menu-load.log gpe-requests.bin im.log; do
                /bin/busybox rm -f "/tmp/$name" || exit 1
                /bin/busybox ln -s "/log/qemu/$name" "/tmp/$name" || exit 1
            done
            case " $(/bin/busybox cat /proc/cmdline) " in
                *" persistent.camera-profile=virtual-functional-camera-v1 "*)
                    [ ! -L /tmp/fullsystem-insmod-policy ] || exit 1
                    if [ -e /tmp/fullsystem-insmod-policy ]; then
                        [ -f /tmp/fullsystem-insmod-policy ] || exit 1
                        /bin/busybox cp /tmp/fullsystem-insmod-policy /dev/qemu-simulation/insmod-policy.before || exit 1
                        /bin/busybox cmp /tmp/fullsystem-insmod-policy /dev/qemu-simulation/insmod-policy.before || exit 1
                    fi
                    echo media-rm > /tmp/fullsystem-insmod-policy || exit 1
                    [ "$(/bin/busybox cat /tmp/fullsystem-insmod-policy)" = media-rm ] || exit 1
                    policy_digest=$(/usr/bin/openssl dgst -sha256 /tmp/fullsystem-insmod-policy) || exit 1
                    echo "$policy_digest"
                    case "$policy_digest" in
                        "SHA256(/tmp/fullsystem-insmod-policy)= c4a7cc15db0902fea0ce2d608184a5585fdf87c40718b7f91570f53595053bc5"|"SHA2-256(/tmp/fullsystem-insmod-policy)= c4a7cc15db0902fea0ce2d608184a5585fdf87c40718b7f91570f53595053bc5") ;;
                        *) exit 1;;
                    esac
                    echo PERSISTENT_INSMOD_POLICY=media-rm;;
            esac
            /bin/busybox touch /dev/qemu-simulation/persistent-init2-observed
            echo 'PERSISTENT_BOOTIN_BIND verified=1 original=/dev/qemu-simulation/bootin-original'
        fi;;
esac
exec /dev/qemu-simulation/cold-house-insmod "$@"
'''.replace('@BOOTIN_SHA@',COLD['BOOTIN_SHA']).replace('@IM_VERSION@',COLD['IM_VERSION']).replace('@IM_SHA@',COLD['IM_SHA'])
PROOF='''#!/bin/busybox sh
set -eu
bb=/bin/busybox
$bb mkdir -p /mnt/persistent-root /mnt/persistent-log
$bb mount -t ext2 -o ro /dev/nflasha7 /mnt/persistent-root
/qemu/cold-start-audit copy /mnt/persistent-root/sbin/init2 /dev/proof-init2 @INIT2_SIZE@ @INIT2_SHA@ 600
$bb rm -f /dev/proof-init2
$bb umount /mnt/persistent-root
echo PERSISTENT_PROOF_P7_MOUNT verified=1
$bb mount -t vfat -o rw /dev/nflasha11 /mnt/persistent-log
folder=/mnt/persistent-log/a7pf-@TOKEN@
case "$1" in
 write)
    [ ! -e "$folder" ]
    $bb mkdir "$folder"
    $bb cp /qemu/proof-payload "$folder/payload.bin"
    $bb sync;;
 read) [ -f "$folder/payload.bin" ];;
 *) exit 2;;
esac
/qemu/cold-start-audit copy "$folder/payload.bin" /dev/proof-readback @PAYLOAD_SIZE@ @PAYLOAD_SHA@ 600
$bb rm -f /dev/proof-readback
if [ "$1" = read ]; then
    $bb rm "$folder/payload.bin"
    $bb rmdir "$folder"
    $bb sync
fi
$bb umount /mnt/persistent-log
if [ "$1" = read ]; then
    $bb mount -t vfat -o ro /dev/nflasha11 /mnt/persistent-log
    [ ! -e "$folder" ]
    $bb umount /mnt/persistent-log
    echo 'PERSISTENT_PROOF_REMOVED readback_absent=1'
fi
echo "PERSISTENT_PROOF_COMPLETE mode=$1 payload_sha256=@PAYLOAD_SHA@ unmounted=1"
'''


def save(path,value):
    with Path(path).open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


class Slice(io.RawIOBase):
    """Bounded read-only pread view; no seek or write on the shared host FD."""
    def __init__(self,fd,offset,length):
        self.fd,self.offset,self.length,self.position=fd,offset,length,0
    def seek(self,offset,whence=0):
        value=offset+(self.position if whence==1 else self.length if whence==2 else 0)
        if whence not in (0,1,2) or not 0<=value<=self.length:raise ValueError('Slice seek outside bounds')
        self.position=value;return value
    def tell(self):return self.position
    def read(self,size=-1):
        size=self.length-self.position if size<0 else min(size,self.length-self.position)
        data=os.pread(self.fd,size,self.offset+self.position)
        if len(data)!=size:raise OSError('Short read in persistent source slice')
        self.position+=len(data);return data


def part(leased,name):
    matches=[r for r in leased['geometry']['slices'] if r['id']==name]
    if len(matches)!=1:raise ValueError('Missing or duplicate slice '+name)
    r=matches[0];return Slice(leased['fd'],r['offset'],r['bytes'])


class IdentityMismatch(ValueError):
    def __init__(self,label,expected,actual):
        self.identity=dict(label=label,expected=expected,actual=actual)
        super().__init__('Persistent identity mismatch: '+json.dumps(self.identity,sort_keys=True))


def identical(label,expected,actual):
    if expected!=actual:raise IdentityMismatch(label,expected,actual)


def failure(error,**fields):
    return dict(fields,error=type(error).__name__+': '+str(error),**getattr(error,'identity',{}))


def firmware_contract(manifest):
    missing=[name for name in IDENTITY_FIELDS if name not in manifest]
    if missing:raise ValueError('Legacy persistent manifest unsupported; rebuild explicitly; missing '+','.join(missing))
    identical('firmware binding schema',1,manifest['firmware_binding_schema'])
    generation=manifest['instance_generation']
    if type(generation) is not int or generation<0:raise ValueError('Invalid bound instance generation')
    if not re.fullmatch(r'[0-9a-f]{64}',manifest['instance_source_manifest_sha256']):
        raise ValueError('Invalid bound instance source manifest SHA256')
    return {name:manifest[name] for name in IDENTITY_FIELDS}


def current_kernel_binding(kernel):
    identical('kernel source slice','nflasha3',kernel.get('source_slice'))
    identical('kernel FAT path','vmlinux.bin',kernel.get('fat_path'))
    identical('official kernel SHA256',COLD['KERNEL_SHA'],kernel.get('sha256'))
    row=COLD['binding'](kernel['path'],'current-disk-kernel')
    identical('current disk kernel bytes',kernel['bytes'],row['bytes'])
    identical('current disk kernel SHA256',kernel['sha256'],row['sha256'])
    return row


def partition_bindings(leased):
    result=[];size=os.fstat(leased['fd']).st_size
    for name in FIRMWARE_SLICES:
        view=part(leased,name)
        if (type(view.offset) is not int or type(view.length) is not int or view.offset<0
                or view.length<=0 or view.offset+view.length>size):raise ValueError('Invalid bound firmware range '+name)
        result.append(dict(id=name,offset=view.offset,bytes=view.length,
                           sha256=DISK['hashed'](leased['fd'],view.offset,view.length)))
    return result


def verify_firmware(leased,manifest):
    firmware_contract(manifest)
    identical('instance generation',manifest['instance_generation'],leased['state'].get('generation'))
    identical('instance source manifest SHA256',manifest['instance_source_manifest_sha256'],leased['state'].get('source_manifest_sha256'))
    identical('instance geometry',manifest['instance_geometry'],leased['geometry'])
    with tempfile.TemporaryDirectory(prefix='a7pf-wire-') as temporary:
        canonical=Path(temporary)/'geometry.bin'
        GEOMETRY['write_camera_wire'](leased['geometry'],canonical)
        identical('canonical wire geometry SHA256',manifest['instance_wire_sha256'],COLD['digest'](canonical))
    identical('instance wire geometry SHA256',manifest['instance_wire_sha256'],
              COLD['digest'](leased['path']/'persistent-geometry.bin'))
    rows=manifest['partition_bindings']
    identical('firmware slice inventory',list(FIRMWARE_SLICES),[row.get('id') for row in rows])
    for row in rows:
        view=part(leased,row['id'])
        identical(row['id']+' range',dict(offset=view.offset,bytes=view.length),
                  dict(offset=row.get('offset'),bytes=row.get('bytes')))
    for expected,actual in zip(rows,partition_bindings(leased)):
        identical(expected['id']+' SHA256',expected['sha256'],actual['sha256'])


def extract_boot_files(view,read_fat,work,prepared_kernel):
    """Read both original boot assets in one bounded p3 FAT traversal."""
    identical('prepared official kernel SHA256',COLD['KERNEL_SHA'],prepared_kernel['sha256'])
    wanted={'initrd.img':(COLD['ORIGINAL_RAMROOT_BYTES'],COLD['ORIGINAL_RAMROOT_SHA'],work/'ram0.ext2'),
            'vmlinux.bin':(prepared_kernel['bytes'],COLD['KERNEL_SHA'],work/'current-kernel.bin')}
    found=set()
    for count,entry in enumerate(read_fat(view)):
        if count>=100000:raise ValueError('Oversized p3 FAT directory inventory')
        name=entry.path.lstrip('/')
        if name not in wanted:continue
        if name in found:raise ValueError('Duplicate current p3 '+name)
        found.add(name);size,sha,target=wanted[name]
        if not stat.S_ISREG(entry.mode) or not 0<entry.size<=128*MIB:raise ValueError('Invalid current p3 file '+name)
        identical('p3 '+name+' bytes',size,entry.size)
        data=entry.contents.read(entry.size+1)
        identical('p3 '+name+' read bytes',entry.size,len(data))
        identical('p3 '+name+' SHA256',sha,hashlib.sha256(data).hexdigest())
        with target.open('xb') as stream:stream.write(data)
        target.chmod(0o600)
    if found!=set(wanted):raise ValueError('Missing current p3 boot assets: '+','.join(sorted(set(wanted)-found)))
    kernel=dict(source_slice='nflasha3',fat_path='vmlinux.bin',path=str(work/'current-kernel.bin'),
                bytes=prepared_kernel['bytes'],sha256=prepared_kernel['sha256'])
    current_kernel_binding(kernel)
    return kernel


def ext2_identities(view,wanted):
    # The prepared runtime bundles FAT only. The complete pinned vendor must run
    # separately so an already imported fwtool stub cannot shadow its ext2 reader.
    parser=r'''import hashlib,json,runpy,stat,sys
from pathlib import Path
api=runpy.run_path(sys.argv[1])
importer=runpy.run_path(str(Path(sys.argv[1]).with_name('import-bodydata.py')))
(ext2,)=importer['vendor'](Path(sys.argv[2]),('fwtool.archive.ext2',))
view=api['Slice'](int(sys.argv[3]),int(sys.argv[4]),int(sys.argv[5]))
wanted=json.loads(sys.argv[6]);result={}
for entry in ext2.readExt2(view):
    name='/'+entry.path.lstrip('/')
    if name not in wanted:continue
    if not stat.S_ISREG(entry.mode):raise ValueError('Expected original regular file '+name)
    h=hashlib.sha256();size=0
    while True:
        data=entry.contents.read(1024*1024)
        if not data:break
        h.update(data);size+=len(data)
    if size!=entry.size:raise ValueError('Short ext2 file '+name)
    result[name]=dict(bytes=size,sha256=h.hexdigest())
if set(result)!=set(wanted):raise ValueError('Missing original ext2 identity')
print(json.dumps(result))
'''
    command=[sys.executable,'-I','-B','-c',parser,str(HERE/'persistent-boot.py'),
             str(PROJECT/'analysis/vendor/fwtool'),str(view.fd),str(view.offset),str(view.length),json.dumps(wanted)]
    checked=subprocess.run(command,pass_fds=(view.fd,),capture_output=True,text=True,timeout=55)
    if checked.returncode:raise ValueError('Verified slice ext2 reader failed: '+checked.stderr[-2500:])
    return json.loads(checked.stdout)


def copy_slice(view,target):
    with Path(target).open('xb') as f:
        for offset in range(0,view.length,MIB):
            data=os.pread(view.fd,min(MIB,view.length-offset),view.offset+offset)
            if len(data)!=min(MIB,view.length-offset):raise OSError('Short slice snapshot')
            if any(data):f.seek(offset);f.write(data)
        f.truncate(view.length)
    Path(target).chmod(0o600)


def install_slice(fd,row,image):
    with Path(image).open('rb') as f:
        for off in range(0,row['bytes'],131072):
            data=f.read(min(131072,row['bytes']-off))
            if not data or os.pwrite(fd,data,row['offset']+off)!=len(data):raise OSError('Short adapter write')
    os.fdatasync(fd)
    if DISK['hashed'](fd,row['offset'],row['bytes'])!=COLD['digest'](image):raise OSError('Adapter readback SHA differs')


def fresh_output(output,*inputs):
    output=Path(os.path.abspath(output));COLD['plain'](output.parent,directory=True)
    if os.path.lexists(output):raise ValueError('Output must be a new directory')
    for source in inputs:
        source=Path(source).resolve()
        if output.is_relative_to(source) or source.is_relative_to(output):raise ValueError('Output overlaps source/instance')
    output.mkdir(mode=0o700);return output


def build(instance,prepared_runtime_analysis,output,*,module=None):
    runtime=COLD['plain'](prepared_runtime_analysis,directory=True)
    instance=COLD['plain'](instance,directory=True)
    output=fresh_output(output,runtime,instance)
    work=output/'artifacts';work.mkdir();scratch=work/'readback';scratch.mkdir()
    inputs=[]
    try:
        manifest_path=COLD['plain'](runtime/'full-system.json')
        source=json.loads(manifest_path.read_text())
        if source.get('schema')!=1 or source.get('source') not in ('private-device-dump','official-bodydata-derived'):
            raise ValueError('Unsupported prepared runtime source class')
        if source.get('cold_init_chain') or source.get('bootin_wrapper_experiment'):raise ValueError('Already adapted RAM profile refused')
        inputs.append(COLD['binding'](manifest_path,'prepared-manifest'))
        kernel=COLD['binding'](runtime/KERNEL_ASSET,'original-kernel')
        identical('prepared official kernel SHA256',COLD['KERNEL_SHA'],kernel['sha256'])
        inputs.append(kernel)
        module=Path(module) if module else DEFAULT_BUILD/'module/sony_persistent_flash.ko'
        modinfo=subprocess.run(['aarch64-linux-gnu-readelf','-p','.modinfo',str(COLD['plain'](module))],capture_output=True,text=True,check=True)
        if 'vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64' not in modinfo.stdout:raise ValueError('Guest module ABI vermagic differs')
        inputs.append(COLD['binding'](module,'guest-block-module'))
        COLD['clone'](module,work/'sony_persistent_flash.ko',COLD['digest'](module))
        overlay=runpy.run_path(str(HERE/'overwrite-images.py'))
        simsource=COLD['plain'](runtime/'root/simulation',directory=True)
        simulation=work/'simulation';simulation.mkdir()
        for path in sorted(simsource.rglob('*')):
            if path.is_dir():COLD['plain'](path,directory=True);continue
            relative=path.relative_to(simsource).as_posix()
            if relative in ('media-template.fat','attach-loop'):continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',relative):raise ValueError('Unsafe simulation path')
            selected=COLD['BOOTIN_WRAPPER_SOURCE'] if relative=='bootin-wrapper' else path
            row=COLD['binding'](selected,'simulation-input');inputs.append(row)
            COLD['clone'](selected,simulation/relative,row['sha256'])
            (simulation/relative).chmod(0o755 if relative=='bootin-wrapper' else row['mode'])
        COLD['validate_bootin_wrapper'](simulation/'bootin-wrapper')
        house=COLD['binding'](runtime/'root/sbin/insmod','house-insmod')
        if house['sha256']!=source.get('derived_files',{}).get('sbin/insmod'):raise ValueError('House insmod identity differs')
        inputs.append(house);COLD['clone'](Path(house['path']),simulation/'cold-house-insmod',house['sha256'])
        (simulation/'cold-house-insmod').chmod(0o755)
        libc=COLD['binding'](runtime/'root/lib/libc-2.25.so','guest-libc')
        if libc['sha256']!=source.get('derived_files',{}).get('lib/libc-2.25.so'):raise ValueError('Prepared libc identity differs')
        inputs.append(libc)
        for path in (HERE/'guest/cold-start-audit.c',HERE/'persistent-flash/create-aliases.sh',HERE/'cold-init-chain.py',Path(__file__)):
            inputs.append(COLD['binding'](path,'builder-source'))
        COLD['_compile_audit'](HERE/'guest/cold-start-audit.c',Path(libc['path']),simulation/'cold-start-audit')
        (simulation/'bootin-original').write_bytes(b'');(simulation/'bootin-original').chmod(0o755)
        shim=work/'persistent-insmod';shim.write_text(INSMOD,encoding='ascii')
        release=work/'persistent-freeramdisk';release.write_text(COLD['FREERAM_OBSERVE'],encoding='ascii')
        bootstrap=work/'persistent-bootstrap';bootstrap.write_text(BOOTSTRAP,encoding='ascii')
        with DISK['lease'](instance) as leased:
            disk_source=leased['state']['source_class']
            if disk_source not in ('private-device-dump','official-bodydata-derived'):raise ValueError('Unknown instance provenance class')
            # Helper provenance is independent; all disk bytes come from this FD,
            # and original kernel/init/helpers/AP hashes are checked separately.
            wire=instance/'persistent-geometry.bin'
            candidate=work/'persistent-geometry.bin';GEOMETRY['write_camera_wire'](leased['geometry'],candidate)
            if wire.exists():
                if COLD['digest'](wire)!=COLD['digest'](candidate):raise ValueError('Existing instance wire geometry drift')
            else:COLD['clone'](candidate,wire,COLD['digest'](candidate))
            before_bindings=partition_bindings(leased)
            identities=ext2_identities(part(leased,'nflasha15'),['/bin/bootin.elf','/lib/appFw.so','/bin/im.elf'])
            COLD['verify_im_identity'](identities['/bin/im.elf'])
            if identities['/bin/bootin.elf']['sha256']!=COLD['BOOTIN_SHA'] or identities['/lib/appFw.so']['sha256']!=APP_SHA:
                raise ValueError('Original bootin/AP identity differs; explicit new baseline required')
            ram0=work/'ram0.ext2';read_fat=runpy.run_path(str(HERE/'prepare-full-system.py'))['readFat']
            actual_kernel=extract_boot_files(part(leased,'nflasha3'),read_fat,work,kernel)
            ram_before=overlay['Ext2'](ram0,scratch).inventory();ram_identity=COLD['scripts'](ram_before,COLD['RAM_SCRIPTS'])
            p7_before=work/'p7-before.ext2';copy_slice(part(leased,'nflasha7'),p7_before)
            p7=work/'p7-adapted.ext2';COLD['clone'](p7_before,p7,COLD['digest'](p7_before))
            before=overlay['Ext2'](p7,scratch).inventory();p7_identity=COLD['scripts'](before,COLD['P7_SCRIPTS'])
            old=before['entries'].get('/sbin/insmod',{})
            ledger=instance/'persistent-boot-adapter.json'
            if old.get('kind')!='symlink':
                if not ledger.is_file() or old.get('sha256')!=json.loads(COLD['plain'](ledger).read_text()).get('shim_sha256'):
                    raise ValueError('Existing p7 insmod is not original or a recorded project adapter')
            wanted={'/simulation':COLD['_link']('/dev/qemu-simulation'),
                '/sbin/insmod':COLD['_file'](shim),'/sbin/freeramdisk':COLD['_file'](release)}
            delta={name:change for name,change in wanted.items() if before['entries'].get(name)!=change[0]}
            after=before
            if delta:_,after=COLD['_edit_image'](p7,scratch,delta,overlay)
            COLD['scripts'](after,COLD['P7_SCRIPTS'])
            p7row=next(r for r in leased['geometry']['slices'] if r['id']=='nflasha7')
            adaptation=dict(schema=1,profile=PROFILE,kind='virtual-boot-adaptation',firmware_user_diff=False,
                changes=['/simulation symlink','/sbin/insmod explicit project shim','/sbin/freeramdisk observer'],
                backup=str(p7_before),before_sha256=COLD['digest'](p7_before),after_sha256=COLD['digest'](p7),
                shim_sha256=COLD['digest'](shim),script_identity=p7_identity,usr_partition_written=False,
                adapter_reused_without_disk_write=not delta)
            save(work/'adapter-intent.json',adaptation)
            if adaptation['before_sha256']!=adaptation['after_sha256']:install_slice(leased['fd'],p7row,p7)
            if ledger.exists():
                previous=json.loads(COLD['plain'](ledger).read_text());save(work/'previous-adapter.json',previous)
                adaptation['initial_backup']=previous.get('initial_backup',previous['backup'])
                adaptation['initial_sha256']=previous.get('initial_sha256',previous['before_sha256'])
                temporary=instance/('persistent-boot-adapter-'+secrets.token_hex(6)+'.json');save(temporary,adaptation);os.replace(temporary,ledger)
            else:
                adaptation['initial_backup']=adaptation['backup']
                adaptation['initial_sha256']=adaptation['before_sha256']
                save(ledger,adaptation)
            geometry=leased['geometry']
            bindings=partition_bindings(leased)
            for original,current in zip(before_bindings,bindings):
                expected=COLD['digest'](p7) if current['id']=='nflasha7' else original['sha256']
                identical(current['id']+' build readback SHA256',expected,current['sha256'])
            identity=dict(firmware_binding_schema=1,actual_kernel=actual_kernel,partition_bindings=bindings,
                instance_generation=leased['state']['generation'],
                instance_source_manifest_sha256=leased['state']['source_manifest_sha256'],
                instance_geometry=geometry,instance_wire_sha256=COLD['digest'](wire))
            verify_firmware(leased,identity)
        token=secrets.token_hex(12);payload=('A7C2 persistent original Sony kernel filesystem proof '+token+'\n').encode()
        payload_path=work/'proof-payload';payload_path.write_bytes(payload)
        proof=PROOF
        init2=after['entries']['/sbin/init2']
        for key,value in dict(INIT2_SIZE=init2['size'],INIT2_SHA=init2['sha256'],TOKEN=token,
                              PAYLOAD_SIZE=len(payload),PAYLOAD_SHA=hashlib.sha256(payload).hexdigest()).items():
            proof=proof.replace('@'+key+'@',str(value))
        proofpath=work/'filesystem-proof';proofpath.write_text(proof,encoding='ascii')
        capacity=[('pnflasha',geometry['user_bytes']//512)]
        capacity.extend(('cnflasha'+str(r['part']),r['bytes']//512) for r in geometry['partition_rows'] if r['bytes'])
        capacity.extend((f'nflashaB{i}',4194304//512) for i in (0,1))
        caplist=work/'capacity-list';caplist.write_text(''.join(f'{n} {s}\n' for n,s in capacity),encoding='ascii')
        simrows=[]
        for path in sorted(simulation.rglob('*')):
            if path.is_file():simrows.append((path.relative_to(simulation).as_posix(),path.stat().st_size,COLD['digest'](path),stat.S_IMODE(path.stat().st_mode)))
        simbytes=sum(row[1] for row in simrows)
        if simbytes>64*MIB:raise ValueError('Simulation helpers exceed small RAM0 profile budget')
        simlist=work/'simulation-list';simlist.write_text(''.join(f'{n} {size} {sha} {mode:o}\n' for n,size,sha,mode in simrows),encoding='ascii')
        ram_bytes=max(32*MIB,((COLD['ORIGINAL_RAMROOT_BYTES']+2*simbytes+16*MIB+MIB-1)//MIB)*MIB)
        if ram_bytes>=200*MIB:raise ValueError('Small RAM0 must stay below 200MiB')
        with ram0.open('r+b') as f:f.truncate(ram_bytes)
        resized=subprocess.run(['resize2fs',str(ram0)],capture_output=True,text=True,timeout=60)
        (work/'ram0-resize.log').write_text(resized.stdout+resized.stderr)
        if resized.returncode:raise RuntimeError('Small original RAM0 resize failed')
        changes={'/simulation':COLD['_link']('/dev/qemu-simulation'),'/sbin/insmod':COLD['_file'](shim),
            '/sbin/persistent-bootstrap':COLD['_file'](bootstrap),'/qemu/sony_persistent_flash.ko':COLD['_file'](module,0o600),
            '/qemu/cold-start-audit':COLD['_file'](simulation/'cold-start-audit'),
            '/qemu/create-aliases.sh':COLD['_file'](HERE/'persistent-flash/create-aliases.sh'),
            '/qemu/simulation-list':COLD['_file'](simlist,0o600),'/qemu/capacity-list':COLD['_file'](caplist,0o600),
            '/qemu/filesystem-proof':COLD['_file'](proofpath),'/qemu/proof-payload':COLD['_file'](payload_path,0o600)}
        for name,size,sha,mode in simrows:changes['/qemu-input/simulation/'+name]=COLD['_file'](simulation/name,mode)
        for path in list(changes):COLD['_parents'](changes,path)
        _,ram_after=COLD['_edit_image'](ram0,scratch,changes,overlay);COLD['scripts'](ram_after,COLD['RAM_SCRIPTS'])
        for name,node in ram_before['entries'].items():
            if name not in changes and ram_after['entries'].get(name)!=node:raise ValueError('Unintended original RAM0 modification '+name)
        if any(p.startswith('/qemu-input/partitions') for p in ram_after['entries']):raise ValueError('RAM0 must contain no partition images')
        COLD['recheck'](inputs)
        result=dict(schema=1,profile=PROFILE,source=disk_source,helper_source_class=source['source'],
            helper_partition_images_used=False,instance=str(instance),**identity,
            instance_wire=str(wire),prepared_runtime_analysis=str(runtime),
            ram0_image=str(ram0),ram0_bytes=ram_bytes,ram0_sha256=COLD['digest'](ram0),
            cold_cmdline=f'root=/dev/ram0 rootfstype=ext2 rw noatime init=/sbin/persistent-bootstrap ramdisk_size={ram_bytes//1024} persistent.profile={PROFILE}',
            original_ram0=dict(source_partition='3',bytes=COLD['ORIGINAL_RAMROOT_BYTES'],sha256=COLD['ORIGINAL_RAMROOT_SHA']),
            script_identity=dict(ram0=ram_identity,p7=p7_identity),native_elf_identity=identities,expected_im=COLD['expected_im'](),
            block_module=dict(path=str(work/'sony_persistent_flash.ko'),sha256=COLD['digest'](module),vermagic='4.9.337-scel+ SMP preempt mod_unload aarch64'),
            qemu_properties={'type':'sony-persistent-flash','backend-fd':'leased inherited FD','geometry':'/instance/persistent-geometry.bin','expected-dev':'fstat leased FD','expected-ino':'fstat leased FD','mmio_base':'0x0b000000','mmio_size':4096},
            simulation_dir=str(simulation),simulation_bytes=simbytes,excluded_helpers=['media-template.fat','attach-loop'],
            adapter=adaptation,partition_images_in_ram0=0,capacity_checks=dict(capacity),inputs=inputs,
            proof=dict(token=token,folder='a7pf-'+token,payload_bytes=len(payload),payload_sha256=hashlib.sha256(payload).hexdigest()),
            memory=dict(minimum_managed_ram_bytes=ram_bytes+simbytes+256*MIB),
            bootin_policy='runtime bind original ELF into moved devtmpfs before wrapper bind; p15 not written',
            original_init_helper_init2_app_unchanged=True,build_verified=True,capture_verified=False,wbi_resume_verified=False,
            private_p5_official_anchor_match=False,cp_ready_verified=False,
            guest_evidence={k:None for k in ('module_loaded','capacities','p7_mounted','filesystem_restart','original_init','pivot_chroot','init2','appfw')})
        save(output/'manifest.json',result);return result
    except BaseException as e:
        save(output/'failure.json',failure(e,profile=PROFILE,build_verified=False,work=str(work)))
        raise


def launch_script(text,manifest):
    """Reuse the raw-ext2/high-DDR adapter, then replace only its profile guard."""
    if manifest.get('profile')!=PROFILE or manifest.get('build_verified') is not True:raise ValueError('Expected persistent boot manifest')
    fake=dict(manifest,profile=COLD['PROFILE'],cold_cmdline=manifest['cold_cmdline']+' coldchain.profile='+COLD['PROFILE'])
    text=COLD['launch_script'](text,fake)
    text=text.replace(' coldchain.profile='+COLD['PROFILE'],'')
    text=text.replace('coldchain.profile=*|fullsystem.bootin-handoff=*',
                      'coldchain.profile=*|persistent.profile=*|persistent.proof=*|fullsystem.bootin-handoff=*')
    text=text.replace('# COLD_INIT_CHAIN_RAW_EXT2:', '# PERSISTENT_FLASH_RAW_EXT2:')
    old='  bwrap --unshare-all --die-with-parent --new-session --clearenv \\\n'
    if text.count(old)!=1:raise ValueError('Unsupported bwrap entrypoint')
    text=text.replace(old,old.rstrip('\n')+'\n    "${persistent_fd_options[@]}" \\\n    --bind "$PERSISTENT_INSTANCE" /instance \\\n    --setenv QEMU_A7PF_PROFILE persistent-flash-cold-v1 \\\n    --setenv QEMU_A7PF_FD "$PERSISTENT_DISK_FD" \\\n    --setenv QEMU_A7PF_DEV "$PERSISTENT_DISK_DEV" \\\n    --setenv QEMU_A7PF_INO "$PERSISTENT_DISK_INO" \\\n')
    guard='''
# Parent supplies a prebound leased FD; never open/recreate the disk here.
if [[ "${QEMU_PREPARE_ONLY:-0}" != 1 ]]; then
  [[ "${PERSISTENT_INSTANCE:-}" == /* && "${PERSISTENT_DISK_FD:-}" =~ ^[0-9]+$ && "$PERSISTENT_DISK_FD" -ge 3 && "${PERSISTENT_DISK_DEV:-}" =~ ^[0-9]+$ && "${PERSISTENT_DISK_INO:-}" =~ ^[0-9]+$ ]] || exit 2
fi
persistent_fd_options=()
if [[ "${QEMU_PREPARE_ONLY:-0}" != 1 ]] && bwrap --help | grep -q -- --preserve-fds; then
  persistent_fd_options=(--preserve-fds "$((PERSISTENT_DISK_FD-2))")
fi
'''
    text=text.replace('set -euo pipefail\n','set -euo pipefail\n'+guard,1)
    anchor='if [[ "${QEMU_PREPARE_ONLY:-0}" == 1 ]]; then'
    if text.count(anchor)!=1:raise ValueError('Unsupported board prepare entrypoint')
    patch='python3 - "$output_dir/virt.dtb" "$project_dir/sources/qemu-tools/usr/lib/libfdt.so.1" <<\'PERSISTENT_DTB\'\n'+DTB_PATCH+'PERSISTENT_DTB\n'
    return text.replace(anchor,patch+anchor,1)


def prepare_launch(prepared_runtime_analysis,manifest,output,*,qemu_build=None,proof=None,camera_profile='strict'):
    if proof not in (None,'write','read'):raise ValueError('Unknown proof phase')
    runtime=COLD['plain'](prepared_runtime_analysis,directory=True)
    camera=runpy.run_path(str(HERE/'persistent-camera-profile.py'))['expand'](camera_profile,runtime)
    if proof is not None and camera_profile!='strict':raise ValueError('Filesystem proof must use strict camera profile')
    output=fresh_output(output,runtime,manifest['instance'])
    try:
        identity=firmware_contract(manifest)
        kernel=current_kernel_binding(manifest['actual_kernel'])
        if COLD['digest'](manifest['ram0_image'])!=manifest['ram0_sha256']:raise ValueError('Built small RAM0 SHA drift')
        COLD['recheck']([r for r in manifest['inputs'] if r['role']!='builder-source'])
        if proof is not None:
            manifest=dict(manifest,cold_cmdline=manifest['cold_cmdline']+' persistent.proof='+proof)
        template=COLD['plain'](runtime/'qemu-kernel-probe.sh');text=launch_script(template.read_text(),manifest)
        analysis=output/'runtime/analysis';analysis.mkdir(parents=True)
        sources=(runtime.parent/'sources').resolve(strict=True);(analysis.parent/'sources').symlink_to(sources,target_is_directory=True)
        assets=['boot-handoff.bin','boards/virt-four.dtb','unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt']
        bindings=[COLD['binding'](template,'board-template'),kernel]
        for row in camera['source_bindings']:
            bound=COLD['binding'](row['path'],row['role'])
            identical('functional camera source '+row['path'],row['sha256'],bound['sha256'])
            bindings.append(bound)
        installed=[]
        for name in assets:
            row=COLD['binding'](runtime/name,'launch-asset');bindings.append(row);COLD['clone'](runtime/name,analysis/name,row['sha256'])
            installed.append(COLD['binding'](analysis/name,'installed-launch-asset'))
        COLD['clone'](Path(kernel['path']),analysis/KERNEL_ASSET,kernel['sha256'])
        installed.append(COLD['binding'](analysis/KERNEL_ASSET,'installed-disk-kernel'))
        script=analysis/'qemu-kernel-persistent.sh';script.write_text(text);script.chmod(0o700)
        qemu_build=Path(qemu_build) if qemu_build else DEFAULT_BUILD/'production/build'
        binary=COLD['plain'](qemu_build/'qemu-system-aarch64')
        production_path=COLD['plain'](qemu_build.parent/'qemu-result.json')
        bindings.extend(COLD['binding'](path,'production-qemu-input') for path in (binary,production_path))
        production=json.loads(production_path.read_text())
        if production.get('status')!='compiled' or production.get('board_profile')!=PROFILE or production.get('test_fixture_only') is not False or COLD['digest'](binary)!=production.get('qemu_binary_sha256'):
            raise ValueError('Expected matching compiled production persistent board, no fixture fallback')
        env=dict(PATH=os.defpath,LC_ALL='C',PYTHONDONTWRITEBYTECODE='1',QEMU_UI_LIVE='1',QEMU_OUTPUT_DIR=str(output/'run'),
            QEMU_TIMEOUT_SECONDS='0',QEMU_FULL_BOOT_SHIM='1',QEMU_FULL_SMP='4',QEMU_ARCH_CNTFRQ='2000000',QEMU_FULL_USB_INIT='original',QEMU_FULL_USB_PLATFORM='full',QEMU_FULL_USB_CONTROLLER='upstream-host',
            QEMU_TCG_THREAD='single',SONY_TIMER_MODEL='1',SONY_DMM_SERVICE='1',MENU_NATIVE_WINDOW='1',QEMU_NATIVE_DISPLAY='none',
            QEMU_FULL_ADAPTER_DIR=str(HERE),QEMU_TRACE_FLAGS='guest_errors,unimp',QEMU_SYSTEM_DIR=str(qemu_build.resolve()))
        env.update(camera['environment'])
        if camera['cmdline']:env['QEMU_EXTRA_CMDLINE']=' '.join(camera['cmdline'])
        command=['bash',str(script),'4096',str(analysis/'boards/virt-four.dtb'),'1','1',manifest['ram0_image']]
        with (output/'prepare.stdout').open('x') as out,(output/'prepare.stderr').open('x') as err:
            r=subprocess.run(command,env={**env,'QEMU_PREPARE_ONLY':'1'},stdin=subprocess.DEVNULL,stdout=out,stderr=err,timeout=55)
        if r.returncode:raise RuntimeError('Persistent board preparation failed; inspect prepare.stderr')
        cmdline=(output/'run/cold-cmdline.txt').read_text().strip()
        if 'rdinit=' in cmdline or 'coldchain.profile=' in cmdline or 'persistent.profile='+PROFILE not in cmdline:raise ValueError('Wrong persistent raw ext2 kernel command line')
        if '__boottime_sony_usb_init' in cmdline:raise ValueError('Original USB aggregate init must remain enabled')
        dtb=output/'run/virt.dtb'
        COLD['recheck'](bindings+installed)
        COLD['recheck']([r for r in manifest['inputs'] if r['role']!='builder-source'])
        installed.extend(COLD['binding'](path,'prepared-launch-asset') for path in
            (Path(manifest['ram0_image']),dtb,output/'run/cold-cmdline.txt'))
        result=dict(schema=1,profile=PROFILE,source=manifest['source'],instance=manifest['instance'],command=command,env=env,
            **identity,identity_failure_dir=str(output),launch_inputs=installed,
            script=str(script),script_sha256=COLD['digest'](script),runtime_analysis=str(analysis),dtb=str(dtb),dtb_sha256=COLD['digest'](dtb),
            cmdline=cmdline,cold_cmdline=manifest['cold_cmdline'],cmdline_file=str(output/'run/cold-cmdline.txt'),
            qmp_socket=str(output/'run/qmp.sock'),qmp_parent=str(output/'run'),qemu_binary=str(binary),qemu_sha256=COLD['digest'](binary),
            proof=proof,camera_profile=camera_profile,camera_profile_contract=camera,template_inputs=bindings,guest_started=False,owner_policy='leased_launch context must outlive normal QMP quit and process wait',
            bwrap_fd_policy='--preserve-fds when supported; bubblewrap 0.13 preserves subprocess pass_fds by default; tested with real sandbox',
            launch_adaptations=dict(raw_ext2_ram0=True,original_usb_aggregate_init=True,usb_platform_resources='full',usb_controller='upstream-host',guest_ddr_bytes=0x200000000,counter_hz=2000000,
                                   initrd_load_address=0x440000000,mmio_base=0x0b000000,physical_storage_compatibility=False))
        save(output/'launch.json',result);return result
    except BaseException as e:
        save(output/'failure.json',failure(e,guest_started=False));raise


@contextmanager
def leased_launch(launch):
    """Yield Popen kwargs while retaining disk lock. Caller registers started child.

    child = Popen(...); binding['children'].append(child). On exceptional exit the
    lease stays held while each registered owner runs; no timeout or kill fallback.
    """
    with DISK['lease'](launch['instance']) as leased:
        try:
            verify_firmware(leased,launch)
            identical('prepared launch script SHA256',launch['script_sha256'],COLD['digest'](launch['script']))
            identical('production QEMU SHA256',launch['qemu_sha256'],COLD['digest'](launch['qemu_binary']))
            current_kernel_binding(launch['actual_kernel'])
            for row in launch['template_inputs']+launch['launch_inputs']:
                identical('launch asset '+row['path'],row,COLD['binding'](row['path'],row['role']))
        except BaseException as error:
            if launch.get('identity_failure_dir'):
                directory=COLD['plain'](launch['identity_failure_dir'],directory=True)
                save(directory/('prelaunch-failure-'+secrets.token_hex(6)+'.json'),failure(error,guest_started=False))
            raise
        st=os.fstat(leased['fd']);env={**launch['env'],'PERSISTENT_INSTANCE':str(leased['path']),
            'PERSISTENT_DISK_FD':str(leased['fd']),'PERSISTENT_DISK_DEV':str(st.st_dev),'PERSISTENT_DISK_INO':str(st.st_ino)}
        children=[]
        binding=dict(launch,command=launch['command'],env=env,pass_fds=(leased['fd'],),children=children,fd=leased['fd'])
        try:yield binding
        finally:
            # Never release the lease while a registered VM owner is still live.
            for child in children:
                if child.poll() is None:child.wait()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance',type=Path,required=True)
    parser.add_argument('--runtime-analysis',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.instance,args.runtime_analysis,args.output),indent=2))
