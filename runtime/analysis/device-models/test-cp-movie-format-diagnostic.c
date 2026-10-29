/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-movie-format-diagnostic.h"
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

/* Unit-only guard stubs/IO mocks are NOT native CP readiness evidence. */
static const unsigned char actual[20]={5,0,0,0x40,0x27,0,0,0x80,5,1,0,0,0,0,0,0,0,0,1,0};
static const unsigned char actual_reply[12]={1,0,0,0x40,0x27,0,0,0x80,0,0xf0,0,0};
struct packet { unsigned int owner,source,bytes;unsigned char body[64]; };
static struct packet *packets[16];
static void *request,*queued,*reused;
static unsigned char expected[20];
static unsigned int allocations,sends,reserves,unreserves,ready_calls,held,logs;
static _Atomic unsigned int frees;
static int predecessors[8]={1,1,1,1,1,1,1,1};
static int reserve_rc,allocate_rc,null_allocate,bad_size,alias,bad_source,bad_copy,error_pointer;
static int send_rc,request_fail,reply_fail,cleanup_fail,inline_free,reuse_free,reentrant_free,async_free;
static int mutate_request,mutate_source,initial_mutation,lose_guard,reenter,inspect_reenter,request_reentry;
static pthread_t worker;
static pthread_mutex_t async_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t async_cond=PTHREAD_COND_INITIALIZER;
static int entered,unblock;
static const struct full_imaging_io io;
static const struct native_cp_movie_format_diagnostic_guard guard;
static long this_tid(void) { return syscall(SYS_gettid); }
static struct native_cp_movie_format_diagnostic_snapshot view(void) {
    struct native_cp_movie_format_diagnostic_snapshot s;native_cp_movie_format_diagnostic_snapshot(&s);
    assert(s.diagnostic_only && s.no_publication && s.virtual_padding && s.opcode==0x4000 && s.supported);
    assert(!s.source_byte1_known && !s.source_business_applied && !s.current_known && !s.source_dependency_closed);
    assert(!s.business_applied && !s.source_dependencies_closed && !s.published && !s.configured && !s.generation);
    assert(!s.pending_complete && !s.native_verified && !s.native_cp && !s.ee && !s.frame && !s.capture);
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
static uint32_t hash(const unsigned char *p) {
    uint32_t value=UINT32_C(2166136261);
    for(unsigned int i=0;i<20;i++)value=(value^p[i])*UINT32_C(16777619);
    return value;
}
static void make_request(void) {
    request=make_packet(NATIVE_CP_MOVIE_FORMAT_SID,FULL_IMAGING_AP,20);
    memcpy(request,actual,20);memcpy(expected,actual,20);
}
static void probe_reentry(void) {
    static struct packet probe={NATIVE_CP_MOVIE_FORMAT_SID,FULL_IMAGING_AP,20,{0}};
    memcpy(probe.body,actual,20);int result=123;
    assert(native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,probe.body,&io,&guard,1,&result)==1);
    assert(result==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
}
static unsigned int size_of(void *p) {
    (void)view();if(inspect_reenter) { inspect_reenter=0;probe_reentry(); }
    return packet(p)->bytes;
}
static unsigned int source_of(void *p) {
    (void)view();if(initial_mutation && p==request) { initial_mutation=0;((unsigned char *)p)[12]=1; }
    return packet(p)->source;
}
static void set_source(void *p,unsigned int source) {
    (void)view();packet(p)->source=bad_source?FULL_IMAGING_AP:source;
    if(bad_copy)((unsigned char *)p)[4]^=1;
    if(reenter)probe_reentry();
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    allocations++;struct native_cp_movie_format_diagnostic_snapshot s=view();
    assert(owner==FULL_IMAGING_AP && bytes==12 && wait==1 && held && s.attempts==1 && !s.requests);
    assert(s.request_bytes==20 && !memcmp(s.request_wire,expected,20) && s.request_fnv1a32==hash(expected));
    if(reenter)probe_reentry();
    if(alias) { *out=(unsigned char *)request+(alias==2?19:alias==3?-11:0);return 0; }
    if(allocate_rc || null_allocate) { *out=NULL;return allocate_rc; }
    *out=make_packet(owner,0,bad_size?(unsigned int)bad_size:12u);return error_pointer?-33:0;
}
static void logger(const char *tag,const char *line) {
    (void)view();logs++;
    assert(strstr(tag,"NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_")==tag);
    assert(strstr(line,"diagnostic_only=1 no_publication=1 virtual_padding=1 source_byte1_known=0"));
    assert(strstr(line,"business_applied=0 source_dependencies_closed=0 configured=0 published=0 pending_complete=0 generation=0 native_verified=0 native_cp=0 EE=0 frame=0 capture=0"));
    if(reenter)probe_reentry();
}
static int release_packet(unsigned int owner,void *p) {
    frees++;(void)view();assert(packet(p)->owner==owner);
    if(reenter)probe_reentry();
    if(reentrant_free && p==queued) {
        reentrant_free=0;int result=123;
        assert(native_cp_movie_format_diagnostic_release_reply(owner,p,release_packet,logger,&result)==1 && result==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
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
    assert(native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,p,release_packet,logger,&result)==1 && !result);
    return NULL;
}
static void check_audit(struct native_cp_movie_format_diagnostic_snapshot s) {
    /* Literal expected values make offset18 and the full conditional u32 matter. */
    static const uint32_t fields[7]={5,1,0,0,0,0,1};
    assert(s.known_field_mask==0x7f && s.virtual_field_mask==0x7f && s.virtual_fields_consumed==0x7f && s.virtual_fields_readback);
    assert(!memcmp(s.virtual_fields,fields,sizeof fields) && !memcmp(s.virtual_readback,fields,sizeof fields));
    assert(s.request_bytes==20 && s.request_fnv1a32==hash(expected) && !memcmp(s.request_wire,expected,20));
}
static int send_packet(unsigned int owner,void *p) {
    struct native_cp_movie_format_diagnostic_snapshot s=view();sends++;
    assert(owner==FULL_IMAGING_AP && packet(p)->owner==owner && packet(p)->source==NATIVE_CP_MOVIE_FORMAT_SID);
    assert(packet(p)->bytes==12 && p!=request && held && s.busy && s.guard_held && s.attempts==1 && s.requests==1 && s.sender_tid==this_tid());
    assert(s.source==FULL_IMAGING_AP && s.request_destination==NATIVE_CP_MOVIE_FORMAT_SID && s.destination==FULL_IMAGING_AP);
    check_audit(s);unsigned char wanted[12];memcpy(wanted,actual_reply,12);memcpy(wanted+4,expected+4,4);
    assert(!memcmp(p,wanted,12) && !memcmp(s.reply_wire,wanted,12));
    queued=p;if(reenter)probe_reentry();
    if(request_reentry) {
        int result=123;unsigned int before=frees;
        assert(native_cp_movie_format_diagnostic_release_reply(NATIVE_CP_MOVIE_FORMAT_SID,request,release_packet,logger,&result)==1 && result==CP_MOVIE_FORMAT_SOURCE_BLOCKED && frees==before);
    }
    if(inline_free) { int result;assert(native_cp_movie_format_diagnostic_release_reply(owner,p,release_packet,logger,&result)==1 && !result); }
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
    if(ready_calls==2 && mutate_request)((unsigned char *)request)[19]^=1;
    if(ready_calls==2 && mutate_source)packet(request)->source=FULL_IMAGING_CP;
    if(ready_calls==2 && lose_guard)predecessors[7]=0;
    for(unsigned int i=0;i<8;i++)if(!predecessors[i])return 0;
    return 1;
}
static const struct full_imaging_io io={allocate,release_packet,set_source,send_packet,size_of,source_of,logger};
static const struct native_cp_movie_format_diagnostic_guard guard={reserve,unreserve,ready};
static int dispatch(const struct native_cp_movie_format_diagnostic_guard *g) {
    int result=123;
    assert(native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,request,&io,g,1,&result)==1);
    return result;
}
static void consume(void) {
    int result=123;
    assert(native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && !result);
}
static void check_clean(void) {
    struct native_cp_movie_format_diagnostic_snapshot s=view();
    assert(s.attempts==1 && s.requests==1 && s.queued && s.request_freed && s.reply_freed && s.clean_completion && s.ap_consumed && !s.faults);
    assert(!s.busy && !s.guard_held && !s.retained_request && !s.live_reply && !s.retained_cleanup);
    assert(s.reply_free_destination==FULL_IMAGING_AP && s.reply_free_source==NATIVE_CP_MOVIE_FORMAT_SID && s.reply_free_bytes==12);
    assert(s.sender_tid==s.waiter_tid && !memcmp(s.freed_reply_wire,s.reply_wire,12));check_audit(s);
}
static void assert_caller_owned(void) {
    struct native_cp_movie_format_diagnostic_snapshot s=view();
    assert(!s.requests && !s.busy && !s.guard_held && !held && !sends);
    assert(!s.retained_request && !s.live_reply && !s.ap_consumed);
    int result=123;unsigned int before=frees;
    assert(!native_cp_movie_format_diagnostic_release_reply(NATIVE_CP_MOVIE_FORMAT_SID,request,release_packet,logger,&result) && result==123 && frees==before);
}
static void fork_test(void *owned) {
    native_cp_movie_format_diagnostic_test_hold_lock();pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);struct native_cp_movie_format_diagnostic_snapshot s;native_cp_movie_format_diagnostic_snapshot(&s);
        assert(s.faults && s.owner_pid!=getpid() && s.diagnostic_only && s.no_publication && !s.native_cp && !s.ee && !s.frame && !s.capture);
        assert(native_cp_movie_format_diagnostic_owner_init()==CP_MOVIE_FORMAT_SOURCE_BLOCKED);int result=123;
        assert(native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,request,&io,&guard,1,&result)==1 && result==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
        assert(native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,owned,release_packet,logger,&result)==(owned!=NULL));
        if(owned)assert(result==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
        _exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    native_cp_movie_format_diagnostic_test_drop_lock();
}
int main(int argc,char **argv) {
    assert(argc==2 && !strcmp(FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE,"diagnostic-cp-movie-format-v1"));
    const char *test=argv[1];if(strcmp(test,"preinit"))assert(!native_cp_movie_format_diagnostic_owner_init());
    make_request();
    if(!strcmp(test,"default-off")) {
        for(int enabled=0;enabled<3;enabled+=2) {
            int result=123;assert(!native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,request,&io,&guard,enabled,&result) && result==123);
        }
        assert_caller_owned();assert(!reserves && !allocations && !frees && !logs);goto done;
    }
    if(!strcmp(test,"unrelated")) {
        static const unsigned int opcodes[]={0x3003,0x3000,0x3030,0x4072,0x3012,0x402d,0x409d,0xffff};
        int result=123;assert(!native_cp_movie_format_diagnostic_dispatch(FULL_IMAGING_CP,request,&io,&guard,1,&result) && result==123);
        for(unsigned int n=0;n<sizeof opcodes/sizeof *opcodes;n++)for(unsigned int bytes=0;bytes<=40;bytes++) {
            unsigned char *p=request;p[2]=(unsigned char)opcodes[n];p[3]=(unsigned char)(opcodes[n]>>8);packet(request)->bytes=bytes;
            result=123;assert(!native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,request,&io,&guard,1,&result) && result==123);
        }
        assert_caller_owned();assert(!reserves && !allocations && !frees && !logs);goto done;
    }
    if(!strcmp(test,"types") || !strcmp(test,"header-byte1") || !strcmp(test,"lengths") || !strcmp(test,"body-bits")) {
        if(!strcmp(test,"types"))for(unsigned int type=0;type<256;type++)if(type!=5) {
            ((unsigned char *)request)[0]=(unsigned char)type;assert(dispatch(&guard)==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
        }
        if(!strcmp(test,"header-byte1"))for(unsigned int value=1;value<256;value++) {
            ((unsigned char *)request)[1]=(unsigned char)value;assert(dispatch(&guard)==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
        }
        if(!strcmp(test,"lengths"))for(unsigned int bytes=0;bytes<=40;bytes++)if(bytes!=20) {
            packet(request)->bytes=bytes;int result=123;
            assert(native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,request,&io,&guard,1,&result)==(bytes>=4));
            assert(result==(bytes>=4?CP_MOVIE_FORMAT_SOURCE_BLOCKED:123));
        }
        if(!strcmp(test,"body-bits"))for(unsigned int byte=8;byte<20;byte++)for(unsigned int bit=0;bit<8;bit++) {
            memcpy(request,actual,20);((unsigned char *)request)[byte]^=(unsigned char)(1u<<bit);
            assert(dispatch(&guard)==CP_MOVIE_FORMAT_SOURCE_BLOCKED);assert(!view().business_applied && !view().configured);
        }
        assert_caller_owned();assert(!view().attempts && !reserves && !allocations && !frees && !logs);goto done;
    }
    if(!strcmp(test,"missing-io")) {
        for(unsigned int n=0;n<7;n++) {
            struct full_imaging_io partial=io;
            switch(n) { case 0:partial.allocate=NULL;break;case 1:partial.release=NULL;break;case 2:partial.set_source=NULL;break;
                case 3:partial.send=NULL;break;case 4:partial.size=NULL;break;case 5:partial.source=NULL;break;default:partial.record=NULL; }
            int result=123;assert(native_cp_movie_format_diagnostic_dispatch(NATIVE_CP_MOVIE_FORMAT_SID,request,&partial,&guard,1,&result)==(n!=4));
            assert_caller_owned();assert(!allocations && !reserves);
        }
        goto done;
    }
    if(!strcmp(test,"missing-guard")) {
        assert(dispatch(NULL)==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
        for(unsigned int n=0;n<3;n++) {
            struct native_cp_movie_format_diagnostic_guard partial=guard;
            if(!n)partial.reserve=NULL;else if(n==1)partial.release=NULL;else partial.predecessor_ready=NULL;
            assert(dispatch(&partial)==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
        }
        assert_caller_owned();assert(!allocations && !reserves);goto done;
    }
    if(!strcmp(test,"predecessor-false")) {
        for(unsigned int n=0;n<8;n++) {
            predecessors[n]=0;assert(dispatch(&guard)==CP_MOVIE_FORMAT_SOURCE_BLOCKED);assert_caller_owned();predecessors[n]=1;
        }
        assert(!view().attempts && !view().faults && !allocations && reserves==8 && unreserves==8);goto done;
    }
    if(!strcmp(test,"preinit") || !strcmp(test,"wrong-source") || !strcmp(test,"reserve-refused") || !strcmp(test,"initial-source-mutation")) {
        if(!strcmp(test,"wrong-source"))packet(request)->source=0x80020003u;
        if(!strcmp(test,"reserve-refused"))reserve_rc=-14;
        if(!strcmp(test,"initial-source-mutation"))initial_mutation=1;
        assert(dispatch(&guard));assert_caller_owned();assert(!view().attempts && !allocations && !sends && !frees && !held);goto done;
    }
    if(!strcmp(test,"fork-lock"))fork_test(NULL);
    if(!strcmp(test,"opaque-cookies")) {
        const unsigned char cookie[4]={0xff,0,0xa5,0x5a};memcpy((unsigned char *)request+4,cookie,4);memcpy(expected,request,20);
    }
    if(!strcmp(test,"allocfail"))allocate_rc=-16;
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
    if(!strcmp(test,"mutated-source"))mutate_source=1;
    if(!strcmp(test,"cleanupfail")) { bad_size=11;cleanup_fail=1; }
    if(allocate_rc || null_allocate || bad_size || alias || bad_source || bad_copy || error_pointer || lose_guard || mutate_request || mutate_source) {
        assert(dispatch(&guard));assert_caller_owned();struct native_cp_movie_format_diagnostic_snapshot s=view();
        assert(s.attempts==1 && s.faults && allocations==1 && unreserves==1);
        assert(s.request_bytes==20 && !memcmp(s.request_wire,expected,20) && s.request_fnv1a32==hash(expected));
        assert(!s.known_field_mask && !s.virtual_fields_readback);
        if(!strcmp(test,"cleanupfail")) {
            assert(s.retained_cleanup && s.reply_free_rc==-23);int result;
            assert(native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,s.retained_cleanup,release_packet,logger,&result)==1 && !result);
            assert(view().faults && view().reply_free_rc==-23 && !view().retained_cleanup);
        }
        allocate_rc=0;assert(dispatch(&guard)==CP_MOVIE_FORMAT_SOURCE_BLOCKED && allocations==1);
        assert(view().faults && view().attempts==1);goto done;
    }
    if(!strcmp(test,"sendfail") || !strcmp(test,"send-cleanupfail") || !strcmp(test,"async-sendfail") || !strcmp(test,"inline-sendfail-free"))send_rc=-17;
    if(!strcmp(test,"send-cleanupfail") || !strcmp(test,"replyfail"))reply_fail=1;
    if(!strcmp(test,"requestfail"))request_fail=1;
    if(!strcmp(test,"inline-free") || !strcmp(test,"fast-free-reuse") || !strcmp(test,"inline-sendfail-free"))inline_free=1;
    if(!strcmp(test,"fast-free-reuse"))reuse_free=1;
    if(!strcmp(test,"reentrant"))reenter=1;
    if(!strcmp(test,"inspect-reentrant"))inspect_reenter=1;
    if(!strcmp(test,"reentrant-free"))reentrant_free=1;
    if(!strcmp(test,"request-reentry"))request_reentry=1;
    if(!strcmp(test,"async-sendfail") || !strcmp(test,"async-success"))async_free=1;
    assert(!dispatch(&guard));struct native_cp_movie_format_diagnostic_snapshot s=view();
    assert(s.attempts==1 && s.requests==1 && s.sender_tid==this_tid() && !held && unreserves==1 && sends==1 && allocations==1);
    check_audit(s);
    if(async_free) {
        assert(s.live_reply && !s.reply_freed && s.send_rc==send_rc);int result=123;unsigned int before=frees;
        assert(native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==CP_MOVIE_FORMAT_SOURCE_BLOCKED && frees==before);
        probe_reentry();assert(allocations==1);
        pthread_mutex_lock(&async_mutex);unblock=1;pthread_cond_broadcast(&async_cond);pthread_mutex_unlock(&async_mutex);
        assert(!pthread_join(worker,NULL));s=view();assert(s.reply_freed && s.faults && !s.ap_consumed);
        if(s.retained_request) { assert(native_cp_movie_format_diagnostic_release_reply(NATIVE_CP_MOVIE_FORMAT_SID,request,release_packet,logger,&result)==1 && !result); }
        goto done;
    }
    if(send_rc) {
        assert(s.faults && s.retained_request && !s.request_freed && !s.queued && s.send_rc==-17);
        if(!strcmp(test,"send-cleanupfail")) { assert(s.live_reply && s.reply_free_rc==-21);consume();assert(view().reply_free_rc==-21); }
        else assert(!s.live_reply);
        int result=123;assert(native_cp_movie_format_diagnostic_release_reply(NATIVE_CP_MOVIE_FORMAT_SID,request,release_packet,logger,&result)==1 && !result);
        assert(view().faults && !view().ap_consumed);goto done;
    }
    if(!strcmp(test,"fork-lock"))fork_test(queued);
    if(!inline_free) {
        assert(!s.ap_consumed && !s.clean_completion && s.live_reply && s.request_freed==(strcmp(test,"requestfail")!=0));
        probe_reentry();assert(allocations==1);
        if(!strcmp(test,"wrong-waiter")) {
            assert(!pthread_create(&worker,NULL,free_in_thread,queued));assert(!pthread_join(worker,NULL));
        } else {
            if(!strcmp(test,"foreign")) {
                void *other=make_packet(FULL_IMAGING_AP,0x90040016u,12);int result=123;
                assert(!native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,other,release_packet,logger,&result) && result==123);destroy(other);
            }
            if(!strcmp(test,"wrong-owner")) {
                int result=123;unsigned int before=frees;
                assert(native_cp_movie_format_diagnostic_release_reply(0x80020003u,queued,release_packet,logger,&result)==1 && result==CP_MOVIE_FORMAT_SOURCE_BLOCKED && frees==before);
            }
            if(!strcmp(test,"altered-wire"))((unsigned char *)queued)[4]^=1;
            if(!strcmp(test,"altered-source"))packet(queued)->source=FULL_IMAGING_AP;
            if(!strcmp(test,"altered-size"))packet(queued)->bytes=11;
            if(reply_fail) {
                int result=123;assert(native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==-21);
                assert(view().live_reply && view().faults);
            }
            consume();
        }
    }
    if(!strcmp(test,"requestfail")) {
        s=view();assert(s.retained_request && s.request_free_rc==-19 && s.faults);
        int result=123;assert(native_cp_movie_format_diagnostic_release_reply(NATIVE_CP_MOVIE_FORMAT_SID,s.retained_request,release_packet,logger,&result)==1 && !result);
        assert(view().request_free_rc==-19);
    }
    int expected_fault=!strcmp(test,"wrong-waiter") || !strcmp(test,"wrong-owner") || !strcmp(test,"replyfail") || !strcmp(test,"requestfail") ||
        !strcmp(test,"reentrant-free") || !strcmp(test,"request-reentry") || !strcmp(test,"altered-wire") || !strcmp(test,"altered-source") || !strcmp(test,"altered-size");
    s=view();assert(s.faults==(unsigned int)expected_fault && s.clean_completion==(unsigned int)!expected_fault);
    if(!expected_fault)check_clean();
    if(!strcmp(test,"double-free")) {
        int result=123;unsigned int before=frees;
        assert(!native_cp_movie_format_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result) && result==123 && frees==before);
    }
    if(reused)assert(!memcmp(reused,(unsigned char[]){0xa5,0xa5,0xa5,0xa5},4));
    probe_reentry();assert(allocations==1 && reserves==1);
    assert(native_cp_movie_format_diagnostic_owner_init()==CP_MOVIE_FORMAT_SOURCE_BLOCKED);
done:
    for(unsigned int i=0;i<16;i++)if(packets[i])free(packets[i]);
    puts("PASS: bounded4000 diagnostic; seven-field audit only; business/CP/EE/frame/capture remain0");return 0;
}
