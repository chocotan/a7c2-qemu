/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Host self-test for cp_scu (profile virtual-cp-scu-i2c-v1).
 *
 * Build & run:
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
 *      scu.c test-scu.c -o test-scu && ./test-scu
 *
 * Covers: invalid profiles, failed init keeps state, all-zero virtual
 * reset, full 32-bit DATA writes on every mapped group, SET/CLR OR/AND~
 * semantics, write-only SET/CLR (reads reject), unknown/unaligned/past-
 * range offsets reject for read+write with sentinel *out and untouched
 * state, SRST group 4 (0x340/0x344/0x348) and 0x3a0 WDT_MISC rejection
 * with the watchdog-owned latch untouched, the original CP I2C0 bring-up
 * sequence (SET 0x54 bit18, then CLR 0x358 bit24), NULL args, re-init.
 */
#include "scu.h"

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
    struct cp_scu s;

    CHECK(cp_scu_init(NULL, CP_SCU_PROFILE) == -1);
    CHECK(cp_scu_init(&s, NULL) == -1);
    CHECK(cp_scu_init(&s, "") == -1);
    CHECK(cp_scu_init(&s, "virtual-cp-scu-i2c-v2") == -1);
    CHECK(cp_scu_init(&s, "virtual-cp-scu-i2c-v1x") == -1);
    CHECK(cp_scu_init(&s, "virtual-cp-scu-i2c-") == -1);
    CHECK(cp_scu_init(&s, "Virtual-cp-scu-i2c-v1") == -1);
    CHECK(cp_scu_init(&s, "virtual-gpio18-loader-state-v1") == -1);
    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
}

static void test_failed_init_keeps_state(void)
{
    struct cp_scu s;
    int i;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    for (i = 0; i < 9; i++) {
        s.clock[i] = 0x10000000u + (uint32_t)i;
    }
    for (i = 0; i < 6; i++) {
        s.reset[i] = 0x20000000u + (uint32_t)i;
    }
    CHECK(cp_scu_init(&s, "nope") == -1);
    CHECK(cp_scu_init(&s, NULL) == -1);
    for (i = 0; i < 9; i++) {
        CHECK(s.clock[i] == 0x10000000u + (uint32_t)i);
    }
    for (i = 0; i < 6; i++) {
        CHECK(s.reset[i] == 0x20000000u + (uint32_t)i);
    }
}

static void test_virtual_reset_zero(void)
{
    struct cp_scu s;
    int i;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    /* Declared virtual reset = all zero; NOT the Sony physical reset. */
    for (i = 0; i < 9; i++) {
        CHECK(s.clock[i] == 0u);
    }
    for (i = 0; i < 6; i++) {
        CHECK(s.reset[i] == 0u);
    }
}

/* DATA offsets of all 14 mapped groups: clock ch0..8 then SRST 0,1,2,3,5. */
static const uint32_t mapped_groups[14] = {
    0x00u, 0x10u, 0x20u, 0x30u, 0x40u, 0x50u, 0x60u, 0x70u, 0x80u,
    0x300u, 0x310u, 0x320u, 0x330u, 0x350u,
};

static void test_direct_32bit_writes_all_groups(void)
{
    struct cp_scu s;
    uint32_t v;
    size_t i;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    for (i = 0; i < 14; i++) {
        uint32_t pattern = 0x10001u * ((uint32_t)i + 1u);

        CHECK(cp_scu_write(&s, mapped_groups[i], pattern) == 0);
        CHECK(cp_scu_read(&s, mapped_groups[i], &v) == 0);
        CHECK(v == pattern); /* full 32-bit retention */
        CHECK(cp_scu_write(&s, mapped_groups[i], 0xffffffffu) == 0);
        CHECK(cp_scu_read(&s, mapped_groups[i], &v) == 0);
        CHECK(v == 0xffffffffu);
        CHECK(cp_scu_write(&s, mapped_groups[i], 0xdeadbeefu) == 0);
        CHECK(cp_scu_read(&s, mapped_groups[i], &v) == 0);
        CHECK(v == 0xdeadbeefu);
    }
    /* struct-level spot check of the bank mapping */
    CHECK(s.clock[0] == 0xdeadbeefu);
    CHECK(s.clock[8] == 0xdeadbeefu);
    CHECK(s.reset[0] == 0xdeadbeefu);
    CHECK(s.reset[3] == 0xdeadbeefu);
    CHECK(s.reset[5] == 0xdeadbeefu);
    CHECK(s.reset[4] == 0u); /* watchdog-owned latch never touched */
}

