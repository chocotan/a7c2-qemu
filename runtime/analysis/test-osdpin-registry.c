/* SPDX-License-Identifier: MIT */
#include "osdpin-registry.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block {unsigned int size,source,pool;unsigned char data[56];};
static struct block *header(void *p){return (void *)((char *)p - offsetof(struct block,data));}
static void *queued;
static unsigned int request_frees,reply_frees,scope_events;
static int send_error;
static unsigned int source(void *p){return header(p)->source;}
static unsigned int size(void *p){return header(p)->size;}
static void set_source(void *p,unsigned int s){header(p)->source=s;}
static int allocate(unsigned int id,void **out,unsigned int bytes,unsigned int count){
    assert(id==0x81cf6789 && bytes==56 && count==1);
    struct block *b=calloc(1,sizeof *b);assert(b);b->pool=id;b->size=bytes;*out=b->data;return 0;
}
static int release(unsigned int id,void *p){
    assert(header(p)->pool==id);
    if(id==NATIVE_OSDPIN_CP)request_frees++;else reply_frees++;
    free(header(p));return 0;
}
static int send(unsigned int id,void *p){
    assert(!queued && id==0x81cf6789 && source(p)==NATIVE_OSDPIN_CP);
    if(send_error)return send_error;
    queued=p;return 0;
}
static void record(const char *tag,const char *text){
    if(!strcmp(tag,"FULL_OSDPIN_SCOPE ")){
        assert(strstr(text,"event_emitted=0") && strstr(text,"event_consumer_verified=0"));scope_events++;
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static void *request(unsigned int type){
    static const unsigned char raw[48]={
        0x89,0x67,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,48,0,24,0,0,0,
        48,0,0,0,0x7f,0xab,0xcd,0xef,0,0x10,0,0,24,0,2,0,1,0,0,0,3,0,0,0};
    struct block *b=calloc(1,sizeof *b);assert(b);
    b->pool=NATIVE_OSDPIN_CP;b->source=0x81cf6001;b->size=48;
    memcpy(b->data,raw,48);memcpy(b->data+32,&type,4);return b->data;
}
int main(void){
    int rc=123;void *p=request(1);
    assert(!native_osdpin_dispatch(NATIVE_OSDPIN_CP,p,&io,0,&rc) && rc==123 && !queued);
    assert(native_osdpin_dispatch(NATIVE_OSDPIN_CP,p,&io,1,&rc) && !rc);
    static const unsigned char expected[56]={
        0x3b,0,0x80,0x90,0xa0,0xa0,0xa0,0xa0,1,0,56,0,24,0,0,0,
        56,0,0,0,0,0,0,0,0,0x10,0,0x80,32,0,2,0,1,0,0,0,3,0,0,0,
        0,0,0,0,1,0,0,0,0x3b,0,0x80,0x90,0,0,0,0};
    assert(!memcmp(queued,expected,56) && scope_events==1);
    struct full_vef_snapshot s;native_osdpin_snapshot(&s);
    assert(s.registry_objects==1 && s.pins[0].state==1 && s.pins[0].peer[0]==255 && s.pins[0].peer[1]==255);
    assert(native_osdpin_release_reply(0x81cf6789,queued,release,record,&rc) && !rc);queued=0;
    assert(request_frees==1 && reply_frees==1);
    for(unsigned int mode=0;mode<4;mode++){
        p=request(mode==0?0x101:1);
        if(mode==1)((unsigned char *)p)[26]=1;
        if(mode==2)header(p)->size=47;
        if(mode==3)memset(p,0,4);
        assert(native_osdpin_dispatch(NATIVE_OSDPIN_CP,p,&io,1,&rc) && rc==-1021 && !queued);
        assert(scope_events==1);release(NATIVE_OSDPIN_CP,p);
    }
    p=request(1);send_error=-66;
    assert(native_osdpin_dispatch(NATIVE_OSDPIN_CP,p,&io,1,&rc) && rc==-66 && !queued);
    send_error=0;release(NATIVE_OSDPIN_CP,p);
    native_osdpin_snapshot(&s);assert(!s.faults && !s.live_replies && s.queries==1 && s.pins[0].state==1);
    puts("OSDPIN_OBSERVED_130_OWN_REPLY_SID_GET_ONLY_EVENT_OMISSION_EXPLICIT_PASS");return 0;
}
