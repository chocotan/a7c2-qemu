/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-notification-control.h"
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

/* Host unit fixture only: does not execute original AP/CP or real all13. */
struct packet { unsigned int owner,source,bytes;unsigned char body[32]; };
static struct packet *packets[16];
static void *request,*queued_reply,*reused;
static unsigned char expected_request[12];
static unsigned int allocations,sends,reserves,unreserves,ready_calls,held,logs,notice_logs;
static _Atomic unsigned int frees;
static int diag_free=1,all13_clean=1,reserve_rc,allocation_rc,bad_allocation,alias,bad_source,bad_copy;
static int send_rc,request_fail,reply_fail,cleanup_fail,inline_free,reuse_free,reentrant_free,async_free;
static int mutate_request,lose_guard,reenter,inspect_reenter,after_admission_fault,allocate_with_error;
static pthread_t free_thread;
static pthread_mutex_t async_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t async_cond=PTHREAD_COND_INITIALIZER;
static int entered,unblock;
static const struct full_imaging_io io;
static const struct native_cp_notification_guard guard;
static long this_tid(void) { return syscall(SYS_gettid); }
static struct native_cp_notification_snapshot view(void) {
    struct native_cp_notification_snapshot s;native_cp_notification_snapshot(&s);
    assert(!s.native_verified && !s.source_byte1_known && !s.notification_mode && !s.d013_registered);
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
    static struct packet probe={NATIVE_CP_NOTIFICATION_SID,FULL_IMAGING_AP,12,{5,0,0x73,0x40}};
    int rc=123;assert(native_cp_notification_dispatch(NATIVE_CP_NOTIFICATION_SID,probe.body,&io,&guard,1,&rc)==1);
    assert(rc==-1021);
}
static unsigned int size_of(void *p) {
    (void)view();if(inspect_reenter) { inspect_reenter=0;probe_reentry(); }
    return packet(p)->bytes;
}
static unsigned int source_of(void *p) { (void)view();return packet(p)->source; }
static void set_source(void *p,unsigned int source) {
    (void)view();packet(p)->source=bad_source?FULL_IMAGING_AP:source;
    if(bad_copy)((unsigned char *)p)[4]^=0x80;
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    allocations++;(void)view();assert(owner==FULL_IMAGING_AP && bytes==12 && wait==1 && held);
    if(reenter)probe_reentry();
    if(alias) { *out=(unsigned char *)request+(alias==2?1:0);return 0; }
    if(allocation_rc) { *out=NULL;return allocation_rc; }
    *out=make_packet(owner,0,bad_allocation?11u:12u);
    if(mutate_request)((unsigned char *)request)[11]^=1;
    if(lose_guard)diag_free=0;
    return allocate_with_error?-33:0;
}
static void logger(const char *tag,const char *line) {
    struct native_cp_notification_snapshot s=view();logs++;
    assert(strstr(tag,"NATIVE_CP_NOTIFICATION_"));
    assert(strstr(line,"native_verified=0") && strstr(line,"CP_history_verified=0") && strstr(line,"capture=0"));
    assert(strstr(line,"internal_virtual_consumer=1") && strstr(line,"original_OSAL_delivery=0"));
    assert(strstr(line,"source_byte1_known=0") && strstr(line,"virtual_padding=1"));
    if(strstr(tag,"_D018_CONSUMED ")) {
        notice_logs++;assert(s.startup_sticky==1 && s.d018_consumed && s.d018_readback);
    }
    if(after_admission_fault && strstr(tag,"_REQUEST ")) {
        after_admission_fault=0;int rc=0;
        assert(native_cp_notification_release_reply(FULL_IMAGING_AP,request,io.release,logger,&rc)==1 && rc==-1021);
    }
}
static int release_packet(unsigned int owner,void *body) {
    frees++;(void)view();assert(packet(body)->owner==owner);
    if(reenter)probe_reentry();
    if(reentrant_free && body==queued_reply) {
        reentrant_free=0;int rc=0;
        assert(native_cp_notification_release_reply(owner,body,release_packet,logger,&rc)==1 && rc==-1021);
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
    assert(native_cp_notification_release_reply(FULL_IMAGING_AP,body,release_packet,logger,&rc)==1 && !rc);
    return NULL;
}
static int send_packet(unsigned int owner,void *body) {
    struct native_cp_notification_snapshot s=view();sends++;
    assert(owner==FULL_IMAGING_AP && packet(body)->owner==owner && packet(body)->source==NATIVE_CP_NOTIFICATION_SID);
    assert(packet(body)->bytes==12 && body!=request && held && s.busy);
    assert(s.requests==1 && s.sender_tid==this_tid());
    assert(s.startup_sticky==1 && s.d018_consumed==1 && s.d018_readback==1 && notice_logs==1);
    assert(s.d018_source==NATIVE_CP_NOTIFICATION_SID && s.d018_destination==FULL_IMAGING_CP && s.d018_bytes==12);
    assert(!memcmp(s.d018_wire,(unsigned char[]){5,0,0x18,0xd0,0,0,0,0,0,0,0,0},12));
    assert(!memcmp(body,(unsigned char[]){1,0,0x73,0x40},4));
    assert(!memcmp((unsigned char *)body+4,expected_request+4,4));
    assert(!memcmp((unsigned char *)body+8,(unsigned char[]){0,0xf0,0,0},4));
    queued_reply=body;if(reenter)probe_reentry();
    if(inline_free) { int rc;assert(native_cp_notification_release_reply(owner,body,release_packet,logger,&rc)==1 && !rc); }
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
    return diag_free && all13_clean;
}
static const struct full_imaging_io io={allocate,release_packet,set_source,send_packet,size_of,source_of,logger};
static const struct native_cp_notification_guard guard={reserve,unreserve,predecessor_ready};
static int dispatch(const struct native_cp_notification_guard *g) {
    int rc=123;assert(native_cp_notification_dispatch(NATIVE_CP_NOTIFICATION_SID,request,&io,g,1,&rc)==1);return rc;
}
static void make_request(void) {
    request=make_packet(NATIVE_CP_NOTIFICATION_SID,FULL_IMAGING_AP,12);
    memcpy(request,(unsigned char[]){5,0,0x73,0x40,0x27,0,0,0x80,0,0,0,0},12);
    memcpy(expected_request,request,12);
}
static void finish_packets(void) {
    for(unsigned int i=0;i<16;i++)if(packets[i]) { free(packets[i]);packets[i]=NULL; }
}
static void assert_refused(void) {
    struct native_cp_notification_snapshot s=view();
    assert(!s.requests && !s.d018_consumed && !s.d018_readback && !s.startup_sticky && !s.queued);
    assert(!s.retained_request && !s.busy && !s.guard_held && !s.live_reply && !s.ap_consumed && !sends);
    assert(!held && !memcmp(request,expected_request,12));
}
int main(int argc,char **argv) {
    assert(argc==2);const char *test=argv[1];make_request();
    if(strcmp(test,"preinit"))assert(!native_cp_notification_owner_init());
    if(!strcmp(test,"normal") || !strcmp(test,"opaque")) {
        struct native_cp_notification_snapshot s=view();
        assert(s.initialized && s.virtual_mode_policy && s.virtual_padding && !s.startup_sticky && !s.requests);
        assert(s.owner_pid==getpid() && native_cp_notification_owner_init()==-1021);
    }
    if(!strcmp(test,"opaque")) {
        memcpy(request,(unsigned char[]){5,0xc7,0x73,0x40,0xd1,0x7f,0x08,0xfe,0,0xa1,0xb2,0xc3},12);
        memcpy(expected_request,request,12);
    }
    if(!strcmp(test,"default-off") || !strcmp(test,"unrelated") || !strcmp(test,"wrong-type") ||
       !strcmp(test,"other-destination") || !strcmp(test,"short-header")) {
        if(!strcmp(test,"unrelated"))((unsigned char *)request)[2]=0x74;
        if(!strcmp(test,"wrong-type"))((unsigned char *)request)[0]=0;
        if(!strcmp(test,"short-header"))packet(request)->bytes=3;
        memcpy(expected_request,request,12);int rc=123;
        assert(!native_cp_notification_dispatch(!strcmp(test,"other-destination")?FULL_IMAGING_CP:NATIVE_CP_NOTIFICATION_SID,
            request,&io,&guard,!strcmp(test,"default-off")?0:1,&rc) && rc==123);
        assert_refused();goto done;
    }
    if(!strcmp(test,"mode1") || !strcmp(test,"mode2") || !strcmp(test,"unknown-mode"))
        ((unsigned char *)request)[8]=!strcmp(test,"mode1")?1:!strcmp(test,"mode2")?2:255;
    if(!strcmp(test,"badlen"))packet(request)->bytes=11;
    if(!strcmp(test,"long"))packet(request)->bytes=13;
    if(!strcmp(test,"wrong-source"))packet(request)->source=0x80020003u;
    if(!strcmp(test,"diag-missing"))diag_free=0;
    if(!strcmp(test,"all13-missing"))all13_clean=0;
    if(!strcmp(test,"reserve-refused"))reserve_rc=-14;
    if(!strcmp(test,"missing-guard") || !strcmp(test,"guard-incomplete") || !strcmp(test,"preinit") ||
       !strcmp(test,"mode1") || !strcmp(test,"mode2") || !strcmp(test,"unknown-mode") ||
       !strcmp(test,"badlen") || !strcmp(test,"long") || !strcmp(test,"wrong-source") ||
       !strcmp(test,"diag-missing") || !strcmp(test,"all13-missing") || !strcmp(test,"reserve-refused")) {
        memcpy(expected_request,request,12);
        struct native_cp_notification_guard incomplete=guard;incomplete.predecessor_ready=NULL;
        assert(dispatch(!strcmp(test,"missing-guard")?NULL:!strcmp(test,"guard-incomplete")?&incomplete:&guard));
        assert_refused();assert(!allocations);goto done;
    }
    if(!strcmp(test,"allocfail"))allocation_rc=-16;
    if(!strcmp(test,"short-allocation"))bad_allocation=1;
    if(!strcmp(test,"alias"))alias=1;
    if(!strcmp(test,"overlap"))alias=2;
    if(!strcmp(test,"bad-reply-source"))bad_source=1;
    if(!strcmp(test,"bad-reply-copy"))bad_copy=1;
    if(!strcmp(test,"allocation-error-pointer"))allocate_with_error=1;
    if(!strcmp(test,"lost-guard"))lose_guard=1;
    if(!strcmp(test,"mutated-request"))mutate_request=1;
    if(!strcmp(test,"cleanupfail"))bad_allocation=cleanup_fail=1;
    if(!strcmp(test,"allocfail") || !strcmp(test,"short-allocation") || !strcmp(test,"alias") ||
       !strcmp(test,"overlap") || !strcmp(test,"bad-reply-source") || !strcmp(test,"bad-reply-copy") ||
       !strcmp(test,"allocation-error-pointer") || !strcmp(test,"lost-guard") || !strcmp(test,"mutated-request") ||
       !strcmp(test,"cleanupfail")) {
        assert(dispatch(&guard));if(mutate_request)memcpy(expected_request,request,12);
        assert_refused();struct native_cp_notification_snapshot s=view();
        assert(s.faults==(!strcmp(test,"allocfail")?0u:1u));
        assert(allocations==1 && unreserves==1);
        if(cleanup_fail==0 && !strcmp(test,"cleanupfail")) {
            assert(s.retained_cleanup && s.reply_free_rc==-23);int rc=0;
            assert(native_cp_notification_release_reply(FULL_IMAGING_AP,s.retained_cleanup,release_packet,logger,&rc)==1 && !rc);
        }
        goto done;
    }
    if(!strcmp(test,"sendfail") || !strcmp(test,"send-cleanupfail") || !strcmp(test,"async-inflight"))send_rc=-17;
    if(!strcmp(test,"send-cleanupfail"))reply_fail=1;
    if(!strcmp(test,"requestfail"))request_fail=1;
    if(!strcmp(test,"replyfail"))reply_fail=1;
    if(!strcmp(test,"inline-free") || !strcmp(test,"fast-free-reuse"))inline_free=1;
    if(!strcmp(test,"fast-free-reuse"))reuse_free=1;
    if(!strcmp(test,"reentrant"))reenter=1;
    if(!strcmp(test,"inspect-reentrant"))inspect_reenter=1;
    if(!strcmp(test,"reentrant-free"))reentrant_free=1;
    if(!strcmp(test,"async-inflight"))async_free=1;
    if(!strcmp(test,"before-consumer-fault"))after_admission_fault=1;
    assert(!dispatch(&guard));
    struct native_cp_notification_snapshot s=view();
    assert(s.requests==1 && s.sender_tid==this_tid() && !held && unreserves==1);
    assert(!memcmp(s.request_wire,expected_request,12) && s.cookie==(unsigned int)(expected_request[4]|(unsigned int)expected_request[5]<<8|(unsigned int)expected_request[6]<<16|(unsigned int)expected_request[7]<<24));
    if(!strcmp(test,"before-consumer-fault")) {
        assert(s.faults && !s.d018_consumed && !s.d018_readback && !sends && s.retained_request && !s.live_reply);goto done;
    }
    assert(s.d018_readback && s.startup_sticky==1 && s.d018_consumed==1 && sends==1);
    if(async_free) {
        assert(s.live_reply && !s.reply_freed && s.faults && s.send_rc==-17);
        int rc=0;unsigned int before=frees;
        assert(native_cp_notification_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && rc==-1021);
        assert(frees==before);
        pthread_mutex_lock(&async_mutex);unblock=1;pthread_cond_broadcast(&async_cond);pthread_mutex_unlock(&async_mutex);
        assert(!pthread_join(free_thread,NULL));s=view();assert(s.reply_freed && s.faults && !s.ap_consumed);goto done;
    }
    if(send_rc) {
        assert(s.faults && s.retained_request && !s.request_freed && !s.queued && s.send_rc==-17);
        if(!strcmp(test,"send-cleanupfail")) {
            assert(s.live_reply && s.reply_free_rc==-21);int rc;
            assert(native_cp_notification_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && !rc);
        } else assert(!s.live_reply);
        goto done;
    }
    assert(s.queued);if(!inline_free)assert(!s.ap_consumed);
    if(!strcmp(test,"fork-lock")) {
        native_cp_notification_test_hold_lock();pid_t child=fork();assert(child>=0);
        if(!child) {
            alarm(2);struct native_cp_notification_snapshot inherited_view;native_cp_notification_snapshot(&inherited_view);
            assert(inherited_view.faults && inherited_view.owner_pid!=getpid());
            assert(native_cp_notification_owner_init()==-1021);int rc=0;
            assert(native_cp_notification_dispatch(NATIVE_CP_NOTIFICATION_SID,queued_reply,&io,&guard,1,&rc)==1 && rc==-1021);
            assert(native_cp_notification_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && rc==-1021);
            _exit(0);
        }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        native_cp_notification_test_drop_lock();
    }
    if(!inline_free) {
        if(!strcmp(test,"wrong-waiter")) {
            assert(!pthread_create(&free_thread,NULL,free_in_thread,queued_reply));assert(!pthread_join(free_thread,NULL));
        } else {
            int rc=123;
            if(!strcmp(test,"foreign")) {
                void *p=make_packet(FULL_IMAGING_AP,NATIVE_CP_NOTIFICATION_SID,12);
                assert(!native_cp_notification_release_reply(FULL_IMAGING_AP,p,release_packet,logger,&rc));destroy(p);
            }
            if(!strcmp(test,"wrong-owner")) {
                unsigned int before=frees;
                assert(native_cp_notification_release_reply(0x80020003u,queued_reply,release_packet,logger,&rc)==1 && rc==-1021);
                assert(frees==before && view().live_reply);
            }
            if(!strcmp(test,"altered-wire"))((unsigned char *)queued_reply)[4]^=1;
            if(!strcmp(test,"altered-source"))packet(queued_reply)->source=FULL_IMAGING_AP;
            if(!strcmp(test,"altered-size"))packet(queued_reply)->bytes=11;
            assert(native_cp_notification_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1);
            if(reply_fail==0 && !strcmp(test,"replyfail")) {
                assert(rc==-21 && view().faults && view().live_reply);
                assert(native_cp_notification_release_reply(FULL_IMAGING_AP,queued_reply,release_packet,logger,&rc)==1 && !rc);
            } else assert(!rc);
        }
    }
    s=view();assert(s.reply_freed && !s.live_reply);
    assert(s.reply_free_destination==FULL_IMAGING_AP);
    if(!strcmp(test,"requestfail")) {
        assert(s.request_free_rc==-19 && s.retained_request && s.faults);int rc;
        assert(native_cp_notification_release_reply(NATIVE_CP_NOTIFICATION_SID,s.retained_request,release_packet,logger,&rc)==1 && !rc);
    }
    int expected_fault=!strcmp(test,"wrong-waiter") || !strcmp(test,"wrong-owner") || !strcmp(test,"replyfail") ||
        !strcmp(test,"requestfail") || !strcmp(test,"reentrant-free") || !strcmp(test,"altered-wire") ||
        !strcmp(test,"altered-source") || !strcmp(test,"altered-size");
    s=view();assert(s.faults==(unsigned int)expected_fault && s.ap_consumed==(unsigned int)!expected_fault);
    if(!expected_fault) {
        assert(s.clean_completion && s.waiter_tid==s.sender_tid && s.request_freed && s.reply_freed);
        assert(s.reply_free_bytes==12 && s.reply_free_source==NATIVE_CP_NOTIFICATION_SID);
        assert(!memcmp(s.freed_reply_wire,s.reply_wire,12));
    }
    if(reused)assert(!memcmp(reused,(unsigned char[]){0xa5,0xa5,0xa5,0xa5},4));
    {
        void *prior=request;make_request();assert(dispatch(&guard)==-1021);request=prior;
        assert(view().requests==1 && view().startup_sticky==1 && view().notification_mode==0);
        assert(native_cp_notification_owner_init()==-1021);
    }
done:
    finish_packets();puts("PASS: virtual mode0/D018 fixture; real AP/all13/CP/capture unverified");return 0;
}
