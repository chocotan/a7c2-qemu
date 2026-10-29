/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PARAMETER_STATE_H
#define NATIVE_CP_PARAMETER_STATE_H
#include "cp-parameter-batch.h"
#include "cp-parameter-import.h"

#define CP_PARAMETER_STATE_IMAGE_BYTES 0xd64u
#define CP_PARAMETER_STATE_KNOWN_BYTES ((CP_PARAMETER_STATE_IMAGE_BYTES + 7u) / 8u)
#define CP_PARAMETER_STATE_SOURCE_VA UINT32_C(0x0165a720)
#define CP_PARAMETER_STATE_OVERRIDE_MODE_OFFSET 0x1c8u
#define CP_PARAMETER_STATE_COMMON_LOCAL_BYTES 694u
#define CP_PARAMETER_STATE_DEFAULT_LOCAL_BYTES 2223u
#define CP_PARAMETER_STATE_INITIAL_LOCAL_KNOWN_BYTES 2913u
#define CP_PARAMETER_ZOOM_BYTES 12u
#define CP_PARAMETER_ZOOM_KNOWN_MASK UINT16_C(0x03ff)

/* CP354768 source-local readback, ordered drive/u32, speed/u8, trigger/u32,
 * movie speed/u8. Count/config consumption never imply optical application,
 * common APPLY, publication, generation advancement or native CP history. */
struct cp_parameter_zoom_readback {
    uint64_t count, source_sequence;
    enum cp_start_state_origin source_origin;
    uint32_t metadata_source, target, caller;
    unsigned char wire[CP_PARAMETER_ZOOM_BYTES], fields[10];
    uint16_t known_mask;
    unsigned char config_consumed;
};

/* Explicit caller-owned virtual parameter image P (165a720), never native RAM.
 * Every byte starts unknown; bytes are valid only where known_mask has a bit.
 * config_consumed: all source-local parameter writes for this slot executed.
 * semantic_complete: the source business algorithm, including business callees,
 * was modeled completely; proven debug-log calls are observational and omitted.
 * These masks are distinct. Neither staging nor partial consumption permits
 * ACK, generation advancement, state publication, ready or capture claims.
 * External serialization and immutable readable input spans are required. */
struct cp_parameter_state {
    uint32_t magic;
    struct cp_parameter_batch batch;
    unsigned char bytes[CP_PARAMETER_STATE_IMAGE_BYTES];
    unsigned char known_mask[CP_PARAMETER_STATE_KNOWN_BYTES];
    uint64_t config_consumed[CP_PARAMETER_BATCH_MASK_WORDS];
    uint64_t semantic_complete[CP_PARAMETER_BATCH_MASK_WORDS];
    unsigned char common_stores_consumed, default_stores_consumed;
    struct cp_parameter_zoom_readback zoom;
};
enum cp_parameter_state_result {
    CP_PARAMETER_STATE_PARTIAL = 1,
    CP_PARAMETER_STATE_COMPLETE = 2
};
int cp_parameter_state_init(struct cp_parameter_state *, bool enabled);
/* Execute only the source-closed STRD step at CP8db6d6: write zero to
 * P[1c8,1d0), once before any batch. This is local config consumption, not
 * completion of 8dc67e's business/notification callees or native publication.
 * init alone keeps every byte unknown; no other constructor defaults are used. */
int cp_parameter_state_consume_reset_store(struct cp_parameter_state *);
/* Source CP8db6a2..8db980: all 195 straight-line local-store instructions,
 * including seven zero helpers. Fresh unknown image only, before staging.
 * Does not execute the AE tail call or flag0 default initializer. The known
 * local bytes include the reset STRD; no business/publication mask advances. */
int cp_parameter_state_consume_common_stores(struct cp_parameter_state *);
/* CP8db9bc flag0 default writes and stack serializer. Requires the exact common
 * local image and an explicit same-stage import decision selecting defaults.
 * No holes are filled, no AE work executes, and semantic/publication masks do
 * not advance. One initial phase before a batch; repeat/non-common is rejected. */
int cp_parameter_state_consume_default_stores(struct cp_parameter_state *,
    const struct cp_parameter_import *);
/* Reuses the fixed 190-slot stager. Malformed/provenance/alias/stale errors
 * preserve the whole owner. One transaction per init; init discards old state.
 * Source paths requiring unknown old state remain unconsumed, not zero-filled.
 * The owned immutable wire copy is retained in batch.bytes for inspection. */
int cp_parameter_state_consume(struct cp_parameter_state *, uint32_t source,
    uint32_t target, const void *input, size_t size);
/* Exact standalone type5/4001, separate from the fixed 190-slot batch. Requires
 * this owner's consumed common/default stores and bulk4063, plus a same-PID,
 * quiescent even guard. Each write needs a strictly newer source sequence;
 * reads permit a later sequence of the same origin. Full u8 inputs survive.
 * All spans (owner/guard/input/output) must be readable, immutable, disjoint;
 * caller externally serializes the transaction. Errors preserve owner/output.
 * Success writes only ten image bytes/known bits, retains original wire/caller,
 * and reads all four ranges back before commit. No batch mask/wire is changed. */
int cp_parameter_state_consume_zoom(struct cp_parameter_state *,
    const struct cp_start_state_guard *, uint32_t metadata_source, uint32_t target,
    const void *input, size_t size, struct cp_parameter_zoom_readback *);
int cp_parameter_state_read_zoom(const struct cp_parameter_state *,
    const struct cp_start_state_guard *, struct cp_parameter_zoom_readback *);
/* All requested bytes must be known, otherwise -ENODATA and output unchanged.
 * Output must not overlap the owner. Empty/out-of-range reads are rejected. */
int cp_parameter_state_read(const struct cp_parameter_state *, size_t offset,
    void *output, size_t size);
#endif
