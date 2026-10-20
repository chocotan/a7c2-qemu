/* SPDX-License-Identifier: MIT */
/* Finite VDF 0205/020b configuration model. No pixels, cable, ready or CP memory
 * writes. Original HDMI binding is static evidence; output is unimplemented. */
#define _GNU_SOURCE
#include "vdf-device.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
/* CP 6d61d0 -> 6d60e8 initializes D+6fb8 to 1, before any 0205 request. */
static struct full_vdf_snapshot state={.hdmi_cache=1,.evf_status={0,1,0,0}};
static struct lease {
    void *pointer;
    unsigned int destination, status;
    unsigned long long serial;
    long sender;
    unsigned int bytes, command;
} replies[8];

static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static unsigned int u32(const unsigned char *p) { return u16(p)|u16(p+2)<<16; }
static void put32(unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(n>>(8*i));
}
static void hex(char *out,const unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<n;i++) snprintf(out+2*i,3,"%02x",p[i]);
    out[2*n]=0;
}
static void event(const struct full_imaging_io *io,const char *tag,const char *text) {
    if (io->record) io->record(tag,text);
}
static int reject(const struct full_imaging_io *io,int *result,const char *why) {
    event(io,"FULL_VDF_UNSUPPORTED ",why);*result=-1021;return 1;
}
/* Called with mutex held, including the real free, so reused pool addresses
 * cannot acquire a new lease before the old one is cleared. */
static int cleanup(const struct full_imaging_io *io,unsigned int dst,void *p,const char *phase) {
    int rc=io->release(dst,p);
    char line[192];
    snprintf(line,sizeof line,"tid=%ld phase=%s destination=%#x pointer=%p rc=%d",
             syscall(SYS_gettid),phase,dst,p,rc);
    if (rc) { state.faults++;state.retained_reply=p; }
    event(io,rc?"FULL_VDF_FAULT ":"FULL_VDF_CLEANUP_FREE ",line);
    return rc;
}
/* CP 6dadd8 -> Accessor+838/6e4ba4 saves this u32; +834/6e4b9a
 * reads it later, behind separate pin/state/type10 resource gates. */
static void hdmi_config(const unsigned char packet[28]) {
    const unsigned char *data=packet+8;
    memcpy(state.internal_packet,packet,28);
    state.hdmi_cache=data[1]?1:data[8];state.hdmi_consumed++;
}
static void apply(const unsigned char *body) {
    unsigned char packet[28]={1,0x20,0x33,0xf0,0x1c,0,1,0};
    memcpy(state.body,body,20);memcpy(packet+8,body,20);
    hdmi_config(packet);state.has_config=1;state.applied++;
}
static int supported(const unsigned char *data) {
    /* AP's known zeroed position/level/UB/reserved fields have no evidenced
     * nonzero consumer here. data[12] stays unnamed, with CP's 0..2 range. */
    if (data[0]!=1 || data[8]>1) return 0;
    for (unsigned int i=2;i<20;i++) if (i!=8 && i!=12 && data[i]) return 0;
    return 1;
}

static int evf_subscribe(void *request,const struct full_imaging_io *io,int *result) {
    const unsigned char *data=(const unsigned char *)request+32;
    pthread_mutex_lock(&mutex);
    /* CP 6c5470 starts with valid=0 and status 00 01 00 00. No sampling
     * producer is modeled: never manufacture a 120c event or a 120b ACK.
     * A future valid-state backend must implement the original event rules. */
    if (state.faults || state.evf_valid) {
        pthread_mutex_unlock(&mutex);
        return reject(io,result,"ownership-fault-or-valid-evf-events-not-modeled");
    }
    memcpy(state.evf_subscription,data,8);
    state.evf_retained=data[4]==1 || data[5]==1;
    state.evf_subscriptions++;
    int freed=io->release(FULL_VDF_CP,request);
    if (freed) { state.faults++;state.retained_request=request; }
    else state.request_freed++;
    char raw[17],line[320];hex(raw,state.evf_subscription,8);
    snprintf(line,sizeof line,
             "tid=%ld notify_destination=%#x config=%s retained_type13=%u valid=%u state=00010000 subscriptions=%llu events=0 ap_reply=none request_free_rc=%d",
             syscall(SYS_gettid),u32(state.evf_subscription),raw,state.evf_retained,
             state.evf_valid,state.evf_subscriptions,freed);
    event(io,freed?"FULL_VDF_FAULT ":"FULL_VDF_EVF_SUBSCRIPTION ",line);
    pthread_mutex_unlock(&mutex);
    *result=0;return 1;
}

