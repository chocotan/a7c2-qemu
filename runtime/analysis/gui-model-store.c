#include "gui-model-store.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>

static void put32(unsigned char *p, unsigned int n) {
    for (unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));
}
static void put64(unsigned char *p, unsigned long long n) {
    for (unsigned int i=0;i<8;i++)p[i]=(unsigned char)(n>>(8*i));
}
static int stopped(const struct gui_model_store_ops *o) {
    return __atomic_load_n(o->stop,__ATOMIC_ACQUIRE)!=0;
}
static int fail(struct gui_model_store *s, const struct gui_model_store_ops *o, const char *reason) {
    s->failed=1;o->log("GUI_MODEL_FAILED ",reason);return -1;
}
int gui_model_store_step(struct gui_model_store *s, const struct gui_model_store_ops *o, const char *path) {
    if(s->failed || stopped(o))return -1;
    void *message=0;
    int rc=o->receive(GUI_MODEL_QUEUE,&message,1000);
    if(rc==-1022 || rc==-1021 || stopped(o)) {
        if(message && o->release(GUI_MODEL_QUEUE,message))return fail(s,o,"release after timeout/shutdown failed");
        return stopped(o)?-1:0;
    }
    if(rc || !message) {
        if(message)o->release(GUI_MODEL_QUEUE,message);
        return fail(s,o,"receive failed; no reply sent");
    }
    struct gui_model_batch batch;
    unsigned int size=o->size(message);
    if(gui_model_decode(message,size,&batch)) {
        const unsigned char *bytes=message;
        for(unsigned int offset=0;offset<size && offset<4096;offset+=128) {
            unsigned int count=size-offset;if(count>128)count=128;
            char raw[257],line[350];
            for(unsigned int i=0;i<count;i++)snprintf(raw+2*i,3,"%02x",bytes[offset+i]);
            snprintf(line,sizeof line,"bytes=%u offset=%u raw=%s",size,offset,raw);
            o->log("GUI_MODEL_REJECT_CHUNK ",line);
        }
        int freed=o->release(GUI_MODEL_QUEUE,message);
        return fail(s,o,freed?"unsupported packet and release failed":"unsupported packet; receiver stopped, no reply");
    }
    struct gui_model_store next=*s;
    next.changed=0;
    next.packets++;
    if(!next.packets) {
        o->release(GUI_MODEL_QUEUE,message);
        return fail(s,o,"local snapshot generation overflow");
    }
    for(unsigned int i=0;i<GUI_MODEL_TYPES;i++)if(batch.present&(1U<<i)) {
        const struct gui_model_value *value=&batch.values[i];
        if(!(s->current.present&(1U<<i)) ||
           memcmp(s->current.values[i].data,value->data,value->bytes))next.changed|=1U<<i;
        next.current.values[i]=*value;
        next.generations[i]=next.packets;
    }
    next.current.present|=batch.present;
    /* This file's generations and exposure fixture are virtual, not CP versions/wire fields. */
    unsigned char raw[GUI_MODEL_STORE_BYTES]={0};
    unsigned int length=GUI_MODEL_STORE_BASE_BYTES+size;
    memcpy(raw,"GMDL0003",8);put64(raw+8,next.packets);
    unsigned long long hash=14695981039346656037ULL;
    for(unsigned int i=0;i<size;i++){hash^=((const unsigned char *)message)[i];hash*=1099511628211ULL;}
    put64(raw+16,hash);put32(raw+24,next.current.present);put32(raw+28,next.changed);
    put32(raw+32,4);put32(raw+36,1);put32(raw+40,1);put32(raw+44,125);put32(raw+48,100);
    put32(raw+52,1);put32(raw+56,GUI_MODEL_TYPES);put32(raw+60,length);
    unsigned int offset=64;
    for(unsigned int i=0;i<GUI_MODEL_TYPES;i++) {
        const struct gui_model_value *value=&next.current.values[i];
        put32(raw+offset,value->type);put32(raw+offset+4,value->bytes);
        put64(raw+offset+8,next.generations[i]);offset+=16;
        memcpy(raw+offset,value->data,value->bytes);offset+=value->bytes;
    }
    memcpy(raw+GUI_MODEL_STORE_PREFIX_BYTES,message,size);
    unsigned long long checksum=14695981039346656037ULL;
    for(unsigned int i=0;i<length-8;i++){checksum^=raw[i];checksum*=1099511628211ULL;}
    put64(raw+length-8,checksum);
    /* A subset can be received first: unused space stays zero and records have length zero. */
    int persisted=o->persist(path,raw,length);
    if(!persisted)*s=next;
    int freed=o->release(GUI_MODEL_QUEUE,message);
    if(persisted || freed)return fail(s,o,persisted?"snapshot commit/readback failed":"original message release failed");
    if(s->packets<=4 || !(s->packets&(s->packets-1))) {
        char text[256];
        snprintf(text,sizeof text,"packets=%llu types=%#x changed=%#x bytes=%u input_fnv=%llx original_free=0 state=%s CP_subscriptions=unimplemented exposure_fixture=F4,1/125,ISO100 records=%u opaque=%u",
                 s->packets,s->current.present,s->changed,size,hash,path,batch.records,batch.opaque);
        o->log("GUI_MODEL_COMMITTED ",text);
    }
    return 0;
}
static pthread_mutex_t service_mutex=PTHREAD_MUTEX_INITIALIZER;
static struct gui_model_store service_state;
static struct gui_model_store_ops service_ops;
static void *pending;
static pid_t owner;
static unsigned int startup_claimed;
static int take_pending(unsigned int queue,void **message,long timeout) {
    (void)timeout;
    if(queue!=GUI_MODEL_QUEUE || !pending)return -1;
    *message=pending;pending=0;return 0;
}
int gui_model_service_start(const struct gui_model_store_ops *ops) {
    if(!ops || !ops->size || !ops->release || !ops->persist || !ops->log || !ops->stop)return -1;
    unsigned int expected=0;
    if(!__atomic_compare_exchange_n(&startup_claimed,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return -1;
    service_ops=*ops;service_ops.receive=take_pending;
    __atomic_store_n(&owner,getpid(),__ATOMIC_RELEASE);
    ops->log("GUI_MODEL_STARTED ","virtual-inline-v1; synchronous complete inline packet store; no CP subscription protocol or composition");
    return 0;
}
int gui_model_service_send(unsigned int queue,void *message,int *rc) {
    pid_t active_owner=__atomic_load_n(&owner,__ATOMIC_ACQUIRE);
    if(queue!=GUI_MODEL_QUEUE || !active_owner)return 0;
    *rc=-1021;
    /* Reject inherited state before touching a mutex potentially held across fork. */
    if(active_owner!=getpid() || !message || pthread_mutex_lock(&service_mutex))return 1;
    if(!service_state.failed && !stopped(&service_ops)) {
        pending=message;
        gui_model_store_step(&service_state,&service_ops,GUI_MODEL_STORE_PATH);
        /* Stop can win before step takes input; then the caller still owns it. */
        if(pending)pending=0;
        else *rc=0;
    }
    pthread_mutex_unlock(&service_mutex);
    return 1;
}
