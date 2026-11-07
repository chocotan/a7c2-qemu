"""Read-only Sony WBI2 inspection; no loader, resume or fullboot execution.

Public APIs accept a path, an fd, or a file object backed by a named owned regular
file. Reads use pread and preserve caller offsets. All successful calls compare
streamed SHA-256 before/after reading and recheck the named inode and parents.
Malformed/unsupported WBI2 raises ValueError; a non-WBI2 magic is a valid negative.
"""
from contextlib import contextmanager, ExitStack
import functools
import hashlib
import json
import operator
import os
from pathlib import Path
import stat
import struct

from sd_transport import directory, regular, identity

HEADER = struct.Struct('<4sI10Q')
SECTION = struct.Struct('<8Q')
SEED = 0x0f0f0f0f
CHUNK_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 ** 3
MAX_READ_BYTES = 16 * 1024 ** 2
MAX_SECTIONS = 65536
UINT64_END = 1 << 64
FACTS_PATH = Path(__file__).absolute().with_name('sony-boot-2.01.json')
FACTS_SHA256 = 'c330e221da3b8ea4a10716674bfbffcbad8ddbd6e8422510d27b2fb3696f4d1b'
HEADER_FIELDS = ('padding', 'sections', 'flags', 'resume_vector', 'dVersion',
                 'sector_size', 'r_data_size', 'kern_start', 'kern_size',
                 'kern_cksum', 'o_data_size')
SECTION_FIELDS = ('addr', 'rlen', 'cksum', 'flag', 'olen', 'virt', 'meta_cksum', 'padding')


def _read_exact(fd, offset, size):
    if (type(offset) is not int or type(size) is not int or offset < 0 or
            not 0 <= size <= MAX_READ_BYTES or offset + size > UINT64_END):
        raise ValueError('Invalid or oversized file read range')
    data = bytearray()
    while len(data) < size:
        block = os.pread(fd, min(CHUNK_BYTES, size - len(data)), offset + len(data))
        if not block:
            raise ValueError('Truncated file read')
        data.extend(block)
    return bytes(data)


def _digest(fd, size):
    digest = hashlib.sha256()
    for offset in range(0, size, CHUNK_BYTES):
        digest.update(_read_exact(fd, offset, min(CHUNK_BYTES, size - offset)))
    return digest.hexdigest()


def _file_info(fd):
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
            info.st_mode & 0o022 or not 0 <= info.st_size <= MAX_SOURCE_BYTES):
        raise ValueError('Source must be an owned, non-writable-by-others regular file within 4 GiB')
    return info


@contextmanager
def _checked_source(source):
    with ExitStack() as stack:
        supplied = None
        if isinstance(source, (str, os.PathLike)):
            path = Path(source).absolute()
        else:
            number = source if type(source) is int else source.fileno()
            if type(number) is not int:
                raise ValueError('Source fd must be an integer')
            supplied = os.dup(number)
            stack.callback(os.close, supplied)
            _file_info(supplied)
            name = getattr(source, 'name', None)
            path = Path(name).absolute() if isinstance(name, (str, os.PathLike)) else Path(
                os.readlink(f'/proc/self/fd/{supplied}'))
            if not path.is_absolute():
                raise ValueError('Source fd has no named absolute regular path')
        parent = stack.enter_context(directory(path.parent))
        fd = regular(parent, path.name)
        stack.callback(os.close, fd)
        before = _file_info(fd)
        if supplied is not None and identity(_file_info(supplied)) != identity(before):
            raise ValueError('Source fd and named file differ')
        digest = _digest(fd, before.st_size)
        if identity(_file_info(fd)) != identity(before):
            raise ValueError('Source changed during initial hash')
        yield fd, before.st_size, digest
        if identity(_file_info(fd)) != identity(before) or _digest(fd, before.st_size) != digest:
            raise ValueError('Source changed during readback')
        if identity(_file_info(fd)) != identity(before):
            raise ValueError('Source changed during readback hash')
        # Rewalk parents: a pinned old directory must not hide a rename or symlink swap.
        with directory(path.parent) as final_parent:
            final_fd = regular(final_parent, path.name)
            try:
                if identity(_file_info(final_fd)) != identity(before):
                    raise ValueError('Named source changed during read')
            finally:
                os.close(final_fd)


