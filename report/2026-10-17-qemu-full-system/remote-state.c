/* SPDX-License-Identifier: MIT */
#include "remote-state.h"
#include <string.h>
#include <pthread.h>
#include <stdio.h>
static unsigned int command(const unsigned char *b) {
    return (unsigned int)b[0]|(unsigned int)b[1]<<8|(unsigned int)b[2]<<16|(unsigned int)b[3]<<24;
}
int remote_state_apply(struct remote_state *s,const void *message,unsigned int size) {
    if(!s || !message || size!=REMOTE_STATE_WIRE_BYTES)return -1;
    const unsigned char *b=message;
    unsigned int op=command(b);
    if(op!=0x2300 && op!=0x2301 && op!=0x2302 && op!=0x2303 && op!=0x2304)return -1;
    int changed=0;
    if(op==0x2300) {
        /* libObj+19e9dc copies exactly 0x598 bytes from GpsComBufferGetAll. */
        changed=!s->gps_seen || memcmp(s->gps_bytes,b+8,sizeof s->gps_bytes);
        memcpy(s->gps_bytes,b+8,sizeof s->gps_bytes);s->gps_seen=1;
        if(changed)s->gps_generation++;
    } else if(op==0x2304) {
        /* PsmGpsApiInit +193de8..193e38: 36 config bytes at +8, including
         * the Backup byte overwritten at wire+0x2a. All other bytes are opaque. */
        changed=!s->gps_init_seen || memcmp(s->gps_configuration,b+8,sizeof s->gps_configuration);
        memcpy(s->gps_configuration,b+8,sizeof s->gps_configuration);s->gps_init_seen=1;
    } else if(op==0x2303) {
        changed=!s->snapshot_seen || memcmp(s->bytes,b+8,REMOTE_STATE_BYTES);
        memcpy(s->bytes,b+8,REMOTE_STATE_BYTES);
        s->snapshot_seen=1;
        if(changed)s->generation++;
    } else {
        changed=!s->control_seen || s->control_command!=op;
        s->control_seen=1;s->control_command=op;
    }
    /* Padding [4,8), [1496,1504) is uninitialized in the original producer.
     * Controls initialize only [0,4); never inspect their remaining bytes. */
    s->requests++;return changed?1:0;
}
static struct remote_state state;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
int full_remote_state_dispatch(unsigned int id,void *message,unsigned int size,unsigned int source,
    int (*release)(unsigned int,void *),void (*record)(const char *,const char *)) {
    if(id!=REMOTE_STATE_SID || !release || !record)return -1024;
    if(!message || size!=REMOTE_STATE_WIRE_BYTES) return -1024;
    unsigned int op=command(message);
    /* 2300 sets source from the original GPS waitable thread's queue ID.
     * That dynamic local queue is unit a1, low-ID e000..ffff. Bind the first
     * valid stream source and reject a different thread until this process exits. */
    int gps_stream=op==0x2300;
    if((gps_stream && (source&0xffffe000u)!=0x00a1e000u) || (!gps_stream && source!=REMOTE_STATE_SID)) {
        char rejected[160];
        snprintf(rejected,sizeof rejected,"endpoint=%#x source=%#x bytes=%u reason=source sender_retains=1",id,source,size);
        record("FULL_REMOTE_STATE_REJECT ",rejected);return -1024;
    }
    pthread_mutex_lock(&mutex);
    if(gps_stream && state.gps_source && source!=state.gps_source) {
        char rejected[160];
        snprintf(rejected,sizeof rejected,"endpoint=%#x source=%#x bound=%#x reason=stream-owner sender_retains=1",id,source,state.gps_source);
        record("FULL_REMOTE_STATE_REJECT ",rejected);
        pthread_mutex_unlock(&mutex);return -1024;
    }
    int changed=remote_state_apply(&state,message,size);
    char text[320];
    if(changed<0) {
        snprintf(text,sizeof text,"endpoint=%#x source=%#x bytes=%u command=%#x sender_retains=1",id,source,size,size>=4?command(message):0);
        record("FULL_REMOTE_STATE_REJECT ",text);
        pthread_mutex_unlock(&mutex);return -1024;
    }
    if(gps_stream)state.gps_source=source;
    /* Preserve one complete effective snapshot and any changed snapshots in
     * bounded byte records. Do not leak uninitialized wire padding into state. */
    if(changed && (op==0x2303 || op==0x2300 || op==0x2304)) {
        const unsigned char *snapshot=op==0x2300?state.gps_bytes:op==0x2304?state.gps_configuration:state.bytes;
        unsigned int snapshot_bytes=op==0x2300?sizeof state.gps_bytes:op==0x2304?sizeof state.gps_configuration:sizeof state.bytes;
        unsigned long long generation=op==0x2300?state.gps_generation:op==0x2304?state.requests:state.generation;
        for(unsigned int offset=0;offset<snapshot_bytes;offset+=64) {
            unsigned int take=snapshot_bytes-offset;if(take>64)take=64;
            char hex[129];
            for(unsigned int i=0;i<take;i++)snprintf(hex+2*i,3,"%02x",snapshot[offset+i]);
            hex[2*take]=0;
            snprintf(text,sizeof text,"command=%#x generation=%llu offset=%u total=%u hex=%s",op,generation,offset,snapshot_bytes,hex);
            record("FULL_REMOTE_STATE_BYTES ",text);
        }
    }
    int rc=release(id,message);
    if(changed || state.requests<=8 || !(state.requests&(state.requests-1)) || rc) {
        snprintf(text,sizeof text,"endpoint=%#x source=%#x requests=%llu command=%#x control=%#x snapshot_seen=%u generation=%llu gps_init=%u gps_seen=%u gps_generation=%llu changed=%u original_free_rc=%d reply_sent=0 cp_render_verified=0",
            id,source,state.requests,op,state.control_command,state.snapshot_seen,state.generation,state.gps_init_seen,state.gps_seen,state.gps_generation,changed,rc);
        record(rc?"FULL_REMOTE_STATE_FAULT ":"FULL_REMOTE_STATE_CONSUMED ",text);
    }
    pthread_mutex_unlock(&mutex);return 0;
}
