"""Build a private raw-newc derivative; never extract or edit the base image."""
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path, PurePosixPath
import secrets
import stat

from initramfs_identity import verify_image

CHUNK = 1024 * 1024
SPACE_RESERVE = 1024 * 1024


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _fd(stack, name, flags, parent=None):
    descriptor = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    stack.callback(os.close, descriptor)
    return descriptor


def _parent(stack, value):
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('Host path contains ..')
    path = path.absolute()
    descriptor = _fd(stack, '/', os.O_RDONLY | os.O_DIRECTORY)
    anchors = []
    for component in path.parts[1:-1]:
        child = _fd(stack, component, os.O_RDONLY | os.O_DIRECTORY, descriptor)
        anchors.append((descriptor, component, os.fstat(child)))
        descriptor = child
    return path, descriptor, path.name, anchors


def _check_anchors(anchors):
    for parent, name, before in anchors:
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (after.st_dev, after.st_ino, after.st_mode) != (before.st_dev, before.st_ino, before.st_mode):
            raise ValueError('Source ancestor changed during build')


def _scan(stack, root_fd):
    files, directories = {}, []

    def walk(descriptor, prefix):
        before = os.fstat(descriptor)
        names = sorted(os.listdir(descriptor))
        directories.append((descriptor, before, names))
        for name in names:
            guest = prefix + name
            guest.encode('utf-8')
            if guest == 'TRAILER!!!' or len(guest.encode('utf-8')) + 1 > 4096:
                raise ValueError('Unsupported overwrite filename')
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                child = _fd(stack, name, os.O_RDONLY | os.O_DIRECTORY, descriptor)
                if _signature(os.fstat(child)) != _signature(info):
                    raise ValueError('Source directory changed during scan')
                walk(child, guest + '/')
            elif stat.S_ISREG(info.st_mode):
                files[guest] = (descriptor, name, info)
            else:
                raise ValueError('Overwrite source must contain only directories and regular files: ' + guest)

    walk(root_fd, '')
    return files, directories


def _entries(stream, size):
    """Framing only: verify_image remains the authority for archive path safety."""
    stream.seek(0)
    while True:
        start = stream.tell()
        header = stream.read(110)
        if len(header) != 110 or header[:6] != b'070701':
            raise ValueError('Incomplete newc header')
        fields = [int(header[i:i + 8], 16) for i in range(6, 110, 8)]
        if not 1 <= fields[11] <= 4096:
            raise ValueError('Invalid newc name length')
        raw = stream.read(fields[11])
        if len(raw) != fields[11] or raw[-1:] != b'\0' or b'\0' in raw[:-1]:
            raise ValueError('Incomplete newc name')
        name = str(PurePosixPath(raw[:-1].decode('utf-8')))
        data = (stream.tell() + 3) & ~3
        end = (data + fields[6] + 3) & ~3
        if end > size:
            raise ValueError('Truncated newc record or padding')
        yield name, fields, start, data, end, header + raw
        if name == 'TRAILER!!!':
            break
        stream.seek(end)


def _copy(stream, output, length, digest=None):
    while length:
        data = stream.read(min(length, CHUNK))
        if not data:
            raise ValueError('Source truncated while reading')
        if output is not None:
            output.write(data)
        if digest is not None:
            digest.update(data)
        length -= len(data)


def _record_size(name, length):
    return ((110 + len(name.encode('utf-8')) + 1 + 3) & ~3) + ((length + 3) & ~3)


def _write_header(output, fields, name):
    raw = name.encode('utf-8') + b'\0'
    fields = list(fields)
    fields[11] = len(raw)
    if any(not 0 <= field <= 0xffffffff for field in fields):
        raise ValueError('newc field exceeds 32 bits')
    output.write(b'070701' + b''.join(f'{field:08x}'.encode('ascii') for field in fields) + raw)
    output.write(b'\0' * ((-output.tell()) % 4))


def _space(parent, required):
    info = os.fstatvfs(parent)
    if info.f_frsize <= 0 or info.f_bavail * info.f_frsize < required + SPACE_RESERVE:
        raise OSError('Insufficient or unknown output space (includes 1 MiB reserve)')


