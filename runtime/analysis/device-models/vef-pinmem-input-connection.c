/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
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
#include "pin-buffer-wire.h"
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
static const unsigned int S[4]={0,2,2,SOURCE},P[4]={0,1,0,PEER};
static const unsigned int VEF_IN[4]={0,1,1,SOURCE},BB_OUT[4]={0,2,1,BB};
static const unsigned int BB_IN[4]={0,1,1,BB},IMAGING_OUT[4]={0,2,1,IMAGING};
static const unsigned char initial_current[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
static const unsigned char initial_payload[16]={1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
static const unsigned char forwarded_current[20]={1,0,0,0,0,0,0,0,1,1,3,0,0x80,7,0,0,0x38,4,0,0};
static const unsigned char forwarded_payload[16]={1,1,3,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_vef_pinmem_input_connection_snapshot state;
static void *messages[4],*current_request;
struct predecessors {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot control;
    struct full_imaging_adf_connection_snapshot audio;
    struct full_infrabb_vef_connection_snapshot fourth;
    struct full_infrabb_vef_control_connection_snapshot fifth;
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
static void put64(unsigned char *p,unsigned long long v){for(unsigned int i=0;i<8;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned long long hash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;return h;
}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[96];snprintf(tag,sizeof tag,"FULL_VEF_PINMEM_INPUT_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[433],text[940];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;
    snprintf(text,sizeof text,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s transport_owner=virtual-local-caller canonical_padding=1 original_CP_executed=0 frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),src,dst,pointer,n,raw);event(io,kind,text);
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *p,unsigned int n){wire_from(io,kind,src,dst,p,p,n);}
static void frame(unsigned char *p,unsigned int n,unsigned int op,unsigned int flags){
    put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,op);put16(p+28,n-24);put16(p+30,flags);
}
static void pair(unsigned char *p,const unsigned int *a,const unsigned int *b){
    for(unsigned int i=0;i<4;i++){put32(p+32+4*i,a[i]);put32(p+48+4*i,b[i]);}
}
static int is_pair(const unsigned char *p){
    for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;
    return 1;
}
static int canonical(const struct full_imaging_io *io,void *p,const unsigned char *expected,unsigned int n,unsigned int src){
    return io->size(p)==n && io->source(p)==src && !memcmp(p,expected,n);
}
static void forget(void *p){for(unsigned int i=0;i<4;i++)if(messages[i]==p){messages[i]=0;break;}}
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
    pthread_mutex_lock(&mutex);unsigned int free_slot=4;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<4;i++){if(messages[i] && messages[i]==*out)alias=1;if(!messages[i] && free_slot==4)free_slot=i;}
    if(alias || (*out && free_slot==4)){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*out=0;event(io,"FAULT ","allocator-returned-live-message-or-capacity");return -1;}
    if(*out)messages[free_slot]=*out;
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,dst,out);return -1;}
    memset(*out,0,n);return 0;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int src){io->set_source(p,src);return io->source(p)==src?0:-1;}
