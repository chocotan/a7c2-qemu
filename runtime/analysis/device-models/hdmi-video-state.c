/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "hdmi-video-state.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_hdmi_video_state_snapshot state;
static full_hdmi_video_backup_reader backup_reader;
static full_hdmi_video_kernel_observer kernel_observer;
static unsigned long long order;
/* CP f5a47758, raw 625846/6236d4. The ff object is registered, never set here. */
static const unsigned int condition_ids[13]={0,0x17,0x16,0x15,0x14,0x13,0x12,0x11,0x23,0x22,0x21,0xff,0x30};
/* Public CP raw e4fc5e, used only when the Backup read actually fails. */
static const unsigned char default_config[28]={
    0x92,0x9b,0x52,0xf4,0x8d,0x72,0x96,0x8c,0xc2,0x92,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0};
enum { PREFIX=1, CONDITION=2, UPM=3 };
struct lease {
    void *pointer;
    unsigned long long serial;
    unsigned int destination,source,bytes,kind,index;
    unsigned int sending,send_done,send_failed,releasing,freed,received,cleanup,retained;
    long sender,receiver;
    unsigned char raw[20];
};
/* At most 3 prefix replies, 2 UPM jobs and 24 condition notifications. */
static struct lease leases[32];

static unsigned int le16(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8;}
static unsigned int le32(const unsigned char *p) {
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
static void put16(unsigned char *p,unsigned int value) {p[0]=(unsigned char)value;p[1]=(unsigned char)(value>>8);}
static void put32(unsigned char *p,unsigned int value) {
    for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(value>>(i*8));
}
static int process(void) {return atomic_load(&owner_pid)==(int)getpid();}
static void fault_locked(int history_unknown) {
    state.faults++;state.ready=0;
    if(history_unknown)state.history_known=0;
}
static void note(const struct full_imaging_io *io,const char *tag,const char *text) {
    if(io && io->record)io->record(tag,text);
}
static int transport(const struct full_imaging_io *io) {
    return io && io->allocate && io->release && io->set_source && io->send && io->size && io->source;
}
static void wire(const struct full_imaging_io *io,const char *tag,const struct lease *l,int rc) {
    char raw[41],line[384];
    for(unsigned int i=0;i<l->bytes;i++)snprintf(raw+i*2,3,"%02x",l->raw[i]);
    raw[l->bytes*2]=0;
    snprintf(line,sizeof line,"tid=%ld source=%#x destination=%#x pointer=%p lease=%llu kind=%u index=%u bytes=%u raw=%s rc=%d original_cp_executed=0 hardware_verified=0 capture_verified=0",
             syscall(SYS_gettid),l->source,l->destination,l->pointer,l->serial,l->kind,l->index,l->bytes,raw,rc);
    note(io,tag,line);
}
static struct lease *find(void *pointer) {
    for(unsigned int i=0;i<32;i++)if(leases[i].pointer==pointer)return &leases[i];
    return NULL;
}
static void retire(struct lease *l) {
    if(l->freed && l->send_done && !l->releasing)memset(l,0,sizeof *l);
}
static void retain(struct lease *l) {
    if(!l->retained) {l->retained=1;state.retained_messages++;}
}
static void freed(struct lease *l) {
    l->freed=1;state.live_messages--;
    if(l->retained) {l->retained=0;state.retained_messages--;}
}
static int cleanup(const struct full_imaging_io *io,struct lease *l) {
    struct lease saved;
    pthread_mutex_lock(&mutex);
    if(l->releasing || l->freed) {pthread_mutex_unlock(&mutex);return 0;}
    l->releasing=1;l->cleanup=1;saved=*l;
    pthread_mutex_unlock(&mutex);
    int rc=io->release(saved.destination,saved.pointer);
    pthread_mutex_lock(&mutex);
    l->releasing=0;
    if(rc) {fault_locked(0);retain(l);}
    else freed(l);
    retire(l);pthread_mutex_unlock(&mutex);
    wire(io,rc?"FULL_HDMI_VIDEO_STATE_FAULT ":"FULL_HDMI_VIDEO_STATE_CLEANUP_FREE ",&saved,rc);
    return rc;
}
/* Publish before send; a successful inline or concurrent free keeps its lease
 * until send returns. Never dereference the message after publishing it. */
static int send_message(const struct full_imaging_io *io,unsigned int destination,unsigned int source,
                        unsigned int kind,unsigned int index,const unsigned char *raw,unsigned int bytes,void *request) {
    pthread_mutex_lock(&mutex);int available=0;
    for(unsigned int i=0;i<32;i++)if(!leases[i].pointer)available=1;
    if(!available || state.faults) {fault_locked(0);pthread_mutex_unlock(&mutex);return -1021;}
    pthread_mutex_unlock(&mutex);
    void *pointer=NULL;
    int rc=io->allocate(destination,&pointer,bytes,kind==CONDITION?0:1);
    pthread_mutex_lock(&mutex);
    struct lease *slot=NULL;
    int alias=pointer && (pointer==request || pointer==state.retained_request || find(pointer));
    for(unsigned int i=0;i<32;i++)if(!leases[i].pointer && !slot)slot=&leases[i];
    if(alias || !slot || !pointer) {
        fault_locked(0);pthread_mutex_unlock(&mutex);
        note(io,"FULL_HDMI_VIDEO_STATE_FAULT ",alias?"allocator-returned-live-message":"allocation-failed-or-ledger-full");
        return rc?rc:-1021;
    }
    *slot=(struct lease){.pointer=pointer,.serial=++state.next_lease,.destination=destination,
        .source=source,.bytes=bytes,.kind=kind,.index=index,.sender=syscall(SYS_gettid)};
    memcpy(slot->raw,raw,bytes);state.live_messages++;
    pthread_mutex_unlock(&mutex);
    if(rc) {cleanup(io,slot);pthread_mutex_lock(&mutex);fault_locked(0);slot->send_done=1;retire(slot);pthread_mutex_unlock(&mutex);return rc;}
    if(io->size(pointer)!=bytes) {
        pthread_mutex_lock(&mutex);fault_locked(0);slot->send_done=1;pthread_mutex_unlock(&mutex);
        cleanup(io,slot);return -1021;
    }
    memcpy(pointer,raw,bytes);io->set_source(pointer,source);
    if(io->source(pointer)!=source || memcmp(pointer,raw,bytes)) {
        pthread_mutex_lock(&mutex);fault_locked(0);slot->send_done=1;pthread_mutex_unlock(&mutex);
        cleanup(io,slot);return -1021;
    }
    pthread_mutex_lock(&mutex);
    if(state.faults) {slot->send_done=1;pthread_mutex_unlock(&mutex);cleanup(io,slot);return -1021;}
    struct lease saved=*slot;
    if(kind==PREFIX)state.prefix_queued++;
    else if(kind==CONDITION)state.condition_message_count++;
    else state.upm_message_count++;
    pthread_mutex_unlock(&mutex);
    wire(io,"FULL_HDMI_VIDEO_STATE_MESSAGE_PUBLISHED ",&saved,0);
    pthread_mutex_lock(&mutex);
    if(state.faults) {slot->send_done=1;pthread_mutex_unlock(&mutex);cleanup(io,slot);return -1021;}
    full_hdmi_video_kernel_observer observer=kind==UPM?kernel_observer:NULL;
    unsigned char effective[16]={0};
    if(observer){memcpy(effective,saved.raw,16);if(index==1)put32(effective+4,state.upm_effective_second_id);}
    slot->sending=1;pthread_mutex_unlock(&mutex);
    if(observer && observer(0,saved.serial,pointer,saved.raw,effective,io->record)) {
        pthread_mutex_lock(&mutex);slot->sending=0;slot->send_done=1;slot->send_failed=1;fault_locked(0);pthread_mutex_unlock(&mutex);
        cleanup(io,slot);return -1021;
    }
    rc=io->send(destination,pointer);
    int sent=rc==0;
    if(sent && observer)rc=observer(1,saved.serial,pointer,saved.raw,effective,io->record);
    pthread_mutex_lock(&mutex);
    slot->sending=0;slot->send_done=1;slot->send_failed=rc!=0;
    if(rc)fault_locked(0);
    if(sent && observer) {
        if(rc)retain(slot);
        else {slot->received=1;state.upm_received++;freed(slot);state.upm_consumed++;}
    }
    /* A sent message with an incomplete kernel receipt may already be freed. */
    int needs_cleanup=rc && !(sent && observer) && !slot->freed && !slot->releasing;
    retire(slot);pthread_mutex_unlock(&mutex);
    if(sent && observer && !rc)wire(io,"FULL_HDMI_VIDEO_STATE_KERNEL_RETIRED ",&saved,0);
    wire(io,rc?"FULL_HDMI_VIDEO_STATE_SEND_FAULT ":"FULL_HDMI_VIDEO_STATE_MESSAGE_SENT ",&saved,rc);
    if(needs_cleanup)cleanup(io,slot);
    return rc;
}

int full_hdmi_video_state_owner_init(void) {
    int pid=(int)getpid(),expected=0;
    int first=atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    if(!process())return -1021;
    struct full_hdmi_snapshot shared={0};
    if(first)full_hdmi_snapshot(&shared);
    pthread_mutex_lock(&mutex);
    if(first) {
        state.owner_pid=pid;state.initialized=1;state.history_known=1;
        /* Initializing is known only when constructed before any HDMI input. */
        if(shared.known || shared.resolution_known || shared.applied || shared.queries || shared.rate_requests ||
           shared.resolution_applied || shared.resolution_queries || shared.pending || shared.live_replies ||
           shared.retained_request || shared.retained_reply || shared.faults || shared.audio_pin_connected_writes)
            fault_locked(1);
        else {state.state_id=FULL_HDMI_VIDEO_INITIALIZING;state.current_initializing=1;}
        state.platform_p60=2;state.platform_p28_known=1;
        state.sync_handle=1;state.monitor_handle=2;
    }
    int rc=state.initialized && !state.faults?0:-1021;pthread_mutex_unlock(&mutex);return rc;
}
int full_hdmi_video_state_bind_backup(full_hdmi_video_backup_reader reader) {
    if(!process() || !reader)return -1021;
    pthread_mutex_lock(&mutex);
    int rc=-1021;
    if(!state.faults && !state.pending && !state.connect_started && (!backup_reader || backup_reader==reader)) {
        backup_reader=reader;state.backup_bound=1;rc=0;
    }
    pthread_mutex_unlock(&mutex);return rc;
}
int full_hdmi_video_state_bind_kernel_observer(full_hdmi_video_kernel_observer observer) {
    if(!process() || !observer)return -1021;
    pthread_mutex_lock(&mutex);
    int rc=-1021;
    if(!state.faults && !state.pending && !state.connect_started && (!kernel_observer || kernel_observer==observer)) {
        kernel_observer=observer;rc=0;
    }
    pthread_mutex_unlock(&mutex);return rc;
}
static int reject(const struct full_imaging_io *io,int *result,const char *why,int unknown) {
    pthread_mutex_lock(&mutex);fault_locked(unknown);pthread_mutex_unlock(&mutex);
    note(io,"FULL_HDMI_VIDEO_STATE_UNSUPPORTED ",why);*result=-1021;return 1;
}
int full_hdmi_video_state_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                    int enabled,int *result) {
    if(destination!=FULL_HDMI_CP || enabled!=FULL_HDMI_VIDEO_STATE_PROFILE || !request || !result)return 0;
    if(!process()) {*result=-1021;return 1;}
    if(!transport(io))return reject(io,result,"missing-transport",1);
    unsigned int bytes=io->size(request);const unsigned char *in=request;
    /* The observed Get is a48B Dataflow envelope, not a bare1000 packet.
     * Owned Connect endpoints must run before this dispatcher. */
    if(bytes==48 && le32(in+4)==0xa0a0a0a0u && le16(in+8)==1 && le16(in+10)==48 &&
       le32(in+12)==24 && le32(in+16)==48 && le16(in+24)==0x1000 && !le16(in+26) &&
       le16(in+28)==24 && le16(in+30)==2)return 0;
    if(bytes<4 || le16(in)!=0x2500)return reject(io,result,"unknown-state-input",1);
    unsigned int command=le16(in+2);
    int delegated=command==0x010a || command==0x020a || command==0x0101 || command==0x0201 || command==0x0117;
    if(!delegated && command!=0x0102 && command!=0x0109 && command!=0x0127)
        return reject(io,result,"unknown-HDMI-state-command",1);
    if(!delegated && (bytes!=12 || le16(in+4)!=12 || le16(in+6)!=1))
        return reject(io,result,"prefix-envelope",1);
    unsigned int caller=io->source(request);
    if((caller>>28)!=8 || !(caller&0x0fffffff))return reject(io,result,"nonlocal-caller",1);
    unsigned int payload=delegated?0:le32(in+8);
    if(command==0x0127 && payload && ((payload>>28)!=8 || !(payload&0x0fffffff)))
        return reject(io,result,"condition-subscription-domain",1);
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.history_known || state.pending || state.connect_started || !state.current_initializing) {
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    state.pending=1;pthread_mutex_unlock(&mutex);
    if(delegated) {
        /* The pre-existing owner remains the only writer of definition,
         * resolution, rates, and the edge13 audio-connected byte. */
        int handled=full_hdmi_dispatch(destination,request,io,FULL_HDMI_BOOT,result);
        pthread_mutex_lock(&mutex);state.pending=0;
        if(!handled || *result)fault_locked(1);
        pthread_mutex_unlock(&mutex);
        if(!handled)*result=-1021;
        return 1;
    }
    unsigned int status=0;
    pthread_mutex_lock(&mutex);
    if(command==0x0102) {
        /* 623c56 stores the raw byte, then parameter6 normalizes >=3 to0.
         * P+28=0 makes124612 return1 without a4808 job. */
        state.stored_g98=payload&255;state.platform_p60=state.stored_g98<3?state.stored_g98:0;
        state.prefix_received|=1;
    } else if(command==0x0109) {
        if((payload&255)>1)status=0xe0000001u;
        else {state.platform_p7c=payload&255;state.prefix_received|=2;}
    } else {
        state.registered_condition_sid=payload;
        for(unsigned int i=0;i<13;i++)state.condition_queues[i]=payload;
        state.prefix_received|=4;
    }
    pthread_mutex_unlock(&mutex);
    unsigned char reply[12]={0,0x25,0,0,12,0,1,0,0,0,0,0};
    put16(reply+2,command|0x8000);put32(reply+8,status);
    int rc=send_message(io,caller,FULL_HDMI_CP,PREFIX,command,reply,sizeof reply,request);
    int freed=rc?0:io->release(FULL_HDMI_CP,request);
    pthread_mutex_lock(&mutex);
    if(freed) {state.retained_request=request;fault_locked(0);}
    else if(!rc)state.request_freed++;
    state.pending=0;pthread_mutex_unlock(&mutex);
    *result=rc;return 1;
}