static void test_set_clr_semantics(void)
{
    struct cp_scu s;
    uint32_t v;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    /* SET only ORs and is idempotent */
    CHECK(cp_scu_write(&s, 0x54u, 1u << 18) == 0);
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == (1u << 18));
    CHECK(cp_scu_write(&s, 0x54u, 1u << 18) == 0);
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == (1u << 18));
    CHECK(cp_scu_write(&s, 0x54u, 0x10u) == 0);
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == ((1u << 18) | 0x10u));
    /* CLR only ANDs ~ and preserves unrelated bits */
    CHECK(cp_scu_write(&s, 0x58u, 0x10u) == 0);
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == (1u << 18));
    CHECK(cp_scu_write(&s, 0x58u, 0xffffffffu) == 0);
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == 0u);
    /* full 32-bit width via SET/CLR companions */
    CHECK(cp_scu_write(&s, 0x04u, 0xffffffffu) == 0);
    CHECK(cp_scu_read(&s, 0x00u, &v) == 0 && v == 0xffffffffu);
    CHECK(cp_scu_write(&s, 0x08u, 0x0f0f0f0fu) == 0);
    CHECK(cp_scu_read(&s, 0x00u, &v) == 0 && v == 0xf0f0f0f0u);
    /* same triple on an SRST group */
    CHECK(cp_scu_write(&s, 0x310u, 0xf0000000u) == 0);
    CHECK(cp_scu_write(&s, 0x314u, 0x0000000fu) == 0);
    CHECK(cp_scu_read(&s, 0x310u, &v) == 0 && v == 0xf000000fu);
    CHECK(cp_scu_write(&s, 0x318u, 0x0000000fu) == 0);
    CHECK(cp_scu_read(&s, 0x310u, &v) == 0 && v == 0xf0000000u);
}

static void test_i2c0_evidence_sequence(void)
{
    struct cp_scu s;
    uint32_t v;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    /* Original CP USER_TSK_DRV_INIT path (findings.json): SET CLK ch5
     * (CLKEN_SERIAL) bit 18 = I2C0 gate (STR 0xf1388054), then CLR SRST
     * ch5 bit 24 releases the I2C0 reset (GPL RST id 184 = ch5 bit24,
     * write 0xf1388358). Pure latch: no ready/IRQ/ACK is consumed. */
    CHECK(cp_scu_write(&s, 0x54u, 1u << 18) == 0);
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == (1u << 18));
    CHECK(cp_scu_write(&s, 0x350u, 1u << 24) == 0); /* bit24 held */
    CHECK(cp_scu_read(&s, 0x350u, &v) == 0 && v == (1u << 24));
    CHECK(cp_scu_write(&s, 0x358u, 1u << 24) == 0); /* release */
    CHECK(cp_scu_read(&s, 0x350u, &v) == 0 && v == 0u);
}

static void test_set_clr_reads_reject(void)
{
    struct cp_scu s;
    uint32_t v;
    size_t i;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    for (i = 0; i < 14; i++) {
        v = 0xfeedfaceu;
        CHECK(cp_scu_read(&s, mapped_groups[i] + 4u, &v) == -1);
        CHECK(v == 0xfeedfaceu); /* *out untouched on failure */
        v = 0xfeedfaceu;
        CHECK(cp_scu_read(&s, mapped_groups[i] + 8u, &v) == -1);
        CHECK(v == 0xfeedfaceu);
    }
}

