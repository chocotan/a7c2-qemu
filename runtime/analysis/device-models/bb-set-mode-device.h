/* SPDX-License-Identifier: MIT */
#ifndef FULL_BB_SET_MODE_DEVICE_H
#define FULL_BB_SET_MODE_DEVICE_H
#include "adf-proc-device.h"
#define FULL_BB_SET_MODE_INPUT 0x92840747u
#define FULL_BB_SET_MODE_PROFILE "virtual-bb-still-target3-op0-v1"
struct full_bb_set_mode_snapshot {
    unsigned int initialized, enabled, busy, faults, pending, guard_held;
    unsigned int generation, requests, applications, queued, clean_completion, ap_consumed;
    unsigned int state_word, state_known, state_setter_calls, state_epoch;
    unsigned int initial_state_bytes_verified, original_cp_executed;
    unsigned int prefix_messages, prefix_config_invalidations, unknown_prefix_messages;
    unsigned int operation_mode, operation_mode_valid, target;
    unsigned int config_initialized, config_invalidated, config_mode_updates, config_saves;
    unsigned int config_snapshot_copies, config_snapshot_known_bytes, config_snapshot_unknown_bytes;
    unsigned long long config_live_fnv, config_known_fnv, config_snapshot_fnv, config_snapshot_known_fnv;
    unsigned int semaphore_acquires, semaphore_releases, semaphore_busy;
    unsigned int queue_generation, outer_owner, outer_queue, outer_task, outer_accepted;
    unsigned int outer_popped, outer_inflight, outer_returned;
    unsigned int inner_owner, inner_queue, inner_task, inner_accepted;
    unsigned int inner_popped, inner_inflight, inner_returned;
    unsigned int queue4_virtual_consumer, queue_finished;
    unsigned int first_internal_completion, second_internal_completion;
    unsigned int handler_linked_byte5, handler_linked_byte7, execution_gate_byte4;
    unsigned int unique_ap_reply, reply_owner, request_freed, reply_freed;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc;
    void *retained_request, *live_reply, *retained_reply, *retained_cleanup;
};
/* Explicit source-equivalent CP model, not original CP execution or live CP RAM.
 * Construct once before fork and only behind the default-off BB profile. State
 * word1 is the public CP data-image initializer; preceding source-reviewed
 * transactions do not call its setter. Only the first target3/opmode0 path is
 * supported. The two queue workers and internal completion order are modeled
 * synchronously under a common native-resource reservation; this is not RTOS
 * scheduling/timing equivalence. No frame/MMIO/PCM/CP task or capture claim. */
int full_bb_set_mode_owner_init(void);
/* Opaque BB config remains unknown except source-identified writes. */
int full_bb_set_mode_observe_input(unsigned int, void *, const struct full_imaging_io *);
int full_bb_set_mode_dispatch(unsigned int, void *, const struct full_imaging_io *,
                              const struct full_adf_proc_guard *, int, int *);
int full_bb_set_mode_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                   void (*)(const char *, const char *), int *);
void full_bb_set_mode_snapshot(struct full_bb_set_mode_snapshot *);
#endif
