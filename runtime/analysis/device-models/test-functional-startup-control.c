/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#ifndef HOST_TEST
#error Host actual-Core fixture only
#endif
#include "functional-startup-control.h"
#include "cp-startup-controls-diagnostic.h"
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
static const unsigned char mode[24] = {5,0,0x14,0x40,0x3c,0,0,0x80,0,0,1,0,1,0,0,0,1,0,0,0,0,0,0,0};
static const unsigned char settings[12] = {5,0,0x57,0x40,0x26,0,0,0x80,0,0,0,0};
static const unsigned char route[16] = {1,5,5,0xad,2,0xb1,0xb2,0xb3,0xb4,0xb5,0xb6,0xb7,0xb8,0,0,0};
static const uint64_t instance = UINT64_C(0xa7401457);
static struct fcam_model *model;
static const char *scenario;
static unsigned int variant, armed;
static struct {
    void *request, *ack, *queued;
    struct message *pool;
    unsigned int pool_live, diagnostic, held, ready_calls, callbacks, records;
    unsigned int state_calls, calls, commits, allocations, sends, request_frees, ack_frees, free_calls;
    unsigned int bytes, caller, active;
    int *dispatch_result;
    unsigned char wire[328], expected_reply[12], authentic[192], previous[192];
    struct { int pid; void *pointer; unsigned int dst, cookie; uint64_t cycle; } slot;
    uint64_t previous_ticket;
} c;
static int is(const char *name) { return armed && !strcmp(scenario, name); }
static long tid(void) { return syscall(SYS_gettid); }
static uint32_t u32(const unsigned char *p) { return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p+4)<<32; }
static void put64(unsigned char *p, uint64_t v) { for(size_t i=0;i<8;i++) p[i]=(unsigned char)(v>>(8*i)); }
static uint64_t fnv(const void *ptr, size_t n) {
    const unsigned char *p=ptr; uint64_t h=UINT64_C(14695981039346656037);
    for(size_t i=0;i<n;i++) h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
static struct functional_startup_control_snapshot owner(void) {
    struct functional_startup_control_snapshot s; functional_startup_control_snapshot(&s);
    assert(s.owner_pid==getpid() && s.functional_only && s.initialized);
    assert(!s.original_ap_verified && !s.original_cp && !s.physical_asic_verified && !s.physical_cp_rtos_verified &&
        !s.original_selector_verified && !s.capture_verified && !s.source_dependencies_closed && !s.native_cp && !s.ee);
    return s;
}
static void callback(void) { (void)owner(); c.callbacks++; }
static void unchanged(const struct functional_startup_control_snapshot *s) { const struct functional_startup_control_snapshot now=owner(); assert(!memcmp(s,&now,sizeof now)); }
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p-24); }
static void *message(unsigned int n, unsigned int src) {
    struct message *m;
    if (!c.diagnostic && is("address-reuse")) {
        assert(!c.pool_live); if(!c.pool) c.pool=malloc(sizeof *m+336); m=c.pool; c.pool_live=1;
    } else m=malloc(sizeof *m+336);
    assert(m); memset(m,0,sizeof *m+336); m->size=n; m->source=src; return m->body;
}
static void destroy(void *p) { if(envelope(p)==c.pool) { assert(c.pool_live); c.pool_live=0; } else free(envelope(p)); }
static unsigned int size(void *p) {
    callback();
    if(!c.diagnostic && is("io-faults")) {
        const struct functional_startup_control_snapshot s=owner();
        if((variant==11 && p==c.request && s.leases[0].releasing) ||
           (variant==13 && p==c.ack && s.leases[1].releasing && s.leases[1].received)) return envelope(p)->size+1;
        if(variant==14 && p==c.ack && s.leases[1].releasing && s.leases[1].received) ((unsigned char *)p)[1]^=1;
    }
    return envelope(p)->size;
}
static unsigned int source(void *p) {
    callback();
    if(!c.diagnostic && is("io-faults") && variant==12 && p==c.request && owner().leases[0].releasing) return envelope(p)->source+1;
    return envelope(p)->source;
}
static void set_source(void *p, unsigned int src) {
    callback(); envelope(p)->source=src;
    if(!c.diagnostic && is("io-faults")) {
        if(variant==5) envelope(p)->source++;
        if(variant==6) ((unsigned char *)p)[7]^=1;
        if(variant==7) envelope(p)->size=11;
    }
}
static void record(const char *tag, const char *text) {
    callback(); assert(tag && text); c.records++;
    if(!c.diagnostic) { assert(!strcmp(tag,FUNCTIONAL_STARTUP_CONTROL_LOG_TAG)); printf("owner_log %s%s\n",tag,text); }
}
static struct fcam_frame_proof proof(void) { struct fcam_frame_proof p; assert(!fcam_model_proof_snapshot(model,&p,sizeof p)); return p; }
static void core_state(unsigned char out[128]) {
    struct fcam_exec_result r={0}; assert(!fcam_model_request(model,FCAM_OP_STATE,NULL,0,out,128,&r)); assert(r.used==128 && !r.token && !r.total && !r.offset);
}
static void hex(const void *ptr, size_t n) { const unsigned char *p=ptr; for(size_t i=0;i<n;i++) printf("%02x",p[i]); }
static void verify_core(const unsigned char before[128], const struct fcam_frame_proof *old, const unsigned char input[32], const unsigned char out[192]) {
    unsigned char after[128]; core_state(after); const struct fcam_frame_proof p=proof(); c.commits++;
    assert(p.version==1 && p.struct_bytes==sizeof p && p.opcode==14 && p.consumer_kind==4 && p.serial==old->serial+1);
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
    assert(p.result_bytes==192 && p.result_fnv1a64==fnv(out,192) && p.encoded_fnv1a64==fnv("",0));
    assert(p.after.rendered==p.before.rendered+1 && p.after.consumed==p.before.consumed+1 && p.after.retired==p.before.retired+1);
    assert(p.after.jpeg_encoded==p.before.jpeg_encoded && p.after.video_encoded==p.before.video_encoded);
    assert(!memcmp(out+160,input,32) && u64(input+24)==fnv(before+8,40));
    printf("core before128=");hex(before,128);printf(" after128=");hex(after,128);printf(" input32=");hex(input,32);printf(" result192=");hex(out,192);
    printf(" proof_consumer=4 proof_bytes=192 proof_fnv=%016llx source_fnv=%016llx token=0 previous_lease=%llu lease=%llu previous_serial=%llu serial=%llu\n",
        (unsigned long long)p.result_fnv1a64,(unsigned long long)p.source_fnv1a64,(unsigned long long)old->lease_generation,(unsigned long long)p.lease_generation,
        (unsigned long long)old->serial,(unsigned long long)p.serial);
}
/* shortcut: direct host bridge transport; parent validates mailbox/original AP integration. */
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *input, size_t n,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    callback(); assert(c.held && c.request && origin && output && result);
    assert(origin->source==0x80020002 && origin->destination==0x90030001 && origin->command==(u32(c.wire)&0xffff0000u)>>16 &&
        origin->bytes==c.bytes && origin->wire_fnv1a64==fnv(c.wire,c.bytes));
    if(op==2) { c.state_calls++; assert(!input && !n && capacity==128); }
    else {
        assert(op==14 && n==32 && capacity==192 && fcam_startup_control_validate_basic(input)); c.calls++;
        const struct functional_startup_control_snapshot s=owner(); assert(u64((const unsigned char *)input+24)==fnv(s.model_state+8,40));
    }
    unsigned char before[128]; core_state(before); const struct fcam_frame_proof old=proof();
    struct fcam_exec_result actual={0}; int rc=fcam_model_request(model,op,input,n,output,capacity,&actual);
    *result=(struct fcam_bridge_result){actual.used,actual.used,instance,actual.token}; unsigned char *out=output;
    if(rc) { assert(op==14 && (is("no-active") || is("stale-configfp"))); return rc; }
    assert(actual.used==capacity && !actual.token && !actual.total && !actual.offset);
    if(op==2) {
        if(is("repeat-state-fail") && c.calls) result->used=127;
        if(is("stale-configfp") && !variant) out[16]^=1;
        if(is("state-mutations")) {
            switch(variant) {
            case 0: result->used=127; break; case 1: result->required=129; break; case 2: result->result_token=1; break;
            case 3: result->model_instance++; break; case 4: out[4]^=1; break; case 5: out[0]^=1; break;
            case 6: out[120]=1; break; case 7: out[8]^=1; break; case 8: out[12]^=1; break;
            case 9: memset(out+16,0,4); break; case 10: out[20]=101; break; case 11: out[24]^=1; break;
            case 12: memset(out+28,0,4); break; case 13: memset(out+32,0,8); break; case 14: memset(out+40,0,8); break;
            case 15: out[104]=1; break; case 16: out[108]=1; break; case 17: memset(out+56,0,8); break;
            case 18: memset(out+64,0,8); break; case 19: memset(out+112,0,8); break;
            case 20: put64(out+72,u64(out+64)+1); break; case 21: put64(out+80,u64(out+72)+1); break;
            case 22: put64(out+88,u64(out+72)+1); break; case 23: memset(out+56,0xff,8); break;
            case 24: memset(out+112,0xff,8); break; case 25: memset(out+64,0xff,8); break;
            case 26: memset(out+72,0xff,8); break; case 27: out[128]^=1; break;
            case 28: out[-1]^=1; break; case 29: return -EIO; case 30: return 1;
            case 31: result->used=result->required=0; break; case 32: result->model_instance=0; break;
            default: assert(0);
            }
        }
    } else {
        verify_core(before,&old,input,out); memcpy(c.previous,c.authentic,192); memcpy(c.authentic,out,192);
        if(is("bad-receipt")) { assert(variant<192); if(variant==32) memset(out+32,0,8); else out[variant]^=1; }
        if(is("bad-descriptor")) {
            switch(variant) {
            case 0: out[96]=8; break; case 1: result->used=result->required=176; break; case 2: result->result_token=1; break;
            case 3: result->model_instance++; break; case 4: result->required=193; break; case 5: return 1; default: assert(0);
            }
        }
        if(is("old-proof")) memcpy(out,c.previous,192);
        if(is("canary")) out[variant?192:-1]^=1;
        if(is("bridge-error")) return -EIO;
    }
    return rc;
}
static int allocate(unsigned int dst, void **out, unsigned int n, unsigned int option) {
    callback(); assert(dst==0x80020002 && n==12 && option==1 && !c.ack); c.allocations++;
    if(!c.diagnostic) {
        const struct functional_startup_control_snapshot s=owner(); assert(s.model_complete && s.leases[0].freed && !c.request);
        if(is("io-faults")) {
            if(variant==0) return -ENOMEM;
            if(variant==1) { *out=c.dispatch_result; return 0; }
            if(variant==2) { *out=(void *)(UINTPTR_MAX-4); return 0; }
            if(variant==10) return 0;
        }
    }
    *out=c.ack=message(n,0);
    if(!c.diagnostic && is("io-faults") && variant==4) envelope(c.ack)->size=11;
    return !c.diagnostic && is("io-faults") && variant==3 ? -ENOMEM : 0;
}
static int real_free(unsigned int dst, void *p) {
    callback(); c.free_calls++;
    if(p==c.request) {
        assert(dst==0x90030001 && envelope(p)->size==c.bytes && envelope(p)->source==c.caller && !memcmp(p,c.wire,c.bytes));
        if(!c.diagnostic) {
            const struct functional_startup_control_snapshot s=owner(); assert(s.model_complete && s.leases[0].releasing && !c.ack);
            if(is("io-faults") && variant==8) return -EIO;
        }
        c.request=NULL; c.request_frees++;
    } else {
        assert(p==c.ack && dst==0x80020002 && !memcmp(p,c.expected_reply,12));
        if(!c.diagnostic) {
            const struct functional_startup_control_snapshot s=owner(); assert(s.leases[1].received && s.leases[1].releasing && s.leases[1].sender_tid==tid());
            assert(c.slot.pointer==p && c.slot.pid==getpid() && c.slot.cycle==s.cycle && c.slot.cookie==u32(c.expected_reply+4));
            if(is("io-faults") && variant==9) return -EIO;
            memset(&c.slot,0,sizeof c.slot); /* Real-free0 clears immutable parent slot before owner publication. */
        }
        c.ack=c.queued=NULL; c.ack_frees++;
    }
    destroy(p); return 0;
}
static int receive_rc;
static void *receiver(void *unused) {
    (void)unused; void *p=c.queued; assert(p && c.slot.pointer==p);
    unsigned int src=source(p), n=size(p), dst=c.slot.dst;
    if(is("receive-faults")) {
        if(variant==0) src++;
        if(variant==1) n++;
        if(variant==2) dst++;
        if(variant==3) ((unsigned char *)p)[4]^=1;
    }
    receive_rc=functional_startup_control_observe_receive_cycle(dst,p,src,n,c.slot.cycle);
    if(is("receive-faults") && variant==4) { assert(receive_rc==1); receive_rc=functional_startup_control_observe_receive_cycle(dst,p,src,n,c.slot.cycle); }
    return NULL;
}
static void observed(void) {
    pthread_t t; assert(!pthread_create(&t,NULL,receiver,NULL)); assert(!pthread_join(t,NULL));
    if(is("receive-faults")) assert(receive_rc==-EPROTO);
    else { assert(receive_rc==1); const struct functional_startup_control_snapshot s=owner(); assert(s.leases[1].receiver_tid!=s.leases[1].sender_tid); }
}
static int sender_free(void) {
    int rc=999; assert(functional_startup_control_release_cycle(is("io-faults")&&variant==15?0x80020003:0x80020002,c.ack,real_free,record,&rc,c.slot.cycle)==1); return rc;
}
static int send(unsigned int dst, void *p) {
    callback(); assert(dst==0x80020002 && p==c.ack && !memcmp(p,c.expected_reply,12)); c.sends++; c.queued=p;
    if(!c.diagnostic) {
        const struct functional_startup_control_snapshot s=owner(); assert(!c.request && s.leases[0].freed && s.leases[1].send_inflight && !s.ap_consumed);
        assert(!c.slot.pointer && s.leases[1].pointer==p && s.leases[1].source==0x90030001 && s.leases[1].bytes==12);
        c.slot.pid=getpid(); c.slot.pointer=p; c.slot.dst=dst; c.slot.cycle=s.cycle; c.slot.cookie=u32(c.expected_reply+4);
        if(is("inline") || is("inline-send-error")) {
            observed(); assert(!sender_free()); const struct functional_startup_control_snapshot now=owner();
            assert(!now.ap_consumed && now.leases[1].freed && now.leases[1].send_inflight && !c.slot.pointer);
            puts("inline freed=1 consumed_before_send_return=0");
        }
    }
    return !c.diagnostic && (is("send-error") || is("inline-send-error")) ? -EIO : 0;
}
static void configure(void) {
    unsigned char st[128], config[48]={0}; core_state(st); memcpy(config,st+8,40); config[8]=25; config[12]=73;
    config[16]=0x20; config[17]=3; config[20]=0xc8; config[21]=0; put64(config+24,25000); put64(config+32,2500000);
    struct fcam_exec_result r={0}; assert(!fcam_model_request(model,FCAM_OP_CONFIGURE,config,48,st,128,&r));
    assert(r.used==128 && u32(st+16)==25 && u32(st+20)==73 && u32(st+24)==800 && u32(st+28)==200);
}
static const struct full_imaging_io io;
static const struct native_cp_state_publication_guard guard;
static int reserve(void) { callback(); assert(!c.held); if(is("predecessor") && variant==1) return -EAGAIN; c.held=1; return 0; }
static void unlock(void) { callback(); assert(c.held); c.held=0; }
static int ready(void) {
    callback(); assert(c.held); if(c.diagnostic) return 1; c.ready_calls++;
    struct native_cp_startup_controls_diagnostic_snapshot d; native_cp_startup_controls_diagnostic_snapshot(&d);
    assert(d.requests==2 && d.completed==2 && d.leases[0].ap_consumed && d.leases[2].ap_consumed && !d.faults && !d.busy && !d.guard_held);
    if(is("predecessor") && !variant) return 0;
    if((is("state-torn") && c.ready_calls==2) || (is("torn-consumed") && c.ready_calls==3)) ((unsigned char *)c.request)[4]^=1;
    if(is("guard-torn") && c.ready_calls==3) return 0;
    if(is("stale-configfp") && variant && c.ready_calls==2) configure();
    if(is("reentrant")) { int rc=999; assert(functional_startup_control_dispatch(0x90030001,c.request,&io,&guard,1,&rc)==1 && rc==-EBUSY); }
    if(c.active) { const struct fcam_frame_proof p=proof(); assert(p.model_instance==instance && p.retired && !p.operation_status && p.width==640 && p.height==480); }
    return 1;
}
static const struct full_imaging_io io={allocate,real_free,set_source,send,size,source,record};
static const struct native_cp_state_publication_guard guard={reserve,unlock,ready};
static const struct native_cp_startup_controls_diagnostic_guard old_guard={reserve,unlock,ready};
static void prepare(unsigned int command, uint32_t cookie) {
    assert(!c.request && !c.ack); c.ready_calls=0; c.bytes=command==0x4014?24:12; c.caller=0x80020002;
    memset(c.wire,0,sizeof c.wire); memcpy(c.wire,command==0x4014?mode:settings,c.bytes);
    for(size_t i=0;i<4;i++) c.wire[4+i]=(unsigned char)(cookie>>(8*i));
    c.request=message(c.bytes,c.caller); memcpy(c.request,c.wire,c.bytes);
    memcpy(c.expected_reply,(unsigned char[12]){1,0,0,0x40,0,0,0,0,0,0xf0,0,0},12); c.expected_reply[2]=(unsigned char)command;
    memcpy(c.expected_reply+4,c.wire+4,4);
}
static void diagnostic_first(void) {
    c.diagnostic=1; assert(!native_cp_startup_controls_diagnostic_owner_init());
    for(unsigned int i=0;i<2;i++) {
        prepare(i?0x4057:0x4014,0x80000026); int rc=999;
        assert(native_cp_startup_controls_diagnostic_dispatch(0x90030001,c.request,&io,&old_guard,1,&rc)==1 && !rc);
        assert(!c.request && c.ack); assert(native_cp_startup_controls_diagnostic_release_reply(0x80020002,c.ack,real_free,record,&rc)==1 && !rc);
        prepare(i?0x4057:0x4014,0x80000026);
        assert(native_cp_startup_controls_diagnostic_dispatch(0x90030001,c.request,&io,&old_guard,1,&rc)==1 && rc==-1022);
        destroy(c.request); c.request=NULL;
    }
    c.diagnostic=0; puts("diagnostic first4014_clean=1 first4057_clean=1 repeat4014=-1022 repeat4057=-1022 unchanged_one_shot=1");
}
static void setup_core(void) {
    model=fcam_model_create(instance); assert(model); if(is("no-init") || is("default-off")) return;
    unsigned char out[192]; struct fcam_exec_result r={0}; assert(!fcam_model_request(model,1,NULL,0,out,128,&r));
    assert(proof().opcode==1 && proof().after.rendered==1 && proof().after.retired==1);
    if(is("no-active")) return;
    assert(!fcam_model_request(model,5,route,16,out,160,&r)); c.active=1;
    if(!(is("normal") && variant==1)) assert(!fcam_model_request(model,13,fcam_still_format_initial,16,out,176,&r));
}
static void *bad_free(void *unused) { (void)unused; assert(sender_free()==-EPROTO); return NULL; }
static void sticky(void) {
    const struct functional_startup_control_snapshot s=owner(); if(!s.faults) return;
    const unsigned int calls=c.calls, allocations=c.allocations, frees=c.free_calls;
    /* Avoid touching fixture's deliberately reused pool while a retained lease exists. */
    struct message *m=calloc(1,sizeof *m+24); assert(m); m->size=24; m->source=0x80020002; memcpy(m->body,mode,24); int rc=999;
    assert(functional_startup_control_dispatch(0x90030001,m->body,&io,&guard,1,&rc)==1 && rc<0); unchanged(&s); free(m);
    if(c.request && s.request_owned) {
        assert(!functional_startup_control_release_cycle(0x90030001,c.request,real_free,record,(int *)(void *)((unsigned char *)c.request+8),s.cycle)); unchanged(&s);
    }
    assert(c.calls==calls && c.allocations==allocations && c.free_calls==frees);
    puts("sticky implicit_retry=0 snapshot_unchanged=1");
}
static void cycle(unsigned int command, uint32_t cookie) {
    prepare(command,cookie); unsigned int dst=0x90030001, enabled=1;
    struct full_imaging_io local_io=io; struct native_cp_state_publication_guard local_guard=guard;
    if(is("opaque")) ((unsigned char *)c.request)[1]=0xe7;
    if(is("default-off")) enabled=0;
    if(is("unsupported")) {
        if(variant==0) dst++;
        if(variant==1) enabled=0;
        if(variant==2) ((unsigned char *)c.request)[0]=6;
        if(variant==3) { ((unsigned char *)c.request)[2]=0xc8; envelope(c.request)->size=328; }
        if(variant==4) ((unsigned char *)c.request)[2]=0x33;
        if(variant==5) envelope(c.request)->size=23;
        if(variant==6) envelope(c.request)->size=25;
        if(variant==7) envelope(c.request)->source++;
        if(variant>=8 && variant<24) ((unsigned char *)c.request)[variant]^=1;
        if(variant>=24 && variant<28) ((unsigned char *)c.request)[8+variant-24]^=1;
        if(variant==28) envelope(c.request)->size=13;
        if(variant==29) envelope(c.request)->size=11;
        if(variant==30) local_io.size=NULL;
        if(variant==31) local_io.source=NULL;
        if(variant==32) local_io.allocate=NULL;
        if(variant==33) local_io.set_source=NULL;
        if(variant==34) local_io.send=NULL;
        if(variant==35) local_io.release=NULL;
        if(variant==36) local_guard.reserve=NULL;
        if(variant==37) local_guard.release=NULL;
        if(variant==38) local_guard.predecessor_ready=NULL;
    }
    memcpy(c.wire,c.request,envelope(c.request)->size<=328?envelope(c.request)->size:0);
    if(is("opaque")) memcpy(c.expected_reply+4,c.wire+4,4);
    const unsigned int calls=c.calls, states=c.state_calls, commits=c.commits, allocations=c.allocations, frees=c.free_calls;
    const struct functional_startup_control_snapshot previous=owner(); unsigned char before[128]; core_state(before); const struct fcam_frame_proof old=proof();
    int rc=999; c.dispatch_result=&rc;
    const int handled=functional_startup_control_dispatch(dst,c.request,&local_io,is("unsupported")&&variant==39?NULL:&local_guard,enabled,&rc);
    struct functional_startup_control_snapshot s=owner(); assert(!s.busy && !s.guard_held && !c.held);
    const int pre=is("default-off") || is("unsupported") || is("predecessor") || is("settings-first");
    if(pre) {
        assert(!handled || rc<0); assert(c.calls==calls && c.state_calls==states && c.allocations==allocations && c.free_calls==frees && c.request);
        unsigned char after[128]; core_state(after); assert(!memcmp(before,after,128)); const struct fcam_frame_proof p=proof(); assert(!memcmp(&old,&p,sizeof p));
        if(is("settings-first")) assert(handled==1 && rc==-ENODATA && !s.mode_applied && !s.command_requests[1]);
        unchanged(&previous); puts("preflight core_delta=0 ownership_delta=0 ack_delta=0 caller_owned=1");
    } else if(s.faults && !s.request_owned) {
        assert(handled==1 && rc<0 && c.request && c.allocations==allocations && c.free_calls==frees && !s.ap_consumed && !s.retained);
        assert(s.operation_attempted==(unsigned int)(c.calls>calls));
        assert(c.state_calls==states+1 && c.commits-commits<=1 && s.cycle==previous.cycle+1);
        assert(s.state_bridge_rc<=0 || is("state-mutations"));
        if(c.commits>commits) assert(!memcmp(s.model_result,c.authentic,192) || is("bad-receipt") || is("bad-descriptor") || is("old-proof"));
        printf("refused rc=%d attempted=%u actual_core_committed=%u caller_owned=1 ack_delta=0 request_free_delta=0 raw192=",rc,s.operation_attempted,c.commits-commits);hex(s.model_result,192);putchar('\n');
    } else {
        assert(handled==1 && !rc && s.request_owned && s.model_complete && c.calls==calls+1 && c.commits==commits+1 && c.state_calls==states+1);
        assert(s.command==command && s.original_wire_bytes==c.bytes && !memcmp(s.original_wire,c.wire,c.bytes) && s.actual_origin_fnv==fnv(c.wire,c.bytes));
        assert(!memcmp(s.model_result,c.authentic,192) && s.current_config40_fnv==fnv(s.model_state+8,40) && s.mode_applied);
        if(is("address-reuse")) assert(c.ack==c.pool->body);
        if(c.ack && !s.faults && !is("inline") && !is("inline-send-error")) {
            if(is("settings-while-live")) {
                struct message *m=calloc(1,sizeof *m+24); assert(m); m->size=24; m->source=0x80020002; memcpy(m->body,mode,24); int blocked=999;
                assert(functional_startup_control_dispatch(0x90030001,m->body,&io,&guard,1,&blocked)==1 && blocked==-EBUSY); unchanged(&s); free(m);
            }
            if(is("ticket") || is("address-reuse") || is("repeat")) {
                int stale=999; const unsigned int count=c.callbacks;
                assert(functional_startup_control_observe_receive_cycle(0x80020002,c.ack,0x90030001,12,c.previous_ticket)==-ESTALE);
                assert(functional_startup_control_release_cycle(0x80020002,c.ack,real_free,record,&stale,c.previous_ticket)==1 && stale==-ESTALE);
                assert(c.callbacks==count); unchanged(&s);
                if(s.cycle>1) { assert(functional_startup_control_observe_receive(0x80020002,c.ack,0x90030001,12)==-ESTALE);
                    assert(functional_startup_control_release(0x80020002,c.ack,real_free,record,&stale)==1 && stale==-ESTALE); unchanged(&s); }
                assert(!functional_startup_control_observe_receive_cycle(0x80020002,(void *)(uintptr_t)0x1230,0x90030001,12,s.cycle));
                assert(!functional_startup_control_release_cycle(0x80020002,(void *)(uintptr_t)0x1230,real_free,record,&stale,s.cycle)); unchanged(&s);
            }
            if(is("settings-while-live")) {
                struct message *m=calloc(1,sizeof *m+12); assert(m); m->size=12; m->source=0x80020002; memcpy(m->body,settings,12); int blocked=999;
                assert(functional_startup_control_dispatch(0x90030001,m->body,&io,&guard,1,&blocked)==1 && blocked==-EBUSY); unchanged(&s); free(m);
            }
            if(!is("no-receive")) observed();
            if(is("wrong-free-thread")) { pthread_t t; assert(!pthread_create(&t,NULL,bad_free,NULL)); assert(!pthread_join(t,NULL)); }
            else if(!is("receive-faults")) assert(sender_free()==(is("no-receive") || (is("io-faults")&&variant>=13)?-EPROTO:is("io-faults")&&variant==9?-EIO:0));
        }
        s=owner(); const unsigned int failed=is("io-faults") || is("send-error") || is("inline-send-error") || is("receive-faults") || is("wrong-free-thread") || is("no-receive");
        assert(s.faults==failed && s.ap_consumed==!failed);
        if(!failed) {
            assert(!s.retained && s.leases[0].freed && s.leases[1].freed && s.leases[1].received && s.leases[1].consumed && !c.slot.pointer);
            assert(s.leases[1].free_tid==s.leases[1].sender_tid && s.leases[1].receiver_tid!=s.leases[1].sender_tid);
            c.previous_ticket=s.cycle;
        }
        printf("lifecycle cycle=%llu command=%x requests=%u completed=%u mode_requests=%u settings_requests=%u mode_completed=%u settings_completed=%u mode_applied=%u consumed=%u faults=%u retained=%u request_free=%u reply_free=%u sender=%ld receiver=%ld free_tid=%ld wire=",
            (unsigned long long)s.cycle,s.command,s.requests,s.completed_cycles,s.command_requests[0],s.command_requests[1],s.command_completed[0],s.command_completed[1],s.mode_applied,s.ap_consumed,s.faults,s.retained,
            s.leases[0].freed,s.leases[1].freed,s.leases[1].sender_tid,s.leases[1].receiver_tid,s.leases[1].free_tid);
        hex(s.original_wire,s.original_wire_bytes);printf(" reply12=");hex(s.reply_wire,12);putchar('\n');
    }
    sticky(); s=owner(); if(c.request) { destroy(c.request); c.request=NULL; } if(c.ack) { destroy(c.ack); c.ack=c.queued=NULL; }
    unchanged(&s);
}
static void fork_check(void) {
    functional_startup_control_test_hold_lock(); pid_t child=fork(); assert(child>=0);
    if(!child) {
        struct functional_startup_control_snapshot s; functional_startup_control_snapshot(&s); assert(s.faults && s.owner_pid!=getpid());
        assert(functional_startup_control_owner_init()==-EXDEV); unsigned char p[24]; memcpy(p,mode,24); int rc=999;
        assert(functional_startup_control_dispatch(0x90030001,p,&io,&guard,1,&rc)==1 && rc==-EXDEV);
        assert(functional_startup_control_observe_receive_cycle(0x80020002,p,0x90030001,12,1)==-EXDEV);
        assert(functional_startup_control_release_cycle(0x80020002,p,real_free,record,&rc,1)==1 && rc==-EXDEV); _exit(0);
    }
    functional_startup_control_test_drop_lock(); int status=0; assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status)); puts("fork rejected_before_inherited_lock=1");
}
static void boundaries(void) {
    const struct functional_startup_control_snapshot s=owner(); const unsigned int count=c.callbacks; int rc=999;
    assert(!functional_startup_control_dispatch(0x90030001,(void *)(UINTPTR_MAX-2),&io,&guard,1,&rc) && rc==999 && c.callbacks==count); unchanged(&s);
    void *p=message(24,0x80020002); memcpy(p,mode,24);
    assert(!functional_startup_control_dispatch(0x90030001,p,&io,&guard,1,(int *)(void *)((unsigned char *)p+8))); assert(!memcmp(p,mode,24)); unchanged(&s); destroy(p);
    puts("boundaries overflow_no_callback=1 alias_unchanged=1");
}
int main(int argc, char **argv) {
    assert(argc==2 || argc==3); scenario=argv[1]; variant=argc==3?(unsigned int)strtoul(argv[2],NULL,10):0; armed=1; setvbuf(stdout,NULL,_IONBF,0);
    assert(!functional_startup_control_owner_init()); assert(functional_startup_control_owner_init()==-EALREADY);
    const struct functional_startup_control_snapshot initial=owner(); assert(!initial.cycle && !initial.operation_attempted && !initial.requests && !c.state_calls && !c.calls);
    armed=0; diagnostic_first(); armed=1; setup_core();
    if(is("fork")) fork_check(); else if(is("pointer-boundaries")) boundaries();
    else {
        const int needs_mode=is("old-proof");
        if(needs_mode) { armed=0; cycle(0x4014,0x8000003c); armed=1; }
        cycle(is("settings-first") || needs_mode || (is("unsupported") && variant>=24 && variant<=29)?0x4057:0x4014,0x8000003c);
        if(is("normal") || is("repeat") || is("same-cookie") || is("address-reuse") || is("inline") || is("opaque") || is("fresh-config") || is("ticket") || is("repeat-state-fail")) {
            if(is("fresh-config")) configure();
            cycle(is("same-cookie")?0x4014:0x4057,is("same-cookie")?0x8000003c:0x12);
            if(is("fresh-config")) { configure(); cycle(0x4014,0x12); cycle(0x4057,0x12); }
            if(is("same-cookie")) { cycle(0x4057,0x8000003c); cycle(0x4057,0x8000003c); }
            if(is("repeat")) { cycle(0x4014,0x8000003c); cycle(0x4057,0x8000003c); }
        }
    }
    assert(!c.pool_live); free(c.pool); fcam_model_destroy(model);
    printf("scope scenario=%s variant=%u calls=%u commits=%u state_calls=%u callbacks=%u records=%u original_ap_verified=false vm_verified=false original_cp=false physical_asic_verified=false physical_cp_rtos_verified=false capture_verified=false media_writes=0\n",
        scenario,variant,c.calls,c.commits,c.state_calls,c.callbacks,c.records); return 0;
}
