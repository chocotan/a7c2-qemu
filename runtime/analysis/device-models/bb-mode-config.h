/* SPDX-License-Identifier: MIT */
#ifndef FULL_BB_MODE_CONFIG_H
#define FULL_BB_MODE_CONFIG_H
#include <stddef.h>
#include <stdint.h>

#define FULL_BB_MODE_CONFIG_BYTES 1760U
#define FULL_BB_MODE_CONFIG_INITIAL_KNOWN 1565U
/* Provenance tokens only: these integers are never dereferenced as host/guest pointers. */
#define FULL_BB_MODE_CONFIG_LIVE_TOKEN UINT32_C(0x01ff34c8)
#define FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN UINT32_C(0x01ff2cc8)
#define FULL_BB_MODE_CONFIG_SAVED_TOKEN UINT32_C(0x017890fc)

struct full_bb_mode_config_view {
    const struct full_bb_mode_config_view *identity;
    uint32_t token;
    uint64_t serial, source_epoch, data_fnv, known_fnv;
    unsigned char bytes[FULL_BB_MODE_CONFIG_BYTES];
    unsigned char known[FULL_BB_MODE_CONFIG_BYTES];
};
struct full_bb_mode_config {
    const struct full_bb_mode_config *identity;
    unsigned int initialized, fault, busy;
    uint64_t epoch, invalidated_epoch, panel_updates, mode_updates, saves, copies;
    uint64_t mode_epoch, saved_mode_epoch;
    uint32_t saved_operation_mode;
    unsigned int saved_valid;
    struct full_bb_mode_config_view live, snapshot;
    uint64_t seal;
};
/* The parent holds its common reservation and serializes ALL access. Snapshot
 * acquires/releases that parent's actual source sem5 through these hooks. A
 * failed lock acquired nothing; failed unlock leaves ownership for the parent
 * to diagnose. No new mutex/clock/transport or borrowed-lock claim is made. */
struct full_bb_mode_config_sem5 {
    void *context;
    int (*lock)(void *);
    int (*unlock)(void *);
};
/* Init once on zero storage; never reset/reinitialize/copy a live or faulted owner.
 * Explicit source stores only; this projection does not execute CP initialization. */
int full_bb_mode_config_init(struct full_bb_mode_config *);
/* Before an unmodeled BB configuration producer, invalidate semantic knowledge.
 * Physical live/snapshot bytes and initializer/update history remain intact. */
int full_bb_mode_config_invalidate(struct full_bb_mode_config *);
int full_bb_mode_config_apply0118(struct full_bb_mode_config *, const void *, size_t);
int full_bb_mode_config_apply0110(struct full_bb_mode_config *, const void *, size_t);
/* Requires a fresh, actual apply0110 since invalidation/last save; never ctor op0. */
int full_bb_mode_config_save_operation_mode(struct full_bb_mode_config *);
int full_bb_mode_config_saved_operation_mode(struct full_bb_mode_config *, uint32_t *);
int full_bb_mode_config_snapshot(struct full_bb_mode_config *,
                                 const struct full_bb_mode_config_sem5 *);
/* Unknown/range/alias refusals leave output untouched and do not fault the owner.
 * Copied/tampered/reentrant owners and malformed writes latch a permanent fault. */
int full_bb_mode_config_read(struct full_bb_mode_config *, uint32_t token,
                             size_t offset, void *, size_t);
/* Borrowed const projection, valid only under parent serialization, holding no
 * lock after return. Contains the entire known mask; opaque copy is not semantic
 * consumption. A saved op0 does not prove BB state1, target3, frames or capture. */
const struct full_bb_mode_config_view *full_bb_mode_config_view(
    struct full_bb_mode_config *, uint32_t token);
#endif
