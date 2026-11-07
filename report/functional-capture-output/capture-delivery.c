/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "capture-delivery.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
struct capture_delivery {
    pthread_mutex_t mutex;
    struct capture_delivery_info info;
    struct capture_notifications packets;
    struct full_imaging_io io;
    struct native_cp_state_publication_guard guard;
    long creator_tid;
    unsigned callbacks,checking[3],initialized[3];
    int building,closing;
};
static long tid(void){return syscall(SYS_gettid);}
static int owner(const struct capture_delivery *d){return !d?-EINVAL:d->info.owner_pid!=getpid()?-ECHILD:0;}
static uint64_t fnv(const void *p,size_t n){const unsigned char *b=p;uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<n;++i)h=(h^b[i])*UINT64_C(1099511628211);return h;}
static void fault(struct capture_delivery *d,int rc){if(rc && !d->info.first_error)d->info.first_error=rc;}
static const uint8_t *wire(const struct capture_delivery *d,unsigned i){return i==0?d->packets.start:i==1?d->packets.entry:d->packets.info;}
static int exact(struct capture_delivery *d,unsigned i,void *p){
    struct native_cp_state_publication_lease *l=&d->info.leases[i];
    return d->io.size(p)==l->bytes && d->io.source(p)==l->source && !memcmp(p,wire(d,i),l->bytes);
}
static void consumed(struct capture_delivery *d,unsigned i){
    struct native_cp_state_publication_lease *l=&d->info.leases[i];
    if(l->queued && l->received && l->freed && !l->consumed){l->consumed=1;++d->info.wire_consumed;}
}
static int stop_build(struct capture_delivery *d,int rc){
    pthread_mutex_lock(&d->mutex);fault(d,rc);d->building=0;pthread_mutex_unlock(&d->mutex);return rc;
}
int capture_delivery_begin(struct capture_output_memory *output,const uint8_t request[16],
    const uint8_t time[12],const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard,struct capture_delivery **out){
    if(!output || !request || !time || !io || !guard || !out || *out || !io->allocate ||
       !io->release || !io->set_source || !io->send || !io->size || !io->source ||
       !guard->reserve || !guard->release || !guard->predecessor_ready)return -EINVAL;
    int rc=guard->reserve();if(rc)return rc;
    if(guard->predecessor_ready()!=1){guard->release();return -ENODATA;}
    struct capture_delivery *d=calloc(1,sizeof *d);if(!d){guard->release();return -ENOMEM;}
    int e=pthread_mutex_init(&d->mutex,NULL);if(e){free(d);guard->release();return -e;}
    d->io=*io;d->guard=*guard;d->creator_tid=tid();d->info.owner_pid=getpid();d->info.guard_held=1;
    rc=capture_notifications_build(output,request,time,&d->packets);
    if(rc){pthread_mutex_destroy(&d->mutex);free(d);guard->release();return rc;}
    d->info.frame_token=d->packets.frame_token;d->info.request_fnv1a64=d->packets.request_fnv1a64;d->info.job_scalar=d->packets.job_scalar;
    static const unsigned bytes[]={CAPTURE_NOTIFY_START_BYTES,CAPTURE_NOTIFY_ENTRY_BYTES,CAPTURE_NOTIFY_INFO_BYTES};
    for(unsigned i=0;i<3;++i)d->info.leases[i]=(struct native_cp_state_publication_lease){.role=i+1,.bytes=bytes[i],.destination=NATIVE_CP_STATE_PUBLICATION_AP,.source=NATIVE_CP_STATE_PUBLICATION_SID,.sender_tid=d->creator_tid,.wire_fnv1a64=fnv(wire(d,i),bytes[i])};
    d->building=1;*out=d;
    for(unsigned i=0;i<3;++i){
        void *p=NULL;rc=io->allocate(NATIVE_CP_STATE_PUBLICATION_AP,&p,bytes[i],1);
        pthread_mutex_lock(&d->mutex);struct native_cp_state_publication_lease *l=&d->info.leases[i];l->allocate_rc=rc;l->pointer=p;if(p)++d->info.retained;pthread_mutex_unlock(&d->mutex);
        if(rc || !p)return stop_build(d,rc?rc:-ENOMEM);
        if(io->size(p)!=bytes[i])return stop_build(d,-EMSGSIZE);
        memcpy(p,wire(d,i),bytes[i]);io->set_source(p,NATIVE_CP_STATE_PUBLICATION_SID);
        if(!exact(d,i,p))return stop_build(d,-EBADMSG);
        pthread_mutex_lock(&d->mutex);d->initialized[i]=1;l->send_inflight=1;d->info.sending=1;pthread_mutex_unlock(&d->mutex);
        rc=io->send(NATIVE_CP_STATE_PUBLICATION_AP,p);
        pthread_mutex_lock(&d->mutex);l->send_inflight=0;l->send_rc=rc;d->info.sending=0;
        if(!rc){l->queued=1;++d->info.queued;consumed(d,i);}else fault(d,rc);
        int observed_error=d->info.first_error;
        pthread_mutex_unlock(&d->mutex);
        if(rc || observed_error)return stop_build(d,rc?rc:observed_error);
    }
    return stop_build(d,0);
}
int capture_delivery_observe(struct capture_delivery *d,unsigned destination,void *message){
    int rc=owner(d);if(rc)return rc;if(destination!=NATIVE_CP_STATE_PUBLICATION_AP || !message)return 0;
    pthread_mutex_lock(&d->mutex);unsigned i=0;for(;i<3 && d->info.leases[i].pointer!=message;++i){}
    if(i==3){pthread_mutex_unlock(&d->mutex);return 0;}
    struct native_cp_state_publication_lease *l=&d->info.leases[i];
    if(d->closing || d->checking[i] || l->releasing){pthread_mutex_unlock(&d->mutex);return -EBUSY;}
    if(l->received || l->freed || (!l->queued && !l->send_inflight)){pthread_mutex_unlock(&d->mutex);return -EALREADY;}
    d->checking[i]=1;++d->callbacks;pthread_mutex_unlock(&d->mutex);
    int matched=exact(d,i,message);long receiver=tid();
    pthread_mutex_lock(&d->mutex);--d->callbacks;d->checking[i]=0;
    if(!matched){++l->faults;fault(d,-EBADMSG);rc=-EBADMSG;}
    else{l->received=1;l->receiver_tid=receiver;++d->info.received;rc=1;}
    pthread_mutex_unlock(&d->mutex);return rc;
}
int capture_delivery_free(struct capture_delivery *d,unsigned destination,void *message,int *result){
    int rc=owner(d);if(rc){if(result)*result=rc;return d?1:0;}
    if(!result || destination!=NATIVE_CP_STATE_PUBLICATION_AP || !message)return 0;
    pthread_mutex_lock(&d->mutex);unsigned i=0;for(;i<3 && d->info.leases[i].pointer!=message;++i){}
    if(i==3){pthread_mutex_unlock(&d->mutex);return 0;}
    struct native_cp_state_publication_lease *l=&d->info.leases[i];
    if(d->closing || d->checking[i] || l->releasing){*result=-EBUSY;pthread_mutex_unlock(&d->mutex);return 1;}
    if(!l->received || l->freed || l->receiver_tid!=tid()){*result=-EPROTO;pthread_mutex_unlock(&d->mutex);return 1;}
    l->releasing=1;++d->callbacks;pthread_mutex_unlock(&d->mutex);
    rc=exact(d,i,message)?d->io.release(destination,message):-EBADMSG;
    pthread_mutex_lock(&d->mutex);--d->callbacks;l->releasing=0;l->free_rc=rc;
    if(!rc){l->freed=1;l->pointer=NULL;l->free_tid=tid();--d->info.retained;consumed(d,i);}
    else{++l->faults;fault(d,rc);}
    pthread_mutex_unlock(&d->mutex);*result=rc;return 1;
}
int capture_delivery_cleanup(struct capture_delivery *d){
    int rc=owner(d);if(rc)return rc;if(tid()!=d->creator_tid)return -EPERM;
    for(unsigned i=0;i<3;++i){
        pthread_mutex_lock(&d->mutex);struct native_cp_state_publication_lease *l=&d->info.leases[i];
        if(d->building || d->closing || d->callbacks){pthread_mutex_unlock(&d->mutex);return -EBUSY;}
        if(!l->pointer || l->queued || l->received){pthread_mutex_unlock(&d->mutex);continue;}
        void *p=l->pointer;l->releasing=1;++d->callbacks;pthread_mutex_unlock(&d->mutex);
        int matches=d->initialized[i]?exact(d,i,p):d->io.size(p)==l->bytes;
        rc=matches?d->io.release(l->destination,p):-EBADMSG;
        pthread_mutex_lock(&d->mutex);l->releasing=0;--d->callbacks;l->free_rc=rc;
        if(!rc){l->pointer=NULL;l->freed=1;l->free_tid=tid();--d->info.retained;}else fault(d,rc);
        pthread_mutex_unlock(&d->mutex);if(rc)return rc;
    }
    return 0;
}
int capture_delivery_info(struct capture_delivery *d,struct capture_delivery_info *out){
    int rc=owner(d);if(rc)return rc;if(!out)return -EINVAL;
    pthread_mutex_lock(&d->mutex);*out=d->info;pthread_mutex_unlock(&d->mutex);return 0;
}
int capture_delivery_close(struct capture_delivery *d){
    int rc=owner(d);if(rc)return rc;if(tid()!=d->creator_tid)return -EPERM;
    pthread_mutex_lock(&d->mutex);
    if(d->building || d->closing || d->callbacks || d->info.retained || d->info.queued!=d->info.wire_consumed){pthread_mutex_unlock(&d->mutex);return -EBUSY;}
    d->closing=1;pthread_mutex_unlock(&d->mutex);
    rc=capture_notifications_release(&d->packets);
    if(rc){pthread_mutex_lock(&d->mutex);d->closing=0;pthread_mutex_unlock(&d->mutex);return rc;}
    if(d->info.guard_held)d->guard.release();
    pthread_mutex_destroy(&d->mutex);free(d);return 0;
}
