/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#ifndef HOST_TEST
#error Host actual-Core fixture only
#endif
#include "functional-still-format.h"
#include "cp-capture-format.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "OSAL envelope");
static const unsigned char first_m[24] = {5,0,0x2d,0x40,0x26,0,0,0x80,2,0,1,1,1,1,1,0,1,1,1,1,1,0,0,0};
static const unsigned char second_l[24] = {5,0,0x2d,0x40,0x3b,0,0,0x80,2,0,0,1,0,1,0,0,0,1,0,1,0,0,0,0};
static const unsigned char route[16] = {1,5,5,0xad,2,0xb1,0xb2,0xb3,0xb4,0xb5,0xb6,0xb7,0xb8,0,0,0};
static const uint64_t instance = UINT64_C(0xa7402d);
static struct fcam_model *model;
static const char *scenario;
static struct {
    void *request, *ack, *queued, *received;
    struct message *pool;
    unsigned int pool_live, diagnostic, held, active, ready_calls, callbacks, records;
    unsigned int init_calls, state_calls, calls, allocations, sends, request_frees, ack_frees, free_calls;
    int *dispatch_result;
    uint64_t ticket, previous_ticket;
    unsigned char wire[24], expected_reply[12], authentic[176];
    unsigned int bytes, caller;
} c;
static int is(const char *name) { return !strcmp(scenario, name); }
static long tid(void) { return syscall(SYS_gettid); }
static uint32_t u32(const unsigned char *p) { return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p+4)<<32; }
static uint64_t fnv(const void *ptr, size_t n) {
    const unsigned char *p = ptr; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i=0; i<n; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static struct functional_still_format_snapshot owner(void) {
    struct functional_still_format_snapshot s; functional_still_format_snapshot(&s);
    assert(s.owner_pid == getpid() && s.functional_only && s.initialized);
    assert(!s.original_ap_verified && !s.original_cp && !s.physical_asic_verified && !s.physical_cp_rtos_verified &&
        !s.original_selector_verified && !s.capture_verified);
    return s;
}
static void callback(void) { (void)owner(); c.callbacks++; }
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p - 24); }
static void *message(unsigned int n, unsigned int src) {
    struct message *m;
    if (!c.diagnostic && is("address-reuse")) {
        assert(!c.pool_live); if (!c.pool) c.pool = malloc(sizeof *m + 32);
        m = c.pool; c.pool_live = 1;
    } else m = malloc(sizeof *m + 32);
    assert(m); memset(m, 0, sizeof *m + 32); m->size=n; m->source=src; return m->body;
}
static void destroy(void *p) {
    if (envelope(p) == c.pool) { assert(c.pool_live); c.pool_live=0; }
    else free(envelope(p));
}
static unsigned int size(void *p) { callback(); return envelope(p)->size; }
static unsigned int source(void *p) { callback(); return envelope(p)->source; }
static void set_source(void *p, unsigned int src) {
    callback(); envelope(p)->source=src;
    if (!c.diagnostic && is("reply-readback")) ((unsigned char *)p)[7] ^= 1;
}
static void record(const char *tag, const char *text) {
    callback(); assert(tag && text); c.records++;
    if (!c.diagnostic) printf("owner_log %s%s\n", tag, text);
}
static void core_state(unsigned char out[128]) {
    struct fcam_exec_result r={0}; assert(!fcam_model_request(model, FCAM_OP_STATE, NULL, 0, out, 128, &r));
    assert(r.used==128 && !r.token && !r.total && !r.offset);
}
static struct fcam_frame_proof proof(void) {
    struct fcam_frame_proof p; assert(!fcam_model_proof_snapshot(model,&p,sizeof p)); return p;
}
static void hex(const void *ptr, size_t n) { const unsigned char *p=ptr; for(size_t i=0;i<n;i++) printf("%02x",p[i]); }
static void verify_core(const unsigned char before[128], const struct fcam_frame_proof *old, const unsigned char out[176]) {
    unsigned char after[128]; core_state(after); const struct fcam_frame_proof p=proof();
    assert(p.version==1 && p.struct_bytes==sizeof p && p.opcode==13 && p.consumer_kind==4 && p.serial==old->serial+1);
    assert(p.model_instance==instance && p.model_lifetime==old->model_lifetime && p.owner_pid==(uint64_t)getpid());
    assert(p.config_generation==u64(before+56)+1 && p.config_generation==u64(after+56));
    assert(p.frame_generation==u64(before+112)+1 && p.frame_generation==u64(after+112));
    assert(!memcmp(before,after,56) && !memcmp(before+80,after+80,32));
    assert(p.lease_generation>old->lease_generation && p.packet_generation==old->packet_generation);
    assert(p.width==640 && p.height==480 && p.stride==1920 && p.active_bytes==921600);
    assert(p.source_fnv1a64 && p.source_fnv1a64==p.consumer_before_fnv1a64 && p.source_fnv1a64==p.consumer_after_fnv1a64);
    assert(p.render_observed && p.consumer_entered && p.consumer_returned && p.retired && !p.encoder_consumed);
    assert(p.source_state==3 && p.consumer_before_state==4 && p.consumer_after_state==4 && p.final_state==1);
    assert(!p.render_status && !p.consumer_status && !p.retire_status && !p.operation_status && !p.encoded_bytes && !p.result_token);
    assert(p.result_bytes==176 && p.result_fnv1a64==fnv(out,176) && p.encoded_fnv1a64==fnv("",0));
    assert(p.after.rendered==p.before.rendered+1 && p.after.consumed==p.before.consumed+1 && p.after.retired==p.before.retired+1);
    assert(p.after.jpeg_encoded==p.before.jpeg_encoded && p.after.video_encoded==p.before.video_encoded);
    printf("core before128=");hex(before,128);printf(" after128=");hex(after,128);printf(" result176=");hex(out,176);
    printf(" proof_consumer=%llu proof_bytes=%llu proof_fnv=%016llx token=0 previous_lease=%llu lease=%llu previous_serial=%llu serial=%llu\n",
        (unsigned long long)p.consumer_kind,(unsigned long long)p.result_bytes,(unsigned long long)p.result_fnv1a64,
        (unsigned long long)old->lease_generation,(unsigned long long)p.lease_generation,(unsigned long long)old->serial,(unsigned long long)p.serial);
}
/* shortcut: direct host transport; the actual mailbox and original AP hooks belong to parent integration. */
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *input, size_t n,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    callback(); assert(c.held && c.request && origin && output && result);
    assert(origin->source==0x80020002 && origin->destination==0x90030001 && origin->command==0x402d &&
        origin->bytes==24 && origin->wire_fnv1a64==fnv(c.wire,24));
    if (op==FCAM_OP_STATE) { c.state_calls++; assert(!input && !n && capacity==128); }
    else { assert(op==13 && n==16 && capacity==176 && !memcmp(input,fcam_still_format_initial,16)); c.calls++; }
    unsigned char before[128]; core_state(before); const struct fcam_frame_proof old=proof();
    struct fcam_exec_result actual={0}; int rc=fcam_model_request(model,op,input,n,output,capacity,&actual);
    assert(!rc && actual.used==capacity && !actual.token && !actual.total && !actual.offset);
    *result=(struct fcam_bridge_result){actual.used,actual.used,instance,actual.token}; unsigned char *out=output;
    if (op==2) {
        if (is("state-cap")) out[4]^=1;
        if (is("state-token")) result->result_token=1;
        if (is("state-max")) memset(out+56,0xff,8);
        if (is("state-short") || (is("repeat-state-fail") && c.calls)) result->used=127;
        if (is("state-canary")) out[128]^=1;
        if (is("state-instance")) result->model_instance++;
    } else {
        verify_core(before,&old,out); memcpy(c.authentic,out,176);
        if (!strncmp(scenario,"mutate-",7)) { unsigned long at=strtoul(scenario+7,NULL,10); assert(at<176); out[at]^=1; }
        if (is("class7")) out[96]=7;
        if (is("result168")) result->used=result->required=168;
        if (is("token")) result->result_token=3;
        if (is("instance")) result->model_instance++;
        if (is("required")) result->required=177;
        if (is("bridge-error")) return -EIO;
        if (is("format-canary")) out[176]^=1;
    }
    return rc;
}
static int allocate(unsigned int dst, void **out, unsigned int n, unsigned int option) {
    callback(); assert(dst==0x80020002 && n==12 && option==1 && !c.ack); c.allocations++;
    if (!c.diagnostic) {
        struct functional_still_format_snapshot s=owner(); assert(s.model_complete && s.leases[0].freed && !c.request);
        if (is("alloc-null")) return -ENOMEM;
        if (is("alloc-alias")) { *out=c.dispatch_result; return 0; }
        if (is("alloc-overflow")) { *out=(void *)(UINTPTR_MAX-4); return 0; }
    }
    *out=c.ack=message(n,0); return !c.diagnostic && is("alloc-error-pointer") ? -ENOMEM : 0;
}
static int real_free(unsigned int dst, void *p) {
    callback(); c.free_calls++;
    if (p==c.request) {
        assert(dst==0x90030001 && envelope(p)->size==c.bytes && envelope(p)->source==c.caller && !memcmp(p,c.wire,c.bytes));
        if (!c.diagnostic) {
            struct functional_still_format_snapshot s=owner(); assert(s.model_complete && s.leases[0].releasing && !c.ack);
            if (is("request-free")) return -EIO;
        }
        c.request=NULL; c.request_frees++;
    } else {
        assert(p==c.ack && dst==0x80020002 && !memcmp(p,c.expected_reply,12));
        if (!c.diagnostic) {
            struct functional_still_format_snapshot s=owner(); assert(s.leases[1].received && s.leases[1].releasing && s.leases[1].sender_tid==tid());
            if (is("reply-free")) return -EIO;
        }
        c.ack=c.queued=c.received=NULL; c.ack_frees++;
    }
    destroy(p); return 0;
}
static int receive_rc;
static void *receiver(void *unused) {
    (void)unused; c.received=c.queued; assert(c.received);
    unsigned int src=source(c.received), n=size(c.received);
    if (is("receive-source")) src++;
    if (is("receive-size")) n++;
    if (is("receive-wire")) ((unsigned char *)c.received)[4]^=1;
    receive_rc=functional_still_format_observe_receive_cycle(0x80020002,c.received,src,n,c.ticket);
    return NULL;
}
static void observed(void) {
    pthread_t thread; assert(!pthread_create(&thread,NULL,receiver,NULL)); assert(!pthread_join(thread,NULL));
    if (!strncmp(scenario,"receive-",8)) assert(receive_rc==-EPROTO);
    else { assert(receive_rc==1); assert(owner().leases[1].receiver_tid!=owner().leases[1].sender_tid); }
}
static int sender_free(void) {
    int rc=999; assert(functional_still_format_release_cycle(0x80020002,c.ack,real_free,record,&rc,c.ticket)==1); return rc;
}
static int send(unsigned int dst, void *p) {
    callback(); assert(dst==0x80020002 && p==c.ack && !memcmp(p,c.expected_reply,12)); c.sends++; c.queued=p;
    if (!c.diagnostic) {
        struct functional_still_format_snapshot s=owner(); c.ticket=s.cycle;
        assert(!c.request && s.leases[0].freed && s.leases[1].send_inflight && !s.ap_consumed);
        if (is("inline") || is("inline-send-error")) {
            observed(); assert(!sender_free()); s=owner(); assert(!s.ap_consumed && s.leases[1].freed && s.leases[1].send_inflight);
            puts("inline freed=1 consumed_before_send_return=0");
        }
    }
    return !c.diagnostic && (is("send-error") || is("inline-send-error")) ? -EIO : 0;
}
static const struct full_imaging_io io;
static const struct native_cp_state_publication_guard guard;
static int reserve(void) { callback(); assert(!c.held); c.held=1; return 0; }
static void unlock(void) { callback(); assert(c.held); c.held=0; }
static int ready(void) {
    callback(); assert(c.held); if (c.diagnostic) return 1;
    c.ready_calls++;
    struct native_cp_capture_format_diagnostic_snapshot d; native_cp_capture_format_diagnostic_snapshot(&d);
    if (is("predecessor") || !d.clean_completion || !d.ap_consumed || d.requests!=1 || d.faults || d.busy ||
        d.retained_request || d.live_reply || d.retained_cleanup || !c.active) return 0;
    const struct fcam_frame_proof p=proof();
    assert(p.model_instance==instance && p.retired && !p.operation_status && p.width==640 && p.height==480);
    if ((is("torn-preflight") && c.ready_calls==1) || (is("state-torn") && c.ready_calls==2) ||
        (is("torn-consumed") && c.ready_calls==3)) ((unsigned char *)c.request)[23]^=1;
    if (is("reentrant")) {
        int rc=999;
        assert(functional_still_format_dispatch(0x90030001,c.request,&io,&guard,1,&rc)==1 && rc==-EBUSY);
    }
    return 1;
}
static const struct full_imaging_io io={allocate,real_free,set_source,send,size,source,record};
static const struct native_cp_state_publication_guard guard={reserve,unlock,ready};
static const struct native_cp_capture_format_diagnostic_guard diagnostic_guard={reserve,unlock,ready};
static void prepare(const unsigned char wire[24], unsigned int cookie) {
    assert(!c.request && !c.ack); c.ready_calls=0; c.ticket=0; c.bytes=24; c.caller=0x80020002;
    memcpy(c.wire,wire,24); if (cookie) c.wire[4]=(unsigned char)cookie;
    c.request=message(24,c.caller); memcpy(c.request,c.wire,24);
    memcpy(c.expected_reply,(unsigned char[12]){1,0,0x2d,0x40,0,0,0,0,0,0xf0,0,0},12); memcpy(c.expected_reply+4,c.wire+4,4);
}
static void diagnostic_first(void) {
    c.diagnostic=1; assert(!native_cp_capture_format_diagnostic_owner_init()); prepare(first_m,0);
    int rc=999; assert(native_cp_capture_format_diagnostic_dispatch(0x90030001,c.request,&io,&diagnostic_guard,1,&rc)==1 && !rc);
    assert(!c.request && c.ack);
    assert(native_cp_capture_format_diagnostic_release_reply(0x80020002,c.ack,real_free,record,&rc)==1 && !rc);
    struct native_cp_capture_format_diagnostic_snapshot d; native_cp_capture_format_diagnostic_snapshot(&d);
    assert(d.requests==1 && d.clean_completion && d.ap_consumed && !d.faults && !d.retained_request && !d.live_reply);
    prepare(second_l,0);
    assert(native_cp_capture_format_diagnostic_dispatch(0x90030001,c.request,&io,&diagnostic_guard,1,&rc)==1 && rc==-1021);
    destroy(c.request); c.request=NULL; c.diagnostic=0; puts("diagnostic first_M_clean=1 second_L_blocked=-1021 unchanged_one_shot=1");
}
static void setup_core(void) {
    model=fcam_model_create(instance); assert(model);
    if (is("default-off") || is("no-init")) return;
    unsigned char out[176]; struct fcam_exec_result r={0};
    assert(!fcam_model_request(model,FCAM_OP_INIT,NULL,0,out,128,&r)); c.init_calls++;
    assert(proof().opcode==1 && proof().after.rendered==1 && proof().after.retired==1);
    if (is("no-active")) return;
    assert(!fcam_model_request(model,FCAM_OP_VDF_PATH,route,16,out,160,&r));
    assert(r.used==160 && !r.token && u32(out+108)==1 && u32(out+116)==1 && !memcmp(out+128,route,16)); c.active=1;
}
static void unchanged(const struct functional_still_format_snapshot *before) {
    struct functional_still_format_snapshot after=owner(); assert(!memcmp(before,&after,sizeof after));
}
static void *bad_free(void *unused) { (void)unused; assert(sender_free()==-EPROTO); return NULL; }
static void cycle(unsigned int cookie) {
    prepare(second_l,cookie);
    const unsigned int calls=c.calls, states=c.state_calls, allocations=c.allocations, frees=c.free_calls;
    unsigned char before[128]; core_state(before); struct fcam_frame_proof old=proof();
    if (is("old-M")) memcpy(c.request,first_m,24);
    if (!strncmp(scenario,"body-",5)) { unsigned long at=strtoul(scenario+5,NULL,10); assert(at<14); ((unsigned char *)c.request)[8+at]^=1; }
    if (is("opaque")) { ((unsigned char *)c.request)[1]=0xe7; ((unsigned char *)c.request)[22]=0xab; ((unsigned char *)c.request)[23]=0xcd; }
    if (is("short")) envelope(c.request)->size=23;
    if (is("long")) envelope(c.request)->size=25;
    if (is("source")) envelope(c.request)->source++;
    if (is("type")) ((unsigned char *)c.request)[0]=4;
    if (is("command")) ((unsigned char *)c.request)[2]^=1;
    memcpy(c.wire,c.request,24);
    const int pre=is("old-M") || !strncmp(scenario,"body-",5) || is("short") || is("long") || is("source") ||
        is("default-off") || is("predecessor") || is("no-init") || is("no-active") || is("type") || is("command") || is("torn-preflight");
    int rc=999; c.dispatch_result=&rc;
    int handled=functional_still_format_dispatch(is("destination")?0x90030002:0x90030001,c.request,&io,&guard,!is("default-off"),&rc);
    struct functional_still_format_snapshot s=owner(); assert(!s.busy && !s.guard_held && !c.held);
    if (pre || is("destination")) {
        assert(c.calls==calls && c.state_calls==states && c.allocations==allocations && c.free_calls==frees && c.request);
        assert(!handled || rc<0); unsigned char after[128]; core_state(after); assert(!memcmp(before,after,128));
        const struct fcam_frame_proof p=proof(); assert(!memcmp(&old,&p,sizeof p));
        puts("preflight frame_delta=0 ownership_delta=0 request_free_delta=0 ack_delta=0 caller_owned=1");
    } else if (!strncmp(scenario,"state-",6) || (is("repeat-state-fail") && c.calls==calls)) {
        assert(handled==1 && rc<0 && c.calls==calls && c.state_calls==states+1 && c.request && s.faults && !s.request_owned);
        assert(c.allocations==allocations && c.free_calls==frees);
        assert(!s.request_owned && !s.ap_consumed && !s.operation_attempted && !s.retained && s.cycle==c.calls+1);
        unsigned char after[128]; core_state(after); assert(!memcmp(before,after,128));
        puts("state_refused op13_delta=0 ownership_delta=0 frame_delta=0");
    } else if (!strncmp(scenario,"mutate-",7) || is("class7") || is("result168") || is("token") || is("instance") ||
        is("required") || is("bridge-error") || is("format-canary") || is("torn-consumed")) {
        assert(handled==1 && rc<0 && c.calls==calls+1 && c.request && s.faults && !s.request_owned && s.operation_attempted);
        assert(c.allocations==allocations && c.free_calls==frees && !s.ap_consumed);
        assert(proof().frame_generation==old.frame_generation+1);
        printf("refused rc=%d actual_core_committed=1 frame_delta=1 caller_owned=1 ack_delta=0 request_free_delta=0\n",rc);
    } else {
        assert(handled==1 && !rc && s.request_owned && s.model_complete && c.calls==calls+1 && c.state_calls==states+1);
        assert(!memcmp(s.original_wire,c.wire,24) && s.actual_origin_fnv==fnv(c.wire,24) && !memcmp(s.canonical16,fcam_still_format_initial,16));
        assert(!memcmp(s.model_result,c.authentic,176));
        if (is("address-reuse")) assert(c.ack==c.pool->body);
        if (c.ack && !s.faults && !is("inline") && !is("inline-send-error")) {
            if (is("busy")) {
                const struct functional_still_format_snapshot snap=owner(); const unsigned int count=c.calls;
                void *p=message(24,0x80020002); memcpy(p,second_l,24); int blocked=999;
                assert(functional_still_format_dispatch(0x90030001,p,&io,&guard,1,&blocked)==1 && blocked==-EBUSY);
                unchanged(&snap); assert(c.calls==count); destroy(p);
            }
            if (is("stale") || is("address-reuse") || is("repeat")) {
                struct functional_still_format_snapshot snap=owner(); int stale=999;
                assert(functional_still_format_observe_receive_cycle(0x80020002,c.ack,0x90030001,12,c.previous_ticket)==-ESTALE);
                assert(functional_still_format_release_cycle(0x80020002,c.ack,real_free,record,&stale,c.previous_ticket)==1 && stale==-ESTALE); unchanged(&snap);
                if (s.cycle>1) {
                    assert(functional_still_format_observe_receive(0x80020002,c.ack,0x90030001,12)==-ESTALE);
                    assert(functional_still_format_release(0x80020002,c.ack,real_free,record,&stale)==1 && stale==-ESTALE); unchanged(&snap);
                }
            }
            if (!is("no-receive")) observed();
            if (is("wrong-free-thread")) { pthread_t t; assert(!pthread_create(&t,NULL,bad_free,NULL)); assert(!pthread_join(t,NULL)); }
            else if (strncmp(scenario,"receive-",8)) assert(sender_free()==(is("reply-free")?-EIO:is("no-receive")?-EPROTO:0));
        }
        s=owner();
        const int failed=is("request-free") || is("reply-free") || is("alloc-null") || is("alloc-alias") || is("alloc-overflow") ||
            is("alloc-error-pointer") || is("reply-readback") || is("send-error") || is("inline-send-error") || is("wrong-free-thread") ||
            is("no-receive") || !strncmp(scenario,"receive-",8);
        assert(s.faults==(unsigned int)failed && s.ap_consumed==(unsigned int)!failed);
        if (!failed) {
            assert(s.leases[0].freed && s.leases[1].freed && s.leases[1].received && s.leases[1].consumed && !s.retained);
            assert(s.leases[1].free_tid==s.leases[1].sender_tid && s.leases[1].receiver_tid!=s.leases[1].sender_tid);
            int stale=999; assert(!functional_still_format_release_cycle(0x80020002,(void *)(uintptr_t)0x1230,real_free,record,&stale,s.cycle));
            c.previous_ticket=s.cycle;
        }
        printf("lifecycle cycle=%llu requests=%u completed=%u consumed=%u faults=%u retained=%u request_free=%u reply_free=%u sender=%ld receiver=%ld free_tid=%ld wire24=",
            (unsigned long long)s.cycle,s.requests,s.completed_cycles,s.ap_consumed,s.faults,s.retained,s.leases[0].freed,s.leases[1].freed,
            s.leases[1].sender_tid,s.leases[1].receiver_tid,s.leases[1].free_tid);hex(s.original_wire,24);printf(" reply12=");hex(s.reply_wire,12);putchar('\n');
    }
    s=owner();
    if (s.faults) {
        const unsigned int count=c.calls, free_count=c.free_calls, alloc_count=c.allocations;
        void *p=message(24,0x80020002); memcpy(p,second_l,24); int blocked=999;
        assert(functional_still_format_dispatch(0x90030001,p,&io,&guard,1,&blocked)==1 && blocked<0);
        unchanged(&s); assert(c.calls==count && c.free_calls==free_count && c.allocations==alloc_count); destroy(p);
        if (s.request_owned && (c.request || c.ack)) {
            if (c.request) {
                int *aliased=(int *)(void *)((unsigned char *)c.request+20);
                assert(!functional_still_format_release_cycle(0x90030001,c.request,real_free,record,aliased,s.cycle));
                assert(!memcmp(c.request,c.wire,24)); unchanged(&s);
            }
            int retry=999; void *retained=c.request?c.request:c.ack;
            assert(functional_still_format_release_cycle(c.request?0x90030001:0x80020002,retained,real_free,record,&retry,s.cycle)==1 && retry<0);
            unchanged(&s); assert(c.free_calls==free_count);
        }
        puts("sticky implicit_retry=0 snapshot_unchanged=1");
    }
    if (c.request) { destroy(c.request); c.request=NULL; }
    if (c.ack) { destroy(c.ack); c.ack=c.received=c.queued=NULL; }
    unchanged(&s);
}
static void fork_check(void) {
    functional_still_format_test_hold_lock(); pid_t child=fork(); assert(child>=0);
    if (!child) {
        struct functional_still_format_snapshot s; functional_still_format_snapshot(&s); assert(s.faults && s.owner_pid!=getpid());
        assert(functional_still_format_owner_init()==-EXDEV);
        unsigned char p[24]; memcpy(p,second_l,24); int rc=999;
        assert(functional_still_format_dispatch(0x90030001,p,&io,&guard,1,&rc)==1 && rc==-EXDEV);
        assert(functional_still_format_observe_receive(0x80020002,p,0x90030001,12)==-EXDEV);
        assert(functional_still_format_release(0x80020002,p,real_free,record,&rc)==1 && rc==-EXDEV); _exit(0);
    }
    functional_still_format_test_drop_lock(); int status=0; assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    puts("fork rejected_before_inherited_lock=1");
}
static void pointer_boundaries(void) {
    const struct functional_still_format_snapshot before=owner(); const unsigned int callbacks=c.callbacks;
    int rc=999;
    assert(!functional_still_format_dispatch(0x90030001,(void *)(UINTPTR_MAX-2),&io,&guard,1,&rc) && rc==999);
    assert(c.callbacks==callbacks); unchanged(&before);
    void *request=message(24,0x80020002); memcpy(request,second_l,24);
    assert(!functional_still_format_dispatch(0x90030001,request,&io,&guard,1,(int *)(void *)((unsigned char *)request+8)));
    assert(!memcmp(request,second_l,24)); unchanged(&before); destroy(request);
    puts("boundaries overflow_no_callback=1 alias_unchanged=1");
}
int main(int argc, char **argv) {
    assert(argc==2); scenario=argv[1]; setvbuf(stdout,NULL,_IONBF,0);
    assert(!functional_still_format_owner_init()); assert(functional_still_format_owner_init()==-EALREADY);
    const struct functional_still_format_snapshot initial=owner(); assert(!initial.cycle && !initial.operation_attempted && !initial.requests);
    diagnostic_first(); setup_core();
    if (is("fork")) fork_check();
    else if (is("pointer-boundaries")) pointer_boundaries();
    else {
        cycle(0);
        if (is("repeat") || is("same-cookie") || is("address-reuse") || is("repeat-state-fail")) cycle(is("same-cookie")?0:0x12);
    }
    assert(!c.pool_live); free(c.pool); fcam_model_destroy(model);
    printf("scope scenario=%s calls=%u state_calls=%u init_calls=%u callbacks=%u records=%u original_ap_verified=false vm_verified=false "
        "original_cp=false physical_asic_verified=false physical_cp_rtos_verified=false capture_verified=false media_writes=0\n",
        scenario,c.calls,c.state_calls,c.init_calls,c.callbacks,c.records); return 0;
}
