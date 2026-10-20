#!/usr/bin/env python3
"""Manage run_dir/SD/card.img without opening devices or following symlinks.

ensure creates a missing run directory and card; verify never changes card bytes.
Both print JSON and atomically replace SD/card.json (including on failure). Exit
0 means size, FAT BPB and fsck.fat -n all passed. No force/overwrite operation.

Probe integration: ensure RUN before building with MENU_SD_IMAGE=RUN/SD/card.img;
copy guest /simulation/sd-card.fat to its RM backing before startup. After guest
flush/export, save the exported image back to RUN/SD/card.img and verify RUN.
Reuse the same RUN to retain the same card. Serialize guest export and this tool.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE / 'menu-root/simulation/media-template.fat'
IMAGE_BYTES = 4 * 1024 * 1024
TEMPLATE_SHA256 = 'f9f321b5c4768fe9c703cbac8b17b94aaa78b59a5e7da8497b7cdc2020f62b1e'
REPORT = 'card.json'


@contextmanager
def directory(path, create=False):
    """Pin every ancestor with openat/O_NOFOLLOW, including the run directory."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('parent traversal (..) is not permitted')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@contextmanager
def regular_file(parent, name):
    # O_NONBLOCK prevents a malicious FIFO from hanging before fstat rejects it.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f'{name}: expected a regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            yield stream
    finally:
        os.close(fd)


def publish(parent, name, data, replace):
    """Fsync and publish complete bytes; card installation is exclusive."""
    temporary = f'.{name}.{uuid.uuid4().hex}.tmp'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent,
                    follow_symlinks=False)
        os.fsync(parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass


def save_report(parent, result):
    try:
        old = os.stat(REPORT, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(old.st_mode):
            raise ValueError(f'{REPORT}: expected a regular file')
    publish(parent, REPORT, (json.dumps(result, sort_keys=True) + '\n').encode(), True)


def bpb(raw):
    def u16(offset):
        return int.from_bytes(raw[offset:offset + 2], 'little')

    total16 = u16(19)
    total32 = int.from_bytes(raw[32:36], 'little')
    fields = {'sector_bytes': u16(11), 'cluster_sectors': raw[13],
              'reserved_sectors': u16(14), 'fats': raw[16],
              'root_entries': u16(17), 'total_sectors': total16 or total32,
              'fat_sectors': u16(22), 'media': raw[21]}
    cluster = fields['cluster_sectors']
    root = (fields['root_entries'] * 32 + 511) // 512
    data_sectors = fields['total_sectors'] - fields['reserved_sectors'] - fields['fats'] * fields['fat_sectors'] - root
    if (raw[510:512] != b'\x55\xaa' or fields['sector_bytes'] != 512 or
            fields['total_sectors'] != IMAGE_BYTES // 512 or (total16 and total32) or
            cluster == 0 or cluster > 128 or cluster & (cluster - 1) or
            not fields['reserved_sectors'] or fields['fats'] not in (1, 2) or
            not fields['root_entries'] or not fields['fat_sectors'] or
            fields['media'] not in (0xf0, *range(0xf8, 0x100)) or data_sectors <= 0):
        raise ValueError('invalid FAT12/16 BPB geometry/signature')
    clusters = data_sectors // cluster
    if not 0 < clusters < 65525:
        raise ValueError('invalid FAT12/16 cluster count')
    fat_bytes = ((clusters + 2) * (12 if clusters < 4085 else 16) + 7) // 8
    if fields['fat_sectors'] * 512 < fat_bytes:
        raise ValueError('BPB FAT table is too small')
    fields['fat_bits'] = 12 if clusters < 4085 else 16
    return fields


def validate(parent, result):
    with regular_file(parent, 'card.img') as stream:
        before = os.fstat(stream.fileno())
        result['bytes'] = before.st_size
        if before.st_size != IMAGE_BYTES:
            raise ValueError(f'card.img must be exactly {IMAGE_BYTES} bytes')
        raw = stream.read(IMAGE_BYTES + 1)
        if len(raw) != IMAGE_BYTES:
            raise ValueError('card.img changed size during read')
        result['sha256'] = hashlib.sha256(raw).hexdigest()
        result['bpb'] = bpb(raw)
        # Pass the pinned read-only descriptor, never reopen a user pathname.
        checked = subprocess.run(['fsck.fat', '-n', f'/proc/self/fd/{stream.fileno()}'],
                                 pass_fds=(stream.fileno(),), capture_output=True,
                                 text=True, timeout=30)
        result['fsck_rc'] = checked.returncode
        result['fsck_output'] = checked.stdout + checked.stderr
        if checked.returncode != 0:
            raise ValueError('fsck.fat -n failed')
        after = os.fstat(stream.fileno())
        named = os.stat('card.img', dir_fd=parent, follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(named):
            raise ValueError('card.img identity/content changed during validation')


def run(command, run_dir):
    card = Path(run_dir).absolute() / 'SD/card.img'
    result = {'ok': False, 'command': command, 'path': str(card), 'bytes': None,
              'sha256': None, 'created': False, 'fsck_rc': None,
              'error': 'validation did not complete'}
    try:
        with directory(card.parent, create=command == 'ensure') as parent:
            save_report(parent, result)
            try:
                if command == 'ensure':
                    try:
                        os.stat('card.img', dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        with directory(TEMPLATE.parent) as source:
                            with regular_file(source, TEMPLATE.name) as stream:
                                raw = stream.read(IMAGE_BYTES + 1)
                        if len(raw) != IMAGE_BYTES or hashlib.sha256(raw).hexdigest() != TEMPLATE_SHA256:
                            raise ValueError('media template size/SHA256 differs from the pinned fixture')
                        publish(parent, 'card.img', raw, False)
                        result['created'] = True
                validate(parent, result)
                result['ok'] = True
                del result['error']
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                result.update(ok=False, error=str(error))
            save_report(parent, result)
    except (OSError, ValueError) as error:
        result.update(ok=False, error=str(error))
    print(json.dumps(result, sort_keys=True))
    return 0 if result['ok'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('command', choices=('ensure', 'verify'))
    parser.add_argument('run_dir', help='reuse this directory to reuse its SD card')
    args = parser.parse_args()
    return run(args.command, args.run_dir)


if __name__ == '__main__':
    sys.exit(main())
