#!/usr/bin/env python3
"""Snapshot observer link inputs and bind them to the protected base initramfs."""
import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

ANALYSIS = Path(__file__).resolve().parents[2] / 'runtime/analysis'
sys.path.insert(0, str(ANALYSIS))
from initramfs_identity import verify_image

LIBRARIES = ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')
SCHEMA = 'a7c2-observer-private-libraries-v1'
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
NEW_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
CHUNK = 1024 * 1024
MAX_LIBRARY_BYTES = 16 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    raw = os.fspath(value)
    _require(isinstance(raw, str) and raw.startswith('/') and '\0' not in raw
             and not raw.startswith('//') and raw == os.path.normpath(raw),
             'Expected a canonical absolute path')
    _require(not any(raw == p or raw.startswith(p + '/')
                     for p in ('/tmp', '/dev', '/proc', '/sys', '/run', '/var/tmp', '/var/run')),
             'Host temporary, device and pseudo-filesystem paths are forbidden')
    return Path(raw)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_uid,
            info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def _directory_identity(info):
    _require(stat.S_ISDIR(info.st_mode) and info.st_uid in (0, os.geteuid())
             and not info.st_mode & 0o022, 'Unsafe directory owner or permissions')
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid


@contextmanager
def _directory(path, *, private=False):
    """Keep every ancestor open and reject path replacement at any level."""
    with ExitStack() as stack:
        fd = os.open('/', DIR_FLAGS)
        stack.callback(os.close, fd)
        root = _directory_identity(os.fstat(fd))
        anchors = []
        for part in path.parts[1:]:
            before = _directory_identity(os.stat(part, dir_fd=fd, follow_symlinks=False))
            child = os.open(part, DIR_FLAGS, dir_fd=fd)
            stack.callback(os.close, child)
            _require(_directory_identity(os.fstat(child)) == before,
                     'Directory changed while opening: ' + str(path))
            anchors.append((fd, part, child, before))
            fd = child
        info = os.fstat(fd)
        _require(info.st_uid == os.geteuid(), 'Selected directory must be owned')
        if private:
            _require(stat.S_IMODE(info.st_mode) == 0o700, 'Build directory must be mode 0700')
        try:
            yield fd
        finally:
            _require(_directory_identity(os.stat('/', follow_symlinks=False)) == root,
                     'Root directory identity changed')
            for parent, name, child, before in anchors:
                _require(_directory_identity(os.fstat(child)) == before
                         == _directory_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                         'Directory identity changed: ' + str(path))


def _regular(info, *, protected=False, private=False):
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1,
             'Input must be an owned single-link regular file')
    if protected:
        _require(not info.st_mode & 0o022, 'Base initramfs must not be group/world writable')
    if private:
        _require(stat.S_IMODE(info.st_mode) == 0o600, 'Private file must be mode 0600')
    return _identity(info)


@contextmanager
def _input(parent, name, *, protected=False, private=False):
    before = _regular(os.stat(name, dir_fd=parent, follow_symlinks=False),
                      protected=protected, private=private)
    fd = os.open(name, READ_FLAGS, dir_fd=parent)
    try:
        _require(_regular(os.fstat(fd), protected=protected, private=private) == before,
                 'Input changed while opening: ' + name)
        yield fd
    finally:
        try:
            _require(_regular(os.fstat(fd), protected=protected, private=private) == before
                     == _regular(os.stat(name, dir_fd=parent, follow_symlinks=False),
                                 protected=protected, private=private),
                     'Input identity changed: ' + name)
        finally:
            os.close(fd)


def _digest(fd, *, limit=None):
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    for data in iter(lambda: os.read(fd, CHUNK), b''):
        size += len(data)
        _require(limit is None or size <= limit, 'Input grew beyond the bounded read size')
        digest.update(data)
    return digest.hexdigest()


def _write(fd, data):
    remaining = memoryview(data)
    while remaining:
        size = os.write(fd, remaining)
        _require(size > 0, 'Private input write made no progress')
        remaining = remaining[size:]


@contextmanager
def _new(parent, name):
    fd = os.open(name, NEW_FLAGS, 0o600, dir_fd=parent)
    try:
        os.fchmod(fd, 0o600)
        _regular(os.fstat(fd), private=True)
        yield fd
    finally:
        os.close(fd)


