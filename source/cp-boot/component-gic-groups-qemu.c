/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Qtest-only secure bus master for real GICD_IGROUPR; no pending/IRQ access. */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/intc/arm_gic.h"
#include "system/qtest.h"
#include "migration/vmstate.h"
#include "qapi/error.h"
#include "exec/memop.h"

#define TYPE_COMPONENT_GIC_GROUPS "a7c2-component-gic-groups"
OBJECT_DECLARE_SIMPLE_TYPE(ComponentGicGroups, COMPONENT_GIC_GROUPS)
struct ComponentGicGroups {
    SysBusDevice parent_obj;
    DeviceState *controller;
    MemoryRegion groups;
    MemoryRegion *target;
};

static bool access_valid(hwaddr offset, unsigned size)
{
    return size == 4 && !(offset & 3) && offset < 0x40;
}
static MemTxResult group_read(void *opaque, hwaddr offset, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    ComponentGicGroups *s = opaque;
    MemTxAttrs secure = { .secure = true };
    if (!qtest_enabled() || !access_valid(offset, size)) {
        return MEMTX_ERROR;
    }
    return memory_region_dispatch_read(s->target, 0x80 + offset, value,
                                        MO_32 | MO_LE, secure);
}
static MemTxResult group_write(void *opaque, hwaddr offset, uint64_t value,
                               unsigned size, MemTxAttrs attrs)
{
    ComponentGicGroups *s = opaque;
    MemTxAttrs secure = { .secure = true };
    if (!qtest_enabled() || !access_valid(offset, size) || value > UINT32_MAX) {
        return MEMTX_ERROR;
    }
    return memory_region_dispatch_write(s->target, 0x80 + offset, value,
                                         MO_32 | MO_LE, secure);
}
static const MemoryRegionOps group_ops = {
    .read_with_attrs = group_read, .write_with_attrs = group_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
};
static void groups_realize(DeviceState *dev, Error **errp)
{
    ComponentGicGroups *s = COMPONENT_GIC_GROUPS(dev);
    if (!qtest_enabled() || !s->controller || !s->controller->realized) {
        error_setg(errp, "Component secure GIC group window requires qtest and a realized original GIC");
        return;
    }
    s->target = sysbus_mmio_get_region(SYS_BUS_DEVICE(s->controller), 0);
    memory_region_init_io(&s->groups, OBJECT(dev), &group_ops, s,
                          TYPE_COMPONENT_GIC_GROUPS, 0x40);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->groups);
}
static const Property group_properties[] = {
    DEFINE_PROP_LINK("controller", ComponentGicGroups, controller, TYPE_ARM_GIC, DeviceState *),
};
static const VMStateDescription group_vmstate = {
    .name = TYPE_COMPONENT_GIC_GROUPS, .unmigratable = true,
};
static void groups_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize = groups_realize;
    dc->vmsd = &group_vmstate;
    dc->user_creatable = false;
    device_class_set_props(dc, group_properties);
    dc->desc = "Diagnostic qtest secure GIC group window, no IRQ/pending synthesis";
}
static const TypeInfo group_type = {
    .name = TYPE_COMPONENT_GIC_GROUPS, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(ComponentGicGroups), .class_init = groups_class_init,
};
static void register_groups(void) { type_register_static(&group_type); }
type_init(register_groups)
