/* SPDX-License-Identifier: MIT */
#ifndef FULL_INFRABB_VEF_CONTROL_CONNECTION_H
#define FULL_INFRABB_VEF_CONTROL_CONNECTION_H
#include "adf-proc-device.h"
#define FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE "virtual-infrabb-control0-vef-control0-v1"
struct full_infrabb_vef_control_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,unadmitted_count,connections,queued;
    unsigned int clean_completion,ap_consumed,request_freed,reply_freed,peer_requests,peer_replies;
    unsigned int source_posthook_checked,source_posthook_no_format,source_marker_skipped;
    unsigned int posthook_checked,posthook_no_format,peer_ordinal,callback_selected,predecessor_preserved;
    unsigned int dmm_allocations,notifications,cache_writes,marker_writes,clock_writes,mmio_writes;
    unsigned int retained_messages,releasing_reply,reply_destination;
    void *live_reply,*retained_request,*retained_cleanup;
};
/* One finite BB type8 OUT0 -> VEF type8 IN0 edge, after four clean AP-consumed
 * edges. Uses the existing registries; VEF ordinal14 selects no format work.
 * Early refusal leaves the request caller-owned and the one-shot unused.
 * The shared resource guard covers all predecessor owners. All callbacks run
 * outside our private mutex; the PID check precedes inherited locks.
 * A zero dispatch result transfers ownership; presend failure does not.
 * Failed local frees remain retained and faulted; recovery never clears faults.
 * No original CP/RTOS, hardware marker, format, pixel or capture claim. */
int full_infrabb_vef_control_connection_owner_init(void);
int full_infrabb_vef_control_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_infrabb_vef_control_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_infrabb_vef_control_connection_snapshot(struct full_infrabb_vef_control_connection_snapshot *);
#endif
