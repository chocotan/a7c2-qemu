/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Included by sony-usb-device-platform.inc only in the source candidate. */
#include "hw/i2c/designware_i2c.h"
#include "hw/usb/scu.h"
#include "hw/usb/beets-qemu.h"
#include "system/address-spaces.h"
#include "system/reset.h"
#include "qemu/bswap.h"
#define SONY_BUSPOWER_PROFILE "virtual-a7c2-usb-buspower-v1"
#define SONY_BUSPOWER_I2C_CLOCK (1u << 18)
#define SONY_BUSPOWER_I2C_RESET (1u << 24) /* reset184 = bank5 bit24 */
typedef struct SonyBusPower SonyBusPower;
typedef struct SonyBusPowerRegion {
    SonyBusPower *owner;
    unsigned base;
    MemoryRegion mr;
} SonyBusPowerRegion;
struct SonyBusPower {
    struct cp_scu scu;
    DeviceState *dw, *beets;
    AddressSpace dw_space;
    SonyBusPowerRegion regions[4];
    qemu_irq i2c_irq;
    uint32_t gpio0[20];
    bool raw_irq, reset_tracking, reset_baseline, reset_departed;
};

static bool sony_buspower_active(const SonyBusPower *p)
{
    return (p->scu.clock[5] & SONY_BUSPOWER_I2C_CLOCK) &&
           !(p->scu.reset[5] & SONY_BUSPOWER_I2C_RESET);
}

static void sony_buspower_i2c_irq(void *opaque, int n, int level)
{
    SonyBusPower *p = opaque;
    p->raw_irq = level != 0;
    qemu_set_irq(p->i2c_irq, p->raw_irq && sony_buspower_active(p));
}

static void sony_buspower_master_reset(SonyBusPower *p)
{
    DesignWareI2CState *s = DESIGNWARE_I2C(p->dw);
    /* Pinned DW enter/hold reset state, without descending into the slave bus. */
    i2c_end_transfer(s->bus);
    /* IC_ENABLE first: DATA_CMD reset has a post-write callback. */
    register_reset(&s->regs_info[0x6c / 4]);
    for (unsigned i = 0; i < ARRAY_SIZE(s->regs); i++) {
        register_reset(&s->regs_info[i]);
    }
    fifo8_reset(&s->rx_fifo);
    s->status = DW_I2C_STATUS_IDLE;
    qemu_irq_lower(s->irq);
    p->raw_irq = false;
    qemu_irq_lower(p->i2c_irq);
}

static void sony_buspower_reset(void *opaque)
{
    SonyBusPower *p = opaque;
    /* QEMU device reset clears Beets; this callback restores board-owned pins. */
    if (cp_scu_init(&p->scu, CP_SCU_PROFILE)) abort();
    memset(p->gpio0, 0, sizeof(p->gpio0));
    p->reset_tracking = p->reset_baseline = p->reset_departed = false;
    sony_buspower_master_reset(p);
    qemu_set_irq(qdev_get_gpio_in_named(p->beets, "enable", 0), 0);
    qemu_set_irq(qdev_get_gpio_in_named(p->beets, "reset", 0), 0);
}

static void sony_buspower_gpio17(SonyBusPower *p, uint32_t dir, uint32_t wdata)
{
    qemu_set_irq(qdev_get_gpio_in_named(p->beets, "enable", 0),
                 !!(dir & wdata & (1u << 13)));
}

static void sony_buspower_gpio0(SonyBusPower *p)
{
    if (!(p->gpio0[0] & (1u << 7))) {
        p->reset_tracking = false;
        return;
    }
    bool level = !!(p->gpio0[0x40 / 4] & (1u << 7));
    if (!p->reset_tracking) {
        p->reset_baseline = level;
        p->reset_tracking = true;
        p->reset_departed = false;
        return;
    }
    /* shortcut: pulse width/polarity unmeasured; require a return to the
     * observed output baseline, replace with measured timing before runtime. */
    if (level != p->reset_baseline && !p->reset_departed) {
        p->reset_departed = true;
        qemu_set_irq(qdev_get_gpio_in_named(p->beets, "reset", 0), 1);
    } else if (level == p->reset_baseline && p->reset_departed) {
        p->reset_departed = false;
        qemu_set_irq(qdev_get_gpio_in_named(p->beets, "reset", 0), 0);
    }
}

