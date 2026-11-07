#!/usr/bin/env python3
"""Capture an immutable native-route dependency revision; never auto-refresh it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ANALYSIS = 'runtime/analysis/'
EXTRA = {
    **{ANALYSIS + 'vendor/fwtool/fwtool/' + name: 'third-party-source' for name in
       ('util/__init__.py', 'archive/__init__.py', 'archive/fat.py', 'io/__init__.py')},
    **{ANALYSIS + 'menu-root/simulation/' + name: 'private-runtime-input' for name in
       ('seed-power-on', 'seed-date-clock', 'menu-regs', 'menu-readmem', 'headless-osd-export', 'ramfb-viewer')},
    **{ANALYSIS + name: 'private-runtime-input' for name in
       ('menu-observe.so', 'libIMDB-menu.so', 'qemu-virt-board/virt-packed.dtb',
        'menu-root/usr/lib/libosal_uipc.so', 'menu-root/usr/lib/libosal_utm.so')},
    'source/vendor/qemu-11.1.2.tar.xz': 'source-archive',
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def relative(name):
    if not isinstance(name, str) or not name or '\\' in name or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('Invalid dependency path')
    return Path(name)


def ordinary(root, name):
    path = root
    for part in relative(name).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('Linked dependency refused: ' + name)
    if not path.is_file():
        raise ValueError('Missing ordinary dependency: ' + name)
    return path


def identity(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected a dependency snapshot directory')
    manifest_path = ordinary(root, 'snapshot.json')
    manifest = json.loads(manifest_path.read_text())
    payload = {'schema': 1, 'files': manifest['files']}
    ident = hashlib.sha256(canonical(payload)).hexdigest()
    if manifest.get('schema') != 1 or manifest.get('id') != ident or root.name != ident:
        raise ValueError('Dependency snapshot identity differs')
    names = set()
    for item in manifest['files']:
        name = item['path']
        if name in names:
            raise ValueError('Duplicate dependency')
        names.add(name)
        path = ordinary(root, name)
        if path.stat().st_size != item['bytes'] or identity(path) != item['sha256']:
            raise ValueError('Dependency snapshot changed: ' + name)
        if stat.S_IMODE(path.stat().st_mode) != item['mode']:
            raise ValueError('Dependency snapshot mode changed: ' + name)
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Linked snapshot content refused')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != names | {'snapshot.json'}:
        raise ValueError('Unexpected dependency snapshot content')
    return manifest


def capture(source, storage, paths, observer=None, observer_sha=None):
    if (observer is None) != (observer_sha is None):
        raise ValueError('Observer override requires its digest')
    before = {name: identity(ordinary(source, name)) for name in paths}
    if observer is not None:
        if observer.is_symlink() or not observer.is_file() or identity(observer) != observer_sha:
            raise ValueError('Observer override identity differs')
    storage.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='capture-', dir=storage))
    try:
        records = []
        for name in sorted(paths):
            original = ordinary(source, name)
            selected = observer if observer is not None and name == ANALYSIS + 'menu-observe.c' else original
            target = stage / relative(name);target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(selected, target)  # Copy bytes, never a hard link.
            mode = stat.S_IMODE(original.stat().st_mode) & ~0o222
            target.chmod(mode)
            digest = identity(target)
            if digest != (observer_sha if selected == observer else before[name]):
                raise ValueError('Dependency changed while copying: ' + name)
            records.append({'path': name, 'role': paths[name], 'bytes': target.stat().st_size,
                            'sha256': digest, 'upstream_sha256': before[name], 'mode': mode,
                            'origin': 'explicit-observer-revision' if selected == observer else 'native-route-copy'})
        after = {name: identity(ordinary(source, name)) for name in paths}
        if before != after:
            raise ValueError('Native source changed during capture; snapshot not selected')
        payload = {'schema': 1, 'files': records}
        ident = hashlib.sha256(canonical(payload)).hexdigest()
        manifest = dict(payload, id=ident)
        (stage / 'snapshot.json').write_bytes(canonical(manifest) + b'\n')
        (stage / 'snapshot.json').chmod(0o444)
        target = storage / ident
        if target.exists() or target.is_symlink():
            verify(target)
        else:
            stage.rename(target)
        verify(target)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def select(here, root):
    manifest = verify(root)
    expected = here / 'runtime/native-source-snapshots' / manifest['id']
    if root.resolve() != expected.resolve():
        raise ValueError('Snapshot must be owned by this full-system runtime')
    pin = here / 'runtime/native-input.json'
    with tempfile.NamedTemporaryFile(dir=pin.parent, prefix='native-pin-', delete=False) as stream:
        stream.write(canonical({'schema': 1, 'id': manifest['id']}) + b'\n')
        temporary = Path(stream.name)
    temporary.replace(pin)


def resolve(here=HERE):
    pin = ordinary(here / 'runtime', 'native-input.json')
    value = json.loads(pin.read_text())
    ident = value.get('id')
    if value.get('schema') != 1 or not isinstance(ident, str) or len(ident) != 64 or any(c not in '0123456789abcdef' for c in ident):
        raise ValueError('Invalid pinned native dependency revision')
    root = here / 'runtime/native-source-snapshots' / ident
    verify(root)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-from', type=Path, help='explicit source route directory; no implicit live-source fallback')
    parser.add_argument('--observer-source', type=Path)
    parser.add_argument('--observer-source-sha256')
    parser.add_argument('--select', action='store_true', help='select the captured revision for future builds/runs')
    args = parser.parse_args()
    if args.capture_from is None:
        if args.select or args.observer_source is not None or args.observer_source_sha256 is not None:
            parser.error('Capture options require --capture-from')
        root = resolve();print('NATIVE_INPUT_VERIFIED', root.name);return
    source = args.capture_from.resolve(strict=True)
    repo = HERE.parents[1]
    prefix = source.relative_to(repo)
    raw = subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--', prefix.as_posix()])
    public = [Path(os.fsdecode(p)).relative_to(prefix).as_posix() for p in raw.split(b'\0') if p]
    if not public:
        raise ValueError('No tracked native dependency sources')
    paths = {name: 'public-source' for name in public};paths.update(EXTRA)
    root = capture(source, HERE / 'runtime/native-source-snapshots', paths, args.observer_source, args.observer_source_sha256)
    if subprocess.check_output(['git', '-C', str(repo), 'ls-files', '-z', '--', prefix.as_posix()]) != raw:
        raise ValueError('Native source inventory changed during capture; not selected')
    if args.select:
        select(HERE, root)
    print('NATIVE_INPUT_CAPTURED', root.name, 'files=' + str(len(paths)), 'selected=' + str(args.select).lower())


if __name__ == '__main__':
    main()
