/* SPDX-License-Identifier: MIT */
/* Limited CP RelMsgReceiver model, derived from the original 403d/4040
 * consumers. This does not implement CP boot, exposure, sensor or capture. */
#define _GNU_SOURCE
#include "imaging-device.h"
#include "../functional-camera-abi.h"
#include "../functional-startup-control-abi.h"
#include <errno.h>
#include <stdatomic.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int functional_pid;
static full_imaging_focus_reset_backend focus_reset_backend;
static full_imaging_focus_query_backend focus_query_backend;
static struct full_imaging_focus_reset_receipt focus_checkpoint;
static unsigned char focus_checkpoint_request[16];
static struct full_imaging_snapshot state = {
    .requested = FULL_IMAGING_POWER_ON_INHIBIT, .af_gate=1,
    .internal_counter_a=1,.internal_counter_b=0x40000001
};
static struct reply_lease {
    void *pointer;
    unsigned int command, token, status, bytes, source;
    long sender;
    unsigned functional,sending,queued,received,releasing,freed;
    long receiver;
    unsigned char wire[24];
    struct full_imaging_io io;
} replies[8];

static unsigned int u16(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8; }
static unsigned int u32(const unsigned char *p) {
    return u16(p) | u16(p+2) << 16;
}
static void put32(unsigned char *p, unsigned int value) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(value >> (8*i));
}
static unsigned int effective(void) { return state.requested & ~state.suppressed; }
static const unsigned char levels[3][23]={
    {0,6,6,15,9,8,8,8,8,3,4,2,1,10,13,17,6,14,11,16,5,12,7},
    {0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,2,1,1,0,1,1,0,1},
    {0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,2,1,1,0,1,1,0,1}
};
static unsigned int select_still(unsigned int kind) {
    unsigned int selected=0;
    for (unsigned int i=0;i<23;i++)
        if (state.still_active[i] && levels[kind][i]>levels[kind][selected]) selected=i;
    return selected;
}
/* Internal CP control endpoint. It consumes the documented 24-byte controls
 * into virtual focus/AE/BW intent. No AF completion, pixels or ready is emitted. */
static void focus_control(const struct full_imaging_io *io,unsigned int command,
                          unsigned int token,unsigned int selector) {
    unsigned char packet[24]={0};
    packet[0]=command==0x3031?2:0;
    packet[2]=(unsigned char)command;packet[3]=(unsigned char)(command>>8);
    put32(packet+4,token);
    put32(packet+(command==0x3031?12:8),selector);
    if (command==0x3031) state.focus_trigger[selector]=0;
    if (command==0x300e || command==0x300f || command==0x3010) state.focus_af=selector;
    if (command==0x3021 || command==0x3022) state.focus_ae=selector;
    if (command==0x302e || command==0x302f) state.focus_bw=selector;
    memcpy(state.last_focus_message,packet,24);state.focus_controls++;
    if (io->record) {
        char line[200],hex[49];
        for (unsigned int i=0;i<24;i++) snprintf(hex+2*i,3,"%02x",packet[i]);
        snprintf(line,sizeof line,"tid=%ld source=%#x destination=0x90030001 cmd=%#x selector=%u consumed=virtual-control raw=%s",
                 syscall(SYS_gettid),FULL_IMAGING_CP,command,selector,hex);
        io->record("FULL_IMAGING_FOCUS_CONTROL ",line);
    }
}
static void arbitrate_still(const struct full_imaging_io *io) {
    unsigned int n=select_still(1);
    if (levels[1][n]!=levels[1][state.ae_selector]) {
        int locking=(0x005b0006u>>n)&1;
        focus_control(io,locking?0x3021:0x3022,locking?state.still_token[n]:0,n);
        state.ae_selector=n;
    }
    n=select_still(0);
    unsigned int old=state.af_selector;
    if (state.af_gate && levels[0][n]!=levels[0][old]) {
        focus_control(io,old==0?0x300e:(n?0x300f:0x3010),n?state.still_token[n]:0,n);
        if (old==0x0d && n && levels[0][n]<levels[0][0x0d]) focus_control(io,0x3025,0,0);
        if (n==0x13) state.pending_still_13=0;
        state.af_selector=n;state.af_gate=0;
    }
    n=select_still(2);
    if (levels[2][n]!=levels[2][state.bw_selector]) {
        focus_control(io,n?0x302e:0x302f,n?state.still_token[n]:0,n);
        state.bw_selector=n;
    }
}
static int still_unlock(void *request,const struct full_imaging_io *io,int *result) {
    const unsigned char *body=request;
    if (io->size(request)!=16 || body[8]>=23 || !((0x007e621cu>>body[8])&1) || body[9] || body[10] || body[11]) {
        if (io->record) io->record("FULL_IMAGING_UNSUPPORTED ","4037-selector-or-envelope-not-modeled");
        *result=-1021;return 1;
    }
    unsigned int selector=body[8];
    unsigned int input_token=u32(body+4);
    pthread_mutex_lock(&mutex);
    if (state.faults || state.active_capture || (selector==0x13 && state.pending_still_13)) {
        pthread_mutex_unlock(&mutex);
        if (io->record) io->record("FULL_IMAGING_UNSUPPORTED ","4037-fault-active-capture-or-pending205b-not-modeled");
        *result=-1021;return 1; /* Capture lifecycle maintenance is not modeled. */
    }
    unsigned int before=state.still_active[selector],old_token=state.still_token[selector];
    unsigned int af_before=state.af_selector,gate_before=state.af_gate;
    int write_slot=selector!=9 && !((selector==2 || selector==0x14) && state.control_latch);
    if (write_slot) {
        state.still_active[selector]=0;state.still_token[selector]=input_token;
        if (!state.arbiter_disabled) arbitrate_still(io);
    } else if (selector==9 && state.focus_latch_09==1) {
        focus_control(io,0x3024,0,9);state.focus_latch_09=0;
    }
    focus_control(io,0x3031,0,selector);
    state.still_unlocks++;
    /* No capture or pending D010 operation can exist in this boot-only model.
     * Future lifecycle support must implement ae156c before accepting captures. */
    int freed=io->release(FULL_IMAGING_CP,request);
    if (freed) state.faults++;
    char line[460];
    snprintf(line,sizeof line,
        "tid=%ld token=%#x saved_token=%#x selector=%#x active_before=%u active_after=%u old_token=%#x af_before=%u af_after=%u gate_before=%u gate_after=%u requested=%#x effective=%#x controls=%llu slot_written=%u ap_reply=none request_free_rc=%d",
        syscall(SYS_gettid),input_token,state.still_token[selector],selector,before,state.still_active[selector],old_token,af_before,state.af_selector,
        gate_before,state.af_gate,state.requested,effective(),state.focus_controls,write_slot,freed);
    pthread_mutex_unlock(&mutex);
    if (io->record) io->record(freed?"FULL_IMAGING_FAULT ":"FULL_IMAGING_STILL_UNLOCK ",line);
    *result=0;return 1;
}
static void event(const struct full_imaging_io *io, const char *tag, const char *text) {
    if (io->record) io->record(tag,text);
}
static int fail(const struct full_imaging_io *io, int *result, const char *why) {
    event(io,"FULL_IMAGING_UNSUPPORTED ",why);
    *result=-1021; /* Transport unavailable, not an invented Sony business status. */
    return 1;
}

