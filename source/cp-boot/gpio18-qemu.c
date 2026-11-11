/* Explicit functional GPIO18 output latch; no peer input, IRQ or link completion.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "qapi/error.h"
#include "gpio18.h"

#define TYPE_CP_GPIO18 "a7c2-cp-gpio18"
OBJECT_DECLARE_SIMPLE_TYPE(CpGpio18State, CP_GPIO18)
struct CpGpio18State {
    SysBusDevice parent_obj;
    MemoryRegion regs;
    struct cp_gpio18 gpio;
    unsigned logged;
};

static void observe(CpGpio18State *s, const char *op, hwaddr offset,
                    uint64_t value, int result)
{
    if (s->logged++ < 48) {
        fprintf(stderr, "CP_GPIO18 profile=virtual-gpio18-loader-state-v1 op=%s offset=0x%" HWADDR_PRIx
                " value=0x%" PRIx64 " result=%d physical_compatible=0\n", op, offset, value, result);
    }
}
static MemTxResult gpio_read(void *opaque, hwaddr offset, uint64_t *value,
                             unsigned size, MemTxAttrs attrs)
{
    CpGpio18State *s = opaque;
    uint32_t data = 0;
    int rc = cp_gpio18_read(&s->gpio, offset, &data);
    observe(s, "read", offset, data, rc);
    if (rc) {
        return MEMTX_ERROR;
    }
    *value = data;
    return MEMTX_OK;
}
static MemTxResult gpio_write(void *opaque, hwaddr offset, uint64_t value,
                              unsigned size, MemTxAttrs attrs)
{
    CpGpio18State *s = opaque;
    int rc = cp_gpio18_write(&s->gpio, offset, value);
    observe(s, "write", offset, value, rc);
    return rc ? MEMTX_ERROR : MEMTX_OK;
}
static const MemoryRegionOps gpio_ops = {
    .read_with_attrs = gpio_read,
    .write_with_attrs = gpio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
};
static void gpio_reset(DeviceState *dev)
{
    CpGpio18State *s = CP_GPIO18(dev);
    if (cp_gpio18_init(&s->gpio, "virtual-gpio18-loader-state-v1")) {
        abort(); /* fixed model-owned profile, not guest data */
    }
    s->logged = 0;
}
static void gpio_realize(DeviceState *dev, Error **errp)
{
    CpGpio18State *s = CP_GPIO18(dev);
    gpio_reset(dev);
    memory_region_init_io(&s->regs, OBJECT(dev), &gpio_ops, s, "a7c2-cp-gpio18", 0x100);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->regs);
}
static void gpio_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize = gpio_realize;
    device_class_set_legacy_reset(dc, gpio_reset);
    dc->desc = "Functional CP GPIO18 loader-state latch (not physical reset values)";
}
static const TypeInfo gpio_type = {
    .name = TYPE_CP_GPIO18, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CpGpio18State), .class_init = gpio_class_init,
};
static void gpio_register_types(void) { type_register_static(&gpio_type); }
type_init(gpio_register_types)
