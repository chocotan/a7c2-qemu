/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "imaging-adf-connection.h"
#include "imaging-control-connection.h"
#include "imaging-pin-connection.h"
#include "pin-registry-core.h"
#include "pin-buffer-owner.h"
#include "adf-device.h"
#include "../infrabb-registry.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define SOURCE NATIVE_INFRAIMAGING_CP
#define PEER FULL_ADF_CP
static const unsigned int S[4]={3,2,0,SOURCE},P[4]={3,1,0,PEER};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_imaging_adf_connection_snapshot state;
static void *messages[3],*current_request;
struct predecessors {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot control;
    struct pin_control_snapshot pool;
    struct full_vef_snapshot source,peer,bb;
};
static int pid_matches(void){return atomic_load(&owner_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_IMAGING_ADF_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[145],text[640];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;
    snprintf(text,sizeof text,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s transport_owner=virtual-local-caller original_cp_executed=0 pcm_verified=0 frames_verified=0 capture_verified=0",
             getpid(),syscall(SYS_gettid),src,dst,pointer,n,raw);event(io,kind,text);
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *p,unsigned int n){wire_from(io,kind,src,dst,p,p,n);}
static void frame(unsigned char *p,unsigned int n,unsigned int op,unsigned int flags){
    put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,op);put16(p+28,n-24);put16(p+30,flags);
}
static void pair(unsigned char *p){for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}}
static int is_pair(const unsigned char *p){
    for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;
    return 1;
}
static int envelope(const struct full_imaging_io *io,void *p,unsigned int n,unsigned int op,unsigned int flags){
    const unsigned char *in=p;
    return p && io->size(p)==n && u32(in+4)==0xa0a0a0a0 && u16(in+8)==1 && u16(in+10)==n &&
        u32(in+12)==24 && u32(in+16)==n && u16(in+24)==0x1000 && u16(in+26)==op &&
        u16(in+28)==n-24 && u16(in+30)==flags;
}
static void forget(void *p){for(unsigned int i=0;i<3;i++)if(messages[i]==p){messages[i]=0;break;}}
static int drop(const struct full_imaging_io *io,unsigned int dst,void **p){
    if(!*p)return 0;
    void *pointer=*p;int rc=io->release(dst,pointer);
    pthread_mutex_lock(&mutex);
    if(rc){state.faults++;state.clean_completion=0;if(!state.retained_cleanup)state.retained_cleanup=pointer;}
    else forget(pointer);
    pthread_mutex_unlock(&mutex);
    char text[180];snprintf(text,sizeof text,"pid=%d tid=%ld destination=%#x pointer=%p rc=%d",getpid(),syscall(SYS_gettid),dst,pointer,rc);
    event(io,rc?"CLEANUP_FAULT ":"INTERNAL_FREE ",text);*p=0;return rc;
}
static int make(const struct full_imaging_io *io,unsigned int dst,unsigned int n,void **out){
    *out=0;int rc=io->allocate(dst,out,n,1);
    pthread_mutex_lock(&mutex);unsigned int free_slot=3;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<3;i++){if(messages[i] && messages[i]==*out)alias=1;if(!messages[i] && free_slot==3)free_slot=i;}
    if(alias || (*out && free_slot==3)){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*out=0;event(io,"FAULT ","allocator-returned-live-message-or-capacity");return -1;}
    if(*out)messages[free_slot]=*out;
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,dst,out);return -1;}
    memset(*out,0,n);return 0;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int src){io->set_source(p,src);return io->source(p)==src?0:-1;}
