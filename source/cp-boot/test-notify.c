/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Host self-test for the notify core (virtual-ap-cp-gpio-lines-v1).
 *
 * Build & run:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
 *      gpio18.c notify.c test-notify.c -o test-notify && ./test-notify
 *
 * Covers: init/reset argument rejection, the BK4 initial state of all four
 * banks, counters zero after init, parameter/offset/port rejections with
 * *out preserved, RDATA 0x10 rules (no peer, disconnected, known bits
 * missing, INEN/DIR gating), real level flips propagating through
 * notify_output -> notify_peer wire snapshots in both directions, invalid
 * peer snapshots keeping previous state, partial reset keeping the peer
 * view while restoring local registers, and 32-bit DATA/SET/CLR semantics.
 */
#include "notify.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond) do {                                                  \
        checks++;                                                         \
        if (!(cond)) {                                                    \
            failures++;                                                   \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                 \
    } while (0)

/* Simulate the main-session transport: push one side's output snapshot
 * into the peer's input view. */
static int wire(struct notify_gpio *from, struct notify_gpio *to)
{
    uint32_t known, levels;

    if (notify_output(from, &known, &levels) != 0) {
        return -1;
    }
    return notify_peer(to, known, levels);
}

static void test_init_reject(void)
{
    struct notify_gpio n;
    uint32_t k, l;

    memset(&n, 0, sizeof(n));
    CHECK(notify_init(NULL, NOTIFY_AP) == -1);
    CHECK(notify_init(&n, (enum notify_side)2) == -1);
    CHECK(notify_init(&n, (enum notify_side)99) == -1);
    CHECK(notify_reset(NULL) == -1);

    n.side = (enum notify_side)7; /* never initialized */
    CHECK(notify_output(&n, &k, &l) == -1);
    CHECK(notify_reset(&n) == -1);
}

static void test_cp_init_state(void)
{
    struct notify_gpio cp;
    uint32_t v = 0xBAD0BAD0u;

    CHECK(notify_init(&cp, NOTIFY_CP) == 0);
    CHECK(cp.side == NOTIFY_CP);
    CHECK(!cp.peer_valid && cp.peer_known == 0u && cp.peer_levels == 0u);
    /* Counters zero after init even though setup writes happened. */
    CHECK(cp.bank17.reads == 0 && cp.bank17.writes == 0);
    CHECK(cp.bank18.reads == 0 && cp.bank18.writes == 0);
    /* BK4-derived bank 17. */
    CHECK(notify_read(&cp, 17, 0x00u, &v) == 0 && v == 0x8u);
    CHECK(notify_read(&cp, 17, 0x20u, &v) == 0 && v == 0xfff357u);
    CHECK(notify_read(&cp, 17, 0x30u, &v) == 0 && v == 0x41208u);
    CHECK(notify_read(&cp, 17, 0x40u, &v) == 0 && v == 0x0u);
    /* Bank 18 via the original cp_gpio18 loader profile. */
    CHECK(notify_read(&cp, 18, 0x00u, &v) == 0 && v == 0xfu);
    CHECK(notify_read(&cp, 18, 0x20u, &v) == 0 && v == 0xfu);
    CHECK(notify_read(&cp, 18, 0x30u, &v) == 0 && v == 0xeu);
    CHECK(notify_read(&cp, 18, 0x40u, &v) == 0 && v == 0x2u);
}

static void test_ap_init_state(void)
{
    struct notify_gpio ap;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(ap.side == NOTIFY_AP);
    CHECK(!ap.peer_valid && ap.peer_known == 0u && ap.peer_levels == 0u);
    CHECK(notify_read(&ap, 17, 0x00u, &v) == 0 && v == 0x12041u);
    CHECK(notify_read(&ap, 17, 0x20u, &v) == 0 && v == 0x2068cfeu);
    CHECK(notify_read(&ap, 17, 0x30u, &v) == 0 && v == 0x52446u);
    CHECK(notify_read(&ap, 17, 0x40u, &v) == 0 && v == 0x41u);
    CHECK(notify_read(&ap, 18, 0x00u, &v) == 0 && v == 0xb41u);
    CHECK(notify_read(&ap, 18, 0x20u, &v) == 0 && v == 0x381u);
    CHECK(notify_read(&ap, 18, 0x30u, &v) == 0 && v == 0xbc1u);
    CHECK(notify_read(&ap, 18, 0x40u, &v) == 0 && v == 0x41u);
    CHECK(ap.bank17.reads == 4 && ap.bank17.writes == 0);
    CHECK(ap.bank18.reads == 4 && ap.bank18.writes == 0);
}

