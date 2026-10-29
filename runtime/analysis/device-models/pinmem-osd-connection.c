/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pinmem-osd-connection.h"
#include "pinmem-drawinfo-connection.h"
#include "scalar-device.h"
#include "adf-device.h"
#include "adf-connection.h"
#include "vef-pinmem-control-connection.h"
#include "vef-pinmem-input-connection.h"
#include "imaging-pin-connection.h"
#include "imaging-control-connection.h"
#include "imaging-adf-connection.h"
#include "infrabb-vef-connection.h"
#include "infrabb-vef-control-connection.h"
#include "vef-path-device.h"
#include "pin-connection.h"
#include "pin-buffer-owner.h"
#include "pinmem-device.h"
#include "pin-registry-core.h"
#include "adf-set-input-device.h"
#include "adf-set-output-device.h"
#include "adf-aip-commands.h"
#include "bb-set-mode-device.h"
#include "../drawinfo-registry.h"
#include "../osdpin-registry.h"
#include "../infrabb-registry.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#define SOURCE FULL_OSD_PINMEM_SID
#define PEER FULL_OSD_PEER_SID
#define DMM 0x9059000eu
#define TOKEN 0x4f534406u
#define MESSAGE_SLOTS 8u
static const unsigned int S[4]={1,3,0,SOURCE},P[4]={1,3,0,PEER};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static struct full_pinmem_osd_connection_snapshot state;
static struct {void *pointer;unsigned int owner;} messages[MESSAGE_SLOTS];
static void *current_request;
static long sender;
static _Alignas(256) unsigned char backing[FULL_OSD_POOL_BYTES];
static struct {
    unsigned char parameter[12],request[64],answer_wire[72];
    void *answer,*body;
    unsigned int source,destination,token;
} event6;
struct history {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot second;
    struct full_imaging_adf_connection_snapshot third;
    struct full_infrabb_vef_connection_snapshot fourth;
    struct full_infrabb_vef_control_connection_snapshot fifth;
    struct full_vef_pinmem_input_connection_snapshot sixth;
    struct full_vef_pinmem_control_connection_snapshot seventh;
    struct scalar_connection_snapshot eighth,ninth,tenth;
    struct full_vef_path_snapshot path;
    struct pin_connection_snapshot old_pin;
    struct full_adf_proc_snapshot proc;
    struct full_adf_set_input_snapshot input;
    struct full_adf_set_output_snapshot output;
    struct full_bb_set_mode_snapshot bb;
    struct pin_control_snapshot pool;
    struct full_vef_snapshot imaging,bb_registry,vef,pinmem,adf,scalar,drawinfo,osdpin;
};
static int pid_matches(void){return atomic_load(&process_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static unsigned long long u64(const unsigned char *p){return u32(p)|(unsigned long long)u32(p+4)<<32;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void put64(unsigned char *p,unsigned long long v){for(unsigned int i=0;i<8;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned long long hash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;return h;
}
static unsigned int sid(unsigned int side){return side==FULL_OSD_PEER_SIDE?PEER:SOURCE;}
static unsigned int opposite(unsigned int side){return side==FULL_OSD_PEER_SIDE?FULL_OSD_PINMEM_SIDE:FULL_OSD_PEER_SIDE;}
static int healthy(void){pthread_mutex_lock(&mutex);int ok=!state.faults;pthread_mutex_unlock(&mutex);return ok;}
static void record(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[96];snprintf(tag,sizeof tag,"FULL_PINMEM_OSD_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *text){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);record(io,"FAULT ",text);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[305],text[1000];
    for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    raw[2*n]=0;snprintf(text,sizeof text,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s virtual_local_transport=1 original_CP_executed=0 original_CP_pages_verified=0 frames_verified=0 capture_verified=0",getpid(),syscall(SYS_gettid),src,dst,pointer,n,raw);
    record(io,kind,text);
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *p,unsigned int n){wire_from(io,kind,src,dst,p,p,n);}
static void frame(unsigned char *p,unsigned int n,unsigned int op,unsigned int flags){
    memset(p,0,n);put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,op);put16(p+28,n-24);put16(p+30,flags);
}
static void pair(unsigned char *p){for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}}
static int is_pair(const unsigned char *p){for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;return 1;}
static int canonical(const struct full_imaging_io *io,void *p,const unsigned char *expected,unsigned int n,unsigned int source){
    return p && io->size(p)==n && io->source(p)==source && !memcmp(p,expected,n) && healthy();
}
static void forget(void *p){for(unsigned int i=0;i<MESSAGE_SLOTS;i++)if(messages[i].pointer==p){messages[i].pointer=0;break;}}
static int drop(const struct full_imaging_io *io,unsigned int owner,void **p){
    if(!*p)return 0;
    void *pointer=*p;int rc=io->release(owner,pointer);
    pthread_mutex_lock(&mutex);if(rc){state.faults++;state.clean_completion=0;if(!state.retained_cleanup)state.retained_cleanup=pointer;}else forget(pointer);pthread_mutex_unlock(&mutex);
    char text[200];snprintf(text,sizeof text,"owner=%#x pointer=%p rc=%d pool_references_released=0",owner,pointer,rc);record(io,rc?"CLEANUP_FAULT ":"INTERNAL_FREE ",text);*p=0;return rc;
}
static int make(const struct full_imaging_io *io,unsigned int owner,unsigned int n,void **out){
    *out=0;int rc=io->allocate(owner,out,n,1);
    pthread_mutex_lock(&mutex);unsigned int slot=MESSAGE_SLOTS;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<MESSAGE_SLOTS;i++){if(messages[i].pointer && messages[i].pointer==*out)alias=1;if(!messages[i].pointer && slot==MESSAGE_SLOTS)slot=i;}
    if(alias || (*out && slot==MESSAGE_SLOTS)){pthread_mutex_unlock(&mutex);*out=0;fail(io,"allocator-returned-live-message-or-capacity");return -1;}
    if(*out){messages[slot].pointer=*out;messages[slot].owner=owner;}
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,owner,out);return -1;}
    memset(*out,0,n);return healthy()?0:-1;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int source){io->set_source(p,source);return io->source(p)==source && healthy()?0:-1;}
static void history_snapshot(struct history *h){
    memset(h,0,sizeof *h);full_imaging_pin_connection_snapshot(&h->first);full_imaging_control_connection_snapshot(&h->second);
    full_imaging_adf_connection_snapshot(&h->third);full_infrabb_vef_connection_snapshot(&h->fourth);full_infrabb_vef_control_connection_snapshot(&h->fifth);
    full_vef_pinmem_input_connection_snapshot(&h->sixth);full_vef_pinmem_control_connection_snapshot(&h->seventh);
    full_scalar_connection_snapshot(&h->eighth);full_adf_connection_snapshot(&h->ninth);full_pinmem_drawinfo_connection_snapshot(&h->tenth);
    full_vef_path_snapshot(&h->path);full_pin_connection_snapshot(&h->old_pin);full_adf_proc_snapshot(&h->proc);
    full_adf_set_input_snapshot(&h->input);full_adf_set_output_snapshot(&h->output);full_bb_set_mode_snapshot(&h->bb);pin_control_snapshot(&h->pool);
    native_infraimaging_snapshot(&h->imaging);native_infrabb_snapshot(&h->bb_registry);full_vef_snapshot(&h->vef);
    full_pinmem_snapshot(&h->pinmem);full_adf_snapshot(&h->adf);full_scalar_snapshot(&h->scalar);native_drawinfo_snapshot(&h->drawinfo);native_osdpin_snapshot(&h->osdpin);
}
#define CLEAN(x) ((x).owner_pid==getpid() && (x).initialized && (x).clean_completion && (x).ap_consumed==1 && (x).connections==1 && (x).requests==1 && (x).request_freed && (x).reply_freed && !(x).busy && !(x).guard_held && !(x).faults && !(x).live_reply && !(x).retained_request && !(x).retained_messages && !(x).releasing_reply)
static int scalar_clean(const struct scalar_connection_snapshot *p){
    return CLEAN(*p) && p->native_guarded && p->queued==1 && p->native_reply_frees==1 && p->waiter_frees==1 &&
        !p->pending_event6 && p->event6_consumed && !p->event6_inflight && !p->retained_cleanup;
}
static int quiet(const struct full_vef_snapshot *p,unsigned int owner,unsigned int count){
    return p->initialized && p->owner_sid==owner && p->registry_objects==count && p->queries && !p->pending && !p->faults && !p->live_replies && !p->retained_request && !p->retained_reply;
}
static int cold(const struct full_vef_pin *p,const unsigned int *key){static const unsigned int empty[4]={0xff,0xff,0,0};return p->state==1 && !memcmp(p->self,key,sizeof p->self) && !memcmp(p->peer,empty,sizeof empty);}
static int dependencies(struct history *h){
    static const unsigned int cache[5]={1,1,1920,1080,3};
    static const unsigned char current[20]={1,0,0,0,0,0,0,0,1,1,3,0,0x80,7,0,0,0x38,4,0,0};
    static const unsigned char initial[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0};
    static const unsigned char payload[16]={1,1,3,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    static const unsigned char historical[16]={1,0,0,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};
    history_snapshot(h);struct full_osd_pool_snapshot pool;full_osd_pool_snapshot(&pool);
    return CLEAN(h->first) && CLEAN(h->second) && CLEAN(h->third) && CLEAN(h->fourth) && CLEAN(h->fifth) && CLEAN(h->sixth) && CLEAN(h->seventh) &&
        scalar_clean(&h->eighth) && scalar_clean(&h->ninth) && scalar_clean(&h->tenth) && !pool.initialized && !pool.live && !pool.faults &&
        !h->second.retained_cleanup && !h->third.retained_cleanup && !h->fourth.retained_cleanup && !h->fifth.retained_cleanup && !h->sixth.retained_cleanup && !h->seventh.retained_cleanup &&
        h->first.format.initialized && h->first.format.consumed==2 && !memcmp(h->first.format.cache,cache,sizeof cache) && h->first.forwarded_formats==1 && h->first.format.payload_fnv64==hash(payload,16) &&
        !memcmp(h->fourth.format.current,current,20) && !memcmp(h->fourth.format.expected,payload,16) && !memcmp(h->fourth.format.command_current,initial,20) &&
        h->fourth.format.current_fnv==hash(current,20) && h->fourth.format.command_fnv==hash(initial,20) && h->fourth.format.payload_fnv==hash(historical,16) &&
        h->fourth.forwarded_vef_formats==1 && h->fourth.forwarded_bb_formats==1 && h->sixth.dmm_requests==9 && h->sixth.reference_readbacks==9 && h->sixth.buffer_freed &&
        h->old_pin.started && h->old_pin.connections==1 && !h->old_pin.faults && h->old_pin.format_consumed && h->old_pin.buffer_released &&
        h->old_pin.format_current.ordinal==1 && h->old_pin.format_current.code==1 && !h->old_pin.format_current.component && !h->old_pin.format_current.encoded_flags &&
        h->old_pin.format_current.width==1920 && h->old_pin.format_current.height==1080 &&
        h->input.owner_pid==getpid() && h->input.configured && h->input.clean_completion && h->input.ap_consumed && !h->input.software_s && h->input.ab_failures==1 && !h->input.ab_register_writes && h->input.first_task_status==FULL_ADF_AIP_TASK_ERROR &&
        h->pool.bound && !h->pool.live && !h->pool.faults && h->pool.allocations==h->pool.releases &&
        quiet(&h->pinmem,SOURCE,13) && quiet(&h->osdpin,PEER,1) && cold(&h->pinmem.pins[8],S) && cold(&h->osdpin.pins[0],P) &&
        pin_registry_key_get_retired(full_pinmem_registry(),S) && pin_registry_key_get_retired(native_osdpin_registry(),P);
}
#undef CLEAN
static int preserved(const struct history *before,unsigned int pending){
    struct history after;history_snapshot(&after);
    if(after.pinmem.pending!=pending || after.osdpin.pending || after.pinmem.pins[8].state || after.osdpin.pins[0].state ||
       memcmp(after.pinmem.pins[8].self,S,sizeof S) || memcmp(after.pinmem.pins[8].peer,P,sizeof P) ||
       memcmp(after.osdpin.pins[0].self,P,sizeof P) || memcmp(after.osdpin.pins[0].peer,S,sizeof S))return -1;
    after.pinmem.pins[8]=before->pinmem.pins[8];after.pinmem.pending=before->pinmem.pending;after.osdpin.pins[0]=before->osdpin.pins[0];
    return memcmp(&after,before,sizeof after)?-1:0;
}
static int same_mapping(const struct full_osd_mapping *a,const struct full_osd_mapping *b){
    return a->handle==b->handle && a->unit==b->unit && a->extent==b->extent && a->generation==b->generation && a->physical==b->physical && a->cp_alias==b->cp_alias;
}
static int references(unsigned int handle,unsigned int side,unsigned int op,struct full_osd_mapping *out){
    struct full_osd_pool_snapshot pool;full_osd_pool_snapshot(&pool);
    if(pool.owner_pid!=(unsigned int)getpid() || !pool.initialized || pool.faults || pool.original_allocator_capacity_verified || pool.original_cp_pages_verified)return -1;
    for(unsigned int i=0;i<FULL_OSD_POOL_SLOTS;i++){
        const struct full_osd_pool_slot_snapshot *s=&pool.slots[i];
        if(!s->live || s->handle!=handle)continue;
        unsigned int creator=op==0x24?opposite(side):side;
        if(s->creator_side!=creator || s->creator_open!=1 || s->owners!=(op==0x20?1u:2u) ||
           s->open_count!=(op==0x24?2u:1u) || s->consumer_open!=(op==0x24) ||
           s->consumer_side!=(op==0x20?0u:opposite(creator)) || full_osd_pool_mapping(side,handle,out) || !same_mapping(out,&s->mapping))return -1;
        pthread_mutex_lock(&mutex);state.reference_readbacks++;pthread_mutex_unlock(&mutex);return 0;
    }
    return -1;
}
/* Finite owned CP-local request consumer. Unknown producer bytes remain a5.
 * Real OSAL allocation/free uses the AP caller's storage lease; replySID/token
 * are independent virtual CP identities, never an AP/kernel alias. Internal
 * CP messages are decoded locally, never sent to unregistered OSAL queues. */
static int dmm(const struct full_imaging_io *io,unsigned int side,unsigned int op,unsigned int bytes,unsigned int *handle,struct full_osd_mapping *mapping){
    unsigned int sequence;pthread_mutex_lock(&mutex);sequence=state.dmm_requests+1;pthread_mutex_unlock(&mutex);
    unsigned int local=0x0061003cu+(sequence-1)*4u,token=0x4f00u+sequence,storage_owner=state.reply_destination;
    void *request=0,*reply=0;unsigned char expected[152],answer[152];int rc=-1;
    if((bytes!=40 && bytes!=152) || (op!=0x20 && op!=0x21 && op!=0x24) || make(io,storage_owner,bytes,&request))goto done;
    memset(expected,FULL_OSD_POOL_UNKNOWN_BYTE,bytes);put16(expected,op);
    if(op!=0x24)put32(expected+4,FULL_OSD_POOL_UNIT);
    if(op!=0x20)put32(expected+8,*handle);
    put32(expected+12,op==0x24?0u:0xffffffffu);put32(expected+16,local);put16(expected+20,token);put16(expected+22,op==0x20?1u:0u);
    memcpy(request,expected,bytes);if(set_source(io,request,sid(side)))goto done;
    wire(io,"DMM_REQUEST ",sid(side),DMM,request,bytes);
    if(!canonical(io,request,expected,bytes,sid(side)))goto done;
    const unsigned char *q=request;
    if(u16(q)!=op || (op!=0x24 && u32(q+4)!=FULL_OSD_POOL_UNIT) || (op!=0x20 && u32(q+8)!=*handle) ||
       u32(q+12)!=(op==0x24?0u:0xffffffffu) || u32(q+16)!=local || u16(q+20)!=token || u16(q+22)!=(op==0x20?1u:0u))goto done;
    pthread_mutex_lock(&mutex);state.dmm_requests++;pthread_mutex_unlock(&mutex);
    if(op==0x20?full_osd_pool_allocate(side,handle):op==0x21?full_osd_pool_share(side,*handle):full_osd_pool_open(side,*handle))goto done;
    if(full_osd_pool_mapping(side,*handle,mapping))goto done;
    if(make(io,storage_owner,bytes,&reply))goto done;
    memset(answer,FULL_OSD_POOL_UNKNOWN_BYTE,bytes);memset(answer,0,40);put16(answer,op|0x8000);put16(answer+6,token);put16(answer+8,1);put32(answer+12,*handle);
    if(op!=0x24)put32(answer+16,FULL_OSD_POOL_UNIT);
    put64(answer+24,mapping->physical);put32(answer+32,mapping->extent);memcpy(reply,answer,bytes);
    if(set_source(io,reply,DMM))goto done;
    wire(io,"DMM_REPLY ",DMM,local,reply,bytes);
    if(!canonical(io,reply,answer,bytes,DMM))goto done;
    const unsigned char *r=reply;struct full_osd_mapping actual;
    if(u16(r)!=(op|0x8000) || u16(r+2) || u16(r+6)!=token || u16(r+8)!=1 || u32(r+12)!=*handle ||
       u64(r+24)!=mapping->physical || u32(r+32)!=mapping->extent || references(*handle,side,op,&actual) || !same_mapping(mapping,&actual))goto done;
    pthread_mutex_lock(&mutex);state.dmm_replies++;state.allocations+=op==0x20;state.shares+=op==0x21;state.opens+=op==0x24;pthread_mutex_unlock(&mutex);rc=0;
done:
    if(request && drop(io,storage_owner,&request))rc=-1;
    if(reply && drop(io,storage_owner,&reply))rc=-1;
    return healthy()?rc:-1;
}
static int create_format(const struct full_imaging_io *io,unsigned int bank,unsigned int index,unsigned int tag,unsigned int peer_handle){
    unsigned int side=bank?FULL_OSD_PINMEM_SIDE:FULL_OSD_PEER_SIDE,h=0,used=0;struct full_osd_mapping mapping;
    unsigned char bytes[256],known[256],readback[256],read_known[256];
    if(dmm(io,side,0x20,bank?152:40,&h,&mapping))return -1;
    pthread_mutex_lock(&mutex);state.resources[bank][index].handle=h;state.resources[bank][index].mapping=mapping;state.resources[bank][index].creator_side=side;pthread_mutex_unlock(&mutex);
    if(tag==FULL_OSD_FORMAT_TAG101?full_osd_format_build_completion101(peer_handle,bytes,known,sizeof bytes,&used):full_osd_format_build_initial(tag,bytes,known,sizeof bytes,&used))return -1;
    if(full_osd_pool_write(side,h,0,bytes,known,sizeof bytes) || full_osd_pool_read(side,h,0,readback,read_known,sizeof bytes) || memcmp(bytes,readback,sizeof bytes) || memcmp(known,read_known,sizeof known))return -1;
    unsigned int count=0;for(unsigned int i=0;i<256;i++)count+=read_known[i];
    pthread_mutex_lock(&mutex);struct full_pinmem_osd_resource *r=&state.resources[bank][index];r->tag=tag;r->used=used;r->known_bytes=count;r->owners=r->opens=1;r->bytes_fnv=hash(readback,256);r->known_fnv=hash(read_known,256);pthread_mutex_unlock(&mutex);
    char text[400];snprintf(text,sizeof text,"bank=%u ordinal=%u handle=%#x unit=%#x extent=256 physical=%#llx cp_alias=%#x used=%u known=%u fnv=%016llx known_fnv=%016llx pixels=0",bank,index,h,FULL_OSD_POOL_UNIT,mapping.physical,mapping.cp_alias,used,count,hash(bytes,256),hash(known,256));record(io,"FORMAT_WRITTEN ",text);return healthy()?0:-1;
}
static int notify(const struct full_imaging_io *io,unsigned int bank,unsigned int index,struct full_osd_format_state *format){
    unsigned int producer=bank?FULL_OSD_PINMEM_SIDE:FULL_OSD_PEER_SIDE,consumer=opposite(producer);
    unsigned int h=state.resources[bank][index].handle,owner=state.reply_destination;
    struct full_osd_mapping mapping,opened;void *notice=0;unsigned char expected[80],known[80];int rc=-1;
    if(dmm(io,producer,0x21,bank?152:40,&h,&mapping) || make(io,owner,80,&notice))goto done;
    if(full_osd_notice_build(producer,h,expected,known,sizeof expected))goto done;
    memcpy(notice,expected,sizeof expected);if(set_source(io,notice,sid(producer)))goto done;
    wire(io,bank?"SOURCE_NOTIFY ":"PEER_NOTIFY ",sid(producer),sid(consumer),notice,80);
    if(!canonical(io,notice,expected,80,sid(producer)) || full_osd_notice_validate(producer,io->source(notice),sid(consumer),notice,80,&opened) || !same_mapping(&mapping,&opened))goto done;
    pthread_mutex_lock(&mutex);if(bank)state.source_notifications++;else state.peer_notifications++;pthread_mutex_unlock(&mutex);
    if(dmm(io,consumer,0x24,bank?40:152,&h,&opened) || !same_mapping(&mapping,&opened))goto done;
    if(bank){
        if(full_osd_format_consume_opened_notice(format,SOURCE,PEER,notice,80,&opened) || format->last_handler_status || format->last_outer_status || format->unsupported_work)goto done;
        pthread_mutex_lock(&mutex);state.format=*format;pthread_mutex_unlock(&mutex);
    }else{
        unsigned char data[256],mask[256];struct full_osd_format_view view;
        if(full_osd_pool_read(consumer,h,0,data,mask,256) || full_osd_format_parse(data,mask,256,&view) || view.tag || view.payload_bytes!=64)goto done;
        for(unsigned int i=0;i<64;i++)if(view.payload[i] || view.known[i]!=1)goto done;
        struct full_osd_format_plane plane={.mapping=opened,.handle=h,.ordinal=index,.tag=0,.payload_bytes=64,.reloads=1};
        memcpy(plane.payload,view.payload,64);memcpy(plane.known,view.known,64);
        pthread_mutex_lock(&mutex);state.source_outputs[index]=plane;pthread_mutex_unlock(&mutex);
    }
    pthread_mutex_lock(&mutex);state.notifications_consumed++;state.consumer_reads++;state.resources[bank][index].owners=state.resources[bank][index].opens=2;pthread_mutex_unlock(&mutex);
    char text[300];snprintf(text,sizeof text,"bank=%u ordinal=%u handle=%#x actual_mapping_read=1 owners=2 opens=2 creator_open=1 consumer_open=1 retained=1 optional_diagnostic_does_not_gate=1 capture_verified=0",bank,index,h);record(io,"FORMAT_CONSUMED ",text);rc=0;
done:
    if(notice && drop(io,owner,&notice))rc=-1;
    return healthy()?rc:-1;
}
static int enqueue_event6(const struct full_imaging_io *io,void *answer,const unsigned char expected[72]){
    if(!canonical(io,answer,expected,72,PEER))return -1;
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.busy || state.event6_enqueued || state.phase!=1 || state.wait_primary!=6 || state.pending_event6!=1){pthread_mutex_unlock(&mutex);return -1;}
    memset(&event6,0,sizeof event6);event6.answer=answer;event6.body=(unsigned char *)answer+24;event6.source=PEER;event6.destination=SOURCE;event6.token=TOKEN;put32(event6.parameter,TOKEN);
    memcpy(event6.request,state.saved_request,64);memcpy(event6.answer_wire,expected,72);state.context_kind=2;state.event6_enqueued=1;state.event6_token=TOKEN;pthread_mutex_unlock(&mutex);
    record(io,"EVENT6_ENQUEUED ","event=6 parameter_bytes=12 token=0x4f534406 token_policy=owned-answer-plus24-map saved_original_request_bytes=64 queue_phase=1 wait_primary=6 keep_pending=1 context_kind=2 original_RTOS_scheduling_verified=0");return healthy()?0:-1;
}
static int consume_event6(const struct full_imaging_io *io){
    unsigned char parameter[12]={0},saved[64],expected[72];void *answer,*body,*request;unsigned int dst;put32(parameter,TOKEN);
    pthread_mutex_lock(&mutex);
    int valid=state.busy && !state.faults && state.pending_event6==1 && state.event6_enqueued==1 && !state.event6_inflight && !state.event6_consumed && state.context_kind==2 && state.phase==1 && state.wait_primary==6 && !state.wait_secondary && state.keep_pending==1;
    if(!valid){pthread_mutex_unlock(&mutex);return -1;}
    state.event6_inflight=1;answer=event6.answer;body=event6.body;request=current_request;dst=state.reply_destination;
    memcpy(saved,event6.request,64);memcpy(expected,event6.answer_wire,72);
    valid=event6.token==TOKEN && !memcmp(event6.parameter,parameter,12) && event6.source==PEER && event6.destination==SOURCE && !memcmp(saved,state.saved_request,64);pthread_mutex_unlock(&mutex);
    valid=valid && body==(unsigned char *)answer+24 && canonical(io,request,saved,64,dst) && is_pair(saved) && canonical(io,answer,expected,72,PEER) && is_pair(expected) &&
        !memcmp(saved+48,(unsigned char *)body+24,sizeof P) && !u32((unsigned char *)body+40) && !u32((unsigned char *)body+44);
    if(valid)valid=!pin_registry_connect_step(full_pinmem_registry(),native_osdpin_registry(),S,P,3);
    pthread_mutex_lock(&mutex);state.event6_inflight=0;
    if(valid){state.event6_consumed=1;state.pending_event6=0;state.event6_token_verified=state.event6_peer_verified=1;state.context_kind=0;state.wait_primary=state.wait_secondary=state.keep_pending=0;event6.answer=event6.body=0;}
    pthread_mutex_unlock(&mutex);
    if(!valid)return -1;
    record(io,"EVENT6_CONSUMED ","parameter_bytes=12 actual_parameter_read=1 token_body_binding_verified=1 saved_peer_u32_fields_verified=4 source_complete_raw=0x5839a6 source_state=0 status=0 tail=0 original_RTOS_scheduling_verified=0");return healthy()?0:-1;
}
static int source_post(const struct full_imaging_io *io,struct full_osd_format_state *format){
    for(unsigned int bank=2;bank<4;bank++)for(unsigned int i=0;i<4;i++)
        if(create_format(io,bank,i,bank==2?FULL_OSD_FORMAT_TAG100:FULL_OSD_FORMAT_TAG102,0) || notify(io,bank,i,format))return -1;
    if(format->notices!=12 || format->new100!=4 || format->new101!=4 || format->new102!=4 || format->retained_opens!=12 || !format->ready ||
       format->readiness_transitions!=1 || format->readiness_post_pending!=1 || format->last_handler_status || format->last_outer_status ||
       format->unsupported_work || format->fifo_submissions || format->output_callbacks || format->completion_callbacks)return -1;
    /* ae9ec8 bookkeeping and outer 46b06c finish only the zero-mask branch;
     * the optional 08000009 diagnostic is not graphics/GPE readiness. */
    for(unsigned int i=0;i<4;i++)if(!format->outputs[i].selection_mask_known || format->outputs[i].selection_mask || u16(format->incoming101[i].payload+8) || u16(format->incoming102[i].payload+4))return -1;
    format->readiness_post_pending=0;
    unsigned char rows[5],row_known[5];unsigned int h;
    pthread_mutex_lock(&mutex);memcpy(rows,state.source_row_enabled,5);memcpy(row_known,state.source_row_known,5);h=state.resources[2][0].handle;pthread_mutex_unlock(&mutex);
    if(full_osd_format_apply_inactive100(h,rows,row_known))return -1;
    unsigned char data[256],known[256];struct full_osd_format_view view;
    if(full_osd_pool_read(FULL_OSD_PINMEM_SIDE,h,0,data,known,256) || full_osd_format_parse(data,known,256,&view) || u32(view.payload) || u32(format->incoming100[0].payload)!=1 || format->reload100)return -1;
    pthread_mutex_lock(&mutex);state.format=*format;state.metadata_ready=1;state.readiness_post_checks=1;state.source_post_updated=1;state.selected_tag100=h;
    state.selected_backing_count=0;state.selected_cached_count=1;state.diagnostics_optional_skipped=1;pthread_mutex_unlock(&mutex);
    record(io,"SOURCE_POST ","source_raw=0x5d61a2 inactive_rows=5 selected_tag100_backing_count=0 OSD_cached_count=1 repeated_notice=0 extra_share=0 extra_open=0 metadata_ready=1 graphics_ready=0 GPE_ready=0 optional_diagnostic_skipped=1");return healthy()?0:-1;
}
static int final_readback(const struct full_imaging_io *io){
    struct full_osd_pool_snapshot pool;full_osd_pool_snapshot(&pool);
    if(pool.owner_pid!=(unsigned int)getpid() || pool.live!=16 || pool.allocations!=16 || pool.shares!=16 || pool.opens!=16 || pool.releases || pool.faults ||
       pool.original_allocator_capacity_verified || pool.original_cp_pages_verified)return -1;
    unsigned int seen[16]={0};
    for(unsigned int bank=0;bank<4;bank++)for(unsigned int i=0;i<4;i++){
        struct full_pinmem_osd_resource r=state.resources[bank][i];unsigned int side=bank?FULL_OSD_PINMEM_SIDE:FULL_OSD_PEER_SIDE,used=0;
        unsigned char expected[256],mask[256],data[256],known[256],cached[128];struct full_osd_mapping mapping;
        if(bank==1?full_osd_format_build_completion101(state.resources[0][i].handle,expected,mask,256,&used):full_osd_format_build_initial(r.tag,expected,mask,256,&used))return -1;
        memcpy(cached,expected+64,used-64);
        const struct full_osd_format_plane *plane=bank==0?&state.format.outputs[i]:bank==1?&state.format.incoming101[i]:bank==2?&state.format.incoming100[i]:&state.format.incoming102[i];
        if(plane->handle!=r.handle || plane->ordinal!=i || plane->tag!=r.tag || plane->payload_bytes!=used-64 || plane->reloads!=1 ||
           !same_mapping(&plane->mapping,&r.mapping) || memcmp(plane->payload,cached,used-64) || memcmp(plane->known,mask+64,used-64))return -1;
        if(!bank){const struct full_osd_format_plane *source=&state.source_outputs[i];
            if(source->handle!=r.handle || source->ordinal!=i || source->tag || source->payload_bytes!=64 || source->reloads!=1 ||
               !same_mapping(&source->mapping,&r.mapping) || memcmp(source->payload,cached,64) || memcmp(source->known,mask+64,64))return -1;}
        if(bank==2 && i==0)put32(expected+64,0);
        if(full_osd_pool_mapping(side,r.handle,&mapping) || !same_mapping(&mapping,&r.mapping) || full_osd_pool_read(opposite(side),r.handle,0,data,known,256) ||
           memcmp(data,expected,256) || memcmp(known,mask,256) || r.used!=used)return -1;
        unsigned int found=0;
        for(unsigned int j=0;j<16;j++)if(pool.slots[j].handle==r.handle && pool.slots[j].live){
            const struct full_osd_pool_slot_snapshot *s=&pool.slots[j];
            if(seen[j]++ || s->owners!=2 || s->open_count!=2 || s->creator_open!=1 || s->consumer_open!=1 || s->creator_side!=side || s->consumer_side!=opposite(side) || !same_mapping(&s->mapping,&mapping))return -1;
            found=1;
        }
        if(!found)return -1;
        pthread_mutex_lock(&mutex);state.resources[bank][i].bytes_fnv=hash(data,256);state.resources[bank][i].known_fnv=hash(known,256);pthread_mutex_unlock(&mutex);
    }
    pthread_mutex_lock(&mutex);int ok=state.dmm_requests==48 && state.dmm_replies==48 && state.reference_readbacks==48 && state.allocations==16 && state.shares==16 && state.opens==16 &&
        state.peer_notifications==4 && state.source_notifications==12 && state.notifications_consumed==16 && state.consumer_reads==16 && state.metadata_ready && state.source_post_updated;
    if(ok)state.canonical_references=1;
    pthread_mutex_unlock(&mutex);
    if(!ok)return -1;
    record(io,"RESOURCE_READBACK ","live=16 owners_each=2 opens_each=2 DMM_requests=48 DMM_replies=48 reference_readbacks=48 peer_notices=4 source_notices=12 exact_backing_and_known_masks_verified=1 selected_backing_count=0 cached_count=1 original_allocator_capacity_verified=0 original_CP_pages_verified=0 frames_verified=0 capture_verified=0");return healthy()?0:-1;
}
int full_pinmem_osd_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&process_pid,&expected,pid);if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);
    if(!state.initialized){
        state.initialized=1;state.owner_pid=pid;memset(state.local_pairs,0xff,sizeof state.local_pairs);
        /* Source constructor clears the five +fc row-enable bytes. */
        memset(state.source_row_known,1,sizeof state.source_row_known);
    }
    pthread_mutex_unlock(&mutex);return 0;
}
void full_pinmem_osd_connection_snapshot(struct full_pinmem_osd_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){memset(out,0,sizeof *out);return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;for(unsigned int i=0;i<MESSAGE_SLOTS;i++)out->retained_messages+=messages[i].pointer!=0;
    out->saved_request_fnv=hash(state.saved_request,64);memcpy(out->event6_parameter,event6.parameter,12);out->event6_parameter_fnv=hash(event6.parameter,12);out->event6_answer=event6.answer;out->event6_body=event6.body;pthread_mutex_unlock(&mutex);
    full_osd_pool_snapshot(&out->pool);
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);record(io,"UNADMITTED ",reason);*result=-1021;return 1;}
static int dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,const struct full_adf_proc_guard *guard,int enabled,int native,int *result){
    if(enabled!=1 || destination!=SOURCE || !io || !result)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->set_source || !io->send || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64 || !is_pair(request))return 0;
    unsigned int d=u32(request);unsigned char expected_request[64];frame(expected_request,64,1,2);pair(expected_request);put32(expected_request,d);memcpy(expected_request+20,(unsigned char *)request+20,4);
    if(d>>28!=8 || !(d&0xfffffff) || !canonical(io,request,expected_request,64,d)){*result=-1021;return 1;}
    if(!native)return unadmitted(io,result,"native-guarded-only=1 caller-owned-request=1");
    pthread_mutex_lock(&mutex);int ready=state.initialized && !state.started && !state.busy && !state.faults && !state.live_reply;pthread_mutex_unlock(&mutex);
    if(!ready)return unadmitted(io,result,"owner-not-cold-or-transaction-started requests_unchanged=1");
    struct history before;if(!dependencies(&before))return unadmitted(io,result,"first10-AP-or-exact-retired-Get-or-pool-not-ready requests=0 faults_unchanged=1");
    if(guard->reserve())return unadmitted(io,result,"resource-guard-busy requests=0 faults_unchanged=1");
    pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    if(!dependencies(&before)){
        guard->release();pthread_mutex_lock(&mutex);state.guard_held=0;pthread_mutex_unlock(&mutex);
        return unadmitted(io,result,"guarded-prerequisite-readback-failed requests=0 faults_unchanged=1");
    }
    pthread_mutex_lock(&mutex);
    if(state.started || state.busy || state.faults || state.live_reply){
        pthread_mutex_unlock(&mutex);guard->release();pthread_mutex_lock(&mutex);state.guard_held=0;pthread_mutex_unlock(&mutex);
        return unadmitted(io,result,"guarded-owner-not-cold");
    }
    state.started=state.requests=state.busy=state.native_guarded=state.guard_held=1;state.reply_destination=d;current_request=request;sender=syscall(SYS_gettid);memcpy(state.saved_request,request,64);pthread_mutex_unlock(&mutex);
    void *forward=0,*answer=0,*final=0;int queued=0;unsigned char expected[72];struct full_osd_format_state format={0};
    wire(io,"REQUEST ",d,SOURCE,request,64);
    if(!healthy() || full_osd_pool_bind(backing,sizeof backing,0x500010000ULL,0x81000000u))goto failed;
    for(unsigned int i=0;i<4;i++)if(create_format(io,0,i,0,0))goto failed;
    unsigned int outputs[4];for(unsigned int i=0;i<4;i++)outputs[i]=state.resources[0][i].handle;
    if(full_osd_format_state_init(&format,outputs) || make(io,d,64,&forward))goto failed;
    frame(expected,64,0x100,1);pair(expected);memcpy(forward,expected,64);
    if(set_source(io,forward,SOURCE) || !canonical(io,request,state.saved_request,64,d) || pin_registry_connect_step(full_pinmem_registry(),native_osdpin_registry(),S,P,1))goto failed;
    pthread_mutex_lock(&mutex);state.context_kind=1;state.phase=1;state.wait_primary=6;state.keep_pending=state.pending_event6=1;state.source_state=2;state.peer_state=1;pthread_mutex_unlock(&mutex);
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,64);
    if(!canonical(io,forward,expected,64,SOURCE) || pin_registry_connect_step(full_pinmem_registry(),native_osdpin_registry(),S,P,2) || make(io,d,72,&answer))goto failed;
    frame(expected,72,0x8100,1);pair(expected);memcpy(answer,expected,72);if(set_source(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,72);
    if(!canonical(io,answer,expected,72,PEER))goto failed;
    for(unsigned int i=0;i<4;i++){
        if(notify(io,0,i,&format) || create_format(io,1,i,FULL_OSD_FORMAT_TAG101,outputs[i]) || notify(io,1,i,&format))goto failed;
        pthread_mutex_lock(&mutex);state.local_pairs[i][0]=(unsigned short)i;state.local_pairs[i][1]=(unsigned short)(4+i);pthread_mutex_unlock(&mutex);
    }
    if(enqueue_event6(io,answer,expected) || consume_event6(io) || source_post(io,&format) || drop(io,d,&forward) || drop(io,d,&answer) || final_readback(io) || preserved(&before,1))goto failed;
    pthread_mutex_lock(&mutex);state.history_preserved=1;state.source_state=state.peer_state=0;pthread_mutex_unlock(&mutex);
    if(make(io,d,56,&final))goto failed;
    frame(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32(expected+32+4*i,S[i]);memcpy(final,expected,56);
    if(set_source(io,final,SOURCE) || !canonical(io,final,expected,56,SOURCE) || !canonical(io,request,state.saved_request,64,d) || preserved(&before,1) || !healthy())goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,56);
    pthread_mutex_lock(&mutex);if(state.faults || state.live_reply || state.releasing_reply){pthread_mutex_unlock(&mutex);goto failed;}state.live_reply=final;pthread_mutex_unlock(&mutex);
    if(io->send(d,final)){
        pthread_mutex_lock(&mutex);if(state.live_reply!=final || state.releasing_reply){state.faults++;state.clean_completion=0;final=0;}else state.live_reply=0;pthread_mutex_unlock(&mutex);goto failed;
    }
    queued=1;pthread_mutex_lock(&mutex);state.queued=1;forget(final);pthread_mutex_unlock(&mutex);wire_from(io,"REPLY_QUEUED ",SOURCE,d,final,final_wire,56);final=0;
    int freed=io->release(SOURCE,request);pthread_mutex_lock(&mutex);state.request_freed=freed==0;
    if(freed){state.faults++;state.clean_completion=0;state.retained_request=request;}current_request=0;pthread_mutex_unlock(&mutex);
    char text[320];snprintf(text,sizeof text,"owner=%#x pointer=%p bytes=64 rc=%d",SOURCE,request,freed);record(io,freed?"REQUEST_FREE_FAULT ":"REQUEST_FREE ",text);
    if(pin_registry_connect_step(full_pinmem_registry(),native_osdpin_registry(),S,P,4) || preserved(&before,0))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    record(io,"COMMIT ","source_state=0 peer_state=0 pending=0 metadata_only=1 AP_reply_after_16_buffers_48_DMM_and_source_post=1 persistent_resources=16 graphics_ready=0 GPE_ready=0 frames_verified=0 capture_verified=0");goto done;
failed:
    fail(io,"transaction-incomplete owned-pool-references-preserved=1 caller-retains-original-until-queued=1");
    if(forward)drop(io,d,&forward);
    if(answer){pthread_mutex_lock(&mutex);int borrowed=state.event6_enqueued && (state.pending_event6 || state.event6_inflight);if(borrowed && !state.retained_cleanup)state.retained_cleanup=answer;pthread_mutex_unlock(&mutex);if(!borrowed)drop(io,d,&answer);}
    if(final)drop(io,d,&final);
    pthread_mutex_lock(&mutex);current_request=0;pthread_mutex_unlock(&mutex);
done:
    guard->release();pthread_mutex_lock(&mutex);state.guard_held=state.busy=0;pthread_mutex_unlock(&mutex);*result=queued?0:-1021;return 1;
}
int full_pinmem_osd_connection_native_dispatch(unsigned int dst,void *q,const struct full_imaging_io *io,const struct full_adf_proc_guard *guard,int enabled,int *result){return dispatch(dst,q,io,guard,enabled,1,result);}
int full_pinmem_osd_connection_dispatch(unsigned int dst,void *q,const struct full_imaging_io *io,int enabled,int *result){return dispatch(dst,q,io,0,enabled,0,result);}
int full_pinmem_osd_connection_release(unsigned int dst,void *reply,int (*release)(unsigned int,void *),void (*log)(const char *,const char *),int *result){
    if(!reply || !release || !result || !pid_matches())return 0;
    pthread_mutex_lock(&mutex);if(reply!=state.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int expected=state.reply_destination;long waiter=sender;
    if(dst!=expected || state.releasing_reply){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.releasing_reply=1;pthread_mutex_unlock(&mutex);int rc=release(dst,reply);long tid=syscall(SYS_gettid);
    pthread_mutex_lock(&mutex);state.releasing_reply=0;
    if(rc){state.faults++;state.clean_completion=0;}else{state.live_reply=0;state.reply_freed=1;state.native_reply_frees++;state.waiter_frees+=tid==waiter;state.ap_consumed=tid==waiter;forget(reply);}
    unsigned int faults=state.faults,consumed=state.ap_consumed;pthread_mutex_unlock(&mutex);
    if(log){char text[400];snprintf(text,sizeof text,"pid=%d tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p bytes=56 command=0x8001 rc=%d faults=%u ap_consumed=%u capture_verified=0",getpid(),tid,waiter,(unsigned int)(tid==waiter),dst,expected,reply,rc,faults,consumed);log(rc?"FULL_PINMEM_OSD_CONNECT_FAULT ":"FULL_PINMEM_OSD_CONNECT_NATIVE_REPLY_FREE ",text);}
    *result=rc;return 1;
}
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void full_pinmem_osd_connection_test_row(unsigned int index,unsigned int enabled,unsigned int known){
    if(!pid_matches() || index>=5 || enabled>255 || known>1)return;
    pthread_mutex_lock(&mutex);state.source_row_enabled[index]=(unsigned char)enabled;state.source_row_known[index]=(unsigned char)known;pthread_mutex_unlock(&mutex);
}
void full_pinmem_osd_connection_test_event_corrupt(unsigned int kind){
    if(!pid_matches())return;
    pthread_mutex_lock(&mutex);if(state.pending_event6 && state.event6_enqueued){
        if(kind==1)event6.parameter[0]^=1;
        if(kind==2)event6.body=(unsigned char *)event6.body+1;
        if(kind==3)event6.request[60]^=1;
        if(kind==4)event6.parameter[11]=1;
        if(kind==5)event6.request[20]^=1;
        if(kind==6)state.phase=0;
        if(kind==7)state.wait_primary=5;
        if(kind==8)state.context_kind=1;
    }pthread_mutex_unlock(&mutex);
}
#endif
