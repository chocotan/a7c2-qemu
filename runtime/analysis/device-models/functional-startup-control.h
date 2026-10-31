/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_STARTUP_CONTROL_H
#define FUNCTIONAL_STARTUP_CONTROL_H
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"
#include "../functional-startup-control-abi.h"
#include <errno.h>

#define FUNCTIONAL_STARTUP_CONTROL_SID NATIVE_CP_STATE_PUBLICATION_SID
#define FUNCTIONAL_STARTUP_CONTROL_AP NATIVE_CP_STATE_PUBLICATION_AP
#define FUNCTIONAL_STARTUP_CONTROL_REQUEST_MAX 24u
#define FUNCTIONAL_STARTUP_CONTROL_REPLY_BYTES 12u
#define FUNCTIONAL_STARTUP_CONTROL_BLOCKED (-ENOTSUP)
/* Complete generic logger tag, including its final space; events are in text. */
#define FUNCTIONAL_STARTUP_CONTROL_LOG_TAG "FUNCTIONAL_STARTUP_CONTROL "

struct functional_startup_control_snapshot {
    int owner_pid;
    unsigned int initialized, busy, guard_held, faults, functional_only;
    unsigned int requests, completed_cycles, ap_consumed, request_owned;
    unsigned int state_valid, operation_attempted, model_complete, retained;
    unsigned int command, command_requests[2], command_completed[2], mode_applied;
    unsigned int original_wire_bytes;
    unsigned int original_ap_verified, original_cp, physical_asic_verified;
    unsigned int physical_cp_rtos_verified, original_selector_verified, capture_verified;
    unsigned int source_dependencies_closed, native_cp, ee;
    uint64_t cycle, model_instance, before_config_generation, config_generation;
    /* STATE128 has no lease counter; before_lease_generation is this owner's
     * last accepted lease. Actual rendered/frame counters bound the next lease. */
    uint64_t before_frame_generation, frame_generation, before_lease_generation, lease_generation;
    uint64_t actual_origin_fnv, result_fnv, current_config40_fnv;
    int state_bridge_rc, state_validation_rc, bridge_rc, validation_rc, transport_rc;
    struct fcam_native_origin origin;
    struct fcam_bridge_result state_response, control_response;
    unsigned char original_wire[24], canonical32[32], reply_wire[12];
    unsigned char model_state[FCAM_STATE_BYTES], model_result[FCAM_STARTUP_CONTROL_RESULT_BYTES];
    struct native_cp_state_publication_lease leases[2];
};
/* Local setup only: no RPC, implicit INIT, importer or reset. Explicit functional
 * profile only. Parent reserve31/predecessor must prove both original one-shot
 * 4014/4057 clean/sender-free, all13, current active VDF and current still-format
 * on the same instance, with all leases retired. No readiness is built here.
 * Only SID/type5/AP and exact 4014/24B/body16 or 4057/12B/body4=0 are supported;
 * 40c8/unknown commands remain unhandled. Original byte1/cookie stay opaque.
 * canonical32 hashes this instance's ACTUAL STATE128 bytes8..47, not Config48.
 * 4057 requires a previous functional4014 with actual reply receive/sender-free.
 * command counters index0=4014, index1=4057. mode_applied is an independently
 * validated software-model receipt, never an original CP/queue/ready claim.
 * Before takeover, failures leave caller ownership and no ACK/free; live Core
 * failures keep sticky fault/raw192/actual rc because counters may have changed.
 * After takeover returns handled1/result0 even on retained I/O failure. Request
 * real-free0 precedes any ACK allocation. Reply byte1=0 is virtual padding.
 * Every IO/guard/bridge/free/logger callback runs outside the private mutex. */
int functional_startup_control_owner_init(void);
int functional_startup_control_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *, int enabled, int *result);
/* Call only after successful original native receive. Parent publishes an
 * immutable {pid,pointer,dst,cycle,cookie} send slot from leases[1] with
 * send_inflight1 BEFORE real_send, then carries that ticket through native
 * receive -> original sender free. Clear the matching slot only on real-free0.
 * Receiver may differ from sender; sender-free requires this generation's full
 * live pointer/src/dst/12B/cookie/wire receive. send0 alone is never consumption.
 * Inline receive/free may precede send return: no early ap_consumed, and a later
 * send error preserves freed fact with sticky fault. Retired addresses are free
 * to reuse; stale tickets never read/free a newer object's storage. */
int functional_startup_control_observe_receive_cycle(unsigned int, void *, unsigned int, unsigned int, uint64_t);
int functional_startup_control_release_cycle(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t);
/* Compatibility hooks accept only cycle1; all later cycles require a ticket. */
int functional_startup_control_observe_receive(unsigned int, void *, unsigned int, unsigned int);
int functional_startup_control_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *);
#ifdef HOST_TEST
void functional_startup_control_test_hold_lock(void);
void functional_startup_control_test_drop_lock(void);
#endif
#endif