static int panel_resolution(void *request,const struct full_imaging_io *io,int *result) {
    const unsigned char *in=request;
    if (!io->allocate || !io->release || !io->source || !io->set_source || !io->send)
        return reject(io,result,"panel-missing-transport");
    if (io->size(request)!=10 || u16(in+4)!=10 || u16(in+6)!=0x8001 || in[8]!=2)
        return reject(io,result,"panel-envelope-or-selector-outside-boot-subset");
    unsigned int dst=io->source(request),size=in[9];
    if ((dst>>28)!=8 || !(dst&0x0fffffff)) return reject(io,result,"panel-nonlocal-caller");
    char line[460];
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x bytes=10 raw=0d2065010a00018002%02x",
             syscall(SYS_gettid),dst,FULL_VDF_INPUT,size);
    event(io,"FULL_VDF_PANEL_REQUEST ",line);
    pthread_mutex_lock(&mutex);
    if (state.faults || state.panel_pending) {
        pthread_mutex_unlock(&mutex);
        return reject(io,result,"panel-fault-or-concurrent-caller-outside-serial-subset");
    }
    /* The original ad ring has capacity9; this finite boot profile supports
     * one in-flight call, refusing overlap instead of reordering completions. */
    state.panel_pending=1;state.panel_caller=dst;
    pthread_mutex_unlock(&mutex);
    void *reply=0;int rc=io->allocate(dst,&reply,12,1);
    pthread_mutex_lock(&mutex);
    struct lease *slot=0;int duplicate=reply && reply==request;
    for (unsigned int i=0;i<8;i++) {
        if (reply && replies[i].pointer==reply) duplicate=1;
        if (!replies[i].pointer && !slot) slot=&replies[i];
    }
    if (duplicate) {
        state.faults++;state.panel_pending=state.panel_caller=0;
        event(io,"FULL_VDF_FAULT ","panel-allocator-returned-live-message");
        pthread_mutex_unlock(&mutex);return reject(io,result,"panel-duplicate-ownership");
    }
    if (rc || !reply || state.faults || !slot) {
        if (reply) cleanup(io,dst,reply,"panel-rejected-reply-free");
        state.panel_pending=state.panel_caller=0;
        pthread_mutex_unlock(&mutex);*result=rc?rc:-1021;return 1;
    }
    struct full_vdf_snapshot before=state;
    unsigned int service_status=size<3?0:1,raw_status=0x590000|service_status;
    if (!service_status) {
        state.panel_shadow[2]|=0x40;
        state.panel_shadow[0x3c]=2;state.panel_shadow[0x3d]=(unsigned char)size;
        state.panel_applied++;
    } else state.panel_invalid++;
    unsigned char *out=reply;
    static const unsigned char header[8]={0x0d,0x20,0x65,0x11,12,0,1,0x80};
    memcpy(out,header,8);put32(out+8,raw_status);io->set_source(reply,FULL_VDF_INPUT);
    unsigned long long serial=++state.next_lease;
    *slot=(struct lease){reply,dst,raw_status,serial,syscall(SYS_gettid),12,0x165};state.live_replies++;
    rc=io->send(dst,reply);
    if (rc) {
        state=before;state.panel_pending=state.panel_caller=0;memset(slot,0,sizeof *slot);
        cleanup(io,dst,reply,"panel-send-error-free");
        snprintf(line,sizeof line,"phase=panel-send destination=%#x rc=%d caller_owned=1 rollback=1",dst,rc);
        event(io,"FULL_VDF_TRANSPORT_FAILURE ",line);
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    state.queued++;
    char raw[25];hex(raw,out,12);
    snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x reply=%p lease=%llu bytes=12 service_status=%u raw_status=%#x raw=%s",
             syscall(SYS_gettid),state.panel_caller,FULL_VDF_INPUT,reply,serial,service_status,raw_status,raw);
    event(io,"FULL_VDF_PANEL_REPLY_QUEUED ",line);
    /* Original order: control shadow ->1118 completion -> cached resolution.
     * No pixel geometry is switched and the hardware-pending bit stays set. */
    if (!service_status) { state.panel_valid[1]=1;state.panel_size[1]=(unsigned char)size; }
    state.panel_pending=state.panel_caller=0;
    int freed=io->release(FULL_VDF_INPUT,request);
    if (freed) { state.faults++;state.retained_request=request; }else state.request_freed++;
    snprintf(line,sizeof line,"tid=%ld selector=2 size=%u service_status=%u raw_status=%#x shadow_flags=%#x shadow_selector=%u shadow_size=%u cached_valid=%u cached_size=%u reply=%p lease=%llu request_free_rc=%d pixels_switched=0",
             syscall(SYS_gettid),size,service_status,raw_status,state.panel_shadow[2],state.panel_shadow[0x3c],
             state.panel_shadow[0x3d],state.panel_valid[1],state.panel_size[1],reply,serial,freed);
    event(io,freed?"FULL_VDF_FAULT ":"FULL_VDF_PANEL_COMMIT ",line);
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}

