/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Six independent configuration-only TPU banks; parent owns MMIO/SCU wiring. */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "qapi/error.h"
#include "migration/vmstate.h"
#include "tpu.h"

#define TYPE_CP_TPU "a7c2-cp-tpu"
OBJECT_DECLARE_SIMPLE_TYPE(CpTpuState, CP_TPU)
struct CpTpuState {
    SysBusDevice parent_obj;
    MemoryRegion regs;
    struct tpu state;
    uint32_t bank;
    unsigned logged;
};

static void observe(CpTpuState *s, const char *op, hwaddr offset,
                    uint64_t value, int result)
{
    if (s->logged++ < 96) {
        fprintf(stderr, "CP_TPU profile=virtual-cp-tpu-config-v1 bank=%u"
                " op=%s offset=0x%" HWADDR_PRIx " value=0x%" PRIx64
                " result=%d clock=%d reset=%d active=%d"
                " configuration_only=1 physical_compatible=0 runtime_verified=0\n",
                s->bank, op, offset, value, result, s->state.clock_enabled,
                s->state.reset_held,
                !!(s->state.regs[TPU_REG_ENABLE / 4u] & 1u));
    }
}

static bool tpu_accepts(void *opaque, hwaddr offset, unsigned size,
                        bool is_write, MemTxAttrs attrs)
{
    (void)opaque;
    (void)attrs;
    return !(offset & 3u) && offset / 4u < TPU_REGISTER_COUNT &&
           (size == 2 || (!is_write && size == 4));
}

static MemTxResult tpu_mmio_read(void *opaque, hwaddr offset, uint64_t *value,
                                 unsigned size, MemTxAttrs attrs)
{
    CpTpuState *s = opaque;
    uint16_t data = 0;
    int rc = TPU_ERR_ACCESS;

    if (tpu_accepts(opaque, offset, size, false, attrs)) {
        rc = tpu_read(&s->state, offset, &data);
    }
    observe(s, "read", offset, data, rc);
    if (rc != TPU_OK) {
        return MEMTX_ERROR;
    }
    *value = data;
    return MEMTX_OK;
}

static MemTxResult tpu_mmio_write(void *opaque, hwaddr offset, uint64_t value,
                                  unsigned size, MemTxAttrs attrs)
{
    CpTpuState *s = opaque;
    int rc = TPU_ERR_ACCESS;

    if (tpu_accepts(opaque, offset, size, true, attrs) && value <= UINT16_MAX) {
        rc = tpu_write(&s->state, offset, value);
    }
    observe(s, "write", offset, value, rc);
    return rc == TPU_OK ? MEMTX_OK : MEMTX_ERROR;
}

static const MemoryRegionOps tpu_ops = {
    .read_with_attrs = tpu_mmio_read,
    .write_with_attrs = tpu_mmio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 2, .max_access_size = 4, .unaligned = false,
        .accepts = tpu_accepts,
    },
    .impl = { .min_access_size = 2, .max_access_size = 4, .unaligned = false },
};

static void tpu_clock_input(void *opaque, int n, int level)
{
    CpTpuState *s = opaque;
    int rc = TPU_ERR_ACCESS;

    if (n == 0 && (level == 0 || level == 1)) {
        rc = tpu_set_clock(&s->state, level != 0);
    }
    observe(s, "clock-enable", 0, level, rc);
}

static void tpu_reset_input(void *opaque, int n, int level)
{
    CpTpuState *s = opaque;
    int rc = TPU_ERR_ACCESS;

    if (n == 0 && (level == 0 || level == 1)) {
        rc = tpu_set_reset(&s->state, level != 0);
    }
    observe(s, "reset", 0, level, rc);
}

static void tpu_device_reset(DeviceState *dev)
{
    CpTpuState *s = CP_TPU(dev);

    (void)tpu_init(&s->state);
    s->logged = 0;
}

static void tpu_realize(DeviceState *dev, Error **errp)
{
    CpTpuState *s = CP_TPU(dev);

    if (s->bank >= TPU_BANK_COUNT) {
        error_setg(errp, "CP TPU bank must be in 0..5");
        return;
    }
    tpu_device_reset(dev);
    qdev_init_gpio_in_named(dev, tpu_clock_input, "clock-enable", 1);
    qdev_init_gpio_in_named(dev, tpu_reset_input, "reset", 1);
    memory_region_init_io(&s->regs, OBJECT(dev), &tpu_ops, s,
                          TYPE_CP_TPU, TPU_MMIO_SIZE);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->regs);
}

static const Property tpu_properties[] = {
    DEFINE_PROP_UINT32("bank", CpTpuState, bank, 0),
};

static const VMStateDescription tpu_vmstate = {
    .name = TYPE_CP_TPU,
    .unmigratable = true,
};
static void tpu_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    (void)data;
    dc->realize = tpu_realize;
    dc->vmsd = &tpu_vmstate;
    device_class_set_legacy_reset(dc, tpu_device_reset);
    device_class_set_props(dc, tpu_properties);
    dc->desc = "Configuration-only CP TPU/PWM/phase bank, runtime unsupported";
}

/* shortcut: migration is undefined; implement it before restoring RAM snapshots. */
static const TypeInfo tpu_type = {
    .name = TYPE_CP_TPU,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CpTpuState),
    .class_init = tpu_class_init,
};

static void tpu_register_types(void)
{
    type_register_static(&tpu_type);
}
type_init(tpu_register_types)
