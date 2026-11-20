/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * cp_scu: bounded functional model of the CP-side SCU clock-gate and
 * soft-reset (SRST) register banks for the virtual CP boot path.
 * Profile: virtual-cp-scu-i2c-v1.
 *
 * Layout follows the public same-SoC kernel headers: regs-scu.h triple
 * (SCU_DATA +0x00 / SCU_SET +0x04 / SCU_CLR +0x08), regs-clk.h channels
 * 0..8 (groups 0x000..0x080, step 0x10) and regs-srst.h channels 0..5
 * (groups 0x300..0x350, step 0x10). Evidence:
 * analysis/scratch/cp-wait-20261111/scu-first-write-review/findings.json
 * (first CP write = STR 0xf1388054 = CLK ch5 SET bit 18, CLKEN_SERIAL
 * I2C0 gate; then CLR 0xf1388358 = SRST ch5 CLR bit 24 releases I2C0).
 */
#ifndef CP_SCU_H
#define CP_SCU_H

#include <stdint.h>

#define CP_SCU_PROFILE "virtual-cp-scu-i2c-v1"

struct cp_scu {
    uint32_t clock[9]; /* CLK ch0..8 DATA latches (groups 0x000..0x080) */
    uint32_t dfs_request, dfs_init, dfs_trigger, dfs_target, dfs_status;
    uint32_t dfs_mode;
    unsigned dfs_initialized, dfs_prepared, dfs_latched, dfs_busy;
    uint32_t reset[6]; /* SRST ch0..5 DATA latches (groups 0x300..0x350);
                        * reset[4] is unreachable by design: the original
                        * watchdog owns SRST group 4 and this model must
                        * never shadow it. */
};

/*
 * Initialize s to the declared virtual reset: all latches zero. This is a
 * functional initial state, NOT a measured Sony physical reset value; no
 * physical reset polarity, clock tree or calibration is claimed. Rejects
 * NULL s, NULL or unknown profile (s untouched). Returns 0 on success,
 * -1 on error.
 */
int cp_scu_init(struct cp_scu *s, const char *profile);

/*
 * Read a DATA register (group base: clock 0x00..0x80, SRST
 * 0x300..0x330 and 0x350). SET (+4) and CLR (+8) are write-only
 * companions: reads there fail. SRST group 4 (0x340/0x344/0x348) always
 * fails: the original watchdog owns that group with real semantics and
 * this model must not shadow it; 0x3a0 (WDT_MISC) likewise fails.
 * Only aligned4 accesses are valid. Returns 0 on success; on any failure
 * (-1, incl. NULL args, unknown/unaligned offsets) *out and state are
 * untouched. Reads never clear, set or acknowledge anything; there is no
 * clock-ready/ACK concept in this model.
 */
int cp_scu_read(struct cp_scu *s, uint32_t offset, uint32_t *out);

/*
 * Write a register: DATA (+0) assigns the full 32-bit value, SET (+4)
 * ORs, CLR (+8) ANDs with the complement. Same exclusions as read: SRST
 * group 4 and 0x3a0 fail; unknown and unaligned offsets fail and leave
 * state untouched. The model is pure storage: it gates no real device
 * clock and asserts no reset line (physical clock-tree/calibration is
 * unproven); downstream QEMU devices are wired at board level, not here.
 * Returns 0 on success, -1 on error.
 */
int cp_scu_write(struct cp_scu *s, uint32_t offset, uint32_t value);

/* CP-only virtual DFS selector at SCU+0xf48. No physical clocks or IRQs. */
int cp_scu_dfs_read(struct cp_scu *s, uint32_t offset, uint32_t *out);
int cp_scu_dfs_write(struct cp_scu *s, uint32_t offset, uint32_t value);
int cp_scu_dfs_complete(struct cp_scu *s);

#endif /* CP_SCU_H */
