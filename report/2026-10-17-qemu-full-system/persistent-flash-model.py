#!/usr/bin/env python3
"""Install the persistent flash model into an independent QEMU source copy only."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-functional-persistent-flash-v1'
INCLUDE = '#include "../block/a7c2-persistent/flash-qemu.c"\n'
BOARD_FRAGMENT = '''/* Explicit parent-owned instance paths; no environment lookup. */
DeviceState *flash = qdev_new("sony-persistent-flash");
qdev_prop_set_int32(flash, "backend-fd", instance_disk_fd);
qdev_prop_set_string(flash, "geometry", instance_geometry_wire_path);
qdev_prop_set_uint64(flash, "expected-dev", instance_disk_stat.st_dev);
qdev_prop_set_uint64(flash, "expected-ino", instance_disk_stat.st_ino);
sysbus_realize_and_unref(SYS_BUS_DEVICE(flash), &error_fatal);
sysbus_mmio_map(SYS_BUS_DEVICE(flash), 0, 0x0b000000);
/* User whole, partition numbers 1..30, B0 selector 31 and B1 selector 32
 * share this one opened FD. No additional boot-area devices or FDs. */
'''


def digest(b):
    return hashlib.sha256(b).hexdigest()


def patch(source, scratch_root):
    source, scratch_root = Path(source).absolute(), Path(scratch_root).resolve()
    if source.is_symlink() or source.resolve() != source or not source.is_relative_to(scratch_root) or source == scratch_root:
        raise ValueError('Source must be a real child of the isolated scratch root')
    if scratch_root == Path('/') or scratch_root.is_relative_to(HERE):
        raise ValueError('Scratch must be a separate local experiment directory')
    board = source/'hw/arm/virt.c'
    if not board.is_file() or board.is_symlink() or not (source/'configure').is_file():
        raise ValueError('Not a complete independent QEMU source')
    before = board.read_bytes()
    if b'0x0c000000' not in before or b'0x0a000000' not in before:
        raise ValueError('Unrecognized virt board MMIO layout')
    receipt = source.parent/'persistent-flash-model-delta.json'
    prior = json.loads(receipt.read_text()) if receipt.exists() else {}
    generated = {f'hw/block/a7c2-persistent/{name}':(HERE/'persistent-flash'/name).read_bytes()
                 for name in ('flash-core.h','flash-core.c','flash-qemu.c')}
    generated['hw/arm/virt.c'] = before if INCLUDE.encode() in before else before + b'\n' + INCLUDE.encode()
    records = {}
    for name, data in generated.items():
        target = source/name
        if target.is_symlink() or not target.parent.resolve().is_relative_to(source):
            raise ValueError('Source delta escapes private source')
        old = target.read_bytes() if target.exists() else None
        saved = prior.get('files',{}).get(name,{})
        owned = old is not None and digest(old) == saved.get('after')
        if name != 'hw/arm/virt.c' and old is not None and old != data and not owned:
            raise ValueError('Refusing to overwrite an unrelated flash model')
        records[name] = dict(before=saved.get('before') if owned else (digest(old) if old else None), after=digest(data))
    for name,data in generated.items():
        (source/name).parent.mkdir(parents=True,exist_ok=True)
        (source/name).write_bytes(data)
    result = dict(schema='a7c2.persistent-flash.source-delta.v1',profile=PROFILE,
                  files=records,device_type='sony-persistent-flash',mmio_base='0x0b000000',mmio_size=4096,
                  selectors=dict(whole=0,partitions='1..30',boot0=31,boot1=32),board_wired=False,
                  physical_compatibility=False,original_kernel_rebuilt=False)
    receipt.write_text(json.dumps(result,indent=2)+'\n')
    (source.parent/'persistent-flash-board-fragment.c.txt').write_text(BOARD_FRAGMENT)
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--scratch-root',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(patch(a.source,a.scratch_root),indent=2))
