/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "infrabb-vef-control-connection.h"
#include "infrabb-vef-connection.h"
#include "imaging-pin-connection.h"
#include "imaging-control-connection.h"
#include "imaging-adf-connection.h"
#include "adf-set-input-device.h"
#include "adf-set-output-device.h"
#include "bb-set-mode-device.h"
#include "adf-aip-commands.h"
#include "adf-device.h"
#include "pin-connection.h"
#include "pinmem-device.h"
#include "vef-path-device.h"
#include "pin-registry-core.h"
#include "pin-buffer-owner.h"
#include "../infrabb-registry.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#define SOURCE NATIVE_INFRABB_CP
#define PEER FULL_VEF_CP
static const unsigned int S[4]={8,2,0,SOURCE},P[4]={8,1,0,PEER};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_infrabb_vef_control_connection_snapshot state;
static void *messages[3],*current_request;
struct predecessors {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot control;
    struct full_imaging_adf_connection_snapshot audio;
    struct full_infrabb_vef_connection_snapshot fourth;
    struct pin_connection_snapshot old_pin;
    struct full_vef_path_snapshot path;
    struct full_adf_proc_snapshot proc;
    struct full_adf_set_input_snapshot input;
    struct full_adf_set_output_snapshot output;
    struct full_bb_set_mode_snapshot bb;
    struct pin_control_snapshot pool;
    struct full_vef_snapshot imaging,source,peer,pinmem,adf;
};
static int pid_matches(void){return atomic_load(&owner_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[90];snprintf(tag,sizeof tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[145],text[700];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;
    snprintf(text,sizeof text,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s transport_owner=virtual-local-caller original_cp_executed=0 frames_verified=0 capture_verified=0",
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
        u32(in+12)==24 && u32(in+16)==n && u16(in+24)==0x1000 && u16(in+26)==op && u16(in+28)==n-24 && u16(in+30)==flags;
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
    full_imaging_adf_connection_snapshot(&p->audio);full_infrabb_vef_connection_snapshot(&p->fourth);
    full_pin_connection_snapshot(&p->old_pin);full_vef_path_snapshot(&p->path);full_adf_proc_snapshot(&p->proc);
    full_adf_set_input_snapshot(&p->input);full_adf_set_output_snapshot(&p->output);full_bb_set_mode_snapshot(&p->bb);
    pin_control_snapshot(&p->pool);native_infraimaging_snapshot(&p->imaging);native_infrabb_snapshot(&p->source);
    full_vef_snapshot(&p->peer);full_pinmem_snapshot(&p->pinmem);full_adf_snapshot(&p->adf);
}
static int cold_pin(const struct full_vef_pin *p,const unsigned int *self){
    static const unsigned int cold_peer[4]={0xff,0xff,0,0};
    return p->state==1 && !memcmp(p->self,self,sizeof p->self) && !memcmp(p->peer,cold_peer,sizeof cold_peer);
}
static int connected(const struct full_vef_pin *a,const struct full_vef_pin *b,const unsigned int *s,const unsigned int *p){
    return !a->state && !b->state && !memcmp(a->self,s,sizeof a->self) && !memcmp(a->peer,p,sizeof a->peer) &&
        !memcmp(b->self,p,sizeof b->self) && !memcmp(b->peer,s,sizeof b->peer);
}
static int quiet_registry(const struct full_vef_snapshot *r,unsigned int sid,unsigned int count){
    return r->initialized && r->owner_sid==sid && r->registry_objects==count && r->queries && !r->pending && !r->faults &&
        !r->live_replies && !r->retained_request && !r->retained_reply;
}
static int dependencies(struct predecessors *p){
    static const unsigned int first_s[4]={0,2,1,NATIVE_INFRAIMAGING_CP},first_p[4]={0,1,1,SOURCE};
    static const unsigned int control_s[4]={8,2,0,NATIVE_INFRAIMAGING_CP},control_p[4]={8,1,0,SOURCE};
    static const unsigned int audio_s[4]={3,2,0,NATIVE_INFRAIMAGING_CP},audio_p[4]={3,1,0,FULL_ADF_CP};
    static const unsigned int fourth_s[4]={0,2,1,SOURCE},fourth_p[4]={0,1,1,PEER};
    static const unsigned int old_s[4]={0,2,3,PEER},old_p[4]={0,1,1,FULL_PINMEM_CP};
    predecessor_snapshot(p);
    const struct full_imaging_pin_connection_snapshot *f=&p->first;
    const struct full_imaging_control_connection_snapshot *c=&p->control;
    const struct full_imaging_adf_connection_snapshot *a=&p->audio;
    const struct full_infrabb_vef_connection_snapshot *v=&p->fourth;
    const struct pin_connection_snapshot *old=&p->old_pin;
    const struct full_vef_path_snapshot *path=&p->path;
    return f->owner_pid==getpid() && f->initialized && f->clean_completion && f->connections==1 && f->ap_consumed==1 &&
        f->format_consumed==1 && f->buffer_freed==1 && f->peer_connected_marker_known==1 && f->peer_connected_marker==1 && f->peer_marker_writes==1 &&
        !f->busy && !f->guard_held && !f->faults && !f->live_reply && !f->retained_request && !f->retained_messages && !f->releasing_reply &&
        c->owner_pid==getpid() && c->initialized && c->clean_completion && c->connections==1 && c->ap_consumed==1 && c->posthook_checked && c->posthook_no_format &&
        c->peer_marker_known==1 && c->peer_marker==1 && c->peer_marker_writes==1 && !c->busy && !c->guard_held && !c->faults &&
        !c->live_reply && !c->retained_request && !c->retained_cleanup && !c->retained_messages && !c->releasing_reply &&
        a->owner_pid==getpid() && a->initialized && a->clean_completion && a->connections==1 && a->ap_consumed==1 &&
        a->no_format_checked && a->callback_guard_checked && !a->callback_selected && !a->busy && !a->guard_held && !a->faults &&
        !a->live_reply && !a->retained_request && !a->retained_cleanup && !a->retained_messages && !a->releasing_reply &&
        v->owner_pid==getpid() && v->initialized && v->clean_completion && v->connections==1 && v->ap_consumed==1 &&
        !v->busy && !v->guard_held && !v->faults && !v->live_reply && !v->retained_request && !v->retained_cleanup && !v->retained_messages && !v->releasing_reply &&
        v->command_prepared && v->command_executed && !v->local_commands_inflight && v->local_commands_returned==1 &&
        v->format_consumed && v->format.matches==1 && v->buffer_freed && v->buffer_closed && v->buffer_transferred && v->predecessor_preserved &&
        p->pool.bound && !p->pool.live && !p->pool.faults && p->pool.allocations>=3 && p->pool.allocations==p->pool.releases &&
        old->started==1 && old->connections==1 && !old->faults && !old->format_pending && old->format_consumed && old->buffer_released &&
        !old->virtual_vef_status && old->format_current.pin_index==2 && old->format_current.ordinal==1 && old->format_current.code==1 &&
        old->format_current.width==1920 && old->format_current.height==1080 &&
        path->owner_pid==getpid() && path->configured && path->clean_completion && !path->busy && !path->guard_held && !path->faults &&
        path->current_path==1 && path->phase==2 && path->state==2 && path->selected_object==FULL_VEF_PATH_NOMEM && !path->work_pending &&
        !path->live_reply && !path->retained_reply && !path->retained_request && !path->retained_cleanup_reply &&
        p->input.owner_pid==getpid() && p->input.configured && p->input.clean_completion && p->input.ap_consumed==1 && !p->input.busy &&
        !p->input.worker_active && !p->input.faults && !p->input.software_s && p->input.ab_failures==1 && !p->input.ab_register_writes &&
        p->input.first_task_status==FULL_ADF_AIP_TASK_ERROR &&
        quiet_registry(&p->imaging,NATIVE_INFRAIMAGING_CP,6) && quiet_registry(&p->source,SOURCE,21) &&
        quiet_registry(&p->peer,PEER,16) && p->source.queries>=4 && p->peer.queries>=3 &&
        quiet_registry(&p->pinmem,FULL_PINMEM_CP,13) && quiet_registry(&p->adf,FULL_ADF_CP,10) &&
        cold_pin(&p->source.pins[9],S) && cold_pin(&p->peer.pins[14],P) &&
        connected(&p->imaging.pins[1],&p->source.pins[1],first_s,first_p) &&
        connected(&p->imaging.pins[5],&p->source.pins[8],control_s,control_p) &&
        connected(&p->imaging.pins[4],&p->adf.pins[4],audio_s,audio_p) &&
        connected(&p->source.pins[5],&p->peer.pins[1],fourth_s,fourth_p) &&
        connected(&p->peer.pins[10],&p->pinmem.pins[1],old_s,old_p);
}
/* Only the new endpoints and source pending may change; no DMM work occurs. */
static int preserved(const struct predecessors *before,unsigned int pending){
    struct predecessors after;predecessor_snapshot(&after);
    if(!connected(&after.source.pins[9],&after.peer.pins[14],S,P) || after.source.pending!=pending || after.peer.pending)return -1;
    after.source.pins[9]=before->source.pins[9];after.source.pending=before->source.pending;after.peer.pins[14]=before->peer.pins[14];
    return memcmp(&after,before,sizeof after)?-1:0;
}
static int posthooks(const struct full_imaging_io *io){
    struct full_vef_snapshot source,peer;native_infrabb_snapshot(&source);full_vef_snapshot(&peer);
    if(!connected(&source.pins[9],&peer.pins[14],S,P) || source.pins[9].self[1]!=2 || source.pins[9].self[0]!=8)return -1;
    /* BB ce08a..ce09a skips marker storage for type8; cec90 exits for dir2. */
    pthread_mutex_lock(&mutex);state.source_posthook_checked=1;state.source_posthook_no_format=1;state.source_marker_skipped=1;pthread_mutex_unlock(&mutex);
    event(io,"SOURCE_POSTHOOK ","raw_ce08a_ce09a_type8_skips_marker=1 raw_cec90_cecf6_dir2_returns=1 source_slot=9 marker_writes=0 original_CP_RAM_read=0 capture_verified=0");
    unsigned int ordinal=peer.registry_objects;
    for(unsigned int i=0;i<peer.registry_objects;i++)if(!memcmp(peer.pins[i].self,P,sizeof P)){ordinal=i;break;}
    if(ordinal!=14 || peer.pins[ordinal].state || memcmp(peer.pins[ordinal].peer,S,sizeof S))return -1;
    unsigned int selected=ordinal==1 || ordinal==2 || ordinal==3;
    if(selected)return -1;
    pthread_mutex_lock(&mutex);state.posthook_checked=1;state.peer_ordinal=ordinal;state.callback_selected=selected;state.posthook_no_format=1;pthread_mutex_unlock(&mutex);
    char text[620];snprintf(text,sizeof text,"raw=0x10c7e8 lookup_raw=0x5f8628 peer_ordinal=%u selected_ordinals=1,2,3 selected=%u registry_objects=%u owned_type=%u owned_dir=%u owned_index=%u owned_sid=%#x peer_state=%u owned_table_readback=1 OtherPIN_raw=0x10c860 return_raw=0x10c866 DMM_allocations=0 notifications=0 cache_writes=0 marker_writes=0 clock_writes=0 MMIO_writes=0 original_CP_executed=0 capture_verified=0",
        ordinal,selected,peer.registry_objects,peer.pins[ordinal].self[0],peer.pins[ordinal].self[1],peer.pins[ordinal].self[2],peer.pins[ordinal].self[3],peer.pins[ordinal].state);
    event(io,"POSTHOOK_NO_FORMAT ",text);return 0;
}
int full_infrabb_vef_control_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);if(!state.initialized){state.owner_pid=pid;state.initialized=1;}pthread_mutex_unlock(&mutex);return 0;
}
void full_infrabb_vef_control_connection_snapshot(struct full_infrabb_vef_control_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_infrabb_vef_control_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<3;i++)out->retained_messages+=messages[i]!=0;
    pthread_mutex_unlock(&mutex);
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){
    pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);event(io,"UNADMITTED ",reason);*result=-1021;return 1;
}
int full_infrabb_vef_control_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                                const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !result || !io)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    const unsigned char *in=request;
    if((u32(in+32)&255)!=8 && (u32(in+48)&255)!=8)return 0;
    unsigned int dst=u32(in),src=io->source(request);
    if(!is_pair(in) || !envelope(io,request,64,1,2) || src!=dst || src>>28!=8 || !(src&0xfffffff)){
        event(io,"UNSUPPORTED ","only-full-key-BB-type8-OUT0-to-VEF-type8-IN0-owned-edge");*result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    pthread_mutex_unlock(&mutex);
    struct predecessors before;
    if(!dependencies(&before))return unadmitted(io,result,"four_predecessors_not_ready=1 requests=0 faults_unchanged=1 owner_not_reset=1");
    if(guard->reserve())return unadmitted(io,result,"resource_guard_busy=1 requests=0 faults_unchanged=1");
    /* Cross-owner snapshots and callbacks never run with our private lock. */
    if(!dependencies(&before)){guard->release();return unadmitted(io,result,"guarded_predecessor_readback_failed=1 requests=0 faults_unchanged=1");}
    pthread_mutex_lock(&mutex);
    if(state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);guard->release();*result=-1021;return 1;}
    state.busy=1;state.requests=1;state.guard_held=1;state.reply_destination=dst;current_request=request;pthread_mutex_unlock(&mutex);
    int queued=0;void *forward=0,*answer=0,*final=0;
    wire(io,"REQUEST ",src,destination,request,64);
    if(make(io,dst,64,&forward))goto failed;
    frame(forward,64,0x100,1);pair(forward);
    if(set_source(io,forward,SOURCE) || pin_registry_connect_step(native_infrabb_registry(),full_vef_registry(),S,P,1))goto failed;
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,64);
    if(!envelope(io,forward,64,0x100,1) || u32(forward) || !is_pair(forward) || io->source(forward)!=SOURCE ||
       pin_registry_connect_step(native_infrabb_registry(),full_vef_registry(),S,P,2))goto failed;
    pthread_mutex_lock(&mutex);state.peer_requests++;pthread_mutex_unlock(&mutex);
    if(make(io,dst,72,&answer))goto failed;
    frame(answer,72,0x8100,1);pair(answer);
    if(set_source(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,72);
    if(!envelope(io,answer,72,0x8100,1) || u32(answer) || !is_pair(answer) || io->source(answer)!=PEER ||
       u32((unsigned char *)answer+64) || u32((unsigned char *)answer+68) ||
       pin_registry_connect_step(native_infrabb_registry(),full_vef_registry(),S,P,3))goto failed;
    pthread_mutex_lock(&mutex);state.peer_replies++;pthread_mutex_unlock(&mutex);
    if(posthooks(io) || drop(io,dst,&forward) || drop(io,dst,&answer) || preserved(&before,1))goto failed;
    pthread_mutex_lock(&mutex);state.predecessor_preserved=1;pthread_mutex_unlock(&mutex);
    if(make(io,dst,56,&final))goto failed;
    frame(final,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32((unsigned char *)final+32+4*i,S[i]);
    if(set_source(io,final,SOURCE) || !envelope(io,final,56,0x8001,2) || u32(final) ||
       u32((unsigned char *)final+48) || u32((unsigned char *)final+52) || preserved(&before,1))goto failed;
    for(unsigned int i=0;i<4;i++)if(u32((unsigned char *)final+32+4*i)!=S[i])goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire);
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.busy || current_request!=request || state.retained_request || state.live_reply || state.releasing_reply){pthread_mutex_unlock(&mutex);goto failed;}
    state.live_reply=final;pthread_mutex_unlock(&mutex);
    if(io->send(dst,final)){
        pthread_mutex_lock(&mutex);
        if(state.live_reply!=final || state.releasing_reply){state.faults++;state.clean_completion=0;final=0;}
        else state.live_reply=0;
        pthread_mutex_unlock(&mutex);goto failed;
    }
    queued=1;wire_from(io,"REPLY_QUEUED ",SOURCE,dst,final,final_wire,sizeof final_wire);
    pthread_mutex_lock(&mutex);state.queued=1;forget(final);pthread_mutex_unlock(&mutex);final=0;
    int freed=io->release(SOURCE,request);
    pthread_mutex_lock(&mutex);state.request_freed=freed==0;
    if(freed){state.faults++;state.clean_completion=0;state.retained_request=request;}else state.retained_request=0;
    current_request=0;pthread_mutex_unlock(&mutex);
    if(pin_registry_connect_step(native_infrabb_registry(),full_vef_registry(),S,P,4) || preserved(&before,0))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_slot=9 peer_ordinal=14 source_state=0 peer_state=0 source_pending=0 posthook_selected=0 format_work=0 marker_writes=0 prior_four_edges_NoMem_AB_failure_S0_preserved=1 unique_reply=1 original_CP_executed=0 frames_verified=0 capture_verified=0");goto done;
failed:
    fail(io,"transaction-incomplete-owned-state-preserved");
    if(forward)drop(io,dst,&forward);
    if(answer)drop(io,dst,&answer);
    if(final)drop(io,dst,&final);
    pthread_mutex_lock(&mutex);current_request=0;pthread_mutex_unlock(&mutex);
done:
    guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
    *result=queued?0:-1021;return 1;
}
int full_infrabb_vef_control_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
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
    if(record){char text[270];snprintf(text,sizeof text,"pid=%d tid=%ld destination=%#x expected=%#x pointer=%p bytes=56 rc=%d faults=%u ap_consumed=%u frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),destination,dst,reply,rc,faults,(unsigned int)(!rc));record("FULL_INFRABB_VEF_CONTROL_CONNECT_REPLY_FREE ",text);}
    *result=rc;return 1;
}
