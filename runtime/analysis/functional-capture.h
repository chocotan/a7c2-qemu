/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_CAPTURE_H
#define FUNCTIONAL_CAPTURE_H
#include "device-models/cp-state-publication.h"
#include <stdint.h>
#define FUNCTIONAL_CAPTURE_POLICY "original-consumer-natural4038-software-jpeg-v1"
struct functional_capture_snapshot {
    int owner_pid,enabled,phase,error;
    unsigned request_freed,frame_acquired,input_attached,encoded,frame_released;
    unsigned notification_queued,notification_consumed,saved_verified;
    unsigned write_readback_verified,resources_released,write_token;
    uint64_t write_bytes,write_fnv;
    uint64_t job,request_fnv,frame_token,model_instance;
    uint32_t request_cookie,group;
};
/* Explicit functional profile setup after original libraries are loaded.
 * No model RPC or original queue message is sent by enable. */
int functional_capture_enable(void (*record)(const char *,const char *));
/* Exact natural type5/4038/16B/AP request only. All other messages delegate.
 * Existing imaging inhibit and reserved predecessor gate must both accept.
 * Accepted request is copied and real-freed once before async execution.
 * This endpoint does not create a successful shutter reply. */
int functional_capture_dispatch(unsigned,void *,const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *,int *);
/* Same-job native SENC Open24/Close25 and output-owner app_dmm transactions.
 * Unknown handles delegate; every success represents actual storage/leases. */
int functional_capture_dmm(unsigned,void *,const struct full_imaging_io *,uintptr_t caller,int *);
/* Original sequence ACK/config/terminal packets delegate exactly once through
 * real IO. Retirement requires send0 and the actual original callback's free0. */
int functional_capture_terminal_send(unsigned,void *,const struct full_imaging_io *,int *);
void functional_capture_observe_freed(unsigned,void *,int,uintptr_t caller);
void functional_capture_observe_received(unsigned,void *);
int functional_capture_release_notification(unsigned,void *,int *);
int functional_capture_snapshot(struct functional_capture_snapshot *);
/* Rejects active or unsaved jobs, retaining their buffers and first error.
 * No destructor, implicit CANCEL, unsafe detach or guessed Fsys completion. */
int functional_capture_shutdown(void);
#endif
