/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "scalar-connection.h"
#include "scalar-device.h"
#include "adf-device.h"
#include "adf-connection.h"
#include "pinmem-device.h"
#include "pin-registry-core.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#ifndef SOURCE_TYPE
#define SOURCE_TYPE 0u
#endif
#if SOURCE_TYPE != 0 && SOURCE_TYPE != 6
#error Only source-closed PinMem YC and DrawInfo callbacks are supported
#endif
#define EDGE_JOIN_INNER(a,b) a##b
#define EDGE_JOIN(a,b) EDGE_JOIN_INNER(a,b)
#ifndef EDGE_TEST_EVENT_CORRUPT
#define EDGE_TEST_EVENT_CORRUPT EDGE_JOIN(EDGE_NATIVE_DISPATCH,_test_event_corrupt)
#endif
#ifndef EDGE_TEST_EVENT_CONSUME
#define EDGE_TEST_EVENT_CONSUME EDGE_JOIN(EDGE_NATIVE_DISPATCH,_test_event_consume)
#endif
#define EVENT_TOKEN (0x504d0000u | (SOURCE_TYPE<<12) | SOURCE_INDEX)
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static struct scalar_connection_snapshot state;
static void *messages[3],*current_request;
static unsigned char saved_request[64];
static long sender;
static const unsigned int S[4]={SOURCE_TYPE,2,SOURCE_INDEX,FULL_PINMEM_CP},P[4]={SOURCE_TYPE,1,PEER_INDEX,PEER_CP};
/* Original context getters read this saved queue entry, not the incoming reply.
 * Only the 12-byte incoming event parameter contains the owned reply token. */
static struct local_event6 {
    unsigned char parameter[12],request[64],answer_wire[72];
    void *answer,*body;
    unsigned int source,destination,token;
} event6;
static int pid_matches(void){return atomic_load(&process_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(i*8));}
static unsigned long long hash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;return h;
}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[96];snprintf(tag,sizeof tag,"FULL_" EDGE_TAG "_CONNECT_%s",kind);io->record(tag,text);}
}
static void fault(const struct full_imaging_io *io,const char *text){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",text);
}
static int healthy(void){pthread_mutex_lock(&mutex);int ok=!state.faults;pthread_mutex_unlock(&mutex);return ok;}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[145],line[650];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;
    snprintf(line,sizeof line,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s original_CP_executed=0 frames_verified=0 capture_verified=0",getpid(),syscall(SYS_gettid),src,dst,pointer,n,raw);
    event(io,kind,line);
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *p,unsigned int n){wire_from(io,kind,src,dst,p,p,n);}
static void envelope(unsigned char *p,unsigned int n,unsigned int op,unsigned int flags){
    put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,op);put16(p+28,n-24);put16(p+30,flags);
}
static void pair(unsigned char *p){for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}}
static int valid_pair(const unsigned char *p){
    for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;
    return 1;
}
static int canonical(const struct full_imaging_io *io,void *p,const unsigned char *expected,unsigned int n,unsigned int src){
    return p && io->size(p)==n && io->source(p)==src && !memcmp(p,expected,n);
}
static void forget(void *p){for(unsigned int i=0;i<3;i++)if(messages[i]==p){messages[i]=0;break;}}
static int drop(const struct full_imaging_io *io,unsigned int dst,void **p){
    if(!*p)return 0;
    void *pointer=*p;int rc=io->release(dst,pointer);
    pthread_mutex_lock(&mutex);
    if(rc){state.faults++;state.clean_completion=0;if(!state.retained_cleanup)state.retained_cleanup=pointer;}else forget(pointer);
    pthread_mutex_unlock(&mutex);
    char line[200];snprintf(line,sizeof line,"pid=%d tid=%ld owner=%#x pointer=%p rc=%d",getpid(),syscall(SYS_gettid),dst,pointer,rc);
    event(io,rc?"CLEANUP_FAULT ":"INTERNAL_FREE ",line);*p=0;return rc;
}
static int make(const struct full_imaging_io *io,unsigned int dst,unsigned int n,void **out){
    *out=0;int rc=io->allocate(dst,out,n,1);
    pthread_mutex_lock(&mutex);unsigned int slot=3;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<3;i++){if(messages[i] && messages[i]==*out)alias=1;if(!messages[i] && slot==3)slot=i;}
    if(alias || (*out && slot==3)){pthread_mutex_unlock(&mutex);*out=0;fault(io,"allocator-returned-live-message-or-capacity");return -1;}
    if(*out)messages[slot]=*out;
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,dst,out);return -1;}
    memset(*out,0,n);return healthy()?0:-1;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int src){io->set_source(p,src);return io->source(p)==src && healthy()?0:-1;}
