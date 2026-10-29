/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-capture-format.h"
#include <pthread.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

static _Thread_local unsigned int inspecting;
static uint16_t u16(const unsigned char *p) {
    return (uint16_t)(p[0] | (unsigned int)p[1] << 8);
}
static uint32_t u32(const unsigned char *p) {
    return (uint32_t)u16(p) | (uint32_t)u16(p + 2) << 16;
}
int cp_capture_format_inspect(struct cp_capture_format_audit *out, uint32_t source,
                              uint32_t destination, const void *wire, size_t bytes) {
    if(!out || !wire || bytes != CP_CAPTURE_FORMAT_BYTES)return -EINVAL;
    uintptr_t a = (uintptr_t)out, b = (uintptr_t)wire;
    if(a <= b ? b-a < sizeof *out : a-b < bytes)return -EINVAL;
    if(source != FULL_IMAGING_AP || destination != NATIVE_CP_CAPTURE_FORMAT_SID)return -EPROTO;
    struct cp_capture_format_audit audit = {0};
    memcpy(audit.request_wire, wire, bytes);
    const unsigned char *p = audit.request_wire;
    if(p[0] != 5 || u16(p+2) != 0x402d)return -EPROTO;
    audit.source = source; audit.destination = destination; audit.cookie = u32(p+4);
    audit.p_e0 = p[8]; audit.p_f8 = p[9];
    audit.p_104 = u16(p+10); audit.p_106 = u16(p+12); audit.p_108 = u16(p+14);
    audit.p_114 = u16(p+16); audit.p_116 = u16(p+18); audit.p_118 = u16(p+20);
    audit.request_fnv1a32 = UINT32_C(2166136261);
    for(size_t i=0; i<bytes; i++)audit.request_fnv1a32 =
        (audit.request_fnv1a32 ^ p[i]) * UINT32_C(16777619);
    audit.first_missing_address = CP_CAPTURE_FORMAT_FIRST_MISSING;
    *out = audit;
    return CP_CAPTURE_FORMAT_SOURCE_BLOCKED;
}
int native_cp_capture_format_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, int enabled, int *result) {
    if(enabled != 1 || destination != NATIVE_CP_CAPTURE_FORMAT_SID || !request || !io || !result)return 0;
    if(inspecting) { *result = CP_CAPTURE_FORMAT_SOURCE_BLOCKED; return 1; }
    if(!io->size)return 0;
    inspecting = 1;
    unsigned int bytes = io->size(request);
    inspecting = 0;
    const unsigned char *p = request;
    if(bytes < 4 || p[0] != 5 || u16(p+2) != 0x402d)return 0;
    *result = CP_CAPTURE_FORMAT_SOURCE_BLOCKED;
    if(bytes != CP_CAPTURE_FORMAT_BYTES || !io->source)return 1;
    inspecting = 1;
    unsigned int source = io->source(request);
    inspecting = 0;
    struct cp_capture_format_audit audit;
    int rc = cp_capture_format_inspect(&audit, source, destination, request, bytes);
    if(rc != CP_CAPTURE_FORMAT_SOURCE_BLOCKED)return 1;
    if(io->record) {
        char hex[CP_CAPTURE_FORMAT_BYTES*2+1], line[640];
        for(size_t i=0; i<CP_CAPTURE_FORMAT_BYTES; i++)snprintf(hex+2*i, 3, "%02x", audit.request_wire[i]);
        snprintf(line, sizeof line,
            "source=%#x destination=%#x bytes=24 request=%s cookie=%#x wire_fnv1a32=%#x "
            "p_e0=%u p_f8=%u p_104=%u p_106=%u p_108=%u p_114=%u p_116=%u p_118=%u "
            "first_missing=%#x needs=P+100/P+110 next=353fec,b0de20,b0e99e "
            "source_closed=0 semantic_consumed=0 generation=0 published=0 reply=0 "
            "request_owned=0 native_cp=0 EE=0 frame=0 capture=0",
            source, destination, hex, audit.cookie, audit.request_fnv1a32,
            (unsigned int)audit.p_e0, (unsigned int)audit.p_f8,
            (unsigned int)audit.p_104, (unsigned int)audit.p_106, (unsigned int)audit.p_108,
            (unsigned int)audit.p_114, (unsigned int)audit.p_116, (unsigned int)audit.p_118,
            audit.first_missing_address);
        /* The diagnostic callback may re-enter dispatch; no owner lock is held. */
        inspecting = 1; io->record("NATIVE_CP_CAPTURE_FORMAT_BLOCKED ", line); inspecting = 0;
    }
    return 1;
}

