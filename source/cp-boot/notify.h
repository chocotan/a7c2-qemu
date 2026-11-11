/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * notify: AP/CP GPIO notify-line core, profile virtual-ap-cp-gpio-lines-v1.
 *
 * Bounded functional model, physical=false: no IRQ, no PCIe/UIPC ACK, no
 * fake ready, and no claim about Sony physical reset values or wiring.
 * Two channels cross-wire the two devices:
 *
 *   ch0: AP GPIO18/9 -> CP GPIO17/2   (CP reads RDATA bit 2 = 0x4)
 *        CP GPIO18/3 -> AP GPIO17/4   (AP reads RDATA bit 4 = 0x10)
 *   ch1: AP GPIO18/8 -> CP GPIO16/2   (bank 16 is not mapped on this part,
 *        CP GPIO18/2 -> AP GPIO17/3    so AP ch1 has no CP consumer)
 *
 * A side drives a channel only when its bank-18 pin has DIR=1 (output) and
 * PORTSEL=1 (GPIO function); the driven level comes from that bank's WDATA
 * latch. Each instance is a state machine only: the transport, wire frames
 * and QEMU staging are implemented by the caller (see notify-qemu.c). The
 * peer view arrives as snapshots via notify_peer()/notify_disconnect().
 *
 * Register file semantics (both banks, offsets per the public same-SoC
 * kernel regs-gpio.h): DIR 0x00 + SET 0x04/CLR 0x08, RDATA 0x10 (read-only
 * wire inputs), INEN 0x20 + SET/CLR, PORTSEL 0x30 + SET/CLR, WDATA 0x40 +
 * SET/CLR, all 32-bit, delegated to cp_gpio18. Bank 17 RDATA reads are the
 * virtual wire; bank 18 RDATA is rejected. Initial state is virtual reset 0
 * plus the verified BK4 script writes (see notify.c); CP bank 18 uses the
 * original cp_gpio18 loader profile. Unconnected or unknown inputs are
 * defined as rejected reads (never fabricated levels).
 *
 * All functions return -1 on invalid arguments or rejected access without
 * changing state or *out; notify_disconnect returns void.
 */
#ifndef NOTIFY_H
#define NOTIFY_H

#include <stdbool.h>
#include <stdint.h>

#include "gpio18.h"

#define NOTIFY_PROFILE "virtual-ap-cp-gpio-lines-v1"

enum notify_side { NOTIFY_AP = 0, NOTIFY_CP = 1 };

struct notify_gpio {
    struct cp_gpio18 bank17;
    struct cp_gpio18 bank18;
    enum notify_side side;
    uint32_t peer_known;   /* peer-driven channels, bit0=ch0, bit1=ch1 */
    uint32_t peer_levels;  /* peer line levels, same bit layout */
    bool peer_valid;       /* a peer snapshot is connected */
};

/* Initialize both register banks to the side's virtual initial state
 * (reset 0 + verified BK4 writes; CP bank 18 via cp_gpio18_init), set the
 * side, and clear the peer view. Counters start at 0. Returns 0 or -1. */
int notify_init(struct notify_gpio *n, enum notify_side side);

/* Reset the local register banks and counters exactly like notify_init for
 * the current side, but keep peer_valid/peer_known/peer_levels: the peer's
 * lines do not change because this end reset. Returns 0 or -1. */
int notify_reset(struct notify_gpio *n);

/* Guest MMIO read on one bank (port 17 or 18). Bank 17 RDATA (0x10) is the
 * virtual wire input and requires, for CP: peer_valid, peer_known bit 0,
 * bank17 INEN bit 2 and DIR bit 2 clear; for AP: peer_valid, peer_known
 * both bits, INEN 0x18 and DIR 0x18 clear. On success *out holds the mapped
 * peer levels (CP: bit2; AP: bit4 from ch0, bit3 from ch1). Everything else
 * delegates to cp_gpio18_read (bank 18 RDATA and unknown offsets are
 * rejected there). *out is only written on success. */
int notify_read(struct notify_gpio *n, unsigned port, uint32_t offset,
                uint32_t *out);

/* Guest MMIO write on one bank (port 17 or 18); delegates to
 * cp_gpio18_write, which rejects read-only RDATA 0x10 and unknown offsets
 * without state change. Returns 0 or -1. */
int notify_write(struct notify_gpio *n, unsigned port, uint32_t offset,
                 uint32_t value);

/* Feed a peer output snapshot: known/levels use bits 0..1 (ch0/ch1).
 * Rejects NULL, known > 3, levels > 3, or levels outside known, leaving
 * the previous peer state untouched. A valid snapshot sets peer_valid. */
int notify_peer(struct notify_gpio *n, uint32_t known, uint32_t levels);

/* Drop the peer view: clears peer_valid/known/levels. Safe on NULL. */
void notify_disconnect(struct notify_gpio *n);

/* Report this side's driven channels: known bit i is 1 only while the
 * channel's bank-18 pin has DIR=1 and PORTSEL=1, and levels bit i then
 * carries that pin's WDATA bit (never reported for undriven channels, so
 * levels & ~known is always 0). AP drives ch0/ch1 on pins 9/8, CP on 3/2.
 * Returns 0 or -1 (NULL arguments). */
int notify_output(const struct notify_gpio *n, uint32_t *known,
                  uint32_t *levels);

#endif /* NOTIFY_H */
