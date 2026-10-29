/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AVIO_OUTPUT_H
#define FULL_ADF_AVIO_OUTPUT_H

#define FULL_ADF_AVIO_JOBS 60u
#define FULL_ADF_AVIO_SHADOW_BYTES 0x70u
#define FULL_ADF_AVIO_BITMAP_BYTES 0x18u

struct full_adf_avio_output;
typedef void (*full_adf_avio_listener)(void *, unsigned int);
typedef void (*full_adf_avio_completion)(struct full_adf_avio_output *, unsigned int);
struct full_adf_avio_snapshot {
    unsigned char shadow[FULL_ADF_AVIO_SHADOW_BYTES];
    unsigned char changed[FULL_ADF_AVIO_BITMAP_BYTES];
    unsigned char touched[FULL_ADF_AVIO_BITMAP_BYTES];
};
struct full_adf_avio_job {
    unsigned int active, type, stage, target, change_mask;
    unsigned long long generation, opaque_lease;
    unsigned int original_callback; /* CP provenance only; callback is always local C. */
    full_adf_avio_completion callback;
};
/* Owned virtual snapshots, never original CP RAM/BSS or external DMM memory.
 * Caller serializes access; a callback may inspect state but must not mutate it.
 * output_finished records this output transaction only, and requires fault==0.
 * queued/consumed/events/callback_calls are cumulative; stage_counts and leaf
 * writes retain the original three-stage history during the same-mask NoOp. */
struct full_adf_avio_output {
    unsigned int known, fault, sync_flag, public_source, source_cache;
    unsigned int current_mask, requested_mask, read_index, write_index, count;
    unsigned int pending_events, queued, consumed, vsync_events, stage_counts[3];
    unsigned int shadow_writes, changed_writes, touched_writes;
    unsigned int callback_running, callback_calls, output_finished;
    unsigned long long generation, last_event;
    full_adf_avio_listener listener;
    void *context;
    struct full_adf_avio_snapshot initial, snapshot;
    struct full_adf_avio_job jobs[FULL_ADF_AVIO_JOBS];
    /* Only generation2: Output+c is stored then cleared before enqueue returns. */
    struct {
        unsigned int enqueued, cache_stores, cache_clears;
        full_adf_avio_listener cache_callback;
    } same;
};
/* Zero storage before construction; invalid construction leaves it unchanged.
 * The parent must validate public_source against the public seed. */
int full_adf_avio_output_init(struct full_adf_avio_output *,
                             const unsigned char shadow[FULL_ADF_AVIO_SHADOW_BYTES],
                             const unsigned char changed[FULL_ADF_AVIO_BITMAP_BYTES],
                             const unsigned char touched[FULL_ADF_AVIO_BITMAP_BYTES],
                             unsigned int public_source);
/* First generation1, target bit3 only. */
int full_adf_avio_output_enqueue(struct full_adf_avio_output *, unsigned long long generation,
                                unsigned int target, full_adf_avio_listener, void *context);
/* Pure control3 read of validated completed generation1 or its generation2 continuation.
 * On failure neither the owner nor either output changes. The cache is not the queued listener. */
int full_adf_avio_output_control3(const struct full_adf_avio_output *, unsigned int *mask,
                                  full_adf_avio_listener *cache_callback);
/* Same owner/ring, generation2 target8 only, after all three original stages.
 * Caller proves power20/power22 came from its same source-owned Power owner.
 * Zero Power values and sync_flag0 enqueue one NoOp, never synchronous completion. */
int full_adf_avio_output_enqueue_same(struct full_adf_avio_output *, unsigned long long generation,
                                     unsigned int target, unsigned int power20, unsigned int power22,
                                     full_adf_avio_listener, void *context);
/* Consume one stage per next event (generation1: 1,2,3; generation2: global event9).
 * Output generation2 is independent of the caller's clock generation.
 * No clock/event source, AIP work, global Idle completion or transport reply. */
int full_adf_avio_output_consume_vsync(struct full_adf_avio_output *,
                                      unsigned long long generation,
                                      unsigned long long event_sequence);
#endif
