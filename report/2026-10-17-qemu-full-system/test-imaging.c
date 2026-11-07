/* SPDX-License-Identifier: MIT */
/* Independent original-wire fixtures and allocator ownership tests. */
#include "imaging-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct block { unsigned size,source,pool; unsigned char body[64]; };
static void *queued;
static unsigned cp_freed,ap_freed,sent;
static int alloc_error,send_error;
static int release_error;
static void *failed_release;
static struct block *header(void *p) { return (void *)((char *)p - offsetof(struct block,body)); }
static int allocate(unsigned pool,void **out,unsigned size,unsigned count) {
    assert(count==1 && size<=64);
    if (alloc_error) return alloc_error;
    struct block *b=calloc(1,sizeof *b);assert(b);b->size=size;b->pool=pool;*out=b->body;return 0;
}
static int release(unsigned pool,void *p) {
    struct block *b=header(p);assert(b->pool==pool);
    if (pool==FULL_IMAGING_AP && release_error) { failed_release=p;return release_error; }
    if (pool==FULL_IMAGING_CP) cp_freed++;else { assert(pool==FULL_IMAGING_AP);ap_freed++; }
    free(b);return 0;
}
static unsigned source(void *p) { return header(p)->source; }
static unsigned size(void *p) { return header(p)->size; }
static void set_source(void *p,unsigned id) { header(p)->source=id; }
static int send(unsigned id,void *p) {
    assert(id==FULL_IMAGING_AP && source(p)==FULL_IMAGING_CP);sent++;
    if (send_error) return send_error;
    assert(!queued);queued=p;return 0;
}
static struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static const unsigned char set_lock[16]={5,0,0x3d,0x40,0x78,0x56,0x34,0x12,0,0x80,0,0,1,0,0,0};
static const unsigned char response[12]={1,0,0x3d,0x40,0x78,0x56,0x34,0x12,0,0xf0,0,0};
static void *request(const unsigned char *data,unsigned bytes) {
    void *p=0;int old=alloc_error;alloc_error=0;assert(!allocate(FULL_IMAGING_CP,&p,bytes,1));alloc_error=old;
    set_source(p,FULL_IMAGING_AP);memcpy(p,data,bytes);return p;
}
static void drain(void) {
    int rc=99;assert(queued);
    assert(full_imaging_release_reply(FULL_IMAGING_AP,queued,release,0,&rc) && rc==0);
    queued=0;
}
static void reset(unsigned initial) {
    assert(!queued);cp_freed=ap_freed=sent=0;
    alloc_error=send_error=release_error=0;failed_release=0;full_imaging_test_reset(initial);
}
static struct full_imaging_snapshot snapshot(void) {
    struct full_imaging_snapshot s;full_imaging_snapshot(&s);return s;
}
static void accepted(const unsigned char *bytes,unsigned count) {
    int rc=99;assert(full_imaging_dispatch(FULL_IMAGING_CP,request(bytes,count),&io,&rc)==1 && rc==0);
}
int main(void) {
    reset(FULL_IMAGING_POWER_ON_INHIBIT);
    accepted(set_lock,16);assert(cp_freed==1 && ap_freed==0 && sent==1);
    assert(size(queued)==12 && memcmp(queued,response,12)==0);
    assert(snapshot().requested==(FULL_IMAGING_POWER_ON_INHIBIT|0x8000));
    assert(full_imaging_capture_begin()!=0);drain();assert(snapshot().waiter_freed==1);
    accepted(set_lock,16);drain();assert(snapshot().requested==(FULL_IMAGING_POWER_ON_INHIBIT|0x8000));
    unsigned char clear[16];memcpy(clear,set_lock,16);clear[12]=0;
    accepted(clear,16);drain();assert(snapshot().requested==FULL_IMAGING_POWER_ON_INHIBIT);
    assert(full_imaging_capture_begin()!=0); /* AP clear must not fake sensor readiness. */

    unsigned char query[12]={5,0,0x40,0x40,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff};
    const unsigned char inhibited[16]={1,0,0x40,0x40,0xff,0xff,0xff,0xff,1,0xf0,0,0,0,0,0,4};
    accepted(query,12);assert(size(queued)==16 && !memcmp(queued,inhibited,16));drain();
    reset(0);accepted(query,12);unsigned char unlocked[16];memcpy(unlocked,inhibited,16);unlocked[8]=0;unlocked[15]=0;
    assert(!memcmp(queued,unlocked,16));drain();
    unsigned char other[16];memcpy(other,set_lock,16);other[9]=0;other[10]=0x20;
    accepted(other,16);drain();assert(snapshot().requested==0x200000);
    other[12]=0;accepted(other,16);drain();assert(snapshot().effective==0);
    assert(!full_imaging_capture_begin());
    int rc=99;void *p=request(set_lock,16);
    assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-1021 && !queued);
    assert(snapshot().requested==0);release(FULL_IMAGING_CP,p);full_imaging_capture_end();
    accepted(set_lock,16);drain();assert(full_imaging_capture_begin()!=0);

    /* Malformed/unknown requests remain caller-owned and cannot alter state. */
    reset(FULL_IMAGING_POWER_ON_INHIBIT);
    for (unsigned variant=0;variant<9;variant++) {
        unsigned char bad[16];memcpy(bad,set_lock,16);unsigned bytes=16;
        if (variant==0) bytes=7;
        if (variant==1) bytes=15;
        if (variant==2) bad[0]=1;
        if (variant==3) bad[1]=1;
        if (variant==4) bad[2]=0x3e;
        if (variant==5) bad[9]=0;
        if (variant==6) bad[12]=2;
        if (variant==7) bad[15]=1;
        p=request(bad,bytes);if (variant==8) set_source(p,0x80020003);
        rc=99;assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-1021);
        assert(!queued && cp_freed==variant && snapshot().requested==FULL_IMAGING_POWER_ON_INHIBIT);
        release(FULL_IMAGING_CP,p);
    }
    p=request(set_lock,16);rc=99;assert(!full_imaging_dispatch(0x90030001,p,&io,&rc) && rc==99);
    release(FULL_IMAGING_CP,p);
    for (unsigned failure=0;failure<2;failure++) {
        reset(0);p=request(set_lock,16);if (!failure) alloc_error=-55;else send_error=-55;
        rc=99;assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-55);
        assert(!queued && cp_freed==0 && ap_freed==failure && snapshot().requested==0 && snapshot().queued==0);
        release(FULL_IMAGING_CP,p);
    }
    /* A rejected command must not hide a failed temporary-reply release. */
    reset(0);assert(!full_imaging_capture_begin());p=request(set_lock,16);release_error=-77;
    assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-1021);
    assert(failed_release && snapshot().faults==1 && ap_freed==0 && !queued);
    void *orphan=failed_release;release_error=0;release(FULL_IMAGING_AP,orphan);
    release(FULL_IMAGING_CP,p);full_imaging_capture_end();
    p=request(set_lock,16);assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-1021);
    assert(!queued && snapshot().faults==1);release(FULL_IMAGING_CP,p);

    /* Only a successful real native free may count as waiter release. */
    reset(0);accepted(set_lock,16);release_error=-77;rc=99;
    assert(full_imaging_release_reply(FULL_IMAGING_AP,queued,release,0,&rc) && rc==-77);
    assert(snapshot().waiter_freed==0 && snapshot().faults==1 && ap_freed==0);
    release_error=0;drain();assert(snapshot().waiter_freed==1 && ap_freed==1);

    /* 4037 is one-way: selector slots and focus controls change, never an AP
     * status reply. Fail all alloc/send attempts to detect accidental replies. */
    unsigned char unlock[16]={5,0,0x37,0x40,0x0a,0,0,0x80,0x12,0,0,0,0xff,0xff,0xff,0xff};
    reset(FULL_IMAGING_POWER_ON_INHIBIT);
    full_imaging_test_still(0x12,1,123);full_imaging_test_still(0x0f,1,456);
    full_imaging_test_arbitration(0x12,0,0,1,0);
    alloc_error=send_error=-55;accepted(unlock,16);
    struct full_imaging_snapshot s=snapshot();
    assert(!queued && !sent && !ap_freed && cp_freed==1 && s.queued==0);
    assert(s.still_active[0x12]==0 && s.still_token[0x12]==0x8000000a);
    assert(s.still_active[0x0f]==1 && s.still_token[0x0f]==456 && s.focus_trigger[0x0f]==1);
    assert(s.af_selector==0x0f && s.ae_selector==0x0f && s.bw_selector==0x0f && s.af_gate==0);
    assert(s.focus_af==0x0f && s.focus_trigger[0x12]==0 && s.requested==FULL_IMAGING_POWER_ON_INHIBIT);
    const unsigned char notice[24]={2,0,0x31,0x30,0,0,0,0,0,0,0,0,0x12,0,0,0,0,0,0,0,0,0,0,0};
    assert(!memcmp(s.last_focus_message,notice,24));
    unsigned long long controls=s.focus_controls;
    unlock[4]=0x0b;memset(unlock+12,0,4);accepted(unlock,16);s=snapshot();
    assert(s.still_token[0x12]==0x8000000b && s.focus_controls==controls+1 && s.focus_af==0x0f && !sent);

    reset(0);full_imaging_test_still(0x12,1,10);
    full_imaging_test_arbitration(0x12,0,0,0,0);accepted(unlock,16);s=snapshot();
    assert(s.focus_controls==1 && s.af_selector==0x12 && s.focus_af==0x12 && s.af_gate==0);
    assert(!s.still_active[0x12] && !s.focus_trigger[0x12]); /* No false AF-free. */
    reset(0);full_imaging_test_still(0x12,1,10);full_imaging_test_still(0x0f,1,20);
    full_imaging_test_arbitration(0x12,0,0,1,1);accepted(unlock,16);s=snapshot();
    assert(s.focus_controls==1 && s.af_selector==0x12 && s.ae_selector==0 && s.bw_selector==0);
    assert(s.still_active[0x0f] && s.still_token[0x0f]==20);
    reset(FULL_IMAGING_POWER_ON_INHIBIT);unlock[8]=4;
    full_imaging_test_still(4,1,100);full_imaging_test_still(0x12,1,200);
    accepted(unlock,16);s=snapshot();
    assert(!s.still_active[4] && s.still_token[4]==0x8000000b && s.still_active[0x12] && s.still_token[0x12]==200);
    assert(!s.focus_trigger[4] && s.focus_trigger[0x12] && !sent && !queued && cp_freed==1);
    assert(s.last_focus_message[3]==4 && s.requested==FULL_IMAGING_POWER_ON_INHIBIT);
    reset(0);unlock[8]=0x17;p=request(unlock,16);
    assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-1021 && !cp_freed && !sent);
    release(FULL_IMAGING_CP,p);

    const unsigned ordinary[]={3,4,0x0d,0x0e,0x11,0x12,0x15,0x16};
    for (unsigned i=0;i<sizeof ordinary/sizeof ordinary[0];i++) {
        reset(FULL_IMAGING_POWER_ON_INHIBIT);unsigned selector=ordinary[i];unlock[8]=selector;
        full_imaging_test_still(selector,1,99);accepted(unlock,16);s=snapshot();
        assert(!s.still_active[selector] && s.still_token[selector]==0x8000000b);
        assert(s.internal_counter_a==1 && s.internal_counter_b==0x40000001);
        assert(!queued && !sent && cp_freed==1 && s.requested==FULL_IMAGING_POWER_ON_INHIBIT);
    }
    for (unsigned selector=2;selector<=0x14;selector+=0x12) {
        for (unsigned latched=0;latched<2;latched++) {
            reset(0);unlock[8]=selector;full_imaging_test_still(selector,1,99);
            full_imaging_test_latches(latched?7:0,0,0);accepted(unlock,16);s=snapshot();
            assert(s.still_active[selector]==latched);
            assert(s.still_token[selector]==(latched?99:0x8000000b));
            assert(s.control_latch==(latched?7u:0u) && s.focus_controls==1 && !s.focus_trigger[selector]);
            assert(!sent && cp_freed==1);
        }
    }
    for (unsigned flag=0;flag<3;flag++) {
        reset(0);unlock[8]=9;full_imaging_test_still(9,1,99);
        full_imaging_test_latches(0,0,flag);accepted(unlock,16);s=snapshot();
        assert(s.still_active[9] && s.still_token[9]==99);
        assert(s.focus_latch_09==(flag==1?0:flag) && s.focus_controls==(flag==1?2u:1u));
        assert(!queued && !sent && cp_freed==1);
    }
    reset(0);unlock[8]=0x13;full_imaging_test_still(0x13,1,99);accepted(unlock,16);
    assert(!snapshot().still_active[0x13] && snapshot().still_token[0x13]==0x8000000b && !sent);
    reset(0);full_imaging_test_still(0x13,1,99);full_imaging_test_latches(0,1,0);p=request(unlock,16);
    assert(full_imaging_dispatch(FULL_IMAGING_CP,p,&io,&rc) && rc==-1021 && !cp_freed && !sent);
    assert(snapshot().pending_still_13==1 && snapshot().still_active[0x13]);release(FULL_IMAGING_CP,p);
    reset(0);unlock[8]=4;full_imaging_test_still(0x13,1,99);full_imaging_test_latches(0,1,0);
    accepted(unlock,16);assert(snapshot().af_selector==0x13 && snapshot().pending_still_13==0 && !sent);
    puts("IMAGING_PROTOCOL_OWNERSHIP_PASS");return 0;
}
