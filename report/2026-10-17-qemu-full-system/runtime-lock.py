#!/usr/bin/env python3
"""Use the same advisory lock as run-full-system.py and build-full-system.py."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


def open_runtime_lock(runtime, *, allow_pending=False):
    runtime = Path(runtime).resolve(strict=True)
    analysis = runtime / 'analysis'
    if analysis.is_symlink() or not analysis.is_dir():
        raise ValueError('runtime analysis must be an ordinary directory')
    lock_path = analysis / '.run.lock'
    if lock_path.is_symlink():
        raise ValueError('refusing a symlinked runtime lock')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('runtime lock must be a private regular file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('runtime is busy: ' + str(lock_path)) from error
        if os.path.lexists(analysis / '.owner-retained.json'):
            raise RuntimeError('owned VM resources are unresolved; verify retained owner before reusing: '+str(analysis / '.owner-retained.json'))
        if not allow_pending and os.path.lexists(analysis / '.config-transaction.json'):
            raise RuntimeError('unfinished configuration transaction; use config-state.py --recover')
        return os.fdopen(fd, 'a')
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def exclusive_runtime(runtime, *, allow_pending=False):
    # Keep the descriptor open throughout the operation; never unlink its inode.
    with open_runtime_lock(runtime, allow_pending=allow_pending):
        yield Path(runtime).resolve(strict=True)
