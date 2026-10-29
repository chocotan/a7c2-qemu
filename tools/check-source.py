#!/usr/bin/env python3
"""Check all three offline QEMU patches and DMA/ATU/PCI source staging; never build or run QEMU."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PATCH_STAGES = (('manifest.json', 'qemu-sony-native.patch'),
                ('qemu-directory-sd.json', 'qemu-directory-sd.patch'),
                ('qemu-sony-usb.json', 'qemu-sony-usb.patch'))


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'Expected regular source file: {path}')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check():
    source = ROOT / 'source'
    stages = [(json.loads((source / name).read_text()), patch) for name, patch in PATCH_STAGES]
    base, directory, usb = (manifest for manifest, _ in stages)
    archive = source / 'vendor' / base['base']
    if not archive.is_file():
        raise ValueError('Missing pinned QEMU archive; supply source/vendor/' + base['base'] +
                         ' as described in source/vendor/README.md (no automatic download)')
    assert digest(archive) == base['base_sha256'], 'QEMU archive hash differs'
    for manifest, patch in stages:
        assert digest(source / patch) == manifest['patch_sha256'], patch
        assert all(set(record) == {'before', 'after'} for record in manifest['source_files'].values()), patch
    assert directory['patch'] == PATCH_STAGES[1][1]
    assert directory['base_archive'] == 'vendor/' + base['base']
    assert digest(source / directory['work_file']) == directory['source_files']['block/vvfat.c']['after']
    assert usb['base_patch_sha256'] == base['patch_sha256']
    dtc = source / 'dtc'
    actual = {p.relative_to(dtc).as_posix() for p in dtc.rglob('*') if p.is_file()}
    assert actual == set(base['dtc_source_files']), 'DTC inventory differs'
    for name, sha in base['dtc_source_files'].items():
        assert digest(dtc / name) == sha, name

    helper = ROOT / 'report/virtual-pcidma/stage_hardware.py'
    spec = importlib.util.spec_from_file_location('publication_stage_hardware', helper)
    hardware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hardware)
    origin = json.loads((hardware.DMA / 'SOURCE-ORIGINS.json').read_text())
    assert origin['source_archive_sha256'] == base['base_sha256']
    assert origin['native_patch_sha256'] == base['patch_sha256']
    assert origin['usb_patch_sha256'] == usb['patch_sha256']
    pins = {'dma_delta_sha256': digest(hardware.DMA / 'qemu-dma330.patch'),
            'atu_source_sha256': {n: digest(hardware.ATU / 'hardware' / n) for n in hardware.ATU_FILES},
            'model_source_sha256': {n: digest(hardware.HERE / 'hardware' / n) for n in hardware.MODEL_FILES},
            'board_source_sha256': {n: digest(hardware.HERE / 'hardware' / n) for n in hardware.FRAGMENTS},
            'atu_board_sha256': digest(hardware.ATU / 'hardware/virt-atu.inc')}
    assert pins['dma_delta_sha256'] == origin['delta_patch_sha256']

    # Materialize only touched text files; leave the upstream archive and installed builds untouched.
    temporary = Path(os.environ['TMPDIR']) if os.environ.get('TMPDIR') not in (None, '', '/tmp') else ROOT / 'validation/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='patch-check-', dir=temporary) as work:
        tree = Path(work)
        names = set(origin['source_files']) | {'hw/misc/meson.build'}
        for manifest, _ in stages:
            names.update(manifest['source_files'])
        with tarfile.open(archive) as tar:
            for name in sorted(names):
                assert not Path(name).is_absolute() and '..' not in Path(name).parts, name
                try:
                    member = tar.getmember('qemu-11.1.2/' + name)
                except KeyError:
                    assert name in base['source_files'] and base['source_files'][name]['before'] is None, name
                    continue
                assert member.isreg() and member.size < 4 * 1024 * 1024, name
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as stream:
                    target.write_bytes(stream.read())
        for manifest, patch in stages:
            for name, record in manifest['source_files'].items():
                actual = digest(tree / name) if (tree / name).exists() else None
                assert actual == record['before'], f'{patch} before identity: {name}'
            subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-d', str(tree),
                            '-i', str(source / patch)], check=True)
            for name, record in manifest['source_files'].items():
                assert digest(tree / name) == record['after'], f'{patch} after identity: {name}'
            print('PATCH_BEFORE_AFTER_IDENTITIES_PASS', patch, len(manifest['source_files']))
        receipt = hardware.stage(tree, apply_dma=True)
        for key, expected in pins.items():
            assert receipt[key] == expected, f'Hardware source pins: {key}'
        for key, parent in (('atu_source_sha256', tree / 'hw/misc'),
                            ('model_source_sha256', tree / 'hw/misc/sony-pcidma')):
            for name, sha in pins[key].items():
                assert digest(parent / name) == sha, f'Staged hardware: {name}'
        assert receipt['virt_after'] == digest(tree / 'hw/arm/virt.c')
        assert receipt['meson_after'] == digest(tree / 'hw/misc/meson.build')
        assert digest(tree / 'hw/dma/pl330.c') == origin['source_files']['hw/dma/pl330.c']['after']
        assert receipt['pcidma_verified'] is False and receipt['capture_verified'] is False
        print('DMA_ATU_PCI_HARDWARE_SOURCE_PINS_PASS', len(hardware.ATU_FILES), len(hardware.MODEL_FILES))
    print('OFFLINE_SOURCE_AND_THREE_PATCH_IDENTITIES_PASS')


if __name__ == '__main__':
    check()
