/* SPDX-License-Identifier: MIT */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "infrabb-connection.h"
#include "infrabb-device.h"
#include "pin-registry-core.h"
#include <stdio.h>
#include <string.h>
static struct post_bb bb_model;
static struct post_report last_post;
static unsigned int get16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int do_vef_in1_post(const struct full_imaging_io *io,const unsigned char *peer_reply){
    unsigned char trigger_frame[28]={2,0x20,8,0xf0,0x1c,0,1,0};
    struct full_vef_snapshot bb_pins,vef_pins;
    full_infrabb_snapshot(&bb_pins);full_vef_snapshot(&vef_pins);
    if(!bb_pins.initialized || !vef_pins.initialized || vef_pins.pins[1].state!=0 ||
       full_vef_current_record(0,trigger_frame+8,20))return POST_BAD_TRIGGER;
    if(!bb_model.initializations && post_bb_init(&bb_model,post_original_cold_cache,16))return POST_BAD_TRIGGER;
    for(unsigned int i=0;i<6;i++)bb_model.pin_states[i]=bb_pins.pins[i].state;
    struct pin_control_snapshot owner;pin_control_snapshot(&owner);
    if(!owner.bound && pin_control_open_guest(1)!=1){
        memset(&last_post,0,sizeof last_post);last_post.status=POST_ALLOC_FAILED;last_post.operation_rc=-1;
        if(io->record)io->record("FULL_INFRABB_POST_FAILURE ","binding-unavailable connection-not-rolled-back");
        return POST_ALLOC_FAILED;
    }
    struct post_trigger trigger={get16(trigger_frame),get16(trigger_frame+2),get16(trigger_frame+4),get16(trigger_frame+6),trigger_frame+8,20};
    struct post_message message;
    enum post_status status=post_produce(get16(peer_reply+0x1a),&trigger,&message,&last_post);
    if(status==POST_READY)status=post_consume(&bb_model,&message,&last_post);
    if(io->record){
        char text[640];
        snprintf(text,sizeof text,"status=%u rc=%d handle=%#x unit=%#x physical=%#llx bytes_read=%u fnv=%#llx format_valid=%u cache_changed=%u cache_updates=%u bb_in1_state=%u owner_state=%u owners=%u opens=%u retained=%u shares=%llu control_formats_only=1 pixels_consumed=0 virtual_cold_record=1 wire0104_verified=0",
            status,last_post.operation_rc,last_post.actual_handle,last_post.unit,last_post.physical,last_post.consumed_bytes,last_post.fnv,last_post.format_valid,
            last_post.cache_changed,last_post.cache_updates,bb_model.pin_states[1],last_post.refs_state,last_post.refs.owners,last_post.refs.opens,last_post.retained,last_post.after.shares);
        io->record("FULL_INFRABB_POST_CONSUMED ",text);
    }
    return status;
}
#define EDGE_TAG "INFRABB"
#define EDGE_DESCRIPTION "only-INFRABB-YC-OUT1-to-VEF-YC-IN1-cold-connection"
#define EDGE_SOURCE_CP FULL_INFRABB_CP
#define EDGE_SOURCE_REGISTRY full_infrabb_registry
#define EDGE_SOURCE_SNAPSHOT full_infrabb_snapshot
#define SOURCE_INDEX 1u
#define SOURCE_SLOT 5u
#define PEER_CP FULL_VEF_CP
#define PEER_INDEX 1u
#define PEER_SLOT 1u
#define PEER_REGISTRY full_vef_registry
#define PEER_SNAPSHOT full_vef_snapshot
#define EDGE_PASS_OTHER 1
#define EDGE_DIRECT_COMPLETION 1
#define EDGE_STATE_FORMAT_LABEL "source_callback_format_published"
#define EDGE_POST_PEER_REPLY(io,reply) do_vef_in1_post(io,reply)
#define EDGE_DISPATCH full_infrabb_connection_dispatch
#define EDGE_RELEASE full_infrabb_connection_release
#define EDGE_SNAPSHOT full_infrabb_connection_snapshot
#define EDGE_RESET full_infrabb_connection_state_reset
#include "pin-peer-connection.inc"
void full_infrabb_post_snapshot(struct post_report *out){
    if(!out)return;
    pthread_mutex_lock(&mutex);*out=last_post;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_PIN_CONNECTION_TEST
void full_infrabb_connection_test_reset(void){
    full_infrabb_connection_state_reset();
    pthread_mutex_lock(&mutex);memset(&bb_model,0,sizeof bb_model);memset(&last_post,0,sizeof last_post);pthread_mutex_unlock(&mutex);
}
#endif