static int cold(const struct full_vef_pin *p,const unsigned int *self){
    static const unsigned int peer[4]={0xff,0xff,0,0};
    return p->state==1 && !memcmp(p->self,self,sizeof p->self) && !memcmp(p->peer,peer,sizeof peer);
}
static int quiet(const struct full_vef_snapshot *p,unsigned int sid,unsigned int count){
    return p->initialized && p->owner_sid==sid && p->registry_objects==count && p->queries>=1 && p->native_freed>=1 &&
        p->waiter_freed>=1 && !p->pending && !p->faults && !p->live_replies && !p->retained_request && !p->retained_reply;
}
static int native_ready(struct full_vef_snapshot *a,struct full_vef_snapshot *b){
    if(!EDGE_NATIVE_PREREQUISITES())return 0;
    full_pinmem_snapshot(a);PEER_SNAPSHOT(b);
    unsigned int peer_count=SOURCE_TYPE==6?2u:10u;
    return quiet(a,FULL_PINMEM_CP,13) && quiet(b,PEER_CP,peer_count) &&
        pin_registry_key_get_retired(full_pinmem_registry(),S) && pin_registry_key_get_retired(PEER_REGISTRY(),P) &&
        b->registry_objects>PEER_SLOT && cold(&a->pins[SOURCE_SLOT],S) && cold(&b->pins[PEER_SLOT],P);
}
static int readback(const struct full_vef_snapshot *before_source,const struct full_vef_snapshot *before_peer,unsigned int pending,int native){
    struct full_vef_snapshot a,b;full_pinmem_snapshot(&a);PEER_SNAPSHOT(&b);
    const struct full_vef_pin *s=&a.pins[SOURCE_SLOT],*p=&b.pins[PEER_SLOT];
    if(a.faults || b.faults || a.pending!=pending || b.pending || s->state || p->state || memcmp(s->self,S,sizeof S) ||
       memcmp(s->peer,P,sizeof P) || memcmp(p->self,P,sizeof P) || memcmp(p->peer,S,sizeof S))return -1;
    pthread_mutex_lock(&mutex);state.source_state=s->state;state.peer_state=p->state;pthread_mutex_unlock(&mutex);
    if(native){a.pins[SOURCE_SLOT]=before_source->pins[SOURCE_SLOT];a.pending=before_source->pending;b.pins[PEER_SLOT]=before_peer->pins[PEER_SLOT];
        if(memcmp(&a,before_source,sizeof a) || memcmp(&b,before_peer,sizeof b) || !EDGE_NATIVE_PREREQUISITES())return -1;}
    return healthy()?0:-1;
}
static int enqueue_event6(const struct full_imaging_io *io,void *answer,const unsigned char expected[72]){
    if(!canonical(io,answer,expected,72,PEER_CP))return -1;
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.busy || state.event6_enqueued || state.pending_event6!=1 || state.phase!=1 || state.wait_primary!=6){pthread_mutex_unlock(&mutex);return -1;}
    memset(&event6,0,sizeof event6);event6.answer=answer;event6.body=(unsigned char *)answer+24;
    event6.source=PEER_CP;event6.destination=FULL_PINMEM_CP;event6.token=EVENT_TOKEN;put32(event6.parameter,EVENT_TOKEN);
    memcpy(event6.request,saved_request,64);memcpy(event6.answer_wire,expected,72);
    state.context_kind=2;state.event6_enqueued=1;state.event6_token=EVENT_TOKEN;pthread_mutex_unlock(&mutex);
    char line[600];snprintf(line,sizeof line,"producer_raw=0x5d74ba event=6 parameter_bytes=12 cleared_bytes=12 token=%#x raw=%02x%02x%02x%02x0000000000000000 token_policy=owned-answer-plus24-map saved_original_request_bytes=64 queue_phase=1 wait_primary=6 wait_secondary=0 keep_pending=1 context_kind=2 original_CP_event_pointer_identity_verified=0 original_RTOS_scheduling_verified=0 capture_verified=0",
        EVENT_TOKEN,(unsigned char)EVENT_TOKEN,(unsigned char)(EVENT_TOKEN>>8),(unsigned char)(EVENT_TOKEN>>16),(unsigned char)(EVENT_TOKEN>>24));event(io,"EVENT6_ENQUEUED ",line);return 0;
}
static int consume_event6(const struct full_imaging_io *io){
    struct local_event6 e;void *request;unsigned int dst;
    pthread_mutex_lock(&mutex);
    if(!state.busy || state.faults || state.pending_event6!=1 || state.event6_enqueued!=1 || state.event6_inflight || state.event6_consumed ||
       state.context_kind!=2 || state.phase!=1 || state.wait_primary!=6 || state.wait_secondary || state.keep_pending!=1){
        pthread_mutex_unlock(&mutex);fault(io,"event6-missing-duplicate-context-phase-or-wait");return -1;}
    state.event6_inflight=1;e=event6;request=current_request;dst=state.reply_destination;pthread_mutex_unlock(&mutex);
    unsigned char parameter[12]={0};put32(parameter,EVENT_TOKEN);
    int valid=e.token==EVENT_TOKEN && !memcmp(e.parameter,parameter,12) && e.answer && e.body==(unsigned char *)e.answer+24 &&
        e.source==PEER_CP && e.destination==FULL_PINMEM_CP && !memcmp(e.request,saved_request,64) &&
        canonical(io,request,e.request,64,dst) && u32(e.request)==dst && valid_pair(e.request) &&
        canonical(io,e.answer,e.answer_wire,72,PEER_CP) && valid_pair(e.answer_wire) &&
        !memcmp(e.request+48,(unsigned char *)e.body+24,4*sizeof(unsigned int)) &&
        !u32((unsigned char *)e.body+40) && !u32((unsigned char *)e.body+44);
    pthread_mutex_lock(&mutex);valid=valid && !state.faults && !memcmp(&event6,&e,sizeof e) && state.context_kind==2 &&
        state.phase==1 && state.wait_primary==6 && !state.wait_secondary && state.keep_pending==1;pthread_mutex_unlock(&mutex);
    if(valid)valid=pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,3)==0;
    pthread_mutex_lock(&mutex);state.event6_inflight=0;
    if(valid){state.event6_consumed=1;state.pending_event6=0;state.event6_token_verified=1;state.event6_peer_verified=1;
        state.context_kind=0;state.wait_primary=state.wait_secondary=state.keep_pending=0;event6.answer=event6.body=0;}
    pthread_mutex_unlock(&mutex);
    if(!valid){fault(io,"event6-owned-12B-parameter-saved-request-peer-source-status-or-tail-mismatch");return -1;}
    char line[850];snprintf(line,sizeof line,"consumer_raw=0x5dd814 work_raw=0xf882c context_getters_raw=0x5db244,0x5db25a,0x5db24a,0x5db39a parameter_bytes=12 parameter_fnv=%016llx token=%#x actual_parameter_read=1 token_body_binding_verified=1 saved_dynamic_destination=%#x saved_request_fnv=%016llx reply_peer=%u,%u,%u,%#x full_peer_u32_verified=4 source_complete_raw=0x5839a6 status=0 tail=0 consumed=1 pending=0 original_CP_event_pointer_identity_verified=0 original_RTOS_scheduling_verified=0 capture_verified=0",hash(e.parameter,12),EVENT_TOKEN,dst,hash(e.request,64),u32((unsigned char *)e.body+24),u32((unsigned char *)e.body+28),u32((unsigned char *)e.body+32),u32((unsigned char *)e.body+36));
    event(io,"EVENT6_CONSUMED ",line);return healthy()?0:-1;
}
#if SOURCE_TYPE == 6
static int drawinfo_manager(const unsigned int *source,const unsigned int *peer){
    if(memcmp(source,S,sizeof S) || memcmp(peer,P,sizeof P))return -1021;
    return 0; /* Source-closed DrawInfoRawManager +c: movs r0,0; bx lr. */
}
#endif
static int source_posthook(const struct full_imaging_io *io){
    struct full_vef_snapshot source;full_pinmem_snapshot(&source);
    if(memcmp(source.pins[SOURCE_SLOT].self,S,sizeof S) || source.pins[SOURCE_SLOT].state)return -1;
    pthread_mutex_lock(&mutex);state.post_callback_type=SOURCE_TYPE;pthread_mutex_unlock(&mutex);
#if SOURCE_TYPE == 0
    /* 5d6bc2 selects the first source group's attributes; dir2 returns at 5d6bf6. */
    if(S[0]!=0 || S[1]!=2)return -1;
    pthread_mutex_lock(&mutex);state.yc_callback_seen=1;pthread_mutex_unlock(&mutex);
    char text[240];snprintf(text,sizeof text,"command=0x8100 selected_group=source type=0 dir=2 index=%u callback_raw=0x5d6bc2 return_raw=0x5d6bf6 format_published=0 buffer_allocated=0 capture_verified=0",SOURCE_INDEX);
    event(io,"YC_DIRECTION_CHECK ",text);
#else
    int (*method)(const unsigned int *,const unsigned int *)=drawinfo_manager;int rc=method(S,P);
    pthread_mutex_lock(&mutex);state.manager_calls++;state.manager_return=(unsigned int)rc;pthread_mutex_unlock(&mutex);
    event(io,"DRAWINFO_MANAGER ","selected_group=source type=6 dir=2 manager=DrawInfoRawManager method_offset=0xc typed_callback_called=1 rc=0 YC_called=0 DMM=0 notifications=0 markers=0 MMIO=0 capture_verified=0");
    if(rc)return -1;
#endif
    return healthy()?0:-1;
}
int EDGE_OWNER_INIT(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&process_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);if(!state.initialized){state.initialized=1;state.owner_pid=pid;}pthread_mutex_unlock(&mutex);return 0;
}
void EDGE_SNAPSHOT(struct scalar_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct scalar_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<3;i++)out->retained_messages+=messages[i]!=0;
    memcpy(out->saved_request,saved_request,64);out->saved_request_fnv=hash(saved_request,64);
    memcpy(out->event6_parameter,event6.parameter,12);out->event6_parameter_fnv=hash(event6.parameter,12);
    out->event6_answer=event6.answer;out->event6_body=event6.body;pthread_mutex_unlock(&mutex);
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){
    pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);event(io,"UNADMITTED ",reason);*result=-1021;return 1;
}
static int dispatch(unsigned int dst,void *request,const struct full_imaging_io *io,const struct full_adf_proc_guard *guard,int enabled,int native,int *result){
    if(enabled!=1 || dst!=FULL_PINMEM_CP || !io || !result)return 0;
    if((native && !pid_matches()) || (!native && EDGE_OWNER_INIT()!=0)){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->set_source || !io->send ||
       (native && (!guard || !guard->reserve || !guard->release))){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    if((native || EDGE_PASS_OTHER) && !valid_pair(request))return 0;
    unsigned int d=u32(request);unsigned char expected_request[64]={0};envelope(expected_request,64,1,2);pair(expected_request);put32(expected_request,d);
    memcpy(expected_request+20,(unsigned char *)request+20,4);
    if(d>>28!=8 || !(d&0xfffffff) || !canonical(io,request,expected_request,64,d)){
        event(io,"UNSUPPORTED ",EDGE_DESCRIPTION);*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);int ready=state.initialized && !state.started && !state.faults && !state.busy && !state.live_reply;
    pthread_mutex_unlock(&mutex);
    if(!ready){if(native)return unadmitted(io,result,"owner-not-cold-or-transaction-already-started");*result=-1021;return 1;}
    struct full_vef_snapshot before_source={0},before_peer={0};
    if(native){
        if(!native_ready(&before_source,&before_peer))return unadmitted(io,result,"predecessor-or-new-cold-Get-free-not-ready requests=0 faults_unchanged=1");
        if(guard->reserve())return unadmitted(io,result,"resource-guard-busy requests=0 faults_unchanged=1");
        pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
        if(!native_ready(&before_source,&before_peer)){
            guard->release();pthread_mutex_lock(&mutex);state.guard_held=0;pthread_mutex_unlock(&mutex);
            return unadmitted(io,result,"guarded-prerequisite-readback-failed requests=0 faults_unchanged=1");}
    }
    pthread_mutex_lock(&mutex);
    if(state.started || state.faults || state.busy || state.live_reply){
        pthread_mutex_unlock(&mutex);if(native){guard->release();pthread_mutex_lock(&mutex);state.guard_held=0;pthread_mutex_unlock(&mutex);}
        *result=-1021;return 1;}
    state.started=state.requests=state.busy=1;state.native_guarded=(unsigned int)native;state.guard_held=(unsigned int)native;
    state.reply_destination=d;sender=syscall(SYS_gettid);current_request=request;memcpy(saved_request,request,64);pthread_mutex_unlock(&mutex);
    void *forward=0,*answer=0,*final=0;int queued=0;unsigned char expected[72]={0};
    wire(io,"REQUEST ",d,FULL_PINMEM_CP,request,64);
    if(!healthy() || make(io,d,64,&forward))goto failed;
    envelope(expected,64,0x100,1);pair(expected);memcpy(forward,expected,64);
    if(set_source(io,forward,FULL_PINMEM_CP) || !canonical(io,request,saved_request,64,d) || !healthy() ||
       pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,1))goto failed;
    pthread_mutex_lock(&mutex);state.context_kind=1;state.phase=1;state.wait_primary=6;state.keep_pending=1;state.pending_event6=1;pthread_mutex_unlock(&mutex);
    wire(io,"PEER_REQUEST ",FULL_PINMEM_CP,PEER_CP,forward,64);
    if(!canonical(io,forward,expected,64,FULL_PINMEM_CP) || !healthy() || pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,2))goto failed;
    if(make(io,d,72,&answer))goto failed;
    memset(expected,0,sizeof expected);envelope(expected,72,0x8100,1);pair(expected);memcpy(answer,expected,72);
    if(set_source(io,answer,PEER_CP))goto failed;
    wire(io,"PEER_REPLY ",PEER_CP,FULL_PINMEM_CP,answer,72);
    if(enqueue_event6(io,answer,expected) || consume_event6(io) || source_posthook(io) ||
       drop(io,d,&forward) || drop(io,d,&answer) || readback(&before_source,&before_peer,1,native))goto failed;
    if(make(io,d,56,&final))goto failed;
    memset(expected,0,sizeof expected);envelope(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32(expected+32+4*i,S[i]);memcpy(final,expected,56);
    if(set_source(io,final,FULL_PINMEM_CP) || !canonical(io,final,expected,56,FULL_PINMEM_CP) || !canonical(io,request,saved_request,64,d) ||
       readback(&before_source,&before_peer,1,native))goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire);
    pthread_mutex_lock(&mutex);
    if(state.faults || state.live_reply || state.releasing_reply || current_request!=request){pthread_mutex_unlock(&mutex);goto failed;}
    state.live_reply=final;pthread_mutex_unlock(&mutex);
    int sent=io->send(d,final);
    if(sent){
        char line[560];pthread_mutex_lock(&mutex);
        /* A callback may already have freed the buffer, or hold its free in
         * another thread. That lease, rather than this stack, owns cleanup. */
        int lease_fault=state.live_reply!=final || state.releasing_reply;
        if(lease_fault){
            state.faults++;state.clean_completion=0;
            snprintf(line,sizeof line,"reason=send-failed-after-release pid=%d owner_pid=%d tid=%ld sender=%ld destination=%#x expected=%#x reply=%p live=%p inflight=%u event6_inflight=%u phase=%u busy=%u queued=%u send_rc=%d faults=%u capture_verified=0",getpid(),state.owner_pid,syscall(SYS_gettid),sender,d,state.reply_destination,final,state.live_reply,state.releasing_reply,state.event6_inflight,state.phase,state.busy,state.queued,sent,state.faults);
            final=0;
        }else state.live_reply=0;
        pthread_mutex_unlock(&mutex);
        if(lease_fault)event(io,"SEND_RELEASE_FAULT ",line);
        goto failed;
    }
    queued=1;pthread_mutex_lock(&mutex);state.queued=1;forget(final);pthread_mutex_unlock(&mutex);
    wire_from(io,"REPLY_QUEUED ",FULL_PINMEM_CP,d,final,final_wire,sizeof final_wire);final=0;
    int freed=io->release(FULL_PINMEM_CP,request);
    pthread_mutex_lock(&mutex);state.request_freed=freed==0;
    if(freed){state.faults++;state.clean_completion=0;state.retained_request=request;}current_request=0;pthread_mutex_unlock(&mutex);
    char line[520];snprintf(line,sizeof line,"pid=%d tid=%ld owner=%#x pointer=%p bytes=64 rc=%d",getpid(),syscall(SYS_gettid),FULL_PINMEM_CP,request,freed);event(io,freed?"REQUEST_FREE_FAULT ":"REQUEST_FREE ",line);
    if(pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,4))goto failed;
    /* Publication cannot be undone; keep the completed pin state even if a
     * logger/free fault made the completion permanently unclean. */
    struct full_vef_snapshot after_source,after_peer;full_pinmem_snapshot(&after_source);PEER_SNAPSHOT(&after_peer);
    if(after_source.pending || after_peer.pending || after_source.pins[SOURCE_SLOT].state || after_peer.pins[PEER_SLOT].state)goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    snprintf(line,sizeof line,"source_type=%u source_slot=%u peer_slot=%u source_state=0 peer_state=0 source_pending=0 event6_consumed=1 parameter_bytes=12 yc_format_published=0 AP_reply_after_source_callback=1 original_CP_event_pointer_identity_verified=0 original_RTOS_scheduling_verified=0 pixels_consumed=0 capture_verified=0",SOURCE_TYPE,SOURCE_SLOT,PEER_SLOT);
    event(io,"STATE_READBACK ",line);goto done;