def _inspect(fd, size, digest):
    if size < 4:
        raise ValueError('Truncated WBI magic')
    first = _read_exact(fd, 0, min(size, 512))
    result = {'source_bytes': size, 'source_sha256': digest,
              'source_readback_sha256': digest,
              'has_wbi2_header': first[:4] == b'WBI2',
              'header_read_bytes': len(first),
              'header_read_sha256': hashlib.sha256(first).hexdigest(),
              'header': None, 'sections': [], 'structure_verified': False,
              'format_status': 'not_wbi2', 'data_checksum_status': 'not_checked',
              'kernel_checksum_status': 'not_checked', 'resume_executed': False,
              'fullboot_verified': False}
    if len(first) >= HEADER.size:
        values = HEADER.unpack_from(first)
        result['header'] = {'magic_hex': values[0].hex(),
                            **dict(zip(HEADER_FIELDS, values[1:]))}
    if not result['has_wbi2_header']:
        return result
    if size < 512:
        raise ValueError('Truncated WBI header sector')
    header = result['header']
    if header['flags'] & 4:
        raise ValueError('Unsupported WBI flag4: required data checksum is not implemented')
    # shortcut: only flags=0 raw images; add other formats only with verified decoding/checksums.
    if header['flags']:
        raise ValueError('Unsupported WBI flags: only uncompressed raw flags=0 is supported')
    count, real, original = header['sections'], header['r_data_size'], header['o_data_size']
    if header['sector_size'] != 512:
        raise ValueError('Unsupported WBI sector size')
    metadata = 512 + real
    table_end = metadata + count * SECTION.size
    if not 0 < count <= MAX_SECTIONS or real % 512 or table_end > size:
        raise ValueError('Invalid WBI section count or extent')
    rows, offset = [], 512
    raw_table = _read_exact(fd, metadata, count * SECTION.size)
    for index, fields in enumerate(SECTION.iter_unpack(raw_table)):
        row = dict(zip(SECTION_FIELDS, fields))
        if functools.reduce(operator.xor, fields[:6], SEED) != row['meta_cksum']:
            raise ValueError(f'Section {index} metadata checksum mismatch')
        addr, rlen, flag, olen = row['addr'], row['rlen'], row['flag'], row['olen']
        if flag & ~1 or not olen or addr % 4096 or olen % 4096:
            raise ValueError(f'Section {index} has unsupported flags/alignment')
        if addr + olen > UINT64_END or rlen != (0 if flag & 1 else olen) or offset + rlen > metadata:
            raise ValueError(f'Section {index} raw data length or physical boundary mismatch')
        row.update(index=index, file_offset=offset if rlen else None, zero_filled=bool(flag & 1))
        rows.append(row)
        offset += rlen
    if offset != metadata or sum(row['olen'] for row in rows) != original:
        raise ValueError('WBI data totals disagree with header')
    ordered = sorted(rows, key=lambda row: row['addr'])
    for left, right in zip(ordered, ordered[1:]):
        if left['addr'] + left['olen'] > right['addr']:
            raise ValueError('Overlapping WBI physical extents')
    result.update(sections=rows, structure_verified=True, format_status='supported_raw',
                  data_checksum_status='not_required_by_header', metadata_offset=metadata,
                  trailing_bytes=size - table_end, represented_bytes=original,
                  unknown_gap_bytes=ordered[-1]['addr'] + ordered[-1]['olen'] - ordered[0]['addr'] - original)
    return result


def inspect_wbi(source):
    """Return all 0x58 header/0x40 section fields and bounded raw-layout checks.

    Non-WBI2 (including a zero head) returns has_wbi2_header=False and
    structure_verified=False. Unsupported/malformed WBI2 raises ValueError.
    Header magic/structure checks never establish actual restoration.
    """
    with _checked_source(source) as (fd, size, digest):
        result = _inspect(fd, size, digest)
    return result


def _saved_range(fd, inspection, physical, size):
    if (type(physical) is not int or type(size) is not int or physical < 0 or
            not 0 < size <= MAX_READ_BYTES or physical + size > UINT64_END):
        raise ValueError('Invalid or oversized physical read range')
    if not inspection['structure_verified']:
        raise ValueError('No supported WBI snapshot layout')
    end, cursor, data = physical + size, physical, bytearray()
    for row in sorted(inspection['sections'], key=lambda row: row['addr']):
        stop = row['addr'] + row['olen']
        if stop <= cursor:
            continue
        if row['addr'] > cursor:
            break
        length = min(end, stop) - cursor
        data.extend(bytes(length) if row['zero_filled'] else _read_exact(
            fd, row['file_offset'] + cursor - row['addr'], length))
        cursor += length
        if cursor == end:
            return bytes(data)
    raise ValueError(f'Unrepresented physical range at {cursor:#x}; unknown holes are not zero')


