/* SPDX-License-Identifier: MIT
 * CP0429 stores configuration, accepts early, then applies through a worker.
 * This explicit inactive virtual subset applies before replying. No CP RAM,
 * genlock service, external timecode samples or original gate writes are used. */
#define _GNU_SOURCE
#include "tcin-device.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct full_tcin_snapshot state;
static struct lease { void *pointer; unsigned int destination; unsigned long long serial; } leases[8];
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static int reject(const struct full_imaging_io *io,int *result,const char *why) {
    if (io->record) io->record("FULL_TCIN_UNSUPPORTED ",why);
    *result=-1021;return 1;
}
static void event(const struct full_imaging_io *io,const char *tag,const char *text) {
    if (io->record) io->record(tag,text);
}
static void dispose_reply(const struct full_imaging_io *io,unsigned int owner,void *reply) {
    int rc=io->release(owner,reply);
    state.cleanup_free_rc=rc;
    if (rc) {
        state.faults++;state.retained_cleanup_reply=reply;state.retained_cleanup_owner=owner;state.clean_completion=0;
        char text[160];
        snprintf(text,sizeof text,"owner=%#x reply=%p cleanup_free_rc=%d retained=1 normal_completion=0",owner,reply,rc);
        event(io,"FULL_TCIN_FAULT ",text);
    }
}