struct cold_input {
    unsigned char initialization[18],config[28];
    unsigned int g14c,g14d,g168,p190,g144,upm_second;
};
static int read_item(full_hdmi_video_backup_reader reader,unsigned int key,void *out,unsigned int cap,unsigned int *bytes) {
    *bytes=0;
    int rc=reader(key,out,cap,bytes);
    pthread_mutex_lock(&mutex);state.backup_reads++;pthread_mutex_unlock(&mutex);
    return rc;
}
static int cold_input(full_hdmi_video_backup_reader reader,struct cold_input *out) {
    unsigned char byte=0,model[17]={0},upm[8]={0};unsigned int n=0;
    memset(out,0,sizeof *out);out->initialization[0]=5;
    int rc=read_item(reader,0x010d008d,&byte,1,&n);
    if(!rc && n)out->initialization[0]=byte==2?6:5;
    rc=read_item(reader,0x003e0005,model,sizeof model,&n);
    if(!rc && n)memcpy(out->initialization+1,model,n<17?n:17);
    rc=read_item(reader,0x009a0001,out->config,sizeof out->config,&n);
    if(rc || !n)memcpy(out->config,default_config,sizeof out->config);
    const unsigned int keys[]={0x009a0009,0x009a000a,0x009a000b,0x009a000c};
    for(unsigned int i=0;i<4;i++) {
        unsigned char value[4]={0};unsigned int cap=i==3?4:1;
        rc=read_item(reader,keys[i],value,cap,&n);
        if(rc==1)return 1;
        if(rc || n!=cap)return -1021;
        if(i==0)out->g14c=value[0]!=0;
        else if(i==1)out->g14d=value[0]!=0;
        else if(i==2)out->p190=value[0];
        else out->g168=le32(value);
    }
    byte=1;rc=read_item(reader,0x010704fd,&byte,1,&n);
    out->g144=!rc && n==1 && !byte;
    rc=read_item(reader,0x00920085,upm,sizeof upm,&n);
    if(rc==1)return 1;
    if(rc || n<5 || n>sizeof upm)return -1021;
    out->upm_second=upm[4]?3:2;
    return 0;
}
/* Bounded virtual resource implementation of the proven fresh row0 branch.
 * These nodes and handles belong to this owner; they are not original CP RAM. */
