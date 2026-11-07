/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "infrabb-device.h"
#include "pin-registry-core.h"
#if defined(TEST_GRMPIN)
#include "grm-pin-device.h"
#undef FULL_INFRABB_CP
#define FULL_INFRABB_CP FULL_GRM_PIN_CP
#define full_infrabb_test_reset full_grm_pin_test_reset
#define full_infrabb_dispatch full_grm_pin_dispatch
#define full_infrabb_release_reply full_grm_pin_release_reply
#define full_infrabb_snapshot full_grm_pin_snapshot
#define full_infrabb_registry full_grm_pin_registry
#define TEST_TYPE 1
#define TEST_DIR 3
#define TEST_INDEX 0
#define CHANGED_SLOT 0
#define REPLY_HEADER FULL_GRM_PIN_CP
#define COUNT 1
#elif defined(TEST_DRAWINFO)
#include "drawinfo-device.h"
#undef FULL_INFRABB_CP
#define FULL_INFRABB_CP FULL_DRAWINFO_CP
#define full_infrabb_test_reset full_drawinfo_test_reset
#define full_infrabb_dispatch full_drawinfo_dispatch
#define full_infrabb_release_reply full_drawinfo_release_reply
#define full_infrabb_snapshot full_drawinfo_snapshot
#define full_infrabb_registry full_drawinfo_registry
#define TEST_TYPE 6
#define TEST_DIR 1
#define TEST_INDEX 0
#define CHANGED_SLOT 1
#define REPLY_HEADER 0
#define COUNT 2
#else
#define TEST_TYPE 0
#define TEST_DIR 2
#define TEST_INDEX 1
#define CHANGED_SLOT 5
#define REPLY_HEADER FULL_INFRABB_CP
#define COUNT 21
#endif
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <stdio.h>
struct message {unsigned int owner,source,size;unsigned char data[64];};
static void *queued;
static int alloc_error,send_error,frees;
static struct message *head(void *p){return (struct message *)((char *)p - offsetof(struct message,data));}
static unsigned int word(void *p,unsigned int i){unsigned int x;memcpy(&x,(char *)p+i*4,4);return x;}
static void put(void *p,unsigned int i,unsigned int x){memcpy((char *)p+i*4,&x,4);}
static int allocate(unsigned int d,void **p,unsigned int n,unsigned int wait){
    assert(wait==1 && n==56);if(alloc_error){*p=0;return -55;}
    struct message *m=calloc(1,sizeof *m);assert(m);m->owner=d;m->size=n;*p=m->data;return 0;
}
static int release(unsigned int d,void *p){assert(head(p)->owner==d);frees++;free(head(p));return 0;}
static void set_source(void *p,unsigned int d){head(p)->source=d;}
static unsigned int size(void *p){return head(p)->size;}
static unsigned int source(void *p){return head(p)->source;}
static int send(unsigned int d,void *p){assert(d==head(p)->owner);if(send_error)return -66;assert(!queued);queued=p;return 0;}
static void record(const char *tag,const char *line){(void)tag;(void)line;}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static void *request(unsigned int type,unsigned int dir,unsigned int index){
    struct message *m=calloc(1,sizeof *m);assert(m);m->owner=FULL_INFRABB_CP;m->source=0x81cf61ca;m->size=48;
    unsigned char *p=m->data;put(p,0,0x81cf61ca);put(p,1,0xa0a0a0a0);put(p,2,0x00300001);put(p,3,24);put(p,4,48);
    put(p,6,0x00001000);put(p,7,0x00020018);put(p,8,type);put(p,9,dir);put(p,10,index);return p;
}
int main(void){
    full_infrabb_test_reset();int rc=123;void *p=request(TEST_TYPE,TEST_DIR,TEST_INDEX);
    assert(!full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,0,&rc) && rc==123);release(FULL_INFRABB_CP,p);
#if defined(TEST_GRMPIN)
    static const unsigned int keys[1][3]={{1,3,0}};
#elif defined(TEST_DRAWINFO)
    static const unsigned int keys[2][3]={{0,1,0},{6,1,0}};
#else
    static const unsigned int keys[21][3]={{0,1,0},{0,1,1},{0,1,2},{0,1,3},{0,2,0},{0,2,1},{0,2,2},{0,2,3},
        {8,1,0},{8,2,0},{6,2,0},{0,1,10},{0,1,11},{0,1,12},{0,1,13},{0,2,10},{0,2,11},{0,2,12},{0,2,13},{8,1,10},{8,2,10}};
#endif
    for(unsigned int i=0;i<COUNT;i++){
        p=request(keys[i][0],keys[i][1],keys[i][2]);assert(full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && !rc && queued);
        assert(word(queued,0)==REPLY_HEADER && word(queued,6)==0x80001000 && word(queued,7)==0x00020020);
        assert(word(queued,8)==keys[i][0] && word(queued,9)==keys[i][1] && word(queued,10)==keys[i][2]);
        assert(word(queued,11)==1 && word(queued,12)==FULL_INFRABB_CP && word(queued,13)==0);
        assert(full_infrabb_release_reply(0x81cf61ca,queued,release,record,&rc) && !rc);queued=0;
    }
    struct full_vef_snapshot s;full_infrabb_snapshot(&s);assert(s.registry_objects==COUNT && s.request_freed==COUNT && s.native_freed==COUNT && !s.live_replies);
    pin_registry_test_set_state(full_infrabb_registry(),CHANGED_SLOT,2);
    p=request(TEST_TYPE,TEST_DIR,TEST_INDEX);assert(full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && !rc && word(queued,11)==2);
    assert(full_infrabb_release_reply(0x81cf61ca,queued,release,record,&rc) && !rc);queued=0;
    pin_registry_test_set_state(full_infrabb_registry(),CHANGED_SLOT,1);
    p=request(0x10000,2,1);
#ifdef TEST_GRMPIN
    assert(full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && !rc && queued);
    assert(word(queued,8)==1 && word(queued,9)==3 && word(queued,10)==0 && word(queued,0)==FULL_GRM_PIN_CP);
    assert(full_infrabb_release_reply(0x81cf61ca,queued,release,record,&rc) && !rc);queued=0;
#else
    assert(full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && rc==-1021 && !queued);release(FULL_INFRABB_CP,p);
#endif
    for(unsigned int i=0;i<2;i++){
        p=request(TEST_TYPE,TEST_DIR,TEST_INDEX);alloc_error=i==0;send_error=i==1;
        assert(full_infrabb_dispatch(FULL_INFRABB_CP,p,&io,1,&rc) && rc==(i?-66:-55) && !queued);
        release(FULL_INFRABB_CP,p);alloc_error=send_error=0;
    }
    full_infrabb_snapshot(&s);assert(!s.pending && !s.live_replies && !s.faults);
#if defined(TEST_GRMPIN)
    puts("GRMPIN_SINGLE_OWN_ATTRIBUTES_NOT_QUERY_ECHO_PASS");
#elif defined(TEST_DRAWINFO)
    puts("DRAWINFO_2_REAL_OBJECTS_FULL_KEYS_OWNER_AND_FAILURE_OWNERSHIP_PASS");
#else
    puts("INFRABB_21_REAL_OBJECTS_FULL_KEYS_OWNER_AND_FAILURE_OWNERSHIP_PASS");
#endif
    return 0;
}