int full_imaging_dispatch(unsigned int destination, void *request,
                          const struct full_imaging_io *io, int *result) {
    if (destination==0x9059000e && request && io && io->size && io->source && io->record) {
        unsigned int bytes=io->size(request),shown=bytes<96?bytes:96;
        const unsigned char *input=request;char hex[193],line[360];
        for (unsigned int i=0;i<shown;i++) snprintf(hex+2*i,3,"%02x",input[i]);
        hex[2*shown]=0;
        snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x bytes=%u shown=%u raw=%s action=original-transport",
                 syscall(SYS_gettid),destination,io->source(request),bytes,shown,hex);
        io->record("FULL_IMAGING_VDF_OBSERVE ",line);
    }
    if (destination!=FULL_IMAGING_CP) return 0;
    if (!io || !result) return 0;
    if (!request || !io->allocate || !io->release || !io->set_source ||
        !io->send || !io->size || !io->source)
        return fail(io,result,"missing-message-or-transport");
    unsigned int size=io->size(request), source=io->source(request);
    const unsigned char *body=request;
    unsigned int command=size>=4?u16(body+2):0, token=size>=8?u32(body+4):0;
    char line[420],raw[65];
    unsigned int shown=size<32?size:32;
    for (unsigned int i=0;i<shown;i++) snprintf(raw+i*2,3,"%02x",body[i]);
    raw[shown*2]=0;
    long tid=syscall(SYS_gettid);
    snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x cmd=%#x bytes=%u raw=%s",
             tid,destination,source,command,size,raw);
    event(io,"FULL_IMAGING_REQUEST ",line);
    if (source!=FULL_IMAGING_AP || size<8 || body[0]!=5 || body[1]!=0)
        return fail(io,result,"unexpected-source-or-envelope");
    if (command==0x4037) return still_unlock(request,io,result);
    int setting=command==0x403d, querying=command==0x4040;
    if ((!setting && !querying) || size!=(setting?16u:12u))
        return fail(io,result,"command-or-body-size-not-modeled");
    unsigned int mask=u32(body+8), lock=setting?body[12]:0;
    if (setting && ((mask!=0x8000 && mask!=0x200000) || lock>1 ||
                    body[13] || body[14] || body[15]))
        return fail(io,result,"unsupported-reason-lock-or-reserved-bytes");
    /* Allocation can wait for a pool block. Never hold the state mutex while
     * waiting for a previous AP owner to free its reply. */
    void *reply=0;
    unsigned int reply_size=setting?12:16;
    int rc=io->allocate(FULL_IMAGING_AP,&reply,reply_size,1);
    if (rc || !reply) { *result=rc?rc:-1021; return 1; }
    pthread_mutex_lock(&mutex);
    struct reply_lease *lease=0;
    for (unsigned int i=0;i<8;i++) if (!replies[i].pointer) { lease=&replies[i]; break; }
    if (state.faults || !lease || (setting && mask==0x8000 && lock && state.active_capture)) {
        /* Active release requires the original deferred-completion lifecycle,
         * which this boot-only subset deliberately rejects rather than ACKs. */
        pthread_mutex_unlock(&mutex);
        int free_rc=io->release(FULL_IMAGING_AP,reply);
        if (free_rc) {
            pthread_mutex_lock(&mutex); state.faults++; pthread_mutex_unlock(&mutex);
            snprintf(line,sizeof line,"tid=%ld phase=rejected-reply-free rc=%d reply=%p",tid,free_rc,reply);
            event(io,"FULL_IMAGING_FAULT ",line);
        }
        return fail(io,result,"fault-full-leases-or-active-release-defer-not-modeled");
    }
    unsigned int before=state.requested;
    if (setting) state.requested=lock?(before|mask):(before&~mask);
    unsigned int matched=effective()&mask;
    unsigned int status=querying && matched?0xf001:0xf000;
    memset(reply,0,reply_size);
    unsigned char *out=reply;
    out[0]=1; out[2]=(unsigned char)command; out[3]=(unsigned char)(command>>8);
    put32(out+4,token); put32(out+8,status);
    if (querying) put32(out+12,matched);
    io->set_source(reply,FULL_IMAGING_CP);
    *lease=(struct reply_lease){.pointer=reply,.command=command,.token=token,.status=status,.bytes=reply_size,.sender=tid};
    rc=io->send(FULL_IMAGING_AP,reply);
    if (rc) {
        state.requested=before;
        memset(lease,0,sizeof *lease);
        if (io->release(FULL_IMAGING_AP,reply)) state.faults++;
        pthread_mutex_unlock(&mutex);
        *result=rc; /* No acceptance: caller still owns its original request. */
        return 1;
    }
    if (setting) state.applied++;
    state.queued++;
    int freed=io->release(FULL_IMAGING_CP,request);
    if (freed) state.faults++;
    snprintf(line,sizeof line,
        "tid=%ld cmd=%#x token=%#x reason=%#x lock=%u before=%#x requested=%#x effective=%#x status=%#x reply=%p request_free_rc=%d queued=%llu",
        tid,command,token,mask,lock,before,state.requested,effective(),status,reply,freed,state.queued);
    pthread_mutex_unlock(&mutex);
    event(io,freed?"FULL_IMAGING_FAULT ":"FULL_IMAGING_COMMIT ",line);
    *result=0; /* Accepted, request consumed, reply ownership transferred. */
    return 1;
}

