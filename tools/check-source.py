#!/usr/bin/env python3
"""Check offline QEMU patches and staged hardware sources; never build or run QEMU."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
ROOT = Path(__file__).resolve().parents[1]
PATCH_STAGES = (('manifest.json', 'qemu-sony-native.patch'), ('qemu-directory-sd.json', 'qemu-directory-sd.patch'), ('qemu-sony-usb.json', 'qemu-sony-usb.patch'))

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
        raise ValueError('Missing pinned QEMU archive; supply source/vendor/' + base['base'] + ' as described in source/vendor/README.md (no automatic download)')
    if not digest(archive) == base['base_sha256']:
        raise ValueError('QEMU archive hash differs')
    for manifest, patch in stages:
        if not digest(source / patch) == manifest['patch_sha256']:
            raise ValueError(patch)
        if not all((set(record) == {'before', 'after'} for record in manifest['source_files'].values())):
            raise ValueError(patch)
    if not directory['patch'] == PATCH_STAGES[1][1]:
        raise ValueError('Source integrity check failed')
    if not directory['base_archive'] == 'vendor/' + base['base']:
        raise ValueError('Source integrity check failed')
    if not digest(source / directory['work_file']) == directory['source_files']['block/vvfat.c']['after']:
        raise ValueError('Source integrity check failed')
    if not usb['base_patch_sha256'] == base['patch_sha256']:
        raise ValueError('Source integrity check failed')
    dtc = source / 'dtc'
    actual = {p.relative_to(dtc).as_posix() for p in dtc.rglob('*') if p.is_file()}
    if not actual == set(base['dtc_source_files']):
        raise ValueError('DTC inventory differs')
    for name, sha in base['dtc_source_files'].items():
        if not digest(dtc / name) == sha:
            raise ValueError(name)
    helper = ROOT / 'report/virtual-pcidma/stage_hardware.py'
    spec = importlib.util.spec_from_file_location('publication_stage_hardware', helper)
    hardware = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hardware)
    origin = json.loads((hardware.DMA / 'SOURCE-ORIGINS.json').read_text())
    if not origin['source_archive_sha256'] == base['base_sha256']:
        raise ValueError('Source integrity check failed')
    if not origin['native_patch_sha256'] == base['patch_sha256']:
        raise ValueError('Source integrity check failed')
    if not origin['usb_patch_sha256'] == usb['patch_sha256']:
        raise ValueError('Source integrity check failed')
    pins = {'dma_delta_sha256': digest(hardware.DMA / 'qemu-dma330.patch'), 'atu_source_sha256': {n: digest(hardware.ATU / 'hardware' / n) for n in hardware.ATU_FILES}, 'model_source_sha256': {n: digest(hardware.HERE / 'hardware' / n) for n in hardware.MODEL_FILES}, 'board_source_sha256': {n: digest(hardware.HERE / 'hardware' / n) for n in hardware.FRAGMENTS}, 'atu_board_sha256': digest(hardware.ATU / 'hardware/virt-atu.inc')}
    if not pins['dma_delta_sha256'] == origin['delta_patch_sha256']:
        raise ValueError('Source integrity check failed')
    temporary = Path(os.environ['TMPDIR']) if os.environ.get('TMPDIR') not in (None, '', '/tmp') else ROOT / 'validation/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='patch-check-', dir=temporary) as work:
        tree = Path(work)
        names = set(origin['source_files']) | {'hw/misc/meson.build'}
        for manifest, _ in stages:
            names.update(manifest['source_files'])
        with tarfile.open(archive) as tar:
            for name in sorted(names):
                if not (not Path(name).is_absolute() and '..' not in Path(name).parts):
                    raise ValueError(name)
                try:
                    member = tar.getmember('qemu-11.1.2/' + name)
                except KeyError:
                    if not (name in base['source_files'] and base['source_files'][name]['before'] is None):
                        raise ValueError(name)
                    continue
                if not (member.isreg() and member.size < 4 * 1024 * 1024):
                    raise ValueError(name)
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as stream:
                    target.write_bytes(stream.read())
        for manifest, patch in stages:
            for name, record in manifest['source_files'].items():
                actual = digest(tree / name) if (tree / name).exists() else None
                if not actual == record['before']:
                    raise ValueError(f'{patch} before identity: {name}')
            subprocess.run(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-d', str(tree), '-i', str(source / patch)], check=True)
            for name, record in manifest['source_files'].items():
                if not digest(tree / name) == record['after']:
                    raise ValueError(f'{patch} after identity: {name}')
            print('PATCH_BEFORE_AFTER_IDENTITIES_PASS', patch, len(manifest['source_files']))
        receipt = hardware.stage(tree, apply_dma=True)
        for key, expected in pins.items():
            if not receipt[key] == expected:
                raise ValueError(f'Hardware source pins: {key}')
        for key, parent in (('atu_source_sha256', tree / 'hw/misc'), ('model_source_sha256', tree / 'hw/misc/sony-pcidma')):
            for name, sha in pins[key].items():
                if not digest(parent / name) == sha:
                    raise ValueError(f'Staged hardware: {name}')
        if not receipt['virt_after'] == digest(tree / 'hw/arm/virt.c'):
            raise ValueError('Source integrity check failed')
        if not receipt['meson_after'] == digest(tree / 'hw/misc/meson.build'):
            raise ValueError('Source integrity check failed')
        if not digest(tree / 'hw/dma/pl330.c') == origin['source_files']['hw/dma/pl330.c']['after']:
            raise ValueError('Source integrity check failed')
        if not (receipt['pcidma_verified'] is False and receipt['capture_verified'] is False):
            raise ValueError('Source integrity check failed')
        print('DMA_ATU_PCI_HARDWARE_SOURCE_PINS_PASS', len(hardware.ATU_FILES), len(hardware.MODEL_FILES))
        helper=source/'persistent-flash/stage.py'
        spec=importlib.util.spec_from_file_location('publication_persistent_flash',helper)
        flash=importlib.util.module_from_spec(spec);spec.loader.exec_module(flash)
        flash_receipt=flash.stage(tree)
        if flash_receipt['board_before']!=receipt['virt_after'] or flash_receipt['board_after']!=digest(tree/'hw/arm/virt.c'):
            raise ValueError('Persistent flash board source chain differs')
        for name,sha in flash_receipt['source_files'].items():
            if digest(tree/'hw/block/a7c2-persistent'/name)!=sha:
                raise ValueError('Persistent flash staged source differs: '+name)
        if flash_receipt['default_enabled'] is not False or flash_receipt['parent_regular_file_fd_required'] is not True:
            raise ValueError('Persistent flash activation boundary differs')
        print('PERSISTENT_FLASH_HARDWARE_SOURCE_PINS_PASS',len(flash.FILES))
    print('OFFLINE_SOURCE_AND_THREE_PATCH_IDENTITIES_PASS')
if __name__ == '__main__':
    check()
