/* SPDX-License-Identifier: MIT */
#include "cp-output-policy.h"
#include <assert.h>
#include <errno.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* run-j1cbs2i1, original AP 258/TID381; supplied captured 20B request. */
static const unsigned char captured[CP_OUTPUT_POLICY_BYTES] = {
    0x05,0x00,0xf9,0x40,0x27,0x00,0x00,0x80,0,0,0,0,0,0,0,0,0,0,0,0
};

static int stage(struct cp_output_policy *o, const void *p, size_t n) {
    return cp_output_policy_stage(o, CP_OUTPUT_POLICY_SOURCE,
                                  CP_OUTPUT_POLICY_TARGET, p, n);
}

static void unchanged(const struct cp_output_policy *o,
                      const struct cp_output_policy *before) {
    assert(memcmp(o, before, sizeof(*o)) == 0);
}

static void local_only(const struct cp_output_policy_snapshot *s) {
    assert(s->config_consumed && s->known_mask == CP_OUTPUT_POLICY_KNOWN_MASK);
    assert(!s->semantic_applied && !s->published && !s->cp_native && !s->ee && !s->capture);
}

int main(void) {
    struct cp_output_policy owner, before;
    struct cp_output_policy_snapshot out, saved;
    unsigned char unaligned[CP_OUTPUT_POLICY_BYTES + 1], *p = unaligned + 1;
    int status;
    pid_t child;
    assert(cp_output_policy_init(NULL, true) == -EINVAL);
    assert(cp_output_policy_init(&owner, true) == 0);
    assert(owner.state.known_mask == 0 && !owner.state.config_consumed);
    memset(&out, 0xa5, sizeof(out));
    memcpy(&saved, &out, sizeof(saved));
    assert(cp_output_policy_snapshot(&owner, 0, &out) == -ENODATA);
    assert(memcmp(&out, &saved, sizeof(out)) == 0);
    assert(stage(&owner, captured, sizeof(captured)) == CP_OUTPUT_POLICY_CONFIG_CONSUMED);
    assert(cp_output_policy_snapshot(&owner, CP_OUTPUT_POLICY_KNOWN_MASK, &out) == 0);
    local_only(&out);
    assert(!out.interval_rec_status && !out.interval_rec_ae_smoothing);
    assert(!out.interval_rec_interval && !out.interval_rec_shut_low_limit);
    assert(memcmp(out.bytes, captured, sizeof(captured)) == 0);

    /* Host counterexample: source byte fields are not three u32 payloads. */
    memcpy(p, captured, sizeof(captured));
    p[1] = 0x7f; p[4] = 0x8e; p[7] = 0xf1;
    p[8] = 0xfe; p[9] = 0xab; p[10] = 0x8a; p[11] = 0x77;
    p[12] = 0x78; p[13] = 0x56; p[14] = 0x34; p[15] = 0x12;
    p[16] = 0xff; p[17] = 0xff; p[18] = 0xff; p[19] = 0x80;
    assert(stage(&owner, p, CP_OUTPUT_POLICY_BYTES) == CP_OUTPUT_POLICY_CONFIG_CONSUMED);
    assert(cp_output_policy_snapshot(&owner, CP_OUTPUT_POLICY_STATUS_KNOWN, &out) == 0);
    local_only(&out);
    assert(out.interval_rec_status == 0xfe && out.interval_rec_ae_smoothing == 0xab);
    assert(out.interval_rec_interval == UINT32_C(0x12345678));
    assert(out.interval_rec_shut_low_limit == UINT32_C(0x80ffffff));
    assert(memcmp(out.bytes, p, CP_OUTPUT_POLICY_BYTES) == 0);
    memset(p, 0, CP_OUTPUT_POLICY_BYTES);
    assert(memcmp(owner.state.bytes, out.bytes, CP_OUTPUT_POLICY_BYTES) == 0);
    memcpy(&before, &owner, sizeof(before));
    memcpy(p, captured, sizeof(captured));

    assert(cp_output_policy_stage(&owner, CP_OUTPUT_POLICY_SOURCE ^ 1,
        CP_OUTPUT_POLICY_TARGET, p, CP_OUTPUT_POLICY_BYTES) == -EPERM);
    unchanged(&owner, &before);
    assert(cp_output_policy_stage(&owner, CP_OUTPUT_POLICY_SOURCE,
        CP_OUTPUT_POLICY_TARGET ^ 1, p, CP_OUTPUT_POLICY_BYTES) == -EPERM);
    unchanged(&owner, &before);
    for (size_t n = 0; n < CP_OUTPUT_POLICY_BYTES; n++) {
        assert(stage(&owner, p, n) == -EMSGSIZE);
        unchanged(&owner, &before);
    }
    assert(stage(&owner, p, CP_OUTPUT_POLICY_BYTES + 1) == -EMSGSIZE);
    assert(stage(&owner, p, SIZE_MAX) == -EMSGSIZE);
    unchanged(&owner, &before);
    p[0] = 1;
    assert(stage(&owner, p, CP_OUTPUT_POLICY_BYTES) == -EPROTO);
    unchanged(&owner, &before);
    p[0] = 5; p[2] ^= 1;
    assert(stage(&owner, p, CP_OUTPUT_POLICY_BYTES) == -EPROTO);
    unchanged(&owner, &before);
    p[2] ^= 1; p[3] ^= 1;
    assert(stage(&owner, p, CP_OUTPUT_POLICY_BYTES) == -EPROTO);
    unchanged(&owner, &before);
    assert(stage(&owner, &owner, CP_OUTPUT_POLICY_BYTES) == -EINVAL);
    assert(stage(&owner, owner.state.bytes, CP_OUTPUT_POLICY_BYTES) == -EINVAL);
    assert(stage(&owner, (void *)(UINTPTR_MAX - 1), CP_OUTPUT_POLICY_BYTES) == -EINVAL);
    assert(stage(&owner, NULL, CP_OUTPUT_POLICY_BYTES) == -EINVAL);
    unchanged(&owner, &before);
    assert(cp_output_policy_snapshot(&owner, 0, &owner.state) == -EINVAL);
    assert(cp_output_policy_snapshot(&owner, 0, NULL) == -EINVAL);
    assert(cp_output_policy_snapshot(&owner, 0,
        (struct cp_output_policy_snapshot *)(UINTPTR_MAX - 1)) == -EINVAL);
    unchanged(&owner, &before);
    memcpy(&saved, &out, sizeof(saved));
    assert(cp_output_policy_snapshot(&owner, UINT32_C(0x10), &out) == -ENOTSUP);
    assert(cp_output_policy_snapshot(&owner, UINT32_MAX, &out) == -ENOTSUP);
    assert(memcmp(&out, &saved, sizeof(out)) == 0);
    unchanged(&owner, &before);
    assert(stage(NULL, captured, sizeof(captured)) == -EINVAL);
    assert(cp_output_policy_snapshot(NULL, 0, &out) == -EINVAL);

    child = fork();
    assert(child >= 0);
    if (!child) {
        assert(stage(&owner, captured, sizeof(captured)) == -ECHILD);
        assert(cp_output_policy_snapshot(&owner, 0, &out) == -ECHILD);
        unchanged(&owner, &before);
        assert(cp_output_policy_init(&owner, true) == 0);
        assert(stage(&owner, captured, sizeof(captured)) == CP_OUTPUT_POLICY_CONFIG_CONSUMED);
        _exit(0);
    }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    unchanged(&owner, &before);
    assert(cp_output_policy_init(&owner, false) == 0);
    memcpy(&before, &owner, sizeof(before));
    assert(stage(&owner, captured, sizeof(captured)) == -EACCES);
    assert(cp_output_policy_snapshot(&owner, 0, &out) == -EACCES);
    unchanged(&owner, &before);
    memset(&owner, 0, sizeof(owner));
    assert(stage(&owner, captured, sizeof(captured)) == -EACCES);
    return 0;
}
