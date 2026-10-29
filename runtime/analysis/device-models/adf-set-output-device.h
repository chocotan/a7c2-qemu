/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_SET_OUTPUT_DEVICE_H
#define FULL_ADF_SET_OUTPUT_DEVICE_H
#include "adf-proc-device.h"
#define FULL_ADF_SET_OUTPUT_INPUT 0x92840747u
struct full_adf_set_output_snapshot {
    unsigned int known, initialized, configured, busy, worker_active, faults, guard_held;
    unsigned int generation, requests, applications, queued, clean_completion, ap_consumed;
    unsigned int dependency_claimed, format_copies, format_readbacks, control3_reads;
    unsigned char format[20];
    unsigned int old_mask, target_mask, power20, power22, system_sound_snapshot_known;
    unsigned int monitor_configures, monitor_b0_queued, aip_b0_consumed, aip_checked, aip_cursor, aip_task_status;
    unsigned int disable_calls, disable_writes, disable_readbacks;
    unsigned int events, hardware_counter, hardware_epoch, source5_queued, source5_consumed;
    unsigned int avio_enqueued, avio_consumed, callbacks, callback_slot, completion_status;
    unsigned int callback_read_index, callback_write_index, callback_count, shadow_writes_before, shadow_writes_after;
    unsigned int inner_queued, inner_consumed, outer_status;
    unsigned int request_owner, reply_owner, cleanup_owner, request_freed, reply_freed, cleanup_freed;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc, cleanup_free_rc;
    void *retained_request, *live_reply, *retained_reply, *retained_cleanup;
};
/* Exact default-off 032d W0/O8 domain only. Same source-owned AVIO/Monitor/
 * AIP/disable/clock, one actual event9, real new B0 and zero shadow writes.
 * No SYSTEMSOUND activity is invented; W0/O8 eliminates its unknown predicates.
 * PID is bound before fork. Unknown work/resources retain request without reply.
 * Allocation is outside the private lock; transport/guard must not reenter.
 * No original CP/hardware audio/PCM/frame/capture assertion. */
int full_adf_set_output_owner_init(void);
int full_adf_set_output_dispatch(unsigned int,void *,const struct full_imaging_io *,
                                const struct full_adf_proc_guard *,int,int *);
int full_adf_set_output_release_reply(unsigned int,void *,int (*)(unsigned int,void *),
                                    void (*)(const char *,const char *),int *);
void full_adf_set_output_snapshot(struct full_adf_set_output_snapshot *);
#ifdef FULL_ADF_SET_OUTPUT_TEST
void full_adf_set_output_test_event_limit(unsigned int);
#endif
#endif