static pthread_mutex_t diagnostic_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int diagnostic_pid;
static struct native_cp_capture_format_diagnostic_snapshot diagnostic;
static struct full_imaging_io diagnostic_io;
static unsigned int diagnostic_releasing, diagnostic_reply_started;
static _Thread_local unsigned int diagnostic_inspecting;
static long diagnostic_tid(void) { return syscall(SYS_gettid); }
static int diagnostic_inherited(void) { int pid=atomic_load(&diagnostic_pid);return pid && pid!=getpid(); }
static void diagnostic_fault(void) { diagnostic.faults=1;diagnostic.clean_completion=diagnostic.ap_consumed=0; }
static void diagnostic_refresh(void) {
    diagnostic.clean_completion=diagnostic.queued && diagnostic.request_freed && diagnostic.reply_freed &&
        !diagnostic.busy && !diagnostic.guard_held && !diagnostic.faults && !diagnostic.retained_request &&
        !diagnostic.live_reply && !diagnostic.retained_cleanup && diagnostic.sender_tid==diagnostic.waiter_tid;
    diagnostic.ap_consumed=diagnostic.clean_completion;
}
void native_cp_capture_format_diagnostic_snapshot(struct native_cp_capture_format_diagnostic_snapshot *out) {
    if(!out)return;
    if(diagnostic_inherited()) { *out=(struct native_cp_capture_format_diagnostic_snapshot){.owner_pid=atomic_load(&diagnostic_pid),.faults=1,.diagnostic_only=1,.no_publication=1};return; }
    pthread_mutex_lock(&diagnostic_mutex);*out=diagnostic;out->owner_pid=atomic_load(&diagnostic_pid);pthread_mutex_unlock(&diagnostic_mutex);
}
static void diagnostic_record(void (*logger)(const char *,const char *),const char *event) {
    if(!logger)return;
    struct native_cp_capture_format_diagnostic_snapshot s;native_cp_capture_format_diagnostic_snapshot(&s);
    char tag[100],line[1700],request[49],reply[25],freed[25];
    for(unsigned int i=0;i<24;i++)snprintf(request+2*i,3,"%02x",s.audit.request_wire[i]);
    for(unsigned int i=0;i<12;i++) { snprintf(reply+2*i,3,"%02x",s.reply_wire[i]);snprintf(freed+2*i,3,"%02x",s.freed_reply_wire[i]); }
    snprintf(tag,sizeof tag,"NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_%s ",event);
    snprintf(line,sizeof line,"pid=%d sender_tid=%ld waiter_tid=%ld requests=%u busy=%u guard=%u faults=%u source=%#x destination=%#x bytes=24 request=%s cookie=%#x wire_fnv1a32=%#x p_e0=%u p_f8=%u p_104=%u p_106=%u p_108=%u p_114=%u p_116=%u p_118=%u first_missing=%#x reply=%s freed_reply=%s reply_free_destination=%#x reply_free_source=%#x reply_free_bytes=%u allocate_rc=%d send_rc=%d request_free_rc=%d reply_free_rc=%d queued=%u request_freed=%u reply_freed=%u clean_completion=%u ap_consumed=%u retained_request=%p live_reply=%p retained_cleanup=%p diagnostic_only=1 no_publication=1 source_business_applied=0 current_known=0 source_dependency_closed=0 source_byte1_known=0 virtual_padding=1 pending_complete=0 generation=0 native_verified=0 native_cp=0 CP_history_verified=0 EE=0 frame=0 capture=0",
        getpid(),s.sender_tid,s.waiter_tid,s.requests,s.busy,s.guard_held,s.faults,s.audit.source,s.audit.destination,
        request,s.cookie,s.audit.request_fnv1a32,s.audit.p_e0,s.audit.p_f8,(unsigned int)s.audit.p_104,
        (unsigned int)s.audit.p_106,(unsigned int)s.audit.p_108,(unsigned int)s.audit.p_114,(unsigned int)s.audit.p_116,
        (unsigned int)s.audit.p_118,s.audit.first_missing_address,reply,freed,s.reply_free_destination,
        s.reply_free_source,s.reply_free_bytes,s.allocate_rc,s.send_rc,s.request_free_rc,s.reply_free_rc,s.queued,
        s.request_freed,s.reply_freed,s.clean_completion,s.ap_consumed,s.retained_request,s.live_reply,s.retained_cleanup);
    logger(tag,line);
}
int native_cp_capture_format_diagnostic_owner_init(void) {
    int expected=0,pid=getpid();atomic_compare_exchange_strong(&diagnostic_pid,&expected,pid);
    if(atomic_load(&diagnostic_pid)!=pid)return CP_CAPTURE_FORMAT_SOURCE_BLOCKED;
    pthread_mutex_lock(&diagnostic_mutex);
    if(diagnostic.initialized || diagnostic.faults || diagnostic.busy) { pthread_mutex_unlock(&diagnostic_mutex);return CP_CAPTURE_FORMAT_SOURCE_BLOCKED; }
    diagnostic.initialized=diagnostic.diagnostic_only=diagnostic.no_publication=diagnostic.virtual_padding=1;
    pthread_mutex_unlock(&diagnostic_mutex);return 0;
}
static int diagnostic_release(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                              void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(diagnostic_inherited()) {
        if(pointer!=diagnostic.live_reply && pointer!=diagnostic.retained_request && pointer!=diagnostic.retained_cleanup)return 0;
        *result=CP_CAPTURE_FORMAT_SOURCE_BLOCKED;return 1;
    }
    unsigned int kind,expected;unsigned char observed[12];long freeing=diagnostic_tid();
    pthread_mutex_lock(&diagnostic_mutex);
    if(pointer==diagnostic.live_reply) { kind=1;expected=diagnostic.destination; }
    else if(pointer==diagnostic.retained_request) { kind=2;expected=NATIVE_CP_CAPTURE_FORMAT_SID; }
    else if(pointer==diagnostic.retained_cleanup) { kind=4;expected=diagnostic.destination; }
    else { pthread_mutex_unlock(&diagnostic_mutex);return 0; }
    int rc=CP_CAPTURE_FORMAT_SOURCE_BLOCKED;
    if(destination!=expected || (diagnostic_releasing&kind) || (kind==2 && diagnostic.busy && !internal) ||
       (kind==1 && !diagnostic_reply_started && !internal))diagnostic_fault();
    else {
        diagnostic_releasing|=kind;pthread_mutex_unlock(&diagnostic_mutex);
        if(kind==1) {
            unsigned int bytes=diagnostic_io.size(pointer),source=diagnostic_io.source(pointer);
            if(bytes==12)memcpy(observed,pointer,12);
            pthread_mutex_lock(&diagnostic_mutex);
            diagnostic.reply_free_destination=destination;diagnostic.reply_free_source=source;diagnostic.reply_free_bytes=bytes;
            if(bytes==12)memcpy(diagnostic.freed_reply_wire,observed,12);
            if(bytes!=12 || source!=NATIVE_CP_CAPTURE_FORMAT_SID || (bytes==12 && memcmp(observed,diagnostic.reply_wire,12)))diagnostic_fault();
            pthread_mutex_unlock(&diagnostic_mutex);
        }
        rc=release(destination,pointer);pthread_mutex_lock(&diagnostic_mutex);diagnostic_releasing&=~kind;
        if(rc)diagnostic_fault();
        else if(kind==1) {
            diagnostic.live_reply=NULL;diagnostic.reply_freed=1;
            if(!internal) { diagnostic.waiter_tid=freeing;if(freeing!=diagnostic.sender_tid)diagnostic_fault(); }
        } else if(kind==2) { diagnostic.retained_request=NULL;diagnostic.request_freed=1; }
        else diagnostic.retained_cleanup=NULL;
    }
    if(kind==1 || (kind==4 && rc))diagnostic.reply_free_rc=rc;
    if(kind==2)diagnostic.request_free_rc=rc;
    diagnostic_refresh();pthread_mutex_unlock(&diagnostic_mutex);
    diagnostic_record(logger,kind==1?"REPLY_FREE":kind==2?"REQUEST_FREE":"CLEANUP_FREE");*result=rc;return 1;
}
int native_cp_capture_format_diagnostic_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
    void (*logger)(const char *,const char *),int *result) { return diagnostic_release(destination,pointer,release,logger,result,0); }
