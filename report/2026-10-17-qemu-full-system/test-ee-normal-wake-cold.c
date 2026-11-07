/* SPDX-License-Identifier: MIT: host fixtures are not native registration. */
#include "ee-normal-wake-cold.h"
#include <assert.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include <stdio.h>
static struct ee_nwc *service;
static void *native_message;
static unsigned source_value, alloc_calls, send_calls, release_calls;
static int alloc_rc, send_rc, wrong_size, wrong_source, synchronous, order;
static struct ee_nwc_snapshot snap(void) {
    struct ee_nwc_snapshot out;
    assert(ee_nwc_snapshot(service,&out)==0);return out;
}
static void unlocked(void) { (void)snap(); }
static int allocate_msg(unsigned dest,void **p,unsigned size,unsigned flags) {
    struct ee_nwc_snapshot handoff, untouched;
    unlocked();assert(dest==EE_NWC_DEST && size==12 && flags==1);++alloc_calls;
    memset(&handoff,0x5a,sizeof handoff);memset(&untouched,0x5a,sizeof untouched);
    assert(ee_nwc_destroy(service,&handoff)==EE_NWC_BUSY);
    assert(!memcmp(&handoff,&untouched,sizeof handoff));
    if (!alloc_rc || alloc_rc==2) { native_message=malloc(12);assert(native_message); }
    *p=native_message;return alloc_rc;
}
static int release_msg(unsigned owner,void *p) {
    (void)owner;(void)p;++release_calls;assert(0);return -1;
}
static void set_source(void *p,unsigned src) { unlocked();assert(p==native_message);source_value=src; }
static unsigned size_msg(void *p) { unlocked();assert(p==native_message);return wrong_size?11:12; }
static unsigned source_msg(void *p) { unlocked();assert(p==native_message);return wrong_source?0:source_value; }
static struct ee_nwc_lease actual_lease(void) {
    struct ee_nwc_lease l=snap().lease;
    l.message=(uintptr_t)native_message;l.source=source_value;l.bytes=12;
    memcpy(l.wire,native_message,12);return l;
}
static void *consume(void *unused) {
    static const unsigned perms[6][3]={{0,1,2},{0,2,1},{1,0,2},{1,2,0},{2,0,1},{2,1,0}};
    struct ee_nwc_snapshot initial=snap();
    struct ee_nwc_lease l=actual_lease();
    struct ee_nwc_receive receive={l,initial.gate.consumer};
    struct ee_nwc_reader reader={getpid(),7,initial.gate.reader,initial.gate.promise,0x20a3,1,1};
    struct ee_nwc_free freed={.lease=l,.owner=EE_NWC_DEST,.rc=0};
    unsigned i;(void)unused;
    for (i=0;i<3;++i) {
        switch(perms[order][i]) {
        case 0:assert(ee_nwc_observe_receive(service,&receive)==0);break;
        case 1:assert(ee_nwc_observe_reader(service,&reader)==0);break;
        default:free(native_message);native_message=NULL;assert(ee_nwc_observe_free(service,&freed)==0);break;
        }
        /* send-return is still absent in the synchronous path. */
        if (synchronous) assert(!snap().retired);
    }
    return NULL;
}
static int send_msg(unsigned dest,void *p) {
    const uint8_t wire[12]={6,0,0xa3,0x20,0,0,0,0,0,0,0,0};
    pthread_t t;
    unlocked();assert(dest==EE_NWC_DEST && p==native_message);++send_calls;
    assert(source_value==EE_NWC_SOURCE && !memcmp(p,wire,12));
    if (synchronous) { assert(!pthread_create(&t,NULL,consume,NULL));assert(!pthread_join(t,NULL)); }
    return send_rc;
}
static const struct full_imaging_io io={allocate_msg,release_msg,set_source,send_msg,size_msg,source_msg,NULL};
static uint8_t rows[128],state[32],adc0[24],adc1[24];
static struct ee_nwc_assets assets;
static struct ee_nwc_initial initial;
static struct ee_adc_sample samples[2];
static struct ee_nwc_gate gate;
static void put32(uint8_t *p,unsigned v) { unsigned i;for(i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i)); }
static void setup(unsigned current0) {
    unsigned i;
    alloc_calls=send_calls=release_calls=0;alloc_rc=send_rc=wrong_size=wrong_source=synchronous=order=0;
    native_message=NULL;source_value=0;memset(rows,0,sizeof(rows));memset(state,0,sizeof(state));
    memset(adc0,0,sizeof(adc0));memset(adc1,0,sizeof(adc1));adc0[0]=150;adc1[22]=150;
    for(i=0;i<2;++i) {
        uint8_t *r=rows+64*i;put32(r+8,i?23:0);r[20]=100;r[24]=200;
        put32(r+36,0x71c9+i);put32(r+40,i?4:current0);r[44]=(uint8_t)i;
    }
    memset(&assets,0,sizeof(assets));assets.pid=getpid();assets.generation=7;
    assets.backup_sha256=EE_NWC_BACKUP_SHA;assets.cp_bank_sha256=EE_NWC_BANK_SHA;
    assets.cp_sha256=EE_NWC_CP_SHA;assets.cp_bank_offset=970752;assets.verified=1;
    assets.keymap_group=1;assets.rows=rows;assets.rows_bytes=128;
    put32(assets.backup_00030162,1);put32(assets.backup_00030162+4,4);assets.config_0092001c[0]=12;
    initial=(struct ee_nwc_initial){getpid(),7,15,15,"model-defined:host-fixture-v1",0,0,state,32};
    samples[0]=(struct ee_adc_sample){adc0,24,100,7,0,1,1,1};
    samples[1]=(struct ee_adc_sample){adc1,24,100,7,1,1,1,1};
    gate=(struct ee_nwc_gate){.pid=getpid(),.generation=7,.consumer=0x100,.promise=0x200,.reader=0x300,
        .registration_event=10,.unlock_event=11,.observer_installed=1,.consumer_registered=1,
        .wait_unlocked=1,.notification_id=0x20a3,.registration_rc=0};
    assert(ee_nwc_create(&service,EE_NWC_PROFILE,getpid(),7,&io)==0);
    assert(snap().constructed && !snap().configured && !snap().object_110c);
}
static void ready(void) {
    assert(ee_nwc_configure(service,&assets,&initial)==0);
    assert(snap().object_10bf==((assets.config_0092001c[0]>>2)&1));
    assert(ee_nwc_arm(service,&gate)==0);
}
static void cleanup(void) {
    struct ee_nwc_snapshot handoff;
    if (snap().pending) assert(ee_nwc_destroy(service,NULL)==EE_NWC_BUSY);
    assert(ee_nwc_destroy(service,&handoff)==0);service=NULL;
    /* Explicit host owner cleanup follows module ownership handoff. */
    free(native_message);native_message=NULL;
    assert(release_calls==0);
}
int main(void) {
    struct ee_nwc_snapshot s;
    struct ee_nwc *out=(struct ee_nwc *)(uintptr_t)1;
    unsigned i;
    assert(ee_nwc_create(&out,NULL,getpid(),7,&io)==EE_NWC_DISABLED && !out);
    assert(ee_nwc_create(&out,"virtual-normal-wake-cold-v2",getpid(),7,&io)==EE_NWC_DISABLED);
    assert(ee_nwc_create(&out,EE_NWC_PROFILE,getpid()+1,7,&io)==EE_NWC_OWNER);
    assert(ee_nwc_create(&out,EE_NWC_PROFILE,getpid(),0,&io)==EE_NWC_GENERATION);
    assert(ee_nwc_create(&out,EE_NWC_PROFILE,getpid(),7,NULL)==EE_NWC_INVALID);
    for(i=0;i<6;++i) {
        setup(3);ready();synchronous=1;order=(int)i;
        assert(ee_nwc_trigger(service,7,samples,100,5)==0);s=snap();
        assert(s.current[0]==3 && s.current[1]==4 && s.selection.decision==EE_NORMAL_SPINAL_OFF);
        assert(s.selection.raw_candidate==0 && s.selection.can_publish==0);
        assert(s.retired && !s.pending && s.send_returned && s.reader_output==1 && s.free_owner==EE_NWC_DEST);
        {
            struct ee_nwc_receive received=s.receive_observed;
            struct ee_nwc_reader reader=s.reader_observed;
            struct ee_nwc_free freed=s.free_observed;
            struct ee_nwc_snapshot after;
            received.lease.generation++;reader.generation++;freed.lease.generation++;
            assert(ee_nwc_observe_receive(service,&received)==EE_NWC_GENERATION);
            assert(ee_nwc_observe_reader(service,&reader)==EE_NWC_GENERATION);
            assert(ee_nwc_observe_free(service,&freed)==EE_NWC_GENERATION);
            after=snap();assert(after.retired);
            assert(after.receive_observed.lease.generation==s.receive_observed.lease.generation);
            assert(after.reader_observed.generation==s.reader_observed.generation);
            assert(after.free_observed.lease.generation==s.free_observed.lease.generation);
        }
        assert(ee_nwc_trigger(service,7,samples,100,5)==EE_NWC_DUPLICATE);
        assert(alloc_calls==1 && send_calls==1);cleanup();
    }
    setup(3);ready();assert(ee_nwc_trigger(service,7,samples,100,5)==0);
    assert(snap().pending && !snap().retired);consume(NULL);assert(snap().retired);cleanup();
    for(i=0;i<2;++i) {
        setup(i?3:1);if(i)assets.config_0092001c[0]=0;ready();
        assert(ee_nwc_trigger(service,7,samples,100,5)==EE_NWC_NO_DELIVERY);
        s=snap();assert(!alloc_calls && !s.selection.raw_candidate_valid && s.first_cold);
        assert(s.selection.decision==(i?EE_TRIGGER_INACTIVE:EE_CONTINUE_EE));cleanup();
    }
    for(i=0;i<4;++i) {
        setup(3);initial.known^=1u<<i;
        assert(ee_nwc_configure(service,&assets,&initial)==EE_NWC_UNKNOWN);
        assert(!snap().configured && !alloc_calls);cleanup();
    }
    setup(3);initial.model_defined=0;assert(ee_nwc_configure(service,&assets,&initial)==EE_NWC_UNKNOWN);cleanup();
    setup(3);assets.generation=8;assert(ee_nwc_configure(service,&assets,&initial)==EE_NWC_GENERATION);cleanup();
    setup(3);assets.backup_sha256="bad";assert(ee_nwc_configure(service,&assets,&initial)==EE_NWC_INVALID);cleanup();
    setup(3);assert(ee_nwc_trigger(service,7,samples,100,5)==EE_NWC_NOT_ARMED);cleanup();
    setup(3);assert(ee_nwc_configure(service,&assets,&initial)==0);gate.consumer_registered=0;
    assert(ee_nwc_arm(service,&gate)==EE_NWC_NOT_ARMED);assert(!alloc_calls);cleanup();
    setup(3);ready();assert(ee_nwc_trigger(service,8,samples,100,5)==EE_NWC_GENERATION);assert(!snap().attempted);cleanup();
    for(i=0;i<8;++i) {
        setup(3);if(i==6)put32(rows+36,0xaaaa);if(i==7)put32(rows+8,24);ready();
        switch(i) {
        case 0:samples[0].known=0;break;
        case 1:samples[0].calibrated=0;break;
        case 2:samples[0].generation=8;break;
        case 3:samples[0].sampled_at=94;break;
        case 4:samples[0].bytes=23;break;
        case 5:samples[0].virtual_input_state=0;break;
        default:break;
        }
        assert(ee_nwc_trigger(service,7,samples,100,5)!=0);assert(!alloc_calls && snap().fault);
        assert(ee_nwc_trigger(service,7,samples,100,5)==EE_NWC_DUPLICATE);cleanup();
    }
    for(i=0;i<5;++i) {
        setup(3);ready();
        if(i<2)alloc_rc=(int)i+1;else if(i==2)wrong_size=1;else if(i==3)wrong_source=1;else send_rc=-8;
        assert(ee_nwc_trigger(service,7,samples,100,5)!=0);s=snap();
        assert(s.fault && !s.retired && !release_calls);
        assert(s.pending==(i!=0));assert(send_calls==(i==4));cleanup();
    }
    for(i=0;i<8;++i) {
        struct ee_nwc_lease l;
        struct ee_nwc_receive r;
        struct ee_nwc_free f;
        struct ee_nwc_reader rd;
        setup(3);ready();assert(ee_nwc_trigger(service,7,samples,100,5)==0);
        l=actual_lease();r=(struct ee_nwc_receive){l,gate.consumer};f=(struct ee_nwc_free){.lease=l,.owner=EE_NWC_DEST,.rc=0};
        rd=(struct ee_nwc_reader){getpid(),7,gate.reader,gate.promise,0x20a3,1,1};
        switch(i) {
        case 0:r.lease.generation=8;assert(ee_nwc_observe_receive(service,&r)==EE_NWC_GENERATION);break;
        case 1:r.lease.message++;assert(ee_nwc_observe_receive(service,&r)==EE_NWC_LEASE);break;
        case 2:r.lease.source++;assert(ee_nwc_observe_receive(service,&r)==EE_NWC_LEASE);break;
        case 3:r.lease.wire[8]=1;assert(ee_nwc_observe_receive(service,&r)==EE_NWC_LEASE);break;
        case 4:r.lease.bytes=11;assert(ee_nwc_observe_receive(service,&r)==EE_NWC_LEASE);break;
        case 5:rd.output=2;assert(ee_nwc_observe_reader(service,&rd)==EE_NWC_READER);break;
        case 6:f.owner++;assert(ee_nwc_observe_free(service,&f)==EE_NWC_FREE);break;
        default:f.rc=-9;assert(ee_nwc_observe_free(service,&f)==EE_NWC_FREE);assert(snap().free_rc==-9);break;
        }
        assert(snap().pending && !snap().retired);cleanup();
    }
    setup(3);ready();{
        int status;pid_t child=fork();assert(child>=0);
        if(!child) _exit(ee_nwc_trigger(service,7,samples,100,5)==EE_NWC_OWNER?0:1);
        assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    }assert(!alloc_calls);cleanup();
    puts("ee-normal-wake-cold: host fixtures passed (no native registration/AP/CP execution)");
    return 0;
}
