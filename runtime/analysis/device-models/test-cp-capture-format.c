/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-capture-format.h"
#include <stddef.h>
#include <pthread.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

/* Actual wire supplied by the parent; provenance/stack wait is external. */
static unsigned char wire[24] = {
    5,0,0x2d,0x40,0x27,0,0,0x80,2,0,1,1,1,1,1,0,1,1,1,1,1,0,0,0
};
static unsigned int length=24, origin=FULL_IMAGING_AP, logs, recurse;
static struct full_imaging_io io;
static unsigned int size_of(void *p) {
    assert(p==wire);
    if(recurse==1) {
        recurse=0; int result=0;
        assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==1);
        assert(result==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
    return length;
}
static unsigned int source_of(void *p) { assert(p==wire); return origin; }
static void record(const char *tag,const char *text) {
    assert(!strcmp(tag,"NATIVE_CP_CAPTURE_FORMAT_BLOCKED "));
    assert(strstr(text,"first_missing=0x353eac"));
    assert(strstr(text,"source_closed=0 semantic_consumed=0 generation=0 published=0 reply=0"));
    assert(strstr(text,"native_cp=0 EE=0 frame=0 capture=0"));
    logs++;
    if(recurse==2) {
        recurse=0; int result=0;
        assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==1);
        assert(result==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
}
static void decode(void) {
    struct cp_capture_format_audit a, saved;
    memset(&a,0xa5,sizeof a); saved=a;
    for(size_t n=0;n<27;n++)if(n!=24) {
        assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,wire,n)==-EINVAL);
        assert(!memcmp(&a,&saved,sizeof a));
    }
    assert(cp_capture_format_inspect(NULL,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,wire,24)==-EINVAL);
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,NULL,24)==-EINVAL);
    assert(cp_capture_format_inspect(&a,0,NATIVE_CP_CAPTURE_FORMAT_SID,wire,24)==-EPROTO);
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,0,wire,24)==-EPROTO);
    assert(!memcmp(&a,&saved,sizeof a));
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,wire,24)==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    assert(!memcmp(a.request_wire,wire,24));
    assert(a.cookie==UINT32_C(0x80000027) && a.p_e0==2 && a.p_f8==0);
    assert(a.p_104==257 && a.p_106==257 && a.p_108==1);
    assert(a.p_114==257 && a.p_116==257 && a.p_118==1);
    assert(a.first_missing_address==0x353eac && a.request_fnv1a32==UINT32_C(0x7c14bd08));
    saved=a;
    wire[1]=0xff; wire[4]=0x91; wire[22]=0xb1; wire[23]=0xc3;
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,wire,24)==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    assert(a.p_e0==saved.p_e0 && a.p_104==saved.p_104 && a.p_118==saved.p_118);
    assert(a.request_fnv1a32!=saved.request_fnv1a32 && a.request_wire[22]==0xb1 && a.request_wire[23]==0xc3);
    memcpy(wire,saved.request_wire,24);
    unsigned char unaligned[25]; memcpy(unaligned+1,wire,24);
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,unaligned+1,24)==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,&a,24)==-EINVAL);
    assert(cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,(unsigned char *)&a+sizeof a-1,24)==-EINVAL);
    for(unsigned int n=0;n<24;n++) {
        wire[n]^=0xff;
        int rc=cp_capture_format_inspect(&a,FULL_IMAGING_AP,NATIVE_CP_CAPTURE_FORMAT_SID,wire,24);
        assert(rc==(n==0 || n==2 || n==3 ? -EPROTO : CP_CAPTURE_FORMAT_SOURCE_BLOCKED));
        wire[n]^=0xff;
    }
}
static void dispatch(void) {
    /* NULL allocation/send/free callbacks make any accidental ACK fatal. */
    io=(struct full_imaging_io){.size=size_of,.source=source_of,.record=record};
    int result=73;
    assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,0,&result)==0 && result==73);
    assert(native_cp_capture_format_dispatch(0,wire,&io,1,&result)==0 && result==73);
    assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==1);
    assert(result==CP_CAPTURE_FORMAT_SOURCE_BLOCKED && logs==1);
    for(unsigned int n=0;n<3;n++) {
        recurse=n; result=0;
        assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==1);
        assert(result==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
    unsigned int before=logs;
    origin=0; result=0;
    assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==1);
    assert(result==CP_CAPTURE_FORMAT_SOURCE_BLOCKED && logs==before); origin=FULL_IMAGING_AP;
    for(unsigned int n=0;n<27;n++)if(n!=24) {
        length=n; result=73;
        assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==(n>=4));
        assert(result==(n>=4 ? CP_CAPTURE_FORMAT_SOURCE_BLOCKED : 73));
    }
    length=24; wire[2]=0x73; result=73;
    assert(native_cp_capture_format_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,wire,&io,1,&result)==0 && result==73);
    wire[2]=0x2d;
}
static int diagnostic_main(int argc,char **argv);
int main(int argc,char **argv) {
    if(argc>1)return diagnostic_main(argc,argv);
    decode(); dispatch();
    puts("402d source blocked; request remains caller-owned; no ACK/CP/EE/frame/capture");
    return 0;
}