def _copy(source, parent, name):
    digest = hashlib.sha256()
    size = 0
    with _new(parent, name) as target:
        os.lseek(source, 0, os.SEEK_SET)
        for data in iter(lambda: os.read(source, CHUNK), b''):
            size += len(data)
            _require(size <= MAX_LIBRARY_BYTES, 'Observer library grew beyond the bounded input size: ' + name)
            _write(target, data)
            digest.update(data)
        os.fsync(target)
        before = _regular(os.fstat(target), private=True)
        expected = digest.hexdigest()
        _require(os.fstat(target).st_size == size and _digest(target) == expected,
                 'Private library full readback differs: ' + name)
        _require(before == _regular(os.fstat(target), private=True)
                 == _regular(os.stat(name, dir_fd=parent, follow_symlinks=False), private=True),
                 'Private library identity changed: ' + name)
    os.fsync(parent)
    return expected, before


class _PinnedImage:
    """Give verify_image its file interface without reopening a mutable path."""
    def __init__(self, fd):
        self.fd = fd

    def open(self, mode):
        _require(mode == 'rb', 'Base initramfs is read-only')
        os.lseek(self.fd, 0, os.SEEK_SET)
        return os.fdopen(os.dup(self.fd), mode)

    def stat(self):
        return os.fstat(self.fd)


