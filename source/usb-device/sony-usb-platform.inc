
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#define SONY_USB_CLOCK_MASK 0xf000u
#define SONY_USB_RESET_MASK 0xf00u
#define SONY_USB_SRAM_DONE (1u << 18)
#define SONY_USB_PARA_SEL (1u << 20)
#define SONY_USB_BYPASS (1u << 16)
#define SONY_USB_EXT_LOAD_DONE (1u << 17)
#define SONY_USB_FW_BASE 0xf10b8000u
#define SONY_USB_FW_WORDS 4096u
#define SONY_USB_FW_END (SONY_USB_FW_BASE + SONY_USB_FW_WORDS * 4u)
typedef struct SonyUsbPower {
    uint32_t clocks, resets, asserted, cfgr0, u2_cfgr[2], control;
    uint16_t tuning[40];
    unsigned phase; /* 0 reset, 1 reference selected, 2 bypass cleared, 3 CR selected */
    uint16_t firmware[SONY_USB_FW_WORDS];
    unsigned firmware_words;
} SonyUsbPower;

static void sony_usb_power_init(SonyUsbPower *p)
{
    *p = (SonyUsbPower) { .resets = SONY_USB_RESET_MASK };
}

static bool sony_usb_sram_initialized(const SonyUsbPower *p)
{
    return p->clocks == SONY_USB_CLOCK_MASK && !p->resets &&
           p->asserted == SONY_USB_RESET_MASK && p->phase == 3;
}

/* Original cxd-phy.c/crphy_defs.h: stored tuning, no PHY firmware execution. */
static int sony_usb_tuning_index(uint32_t address)
{
    static const uint32_t common[] = {0x003c,0x012c,0x470c,0x4b0c,0x4710,0x4b10,0x4714,0x4b14};
    static const uint32_t lane[] = {0x4008,0x400c,0xc004,0x4028,0xc384,0x4038,0x4034,0xc064};
    if (address < 0xf10a0000u) { return -1; }
    uint32_t offset = address - 0xf10a0000u;
    for (unsigned i=0;i<sizeof common/sizeof *common;i++) {
        if (offset==common[i]) { return (int)i; }
    }
    for (unsigned n=0;n<4;n++) {
        for (unsigned i=0;i<8;i++) {
            if (offset==lane[i]+0x400u*n) { return 8+(int)(n*8+i); }
        }
    }
    return -1;
}

static int sony_usb_power_read(SonyUsbPower *p, uint32_t address,
                               unsigned size, uint32_t *value)
{
    *value = UINT32_MAX;
    int tuning=sony_usb_tuning_index(address);
    if (tuning>=0) {
        if ((size!=2 && size!=4) || (address&3)) { return -EOPNOTSUPP; }
        if (!sony_usb_sram_initialized(p)) { return -EAGAIN; }
        *value=p->tuning[tuning];return 0;
    }
    if (address >= SONY_USB_FW_BASE && address < SONY_USB_FW_END) {
        if ((size != 2 && size != 4) || (address & (size - 1))) { return -EOPNOTSUPP; }
        unsigned index = (address - SONY_USB_FW_BASE) / 4;
        if (!sony_usb_sram_initialized(p) || index >= p->firmware_words) { return -ENODATA; }
        *value = (uint32_t)p->firmware[index] >> ((address & 3) * 8);
        return 0;
    }
    if (size != 4) { return -EOPNOTSUPP; }
    switch (address) {
    case 0xf1388000: *value = p->clocks; break;
    case 0xf1388300: *value = p->resets; break;
    case 0xf1080000: case 0xf1080004:
        *value=p->u2_cfgr[(address-0xf1080000u)/4];break;
    case 0xf1080010: *value=p->control;break;
    case 0xf1080020:
        *value = p->cfgr0 | (sony_usb_sram_initialized(p) ? SONY_USB_SRAM_DONE : 0);
        break;
    /* Original cxd clock registration reads these div/mux/gate reset values.
     * They are explicit functional reset state, not additional working clocks. */
    case 0xf1388020: case 0xf1388030: case 0xf1388040: case 0xf1388050:
    case 0xf1388080: case 0xf138810c: case 0xf1388110: case 0xf1388114:
    case 0xf1388118: case 0xf138811c: case 0xf1388210: case 0xf1388220:
    case 0xf1388230: *value = 0; break;
    default: return -EOPNOTSUPP;
    }
    return 0;
}

