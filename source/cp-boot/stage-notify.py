#!/usr/bin/env python3
"""Add default-off output-driven AP/CP GPIO lines to the pinned CP diagnostic."""
import argparse
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROFILE='virtual-ap-cp-gpio-lines-v1'
PARENT_SHA='f7f94f364bd1509957d9b5aea8370dab2ae02fe874237efc0081a8728024be0d'
BASES={
    'hw/core/null-machine.c':'76627ad13b640723d8c6cefee7968431e4b6d7bcfb003889e4411e49acf2ab6f',
    'hw/gpio/meson.build':'338d5f6a18151290d85495cf0692b7e2a70a0a6638d617f45168b5c493b479c6',
    'hw/arm/virt.c':'0e7ff65238d2ae7b49cc902573fe03cdf325206fdf80079d57f70de817e3d103',
}
FILES=('notify.h','notify.c','notify-qemu.c')
INSERT='''    const char *notify = g_getenv("QEMU_AP_CP_GPIO_LINES");
    if (notify) {
        const char *side = g_getenv("QEMU_AP_CP_GPIO_SIDE");
        Chardev *peer = qemu_chr_find("notify-peer");
        if (strcmp(notify, "virtual-ap-cp-gpio-lines-v1") || !side ||
            (strcmp(side, "ap") && strcmp(side, "cp")) || !peer ||
            g_getenv("QEMU_CP_GPIO18_PROFILE")) {
            error_report("GPIO lines require explicit profile, AP/CP side and dedicated notify-peer; no legacy GPIO18 overlap");
            exit(1);
        }
        DeviceState *dev = qdev_new("a7c2-ap-cp-gpio-lines");
        qdev_prop_set_string(dev, "side", side);
        qdev_prop_set_chr(dev, "chardev", peer);
        SysBusDevice *bus = SYS_BUS_DEVICE(dev);
        sysbus_realize_and_unref(bus, &error_fatal);
        sysbus_mmio_map(bus, 0, 0xf102e000);
        sysbus_mmio_map(bus, 1, 0xf102f000);
    }
'''
AP_INSERT='''
    const char *notify = g_getenv("QEMU_AP_CP_GPIO_LINES");
    if (notify) {
        const char *side = g_getenv("QEMU_AP_CP_GPIO_SIDE");
        Chardev *peer = qemu_chr_find("notify-peer");
        if (strcmp(notify, "virtual-ap-cp-gpio-lines-v1") || !side ||
            strcmp(side, "ap") || !peer || g_getenv("QEMU_CP_GPIO18_PROFILE")) {
            error_report("AP GPIO lines require explicit profile, side=ap and notify-peer");
            exit(1);
        }
        DeviceState *dev = qdev_new("a7c2-ap-cp-gpio-lines");
        qdev_prop_set_string(dev, "side", "ap");
        qdev_prop_set_chr(dev, "chardev", peer);
        SysBusDevice *bus = SYS_BUS_DEVICE(dev);
        sysbus_realize_and_unref(bus, &error_fatal);
        memory_region_add_subregion_overlap(sysmem, 0xf102e000,
                                             sysbus_mmio_get_region(bus, 0), 2);
        memory_region_add_subregion_overlap(sysmem, 0xf102f000,
                                             sysbus_mmio_get_region(bus, 1), 2);
        sysbus_connect_irq(bus, 0, qdev_get_gpio_in(vms->gic, 60));
        sysbus_connect_irq(bus, 1, qdev_get_gpio_in(vms->gic, 59));
    }
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stage(tree):
    tree=Path(tree).resolve(strict=True)
    parent_path=tree/'cp-gpio18-stage.json'
    if parent_path.is_symlink() or sha(parent_path.read_bytes())!=PARENT_SHA:
        raise ValueError('Pinned GPIO18 parent stage differs')
    parent=json.loads(parent_path.read_text())
    inherited={name:digest for name,digest in parent['outputs'].items() if name not in BASES}
    for name,digest in inherited.items():
        path=tree/name
        if path.is_symlink() or sha(path.read_bytes())!=digest:
            raise ValueError('Inherited GPIO18 source differs: '+name)
    receipt=tree/'cp-notify-stage.json'
    if receipt.exists():
        proof=json.loads(receipt.read_text())
        if proof.get('profile')!=PROFILE or proof.get('parent_stage_sha256')!=PARENT_SHA:
            raise ValueError('Unknown prior notification stage')
        for name in FILES:
            if sha((HERE/name).read_bytes())!=proof['sources'].get(name):
                raise ValueError('Notification source changed after staging')
        for name,digest in proof['outputs'].items():
            path=tree/name
            if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or sha(path.read_bytes())!=digest:
                raise ValueError('Notification stage drift: '+name)
        return proof
    originals={}
    for name,digest in BASES.items():
        path=tree/name
        if path.is_symlink() or sha(path.read_bytes())!=digest:
            raise ValueError('Pinned CP notification base differs: '+name)
        originals[name]=path.read_bytes()
    board=originals['hw/core/null-machine.c'].decode()
    anchor='    const char *gpio18 = g_getenv("QEMU_CP_GPIO18_PROFILE");'
    include='#include "hw/core/qdev-properties.h"'
    if board.count(anchor)!=1 or board.count(include)!=1:
        raise ValueError('Unknown notification insertion anchors')
    board=board.replace(include,include+'\n#include "hw/core/qdev-properties-system.h"\n#include "chardev/char.h"')
    ap_board=originals['hw/arm/virt.c'].decode()
    ap_anchor='    create_gic(vms, sysmem);'
    if ap_board.count(ap_anchor)!=1 or ap_board.count(include)!=1:
        raise ValueError('Unknown AP notification insertion anchors')
    ap_board=ap_board.replace(include,include+'\n#include "hw/core/qdev-properties-system.h"\n#include "chardev/char.h"')
    planned={'hw/core/null-machine.c':board.replace(anchor,INSERT+anchor).encode(),
             'hw/arm/virt.c':ap_board.replace(ap_anchor,ap_anchor+AP_INSERT).encode(),
             'hw/gpio/meson.build':originals['hw/gpio/meson.build']+b"system_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('notify.c', 'notify-qemu.c'))\n"}
    sources={}
    for name in FILES:
        if (tree/'hw/gpio'/name).exists():
            raise ValueError('Unowned notification target: '+name)
        data=(HERE/name).read_bytes()
        planned['hw/gpio/'+name]=data
        sources[name]=sha(data)
    backup=tree/'cp-notify-before'
    backup.mkdir()
    for name,data in originals.items():
        path=backup/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        if path.read_bytes()!=data:
            raise ValueError('Original source backup readback differs')
    for name,data in planned.items():
        path=tree/name;path.write_bytes(data)
        if path.read_bytes()!=data:
            raise ValueError('Notification source readback differs')
    proof=dict(schema='a7c2-cp-notify-stage-v1',profile=PROFILE,parent_stage_sha256=PARENT_SHA,
               base_sha256=BASES,inherited_sources=inherited,sources=sources,
               outputs={name:sha(data) for name,data in planned.items()},default_off=True,
               physical_compatible=False,cp_irq_supported=False,ap_gic_spis=[60,59],
               original_ap_consumption_verified=False)
    with receipt.open('x') as stream:
        stream.write(json.dumps(proof,indent=2,sort_keys=True)+'\n')
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu_source',type=Path)
    print(json.dumps(stage(parser.parse_args().qemu_source),indent=2))