static void predecessor_snapshot(struct predecessors *p){
    memset(p,0,sizeof *p);full_imaging_pin_connection_snapshot(&p->first);full_imaging_control_connection_snapshot(&p->control);
    pin_control_snapshot(&p->pool);native_infraimaging_snapshot(&p->source);full_adf_snapshot(&p->peer);native_infrabb_snapshot(&p->bb);
}
static int cold_pin(const struct full_vef_pin *p,const unsigned int *self){
    static const unsigned int cold_peer[4]={0xff,0xff,0,0};
    return p->state==1 && !memcmp(p->self,self,sizeof p->self) && !memcmp(p->peer,cold_peer,sizeof cold_peer);
}
static int registry_ready(const struct full_vef_snapshot *s,unsigned int sid,unsigned int count){
    return s->initialized && s->registry_objects==count && s->owner_sid==sid && !s->pending && !s->faults && !s->live_replies &&
        !s->retained_request && !s->retained_reply && s->queries && s->queued==s->queries &&
        s->request_freed==s->queries && s->native_freed==s->queries;
}
static int dependencies(struct predecessors *p){
    predecessor_snapshot(p);
    const struct full_imaging_pin_connection_snapshot *f=&p->first;
    const struct full_imaging_control_connection_snapshot *c=&p->control;
    return f->owner_pid==getpid() && f->initialized && f->clean_completion && f->connections==1 && f->ap_consumed==1 &&
        f->format_consumed==1 && f->buffer_freed==1 && f->peer_connected_marker_known==1 && f->peer_connected_marker==1 && f->peer_marker_writes==1 &&
        !f->busy && !f->guard_held && !f->faults && !f->live_reply && !f->retained_request && !f->retained_messages && !f->releasing_reply &&
        c->owner_pid==getpid() && c->initialized && c->clean_completion && c->connections==1 && c->ap_consumed==1 &&
        c->peer_marker_known==1 && c->peer_marker==1 && c->peer_marker_writes==1 && c->posthook_checked && c->posthook_no_format &&
        !c->busy && !c->guard_held && !c->faults && !c->live_reply && !c->retained_request && !c->retained_messages && !c->releasing_reply &&
        p->pool.bound && !p->pool.live && !p->pool.faults && p->pool.allocations>=2 && p->pool.allocations==p->pool.releases &&
        registry_ready(&p->source,SOURCE,6) && p->source.queries>=3 && cold_pin(&p->source.pins[4],S) &&
        registry_ready(&p->peer,PEER,10) && cold_pin(&p->peer.pins[4],P) && registry_ready(&p->bb,NATIVE_INFRABB_CP,21);
}
/* Concurrent Get bookkeeping changes conservatively refuse this finite edge. */
static int preserved(const struct predecessors *before,unsigned int pending){
    struct predecessors after;predecessor_snapshot(&after);
    if(memcmp(&after.first,&before->first,sizeof after.first) || memcmp(&after.control,&before->control,sizeof after.control) ||
       memcmp(&after.pool,&before->pool,sizeof after.pool) || memcmp(&after.bb,&before->bb,sizeof after.bb) ||
       after.source.pins[4].state || after.peer.pins[4].state || after.source.pending!=pending || after.peer.pending ||
       memcmp(after.source.pins[4].self,S,sizeof S) || memcmp(after.source.pins[4].peer,P,sizeof P) ||
       memcmp(after.peer.pins[4].self,P,sizeof P) || memcmp(after.peer.pins[4].peer,S,sizeof S))return -1;
    after.source.pins[4]=before->source.pins[4];after.source.pending=before->source.pending;after.peer.pins[4]=before->peer.pins[4];
    return memcmp(&after.source,&before->source,sizeof after.source) || memcmp(&after.peer,&before->peer,sizeof after.peer)?-1:0;
}
int full_imaging_adf_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);if(!state.initialized){state.owner_pid=pid;state.initialized=1;}pthread_mutex_unlock(&mutex);return 0;
}
void full_imaging_adf_connection_snapshot(struct full_imaging_adf_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_imaging_adf_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<3;i++)out->retained_messages+=messages[i]!=0;
    pthread_mutex_unlock(&mutex);
}
int full_imaging_adf_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                         const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !result || !io)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    const unsigned char *in=request;
    if((u32(in+32)&255u)!=3 && (u32(in+48)&255u)!=3)return 0;
    unsigned int dst=u32(in),src=io->source(request);
    if(!envelope(io,request,64,1,2) || !is_pair(in) || src!=dst || src>>28!=8 || !(src&0xfffffff)){
        event(io,"UNSUPPORTED ","only-90050004-type3-audio0-to-ADF-type3-audio0-owned-edge");*result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.busy=1;state.requests=1;state.reply_destination=dst;current_request=request;pthread_mutex_unlock(&mutex);
    int held=0,queued=0;void *forward=0,*answer=0,*final=0;struct predecessors before;
    if(!dependencies(&before) || guard->reserve())goto failed;
    held=1;pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    if(!dependencies(&before))goto failed;
    wire(io,"REQUEST ",src,destination,request,64);
    if(make(io,dst,64,&forward))goto failed;
    frame(forward,64,0x100,1);pair(forward);
    if(set_source(io,forward,SOURCE) || pin_registry_connect_step(native_infraimaging_registry(),full_adf_registry(),S,P,1))goto failed;
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,64);
    if(!envelope(io,forward,64,0x100,1) || u32(forward) || !is_pair(forward) || io->source(forward)!=SOURCE ||
       pin_registry_connect_step(native_infraimaging_registry(),full_adf_registry(),S,P,2))goto failed;
    pthread_mutex_lock(&mutex);state.peer_requests++;pthread_mutex_unlock(&mutex);
    /* CP 19743a..197476: only type5/dir1/index0 selects the extra operation. */
    unsigned int selected=P[0]==5 && P[1]==1 && P[2]==0;
    pthread_mutex_lock(&mutex);state.callback_guard_checked=1;state.callback_selected=selected;state.no_format_checked=!selected;pthread_mutex_unlock(&mutex);
    if(selected)goto failed;
    event(io,"CALLBACK_SKIPPED ","CP_VA=0x0019743a return_CP_VA=0x00197476 peer_type=3 peer_dir=1 peer_index=0 callback_selected=0 marker_writes=0 DMM_allocations=0 notifications=0 cache_writes=0 PCM_consumed=0 B0_commands=0 AVIO_jobs=0 source7_events=0 capture_verified=0");
    if(make(io,dst,72,&answer))goto failed;
    frame(answer,72,0x8100,1);pair(answer);
    if(set_source(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,72);
    if(!envelope(io,answer,72,0x8100,1) || u32(answer) || !is_pair(answer) || io->source(answer)!=PEER ||
       u32((unsigned char *)answer+64) || u32((unsigned char *)answer+68) ||
       pin_registry_connect_step(native_infraimaging_registry(),full_adf_registry(),S,P,3))goto failed;
    pthread_mutex_lock(&mutex);state.peer_replies++;pthread_mutex_unlock(&mutex);
    if(drop(io,dst,&forward) || drop(io,dst,&answer) || preserved(&before,1))goto failed;
    if(make(io,dst,56,&final))goto failed;
    frame(final,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32((unsigned char *)final+32+4*i,S[i]);
    if(set_source(io,final,SOURCE) || !envelope(io,final,56,0x8001,2) || u32(final) ||
       u32((unsigned char *)final+48) || u32((unsigned char *)final+52) || preserved(&before,1))goto failed;
    for(unsigned int i=0;i<4;i++)if(u32((unsigned char *)final+32+4*i)!=S[i])goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire);
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.busy || current_request!=request || state.retained_request || state.live_reply || state.releasing_reply){pthread_mutex_unlock(&mutex);goto failed;}
    state.predecessor_preserved=1;state.live_reply=final;pthread_mutex_unlock(&mutex);
    if(io->send(dst,final)){
        pthread_mutex_lock(&mutex);
        if(state.live_reply!=final || state.releasing_reply){state.faults++;final=0;}
        else state.live_reply=0;
        pthread_mutex_unlock(&mutex);goto failed;
    }
    queued=1;wire_from(io,"REPLY_QUEUED ",SOURCE,dst,final,final_wire,sizeof final_wire);
    pthread_mutex_lock(&mutex);state.queued=1;forget(final);pthread_mutex_unlock(&mutex);final=0;
    int freed=io->release(SOURCE,request);
    pthread_mutex_lock(&mutex);state.request_freed=freed==0;
    if(freed){state.faults++;state.clean_completion=0;state.retained_request=request;}else state.retained_request=0;
    current_request=0;pthread_mutex_unlock(&mutex);
    if(pin_registry_connect_step(native_infraimaging_registry(),full_adf_registry(),S,P,4) || preserved(&before,0))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_state=0 peer_state=0 source_pending=0 callback_selected=0 no_format_checked=1 predecessor_preserved=1 unique_reply=1 original_cp_executed=0 pcm_verified=0 frames_verified=0 capture_verified=0");
    goto done;
