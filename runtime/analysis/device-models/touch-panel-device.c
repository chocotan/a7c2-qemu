/* SPDX-License-Identifier: MIT */
/* Bounded virtual DevPanel touch configuration, not a CP/touch hardware model.
 * The valid subset performs a real cached byte write/readback and constructs
 * the analyzed F02F body and TP-control payload. The F02F envelope/transport
 * and TP control result are deliberately not claimed or fabricated. */
#define _GNU_SOURCE
#include "touch-panel-device.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static struct full_touch_panel_snapshot state;
static struct lease { void *pointer; unsigned int destination; unsigned long long serial; } leases[8];

static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static void put32(unsigned char *p,unsigned int value) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(value>>(8*i));
}
static void hex(char *out,const unsigned char *p,unsigned int bytes) {
    for (unsigned int i=0;i<bytes;i++) snprintf(out+2*i,3,"%02x",p[i]);
    out[2*bytes]=0;
}
static void event(const struct full_imaging_io *io,const char *tag,const char *text) {
    if (io && io->record) io->record(tag,text);
}
static int unsupported(const struct full_imaging_io *io,int *result,const char *why) {
    event(io,"FULL_TOUCH_PANEL_UNSUPPORTED ",why);*result=-1021;return 1;
}
/* The caller still owns its request on every error path. Reply ownership is
 * independent and is retained if its actual release fails. */
static int cleanup_reply(const struct full_imaging_io *io,unsigned int destination,void *reply,const char *phase) {
    int rc=io->release(destination,reply);
    char text[192];
    snprintf(text,sizeof text,"tid=%ld phase=%s destination=%#x reply=%p rc=%d",
             syscall(SYS_gettid),phase,destination,reply,rc);
    if (rc) { state.faults++;state.retained_reply=reply; }
    event(io,rc?"FULL_TOUCH_PANEL_FAULT ":"FULL_TOUCH_PANEL_CLEANUP ",text);
    return rc;
}

