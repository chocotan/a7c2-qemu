/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "imaging-pin-connection.h"
#include "bb-set-mode-device.h"
#include "pin-registry-core.h"
#include "pin-buffer-owner.h"
#include "../infrabb-registry.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define SOURCE NATIVE_INFRAIMAGING_CP
#define PEER NATIVE_INFRABB_CP
#define DMM 0x0061003cu
#define DMM_BYTES 216u
static const unsigned int S[4]={0,2,1,SOURCE},P[4]={0,1,1,PEER};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_imaging_pin_connection_snapshot state;
static void *messages[8];
static void *current_request;
static int pid_matches(void){return atomic_load(&owner_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static unsigned long long u64(const unsigned char *p){return u32(p)|(unsigned long long)u32(p+4)<<32;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static void put64(unsigned char *p,unsigned long long v){put32(p,(unsigned int)v);put32(p+4,(unsigned int)(v>>32));}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_IMAGING_PIN_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire_from(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *p,const unsigned char *data,unsigned int n){
    char raw[DMM_BYTES*2+1],text[900];
    for(unsigned int i=0;i<n;i++){snprintf(raw+2*i,3,"%02x",data[i]);}
    raw[2*n]=0;
    snprintf(text,sizeof text,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s transport_owner=virtual-local-caller original_cp_executed=0 frames_verified=0 capture_verified=0",
             getpid(),syscall(SYS_gettid),src,dst,p,n,raw);event(io,kind,text);
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *p,unsigned int n){
    wire_from(io,kind,src,dst,p,p,n);
}
static void frame(unsigned char *p,unsigned int n,unsigned int op,unsigned int flags){
    put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,op);put16(p+28,n-24);put16(p+30,flags);
}
static void pair(unsigned char *p){
    for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}
}
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
static int drop(const struct full_imaging_io *io,unsigned int dst,void **p){
    if(!*p)return 0;
    void *pointer=*p;int rc=io->release(dst,pointer);
    pthread_mutex_lock(&mutex);
    if(rc)state.faults++;
    else for(unsigned int i=0;i<8;i++)if(messages[i]==pointer){messages[i]=0;break;}
    pthread_mutex_unlock(&mutex);
    char text[180];snprintf(text,sizeof text,"pid=%d tid=%ld destination=%#x pointer=%p rc=%d",getpid(),syscall(SYS_gettid),dst,pointer,rc);
    event(io,rc?"CLEANUP_FAULT ":"INTERNAL_FREE ",text);*p=0;return rc;
}
static int make(const struct full_imaging_io *io,unsigned int dst,unsigned int n,void **out){
    *out=0;int rc=io->allocate(dst,out,n,1);
    pthread_mutex_lock(&mutex);unsigned int free_slot=8;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<8;i++){if(messages[i] && messages[i]==*out)alias=1;if(!messages[i] && free_slot==8)free_slot=i;}
    if(alias || (*out && free_slot==8)){state.faults++;pthread_mutex_unlock(&mutex);*out=0;event(io,"FAULT ","allocator-returned-live-message-or-capacity");return -1;}
    if(*out)messages[free_slot]=*out;
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,dst,out);return -1;}
    memset(*out,0,n);return 0;
}
static int set_source(const struct full_imaging_io *io,void *p,unsigned int src){
    io->set_source(p,src);return io->source(p)==src?0:-1;
}
static int dependencies(void){
    struct full_bb_set_mode_snapshot bb={0};full_bb_set_mode_snapshot(&bb);
    struct full_vef_snapshot a={0},b={0};native_infraimaging_snapshot(&a);native_infrabb_snapshot(&b);
    return bb.owner_pid==getpid() && bb.initialized && bb.applications==1 && bb.ap_consumed==1 && bb.clean_completion &&
        bb.queue_finished && bb.outer_returned && bb.inner_returned && !bb.busy && !bb.pending && !bb.guard_held &&
        !bb.faults && !bb.retained_request && !bb.live_reply && !bb.retained_reply && !bb.retained_cleanup &&
        a.initialized && a.registry_objects==6 && a.owner_sid==SOURCE && a.queries && !a.pending && !a.faults && !a.live_replies &&
        !a.retained_request && !a.retained_reply && !memcmp(a.pins[1].self,S,sizeof S) && a.pins[1].state==1 &&
        b.initialized && b.registry_objects==21 && b.owner_sid==PEER && b.queries && !b.pending && !b.faults && !b.live_replies &&
        !b.retained_request && !b.retained_reply && !memcmp(b.pins[1].self,P,sizeof P) && b.pins[1].state==1;
}
int full_imaging_pin_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);
    if(!state.initialized){state.owner_pid=pid;if(full_infraimaging_format_init(&state.format)){pthread_mutex_unlock(&mutex);return -1021;}state.initialized=1;}
    pthread_mutex_unlock(&mutex);return 0;
}
void full_imaging_pin_connection_snapshot(struct full_imaging_pin_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_imaging_pin_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;
    for(unsigned int i=0;i<8;i++)out->retained_messages+=messages[i]!=0;
    pthread_mutex_unlock(&mutex);
}
static int forward_ready(unsigned int handle){
    if(state.owner_pid!=getpid() || state.initialized!=1 || state.clean_completion!=1 ||
       state.connections!=1 || state.ap_consumed!=1 || state.request_freed!=1 || state.reply_freed!=1 ||
       state.format_consumed!=1 || state.buffer_freed!=1 || state.peer_connected_marker_known!=1 ||
       state.peer_connected_marker!=1 || state.busy || state.guard_held || state.faults ||
       state.live_reply || state.retained_request || state.releasing_reply || current_request ||
       handle==state.buffer_handle || handle==state.forwarded_handle ||
       state.forwarded_formats==UINT_MAX || state.format.consumed==UINT_MAX ||
       state.format.consumed!=state.forwarded_formats+1)return 0;
    for(unsigned int i=0;i<8;i++)if(messages[i])return 0;
    return 1;
}
int full_imaging_pin_connection_accept_forwarded_format(unsigned int handle,const struct full_imaging_io *io){
    if(!io || !io->record || !pid_matches())return -1021;
    pthread_mutex_lock(&mutex);int ready=forward_ready(handle);pthread_mutex_unlock(&mutex);
    if(!ready)return -1021;
    /* The caller's resource guard holds the lease stable; do not nest pool/owner locks. */
    struct pin_control_references refs={0};unsigned char packet[FULL_INFRAIMAGING_FORMAT_BYTES];
    if(pin_control_references(handle,&refs) || refs.handle!=handle || refs.owners!=1 || refs.opens!=1 ||
       refs.creator || refs.consumer!=1 || refs.consumer_open!=1 ||
       pin_control_read_consumer(handle,0,packet,sizeof packet) ||
       u32(packet+4)!=0x01000000 || u32(packet+0x28))return -1021;
    pthread_mutex_lock(&mutex);
    if(!forward_ready(handle) || full_infraimaging_format_consume(&state.format,packet,sizeof packet)){
        pthread_mutex_unlock(&mutex);return -1021;
    }
    state.forwarded_formats++;state.forwarded_handle=handle;
    struct full_infraimaging_format format=state.format;unsigned int count=state.forwarded_formats;
    pthread_mutex_unlock(&mutex);
    char text[560];snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x unit=0x404 bytes=80 key=0 payload_bytes=16 synchronization_object=0x21 cache=%u,%u,%u,%u,%u payload_fnv64=%016llx consumed=%u forwarded_formats=%u mapped_backing_read=1 original_cp_executed=0 original_CP_page_tables_verified=0 frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),handle,format.cache[0],format.cache[1],format.cache[2],format.cache[3],format.cache[4],format.payload_fnv64,format.consumed,count);
    event(io,"FORWARD_FORMAT_CONSUMED ",text);return 0;
}
/* The producer/consumer IDs here are explicit virtual endpoint identities.
 * Sony creates temporary 2a/owner284 and owner5 senders; these are not their IDs. */
