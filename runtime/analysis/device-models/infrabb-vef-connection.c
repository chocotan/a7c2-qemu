/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "infrabb-vef-connection.h"
#include "imaging-pin-connection.h"
#include "imaging-control-connection.h"
#include "imaging-adf-connection.h"
#include "adf-set-input-device.h"
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
#define DMM 0x0061003cu
static const unsigned int S[4]={0,2,1,SOURCE},P[4]={0,1,1,PEER};
static const unsigned int OLD_S[4]={0,2,3,PEER},OLD_P[4]={0,1,1,FULL_PINMEM_CP};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_infrabb_vef_connection_snapshot state;
static void *messages[8],*current_request;
struct predecessors {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot control;
    struct full_imaging_adf_connection_snapshot audio;
    struct pin_connection_snapshot old_pin;
    struct full_vef_path_snapshot path;
    struct full_adf_set_input_snapshot input;
    struct pin_control_snapshot pool;
    struct full_vef_snapshot imaging,source,peer,pinmem,adf;
};
static int pid_matches(void){return atomic_load(&owner_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static unsigned long long u64(const unsigned char *p){return u32(p)|(unsigned long long)u32(p+4)<<32;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void put64(unsigned char *p,unsigned long long v){put32(p,(unsigned int)v);put32(p+4,(unsigned int)(v>>32));}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_INFRABB_VEF_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[433],text[900];
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
static void forget(void *p){for(unsigned int i=0;i<8;i++)if(messages[i]==p){messages[i]=0;break;}}
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
    pthread_mutex_lock(&mutex);unsigned int free_slot=8;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<8;i++){if(messages[i] && messages[i]==*out)alias=1;if(!messages[i] && free_slot==8)free_slot=i;}
    if(alias || (*out && free_slot==8)){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*out=0;event(io,"FAULT ","allocator-returned-live-message-or-capacity");return -1;}
    if(*out)messages[free_slot]=*out;
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,dst,out);return -1;}
    memset(*out,0,n);return 0;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int src){io->set_source(p,src);return io->source(p)==src?0:-1;}
