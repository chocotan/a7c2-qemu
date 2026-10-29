/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "vef-pinmem-control-connection.h"
#include "vef-pinmem-input-connection.h"
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
#define SOURCE FULL_VEF_CP
#define PEER FULL_PINMEM_CP
#define BB NATIVE_INFRABB_CP
#define IMAGING NATIVE_INFRAIMAGING_CP
#define EVENT_TOKEN 0x56450001u
static const unsigned int S[4]={8,2,0,SOURCE},P[4]={8,1,0,PEER};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_vef_pinmem_control_connection_snapshot state;
static void *messages[3],*current_request;
static unsigned char saved_request[64];
/* The native token binds one owned reply body; no host pointer enters CP wire. */
static struct local_event8 {
    unsigned char parameter[32],request[64],answer_wire[72];
    void *answer,*body;
    unsigned int source,destination,token;
} event8;
struct predecessors {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot control;
    struct full_imaging_adf_connection_snapshot audio;
    struct full_infrabb_vef_connection_snapshot fourth;
    struct full_infrabb_vef_control_connection_snapshot fifth;
    struct full_vef_pinmem_input_connection_snapshot sixth;
    struct pin_connection_snapshot old_pin;
    struct full_vef_path_snapshot path;
    struct full_adf_proc_snapshot proc;
    struct full_adf_set_input_snapshot input;
    struct full_adf_set_output_snapshot output;
    struct full_bb_set_mode_snapshot bb;
    struct pin_control_snapshot pool;
    struct full_vef_snapshot imaging,bb_registry,vef,pinmem,adf;
};
static int pid_matches(void){return atomic_load(&owner_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned long long hash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;return h;
}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[96];snprintf(tag,sizeof tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[145],text[700];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;
    snprintf(text,sizeof text,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s transport_owner=virtual-local-caller original_CP_executed=0 frames_verified=0 capture_verified=0",
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
    full_imaging_adf_connection_snapshot(&p->audio);full_infrabb_vef_connection_snapshot(&p->fourth);full_infrabb_vef_control_connection_snapshot(&p->fifth);
    full_vef_pinmem_input_connection_snapshot(&p->sixth);full_pin_connection_snapshot(&p->old_pin);full_vef_path_snapshot(&p->path);
    full_adf_proc_snapshot(&p->proc);full_adf_set_input_snapshot(&p->input);full_adf_set_output_snapshot(&p->output);full_bb_set_mode_snapshot(&p->bb);
    pin_control_snapshot(&p->pool);native_infraimaging_snapshot(&p->imaging);native_infrabb_snapshot(&p->bb_registry);
    full_vef_snapshot(&p->vef);full_pinmem_snapshot(&p->pinmem);full_adf_snapshot(&p->adf);
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
#define CLEAN(x) ((x).owner_pid==getpid() && (x).initialized && (x).clean_completion && (x).requests==1 && (x).connections==1 && \
    (x).ap_consumed==1 && (x).request_freed && (x).reply_freed && !(x).busy && !(x).guard_held && !(x).faults && \
    !(x).live_reply && !(x).retained_request && !(x).retained_messages && !(x).releasing_reply)
static int dependencies(struct predecessors *p){
    static const unsigned int fs[4]={0,2,1,IMAGING},fp[4]={0,1,1,BB},cs[4]={8,2,0,IMAGING},cp[4]={8,1,0,BB};
    static const unsigned int as[4]={3,2,0,IMAGING},ap[4]={3,1,0,FULL_ADF_CP},vs[4]={0,2,1,BB},vp[4]={0,1,1,SOURCE};
    static const unsigned int zs[4]={8,2,0,BB},zp[4]={8,1,0,SOURCE},os[4]={0,2,3,SOURCE},op[4]={0,1,1,PEER};
    static const unsigned int xs[4]={0,2,2,SOURCE},xp[4]={0,1,0,PEER},cache[5]={1,1,1920,1080,3};
    static const unsigned char current[20]={1,0,0,0,0,0,0,0,1,1,3,0,0x80,7,0,0,0x38,4,0,0};
    static const unsigned char initial[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
    static const unsigned char payload[16]={1,1,3,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    static const unsigned char historical[16]={1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    predecessor_snapshot(p);
    const struct full_imaging_pin_connection_snapshot *f=&p->first;
    const struct full_infrabb_vef_connection_snapshot *v=&p->fourth;
    const struct full_vef_pinmem_input_connection_snapshot *x=&p->sixth;
    const struct full_vef_path_snapshot *path=&p->path;
    const struct pin_connection_snapshot *old=&p->old_pin;
    return CLEAN(p->first) && CLEAN(p->control) && CLEAN(p->audio) && CLEAN(p->fourth) && CLEAN(p->fifth) && CLEAN(p->sixth) &&
        !p->control.retained_cleanup && !p->audio.retained_cleanup && !v->retained_cleanup && !p->fifth.retained_cleanup && !x->retained_cleanup &&
        f->format_consumed==1 && f->buffer_freed && f->peer_connected_marker_known==1 && f->peer_connected_marker==1 && f->peer_marker_writes==1 &&
        f->format.initialized && f->format.consumed==2 && !memcmp(f->format.cache,cache,sizeof cache) && f->format.payload_fnv64==hash(payload,16) &&
        f->forwarded_formats==1 && f->forwarded_handle==x->buffer_handle &&
        p->control.posthook_checked && p->control.posthook_no_format && p->control.peer_marker_known==1 && p->control.peer_marker==1 && p->control.peer_marker_writes==1 &&
        p->audio.no_format_checked && p->audio.callback_guard_checked && !p->audio.callback_selected &&
        v->command_prepared && v->command_executed && !v->local_commands_inflight && v->local_commands_returned==1 &&
        v->format_consumed && v->format.matches==1 && !v->format.mismatches && v->buffer_freed && v->buffer_closed && v->buffer_transferred && v->predecessor_preserved &&
        v->format.initialized && v->format.current_known_bytes==20 && v->format.expected_known_bytes==16 && v->format.prepares==1 && v->format.executions==1 && !v->format.command_state &&
        !memcmp(v->format.current,current,20) && !memcmp(v->format.expected,payload,16) && !memcmp(v->format.command_current,initial,20) &&
        v->format.current_fnv==hash(current,20) && v->format.command_fnv==hash(initial,20) && v->format.payload_fnv==hash(historical,16) &&
        v->format.forwarded_vef_payload_fnv==hash(payload,16) && v->format.forwarded_bb_payload_fnv==hash(payload,16) &&
        v->forwarded_vef_formats==1 && v->forwarded_bb_formats==1 && v->forwarded_format_handle==x->buffer_handle &&
        p->fifth.source_posthook_checked && p->fifth.source_posthook_no_format && p->fifth.source_marker_skipped &&
        p->fifth.posthook_checked && p->fifth.posthook_no_format && p->fifth.peer_ordinal==14 && !p->fifth.callback_selected &&
        x->predecessor_preserved && x->buffer_handle && x->buffer_written && x->buffer_freed && x->payload_fnv==hash(payload,16) &&
        x->dmm_requests==9 && x->dmm_replies==9 && x->dmm_allocations==1 && x->dmm_shares==1 && x->dmm_creator_releases==1 &&
        x->dmm_opens==3 && x->dmm_consumer_closes==3 && x->dmm_frees==1 && x->notifications==3 && x->notifications_consumed==3 &&
        x->vef_format_consumed && x->bb_format_consumed && x->bb_format_changed==1 && x->imaging_format_consumed && x->reference_readbacks==9 &&
        !x->owners && !x->opens && !x->creator && !x->consumer && !x->consumer_open && !x->current_consumer_sid &&
        x->runtime_status22_known && x->runtime_status22==1 && x->runtime_status22_writer_generation==1 && x->runtime_status22_writes==1 &&
        p->pool.bound && !p->pool.live && !p->pool.faults && p->pool.allocations>=4 && p->pool.allocations==p->pool.releases &&
        old->started==1 && old->connections==1 && !old->faults && !old->format_pending && old->format_consumed && old->buffer_released &&
        !old->virtual_vef_status && old->format_current.pin_index==2 && old->format_current.ordinal==1 && old->format_current.code==1 &&
        !old->format_current.component && !old->format_current.encoded_flags && old->format_current.width==1920 && old->format_current.height==1080 &&
        path->owner_pid==getpid() && path->configured && path->clean_completion && !path->busy && !path->guard_held && !path->faults &&
        path->current_path==1 && path->phase==2 && path->state==2 && path->selected_object==FULL_VEF_PATH_NOMEM && !path->work_pending &&
        path->runtime_status22_known && path->runtime_status22==1 && path->runtime_status22_writer_generation==1 && path->runtime_status22_writes==1 &&
        path->generation==1 && path->inner_generation==1 && path->applications==1 && path->reply_freed && path->request_freed &&
        !path->live_reply && !path->retained_reply && !path->retained_request && !path->retained_cleanup_reply &&
        p->input.owner_pid==getpid() && p->input.configured && p->input.clean_completion && p->input.ap_consumed==1 && !p->input.busy &&
        !p->input.worker_active && !p->input.faults && !p->input.software_s && p->input.ab_failures==1 && !p->input.ab_register_writes && p->input.first_task_status==FULL_ADF_AIP_TASK_ERROR &&
        quiet_registry(&p->imaging,IMAGING,6) && quiet_registry(&p->bb_registry,BB,21) && quiet_registry(&p->vef,SOURCE,16) && p->vef.queries>=5 &&
        quiet_registry(&p->pinmem,PEER,13) && p->pinmem.queries>=3 && quiet_registry(&p->adf,FULL_ADF_CP,10) &&
        pin_registry_key_get_retired(full_vef_registry(),S) && pin_registry_key_get_retired(full_pinmem_registry(),P) &&
        cold_pin(&p->vef.pins[15],S) && cold_pin(&p->pinmem.pins[12],P) &&
        connected(&p->imaging.pins[1],&p->bb_registry.pins[1],fs,fp) && connected(&p->imaging.pins[5],&p->bb_registry.pins[8],cs,cp) &&
        connected(&p->imaging.pins[4],&p->adf.pins[4],as,ap) && connected(&p->bb_registry.pins[5],&p->vef.pins[1],vs,vp) &&
        connected(&p->bb_registry.pins[9],&p->vef.pins[14],zs,zp) && connected(&p->vef.pins[10],&p->pinmem.pins[1],os,op) &&
        connected(&p->vef.pins[9],&p->pinmem.pins[0],xs,xp);
}
#undef CLEAN
static int preserved(const struct predecessors *before,unsigned int pending){
    struct predecessors after;predecessor_snapshot(&after);
    if(!connected(&after.vef.pins[15],&after.pinmem.pins[12],S,P) || after.vef.pending!=pending || after.pinmem.pending)return -1;
    after.vef.pins[15]=before->vef.pins[15];after.vef.pending=before->vef.pending;after.pinmem.pins[12]=before->pinmem.pins[12];
    return memcmp(&after,before,sizeof after)?-1:0;
}
/* PinMem type8 -> raw f74a2 -> 5d6a78 manager CP10f5008, +c -> 5d6a86. */
static int type8_manager(const unsigned int *source,const unsigned int *peer){
    if(memcmp(source,S,sizeof S) || memcmp(peer,P,sizeof P))return -1021;
    return 0; /* raw 5d6a86: 00207047 (movs r0,0; bx lr). */
}
static int sink_manager(const struct full_imaging_io *io){
    struct full_vef_snapshot a,b;full_vef_snapshot(&a);full_pinmem_snapshot(&b);
    if(a.pins[15].state!=2 || b.pins[12].state || memcmp(b.pins[12].peer,S,sizeof S) || memcmp(b.pins[12].self,P,sizeof P))return -1;
    int (*method)(const unsigned int *,const unsigned int *)=type8_manager;
    int rc=method(b.pins[12].peer,b.pins[12].self);
    pthread_mutex_lock(&mutex);state.manager_calls++;state.manager_return=(unsigned int)rc;pthread_mutex_unlock(&mutex);
    event(io,"SINK_MANAGER ","type=8 choice_raw=0xf7474 branch_raw=0xf74a2 manager_get_raw=0x5d6a78 manager_CP_VA=0x10f5008 vtable_CP_VA=0xd270f0 method_offset=0xc method_raw=0x5d6a86 typed_callback_called=1 rc=0 DMM=0 markers=0 events=0 clocks=0 MMIO=0 original_CP_executed=0 capture_verified=0");return rc;
}
static int enqueue_event8(const struct full_imaging_io *io,void *answer,const unsigned char expected[72]){
    if(!canonical(io,answer,expected,72,PEER))return -1;
    pthread_mutex_lock(&mutex);
    if(state.faults || state.event8_enqueued || state.event8_pending || !state.busy){pthread_mutex_unlock(&mutex);return -1;}
    memset(&event8,0,sizeof event8);event8.answer=answer;event8.body=(unsigned char *)answer+24;
    event8.source=PEER;event8.destination=SOURCE;event8.token=EVENT_TOKEN;put32(event8.parameter,EVENT_TOKEN);
    memcpy(event8.request,saved_request,64);memcpy(event8.answer_wire,expected,72);
    state.event8_enqueued=1;state.event8_pending=1;state.event8_token=EVENT_TOKEN;pthread_mutex_unlock(&mutex);
    event(io,"EVENT8_ENQUEUED ","producer_raw=0x5f99fe-0x5f9a4e event=8 parameter_bytes=32 cleared_bytes=32 body_offset=24 token=0x56450001 token_policy=owned-answer-body-map borrowed_reply_held=1 bounded_local_queue=1 original_CP_event_pointer_identity_verified=0 original_RTOS_scheduling_verified=0 capture_verified=0");return 0;
}
static int consume_event8(const struct full_imaging_io *io){
    struct local_event8 e;void *request;
    pthread_mutex_lock(&mutex);
    if(!state.busy || !state.guard_held || state.faults || state.event8_pending!=1 || state.event8_inflight || state.event8_consumed){
        pthread_mutex_unlock(&mutex);fail(io,"event8-missing-duplicate-or-inflight");return -1;
    }
    state.event8_inflight=1;e=event8;request=current_request;pthread_mutex_unlock(&mutex);
    unsigned char parameter[32]={0};put32(parameter,EVENT_TOKEN);
    int valid=e.token==EVENT_TOKEN && !memcmp(e.parameter,parameter,32) && e.answer && e.body==(unsigned char *)e.answer+24 &&
        e.source==PEER && e.destination==SOURCE && canonical(io,request,e.request,64,state.reply_destination) &&
        canonical(io,e.answer,e.answer_wire,72,PEER) && is_pair(e.request) && is_pair(e.answer_wire) &&
        !memcmp(e.request+48,(unsigned char *)e.body+24,3*sizeof(unsigned int)) &&
        u32(e.request+60)==u32((unsigned char *)e.body+36) && !u32((unsigned char *)e.body+40) && !u32((unsigned char *)e.body+44);
    pthread_mutex_lock(&mutex);valid=valid && !state.faults && !memcmp(&event8,&e,sizeof e);pthread_mutex_unlock(&mutex);
    if(valid)valid=pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,3)==0;
    pthread_mutex_lock(&mutex);state.event8_inflight=0;
    if(valid){state.event8_pending=0;state.event8_consumed=1;state.event8_token_verified=1;state.event8_peer_verified=1;state.peer_replies++;event8.answer=event8.body=0;}
    pthread_mutex_unlock(&mutex);
    if(!valid){fail(io,"event8-parameter-body-saved-request-peer-or-status-mismatch");return -1;}
    event(io,"EVENT8_CONSUMED ","consumer_raw=0x10cb3e-0x10cb6a event=8 actual_parameter_read=1 token_body_binding_verified=1 saved_original_header_bytes=24 original_peer_type_dir_index_verified=1 strict_peer_owner_verified=1 status=0 tail=0 source_complete_raw=0x5839a6 consumed=1 pending=0 original_CP_event_pointer_identity_verified=0 original_RTOS_scheduling_verified=0 capture_verified=0");
    pthread_mutex_lock(&mutex);valid=!state.faults;pthread_mutex_unlock(&mutex);return valid?0:-1;
}
static int source_posthook(const struct full_imaging_io *io){
    struct full_vef_snapshot a,b;full_vef_snapshot(&a);full_pinmem_snapshot(&b);
    if(!connected(&a.pins[15],&b.pins[12],S,P))return -1;
    unsigned int ordinal=a.registry_objects;
    for(unsigned int i=0;i<a.registry_objects;i++)if(!memcmp(a.pins[i].self,S,sizeof S)){ordinal=i;break;}
    if(ordinal!=15 || ordinal==1 || ordinal==2 || ordinal==3)return -1;
    pthread_mutex_lock(&mutex);state.source_ordinal=ordinal;state.posthook_checked=1;state.posthook_no_format=1;pthread_mutex_unlock(&mutex);
    event(io,"POSTHOOK_NO_FORMAT ","handler_raw=0x5f9a30 posthook_raw=0x10c89c lookup_raw=0x5f8628 key=FIRST_source_key source_ordinal=15 owned_table_readback=1 selected_ordinals=1,2,3 selected=0 OtherPIN_raw=0x10c914 current_info_calls=0 f008_calls=0 DMM_allocations=0 notifications=0 cache_writes=0 marker_writes=0 clock_writes=0 MMIO_writes=0 original_CP_executed=0 capture_verified=0");return 0;
}
int full_vef_pinmem_control_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);if(!state.initialized){state.owner_pid=pid;state.source_slot=15;state.peer_ordinal=12;state.initialized=1;}pthread_mutex_unlock(&mutex);return 0;
}
void full_vef_pinmem_control_connection_snapshot(struct full_vef_pinmem_control_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_vef_pinmem_control_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<3;i++)out->retained_messages+=messages[i]!=0;
    memcpy(out->event8_parameter,event8.parameter,32);out->event8_answer=event8.answer;out->event8_body=event8.body;pthread_mutex_unlock(&mutex);
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){
    pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);event(io,"UNADMITTED ",reason);*result=-1021;return 1;
}
int full_vef_pinmem_control_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                               const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !result || !io)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64 || !is_pair(request))return 0;
    unsigned int dst=u32(request),src=io->source(request);unsigned char expected_request[64]={0};frame(expected_request,64,1,2);pair(expected_request);put32(expected_request,dst);
    memcpy(expected_request+20,(unsigned char *)request+20,4);
    if(src!=dst || src>>28!=8 || !(src&0xfffffff) || !canonical(io,request,expected_request,64,src)){
        event(io,"UNSUPPORTED ","only-full-key-VEF-type8-OUT0-to-PinMem-type8-IN0-owned-edge");*result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    pthread_mutex_unlock(&mutex);
    struct predecessors before;
    if(!dependencies(&before))return unadmitted(io,result,"six_predecessors_or_new_cold_Get_not_ready=1 requests=0 faults_unchanged=1 owner_not_reset=1");
    if(guard->reserve())return unadmitted(io,result,"resource_guard_busy=1 requests=0 faults_unchanged=1");
    if(!dependencies(&before)){guard->release();return unadmitted(io,result,"guarded_predecessor_readback_failed=1 requests=0 faults_unchanged=1");}
    pthread_mutex_lock(&mutex);
    if(state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);guard->release();*result=-1021;return 1;}
    state.busy=1;state.requests=1;state.guard_held=1;state.reply_destination=dst;state.sender_tid=syscall(SYS_gettid);current_request=request;memcpy(saved_request,request,64);pthread_mutex_unlock(&mutex);
    int queued=0;void *forward=0,*answer=0,*final=0;unsigned char expected[72]={0};
    wire(io,"REQUEST ",src,destination,request,64);
    if(make(io,dst,64,&forward))goto failed;
    frame(expected,64,0x100,1);pair(expected);memcpy(forward,expected,64);
    if(set_source(io,forward,SOURCE) || pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,1))goto failed;
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,64);
    if(!canonical(io,forward,expected,64,SOURCE) || pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,2))goto failed;
    pthread_mutex_lock(&mutex);state.peer_requests++;pthread_mutex_unlock(&mutex);
    if(sink_manager(io) || make(io,dst,72,&answer))goto failed;
    memset(expected,0,sizeof expected);frame(expected,72,0x8100,1);pair(expected);memcpy(answer,expected,72);
    if(set_source(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,72);
    if(enqueue_event8(io,answer,expected) || consume_event8(io) || source_posthook(io) ||
       drop(io,dst,&forward) || drop(io,dst,&answer) || preserved(&before,1))goto failed;
    pthread_mutex_lock(&mutex);state.predecessor_preserved=1;pthread_mutex_unlock(&mutex);
    if(make(io,dst,56,&final))goto failed;
    memset(expected,0,sizeof expected);frame(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32(expected+32+4*i,S[i]);memcpy(final,expected,56);
    if(set_source(io,final,SOURCE) || !canonical(io,final,expected,56,SOURCE) || preserved(&before,1))goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire);
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.busy || current_request!=request || state.retained_request || state.live_reply || state.releasing_reply){pthread_mutex_unlock(&mutex);goto failed;}
    state.live_reply=final;pthread_mutex_unlock(&mutex);
    if(io->send(dst,final)){
        pthread_mutex_lock(&mutex);
        if(state.live_reply!=final || state.releasing_reply){state.faults++;state.clean_completion=0;final=0;}else state.live_reply=0;
        pthread_mutex_unlock(&mutex);goto failed;
    }
    queued=1;wire_from(io,"REPLY_QUEUED ",SOURCE,dst,final,final_wire,sizeof final_wire);
    pthread_mutex_lock(&mutex);state.queued=1;forget(final);pthread_mutex_unlock(&mutex);final=0;
    int freed=io->release(SOURCE,request);
    pthread_mutex_lock(&mutex);state.request_freed=freed==0;
    if(freed){state.faults++;state.clean_completion=0;state.retained_request=request;}else state.retained_request=0;
    current_request=0;pthread_mutex_unlock(&mutex);
    if(pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,4) || preserved(&before,0))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_slot=15 peer_ordinal=12 source_state=0 peer_state=0 source_pending=0 manager_calls=1 manager_rc=0 event8_enqueued=1 event8_consumed=1 event8_pending=0 source_posthook_ordinal=15 selected=0 format_work=0 marker_writes=0 prior_six_edges_live_caches_DMM_NoMem_AB_failure_S0_preserved=1 unique_reply=1 original_CP_executed=0 frames_verified=0 capture_verified=0");goto done;