static MemTxResult sony_buspower_read(void *opaque, hwaddr off, uint64_t *value,
                                      unsigned size, MemTxAttrs attrs)
{
    SonyBusPowerRegion *r = opaque;
    SonyBusPower *p = r->owner;
    uint32_t word = 0;
    MemTxResult rc = MEMTX_ERROR;
    *value = UINT32_MAX;
    if (size != 4 || (off & 3)) goto done;
    if (r->base == 0xf1012000) {
        if (off < 0x100 && sony_buspower_active(p)) {
            rc = address_space_read(&p->dw_space, off, attrs, &word, 4);
            word = le32_to_cpu(word);
        }
    } else if (r->base == 0xf101d000) {
        if (!(off & 0xf) && off <= 0x40) {
            word = p->gpio0[off / 4];
            if (off == 0x10) word = p->gpio0[0x40 / 4] & p->gpio0[0];
            rc = MEMTX_OK;
        }
    } else if (!cp_scu_read(&p->scu, r->base - 0xf1388000u + off, &word)) {
        rc = MEMTX_OK;
    }
    if (rc == MEMTX_OK) *value = word;
done:
    if (rc != MEMTX_OK) qemu_log_mask(LOG_GUEST_ERROR,
        "SONY_BUSPOWER read rejected address=0x%" HWADDR_PRIx " size=%u\n",
        r->base + off, size);
    return rc;
}

static MemTxResult sony_buspower_write(void *opaque, hwaddr off, uint64_t value,
                                       unsigned size, MemTxAttrs attrs)
{
    SonyBusPowerRegion *r = opaque;
    SonyBusPower *p = r->owner;
    MemTxResult rc = MEMTX_ERROR;
    if (size != 4 || (off & 3) || value > UINT32_MAX) goto done;
    if (r->base == 0xf1012000) {
        if (off < 0x100 && sony_buspower_active(p)) {
            uint32_t word = cpu_to_le32(value);
            rc = address_space_write(&p->dw_space, off, attrs, &word, 4);
        }
    } else if (r->base == 0xf101d000) {
        if (off > 0x48 || (off & ~0xf) == 0x10) goto done;
        uint32_t *word = &p->gpio0[(off & ~0xf) / 4];
        switch (off & 0xf) {
        case 0: *word = value; break;
        case 4: *word |= value; break;
        case 8: *word &= ~value; break;
        default: goto done;
        }
        sony_buspower_gpio0(p);
        rc = MEMTX_OK;
    } else {
        uint32_t before = p->scu.reset[5];
        if (cp_scu_write(&p->scu, r->base - 0xf1388000u + off, value)) goto done;
        if ((p->scu.reset[5] & ~before) & SONY_BUSPOWER_I2C_RESET) {
            sony_buspower_master_reset(p);
        }
        qemu_set_irq(p->i2c_irq, p->raw_irq && sony_buspower_active(p));
        rc = MEMTX_OK;
    }
done:
    if (rc != MEMTX_OK) qemu_log_mask(LOG_GUEST_ERROR,
        "SONY_BUSPOWER write rejected address=0x%" HWADDR_PRIx
        " size=%u value=0x%" PRIx64 "\n", r->base + off, size, value);
    return rc;
}

static const MemoryRegionOps sony_buspower_ops = {
    .read_with_attrs = sony_buspower_read,
    .write_with_attrs = sony_buspower_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4 },
    .impl = { .min_access_size = 4, .max_access_size = 4 },
};

static SonyBusPower *sony_buspower_create(MemoryRegion *sysmem, DeviceState *gic)
{
    SonyBusPower *p = g_new0(SonyBusPower, 1);
    if (cp_scu_init(&p->scu, CP_SCU_PROFILE)) abort();
    p->dw = qdev_new(TYPE_DESIGNWARE_I2C);
    sysbus_realize_and_unref(SYS_BUS_DEVICE(p->dw), &error_fatal);
    /* Original DTS GIC_SPI 216 -> QEMU input216 / architectural INTID248. */
    p->i2c_irq = qdev_get_gpio_in(gic, 216);
    sysbus_connect_irq(SYS_BUS_DEVICE(p->dw), 0,
                       qemu_allocate_irq(sony_buspower_i2c_irq, p, 0));
    address_space_init(&p->dw_space,
        sysbus_mmio_get_region(SYS_BUS_DEVICE(p->dw), 0), "sony-buspower-dw-private");
    p->beets = DEVICE(i2c_slave_create_simple(DESIGNWARE_I2C(p->dw)->bus,
                                             TYPE_SONY_BEETS, 0x08));
    const unsigned bases[] = {0xf1012000, 0xf1388050, 0xf1388350, 0xf101d000};
    const unsigned sizes[] = {0x1000, 0x10, 0x10, 0x1000};
    for (unsigned i = 0; i < 4; i++) {
        SonyBusPowerRegion *r = &p->regions[i];
        r->owner = p;
        r->base = bases[i];
        memory_region_init_io(&r->mr, NULL, &sony_buspower_ops, r,
                              "sony-buspower-candidate", sizes[i]);
        memory_region_add_subregion_overlap(sysmem, bases[i], &r->mr, 6);
    }
    sony_buspower_reset(p);
    qemu_register_reset(sony_buspower_reset, p);
    return p;
}
