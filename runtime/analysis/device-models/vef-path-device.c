/* SPDX-License-Identifier: MIT
 * Explicit opt-in virtual PathProcessNoMem control consumption; never executes CP code.
 * Contract: report/vef-path-frontier.md, 2002:1001 -> 2a6 -> E | 005a0000. */
#include "vef-path-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static int current_process(void) {
    int pid=(int)getpid(),expected=0;
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return atomic_load(&owner_pid)==pid;
}
int full_vef_path_owner_init(void) { return current_process()?0:-1021; }
/* raw5f8324..5f832c clears S+0x20, including the independent status halfword at +0x22. */
#define COLD_STATE { .current_path=0x14, .phase=1, .state=2, \
    .runtime_status22=0, .runtime_status22_known=1, \
    .runtime_status22_writer_generation=0, .runtime_status22_writes=0, \
    .cached_handles={FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY} }
static struct full_vef_path_snapshot state=COLD_STATE;
#ifdef FULL_VEF_PATH_TEST
static int stale_generation;
#endif
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static unsigned int u32(const unsigned char *p) { return u16(p)|u16(p+2)<<16; }
static void event(void (*record)(const char *,const char *),const char *tag,const char *text) {
    char line[1100];
    snprintf(line,sizeof line,"%s scope=virtualNoMemOnly original_cp_executed=0 hardware_verified=0 frames_verified=0 capture_verified=0 global_dmm_idle_claim=0",text);
    if (record) record(tag,line);
}
static int reject(const struct full_imaging_io *io,int *result,const char *why) {
    event(io->record,"FULL_VEF_PATH_UNSUPPORTED ",why);*result=-1021;return 1;
}
static int eligible(void) {
    if (state.state!=2 || state.work_pending || state.extra_resource || state.pending_context) return 0;
    if (!((state.current_path==0x14 && state.phase==1) || (state.current_path==1 && state.phase==2))) return 0;
    for (unsigned int i=0;i<4;i++) if (state.cached_handles[i]!=FULL_VEF_PATH_EMPTY) return 0;
    return 1;
}
/* Caller holds mutex; latch faults before dropping the common resource gate. */
static void finish(const struct full_vef_path_guard *guard) {
    guard->release();state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
}
static int fail(const struct full_imaging_io *io,const struct full_vef_path_guard *guard,
                int *result,int rc,const char *why,unsigned int owner,void *reply) {
    state.faults++;state.clean_completion=0;
    if (reply) {
        state.cleanup_free_rc=io->release(owner,reply);
        if (state.cleanup_free_rc) {
            state.retained_cleanup_reply=reply;state.retained_cleanup_owner=owner;
        } else state.cleanup_freed++;
    }
    char text[680];
    snprintf(text,sizeof text,"reason=%s rc=%d allocate_rc=%d send_rc=%d reply=%p owner=%#x cleanup_free_rc=%d retained_cleanup=%u generation=%u current_path=%u phase=%u work_pending=%u applications=%llu normal_completion=0",
        why,rc,state.allocate_rc,state.send_rc,reply,owner,state.cleanup_free_rc,
        (unsigned int)(state.retained_cleanup_reply!=0),state.generation,state.current_path,
        state.phase,state.work_pending,state.applications);
    event(io->record,"FULL_VEF_PATH_FAULT ",text);
    finish(guard);*result=rc;return 1;
}
/* Immutable virtual 20B request; the generation is part of the consumed data. */
static int process_nomem(const unsigned char inner[20]) {
    static const unsigned char header[8]={2,0x20,1,0,20,0,1,0};
    state.inner_generation=u16(inner+10);
    if (memcmp(inner,header,8) || u16(inner+8)!=1 ||
        state.inner_generation!=state.generation || !state.work_pending || state.phase!=0)
        return -1021;
    /* Empty descriptors require no DMM release; a nonempty handle is refused. */
    if (state.cached_handles[1]!=FULL_VEF_PATH_EMPTY || state.cached_handles[2]!=FULL_VEF_PATH_EMPTY)
        return -1021;
    state.selected_object=FULL_VEF_PATH_NOMEM;state.property=2;state.input_selection=0x38;
    state.stage0_done=1;
    state.stage1_done=1;
    state.state=2;state.current_path=u16(inner+8);state.phase=2;state.work_pending=0;
    return 0;
}

