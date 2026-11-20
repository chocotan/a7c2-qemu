/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Configuration-only TPU/PWM/phase model; no running timer or event engine. */
#include "tpu.h"

#include <stddef.h>
#include <string.h>

static bool valid_offset(uint32_t offset)
{
    return !(offset & 3u) && offset / 4u < TPU_REGISTER_COUNT;
}

static bool active(const struct tpu *s)
{
    return (s->regs[TPU_REG_ENABLE / 4u] & 1u) != 0;
}

int tpu_init(struct tpu *s)
{
    if (s == NULL) {
        return TPU_ERR_ACCESS;
    }
    memset(s, 0, sizeof(*s));
    return TPU_OK;
}

int tpu_read(const struct tpu *s, uint32_t offset, uint16_t *out)
{
    if (s == NULL || out == NULL || !valid_offset(offset)) {
        return TPU_ERR_ACCESS;
    }
    if (!s->clock_enabled || s->reset_held) {
        return TPU_ERR_GATED;
    }
    if ((offset == TPU_REG_STATUS || offset == TPU_REG_COUNTER) &&
        (active(s) || s->runtime_unmodeled)) {
        return TPU_ERR_RUNTIME;
    }
    *out = offset == TPU_REG_STATUS ? 0 : s->regs[offset / 4u];
    return TPU_OK;
}

int tpu_write(struct tpu *s, uint32_t offset, uint16_t value)
{
    if (s == NULL || !valid_offset(offset) || offset == TPU_REG_STATUS) {
        return TPU_ERR_ACCESS;
    }
    if (!s->clock_enabled || s->reset_held) {
        return TPU_ERR_GATED;
    }
    if (offset == TPU_REG_COUNTER && active(s)) {
        return TPU_ERR_RUNTIME;
    }
    s->regs[offset / 4u] = value;
    if (offset == TPU_REG_ENABLE && active(s)) {
        s->runtime_unmodeled = true;
    }
    /* +28 preserves only the command; no unproved W1C or event side effects. */
    return TPU_OK;
}

int tpu_set_clock(struct tpu *s, bool enabled)
{
    if (s == NULL) {
        return TPU_ERR_ACCESS;
    }
    s->clock_enabled = enabled;
    return TPU_OK;
}

int tpu_set_reset(struct tpu *s, bool held)
{
    if (s == NULL) {
        return TPU_ERR_ACCESS;
    }
    if (held && !s->reset_held) {
        memset(s->regs, 0, sizeof(s->regs));
        s->runtime_unmodeled = false;
    }
    s->reset_held = held;
    return TPU_OK;
}
