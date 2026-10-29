/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-movie-format-diagnostic.h"
#include <pthread.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>

/* Source8deadbd0 COMPLETED: public CP sha256
 * f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428,
 * VA=raw+108000; AP appFw ELF sha256
 * 2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b.
 * AP3545ab8 set_movie_format,3546010 asks12B,3546014 tests+8=f000 only.
 * Actual AP258/tid378 follows409d free rc0;4000 wait saved3535b04/3546014/
 * 34cba34/3389214/338ea00. Request0500004027000080050100000000000000000100.
 * CP type5 dispatcher35cf70 first20B record10fab8c:
 * {4000,35421d,0,0,35d0e5}; handler35421c consumes byte8/9/10, LE32+12,
 * byte16/17/18; byte11/19 unconsumed. Conditional+12 only writes165a750 if
 * nonzero. Actual1/0 rate maps0, matrix f812dc+5*7+0 byte1 valid; d939f0
 * logging/matrix checks prove NO native application by this diagnostic.
 * 35448c saves opcode/cookie/REAL source/callback354551 at pending165b498;
 * 8dad54 copies16 active165b488;8db16a invokes354550 (P942 waits unclosed).
 * Only source completion writesf000/returns12 via8daa14/4b3c48, independently
 * allocated type1/4000/cookie, source90030001 to original80020002. Byte1 UNKNOWN.
 * AP shared receiver checks source/type/opcode/length, copies12 then frees on
 * original sender; +8 is the only business result. No extra data is invented. */