struct descriptor {unsigned int owner,index,data;};
struct job {struct descriptor *descriptor;unsigned int number;struct job *next;};
struct node {unsigned int owner,bytes;unsigned char wake[4],data[12];struct node *next;};
static struct job *job_head;
static struct node *node_head[2];
static int queue_node(unsigned int handle,unsigned int index,unsigned int status,unsigned int data) {
    if(handle<1 || handle>2 || node_head[handle-1])return -1021;
    struct node *node=calloc(1,sizeof *node);
    if(!node)return -1021;
    node->owner=handle;node->bytes=12;put32(node->wake,1);
    put32(node->data,index);put32(node->data+4,status);put32(node->data+8,data);
    node_head[handle-1]=node;state.driver_nodes_queued++;return 0;
}
static int read_node(unsigned int handle,unsigned char out[12]) {
    if(handle<1 || handle>2)return -1021;
    struct node *node=node_head[handle-1];
    /* poll/op1 use the same resource; an unrelated handle cannot satisfy it. */
    if(!node || node->owner!=handle || node->bytes!=12)return -1021;
    unsigned char wake[4];memcpy(wake,node->wake,sizeof wake);state.driver_poll_calls++;
    if(le32(wake)!=1)return -1021;
    memset(node->wake,0,sizeof node->wake);state.driver_wake_reads++;
    memcpy(out,node->data,12);state.driver_nodes_read++;node_head[handle-1]=node->next;
    free(node);state.driver_nodes_freed++;return 0;
}
static int driver_exit(const struct cold_input *input) {
    if(state.driver_current_mode || state.driver_target_mode || state.driver_active || state.driver_dirty || job_head || node_head[0] || node_head[1])return -1021;
    /* 123e7c: monitor handle subscribes6000f before sync handle writes18B. */
    state.monitor_subscription=0x6000f;
    memcpy(state.initialization,input->initialization,18);
    memcpy(state.driver_initialization,input->initialization,18);state.driver_initialization[17]=0;
    state.driver_initialization_writes++;
    memcpy(state.platform_initialization,input->initialization,18);
    if(memcmp(state.initialization,state.platform_initialization,18) ||
       memcmp(state.initialization,state.driver_initialization,17) || state.driver_initialization[17])return -1021;
    memcpy(state.config,input->config,28);
    memset(state.platform_config,0,36);memcpy(state.platform_config+8,state.config,28);
    struct descriptor *descriptor=calloc(1,sizeof *descriptor);
    if(!descriptor)return -1021;
    struct job *job=calloc(1,sizeof *job);
    if(!job) {free(descriptor);state.driver_descriptors_freed++;return -1021;}
    *descriptor=(struct descriptor){state.sync_handle,7,le32(state.platform_config)};
    job->descriptor=descriptor;job->number=6;job_head=job;state.driver_jobs++;
    /* afe12a saves all36B; the job wrapper, descriptor and callback node have
     * distinct lifetimes. Slot4, row0/column8 is the original policy byte0. */
    memcpy(state.driver_config,state.platform_config,36);state.driver_config_writes++;
    if(memcmp(state.driver_config,state.platform_config,36) || le32(state.driver_config)>1 || le32(state.driver_config+4)>2)return -1021;
    state.driver_policy_slot=4;state.driver_policy_row=state.driver_current_mode;
    state.driver_policy_column=8;state.driver_policy=0;
    struct job *running=job_head;
    if(!running || running->number!=6 || running->descriptor->owner!=state.sync_handle)return -1021;
    int rc=queue_node(running->descriptor->owner,running->descriptor->index,0,running->descriptor->data);
    if(rc)return rc;
    free(running->descriptor);state.driver_descriptors_freed++;
    job_head=running->next;free(running);state.driver_jobs_consumed++;
    rc=read_node(state.sync_handle,state.completion);
    if(rc || le32(state.completion)!=7 || le32(state.completion+4) || le32(state.completion+8)!=le32(state.driver_config))return -1021;
    state.completion_owner=state.sync_handle;state.completion_index=le32(state.completion);
    state.g14c=input->g14c;state.g14d=input->g14d;state.g168=input->g168;
    state.platform_p190=input->p190;state.g144=input->g144;state.g13c=input->g144;
    state.monitoring_enabled=1;
    /* 480d queues the monitoring handle's distinct index1 cached HPD0 node. */
    return queue_node(state.monitor_handle,1,0,0);
}
static int conditions(const struct full_imaging_io *io,unsigned int batch) {
    for(unsigned int i=0;i<13;i++) {
        if(condition_ids[i]==0xff)continue;
        pthread_mutex_lock(&mutex);state.condition_flags[i]=1;
        unsigned int destination=state.condition_queues[i];pthread_mutex_unlock(&mutex);
        if(!destination)return -1021;
        unsigned char raw[20]={0};put32(raw,2);put32(raw+4,condition_ids[i]);put32(raw+8,1);
        int rc=send_message(io,destination,FULL_HDMI_VIDEO_CONDITION_SOURCE,CONDITION,batch*13+i,raw,sizeof raw,NULL);
        if(rc)return rc;
    }
    return 0;
}
static int prerequisites(void) {
    struct full_hdmi_snapshot shared;full_hdmi_snapshot(&shared);
    static const unsigned char resolution[6]={0,0,0,0,6,5},rates[5]={1,0,17,17,0};
    return !shared.faults && !shared.pending && !shared.live_replies && !shared.retained_request && !shared.retained_reply &&
        shared.known && !shared.definition && shared.applied && shared.resolution_known && shared.resolution_applied &&
        !memcmp(shared.resolution,resolution,6) && shared.rate_known_mask==31 && shared.rate_requests>=6 && !memcmp(shared.rates,rates,5);
}
static int ready_locked(void) {
    state.ready=!state.faults && state.history_known && state.exit_completed && state.entry_completed &&
        state.cached_hpd_completed && state.condition_message_count==24 && state.condition_received==24 &&
        state.condition_consumed==24 && state.upm_message_count==2 && state.upm_received==2 && state.upm_consumed==2 &&
        !state.live_messages && !state.retained_messages && !state.retained_request && !state.pending;
    return state.ready;
}
int full_hdmi_video_state_connect_begin(const struct full_imaging_io *io) {
    if(!process() || !transport(io))return -1021;
    pthread_mutex_lock(&mutex);
    if(state.faults || !state.history_known) {pthread_mutex_unlock(&mutex);return -1021;}
    if(state.pending) {pthread_mutex_unlock(&mutex);return 1;}
    if(state.entry_completed) {int rc=ready_locked()?0:1;pthread_mutex_unlock(&mutex);return rc;}
    if(state.prefix_received!=7 || state.prefix_queued!=state.prefix_native_freed ||
       !state.registered_condition_sid || !state.current_initializing || !state.platform_p28_known || state.platform_p28 ||
       state.stored_g98!=1 || state.platform_p60!=1 || state.platform_p7c || !backup_reader) {
        pthread_mutex_unlock(&mutex);return 1;
    }
    state.pending=1;full_hdmi_video_backup_reader reader=backup_reader;
    pthread_mutex_unlock(&mutex);
    /* A callback inside the old config owner sees pending before it could
     * reenter that owner's mutex. Never hold our lock while querying it. */
    if(!prerequisites()) {
        pthread_mutex_lock(&mutex);state.pending=0;pthread_mutex_unlock(&mutex);return 1;
    }
    struct cold_input input;int rc=cold_input(reader,&input);
    if(rc) {
        pthread_mutex_lock(&mutex);state.pending=0;if(rc<0)fault_locked(0);pthread_mutex_unlock(&mutex);
        note(io,rc<0?"FULL_HDMI_VIDEO_STATE_FAULT ":"FULL_HDMI_VIDEO_STATE_PENDING ","Backup-required-input-unavailable");
        return rc<0?-1021:1;
    }
    pthread_mutex_lock(&mutex);
    if(state.faults) {state.pending=0;pthread_mutex_unlock(&mutex);return -1021;}
    state.connect_started=1;state.video_g58=1;state.transition_order[0]=++order;
    rc=driver_exit(&input);
    if(!rc) {
        state.exit_completed=1;state.transition_order[1]=++order;
        state.current_initializing=0;state.current_hpd_low=1;state.state_id=FULL_HDMI_VIDEO_HPD_LOW;
        state.transition_order[2]=++order;state.upm_effective_second_id=input.upm_second;
        state.diagnostics_masked+=2;
    } else fault_locked(0);
    pthread_mutex_unlock(&mutex);
    if(!rc) {
        char line[384];char init[37],config[73];
        for(unsigned int i=0;i<18;i++)snprintf(init+2*i,3,"%02x",input.initialization[i]);
        unsigned char raw_config[36]={0};memcpy(raw_config+8,input.config,28);
        for(unsigned int i=0;i<36;i++)snprintf(config+2*i,3,"%02x",raw_config[i]);
        snprintf(line,sizeof line,"virtual_resource=1 initialization=%s config=%s job=6 slot=4 row=0 column=8 policy=0 completion=070000000000000000000000 same_owner_op1_read=1 node_freed=1 original_cp_executed=0 hardware_verified=0 capture_verified=0",init,config);
        note(io,"FULL_HDMI_VIDEO_STATE_DRIVER_CONSUMED ",line);
        for(unsigned int i=0;i<2 && !rc;i++) {
            unsigned char raw[16]={0};put32(raw,0x00920117);put32(raw+4,i?2:0);put32(raw+8,0x009a0000);
            rc=send_message(io,FULL_HDMI_VIDEO_UPM,FULL_HDMI_CP,UPM,i,raw,sizeof raw,NULL);
        }
    }
    if(!rc)rc=conditions(io,0);
    if(!rc) {
        unsigned char cached[12];pthread_mutex_lock(&mutex);
        rc=read_node(state.monitor_handle,cached);
        if(!rc && (le32(cached)!=1 || le32(cached+4) || le32(cached+8)))rc=-1021;
        if(!rc) {state.entry_completed=1;state.transition_order[3]=++order;state.diagnostics_masked++;}
        pthread_mutex_unlock(&mutex);
    }
    /* 625904 repeats setters even when the old flags are already1. */
    if(!rc)rc=conditions(io,1);
    pthread_mutex_lock(&mutex);
    if(rc)fault_locked(0);else state.cached_hpd_completed=1;
    state.pending=0;int ready=ready_locked();pthread_mutex_unlock(&mutex);
    note(io,rc?"FULL_HDMI_VIDEO_STATE_FAULT ":"FULL_HDMI_VIDEO_STATE_PENDING ",
         rc?"exit-entry-or-notification-failure":"waiting-for-actual-UPM-and-condition-receive-free");
    return rc?-1021:ready?0:1;
}
int full_hdmi_video_state_connect_ready(void) {
    if(!process())return 0;
    pthread_mutex_lock(&mutex);int ready=ready_locked();pthread_mutex_unlock(&mutex);return ready;
}
int full_hdmi_video_state_observe_receive(unsigned int id,void *pointer,unsigned int source,unsigned int bytes) {
    if(!process() || !pointer)return 0;
    pthread_mutex_lock(&mutex);struct lease *l=find(pointer);
    if(!l || l->freed || (l->kind==UPM && kernel_observer)) {pthread_mutex_unlock(&mutex);return 0;}
    int valid=l->sending || l->send_done;
    valid=valid && !l->send_failed && !l->freed && !l->releasing && !l->cleanup && !l->received &&
        id==l->destination && source==l->source && bytes==l->bytes;
    if(valid)valid=!memcmp(pointer,l->raw,l->bytes);
    if(!valid)fault_locked(0);
    else {
        l->received=1;l->receiver=syscall(SYS_gettid);
        if(l->kind==CONDITION)state.condition_received++;
        else if(l->kind==UPM)state.upm_received++;
    }
    pthread_mutex_unlock(&mutex);return valid?1:-1021;
}
int full_hdmi_video_state_release(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                                   void (*record)(const char *,const char *),int *result) {
    if(!process() || !pointer || !release || !result)return 0;
    pthread_mutex_lock(&mutex);struct lease *l=find(pointer);
    if(!l || l->freed || (l->kind==UPM && kernel_observer)) {pthread_mutex_unlock(&mutex);return 0;}
    struct lease saved=*l;long tid=syscall(SYS_gettid);
    int allowed=!l->releasing && !l->freed && !l->cleanup && destination==l->destination &&
        (l->sending || (l->send_done && !l->send_failed));
    if(l->kind!=PREFIX)allowed=allowed && l->received && l->receiver==tid;
    unsigned char expected[20];memcpy(expected,l->raw,l->bytes);
    if(l->kind==UPM && l->index==1)put32(expected+4,state.upm_effective_second_id);
    if(allowed)allowed=!memcmp(pointer,expected,l->bytes);
    if(!allowed) {
        fault_locked(0);retain(l);*result=-1021;pthread_mutex_unlock(&mutex);
        if(record)record("FULL_HDMI_VIDEO_STATE_FREE_REJECTED ","wrong-owner-thread-payload-or-unobserved-receive retained=1 consumed=0");
        return 1;
    }
    l->releasing=1;pthread_mutex_unlock(&mutex);
    int rc=release(destination,pointer);
    pthread_mutex_lock(&mutex);l->releasing=0;*result=rc;
    if(rc) {fault_locked(0);retain(l);}
    else {
        freed(l);
        if(l->kind==PREFIX) {state.prefix_native_freed++;if(l->sender==tid)state.prefix_waiter_freed++;}
        else if(l->kind==CONDITION)state.condition_consumed++;
        else state.upm_consumed++;
    }
    retire(l);ready_locked();pthread_mutex_unlock(&mutex);
    if(record) {
        char line[320];snprintf(line,sizeof line,"tid=%ld receiver=%ld sender=%ld destination=%#x pointer=%p lease=%llu kind=%u bytes=%u rc=%d received=%u consumed=%u original_cp_executed=0 hardware_verified=0 capture_verified=0",
            tid,saved.receiver,saved.sender,destination,pointer,saved.serial,saved.kind,saved.bytes,rc,saved.received,!rc);
        record(rc?"FULL_HDMI_VIDEO_STATE_FREE_FAULT ":"FULL_HDMI_VIDEO_STATE_NATIVE_FREE ",line);
    }
    return 1;
}
void full_hdmi_video_state_snapshot(struct full_hdmi_video_state_snapshot *out) {
    if(!out)return;
    if(!process()) {memset(out,0,sizeof *out);return;}
    pthread_mutex_lock(&mutex);ready_locked();*out=state;pthread_mutex_unlock(&mutex);
}
#ifdef FULL_HDMI_VIDEO_STATE_TEST
void full_hdmi_video_state_test_reset(void) {
    pthread_mutex_lock(&mutex);
    while(job_head) {struct job *next=job_head->next;free(job_head->descriptor);free(job_head);job_head=next;}
    for(unsigned int i=0;i<2;i++)while(node_head[i]) {struct node *next=node_head[i]->next;free(node_head[i]);node_head[i]=next;}
    memset(&state,0,sizeof state);memset(leases,0,sizeof leases);backup_reader=NULL;kernel_observer=NULL;order=0;
    atomic_store(&owner_pid,0);pthread_mutex_unlock(&mutex);
}
#endif
