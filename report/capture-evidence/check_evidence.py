#!/usr/bin/env python3
"""Bounded, read-only evidence inspection; never establishes firmware capture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
import warnings

OWN = Path(__file__).resolve().parent
CARD_SIZE = 134217728
MAX_FILE = 16 * 1024 * 1024
MAX_LOG = 32 * 1024 * 1024


def require(ok, why):
    if not ok:
        raise ValueError(why)


def open_owned(root, relative, limit):
    """Walk directory fds without following any symlink, including the leaf."""
    parts = Path(relative).parts
    require(parts and not Path(relative).is_absolute() and
            all(p not in ('.', '..') for p in parts), 'unsafe evidence path')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)
    try:
        info = os.fstat(leaf)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit,
                'not a bounded regular evidence file')
        return os.fdopen(leaf, 'rb')
    except BaseException:
        os.close(leaf)
        raise


def read_owned(root, relative, limit=MAX_FILE):
    with open_owned(root, relative, limit) as f:
        data = f.read(limit + 1)
        require(len(data) <= limit, 'evidence grew past bound')
        return data


def load_json(root, relative):
    value = json.loads(read_owned(root, relative))
    require(isinstance(value, dict), 'JSON object required')
    return value


def digest_file(f, snapshot=None):
    h = hashlib.sha256()
    size = 0
    for data in iter(lambda: f.read(1024 * 1024), b''):
        size += len(data)
        require(size <= CARD_SIZE, 'image grew past bound')
        h.update(data)
        if snapshot is not None:
            require(snapshot.write(data) == len(data), 'short private snapshot write')
    return size, h.hexdigest()


def jpeg_structure(data):
    """Single-scan marker bounds only; no entropy or pixel decoding."""
    require(data.startswith(b'\xff\xd8'), 'missing JPEG SOI')
    pos, sof, sos = 2, False, False
    while pos < len(data):
        require(data[pos] == 255, 'JPEG marker expected')
        while pos < len(data) and data[pos] == 255:
            pos += 1
        require(pos < len(data), 'truncated JPEG marker')
        marker = data[pos]
        pos += 1
        require(marker not in (0, 0xd8, 0xd9) and not 0xd0 <= marker <= 0xd7,
                'unexpected JPEG marker')
        require(pos + 2 <= len(data), 'truncated JPEG length')
        length = int.from_bytes(data[pos:pos + 2], 'big')
        require(length >= 2 and pos + length <= len(data), 'JPEG segment out of bounds')
        payload = data[pos + 2:pos + length]
        pos += length
        if marker in (0xc0, 0xc1, 0xc2):
            require(len(payload) >= 6 and payload[0] in (8, 12) and
                    int.from_bytes(payload[1:3], 'big') > 0 and
                    int.from_bytes(payload[3:5], 'big') > 0 and
                    1 <= payload[5] <= 4 and len(payload) == 6 + 3 * payload[5],
                    'invalid JPEG SOF')
            sof = True
        if marker == 0xda:
            require(sof and len(payload) >= 4 and 1 <= payload[0] <= 4 and
                    len(payload) == 4 + 2 * payload[0], 'invalid JPEG SOS')
            sos = True
            start = pos
            while pos < len(data):
                if data[pos] != 255:
                    pos += 1
                    continue
                require(pos + 1 < len(data), 'truncated JPEG entropy marker')
                nxt = data[pos + 1]
                if nxt == 255:
                    pos += 1  # legal marker fill; next iteration locates marker
                elif nxt == 0 or 0xd0 <= nxt <= 0xd7:
                    pos += 2
                elif nxt == 0xd9:
                    require(pos > start and pos + 2 == len(data), 'empty scan or trailing JPEG bytes')
                    return {'format': 'JPEG', 'structure_valid': sof and sos,
                            'decoded': False, 'scope': 'single scan SOI/SOF/SOS/EOI and segment bounds'}
                else:
                    raise ValueError('unsupported multi-scan/entropy marker')
    raise ValueError('missing JPEG EOI')


def mp4_structure(data):
    """Top-level ISO BMFF atom bounds; no track/sample or codec validation."""
    pos, atoms = 0, []
    while pos < len(data):
        require(len(atoms) < 4096 and pos + 8 <= len(data), 'MP4 atom header/budget')
        length, kind = struct.unpack_from('>I4s', data, pos)
        header = 8
        if length == 1:
            require(pos + 16 <= len(data), 'truncated extended MP4 atom')
            length, header = struct.unpack_from('>Q', data, pos + 8)[0], 16
        require(length >= header and pos + length <= len(data), 'MP4 atom length out of bounds/unsupported zero')
        if kind == b'ftyp':
            require(length >= header + 8 and (length - header - 8) % 4 == 0,
                    'invalid MP4 ftyp')
            brands = data[pos + header:pos + header + 4]
            brands += data[pos + header + 8:pos + length]
            require(any(b in (b'isom', b'iso2', b'mp41', b'mp42', b'avc1')
                        for b in [brands[i:i+4] for i in range(0, len(brands), 4)]),
                    'unsupported MP4 brand')
        atoms.append(kind.decode('ascii', 'replace'))
        pos += length
    require(all(k in atoms for k in ('ftyp', 'moov', 'mdat')), 'MP4 requires ftyp/moov/mdat')
    return {'format': 'MP4', 'structure_valid': True, 'decoded': False,
            'atoms': atoms, 'scope': 'top-level atoms only; tracks/samples unverified'}


def candidate(path, data):
    suffix = Path(path).suffix.lower()
    kind = 'JPEG' if data.startswith(b'\xff\xd8') else (
        'MP4' if len(data) >= 8 and data[4:8] == b'ftyp' else None)
    if kind is None and suffix not in ('.jpg', '.jpeg', '.mp4'):
        return None
    result = {'path': path, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'structure_valid': False, 'decoded': False, 'firmware_origin_verified': False}
    try:
        require(kind is not None, 'extension only; no supported container signature')
        result.update(jpeg_structure(data) if kind == 'JPEG' else mp4_structure(data))
    except ValueError as error:
        result['error'] = str(error)
    return result


class Fat16:
    def __init__(self, f, size):
        self.f, self.size = f, size
        b = self.read(0, 512)
        u16 = lambda n: struct.unpack_from('<H', b, n)[0]
        u32 = lambda n: struct.unpack_from('<I', b, n)[0]
        self.spc, reserved, fats = b[13], u16(14), b[16]
        roots, fat_sectors = u16(17), u16(22)
        total = u16(19) or u32(32)
        require(b[510:] == b'\x55\xaa' and u16(11) == 512 and
                self.spc in (1, 2, 4, 8, 16, 32, 64) and reserved > 0 and
                fats in (1, 2) and roots > 0 and roots % 16 == 0 and
                fat_sectors > 0 and total * 512 == size and u32(28) == 0,
                'unsupported/invalid FAT16 BPB (512B superfloppy only)')
        self.cluster_bytes = self.spc * 512
        self.root_offset = (reserved + fats * fat_sectors) * 512
        self.root_bytes = roots * 32
        self.data_offset = self.root_offset + self.root_bytes
        self.clusters = (size - self.data_offset) // self.cluster_bytes
        require(4085 <= self.clusters < 65525 and self.clusters + 1 < 0xfff0 and
                fat_sectors * 512 >= (self.clusters + 2) * 2,
                'unsupported FAT type or insufficient FAT capacity')
        self.fat = self.read(reserved * 512, fat_sectors * 512)
        require(self.fat[0] == b[21] and self.fat[1:4] == b'\xff\xff\xff', 'invalid reserved FAT entries')
        for n in range(1, fats):
            require(self.read((reserved + n * fat_sectors) * 512, len(self.fat)) == self.fat,
                    'FAT copies disagree')
        self.used, self.entries, self.candidates = set(), [], []
        self.lfn_skipped = 0
        self.read_budget = 64 * 1024 * 1024

    def read(self, offset, length):
        require(0 <= offset <= self.size and 0 <= length <= self.size - offset, 'disk read out of bounds')
        self.f.seek(offset)
        data = self.f.read(length)
        require(len(data) == length, 'truncated image')
        return data

    def chain(self, first, maximum):
        chain, seen = [], set()
        current = first
        while True:
            require(2 <= current <= self.clusters + 1 and current < 0xfff0,
                    'cluster out of range/reserved/free/bad')
            require(current not in seen and current not in self.used, 'cluster cycle/crosslink')
            seen.add(current)
            chain.append(current)
            require(len(chain) * self.cluster_bytes <= maximum, 'cluster chain exceeds size bound')
            current = struct.unpack_from('<H', self.fat, current * 2)[0]
            if current >= 0xfff8:
                break
        self.used.update(seen)
        return chain

    def content(self, chain, length):
        require(length <= self.read_budget, 'aggregate file read budget exceeded')
        self.read_budget -= length
        data = b''.join(self.read(self.data_offset + (c - 2) * self.cluster_bytes,
                                  self.cluster_bytes) for c in chain)
        return data[:length]

    def walk(self, raw=None, parent='', depth=0):
        require(depth <= 16, 'directory depth bound exceeded')
        if raw is None:
            raw = self.read(self.root_offset, self.root_bytes)
        for pos in range(0, len(raw), 32):
            e = raw[pos:pos+32]
            if e[0] == 0:
                break
            if e[0] == 0xe5:
                continue
            if e[11] == 15:
                self.lfn_skipped += 1
                continue
            if e[:11] in (b'.          ', b'..         '):
                require(bool(parent) and e[11] == 16, 'invalid dot directory entry')
                continue
            require(e[11] & 0xc0 == 0 and struct.unpack_from('<H', e, 20)[0] == 0,
                    'unsupported directory attributes/high cluster')
            if e[11] & 8:
                require(not e[11] & 16, 'invalid volume directory')
                continue
            require(all(32 <= c < 127 and c not in b'"*+,/:;<=>?[\\]|' for c in e[:11]),
                    'unsafe/unsupported short name')
            base, ext = e[:8].decode('ascii').rstrip(), e[8:11].decode('ascii').rstrip()
            require(bool(base) and base not in ('.', '..'), 'invalid short name')
            name = base + ('.' + ext if ext else '')
            path = parent + '/' + name
            require(not any(x['path'] == path for x in self.entries), 'duplicate directory entry')
            directory = bool(e[11] & 16)
            first, length = struct.unpack_from('<H', e, 26)[0], struct.unpack_from('<I', e, 28)[0]
            require(len(self.entries) < 4096 and length <= MAX_FILE, 'file/entry size budget exceeded')
            item = {'path': path, 'bytes': length, 'directory': directory}
            self.entries.append(item)
            if directory:
                require(length == 0, 'directory has nonzero size')
                chain = self.chain(first, 1024 * 1024)
                self.walk(self.content(chain, len(chain) * self.cluster_bytes), path, depth + 1)
            elif length:
                capacity = ((length + self.cluster_bytes - 1) // self.cluster_bytes) * self.cluster_bytes
                chain = self.chain(first, capacity)
                require(len(chain) * self.cluster_bytes == capacity, 'file chain shorter than size')
                data = self.content(chain, length)
                item['sha256'] = hashlib.sha256(data).hexdigest()
                c = candidate(path, data)
                if c:
                    self.candidates.append(c)
            else:
                require(first == 0, 'empty file owns clusters')
                c = candidate(path, b'')
                if c:
                    self.candidates.append(c)


def png_digest(file):
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(file) as im:
                require(im.format == 'PNG' and im.size == (640, 480),
                        'original LCD PNG must be 640x480')
                return {'rgb_sha256': hashlib.sha256(im.convert('RGB').tobytes()).hexdigest(),
                        'width': im.width, 'height': im.height}
    except Image.DecompressionBombError as error:
        raise ValueError('PNG decompression dimensions exceed safety bound') from error


def check_input(root, proof, expected):
    data = read_owned(root, 'console.log', MAX_LOG)
    events = []
    last = -1
    for line in data.decode('utf-8', 'replace').splitlines():
        if 'OBS INPUT_EVENT32 ' not in line:
            continue
        match = re.search(r'OBS INPUT_EVENT32 n=(\d+) tid=(\d+) words=\[([^\]]+)\]', line)
        require(match is not None, 'malformed original INPUT_EVENT32')
        words = [int(w.strip(), 0) for w in match[3].split(',')]
        require(len(words) == 8 and all(0 <= w <= 0xffffffff for w in words), 'invalid INPUT_EVENT32 words')
        seq = int(match[1])
        require(seq > last, 'INPUT_EVENT32 sequence not increasing')
        last = seq
        events.append({'sequence': seq, 'key': words[0], 'status': words[2]})
    cursor, matches = 0, []
    for key, status in expected:
        while cursor < len(events) and (events[cursor]['key'], events[cursor]['status']) != (key, status):
            cursor += 1
        require(cursor < len(events), f'missing ordered key/status {key:#x}:{status}')
        matches.append(events[cursor])
        cursor += 1
    # Other keys may interleave, but the selected keys must have exactly the requested order.
    selected = [e for e in events if e['key'] in {k for k, _ in expected}]
    require([(e['key'], e['status']) for e in selected] == expected,
            'selected-key status stream differs from expected')
    rows = []
    images = proof.get('images')
    require(isinstance(images, list) and 0 < len(images) <= 256, 'invalid PNG proof images')
    for row in images:
        require(isinstance(row, dict), 'PNG proof row must be an object')
        result = {'image': row.get('image'), 'ok': False}
        try:
            with open_owned(root, row['image'], MAX_FILE) as f:
                result.update(png_digest(f))
                result['ok'] = result['rgb_sha256'] == row.get('pixel_sha256')
        except (ImportError, OSError, ValueError, KeyError, TypeError, Warning) as error:
            result['error'] = f'{type(error).__name__}: {error}'
        rows.append(result)
    return {'ok': all(r['ok'] for r in rows), 'ordered_original_events': matches,
            'expected': expected, 'console_sha256': hashlib.sha256(data).hexdigest(),
            'png': rows, 'png_digest_mode': 'SHA256(decoded RGB bytes); Pillow required'}


def check_disk(root):
    report = load_json(root, 'SD/export.json')
    # Hash and parse the SAME private byte snapshot. Re-reading the live source
    # fd for FAT after hashing could bind its digest to a different tree.
    with open_owned(root, 'SD/card.img', CARD_SIZE) as f, tempfile.TemporaryFile() as snapshot:
        space = os.fstatvfs(snapshot.fileno())
        require(space.f_bavail * space.f_frsize >= CARD_SIZE + 1024 * 1024,
                'insufficient private snapshot space')
        size, sha = digest_file(f, snapshot)
        snapshot.flush()
        require(size == CARD_SIZE and report.get('expected_total') == CARD_SIZE,
                'card size must be fixed 134217728 bytes')
        require(report.get('sha256') == sha, 'export/card SHA256 mismatch')
        q, life = report.get('quiesce', {}), report.get('flush_lifecycle', {})
        require(report.get('ok') is True and report.get('card_published') is True and
                type(report.get('fsck_rc')) is int and report['fsck_rc'] == 0,
                'export/fsck result not successful')
        require(type(q) is dict and type(life) is dict and
                type(q.get('original_Fsys_FlushVolume_rc')) is int and
                q['original_Fsys_FlushVolume_rc'] == 0 and q.get('owner_stopped') is True and
                life.get('ok') is True and life.get('resumed') is True and life.get('status') == 'resumed' and
                type(report.get('sequence')) is int and
                report['sequence'] == q.get('sequence') == life.get('sequence') and
                type(q.get('pid')) is int and q['pid'] > 0 and q['pid'] == life.get('pid'),
                'quiesce/resumed sequence/pid mismatch')
        evidence = report.get('evidence', '')
        require(re.fullmatch(r'export-[0-9a-f]{32}', evidence) is not None, 'unsafe fsck record path')
        fsck = read_owned(root, f'SD/{evidence}/fsck.txt', 65536).decode('utf-8', 'replace')
        require('fsck.fat ' in fsck and re.search(r'\d+ files, \d+/\d+ clusters', fsck),
                'missing recognized fsck record')
        fat = Fat16(snapshot, size)
        fat.walk()
        return ({'ok': True, 'bytes': size, 'sha256': sha, 'fsck_record': fsck,
                 'fsck_record_sha256': hashlib.sha256(fsck.encode()).hexdigest(),
                 'fsck_reexecuted': False, 'resumed_record_checked': True,
                 'tree_and_hash_share_private_snapshot': True,
                 'source_atomic_snapshot_claimed': False,
                 'entries': fat.entries, 'lfn_entries_ignored': fat.lfn_skipped,
                 'lfn_policy': 'all LFN records ignored, including malformed; use validated short name only'},
                fat.candidates)


def inspect(root, expected):
    result = {'input': {'ok': False}, 'disk': {'ok': False},
              'artifactCandidate': {'items': [], 'decoded': False},
              'firmwareCaptureProof': {'capture_verified': False,
                  'reason': 'requires independent original capture → encoder → Fsys/lease evidence; not implemented'}}
    try:
        result['input'] = check_input(root, load_json(root, 'gtk-input-proof.json'), expected)
    except (OSError, ValueError, TypeError, KeyError) as error:
        result['input']['error'] = f'{type(error).__name__}: {error}'
    try:
        disk, items = check_disk(root)
        result['disk'], result['artifactCandidate']['items'] = disk, items
    except (OSError, ValueError, TypeError, KeyError, struct.error) as error:
        result['disk']['error'] = f'{type(error).__name__}: {error}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='explicit owned evidence run; no discovery')
    parser.add_argument('--expect', required=True, help='ordered key:status pairs, e.g. 0xa7:1,0xa7:0')
    parser.add_argument('--output', type=Path, help='new JSON directly beside this tool; omit for stdout')
    args = parser.parse_args()
    try:
        require(args.run.is_absolute() and not args.run.is_symlink() and args.run.is_dir(),
                'run must be explicit absolute nonsymlink directory')
        expected = [tuple(int(n, 0) for n in pair.split(':')) for pair in args.expect.split(',')]
        require(0 < len(expected) <= 512 and all(len(p) == 2 and 0 <= p[0] <= 0xffffffff and 0 <= p[1] <= 0xffffffff
                                               for p in expected), 'invalid expected key/status list')
        if args.output:
            require(args.output.is_absolute() and args.output.parent.resolve() == OWN and
                    args.output.parent == OWN and not args.output.exists() and
                    not args.output.is_symlink(), 'output must be new file directly inside tool directory')
            require(not OWN.is_relative_to(args.run.resolve()), 'output cannot be inside run')
        result = inspect(args.run, expected)
        text = json.dumps(result, indent=2) + '\n'
        if args.output:
            with args.output.open('x', encoding='utf-8') as f:
                f.write(text)
        else:
            print(text, end='')
        return 0 if result['input']['ok'] and result['disk']['ok'] else 1
    except (OSError, ValueError) as error:
        parser.exit(2, f'{type(error).__name__}: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
