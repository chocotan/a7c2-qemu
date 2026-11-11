/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Virtual GPIO port-18 model, profile virtual-gpio18-loader-state-v1.
 *
 * Functional model only: no peer device, no IRQ, no ACK, no forced-ready.
 * WDATA is a self-holding latch that only reflects what the guest wrote.
 * Virtual reset is defined as all-zero (NOT the Sony physical reset value);
 * init then applies the six op32 loader writes verified from the original
 * BK4 f9014a/ed000 boot script (see cp_gpio18_init).
 *
 * Registers retain full 32-bit guest writes. The script constrains its written
 * bits only; it does not prove any physical reserved-bit/reset values.
 */
#include "gpio18.h"

#include <stddef.h>
#include <string.h>

/* Offsets per public mach/regs-gpio.h of the same SoC. */
#define REG_DIR     0x00u
#define REG_SET     0x04u
#define REG_CLR     0x08u
#define REG_RDATA   0x10u
#define REG_INEN    0x20u
#define REG_PORTSEL 0x30u
#define REG_WDATA   0x40u

static uint32_t *cp_gpio18_reg(struct cp_gpio18 *s, uint32_t offset)
{
    switch (offset) {
    case REG_DIR:
        return &s->dir;
    case REG_INEN:
        return &s->inen;
    case REG_PORTSEL:
        return &s->portsel;
    case REG_WDATA:
        return &s->wdata;
    default:
        return NULL; /* RDATA 0x10, SET/CLR, pull, irq, unaligned, ... */
    }
}

int cp_gpio18_init(struct cp_gpio18 *s, const char *profile)
{
    if (s == NULL || profile == NULL ||
        strcmp(profile, CP_GPIO18_PROFILE) != 0) {
        return -1;
    }
    memset(s, 0, sizeof(*s));

    /* Six op32 loader writes from the verified BK4 f9014a/ed000 script,
     * expressed exactly as the SET/CLR MMIO writes they are. */
    (void)cp_gpio18_write(s, REG_WDATA + REG_SET, 2u);   /* SET WDATA=2   */
    (void)cp_gpio18_write(s, REG_WDATA + REG_CLR, 0xcu); /* CLR WDATA=0xc */
    (void)cp_gpio18_write(s, REG_PORTSEL + REG_SET, 0xeu); /* SET PORTSEL */
    (void)cp_gpio18_write(s, REG_PORTSEL + REG_CLR, 1u); /* CLR PORTSEL=1 */
    (void)cp_gpio18_write(s, REG_DIR + REG_SET, 0xfu);   /* SET DIR=0xf   */
    (void)cp_gpio18_write(s, REG_INEN + REG_SET, 0xfu);  /* SET INEN=0xf  */

    /* Loader ops are model initialization, not guest traffic. */
    s->reads = 0;
    s->writes = 0;
    return 0;
}

int cp_gpio18_read(struct cp_gpio18 *s, uint32_t offset, uint32_t *out)
{
    const uint32_t *r;

    if (s == NULL || out == NULL) {
        return -1;
    }
    r = cp_gpio18_reg(s, offset);
    if (r == NULL) {
        return -1; /* unknown/unimplemented: *out and state stay untouched */
    }
    *out = *r;
    s->reads++;
    return 0;
}

int cp_gpio18_write(struct cp_gpio18 *s, uint32_t offset, uint32_t value)
{
    uint32_t *r;

    if (s == NULL) {
        return -1;
    }
    r = cp_gpio18_reg(s, offset);
    if (r != NULL) {
        *r = value;
    } else {
        switch (offset) {
        case REG_DIR + REG_SET:
            s->dir |= value;
            break;
        case REG_INEN + REG_SET:
            s->inen |= value;
            break;
        case REG_PORTSEL + REG_SET:
            s->portsel |= value;
            break;
        case REG_WDATA + REG_SET:
            s->wdata |= value;
            break;
        case REG_DIR + REG_CLR:
            s->dir &= ~value;
            break;
        case REG_INEN + REG_CLR:
            s->inen &= ~value;
            break;
        case REG_PORTSEL + REG_CLR:
            s->portsel &= ~value;
            break;
        case REG_WDATA + REG_CLR:
            s->wdata &= ~value;
            break;
        default:
            return -1; /* unknown, read-only RDATA 0x10, pull, irq */
        }
    }
    s->writes++;
    return 0;
}
