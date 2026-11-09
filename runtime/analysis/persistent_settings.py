"""Reset only the stopped virtual settings volume; preserve firmware, SD and history."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

import persistent_storage as storage

PENDING='settings-reset-pending.json'


def require_complete(instance):
    if os.path.lexists(Path(instance)/PENDING):
        raise ValueError('内部盘有未完成的配置复位；保留前像并先核恢复事务')


def _outside(fd, partition):
    digest=hashlib.sha256()
    for start,end in ((0,partition['offset']),
                      (partition['offset']+partition['bytes'],os.fstat(fd).st_size)):
        for offset in range(start,end,storage.disk.CHUNK):
            count=min(storage.disk.CHUNK,end-offset);data=os.pread(fd,count,offset)
            if len(data)!=count:raise OSError('Short read outside the settings volume')
            digest.update(data)
    return digest.hexdigest()


def _copy(source, target, count, target_offset=0, source_offset=0):
    for offset in range(0,count,storage.disk.CHUNK):
        size=min(storage.disk.CHUNK,count-offset);data=os.pread(source,size,source_offset+offset)
        if len(data)!=size or os.pwrite(target,data,target_offset+offset)!=size:
            raise OSError('Short settings partition copy')
    os.fsync(target)


def reset(instance, commit_configuration):
    """Commit an official p2 image and the caller's logical reset under the disk lease."""
    instance=Path(instance).absolute()
    require_complete(instance)
    factory=instance.parent/'factory'
    fd=storage.disk.SECURE_OPEN(factory/'manifest.json')
    try:
        if os.fstat(fd).st_size>1024**2:raise ValueError('Factory reset manifest exceeds the bound')
        raw=os.pread(fd,os.fstat(fd).st_size,0);manifest=json.loads(raw)
    finally:os.close(fd)
    marker=factory/'FACTORY-IMAGES-COMPLETE'
    check=storage.disk.SECURE_OPEN(marker)
    try:completed=os.read(check,65).decode().strip()
    finally:os.close(check)
    if completed!=hashlib.sha256(raw).hexdigest() or manifest.get('bodydata_sha256')!=storage.PACKAGE_SHA:
        raise ValueError('Configuration reset requires the verified official factory manifest')
    records=[row for row in manifest.get('images',[]) if row.get('name')=='nflasha2.img']
    if len(records)!=1:raise ValueError('Missing exact official settings volume')
    record=records[0];name=record.get('file',record['name'])
    if Path(name).name!=name:raise ValueError('Factory settings image must be a basename')
    source=storage.disk.SECURE_OPEN(factory/name)
    try:
        before_source=storage.disk.stamp(source)
        if before_source[2]!=record['bytes'] or storage.disk.hashed(source)!=record['sha256']:
            raise ValueError('Official settings image changed')
        with storage.instance_lease(instance) as leased:
            require_complete(instance)
            partitions=[p for p in leased['geometry']['slices'] if p['id']=='nflasha2']
            initial=[p for p in leased['state']['source_images'] if p['name']=='nflasha2.img']
            if (len(partitions)!=1 or len(initial)!=1 or partitions[0]['bytes']!=record['bytes']
                    or initial[0]['sha256']!=record['sha256']):
                raise ValueError('Official reset image differs from this instance factory settings')
            part=partitions[0]
            if not (0<part['bytes']<=128*1024**2 and 512<=part['offset']
                    and part['offset']+part['bytes']<=os.fstat(leased['fd']).st_size):
                raise ValueError('Settings partition is outside the verified disk bounds')
            free=os.statvfs(instance)
            if free.f_bavail*free.f_frsize<part['bytes']+64*1024**3:
                raise ValueError('Configuration reset needs its complete before-image plus 64GiB reserve')
            archive=instance/'configuration-resets'
            if archive.is_symlink():raise ValueError('Symlink settings recovery archive')
            archive.mkdir(mode=0o700,exist_ok=True)
            checked=storage.disk.SECURE_OPEN(archive,directory=True);os.close(checked)
            directory=Path(tempfile.mkdtemp(prefix='reset-',dir=archive))
            backup=directory/'setting-before.img';out=os.open(backup,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            try:_copy(leased['fd'],out,part['bytes'],source_offset=part['offset'])
            finally:os.close(out)
            original=storage.disk.hashed(leased['fd'],part['offset'],part['bytes'])
            if storage.sha(backup)!=original:raise OSError('Settings before-image readback differs')
            outside=_outside(leased['fd'],part)
            state=dict(schema='a7c2-persistent-settings-reset-v1',state='prepared',before=str(backup),
                       before_sha256=original,official_sha256=record['sha256'],partition=part,
                       outside_sha256=outside,firmware_and_sd_reset=False)
            journal=instance/PENDING;storage._save(journal,state);committed=False
            try:
                _copy(source,leased['fd'],part['bytes'],target_offset=part['offset'])
                if (storage.disk.hashed(leased['fd'],part['offset'],part['bytes'])!=record['sha256']
                        or _outside(leased['fd'],part)!=outside or storage.disk.stamp(source)!=before_source):
                    raise OSError('Configuration reset scope/content readback differs')
                state['state']='disk-verified';storage._save(journal,state)
                configuration=commit_configuration();committed=True
                state.update(state='committed',configuration=configuration,settings_partition_readback_verified=True,
                             other_disk_bytes_unchanged=True,original_before_image_retained=True)
                storage._save(directory/'result.json',state);journal.unlink()
                return state
            except BaseException as error:
                state['error']=type(error).__name__+': '+str(error)
                if not committed:
                    try:
                        old=storage.disk.SECURE_OPEN(backup)
                        try:_copy(old,leased['fd'],part['bytes'],target_offset=part['offset'])
                        finally:os.close(old)
                    except BaseException as rollback_error:
                        state.update(state='recovery-required',rollback_error=str(rollback_error),rollback_verified=False)
                        storage._save(journal,state);storage._save(directory/'result.json',state)
                        raise
                    restored=(storage.disk.hashed(leased['fd'],part['offset'],part['bytes'])==original
                              and _outside(leased['fd'],part)==outside)
                    state.update(state='rolled-back' if restored else 'recovery-required',rollback_verified=restored)
                    storage._save(journal,state);storage._save(directory/'result.json',state)
                    if restored:journal.unlink()
                raise
    finally:os.close(source)
