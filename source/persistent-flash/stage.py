#!/usr/bin/env python3
"""Stage the default-off persistent flash model after the native QEMU patches."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE=Path(__file__).resolve().parent
FILES=('flash-core.h','flash-core.c','flash-qemu.c')
INCLUDE='#include "../block/a7c2-persistent/flash-qemu.c"\n'
FRAGMENT='''
    /* This profile consumes one parent-owned regular-file descriptor. */
    const char *pf_profile = g_getenv("QEMU_A7PF_PROFILE");
    const char *pf_keys[] = {"QEMU_A7PF_FD", "QEMU_A7PF_DEV", "QEMU_A7PF_INO"};
    uint64_t pf_values[3] = {0};
    bool pf_any = pf_profile != NULL;
    for (unsigned int i = 0; i < 3; i++) {
        pf_any |= g_getenv(pf_keys[i]) != NULL;
    }
    if (pf_any) {
        if (!pf_profile || strcmp(pf_profile, "persistent-flash-cold-v1")) {
            error_report("missing or invalid persistent flash profile");
            exit(1);
        }
        for (unsigned int i = 0; i < 3; i++) {
            const char *value = g_getenv(pf_keys[i]);
            if (!value || !*value || strspn(value, "0123456789") != strlen(value)) {
                error_report("invalid persistent flash numeric property");
                exit(1);
            }
            errno = 0;
            pf_values[i] = g_ascii_strtoull(value, NULL, 10);
            if (errno || !pf_values[i]) {
                error_report("overflow or zero persistent flash property");
                exit(1);
            }
        }
        if (pf_values[0] < 3 || pf_values[0] > INT_MAX) {
            error_report("persistent flash fd must be inherited and >=3");
            exit(1);
        }
        DeviceState *pf = qdev_new("sony-persistent-flash");
        qdev_prop_set_int32(pf, "backend-fd", pf_values[0]);
        qdev_prop_set_string(pf, "geometry", "/instance/persistent-geometry.bin");
        qdev_prop_set_uint64(pf, "expected-dev", pf_values[1]);
        qdev_prop_set_uint64(pf, "expected-ino", pf_values[2]);
        sysbus_realize_and_unref(SYS_BUS_DEVICE(pf), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(pf), 0, 0x0b010000);
    }
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(source):
    source=Path(source).resolve(strict=True)
    board=source/'hw/arm/virt.c'
    target=source/'hw/block/a7c2-persistent'
    text=board.read_text()
    anchor='static void machvirt_init(MachineState *machine)\n{'
    if text.count(anchor)!=1 or INCLUDE in text or target.exists():
        raise ValueError('Unexpected or already staged persistent flash source')
    before=sha(board)
    target.mkdir(parents=True)
    for name in FILES:
        shutil.copyfile(HERE/name,target/name)
    board.write_text(text.replace(anchor,anchor+FRAGMENT)+'\n'+INCLUDE)
    return dict(schema='a7c2-default-off-persistent-hardware-source-v1',profile='persistent-flash-cold-v1',
                source_files={n:sha(HERE/n) for n in FILES},stage_source_sha256=sha(Path(__file__)),
                board_before=before,board_after=sha(board),default_enabled=False,
                parent_regular_file_fd_required=True,mmio_base='0x0b010000',usb_network_mmio_nonoverlap=True,physical_emmc_compatibility_verified=False,
                original_guest_execution_verified=False)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: stage.py PATCHED_QEMU_SOURCE')
    print(json.dumps(stage(sys.argv[1]),indent=2))
