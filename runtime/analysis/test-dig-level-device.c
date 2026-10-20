/* SPDX-License-Identifier: MIT */
#include "dig-level-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block {unsigned int size,source,pool;unsigned char data[24];};
static struct block *header(void *p){return (void *)((char *)p - offsetof(struct block,data));}
static void *queued;static int send_error,alloc_error;
static unsigned int request_frees,reply_frees,consumption_records;
static unsigned int size(void *p){return header(p)->size;}
static unsigned int source(void *p){return header(p)->source;}
static void set_source(void *p,unsigned int id){header(p)->source=id;}
static int release(unsigned int id,void *p){
    assert(header(p)->pool==id);
    if(id==NATIVE_DIG_LEVEL_SID)request_frees++;else reply_frees++;
    free(header(p));return 0;
}
static int allocate(unsigned int id,void **p,unsigned int bytes,unsigned int count){
    assert(id==0x81cf61c5 && bytes==24 && count==1);
    if(alloc_error){*p=0;return alloc_error;}
    struct block *b=calloc(1,sizeof *b);assert(b);b->pool=id;b->size=bytes;*p=b->data;return 0;
}
static int send(unsigned int id,void *p){
    assert(!queued && id==0x81cf61c5 && source(p)==NATIVE_DIG_LEVEL_SID && size(p)==24);
    static const unsigned char expected[24]={3};assert(!memcmp(p,expected,24));
    if(send_error)return send_error;
    queued=p;return 0;
}
static void record(const char *tag,const char *text){
    if(!strcmp(tag,"FULL_DIG_LEVEL_CONTROL_CONSUMED ")){
        assert(strstr(text,"sample_valid=0") && strstr(text,"angle_events=0") && strstr(text,"original_cp_task_running=0"));consumption_records++;
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static void *request(void){
    struct block *b=calloc(1,sizeof *b);assert(b);b->size=24;b->pool=NATIVE_DIG_LEVEL_SID;b->source=0x81cf61c5;b->data[0]=3;return b->data;
}
int main(void){
    struct native_dig_level_snapshot s;int rc=123;void *p=request();
    assert(!native_dig_level_dispatch(NATIVE_DIG_LEVEL_SID,p,&io,0,&rc) && rc==123);
    assert(native_dig_level_dispatch(NATIVE_DIG_LEVEL_SID,p,&io,1,&rc) && !rc && queued);
    native_dig_level_snapshot(&s);assert(s.notification_enabled && s.notification_countdown==30 && s.mode==2 && s.worker_started);
    assert(s.consumed==1 && s.request_freed==1 && s.live_replies==1 && !s.sample_valid && !s.latched_error);
    assert(native_dig_level_release(0x81cf61c5,queued,release,record,&rc) && !rc);queued=0;
    for(unsigned int kind=0;kind<4;kind++){
        p=request();if(kind==0)((unsigned char *)p)[0]=4;
        if(kind==1)((unsigned char *)p)[4]=1;
        if(kind==2)header(p)->size=23;
        if(kind==3)header(p)->source=0;
        assert(native_dig_level_dispatch(NATIVE_DIG_LEVEL_SID,p,&io,1,&rc) && rc==-1021 && !queued);
        release(NATIVE_DIG_LEVEL_SID,p);
    }
    p=request();alloc_error=-55;
    assert(native_dig_level_dispatch(NATIVE_DIG_LEVEL_SID,p,&io,1,&rc) && rc==-55 && !queued);
    release(NATIVE_DIG_LEVEL_SID,p);alloc_error=0;
    native_dig_level_snapshot(&s);assert(s.consumed==1);
    p=request();send_error=-66;
    assert(native_dig_level_dispatch(NATIVE_DIG_LEVEL_SID,p,&io,1,&rc) && rc==-66 && !queued);
    release(NATIVE_DIG_LEVEL_SID,p);send_error=0;
    native_dig_level_snapshot(&s);assert(s.consumed==2 && s.notification_enabled && !s.live_replies);
    p=request();assert(native_dig_level_dispatch(NATIVE_DIG_LEVEL_SID,p,&io,1,&rc) && !rc);
    assert(native_dig_level_release(0x81cf61c5,queued,release,record,&rc) && !rc);queued=0;
    native_dig_level_snapshot(&s);assert(s.consumed==3 && s.notification_countdown==30 && s.waiter_freed==2);
    assert(consumption_records==3 && !s.faults && !s.sample_valid && !s.live_replies);
    assert(request_frees==8 && reply_frees==3);
    puts("DIG_LEVEL_SELECTOR3_VIRTUAL_SUBSCRIPTION_NO_SAMPLES_OWNERSHIP_FAILURE_PASS");return 0;
}