static void predecessor_snapshot(struct predecessors *p){
    memset(p,0,sizeof *p);full_imaging_pin_connection_snapshot(&p->first);full_imaging_control_connection_snapshot(&p->control);
    full_imaging_adf_connection_snapshot(&p->audio);full_pin_connection_snapshot(&p->old_pin);full_vef_path_snapshot(&p->path);
    full_adf_set_input_snapshot(&p->input);pin_control_snapshot(&p->pool);native_infraimaging_snapshot(&p->imaging);
    native_infrabb_snapshot(&p->source);full_vef_snapshot(&p->peer);full_pinmem_snapshot(&p->pinmem);full_adf_snapshot(&p->adf);
}
static int cold_pin(const struct full_vef_pin *p,const unsigned int *self){
    static const unsigned int cold_peer[4]={0xff,0xff,0,0};
    return p->state==1 && !memcmp(p->self,self,sizeof p->self) && !memcmp(p->peer,cold_peer,sizeof cold_peer);
}
static int quiet_registry(const struct full_vef_snapshot *r,unsigned int sid,unsigned int count){
    return r->initialized && r->owner_sid==sid && r->registry_objects==count && r->queries && !r->pending && !r->faults &&
        !r->live_replies && !r->retained_request && !r->retained_reply;
}
static int dependencies(struct predecessors *p){
    predecessor_snapshot(p);
    const struct full_imaging_pin_connection_snapshot *f=&p->first;
    const struct full_imaging_control_connection_snapshot *c=&p->control;
    const struct full_imaging_adf_connection_snapshot *a=&p->audio;
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
        p->pool.bound && !p->pool.live && !p->pool.faults && p->pool.allocations>=2 && p->pool.allocations==p->pool.releases &&
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
        quiet_registry(&p->peer,PEER,16) && quiet_registry(&p->pinmem,FULL_PINMEM_CP,13) && quiet_registry(&p->adf,FULL_ADF_CP,10) &&
        cold_pin(&p->source.pins[5],S) && cold_pin(&p->peer.pins[1],P) &&
        !p->peer.pins[10].state && !memcmp(p->peer.pins[10].self,OLD_S,sizeof OLD_S) && !memcmp(p->peer.pins[10].peer,OLD_P,sizeof OLD_P) &&
        !p->pinmem.pins[1].state && !memcmp(p->pinmem.pins[1].self,OLD_P,sizeof OLD_P) && !memcmp(p->pinmem.pins[1].peer,OLD_S,sizeof OLD_S);
}
static int preserved(const struct predecessors *before,unsigned int pending,unsigned int buffer_done){
    struct predecessors after;predecessor_snapshot(&after);
    if(after.source.pins[5].state || after.peer.pins[1].state || after.source.pending!=pending || after.peer.pending ||
       memcmp(after.source.pins[5].self,S,sizeof S) || memcmp(after.source.pins[5].peer,P,sizeof P) ||
       memcmp(after.peer.pins[1].self,P,sizeof P) || memcmp(after.peer.pins[1].peer,S,sizeof S))return -1;
    after.source.pins[5]=before->source.pins[5];after.source.pending=before->source.pending;after.peer.pins[1]=before->peer.pins[1];
    struct pin_control_snapshot expected=before->pool;
    if(buffer_done){
        expected.allocations++;expected.releases++;expected.payload_writes++;expected.consumer_reads++;
        expected.consumer_opens++;expected.consumer_closes++;expected.consumer_releases++;expected.creator_closes++;expected.creator_transfers++;
    }
    if(memcmp(&after.pool,&expected,sizeof expected))return -1;
    after.pool=before->pool;
    return memcmp(&after,before,sizeof after)?-1:0;
}
int full_infrabb_vef_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);
    if(!state.initialized){state.owner_pid=pid;if(full_infrabb_vef_format_init(&state.format)){pthread_mutex_unlock(&mutex);return -1021;}state.initialized=1;}
    pthread_mutex_unlock(&mutex);return 0;
}
void full_infrabb_vef_connection_snapshot(struct full_infrabb_vef_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_infrabb_vef_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<8;i++)out->retained_messages+=messages[i]!=0;
    pthread_mutex_unlock(&mutex);
}
static int references(const struct full_imaging_io *io,const char *phase,unsigned int owners,unsigned int opens,unsigned int creator,unsigned int consumer,unsigned int consumer_open){
    struct pin_control_references r={0};
    if(pin_control_references(state.buffer_handle,&r) || r.owners!=owners || r.opens!=opens || r.creator!=creator || r.consumer!=consumer || r.consumer_open!=consumer_open)return -1;
    char text[250];snprintf(text,sizeof text,"pid=%d tid=%ld phase=%s handle=%#x owners=%u opens=%u creator=%u consumer=%u consumer_open=%u",
        getpid(),syscall(SYS_gettid),phase,r.handle,r.owners,r.opens,r.creator,r.consumer,r.consumer_open);event(io,"REFERENCE_READBACK ",text);return 0;
}
/* Sony uses dynamic owner284/type2a temporary senders for 216B BB helpers.
 * These local virtual senders are explicit model identities, not CP task IDs. */
