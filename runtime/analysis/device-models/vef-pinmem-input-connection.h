/* SPDX-License-Identifier: MIT */
#ifndef FULL_VEF_PINMEM_INPUT_CONNECTION_H
#define FULL_VEF_PINMEM_INPUT_CONNECTION_H
#include "adf-proc-device.h"
#include "pin-format.h"
#define FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE "virtual-vef-out2-pinmem-in0-forward-format-v1"
struct full_vef_pinmem_input_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,unadmitted_count,connections,queued;
    unsigned int clean_completion,ap_consumed,request_freed,reply_freed,peer_requests,peer_replies;
    unsigned int record_bound,record_index,peer_ordinal,source_slot,predecessor_preserved;
    unsigned int runtime_status22,runtime_status22_known,runtime_status22_writer_generation,runtime_status22_writes;
    unsigned int buffer_handle,buffer_cp_virtual,buffer_bytes,buffer_written,buffer_freed;
    unsigned int dmm_requests,dmm_replies,dmm_allocations,dmm_shares,dmm_creator_releases;
    unsigned int dmm_opens,dmm_consumer_closes,dmm_frees,notifications,notifications_consumed;
    unsigned int current_consumer_sid,vef_format_consumed,bb_format_consumed,bb_format_changed,imaging_format_consumed;
    unsigned int reference_readbacks,owners,opens,creator,consumer,consumer_open;
    unsigned int retained_messages,releasing_reply,reply_destination;
    unsigned long long buffer_physical,buffer_fnv,payload_fnv;
    void *live_reply,*retained_request,*retained_cleanup;
    struct pin_yc_parameters record;
};
/* One OUT2/IN0 edge on the existing VEF and PinMem registries, after five clean
 * AP-consumed connections. Owns the common resource guard once; dispatch BEFORE
 * the legacy VEF send-enter gate. Early refusal consumes neither request nor
 * one-shot. The PinMem record0 is an explicit public-constructor projection,
 * not live negotiation. The tracked SetPath status must have a real writer.
 * Nine DMM messages and three notifications forward one mapped SSYN01 handle
 * through the existing VEF, BB and Imaging live caches, then retire it.
 * io->record is required by the shared Imaging reader. Callbacks run outside
 * our private lock; child PIDs refuse before inherited locks/callbacks.
 * Presend errors leave the request caller-owned. Partial buffers/caches and
 * failed message frees remain faulted; there is no rollback or fault reset.
 * Publication follows finite format consumption, not original RTOS scheduling.
 * No original CP RAM/page-table, pixels, frames or capture claim. */
int full_vef_pinmem_input_connection_owner_init(void);
int full_vef_pinmem_input_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_vef_pinmem_input_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_vef_pinmem_input_connection_snapshot(struct full_vef_pinmem_input_connection_snapshot *);
#endif
