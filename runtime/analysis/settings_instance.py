"""Bind verified original snapshots to the existing leased generation store."""
import hashlib
import os
from pathlib import Path
import stat
import setting_store

from settings_checkpoint import inspect_backup,SIZE


def default_instance(root):
    """Create the one default private instance without replacing existing state."""
    root=Path(root).absolute()
    with setting_store._directory(root,create=True) as parent:
        try:
            os.mkdir('default',0o700,dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
    path=root/'default'
    with setting_store._directory(path):pass
    return path


def load_for_boot(token,firmware_sha):
    """Return validated bytes or explicit seed/reset status, never a silent fallback."""
    current=token.load(firmware_sha)
    if current is None:
        return {'state':'new','generation':None,'data':None}
    if current['state']=='reset':
        return {'state':'reset','generation':current['generation'],'data':None}
    inspected=inspect_backup(current['data'])
    if inspected['sha256']!=current['sha256']:
        raise ValueError('Instance record and validated Backup differ')
    return {**inspected,'state':'backup','generation':current['generation'],'data':current['data']}


def stage_restore(source,expected_sha,base_cpio,run):
    """Create a run-private seed derivative from a validated immutable generation."""
    from firmware_overlay import build_overlay_initramfs
    source=Path(source)
    if source.name!='backup.bin':raise ValueError('Immutable generation backup.bin required')
    with setting_store._directory(source.parent) as parent:
        data=setting_store._read(parent,source.name,SIZE)
    inspected=inspect_backup(data)
    if inspected['sha256']!=expected_sha:raise ValueError('Restored generation SHA differs')
    run=Path(run);overlay=run/'settings-restore-input'
    overlay.mkdir(mode=0o700)
    (overlay/'seed-setting').mkdir(mode=0o700)
    for path in (overlay/'seed-backup.bin',overlay/'seed-setting/Backup.bin'):
        with path.open('xb') as stream:stream.write(data)
        path.chmod(0o600)
    output=run/'settings-initramfs.cpio'
    manifest=build_overlay_initramfs(base_cpio,overlay,output)
    return output,manifest


def publish_snapshot(token,run,result,firmware_sha,expected_generation):
    """Publish only the explicit original transport result under the run lease."""
    token.check()
    if not(result.get('ok') is True and result.get('language_date_consistency_verified') is True
           and result.get('file')=='SETTING/Backup.bin'):
        raise ValueError('Original verified settings snapshot required')
    run=Path(run)
    directory=run/'SETTING'
    if directory.is_symlink():raise ValueError('Snapshot directory cannot be a symlink')
    fd=os.open(directory/'Backup.bin',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC)
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=SIZE:
            raise ValueError('Exact ordinary Backup file required')
        chunks=[];remaining=SIZE+1
        while remaining:
            piece=os.read(fd,min(remaining,1024*1024))
            if not piece:break
            chunks.append(piece);remaining-=len(piece)
        after=os.fstat(fd)
        if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
            raise ValueError('Snapshot changed during publication read')
        data=b''.join(chunks)
    finally:
        os.close(fd)
    inspected=inspect_backup(data)
    if not(inspected['sha256']==result.get('guest_sha256')==result.get('sha256')
           and inspected['language']==result.get('language')
           and inspected['date_format']==result.get('date_format')):
        raise ValueError('Original guest and host settings evidence disagree')
    published=token.commit(data,firmware_sha,expected_generation,guest_sha256=result['guest_sha256'])
    return {k:v for k,v in published.items() if k!='data'}
