/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pinmem-hdmi-video-connection.h"
#include "pinmem-drawinfo-connection.h"
#include "pinmem-device.h"
#include "hdmi-pin-device.h"
#include "hdmi-video-state.h"
#include "pin-registry-core.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define TAG "FULL_PINMEM_HDMI_VIDEO_CONNECT_"
#define EVENT_TOKEN 0x504d4000u
static const unsigned int S[4]={4,2,0,FULL_PINMEM_CP},P[4]={4,1,0,FULL_HDMI_PIN_CP};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static struct full_pinmem_hdmi_video_connection_snapshot state;
static struct full_imaging_io transport;
static struct full_adf_proc_guard reservation;
static struct full_vef_snapshot before_source,before_peer;
static void *owned[3],*original_request;
static int admitting,reply_sending,reply_send_done,progress_requested;
static struct local_event6 {
    unsigned char parameter[12],request[64],answer_wire[72];
    void *answer,*body;
    unsigned int token,source,destination;
} event6;

static int process(void){return atomic_load(&process_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned long long hash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;
    for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;
    return h;
}
static void note(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[96];snprintf(tag,sizeof tag,TAG "%s",kind);io->record(tag,text);}
}
static void fault_locked(void){state.connection.faults++;state.connection.clean_completion=0;}
static void fault(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);fault_locked();pthread_mutex_unlock(&mutex);note(io,"FAULT ",reason);
}
static int healthy(void){
    pthread_mutex_lock(&mutex);int ok=!state.connection.faults && state.source_gate_known &&
        !state.source_gate && state.source_history_known;pthread_mutex_unlock(&mutex);return ok;
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,
                 void *pointer,const unsigned char *bytes,unsigned int n){
    char raw[145],line[650];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",bytes[i]);
    raw[2*n]=0;
    snprintf(line,sizeof line,"pid=%d producer_tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s original_CP_executed=0 original_RTOS_scheduling_verified=0 frames_verified=0 capture_verified=0",
             getpid(),syscall(SYS_gettid),src,dst,pointer,n,raw);note(io,kind,line);
}
static void envelope(unsigned char *p,unsigned int n,unsigned int command,unsigned int flags){
    memset(p,0,n);put32(p+4,0xa0a0a0a0u);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,command);put16(p+28,n-24);put16(p+30,flags);
}
static void pair(unsigned char *p){for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}}
static int valid_pair(const unsigned char *p){
    for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;
    return 1;
}
static int canonical(const struct full_imaging_io *io,void *p,const unsigned char *expected,unsigned int n,unsigned int src){
    return p && io->size(p)==n && io->source(p)==src && !memcmp(p,expected,n) && healthy();
}
static void forget_locked(void *p){for(unsigned int i=0;i<3;i++)if(owned[i]==p)owned[i]=NULL;}
static int drop(const struct full_imaging_io *io,unsigned int owner,unsigned int slot){
    pthread_mutex_lock(&mutex);void *p=owned[slot];int retained=p && state.connection.retained_cleanup==p;
    pthread_mutex_unlock(&mutex);
    if(!p)return 0;
    if(retained)return -1021;
    int rc=io->release(owner,p);
    pthread_mutex_lock(&mutex);
    if(rc){fault_locked();if(!state.connection.retained_cleanup)state.connection.retained_cleanup=p;}
    else forget_locked(p);
    pthread_mutex_unlock(&mutex);
    char line[220];snprintf(line,sizeof line,"owner=%#x pointer=%p rc=%d",owner,p,rc);
    note(io,rc?"CLEANUP_FAULT ":"INTERNAL_FREE ",line);return rc;
}
static int make(const struct full_imaging_io *io,unsigned int owner,unsigned int n,unsigned int slot,void **out){
    *out=NULL;int rc=io->allocate(owner,out,n,1);
    pthread_mutex_lock(&mutex);int alias=*out && (*out==original_request || *out==state.connection.live_reply);
    for(unsigned int i=0;i<3;i++)if(*out && owned[i]==*out)alias=1;
    if(alias || owned[slot]){pthread_mutex_unlock(&mutex);*out=NULL;fault(io,"allocator-returned-live-message");return -1021;}
    owned[slot]=*out;pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n || !healthy()){
        if(*out)drop(io,owner,slot);
        *out=NULL;return -1021;
    }
    memset(*out,0,n);return 0;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int src){
    io->set_source(p,src);return io->source(p)==src && healthy()?0:-1021;
}
static int predecessor(void){
    struct scalar_connection_snapshot p;full_pinmem_drawinfo_connection_snapshot(&p);
    return p.owner_pid==getpid() && p.initialized && p.native_guarded && p.clean_completion &&
        p.ap_consumed==1 && p.connections==1 && p.requests==1 && p.queued==1 && p.request_freed==1 &&
        p.reply_freed==1 && p.native_reply_frees==1 && p.waiter_frees==1 && p.event6_consumed==1 &&
        !p.pending_event6 && !p.event6_inflight && !p.faults && !p.busy && !p.guard_held &&
        !p.retained_cleanup && !p.retained_messages && !p.releasing_reply && !p.live_reply && !p.retained_request;
}
static int cold(const struct full_vef_pin *p,const unsigned int key[4]){
    static const unsigned int empty[4]={0xff,0xff,0,0};
    return p->state==1 && !memcmp(p->self,key,16) && !memcmp(p->peer,empty,16);
}
static int quiet(const struct full_vef_snapshot *p,unsigned int sid,unsigned int count){
    return p->initialized && p->owner_sid==sid && p->registry_objects==count && p->queries &&
        p->queued==p->queries && p->request_freed==p->queries && p->native_freed==p->queries &&
        p->waiter_freed==p->queries && !p->pending && !p->faults && !p->live_replies &&
        !p->retained_request && !p->retained_reply;
}
static int native_ready(struct full_vef_snapshot *source,struct full_vef_snapshot *peer){
    if(!healthy() || !predecessor())return 0;
    full_pinmem_snapshot(source);full_hdmi_pin_snapshot(peer);
    return quiet(source,FULL_PINMEM_CP,13) && quiet(peer,FULL_HDMI_PIN_CP,2) &&
        pin_registry_key_get_retired(full_pinmem_registry(),S) &&
        pin_registry_key_get_retired(full_hdmi_pin_registry(),P) &&
        cold(&source->pins[7],S) && cold(&peer->pins[0],P);
}
/* Compare every other physical port and the owners' complete lease history;
 * shared HDMI audio state, if already connected, is preserved as received. */
