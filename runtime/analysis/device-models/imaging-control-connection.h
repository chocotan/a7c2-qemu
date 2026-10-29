/* SPDX-License-Identifier: MIT */
#ifndef FULL_IMAGING_CONTROL_CONNECTION_H
#define FULL_IMAGING_CONTROL_CONNECTION_H
#include "adf-proc-device.h"
#define FULL_IMAGING_CONTROL_CONNECTION_PROFILE "virtual-imaging-control0-bb-control0-v1"
struct full_imaging_control_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,connections,queued;
    unsigned int clean_completion,ap_consumed,request_freed,reply_freed;
    unsigned int peer_requests,peer_replies,peer_marker,peer_marker_known,peer_marker_writes;
    unsigned int posthook_checked,posthook_no_format,retained_messages,releasing_reply;
    unsigned int reply_destination;
    void *live_reply,*retained_request,*retained_cleanup;
};
/* One source-derived virtual type8 edge. The sink index0 posthook returns before
 * DMM/SSYN; the completed OUT1 data edge and its backing remain unchanged.
 * A handled result of 0 transfers request ownership; any other result leaves it
 * with the caller, without a retained_request reference. Concurrent Get changes
 * may conservatively refuse this finite transaction; no global CP idle claim. */
int full_imaging_control_connection_owner_init(void);
int full_imaging_control_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,
                                             const struct full_adf_proc_guard *,int,int *);
int full_imaging_control_connection_release(unsigned int,void *,int (*)(unsigned int,void *),
                                            void (*)(const char *,const char *),int *);
void full_imaging_control_connection_snapshot(struct full_imaging_control_connection_snapshot *);
#endif
