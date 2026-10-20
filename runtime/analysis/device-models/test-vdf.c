/* SPDX-License-Identifier: MIT */
/* Original raw52 and independent CP reply36 fixtures; real ownership callbacks
 * and a deterministic reused-address race, with no VM or device dependencies. */
#include "vdf-device.h"
#include <assert.h>
#include <stddef.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const unsigned char raw52[52]={
    0xc4,0x61,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,0x34,0,0x18,0,0,0,
    0x34,0,0,0,0x7f,0,0,0,1,0x20,5,2,0x1c,0,1,0,
    1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
};
/* CP 6e339e/68af96/68c67a producer, not copied from the implementation.
 * Header bytes20..23 are opaque and excluded from the comparison. */
static const unsigned char reply36[36]={
    0,0,0,0,0xa0,0xa0,0xa0,0xa0,1,0,0x24,0,0x18,0,0,0,
    0x24,0,0,0,0xee,0xdd,0xcc,0xbb,1,0x20,5,0x12,0x0c,0,1,0,0,0,0,0
};
static const unsigned char internal28[28]={
    1,0x20,0x33,0xf0,0x1c,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
};
static const unsigned char evf40[40]={
    0xc2,0x61,0xcf,0x81,0xa0,0xa0,0xa0,0xa0,1,0,40,0,24,0,0,0,
    40,0,0,0,1,4,0x10,0x40,1,0x20,0x0b,2,16,0,1,0,
    0x8d,0x61,0xcf,0x81,1,1,0,0
};
struct block { unsigned int size,source,pool;unsigned char body[64]; };
static struct block *header(void *p) { return (void *)((char *)p - offsetof(struct block,body)); }
static pthread_mutex_t mock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static void *queue[16],*failed_reply,*failed_request,*duplicate_return;
static unsigned int qn,cp_freed,ap_freed,alloc_calls,send_calls,free_calls;
static int alloc_error,alloc_null,alloc_dirty,send_error,reply_error,request_error;
static unsigned int queued_logs,free_logs,fault_logs;
static unsigned long long freed_serial[16];
static struct block reused;
static int reuse_mode,available,allocation_waiting,claimed,free_entered,finish_free;
static unsigned int reused_frees;

