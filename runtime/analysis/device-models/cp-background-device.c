/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-background-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t state_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t lease_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Atomic unsigned int faults;
static unsigned int sending;
static uint64_t next_ticket=1;
static struct cp_sync_resources *resources;
static struct cp_cold_control *control;
static void *retained_request;
struct reply_lease { uint64_t ticket; void *pointer; unsigned int destination, sending, freed; };
static struct reply_lease leases[8];

static void note(const struct full_imaging_io *io,const char *tag,const char *text) {
    if (io && io->record) io->record(tag,text);
}
static int unsupported(const struct full_imaging_io *io,int *result,const char *why) {
    note(io,"NATIVE_CP_BACKGROUND_UNSUPPORTED ",why);*result=-1021;return 1;
}
/* Claim before the very first mutex acquisition. A fork between claim and
 * lock inherits the parent's PID and refuses, even during initialization. */
static int claim_owner(void) {
    int expected=0,pid=getpid();
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return !expected || expected==pid;
}
static unsigned int u32(const unsigned char *p) {
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
static void put32(unsigned char *p,unsigned int v) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(v>>(8*i));
}
/* state_mutex held. No foreign/inherited mutex is acquired by the caller. */
static int initialize(void) {
    int pid=getpid(),owner=atomic_load(&owner_pid);
    if (owner && owner!=pid) return -1;
    if (!owner) return -1;
    if (control) return 0;
    if (!resources) resources=cp_sync_create(32u*1024u*1024u);
    if (resources) control=cp_cold_create(3,resources);
    if (!control) { atomic_fetch_add(&faults,1);return -1; }
    return 0;
}
struct cp_sync_resources *native_cp_background_resources(void) {
    if (!claim_owner()) return NULL;
    pthread_mutex_lock(&state_mutex);
    struct cp_sync_resources *r=initialize()?NULL:resources;
    pthread_mutex_unlock(&state_mutex);return r;
}
static void done_sending(void) {
    pthread_mutex_lock(&state_mutex);sending=0;pthread_mutex_unlock(&state_mutex);
}
int native_cp_background_release(unsigned int id,void *message,
                                int (*release)(unsigned int,void *),
                                void (*record)(const char *,const char *),int *result) {
    if (!message || !release || !result || !atomic_load(&owner_pid)) return 0;
    if (atomic_load(&owner_pid)!=getpid()) {
        /* The child has its own snapshot, so inspect without an inherited lock. */
        for (unsigned int i=0;i<8;i++) if (leases[i].pointer==message) { *result=-1021;return 1; }
        if (retained_request==message) { *result=-1021;return 1; }
        return 0;
    }
    struct reply_lease saved={0};unsigned char observed[12]={0};
    pthread_mutex_lock(&lease_mutex);
    for (unsigned int i=0;i<8;i++) if (leases[i].pointer==message) {
        struct reply_lease *l=&leases[i];saved=*l;
        memcpy(observed,message,sizeof observed); /* live owned payload, before free */
        if (id!=l->destination) { *result=-1021;atomic_fetch_add(&faults,1); }
        else {
            *result=release(id,message);
            if (*result) atomic_fetch_add(&faults,1);
            else {
                l->freed=1;l->pointer=NULL; /* address can immediately be reused */
                if (!l->sending) memset(l,0,sizeof *l);
            }
        }
        break;
    }
    pthread_mutex_unlock(&lease_mutex);
    if (!saved.ticket) {
        int matched=0;
        pthread_mutex_lock(&state_mutex);
        if (retained_request==message) {
            matched=1;
            *result=id==NATIVE_CP_BACKGROUND_SID?release(id,message):-1021;
            if (!*result) retained_request=NULL;
        }
        pthread_mutex_unlock(&state_mutex);
        if (matched && record) {
            char line[180];snprintf(line,sizeof line,"tid=%ld request=%p owner=%#x rc=%d",
                syscall(SYS_gettid),message,id,*result);
            record("NATIVE_CP_BACKGROUND_RETAINED_REQUEST_FREE ",line);
        }
        return matched;
    }
    if (saved.ticket && record) {
        char line[270],raw[25];
        for (unsigned int i=0;i<12;i++) snprintf(raw+2*i,3,"%02x",observed[i]);
        snprintf(line,sizeof line,"tid=%ld ticket=%llu destination=%#x message=%p bytes=12 wire=%s rc=%d",
            syscall(SYS_gettid),(unsigned long long)saved.ticket,id,message,raw,*result);
        record("NATIVE_CP_BACKGROUND_REPLY_FREE ",line);
    }
    return saved.ticket!=0;
}
int native_cp_background_dispatch(unsigned int destination,void *request,
                                 const struct full_imaging_io *io,int enabled,int *result) {
    if (!enabled || destination!=NATIVE_CP_BACKGROUND_SID || !result) return 0;
    if (!request || !io || !io->size) return unsupported(io,result,"missing-transport");
    unsigned int size=io->size(request);
    const unsigned char *body=request;
    /* A control overlay, not replacement of every CP channel. Returning
     * unhandled delegates to the original transport without inventing its
     * return value, accepting its packet or claiming a peripheral effect. */
    if (size<4 || body[0] || body[2]!=7 || body[3]!=0x30) return 0;
    if (!io->allocate || !io->release || !io->send || !io->set_source || !io->source)
        return unsupported(io,result,"missing-transport");
    if (atomic_load(&owner_pid) && atomic_load(&owner_pid)!=getpid())
        return unsupported(io,result,"inherited-profile");
    unsigned int source=io->source(request);
    if (size!=24 || !source || source==NATIVE_CP_BACKGROUND_SID)
        return unsupported(io,result,"only-type0-24B-3007-supported");
    /* Original libObj writes type and command only; byte1 and +8..23 are
     * uninitialized. The original 3007 receiver copies opaque/source into a
     * zeroed internal event and does not consume these bytes as arguments. */
    unsigned int opaque=u32(body+4);
    if (!claim_owner()) return unsupported(io,result,"inherited-profile");
    pthread_mutex_lock(&state_mutex);
    if (initialize() || sending || atomic_load(&faults) || !next_ticket) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"busy-fault-or-initialization");
    }
    unsigned int slot=8;
    pthread_mutex_lock(&lease_mutex);
    for (unsigned int i=0;i<8;i++) if (!leases[i].ticket) { slot=i;break; }
    if (slot==8) {
        pthread_mutex_unlock(&lease_mutex);pthread_mutex_unlock(&state_mutex);
        return unsupported(io,result,"reply-leases-full");
    }
    uint64_t ticket=next_ticket++;
    leases[slot]=(struct reply_lease){.ticket=ticket,.destination=source,.sending=1};
    sending=1;
    pthread_mutex_unlock(&lease_mutex);pthread_mutex_unlock(&state_mutex);

    /* Allocation may wait for the receiver to free older packets. No model
     * mutex is held, and the original request remains caller-owned on error. */
    void *reply=NULL;
    int rc=io->allocate(source,&reply,12,1);
    if (rc || !reply) {
        pthread_mutex_lock(&lease_mutex);memset(&leases[slot],0,sizeof leases[slot]);pthread_mutex_unlock(&lease_mutex);
        done_sending();*result=rc?rc:-1021;return 1;
    }
    pthread_mutex_lock(&lease_mutex);leases[slot].pointer=reply;pthread_mutex_unlock(&lease_mutex);
    rc=cp_cold_begin(control,0x3007);
    for (unsigned int i=0;!rc && i<8;i++) {
        int tick=cp_cold_tick(control);
        if (tick==1) { rc=1;break; }
        if (tick<0) { rc=tick;break; }
    }
    struct cp_cold_snapshot state={0};unsigned int command=0;
    if (rc==1 && !cp_cold_take_end(control,&command) && command==0x3007 &&
        !cp_cold_observe_end(control,command) && !cp_cold_snapshot(control,&state)) rc=0;
    else { atomic_fetch_add(&faults,1);rc=-1021; }
    if (!rc) {
        unsigned char *out=reply;
        memset(out,0,12);out[0]=1;out[2]=7;out[3]=0x30;
        put32(out+4,opaque);put32(out+8,0xf000);
        io->set_source(reply,NATIVE_CP_BACKGROUND_SID);
        char line[500];
        snprintf(line,sizeof line,"tid=%ld ticket=%llu model_mode=%u request_mode=0 generation=%u current=%#x group=%u slot0=%#x pending_modules=%#x parameter_valid=%u partial_state_generation=%u observer_a=%u observer_b=%u exec_active=%u exec_last_event=%#x destination=%#x opaque=%#x hardware_ready=0",
            syscall(SYS_gettid),(unsigned long long)ticket,state.model_mode,state.generation,state.current,state.group,
            state.observed[0],state.pending_modules,state.parameter_valid,state.state_record_generation,
            state.observer_a_index,state.observer_b_index,state.exec_active,state.exec_last_event,source,opaque);
        note(io,"NATIVE_CP_BACKGROUND_CONTROL ",line);
        /* No lock across send: a receiver may free the reply before it returns. */
        rc=io->send(source,reply);
    }
    pthread_mutex_lock(&lease_mutex);
    struct reply_lease *lease=&leases[slot];
    if (lease->ticket!=ticket) { atomic_fetch_add(&faults,1);rc=-1021; }
    else {
        lease->sending=0;
        if (rc && !lease->freed) {
            int freed=io->release(source,reply);
            if (freed) atomic_fetch_add(&faults,1);
            else { lease->pointer=NULL;lease->freed=1; }
        }
        if (lease->freed) memset(lease,0,sizeof *lease);
    }
    pthread_mutex_unlock(&lease_mutex);
    if (rc) { atomic_fetch_add(&faults,1);done_sending();*result=rc;return 1; }
    /* Successful queue transfer consumes exactly the original request. */
    int freed=io->release(NATIVE_CP_BACKGROUND_SID,request);
    if (freed) {
        atomic_fetch_add(&faults,1);
        pthread_mutex_lock(&state_mutex);retained_request=request;pthread_mutex_unlock(&state_mutex);
    }
    char line[250];snprintf(line,sizeof line,"tid=%ld ticket=%llu source=%#x request=%p reply_queue_rc=0 request_free_rc=%d camera_recovery_verified=0",
        syscall(SYS_gettid),(unsigned long long)ticket,source,request,freed);
    note(io,"NATIVE_CP_BACKGROUND_ACCEPT ",line);
    done_sending();*result=0;return 1;
}
