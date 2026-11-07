#!/usr/bin/env python3
"""Original Sony USB driver integration on an isolated functional device board.

The controller model supplies no Sony descriptors. This profile adds the real
platform resources, Sony extcon and a functional GPIO VBUS source. PHY SRAM init
and the CR download/handoff are finite clock/reset/configuration models. The
model stores guest firmware words; it does not emulate the PHY instruction set.
SRAM init completion never implies UDC or descriptor readiness. See ../2026-11-06-complete-boot-flow/usb-original-driver.md.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-functional-sony-usb-device-v1'
CONTROLLER = 'sony-device'
MODEL_ENV = 'QEMU_SONY_USB_DEVICE'
PERSISTENT = runpy.run_path(str(HERE / 'persistent-boot.py'))
COLD = PERSISTENT['COLD']
U32 = lambda *v: struct.pack('>' + 'I' * len(v), *v)
REG = lambda address, size: struct.pack('>QQ', address, size)

# Shared by the QEMU callbacks and standalone host C tests. Original source order:
# dwc3-of-cxd.c:396-471; cxd-phy.c:298-309,361-375,399-416; cxd-clk-gate.c:46-98.
PHY_MODEL_C = r'''
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
    uint32_t clocks, resets, asserted, cfgr0;
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

static int sony_usb_power_read(SonyUsbPower *p, uint32_t address,
                               unsigned size, uint32_t *value)
{
    *value = UINT32_MAX;
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
    if (size != 4) { return -EOPNOTSUPP; }
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
'''

# Included in an independent virt.c, never installed into another owner's source.
PLATFORM_C = PHY_MODEL_C + r'''
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
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def add_nodes(fdt, buffer, mode='full', controller=CONTROLLER):
    """Compatible add_nodes API for usb-platform.py's DTB adapter call site."""
    if controller != CONTROLLER or mode != 'full':
        raise ValueError('Sony device resources require full/sony-device explicitly')
    root = fdt.fdt_path_offset(buffer, b'/')

    def prop(node, key):
        length = ctypes.c_int()
        ptr = fdt.fdt_getprop(buffer, node, key, ctypes.byref(length))
        return ctypes.string_at(ptr, length.value) if ptr and length.value >= 0 else None

    if prop(root, b'compatible') != b'linux,dummy-virt\0':
        raise ValueError('Expected explicit generic-virt board')
    if any(prop(root, key) != U32(2) for key in (b'#address-cells', b'#size-cells')):
        raise ValueError('Expected two-cell root resource addresses')
    gic = fdt.fdt_path_offset(buffer, b'/intc@8000000')
    if gic < 0 or not prop(gic, b'phandle'):
        raise ValueError('Missing explicit GIC phandle')
    # Reserve a bounded phandle range; reject collisions instead of guessing.
    handles = tuple(range(0x7f10, 0x7f14))
    for handle in handles:
        if fdt.fdt_node_offset_by_phandle(buffer, handle) >= 0:
            raise ValueError('USB profile phandle collision')
    paths = ('/sony-usb-clock', '/sony-usb-scu@f1388000', '/fusb_otg',
             '/fusb_dwc3regs@f10c0000', '/soc/usbs@f1080000')
    required = (*paths, paths[1] + '/rst@300', paths[4] + '/usb@f10c0000',
                '/sony-usb@f1080000')
    if any(fdt.fdt_path_offset(buffer, p.encode()) >= 0 for p in required):
        raise ValueError('USB resource node already exists')
    soc_values = {'compatible': b'simple-bus\0', '#address-cells': U32(2),
                  '#size-cells': U32(2), 'ranges': b''}
    soc = fdt.fdt_path_offset(buffer, b'/soc')
    if soc >= 0:
        actual_path = ctypes.create_string_buffer(256)
        if fdt.fdt_get_path(buffer, soc, actual_path, len(actual_path)) or actual_path.value != b'/soc':
            raise ValueError('Expected exact /soc bus path')
        count, cursor = 0, fdt.fdt_first_property_offset(buffer, soc)
        while cursor >= 0:
            count += 1
            cursor = fdt.fdt_next_property_offset(buffer, cursor)
        if (cursor != -1 or count != len(soc_values) or
                any(prop(soc, key.encode()) != value for key, value in soc_values.items()) or
                fdt.fdt_first_subnode(buffer, soc) != -1):
            raise ValueError('Existing /soc must be an empty exact two-cell simple-bus')
    elif soc != -1:
        raise ValueError('Cannot inspect /soc bus')

    def node(path, values):
        parent, _, name = path.rpartition('/')
        parent_node = fdt.fdt_path_offset(buffer, (parent or '/').encode())
        result = fdt.fdt_add_subnode(buffer, parent_node, name.encode())
        if result < 0:
            raise ValueError('Cannot add USB node ' + path + ': ' + str(result))
        for key, value in values.items():
            if fdt.fdt_setprop(buffer, result, key.encode(), value, len(value)) < 0:
                raise ValueError('Cannot set USB property ' + path + '/' + key)
        return result

    node(paths[0], {'compatible': b'cxd,900xx-clock\0', '#clock-cells': U32(1),
                    'reg': REG(0, 0x300), 'syscon': U32(handles[1]),
                    'phandle': U32(handles[0])})
    node(paths[1], {'compatible': b'cxd900xx,scu\0syscon\0simple-mfd\0',
                    '#address-cells': U32(2), '#size-cells': U32(2), 'ranges': b'',
                    'reg': REG(0xf1388000, 0x2000), 'phandle': U32(handles[1])})
    node(paths[1] + '/rst@300', {'compatible': b'cxd900xx,reset\0',
         'reg': REG(0x300, 0x80), '#reset-cells': U32(1),
         'syscon': U32(handles[1]), 'phandle': U32(handles[2])})
    node(paths[2], {'compatible': b'linux,extcon-fusb_otg\0',
                    'phandle': U32(handles[3]), 'status': b'okay\0'})
    node(paths[3], {'compatible': b'snps,fusb_dwc3regs\0',
                    'reg': REG(0xf10c0000, 0x11000), 'status': b'okay\0'})
    if soc < 0:
        node('/soc', soc_values)
    # OF uses translated reg + node name, with the real parent device hierarchy.
    node(paths[4], {'compatible': b'cxdchip,dwc3\0',
         'reg': REG(0xf1080000, 0x1000) + REG(0xf10a0000, 0x1c000),
         'reg-names': b'ss_usb\0phy_cr\0', '#address-cells': U32(2),
         '#size-cells': U32(2), 'ranges': b'',
         'clocks': U32(handles[0], 19, handles[0], 18, handles[0], 17, handles[0], 16),
         'clock-names': b'usb_sus_clk\0usb_axi_clk\0usb_apb_clk\0usb_refclk\0',
         'resets': U32(handles[2], 11, handles[2], 10, handles[2], 9, handles[2], 8),
         'reset-names': b'rst_u31\0rst_u2\0rst_apb\0rst_axi\0', 'status': b'okay\0'})
    # Re-read the GIC offset after every tree insertion: libfdt offsets can move.
    gic = fdt.fdt_path_offset(buffer, b'/intc@8000000')
    node(paths[4] + '/usb@f10c0000', {'compatible': b'snps,dwc3\0',
         'reg': REG(0xf10c0000, 0x11000), 'interrupt-parent': prop(gic, b'phandle'),
         'interrupts': U32(0, 184, 4), 'extcon': U32(handles[3]),
         'dr_mode': b'otg\0', 'maximum-speed': b'high-speed\0',
         'phy_type': b'utmi\0', 'status': b'okay\0'})


