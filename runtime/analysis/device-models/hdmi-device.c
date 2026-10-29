/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "hdmi-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct full_hdmi_snapshot state;
static _Atomic int audio_marker_pid;
static struct lease {
    void *pointer;
    unsigned int destination, command, bytes, status;
    unsigned long long serial;
    long sender;
} replies[8];
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static void put16(unsigned char *p,unsigned int n) { p[0]=(unsigned char)n;p[1]=(unsigned char)(n>>8); }
static void put32(unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(n>>(i*8));
}
static void hex(char *text,const unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<n;i++) snprintf(text+2*i,3,"%02x",p[i]);
    text[2*n]=0;
}
static void event(const struct full_imaging_io *io,const char *tag,const char *text) {
    if (io->record) io->record(tag,text);
}
static int reject(const struct full_imaging_io *io,int *result,const char *reason) {
    event(io,"FULL_HDMI_UNSUPPORTED ",reason);*result=-1021;return 1;
}
/* Mutex includes the real free: a pool address cannot acquire a new lease
 * until its previous owner has actually released it. */
static int cleanup(const struct full_imaging_io *io,unsigned int dst,void *p) {
    int rc=io->release(dst,p);
    if (rc) { state.faults++;state.retained_reply=p; }
    char line[160];snprintf(line,sizeof line,"tid=%ld destination=%#x reply=%p rc=%d",syscall(SYS_gettid),dst,p,rc);
    event(io,rc?"FULL_HDMI_FAULT ":"FULL_HDMI_CLEANUP_FREE ",line);return rc;
}

int full_hdmi_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                       int enabled,int *result) {
    if (destination!=FULL_HDMI_CP || (enabled!=FULL_HDMI_DEFINITION && enabled!=FULL_HDMI_BOOT) ||
        !request || !io || !io->size || !result) return 0;
    const unsigned char *in=request;unsigned int bytes=io->size(request);
    if (bytes<4 || u16(in)!=0x2500) return 0;
    unsigned int command=u16(in+2);
    int resolution=command==0x0101 || command==0x0201;
    int rate=command==0x0117;
    if (command!=0x010a && command!=0x020a && !(enabled==FULL_HDMI_BOOT && (resolution || rate))) return 0;
    unsigned int required=(command==0x010a || rate)?12:command==0x0101?16:8;
    if (!io->allocate || !io->release || !io->source || !io->set_source || !io->send)
        return reject(io,result,"missing-transport");
    if (bytes!=required || u16(in+4)!=required || u16(in+6)!=1)
        return reject(io,result,"definition-envelope");
    unsigned int dst=io->source(request),reply_bytes=command==0x020a?16:command==0x0201?20:12;
    if ((dst>>28)!=8 || !(dst&0x0fffffff)) return reject(io,result,"nonlocal-caller");
    char raw[41],line[480];hex(raw,in,bytes);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x command=%#x bytes=%u raw=%s",
             syscall(SYS_gettid),dst,destination,command,bytes,raw);event(io,"FULL_HDMI_REQUEST ",line);
    pthread_mutex_lock(&mutex);
    if (state.faults || state.pending || (command==0x020a && !state.known) ||
        (command==0x0201 && !state.resolution_known)) {
        pthread_mutex_unlock(&mutex);return reject(io,result,"fault-concurrent-call-or-unknown-initial-definition");
    }
    state.pending=1;pthread_mutex_unlock(&mutex);
    void *reply=0;int rc=io->allocate(dst,&reply,reply_bytes,1);
    pthread_mutex_lock(&mutex);
    struct lease *slot=0;int duplicate=reply && reply==request;
    for (unsigned int i=0;i<8;i++) {
        if (reply && replies[i].pointer==reply) duplicate=1;
        if (!replies[i].pointer && !slot) slot=&replies[i];
    }
    if (duplicate) {
        state.faults++;state.pending=0;event(io,"FULL_HDMI_FAULT ","allocator-returned-live-message");
        pthread_mutex_unlock(&mutex);return reject(io,result,"duplicate-reply-ownership");
    }
    if (rc || !reply || !slot || state.faults) {
        if (reply) cleanup(io,dst,reply);
        state.pending=0;pthread_mutex_unlock(&mutex);*result=rc?rc:-1021;return 1;
    }
    struct full_hdmi_snapshot before=state;
    unsigned int requested=command==0x010a?in[8]:0;
    /* Original shared state624dc6 writes singleton+e4 and replies1. Active
     * output states and their deferred transitions are outside this profile. */
    if (command==0x010a) { state.definition=requested<6?requested:0;state.known=1;state.applied++; }
    else if (command==0x020a) state.queries++;
    else if (command==0x0101) {
        /* Original624926 shared state: preserve all six bytes, then reply0.
         * Active output-state transitions are not part of this owner. */
        memcpy(state.resolution,in+8,6);state.resolution_known=1;state.resolution_applied++;
    } else if (command==0x0201) state.resolution_queries++;
    else {
        /* Shared12a44c: the original wire has HDMI and DP pairs, but only
         * D/R updates S+a6..aa. No original array getter is established. */
        memcpy(state.last_rate_payload,in+8,4);state.rate_requests++;
        if (in[8]<5) { state.rates[in[8]]=in[9];state.rate_known_mask|=1u<<in[8]; }
    }
    unsigned int status=command==0x010a?1:0,readback=state.definition;
    unsigned char *out=reply;memset(out,0,reply_bytes);
    put16(out,0x2500);put16(out+2,command|0x8000);put16(out+4,reply_bytes);put16(out+6,1);
    put32(out+8,status);
    /* 624e12 reads the same saved field. Original +13..15 are unspecified;
     * this model explicitly initializes its own padding, never requires it. */
    if (command==0x020a) out[12]=(unsigned char)readback;
    if (command==0x0201) memcpy(out+12,state.resolution,6); /* Original623cfa clears the last two bytes. */
    io->set_source(reply,FULL_HDMI_CP);
    unsigned long long serial=++state.next_lease;
    *slot=(struct lease){reply,dst,command,reply_bytes,status,serial,syscall(SYS_gettid)};state.live_replies++;
    rc=io->send(dst,reply);
    if (rc) {
        state=before;state.pending=0;memset(slot,0,sizeof *slot);cleanup(io,dst,reply);
        snprintf(line,sizeof line,"phase=send rc=%d caller_owned=1 rollback=1",rc);
        event(io,"FULL_HDMI_TRANSPORT_FAILURE ",line);
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    state.queued++;hex(raw,out,reply_bytes);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x command=%#x reply=%p lease=%llu bytes=%u status=%u raw=%s",
             syscall(SYS_gettid),FULL_HDMI_CP,dst,command,reply,serial,reply_bytes,status,raw);
    event(io,"FULL_HDMI_REPLY_QUEUED ",line);
    int freed=io->release(FULL_HDMI_CP,request);
    if (freed) { state.faults++;state.retained_request=request; }else state.request_freed++;
    state.pending=0;
    if (resolution) {
        char saved[13];hex(saved,state.resolution,6);
        snprintf(line,sizeof line,"tid=%ld command=%#x resolution=%s resolution_known=%u status=%u applied=%llu queries=%llu reply=%p lease=%llu request_free_rc=%d hdmi_output_verified=0 camera_startup_verified=0",
                 syscall(SYS_gettid),command,saved,state.resolution_known,status,state.resolution_applied,
                 state.resolution_queries,reply,serial,freed);
    } else if (rate) {
        char saved[11];hex(saved,state.rates,5);
        const unsigned char *payload=state.last_rate_payload;
        unsigned int selector=payload[0];
        snprintf(line,sizeof line,"tid=%ld command=0x117 selector=%u rate=%u dp_selector=%u dp_rate=%u dp_applied=0 matched=%u readback=%u known_mask=%#x rates=%s status=0 requests=%llu reply=%p lease=%llu request_free_rc=%d hdmi_output_verified=0 camera_startup_verified=0",
                 syscall(SYS_gettid),selector,payload[1],payload[2],payload[3],selector<5,
                 selector<5?state.rates[selector]:0,state.rate_known_mask,saved,state.rate_requests,reply,serial,freed);
    } else {
        snprintf(line,sizeof line,"tid=%ld command=%#x requested=%u known_before=%u readback_before=%u known_after=%u readback=%u status=%u applied=%llu queries=%llu reply=%p lease=%llu request_free_rc=%d hdmi_output_verified=0 camera_startup_verified=0",
                 syscall(SYS_gettid),command,requested,before.known,before.definition,state.known,readback,status,
                 state.applied,state.queries,reply,serial,freed);
    }
    event(io,freed?"FULL_HDMI_FAULT ":"FULL_HDMI_COMMIT ",line);
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}

