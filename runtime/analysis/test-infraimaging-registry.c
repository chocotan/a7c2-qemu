/* SPDX-License-Identifier: MIT */
#include "infrabb-registry.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct block { unsigned int size,source,pool; unsigned char data[64]; };
static void *queued;
static unsigned int caller=0x81cf61c4,request_frees,reply_frees;
static struct block *header(void *p){return (void *)((char *)p - offsetof(struct block,data));}
static unsigned int size(void *p){return header(p)->size;}
static unsigned int source(void *p){return header(p)->source;}
static void set_source(void *p,unsigned int id){header(p)->source=id;}
static void put32(void *p,unsigned int v){memcpy(p,&v,4);}
static int allocate(unsigned int id,void **out,unsigned int bytes,unsigned int count){
    assert(id==caller && bytes==56 && count==1);
    struct block *b=calloc(1,sizeof *b);assert(b);b->pool=id;b->size=bytes;*out=b->data;return 0;
}
static int release(unsigned int id,void *p){
    assert(header(p)->pool==id);
    if(id==NATIVE_INFRAIMAGING_CP)request_frees++;else{assert(id==caller);reply_frees++;}
    free(header(p));return 0;
}
static int send(unsigned int id,void *p){
    assert(id==caller && source(p)==NATIVE_INFRAIMAGING_CP && !queued);queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(unsigned int type,unsigned int dir,unsigned int index){
    static const unsigned char raw[48]={
        0xc4,0x61,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,48,0,24,0,0,0,
        48,0,0,0,0x7f,0,0,0,0,0x10,0,0,24,0,2,0};
    struct block *b=calloc(1,sizeof *b);assert(b);
    b->pool=NATIVE_INFRAIMAGING_CP;b->source=caller;b->size=48;memcpy(b->data,raw,48);
    put32(b->data,caller);put32(b->data+32,type);put32(b->data+36,dir);put32(b->data+40,index);
    return b->data;
}
static void drain(void){
    int rc=77;
    assert(!native_infrabb_release_reply(caller,queued,release,0,&rc) && rc==77);
    assert(native_infraimaging_release_reply(caller,queued,release,0,&rc) && !rc);queued=0;
}
int main(void){
    int rc=77;void *p=request(0,2,1);
    assert(!native_infraimaging_dispatch(NATIVE_INFRAIMAGING_CP,p,&io,0,&rc) && rc==77 && !queued);
    assert(!native_infraimaging_dispatch(NATIVE_INFRABB_CP,p,&io,1,&rc) && rc==77 && !queued);
    assert(native_infraimaging_dispatch(NATIVE_INFRAIMAGING_CP,p,&io,1,&rc) && !rc);
    /* +20 is virtual zero padding, not a source-proven reserved-field value. */
    static const unsigned char expected[56]={
        4,0,5,0x90,0xa0,0xa0,0xa0,0xa0,1,0,56,0,24,0,0,0,
        56,0,0,0,0,0,0,0,0,0x10,0,0x80,32,0,2,0,
        0,0,0,0,2,0,0,0,1,0,0,0,1,0,0,0,4,0,5,0x90,0,0,0,0};
    assert(queued!=p && !memcmp(queued,expected,56));drain();
    struct full_vef_snapshot s,other;native_infraimaging_snapshot(&s);native_infrabb_snapshot(&other);
    assert(s.registry_objects==6 && s.owner_sid==NATIVE_INFRAIMAGING_CP && s.queries==1);
    assert(!other.initialized && !other.queries && !other.live_replies);
    static const unsigned int keys[6][3]={{0,2,0},{0,2,1},{0,2,2},{0,2,3},{3,2,0},{8,2,0}};
    for(unsigned int i=0;i<6;i++){
        assert(!memcmp(s.pins[i].self,keys[i],12) && s.pins[i].self[3]==NATIVE_INFRAIMAGING_CP);
        assert(s.pins[i].state==1 && s.pins[i].peer[0]==255 && s.pins[i].peer[1]==255 && !s.pins[i].peer[2] && !s.pins[i].peer[3]);
        caller=(i&1)?0x81cf61c8:0x81cf61c4;p=request(keys[i][0],keys[i][1],keys[i][2]);
        put32((unsigned char *)p+20,0xa5a5a5a5);
        assert(native_infraimaging_dispatch(NATIVE_INFRAIMAGING_CP,p,&io,1,&rc) && !rc);
        assert(!memcmp((unsigned char *)queued+32,keys[i],12));drain();
    }
    static const unsigned int invalid[5][3]={{0x100,2,1},{0,0x102,1},{0,2,0x101},{0,1,0},{3,2,1}};
    for(unsigned int i=0;i<5;i++){
        p=request(invalid[i][0],invalid[i][1],invalid[i][2]);unsigned int before=request_frees;
        assert(native_infraimaging_dispatch(NATIVE_INFRAIMAGING_CP,p,&io,1,&rc) && rc==-1021 && !queued);
        assert(request_frees==before);release(NATIVE_INFRAIMAGING_CP,p);
    }
    p=request(0,2,1);header(p)->size=64;((unsigned char *)p)[10]=64;put32((unsigned char *)p+16,64);
    ((unsigned char *)p)[26]=1;((unsigned char *)p)[28]=40;
    assert(native_infraimaging_dispatch(NATIVE_INFRAIMAGING_CP,p,&io,1,&rc) && rc==-1021 && !queued);
    release(NATIVE_INFRAIMAGING_CP,p);native_infraimaging_snapshot(&s);
    assert(s.queries==7 && !s.faults && !s.pending && !s.live_replies && s.native_freed==7);
    for(unsigned int i=0;i<6;i++)assert(s.pins[i].state==1);
    caller=0x81cf61c4;p=request(0,2,1);
    assert(native_infraimaging_dispatch(NATIVE_INFRAIMAGING_CP,p,&io,1,&rc) && !rc);
    assert(native_infraimaging_release_reply(caller^4,queued,release,0,&rc) && rc==-1021);
    native_infraimaging_snapshot(&s);assert(s.faults==1 && s.live_replies==1 && reply_frees==7);
    drain();native_infraimaging_snapshot(&s);
    assert(!s.live_replies && s.faults==1 && reply_frees==8 && request_frees==14);
    puts("INFRAIMAGING_SIX_FULL_KEYS_DYNAMIC_CALLERS_COLD_GET_ONLY_PASS");
    return 0;
}