static const unsigned char body[12]={5,1,0,0,0,0,0,0,0,0,1,0};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct native_cp_movie_format_diagnostic_snapshot state={.diagnostic_only=1,.no_publication=1,.virtual_padding=1,.opcode=0x4000,.supported=1};
static struct full_imaging_io owned_io;
static unsigned int releasing,reply_started;
static _Thread_local unsigned int inspecting;
static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int pid=atomic_load(&owner_pid);return pid && pid!=getpid(); }
static unsigned int u16(const unsigned char *p) { return p[0] | (unsigned int)p[1]<<8; }
static uint32_t u32(const unsigned char *p) { return u16(p) | (uint32_t)u16(p+2)<<16; }
static void fault(void) { state.faults=1;state.clean_completion=state.ap_consumed=0; }
static void refresh(void) {
    state.clean_completion=state.queued && state.request_freed && state.reply_freed && !state.busy &&
        !state.guard_held && !state.faults && !releasing && !state.retained_request && !state.live_reply &&
        !state.retained_cleanup && state.sender_tid==state.waiter_tid;
    state.ap_consumed=state.clean_completion;
}
void native_cp_movie_format_diagnostic_snapshot(struct native_cp_movie_format_diagnostic_snapshot *out) {
    if(!out)return;
    int pid=atomic_load(&owner_pid);
    if(pid && pid!=getpid()) { *out=(struct native_cp_movie_format_diagnostic_snapshot){.owner_pid=pid,.faults=1,.diagnostic_only=1,.no_publication=1,.virtual_padding=1};return; }
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=pid;pthread_mutex_unlock(&mutex);
}
int native_cp_movie_format_diagnostic_owner_init(void) {
    int expected=0,pid=getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(atomic_load(&owner_pid)!=pid)return CP_MOVIE_FORMAT_SOURCE_BLOCKED;
    pthread_mutex_lock(&mutex);
    if(state.initialized || state.attempts || state.busy || state.faults) { pthread_mutex_unlock(&mutex);return CP_MOVIE_FORMAT_SOURCE_BLOCKED; }
    state.initialized=1;pthread_mutex_unlock(&mutex);return 0;
}
static void record(void (*logger)(const char *,const char *),const char *event) {
    if(!logger)return;
    struct native_cp_movie_format_diagnostic_snapshot s;native_cp_movie_format_diagnostic_snapshot(&s);
    char tag[80],line[2500],request[41],reply[25],freed[25];
    for(unsigned int i=0;i<20;i++)snprintf(request+2*i,3,"%02x",s.request_wire[i]);
    for(unsigned int i=0;i<12;i++) { snprintf(reply+2*i,3,"%02x",s.reply_wire[i]);snprintf(freed+2*i,3,"%02x",s.freed_reply_wire[i]); }
    snprintf(tag,sizeof tag,"NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_%s ",event);
    snprintf(line,sizeof line,"pid=%d opcode=0x4000 sender_tid=%ld waiter_tid=%ld attempts=%u requests=%u busy=%u guard=%u faults=%u source=%#x request_destination=%#x destination=%#x bytes=%u request=%s cookie=%#x wire_fnv1a32=%#x reply=%s freed_reply=%s reply_free_destination=%#x reply_free_source=%#x reply_free_bytes=%u allocate_rc=%d send_rc=%d request_free_rc=%d reply_free_rc=%d queued=%u request_freed=%u reply_freed=%u clean_completion=%u ap_consumed=%u known_field_mask=%#x virtual_field_mask=%#x virtual_fields_readback=%u virtual_fields_consumed=%#x virtual_fields=%u,%u,%u,%u,%u,%u,%u virtual_readback=%u,%u,%u,%u,%u,%u,%u retained_request=%p live_reply=%p retained_cleanup=%p diagnostic_only=1 no_publication=1 virtual_padding=1 source_byte1_known=0 source_business_applied=0 current_known=0 source_dependency_closed=0 business_applied=0 source_dependencies_closed=0 configured=0 published=0 pending_complete=0 generation=0 native_verified=0 native_cp=0 EE=0 frame=0 capture=0",
        s.owner_pid,s.sender_tid,s.waiter_tid,s.attempts,s.requests,s.busy,s.guard_held,s.faults,s.source,s.request_destination,s.destination,s.request_bytes,request,s.cookie,s.request_fnv1a32,reply,freed,s.reply_free_destination,s.reply_free_source,s.reply_free_bytes,s.allocate_rc,s.send_rc,s.request_free_rc,s.reply_free_rc,s.queued,s.request_freed,s.reply_freed,s.clean_completion,s.ap_consumed,s.known_field_mask,s.virtual_field_mask,s.virtual_fields_readback,s.virtual_fields_consumed,
        s.virtual_fields[0],s.virtual_fields[1],s.virtual_fields[2],s.virtual_fields[3],s.virtual_fields[4],s.virtual_fields[5],s.virtual_fields[6],s.virtual_readback[0],s.virtual_readback[1],s.virtual_readback[2],s.virtual_readback[3],s.virtual_readback[4],s.virtual_readback[5],s.virtual_readback[6],s.retained_request,s.live_reply,s.retained_cleanup);
    logger(tag,line);
}
static int release_owned(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                         void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(inherited()) {
        if(pointer!=state.live_reply && pointer!=state.retained_request && pointer!=state.retained_cleanup)return 0;
        *result=CP_MOVIE_FORMAT_SOURCE_BLOCKED;return 1;
    }
    unsigned int kind,expected;long freeing=tid();pthread_mutex_lock(&mutex);
    if(pointer==state.live_reply) { kind=1;expected=state.destination; }
    else if(pointer==state.retained_request) { kind=2;expected=NATIVE_CP_MOVIE_FORMAT_SID; }
    else if(pointer==state.retained_cleanup) { kind=4;expected=state.destination; }
    else { pthread_mutex_unlock(&mutex);return 0; }
    int rc=CP_MOVIE_FORMAT_SOURCE_BLOCKED;
    if(destination!=expected || (releasing&kind) || (kind==2 && state.busy && !internal) ||
       (kind==1 && !reply_started && !internal))fault();
    else {
        struct full_imaging_io io=owned_io;releasing|=kind;pthread_mutex_unlock(&mutex);
        if(kind==1) {
            unsigned char observed[12];unsigned int bytes=io.size(pointer),source=io.source(pointer);
            if(bytes==12)memcpy(observed,pointer,12);
            pthread_mutex_lock(&mutex);
            state.reply_free_destination=destination;state.reply_free_source=source;state.reply_free_bytes=bytes;
            if(bytes==12)memcpy(state.freed_reply_wire,observed,12);
            if(bytes!=12 || source!=NATIVE_CP_MOVIE_FORMAT_SID || (bytes==12 && memcmp(observed,state.reply_wire,12)))fault();
            pthread_mutex_unlock(&mutex);
        }
        rc=release(destination,pointer);pthread_mutex_lock(&mutex);releasing&=~kind;
        if(rc)fault();
        else if(kind==1) {
            state.live_reply=NULL;state.reply_freed=1;
            if(!internal) { state.waiter_tid=freeing;if(freeing!=state.sender_tid)fault(); }
        } else if(kind==2) { state.retained_request=NULL;state.request_freed=1; }
        else state.retained_cleanup=NULL;
    }
    if((kind==1 || kind==4) && !state.reply_free_rc)state.reply_free_rc=rc;
    if(kind==2 && !state.request_free_rc)state.request_free_rc=rc;
    refresh();pthread_mutex_unlock(&mutex);record(logger,kind==1?"REPLY_FREE":kind==2?"REQUEST_FREE":"CLEANUP_FREE");*result=rc;return 1;
}
int native_cp_movie_format_diagnostic_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
    void (*logger)(const char *,const char *),int *result) { return release_owned(destination,pointer,release,logger,result,0); }
