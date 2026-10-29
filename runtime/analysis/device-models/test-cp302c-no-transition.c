/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp302c-no-transition.h"
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

#define AP 0x80020002u
#define PRIOR_AP 0x810261c7u
/* Host-unit-only transport and all13-ready fixture. It does NOT execute the
 * original CP, the real AP waiter, or the production all13 audio backend. */
struct packet { unsigned int owner,source,bytes;unsigned char body[24]; };
static struct packet *packets[32];
static void *request,*queued_reply,*reused;
static unsigned int size_calls,allocations,sends,reserves,unreserves,reserve_failures,ready_calls,guard_held;
static _Atomic unsigned int releases;
static int ready=1,reserve_rc,allocation_rc,short_allocation,alias_allocation,bad_reply_source;
static int send_rc,fail_request_free,fail_reply_free,inline_free,reuse_free,reentrant_free,async_free;
static int log_request,log_reply,log_admission,log_commit,log_free,diagnostic;
static int input_during_allocate,input_before_publication;
static unsigned char expected_request[24];
static pthread_t free_thread;
static pthread_mutex_t async_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t async_cond=PTHREAD_COND_INITIALIZER;
static int entered,unblock;
static long this_tid(void) { return syscall(SYS_gettid); }
static unsigned int command(const unsigned char *p) { return p[2]|(unsigned int)p[3]<<8; }
static void put32(unsigned char *p,unsigned int v) { for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(i*8)); }
static struct native_cp302c_snapshot view(void) {
    struct native_cp302c_snapshot s;native_cp302c_snapshot(&s);
    assert(!s.mode_transition && !s.module_complete && !s.module_effects && !s.capture);
    if(s.diagnostic) {
        assert(!s.history_valid && !s.current_known && !s.current && !s.no_transition);
        assert(!s.observer_a && !s.observer_b && !s.executor_active && !s.executor_last_event);
    }
    return s;
}
static struct packet *packet(void *p) { return (struct packet *)((unsigned char *)p - offsetof(struct packet,body)); }
static void *make_packet(unsigned int owner,unsigned int source,unsigned int bytes,unsigned int op) {
    struct packet *p=calloc(1,sizeof *p);assert(p);p->owner=owner;p->source=source;p->bytes=bytes;
    p->body[2]=(unsigned char)op;p->body[3]=(unsigned char)(op>>8);
    unsigned int i=0;while(i<32 && packets[i])i++;assert(i<32);packets[i]=p;return p->body;
}
static void destroy(void *body) {
    struct packet *p=packet(body);unsigned int i=0;while(i<32 && packets[i]!=p)i++;
    assert(i<32);packets[i]=NULL;free(p);
}
static unsigned int size_of(void *p) { size_calls++;(void)view();return packet(p)->bytes; }
static unsigned int source_of(void *p) { (void)view();return packet(p)->source; }
static void set_source(void *p,unsigned int source) { (void)view();packet(p)->source=bad_reply_source?AP:source; }
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    allocations++;assert(bytes==12 && wait==1);(void)view();
    if(input_during_allocate) {
        unsigned char wire[12]={5,0,0xb8,0x40};
        assert(!native_cp302c_observe_input(NATIVE_CP302C_SID,wire,AP,sizeof wire,"during-allocation"));
    }
    if(alias_allocation) { *out=request;return 0; }
    if(allocation_rc) { *out=NULL;return allocation_rc; }
    *out=make_packet(owner,0,short_allocation?11u:12u,0);return 0;
}
static void logger(const char *tag,const char *line) {
    (void)view();assert(strstr(tag,diagnostic?"NATIVE_CP302C_DIAGNOSTIC_":"NATIVE_CP302C_NOCONVERT_"));
    assert(strstr(line,"mode_transition=0") && strstr(line,"capture=0"));
    if(diagnostic) {
        assert(strstr(line,"diagnostic_only=1") && strstr(line,"history_verified=0") && strstr(line,"current_known=0"));
        assert(strstr(line,"original_CP_executed=0") && strstr(line,"no_transition=0") && strstr(line,"frame=0"));
        assert(strstr(line,"module_complete=0") && strstr(line,"module_effects=0"));
        assert(strstr(line,"no_conversion_verified=0") && strstr(line,"native_verified=0"));
        assert(!strstr(line,"query3041_can_start") && !strstr(line," current=0") && !strstr(line,"source_history_valid=1"));
        assert(!strstr(tag,"NOCONVERT") && !strstr(line,"no_conversion_only=1"));
        if(strstr(tag,"_TRANSPORT_ADMISSION ")) { log_admission++;assert(strstr(line,"transport_only=1")); }
        if(strstr(tag,"_TRANSPORT_COMMIT ")) { log_commit++;assert(strstr(line,"transport_only=1")); }
        if(input_before_publication && strstr(tag,"_REQUEST ")) {
            unsigned char wire[12]={5,0,0x39,0x41};
            assert(!native_cp302c_observe_input(NATIVE_CP302C_SID,wire,AP,sizeof wire,"before-publication"));
        }
    }
    if(strstr(tag,"_REQUEST ")) { log_request++;assert(strstr(line,"bytes=24 wire=")); }
    if(!diagnostic && strstr(tag,"_ADMISSION ")) { log_admission++;assert(strstr(line,"query3041_can_start=0")); }
    if(strstr(tag,"_REPLY_QUEUED ")) { log_reply++;assert(strstr(line,"bytes=12 wire=01002c30")); }
    if(!diagnostic && strstr(tag,"_COMMIT "))log_commit++;
    if(strstr(tag,"_REPLY_FREE ")) { log_free++;assert(strstr(line,"sender_tid=") && strstr(line,"waiter_tid=")); }
}
static int release_packet(unsigned int owner,void *body) {
    releases++;assert(packet(body)->owner==owner);(void)view();
    if(reentrant_free && body==queued_reply) {
        reentrant_free=0;int rc=0;
        assert(native_cp302c_release_reply(owner,body,release_packet,logger,&rc)==1 && rc==-1021);
    }
    if(async_free && body==queued_reply) {
        pthread_mutex_lock(&async_mutex);entered=1;pthread_cond_broadcast(&async_cond);
        while(!unblock)pthread_cond_wait(&async_cond,&async_mutex);
        pthread_mutex_unlock(&async_mutex);
    }
    if(body==request && fail_request_free) { fail_request_free--;return -19; }
    if(body==queued_reply && fail_reply_free) { fail_reply_free--;return -21; }
    if(body==queued_reply && reuse_free) {
        reused=body;packet(body)->owner=0x81234567u;memset(body,0xa5,12);return 0;
    }
    destroy(body);return 0;
}
static void *free_in_thread(void *body) {
    int rc=123;assert(native_cp302c_release_reply(AP,body,release_packet,logger,&rc)==1 && !rc);return NULL;
}
static int send_packet(unsigned int owner,void *body) {
    assert(packet(body)->owner==owner && packet(body)->source==NATIVE_CP302C_SID);
    if(command(body)==0x3007)return 0;
    sends++;assert(owner==AP && packet(body)->bytes==12);queued_reply=body;
    assert(!memcmp(body,(unsigned char[]){1,0,0x2c,0x30},4));
    assert(!memcmp((unsigned char *)body+4,expected_request+4,4));
    assert(!memcmp((unsigned char *)body+8,(unsigned char[]){0,0xf0,0,0},4));
    if(inline_free) { int rc;assert(native_cp302c_release_reply(owner,body,release_packet,logger,&rc)==1 && !rc); }
    if(async_free) {
        assert(!pthread_create(&free_thread,NULL,free_in_thread,body));
        pthread_mutex_lock(&async_mutex);while(!entered)pthread_cond_wait(&async_cond,&async_mutex);pthread_mutex_unlock(&async_mutex);
    }
    return send_rc;
}
static int reserve(void) { (void)view();reserves++;if(reserve_rc){reserve_failures++;return reserve_rc;}assert(!guard_held);guard_held=1;return 0; }
static void unreserve(void) { (void)view();assert(guard_held);guard_held=0;unreserves++; }
static int predecessor_ready(void) { (void)view();assert(guard_held);ready_calls++;return ready; }
static const struct full_imaging_io io={allocate,release_packet,set_source,send_packet,size_of,source_of,logger};
static const struct native_cp302c_guard guard={reserve,unreserve,predecessor_ready};
static void initialize(void) {
    assert(!(diagnostic?native_cp302c_diagnostic_owner_init():native_cp302c_owner_init()));
    struct native_cp302c_snapshot s=view();
    assert(s.initialized && !s.current && s.history_seq==1 && s.diagnostic==(unsigned int)diagnostic);
    assert(!s.observer_a && !s.observer_b && s.virtual_padding && !s.source_byte1_known);
    if(!diagnostic)assert(s.history_valid && s.current_known && s.executor_active==1 && s.executor_last_event==0xf00);
    else {
        assert(!s.diagnostic_inputs && !s.diagnostic_transport);
        assert(native_cp302c_owner_init() && native_cp302c_diagnostic_owner_init());
    }
    assert(s.owner_pid==getpid() && !s.requests && !s.faults);
}
static void make_request(int opaque) {
    request=make_packet(NATIVE_CP302C_SID,AP,24,0x302c);put32((unsigned char *)request+4,0x80000027u);
    if(opaque) {
        ((unsigned char *)request)[1]=0xd1;put32((unsigned char *)request+4,0xdeadbee1u);
        for(unsigned int i=8;i<24;i++)((unsigned char *)request)[i]=(unsigned char)(i+0x70);
    }
    memcpy(expected_request,request,24);
}
static int dispatch(const struct native_cp302c_guard *g,int enabled) {
    int rc=321;assert(native_cp302c_dispatch(NATIVE_CP302C_SID,request,&io,g,enabled,&rc)==1);return rc;
}
/* Feed full wire from an actually queued and freed HOST fixture allocation.
 * Distorted cases deliberately fail evidence; none is a live-camera claim. */
