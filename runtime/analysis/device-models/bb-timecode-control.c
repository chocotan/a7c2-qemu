/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "bb-timecode-control.h"
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_bb_timecode_snapshot state;
static struct full_imaging_io transport;
static struct full_bb_timecode_guard reservation;
static void *request_identity, *reply_identity;
/* shortcut: 64 history slots; grow the reviewed bound if real workloads exhaust it. */
#define RETIRED_REPLY_CAPACITY 64u
static void *retired_replies[RETIRED_REPLY_CAPACITY];
static unsigned int retired_slot;
static unsigned char request_wire[12], reply_wire[12];
static unsigned int tc_committed_mask, preset_committed_mask;
static int preset_result=-EINPROGRESS;
static unsigned int owned, releasing, observing, delivery_seen;
static int fault_rc;
typedef void (*recorder)(const char *, const char *);

static unsigned int tid(void) { return (unsigned int)syscall(SYS_gettid); }
static int same_process(void) { return atomic_load(&owner_pid)==(int)getpid(); }
static unsigned int le16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static uint32_t le32(const unsigned char *p) {
    return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static int preset_command(unsigned int command) { return command==0x040a || command==0x0409; }
static void put32(unsigned char *p,uint32_t n) {
    for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));
}
static void put64(unsigned char *p,uint64_t n) {
    for(unsigned int i=0;i<8;i++)p[i]=(unsigned char)(n>>(8*i));
}
static uint64_t fnv(const unsigned char *p,unsigned int n) {
    uint64_t h=UINT64_C(14695981039346656037);
    for(unsigned int i=0;i<n;i++)h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
static void serialize(const struct full_bb_timecode_snapshot *s,unsigned char out[48]) {
    put32(out,1);put32(out+4,48);put32(out+8,(uint32_t)s->owner_pid);
    put32(out+12,s->known_mask);put64(out+16,s->generation);
    put32(out+24,s->tcmode);put32(out+28,s->dfmode);put32(out+32,s->run);
    put32(out+36,0);put64(out+40,s->applications);
}
static void read_state(unsigned char out[48]) {
    struct full_bb_timecode_snapshot s;
    full_bb_timecode_control_snapshot(&s);serialize(&s,out);
}
static void serialize_preset(const struct full_bb_timecode_snapshot *s,unsigned char out[48]) {
    put32(out,1);put32(out+4,48);put32(out+8,(uint32_t)s->owner_pid);
    put32(out+12,s->preset_known_mask);put64(out+16,s->preset_generation);
    put32(out+24,s->preset_raw4);put32(out+28,s->ubmode_wire);
    put32(out+32,0);put32(out+36,0);put64(out+40,s->preset_applications);
}
static void read_preset_state(unsigned char out[48]) {
    struct full_bb_timecode_snapshot s;
    full_bb_timecode_control_snapshot(&s);serialize_preset(&s,out);
}
/* Every event is an immutable capture made under the lock. A reentrant logger
 * can advance a later transaction without changing this event's generation. */
static void event_locked(const char *event,int rc,recorder record) {
    struct full_bb_timecode_snapshot s=state;
    uintptr_t request=(uintptr_t)request_identity,reply=(uintptr_t)reply_identity;
    unsigned int actor=tid();
    int preset=preset_command(s.command),business_result=preset?preset_result:0;
    pthread_mutex_unlock(&mutex);
    if(record) {
        char line[3072],preset_fields[512]={0};
        if(preset) {
            (void)snprintf(preset_fields,sizeof preset_fields,
                " preset_generation=%" PRIu64 " preset_known_mask=%u preset_raw4=0x%08" PRIx32 " ubmode_wire=%u preset_command_generation0=%" PRIu64 " preset_command_generation1=%" PRIu64 " preset_applications=%" PRIu64,
                s.preset_generation,s.preset_known_mask,s.preset_raw4,s.ubmode_wire,
                s.preset_command_generations[0],s.preset_command_generations[1],s.preset_applications);
        }
        (void)snprintf(line,sizeof line,
            "event=%s pid=%d tid=%u transaction=%" PRIu64 " command=0x%04x source=0x%08x request_pointer=0x%" PRIxPTR " reply_pointer=0x%" PRIxPTR
            " sender_tid=%u receiver_tid=%u generation=%" PRIu64 " known_mask=%u tcmode=%u dfmode=%u run=%u command_generation0=%" PRIu64 " command_generation1=%" PRIu64 " command_generation2=%" PRIu64
            " input_fnv=%016" PRIx64 " state_fnv=%016" PRIx64 " reply_fnv=%016" PRIx64 " result=%d rc=%d allocate_rc=%d send_rc=%d request_free_rc=%d reply_free_rc=%d cleanup_rc=%d"
            " request_free_count=%" PRIu64 " reply_free_count=%" PRIu64 " busy_count=%" PRIu64 " guard_failures=%" PRIu64 " requests=%" PRIu64 " applications=%" PRIu64
            " initialized=%u busy=%u guard_held=%u faults=%u queued=%u request_freed=%u reply_received=%u reply_freed=%u ap_consumed=%u inflight=%u pending_commit=%u retained_request=%u live_reply=%u retained_reply=%u retained_cleanup=%u"
            " software_model=1 original_CP=0 physical=0 frames=0 capture=0 native_CP_verified=0 original_RTOS_verified=0 capture_verified=0 physical_asic_compatibility_verified=0 minimal_business_patch=null%s",
            event,s.owner_pid,actor,s.transaction,s.command,s.source,request,reply,
            s.sender_tid,s.receiver_tid,s.generation,s.known_mask,s.tcmode,s.dfmode,s.run,
            s.command_generations[0],s.command_generations[1],s.command_generations[2],
            s.input_fnv,s.state_fnv,s.reply_fnv,business_result,rc,s.allocate_rc,s.send_rc,s.request_free_rc,s.reply_free_rc,s.cleanup_rc,
            s.request_free_count,s.reply_free_count,s.busy_count,s.guard_failures,s.requests,s.applications,
            s.initialized,s.busy,s.guard_held,s.faults,s.queued,s.request_freed,s.reply_received,s.reply_freed,s.ap_consumed,
            s.inflight,s.pending_commit,(unsigned int)(s.retained_request!=NULL),(unsigned int)(s.live_reply!=NULL),
            (unsigned int)(s.retained_reply!=NULL),(unsigned int)(s.retained_cleanup!=NULL),preset_fields);
        record(preset?"FUNCTIONAL_BB_TIMECODE_PRESET_EVENT ":"FUNCTIONAL_BB_TIMECODE_EVENT ",line);
    }
    pthread_mutex_lock(&mutex);
}
static void bytes_locked(const char *event,const char *kind,const unsigned char *p,unsigned int n) {
    struct full_bb_timecode_snapshot s=state;
    uintptr_t request=(uintptr_t)request_identity,reply=(uintptr_t)reply_identity;
    unsigned int actor=tid();char raw[97],line[768];
    for(unsigned int i=0;i<n;i++)(void)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;
    (void)snprintf(line,sizeof line,
        "event=%s kind=%s total=%u offset=0 bytes=%u raw=%s whole_fnv=%016" PRIx64
        " pid=%d tid=%u transaction=%" PRIu64 " command=0x%04x source=0x%08x request_pointer=0x%" PRIxPTR " reply_pointer=0x%" PRIxPTR " sender_tid=%u receiver_tid=%u",
        event,kind,n,n,raw,fnv(p,n),s.owner_pid,actor,s.transaction,s.command,s.source,request,reply,s.sender_tid,s.receiver_tid);
    recorder record=transport.record;
    pthread_mutex_unlock(&mutex);record(preset_command(s.command)?"FUNCTIONAL_BB_TIMECODE_PRESET_BYTES ":"FUNCTIONAL_BB_TIMECODE_BYTES ",line);pthread_mutex_lock(&mutex);
}
static int counters_full(void) {
    return state.transaction==UINT64_MAX || state.generation==UINT64_MAX || state.requests==UINT64_MAX ||
        state.applications==UINT64_MAX || state.request_free_count==UINT64_MAX || state.reply_free_count==UINT64_MAX ||
        state.busy_count==UINT64_MAX || state.guard_failures==UINT64_MAX ||
        state.command_generations[0]==UINT64_MAX || state.command_generations[1]==UINT64_MAX ||
        state.command_generations[2]==UINT64_MAX;
}
static int overlap(void *a,unsigned int an,void *b,unsigned int bn) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x>UINTPTR_MAX-an || y>UINTPTR_MAX-bn || (x<y+bn && y<x+an);
}
/* Under mutex; NULL searches for a slot reserved before transaction mutation. */
static unsigned int retired_index(void *pointer) {
    for(unsigned int i=0;i<RETIRED_REPLY_CAPACITY;i++)if(retired_replies[i]==pointer)return i;
    return RETIRED_REPLY_CAPACITY;
}
static int request_valid(void *p,const struct full_imaging_io *io,unsigned int caller,const unsigned char *wire,unsigned int n) {
    return io->size(p)==n && io->source(p)==caller && !memcmp(p,wire,n);
}
static int reply_valid(void *p,const struct full_imaging_io *io,const unsigned char wire[12]) {
    return io->size(p)==12 && io->source(p)==FULL_BB_TIMECODE_CONTROL_CP && !memcmp(p,wire,12);
}
static void drop_guard_locked(void) {
    if(!state.guard_held)return;
    void (*release)(void)=reservation.release;
    pthread_mutex_unlock(&mutex);release();pthread_mutex_lock(&mutex);state.guard_held=0;
}
/* Called with mutex held; retired pointer values are never dereferenced. */
static void identity_refused_locked(const char *operation,unsigned int destination,void *pointer,
    unsigned int source,unsigned int bytes,unsigned int metadata_known,unsigned int matched_slot,recorder record) {
    if(!record)return;
    int saved_errno=errno,pid=(int)getpid(),owner=atomic_load(&owner_pid);
    struct full_bb_timecode_snapshot s=state;
    void *request=request_identity,*reply=reply_identity,*matched=retired_replies[matched_slot];
    unsigned int slot=retired_slot,was_owned=owned,was_releasing=releasing,was_observing=observing,was_delivery=delivery_seen;
    unsigned int tc_commits=tc_committed_mask,preset_commits=preset_committed_mask;
    int prior_fault=fault_rc,prior_result=preset_result;
    unsigned int actor=tid(),handled=!strcmp(operation,"free");
    unsigned char before[48],after[48],other_before[48],other_after[48];
    if(preset_command(s.command)){serialize_preset(&s,before);serialize(&s,other_before);}
    else {serialize(&s,before);serialize_preset(&s,other_before);}
    char line[3072];
    int used=snprintf(line,sizeof line,
        "operation=%s pid=%d tid=%u owner_pid=%d attempt_destination=0x%08x attempt_pointer=0x%" PRIxPTR
        " attempt_source=0x%08x attempt_bytes=%u metadata_known=%u matched_slot=%u matched_pointer=0x%" PRIxPTR
        " current_transaction=%" PRIu64 " current_command=0x%04x current_sender_tid=%u current_receiver_tid=%u"
        " current_request=0x%" PRIxPTR " current_reply=0x%" PRIxPTR " current_live=0x%" PRIxPTR
        " current_retained_request=0x%" PRIxPTR " current_retained_reply=0x%" PRIxPTR " current_cleanup=0x%" PRIxPTR
        " current_busy=%u current_guard_held=%u current_faults=%u current_inflight=%u current_pending_commit=%u"
        " rc=%d handled=%u real_free_called=0 receive_result_overridden=0",
        operation,pid,actor,owner,destination,(uintptr_t)pointer,source,bytes,metadata_known,matched_slot,(uintptr_t)matched,
        s.transaction,s.command,s.sender_tid,s.receiver_tid,(uintptr_t)request,(uintptr_t)reply,(uintptr_t)s.live_reply,
        (uintptr_t)s.retained_request,(uintptr_t)s.retained_reply,(uintptr_t)s.retained_cleanup,
        s.busy,s.guard_held,s.faults,s.inflight,s.pending_commit,-EALREADY,handled);
    /* Compare the locked capture/format interval, before the recorder can reenter. */
    if(preset_command(s.command)){serialize_preset(&state,after);serialize(&state,other_after);}
    else {serialize(&state,after);serialize_preset(&state,other_after);}
    unsigned int unchanged=!memcmp(before,after,48) && !memcmp(other_before,other_after,48) &&
        owner==atomic_load(&owner_pid) && request==request_identity && reply==reply_identity &&
        matched==retired_replies[matched_slot] && slot==retired_slot &&
        s.retained_request==state.retained_request && s.live_reply==state.live_reply &&
        s.retained_reply==state.retained_reply && s.retained_cleanup==state.retained_cleanup &&
        s.transaction==state.transaction && s.command==state.command && s.source==state.source &&
        s.sender_tid==state.sender_tid && s.receiver_tid==state.receiver_tid &&
        s.initialized==state.initialized && s.busy==state.busy && s.guard_held==state.guard_held && s.faults==state.faults &&
        s.inflight==state.inflight && s.pending_commit==state.pending_commit &&
        s.queued==state.queued && s.request_freed==state.request_freed && s.reply_received==state.reply_received &&
        s.reply_freed==state.reply_freed && s.ap_consumed==state.ap_consumed &&
        s.allocate_rc==state.allocate_rc && s.send_rc==state.send_rc && s.request_free_rc==state.request_free_rc &&
        s.reply_free_rc==state.reply_free_rc && s.cleanup_rc==state.cleanup_rc &&
        s.requests==state.requests && s.request_free_count==state.request_free_count && s.reply_free_count==state.reply_free_count &&
        s.busy_count==state.busy_count && s.guard_failures==state.guard_failures &&
        s.input_fnv==state.input_fnv && s.state_fnv==state.state_fnv && s.reply_fnv==state.reply_fnv &&
        !memcmp(s.command_generations,state.command_generations,sizeof s.command_generations) &&
        !memcmp(s.preset_command_generations,state.preset_command_generations,sizeof s.preset_command_generations) &&
        was_owned==owned && was_releasing==releasing && was_observing==observing && was_delivery==delivery_seen &&
        tc_commits==tc_committed_mask && preset_commits==preset_committed_mask && prior_fault==fault_rc && prior_result==preset_result;
    if(used<0 || (size_t)used>=sizeof line){errno=saved_errno;return;}
    int suffix=snprintf(line+(size_t)used,sizeof line-(size_t)used,
        " state_before_fnv=%016" PRIx64 " state_after_fnv=%016" PRIx64 " owner_state_unchanged=%u",
        fnv(before,48),fnv(after,48),unchanged);
    if(suffix<0 || (size_t)suffix>=sizeof line-(size_t)used){errno=saved_errno;return;}
    pthread_mutex_unlock(&mutex);record("FUNCTIONAL_BB_TIMECODE_IDENTITY_REFUSED ",line);pthread_mutex_lock(&mutex);
    errno=saved_errno;
}
static int refuse_locked(int rc,recorder record) {
    event_locked("REFUSED",rc,record);pthread_mutex_unlock(&mutex);return rc;
}
/* Nonzero send keeps ownership only if no real receive has been observed.
 * An observed or already freed reply must never be reclaimed by dispatch. */
