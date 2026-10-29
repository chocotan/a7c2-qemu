/* SPDX-License-Identifier: MIT */
#ifndef FULL_SCALAR_CONNECTION_H
#define FULL_SCALAR_CONNECTION_H
#include "adf-proc-device.h"
#define FULL_PINMEM_SCALAR_CONNECTION_PROFILE "virtual-pinmem-out1-scalar-in4-v1"
#define FULL_PINMEM_PEER_CONNECTIONS_PROFILE "virtual-pinmem-scalar-adf-drawinfo-chain-v1"
struct scalar_connection_snapshot {
    unsigned int started,faults,pending_event6,event6_consumed,yc_callback_seen,yc_format_published;
    unsigned int source_state,peer_state;
    unsigned long long connections,native_reply_frees,waiter_frees;
    int owner_pid;
    unsigned int initialized,native_guarded,busy,guard_held,requests,clean_completion,ap_consumed;
    unsigned int request_freed,queued,reply_freed,unadmitted_count,retained_messages,releasing_reply,reply_destination;
    unsigned int event6_enqueued,event6_inflight,event6_token,event6_token_verified,event6_peer_verified;
    unsigned int context_kind,phase,wait_primary,wait_secondary,keep_pending;
    unsigned int post_callback_type,manager_calls,manager_return;
    unsigned int original_CP_event_pointer_identity_verified,original_RTOS_scheduling_verified;
    unsigned char saved_request[64],event6_parameter[12];
    unsigned long long saved_request_fnv,event6_parameter_fnv;
    void *event6_answer,*event6_body,*live_reply,*retained_request,*retained_cleanup;
};
/* Native entry points use the same instances as the legacy dispatcher. They
 * require explicit PID construction, the predecessor and cold Get/free state,
 * and one resource reservation. A virtual 12B event6 parameter maps an owned
 * reply body using a 32-bit token; it carries no native or CP pointer. Callbacks
 * run outside the private mutex. AP consumption requires the original sender
 * thread's successful free. The finite native ordering defers the AP reply
 * until the source post-callback has returned; RTOS timing is not modeled. */
int full_scalar_connection_owner_init(void);
int full_scalar_connection_native_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_scalar_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_scalar_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_scalar_connection_snapshot(struct scalar_connection_snapshot *);
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void full_scalar_connection_test_event_corrupt(unsigned int);
int full_scalar_connection_test_event_consume(const struct full_imaging_io *);
#endif
#ifdef FULL_PIN_CONNECTION_TEST
void full_scalar_connection_test_reset(void);
#endif
#endif
