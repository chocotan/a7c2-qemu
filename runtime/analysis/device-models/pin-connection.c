/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pin-connection.h"
#include "pin-registry-core.h"
#include "pinmem-device.h"
#include "pin-buffer-owner.h"
#include "pin-buffer-wire.h"
#include <pthread.h>
#include <stdio.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static struct pin_connection_snapshot state;
static void *reply,*blocked[8],*retained[8];
static unsigned int reply_destination,retained_count;
static long sender;
static const unsigned int S[4]={0,2,3,FULL_VEF_CP},P[4]={0,1,1,FULL_PINMEM_CP};
static int current_process(void){int pid=(int)getpid(),expected=0;atomic_compare_exchange_strong(&process_pid,&expected,pid);return atomic_load(&process_pid)==pid;}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static unsigned long long u64(const unsigned char *p){return u32(p)|(unsigned long long)u32(p+4)<<32;}
static void put16(unsigned char *p,unsigned int n){p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static void event(const struct full_imaging_io *io,const char *kind,const char *line){
    if(io->record){char tag[64];snprintf(tag,sizeof tag,"FULL_PIN_CONNECT_%s",kind);io->record(tag,line);}
}
static void format_event(const struct full_imaging_io *io,const char *kind,const char *line){
    if(io->record){char tag[64];snprintf(tag,sizeof tag,"FULL_PIN_FORMAT_%s",kind);io->record(tag,line);}
}
static void wire_event(const struct full_imaging_io *io,const char *kind,unsigned int source,unsigned int destination,void *p,unsigned int bytes){
    char hex[305],line[640];for(unsigned int i=0;i<bytes;i++)snprintf(hex+2*i,3,"%02x",((unsigned char *)p)[i]);hex[2*bytes]=0;
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s",syscall(SYS_gettid),source,destination,p,bytes,hex);event(io,kind,line);
}
static void fault(const struct full_imaging_io *io,const char *reason){
    state.faults++;pin_registry_connect_fault(full_vef_registry(),full_pinmem_registry());event(io,"FAULT ",reason);
}
static int release_owned(const struct full_imaging_io *io,unsigned int owner,void **p){
    if(!*p)return 0;
    unsigned int bytes=io->size(*p);
    int rc=io->release(owner,*p);char line[180];snprintf(line,sizeof line,"tid=%ld owner=%#x pointer=%p bytes=%u rc=%d",syscall(SYS_gettid),owner,*p,bytes,rc);
    event(io,rc?"FAULT ":"INTERNAL_FREE ",line);
    if(rc){if(retained_count<8)retained[retained_count++]=*p;state.faults++;}
    *p=0;return rc;
}
static int allocate_owned(const struct full_imaging_io *io,unsigned int dst,unsigned int bytes,void **out,void *request,void *other){
    *out=0;int rc=io->allocate(dst,out,bytes,1);
    if(*out && (*out==request || *out==reply || *out==other)){
        fault(io,"allocator-returned-live-message");*out=0;return -1;
    }
    for(unsigned int i=0;i<state.blocked_requests;i++)if(*out && *out==blocked[i]){
        fault(io,"allocator-returned-blocked-request");*out=0;return -1;
    }
    if(rc || !*out){if(*out)release_owned(io,dst,out);return -1;}
    if(io->size(*out)!=bytes){release_owned(io,dst,out);return -1;}
    memset(*out,0,bytes);return 0;
}
static int envelope(const struct full_imaging_io *io,void *p,unsigned int bytes,unsigned int command,unsigned int inner_bytes,unsigned int flags){
    const unsigned char *in=p;
    return p && io->size(p)==bytes && u32(in+4)==0xa0a0a0a0 && u16(in+8)==1 && u16(in+10)==bytes &&
        u32(in+12)==24 && u32(in+16)==bytes && u16(in+24)==0x1000 && u16(in+26)==command && u16(in+28)==inner_bytes && u16(in+30)==flags;
}
static void frame(unsigned char *p,unsigned int bytes,unsigned int command,unsigned int inner_bytes,unsigned int flags){
    put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,bytes);put32(p+12,24);put32(p+16,bytes);
    put16(p+24,0x1000);put16(p+26,command);put16(p+28,inner_bytes);put16(p+30,flags);
}
static void attributes(unsigned char *out,const unsigned int *s,const unsigned int *p){for(unsigned int i=0;i<4;i++){put32(out+4*i,s[i]);put32(out+16+4*i,p[i]);}}
static int decode_pair(const unsigned char *p,unsigned int *s,unsigned int *peer){
    for(unsigned int i=0;i<4;i++){s[i]=u32(p+32+4*i);peer[i]=u32(p+48+4*i);}
    return !memcmp(s,S,sizeof S) && !memcmp(peer,P,sizeof P);
}
static int buffer_postprocess(const struct full_imaging_io *io,unsigned int dst,void *original){
    void *message=0;
    if(allocate_owned(io,dst,PIN_CONTROL_MESSAGE_BYTES,&message,original,0))return -1;
    unsigned char *p=message;put16(p,0x20);put32(p+4,PIN_CONTROL_UNIT);put32(p+0xc,0xffffffff);put16(p+0x16,1);
    io->set_source(message,PIN_CONTROL_CLIENT_SID);wire_event(io,"DMM_REQUEST ",PIN_CONTROL_CLIENT_SID,PIN_CONTROL_DMM_SID,message,PIN_CONTROL_MESSAGE_BYTES);
    int handled=pin_control_dmm_message(PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,p,PIN_CONTROL_MESSAGE_BYTES,1);
    if(handled!=1){release_owned(io,dst,&message);return -1;}
    io->set_source(message,PIN_CONTROL_DMM_SID);wire_event(io,"DMM_REPLY ",PIN_CONTROL_DMM_SID,PIN_CONTROL_CLIENT_SID,message,PIN_CONTROL_MESSAGE_BYTES);
    unsigned int handle=u32(p+0xc),bytes=u32(p+0x20);unsigned long long physical=u64(p+0x18);
    unsigned int slot=handle&0x3ff;
    int valid=io->source(message)==PIN_CONTROL_DMM_SID && u16(p)==0x8020 && !u16(p+2) && !u16(p+0xa) && u16(p+8)==1 && u32(p+0x10)==PIN_CONTROL_UNIT &&
        slot<PIN_CONTROL_SLOTS && bytes==PIN_CONTROL_SLOT_BYTES && physical==PIN_CONTROL_PHYSICAL+slot*PIN_CONTROL_SLOT_BYTES;
    state.buffer_handle=handle;state.buffer_bytes=bytes;state.buffer_physical=physical;
    int freed=release_owned(io,dst,&message);
    if(!valid || freed || pin_control_write_ssyn(handle,&state.header_digest))return -1;
    char line[260];snprintf(line,sizeof line,"tid=%ld unit=%#x handle=%#x physical=%#llx cp_virtual=%#x bytes=%u header_fnv64=%016llx format_pending=1 buffer_released=0 pixels_consumed=0",
        sender,PIN_CONTROL_UNIT,handle,physical,PIN_CONTROL_CP_VIRTUAL+slot*PIN_CONTROL_SLOT_BYTES,bytes,state.header_digest);
    event(io,"BUFFER_WRITTEN ",line);return 0;
}
static int format_dmm(const struct full_imaging_io *io,unsigned int dst,unsigned int command,unsigned int option,unsigned int source,void *notify){
    void *message=0;if(allocate_owned(io,dst,PIN_CONTROL_MESSAGE_BYTES,&message,0,notify))return -1;
    unsigned char *p=message;put16(p,command);put32(p+8,state.buffer_handle);
    if(command==0x21)put32(p+4,PIN_CONTROL_UNIT);
    put16(p+0x16,option);io->set_source(message,source);
    wire_event(io,"FORMAT_DMM_REQUEST ",source,PIN_CONTROL_DMM_SID,message,PIN_CONTROL_MESSAGE_BYTES);
    int handled=pin_control_dmm_message(PIN_CONTROL_DMM_SID,source,p,PIN_CONTROL_MESSAGE_BYTES,1);
    int valid=handled==1 && u16(p)==(command|0x8000) && !u16(p+2) && !u16(p+0xa) && u32(p+0xc)==state.buffer_handle;
    if(command==0x24)valid=valid && u16(p+8)==1 && !u32(p+0x10) && u64(p+0x18)==state.buffer_physical && u32(p+0x20)==state.buffer_bytes;
    else valid=valid && !u16(p+8) && u32(p+0x10)==(command==0x21?PIN_CONTROL_UNIT:0);
    if(handled==1){io->set_source(message,PIN_CONTROL_DMM_SID);wire_event(io,"FORMAT_DMM_REPLY ",PIN_CONTROL_DMM_SID,source,message,PIN_CONTROL_MESSAGE_BYTES);}
    int freed=release_owned(io,dst,&message);return valid && !freed?0:-1;
}
static int reference_event(const struct full_imaging_io *io,const char *phase,unsigned int owners,unsigned int opens,unsigned int creator,unsigned int consumer,unsigned int open){
    struct pin_control_references refs;
    if(pin_control_references(state.buffer_handle,&refs) || refs.owners!=owners || refs.opens!=opens ||
       refs.creator!=creator || refs.consumer!=consumer || refs.consumer_open!=open)return -1;
    char line[240];snprintf(line,sizeof line,"tid=%ld phase=%s handle=%#x owners=%u opens=%u creator=%u consumer=%u consumer_open=%u",
        sender,phase,refs.handle,refs.owners,refs.opens,refs.creator,refs.consumer,refs.consumer_open);
    format_event(io,"REFERENCE_READBACK ",line);return 0;
}
static int format_postprocess(const struct full_imaging_io *io,unsigned int dst){
    /* This is an explicit virtual cold owner. It holds the original constructor
     * defaults, never labels them AP negotiation, and does not write original
     * firmware state. Unsupported 0f/11 device effects are not acknowledged. */
    const struct pin_yc_parameters parameters={0,1920,1080,1,0};
    state.virtual_vef_status=0;
    state.format_current=(struct pin_yc_current_info){2,1,0,0,0,1920,1080};
    unsigned char packet[PIN_YC_FORMAT_BYTES],readback[PIN_YC_FORMAT_BYTES];
    if(pin_yc_build(&parameters,packet,sizeof packet) || pin_control_write_payload(state.buffer_handle,packet,sizeof packet,&state.format_digest))return -1;
    char line[440];snprintf(line,sizeof line,"tid=%ld handle=%#x physical=%#llx bytes=80 fnv64=%016llx parameter_source=virtual-cold-constructor raw_flags=0 code=1 component=0 width=1920 height=1080 original_negotiation_verified=0",
        sender,state.buffer_handle,state.buffer_physical,state.format_digest);format_event(io,"BUFFER_WRITTEN ",line);
    if(format_dmm(io,dst,0x21,0,PIN_CONTROL_CLIENT_SID,0) || reference_event(io,"shared",2,1,1,1,0))return -1;
    void *notify=0;if(allocate_owned(io,dst,80,&notify,0,0))return -1;
    frame(notify,80,0x104,56,1);attributes((unsigned char *)notify+32,P,S);
    put32((unsigned char *)notify+64,PIN_CONTROL_UNIT);put32((unsigned char *)notify+68,state.buffer_handle);io->set_source(notify,FULL_PINMEM_CP);
    wire_event(io,"FORMAT_NOTIFY_QUEUED ",FULL_PINMEM_CP,FULL_VEF_CP,notify,80);
    /* One valid asynchronous ordering: sender drops its local lease before
     * the accepted VEF notification opens the separately shared reference. */
    if(format_dmm(io,dst,0x23,2,PIN_CONTROL_CLIENT_SID,notify) || reference_event(io,"creator-released",1,0,0,1,0))goto failed;
    unsigned char *n=notify;
    if(!envelope(io,notify,80,0x104,56,1) || u32(n) || io->source(notify)!=FULL_PINMEM_CP ||
       u32(n+64)!=PIN_CONTROL_UNIT || u32(n+68)!=state.buffer_handle || u32(n+72) || u32(n+76))goto failed;
    for(unsigned int i=0;i<4;i++)if(u32(n+32+4*i)!=P[i] || u32(n+48+4*i)!=S[i])goto failed;
    struct full_vef_snapshot registry;full_vef_snapshot(&registry);
    if(memcmp(registry.pins[10].self,S,sizeof S) || memcmp(registry.pins[10].peer,P,sizeof P) || registry.pins[10].state)goto failed;
    if(format_dmm(io,dst,0x24,0,PIN_CONTROL_CONSUMER_SID,notify) || reference_event(io,"consumer-open",1,1,0,1,1) ||
       pin_control_read_consumer(state.buffer_handle,0,readback,sizeof readback))goto failed;
    struct pin_yc_payload payload;
    if(pin_yc_decode(readback,sizeof readback,&payload) || pin_yc_store(&payload,&state.format_current))goto failed;
    unsigned char current[20];put32(current,state.format_current.pin_index);put32(current+4,state.format_current.ordinal);
    current[8]=state.format_current.code;current[9]=state.format_current.component;put16(current+10,state.format_current.encoded_flags);
    put32(current+12,state.format_current.width);put32(current+16,state.format_current.height);
    char hex[41];for(unsigned int i=0;i<sizeof current;i++)snprintf(hex+2*i,3,"%02x",current[i]);hex[40]=0;
    snprintf(line,sizeof line,"tid=%ld handle=%#x source_slot=10 ordinal=1 downstream_pin=%u status=%u status_source=virtual-cold-constructor currentinfo_raw=%s original_runtime_state_verified=0 pixels_consumed=0",
        sender,state.buffer_handle,state.format_current.pin_index,state.virtual_vef_status,hex);format_event(io,"CPU_STATE_READBACK ",line);
    if(state.virtual_vef_status==0xf || state.virtual_vef_status==0x11)goto failed;
    /* Read the existing registry, do not force the downstream pin state. Only
     * the constructor-cold state1 release branch is implemented here. */
    const unsigned int Q[4]={0,1,2,FULL_VEF_CP};
    if(state.format_current.pin_index!=2 || state.format_current.ordinal!=1 ||
       memcmp(registry.pins[2].self,Q,sizeof Q) || registry.pins[2].state!=1)goto failed;
    snprintf(line,sizeof line,"tid=%ld handle=%#x downstream_pin=2 state=1 action=consumer-close-and-owner-release forwarding=0",sender,state.buffer_handle);
    format_event(io,"DOWNSTREAM_READBACK ",line);
    if(format_dmm(io,dst,0x23,2,PIN_CONTROL_CONSUMER_SID,notify))goto failed;
    struct pin_control_references ended;struct pin_control_snapshot pool;pin_control_snapshot(&pool);
    if(pin_control_references(state.buffer_handle,&ended)==0 || pool.live || pool.faults)goto failed;
    if(release_owned(io,dst,&notify))return -1;
    state.buffer_released=1;state.format_consumed=1;state.format_pending=0;
    snprintf(line,sizeof line,"tid=%ld handle=%#x live=0 owners=0 opens=0 buffer_released=1 format_cpu_consumed=1 pinmem_postprocess_pending=0 frame_ready=0 pixels_consumed=0 camera_startup_verified=0",
        sender,state.buffer_handle);format_event(io,"COMMIT ",line);return 0;
failed:
    release_owned(io,dst,&notify);return -1;
}
int full_pin_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,int enabled,int *result){
    if((enabled!=1 && enabled!=2) || (destination!=FULL_VEF_CP && destination!=FULL_PINMEM_CP) || !io || !result)return 0;
    if(!current_process()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source){*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    if(state.faults){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    if(io->size(request)<24){pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    unsigned int source=io->source(request),dst=u32(request);
    if(state.format_pending && destination==FULL_PINMEM_CP){
        if(!envelope(io,request,48,0,24,2) || source>>28!=8 || dst>>28!=8 || !(source&0xfffffff) || !(dst&0xfffffff) || state.blocked_requests==8 || request==reply){
            pthread_mutex_unlock(&mutex);*result=-1021;return 1;
        }
        for(unsigned int i=0;i<state.blocked_requests;i++)if(blocked[i]==request){
            fault(io,"duplicate-blocked-request");pthread_mutex_unlock(&mutex);*result=-1021;return 1;
        }
        blocked[state.blocked_requests++]=request;
        wire_event(io,"FORMAT_BLOCKED_REQUEST ",source,destination,request,48);
        pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    if(destination!=FULL_VEF_CP || io->size(request)!=64){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int s[4],p[4];struct pin_control_snapshot backend;pin_control_snapshot(&backend);
    if(state.started || !backend.bound || backend.faults || !envelope(io,request,64,1,40,2) ||
       source!=dst || source>>28!=8 || !(source&0xfffffff) || !decode_pair(request,s,p)){
        event(io,"UNSUPPORTED ","only-known-edge-with-real-control-backing");pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    state.started=1;state.format_pending=1;state.format_mode=enabled==2;sender=syscall(SYS_gettid);reply_destination=dst;
    wire_event(io,"REQUEST ",source,destination,request,64);
    void *forward=0,*answer=0,*final=0;
    int committed=0;
    if(allocate_owned(io,dst,64,&forward,request,0))goto failed;
    frame(forward,64,0x100,40,1);attributes((unsigned char *)forward+32,s,p);io->set_source(forward,FULL_VEF_CP);
    if(pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),s,p,1))goto failed;
    wire_event(io,"PEER_REQUEST ",FULL_VEF_CP,FULL_PINMEM_CP,forward,64);
    unsigned int a[4],b[4];
    if(!envelope(io,forward,64,0x100,40,1) || io->source(forward)!=FULL_VEF_CP || !decode_pair(forward,a,b) ||
       pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),a,b,2))goto failed;
    state.peer_requests_consumed++;
    if(allocate_owned(io,dst,72,&answer,request,forward))goto failed;
    frame(answer,72,0x8100,48,1);attributes((unsigned char *)answer+32,a,b);io->set_source(answer,FULL_PINMEM_CP);
    wire_event(io,"PEER_REPLY ",FULL_PINMEM_CP,FULL_VEF_CP,answer,72);
    if(release_owned(io,dst,&forward))goto failed;
    if(!envelope(io,answer,72,0x8100,48,1) || io->source(answer)!=FULL_PINMEM_CP || !decode_pair(answer,a,b) ||
       u32((unsigned char *)answer+64) || pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),a,b,3))goto failed;
    state.peer_replies_consumed++;
    if(release_owned(io,dst,&answer))goto failed;
    if(allocate_owned(io,dst,56,&final,request,0))goto failed;
    frame(final,56,0x8001,32,2);for(unsigned int i=0;i<4;i++)put32((unsigned char *)final+32+4*i,s[i]);
    io->set_source(final,FULL_VEF_CP);if(io->source(final)!=FULL_VEF_CP)goto failed;reply=final;
    if(io->send(dst,final)){reply=0;goto failed;}
    final=0;committed=1;wire_event(io,"REPLY_QUEUED ",FULL_VEF_CP,dst,reply,56);
    int request_rc=io->release(FULL_VEF_CP,request);
    char released[180];snprintf(released,sizeof released,"tid=%ld owner=%#x pointer=%p bytes=64 rc=%d",sender,FULL_VEF_CP,request,request_rc);
    event(io,request_rc?"FAULT ":"REQUEST_FREE ",released);
    if(request_rc){if(retained_count<8)retained[retained_count++]=request;fault(io,"original-request-free-failed");goto failed;}
    if(pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),s,p,4))goto failed;
    state.connections++;
    /* The CP message allocation lease is independent of the control-buffer
     * lease. Do not compare new allocations with the now-freed AP request. */
    if(buffer_postprocess(io,dst,0))goto failed;
    struct full_vef_snapshot source_state,peer_state;
    full_vef_snapshot(&source_state);full_pinmem_snapshot(&peer_state);
    const struct full_vef_pin *source_pin=&source_state.pins[10],*peer_pin=&peer_state.pins[1];
    if(source_pin->state || peer_pin->state || source_state.pending || source_state.faults || peer_state.faults ||
       memcmp(source_pin->self,S,sizeof S) || memcmp(source_pin->peer,P,sizeof P) ||
       memcmp(peer_pin->self,P,sizeof P) || memcmp(peer_pin->peer,S,sizeof S))goto failed;
    char readback[520];
    snprintf(readback,sizeof readback,"tid=%ld source_slot=10 source_state=%u source_self=%u,%u,%u,%#x source_peer=%u,%u,%u,%#x peer_slot=1 peer_state=%u peer_self=%u,%u,%u,%#x peer_peer=%u,%u,%u,%#x source_pending=%u format_pending=1",
        sender,source_pin->state,source_pin->self[0],source_pin->self[1],source_pin->self[2],source_pin->self[3],
        source_pin->peer[0],source_pin->peer[1],source_pin->peer[2],source_pin->peer[3],peer_pin->state,
        peer_pin->self[0],peer_pin->self[1],peer_pin->self[2],peer_pin->self[3],peer_pin->peer[0],peer_pin->peer[1],peer_pin->peer[2],peer_pin->peer[3],source_state.pending);
    event(io,"STATE_READBACK ",readback);
    if(state.format_mode && format_postprocess(io,dst))goto failed;
    event(io,"COMMIT ",state.format_mode?"metadata_connected=1 format_pending=0 buffer_released=1 pixels_consumed=0 camera_startup_verified=0":
        "metadata_connected=1 format_pending=1 buffer_released=0 pixels_consumed=0 camera_startup_verified=0");
    pthread_mutex_unlock(&mutex);*result=0;return 1;