failed:
    fail(io,"transaction-incomplete-owned-state-preserved");
    if(forward)drop(io,dst,&forward);
    if(answer){
        pthread_mutex_lock(&mutex);int borrowed=state.event8_pending || state.event8_inflight;
        if(borrowed && !state.retained_cleanup)state.retained_cleanup=answer;
        pthread_mutex_unlock(&mutex);if(!borrowed)drop(io,dst,&answer);
    }
    if(final)drop(io,dst,&final);
    pthread_mutex_lock(&mutex);current_request=0;pthread_mutex_unlock(&mutex);
done:
    guard->release();pthread_mutex_lock(&mutex);state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
    *result=queued?0:-1021;return 1;
}
int full_vef_pinmem_control_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                                              void (*record)(const char *,const char *),int *result){
    if(!reply || !release || !result || !pid_matches())return 0;
    pthread_mutex_lock(&mutex);
    if(reply!=state.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int dst=state.reply_destination;long sender=state.sender_tid,tid=syscall(SYS_gettid);
    if(destination!=dst || state.releasing_reply){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.releasing_reply=1;pthread_mutex_unlock(&mutex);
    int rc=release(destination,reply);
    pthread_mutex_lock(&mutex);state.releasing_reply=0;
    if(rc){state.faults++;state.clean_completion=0;}else{state.live_reply=0;state.reply_freed=1;state.ap_consumed=tid==sender;forget(reply);}
    unsigned int faults=state.faults,consumed=state.ap_consumed;pthread_mutex_unlock(&mutex);
    if(record){char text[330];snprintf(text,sizeof text,"pid=%d tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x pointer=%p bytes=56 rc=%d faults=%u ap_consumed=%u frames_verified=0 capture_verified=0",
        getpid(),tid,sender,(unsigned int)(tid==sender),destination,dst,reply,rc,faults,consumed);record("FULL_VEF_PINMEM_CONTROL_CONNECT_REPLY_FREE ",text);}
    *result=rc;return 1;
}
#ifdef FULL_VEF_TEST
void full_vef_pinmem_control_connection_test_event_corrupt(unsigned int kind){
    if(!pid_matches())return;
    pthread_mutex_lock(&mutex);
    if(state.event8_pending){
        if(kind==1)event8.parameter[0]^=1;
        if(kind==2)event8.body=(unsigned char *)event8.body+1;
        if(kind==3)event8.request[48]^=1;
        if(kind==4)event8.parameter[31]=1;
        if(kind==5)event8.request[20]^=1;
    }
    pthread_mutex_unlock(&mutex);
}
int full_vef_pinmem_control_connection_test_event_consume(const struct full_imaging_io *io){
    if(!pid_matches() || !io || !io->size || !io->source)return -1021;
    return consume_event8(io);
}
#endif