static void diagnostic_finish(const struct native_cp_capture_format_diagnostic_guard *guard) {
    pthread_mutex_lock(&diagnostic_mutex);unsigned int held=diagnostic.guard_held;pthread_mutex_unlock(&diagnostic_mutex);
    if(held)guard->release();
    pthread_mutex_lock(&diagnostic_mutex);diagnostic.guard_held=diagnostic.busy=0;diagnostic_refresh();pthread_mutex_unlock(&diagnostic_mutex);
}
int native_cp_capture_format_diagnostic_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
    const struct native_cp_capture_format_diagnostic_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP_CAPTURE_FORMAT_SID || !request || !io || !result)return 0;
    if(diagnostic_inherited() || diagnostic_inspecting) { *result=CP_CAPTURE_FORMAT_SOURCE_BLOCKED;return 1; }
    if(!io->size)return 0;
    diagnostic_inspecting=1;unsigned int bytes=io->size(request);diagnostic_inspecting=0;const unsigned char *p=request;
    if(bytes<4 || p[0]!=5 || u16(p+2)!=0x402d)return 0;
    *result=CP_CAPTURE_FORMAT_SOURCE_BLOCKED;
    if(bytes!=24 || !io->source || !io->allocate || !io->set_source || !io->send || !io->release || !io->record ||
       !guard || !guard->reserve || !guard->release || !guard->predecessor_ready)return 1;
    diagnostic_inspecting=1;unsigned int caller=io->source(request);diagnostic_inspecting=0;
    struct cp_capture_format_audit audit;
    if(cp_capture_format_inspect(&audit,caller,destination,request,bytes)!=CP_CAPTURE_FORMAT_SOURCE_BLOCKED)return 1;
    pthread_mutex_lock(&diagnostic_mutex);
    if(!diagnostic.initialized || diagnostic.faults || diagnostic.requests || diagnostic.busy || diagnostic.guard_held ||
       diagnostic.retained_request || diagnostic.live_reply || diagnostic.retained_cleanup) { pthread_mutex_unlock(&diagnostic_mutex);return 1; }
    diagnostic.busy=1;pthread_mutex_unlock(&diagnostic_mutex);
    int rc=guard->reserve();
    if(rc) { diagnostic_finish(guard);*result=rc;return 1; }
    pthread_mutex_lock(&diagnostic_mutex);diagnostic.guard_held=1;pthread_mutex_unlock(&diagnostic_mutex);
    if(guard->predecessor_ready()!=1) { diagnostic_finish(guard);return 1; }
    unsigned char reply_wire[12]={1,0,0x2d,0x40,0,0,0,0,0,0xf0,0,0};memcpy(reply_wire+4,audit.request_wire+4,4);
    void *reply=NULL;rc=io->allocate(caller,&reply,12,1);
    uintptr_t a=(uintptr_t)reply,b=(uintptr_t)request;
    int alias=reply && (a<=b?b-a<12:a-b<24);
    int valid=!rc && reply && !alias && io->size(reply)==12;
    if(valid) {
        memcpy(reply,reply_wire,12);io->set_source(reply,NATIVE_CP_CAPTURE_FORMAT_SID);
        valid=io->source(reply)==NATIVE_CP_CAPTURE_FORMAT_SID && io->size(reply)==12 && !memcmp(reply,reply_wire,12);
    }
    valid=valid && guard->predecessor_ready()==1 && io->size(request)==24 &&
        io->source(request)==caller && !memcmp(request,audit.request_wire,24);
    pthread_mutex_lock(&diagnostic_mutex);diagnostic.allocate_rc=rc;valid=valid && !diagnostic.faults;
    if(!valid) {
        if(alias || reply || !rc)diagnostic_fault();
        if(reply && !alias) { diagnostic.retained_cleanup=reply;diagnostic.destination=caller; }
        pthread_mutex_unlock(&diagnostic_mutex);
        if(reply && !alias) { int freed;diagnostic_release(caller,reply,io->release,io->record,&freed,1); }
        diagnostic_finish(guard);*result=rc?rc:CP_CAPTURE_FORMAT_SOURCE_BLOCKED;diagnostic_record(io->record,"REFUSED");return 1;
    }
    diagnostic.requests=1;diagnostic.audit=audit;diagnostic.cookie=audit.cookie;diagnostic.destination=caller;
    diagnostic.sender_tid=diagnostic_tid();diagnostic.retained_request=request;diagnostic.live_reply=reply;
    memcpy(diagnostic.reply_wire,reply_wire,12);diagnostic_io=*io;pthread_mutex_unlock(&diagnostic_mutex);
    diagnostic_record(io->record,"REQUEST");
    pthread_mutex_lock(&diagnostic_mutex);rc=diagnostic.faults?CP_CAPTURE_FORMAT_SOURCE_BLOCKED:0;
    if(!rc)diagnostic_reply_started=1;
    pthread_mutex_unlock(&diagnostic_mutex);
    if(!rc)rc=io->send(caller,reply);
    pthread_mutex_lock(&diagnostic_mutex);diagnostic.send_rc=rc;
    if(rc)diagnostic_fault();else diagnostic.queued=1;
    int cleanup=rc && diagnostic.live_reply && !(diagnostic_releasing&1);pthread_mutex_unlock(&diagnostic_mutex);
    if(rc) {
        if(cleanup) { int freed;diagnostic_release(caller,reply,io->release,io->record,&freed,1); }
    } else {
        diagnostic_record(io->record,"REPLY_QUEUED");
        int freed;diagnostic_release(destination,request,io->release,io->record,&freed,1);
    }
    diagnostic_finish(guard);diagnostic_record(io->record,rc?"FAULT":"COMPLETE");*result=0;return 1;
}
#ifdef NATIVE_CP_CAPTURE_FORMAT_TEST
void native_cp_capture_format_diagnostic_test_hold_lock(void) { pthread_mutex_lock(&diagnostic_mutex); }
void native_cp_capture_format_diagnostic_test_drop_lock(void) { pthread_mutex_unlock(&diagnostic_mutex); }
#endif
