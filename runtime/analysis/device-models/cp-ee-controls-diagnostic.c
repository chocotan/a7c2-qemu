/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-ee-controls-diagnostic.h"
#include <pthread.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>

struct control {
    struct native_cp_ee_controls_diagnostic_lease s;
    struct full_imaging_io io;
    unsigned int bytes, type, fields, releasing, reply_started;
};
/* Source contract f3ca0b0e FINAL, public CP raw base0x108000 (Thumb):
 * CP sha256 f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428;
 * AP appFw ELF sha256 2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b.
 * Actual run-ktnudlyz AP259 tid382 freed4014/4057 rc0;409d is PARALLEL
 * tid379,80020002->90030001,05009d402700008000000000,wait3545970.
 * 409d AP35457ec asks12B/type5; CP table10fb6cc->35836c/check362238 copies
 * FOUR bytes+8..11 zeroextended to165a8f0/f4/f8/fc,35448c PENDING358421;
 * publish8db16a->358420 writesf000/returns12. Common type1/opcode/cookie.
 * 4072 AP354565c asks12B/type5,x4/x5=0,local return0;CP table10fb370->
 * 357094 copies byte8/9 to165aa68/9, NO reply or pending callback.
 * 3012 AP3546244->35460e4 builds24B/type0,16 zero tail bytes;CP4b6064->
 * event8100,b225ee produces12B/type1/3012/cookie/f000, fixed dst80020002,
 * src90030001. AP tests+8=f000 only. Reply byte1 is UNKNOWN, virtual0 here.
 * 3003 is UNHANDLED:16B reply+12..15 are SOURCE DATA P46/47/48 and
 * [a499f4()+8],P=*[b2ddb4()+34]; AP copies/logs these UNKNOWN values.
 * No source business/crank/publication/generation or capture claim follows. */
