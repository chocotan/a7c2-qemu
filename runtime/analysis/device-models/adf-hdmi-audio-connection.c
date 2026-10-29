/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "adf-hdmi-audio-connection.h"
#include "pinmem-drawinfo-connection.h"
#include "pin-registry-core.h"
#include "adf-device.h"
#include "hdmi-pin-device.h"
#include "hdmi-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
/* Exported by the shared registry integration, never a second HDMI owner. */
struct pin_registry_owner *full_hdmi_pin_registry(void);
#define SOURCE FULL_ADF_CP
#define PEER FULL_HDMI_PIN_CP
static const unsigned int S[4]={5,2,0,SOURCE},P[4]={5,1,0,PEER};
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_adf_hdmi_audio_connection_snapshot state;
static void *messages[3],*current_request;
struct predecessors {
    struct scalar_connection_snapshot tenth;
    struct full_vef_snapshot source,peer;
    struct full_hdmi_snapshot hdmi;
};
static int pid_matches(void){return atomic_load(&owner_pid)==(int)getpid();}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int n){p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8);}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_ADF_HDMI_AUDIO_CONNECT_%s",kind);io->record(tag,text);}
}
static void fail(const struct full_imaging_io *io,const char *reason){
    pthread_mutex_lock(&mutex);state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);event(io,"FAULT ",reason);
}
static void wire(const struct full_imaging_io *io,const char *kind,unsigned int src,unsigned int dst,void *pointer,const unsigned char *p,unsigned int n){
    char raw[145],line[500];for(unsigned int i=0;i<n;i++)snprintf(raw+2*i,3,"%02x",p[i]);raw[2*n]=0;
    snprintf(line,sizeof line,"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s original_CP_executed=0 capture_verified=0",getpid(),syscall(SYS_gettid),src,dst,pointer,n,raw);event(io,kind,line);
}
static void frame(unsigned char *p,unsigned int n,unsigned int op,unsigned int kind){
    memset(p,0,n);put32(p+4,0xa0a0a0a0);put16(p+8,1);put16(p+10,n);put32(p+12,24);put32(p+16,n);
    put16(p+24,0x1000);put16(p+26,op);put16(p+28,n-24);put16(p+30,kind);
}
static void pair(unsigned char *p){for(unsigned int i=0;i<4;i++){put32(p+32+4*i,S[i]);put32(p+48+4*i,P[i]);}}
static int is_pair(const unsigned char *p){for(unsigned int i=0;i<4;i++)if(u32(p+32+4*i)!=S[i] || u32(p+48+4*i)!=P[i])return 0;return 1;}
static int canonical(const struct full_imaging_io *io,void *p,const unsigned char *expected,unsigned int n,unsigned int src){
    return p && io->size(p)==n && io->source(p)==src && !memcmp(p,expected,n);
}
static void capture(struct predecessors *p){
    memset(p,0,sizeof *p);full_pinmem_drawinfo_connection_snapshot(&p->tenth);full_adf_snapshot(&p->source);full_hdmi_pin_snapshot(&p->peer);full_hdmi_snapshot(&p->hdmi);
}
static int cold(const struct full_vef_pin *p,const unsigned int *self){
    static const unsigned int empty[4]={0xff,0xff,0,0};return p->state==1 && !memcmp(p->self,self,sizeof p->self) && !memcmp(p->peer,empty,sizeof empty);
}
static int quiet(const struct full_vef_snapshot *p,unsigned int sid,unsigned int count){
    return p->initialized && p->owner_sid==sid && p->registry_objects==count && p->queries>=1 && p->queries==p->queued &&
        p->request_freed==p->queries && p->native_freed==p->queries && p->waiter_freed==p->queries &&
        !p->pending && !p->faults && !p->live_replies && !p->retained_request && !p->retained_reply;
}
static int dependencies(struct predecessors *p){
    capture(p);const struct scalar_connection_snapshot *t=&p->tenth;
    return t->owner_pid==getpid() && t->initialized && t->native_guarded && t->clean_completion && t->ap_consumed==1 && t->connections==1 &&
        t->requests==1 && t->queued==1 && t->request_freed==1 && t->reply_freed==1 && t->native_reply_frees==1 && t->waiter_frees==1 &&
        !t->pending_event6 && t->event6_consumed==1 && !t->faults && !t->busy && !t->guard_held && !t->retained_messages && !t->releasing_reply &&
        !t->live_reply && !t->retained_request && !t->retained_cleanup && quiet(&p->source,SOURCE,10) && quiet(&p->peer,PEER,2) &&
        pin_registry_key_get_retired(full_adf_registry(),S) && pin_registry_key_get_retired(full_hdmi_pin_registry(),P) &&
        cold(&p->source.pins[9],S) && cold(&p->peer.pins[1],P) &&
        !p->hdmi.faults && !p->hdmi.pending && !p->hdmi.live_replies && !p->hdmi.retained_request && !p->hdmi.retained_reply &&
        !p->hdmi.audio_pin_connected_known && !p->hdmi.audio_pin_connected_writes;
}
static int preserved(const struct predecessors *before,unsigned int pending,int marker){
    struct predecessors after;capture(&after);
    if(after.source.pending!=pending || after.peer.pending || memcmp(&after.source.pins[9].self,S,sizeof S) || memcmp(&after.peer.pins[1].self,P,sizeof P) ||
        after.source.pins[9].state || after.peer.pins[1].state || memcmp(after.source.pins[9].peer,P,sizeof P) || memcmp(after.peer.pins[1].peer,S,sizeof S))return -1;
    after.source.pins[9]=before->source.pins[9];after.source.pending=before->source.pending;after.peer.pins[1]=before->peer.pins[1];
    if(marker){
        if(after.hdmi.audio_pin_connected!=1 || after.hdmi.audio_pin_connected_known!=1 || after.hdmi.audio_pin_connected_writes!=1 || after.hdmi.audio_pin_connected_owner_pid!=getpid())return -1;
        after.hdmi.audio_pin_connected=before->hdmi.audio_pin_connected;after.hdmi.audio_pin_connected_known=before->hdmi.audio_pin_connected_known;
        after.hdmi.audio_pin_connected_writes=before->hdmi.audio_pin_connected_writes;after.hdmi.audio_pin_connected_owner_pid=before->hdmi.audio_pin_connected_owner_pid;
    }
    return memcmp(&after,before,sizeof after)?-1:0;
}
static void forget(void *p){for(unsigned int i=0;i<3;i++)if(messages[i]==p){messages[i]=0;break;}}
static int drop(const struct full_imaging_io *io,unsigned int dst,void **p){
    if(!*p)return 0;
    void *pointer=*p;int rc=io->release(dst,pointer);
    pthread_mutex_lock(&mutex);if(rc){state.faults++;state.clean_completion=0;if(!state.retained_cleanup)state.retained_cleanup=pointer;}else forget(pointer);pthread_mutex_unlock(&mutex);
    char text[160];snprintf(text,sizeof text,"pid=%d destination=%#x pointer=%p rc=%d",getpid(),dst,pointer,rc);event(io,rc?"CLEANUP_FAULT ":"INTERNAL_FREE ",text);*p=0;return rc;
}
static int make(const struct full_imaging_io *io,unsigned int dst,unsigned int n,void **out){
    *out=0;int rc=io->allocate(dst,out,n,1);
    pthread_mutex_lock(&mutex);unsigned int slot=3;int alias=*out && (*out==current_request || *out==state.live_reply);
    for(unsigned int i=0;i<3;i++){if(messages[i] && messages[i]==*out)alias=1;if(!messages[i] && slot==3)slot=i;}
    if(alias || (*out && slot==3)){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*out=0;event(io,"FAULT ","allocator-returned-live-message-or-capacity");return -1;}
    if(*out)messages[slot]=*out;
    pthread_mutex_unlock(&mutex);
    if(rc || !*out || io->size(*out)!=n){if(*out)drop(io,dst,out);return -1;}
    memset(*out,0,n);return 0;
}
static int source_set(const struct full_imaging_io *io,void *p,unsigned int sid){io->set_source(p,sid);return io->source(p)==sid?0:-1;}
static int healthy(void){pthread_mutex_lock(&mutex);int ok=!state.faults;pthread_mutex_unlock(&mutex);return ok;}
int full_adf_hdmi_audio_connection_owner_init(void){
    int expected=0,pid=(int)getpid();atomic_compare_exchange_strong(&owner_pid,&expected,pid);if(!pid_matches())return -1021;
    pthread_mutex_lock(&mutex);if(!state.initialized){state.initialized=1;state.owner_pid=pid;state.source_slot=9;state.peer_ordinal=1;}pthread_mutex_unlock(&mutex);return 0;
}
void full_adf_hdmi_audio_connection_snapshot(struct full_adf_hdmi_audio_connection_snapshot *out){
    if(!out)return;
    if(!pid_matches()){*out=(struct full_adf_hdmi_audio_connection_snapshot){0};return;}
    pthread_mutex_lock(&mutex);*out=state;out->retained_messages=0;for(unsigned int i=0;i<3;i++)out->retained_messages+=messages[i]!=0;pthread_mutex_unlock(&mutex);
}
static int unadmitted(const struct full_imaging_io *io,int *result,const char *reason){
    pthread_mutex_lock(&mutex);state.unadmitted_count++;pthread_mutex_unlock(&mutex);event(io,"UNADMITTED ",reason);*result=-1021;return 1;
}
int full_adf_hdmi_audio_connection_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,const struct full_adf_proc_guard *guard,int enabled,int *result){
    if(enabled!=1 || destination!=SOURCE || !io || !result)return 0;
    if(!pid_matches()){*result=-1021;return 1;}
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    if(io->size(request)!=64 || !is_pair(request))return 0;
    unsigned int dst=u32(request),src=io->source(request);unsigned char original[64];frame(original,64,1,2);pair(original);put32(original,dst);memcpy(original+20,(unsigned char *)request+20,4);
    if(src!=dst || src>>28!=8 || !(src&0xfffffff) || !canonical(io,request,original,64,src)){event(io,"UNSUPPORTED ","only-canonical-full-key-audio-connection");*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);int ready=state.initialized && !state.busy && !state.faults && !state.requests && !state.live_reply;pthread_mutex_unlock(&mutex);
    if(!ready){*result=-1021;return 1;}
    struct predecessors before;
    if(!dependencies(&before))return unadmitted(io,result,"actual_tenth_AP_free_or_cold_Get_not_ready=1 requests=0 faults_unchanged=1");
    if(guard->reserve())return unadmitted(io,result,"resource_guard_busy=1 requests=0 faults_unchanged=1");
    if(!dependencies(&before)){guard->release();return unadmitted(io,result,"guarded_predecessor_readback_failed=1 requests=0 faults_unchanged=1");}
    pthread_mutex_lock(&mutex);
    if(state.busy || state.faults || state.requests || state.live_reply){pthread_mutex_unlock(&mutex);guard->release();*result=-1021;return 1;}
    state.busy=state.guard_held=state.native_guarded=state.requests=1;state.reply_destination=dst;state.sender_tid=syscall(SYS_gettid);
    memcpy(state.saved_request,original,64);state.marker_old_known=before.hdmi.audio_pin_connected_known;state.marker_old=before.hdmi.audio_pin_connected;current_request=request;pthread_mutex_unlock(&mutex);
    int queued=0;void *forward=0,*answer=0,*final=0;unsigned char expected[72];
    wire(io,"REQUEST ",src,destination,request,original,64);
    if(!canonical(io,request,original,64,src) || !healthy() || make(io,dst,64,&forward))goto failed;
    frame(expected,64,0x100,1);pair(expected);memcpy(forward,expected,64);
    if(source_set(io,forward,SOURCE) || pin_registry_connect_step(full_adf_registry(),full_hdmi_pin_registry(),S,P,1))goto failed;
    wire(io,"PEER_REQUEST ",SOURCE,PEER,forward,forward,64);
    if(!canonical(io,forward,expected,64,SOURCE) || !canonical(io,request,original,64,src) || !healthy() || pin_registry_connect_step(full_adf_registry(),full_hdmi_pin_registry(),S,P,2))goto failed;
    pthread_mutex_lock(&mutex);state.peer_requests=1;state.source_state=2;state.peer_state=0;pthread_mutex_unlock(&mutex);
    if(make(io,dst,72,&answer))goto failed;
    frame(expected,72,0x8100,1);pair(expected);memcpy(answer,expected,72);
    if(source_set(io,answer,PEER))goto failed;
    wire(io,"PEER_REPLY ",PEER,SOURCE,answer,answer,72);
    if(!canonical(io,answer,expected,72,PEER) || !canonical(io,request,original,64,src) || !healthy())goto failed;
    /* raw1295a2 calls base583818 before the business hook. The native owner
     * validates that peer reply before writing the shared HDMI byte. */
    if(full_hdmi_audio_pin_connected_one())goto failed;
    struct full_hdmi_snapshot hdmi;full_hdmi_snapshot(&hdmi);
    if(hdmi.audio_pin_connected!=1 || hdmi.audio_pin_connected_known!=1 || hdmi.audio_pin_connected_writes!=1 || hdmi.audio_pin_connected_owner_pid!=getpid())goto failed;
    pthread_mutex_lock(&mutex);state.marker_known=hdmi.audio_pin_connected_known;state.marker_value=hdmi.audio_pin_connected;
    state.marker_writes=hdmi.audio_pin_connected_writes;state.marker_owner_pid=hdmi.audio_pin_connected_owner_pid;state.marker_readbacks=1;pthread_mutex_unlock(&mutex);
    event(io,"HDMI_MARKER_READBACK ","hook_raw=0x1297fe Generic_tag_ADF_byte4=1 state_vtable_offset=0x34 old_known=0 connected=1 known=1 writes=1 readback=1 singleton_offset=0x60 next_state_null=1 state_identity_known=0 original_CP_memory_identity_verified=0 DMM=0 SSYN=0 clocks=0 PCM=0 MMIO=0 capture_verified=0");
    full_hdmi_snapshot(&hdmi);
    if(!canonical(io,answer,expected,72,PEER) || !canonical(io,request,original,64,src) || !healthy() ||
        hdmi.audio_pin_connected!=1 || hdmi.audio_pin_connected_known!=1 || hdmi.audio_pin_connected_writes!=1 || pin_registry_connect_step(full_adf_registry(),full_hdmi_pin_registry(),S,P,3))goto failed;
    pthread_mutex_lock(&mutex);state.peer_replies=state.source_handler_completed=state.posthook_checked=1;state.source_state=0;pthread_mutex_unlock(&mutex);
    event(io,"SOURCE_COMPLETED ","handler_raw=0x1976d8 method_CP_VA=0x68b9a6 source=5,2,0 complete_direct=1 event6=0 event8=0 postguard_raw=0x1977e0 selected_type5_dir1_index0=0 format_published=0 source_state=0 capture_verified=0");
    if(!canonical(io,request,original,64,src) || !healthy() || drop(io,dst,&forward) || drop(io,dst,&answer) || preserved(&before,1,1) || make(io,dst,56,&final))goto failed;
    frame(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)put32(expected+32+4*i,S[i]);memcpy(final,expected,56);
    if(source_set(io,final,SOURCE) || !canonical(io,final,expected,56,SOURCE) || !canonical(io,request,original,64,src) || preserved(&before,1,1))goto failed;
    unsigned char final_wire[56];memcpy(final_wire,final,56);
    pthread_mutex_lock(&mutex);
    if(state.faults || current_request!=request || !state.busy || state.retained_request || state.live_reply || state.releasing_reply){pthread_mutex_unlock(&mutex);goto failed;}
    state.live_reply=final;state.predecessor_preserved=1;pthread_mutex_unlock(&mutex);
    if(io->send(dst,final)){
        pthread_mutex_lock(&mutex);if(state.live_reply!=final || state.releasing_reply){state.faults++;state.clean_completion=0;final=0;}else state.live_reply=0;pthread_mutex_unlock(&mutex);goto failed;
    }
    queued=1;wire(io,"REPLY_QUEUED ",SOURCE,dst,final,final_wire,56);
    pthread_mutex_lock(&mutex);state.queued=1;forget(final);pthread_mutex_unlock(&mutex);final=0;
    int freed=io->release(SOURCE,request);
    pthread_mutex_lock(&mutex);state.request_freed=freed==0;if(freed){state.faults++;state.clean_completion=0;state.retained_request=request;}current_request=0;pthread_mutex_unlock(&mutex);
    if(pin_registry_connect_step(full_adf_registry(),full_hdmi_pin_registry(),S,P,4) || preserved(&before,0,1))goto failed;
    pthread_mutex_lock(&mutex);state.connections=1;state.clean_completion=!state.faults && state.request_freed;pthread_mutex_unlock(&mutex);
    event(io,"COMMIT ","connections=1 source_slot=9 peer_ordinal=1 source_state=0 peer_state=0 source_pending=0 marker_known=1 marker=1 marker_writes=1 direct_source_handler=1 format_work=0 prior_ten_and_unrelated_HDMI_pins_preserved=1 original_RTOS_scheduling_verified=0 capture_verified=0");goto done;
failed:
    fail(io,"transaction-incomplete-owned-state-preserved");drop(io,dst,&forward);drop(io,dst,&answer);drop(io,dst,&final);
    pthread_mutex_lock(&mutex);current_request=0;pthread_mutex_unlock(&mutex);
done:
    guard->release();pthread_mutex_lock(&mutex);state.busy=state.guard_held=0;pthread_mutex_unlock(&mutex);*result=queued?0:-1021;return 1;
}
int full_adf_hdmi_audio_connection_release(unsigned int destination,void *reply,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *result){
    if(!reply || !release || !result || !pid_matches())return 0;
    pthread_mutex_lock(&mutex);if(reply!=state.live_reply){pthread_mutex_unlock(&mutex);return 0;}
    unsigned int expected=state.reply_destination;long sender=state.sender_tid,tid=syscall(SYS_gettid);
    if(destination!=expected || state.releasing_reply){state.faults++;state.clean_completion=0;pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    state.releasing_reply=1;pthread_mutex_unlock(&mutex);int rc=release(destination,reply);
    pthread_mutex_lock(&mutex);state.releasing_reply=0;
    if(rc){state.faults++;state.clean_completion=0;}else{
        state.live_reply=0;state.reply_freed=1;state.native_reply_frees++;forget(reply);
        if(tid==sender){state.waiter_frees++;state.ap_consumed=1;}else{state.faults++;state.clean_completion=0;}
    }
    unsigned int faults=state.faults,consumed=state.ap_consumed;pthread_mutex_unlock(&mutex);
    if(record){char line[300];snprintf(line,sizeof line,"pid=%d tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x pointer=%p bytes=56 rc=%d faults=%u ap_consumed=%u capture_verified=0",getpid(),tid,sender,(unsigned int)(tid==sender),destination,expected,reply,rc,faults,consumed);record("FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE ",line);}
    *result=rc;return 1;
}
