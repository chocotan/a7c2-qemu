/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_SLOT1_PUBLICATION_H
#define NATIVE_CP_SLOT1_PUBLICATION_H
#include <stddef.h>
#include <stdint.h>

#define CP_SLOT1_BANK_BYTES 0x210u
#define CP_SLOT1_ROOT_BYTES 0xe18u
#define CP_SLOT1_RECORD_BYTES 0xc0cu
#define CP_SLOT1_SNAPSHOT_BYTES (CP_SLOT1_ROOT_BYTES + CP_SLOT1_RECORD_BYTES)
struct cp_slot1_publication;
enum cp_slot1_stage {
    CP_SLOT1_IDLE, CP_SLOT1_QUEUED, CP_SLOT1_EXECUTING,
    CP_SLOT1_BLOCKED_PREFIX, CP_SLOT1_BLOCKED_POST
};
struct cp_slot1_view {
    uint64_t work, bank_work[2], completed_work;
    unsigned int input_mode, derived_mode, busy, stage, selector, alias;
    unsigned int requested, observed, observation_current, callbacks;
};
/* Both functions are REQUIRED. They must consume the owned snapshot and
 * implement the real admitted prefix/postwork (including conditional IPC).
 * There is deliberately no default success implementation. The span covers
 * only the two proven copied ranges, NOT all root/context/pointer metadata.
 * Callbacks may inspect this component, but must not retain the span or destroy
 * it. One writer per instance; destruction additionally requires quiescence. */
struct cp_slot1_effects {
    int (*prefix)(void *, const unsigned char *, size_t);
    int (*postwork)(void *, const unsigned char *, size_t);
};
struct cp_slot1_publication *cp_slot1_create(unsigned int input_mode,
    const unsigned char banks[2 * CP_SLOT1_BANK_BYTES]);
int cp_slot1_destroy(struct cp_slot1_publication *);
/* Periodic input->M mapping, not a forced M value. Updates are refused while
 * work is outstanding. Only the original input-I=3 profile is admitted. */
int cp_slot1_set_input_mode(struct cp_slot1_publication *, unsigned int);
/* Copy the distinct original root and record ranges into one owned queue slot.
 * This is NOT the full N/D context model and never acknowledges a CP command. */
int cp_slot1_enqueue(struct cp_slot1_publication *, const void *root, size_t,
    const void *record, size_t);
int cp_slot1_execute(struct cp_slot1_publication *, const struct cp_slot1_effects *, void *);
/* Explicit failed-work cleanup, equivalent only to module1 occupancy cleanup.
 * It does not establish postwork success, observation, or a CP completion. */
int cp_slot1_abort(struct cp_slot1_publication *);
/* Owned alias arithmetic for the two identified refresh gates. Caller must
 * establish the separate event/receipt prerequisites before using this helper.
 * It does not change any original guest pointer or sequencer returned value. */
int cp_slot1_refresh(struct cp_slot1_publication *, unsigned int root_enabled,
    unsigned int query_result);
int cp_slot1_snapshot(struct cp_slot1_publication *, struct cp_slot1_view *);
int cp_slot1_read_banks(struct cp_slot1_publication *, unsigned char *, size_t);
#endif
