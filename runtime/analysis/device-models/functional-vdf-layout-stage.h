/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_VDF_LAYOUT_STAGE_H
#define FUNCTIONAL_VDF_LAYOUT_STAGE_H
#include "cp-state-publication.h"
#include "../functional-camera-bridge.h"
#include "../functional-vdf-path-abi.h"

#define FUNCTIONAL_LAYOUT_STAGE_SID UINT32_C(0x92840747)
#define FUNCTIONAL_LAYOUT_STAGE_REQUEST_BYTES 40u
#define FUNCTIONAL_LAYOUT_STAGE_BANK_BYTES 32u
#define FUNCTIONAL_LAYOUT_STAGE_ACK_BYTES 12u

struct functional_vdf_layout_stage_applied {
    int owner_pid;
    unsigned int verified, semantic_applied, frame_consumed;
    uint64_t stage_generation, model_instance, config_generation, frame_generation;
    uint64_t lease_generation, result_fnv1a64;
};
struct functional_vdf_layout_stage_snapshot {
    int owner_pid;
    unsigned int initialized, busy, faults, requests, completed_cycles;
    unsigned int request_owned, bank_written, readback_verified, ack_queued, ack_received, ap_consumed;
    unsigned int stage_only, semantic_applied, frame_consumed, hardware_ready, capture_verified;
    unsigned int physical_asic_verified, original_cp_fifo_verified, physical_cp_rtos_verified;
    int validation_rc;
    uint64_t cycle, stage_generation, bank_fnv1a64, readback_fnv1a64;
    struct fcam_native_origin origin;
    unsigned char original_wire[FUNCTIONAL_LAYOUT_STAGE_REQUEST_BYTES];
    unsigned char bank32[FUNCTIONAL_LAYOUT_STAGE_BANK_BYTES];
    unsigned char copied_readback32[FUNCTIONAL_LAYOUT_STAGE_BANK_BYTES];
    void *allocation_returned;
    unsigned int allocation_alias;
    struct native_cp_state_publication_lease leases[2];
    struct functional_vdf_layout_stage_applied applied;
};
/* Explicit functional profile, route_ready == 0 only. Other routes/profiles
 * return0 without IO. Matching rejects are caller-owned/result<0. Once owned,
 * returns1/result0 even on fault: retained leases and faults must be inspected.
 * No reset, bridge INIT/RPC, all13 change, media allocation, or frame claim. */
int functional_vdf_layout_stage_owner_init(void);
int functional_vdf_layout_stage_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *, int enabled, int route_ready, int *result);
void functional_vdf_layout_stage_snapshot(struct functional_vdf_layout_stage_snapshot *);
/* Only after actual original receive. Save the returned immutable ticket in
 * receiver TLS; do not fetch the current cycle at free. Same sender TID for
 * receive/free. Free failure retains its lease/ticket and faults stay sticky. */
int functional_vdf_layout_stage_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket);
int functional_vdf_layout_stage_release_cycle(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*record)(const char *, const char *), int *result);
/* Exact-size, same-PID, completed healthy generation copy for a later real op7.
 * Never marks applied. Caller owns separate accessible output and digest. */
int functional_vdf_layout_stage_read_bank(uint64_t stage_generation, void *out,
    size_t bytes, uint64_t *readback_fnv1a64);
/* Main calls ONLY after the actual native op7's validated model192, full RGB
 * sink consumption and retirement. Revalidates exact layout32, shape, instance,
 * generations, full byte count and digest equality; copies an independent
 * apply receipt. Early stage_only/semantic/frame fields stay unchanged. This
 * API cannot authenticate fabricated caller data as a real model execution. */
int functional_vdf_layout_stage_bind_applied(uint64_t stage_generation, int model_owner_pid,
    uint64_t model_instance, const void *model192, size_t bytes,
    const struct fcam_bridge_result *metadata);
#ifdef HOST_TEST
void functional_vdf_layout_stage_test_hold_lock(void);
void functional_vdf_layout_stage_test_drop_lock(void);
void *functional_vdf_layout_stage_test_private_address(unsigned int index);
void functional_vdf_layout_stage_test_corrupt_readback(unsigned int offset);
#endif
#endif
