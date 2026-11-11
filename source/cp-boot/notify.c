/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * notify core, profile virtual-ap-cp-gpio-lines-v1 (functional model,
 * physical=false: no IRQ, no UIPC ACK, no Sony physical-reset claim).
 *
 * State machine only. The initial state is the declared virtual reset 0
 * plus the op32 writes verified from the original BK4 script (bank 18 of
 * the CP side reuses the original cp_gpio18 loader profile); it is not a
 * claim that any real code executed. Loader writes are initialization, not
 * guest traffic, so the cp_gpio18 counters are zeroed afterwards.
 */
#include "notify.h"

#include <stddef.h>
#include <string.h>

#define REG_RDATA 0x10u

struct reg_write {
    uint32_t off;
    uint32_t val;
};

/* Bank-17 initial writes from the verified BK4 script (hex). */
static const struct reg_write CP17_INIT[] = {
    { 0x48u, 0x8u },       { 0x34u, 0x41208u },  { 0x38u, 0xfbe157u },
    { 0x04u, 0x8u },       { 0x08u, 0xfff357u }, { 0x24u, 0xfff357u },
    { 0x28u, 0x8u },
};
static const struct reg_write AP17_INIT[] = {
    { 0x44u, 0x41u },      { 0x48u, 0x12000u },  { 0x34u, 0x52446u },
    { 0x38u, 0x20288b9u }, { 0x04u, 0x12041u },  { 0x08u, 0x68cbeu },
    { 0x24u, 0x2068cfeu }, { 0x28u, 0x12001u },
};
/* The AP script writes no bank-18 PORTSEL CLR (offset 0x38). */
static const struct reg_write AP18_INIT[] = {
    { 0x44u, 0x41u },      { 0x48u, 0x300u },    { 0x34u, 0xbc1u },
    { 0x04u, 0xb41u },     { 0x08u, 0x80u },     { 0x24u, 0x381u },
    { 0x28u, 0x840u },
};

/* This side's bank-18 output pin for a channel: AP ch0/ch1 = pins 9/8,
 * CP ch0/ch1 = pins 3/2. */
static uint32_t out_pin(enum notify_side side, unsigned ch)
{
    if (side == NOTIFY_CP) {
        return ch == 0u ? 3u : 2u;
    }
    return ch == 0u ? 9u : 8u;
}

static int apply_writes(struct cp_gpio18 *b, const struct reg_write *table,
                        size_t n)
{
    size_t i;

    for (i = 0; i < n; i++) {
        if (cp_gpio18_write(b, table[i].off, table[i].val) != 0) {
            return -1;
        }
    }
    return 0;
}

/* Build the local register banks for one side (virtual reset 0 + BK4
 * writes), leaving the peer view untouched. */
static int local_init(struct notify_gpio *n, enum notify_side side)
{
    if (side != NOTIFY_AP && side != NOTIFY_CP) {
        return -1;
    }
    n->side = side;
    if (side == NOTIFY_CP) {
        memset(&n->bank17, 0, sizeof(n->bank17));
        if (apply_writes(&n->bank17, CP17_INIT,
                         sizeof(CP17_INIT) / sizeof(CP17_INIT[0])) != 0) {
            return -1;
        }
        /* Original loader profile; also zeroes its own counters. */
        if (cp_gpio18_init(&n->bank18, CP_GPIO18_PROFILE) != 0) {
            return -1;
        }
    } else {
        memset(&n->bank17, 0, sizeof(n->bank17));
        memset(&n->bank18, 0, sizeof(n->bank18));
        if (apply_writes(&n->bank17, AP17_INIT,
                         sizeof(AP17_INIT) / sizeof(AP17_INIT[0])) != 0 ||
            apply_writes(&n->bank18, AP18_INIT,
                         sizeof(AP18_INIT) / sizeof(AP18_INIT[0])) != 0) {
            return -1;
        }
    }
    /* BK4 writes are initialization, not guest traffic. */
    n->bank17.reads = 0;
    n->bank17.writes = 0;
    n->bank18.reads = 0;
    n->bank18.writes = 0;
    return 0;
}

