"""One product-owned virtual disk; raw-initramfs AP startup remains explicit."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import tempfile

import persistent_disk as disk
from persistent_geometry import write_camera_wire
from firmware_overlay import build_overlay_initramfs

ANALYSIS=Path(__file__).resolve().parent
PRODUCT=ANALYSIS.parents[1]
PROFILE='product-single-disk-v1'
PACKAGE_SHA='eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
MODULE_SOURCE=PRODUCT/'source/persistent-flash'
MODULE_OUTPUTS=ANALYSIS/'persistent-flash-module'


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def _save(path,value):
    temporary=path.with_suffix('.new')
    with temporary.open('x') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def ensure_instance(base=None):
    from factory_images import generate
    base=Path(base or ANALYSIS/'persistent-storage').absolute()
    if '..' in base.parts or any(p.is_symlink() for p in (*base.parents,base)):
        raise ValueError('Persistent storage requires ordinary absolute directories')
    base.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=os.open(base/'.prepare.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        instance=base/'default'
        if instance.exists():
            with disk.lease(instance):pass
            return instance
        cache=ANALYSIS.parent/'bodydata-cache'/PACKAGE_SHA
        factory=base/'factory'
        if not factory.exists():generate(cache,factory,ANALYSIS/'vendor/fwtool-sdk')
        manifest=json.loads((factory/'manifest.json').read_bytes())
        if (factory/'FACTORY-IMAGES-COMPLETE').read_text().strip()!=sha(factory/'manifest.json') or manifest.get('bodydata_sha256')!=PACKAGE_SHA:
            raise ValueError('Persistent factory manifest or input differs')
        disk.create(factory,cache/'firmware-root/0300_partconf/partinf.conf',instance)
        return instance
    finally:os.close(lock)


def module_file():
    manifest=MODULE_SOURCE/'abi-manifest.json'
    build=MODULE_OUTPUTS/('build-'+sha(manifest)[:16])
    result=build/'result.json'
    if not result.exists():
        if build.exists():raise ValueError('Preserve failed persistent module build; select a fresh output')
        subprocess.run([sys.executable,'-B',str(MODULE_SOURCE/'build.py'),'--source',str(MODULE_SOURCE),'--output',str(build)],check=True)
    proof=json.loads(result.read_bytes());path=build/'sony_persistent_flash.ko'
    if proof.get('source_manifest_sha256')!=sha(manifest) or proof.get('module',{}).get('sha256')!=sha(path):
        raise ValueError('Persistent module differs from checked product sources')
    for name,row in json.loads(manifest.read_bytes())['files'].items():
        source=MODULE_SOURCE/name
        if source.is_symlink() or source.stat().st_size!=row['bytes'] or sha(source)!=row['sha256']:
            raise ValueError('Persistent module source changed: '+name)
    return path


def binary_environment():
    proof_path=PRODUCT/'source/persistent-flash-build.json'
    proof=json.loads(proof_path.read_bytes())
    binary=ANALYSIS.parent/'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'
    if proof.get('binary_sha256')!=sha(binary) or proof.get('profile')!='persistent-flash-cold-v1' or proof.get('mmio_base')!='0x0b010000':
        raise ValueError('Rebuild product QEMU with persistent flash support')
    for name,digest in proof['source_files'].items():
        if sha(MODULE_SOURCE/name)!=digest:raise ValueError('Persistent QEMU model source changed')
    if sha(MODULE_SOURCE/'stage.py')!=proof['stage_source_sha256']:raise ValueError('Persistent QEMU staging source changed')
    return dict(QEMU_SYSTEM_DIR=str(binary.parent),QEMU_SYSTEM_BINARY=binary.name)


@contextmanager
def instance_lease(instance):
    with disk.lease(instance) as leased:
        wire=Path(instance)/'persistent-geometry.bin'
        with tempfile.TemporaryDirectory(prefix='geometry-',dir=instance) as temporary:
            candidate=Path(temporary)/'geometry.bin';write_camera_wire(leased['geometry'],candidate)
            if wire.exists():
                if wire.is_symlink() or sha(wire)!=sha(candidate):raise ValueError('Persistent wire geometry changed')
            else:os.link(candidate,wire)
        if leased['geometry']['user_bytes']!=1954545664:raise ValueError('Exact model capacity required')
        yield leased


def inherited_environment(leased):
    info=os.fstat(leased['fd'])
    if not stat.S_ISREG(info.st_mode) or info.st_size!=leased['geometry']['backing_bytes']:
        raise ValueError('Persistent inherited descriptor is not the instance disk')
    return dict(binary_environment(),A7C2_STORAGE_PROFILE=PROFILE,A7C2_EMMC_INSTANCE=str(leased['path']),
                A7C2_EMMC_FD=str(leased['fd']),A7C2_EMMC_DEV=str(info.st_dev),A7C2_EMMC_INO=str(info.st_ino))


def inherited_fd(environment):
    if environment.get('A7C2_STORAGE_PROFILE') is None:return None
    if environment['A7C2_STORAGE_PROFILE']!=PROFILE:raise ValueError('Unknown persistent storage profile')
    values=[]
    for name in ('A7C2_EMMC_FD','A7C2_EMMC_DEV','A7C2_EMMC_INO'):
        value=environment.get(name,'')
        if not value.isascii() or not value.isdigit():raise ValueError('Invalid inherited persistent identity')
        values.append(int(value))
    fd,device,inode=values
    if fd<3:raise ValueError('Persistent descriptor must be parent-owned')
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or (info.st_dev,info.st_ino)!=(device,inode):raise ValueError('Persistent descriptor identity changed')
    instance=Path(environment['A7C2_EMMC_INSTANCE']).absolute()
    if (instance/'camera.emmc').is_symlink() or (instance/'camera.emmc').stat().st_ino!=inode:
        raise ValueError('Persistent path does not match inherited descriptor')
    return fd


def augment_initramfs(base,output,overwrite=None,restore_path=None,restore_selection=None):
    folder=Path(tempfile.mkdtemp(prefix='persistent-adapter-',dir=Path(output).parent));root=folder/'overlay';simulation=root/'simulation';simulation.mkdir(parents=True)
    for name,source in (('sony_persistent_flash.ko',module_file()),('persistent-libIMDB.so',ANALYSIS/'menu-root/usr/lib/libIMDB.so')):
        destination=simulation/name
        with source.open('rb') as stream,destination.open('xb') as target:
            import shutil
            shutil.copyfileobj(stream,target,1024*1024)
        destination.chmod(0o600)
        if sha(source)!=sha(destination):raise ValueError('Persistent runtime helper readback differs')
    entries=list((overwrite or {}).get('entries',[]))
    if restore_path:
        from firmware_development import guest_path
        guest_path(restore_path)
        source=ANALYSIS/'menu-root'/restore_path.lstrip('/')
        entries=[dict(path=restore_path.lstrip('/'),source=str(source),new_sha256=sha(source),size=source.stat().st_size,mode=source.stat().st_mode)]
    apply=['#!/bin/busybox sh','set -e']
    for index,entry in enumerate(entries):
        from firmware_development import guest_path
        relative=entry['path'];guest_path('/'+relative)
        if not relative.startswith('usr/') or '..' in Path(relative).parts:raise ValueError('Persistent file tests currently require a target under /usr')
        source=Path(entry['source']);target=simulation/('persistent-test-'+str(index));target.write_bytes(source.read_bytes());target.chmod(0o600)
        if sha(target)!=entry['new_sha256'] or target.stat().st_size!=entry['size']:raise ValueError('Persistent file test source changed')
        identity=hashlib.sha256((relative+entry['new_sha256']+str(restore_selection or source)).encode()).hexdigest();marker='/log/qemu/filetest-'+identity+'.applied'
        apply += ['if [ ! -f '+marker+' ]; then','  /bin/busybox mkdir -p /log/qemu/filetest-'+identity,
                  '  if [ -f /'+relative+' ]; then /bin/busybox cp /'+relative+' /log/qemu/filetest-'+identity+'/before; /bin/busybox cmp /'+relative+' /log/qemu/filetest-'+identity+'/before; fi',
                  '  /bin/busybox mount -o remount,rw /usr',
                  '  /bin/busybox mkdir -p /'+str(Path(relative).parent),
                  '  /bin/busybox cp /simulation/persistent-test-'+str(index)+' /'+relative,
                  '  /bin/busybox chmod '+format(entry['mode']&0o777,'o')+' /'+relative,
                  '  digest=$(/usr/bin/openssl dgst -sha256 /'+relative+')',
                  '  case "$digest" in "SHA256(/'+relative+')= '+entry['new_sha256']+'"|"SHA2-256(/'+relative+')= '+entry['new_sha256']+'") ;; *) exit 1;; esac',
                  '  /bin/busybox sync','  /bin/busybox mount -o remount,ro /usr',
                  '  echo '+entry['new_sha256']+' > '+marker,'  /bin/busybox sync','fi']
    (simulation/'persistent-apply-test').write_text('\n'.join(apply)+'\n',encoding='ascii');(simulation/'persistent-apply-test').chmod(0o755)
    manifest=build_overlay_initramfs(base,root,output)
    _save(folder/'overlay.json',manifest)
    return manifest


def prepare_shutdown(serial,run):
    import re
    parameter='/sys/module/sony_persistent_flash/parameters/quiesce'
    script='( echo 1 > '+parameter+' && echo PERSISTENT_STORAGE_FREEZE_BEGIN && /bin/busybox cat '+parameter+' && echo PERSISTENT_STORAGE_FREEZE_END )'
    run=Path(run)
    try:
        raw=serial(script);(run/'persistent-shutdown.raw').write_bytes(raw)
        states=re.findall(rb'^PERSISTENT_STORAGE_FREEZE_BEGIN\r?\n([0-9]+) ([0-9]+)\r?\n(?:[ \t]*\r?\n)*PERSISTENT_STORAGE_FREEZE_END\r?$',raw,re.M)
        if states!=[(b'1',b'19')]:raise ValueError('All nineteen internal volumes did not read back frozen')
        receipt=dict(frozen_verified=True,frozen_partitions=19,original_freeze_bdev_used=True,raw_sha256=hashlib.sha256(raw).hexdigest())
        _save(run/'persistent-shutdown.json',receipt)
        return receipt
    except BaseException:
        try:
            recovery=serial('( echo 0 > '+parameter+' && /bin/busybox cat '+parameter+' )')
            (run/'persistent-shutdown-thaw.raw').write_bytes(recovery)
        except Exception as error:(run/'persistent-shutdown-thaw-error.txt').write_text(str(error)+'\n')
        raise


def mount_commands(overwrite=None):
    # This is the existing product AP route using real persistent volumes.
    # Original init/pivot_root cold-chain verification remains a separate stage.
    commands=[
        'export HOME=/ TOPRC=/etc/toprc MALLOC_OPTIONS=gfffffffff MALLOC_MMAP_THRESHOLD_=131072 MALLOC_CHECK_=3 LT_ABORTREASON=0 WBSHD=/tmp_wbshd/shared.XXXXXX',
        'insmod /simulation/sony_persistent_flash.ko mmio_base=0x0b010000 || { echo PERSISTENT_STORAGE_FAILED=module; exit 1; }',
        "for p in /sys/block/cnflasha*; do name=${p##*/}; dev=$(/bin/busybox cat \"$p/dev\"); major=${dev%:*}; minor=${dev#*:}; /bin/busybox mknod /dev/$name b $major $minor; /bin/busybox ln -s $name /dev/nflasha${name#cnflasha}; done",
        'mount -t ext2 -o ro /dev/cnflasha15 /usr || { echo PERSISTENT_STORAGE_FAILED=usr; exit 1; }',
        'mount --bind /simulation/persistent-libIMDB.so /usr/lib/libIMDB.so || { echo PERSISTENT_STORAGE_FAILED=imdb; exit 1; }',
        'mount -t vfat -o rw,nodiratime,noatime,sync,posix_attr /dev/cnflasha2 /setting || { echo PERSISTENT_STORAGE_FAILED=setting; exit 1; }',
        'mount -t vfat -o rw,nodiratime,noatime,sync,posix_attr /dev/cnflasha10 /tmp || { echo PERSISTENT_STORAGE_FAILED=tmp; exit 1; }',
        'mount -t vfat -o rw,nodiratime,noatime,sync,posix_attr,batch_sync /dev/cnflasha11 /log || { echo PERSISTENT_STORAGE_FAILED=log; exit 1; }',
        'mkdir -p /log/qemu',
        'mount --bind /tmp /etc || { echo PERSISTENT_STORAGE_FAILED=etc-alias; exit 1; }',
        'mount --bind /tmp /var || { echo PERSISTENT_STORAGE_FAILED=var-alias; exit 1; }',
        # The disk lease is exclusive and no AP has started in this new guest.
        'rm -f /tmp/rm-file.claim /tmp/headless-osd.claim /tmp/gui-model.claim',
        'rm -f /tmp/sd-flush.request /tmp/sd-hotplug.state /tmp/date-clock.ready /tmp/system-sound.ready /tmp/headless-osd-frame.bin /tmp/headless-osd-frame.bin.part /tmp/gui-model-state.bin /tmp/hdmi-format-state.bin /tmp/hdmi-photo-state.bin',
        '/simulation/persistent-apply-test || { echo PERSISTENT_STORAGE_FAILED=file-test; exit 1; }',
        'for name in menu-load.log gpe-requests.bin im.log; do rm -f /tmp/$name; ln -s /log/qemu/$name /tmp/$name; done',
        "echo PERSISTENT_STORAGE_MOUNTED; /bin/busybox cat /proc/mounts; /bin/busybox grep -E '^(Uid|Gid):' /proc/$$/status",
    ]
    selected={row['path']:row['new_sha256'] for row in (overwrite or {}).get('entries',[])}
    for relative in ('usr/bin/bootin.elf','usr/bin/im.elf','usr/lib/appFw.so','usr/lib/libInfraCrypt.so','usr/lib/libInfraCryptCore.so','usr/lib/libInfraSKD.so'):
        digest=selected.get(relative) or sha(ANALYSIS/'menu-root'/relative)
        commands+=['digest=$(/usr/bin/openssl dgst -sha256 /'+relative+') || exit 1',
                   'case "$digest" in "SHA256(/'+relative+')= '+digest+'"|"SHA2-256(/'+relative+')= '+digest+'") echo PERSISTENT_GUEST_ELF_VERIFIED path=/'+relative+' sha256='+digest+';; *) echo PERSISTENT_STORAGE_FAILED=guest-elf-'+Path(relative).name+'; exit 1;; esac']
    return commands