static int failure_locked(int rc,void *cleanup) {
    if(owned){state.faults=1;if(!fault_rc)fault_rc=rc;}
    if(cleanup) {
        state.retained_cleanup=cleanup;state.retained_reply=NULL;state.live_reply=NULL;
        struct full_imaging_io ops=transport;unsigned int caller=state.source;
        pthread_mutex_unlock(&mutex);
        int freed=ops.release(caller,cleanup);
        pthread_mutex_lock(&mutex);state.cleanup_rc=freed;
        if(!freed)state.retained_cleanup=NULL;
        else {state.faults=1;if(!fault_rc)fault_rc=freed;}
    }
    drop_guard_locked();state.inflight=0;
    if(!state.faults)state.busy=0;
    event_locked(state.faults?"FAULT":"REFUSED",rc,transport.record);
    pthread_mutex_unlock(&mutex);return rc;
}
static void commit_locked(recorder record) {
    if(state.queued && state.reply_freed && !state.inflight && !state.guard_held && !state.faults) {
        if(preset_command(state.command))preset_committed_mask|=1u<<(state.command==0x040a?0:1);
        else tc_committed_mask|=1u<<(state.command-0x0400);
        state.pending_commit=0;state.ap_consumed=1;state.busy=0;owned=0;
        event_locked("COMMIT",0,record);
    }
}
int full_bb_timecode_control_owner_init(void) {
    int pid=(int)getpid(),expected=0;
    (void)atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!same_process())return -ECHILD;
    pthread_mutex_lock(&mutex);
    if(state.initialized){pthread_mutex_unlock(&mutex);return -EALREADY;}
    state.owner_pid=pid;state.initialized=1;
    unsigned char initial[48];serialize(&state,initial);state.state_fnv=fnv(initial,48);
    pthread_mutex_unlock(&mutex);return 0;
}
void full_bb_timecode_control_snapshot(struct full_bb_timecode_snapshot *out) {
    if(!out)return;
    if(!same_process()) {
        *out=(struct full_bb_timecode_snapshot){.owner_pid=atomic_load(&owner_pid),.faults=1};return;
    }
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
int full_bb_timecode_control_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
    const struct full_bb_timecode_guard *guard,int enabled,int *result) {
    if(!enabled || destination!=FULL_BB_TIMECODE_CONTROL_CP)return 0;
    if(!result)return 1;
    if(!same_process()){*result=-ECHILD;return 1;}
    if(enabled!=1 || !request || !io || !io->size){*result=-EINVAL;return 1;}
    unsigned int n=io->size(request);
    if(n<4)return 0;
    unsigned int command=le16((unsigned char *)request+2);
    int preset=preset_command(command);
    if(!preset && (command<0x0400 || command>0x0402))return 0;
    unsigned int expected_n=command==0x040a?12:10;
    if(n!=expected_n || !io->source || !io->allocate || !io->release || !io->set_source || !io->send || !io->record ||
       !guard || !guard->reserve || !guard->release || !guard->predecessors_ready){*result=-EINVAL;return 1;}
    unsigned char wire[12]={0};memcpy(wire,request,n);
    unsigned int caller=io->source(request),index=preset?(command==0x040a?0u:1u):command-0x0400;
    if(le16(wire)!=0x200d || le16(wire+4)!=n || le16(wire+6)!=0x8001 ||
       (command!=0x040a && le16(wire+8)>1) ||
       caller<0x80000001u || caller>0x8fffffffu){*result=-EINVAL;return 1;}
    struct full_imaging_io ops=*io;
    struct full_bb_timecode_guard guards=*guard;
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.faults) {*result=refuse_locked(-EPERM,ops.record);return 1;}
    if(state.busy) {
        int rc=-EBUSY;
        if(state.busy_count==UINT64_MAX)rc=-EOVERFLOW;else state.busy_count++;
        *result=refuse_locked(rc,ops.record);return 1;
    }
    /* Functional sequencing policy: actual owner COMMIT, not initialized bits. */
    if(preset && (tc_committed_mask!=7 || state.known_mask!=7 ||
       !state.command_generations[0] || !state.command_generations[1] || !state.command_generations[2] ||
       (command==0x0409 && (!(preset_committed_mask&1u) || !(state.preset_known_mask&1u) || !state.preset_command_generations[0])))) {
        pthread_mutex_unlock(&mutex);*result=-ENODATA;return 1;
    }
    if(counters_full() || (preset && (state.preset_generation==UINT64_MAX || state.preset_applications==UINT64_MAX ||
       state.preset_command_generations[0]==UINT64_MAX || state.preset_command_generations[1]==UINT64_MAX))) {
        *result=refuse_locked(-EOVERFLOW,ops.record);return 1;
    }
    unsigned int slot=retired_index(NULL);
    if(slot==RETIRED_REPLY_CAPACITY) {*result=refuse_locked(-ENOSPC,ops.record);return 1;}
    retired_slot=slot;
    state.transaction++;state.requests++;state.busy=1;
    state.sender_tid=tid();state.receiver_tid=0;state.command=command;state.source=caller;
    state.queued=state.request_freed=state.reply_received=state.reply_freed=state.ap_consumed=0;
    state.allocate_rc=state.send_rc=state.request_free_rc=state.reply_free_rc=state.cleanup_rc=-EINPROGRESS;
    state.inflight=state.pending_commit=0;state.input_fnv=fnv(wire,n);state.reply_fnv=0;
    if(preset)preset_result=-EINPROGRESS;
    transport=ops;reservation=guards;owned=releasing=observing=delivery_seen=0;fault_rc=0;
    request_identity=request;reply_identity=NULL;memcpy(request_wire,wire,n);
    struct full_bb_timecode_snapshot prior=state;
    unsigned char before[48],expected_before[48];
    if(preset)serialize_preset(&prior,expected_before);else serialize(&prior,expected_before);
    pthread_mutex_unlock(&mutex);
    if(preset)read_preset_state(before);else read_state(before);
    pthread_mutex_lock(&mutex);
    if(memcmp(before,expected_before,48)) {*result=failure_locked(-EBADMSG,NULL);return 1;}
    state.state_fnv=fnv(before,48);
    event_locked("BEGIN",0,ops.record);
    bytes_locked("BEGIN","request",wire,n);bytes_locked("BEGIN","state_before",before,48);
    pthread_mutex_unlock(&mutex);
    int rc=guards.reserve();
    pthread_mutex_lock(&mutex);
    if(rc) {state.guard_failures++;*result=failure_locked(rc,NULL);return 1;}
    state.guard_held=1;pthread_mutex_unlock(&mutex);
    int ready=guards.predecessors_ready();
    pthread_mutex_lock(&mutex);
    if(ready!=1) {state.guard_failures++;*result=failure_locked(ready<0?ready:-ENODATA,NULL);return 1;}
    pthread_mutex_unlock(&mutex);
    void *reply=NULL;rc=ops.allocate(caller,&reply,12,1);
    int allocation_observed=0;
    if(!rc && reply && !overlap(reply,12,request,n))
        allocation_observed=full_bb_timecode_control_observe_allocate(caller,reply,12,1,rc);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;
    if(reply && overlap(reply,12,request,n)) {
        *result=failure_locked(rc?rc:-EINVAL,NULL);return 1;
    }
    if(allocation_observed<0) {*result=failure_locked(allocation_observed,NULL);return 1;}
    if(rc || !reply) {*result=failure_locked(rc?rc:-ENOMEM,reply);return 1;}
    pthread_mutex_unlock(&mutex);
    if(ops.size(reply)!=12) {pthread_mutex_lock(&mutex);*result=failure_locked(-EMSGSIZE,reply);return 1;}
    unsigned char response[12]={0x0d,0x20,0,0x14,12,0,1,0x80,0,0,0,0};
    response[2]=(unsigned char)(command-0x0400);
    if(preset)put32(response+8,(uint32_t)-EINPROGRESS);
    memcpy(reply,response,12);ops.set_source(reply,FULL_BB_TIMECODE_CONTROL_CP);
    int valid=reply_valid(reply,&ops,response) && request_valid(request,&ops,caller,wire,n);
    ready=guards.predecessors_ready();
    valid=valid && reply_valid(reply,&ops,response) && request_valid(request,&ops,caller,wire,n);
    pthread_mutex_lock(&mutex);
    if(!valid || ready!=1) {
        if(ready!=1)state.guard_failures++;
        *result=failure_locked(ready!=1?(ready<0?ready:-ENODATA):-EBADMSG,reply);return 1;
    }
    /* OWNERSHIP TRANSFER: preallocated, independent reply and original request
     * now belong to this owner. Subsequent errors are sticky; no state rollback. */
    owned=1;state.retained_request=request;state.retained_reply=reply;
    unsigned char actual_reply[12];memcpy(actual_reply,reply,12);
    reply_identity=reply;memcpy(reply_wire,actual_reply,12);state.reply_fnv=fnv(actual_reply,12);
    /* Explicit software work item consumption; no CP RAM, RTOS or ASIC writes. */
    unsigned int value=preset?(index==0?le32(request_wire+8):le16(request_wire+8)):request_wire[8];
    if(preset) {
        if(index==0)state.preset_raw4=value;else state.ubmode_wire=value;
        state.preset_known_mask|=1u<<index;state.preset_generation++;state.preset_applications++;
        state.preset_command_generations[index]=state.preset_generation;
    } else {
        if(index==0)state.tcmode=value;else if(index==1)state.dfmode=value;else state.run=value;
        state.known_mask|=1u<<index;state.generation++;state.applications++;
        state.command_generations[index]=state.generation;
    }
    event_locked("STATE_WRITTEN",0,ops.record);pthread_mutex_unlock(&mutex);
    unsigned char after[48],expected_state[48];
    if(preset)read_preset_state(after);else read_state(after);
    memcpy(expected_state,before,48);
    /* Expected is only a comparison oracle; actual bytes came from the getter. */
    put32(expected_state+12,(preset?prior.preset_known_mask:prior.known_mask)|(1u<<index));
    put64(expected_state+16,(preset?prior.preset_generation:prior.generation)+1);
    put32(expected_state+24+4*index,value);
    put64(expected_state+40,(preset?prior.preset_applications:prior.applications)+1);
    pthread_mutex_lock(&mutex);
    int readback_ok=!memcmp(after,expected_state,48);
    if(preset) {
        readback_ok=readback_ok && state.preset_generation==prior.preset_generation+1 && state.preset_applications==prior.preset_applications+1;
        for(unsigned int i=0;i<2;i++)
            if(state.preset_command_generations[i]!=(i==index?state.preset_generation:prior.preset_command_generations[i]))readback_ok=0;
    } else {
        readback_ok=readback_ok && state.generation==prior.generation+1 && state.applications==prior.applications+1;
        for(unsigned int i=0;i<3;i++)
            if(state.command_generations[i]!=(i==index?state.generation:prior.command_generations[i]))readback_ok=0;
    }
    state.state_fnv=fnv(after,48);
    if(!readback_ok || state.faults) {*result=failure_locked(fault_rc?fault_rc:-EBADMSG,reply);return 1;}
    if(preset) {
        preset_result=0;put32(response+8,0);memcpy(reply,response,12);
        memcpy(actual_reply,reply,12);memcpy(reply_wire,actual_reply,12);state.reply_fnv=fnv(actual_reply,12);
    }
    event_locked("STATE_READBACK",0,ops.record);
    bytes_locked("STATE_READBACK","state_after",after,48);bytes_locked("STATE_READBACK","reply",actual_reply,12);
    pthread_mutex_unlock(&mutex);
    valid=reply_valid(reply,&ops,response) && request_valid(request,&ops,caller,wire,n);
    pthread_mutex_lock(&mutex);
    if(!valid || state.faults) {*result=failure_locked(fault_rc?fault_rc:-EBADMSG,reply);return 1;}
    pthread_mutex_unlock(&mutex);
    rc=ops.release(destination,request);
    pthread_mutex_lock(&mutex);state.request_free_rc=rc;
    if(!rc){state.request_freed=1;state.request_free_count++;state.retained_request=NULL;}
    event_locked("REQUEST_FREE",rc,ops.record);
    if(rc) {*result=failure_locked(rc,reply);return 1;}
    pthread_mutex_unlock(&mutex);valid=reply_valid(reply,&ops,response);pthread_mutex_lock(&mutex);
    if(!valid || state.faults) {*result=failure_locked(fault_rc?fault_rc:-EBADMSG,reply);return 1;}
    /* Conservative software policy: publish only after original free returned 0. */
    state.live_reply=reply;state.inflight=1;pthread_mutex_unlock(&mutex);
    rc=ops.send(caller,reply);
    pthread_mutex_lock(&mutex);state.send_rc=rc;
    if(rc) {
        void *cleanup=(!delivery_seen && !state.reply_freed && !releasing)?reply:NULL;
        *result=failure_locked(rc,cleanup);return 1;
    }
    state.queued=1;event_locked("REPLY_QUEUED",0,ops.record);
    drop_guard_locked();state.inflight=0;
    if(state.faults) {*result=failure_locked(fault_rc?fault_rc:-EIO,NULL);return 1;}
    commit_locked(ops.record);pthread_mutex_unlock(&mutex);*result=0;return 1;
}
int full_bb_timecode_control_observe_allocate(unsigned int destination,void *pointer,unsigned int bytes,unsigned int count,int rc) {
    if(!same_process())return -ECHILD;
    if(rc || count!=1 || !pointer)return 0;
    /* Any real new allocation, including foreign destination/size, ends an
     * address's historical identity. Its metadata must not filter retirement. */
    (void)destination;(void)bytes;
    pthread_mutex_lock(&mutex);
    if((state.busy && !state.request_freed && pointer==request_identity) ||
       pointer==state.retained_request || pointer==state.live_reply || pointer==state.retained_reply || pointer==state.retained_cleanup) {
        pthread_mutex_unlock(&mutex);return -EBUSY;
    }
    if(pointer==reply_identity) {
        int retired=state.initialized && state.reply_freed && state.request_freed && state.ap_consumed && state.queued &&
            !state.busy && !state.inflight && !state.pending_commit && !state.guard_held && !state.faults &&
            !state.retained_request && !state.live_reply && !state.retained_reply && !state.retained_cleanup &&
            !owned && !releasing && !observing && !state.send_rc && !state.request_free_rc && !state.reply_free_rc;
        if(!retired) {pthread_mutex_unlock(&mutex);return -EBUSY;}
        reply_identity=NULL;
    }
    unsigned int slot=retired_index(pointer);
    if(slot==RETIRED_REPLY_CAPACITY) {pthread_mutex_unlock(&mutex);return 0;}
    retired_replies[slot]=NULL;
    pthread_mutex_unlock(&mutex);return 1;
}
int full_bb_timecode_control_observe_receive(unsigned int destination,void *pointer,unsigned int source,unsigned int bytes) {
    if(!same_process())return -ECHILD;
    pthread_mutex_lock(&mutex);
    unsigned int matched=pointer && pointer!=reply_identity?retired_index(pointer):RETIRED_REPLY_CAPACITY;
    if(matched!=RETIRED_REPLY_CAPACITY) {
        identity_refused_locked("receive",destination,pointer,source,bytes,1,matched,transport.record);
        return refuse_locked(-EALREADY,transport.record);
    }
    if(!pointer || pointer!=reply_identity) {pthread_mutex_unlock(&mutex);return 0;}
    if(pointer==state.live_reply && (state.inflight || state.queued))delivery_seen=1;
    int rc=0;
    if(state.reply_freed || state.reply_received)rc=-EALREADY;
    else if(state.faults || pointer!=state.live_reply || (!state.inflight && !state.queued) || observing || releasing)rc=-EBUSY;
    else if(destination!=state.source || source!=FULL_BB_TIMECODE_CONTROL_CP || bytes!=12 || tid()!=state.sender_tid)rc=-EPERM;
    if(rc) {
        if(owned && !state.reply_freed){state.faults=1;state.retained_reply=state.live_reply;if(!fault_rc)fault_rc=rc;}
        event_locked(state.faults?"FAULT":"REFUSED",rc,transport.record);pthread_mutex_unlock(&mutex);return rc;
    }
    observing=1;struct full_imaging_io ops=transport;
    pthread_mutex_unlock(&mutex);
    int valid=reply_valid(pointer,&ops,reply_wire);
    pthread_mutex_lock(&mutex);observing=0;
    if(!valid || state.faults) {
        state.faults=1;state.retained_reply=pointer;if(!fault_rc)fault_rc=-EBADMSG;
        int error=fault_rc;event_locked("FAULT",error,ops.record);pthread_mutex_unlock(&mutex);return error;
    }
    state.reply_received=1;state.receiver_tid=tid();
    event_locked("RECEIVE",0,ops.record);pthread_mutex_unlock(&mutex);return 1;
}
int full_bb_timecode_control_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
    void (*record)(const char *,const char *),int *result) {
    if(!result)return 1;
    if(!same_process()){*result=-ECHILD;return 1;}
    pthread_mutex_lock(&mutex);
    unsigned int matched=pointer && pointer!=reply_identity?retired_index(pointer):RETIRED_REPLY_CAPACITY;
    if(matched!=RETIRED_REPLY_CAPACITY) {
        identity_refused_locked("free",destination,pointer,0,0,0,matched,record?record:transport.record);
        *result=refuse_locked(-EALREADY,record?record:transport.record);return 1;
    }
    if(!pointer || pointer!=reply_identity) {pthread_mutex_unlock(&mutex);return 0;}
    recorder log=record?record:transport.record;int rc=0;
    if(state.reply_freed)rc=-EALREADY;
    else if(!release || releasing || observing || !state.reply_received || pointer!=state.live_reply)rc=-EBUSY;
    else if(destination!=state.source || tid()!=state.sender_tid || tid()!=state.receiver_tid)rc=-EPERM;
    if(rc) {
        if(owned && !state.reply_freed){state.faults=1;state.retained_reply=state.live_reply;if(!fault_rc)fault_rc=rc;}
        event_locked(state.faults?"FAULT":"REFUSED",rc,log);pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    if(state.faults) {*result=refuse_locked(-EPERM,log);return 1;}
    releasing=1;pthread_mutex_unlock(&mutex);
    rc=release(destination,pointer);
    pthread_mutex_lock(&mutex);releasing=0;state.reply_free_rc=rc;
    if(rc){state.faults=1;state.retained_reply=pointer;if(!fault_rc)fault_rc=rc;}
    else {
        retired_replies[retired_slot]=pointer;
        state.reply_free_count++;state.reply_freed=1;state.live_reply=state.retained_reply=NULL;
        state.pending_commit=1;
    }
    event_locked("REPLY_FREE",rc,log);
    if(rc)event_locked("FAULT",rc,log);else commit_locked(log);
    pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
