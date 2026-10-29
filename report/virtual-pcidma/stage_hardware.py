#!/usr/bin/env python3
"""Stage the same default-off PCI/ATU hardware into native and diagnostic builds."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
DMA = HERE.parent / 'virtual-dma330'
ATU = HERE.parent / 'virtual-atu'
ATU_FILES = ('sony_atu.c', 'atu_core.c', 'atu_core.h')
MODEL_FILES = (
    'sony_pcidma.c', 'backup_peer.h', 'lli.c', 'lli.h', 'registers.c', 'registers.h',
    'test_pcie_peer.c', 'test_root_dbi.c', 'test_pcie_scu.c', 'scu.c', 'scu.h',
    'ccf.c', 'ccf.h', 'test_ccf_scu.c', 'phy_sram.c', 'phy_sram.h',
    'qemu_phy_sram.c', 'phy_clear_job.c', 'phy_clear_job.h', 'qemu_phy_init.c',
    'phy_calib.c', 'phy_calib.h', 'dfs.c', 'dfs.h', 'qemu_dfs.c',
)
FRAGMENTS = ('virt-pcidma.inc', 'virt-pcie-scu.inc', 'virt-pcie-peer.inc')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stage(src, apply_dma=False):
    origin = json.loads((DMA / 'SOURCE-ORIGINS.json').read_text())
    patch = DMA / 'qemu-dma330.patch'
    if sha(patch) != origin['delta_patch_sha256']:
        raise ValueError('DMA patch identity differs')
    phase = 'before' if apply_dma else 'after'
    for name, record in origin['source_files'].items():
        if sha(src / name) != record[phase]:
            raise ValueError('PCI hardware staging input differs: ' + name)
    target = src / 'hw/misc/sony-pcidma'
    if target.exists():
        raise ValueError('PCI hardware was already staged')
    if apply_dma:
        subprocess.run(['patch', '--batch', '-p1', '-d', str(src), '-i', str(patch)],
                       check=True, stdout=sys.stderr)
        for name, record in origin['source_files'].items():
            if sha(src / name) != record['after']:
                raise ValueError('DMA patched source differs: ' + name)
    virt = src / 'hw/arm/virt.c'
    text = virt.read_text()
    anchor = '    create_gic(vms, sysmem);\n'
    peer_anchor = '    create_pcie(vms);\n'
    include = '#include "qemu/osdep.h"\n'
    point = '        memory_region_add_subregion_overlap(sysmem, 0x600000000ULL, observe, 1);\n'
    fragment = (ATU / 'hardware/virt-atu.inc').read_text()
    if any(text.count(a) != 1 for a in (anchor, peer_anchor, include)) or fragment.count(point) != 1:
        raise ValueError('PCI hardware board insertion point differs')
    fragment = fragment.replace(point, point + (HERE / 'hardware/virt-pcidma.inc').read_text())
    text = text.replace(anchor, anchor + fragment + (HERE / 'hardware/virt-pcie-scu.inc').read_text())
    text = text.replace(peer_anchor, peer_anchor + (HERE / 'hardware/virt-pcie-peer.inc').read_text())
    text = text.replace(include, include + '#include "hw/pci/pci_bridge.h"\n#include "hw/pci/pci_bus.h"\n#include "hw/misc/sony-pcidma/backup_peer.h"\n')
    target.mkdir()
    for name in ATU_FILES:
        shutil.copyfile(ATU / 'hardware' / name, src / 'hw/misc' / name)
    for name in MODEL_FILES:
        shutil.copyfile(HERE / 'hardware' / name, target / name)
    objects = ['sony_atu.c', 'atu_core.c'] + ['sony-pcidma/' + n for n in MODEL_FILES if n.endswith('.c')]
    with (src / 'hw/misc/meson.build').open('a') as stream:
        stream.write('\nsystem_ss.add(files(' + ', '.join(repr(n) for n in objects) + '))\n')
    virt.write_text(text)
    return {
        'dma_delta_sha256': origin['delta_patch_sha256'],
        'atu_source_sha256': {n: sha(ATU / 'hardware' / n) for n in ATU_FILES},
        'model_source_sha256': {n: sha(HERE / 'hardware' / n) for n in MODEL_FILES},
        'board_source_sha256': {n: sha(HERE / 'hardware' / n) for n in FRAGMENTS},
        'atu_board_sha256': sha(ATU / 'hardware/virt-atu.inc'),
        'virt_after': sha(virt),
        'meson_after': sha(src / 'hw/misc/meson.build'),
        'pcidma_verified': False, 'capture_verified': False,
    }


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: stage_hardware.py PATCHED_NATIVE_SOURCE_DIRECTORY')
    print(json.dumps(stage(Path(sys.argv[1]).resolve(), apply_dma=True), indent=2))
