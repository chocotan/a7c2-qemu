/* SPDX-License-Identifier: MIT */
/* Limited CP RelMsgReceiver model, derived from the original 403d/4040
 * consumers. This does not implement CP boot, exposure, sensor or capture. */
#define _GNU_SOURCE
#include "imaging-device.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static struct full_imaging_snapshot state = {
    .requested = FULL_IMAGING_POWER_ON_INHIBIT, .af_gate=1,
    .internal_counter_a=1,.internal_counter_b=0x40000001
};
static struct reply_lease {
    void *pointer;
    unsigned int command, token, status, bytes;
    long sender;
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
    *lease=(struct reply_lease){reply,command,token,status,reply_size,tid};
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
    pthread_mutex_lock(&mutex);
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
    pthread_mutex_lock(&mutex); *out=state; out->effective=effective(); pthread_mutex_unlock(&mutex);
}
int full_imaging_capture_begin(void) {
    pthread_mutex_lock(&mutex);
    int denied=state.active_capture || effective()!=0 || state.faults;
    if (!denied) state.active_capture=1;
    pthread_mutex_unlock(&mutex);
    return denied?-16:0;
}
void full_imaging_capture_end(void) {
    pthread_mutex_lock(&mutex); state.active_capture=0; pthread_mutex_unlock(&mutex);
}
#ifdef FULL_IMAGING_TEST
void full_imaging_test_reset(unsigned int initial_mask) {
    pthread_mutex_lock(&mutex);
    state=(struct full_imaging_snapshot){.requested=initial_mask,.af_gate=1,
        .internal_counter_a=1,.internal_counter_b=0x40000001};
    memset(replies,0,sizeof replies);
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