static void finish(const struct native_cp_movie_format_diagnostic_guard *guard) {
    pthread_mutex_lock(&mutex);unsigned int held=state.guard_held;pthread_mutex_unlock(&mutex);
    if(held)guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=state.busy=0;refresh();pthread_mutex_unlock(&mutex);
}
int native_cp_movie_format_diagnostic_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
    const struct native_cp_movie_format_diagnostic_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP_MOVIE_FORMAT_SID || !request || !io || !result)return 0;
    if(inherited() || inspecting) { *result=CP_MOVIE_FORMAT_SOURCE_BLOCKED;return 1; }
    if(!io->size)return 0;
    inspecting=1;unsigned int bytes=io->size(request);inspecting=0;const unsigned char *wire=request;
    if(bytes<4 || u16(wire+2)!=0x4000)return 0;
    *result=CP_MOVIE_FORMAT_SOURCE_BLOCKED;
    if(bytes!=20 || wire[0]!=5 || wire[1]!=0 || memcmp(wire+8,body,12) || !io->source || !io->allocate ||
       !io->set_source || !io->send || !io->release || !io->record || !guard || !guard->reserve || !guard->release || !guard->predecessor_ready)return 1;
    inspecting=1;unsigned int source=io->source(request);inspecting=0;
    if(source!=FULL_IMAGING_AP)return 1;
    unsigned char copy[20];memcpy(copy,request,20);
    if(copy[0]!=5 || copy[1]!=0 || u16(copy+2)!=0x4000 || memcmp(copy+8,body,12))return 1;
    uint32_t hash=UINT32_C(2166136261);
    for(unsigned int i=0;i<20;i++)hash=(hash^copy[i])*UINT32_C(16777619);
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.attempts || state.faults || state.busy || state.guard_held || releasing ||
       state.retained_request || state.live_reply || state.retained_cleanup) { pthread_mutex_unlock(&mutex);return 1; }
    state.busy=1;pthread_mutex_unlock(&mutex);
    int rc=guard->reserve();
    if(rc) { finish(guard);*result=rc;return 1; }
    pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    if(guard->predecessor_ready()!=1) { finish(guard);return 1; }
    pthread_mutex_lock(&mutex);state.attempts=1;owned_io=*io;
    state.source=source;state.request_destination=destination;state.destination=source;state.request_bytes=20;
    state.cookie=u32(copy+4);state.request_fnv1a32=hash;memcpy(state.request_wire,copy,20);pthread_mutex_unlock(&mutex);
    unsigned char reply_wire[12]={1,0,0,0x40,0,0,0,0,0,0xf0,0,0};memcpy(reply_wire+4,copy+4,4);
    void *reply=NULL;rc=io->allocate(source,&reply,12,1);
    uintptr_t a=(uintptr_t)reply,b=(uintptr_t)request;
    int alias=reply && (a<=b?b-a<12:a-b<20);
    int valid=!rc && reply && !alias && io->size(reply)==12;
    if(valid) {
        memcpy(reply,reply_wire,12);io->set_source(reply,NATIVE_CP_MOVIE_FORMAT_SID);
        valid=io->source(reply)==NATIVE_CP_MOVIE_FORMAT_SID && io->size(reply)==12 && !memcmp(reply,reply_wire,12);
    }
    valid=valid && guard->predecessor_ready()==1 && io->size(request)==20 && io->source(request)==source && !memcmp(request,copy,20);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;memcpy(state.reply_wire,reply_wire,12);valid=valid && !state.faults;
    if(!valid) {
        fault();if(reply && !alias)state.retained_cleanup=reply;pthread_mutex_unlock(&mutex);
        if(reply && !alias) { int freed;release_owned(source,reply,io->release,io->record,&freed,1); }
        finish(guard);*result=rc?rc:CP_MOVIE_FORMAT_SOURCE_BLOCKED;record(io->record,"REFUSED");return 1;
    }
    state.requests=1;state.sender_tid=tid();state.retained_request=request;state.live_reply=reply;
    state.virtual_fields[0]=copy[8];state.virtual_fields[1]=copy[9];state.virtual_fields[2]=copy[10];
    state.virtual_fields[3]=u32(copy+12);state.virtual_fields[4]=copy[16];state.virtual_fields[5]=copy[17];state.virtual_fields[6]=copy[18];
    memcpy(state.virtual_readback,state.virtual_fields,sizeof state.virtual_fields);
    state.known_field_mask=state.virtual_field_mask=state.virtual_fields_consumed=CP_MOVIE_FORMAT_KNOWN_MASK;
    state.virtual_fields_readback=!memcmp(state.virtual_fields,state.virtual_readback,sizeof state.virtual_fields);
    reply_started=1;pthread_mutex_unlock(&mutex);
    rc=io->send(source,reply);
    pthread_mutex_lock(&mutex);state.send_rc=rc;if(rc)fault();else state.queued=1;
    int cleanup=rc && state.live_reply && !(releasing&1);pthread_mutex_unlock(&mutex);
    if(cleanup) { int freed;release_owned(source,reply,io->release,io->record,&freed,1); }
    if(!rc) { int freed;release_owned(destination,request,io->release,io->record,&freed,1); }
    finish(guard);record(io->record,rc?"FAULT":"COMPLETE");*result=0;return 1;
}
#ifdef NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_TEST
void native_cp_movie_format_diagnostic_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_cp_movie_format_diagnostic_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