failed:
    fail(io,"transaction-incomplete-owned-state-preserved");
    if(forward)drop(io,dst,&forward);
    if(answer)drop(io,dst,&answer);
    if(final)drop(io,dst,&final);
    pthread_mutex_lock(&mutex);current_request=0;if(!queued)state.retained_request=0;pthread_mutex_unlock(&mutex);
done:
    if(held)guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
    *result=queued?0:-1021;return 1;
}
int full_imaging_adf_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                                        void (*record)(const char *,const char *),int *result){
    if(!reply || !release || !result || !pid_matches())return 0;
    pthread_mutex_lock(&mutex);
    if(reply!=state.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int dst=state.reply_destination;
    if(destination!=dst || state.releasing_reply){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.releasing_reply=1;pthread_mutex_unlock(&mutex);
    int rc=release(destination,reply);
    pthread_mutex_lock(&mutex);state.releasing_reply=0;
    if(rc){state.faults++;state.clean_completion=0;}else{state.live_reply=0;state.reply_freed=1;state.ap_consumed=1;forget(reply);}
    unsigned int faults=state.faults;pthread_mutex_unlock(&mutex);
    if(record){char text[290];snprintf(text,sizeof text,"pid=%d tid=%ld destination=%#x expected=%#x pointer=%p bytes=56 rc=%d faults=%u ap_consumed=%u pcm_verified=0 frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),destination,dst,reply,rc,faults,(unsigned int)(!rc));record("FULL_IMAGING_ADF_CONNECT_REPLY_FREE ",text);}
    *result=rc;return 1;
}
