/* SPDX-License-Identifier: MIT */
#ifndef FULL_IMAGING_PIN_CONNECTION_H
#define FULL_IMAGING_PIN_CONNECTION_H
#include "adf-proc-device.h"
#include "infraimaging-format.h"
#define FULL_IMAGING_PIN_CONNECTION_PROFILE "virtual-imaging-out1-bb-in1-v1"
struct full_imaging_pin_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,connections,queued,ap_consumed;
    unsigned int clean_completion,request_freed,reply_freed,peer_requests,peer_replies;
    unsigned int buffer_handle,buffer_opened,buffer_transferred,buffer_freed,format_consumed;
    unsigned int dmm_allocations,dmm_creator_closes,dmm_opens,dmm_frees;
    unsigned int synchronization_acquires,synchronization_releases;
    unsigned int peer_connected_marker,peer_connected_marker_known,peer_marker_writes;
    unsigned int retained_messages,releasing_reply;
    unsigned long long buffer_physical,buffer_fnv;
    unsigned int buffer_cp_virtual,reply_destination;
    void *live_reply,*retained_request;
    struct full_infraimaging_format format;
    unsigned int forwarded_formats,forwarded_handle;
};
/* Single source-equivalent virtual edge, synchronous local providers, not CP
 * tasks/RTOS timing. Publish one AP reply only after real mapped SSYN consumption
 * and ownership retirement. Unsupported edges remain caller-owned errors. */
int full_imaging_pin_connection_owner_init(void);
int full_imaging_pin_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,
                                         const struct full_adf_proc_guard *,int,int *);
int full_imaging_pin_connection_release(unsigned int,void *,int (*)(unsigned int,void *),
                                        void (*)(const char *,const char *),int *);
/* Caller holds the common resource guard and validates the notification. Reads
 * the sole open unit404 consumer's mapped SSYN01/type0 into this same OUT1 cache.
 * Caller owns Open/Close/Free; rejection preserves this owner without faulting it.
 * Requires io->record; no other callback is used. The logger may snapshot this
 * owner because it runs outside the owner's mutex. */
int full_imaging_pin_connection_accept_forwarded_format(unsigned int handle,
                                                        const struct full_imaging_io *io);
void full_imaging_pin_connection_snapshot(struct full_imaging_pin_connection_snapshot *);
#endif