def read_saved_range(source, inspection, physical, size):
    """Read at most MAX_READ_BYTES, spanning adjacent saved/explicit-zero extents.

    Reparse and compare the inspection to reject stale or caller-edited mappings.
    Any uncovered byte is an error, including holes inside the snapshot envelope.
    """
    with _checked_source(source) as (fd, length, digest):
        actual = _inspect(fd, length, digest)
        if type(inspection) is not dict or inspection != actual:
            raise ValueError('Inspection does not match the current source')
        result = _saved_range(fd, actual, physical, size)
    return result


def _load_facts():
    with _checked_source(FACTS_PATH) as (fd, size, digest):
        if size > 65536 or digest != FACTS_SHA256:
            raise ValueError('Sony 2.01 bound facts changed')
        facts = json.loads(_read_exact(fd, 0, size))
    return facts


def _binding(fd, size, digest, facts):
    if size == facts['raw_bytes'] and digest == facts['raw_sha256']:
        return 'official_raw'
    if size != facts['factory_bytes'] or _digest(fd, facts['raw_bytes']) != facts['raw_sha256']:
        return None
    for offset in range(facts['raw_bytes'], size, CHUNK_BYTES):
        if any(_read_exact(fd, offset, min(CHUNK_BYTES, size - offset))):
            return None
    return 'official_zero_padded'


def _compare_cache(source, ap_path, facts):
    """Internal fact injection for synthetic tests; public compare_cache pins its facts."""
    cache = facts['cache']
    with _checked_source(source) as (fd, size, digest), _checked_source(ap_path) as (ap, ap_size, ap_sha):
        result = {'source_bytes': size, 'source_sha256': digest,
                  'source_readback_sha256': digest, 'ap_sha256': ap_sha,
                  'ap_readback_sha256': ap_sha, 'reference_ap_sha256': cache['ap_sha256'],
                  'reference_ap_identity_matches': ap_sha == cache['ap_sha256'],
                  'binding': _binding(fd, size, digest, facts),
                  'cache_compatibility': 'unknown', 'checked_pages': 0,
                  'mismatches': [], 'pages': [], 'scope': cache['scope'],
                  'whole_image_compatibility': 'unknown', 'resume_executed': False,
                  'fullboot_verified': False}
        if result['binding'] is not None:
            inspection = _inspect(fd, size, digest)
            for anchor in cache['anchors']:
                index = anchor['file_page_index']
                descriptor = _saved_range(fd, inspection, int(anchor['descriptor'], 0), cache['descriptor_bytes'])
                mapping, saved_index = struct.unpack_from('<QQ', descriptor, 8)
                if mapping != int(cache['mapping'], 0) or saved_index != index:
                    raise ValueError('Bound cache descriptor mapping/index differs')
                saved = _saved_range(fd, inspection, int(anchor['physical'], 0), cache['page_bytes'])
                offset = index * cache['page_bytes']
                disk = _read_exact(ap, offset, min(cache['page_bytes'], max(0, ap_size - offset)))
                different = len(saved) - len(disk) + sum(a != b for a, b in zip(saved, disk))
                page = {'file_page_index': index, 'physical': anchor['physical'],
                        'descriptor': anchor['descriptor'], 'file_offset': offset,
                        'saved_sha256': hashlib.sha256(saved).hexdigest(),
                        'ap_sha256': hashlib.sha256(disk).hexdigest(),
                        'ap_bytes': len(disk), 'different_bytes': different}
                result['pages'].append(page)
                result['checked_pages'] += 1
                if different:
                    result['mismatches'].append(page)
            result['cache_compatibility'] = ('incompatible_at_checked_pages' if result['mismatches']
                                             else 'matched_at_checked_pages')
    return result


def compare_cache(source, ap_path):
    """Compare only four official-package cache anchors, after exact WBI binding.

    Accept the original 267171648-byte payload or that exact prefix zero-padded
    to 314572800 bytes. Unknown WBI hashes never use these anchors. Matching all
    checked pages leaves whole-image compatibility and actual resume unverified.
    """
    return _compare_cache(source, ap_path, _load_facts()['wbi'])
