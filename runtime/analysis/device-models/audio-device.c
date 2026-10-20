/* SPDX-License-Identifier: MIT */
/* Finite BB->ADF boot configuration. No physical driver or playback ACK. */
#define _GNU_SOURCE
#include "audio-device.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
/* Original 578e0a constructor: independent per-kind volume defaults to 7. */
static struct full_audio_snapshot state={.system_volume={
    7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7,7}};
static struct lease { void *pointer;unsigned int destination,bytes,command;long sender;unsigned long long serial; } replies[8];
static unsigned int u16(const unsigned char *p) { return p[0]|(unsigned int)p[1]<<8; }
static void put32(unsigned char *p,unsigned int n) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(n>>(8*i));
}
static void log_event(const struct full_imaging_io *io,const char *tag,const char *line) {
    if (io->record) io->record(tag,line);
}
static int reject(const struct full_imaging_io *io,int *result,const char *reason) {
    log_event(io,"FULL_AUDIO_UNSUPPORTED ",reason);*result=-1021;return 1;
}
static unsigned int normalized(unsigned int wire) { return !wire?0:wire<=16?wire-1:15; }
static int consume_control(unsigned int wire) {
    unsigned char control[64]={4};control[4]=(unsigned char)normalized(wire);
    /* Explicit virtual driver: op4 saves its level, then reads the same state
     * back. Nothing is sent to the original physical driver or DSP. */
    memcpy(state.driver_control,control,64);state.driver_level=state.driver_control[4];
    state.driver_consumed++;
    return memcmp(state.driver_control,control,64) || state.driver_level!=normalized(wire);
}
static int cleanup(const struct full_imaging_io *io,unsigned int dst,void *reply) {
    int rc=io->release(dst,reply);
    if (rc) {
        state.faults++;state.retained_reply=reply;
        char line[180];
        snprintf(line,sizeof line,"tid=%ld phase=temporary-reply-free destination=%#x reply=%p rc=%d",
                 syscall(SYS_gettid),dst,reply,rc);
        log_event(io,"FULL_AUDIO_FAULT ",line);
    }
    return rc;
}
static int dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                    int enabled,int capabilities,int *result) {
    if ((enabled!=FULL_AUDIO_VOLUME && enabled!=FULL_AUDIO_BOOT) || destination!=FULL_AUDIO_INPUT ||
        !request || !io || !result || !io->size)
        return 0;
    unsigned int bytes=io->size(request);const unsigned char *in=request;
    if (bytes<4) return 0;
    unsigned int command=u16(in+2),frame=u16(in);
    if (enabled==FULL_AUDIO_BOOT && frame==0x2004 && command==0x0203) {
        /* Record what the original playback request actually carries before
         * deciding anything: an id, a length, or PCM itself. Behaviour is not
         * changed here - the request is still refused - so no fake playback. */
        char line[240]; int used=snprintf(line,sizeof line,"bytes=%u head=",bytes);
        unsigned int head=bytes<48?bytes:48;
        for (unsigned int i=0;i<head && used>0 && used<(int)sizeof line-3;i++)
            used+=snprintf(line+used,sizeof line-(size_t)used,"%02x",in[i]);
        log_event(io,"FULL_AUDIO_PLAYBACK_REQUEST ",line);
        return reject(io,result,"0203-playback-not-supported");
    }
    if (frame!=0x200d) return 0;
    if (enabled==FULL_AUDIO_BOOT && command==0x032b)
        return reject(io,result,"032b-playback-not-supported");
    if (command!=0x0330 && (enabled!=FULL_AUDIO_BOOT ||
                           (command!=0x033f && command!=0x0329 && command!=0x032c && command!=0x032a &&
                            !(command==0x0327 && capabilities==FULL_AUDIO_CAPS_INPUTLESS))))
        return 0; /* The shared BB input also carries VDF/display controls. */
    if (!io->source || !io->allocate || !io->release || !io->set_source || !io->send)
        return reject(io,result,"missing-transport");
    unsigned int required=(command==0x0330 || command==0x032c || command==0x032a)?10:(command==0x033f || command==0x0327)?8:40;
    unsigned int reply_bytes=command==0x033f?24:command==0x0327?28:12;
    if (bytes!=required || u16(in+4)!=required || u16(in+6)!=0x8001)
        return reject(io,result,"command-envelope");
    unsigned int dst=io->source(request),wire=(command==0x0330 || command==0x032c || command==0x032a)?in[8]:0;
    unsigned int kind=command==0x0329?in[20]:command==0x032c?in[9]:0,regist=command==0x0329?in[22]:0;
    if ((dst>>28)!=8 || !(dst&0x0fffffff)) return reject(io,result,"nonlocal-reply-destination");
    if ((command==0x033f || command==0x0329) && full_sound_ready())
        return reject(io,result,"sound-owner-not-ready-or-readback-failed");
    if (command==0x0329 && (in[23]>1 || in[24]>1))
        return reject(io,result,"0329-original-assertion-domain");
    char line[600],raw[81];
    for (unsigned int i=0;i<bytes;i++) snprintf(raw+2*i,3,"%02x",in[i]);
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x command=%#x bytes=%u raw=%s",
             syscall(SYS_gettid),dst,destination,command,bytes,raw);
    log_event(io,"FULL_AUDIO_REQUEST ",line);
    pthread_mutex_lock(&lock);int faulted=state.faults!=0;pthread_mutex_unlock(&lock);
    if (faulted) return reject(io,result,"ownership-fault-gate");
    void *reply=0;int rc=io->allocate(dst,&reply,reply_bytes,1);
    pthread_mutex_lock(&lock);
    struct lease *slot=0;int duplicate=reply && reply==request;
    for (unsigned int i=0;i<8;i++) {
        if (reply && replies[i].pointer==reply) duplicate=1;
        if (!replies[i].pointer && !slot) slot=&replies[i];
    }
    if (duplicate) {
        state.faults++;log_event(io,"FULL_AUDIO_FAULT ","allocator-returned-live-message");
        pthread_mutex_unlock(&lock);return reject(io,result,"duplicate-message-ownership");
    }
    if (rc || !reply) {
        snprintf(line,sizeof line,"phase=allocate destination=%#x rc=%d null_reply=%u caller_owned=1",dst,rc,reply==0);
        log_event(io,"FULL_AUDIO_TRANSPORT_FAILURE ",line);
        if (reply) cleanup(io,dst,reply);
        pthread_mutex_unlock(&lock);*result=rc?rc:-1021;return 1;
    }
    if (state.faults || !slot) {
        cleanup(io,dst,reply);pthread_mutex_unlock(&lock);
        return reject(io,result,"fault-or-full-leases");
    }
    struct full_audio_snapshot before=state;
    unsigned int service_status=0;int table_index=-1;
    if (command==0x033f && full_sound_ready()) {
        cleanup(io,dst,reply);pthread_mutex_unlock(&lock);
        return reject(io,result,"sound-owner-response-readback-failed");
    }
    if (command==0x0329 && full_sound_table(state.table,in,&service_status,&table_index)) {
        state=before;cleanup(io,dst,reply);pthread_mutex_unlock(&lock);
        return reject(io,result,"0329-unsupported-owner-range-or-readback");
    }
    if (command==0x0330 && consume_control(wire)) {
        state=before;cleanup(io,dst,reply);pthread_mutex_unlock(&lock);
        return reject(io,result,"virtual-driver-readback-failed");
    }
    if (command==0x0330) { state.wire_volume=wire;state.known=1;state.applied++; }
    if (command==0x032a) {
        unsigned int mask=wire&7;
        if (!!state.system_path != !!mask) {
            /* Original CPVA67dd78/control127: idle owner only; playback is rejected. */
            state.path_control_argument=mask?0:1;
            state.path_register=(state.path_register&~1U)|(mask?1U:0U);
            state.path_control_consumed++;
        }
        state.system_path=mask;state.path_applied++;
    }
    unsigned int matched=0;
    if (command==0x032c) {
        if (wire>=8) service_status=0xe002;
        else {
            if (!kind) { memset(state.system_volume,(int)wire,sizeof state.system_volume);matched=FULL_SOUND_SLOTS; }
            else if (kind<=FULL_SOUND_SLOTS) { state.system_volume[kind-1]=(unsigned char)wire;matched=1; }
            state.system_volume_applied++;
        }
    }
    if (command==0x033f) state.queries++;
    if (command==0x0329 && !service_status) state.table_applied++;
    unsigned char capability_flags[16]={0};
    if (command==0x0327) {
        if (!state.capabilities.profile && !state.capabilities.error)
            full_audio_capabilities_inputless(&state.capabilities);
        service_status=full_audio_capabilities_read(&state.capabilities,capability_flags);
    }
    /* CP relay 1c6664/1c6666 ORs the ADF domain into the service status. */
    unsigned char completed[28]={0x0d,0x20,0,0x13,0,0,1,0x80};
    completed[2]=(unsigned char)command;completed[4]=(unsigned char)reply_bytes;
    put32(completed+8,0x580000|service_status);
    if (command==0x033f) {
        put32(completed+16,(unsigned int)SYSTEM_SOUND_AUDIO_PHYS64);
        put32(completed+20,(unsigned int)(SYSTEM_SOUND_AUDIO_PHYS64>>32));
    }
    if (command==0x0327) memcpy(completed+12,capability_flags,16);
    memcpy(reply,completed,reply_bytes);io->set_source(reply,FULL_AUDIO_INPUT);
    unsigned long long serial=++state.next_lease;
    *slot=(struct lease){reply,dst,reply_bytes,command,syscall(SYS_gettid),serial};state.live_replies++;
    rc=io->send(dst,reply);
    if (rc) {
        state=before;memset(slot,0,sizeof *slot);cleanup(io,dst,reply);
        snprintf(line,sizeof line,"phase=send destination=%#x reply=%p rc=%d caller_owned=1 rollback=1",dst,reply,rc);
        log_event(io,"FULL_AUDIO_TRANSPORT_FAILURE ",line);
        pthread_mutex_unlock(&lock);*result=rc;return 1;
    }
    state.queued++;
    for (unsigned int i=0;i<reply_bytes;i++) snprintf(raw+2*i,3,"%02x",completed[i]);
    snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x reply=%p lease=%llu command=%#x bytes=%u service_status=%#x raw_status=%#x raw=%s",
             syscall(SYS_gettid),dst,FULL_AUDIO_INPUT,reply,serial,command,reply_bytes,service_status,0x580000|service_status,raw);
    log_event(io,"FULL_AUDIO_REPLY_QUEUED ",line);
    int freed=io->release(FULL_AUDIO_INPUT,request);
    if (freed) { state.faults++;state.retained_request=request; }else state.request_freed++;
    if (command==0x0330) snprintf(line,sizeof line,"tid=%ld wire=%u level=%u previous_known=%u previous_wire=%u previous_level=%u control_op=4 driver_readback=%u applied=%llu consumed=%llu reply=%p lease=%llu request_free_rc=%d audio_output_verified=0",
             syscall(SYS_gettid),wire,state.driver_level,before.known,before.wire_volume,before.driver_level,
             state.driver_control[4],state.applied,state.driver_consumed,reply,serial,freed);
    else if (command==0x032a) snprintf(line,sizeof line,
             "tid=%ld command=0x32a wire=%u masked_path=%u previous_path=%u cached_path=%u path_readback=%u control_op=0x127 control_argument=%u control_consumed=%llu register_before=%#x register_after=%#x register_readback=%#x request_active=0 deferred_callback=0 applied=%llu reply=%p lease=%llu request_free_rc=%d audio_output_verified=0 camera_startup_verified=0",
             syscall(SYS_gettid),wire,wire&7,before.system_path,state.system_path,state.system_path,
             state.path_control_argument,state.path_control_consumed,before.path_register,state.path_register,
             state.path_register,state.path_applied,reply,serial,freed);
    else if (command==0x033f) snprintf(line,sizeof line,
             "tid=%ld command=0x33f physical=%#llx phys64=%#llx cpu=%#llx bytes=%lu capacity=%lu fnv64=%016llx owner_readback=1 mapping=read-only lifetime=process reply=%p lease=%llu request_free_rc=%d camera_startup_verified=0 audio_output_verified=0",
             syscall(SYS_gettid),SYSTEM_SOUND_PHYSICAL,SYSTEM_SOUND_AUDIO_PHYS64,SYSTEM_SOUND_BUS,
             SYSTEM_SOUND_BYTES,SYSTEM_SOUND_CAPACITY,SYSTEM_SOUND_FNV,reply,serial,freed);
    else if (command==0x032c) {
        unsigned int readback=kind>=1 && kind<=FULL_SOUND_SLOTS?state.system_volume[kind-1]:0;
        snprintf(line,sizeof line,"tid=%ld command=0x32c vol=%u kind=%u matched=%u service_status=%#x raw_status=%#x readback=%u applied=%llu reply=%p lease=%llu request_free_rc=%d audio_output_verified=0",
                 syscall(SYS_gettid),wire,kind,matched,service_status,0x580000|service_status,readback,
                 state.system_volume_applied,reply,serial,freed);
    } else if (command==0x0327) {
        char flags[33];for (unsigned int i=0;i<16;i++)snprintf(flags+2*i,3,"%02x",state.capabilities.flags[i]);
        snprintf(line,sizeof line,"tid=%ld command=0x327 owner=inputless valid=%u input_devices=%u pro=%u aip=%u znr=%u error=%#x service_status=%#x cached_flags=%s queries=%llu reply=%p lease=%llu request_free_rc=%d audio_input_verified=0 audio_output_verified=0 camera_startup_verified=0",
                 syscall(SYS_gettid),state.capabilities.valid,state.capabilities.input_devices,state.capabilities.pro,
                 state.capabilities.aip,state.capabilities.znr,state.capabilities.error,service_status,flags,
                 state.capabilities.queries,reply,serial,freed);
    } else {
        const struct full_sound_slot *entry=table_index<0?0:&state.table[table_index];
        snprintf(line,sizeof line,"tid=%ld command=0x329 kind=%u regist=%u slot=%d service_status=%#x offset=%#x size=%#x phys64=%#llx cpu=%#x fnv64=%016llx slice_readback=%u reply=%p lease=%llu request_free_rc=%d camera_startup_verified=0 audio_output_verified=0",
                 syscall(SYS_gettid),kind,regist,table_index,service_status,entry?entry->offset:0,
                 entry?entry->size:0,entry?SYSTEM_SOUND_AUDIO_PHYS64+entry->offset:0,entry?entry->cpu:0,
                 entry?entry->digest:0,entry && regist==1 && !service_status,reply,serial,freed);
    }
    log_event(io,freed?"FULL_AUDIO_FAULT ":"FULL_AUDIO_COMMIT ",line);
    pthread_mutex_unlock(&lock);*result=0;return 1;
}
int full_audio_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,int enabled,int *result) {
    return dispatch(destination,request,io,enabled,0,result);
}
int full_audio_dispatch_capabilities(unsigned int destination,void *request,const struct full_imaging_io *io,
                                     int enabled,int capabilities,int *result) {
    return dispatch(destination,request,io,enabled,capabilities,result);
}
int full_audio_release_reply(unsigned int destination,void *reply,int (*release)(unsigned int,void *),
                             void (*record)(const char *,const char *),int *result) {
    if (!reply || !release || !result) return 0;
    pthread_mutex_lock(&lock);struct lease found={0};
    for (unsigned int i=0;i<8;i++) if (replies[i].pointer==reply) {
        found=replies[i];
        *result=destination==found.destination?release(destination,reply):-1021;
        if (*result) state.faults++;
        else {
            memset(&replies[i],0,sizeof replies[i]);state.live_replies--;state.native_freed++;
            if (found.sender==syscall(SYS_gettid)) state.waiter_freed++;
        }
        break;
    }
    if (found.pointer && record) {
        char line[240];long tid=syscall(SYS_gettid);
        snprintf(line,sizeof line,"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu command=%#x bytes=%u rc=%d",
                 tid,found.sender,tid==found.sender,destination,found.destination,reply,found.serial,found.command,found.bytes,*result);
        record(*result?"FULL_AUDIO_FAULT ":"FULL_AUDIO_NATIVE_REPLY_FREE ",line);
    }
    pthread_mutex_unlock(&lock);return found.pointer!=0;
}
void full_audio_snapshot(struct full_audio_snapshot *out) {
    pthread_mutex_lock(&lock);*out=state;pthread_mutex_unlock(&lock);
}
int full_audio_replay_config(unsigned int *level) {
    pthread_mutex_lock(&lock);int rc=-1021;
    if (level && state.known && !state.faults && !consume_control(state.wire_volume)) {
        *level=state.driver_level;rc=0;
    }
    pthread_mutex_unlock(&lock);return rc;
}
#ifdef FULL_AUDIO_TEST
void full_audio_test_reset(void) {
    pthread_mutex_lock(&lock);state=(struct full_audio_snapshot){0};
    memset(state.system_volume,7,sizeof state.system_volume);
    memset(replies,0,sizeof replies);full_sound_test_reset();pthread_mutex_unlock(&lock);
}
void full_audio_test_capabilities_bind(const struct full_audio_capabilities *owner) {
    pthread_mutex_lock(&lock);state.capabilities=*owner;pthread_mutex_unlock(&lock);
}
#endif