int full_vdf_reverse_dispatch(unsigned int destination,void *request,
                             const struct full_imaging_io *io,int enabled,int *result) {
    if(enabled!=1 || destination!=FULL_VDF_INPUT || !request || !io || !io->size || !result)return 0;
    unsigned int bytes=io->size(request);const unsigned char *in=request;
    if(bytes<4 || u16(in)!=0x200d || u16(in+2)!=0x119)return 0;
    if(!io->source || !io->allocate || !io->release || !io->send || !io->set_source)
        return reject(io,result,"reverse-missing-transport");
    if(bytes!=28 || u16(in+4)!=28 || u16(in+6)!=0x8001 || in[8]>1 || in[9]>1 || in[10])
        return reject(io,result,"reverse-only-immediate-hv-no-osd-subset");
    for(unsigned int i=11;i<28;i++)if(in[i])return reject(io,result,"reverse-nonzero-mode-or-reserved-subset");
    unsigned int dst=io->source(request),h=in[8],v=in[9];
    if(dst>>28!=8 || !(dst&0xfffffff) || dst==0x81b40549)
        return reject(io,result,"reverse-only-observed-dynamic-ap-source");
    char raw[57],line[600];hex(raw,in,28);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x bytes=28 raw=%s",syscall(SYS_gettid),dst,destination,raw);
    event(io,"FULL_VDF_REVERSE_REQUEST ",line);
    void *reply=0;int rc=io->allocate(dst,&reply,12,1);
    pthread_mutex_lock(&mutex);struct lease *slot=0;int duplicate=reply && reply==request;
    for(unsigned int i=0;i<8;i++){
        if(reply && replies[i].pointer==reply)duplicate=1;
        if(!replies[i].pointer && !slot)slot=&replies[i];
    }
    if(duplicate){state.faults++;event(io,"FULL_VDF_FAULT ","reverse-allocator-alias");pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    if(rc || !reply || !slot || state.faults){
        if(reply)cleanup(io,dst,reply,"reverse-allocation-cleanup");
        pthread_mutex_unlock(&mutex);*result=rc?rc:-1021;return 1;
    }
    if(io->size(reply)!=12){cleanup(io,dst,reply,"reverse-wrong-size");pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    struct full_vdf_snapshot before=state;
    unsigned char internal[20]={1,0x20,1,1,20,0,1,0};internal[8]=(unsigned char)h;internal[9]=(unsigned char)v;
    memcpy(state.reverse_internal,internal,sizeof internal);
    /* CPVA6db93a stores defined {0,h,v} fields; virtual trailing word is zero.
     * The virtual consumer owns that byte, not the absent panel/EVF driver. */
    state.reverse_properties[0]=state.reverse_properties[3]=0;
    state.reverse_properties[1]=state.reverse_internal[8]==1;
    state.reverse_properties[2]=state.reverse_internal[9]==1;
    state.reverse_osd=state.reverse_internal[10];
    state.reverse_control=2*state.reverse_properties[1]+state.reverse_properties[2];
    state.reverse_control_consumed++;state.reverse_applied++;
    unsigned char *out=reply;
    static const unsigned char header[8]={0x0d,0x20,0x19,0x11,12,0,1,0x80};
    memcpy(out,header,8);put32(out+8,0);io->set_source(reply,FULL_VDF_INPUT);
    unsigned long long serial=++state.next_lease;long tid=syscall(SYS_gettid);
    *slot=(struct lease){reply,dst,0,serial,tid,12,0x119};state.live_replies++;
    rc=io->send(dst,reply);
    if(rc){state=before;memset(slot,0,sizeof *slot);cleanup(io,dst,reply,"reverse-send-cleanup");pthread_mutex_unlock(&mutex);*result=rc;return 1;}
    state.queued++;hex(raw,out,12);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x reply=%p lease=%llu bytes=12 raw_status=0 raw=%s",tid,FULL_VDF_INPUT,dst,reply,serial,raw);
    event(io,"FULL_VDF_REVERSE_REPLY_QUEUED ",line);
    int freed=io->release(FULL_VDF_INPUT,request);
    if(freed){state.faults++;state.retained_request=request;}else state.request_freed++;
    snprintf(line,sizeof line,"tid=%ld hrev=%u vrev=%u osdrev=%u properties=0,%u,%u,0 control_destination=0x027d0728 control=%u control_readback=%u consumed=%llu applied=%llu timing=0 owner=virtual-panel-config reply=%p lease=%llu request_free_rc=%d hardware_driver_executed=0 pixels_flipped=0 camera_startup_verified=0",
             tid,h,v,state.reverse_osd,state.reverse_properties[1],state.reverse_properties[2],state.reverse_control,state.reverse_control,
             state.reverse_control_consumed,state.reverse_applied,reply,serial,freed);
    event(io,freed?"FULL_VDF_FAULT ":"FULL_VDF_REVERSE_COMMIT ",line);
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}

int full_vdf_dispatch(unsigned int destination,void *request,
                      const struct full_imaging_io *io,int enabled,int *result) {
    if (destination!=FULL_VDF_CP && destination!=FULL_VDF_INPUT) return 0;
    pthread_mutex_lock(&mutex);
    int config_changed=!state.configured || state.enabled!=(unsigned int)(enabled==1);
    state.enabled=enabled==1;state.configured=1;
    pthread_mutex_unlock(&mutex);
    if (config_changed && io && io->record)
        io->record("FULL_VDF_CONFIG ",enabled==1?"enabled=1 profile=timecode virtual_config_only=1":"enabled=0 profile=off");
    if (enabled!=1) return 0;
    if (destination==FULL_VDF_INPUT) {
        if (request && io && io->size && result && io->size(request)>=4 &&
            u16(request)==0x200d && u16((unsigned char *)request+2)==0x165)
            return panel_resolution(request,io,result);
        return 0;
    }
    if (!io || !result) return 0;
    if (!request || !io->allocate || !io->release || !io->set_source ||
        !io->send || !io->size || !io->source) return reject(io,result,"missing-transport");
    unsigned int bytes=io->size(request),source=io->source(request);
    const unsigned char *in=request;
    char raw[105],line[640];
    hex(raw,in,bytes<52?bytes:52);
    snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x bytes=%u raw=%s",
             syscall(SYS_gettid),destination,source,bytes,raw);
    event(io,"FULL_VDF_REQUEST ",line);
    if ((bytes!=52 && bytes!=40) || u32(in+4)!=0xa0a0a0a0 || u16(in+8)!=1 ||
        u16(in+10)!=bytes || u32(in+12)!=24 || u32(in+16)!=bytes ||
        u16(in+24)!=0x2001 || u16(in+28)!=bytes-24 || u16(in+30)!=1 ||
        !((bytes==52 && u16(in+26)==0x0205) || (bytes==40 && u16(in+26)==0x020b)))
        return reject(io,result,"unknown-command-or-envelope");
    unsigned int dst=u32(in);
    /* AP local IDs include dynamic 0x81xxxxxx IDs. A zero replySID suppresses
     * replies but still requires a local AP source. Never route to CP/global. */
    if ((source>>28)!=8 || !(source&0x0fffffff) || (dst && dst!=source))
        return reject(io,result,"nonlocal-or-mismatched-reply-source");
    if (u16(in+26)==0x020b) return evf_subscribe(request,io,result);
    const unsigned char *data=in+32;
    unsigned int status=data[12]>=3 || !data[0] || data[1]>=2;
    if (!status && !supported(data)) return reject(io,result,"data-outside-evidenced-subset");
    pthread_mutex_lock(&mutex);
    int faulted=state.faults!=0;
    pthread_mutex_unlock(&mutex);
    if (faulted) return reject(io,result,"ownership-fault-gate");
    /* Allocation may block on a previous receiver; do not hold the state lock. */
    void *reply=0;
    int rc=dst?io->allocate(dst,&reply,36,1):0;
    pthread_mutex_lock(&mutex);
    struct lease *slot=0;
    int duplicate=reply && reply==request;
    for (unsigned int i=0;i<8;i++) {
        if (replies[i].pointer==reply && reply) duplicate=1;
        if (!replies[i].pointer && !slot) slot=&replies[i];
    }
    if (duplicate) {
        state.faults++;
        event(io,"FULL_VDF_FAULT ","allocator-returned-live-message-pointer; no-free-or-commit");
        pthread_mutex_unlock(&mutex);return reject(io,result,"duplicate-reply-ownership");
    }
    if (rc || (dst && !reply)) {
        snprintf(line,sizeof line,"phase=allocate destination=%#x rc=%d null_reply=%u caller_owned=1",
                 dst,rc,reply==0);
        event(io,"FULL_VDF_TRANSPORT_FAILURE ",line);
        if (reply) cleanup(io,dst,reply,"allocate-error-free");
        pthread_mutex_unlock(&mutex);*result=rc?rc:-1021;return 1;
    }
    if (state.faults || (dst && !slot)) {
        if (reply) cleanup(io,dst,reply,"rejected-reply-free");
        pthread_mutex_unlock(&mutex);return reject(io,result,"fault-or-full-leases");
    }
    struct full_vdf_snapshot before=state;
    if (!status) apply(data);else state.invalid++;
    unsigned long long serial=0;
    if (dst) {
        unsigned char *out=reply;
        memset(out,0,36);put32(out+4,0xa0a0a0a0);
        out[8]=1;out[10]=36;put32(out+12,24);put32(out+16,36);
        memcpy(out+24,in+24,2);out[26]=5;out[27]=0x12;out[28]=12;
        memcpy(out+30,in+30,2);put32(out+32,status);
        io->set_source(reply,FULL_VDF_CP);
        serial=++state.next_lease;
        *slot=(struct lease){reply,dst,status,serial,syscall(SYS_gettid),36,0x0205};
        state.live_replies++;
        rc=io->send(dst,reply);
        if (rc) {
            state=before;memset(slot,0,sizeof *slot);
            snprintf(line,sizeof line,"phase=send destination=%#x reply=%p rc=%d caller_owned=1 rollback=1",
                     dst,reply,rc);
            event(io,"FULL_VDF_TRANSPORT_FAILURE ",line);
            cleanup(io,dst,reply,"send-error-free");
            pthread_mutex_unlock(&mutex);*result=rc;return 1;
        }
        state.queued++;
        char wire[73];hex(wire,out,36);
        snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x reply=%p lease=%llu status=%u bytes=36 raw=%s queued=%llu",
                 syscall(SYS_gettid),dst,FULL_VDF_CP,reply,serial,status,wire,state.queued);
        event(io,"FULL_VDF_REPLY_QUEUED ",line);
    }
    int freed=io->release(FULL_VDF_CP,request);
    if (freed) { state.faults++;state.retained_request=request; }
    else state.request_freed++;
    char packet[57];hex(packet,state.internal_packet,28);
    snprintf(line,sizeof line,
             "tid=%ld request=%p destination=%#x status=%u applied=%llu internal_destination=%#x mask=4 internal=%s cache_before=%u cache_after=%u hdmi_consumed=%llu reply=%p lease=%llu request_free_rc=%d camera_verified=0",
             syscall(SYS_gettid),request,dst,status,state.applied,FULL_VDF_HDMI,packet,
             before.hdmi_cache,state.hdmi_cache,state.hdmi_consumed,reply,serial,freed);
    event(io,freed?"FULL_VDF_FAULT ":"FULL_VDF_COMMIT ",line);
    pthread_mutex_unlock(&mutex);
    *result=0;return 1; /* Queue transfer is irreversible, even if request free faults. */
}

