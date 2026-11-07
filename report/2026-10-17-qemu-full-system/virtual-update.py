#!/usr/bin/env python3
"""Install BODYDATA from a regular FAT image into new, fixed-size image copies.

This is an explicitly selected host_functional model, never an authentication
fallback. It does NOT run p1's receiver, UPM, original writers or reboot code.
Unmodelled formatting, Backup, application and peripheral effects stay uncovered.

install_sd(sd_image, images_manifest, output_dir, *, fwtool_dir,
           mtools_dir=None, decoder=None, fail_after=None) returns a receipt.
images_manifest is manifest.json beside the 19 source images, or full-system.json
beside root/partitions/. No source image is ever opened writable. output_dir must
not exist; all failure artifacts and partial writes are retained there.

An optional local decoder(source_stream, output_stream, fwtool_dir) writes an
actual plaintext FDAT and returns diagnostic metadata. UFU CRC, FDAT header CRC,
section bounds, tar checksums and per-file .sum CRCs are checked independently.
The default decoder uses the existing, pinned fwtool SDK in the current Python
interpreter (which must already provide its crypto dependency).
fail_after injects a failure after this many partition bytes, including WBI drop.
Run tests with: python3 test-virtual-update.py
"""
import argparse
import binascii
from contextlib import ExitStack
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
CHUNK = 1024 ** 2
MAGIC = b'\x89UFU\r\n\x1a\n'
NAMES = {'a7c2-rootfs.img', 'a7c2-usr.img'} | {
    f'nflasha{n}.img' for n in (1, 2, 3, 4, 5, 6, 8, 10, 11, 12, 13, 18, 22, 23, 30, 'B0', 'B1')}


def _module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


FAT = _module('_virtual_update_fat', 'fat_image.py')
IMPORT = _module('_virtual_update_import', 'import-bodydata.py')


class InstallError(RuntimeError):
    """The original error is __cause__; receipt and partial images are retained."""
    def __init__(self, error, receipt):
        super().__init__(str(error))
        self.receipt = receipt


def _path(path):
    return Path(path).absolute()  # Do not resolve away a symlink before checking it.


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hash(fd, offset=0, size=None):
    size = os.fstat(fd).st_size - offset if size is None else size
    result = hashlib.sha256()
    for start in range(offset, offset + size, CHUNK):
        count = min(CHUNK, offset + size - start)
        data = os.pread(fd, count, start)
        if len(data) != count:
            raise OSError('Short read while hashing fixed file descriptor')
        result.update(data)
    return result.hexdigest()


class _Source:
    def __init__(self, path):
        self.path = _path(path)
        self.fd = FAT.secure_open(self.path)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            self.info = os.fstat(self.fd)
            self.sha256 = _hash(self.fd)
            self.verify()
        except BaseException:
            self.close()
            raise

    def close(self):
        os.close(self.fd)

    def verify(self):
        current = FAT.secure_open(self.path)
        try:
            if (_identity(os.fstat(current)) != _identity(self.info)
                    or _identity(os.fstat(self.fd)) != _identity(self.info)):
                raise ValueError('Source identity/metadata changed: ' + str(self.path))
            actual = _hash(self.fd)
            if actual != self.sha256:
                raise ValueError('Source hash changed: ' + str(self.path))
            if _identity(os.fstat(self.fd)) != _identity(self.info):
                raise ValueError('Source changed while hashing: ' + str(self.path))
            return actual
        finally:
            os.close(current)