static void predecessor_snapshot(struct predecessors *p){
    memset(p,0,sizeof *p);full_imaging_pin_connection_snapshot(&p->first);full_imaging_control_connection_snapshot(&p->control);
    full_imaging_adf_connection_snapshot(&p->audio);full_infrabb_vef_connection_snapshot(&p->fourth);full_infrabb_vef_control_connection_snapshot(&p->fifth);
    full_pin_connection_snapshot(&p->old_pin);full_vef_path_snapshot(&p->path);full_adf_proc_snapshot(&p->proc);
    full_adf_set_input_snapshot(&p->input);full_adf_set_output_snapshot(&p->output);full_bb_set_mode_snapshot(&p->bb);
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
static int dependencies(struct predecessors *p){
    static const unsigned int cs[4]={8,2,0,IMAGING},cp[4]={8,1,0,BB};
    static const unsigned int as[4]={3,2,0,IMAGING},ap[4]={3,1,0,FULL_ADF_CP};
    static const unsigned int fs[4]={8,2,0,BB},fp[4]={8,1,0,SOURCE};
    static const unsigned int os[4]={0,2,3,SOURCE},op[4]={0,1,1,PEER};
    static const unsigned int initial_cache[5]={0,1,1920,1080,0};
    predecessor_snapshot(p);
    const struct full_imaging_pin_connection_snapshot *f=&p->first;
    const struct full_imaging_control_connection_snapshot *c=&p->control;
    const struct full_imaging_adf_connection_snapshot *a=&p->audio;
    const struct full_infrabb_vef_connection_snapshot *v=&p->fourth;
    const struct full_infrabb_vef_control_connection_snapshot *z=&p->fifth;
    const struct pin_connection_snapshot *old=&p->old_pin;
    const struct full_vef_path_snapshot *path=&p->path;
    return f->owner_pid==getpid() && f->initialized && f->clean_completion && f->connections==1 && f->ap_consumed==1 && f->request_freed && f->reply_freed &&
        f->format_consumed==1 && f->buffer_freed==1 && f->peer_connected_marker_known==1 && f->peer_connected_marker==1 && f->peer_marker_writes==1 &&
        f->format.initialized==1 && f->format.consumed==1 && !memcmp(f->format.cache,initial_cache,sizeof initial_cache) &&
        f->format.payload_fnv64==hash(initial_payload,sizeof initial_payload) && !f->forwarded_formats && !f->forwarded_handle &&
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
        v->format_consumed && v->format.matches==1 && !v->format.mismatches && v->buffer_freed && v->buffer_closed && v->buffer_transferred && v->predecessor_preserved &&
        v->format.initialized==1 && v->format.current_known_bytes==20 && v->format.expected_known_bytes==16 && v->format.prepares==1 && v->format.executions==1 && !v->format.command_state &&
        !memcmp(v->format.current,initial_current,sizeof initial_current) && !memcmp(v->format.command_current,initial_current,sizeof initial_current) &&
        !memcmp(v->format.expected,initial_payload,sizeof initial_payload) && v->format.current_fnv==hash(initial_current,sizeof initial_current) &&
        v->format.command_fnv==v->format.current_fnv && v->format.payload_fnv==hash(initial_payload,sizeof initial_payload) &&
        !v->forwarded_vef_formats && !v->forwarded_bb_formats && !v->forwarded_format_handle && !v->format.forwarded_vef_payload_fnv && !v->format.forwarded_bb_payload_fnv &&
        z->owner_pid==getpid() && z->initialized && z->clean_completion && z->connections==1 && z->ap_consumed==1 && z->request_freed && z->reply_freed &&
        !z->busy && !z->guard_held && !z->faults && !z->live_reply && !z->retained_request && !z->retained_cleanup && !z->retained_messages && !z->releasing_reply &&
        z->source_posthook_checked && z->source_posthook_no_format && z->source_marker_skipped && z->posthook_checked && z->posthook_no_format && z->peer_ordinal==14 && !z->callback_selected &&
        p->pool.bound && !p->pool.live && !p->pool.faults && p->pool.allocations>=3 && p->pool.allocations==p->pool.releases &&
        old->started==1 && old->connections==1 && !old->faults && !old->format_pending && old->format_consumed && old->buffer_released &&
        !old->virtual_vef_status && old->format_current.pin_index==2 && old->format_current.ordinal==1 && old->format_current.code==1 &&
        !old->format_current.component && !old->format_current.encoded_flags && old->format_current.width==1920 && old->format_current.height==1080 &&
        path->owner_pid==getpid() && path->configured && path->clean_completion && !path->busy && !path->guard_held && !path->faults &&
        path->current_path==1 && path->phase==2 && path->state==2 && path->selected_object==FULL_VEF_PATH_NOMEM && !path->work_pending &&
        path->runtime_status22_known==1 && path->runtime_status22==1 && path->runtime_status22_writer_generation==1 && path->runtime_status22_writes==1 &&
        path->generation==1 && path->inner_generation==1 && path->applications==1 && path->reply_freed==1 && path->request_freed==1 &&
        !path->live_reply && !path->retained_reply && !path->retained_request && !path->retained_cleanup_reply &&
        p->input.owner_pid==getpid() && p->input.configured && p->input.clean_completion && p->input.ap_consumed==1 && !p->input.busy &&
        !p->input.worker_active && !p->input.faults && !p->input.software_s && p->input.ab_failures==1 && !p->input.ab_register_writes &&
        p->input.first_task_status==FULL_ADF_AIP_TASK_ERROR &&
        quiet_registry(&p->imaging,IMAGING,6) && quiet_registry(&p->bb_registry,BB,21) && quiet_registry(&p->vef,SOURCE,16) &&
        p->vef.queries>=4 && quiet_registry(&p->pinmem,PEER,13) && p->pinmem.queries>=2 && quiet_registry(&p->adf,FULL_ADF_CP,10) &&
        cold_pin(&p->vef.pins[9],S) && cold_pin(&p->pinmem.pins[0],P) &&
        connected(&p->imaging.pins[1],&p->bb_registry.pins[1],IMAGING_OUT,BB_IN) &&
        connected(&p->imaging.pins[5],&p->bb_registry.pins[8],cs,cp) && connected(&p->imaging.pins[4],&p->adf.pins[4],as,ap) &&
        connected(&p->bb_registry.pins[5],&p->vef.pins[1],BB_OUT,VEF_IN) && connected(&p->bb_registry.pins[9],&p->vef.pins[14],fs,fp) &&
        connected(&p->vef.pins[10],&p->pinmem.pins[1],os,op);
}
/* Compare exact expected live deltas; historical command/ordinal1/clock/bank and
 * failure snapshots remain byte-for-byte authoritative, never replaced. */
static int preserved(const struct predecessors *before,unsigned int pending,unsigned int consumed){
    struct predecessors after,expected=*before;predecessor_snapshot(&after);
    if(!connected(&after.vef.pins[9],&after.pinmem.pins[0],S,P) || after.vef.pending!=pending || after.pinmem.pending)return -1;
    expected.vef.pins[9]=after.vef.pins[9];expected.vef.pending=pending;expected.pinmem.pins[0]=after.pinmem.pins[0];
    if(consumed){
        expected.pool.allocations++;expected.pool.releases++;expected.pool.payload_writes++;expected.pool.consumer_reads+=3;
        expected.pool.shares++;expected.pool.creator_releases++;expected.pool.consumer_opens+=3;expected.pool.consumer_closes+=3;expected.pool.consumer_releases++;
        memcpy(expected.fourth.format.current,forwarded_current,sizeof forwarded_current);memcpy(expected.fourth.format.expected,forwarded_payload,sizeof forwarded_payload);
        expected.fourth.format.current_fnv=hash(forwarded_current,sizeof forwarded_current);
        expected.fourth.format.forwarded_vef_payload_fnv=expected.fourth.format.forwarded_bb_payload_fnv=hash(forwarded_payload,sizeof forwarded_payload);
        expected.fourth.forwarded_vef_formats=expected.fourth.forwarded_bb_formats=1;expected.fourth.forwarded_format_handle=state.buffer_handle;
        const unsigned int cache[5]={1,1,1920,1080,3};memcpy(expected.first.format.cache,cache,sizeof cache);
        expected.first.format.consumed++;expected.first.format.payload_fnv64=hash(forwarded_payload,sizeof forwarded_payload);
        expected.first.forwarded_formats=1;expected.first.forwarded_handle=state.buffer_handle;
    }
    return memcmp(&after,&expected,sizeof after)?-1:0;
}
int full_vef_pinmem_input_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);
    if(!state.initialized){
        state.owner_pid=pid;state.record=(struct pin_yc_parameters){3,1920,1080,1,1};
        state.record_index=0;state.record_bound=1;state.source_slot=9;state.peer_ordinal=0;state.initialized=1;
    }
    pthread_mutex_unlock(&mutex);return 0;
}
void full_vef_pinmem_input_connection_snapshot(struct full_vef_pinmem_input_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_vef_pinmem_input_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<4;i++)out->retained_messages+=messages[i]!=0;
    pthread_mutex_unlock(&mutex);
}
static int references(const struct full_imaging_io *io,const char *phase,unsigned int owners,unsigned int opens,unsigned int creator,unsigned int consumer,unsigned int consumer_open){
    struct pin_control_references r={0};
    if(pin_control_references(state.buffer_handle,&r) || r.handle!=state.buffer_handle || r.owners!=owners || r.opens!=opens ||
       r.creator!=creator || r.consumer!=consumer || r.consumer_open!=consumer_open)return -1;
    pthread_mutex_lock(&mutex);state.reference_readbacks++;state.owners=r.owners;state.opens=r.opens;state.creator=r.creator;state.consumer=r.consumer;state.consumer_open=r.consumer_open;pthread_mutex_unlock(&mutex);
    char text[300];snprintf(text,sizeof text,"pid=%d tid=%ld phase=%s handle=%#x owners=%u opens=%u creator=%u consumer=%u consumer_open=%u current_consumer_sid=%#x",
        getpid(),syscall(SYS_gettid),phase,r.handle,r.owners,r.opens,r.creator,r.consumer,r.consumer_open,state.current_consumer_sid);event(io,"REFERENCE_READBACK ",text);return 0;
}
/* The 216B BB/Imaging senders are explicit virtual identities; Sony's temporary
 * owner284/owner5 tasks and uninitialized message padding are not reproduced. */