failed:
    fault(io,"transaction-incomplete-owned-state-preserved");
    if(forward)drop(io,d,&forward);
    if(answer){pthread_mutex_lock(&mutex);int borrowed=state.event6_enqueued && (state.pending_event6 || state.event6_inflight);
        if(borrowed && !state.retained_cleanup)state.retained_cleanup=answer;
        pthread_mutex_unlock(&mutex);if(!borrowed)drop(io,d,&answer);}
    if(final)drop(io,d,&final);
    pthread_mutex_lock(&mutex);current_request=0;pthread_mutex_unlock(&mutex);
done:
    if(native)guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
    *result=queued?0:-1021;return 1;
}
int EDGE_DISPATCH(unsigned int dst,void *request,const struct full_imaging_io *io,int enabled,int *result){return dispatch(dst,request,io,0,enabled,0,result);}
int EDGE_NATIVE_DISPATCH(unsigned int dst,void *request,const struct full_imaging_io *io,const struct full_adf_proc_guard *guard,int enabled,int *result){return dispatch(dst,request,io,guard,enabled,1,result);}
int EDGE_RELEASE(unsigned int d,void *message,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *result){
    if(!message || !release || !result || !pid_matches())return 0;
    pthread_mutex_lock(&mutex);
    if(message!=state.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int dst=state.reply_destination;long waiter=sender;
    if(d!=dst || state.releasing_reply){
        char line[560];state.faults++;state.clean_completion=0;
        snprintf(line,sizeof line,"reason=%s pid=%d owner_pid=%d tid=%ld sender=%ld destination=%#x expected=%#x reply=%p live=%p inflight=%u event6_inflight=%u phase=%u busy=%u queued=%u faults=%u rc=-1021 capture_verified=0",d!=dst?"wrong-destination":"release-inflight",getpid(),state.owner_pid,syscall(SYS_gettid),waiter,d,dst,message,state.live_reply,state.releasing_reply,state.event6_inflight,state.phase,state.busy,state.queued,state.faults);
        pthread_mutex_unlock(&mutex);
        if(record)record("FULL_" EDGE_TAG "_CONNECT_RELEASE_REJECT_FAULT ",line);
        *result=-1021;return 1;
    }
    state.releasing_reply=1;pthread_mutex_unlock(&mutex);
    int rc=release(d,message);long tid=syscall(SYS_gettid);
    pthread_mutex_lock(&mutex);state.releasing_reply=0;
    if(rc){state.faults++;state.clean_completion=0;}else{state.live_reply=0;state.native_reply_frees++;state.waiter_frees+=(tid==waiter);
        state.reply_freed=1;state.ap_consumed=(tid==waiter);forget(message);}
    unsigned int faults=state.faults,consumed=state.ap_consumed;pthread_mutex_unlock(&mutex);
    if(record){char line[380];snprintf(line,sizeof line,"pid=%d tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p bytes=56 command=0x8001 rc=%d faults=%u ap_consumed=%u capture_verified=0",getpid(),tid,waiter,(unsigned int)(tid==waiter),d,dst,message,rc,faults,consumed);
        record(rc?"FULL_" EDGE_TAG "_CONNECT_FAULT ":"FULL_" EDGE_TAG "_CONNECT_NATIVE_REPLY_FREE ",line);}
    *result=rc;return 1;
}
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void EDGE_TEST_EVENT_CORRUPT(unsigned int kind){
    if(!pid_matches())return;
    pthread_mutex_lock(&mutex);
    if(state.pending_event6 && state.event6_enqueued){
        if(kind==1)event6.parameter[0]^=1;
        if(kind==2)event6.body=(unsigned char *)event6.body+1;
        if(kind==3)event6.request[48]^=1;
        if(kind==4)event6.parameter[11]=1;
        if(kind==5)event6.request[20]^=1;
        if(kind==6)state.phase=0;
        if(kind==7)state.wait_primary=5;
        if(kind==8)state.context_kind=1;
    }
    pthread_mutex_unlock(&mutex);
}
int EDGE_TEST_EVENT_CONSUME(const struct full_imaging_io *io){
    if(!pid_matches() || !io || !io->size || !io->source)return -1021;
    return consume_event6(io);
}
#endif
#ifdef FULL_PIN_CONNECTION_TEST
void EDGE_RESET(void){
    /* Test fixtures dispose retained buffers themselves before resetting. */
    if(atomic_load(&process_pid) && !pid_matches())return;
    pthread_mutex_lock(&mutex);state=(struct scalar_connection_snapshot){0};memset(messages,0,sizeof messages);memset(saved_request,0,sizeof saved_request);
    memset(&event6,0,sizeof event6);current_request=0;sender=0;atomic_store(&process_pid,(int)getpid());pthread_mutex_unlock(&mutex);
}
#endif
