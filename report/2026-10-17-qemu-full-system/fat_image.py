"""Bounded raw FAT12/16/32 image overlay prototype; Python standard library only.

Conventional VFAT permissions require explicit fmask/dmask; no host umask is read.
default_uid/gid configure Sony's one-bit non-root POSIX mapping, not mount owners.
Optional image padding must remain entirely zero outside the BPB filesystem.
Only private, disposable regular image copies may be passed to apply().
"""
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import subprocess
import tempfile


def secure_open(path, flags=os.O_RDONLY, *, directory=False):
    """Reject symlinks in every host path component, including the final one."""
    path = os.fspath(path)
    if not os.path.isabs(path) or any(p in ('.', '..') for p in path.split('/')):
        raise ValueError('Host path must be absolute without dot components')
    parts = [p for p in path.split('/') if p]
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
            raise ValueError('Expected ordinary host directory' if directory else 'Expected regular host file')
        result = os.open(parts[-1], flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        if not (stat.S_ISDIR(os.fstat(result).st_mode) if directory else stat.S_ISREG(os.fstat(result).st_mode)):
            os.close(result)
            raise ValueError('Expected ordinary host directory' if directory else 'Expected regular host file')
        return result
    finally:
        os.close(fd)


def component(name):
    if (not name or name in ('.', '..') or name[-1] in ' .'
            or any(ord(c) < 32 or ord(c) == 127 or c in '/\\:*?"<>|[]' for c in name)
            or len(name.encode('utf-16le')) > 510):
        raise ValueError('Unsafe/unsupported FAT name: ' + repr(name))
    return name


def canonical(path):
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('Expected absolute guest path')
    if path != '/':
        for name in path[1:].split('/'):
            component(name)
    if len(path.encode('utf-8')) > 4096:
        raise ValueError('Guest path too long')
    return path


def link_text(target):
    if not isinstance(target, str) or not target or len(target.encode('utf-8')) > 4096:
        raise ValueError('Invalid symlink target')
    for part in target.split('/'):
        if part not in ('', '.', '..'):
            component(part)
    return target


def link_target(path, target):
    link_text(target)
    stack = [] if target.startswith('/') else path.strip('/').split('/')[:-1]
    for part in target.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if not stack:
                raise ValueError('Symlink target escapes guest root')
            stack.pop()
        else:
            component(part)
            stack.append(part)
    return target


class FatImage:
    def __init__(self, path, scratch, max_file_bytes=256 * 1024**2, *, mtools_dir,
                 fmask, dmask, default_uid=1000, default_gid=1000, rodir=False,
                 allow_zero_padding=False,
                 max_total_bytes=1024**3, max_image_bytes=16 * 1024**3,
                 max_entries=200000, max_clusters=4 * 1024**2):
        if any(type(mask) is not int or not 0 <= mask <= 0o777 for mask in (fmask, dmask)):
            raise ValueError('Explicit fmask/dmask must be permission masks in 0000..0777')
        if any(type(value) is not int or not 0 < value < 0xffffffff for value in (default_uid, default_gid)):
            raise ValueError('Sony non-root default UID/GID must be valid positive IDs')
        self.path = Path(path)
        self.scratch = Path(scratch)
        self.tools = Path(mtools_dir)
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_image_bytes = max_image_bytes
        self.max_entries = max_entries
        self.max_clusters = max_clusters
        self.fmask, self.dmask = fmask, dmask
        self.default_uid, self.default_gid = default_uid, default_gid
        self.rodir = rodir
        self.allow_zero_padding = allow_zero_padding
        self.fs_bytes = None
        self.fd = secure_open(path)
        self.identity = os.fstat(self.fd)
        self.wfd = None
        self.scratch_fd = None
        try:
            self.scratch_fd = secure_open(scratch, os.O_RDONLY | os.O_DIRECTORY, directory=True)
            self._bpb()
        except BaseException:
            self.close()
            raise

    def close(self):
        for key in ('fd', 'wfd', 'scratch_fd'):
            fd = getattr(self, key, None)
            if fd is not None:
                os.close(fd)
                setattr(self, key, None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _physical_read(self, offset, count):
        if offset < 0 or count < 0 or offset + count > self.identity.st_size:
            raise ValueError('Read outside image')
        data = os.pread(self.fd, count, offset)
        if len(data) != count:
            raise ValueError('Truncated image read')
        return data

    def read(self, offset, count):
        limit = self.identity.st_size if self.fs_bytes is None else self.fs_bytes
        if offset < 0 or count < 0 or offset + count > limit:
            raise ValueError('Read outside BPB filesystem')
        return self._physical_read(offset, count)

    def _check_padding(self):
        if os.fstat(self.fd).st_size != self.identity.st_size:
            raise ValueError('Filesystem image size changed')
        for offset in range(self.fs_bytes, self.identity.st_size, 1024**2):
            count = min(1024**2, self.identity.st_size - offset)
            if self._physical_read(offset, count) != b'\0' * count:
                raise ValueError('Nonzero trailing payload outside BPB filesystem')

    def _bpb(self):
        if not 512 <= self.identity.st_size <= self.max_image_bytes:
            raise ValueError('Image exceeds audit bound or is truncated')
        b = self.read(0, 512)
        u16 = lambda p: struct.unpack_from('<H', b, p)[0]
        u32 = lambda p: struct.unpack_from('<I', b, p)[0]
        self.sector, self.spc = u16(11), b[13]
        reserved, self.nfats, roots = u16(14), b[16], u16(17)
        total = u16(19) or u32(32)
        self.fat_sectors = u16(22) or u32(36)
        if (b[510:] != b'\x55\xaa' or self.sector not in (512, 1024, 2048, 4096)
                or self.spc not in (1, 2, 4, 8, 16, 32, 64, 128)
                or not reserved or self.nfats not in (1, 2) or not self.fat_sectors
                or not total or total * self.sector > self.identity.st_size):
            raise ValueError('Unsupported/invalid BPB or truncated filesystem')
        self.fs_bytes = total * self.sector
        self.boot_sector = b
        self.zero_chs = not u16(24) or not u16(26)
        if self.fs_bytes != self.identity.st_size and not self.allow_zero_padding:
            raise ValueError('Trailing image bytes require explicit allow_zero_padding=True')
        self._check_padding()
        rootsecs = (roots * 32 + self.sector - 1) // self.sector
        self.data_sector = reserved + self.nfats * self.fat_sectors + rootsecs
        self.clusters = (total - self.data_sector) // self.spc
        if not 1 <= self.clusters <= self.max_clusters:
            raise ValueError('Invalid/oversized cluster count')
        self.bits = 12 if self.clusters < 4085 else 16 if self.clusters < 65525 else 32
        self.fat_start = reserved * self.sector
        self.fat_bytes = self.fat_sectors * self.sector
        self.root_offset = (reserved + self.nfats * self.fat_sectors) * self.sector
        self.root_slots = roots
        self.cluster_bytes = self.sector * self.spc
        if self.cluster_bytes > 65536 or (self.clusters + 2) * self.bits > self.fat_bytes * 8:
            raise ValueError('Invalid FAT/cluster geometry')
        if self.bits == 32:
            if roots or u16(22) or u16(42) or u16(40) & 0x80:
                raise ValueError('Unsupported FAT32 version/nonmirrored FAT')
            self.root_cluster = u32(44)
            if not 2 <= self.root_cluster < self.clusters + 2:
                raise ValueError('Invalid FAT32 root')
        else:
            if not roots or not u16(22):
                raise ValueError('Invalid FAT12/16 root')
            self.root_cluster = 0
        self._fat_copies()
        if self.fat(0) & 255 != b[21] or self.fat(1) < (0xff8 if self.bits == 12 else 0xfff8 if self.bits == 16 else 0xffffff8):
            raise ValueError('Invalid reserved FAT entries')

    def _fat_copies(self):
        for table in range(1, self.nfats):
            for offset in range(0, self.fat_bytes, 1024**2):
                count = min(1024**2, self.fat_bytes - offset)
                if self.read(self.fat_start + offset, count) != self.read(self.fat_start + table * self.fat_bytes + offset, count):
                    raise ValueError('FAT copies disagree')

    def fat(self, cluster):
        offset = cluster * self.bits // 8
        if self.bits == 12:
            value = int.from_bytes(self.read(self.fat_start + offset, 2), 'little')
            return (value >> 4 if cluster & 1 else value) & 0xfff
        return int.from_bytes(self.read(self.fat_start + offset, self.bits // 8), 'little') & (0xffff if self.bits == 16 else 0xfffffff)

    def chain(self, start, owner):
        seen = set()
        eoc = {12: 0xff8, 16: 0xfff8, 32: 0xffffff8}[self.bits]
        reserved = eoc - 8
        while start:
            if not 2 <= start < min(self.clusters + 2, reserved) or start in seen:
                raise ValueError('Cyclic/free/reserved/bad cluster chain')
            if start in self.used:
                raise ValueError('Cross-linked cluster: ' + owner)
            seen.add(start)
            self.used.add(start)
            if len(self.used) > self.max_clusters:
                raise ValueError('Cluster audit bound exceeded')
            yield start
            value = self.fat(start)
            if value >= eoc:
                return
            if value < 2 or value >= reserved:
                raise ValueError('Free/reserved/bad cluster in allocated chain')
            start = value

    def cluster_offset(self, cluster):
        return (self.data_sector + (cluster - 2) * self.spc) * self.sector

    @staticmethod
    def checksum(short):
        checksum = 0
        for byte in short:
            checksum = (((checksum & 1) << 7) + (checksum >> 1) + byte) & 255
        return checksum

    def _name(self, raw, lfn):
        short = raw[:11]
        if raw[12] & ~0x18:
            raise ValueError('Invalid short name case bits')
        if short[0] == 5:
            short = b'\xe5' + short[1:]
        base, ext = short[:8].rstrip(b' '), short[8:].rstrip(b' ')
        if (not base or any(byte < 33 or byte == 127 or byte in b'"*+,./:;<=>?[\\]|'
                            for byte in base + ext)):
            raise ValueError('Invalid DOS alias')
        alias = base.decode('cp850') + ('.' + ext.decode('cp850') if ext else '')
        component(alias)
        display = (base.decode('cp850').lower() if raw[12] & 8 else base.decode('cp850'))
        if ext:
            display += '.' + (ext.decode('cp850').lower() if raw[12] & 16 else ext.decode('cp850'))
        if not lfn:
            return display, alias
        n = len(lfn)
        if not 1 <= n <= 20:
            raise ValueError('LFN slot count exceeds FAT limit')
        units = b''
        for i, slot in enumerate(lfn):
            if (slot[0] != (n - i | (0x40 if i == 0 else 0)) or slot[11] != 15
                    or slot[12] or slot[13] != self.checksum(raw[:11]) or slot[26:28] != b'\0\0'):
                raise ValueError('Invalid LFN order/checksum/header')
        for slot in reversed(lfn):
            units += slot[1:11] + slot[14:26] + slot[28:32]
        values = list(struct.unpack('<' + 'H' * (len(units) // 2), units))
        if 0 in values:
            end = values.index(0)
            if any(v != 0xffff for v in values[end + 1:]) or end < (n - 1) * 13:
                raise ValueError('Invalid LFN padding/slot count')
            units = units[:end * 2]
        elif 0xffff in values:
            raise ValueError('Unterminated LFN padding')
        name = units.decode('utf-16le', errors='strict')
        component(name)
        return name, alias

    def _metadata(self, raw):
        attr, cs = raw[11], raw[13]
        directory = bool(attr & 16)
        kind = 'dir' if directory else 'file'
        px = (not attr & 4 or directory) and cs & 0xe0 == 0xe0
        if attr & 4 and not directory and cs & 1:
            typecode = cs >> 5
            if typecode > 5:
                raise ValueError('Invalid Sony special type')
            size = int.from_bytes(raw[28:32], 'little')
            if (typecode == 1 and size > 4096 and (size & 65535) <= 4096
                    or typecode != 1 and size and not size & 65535):
                raise ValueError('Ambiguous Sony special size truncation in native decoder')
            # The Sony decoder falls back to ordinary VFAT when the special
            # size test fails; SYS plus an odd DOS timestamp alone is not POSIX.
            if typecode == 1 and size <= 4096 or typecode != 1 and size == 0:
                kind = 'symlink' if typecode == 1 else 'file' if typecode == 0 else 'special'
                px = True
        if px:
            user = (0 if attr & 2 else 4) | (0 if attr & 1 else 2) | (0 if attr & 32 else 1)
            other = (0 if cs & 16 else 4) | (0 if cs & 8 else 2) | (0 if cs & 4 else 1)
            perms = user << 6 | other << 3 | other
            uid = self.default_uid if cs & 2 else 0
            gid = self.default_gid if cs & 2 else 0
        else:
            perms = 0o777
            if attr & 1 and (not directory or self.rodir):
                perms &= ~0o222
            perms &= ~(self.dmask if directory else self.fmask)
            uid = gid = 0
        types = {'file': stat.S_IFREG, 'dir': stat.S_IFDIR, 'symlink': stat.S_IFLNK,
                 'special': {2: stat.S_IFBLK, 3: stat.S_IFCHR, 4: stat.S_IFIFO, 5: stat.S_IFSOCK}.get(cs >> 5, 0)}
        node = dict(kind=kind, mode=types[kind] | perms, uid=uid, gid=gid, flags=0, acl=0)
        if kind == 'special':
            node['device'] = int.from_bytes(raw[14:16], 'little')
        return node

    def _records(self, cluster, path):
        if cluster == 0:
            for slot in range(self.root_slots):
                offset = self.root_offset + slot * 32
                yield offset, self.read(offset, 32)
        else:
            # Consume the full chain even after the directory end marker.
            for value in self.chain(cluster, path):
                offset = self.cluster_offset(value)
                data = self.read(offset, self.cluster_bytes)
                for pos in range(0, self.cluster_bytes, 32):
                    yield offset + pos, data[pos:pos + 32]

    def inventory(self):
        self._check_padding()
        if self.read(0, 512) != self.boot_sector:
            raise ValueError('BPB/boot sector changed since audit')
        self._fat_copies()
        self.used = set()
        self.locations = {}
        self.aliases = {}
        entries = {'/': dict(kind='dir', mode=stat.S_IFDIR | (0o777 & ~self.dmask), uid=0, gid=0, flags=0, acl=0)}
        pending = [('/', self.root_cluster, 0)]
        budget = 0
        slots = 0
        while pending:
            parent, cluster, parent_cluster = pending.pop()
            names = {}
            self.aliases[parent] = names
            lfn = []
            ended = False
            dots = set()
            for offset, raw in self._records(cluster, parent):
                slots += 1
                if slots > max(4096, self.max_entries * 24):
                    raise ValueError('Directory slot audit bound exceeded')
                if ended:
                    continue
                if raw[0] in (0, 0xe5):
                    if lfn:
                        raise ValueError('Orphan LFN slots')
                    ended = raw[0] == 0
                    continue
                if raw[11] == 15:
                    lfn.append(raw)
                    if len(lfn) > 20:
                        raise ValueError('LFN too long')
                    continue
                attr = raw[11]
                start = int.from_bytes(raw[26:28], 'little')
                if self.bits == 32:
                    start |= int.from_bytes(raw[20:22], 'little') << 16
                size = int.from_bytes(raw[28:32], 'little')
                if attr & 0xc0:
                    raise ValueError('Reserved FAT attribute bits')
                if raw[:11] in (b'.          ', b'..         '):
                    name = raw[:11].rstrip().decode()
                    expected = cluster if name == '.' else parent_cluster
                    if parent == '/' or lfn or not attr & 16 or size or start != expected or name in dots:
                        raise ValueError('Invalid dot directory entry')
                    dots.add(name)
                    continue
                if attr & 8:
                    if parent != '/' or attr != 8 or lfn or start or size:
                        raise ValueError('Invalid volume entry')
                    continue
                name, alias = self._name(raw, lfn)
                lfn = []
                for key in {name.casefold(), alias.casefold()}:
                    if key in names:
                        raise ValueError('Duplicate LFN/DOS alias/case-insensitive name')
                    names[key] = name
                path = canonical(parent.rstrip('/') + '/' + name)
                if len(entries) >= self.max_entries:
                    raise ValueError('Tree entry audit bound exceeded')
                node = self._metadata(raw)
                self.locations[path] = (offset, raw)
                if node['kind'] == 'dir':
                    if size or start < 2:
                        raise ValueError('Invalid directory size/start')
                    pending.append((path, start, cluster if parent != '/' else 0))
                else:
                    if size > self.max_file_bytes or budget + size > self.max_total_bytes:
                        raise ValueError('File/tree data audit bound exceeded')
                    budget += size
                    hashed = hashlib.sha256()
                    target = bytearray()
                    count = 0
                    for value in self.chain(start, path):
                        count += 1
                        remaining = size - (count - 1) * self.cluster_bytes
                        if remaining <= 0:
                            raise ValueError('Overallocated file chain')
                        data = self.read(self.cluster_offset(value), min(remaining, self.cluster_bytes))
                        hashed.update(data)
                        if node['kind'] == 'symlink':
                            target.extend(data)
                    if count != (size + self.cluster_bytes - 1) // self.cluster_bytes:
                        raise ValueError('Short file chain')
                    if node['kind'] == 'symlink':
                        # Existing links can cross mount boundaries (Sony mtab
                        # is ../proc/mounts). Inventory reads bytes, never follows.
                        node['target'] = link_text(target.decode('utf-8', errors='strict'))
                    elif node['kind'] == 'file':
                        node.update(size=size, sha256=hashed.hexdigest())
                entries[path] = node
            if lfn or parent != '/' and dots != {'.', '..'}:
                raise ValueError('Missing dot entries/orphan LFN')
        return {'entries': entries, 'hardlinks': []}

    def _write(self, offset, data):
        if self.wfd is None:
            self.wfd = secure_open(self.path, os.O_RDWR)
            identity = os.fstat(self.wfd)
            if (identity.st_dev, identity.st_ino, identity.st_size) != (self.identity.st_dev, self.identity.st_ino, self.identity.st_size):
                os.close(self.wfd)
                self.wfd = None
                raise ValueError('Image replaced since audit')
        if offset < 0 or offset + len(data) > self.fs_bytes:
            raise ValueError('Write outside BPB filesystem')
        if os.pwrite(self.wfd, data, offset) != len(data):
            raise OSError('Short image write')

    def _command(self, tool, path, source_fd=None):
        self._write(0, b'')
        argv = [str(self.tools / tool), '-i', '/proc/self/fd/' + str(self.wfd)]
        fds = [self.wfd]
        if source_fd is not None:
            argv += ['/proc/self/fd/' + str(source_fd)]
            fds.append(source_fd)
        argv.append('::' + path)
        # mtools 4.0.49 grows a directory by only one cluster per attempt. A
        # 20-slot LFN can need two 512-byte clusters; retry only that exact case.
        units = len(PurePosixPath(path).name.encode('utf-16le')) // 2
        long_slots = (units + 12) // 13 + 1 > self.cluster_bytes // 32
        growable = self.bits == 32 or str(PurePosixPath(path).parent) != '/'
        reference = self.inventory() if long_slots and growable else None
        for attempt in range(2):
            if source_fd is not None:
                os.lseek(source_fd, 0, os.SEEK_SET)
            # Sony's LBA-only images have zero CHS, which mtools rejects. Only
            # for those images, independent parsing and fsck replace its checks.
            env = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'MTOOLSRC': '/dev/null',
                   'MTOOLS_SKIP_CHECK': '1' if self.zero_chs else '0'}
            result = subprocess.run(argv, pass_fds=fds, capture_output=True, timeout=120, env=env)
            self._check_padding()
            if result.returncode == 0:
                return
            if (attempt == 0 and reference is not None and b'No directory slots' in result.stderr
                    and self.inventory() == reference):
                continue
            raise RuntimeError(f'{tool} failed ({result.returncode}): ' + result.stderr.decode(errors='replace'))

    def encode(self, node):
        kind, mode = node['kind'], node['mode']
        expected_type = {'file': stat.S_IFREG, 'dir': stat.S_IFDIR, 'symlink': stat.S_IFLNK}.get(kind)
        if (expected_type is None or stat.S_IFMT(mode) != expected_type or mode & ~(0o170000 | 0o777)
                or (mode >> 3) & 7 != mode & 7
                or (node['uid'], node['gid']) not in ((0, 0), (self.default_uid, self.default_gid))
                or node['flags'] or node['acl']):
            raise ValueError('Unrepresentable Sony VFAT POSIX attributes')
        attr = (16 if kind == 'dir' else 4 if kind == 'symlink' else 0)
        attr |= (0 if mode & 0o400 else 2) | (0 if mode & 0o200 else 1) | (0 if mode & 0o100 else 32)
        cs = (0x21 if kind == 'symlink' else 0xe0) | (2 if node['uid'] else 0)
        cs |= (0 if mode & 4 else 16) | (0 if mode & 2 else 8) | (0 if mode & 1 else 4)
        return attr, cs

    def _can_preserve_metadata(self, raw, after):
        size = after.get('size', len(after.get('target', '').encode('utf-8')))
        if not 0 <= size <= 0xffffffff:
            return False
        candidate = raw[:28] + size.to_bytes(4, 'little')
        try:
            return self._metadata(candidate) == {key: after[key] for key in ('kind', 'mode', 'uid', 'gid', 'flags', 'acl')}
        except ValueError:
            return False

    def apply(self, item):
        path = canonical(item['path'])
        # mtools truncates UTF-16 surrogate pairs even when it exits successfully.
        if any(ord(char) > 0xffff for char in path):
            raise ValueError('mtools cannot safely create/replace non-BMP guest names')
        if path == '/':
            raise ValueError('Root replacement forbidden')
        before_tree = self.inventory()
        entries = before_tree['entries']
        old = entries.get(path)
        after = item['after']
        if item['before'] != old or item['kind'] != after['kind']:
            raise ValueError('Stale operation or kind mismatch')
        for ancestor in PurePosixPath(path).parents:
            if entries.get(str(ancestor), {}).get('kind') != 'dir':
                raise ValueError('Missing/symlink/non-directory guest ancestor')
        parent = str(PurePosixPath(path).parent)
        basename = PurePosixPath(path).name
        collision = self.aliases[parent].get(basename.casefold())
        if collision is not None and collision != basename:
            raise ValueError('Guest name collides with DOS alias/case variant')
        if old and (old['kind'] == 'special' or (old['kind'] == 'dir') != (after['kind'] == 'dir')):
            raise ValueError('Directory/file/special node conflict')
        if old and after['kind'] == 'dir':
            if after != old:
                raise ValueError('Merged directory metadata must be retained')
            return
        if old and (old['mode'] & 0o7777, old['uid'], old['gid']) != (after['mode'] & 0o7777, after['uid'], after['gid']):
            raise ValueError('Replacement must inherit old permissions and ownership')
        if old is None and len(entries) >= self.max_entries:
            raise ValueError('Expected tree exceeds entry audit bound')
        try:
            attr, cs = self.encode(after)
        except ValueError:
            # A conventional entry can inherit unequal group/other bits from
            # an explicit mount mask even though a new POSIX entry cannot.
            raw = self.locations[path][1] if old else None
            if not old or old['kind'] != after['kind'] or not self._can_preserve_metadata(raw, after):
                raise
            attr, cs = raw[11], raw[13]
        total = sum(node.get('size', len(node.get('target', '').encode('utf-8'))) for node in entries.values())
        total -= (old or {}).get('size', len((old or {}).get('target', '').encode('utf-8')))
        total += after.get('size', len(after.get('target', '').encode('utf-8')))
        if total > self.max_total_bytes:
            raise ValueError('Expected tree exceeds total data audit bound')
        if self.zero_chs:
            # Never enable mtools' zero-CHS compatibility on a broken source FS.
            self.fsck()
        old_locations = dict(self.locations)
        if after['kind'] == 'symlink':
            target = link_target(path, after['target'])
            if item.get('target', target) != target:
                raise ValueError('Symlink target mismatch')
            # Anonymous source: no host path follows the guest symlink string.
            with tempfile.TemporaryFile(dir='/proc/self/fd/' + str(self.scratch_fd)) as source:
                source.write(target.encode('utf-8'))
                source.flush()
                self._mutate(path, old, after, attr, cs, old_locations, source.fileno())
        elif after['kind'] == 'file':
            fd = secure_open(item['snapshot'])
            try:
                info = os.fstat(fd)
                if not 0 <= info.st_size <= self.max_file_bytes or info.st_size != after['size']:
                    raise ValueError('Snapshot exceeds bound/size mismatch')
                with os.fdopen(os.dup(fd), 'rb') as source:
                    hashed = hashlib.file_digest(source, 'sha256').hexdigest()
                if hashed != after['sha256']:
                    raise ValueError('Snapshot digest mismatch')
                os.lseek(fd, 0, os.SEEK_SET)
                self._mutate(path, old, after, attr, cs, old_locations, fd)
            finally:
                os.close(fd)
        else:
            self._mutate(path, old, after, attr, cs, old_locations, None)
        os.fsync(self.wfd)
        expected = dict(entries)
        expected[path] = after
        if self.inventory() != {'entries': expected, 'hardlinks': []}:
            raise ValueError('Independent full-tree readback differs from expected overlay')
        if os.fstat(self.fd).st_size != self.identity.st_size:
            raise ValueError('Filesystem image size changed')

    def _mutate(self, path, old, after, attr, cs, originals, source_fd):
        if old:
            # mtools must see an ordinary writable file before unlink/reallocate.
            offset, raw = originals[path]
            self._write(offset + 11, b'\x20')
            self._write(offset + 13, b'\0')
            self._command('mdel', path)
        self._command('mmd' if after['kind'] == 'dir' else 'mcopy', path, source_fd)
        self.inventory()
        if path not in self.locations:
            raise ValueError('mtools did not create the exact requested guest name')
        for name, (_, raw) in originals.items():
            if name == path:
                continue
            if name not in self.locations:
                raise ValueError('mtools removed an unrelated entry')
            offset, _ = self.locations[name]
            self._write(offset + 11, raw[11:12])
            self._write(offset + 13, raw[13:20])
        offset, _ = self.locations[path]
        raw = originals[path][1] if old else None
        preserve = old and old['kind'] == after['kind']
        if preserve:
            # Changing a conventional SYS file to empty may activate Sony's
            # special-file discriminator; encode POSIX rather than change kind.
            preserve = self._can_preserve_metadata(raw, after)
        if preserve:
            self._write(offset + 11, raw[11:12])
            self._write(offset + 13, raw[13:20])
        else:
            self._write(offset + 11, bytes([attr]))
            self._write(offset + 13, bytes([cs]))

    def fsck(self):
        self._check_padding()
        result = subprocess.run(['/usr/bin/fsck.fat', '-n', '/proc/self/fd/' + str(self.fd)],
                                pass_fds=[self.fd], capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(f'Derived FAT failed fsck.fat -n ({result.returncode}): ' + result.stdout + result.stderr)
        self._check_padding()
        return result.stdout