def build_overlay_initramfs(base_cpio, overwrite_dir, output_cpio):
    """Return a JSON-safe manifest after verified, atomic, no-clobber publication.

    Empty directories are ignored. Replacements keep base mode/uid/gid; additions
    use source rwx bits (no special bits), uid/gid 0, and new parents use 0755.
    Requires Linux O_NOFOLLOW/dir_fd, a raw 070701 image and sibling hard links.
    """
    with ExitStack() as stack:
        base, base_parent, base_name, base_anchors = _parent(stack, base_cpio)
        source, source_parent, source_name, source_anchors = _parent(stack, overwrite_dir)
        output, out_parent, out_name, out_anchors = _parent(stack, output_cpio)
        if output == source or source in output.parents:
            raise ValueError('Output must be outside overwrite directory')
        if os.path.lexists(output):
            raise FileExistsError(output)
        base_fd = _fd(stack, base_name, os.O_RDONLY | os.O_NONBLOCK, base_parent)
        before = os.fstat(base_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Base image must be a regular file')
        source_fd = _fd(stack, source_name, os.O_RDONLY | os.O_DIRECTORY, source_parent)
        source_anchors.append((source_parent, source_name, os.fstat(source_fd)))
        base_anchors.append((base_parent, base_name, before))
        files, directories = _scan(stack, source_fd)
        pinned_base = Path(f'/proc/self/fd/{base_fd}')
        verify_image(pinned_base, {})
        image = stack.enter_context(os.fdopen(os.dup(base_fd), 'rb'))
        records = list(_entries(image, before.st_size))
        entries = {name: fields for name, fields, *_ in records[:-1]}
        indexed_records = {record[0]: record for record in records[:-1]}
        if '.' in entries and not stat.S_ISDIR(entries['.'][1]):
            raise ValueError('Base archive root is not a directory')
        parents = set()
        for name in entries:
            parents.update(str(p) for p in PurePosixPath(name).parents if str(p) != '.')
        for name in files:
            if name in entries and (not stat.S_ISREG(entries[name][1]) or entries[name][4] != 1):
                raise ValueError('Overwrite target is not a unique regular file: ' + name)
            if name in parents:
                raise ValueError('Overwrite target contains base descendants: ' + name)
            for ancestor in PurePosixPath(name).parents:
                if str(ancestor) in entries and not stat.S_ISDIR(entries[str(ancestor)][1]):
                    raise ValueError('Overwrite path has a nondirectory base ancestor: ' + name)
        new_dirs = set()
        for name in files:
            new_dirs.update(str(p) for p in PurePosixPath(name).parents
                            if str(p) != '.' and str(p) not in entries)
        required = before.st_size + sum(_record_size(name, 0) for name in new_dirs)
        for name, (_, _, info) in files.items():
            if info.st_size > 0xffffffff:
                raise ValueError('Overwrite file exceeds newc limit: ' + name)
            if name in entries:
                record = indexed_records[name]
                raw_name = record[5][110:-1].decode('utf-8')
                required += _record_size(raw_name, info.st_size) - (record[4] - record[2])
            else:
                required += _record_size(name, info.st_size)
        _space(out_parent, required)
        temporary = '.' + out_name + '.' + secrets.token_hex(12) + '.partial'
        temporary_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                               0o600, dir_fd=out_parent)
        published = False
        manifest = {'base_cpio': str(base), 'overwrite_dir': str(source), 'output_cpio': str(output),
                    'source_class': 'overwrite_derivative', 'original_libraries_unchanged': False,
                    'empty_directories': 'ignored', 'created_directories': sorted(new_dirs), 'entries': []}
        try:
            with os.fdopen(temporary_fd, 'wb') as target:
                base_hash = hashlib.sha256()
                image.seek(0)
                _copy(image, None, before.st_size, base_hash)
                manifest['base_cpio_sha256'] = base_hash.hexdigest()

                def write_source(name, fields, archive_name, old_sha=None):
                    parent, leaf, info = files[name]
                    with ExitStack() as reading:
                        descriptor = _fd(reading, leaf, os.O_RDONLY | os.O_NONBLOCK, parent)
                        if _signature(os.fstat(descriptor)) != _signature(info):
                            raise ValueError('Overwrite source changed before reading: ' + name)
                        fields = list(fields)
                        fields[6] = info.st_size
                        _write_header(target, fields, archive_name)
                        digest = hashlib.sha256()
                        with os.fdopen(os.dup(descriptor), 'rb') as content:
                            _copy(content, target, info.st_size, digest)
                            if content.read(1):
                                raise ValueError('Overwrite source grew: ' + name)
                        if _signature(os.fstat(descriptor)) != _signature(info):
                            raise ValueError('Overwrite source changed while reading: ' + name)
                    target.write(b'\0' * ((-target.tell()) % 4))
                    manifest['entries'].append({'path': name, 'action': 'replace' if old_sha else 'add',
                        'source_class': 'user_overwrite', 'source': str(source / name),
                        'old_sha256': old_sha, 'new_sha256': digest.hexdigest(), 'size': info.st_size,
                        'mode': fields[1], 'uid': fields[2], 'gid': fields[3]})

                inode = max((r[1][0] for r in records), default=0)
                # Base archives may omit explicit parent records; emit new parents first.
                for name in sorted(new_dirs, key=lambda n: (n.count('/'), n)):
                    inode += 1
                    _write_header(target, [inode, stat.S_IFDIR | 0o755, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0], name)
                for name, fields, start, data, end, raw_header in records[:-1]:
                    if name in files:
                        digest = hashlib.sha256()
                        image.seek(data)
                        _copy(image, None, fields[6], digest)
                        write_source(name, fields, raw_header[110:-1].decode('utf-8'), digest.hexdigest())
                    else:
                        image.seek(start)
                        _copy(image, target, end - start)
                for name in sorted(files.keys() - entries.keys()):
                    inode += 1
                    info = files[name][2]
                    fields = [inode, stat.S_IFREG | (info.st_mode & 0o777), 0, 0, 1, 0, info.st_size, 0, 0, 0, 0, 0, 0]
                    write_source(name, fields, name)
                image.seek(records[-1][2])
                _copy(image, target, before.st_size - records[-1][2])
                if target.tell() != required:
                    raise ValueError('Derived image size differs from plan')
                target.flush()
                os.fsync(target.fileno())
                result_info = os.fstat(target.fileno())
            expected = {item['path']: item['new_sha256'] for item in manifest['entries']}
            temporary_path = Path(f'/proc/self/fd/{out_parent}') / temporary
            verify_image(temporary_path, expected)
            with temporary_path.open('rb') as final:
                manifest['output_cpio_sha256'] = hashlib.file_digest(final, 'sha256').hexdigest()
            manifest['output_cpio_bytes'] = required
            if _signature(os.fstat(base_fd)) != _signature(before):
                raise ValueError('Base image changed during build')
            _check_anchors(base_anchors + source_anchors + out_anchors)
            for descriptor, info, names in directories:
                if _signature(os.fstat(descriptor)) != _signature(info) or sorted(os.listdir(descriptor)) != names:
                    raise ValueError('Overwrite directory changed during build')
            for parent, name, info in files.values():
                if _signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _signature(info):
                    raise ValueError('Overwrite source changed during build')
            os.link(temporary, out_name, src_dir_fd=out_parent, dst_dir_fd=out_parent, follow_symlinks=False)
            published = True
            os.unlink(temporary, dir_fd=out_parent)
            os.fsync(out_parent)
        except BaseException:
            if published:
                try:
                    # Only remove the publication if it still refers to our inode.
                    current = os.stat(out_name, dir_fd=out_parent, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (result_info.st_dev, result_info.st_ino):
                        os.unlink(out_name, dir_fd=out_parent)
                except FileNotFoundError:
                    pass
            raise
        finally:
            try:
                os.unlink(temporary, dir_fd=out_parent)
            except FileNotFoundError:
                pass
        return manifest