def adapt_script(text, *, observe_generation=False):
    """Adapt a copied full-system launcher; preserve the off/host implementation."""
    if type(observe_generation) is not bool:
        raise ValueError('USB generation observation requires a typed boolean')
    option = '  display_args+=(-global sony-dwc3-gadget.generation-observe=on)\n'
    marker = '# FULLSYSTEM_SONY_USB_DEVICE_PROFILE'
    if marker in text:
        if text.count(option) != int(observe_generation):
            raise ValueError('Prepared USB generation selection differs')
        return text
    anchor = 'runpy.run_path(sys.argv[7])["add_nodes"](fdt,buffer,sys.argv[6],sys.argv[8])'
    if text.count(anchor) != 1:
        raise ValueError('Unsupported USB DTB call site')
    replacement = (marker + '\n'
        'usb_adapter = str(Path(sys.argv[7]).with_name("usb-device-profile.py")) if sys.argv[8] == "sony-device" else sys.argv[7]\n'
        'runpy.run_path(usb_adapter)["add_nodes"](fdt,buffer,sys.argv[6],sys.argv[8])')
    # Path is already imported by the prepared full-system DTB builder.
    text = text.replace(anchor, replacement, 1)
    anchor = 'bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"'
    if text.count(anchor) != 1:
        raise ValueError('Unsupported USB sandbox call site')
    code = '''if [[ "${QEMU_FULL_USB_CONTROLLER:-off}" == sony-device ]]; then
  [[ "${QEMU_FULL_USB_PLATFORM:-off}" == full && "${QEMU_FULL_USB_INIT:-skipped}" == original ]] || { echo 'sony-device requires full/original' >&2; exit 2; }
  timer_environment+=(--setenv QEMU_SONY_USB_DEVICE 1)
  for usb_binding in QEMU_SONY_USB_RUN_ID QEMU_SONY_USB_LEASE QEMU_SONY_USB_QMP_HOST_PATH QEMU_SONY_USB_BACKEND_SOCKET; do
    [[ -n "${!usb_binding:-}" ]] || { echo "Missing $usb_binding" >&2; exit 2; }
    timer_environment+=(--setenv "$usb_binding" "${!usb_binding}")
  done
fi
'''
    if observe_generation:
        code = code.replace('  timer_environment+=(--setenv QEMU_SONY_USB_DEVICE 1)\n',
                            '  timer_environment+=(--setenv QEMU_SONY_USB_DEVICE 1)\n' + option, 1)
    return text.replace(anchor, code + anchor, 1)