static void test_init_output_state(void)
{
    struct notify_gpio ap, cp;
    uint32_t k, l;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_init(&cp, NOTIFY_CP) == 0);
    CHECK(notify_output(&ap, &k, &l) == 0 && k == 0x3u && l == 0x0u);
    CHECK(notify_output(&cp, &k, &l) == 0 && k == 0x3u && l == 0x0u);
    /* A channel stops being known when DIR or PORTSEL drops out. */
    CHECK(notify_write(&cp, 18, 0x08u, 0x8u) == 0); /* CLR DIR ch0 pin3 */
    CHECK(notify_output(&cp, &k, &l) == 0 && k == 0x2u);
    CHECK(notify_write(&cp, 18, 0x04u, 0x8u) == 0); /* restore */
    CHECK(notify_write(&cp, 18, 0x38u, 0x8u) == 0); /* CLR PORTSEL pin3 */
    CHECK(notify_output(&cp, &k, &l) == 0 && k == 0x2u);
    CHECK(notify_write(&cp, 18, 0x34u, 0x8u) == 0); /* restore */
    CHECK(notify_output(&cp, &k, &l) == 0 && k == 0x3u);
}

static void test_param_reject(void)
{
    struct notify_gpio ap;
    uint32_t v, k, l;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    v = 0xCAFEBABEu;
    CHECK(notify_read(NULL, 17, 0x00u, &v) == -1);
    CHECK(notify_read(&ap, 17, 0x00u, NULL) == -1);
    CHECK(notify_write(NULL, 17, 0x00u, 1u) == -1);
    /* Wrong ports. */
    CHECK(notify_read(&ap, 0, 0x00u, &v) == -1 && v == 0xCAFEBABEu);
    CHECK(notify_read(&ap, 1, 0x00u, &v) == -1);
    CHECK(notify_read(&ap, 16, 0x00u, &v) == -1);
    CHECK(notify_read(&ap, 19, 0x00u, &v) == -1);
    CHECK(notify_read(&ap, 100, 0x00u, &v) == -1);
    CHECK(notify_write(&ap, 16, 0x00u, 1u) == -1);
    CHECK(notify_write(&ap, 19, 0x44u, 1u) == -1);
    /* Unknown/unaligned offsets. */
    CHECK(notify_read(&ap, 17, 0x14u, &v) == -1);
    CHECK(notify_read(&ap, 18, 0x50u, &v) == -1);
    CHECK(notify_read(&ap, 17, 0x02u, &v) == -1);
    CHECK(notify_write(&ap, 17, 0x14u, 1u) == -1);
    CHECK(notify_write(&ap, 18, 0x2cu, 1u) == -1);
    /* Bank 18 RDATA is never wire-readable; writes to RDATA are illegal. */
    CHECK(notify_read(&ap, 18, 0x10u, &v) == -1 && v == 0xCAFEBABEu);
    CHECK(notify_write(&ap, 18, 0x10u, 1u) == -1);
    CHECK(notify_write(&ap, 17, 0x10u, 1u) == -1);
    /* Peer snapshots are two-bit masks only. */
    CHECK(notify_peer(NULL, 0u, 0u) == -1);
    CHECK(notify_peer(&ap, 4u, 0u) == -1);
    CHECK(notify_peer(&ap, 3u, 4u) == -1);
    CHECK(notify_peer(&ap, 2u, 3u) == -1);
    CHECK(notify_peer(&ap, 0u, 1u) == -1);
    CHECK(!ap.peer_valid);
    CHECK(notify_output(NULL, &k, &l) == -1);
    CHECK(notify_output(&ap, NULL, &l) == -1);
    CHECK(notify_output(&ap, &k, NULL) == -1);
    notify_disconnect(NULL); /* must not crash */
    /* Failed traffic does not touch counters. */
    CHECK(ap.bank17.reads == 0 && ap.bank17.writes == 0);
    CHECK(ap.bank18.reads == 0 && ap.bank18.writes == 0);
}

static void test_no_peer_reject(void)
{
    struct notify_gpio ap, cp;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_init(&cp, NOTIFY_CP) == 0);
    v = 0x12345678u;
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1 && v == 0x12345678u);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == -1 && v == 0x12345678u);
    CHECK(ap.bank17.reads == 0 && cp.bank17.reads == 0);
}

