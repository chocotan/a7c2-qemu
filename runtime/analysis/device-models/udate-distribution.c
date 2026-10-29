/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "udate-distribution.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t state_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid, busy, faults;
static struct native_udate_snapshot state;
static void *retained_request;
static unsigned int retained_id;
struct retained_message { void *pointer; unsigned int id; };
static struct retained_message retained[4];

static void note(const struct native_udate_io *io,const char *tag,const char *text) {
    if (io && io->record) io->record(tag,text);
}
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static unsigned int u32(const unsigned char *p) {
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
static unsigned long long u64(const unsigned char *p) {
    unsigned long long v=0;for (unsigned int i=0;i<8;i++) v|=(unsigned long long)p[i]<<(8*i);return v;
}
static void put16(unsigned char *p,unsigned int v) { p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8); }
static void put32(unsigned char *p,unsigned int v) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(v>>(8*i));
}
static int claim_owner(void) {
    int expected=0,pid=getpid();
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return !expected || expected==pid;
}
static int fail(const struct native_udate_io *io,int *result,const char *stage,int rc) {
    if (!rc) rc=-1021;
    atomic_fetch_add(&faults,1);
    if (io && io->record) {
        char line[280];
        snprintf(line,sizeof line,"tid=%ld stage=%s rc=%d faults=%u virtual_completion=0",
                 syscall(SYS_gettid),stage,rc,atomic_load(&faults));
        io->record("NATIVE_UDATE_ERROR ",line);
    }
    *result=rc;return 1;
}
static void retain(unsigned int id,void *message,const struct native_udate_io *io) {
    pthread_mutex_lock(&state_mutex);
    unsigned int slot=4;
    for (unsigned int i=0;i<4;i++) if (!retained[i].pointer) { slot=i;break; }
    if (slot<4) retained[slot]=(struct retained_message){message,id};
    pthread_mutex_unlock(&state_mutex);
    atomic_fetch_add(&faults,1);
    if (io && io->record) {
        char line[220];
        snprintf(line,sizeof line,"tid=%ld id=%#x message=%p retained=%u",
                 syscall(SYS_gettid),id,message,slot<4?slot+1:4);
        io->record("NATIVE_UDATE_RETAIN ",line);
    }
}
static int release_or_retain(const struct native_udate_io *io,unsigned int id,void **message) {
    if (!*message) return 0;
    int rc=io->release(id,*message);
    if (rc) retain(id,*message,io);
    *message=NULL;
    return rc;
}
static int timer_read(const struct native_udate_io *io,unsigned long long *value) {
    unsigned char request[32]={0};put32(request,32);
    int rc=io->sync_direct(0x910042,request);
    if (!rc) *value=u64(request+0x18);
    return rc;
}
static int leap(unsigned int year) { return year%4==0 && (year%100!=0 || year%400==0); }
static int valid_date(const unsigned char *p) {
    static const unsigned char days[]={31,28,31,30,31,30,31,31,30,31,30,31};
    unsigned int year=u16(p),month=p[2],day=p[3];
    if (year<1 || month<1 || month>12 || day<1 || p[12]>2) return 0;
    unsigned int limit=days[month-1]+(month==2 && leap(year));
    return day<=limit && p[4]<24 && p[5]<60 && p[6]<60;
}
static int valid_timezone_half(unsigned int raw) {
    if (raw==0x7fff) return 1;
    int value=(int)(short)raw;
    return value>=-1440 && value<=1440;
}
static int valid_timezone(const unsigned char *p) {
    return valid_timezone_half(u16(p)) && valid_timezone_half(u16(p+2)) && u16(p+4)==0;
}
int native_udate_distribution_release(unsigned int id,void *message,
    int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *result) {
    if (!message || !release || !result || !atomic_load(&owner_pid)) return 0;
    if (atomic_load(&owner_pid)!=getpid()) {
        /* A fork child may inherit this mutex already locked. Its private
         * post-fork snapshot is readable without taking that inherited lock. */
        int matched=retained_request==message;
        if (!matched) for (unsigned int i=0;i<4;i++) if (retained[i].pointer==message) { matched=1;break; }
        if (matched) { *result=-1021;return 1; }
        return 0;
    }
    pthread_mutex_lock(&state_mutex);
    if (retained_request==message) {
        *result=id==retained_id?release(id,message):-1021;
        if (!*result) retained_request=NULL;
        pthread_mutex_unlock(&state_mutex);
        if (record) {
            char line[200];snprintf(line,sizeof line,"tid=%ld id=%#x message=%p rc=%d",
                syscall(SYS_gettid),id,message,*result);
            record("NATIVE_UDATE_RETAINED_FREE ",line);
        }
        return 1;
    }
    unsigned int slot=4;
    for (unsigned int i=0;i<4;i++) if (retained[i].pointer==message) { slot=i;break; }
    if (slot==4) { pthread_mutex_unlock(&state_mutex);return 0; }
    unsigned int expected=retained[slot].id;
    *result=id==expected?release(id,message):-1021;
    if (!*result) retained[slot].pointer=NULL;
    pthread_mutex_unlock(&state_mutex);
    if (record) {
        char line[200];snprintf(line,sizeof line,"tid=%ld id=%#x message=%p rc=%d",
            syscall(SYS_gettid),id,message,*result);
        record("NATIVE_UDATE_AUX_FREE ",line);
    }
    return 1;
}
int native_udate_distribution_dispatch(unsigned int destination,void *request,
    const struct native_udate_io *io,int enabled,int *result) {
    if (!enabled || destination!=NATIVE_UDATE_DISTRIBUTION_TARGET1_SID || !result) return 0;
    if (!request || !io || !io->size || !io->source) return fail(io,result,"missing-request",-1021);
    const unsigned char *body=request;
    unsigned int size=io->size(request),source=io->source(request);
    unsigned int observed_type=size>=4?u32(body):0;
    unsigned int observed_sync=size>=12?u32(body+8):0;
    unsigned int observed_reason=size>=0x2a?u16(body+0x28):0;
    if (size!=NATIVE_UDATE_DISTRIBUTION_MESSAGE_BYTES || observed_type!=1 || observed_sync!=0 ||
        observed_reason!=1 || source!=NATIVE_UDATE_DISTRIBUTION_SID) {
        static _Atomic unsigned int unhandled;
        unsigned int n=atomic_fetch_add(&unhandled,1);
        if (n<16 && io->record) {
            char line[280];snprintf(line,sizeof line,
                "tid=%ld destination=%#x source=%#x size=%u type=%#x sync=%#x reason=%#x delegated=1",
                syscall(SYS_gettid),destination,source,size,observed_type,observed_sync,observed_reason);
            io->record("NATIVE_UDATE_UNHANDLED ",line);
        }
        return 0;
    }
    if (!io->allocate || !io->release || !io->set_source || !io->send ||
        !io->dynamic_id || !io->receive || !io->sync_direct)
        return fail(io,result,"missing-transport",-1021);
    if (!claim_owner()) return fail(io,result,"inherited-profile",-1021);
    if (atomic_exchange(&busy,1)) return fail(io,result,"busy",-1021);
    if (atomic_load(&faults)) { atomic_store(&busy,0);return fail(io,result,"latched-fault",-1021); }
    if (io->record) {
        char line[240];snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x bytes=%u reason=1",
            syscall(SYS_gettid),destination,source,size);
        io->record("NATIVE_UDATE_REQUEST ",line);
    }
    void *query=NULL,*reply=NULL,*done=NULL;
    const char *stage="roundtrip";
    unsigned int queue=0,reply_queue=0,queue_active=0,queue_pending=0,response_size=0;
    unsigned char response[44];
    unsigned long long before=0,after=0;
    int rc=timer_read(io,&before);
    if (rc) { atomic_store(&busy,0);return fail(io,result,"timer-before",rc); }
    rc=io->dynamic_id(0x2a,0x90,(unsigned long)&queue);
    if (rc || !queue) { atomic_store(&busy,0);return fail(io,result,"queue-create",rc?rc:-1021); }
    queue_active=1;reply_queue=queue|0x80000000U;
    stage="query-allocate";
    rc=io->allocate(source,&query,44,1);
    if (rc || !query) goto cleanup;
    memset(query,0,44);put32(query,2);put32((unsigned char *)query+8,1);
    /* The original receiver takes the reply destination from body+0x0c;
     * OSAL source remains the virtual remote's base identity. */
    put32((unsigned char *)query+0x0c,reply_queue);
    io->set_source(query,NATIVE_UDATE_DISTRIBUTION_SID);
    stage="query-send";
    rc=io->send(source,query);
    if (rc) goto cleanup;
    query=NULL;queue_pending=1;stage="receive"; /* the original AP distribution thread now owns it */
    if (io->record) {
        char line[260];snprintf(line,sizeof line,"tid=%ld destination=%#x reply_queue=%#x timer_before=%llu",
            syscall(SYS_gettid),source,reply_queue,before);
        io->record("NATIVE_UDATE_QUERY ",line);
    }
    rc=io->receive(reply_queue,&reply,NATIVE_UDATE_DISTRIBUTION_REPLY_TIMEOUT_MS);
    if (rc || !reply) goto cleanup;
    queue_pending=0;
    response_size=io->size(reply);
    if (response_size==44) memcpy(response,reply,44);
    stage="response-free";
    rc=release_or_retain(io,reply_queue,&reply);
    if (rc) goto cleanup;
    stage="queue-free";
    rc=io->dynamic_id(0x4a,0,reply_queue);queue_active=0;
    if (rc) goto cleanup;
    stage="timer-after";
    rc=timer_read(io,&after);
    if (rc || after<before) goto cleanup;
    stage="response-validate";
    if (response_size!=44 || u32(response)!=2 || u32(response+4)!=0 ||
        !valid_date(response+0x10) || !valid_timezone(response+0x20)) {
        rc=-1021;goto cleanup;
    }
    pthread_mutex_lock(&state_mutex);
    memcpy(state.date,response+0x10,16);memcpy(state.timezone,response+0x20,8);
    state.reason=1;state.timer_before=before;state.timer_after=after;
    state.elapsed=(after-before)>>1;state.generation++;state.valid=1;state.done_sent=0;
    unsigned long long generation=state.generation;
    pthread_mutex_unlock(&state_mutex);
    if (io->record) {
        char line[360];snprintf(line,sizeof line,
            "tid=%ld generation=%llu date=%04u-%02u-%02uT%02u:%02u:%02u type=%u timezone=%d/%d elapsed=%llu status=0",
            syscall(SYS_gettid),generation,u16(response+0x10),response[0x12],response[0x13],
            response[0x14],response[0x15],response[0x16],response[0x1c],
            (short)u16(response+0x20),(short)u16(response+0x22),(after-before)>>1);
        io->record("NATIVE_UDATE_RESPONSE ",line);
    }
    stage="done-allocate";
    rc=io->allocate(source,&done,44,1);
    if (rc || !done) goto cleanup;
    memset(done,0,44);put32(done,4);put16((unsigned char *)done+0x28,1);
    /* Emulate the source identity visible after the target1 inter-chip
     * receive: done_notified() extracts bits 28..30 to select its semaphore. */
    io->set_source(done,destination);
    stage="done-send";
    rc=io->send(source,done);
    if (rc) goto cleanup;
    done=NULL; /* original UDATE_INTERSYNC now owns and consumes it */
    pthread_mutex_lock(&state_mutex);state.done_sent=1;pthread_mutex_unlock(&state_mutex);
    rc=io->release(destination,request);
    if (rc) {
        pthread_mutex_lock(&state_mutex);retained_request=request;retained_id=destination;pthread_mutex_unlock(&state_mutex);
        atomic_fetch_add(&faults,1);
    }
    atomic_store(&busy,0);
    if (io->record) {
        char line[420];snprintf(line,sizeof line,
            "tid=%ld generation=%llu reason=1 target=1 done_source=%#x timer_before=%llu timer_after=%llu elapsed=%llu request_free_rc=%d faults=%u request_retained=%u done_sent=1 virtual_completion=1 hardware_ready=0 camera_capture_verified=0",
            syscall(SYS_gettid),generation,destination,before,after,(after-before)>>1,rc,
            atomic_load(&faults),rc!=0);
        io->record("NATIVE_UDATE_DONE ",line);
    }
    *result=0;return 1;
