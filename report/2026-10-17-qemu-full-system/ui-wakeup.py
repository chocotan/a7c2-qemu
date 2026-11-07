"""One owned input directory wakes the existing serial owner; no worker thread."""
import ctypes
import os
from pathlib import Path
import select
import stat
import struct
import sys
import time


class UiWakeup:
    max_wait = .2
    controls = ('save-card-and-exit.request', 'input-quiesce.request', 'input-producer-stopped')
    event = struct.Struct('iIII')
    lost = 0x400 | 0x800 | 0x8000  # DELETE_SELF, MOVE_SELF, IGNORED

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else None
        self.fd = self.directory_fd = None
        self.control_state = ()
        if self.directory is None:
            return
        if not sys.platform.startswith('linux'):
            raise RuntimeError('Owned UI input wakeup requires Linux inotify')
        try:
            self.directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            st = os.fstat(self.directory_fd)
            if st.st_uid != os.geteuid():
                raise ValueError('UI input directory must belong to the runner user')
            self.identity = (st.st_dev, st.st_ino)
            libc = ctypes.CDLL(None, use_errno=True)
            libc.inotify_init1.argtypes = [ctypes.c_int]
            libc.inotify_init1.restype = ctypes.c_int
            libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
            libc.inotify_add_watch.restype = ctypes.c_int
            self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if self.fd < 0:
                self.fd = None
                raise OSError(ctypes.get_errno(), 'inotify_init1')
            # Atomic rename is the UI publication boundary; also accept a closed direct write.
            mask = 0x8 | 0x80 | self.lost  # CLOSE_WRITE, MOVED_TO, watch lifetime
            if libc.inotify_add_watch(self.fd, os.fsencode(f'/proc/self/fd/{self.directory_fd}'), mask) < 0:
                raise OSError(ctypes.get_errno(), 'inotify_add_watch')
        except BaseException:
            self.close()
            raise

    def close(self):
        for name in ('fd', 'directory_fd'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def _drain(self):
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                return
            if not data:
                raise RuntimeError('Owned UI input watch reached EOF')
            offset = 0
            while offset < len(data):
                _, mask, _, length = self.event.unpack_from(data, offset)
                if mask & self.lost:
                    raise RuntimeError('Owned UI input directory watch was lost')
                offset += self.event.size + length
            # IN_Q_OVERFLOW requires a filesystem rescan, performed by wait().

    def wait(self, deadline=None):
        until = time.monotonic() + self.max_wait
        if deadline is not None:
            until = min(until, deadline)
        while True:
            if self.directory is not None:
                st = self.directory.lstat()
                if not stat.S_ISDIR(st.st_mode) or (st.st_dev, st.st_ino) != self.identity:
                    raise RuntimeError('Owned UI input directory was replaced')
                self._drain()
                controls=[]
                for name in self.controls:
                    try:
                        item=(self.directory/name).stat()
                    except FileNotFoundError:
                        continue
                    controls.append((name,item.st_ino,item.st_mtime_ns,item.st_size))
                controls=tuple(controls)
                changed=controls!=self.control_state
                self.control_state=controls
                if changed and controls:
                    return 'control'
                if any(self.directory.glob('*.cmd')):
                    return 'input'
            delay = max(0.0, until-time.monotonic())
            if not delay or not select.select([] if self.fd is None else [self.fd], [], [], delay)[0]:
                return 'deadline'
