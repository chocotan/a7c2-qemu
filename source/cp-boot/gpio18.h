/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * cp_gpio18: bounded functional model of the CP-side GPIO port 18 register
 * file for the virtual CP boot path. Profile: virtual-gpio18-loader-state-v1.
 *
 * Register offsets follow the public same-SoC kernel header
 * linux-kernel/drivers/udif/mach-cxd900xx/include/mach/regs-gpio.h
 * (DIR 0x00 / SET +0x04 / CLR +0x08, RDATA 0x10, INEN 0x20, FUNC/PORTSEL
 * 0x30, WDATA 0x40; each data register has SET/CLR companions at +4/+8).
 */
#ifndef CP_GPIO18_H
#define CP_GPIO18_H

#include <stdint.h>

#define CP_GPIO18_PROFILE "virtual-gpio18-loader-state-v1"

struct cp_gpio18 {
    uint32_t dir;     /* 0x00 direction latch */
    uint32_t inen;    /* 0x20 input-enable latch */
    uint32_t portsel; /* 0x30 port/function select latch (kernel: GPIO_FUNC) */
    uint32_t wdata;   /* 0x40 output-data latch, written by the guest only */
    uint64_t reads;   /* successful reads so far (diagnostics only) */
    uint64_t writes;  /* successful writes so far (diagnostics only) */
};

/*
 * Initialize s to the explicit virtual reset (all zero, NOT the Sony
 * physical reset) and apply the six op32 loader writes verified from the
 * original BK4 f9014a/ed000 script, yielding DIR=0xf INEN=0xf PORTSEL=0xe
 * WDATA=0x2. This is a declared functional initial state, not a claim that
 * real NOR code executed. Rejects NULL s, NULL or unknown profile.
 * Returns 0 on success, -1 on error (s untouched).
 */
int cp_gpio18_init(struct cp_gpio18 *s, const char *profile);

/*
 * Read a data register (0x00/0x20/0x30/0x40). Returns 0 on success.
 * Returns -1 for unknown or unimplemented offsets (RDATA 0x10, SET/CLR,
 * pull, irq, unaligned...); *out and state are left untouched.
 */
int cp_gpio18_read(struct cp_gpio18 *s, uint32_t offset, uint32_t *out);

/*
 * Write a data register (0x00/0x20/0x30/0x40) or its SET/CLR companion
 * (base+0x04 / base+0x08). Returns 0 on success.
 * Returns -1 for unknown offsets and read-only registers (RDATA 0x10);
 * state is left untouched. Counters only advance on success.
 */
int cp_gpio18_write(struct cp_gpio18 *s, uint32_t offset, uint32_t value);

#endif /* CP_GPIO18_H */