cleanup:
    if (query) (void)release_or_retain(io,source,&query);
    if (reply) (void)release_or_retain(io,reply_queue,&reply);
    if (done) (void)release_or_retain(io,source,&done);
    if (queue_active && queue_pending) {
        /* A late original reply has nowhere safe to go if this queue is freed. */
        atomic_fetch_add(&faults,1);
        note(io,"NATIVE_UDATE_QUEUE_RETAINED ","response-pending; no normal completion");
    } else if (queue_active) {
        int freed=io->dynamic_id(0x4a,0,reply_queue);
        if (freed) atomic_fetch_add(&faults,1);
    }
    atomic_store(&busy,0);
    return fail(io,result,stage,rc?rc:-1021);
}
#ifdef NATIVE_UDATE_DISTRIBUTION_TEST
void native_udate_test_reset(void) {
    memset(&state,0,sizeof state);memset(retained,0,sizeof retained);
    retained_request=NULL;retained_id=0;
    atomic_store(&owner_pid,0);atomic_store(&busy,0);atomic_store(&faults,0);
}
void native_udate_test_snapshot(struct native_udate_snapshot *out) {
    pthread_mutex_lock(&state_mutex);*out=state;
    out->retained=retained_request!=NULL;pthread_mutex_unlock(&state_mutex);
    out->busy=atomic_load(&busy);out->faults=atomic_load(&faults);
}
void native_udate_test_lock_state(void) { pthread_mutex_lock(&state_mutex); }
void native_udate_test_unlock_state(void) { pthread_mutex_unlock(&state_mutex); }
#endif
