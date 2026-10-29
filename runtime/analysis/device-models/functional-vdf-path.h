/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_VDF_PATH_H
#define FUNCTIONAL_VDF_PATH_H
#include <errno.h>
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"
#include "../functional-vdf-path-abi.h"
#include "../functional-bb-startup-abi.h"

#define FUNCTIONAL_VDF_PATH_SID UINT32_C(0x92840747)
#define FUNCTIONAL_VDF_PATH_REQUEST_BYTES 24u
#define FUNCTIONAL_VDF_ZEBRA_REQUEST_BYTES 14u
#define FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES 40u
#define FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES 16u
#define FUNCTIONAL_VDF_FLAG_REQUEST_BYTES 10u
#define FUNCTIONAL_VDF_REFRESH_REQUEST_BYTES 8u
#define FUNCTIONAL_BB_0111_REQUEST_BYTES 36u
#define FUNCTIONAL_BB_0166_REQUEST_BYTES 36u
#define FUNCTIONAL_BB_0167_REQUEST_BYTES 10u
#define FUNCTIONAL_BB_015F_REQUEST_BYTES 12u
#define FUNCTIONAL_BB_0128_REQUEST_BYTES 20u
#define FUNCTIONAL_VDF_MAX_REQUEST_BYTES 40u
#define FUNCTIONAL_VDF_PATH_ACK_BYTES 12u
#define FUNCTIONAL_VDF_PATH_LEASES 2u
#define FUNCTIONAL_VDF_PATH_REQUEST 0u
#define FUNCTIONAL_VDF_PATH_ACK 1u
#define FUNCTIONAL_VDF_PATH_BLOCKED (-ENODATA)

enum functional_vdf_path_phase {
    FUNCTIONAL_VDF_PATH_IDLE = 0,
    FUNCTIONAL_VDF_PATH_PROBING,
    FUNCTIONAL_VDF_PATH_MODEL_COMPLETE,
    FUNCTIONAL_VDF_PATH_ACK_QUEUED,
    FUNCTIONAL_VDF_PATH_ACK_RECEIVED,
    FUNCTIONAL_VDF_PATH_AP_CONSUMED,
    FUNCTIONAL_VDF_PATH_FAULT
};
struct functional_vdf_path_snapshot {
    int owner_pid;
    unsigned int initialized, busy, guard_held, faults, phase, functional_model;
    unsigned int refresh_queue_bound, refresh_queue_source;
    unsigned int requests, completed_cycles, init_attempted, model_initialized;
    unsigned int request_owned, model_complete, ack_queued, ack_received, ap_consumed;
    unsigned int physical_cp_rtos_verified, original_cp_fifo_verified;
    unsigned int original_selector_verified, physical_asic_verified, capture_verified;
    int init_rc, bridge_rc, validation_rc;
    void *allocation_returned;
    unsigned int allocation_alias;
    uint64_t cycle, model_instance, config_generation, frame_generation, lease_generation;
    uint64_t before_config_generation, before_frame_generation;
    struct fcam_native_origin origin;
    unsigned char original_wire[FUNCTIONAL_VDF_MAX_REQUEST_BYTES];
    unsigned char canonical_config[FCAM_VDF_INPUT_BYTES];
    unsigned char canonical_zebra8[FCAM_ZEBRA_INPUT_BYTES];
    unsigned char canonical_layout32[FCAM_LAYOUT_INPUT_BYTES];
    unsigned char canonical_display16[FCAM_DISPLAY_INPUT_BYTES];
    unsigned char canonical_bb32[FCAM_BB_INPUT_BYTES];
    unsigned char init_state[FCAM_STATE_BYTES];
    unsigned char model_result[FCAM_VDF_RESULT_MAX_BYTES];
    unsigned int model_result_bytes;
    struct native_cp_state_publication_lease leases[FUNCTIONAL_VDF_PATH_LEASES];
};
/* Process-local setup only; no bridge initialization or RPC. Parent initializes
 * the bridge after exact request recognition and its all13/resource guard.
 * This owner calls INIT once to pin State128/model instance, then VDF_PATH,
 * VDF_ZEBRA, VDF_LAYOUT, VDF_DISPLAY_CONFIG or BB_STARTUP_CONFIG per cycle. Layout accepts only
 * initial case0 with an active current 640x480 route; result192 reads back all
 * layout32. Display accepts disabled0152/off0162 or exact-bound0141 on a committed
 * active route; result176 reads back typed canonical_display16. Both prove RGB
 * consumption/retirement before independent replies. BB startup0111/0166/0167/
 * 015f/0128 uses BB_STARTUP_CONFIG/result192, canonical_bb32 and class5, with
 * an active committed 640x480 route and the shared ABI's neutral software-only
 * policy. Each has its own zero-status reply and real request retirement before
 * ACK allocation. Config48 is unchanged. No CP3003/start/mode1 prerequisite.
 * Only explicit profile enabled==1 owns it.
 * Unrelated requests return0; rejected matching requests return1/result<0 and
 * remain caller-owned. Once request_owned is set, result0 means takeover even
 * after a transport fault; actual retained leases and sticky faults are visible.
 * Reserve/release/ready callbacks are always outside the private mutex.
 */
int functional_vdf_path_owner_init(void);
/* Trusted caller only: after owner_init, independently read the original AP
 * global queue source twice at the verified refresh call site and require both
 * reads to equal the real request source. This API does not verify that evidence.
 * Exact queue identity authorizes only 0141 transport; it proves no hardware
 * readiness and changes no model, frame or generation state. Nonzero sources
 * other than UINT_MAX/our SID may bind once; same ID is idempotent, a different
 * ID returns -ESTALE. Uninitialized/busy/faulted/inherited owners reject binding
 * (-ENODEV/-EBUSY/-EPROTO/-EXDEV) without changing state; invalid IDs use -EINVAL.
 * Other commands retain their existing 81cf source rule.
 */
int functional_vdf_path_bind_refresh_queue(unsigned int source);
int functional_vdf_path_dispatch(unsigned int, void *, const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *, int enabled, int *result);
void functional_vdf_path_snapshot(struct functional_vdf_path_snapshot *);
/* Call ONLY after real successful rcv. On acceptance writes immutable cycle to
 * *ticket; store it in receiver TLS. ACK receive AND free require original
 * sender TID. No snapshot-at-free ticket lookup. A failed free retains the
 * lease and ticket; only successful real free plus send success is AP consumed.
 * Both hooks tolerate receive/free inline inside send before send returns.
 * Retired addresses alone do not own later messages: unmatched receives and
 * unqualified frees return0; explicit stale tickets still reject old events.
 */
int functional_vdf_path_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket);
int functional_vdf_path_release_cycle(unsigned int destination, void *pointer,
    uint64_t ticket, int (*real_free)(unsigned int, void *),
    void (*record)(const char *, const char *), int *result);
#ifdef HOST_TEST
void functional_vdf_path_test_hold_lock(void);
void functional_vdf_path_test_drop_lock(void);
void *functional_vdf_path_test_snapshot_address(void);
#endif
#endif