static struct control controls[CP_EE_CONTROLS_COMMANDS] = {
    {.s={.opcode=0x409d}, .bytes=12, .type=5, .fields=4},
    {.s={.opcode=0x4072,.oneway=1}, .bytes=12, .type=5, .fields=2},
    {.s={.opcode=0x3012}, .bytes=24, .type=0}
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
    int done=c->s.oneway?c->s.oneway_consumed:
        c->s.queued && c->s.reply_freed && c->s.sender_tid==c->s.waiter_tid;
    c->s.clean_completion=c->s.requests && done && c->s.request_freed && !c->s.busy &&
        !c->s.guard_held && !c->s.faults && !c->releasing && !c->s.retained_request &&
        !c->s.live_reply && !c->s.retained_cleanup;
    c->s.ap_consumed=!c->s.oneway && c->s.clean_completion;
}
void native_cp_ee_controls_diagnostic_snapshot(struct native_cp_ee_controls_diagnostic_snapshot *out) {
    if(!out)return;
    int pid=atomic_load(&owner_pid);
    *out=(struct native_cp_ee_controls_diagnostic_snapshot){.owner_pid=pid,.diagnostic_only=1,.virtual_padding=1};
    if(pid && pid!=getpid()) { out->faults=1;return; }
    pthread_mutex_lock(&mutex);out->initialized=initialized;
    for(unsigned int i=0;i<CP_EE_CONTROLS_COMMANDS;i++) {
        const struct control *c=&controls[i];out->leases[i]=c->s;out->leases[i].supported=1;
        out->attempts+=c->s.attempts;out->requests+=c->s.requests;out->completed+=c->s.clean_completion;
        out->busy|=c->s.busy;out->guard_held|=c->s.guard_held;out->faults|=c->s.faults;
    }
    pthread_mutex_unlock(&mutex);
}
int native_cp_ee_controls_diagnostic_owner_init(void) {
    int expected=0,pid=getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(atomic_load(&owner_pid)!=pid)return CP_EE_CONTROLS_SOURCE_BLOCKED;
    pthread_mutex_lock(&mutex);
    if(initialized) { pthread_mutex_unlock(&mutex);return CP_EE_CONTROLS_SOURCE_BLOCKED; }
    initialized=1;pthread_mutex_unlock(&mutex);return 0;
}
static void record(struct control *c,void (*logger)(const char *,const char *),const char *event) {
    if(!logger)return;
    struct native_cp_ee_controls_diagnostic_snapshot snapshot;native_cp_ee_controls_diagnostic_snapshot(&snapshot);
    struct native_cp_ee_controls_diagnostic_lease s=snapshot.leases[c-controls];
    char tag[80],line[2400],request[CP_EE_CONTROLS_REQUEST_MAX*2+1]={0},reply[25]="none",freed[25]="none";
    for(unsigned int i=0;i<s.request_bytes;i++)snprintf(request+2*i,3,"%02x",s.request_wire[i]);
    if(!s.oneway)for(unsigned int i=0;i<12;i++)snprintf(reply+2*i,3,"%02x",s.reply_wire[i]);
    if(s.reply_free_bytes==12)for(unsigned int i=0;i<12;i++)snprintf(freed+2*i,3,"%02x",s.freed_reply_wire[i]);
    snprintf(tag,sizeof tag,"NATIVE_CP_EE_DIAGNOSTIC_%s ",event);
    snprintf(line,sizeof line,"pid=%d opcode=%#x sender_tid=%ld waiter_tid=%ld attempts=%u requests=%u busy=%u guard=%u faults=%u source=%#x request_destination=%#x destination=%#x bytes=%u request=%s cookie=%#x wire_fnv1a32=%#x source_byte1_known=%u reply=%s freed_reply=%s reply_free_destination=%#x reply_free_source=%#x reply_free_bytes=%u allocate_rc=%d send_rc=%d request_free_rc=%d reply_free_rc=%d queued=%u request_freed=%u reply_freed=%u clean_completion=%u ap_consumed=%u oneway=%u oneway_consumed=%u virtual_field_mask=%#x virtual_fields_readback=%u virtual_fields_consumed=%#x virtual_fields=%u,%u,%u,%u virtual_readback=%u,%u,%u,%u retained_request=%p live_reply=%p retained_cleanup=%p diagnostic_only=1 virtual_padding=1 business_applied=0 source_dependencies_closed=0 configured=0 published=0 generation=0 native_cp=0 EE=0 frame=0 capture=0",
        snapshot.owner_pid,s.opcode,s.sender_tid,s.waiter_tid,s.attempts,s.requests,s.busy,s.guard_held,s.faults,s.source,s.request_destination,s.destination,
        s.request_bytes,request,s.cookie,s.request_fnv1a32,s.source_byte1_known,reply,freed,s.reply_free_destination,s.reply_free_source,s.reply_free_bytes,
        s.allocate_rc,s.send_rc,s.request_free_rc,s.reply_free_rc,s.queued,s.request_freed,s.reply_freed,s.clean_completion,s.ap_consumed,s.oneway,s.oneway_consumed,
        s.virtual_field_mask,s.virtual_fields_readback,s.virtual_fields_consumed,s.virtual_fields[0],s.virtual_fields[1],s.virtual_fields[2],s.virtual_fields[3],
        s.virtual_readback[0],s.virtual_readback[1],s.virtual_readback[2],s.virtual_readback[3],s.retained_request,s.live_reply,s.retained_cleanup);
    logger(tag,line);
}
static int release_owned(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                         void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(inherited()) {
        for(unsigned int i=0;i<CP_EE_CONTROLS_COMMANDS;i++) {
            struct control *c=&controls[i];
            if(pointer==c->s.live_reply || pointer==c->s.retained_request || pointer==c->s.retained_cleanup) {
                *result=CP_EE_CONTROLS_SOURCE_BLOCKED;return 1;
            }
        }
        return 0;
    }
    struct control *c=NULL;unsigned int kind=0,expected=0;long freeing=tid();
    pthread_mutex_lock(&mutex);
    for(unsigned int i=0;i<CP_EE_CONTROLS_COMMANDS;i++) {
        struct control *candidate=&controls[i];
        if(pointer==candidate->s.live_reply) { c=candidate;kind=1;expected=c->s.destination;break; }
        if(pointer==candidate->s.retained_request) { c=candidate;kind=2;expected=NATIVE_CP_EE_CONTROLS_SID;break; }
        if(pointer==candidate->s.retained_cleanup) { c=candidate;kind=4;expected=FULL_IMAGING_AP;break; }
    }
    if(!c) { pthread_mutex_unlock(&mutex);return 0; }
    int rc=CP_EE_CONTROLS_SOURCE_BLOCKED;
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
            if(bytes!=12 || source!=NATIVE_CP_EE_CONTROLS_SID || (bytes==12 && memcmp(observed,c->s.reply_wire,12)))fault(c);
            pthread_mutex_unlock(&mutex);
        }
        rc=release(destination,pointer);pthread_mutex_lock(&mutex);c->releasing&=~kind;
        if(rc)fault(c);
        else if(kind==1) {
            c->s.live_reply=NULL;c->s.reply_freed=1;
            if(!internal) { c->s.waiter_tid=freeing;if(freeing!=c->s.sender_tid)fault(c); }
        } else if(kind==2) {
            c->s.retained_request=NULL;c->s.request_freed=1;
            if(c->s.oneway) { c->s.oneway_consumed=1;c->s.virtual_fields_consumed=c->s.virtual_field_mask; }
        } else c->s.retained_cleanup=NULL;
    }
    if((kind==1 || kind==4) && !c->s.reply_free_rc)c->s.reply_free_rc=rc;
    if(kind==2 && !c->s.request_free_rc)c->s.request_free_rc=rc;
    refresh(c);pthread_mutex_unlock(&mutex);
    record(c,logger,kind==1?"REPLY_FREE":kind==2?"REQUEST_FREE":"CLEANUP_FREE");*result=rc;return 1;
}
int native_cp_ee_controls_diagnostic_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
    void (*logger)(const char *,const char *),int *result) { return release_owned(destination,pointer,release,logger,result,0); }