static int sony_usb_power_write(SonyUsbPower *p, uint32_t address,
                                unsigned size, uint32_t value)
{
    int tuning=sony_usb_tuning_index(address);
    if (tuning>=0) {
        if ((size!=2 && size!=4) || (address&3) || value>UINT16_MAX) { return -EOPNOTSUPP; }
        if (!sony_usb_sram_initialized(p) || !(p->cfgr0 & SONY_USB_PARA_SEL) || (p->cfgr0 & SONY_USB_EXT_LOAD_DONE)) { return -EAGAIN; }
        p->tuning[tuning]=(uint16_t)value;return 0;
    }
    if (size != 4) { return -EOPNOTSUPP; }
    if (address == 0xf1080000u || address == 0xf1080004u || address == 0xf1080010u) {
        uint32_t mask=address==0xf1080000u?0x0e000700u:address==0xf1080004u?0x7fu:0xcu;
        if (value & ~mask) { return -EOPNOTSUPP; }
        if (p->clocks!=SONY_USB_CLOCK_MASK || (p->resets & 0x200u)) { return -EAGAIN; }
        if (address==0xf1080010u) { p->control=value; }
        else { p->u2_cfgr[(address-0xf1080000u)/4]=value; }
        return 0;
    }
    if (address >= SONY_USB_FW_BASE && address < SONY_USB_FW_END) {
        if ((address & 3) || value > UINT16_MAX) { return -EOPNOTSUPP; }
        if (!sony_usb_sram_initialized(p) || !(p->cfgr0 & SONY_USB_PARA_SEL)) { return -EAGAIN; }
        if ((p->cfgr0 & SONY_USB_EXT_LOAD_DONE) ||
            address != SONY_USB_FW_BASE + p->firmware_words * 4) { return -EINVAL; }
        p->firmware[p->firmware_words++] = value;
        return 0;
    }
    if (address == 0xf1388004 || address == 0xf1388008) {
        if (value & ~SONY_USB_CLOCK_MASK) { return -EOPNOTSUPP; }
        if (address == 0xf1388004) { p->clocks |= value; }
        else { p->clocks &= ~value; }
        if (p->clocks != SONY_USB_CLOCK_MASK) {
            p->phase = 0; p->firmware_words = 0; p->cfgr0 &= ~SONY_USB_EXT_LOAD_DONE;
        }
    } else if (address == 0xf1388304 || address == 0xf1388308) {
        if (value & ~SONY_USB_RESET_MASK) { return -EOPNOTSUPP; }
        if (address == 0xf1388304 && value) {
            if (!p->resets) { p->asserted = 0; }
            p->resets |= value; p->asserted |= value; p->phase = 0;
            p->firmware_words = 0; p->cfgr0 &= ~SONY_USB_EXT_LOAD_DONE;
            if (value & 0xc00) { p->cfgr0 = 0; }
        } else if (address == 0xf1388308) { p->resets &= ~value; }
    } else if (address == 0xf1080020) {
        const uint32_t controls = 1u | SONY_USB_BYPASS | (1u << 17) |
                                  (1u << 19) | SONY_USB_PARA_SEL;
        if (value & ~(controls | SONY_USB_SRAM_DONE)) { return -EOPNOTSUPP; }
        if ((value & SONY_USB_EXT_LOAD_DONE) && !(p->cfgr0 & SONY_USB_EXT_LOAD_DONE) &&
            (!sony_usb_sram_initialized(p) || p->firmware_words != SONY_USB_FW_WORDS)) {
            return -EAGAIN;
        }
        p->cfgr0 = value & controls; /* bit18 is hardware-owned; RMW cannot set it. */
        if (p->clocks != SONY_USB_CLOCK_MASK ||
            p->asserted != SONY_USB_RESET_MASK || (value & (1u | SONY_USB_BYPASS))) {
            p->phase = 0;
        } else if (p->resets == 0xd00) { /* Only APB released during setup. */
            if (p->phase == 0 && !(value & SONY_USB_PARA_SEL)) { p->phase = 1; }
            else if (p->phase == 1 && !(value & SONY_USB_PARA_SEL)) { p->phase = 2; }
            else if (p->phase == 2 && (value & SONY_USB_PARA_SEL)) { p->phase = 3; }
            else { p->phase = 0; }
        } else if (p->phase != 3 || p->resets || !(value & SONY_USB_PARA_SEL)) {
            p->phase = 0;
        }
        if (!p->phase) { p->firmware_words = 0; p->cfgr0 &= ~SONY_USB_EXT_LOAD_DONE; }
    } else { return -EOPNOTSUPP; }
    return 0;
}

