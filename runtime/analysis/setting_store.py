"""Linux host-only Backup storage. No guest export or guest consistency claim.

All cooperating processes must use this module and the same stable instance path.
An input SHA verifies byte transport only; the controller owns guest quiescence.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

BACKUP_SIZE = 2390264
RESERVE = 1024 * 1024
SHA = re.compile(r'[0-9a-fA-F]{64}\Z')
GENERATION = re.compile(r'[0-9a-f]{32}\Z')


class StoreError(ValueError):
    pass


class Conflict(StoreError):
    pass


class PublicationUncertain(OSError):
    """Rename succeeded but directory fsync failed: reload before retrying."""


def _sha(value):
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise StoreError('64 hexadecimal SHA256 characters required')
    return value.lower()


def _expected(value):
    if value is not None and (not isinstance(value, str) or GENERATION.fullmatch(value) is None):
        raise StoreError('expected generation must be None or a generation token')


def _private(fd, directory=False):
    s = os.fstat(fd)
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(s.st_mode) or s.st_uid != os.geteuid() or
            stat.S_IMODE(s.st_mode) != (0o700 if directory else 0o600) or
            (not directory and s.st_nlink != 1)):
        raise StoreError('owned private directory (0700) or regular file (0600) required')


@contextmanager
def _directory(instance, create=False, missing_ok=False):
    path = Path(instance)
    if '..' in path.parts:
        raise StoreError('parent traversal refused')
    path = path.absolute()
    if path == Path('/'):
        raise StoreError('instance cannot be filesystem root')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, part in enumerate(path.parts[1:], 1):
            last = index == len(path.parts) - 1
            if last and create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=fd)
            except FileNotFoundError:
                if last and missing_ok:
                    yield None
                    return
                raise
            os.close(fd)
            fd = child
            s = os.fstat(fd)
            # Sticky shared ancestors (e.g. /tmp) are allowed; symlinks never are.
            if (s.st_uid not in (0, os.geteuid()) or
                    (s.st_mode & 0o022 and not s.st_mode & stat.S_ISVTX)):
                raise StoreError('unsafe instance ancestor')
        _private(fd, directory=True)
        yield fd
    finally:
        os.close(fd)


def _regular(parent, name, flags=os.O_RDONLY):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 0o600, dir_fd=parent)
    try:
        _private(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def _locked(instance, create=False, missing_ok=False):
    with _directory(instance, create, missing_ok) as parent:
        if parent is None:
            yield None
            return
        lock = _regular(parent, '.setting-store.lock', os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield parent
        finally:
            os.close(lock)


def _read(parent, name, limit):
    fd = _regular(parent, name)
    try:
        before = os.fstat(fd)
        if before.st_size > limit:
            raise StoreError('oversized file')
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise StoreError('file changed while reading')
        data = b''.join(chunks)
        if len(data) > limit or len(data) != before.st_size:
            raise StoreError('invalid file length')
        return data
    finally:
        os.close(fd)


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise StoreError('duplicate JSON field')
            result[key] = value
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise StoreError('corrupt JSON') from exc
    if not isinstance(value, dict):
        raise StoreError('JSON object required')
    return value


def _current(parent, firmware_sha=None):
    try:
        raw = _read(parent, 'current.json', 4096)
    except FileNotFoundError:
        # A missing pointer in a previously written store is damage, not a seed.
        if any(n.startswith(('generation-', '.current-')) for n in os.listdir(parent)):
            raise StoreError('missing manifest in a nonempty store')
        return None
    pointer = _json(raw)
    if set(pointer) != {'generation'}:
        raise StoreError('invalid manifest')
    generation = pointer['generation']
    if not isinstance(generation, str) or GENERATION.fullmatch(generation) is None:
        raise StoreError('invalid generation')
    child = os.open('generation-' + generation,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        _private(child, directory=True)
        record = _json(_read(child, 'record.json', 4096))
        if (set(record) != {'generation', 'firmware_sha', 'state', 'length', 'sha256'} or
                record['generation'] != generation or
                _sha(record['firmware_sha']) != record['firmware_sha']):
            raise StoreError('invalid generation record')
        if firmware_sha is not None and record['firmware_sha'] != firmware_sha:
            raise StoreError('firmware mismatch')
        if record['state'] == 'reset':
            if type(record['length']) is not int or record['length'] != 0 or record['sha256'] is not None:
                raise StoreError('invalid reset record')
            data = None
        elif record['state'] == 'backup':
            if (type(record['length']) is not int or record['length'] != BACKUP_SIZE or
                    _sha(record['sha256']) != record['sha256']):
                raise StoreError('invalid backup record')
            data = _read(child, 'backup.bin', BACKUP_SIZE)
            if len(data) != BACKUP_SIZE or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise StoreError('backup length/digest mismatch')
        else:
            raise StoreError('unknown generation state')
        return dict(record, data=data)
    finally:
        os.close(child)


def _space(parent, required):
    try:
        info = os.fstatvfs(parent)
    except OSError as exc:
        raise StoreError('free space unknown') from exc
    if (type(info.f_bavail) is not int or type(info.f_frsize) is not int or
            info.f_bavail < 0 or info.f_frsize <= 0):
        raise StoreError('free space unknown')
    if info.f_bavail * info.f_frsize < required + RESERVE:
        raise StoreError('insufficient free space')


def _write(parent, name, data):
    fd = _regular(parent, name, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError('short write')
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _encode(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode('ascii')


def _publish(parent, firmware_sha, data):
    _space(parent, (len(data) if data is not None else 0) + 16384)
    generation = uuid.uuid4().hex
    record = dict(generation=generation, firmware_sha=firmware_sha,
                  state='reset' if data is None else 'backup',
                  length=0 if data is None else len(data),
                  sha256=None if data is None else hashlib.sha256(data).hexdigest())
    name = 'generation-' + generation
    os.mkdir(name, 0o700, dir_fd=parent)
    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent)
    try:
        _private(child, directory=True)
        if data is not None:
            _write(child, 'backup.bin', data)
            if _read(child, 'backup.bin', BACKUP_SIZE) != data:
                raise StoreError('payload readback mismatch')
        _write(child, 'record.json', _encode(record))
        if _json(_read(child, 'record.json', 4096)) != record:
            raise StoreError('generation readback mismatch')
        os.fsync(child)
    finally:
        os.close(child)
    os.fsync(parent)
    candidate = '.current-' + generation
    _write(parent, candidate, _encode({'generation': generation}))
    if _json(_read(parent, candidate, 4096)) != {'generation': generation}:
        raise StoreError('pointer readback mismatch')
    os.fsync(parent)
    os.replace(candidate, 'current.json', src_dir_fd=parent, dst_dir_fd=parent)
    try:
        os.fsync(parent)
    except OSError as exc:
        raise PublicationUncertain('manifest renamed; durability unknown; reload before retry') from exc
    return dict(record, data=data)


def _cas(current, expected):
    actual = None if current is None else current['generation']
    if actual != expected:
        raise Conflict('current generation changed')


def _input(source):
    if isinstance(source, bytes):
        data = source
    elif type(source) is int:
        before = os.fstat(source)
        if not stat.S_ISREG(before.st_mode) or before.st_size != BACKUP_SIZE:
            raise StoreError('input fd must be an exact-size regular file')
        chunks = []
        offset = 0
        while offset < BACKUP_SIZE:
            chunk = os.pread(source, BACKUP_SIZE - offset, offset)
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        after = os.fstat(source)
        if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise StoreError('input changed while reading')
        data = b''.join(chunks)
    else:
        raise StoreError('explicit bytes or regular-file fd required')
    if len(data) != BACKUP_SIZE:
        raise StoreError('official Backup size must be exactly 2390264')
    return data


def commit(instance, inputfd_or_bytes, firmware_sha, expected_current_generation, *, guest_sha256):
    """Persist explicit bytes matching a separately obtained guest SHA256.

    None is the CAS token only for a new empty instance. Returns metadata + data.
    Hash agreement does not establish a coherent/committed guest Backup snapshot.
    """
    firmware_sha = _sha(firmware_sha)
    guest_sha256 = _sha(guest_sha256)
    _expected(expected_current_generation)
    data = _input(inputfd_or_bytes)
    if hashlib.sha256(data).hexdigest() != guest_sha256:
        raise StoreError('independent guest SHA256 mismatch')
    with _locked(instance, create=True) as parent:
        current = _current(parent, firmware_sha)
        _cas(current, expected_current_generation)
        return _publish(parent, firmware_sha, data)


def load(instance, firmware_sha):
    """None means absent/unseeded. A reset is an explicit generation with data=None."""
    firmware_sha = _sha(firmware_sha)
    with _locked(instance, missing_ok=True) as parent:
        return None if parent is None else _current(parent, firmware_sha)


def reset(instance, expected_generation, confirmed, *, offline_lease):
    """Publish a tombstone, preserving every earlier file.

    offline_lease(absolute_instance_path) MUST return a controller-owned context
    manager that establishes offline state, excludes guest/UI start and all
    configuration users, and holds that exclusion until exit. A bool is not a
    capability. This module cannot verify controller/VM lifecycle safety.
    """
    if confirmed is not True:
        raise StoreError('explicit reset confirmation required')
    if not callable(offline_lease):
        raise StoreError('controller offline lease factory required')
    _expected(expected_generation)
    result = None
    with offline_lease(os.fspath(Path(instance).absolute())):
        with _locked(instance) as parent:
            current = _current(parent)
            _cas(current, expected_generation)
            if current is None:
                raise StoreError('no configuration generation to reset')
            result = _publish(parent, current['firmware_sha'], None)
    if result is None:
        raise StoreError('controller lease suppressed reset failure')
    return result
