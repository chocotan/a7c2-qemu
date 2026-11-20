#!/usr/bin/env python3
"""Stage the explicit Sony device hardware into a fresh product QEMU source."""
import hashlib
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
FILES=('sony-dwc3.c','sony-dwc3.h','sony-dwc3-bridge.c','sony-dwc3-bridge.h','sony-usb-platform.inc','board-fragment.inc')

def sha(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()



BUSPOWER_FILES = ('beets-core.h', 'beets-core.c', 'beets-qemu.h',
                  'beets-qemu.c', 'buspower-board.inc')
BUSPOWER_UPSTREAM = {
    'hw/i2c/designware_i2c.c': '48035387864db59e0eb376447672174cc892d6a7ce46349a26abd37152d68785',
    'include/hw/i2c/designware_i2c.h': '1fd1c92862820002f324ce6bb394c3c456ff8c1e3aae10ec516c022f74145866',
}
BUSPOWER_SCU = {
    'scu.c': 'feca9f7aebaaffeb013e2d3449272507f8923f764bd26d9fc797f2510f0e392d',
    'scu.h': 'a2b149ccc433c940dcdb87ddfc3f58d40dccc71d66daf3a7e6d4525c550a6655',
}


def buspower_stage_inputs(source):
    for name, expected in BUSPOWER_UPSTREAM.items():
        if sha(source / name) != expected:
            raise ValueError('Changed QEMU11.1.2 DW-I2C input: ' + name)
    for name, expected in BUSPOWER_SCU.items():
        if sha(HERE.parent / 'cp-boot' / name) != expected:
            raise ValueError('Changed shared SCU core: ' + name)
    config = source / 'hw/arm/Kconfig'
    config_text = config.read_text()
    if config_text.count('config ARM_VIRT\n') != 1:
        raise ValueError('Unique ARM_VIRT Kconfig required')
    return config, config_text


def buspower_stage_files(source):
    outputs = {}
    for name in BUSPOWER_FILES:
        target = source / 'hw/usb' / name
        with target.open('x') as stream:
            stream.write((HERE / name).read_text())
        if sha(target) != sha(HERE / name):
            raise ValueError('BusPower source readback mismatch: ' + name)
        outputs[str(target.relative_to(source))] = sha(target)
    for name in BUSPOWER_SCU:
        target = source / 'hw/usb' / name
        original = HERE.parent / 'cp-boot' / name
        with target.open('x') as stream:
            stream.write(original.read_text())
        if sha(target) != BUSPOWER_SCU[name]:
            raise ValueError('SCU readback mismatch: ' + name)
        outputs[str(target.relative_to(source))] = sha(target)
    return outputs

def stage(source, buspower_candidate=False):
    source=Path(source).absolute()
    if source.is_symlink() or not source.is_dir() or any(p.is_symlink() for p in source.parents):
        raise ValueError('Ordinary independent source directory required')
    buspower_config = buspower_stage_inputs(source) if buspower_candidate else None
    board=source/'hw/arm/virt.c';meson=source/'hw/usb/meson.build';text=board.read_text();build=meson.read_text()
    if 'sony-dwc3-gadget' in text or 'sony-dwc3.c' in build:raise ValueError('USB device model already staged; use a fresh source')
    include='#include "hw/arm/virt.h"';anchor='    create_msi_controller(vms);'
    if text.count(include)!=1 or text.count(anchor)!=1:raise ValueError('Unsupported product QEMU board')
    before={str(p.relative_to(source)):sha(p) for p in (board,meson)}
    outputs={}
    if buspower_candidate:
        config, config_text = buspower_config
        before[str(config.relative_to(source))] = sha(config)
        config.write_text(config_text.replace('config ARM_VIRT\n', 'config ARM_VIRT\n    select DESIGNWARE_I2C\n', 1))
        outputs[str(config.relative_to(source))] = sha(config)
        outputs.update(buspower_stage_files(source))
    for name in FILES[:4]:
        path=source/'hw/usb'/name
        with path.open('x') as output:
            if name=='sony-dwc3.c':output.write('#define SONY_DWC3_QEMU 1\n')
            output.write((HERE/name).read_text())
        outputs[str(path.relative_to(source))]=sha(path)
    provider=source/'hw/arm/sony-usb-device-platform.inc'
    with provider.open('x') as output:
        if buspower_candidate: output.write('#define SONY_USB_BUSPOWER_CANDIDATE 1\n')
        output.write((HERE/'sony-usb-platform.inc').read_text())
    outputs[str(provider.relative_to(source))]=sha(provider)
    fragment=(HERE/'board-fragment.inc').read_text()
    text=text.replace(include,include+'\n#include "qemu/log.h"\n#include "hw/arm/sony-usb-device-platform.inc"',1)
    code='    if (!g_strcmp0(g_getenv("QEMU_SONY_USB_DEVICE"), "1")) {\n'+fragment+'\n    }\n'
    if buspower_candidate:
        code = '    if (g_getenv("QEMU_SONY_USB_BUSPOWER_PROFILE") && g_strcmp0(g_getenv("QEMU_SONY_USB_DEVICE"), "1")) { error_report("BusPower requires USB device profile"); exit(1); }\n' + code
    board.write_text(text.replace(anchor,code+anchor,1))
    meson.write_text(build+"\nsystem_ss.add(when: 'CONFIG_USB', if_true: files('sony-dwc3.c', 'sony-dwc3-bridge.c'))\n")
    if buspower_candidate:
        with meson.open('a') as stream:
            stream.write("\nsystem_ss.add(when: 'CONFIG_USB', if_true: files('beets-core.c', 'beets-qemu.c', 'scu.c'))\n")
    outputs.update({str(p.relative_to(source)):sha(p) for p in (board,meson)})
    return dict(schema=('a7c2-source-only-usb-buspower-build-v1' if buspower_candidate else 'a7c2-product-sony-usb-device-build-v1'),profile=('virtual-a7c2-usb-buspower-v1' if buspower_candidate else 'virtual-functional-sony-usb-device-v1'),source_before=before,source_after=outputs,product_sources={name:sha(HERE/name) for name in (*FILES,'stage.py',*(BUSPOWER_FILES if buspower_candidate else ())) },firmware_descriptors_in_model=False,default_enabled=False,host_enumerated=False,authentication_verified=False,physical_asic_verified=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('--buspower-source-candidate', action='store_true')
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.buspower_source_candidate), indent=2))
