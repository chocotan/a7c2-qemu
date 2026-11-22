"""Lossless sparse delivery for the product's ordinary 1 GiB virtual SD card.

Only nonzero 4 KiB blocks enter RAM0. The guest reconstructs and hashes the full
ordinary image before original Fsys consumes it; no host block device is used.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

from sd_transport import card_source, identity

TOTAL = 4 * 1024**3
VALID_TOTALS = (1024**3, 4 * 1024**3)
BLOCK = 4096
MAX_CHUNK = 4 * 1024**2
MAX_CHUNKS = 4096
MAX_DATA = 384 * 1024**2


def digest(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def _source(source, source_fd):
    """A supplied FD is the input capability; never reopen its descriptive path."""
    if source_fd is None:
        with card_source(source) as fd:
            yield fd
        return
    if type(source_fd) is not int or source_fd < 0:
        raise ValueError('Sparse seed requires an exact caller-held source FD')
    fd = os.dup(source_fd)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600 or
                fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            raise ValueError('Sparse seed FD requires owned single-link 0600 read-only input')
        yield fd
        after = os.fstat(fd)
        if (identity(before) != identity(after) or before.st_mode != after.st_mode or
                before.st_nlink != after.st_nlink or before.st_uid != after.st_uid):
            raise ValueError('Sparse seed FD identity changed while packaging')
    finally:
        os.close(fd)


SCAN_CHUNK = 1024 * 1024
_ZERO_SCAN = bytes(SCAN_CHUNK)
_ZERO_BLOCK = bytes(BLOCK)


def _apply_manifest_source(destination, manifest, source_label):
    updated = dict(manifest, source=source_label)
    (destination / 'manifest.json').write_text(json.dumps(updated, indent=2) + '\n')
    return updated


def _cache_base():
    cold_dir = Path(__file__).resolve().parent / 'cold'
    return cold_dir / '.cache' if cold_dir.is_dir() else None


def _try_cache_reuse(source, destination, verify_sha):
    src = Path(source)
    cache_base = _cache_base()
    if not src.is_file() or cache_base is None:
        return None
    cache_dir = cache_base / 'sd-seed-noshacache'
    stamp_path = cache_dir / 'stamp.json'
    manifest_path = cache_dir / 'manifest.json'
    if not (stamp_path.is_file() and manifest_path.is_file()):
        return None
    try:
        st = src.stat()
        want = {'source': str(src.resolve()), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
                'verify_sha': bool(verify_sha)}
        if json.loads(stamp_path.read_text()) != want:
            return None
        cached = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    required = ['identity.txt', 'chunks.txt', 'manifest.json', 'zero.bin'] + [row['file'] for row in cached.get('chunks', [])]
    if not all((cache_dir / name).is_file() for name in required):
        return None
    destination.mkdir(mode=0o700)
    for name in required:
        shutil.copyfile(cache_dir / name, destination / name)
    return _apply_manifest_source(destination, cached, str(src.absolute()))


def _save_cache(source, destination, manifest, verify_sha):
    src = Path(source)
    cache_base = _cache_base()
    if not src.is_file() or cache_base is None:
        return
    cache_dir = cache_base / 'sd-seed-noshacache'
    tmp_dir = cache_base / f'sd-seed.{os.getpid()}.tmp'
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        names = ['identity.txt', 'chunks.txt', 'manifest.json', 'zero.bin'] + [row['file'] for row in manifest.get('chunks', [])]
        for name in names:
            shutil.copyfile(destination / name, tmp_dir / name)
        st = src.stat()
        stamp = {'source': str(src.resolve()), 'size': st.st_size, 'mtime_ns': st.st_mtime_ns,
                 'verify_sha': bool(verify_sha)}
        (tmp_dir / 'stamp.json').write_text(json.dumps(stamp, sort_keys=True) + '\n')
        old = cache_base / f'sd-seed.old.{os.getpid()}'
        if cache_dir.exists():
            cache_dir.replace(old)
            shutil.rmtree(old, ignore_errors=True)
        tmp_dir.replace(cache_dir)
    except OSError:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def build(source, destination, *, source_fd=None, verify_sha=True):
    """Create a fresh seed directory; failures remain for diagnosis.

    source_fd is an optional borrowed, read-only capability. The caller keeps its
    lease until packaging and later consumption finish; source is then a label.
    """
    destination = Path(destination).absolute()
    if '..' in destination.parts or destination.exists() or destination.is_symlink():
        raise ValueError('Sparse seed requires a fresh ordinary destination')
    if shutil.disk_usage(destination.parent).free < TOTAL + 64 * 1024**3:
        raise ValueError('Sparse seed/export requires 4 GiB plus the 64 GiB reserve')
    if not verify_sha and source_fd is None:
        cached = _try_cache_reuse(source, destination, verify_sha)
        if cached is not None:
            return cached
    destination.mkdir(mode=0o700)
    rows = []
    pending = bytearray()
    pending_offset = 0
    data_bytes = 0
    full = hashlib.sha256() if verify_sha else None
    zero_hex = '0' * 64

    def flush():
        nonlocal pending, pending_offset, data_bytes
        if not pending:
            return
        if len(rows) >= MAX_CHUNKS or len(pending) > MAX_DATA - data_bytes:
            raise ValueError('Nonzero SD content exceeds the bounded RAM0 seed budget')
        name = f'chunk-{len(rows):06d}.bin'
        raw = bytes(pending)
        path = destination / name
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            if verify_sha:
                os.fsync(stream.fileno())
        if verify_sha:
            with path.open('rb') as stream:
                actual_raw = stream.read(len(raw) + 1)
            if actual_raw != raw:
                raise ValueError('Seed chunk readback differs')
        rows.append({'offset': pending_offset, 'length': len(raw), 'file': name,
                     'sha256': digest(raw) if verify_sha else zero_hex})
        data_bytes += len(raw)
        pending = bytearray()

    def scan_chunk(big_offset, chunk):
        nonlocal pending_offset
        if full is not None:
            full.update(chunk)
        if chunk == _ZERO_SCAN[:len(chunk)]:
            flush()
            return
        view = memoryview(chunk)
        for inner in range(0, len(chunk), BLOCK):
            raw = view[inner:inner + BLOCK]
            if raw != _ZERO_BLOCK:
                if not pending:
                    pending_offset = big_offset + inner
                pending.extend(raw)
                if len(pending) >= MAX_CHUNK:
                    flush()
            else:
                flush()

    with _source(source, source_fd) as fd:
        before = os.fstat(fd)
        total = before.st_size
        if total not in VALID_TOTALS:
            raise ValueError('The product camera SD must be 1 GiB or 4 GiB')
        used_seek_data = False
        if not verify_sha and hasattr(os, 'SEEK_DATA') and hasattr(os, 'SEEK_HOLE'):
            try:
                cursor = 0
                while cursor < total:
                    try:
                        data_start = os.lseek(fd, cursor, os.SEEK_DATA)
                    except OSError as exc:
                        if exc.errno == 6:  # ENXIO: no more data extents
                            flush()
                            break
                        raise
                    if data_start >= total:
                        flush()
                        break
                    aligned_start = (data_start // BLOCK) * BLOCK
                    if aligned_start > cursor:
                        flush()
                    hole_start = os.lseek(fd, data_start, os.SEEK_HOLE)
                    aligned_end = min(total, ((hole_start + BLOCK - 1) // BLOCK) * BLOCK)
                    pos = aligned_start
                    while pos < aligned_end:
                        step = min(SCAN_CHUNK, aligned_end - pos)
                        chunk = os.pread(fd, step, pos)
                        if len(chunk) != step:
                            raise ValueError('Short virtual SD read')
                        scan_chunk(pos, chunk)
                        pos += step
                    cursor = aligned_end
                used_seek_data = True
            except OSError:
                for row in rows:
                    (destination / row['file']).unlink(missing_ok=True)
                rows.clear()
                pending.clear()
                data_bytes = 0
                used_seek_data = False
        if not used_seek_data:
            for big_offset in range(0, total, SCAN_CHUNK):
                chunk = os.pread(fd, SCAN_CHUNK, big_offset)
                if len(chunk) != SCAN_CHUNK:
                    raise ValueError('Short virtual SD read')
                scan_chunk(big_offset, chunk)
        flush()
        if os.fstat(fd).st_size != total:
            raise ValueError('Virtual SD size changed while packaging')

    # Independently visit every logical block when verify_sha is enabled.
    for row in rows:
        if row['offset'] % BLOCK or row['length'] % BLOCK or row['length'] > MAX_CHUNK:
            raise ValueError('Unaligned/oversized sparse seed chunk')
    if verify_sha:
        actual = hashlib.sha256()
        cursor = 0
        for row in rows:
            gap = row['offset'] - cursor
            while gap > 0:
                step = min(gap, SCAN_CHUNK)
                actual.update(_ZERO_SCAN if step == SCAN_CHUNK else _ZERO_SCAN[:step])
                gap -= step
            raw = (destination / row['file']).read_bytes()
            if len(raw) != row['length']:
                raise ValueError('Short packaged chunk during reconstruction')
            actual.update(raw)
            cursor = row['offset'] + row['length']
        gap = total - cursor
        while gap > 0:
            step = min(gap, SCAN_CHUNK)
            actual.update(_ZERO_SCAN if step == SCAN_CHUNK else _ZERO_SCAN[:step])
            gap -= step
        if actual.hexdigest() != full.hexdigest():
            raise ValueError('Sparse seed does not reconstruct the original full-card SHA')

    zero = destination / 'zero.bin'
    with zero.open('xb') as stream:
        stream.write(_ZERO_BLOCK)
        stream.flush()
        if verify_sha:
            os.fsync(stream.fileno())
    if verify_sha and zero.read_bytes() != _ZERO_BLOCK:
        raise ValueError('Terminal zero-block readback differs')
    full_hex = full.hexdigest() if full is not None else zero_hex
    manifest = {'schema': 'a7c2-sparse-sd-seed-v1', 'bytes': total,
                'sha256': full.hexdigest() if verify_sha else None,
                'sha_verified': bool(verify_sha),
                'block_bytes': BLOCK, 'data_bytes': data_bytes,
                'chunks': rows, 'terminal_zero_file': 'zero.bin', 'source': str(Path(source).absolute()),
                'representation_only': True, 'physical_device': False}
    (destination / 'identity.txt').write_text(f"{total} {full_hex}\n", encoding='ascii')
    (destination / 'chunks.txt').write_text(''.join(
        f"{row['offset']} {row['length']} {row['file']} {row['sha256']}\n" for row in rows), encoding='ascii')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for name in ('identity.txt', 'chunks.txt', 'manifest.json'):
        path = destination / name
        if path.stat().st_size > 16 * 1024**2:
            raise ValueError('Seed metadata exceeds bound')
    if not verify_sha and source_fd is None:
        _save_cache(source, destination, manifest, verify_sha)
    return manifest
