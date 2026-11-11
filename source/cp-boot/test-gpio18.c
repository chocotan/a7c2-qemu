/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Host self-test for cp_gpio18 (profile virtual-gpio18-loader-state-v1).
 *
 * Build & run:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
 *      gpio18.c test-gpio18.c -o test-gpio18 && ./test-gpio18
 *
 * Covers: profile rejection, loader initial state, data-register reads,
 * SET/CLR write semantics, unknown/read-only offsets (state and *out must
 * stay untouched), NULL args, counter accounting, re-init reset.
 */
#include "gpio18.h"

#include <stdint.h>
#include <stdio.h>

static int failures;
static int checks;

#define CHECK(cond) do {                                                  \
        checks++;                                                         \
        if (!(cond)) {                                                    \
            failures++;                                                   \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                 \
    } while (0)

static void test_init_profile(void)
{
    struct cp_gpio18 s;

    CHECK(cp_gpio18_init(NULL, CP_GPIO18_PROFILE) == -1);
    CHECK(cp_gpio18_init(&s, NULL) == -1);
    CHECK(cp_gpio18_init(&s, "") == -1);
    CHECK(cp_gpio18_init(&s, "virtual-gpio18-loader-state-v2") == -1);
    CHECK(cp_gpio18_init(&s, "virtual-gpio18-loader-state-v1x") == -1);
    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
}

static void test_failed_init_keeps_state(void)
{
    struct cp_gpio18 s;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    s.dir = 0x1u;
    s.inen = 0x2u;
    s.portsel = 0x4u;
    s.wdata = 0x8u;
    s.reads = 7;
    s.writes = 9;
    CHECK(cp_gpio18_init(&s, "nope") == -1);
    CHECK(cp_gpio18_init(&s, NULL) == -1);
    CHECK(s.dir == 0x1u && s.inen == 0x2u && s.portsel == 0x4u &&
          s.wdata == 0x8u && s.reads == 7 && s.writes == 9);
}

static void test_loader_state(void)
{
    struct cp_gpio18 s;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    /* BK4 f9014a/ed000 six-op32 functional initial state */
    CHECK(s.dir == 0xfu);
    CHECK(s.inen == 0xfu);
    CHECK(s.portsel == 0xeu);
    CHECK(s.wdata == 0x2u);
    CHECK(s.reads == 0);
    CHECK(s.writes == 0);
}

static void test_reads_and_counters(void)
{
    struct cp_gpio18 s;
    uint32_t v = 0xfeedfaceu;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    CHECK(cp_gpio18_read(&s, 0x00u, &v) == 0);
    CHECK(v == 0xfu);
    CHECK(cp_gpio18_read(&s, 0x20u, &v) == 0);
    CHECK(v == 0xfu);
    CHECK(cp_gpio18_read(&s, 0x30u, &v) == 0);
    CHECK(v == 0xeu);
    CHECK(cp_gpio18_read(&s, 0x40u, &v) == 0);
    CHECK(v == 0x2u);
    CHECK(s.reads == 4);
    CHECK(s.writes == 0);
}

static void test_unknown_reads(void)
{
    /* RDATA 0x10, all SET/CLR companions, gaps, pull/irq-style, unaligned,
     * out-of-range. Every one must fail without touching *out or state. */
    static const uint32_t bad[] = {
        0x10u, 0x04u, 0x08u, 0x24u, 0x28u, 0x34u, 0x38u, 0x44u, 0x48u,
        0x0cu, 0x14u, 0x18u, 0x1cu, 0x50u, 0x54u, 0x58u, 0x60u, 0x100u,
        0xffffffffu, 0x01u, 0x02u, 0x42u,
    };
    struct cp_gpio18 s;
    uint32_t v;
    size_t i;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    CHECK(cp_gpio18_read(&s, 0x00u, &v) == 0);
    CHECK(v == 0xfu);
    for (i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        v = 0xfeedfaceu;
        CHECK(cp_gpio18_read(&s, bad[i], &v) == -1);
        CHECK(v == 0xfeedfaceu); /* *out untouched on failure */
    }
    CHECK(s.reads == 1); /* only the successful read counted */
    CHECK(s.writes == 0);
}

