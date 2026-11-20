"""Source-only quarantine component; no launcher and no cleanup authority.

All cooperating writers must check the same pinned instance directory while
holding its existing directory flock and disk OFD. This is not a same-UID
security boundary. A retained/partial/malformed marker always blocks reuse.
"""
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import stat

NAME = 'owner-quarantine.json'
SCHEMA = 'a7c2-owner-quarantine-draft-v1'


class Rejected(RuntimeError):
    pass


def identity(info):
    return info.st_dev, info.st_ino


@dataclass(frozen=True)
class Generation:
    pid: int
    start_ticks: int
    boot_id: str

    @classmethod
    def current(cls):
        raw = Path('/proc/self/stat').read_bytes()
        return cls(os.getpid(), int(raw.rsplit(b') ', 1)[1].split()[19]),
                   Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def _lock_present(fd, kind, pid, end):
    info = os.fstat(fd)
    expected = f'{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino}'
    rows = (line.split() for line in Path(f'/proc/self/fdinfo/{fd}').read_text().splitlines()
            if line.startswith('lock:'))
    if not any(len(row) == 9 and row[2:6] == [kind, 'ADVISORY', 'WRITE', str(pid)]
               and row[6:] == [expected, '0', end] for row in rows):
        raise Rejected('required directory flock or disk OFD is absent')


def _check_inputs(directory_fd, lock_fd, disk_fd):
    directory = os.fstat(directory_fd)
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or stat.S_IMODE(directory.st_mode) != 0o700):
        raise Rejected('pinned private 0700 instance directory required')
    for name, fd in (('.disk.lock', lock_fd), ('camera.emmc', disk_fd)):
        info = os.fstat(fd)
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(named.st_mode)
                or identity(named) != identity(info) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise Rejected('leased file identity, ownership or link count changed')
        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
            raise Rejected('leased files must be opened read/write')
    _lock_present(lock_fd, 'FLOCK', os.getpid(), 'EOF')
    _lock_present(disk_fd, 'OFDLCK', -1, '0')


def refuse_unfinished(directory_fd):
    """Run on EVERY write admission under the existing instance/disk locks.

    Existence alone blocks: never parse a marker to infer a dead owner is safe.
    Permission and I/O errors propagate as refusal, never as absence.
    """
    try:
        os.stat(NAME, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise Rejected('unfinished quarantine marker exists; preserve and refuse writer')


class Marker:
    """An armed token belongs only to the creating live owner generation.

    No reopen/adopt operation exists. Keep this object until owner shutdown;
    closing its FD never removes its persistent marker.
    """
    def __init__(self, directory_fd, lock_fd, disk_fd, run_id, owner_generation):
        self.fd = None
        self.armed = False
        self.directory_fd, self.lock_fd, self.disk_fd = directory_fd, lock_fd, disk_fd
        self.creator = Generation.current()
        for value in (run_id, owner_generation):
            if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,96}', value) is None:
                raise Rejected('bounded run ID and owner generation required')
        _check_inputs(directory_fd, lock_fd, disk_fd)
        refuse_unfinished(directory_fd)
        info = os.fstat(disk_fd)
        self.disk = (info.st_dev, info.st_ino, info.st_size)
        self.directory = identity(os.fstat(directory_fd))
        self.lock = identity(os.fstat(lock_fd))
        self.record = dict(schema=SCHEMA, state='unfinished', run_id=run_id,
                           owner_generation=owner_generation,
                           owner=dict(pid=self.creator.pid, start_ticks=self.creator.start_ticks,
                                      boot_id=self.creator.boot_id),
                           disk=dict(dev=info.st_dev, inode=info.st_ino, bytes=info.st_size),
                           directory=list(self.directory), lock=list(self.lock))
        self.raw = (json.dumps(self.record, sort_keys=True, separators=(',', ':')) + '\n').encode()

    def arm_before_gate(self):
        """Create once; any exception forbids gate release and preserves bytes.

        Register this object with the owner BEFORE this call. No error path
        unlinks, truncates, replaces or retries a partially written marker.
        """
        if self.fd is not None or self.armed:
            raise Rejected('marker creation cannot be retried')
        self._check_owner_and_lease()
        self.fd = os.open(NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                          os.O_CLOEXEC, 0o600, dir_fd=self.directory_fd)
        self.marker_identity = identity(os.fstat(self.fd))
        os.fchmod(self.fd, 0o600)
        # Persist the empty name first so a later write failure also blocks reuse.
        os.fsync(self.directory_fd)
        if os.pwrite(self.fd, self.raw, 0) != len(self.raw):
            raise OSError('short quarantine write; partial marker retained')
        os.fsync(self.fd)
        self._check_bytes()
        os.fsync(self.directory_fd)
        self._check_owner_and_lease()
        self.armed = True

    def _check_owner_and_lease(self):
        if Generation.current() != self.creator:
            raise Rejected('quarantine token belongs to another process generation')
        _check_inputs(self.directory_fd, self.lock_fd, self.disk_fd)
        info = os.fstat(self.disk_fd)
        if ((info.st_dev, info.st_ino, info.st_size) != self.disk or
                identity(os.fstat(self.directory_fd)) != self.directory or
                identity(os.fstat(self.lock_fd)) != self.lock):
            raise Rejected('quarantine lease binding changed')

    def _check_bytes(self):
        info = os.fstat(self.fd)
        named = os.stat(NAME, dir_fd=self.directory_fd, follow_symlinks=False)
        if (identity(info) != self.marker_identity or identity(named) != self.marker_identity
                or not stat.S_ISREG(named.st_mode) or info.st_nlink != 1
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size != len(self.raw)
                or os.pread(self.fd, len(self.raw) + 1, 0) != self.raw):
            raise Rejected('quarantine marker identity/content readback differs')

    def require_armed_before_gate(self):
        if not self.armed:
            raise Rejected('durable quarantine marker not armed; gate must remain closed')
        self._check_owner_and_lease()
        self._check_bytes()

    def finish(self, *, owner_generation, quit_request_id, quit_reply, returncode):
        """Deliberately closed until a complete live reference audit exists.

        QMP reply/rc arguments are checks, not authenticated evidence adapters.
        They can never authorize removal in this source-only candidate.
        """
        self.require_armed_before_gate()
        if owner_generation != self.record['owner_generation']:
            raise Rejected('finish belongs to another owner generation')
        if (not isinstance(quit_request_id, str) or not quit_request_id
                or not isinstance(quit_reply, dict)
                or quit_reply.get('id') != quit_request_id
                or 'return' not in quit_reply or 'error' in quit_reply
                or type(returncode) is not int or returncode != 0):
            raise Rejected('matched QMP quit acknowledgement and rc0 required')
        raise Rejected('removal CLOSED: descendant/FD/detach/reference proof not implemented')

    def close(self):
        """Close only the token FD; the persistent quarantine remains intact."""
        if self.fd is not None:
            fd, self.fd = self.fd, None
            self.armed = False
            os.close(fd)
