/* SPDX-License-Identifier: GPL-2.0-or-later
 * Route the real PL080 masked per-channel TC/error state to CP INTIDs.
 * The upstream controller performs DMA; this wrapper never synthesizes completion.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "qapi/error.h"
#include "migration/vmstate.h"
#include "exec/memop.h"

#define TYPE_CP_PL080 "a7c2-cp-pl080"
OBJECT_DECLARE_SIMPLE_TYPE(CpPl080State, CP_PL080)
struct CpPl080State {
    SysBusDevice parent_obj;
    DeviceState *controller;
    MemoryRegion proxy;
    qemu_irq channel[8];
    unsigned logged;
};
static void update_channels(CpPl080State *s)
{
    uint64_t tc = 0, error = 0;
    MemoryRegion *target = sysbus_mmio_get_region(SYS_BUS_DEVICE(s->controller), 0);
    MemTxResult a = memory_region_dispatch_read(target, 0x04, &tc, MO_32 | MO_LE, MEMTXATTRS_UNSPECIFIED);
    MemTxResult b = memory_region_dispatch_read(target, 0x0c, &error, MO_32 | MO_LE, MEMTXATTRS_UNSPECIFIED);
    uint32_t pending = a == MEMTX_OK && b == MEMTX_OK ? (tc | error) & 0xff : 0;
    for (unsigned channel = 0; channel < 8; channel++) {
        qemu_set_irq(s->channel[channel], !!(pending & (1u << channel)));
    }
    if (s->logged++ < 64) {
        fprintf(stderr, "CP_PL080 pending=0x%x tc=0x%" PRIx64 " error=0x%" PRIx64
                " source=upstream-controller physical_compatible=0\n", pending, tc, error);
    }
}
static void aggregate_irq(void *opaque, int number, int level)
{
    CpPl080State *s = opaque;
    update_channels(s);
}
static bool access_valid(hwaddr offset, unsigned size)
{
    return (size == 1 || size == 2 || size == 4) && !(offset & (size - 1)) && offset < 0x1000;
}
static MemOp access_op(unsigned size)
{
    return MO_LE | (size == 1 ? MO_8 : size == 2 ? MO_16 : MO_32);
}
static MemTxResult proxy_read(void *opaque, hwaddr offset, uint64_t *value,
                              unsigned size, MemTxAttrs attrs)
{
    CpPl080State *s = opaque;
    if (!access_valid(offset, size)) {
        return MEMTX_ERROR;
    }
    return memory_region_dispatch_read(sysbus_mmio_get_region(SYS_BUS_DEVICE(s->controller), 0),
                                       offset, value, access_op(size), attrs);
}
static MemTxResult proxy_write(void *opaque, hwaddr offset, uint64_t value,
                               unsigned size, MemTxAttrs attrs)
{
    CpPl080State *s = opaque;
    if (!access_valid(offset, size)) {
        return MEMTX_ERROR;
    }
    MemTxResult result = memory_region_dispatch_write(
        sysbus_mmio_get_region(SYS_BUS_DEVICE(s->controller), 0), offset, value, access_op(size), attrs);
    update_channels(s);
    return result;
}
static const MemoryRegionOps proxy_ops = {
    .read_with_attrs = proxy_read, .write_with_attrs = proxy_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 1, .max_access_size = 4 },
};
static void router_reset(DeviceState *dev)
{
    CpPl080State *s = CP_PL080(dev);
    if (s->controller && s->controller->realized) {
        device_cold_reset(s->controller);
    }
    for (unsigned channel = 0; channel < 8; channel++) {
        qemu_set_irq(s->channel[channel], 0);
    }
    s->logged = 0;
}
static void router_realize(DeviceState *dev, Error **errp)
{
    CpPl080State *s = CP_PL080(dev);
    if (!s->controller || !s->controller->realized) {
        error_setg(errp, "CP PL080 router requires an already-realized upstream pl080");
        return;
    }
    for (unsigned channel = 0; channel < 8; channel++) {
        sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->channel[channel]);
    }
    qdev_init_gpio_in_named(dev, aggregate_irq, "aggregate", 1);
    sysbus_connect_irq(SYS_BUS_DEVICE(s->controller), 0,
                       qdev_get_gpio_in_named(dev, "aggregate", 0));
    memory_region_init_io(&s->proxy, OBJECT(dev), &proxy_ops, s, "cp-pl080-upstream-proxy", 0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->proxy);
}
static const Property router_properties[] = {
    DEFINE_PROP_LINK("controller", CpPl080State, controller, "pl080", DeviceState *),
};
static const VMStateDescription router_vmstate = {
    .name = TYPE_CP_PL080,
    .unmigratable = true,
};
static void router_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize = router_realize;
    dc->vmsd = &router_vmstate;
    device_class_set_legacy_reset(dc, router_reset);
    device_class_set_props(dc, router_properties);
    dc->desc = "CP per-channel IRQ adapter for upstream PL080, no fake DMA completion";
}
/* shortcut: this explicit boot profile has no paired migration contract yet. */
static const TypeInfo router_type = {
    .name = TYPE_CP_PL080, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CpPl080State), .class_init = router_class_init,
};
static void router_register(void) { type_register_static(&router_type); }
type_init(router_register)
