/* SPDX-License-Identifier: MIT */
#ifndef FULL_INFRABB_VEF_CONNECTION_H
#define FULL_INFRABB_VEF_CONNECTION_H
#include "adf-proc-device.h"
#include "infrabb-vef-format.h"
#define FULL_INFRABB_VEF_CONNECTION_PROFILE "virtual-infrabb-out1-vef-in1-same-format-v1"
struct full_infrabb_vef_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,unadmitted_count,connections,queued;
    unsigned int clean_completion,ap_consumed,request_freed,reply_freed,peer_requests,peer_replies;
    unsigned int source_posthook_checked,source_posthook_no_format,predecessor_preserved;
    unsigned int command_prepared,command_executed,local_commands_inflight,local_commands_returned;
    unsigned int buffer_handle,buffer_cp_virtual,buffer_opened,buffer_closed,buffer_transferred,buffer_freed,format_consumed;
    unsigned int dmm_allocations,dmm_creator_closes,dmm_opens,dmm_consumer_closes,dmm_frees;
    unsigned int retained_messages,releasing_reply,reply_destination;
    unsigned long long buffer_physical,buffer_fnv;
    void *live_reply,*retained_request,*retained_cleanup;
    struct full_infrabb_vef_format format;
    unsigned int forwarded_vef_formats,forwarded_bb_formats,forwarded_format_handle;
};
/* One virtual BB OUT1 -> VEF IN1 edge; same-format only. Requires the original
 * three new edges and existing VEF/PinMem + S0/NoMem owners to remain intact.
 * Precondition refusal does not consume the one-shot request or latch a fault.
 * The shared guard must reserve these resources; callbacks run outside our lock.
 * A result of 0 transfers request ownership. Any presend failure leaves the
 * request with its caller; mapped buffer/failed local frees remain faulted.
 * Reply publication is deferred until finite format work/Close/Free completes;
 * this is an explicit ordering policy, not CP RTOS scheduling equivalence. */
int full_infrabb_vef_connection_owner_init(void);
int full_infrabb_vef_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_infrabb_vef_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_infrabb_vef_connection_snapshot(struct full_infrabb_vef_connection_snapshot *);
/* Caller holds the common resource guard and has opened the same consumer H.
 * These one-shot SSYN01 readers only update this owner's existing live caches;
 * they never allocate, change references, forward notifications or touch the
 * fourth-edge command/buffer history. io is optional and used only for record.
 * Refusal returns -1021 without changing this owner; actual reads still count. */
int full_infrabb_vef_connection_accept_forwarded_vef_format(unsigned int handle,const struct full_imaging_io *io);
int full_infrabb_vef_connection_accept_forwarded_bb_format(unsigned int handle,const struct full_imaging_io *io,int *changed);
#endif
