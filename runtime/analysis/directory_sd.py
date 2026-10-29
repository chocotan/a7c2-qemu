"""Exclusive host directory lease; the directory itself is the virtual card content."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from sd_transport import directory

TOTAL_SECTORS = 500_000_000
TOTAL = TOTAL_SECTORS * 512


@contextmanager
def directory_lease(root):
    root = Path(root).absolute()
    root.mkdir(mode=0o700, exist_ok=True)
    with directory(root.parent) as parent:
        lock_name = '.' + root.name + '.lock'
        lock = os.open(lock_name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600, dir_fd=parent)
        fd = None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
            before = os.fstat(fd)
            named = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
            if ((before.st_dev, before.st_ino) != (named.st_dev, named.st_ino) or
                    before.st_uid != os.geteuid() or before.st_mode & 0o022):
                raise ValueError('Directory SD requires an owned, non-world/group-writable directory')
            if os.fstatvfs(fd).f_bavail * os.fstatvfs(fd).f_frsize < 1024**3:
                raise ValueError('At least 1GiB host headroom is required')
            yield dict(fd=fd, lock_fd=lock, path=str(root), bytes=TOTAL,
                       total_sectors=TOTAL_SECTORS, device=before.st_dev, inode=before.st_ino,
                       guest_attached=False, firmware_format_verified=False,
                       external_edit_during_lease_allowed=False)
            after = os.fstat(fd)
            named = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
            if ((after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or
                    (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
                raise ValueError('Directory SD inode/path changed during lease')
        finally:
            if fd is not None:
                os.close(fd)
            os.close(lock)
