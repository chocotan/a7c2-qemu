/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Virtual SCU clock/SRST latch bank, profile virtual-cp-scu-i2c-v1.
 *
 * Functional model only: pure 32-bit storage with SET/CLR companions.
 * No side effects, no IRQ, no clock-ready/ACK, no real clock gating.
 * Virtual reset is defined all-zero, NOT the Sony physical reset value.
 *
 * SRST group 4 (0x340/0x344/0x348) is deliberately unreachable: the
 * original CP watchdog owns that group with real semantics, as it owns
 * 0x3a0 (WDT_MISC); this model must never shadow or override them.
 */
#include "scu.h"

#include <stddef.h>
#include <string.h>

#define SRST_BASE    0x300u
#define GROUP_STRIDE 0x10u
#define NCLK         9u
#define NSRST        6u
#define SRST_WDT_CH  4u /* watchdog-owned group, never mapped */

/* Decode offset -> bank/index/sub-offset. Only aligned4 offsets with sub
 * in {0x0 DATA, 0x4 SET, 0x8 CLR} inside the modeled groups decode. */
static int cp_scu_decode(uint32_t offset, int *is_reset, unsigned *idx,
                         unsigned *sub)
{
    if (offset & 3u) {
        return -1; /* only aligned4 accesses are valid */
    }
    *sub = offset & (GROUP_STRIDE - 1u);
    if (*sub != 0u && *sub != 4u && *sub != 8u) {
        return -1;
    }
    if (offset < SRST_BASE) {
        *is_reset = 0;
        *idx = offset / GROUP_STRIDE;
        return *idx < NCLK ? 0 : -1;
    }
    *is_reset = 1;
    *idx = (offset - SRST_BASE) / GROUP_STRIDE;
    return *idx < NSRST ? 0 : -1; /* 0x360.. and 0x3a0 WDT_MISC: unknown */
}

int cp_scu_init(struct cp_scu *s, const char *profile)
{
    if (s == NULL || profile == NULL ||
        strcmp(profile, CP_SCU_PROFILE) != 0) {
        return -1;
    }
    memset(s, 0, sizeof(*s)); /* declared virtual reset, not physical */
    return 0;
}

int cp_scu_read(struct cp_scu *s, uint32_t offset, uint32_t *out)
{
    int is_reset;
    unsigned idx, sub;

    if (s == NULL || out == NULL) {
        return -1;
    }
    if (cp_scu_decode(offset, &is_reset, &idx, &sub)) {
        return -1; /* unknown/unaligned: *out and state stay untouched */
    }
    if (sub != 0u) {
        return -1; /* SET/CLR are write-only companions */
    }
    if (is_reset && idx == SRST_WDT_CH) {
        return -1; /* watchdog-owned group, never mapped */
    }
    *out = is_reset ? s->reset[idx] : s->clock[idx]; /* real latch */
    return 0;
}

int cp_scu_write(struct cp_scu *s, uint32_t offset, uint32_t value)
{
    int is_reset;
    unsigned idx, sub;
    uint32_t *r;

    if (s == NULL) {
        return -1;
    }
    if (cp_scu_decode(offset, &is_reset, &idx, &sub)) {
        return -1; /* unknown/unaligned: state stays untouched */
    }
    if (is_reset && idx == SRST_WDT_CH) {
        return -1; /* watchdog-owned group, never mapped */
    }
    r = is_reset ? &s->reset[idx] : &s->clock[idx];
    switch (sub) {
    case 0u:
        *r = value; /* full 32-bit retention; no mask proven physical */
        break;
    case 4u:
        *r |= value;
        break;
    case 8u:
        *r &= ~value;
        break;
    default:
        return -1; /* unreachable: decode already filtered other subs */
    }
    return 0;
}

int cp_scu_dfs_read(struct cp_scu *s, uint32_t offset, uint32_t *out)
{
    if (!s || !out) return -1;
    switch (offset) {
    case 0: *out = s->dfs_request; return 0;
    case 4: *out = s->dfs_init; return 0;
    case 8: *out = s->dfs_trigger; return 0;
    case 12: *out = s->dfs_target; return 0;
    case 16: *out = s->dfs_status; return 0;
    default: return -1;
    }
}

int cp_scu_dfs_write(struct cp_scu *s, uint32_t offset, uint32_t value)
{
    if (!s) return -1;
    if (offset == 4) {
        if (value != 0x101 || s->dfs_busy) return -1;
        s->dfs_init = value;
        s->dfs_initialized = 1;
        return 0;
    }
    if (!s->dfs_initialized) return -1;
    switch (offset) {
    case 0:
        if (value != 0x101) return -1;
        s->dfs_request = value;
        s->dfs_prepared = 1;
        s->dfs_latched = 0;
        return 0;
    case 12:
        if (!s->dfs_prepared || s->dfs_busy || (value & ~0x100u) > 6) return -1;
        s->dfs_target = value;
        s->dfs_latched = 1;
        return 0;
    case 8:
        if (value != 1 || !s->dfs_prepared || !s->dfs_latched || s->dfs_busy) return -1;
        s->dfs_trigger = value;
        s->dfs_status = s->dfs_mode | 0x100u;
        s->dfs_busy = 1;
        s->dfs_prepared = s->dfs_latched = 0;
        return 0;
    default: return -1;
    }
}

int cp_scu_dfs_complete(struct cp_scu *s)
{
    if (!s || !s->dfs_busy) return 0;
    s->dfs_mode = s->dfs_target & 0xffu;
    s->dfs_status = s->dfs_mode;
    if (!s->dfs_prepared) s->dfs_request = 1;
    s->dfs_busy = 0;
    return 1;
}
