/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-startup-controls-diagnostic.h"
#include <pthread.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>

struct control {
    struct native_cp_startup_controls_diagnostic_lease s;
    struct full_imaging_io io;
    unsigned int bytes, releasing, reply_started;
};
/* Parent source contract e4fb06a1 (public CP raw base108000, Thumb):
 * 4014 SetCapMode: AP35463d8/send3547168,24B; table10fad80,
 * handler355650/checker35e7e8(apply1); mode@8 and1a5345c/mask can rejectf001.
 * 40c8 SetMRProfileLoad: AP353f41c,328B; table10fb5b4,
 * handler3573a4/checker8db6a0(apply0), all320 body bytes -> queuedb2565c.
 * 4057 SetSettingLoad: AP353f584,12B; table10fb1a4,
 * handler3570ec/checker3644c8(apply0), worker4b98f0.
 * Common independent12B type1/opcode/echo+4/f000 accepted by AP; byte1 is
 * source0 for40c8/4057, unknown for4014 (explicit virtual0 here).
 * Business overrides, queues and waits remain unclosed for ALL THREE.
 * No status16B payload or parameter business state is manufactured here. */
static struct control controls[CP_STARTUP_CONTROLS_COMMANDS] = {
    {.s={.opcode=0x4014}, .bytes=24},
    {.s={.opcode=0x40c8,.source_byte1_known=1}, .bytes=328},
    {.s={.opcode=0x4057,.source_byte1_known=1}, .bytes=12}
};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static unsigned int initialized;
static _Thread_local unsigned int inspecting;
static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int pid=atomic_load(&owner_pid);return pid && pid!=getpid(); }
static unsigned int u16(const unsigned char *p) { return p[0] | (unsigned int)p[1]<<8; }
static uint32_t u32(const unsigned char *p) { return u16(p) | (uint32_t)u16(p+2)<<16; }
static void fault(struct control *c) { c->s.faults=1;c->s.clean_completion=c->s.ap_consumed=0; }
static void refresh(struct control *c) {
    c->s.clean_completion=c->s.queued && c->s.request_freed && c->s.reply_freed &&
        !c->s.busy && !c->s.guard_held && !c->s.faults && !c->releasing &&
        !c->s.retained_request && !c->s.live_reply && !c->s.retained_cleanup && c->s.sender_tid==c->s.waiter_tid;
    c->s.ap_consumed=c->s.clean_completion;
}
void native_cp_startup_controls_diagnostic_snapshot(struct native_cp_startup_controls_diagnostic_snapshot *out) {
    if(!out)return;
    int pid=atomic_load(&owner_pid);
    *out=(struct native_cp_startup_controls_diagnostic_snapshot){.owner_pid=pid,.diagnostic_only=1,.virtual_padding=1};
    if(pid && pid!=getpid()) { out->faults=1;return; }
    pthread_mutex_lock(&mutex);out->initialized=initialized;
    for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++) {
        const struct control *c=&controls[i];out->leases[i]=c->s;out->leases[i].supported=c->bytes!=0;
        out->requests+=c->s.requests;out->completed+=c->s.clean_completion;
        out->busy|=c->s.busy;out->guard_held|=c->s.guard_held;out->faults|=c->s.faults;
    }
    pthread_mutex_unlock(&mutex);
}
int native_cp_startup_controls_diagnostic_owner_init(void) {
    int expected=0,pid=getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(atomic_load(&owner_pid)!=pid)return CP_STARTUP_CONTROLS_SOURCE_BLOCKED;
    pthread_mutex_lock(&mutex);
    if(initialized) { pthread_mutex_unlock(&mutex);return CP_STARTUP_CONTROLS_SOURCE_BLOCKED; }
    initialized=1;pthread_mutex_unlock(&mutex);return 0;
}
static void record(struct control *c,void (*logger)(const char *,const char *),const char *event) {
    if(!logger)return;
    struct native_cp_startup_controls_diagnostic_snapshot snapshot;native_cp_startup_controls_diagnostic_snapshot(&snapshot);
    struct native_cp_startup_controls_diagnostic_lease s=snapshot.leases[c-controls];
    char tag[100],line[2400],request[CP_STARTUP_CONTROLS_REQUEST_MAX*2+1]={0},reply[25],freed[25];
    for(unsigned int i=0;i<s.request_bytes;i++)snprintf(request+2*i,3,"%02x",s.request_wire[i]);
    for(unsigned int i=0;i<12;i++) { snprintf(reply+2*i,3,"%02x",s.reply_wire[i]);snprintf(freed+2*i,3,"%02x",s.freed_reply_wire[i]); }
    snprintf(tag,sizeof tag,"NATIVE_CP_STARTUP_DIAGNOSTIC_%s ",event);
    snprintf(line,sizeof line,"pid=%d opcode=%#x sender_tid=%ld waiter_tid=%ld requests=%u busy=%u guard=%u faults=%u source=%#x request_destination=%#x destination=%#x bytes=%u request=%s cookie=%#x wire_fnv1a32=%#x source_byte1_known=%u reply=%s freed_reply=%s reply_free_destination=%#x reply_free_source=%#x reply_free_bytes=%u allocate_rc=%d send_rc=%d request_free_rc=%d reply_free_rc=%d queued=%u request_freed=%u reply_freed=%u clean_completion=%u ap_consumed=%u retained_request=%p live_reply=%p retained_cleanup=%p diagnostic_only=1 virtual_padding=1 business_applied=0 source_dependencies_closed=0 configured=0 published=0 generation=0 native_cp=0 EE=0 frame=0 capture=0",
        snapshot.owner_pid,s.opcode,s.sender_tid,s.waiter_tid,s.requests,s.busy,s.guard_held,s.faults,s.source,s.request_destination,s.destination,
        s.request_bytes,request,s.cookie,s.request_fnv1a32,s.source_byte1_known,reply,freed,s.reply_free_destination,s.reply_free_source,s.reply_free_bytes,
        s.allocate_rc,s.send_rc,s.request_free_rc,s.reply_free_rc,s.queued,s.request_freed,s.reply_freed,s.clean_completion,
        s.ap_consumed,s.retained_request,s.live_reply,s.retained_cleanup);
    logger(tag,line);
}
static int release_owned(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                         void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(inherited()) {
        for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++) {
            struct control *c=&controls[i];
            if(pointer==c->s.live_reply || pointer==c->s.retained_request || pointer==c->s.retained_cleanup) {
                *result=CP_STARTUP_CONTROLS_SOURCE_BLOCKED;return 1;
            }
        }
        return 0;
    }
    struct control *c=NULL;unsigned int kind=0,expected=0;long freeing=tid();
    pthread_mutex_lock(&mutex);
    for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++) {
        struct control *candidate=&controls[i];
        if(pointer==candidate->s.live_reply) { c=candidate;kind=1;expected=c->s.destination;break; }
        if(pointer==candidate->s.retained_request) { c=candidate;kind=2;expected=NATIVE_CP_STARTUP_CONTROLS_SID;break; }
        if(pointer==candidate->s.retained_cleanup) { c=candidate;kind=4;expected=FULL_IMAGING_AP;break; }
    }
    if(!c) { pthread_mutex_unlock(&mutex);return 0; }
    int rc=CP_STARTUP_CONTROLS_SOURCE_BLOCKED;
    if(destination!=expected || (c->releasing&kind) || (kind==2 && c->s.busy && !internal) ||
       (kind==1 && !c->reply_started && !internal))fault(c);
    else {
        struct full_imaging_io io=c->io;c->releasing|=kind;pthread_mutex_unlock(&mutex);
        if(kind==1) {
            unsigned char observed[12];unsigned int bytes=io.size(pointer),source=io.source(pointer);
            if(bytes==12)memcpy(observed,pointer,12);
            pthread_mutex_lock(&mutex);
            c->s.reply_free_destination=destination;c->s.reply_free_source=source;c->s.reply_free_bytes=bytes;
            if(bytes==12)memcpy(c->s.freed_reply_wire,observed,12);
            if(bytes!=12 || source!=NATIVE_CP_STARTUP_CONTROLS_SID || (bytes==12 && memcmp(observed,c->s.reply_wire,12)))fault(c);
            pthread_mutex_unlock(&mutex);
        }
        rc=release(destination,pointer);pthread_mutex_lock(&mutex);c->releasing&=~kind;
        if(rc)fault(c);
        else if(kind==1) {
            c->s.live_reply=NULL;c->s.reply_freed=1;
            if(!internal) { c->s.waiter_tid=freeing;if(freeing!=c->s.sender_tid)fault(c); }
        } else if(kind==2) { c->s.retained_request=NULL;c->s.request_freed=1; }
        else c->s.retained_cleanup=NULL;
    }
    if((kind==1 || kind==4) && !c->s.reply_free_rc)c->s.reply_free_rc=rc;
    if(kind==2 && !c->s.request_free_rc)c->s.request_free_rc=rc;
    refresh(c);pthread_mutex_unlock(&mutex);
    record(c,logger,kind==1?"REPLY_FREE":kind==2?"REQUEST_FREE":"CLEANUP_FREE");*result=rc;return 1;
}
int native_cp_startup_controls_diagnostic_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
    void (*logger)(const char *,const char *),int *result) { return release_owned(destination,pointer,release,logger,result,0); }
