/* SPDX-License-Identifier: MIT */
#include "infrabb-registry.h"
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
    assert(id==0x81cf61c8 && bytes==56 && count==1);
    struct block *b=calloc(1,sizeof *b);assert(b);
    b->pool=id;b->size=bytes;*out=b->data;return 0;
}
static int release(unsigned int id,void *p) {
    assert(header(p)->pool==id);
    if(id==NATIVE_INFRABB_CP) ++request_frees;else ++reply_frees;
    free(header(p));return 0;
}
static int send(unsigned int id,void *p) {
    assert(!queued && id==0x81cf61c8 && source(p)==NATIVE_INFRABB_CP);
    queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(unsigned int type,unsigned int dir,unsigned int index) {
    /* Original run-q9w2fg7h envelope; opaque +20 is deliberately nonzero. */
    static const unsigned char raw[48]={
        0xc8,0x61,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,48,0,24,0,0,0,
        48,0,0,0,0x7f,0,0,0,0,0x10,0,0,24,0,2,0};
    struct block *b=calloc(1,sizeof *b);assert(b);
    b->pool=NATIVE_INFRABB_CP;b->source=0x81cf61c8;b->size=48;
    memcpy(b->data,raw,48);
    unsigned int fields[3]={type,dir,index};memcpy(b->data+32,fields,12);
    return b->data;
}
static void drain(void) {
    int rc=123;
    assert(native_infrabb_release_reply(0x81cf61c8,queued,release,0,&rc) && rc==0);
    queued=0;
}
int main(void) {
    int rc=123;void *p=request(0,2,1);
    assert(!native_infrabb_dispatch(NATIVE_INFRABB_CP,p,&io,0,&rc) && rc==123 && !queued);
    assert(native_infrabb_dispatch(NATIVE_INFRABB_CP,p,&io,1,&rc) && !rc);
    static const unsigned char expected[56]={
        0x4a,7,0x84,0x92,0xa0,0xa0,0xa0,0xa0,1,0,56,0,24,0,0,0,
        56,0,0,0,0,0,0,0,0,0x10,0,0x80,32,0,2,0,
        0,0,0,0,2,0,0,0,1,0,0,0,1,0,0,0,0x4a,7,0x84,0x92,0,0,0,0};
    assert(!memcmp(queued,expected,56));
    struct full_vef_snapshot s;native_infrabb_snapshot(&s);
    assert(s.registry_objects==21 && s.pins[5].state==1 && s.pins[5].self[3]==NATIVE_INFRABB_CP);
    assert(s.pins[5].peer[0]==255 && s.pins[5].peer[1]==255 && !s.pins[5].peer[2] && !s.pins[5].peer[3]);
    drain();assert(request_frees==1 && reply_frees==1);
    /* Full-u32 comparison must reject keys that VEF's low-byte lookup accepts. */
    p=request(0x100,2,1);rc=123;
    assert(native_infrabb_dispatch(NATIVE_INFRABB_CP,p,&io,1,&rc) && rc==-1021 && !queued);
    assert(request_frees==1);release(NATIVE_INFRABB_CP,p);
    p=request(8,2,10);assert(native_infrabb_dispatch(NATIVE_INFRABB_CP,p,&io,1,&rc) && !rc);
    native_infrabb_snapshot(&s);assert(s.pins[20].self[2]==10 && s.queries==2);drain();
    p=request(0,2,1);((unsigned char *)p)[26]=1;rc=123;
    assert(native_infrabb_dispatch(NATIVE_INFRABB_CP,p,&io,1,&rc) && rc==-1021 && !queued);
    release(NATIVE_INFRABB_CP,p);
    native_infrabb_snapshot(&s);assert(!s.live_replies && !s.faults && s.pins[5].state==1);
    puts("INFRABB_21_FULL_KEYS_OWN_REPLY_SID_GET_ONLY_PASS");return 0;
}
