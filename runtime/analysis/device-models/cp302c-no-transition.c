/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp302c-no-transition.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct native_cp302c_snapshot state;
static unsigned int releasing,publication_started;
static struct full_imaging_io transport;

static long tid(void) { return syscall(SYS_gettid); }
static int bind_process(void) {
    int expected=0,pid=getpid();
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return atomic_load(&owner_pid)==pid;
}
static int inherited(void) {
    int pid=atomic_load(&owner_pid);return pid && pid!=getpid();
}
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static unsigned int u32(const unsigned char *p) { return u16(p)|u16(p+2)<<16; }
static void put32(unsigned char *p,unsigned int value) {
    for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(value>>(i*8));
}
static int ap_source(unsigned int source) { return source>>28==8 && (source&0x0fffffffu); }
static void fault(void) { state.faults=1;state.clean_completion=state.ap_consumed=0; }
static void invalidate(void) { fault();state.history_valid=state.current_known=0; }
static void refresh(void) {
    state.clean_completion=state.queued && state.request_freed && !state.busy &&
        !state.guard_held && !state.faults && !state.retained_request && !state.retained_cleanup &&
        (!state.diagnostic || (state.reply_freed && state.waiter_tid==state.sender_tid));
    state.ap_consumed=state.clean_completion && state.reply_freed && state.waiter_tid==state.sender_tid;
}
void native_cp302c_snapshot(struct native_cp302c_snapshot *out) {
    if(!out)return;
    if(inherited()) { *out=(struct native_cp302c_snapshot){.owner_pid=atomic_load(&owner_pid),.faults=1};return; }
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=atomic_load(&owner_pid);pthread_mutex_unlock(&mutex);
}
static void record(void (*logger)(const char *,const char *),const char *event,const char *text) {
    if(!logger)return;
    struct native_cp302c_snapshot s;native_cp302c_snapshot(&s);
    char tag[80],line[1000];snprintf(tag,sizeof tag,"NATIVE_CP302C_%s_%s ",s.diagnostic?"DIAGNOSTIC":"NOCONVERT",event);
    if(s.diagnostic)snprintf(line,sizeof line,
        "%s pid=%d tid=%ld historyseq=%llu faults=%u ap_consumed=%u diagnostic_only=1 diagnostic_transport=%u diagnostic_inputs=%u history_verified=0 current_known=0 no_transition=0 mode_transition=0 module_complete=0 module_effects=0 frame=0 capture=0 no_conversion_verified=0 native_verified=0 source_byte1_known=0 virtual_padding=1 original_CP_executed=0 live_CP_RAM_read=0",
        text,getpid(),tid(),s.history_seq,s.faults,s.ap_consumed,s.diagnostic_transport,s.diagnostic_inputs);
    else snprintf(line,sizeof line,
        "%s pid=%d tid=%ld historyseq=%llu faults=%u ap_consumed=%u no_transition=%u mode_transition=0 module_complete=0 module_effects=0 capture=0 source_byte1_known=0 virtual_padding=1 original_CP_executed=0 live_CP_RAM_read=0",
        text,getpid(),tid(),s.history_seq,s.faults,s.ap_consumed,s.no_transition);
    logger(tag,line);
}
static void hex(char *out,const unsigned char *wire,unsigned int bytes) {
    for(unsigned int i=0;i<bytes;i++)snprintf(out+2*i,3,"%02x",wire[i]);
    out[2*bytes]=0;
}
static int initialize(unsigned int diagnostic) {
    if(!bind_process())return -1021;
    pthread_mutex_lock(&mutex);
    if(state.initialized || state.history_seq || state.faults) { pthread_mutex_unlock(&mutex);return -1021; }
    state.initialized=1;state.diagnostic=diagnostic;
    if(!diagnostic) {
        /* Fresh source proof 7f959: explicit current clear BEFORE central inputs,
         * then A/B state0 and executor active1/last-event f00 constructors. These
         * are virtual source-derived fields, never a claim about live CP RAM. */
        state.history_valid=state.current_known=1;
        state.current=state.observer_a=state.observer_b=0;
        state.executor_active=1;state.executor_last_event=0xf00;
    }
    state.virtual_padding=1;state.history_seq=1;
    pthread_mutex_unlock(&mutex);return 0;
}
int native_cp302c_owner_init(void) { return initialize(0); }
int native_cp302c_diagnostic_owner_init(void) { return initialize(1); }
static int history_ready(void) {
    return state.diagnostic?(!state.history_valid && !state.current_known):
        (state.history_valid && state.current_known && !state.current);
}
int native_cp302c_parameter_prefix_supported(unsigned int command) {
    /* 10fada8/355994/35ea5c: 402a writes only parameter+160 and skips
     * the common apply flag; this recognizes input, not config consumption. */
    return command==0x402a;
}
int native_cp302c_observe_input(unsigned int dst,const void *message,
                               unsigned int source,unsigned int bytes,const char *entry) {
    if(dst!=NATIVE_CP302C_SID)return 0;
    if(!bind_process())return -1021;
    const unsigned char *p=message;(void)entry;
    pthread_mutex_lock(&mutex);
    if(!state.initialized) { state.history_seq++;invalidate();pthread_mutex_unlock(&mutex);return -1021; }
    /* A refused owned probe executes no event and may be retried after 3007. */
    if(p && bytes==24 && !p[0] && u16(p+2)==0x302c && ap_source(source)) {
        pthread_mutex_unlock(&mutex);return 0;
    }
    state.history_seq++;
    if(state.diagnostic)state.diagnostic_inputs++;
    if(p && bytes==24 && !p[0] && u16(p+2)==0x3007 && ap_source(source) &&
       history_ready() && !state.central_busy &&
       !state.busy && !state.predecessor_seen && !state.requests && !state.faults) {
        memcpy(state.predecessor_wire,p,24);state.predecessor_cookie=u32(p+4);
        state.predecessor_source=source;state.predecessor_sender_tid=tid();
        state.predecessor_seen=state.central_busy=1;
    } else if(state.diagnostic) {
        /* Unmodeled input is audit only; it cannot establish CP history. */
        if(!state.requests && p && bytes>=4 && u16(p+2)==0x3007)fault();
    } else if(p && bytes==12 && source==0x80020002u && p[0]==5 &&
              native_cp302c_parameter_prefix_supported(u16(p+2)) && state.history_valid &&
              !state.busy && !state.central_busy && !state.requests) {
        /* shortcut: remaining type5 consumers are open; they invalidate history. */
    } else invalidate();
    int rc=state.faults?-1021:0;pthread_mutex_unlock(&mutex);return rc;
}
int native_cp302c_observe_3007_reply_freed(unsigned int source,unsigned int destination,
                                        const void *wire,unsigned int bytes,int queue_rc,int free_rc,
                                        long sender_tid,long freeing_tid) {
    if(!bind_process())return -1021;
    const unsigned char *p=wire;pthread_mutex_lock(&mutex);
    if(!state.initialized || !history_ready() ||
       !state.predecessor_seen || state.predecessor_completed || !state.central_busy || state.requests ||
       state.faults || !p || bytes!=12 || p[0]!=1 || u16(p+2)!=0x3007 ||
       u32(p+4)!=state.predecessor_cookie || u32(p+8)!=0xf000 || source!=NATIVE_CP302C_SID ||
       destination!=state.predecessor_source || queue_rc || free_rc ||
       sender_tid!=state.predecessor_sender_tid || freeing_tid!=tid() || freeing_tid!=sender_tid) {
        invalidate();pthread_mutex_unlock(&mutex);return -1021;
    }
    /* Strict d974b8/eda43e predicts 0 -> 57 -> 0 after the original
     * sender's queued 3007/f000 free rc0; diagnostic records transport only. */
    if(!state.diagnostic) {
        state.current=0x57;state.history_seq++;state.current=0;state.history_seq++;
    }
    state.central_busy=0;state.predecessor_completed=1;
    pthread_mutex_unlock(&mutex);return 0;
}
/* No transport/guard/logger callback runs under mutex, including reentrant
 * frees. A bit reserves each live allocation until its actual free returns. */
