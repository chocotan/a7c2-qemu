/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-state-publication.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local unsigned int inspecting;
static struct native_cp_state_publication_snapshot state;
static struct full_imaging_io transport;
static unsigned char wires[CP_STATE_PUBLICATION_LEASES][CP_STATE_SNAPSHOT_BYTES];
static unsigned int started[CP_STATE_PUBLICATION_LEASES];
static long tid(void) {return syscall(SYS_gettid);}
static int inherited(void) {int p=atomic_load(&owner_pid);return p && p!=getpid();}
static unsigned int u16(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8;}
static int span(const void *p,size_t n) {return p && n<=UINTPTR_MAX-(uintptr_t)p;}
static int overlaps(const void *a,size_t an,const void *b,size_t bn) {
    return (uintptr_t)a<(uintptr_t)b+bn && (uintptr_t)b<(uintptr_t)a+an;
}
static uint64_t hash(const void *p,size_t n) {
    const unsigned char *b=p;uint64_t h=UINT64_C(14695981039346656037);
    for(size_t i=0;i<n;i++) {h^=b[i];h*=UINT64_C(1099511628211);}return h;
}
static void fault(unsigned int index) {
    state.faults=1;state.leases[index].faults=1;
    state.start_complete=state.mode1_complete=0;
}
static void refresh(void) {
    struct native_cp_state_publication_lease *s=state.leases;
    for(unsigned int i=0;i<CP_STATE_PUBLICATION_LEASES;i++) {
        s[i].consumed=s[i].role!=1 && s[i].queued && s[i].freed && !s[i].faults &&
            !s[i].send_inflight && !s[i].releasing && !s[i].send_rc && !s[i].free_rc &&
            (s[i].role==2?s[i].free_tid==s[i].sender_tid:s[i].received && s[i].free_tid==s[i].receiver_tid);
    }
    state.start_complete=state.start_requests && s[0].freed && s[1].consumed && !state.faults && !state.busy;
    state.mode1_complete=state.mode1_requests && s[2].freed && s[3].consumed && s[4].consumed && !state.faults && !state.busy;
    state.notification_queued=s[4].queued;
    state.notification_ap_consumed=s[4].consumed;
    if(s[4].consumed && !state.faults)state.shadow_generation=state.published_generation;
}
int native_cp_state_publication_owner_init(void) {
    int pid=getpid(),expected=0;atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(atomic_load(&owner_pid)!=pid)return -EXDEV;
    pthread_mutex_lock(&mutex);
    if(state.initialized) {pthread_mutex_unlock(&mutex);return -EALREADY;}
    state.owner_pid=pid;state.initialized=1;pthread_mutex_unlock(&mutex);return 0;
}
void native_cp_state_publication_snapshot(struct native_cp_state_publication_snapshot *out) {
    if(!out)return;
    if(inherited()) {*out=(struct native_cp_state_publication_snapshot){.owner_pid=atomic_load(&owner_pid),.faults=1};return;}
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
static void record(void (*logger)(const char *,const char *),const char *event,unsigned int index) {
    if(!logger)return;
    struct native_cp_state_publication_snapshot s;native_cp_state_publication_snapshot(&s);
    struct native_cp_state_publication_lease l=s.leases[index];char tag[96],text[1100];
    snprintf(tag,sizeof tag,"NATIVE_CP_STATE_PUBLICATION_%s ",event);
    snprintf(text,sizeof text,"pid=%d tid=%ld index=%u role=%u bytes=%u destination=%#x source=%#x wire_fnv1a=%016llx queued=%u received=%u freed=%u consumed=%u sender_tid=%ld receiver_tid=%ld free_tid=%ld allocate_rc=%d send_rc=%d free_rc=%d retained=%p faults=%u busy=%u guard=%u start_complete=%u mode1_complete=%u start_known=%u full_layout_copied=%u published_generation=%u shadow_generation=%u notification_AP_consumed=%u owned_data_transport=1 business_applied=0 original_CP=0 EE=0 frame=0 capture=0",
        s.owner_pid,tid(),index,l.role,l.bytes,l.destination,l.source,(unsigned long long)l.wire_fnv1a64,
        l.queued,l.received,l.freed,l.consumed,l.sender_tid,l.receiver_tid,l.free_tid,l.allocate_rc,l.send_rc,l.free_rc,
        l.pointer,s.faults,s.busy,s.guard_held,s.start_complete,s.mode1_complete,s.start_data_known_mask,
        s.full_layout_copied,s.published_generation,s.shadow_generation,s.notification_ap_consumed);
    logger(tag,text);
}
static int release_owned(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
    void (*logger)(const char *,const char *),int *result,int internal) {
    if(!pointer || !release || !result)return 0;
    if(inherited()) {*result=-EXDEV;return 1;}
    pthread_mutex_lock(&mutex);unsigned int index;
    for(index=0;index<CP_STATE_PUBLICATION_LEASES;index++)if(state.leases[index].pointer==pointer)break;
    if(index==CP_STATE_PUBLICATION_LEASES) {pthread_mutex_unlock(&mutex);return 0;}
    struct native_cp_state_publication_lease l=state.leases[index];struct full_imaging_io io=transport;
    long current=tid();int permitted=destination==l.destination && !l.releasing &&
        (internal || (l.role==2 && started[index] && current==l.sender_tid) ||
         (l.role==3 && started[index] && l.received && current==l.receiver_tid));
    if(!permitted) {fault(index);pthread_mutex_unlock(&mutex);*result=-EPROTO;return 1;}
    state.leases[index].releasing=1;pthread_mutex_unlock(&mutex);
    int valid=internal || (io.size && io.source && io.size(pointer)==l.bytes &&
        io.source(pointer)==l.source && !memcmp(pointer,wires[index],l.bytes));
    int rc=valid?release(destination,pointer):-EPROTO;
    pthread_mutex_lock(&mutex);state.leases[index].releasing=0;state.leases[index].free_rc=rc;
    if(rc)fault(index);
    else {state.leases[index].pointer=NULL;state.leases[index].freed=1;state.leases[index].free_tid=current;}
    refresh();pthread_mutex_unlock(&mutex);record(logger,internal?"OWNED_FREE":"AP_FREE",index);*result=rc;return 1;
}
int native_cp_state_publication_release(unsigned int destination,void *pointer,
    int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result) {
    return release_owned(destination,pointer,release,logger,result,0);
}
int native_cp_state_publication_observe_receive(unsigned int destination,void *pointer,unsigned int source,unsigned int bytes) {
    if(inherited())return -EXDEV;
    pthread_mutex_lock(&mutex);struct native_cp_state_publication_lease l=state.leases[4];struct full_imaging_io io=transport;
    if(!pointer || l.pointer!=pointer) {pthread_mutex_unlock(&mutex);return 0;}
    if(!started[4] || destination!=l.destination || source!=l.source || bytes!=l.bytes ||
       l.releasing || l.received) {fault(4);pthread_mutex_unlock(&mutex);return -EPROTO;}
    state.leases[4].releasing=1;pthread_mutex_unlock(&mutex);
    int valid=io.size && io.source && io.size(pointer)==bytes && io.source(pointer)==source &&
        !memcmp(pointer,wires[4],bytes);
    pthread_mutex_lock(&mutex);state.leases[4].releasing=0;
    if(valid && !state.faults) {state.leases[4].received=1;state.leases[4].receiver_tid=tid();}
    else {fault(4);valid=0;}
    pthread_mutex_unlock(&mutex);return valid?1:-EPROTO;
}
static void finish(const struct native_cp_state_publication_guard *guard) {
    pthread_mutex_lock(&mutex);unsigned int held=state.guard_held;state.guard_held=0;pthread_mutex_unlock(&mutex);
    if(held)guard->release();
    pthread_mutex_lock(&mutex);state.busy=0;refresh();pthread_mutex_unlock(&mutex);
}
static int allocate_message(unsigned int index,unsigned int bytes,const struct full_imaging_io *io) {
    void *p=NULL;int rc=io->allocate(NATIVE_CP_STATE_PUBLICATION_AP,&p,bytes,1);
    int valid=!rc && span(p,bytes);
    pthread_mutex_lock(&mutex);
    if(p)for(unsigned int i=0;i<CP_STATE_PUBLICATION_LEASES;i++) {
        struct native_cp_state_publication_lease *l=&state.leases[i];
        if(l->pointer && (!span(l->pointer,l->bytes) || overlaps(p,bytes,l->pointer,l->bytes)))valid=0;
    }
    int alias=0;
    if(p)for(unsigned int i=0;i<CP_STATE_PUBLICATION_LEASES;i++) {
        struct native_cp_state_publication_lease *l=&state.leases[i];
        if(l->pointer && span(l->pointer,l->bytes) && span(p,bytes) && overlaps(p,bytes,l->pointer,l->bytes))alias=1;
    }
    struct native_cp_state_publication_lease *l=&state.leases[index];
    l->bytes=bytes;l->destination=NATIVE_CP_STATE_PUBLICATION_AP;l->source=NATIVE_CP_STATE_PUBLICATION_SID;
    l->role=index==4?3u:2u;l->sender_tid=tid();l->allocate_rc=rc;
    if(p && !alias)l->pointer=p;
    if(!valid)fault(index);
    pthread_mutex_unlock(&mutex);
    if(valid) {
        valid=io->size(p)==bytes;
        if(valid) {memcpy(p,wires[index],bytes);io->set_source(p,NATIVE_CP_STATE_PUBLICATION_SID);
            valid=io->size(p)==bytes && io->source(p)==NATIVE_CP_STATE_PUBLICATION_SID && !memcmp(p,wires[index],bytes);}
        if(!valid) {pthread_mutex_lock(&mutex);fault(index);pthread_mutex_unlock(&mutex);}
    }
    pthread_mutex_lock(&mutex);l->wire_fnv1a64=hash(wires[index],bytes);pthread_mutex_unlock(&mutex);
    return valid?0:rc?rc:-EPROTO;
}
static int send_message(unsigned int index,const struct full_imaging_io *io) {
    pthread_mutex_lock(&mutex);void *p=state.leases[index].pointer;
    int valid=p && !state.faults;
    if(valid) {started[index]=1;state.leases[index].send_inflight=1;}
    pthread_mutex_unlock(&mutex);if(!valid)return -EPROTO;
    int rc=io->send(NATIVE_CP_STATE_PUBLICATION_AP,p);
    pthread_mutex_lock(&mutex);state.leases[index].send_inflight=0;state.leases[index].send_rc=rc;
    if(rc)fault(index);else state.leases[index].queued=1;
    refresh();pthread_mutex_unlock(&mutex);record(io->record,"SENT",index);return rc;
}
int native_cp_state_publication_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard,const struct native_cp_state_publication_providers *providers,
    int enabled,int *result) {
    if(enabled!=1 || destination!=NATIVE_CP_STATE_PUBLICATION_SID || !request || !io || !io->size || !result)return 0;
    if(inherited() || inspecting) {*result=-EXDEV;return 1;}
    inspecting=1;unsigned int bytes=io->size(request);inspecting=0;
    if(bytes<4 || !span(request,bytes))return 0;
    const unsigned char *p=request;unsigned int command=u16(p+2);
    int start=p[0]==0 && (command==0x3003 || command==0x3000);
    int mode=p[0]==5 && command==0x4073 && bytes==12 && p[8]==1;
    if(!start && !mode)return 0;
    *result=CP_STATE_PUBLICATION_BLOCKED;
    if(bytes!=(start?24u:12u) || !io->source || !io->allocate || !io->set_source || !io->send || !io->release ||
       !guard || !guard->reserve || !guard->release || !guard->predecessor_ready || !providers ||
       (start?!providers->start:!providers->full))return 1;
    for(unsigned int i=8;start && i<24;i++)if(p[i])return 1;
    inspecting=1;unsigned int caller=io->source(request);inspecting=0;
    if(caller!=NATIVE_CP_STATE_PUBLICATION_AP)return 1;
    unsigned char saved[24];memcpy(saved,request,bytes);
    pthread_mutex_lock(&mutex);
    int ready=state.initialized && !state.busy && !state.faults &&
        (start?!state.start_requests:state.start_complete && !state.mode1_requests);
    if(ready)state.busy=1;
    pthread_mutex_unlock(&mutex);if(!ready)return 1;
    int rc=guard->reserve();
    if(rc) {finish(guard);*result=rc;return 1;}
    pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    if(guard->predecessor_ready()!=1) {finish(guard);return 1;}
    struct cp_state_snapshot full={0};struct cp_start_state_readback data={0};unsigned char reply[16]={1,0,0,0,0,0,0,0,0,0xf0,0,0};
    if(start) {
        struct cp_start_state_data source={0};struct cp_start_state_guard source_guard={0};
        rc=providers->start(providers->context,&source,&source_guard);
        if(!rc && source_guard.source_origin!=CP_START_STATE_ORIGIN_VIRTUAL_SOURCE)rc=-EXDEV;
        if(!rc)rc=cp_start_state_data_snapshot(&source,&source_guard,&data);
        if(!rc)rc=cp_start_state_data_build_reply(&source,&source_guard,(uint16_t)command,
            (uint32_t)saved[4]|(uint32_t)saved[5]<<8|(uint32_t)saved[6]<<16|(uint32_t)saved[7]<<24,reply,16);
    } else {
        struct cp_state_snapshot supplied={0};rc=providers->full(providers->context,&supplied);
        if(!rc) {
            struct cp_state_snapshot_input input={supplied.bytes,supplied.known,CP_STATE_SNAPSHOT_BYTES,
                CP_STATE_SNAPSHOT_BYTES,supplied.generation};
            rc=cp_full_state_snapshot_copy(&input,&full);
            pthread_mutex_lock(&mutex);
            if(!rc && full.generation.shadow_generation!=state.shadow_generation)rc=-ESTALE;
            pthread_mutex_unlock(&mutex);
        }
        reply[2]=0x73;reply[3]=0x40;memcpy(reply+4,saved+4,4);
    }
    if(rc || guard->predecessor_ready()!=1 || io->size(request)!=bytes || io->source(request)!=caller || memcmp(request,saved,bytes)) {
        pthread_mutex_lock(&mutex);state.provider_rc=rc?rc:CP_STATE_PUBLICATION_BLOCKED;state.provider_refusals++;pthread_mutex_unlock(&mutex);
        finish(guard);*result=rc?rc:CP_STATE_PUBLICATION_BLOCKED;return 1;
    }
    unsigned int req=start?0u:2u,ack=req+1u;
    pthread_mutex_lock(&mutex);transport=*io;
    struct native_cp_state_publication_lease *l=&state.leases[req];
    *l=(struct native_cp_state_publication_lease){.role=1,.bytes=bytes,.destination=destination,.source=caller,.sender_tid=tid(),.pointer=request};
    memcpy(wires[req],saved,bytes);l->wire_fnv1a64=hash(saved,bytes);
    memcpy(wires[ack],reply,start?16u:12u);
    if(mode)memcpy(wires[4],full.bytes,CP_STATE_SNAPSHOT_BYTES);
    pthread_mutex_unlock(&mutex);
    rc=allocate_message(ack,start?16u:12u,io);
    if(!rc && mode)rc=allocate_message(4,CP_STATE_SNAPSHOT_BYTES,io);
    if(rc) {
        pthread_mutex_lock(&mutex);state.leases[req].pointer=NULL;pthread_mutex_unlock(&mutex);
        for(unsigned int i=ack;i<=4;i++) {
            pthread_mutex_lock(&mutex);void *cleanup=state.leases[i].pointer;pthread_mutex_unlock(&mutex);
            if(cleanup) {int freed;release_owned(caller,cleanup,io->release,io->record,&freed,1);}
        }
        finish(guard);*result=rc;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(start) {state.start_requests=1;state.start_data_known_mask=data.known_mask;}
    else {state.mode1_requests=1;state.full_layout_copied=state.full_source_copied=state.publication_copied=1;
        state.published_generation=full.generation.published_generation;}
    pthread_mutex_unlock(&mutex);
    rc=send_message(ack,io);
    if(!rc && mode) {
        pthread_mutex_lock(&mutex);state.notification_mode=1;pthread_mutex_unlock(&mutex);
        rc=send_message(4,io);
    }
    int freed;
    if(!rc)release_owned(destination,request,io->release,io->record,&freed,1);
    else for(unsigned int i=ack;i<=4;i++) {
        pthread_mutex_lock(&mutex);void *cleanup=state.leases[i].pointer;
        int can_clean=cleanup && !state.leases[i].queued && !state.leases[i].releasing;
        pthread_mutex_unlock(&mutex);
        if(can_clean)release_owned(caller,cleanup,io->release,io->record,&freed,1);
    }
    finish(guard);record(io->record,rc?"FAULT":"COMMIT",ack);*result=0;return 1;
}
