#!/usr/bin/env python3
"""Verify the pinned offline source and both patch stages without compiling or running QEMU."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Expected regular source file: {path}')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check():
    source = ROOT / 'source'
    base = json.loads((source / 'manifest.json').read_text())
    usb = json.loads((source / 'qemu-sony-usb.json').read_text())
    archive = source/'vendor'/base['base']
    assert digest(archive) == base['base_sha256'], 'QEMU archive hash differs'
    assert digest(source / 'qemu-sony-native.patch') == base['patch_sha256']
    assert digest(source / 'qemu-sony-usb.patch') == usb['patch_sha256']
    assert usb['base_patch_sha256'] == base['patch_sha256']
    dtc = source / 'dtc'
    actual = {p.relative_to(dtc).as_posix() for p in dtc.rglob('*') if p.is_file()}
    assert actual == set(base['dtc_source_files']), 'DTC inventory differs'
    for name, sha in base['dtc_source_files'].items():
        assert digest(dtc / name) == sha, name
    # Materialize only the touched text files; do not unpack/build the 1 GiB source tree.
    temporary = Path(os.environ['TMPDIR']) if os.environ.get('TMPDIR') not in (None, '', '/tmp') else ROOT / 'validation/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='patch-check-', dir=temporary) as work:
        tree = Path(work)
        names = set(base['source_files']) | set(usb['source_files'])
        with tarfile.open(archive) as tar:
            for name in sorted(names):
                try:
                    member = tar.getmember('qemu-11.1.2/' + name)
                except KeyError:
                    assert base['source_files'][name]['before'] is None, name
                    continue
                assert member.isreg() and member.size < 4 * 1024 * 1024, name
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as stream:
                    target.write_bytes(stream.read())
        for manifest, patch in ((base, 'qemu-sony-native.patch'), (usb, 'qemu-sony-usb.patch')):
            for name, record in manifest['source_files'].items():
                actual = digest(tree / name) if (tree / name).exists() else None
                assert actual == record['before'], f'Before identity: {name}'
            subprocess.run(['patch', '--batch', '-p1', '-d', str(tree), '-i', str(source / patch)], check=True)
            for name, record in manifest['source_files'].items():
                assert digest(tree / name) == record['after'], f'After identity: {name}'
    print('OFFLINE_SOURCE_AND_BOTH_PATCH_IDENTITIES_PASS')


if __name__ == '__main__':
    check()
