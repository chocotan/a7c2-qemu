/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_FUNCTIONAL_CAMERA_CONTROL_H
#define NATIVE_FUNCTIONAL_CAMERA_CONTROL_H
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"

#define FUNCTIONAL_CAMERA_CONTROL_SID NATIVE_CP_STATE_PUBLICATION_SID
#define FUNCTIONAL_CAMERA_CONTROL_AP NATIVE_CP_STATE_PUBLICATION_AP
#define FUNCTIONAL_CAMERA_CONTROL_LEASES CP_STATE_PUBLICATION_LEASES
#define FUNCTIONAL_CAMERA_CONTROL_BLOCKED (-ENODATA)

enum functional_camera_control_phase {
    FUNCTIONAL_CAMERA_CONTROL_UNKNOWN = 0,
    FUNCTIONAL_CAMERA_CONTROL_PROBING,
    FUNCTIONAL_CAMERA_CONTROL_INITIALIZED,
    FUNCTIONAL_CAMERA_CONTROL_START_QUEUED,
    FUNCTIONAL_CAMERA_CONTROL_START_CONSUMED,
    FUNCTIONAL_CAMERA_CONTROL_STATE_PROBING,
    FUNCTIONAL_CAMERA_CONTROL_PUBLICATION_COPIED,
    FUNCTIONAL_CAMERA_CONTROL_NOTICE_QUEUED,
    FUNCTIONAL_CAMERA_CONTROL_NOTICE_RECEIVED,
    FUNCTIONAL_CAMERA_CONTROL_NOTICE_CONSUMED,
    FUNCTIONAL_CAMERA_CONTROL_FAULT,
    FUNCTIONAL_CAMERA_CONTROL_MODE_ACK_CONSUMED
};
struct native_functional_camera_control_snapshot {
    int owner_pid;
    unsigned int initialized, busy, guard_held, faults, phase;
    unsigned int start_requests, start_complete, mode1_requests, mode1_complete;
    unsigned int model_initialized, business_ready, functional_model;
    unsigned int original_cp, physical_asic_verified, ee, frame, capture;
    unsigned int probe_attempts, probe_successes, probe_refusals;
    int bridge_rc, probe_rc;
    uint64_t probe_run_id, init_run_id, state_run_id;
    uint64_t model_instance, config_generation, rendered, frame_generation;
    struct fcam_native_origin last_origin;
    unsigned char model_state[FCAM_STATE_BYTES];
    unsigned int start_defined_mask, start_original_known_mask;
    unsigned int full_layout_copied, full_model_defined, full_original_source_known;
    unsigned int publication_copied, notification_queued;
    unsigned int notification_received, notification_ap_consumed;
    unsigned int shadow_generation, published_generation;
    unsigned int defined_blocks, projected_blocks, zero_policy_blocks;
    unsigned char block_defined[CP_FULL_STATE_SNAPSHOT_BLOCKS];
    unsigned char block_projected[CP_FULL_STATE_SNAPSHOT_BLOCKS];
    struct native_cp_state_publication_lease leases[FUNCTIONAL_CAMERA_CONTROL_LEASES];
    /* mode1_requests is lifetime acceptance; mode1_complete is the last cycle.
     * notification_* and publication_* describe the last full publication,
     * including during an ACK-only cycle. No ACK-only publication is counted. */
    unsigned int notification_mode, mode1_ack_only, mode1_cycle_generation;
    unsigned int mode1_cycles_completed, mode1_ack_only_requests;
    unsigned int mode1_ack_only_completed, full_notifications_queued, full_notifications_consumed;
    uint64_t mode1_cycle_id, lease_cycle_id[FUNCTIONAL_CAMERA_CONTROL_LEASES];
    /* Latest full copy's one-frame-period software capability, not AP/flash completion. */
    unsigned int xsync_defined, xsync_source_fps, xsync_word, xsync_half;
    uint64_t xsync_source_generation;
};
/* Local setup only: no broker/host operation, reset, readiness import or RPC.
 * Explicit functional profile only. Main still supplies its complete same-
 * process predecessor cohort (including the real 4072/earlier original frees).
 * Exact 3003/3000 start performs live INIT with the original request origin;
 * exact 4073 mode1 performs live STATE only after the original start ACK free.
 * Repeat mode1 requires all previous leases retired. A newer actual generation
 * publishes a full notice; an already AP-consumed generation needs only ACK.
 * Missing/invalid model data returns handled=1/result<0, caller retains request.
 * After successful allocations, accepted requests are retained until real free;
 * result=0 then means owner takeover, never AP consumption or capture success.
 * Other modes/commands return0 for their existing owners. */
int native_functional_camera_control_owner_init(void);
int native_functional_camera_control_dispatch(unsigned int, void *,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    int enabled, int *result);
/* Observe ONLY an actual original receive. Exact full pointer/source/bytes are
 * checked before its receiver may free a notice. The original imaging worker
 * may receive an ACK for a different requesting thread; ACKs must still be
 * freed by that original sender. Shadow advances only after the observed full
 * notification's real free on its receiving thread returns0. */
int native_functional_camera_control_observe_receive(unsigned int, void *, unsigned int, unsigned int);
int native_functional_camera_control_release(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result);
/* Repeated mode leases require the ticket captured for that actual transport
 * event, from lease_cycle_id in the snapshot. Never look up a fresh ticket for
 * an old event. Unqualified hooks accept only startup/first-mode leases; later
 * mode leases return -ESTALE without touching the owned pointer or real free. */
int native_functional_camera_control_observe_receive_cycle(unsigned int, void *, unsigned int, unsigned int, uint64_t);
int native_functional_camera_control_release_cycle(unsigned int, void *, int (*)(unsigned int, void *),
    void (*)(const char *, const char *), int *result, uint64_t);
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *);
#ifdef HOST_TEST
void native_functional_camera_control_test_hold_lock(void);
void native_functional_camera_control_test_drop_lock(void);
#endif
#endif