static int dmm(const struct full_imaging_io *io,unsigned int dst,unsigned int command,int consumer){
    unsigned int n=consumer?216u:152u,src=consumer?SOURCE:PEER;
    void *message=0;if(make(io,dst,n,&message))return -1;
    unsigned char *p=message;put16(p,command);if(consumer)put16(p+0x14,0x55);
    if(command==0x20){put32(p+4,PIN_CONTROL_UNIT);put32(p+0xc,0xffffffff);put16(p+0x16,1);}
    else {put32(p+8,state.buffer_handle);if(command==0x24)put32(p+0xc,0xffffffff);}
    if(set_source(io,message,src)){drop(io,dst,&message);return -1;}
    wire(io,"DMM_REQUEST ",src,DMM,message,n);
    struct pin_control_lease lease={0};int rc=-1;
    if(io->size(message)==n && io->source(message)==src && u16(p)==command && (!consumer || u16(p+0x14)==0x55)){
        if(!consumer && command==0x20 && u32(p+4)==PIN_CONTROL_UNIT && u32(p+0xc)==0xffffffff && u16(p+0x16)==1)
            rc=pin_control_allocate(PIN_CONTROL_UNIT,&lease);
        else if(u32(p+8)==state.buffer_handle){
            if(!consumer && command==0x25)rc=pin_control_close_creator(state.buffer_handle);
            else if(consumer && command==0x24 && u32(p+0xc)==0xffffffff && !u16(p+0x16))rc=pin_control_open_consumer(state.buffer_handle,PIN_CONTROL_UNIT,&lease);
            else if(consumer && command==0x25)rc=pin_control_close_consumer(state.buffer_handle);
            else if(consumer && command==0x23 && !u16(p+0x16))rc=pin_control_release_closed_consumer(state.buffer_handle);
        }
    }
    if(rc){drop(io,dst,&message);return -1;}
    pthread_mutex_lock(&mutex);
    if(command==0x20){state.buffer_handle=lease.handle;state.buffer_physical=lease.physical;state.buffer_cp_virtual=lease.cp_virtual;state.dmm_allocations++;}
    else if(command==0x25 && !consumer)state.dmm_creator_closes++;
    else if(command==0x24){state.buffer_opened=1;state.dmm_opens++;}
    else if(command==0x25){state.buffer_closed=1;state.dmm_consumer_closes++;}
    else if(command==0x23){state.buffer_freed=1;state.dmm_frees++;}
    pthread_mutex_unlock(&mutex);
    memset(p,0,n);put16(p,command|0x8000);if(consumer)put16(p+6,0x55);put32(p+0xc,state.buffer_handle);
    if(command==0x20)put32(p+0x10,PIN_CONTROL_UNIT);
    if(command==0x20 || command==0x24){put16(p+8,1);put64(p+0x18,lease.physical);put32(p+0x20,lease.bytes);}
    if(set_source(io,message,DMM)){drop(io,dst,&message);return -1;}
    wire(io,"DMM_REPLY ",DMM,src,message,n);
    int valid=io->size(message)==n && u16(p)==(command|0x8000) && !u16(p+2) && (!consumer || u16(p+6)==0x55) &&
        u32(p+0xc)==state.buffer_handle && io->source(message)==DMM;
    if(command==0x20 || command==0x24)valid=valid && u16(p+8)==1 && lease.bytes==PIN_CONTROL_SLOT_BYTES &&
        u64(p+0x18)==state.buffer_physical && u32(p+0x20)==lease.bytes && lease.slot<PIN_CONTROL_SLOTS &&
        lease.physical==PIN_CONTROL_PHYSICAL+lease.slot*PIN_CONTROL_SLOT_BYTES && lease.cp_virtual==PIN_CONTROL_CP_VIRTUAL+lease.slot*PIN_CONTROL_SLOT_BYTES;
    return drop(io,dst,&message) || !valid?-1:0;
}
static int consume_format(const struct full_imaging_io *io,unsigned int dst){
    void *internal=0;if(make(io,dst,36,&internal))return -1;
    pthread_mutex_lock(&mutex);int rc=full_infrabb_vef_format_internal(&state.format,internal,36);pthread_mutex_unlock(&mutex);
    if(rc || set_source(io,internal,PEER)){drop(io,dst,&internal);return -1;}
    wire(io,"COMMAND_REQUEST ",PEER,PEER,internal,36);
    if(io->size(internal)!=36 || io->source(internal)!=PEER){drop(io,dst,&internal);return -1;}
    pthread_mutex_lock(&mutex);rc=full_infrabb_vef_format_prepare(&state.format,internal,36);
    if(!rc){state.command_prepared=1;state.local_commands_inflight=1;}pthread_mutex_unlock(&mutex);
    if(drop(io,dst,&internal) || rc)return -1;
    event(io,"COMMAND_PREPARED ","frame=2002 command=f008 context=1 payload_bytes=20 copy_readback_equal=1 ordinal=0 command_state=0 known_bytes=20 old_ordinal1_preserved=1 original_CP_command_list_verified=0");
    struct full_vef_snapshot v;full_vef_snapshot(&v);
    unsigned char packet[80],readback[80];
    if(memcmp(v.pins[1].self,P,sizeof P) || memcmp(v.pins[1].peer,S,sizeof S))return -1;
    pthread_mutex_lock(&mutex);rc=full_infrabb_vef_format_execute(&state.format,v.pins[1].state,packet,sizeof packet);pthread_mutex_unlock(&mutex);
    if(rc || dmm(io,dst,0x20,0) || references(io,"allocated",1,1,1,0,0))return -1;
    unsigned long long digest=0;if(pin_control_write_payload(state.buffer_handle,packet,sizeof packet,&digest))return -1;
    pthread_mutex_lock(&mutex);state.buffer_fnv=digest;pthread_mutex_unlock(&mutex);
    char text[540];snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x physical=%#llx cp_virtual=%#x bytes=80 fnv64=%016llx header_word=0x02000000 key=0 payload_bytes=16 payload=01000000000000008007000038040000 original_CP_page_tables_verified=0 pixels_consumed=0",
        getpid(),syscall(SYS_gettid),state.buffer_handle,state.buffer_physical,state.buffer_cp_virtual,digest);event(io,"FORMAT_WRITTEN ",text);
    if(dmm(io,dst,0x25,0) || references(io,"creator-closed",1,0,1,0,0))return -1;
    void *notify=0;if(make(io,dst,80,&notify))return -1;
    unsigned char *p=notify;frame(p,80,0x104,1);
    for(unsigned int i=0;i<4;i++){put32(p+32+4*i,P[i]);put32(p+48+4*i,S[i]);}
    put32(p+64,PIN_CONTROL_UNIT);put32(p+68,state.buffer_handle);
    if(set_source(io,notify,PEER)){drop(io,dst,&notify);return -1;}
    wire(io,"FORMAT_NOTIFY ",PEER,SOURCE,notify,80);
    int valid=envelope(io,notify,80,0x104,1) && io->source(notify)==PEER && !u32(p) && u32(p+64)==PIN_CONTROL_UNIT &&
        u32(p+68)==state.buffer_handle && !u32(p+72) && !u32(p+76);
    for(unsigned int i=0;i<4;i++)valid=valid && u32(p+32+4*i)==P[i] && u32(p+48+4*i)==S[i];
    if(!valid || pin_control_transfer_creator(state.buffer_handle,PIN_CONTROL_UNIT)){drop(io,dst,&notify);return -1;}
    pthread_mutex_lock(&mutex);state.buffer_transferred=1;pthread_mutex_unlock(&mutex);
    if(references(io,"transferred",1,0,0,1,0) || dmm(io,dst,0x24,1) || references(io,"consumer-open",1,1,0,1,1) ||
       pin_control_read_consumer(state.buffer_handle,0,readback,sizeof readback) || memcmp(packet,readback,sizeof packet)){drop(io,dst,&notify);return -1;}
    pthread_mutex_lock(&mutex);rc=full_infrabb_vef_format_consume(&state.format,readback,sizeof readback);
    if(!rc)state.format_consumed=1;
    struct full_infrabb_vef_format format=state.format;pthread_mutex_unlock(&mutex);
    if(rc){event(io,"FORMAT_REFUSED ","same_format=0 original_mismatch_forward_unimplemented=1 buffer_retained=1 Close25=0 Free23=0 capture_verified=0");drop(io,dst,&notify);return -1;}
    snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x bytes=16 currentinfo_bytes=20 current_fnv64=%016llx command_fnv64=%016llx payload_fnv64=%016llx code=1 component=0 flags_u16=0 width=1920 height=1080 BB_IN1_state=0 mapped_backing_read=1 virtual_BB_table=public_raw_fe79ac original_CP_RAM_read=0 frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),state.buffer_handle,format.current_fnv,format.command_fnv,format.payload_fnv);event(io,"FORMAT_CONSUMED ",text);
    if(dmm(io,dst,0x25,1) || references(io,"consumer-closed",1,0,0,1,0) || dmm(io,dst,0x23,1)){drop(io,dst,&notify);return -1;}
    struct pin_control_references ended={0};struct pin_control_snapshot pool={0};pin_control_snapshot(&pool);
    if(pin_control_references(state.buffer_handle,&ended)==0 || pool.live || pool.faults || pool.allocations!=pool.releases){drop(io,dst,&notify);return -1;}
    event(io,"BUFFER_RETIRED ","owners=0 opens=0 live=0 creator_Close25=1 consumer_Close25=1 Free23_option0=1 share21=0 original_CP_executed=0 capture_verified=0");
    if(drop(io,dst,&notify))return -1;
    pthread_mutex_lock(&mutex);state.command_executed=1;state.local_commands_inflight=0;state.local_commands_returned=1;pthread_mutex_unlock(&mutex);
    event(io,"COMMAND_RETURNED ","context=3 type_table_entry=2 synchronous_execute=1 local_commands_inflight=0 local_commands_returned=1 old_command_owner_preserved=1 original_CP_command_list_verified=0 original_RTOS_timing_verified=0");return 0;
}
int full_infrabb_vef_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                        const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !result || !io)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    const unsigned char *in=request;unsigned int dst=u32(in),src=io->source(request);
    if(!is_pair(in))return 0;
    if(!envelope(io,request,64,1,2) || src!=dst || src>>28!=8 || !(src&0xfffffff)){
        event(io,"UNSUPPORTED ","only-full-key-BB-OUT1-to-VEF-IN1-owned-edge");*result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    pthread_mutex_unlock(&mutex);
    struct predecessors before;
    if(!dependencies(&before)){
        pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);
        event(io,"UNADMITTED ","predecessors_not_ready=1 requests=0 faults_unchanged=1 owner_not_reset=1");*result=-1021;return 1;
    }
    if(guard->reserve()){
        pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);
        event(io,"UNADMITTED ","resource_guard_busy=1 requests=0 faults_unchanged=1");*result=-1021;return 1;
    }
    /* Snapshots can reenter this module through foreign callbacks: never hold
     * our private mutex while taking another owner's snapshot or guard. */
    if(!dependencies(&before)){guard->release();*result=-1021;return 1;}
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
    pthread_mutex_lock(&mutex);state.peer_replies++;state.source_posthook_checked=1;state.source_posthook_no_format=1;pthread_mutex_unlock(&mutex);
    if(S[1]!=2)goto failed;
    event(io,"SOURCE_POSTHOOK ","raw=0xcec90 source_dir=2 returns_without_format=1 extra_sink_marker_writes=0 VEF_producer_separate=1");
    if(drop(io,dst,&forward) || drop(io,dst,&answer) || preserved(&before,1,0) || consume_format(io,dst) || preserved(&before,1,1))goto failed;
    pthread_mutex_lock(&mutex);state.predecessor_preserved=1;pthread_mutex_unlock(&mutex);
    if(make(io,dst,56,&final))goto failed;
    frame(final,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32((unsigned char *)final+32+4*i,S[i]);
    if(set_source(io,final,SOURCE) || !envelope(io,final,56,0x8001,2) || u32(final) ||
       u32((unsigned char *)final+48) || u32((unsigned char *)final+52) || preserved(&before,1,1))goto failed;
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
    if(pin_registry_connect_step(native_infrabb_registry(),full_vef_registry(),S,P,4) || preserved(&before,0,1))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_state=0 peer_state=0 source_pending=0 format_consumed=1 buffer_freed=1 unique_reply=1 prior_edges_NoMem_AB_failure_S0_preserved=1 original_CP_executed=0 frames_verified=0 capture_verified=0");goto done;
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
int full_infrabb_vef_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
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
        getpid(),syscall(SYS_gettid),destination,dst,reply,rc,faults,(unsigned int)(!rc));record("FULL_INFRABB_VEF_CONNECT_REPLY_FREE ",text);}
    *result=rc;return 1;
}
static int forward_ready(unsigned int handle,int bb){
    if(state.initialized!=1 || state.owner_pid!=(int)getpid() || state.clean_completion!=1 || state.connections!=1 ||
       state.ap_consumed!=1 || state.request_freed!=1 || state.reply_freed!=1 || state.queued!=1 || state.requests!=1 ||
       state.format_consumed!=1 || state.format.matches!=1 || state.buffer_freed!=1 || state.command_prepared!=1 ||
       state.command_executed!=1 || state.local_commands_returned!=1 || state.local_commands_inflight ||
       state.busy || state.faults || state.guard_held || state.live_reply || state.retained_request || state.retained_cleanup ||
       state.releasing_reply || current_request)return 0;
    for(unsigned int i=0;i<8;i++)if(messages[i])return 0;
    return bb?state.forwarded_vef_formats==1 && !state.forwarded_bb_formats && state.forwarded_format_handle==handle:
        !state.forwarded_vef_formats && !state.forwarded_bb_formats;
}
static int accept_forwarded(unsigned int handle,const struct full_imaging_io *io,int bb,int *changed){
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);int ready=forward_ready(handle,bb);pthread_mutex_unlock(&mutex);
    if(!ready)return -1021;
    struct pin_control_references refs={0};unsigned char packet[80];
    if(pin_control_references(handle,&refs) || refs.handle!=handle || refs.owners!=1 || refs.opens!=1 ||
       refs.creator || refs.consumer!=1 || refs.consumer_open!=1 ||
       pin_control_read_consumer(handle,0,packet,sizeof packet))return -1021;
    pthread_mutex_lock(&mutex);
    if(!forward_ready(handle,bb)){pthread_mutex_unlock(&mutex);return -1021;}
    int rc=bb?full_infrabb_vef_format_accept_forwarded_bb(&state.format,packet,sizeof packet,changed):
        full_infrabb_vef_format_accept_forwarded_vef(&state.format,packet,sizeof packet);
    if(rc){pthread_mutex_unlock(&mutex);return -1021;}
    if(bb)state.forwarded_bb_formats++;
    else{state.forwarded_vef_formats++;state.forwarded_format_handle=handle;}
    struct full_infrabb_vef_format format=state.format;pthread_mutex_unlock(&mutex);
    if(io && io->record){
        char current[41],expected[33],payload[33],text[900];
        for(unsigned int i=0;i<20;i++)snprintf(current+2*i,3,"%02x",format.current[i]);
        for(unsigned int i=0;i<16;i++){
            snprintf(expected+2*i,3,"%02x",format.expected[i]);snprintf(payload+2*i,3,"%02x",packet[64+i]);
        }
        snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x bytes=80 payload_bytes=16 mapped_backing_read=1 owners=1 opens=1 creator=0 consumer=1 consumer_open=1 changed=%d current_raw=%s expected_raw=%s payload_raw=%s current_fnv64=%016llx payload_fnv64=%016llx command_fnv64=%016llx fourth_payload_fnv64=%016llx original_CP_RAM_read=0 original_CP_page_tables_verified=0 frames_verified=0 capture_verified=0",
            getpid(),syscall(SYS_gettid),handle,*changed,current,expected,payload,format.current_fnv,
            bb?format.forwarded_bb_payload_fnv:format.forwarded_vef_payload_fnv,format.command_fnv,format.payload_fnv);
        io->record(bb?"FULL_INFRABB_VEF_FORWARD_BB_FORMAT_CONSUMED ":"FULL_INFRABB_VEF_FORWARD_VEF_FORMAT_CONSUMED ",text);
    }
    return 0;
}
int full_infrabb_vef_connection_accept_forwarded_vef_format(unsigned int handle,const struct full_imaging_io *io){
    int changed=0;return accept_forwarded(handle,io,0,&changed);
}
int full_infrabb_vef_connection_accept_forwarded_bb_format(unsigned int handle,const struct full_imaging_io *io,int *changed){
    if(!changed)return -1021;
    *changed=0;return accept_forwarded(handle,io,1,changed);
}

