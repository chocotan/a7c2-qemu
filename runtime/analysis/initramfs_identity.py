"""Verify bytes in a raw newc image without extracting or executing its files."""
import hashlib
from pathlib import PurePosixPath
import stat


def verify_image(image, expected):
    found = {}
    entries, parents = {}, set()
    with image.open('rb') as stream:
        size = image.stat().st_size
        while True:
            header = stream.read(110)
            if len(header) != 110 or header[:6] != b'070701':
                raise ValueError('Selected initramfs has an incomplete or unsupported newc header')
            fields = [int(header[i:i+8], 16) for i in range(6, 110, 8)]
            _, mode, _, _, links, _, length, _, _, _, _, namesize, _ = fields
            if not 1 <= namesize <= 4096:
                raise ValueError('Selected initramfs filename length differs')
            raw = stream.read(namesize)
            if len(raw) != namesize or raw[-1:] != b'\0' or b'\0' in raw[:-1]:
                raise ValueError('Selected initramfs filename is incomplete or ambiguous')
            name = raw[:-1].decode('utf-8')
            stream.seek((-stream.tell()) % 4, 1)
            if stream.tell() + length > size:
                raise ValueError('Selected initramfs entry is truncated')
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Selected initramfs contains a nonlocal path')
            name = str(path)
            if name == 'TRAILER!!!':
                if length or any(stream.read()):
                    raise ValueError('Selected initramfs trailer is ambiguous')
                break
            ancestors = [str(p) for p in path.parents if str(p) != '.']
            if name in entries or any(p in entries and not stat.S_ISDIR(entries[p]) for p in ancestors):
                raise ValueError('Selected initramfs has duplicate paths or a nondirectory ancestor')
            if name in parents and not stat.S_ISDIR(mode):
                raise ValueError('Selected initramfs replaces an ancestor with a nondirectory')
            entries[name] = mode
            parents.update(ancestors)
            if name in expected:
                if name in found or not stat.S_ISREG(mode) or links != 1:
                    raise ValueError(f'Selected initramfs identity is not a unique regular file: {name}')
                digest = hashlib.sha256()
                remaining = length
                while remaining:
                    data = stream.read(min(remaining, 1024 * 1024))
                    if not data:
                        raise ValueError('Selected initramfs file is truncated')
                    digest.update(data); remaining -= len(data)
                found[name] = digest.hexdigest()
                if found[name] != expected[name]:
                    raise ValueError(f'Selected initramfs content differs: {name}')
            else:
                stream.seek(length, 1)
            stream.seek((-stream.tell()) % 4, 1)
    if found.keys() != expected.keys():
        raise ValueError(f'Selected initramfs identity files missing: {sorted(expected.keys() - found.keys())}')
    return found
