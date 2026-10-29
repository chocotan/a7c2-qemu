/* SPDX-License-Identifier: MIT */
#ifndef FULL_IMAGING_ADF_CONNECTION_H
#define FULL_IMAGING_ADF_CONNECTION_H
#include "adf-proc-device.h"
#define FULL_IMAGING_ADF_CONNECTION_PROFILE "virtual-imaging-audio0-adf-audio0-v1"
struct full_imaging_adf_connection_snapshot {
    int owner_pid;
    unsigned int initialized,busy,faults,guard_held,requests,connections,queued;
    unsigned int clean_completion,ap_consumed,request_freed,reply_freed;
    unsigned int peer_requests,peer_replies,callback_guard_checked,callback_selected;
    unsigned int no_format_checked,predecessor_preserved,retained_messages,releasing_reply;
    unsigned int reply_destination;
    void *live_reply,*retained_request,*retained_cleanup;
};
/* One type3 virtual handshake. CP 19743a selects the extra ADF callback only
 * for type5/dir1/index0; this edge has no marker, DMM, PCM or format work.
 * A handled result of 0 transfers request ownership; failure before queuing
 * leaves the original request with its caller, without a retained reference.
 * The supplied guard must reserve the shared prior ADF/BB/control resources. */
int full_imaging_adf_connection_owner_init(void);
int full_imaging_adf_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,
                                         const struct full_adf_proc_guard *,int,int *);
int full_imaging_adf_connection_release(unsigned int,void *,int (*)(unsigned int,void *),
                                        void (*)(const char *,const char *),int *);
void full_imaging_adf_connection_snapshot(struct full_imaging_adf_connection_snapshot *);
#endif