/* Functional Sony USB clock/reset/PHY/GPIO; no UDC ready or AP mode injection. */
#include "hw/core/irq.h"
#define SONY_USB_VBUS_INPUT (1u << 12)
#define SONY_USB_C1_INPUT (1u << 18)
typedef struct SonyUsbPlatform {
    MemoryRegion gpio, gpioint, clock, reset, phy, cr;
    uint32_t gpio_regs[20], int_regs[16];
    SonyUsbPower power;
    bool present, c1_input;
    uint64_t generation, reads;
    qemu_irq vbus_irq, controller_vbus;
} SonyUsbPlatform;

static MemTxResult sony_usb_bad(hwaddr a, unsigned n, bool write)
{
    qemu_log_mask(LOG_GUEST_ERROR,
        "SONY_USB_PLATFORM unsupported %s address=0x%" HWADDR_PRIx " size=%u\n",
        write ? "write" : "read", a, n);
    return MEMTX_ERROR;
}

static uint32_t sony_usb_gpio_rdata(const SonyUsbPlatform *p)
{
    return (p->gpio_regs[0x10 / 4] & ~(SONY_USB_VBUS_INPUT | SONY_USB_C1_INPUT)) |
           (p->present ? SONY_USB_VBUS_INPUT : 0) |
           (p->c1_input ? SONY_USB_C1_INPUT : 0);
}

static MemTxResult sony_usb_gpio_read(void *opaque, hwaddr off, uint64_t *v,
                                     unsigned n, MemTxAttrs attrs)
{
    SonyUsbPlatform *p = opaque;
    if (n != 4 || (off & 3) || (off & 0xf) == 0xc || off > 0x48) {
        *v = 0; return sony_usb_bad(0xf102e000 + off, n, false);
    }
    if (off == 0x10) {
        *v = sony_usb_gpio_rdata(p);
        if (p->reads++ < 32) {
            fprintf(stderr, "SONY_USB_VBUS_GPIO_READ generation=%" PRIu64
                    " value=0x%08x (consumer read, not event proof)\n",
                    p->generation, (unsigned)*v);
        }
    } else { *v = p->gpio_regs[(off & ~0xf) / 4]; }
    return MEMTX_OK;
}

