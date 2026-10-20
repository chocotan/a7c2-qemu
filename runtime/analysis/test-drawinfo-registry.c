/* SPDX-License-Identifier: MIT */
#include "drawinfo-registry.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block { unsigned int size, source, pool; unsigned char data[56]; };
static struct block *header(void *p) { return (void *)((char *)p - offsetof(struct block,data)); }
static void *queued;
static unsigned int request_frees, reply_frees;
static unsigned int source(void *p) { return header(p)->source; }
static unsigned int size(void *p) { return header(p)->size; }
static void set_source(void *p,unsigned int s) { header(p)->source=s; }
static int allocate(unsigned int id,void **out,unsigned int bytes,unsigned int count) {
    assert(id==0x81cf6789 && bytes==56 && count==1);
    struct block *b=calloc(1,sizeof *b);assert(b);
    b->pool=id;b->size=bytes;*out=b->data;return 0;
}
static int release(unsigned int id,void *p) {
    assert(header(p)->pool==id);
    if(id==NATIVE_DRAWINFO_CP)++request_frees;else ++reply_frees;
    free(header(p));return 0;
}
static int send(unsigned int id,void *p) {
    assert(!queued && id==0x81cf6789 && source(p)==NATIVE_DRAWINFO_CP);
    queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(unsigned int type) {
    static const unsigned char raw[48]={
        0x89,0x67,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,48,0,24,0,0,0,
        48,0,0,0,0x7f,0xab,0xcd,0xef,0,0x10,0,0,24,0,2,0,
        6,0,0,0,1,0,0,0};
    struct block *b=calloc(1,sizeof *b);assert(b);
    b->pool=NATIVE_DRAWINFO_CP;b->source=0x81cf6001;b->size=48;
    memcpy(b->data,raw,48);memcpy(b->data+32,&type,4);return b->data;
}
int main(void) {
    int rc=123;void *p=request(6);
    assert(!native_drawinfo_dispatch(NATIVE_DRAWINFO_CP,p,&io,0,&rc) && rc==123 && !queued);
    assert(native_drawinfo_dispatch(NATIVE_DRAWINFO_CP,p,&io,1,&rc) && !rc);
    static const unsigned char expected[56]={
        0,0,0,0,0xa0,0xa0,0xa0,0xa0,1,0,56,0,24,0,0,0,
        56,0,0,0,0,0,0,0,0,0x10,0,0x80,32,0,2,0,
        6,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0x83,7,0x8d,0x92,0,0,0,0};
    assert(!memcmp(queued,expected,56));
    struct full_vef_snapshot s;native_drawinfo_snapshot(&s);
    assert(s.registry_objects==2 && s.pins[1].self[0]==6 && s.pins[1].state==1);
    assert(s.pins[0].state==1 && s.pins[0].peer[0]==255 && s.pins[1].peer[1]==255);
    assert(native_drawinfo_release_reply(0x81cf6789,queued,release,0,&rc) && !rc);queued=0;
    assert(request_frees==1 && reply_frees==1);
    p=request(0x106);rc=123;
    assert(native_drawinfo_dispatch(NATIVE_DRAWINFO_CP,p,&io,1,&rc) && rc==-1021 && !queued);
    assert(request_frees==1);release(NATIVE_DRAWINFO_CP,p);
    p=request(0);assert(native_drawinfo_dispatch(NATIVE_DRAWINFO_CP,p,&io,1,&rc) && !rc);
    assert(native_drawinfo_release_reply(0x81cf6789,queued,release,0,&rc) && !rc);queued=0;
    p=request(6);((unsigned char *)p)[26]=1;
    assert(native_drawinfo_dispatch(NATIVE_DRAWINFO_CP,p,&io,1,&rc) && rc==-1021 && !queued);
    release(NATIVE_DRAWINFO_CP,p);native_drawinfo_snapshot(&s);
    assert(!s.faults && !s.live_replies && s.queries==2 && s.pins[1].state==1);
    puts("DRAWINFO_TWO_OBJECTS_FULL_KEYS_DYNAMIC_DEST_ZERO_REPLY_SID_PASS");return 0;
}