int full_imaging_release_reply(unsigned int destination, void *reply,
                              int (*release)(unsigned int,void *),
                              void (*record)(const char *,const char *),int *result) {
    if (destination!=FULL_IMAGING_AP || !reply || !release || !result) return 0;
    struct reply_lease found={0};
    int functional=atomic_load(&functional_pid);
    if(functional && functional!=getpid()){*result=-ECHILD;return 1;}
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<8;++i)if(replies[i].pointer==reply && replies[i].functional){
        struct reply_lease *l=&replies[i];
        if(l->releasing || l->freed || !l->received || l->sender!=syscall(SYS_gettid)){
            *result=-EPROTO;pthread_mutex_unlock(&mutex);return 1;
        }
        found=*l;l->releasing=1;pthread_mutex_unlock(&mutex);
        int exact=found.io.size(reply)==found.bytes && found.io.source(reply)==found.source && !memcmp(reply,found.wire,found.bytes);
        int rc=exact?release(destination,reply):-EBADMSG;
        pthread_mutex_lock(&mutex);l->releasing=0;
        if(!rc){l->freed=1;++state.waiter_freed;if(l->queued && !l->sending)memset(l,0,sizeof *l);}else ++state.faults;
        pthread_mutex_unlock(&mutex);
        if((found.command==0x414d || found.command==0x403f || found.command==0x403e || found.command==0x3020) && record){char line[320];
            if(found.command==0x403e){snprintf(line,sizeof line,
                "tid=%ld sender_tid=%ld receiver_tid=%ld source=%#x destination=%#x cmd=0x403e token=%#x bytes=16 status=%#x value=%u rc=%d capture_verified=0",
                syscall(SYS_gettid),found.sender,found.receiver,found.source,destination,found.token,found.status,u32(found.wire+12),rc);
                record("FUNCTIONAL_CAMERA_FOCUS_QUERY_REPLY_FREE ",line);
            }else if(found.command==0x403f && found.status==0xf000){snprintf(line,sizeof line,
                "tid=%ld sender_tid=%ld receiver_tid=%ld source=%#x destination=%#x cmd=0x403f token=%#x bytes=12 status=0xf000 rc=%d magnification_disabled=1 capture_verified=0",
                syscall(SYS_gettid),found.sender,found.receiver,found.source,destination,found.token,rc);
                record("FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_APPLIED_REPLY_FREE ",line);
            }else{snprintf(line,sizeof line,
            "tid=%ld sender_tid=%ld receiver_tid=%ld source=%#x destination=%#x cmd=%#x token=%#x bytes=%u status=%#x rc=%d %s=0 capture_verified=0",
            syscall(SYS_gettid),found.sender,found.receiver,found.source,destination,found.command,found.token,found.bytes,found.status,rc,
            found.command==0x3020?"flash_lock_available":"position_available");
            record(found.command==0x414d?"FUNCTIONAL_CAMERA_LENS_POSITION_REPLY_FREE ":found.command==0x403f?"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_REPLY_FREE ":"FUNCTIONAL_CAMERA_FELOCK_REPLY_FREE ",line);}}
        *result=rc;return 1;
    }
    for (unsigned int i=0;i<8;i++) if (replies[i].pointer==reply) {
        found=replies[i];
        /* Keep the lease protected across the real release. An allocator may
         * reuse the pool address immediately; a pointer-only post-free hook
         * could otherwise mistake a new reply for the old one. */
        *result=release(destination,reply);
        if (!*result) {
            memset(&replies[i],0,sizeof replies[i]);
            if (found.sender==syscall(SYS_gettid)) state.waiter_freed++;
        } else state.faults++;
        break;
    }
    pthread_mutex_unlock(&mutex);
    if (found.pointer && record) {
        char line[256]; long tid=syscall(SYS_gettid);
        snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u cmd=%#x token=%#x status=%#x reply=%p bytes=%u rc=%d",
                 tid,found.sender,tid==found.sender,found.command,found.token,found.status,reply,found.bytes,*result);
        record(*result?"FULL_IMAGING_FAULT ":"FULL_IMAGING_NATIVE_REPLY_FREE ",line);
    }
    return found.pointer!=0;
}
void full_imaging_snapshot(struct full_imaging_snapshot *out) {
    int pid=atomic_load(&functional_pid);
    if(pid && pid!=getpid()){memset(out,0,sizeof *out);out->faults=1;return;}
    pthread_mutex_lock(&mutex); *out=state; out->effective=effective();out->live_replies=0;
    for(unsigned i=0;i<8;++i)out->live_replies+=replies[i].pointer!=NULL;
    pthread_mutex_unlock(&mutex);
}
int full_imaging_capture_begin(void) {
    pthread_mutex_lock(&mutex);
    int denied=state.active_capture || effective()!=0 || state.faults;
    if (!denied) state.active_capture=1;
    pthread_mutex_unlock(&mutex);
    return denied?-16:0;
}
void full_imaging_capture_end(void) {
    int pid=atomic_load(&functional_pid);if(pid && pid!=getpid())return;
    pthread_mutex_lock(&mutex); state.active_capture=0; pthread_mutex_unlock(&mutex);
}
static uint64_t u64(const unsigned char *p){return u32(p)|(uint64_t)u32(p+4)<<32;}
static uint64_t focus_hash(const unsigned char *p,size_t bytes){
    uint64_t hash=UINT64_C(14695981039346656037);
    for(size_t i=0;i<bytes;++i)hash=(hash^p[i])*UINT64_C(1099511628211);
    return hash;
}
static int focus_zero(const unsigned char *p,size_t bytes){
    for(size_t i=0;i<bytes;++i)if(p[i])return 0;
    return 1;
}
static int focus_receipt_valid(const unsigned char request[16],const struct full_imaging_focus_reset_receipt *r){
    const unsigned char *s=r->state,*c=r->canonical,*p=r->result;
    uint64_t instance=u64(s+48),generation=u64(s+56),frame=u64(s+112);
    return r->origin_fnv==focus_hash(request,16) && instance && generation && generation!=UINT64_MAX &&
        frame && frame!=UINT64_MAX && u32(s)==FCAM_ABI_VERSION && u32(s+4)==FCAM_CAPABILITIES &&
        u32(s+8)==640 && u32(s+12)==480 && u32(s+16) && u32(s+20) && u32(s+20)<=100 &&
        !u32(s+104) && !u32(s+108) && focus_zero(s+120,8) &&
        u16(c)==FCAM_STARTUP_CONTROL_CMD_FOCUS_OFF && u16(c+2)==8 && focus_zero(c+4,20) &&
        u64(c+24)==focus_hash(s+8,40) &&
        u32(p)==FCAM_ABI_VERSION && u32(p+4)==192 && u64(p+8)==instance &&
        u64(p+16)==generation+1 && u64(p+24)==frame+1 && u64(p+32) &&
        u64(p+40)==focus_hash(c,32) && u64(p+48) && u64(p+48)==u64(p+56) &&
        u64(p+64)==UINT64_C(640)*480*3 && u32(p+72)==640 && u32(p+76)==480 && u32(p+80)==1920 &&
        u32(p+84)==0x90590819 && u32(p+88)==1 && u32(p+92)==1 && u32(p+96)==9 &&
        u32(p+100)==1 && u32(p+104)==1 && u32(p+108)==1 && u32(p+112)==1 && u32(p+116)==1 &&
        focus_zero(p+120,8) && p[128]==1 && p[129]==5 && p[130]==5 && p[132]<=2 &&
        focus_zero(p+141,3) && u64(p+144)==frame && u64(p+152)==generation && !memcmp(p+160,c,32);
}
static int functional_guard(void){int pid=atomic_load(&functional_pid);return !pid?-ENODEV:pid!=getpid()?-ECHILD:0;}
int full_imaging_functional_enable(void){
    int expected=0;atomic_compare_exchange_strong(&functional_pid,&expected,getpid());int rc=functional_guard();if(rc)return rc;
    pthread_mutex_lock(&mutex);
    if(state.functional_enabled)rc=-EALREADY;
    else if(state.active_capture || state.faults)rc=-EBUSY;
    else{state.functional_enabled=1;state.functional_owner_pid=getpid();}
    pthread_mutex_unlock(&mutex);return rc;
}
int full_imaging_functional_bind_focus_reset(full_imaging_focus_reset_backend backend){
    int rc=functional_guard();if(rc)return rc;
    if(!backend)return -EINVAL;
    pthread_mutex_lock(&mutex);
    if(!state.functional_enabled)rc=-ENODEV;
    else if(state.functional_busy || state.active_capture || state.faults)rc=-EBUSY;
    else if(focus_reset_backend && focus_reset_backend!=backend)rc=-EALREADY;
    else focus_reset_backend=backend;
    pthread_mutex_unlock(&mutex);return rc;
}
int full_imaging_functional_bind_focus_query(full_imaging_focus_query_backend backend){
    int rc=functional_guard();if(rc)return rc;
    if(!backend)return -EINVAL;
    pthread_mutex_lock(&mutex);
    if(!state.functional_enabled)rc=-ENODEV;
    else if(state.functional_busy || state.active_capture || state.faults)rc=-EBUSY;
    else if(focus_query_backend && focus_query_backend!=backend)rc=-EALREADY;
    else focus_query_backend=backend;
    pthread_mutex_unlock(&mutex);return rc;
}
static int focus_query_state_valid(const unsigned char fresh[128]){
    const unsigned char *saved=focus_checkpoint.result;
    return state.focus_reset_applied && focus_receipt_valid(focus_checkpoint_request,&focus_checkpoint) &&
        focus_hash(saved,192)==state.focus_result_fnv &&
        u64(saved+8)==state.focus_model_instance && u64(saved+16)==state.focus_config_generation &&
        u64(saved+24)==state.focus_frame_generation &&
        u32(fresh)==FCAM_ABI_VERSION && u32(fresh+4)==FCAM_CAPABILITIES &&
        u32(fresh+8)==640 && u32(fresh+12)==480 && u32(fresh+16) &&
        u32(fresh+20) && u32(fresh+20)<=100 &&
        u64(fresh+48)==u64(saved+8) && u64(fresh+56)>=u64(saved+16) &&
        u64(fresh+112)>=u64(saved+24) && !u32(fresh+104) && !u32(fresh+108) && focus_zero(fresh+120,8);
}
int full_imaging_capture_begin_functional(const uint8_t *p,size_t bytes,uint64_t instance,uint64_t generation){
    int rc=functional_guard();if(rc)return rc;
    if(!p || bytes!=128 || !instance || !generation)return -EINVAL;
    if(u32(p)!=FCAM_ABI_VERSION || u32(p+4)!=FCAM_CAPABILITIES ||
       !u32(p+8) || u32(p+8)>FCAM_MAX_STILL_WIDTH || !u32(p+12) || u32(p+12)>FCAM_MAX_STILL_HEIGHT ||
       !u32(p+16) || u32(p+16)>60 || !u32(p+20) || u32(p+20)>100 ||
       u64(p+48)!=instance || u64(p+56)!=generation || !u64(p+64) || !u64(p+112) ||
       u32(p+104) || u32(p+108) || u64(p+120))return -ENOTSUP;
    pthread_mutex_lock(&mutex);unsigned live=0;for(unsigned i=0;i<8;++i)live+=replies[i].pointer!=NULL;
    if(!state.functional_enabled || state.functional_busy || state.active_capture || state.faults || live ||
       state.suppressed || (effective()&~FULL_IMAGING_POWER_ON_INHIBIT))rc=-EBUSY;
    else{state.active_capture=1;state.functional_instance=instance;state.functional_generation=generation;state.functional_frame=u64(p+112);}
    pthread_mutex_unlock(&mutex);return rc;
}
void full_imaging_functional_observe_receive(unsigned destination,void *message,unsigned source,unsigned bytes){
    if(functional_guard() || destination!=FULL_IMAGING_AP || !message)return;
    struct reply_lease observed={0};int rc=-EPROTO;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<8;++i){struct reply_lease *l=&replies[i];if(l->pointer!=message || !l->functional)continue;
        if(l->received || l->freed || l->releasing || (!l->queued && !l->sending) || source!=l->source ||
           bytes!=l->bytes || memcmp(message,l->wire,l->bytes))++state.faults;
        else{l->received=1;l->receiver=syscall(SYS_gettid);rc=0;}
        observed=*l;break;
    }
    pthread_mutex_unlock(&mutex);
    if((observed.command==0x414d || observed.command==0x403f || observed.command==0x403e || observed.command==0x3020) && observed.io.record){char line[320];
        if(observed.command==0x403e){snprintf(line,sizeof line,
            "tid=%ld sender_tid=%ld source=%#x destination=%#x cmd=0x403e token=%#x bytes=16 status=%#x value=%u rc=%d capture_verified=0",
            syscall(SYS_gettid),observed.sender,source,destination,observed.token,observed.status,u32(observed.wire+12),rc);
            observed.io.record("FUNCTIONAL_CAMERA_FOCUS_QUERY_REPLY_RECEIVED ",line);
        }else if(observed.command==0x403f && observed.status==0xf000){snprintf(line,sizeof line,
            "tid=%ld sender_tid=%ld source=%#x destination=%#x cmd=0x403f token=%#x bytes=12 status=0xf000 rc=%d magnification_disabled=1 capture_verified=0",
            syscall(SYS_gettid),observed.sender,source,destination,observed.token,rc);
            observed.io.record("FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_APPLIED_REPLY_RECEIVED ",line);
        }else{snprintf(line,sizeof line,
        "tid=%ld sender_tid=%ld source=%#x destination=%#x cmd=%#x token=%#x bytes=%u status=%#x rc=%d %s=0 capture_verified=0",
        syscall(SYS_gettid),observed.sender,source,destination,observed.command,observed.token,bytes,observed.status,rc,
        observed.command==0x3020?"flash_lock_available":"position_available");
        observed.io.record(observed.command==0x414d?"FUNCTIONAL_CAMERA_LENS_POSITION_REPLY_RECEIVED ":observed.command==0x403f?"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_REPLY_RECEIVED ":"FUNCTIONAL_CAMERA_FELOCK_REPLY_RECEIVED ",line);}}
}
int full_imaging_functional_dispatch(unsigned destination,void *message,const struct full_imaging_io *io,int *result){
    if((destination!=FULL_IMAGING_CP && destination!=FULL_IMAGING_LENS_POSITION_CP) ||
       !message || !io || !io->size || io->size(message)<4)return 0;
    const unsigned char *p=message;unsigned command=u16(p+2);
    int lens_position=command==0x414d && destination==FULL_IMAGING_LENS_POSITION_CP;
    int focus_magnification=command==0x403f && destination==FULL_IMAGING_CP;
    int focus_query=command==0x403e && destination==FULL_IMAGING_CP;
    int felock=command==0x3020 && destination==FULL_IMAGING_FELOCK_CP;
    int unavailable=lens_position || focus_magnification || focus_query || felock;
    if(!unavailable && (destination!=FULL_IMAGING_CP || (command!=0x403d && command!=0x4040)))return 0;
    if(!result)return 0;
    int rc=functional_guard();if(rc){*result=rc;return 1;}
    if(!io->allocate || !io->release || !io->set_source || !io->send || !io->source){*result=-EINVAL;return 1;}
    int setting=command==0x403d;unsigned bytes=lens_position?8u:focus_magnification || setting?16u:12u;
    if(io->size(message)!=bytes || io->source(message)!=FULL_IMAGING_AP || p[0]!=(felock?0:5) || p[1]){*result=-ENOTSUP;return 1;}
    if(felock && u32(p+8)>1){*result=-ENOTSUP;return 1;}
    if(focus_query && u32(p+8)!=0x10f01u){*result=-ENOTSUP;return 1;}
    unsigned mask=unavailable?0:u32(p+8),lock=setting?p[12]:0,token=u32(p+4);
    if(setting && ((mask!=0x8000 && mask!=0x200000) || lock>1 || p[13] || p[14] || p[15])){*result=-ENOTSUP;return 1;}
    pthread_mutex_lock(&mutex);unsigned index=0;while(index<8 && replies[index].pointer)++index;
    if(!state.functional_enabled || state.functional_busy || state.faults || index==8 ||
       (focus_query && state.active_capture) || (setting && lock && state.active_capture)){
        pthread_mutex_unlock(&mutex);*result=-EBUSY;return 1;
    }
    state.functional_busy=1;full_imaging_focus_reset_backend backend=focus_reset_backend;
    full_imaging_focus_query_backend query_backend=focus_query_backend;
    int query_has_checkpoint=state.focus_reset_applied!=0;
    if(focus_query)for(unsigned i=0;i<8;++i)if(replies[i].pointer){
        state.functional_busy=0;pthread_mutex_unlock(&mutex);*result=-EBUSY;return 1;
    }
    pthread_mutex_unlock(&mutex);
    unsigned reply_bytes=lens_position?24u:focus_magnification || setting || felock?12u:16u;void *reply=NULL;rc=io->allocate(FULL_IMAGING_AP,&reply,reply_bytes,1);
    if(!rc && !reply)rc=-ENOMEM;
    uintptr_t reply_address=(uintptr_t)reply,request_address=(uintptr_t)message;
    int aliased=reply && (reply_address<=request_address?
        request_address-reply_address<reply_bytes:reply_address-request_address<bytes);
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;reply && i<8;++i)if(replies[i].pointer){
        uintptr_t live=(uintptr_t)replies[i].pointer;
        aliased|=reply_address<=live?live-reply_address<reply_bytes:reply_address-live<replies[i].bytes;
    }
    pthread_mutex_unlock(&mutex);
    if(aliased){reply=NULL;if(!rc)rc=-EINVAL;}
    if(!rc && io->size(reply)!=reply_bytes)rc=-EMSGSIZE;
    if(rc){
        if(reply){int freed=io->release(FULL_IMAGING_AP,reply);if(freed){pthread_mutex_lock(&mutex);++state.faults;replies[index]=(struct reply_lease){.pointer=reply,.bytes=reply_bytes,.functional=1};pthread_mutex_unlock(&mutex);}}
        pthread_mutex_lock(&mutex);state.functional_busy=0;pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    struct full_imaging_focus_reset_receipt focus_receipt={0};
    int focus_attempted=focus_magnification && !u32(p+8) && !u32(p+12) && backend;
    int focus_applied=0,focus_rc=-ENODEV;
    if(focus_attempted){
        unsigned char original[16],before_request[16];memcpy(original,p,sizeof original);memcpy(before_request,p,sizeof before_request);
        if(io->record){char line[440],hex[33];
            for(unsigned i=0;i<16;++i)snprintf(hex+2*i,3,"%02x",original[i]);
            snprintf(line,sizeof line,
                "pid=%d tid=%ld source=%#x destination=%#x cmd=0x403f token=%#x request_bytes=16 raw=%s native_fnv=%#llx policy=%s capture_verified=0",
                getpid(),syscall(SYS_gettid),FULL_IMAGING_AP,destination,token,hex,
                (unsigned long long)focus_hash(original,16),FULL_IMAGING_FOCUS_RESET_POLICY);
            io->record("FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_RESET_REQUEST ",line);}
        pthread_mutex_lock(&mutex);++state.focus_reset_requests;pthread_mutex_unlock(&mutex);
        focus_rc=backend(original,&focus_receipt);
        if(io->size(message)!=16 || io->source(message)!=FULL_IMAGING_AP ||
           memcmp(original,before_request,16) || memcmp(message,before_request,16)){
            int released=io->release(FULL_IMAGING_AP,reply);
            pthread_mutex_lock(&mutex);++state.faults;++state.focus_reset_failed;state.functional_busy=0;
            if(released)replies[index]=(struct reply_lease){.pointer=reply,.bytes=reply_bytes,.functional=1};
            pthread_mutex_unlock(&mutex);*result=-EBADMSG;return 1;
        }
        if(!focus_rc && !focus_receipt_valid(original,&focus_receipt))focus_rc=-EPROTO;
        focus_applied=!focus_rc;
    }
    unsigned char query_state[128]={0},query_request[12]={0};
    int query_rc=-ENODATA,query_applied=0;uint64_t query_checkpoint_fnv=0;
    if(focus_query){
        memcpy(query_request,p,12);
        pthread_mutex_lock(&mutex);++state.focus_query_requests;pthread_mutex_unlock(&mutex);
        if(query_backend && query_has_checkpoint){
            query_rc=query_backend(query_request,query_state);
            if(io->size(message)!=12 || io->source(message)!=FULL_IMAGING_AP ||
               memcmp(message,query_request,12) || u16(query_request+2)!=0x403e || u32(query_request+8)!=0x10f01u){
                int released=io->release(FULL_IMAGING_AP,reply);
                pthread_mutex_lock(&mutex);++state.faults;++state.focus_query_failed;state.functional_busy=0;
                if(released)replies[index]=(struct reply_lease){.pointer=reply,.bytes=reply_bytes,.functional=1};
                pthread_mutex_unlock(&mutex);*result=-EBADMSG;return 1;
            }
            pthread_mutex_lock(&mutex);
            if(!query_rc && !focus_query_state_valid(query_state))query_rc=-EPROTO;
            pthread_mutex_unlock(&mutex);
            query_applied=!query_rc;
        }
    }
    pthread_mutex_lock(&mutex);unsigned before=state.requested;
    if(focus_attempted && focus_rc)++state.focus_reset_failed;
    if(focus_query && !query_applied)++state.focus_query_failed;
    if(setting)state.requested=lock?(before|mask):(before&~mask);
    unsigned matched=effective()&mask,status=(unavailable && !focus_applied && !query_applied) || (!unavailable && !setting && matched)?0xf001:0xf000;
    if(focus_query){matched=query_applied?u32(focus_checkpoint.canonical+4):0;query_checkpoint_fnv=state.focus_result_fnv;}
    struct reply_lease *l=&replies[index];
    *l=(struct reply_lease){.pointer=reply,.command=command,.token=token,.status=status,.bytes=reply_bytes,.source=destination,
        .sender=syscall(SYS_gettid),.functional=1,.sending=1,.io=*io};
    l->wire[0]=1;l->wire[2]=(unsigned char)command;l->wire[3]=(unsigned char)(command>>8);
    put32(l->wire+4,token);put32(l->wire+8,status);if(!setting)put32(l->wire+12,matched);
    memcpy(reply,l->wire,reply_bytes);pthread_mutex_unlock(&mutex);io->set_source(reply,destination);
    if(io->size(reply)!=reply_bytes || io->source(reply)!=destination)rc=-EBADMSG;
    else rc=io->send(FULL_IMAGING_AP,reply);
    pthread_mutex_lock(&mutex);l->sending=0;
    if(rc){
        if(l->received || l->freed){++state.faults;state.functional_busy=0;pthread_mutex_unlock(&mutex);*result=rc;return 1;}
        state.requested=before;pthread_mutex_unlock(&mutex);int freed=io->release(FULL_IMAGING_AP,reply);pthread_mutex_lock(&mutex);
        if(freed)++state.faults;else memset(l,0,sizeof *l);
        state.functional_busy=0;pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    l->queued=1;++state.queued;if(setting)++state.applied;
    if(focus_applied){
        ++state.focus_reset_applied;state.focus_model_instance=u64(focus_receipt.result+8);
        state.focus_config_generation=u64(focus_receipt.result+16);state.focus_frame_generation=u64(focus_receipt.result+24);
        state.focus_result_fnv=focus_hash(focus_receipt.result,192);
        focus_checkpoint=focus_receipt;memcpy(focus_checkpoint_request,p,16);
    }
    if(query_applied)++state.focus_query_succeeded;
    if(l->freed)memset(l,0,sizeof *l);
    pthread_mutex_unlock(&mutex);int freed=io->release(destination,message);pthread_mutex_lock(&mutex);
    if(freed)++state.faults;
    state.functional_busy=0;unsigned after=state.requested;pthread_mutex_unlock(&mutex);
    if(io->record){char line[1152];
        if(focus_attempted){snprintf(line,sizeof line,
            "pid=%d tid=%ld cmd=0x403f token=%#x backend_rc=%d native_fnv=%#llx model_instance=%#llx cfg_before=%llu cfg=%llu frame_before=%llu frame=%llu canonical_fnv=%#llx model_fnv=%#llx capture_verified=0",
            getpid(),syscall(SYS_gettid),token,focus_rc,(unsigned long long)focus_receipt.origin_fnv,
            (unsigned long long)u64(focus_receipt.state+48),(unsigned long long)u64(focus_receipt.state+56),
            (unsigned long long)u64(focus_receipt.result+16),(unsigned long long)u64(focus_receipt.state+112),
            (unsigned long long)u64(focus_receipt.result+24),(unsigned long long)focus_hash(focus_receipt.canonical,32),
            (unsigned long long)focus_hash(focus_receipt.result,192));
            io->record("FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_BACKEND ",line);}
        if(focus_query){char raw[25],state_hex[257];
            for(unsigned i=0;i<12;++i)snprintf(raw+2*i,3,"%02x",query_request[i]);
            for(unsigned i=0;i<128;++i)snprintf(state_hex+2*i,3,"%02x",query_state[i]);
            snprintf(line,sizeof line,
                "pid=%d tid=%ld source=%#x destination=%#x cmd=0x403e token=%#x request_bytes=12 reply_bytes=16 status=%#x value=%u backend_rc=%d raw=%s state=%s state_fnv=%#llx model_instance=%#llx cfg=%llu frame=%llu checkpoint_fnv=%#llx request_free_rc=%d policy=%s physical_ASIC_verified=0 capture_verified=0",
                getpid(),syscall(SYS_gettid),FULL_IMAGING_AP,destination,token,status,matched,query_rc,raw,state_hex,
                (unsigned long long)focus_hash(query_state,128),(unsigned long long)u64(query_state+48),
                (unsigned long long)u64(query_state+56),(unsigned long long)u64(query_state+112),
                (unsigned long long)query_checkpoint_fnv,freed,FULL_IMAGING_FOCUS_QUERY_POLICY);
            io->record("FUNCTIONAL_CAMERA_FOCUS_QUERY ",line);
        }else if(focus_applied){snprintf(line,sizeof line,
            "pid=%d tid=%ld source=%#x destination=%#x cmd=0x403f token=%#x request_bytes=16 reply_bytes=12 status=0xf000 request_free_rc=%d policy=%s native_fnv=%#llx model_instance=%#llx cfg=%llu frame=%llu model_fnv=%#llx rgb_bytes=921600 frame_consumed=1 frame_retired=1 magnification_disabled=1 capture_verified=0",
            getpid(),syscall(SYS_gettid),FULL_IMAGING_AP,destination,token,freed,FULL_IMAGING_FOCUS_RESET_POLICY,
            (unsigned long long)focus_receipt.origin_fnv,(unsigned long long)u64(focus_receipt.result+8),
            (unsigned long long)u64(focus_receipt.result+16),(unsigned long long)u64(focus_receipt.result+24),
            (unsigned long long)focus_hash(focus_receipt.result,192));
            io->record("FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_APPLIED ",line);
        }else if(unavailable){snprintf(line,sizeof line,
            "pid=%d tid=%ld source=%#x destination=%#x cmd=%#x token=%#x request_bytes=%u reply_bytes=%u status=%#x request_free_rc=%d policy=%s %s=0 capture_verified=0",
            getpid(),syscall(SYS_gettid),FULL_IMAGING_AP,destination,command,token,bytes,reply_bytes,status,freed,
            lens_position?FULL_IMAGING_LENS_POSITION_POLICY:focus_magnification?FULL_IMAGING_FOCUS_MAGNIFICATION_POLICY:FULL_IMAGING_FELOCK_POLICY,
            felock?"flash_lock_available":"position_available");
            io->record(lens_position?"FUNCTIONAL_CAMERA_LENS_POSITION_UNAVAILABLE ":focus_magnification?"FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_UNAVAILABLE ":"FUNCTIONAL_CAMERA_FELOCK_UNAVAILABLE ",line);
        }else{snprintf(line,sizeof line,
            "pid=%d tid=%ld cmd=%#x token=%#x mask=%#x lock=%u requested_before=%#x requested_after=%#x request_free_rc=%d policy=%s CP_D012_verified=0 capture_verified=0",
            getpid(),syscall(SYS_gettid),command,token,mask,lock,before,after,freed,FULL_IMAGING_FUNCTIONAL_POLICY);
            io->record("FUNCTIONAL_CAMERA_INTERLOCK ",line);}}
    *result=0;return 1;
}
#ifdef FULL_IMAGING_TEST
void full_imaging_test_reset(unsigned int initial_mask) {
    pthread_mutex_lock(&mutex);
    state=(struct full_imaging_snapshot){.requested=initial_mask,.af_gate=1,
        .internal_counter_a=1,.internal_counter_b=0x40000001};
    memset(replies,0,sizeof replies);focus_reset_backend=NULL;focus_query_backend=NULL;
    memset(&focus_checkpoint,0,sizeof focus_checkpoint);memset(focus_checkpoint_request,0,sizeof focus_checkpoint_request);
    pthread_mutex_unlock(&mutex);
}
void full_imaging_test_still(unsigned int selector,unsigned int active,unsigned int token) {
    if (selector>=23) return;
    pthread_mutex_lock(&mutex);
    state.still_active[selector]=active;state.still_token[selector]=token;
    state.focus_trigger[selector]=active;
    pthread_mutex_unlock(&mutex);
}
void full_imaging_test_arbitration(unsigned int af,unsigned int ae,unsigned int bw,
                                  unsigned int gate,unsigned int disabled) {
    pthread_mutex_lock(&mutex);
    state.af_selector=state.focus_af=af;state.ae_selector=state.focus_ae=ae;
    state.bw_selector=state.focus_bw=bw;state.af_gate=gate;state.arbiter_disabled=disabled;
    pthread_mutex_unlock(&mutex);
}
void full_imaging_test_latches(unsigned int control,unsigned int pending13,unsigned int focus09) {
    pthread_mutex_lock(&mutex);
    state.control_latch=control;state.pending_still_13=pending13;state.focus_latch_09=focus09;
    pthread_mutex_unlock(&mutex);
}
#endif