def patch_source(source, scratch_root):
    """Generate only a board/provider delta in an explicitly independent copy.

    Install usb-gadget-model.py into that copy first. Production and synthetic
    boards are accepted; synthetic guards stay inactive on this normal profile.
    """
    source, scratch_root = Path(source).resolve(), Path(scratch_root).resolve()
    if (scratch_root == Path('/') or scratch_root.is_relative_to(HERE) or
            not source.is_relative_to(scratch_root) or source == scratch_root):
        raise ValueError('Expected independent source below explicit scratch root')
    board = source / 'hw/arm/virt.c'
    provider = source / 'hw/arm/sony-usb-device-platform.inc'
    for target in (board, provider):
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError('Refuse escaped or symlinked source targets')
    text = board.read_text()
    model_files = {}
    for name in ('sony-dwc3.c', 'sony-dwc3.h', 'sony-dwc3-bridge.c', 'sony-dwc3-bridge.h'):
        target = source / 'hw/usb' / name
        expected = (HERE / 'usb-gadget' / name).read_bytes()
        if name == 'sony-dwc3.c':
            expected = b'#define SONY_DWC3_QEMU 1\n' + expected
        if (target.is_symlink() or not target.resolve().is_relative_to(source) or
                not target.is_file() or target.read_bytes() != expected):
            raise ValueError('Install matching independent bridge/core snapshot first: ' + name)
        model_files['hw/usb/' + name] = sha(expected)
    if 'SONY_USB_DEVICE_PROFILE' in text or provider.exists():
        raise ValueError('Device profile already applied; use a fresh copy')
    before = sha(board.read_bytes())
    include = '#include "hw/arm/virt.h"'
    anchor = '    create_msi_controller(vms);'
    if text.count(include) != 1 or text.count(anchor) != 1:
        raise ValueError('Unsupported virt board insertion points')
    fragment = runpy.run_path(str(HERE / 'usb-gadget-model.py'))['BOARD_FRAGMENT']
    fragment = fragment.replace('/* Hold usb for sony_dwc3_qemu_core(usb);',
        'sony_usb_platform_create(sysmem, usb, vms->gic);\n/* Hold usb for sony_dwc3_qemu_core(usb);')
    text = text.replace(include, include + '\n#include "qemu/log.h"\n#include "hw/arm/sony-usb-device-platform.inc"', 1)
    code = ('    /* SONY_USB_DEVICE_PROFILE: explicit functional board only. */\n'
            '    if (g_getenv("QEMU_SONY_USB_DEVICE")) {\n'
            '        if (g_getenv("QEMU_SONY_USB_DWC3") || g_getenv("QEMU_SONY_DWC3_CORE_TEST")) {\n'
            '            error_report("Conflicting host/test/device USB controllers");\n'
            '            exit(EXIT_FAILURE);\n'
            '        }\n' + fragment + '\n    }\n')
    provider.write_text(PLATFORM_C)
    board.write_text(text.replace(anchor, code + anchor, 1))
    receipt = dict(schema='a7c2.usb-device-source.v1', profile=PROFILE,
        files={'hw/arm/virt.c': dict(before=before, after=sha(board.read_bytes())),
               'hw/arm/sony-usb-device-platform.inc': dict(before=None, after=sha(provider.read_bytes()))},
        model_source_sha256=model_files,
        controller='sony-dwc3-gadget', mmio='0xf10c0000', resource_bytes=0x11000,
        model_bytes=0x10000, gic_spi=184, vbus_gpio='17.12', vbus_spi=68,
        external_pad_model='project-helper-c1-rdata-rmw-v1', c1_gpio='17.18',
        c1_irq_delivered=False, c1_usb_reset_preserved=True,
        clocks='original cxd provider USB gates 19/18/17/16; functional gate registers',
        phy_sram_supported=False, phy_sram_init_model='clock-reset-config-sequence-v1',
        phy_cr_download_model='guest-u16-in-u32-4096-sequential-v1',
        phy_firmware_execution_verified=False, vbus_kernel_event_delivered=False,
        guest_descriptor_ready=False, export_allowed=False)
    (source.parent / 'usb-device-source-delta.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def launch_environment(run_dir, lease):
    """Return the four explicit bridge bindings for prepare_launch's owned run."""
    run_dir = Path(run_dir).absolute()
    if run_dir.is_symlink() or not run_dir.is_dir() or run_dir.resolve() != run_dir:
        raise ValueError('Expected an existing plain absolute run directory')
    info = run_dir.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise ValueError('Run directory must be owned and not group/world writable')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', run_dir.name):
        raise ValueError('Invalid bridge run id')
    if not isinstance(lease, str) or not 32 <= len(lease) <= 128 or any(not 0x21 <= ord(c) <= 0x7e for c in lease):
        raise ValueError('Expected explicit per-run ASCII lease (32..128 chars)')
    for name in ('usb-endpoint.sock', 'qmp.sock'):
        if (run_dir / name).exists() or (run_dir / name).is_symlink():
            raise ValueError('Run socket existed before this launch')
    return dict(QEMU_FULL_USB_INIT='original', QEMU_FULL_USB_PLATFORM='full',
        QEMU_FULL_USB_CONTROLLER=CONTROLLER, QEMU_SONY_USB_RUN_ID=run_dir.name,
        QEMU_SONY_USB_LEASE=lease, QEMU_SONY_USB_QMP_HOST_PATH=str(run_dir / 'qmp.sock'),
        QEMU_SONY_USB_BACKEND_SOCKET='/out/usb-endpoint.sock')


def production_inputs(launch):
    """Require the persistent + Sony-device combination, bound to its real binary."""
    binary = COLD['plain'](launch['qemu_binary'])
    manifest = COLD['plain'](binary.parent.parent / 'qemu-result.json')
    for path in (binary, manifest):
        rows = [r for r in launch['template_inputs'] if r['path'] == str(path)]
        if len(rows) != 1 or rows[0]['role'] != 'production-qemu-input':
            raise ValueError('Missing persistent production QEMU binding: ' + str(path))
    production = json.loads(manifest.read_text())
    if (production.get('status') != 'compiled' or
            production.get('board_profile') != PERSISTENT['PROFILE'] or
            production.get('test_fixture_only') is not False or
            production.get('usb_device_profile') != PROFILE or
            not re.fullmatch(r'[0-9a-f]{64}', production.get('board_source_sha256', '')) or
            production.get('binary') != str(binary) or
            production.get('qemu_binary_sha256') != launch['qemu_sha256'] or
            COLD['digest'](binary) != launch['qemu_sha256'] or
            launch['env'].get('QEMU_SYSTEM_DIR') != str(binary.parent)):
        raise ValueError('Expected matching production persistent + USB device QEMU combination')
    expected = {}
    for name in ('sony-dwc3.c', 'sony-dwc3.h', 'sony-dwc3-bridge.c', 'sony-dwc3-bridge.h'):
        data = (HERE / 'usb-gadget' / name).read_bytes()
        if name == 'sony-dwc3.c':
            data = b'#define SONY_DWC3_QEMU 1\n' + data
        expected['hw/usb/' + name] = sha(data)
    expected['hw/arm/sony-usb-device-platform.inc'] = sha(PLATFORM_C.encode())
    if production.get('usb_source_sha256') != expected:
        raise ValueError('Production USB model/source identity differs')
    names = ('dwc3-model-delta.json', 'usb-device-source-delta.json',
             'persistent-flash-model-delta.json', 'persistent-usb-source-delta.json')
    deltas = production.get('source_deltas_sha256', {})
    if (not isinstance(deltas, dict) or set(deltas) != set(names) or
            production.get('all_source_delta_sha256') != deltas[names[-1]] or
            production.get('source_delta_sha256') != deltas[names[-2]]):
        raise ValueError('Missing persistent + USB source combination metadata')
    bindings = []
    for name in names:
        row = COLD['binding'](manifest.parent / name, 'usb-qemu-source-contract')
        if row['sha256'] != deltas[name]:
            raise ValueError('Production source delta drift: ' + name)
        bindings.append(row)
    combined = json.loads(Path(bindings[-1]['path']).read_text())
    if (combined.get('schema') != 'a7c2.persistent-usb-source.v1' or
            combined.get('provider_sha256') != expected['hw/arm/sony-usb-device-platform.inc'] or
            combined.get('model_source_sha256') != {k: v for k, v in expected.items() if k.startswith('hw/usb/')} or
            combined.get('files', {}).get('hw/arm/virt.c', {}).get('after') != production.get('board_source_sha256')):
        raise ValueError('Persistent + USB combined source identity differs')
    return bindings


def prepare_launch(launch, *, lease, observe_generation=False):
    """Adapt a current, unstarted persistent launch; rebind only regenerated files.

    The caller keeps the disk lease/normal QMP exit owner and the private UI run
    context. This prepares resources only; the USB lease stays in memory.
    """
    if type(observe_generation) is not bool:
        raise ValueError('USB generation observation requires a typed boolean')
    if launch.get('guest_started') is not False or launch.get('profile') != PERSISTENT['PROFILE']:
        raise ValueError('Only an unstarted prepared persistent launch can select the device profile')
    PERSISTENT['firmware_contract'](launch)
    kernel = PERSISTENT['current_kernel_binding'](launch['actual_kernel'])
    templates, inputs = launch['template_inputs'], launch['launch_inputs']
    COLD['recheck'](templates + inputs)
    if kernel not in templates:
        raise ValueError('Missing current-disk kernel template binding')
    original = COLD['plain'](launch['script'])
    original_binding = COLD['binding'](original, 'prepared-launch-script')
    if original_binding['sha256'] != launch['script_sha256']:
        raise ValueError('Prepared launch script drift')
    if launch['command'].count(str(original)) != 1:
        raise ValueError('Prepared launch command must select its bound script exactly once')
    run_dir = Path(launch['qmp_socket']).parent
    if (launch['qmp_socket'] != str(run_dir / 'qmp.sock') or
            launch.get('qmp_parent') != str(run_dir) or
            launch['env'].get('QEMU_OUTPUT_DIR') != str(run_dir)):
        raise ValueError('Prepared run/QMP identity differs')
    env = {**launch['env'], **launch_environment(run_dir, lease)}
    if observe_generation and 'guest_errors' not in env.get('QEMU_TRACE_FLAGS', 'in_asm,cpu_reset,guest_errors,unimp').split(','):
        raise ValueError('USB generation observation requires the existing guest_errors log sink')
    regenerated = {}
    for key in ('dtb', 'cmdline_file'):
        path = str(COLD['plain'](launch[key]))
        rows = [r for r in inputs if r['path'] == path]
        if path in regenerated or len(rows) != 1 or Path(path).parent != run_dir:
            raise ValueError('Missing or ambiguous prepared USB asset binding: ' + key)
        regenerated[path] = rows[0]
    dtb_before, cmdline_before = (regenerated[launch[key]] for key in ('dtb', 'cmdline_file'))
    if dtb_before['sha256'] != launch['dtb_sha256']:
        raise ValueError('Prepared DTB SHA drift')
    cmdline_bytes = Path(launch['cmdline_file']).read_bytes()
    if (sha(cmdline_bytes) != cmdline_before['sha256'] or
            cmdline_bytes.decode('ascii').strip() != launch['cmdline']):
        raise ValueError('Prepared command line drift')
    source_bindings = production_inputs(launch)
    if observe_generation:
        release_api = HERE / 'usb-generation-build.py'
        release = runpy.run_path(str(release_api))['source_contract']()
        production = json.loads((Path(launch['qemu_binary']).parent.parent / 'qemu-result.json').read_text())
        if production.get('generation_observer_release') != release:
            raise ValueError('USB generation observation requires its reviewed binary release')
        names = ('usb-generation-build.py', 'usb-generation-source-contract.json', 'persistent-flash/build.py',
                 *release['persistent_model_sha256'],
                 *(name for name in release['build_public_sha256'] if name != 'usb-device-profile.py'))
        seen = {row['path'] for row in templates + inputs + source_bindings}
        for name in names:
            path = HERE / name
            if str(path) not in seen:
                source_bindings.append(COLD['binding'](path, 'usb-generation-source'))
                seen.add(str(path))
    source_bindings.append(COLD['binding'](Path(__file__), 'usb-device-profile-source'))
    script = original.with_name('qemu-kernel-usb-device.sh')
    text = adapt_script(original.read_text(), **({'observe_generation': True} if observe_generation else {}))
    with script.open('x') as out:
        out.write(text)
    script.chmod(0o700)
    script_binding = COLD['binding'](script, 'usb-device-launch-script')
    command = [str(script) if arg == str(original) else arg for arg in launch['command']]
    with (run_dir.parent / 'usb-prepare.stdout').open('x') as out, (run_dir.parent / 'usb-prepare.stderr').open('x') as err:
        subprocess.run(command, env={**env, 'QEMU_PREPARE_ONLY': '1'},
                       stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=55, check=True)
    COLD['recheck'](templates + [r for r in inputs if r['path'] not in regenerated] +
                    [original_binding, script_binding] + source_bindings)
    PERSISTENT['current_kernel_binding'](launch['actual_kernel'])
    if Path(launch['cmdline_file']).read_bytes() != cmdline_bytes:
        raise ValueError('USB preparation changed the original command line bytes')
    rebound = {path: COLD['binding'](path, row['role']) for path, row in regenerated.items()}
    updated_inputs = [rebound.get(row['path'], row) for row in inputs] + [script_binding]
    COLD['recheck'](updated_inputs)
    delta = dict(schema='a7c2.usb-device-launch-delta.v1',
        script_before=original_binding, script_after=script_binding,
        dtb_before=dtb_before, dtb_after=rebound[launch['dtb']],
        cmdline_before=cmdline_before, cmdline_after=rebound[launch['cmdline_file']],
        cmdline_bytes_unchanged=True, topology='/soc/usbs@f1080000/usb@f10c0000',
        profile_source=source_bindings[-1])
    if observe_generation:
        delta['generation_observe'] = True
    result = dict(launch, env=env, script=str(script), script_sha256=script_binding['sha256'],
        command=command, dtb_sha256=rebound[launch['dtb']]['sha256'],
        launch_inputs=updated_inputs, template_inputs=templates + source_bindings,
        usb_device_delta=delta, usb_device_profile=PROFILE, guest_descriptor_ready=False, export_allowed=False)
    result['launch_adaptations'] = dict(launch.get('launch_adaptations', {}),
        usb_platform_resources='full', usb_controller=CONTROLLER,
        usb_vbus='functional Sony GPIO17.12 -> original fusb', phy_sram_supported=False,
        phy_sram_init_model='clock-reset-config-sequence-v1', vbus_kernel_event_delivered=False)
    if observe_generation:
        result['launch_adaptations']['usb_generation_observe'] = True
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--scratch-root', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(patch_source(args.source, args.scratch_root), indent=2))
