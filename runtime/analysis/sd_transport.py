"""Fixed guest helper -> reserved RAM -> QMP -> checked atomic SD/card.img.

The owner MUST freeze/flush original Fsys and serialize the VM/export lifecycle.
Callbacks are trusted adapters: serial_command(str)->bytes, qmp(dict)->dict.
No callback command, guest path, physical address or shell text is user supplied.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import uuid

CAP = 0x400000
PHYS = 0x41E600000
RESERVE = 1024 * 1024
MARKER = re.compile(
    rb'SD_EXPORT_READY offset=(0|[1-9][0-9]*) len=([1-9][0-9]*) total=([1-9][0-9]*) '
    rb'dev=(0|[1-9][0-9]*) inode=([1-9][0-9]*) '
    rb'mtime=(-?(?:0|[1-9][0-9]*)\.[0-9]{9}) ctime=(-?(?:0|[1-9][0-9]*)\.[0-9]{9}) '
    rb'fnv64=([0-9a-f]{16}) rc=0')


def fnv64(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return f'{value:016x}'


def identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns


@contextmanager
def directory(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('parent traversal refused')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if os.fstat(fd).st_uid != os.geteuid():
            raise ValueError('run/SD must be owned by this user')
        if os.fstat(fd).st_mode & 0o022:
            raise ValueError('run/SD must not be writable by group/others')
        yield fd
    finally:
        os.close(fd)


def regular(parent, name, flags=os.O_RDONLY):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=parent)
    if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_uid != os.geteuid():
        os.close(fd)
        raise ValueError(f'{name}: owned regular file required')
    return fd


@contextmanager
def card_source(path):
    path=Path(path).absolute()
    with directory(path.parent) as parent:
        fd=regular(parent,path.name)
        try:
            before=os.fstat(fd)
            if not 0x400000<=before.st_size<=0x80000000 or before.st_size%4096:
                raise ValueError('Virtual SD must be a 4096-byte aligned 4 MiB..2 GiB regular image')
            yield fd
            if identity(before)!=identity(os.fstat(fd)):raise ValueError('Virtual SD source changed while reading')
        finally:os.close(fd)


def write_file(parent, name, data):
    fd = regular(parent, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def report(parent, result):
    try:
        fd = regular(parent, 'export.json')
    except FileNotFoundError:
        pass
    else:
        os.close(fd)
    name = f'.export-{uuid.uuid4().hex}.tmp'
    write_file(parent, name, (json.dumps(result, sort_keys=True) + '\n').encode())
    os.replace(name, 'export.json', src_dir_fd=parent, dst_dir_fd=parent)
    os.fsync(parent)


def digest_fd(fd):
    before = os.fstat(fd)
    sha = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        block = os.read(fd, CAP)
        if not block:
            break
        sha.update(block)
    if identity(before) != identity(os.fstat(fd)):
        raise ValueError('host image changed while hashing')
    return sha.hexdigest()


def check_space(parent, needed):
    info = os.fstatvfs(parent)
    if (type(info.f_bavail) is not int or type(info.f_frsize) is not int or
            info.f_bavail < 0 or info.f_frsize <= 0):
        raise ValueError('cannot determine free space')
    available = info.f_bavail * info.f_frsize
    if available < needed:
        raise ValueError(f'insufficient free space: available={available} required={needed}')


def export_card(run_dir, expected_total, *, serial_command, qmp, expected_old_sha256=None,quiesce=None,sparse=False):
    """Return export.json content; ok only after fsck and atomic publication.

    run_dir must already exist and be owned; SD is created mode 0700 if absent.
    All cooperating writers must honor SD/.export.lock. Failed evidence stays in
    SD/export-<id>; an unsafe report path is refused rather than followed.
    """
    result = {'ok': False, 'error': 'export interrupted', 'chunks': [], 'sha256': None,
              'expected_total': expected_total if type(expected_total) is int else None,
              'expected_old_sha256': expected_old_sha256 if isinstance(expected_old_sha256, str) else None,
              'quiesce': 'required_from_caller'}
    try:
        with directory(run_dir) as run:
            try:
                os.mkdir('SD', 0o700, dir_fd=run)
            except FileExistsError:
                pass
            # Open relative to the pinned run, without following an SD symlink.
            parent = os.open('SD', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=run)
            try:
                s = os.fstat(parent)
                if s.st_uid != os.geteuid() or s.st_mode & 0o022:
                    raise ValueError('SD must be owned and not group/other writable')
                lock = regular(parent, '.export.lock', os.O_RDWR | os.O_CREAT)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    _export_locked(parent, expected_total, serial_command, qmp,
                                   expected_old_sha256, result,quiesce,sparse)
                finally:
                    os.close(lock)
            finally:
                os.close(parent)
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    return result


def _export_locked(parent, total, serial_command, qmp, expected_old, result,quiesce=None,sparse=False):
    # Invalidate old success before checking inputs or calling guest/QMP.
    report(parent, result)
    evidence = candidate = old = None
    try:
        if type(total) is not int or total < 512 or total > (1 << 63)-1 or total % 512:
            raise ValueError('expected_total must be a positive sector-aligned int64')
        if expected_old is not None and not re.fullmatch('[0-9a-f]{64}', expected_old):
            raise ValueError('expected_old_sha256 must be lowercase SHA256')
        try:
            old = regular(parent, 'card.img')
        except FileNotFoundError:
            if expected_old is not None:
                raise ValueError('expected old card missing')
        else:
            if expected_old is None or digest_fd(old) != expected_old:
                raise ValueError('unknown old card: refusing overwrite')
            old_identity = identity(os.fstat(old))
        check_space(parent, 2 * total + CAP + RESERVE)
        if quiesce is not None:result['quiesce']=quiesce()
        name = 'export-' + uuid.uuid4().hex
        os.mkdir(name, 0o700, dir_fd=parent)
        result['evidence'] = name
        evidence = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        candidate = regular(evidence, 'candidate.img', os.O_RDWR | os.O_CREAT | os.O_EXCL)
        os.ftruncate(candidate,total)
        stamp = None
        first_hash = None
        sequence = 0

        def guest(offset, length):
            nonlocal stamp, sequence
            command = f'/simulation/sd-window-export {offset} {length} {total}'
            raw = serial_command(command)
            if not isinstance(raw, bytes) or len(raw) > RESERVE:
                raise ValueError('serial callback must return bounded bytes')
            sequence += 1
            write_file(evidence, f'serial-{sequence:04d}.txt', raw)
            lines = raw.replace(b'\r\n', b'\n').split(b'\n')
            matches = [MARKER.fullmatch(line) for line in lines if line.startswith(b'SD_EXPORT_READY')]
            if len(matches) != 1 or matches[0] is None or any(b'SD_EXPORT_ERROR' in line for line in lines):
                raise ValueError('missing/invalid/duplicate guest READY')
            values = matches[0].groups()
            if tuple(map(int, values[:3])) != (offset, length, total):
                raise ValueError('guest offset/length/total mismatch')
            current = [v.decode('ascii') for v in values[2:7]]
            if stamp is not None and current != stamp:
                raise ValueError('guest identity changed: still writing or replaced')
            stamp = current
            result['guest_identity'] = current
            return values[7].decode('ascii')

        def extent_map(name):
            from sd_sparse import parse_map
            raw=serial_command('/simulation/sd-sparse map')
            if type(raw) is not bytes or len(raw)>RESERVE:
                raise ValueError('Sparse map callback must return bounded bytes')
            write_file(evidence,name,raw)
            return parse_map(raw,total)

        mapped=None
        if sparse:
            if sparse is not True:
                raise ValueError('Sparse export flag must be bool')
            mapped=extent_map('sparse-before.txt')
            result['sparse_map']=mapped
            expected=guest(0,min(CAP,total))
            if result['guest_identity']!=mapped['identity']:
                raise ValueError('Sparse map and window identity differ')
            first_hash=expected
            windows=mapped['ranges']
        else:
            windows=((offset,min(CAP,total-offset)) for offset in range(0,total,CAP))
        for offset,length in windows:
            check_space(parent, (total-offset) * 2 + CAP + RESERVE)
            expected_fnv = guest(offset, length)
            if first_hash is None:
                first_hash = expected_fnv
            chunk_name = f'chunk-{offset:016x}.bin'
            chunk = regular(evidence, chunk_name, os.O_RDWR | os.O_CREAT | os.O_EXCL)
            try:
                args = {'execute': 'pmemsave', 'arguments': {'val': PHYS, 'size': length,
                        'filename': f'/proc/{os.getpid()}/fd/{chunk}'}}
                response = qmp(args)
                result['chunks'].append({'offset': offset, 'len': length, 'guest_fnv64': expected_fnv,
                                         'qmp': response, 'file': chunk_name})
                if not isinstance(response, dict) or response != {'return': {}}:
                    raise ValueError('QMP pmemsave failed')
                os.fsync(chunk)
                before = os.fstat(chunk)
                if before.st_size != length:
                    raise ValueError('QMP chunk length mismatch')
                raw = os.pread(chunk, length+1, 0)
                actual = fnv64(raw)
                result['chunks'][-1]['actual_fnv64'] = actual
                if len(raw) != length or actual != expected_fnv:
                    raise ValueError('QMP chunk FNV mismatch')
                if guest(offset, length) != expected_fnv:
                    raise ValueError('guest bytes changed after QMP read')
                if identity(before) != identity(os.fstat(chunk)):
                    raise ValueError('QMP chunk changed during read')
                # Sparse holes are zero only because the guest kernel attested them.
                if os.pwrite(candidate,raw,offset)!=len(raw):
                    raise ValueError('Short candidate write')
            finally:
                os.close(chunk)
        os.fsync(candidate)
        if os.fstat(candidate).st_size != total:
            raise ValueError('assembled image size mismatch')
        result['sha256'] = digest_fd(candidate)
        # fsck receives a pinned read-only descriptor and has no repair option.
        readonly = regular(evidence, 'candidate.img')
        try:
            try:
                checked = subprocess.run(['fsck.fat', '-n', f'/proc/self/fd/{readonly}'],
                                         pass_fds=(readonly,), capture_output=True, timeout=60)
            except subprocess.TimeoutExpired as error:
                write_file(evidence, 'fsck.txt', (error.stdout or b'') + (error.stderr or b''))
                result['fsck_rc'] = None
                raise
        finally:
            os.close(readonly)
        write_file(evidence, 'fsck.txt', checked.stdout + checked.stderr)
        result['fsck_rc'] = checked.returncode
        if checked.returncode:
            raise ValueError('fsck.fat -n failed')
        if guest(0, min(CAP, total)) != first_hash:
            raise ValueError('guest bytes changed before publication')
        if mapped is not None and extent_map('sparse-after.txt')!=mapped:
            raise ValueError('Sparse map/identity changed before publication')
        if digest_fd(candidate) != result['sha256']:
            raise ValueError('candidate changed during fsck')
        if old is None:
            os.link('candidate.img', 'card.img', src_dir_fd=evidence, dst_dir_fd=parent,
                    follow_symlinks=False)
        else:
            named = os.stat('card.img', dir_fd=parent, follow_symlinks=False)
            if identity(named) != old_identity or identity(os.fstat(old)) != old_identity or digest_fd(old) != expected_old:
                raise ValueError('old card changed before publication')
            os.link('card.img', 'previous-card.img', src_dir_fd=parent, dst_dir_fd=evidence,
                    follow_symlinks=False)
            os.replace('candidate.img', 'card.img', src_dir_fd=evidence, dst_dir_fd=parent)
        result['card_published']=True
        os.fsync(parent)
        result.update(ok=True)
        del result['error']
    except Exception as error:
        result.update(ok=False, error=f'{type(error).__name__}: {error}')
    finally:
        if evidence is not None:
            try:
                os.fsync(evidence)
            except OSError as error:
                result.update(ok=False, error=f'evidence fsync: {error}')
        for fd in (candidate, old, evidence):
            if fd is not None:
                os.close(fd)
        pending=dict(result)
        if quiesce is not None and pending.get('ok'):
            pending.update(ok=False,export_data_ok=True,error='owner recovery pending')
        report(parent,pending)
