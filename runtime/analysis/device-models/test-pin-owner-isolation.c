/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pinmem-device.h"
#ifdef TEST_SCALAR
#include "scalar-device.h"
#undef FULL_PINMEM_CP
#define FULL_PINMEM_CP FULL_SCALAR_CP
#define full_pinmem_dispatch full_scalar_dispatch
#define full_pinmem_snapshot full_scalar_snapshot
#define full_pinmem_test_reset full_scalar_test_reset
#define full_pinmem_release_reply full_scalar_release_reply
#define PEER_OBJECTS 10
#else
#define PEER_OBJECTS 13
#endif
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
struct block {unsigned int owner,source,bytes;unsigned char data[56];};
static struct block reused;
static void *queued;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static int available,waiting,freed,claimed;
static unsigned int frees;
struct ops {
    unsigned int owner;
    int (*dispatch)(unsigned int,void *,const struct full_imaging_io *,int,int *);
    void (*snapshot)(struct full_vef_snapshot *);
    void (*reset)(void);
};
static const struct ops devices[2]={{FULL_VEF_CP,full_vef_dispatch,full_vef_snapshot,full_vef_test_reset},
                                  {FULL_PINMEM_CP,full_pinmem_dispatch,full_pinmem_snapshot,full_pinmem_test_reset}};
static unsigned int new_device;
static struct block *header(void *p){return (struct block *)((char *)p - offsetof(struct block,data));}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static unsigned int u32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static int allocate(unsigned int dst,void **out,unsigned int n,unsigned int wait){
    assert(n==56 && wait==1);pthread_mutex_lock(&lock);
    while(!available){waiting=1;pthread_cond_broadcast(&condition);assert(!pthread_cond_wait(&condition,&lock));}
    available=0;reused=(struct block){.owner=dst,.bytes=n};*out=reused.data;
    if(freed){claimed=1;pthread_cond_broadcast(&condition);}
    pthread_mutex_unlock(&lock);return 0;
}
static int release(unsigned int owner,void *p){
    assert(header(p)->owner==owner);
    if(header(p)!=&reused){free(header(p));return 0;}
    pthread_mutex_lock(&lock);available=1;
    if(!frees++){
        freed=1;pthread_cond_broadcast(&condition);
        while(!claimed)assert(!pthread_cond_wait(&condition,&lock));
    }
    pthread_mutex_unlock(&lock);return 0;
}
static void set_source(void *p,unsigned int source){header(p)->source=source;}
static unsigned int source(void *p){return header(p)->source;}
static unsigned int size(void *p){return header(p)->bytes;}
static int send(unsigned int dst,void *p){assert(header(p)->owner==dst && !queued);queued=p;return 0;}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(unsigned int device,unsigned int sid){
    struct block *m=calloc(1,sizeof *m);assert(m);m->owner=devices[device].owner;m->source=sid;m->bytes=48;
    unsigned char *p=m->data;put32(p,sid);put32(p+4,0xa0a0a0a0);p[8]=1;p[10]=48;put32(p+12,24);put32(p+16,48);
    p[25]=0x10;p[28]=24;p[30]=2;put32(p+36,device?1:2);put32(p+40,device?1:3);return p;
}
static void classified_free(unsigned int sid,void *p){
    int rc=123;int handled=full_pinmem_release_reply(sid,p,release,0,&rc);
    if(!handled)handled=full_vef_release_reply(sid,p,release,0,&rc);
    assert(handled && !rc);
}
static void *caller(void *p){
    int rc=123;assert(devices[new_device].dispatch(devices[new_device].owner,p,&io,1,&rc) && !rc);
    assert(queued==reused.data && source(queued)==devices[new_device].owner && u32((unsigned char *)queued+48)==devices[new_device].owner);
    classified_free(0x81e10002,queued);queued=0;return 0;
}
int main(void){
    alarm(15);
    for(unsigned int iteration=0;iteration<50;iteration++){
        for(unsigned int i=0;i<2;i++)devices[i].reset();
        queued=0;available=1;waiting=freed=claimed=0;frees=0;
        unsigned int old=iteration%2;new_device=1-old;int rc=123;
        void *first=request(old,0x81e10001);
        assert(devices[old].dispatch(devices[old].owner,first,&io,1,&rc) && !rc);void *old_reply=queued;queued=0;
        struct full_vef_snapshot other;devices[new_device].snapshot(&other);assert(!other.initialized && !other.queries);
        void *next=request(new_device,0x81e10002);pthread_t a;assert(!pthread_create(&a,0,caller,next));
        pthread_mutex_lock(&lock);while(!waiting)assert(!pthread_cond_wait(&condition,&lock));pthread_mutex_unlock(&lock);
        classified_free(0x81e10001,old_reply);assert(!pthread_join(a,0));
        for(unsigned int i=0;i<2;i++){
            struct full_vef_snapshot s;devices[i].snapshot(&s);
            assert(s.owner_sid==devices[i].owner && s.registry_objects==(i?PEER_OBJECTS:16));
            assert(!s.faults && !s.live_replies && s.queries==1 && s.native_freed==1);
        }
    }
#ifdef TEST_SCALAR
    puts("VEF_SCALAR_INDEPENDENT_OBJECTS_SOURCE_CROSS_OWNER_ABA_50_PASS");
#else
    puts("VEF_PINMEM_INDEPENDENT_OBJECTS_SOURCE_CROSS_OWNER_ABA_50_PASS");
#endif
    return 0;
}