int full_touch_panel_dispatch(unsigned int destination,void *request,
                             const struct full_imaging_io *io,int enabled,int *result) {
    if (destination!=FULL_TOUCH_PANEL_INPUT || !request || !io || !io->size || !result) return 0;
    const unsigned char *in=request;
    unsigned int bytes=io->size(request);
    if (bytes<4 || u16(in)!=0x200d || u16(in+2)!=0x146) return 0;
    if (enabled!=1) return 0;
    if (!io->allocate || !io->release || !io->source || !io->set_source || !io->send)
        return unsupported(io,result,"missing-transport");
    /* Only the measured valid boot shape is admitted. In particular, do not
     * invent the original invalid-enable side effects or a normal reply. */
    if (bytes!=10 || u16(in+4)!=10 || u16(in+6)!=0x8001 || in[8]>1 || in[9]!=0)
        return unsupported(io,result,"outside-valid-0146-envelope-or-enable");
    unsigned int caller=io->source(request);
    if ((caller>>28)!=8 || !(caller&0x0fffffff))
        return unsupported(io,result,"nonlocal-caller");
    char raw[21],text[640];hex(raw,in,10);
    snprintf(text,sizeof text,"tid=%ld destination=%#x source=%#x bytes=10 raw=%s virtual_config_only=1",
             syscall(SYS_gettid),destination,caller,raw);
    event(io,"FULL_TOUCH_PANEL_REQUEST ",text);

    pthread_mutex_lock(&mutex);
    if (!state.configured) {
        state.enabled=1;state.configured=1;
        event(io,"FULL_TOUCH_PANEL_CONFIG ","enabled=1 profile=virtual-config-v1 original_cp_executed=0 hardware_touch_verified=0");
    }
    if (state.faults || state.pending) {
        pthread_mutex_unlock(&mutex);
        return unsupported(io,result,"fault-or-concurrent-request");
    }
    state.pending=1;state.requests++;state.clean_completion=0;
    pthread_mutex_unlock(&mutex);

    void *reply=0;
    int rc=io->allocate(caller,&reply,12,1);
    pthread_mutex_lock(&mutex);
    struct lease *slot=0;int duplicate=reply && reply==request;
    for (unsigned int i=0;i<8;i++) {
        if (reply && leases[i].pointer==reply) duplicate=1;
        if (!leases[i].pointer && !slot) slot=&leases[i];
    }
    if (duplicate) {
        state.faults++;state.pending=0;
        event(io,"FULL_TOUCH_PANEL_FAULT ","allocator-returned-live-request-or-reply");
        pthread_mutex_unlock(&mutex);
        return unsupported(io,result,"duplicate-message-ownership");
    }
    if (rc || !reply || !slot || state.faults) {
        if (reply) cleanup_reply(io,caller,reply,"allocation-rejected");
        state.pending=0;
        pthread_mutex_unlock(&mutex);
        *result=rc?rc:-1021;return 1;
    }
    if (io->size(reply)!=12) {
        cleanup_reply(io,caller,reply,"wrong-reply-size");state.pending=0;
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    struct full_touch_panel_snapshot before=state;
    unsigned int enable=in[8];
    /* CP DevPanelCmdSetTouchPanel: Accessor+20, byte 0x6f90. This is the
     * virtual cache, not a write into CP memory. Valid values only. */
    state.cache=(unsigned char)enable;
    state.readback=state.cache;
    if (state.readback!=enable) {
        state.faults++;state.pending=0;
        cleanup_reply(io,caller,reply,"cache-readback-failed");
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    state.applied++;
    state.f02f[0]=1;state.f02f[1]=0x20;state.f02f[2]=0x2f;state.f02f[3]=0xf0;
    state.f02f[4]=12;state.f02f[5]=0;state.f02f[6]=1;state.f02f[7]=0;
    state.f02f[8]=(unsigned char)enable;state.f02f[9]=state.f02f[10]=state.f02f[11]=0;
    /* The virtual Accessor+4/+58 gate is declared as zero by this profile.
     * The original gate value and TP backend result are not measured. The
     * original DevPanel discards the TP-control return; we likewise record
     * submission without turning it into an applied/hardware result. */
    state.control_gate=0;
    if (state.control_gate!=1) {
        put32(state.control,3);put32(state.control+4,enable==1);
        state.control_submissions++;
    }
    state.control_result_verified=0;
    state.outer_status=0x00590000;
    unsigned char *out=reply;
    static const unsigned char header[8]={0x0d,0x20,0x46,0x11,12,0,1,0x80};
    memcpy(out,header,8);put32(out+8,state.outer_status);
    io->set_source(reply,FULL_TOUCH_PANEL_INPUT);
    *slot=(struct lease){reply,caller,++state.next_lease};state.live_replies++;
    rc=io->send(caller,reply);
    if (rc) {
        unsigned long long requests=state.requests;
        state=before;state.requests=requests;state.pending=0;
        memset(slot,0,sizeof *slot);
        cleanup_reply(io,caller,reply,"send-failed");
        snprintf(text,sizeof text,"tid=%ld destination=%#x rc=%d rollback=1 normal_completion=0",
                 syscall(SYS_gettid),caller,rc);
        event(io,"FULL_TOUCH_PANEL_TRANSPORT_FAILURE ",text);
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    state.queued++;
    char reply_raw[25];hex(reply_raw,out,12);
    snprintf(text,sizeof text,
             "tid=%ld destination=%#x source=%#x reply=%p lease=%llu bytes=12 raw_status=%#x raw=%s",
             syscall(SYS_gettid),caller,FULL_TOUCH_PANEL_INPUT,reply,slot->serial,
             state.outer_status,reply_raw);
    event(io,"FULL_TOUCH_PANEL_REPLY_QUEUED ",text);
    char f02f_raw[25],control_raw[17];hex(f02f_raw,state.f02f,12);hex(control_raw,state.control,8);
    snprintf(text,sizeof text,
             "tid=%ld f02f=%s f02f_destination=%#x vdf_reply_sid=%#x cache=%u readback=%u control_gate_virtual=%u control=%s control_submissions=%llu control_result_verified=0 f02f_transport_verified=0 original_cp_executed=0 hardware_touch_verified=0",
             syscall(SYS_gettid),f02f_raw,FULL_TOUCH_PANEL_F02F_DEST,FULL_TOUCH_PANEL_VDF_REPLY,
             state.cache,state.readback,state.control_gate,control_raw,state.control_submissions);
    event(io,"FULL_TOUCH_PANEL_DEVPANEL ",text);
    int freed=io->release(FULL_TOUCH_PANEL_INPUT,request);
    state.last_request_free_rc=freed;
    if (freed) { state.faults++;state.retained_request=request; }
    else state.request_freed++;
    state.clean_completion=freed==0 && state.faults==0;
    state.pending=0;
    snprintf(text,sizeof text,
             "tid=%ld enable=%u cache=%u readback=%u outer_status=%#x applied=%llu queued=%llu request_free_rc=%d request_retained=%u clean_completion=%u f02f_transport_verified=0 control_result_verified=0 hardware_touch_verified=0 camera_capture_verified=0",
             syscall(SYS_gettid),enable,state.cache,state.readback,state.outer_status,
             state.applied,state.queued,freed,(unsigned int)(state.retained_request!=0),state.clean_completion);
    event(io,freed?"FULL_TOUCH_PANEL_FAULT ":"FULL_TOUCH_PANEL_COMMIT ",text);
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}

int full_touch_panel_release_reply(unsigned int destination,void *reply,
                                   int (*release)(unsigned int,void *),
                                   void (*record)(const char *,const char *),int *result) {
    if (!reply || !release || !result) return 0;
    pthread_mutex_lock(&mutex);
    for (unsigned int i=0;i<8;i++) if (leases[i].pointer==reply) {
        int rc=release(destination,reply);state.last_reply_free_rc=rc;
        char text[240];
        snprintf(text,sizeof text,"tid=%ld destination=%#x reply=%p lease=%llu rc=%d",
                 syscall(SYS_gettid),destination,reply,leases[i].serial,rc);
        if (rc) {
            state.faults++;state.retained_reply=reply;
            if (record) record("FULL_TOUCH_PANEL_FAULT ",text);
            pthread_mutex_unlock(&mutex);*result=rc;return 1;
        }
        if (state.retained_reply==reply) state.retained_reply=0;
        memset(&leases[i],0,sizeof leases[i]);state.live_replies--;
        state.waiter_freed++;state.native_freed++;
        if (record) record("FULL_TOUCH_PANEL_REPLY_FREE ",text);
        pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    pthread_mutex_unlock(&mutex);return 0;
}

void full_touch_panel_snapshot(struct full_touch_panel_snapshot *out) {
    if (!out) return;
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_TOUCH_PANEL_TEST
void full_touch_panel_test_reset(void) {
    pthread_mutex_lock(&mutex);
    memset(&state,0,sizeof state);memset(leases,0,sizeof leases);
    pthread_mutex_unlock(&mutex);
}
#endif
