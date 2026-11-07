/* SPDX-License-Identifier: MIT */
#include "vdf-device.h"
#include <assert.h>
#include <stddef.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block { unsigned int bytes,source,pool;unsigned char data[16]; };
static struct block *header(void *p) { return (void *)((char *)p - offsetof(struct block,data)); }
static const unsigned char raw10[10]={0x0d,0x20,0x65,1,10,0,1,0x80,2,0};
/* Includes the 00590000 namespace OR from the actual 7b9 relay. */
static const unsigned char raw12[12]={0x0d,0x20,0x65,0x11,12,0,1,0x80,0,0,0x59,0};
static void *queued,*failed;
static int allocation_error,send_error,free_error,request_error;
static unsigned int freed_requests,freed_replies,allocations;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition=PTHREAD_COND_INITIALIZER;
static int delay_allocate,entered,proceed;
static int allocate(unsigned int id,void **out,unsigned int n,unsigned int count) {
    assert(id>>28==8 && n==12 && count==1);
    pthread_mutex_lock(&mutex);allocations++;
    if (delay_allocate) { entered=1;pthread_cond_broadcast(&condition);while (!proceed) pthread_cond_wait(&condition,&mutex); }
    int rc=allocation_error;pthread_mutex_unlock(&mutex);
    if (rc) return rc;
    struct block *b=calloc(1,sizeof *b);assert(b);b->bytes=n;b->pool=id;*out=b->data;return 0;
}
static int release(unsigned int id,void *p) {
    assert(header(p)->pool==id);
    int rc=id==FULL_VDF_INPUT?request_error:free_error;
    if (rc) { failed=p;return rc; }
    if (id==FULL_VDF_INPUT) freed_requests++;else freed_replies++;
    free(header(p));return 0;
}
static unsigned int size(void *p) { return header(p)->bytes; }
static unsigned int source(void *p) { return header(p)->source; }
static void set_source(void *p,unsigned int id) { header(p)->source=id; }
static int send(unsigned int id,void *p) {
    assert(id==header(p)->pool && source(p)==FULL_VDF_INPUT && size(p)==12);
    assert(!memcmp(p,raw12,8) && !memcmp((char *)p+9,raw12+9,3));
    if (send_error) return send_error;
    assert(!queued);queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(unsigned int value,unsigned int id) {
    struct block *b=calloc(1,sizeof *b);assert(b);b->bytes=10;b->pool=FULL_VDF_INPUT;b->source=id;
    memcpy(b->data,raw10,10);b->data[9]=(unsigned char)value;return b->data;
}
static struct full_vdf_snapshot snapshot(void) { struct full_vdf_snapshot s;full_vdf_snapshot(&s);return s; }
static void reset(void) {
    assert(!queued && !failed);allocation_error=send_error=free_error=request_error=0;
    freed_requests=freed_replies=allocations=0;delay_allocate=entered=proceed=0;full_vdf_test_reset();
}
static void drain(void) {
    assert(queued);int rc=123;
    assert(full_vdf_release_reply(header(queued)->pool,queued,release,0,&rc) && !rc);queued=0;
}
static void accept(unsigned int value) {
    int rc=123;assert(full_vdf_dispatch(FULL_VDF_INPUT,request(value,0x81cf61c4),&io,1,&rc) && !rc);
}
static void *worker(void *p) {
    int rc=123;assert(full_vdf_dispatch(FULL_VDF_INPUT,p,&io,1,&rc) && !rc);return 0;
}
int main(void) {
    reset();int rc=123;void *p=request(0,0x81cf61c4);
    assert(!full_vdf_dispatch(FULL_VDF_INPUT,p,&io,0,&rc) && rc==123 && !allocations);release(FULL_VDF_INPUT,p);
    for (unsigned int value=0;value<3;value++) {
        accept(value);struct full_vdf_snapshot s=snapshot();
        assert(s.panel_shadow[2]==0x40 && s.panel_shadow[0x3c]==2 && s.panel_shadow[0x3d]==value);
        assert(s.panel_valid[1]==1 && s.panel_size[1]==value && !s.panel_valid[0]);
        assert(!s.panel_pending && !s.panel_caller && !s.faults);
        assert(freed_requests==value+2 && freed_replies==value);
        assert(!memcmp(queued,raw12,12));drain();
    }
    struct full_vdf_snapshot before=snapshot();accept(3);struct full_vdf_snapshot s=snapshot();
    assert(((unsigned char *)queued)[8]==1 && !memcmp((char *)queued+9,raw12+9,3));
    assert(!memcmp(s.panel_shadow,before.panel_shadow,64) && s.panel_size[1]==before.panel_size[1]);
    assert(s.panel_applied==before.panel_applied && s.panel_invalid==1);drain();
    for (unsigned int failure=0;failure<3;failure++) {
        reset();p=request(1,0x81cf61c4);
        if (!failure) allocation_error=-55;else send_error=-66;
        if (failure==2) free_error=-77;
        assert(full_vdf_dispatch(FULL_VDF_INPUT,p,&io,1,&rc) && rc==(failure?-66:-55));
        s=snapshot();assert(!s.panel_applied && !s.panel_shadow[2] && !s.panel_pending && !s.panel_caller && !queued);
        assert(s.faults==(failure==2));
        if (failed) { free_error=0;release(0x81cf61c4,failed);failed=0; }
        release(FULL_VDF_INPUT,p);
    }
    reset();delay_allocate=1;p=request(0,0x81cf61c4);pthread_t thread;
    assert(!pthread_create(&thread,0,worker,p));
    pthread_mutex_lock(&mutex);while (!entered) pthread_cond_wait(&condition,&mutex);pthread_mutex_unlock(&mutex);
    s=snapshot();assert(s.panel_pending==1 && s.panel_caller==0x81cf61c4);
    void *second=request(1,0x81cf61c3);
    assert(full_vdf_dispatch(FULL_VDF_INPUT,second,&io,1,&rc) && rc==-1021 && allocations==1);
    release(FULL_VDF_INPUT,second);
    pthread_mutex_lock(&mutex);proceed=1;pthread_cond_broadcast(&condition);pthread_mutex_unlock(&mutex);
    assert(!pthread_join(thread,0));assert(header(queued)->pool==0x81cf61c4);drain();
    reset();request_error=-88;accept(0);s=snapshot();assert(s.faults==1 && failed && queued);
    request_error=0;release(FULL_VDF_INPUT,failed);failed=0;drain();
    p=request(1,0x81cf61c4);assert(full_vdf_dispatch(FULL_VDF_INPUT,p,&io,1,&rc) && rc==-1021);release(FULL_VDF_INPUT,p);
    puts("PANEL_RESOLUTION_SHADOW_RAW_DOMAIN_OWNERSHIP_PASS");return 0;
}
