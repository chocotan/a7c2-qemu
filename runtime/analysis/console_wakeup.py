"""Wait for the owned serial log to change without a fixed input-response delay."""
import ctypes
import errno
import os
from pathlib import Path
import select
import struct


class ConsoleWakeup:
    def __init__(self, path):
        self.fd = -1
        libc = ctypes.CDLL(None, use_errno=True)
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'Cannot watch serial completion')
        try:
            if libc.inotify_add_watch(self.fd, os.fsencode(Path(path)), 0x2 | 0x400 | 0x800) < 0:
                raise OSError(ctypes.get_errno(), 'Cannot watch owned console log')
        except BaseException:
            os.close(self.fd); self.fd = -1
            raise

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        if self.fd >= 0:
            os.close(self.fd); self.fd = -1

    def wait(self, timeout=.05):
        if self.fd < 0:
            raise ValueError('Serial watch already closed')
        if not select.select([self.fd], [], [], max(0, timeout))[0]:
            return
        while True:
            try:
                raw = os.read(self.fd, 65536)
            except BlockingIOError:
                return
            if not raw:
                raise OSError(errno.EIO, 'Serial completion watch closed')
            offset = 0
            while offset < len(raw):
                if len(raw) - offset < 16:
                    raise ValueError('Short serial completion notification')
                _watch, mask, _cookie, length = struct.unpack_from('iIII', raw, offset)
                offset += 16 + length
                if offset > len(raw) or mask & (0x4000 | 0x400 | 0x800 | 0x8000):
                    raise OSError(errno.EIO, 'Serial completion watch lost its bound file')