int full_tcin_dispatch(unsigned int destination,void *request,
                       const struct full_imaging_io *io,int enabled,int *result) {
    if (destination!=FULL_TCIN_INPUT || !request || !io || !io->size || !result) return 0;
    const unsigned char *in=request;
    unsigned int bytes=io->size(request);
    if (bytes<4 || u16(in)!=0x200d || u16(in+2)!=0x429 || enabled!=1) return 0;
    if (!io->allocate || !io->release || !io->source || !io->set_source || !io->send)
        return reject(io,result,"missing-transport");
    if (bytes!=10) return reject(io,result,"only-ten-byte-0429-is-modeled");
    unsigned char input[10];memcpy(input,request,sizeof(input));
    if (u16(input)!=0x200d || u16(input+2)!=0x429 || u16(input+4)!=10 ||
        u16(input+6)!=0x8001 || input[8]!=0 || input[9]!=0)
        return reject(io,result,"only-valid-disable-0429-is-modeled");
    unsigned int caller=io->source(request);
    if ((caller>>28)!=8 || !(caller&0x0fffffff)) return reject(io,result,"nonlocal-caller");
    char text[640];
    snprintf(text,sizeof text,"tid=%ld destination=%#x source=%#x request=%p bytes=10 raw=0d2029040a0001800000 virtual_inactive=1",
             syscall(SYS_gettid),destination,caller,request);
    event(io,"FULL_TCIN_REQUEST ",text);
    pthread_mutex_lock(&mutex);
    if (state.faults || state.busy || state.condition || state.active || state.connected) {
        pthread_mutex_unlock(&mutex);
        return reject(io,result,"fault-concurrent-or-noninactive-state");
    }
    state.configured=1;state.busy=1;state.requests++;state.clean_completion=0;
    pthread_mutex_unlock(&mutex);

    void *reply=0;
    int rc=io->allocate(caller,&reply,12,1);
    pthread_mutex_lock(&mutex);
    struct lease *slot=0;
    int duplicate=reply && reply==request;
    for (unsigned int i=0;i<8;i++) {
        if (reply && leases[i].pointer==reply) duplicate=1;
        if (!leases[i].pointer && !slot) slot=&leases[i];
    }
    if (duplicate) {
        state.faults++;state.busy=0;
        pthread_mutex_unlock(&mutex);
        return reject(io,result,"allocator-returned-live-request-or-reply");
    }
    unsigned int reply_bytes=reply && !rc?io->size(reply):0;
    if (rc || !reply || !slot || state.faults || reply_bytes!=12) {
        if (reply) dispose_reply(io,caller,reply);
        snprintf(text,sizeof text,"allocate_rc=%d owner=%#x reply=%p reply_bytes=%u slot_available=%u cleanup_free_rc=%d retained_cleanup=%u faults=%u normal_completion=0",
                 rc,caller,reply,reply_bytes,(unsigned int)(slot!=0),state.cleanup_free_rc,
                 (unsigned int)(state.retained_cleanup_reply!=0),state.faults);
        event(io,"FULL_TCIN_FAULT ",text);
        state.busy=0;
        pthread_mutex_unlock(&mutex);*result=rc?rc:-1021;return 1;
    }
    /* Own virtual state, mirroring the analyzed inactive branch. The actual
     * CP condition word and worker execution remain unobserved. */
    state.requested=input[8];
    state.pending_flags|=0x04000000u;
    state.applied=state.requested;
    state.connected=0;
    state.pending_flags&=~0x04000000u;
    if (state.requested || state.applied || state.active || state.connected || state.pending_flags) {
        state.faults++;state.busy=0;
        dispose_reply(io,caller,reply);
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    state.applications++;
    snprintf(text,sizeof text,"tid=%ld requested=%u applied=%u condition_virtual=%u active_virtual=%u connected_virtual=%u pending=%#x applications=%llu genlock_stop_not_required=1 virtual_config_only=1 original_cp_executed=0",
             syscall(SYS_gettid),state.requested,state.applied,state.condition,state.active,
             state.connected,state.pending_flags,state.applications);
    event(io,"FULL_TCIN_APPLIED ",text);
    static const unsigned char response[12]={0x0d,0x20,0x29,0x14,12,0,1,0x80,0,0,0,0};
    memcpy(reply,response,sizeof(response));
    io->set_source(reply,FULL_TCIN_INPUT);
    *slot=(struct lease){reply,caller,++state.next_lease};state.live_replies++;
    rc=io->send(caller,reply);
    if (rc) {
        /* The applied virtual state is retained; transport failure is not rollback. */
        memset(slot,0,sizeof(*slot));state.live_replies--;state.faults++;
        dispose_reply(io,caller,reply);state.busy=0;
        snprintf(text,sizeof text,"reply-send-failed send_rc=%d owner=%#x reply=%p cleanup_free_rc=%d retained_cleanup=%u applied-state-retained=1 normal_completion=0",
                 rc,caller,reply,state.cleanup_free_rc,(unsigned int)(state.retained_cleanup_reply!=0));
        event(io,"FULL_TCIN_FAULT ",text);
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    state.queued++;
    snprintf(text,sizeof text,"tid=%ld destination=%#x source=%#x reply=%p lease=%llu bytes=12 raw=0d2029140c00018000000000",
             syscall(SYS_gettid),caller,FULL_TCIN_INPUT,reply,slot->serial);
    event(io,"FULL_TCIN_REPLY_QUEUED ",text);
    int freed=io->release(FULL_TCIN_INPUT,request);
    state.request_free_rc=freed;
    if (freed) { state.faults++;state.retained_request=request; }
    else state.request_freed++;
    state.busy=0;state.clean_completion=!freed && !state.faults;
    snprintf(text,sizeof text,
        "tid=%ld requested=%u applied=%u condition_virtual=%u active_virtual=%u connected_virtual=%u pending=%#x applications=%llu request_free_rc=%d request_retained=%u clean_completion=%u native_acceptance_precedes_application=1 virtual_applied_before_reply=1 genlock_stop_sent=0 original_cp_executed=0 hardware_tcin_verified=0 capture_verified=0",
        syscall(SYS_gettid),state.requested,state.applied,state.condition,state.active,state.connected,
        state.pending_flags,state.applications,freed,(unsigned int)(state.retained_request!=0),state.clean_completion);
    event(io,freed?"FULL_TCIN_FAULT ":"FULL_TCIN_COMMIT ",text);
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}

int full_tcin_release_reply(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                            void (*record)(const char *,const char *),int *result) {
    if (!reply || !release || !result) return 0;
    pthread_mutex_lock(&mutex);
    if (reply==state.retained_cleanup_reply) {
        unsigned int expected=state.retained_cleanup_owner;
        int rc=destination==expected?release(destination,reply):-1021;
        state.cleanup_free_rc=rc;
        if (rc) state.faults++;
        else { state.retained_cleanup_reply=0;state.retained_cleanup_owner=0; }
        char text[240];
        snprintf(text,sizeof text,"destination=%#x expected=%#x reply=%p cleanup_free_rc=%d retained=%u normal_completion=0",
                 destination,expected,reply,rc,(unsigned int)(state.retained_cleanup_reply!=0));
        if (record) record(rc?"FULL_TCIN_FAULT ":"FULL_TCIN_CLEANUP_REPLY_FREE ",text);
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    for (unsigned int i=0;i<8;i++) if (leases[i].pointer==reply) {
        int rc=destination==leases[i].destination?release(destination,reply):-1021;
        state.reply_free_rc=rc;
        char text[240];
        snprintf(text,sizeof text,"tid=%ld destination=%#x expected=%#x reply=%p lease=%llu rc=%d",
                 syscall(SYS_gettid),destination,leases[i].destination,reply,leases[i].serial,rc);
        if (rc) {
            state.faults++;state.retained_reply=reply;state.clean_completion=0;
            if (record) record("FULL_TCIN_FAULT ",text);
        } else {
            if (state.retained_reply==reply) state.retained_reply=0;
            memset(&leases[i],0,sizeof(leases[i]));state.live_replies--;state.reply_freed++;
            if (record) record("FULL_TCIN_REPLY_FREE ",text);
        }
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    pthread_mutex_unlock(&mutex);return 0;
}
void full_tcin_snapshot(struct full_tcin_snapshot *out) {
    if (!out) return;
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_TCIN_TEST
void full_tcin_test_reset(void) {
    pthread_mutex_lock(&mutex);memset(&state,0,sizeof(state));memset(leases,0,sizeof(leases));pthread_mutex_unlock(&mutex);
}
void full_tcin_test_state(unsigned int condition,unsigned int active,unsigned int connected) {
    pthread_mutex_lock(&mutex);state.condition=condition;state.active=active;state.connected=connected;pthread_mutex_unlock(&mutex);
}
#endif
