/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_PROC_DEVICE_H
#define FULL_ADF_PROC_DEVICE_H
#include "imaging-device.h"
#define FULL_ADF_PROC_INPUT 0x92840747u
struct full_adf_proc_guard {
    int (*reserve)(void);
    void (*release)(void);
};
struct full_adf_hotshoe_owner;
struct full_adf_glee_input_owner;
struct full_adf_aip_commands;
struct full_adf_source7_clock;
struct full_adf_avio_output;
struct full_adf_hdmi_monitor;
struct full_adf_aip_disable;
struct full_adf_proc_input_owners {
    struct full_adf_hotshoe_owner *hotshoe;
    struct full_adf_glee_input_owner *glee;
    struct full_adf_avio_output *output;
    struct full_adf_hdmi_monitor *monitor;
    struct full_adf_aip_disable *disable;
    struct full_adf_aip_commands *commands;
    struct full_adf_source7_clock *clock;
    unsigned int capability_word0, capability_word7, capability_word8;
    unsigned int software_s, software_k;
    unsigned int output_target, source5_target, source5_flags, source5_software, source5_sender;
};
struct full_adf_proc_snapshot {
    unsigned int configured, busy, faults, guard_held, worker_active;
    unsigned int generation, requests, applications, queued, clean_completion, ap_consumed;
    unsigned int pin_immediately, capability_word0, capability_word7, capability_word8, init_f, output_source;
    unsigned int requested_path, requested_mode, requested_format, requested_notify;
    unsigned int active_path, active_mode, active_format, active_notify, pending_config, config_commits;
    unsigned int output_requests, avio_pending_mask;
    unsigned int global_state, idle_stage, queued_config, start_job_registered, start_job_consumed;
    unsigned int stop_phase1, stop_cleanup_calls, notify2, notify0;
    unsigned int prelude_requested, prelude_current, prelude_config, prelude_calls;
    unsigned int routing_initialized, routing_pending, routing_prepared;
    unsigned int af_queued, b0_queued, af_consumed, b0_consumed, command_sequence;
    unsigned int disable_writes, disable_readbacks;
    unsigned int pending_path, pending_mode, pending_format, pending_notify, pending_token;
    unsigned int inner_queued, inner_consumed, inner_status, outer_status;
    unsigned int input_pending_at_notify2, config_pending_at_notify2;
    unsigned int source5_registered, source5_queued, source5_consumed, source5_pending;
    unsigned int resource_preparations, coefficients, gate_writes, delay_state;
    unsigned int delay_same_tick_waits, delay_completed_event;
    unsigned int events, hardware_counter, cached_counter, avio_stages, avio_callbacks;
    unsigned int input_controls, input_callbacks, input_readbacks, input_complete;
    unsigned int input_enqueued_event, input_consumed_event;
    unsigned int cold_owners_initialized, cold_control30_notes, input_handoff;
    unsigned int monitor_initializations, monitor_prepares, monitor_commits;
    unsigned int reply_owner, request_owner, cleanup_owner;
    unsigned int request_freed, reply_freed, cleanup_freed;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc, cleanup_free_rc;
    unsigned long long config_fnv;
    void *retained_request, *live_reply, *retained_reply, *retained_cleanup;
};
/* Default-off independent source7 CONTROL events only. Owner PID must be bound
 * by the constructor before fork; child entries reject before callbacks/locks.
 * Valid acceptance transfers the request into this single asynchronous worker.
 * A fault preserves it and sends NO reply. A successful reply has independent
 * ownership and is counted consumed only after the original caller frees it.
 * Guard and all transport callbacks must not reenter this module; allocation
 * is performed outside its private mutex. No original CP or PCM/frame claim. */
int full_adf_proc_owner_init(void);
int full_adf_proc_dispatch(unsigned int,void *,const struct full_imaging_io *,
                            const struct full_adf_proc_guard *,int,int *);
int full_adf_proc_release_reply(unsigned int,void *,int (*)(unsigned int,void *),
                                void (*)(const char *,const char *),int *);
/* Irreversible first-input handoff after original AP0323 reply-free and complete
 * queue/work drain. out must be zero storage. No init, clone, reset or tick occurs.
 * The caller owns subsequent serial access and the common resource reservation;
 * this completed Proc cannot reclaim the transferred owners, even in test reset. */
int full_adf_proc_claim_input(struct full_adf_proc_input_owners *);
void full_adf_proc_snapshot(struct full_adf_proc_snapshot *);
#ifdef FULL_ADF_PROC_TEST
int full_adf_proc_test_reset(void);
void full_adf_proc_test_event_limit(unsigned int);
void full_adf_proc_test_seed_path(const char *);
void full_adf_proc_test_hold_lock(void);
void full_adf_proc_test_drop_lock(void);
#endif
#endif