/* Host fixture: predecessor callbacks are mocks, not real AP/all13 evidence. */
struct packet { unsigned int owner,source,bytes;unsigned char body[32]; };
static struct packet *packets[16];
static void *request,*queued_reply,*reused;
static unsigned char expected_request[24];
static unsigned int allocations,sends,reserves,unreserves,ready_calls,held,d_logs;
static _Atomic unsigned int frees;
static int notification_free=1,diag_free=1,all13_clean=1,staging_free=1,reserve_rc,allocation_rc,bad_allocation,alias,bad_source,bad_copy;
static int send_rc,request_fail,reply_fail,cleanup_fail,inline_free,reuse_free,reentrant_free,async_free;
static int mutate_request,lose_guard,reenter,inspect_reenter,after_admission_fault,allocate_with_error,null_allocation;
static pthread_t free_thread;
static pthread_mutex_t async_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t async_cond=PTHREAD_COND_INITIALIZER;
static int entered,unblock;
static const struct full_imaging_io d_io;
static const struct native_cp_capture_format_diagnostic_guard guard;
static long this_tid(void) { return syscall(SYS_gettid); }
static struct native_cp_capture_format_diagnostic_snapshot view(void) {
    struct native_cp_capture_format_diagnostic_snapshot s;native_cp_capture_format_diagnostic_snapshot(&s);
    assert(!s.source_business_applied && !s.current_known && !s.source_dependency_closed && !s.generation);
    assert(!s.pending_complete && !s.native_verified && !s.native_cp && !s.ee && !s.frame && !s.capture && !s.source_byte1_known);
    if(s.initialized)assert(s.diagnostic_only && s.no_publication && s.virtual_padding);
    return s;
}
static struct packet *packet(void *p) { return (struct packet *)((unsigned char *)p - offsetof(struct packet,body)); }
static void *make_packet(unsigned int owner,unsigned int source,unsigned int bytes) {
    struct packet *p=calloc(1,sizeof *p);assert(p);p->owner=owner;p->source=source;p->bytes=bytes;
    unsigned int i=0;while(i<16 && packets[i])i++;assert(i<16);packets[i]=p;return p->body;
}
static void destroy(void *body) {
    struct packet *p=packet(body);unsigned int i=0;while(i<16 && packets[i]!=p)i++;
    assert(i<16);packets[i]=NULL;free(p);
}
static void probe_reentry(void) {
    static struct packet probe={NATIVE_CP_CAPTURE_FORMAT_SID,FULL_IMAGING_AP,24,{5,0,0x2d,0x40}};
    int rc=123;assert(native_cp_capture_format_diagnostic_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,probe.body,&d_io,&guard,1,&rc)==1);
    assert(rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
}
static unsigned int d_size(void *p) {
    (void)view();if(inspect_reenter) { inspect_reenter=0;probe_reentry(); }
    return packet(p)->bytes;
}
static unsigned int d_source(void *p) { (void)view();return packet(p)->source; }
static void d_set_source(void *p,unsigned int source) {
    (void)view();packet(p)->source=bad_source?FULL_IMAGING_AP:source;
    if(bad_copy)((unsigned char *)p)[4]^=0x80;
}
static int d_allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    allocations++;(void)view();assert(owner==FULL_IMAGING_AP && bytes==12 && wait==1 && held);
    if(reenter)probe_reentry();
    if(alias) { *out=(unsigned char *)request+(alias==2?23:alias==3?-11:0);return 0; }
    if(allocation_rc || null_allocation) { *out=NULL;return allocation_rc; }
    *out=make_packet(owner,0,bad_allocation?(unsigned int)bad_allocation:12u);
    if(mutate_request)((unsigned char *)request)[23]^=1;
    if(lose_guard)notification_free=0;
    return allocate_with_error?-33:0;
}
static void logger(const char *tag,const char *line) {
    (void)view();d_logs++;
    assert(strstr(tag,"NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_")==tag);
    assert(strstr(line,"diagnostic_only=1 no_publication=1 source_business_applied=0 current_known=0 source_dependency_closed=0"));
    assert(strstr(line,"pending_complete=0 generation=0 native_verified=0 native_cp=0 CP_history_verified=0 EE=0 frame=0 capture=0"));
    assert(strstr(line,"source_byte1_known=0 virtual_padding=1"));
    if(reenter)probe_reentry();
    if(after_admission_fault && strstr(tag,"_REQUEST ")) {
        after_admission_fault=0;int rc=0;
        assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,request,d_io.release,logger,&rc)==1 && rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
}
static int release_packet(unsigned int owner,void *body) {
    frees++;(void)view();assert(packet(body)->owner==owner);
    if(reenter)probe_reentry();
    if(reentrant_free && body==queued_reply) {
        reentrant_free=0;int rc=0;
        assert(native_cp_capture_format_diagnostic_release_reply(owner,body,release_packet,logger,&rc)==1 && rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
    if(async_free && body==queued_reply) {
        pthread_mutex_lock(&async_mutex);entered=1;pthread_cond_broadcast(&async_cond);
        while(!unblock)pthread_cond_wait(&async_cond,&async_mutex);
        pthread_mutex_unlock(&async_mutex);
    }
    if(body==request && request_fail) { request_fail--;return -19; }
    if(body!=request && cleanup_fail) { cleanup_fail--;return -23; }
    if(body==queued_reply && reply_fail) { reply_fail--;return -21; }
    if(body==queued_reply && reuse_free) {
        reused=body;packet(body)->owner=0x81234567u;memset(body,0xa5,12);return 0;
    }
    destroy(body);return 0;
}
static void *free_in_thread(void *body) {
    int rc=123;
    assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,body,release_packet,logger,&rc)==1 && !rc);
    return NULL;
}
static int send_packet(unsigned int owner,void *body) {
    struct native_cp_capture_format_diagnostic_snapshot s=view();sends++;
    assert(owner==FULL_IMAGING_AP && packet(body)->owner==owner && packet(body)->source==NATIVE_CP_CAPTURE_FORMAT_SID);
    assert(packet(body)->bytes==12 && body!=request && held && s.busy);
    assert(s.requests==1 && s.sender_tid==this_tid() && ready_calls==2 && d_logs==1);
    assert(!memcmp(s.audit.request_wire,expected_request,24));
    assert(!memcmp(body,(unsigned char[]){1,0,0x2d,0x40},4));
    assert(!memcmp((unsigned char *)body+4,expected_request+4,4));
    assert(!memcmp((unsigned char *)body+8,(unsigned char[]){0,0xf0,0,0},4));
    queued_reply=body;if(reenter)probe_reentry();
    if(inline_free) { int rc;assert(native_cp_capture_format_diagnostic_release_reply(owner,body,release_packet,logger,&rc)==1 && !rc); }
    if(async_free) {
        assert(!pthread_create(&free_thread,NULL,free_in_thread,body));
        pthread_mutex_lock(&async_mutex);while(!entered)pthread_cond_wait(&async_cond,&async_mutex);pthread_mutex_unlock(&async_mutex);
    }
    return send_rc;
}
static int reserve(void) {
    (void)view();reserves++;if(reenter)probe_reentry();
    if(reserve_rc)return reserve_rc;
    assert(!held);held=1;return 0;
}
static void unreserve(void) { (void)view();assert(held);if(reenter)probe_reentry();held=0;unreserves++; }
static int predecessor_ready(void) {
    (void)view();assert(held);ready_calls++;if(reenter)probe_reentry();
    return notification_free && diag_free && all13_clean && staging_free;
}
static const struct full_imaging_io d_io={d_allocate,release_packet,d_set_source,send_packet,d_size,d_source,logger};
static const struct native_cp_capture_format_diagnostic_guard guard={reserve,unreserve,predecessor_ready};
static int d_dispatch(const struct native_cp_capture_format_diagnostic_guard *g) {
    int rc=123;assert(native_cp_capture_format_diagnostic_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,request,&d_io,g,1,&rc)==1);return rc;
}
static void make_request(void) {
    request=make_packet(NATIVE_CP_CAPTURE_FORMAT_SID,FULL_IMAGING_AP,24);memcpy(request,wire,24);memcpy(expected_request,request,24);
}
static void finish_packets(void) { for(unsigned int i=0;i<16;i++)if(packets[i]) { free(packets[i]);packets[i]=NULL; } }
static void assert_refused(void) {
    struct native_cp_capture_format_diagnostic_snapshot s=view();
    assert(!s.requests && !s.queued && !s.retained_request && !s.busy && !s.guard_held && !s.live_reply && !s.ap_consumed && !sends);
    assert(!held && !memcmp(request,expected_request,24));
}
static int diagnostic_main(int argc,char **argv) {
    assert(argc==2);const char *test=argv[1];make_request();
    if(strcmp(test,"preinit"))assert(!native_cp_capture_format_diagnostic_owner_init());
    if(!strcmp(test,"normal")) {
        struct native_cp_capture_format_diagnostic_snapshot s=view();
        assert(s.initialized && !s.requests && s.owner_pid==getpid());
        assert(native_cp_capture_format_diagnostic_owner_init()==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
    if(!strcmp(test,"opaque")) {
        ((unsigned char *)request)[1]=0xc7;((unsigned char *)request)[4]=0xd1;((unsigned char *)request)[22]=0xa1;((unsigned char *)request)[23]=0xb2;
        memcpy(expected_request,request,24);
    }
    if(!strcmp(test,"default-off") || !strcmp(test,"unrelated") || !strcmp(test,"wrong-type") || !strcmp(test,"other-destination") || !strcmp(test,"short-header")) {
        if(!strcmp(test,"unrelated"))((unsigned char *)request)[2]=0x2e;
        if(!strcmp(test,"wrong-type"))((unsigned char *)request)[0]=0;
        if(!strcmp(test,"short-header"))packet(request)->bytes=3;
        memcpy(expected_request,request,24);int rc=123;
        assert(!native_cp_capture_format_diagnostic_dispatch(!strcmp(test,"other-destination")?FULL_IMAGING_CP:NATIVE_CP_CAPTURE_FORMAT_SID,
            request,&d_io,&guard,!strcmp(test,"default-off")?0:1,&rc) && rc==123);
        assert_refused();goto done;
    }
    if(!strcmp(test,"badlen"))packet(request)->bytes=23;
    if(!strcmp(test,"long"))packet(request)->bytes=25;
    if(!strcmp(test,"wrong-source"))packet(request)->source=0x80020003u;
    if(!strcmp(test,"notification-missing"))notification_free=0;
    if(!strcmp(test,"diag-missing"))diag_free=0;
    if(!strcmp(test,"all13-missing"))all13_clean=0;
    if(!strcmp(test,"staging-missing"))staging_free=0;
    if(!strcmp(test,"reserve-refused"))reserve_rc=-14;
    if(!strcmp(test,"missing-io")) {
        for(unsigned int i=0;i<7;i++) {
            struct full_imaging_io partial=d_io;
            switch(i) {
            case 0:partial.allocate=NULL;break;case 1:partial.release=NULL;break;case 2:partial.set_source=NULL;break;
            case 3:partial.send=NULL;break;case 4:partial.size=NULL;break;case 5:partial.source=NULL;break;default:partial.record=NULL;
            }
            int rc=123;assert(native_cp_capture_format_diagnostic_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,request,&partial,&guard,1,&rc)==(i==4?0:1));
            assert_refused();assert(!allocations && !reserves);
        }
        goto done;
    }
    if(!strcmp(test,"missing-guard") || !strcmp(test,"guard-incomplete") || !strcmp(test,"preinit") || !strcmp(test,"badlen") ||
       !strcmp(test,"long") || !strcmp(test,"wrong-source") || !strcmp(test,"notification-missing") || !strcmp(test,"diag-missing") ||
       !strcmp(test,"all13-missing") || !strcmp(test,"staging-missing") || !strcmp(test,"reserve-refused")) {
        struct native_cp_capture_format_diagnostic_guard incomplete=guard;incomplete.predecessor_ready=NULL;
        assert(d_dispatch(!strcmp(test,"missing-guard")?NULL:!strcmp(test,"guard-incomplete")?&incomplete:&guard));
        assert_refused();assert(!allocations);goto done;
    }
    if(!strcmp(test,"allocfail"))allocation_rc=-16;
    if(!strcmp(test,"null-allocation"))null_allocation=1;
    if(!strcmp(test,"short-allocation"))bad_allocation=11;
    if(!strcmp(test,"long-allocation"))bad_allocation=13;
    if(!strcmp(test,"alias"))alias=1;
    if(!strcmp(test,"overlap"))alias=2;
    if(!strcmp(test,"overlap-before"))alias=3;
    if(!strcmp(test,"bad-reply-source"))bad_source=1;
    if(!strcmp(test,"bad-reply-copy"))bad_copy=1;
    if(!strcmp(test,"allocation-error-pointer"))allocate_with_error=1;
    if(!strcmp(test,"lost-guard"))lose_guard=1;
    if(!strcmp(test,"mutated-request"))mutate_request=1;
    if(!strcmp(test,"cleanupfail")) { bad_allocation=11;cleanup_fail=1; }
    if(allocation_rc || null_allocation || bad_allocation || alias || bad_source || bad_copy || allocate_with_error || lose_guard || mutate_request) {
        assert(d_dispatch(&guard));if(mutate_request)memcpy(expected_request,request,24);
        assert_refused();struct native_cp_capture_format_diagnostic_snapshot s=view();
        assert(s.faults==(!strcmp(test,"allocfail")?0u:1u));assert(allocations==1 && unreserves==1);
        if(!strcmp(test,"cleanupfail")) {
            assert(s.retained_cleanup && s.reply_free_rc==-23);int rc=0;
            assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,s.retained_cleanup,release_packet,logger,&rc)==1 && !rc);
        }
        goto done;
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
    if(!strcmp(test,"before-send-fault"))after_admission_fault=1;
    assert(!d_dispatch(&guard));
    struct native_cp_capture_format_diagnostic_snapshot s=view();
    assert(s.requests==1 && s.sender_tid==this_tid() && !held && unreserves==1 && s.cookie==s.audit.cookie);
    assert(!memcmp(s.audit.request_wire,expected_request,24) && s.audit.first_missing_address==CP_CAPTURE_FORMAT_FIRST_MISSING);
    if(!strcmp(test,"before-send-fault")) {
        assert(s.faults && !sends && s.retained_request && !s.live_reply);goto done;
    }
    assert(sends==1);
    if(async_free) {
        assert(s.live_reply && !s.reply_freed && s.faults && s.send_rc==-17);
        int rc=0;unsigned int before=frees;
        assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
        assert(frees==before);
        pthread_mutex_lock(&async_mutex);unblock=1;pthread_cond_broadcast(&async_cond);pthread_mutex_unlock(&async_mutex);
        assert(!pthread_join(free_thread,NULL));s=view();assert(s.reply_freed && s.faults && !s.ap_consumed);goto done;
    }
    if(send_rc) {
        assert(s.faults && s.retained_request && !s.request_freed && !s.queued && s.send_rc==-17);
        if(!strcmp(test,"send-cleanupfail")) {
            assert(s.live_reply && s.reply_free_rc==-21);int rc;
            assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && !rc);
        } else assert(!s.live_reply);
        goto done;
    }
    assert(s.queued);if(!inline_free)assert(!s.ap_consumed);
    if(!strcmp(test,"fork-lock")) {
        native_cp_capture_format_diagnostic_test_hold_lock();pid_t child=fork();assert(child>=0);
        if(!child) {
            alarm(2);struct native_cp_capture_format_diagnostic_snapshot inherited;native_cp_capture_format_diagnostic_snapshot(&inherited);
            assert(inherited.faults && inherited.owner_pid!=getpid() && inherited.diagnostic_only && inherited.no_publication);
            assert(native_cp_capture_format_diagnostic_owner_init()==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);int rc=0;
            assert(native_cp_capture_format_diagnostic_dispatch(NATIVE_CP_CAPTURE_FORMAT_SID,queued_reply,&d_io,&guard,1,&rc)==1 && rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
            assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
            _exit(0);
        }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        native_cp_capture_format_diagnostic_test_drop_lock();
    }
    if(!inline_free) {
        if(!strcmp(test,"wrong-waiter")) {
            assert(!pthread_create(&free_thread,NULL,free_in_thread,queued_reply));assert(!pthread_join(free_thread,NULL));
        } else {
            int rc=123;
            if(!strcmp(test,"foreign")) {
                void *speech=make_packet(FULL_IMAGING_AP,0x90041234u,12),*osd[16];
                assert(!native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,speech,release_packet,logger,&rc));destroy(speech);
                for(unsigned int i=0;i<16;i++) {
                    osd[i]=make_packet(FULL_IMAGING_AP,0x90040016u,12);
                    assert(!native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,osd[i],release_packet,logger,&rc));destroy(osd[i]);
                }
            }
            if(!strcmp(test,"wrong-owner")) {
                unsigned int before=frees;
                assert(native_cp_capture_format_diagnostic_release_reply(0x80020003u,queued_reply,release_packet,logger,&rc)==1 && rc==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
                assert(frees==before && view().live_reply);
            }
            if(!strcmp(test,"altered-wire"))((unsigned char *)queued_reply)[4]^=1;
            if(!strcmp(test,"altered-source"))packet(queued_reply)->source=FULL_IMAGING_AP;
            if(!strcmp(test,"altered-size"))packet(queued_reply)->bytes=11;
            assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1);
            if(!strcmp(test,"replyfail")) {
                assert(rc==-21 && view().faults && view().live_reply);
                assert(native_cp_capture_format_diagnostic_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && !rc);
            } else assert(!rc);
        }
    }
    s=view();assert(s.reply_freed && !s.live_reply && s.reply_free_destination==FULL_IMAGING_AP);
    if(!strcmp(test,"requestfail")) {
        assert(s.request_free_rc==-19 && s.retained_request && s.faults);int rc;
        assert(native_cp_capture_format_diagnostic_release_reply(NATIVE_CP_CAPTURE_FORMAT_SID,s.retained_request,release_packet,logger,&rc)==1 && !rc);
    }
    int expected_fault=!strcmp(test,"wrong-waiter") || !strcmp(test,"wrong-owner") || !strcmp(test,"replyfail") ||
        !strcmp(test,"requestfail") || !strcmp(test,"reentrant-free") || !strcmp(test,"altered-wire") || !strcmp(test,"altered-source") || !strcmp(test,"altered-size");
    s=view();assert(s.faults==(unsigned int)expected_fault && s.ap_consumed==(unsigned int)!expected_fault);
    if(!expected_fault) {
        assert(s.clean_completion && s.waiter_tid==s.sender_tid && s.request_freed && s.reply_freed);
        assert(s.reply_free_bytes==12 && s.reply_free_source==NATIVE_CP_CAPTURE_FORMAT_SID && !memcmp(s.freed_reply_wire,s.reply_wire,12));
    }
    if(reused)assert(!memcmp(reused,(unsigned char[]){0xa5,0xa5,0xa5,0xa5},4));
    {
        void *prior=request;make_request();assert(d_dispatch(&guard)==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);request=prior;
        assert(view().requests==1 && native_cp_capture_format_diagnostic_owner_init()==CP_CAPTURE_FORMAT_SOURCE_BLOCKED);
    }
done:
    finish_packets();puts("PASS: diagnostic402d transport only; format/current/publication/EE/capture unverified");return 0;
}