def snapshot_libraries(analysis, output):
    """Populate an existing owned 0700 build; retain all partial files on failure."""
    analysis, output = _canonical(analysis), _canonical(output)
    _require(analysis != output and analysis not in output.parents and output not in analysis.parents,
             'Analysis and build directories must be separate')
    with ExitStack() as stack, ExitStack() as inputs:
        analysis_fd = inputs.enter_context(_directory(analysis))
        output_fd = stack.enter_context(_directory(output, private=True))
        source_fd = inputs.enter_context(_directory(analysis / 'menu-root/lib'))
        image_fd = inputs.enter_context(_input(analysis_fd, 'menu-initramfs.cpio', protected=True))
        base_sha = _digest(image_fd)
        sources = {name: inputs.enter_context(_input(source_fd, name)) for name in LIBRARIES}
        for name, fd in sources.items():
            _require(0 < os.fstat(fd).st_size <= MAX_LIBRARY_BYTES,
                     'Observer library exceeds the bounded input size: ' + name)
        # A pre-existing receipt or lib directory is never reused or overwritten.
        try:
            os.stat('library-inputs.json', dir_fd=output_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('Private library receipt already exists')
        os.mkdir('lib', mode=0o700, dir_fd=output_fd)
        os.fsync(output_fd)
        private_fd = stack.enter_context(_directory(output / 'lib', private=True))
        libraries, private_identities = {}, {}
        for name, fd in sources.items():
            sha, private_identities[name] = _copy(fd, private_fd, name)
            libraries['lib/' + name] = dict(sha256=sha,
                source=str(analysis / 'menu-root/lib' / name), snapshot=str(output / 'lib' / name))
        expected = {name: item['sha256'] for name, item in libraries.items()}
        _require(verify_image(_PinnedImage(image_fd), expected) == expected,
                 'Base initramfs library identities differ')
        _require(_digest(image_fd) == base_sha, 'Base initramfs full SHA256 changed')
        # Re-read sources before closing their pinned identity checks.
        for name, fd in sources.items():
            _require(_digest(fd, limit=MAX_LIBRARY_BYTES) == libraries['lib/' + name]['sha256'],
                     'Source library full SHA256 changed: ' + name)
        for name in LIBRARIES:
            with _input(private_fd, name, private=True) as fd:
                _require(_identity(os.fstat(fd)) == private_identities[name],
                         'Private library identity changed: ' + name)
                _require(_digest(fd) == libraries['lib/' + name]['sha256'],
                         'Private library full SHA256 changed: ' + name)
        # Finish all source identity and ancestor checks before publishing success.
        inputs.close()
        receipt = dict(schema=SCHEMA, base_initramfs_sha256=base_sha,
                       libraries=libraries, physical_compatible=False)
        raw = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
        with _new(output_fd, 'library-inputs.json') as fd:
            _write(fd, raw)
            os.fsync(fd)
            before = _regular(os.fstat(fd), private=True)
            _require(_digest(fd) == hashlib.sha256(raw).hexdigest()
                     and os.fstat(fd).st_size == len(raw), 'Receipt full readback differs')
            _require(before == _regular(os.fstat(fd), private=True)
                     == _regular(os.stat('library-inputs.json', dir_fd=output_fd,
                                         follow_symlinks=False), private=True),
                     'Receipt identity changed')
        os.fsync(output_fd)
    return receipt


def link_observer(output, inputs):
    """Link the diagnostic observer without giving Clang mutable library paths."""
    output = _canonical(output)
    destination = output / 'menu-observe.so'
    sources = [_canonical(path) for path in inputs]
    _require(sources and all(path.resolve(strict=True) == path and path.is_file() and
             ((path.suffix == '.c' and path.is_relative_to(output / 'snapshot')) or
              (path.suffix == '.o' and path.parent == output / 'objects')) for path in sources),
             'Expected isolated observer source and object inputs')
    with ExitStack() as stack:
        output_fd = stack.enter_context(_directory(output, private=True))
        private_fd = stack.enter_context(_directory(output / 'lib', private=True))
        tmp_fd = stack.enter_context(_directory(output / 'tmp', private=True))
        _require(not os.path.lexists(destination), 'Observer output already exists')
        receipt_fd = stack.enter_context(_input(output_fd, 'library-inputs.json', private=True))
        with os.fdopen(os.dup(receipt_fd), 'rb') as stream:
            raw = stream.read(65537)
        _require(0 < len(raw) <= 65536, 'Observer library receipt size is invalid')
        receipt = json.loads(raw)
        rows = receipt.get('libraries', {})
        _require(receipt.get('schema') == SCHEMA and receipt.get('physical_compatible') is False and
                 set(rows) == {'lib/' + name for name in LIBRARIES}, 'Invalid observer library receipt')
        fds = []
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        for name in LIBRARIES:
            with _input(private_fd, name, private=True) as source:
                with os.fdopen(os.dup(source), 'rb') as stream:
                    data = stream.read(MAX_LIBRARY_BYTES + 1)
                row = rows['lib/' + name]
                _require(0 < len(data) <= MAX_LIBRARY_BYTES and row['snapshot'] == str(output / 'lib' / name) and
                         hashlib.sha256(data).hexdigest() == row['sha256'], 'Private library differs: ' + name)
            fd = os.memfd_create('a7c2-' + name, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            stack.callback(os.close, fd)
            _write(fd, data)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
            _require(fcntl.fcntl(fd, fcntl.F_GET_SEALS) == seals and
                     _digest(fd, limit=MAX_LIBRARY_BYTES) == row['sha256'], 'Sealed library differs: ' + name)
            fds.append(fd)
        tmp_path = f'/proc/self/fd/{tmp_fd}'
        subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
                        '-mno-outline-atomics', '-isystem', '/usr/aarch64-linux-gnu/include',
                        f'-ffile-prefix-map={output}/snapshot=.', '-shared', '-fPIC', '-Wl,--no-undefined',
                        '-Wl,--gc-sections', '-Wl,-soname,menu-observe.so', *map(str, sources),
                        *(f'/proc/self/fd/{fd}' for fd in fds), '-o', str(destination)],
                       pass_fds=(tmp_fd, *fds), check=True,
                       env={**os.environ, 'TMPDIR': tmp_path, 'TMP': tmp_path, 'TEMP': tmp_path})
        with _input(output_fd, 'menu-observe.so', protected=True) as artifact:
            header = os.pread(artifact, 20, 0)
            _require(header[:6] == b'\x7fELF\x02\x01' and header[16:20] == b'\x03\x00\xb7\x00',
                     'Observer output is not an AArch64 shared object')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--link', nargs='+')
    args = parser.parse_args(argv)
    try:
        if args.link is None:
            snapshot_libraries(args.analysis, args.output)
        else:
            link_observer(args.output, args.link)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Private observer inputs rejected: ' + str(error) + '\n')
    print(str(Path(args.output) / 'library-inputs.json'))


if __name__ == '__main__':
    main()