static int allocate(unsigned int pool,void **out,unsigned int bytes,unsigned int count) {
    assert(pool>>28==8 && bytes==36 && count==1);
    pthread_mutex_lock(&mock);alloc_calls++;
    if (duplicate_return) { *out=duplicate_return;pthread_mutex_unlock(&mock);return 0; }
    if (alloc_error && !alloc_dirty) { int rc=alloc_error;pthread_mutex_unlock(&mock);return rc; }
    if (alloc_null) { *out=0;pthread_mutex_unlock(&mock);return 0; }
    struct block *b;
    if (reuse_mode) {
        while (!available) {
            allocation_waiting=1;pthread_cond_broadcast(&changed);
            pthread_cond_wait(&changed,&mock);
        }
        available=0;b=&reused;
        if (free_entered) { claimed=1;pthread_cond_broadcast(&changed); }
    } else { b=calloc(1,sizeof *b);assert(b); }
    b->size=bytes;b->pool=pool;b->source=0;*out=b->body;
    int rc=alloc_error;pthread_mutex_unlock(&mock);return rc;
}
static int release(unsigned int pool,void *p) {
    pthread_mutex_lock(&mock);
    struct block *b=header(p);assert(b->pool==pool);free_calls++;
    int rc=pool==FULL_VDF_CP?request_error:reply_error;
    if (rc) {
        if (pool==FULL_VDF_CP) failed_request=p;else failed_reply=p;
        pthread_mutex_unlock(&mock);return rc;
    }
    if (b==&reused) {
        reused_frees++;
        if (reused_frees==1) {
            free_entered=1;available=1;pthread_cond_broadcast(&changed);
            while (!finish_free) pthread_cond_wait(&changed,&mock);
        } else available=1;
    } else free(b);
    if (pool==FULL_VDF_CP) cp_freed++;else ap_freed++;
    pthread_cond_broadcast(&changed);pthread_mutex_unlock(&mock);return 0;
}
static unsigned int size(void *p) { return header(p)->size; }
static unsigned int source(void *p) { return header(p)->source; }
static void set_source(void *p,unsigned int id) { header(p)->source=id; }
static int send(unsigned int dst,void *p) {
    pthread_mutex_lock(&mock);send_calls++;
    assert(dst==header(p)->pool && source(p)==FULL_VDF_CP && size(p)==36);
    int rc=send_error;
    if (!rc) { assert(qn<16);queue[qn++]=p; }
    pthread_cond_broadcast(&changed);pthread_mutex_unlock(&mock);return rc;
}
static void record(const char *tag,const char *line) {
    pthread_mutex_lock(&mock);
    assert(strlen(tag)+strlen(line)+6<512); /* Derived observer's console buffer. */
    if (!strcmp(tag,"FULL_VDF_REPLY_QUEUED ")) { queued_logs++;assert(strstr(line,"raw=")); }
    if (!strcmp(tag,"FULL_VDF_NATIVE_REPLY_FREE ")) {
        const char *s=strstr(line,"lease=");assert(s && free_logs<16);
        freed_serial[free_logs++]=strtoull(s+6,0,10);assert(strstr(line,"rc=0"));
    }
    if (!strcmp(tag,"FULL_VDF_FAULT ")) fault_logs++;
    if (!strcmp(tag,"FULL_VDF_COMMIT ") && strstr(line,"applied=1 ") && strstr(line,"status=0 "))
        assert(strstr(line,"cache_before=1 ") && strstr(line,"cache_after=0 "));
    pthread_mutex_unlock(&mock);
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static void put32(unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(n>>(8*i));
}
static void *request(const unsigned char *bytes,unsigned int n,unsigned int src) {
    assert(n<=64);struct block *b=calloc(1,sizeof *b);assert(b);
    b->size=n;b->source=src;b->pool=FULL_VDF_CP;memcpy(b->body,bytes,n);return b->body;
}
static struct full_vdf_snapshot snapshot(void) {
    struct full_vdf_snapshot s;full_vdf_snapshot(&s);return s;
}
static void reset(void) {
    assert(qn==0 && !failed_reply && !failed_request);
    cp_freed=ap_freed=alloc_calls=send_calls=free_calls=0;
    alloc_error=alloc_null=alloc_dirty=send_error=reply_error=request_error=0;
    duplicate_return=0;
    queued_logs=free_logs=fault_logs=0;memset(freed_serial,0,sizeof freed_serial);
    reuse_mode=available=allocation_waiting=claimed=free_entered=finish_free=0;reused_frees=0;
    full_vdf_test_reset();
}
static void *pop(void) {
    pthread_mutex_lock(&mock);assert(qn);void *p=queue[0];
    memmove(queue,queue+1,--qn*sizeof queue[0]);pthread_mutex_unlock(&mock);return p;
}
static void native_free(void *p) {
    int rc=123;unsigned int dst=header(p)->pool;
    assert(full_vdf_release_reply(dst,p,release,record,&rc) && !rc);
}
static void drain(void) { native_free(pop()); }
static void accepted(const unsigned char *bytes,unsigned int src) {
    int rc=123;assert(full_vdf_dispatch(FULL_VDF_CP,request(bytes,52,src),&io,1,&rc) && !rc);
}
static void expected_reply(void *p,unsigned int status) {
    unsigned char expected[36];memcpy(expected,reply36,36);expected[32]=(unsigned char)status;
    assert(size(p)==36 && source(p)==FULL_VDF_CP);
    assert(!memcmp(p,expected,20) && !memcmp((unsigned char *)p+24,expected+24,12));
}
static void rejected(const unsigned char *bytes,unsigned int n,unsigned int src) {
    struct full_vdf_snapshot before=snapshot();unsigned int freed=cp_freed,alloced=alloc_calls;
    void *p=request(bytes,n,src);int rc=123;
    assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==-1021);
    struct full_vdf_snapshot after=snapshot();
    assert(cp_freed==freed && alloc_calls==alloced && !qn);
    assert(!memcmp(after.body,before.body,20) && after.applied==before.applied);
    assert(!release(FULL_VDF_CP,p));
}