static MemTxResult sony_usb_gpio_write(void *opaque, hwaddr off, uint64_t v,
                                      unsigned n, MemTxAttrs attrs)
{
    SonyUsbPlatform *p = opaque;
    if (n != 4 || (off & 3) || off > 0x48) {
        return sony_usb_bad(0xf102e000 + off, n, true);
    }
    if ((off & ~0xf) == 0x10) {
        /* Project helper external pad only; physical kernel RDATA stays read-only. */
        if (off != 0x10 || ((v ^ sony_usb_gpio_rdata(p)) & ~(uint64_t)SONY_USB_C1_INPUT)) {
            return sony_usb_bad(0xf102e000 + off, n, true);
        }
        p->c1_input = (v & SONY_USB_C1_INPUT) != 0;
        return MEMTX_OK;
    }
    uint32_t *r = &p->gpio_regs[(off & ~0xf) / 4];
    switch (off & 0xf) {
    case 0: *r = v; break;
    case 4: *r |= v; break;
    case 8: *r &= ~v; break;
    default: return sony_usb_bad(0xf102e000 + off, n, true);
    }
    return MEMTX_OK;
}

static MemTxResult sony_usb_int_read(void *opaque, hwaddr off, uint64_t *v,
                                    unsigned n, MemTxAttrs attrs)
{
    SonyUsbPlatform *p = opaque;
    *v = 0;
    if (n != 4 || (off & 0xf) || off > 0x30) {
        return sony_usb_bad(0xf1030000 + off, n, false);
    }
    *v = p->int_regs[off / 4]; return MEMTX_OK;
}

static MemTxResult sony_usb_int_write(void *opaque, hwaddr off, uint64_t v,
                                     unsigned n, MemTxAttrs attrs)
{
    SonyUsbPlatform *p = opaque;
    if (n != 4 || (off & 3) || off > 0x38) {
        return sony_usb_bad(0xf1030000 + off, n, true);
    }
    uint32_t *r = &p->int_regs[(off & ~0xf) / 4];
    switch (off & 0xf) {
    case 0: *r = v; break;
    case 4: *r |= v; break;
    case 8: *r &= ~v; break;
    default: return sony_usb_bad(0xf1030000 + off, n, true);
    }
    return MEMTX_OK;
}

#define SONY_USB_POWER_CALLBACKS(label, base) \
static MemTxResult sony_usb_##label##_read(void *opaque, hwaddr off, uint64_t *v, \
                                         unsigned n, MemTxAttrs attrs) \
{ \
    SonyUsbPlatform *p = opaque; \
    uint32_t value; \
    int rc = sony_usb_power_read(&p->power, base + off, n, &value); \
    *v = value; \
    fprintf(stderr, "SONY_USB_POWER_READ address=0x%" HWADDR_PRIx \
            " size=%u value=0x%x rc=%d\n", (hwaddr)(base + off), n, value, rc); \
    return rc ? sony_usb_bad(base + off, n, false) : MEMTX_OK; \
} \
static MemTxResult sony_usb_##label##_write(void *opaque, hwaddr off, uint64_t v, \
                                          unsigned n, MemTxAttrs attrs) \
{ \
    SonyUsbPlatform *p = opaque; \
    bool before = sony_usb_sram_initialized(&p->power); \
    int rc = sony_usb_power_write(&p->power, base + off, n, v); \
    if (rc) { \
        fprintf(stderr, "SONY_USB_POWER_REJECT address=0x%" HWADDR_PRIx \
                " size=%u value=0x%x rc=%d\n", (hwaddr)(base + off), n, (unsigned)v, rc); \
        return sony_usb_bad(base + off, n, true); \
    } \
    fprintf(stderr, "SONY_USB_POWER_WRITE address=0x%" HWADDR_PRIx \
            " value=0x%x clocks=0x%x resets=0x%x phase=%u SRAM_INIT_DONE=%d firmware_words=%u handoff=%d\n", \
            (hwaddr)(base + off), (unsigned)v, p->power.clocks, \
            p->power.resets, p->power.phase, sony_usb_sram_initialized(&p->power), \
            p->power.firmware_words, !!(p->power.cfgr0 & SONY_USB_EXT_LOAD_DONE)); \
    if (before != sony_usb_sram_initialized(&p->power)) { \
        fprintf(stderr, "SONY_USB_PHY_SRAM_INIT_CHANGED initialized=%d; UDC unverified\n", \
                sony_usb_sram_initialized(&p->power)); \
    } \
    return MEMTX_OK; \
}
SONY_USB_POWER_CALLBACKS(clock, 0xf1388000u)
SONY_USB_POWER_CALLBACKS(reset, 0xf1388300u)
SONY_USB_POWER_CALLBACKS(phy, 0xf1080000u)
SONY_USB_POWER_CALLBACKS(cr, 0xf10a0000u)
#undef SONY_USB_POWER_CALLBACKS

