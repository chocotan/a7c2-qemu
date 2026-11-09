"""Lossless sparse delivery for the product's ordinary 1 GiB virtual SD card.

Only nonzero 4 KiB blocks enter RAM0. The guest reconstructs and hashes the full
ordinary image before original Fsys consumes it; no host block device is used.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil

from sd_transport import card_source

TOTAL = 1024**3
BLOCK = 4096
MAX_CHUNK = 4 * 1024**2
MAX_CHUNKS = 4096
MAX_DATA = 384 * 1024**2


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build(source, destination):
    """Create a fresh seed directory; failures remain for diagnosis."""
    destination = Path(destination).absolute()
    if '..' in destination.parts or destination.exists() or destination.is_symlink():
        raise ValueError('Sparse seed requires a fresh ordinary destination')
    if shutil.disk_usage(destination.parent).free < TOTAL + 64 * 1024**3:
        raise ValueError('Sparse seed/export requires 1 GiB plus the 64 GiB reserve')
    destination.mkdir(mode=0o700)
    rows = []
    pending = bytearray()
    pending_offset = 0
    data_bytes = 0
    full = hashlib.sha256()

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
            os.fsync(stream.fileno())
        with path.open('rb') as stream:
            actual = stream.read(len(raw) + 1)
        if actual != raw:
            raise ValueError('Seed chunk readback differs')
        rows.append({'offset': pending_offset, 'length': len(raw), 'file': name,
                     'sha256': digest(raw)})
        data_bytes += len(raw)
        pending = bytearray()

    with card_source(source) as fd:
        before = os.fstat(fd)
        if before.st_size != TOTAL:
            raise ValueError('The product camera SD must be exactly 1 GiB')
        for offset in range(0, TOTAL, BLOCK):
            raw = os.pread(fd, BLOCK, offset)
            if len(raw) != BLOCK:
                raise ValueError('Short virtual SD read')
            full.update(raw)
            if any(raw):
                if not pending:
                    pending_offset = offset
                pending.extend(raw)
                if len(pending) >= MAX_CHUNK:
                    flush()
            else:
                flush()
        flush()
        if os.fstat(fd).st_size != TOTAL:
            raise ValueError('Virtual SD size changed while packaging')

    # Independently visit every logical block, using only the packaged chunks.
    for row in rows:
        if row['offset'] % BLOCK or row['length'] % BLOCK or row['length'] > MAX_CHUNK:
            raise ValueError('Unaligned/oversized sparse seed chunk')
    actual = hashlib.sha256()
    index = 0
    stream = None
    try:
        for offset in range(0, TOTAL, BLOCK):
            while index < len(rows) and offset >= rows[index]['offset'] + rows[index]['length']:
                if stream is not None:
                    stream.close()
                    stream = None
                index += 1
            if index < len(rows) and rows[index]['offset'] == offset:
                stream = (destination / rows[index]['file']).open('rb')
            if stream is not None:
                raw = stream.read(BLOCK)
                if len(raw) != BLOCK:
                    raise ValueError('Short packaged chunk during reconstruction')
            else:
                raw = bytes(BLOCK)
            actual.update(raw)
    finally:
        if stream is not None:
            stream.close()
    if actual.hexdigest() != full.hexdigest():
        raise ValueError('Sparse seed does not reconstruct the original full-card SHA')

    zero = destination/'zero.bin'
    with zero.open('xb') as stream:
        stream.write(bytes(BLOCK));stream.flush();os.fsync(stream.fileno())
    if zero.read_bytes()!=bytes(BLOCK):
        raise ValueError('Terminal zero-block readback differs')
    manifest = {'schema': 'a7c2-sparse-sd-seed-v1', 'bytes': TOTAL,
                'sha256': full.hexdigest(), 'block_bytes': BLOCK, 'data_bytes': data_bytes,
                'chunks': rows, 'terminal_zero_file': 'zero.bin', 'source': str(Path(source).absolute()),
                'representation_only': True, 'physical_device': False}
    (destination / 'identity.txt').write_text(f"{TOTAL} {full.hexdigest()}\n", encoding='ascii')
    (destination / 'chunks.txt').write_text(''.join(
        f"{row['offset']} {row['length']} {row['file']} {row['sha256']}\n" for row in rows), encoding='ascii')
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for name in ('identity.txt', 'chunks.txt', 'manifest.json'):
        path = destination / name
        if path.stat().st_size > 16 * 1024**2:
            raise ValueError('Seed metadata exceeds bound')
    return manifest
