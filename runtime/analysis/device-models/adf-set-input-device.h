/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_SET_INPUT_DEVICE_H
#define FULL_ADF_SET_INPUT_DEVICE_H
#include "adf-proc-device.h"
#define FULL_ADF_SET_INPUT_INPUT 0x92840747u
#define FULL_ADF_SET_INPUT_KIKILOG 0x811006e9u
struct full_adf_set_input_snapshot {
    unsigned int configured, busy, worker_active, faults, guard_held;
    unsigned int generation, requests, applications, queued, clean_completion, ap_consumed;
    unsigned int dependency_claimed, output_handoff, capability_word7, capability_word8, init_selector;
    unsigned int hotshoe_callbacks, hotshoe_commits, glee_callbacks, glee_readbacks;
    unsigned int pending_config, config_commits, completion_mask, digital_pending;
    unsigned int active_type, active_channels, active_sampling, active_depth;
    unsigned int control139, control131, control141, control102, control110, mask650, value7c;
    unsigned int abb65c, abb660, abb_bb, abb_c0, software_s;
    unsigned int soft74490, soft743ac, soft744c0, soft743d0, soft743d4;
    unsigned int provider_calls, ab_failures, ab_register_writes, feature_callbacks;
    unsigned int events, hardware_counter, hardware_epoch, source5_queued, source5_consumed;
    unsigned int aip_dispatches, first_snapshot_count, first_checked, first_cursor, uninspected;
    unsigned int first_task_status, last_task_status, ring_read, ring_write, last_snapshot_count;
    unsigned int config03, config02, config_writes, config_readbacks;
    unsigned long long config_public_reads, config_write_hash;
    unsigned int inner_queued, inner_consumed, inner_status, outer_status;
    unsigned int kikilog_attempted, kikilog_queued, kikilog_allocator_source;
    unsigned int request_owner, reply_owner, cleanup_owner;
    unsigned int request_freed, reply_freed, cleanup_freed;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc, cleanup_free_rc;
    int kikilog_allocate_rc, kikilog_send_rc;
    void *retained_request, *live_reply, *retained_reply, *retained_cleanup;
};
/* Default-off virtual-input-s0-v1 only. The original metadata completion is
 * independent of the AB/status1 asynchronous task1004; neither is falsified.
 * This service consumes real public configuration and owned register work,
 * but asserts no original CP execution, hardware audio, PCM, frames or capture.
 * Valid acceptance transfers the exact request to a single async worker;
 * unknown resources/work retain it without a reply. Parent binds PID before
 * fork. Transport/guard callbacks must not reenter this module. Allocation is
 * outside its private mutex. Kikilog success transfers its message to the
 * kernel; that pointer is never treated as a live user-owned reply afterward. */
int full_adf_set_input_owner_init(void);
int full_adf_set_input_dispatch(unsigned int, void *, const struct full_imaging_io *,
                               const struct full_adf_proc_guard *, int, int *);
int full_adf_set_input_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                   void (*)(const char *, const char *), int *);
/* One irreversible transfer to 032d, only after the original AP1336 reply free
 * and every generation2 work/ring/subscription has drained. out must be zero.
 * This copies owner references, never the live devices or their snapshots. */
int full_adf_set_input_claim_output(struct full_adf_proc_input_owners *);
void full_adf_set_input_snapshot(struct full_adf_set_input_snapshot *);
#ifdef FULL_ADF_SET_INPUT_TEST
void full_adf_set_input_test_seed_path(const char *);
void full_adf_set_input_test_event_limit(unsigned int);
#endif
#endif
