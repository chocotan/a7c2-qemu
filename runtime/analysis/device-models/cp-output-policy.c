/* SPDX-License-Identifier: MIT */
#include "cp-output-policy.h"
#include <errno.h>
#include <string.h>
#include <unistd.h>

static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static int ready(const struct cp_output_policy *owner) {
    if (!owner) return -EINVAL;
    if (!owner->enabled) return -EACCES;
    if (owner->owner_pid != getpid()) return -ECHILD;
    return 0;
}

static int separate(const struct cp_output_policy *owner,
                    const void *other, size_t size) {
    uintptr_t a = (uintptr_t)owner, b = (uintptr_t)other;
    if (!other || a > UINTPTR_MAX - sizeof(*owner) || b > UINTPTR_MAX - size)
        return -EINVAL;
    if (a < b + size && b < a + sizeof(*owner)) return -EINVAL;
    return 0;
}

int cp_output_policy_init(struct cp_output_policy *owner, bool enabled) {
    if (!owner) return -EINVAL;
    memset(owner, 0, sizeof(*owner));
    owner->owner_pid = getpid();
    owner->enabled = enabled;
    return 0;
}

int cp_output_policy_stage(struct cp_output_policy *owner, uint32_t source,
                           uint32_t target, const void *input, size_t size) {
    struct cp_output_policy_snapshot next = {0};
    const unsigned char *p = next.bytes;
    int rc = ready(owner);
    if (rc) return rc;
    if (source != CP_OUTPUT_POLICY_SOURCE || target != CP_OUTPUT_POLICY_TARGET)
        return -EPERM;
    if (size != CP_OUTPUT_POLICY_BYTES) return -EMSGSIZE;
    rc = separate(owner, input, size);
    if (rc) return rc;
    memcpy(next.bytes, input, size);
    if (p[0] != 5 || p[2] != 0xf9 || p[3] != 0x40) return -EPROTO;
    next.interval_rec_status = p[8];
    next.interval_rec_ae_smoothing = p[9];
    next.interval_rec_interval = le32(p + 12);
    next.interval_rec_shut_low_limit = le32(p + 16);
    next.known_mask = CP_OUTPUT_POLICY_KNOWN_MASK;
    next.config_consumed = true;
    /* shortcut: local setter only; original CP dirty-state consumers are absent. */
    owner->state = next;
    return CP_OUTPUT_POLICY_CONFIG_CONSUMED;
}

int cp_output_policy_snapshot(const struct cp_output_policy *owner,
                              uint32_t required_known_mask,
                              struct cp_output_policy_snapshot *output) {
    int rc = ready(owner);
    if (rc) return rc;
    rc = separate(owner, output, sizeof(*output));
    if (rc) return rc;
    if (required_known_mask & ~CP_OUTPUT_POLICY_KNOWN_MASK) return -ENOTSUP;
    if (!owner->state.config_consumed ||
        (owner->state.known_mask & required_known_mask) != required_known_mask)
        return -ENODATA;
    *output = owner->state;
    return 0;
}