static int dmm(const struct full_imaging_io *io,unsigned int dst,unsigned int stage){
    static const unsigned int commands[9]={0x20,0x21,0x23,0x24,0x25,0x24,0x25,0x24,0x23};
    if(!stage || stage>9 || state.dmm_requests!=stage-1)return -1;
    unsigned int command=commands[stage-1],n=stage<=5?152u:216u;
    unsigned int src=stage<=3?PIN_CONTROL_CLIENT_SID:stage<=5?SOURCE:stage<=7?BB:IMAGING;
    unsigned int option=stage==1?1u:stage==3 || stage==9?2u:0u;
    unsigned int wait=stage==1 || stage==6?0xffffffffu:0u;
    unsigned int notify=stage<=3?0u:stage<=5?1u:stage<=7?2u:3u;
    if(state.notifications_consumed!=notify || (notify && state.current_consumer_sid!=src) ||
       (stage==5 && !state.vef_format_consumed) || (stage==7 && (!state.bb_format_consumed || state.bb_format_changed!=1)) ||
       (stage==9 && !state.imaging_format_consumed))return -1;
    void *message=0;if(make(io,dst,n,&message))return -1;
    unsigned char expected[216]={0};put16(expected,command);
    if(n==216)put16(expected+0x14,0x55);
    if(stage==1){put32(expected+4,PIN_CONTROL_UNIT);put32(expected+0xc,wait);}
    else{put32(expected+8,state.buffer_handle);if(stage==2)put32(expected+4,PIN_CONTROL_UNIT);if(command==0x24)put32(expected+0xc,wait);}
    put16(expected+0x16,option);memcpy(message,expected,n);
    if(set_source(io,message,src)){drop(io,dst,&message);return -1;}
    wire(io,"DMM_REQUEST ",src,PIN_CONTROL_DMM_SID,message,n);
    if(!canonical(io,message,expected,n,src)){drop(io,dst,&message);return -1;}
    struct pin_control_lease lease={0};int rc;
    if(n==152)rc=pin_control_dmm_message(PIN_CONTROL_DMM_SID,src,message,n,1)==1?0:-1;
    else if(command==0x24)rc=pin_control_open_consumer(state.buffer_handle,PIN_CONTROL_UNIT,&lease);
    else if(command==0x25)rc=pin_control_close_consumer(state.buffer_handle);
    else rc=pin_control_release_consumer(state.buffer_handle);
    if(rc){drop(io,dst,&message);return -1;}
    pthread_mutex_lock(&mutex);state.dmm_requests++;
    if(stage==1){
        state.buffer_handle=u32((unsigned char *)message+0xc);unsigned int slot=state.buffer_handle&0x3ff;
        state.buffer_physical=PIN_CONTROL_PHYSICAL+(unsigned long long)slot*PIN_CONTROL_SLOT_BYTES;
        state.buffer_cp_virtual=PIN_CONTROL_CP_VIRTUAL+slot*PIN_CONTROL_SLOT_BYTES;state.buffer_bytes=PIN_CONTROL_SLOT_BYTES;state.dmm_allocations++;
    }else if(stage==2)state.dmm_shares++;
    else if(stage==3)state.dmm_creator_releases++;
    else if(command==0x24)state.dmm_opens++;
    else if(command==0x25)state.dmm_consumer_closes++;
    else{state.dmm_frees++;state.dmm_consumer_closes++;state.buffer_freed=1;}
    pthread_mutex_unlock(&mutex);
    memset(expected,0,n);put16(expected,command|0x8000);if(n==216)put16(expected+6,0x55);put32(expected+0xc,state.buffer_handle);
    if(stage==1 || stage==2)put32(expected+0x10,PIN_CONTROL_UNIT);
    if(command==0x20 || command==0x24){put16(expected+8,1);put64(expected+0x18,state.buffer_physical);put32(expected+0x20,state.buffer_bytes);}
    if(n==216)memcpy(message,expected,n);
    int lease_valid=n==152 || command!=0x24 || (lease.handle==state.buffer_handle && lease.unit==PIN_CONTROL_UNIT && lease.bytes==state.buffer_bytes &&
        lease.physical==state.buffer_physical && lease.cp_virtual==state.buffer_cp_virtual && lease.slot<PIN_CONTROL_SLOTS);
    if(set_source(io,message,PIN_CONTROL_DMM_SID)){drop(io,dst,&message);return -1;}
    wire(io,"DMM_REPLY ",PIN_CONTROL_DMM_SID,src,message,n);
    int valid=lease_valid && (state.buffer_handle&0x3ff)<PIN_CONTROL_SLOTS && canonical(io,message,expected,n,PIN_CONTROL_DMM_SID);
    if(valid){pthread_mutex_lock(&mutex);state.dmm_replies++;pthread_mutex_unlock(&mutex);}
    return drop(io,dst,&message) || !valid?-1:0;
}
static int live_caches(unsigned int hop){
    struct full_infrabb_vef_connection_snapshot v;struct full_imaging_pin_connection_snapshot f;
    full_infrabb_vef_connection_snapshot(&v);full_imaging_pin_connection_snapshot(&f);
    if(v.forwarded_vef_formats!=1 || v.forwarded_format_handle!=state.buffer_handle || memcmp(v.format.current,forwarded_current,20) ||
       v.format.current_fnv!=hash(forwarded_current,20) || v.format.forwarded_vef_payload_fnv!=hash(forwarded_payload,16))return -1;
    if(hop>=2 && (v.forwarded_bb_formats!=1 || memcmp(v.format.expected,forwarded_payload,16) || v.format.forwarded_bb_payload_fnv!=hash(forwarded_payload,16)))return -1;
    if(hop==1 && (v.forwarded_bb_formats || memcmp(v.format.expected,initial_payload,16)))return -1;
    if(hop==3){const unsigned int cache[5]={1,1,1920,1080,3};
        if(f.forwarded_formats!=1 || f.forwarded_handle!=state.buffer_handle || f.format.consumed!=2 ||
           memcmp(f.format.cache,cache,sizeof cache) || f.format.payload_fnv64!=hash(forwarded_payload,16))return -1;}
    return 0;
}
static int consume_hop(const struct full_imaging_io *io,unsigned int dst,unsigned int hop){
    const unsigned int *a=hop==1?P:hop==2?VEF_IN:BB_IN,*b=hop==1?S:hop==2?BB_OUT:IMAGING_OUT;
    unsigned int src=hop==1?PEER:hop==2?SOURCE:BB,target=hop==1?SOURCE:hop==2?BB:IMAGING;
    if(!hop || hop>3 || state.notifications_consumed!=hop-1)return -1;
    struct full_vef_snapshot v,bb,im,pm;full_vef_snapshot(&v);native_infrabb_snapshot(&bb);native_infraimaging_snapshot(&im);full_pinmem_snapshot(&pm);
    if((hop==1 && !connected(&pm.pins[0],&v.pins[9],P,S)) ||
       (hop==2 && !connected(&v.pins[1],&bb.pins[5],VEF_IN,BB_OUT)) ||
       (hop==3 && !connected(&bb.pins[1],&im.pins[1],BB_IN,IMAGING_OUT)))return -1;
    void *notify=0;if(make(io,dst,80,&notify))return -1;
    unsigned char expected[80]={0};frame(expected,80,0x104,1);pair(expected,a,b);put32(expected+64,PIN_CONTROL_UNIT);put32(expected+68,state.buffer_handle);memcpy(notify,expected,80);
    if(set_source(io,notify,src)){drop(io,dst,&notify);return -1;}
    wire(io,"FORMAT_NOTIFY ",src,target,notify,80);
    pthread_mutex_lock(&mutex);state.notifications++;pthread_mutex_unlock(&mutex);
    if(!canonical(io,notify,expected,80,src)){drop(io,dst,&notify);return -1;}
    pthread_mutex_lock(&mutex);state.notifications_consumed++;state.current_consumer_sid=target;pthread_mutex_unlock(&mutex);
    char text[270];snprintf(text,sizeof text,"hop=%u source=%#x destination=%#x handle=%#x offset=0 size=0x404 actual_notification_consumed=1 extra_share=0",hop,src,target,state.buffer_handle);event(io,"FORMAT_NOTIFY_CONSUMED ",text);
    unsigned int stage=hop==1?4u:hop==2?6u:8u;
    if(dmm(io,dst,stage) || references(io,hop==1?"vef-open":hop==2?"bb-open":"imaging-open",1,1,0,1,1))goto failed;
    int rc,changed=0;
    if(hop==1)rc=full_infrabb_vef_connection_accept_forwarded_vef_format(state.buffer_handle,io);
    else if(hop==2)rc=full_infrabb_vef_connection_accept_forwarded_bb_format(state.buffer_handle,io,&changed);
    else rc=full_imaging_pin_connection_accept_forwarded_format(state.buffer_handle,io);
    if(rc || (hop==2 && changed!=1) || live_caches(hop))goto failed;
    pthread_mutex_lock(&mutex);
    if(hop==1)state.vef_format_consumed=1;else if(hop==2){state.bb_format_consumed=1;state.bb_format_changed=(unsigned int)changed;}else state.imaging_format_consumed=1;
    pthread_mutex_unlock(&mutex);
    snprintf(text,sizeof text,"hop=%u source=%#x destination=%#x handle=%#x mapped_read=1 payload_fnv64=%016llx changed=%d live_authority_updated=1 old_ordinal1_preserved=1 frames_verified=0 capture_verified=0",hop,src,target,state.buffer_handle,hash(forwarded_payload,16),changed);event(io,"FORMAT_CONSUMED ",text);
    if(dmm(io,dst,stage+1))goto failed;
    if(hop<3 && references(io,hop==1?"vef-closed":"bb-closed",1,0,0,1,0))goto failed;
    if(drop(io,dst,&notify))return -1;
    return 0;
failed:
    drop(io,dst,&notify);return -1;
}
static int format_chain(const struct full_imaging_io *io,unsigned int dst,const struct predecessors *before){
    if(!state.record_bound || state.record_index || state.record.raw_flags!=3 || state.record.width!=1920 || state.record.height!=1080 || state.record.code!=1 || state.record.component!=1)return -1;
    unsigned char packet[80];unsigned long long digest=0;
    if(pin_yc_build(&state.record,packet,sizeof packet) || memcmp(packet+64,forwarded_payload,16) ||
       dmm(io,dst,1) || references(io,"allocated",1,1,1,0,0) || pin_control_write_payload(state.buffer_handle,packet,sizeof packet,&digest))return -1;
    pthread_mutex_lock(&mutex);state.buffer_written=1;state.buffer_fnv=digest;state.payload_fnv=hash(packet+64,16);pthread_mutex_unlock(&mutex);
    char text[650];snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x physical=%#llx cp_virtual=%#x bytes=80 fnv64=%016llx payload_fnv64=%016llx record_index=0 raw_flags=3 code=1 component=1 width=1920 height=1080 source=public-PinMem-constructor-raw5d6b60-5d6bbe header_word=0x01000000 key=0 payload=01010300000000008007000038040000 original_CP_RAM_read=0 original_CP_page_tables_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),state.buffer_handle,state.buffer_physical,state.buffer_cp_virtual,digest,state.payload_fnv);event(io,"FORMAT_WRITTEN ",text);
    if(dmm(io,dst,2) || references(io,"shared",2,1,1,1,0) || dmm(io,dst,3) || references(io,"creator-released",1,0,0,1,0))return -1;
    for(unsigned int hop=1;hop<=3;hop++)if(consume_hop(io,dst,hop))return -1;
    struct pin_control_references ended={0};struct pin_control_snapshot pool;pin_control_snapshot(&pool);
    if(pin_control_references(state.buffer_handle,&ended)==0 || pool.live || pool.faults || pool.allocations!=pool.releases || preserved(before,1,1))return -1;
    pthread_mutex_lock(&mutex);state.reference_readbacks++;state.owners=state.opens=state.creator=state.consumer=state.consumer_open=state.current_consumer_sid=0;pthread_mutex_unlock(&mutex);
    event(io,"REFERENCE_READBACK ","phase=retired owners=0 opens=0 creator=0 consumer=0 consumer_open=0 handle_lookup_refused=1 pool_live=0 exact_pool_deltas_verified=1");
    event(io,"BUFFER_RETIRED ","DMM_requests=9 DMM_replies=9 notifications=3 mapped_reads=3 extra_share=0 consumer_Close25=2 final_Free23_option2_closes_once=1 owners=0 opens=0 live=0 old_ordinal1_preserved=1 capture_verified=0");return 0;
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){
    pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);event(io,"UNADMITTED ",reason);*result=-1021;return 1;
}
int full_vef_pinmem_input_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                             const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !result || !io)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !io->record || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    if(!is_pair(request))return 0;
    unsigned int dst=u32(request),src=io->source(request);unsigned char expected_request[64]={0};frame(expected_request,64,1,2);pair(expected_request,S,P);put32(expected_request,dst);
    /* The original request has observed unknown outer bytes; only the known
     * envelope and complete endpoint keys are constrained, not those holes. */
    memcpy(expected_request+20,(unsigned char *)request+20,4);
    if(src!=dst || src>>28!=8 || !(src&0xfffffff) || !canonical(io,request,expected_request,64,src)){
        event(io,"UNSUPPORTED ","only-full-key-VEF-OUT2-to-PinMem-IN0-owned-edge");*result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    pthread_mutex_unlock(&mutex);
    struct predecessors before;
    if(!dependencies(&before))return unadmitted(io,result,"five_predecessors_or_tracked_SetPath_status_not_ready=1 requests=0 faults_unchanged=1 owner_not_reset=1");
    if(guard->reserve())return unadmitted(io,result,"resource_guard_busy=1 requests=0 faults_unchanged=1");
    if(!dependencies(&before)){guard->release();return unadmitted(io,result,"guarded_predecessor_readback_failed=1 requests=0 faults_unchanged=1");}
    pthread_mutex_lock(&mutex);
    if(state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);guard->release();*result=-1021;return 1;}
    state.busy=1;state.requests=1;state.guard_held=1;state.reply_destination=dst;current_request=request;
    state.runtime_status22=before.path.runtime_status22;state.runtime_status22_known=before.path.runtime_status22_known;
    state.runtime_status22_writer_generation=before.path.runtime_status22_writer_generation;state.runtime_status22_writes=before.path.runtime_status22_writes;pthread_mutex_unlock(&mutex);
    int queued=0;void *forward=0,*answer=0,*final=0;unsigned char expected[72]={0};
    wire(io,"REQUEST ",src,destination,request,64);
    event(io,"STATUS_READBACK ","runtime_status22=1 known=1 writer_generation=1 writes=1 producer=SetPath-original-completion-raw109c3c-109cde NoMem_state=2 distinct_old_ordinal1_status=0 not_forced=1");
    if(make(io,dst,64,&forward))goto failed;
    frame(expected,64,0x100,1);pair(expected,S,P);memcpy(forward,expected,64);
    if(set_source(io,forward,SOURCE) || pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,1))goto failed;
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,64);
    if(!canonical(io,forward,expected,64,SOURCE) || pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,2))goto failed;
    pthread_mutex_lock(&mutex);state.peer_requests++;pthread_mutex_unlock(&mutex);
    if(make(io,dst,72,&answer))goto failed;
    memset(expected,0,sizeof expected);frame(expected,72,0x8100,1);pair(expected,S,P);memcpy(answer,expected,72);
    if(set_source(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,72);
    if(!canonical(io,answer,expected,72,PEER) || pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,3))goto failed;
    pthread_mutex_lock(&mutex);state.peer_replies++;pthread_mutex_unlock(&mutex);
    if(drop(io,dst,&forward) || drop(io,dst,&answer) || preserved(&before,1,0) || format_chain(io,dst,&before) || preserved(&before,1,1))goto failed;
    pthread_mutex_lock(&mutex);state.predecessor_preserved=1;pthread_mutex_unlock(&mutex);
    if(make(io,dst,56,&final))goto failed;
    memset(expected,0,sizeof expected);frame(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32(expected+32+4*i,S[i]);memcpy(final,expected,56);
    if(set_source(io,final,SOURCE) || !canonical(io,final,expected,56,SOURCE) || preserved(&before,1,1))goto failed;
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
    if(pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,4) || preserved(&before,0,1))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_slot=9 peer_ordinal=0 source_state=0 peer_state=0 source_pending=0 DMM_requests=9 notifications=3 mapped_reads=3 VEF_BB_Imaging_live_caches_updated=1 buffer_freed=1 prior_five_histories_NoMem_AB_failure_S0_clocks_banks_preserved=1 unique_reply=1 original_CP_executed=0 frames_verified=0 capture_verified=0");goto done;
failed:
    fail(io,"transaction-incomplete-partial-mapped-buffer-and-live-caches-preserved");
    if(forward)drop(io,dst,&forward);
    if(answer)drop(io,dst,&answer);
    if(final)drop(io,dst,&final);
    pthread_mutex_lock(&mutex);current_request=0;pthread_mutex_unlock(&mutex);
done:
    guard->release();pthread_mutex_lock(&mutex);state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
    *result=queued?0:-1021;return 1;
}
int full_vef_pinmem_input_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
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
    if(record){char text[300];snprintf(text,sizeof text,"pid=%d tid=%ld destination=%#x expected=%#x pointer=%p bytes=56 rc=%d faults=%u ap_consumed=%u frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),destination,dst,reply,rc,faults,(unsigned int)(!rc));record("FULL_VEF_PINMEM_INPUT_CONNECT_REPLY_FREE ",text);}
    *result=rc;return 1;
}