static void finish(struct control *c,const struct native_cp_ee_controls_diagnostic_guard *guard) {
    pthread_mutex_lock(&mutex);unsigned int held=c->s.guard_held;pthread_mutex_unlock(&mutex);
    if(held)guard->release();
    pthread_mutex_lock(&mutex);c->s.guard_held=c->s.busy=0;refresh(c);pthread_mutex_unlock(&mutex);
}
static int available(const struct control *next) {
    if(!initialized || next->s.attempts)return 0;
    for(unsigned int i=0;i<CP_EE_CONTROLS_COMMANDS;i++) {
        const struct control *c=&controls[i];
        if(c->s.faults || c->s.busy || c->s.guard_held || c->releasing || c->s.retained_request || c->s.live_reply ||
           c->s.retained_cleanup || (c->s.requests && !c->s.clean_completion) || (c<next && !c->s.clean_completion))return 0;
    }
    return 1;
}
int native_cp_ee_controls_diagnostic_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
    const struct native_cp_ee_controls_diagnostic_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP_EE_CONTROLS_SID || !request || !io || !result)return 0;
    if(inherited() || inspecting) { *result=CP_EE_CONTROLS_SOURCE_BLOCKED;return 1; }
    if(!io->size)return 0;
    inspecting=1;unsigned int bytes=io->size(request);inspecting=0;const unsigned char *wire=request;
    if(bytes<4)return 0;
    struct control *c=NULL;
    for(unsigned int i=0;i<CP_EE_CONTROLS_COMMANDS;i++)
        if(controls[i].s.opcode==u16(wire+2) && wire[0]==controls[i].type) { c=&controls[i];break; }
    if(!c)return 0;
    *result=CP_EE_CONTROLS_SOURCE_BLOCKED;
    if(bytes!=c->bytes || !io->source || !io->release || !io->record ||
       (!c->s.oneway && (!io->allocate || !io->set_source || !io->send)) ||
       !guard || !guard->reserve || !guard->release || !guard->predecessor_ready)return 1;
    inspecting=1;unsigned int source=io->source(request);inspecting=0;
    if(source!=FULL_IMAGING_AP)return 1;
    unsigned char copy[CP_EE_CONTROLS_REQUEST_MAX];memcpy(copy,request,bytes);
    uint32_t hash=UINT32_C(2166136261);
    for(unsigned int i=0;i<bytes;i++)hash=(hash^copy[i])*UINT32_C(16777619);
    pthread_mutex_lock(&mutex);
    if(!available(c)) { pthread_mutex_unlock(&mutex);return 1; }
    c->s.busy=1;pthread_mutex_unlock(&mutex);
    int rc=guard->reserve();
    if(rc) { finish(c,guard);*result=rc;return 1; }
    pthread_mutex_lock(&mutex);c->s.guard_held=1;pthread_mutex_unlock(&mutex);
    if(guard->predecessor_ready()!=1) { finish(c,guard);return 1; }
    pthread_mutex_lock(&mutex);c->s.attempts=1;c->io=*io;
    c->s.source=source;c->s.request_destination=destination;c->s.destination=c->s.oneway?0:source;
    c->s.request_bytes=bytes;c->s.cookie=u32(copy+4);c->s.request_fnv1a32=hash;
    memcpy(c->s.request_wire,copy,bytes);pthread_mutex_unlock(&mutex);
    unsigned char reply_wire[12]={1,0,0,0,0,0,0,0,0,0xf0,0,0};
    void *reply=NULL;int alias=0,valid=1;
    if(!c->s.oneway) {
        memcpy(reply_wire+2,copy+2,6);rc=io->allocate(source,&reply,12,1);
        uintptr_t a=(uintptr_t)reply,b=(uintptr_t)request;
        alias=reply && (a<=b?b-a<12:a-b<bytes);
        valid=!rc && reply && !alias && io->size(reply)==12;
        if(valid) {
            memcpy(reply,reply_wire,12);io->set_source(reply,NATIVE_CP_EE_CONTROLS_SID);
            valid=io->source(reply)==NATIVE_CP_EE_CONTROLS_SID && io->size(reply)==12 && !memcmp(reply,reply_wire,12);
        }
    }
    valid=valid && guard->predecessor_ready()==1 && io->size(request)==bytes && io->source(request)==source && !memcmp(request,copy,bytes);
    pthread_mutex_lock(&mutex);c->s.allocate_rc=rc;
    if(!c->s.oneway)memcpy(c->s.reply_wire,reply_wire,12);
    for(unsigned int i=0;i<CP_EE_CONTROLS_COMMANDS;i++)valid=valid && !controls[i].s.faults;
    if(!valid) {
        fault(c);if(reply && !alias)c->s.retained_cleanup=reply;pthread_mutex_unlock(&mutex);
        if(reply && !alias) { int freed;release_owned(source,reply,io->release,io->record,&freed,1); }
        finish(c,guard);*result=rc?rc:CP_EE_CONTROLS_SOURCE_BLOCKED;record(c,io->record,"REFUSED");return 1;
    }
    c->s.requests=1;c->s.sender_tid=tid();c->s.retained_request=request;c->s.live_reply=reply;
    for(unsigned int i=0;i<c->fields;i++) { c->s.virtual_fields[i]=copy[8+i];c->s.virtual_readback[i]=c->s.virtual_fields[i]; }
    if(c->fields) { c->s.virtual_field_mask=(1u<<c->fields)-1;c->s.virtual_fields_readback=1; }
    if(!c->s.oneway) { c->s.virtual_fields_consumed=c->s.virtual_field_mask;c->reply_started=1; }
    pthread_mutex_unlock(&mutex);
    if(!c->s.oneway) {
        rc=io->send(source,reply);
        pthread_mutex_lock(&mutex);c->s.send_rc=rc;if(rc)fault(c);else c->s.queued=1;
        int cleanup=rc && c->s.live_reply && !(c->releasing&1);pthread_mutex_unlock(&mutex);
        if(cleanup) { int freed;release_owned(source,reply,io->release,io->record,&freed,1); }
    }
    if(!rc) { int freed;release_owned(destination,request,io->release,io->record,&freed,1); }
    finish(c,guard);record(c,io->record,rc?"FAULT":"COMPLETE");*result=0;return 1;
}
#ifdef NATIVE_CP_EE_CONTROLS_DIAGNOSTIC_TEST
void native_cp_ee_controls_diagnostic_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_cp_ee_controls_diagnostic_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