struct work { void *request;int rc; };
static void *dispatch_thread(void *arg) {
    struct work *w=arg;assert(full_vdf_dispatch(FULL_VDF_CP,w->request,&io,1,&w->rc));return 0;
}
static void *free_thread(void *p) { native_free(p);return 0; }
static void aba_race(void) {
    reset();reuse_mode=available=1;
    accepted(raw52,0x81cf61c4);void *old=pop();expected_reply(old,0);
    unsigned char next[52];memcpy(next,raw52,52);put32(next,0x8fabcdef);next[33]=1;
    struct work w={request(next,52,0x8fabcdef),123};pthread_t sender,receiver;
    assert(!pthread_create(&sender,0,dispatch_thread,&w));
    pthread_mutex_lock(&mock);
    while (!allocation_waiting) pthread_cond_wait(&changed,&mock);
    pthread_mutex_unlock(&mock);
    assert(!pthread_create(&receiver,0,free_thread,old));
    pthread_mutex_lock(&mock);
    while (!claimed) pthread_cond_wait(&changed,&mock);
    /* New allocation now owns the identical pool address, while the old real
     * free has not returned. New dispatch must not send/register over its lease. */
    assert(free_entered && send_calls==1 && queued_logs==1 && ap_freed==0);
    finish_free=1;pthread_cond_broadcast(&changed);pthread_mutex_unlock(&mock);
    assert(!pthread_join(receiver,0));assert(!pthread_join(sender,0));assert(w.rc==0);
    struct full_vdf_snapshot s=snapshot();
    assert(s.native_freed==1 && s.waiter_freed==0 && s.live_replies==1 && !s.faults);
    assert(s.queued==2 && s.hdmi_cache==1 && s.applied==2 && cp_freed==2 && ap_freed==1);
    void *now=pop();assert(now==old && header(now)->pool==0x8fabcdef);expected_reply(now,0);
    native_free(now);s=snapshot();
    assert(s.native_freed==2 && s.live_replies==0 && s.waiter_freed==0 && !s.faults);
    assert(ap_freed==2 && free_logs==2 && freed_serial[0]==1 && freed_serial[1]==2);
}

static void subscribed(const unsigned char *bytes) {
    int rc=123;
    assert(full_vdf_dispatch(FULL_VDF_CP,request(bytes,40,0x81cf61c2),&io,1,&rc) && !rc);
}
static void evf_subscriptions(void) {
    reset();struct full_vdf_snapshot s=snapshot();
    const unsigned char initial[4]={0,1,0,0};
    assert(!s.evf_valid && !s.evf_retained && !memcmp(s.evf_status,initial,4));
    alloc_error=send_error=-55; /* Any invented ACK/event must fail the test. */
    subscribed(evf40);s=snapshot();
    assert(!memcmp(s.evf_subscription,evf40+32,8) && s.evf_subscriptions==1);
    assert(s.evf_retained && !s.evf_valid && !s.applied && !s.hdmi_consumed);
    assert(cp_freed==1 && !alloc_calls && !send_calls && !qn && !s.faults);
    for (unsigned int temp=0;temp<3;temp++) for (unsigned int device=0;device<3;device++) {
        unsigned char bytes[40];memcpy(bytes,evf40,40);
        put32(bytes+32,0x8abc1000+3*temp+device);
        bytes[36]=(unsigned char)temp;bytes[37]=(unsigned char)device;
        bytes[38]=0xa5;bytes[39]=0xff;
        subscribed(bytes);s=snapshot();
        assert(!memcmp(s.evf_subscription,bytes+32,8));
        assert(s.evf_retained==(temp==1 || device==1));
        assert(!s.evf_valid && !memcmp(s.evf_status,initial,4));
        assert(!alloc_calls && !send_calls && !qn && !s.faults);
    }
    unsigned char bytes[40];memcpy(bytes,evf40,40);memset(bytes+32,0,8);
    subscribed(bytes);s=snapshot();
    assert(!s.evf_retained && !memcmp(s.evf_subscription,bytes+32,8));
    assert(s.evf_subscriptions==11 && cp_freed==11 && !alloc_calls && !send_calls);
    rejected(evf40,39,0x81cf61c2);
    alloc_error=send_error=0;accepted(raw52,0x81cf61c4);drain();s=snapshot();
    assert(!memcmp(s.evf_subscription,bytes+32,8) && !s.evf_valid && !s.evf_retained);
    reset();request_error=-88;subscribed(evf40);s=snapshot();
    assert(s.faults==1 && failed_request && s.retained_request==failed_request);
    assert(!cp_freed && !alloc_calls && !send_calls && !qn && fault_logs==1);
    request_error=0;assert(!release(FULL_VDF_CP,failed_request));failed_request=0;
    rejected(evf40,40,0x81cf61c2);
    puts("VDF_EVF_SUBSCRIPTION_NO_EVENTS_PASS");
}

