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


def stage(source):
    source=Path(source).absolute()
    if source.is_symlink() or not source.is_dir() or any(p.is_symlink() for p in source.parents):
        raise ValueError('Ordinary independent source directory required')
    board=source/'hw/arm/virt.c';meson=source/'hw/usb/meson.build';text=board.read_text();build=meson.read_text()
    if 'sony-dwc3-gadget' in text or 'sony-dwc3.c' in build:raise ValueError('USB device model already staged; use a fresh source')
    include='#include "hw/arm/virt.h"';anchor='    create_msi_controller(vms);'
    if text.count(include)!=1 or text.count(anchor)!=1:raise ValueError('Unsupported product QEMU board')
    before={str(p.relative_to(source)):sha(p) for p in (board,meson)}
    outputs={}
    for name in FILES[:4]:
        path=source/'hw/usb'/name
        with path.open('x') as output:
            if name=='sony-dwc3.c':output.write('#define SONY_DWC3_QEMU 1\n')
            output.write((HERE/name).read_text())
        outputs[str(path.relative_to(source))]=sha(path)
    provider=source/'hw/arm/sony-usb-device-platform.inc'
    with provider.open('x') as output:output.write((HERE/'sony-usb-platform.inc').read_text())
    outputs[str(provider.relative_to(source))]=sha(provider)
    fragment=(HERE/'board-fragment.inc').read_text()
    text=text.replace(include,include+'\n#include "qemu/log.h"\n#include "hw/arm/sony-usb-device-platform.inc"',1)
    code='    if (!g_strcmp0(g_getenv("QEMU_SONY_USB_DEVICE"), "1")) {\n'+fragment+'\n    }\n'
    board.write_text(text.replace(anchor,code+anchor,1))
    meson.write_text(build+"\nsystem_ss.add(when: 'CONFIG_USB', if_true: files('sony-dwc3.c', 'sony-dwc3-bridge.c'))\n")
    outputs.update({str(p.relative_to(source)):sha(p) for p in (board,meson)})
    return dict(schema='a7c2-product-sony-usb-device-build-v1',profile='virtual-functional-sony-usb-device-v1',source_before=before,source_after=outputs,product_sources={name:sha(HERE/name) for name in (*FILES,'stage.py')},firmware_descriptors_in_model=False,default_enabled=False,host_enumerated=False,authentication_verified=False,physical_asic_verified=False)


if __name__=='__main__':print(json.dumps(stage(sys.argv[1]),indent=2))
