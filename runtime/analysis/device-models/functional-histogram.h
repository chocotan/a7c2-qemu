/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_HISTOGRAM_H
#define FUNCTIONAL_HISTOGRAM_H
#include <errno.h>
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"
#include "../functional-bb-startup-abi.h"

#define FUNCTIONAL_HISTOGRAM_SID UINT32_C(0x92840747)
#define FUNCTIONAL_HISTOGRAM_REQUEST_BYTES 12u
#define FUNCTIONAL_HISTOGRAM_ACK_BYTES 12u
#define FUNCTIONAL_HISTOGRAM_NOTIFICATION_BYTES 1034u
#define FUNCTIONAL_HISTOGRAM_LEASES 3u
#define FUNCTIONAL_HISTOGRAM_REQUEST 0u
#define FUNCTIONAL_HISTOGRAM_ACK 1u
#define FUNCTIONAL_HISTOGRAM_NOTIFICATION 2u

struct functional_histogram_snapshot {
    int owner_pid, bridge_rc, validation_rc;
    unsigned int initialized, functional_model, busy, guard_held, faults;
    unsigned int queue_bound, queue_source, requests, model_complete, request_owned;
    unsigned int ack_consumed, notification_consumed, ap_consumed;
    unsigned int physical_asic_verified, original_cp_fifo_verified, physical_cp_rtos_verified;
    unsigned int ui_applied, continuous_histogram, capture_verified;
    uint64_t cycle, model_instance, config_generation, frame_generation, lease_generation;
    uint64_t before_config_generation, before_frame_generation;
    uint64_t model_result_fnv1a64, notification_fnv1a64, channel_fnv1a64[4];
    unsigned int model_result_bytes, notification_selector;
    struct fcam_native_origin origin;
    void *original_request;
    struct fcam_bridge_result bridge_result;
    unsigned char original_wire[FUNCTIONAL_HISTOGRAM_REQUEST_BYTES];
    unsigned char canonical8[FCAM_HIST_INPUT_BYTES];
    unsigned char model_result[FCAM_HIST_RESULT_BYTES];
    unsigned char notification_wire[FUNCTIONAL_HISTOGRAM_NOTIFICATION_BYTES];
    struct native_cp_state_publication_lease leases[FUNCTIONAL_HISTOGRAM_LEASES];
    unsigned int allocate_attempted[FUNCTIONAL_HISTOGRAM_LEASES];
    unsigned int allocation_alias[FUNCTIONAL_HISTOGRAM_LEASES];
    unsigned int free_attempted[FUNCTIONAL_HISTOGRAM_LEASES];
    unsigned int send_started[FUNCTIONAL_HISTOGRAM_LEASES];
    void *allocation_returned[FUNCTIONAL_HISTOGRAM_LEASES];
};
/* Local setup only, no RPC, native state changes or CP3003/mode1 prerequisite.
 * Exactly the first enabled/mode1 0148 request is supported; no reset/re-enable,
 * mode0, disable, synthetic future, continuous stream or physical ASIC claim. */
int functional_histogram_owner_init(void);
/* Trusted main must first verify the real AP *0910fa20 at the original callsite
 * with two independent readbacks equal to the request's actual source. This
 * function binds identity only; its parameter is not native verification.
 * After init: bind once, same ID idempotent, different ID -ESTALE. Reject 0,
 * UINT_MAX and our SID. Forked owners reject before inherited mutexes. */
int functional_histogram_bind_queue(unsigned int source);
/* Unrelated messages return0. Matching refusal returns1/result<0, caller-owned.
 * Only full verified result1192 takes over; then result0 includes sticky OSAL
 * faults with retained actual pointers. Request freeQ0 precedes independent
 * allocD(12)/allocD(1034), full copy/readback, ACK-first sends with sourceQ.
 * Guard is the parent's all13/resource guard, not a CP mode1 completion test.
 * Callbacks and logger always execute outside the private mutex. Each record
 * captures state and a nonzero increasing snapshot_id together under mutex;
 * main event_role is request1/ACK2/notification3, or0 for non-lease events.
 * All three LEASE rows carry that same pid/cycle/snapshot_id. Log lines may
 * interleave; serial exhaustion faults the owner and emits only RECORD_FAILED. */
int functional_histogram_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *, int enabled, int *result);
/* Call only after real receive rc0. Stores immutable cycle1 into *ticket.
 * ACK receiver may differ from request sender (original promise/future path).
 * ACK free must be on the original request sender; notification free must be
 * on its actual observed receiver. Main must transfer the ORIGINAL ticket to
 * the waiting caller, never refresh a ticket from a snapshot at free time.
 * Inline receive/free before send returns is supported; send0 alone is queued.
 * Only live pointers are owned. Retired diagnostic addresses return0. */
int functional_histogram_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket);
int functional_histogram_release_cycle(unsigned int destination, void *pointer,
    uint64_t ticket, int (*real_free)(unsigned int, void *),
    void (*record)(const char *, const char *), int *result);
void functional_histogram_snapshot(struct functional_histogram_snapshot *);
/* Supplied by main/real bridge; no production model stub in this owner. */
int fcam_bridge_histogram(const struct fcam_native_origin *, const unsigned char[FCAM_HIST_INPUT_BYTES],
    unsigned char[FCAM_HIST_RESULT_BYTES], struct fcam_bridge_result *);
#ifdef HOST_TEST
void functional_histogram_test_hold_lock(void);
void functional_histogram_test_drop_lock(void);
void *functional_histogram_test_state_address(void);
const void *functional_histogram_test_constant_address(void);
void *functional_histogram_test_serial_address(void);
void functional_histogram_test_exhaust_serial(void);
#endif
#endif
