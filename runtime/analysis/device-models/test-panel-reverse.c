/* SPDX-License-Identifier: MIT */
#include "vdf-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block {unsigned int size,source,pool;unsigned char data[28];};
static struct block *header(void *p){return (void *)((char *)p - offsetof(struct block,data));}
static void *queued;static int send_error;static unsigned int requests,replies;
static unsigned int size(void *p){return header(p)->size;}
static unsigned int source(void *p){return header(p)->source;}
static void set_source(void *p,unsigned int id){header(p)->source=id;}
static int release(unsigned int id,void *p){assert(header(p)->pool==id);if(id==FULL_VDF_INPUT)requests++;else replies++;free(header(p));return 0;}
static int allocate(unsigned int id,void **p,unsigned int n,unsigned int count){
    assert(id==0x81cf61c5 && n==12 && count==1);struct block *b=calloc(1,sizeof *b);assert(b);
    b->size=n;b->pool=id;*p=b->data;return 0;
}
static int send(unsigned int id,void *p){
    static const unsigned char expected[12]={0x0d,0x20,0x19,0x11,12,0,1,0x80};
    assert(!queued && id==0x81cf61c5 && size(p)==12 && source(p)==FULL_VDF_INPUT && !memcmp(p,expected,12));
    if(send_error)return send_error;
    queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(unsigned int h,unsigned int v){
    struct block *b=calloc(1,sizeof *b);assert(b);b->size=28;b->pool=FULL_VDF_INPUT;b->source=0x81cf61c5;
    const unsigned char raw[8]={0x0d,0x20,0x19,1,28,0,1,0x80};memcpy(b->data,raw,8);
    b->data[8]=(unsigned char)h;b->data[9]=(unsigned char)v;return b->data;
}
int main(void){
    int rc=123;void *p=request(1,1);assert(!full_vdf_reverse_dispatch(FULL_VDF_INPUT,p,&io,0,&rc) && rc==123);
    release(FULL_VDF_INPUT,p);
    for(unsigned int h=0;h<=1;h++)for(unsigned int v=0;v<=1;v++){
        p=request(h,v);assert(full_vdf_reverse_dispatch(FULL_VDF_INPUT,p,&io,1,&rc) && !rc && queued);
        struct full_vdf_snapshot s;full_vdf_snapshot(&s);
        assert(s.reverse_properties[0]==0 && s.reverse_properties[1]==h && s.reverse_properties[2]==v && s.reverse_properties[3]==0);
        assert(s.reverse_control==2*h+v && !s.reverse_osd && !s.applied && !s.panel_applied);
        assert(full_vdf_release_reply(0x81cf61c5,queued,release,0,&rc) && !rc);queued=0;
    }
    struct full_vdf_snapshot before;full_vdf_snapshot(&before);
    p=request(0,0);send_error=-66;assert(full_vdf_reverse_dispatch(FULL_VDF_INPUT,p,&io,1,&rc) && rc==-66 && !queued);
    send_error=0;release(FULL_VDF_INPUT,p);
    struct full_vdf_snapshot s;full_vdf_snapshot(&s);assert(s.reverse_applied==4 && s.reverse_control_consumed==4 && s.reverse_control==3);
    for(unsigned int kind=0;kind<4;kind++){
        p=request(1,1);
        if(kind==0)((unsigned char *)p)[8]=2;
        if(kind==1)((unsigned char *)p)[10]=1;
        if(kind==2)((unsigned char *)p)[12]=1;
        if(kind==3)header(p)->size=27;
        assert(full_vdf_reverse_dispatch(FULL_VDF_INPUT,p,&io,1,&rc) && rc==-1021 && !queued);release(FULL_VDF_INPUT,p);
    }
    full_vdf_snapshot(&s);assert(!s.faults && !s.live_replies && s.reverse_applied==before.reverse_applied);
    assert(s.waiter_freed==4 && requests==10 && replies==5);
    puts("VDF_PANEL_REVERSE_VIRTUAL_CONFIG_ZERO_STATUS_CONTROL_READBACK_ROLLBACK_PASS");return 0;
}