static int dmm(const struct full_imaging_io *io,unsigned int dst,unsigned int command){
    void *message=0;if(make(io,dst,DMM_BYTES,&message))return -1;
    unsigned char *p=message;put16(p,command);put16(p+0x14,0x55);
    unsigned int src=command==0x20 || command==0x25?PEER:SOURCE;
    if(command==0x20){put32(p+4,PIN_CONTROL_UNIT);put32(p+0xc,0xffffffff);put16(p+0x16,1);}
    else {put32(p+8,state.buffer_handle);if(command==0x23)put16(p+0x16,2);}
    if(set_source(io,message,src)){drop(io,dst,&message);return -1;}
    wire(io,"DMM_REQUEST ",src,DMM,message,DMM_BYTES);
    struct pin_control_lease lease={0};int rc=-1;
    if(io->size(message)==DMM_BYTES && u16(p)==command && u16(p+0x14)==0x55){
        if(command==0x20 && u32(p+4)==PIN_CONTROL_UNIT && u32(p+0xc)==0xffffffff && u16(p+0x16)==1)
            rc=pin_control_allocate(PIN_CONTROL_UNIT,&lease);
        else if(command==0x25 && u32(p+8)==state.buffer_handle)rc=pin_control_close_creator(state.buffer_handle);
        else if(command==0x24 && u32(p+8)==state.buffer_handle && !u32(p+0xc) && !u16(p+0x16))rc=pin_control_open_consumer(state.buffer_handle,PIN_CONTROL_UNIT,&lease);
        else if(command==0x23 && u32(p+8)==state.buffer_handle && u16(p+0x16)==2)rc=pin_control_release_consumer(state.buffer_handle);
    }
    if(rc){drop(io,dst,&message);return -1;}
    pthread_mutex_lock(&mutex);
    if(command==0x20){state.buffer_handle=lease.handle;state.buffer_physical=lease.physical;state.buffer_cp_virtual=lease.cp_virtual;state.dmm_allocations++;}
    if(command==0x25)state.dmm_creator_closes++;
    if(command==0x24){state.buffer_opened=1;state.dmm_opens++;}
    if(command==0x23){state.buffer_freed=1;state.dmm_frees++;}
    pthread_mutex_unlock(&mutex);
    memset(p,0,DMM_BYTES);put16(p,command|0x8000);put16(p+6,0x55);put32(p+0xc,state.buffer_handle);
    if(command==0x20)put32(p+0x10,PIN_CONTROL_UNIT);
    if(command==0x20 || command==0x24){put16(p+8,1);put64(p+0x18,lease.physical);put32(p+0x20,lease.bytes);}
    if(set_source(io,message,DMM)){drop(io,dst,&message);return -1;}
    wire(io,"DMM_REPLY ",DMM,src,message,DMM_BYTES);
    int valid=u16(p)==(command|0x8000) && !u16(p+2) && u16(p+6)==0x55 && u32(p+0xc)==state.buffer_handle && io->source(message)==DMM;
    if(command==0x20 || command==0x24)valid=valid && u16(p+8)==1 && lease.bytes==PIN_CONTROL_SLOT_BYTES &&
        u64(p+0x18)==state.buffer_physical && u32(p+0x20)==lease.bytes && lease.physical==PIN_CONTROL_PHYSICAL+lease.slot*PIN_CONTROL_SLOT_BYTES &&
        lease.cp_virtual==PIN_CONTROL_CP_VIRTUAL+lease.slot*PIN_CONTROL_SLOT_BYTES;
    return drop(io,dst,&message) || !valid?-1:0;
}
static int references(const struct full_imaging_io *io,const char *phase,unsigned int owners,unsigned int opens,unsigned int creator,unsigned int consumer,unsigned int consumer_open){
    struct pin_control_references r={0};
    if(pin_control_references(state.buffer_handle,&r) || r.owners!=owners || r.opens!=opens || r.creator!=creator || r.consumer!=consumer || r.consumer_open!=consumer_open)return -1;
    char text[250];snprintf(text,sizeof text,"pid=%d tid=%ld phase=%s handle=%#x owners=%u opens=%u creator=%u consumer=%u consumer_open=%u",
        getpid(),syscall(SYS_gettid),phase,r.handle,r.owners,r.opens,r.creator,r.consumer,r.consumer_open);event(io,"REFERENCE_READBACK ",text);return 0;
}
static int consume_format(const struct full_imaging_io *io,unsigned int dst){
    unsigned char packet[FULL_INFRAIMAGING_FORMAT_BYTES],readback[FULL_INFRAIMAGING_FORMAT_BYTES];
    if(dmm(io,dst,0x20) || references(io,"allocated",1,1,1,0,0) || full_infraimaging_format_build(packet,sizeof packet))return -1;
    unsigned long long digest=0;
    if(pin_control_write_payload(state.buffer_handle,packet,sizeof packet,&digest))return -1;
    pthread_mutex_lock(&mutex);state.buffer_fnv=digest;pthread_mutex_unlock(&mutex);
    char text[420];snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x physical=%#llx cp_virtual=%#x bytes=80 fnv64=%016llx header_word=0x06000000 key=0 payload_bytes=16 payload=01000000000000008007000038040000 pixels_consumed=0",
        getpid(),syscall(SYS_gettid),state.buffer_handle,state.buffer_physical,state.buffer_cp_virtual,digest);event(io,"FORMAT_WRITTEN ",text);
    if(dmm(io,dst,0x25) || references(io,"creator-closed",1,0,1,0,0))return -1;
    void *notify=0;if(make(io,dst,80,&notify))return -1;
    unsigned char *p=notify;frame(p,80,0x104,1);
    for(unsigned int i=0;i<4;i++){put32(p+32+4*i,P[i]);put32(p+48+4*i,S[i]);}
    put32(p+64,PIN_CONTROL_UNIT);put32(p+68,state.buffer_handle);
    if(set_source(io,notify,PEER)){drop(io,dst,&notify);return -1;}
    wire(io,"FORMAT_NOTIFY ",PEER,SOURCE,notify,80);
    int valid=envelope(io,notify,80,0x104,1) && io->source(notify)==PEER && !u32(p) &&
        u32(p+64)==PIN_CONTROL_UNIT && u32(p+68)==state.buffer_handle && !u32(p+72) && !u32(p+76);
    for(unsigned int i=0;i<4;i++)valid=valid && u32(p+32+4*i)==P[i] && u32(p+48+4*i)==S[i];
    if(!valid || pin_control_transfer_creator(state.buffer_handle,PIN_CONTROL_UNIT)){drop(io,dst,&notify);return -1;}
    pthread_mutex_lock(&mutex);state.buffer_transferred=1;pthread_mutex_unlock(&mutex);
    if(references(io,"transferred",1,0,0,1,0) || dmm(io,dst,0x24) || references(io,"consumer-open",1,1,0,1,1) ||
       pin_control_read_consumer(state.buffer_handle,0,readback,sizeof readback) || memcmp(packet,readback,sizeof packet)){
        drop(io,dst,&notify);return -1;
    }
    pthread_mutex_lock(&mutex);state.synchronization_acquires++;
    int consumed=full_infraimaging_format_consume(&state.format,readback,sizeof readback);
    state.synchronization_releases++;if(!consumed)state.format_consumed=1;
    struct full_infraimaging_format format=state.format;pthread_mutex_unlock(&mutex);
    if(consumed){drop(io,dst,&notify);return -1;}
    snprintf(text,sizeof text,"pid=%d tid=%ld handle=%#x selected_output=1 key=0 bytes=16 synchronization_object=0x21 acquires=1 releases=1 cache=%u,%u,%u,%u,%u payload_fnv64=%016llx mapped_backing_read=1 original_CP_page_tables_verified=0 virtual_mapping=physical500000000-to-CP80000000 frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),state.buffer_handle,format.cache[0],format.cache[1],format.cache[2],format.cache[3],format.cache[4],format.payload_fnv64);
    event(io,"FORMAT_CONSUMED ",text);
    if(dmm(io,dst,0x23)){drop(io,dst,&notify);return -1;}
    struct pin_control_references ended={0};struct pin_control_snapshot pool={0};pin_control_snapshot(&pool);
    if(pin_control_references(state.buffer_handle,&ended)==0 || pool.live || pool.faults || pool.allocations!=pool.releases){drop(io,dst,&notify);return -1;}
    event(io,"BUFFER_RETIRED ","owners=0 opens=0 live=0 Free23_option2=1 creator_Close25_was_not_release=1 bytes_preserved=1 capture_verified=0");
    return drop(io,dst,&notify)?-1:0;
}
int full_imaging_pin_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                         const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !result || !io)return 0;
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    const unsigned char *in=request;unsigned int dst=u32(in),src=io->source(request);
    if(!envelope(io,request,64,1,2) || !is_pair(in) || src!=dst || src>>28!=8 || !(src&0xfffffff)){
        event(io,"UNSUPPORTED ","only-90050004-OUT1-to-InfraBB-IN1-owned-edge");*result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.busy=1;state.requests=1;state.reply_destination=dst;current_request=request;pthread_mutex_unlock(&mutex);
    int held=0,queued=0;void *forward=0,*answer=0,*final=0;
    if(!dependencies() || guard->reserve())goto failed;
    held=1;pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    struct pin_control_snapshot pool={0};pin_control_snapshot(&pool);
    if(!pool.bound || pool.faults || pool.live || !pool.allocations || pool.allocations!=pool.releases)goto failed;
    wire(io,"REQUEST ",src,destination,request,64);
    if(make(io,dst,64,&forward))goto failed;
    frame(forward,64,0x100,1);pair(forward);
    if(set_source(io,forward,SOURCE) || pin_registry_connect_step(native_infraimaging_registry(),native_infrabb_registry(),S,P,1))goto failed;
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,64);
    if(!envelope(io,forward,64,0x100,1) || !is_pair(forward) || io->source(forward)!=SOURCE ||
       pin_registry_connect_step(native_infraimaging_registry(),native_infrabb_registry(),S,P,2))goto failed;
    pthread_mutex_lock(&mutex);state.peer_requests++;pthread_mutex_unlock(&mutex);
    if(make(io,dst,72,&answer))goto failed;
    frame(answer,72,0x8100,1);pair(answer);
    if(set_source(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,72);
    if(!envelope(io,answer,72,0x8100,1) || !is_pair(answer) || io->source(answer)!=PEER || u32((unsigned char *)answer+64) || u32((unsigned char *)answer+68) ||
       pin_registry_connect_step(native_infraimaging_registry(),native_infrabb_registry(),S,P,3))goto failed;
    pthread_mutex_lock(&mutex);
    state.peer_replies++;state.peer_connected_marker=1;state.peer_connected_marker_known=1;state.peer_marker_writes++;
    unsigned int marker_readback=state.peer_connected_marker;
    pthread_mutex_unlock(&mutex);
    if(marker_readback!=1)goto failed;
    event(io,"PEER_MARKER_WRITTEN ","source_CP_VA=0x01acad10 peer_index=1 old_value_known=0 value=1 readback=1 writes=1 virtual_projection=1 original_CP_RAM_read=0 capture_verified=0");
    if(drop(io,dst,&forward) || drop(io,dst,&answer) || consume_format(io,dst))goto failed;
    if(make(io,dst,56,&final))goto failed;
    frame(final,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32((unsigned char *)final+32+4*i,S[i]);
    if(set_source(io,final,SOURCE))goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire);
    pthread_mutex_lock(&mutex);
    if(state.faults){pthread_mutex_unlock(&mutex);goto failed;}
    state.live_reply=final;pthread_mutex_unlock(&mutex);
    if(io->send(dst,final)){
        pthread_mutex_lock(&mutex);if(state.live_reply!=final || state.releasing_reply){state.faults++;final=0;}else state.live_reply=0;pthread_mutex_unlock(&mutex);goto failed;
    }
    queued=1;wire_from(io,"REPLY_QUEUED ",SOURCE,dst,final,final_wire,sizeof final_wire);
    pthread_mutex_lock(&mutex);state.queued=1;for(unsigned int i=0;i<8;i++)if(messages[i]==final){messages[i]=0;break;}pthread_mutex_unlock(&mutex);final=0;
    int freed=io->release(SOURCE,request);
    pthread_mutex_lock(&mutex);state.request_freed=freed==0;if(freed){state.faults++;state.retained_request=request;}current_request=0;pthread_mutex_unlock(&mutex);
    if(pin_registry_connect_step(native_infraimaging_registry(),native_infrabb_registry(),S,P,4))goto failed;
    struct full_vef_snapshot a={0},b={0};native_infraimaging_snapshot(&a);native_infrabb_snapshot(&b);
    if(a.pins[1].state || b.pins[1].state || a.pending || a.faults || b.faults ||
       memcmp(a.pins[1].self,S,sizeof S) || memcmp(a.pins[1].peer,P,sizeof P) ||
       memcmp(b.pins[1].self,P,sizeof P) || memcmp(b.pins[1].peer,S,sizeof S))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_state=0 peer_state=0 source_pending=0 format_consumed=1 buffer_freed=1 unique_reply=1 reply_deferred_until_format_and_Free=1 original_cp_executed=0 frames_verified=0 capture_verified=0");
    goto done;
failed:
    fail(io,"transaction-incomplete-owned-state-preserved");
    if(forward)drop(io,dst,&forward);
    if(answer)drop(io,dst,&answer);
    if(final)drop(io,dst,&final);
    pthread_mutex_lock(&mutex);if(!queued)current_request=0;pthread_mutex_unlock(&mutex);
done:
    if(held)guard->release();
    pthread_mutex_lock(&mutex);state.guard_held=0;state.busy=0;pthread_mutex_unlock(&mutex);
    *result=queued?0:-1021;return 1;
}
int full_imaging_pin_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                                        void (*record)(const char *,const char *),int *result){
    if(!reply || !release || !result || !pid_matches())return 0;
    pthread_mutex_lock(&mutex);
    if(reply!=state.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int dst=state.reply_destination;
    if(destination!=dst || state.releasing_reply){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.releasing_reply=1;pthread_mutex_unlock(&mutex);
    int rc=release(destination,reply);
    pthread_mutex_lock(&mutex);state.releasing_reply=0;
    if(rc){state.faults++;state.clean_completion=0;}else{state.live_reply=0;state.reply_freed=1;state.ap_consumed=1;for(unsigned int i=0;i<8;i++)if(messages[i]==reply){messages[i]=0;break;}}
    unsigned int faults=state.faults;pthread_mutex_unlock(&mutex);
    if(record){char text[270];snprintf(text,sizeof text,"pid=%d tid=%ld destination=%#x expected=%#x pointer=%p bytes=56 rc=%d faults=%u ap_consumed=%u frames_verified=0 capture_verified=0",
        getpid(),syscall(SYS_gettid),destination,dst,reply,rc,faults,(unsigned int)(!rc));record("FULL_IMAGING_PIN_CONNECT_REPLY_FREE ",text);}
    *result=rc;return 1;
}