int full_hdmi_release_reply(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                            void (*record)(const char *,const char *),int *result) {
    if (!reply || !release || !result) return 0;
    pthread_mutex_lock(&mutex);struct lease found={0};
    for (unsigned int i=0;i<8;i++) if (replies[i].pointer==reply) {
        found=replies[i];*result=found.destination==destination?release(destination,reply):-1021;
        if (*result) state.faults++;
        else {
            memset(&replies[i],0,sizeof replies[i]);state.live_replies--;state.native_freed++;
            if (found.sender==syscall(SYS_gettid)) state.waiter_freed++;
        }
        break;
    }
    if (found.pointer && record) {
        char line[320];long tid=syscall(SYS_gettid);
        snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu command=%#x bytes=%u status=%u rc=%d",
                 tid,found.sender,tid==found.sender,destination,found.destination,reply,found.serial,
                 found.command,found.bytes,found.status,*result);
        record(*result?"FULL_HDMI_FAULT ":"FULL_HDMI_NATIVE_REPLY_FREE ",line);
    }
    pthread_mutex_unlock(&mutex);return found.pointer!=0;
}
int full_hdmi_audio_pin_connected_one(void) {
    int pid=(int)getpid(),expected=0;
    atomic_compare_exchange_strong(&audio_marker_pid,&expected,pid);
    if (atomic_load(&audio_marker_pid)!=pid) return -1021;
    pthread_mutex_lock(&mutex);
    int rc=-1021;
    if (!state.faults && !state.pending && !state.live_replies &&
        !state.retained_request && !state.retained_reply && !state.audio_pin_connected_writes) {
        /* All ten state vtables select one of three true branches: write1 only.
         * The old byte is unknown, and return0 means no state transition. */
        state.audio_pin_connected=1;state.audio_pin_connected_known=1;
        state.audio_pin_connected_writes=1;state.audio_pin_connected_owner_pid=pid;rc=0;
    }
    pthread_mutex_unlock(&mutex);return rc;
}
void full_hdmi_snapshot(struct full_hdmi_snapshot *out) {
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_HDMI_TEST
void full_hdmi_test_reset(void) {
    pthread_mutex_lock(&mutex);state=(struct full_hdmi_snapshot){0};memset(replies,0,sizeof replies);
    atomic_store(&audio_marker_pid,0);
    pthread_mutex_unlock(&mutex);
}
#endif
