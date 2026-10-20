/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "dig-level-device.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct native_dig_level_snapshot state;
static struct lease {void *pointer;unsigned int destination;long sender;unsigned long long serial;} leases[8];
static unsigned int u32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static void event(const struct full_imaging_io *io,const char *kind,const char *text){
    if(io->record){char tag[80];snprintf(tag,sizeof tag,"FULL_DIG_LEVEL_%s",kind);io->record(tag,text);}
}
static int consume(const unsigned char *packet,unsigned int bytes){
    if(bytes!=20 || state.mode!=2 || !state.worker_started || u32(packet)!=3)return -1;
    for(unsigned int i=4;i<20;i++)if(packet[i])return -1;
    state.notification_enabled=1;state.notification_countdown=30;state.consumed++;return 0;
}
int native_dig_level_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,int enabled,int *rc){
    if(enabled!=1 || destination!=NATIVE_DIG_LEVEL_SID || !rc || !io)return 0;
    if(!request || !io->size || !io->source || !io->allocate || !io->release || !io->send || !io->set_source){*rc=-1021;return 1;}
    unsigned int bytes=io->size(request),dst=io->source(request);const unsigned char *in=request;
    if(bytes!=24 || u32(in)!=3 || dst>>28!=8 || !(dst&0xfffffff)){
        event(io,"UNSUPPORTED ","only-observed-selector3-local-24B");*rc=-1021;return 1;
    }
    for(unsigned int i=4;i<24;i++)if(in[i]){event(io,"UNSUPPORTED ","nonzero-observed-reserved-subset");*rc=-1021;return 1;}
    /* OSAL allocation may wait for a prior waiter to free; do not hold its lease lock. */
    void *reply=0;*rc=io->allocate(dst,&reply,24,1);
    pthread_mutex_lock(&mutex);
    struct lease *slot=0;
    for(unsigned int i=0;i<8;i++)if(!leases[i].pointer){slot=&leases[i];break;}
    char text[520];
    snprintf(text,sizeof text,"tid=%ld source=%#x destination=%#x bytes=24 raw=030000000000000000000000000000000000000000000000",syscall(SYS_gettid),dst,destination);
    event(io,"REQUEST ",text);
    if(reply==request){state.faults++;event(io,"FAULT ","allocator-alias-request");pthread_mutex_unlock(&mutex);*rc=-1021;return 1;}
    for(unsigned int i=0;i<8;i++)if(reply && leases[i].pointer==reply){
        state.faults++;event(io,"FAULT ","allocator-alias-live-reply");pthread_mutex_unlock(&mutex);*rc=-1021;return 1;
    }
    if(state.faults || !slot){
        if(reply && io->release(dst,reply)){state.faults++;event(io,"FAULT ","failed-rejected-allocation-cleanup");}
        pthread_mutex_unlock(&mutex);*rc=-1021;return 1;
    }
    if(*rc || !reply){
        if(reply && io->release(dst,reply)){state.faults++;event(io,"FAULT ","failed-partial-allocation-cleanup");}
        if(!*rc)*rc=-1021;
        pthread_mutex_unlock(&mutex);return 1;
    }
    if(io->size(reply)!=24){
        if(io->release(dst,reply)){state.faults++;event(io,"FAULT ","failed-wrong-size-cleanup");}
        pthread_mutex_unlock(&mutex);*rc=-1021;return 1;
    }
    /* Virtual mode2 owns an inline command consumer; original CP task is absent.
     * No sample source exists, so subscription never fabricates angle/error data. */
    state.mode=2;state.worker_started=1;
    unsigned char downstream[20];memcpy(downstream,request,sizeof downstream);
    if(consume(downstream,sizeof downstream)){
        if(io->release(dst,reply))state.faults++;
        pthread_mutex_unlock(&mutex);*rc=-1021;return 1;
    }
    snprintf(text,sizeof text,"tid=%ld destination=0x90a3035b command=3 bytes=20 consumed=%llu notification_enabled=%u countdown=%u mode=%u worker_started=%u worker_execution=inline-virtual sample_valid=0 latched_error=0 original_cp_task_running=0 angle_events=0",
             syscall(SYS_gettid),state.consumed,state.notification_enabled,state.notification_countdown,state.mode,state.worker_started);
    event(io,"CONTROL_CONSUMED ",text);
    memcpy(reply,request,24);memset((unsigned char *)reply+16,0,4);io->set_source(reply,NATIVE_DIG_LEVEL_SID);
    unsigned long long serial=++state.next_lease;long tid=syscall(SYS_gettid);
    *slot=(struct lease){reply,dst,tid,serial};state.live_replies++;
    *rc=io->send(dst,reply);
    if(*rc){
        memset(slot,0,sizeof *slot);state.live_replies--;
        if(io->release(dst,reply)){state.faults++;event(io,"FAULT ","failed-send-cleanup");}
        event(io,"TRANSPORT_FAILURE ","reply-send-failed-request-caller-owned-subscription-retained");
        pthread_mutex_unlock(&mutex);return 1;
    }
    state.queued++;
    snprintf(text,sizeof text,"tid=%ld source=%#x destination=%#x reply=%p lease=%llu bytes=24 result=0 raw=030000000000000000000000000000000000000000000000",tid,NATIVE_DIG_LEVEL_SID,dst,reply,serial);
    event(io,"REPLY_QUEUED ",text);
    int freed=io->release(NATIVE_DIG_LEVEL_SID,request);
    if(freed)state.faults++;else state.request_freed++;
    snprintf(text,sizeof text,"tid=%ld reply=%p lease=%llu request_free_rc=%d notification_enabled=%u countdown=%u sample_valid=0 angle_events=0 camera_startup_verified=0",tid,reply,serial,freed,state.notification_enabled,state.notification_countdown);
    event(io,freed?"FAULT ":"COMMIT ",text);pthread_mutex_unlock(&mutex);*rc=0;return 1;
}
int native_dig_level_release(unsigned int destination,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){
    if(!p || !release || !rc)return 0;
    pthread_mutex_lock(&mutex);int found=0;
    for(unsigned int i=0;i<8;i++)if(leases[i].pointer==p){
        struct lease lease=leases[i];found=1;
        *rc=destination==lease.destination?release(destination,p):-1021;
        if(*rc)state.faults++;
        else{memset(&leases[i],0,sizeof leases[i]);state.live_replies--;if(syscall(SYS_gettid)==lease.sender)state.waiter_freed++;}
        if(record){char text[300];snprintf(text,sizeof text,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu bytes=24 rc=%d",syscall(SYS_gettid),lease.sender,syscall(SYS_gettid)==lease.sender,destination,lease.destination,p,lease.serial,*rc);record(*rc?"FULL_DIG_LEVEL_FAULT ":"FULL_DIG_LEVEL_NATIVE_REPLY_FREE ",text);}
        break;
    }
    pthread_mutex_unlock(&mutex);return found;
}
void native_dig_level_snapshot(struct native_dig_level_snapshot *out){pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);}
