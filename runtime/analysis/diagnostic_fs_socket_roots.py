"""Explicit diagnostic F/S binding; no allocation, fallback or cleanup authority."""
import os
from pathlib import Path
import socket
import stat
from contextlib import contextmanager

DIAGNOSTIC_FS_PROFILE = 'diagnostic-single-ap-sockets-v1'
PROJECT = Path(__file__).resolve().parents[2]
_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW


# Synthetic peers and component lock tests do not prove the real owner contract.
FS_RUNTIME_BLOCKERS = (
    'single AP disk owner continuous lease and parent-death recovery are unverified',
    'real QEMU endpoint identity, reconnect and batch reference audit are unverified',
    'normal exit, detach and final owner/lease release are unverified',
)


def require_runtime_ready():
    # Deliberately unconditional: no environment, receipt or mutable status unlocks it.
    raise RuntimeError('BLOCKED: ' + '; '.join(FS_RUNTIME_BLOCKERS))


def identity(info):
    return dict(dev=info.st_dev, ino=info.st_ino, uid=info.st_uid,
                mode=stat.S_IMODE(info.st_mode), kind=stat.S_IFMT(info.st_mode))


def process_identity(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('process identity requires a positive PID')
    fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, start_ticks=int(fields[19]),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def open_directory(path):
    path = Path(path)
    if (not path.is_absolute() or '..' in path.parts or
            path != path.resolve(strict=True)):
        raise ValueError('directory must be absolute, canonical and nonsymlink')
    fd = os.open('/', _DIR)
    try:
        for part in path.parts[1:]:
            child = os.open(part, _DIR, dir_fd=fd)
            os.close(fd)
            fd = child
        if identity(os.fstat(fd)) != identity(path.lstat()):
            raise ValueError('directory changed while opening')
        return fd
    except BaseException:
        os.close(fd)
        raise


class DiagnosticRoots:
    def __init__(self, files, sockets, profile):
        require_runtime_ready()
        if profile != DIAGNOSTIC_FS_PROFILE:
            raise ValueError('independent socket root requires explicit diagnostic profile')
        self.files, self.sockets = Path(files), Path(sockets)
        if not self.files.is_relative_to(PROJECT) or self.files == PROJECT:
            raise ValueError('F must be within this project')
        parent = Path('/run/user') / str(os.geteuid())
        if not self.sockets.is_relative_to(parent) or self.sockets == parent:
            raise ValueError('S must be below /run/user/<euid>; no fallback')
        self.owner = process_identity(os.getpid())
        self.directories = {}
        self.endpoints = {}
        for path, private in ((self.files, False), (parent, True), (self.sockets, True)):
            fd = open_directory(path)
            try:
                info = os.fstat(fd)
                if (info.st_uid != os.geteuid() or info.st_mode & 0o022 or
                        (private and stat.S_IMODE(info.st_mode) != 0o700)):
                    raise ValueError('unsafe F/S ownership or permissions')
                self.directories[path] = identity(info)
            finally:
                os.close(fd)
        current = self.sockets.parent
        while current != parent:
            fd = open_directory(current)
            try:
                info = os.fstat(fd)
                if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise ValueError('unsafe intermediate S directory')
                self.directories[current] = identity(info)
            finally:
                os.close(fd)
            current = current.parent

    def revalidate(self):
        require_runtime_ready()
        if process_identity(os.getpid()) != self.owner:
            raise ValueError('diagnostic root owner changed')
        for path, expected in self.directories.items():
            fd = open_directory(path)
            try:
                if identity(os.fstat(fd)) != expected:
                    raise ValueError('F/S directory identity changed')
            finally:
                os.close(fd)

    def binding(self):
        self.revalidate()
        return dict(profile=DIAGNOSTIC_FS_PROFILE, files=str(self.files), sockets=str(self.sockets),
                    directories={str(p): value for p, value in self.directories.items()})

    def child(self, path):
        require_runtime_ready()
        path = Path(path)
        if path.parent != self.sockets or path.name in ('', '.', '..') or path.is_symlink():
            raise ValueError('endpoint must be a direct nonsymlink S child')
        return path

    def endpoint(self, path):
        path = self.child(path)
        self.revalidate()
        fd = open_directory(self.sockets)
        try:
            info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError('diagnostic endpoint must be owned 0600 socket with one link')
            current = identity(info)
            if path in self.endpoints and self.endpoints[path] != current:
                raise ValueError('diagnostic endpoint inode changed')
            self.endpoints[path] = current
            return current
        finally:
            os.close(fd)

    @contextmanager
    def connect_path(self, path):
        path = self.child(path)
        expected = self.endpoint(path)
        fd = open_directory(self.sockets)
        try:
            yield f'/proc/self/fd/{fd}/{path.name}'
            if self.endpoint(path) != expected or identity(os.fstat(fd)) != self.directories[self.sockets]:
                raise ValueError('diagnostic socket changed while connecting')
        finally:
            os.close(fd)


class DiagnosticListener:
    """Owned until transfer() succeeds; asyncio then owns this socket object."""
    def __init__(self, roots, name):
        require_runtime_ready()
        self.roots = roots
        self.path = roots.child(roots.sockets / name)
        self.listener = None
        self.server = None
        self.state = 'new'

    def bind(self):
        require_runtime_ready()
        if self.state != 'new':
            raise ValueError('listener already bound or transferred')
        self.roots.revalidate()
        fd = open_directory(self.roots.sockets)
        try:
            try:
                os.stat(self.path.name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError('diagnostic endpoint already exists')
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.state = 'owned'
            address = str(self.path) if len(os.fsencode(self.path)) < 108 else f'/proc/self/fd/{fd}/{self.path.name}'
            self.listener.bind(address)
            os.chmod(self.path.name, 0o600, dir_fd=fd, follow_symlinks=False)
            self.roots.endpoint(self.path)
            self.listener.setblocking(False)
            return self
        except BaseException:
            self.state = 'blocked-retained'
            if self.listener is not None:
                self.listener.close()
            raise
        finally:
            os.close(fd)

    async def transfer(self, callback):
        require_runtime_ready()
        import asyncio
        import inspect
        if self.state != 'owned':
            raise ValueError('listener not available for transfer')
        loop = asyncio.get_running_loop()
        if 'cleanup_socket' not in inspect.signature(loop.create_unix_server).parameters:
            raise RuntimeError('diagnostic listener requires cleanup_socket=False support')
        self.roots.endpoint(self.path)
        self.state = 'transferring'
        try:
            self.server = await asyncio.start_unix_server(callback, sock=self.listener,
                                                          cleanup_socket=False, start_serving=False)
        except BaseException:
            self.state = 'blocked-retained'
            raise
        self.listener = None
        self.state = 'server-owned'
        return self.server

    def close_untransferred(self):
        require_runtime_ready()
        if self.state == 'new':
            return
        if self.state == 'transferring' or (self.state == 'blocked-retained' and self.server is None):
            raise RuntimeError('listener transfer ownership unknown; retain owner')
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        self.roots.endpoint(self.path)