static int release_owned(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                         void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(inherited()) {
        if(pointer!=state.live_reply && pointer!=state.retained_request && pointer!=state.retained_cleanup)return 0;
        *result=-1021;return 1;
    }
    unsigned char observed[12]={0};char raw[25],line[500];unsigned int kind,expected,observed_bytes=0;long freeing=tid();
    pthread_mutex_lock(&mutex);
    if(pointer==state.live_reply) { kind=1;expected=state.destination; }
    else if(pointer==state.retained_request) { kind=2;expected=NATIVE_CP302C_SID; }
    else if(pointer==state.retained_cleanup) { kind=4;expected=state.destination; }
    else { pthread_mutex_unlock(&mutex);return 0; }
    int rc=-1021;
    if(kind==1 && !(releasing&kind)) { memcpy(observed,pointer,12);observed_bytes=12; }
    if(destination!=expected || (releasing&kind) || (kind==2 && state.busy && !internal) ||
       (kind==1 && !publication_started && !internal))fault();
    else {
        releasing|=kind;
        if(kind==1 && memcmp(observed,state.reply_wire,12))fault();
        pthread_mutex_unlock(&mutex);rc=release(destination,pointer);pthread_mutex_lock(&mutex);
        releasing&=~kind;
        if(rc)fault();
        else if(kind==1) {
            state.live_reply=NULL;state.reply_freed=1;state.waiter_tid=freeing;
            if(freeing!=state.sender_tid)fault();
        } else if(kind==2) { state.retained_request=NULL;state.request_freed=1; }
        else state.retained_cleanup=NULL;
    }
    if(kind==1)state.reply_free_rc=rc;
    if(kind==2)state.request_free_rc=rc;
    refresh();long sender=state.sender_tid;pthread_mutex_unlock(&mutex);
    hex(raw,observed,12);
    snprintf(line,sizeof line,"generation=1 destination=%#x expected=%#x pointer=%p sender_tid=%ld waiter_tid=%ld rc=%d bytes=%u wire=%s kind=%u",
             destination,expected,pointer,sender,freeing,rc,observed_bytes,observed_bytes?raw:"",kind);
    record(logger,kind==1?"REPLY_FREE":kind==2?"REQUEST_FREE":"CLEANUP_FREE",line);
    *result=rc;return 1;
}
int native_cp302c_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                               void (*logger)(const char *,const char *),int *result) {
    return release_owned(destination,pointer,release,logger,result,0);
}
static int admissible(void) {
    return state.initialized && history_ready() &&
        state.predecessor_completed && !state.central_busy && !state.faults && !state.requests &&
        !state.busy && !state.retained_request && !state.live_reply && !state.retained_cleanup;
}
static void finish(const struct native_cp302c_guard *guard) {
    pthread_mutex_lock(&mutex);unsigned int held=state.guard_held;pthread_mutex_unlock(&mutex);
    if(held)guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=state.busy=0;refresh();pthread_mutex_unlock(&mutex);
}
int native_cp302c_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                          const struct native_cp302c_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP302C_SID || !request || !io || !result)return 0;
    if(inherited()) { *result=-1021;return 1; }
    if(!io->size)return 0;
    unsigned int bytes=io->size(request);const unsigned char *p=request;
    if(bytes<4 || p[0] || u16(p+2)!=0x302c)return 0;
    *result=-1021;
    if(bytes!=24 || !io->source || !io->allocate || !io->set_source || !io->send || !io->release ||
       !guard || !guard->reserve || !guard->release || !guard->predecessor_ready)return 1;
    unsigned int caller=io->source(request);if(!ap_source(caller))return 1;
    unsigned char request_wire[24],reply_wire[12]={1,0,0x2c,0x30};memcpy(request_wire,request,24);
    put32(reply_wire+4,u32(request_wire+4));put32(reply_wire+8,0xf000);
    pthread_mutex_lock(&mutex);
    if(!admissible()) {
        pthread_mutex_unlock(&mutex);record(io->record,"UNADMITTED","requests_accepted=0 reason=history-or-predecessor-or-busy");return 1;
    }
    unsigned long long sequence=state.history_seq;state.busy=1;pthread_mutex_unlock(&mutex);
    int rc=guard->reserve();
    if(rc) { finish(guard);*result=rc;return 1; }
    pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    if(guard->predecessor_ready()!=1) { finish(guard);return 1; }
    void *reply=NULL;rc=io->allocate(caller,&reply,12,1);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;
    int alias=reply && (reply==request || reply==state.live_reply || reply==state.retained_request || reply==state.retained_cleanup);
    pthread_mutex_unlock(&mutex);
    int valid=!rc && reply && !alias && io->size(reply)==12;
    if(valid) {
        memcpy(reply,reply_wire,12);io->set_source(reply,NATIVE_CP302C_SID);
        valid=io->source(reply)==NATIVE_CP302C_SID && io->size(reply)==12 && !memcmp(reply,reply_wire,12);
    }
    pthread_mutex_lock(&mutex);
    valid=valid && history_ready() &&
        !state.faults && sequence==state.history_seq && state.predecessor_completed;
    if(!valid) {
        if(alias || reply || !rc)fault();
        if(reply && !alias) { state.retained_cleanup=reply;state.destination=caller; }
        pthread_mutex_unlock(&mutex);
        if(reply && !alias) { int freed;release_owned(caller,reply,io->release,io->record,&freed,1); }
        finish(guard);*result=rc?rc:-1021;return 1;
    }
    /* Strict only: b1ffba -> b20220/b20364 -> b2232a -> b1f140(3041) returns 0:
     * current0 has no 3041 entry in the 320-row table. Invert to select
     * b20010/vptr+1c4/4b4b00, event17/4b4b86 -> b22788, BEFORE perform,
     * phase0 and observer phase1/3. No start3041/module/current commit. */
    unsigned int diagnostic=state.diagnostic;
    state.requests=state.generation=1;state.no_transition=!diagnostic;state.diagnostic_transport=diagnostic;
    state.cookie=u32(request_wire+4);
    state.destination=caller;state.sender_tid=tid();state.retained_request=request;state.live_reply=reply;
    memcpy(state.request_wire,request_wire,24);memcpy(state.reply_wire,reply_wire,12);transport=*io;
    pthread_mutex_unlock(&mutex);
    char raw[49],line[400];hex(raw,request_wire,24);
    snprintf(line,sizeof line,"generation=1 destination=%#x source=%#x bytes=24 wire=%s cookie=%#x",destination,caller,raw,u32(request_wire+4));
    record(io->record,"REQUEST",line);
    if(diagnostic)record(io->record,"TRANSPORT_ADMISSION","transport_only=1 CP_state_established=0 config_consumed=0");
    else record(io->record,"ADMISSION","query3041_can_start=0 inverted=1 current=0 source_history_valid=1 phase0=0 normal_perform=0 observer_phase1=0 observer_phase3=0 start3041=0 module_calls=0");
    /* b22788 uses the edca941d... 44B local source record; byte1 is not
     * initialized. Only the independent 4b6a70 12B projection is sent. Its
     * byte1=0 is explicit virtual padding, NOT a recovered original byte. */
    pthread_mutex_lock(&mutex);rc=state.faults || (diagnostic &&
        (!history_ready() || sequence!=state.history_seq || !state.predecessor_completed || state.central_busy))?-1021:0;
    if(rc)fault();else publication_started=1;
    pthread_mutex_unlock(&mutex);
    if(!rc)rc=io->send(caller,reply);
    pthread_mutex_lock(&mutex);state.send_rc=rc;
    if(rc)fault();else state.queued=1;
    int cleanup=rc && state.live_reply && !(releasing&1);pthread_mutex_unlock(&mutex);
    if(rc) {
        if(cleanup) { int freed;release_owned(caller,reply,io->release,io->record,&freed,1); }
    } else {
        hex(raw,reply_wire,12);snprintf(line,sizeof line,"generation=1 destination=%#x source=%#x bytes=12 wire=%s queue_rc=0",caller,NATIVE_CP302C_SID,raw);
        record(io->record,"REPLY_QUEUED",line);
        int freed;release_owned(destination,request,transport.release,io->record,&freed,1);
    }
    finish(guard);
    if(diagnostic)record(io->record,rc?"FAULT":"TRANSPORT_COMMIT","generation=1 transport_only=1 requests=1 mode_commits=0 module_ticks=0");
    else record(io->record,rc?"FAULT":"COMMIT","generation=1 no_conversion_only=1 requests=1 mode_commits=0 module_ticks=0 pending_modules_unchanged=1");
    *result=0;return 1;
}
#ifdef NATIVE_CP302C_TEST
void native_cp302c_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_cp302c_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