int full_vdf_release_reply(unsigned int destination,void *reply,
                          int (*release)(unsigned int,void *),
                          void (*record)(const char *,const char *),int *result) {
    if (!reply || !release || !result) return 0;
    struct lease found={0};
    pthread_mutex_lock(&mutex);
    for (unsigned int i=0;i<8;i++) if (replies[i].pointer==reply) {
        found=replies[i];
        if (found.destination!=destination) *result=-1021;
        else *result=release(destination,reply);
        if (*result) state.faults++;
        else {
            memset(&replies[i],0,sizeof replies[i]);state.live_replies--;
            state.native_freed++;
            if (found.sender==syscall(SYS_gettid)) state.waiter_freed++;
        }
        break;
    }
    if (found.pointer && record) {
        char line[320];long tid=syscall(SYS_gettid);
        snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected_destination=%#x reply=%p lease=%llu status=%u bytes=%u cmd=%#x rc=%d",
                 tid,found.sender,tid==found.sender,destination,found.destination,reply,
                 found.serial,found.status,found.bytes,found.command,*result);
        record(*result?"FULL_VDF_FAULT ":"FULL_VDF_NATIVE_REPLY_FREE ",line);
    }
    pthread_mutex_unlock(&mutex);return found.pointer!=0;
}
void full_vdf_snapshot(struct full_vdf_snapshot *out) {
    pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_VDF_TEST
void full_vdf_test_reset(void) {
    pthread_mutex_lock(&mutex);state=(struct full_vdf_snapshot){.hdmi_cache=1,.evf_status={0,1,0,0}};
    memset(replies,0,sizeof replies);pthread_mutex_unlock(&mutex);
}
#endif
