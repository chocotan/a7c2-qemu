/* SPDX-License-Identifier: GPL-2.0-or-later
 * Functional SCU latches plus gated upstream I2C and PL330 windows.
 * Watchdog bit18 decisions and WDT_MISC remain with the original owner.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qemu/bswap.h"
#include "qemu/timer.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/i2c/designware_i2c.h"
#include "qapi/error.h"
#include "migration/vmstate.h"
#include "exec/memop.h"
#include "scu.h"

#define TYPE_CP_SCU "a7c2-cp-scu"
OBJECT_DECLARE_SIMPLE_TYPE(CpScuState, CP_SCU)
#define SCU_REGIONS 14
#define I2C_BANKS 5
#define DMA_BANKS 4
#define PL330_BANKS 2
#define BUS_BANKS (I2C_BANKS + DMA_BANKS)
#define TPU_BANKS 6
#define TIMER_RESET_REGION (SCU_REGIONS + BUS_BANKS)
#define DFS_REGION (TIMER_RESET_REGION + 1)
#define DFS_DELAY_NS 1000u
#define WDT_RESET_BIT (1u << 18)
#define TPU_RESET_MASK (0x3fu << 20)
struct CpScuRegion { CpScuState *owner; uint32_t base; int bank; };
struct CpScuState {
    SysBusDevice parent_obj;
    MemoryRegion regions[SCU_REGIONS + BUS_BANKS + 2];
    struct CpScuRegion contexts[SCU_REGIONS + BUS_BANKS + 2];
    struct cp_scu state;
    QEMUTimer *dfs_timer;
    DeviceState *i2c[I2C_BANKS];
    DeviceState *dma[DMA_BANKS];
    AddressSpace *bus_spaces[BUS_BANKS];
    unsigned initialized_bus_spaces;
    DeviceState *watchdog, *tpu[TPU_BANKS];
    uint32_t tpu_reset_bits, tpu_clock_lines, tpu_reset_lines;
    bool tpu_lines_initialized;
    unsigned logged;
};
static const uint32_t region_bases[SCU_REGIONS] = {
    0,0x10,0x20,0x30,0x40,0x50,0x60,0x70,0x80,
    0x300,0x310,0x320,0x330,0x350,
};

static void observe(CpScuState *s, const char *op, int bank, hwaddr offset,
                     uint64_t value, MemTxResult result)
{
    if (s->logged++ < 1024) {
        fprintf(stderr, "CP_SCU profile=virtual-cp-scu-i2c-v1 op=%s bank=%d"
                " offset=0x%" HWADDR_PRIx " value=0x%" PRIx64
                " result=%d physical_compatible=0 ready_or_ack=0\n",
                op, bank, offset, value, result);
    }
}
static void dfs_tick(void *opaque)
{
    CpScuState *s = opaque;
    if (cp_scu_dfs_complete(&s->state)) {
        fprintf(stderr, "CP_DFS complete target=0x%x virtual=1 clocks_changed=0 physical_compatible=0\n",
                s->state.dfs_target);
    }
}
static void update_tpu_lines(CpScuState *s)
{
    uint32_t clocks = s->state.clock[4] & 0x3f;
    uint32_t resets = (s->tpu_reset_bits >> 20) & 0x3f;
    uint32_t changed_clocks = s->tpu_lines_initialized ? clocks ^ s->tpu_clock_lines : 0x3f;
    uint32_t changed_resets = s->tpu_lines_initialized ? resets ^ s->tpu_reset_lines : 0x3f;
    for (unsigned bank = 0; bank < TPU_BANKS; bank++) {
        if (changed_clocks & (1u << bank)) {
            qemu_set_irq(qdev_get_gpio_in_named(s->tpu[bank], "clock-enable", 0), !!(clocks & (1u << bank)));
        }
        if (changed_resets & (1u << bank)) {
            qemu_set_irq(qdev_get_gpio_in_named(s->tpu[bank], "reset", 0), !!(resets & (1u << bank)));
        }
    }
    s->tpu_clock_lines = clocks;
    s->tpu_reset_lines = resets;
    s->tpu_lines_initialized = true;
}
static MemTxResult timer_reset_read(CpScuState *s, uint64_t *value, MemTxAttrs attrs)
{
    uint64_t watchdog = 0;
    MemTxResult result = memory_region_dispatch_read(
        sysbus_mmio_get_region(SYS_BUS_DEVICE(s->watchdog), 1), 0x40,
        &watchdog, MO_32 | MO_LE, attrs);
    if (result == MEMTX_OK) {
        *value = (watchdog & WDT_RESET_BIT) | s->tpu_reset_bits;
    }
    return result;
}
static MemTxResult timer_reset_write(CpScuState *s, hwaddr offset,
                                     uint64_t value, MemTxAttrs attrs)
{
    if ((offset != 0 && offset != 4 && offset != 8) ||
        (value & ~(uint64_t)(WDT_RESET_BIT | TPU_RESET_MASK))) {
        return MEMTX_ERROR;
    }
    MemTxResult result = memory_region_dispatch_write(
        sysbus_mmio_get_region(SYS_BUS_DEVICE(s->watchdog), 1), 0x40 + offset,
        value & WDT_RESET_BIT, MO_32 | MO_LE, attrs);
    if (result != MEMTX_OK) {
        return result;
    }
    uint32_t bits = value & TPU_RESET_MASK;
    if (offset == 0) {
        s->tpu_reset_bits = bits;
    } else if (offset == 4) {
        s->tpu_reset_bits |= bits;
    } else {
        s->tpu_reset_bits &= ~bits;
    }
    update_tpu_lines(s);
    return MEMTX_OK;
}
static DeviceState *bus_device(CpScuState *s, unsigned bank)
{
    return bank < I2C_BANKS ? s->i2c[bank] : s->dma[bank - I2C_BANKS];
}
static void reset_controller(CpScuState *s, unsigned bank)
{
    DeviceState *target = bus_device(s, bank);
    device_cold_reset(target);
    unsigned outputs = bank < I2C_BANKS ? 1 : bank < I2C_BANKS + 2 ? 9 : 8;
    for (unsigned output = 0; output < outputs; output++) {
        qemu_set_irq(qdev_get_gpio_out_connector(target, SYSBUS_DEVICE_GPIO_IRQ, output), 0);
    }
}
static bool bus_accessible(CpScuState *s, unsigned bank)
{
    if (bank < I2C_BANKS) {
        return (s->state.clock[5] & (1u << (18 + bank))) &&
               !(s->state.reset[5] & (1u << (24 + bank)));
    }
    if (bank < I2C_BANKS + PL330_BANKS) {
        return !(s->state.reset[3] & (1u << (14 + bank - I2C_BANKS)));
    }
    /* PL080's SCU reset/clock route is unknown; never infer the next bits. */
    return true;
}
static bool bus_size_valid(unsigned bank, unsigned size, hwaddr offset)
{
    return (bank < I2C_BANKS ? size == 4 : (size == 1 || size == 2 || size == 4)) &&
           !(offset & (size - 1)) && offset < (bank < I2C_BANKS ? 0x100 : 0x1000);
}
static MemTxResult scu_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    struct CpScuRegion *region = opaque;
    CpScuState *s = region->owner;
    uint64_t data = 0;
    MemTxResult rc = MEMTX_ERROR;
    if (region->bank >= 0) {
        if (bus_size_valid(region->bank, size, offset) && bus_accessible(s, region->bank)) {
            uint32_t raw = 0;
            /* A stock controller may expose a container with register subregions. */
            rc = address_space_read(s->bus_spaces[region->bank], offset, attrs, &raw, size);
            data = le32_to_cpu(raw);
        }
    } else if (region->bank == -3) {
        uint32_t word = 0;
        if (size == 4 && !cp_scu_dfs_read(&s->state, offset, &word)) {
            data = word;
            rc = MEMTX_OK;
        }
    } else if (region->bank == -2) {
        if (size == 4 && offset == 0) {
            rc = timer_reset_read(s, &data, attrs);
        }
    } else if (size == 4 && !(offset & 3)) {
        uint32_t word = 0;
        if (!cp_scu_read(&s->state, region->base + offset, &word)) {
            data = word;
            rc = MEMTX_OK;
        }
    }
    observe(s, "read", region->bank, region->base + offset, data, rc);
    if (rc == MEMTX_OK) {
        *value = data;
    }
    return rc;
}
static MemTxResult scu_write(void *opaque, hwaddr offset, uint64_t value,
                             unsigned size, MemTxAttrs attrs)
{
    struct CpScuRegion *region = opaque;
    CpScuState *s = region->owner;
    MemTxResult rc = MEMTX_ERROR;
    if (region->bank >= 0) {
        if (bus_size_valid(region->bank, size, offset) && bus_accessible(s, region->bank)) {
            uint32_t raw = cpu_to_le32(value);
            rc = address_space_write(s->bus_spaces[region->bank], offset, attrs, &raw, size);
        }
    } else if (region->bank == -3) {
        if (size == 4 && value <= UINT32_MAX &&
            !cp_scu_dfs_write(&s->state, offset, value)) {
            rc = MEMTX_OK;
            if (offset == 8) {
                timer_mod(s->dfs_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + DFS_DELAY_NS);
            }
        }
    } else if (region->bank == -2) {
        if (size == 4 && !(offset & 3)) {
            rc = timer_reset_write(s, offset, value, attrs);
        }
    } else if (size == 4 && !(offset & 3) && value <= UINT32_MAX) {
        uint32_t old_i2c_reset = s->state.reset[5];
        uint32_t old_dma_reset = s->state.reset[3];
        if (!cp_scu_write(&s->state, region->base + offset, value)) {
            rc = MEMTX_OK;
            update_tpu_lines(s);
            uint32_t asserted = s->state.reset[5] & ~old_i2c_reset;
            for (unsigned bank = 0; bank < I2C_BANKS; bank++) {
                if (asserted & (1u << (24 + bank))) {
                    reset_controller(s, bank);
                }
            }
            asserted = s->state.reset[3] & ~old_dma_reset;
            for (unsigned bank = 0; bank < PL330_BANKS; bank++) {
                if (asserted & (1u << (14 + bank))) {
                    reset_controller(s, I2C_BANKS + bank);
                }
            }
        }
    }
    observe(s, "write", region->bank, region->base + offset, value, rc);
    return rc;
}
static const MemoryRegionOps scu_ops = {
    .read_with_attrs = scu_read, .write_with_attrs = scu_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 1, .max_access_size = 4 },
};
static void scu_reset(DeviceState *dev)
{
    CpScuState *s = CP_SCU(dev);
    if (s->dfs_timer) timer_del(s->dfs_timer);
    if (cp_scu_init(&s->state, CP_SCU_PROFILE)) {
        abort();
    }
    s->logged = 0;
    s->tpu_reset_bits = 0;
    s->tpu_lines_initialized = false;
    for (unsigned bank = 0; bank < TPU_BANKS; bank++) {
        if (s->tpu[bank]) {
            device_cold_reset(s->tpu[bank]);
        }
    }
    if (s->tpu[0]) {
        update_tpu_lines(s);
    }
    for (unsigned bank = 0; bank < BUS_BANKS; bank++) {
        DeviceState *target = bus_device(s, bank);
        if (target) {
            reset_controller(s, bank);
        }
    }
}
static void scu_realize(DeviceState *dev, Error **errp)
{
    CpScuState *s = CP_SCU(dev);
    for (unsigned bank = 0; bank < BUS_BANKS; bank++) {
        DeviceState *target = bus_device(s, bank);
        if (!target || !target->realized) {
            error_setg(errp, "SCU requires five realized I2C, two PL330 and two PL080 router links");
            return;
        }
    }
    if (!s->watchdog || !s->watchdog->realized) {
        error_setg(errp, "SCU timer reset composition requires the original watchdog");
        return;
    }
    for (unsigned bank = 0; bank < TPU_BANKS; bank++) {
        if (!s->tpu[bank] || !s->tpu[bank]->realized) {
            error_setg(errp, "SCU requires six realized TPU configuration links");
            return;
        }
    }
    for (unsigned bank = 0; bank < BUS_BANKS; bank++) {
        MemoryRegion *root = sysbus_mmio_get_region(SYS_BUS_DEVICE(bus_device(s, bank)), 0);
        s->bus_spaces[bank] = g_new0(AddressSpace, 1);
        address_space_init(s->bus_spaces[bank], root, "cp-scu-controller");
        s->initialized_bus_spaces++;
    }
    s->dfs_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, dfs_tick, s);
    scu_reset(dev);
    for (unsigned i = 0; i < SCU_REGIONS + BUS_BANKS; i++) {
        bool is_bus = i >= SCU_REGIONS;
        unsigned bank = is_bus ? i - SCU_REGIONS : 0;
        s->contexts[i].owner = s;
        s->contexts[i].base = is_bus ? 0 : region_bases[i];
        s->contexts[i].bank = is_bus ? (int)bank : -1;
        memory_region_init_io(&s->regions[i], OBJECT(dev), &scu_ops,
            &s->contexts[i], is_bus ? "cp-scu-gated-controller" : "cp-scu-registers",
            !is_bus ? 0x10 : bank < I2C_BANKS ? 0x100 : 0x1000);
        sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->regions[i]);
    }
    s->contexts[TIMER_RESET_REGION] = (struct CpScuRegion){s, 0x340, -2};
    memory_region_init_io(&s->regions[TIMER_RESET_REGION], OBJECT(dev), &scu_ops,
        &s->contexts[TIMER_RESET_REGION], "cp-scu-watchdog-tpu-reset-composition", 0x10);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->regions[TIMER_RESET_REGION]);
    s->contexts[DFS_REGION] = (struct CpScuRegion){s, 0xf48, -3};
    memory_region_init_io(&s->regions[DFS_REGION], OBJECT(dev), &scu_ops,
        &s->contexts[DFS_REGION], "cp-virtual-dfs-selector", 0x14);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->regions[DFS_REGION]);
}
static void scu_finalize(Object *obj)
{
    CpScuState *s = CP_SCU(obj);
    if (s->dfs_timer) timer_free(s->dfs_timer);
    for (unsigned bank = 0; bank < s->initialized_bus_spaces; bank++) {
        address_space_destroy_free(s->bus_spaces[bank]);
    }
}
static const Property scu_properties[] = {
    DEFINE_PROP_LINK("i2c0", CpScuState, i2c[0], TYPE_DESIGNWARE_I2C, DeviceState *),
    DEFINE_PROP_LINK("i2c1", CpScuState, i2c[1], TYPE_DESIGNWARE_I2C, DeviceState *),
    DEFINE_PROP_LINK("i2c2", CpScuState, i2c[2], TYPE_DESIGNWARE_I2C, DeviceState *),
    DEFINE_PROP_LINK("i2c3", CpScuState, i2c[3], TYPE_DESIGNWARE_I2C, DeviceState *),
    DEFINE_PROP_LINK("i2c4", CpScuState, i2c[4], TYPE_DESIGNWARE_I2C, DeviceState *),
    DEFINE_PROP_LINK("dma0", CpScuState, dma[0], "pl330", DeviceState *),
    DEFINE_PROP_LINK("dma1", CpScuState, dma[1], "pl330", DeviceState *),
    DEFINE_PROP_LINK("dma2", CpScuState, dma[2], "a7c2-cp-pl080", DeviceState *),
    DEFINE_PROP_LINK("dma3", CpScuState, dma[3], "a7c2-cp-pl080", DeviceState *),
    DEFINE_PROP_LINK("watchdog", CpScuState, watchdog, "sony-cp-wdt", DeviceState *),
    DEFINE_PROP_LINK("tpu0", CpScuState, tpu[0], "a7c2-cp-tpu", DeviceState *),
    DEFINE_PROP_LINK("tpu1", CpScuState, tpu[1], "a7c2-cp-tpu", DeviceState *),
    DEFINE_PROP_LINK("tpu2", CpScuState, tpu[2], "a7c2-cp-tpu", DeviceState *),
    DEFINE_PROP_LINK("tpu3", CpScuState, tpu[3], "a7c2-cp-tpu", DeviceState *),
    DEFINE_PROP_LINK("tpu4", CpScuState, tpu[4], "a7c2-cp-tpu", DeviceState *),
    DEFINE_PROP_LINK("tpu5", CpScuState, tpu[5], "a7c2-cp-tpu", DeviceState *),
};
static const VMStateDescription scu_vmstate = {
    .name = TYPE_CP_SCU,
    .unmigratable = true,
};
static void scu_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize = scu_realize;
    dc->vmsd = &scu_vmstate;
    device_class_set_legacy_reset(dc, scu_reset);
    device_class_set_props(dc, scu_properties);
    dc->desc = "Functional CP SCU and gated upstream I2C, no fabricated ACK";
}
/* shortcut: paired boot-device migration is not defined; add it before RAM restore. */
static const TypeInfo scu_type = {
    .name = TYPE_CP_SCU, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(CpScuState), .class_init = scu_class_init,
    .instance_finalize = scu_finalize,
};
static void scu_register_types(void) { type_register_static(&scu_type); }
type_init(scu_register_types)
