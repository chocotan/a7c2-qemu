/* SPDX-License-Identifier: MIT */
#ifndef FULL_HDMI_VIDEO_STATE_H
#define FULL_HDMI_VIDEO_STATE_H
#include "hdmi-device.h"

#define FULL_HDMI_VIDEO_STATE_PROFILE 1
#define FULL_HDMI_VIDEO_CONDITION_SOURCE 0x91ca0816u
#define FULL_HDMI_VIDEO_UPM 0x80920572u
/* These identify this virtual owner's states, not an original CP enum. */
#define FULL_HDMI_VIDEO_INITIALIZING 1u
#define FULL_HDMI_VIDEO_HPD_LOW 2u

struct full_hdmi_video_state_snapshot {
    int owner_pid;
    unsigned int initialized, state_id, current_initializing, current_hpd_low;
    unsigned int history_known, faults, pending, prefix_received, registered_condition_sid;
    unsigned int stored_g98, platform_p60, platform_p7c, platform_p28, platform_p28_known;
    unsigned int video_g58, condition_flags[13], condition_queues[13];
    unsigned int connect_started, exit_completed, entry_completed, cached_hpd_completed, ready;
    unsigned int live_messages, retained_messages, backup_bound, backup_reads;
    unsigned int condition_message_count, condition_received, condition_consumed;
    unsigned int upm_message_count, upm_received, upm_consumed, upm_effective_second_id;
    unsigned int prefix_queued, prefix_native_freed, prefix_waiter_freed, request_freed;
    unsigned int driver_jobs, driver_jobs_consumed, driver_descriptors_freed;
    unsigned int driver_nodes_queued, driver_nodes_read, driver_nodes_freed;
    unsigned int driver_poll_calls, driver_wake_reads, monitor_subscription;
    unsigned int driver_initialization_writes, driver_config_writes, monitoring_enabled;
    unsigned int driver_current_mode, driver_target_mode, driver_active, driver_dirty;
    unsigned int sync_handle, monitor_handle, completion_owner, completion_index;
    unsigned int driver_policy_slot, driver_policy_row, driver_policy_column, driver_policy;
    unsigned int g14c, g14d, g168, platform_p190, g144, g13c;
    unsigned int diagnostics_masked, original_cp_executed, hardware_verified, capture_verified;
    unsigned long long next_lease, transition_order[4];
    unsigned char initialization[18], platform_initialization[18], driver_initialization[18];
    unsigned char config[28], platform_config[36], driver_config[36], completion[12];
    void *retained_request;
};

/* The reader returns 0 with the actual stored length, 1 for an absent item, or
 * a negative error. It copies min(length, capacity) bytes. Bind the same public
 * Backup source used by the run; absence of necessary bytes leaves Connect
 * pending. No private dump values or invented successful reads are supplied. */
typedef int (*full_hdmi_video_backup_reader)(unsigned int key, void *out,
                                           unsigned int capacity, unsigned int *length);
/* Call once before any HDMI input, including the pre-existing config owner.
 * Late initialization cannot assert the original Initializing history. */
int full_hdmi_video_state_owner_init(void);
int full_hdmi_video_state_bind_backup(full_hdmi_video_backup_reader);
/* stage0 arms observation before sending; stage1 validates the original kernel
 * receive/handler/final-free receipt. A completed receipt retires this lease
 * without reading or freeing its already released OSAL allocation. */
typedef int (*full_hdmi_video_kernel_observer)(unsigned int stage,unsigned long long lease,
    void *pointer,const unsigned char raw[16],const unsigned char effective[16],
    void (*record)(const char *,const char *));
int full_hdmi_video_state_bind_kernel_observer(full_hdmi_video_kernel_observer);
/* Route owned Connect messages to their endpoint first. This dispatcher owns
 * the three2500 prefix commands and delegates the existing config commands;
 * a valid48B PinGet falls through without modifying HDMI state. */
int full_hdmi_video_state_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
/* Invoke instead of forcing a state at Connect. 0=complete, 1=pending,
 * -1021=fault. Repeated calls do not enqueue another initialization or batch.
 * An asynchronous endpoint must retain its AP reply until connect_ready(). */
int full_hdmi_video_state_connect_begin(const struct full_imaging_io *);
int full_hdmi_video_state_connect_ready(void);
void full_hdmi_video_state_snapshot(struct full_hdmi_video_state_snapshot *);
/* Call only after an actual successful original OSAL receive. The corresponding
 * real free must occur on that same receiver thread. Sending or provider-side
 * cleanup alone never consumes a condition/UPM notification. UPM observation
 * may require kernel instrumentation; without it the connection stays pending.
 * UPM uses FULL_HDMI_CP as this model's envelope identity; the original CP
 * producer did not explicitly set a source, and k_psave_api does not read it. */
int full_hdmi_video_state_observe_receive(unsigned int id, void *message,
                                         unsigned int source, unsigned int bytes);
int full_hdmi_video_state_release(unsigned int, void *, int (*)(unsigned int, void *),
                                  void (*)(const char *, const char *), int *);
#ifdef FULL_HDMI_VIDEO_STATE_TEST
void full_hdmi_video_state_test_reset(void);
#endif
#endif
