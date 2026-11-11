#!/usr/bin/env python3
"""Stage the explicit GPIO18 model into the pinned private CP diagnostic tree."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-gpio18-loader-state-v1'
BASES = {
    'hw/core/null-machine.c': '8d4e4ab5863c5bd8408ba276f13c5f58b93bf1048750a68bb450e0fc4de06af3',
    'hw/gpio/meson.build': 'f28a7f223c66915f96198503de99a9aa937a384823cd9806953012ab3384aae4',
}
FILES = ('gpio18.h', 'gpio18.c', 'gpio18-qemu.c')
ANCHOR = '    if (g_getenv("QEMU_CP_UIPC_RAM")) {'
INSERT = '''    const char *gpio18 = g_getenv("QEMU_CP_GPIO18_PROFILE");
    if (gpio18) {
        if (strcmp(gpio18, "virtual-gpio18-loader-state-v1")) {
            error_report("Unknown functional CP GPIO18 profile");
            exit(1);
        }
        DeviceState *gpio = qdev_new("a7c2-cp-gpio18");
        SysBusDevice *bus = SYS_BUS_DEVICE(gpio);
        sysbus_realize_and_unref(bus, &error_fatal);
        sysbus_mmio_map(bus, 0, 0xf102f000);
    }
'''
MESON = "system_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('gpio18.c', 'gpio18-qemu.c'))\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stage(tree):
    tree = Path(tree).resolve(strict=True)
    receipt = tree / 'cp-gpio18-stage.json'
    if receipt.exists():
        proof = json.loads(receipt.read_text())
        if proof.get('profile') != PROFILE or set(proof.get('sources', {})) != set(FILES):
            raise ValueError('Unknown prior CP GPIO18 stage')
        for name in FILES:
            if sha((HERE / name).read_bytes()) != proof['sources'][name]:
                raise ValueError('Model source changed after staging: ' + name)
        for name, digest in proof['outputs'].items():
            if (tree / name).is_symlink() or sha((tree / name).read_bytes()) != digest:
                raise ValueError('Staged CP source changed: ' + name)
        return proof
    originals = {}
    for name, digest in BASES.items():
        path = tree / name
        if path.is_symlink() or sha(path.read_bytes()) != digest:
            raise ValueError('Pinned private CP base differs: ' + name)
        originals[name] = path.read_bytes()
    text = originals['hw/core/null-machine.c'].decode()
    if text.count(ANCHOR) != 1:
        raise ValueError('Unknown CP GPIO18 insertion anchor')
    planned = {
        'hw/core/null-machine.c': text.replace(ANCHOR, INSERT + ANCHOR).encode(),
        'hw/gpio/meson.build': originals['hw/gpio/meson.build'] + MESON.encode(),
    }
    sources = {}
    for name in FILES:
        data = (HERE / name).read_bytes()
        if (tree / 'hw/gpio' / name).exists():
            raise ValueError('Unowned GPIO18 destination: ' + name)
        planned['hw/gpio/' + name] = data
        sources[name] = sha(data)
    # Save exact source restoration bytes before any changes; no firmware/disk is touched.
    backup = tree / 'cp-gpio18-before'
    backup.mkdir()
    for name, data in originals.items():
        dest = backup / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    for name, data in planned.items():
        (tree / name).write_bytes(data)
    proof = dict(schema='a7c2-cp-gpio18-stage-v1', profile=PROFILE, default_off=True,
                 base_sha256=BASES, sources=sources,
                 outputs={name: sha(data) for name, data in planned.items()},
                 physical_compatible=False, peer_input_supplied=False,
                 source_scope='Pinned private CP diagnostic tree only; not vanilla QEMU')
    with receipt.open('x') as stream:
        stream.write(json.dumps(proof, indent=2, sort_keys=True) + '\n')
    return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('qemu_source', type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.qemu_source), indent=2))
