/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "vef-device.h"
#if defined(TEST_HDMIPIN)
#include "hdmi-pin-device.h"
#undef FULL_VEF_CP
#define FULL_VEF_CP FULL_HDMI_PIN_CP
#define full_vef_dispatch(...) full_hdmi_pin_dispatch(__VA_ARGS__)
#define full_vef_release_reply(...) full_hdmi_pin_release_reply(__VA_ARGS__)
#define full_vef_snapshot(out) full_hdmi_pin_snapshot(out)
#define full_vef_test_reset() full_hdmi_pin_test_reset()
#define full_vef_test_set_state(i,value) full_hdmi_pin_test_set_state(i,value)
#define OBJECT_COUNT 2
#define CHANGED_SLOT 0
#define COMMIT_TAG "FULL_HDMIPIN_COMMIT "
#elif defined(TEST_ADF)
#include "adf-device.h"
#undef FULL_VEF_CP
#define FULL_VEF_CP FULL_ADF_CP
#define full_vef_dispatch(...) full_adf_dispatch(__VA_ARGS__)
#define full_vef_release_reply(...) full_adf_release_reply(__VA_ARGS__)
#define full_vef_snapshot(out) full_adf_snapshot(out)
#define full_vef_test_reset() full_adf_test_reset()
#define full_vef_test_set_state(i,value) full_adf_test_set_state(i,value)
#define OBJECT_COUNT 10
#define CHANGED_SLOT 0
#define COMMIT_TAG "FULL_ADF_COMMIT "
#elif defined(TEST_SCALAR)
#include "scalar-device.h"
#undef FULL_VEF_CP
#define FULL_VEF_CP FULL_SCALAR_CP
#define full_vef_dispatch(...) full_scalar_dispatch(__VA_ARGS__)
#define full_vef_release_reply(...) full_scalar_release_reply(__VA_ARGS__)
#define full_vef_snapshot(out) full_scalar_snapshot(out)
#define full_vef_test_reset() full_scalar_test_reset()
#define full_vef_test_set_state(i,value) full_scalar_test_set_state(i,value)
#define OBJECT_COUNT 10
#define CHANGED_SLOT 8
#define COMMIT_TAG "FULL_SCALAR_COMMIT "
#elif defined(TEST_PINMEM)
#include "pinmem-device.h"
#undef FULL_VEF_CP
#define FULL_VEF_CP FULL_PINMEM_CP
#define full_vef_dispatch(...) full_pinmem_dispatch(__VA_ARGS__)
#define full_vef_release_reply(...) full_pinmem_release_reply(__VA_ARGS__)
#define full_vef_snapshot(out) full_pinmem_snapshot(out)
#define full_vef_test_reset() full_pinmem_test_reset()
#define full_vef_test_set_state(i,value) full_pinmem_test_set_state(i,value)
#define OBJECT_COUNT 13
#define CHANGED_SLOT 6
#define COMMIT_TAG "FULL_PINMEM_COMMIT "
#else
#define OBJECT_COUNT 16
#define CHANGED_SLOT 10
#define COMMIT_TAG "FULL_VEF_COMMIT "
#endif
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>
struct message {unsigned int owner,source,bytes,live;unsigned char data[64];};
static struct message pool[16];static void *queued;
static int alloc_error,send_error,reply_error,request_error;
static void *alias;
static struct {pthread_mutex_t lock;pthread_cond_t condition;int active,waiting,freed,reused;void *old;unsigned int dst;} race={.lock=PTHREAD_MUTEX_INITIALIZER,.condition=PTHREAD_COND_INITIALIZER};
static unsigned int expected_keys[3],expected_state=1;
static unsigned int get32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static struct message *header(void *p){for(unsigned int i=0;i<16;i++)if(pool[i].data==p)return &pool[i];assert(0);return 0;}
static int allocate(unsigned int dst,void **out,unsigned int n,unsigned int wait){
    assert(n==56 && wait==1);
    if(alias){*out=alias;return 0;}
    if(alloc_error){*out=0;return alloc_error;}
    if(race.active && dst==race.dst){
        pthread_mutex_lock(&race.lock);race.waiting=1;pthread_cond_broadcast(&race.condition);
        while(!race.freed)assert(!pthread_cond_wait(&race.condition,&race.lock));
        struct message *m=header(race.old);assert(!m->live);*m=(struct message){.owner=dst,.bytes=n,.live=1};*out=m->data;
        race.reused=1;pthread_cond_broadcast(&race.condition);pthread_mutex_unlock(&race.lock);return 0;
    }
    for(unsigned int i=0;i<16;i++)if(!pool[i].live){pool[i]=(struct message){.owner=dst,.bytes=n,.live=1};*out=pool[i].data;return 0;}
    assert(0);return -1;
}
static int release(unsigned int owner,void *p){
    struct message *m=header(p);assert(m->live && m->owner==owner);
    int rc=owner==FULL_VEF_CP?request_error:reply_error;if(rc)return rc;
    if(race.active && p==race.old && owner!=race.dst){
        pthread_mutex_lock(&race.lock);m->live=0;race.freed=1;pthread_cond_broadcast(&race.condition);
        while(!race.reused)assert(!pthread_cond_wait(&race.condition,&race.lock));
        pthread_mutex_unlock(&race.lock);return 0;
    }
    m->live=0;memset(m->data,0xdd,sizeof m->data);return 0;
}
static void set_source(void *p,unsigned int source){header(p)->source=source;}
static unsigned int source(void *p){return header(p)->source;}
static unsigned int size(void *p){return header(p)->bytes;}
static int send(unsigned int dst,void *p){
    struct message *m=header(p);assert(m->live && m->owner==dst && m->source==FULL_VEF_CP && m->bytes==56);
    if(send_error)return send_error;
    assert(!queued);queued=p;return 0;
}
static void record(const char *tag,const char *line){
    if(!strcmp(tag,COMMIT_TAG)){
        char match[100];snprintf(match,sizeof match,"type=%u dir=%u index=%u pin_state=%u",expected_keys[0],expected_keys[1],expected_keys[2],expected_state);
        assert(strstr(line,match) && strstr(line,"connect_performed=0 pixels_consumed=0"));
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static struct full_vef_snapshot snapshot(void){struct full_vef_snapshot s;full_vef_snapshot(&s);return s;}
static void reset(void){full_vef_test_reset();memset(pool,0,sizeof pool);queued=alias=0;alloc_error=send_error=reply_error=request_error=0;expected_state=1;}
static void *request(unsigned int type,unsigned int dir,unsigned int index,unsigned int src,unsigned int dst){
    struct message *m=0;for(unsigned int i=0;i<16;i++)if(!pool[i].live){m=&pool[i];break;}assert(m);
    *m=(struct message){.owner=FULL_VEF_CP,.source=src,.bytes=48,.live=1};unsigned char *p=m->data;
    put32(p,dst);put32(p+4,0xa0a0a0a0);p[8]=1;p[10]=48;put32(p+12,24);put32(p+16,48);put32(p+20,0x1234abcd);
    p[25]=0x10;p[28]=24;p[30]=2;put32(p+32,type);put32(p+36,dir);put32(p+40,index);put32(p+44,0xfedcba98);
    expected_keys[0]=type;expected_keys[1]=dir;expected_keys[2]=index;return p;
}
static void finish(unsigned int dst){
    assert(queued);const unsigned char *p=queued;assert(get32(p)==0 && get32(p+4)==0xa0a0a0a0);
    assert(p[8]==1 && p[10]==56 && get32(p+12)==24 && get32(p+16)==56);
    assert(get32(p+24)==0x80001000 && get32(p+28)==0x00020020);
    for(unsigned int i=0;i<3;i++)assert(get32(p+32+4*i)==expected_keys[i]);
    assert(get32(p+44)==expected_state && get32(p+48)==FULL_VEF_CP && !get32(p+52));
    int rc=123;assert(full_vef_release_reply(dst,queued,release,record,&rc) && !rc);queued=0;
}
static void accepted(unsigned int type,unsigned int dir,unsigned int index,unsigned int sid){
    void *p=request(type,dir,index,sid,sid);int rc=123;
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc);finish(sid);
}
static void registry_tests(void){
    reset();
    for(unsigned int i=0;i<OBJECT_COUNT;i++){
#if defined(TEST_SCALAR)
        unsigned int type=0,dir=i/5+1,index=i%5;
#elif defined(TEST_PINMEM)
        static const unsigned int attributes[13][3]={{0,1,0},{0,1,1},{0,1,2},{0,2,0},{0,2,1},{0,2,2},{0,2,3},{4,2,0},{1,3,0},{4,1,0},{6,2,0},{6,1,0},{8,1,0}};
        unsigned int type=attributes[i][0],dir=attributes[i][1],index=attributes[i][2];
#else
        unsigned int type=i<14?0:8,dir=i<14?i/7+1:i-13,index=i<14?i%7:0;
#endif
        accepted(type,dir,index,0x81b10001+i);struct full_vef_snapshot s=snapshot();
        assert(s.initialized && s.pins[i].self[0]==type && s.pins[i].self[1]==dir && s.pins[i].self[2]==index);
        assert(s.pins[i].self[3]==FULL_VEF_CP && s.pins[i].state==1 && s.pins[i].peer[0]==255 && s.pins[i].peer[1]==255);
    }
    assert(snapshot().registry_objects==OBJECT_COUNT && snapshot().owner_sid==FULL_VEF_CP);
    accepted(0x12340000,0x34560002,0x56780003,0x81b10201);assert(snapshot().queries==OBJECT_COUNT+1);
    full_vef_test_set_state(CHANGED_SLOT,2);expected_state=2;accepted(0,2,3,0x81b10202);
    assert(snapshot().pins[CHANGED_SLOT].state==2 && snapshot().waiter_freed==OBJECT_COUNT+2);
#if defined(TEST_SCALAR)
    expected_state=1;accepted(0,1,4,0x81b10203);assert(snapshot().pins[4].state==1);
    puts("SCALAR_REGISTRY_10_INDEPENDENT_OBJECTS_NATIVE_TARGET_014_PASS");
#elif defined(TEST_PINMEM)
    expected_state=1;accepted(0,1,1,0x81b10203);assert(snapshot().pins[1].state==1);
    puts("PINMEM_REGISTRY_13_OBJECTS_ACTUAL_PEER_KEYS_OWNER_PASS");
#else
    puts("VEF_REGISTRY_16_OBJECTS_LOW_BYTE_LOOKUP_FULL_ECHO_STATE_PASS");
#endif
}
static void fault_tests(void){
    reset();int rc=123;void *p=request(0,2,3,0x81b10101,0x81b10102);
    assert(!full_vef_dispatch(FULL_VEF_CP,p,&io,0,&rc) && rc==123 && !snapshot().initialized);
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc);finish(0x81b10102);
    const unsigned int missing[][3]={{9,2,3},{0,0,0},{0,2,7}};
    for(unsigned int i=0;i<3;i++){
        p=request(missing[i][0],missing[i][1],missing[i][2],0x81b10101,0x81b10101);
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021 && header(p)->live && !queued);assert(!release(FULL_VEF_CP,p));
    }
    p=request(0,2,3,0x81b10101,0x81b10101);((unsigned char *)p)[26]=1;
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021);assert(!release(FULL_VEF_CP,p));
    for(unsigned int failure=0;failure<2;failure++){
        reset();p=request(0,2,3,0x81b10101,0x81b10101);if(!failure)alloc_error=-55;else send_error=-66;
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==(failure?-66:-55) && header(p)->live);
        assert(!snapshot().queries && !snapshot().pending && !snapshot().live_replies && !queued);
        alloc_error=send_error=0;assert(!release(FULL_VEF_CP,p));
    }
    reset();p=request(0,2,3,0x81b10101,0x81b10101);request_error=-77;
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc && snapshot().faults && header(p)->live);
    request_error=0;assert(!release(FULL_VEF_CP,p));reply_error=-78;
    assert(full_vef_release_reply(0x81b10101,queued,release,record,&rc) && rc==-78 && snapshot().live_replies==1);
    reply_error=0;finish(0x81b10101);assert(!snapshot().live_replies);
    p=request(0,2,3,0x81b10101,0x81b10101);assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021);assert(!release(FULL_VEF_CP,p));
    reset();p=request(0,2,3,0x81b10101,0x81b10101);send_error=-66;reply_error=-79;
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-66);
    struct full_vef_snapshot s=snapshot();assert(s.faults && s.retained_reply && !s.live_replies && !s.queries && header(p)->live);
    send_error=reply_error=0;assert(!release(0x81b10101,s.retained_reply));assert(!release(FULL_VEF_CP,p));
    reset();p=request(0,2,3,0x81b10101,0x81b10101);alias=p;
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021 && snapshot().faults && header(p)->live);
    alias=0;assert(!release(FULL_VEF_CP,p));
    reset();p=request(0,2,3,0x81b10101,0x81b10101);
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc);
    assert(full_vef_release_reply(0x81b10102,queued,release,record,&rc) && rc==-1021 && snapshot().live_replies==1);
    finish(0x81b10101);assert(!snapshot().live_replies);
}
static void envelope_and_exhaustion_tests(void){
    reset();int rc=123;
    const unsigned int ids[][2]={{0x81b10501,0},{0x905a0048,0x81b10501},{0x81b10501,0x905a0048}};
    for(unsigned int i=0;i<3;i++){
        void *p=request(0,2,3,ids[i][0],ids[i][1]);
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021 && header(p)->live && !queued);
        assert(!release(FULL_VEF_CP,p));
    }
    const unsigned int offsets[]={4,8,10,12,16,24,26,28,30};
    for(unsigned int i=0;i<sizeof offsets/sizeof *offsets;i++){
        unsigned char *p=request(0,2,3,0x81b10501,0x81b10501);p[offsets[i]]^=1;
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021 && header(p)->live && !queued);
        assert(!release(FULL_VEF_CP,p));
    }
    void *p=request(0,2,3,0x81b10501,0x81b10501);header(p)->bytes=47;
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021 && header(p)->live);assert(!release(FULL_VEF_CP,p));
    reset();void *held[8];
    for(unsigned int i=0;i<8;i++){
        p=request(0,2,3,0x81b10600+i,0x81b10600+i);
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc);held[i]=queued;queued=0;
    }
    p=request(0,2,3,0x81b10700,0x81b10700);
    assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && rc==-1021 && header(p)->live);
    assert(snapshot().live_replies==8 && snapshot().queries==8 && !snapshot().pending);
    assert(!release(FULL_VEF_CP,p));
    for(unsigned int i=0;i<8;i++)assert(full_vef_release_reply(0x81b10600+i,held[i],release,record,&rc) && !rc);
    assert(!snapshot().live_replies && !snapshot().faults);
}
struct heap_message {unsigned int owner,source,bytes;unsigned char data[];};
static struct heap_message *heap_header(void *p){return (struct heap_message *)((char *)p - offsetof(struct heap_message,data));}
static int heap_allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait){
    assert(bytes==56 && wait==1);struct heap_message *m=calloc(1,sizeof *m+bytes);assert(m);
    m->owner=owner;m->bytes=bytes;*out=m->data;return 0;
}
static int heap_release(unsigned int owner,void *p){assert(heap_header(p)->owner==owner);free(heap_header(p));return 0;}
static unsigned int heap_size(void *p){return heap_header(p)->bytes;}
static unsigned int heap_source(void *p){return heap_header(p)->source;}
static void heap_set_source(void *p,unsigned int source){heap_header(p)->source=source;}
static int heap_send(unsigned int owner,void *p){assert(heap_header(p)->owner==owner && heap_source(p)==FULL_VEF_CP && heap_size(p)==56 && !queued);queued=p;return 0;}
static void actual_heap_test(void){
    reset();const struct full_imaging_io heap_io={heap_allocate,heap_release,heap_set_source,heap_send,heap_size,heap_source,record};
    unsigned char *original=request(0,2,3,0x81b10801,0x81b10801);
    struct heap_message *m=calloc(1,sizeof *m+48);assert(m);m->owner=FULL_VEF_CP;m->source=0x81b10801;m->bytes=48;
    memcpy(m->data,original,48);assert(!release(FULL_VEF_CP,original));int rc=123;
    assert(full_vef_dispatch(FULL_VEF_CP,m->data,&heap_io,1,&rc) && !rc);
    assert(queued && get32((unsigned char *)queued+48)==FULL_VEF_CP && heap_size(queued)==56);
    assert(full_vef_release_reply(0x81b10801,queued,heap_release,record,&rc) && !rc);queued=0;
    assert(!snapshot().faults && !snapshot().live_replies);
    puts("VEF_ACTUAL_48B_REQUEST_56B_REPLY_HEAP_FREE_PASS");
}
static void *new_caller(void *p){int rc=123;assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc && queued==race.old);finish(race.dst);return 0;}
static void interleaving(void){
    for(unsigned int iteration=0;iteration<50;iteration++){
        reset();void *p=request(0,2,3,0x81b10301,0x81b10301);int rc=123;
        assert(full_vef_dispatch(FULL_VEF_CP,p,&io,1,&rc) && !rc);void *old=queued;queued=0;
        void *next=request(0,2,3,0x81b10302,0x81b10302);
        race.active=1;race.waiting=race.freed=race.reused=0;race.old=old;race.dst=0x81b10302;
        pthread_t a;assert(!pthread_create(&a,0,new_caller,next));pthread_mutex_lock(&race.lock);
        while(!race.waiting) {
            assert(!pthread_cond_wait(&race.condition,&race.lock));
        }
        pthread_mutex_unlock(&race.lock);
        void *third=request(0,2,3,0x81b10303,0x81b10303);
        assert(full_vef_dispatch(FULL_VEF_CP,third,&io,1,&rc) && rc==-1021 && header(third)->live);
        assert(!release(FULL_VEF_CP,third));
        assert(full_vef_release_reply(0x81b10301,old,release,record,&rc) && !rc);assert(!pthread_join(a,0));race.active=0;
        assert(race.reused && !snapshot().faults && !snapshot().live_replies && snapshot().queries==2);
    }
    puts("VEF_56B_REAL_FREE_SAME_ADDRESS_INTERLEAVING_50_PASS");
}
int main(void){alarm(15);registry_tests();fault_tests();envelope_and_exhaustion_tests();actual_heap_test();interleaving();puts("VEF_QUERY_ONLY_WIRE_OWNERSHIP_FAILURE_PASS");return 0;}