int full_vef_path_dispatch(unsigned int destination,void *request,
                           const struct full_imaging_io *io,const struct full_vef_path_guard *guard,
                           int enabled,int *result) {
    if (destination!=FULL_VEF_PATH_INPUT || !request || !io || !io->size || !result || enabled!=1) return 0;
    /* Inherited callbacks may also own locks; do not invoke any in a child. */
    if (!current_process()) { *result=-1021;return 1; }
    const unsigned char *in=request;
    unsigned int bytes=io->size(request);
    if (bytes<4 || u16(in)!=0x200d || u16(in+2)!=0x149) return 0;
    if (!io->allocate || !io->release || !io->source || !io->set_source || !io->send)
        return reject(io,result,"missing-transport");
    if (bytes!=10) return reject(io,result,"only-ten-byte-0149-is-modeled");
    unsigned char input[10];memcpy(input,request,sizeof input);
    if (u16(input)!=0x200d || u16(input+2)!=0x149 || u16(input+4)!=10 ||
        u16(input+6)!=0x8001 || u16(input+8)!=1)
        return reject(io,result,"only-valid-path-one-is-modeled");
    unsigned int caller=io->source(request);
    if ((caller>>28)!=8 || !(caller&0x0fffffff)) return reject(io,result,"nonlocal-caller");
    if (!guard || !guard->reserve || !guard->release) return reject(io,result,"missing-common-resource-reservation");
    pthread_mutex_lock(&mutex);
    if (state.busy || state.faults || state.live_replies) {
        pthread_mutex_unlock(&mutex);return reject(io,result,"busy-fault-or-live-reply");
    }
    state.busy=1;state.configured=1;state.requests++;state.clean_completion=0;
    char text[840];
    snprintf(text,sizeof text,"destination=%#x caller=%#x request=%p bytes=10 raw=0d2049010a0001800100 requests=%llu",
        destination,caller,request,state.requests);
    event(io->record,"FULL_VEF_PATH_REQUEST ",text);
    pthread_mutex_unlock(&mutex);
    int rc=guard->reserve();
    pthread_mutex_lock(&mutex);
    if (rc) {
        state.retained_request=request;state.retained_request_owner=FULL_VEF_PATH_INPUT;
        state.faults++;state.clean_completion=0;
        snprintf(text,sizeof text,"request_accepted=1 request=%p request_owner=%#x reservation_rc=%d common_guard_held=0 reply_queued=0 normal_completion=0 ap_consumed=0 faulted_pending=1",
            request,FULL_VEF_PATH_INPUT,rc);
        state.busy=0;
        event(io->record,"FULL_VEF_PATH_PENDING ",text);
        pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    state.guard_held=1;
    if (!eligible()) {
        snprintf(text,sizeof text,"owned-state-not-idle path=%u phase=%u state=%u cache=%08x,%08x,%08x,%08x extra=%u context=%u work=%u normal_completion=0",
            state.current_path,state.phase,state.state,state.cached_handles[0],state.cached_handles[1],
            state.cached_handles[2],state.cached_handles[3],state.extra_resource,state.pending_context,state.work_pending);
        event(io->record,"FULL_VEF_PATH_UNSUPPORTED ",text);
        finish(guard);*result=-1021;return 1;
    }
    if (state.generation>=0xffffu)
        return fail(io,guard,result,-1021,"generation-exhausted",caller,0);
    pthread_mutex_unlock(&mutex);
    void *reply=0;
    rc=io->allocate(caller,&reply,12,1);
    pthread_mutex_lock(&mutex);
    state.allocate_rc=rc;
    if (reply==request)
        return fail(io,guard,result,-1021,"allocator-returned-caller-owned-request",caller,0);
    unsigned int reply_bytes=reply && !rc?io->size(reply):0;
    if (rc || !reply || reply_bytes!=12) {
        snprintf(text,sizeof text,"allocation-or-size reply_bytes=%u",reply_bytes);
        return fail(io,guard,result,rc?rc:-1021,text,caller,reply);
    }
    if (!eligible()) return fail(io,guard,result,-1021,"owned-state-changed-during-allocation",caller,reply);
    state.requested_path=u16(input+8);state.generation++;state.phase=0;state.work_pending=1;
    state.stage0_done=0;state.stage1_done=0;
    unsigned int generation=state.generation;
#ifdef FULL_VEF_PATH_TEST
    if (stale_generation) generation--;
#endif
    const unsigned char inner[20]={2,0x20,1,0,20,0,1,0,1,0,
        (unsigned char)generation,(unsigned char)(generation>>8),0,0,0,0,0,0,0,0};
    memcpy(state.inner_request,inner,sizeof inner);
    rc=process_nomem(inner);
    if (rc) return fail(io,guard,result,rc,"backend-rejected-inner-request",caller,reply);
    static const unsigned char completion[12]={2,0x20,1,0x10,12,0,1,0,0,0,0,0};
    memcpy(state.inner_completion,completion,sizeof completion);
    state.execution_status=u32(state.inner_completion+8);
    state.outer_status=state.execution_status|0x005a0000u;
    if (memcmp(state.inner_request,inner,20) || memcmp(state.inner_completion,completion,12) ||
        state.current_path!=state.requested_path || state.phase!=2 || state.state!=2 ||
        state.selected_object!=FULL_VEF_PATH_NOMEM || state.property!=2 || state.input_selection!=0x38 ||
        !state.stage0_done || !state.stage1_done || !eligible() || state.outer_status!=0x005a0000u)
        return fail(io,guard,result,-1021,"virtual-state-readback-failed",caller,reply);
    /* raw109c76 sets S+0x22 from the requested path after the path record update. */
    state.runtime_status22=state.requested_path;state.runtime_status22_known=1;
    state.runtime_status22_writer_generation=state.generation;state.runtime_status22_writes++;
    if (!state.runtime_status22_known || state.runtime_status22!=state.current_path ||
        state.runtime_status22_writer_generation!=state.inner_generation ||
        state.runtime_status22_writes!=state.applications+1u)
        return fail(io,guard,result,-1021,"runtime-status22-readback-failed",caller,reply);
    state.applications++;
    snprintf(text,sizeof text,"generation=%u inner_generation=%u requested_path=%u current_path=%u phase=%u state=%u object=PathProcessNoMem property=%u input_selection=%#x stage0_done=%u stage1_done=%u cache=%08x,%08x,%08x,%08x extra=%u context=%u work=%u execution_status=%#x outer_status=%#x common_guard_held=1 dmm_release_calls=0 applications=%llu inner_completion=022001100c00010000000000",
        state.generation,state.inner_generation,state.requested_path,state.current_path,state.phase,state.state,
        state.property,state.input_selection,state.stage0_done,state.stage1_done,state.cached_handles[0],
        state.cached_handles[1],state.cached_handles[2],state.cached_handles[3],state.extra_resource,
        state.pending_context,state.work_pending,state.execution_status,state.outer_status,state.applications);
    size_t used=strlen(text);
    snprintf(text+used,sizeof text-used," inner_request=02200100140001000100%02x%02x0000000000000000 runtime_status22=%u runtime_status22_known=%u runtime_status22_writer_generation=%u runtime_status22_writes=%u",
        inner[10],inner[11],state.runtime_status22,state.runtime_status22_known,
        state.runtime_status22_writer_generation,state.runtime_status22_writes);
    event(io->record,"FULL_VEF_PATH_APPLIED ",text);
    unsigned char response[12]={0x0d,0x20,0x49,0x11,12,0,1,0x80,
        (unsigned char)state.outer_status,(unsigned char)(state.outer_status>>8),
        (unsigned char)(state.outer_status>>16),(unsigned char)(state.outer_status>>24)};
    memcpy(reply,response,sizeof response);io->set_source(reply,FULL_VEF_PATH_INPUT);
    if (io->size(reply)!=12 || io->source(reply)!=FULL_VEF_PATH_INPUT || memcmp(reply,response,12))
        return fail(io,guard,result,-1021,"reply-readback-failed",caller,reply);
    state.live_reply=reply;state.reply_owner=caller;state.live_replies=1;
    rc=io->send(caller,reply);state.send_rc=rc;
    if (rc) {
        state.live_reply=0;state.reply_owner=0;state.live_replies=0;
        return fail(io,guard,result,rc,"send-failed-applied-state-retained",caller,reply);
    }
    state.queued++;
    snprintf(text,sizeof text,"destination=%#x source=%#x reply=%p generation=%u bytes=12 raw=0d2049110c00018000005a00 queued=%llu",
        caller,FULL_VEF_PATH_INPUT,reply,state.generation,state.queued);
    event(io->record,"FULL_VEF_PATH_QUEUED ",text);
    rc=io->release(FULL_VEF_PATH_INPUT,request);state.request_free_rc=rc;
    if (rc) {
        state.retained_request=request;state.retained_request_owner=FULL_VEF_PATH_INPUT;state.faults++;
    } else state.request_freed++;
    state.clean_completion=!state.faults;
    snprintf(text,sizeof text,"generation=%u current_path=%u phase=%u state=%u request=%p request_owner=%#x request_free_rc=%d retained_request=%u queued=%llu clean_completion=%u ap_consumed=0",
        state.generation,state.current_path,state.phase,state.state,request,FULL_VEF_PATH_INPUT,rc,
        (unsigned int)(state.retained_request!=0),state.queued,state.clean_completion);
    event(io->record,rc?"FULL_VEF_PATH_FAULT ":"FULL_VEF_PATH_COMMIT ",text);
    finish(guard);*result=0;return 1;
}

int full_vef_path_release_reply(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                              void (*record)(const char *,const char *),int *result) {
    if (!reply || !release || !result) return 0;
    if (!current_process()) { *result=-1021;return 1; }
    pthread_mutex_lock(&mutex);
    unsigned int owner;
    int kind;
    if (reply==state.retained_cleanup_reply) { kind=0;owner=state.retained_cleanup_owner; }
    else if (reply==state.live_reply) { kind=1;owner=state.reply_owner; }
    else if (reply==state.retained_request) { kind=2;owner=state.retained_request_owner; }
    else { pthread_mutex_unlock(&mutex);return 0; }
    int rc=destination==owner?release(destination,reply):-1021;
    if (kind==0) state.cleanup_free_rc=rc;
    if (kind==1) state.reply_free_rc=rc;
    if (kind==2) state.request_free_rc=rc;
    if (rc) {
        state.faults++;state.clean_completion=0;
        if (kind==1) state.retained_reply=reply;
    } else if (kind==0) {
        state.retained_cleanup_reply=0;state.retained_cleanup_owner=0;state.cleanup_freed++;
    } else if (kind==1) {
        state.live_reply=0;state.reply_owner=0;state.live_replies=0;state.retained_reply=0;state.reply_freed++;
    } else {
        state.retained_request=0;state.retained_request_owner=0;state.request_freed++;
    }
    const char *tag=rc?"FULL_VEF_PATH_FAULT ":kind==0?"FULL_VEF_PATH_CLEANUP_REPLY_FREE ":
        kind==1?"FULL_VEF_PATH_REPLY_FREE ":"FULL_VEF_PATH_REQUEST_FREE ";
    char text[380];
    snprintf(text,sizeof text,"destination=%#x expected=%#x pointer=%p generation=%u kind=%s rc=%d retained=%u faults=%u ap_consumed=%u",
        destination,owner,reply,state.generation,kind==0?"local-cleanup":kind==1?"queued-reply":"original-request",
        rc,(unsigned int)(rc!=0),state.faults,(unsigned int)(!rc && kind==1));
    event(record,tag,text);pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
void full_vef_path_snapshot(struct full_vef_path_snapshot *out) {
    if (!out) return;
    if (!current_process()) {
        *out=(struct full_vef_path_snapshot){.faults=1,.owner_pid=atomic_load(&owner_pid)};return;
    }
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=atomic_load(&owner_pid);pthread_mutex_unlock(&mutex);
}
#ifdef FULL_VEF_PATH_TEST
void full_vef_path_test_reset(void) {
    if (!current_process()) return;
    pthread_mutex_lock(&mutex);state=(struct full_vef_path_snapshot)COLD_STATE;stale_generation=0;pthread_mutex_unlock(&mutex);
}
void full_vef_path_test_resources(const unsigned int handles[4],unsigned int extra,unsigned int pending) {
    if (!current_process()) return;
    pthread_mutex_lock(&mutex);memcpy(state.cached_handles,handles,sizeof state.cached_handles);
    state.extra_resource=extra;state.pending_context=pending;pthread_mutex_unlock(&mutex);
}
void full_vef_path_test_generation(unsigned int generation,int stale) {
    if (!current_process()) return;
    pthread_mutex_lock(&mutex);state.generation=generation;stale_generation=stale;pthread_mutex_unlock(&mutex);
}
void full_vef_path_test_hold_lock(void) { if (current_process()) pthread_mutex_lock(&mutex); }
void full_vef_path_test_drop_lock(void) { if (current_process()) pthread_mutex_unlock(&mutex); }
#endif
