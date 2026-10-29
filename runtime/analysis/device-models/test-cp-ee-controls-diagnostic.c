/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-ee-controls-diagnostic.h"
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

/* Native cohort/IO mocks test diagnostic transport, never source CP business. */
static const unsigned int opcodes[3]={0x409d,0x4072,0x3012},sizes[3]={12,12,24};
static const unsigned char actual409d[12]={5,0,0x9d,0x40,0x27,0,0,0x80,0,0,0,0};
struct packet { unsigned int owner,source,bytes;unsigned char body[48]; };
static struct packet *packets[32];
static unsigned char expected[3][CP_EE_CONTROLS_REQUEST_MAX];
static void *request,*queued,*reused;
static unsigned int current,allocations,sends,reserves,unreserves,ready_calls,held,logs;
static _Atomic unsigned int frees;
/* all13, samePID,302c,4073,402d,4014,4057 actual free pairs, each own waiter. */
static int predecessors[7]={1,1,1,1,1,1,1};
static int reserve_rc,allocate_rc,null_allocate,bad_size,alias,bad_source,bad_copy,error_pointer;
static int send_rc,request_fail,reply_fail,cleanup_fail,inline_free,reuse_free,reentrant_free,async_free;
static int mutate_request,lose_guard,reenter,inspect_reenter;
static pthread_t worker;
static pthread_mutex_t async_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t async_cond=PTHREAD_COND_INITIALIZER;
static int entered,unblock;
static const struct full_imaging_io io;
static const struct native_cp_ee_controls_diagnostic_guard guard;
static long this_tid(void) { return syscall(SYS_gettid); }
static struct native_cp_ee_controls_diagnostic_snapshot view(void) {
    struct native_cp_ee_controls_diagnostic_snapshot s;native_cp_ee_controls_diagnostic_snapshot(&s);
    assert(s.diagnostic_only && s.virtual_padding);
    assert(!s.business_applied && !s.source_dependencies_closed && !s.published && !s.configured && !s.generation);
    assert(!s.native_cp && !s.ee && !s.frame && !s.capture);
    for(unsigned int i=0;i<3;i++) {
        assert(s.leases[i].opcode==opcodes[i] && s.leases[i].supported && !s.leases[i].source_byte1_known);
        if(i==1)assert(s.leases[i].oneway && !s.leases[i].queued && !s.leases[i].reply_freed && !s.leases[i].ap_consumed && !s.leases[i].waiter_tid && !s.leases[i].live_reply);
    }
    return s;
}
static struct packet *packet(void *p) { return (struct packet *)((unsigned char *)p - offsetof(struct packet,body)); }
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
    current=index;queued=NULL;request=make_packet(NATIVE_CP_EE_CONTROLS_SID,FULL_IMAGING_AP,sizes[index]);
    unsigned char *p=request;
    if(!index)memcpy(p,actual409d,12);
    else { p[0]=index==2?0:5;p[2]=(unsigned char)opcodes[index];p[3]=(unsigned char)(opcodes[index]>>8);p[4]=(unsigned char)(0x27+17*index);p[7]=0x80; }
    if(index==1) { p[8]=0x83;p[9]=0xfe;p[10]=0x5a;p[11]=0xa5; }
    memcpy(expected[index],p,sizes[index]);
}
static void probe_reentry(void) {
    static struct packet probe={NATIVE_CP_EE_CONTROLS_SID,FULL_IMAGING_AP,0,{0}};
    probe.bytes=sizes[current];probe.body[0]=current==2?0:5;
    probe.body[2]=(unsigned char)opcodes[current];probe.body[3]=(unsigned char)(opcodes[current]>>8);
    int result=123;
    assert(native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,probe.body,&io,&guard,1,&result)==1);
    assert(result==CP_EE_CONTROLS_SOURCE_BLOCKED);
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
    allocations++;(void)view();assert(current!=1 && owner==FULL_IMAGING_AP && bytes==12 && wait==1 && held);
    assert(view().leases[current].attempts && !view().leases[current].requests);
    if(reenter)probe_reentry();
    if(alias) { *out=(unsigned char *)request+(alias==2?(int)sizes[current]-1:alias==3?-11:0);return 0; }
    if(allocate_rc || null_allocate) { *out=NULL;return allocate_rc; }
    *out=make_packet(owner,0,bad_size?(unsigned int)bad_size:12u);return error_pointer?-33:0;
}
static void logger(const char *tag,const char *line) {
    struct native_cp_ee_controls_diagnostic_lease s=view().leases[current];logs++;
    assert(strstr(tag,"NATIVE_CP_EE_DIAGNOSTIC_")==tag);
    assert(strstr(line,"diagnostic_only=1 virtual_padding=1 business_applied=0 source_dependencies_closed=0 configured=0 published=0 generation=0 native_cp=0 EE=0 frame=0 capture=0"));
    if(s.oneway)assert(strstr(line,"reply=none freed_reply=none"));
    if(!s.faults && s.requests)assert(s.oneway?frees>0:sends>0);
    if(reenter)probe_reentry();
}
static int release_packet(unsigned int owner,void *p) {
    frees++;(void)view();assert(packet(p)->owner==owner);
    if(current==1 && p==request)assert(!view().leases[1].oneway_consumed && !view().leases[1].virtual_fields_consumed);
    if(reenter)probe_reentry();
    if(reentrant_free && (p==queued || current==1)) {
        reentrant_free=0;int result=123;
        assert(native_cp_ee_controls_diagnostic_release_reply(owner,p,release_packet,logger,&result)==1 && result==CP_EE_CONTROLS_SOURCE_BLOCKED);
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
    assert(native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,p,release_packet,logger,&result)==1 && !result);
    return NULL;
}
static int send_packet(unsigned int owner,void *p) {
    struct native_cp_ee_controls_diagnostic_lease s=view().leases[current];sends++;
    assert(current!=1 && owner==FULL_IMAGING_AP && packet(p)->owner==owner && packet(p)->source==NATIVE_CP_EE_CONTROLS_SID);
    assert(packet(p)->bytes==12 && p!=request && held && s.busy && s.guard_held && s.attempts==1 && s.requests==1 && s.sender_tid==this_tid());
    assert(s.source==FULL_IMAGING_AP && s.request_destination==NATIVE_CP_EE_CONTROLS_SID && s.destination==FULL_IMAGING_AP);
    assert(s.request_bytes==sizes[current] && s.request_fnv1a32==hash(expected[current],sizes[current]));
    assert(!memcmp(s.request_wire,expected[current],sizes[current]));
    assert(!memcmp(p,(unsigned char[]){1,0,(unsigned char)opcodes[current],(unsigned char)(opcodes[current]>>8)},4));
    assert(!memcmp((unsigned char *)p+4,expected[current]+4,4));
    assert(!memcmp((unsigned char *)p+8,(unsigned char[]){0,0xf0,0,0},4));
    queued=p;if(reenter)probe_reentry();
    if(inline_free) { int result;assert(native_cp_ee_controls_diagnostic_release_reply(owner,p,release_packet,logger,&result)==1 && !result); }
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
    if(ready_calls==2 && mutate_request)((unsigned char *)request)[sizes[current]-1]^=1;
    if(ready_calls==2 && lose_guard)predecessors[4]=0;
    for(unsigned int i=0;i<7;i++)if(!predecessors[i])return 0;
    return 1;
}
static const struct full_imaging_io io={allocate,release_packet,set_source,send_packet,size_of,source_of,logger};
static const struct native_cp_ee_controls_diagnostic_guard guard={reserve,unreserve,ready};
static int dispatch(const struct native_cp_ee_controls_diagnostic_guard *g) {
    int result=123;
    assert(native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&io,g,1,&result)==1);
    return result;
}
static void consume(void) {
    int result=123;assert(current!=1);
    assert(native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && !result);
}
static void check_clean(unsigned int index) {
    struct native_cp_ee_controls_diagnostic_lease s=view().leases[index];
    assert(s.attempts==1 && s.requests==1 && s.request_freed && s.clean_completion && !s.faults);
    assert(!s.busy && !s.guard_held && !s.retained_request && !s.live_reply && !s.retained_cleanup);
    assert(!memcmp(s.request_wire,expected[index],sizes[index]) && s.request_fnv1a32==hash(expected[index],sizes[index]));
    assert(s.virtual_field_mask==(index==0?15u:index==1?3u:0u));
    assert(s.virtual_fields_consumed==s.virtual_field_mask && s.virtual_fields_readback==(index!=2));
    for(unsigned int n=0;n<(index==0?4u:index==1?2u:0u);n++)assert(s.virtual_fields[n]==expected[index][8+n] && s.virtual_readback[n]==s.virtual_fields[n]);
    if(index==1)assert(s.oneway_consumed && !s.reply_freed && !s.ap_consumed && !s.queued && !s.waiter_tid && !s.destination);
    else {
        assert(s.queued && s.reply_freed && s.ap_consumed && !s.oneway_consumed && s.waiter_tid==s.sender_tid);
        assert(s.reply_free_destination==FULL_IMAGING_AP && s.reply_free_source==NATIVE_CP_EE_CONTROLS_SID && s.reply_free_bytes==12);
        assert(!memcmp(s.freed_reply_wire,s.reply_wire,12));
    }
}
static void assert_refused(unsigned int index) {
    struct native_cp_ee_controls_diagnostic_snapshot s=view();
    assert(s.requests==index && !s.busy && !s.guard_held && !held && !sends);
    assert(!s.leases[index].retained_request && !s.leases[index].live_reply && !s.leases[index].ap_consumed && !s.leases[index].oneway_consumed);
}
static void *complete_in_thread(void *unused) {
    (void)unused;assert(!dispatch(&guard));if(current!=1 && !inline_free)consume();return NULL;
}
static void fork_test(void *owned) {
    native_cp_ee_controls_diagnostic_test_hold_lock();pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);struct native_cp_ee_controls_diagnostic_snapshot s;native_cp_ee_controls_diagnostic_snapshot(&s);
        assert(s.faults && s.owner_pid!=getpid() && s.diagnostic_only && !s.native_cp && !s.ee && !s.frame && !s.capture);
        assert(native_cp_ee_controls_diagnostic_owner_init()==CP_EE_CONTROLS_SOURCE_BLOCKED);int result=123;
        assert(native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&io,&guard,1,&result)==1 && result==CP_EE_CONTROLS_SOURCE_BLOCKED);
        assert(native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,owned,release_packet,logger,&result)==(owned!=NULL));
        if(owned)assert(result==CP_EE_CONTROLS_SOURCE_BLOCKED);
        _exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    native_cp_ee_controls_diagnostic_test_drop_lock();
}
int main(int argc,char **argv) {
    assert(argc==3 && !strcmp(FULL_CP_EE_DIAGNOSTIC_PROFILE,"diagnostic-cp-ee-controls-v1"));
    unsigned int index=(unsigned int)strtoul(argv[1],NULL,10);assert(index<3);const char *test=argv[2];
    if(strcmp(test,"preinit"))assert(!native_cp_ee_controls_diagnostic_owner_init());
    if(!strcmp(test,"sequence") || !strcmp(test,"sequence-inline") || !strcmp(test,"sequence-thread")) {
        inline_free=!strcmp(test,"sequence-inline");
        for(unsigned int i=0;i<3;i++) {
            make_request(i);
            if(!strcmp(test,"sequence-thread") && i!=1) {
                assert(!pthread_create(&worker,NULL,complete_in_thread,NULL));assert(!pthread_join(worker,NULL));
                assert(view().leases[i].sender_tid!=this_tid());
            } else {
                assert(!dispatch(&guard));
                if(i!=1 && !inline_free) {
                    assert(!view().leases[i].ap_consumed);void *saved=request,*reply=queued;
                    make_request(i==0?1:2);unsigned int before=allocations;
                    assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED && allocations==before);destroy(request);
                    request=saved;queued=reply;current=i;consume();
                }
            }
            check_clean(i);
        }
        assert(view().completed==3 && view().requests==3 && view().attempts==3 && !view().faults && allocations==2 && sends==2 && frees==5);
        for(unsigned int i=0;i<3;i++) { make_request(i);assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED);destroy(request); }
        assert(allocations==2 && sends==2 && reserves==3);goto done;
    }
    if(!strcmp(test,"order") || !strcmp(test,"order-after409d")) {
        unsigned int earlier=!strcmp(test,"order-after409d");
        if(earlier) { make_request(0);assert(!dispatch(&guard));consume();check_clean(0); }
        make_request(index);assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED);
        assert(view().attempts==earlier && reserves==earlier && allocations==earlier && frees==earlier*2 && sends==earlier);goto done;
    }
    /* Earlier local commands really complete; snapshot history is never reset. */
    if(strcmp(test,"preinit"))for(unsigned int i=0;i<index;i++) {
        make_request(i);assert(!dispatch(&guard));if(i!=1)consume();check_clean(i);
    }
    allocations=sends=reserves=unreserves=ready_calls=logs=0;frees=0;make_request(index);
    if(!strcmp(test,"opaque")) {
        unsigned char *p=request;for(unsigned int n=8;n<sizes[index];n++)p[n]=(unsigned char)(0x81+29*n);
        p[1]=0xff;p[4]^=0x81;memcpy(expected[index],p,sizes[index]);
    }
    if(!strcmp(test,"default-off") || !strcmp(test,"enabled-two") || !strcmp(test,"unknown") || !strcmp(test,"wrong-type") || !strcmp(test,"other-destination") || !strcmp(test,"short-header")) {
        if(!strcmp(test,"unknown"))((unsigned char *)request)[2]=0x13;
        if(!strcmp(test,"wrong-type"))((unsigned char *)request)[0]=index==2?5:0;
        if(!strcmp(test,"short-header"))packet(request)->bytes=3;
        int result=123,enabled=!strcmp(test,"default-off")?0:!strcmp(test,"enabled-two")?2:1;
        assert(!native_cp_ee_controls_diagnostic_dispatch(!strcmp(test,"other-destination")?FULL_IMAGING_CP:NATIVE_CP_EE_CONTROLS_SID,request,&io,&guard,enabled,&result) && result==123);
        assert_refused(index);assert(!allocations && !reserves && !frees && !logs);goto done;
    }
    if(!strcmp(test,"all-wrong-types")) {
        unsigned char *p=request;
        for(unsigned int type=0;type<=255;type++)if(type!=(index==2?0u:5u)) {
            p[0]=(unsigned char)type;int result=123;
            assert(!native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&io,&guard,1,&result) && result==123);
        }
        assert_refused(index);assert(!allocations && !sends && !frees && !logs && !reserves);goto done;
    }
    if(!strcmp(test,"3003")) {
        unsigned char *p=request;for(unsigned int n=0;n<24;n++)p[n]=(unsigned char)(0x95+n);
        p[0]=0;p[2]=3;p[3]=0x30;unsigned char copy[24];memcpy(copy,p,24);
        for(unsigned int bytes=0;bytes<=32;bytes++) {
            packet(request)->bytes=bytes;int result=123;
            assert(!native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&io,&guard,1,&result) && result==123);
            assert(!memcmp(request,copy,24));
        }
        assert_refused(index);assert(!allocations && !sends && !frees && !logs && !reserves);goto done;
    }
    if(!strcmp(test,"all-bad-lengths")) {
        for(unsigned int bytes=0;bytes<=CP_EE_CONTROLS_REQUEST_MAX+1;bytes++)if(bytes!=sizes[index]) {
            packet(request)->bytes=bytes;int result=123;
            assert(native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&io,&guard,1,&result)==(bytes>=4));
            assert(result==(bytes>=4?CP_EE_CONTROLS_SOURCE_BLOCKED:123));
        }
        assert_refused(index);assert(!allocations && !reserves);goto done;
    }
    if(!strcmp(test,"missing-io")) {
        for(unsigned int n=0;n<7;n++) {
            if(index==1 && (n==0 || n==2 || n==3))continue;
            struct full_imaging_io partial=io;
            switch(n) { case 0:partial.allocate=NULL;break;case 1:partial.release=NULL;break;case 2:partial.set_source=NULL;break;
                case 3:partial.send=NULL;break;case 4:partial.size=NULL;break;case 5:partial.source=NULL;break;default:partial.record=NULL; }
            int result=123;assert(native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&partial,&guard,1,&result)==(n!=4));
            assert_refused(index);assert(!allocations && !reserves);
        }
        goto done;
    }
    if(!strcmp(test,"missing-guard")) {
        assert(dispatch(NULL)==CP_EE_CONTROLS_SOURCE_BLOCKED);
        for(unsigned int n=0;n<3;n++) {
            struct native_cp_ee_controls_diagnostic_guard partial=guard;
            if(!n)partial.reserve=NULL;else if(n==1)partial.release=NULL;else partial.predecessor_ready=NULL;
            assert(dispatch(&partial)==CP_EE_CONTROLS_SOURCE_BLOCKED);
        }
        assert_refused(index);assert(!allocations && !reserves);goto done;
    }
    if(!strcmp(test,"no-predecessors")) {
        for(unsigned int n=0;n<7;n++) { predecessors[n]=0;assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED);assert_refused(index);predecessors[n]=1; }
        assert(!allocations && reserves==7 && unreserves==7);goto done;
    }
    if(!strcmp(test,"preinit") || !strcmp(test,"wrong-source") || !strcmp(test,"reserve-refused")) {
        if(!strcmp(test,"wrong-source"))packet(request)->source=0x80020003u;
        if(!strcmp(test,"reserve-refused"))reserve_rc=-14;
        assert(dispatch(&guard));assert(!view().leases[index].attempts && !allocations && !sends && !frees && !held);goto done;
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
    if(!strcmp(test,"cleanupfail")) { bad_size=11;cleanup_fail=1; }
    if(allocate_rc || null_allocate || bad_size || alias || bad_source || bad_copy || error_pointer || lose_guard || mutate_request) {
        assert(dispatch(&guard));assert_refused(index);struct native_cp_ee_controls_diagnostic_lease s=view().leases[index];
        assert(s.attempts==1 && s.faults && allocations==(index!=1) && unreserves==1);
        assert(s.request_bytes==sizes[index] && !memcmp(s.request_wire,expected[index],sizes[index]) && s.request_fnv1a32==hash(expected[index],sizes[index]));
        if(!strcmp(test,"cleanupfail")) {
            assert(s.retained_cleanup && s.reply_free_rc==-23);int result;
            assert(native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,s.retained_cleanup,release_packet,logger,&result)==1 && !result);
            assert(view().leases[index].faults && view().leases[index].reply_free_rc==-23);
        }
        allocate_rc=0;unsigned int before=allocations;assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED && allocations==before);
        assert(view().leases[index].faults && view().leases[index].attempts==1);goto done;
    }
    if(!strcmp(test,"sendfail") || !strcmp(test,"send-cleanupfail") || !strcmp(test,"async-inflight"))send_rc=-17;
    if(!strcmp(test,"send-cleanupfail") || !strcmp(test,"replyfail"))reply_fail=1;
    if(!strcmp(test,"requestfail"))request_fail=1;
    if(!strcmp(test,"inline-free") || !strcmp(test,"fast-free-reuse"))inline_free=1;
    if(!strcmp(test,"fast-free-reuse"))reuse_free=1;
    if(!strcmp(test,"reentrant"))reenter=1;
    if(!strcmp(test,"inspect-reentrant"))inspect_reenter=1;
    if(!strcmp(test,"reentrant-free"))reentrant_free=1;
    if(!strcmp(test,"async-inflight") || !strcmp(test,"async-success"))async_free=1;
    if(!strcmp(test,"oneway-minimal-io")) {
        assert(index==1);struct full_imaging_io partial=io;partial.allocate=NULL;partial.send=NULL;partial.set_source=NULL;int result=123;
        assert(native_cp_ee_controls_diagnostic_dispatch(NATIVE_CP_EE_CONTROLS_SID,request,&partial,&guard,1,&result)==1 && !result);
    } else assert(!dispatch(&guard));
    struct native_cp_ee_controls_diagnostic_lease s=view().leases[index];
    assert(s.attempts==1 && s.requests==1 && s.sender_tid==this_tid() && !held && unreserves==1 && sends==(index!=1));
    if(index==1)assert(!allocations && !sends && frees==1);
    if(async_free) {
        assert(s.live_reply && !s.reply_freed && s.send_rc==send_rc);int result=123;unsigned int before=frees;
        assert(native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==CP_EE_CONTROLS_SOURCE_BLOCKED && frees==before);
        void *saved=request,*reply=queued;make_request(index==0?1:2);before=allocations;
        assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED && allocations==before);destroy(request);request=saved;queued=reply;current=index;
        pthread_mutex_lock(&async_mutex);unblock=1;pthread_cond_broadcast(&async_cond);pthread_mutex_unlock(&async_mutex);
        assert(!pthread_join(worker,NULL));s=view().leases[index];assert(s.reply_freed && s.faults && !s.ap_consumed);goto done;
    }
    if(send_rc) {
        assert(s.faults && s.retained_request && !s.request_freed && !s.queued && s.send_rc==-17);
        if(!strcmp(test,"send-cleanupfail")) { assert(s.live_reply && s.reply_free_rc==-21);consume();assert(view().leases[index].reply_free_rc==-21); }
        else assert(!s.live_reply);
        int result=123;assert(native_cp_ee_controls_diagnostic_release_reply(NATIVE_CP_EE_CONTROLS_SID,request,release_packet,logger,&result)==1 && !result);
        assert(view().leases[index].faults && !view().leases[index].ap_consumed);goto done;
    }
    if(!strcmp(test,"fork-lock"))fork_test(index==1?NULL:queued);
    if(index!=1 && !inline_free) {
        if(!strcmp(test,"wrong-waiter") || !strcmp(test,"cross-fault")) {
            assert(!pthread_create(&worker,NULL,free_in_thread,queued));assert(!pthread_join(worker,NULL));
        } else {
            if(!strcmp(test,"foreign")) {
                void *other=make_packet(FULL_IMAGING_AP,0x90040016u,12);int result=123;
                assert(!native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,other,release_packet,logger,&result) && result==123);destroy(other);
            }
            if(!strcmp(test,"wrong-owner")) {
                int result=123;unsigned int before=frees;
                assert(native_cp_ee_controls_diagnostic_release_reply(0x80020003u,queued,release_packet,logger,&result)==1 && result==CP_EE_CONTROLS_SOURCE_BLOCKED && frees==before);
            }
            if(!strcmp(test,"altered-wire"))((unsigned char *)queued)[4]^=1;
            if(!strcmp(test,"altered-source"))packet(queued)->source=FULL_IMAGING_AP;
            if(!strcmp(test,"altered-size"))packet(queued)->bytes=11;
            if(reply_fail) {
                int result=123;assert(native_cp_ee_controls_diagnostic_release_reply(FULL_IMAGING_AP,queued,release_packet,logger,&result)==1 && result==-21);
                assert(view().leases[index].live_reply && view().leases[index].faults);
            }
            consume();
        }
    }
    if(!strcmp(test,"requestfail")) {
        s=view().leases[index];assert(s.retained_request && s.request_free_rc==-19 && s.faults && !s.oneway_consumed);
        void *saved=request,*reply=queued;make_request(index==0?1:2);unsigned int before=allocations;
        assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED && allocations==before);destroy(request);request=saved;queued=reply;current=index;
        int result=123;
        assert(native_cp_ee_controls_diagnostic_release_reply(NATIVE_CP_EE_CONTROLS_SID,s.retained_request,release_packet,logger,&result)==1 && !result);
        assert(view().leases[index].request_free_rc==-19);
        if(index==1)assert(view().leases[index].oneway_consumed && !view().leases[index].ap_consumed);
    }
    int expected_fault=!strcmp(test,"wrong-waiter") || !strcmp(test,"cross-fault") || !strcmp(test,"wrong-owner") || !strcmp(test,"replyfail") ||
        !strcmp(test,"requestfail") || !strcmp(test,"reentrant-free") || !strcmp(test,"altered-wire") || !strcmp(test,"altered-source") || !strcmp(test,"altered-size");
    s=view().leases[index];assert(s.faults==(unsigned int)expected_fault && s.clean_completion==(unsigned int)!expected_fault);
    if(!expected_fault)check_clean(index);
    if(!strcmp(test,"double-free")) {
        int result=123;unsigned int before=frees;void *pointer=index==1?request:queued;
        assert(!native_cp_ee_controls_diagnostic_release_reply(index==1?NATIVE_CP_EE_CONTROLS_SID:FULL_IMAGING_AP,pointer,release_packet,logger,&result) && result==123 && frees==before);
    }
    if(reused)assert(!memcmp(reused,(unsigned char[]){0xa5,0xa5,0xa5,0xa5},4));
    if(!strcmp(test,"cross-fault")) {
        make_request(index==0?1:2);unsigned int before=allocations;
        assert(dispatch(&guard)==CP_EE_CONTROLS_SOURCE_BLOCKED && allocations==before && view().leases[index].faults);
    }
    assert(native_cp_ee_controls_diagnostic_owner_init()==CP_EE_CONTROLS_SOURCE_BLOCKED);
done:
    for(unsigned int i=0;i<32;i++)if(packets[i])free(packets[i]);
    puts("PASS: bounded EE diagnostic; oneway has no ACK; business/CP/EE/frame/capture remain0");return 0;
}