static void test_writes_set_clr_and_counters(void)
{
    struct cp_gpio18 s;
    uint32_t v;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);

    /* DATA writes retain all bits; the loader masks do not prove width. */
    CHECK(cp_gpio18_write(&s, 0x00u, 0x33u) == 0);
    CHECK(cp_gpio18_write(&s, 0x20u, 0x0u) == 0);
    CHECK(cp_gpio18_write(&s, 0x30u, 0xffffffffu) == 0);
    CHECK(cp_gpio18_write(&s, 0x40u, 0xa5u) == 0);
    CHECK(cp_gpio18_read(&s, 0x00u, &v) == 0 && v == 0x33u);
    CHECK(cp_gpio18_read(&s, 0x20u, &v) == 0 && v == 0x0u);
    CHECK(cp_gpio18_read(&s, 0x30u, &v) == 0 && v == 0xffffffffu);
    CHECK(cp_gpio18_read(&s, 0x40u, &v) == 0 && v == 0xa5u);

    /* SET/CLR preserve unrelated high bits. */
    CHECK(cp_gpio18_write(&s, 0x44u, 0x8u) == 0);
    CHECK(cp_gpio18_write(&s, 0x48u, 0x4u) == 0);
    CHECK(cp_gpio18_write(&s, 0x04u, 0x8u) == 0);
    CHECK(cp_gpio18_write(&s, 0x08u, 0x3u) == 0);
    CHECK(cp_gpio18_write(&s, 0x24u, 0x6u) == 0);
    CHECK(cp_gpio18_write(&s, 0x28u, 0x2u) == 0);
    CHECK(cp_gpio18_write(&s, 0x34u, 0x1u) == 0);
    CHECK(cp_gpio18_write(&s, 0x38u, 0x3u) == 0);
    CHECK(cp_gpio18_read(&s, 0x00u, &v) == 0 && v == 0x38u);
    CHECK(cp_gpio18_read(&s, 0x20u, &v) == 0 && v == 0x4u);
    CHECK(cp_gpio18_read(&s, 0x30u, &v) == 0 && v == 0xfffffffcu);
    CHECK(cp_gpio18_read(&s, 0x40u, &v) == 0 && v == 0xa9u);
    CHECK(s.reads == 8);
    CHECK(s.writes == 12);

    /* Functional storage preserves guest-written high bits too. */
    CHECK(cp_gpio18_write(&s, 0x40u, 0xfffffff0u) == 0);
    CHECK(cp_gpio18_read(&s, 0x40u, &v) == 0 && v == 0xfffffff0u);
    CHECK(cp_gpio18_write(&s, 0x44u, 0xffffffffu) == 0);
    CHECK(cp_gpio18_read(&s, 0x40u, &v) == 0 && v == 0xffffffffu);
}

static void test_unknown_writes(void)
{
    /* read-only RDATA 0x10, gaps, pull/irq-style, unaligned, out-of-range */
    static const uint32_t bad[] = {
        0x10u, 0x0cu, 0x14u, 0x18u, 0x1cu, 0x50u, 0x54u, 0x58u, 0x100u,
        0xffffffffu, 0x02u,
    };
    struct cp_gpio18 s;
    size_t i;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    s.dir = 0x12345678u;
    s.inen = 0x9abcdef0u;
    s.portsel = 0x0f0f0f0fu;
    s.wdata = 0xdeadbeefu;
    s.reads = 3;
    s.writes = 5;
    for (i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        CHECK(cp_gpio18_write(&s, bad[i], 0xffffffffu) == -1);
    }
    CHECK(s.dir == 0x12345678u && s.inen == 0x9abcdef0u &&
          s.portsel == 0x0f0f0f0fu && s.wdata == 0xdeadbeefu);
    CHECK(s.reads == 3 && s.writes == 5);
}

static void test_null_args(void)
{
    struct cp_gpio18 s;
    uint32_t v = 0;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    CHECK(cp_gpio18_read(NULL, 0x00u, &v) == -1);
    CHECK(cp_gpio18_read(&s, 0x00u, NULL) == -1);
    CHECK(cp_gpio18_write(NULL, 0x00u, 0u) == -1);
    CHECK(cp_gpio18_write(NULL, 0x10u, 0u) == -1);
    CHECK(s.reads == 0 && s.writes == 0);
}

static void test_reinit_reset(void)
{
    struct cp_gpio18 s;
    uint32_t v;

    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    CHECK(cp_gpio18_write(&s, 0x40u, 0xffu) == 0);
    CHECK(cp_gpio18_write(&s, 0x38u, 0xfu) == 0);
    CHECK(cp_gpio18_write(&s, 0x00u, 0x0u) == 0);
    CHECK(cp_gpio18_read(&s, 0x40u, &v) == 0 && v == 0xffu);
    CHECK(cp_gpio18_init(&s, CP_GPIO18_PROFILE) == 0);
    /* back to the explicit loader state with clean counters */
    CHECK(s.dir == 0xfu && s.inen == 0xfu && s.portsel == 0xeu &&
          s.wdata == 0x2u);
    CHECK(s.reads == 0 && s.writes == 0);
}

int main(void)
{
    test_init_profile();
    test_failed_init_keeps_state();
    test_loader_state();
    test_reads_and_counters();
    test_unknown_reads();
    test_writes_set_clr_and_counters();
    test_unknown_writes();
    test_null_args();
    test_reinit_reset();

    if (failures != 0) {
        fprintf(stderr, "gpio18 self-test: %d/%d checks FAILED\n",
                failures, checks);
        return 1;
    }
    printf("gpio18 self-test: ALL %d CHECKS PASSED\n", checks);
    return 0;
}
