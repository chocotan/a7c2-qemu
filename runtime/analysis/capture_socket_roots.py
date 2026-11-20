"""Owner-bound pathname sockets for the held-disk RAM capture experiment only."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import stat

from diagnostic_fs_socket_roots import identity, open_directory, process_identity

PROFILE = 'capture-ram-short-sockets-v1'
PROFILE_ENV = 'A7C2_CAPTURE_SOCKET_PROFILE'
ROOT_ENV = 'A7C2_CAPTURE_SOCKET_ROOT'
FD_ENV = 'A7C2_CAPTURE_SOCKET_FD'
BINDING_NAME = 'capture-short-sockets.json'
NAMES = ('qmp.sock', 'lcd-qmp.sock', 'hdmi-upm-gdb.sock', 'hdmi-upm-control.sock')
RUNS = Path(__file__).resolve().parent / 'menu-runs'
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
RECORD_MAX = 8192


def _parent():
    return Path('/run/user') / str(os.geteuid())


def _private_dir(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Capture socket directory must be owned mode 0700')
    return identity(info)


def _run(path):
    run = Path(path)
    if run.parent != RUNS or not re.fullmatch(r'[0-9a-f]{4}', run.name):
        raise ValueError('Capture files must be an exact first-level menu run')
    return run


def _file_id(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Capture file directory must be owned and not group/world writable')
    return identity(info)


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('Duplicate capture socket binding key')
        out[key] = value
    return out


def _read_binding(dirfd):
    fd = os.open(BINDING_NAME, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dirfd)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or
                not 0 < before.st_size <= RECORD_MAX):
            raise ValueError('Invalid capture socket binding file')
        raw = stream.read(RECORD_MAX + 1)
        after = os.fstat(fd)
        if len(raw) != before.st_size or before.st_mtime_ns != after.st_mtime_ns or before.st_ctime_ns != after.st_ctime_ns:
            raise ValueError('Capture socket binding changed during read')
    return json.loads(raw, object_pairs_hook=_pairs)


def _usable_umask():
    for line in Path('/proc/thread-self/status').read_text().splitlines():
        if line.startswith('Umask:'):
            return not int(line.split()[1], 8) & 0o700
    return False


class CaptureSocketRoots:
    def __init__(self, run, record):
        self.files = _run(run)
        if (not isinstance(record, dict) or
                set(record) != {'profile', 'files', 'name', 'owner', 'files_id', 'parent_id', 'socket_id'} or
                record['profile'] != PROFILE or record['files'] != str(self.files) or
                not isinstance(record['name'], str) or not re.fullmatch(r'c-[0-9a-f]{32}', record['name'])):
            raise ValueError('Invalid capture socket binding')
        owner = record['owner']
        if (not isinstance(owner, dict) or set(owner) != {'pid', 'start_ticks', 'boot_id'} or
                type(owner['pid']) is not int or owner['pid'] <= 1 or
                type(owner['start_ticks']) is not int or owner['start_ticks'] <= 0 or
                not isinstance(owner['boot_id'], str)):
            raise ValueError('Invalid capture socket owner generation')
        self.sockets = _parent() / record['name']
        if max(len(os.fsencode(self.sockets / name)) for name in NAMES) >= 108:
            raise ValueError('Capture socket path exceeds AF_UNIX limit')
        for key in ('files_id', 'parent_id', 'socket_id'):
            value = record[key]
            if (not isinstance(value, dict) or set(value) != {'dev', 'ino', 'uid', 'mode', 'kind'} or
                    any(type(field) is not int for field in value.values()) or value['kind'] != stat.S_IFDIR):
                raise ValueError('Invalid capture directory identity')
        self._record = json.loads(json.dumps(record))
        self._endpoints = {}

    @classmethod
    def create(cls, run):
        run = _run(run)
        if not _usable_umask():
            raise ValueError('Capture socket owner umask removes required owner permissions')
        runfd = open_directory(run)
        try:
            files_id = _file_id(runfd)
            try:
                os.stat(BINDING_NAME, dir_fd=runfd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError('Capture socket binding already exists')
            parentfd = open_directory(_parent())
            try:
                parent_id = _private_dir(parentfd)
                for _ in range(8):
                    name = 'c-' + secrets.token_hex(16)
                    if len(os.fsencode(_parent() / name / max(NAMES, key=len))) >= 108:
                        raise ValueError('Capture socket path exceeds AF_UNIX limit')
                    try:
                        os.mkdir(name, 0o700, dir_fd=parentfd)
                    except FileExistsError:
                        continue
                    break
                else:
                    raise FileExistsError('No unique capture socket directory available')
                childfd = os.open(name, DIR, dir_fd=parentfd)
                try:
                    socket_id = _private_dir(childfd)
                    if os.listdir(childfd) or identity(os.stat(name, dir_fd=parentfd, follow_symlinks=False)) != socket_id:
                        raise ValueError('Capture socket directory changed during allocation')
                finally:
                    os.close(childfd)
            finally:
                os.close(parentfd)
            owner = process_identity(os.getpid())
            record = dict(profile=PROFILE, files=str(run), name=name, owner=owner,
                          files_id=files_id, parent_id=parent_id, socket_id=socket_id)
            root = cls(run, record)
            fd = os.open(BINDING_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                         0o600, dir_fd=runfd)
            with os.fdopen(fd, 'wb') as out:
                out.write((json.dumps(record, sort_keys=True) + '\n').encode('ascii'))
                out.flush()
                os.fsync(out.fileno())
            root.binding()
            return root
        finally:
            os.close(runfd)

    @classmethod
    def open(cls, run, expected):
        root = cls(run, expected)
        root.binding()
        return root

    @contextmanager
    def directory(self):
        owner = self._record['owner']
        if process_identity(owner['pid']) != owner:
            raise ValueError('Capture socket owner generation changed')
        runfd = open_directory(self.files)
        try:
            if _file_id(runfd) != self._record['files_id'] or _read_binding(runfd) != self._record:
                raise ValueError('Capture socket binding no longer matches its run')
            parentfd = open_directory(_parent())
            try:
                if _private_dir(parentfd) != self._record['parent_id']:
                    raise ValueError('Capture socket parent changed')
                fd = os.open(self.sockets.name, DIR, dir_fd=parentfd)
                try:
                    if _private_dir(fd) != self._record['socket_id']:
                        raise ValueError('Capture socket directory changed')
                    yield fd
                finally:
                    os.close(fd)
            finally:
                os.close(parentfd)
        finally:
            os.close(runfd)

    def binding(self):
        with self.directory():
            return json.loads(json.dumps(self._record))

    def child(self, path):
        path = Path(path)
        if path.parent != self.sockets or path.name not in NAMES:
            raise ValueError('Not a capture socket endpoint')
        return path

    def _endpoint(self, fd, name):
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        now = identity(info)
        if (not stat.S_ISSOCK(info.st_mode) or info.st_nlink != 1 or
                now['uid'] != os.geteuid() or now['mode'] != 0o600):
            raise ValueError('Capture socket must be owned single-link mode 0600')
        if self._endpoints.setdefault(name, now) != now:
            raise ValueError('Capture socket endpoint replaced')
        return dict(now)

    def endpoint(self, path):
        name = self.child(path).name
        with self.directory() as fd:
            return self._endpoint(fd, name)

    def verify_all(self):
        with self.directory() as fd:
            if set(os.listdir(fd)) != set(NAMES):
                raise ValueError('Capture listener set differs from exact four endpoints')
            return {name: self._endpoint(fd, name) for name in NAMES}

    @contextmanager
    def connect_path(self, path):
        name = self.child(path).name
        with self.directory() as fd:
            self._endpoint(fd, name)
            yield f'/proc/self/fd/{fd}/{name}'
            self._endpoint(fd, name)
        with self.directory():
            pass

    @contextmanager
    def launch(self):
        if self._record['owner']['pid'] != os.getpid():
            raise ValueError('Only the capture owner can launch')
        with self.directory() as fd:
            if os.listdir(fd):
                raise ValueError('Capture socket directory was not empty at launch')
            yield {PROFILE_ENV: PROFILE, ROOT_ENV: str(self.sockets), FD_ENV: str(fd)}, fd


def launcher_preflight(env):
    if env.get(PROFILE_ENV) != PROFILE or not re.fullmatch(r'[1-9][0-9]*', env.get(FD_ENV, '')):
        raise ValueError('Capture socket launch requires its profile and inherited dirfd')
    files = _run(env['QEMU_OUTPUT_DIR'])
    runfd = open_directory(files)
    try:
        record = _read_binding(runfd)
    finally:
        os.close(runfd)
    root = CaptureSocketRoots.open(files, record)
    parent_stat = Path('/proc', str(os.getppid()), 'stat').read_text()
    launcher_owner = int(parent_stat.rsplit(')', 1)[1].split()[1])
    if record['owner']['pid'] != launcher_owner or env.get(ROOT_ENV) != str(root.sockets):
        raise ValueError('Capture socket launch does not belong to its binding owner')
    with root.directory() as fd:
        inherited = int(env[FD_ENV])
        if inherited < 3 or _private_dir(inherited) != _private_dir(fd) or os.listdir(fd):
            raise ValueError('Capture socket launch inherited the wrong directory')


if __name__ == '__main__':
    launcher_preflight(os.environ)
