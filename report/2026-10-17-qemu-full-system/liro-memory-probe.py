#!/usr/bin/env python3
"""Read-only owned-QEMU inspection, never an image preload or LIRO start."""
import hashlib
from pathlib import Path
import re
import shutil

KERNEL_SHA256 = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
IMAGE_SHA256 = '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
IMAGE_BYTES = 0xd286e0
ADDRESS = 0x401000000
CAPACITY = 0x1000000
MEMSTART_PHYSICAL = 0x4005e99c8
PAGE_OFFSET = 0xffffffc000000000


def probe(qmp, kernel_sha256, output, address):
    if kernel_sha256 != KERNEL_SHA256 or address != ADDRESS:
        raise ValueError('LIRO memory probe requires the exact kernel and observed reserved address')
    output = Path(output)
    target = output / 'liro-reserved-memory.bin'
    if target.exists() or shutil.disk_usage(output).free < CAPACITY + 1024 * 1024:
        raise ValueError('Refuse existing memory evidence or insufficient host space')
    running = bool(qmp('query-status').get('running', False))

    def word(address, width):
        text = qmp('human-monitor-command', {'command-line': f'xp /1{"g" if width == 8 else "w"}x {address:#x}'})
        values = re.findall(r'0x([0-9a-fA-F]+)', text)
        if len(values) != 1:
            raise ValueError('Incomplete read-only RAM evidence')
        return int(values[0], 16)

    try:
        if running:
            qmp('stop')
        # Same original 2.01 instruction anchor used by the USB core proof.
        if word(0x400365cd4, 4) != 0xf94036f4:
            raise ValueError('Original kernel RAM instruction identity differs')
        memstart = word(MEMSTART_PHYSICAL, 8)
        if memstart != 0x400000000:
            raise ValueError('Observed memory base differs from declared 8 GiB profile')
        qmp('pmemsave', {'val': address, 'size': CAPACITY, 'filename': '/out/liro-reserved-memory.bin'})
        data = target.read_bytes()
        if len(data) != CAPACITY:
            raise ValueError('Reserved RAM export is incomplete')
        prefix_sha = hashlib.sha256(data[:IMAGE_BYTES]).hexdigest()
        return {'liro_reserved_memory_observed': True, 'kernel_sha256': kernel_sha256,
                'memstart_symbol_physical': hex(MEMSTART_PHYSICAL), 'memstart_value': hex(memstart),
                'physical': hex(address), 'capacity': CAPACITY, 'export_sha256': hashlib.sha256(data).hexdigest(),
                'window_all_zero': not any(data), 'image_prefix_sha256': prefix_sha,
                'image_matches_original': prefix_sha == IMAGE_SHA256, 'image_bytes': IMAGE_BYTES,
                'header_magic_hex': data[8:12].hex(), 'direct_map_address': hex((address - memstart) | PAGE_OFFSET),
                'linked_address_compatible': ((address - memstart) | PAGE_OFFSET) == 0xffffffc001000000,
                'image_loaded_by_probe': False, 'LIRO_initialized_verified': False,
                'MC_owner_verified': False, 'camera_startup_verified': False}
    finally:
        if running:
            qmp('cont')