def _create(directory_fd, name):
    fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _write(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError('Zero write')
        view = view[written:]


class _Journal:
    def __init__(self, directory_fd):
        self.fd = _create(directory_fd, 'state.jsonl')
        self.count = 0

    def append(self, state, **data):
        entry = {'sequence': self.count, 'state': state, **data}
        raw = (json.dumps(entry, sort_keys=True) + '\n').encode()
        offset = os.lseek(self.fd, 0, os.SEEK_END)
        _write(self.fd, raw)
        os.fsync(self.fd)
        if os.pread(self.fd, len(raw), offset) != raw:
            raise OSError('State journal readback mismatch')
        self.count += 1


def _fat(source, scratch, mtools_dir):
    image = FAT.FatImage(source.path, scratch, mtools_dir=mtools_dir or HERE,
                         fmask=0o022, dmask=0o022, max_file_bytes=2 * 1024**3,
                         max_total_bytes=4 * 1024**3, allow_zero_padding=True)
    try:
        if _identity(image.identity) != _identity(source.info):
            raise ValueError('FAT image replaced since source lock')
        os.close(image.fd)
        image.fd = os.dup(source.fd)
        tree = image.inventory()['entries']
        matches = [name for name in tree if name.casefold() == '/bodydata.dat']
        if len(matches) != 1 or tree[matches[0]]['kind'] != 'file' or not tree[matches[0]]['size']:
            raise ValueError('Expected one ordinary, nonempty root BODYDATA.DAT')
        return image, matches[0], tree[matches[0]]
    except BaseException:
        image.close()
        raise


def _copy_fat_file(image, name, node, target_fd):
    _, raw = image.locations[name]
    start = int.from_bytes(raw[26:28], 'little')
    if image.bits == 32:
        start |= int.from_bytes(raw[20:22], 'little') << 16
    # inventory already checked cross-links across the entire tree. Reusing its
    # used set would reject this second traversal of the same audited chain.
    image.used = set()
    remaining = node['size']
    for cluster in image.chain(start, name):
        if remaining <= 0:
            raise ValueError('Overallocated BODYDATA chain')
        data = image.read(image.cluster_offset(cluster), min(remaining, image.cluster_bytes))
        _write(target_fd, data)
        remaining -= len(data)
    os.fsync(target_fd)
    if remaining or os.fstat(target_fd).st_size != node['size'] or _hash(target_fd) != node['sha256']:
        raise ValueError('BODYDATA FAT export readback mismatch')


def read_sd_package(sd_image, output_dir, *, mtools_dir=None):
    """Export a genuinely audited root FAT file; output_dir must already exist."""
    source = _Source(sd_image)
    try:
        out = FAT.secure_open(_path(output_dir), directory=True)
    except BaseException:
        source.close()
        raise
    try:
        image, name, node = _fat(source, _path(output_dir), mtools_dir)
        with image:
            fd = _create(out, 'BODYDATA.DAT')
            try:
                _copy_fat_file(image, name, node, fd)
                source.verify()
                return {'path': str(_path(output_dir) / 'BODYDATA.DAT'),
                        'bytes': node['size'], 'sha256': node['sha256'], 'fat_bits': image.bits}
            finally:
                os.close(fd)
    finally:
        os.close(out)
        source.close()


def _inspect_package(source, directory_fd):
    with os.fdopen(os.dup(source.fd), 'rb') as stream:
        total, chunks = IMPORT.chunks(stream)
    crc = 0
    crc_end = chunks[b'DEND'][0] - 8
    for offset in range(0, crc_end, CHUNK):
        data = os.pread(source.fd, min(CHUNK, crc_end - offset), offset)
        crc = binascii.crc32(data, crc)
    expected = struct.unpack('>I', os.pread(source.fd, 4, chunks[b'DEND'][0]))[0]
    if crc & 0xffffffff != expected:
        raise ValueError('UFU outer CRC mismatch')
    result = {'bytes': total, 'sha256': source.sha256, 'outer_crc_valid': True,
              'signature': {'status': 'unknown', 'stock_receiver_acceptance': 'unknown'}}
    fd_offset, fd_size = chunks[b'FDAT']
    openssl = shutil.which('openssl')
    key = HERE / 'keys/sony-update-public.pem'
    if openssl and key.exists() and fd_size >= 272 and (fd_size - 272) % 1024 == 0:
        signed_end = fd_offset + fd_size - 256
        hashed = _hash(source.fd, fd_offset, fd_size - 256)
        for name, data in (('signature.bin', os.pread(source.fd, 256, signed_end)),
                           ('signed-digest.bin', bytes.fromhex(hashed))):
            fd = _create(directory_fd, name)
            try:
                _write(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
        key_source = _Source(key)
        try:
            der = subprocess.run([openssl, 'pkey', '-pubin', '-in', '/proc/self/fd/' + str(key_source.fd),
                                  '-outform', 'DER'], pass_fds=[key_source.fd], capture_output=True, timeout=15)
            if der.returncode or hashlib.sha256(der.stdout).hexdigest() != IMPORT.KEY_DER_SHA:
                raise ValueError('Sony public verification key differs')
            result_sig = subprocess.run(
                [openssl, 'pkeyutl', '-verify', '-pubin', '-inkey', '/proc/self/fd/' + str(key_source.fd),
                 '-pkeyopt', 'digest:sha256', '-in', '/proc/self/fd/' + str(directory_fd) + '/signed-digest.bin',
                 '-sigfile', '/proc/self/fd/' + str(directory_fd) + '/signature.bin'],
                pass_fds=[key_source.fd, directory_fd], capture_output=True, timeout=15)
            key_source.verify()
            result['signature'] = {'status': 'valid' if result_sig.returncode == 0 else 'invalid',
                                   'algorithm': 'RSA-2048-PKCS1-v1.5-SHA256', 'returncode': result_sig.returncode,
                                   'signed_sha256': hashed, 'key_der_sha256': IMPORT.KEY_DER_SHA,
                                   'stdout': result_sig.stdout.decode(errors='replace'),
                                   'stderr': result_sig.stderr.decode(errors='replace'),
                                   'stock_receiver_acceptance': 'unknown'}
        finally:
            key_source.close()
    result['fdat_offset'], result['fdat_bytes'] = fd_offset, fd_size
    return result


def _default_decoder(source, destination, fwtool_dir):
    dat, fdat = IMPORT.vendor(_path(fwtool_dir))
    container = dat.readDat(source)
    decrypter, plaintext = fdat.decryptFdat(container.firmwareData)
    while data := plaintext.read(CHUNK):
        if destination.tell() + len(data) > 2 * os.fstat(source.fileno()).st_size:
            raise ValueError('Decrypted FDAT exceeds explicit bound')
        destination.write(data)
    return {'decrypter': decrypter, 'block_checksums_valid': True}


def _fdat(fd):
    header = os.pread(fd, 512, 0)
    if len(header) != 512 or header[:8] != b'UDTRFIRM' or header[12:16] != b'0100':
        raise ValueError('Invalid/truncated plaintext FDAT header')
    if binascii.crc32(header[12:]) & 0xffffffff != struct.unpack_from('<I', header, 8)[0]:
        raise ValueError('FDAT header CRC mismatch')
    if header[16:17] != b'U' or header[20:21] != b'N':
        raise ValueError('Unsupported FDAT mode/LUW')
    firmware_offset, firmware_size, count = struct.unpack_from('<III', header, 48)
    if not 1 <= count <= 28:
        raise ValueError('Invalid FDAT filesystem count')
    sections = []
    user_fs = False
    for index in range(count):
        mode, offset, size = struct.unpack_from('<c3xII4x', header, 64 + index * 16)
        user_fs |= mode == b'U' and size > 0
        if size:
            sections.append((offset, size))
    sections.append((firmware_offset, firmware_size))
    total = os.fstat(fd).st_size
    if not user_fs or not firmware_size or any(o < 512 or n < 0 or o + n > total for o, n in sections):
        raise ValueError('FDAT section outside plaintext/missing updater')
    ordered = sorted(sections)
    if any(a + n > b for (a, n), (b, _) in zip(ordered, ordered[1:])):
        raise ValueError('Overlapping FDAT sections')
    return {'model': struct.unpack_from('<I', header, 36)[0],
            'region': struct.unpack_from('<I', header, 40)[0],
            'version': f'{header[33]:x}.{header[32]:02x}', 'header_crc_valid': True,
            'header_sha256': hashlib.sha256(header).hexdigest(),
            'tar_offset': firmware_offset, 'tar_bytes': firmware_size,
            'bytes': total, 'sha256': _hash(fd)}


def decode_package(package_path, output_dir, *, fwtool_dir, decoder=None):
    """Decode to a real FDAT file; decoder metadata cannot assert original pass."""
    source = _Source(package_path)
    try:
        out = FAT.secure_open(_path(output_dir), directory=True)
    except BaseException:
        source.close()
        raise
    try:
        inspected = _inspect_package(source, out)
        fd = _create(out, 'firmware.fdat')
        try:
            with os.fdopen(os.dup(source.fd), 'rb') as src, os.fdopen(os.dup(fd), 'wb') as dst:
                metadata = (decoder or _default_decoder)(src, dst, fwtool_dir) or {}
                dst.flush()
            os.fsync(fd)
            if os.fstat(fd).st_size > 2 * source.info.st_size:
                raise ValueError('Decrypted FDAT exceeds explicit bound')
            result = _fdat(fd)
            result.update(package=inspected, path=str(_path(output_dir) / 'firmware.fdat'),
                          decrypter=metadata.get('decrypter', 'custom'),
                          block_checksums_valid=metadata.get('block_checksums_valid'),
                          execution_kind='host_functional', sd_receiver_executed=False,
                          guest_original_install_verified=False)
            source.verify()
            return result
        finally:
            os.close(fd)
    finally:
        os.close(out)
        source.close()


class _Part(io.RawIOBase):
    def __init__(self, fd, offset, size):
        self.fd, self.offset, self.size, self.position = fd, offset, size, 0

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        data = os.pread(self.fd, count, self.offset + self.position)
        if len(data) != count:
            raise OSError('Short FDAT section read')
        self.position += count
        return data


class _Writer:
    def __init__(self, volumes, journal, receipt, fail_after):
        if fail_after is not None and (type(fail_after) is not int or fail_after < 0):
            raise ValueError('fail_after must be a nonnegative partition byte count')
        self.volumes, self.journal, self.receipt, self.fail_after = volumes, journal, receipt, fail_after

    def write(self, partition, offset, data):
        volume = self.volumes[partition]
        if not data or offset < 0 or offset + len(data) > volume['bytes']:
            raise ValueError('Zero/out-of-capacity partition write: ' + partition)
        view = memoryview(data)
        while view:
            already = self.receipt['partition_bytes_written']
            if self.fail_after is not None:
                if already >= self.fail_after:
                    raise OSError('Injected failure after partition write')
                view = view[:self.fail_after - already]
            size = os.pwrite(volume['fd'], view, offset)
            if not 0 < size <= len(view):
                raise OSError('Zero/invalid partition pwrite: ' + partition)
            self.receipt['partition_bytes_written'] += size
            volume['written_end'] = max(volume['written_end'], offset + size)
            readback = os.pread(volume['fd'], size, offset)
            valid = readback == view[:size]
            self.journal.append('partition_write', partition=partition, offset=offset, bytes=size,
                                sha256=hashlib.sha256(view[:size]).hexdigest(), readback_valid=valid)
            if not valid:
                raise OSError('Partition write readback mismatch: ' + partition)
            offset += size
            data = data[size:]
            view = memoryview(data)
            if self.fail_after is not None and self.receipt['partition_bytes_written'] >= self.fail_after:
                raise OSError('Injected failure after partition write')


def _relative(name):
    if (not isinstance(name, str) or not name or name.startswith('/') or '\\' in name
            or any(p in ('', '.', '..') or ':' in p or any(ord(c) < 32 or ord(c) == 127 for c in p)
                   for p in name.split('/'))):
        raise ValueError('Unsafe tar path: ' + repr(name))
    if len(name.encode()) > 4096:
        raise ValueError('Tar path too long')
    return name


def _logical(name):
    stage, _, rest = name.partition('/')
    match = re.fullmatch(r'[0-9]{4}_([A-Za-z0-9_]+)', stage)
    if not match:
        raise ValueError('Unsupported updater tar stage: ' + name)
    return match[1] + ('/' + rest if rest else '')


def _check_sum(data, group, observed):
    checked = []
    for line in data.decode('ascii').splitlines():
        fields = line.split(',')
        if (len(fields) != 12 or fields[0] not in ('0', '2', '5')
                or fields[0] != '2' and fields[-1]):
            raise ValueError('Unsupported/malformed updater .sum record')
        path = group + '/' + _relative(fields[10])
        if path not in observed or observed[path]['type'] != fields[0]:
            raise ValueError('Checksum record has no preceding tar member: ' + path)
        if fields[0] == '2' and fields[11] != observed[path]['target']:
            raise ValueError('Updater symlink target mismatch: ' + path)
        if fields[0] == '0':
            crc, size = int(fields[1], 16), int(fields[2], 16)
            if (observed[path]['crc32'], observed[path]['bytes']) != (crc, size):
                raise ValueError('Updater file CRC/size mismatch: ' + path)
            checked.append(path)
    return checked


def _drop_targets(data):
    rows = []
    for line in data.splitlines():
        line = line.split(b'#', 1)[0].strip()
        if not line:
            continue
        fields = line.split(b',')
        if len(fields) != 4 or any(not re.fullmatch(rb'0[xX][0-9a-fA-F]{1,8}', p.strip()) for p in fields):
            raise ValueError('Invalid partinf.conf row')
        rows.append(tuple(int(p, 16) for p in fields))
    if not rows or len(rows) > 64:
        raise ValueError('Invalid partinf.conf partition count')
    targets = []
    for number, (_, size, kind, _) in enumerate(rows, 1):
        if kind & 2 and size:
            if size < 512:
                raise ValueError('WBI partconf size field below original drop threshold')
            targets.append('nflasha' + str(number))
    return targets


def apply_stream(stream, volumes, journal, receipt, *, fail_after=None):
    """Consume tar in order, drop at checked partconf_sum, then pwrite images.

    volumes are the private cloned fd/bytes dictionaries made by install_sd.
    Links are recorded and never followed or materialised on the host.
    """
    writer = _Writer(volumes, journal, receipt, fail_after)
    observed, names, links = {}, set(), set()
    checksummed = set()
    partconf = None
    dropped = False
    applied = []
    receipt['applied_images'] = applied
    total = 0
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for index, member in enumerate(archive):
            name = _relative(member.name)
            logical = _logical(name)
            if name in names or logical in observed or index >= 100000:
                raise ValueError('Duplicate/oversized tar inventory')
            if any(name.startswith(link + '/') for link in links):
                raise ValueError('Tar path descends through a symlink')
            names.add(name)
            if member.sparse or not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError('Unsupported hardlink/device/sparse tar member: ' + name)
            if member.size < 0 or member.size > 2 * 1024**3:
                raise ValueError('Tar member exceeds bound')
            total += member.size
            if total > 4 * 1024**3:
                raise ValueError('Tar stream exceeds bound')
            row = {'path': name, 'logical_path': logical, 'bytes': member.size}
            if member.isdir():
                if member.size:
                    raise ValueError('Nonempty tar directory')
                row['type'] = '5'
            elif member.issym():
                if member.size or not member.linkname or len(member.linkname.encode()) > 4096 or '\0' in member.linkname:
                    raise ValueError('Invalid tar symlink')
                links.add(name)
                row.update(type='2', target=member.linkname)
            else:
                partition = None
                if logical.startswith('part_image/'):
                    match = re.fullmatch(r'part_image/dev/(nflasha[0-9]+)', logical)
                    if not match or match[1] not in volumes:
                        raise ValueError('Unsupported partition target: ' + logical)
                    partition = match[1]
                    if not member.size or member.size > volumes[partition]['bytes']:
                        raise ValueError('Zero/out-of-capacity partition image: ' + logical)
                    journal.append('partition_image_begin', path=name, partition=partition, bytes=member.size)
                capture = logical == 'partconf/partinf.conf' or logical.split('/')[0].endswith('_sum')
                if capture and member.size > 16 * CHUNK:
                    raise ValueError('Oversized updater metadata')
                data = bytearray()
                hashed, crc, offset = hashlib.sha256(), 0, 0
                with archive.extractfile(member) as source:
                    while block := source.read(CHUNK):
                        hashed.update(block)
                        crc = binascii.crc32(block, crc)
                        if capture:
                            data.extend(block)
                        if partition:
                            writer.write(partition, offset, block)
                        offset += len(block)
                if offset != member.size:
                    raise ValueError('Truncated tar payload: ' + name)
                row.update(type='0', sha256=hashed.hexdigest(), crc32=crc & 0xffffffff)
                if partition:
                    fd = volumes[partition]['fd']
                    os.fsync(fd)
                    if _hash(fd, 0, member.size) != row['sha256']:
                        raise OSError('Partition full payload readback mismatch')
                    applied.append({'partition': partition, 'bytes': member.size, 'sha256': row['sha256'],
                                    'tar_index': index, 'readback_valid': True})
                    journal.append('partition_image_verified', **applied[-1])
                if logical == 'partconf/partinf.conf':
                    partconf = bytes(data)
                group = logical.split('/')[0]
                if group.endswith('_sum') and logical.endswith('.sum'):
                    checked = _check_sum(data, group[:-4], observed)
                    checksummed.update(checked)
                    journal.append('updater_sum_verified', path=name, checked=checked)
                    if logical == 'partconf_sum/partconf.sum':
                        if dropped or partconf is None or 'partconf/partinf.conf' not in checked:
                            raise ValueError('Missing/duplicate partconf drop trigger')
                        for target in _drop_targets(partconf):
                            if target not in volumes or volumes[target]['bytes'] < 512:
                                raise ValueError('Drop target missing/too small: ' + target)
                            before = os.pread(volumes[target]['fd'], 512, 0)
                            journal.append('wbi_drop_begin', partition=target, before_hex=before.hex())
                            writer.write(target, 0, bytes(512))
                            os.fsync(volumes[target]['fd'])
                            journal.append('wbi_drop_verified', partition=target, bytes=512, readback_hex=bytes(512).hex())
                            receipt['wbi_dropped'].append(target)
                        dropped = True
            observed[logical] = row
            journal.append('tar_member_consumed', **row)
        tar_end = archive.offset
    if isinstance(stream, _Part):
        if stream.size - tar_end < 1024:
            raise ValueError('Missing tar end markers')
        for offset in range(tar_end, stream.size, CHUNK):
            count = min(CHUNK, stream.size - offset)
            data = os.pread(stream.fd, count, stream.offset + offset)
            if len(data) != count or data != bytes(count):
                raise ValueError('Nonzero/truncated data after tar end')
    if any('part_image/dev/' + row['partition'] not in checksummed for row in applied):
        raise ValueError('Partition image missing its stream .sum validation')
    if partconf is not None and not dropped:
        raise ValueError('partconf present without its checked drop stage')
    if not applied:
        raise ValueError('Tar contained no partition image writes')
    receipt['applied_images'] = applied
    receipt['tar_members_consumed'] = len(names)
    return applied


def _poststate(volume, scratch, mtools_dir, journal):
    if mtools_dir is None:
        return {'status': 'blocked', 'reason': 'mtools_dir was not supplied; no comp/mode files were changed'}
    tools = _path(mtools_dir)
    for name in ('mcopy', 'mmd', 'mdel'):
        if not (tools / name).is_file():
            return {'status': 'blocked', 'reason': 'missing mtools executable: ' + name}
    with FAT.FatImage(volume['path'], scratch, mtools_dir=tools, fmask=0o022, dmask=0o022) as image:
        if _identity(image.identity)[:3] != _identity(os.fstat(volume['fd']))[:3]:
            raise ValueError('Poststate volume replaced')
        entries = image.inventory()['entries']
        modes = [p for p in entries if re.fullmatch('/updater/mode[0-9]+', p)]
        # SD's outer mode5 selects body action 6; the numbering is not shared.
        # Original EndUpdate/Backup prerequisites remain explicitly uncovered.
        if (modes != ['/updater/mode5'] or entries[modes[0]]['kind'] != 'file'
                or entries[modes[0]]['size'] != 0 or '/updater/uincomp' in entries
                or '/updater/comp' in entries
                or entries.get('/updater/mode', {}).get('kind') != 'file'
                or entries['/updater/mode']['size'] != 0):
            return {'status': 'blocked', 'reason': 'requires sole empty mode5 and base mode, absent comp/uincomp',
                    'observed_modes': modes}
        scratch_fd = FAT.secure_open(scratch, directory=True)
        try:
            fd = _create(scratch_fd, 'empty-comp')
            os.close(fd)
        finally:
            os.close(scratch_fd)
        before = dict(entries)
        after = dict(kind='file', mode=stat.S_IFREG | 0o644, uid=0, gid=0, flags=0, acl=0,
                     size=0, sha256=hashlib.sha256(b'').hexdigest())
        journal.append('poststate_begin', condition='host SD flag subset: sole empty mode5 and base mode, no comp/uincomp')
        image._command('mdel', '/updater/mode5')
        os.fsync(image.wfd)
        expected = {p: node for p, node in before.items() if p != '/updater/mode5'}
        if image.inventory() != {'entries': expected, 'hardlinks': []}:
            raise ValueError('mode5 deletion full-tree readback differs')
        journal.append('poststate_mode5_deleted', readback_valid=True)
        image.apply({'path': '/updater/comp', 'kind': 'file', 'before': None,
                     'after': after, 'snapshot': str(scratch / 'empty-comp')})
        journal.append('poststate_comp_created', readback_valid=True)
        image._command('mdel', '/updater/mode')
        os.fsync(image.wfd)
        del expected['/updater/mode']
        expected['/updater/comp'] = after
        if image.inventory() != {'entries': expected, 'hardlinks': []}:
            raise ValueError('Poststate full-tree readback differs')
        removed = ['/updater/mode5', '/updater/mode']
        journal.append('poststate_verified', created='/updater/comp', removed=removed)
        return {'status': 'applied_host_subset', 'created': '/updater/comp', 'removed': removed,
                'outer_mode': 5, 'body_action': 6, 'full_tree_readback_valid': True,
                'original_completeupdate_executed': False}


def _manifest(manifest_path, stack):
    source = _Source(manifest_path)
    stack.callback(source.close)
    if source.info.st_size > 16 * CHUNK:
        raise ValueError('Oversized images manifest')
    manifest = json.loads(os.pread(source.fd, source.info.st_size, 0))
    records = [{**row, 'name': row.get('name', row.get('file'))} for row in manifest['images']]
    if len(records) != len(NAMES) or {row['name'] for row in records} != NAMES:
        raise ValueError('Expected complete, unique 19-volume inventory')
    source_class = manifest.get('input_source_class', manifest.get('source', 'private-device-dump'))
    if source_class not in ('private-device-dump', 'official-bodydata-derived'):
        raise ValueError('Unknown input_source_class')
    base = source.path.parent
    if source.path.name == 'full-system.json':
        base = base / 'root/partitions'
    images = {}
    inodes = set()
    for row in records:
        name = row.get('file', row['name'])
        if not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Image file must be an ordinary basename')
        if type(row['bytes']) is not int or not 0 < row['bytes'] <= 2 * 1024**3:
            raise ValueError('Invalid partition capacity')
        if not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256']):
            raise ValueError('Invalid partition digest')
        image = _Source(base / name)
        stack.callback(image.close)
        if image.info.st_size != row['bytes'] or image.sha256 != row['sha256']:
            raise ValueError('Source partition size/hash mismatch: ' + name)
        inode = (image.info.st_dev, image.info.st_ino)
        if inode in inodes:
            raise ValueError('Source volumes must have independent inodes')
        inodes.add(inode)
        part = {'a7c2-rootfs.img': 'nflasha7', 'a7c2-usr.img': 'nflasha15'}.get(row['name'], row['name'][:-4])
        images[part] = {'source': image, 'name': row['name'], 'bytes': row['bytes']}
    return source, images, source_class


def install_sd(sd_image, images_manifest, output_dir, *, fwtool_dir,
               mtools_dir=None, decoder=None, fail_after=None):
    """Explicit host model. Failed original authentication must never call this as fallback."""
    output = _path(output_dir)
    if fail_after is not None and (type(fail_after) is not int or fail_after < 0):
        raise ValueError('fail_after must be a nonnegative partition byte count')
    receipt = {'schema': 1, 'execution_kind': 'host_functional', 'sd_receiver_executed': False,
               'guest_original_install_verified': False, 'stock_receiver_acceptance': 'unknown',
               'state': 'preflight', 'output_dir': str(output), 'partition_stream_verified': False,
               'partition_bytes_written': 0, 'wbi_dropped': [], 'final_mode': 'unknown',
               'automatic_rollback': False, 'backup_policy': 'source bytes cloned; original Backup callbacks not executed',
               'uncovered': ['original p1 receiver, authentication and UPM',
                             'us_mkfs formatting, partition table and Backup callbacks',
                             'application file overlays and peripheral/loader writers',
                             'original EndUpdate/CompleteUpdate predicates and side effects',
                             'reboot, power state and next loader mode']}
    with ExitStack() as stack:
        parent_fd = FAT.secure_open(output.parent, directory=True)
        stack.callback(os.close, parent_fd)
        if os.path.lexists(output):
            raise ValueError('output_dir must not exist')
        manifest_source, sources, source_class = _manifest(images_manifest, stack)
        sd = _Source(sd_image)
        stack.callback(sd.close)
        source_inodes = {(v['source'].info.st_dev, v['source'].info.st_ino) for v in sources.values()}
        if (sd.info.st_dev, sd.info.st_ino) in source_inodes:
            raise ValueError('SD image aliases an internal volume')
        fat, body_name, body_node = _fat(sd, output.parent, mtools_dir)
        stack.callback(fat.close)
        required = sum(v['bytes'] for v in sources.values()) + 4 * body_node['size'] + 64 * CHUNK
        usage = os.fstatvfs(parent_fd)
        if usage.f_bavail * usage.f_frsize < required:
            raise OSError('Insufficient space for fixed clones and bounded package staging')
        os.mkdir(output.name, 0o700, dir_fd=parent_fd)
        out_fd = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        stack.callback(os.close, out_fd)
        out_identity = _identity(os.fstat(out_fd))[:2]
        journal = _Journal(out_fd)
        stack.callback(os.close, journal.fd)
        receipt.update(input_source_class=source_class, space_required_bytes=required,
                       source_manifest_sha256=manifest_source.sha256,
                       sd={'path': str(sd.path), 'bytes': sd.info.st_size, 'sha256': sd.sha256},
                       source_images=[{'name': v['name'], 'bytes': v['bytes'], 'sha256': v['source'].sha256}
                                      for v in sources.values()])
        volumes = {}
        primary = None
        try:
            journal.append('clone_begin', execution_kind='host_functional', input_source_class=source_class)
            os.mkdir('images', 0o700, dir_fd=out_fd)
            images_fd = os.open('images', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=out_fd)
            stack.callback(os.close, images_fd)
            for part, source in sources.items():
                fd = _create(images_fd, source['name'])
                stack.callback(os.close, fd)
                if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) in source_inodes:
                    raise ValueError('Clone aliases source inode')
                for offset in range(0, source['bytes'], CHUNK):
                    data = os.pread(source['source'].fd, min(CHUNK, source['bytes'] - offset), offset)
                    if not data:
                        raise OSError('Truncated source clone read')
                    _write(fd, data)
                os.fsync(fd)
                if os.fstat(fd).st_size != source['bytes'] or _hash(fd) != source['source'].sha256:
                    raise OSError('Clone readback mismatch: ' + part)
                volumes[part] = {**source, 'fd': fd, 'path': output / 'images' / source['name'], 'written_end': 0}
                journal.append('clone_verified', partition=part, sha256=source['source'].sha256, bytes=source['bytes'])
            receipt['state'] = 'read_sd_package'
            package_fd = _create(out_fd, 'BODYDATA.DAT')
            stack.callback(os.close, package_fd)
            _copy_fat_file(fat, body_name, body_node, package_fd)
            fcntl.flock(package_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            receipt['package'] = {'bytes': body_node['size'], 'sha256': body_node['sha256'], 'fat_bits': fat.bits}
            journal.append('sd_package_readback_verified', **receipt['package'])
            receipt['state'] = 'decode_package'
            package_snapshot = _Source(output / 'BODYDATA.DAT')
            stack.callback(package_snapshot.close)
            if (_identity(package_snapshot.info)[:3] != _identity(os.fstat(package_fd))[:3]
                    or package_snapshot.sha256 != body_node['sha256']):
                raise ValueError('Exported BODYDATA replaced/changed before decode')
            decoded = decode_package(output / 'BODYDATA.DAT', output, fwtool_dir=fwtool_dir, decoder=decoder)
            package_snapshot.verify()
            if decoded['package']['sha256'] != body_node['sha256']:
                raise ValueError('Decoder consumed another package snapshot')
            receipt['decoded'] = decoded
            journal.append('package_decoded', **decoded)
            for source in [manifest_source, sd] + [v['source'] for v in sources.values()]:
                source.verify()
            plaintext = _Source(decoded['path'])
            stack.callback(plaintext.close)
            if plaintext.sha256 != decoded['sha256'] or plaintext.info.st_size != decoded['bytes']:
                raise ValueError('Plaintext FDAT replaced/changed before application')
            receipt['state'] = 'apply_stream'
            apply_stream(_Part(plaintext.fd, decoded['tar_offset'], decoded['tar_bytes']), volumes, journal,
                         receipt, fail_after=fail_after)
            plaintext.verify()
            receipt['state'] = 'verify_fixed_volumes'
            readback = []
            for part, volume in volumes.items():
                source = volume['source']
                if os.fstat(volume['fd']).st_size != volume['bytes']:
                    raise ValueError('Fixed partition capacity changed: ' + part)
                end = volume['written_end']
                if _hash(volume['fd'], end) != _hash(source.fd, end):
                    raise ValueError('Unwritten partition tail changed: ' + part)
                readback.append({'partition': part, 'bytes': volume['bytes'], 'sha256': _hash(volume['fd']),
                                 'written_end': end, 'tail_preserved': True})
            receipt['volumes_before_poststate'] = readback
            p5 = volumes['nflasha5']
            head = os.pread(p5['fd'], min(512, p5['bytes']), 0)
            p5_image = next((r for r in reversed(receipt['applied_images']) if r['partition'] == 'nflasha5'), None)
            receipt['p5'] = {'first512_hex': head.hex(), 'first512_sha256': hashlib.sha256(head).hexdigest(),
                             'starts_with_WBI2': head[:4] == b'WBI2', 'drop_executed': 'nflasha5' in receipt['wbi_dropped'],
                             'package_image_written_back': p5_image is not None,
                             'package_payload_readback_valid': bool(p5_image and _hash(p5['fd'], 0, p5_image['bytes']) == p5_image['sha256']),
                             'drop_zero_header_overwritten': bool(p5_image and 'nflasha5' in receipt['wbi_dropped'] and head != bytes(len(head))),
                             'boot_restore_executed': False}
            journal.append('p5_final_readback', **receipt['p5'])
            receipt['partition_stream_verified'] = True
            receipt['state'] = 'poststate'
            receipt['poststate'] = _poststate(volumes['nflasha2'], output, mtools_dir, journal)
            receipt['state'] = 'host_partition_model_applied'
        except Exception as error:
            primary = error
            receipt['failed_state'] = receipt['state']
            receipt['state'] = 'failed'
            receipt['error'] = {'type': type(error).__name__, 'message': str(error), 'errno': getattr(error, 'errno', None)}
        finally:
            checks, errors = [], []
            for source in [manifest_source, sd] + [v['source'] for v in sources.values()]:
                try:
                    checks.append({'path': str(source.path), 'before_sha256': source.sha256, 'after_sha256': source.verify(),
                                   'identity_and_hash_unchanged': True})
                except Exception as error:
                    errors.append({'path': str(source.path), 'type': type(error).__name__, 'message': str(error)})
                    if primary is None:
                        primary = error
                        receipt['failed_state'] = receipt['state']
                        receipt['state'] = 'failed'
                        receipt['error'] = {'type': type(error).__name__, 'message': str(error)}
            receipt['source_checks'], receipt['source_check_errors'] = checks, errors
            receipt['source_images_unchanged'] = not errors
            partial = []
            for part, volume in volumes.items():
                try:
                    os.fsync(volume['fd'])
                    fd = FAT.secure_open(volume['path'])
                    try:
                        if _identity(os.fstat(fd))[:3] != _identity(os.fstat(volume['fd']))[:3] or os.fstat(fd).st_nlink != 1:
                            raise ValueError('Output volume replaced or hardlinked: ' + part)
                    finally:
                        os.close(fd)
                    partial.append({'partition': part, 'bytes': os.fstat(volume['fd']).st_size,
                                    'written_end': volume['written_end'], 'sha256': _hash(volume['fd'])})
                except Exception as error:
                    errors.append({'partition': part, 'type': type(error).__name__, 'message': str(error)})
                    if primary is None:
                        primary = error
            receipt['retained_images'] = partial
            try:
                check_fd = FAT.secure_open(output, directory=True)
                try:
                    if _identity(os.fstat(check_fd))[:2] != out_identity:
                        raise ValueError('Output directory replaced')
                finally:
                    os.close(check_fd)
                if primary is not None:
                    receipt['state'] = 'failed'
                    receipt.setdefault('error', {'type': type(primary).__name__, 'message': str(primary)})
                journal.append(receipt['state'], error=receipt.get('error'), partition_bytes_written=receipt['partition_bytes_written'])
                receipt['journal_records'] = journal.count
                raw = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
                fd = _create(out_fd, 'receipt.json')
                try:
                    _write(fd, raw)
                    os.fsync(fd)
                    if os.pread(fd, len(raw), 0) != raw:
                        raise OSError('Receipt readback mismatch')
                finally:
                    os.close(fd)
                os.fsync(out_fd)
                os.fsync(parent_fd)
            except Exception as error:
                receipt['evidence_error'] = {'type': type(error).__name__, 'message': str(error)}
                if primary is None:
                    primary = error
        if primary is not None:
            raise InstallError(primary, receipt) from primary
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sd-image', type=Path, required=True)
    parser.add_argument('--images-manifest', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--fwtool-dir', type=Path, required=True)
    parser.add_argument('--mtools-dir', type=Path)
    parser.add_argument('--fail-after', type=int)
    args = parser.parse_args()
    try:
        result = install_sd(args.sd_image, args.images_manifest, args.output_dir, fwtool_dir=args.fwtool_dir,
                            mtools_dir=args.mtools_dir, fail_after=args.fail_after)
    except InstallError as error:
        print(json.dumps(error.receipt, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
