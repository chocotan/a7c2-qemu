#!/usr/bin/env python3
"""Build one persistent virtual eMMC container from read-only complete images.

The user area uses the original SDM2 label and configured partition extents.
Hardware boot0/boot1 occupy separate logical areas in the same backing file;
their container offsets are a virtual format, not physical eMMC LBAs.
"""
import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import struct

HERE = Path(__file__).resolve().parent
def secure_open(path, flags=os.O_RDONLY, *, directory=False):
    """Reject symlinks in every host path component, including the final one."""
    path = os.fspath(path)
    if not os.path.isabs(path) or any(p in ('.', '..') for p in path.split('/')):
        raise ValueError('Host path must be absolute without dot components')
    parts = [p for p in path.split('/') if p]
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('Expected ordinary host directory' if directory else 'Expected regular host file')
        result = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        if not (stat.S_ISDIR(os.fstat(result).st_mode) if directory else stat.S_ISREG(os.fstat(result).st_mode)):
            os.close(result)
            raise ValueError('Expected ordinary host directory' if directory else 'Expected regular host file')
        return result
    finally:
        os.close(fd)

SECURE_OPEN = secure_open
USER_CAPACITY = 1954545664
SECTOR, CHUNK, BOOT_BYTES = 512, 1024**2, 4*1024**2
PARTS = (1,2,3,4,5,6,7,8,10,11,12,13,15,18,22,23,30)
SCHEMA = 'a7c2-persistent-emmc-v1'


def image_name(part):
    return {7:'a7c2-rootfs.img',15:'a7c2-usr.img'}.get(part,'nflasha'+str(part)+'.img')


def stamp(fd):
    info=os.fstat(fd)
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns


def hashed(fd, offset=0, count=None):
    count=os.fstat(fd).st_size-offset if count is None else count
    result=hashlib.sha256()
    while count:
        block=os.pread(fd,min(count,CHUNK),offset)
        if not block:raise OSError('Truncated disk/source range')
        result.update(block);offset+=len(block);count-=len(block)
    return result.hexdigest()


def parse_layout(data):
    rows=[]
    for raw in data.splitlines():
        raw=raw.strip()
        if not raw or raw.startswith(b'#'):continue
        if not re.fullmatch(rb'0x[0-9a-fA-F]{8}(?:,0x[0-9a-fA-F]{8}){3}',raw):
            raise ValueError('Unsupported Sony partition configuration row')
        start,size,kind,flags=(int(v,16) for v in raw.split(b','))
        rows.append(dict(part=len(rows)+1,start_lba=start,sectors=size,type=kind,flags=flags,
                         offset=start*SECTOR,bytes=size*SECTOR))
    if len(rows)!=30 or {r['part'] for r in rows if r['bytes']}!=set(PARTS):
        raise ValueError('Expected the complete 30-entry Sony layout with 17 nonempty partitions')
    used=sorted((r for r in rows if r['bytes']),key=lambda r:r['offset'])
    if used[0]['offset']<SECTOR:raise ValueError('Partition overlaps the SDM2 label')
    for a,b in zip(used,used[1:]):
        if a['offset']+a['bytes']>b['offset']:raise ValueError('Overlapping partition geometry')
    extent=max(r['offset']+r['bytes'] for r in used)
    if extent>4*1024**3:raise ValueError('Geometry exceeds the bound for this virtual device')
    return rows,extent


def label_bytes(rows):
    header=struct.pack('<III20x',0x36343238,0x30302e32,30)
    return header+b''.join(struct.pack('<4I',r['start_lba'],r['sectors'],r['type'],r['flags']) for r in rows)