failed:
    release_owned(io,dst,&forward);release_owned(io,dst,&answer);release_owned(io,dst,&final);
    fault(io,committed?"post-reply-resource-failure":"connection-message-failure");
    pthread_mutex_unlock(&mutex);*result=committed?0:-1021;return 1;
}
int full_pin_connection_release(unsigned int destination,void *message,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *result){
    if(!message || !release || !result)return 0;
    if(!current_process()){if(message!=reply)return 0;*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    if(message!=reply){pthread_mutex_unlock(&mutex);return 0;}
    *result=destination==reply_destination?release(destination,message):-1021;
    long tid=syscall(SYS_gettid);
    if(*result)state.faults++;
    else{reply=0;state.native_reply_frees++;state.waiter_frees+=(tid==sender);}
    if(record){char line[240];snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p bytes=56 command=0x8001 rc=%d",tid,sender,tid==sender,destination,reply_destination,message,*result);
        record(*result?"FULL_PIN_CONNECT_FAULT ":"FULL_PIN_CONNECT_NATIVE_REPLY_FREE ",line);}
    pthread_mutex_unlock(&mutex);return 1;
}
void full_pin_connection_snapshot(struct pin_connection_snapshot *out){
    if(!out)return;
    if(!current_process()){*out=(struct pin_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_PIN_CONNECTION_TEST
void full_pin_connection_test_reset(void){
    pthread_mutex_lock(&mutex);state=(struct pin_connection_snapshot){0};reply=0;memset(blocked,0,sizeof blocked);memset(retained,0,sizeof retained);retained_count=reply_destination=0;sender=0;atomic_store(&process_pid,(int)getpid());pthread_mutex_unlock(&mutex);
}
#endif
