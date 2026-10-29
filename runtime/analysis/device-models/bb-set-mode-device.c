/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "bb-set-mode-device.h"
#include "bb-mode-config.h"
#include "bb-mode-work-queue.h"
#include "adf-set-output-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t sem5=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_bb_set_mode_snapshot state;
static struct full_bb_mode_config config_owner;
static struct full_bb_mode_work_queue queue_owner;
static struct full_imaging_io transport;
static struct full_adf_proc_guard reservation;
static const unsigned char state_initializer[32]={
    1,0,0,0,0,0,0,0, 0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0, 1,0,0,0,0,0,0,0
};
static const struct {uint32_t sid,data;} plane_roots[]={
    {0x90590819u,0x012468c8u},{0x9059081au,0x01238938u},
    {0x9059081bu,0x0123f8c8u},{0x9059081cu,0x0124d860u}
};
/* CP 201ad8 binds accessor+8 to these roots; f024 only writes D+fa/D+1680..+1920. */
static int plane_no_mode_alias(void) {
    for(unsigned int i=0;i<sizeof plane_roots/sizeof *plane_roots;i++) {
        uint32_t data=plane_roots[i].data,word=0x010efa3cu;
        if(plane_roots[i].sid!=0x90590819u+i || data>UINT32_MAX-0x1920u ||
           (data+0xfau>=word && data+0xfau<word+4u) ||
           (data+0x1680u<word+4u && data+0x1920u>word))return 0;
    }
    return 1;
}
static void *request_pointer,*live_reply,*retained_request,*retained_reply,*retained_cleanup;
static unsigned int request_owner,reply_owner,cleanup_owner,reply_sending,reply_freed,releasing_reply;

