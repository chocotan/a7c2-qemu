/* SPDX-License-Identifier: MIT */
#include "cp-periodic-service.h"
#include <pthread.h>
#include <stdio.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct native_cp_periodic_state state;
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
int native_cp_periodic_dispatch(unsigned int destination,void *request,
                               const struct full_imaging_io *io,int enabled,int *rc){
    if(enabled!=1 || !io || !rc ||
       (destination!=NATIVE_CP_PERIODIC_START && destination!=NATIVE_CP_PERIODIC_STOP))return 0;
    if(!request || !io->size || !io->release){*rc=-1021;return 1;}
    unsigned int bytes=io->size(request);
    if(bytes!=(destination==NATIVE_CP_PERIODIC_START?4u:0u)){
        if(io->record)io->record("FULL_CP_PERIODIC_REJECT ","reason=packet-size request_caller_owned=1");
        *rc=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    struct native_cp_periodic_state next=state;
    if(destination==NATIVE_CP_PERIODIC_START){
        const unsigned char *in=request;
        unsigned int first=u16(in),second=u16(in+2),period=first&0x7fffu;
        /* CP aca9da: default period100; ARM UDIV by zero yields zero. */
        next.period=period?period:100u;
        if(!second){next.count=5;next.phase=0;}
        else if(first&0x8000u){next.count=in[2];next.phase=in[3];}
        else{next.count=period?second/period:0;next.phase=255;}
        next.requested_active=1;next.starts++;
    }else{next.requested_active=0;next.stops++;}
    /* Parse before transfer; failed release preserves caller ownership and state. */
    int result=io->release(destination,request);
    if(!result){next.released++;state=next;}
    if(io->record){
        char text[480];
        snprintf(text,sizeof text,
                 "destination=%#x bytes=%u release_rc=%d period=%u count=%u phase=%u requested_active=%u starts=%llu stops=%llu released=%llu config_applied=%u timer_started=0 original_cp_executed=0 samples=0 replies=0 camera_startup_verified=0",
                 destination,bytes,result,state.period,state.count,state.phase,state.requested_active,
                 state.starts,state.stops,state.released,result==0);
        io->record(result?"FULL_CP_PERIODIC_RELEASE_FAILURE ":"FULL_CP_PERIODIC_CONFIG_COMMIT ",text);
    }
    pthread_mutex_unlock(&mutex);*rc=result;return 1;
}
void native_cp_periodic_snapshot(struct native_cp_periodic_state *out){
    if(!out)return;
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
