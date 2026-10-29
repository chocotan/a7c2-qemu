/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "adf-set-output-device.h"
#include "adf-set-input-device.h"
#include "adf-set-input-cold-owners.h"
#include "adf-avio-output.h"
#include "adf-hdmi-monitor.h"
#include "adf-aip-commands.h"
#include "adf-aip-disable.h"
#include "adf-source7-clock.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/timerfd.h>
#include <time.h>
#include <unistd.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_adf_set_output_snapshot state;
static struct full_imaging_io transport;
static struct full_adf_proc_guard reservation;
static struct full_adf_proc_input_owners owners;
static struct full_adf_avio_snapshot prior_shadow;
static unsigned char inner[12],failure_history[FULL_ADF_AIP_SNAPSHOT_BYTES];
static struct {unsigned int live;struct full_adf_source7_event value;} source5_event;
#ifdef FULL_ADF_SET_OUTPUT_TEST
static unsigned int event_limit=1;
#endif
static int current_process(void)
{
    int pid=(int)getpid(),unbound=0;
    atomic_compare_exchange_strong(&owner_pid,&unbound,pid);
    return atomic_load(&owner_pid)==pid;
}
int full_adf_set_output_owner_init(void)
{
    if(!current_process())return -1021;
    pthread_mutex_lock(&mutex);
    if(!state.initialized) {state.known=1;state.initialized=1;}
    int rc=state.known==1 && state.initialized==1?0:-1021;
    pthread_mutex_unlock(&mutex);return rc;
}
static unsigned int u16(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p) {return u16(p)|u16(p+2)<<16;}
static void event(void (*record)(const char *,const char *),const char *tag,const char *text)
{
    char line[1380];snprintf(line,sizeof line,"%s pid=%d tid=%ld scope=virtualOutputConfigurationNoChange original_cp_executed=0 hardware_verified=0 native_frequency_verified=0 original_event_identity_verified=0 pcm_verified=0 frames_verified=0 capture_verified=0",text,getpid(),syscall(SYS_gettid));
    if(record)record(tag,line);
}
static void log_event(const char *tag,const char *text) {event(transport.record,tag,text);}
static int now_ns(uint64_t *out)
{
    struct timespec t;
    if(clock_gettime(CLOCK_MONOTONIC,&t) || t.tv_sec<0 || t.tv_nsec<0 || t.tv_nsec>=1000000000L ||
       (uint64_t)t.tv_sec>UINT64_MAX/UINT64_C(1000000000))return -1021;
    uint64_t seconds=(uint64_t)t.tv_sec*UINT64_C(1000000000);
    if(seconds>UINT64_MAX-(uint64_t)t.tv_nsec)return -1021;
    *out=seconds+(uint64_t)t.tv_nsec;return 0;
}
static int monitor_enqueue(void *context,unsigned int mode,unsigned int enable,unsigned int channel)
{
    static const unsigned char b0[16]={0xb0,0,0,0,16,0,0,0,0,0,0,0,0,0,0,0};
    if(context!=&state || mode!=1 || enable || channel || !state.busy || !state.guard_held ||
       state.monitor_b0_queued || full_adf_aip_commands_output_enqueue(owners.commands,b0,16,3))return -1021;
    state.monitor_b0_queued=1;
    log_event("FULL_ADF_SET_OUTPUT_MONITOR_COMMAND ","generation=3 monitor_generation=2 control13d=1 mode=1 enable=0 channel=0 opcode=0xb0 bytes=16 raw=b0000000100000000000000000000000 newly_queued=1 old_history_replayed=0");
    return 0;
}
static int disable_command(void *context)
{
    if(context!=&state || owners.software_s || !state.guard_held || state.aip_b0_consumed ||
       owners.disable->calls!=2 || owners.disable->writes!=14 || owners.disable->readbacks!=14 ||
       full_adf_aip_disable_apply(owners.disable,owners.software_s))return -1021;
    state.disable_calls=owners.disable->calls;state.disable_writes=owners.disable->writes;
    state.disable_readbacks=owners.disable->readbacks;
    if(state.disable_calls!=3 || state.disable_writes!=21 || state.disable_readbacks!=21)return -1021;
    char text[620];snprintf(text,sizeof text,"generation=3 global_event=9 same_disable_bank=1 calls=%u writes=%u readbacks=%u active0400=%#x route8828=%#x route882c=%#x route8830=%#x route8928=%#x route892c=%#x route8930=%#x controla000=%#x",
        state.disable_calls,state.disable_writes,state.disable_readbacks,owners.disable->registers.active0400,
        owners.disable->registers.route8828,owners.disable->registers.route882c,owners.disable->registers.route8830,
        owners.disable->registers.route8928,owners.disable->registers.route892c,owners.disable->registers.route8930,
        owners.disable->registers.controla000);
    log_event("FULL_ADF_SET_OUTPUT_DISABLE_READBACK ",text);return 0;
}
static void output_complete(void *context,unsigned int status)
{
    if(context!=&state || status || state.callbacks || state.callback_slot!=1 || state.aip_b0_consumed!=1 ||
       owners.output->read_index!=4 || owners.output->write_index!=4 || owners.output->count ||
       owners.output->output_finished || owners.output->callback_running!=1 ||
       state.monitor_configures!=1 || state.inner_queued) {state.faults=1;return;}
    state.callbacks=1;state.callback_slot=0;state.completion_status=status;
    state.callback_read_index=owners.output->read_index;state.callback_write_index=owners.output->write_index;
    state.callback_count=owners.output->count;
    static const unsigned char completed[12]={4,0x20,1,0x83,12,0,1,0,0,0,0,0};
    memcpy(inner,completed,12);state.inner_queued=1;
    log_event("FULL_ADF_SET_OUTPUT_CALLBACK ","generation=3 output_generation=2 global_event=9 status=0 pop_before_callback=1 read=4 write=4 count=0 output_finished=0 controller_callback_slot=0 format_cache_kept=1 inner_queued=1 raw=042001830c00010000000000 outer_published=0");
}
static int source5_take(const struct full_adf_source7_event *tick,struct full_adf_source7_event *taken)
{
    struct full_adf_source7_snapshot cache;
    if(!tick || !taken || source5_event.live || state.source5_queued || state.source5_consumed ||
       tick->generation!=3 || tick->sequence!=9 || owners.source5_target!=0x9058003f || owners.source5_flags!=1 ||
       owners.source5_software!=5 || owners.source5_sender!=0x928c0786 ||
       full_adf_source7_clock_get(owners.clock,3,5,&cache) || cache.counter!=tick->cache.counter ||
       cache.epoch!=tick->cache.epoch || cache.phase!=tick->cache.phase)return -1021;
    source5_event.value=*tick;source5_event.live=1;state.source5_queued=1;
    if(source5_event.value.generation!=3 || source5_event.value.sequence!=9 ||
       source5_event.value.cache.counter!=cache.counter || source5_event.value.cache.epoch!=cache.epoch)return -1021;
    *taken=source5_event.value;source5_event.live=0;state.source5_consumed=1;return 0;
}
static int backend(void)
{
    if(full_adf_set_input_claim_output(&owners))return -1021;
    state.dependency_claimed=1;
    if(!owners.output || !owners.monitor || !owners.disable || !owners.clock || owners.software_s || owners.software_k)return -1021;
    full_adf_avio_listener cache_callback=0;
    if(full_adf_avio_output_control3(owners.output,&state.old_mask,&cache_callback) || state.old_mask!=8 || cache_callback)return -1021;
    state.control3_reads=1;
    /* W0/O8 makes every unknown SYSTEMSOUND branch yield8; none is fabricated. */
    state.target_mask=state.old_mask&8u;state.power20=owners.glee->power.flag_20;state.power22=owners.glee->power.flag_22;
    if(state.target_mask!=8 || state.power20 || state.power22 || owners.glee->power.field_14!=2 ||
       !owners.output->output_finished || owners.output->consumed!=3 || owners.output->shadow_writes!=7)return -1021;
    prior_shadow=owners.output->snapshot;state.shadow_writes_before=owners.output->shadow_writes;
    memcpy(failure_history,owners.commands->input.failure_snapshot,sizeof failure_history);
    log_event("FULL_ADF_SET_OUTPUT_DEPENDENCIES ","generation=3 original_AP1336_reply_freed=1 same_Output60_owner=1 same_monitor=1 same_command_buffer=1 same_disable_bank=1 same_source7_clock=1 control3_mask=8 control3_callback=0 wire_bitmap=0 computed_mask=8 system_sound_activity_snapshot_known=0 mask_invariant_W0_O8=1 power20=0 power22=0 counter_before=8 epoch_before=8");
    if(full_adf_aip_commands_output_begin(owners.commands,3) ||
       full_adf_hdmi_monitor_configure(owners.monitor,2,state.format,sizeof state.format,monitor_enqueue,&state) ||
       owners.monitor->configure_count!=1 || owners.monitor->fault || state.monitor_b0_queued!=1)return -1021;
    state.monitor_configures=owners.monitor->configure_count;
    if(memcmp(owners.monitor->config,state.format,20) || owners.monitor->flag_240 || owners.monitor->flag_242 ||
       owners.monitor->prepare_count!=1 || owners.monitor->commit_count!=1 || owners.monitor->emitted_af!=1 ||
       owners.monitor->emitted_b0!=2)return -1021;
    log_event("FULL_ADF_SET_OUTPUT_MONITOR ","generation=3 same_initialized_monitor=1 prepare_notify1=1 commit_notify4=1 configure_notify2=1 format_bytes=20 format_copied=1 cache_first8_equal=1 flag240=0 flag242=0 control13d_still_submitted=1 emitted_AF_total=1 emitted_B0_total=2 unknown243_known=0");
    state.callback_slot=1;
    if(full_adf_avio_output_enqueue_same(owners.output,2,state.target_mask,state.power20,state.power22,output_complete,&state) ||
       owners.output->read_index!=3 || owners.output->write_index!=4 || owners.output->count!=1 ||
       memcmp(&prior_shadow,&owners.output->snapshot,sizeof prior_shadow))return -1021;
    state.avio_enqueued=1;
    if(full_adf_avio_output_control3(owners.output,&state.target_mask,&cache_callback) || state.target_mask!=8 || cache_callback)return -1021;
    state.control3_reads++;
    log_event("FULL_ADF_SET_OUTPUT_AVIO_QUEUED ","generation=3 output_generation=2 read=3 write=4 count=1 target=8 change=0 job_contract=0000080000000000616f6600 control3_mask=8 control3_callback=0 callback_in_job=1 required_free_slots_gt5=1 shadow_writes_added=0 completed=0");
    uint64_t now;
    if(now_ns(&now) || full_adf_source7_clock_continue_output(owners.clock,now))return -1021;
    int fd=timerfd_create(CLOCK_MONOTONIC,TFD_CLOEXEC);
    if(fd<0)return -1021;
    int rc=-1021;
#ifdef FULL_ADF_SET_OUTPUT_TEST
    if(!event_limit)goto timer_done;
#endif
    uint64_t deadline=owners.clock->deadline_ns;
    struct itimerspec timer={.it_value={.tv_sec=(time_t)(deadline/UINT64_C(1000000000)),
        .tv_nsec=(long)(deadline%UINT64_C(1000000000))}};
    if(timerfd_settime(fd,TFD_TIMER_ABSTIME,&timer,0))goto timer_done;
    uint64_t expirations=0;ssize_t got;
    do {got=read(fd,&expirations,sizeof expirations);} while(got<0 && errno==EINTR);
    if(got!=(ssize_t)sizeof expirations || expirations!=1 || now_ns(&now))goto timer_done;
    struct full_adf_source7_event tick,delivered;
    if(full_adf_source7_clock_expire(owners.clock,3,now,&tick) || tick.generation!=3 || tick.sequence!=9 ||
       tick.deadline_ns!=deadline || tick.observed_ns<deadline || tick.hardware_source!=7 || tick.software_source!=5 ||
       tick.hardware.counter!=9 || tick.hardware.epoch!=9 || tick.fb.counter!=9 || tick.fb.epoch!=9 ||
       tick.cache.counter!=9 || tick.cache.epoch!=9 || tick.hardware.phase!=tick.fb.phase || tick.hardware.phase!=tick.cache.phase ||
       source5_take(&tick,&delivered))goto timer_done;
    tick=delivered;state.events=1;state.hardware_counter=tick.hardware.counter;state.hardware_epoch=(unsigned int)tick.hardware.epoch;
    char text[700];snprintf(text,sizeof text,"generation=3 event=9 guest_timerfd_expirations=%llu deadline_ns=%llu observed_ns=%llu hardware_counter=9 epoch=9 queued=%u consumed=%u hardware_source=7 software_source=5 policy_period_ns=1000000 getter_advances=0",
        (unsigned long long)expirations,(unsigned long long)deadline,(unsigned long long)tick.observed_ns,state.source5_queued,state.source5_consumed);
    log_event("FULL_ADF_SET_OUTPUT_EVENT ",text);
    if(full_adf_aip_commands_output_flush(owners.commands,3,tick.sequence,disable_command,&state) || owners.commands->fault ||
       owners.commands->output.dispatches!=1 || owners.commands->output.snapshot_count!=1 ||
       owners.commands->output.checked!=1 || owners.commands->output.local_cursor!=3 || owners.commands->output.task_status ||
       owners.commands->input.ring_read!=10 || owners.commands->input.ring_write!=10 ||
       owners.commands->command_count || owners.commands->cursor ||
       memcmp(failure_history,owners.commands->input.failure_snapshot,sizeof failure_history))goto timer_done;
    state.aip_b0_consumed=1;state.aip_checked=owners.commands->output.checked;
    state.aip_cursor=owners.commands->output.local_cursor;state.aip_task_status=owners.commands->output.task_status;
    log_event("FULL_ADF_SET_OUTPUT_AIP_CONSUMED ","generation=3 global_event=9 priority=4 B0_newly_consumed=1 snapshot_count=1 checked=1 cursor_words=3 task_rc=0 ring_read=10 ring_write=10 disable_calls=3 writes=21 readbacks=21 previous_AB_status1_history_preserved=1 previous_uninspected7_rechecked=0");
    if(full_adf_avio_output_consume_vsync(owners.output,2,tick.sequence) || owners.output->fault || state.faults ||
       state.callbacks!=1 || state.callback_slot || state.inner_queued!=1 || state.completion_status ||
       owners.output->read_index!=4 || owners.output->write_index!=4 || owners.output->count ||
       !owners.output->output_finished || owners.output->callback_calls!=2 || owners.output->pending_events ||
       owners.output->shadow_writes!=state.shadow_writes_before || memcmp(&prior_shadow,&owners.output->snapshot,sizeof prior_shadow))goto timer_done;
    state.avio_consumed=1;state.shadow_writes_after=owners.output->shadow_writes;
    if(full_adf_avio_output_control3(owners.output,&state.target_mask,&cache_callback) || state.target_mask!=8 || cache_callback)goto timer_done;
    state.control3_reads++;
    if(owners.clock->armed || owners.clock->events_delivered!=9)goto timer_done;
    rc=0;
timer_done:
    if(close(fd))rc=-1021;
    if(rc && owners.clock->armed)full_adf_source7_clock_cancel(owners.clock,3);
    if(rc)return rc;
    if(memcmp(inner,"\x04\x20\x01\x83\x0c\x00\x01\x00",8) || u32(inner+8))return -1021;
    state.outer_status=u32(inner+8)|0x580000u;state.inner_consumed=1;
    log_event("FULL_ADF_SET_OUTPUT_INNER_RELAY ","generation=3 source=0x9058003f target=0x928407b9 raw=042001830c00010000000000 callback_status=0 outer_status=0x580000 format_cache_kept=1 controller_callback_slot=0");
    return 0;
}
static void finish(void)
{
    if(state.guard_held) {reservation.release();state.guard_held=0;}
    state.busy=0;state.worker_active=0;pthread_mutex_unlock(&mutex);
}
static void pending(int rc,const char *reason,void *temporary)
{
    state.faults=1;state.clean_completion=0;
    if(temporary && temporary!=state.retained_request) {
        state.cleanup_free_rc=transport.release(state.reply_owner,temporary);
        if(state.cleanup_free_rc) {state.retained_cleanup=temporary;state.cleanup_owner=state.reply_owner;}
        else state.cleanup_freed++;
    }
    char text[420];snprintf(text,sizeof text,"generation=3 reason=%s rc=%d request=%p events=%u queued=%u retained_cleanup=%u faulted_pending=1 normal_completion=0 ap_consumed=0",reason,rc,state.retained_request,state.events,state.queued,(unsigned int)(state.retained_cleanup!=0));
    log_event("FULL_ADF_SET_OUTPUT_PENDING ",text);finish();
}
static void *worker(void *unused)
{
    (void)unused;pthread_mutex_lock(&mutex);
    if(!current_process() || !state.busy || state.generation!=3 || !state.retained_request || state.initialized!=1) {
        pending(-1021,"worker-ownership",0);return 0;
    }
    int rc=reservation.reserve();
    if(rc) {pending(rc,"resource-reservation",0);return 0;}
    state.guard_held=1;rc=backend();
    if(rc || state.faults) {pending(rc?rc:-1021,"backend-not-complete",0);return 0;}
    state.applications=1;
    log_event("FULL_ADF_SET_OUTPUT_APPLIED ","generation=3 format_bytes=20 format_copies=1 format_readbacks=1 control3_old_mask=8 target_mask=8 system_sound_snapshot_known=0 monitor_configures=1 B0_newly_consumed=1 disable_writes_total=21 disable_readbacks_total=21 global_event=9 avio_job_consumed=1 callback_status=0 shadow_writes_added=0 inner_consumed=1 outer_status=0x580000");
    void *reply=0;pthread_mutex_unlock(&mutex);
    rc=transport.allocate(state.reply_owner,&reply,12,1);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;
    if(reply==state.retained_request) {pending(-1021,"allocator-returned-original-request",0);return 0;}
    if(rc || !reply || transport.size(reply)!=12 || state.faults) {pending(rc?rc:-1021,"reply-allocation",reply);return 0;}
    unsigned char response[12]={0x0d,0x20,0x2d,0x13,12,0,1,0x80,0,0,0x58,0};
    memcpy(reply,response,12);transport.set_source(reply,FULL_ADF_SET_OUTPUT_INPUT);
    if(transport.source(reply)!=FULL_ADF_SET_OUTPUT_INPUT || transport.size(reply)!=12 || memcmp(reply,response,12)) {
        pending(-1021,"reply-readback",reply);return 0;
    }
    state.live_reply=reply;rc=transport.send(state.reply_owner,reply);state.send_rc=rc;
    if(rc) {state.live_reply=0;pending(rc,"reply-send",reply);return 0;}
    state.queued=1;
    char text[350];snprintf(text,sizeof text,"generation=3 destination=%#x source=0x92840747 reply=%p bytes=12 raw=0d202d130c00018000005800 B0_new=1 AVIO_NoOp_consumed=1 global_event=9",state.reply_owner,reply);
    log_event("FULL_ADF_SET_OUTPUT_QUEUED ",text);
    void *request=state.retained_request;state.request_free_rc=transport.release(state.request_owner,request);
    if(state.request_free_rc)state.faults=1;
    else {state.retained_request=0;state.request_owner=0;state.request_freed=1;}
    state.clean_completion=!state.faults && !state.retained_request && !state.retained_cleanup;
    snprintf(text,sizeof text,"generation=3 request=%p request_free_rc=%d retained_request=%u clean_completion=%u queued=1 ap_consumed=0",request,state.request_free_rc,(unsigned int)(state.retained_request!=0),state.clean_completion);
    log_event(state.faults?"FULL_ADF_SET_OUTPUT_FAULT ":"FULL_ADF_SET_OUTPUT_COMMIT ",text);finish();return 0;
}
int full_adf_set_output_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                                const struct full_adf_proc_guard *guard,int enabled,int *result)
{
    if(enabled!=1 || destination!=FULL_ADF_SET_OUTPUT_INPUT || !request || !io || !result)return 0;
    if(!current_process()) {*result=-1021;return 1;}
    if(!io->size)return 0;
    unsigned int bytes=io->size(request);
    if(bytes<4 || u16(request)!=0x200d || u16((unsigned char *)request+2)!=0x32d)return 0;
    if(!io->source || !io->allocate || !io->release || !io->set_source || !io->send ||
       !guard || !guard->reserve || !guard->release || bytes!=26) {*result=-1021;return 1;}
    static const unsigned char expected[26]={0x0d,0x20,0x2d,3,26,0,1,0x80,0,0,1,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0};
    unsigned int caller=io->source(request);
    if(memcmp(request,expected,26) || (caller>>28)!=8 || !(caller&0x0fffffff)) {*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    if(state.known!=1 || state.initialized!=1 || state.requests || state.busy || state.faults ||
       state.live_reply || state.retained_request || state.retained_cleanup) {pthread_mutex_unlock(&mutex);*result=-1021;return 1;}
    transport=*io;reservation=*guard;state.configured=1;state.generation=3;state.requests=1;state.busy=1;state.worker_active=1;
    state.request_owner=FULL_ADF_SET_OUTPUT_INPUT;state.reply_owner=caller;state.retained_request=request;
    memset(state.format,0,sizeof state.format);memcpy(state.format+4,(unsigned char *)request+10,16);
    state.format_copies=1;
    if(memcmp(state.format+4,(unsigned char *)request+10,16) || u32(state.format)) {
        pending(-1021,"format-copy-readback",0);*result=0;return 1;
    }
    state.format_readbacks=1;
    char text[350];snprintf(text,sizeof text,"generation=3 caller=%#x request=%p bytes=26 raw=0d202d031a000180000001000101010100000000000000000000 format20=0000000001000101010100000000000000000000 format_readback=1 normal_completion=0",caller,request);
    log_event("FULL_ADF_SET_OUTPUT_REQUEST ",text);
    pthread_attr_t attr;int rc=pthread_attr_init(&attr);
    if(!rc) {
        rc=pthread_attr_setdetachstate(&attr,PTHREAD_CREATE_DETACHED);pthread_t thread;
        if(!rc)rc=pthread_create(&thread,&attr,worker,0);
        pthread_attr_destroy(&attr);
    }
    if(rc) {pending(rc,"worker-create",0);*result=0;return 1;}
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}
int full_adf_set_output_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                                    void (*record)(const char *,const char *),int *result)
{
    if(!pointer || !release || !result)return 0;
    if(!current_process()) {*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);int kind;unsigned int expected;
    if(pointer==state.live_reply) {kind=1;expected=state.reply_owner;}
    else if(pointer==state.retained_cleanup) {kind=2;expected=state.cleanup_owner;}
    else if(pointer==state.retained_request) {kind=3;expected=state.request_owner;}
    else {pthread_mutex_unlock(&mutex);return 0;}
    int rc=destination==expected && !(kind==3 && state.busy)?release(destination,pointer):-1021;
    if(rc) {state.faults=1;state.clean_completion=0;if(kind==1)state.retained_reply=pointer;}
    else if(kind==1) {state.live_reply=0;state.retained_reply=0;state.reply_freed++;state.ap_consumed=1;}
    else if(kind==2) {state.retained_cleanup=0;state.cleanup_owner=0;state.cleanup_freed++;}
    else {state.retained_request=0;state.request_owner=0;state.request_freed++;}
    if(kind==1)state.reply_free_rc=rc;
    if(kind==2)state.cleanup_free_rc=rc;
    if(kind==3)state.request_free_rc=rc;
    char text[350];snprintf(text,sizeof text,"generation=3 destination=%#x expected=%#x pointer=%p kind=%s rc=%d faults=%u retained=%u ap_consumed=%u metadata_completion_only=1",destination,expected,pointer,kind==1?"queued-reply":kind==2?"local-cleanup":"original-request",rc,state.faults,(unsigned int)(rc!=0),(unsigned int)(!rc && kind==1));
    event(record,rc?"FULL_ADF_SET_OUTPUT_FAULT ":kind==1?"FULL_ADF_SET_OUTPUT_REPLY_FREE ":"FULL_ADF_SET_OUTPUT_RECOVERY_FREE ",text);
    pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
void full_adf_set_output_snapshot(struct full_adf_set_output_snapshot *out)
{
    if(!out)return;
    if(!current_process()) {*out=(struct full_adf_set_output_snapshot){.faults=1,.owner_pid=atomic_load(&owner_pid)};return;}
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=atomic_load(&owner_pid);pthread_mutex_unlock(&mutex);
}
#ifdef FULL_ADF_SET_OUTPUT_TEST
void full_adf_set_output_test_event_limit(unsigned int value) {event_limit=value;}
#endif
