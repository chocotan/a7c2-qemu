"""Verify original flush, then inspect host files without exporting a disk-sized RAM image."""
import hashlib
import os
from pathlib import Path

from directory_sd import TOTAL

_COMMIT_READY = b'vvfat: directory commit tracking ready'
_COMMIT_PENDING = b'vvfat: host directory commit pending'
_COMMIT_COMPLETE = b'vvfat: host directory commit complete'
_CLOSE_PENDING = b'vvfat: closed with uncommitted host directory state'


def read_commit_status(path):
    ready = False
    pending = False
    closed_pending = False
    transitions = 0
    with open(path, 'rb') as stream:
        for line in stream:
            if _COMMIT_READY in line:
                ready = True
            if _COMMIT_PENDING in line:
                if not pending:
                    transitions += 1
                pending = True
            if _COMMIT_COMPLETE in line:
                if pending:
                    transitions += 1
                pending = False
            if _CLOSE_PENDING in line:
                pending = True
                closed_pending = True
    return {'available': ready, 'pending': pending,
            'closed_pending': closed_pending, 'transitions': transitions}


def _open_at(root_fd, relative, *, directory=False):
    parts = Path(relative).parts
    if not parts or any(part in ('', '.', '..') for part in parts):
        raise ValueError('Unsafe directory-SD relative path')
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        if directory:
            flags |= os.O_DIRECTORY
        next_fd = os.open(parts[-1], flags, dir_fd=fd)
        os.close(fd)
        return next_fd
    except BaseException:
        os.close(fd)
        raise


def _sync_tree(root_fd):
    files = []
    directories = []

    def visit(fd, relative):
        directories.append(relative)
        if len(directories) > 4096:
            raise ValueError('Directory SD directory count exceeds bound')
        entries = list(os.scandir(fd))
        for entry in entries:
            if entry.name in ('', '.', '..') or '/' in entry.name or '\\' in entry.name:
                raise ValueError('Unsupported directory-SD name')
            path = f'{relative}/{entry.name}' if relative else entry.name
            if entry.is_symlink():
                raise ValueError('Directory SD contains a symlink')
            if entry.is_dir(follow_symlinks=False):
                child = _open_at(root_fd, path, directory=True)
                try:
                    visit(child, path)
                finally:
                    os.close(child)
            elif entry.is_file(follow_symlinks=False):
                files.append({'path': path})
                if len(files) > 4096:
                    raise ValueError('Directory SD file count exceeds bound')
            else:
                raise ValueError('Directory SD only supports regular files/directories')

    root = os.dup(root_fd)
    try:
        visit(root, '')
    finally:
        os.close(root)
    for record in files:
        fd = _open_at(root_fd, record['path'])
        try:
            if os.fsync(fd):
                raise OSError('Directory-SD file fsync failed')
            info = os.fstat(fd)
            digest = hashlib.sha256()
            while True:
                data = os.read(fd, 8 * 1024 * 1024)
                if not data:
                    break
                digest.update(data)
            record.update(bytes=info.st_size, sha256=digest.hexdigest())
        finally:
            os.close(fd)
    for relative in directories:
        fd = root_fd if not relative else _open_at(root_fd, relative, directory=True)
        try:
            if os.fsync(fd):
                raise OSError('Directory-SD directory fsync failed')
        finally:
            if relative:
                os.close(fd)
    return files


def snapshot(lease, *, quiesce, guest_sync, original_mount, commit_status):
    result = dict(ok=False, scope='original-flushed host directory snapshot; no disk image export',
                  bytes=TOTAL, host_directory=lease.get('path'),
                  host_directory_verified=False, original_mount_verified=False,
                  original_capture_verified=False, firmware_format_verified=False,
                  filesystem_image_check='not_applicable_virtual_fat_metadata')
    result['quiesce'] = quiesce()
    if original_mount() is not True:
        raise ValueError('Original Fsys mount is not verified; refusing directory success')
    result['original_mount_verified'] = True
    if not isinstance(result['quiesce'], dict) or result['quiesce'].get('owner_stopped') is not True:
        raise ValueError('Original filesystem flush/owner STOP must be confirmed')
    raw = guest_sync()
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('Guest sync response must be bounded original bytes')
    lines = raw.replace(b'\r\n', b'\n').split(b'\n')
    marker = b'HOST_SD_BLOCK_SYNC bytes=256000000000 fsync_rc=0 '
    if sum(line.startswith(marker) and line.endswith(b'no_data_writes=1') for line in lines) != 1:
        raise ValueError('Real guest block fsync not confirmed')
    result['guest_block_sync_confirmed'] = True
    status = commit_status()
    if (not isinstance(status, dict) or status.get('available') is not True or
            status.get('pending') is not False or status.get('closed_pending') is not False):
        raise ValueError('Directory vvfat host commit is not verified clean')
    result['directory_commit_status'] = status
    fd = lease['fd']
    before = os.fstat(fd)
    if lease.get('path') and Path(lease['path']).resolve() != Path(os.readlink(f'/proc/self/fd/{fd}')).resolve():
        raise ValueError('Pinned directory path and descriptor differ')
    if (before.st_dev, before.st_ino) != (lease['device'], lease['inode']):
        raise ValueError('Pinned directory identity changed')
    files = _sync_tree(fd)
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_mtime_ns):
        raise ValueError('Directory changed while quiesced')
    result.update(files=files, file_count=len(files), host_directory_verified=True, ok=True)
    return result
