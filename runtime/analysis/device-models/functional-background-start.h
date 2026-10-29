/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_BACKGROUND_START_H
#define FUNCTIONAL_BACKGROUND_START_H
#include <errno.h>
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"

#define FUNCTIONAL_BACKGROUND_START_SID NATIVE_CP_STATE_PUBLICATION_SID
#define FUNCTIONAL_BACKGROUND_START_REQUEST_BYTES 24u
#define FUNCTIONAL_BACKGROUND_START_REPLY_BYTES 12u
#define FUNCTIONAL_BACKGROUND_START_LEASES 2u
#define FUNCTIONAL_BACKGROUND_START_BLOCKED (-ENODATA)

enum functional_background_start_phase {
    FUNCTIONAL_BACKGROUND_START_IDLE = 0,
    FUNCTIONAL_BACKGROUND_START_PENDING,
    FUNCTIONAL_BACKGROUND_START_PROBING,
    FUNCTIONAL_BACKGROUND_START_MODEL_COMPLETE,
    FUNCTIONAL_BACKGROUND_START_REPLY_QUEUED,
    FUNCTIONAL_BACKGROUND_START_REPLY_RECEIVED,
    FUNCTIONAL_BACKGROUND_START_AP_CONSUMED,
    FUNCTIONAL_BACKGROUND_START_FAULT
};
struct functional_background_start_snapshot {
    int owner_pid;
    unsigned int initialized, functional_model, bound, bound_source, phase;
    unsigned int requests, completed_cycles, pending, working, guard_held, faults;
    unsigned int init_called, state_called, probe_successes, state_copied, readback_verified;
    unsigned int functional_core_initialized, model_complete, original_request_freed;
    unsigned int reply_queued, reply_received, reply_retained, live_leases;
    unsigned int transport_complete, ap_consumed, allocation_alias;
    unsigned int source_physical_verified, original_cp_rtos_verified, cp_modules_verified;
    unsigned int original_masks_verified, business_published, hardware_ready, image_ready, capture_verified;
    int error, reserve_rc, predecessor_rc, init_rc, state_rc, validation_rc;
    long sender_tid, producer_tid, receiver_tid;
    uint64_t cycle, receive_ticket, free_ticket, model_instance, config_generation, frame_generation;
    uint64_t rendered, consumed, jpeg_encoded, video_encoded, result_bytes_read;
    uint64_t init_fnv1a64, state_fnv1a64, cache_fnv1a64, readback_fnv1a64;
    struct fcam_native_origin origin;
    struct fcam_bridge_result init_result, state_result;
    unsigned char original_wire[FUNCTIONAL_BACKGROUND_START_REQUEST_BYTES];
    unsigned char reply_wire[FUNCTIONAL_BACKGROUND_START_REPLY_BYTES];
    unsigned char init_state[FCAM_STATE_BYTES], actual_state[FCAM_STATE_BYTES];
    unsigned char model_state[FCAM_STATE_BYTES], copied_readback[FCAM_STATE_BYTES];
    void *allocation_returned;
    struct native_cp_state_publication_lease leases[FUNCTIONAL_BACKGROUND_START_LEASES];
};
/* Process-local setup only; no RPC or device initialization. Explicit profile
 * enabled==1 only. Parent verifies libObj eda50, original BL bytes/same base and
 * actual osal_dynamic_id(2a,102) source before binding/dispatch. This owner does
 * not establish caller provenance. Source is dynamic, never a fixed queue ID.
 * Binding the same nonzero/non-SID/non-UINT_MAX source is idempotent. A new
 * source requires the previous cycle's actual AP-consumption and all leases,
 * pending work and guard fully retired; otherwise it is -ESTALE. An inherited
 * owner rejects before taking its mutex. */
int functional_background_start_owner_init(void);
int functional_background_start_bind_source_once(unsigned int source);
/* Unrelated/disabled requests return0 unchanged. Matching malformed/unbound/
 * busy/faulted requests return1/result<0, caller-owned. Accepted result0 means
 * one immutable pending original request is retained, with no ACK/completion.
 * Acceptance calls progress once; predecessor_ready==0 leaves it pending and
 * performs no bridge operation. IO/guard callbacks are copied for later use.
 * Every callback, including logger and guard, runs outside the private mutex. */
int functional_background_start_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    int enabled, int *result);
/* Parent calls after its same-run last13 ORIGINAL free0 (and on an accepted
 * request whose complete actual predecessor snapshot is already ready).
 * predecessor_ready==0 (or -ENODATA) returns before reserve, hence before any
 * parent mailbox setup. reserve -> rechecked actual predecessor_ready must
 * precede synchronous INIT128/STATE128;
 * parent bridge transport waits for its actual HDMI debugger handoff. No timer,
 * worker, synthetic ready flag or RPC in owner_init. Both probes must agree in
 * every byte/instance and their complete State128 is independently cached and
 * read back. Original request is really freed before allocating a distinct
 * 12B type1/3006/opaque+4/F000 reply. Returns0 if idle/pending/inflight, 1 after
 * successful send (still not AP-consumed), negative errno on a sticky fault.
 * Accepted ownership persists across faults; progress never retries failed IO.
 * The progressing thread is the bridge producer, separate from original sender.
 */
int functional_background_start_progress(void);
void functional_background_start_snapshot(struct functional_background_start_snapshot *);
/* Call ONLY after actual successful original rcv, capturing immutable *ticket
 * in receiver TLS. Complete body/source/length and ORIGINAL sender TID must
 * match. Release uses that ticket, never a snapshot refreshed at free. Real
 * free0 on that sender/receiver plus send0 alone establishes AP consumption.
 * Inline receive/free during send is allowed. Failed free retains its lease,
 * is sticky and is never retried. Retired addresses do not own fresh messages;
 * explicit old tickets reject stale events without touching real_free.
 */
int functional_background_start_observe_receive_cycle(unsigned int destination,
    void *pointer, unsigned int source, unsigned int bytes, uint64_t *ticket);
int functional_background_start_release_cycle(unsigned int destination, void *pointer,
    uint64_t ticket, int (*real_free)(unsigned int, void *),
    void (*record)(const char *, const char *), int *result);
#ifdef HOST_TEST
void functional_background_start_test_hold_lock(void);
void functional_background_start_test_drop_lock(void);
void *functional_background_start_test_snapshot_address(void);
#endif
#endif
