#!/usr/bin/env python3
"""Private configuration staging, rollback, and explicit interrupted-commit recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
exclusive_runtime = runpy.run_path(str(HERE / 'runtime-lock.py'))['exclusive_runtime']
TARGETS = {'root/partitions/nflasha2.img', 'full-system.cpio', 'full-system.json',
           'config-generation.json', 'official-pp.bin', 'reset-record.json', 'runs'}
MARKER = '.config-transaction.json'


def mtools(name):
    candidate = HERE / 'runtime/analysis/mtools-arch-yRYM5W/extracted/usr/bin' / name
    found = candidate if candidate.is_file() else shutil.which(name)
    if not found:
        raise RuntimeError(name + ' is unavailable')
    return Path(found)


def tool(name, image, *args):
    return subprocess.run([str(mtools(name)), '-i', str(image), *map(str, args)],
                          capture_output=True, timeout=60,
                          env={**os.environ, 'MTOOLS_SKIP_CHECK': '1'})


def read_regular(path, *, expected=None, limit=4 * 1024**2):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_size > limit
                or expected is not None and before.st_size != expected):
            raise ValueError('unexpected source file type/size: ' + str(path))
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if len(data) != before.st_size or identity(before) != identity(after):
            raise ValueError('source changed during snapshot: ' + str(path))
        return data


def extract(image, target):
    with tempfile.TemporaryDirectory(prefix='config-read-') as directory:
        path = Path(directory) / 'data'
        result = tool('mcopy', image, '::/' + target, path)
        if result.returncode == 0:
            return path.read_bytes()
        listing = tool('mdir', image, '-b', '::/')
        names = {line.rstrip('/').rsplit('/', 1)[-1].casefold()
                 for line in listing.stdout.decode('utf-8', errors='strict').splitlines()}
        if listing.returncode == 0 and target.casefold() not in names:
            return None
        raise RuntimeError('cannot read ' + target + ': ' + result.stderr.decode(errors='replace')[:300])


def mcopy(image, source, target):
    result = tool('mcopy', image, '-o', source, '::/' + target)
    if result.returncode:
        raise RuntimeError('cannot write ' + target + ': ' + result.stderr.decode(errors='replace')[:300])


def delete_file(image, target):
    if extract(image, target) is None:
        return
    result = tool('mdel', image, '::/' + target)
    if result.returncode or extract(image, target) is not None:
        raise RuntimeError('cannot verify deletion of ' + target)


def owned(runtime, relative, *, directory=False, missing=False):
    """Check only mutable host paths, leaving ordinary guest symlinks intact."""
    root = Path(runtime).resolve(strict=True)
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('unsafe runtime-relative path')
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        last = index == len(relative.parts) - 1
        if current.is_symlink():
            raise ValueError('refusing symlink in mutable runtime path: ' + str(current))
        if not os.path.lexists(current):
            if last and missing:
                return current
            raise ValueError('missing runtime path: ' + str(current))
        info = current.lstat()
        if not last or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError('runtime path must be a directory: ' + str(current))
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('runtime path must be a private regular file: ' + str(current))
    return current


def fingerprint(path):
    if not os.path.lexists(path):
        return None
    info = path.lstat()
    if stat.S_ISREG(info.st_mode):
        kind = 'file'
    elif stat.S_ISDIR(info.st_mode):
        kind = 'dir'
    else:
        raise ValueError('unexpected transaction node: ' + str(path))
    return [info.st_dev, info.st_ino, kind]


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def journal(base, record):
    fd, name = tempfile.mkstemp(prefix='.config-journal-', dir=base)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, base / MARKER)
        sync_directory(base)
    finally:
        Path(name).unlink(missing_ok=True)


def recover_locked(runtime):
    base = owned(runtime, 'analysis', directory=True)
    marker = owned(runtime, 'analysis/' + MARKER)
    record = json.loads(marker.read_text())
    stage_name = record.get('stage', '')
    if (record.get('schema') != 'config-transaction-v1'
            or not re.fullmatch(r'\.config-state-[a-z0-9_]{8}', stage_name)
            or record.get('phase') not in ('prepared', 'committed', 'rolledback')):
        raise ValueError('unrecognised configuration recovery journal')
    stage = owned(runtime, 'analysis/' + stage_name, directory=True, missing=True)
    changes = record.get('changes', [])
    if (not changes or len(changes) > len(TARGETS)
            or len({item['target'] for item in changes}) != len(changes)
            or any(item['target'] not in TARGETS for item in changes)):
        raise ValueError('invalid configuration recovery targets')
    if record['phase'] == 'prepared':
        for item in reversed(changes):
            name = item['target']
            target = owned(runtime, 'analysis/' + name, directory=name == 'runs', missing=True)
            backup = owned(runtime, 'analysis/' + stage_name + '/old/' + name,
                           directory=name == 'runs', missing=True)
            old, new = item['old'], item['new']
            if fingerprint(backup) is not None:
                if fingerprint(backup) != old or fingerprint(target) not in (None, new):
                    raise ValueError('recovery identity changed: ' + name)
                if os.path.lexists(target):
                    if target.is_dir():
                        target.rmdir()  # The replacement runs directory is empty.
                    else:
                        target.unlink()
                os.replace(backup, target)
                sync_directory(target.parent)
            elif old is None:
                if fingerprint(target) is not None:
                    if fingerprint(target) != new:
                        raise ValueError('new recovery target changed: ' + name)
                    if target.is_dir():
                        target.rmdir()
                    else:
                        target.unlink()
                    sync_directory(target.parent)
            elif fingerprint(target) != old:
                raise ValueError('original recovery target missing or changed: ' + name)
        record['phase'] = 'rolledback'
        journal(base, record)
    else:
        field = 'new' if record['phase'] == 'committed' else 'old'
        for item in changes:
            target = owned(runtime, 'analysis/' + item['target'],
                           directory=item['target'] == 'runs', missing=True)
            if fingerprint(target) != item[field]:
                raise ValueError('completed recovery target changed: ' + item['target'])
    # Commit/rollback is complete before removing the guard. Keep it on cleanup failure.
    if stage.exists():
        shutil.rmtree(stage)
    marker.unlink()
    sync_directory(base)
    return record['phase']


class Transaction:
    def __init__(self, runtime):
        self.runtime = Path(runtime).resolve(strict=True)
        self.base = owned(runtime, 'analysis', directory=True)
        self.stage = None
        self.pending = False

    def __enter__(self):
        for name in TARGETS:
            owned(self.runtime, 'analysis/' + name, directory=name == 'runs', missing=True)
        root = owned(self.runtime, 'analysis/root', directory=True)
        self.stage = Path(tempfile.mkdtemp(prefix='.config-state-', dir=self.base))
        try:
            subprocess.run(['cp', '-a', '--reflink=auto', '--', str(root), str(self.stage / 'root')],
                           check=True, capture_output=True, timeout=120)
        except BaseException:
            shutil.rmtree(self.stage)
            raise
        return self

    def __exit__(self, *error):
        if not self.pending and self.stage.exists():
            shutil.rmtree(self.stage)

    @property
    def image(self):
        return self.stage / 'root/partitions/nflasha2.img'

    def repack(self):
        root = self.stage / 'root'
        manifest = json.loads((self.base / 'full-system.json').read_text())
        names = b'\0'.join(os.fsencode(str(p.relative_to(root))) for p in sorted(root.rglob('*'))) + b'\0'
        archive = self.stage / 'full-system.cpio'
        with archive.open('wb') as target:
            subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--quiet'], cwd=root,
                           input=names, stdout=target, check=True, timeout=120)
        with archive.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        manifest['initrd_sha256'] = digest
        (self.stage / 'full-system.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return digest

    def commit(self, replacements):
        if not replacements or set(replacements) - TARGETS:
            raise ValueError('unsupported configuration transaction target')
        changes = []
        for name, source in replacements.items():
            target = owned(self.runtime, 'analysis/' + name, directory=name == 'runs', missing=True)
            if source is not None:
                source = owned(self.runtime, source.relative_to(self.runtime), directory=name == 'runs')
                if not source.is_relative_to(self.stage):
                    raise ValueError('new configuration must be staged inside this transaction')
                if source.is_file():
                    with source.open('rb') as stream:
                        os.fsync(stream.fileno())
            changes.append({'target': name, 'old': fingerprint(target),
                            'new': fingerprint(source) if source is not None else None})
            (self.stage / 'old' / name).parent.mkdir(parents=True, exist_ok=True)
        record = {'schema': 'config-transaction-v1', 'phase': 'prepared',
                  'stage': self.stage.name, 'changes': changes}
        journal(self.base, record)
        self.pending = True
        try:
            for item in changes:
                name = item['target']
                target = self.base / name
                if item['old'] is not None:
                    os.replace(target, self.stage / 'old' / name)
                    sync_directory((self.stage / 'old' / name).parent)
                if replacements[name] is not None:
                    os.replace(replacements[name], target)
                sync_directory(target.parent)
        except BaseException:
            recover_locked(self.runtime)
            self.pending = False
            raise
        record['phase'] = 'committed'
        journal(self.base, record)
        # If cleanup fails, leave a committed journal; recovery only finishes cleanup.
        recover_locked(self.runtime)
        self.pending = False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--recover', action='store_true', required=True)
    args = parser.parse_args()
    with exclusive_runtime(args.runtime, allow_pending=True):
        phase = recover_locked(args.runtime)
    print('CONFIG_TRANSACTION_RECOVERED', phase)


if __name__ == '__main__':
    main()