static int readback(unsigned int source_state,unsigned int pending){
    struct full_vef_snapshot a,b;full_pinmem_snapshot(&a);full_hdmi_pin_snapshot(&b);
    if(a.pins[7].state!=source_state || b.pins[0].state || a.pending!=pending || b.pending ||
       memcmp(a.pins[7].self,S,16) || memcmp(a.pins[7].peer,P,16) ||
       memcmp(b.pins[0].self,P,16) || memcmp(b.pins[0].peer,S,16))return -1021;
    pthread_mutex_lock(&mutex);state.connection.source_state=a.pins[7].state;state.connection.peer_state=b.pins[0].state;
    pthread_mutex_unlock(&mutex);
    a.pins[7]=before_source.pins[7];a.pending=before_source.pending;b.pins[0]=before_peer.pins[0];
    return memcmp(&a,&before_source,sizeof a) || memcmp(&b,&before_peer,sizeof b) || !predecessor() || !healthy()?-1021:0;
}
static int prepare(const struct full_imaging_io *io,unsigned int d){
    void *forward=NULL,*answer=NULL;unsigned char expected[72];
    if(!canonical(io,original_request,state.connection.saved_request,64,d) || make(io,d,64,0,&forward))return -1021;
    envelope(expected,64,0x100,1);pair(expected);memcpy(forward,expected,64);
    if(set_source(io,forward,FULL_PINMEM_CP) || !canonical(io,forward,expected,64,FULL_PINMEM_CP) ||
       pin_registry_connect_step(full_pinmem_registry(),full_hdmi_pin_registry(),S,P,1))return -1021;
    pthread_mutex_lock(&mutex);state.connection.source_state=2;state.connection.peer_state=1;
    state.connection.context_kind=1;state.connection.phase=1;
    state.connection.wait_primary=6;state.connection.keep_pending=1;state.connection.pending_event6=1;
    pthread_mutex_unlock(&mutex);
    wire(io,"PEER_REQUEST ",FULL_PINMEM_CP,FULL_HDMI_PIN_CP,forward,expected,64);
    if(!canonical(io,forward,expected,64,FULL_PINMEM_CP) ||
       pin_registry_connect_step(full_pinmem_registry(),full_hdmi_pin_registry(),S,P,2))return -1021;
    pthread_mutex_lock(&mutex);state.connection.peer_state=0;pthread_mutex_unlock(&mutex);
    if(make(io,d,72,1,&answer))return -1021;
    envelope(expected,72,0x8100,1);pair(expected);memcpy(answer,expected,72);
    if(set_source(io,answer,FULL_HDMI_PIN_CP) || !canonical(io,answer,expected,72,FULL_HDMI_PIN_CP) || readback(2,1))return -1021;
    pthread_mutex_lock(&mutex);
    memset(&event6,0,sizeof event6);event6.answer=answer;event6.body=(unsigned char *)answer+24;
    event6.source=FULL_HDMI_PIN_CP;event6.destination=FULL_PINMEM_CP;event6.token=EVENT_TOKEN;
    put32(event6.parameter,EVENT_TOKEN);memcpy(event6.request,state.connection.saved_request,64);memcpy(event6.answer_wire,expected,72);
    state.connection.context_kind=2;state.connection.event6_enqueued=1;state.connection.event6_token=EVENT_TOKEN;
    state.peer_waiting=1;pthread_mutex_unlock(&mutex);
    note(io,"EVENT6_ENQUEUED ","event=6 parameter_bytes=12 token_policy=owned-answer-plus24-map phase=1 wait_primary=6 keep_pending=1 peer_posthandler_pending=1 original_CP_event_pointer_identity_verified=0 capture_verified=0");
    return drop(io,d,0);
}
static int consume_event6(const struct full_imaging_io *io,unsigned int d){
    pthread_mutex_lock(&mutex);
    int valid=state.connection.pending_event6==1 && state.connection.event6_enqueued==1 &&
        !state.connection.event6_inflight && !state.connection.event6_consumed && state.connection.context_kind==2 &&
        state.connection.phase==1 && state.connection.wait_primary==6 && !state.connection.wait_secondary && state.connection.keep_pending==1;
    struct local_event6 e=event6;
    if(valid)state.connection.event6_inflight=1;
    pthread_mutex_unlock(&mutex);
    unsigned char expected[12]={0};put32(expected,EVENT_TOKEN);
    valid=valid && e.token==EVENT_TOKEN && !memcmp(e.parameter,expected,12) &&
        e.answer && e.body==(unsigned char *)e.answer+24 && e.source==FULL_HDMI_PIN_CP && e.destination==FULL_PINMEM_CP &&
        !memcmp(e.request,state.connection.saved_request,64) && valid_pair(e.request) && u32(e.request)==d &&
        canonical(io,original_request,e.request,64,d) && canonical(io,e.answer,e.answer_wire,72,FULL_HDMI_PIN_CP) &&
        valid_pair(e.answer_wire) && !memcmp(e.request+48,(unsigned char *)e.body+24,16) &&
        !u32((unsigned char *)e.body+40) && !u32((unsigned char *)e.body+44);
    pthread_mutex_lock(&mutex);valid=valid && !state.connection.faults && !memcmp(&e,&event6,sizeof e);
    pthread_mutex_unlock(&mutex);
    if(valid)valid=pin_registry_connect_step(full_pinmem_registry(),full_hdmi_pin_registry(),S,P,3)==0;
    pthread_mutex_lock(&mutex);state.connection.event6_inflight=0;
    if(valid){state.connection.source_state=0;state.connection.event6_consumed=1;state.connection.pending_event6=0;state.connection.event6_token_verified=1;
        state.connection.event6_peer_verified=1;state.connection.context_kind=0;
        state.connection.wait_primary=state.connection.wait_secondary=state.connection.keep_pending=0;event6.answer=event6.body=NULL;}
    pthread_mutex_unlock(&mutex);
    if(!valid)return -1021;
    char line[430];snprintf(line,sizeof line,"consumer_raw=0x5dd814 source_complete_raw=0x5839a6 parameter_bytes=12 parameter_fnv=%016llx saved_request_fnv=%016llx token=%#x actual_parameter_read=1 full_peer_u32_verified=4 status=0 tail=0 consumed=1 pending=0 capture_verified=0",
        hash(e.parameter,12),hash(e.request,64),EVENT_TOKEN);note(io,"EVENT6_CONSUMED ",line);return healthy()?0:-1021;
}
static int source_posthook(const struct full_imaging_io *io){
    if(!healthy() || readback(0,1))return -1021;
    pthread_mutex_lock(&mutex);state.connection.post_callback_type=4;state.connection.manager_calls++;
    state.connection.manager_return=0;pthread_mutex_unlock(&mutex);
    note(io,"VIDEO_MANAGER ","selector_raw=0xf749c manager_raw=0x5d55c0 object_raw=0x10f5004 vptr_raw=0xd27080 method_offset=0xc gate_load_raw=0x5d55ce gate_offset=0x6a gate_ctor_known=1 gate=0 gate_reset_at_connect=0 typed_callback_called=1 DMM=0 notifications=0 clocks=0 markers=0 capture_verified=0");
    return healthy()?0:-1021;
}
static int publish(const struct full_imaging_io *io,unsigned int d){
    void *final=NULL;unsigned char expected[56];
    if(make(io,d,56,2,&final))return -1021;
    envelope(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32(expected+32+4*i,S[i]);memcpy(final,expected,56);
    if(set_source(io,final,FULL_PINMEM_CP) || !canonical(io,final,expected,56,FULL_PINMEM_CP) ||
       !canonical(io,original_request,state.connection.saved_request,64,d) || readback(0,1))return -1021;
    pthread_mutex_lock(&mutex);
    if(state.connection.faults || state.connection.live_reply || state.connection.releasing_reply){pthread_mutex_unlock(&mutex);return -1021;}
    state.connection.live_reply=final;state.producer_tid=syscall(SYS_gettid);reply_sending=1;
    pthread_mutex_unlock(&mutex);
    /* expected is copied before send: a receiver may free final inline. */
    int rc=io->send(d,final);
    pthread_mutex_lock(&mutex);reply_sending=0;reply_send_done=1;
    int cleanup=0;
    if(rc){fault_locked();cleanup=state.connection.live_reply==final && !state.connection.releasing_reply;
        if(cleanup)state.connection.live_reply=NULL;}
    else{state.connection.queued=1;forget_locked(final);}
    pthread_mutex_unlock(&mutex);
    if(rc){if(cleanup)drop(io,d,2);return -1021;}
    wire(io,"REPLY_QUEUED ",FULL_PINMEM_CP,d,final,expected,56);
    void *request=original_request;
    rc=io->release(FULL_PINMEM_CP,request);
    pthread_mutex_lock(&mutex);state.connection.request_freed=rc==0;
    if(rc)fault_locked();
    else{original_request=NULL;state.connection.retained_request=NULL;state.request_owned=0;}
    pthread_mutex_unlock(&mutex);
    char line[220];snprintf(line,sizeof line,"owner=%#x pointer=%p bytes=64 rc=%d",FULL_PINMEM_CP,request,rc);
    note(io,rc?"REQUEST_FREE_FAULT ":"REQUEST_FREE ",line);
    if(pin_registry_connect_step(full_pinmem_registry(),full_hdmi_pin_registry(),S,P,4) || readback(0,0))return -1021;
    pthread_mutex_lock(&mutex);state.connection.connections=1;
    state.connection.clean_completion=!state.connection.faults && state.connection.request_freed;
    pthread_mutex_unlock(&mutex);
    note(io,"STATE_READBACK ","source_slot=7 peer_slot=0 source_state=0 peer_state=0 source_pending=0 event6_consumed=1 source_gate=0 peer_state_ready=1 AP_reply_after_peer_and_source_callbacks=1 pixels_consumed=0 capture_verified=0");return 0;
}
static int run_progress(const struct full_imaging_io *io,unsigned int d){
    pthread_mutex_lock(&mutex);int prepared=state.connection.event6_enqueued;pthread_mutex_unlock(&mutex);
    if(!healthy() || (!prepared && prepare(io,d)) || readback(2,1))return -1021;
    int rc=full_hdmi_video_state_connect_begin(io);
    if(rc<0)return -1021;
    if(rc || !full_hdmi_video_state_connect_ready())return 1;
    pthread_mutex_lock(&mutex);state.peer_waiting=0;state.peer_ready=1;pthread_mutex_unlock(&mutex);
    wire(io,"PEER_REPLY ",FULL_HDMI_PIN_CP,FULL_PINMEM_CP,event6.answer,event6.answer_wire,72);
    if(consume_event6(io,d) || source_posthook(io) || drop(io,d,1) || readback(0,1))return -1021;
    return publish(io,d);
}
static int finish_slice(const struct full_imaging_io *io,const struct full_adf_proc_guard *guard,unsigned int d,int rc){
    for(;;){
        if(rc<0){
            fault(io,"transaction-incomplete-owned-state-preserved");drop(io,d,0);
            pthread_mutex_lock(&mutex);int borrowed=state.connection.pending_event6 || state.connection.event6_inflight;
            if(borrowed && owned[1] && !state.connection.retained_cleanup)state.connection.retained_cleanup=owned[1];
            int cleanup_final=owned[2] && !state.connection.live_reply && !state.connection.releasing_reply;
            pthread_mutex_unlock(&mutex);
            if(!borrowed)drop(io,d,1);
            if(cleanup_final)drop(io,d,2);
        }
        /* Latch faults before callbacks can release the shared reservation. */
        pthread_mutex_lock(&mutex);if(rc<0 && !state.connection.faults)fault_locked();pthread_mutex_unlock(&mutex);
        guard->release();
        pthread_mutex_lock(&mutex);
        int retry=rc==1 && progress_requested;
        state.connection.guard_held=0;progress_requested=0;
        if(!retry)state.progressing=0;
        if(rc!=1)state.connection.busy=0;
        pthread_mutex_unlock(&mutex);
        if(!retry)return rc;
        if(guard->reserve()){
            pthread_mutex_lock(&mutex);state.progressing=0;pthread_mutex_unlock(&mutex);return 1;
        }
        pthread_mutex_lock(&mutex);state.connection.guard_held=1;pthread_mutex_unlock(&mutex);
        rc=run_progress(io,d);
    }
}
int full_pinmem_hdmi_video_connection_owner_init(void){
    int pid=(int)getpid(),expected=0;atomic_compare_exchange_strong(&process_pid,&expected,pid);
    if(!process())return -1021;
    pthread_mutex_lock(&mutex);
    if(!state.connection.initialized){state.connection.initialized=1;state.connection.owner_pid=pid;
        /* Public raw5d443c/5d4460 clear the whole VideoRawManager +0x68 word. */
        state.source_gate_known=1;state.source_history_known=1;}
    int rc=state.source_history_known && !state.connection.faults?0:-1021;
    pthread_mutex_unlock(&mutex);return rc;
}
int full_pinmem_hdmi_video_connection_observe_input(unsigned int dst,const void *message,unsigned int bytes){
    if(dst!=FULL_PINMEM_CP)return 0;
    if(!process())return -1021;
    const unsigned char *p=message;
    int known=p && (bytes==48 || bytes==64) && u32(p+4)==0xa0a0a0a0u && u16(p+8)==1 &&
        u16(p+10)==bytes && u32(p+12)==24 && u32(p+16)==bytes && u16(p+24)==0x1000 &&
        u16(p+26)==(bytes==48?0u:1u) && u16(p+28)==bytes-24 && u16(p+30)==2;
    pthread_mutex_lock(&mutex);state.source_inputs++;
    if(!known){state.source_history_known=0;state.source_gate_known=0;fault_locked();}
    pthread_mutex_unlock(&mutex);return known?0:-1021;
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){
    pthread_mutex_lock(&mutex);state.connection.unadmitted_count++;pthread_mutex_unlock(&mutex);
    note(io,"UNADMITTED ",reason);*result=-1021;return 1;
}
int full_pinmem_hdmi_video_connection_dispatch(unsigned int dst,void *request,const struct full_imaging_io *io,
                                               const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || dst!=FULL_PINMEM_CP || !io || !result)return 0;
    if(!process()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->set_source || !io->send ||
       !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64 || !valid_pair(request))return 0;
    unsigned int d=u32(request);unsigned char expected[64];envelope(expected,64,1,2);pair(expected);put32(expected,d);
    memcpy(expected+20,(unsigned char *)request+20,4);
    if((d>>28)!=8 || !(d&0x0fffffff) || !canonical(io,request,expected,64,d)){
        *result=-1021;note(io,"UNSUPPORTED ","only-PinMem-VIDEO0-HDMI-VIDEO0-canonical-request");return 1;}
    pthread_mutex_lock(&mutex);
    int ready=state.connection.initialized && !state.connection.started && !state.connection.faults && !admitting;
    if(ready)admitting=1;
    pthread_mutex_unlock(&mutex);
    if(!ready)return unadmitted(io,result,"owner-not-cold-or-transaction-already-started");
    struct full_vef_snapshot a,b;
    if(!native_ready(&a,&b) || guard->reserve()){
        pthread_mutex_lock(&mutex);admitting=0;pthread_mutex_unlock(&mutex);
        return unadmitted(io,result,"predecessor-canonical-Get-or-resource-guard-unavailable");
    }
    pthread_mutex_lock(&mutex);state.connection.guard_held=1;pthread_mutex_unlock(&mutex);
    if(!native_ready(&a,&b)){
        guard->release();pthread_mutex_lock(&mutex);state.connection.guard_held=0;admitting=0;pthread_mutex_unlock(&mutex);
        return unadmitted(io,result,"guarded-prerequisite-readback-failed");
    }
    pthread_mutex_lock(&mutex);
    before_source=a;before_peer=b;transport=*io;reservation=*guard;original_request=request;
    memcpy(state.connection.saved_request,request,64);state.connection.retained_request=request;state.request_owned=1;
    state.connection.started=state.connection.requests=state.connection.busy=state.connection.native_guarded=1;
    state.connection.reply_destination=d;state.sender_tid=syscall(SYS_gettid);state.progressing=1;admitting=0;
    pthread_mutex_unlock(&mutex);
    wire(io,"REQUEST ",d,FULL_PINMEM_CP,request,state.connection.saved_request,64);
    int rc=run_progress(io,d);finish_slice(io,guard,d,rc);
    /* Queue acceptance owns request even if a later internal step faults. */
    *result=0;return 1;
}
int full_pinmem_hdmi_video_connection_progress(void){
    if(!process())return -1021;
    int ready=full_hdmi_video_state_connect_ready();
    pthread_mutex_lock(&mutex);
    if(state.connection.faults){pthread_mutex_unlock(&mutex);return -1021;}
    if(!state.connection.busy || state.connection.queued){pthread_mutex_unlock(&mutex);return 0;}
    if(state.progressing){
        /* Generic reentry cannot spin a pending slice; a real final consume can. */
        progress_requested|=ready!=0;
        pthread_mutex_unlock(&mutex);return 1;
    }
    state.progressing=1;struct full_imaging_io io=transport;struct full_adf_proc_guard guard=reservation;
    unsigned int d=state.connection.reply_destination;pthread_mutex_unlock(&mutex);
    if(guard.reserve()){
        pthread_mutex_lock(&mutex);state.progressing=0;pthread_mutex_unlock(&mutex);return 1;
    }
    pthread_mutex_lock(&mutex);state.connection.guard_held=1;pthread_mutex_unlock(&mutex);
    return finish_slice(&io,&guard,d,run_progress(&io,d));
}
int full_pinmem_hdmi_video_connection_release(unsigned int d,void *message,int (*release)(unsigned int,void *),
                                              void (*record)(const char *,const char *),int *result){
    if(!process() || !message || !release || !result)return 0;
    pthread_mutex_lock(&mutex);
    if(message!=state.connection.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int expected=state.connection.reply_destination;long sender=state.sender_tid,producer=state.producer_tid;
    if(d!=expected || state.connection.releasing_reply || (!reply_sending && !reply_send_done)){
        fault_locked();pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.connection.releasing_reply=1;pthread_mutex_unlock(&mutex);
    int rc=release(d,message);long tid=syscall(SYS_gettid);
    pthread_mutex_lock(&mutex);state.connection.releasing_reply=0;
    if(rc){fault_locked();if(reply_send_done && !state.connection.queued && !state.connection.retained_cleanup)state.connection.retained_cleanup=message;}
    else{state.connection.live_reply=NULL;state.connection.native_reply_frees++;state.connection.waiter_frees+=tid==sender;
        state.connection.reply_freed=1;state.connection.ap_consumed=tid==sender;forget_locked(message);}
    unsigned int faults=state.connection.faults,consumed=state.connection.ap_consumed;pthread_mutex_unlock(&mutex);
    if(record){char line[430];snprintf(line,sizeof line,"pid=%d tid=%ld sender=%ld producer_tid=%ld waiter=%u destination=%#x expected=%#x reply=%p bytes=56 command=0x8001 rc=%d faults=%u ap_consumed=%u capture_verified=0",
        getpid(),tid,sender,producer,(unsigned int)(tid==sender),d,expected,message,rc,faults,consumed);
        record(rc?TAG "FAULT ":TAG "NATIVE_REPLY_FREE ",line);}
    *result=rc;return 1;
}
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out){
    if(!out)return;
    if(!process()){memset(out,0,sizeof *out);return;}
    pthread_mutex_lock(&mutex);*out=state;out->connection.retained_messages=0;
    for(unsigned int i=0;i<3;i++)out->connection.retained_messages+=owned[i]!=NULL;
    out->connection.saved_request_fnv=hash(state.connection.saved_request,64);
    memcpy(out->connection.event6_parameter,event6.parameter,12);out->connection.event6_parameter_fnv=hash(event6.parameter,12);
    out->connection.event6_answer=event6.answer;out->connection.event6_body=event6.body;
    pthread_mutex_unlock(&mutex);
}
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void full_pinmem_hdmi_video_connection_test_event_corrupt(unsigned int kind){
    if(!process())return;
    pthread_mutex_lock(&mutex);
    if(state.connection.event6_enqueued && state.connection.pending_event6){
        if(kind==1)event6.parameter[0]^=1;
        if(kind==2)event6.body=(unsigned char *)event6.body+1;
        if(kind==3)event6.request[48]^=1;
        if(kind==4)event6.parameter[11]=1;
        if(kind==5)event6.request[20]^=1;
        if(kind==6)state.connection.phase=0;
        if(kind==7)state.connection.wait_primary=5;
        if(kind==8)state.connection.context_kind=1;
    }
    pthread_mutex_unlock(&mutex);
}
#endif
