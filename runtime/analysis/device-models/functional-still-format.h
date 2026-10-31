/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_STILL_FORMAT_H
#define FUNCTIONAL_STILL_FORMAT_H
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"
#include <errno.h>

#define FUNCTIONAL_STILL_FORMAT_SID NATIVE_CP_STATE_PUBLICATION_SID
#define FUNCTIONAL_STILL_FORMAT_AP NATIVE_CP_STATE_PUBLICATION_AP
#define FUNCTIONAL_STILL_FORMAT_REQUEST_BYTES 24u
#define FUNCTIONAL_STILL_FORMAT_REPLY_BYTES 12u
#define FUNCTIONAL_STILL_FORMAT_BLOCKED (-ENOTSUP)

struct functional_still_format_snapshot {
    int owner_pid;
    unsigned int initialized, busy, guard_held, faults, functional_only;
    unsigned int requests, completed_cycles, ap_consumed, request_owned;
    unsigned int state_valid, operation_attempted, model_complete, retained;
    unsigned int original_ap_verified, original_cp, physical_asic_verified;
    unsigned int physical_cp_rtos_verified, original_selector_verified, capture_verified;
    uint64_t cycle, model_instance, before_config_generation, config_generation;
    /* STATE128 has no lease counter; before_lease_generation is this owner's
     * last accepted lease. Current rendered/frame counters bound a new lease. */
    uint64_t before_frame_generation, frame_generation, before_lease_generation, lease_generation;
    uint64_t actual_origin_fnv, result_fnv;
    int state_bridge_rc, state_validation_rc, bridge_rc, validation_rc, transport_rc;
    struct fcam_native_origin origin;
    struct fcam_bridge_result state_response, format_response;
    unsigned char original_wire[24], canonical16[16], reply_wire[12];
    unsigned char model_state[FCAM_STATE_BYTES], model_result[FCAM_STILL_FORMAT_RESULT_BYTES];
    struct native_cp_state_publication_lease leases[2];
};
/* Local setup only; no RPC, importer, implicit INIT or reset. Explicit functional
 * profile only. Parent's reserved predecessor predicate must prove actual prior
 * diagnostic M clean/AP free, active current-instance VDF, all13 and all resources.
 * Only exact type5/402d/24B/AP with the L/Fine tuple is supported; wire22..23
 * remain opaque in raw24/FNV and become virtual zero in canonical16.
 * Before Core admission refusals leave caller ownership. A corrupt/failed live
 * Core result also leaves caller ownership, with sticky fault and actual raw
 * result/call rc visible: remote counters may already have changed.
 * After typed validation takeover returns result0, including retained I/O faults.
 * Request real free rc0 precedes independent reply allocation/send. Reply byte1
 * is explicit software padding zero, never an original-source proven value. */
int functional_still_format_owner_init(void);
int functional_still_format_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *, int enabled, int *result);
/* Call only for an actual successful original receive. CP's receiving thread may
 * differ from the original sender; only the sender may real-free the reply after
 * that receive. No consumption until send returned0 and the whole cycle retired. */
int functional_still_format_observe_receive(unsigned int, void *, unsigned int, unsigned int);
int functional_still_format_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
/* Parent captures snapshot.cycle for the actual queued event/promise and carries
 * it through original receive -> sender free. Never refresh an old event's ticket.
 * Unqualified hooks accept cycle1 only; later cycles require these ticketed hooks.
 * Stale tickets return -ESTALE unchanged, never dereference/free a reused address. */
int functional_still_format_observe_receive_cycle(unsigned int, void *, unsigned int, unsigned int, uint64_t);
int functional_still_format_release_cycle(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t);
void functional_still_format_snapshot(struct functional_still_format_snapshot *);
#ifdef HOST_TEST
void functional_still_format_test_hold_lock(void);
void functional_still_format_test_drop_lock(void);
#endif
#endif
