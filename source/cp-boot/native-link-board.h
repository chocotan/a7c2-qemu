/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef A7C2_NATIVE_LINK_BOARD_H
#define A7C2_NATIVE_LINK_BOARD_H
#include "qemu/error-report.h"
#include "hw/core/boards.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/sysbus.h"
#include "system/hostmem.h"
#include "qapi/error.h"

#define NATIVE_LINK_PROFILE "virtual-native-ap-cp-link-v1"

/* One paired local experiment; never selects the old test peer or direct DMA. */
static inline bool native_link_enabled(const char *side)
{
    const char *profile = g_getenv("QEMU_NATIVE_AP_CP_LINK");
    if (!profile) {
        return false;
    }
    if (strcmp(profile, NATIVE_LINK_PROFILE) ||
        g_strcmp0(g_getenv("QEMU_AP_CP_GPIO_SIDE"), side) ||
        g_strcmp0(g_getenv("QEMU_AP_CP_GPIO_LINES"), "virtual-ap-cp-gpio-lines-v1") ||
        g_getenv("QEMU_CP_EDMA_DIRECT") || g_getenv("QEMU_SONY_ATU_TEST") ||
        g_getenv("QEMU_SONY_PCIDMA_TEST") || g_getenv("QEMU_SONY_PCIE_PEER_TEST")) {
        error_report("Native AP/CP link requires its exact side and GPIO profile, without legacy peers/direct DMA");
        exit(1);
    }
    if (!strcmp(side, "cp") &&
        (g_strcmp0(g_getenv("QEMU_CP_GIC"), "1") ||
         g_strcmp0(g_getenv("QEMU_CP_TIMERS"), "1") ||
         g_strcmp0(g_getenv("QEMU_CP_WATCHDOG"), "1") ||
         g_strcmp0(g_getenv("QEMU_CP_EDMA_GATE"), "1") ||
         g_strcmp0(g_getenv("QEMU_CP_UIPC_RAM"), "1") ||
         g_strcmp0(g_getenv("QEMU_CP_BOOT_PERIPHERALS"), "virtual-cp-boot-peripherals-v1"))) {
        error_report("Native CP link requires the complete explicit CP controller profile");
        exit(1);
    }
    return true;
}

static inline MemoryRegion *native_link_peer_memory(MachineState *machine,
                                                    const char *side)
{
    Object *peer = object_resolve_path_component(object_get_objects_root(), "native-peer-ram");
    Object *oom = object_resolve_path_component(object_get_objects_root(), "native-peer-oom");
    if (!machine->memdev || !peer || (strcmp(side, "ap") && oom)) {
        error_report("Native link requires its separate file-backed local and peer RAM objects");
        exit(1);
    }
    DeviceState *view = qdev_new("a7c2-native-peer-ram");
    object_property_add_child(OBJECT(machine), "native-peer-view", OBJECT(view));
    qdev_prop_set_string(view, "side", side);
    object_property_set_link(OBJECT(view), "local-backend", OBJECT(machine->memdev), &error_fatal);
    object_property_set_link(OBJECT(view), "peer-backend", peer, &error_fatal);
    if (oom) {
        object_property_set_link(OBJECT(view), "peer-oom-backend", oom, &error_fatal);
    }
    SysBusDevice *bus = SYS_BUS_DEVICE(view);
    sysbus_realize_and_unref(bus, &error_fatal);
    fprintf(stderr, "NATIVE_LINK profile=%s side=%s separate_local_backing=1 physical_compatible=0\n",
            NATIVE_LINK_PROFILE, side);
    return sysbus_mmio_get_region(bus, 0);
}

MemoryRegion *a7c2_native_local_oom(MachineState *machine, Error **errp);
#endif