def save(path,value):
    temporary=path.with_suffix(path.suffix+'.new')
    with temporary.open('x') as stream:
        os.fchmod(stream.fileno(),0o600)
        json.dump(value,stream,indent=2,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def create(source_dir,partinf,output):
    source=Path(os.path.abspath(source_dir));config=Path(os.path.abspath(partinf));output=Path(os.path.abspath(output))
    with ExitStack() as stack:
        for directory in (source,output.parent):
            fd=SECURE_OPEN(directory,directory=True);stack.callback(os.close,fd)
        if os.path.lexists(output):raise ValueError('Instance output must be fresh; old disks are never replaced')
        manifest_fd=SECURE_OPEN(source/'manifest.json');stack.callback(os.close,manifest_fd)
        config_fd=SECURE_OPEN(config);stack.callback(os.close,config_fd)
        if os.fstat(manifest_fd).st_size>1024**2 or os.fstat(config_fd).st_size>65536:
            raise ValueError('Manifest/config size limit exceeded')
        manifest=json.loads(os.pread(manifest_fd,os.fstat(manifest_fd).st_size,0))
        config_bytes=os.pread(config_fd,os.fstat(config_fd).st_size,0)
        rows,user_bytes=parse_layout(config_bytes)
        configured_extent=user_bytes
        if user_bytes>USER_CAPACITY:raise ValueError('Official partition extent exceeds fixed model capacity')
        user_bytes=USER_CAPACITY
        if manifest.get('source')!='official-bodydata-derived':raise ValueError('Product instances require the verified official factory route')
        records=manifest.get('images',[])
        expected={image_name(p) for p in PARTS}|{'nflashaB0.img','nflashaB1.img'}
        if len(records)!=19 or {r.get('name') for r in records}!=expected:
            raise ValueError('All 19 complete source images are required')
        files={};bindings=[]
        for row in records:
            name=row.get('file',row['name'])
            if Path(name).name!=name or name in ('.','..'):raise ValueError('Image input must be a basename')
            fd=SECURE_OPEN(source/name);stack.callback(os.close,fd)
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            before=stamp(fd);sha=hashed(fd)
            if before[2]!=row['bytes'] or sha!=row['sha256']:raise ValueError('Source image identity differs: '+name)
            files[row['name']]=(fd,before,sha)
            bindings.append(dict(name=row['name'],bytes=before[2],sha256=sha))
        slices=[]
        for row in rows:
            if not row['bytes']:continue
            name=image_name(row['part']);fd,before,sha=files[name]
            if before[2]!=row['bytes']:raise ValueError('Image capacity differs from original layout: '+name)
            slices.append(dict(id='nflasha'+str(row['part']),area='user',offset=row['offset'],bytes=row['bytes'],
                               source=name,source_sha256=sha))
        for index,name in enumerate(('nflashaB0.img','nflashaB1.img')):
            if files[name][1][2]!=BOOT_BYTES:raise ValueError('Hardware boot area must be exactly 4 MiB')
            slices.append(dict(id='nflashaB'+str(index),area='boot'+str(index),offset=user_bytes+index*BOOT_BYTES,
                               bytes=BOOT_BYTES,source=name,source_sha256=files[name][2]))
        total=user_bytes+2*BOOT_BYTES
        if shutil.disk_usage(output.parent).free<total+1024**3:raise OSError('Insufficient instance disk space plus reserve')
        output.mkdir(mode=0o700)
        disk=output/'camera.emmc'
        status=dict(schema=SCHEMA,state='creating',source_class='official-bodydata-derived-virtual-factory',
                    original_sources_opened_writable=False,physical_devices_used=False)
        save(output/'creation.json',status)
        try:
            fd=os.open(disk,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);stack.callback(os.close,fd)
            os.ftruncate(fd,total)
            label=label_bytes(rows)
            if len(label)!=SECTOR or os.pwrite(fd,label,0)!=SECTOR:raise OSError('Short SDM2 label write')
            for item in slices:
                src=files[item['source']][0]
                for offset in range(0,item['bytes'],CHUNK):
                    count=min(CHUNK,item['bytes']-offset);data=os.pread(src,count,offset)
                    if len(data)!=count or os.pwrite(fd,data,item['offset']+offset)!=count:
                        raise OSError('Short partition copy: '+item['id'])
                if hashed(fd,item['offset'],item['bytes'])!=item['source_sha256']:
                    raise OSError('Disk slice readback mismatch: '+item['id'])
            for name,(src,before,sha) in files.items():
                if stamp(src)!=before or hashed(src)!=sha:raise ValueError('Source changed during creation: '+name)
            os.fsync(fd)
            if os.pread(fd,SECTOR,0)!=label:raise OSError('SDM2 label changed during creation')
            geometry=dict(schema=SCHEMA,sector_bytes=SECTOR,backing_file='camera.emmc',backing_bytes=total,
                          user_bytes=user_bytes,partition_rows=rows,slices=slices,
                          area_mapping='user then virtual boot0 and boot1 in one container; not physical boot LBAs',
                          user_capacity_basis='fixed publicly recorded ILCE-7CM2 model capacity; no physical device queried',
                          configured_user_extent_bytes=configured_extent,
                          unused_user_tail_bytes=user_bytes-configured_extent,
                          unused_tail_initialization='zero; unallocated physical tail bytes were not captured',
                          sdm2_label_sha256=hashlib.sha256(label).hexdigest())
            save(output/'geometry.json',geometry)
            initial=dict(schema=SCHEMA,generation=0,source_class='official-bodydata-derived-virtual-factory',state='stopped',
                         geometry_sha256=hashlib.sha256((output/'geometry.json').read_bytes()).hexdigest(),
                         initial_disk_sha256=hashed(fd),source_images=bindings,
                         source_manifest_sha256=hashed(manifest_fd),partinf_sha256=hashed(config_fd),
                         fixed_model_user_capacity_bytes=USER_CAPACITY,
                         normal_restart_policy='reuse this disk; never recreate it from source images',
                         firmware_baseline='official images plus explicitly new virtual factory volumes; AP/kernel identity separately checked',
                         initial_only=True,full_boot_verified=False)
            save(output/'instance.json',initial)
            lock=os.open(output/'.disk.lock',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);os.close(lock)
            status.update(state='created',disk_bytes=total,user_bytes=user_bytes,slice_readbacks_verified=19)
            save(output/'creation.json',status)
            return initial
        except BaseException as error:
            status.update(state='failed',error=type(error).__name__+': '+str(error))
            save(output/'creation.json',status)
            raise


@contextmanager
def lease(instance):
    """One writer/VM per instance; callers retain this lease through VM shutdown."""
    instance=Path(os.path.abspath(instance))
    directory=SECURE_OPEN(instance,directory=True)
    lock=SECURE_OPEN(instance/'.disk.lock',os.O_RDWR)
    disk=None
    metadata=[]
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if os.path.lexists(instance/'settings-reset-pending.json'):
            raise ValueError('内部盘有未完成的配置复位；先核恢复事务')
        disk=SECURE_OPEN(instance/'camera.emmc',os.O_RDWR)
        for name in ('geometry.json','instance.json'):
            fd=SECURE_OPEN(instance/name);metadata.append(fd)
            if os.fstat(fd).st_size>1024**2:raise ValueError('Instance metadata exceeds budget')
        geometry=json.loads(os.pread(metadata[0],os.fstat(metadata[0]).st_size,0))
        state=json.loads(os.pread(metadata[1],os.fstat(metadata[1]).st_size,0))
        if geometry.get('schema')!=SCHEMA or state.get('schema')!=SCHEMA:
            raise ValueError('Unknown camera disk instance')
        if hashed(metadata[0])!=state['geometry_sha256']:
            raise ValueError('Camera geometry was changed')
        if os.fstat(disk).st_size!=geometry['backing_bytes']:raise ValueError('Camera backing capacity changed')
        if os.pread(disk,SECTOR,0)[:8]!=b'82462.00':raise ValueError('Camera SDM2 label is invalid')
        yield dict(fd=disk,geometry=geometry,state=state,path=instance)
    finally:
        if disk is not None:os.close(disk)
        for fd in metadata:os.close(fd)
        os.close(lock);os.close(directory)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--partinf',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(create(args.source,args.partinf,args.output),indent=2))


if __name__=='__main__':main()
