/* SPDX-License-Identifier: MIT */
#ifndef FULL_PINMEM_HDMI_VIDEO_CONNECTION_H
#define FULL_PINMEM_HDMI_VIDEO_CONNECTION_H
#include "scalar-connection.h"
#define FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE "virtual-pinmem-video0-hdmi-video0-initializing-v1"
struct full_pinmem_hdmi_video_connection_snapshot {
    struct scalar_connection_snapshot connection;
    unsigned int source_gate_known,source_gate,source_history_known,source_inputs;
    unsigned int peer_waiting,peer_ready,progressing,request_owned;
    long sender_tid,producer_tid;
};
/* Construct before any PinMem input: the public VideoRawManager constructor
 * clears its +0x68 word, including the +0x6a gate. No gate reset at Connect.
 * Observe every PinMem input before dispatch; anything beyond the audited
 * 1000 Get/Connect prefix invalidates this finite source history. */
int full_pinmem_hdmi_video_connection_owner_init(void);
int full_pinmem_hdmi_video_connection_observe_input(unsigned int,const void *,unsigned int);
/* Requires the actual guarded tenth edge and canonical retired Get keys.
 * Admission transfers the original request to this asynchronous owner and
 * returns send-success even while pending/faulted; only a unique 56B reply
 * indicates completion. Before admission the caller still owns its request.
 * Resource reservations cover one progress slice and are released before an
 * asynchronous wait, so a POSIX mutex is never unlocked by another thread.
 * The guard must admit this owner's known pending S7=2/P0=0 reservation on
 * resumption; the endpoint rechecks the complete saved registries each time.
 * Receive/free instrumentation calls progress outside all resource locks. */
int full_pinmem_hdmi_video_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
/* Call after HDMI's actual receive/free or driver completion, outside that
 * owner's locks. No worker, polling, sleep, fake receive or forced-ready bit.
 * 0=idle/completed, 1=pending/reentrant, -1021=fault. */
int full_pinmem_hdmi_video_connection_progress(void);
int full_pinmem_hdmi_video_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *);
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void full_pinmem_hdmi_video_connection_test_event_corrupt(unsigned int);
#endif
#endif
