"""Owned host-file SD lease: fixed decimal 256GB, never a device or guest RAM copy."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import uuid

from sd_transport import directory, regular, identity, write_file

TOTAL = 256_000_000_000


@contextmanager
def card_lease(root):
    """Hold until the owned VM exits; never repair, truncate or replace an existing card."""
    root = Path(root).absolute()
    with directory(root) as parent:
        lock = regular(parent,'.card.lock',os.O_RDWR|os.O_CREAT)
        fd = None
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            created=False
            try:
                fd=regular(parent,'card.img',os.O_RDWR)
            except FileNotFoundError:
                fd=regular(parent,'card.img',os.O_RDWR|os.O_CREAT|os.O_EXCL)
                # A failed initial creation stays invalid and is never silently repaired.
                info=os.fstatvfs(parent)
                if info.f_bavail*info.f_frsize<1024**3:
                    raise ValueError('At least 1GiB host headroom required to create the sparse card')
                os.ftruncate(fd,TOTAL);os.fsync(fd);os.fsync(parent);created=True
            before=os.fstat(fd)
            if before.st_size!=TOTAL or before.st_nlink!=1:
                raise ValueError('Host SD must be a singly-linked owned regular file of exactly256GB')
            named=os.stat('card.img',dir_fd=parent,follow_symlinks=False)
            if identity(before)!=identity(named):
                raise ValueError('Host SD inode/path changed before lease')
            yield dict(fd=fd,lock_fd=lock,path=str(root/'card.img'),bytes=TOTAL,
                       created=created,device=before.st_dev,inode=before.st_ino,
                       allocated_before=before.st_blocks*512)
            after=os.fstat(fd);named=os.stat('card.img',dir_fd=parent,follow_symlinks=False)
            if after.st_size!=TOTAL or after.st_nlink!=1 or after.st_dev!=before.st_dev or after.st_ino!=before.st_ino or identity(after)!=identity(named):
                raise ValueError('Host SD size/inode/path changed during lease')
            os.fsync(fd)
        finally:
            if fd is not None:os.close(fd)
            os.close(lock)


def main():
    root=Path(__file__).resolve().parent/'host-sd'
    root.mkdir(mode=0o700,exist_ok=True)
    with card_lease(root) as lease:
        proof={k:v for k,v in lease.items() if k not in ('fd','lock_fd')}
        proof.update(scope='host sparse raw virtual card, decimal256GB; no physical device',
                     guest_attached=False,formatted_by_camera=False,full_content_digest_verified=False)
        # Do not imply a lease remains held after this preparation-only command exits.
        proof['lease_scope']='preparation only; VM launcher must reacquire and retain lease'
        with directory(root) as parent:
            temporary='.prepared-'+uuid.uuid4().hex+'.json'
            write_file(parent,temporary,(json.dumps(proof,indent=2)+'\n').encode())
            os.replace(temporary,'prepared.json',src_dir_fd=parent,dst_dir_fd=parent)
            os.fsync(parent)
        print(json.dumps(proof,indent=2))


if __name__=='__main__':main()