static void test_wire_flips(void)
{
    struct notify_gpio ap, cp;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_init(&cp, NOTIFY_CP) == 0);
    CHECK(wire(&cp, &ap) == 0);
    CHECK(wire(&ap, &cp) == 0);
    CHECK(ap.peer_valid && ap.peer_known == 0x3u && ap.peer_levels == 0x0u);
    CHECK(cp.peer_valid && cp.peer_known == 0x3u && cp.peer_levels == 0x0u);
    /* Both ends read their initial wire state. */
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x0u);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x0u);
    CHECK(ap.bank17.reads == 1u); /* RDATA reads count as bank reads */

    /* CP flips ch0 (pin3) and ch1 (pin2); AP maps them to bits 4 and 3. */
    CHECK(notify_write(&cp, 18, 0x44u, 0x8u) == 0);  /* WDATA SET pin3 */
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x10u);
    CHECK(notify_write(&cp, 18, 0x48u, 0x8u) == 0);  /* WDATA CLR pin3 */
    CHECK(notify_write(&cp, 18, 0x44u, 0x4u) == 0);  /* WDATA SET pin2 */
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x8u);
    CHECK(notify_write(&cp, 18, 0x44u, 0x8u) == 0);  /* both channels */
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x18u);

    /* AP flips ch0 (pin9, seen by CP at bit2) and ch1 (pin8, no consumer
     * on this part). */
    CHECK(notify_write(&ap, 18, 0x40u, 0x200u) == 0);
    CHECK(wire(&ap, &cp) == 0);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x4u);
    CHECK(notify_write(&ap, 18, 0x40u, 0x300u) == 0);
    CHECK(wire(&ap, &cp) == 0);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x4u);
    CHECK(notify_write(&ap, 18, 0x40u, 0x100u) == 0);
    CHECK(wire(&ap, &cp) == 0);
    CHECK(cp.peer_levels == 0x2u); /* ch1 traveled but has no consumer */
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x0u);
}

static void test_known_rules(void)
{
    struct notify_gpio ap, cp;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_init(&cp, NOTIFY_CP) == 0);

    /* AP needs both channels known (known == 3). */
    CHECK(notify_peer(&ap, 0u, 0u) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1);
    CHECK(notify_peer(&ap, 1u, 1u) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1);
    CHECK(notify_peer(&ap, 2u, 2u) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1);
    CHECK(notify_peer(&ap, 3u, 1u) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x10u);
    CHECK(notify_peer(&ap, 3u, 2u) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x8u);

    /* CP needs only ch0 (known bit 0). */
    CHECK(notify_peer(&cp, 0u, 0u) == 0);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == -1);
    CHECK(notify_peer(&cp, 2u, 2u) == 0);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == -1);
    CHECK(notify_peer(&cp, 1u, 0u) == 0);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x0u);
    CHECK(notify_peer(&cp, 3u, 1u) == 0);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x4u);

    /* Local INEN/DIR gating: break the input config, reads are rejected. */
    CHECK(notify_write(&cp, 17, 0x28u, 0x4u) == 0); /* INEN CLR bit2 */
    CHECK(notify_read(&cp, 17, 0x10u, &v) == -1);
    CHECK(notify_write(&cp, 17, 0x24u, 0x4u) == 0); /* INEN SET bit2 */
    CHECK(notify_write(&cp, 17, 0x04u, 0x4u) == 0); /* DIR SET bit2 */
    CHECK(notify_read(&cp, 17, 0x10u, &v) == -1);
    CHECK(notify_write(&cp, 17, 0x08u, 0x4u) == 0); /* DIR CLR bit2 */
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x4u);

    CHECK(notify_write(&ap, 17, 0x04u, 0x18u) == 0); /* DIR SET 0x18 */
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1);
    CHECK(notify_write(&ap, 17, 0x08u, 0x18u) == 0); /* DIR CLR 0x18 */
    CHECK(notify_write(&ap, 17, 0x28u, 0x18u) == 0); /* INEN CLR 0x18 */
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1);
    CHECK(notify_write(&ap, 17, 0x24u, 0x18u) == 0); /* INEN SET 0x18 */
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x8u);
}

static void test_invalid_peer_keeps_state(void)
{
    struct notify_gpio ap;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_peer(&ap, 3u, 2u) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x8u);
    CHECK(notify_peer(&ap, 4u, 0u) == -1);
    CHECK(notify_peer(&ap, 2u, 3u) == -1);
    CHECK(notify_peer(&ap, 0u, 1u) == -1);
    CHECK(notify_peer(&ap, 3u, 4u) == -1);
    CHECK(notify_peer(&ap, 1u, 2u) == -1);
    CHECK(notify_peer(NULL, 3u, 2u) == -1);
    /* State survived every rejected snapshot. */
    CHECK(ap.peer_valid && ap.peer_known == 0x3u && ap.peer_levels == 0x2u);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x8u);
}

