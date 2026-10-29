/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-startup-controls-diagnostic.h"
#include <assert.h>
#include <stddef.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
_Static_assert(CP_STARTUP_CONTROLS_REQUEST_MAX>=328,"40c8 must retain all320 body bytes");

/* Mock predecessor/IO evidence tests transport only; no real AP/business state. */
static const unsigned int opcodes[3]={0x4014,0x40c8,0x4057},sizes[3]={24,328,12};
static const unsigned char actual4014[24]={5,0,0x14,0x40,0x27,0,0,0x80,0,0,1,0,1,0,0,0,1,0,0,0,0,0,0,0};
struct packet { unsigned int owner,source,bytes;unsigned char body[CP_STARTUP_CONTROLS_REQUEST_MAX+24]; };
static struct packet *packets[32];
static unsigned char expected[3][CP_STARTUP_CONTROLS_REQUEST_MAX];
static void *request,*queued,*reused;
static unsigned int current,allocations,sends,reserves,unreserves,ready_calls,held,logs;
static _Atomic unsigned int frees;
static int predecessors[6]={1,1,1,1,1,1};
static int reserve_rc,allocate_rc,null_allocate,bad_size,alias,bad_source,bad_copy,error_pointer;
static int send_rc,request_fail,reply_fail,cleanup_fail,inline_free,reuse_free,reentrant_free,async_free;
static int mutate_request,lose_guard,reenter,inspect_reenter,before_send_fault;
static pthread_t worker;
static pthread_mutex_t async_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t async_cond=PTHREAD_COND_INITIALIZER;
static int entered,unblock;
static const struct full_imaging_io io;
static const struct native_cp_startup_controls_diagnostic_guard guard;
static long this_tid(void) { return syscall(SYS_gettid); }
static struct native_cp_startup_controls_diagnostic_snapshot view(void) {
    struct native_cp_startup_controls_diagnostic_snapshot s;native_cp_startup_controls_diagnostic_snapshot(&s);
    assert(s.diagnostic_only && s.virtual_padding);
    assert(!s.business_applied && !s.source_dependencies_closed && !s.published && !s.configured && !s.generation);
    assert(!s.native_cp && !s.ee && !s.frame && !s.capture);
    for(unsigned int i=0;i<3;i++)assert(s.leases[i].opcode==opcodes[i] && s.leases[i].supported && s.leases[i].source_byte1_known==(i!=0));
    return s;
}
static struct packet *packet(void *body) { return (struct packet *)((unsigned char *)body - offsetof(struct packet,body)); }
static void *make_packet(unsigned int owner,unsigned int source,unsigned int bytes) {
    struct packet *p=calloc(1,sizeof *p);assert(p);p->owner=owner;p->source=source;p->bytes=bytes;
    unsigned int i=0;while(i<32 && packets[i])i++;assert(i<32);packets[i]=p;return p->body;
}
static void destroy(void *body) {
    struct packet *p=packet(body);unsigned int i=0;while(i<32 && packets[i]!=p)i++;
    assert(i<32);packets[i]=NULL;free(p);
}
static uint32_t hash(const unsigned char *p,unsigned int bytes) {
    uint32_t value=UINT32_C(2166136261);
    for(unsigned int i=0;i<bytes;i++)value=(value^p[i])*UINT32_C(16777619);
    return value;
}
static void make_request(unsigned int index) {
    current=index;request=make_packet(NATIVE_CP_STARTUP_CONTROLS_SID,FULL_IMAGING_AP,sizes[index]);
    unsigned char *p=request;
    if(!index)memcpy(p,actual4014,24);
    else {
        for(unsigned int i=0;i<sizes[index];i++)p[i]=(unsigned char)(i*37u+index*13u);
        p[0]=5;p[1]=0;p[2]=(unsigned char)opcodes[index];p[3]=(unsigned char)(opcodes[index]>>8);
        p[4]=(unsigned char)(0x27+index*17);p[5]=p[6]=0;p[7]=0x80;
    }
    memcpy(expected[index],p,sizes[index]);
}
static void probe_reentry(void) {
    static struct packet probe={NATIVE_CP_STARTUP_CONTROLS_SID,FULL_IMAGING_AP,0,{5,0}};
    probe.bytes=sizes[current];probe.body[2]=(unsigned char)opcodes[current];probe.body[3]=(unsigned char)(opcodes[current]>>8);
    int result=123;
    assert(native_cp_startup_controls_diagnostic_dispatch(NATIVE_CP_STARTUP_CONTROLS_SID,probe.body,&io,&guard,1,&result)==1);
    assert(result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
}
static unsigned int size_of(void *p) {
    (void)view();if(inspect_reenter) { inspect_reenter=0;probe_reentry(); }
    return packet(p)->bytes;
}
static unsigned int source_of(void *p) { (void)view();return packet(p)->source; }
static void set_source(void *p,unsigned int source) {
    (void)view();packet(p)->source=bad_source?FULL_IMAGING_AP:source;
    if(bad_copy)((unsigned char *)p)[4]^=1;
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    allocations++;(void)view();assert(owner==FULL_IMAGING_AP && bytes==12 && wait==1 && held);
    if(reenter)probe_reentry();
    if(alias) { *out=(unsigned char *)request+(alias==2?(int)sizes[current]-1:alias==3?-11:0);return 0; }
    if(allocate_rc || null_allocate) { *out=NULL;return allocate_rc; }
    *out=make_packet(owner,0,bad_size?(unsigned int)bad_size:12u);
    if(mutate_request)((unsigned char *)request)[sizes[current]-1]^=1;
    if(lose_guard)predecessors[4]=0;
    return error_pointer?-33:0;
}
static void logger(const char *tag,const char *line) {
    (void)view();logs++;
    assert(strstr(tag,"NATIVE_CP_STARTUP_DIAGNOSTIC_")==tag);
    assert(strstr(line,"diagnostic_only=1 virtual_padding=1 business_applied=0 source_dependencies_closed=0 configured=0 published=0 generation=0 native_cp=0 EE=0 frame=0 capture=0"));
    if(reenter)probe_reentry();
    if(before_send_fault && strstr(tag,"_REQUEST ")) {
        before_send_fault=0;int result=123;
        assert(native_cp_startup_controls_diagnostic_release_reply(NATIVE_CP_STARTUP_CONTROLS_SID,request,io.release,logger,&result)==1);
        assert(result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
    }
}
static int release_packet(unsigned int owner,void *p) {
    frees++;(void)view();assert(packet(p)->owner==owner);
    if(reenter)probe_reentry();
    if(reentrant_free && p==queued) {
        reentrant_free=0;int result=123;
        assert(native_cp_startup_controls_diagnostic_release_reply(owner,p,release_packet,logger,&result)==1);
        assert(result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
    }
    if(async_free && p==queued) {
        pthread_mutex_lock(&async_mutex);entered=1;pthread_cond_broadcast(&async_cond);
        while(!unblock)pthread_cond_wait(&async_cond,&async_mutex);
        pthread_mutex_unlock(&async_mutex);
    }
    if(p==request && request_fail) { request_fail--;return -19; }
    if(p!=request && cleanup_fail) { cleanup_fail--;return -23; }
    if(p==queued && reply_fail) { reply_fail--;return -21; }
    if(p==queued && reuse_free) { reused=p;packet(p)->owner=0x81234567u;memset(p,0xa5,12);return 0; }
    destroy(p);return 0;
}
static void *free_in_thread(void *p) {
    int result=123;
    assert(native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,p,release_packet,logger,&result)==1 && !result);
    return NULL;
}
static int send_packet(unsigned int owner,void *p) {
    struct native_cp_startup_controls_diagnostic_snapshot s=view();sends++;
    struct native_cp_startup_controls_diagnostic_lease lease=s.leases[current];
    assert(owner==FULL_IMAGING_AP && packet(p)->owner==owner && packet(p)->source==NATIVE_CP_STARTUP_CONTROLS_SID);
    assert(packet(p)->bytes==12 && p!=request && held && lease.busy && lease.guard_held);
    assert(lease.requests==1 && lease.sender_tid==this_tid());
    assert(lease.source==FULL_IMAGING_AP && lease.request_destination==NATIVE_CP_STARTUP_CONTROLS_SID && lease.destination==FULL_IMAGING_AP);
    assert(lease.request_bytes==sizes[current] && lease.request_fnv1a32==hash(expected[current],sizes[current]));
    assert(!memcmp(lease.request_wire,expected[current],sizes[current]));
    assert(!memcmp(p,(unsigned char[]){1,0,(unsigned char)opcodes[current],(unsigned char)(opcodes[current]>>8)},4));
    assert(!memcmp((unsigned char *)p+4,expected[current]+4,4));
    assert(!memcmp((unsigned char *)p+8,(unsigned char[]){0,0xf0,0,0},4));
    queued=p;if(reenter)probe_reentry();
    if(inline_free) { int result;assert(native_cp_startup_controls_diagnostic_release_reply(owner,p,release_packet,logger,&result)==1 && !result); }
    if(async_free) {
        assert(!pthread_create(&worker,NULL,free_in_thread,p));
        pthread_mutex_lock(&async_mutex);while(!entered)pthread_cond_wait(&async_cond,&async_mutex);pthread_mutex_unlock(&async_mutex);
    }
    return send_rc;
}
static int reserve(void) { (void)view();reserves++;if(reenter)probe_reentry();if(reserve_rc)return reserve_rc;assert(!held);held=1;return 0; }
static void unreserve(void) { (void)view();assert(held);if(reenter)probe_reentry();held=0;unreserves++; }
static int ready(void) {
    (void)view();assert(held);ready_calls++;if(reenter)probe_reentry();
    for(unsigned int i=0;i<6;i++)if(!predecessors[i])return 0;
    return 1;
}
static const struct full_imaging_io io={allocate,release_packet,set_source,send_packet,size_of,source_of,logger};
static const struct native_cp_startup_controls_diagnostic_guard guard={reserve,unreserve,ready};
static int dispatch(const struct native_cp_startup_controls_diagnostic_guard *g) {
    int result=123;
    assert(native_cp_startup_controls_diagnostic_dispatch(NATIVE_CP_STARTUP_CONTROLS_SID,request,&io,g,1,&result)==1);
    return result;
}
static void assert_refused(void) {
    struct native_cp_startup_controls_diagnostic_snapshot s=view();
    assert(!s.requests && !s.busy && !s.guard_held && !held && !sends);
    for(unsigned int i=0;i<3;i++)assert(!s.leases[i].retained_request && !s.leases[i].live_reply && !s.leases[i].ap_consumed);
}
static void consume(void) {
    int result=123;assert(native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && !result);
}
static void check_clean(unsigned int index) {
    struct native_cp_startup_controls_diagnostic_lease s=view().leases[index];
    assert(s.requests==1 && s.queued && s.request_freed && s.reply_freed && s.clean_completion && s.ap_consumed && !s.faults);
    assert(!s.busy && !s.guard_held && !s.retained_request && !s.live_reply && !s.retained_cleanup);
    assert(s.waiter_tid==s.sender_tid && s.sender_tid==this_tid());
    assert(s.reply_free_destination==FULL_IMAGING_AP && s.reply_free_source==NATIVE_CP_STARTUP_CONTROLS_SID && s.reply_free_bytes==12);
    assert(!memcmp(s.freed_reply_wire,s.reply_wire,12) && !memcmp(s.request_wire,expected[index],sizes[index]));
    assert(s.request_fnv1a32==hash(expected[index],sizes[index]));
}
static void fork_test(void) {
    native_cp_startup_controls_diagnostic_test_hold_lock();pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);struct native_cp_startup_controls_diagnostic_snapshot s;native_cp_startup_controls_diagnostic_snapshot(&s);
        assert(s.faults && s.owner_pid!=getpid() && s.diagnostic_only && !s.native_cp && !s.ee && !s.frame && !s.capture);
        assert(native_cp_startup_controls_diagnostic_owner_init()==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);int result=123;
        assert(native_cp_startup_controls_diagnostic_dispatch(NATIVE_CP_STARTUP_CONTROLS_SID,queued,&io,&guard,1,&result)==1 && result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
        assert(native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
        _exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    native_cp_startup_controls_diagnostic_test_drop_lock();
}
int main(int argc,char **argv) {
    assert(argc==3);assert(!strcmp(FULL_CP_STARTUP_DIAGNOSTIC_PROFILE,"diagnostic-cp-startup-controls-v1"));
    unsigned int index=(unsigned int)strtoul(argv[1],NULL,10);assert(index<3);const char *test=argv[2];
    make_request(index);
    if(strcmp(test,"preinit"))assert(!native_cp_startup_controls_diagnostic_owner_init());
    if(!strcmp(test,"sequence") || !strcmp(test,"sequence-inline") || !strcmp(test,"sequence-reverse")) {
        destroy(request);inline_free=!strcmp(test,"sequence-inline");
        const unsigned int order[3]={2,0,1};
        for(unsigned int n=0;n<3;n++) {
            unsigned int which=!strcmp(test,"sequence-reverse")?order[n]:n;make_request(which);assert(!dispatch(&guard));
            if(!inline_free) {
                assert(!view().leases[which].ap_consumed);
                void *saved=request;unsigned int next=(which+1)%3;make_request(next);
                unsigned int before=allocations;assert(dispatch(&guard)==CP_STARTUP_CONTROLS_SOURCE_BLOCKED && allocations==before);
                destroy(request);request=saved;current=which;consume();
            }
            check_clean(which);assert(view().requests==n+1 && view().completed==n+1);
        }
        struct native_cp_startup_controls_diagnostic_snapshot saved=view();
        assert(saved.requests==3 && saved.completed==3 && !saved.faults && allocations==3 && sends==3 && ready_calls==6);
        assert(saved.leases[0].cookie!=saved.leases[1].cookie && saved.leases[1].cookie!=saved.leases[2].cookie);
        for(unsigned int i=0;i<3;i++) {
            make_request(i);assert(dispatch(&guard)==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);destroy(request);check_clean(i);
        }
        assert(view().requests==3 && allocations==3 && reserves==3);goto done;
    }
    if(!strcmp(test,"opaque")) {
        unsigned char *p=request;p[1]=0xff;p[4]^=0x81;p[sizes[index]-1]=0xf6;memcpy(expected[index],p,sizes[index]);
    }
    if(!strcmp(test,"default-off") || !strcmp(test,"enabled-two") || !strcmp(test,"unknown") || !strcmp(test,"wrong-type") || !strcmp(test,"other-destination") || !strcmp(test,"short-header")) {
        if(!strcmp(test,"unknown"))((unsigned char *)request)[2]=0x13;
        if(!strcmp(test,"wrong-type"))((unsigned char *)request)[0]=1;
        if(!strcmp(test,"short-header"))packet(request)->bytes=3;
        int result=123,enabled=!strcmp(test,"default-off")?0:!strcmp(test,"enabled-two")?2:1;
        assert(!native_cp_startup_controls_diagnostic_dispatch(!strcmp(test,"other-destination")?FULL_IMAGING_CP:NATIVE_CP_STARTUP_CONTROLS_SID,request,&io,&guard,enabled,&result) && result==123);
        assert_refused();assert(!allocations && !reserves && !frees && !logs);goto done;
    }
    if(!strcmp(test,"all-bad-lengths")) {
        for(unsigned int bytes=0;bytes<=CP_STARTUP_CONTROLS_REQUEST_MAX+1;bytes++)if(bytes!=sizes[index]) {
            packet(request)->bytes=bytes;int result=123;
            assert(native_cp_startup_controls_diagnostic_dispatch(NATIVE_CP_STARTUP_CONTROLS_SID,request,&io,&guard,1,&result)==(bytes>=4));
            assert(result==(bytes>=4?CP_STARTUP_CONTROLS_SOURCE_BLOCKED:123));
        }
        assert_refused();assert(!allocations && !reserves);goto done;
    }
    if(!strcmp(test,"missing-io")) {
        for(unsigned int n=0;n<7;n++) {
            struct full_imaging_io partial=io;
            switch(n) { case 0:partial.allocate=NULL;break;case 1:partial.release=NULL;break;case 2:partial.set_source=NULL;break;
                case 3:partial.send=NULL;break;case 4:partial.size=NULL;break;case 5:partial.source=NULL;break;default:partial.record=NULL; }
            int result=123;assert(native_cp_startup_controls_diagnostic_dispatch(NATIVE_CP_STARTUP_CONTROLS_SID,request,&partial,&guard,1,&result)==(n!=4));
            assert_refused();assert(!allocations && !reserves);
        }
        goto done;
    }
    if(!strcmp(test,"missing-guard")) {
        assert(dispatch(NULL)==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
        for(unsigned int n=0;n<3;n++) {
            struct native_cp_startup_controls_diagnostic_guard partial=guard;
            if(!n)partial.reserve=NULL;else if(n==1)partial.release=NULL;else partial.predecessor_ready=NULL;
            assert(dispatch(&partial)==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
        }
        assert_refused();assert(!allocations && !reserves);goto done;
    }
    if(!strcmp(test,"no-predecessors")) {
        for(unsigned int n=0;n<6;n++) { predecessors[n]=0;assert(dispatch(&guard)==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);assert_refused();predecessors[n]=1; }
        assert(!allocations && reserves==6 && unreserves==6);goto done;
    }
    if(!strcmp(test,"preinit") || !strcmp(test,"wrong-source") || !strcmp(test,"reserve-refused")) {
        if(!strcmp(test,"wrong-source"))packet(request)->source=0x80020003u;
        if(!strcmp(test,"reserve-refused"))reserve_rc=-14;
        assert(dispatch(&guard));assert_refused();assert(!allocations);goto done;
    }
    if(!strcmp(test,"allocfail") || !strcmp(test,"alloc-retry"))allocate_rc=-16;
    if(!strcmp(test,"null-allocation"))null_allocate=1;
    if(!strcmp(test,"short-allocation"))bad_size=11;
    if(!strcmp(test,"long-allocation"))bad_size=13;
    if(!strcmp(test,"alias"))alias=1;
    if(!strcmp(test,"overlap"))alias=2;
    if(!strcmp(test,"overlap-before"))alias=3;
    if(!strcmp(test,"bad-reply-source"))bad_source=1;
    if(!strcmp(test,"bad-reply-copy"))bad_copy=1;
    if(!strcmp(test,"allocation-error-pointer"))error_pointer=1;
    if(!strcmp(test,"lost-guard"))lose_guard=1;
    if(!strcmp(test,"mutated-request"))mutate_request=1;
    if(!strcmp(test,"cleanupfail")) { bad_size=11;cleanup_fail=1; }
    if(allocate_rc || null_allocate || bad_size || alias || bad_source || bad_copy || error_pointer || lose_guard || mutate_request) {
        assert(dispatch(&guard));assert_refused();struct native_cp_startup_controls_diagnostic_lease s=view().leases[index];
        assert(s.faults==(allocate_rc?0u:1u) && allocations==1 && unreserves==1);
        assert(s.request_bytes==sizes[index] && !memcmp(s.request_wire,expected[index],sizes[index]) && s.request_fnv1a32==hash(expected[index],sizes[index]));
        if(!strcmp(test,"cleanupfail")) {
            assert(s.retained_cleanup && s.reply_free_rc==-23);int result;
            assert(native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,s.retained_cleanup,release_packet,logger,&result)==1 && !result);
            assert(view().leases[index].faults && view().leases[index].reply_free_rc==-23);
        }
        if(strcmp(test,"alloc-retry"))goto done;
        allocate_rc=0;assert(!dispatch(&guard));consume();check_clean(index);assert(view().leases[index].allocate_rc==-16);goto done;
    }
    if(!strcmp(test,"sendfail") || !strcmp(test,"send-cleanupfail") || !strcmp(test,"async-inflight"))send_rc=-17;
    if(!strcmp(test,"send-cleanupfail") || !strcmp(test,"replyfail"))reply_fail=1;
    if(!strcmp(test,"requestfail"))request_fail=1;
    if(!strcmp(test,"inline-free") || !strcmp(test,"fast-free-reuse"))inline_free=1;
    if(!strcmp(test,"fast-free-reuse"))reuse_free=1;
    if(!strcmp(test,"reentrant"))reenter=1;
    if(!strcmp(test,"inspect-reentrant"))inspect_reenter=1;
    if(!strcmp(test,"reentrant-free"))reentrant_free=1;
    if(!strcmp(test,"async-inflight"))async_free=1;
    if(!strcmp(test,"before-send-fault"))before_send_fault=1;
    assert(!dispatch(&guard));struct native_cp_startup_controls_diagnostic_lease s=view().leases[index];
    assert(s.requests==1 && s.sender_tid==this_tid() && !held && unreserves==1);
    if(!strcmp(test,"before-send-fault")) { assert(s.faults && !sends && s.retained_request && !s.live_reply);goto done; }
    assert(sends==1);
    if(async_free) {
        assert(s.live_reply && !s.reply_freed && s.faults && s.send_rc==-17);int result=123;unsigned int before=frees;
        assert(native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
        assert(frees==before);pthread_mutex_lock(&async_mutex);unblock=1;pthread_cond_broadcast(&async_cond);pthread_mutex_unlock(&async_mutex);
        assert(!pthread_join(worker,NULL));s=view().leases[index];assert(s.reply_freed && s.faults && !s.ap_consumed);goto done;
    }
    if(send_rc) {
        assert(s.faults && s.retained_request && !s.request_freed && !s.queued && s.send_rc==-17);
        if(!strcmp(test,"send-cleanupfail")) { assert(s.live_reply && s.reply_free_rc==-21);consume();assert(view().leases[index].reply_free_rc==-21); }
        else assert(!s.live_reply);
        goto done;
    }
    if(!strcmp(test,"fork-lock"))fork_test();
    if(!inline_free) {
        if(!strcmp(test,"wrong-waiter") || !strcmp(test,"cross-fault")) {
            assert(!pthread_create(&worker,NULL,free_in_thread,queued));assert(!pthread_join(worker,NULL));
        } else {
            if(!strcmp(test,"foreign")) {
                void *other=make_packet(FULL_IMAGING_AP,0x90040016u,12);int result=123;
                assert(!native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,other,release_packet,logger,&result) && result==123);destroy(other);
            }
            if(!strcmp(test,"wrong-owner")) {
                int result=123;unsigned int before=frees;
                assert(native_cp_startup_controls_diagnostic_release_reply(0x80020003u,queued,release_packet,logger,&result)==1 && result==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
                assert(frees==before && view().leases[index].live_reply);
            }
            if(!strcmp(test,"altered-wire"))((unsigned char *)queued)[4]^=1;
            if(!strcmp(test,"altered-source"))packet(queued)->source=FULL_IMAGING_AP;
            if(!strcmp(test,"altered-size"))packet(queued)->bytes=11;
            if(reply_fail) {
                int result=123;assert(native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==-21);
                assert(view().leases[index].live_reply && view().leases[index].faults);
            }
            consume();
        }
    }
    s=view().leases[index];assert(s.reply_freed && !s.live_reply);
    if(!strcmp(test,"requestfail")) {
        assert(s.retained_request && s.request_free_rc==-19 && s.faults);int result=123;
        assert(native_cp_startup_controls_diagnostic_release_reply(NATIVE_CP_STARTUP_CONTROLS_SID,s.retained_request,release_packet,logger,&result)==1 && !result);
        assert(view().leases[index].request_free_rc==-19);
    }
    int expected_fault=!strcmp(test,"wrong-waiter") || !strcmp(test,"cross-fault") || !strcmp(test,"wrong-owner") || !strcmp(test,"replyfail") ||
        !strcmp(test,"requestfail") || !strcmp(test,"reentrant-free") || !strcmp(test,"altered-wire") || !strcmp(test,"altered-source") || !strcmp(test,"altered-size");
    s=view().leases[index];assert(s.faults==(unsigned int)expected_fault && s.ap_consumed==(unsigned int)!expected_fault);
    if(!expected_fault)check_clean(index);
    if(!strcmp(test,"double-free")) {
        int result=123;unsigned int before=frees;
        assert(!native_cp_startup_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result) && result==123 && frees==before);
    }
    if(reused)assert(!memcmp(reused,(unsigned char[]){0xa5,0xa5,0xa5,0xa5},4));
    if(!strcmp(test,"cross-fault")) {
        make_request((index+1)%3);unsigned int before=allocations;assert(dispatch(&guard)==CP_STARTUP_CONTROLS_SOURCE_BLOCKED && allocations==before);
        assert(view().leases[index].faults && !view().leases[current].requests);
    }
    assert(native_cp_startup_controls_diagnostic_owner_init()==CP_STARTUP_CONTROLS_SOURCE_BLOCKED);
done:
    for(unsigned int i=0;i<32;i++)if(packets[i])free(packets[i]);
    puts("PASS: finite startup diagnostic transport; business/CP/EE/frame/capture remain0");return 0;
}
