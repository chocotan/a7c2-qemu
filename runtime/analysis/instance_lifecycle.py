"""Linux host lifecycle exclusion; no guest-state or VM liveness inference."""
import fcntl
import os
from pathlib import Path

import setting_store as store

LOCK = '.instance-lifecycle.lock'


class LeaseError(store.StoreError):
    pass


class Busy(LeaseError):
    pass


def _identity(fd):
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


class Instance:
    """Bind an existing private directory; never create a replacement instance."""

    def __init__(self, instance):
        if '..' in Path(instance).parts:
            raise LeaseError('parent traversal refused')
        self.path = os.fspath(Path(instance).absolute())
        with store._directory(self.path) as parent:
            self._identity = _identity(parent)

    def _check_directory(self, parent):
        if _identity(parent) != self._identity:
            raise LeaseError('instance directory identity changed')

    def run_lease(self):
        """Acquire before VM start; release only after all owned descendants exit."""
        return _Lease(self)

    def offline_lease(self, absolute_instance_path):
        """Factory for setting_store.reset(..., offline_lease=...)."""
        if absolute_instance_path != self.path:
            raise LeaseError('offline lease path mismatch')
        return _Lease(self)

    def reset(self, expected_generation, *, confirmed):
        """Publish store's logical tombstone; never delete history or SD files."""
        return store.reset(self.path, expected_generation, confirmed,
                           offline_lease=self.offline_lease)


class _Lease:
    def __init__(self, instance):
        self._instance = instance
        self._fd = None
        self._used = False
        self.pid = None

    def __bool__(self):
        raise TypeError('lease is a capability, not a boolean; call check()')

    def __enter__(self):
        if self._used:
            raise LeaseError('lease objects are single-use and non-reentrant')
        self._used = True
        with store._directory(self._instance.path) as parent:
            self._instance._check_directory(parent)
            fd = store._regular(parent, LOCK, os.O_RDWR | os.O_CREAT)
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise Busy('instance lifecycle lease is held') from exc
                self._fd, self.pid = fd, os.getpid()
                self.check()
            except BaseException:
                self._fd = None
                os.close(fd)
                raise
        return self

    def check(self):
        """Raise unless this process owns an active token for the bound path."""
        if self._fd is None or self.pid != os.getpid():
            raise LeaseError('inactive lease or foreign owner pid')
        with store._directory(self._instance.path) as parent:
            self._instance._check_directory(parent)
            other = store._regular(parent, LOCK)
            try:
                store._private(self._fd)
                if _identity(other) != _identity(self._fd):
                    raise LeaseError('lifecycle lock identity changed')
            finally:
                os.close(other)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._fd is None:
            raise LeaseError('inactive lease')
        fd, self._fd = self._fd, None
        # close (never LOCK_UN) cannot unlock the parent's shared fork description.
        os.close(fd)
        if self.pid != os.getpid():
            raise LeaseError('fork child cannot release owner lease')
        return False

    def load(self, firmware_sha):
        self.check()
        return store.load(self._instance.path, firmware_sha)

    def commit(self, inputfd_or_bytes, firmware_sha, expected_current_generation,
               *, guest_sha256):
        self.check()
        return store.commit(self._instance.path, inputfd_or_bytes, firmware_sha,
                            expected_current_generation, guest_sha256=guest_sha256)
