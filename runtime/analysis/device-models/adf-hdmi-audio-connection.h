/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_HDMI_AUDIO_CONNECTION_H
#define FULL_ADF_HDMI_AUDIO_CONNECTION_H
#include "adf-proc-device.h"
#define FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE "virtual-adf-audio0-hdmi-audio0-v1"
struct full_adf_hdmi_audio_connection_snapshot {
    int owner_pid;
    unsigned int initialized,native_guarded,busy,guard_held,requests,faults;
    unsigned int clean_completion,ap_consumed,connections,queued,request_freed,reply_freed;
    unsigned int unadmitted_count,retained_messages,releasing_reply,reply_destination;
    unsigned int source_slot,peer_ordinal,source_state,peer_state,peer_requests,peer_replies;
    unsigned int source_handler_completed,posthook_checked,callback_selected,predecessor_preserved;
    unsigned int marker_old_known,marker_old,marker_known,marker_value,marker_readbacks;
    unsigned long long marker_writes,native_reply_frees,waiter_frees;
    int marker_owner_pid;
    unsigned int dmm_allocations,notifications,cache_writes,clock_writes,mmio_writes;
    unsigned int original_CP_memory_identity_verified,original_RTOS_scheduling_verified;
    unsigned char saved_request[64];
    long sender_tid;
    void *live_reply,*retained_request,*retained_cleanup;
};
/* Finite source5/OUT0 to HDMI audio5/IN0. The real source handler completes
 * directly, without PinMem event6 or VEF event8. Native AP publication waits
 * for the shared connected-one marker's readback; original RTOS timing is unknown.
 * Dependencies stop at the actual tenth edge, not unsupported video/OSD edges. */
int full_adf_hdmi_audio_connection_owner_init(void);
int full_adf_hdmi_audio_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_adf_hdmi_audio_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_adf_hdmi_audio_connection_snapshot(struct full_adf_hdmi_audio_connection_snapshot *);
#endif
