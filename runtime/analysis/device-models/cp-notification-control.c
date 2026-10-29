/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-notification-control.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct native_cp_notification_snapshot state;
static struct full_imaging_io transport;
static unsigned int releasing,publication_started;
static _Thread_local unsigned int inspecting;
static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int pid=atomic_load(&owner_pid);return pid && pid!=getpid(); }
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static unsigned int u32(const unsigned char *p) { return u16(p)|u16(p+2)<<16; }
static void fault(void) { state.faults=1;state.clean_completion=state.ap_consumed=0; }
static void refresh(void) {
    state.clean_completion=state.queued && state.request_freed && state.reply_freed &&
        state.d018_readback && !state.busy && !state.guard_held && !state.faults &&
        !state.retained_request && !state.live_reply && !state.retained_cleanup &&
        state.sender_tid==state.waiter_tid;
    state.ap_consumed=state.clean_completion;
}
void native_cp_notification_snapshot(struct native_cp_notification_snapshot *out) {
    if(!out)return;
    if(inherited()) { *out=(struct native_cp_notification_snapshot){.owner_pid=atomic_load(&owner_pid),.faults=1};return; }
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=atomic_load(&owner_pid);pthread_mutex_unlock(&mutex);
}
static void hex(char *out,const unsigned char *p) {
    for(unsigned int i=0;i<12;i++)snprintf(out+2*i,3,"%02x",p[i]);
    out[24]=0;
}
static void record(void (*logger)(const char *,const char *),const char *event) {
    if(!logger)return;
    struct native_cp_notification_snapshot s;native_cp_notification_snapshot(&s);
    char tag[100],line[1100],request[25],reply[25],notice[25];
    hex(request,s.request_wire);hex(reply,s.reply_wire);hex(notice,s.d018_wire);
    snprintf(tag,sizeof tag,"NATIVE_CP_NOTIFICATION_%s ",event);
    snprintf(line,sizeof line,"pid=%d sender_tid=%ld waiter_tid=%ld requests=%u busy=%u guard=%u faults=%u destination=%#x request=%s reply=%s d018=%s d018_source=%#x d018_destination=%#x d018_bytes=%u d018_consumed=%u d018_readback=%u startup_sticky=%u d013_registered=%u allocate_rc=%d send_rc=%d request_free_rc=%d reply_free_rc=%d queued=%u request_freed=%u reply_freed=%u ap_consumed=%u retained_request=%p live_reply=%p retained_cleanup=%p virtual_mode_policy=1 notification_mode=%u source_byte1_known=0 virtual_padding=1 internal_virtual_consumer=1 original_OSAL_delivery=0 virtual_publish_after_consumer=1 diagnostic_only=1 native_verified=0 CP_history_verified=0 pending_complete=0 full_snapshot=0 frame=0 capture=0",
        getpid(),s.sender_tid,s.waiter_tid,s.requests,s.busy,s.guard_held,s.faults,s.destination,
        request,reply,notice,s.d018_source,s.d018_destination,s.d018_bytes,s.d018_consumed,
        s.d018_readback,s.startup_sticky,s.d013_registered,s.allocate_rc,s.send_rc,
        s.request_free_rc,s.reply_free_rc,s.queued,s.request_freed,s.reply_freed,s.ap_consumed,
        s.retained_request,s.live_reply,s.retained_cleanup,s.notification_mode);
    logger(tag,line);
}
int native_cp_notification_owner_init(void) {
    int expected=0,pid=getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(atomic_load(&owner_pid)!=pid)return -1021;
    pthread_mutex_lock(&mutex);
    if(state.initialized || state.faults || state.busy) { pthread_mutex_unlock(&mutex);return -1021; }
    /* Explicit virtual policy, not an original CP RAM initializer. */
    state.initialized=state.virtual_mode_policy=state.virtual_padding=1;
    state.notification_mode=state.startup_sticky=state.d013_registered=0;
    pthread_mutex_unlock(&mutex);return 0;
}
static int release_owned(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                         void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(inherited()) {
        if(pointer!=state.live_reply && pointer!=state.retained_request && pointer!=state.retained_cleanup)return 0;
        *result=-1021;return 1;
    }
    unsigned int kind,expected;unsigned char observed[12];long freeing=tid();
    pthread_mutex_lock(&mutex);
    if(pointer==state.live_reply) { kind=1;expected=state.destination; }
    else if(pointer==state.retained_request) { kind=2;expected=NATIVE_CP_NOTIFICATION_SID; }
    else if(pointer==state.retained_cleanup) { kind=4;expected=state.destination; }
    else { pthread_mutex_unlock(&mutex);return 0; }
    int rc=-1021;
    if(destination!=expected || (releasing&kind) || (kind==2 && state.busy && !internal) ||
       (kind==1 && !publication_started && !internal))fault();
    else {
        releasing|=kind;pthread_mutex_unlock(&mutex);
        if(kind==1) {
            unsigned int bytes=transport.size(pointer),source=transport.source(pointer);
            if(bytes==12)memcpy(observed,pointer,12);
            pthread_mutex_lock(&mutex);
            state.reply_free_destination=destination;state.reply_free_source=source;state.reply_free_bytes=bytes;
            if(bytes==12)memcpy(state.freed_reply_wire,observed,12);
            if(bytes!=12 || source!=NATIVE_CP_NOTIFICATION_SID || (bytes==12 && memcmp(observed,state.reply_wire,12)))fault();
            pthread_mutex_unlock(&mutex);
        }
        rc=release(destination,pointer);pthread_mutex_lock(&mutex);
        releasing&=~kind;
        if(rc)fault();
        else if(kind==1) {
            state.live_reply=NULL;state.reply_freed=1;
            if(!internal) { state.waiter_tid=freeing;if(freeing!=state.sender_tid)fault(); }
        } else if(kind==2) { state.retained_request=NULL;state.request_freed=1; }
        else state.retained_cleanup=NULL;
    }
    if(kind==1)state.reply_free_rc=rc;
    if(kind==2)state.request_free_rc=rc;
    if(kind==4 && rc)state.reply_free_rc=rc;
    refresh();pthread_mutex_unlock(&mutex);
    record(logger,kind==1?"REPLY_FREE":kind==2?"REQUEST_FREE":"CLEANUP_FREE");
    *result=rc;return 1;
}
int native_cp_notification_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                                         void (*logger)(const char *,const char *),int *result) {
    return release_owned(destination,pointer,release,logger,result,0);
}
static int admissible(void) {
    return state.initialized && state.virtual_mode_policy && !state.notification_mode &&
        !state.faults && !state.requests && !state.busy && !state.guard_held &&
        !state.retained_request && !state.live_reply && !state.retained_cleanup;
}
static void finish(const struct native_cp_notification_guard *guard) {
    pthread_mutex_lock(&mutex);unsigned int held=state.guard_held;pthread_mutex_unlock(&mutex);
    if(held)guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=state.busy=0;refresh();pthread_mutex_unlock(&mutex);
}
static int consume_d018(unsigned int destination,unsigned int source,const unsigned char *wire,unsigned int bytes) {
    pthread_mutex_lock(&mutex);
    int valid=destination==FULL_IMAGING_CP && source==NATIVE_CP_NOTIFICATION_SID && bytes==12 &&
        wire && wire[0]==5 && u16(wire+2)==0xd018 && !u32(wire+4) && state.requests==1 &&
        state.busy && !state.faults && !state.notification_mode && !state.d013_registered && !state.d018_consumed;
    if(valid) {
        memcpy(state.d018_wire,wire,12);state.d018_source=source;
        state.d018_destination=destination;state.d018_bytes=bytes;
        /* 459040 -> 4586d0: with no D013 registration, sticky is the full effect. */
        if(!state.startup_sticky)state.startup_sticky=1;
        state.d018_consumed=1;
    } else fault();
    pthread_mutex_unlock(&mutex);return valid;
}
int native_cp_notification_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                    const struct native_cp_notification_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP_NOTIFICATION_SID || !request || !io || !result)return 0;
    if(inherited() || inspecting) { *result=-1021;return 1; }
    if(!io->size)return 0;
    /* Avoid recursion through envelope inspection callbacks, before admission. */
    inspecting=1;unsigned int bytes=io->size(request);inspecting=0;const unsigned char *p=request;
    if(bytes<4 || p[0]!=5 || u16(p+2)!=0x4073)return 0;
    *result=-1021;
    if(bytes!=12 || p[8] || !io->source || !io->allocate || !io->set_source || !io->send || !io->release ||
       !guard || !guard->reserve || !guard->release || !guard->predecessor_ready)return 1;
    inspecting=1;unsigned int caller=io->source(request);inspecting=0;
    if(caller!=FULL_IMAGING_AP)return 1;
    unsigned char request_wire[12],reply_wire[12]={1,0,0x73,0x40,0,0,0,0,0,0xf0,0,0};
    const unsigned char notice[12]={5,0,0x18,0xd0,0,0,0,0,0,0,0,0};
    memcpy(request_wire,request,12);memcpy(reply_wire+4,request_wire+4,4);
    pthread_mutex_lock(&mutex);
    if(!admissible()) { pthread_mutex_unlock(&mutex);return 1; }
    state.busy=1;pthread_mutex_unlock(&mutex);
    int rc=guard->reserve();
    if(rc) { finish(guard);*result=rc;return 1; }
    pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    if(guard->predecessor_ready()!=1) { finish(guard);return 1; }
    void *reply=NULL;rc=io->allocate(caller,&reply,12,1);
    uintptr_t a=(uintptr_t)reply,b=(uintptr_t)request;
    int alias=reply && (a<=b?b-a<12:a-b<12);
    int valid=!rc && reply && !alias && io->size(reply)==12;
    if(valid) {
        memcpy(reply,reply_wire,12);io->set_source(reply,NATIVE_CP_NOTIFICATION_SID);
        valid=io->source(reply)==NATIVE_CP_NOTIFICATION_SID && io->size(reply)==12 && !memcmp(reply,reply_wire,12);
    }
    valid=valid && guard->predecessor_ready()==1 && io->size(request)==12 &&
        io->source(request)==caller && !memcmp(request,request_wire,12);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;valid=valid && !state.faults;
    if(!valid) {
        if(alias || reply || !rc)fault();
        if(reply && !alias) { state.retained_cleanup=reply;state.destination=caller; }
        pthread_mutex_unlock(&mutex);
        if(reply && !alias) { int freed;release_owned(caller,reply,io->release,io->record,&freed,1); }
        finish(guard);*result=rc?rc:-1021;record(io->record,"REFUSED");return 1;
    }
    state.requests=1;state.cookie=u32(request_wire+4);state.destination=caller;state.sender_tid=tid();
    state.retained_request=request;state.live_reply=reply;
    memcpy(state.request_wire,request_wire,12);memcpy(state.reply_wire,reply_wire,12);transport=*io;
    pthread_mutex_unlock(&mutex);record(io->record,"REQUEST");
    valid=consume_d018(FULL_IMAGING_CP,NATIVE_CP_NOTIFICATION_SID,notice,12);
    struct native_cp_notification_snapshot readback;native_cp_notification_snapshot(&readback);
    valid=valid && readback.startup_sticky==1 && !readback.d013_registered && readback.d018_consumed==1 &&
        readback.d018_source==NATIVE_CP_NOTIFICATION_SID && readback.d018_destination==FULL_IMAGING_CP &&
        readback.d018_bytes==12 && !memcmp(readback.d018_wire,notice,12);
    pthread_mutex_lock(&mutex);
    valid=valid && !state.faults;
    if(valid)state.d018_readback=1;else fault();
    pthread_mutex_unlock(&mutex);record(io->record,valid?"D018_CONSUMED":"D018_REFUSED");
    pthread_mutex_lock(&mutex);rc=state.faults || !state.d018_readback?-1021:0;
    if(!rc)publication_started=1;
    pthread_mutex_unlock(&mutex);
    if(!rc)rc=io->send(caller,reply);
    pthread_mutex_lock(&mutex);state.send_rc=rc;
    if(rc)fault();else state.queued=1;
    int cleanup=rc && state.live_reply && !(releasing&1);pthread_mutex_unlock(&mutex);
    if(rc) {
        if(cleanup) { int freed;release_owned(caller,reply,io->release,io->record,&freed,1); }
    } else {
        record(io->record,"REPLY_QUEUED");
        int freed;release_owned(destination,request,io->release,io->record,&freed,1);
    }
    finish(guard);record(io->record,rc?"FAULT":"COMMIT");*result=0;return 1;
}
#ifdef NATIVE_CP_NOTIFICATION_TEST
void native_cp_notification_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_cp_notification_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