int notify_init(struct notify_gpio *n, enum notify_side side)
{
    if (n == NULL || (side != NOTIFY_AP && side != NOTIFY_CP)) {
        return -1;
    }
    n->peer_valid = false;
    n->peer_known = 0u;
    n->peer_levels = 0u;
    return local_init(n, side);
}

int notify_reset(struct notify_gpio *n)
{
    uint32_t known, levels;
    bool valid;

    if (n == NULL) {
        return -1;
    }
    known = n->peer_known;
    levels = n->peer_levels;
    valid = n->peer_valid;
    if (local_init(n, n->side) != 0) {
        return -1;
    }
    n->peer_known = known;
    n->peer_levels = levels;
    n->peer_valid = valid;
    return 0;
}

/* Bank-17 RDATA: the virtual wire input. The receiver only gets levels for
 * channels the peer actually drives and only while its own input-enable /
 * direction configuration matches the BK4 wiring. */
static int read_rdata17(struct notify_gpio *n, uint32_t *out)
{
    const struct cp_gpio18 *b = &n->bank17;

    if (!n->peer_valid) {
        return -1;
    }
    if (n->side == NOTIFY_CP) {
        if (!(n->peer_known & 0x1u) || !(b->inen & 0x4u) ||
            (b->dir & 0x4u) != 0u) {
            return -1;
        }
        *out = (n->peer_levels & 0x1u) ? 0x4u : 0x0u;
    } else {
        if (n->peer_known != 0x3u || (b->inen & 0x18u) != 0x18u ||
            (b->dir & 0x18u) != 0x0u) {
            return -1;
        }
        *out = ((n->peer_levels & 0x1u) ? 0x10u : 0x0u) |
               ((n->peer_levels & 0x2u) ? 0x8u : 0x0u);
    }
    n->bank17.reads++; /* a successful guest read of bank 17 */
    return 0;
}

int notify_read(struct notify_gpio *n, unsigned port, uint32_t offset,
                uint32_t *out)
{
    if (n == NULL || out == NULL) {
        return -1;
    }
    if (port == 17u && offset == REG_RDATA) {
        return read_rdata17(n, out);
    }
    if (port != 17u && port != 18u) {
        return -1;
    }
    /* Bank 18 RDATA (0x10) and every unknown offset are rejected here. */
    return cp_gpio18_read(port == 17u ? &n->bank17 : &n->bank18, offset,
                          out);
}

int notify_write(struct notify_gpio *n, unsigned port, uint32_t offset,
                 uint32_t value)
{
    if (n == NULL || (port != 17u && port != 18u)) {
        return -1;
    }
    /* Read-only RDATA 0x10 and unknown offsets are rejected by the
     * register-file model, leaving state untouched. */
    return cp_gpio18_write(port == 17u ? &n->bank17 : &n->bank18, offset,
                           value);
}

int notify_peer(struct notify_gpio *n, uint32_t known, uint32_t levels)
{
    if (n == NULL || known > 0x3u || levels > 0x3u ||
        (levels & ~known) != 0u) {
        return -1; /* no state change */
    }
    n->peer_valid = true;
    n->peer_known = known;
    n->peer_levels = levels;
    return 0;
}

void notify_disconnect(struct notify_gpio *n)
{
    if (n == NULL) {
        return;
    }
    n->peer_valid = false;
    n->peer_known = 0u;
    n->peer_levels = 0u;
}

int notify_output(const struct notify_gpio *n, uint32_t *known,
                  uint32_t *levels)
{
    uint32_t k = 0u;
    uint32_t l = 0u;
    unsigned ch;

    if (n == NULL || known == NULL || levels == NULL) {
        return -1;
    }
    if (n->side != NOTIFY_AP && n->side != NOTIFY_CP) {
        return -1;
    }
    for (ch = 0u; ch < 2u; ch++) {
        uint32_t pin = 1u << out_pin(n->side, ch);

        /* Driven only while the bank-18 pin is a GPIO output; the level
         * is never reported for an undriven channel. */
        if ((n->bank18.dir & pin) != 0u && (n->bank18.portsel & pin) != 0u) {
            k |= 1u << ch;
            if ((n->bank18.wdata & pin) != 0u) {
                l |= 1u << ch;
            }
        }
    }
    *known = k;
    *levels = l;
    return 0;
}
