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
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static struct scalar_connection_snapshot state;
static void *reply,*retained[4];
static unsigned int destination_sid,retained_count;
static long sender;
/* Instantiated independently by the two explicitly supported cold metadata
 * edges. Each translation unit owns its own state, mutex and message leases. */
static const unsigned int S[4]={0,2,SOURCE_INDEX,FULL_PINMEM_CP},P[4]={0,1,PEER_INDEX,PEER_CP};
static int current_process(void){int pid=(int)getpid(),expected=0;atomic_compare_exchange_strong(&process_pid,&expected,pid);return atomic_load(&process_pid)==pid;}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(i*8));}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_" EDGE_TAG "_CONNECT_%s",kind);io->record(tag,text);}
}
static void fault(const struct full_imaging_io *io,const char *text){
    state.faults++;pin_registry_connect_fault(full_pinmem_registry(),PEER_REGISTRY());event(io,"FAULT ",text);
}
static void wire_event(const struct full_imaging_io *io,const char *kind,unsigned int source,unsigned int dst,void *message,unsigned int bytes){
    char hex[145],line[420];
    for(unsigned int i=0;i<bytes;i++)snprintf(hex+2*i,3,"%02x",((unsigned char *)message)[i]);hex[2*bytes]=0;
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s",sender,source,dst,message,bytes,hex);event(io,kind,line);
}
static int release_owned(const struct full_imaging_io *io,void **p){
    if(!*p)return 0;
    unsigned int bytes=io->size(*p);int rc=io->release(destination_sid,*p);char line[180];
    snprintf(line,sizeof line,"tid=%ld owner=%#x pointer=%p bytes=%u rc=%d",sender,destination_sid,*p,bytes,rc);event(io,rc?"FAULT ":"INTERNAL_FREE ",line);
    if(rc){state.faults++;if(retained_count<4)retained[retained_count++]=*p;}
    *p=0;return rc;
}
static int allocate_owned(const struct full_imaging_io *io,unsigned int bytes,void **out,void *request,void *other){
    *out=0;int rc=io->allocate(destination_sid,out,bytes,1);
    if(*out && (*out==request || *out==other || *out==reply)){fault(io,"allocator-returned-live-message");*out=0;return -1;}
    if(rc || !*out){if(*out)release_owned(io,out);return -1;}
    if(io->size(*out)!=bytes){release_owned(io,out);return -1;}
    memset(*out,0,bytes);return 0;
}
static void envelope(unsigned char *p,unsigned int bytes,unsigned int command,unsigned int flags){
    put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,bytes);put32(p+12,24);put32(p+16,bytes);
    put16(p+24,0x1000);put16(p+26,command);put16(p+28,bytes-24);put16(p+30,flags);
}
static int valid_envelope(const struct full_imaging_io *io,void *message,unsigned int bytes,unsigned int command,unsigned int flags){
    const unsigned char *p=message;
    return io->size(message)==bytes && u32(p+4)==0xa0a0a0a0 && u16(p+8)==1 && u16(p+10)==bytes && u32(p+12)==24 &&
        u32(p+16)==bytes && u16(p+24)==0x1000 && u16(p+26)==command && u16(p+28)==bytes-24 && u16(p+30)==flags;
}
static void pair(unsigned char *p){for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}}
static int valid_pair(const unsigned char *p){
    for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;
    return 1;
}
int EDGE_DISPATCH(unsigned int dst,void *request,const struct full_imaging_io *io,int enabled,int *result){
    if(enabled!=1 || dst!=FULL_PINMEM_CP || !io || !result)return 0;
    if(!current_process()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->set_source || !io->send){*result=-1021;return 1;}
    if(io->size(request)!=64)return 0;
    if(EDGE_PASS_OTHER && !valid_pair(request))return 0;
    pthread_mutex_lock(&mutex);
    unsigned int d=u32(request);
    if(state.started || state.faults || io->source(request)!=d || d>>28!=8 || !(d&0xfffffff) ||
       !valid_envelope(io,request,64,1,2) || !valid_pair(request)){
        event(io,"UNSUPPORTED ",EDGE_DESCRIPTION);pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    state.started=1;sender=syscall(SYS_gettid);destination_sid=d;
    wire_event(io,"REQUEST ",d,FULL_PINMEM_CP,request,64);
    void *forward=0,*answer=0,*final=0;int committed=0;
    if(allocate_owned(io,64,&forward,request,0))goto failed;
    envelope(forward,64,0x100,1);pair(forward);io->set_source(forward,FULL_PINMEM_CP);
    if(pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,1))goto failed;
    state.pending_event6=1;
    wire_event(io,"PEER_REQUEST ",FULL_PINMEM_CP,PEER_CP,forward,64);
    if(!valid_envelope(io,forward,64,0x100,1) || u32(forward) || io->source(forward)!=FULL_PINMEM_CP || !valid_pair(forward) ||
       pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,2))goto failed;
    if(allocate_owned(io,72,&answer,request,forward))goto failed;
    envelope(answer,72,0x8100,1);pair(answer);io->set_source(answer,PEER_CP);
    wire_event(io,"PEER_REPLY ",PEER_CP,FULL_PINMEM_CP,answer,72);
    if(release_owned(io,&forward))goto failed;
    if(!state.pending_event6 || !valid_envelope(io,answer,72,0x8100,1) || u32(answer) || io->source(answer)!=PEER_CP ||
       !valid_pair(answer) || u32((unsigned char *)answer+64) || u32((unsigned char *)answer+68))goto failed;
    /* Original 8100 keeps the first group's attributes for the YC callback.
     * Only type0/dir1 publishes format. Both supported OUT pins have dir2: no allocation
     * or cache notification is prescribed. Inspect the actual decoded frame. */
    state.yc_callback_seen=1;
    unsigned int type=u32((unsigned char *)answer+32),dir=u32((unsigned char *)answer+36);
    if(type!=0 || dir!=2)goto failed;
    char details[200];
    snprintf(details,sizeof details,"command=0x8100 selected_group=source type=0 dir=2 index=%u format_published=0 buffer_allocated=0",SOURCE_INDEX);
    event(io,"YC_DIRECTION_CHECK ",details);
    if(pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,3))goto failed;
    state.event6_consumed=1;state.pending_event6=0;
    snprintf(details,sizeof details,"source=0,2,%u,0x90590818 peer=0,1,%u,%#x status=0",SOURCE_INDEX,PEER_INDEX,PEER_CP);
    event(io,"EVENT6_CONSUMED ",details);
    if(release_owned(io,&answer))goto failed;
    if(allocate_owned(io,56,&final,request,0))goto failed;
    envelope(final,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32((unsigned char *)final+32+4*i,S[i]);
    io->set_source(final,FULL_PINMEM_CP);if(io->source(final)!=FULL_PINMEM_CP)goto failed;
    reply=final;if(io->send(d,final)){reply=0;goto failed;}final=0;committed=1;
    wire_event(io,"REPLY_QUEUED ",FULL_PINMEM_CP,d,reply,56);
    int freed=io->release(FULL_PINMEM_CP,request);char line[420];
    snprintf(line,sizeof line,"tid=%ld owner=%#x pointer=%p bytes=64 rc=%d",sender,FULL_PINMEM_CP,request,freed);event(io,freed?"FAULT ":"REQUEST_FREE ",line);
    if(freed){if(retained_count<4)retained[retained_count++]=request;goto failed;}
    if(pin_registry_connect_step(full_pinmem_registry(),PEER_REGISTRY(),S,P,4))goto failed;
    struct full_vef_snapshot source,peer;full_pinmem_snapshot(&source);PEER_SNAPSHOT(&peer);
    const struct full_vef_pin *a=&source.pins[SOURCE_SLOT],*b=&peer.pins[PEER_SLOT];
    if(source.faults || peer.faults || source.pending || peer.pending || a->state || b->state ||
       memcmp(a->self,S,sizeof S) || memcmp(a->peer,P,sizeof P) ||
       memcmp(b->self,P,sizeof P) || memcmp(b->peer,S,sizeof S))goto failed;
    state.source_state=a->state;state.peer_state=b->state;state.connections++;
    snprintf(line,sizeof line,"tid=%ld source_slot=%u source_state=%u source_self=%u,%u,%u,%#x source_peer=%u,%u,%u,%#x peer_slot=%u peer_state=%u peer_self=%u,%u,%u,%#x peer_peer=%u,%u,%u,%#x source_pending=%u event6_consumed=%u yc_format_published=0 pixels_consumed=0",
        sender,SOURCE_SLOT,a->state,a->self[0],a->self[1],a->self[2],a->self[3],
        a->peer[0],a->peer[1],a->peer[2],a->peer[3],PEER_SLOT,b->state,
        b->self[0],b->self[1],b->self[2],b->self[3],
        b->peer[0],b->peer[1],b->peer[2],b->peer[3],source.pending,state.event6_consumed);
    event(io,"STATE_READBACK ",line);pthread_mutex_unlock(&mutex);*result=0;return 1;
failed:
    release_owned(io,&forward);release_owned(io,&answer);release_owned(io,&final);
    fault(io,committed?"post-reply-state-or-release-failure":"message-or-state-transition-failed");
    pthread_mutex_unlock(&mutex);*result=committed?0:-1021;return 1;
}
int EDGE_RELEASE(unsigned int d,void *message,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *result){
    if(!message || !release || !result)return 0;
    if(!current_process()){if(message!=reply)return 0;*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);if(message!=reply){pthread_mutex_unlock(&mutex);return 0;}
    *result=d==destination_sid?release(d,message):-1021;long tid=syscall(SYS_gettid);
    if(*result)state.faults++;else{reply=0;state.native_reply_frees++;state.waiter_frees+=tid==sender;}
    if(record){char line[240];snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p bytes=56 command=0x8001 rc=%d",tid,sender,tid==sender,d,destination_sid,message,*result);
        record(*result?"FULL_" EDGE_TAG "_CONNECT_FAULT ":"FULL_" EDGE_TAG "_CONNECT_NATIVE_REPLY_FREE ",line);}
    pthread_mutex_unlock(&mutex);return 1;
}
void EDGE_SNAPSHOT(struct scalar_connection_snapshot *out){
    if(!out)return;if(!current_process()){*out=(struct scalar_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_PIN_CONNECTION_TEST
void EDGE_RESET(void){
    pthread_mutex_lock(&mutex);state=(struct scalar_connection_snapshot){0};reply=0;memset(retained,0,sizeof retained);retained_count=destination_sid=0;sender=0;atomic_store(&process_pid,(int)getpid());pthread_mutex_unlock(&mutex);
}
#endif
