/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef A7C2_CP_TPU_H
#define A7C2_CP_TPU_H

#include <stdbool.h>
#include <stdint.h>

#define TPU_BANK_COUNT 6u
#define TPU_MMIO_SIZE 0x1000u
#define TPU_REGISTER_COUNT 14u

#define TPU_REG_STATUS 0x10u
#define TPU_REG_COUNTER 0x14u
#define TPU_REG_CLEAR 0x28u
#define TPU_REG_ENABLE 0x2cu

enum tpu_result {
    TPU_OK = 0,
    TPU_ERR_ACCESS = -1,
    TPU_ERR_GATED = -2,
    TPU_ERR_RUNTIME = -3,
};

struct tpu {
    /* Independent 16-bit slots at +00,+04,...,+34; +10 is read-only. */
    uint16_t regs[TPU_REGISTER_COUNT];
    bool clock_enabled;
    bool reset_held;
    /* Once enabled, status/count stay unknown until reset, even after stop. */
    bool runtime_unmodeled;
};

/* Explicit virtual all-zero state, not a claim about physical reset values.
 * Clock starts disabled; reset-held starts false. NULL is rejected. */
int tpu_init(struct tpu *s);

/* Aligned 4-byte-spaced, known 16-bit registers only. Errors leave output and
 * state untouched. +10 is zero only in stopped/no-activity virtual state;
 * +10/+14 reject active or previously active state until reset. */
int tpu_read(const struct tpu *s, uint32_t offset, uint16_t *out);
int tpu_write(struct tpu *s, uint32_t offset, uint16_t value);

/* MMIO requires clock-enabled and !reset-held. Clock changes preserve all
 * configuration; reset rising edge clears regs/runtime but preserves clock.
 * +2c.bit0 is the sole active/enable source; no timer/PWM/phase/IRQ engine.
 * +28 stores command/readback only and never clears unknown runtime state.
 * These setters reject NULL and otherwise return TPU_OK. */
int tpu_set_clock(struct tpu *s, bool enabled);
int tpu_set_reset(struct tpu *s, bool held);

/* QEMU adapter: a7c2-cp-tpu, uint32 bank property 0..5, one 0x1000 MMIO region.
 * GPIO inputs: "clock-enable"[0], "reset"[0], levels 0/1; no IRQ output.
 * Read sizes 2 or 4 (zero-extended low 16 bits); writes size 2 only.
 * All offsets must be 4-byte aligned. +38/+3c and other widths are rejected.
 * Parent owns mappings and SCU ch4 composition with watchdog bit18. */
#endif
