/* SPDX-License-Identifier: MIT */
#ifndef FULL_BB_TIMECODE_CONTROL_H
#define FULL_BB_TIMECODE_CONTROL_H

#include "imaging-device.h"

#define FULL_BB_TIMECODE_CONTROL_PROFILE "virtual-bb-timecode-controls-v1"
#define FULL_BB_TIMECODE_CONTROL_CP 0x92840747u

struct full_bb_timecode_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessors_ready)(void);
};

/* Host diagnostic snapshot; not a wire layout. The separate 48-byte state ABI
 * is documented in INTERFACE.md. Zero known_mask means no observed input. */
struct full_bb_timecode_snapshot {
    int owner_pid;
    unsigned int initialized, busy, faults, guard_held;
    uint64_t transaction, generation, requests, applications;
    unsigned int known_mask, tcmode, dfmode, run;
    uint64_t command_generations[3];
    uint64_t input_fnv, state_fnv, reply_fnv;
    unsigned int sender_tid, receiver_tid, command, source;
    unsigned int queued, request_freed, reply_received, reply_freed, ap_consumed;
    int allocate_rc, send_rc, request_free_rc, reply_free_rc, cleanup_rc;
    uint64_t request_free_count, reply_free_count, busy_count, guard_failures;
    void *retained_request, *live_reply, *retained_reply, *retained_cleanup;
    unsigned int inflight, pending_commit;
    /* Append-only host diagnostics; the original State48 remains unchanged. */
    uint64_t preset_generation;
    unsigned int preset_known_mask, preset_raw4, ubmode_wire;
    uint64_t preset_command_generations[2], preset_applications;
};

/* Once per process; repeat initialization returns -EALREADY without resetting.
 * All callbacks (including record and guards) run outside the private mutex. */
int full_bb_timecode_control_owner_init(void);
/* Handled errors return 1 and store a negative errno/original callback error.
 * Before the marked ownership transfer, the caller still owns the request.
 * After transfer, inspect snapshot even on failure: no retry or double free. */
int full_bb_timecode_control_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct full_bb_timecode_guard *, int, int *);
/* Call after actual allocator return. A real rc0/count1/non-NULL allocation
 * retires ONLY a fully freed, quiescent historical identity at that address.
 * Returns 1 if retired, 0 unrelated/ineligible, negative for PID/live alias.
 * A live/retained alias must be refused by the caller, never freed as new. */
int full_bb_timecode_control_observe_allocate(unsigned int, void *, unsigned int, unsigned int, int);
/* Main calls this only AFTER a successful real receive, with actual metadata. */
int full_bb_timecode_control_observe_receive(unsigned int, void *, unsigned int, unsigned int);
/* This wraps the actual free; same original-sender/receiver TID is mandatory. */
int full_bb_timecode_control_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *);
void full_bb_timecode_control_snapshot(struct full_bb_timecode_snapshot *);

#endif