static void finish(struct control *c,const struct native_cp_startup_controls_diagnostic_guard *guard) {
    pthread_mutex_lock(&mutex);unsigned int held=c->s.guard_held;pthread_mutex_unlock(&mutex);
    if(held)guard->release();
    pthread_mutex_lock(&mutex);c->s.guard_held=c->s.busy=0;refresh(c);pthread_mutex_unlock(&mutex);
}
static int available(void) {
    if(!initialized)return 0;
    for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++) {
        struct control *c=&controls[i];
        if(c->s.faults || c->s.busy || c->s.guard_held || c->releasing || c->s.retained_request || c->s.live_reply ||
           c->s.retained_cleanup || (c->s.requests && !c->s.clean_completion))return 0;
    }
    return 1;
}
int native_cp_startup_controls_diagnostic_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
    const struct native_cp_startup_controls_diagnostic_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP_STARTUP_CONTROLS_SID || !request || !io || !result)return 0;
    if(inherited() || inspecting) { *result=CP_STARTUP_CONTROLS_SOURCE_BLOCKED;return 1; }
    if(!io->size)return 0;
    inspecting=1;unsigned int bytes=io->size(request);inspecting=0;const unsigned char *wire=request;
    if(bytes<4 || wire[0]!=5)return 0;
    struct control *c=NULL;
    for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++)
        if(controls[i].s.opcode==u16(wire+2) && controls[i].bytes) { c=&controls[i];break; }
    if(!c)return 0;
    *result=CP_STARTUP_CONTROLS_SOURCE_BLOCKED;
    if(bytes!=c->bytes || bytes<8 || bytes>CP_STARTUP_CONTROLS_REQUEST_MAX || !io->source || !io->allocate ||
       !io->set_source || !io->send || !io->release || !io->record || !guard || !guard->reserve || !guard->release || !guard->predecessor_ready)return 1;
    inspecting=1;unsigned int source=io->source(request);inspecting=0;
    if(source!=FULL_IMAGING_AP)return 1;
    unsigned char copy[CP_STARTUP_CONTROLS_REQUEST_MAX];memcpy(copy,request,bytes);
    uint32_t hash=UINT32_C(2166136261);
    for(unsigned int i=0;i<bytes;i++)hash=(hash^copy[i])*UINT32_C(16777619);
    pthread_mutex_lock(&mutex);
    if(!available() || c->s.requests) { pthread_mutex_unlock(&mutex);return 1; }
    c->s.busy=1;pthread_mutex_unlock(&mutex);
    int rc=guard->reserve();
    if(rc) { finish(c,guard);*result=rc;return 1; }
    pthread_mutex_lock(&mutex);c->s.guard_held=1;pthread_mutex_unlock(&mutex);
    if(guard->predecessor_ready()!=1) { finish(c,guard);return 1; }
    unsigned char reply_wire[12]={1,0,0,0,0,0,0,0,0,0xf0,0,0};memcpy(reply_wire+2,copy+2,6);
    void *reply=NULL;rc=io->allocate(source,&reply,12,1);
    uintptr_t a=(uintptr_t)reply,b=(uintptr_t)request;
    int alias=reply && (a<=b?b-a<12:a-b<bytes);
    int valid=!rc && reply && !alias && io->size(reply)==12;
    if(valid) {
        memcpy(reply,reply_wire,12);io->set_source(reply,NATIVE_CP_STARTUP_CONTROLS_SID);
        valid=io->source(reply)==NATIVE_CP_STARTUP_CONTROLS_SID && io->size(reply)==12 && !memcmp(reply,reply_wire,12);
    }
    valid=valid && guard->predecessor_ready()==1 && io->size(request)==bytes && io->source(request)==source && !memcmp(request,copy,bytes);
    pthread_mutex_lock(&mutex);
    c->io=*io;if(!c->s.allocate_rc)c->s.allocate_rc=rc;
    c->s.source=source;c->s.request_destination=destination;c->s.destination=source;c->s.request_bytes=bytes;c->s.cookie=u32(copy+4);c->s.request_fnv1a32=hash;
    memcpy(c->s.request_wire,copy,bytes);memcpy(c->s.reply_wire,reply_wire,12);
    for(unsigned int i=0;i<CP_STARTUP_CONTROLS_COMMANDS;i++)valid=valid && !controls[i].s.faults;
    if(!valid) {
        if(alias || reply || !rc)fault(c);
        if(reply && !alias)c->s.retained_cleanup=reply;
        pthread_mutex_unlock(&mutex);
        if(reply && !alias) { int freed;release_owned(source,reply,io->release,io->record,&freed,1); }
        finish(c,guard);*result=rc?rc:CP_STARTUP_CONTROLS_SOURCE_BLOCKED;record(c,io->record,"REFUSED");return 1;
    }
    c->s.requests=1;c->s.sender_tid=tid();c->s.retained_request=request;c->s.live_reply=reply;
    pthread_mutex_unlock(&mutex);record(c,io->record,"REQUEST");
    pthread_mutex_lock(&mutex);rc=c->s.faults?CP_STARTUP_CONTROLS_SOURCE_BLOCKED:0;if(!rc)c->reply_started=1;pthread_mutex_unlock(&mutex);
    if(!rc)rc=io->send(source,reply);
    pthread_mutex_lock(&mutex);c->s.send_rc=rc;if(rc)fault(c);else c->s.queued=1;
    int cleanup=rc && c->s.live_reply && !(c->releasing&1);pthread_mutex_unlock(&mutex);
    if(rc) {
        if(cleanup) { int freed;release_owned(source,reply,io->release,io->record,&freed,1); }
    } else {
        record(c,io->record,"REPLY_QUEUED");int freed;release_owned(destination,request,io->release,io->record,&freed,1);
    }
    finish(c,guard);record(c,io->record,rc?"FAULT":"COMPLETE");*result=0;return 1;
}
#ifdef NATIVE_CP_STARTUP_CONTROLS_DIAGNOSTIC_TEST
void native_cp_startup_controls_diagnostic_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_cp_startup_controls_diagnostic_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