static void prior(const char *distort) {
    unsigned long long before=view().history_seq;
    void *p=make_packet(NATIVE_CP302C_SID,PRIOR_AP,24,0x3007);
    static const unsigned char actual[24]={0,7,7,0x30,0xc1,0xff,0xff,0xff,0x80,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
    memcpy(p,actual,sizeof actual);
    assert(!native_cp302c_observe_input(NATIVE_CP302C_SID,p,PRIOR_AP,24,"host-unit-3007"));
    struct native_cp302c_snapshot s=view();assert(s.predecessor_seen && !s.predecessor_completed && s.central_busy);
    void *reply=make_packet(PRIOR_AP,NATIVE_CP302C_SID,12,0x3007);
    ((unsigned char *)reply)[0]=1;((unsigned char *)reply)[1]=0x76;
    put32((unsigned char *)reply+4,0xffffffc1u);put32((unsigned char *)reply+8,0xf000);
    unsigned int source=packet(reply)->source,owner=packet(reply)->owner;
    if(!strcmp(distort,"cookie"))((unsigned char *)reply)[4]^=1;
    if(!strcmp(distort,"source"))source=AP;
    if(!strcmp(distort,"owner"))owner=AP;
    if(!strcmp(distort,"type"))((unsigned char *)reply)[0]=2;
    if(!strcmp(distort,"result"))((unsigned char *)reply)[8]++;
    unsigned char wire[12];memcpy(wire,reply,12);int queued=send_packet(PRIOR_AP,reply);
    assert(!release_packet(NATIVE_CP302C_SID,p));int freed=release_packet(PRIOR_AP,reply);
    if(!strcmp(distort,"queue"))queued=-7;
    if(!strcmp(distort,"free"))freed=-8;
    if(!strcmp(distort,"command"))wire[2]++;
    long sender=this_tid(),freeing=this_tid();if(!strcmp(distort,"tid"))sender++;
    if(!strcmp(distort,"freeing-tid"))freeing++;
    int rc=native_cp302c_observe_3007_reply_freed(source,owner,wire,!strcmp(distort,"short")?11u:12u,queued,freed,sender,freeing);
    s=view();
    if(*distort)assert(rc && !s.history_valid && !s.current_known && s.faults && !s.predecessor_completed);
    else {
        assert(!rc && s.predecessor_completed && !s.central_busy && !s.current);
        assert(s.history_seq==before+(diagnostic?1u:3u));
        assert(s.current_known==(unsigned int)!diagnostic);
        assert(!memcmp(s.predecessor_wire,actual,24) && s.predecessor_cookie==0xffffffc1u);
        assert(s.predecessor_source==PRIOR_AP && s.predecessor_sender_tid==this_tid());
    }
}
static void *prior_thread(void *distort) { prior(distort);return NULL; }
static void run_prior(const char *distort) {
    pthread_t thread;assert(!pthread_create(&thread,NULL,prior_thread,(void *)distort));assert(!pthread_join(thread,NULL));
    assert(view().predecessor_sender_tid!=this_tid());
}
static void assert_no_claim(void) {
    struct native_cp302c_snapshot s=view();assert(!s.requests && !s.queued && !s.no_transition && !s.ap_consumed);
    assert(!s.retained_request && !s.live_reply && !guard_held && !s.busy);
}
static void consume(void) {
    int rc=123;assert(native_cp302c_release_reply(AP,queued_reply,release_packet,logger,&rc)==1 && !rc);
}
static void assert_success(void) {
    struct native_cp302c_snapshot s=view();
    assert(s.requests==1 && s.generation==1 && s.queued==1 && s.request_freed==1 && s.reply_freed==1);
    assert(s.clean_completion && s.ap_consumed && !s.faults && !s.busy && !s.guard_held);
    assert(s.no_transition==(unsigned int)!diagnostic && s.diagnostic_transport==(unsigned int)diagnostic);
    assert(!s.current && !s.central_busy && s.predecessor_completed);
    if(!diagnostic) {
        assert(s.history_valid && s.current_known);
        assert(!s.observer_a && !s.observer_b && s.executor_active==1 && s.executor_last_event==0xf00);
    }
    assert(s.virtual_padding && !s.source_byte1_known && s.sender_tid==this_tid() && s.waiter_tid==this_tid());
    assert(!memcmp(s.request_wire,expected_request,24) && !memcmp(s.reply_wire+4,expected_request+4,4));
    assert(!s.retained_request && !s.live_reply && !s.retained_cleanup);
    assert(log_request==1 && log_reply==1 && log_admission==1 && log_commit==1 && log_free==1);
    assert(allocations==1 && sends==1 && reserves==unreserves+reserve_failures && !guard_held);
    void *next=make_packet(NATIVE_CP302C_SID,AP,24,0x302c);memcpy(next,expected_request,24);int rc=99;
    assert(native_cp302c_dispatch(NATIVE_CP302C_SID,next,&io,&guard,1,&rc)==1 && rc==-1021);
    assert(view().requests==1 && !view().faults);destroy(next);
}
static void audit_unknown(void) {
    unsigned char parameter[12]={5,0xd1,0xb8,0x40,1,2,3,4,5,6,7,8};
    unsigned char large[184],copy[184],mode[24]={0,0,6,0x30};
    for(unsigned int i=0;i<sizeof large;i++)large[i]=(unsigned char)(i+0x57);
    large[0]=5;large[2]=0x39;large[3]=0x41;memcpy(copy,large,sizeof copy);
    struct native_cp302c_snapshot before=view();unsigned int calls=size_calls;
    assert(!native_cp302c_parameter_prefix_supported(0x40b8) && !native_cp302c_parameter_prefix_supported(0x4139));
    int expected_rc=before.faults?-1021:0;
    assert(native_cp302c_observe_input(NATIVE_CP302C_SID,parameter,AP,sizeof parameter,"unknown-40b8")==expected_rc);
    assert(native_cp302c_observe_input(NATIVE_CP302C_SID,large,PRIOR_AP,sizeof large,"full-184-byte-4139")==expected_rc);
    assert(native_cp302c_observe_input(NATIVE_CP302C_SID,mode,AP,sizeof mode,"unmodeled-mode-input")==expected_rc);
    struct native_cp302c_snapshot after=view();
    assert(!memcmp(large,copy,sizeof copy) && size_calls==calls);
    before.history_seq+=3;before.diagnostic_inputs+=3;assert(!memcmp(&before,&after,sizeof before));
}
int main(int argc,char **argv) {
    assert(argc==2);const char *test=argv[1];
    diagnostic=!strncmp(test,"diag-",5);if(diagnostic)test+=5;
    if(!strcmp(test,"default-off")) {
        if(diagnostic)initialize();
        make_request(0);int rc=99;
        assert(!native_cp302c_dispatch(NATIVE_CP302C_SID,request,&io,&guard,0,&rc) && rc==99 && !size_calls);
        assert(!native_cp302c_dispatch(0x90000000u,request,&io,&guard,1,&rc) && rc==99 && !size_calls);
        assert_no_claim();goto done;
    }
    if(!strcmp(test,"preinit")) {
        unsigned char wire[4]={0,0,6,0x30};
        assert(native_cp302c_observe_input(NATIVE_CP302C_SID,wire,AP,4,"before-constructor"));
        assert(native_cp302c_owner_init() && native_cp302c_diagnostic_owner_init() && view().faults && !view().current_known);goto done;
    }
    initialize();make_request(!strcmp(test,"opaque"));
    if(diagnostic) {
        assert(!strcmp(FULL_CP302C_DIAGNOSTIC_PROFILE,"diagnostic-cp302c-reply-only-v1"));
        audit_unknown();
        if(!strcmp(test,"no-3007")) {
            assert(dispatch(&guard,1)==-1021);assert_no_claim();assert(!allocations && !reserves);goto done;
        }
        if(!strcmp(test,"early-free")) {
            unsigned char wire[12]={1,0,7,0x30,0xc1,0xff,0xff,0xff,0,0xf0,0,0};
            assert(native_cp302c_observe_3007_reply_freed(NATIVE_CP302C_SID,PRIOR_AP,wire,12,0,0,this_tid(),this_tid()));
            assert(view().faults && !view().predecessor_completed && dispatch(&guard,1)==-1021);
            assert_no_claim();assert(native_cp302c_diagnostic_owner_init());goto done;
        }
        if(!strncmp(test,"input-",6)) {
            unsigned char wire[24]={0,0,7,0x30};
            unsigned int bytes=!strcmp(test,"input-short")?23u:24u;
            unsigned int source=!strcmp(test,"input-source")?NATIVE_CP302C_SID:AP;
            if(!strcmp(test,"input-type"))wire[0]=5;
            if(!strcmp(test,"input-repeat"))assert(!native_cp302c_observe_input(NATIVE_CP302C_SID,wire,source,bytes,"first-3007"));
            assert(native_cp302c_observe_input(NATIVE_CP302C_SID,wire,source,bytes,"bad-3007"));
            assert(view().faults && !view().predecessor_completed && dispatch(&guard,1)==-1021);
            assert_no_claim();goto done;
        }
    }
    if(!strcmp(test,"prefix-before")) {
        unsigned char prefix[12]={5,0,0x2a,0x40,1,0,0,0x80,0x7f,0xa5,0xa5,0xa5};
        assert(native_cp302c_parameter_prefix_supported(0x402a));
        assert(!native_cp302c_observe_input(NATIVE_CP302C_SID,prefix,AP,12,"prefix-before-3007"));
        assert(view().history_seq==2 && view().history_valid && !view().current);
    }
    if(!strcmp(test,"early")) {
        struct native_cp302c_snapshot before=view();
        assert(!native_cp302c_observe_input(NATIVE_CP302C_SID,request,AP,24,"early-probe"));
        assert(dispatch(&guard,1)==-1021);assert_no_claim();
        struct native_cp302c_snapshot after=view();assert(!memcmp(&before,&after,sizeof before) && !reserves && !allocations);
    }
    if(!strncmp(test,"prior-",6)) { run_prior(test+6);assert(dispatch(&guard,1)==-1021);assert_no_claim();goto done; }
    run_prior("");
    if(diagnostic)audit_unknown();
    if(!strncmp(test,"prefix-",7) && strcmp(test,"prefix-before")) {
        unsigned char prefix[16]={5,0x71,0x2a,0x40,0x2a,0,0,0x80,0xff,0xa5,0xa5,0xa5};
        unsigned int bytes=!strcmp(test,"prefix-short")?8u:!strcmp(test,"prefix-long")?16u:12u;
        unsigned int source=!strcmp(test,"prefix-source")?PRIOR_AP:AP;
        if(!strcmp(test,"prefix-type"))prefix[0]=2;
        struct native_cp302c_snapshot before=view();
        int rc=native_cp302c_observe_input(NATIVE_CP302C_SID,prefix,source,bytes,"prefix-after-3007");
        if(strcmp(test,"prefix-after")) {
            assert(rc && !view().history_valid && !view().current_known && view().faults);
            assert(dispatch(&guard,1)==-1021);assert_no_claim();goto done;
        }
        struct native_cp302c_snapshot after=view();assert(!rc && after.history_seq==before.history_seq+1);
        before.history_seq=after.history_seq;assert(!memcmp(&before,&after,sizeof before));
    }
    if(!strcmp(test,"other-endpoints")) {
        struct native_cp302c_snapshot before=view();
        unsigned char wire[24]={5,0,0x3d,0x40};
        assert(!native_cp302c_observe_input(0x90040193u,wire,AP,24,"API-entry-not-IPC-delivery"));
        wire[2]=0x37;assert(!native_cp302c_observe_input(0x90040193u,wire,AP,24,"API-entry-not-IPC-delivery"));
        wire[2]=0xa5;assert(!native_cp302c_observe_input(0x90040193u,wire,AP,24,"API-entry-not-IPC-delivery"));
        struct native_cp302c_snapshot after=view();assert(!memcmp(&before,&after,sizeof before));
    }
    if(!strcmp(test,"unknown-type5") || !strcmp(test,"unknown-mode")) {
        unsigned char wire[24]={0,0,6,0x30};
        if(!strcmp(test,"unknown-type5")) { wire[0]=5;wire[2]=0xb8;wire[3]=0x40; }
        assert(!native_cp302c_parameter_prefix_supported(0x40b8));
        assert(!native_cp302c_parameter_prefix_supported(0x4139));
        assert(native_cp302c_observe_input(NATIVE_CP302C_SID,wire,AP,24,"unknown-causal-input"));
        assert(dispatch(&guard,1)==-1021 && native_cp302c_owner_init());assert_no_claim();
        assert(view().faults && !view().history_valid && !view().current_known);goto done;
    }
    if(!strcmp(test,"guard")) {
        assert(dispatch(NULL,1)==-1021);struct native_cp302c_guard incomplete=guard;incomplete.predecessor_ready=NULL;
        assert(dispatch(&incomplete,1)==-1021);reserve_rc=-11;assert(dispatch(&guard,1)==-11);assert_no_claim();
        reserve_rc=0;ready=0;assert(dispatch(&guard,1)==-1021);assert_no_claim();assert(!view().faults && !allocations);ready=1;
    }
    if(!strcmp(test,"malformed")) {
        packet(request)->bytes=23;assert(dispatch(&guard,1)==-1021);assert_no_claim();
        packet(request)->bytes=24;packet(request)->source=0x90030002u;assert(dispatch(&guard,1)==-1021);assert_no_claim();
        packet(request)->source=AP;((unsigned char *)request)[0]=2;int rc=99;
        assert(!native_cp302c_dispatch(NATIVE_CP302C_SID,request,&io,&guard,1,&rc) && rc==99);assert_no_claim();
        ((unsigned char *)request)[0]=0;
    }
    if(!strcmp(test,"allocfail")) {
        allocation_rc=-12;assert(dispatch(&guard,1)==-12);assert_no_claim();assert(!view().faults);
        assert(packet(request)->owner==NATIVE_CP302C_SID);allocation_rc=0;allocations=0;
    }
    if(!strcmp(test,"during-allocation"))input_during_allocate=1;
    if(!strcmp(test,"before-publication"))input_before_publication=1;
    if(!strcmp(test,"short-allocation"))short_allocation=1;
    if(!strcmp(test,"alias"))alias_allocation=1;
    if(!strcmp(test,"bad-reply-source"))bad_reply_source=1;
    if(short_allocation || alias_allocation || bad_reply_source || input_during_allocate) {
        unsigned int before=releases;assert(dispatch(&guard,1)==-1021);assert_no_claim();assert(view().faults);
        assert(releases==before+(alias_allocation?0u:1u));assert(packet(request)->bytes==24);
        assert(!memcmp(request,expected_request,24) && !sends);goto done;
    }
    if(!strcmp(test,"sendfail") || !strcmp(test,"cleanupfail") || !strcmp(test,"async-inflight"))send_rc=-17;
    if(!strcmp(test,"requestfail"))fail_request_free=1;
    if(!strcmp(test,"replyfail") || !strcmp(test,"cleanupfail"))fail_reply_free=1;
    if(!strcmp(test,"fast-free-reuse"))inline_free=reuse_free=1;
    if(!strcmp(test,"reentrant"))reentrant_free=1;
    if(!strcmp(test,"async-inflight"))async_free=1;
    assert(!dispatch(&guard,1));
    if(input_before_publication) {
        struct native_cp302c_snapshot s=view();assert(s.faults && !s.queued && !sends && s.retained_request && !s.live_reply && !s.ap_consumed);
    } else if(async_free) {
        struct native_cp302c_snapshot s=view();assert(s.faults && s.live_reply && !s.reply_freed && s.retained_request && !s.ap_consumed);
        unsigned int calls=releases;pthread_mutex_lock(&async_mutex);unblock=1;pthread_cond_broadcast(&async_cond);pthread_mutex_unlock(&async_mutex);
        assert(!pthread_join(free_thread,NULL));assert(releases==calls);assert(!view().live_reply && view().reply_freed && !view().ap_consumed);
    } else if(send_rc) {
        struct native_cp302c_snapshot s=view();assert(s.faults && !s.queued && s.retained_request && !s.ap_consumed);
        if(!strcmp(test,"cleanupfail")) { assert(s.live_reply);consume();assert(!view().live_reply && view().faults); }
        else assert(!s.live_reply && s.reply_freed);
    } else if(!strcmp(test,"foreign")) {
        assert(!pthread_create(&free_thread,NULL,free_in_thread,queued_reply));assert(!pthread_join(free_thread,NULL));
        assert(view().reply_freed && view().faults && !view().ap_consumed);
    } else if(!strcmp(test,"wrong-owner")) {
        unsigned int before=releases;int rc=0;assert(native_cp302c_release_reply(PRIOR_AP,queued_reply,release_packet,logger,&rc)==1 && rc==-1021);
        assert(releases==before && view().live_reply && view().faults);consume();assert(!view().ap_consumed);
    } else if(!strcmp(test,"fork-lock")) {
        native_cp302c_test_hold_lock();pid_t child=fork();assert(child>=0);
        if(!child) {
            alarm(3);unsigned int before=size_calls;int rc=0;
            assert(native_cp302c_owner_init());assert(dispatch(&guard,1)==-1021 && size_calls==before);
            assert(view().faults && view().owner_pid!=getpid());
            assert(native_cp302c_observe_input(NATIVE_CP302C_SID,expected_request,AP,24,"child"));
            assert(native_cp302c_release_reply(AP,queued_reply,release_packet,logger,&rc)==1 && rc==-1021);
            _exit(0);
        }
        int status;assert(waitpid(child,&status,0)==child);native_cp302c_test_drop_lock();assert(WIFEXITED(status) && !WEXITSTATUS(status));
        consume();assert_success();
    } else if(!strcmp(test,"replyfail")) {
        int rc=0;assert(native_cp302c_release_reply(AP,queued_reply,release_packet,logger,&rc)==1 && rc==-21);
        assert(view().live_reply && view().faults && !view().ap_consumed);consume();assert(!view().live_reply && !view().ap_consumed);
    } else {
        if(diagnostic && !inline_free)assert(!view().clean_completion && !view().ap_consumed);
        if(diagnostic)audit_unknown();
        if(!inline_free)consume();
        if(diagnostic)audit_unknown();
        if(!strcmp(test,"requestfail") || !strcmp(test,"reentrant"))assert(view().faults && !view().ap_consumed);
        else assert_success();
        if(reused) { int rc=99;assert(!native_cp302c_release_reply(AP,reused,release_packet,logger,&rc) && rc==99); }
    }
    if(view().retained_request) {
        int rc=123;assert(native_cp302c_release_reply(NATIVE_CP302C_SID,request,release_packet,logger,&rc)==1 && !rc);
        assert(view().faults && !view().retained_request && !view().ap_consumed);
    }
    assert(!guard_held && !view().busy && !view().guard_held);
 done:
    for(unsigned int i=0;i<32;i++)free(packets[i]);
    puts("host-unit-only CP302c finite owner: ok; real AP/all13/CP/capture unverified");return 0;
}