int main(void) {
    reset();void *p=request(raw52,52,0x81cf61c4);int rc=123;
    assert(!full_vdf_dispatch(FULL_VDF_CP,p,&io,0,&rc) && rc==123);
    assert(snapshot().configured && !snapshot().enabled && !snapshot().applied && !cp_freed && !alloc_calls);
    assert(snapshot().hdmi_cache==1 && !snapshot().has_config);
    assert(!full_vdf_dispatch(FULL_VDF_CP,p,&io,2,&rc));
    assert(!full_vdf_dispatch(0x90040193,p,&io,1,&rc));assert(!release(FULL_VDF_CP,p));
    reset();accepted(raw52,0x81cf61c4);
    assert(qn==1 && cp_freed==1 && !ap_freed && alloc_calls==1 && send_calls==1 && queued_logs==1);
    expected_reply(queue[0],0);assert(header(queue[0])->pool==0x81cf61c4);
    struct full_vdf_snapshot s=snapshot();
    assert(s.enabled && s.applied==1 && s.has_config && s.hdmi_consumed==1 && s.hdmi_cache==0);
    assert(!memcmp(s.body,raw52+32,20) && !memcmp(s.internal_packet,internal28,28));
    assert(s.queued==1 && s.request_freed==1 && s.live_replies==1 && !s.native_freed);
    drain();s=snapshot();assert(s.waiter_freed==1 && s.native_freed==1 && !s.live_replies && !s.faults);

    unsigned char bytes[52];
    for (unsigned int tc=0;tc<2;tc++) for (unsigned int valid=0;valid<2;valid++)
        for (unsigned int unnamed12=0;unnamed12<3;unnamed12++) {
            memcpy(bytes,raw52,52);bytes[33]=(unsigned char)tc;bytes[40]=(unsigned char)valid;
            bytes[44]=(unsigned char)unnamed12;
            memset(bytes+20,0xdd,4); /* Legal opaque outer storage. */
            accepted(bytes,0x81cf61c4);expected_reply(queue[0],0);
            s=snapshot();assert(s.hdmi_cache==(tc?1:valid));assert(!memcmp(s.body,bytes+32,20));
            assert(!memcmp(s.internal_packet+8,bytes+32,20));drain();
        }
    for (unsigned int bad=0;bad<3;bad++) {
        memcpy(bytes,raw52,52);bytes[bad==0?44:(bad==1?32:33)]=(unsigned char)(bad==0?3:(bad==1?0:2));
        struct full_vdf_snapshot before=snapshot();accepted(bytes,0x81cf61c4);expected_reply(queue[0],1);
        s=snapshot();assert(s.invalid==before.invalid+1 && s.applied==before.applied);
        assert(s.hdmi_consumed==before.hdmi_consumed && s.hdmi_cache==before.hdmi_cache);
        assert(!memcmp(s.body,before.body,20) && !memcmp(s.internal_packet,before.internal_packet,28));drain();
    }
    /* Legal CP bodies outside the finite supported subset reject transport. */
    const unsigned int unsupported[]={32,34,35,36,37,38,39,40,41,42,43,45,46,47,48,49,50,51};
    for (unsigned int i=0;i<sizeof unsupported/sizeof unsupported[0];i++) {
        memcpy(bytes,raw52,52);bytes[unsupported[i]]=2;rejected(bytes,52,0x81cf61c4);
    }
    /* Every envelope field is independently rejected. Opaque +20 is excluded. */
    const unsigned int fields[]={4,8,10,12,16,24,26,28,30};
    for (unsigned int i=0;i<sizeof fields/sizeof fields[0];i++) {
        memcpy(bytes,raw52,52);bytes[fields[i]]^=1;rejected(bytes,52,0x81cf61c4);
    }
    for (unsigned int n=0;n<52;n++) rejected(raw52,n,0x81cf61c4);
    unsigned char longbody[53]={0};memcpy(longbody,raw52,52);rejected(longbody,53,0x81cf61c4);
    rejected(raw52,52,0x81cf61c5);rejected(raw52,52,0x9059000e);
    memcpy(bytes,raw52,52);put32(bytes,0x9059081b);rejected(bytes,52,0x81cf61c4);
    memcpy(bytes,raw52,52);put32(bytes,0x80000000);rejected(bytes,52,0x80000000);
    reset();memcpy(bytes,raw52,52);put32(bytes,0x8abc1234);accepted(bytes,0x8abc1234);
    assert(header(queue[0])->pool==0x8abc1234);expected_reply(queue[0],0);drain();
    memcpy(bytes,raw52,52);put32(bytes,0x81cf61c3);accepted(bytes,0x81cf61c3);
    assert(header(queue[0])->pool==0x81cf61c3);expected_reply(queue[0],0);drain();
    /* Disabling after queue transfer must never disable the free interceptor. */
    accepted(raw52,0x81cf61c4);p=request(raw52,52,0x81cf61c4);
    assert(!full_vdf_dispatch(FULL_VDF_CP,p,&io,0,&rc));drain();assert(!snapshot().live_replies);
    assert(!release(FULL_VDF_CP,p));
    reset();memcpy(bytes,raw52,52);put32(bytes,0);accepted(bytes,0x81cf61c4);
    assert(cp_freed==1 && !alloc_calls && !send_calls && !qn && snapshot().applied==1);
    bytes[32]=0;accepted(bytes,0x81cf61c4);
    assert(cp_freed==2 && !qn && snapshot().invalid==1 && snapshot().applied==1);

    for (unsigned int failure=0;failure<4;failure++) {
        reset();accepted(raw52,0x81cf61c4);drain();s=snapshot();
        memcpy(bytes,raw52,52);bytes[33]=1;p=request(bytes,52,0x81cf61c4);
        if (failure==0) alloc_error=-55;
        if (failure==1) send_error=-66;
        if (failure==2) alloc_null=1;
        if (failure==3) { alloc_error=-55;alloc_dirty=1; }
        assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==(failure==1?-66:(failure==2?-1021:-55)));
        struct full_vdf_snapshot after=snapshot();
        assert(!qn && cp_freed==1 && after.applied==s.applied && after.queued==s.queued);
        assert(after.hdmi_consumed==s.hdmi_consumed && after.hdmi_cache==s.hdmi_cache && !after.faults);
        assert(!memcmp(after.body,s.body,20) && !memcmp(after.internal_packet,s.internal_packet,28));
        assert(ap_freed==(failure==1 || failure==3?2u:1u));assert(!release(FULL_VDF_CP,p));
    }
    /* Temporary reply cleanup failure is retained, logged and gates traffic. */
    reset();send_error=-66;reply_error=-77;p=request(raw52,52,0x81cf61c4);
    assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==-66);
    s=snapshot();assert(s.faults==1 && s.retained_reply==failed_reply && !s.applied && !s.queued && fault_logs==1);
    assert(failed_reply && !ap_freed && !cp_freed);reply_error=0;send_error=0;
    assert(!release(0x81cf61c4,failed_reply));failed_reply=0;assert(!release(FULL_VDF_CP,p));
    rejected(raw52,52,0x81cf61c4);
    /* Request free faults after an irreversible queued transfer cannot cause a
     * false send failure (which would make the AP free the request again). */
    reset();request_error=-88;accepted(raw52,0x81cf61c4);s=snapshot();
    assert(s.faults==1 && s.retained_request==failed_request && !s.request_freed && s.queued==1);
    assert(failed_request && !cp_freed && !ap_freed);request_error=0;
    assert(!release(FULL_VDF_CP,failed_request));failed_request=0;drain();rejected(raw52,52,0x81cf61c4);
    /* Native failure preserves the same lease for a real retry. Wrong-domain
     * frees never reach the allocator. Neither case counts as waiter release. */
    for (unsigned int wrong=0;wrong<2;wrong++) {
        reset();accepted(raw52,0x81cf61c4);p=pop();unsigned int calls=free_calls;
        if (!wrong) reply_error=-77;
        assert(full_vdf_release_reply(wrong?0x80020002:0x81cf61c4,p,release,record,&rc));
        assert(rc==(wrong?-1021:-77));s=snapshot();
        assert(s.faults==1 && s.live_replies==1 && !s.waiter_freed && !s.native_freed);
        assert(!ap_freed && free_calls==calls+(wrong?0u:1u));reply_error=0;failed_reply=0;
        native_free(p);assert(snapshot().waiter_freed==1 && snapshot().live_replies==0);
        assert(fault_logs==1 && free_logs==1);rejected(raw52,52,0x81cf61c4);
    }
    /* Full lease table rejects without consumption; cleanup is real. */
    reset();for (unsigned int i=0;i<8;i++) accepted(raw52,0x81cf61c4);
    p=request(raw52,52,0x81cf61c4);
    assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==-1021);
    assert(cp_freed==8 && ap_freed==1 && snapshot().live_replies==8 && snapshot().applied==8);
    assert(!release(FULL_VDF_CP,p));while (qn) drain();
    for (unsigned int dirty=0;dirty<2;dirty++) {
        reset();
        if (!dirty) for (unsigned int i=0;i<8;i++) accepted(raw52,0x81cf61c4);
        else { alloc_error=-55;alloc_dirty=1; }
        reply_error=-77;p=request(raw52,52,0x81cf61c4);
        assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==(dirty?-55:-1021));
        s=snapshot();assert(s.faults==1 && s.retained_reply==failed_reply && failed_reply);
        assert(s.applied==(dirty?0u:8u) && fault_logs==1);
        reply_error=0;assert(!release(0x81cf61c4,failed_reply));failed_reply=0;
        assert(!release(FULL_VDF_CP,p));while (qn) drain();
    }
    reset();accepted(raw52,0x81cf61c4);duplicate_return=queue[0];p=request(raw52,52,0x81cf61c4);
    assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==-1021);
    assert(snapshot().faults==1 && snapshot().applied==1 && snapshot().live_replies==1);
    assert(cp_freed==1 && !ap_freed && qn==1 && fault_logs==1);duplicate_return=0;
    expected_reply(queue[0],0);drain();assert(!release(FULL_VDF_CP,p));
    reset();p=request(raw52,52,0x81cf61c4);duplicate_return=p;
    assert(full_vdf_dispatch(FULL_VDF_CP,p,&io,1,&rc) && rc==-1021);
    assert(snapshot().faults==1 && !snapshot().applied && !snapshot().live_replies);
    assert(!cp_freed && !ap_freed && !qn && !memcmp(p,raw52,52));duplicate_return=0;
    assert(!release(FULL_VDF_CP,p));
    /* Unknown ordinary OSAL free remains untouched. */
    p=request(raw52,52,0x81cf61c4);rc=123;
    assert(!full_vdf_release_reply(FULL_VDF_CP,p,release,record,&rc) && rc==123);assert(!release(FULL_VDF_CP,p));
    for (unsigned int i=0;i<50;i++) aba_race();
    assert(!failed_reply && !failed_request && !qn);
    evf_subscriptions();
    puts("VDF_PROTOCOL_STATE_OWNERSHIP_ABA_PASS");return 0;
}
