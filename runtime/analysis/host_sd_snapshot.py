"""Snapshot a quiesced host-backed card, never copy256GB through guest RAM."""
import hashlib
import os
import subprocess

from host_sd import TOTAL
from sd_transport import identity

MAX_DATA=4*1024**3
MAX_EXTENTS=65536
BLOCK=4*1024**2


def snapshot(lease, *, quiesce, guest_sync):
    """Caller owns lease and flush/STOP/recovery; this function never resumes the guest."""
    result=dict(ok=False,scope='quiesced host-backed SD snapshot, not camera media acceptance',
                bytes=TOTAL,card_published=False,full_logical_sha256_verified=False)
    result['quiesce']=quiesce()
    if not isinstance(result['quiesce'],dict) or result['quiesce'].get('owner_stopped') is not True:
        raise ValueError('Original filesystem flush/owner STOP must be confirmed')
    sync=guest_sync()
    if type(sync) is not bytes or len(sync)>1024*1024:
        raise ValueError('Guest block sync result must be bounded original bytes')
    lines=sync.replace(b'\r\n',b'\n').split(b'\n')
    marker=b'HOST_SD_BLOCK_SYNC bytes=256000000000 fsync_rc=0 '
    if sum(line.startswith(marker) and line.endswith(b'no_data_writes=1') for line in lines)!=1:
        raise ValueError('Real guest block fsync not confirmed')
    result['guest_block_sync_confirmed']=True
    fd=lease['fd']
    before=os.fstat(fd)
    if before.st_size!=TOTAL or (before.st_dev,before.st_ino)!=(lease['device'],lease['inode']):
        raise ValueError('Pinned host SD identity changed')
    os.fsync(fd)
    # Sparse extent digest has a distinct name and binds size/offset/length/content;
    # it is explicitly not a whole logical256GB SHA256.
    cursor=data=0;extents=[];digest=hashlib.sha256(b'HOST-SD-SPARSE-V1\0'+str(TOTAL).encode()+b'\0')
    while cursor<TOTAL:
        try:start=os.lseek(fd,cursor,os.SEEK_DATA)
        except OSError as error:
            import errno
            if error.errno==errno.ENXIO:break
            raise
        end=os.lseek(fd,start,os.SEEK_HOLE)
        if not cursor<=start<end<=TOTAL or len(extents)>=MAX_EXTENTS or end-start>MAX_DATA-data:
            raise ValueError('Sparse host map exceeds bounds or data limit; no silent truncation')
        data+=end-start;part=hashlib.sha256();offset=start
        digest.update(start.to_bytes(8,'little')+(end-start).to_bytes(8,'little'))
        while offset<end:
            count=min(BLOCK,end-offset);raw=os.pread(fd,count,offset)
            if len(raw)!=count:raise ValueError('Host card short read')
            digest.update(raw);part.update(raw);offset+=count
        extents.append(dict(offset=start,length=end-start,sha256=part.hexdigest()))
        cursor=end
    result.update(sparse_manifest_sha256=digest.hexdigest(),extents=extents,
                  data_bytes=data,allocated_bytes=before.st_blocks*512)
    # Read-only descriptor on the pinned inode, no pathname reopen or write/repair flags.
    readonly=os.open(f'/proc/self/fd/{fd}',os.O_RDONLY|os.O_CLOEXEC)
    try:
        checked=subprocess.run(['fsck.fat','-n',f'/proc/self/fd/{readonly}'],pass_fds=(readonly,),
                                capture_output=True,timeout=90)
    finally:os.close(readonly)
    result.update(fsck_rc=checked.returncode,fsck_output=(checked.stdout+checked.stderr).decode(errors='replace'))
    if identity(before)!=identity(os.fstat(fd)):
        raise ValueError('Host card changed while quiesced')
    if checked.returncode:
        result['error']='Strict readonly filesystem check failed; no repair performed'
        return result
    result['ok']=True
    result['host_file_snapshot_verified']=True
    return result
