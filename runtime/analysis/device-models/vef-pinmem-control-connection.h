/* SPDX-License-Identifier: MIT */
#ifndef FULL_VEF_PINMEM_CONTROL_CONNECTION_H
#define FULL_VEF_PINMEM_CONTROL_CONNECTION_H
#include "adf-proc-device.h"
#define FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE "virtual-vef-control0-pinmem-control0-v1"
struct full_vef_pinmem_control_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,unadmitted_count,connections,queued;
    unsigned int clean_completion,ap_consumed,request_freed,reply_freed,peer_requests,peer_replies;
    unsigned int source_slot,peer_ordinal,source_ordinal,predecessor_preserved;
    unsigned int manager_calls,manager_return,posthook_checked,posthook_no_format,callback_selected;
    unsigned int event8_enqueued,event8_consumed,event8_pending,event8_inflight,event8_token;
    unsigned int event8_token_verified,event8_peer_verified,original_CP_event_pointer_identity_verified;
    unsigned int dmm_allocations,notifications,cache_writes,marker_writes,clock_writes,mmio_writes;
    unsigned int retained_messages,releasing_reply,reply_destination;
    unsigned char event8_parameter[32];
    void *event8_answer,*event8_body,*live_reply,*retained_request,*retained_cleanup;
    long sender_tid;
};
/* One finite type8 OUT0 -> IN0 edge on the existing VEF/PinMem registries after
 * six clean AP-consumed edges. Dispatch before the legacy VEF send-enter gate.
 * A typed local event8 owns a zeroed 32B parameter; its explicit 32-bit token
 * maps a borrowed independent reply body until consumption, never a truncated
 * host/CP pointer. The consumer validates the saved request and all peer keys
 * before source completion. This is local finite ordering, not RTOS timing or
 * original CP event-pointer identity. PinMem's type8 manager returns zero;
 * VEF's actual table ordinal15 selects no format callback or marker write.
 * Callbacks run outside the private mutex; PID rejection precedes all locks.
 * Presend errors leave the request caller-owned; failed frees/event borrows
 * remain retained and faulted. Cleanup/reinitialization never clears faults.
 * Only a successful original-sender TID free proves AP consumption; other valid
 * frees retire the lease without admitting the next edge.
 * No DMM, live-cache mutation, MMIO, clock, frame or capture claim. */
int full_vef_pinmem_control_connection_owner_init(void);
int full_vef_pinmem_control_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_vef_pinmem_control_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_vef_pinmem_control_connection_snapshot(struct full_vef_pinmem_control_connection_snapshot *);
#ifdef FULL_VEF_TEST
void full_vef_pinmem_control_connection_test_event_corrupt(unsigned int);
int full_vef_pinmem_control_connection_test_event_consume(const struct full_imaging_io *);
#endif
#endif