static void test_disconnect(void)
{
    struct notify_gpio ap, cp;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_init(&cp, NOTIFY_CP) == 0);
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x0u);
    notify_disconnect(&ap);
    CHECK(!ap.peer_valid && ap.peer_known == 0u && ap.peer_levels == 0u);
    v = 0xDEADBEEFu;
    CHECK(notify_read(&ap, 17, 0x10u, &v) == -1 && v == 0xDEADBEEFu);
    /* Reconnect works after a disconnect. */
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0);
}

static void test_partial_reset(void)
{
    struct notify_gpio ap, cp;
    uint32_t v;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    CHECK(notify_init(&cp, NOTIFY_CP) == 0);
    CHECK(wire(&ap, &cp) == 0);
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_write(&cp, 18, 0x44u, 0x8u) == 0);
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x10u);

    /* Dirty the CP local state and counters. */
    CHECK(notify_write(&cp, 17, 0x00u, 0xffffffffu) == 0);
    CHECK(notify_write(&cp, 18, 0x48u, 0xfu) == 0);
    CHECK(notify_read(&cp, 17, 0x00u, &v) == 0 && v == 0xffffffffu);
    CHECK(cp.bank17.reads > 0 && cp.bank17.writes > 0);

    CHECK(notify_reset(&cp) == 0);
    /* Local registers back to the BK4 initial state, counters re-zeroed. */
    CHECK(cp.bank17.dir == 0x8u && cp.bank17.inen == 0xfff357u &&
          cp.bank17.portsel == 0x41208u && cp.bank17.wdata == 0x0u);
    CHECK(cp.bank18.dir == 0xfu && cp.bank18.inen == 0xfu &&
          cp.bank18.portsel == 0xeu && cp.bank18.wdata == 0x2u);
    CHECK(cp.bank17.reads == 0 && cp.bank17.writes == 0);
    CHECK(cp.bank18.reads == 0 && cp.bank18.writes == 0);
    /* The peer view survives the local reset. */
    CHECK(cp.peer_valid && cp.peer_known == 0x3u && cp.peer_levels == 0x0u);
    CHECK(notify_read(&cp, 17, 0x10u, &v) == 0 && v == 0x0u);
    /* The AP end is untouched. */
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x10u);
    CHECK(ap.bank17.dir == 0x12041u);
    /* Re-wiring after reset restores the initial wire levels. */
    CHECK(wire(&cp, &ap) == 0);
    CHECK(notify_read(&ap, 17, 0x10u, &v) == 0 && v == 0x0u);
}

static void test_setclr_32bit(void)
{
    struct notify_gpio ap;
    uint64_t w0;
    uint32_t v, k, l;

    CHECK(notify_init(&ap, NOTIFY_AP) == 0);
    /* Full 32-bit latch writes and SET/CLR companions on bank 17 DIR. */
    CHECK(notify_write(&ap, 17, 0x00u, 0x12345678u) == 0);
    CHECK(notify_read(&ap, 17, 0x00u, &v) == 0 && v == 0x12345678u);
    CHECK(notify_write(&ap, 17, 0x04u, 0x0000f00fu) == 0);
    CHECK(notify_read(&ap, 17, 0x00u, &v) == 0 && v == 0x1234f67fu);
    CHECK(notify_write(&ap, 17, 0x08u, 0x0000ff00u) == 0);
    CHECK(notify_read(&ap, 17, 0x00u, &v) == 0 && v == 0x1234007fu);

    /* Full-width WDATA on bank 18 drives both channels. */
    CHECK(notify_write(&ap, 18, 0x40u, 0xffffffffu) == 0);
    CHECK(notify_output(&ap, &k, &l) == 0 && k == 0x3u && l == 0x3u);
    CHECK(notify_write(&ap, 18, 0x48u, 0xffffffffu) == 0);
    CHECK(notify_output(&ap, &k, &l) == 0 && k == 0x3u && l == 0x0u);

    /* Counters only advance on success. */
    w0 = ap.bank18.writes;
    CHECK(notify_write(&ap, 18, 0x40u, 0x1u) == 0);
    CHECK(ap.bank18.writes == w0 + 1u);
    w0 = ap.bank18.writes;
    CHECK(notify_write(&ap, 18, 0x10u, 0x1u) == -1);
    CHECK(ap.bank18.writes == w0);
}

int main(void)
{
    test_init_reject();
    test_cp_init_state();
    test_ap_init_state();
    test_init_output_state();
    test_param_reject();
    test_no_peer_reject();
    test_wire_flips();
    test_known_rules();
    test_invalid_peer_keeps_state();
    test_disconnect();
    test_partial_reset();
    test_setclr_32bit();

    if (failures == 0) {
        printf("ALL %d CHECKS PASSED\n", checks);
        return 0;
    }
    printf("%d of %d CHECKS FAILED\n", failures, checks);
    return 1;
}
