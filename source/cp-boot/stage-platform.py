#!/usr/bin/env python3
"""Port the CP runtime onto exact native-patched official QEMU 11.1.2 sources.

No firmware, build, tests or VM is run. The source receipt is valid before the
GPIO18/notify/peripheral child stages; rerunning over a changed child rejects.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).resolve().parent
PLATFORM = HERE / 'platform'
PRODUCT = HERE.parent.parent
PROFILE = 'virtual-cp-platform-v1'
RECEIPT = 'cp-platform-stage.json'
BACKUP = 'cp-platform-before'
PATCH_FILES = frozenset(('hw/core/null-machine.c', 'hw/dma/meson.build',
                         'hw/misc/meson.build', 'hw/watchdog/meson.build',
                         'hw/timer/sony_hwtimer.c'))
MODEL_FILES = frozenset(('hw/dma/sony_cp_edma.c', 'hw/misc/sony_cp_edma_gate.c',
                         'hw/watchdog/sony_cxd_wdt.c'))
GIB = 1024 ** 3
SOURCE_BUDGET = 4 * GIB
BUILD_BUDGET = 12 * GIB
RESERVE = 64 * GIB


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def target(root, name):
    parts = name.split('/')
    if not name or any(part in ('', '.', '..') for part in parts) or '\\' in name:
        raise ValueError('Unsafe platform source path: ' + name)
    path = root
    for part in parts:
        if path.is_symlink() or not path.is_dir():
            raise ValueError('Platform source parent must be a real directory: ' + str(path))
        path = path / part
    if path.is_symlink():
        raise ValueError('Platform source cannot be a symlink: ' + str(path))
    return path


def read(root, name):
    path = target(root, name)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Platform source must be regular: ' + str(path))
    return path.read_bytes()


def check(root, name, digest):
    path = target(root, name)
    if digest is None:
        if path.exists():
            raise ValueError('Unowned platform destination: ' + name)
        return None
    data = read(root, name)
    if sha(data) != digest:
        raise ValueError('Platform source SHA256 differs: ' + str(path))
    return data


def apply_exact(patch, originals):
    """Interpret only the pinned, existing-text-file unified diff, without fuzz."""
    lines = patch.decode('utf-8').splitlines(keepends=True)
    outputs = {}
    cursor = 0
    while cursor < len(lines):
        header = lines[cursor]
        if not header.startswith('--- a/') or cursor + 1 >= len(lines):
            raise ValueError('Unexpected platform patch header')
        name = header[len('--- a/'):].removesuffix('\n')
        if name in outputs or name not in originals or originals[name] is None:
            raise ValueError('Unexpected platform patch target: ' + name)
        if lines[cursor + 1] != '+++ b/' + name + '\n':
            raise ValueError('Platform patch rename/add/delete is not supported')
        cursor += 2
        old = originals[name].decode('utf-8').splitlines(keepends=True)
        new = []
        position = 0
        hunks = 0
        while cursor < len(lines) and lines[cursor].startswith('@@ '):
            match = re.fullmatch(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n', lines[cursor])
            if not match:
                raise ValueError('Unexpected platform patch hunk')
            old_count = int(match[2]) if match[2] is not None else 1
            new_count = int(match[4]) if match[4] is not None else 1
            start = int(match[1]) - (old_count != 0)
            new_start = int(match[3]) - (new_count != 0)
            if not position <= start <= len(old):
                raise ValueError('Overlapping/out-of-range platform patch hunk')
            new.extend(old[position:start])
            position = start
            if len(new) != new_start:
                raise ValueError('Platform patch output position differs')
            cursor += 1
            consumed = produced = 0
            while consumed < old_count or produced < new_count:
                if cursor >= len(lines) or lines[cursor][0] not in ' +-':
                    raise ValueError('Truncated platform patch hunk')
                line = lines[cursor]
                if line[0] in ' -':
                    if position >= len(old) or old[position] != line[1:]:
                        raise ValueError('Exact platform patch context differs: ' + name)
                    position += 1
                    consumed += 1
                if line[0] in ' +':
                    new.append(line[1:])
                    produced += 1
                if consumed > old_count or produced > new_count:
                    raise ValueError('Platform patch hunk lengths differ')
                cursor += 1
            hunks += 1
        if not hunks:
            raise ValueError('Platform patch lacks a hunk: ' + name)
        outputs[name] = ''.join(new + old[position:]).encode('utf-8')
    return outputs


def recipe():
    raw = read(PLATFORM, 'source-origins.json')
    origin = json.loads(raw)
    if origin.get('schema') != 'a7c2-cp-platform-origins-v1' or origin.get('profile') != PROFILE:
        raise ValueError('Unknown CP platform recipe')
    if (set(origin['sources']) != PATCH_FILES | MODEL_FILES or
            set(origin['source_models']) != MODEL_FILES or
            {name for name, row in origin['sources'].items() if row['operation'] == 'patch'} != PATCH_FILES):
        raise ValueError('CP platform source inventory differs')
    upstream = origin['upstream']
    native_raw = check(PRODUCT, upstream['native_manifest']['path'], upstream['native_manifest']['sha256'])
    native = json.loads(native_raw)
    check(PRODUCT, upstream['native_patch']['path'], upstream['native_patch']['sha256'])
    if (native['base_sha256'] != upstream['archive']['sha256'] or
            native['patch_sha256'] != upstream['native_patch']['sha256']):
        raise ValueError('Platform and native upstream identities differ')
    patch = check(PLATFORM, origin['patch']['path'], origin['patch']['sha256'])
    models = {}
    for name, record in origin['sources'].items():
        if record['operation'] == 'copy':
            if record['before'] is not None or record['after'] != origin['source_models'].get(name):
                raise ValueError('Unknown CP runtime copy identity')
            models[name] = check(PLATFORM, record['source'], record['after'])
        elif record['operation'] != 'patch' or record['before'] is None:
            raise ValueError('Unknown CP platform operation')
    if set(models) != set(origin['source_models']):
        raise ValueError('CP runtime source inventory differs')
    for name, digest in origin['downstream']['recipe_files'].items():
        check(HERE, name, digest)
    return origin, sha(raw), patch, models


def new_file(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if path.is_symlink() or path.read_bytes() != data:
        raise ValueError('Platform write readback differs: ' + str(path))


def stage(tree):
    given = Path(tree).absolute()
    if any(path.is_symlink() for path in (given, *given.parents)):
        raise ValueError('Platform tree path cannot contain symlinks')
    tree = given.resolve(strict=True)
    if not tree.is_dir():
        raise ValueError('Platform tree must be a directory')
    origin, origin_sha, patch, models = recipe()
    sources = origin['sources']
    before = {name: record['before'] for name, record in sources.items()}
    after = {name: record['after'] for name, record in sources.items()}
    guards = origin['unchanged_inputs']
    proof = dict(schema='a7c2-cp-platform-stage-v1', profile=PROFILE,
                 source_origins_sha256=origin_sha, upstream=origin['upstream'],
                 patch_sha256=origin['patch']['sha256'], base_sha256=before,
                 inherited_sources=guards, sources=origin['source_models'], outputs=after,
                 default_off=True, physical_compatible=False, full_boot_verified=False,
                 source_scope=origin['scope'])
    receipt = target(tree, RECEIPT)
    backup = tree / BACKUP
    for name, digest in guards.items():
        check(tree, name, digest)
    if receipt.exists():
        if read(tree, RECEIPT) != encoded(proof):
            raise ValueError('Unknown/drifted CP platform receipt')
        for name, digest in after.items():
            check(tree, name, digest)
        for name, digest in before.items():
            if digest is not None:
                check(backup, name, digest)
        return proof
    if backup.exists() or backup.is_symlink():
        raise ValueError('Unreceipted platform backup exists; preserve and inspect it')
    for name in ('cp-gpio18-stage.json', 'cp-notify-stage.json', 'cp-peripherals-stage.json'):
        path = target(tree, name)
        if path.exists():
            raise ValueError('Start from the native-patched tree before child stages: ' + name)
    originals = {name: check(tree, name, digest) for name, digest in before.items()}
    planned = apply_exact(patch, originals)
    if set(planned) != set(sources) - set(models):
        raise ValueError('Platform patch inventory differs')
    planned.update(models)
    for name, data in planned.items():
        if sha(data) != after[name]:
            raise ValueError('Planned platform output SHA256 differs: ' + name)
        temporary = target(tree, name).with_name(Path(name).name + '.cp-platform-new')
        if temporary.exists() or temporary.is_symlink():
            raise ValueError('Unowned platform temporary exists: ' + str(temporary))
    # All source inputs and every computed output are admitted before any write.
    backup.mkdir()
    for name, data in originals.items():
        if data is not None:
            path = backup / name
            path.parent.mkdir(parents=True, exist_ok=True)
            new_file(path, data)
    for name, digest in {**before, **guards}.items():
        check(tree, name, digest)
    for name, data in planned.items():
        path = target(tree, name)
        if before[name] is None:
            new_file(path, data)
        else:
            temporary = path.with_name(path.name + '.cp-platform-new')
            new_file(temporary, data)
            check(tree, name, before[name])
            os.replace(temporary, path)
    for name, digest in {**guards, **after}.items():
        check(tree, name, digest)
    for name, digest in before.items():
        if digest is not None:
            check(backup, name, digest)
    new_file(receipt, encoded(proof))
    return proof


def file_sha(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('Build input path cannot contain symlinks: ' + str(path))
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Build input must be regular: ' + str(path))
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after) or identity(after) != identity(path.stat()):
        raise ValueError('Build input changed while hashing: ' + str(path))
    return digest


def space_budget(parent):
    try:
        space = os.statvfs(parent)
        if (type(space.f_bavail) is not int or space.f_bavail < 0 or
                type(space.f_frsize) is not int or space.f_frsize <= 0):
            raise ValueError('Filesystem free space is unknown')
        available = space.f_bavail * space.f_frsize
    except (OSError, ValueError, AttributeError, TypeError) as error:
        raise ValueError('Filesystem free space is unknown') from error
    required = SOURCE_BUDGET + BUILD_BUDGET + RESERVE
    if available < required:
        raise ValueError('Insufficient build space: need 80 GiB including the 64 GiB reserve')
    return dict(source_budget_bytes=SOURCE_BUDGET, build_budget_bytes=BUILD_BUDGET,
                reserve_bytes=RESERVE, required_bytes=required,
                available_bytes=available, fits=True)


def preflight_build(archive, output):
    """Read-only admission, shared by the offline builder and its boundary tests."""
    origin, origin_sha, _, _ = recipe()
    archive = Path(archive).absolute()
    output = Path(output).absolute()
    for path in (archive, output, PRODUCT):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError('Build paths cannot contain symlinks: ' + str(path))
        if path == Path('/tmp') or Path('/tmp') in path.parents:
            raise ValueError('Build materials must be outside /tmp')
    archive = archive.resolve(strict=True)
    output = output.resolve()
    allowed = (PRODUCT / 'source/build').resolve()
    if allowed not in output.parents:
        raise ValueError('NEW_OUTPUT must be a new child of this product source/build directory')
    if output.exists():
        raise ValueError('NEW_OUTPUT already exists; output reuse is refused')
    parent = output.parent
    while not parent.exists():
        parent = parent.parent
    if not parent.is_dir() or parent.stat().st_uid != os.geteuid() or PRODUCT.stat().st_uid != os.geteuid():
        raise ValueError('Build output parent and product must be owned by the current user')
    if file_sha(archive) != origin['upstream']['archive']['sha256']:
        raise ValueError('QEMU archive SHA256 differs')
    return dict(archive=str(archive), output=str(output), source_origins_sha256=origin_sha,
                storage=space_budget(parent), workers=2, default_binary_replaced=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu_source', type=Path,
                        help='Official 11.1.2 tree with only the pinned product native patch applied')
    print(json.dumps(stage(parser.parse_args().qemu_source), indent=2))