static int current_process(void) {
    int pid=(int)getpid(),expected=0;
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return atomic_load(&owner_pid)==pid;
}
static unsigned int u16(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p) {
    return u16(p)|u16(p+2)<<16;
}
static unsigned int known_count(const unsigned char *mask,unsigned int bytes) {
    unsigned int count=0;for(unsigned int i=0;i<bytes;i++)if(mask[i]==0xff)count++;return count;
}
static void event(const char *tag,const char *text) {
    if(transport.record)transport.record(tag,text);
}
static void log_unlocked(const char *tag,const char *text) {
    char line[1250];snprintf(line,sizeof line,
        "%s pid=%d tid=%ld original_cp_executed=0 hardware_verified=0 native_frequency_verified=0 original_event_identity_verified=0 pcm_verified=0 frames_verified=0 capture_verified=0",
        text,getpid(),syscall(SYS_gettid));event(tag,line);
}
/* State is published before observation; a logger may read the public snapshot. */
static void log_line(const char *tag,const char *text) {
    pthread_mutex_unlock(&mutex);log_unlocked(tag,text);pthread_mutex_lock(&mutex);
}
static int sem5_lock(void *context) {
    if(context!=&config_owner || pthread_mutex_lock(&sem5))return -1021;
    if(state.semaphore_busy){pthread_mutex_unlock(&sem5);return -1021;}
    state.semaphore_busy=1;state.semaphore_acquires++;return 0;
}
static int sem5_unlock(void *context) {
    if(context!=&config_owner || !state.semaphore_busy)return -1021;
    state.semaphore_busy=0;state.semaphore_releases++;
    return pthread_mutex_unlock(&sem5)?-1021:0;
}
static const struct full_bb_mode_config_sem5 sem5_ops={&config_owner,sem5_lock,sem5_unlock};
static int latch(const char *why,int rc) {
    state.faults=1;state.pending=1;state.clean_completion=0;
    char text[340];snprintf(text,sizeof text,
        "generation=1 reason=%s rc=%d retained_request=%u retained_reply=%u retained_cleanup=%u busy=%u ap_consumed=0",
        why,rc,(unsigned int)(retained_request!=NULL),(unsigned int)(retained_reply!=NULL),
        (unsigned int)(retained_cleanup!=NULL),state.busy);
    log_line("FULL_BB_SET_MODE_PENDING ",text);return rc?rc:-1021;
}
static void refresh_snapshots(void) {
    state.config_initialized=config_owner.initialized;
    state.config_invalidated=(unsigned int)(config_owner.invalidated_epoch!=0);
    state.config_mode_updates=(unsigned int)config_owner.mode_updates;
    state.config_saves=(unsigned int)config_owner.saves;
    state.config_snapshot_copies=(unsigned int)config_owner.copies;
    state.config_live_fnv=config_owner.live.data_fnv;
    state.config_known_fnv=config_owner.live.known_fnv;
    state.config_snapshot_fnv=config_owner.snapshot.data_fnv;
    state.config_snapshot_known_fnv=config_owner.snapshot.known_fnv;
    state.config_snapshot_known_bytes=known_count(config_owner.snapshot.known,FULL_BB_MODE_CONFIG_BYTES);
    state.config_snapshot_unknown_bytes=FULL_BB_MODE_CONFIG_BYTES-state.config_snapshot_known_bytes;
    state.queue_generation=(unsigned int)queue_owner.generation;
    state.outer_owner=queue_owner.outer.source_owner;state.outer_queue=queue_owner.outer.source_queue;
    state.outer_task=queue_owner.outer.consumer_task;state.outer_accepted=queue_owner.outer.accepted;
    state.outer_popped=queue_owner.outer.popped;state.outer_inflight=queue_owner.outer.inflight;
    state.outer_returned=queue_owner.outer.returned;
    state.inner_owner=queue_owner.inner.source_owner;state.inner_queue=queue_owner.inner.source_queue;
    state.inner_task=queue_owner.inner.consumer_task;state.inner_accepted=queue_owner.inner.accepted;
    state.inner_popped=queue_owner.inner.popped;state.inner_inflight=queue_owner.inner.inflight;
    state.inner_returned=queue_owner.inner.returned;
    state.queue4_virtual_consumer=queue_owner.inner.consumer_task;
    state.queue_finished=(unsigned int)full_bb_mode_work_queue_finished(&queue_owner,1);
}
int full_bb_set_mode_owner_init(void) {
    if(!current_process())return -1021;
    pthread_mutex_lock(&mutex);
    if(state.initialized || !plane_no_mode_alias() || u32(state_initializer)!=1 || u32(state_initializer+24)!=1 ||
       full_bb_mode_config_init(&config_owner) || full_bb_mode_work_queue_init(&queue_owner)) {
        state.faults=state.pending=1;pthread_mutex_unlock(&mutex);return -1021;
    }
    state.initialized=state.enabled=state.state_known=state.initial_state_bytes_verified=1;
    state.generation=1;state.state_epoch=1;state.state_word=u32(state_initializer);state.original_cp_executed=0;
    state.handler_linked_byte5=state.handler_linked_byte7=0;state.execution_gate_byte4=1;
    refresh_snapshots();
    char text[420];snprintf(text,sizeof text,
        "generation=1 virtual_source_image_initializer=1 state_word=%u state_word_source_byte_offset=0 additional_source_word6=%u setter_calls=0 handler_linked5=0 handler_linked7=0 execution_gate4=1 original_cp_executed=0 live_CP_RAM_read=0 virtual_policy_only=1",
        state.state_word,u32(state_initializer+24));
    log_line("FULL_BB_SET_MODE_OWNER_INIT ",text);
    pthread_mutex_unlock(&mutex);return 0;
}
int full_bb_set_mode_observe_input(unsigned int destination,void *request,const struct full_imaging_io *io) {
    if(destination!=FULL_BB_SET_MODE_INPUT || !request || !io || !io->size || !current_process())return 0;
    unsigned int bytes=io->size(request);if(bytes<4)return 0;
    const unsigned char *p=request;unsigned int command=u16(p+2);
    if(command==0x0110)return 0;
    static const struct {unsigned int command,bytes;} prior[]={
        {0x0323,12},{0x0336,14},{0x032d,26},{0x032f,10},{0x016a,8},
        {0x0118,22},{0x013d,10},{0x011a,14},{0x042b,10},{0x0500,10},
        {0x0159,10},{0x014c,40},{0x0161,10},{0x0330,10},{0x033f,8},
        {0x0329,40},{0x0142,10},{0x015a,10},{0x0145,24},{0x011b,10},
        {0x032c,10},{0x0160,10},{0x0150,20},{0x0327,8},{0x032a,10},{0x0119,28},
        {0x0165,10},{0x0146,10},{0x0429,10},{0x0149,10},{0x0147,680}
    };
    unsigned int reviewed=0;
    for(unsigned int i=0;i<sizeof prior/sizeof *prior;i++)
        if(prior[i].command==command && prior[i].bytes==bytes)reviewed=1;
    reviewed=reviewed && bytes>=8 && u16(p)==0x200d && u16(p+4)==bytes && u16(p+6)==0x8001;
    pthread_mutex_lock(&mutex);
    if(state.busy) {
        latch("concurrent-prefix-during-mode-transaction",-1021);
        pthread_mutex_unlock(&mutex);return -1021;
    }
    if(state.initialized && !state.applications) {
        transport.record=io->record;
        if(state.prefix_messages==UINT32_MAX)latch("prefix-counter-overflow",-1021);
        else state.prefix_messages++;
        if(command==0x0147 && (!plane_no_mode_alias() || state.requests || queue_owner.generation ||
            queue_owner.outer.accepted || queue_owner.inner.accepted || queue_owner.outer.inflight ||
            queue_owner.inner.inflight || queue_owner.pending || queue_owner.fault))reviewed=0;
        if(!reviewed) {state.unknown_prefix_messages++;state.state_known=0;}
        if(full_bb_mode_config_invalidate(&config_owner)) {
            latch("prefix-config-invalidation",-1021);
            state.state_known=0;
        } else state.prefix_config_invalidations++;
        if(command==0x0118 && reviewed && full_bb_mode_config_apply0118(&config_owner,request,bytes)) {
            state.unknown_prefix_messages++;state.state_known=0;
            latch("0118-exact-config-update-refused",-1021);
        }
        refresh_snapshots();
        char raw[129],text[500];unsigned int shown=bytes<64?bytes:64;
        for(unsigned int i=0;i<shown;i++)snprintf(raw+2*i,3,"%02x",p[i]);
        raw[shown*2]=0;
        snprintf(text,sizeof text,
            "generation=1 command=%#x bytes=%u raw=%s source_reviewed_no_word0_setter=%u state_word_known=%u state_word=%u state_setter_calls=%u opaque_config_validated=0 plane_alias_contract=%u local_deferred_mode_jobs=%u original_vdf_execution_verified=0",
            command,bytes,raw,reviewed,state.state_known,state.state_word,state.state_setter_calls,
            command==0x0147?(unsigned int)plane_no_mode_alias():0u,
            queue_owner.outer.count+queue_owner.inner.count+queue_owner.outer.inflight+queue_owner.inner.inflight);
        log_line(reviewed?"FULL_BB_SET_MODE_PREFIX_OBSERVED ":"FULL_BB_SET_MODE_PREFIX_UNKNOWN ",text);
    }
    pthread_mutex_unlock(&mutex);return 0;
}
struct provider_context {uint32_t target;unsigned int snapshot_verified;};
static struct provider_context current_provider;
static int outer_work(void *opaque,uint32_t target) {
    if(opaque!=&current_provider || target!=3 || state.state_known!=1 || state.state_word!=1 ||
       state.state_setter_calls || !state.operation_mode_valid || state.operation_mode!=0 ||
       !state.first_internal_completion || state.second_internal_completion)return -1021;
    if(full_bb_mode_config_snapshot(&config_owner,&sem5_ops))return -1021;
    const struct full_bb_mode_config_view *view=full_bb_mode_config_view(&config_owner,FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN);
    if(!view || view->token!=FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN || view->serial!=1 ||
       view->source_epoch!=config_owner.live.source_epoch || view->data_fnv!=config_owner.live.data_fnv ||
       view->known_fnv!=config_owner.live.known_fnv || !config_owner.saved_valid ||
       config_owner.saved_operation_mode!=0 || config_owner.snapshot.bytes[0x68]!=0 ||
       !view->known[0x68] || !view->known[0x69] || !view->known[0x6a] || !view->known[0x6b] ||
       state.config_snapshot_unknown_bytes==0)return -1021;
    current_provider.target=target;current_provider.snapshot_verified=1;
    if(full_bb_mode_work_queue_enqueue_inner(&queue_owner,1,FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN,
                                             FULL_BB_MODE_INNER_WORK,opaque))return -1021;
    refresh_snapshots();
    char text[850];snprintf(text,sizeof text,
        "generation=1 task=30 target=%u work=0x001aaddd live=0x01ff34c8 snapshot=0x01ff2cc8 bytes=1760 sem5_acquired=1 sem5_released=1 snapshot_copy_readback=1 known_bytes=%u unknown_bytes=%u live_fnv=%016llx snapshot_fnv=%016llx live_known_fnv=%016llx snapshot_known_fnv=%016llx queue3_read=%u queue3_write=%u queue3_queued=%u queue3_inflight=%u queue3_free=%u opmode_token=0x017890fc operation_mode=0 inner_job_enqueued=1 original_CP_task_executed=0 snapshot_payload_is_original_CP_memory=0",
        target,state.config_snapshot_known_bytes,state.config_snapshot_unknown_bytes,
        state.config_live_fnv,state.config_snapshot_fnv,state.config_known_fnv,state.config_snapshot_known_fnv,
        queue_owner.outer.ring_read,queue_owner.outer.ring_write,queue_owner.outer.count,
        queue_owner.outer.inflight,queue_owner.outer.free_bytes);
    log_line("FULL_BB_MODE_OUTER_WORK ",text);return 0;
}
static int inner_work(void *opaque,uint32_t snapshot_token) {
    struct provider_context *context=opaque;uint32_t pmf,adjust,work,arg0,arg1,opmode;
    if(opaque!=&current_provider || !context || context->target!=3 || !context->snapshot_verified ||
       snapshot_token!=FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN || state.state_known!=1 ||
       state.state_word!=1 || state.state_setter_calls || !state.operation_mode_valid || state.operation_mode!=0 ||
       config_owner.saved_operation_mode!=0 || config_owner.snapshot.bytes[0x68]!=0 ||
       full_bb_mode_record_read32(&queue_owner.inner.executing,0,&pmf) || pmf!=FULL_BB_MODE_INNER_PMF ||
       full_bb_mode_record_read32(&queue_owner.inner.executing,4,&adjust) || adjust ||
       full_bb_mode_record_read32(&queue_owner.inner.executing,8,&work) || work!=FULL_BB_MODE_INNER_WORK ||
       full_bb_mode_record_read32(&queue_owner.inner.executing,24,&arg0) || arg0!=snapshot_token ||
       full_bb_mode_record_read32(&queue_owner.inner.executing,28,&arg1) || arg1)return -1021;
    /* Only the target3/opmode0 child is modeled; it reads the saved mode, not cfg+0x68. */
    if(full_bb_mode_config_saved_operation_mode(&config_owner,&opmode) || opmode!=0)return -1021;
    if(state.first_internal_completion!=1 || state.second_internal_completion || !state.handler_linked_byte7 ||
       state.handler_linked_byte5!=1 || state.execution_gate_byte4!=1)return -1021;
    state.applications=1;
    state.second_internal_completion=1;state.handler_linked_byte7=0;state.execution_gate_byte4=1;
    state.unique_ap_reply=1;
    refresh_snapshots();
    log_line("FULL_BB_MODE_SECOND_COMPLETION ","generation=1 event=0x21a result=0 linked_byte5=1 linked_byte7=0 execution_gate_byte4=1 unique_1110_pending=1 duplicate_reply_suppressed=1 mode_task_scope=target3-opmode0-no-frame-no-MMIO");
    return 0;
}
static void release_guard(void) {
    if(state.guard_held){
        pthread_mutex_unlock(&mutex);reservation.release();pthread_mutex_lock(&mutex);
        state.guard_held=0;
    }
}
static void retain_failure(int rc,const char *reason,void *temporary) {
    latch(reason,rc);
    if(temporary && temporary!=request_pointer){
        retained_cleanup=temporary;cleanup_owner=reply_owner;
        pthread_mutex_unlock(&mutex);int freed=transport.release(reply_owner,temporary);pthread_mutex_lock(&mutex);
        if(!freed){retained_cleanup=NULL;cleanup_owner=0;}
    }
    release_guard();state.busy=0;
}
int full_bb_set_mode_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                              const struct full_adf_proc_guard *guard,int enabled,int *result) {
    if(enabled!=1 || destination!=FULL_BB_SET_MODE_INPUT || !request || !io || !result)return 0;
    if(!current_process()){*result=-1021;return 1;}
    if(!io->size)return 0;
    unsigned int bytes=io->size(request);
    if(bytes<4 || u16(request)!=0x200d || u16((unsigned char *)request+2)!=0x0110)return 0;
    if(bytes!=10 || !io->source || !io->allocate || !io->release || !io->set_source || !io->send ||
       !guard || !guard->reserve || !guard->release){*result=-1021;return 1;}
    static const unsigned char expected[10]={0x0d,0x20,0x10,1,10,0,1,0x80,0,0};
    unsigned int caller=io->source(request);
    if(memcmp(request,expected,sizeof expected) || (caller>>28)!=8 || !(caller&0x0fffffff)){
        *result=-1021;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(!state.initialized || !state.enabled || state.faults || state.requests || state.busy ||
       !state.state_known || state.unknown_prefix_messages || state.state_word!=1 || state.state_setter_calls || state.original_cp_executed ||
       state.execution_gate_byte4!=1 || state.handler_linked_byte5 || state.handler_linked_byte7 ||
       state.first_internal_completion || state.second_internal_completion ||
       config_owner.fault || queue_owner.fault || queue_owner.generation || queue_owner.busy || queue_owner.pending ||
       queue_owner.outer.accepted || queue_owner.outer.count || queue_owner.outer.inflight ||
       queue_owner.inner.accepted || queue_owner.inner.count || queue_owner.inner.inflight ||
       request_pointer || live_reply || retained_request || retained_reply || retained_cleanup){
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    state.requests=1;state.busy=1;state.pending=1;state.generation=1;
    request_pointer=retained_request=request;request_owner=destination;reply_owner=caller;state.reply_owner=caller;
    transport=*io;reservation=*guard;
    pthread_mutex_unlock(&mutex);
    char raw[21],line[500];const unsigned char *p=request;
    for(unsigned int i=0;i<10;i++)snprintf(raw+2*i,3,"%02x",p[i]);
    snprintf(line,sizeof line,"generation=1 caller=%#x request=%p bytes=10 raw=%s ap_input_u32_0=2 ap_input_u32_1=0 encoded_operation_mode=0 state_word=1 state_source=virtual_CP_image_initializer response_bytes=12 normal_completion=0",
        caller,request,raw);
    log_unlocked("FULL_BB_SET_MODE_REQUEST ",line);
    int rc=reservation.reserve();
    if(rc){pthread_mutex_lock(&mutex);retain_failure(rc,"resource-reservation",NULL);pthread_mutex_unlock(&mutex);*result=0;return 1;}
    pthread_mutex_lock(&mutex);state.guard_held=1;pthread_mutex_unlock(&mutex);
    struct full_adf_set_output_snapshot output={0};
    full_adf_set_output_snapshot(&output);
    if(output.owner_pid!=getpid() || !output.configured || !output.clean_completion || !output.ap_consumed ||
       !output.request_freed || !output.reply_freed || output.busy || output.worker_active || output.guard_held ||
       output.faults || output.retained_request || output.retained_reply || output.retained_cleanup ||
       !state.state_known || state.unknown_prefix_messages || state.state_word!=1 || state.state_setter_calls || state.original_cp_executed) {
        pthread_mutex_lock(&mutex);latch("prior-source-owner-or-BB-state-not-admissible",-1021);
        release_guard();state.busy=0;pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(full_bb_mode_config_apply0110(&config_owner,request,bytes) ||
       full_bb_mode_config_save_operation_mode(&config_owner) ||
       full_bb_mode_config_saved_operation_mode(&config_owner,&state.operation_mode) || state.operation_mode!=0){
        retain_failure(-1021,"0110-operation-mode-not-proven",NULL);pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    state.operation_mode_valid=1;state.target=3;
    /* Original first event21a precedes both jobs; its unique AP reply is
     * conservatively held until this bounded virtual work has returned. */
    state.first_internal_completion=1;state.handler_linked_byte5=1;state.handler_linked_byte7=1;
    state.unique_ap_reply=1;
    log_line("FULL_BB_MODE_FIRST_COMPLETION ","generation=1 event=0x21a result=0 unique_1110_pending=1 mode_work_pending=1 reply_publication_deferred_until_virtual_work=1");
    if(full_bb_mode_work_queue_enqueue_outer(&queue_owner,1,state.target)){
        retain_failure(-1021,"outer-work-admission",NULL);pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    current_provider=(struct provider_context){0,0};
    rc=full_bb_mode_work_queue_dispatch_outer(&queue_owner,1,30,outer_work,&current_provider);
    if(!rc)rc=full_bb_mode_work_queue_dispatch_inner(&queue_owner,1,31,inner_work,&current_provider);
    if(rc || !full_bb_mode_work_queue_finished(&queue_owner,1) || !state.first_internal_completion ||
       !state.second_internal_completion || !state.unique_ap_reply || !state.applications){
        retain_failure(rc?rc:-1021,"target3-mode-work-not-complete",NULL);
        pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    refresh_snapshots();
    state.pending=0;
    log_line("FULL_BB_SET_MODE_APPLIED ","generation=1 state_word=1 target=3 operation_mode=0 work1aaddd_returned=1 work1b37ed_returned=1 snapshot_bytes=1760 internal_completions=2 unique_reply=1 original_cp_executed=0 hardware_mode_change_verified=0");
    pthread_mutex_unlock(&mutex);
    void *reply=NULL;rc=transport.allocate(caller,&reply,12,1);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;pthread_mutex_unlock(&mutex);
    if(reply==request){pthread_mutex_lock(&mutex);retain_failure(-1021,"allocator-returned-original-request",NULL);pthread_mutex_unlock(&mutex);*result=0;return 1;}
    if(rc || !reply || transport.size(reply)!=12){pthread_mutex_lock(&mutex);retain_failure(rc?rc:-1021,"reply-allocation-or-size",reply);pthread_mutex_unlock(&mutex);*result=0;return 1;}
    static const unsigned char response[12]={0x0d,0x20,0x10,0x11,12,0,1,0x80,0,0,0,0};
    memcpy(reply,response,sizeof response);transport.set_source(reply,FULL_BB_SET_MODE_INPUT);
    if(transport.source(reply)!=FULL_BB_SET_MODE_INPUT || transport.size(reply)!=12 || memcmp(reply,response,12)){
        pthread_mutex_lock(&mutex);retain_failure(-1021,"reply-readback",reply);pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    pthread_mutex_lock(&mutex);
    if(state.faults){retain_failure(-1021,"fault-before-reply-publication",reply);pthread_mutex_unlock(&mutex);*result=0;return 1;}
    live_reply=reply;reply_sending=1;pthread_mutex_unlock(&mutex);
    rc=transport.send(caller,reply);
    pthread_mutex_lock(&mutex);state.send_rc=rc;reply_sending=0;
    if(rc){
        if(!releasing_reply)live_reply=NULL;
        retain_failure(rc,"reply-send",reply_freed || releasing_reply?NULL:reply);
        pthread_mutex_unlock(&mutex);*result=0;return 1;
    }
    state.queued=1;
    snprintf(line,sizeof line,"generation=1 destination=%#x source=%#x reply=%p bytes=12 raw=0d2010110c00018000000000 target=3 operation_mode=0 two_internal_completions=1 unique_reply=1",
        caller,FULL_BB_SET_MODE_INPUT,reply);log_line("FULL_BB_SET_MODE_REPLY_QUEUED ",line);
    void *original=request_pointer;
    pthread_mutex_unlock(&mutex);
    int freed=transport.release(request_owner,original);
    pthread_mutex_lock(&mutex);state.request_free_rc=freed;
    if(state.request_free_rc){state.faults=1;state.clean_completion=0;retained_request=original;}
    else {request_pointer=NULL;retained_request=NULL;request_owner=0;state.request_freed=1;}
    if(reply_freed){live_reply=NULL;reply_freed=0;}
    state.pending=0;state.busy=0;release_guard();
    state.clean_completion=!state.faults && !retained_request && !retained_reply && !retained_cleanup;
    snprintf(line,sizeof line,"generation=1 request=%p request_free_rc=%d retained_request=%u clean_completion=%u queued=1 ap_consumed=0",
        original,state.request_free_rc,(unsigned int)(retained_request!=NULL),state.clean_completion);
    log_line(state.faults?"FULL_BB_SET_MODE_FAULT ":"FULL_BB_SET_MODE_COMMIT ",line);
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}
int full_bb_set_mode_release_reply(unsigned int destination,void *pointer,
                                   int (*release)(unsigned int,void *),
                                   void (*logger)(const char *,const char *),int *result){
    if(!pointer || !release || !result)return 0;
    if(!current_process()){*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);const char *kind=NULL;unsigned int expected=0;int rc=0;
    if(pointer==live_reply && !reply_freed){kind="queued-reply";expected=reply_owner;}
    else if(pointer==retained_request){kind="original-request";expected=request_owner;}
    else if(pointer==retained_cleanup){kind="local-cleanup";expected=cleanup_owner;}
    else {pthread_mutex_unlock(&mutex);return 0;}
    if(destination!=expected || releasing_reply || (pointer==retained_request && state.busy))rc=-1021;
    else {
        releasing_reply=1;pthread_mutex_unlock(&mutex);
        rc=release(destination,pointer);
        pthread_mutex_lock(&mutex);releasing_reply=0;
    }
    if(rc){state.faults=1;state.clean_completion=0;if(!strcmp(kind,"queued-reply"))retained_reply=pointer;}
    else if(!strcmp(kind,"queued-reply")){reply_freed=1;state.reply_freed++;state.ap_consumed=1;retained_reply=NULL;if(!reply_sending)live_reply=NULL;}
    else if(!strcmp(kind,"original-request")){retained_request=NULL;request_pointer=NULL;request_owner=0;state.request_freed++;}
    else {retained_cleanup=NULL;cleanup_owner=0;}
    if(!strcmp(kind,"queued-reply"))state.reply_free_rc=rc;
    char text[300];snprintf(text,sizeof text,"generation=1 destination=%#x expected=%#x pointer=%p kind=%s rc=%d faults=%u retained=%u ap_consumed=%u metadata_completion_only=1",
        destination,expected,pointer,kind,rc,state.faults,(unsigned int)(rc!=0),!rc && !strcmp(kind,"queued-reply"));
    const char *tag=rc?"FULL_BB_SET_MODE_FAULT ":!strcmp(kind,"queued-reply")?"FULL_BB_SET_MODE_REPLY_FREE ":"FULL_BB_SET_MODE_RECOVERY_FREE ";
    pthread_mutex_unlock(&mutex);
    if(logger)logger(tag,text);
    *result=rc;return 1;
}
void full_bb_set_mode_snapshot(struct full_bb_set_mode_snapshot *out){
    if(!out)return;
    if(!current_process()){*out=(struct full_bb_set_mode_snapshot){.faults=1,.owner_pid=atomic_load(&owner_pid)};return;}
    pthread_mutex_lock(&mutex);refresh_snapshots();*out=state;out->owner_pid=atomic_load(&owner_pid);
    out->retained_request=retained_request;out->live_reply=live_reply;
    out->retained_reply=retained_reply;out->retained_cleanup=retained_cleanup;
    pthread_mutex_unlock(&mutex);
}