/* Offsets that must fail for BOTH reads and writes. */
static const uint32_t bad_rw[] = {
    0x01u, 0x02u, 0x03u,             /* unaligned clock ch0 */
    0x41u, 0x42u,                    /* unaligned clock ch4 */
    0x0cu, 0x1cu, 0x8cu,             /* unknown sub-offset 0xc */
    0x90u, 0x94u, 0x98u,             /* past clock ch8 */
    0x100u, 0x290u, 0x2f0u,          /* far past clock range */
    0x301u, 0x305u, 0x349u, 0x351u,  /* unaligned SRST */
    0x30cu, 0x34cu, 0x35cu,          /* unknown sub-offset 0xc in SRST */
    0x340u, 0x344u, 0x348u,          /* SRST ch4: original watchdog */
    0x360u, 0x368u, 0x370u,          /* past SRST ch5 */
    0x3a0u, 0x3a4u, 0x3a8u,          /* WDT_MISC (watchdog) and beyond */
    0xffffffffu,                     /* wraparound */
};

static void test_unknown_reject(void)
{
    struct cp_scu s;
    uint32_t v;
    size_t i;
    int k;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    /* sentinels everywhere so rejection must leave state untouched */
    for (k = 0; k < 9; k++) {
        s.clock[k] = 0x10000000u + (uint32_t)k;
    }
    for (k = 0; k < 6; k++) {
        s.reset[k] = 0x20000000u + (uint32_t)k;
    }
    for (i = 0; i < sizeof(bad_rw) / sizeof(bad_rw[0]); i++) {
        v = 0xfeedfaceu;
        CHECK(cp_scu_read(&s, bad_rw[i], &v) == -1);
        CHECK(v == 0xfeedfaceu); /* *out untouched */
        CHECK(cp_scu_write(&s, bad_rw[i], 0xffffffffu) == -1);
    }
    for (k = 0; k < 9; k++) {
        CHECK(s.clock[k] == 0x10000000u + (uint32_t)k);
    }
    for (k = 0; k < 6; k++) {
        CHECK(s.reset[k] == 0x20000000u + (uint32_t)k);
    }
}

static void test_watchdog_group_and_wdt_misc_reject(void)
{
    struct cp_scu s;
    uint32_t v;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    s.reset[4] = 0xcafebeefu; /* sentinel in the unreachable latch */
    /* SRST group 4 DATA/SET/CLR: watchdog-owned, must never map */
    v = 0xfeedfaceu;
    CHECK(cp_scu_read(&s, 0x340u, &v) == -1);
    CHECK(v == 0xfeedfaceu);
    CHECK(cp_scu_write(&s, 0x340u, 0xffffffffu) == -1);
    CHECK(cp_scu_write(&s, 0x344u, 0xffffffffu) == -1);
    CHECK(cp_scu_write(&s, 0x348u, 0xffffffffu) == -1);
    CHECK(s.reset[4] == 0xcafebeefu); /* watchdog latch untouched */
    /* 0x3a0 WDT_MISC: original watchdog peripheral, not ours */
    v = 0xfeedfaceu;
    CHECK(cp_scu_read(&s, 0x3a0u, &v) == -1);
    CHECK(v == 0xfeedfaceu);
    CHECK(cp_scu_write(&s, 0x3a0u, 0xffffffffu) == -1);
    /* neighbors still work: SRST ch3 0x330 and ch5 0x350 */
    CHECK(cp_scu_write(&s, 0x330u, 0x33u) == 0);
    CHECK(cp_scu_read(&s, 0x330u, &v) == 0 && v == 0x33u);
    CHECK(cp_scu_write(&s, 0x350u, 0x55u) == 0);
    CHECK(cp_scu_read(&s, 0x350u, &v) == 0 && v == 0x55u);
    CHECK(s.reset[4] == 0xcafebeefu);
}