#define SONY_USB_OPS(label) \
static const MemoryRegionOps sony_usb_##label##_ops = { \
    .read_with_attrs = sony_usb_##label##_read, \
    .write_with_attrs = sony_usb_##label##_write, \
    .endianness = DEVICE_LITTLE_ENDIAN, \
    .valid.min_access_size = 4, .valid.max_access_size = 4, \
    .impl.min_access_size = 4, .impl.max_access_size = 4, \
}
SONY_USB_OPS(gpio);
SONY_USB_OPS(int);
SONY_USB_OPS(clock);
SONY_USB_OPS(reset);
SONY_USB_OPS(phy);
#undef SONY_USB_OPS
static const MemoryRegionOps sony_usb_cr_ops = {
    .read_with_attrs = sony_usb_cr_read,
    .write_with_attrs = sony_usb_cr_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 2, .valid.max_access_size = 4, .valid.unaligned = false,
    .impl.min_access_size = 2, .impl.max_access_size = 4, .impl.unaligned = false,
};

static void sony_usb_vbus_request(void *opaque, int n, int level)
{
    SonyUsbPlatform *p = opaque;
    bool present = level != 0;
    if (present == p->present) { return; }
    p->present = present; p->generation++; p->reads = 0;
    qemu_set_irq(p->controller_vbus, present);
    /* GPIO17.12 is GIC INTID100 / SPI68; both-edge config lives at GPIO19. */
    if ((p->int_regs[(present ? 0x20 : 0x30) / 4] & (1u << 12)) &&
        !(p->int_regs[0x10 / 4] & (1u << 12))) {
        qemu_irq_pulse(p->vbus_irq);
    }
    fprintf(stderr, "SONY_USB_VBUS_APPLIED generation=%" PRIu64
            " present=%d gpio=17.12; kernel event unverified\n", p->generation, present);
}

static void sony_usb_platform_create(MemoryRegion *sysmem, DeviceState *usb,
                                     DeviceState *gic)
{
    SonyUsbPlatform *p = g_new0(SonyUsbPlatform, 1);
    sony_usb_power_init(&p->power);
    p->vbus_irq = qdev_get_gpio_in(gic, 68);
    p->controller_vbus = qdev_get_gpio_in_named(usb, "vbus", 0);
    qdev_connect_gpio_out_named(usb, "vbus-request", 0,
                               qemu_allocate_irq(sony_usb_vbus_request, p, 0));
#define SONY_USB_MAP(field, ops, addr, size) \
    memory_region_init_io(&p->field, NULL, &sony_usb_##ops##_ops, p, \
                         "sony-usb-" #field, size); \
    memory_region_add_subregion_overlap(sysmem, addr, &p->field, 5)
    SONY_USB_MAP(gpio, gpio, 0xf102e000, 0x1000);
    SONY_USB_MAP(gpioint, int, 0xf1030000, 0x1000);
    SONY_USB_MAP(clock, clock, 0xf1388000, 0x240);
    SONY_USB_MAP(reset, reset, 0xf1388300, 0x80);
    SONY_USB_MAP(phy, phy, 0xf1080000, 0x1000);
    SONY_USB_MAP(cr, cr, 0xf10a0000, 0x1c000);
#undef SONY_USB_MAP
}