static void test_null_args(void)
{
    struct cp_scu s;
    uint32_t v = 0;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    CHECK(cp_scu_read(NULL, 0x00u, &v) == -1);
    CHECK(cp_scu_read(&s, 0x00u, NULL) == -1);
    CHECK(cp_scu_write(NULL, 0x00u, 0u) == -1);
    CHECK(cp_scu_write(NULL, 0x340u, 0u) == -1);
    CHECK(s.clock[0] == 0u && s.reset[5] == 0u && s.reset[4] == 0u);
}

static void test_reinit_reset(void)
{
    struct cp_scu s;
    uint32_t v;
    int i;

    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    CHECK(cp_scu_write(&s, 0x50u, 0xffffffffu) == 0);
    CHECK(cp_scu_write(&s, 0x350u, 0xffffffffu) == 0);
    s.reset[4] = 0x12345678u; /* poke the reserved latch directly */
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == 0xffffffffu);
    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    /* back to the declared all-zero virtual reset, incl. reserved ch4 */
    for (i = 0; i < 9; i++) {
        CHECK(s.clock[i] == 0u);
    }
    for (i = 0; i < 6; i++) {
        CHECK(s.reset[i] == 0u);
    }
    CHECK(cp_scu_read(&s, 0x50u, &v) == 0 && v == 0u);
}

static void test_cp_dfs_transactions(void)
{
    struct cp_scu s;
    uint32_t v = 0xdeadbeefu;
    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    CHECK(cp_scu_dfs_write(&s, 0, 0x101) == -1);
    CHECK(cp_scu_dfs_write(&s, 4, 0x101) == 0);
    CHECK(cp_scu_dfs_write(&s, 0, 0x101) == 0);
    CHECK(cp_scu_dfs_read(&s, 16, &v) == 0 && !(v & 0x100));
    CHECK(cp_scu_dfs_write(&s, 12, 0x106) == 0);
    CHECK(cp_scu_dfs_write(&s, 8, 1) == 0);
    CHECK(cp_scu_dfs_read(&s, 16, &v) == 0 && (v & 0x100));
    CHECK(cp_scu_dfs_write(&s, 0, 0x101) == 0);
    CHECK(cp_scu_dfs_write(&s, 12, 3) == -1);
    CHECK(cp_scu_dfs_complete(&s) == 1);
    CHECK(cp_scu_dfs_read(&s, 0, &v) == 0 && v == 0x101);
    CHECK(cp_scu_dfs_read(&s, 16, &v) == 0 && v == 6);
    CHECK(cp_scu_dfs_write(&s, 12, 3) == 0);
    CHECK(cp_scu_dfs_write(&s, 8, 1) == 0);
    CHECK(cp_scu_dfs_complete(&s) == 1);
    CHECK(cp_scu_dfs_read(&s, 0, &v) == 0 && v == 1);
    CHECK(cp_scu_dfs_read(&s, 16, &v) == 0 && v == 3);
    CHECK(cp_scu_dfs_write(&s, 0, 0x101) == 0);
    CHECK(cp_scu_dfs_write(&s, 12, 7) == -1);
    CHECK(cp_scu_dfs_write(&s, 12, 0x200) == -1);
    CHECK(cp_scu_dfs_write(&s, 8, 1) == -1);
    CHECK(cp_scu_dfs_read(&s, 3, &v) == -1);
    CHECK(cp_scu_dfs_write(&s, 20, 1) == -1);
    CHECK(cp_scu_init(&s, CP_SCU_PROFILE) == 0 && !s.dfs_initialized && !s.dfs_busy);
}

int main(void)
{
    test_init_profile();
    test_failed_init_keeps_state();
    test_virtual_reset_zero();
    test_direct_32bit_writes_all_groups();
    test_set_clr_semantics();
    test_i2c0_evidence_sequence();
    test_set_clr_reads_reject();
    test_unknown_reject();
    test_watchdog_group_and_wdt_misc_reject();
    test_null_args();
    test_reinit_reset();
    test_cp_dfs_transactions();

    if (failures != 0) {
        fprintf(stderr, "scu self-test: %d/%d checks FAILED\n",
                failures, checks);
        return 1;
    }
    printf("scu self-test: ALL %d CHECKS PASSED\n", checks);
    return 0;
}
