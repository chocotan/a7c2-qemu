/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "adf-set-input-device.h"
#include "adf-set-input-cold-owners.h"
#include "adf-aip-commands.h"
#include "adf-aip-input-config.h"
#include "adf-source7-clock.h"
#include "adf-avio-output.h"
#include "adf-hdmi-monitor.h"
#include "adf-aip-disable.h"
#include <errno.h>
#include <fcntl.h>
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
static struct full_adf_set_input_snapshot state;
static struct full_imaging_io transport;
static struct full_adf_proc_guard reservation;
static struct full_adf_proc_input_owners owners;
static struct full_adf_public_config configuration;
static struct full_adf_aip_input_config registers;
static unsigned char inner[12],failure_history[120];
static struct {
    unsigned int live, target, sender, flags;
    struct full_adf_source7_event value;
} source5_event;
#ifdef FULL_ADF_SET_INPUT_TEST
static const char *seed_path="/seed-backup.bin";
static unsigned int event_limit=4;
#else
static const char seed_path[]="/seed-backup.bin";
#endif
static int current_process(void)
{
    int pid=(int)getpid(),unbound=0;
    atomic_compare_exchange_strong(&owner_pid,&unbound,pid);
    return atomic_load(&owner_pid)==pid;
}
int full_adf_set_input_owner_init(void) {return current_process()?0:-1021;}
static unsigned int u16(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p) {return u16(p)|u16(p+2)<<16;}
static void put32(unsigned char *p,unsigned int value)
{
    for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(value>>(8*i));
}
static void event(void (*record)(const char *,const char *),const char *tag,const char *text)
{
    char line[1380];
    snprintf(line,sizeof line,"%s pid=%d tid=%ld scope=virtualInputConfigurationS0 original_cp_executed=0 hardware_verified=0 native_frequency_verified=0 original_event_identity_verified=0 pcm_verified=0 frames_verified=0 capture_verified=0",text,getpid(),syscall(SYS_gettid));
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
static int enqueue(unsigned int opcode,unsigned int bytes)
{
    unsigned char command[12]={0};put32(command,opcode);put32(command+4,bytes);
    return full_adf_aip_commands_input_enqueue(owners.commands,command,bytes,2);
}
static void glee_complete(void *context,unsigned int status)
{
    if(context!=&state || status || !state.busy || !state.guard_held || state.glee_callbacks ||
       state.config_commits || state.inner_queued || state.pending_config!=1 || state.digital_pending ||
       !owners.glee->callback_active || owners.glee->callbacks_started!=1 || owners.glee->callbacks_returned ||
       !owners.hotshoe->busy || owners.hotshoe->popped!=1 || owners.commands->input.enqueued!=3) {
        state.faults=1;return;
    }
    state.glee_callbacks=1;state.completion_mask|=1;
    state.active_type=0;state.active_channels=2;state.active_sampling=0;state.active_depth=0;
    state.config_commits=1;state.pending_config=0;state.completion_mask=0;
    static const unsigned char completed[12]={4,0x20,1,0x84,12,0,1,0,0,0,0,0};
    memcpy(inner,completed,sizeof inner);state.inner_queued=1;
    log_event("FULL_ADF_SET_INPUT_METADATA ","generation=2 glee_callback_status=0 owner_request_generation=1 hotshoe_callback_running=1 queued_commands=3 active_cache=00020000 completion_mask_consumed=1 digital_pending=0 config_commits=1 inner_queued=1 inner_raw=042001840c00010000000000 AIP102_queued=0 outer_published=0");
}
static void hotshoe_complete(void *context,unsigned int status)
{
    if(context!=&state || status || state.hotshoe_callbacks || !owners.hotshoe->busy ||
       owners.hotshoe->fifo_count || owners.hotshoe->popped!=1 || state.software_s) {state.faults=1;return;}
    state.hotshoe_callbacks=1;
    if(enqueue(0xad,8) || enqueue(0xab,12) || enqueue(0xae,12)) {state.faults=1;return;}
    state.control139=1;
    /* Mode0: 131 clears bit1 without queuing48 or invoking a null callback. */
    state.mask650&=~2u;state.control131=1;
    log_event("FULL_ADF_SET_INPUT_CONTROL139 ","generation=2 parameters=0/0/0/2 queued=AD/AB0/AE0 command_count=3 control131_parameter=0x20 callback=0 mode=0 mask650=0 opcode48_queued=0");
    if(full_adf_glee_input_control0(owners.glee,1,0,0,1,glee_complete,&state) || state.faults) {
        state.faults=1;return;
    }
    unsigned int type=99,source=99,callback=99;
    if(full_adf_glee_input_control1(owners.glee,&type,&source,&callback) || type || source!=1 || callback ||
       !owners.glee->complete || owners.glee->callbacks_returned!=1 || state.glee_callbacks!=1 ||
       state.config_commits!=1 || state.inner_queued!=1) {state.faults=1;return;}
    state.glee_readbacks=1;
    log_event("FULL_ADF_SET_INPUT_GLEE ","generation=2 same_initialized_owner=1 owner_request_generation=1 control30_notes=1 control0_callbacks=1 control1_type=0 control1_source=1 control1_callback=0 input_ring=0 kind_cache=0 power20=0 power21=0 power22=0 power_state=2 synchronous_reference_branch=1");
    if(state.abb660!=1 || state.abb65c || state.abb_bb || state.abb_c0) {state.faults=1;return;}
    state.control141=2;
    unsigned char command02[44];
    if(full_adf_aip_input_config_make02(&registers,command02,sizeof command02) ||
       enqueue(0xb8,12) || enqueue(3,12) ||
       full_adf_aip_commands_input_enqueue(owners.commands,command02,sizeof command02,2) ||
       enqueue(0x11,8) || enqueue(0xb6,12) || enqueue(0xb7,12)) {state.faults=1;return;}
    state.control102=1;
    if(state.value7c!=1) {state.faults=1;return;}
    state.control110=1;
    log_event("FULL_ADF_SET_INPUT_CONTROL102 ","generation=2 metadata_already_committed=1 control141_queries=2 control141_value=1 selector=2 source_parameters=3/0/0/0/0/0/0/1/0/0 queued=B8/03/02/11/B6/B7 command_count=9 body_bytes=132 control110_parameter=1 existing7c=1 opcode42_queued=0");
}
static int execute_command(void *context,const unsigned char *command,unsigned int bytes,unsigned int *status)
{
    if(context!=&state || !command || !status || !state.busy || !state.guard_held || state.software_s ||
       bytes<8 || u32(command+4)!=bytes)return -1021;
    unsigned int opcode=u32(command);int rc=0;
    switch(opcode) {
    case 0xad:state.soft74490=0;*status=0;break;
    case 0xab:
        /* b658b4 only accepts S1/S6; S0 does not execute the C008/C00C writes. */
        state.ab_failures++;*status=1;break;
    case 0xae:state.soft743ac=0;*status=0;break;
    case 0xb8:state.soft744c0=0;*status=0;break;
    case 3:rc=full_adf_aip_input_config_consume03(&registers,u32(command+8));*status=0;break;
    case 2:rc=full_adf_aip_input_config_consume02(&registers,command,bytes);*status=0;break;
    case 0x11: {
        unsigned int feature=99;
        if(full_adf_public_config_read(&configuration,0x690228,&feature) || feature)return -1021;
        *status=0;break;
    }
    case 0xb6:state.soft743d0=0;*status=0;break;
    case 0xb7:state.soft743d4=0;*status=0;break;
    default:return -1021;
    }
    if(rc || registers.fault)return -1021;
    state.provider_calls++;
    state.config03=registers.applies03;state.config02=registers.applies02;
    state.config_writes=registers.writes;state.config_readbacks=registers.readbacks;
    state.config_public_reads=registers.public_reads;state.config_write_hash=registers.write_hash;
    if(opcode==2 || opcode==3) {
        char text[720];
        snprintf(text,sizeof text,"generation=2 opcode=%#x selector=%u applied03=%u applied02=%u writes=%u readbacks=%u public_reads=%u write_hash=%016llx cache0=%#x cache1=%#x cache7=%#x cache8=%#x route2060=%u route2064=%u route2068=%u route206c=%u classification2008=%u classification200c=%u active=%u flag3c=%u",
            opcode,registers.selector,registers.applies03,registers.applies02,registers.writes,registers.readbacks,
            registers.public_reads,registers.write_hash,registers.cache[0],registers.cache[1],registers.cache[7],registers.cache[8],
            registers.registers[0x60/4],registers.registers[0x64/4],registers.registers[0x68/4],registers.registers[0x6c/4],
            registers.registers[8/4],registers.registers[12/4],registers.active,registers.flag3c);
        log_event("FULL_ADF_SET_INPUT_CONFIG_READBACK ",text);
    }
    return 0;
}
static int notify_source5(const struct full_adf_source7_event *produced,struct full_adf_source7_event *taken)
{
    struct full_adf_source7_snapshot cache;
    if(!produced || !taken || source5_event.live || produced->generation!=2 ||
       produced->sequence!=state.source5_consumed+5u || produced->hardware_source!=7 || produced->software_source!=5 ||
       full_adf_source7_clock_get(owners.clock,2,5,&cache) || cache.counter!=produced->cache.counter ||
       cache.phase!=produced->cache.phase || cache.epoch!=produced->cache.epoch)return -1021;
    source5_event.value=*produced;source5_event.target=owners.source5_target;
    source5_event.sender=owners.source5_sender;source5_event.flags=owners.source5_flags;source5_event.live=1;
    state.source5_queued++;
    if(source5_event.target!=0x9058003f || source5_event.sender!=0x928c0786 || source5_event.flags!=1 ||
       source5_event.value.generation!=2 || source5_event.value.sequence!=state.source5_consumed+5u ||
       source5_event.value.cache.counter!=cache.counter || source5_event.value.cache.epoch!=cache.epoch)return -1021;
    *taken=source5_event.value;source5_event.live=0;state.source5_consumed++;return 0;
}
static int backend(void)
{
    if(full_adf_proc_claim_input(&owners))return -1021;
    state.dependency_claimed=1;state.capability_word7=owners.capability_word7;state.capability_word8=owners.capability_word8;
    state.software_s=owners.software_s;
    if(state.software_s || owners.software_k || owners.capability_word0!=1 || state.capability_word7 || state.capability_word8!=1 || owners.output_target!=8 ||
       owners.source5_target!=0x9058003f || owners.source5_flags!=1 || owners.source5_software!=5 ||
       owners.source5_sender!=0x928c0786)return -1021;
    log_event("FULL_ADF_SET_INPUT_DEPENDENCIES ","generation=2 original_AP0323_reply_freed=1 same_hotshoe_owner=1 same_glee_owner=1 same_command_buffer=1 same_source7_clock=1 counter_before=4 epoch_before=4 capability_word7=0 capability_word8=1 output_target=8");
    int fd=open(seed_path,O_RDONLY|O_CLOEXEC);
    if(fd<0)return -1021;
    int rc=full_adf_public_config_load(&configuration,fd),closed=close(fd);
    if(rc || closed)return -1021;
    unsigned int variant,feature,other,selector;
    if(full_adf_public_config_read(&configuration,0x690219,&variant) ||
       full_adf_public_config_read(&configuration,0x690228,&feature) ||
       full_adf_public_config_read(&configuration,0x6902a8,&other) ||
       full_adf_public_config_read(&configuration,0x690227,&selector) || variant || feature || other || selector)return -1021;
    state.abb65c=variant;state.abb660=variant==0;state.abb_bb=feature;state.abb_c0=0;
    state.value7c=1; /* b6ce34's independent owned Abb reset, not original CP RAM. */
    unsigned int reset[FULL_ADF_AIP_INPUT_CONFIG_REGISTERS]={0};
    if(full_adf_aip_input_config_init(&registers,&configuration,owners.capability_word8,reset) || registers.selector!=2 ||
       full_adf_aip_commands_input_begin(owners.commands,2))return -1021;
    state.init_selector=registers.selector;state.pending_config=1;
    log_event("FULL_ADF_SET_INPUT_PUBLIC_CONFIG ","generation=2 source=public_ALLLANG_3dab key690219=0 key690227=0 key690228=0 key6902a8=0 capability_word8=1 init_selector=2 asset_bytes=393 known_bytes=362 unknown_bytes=31 unknown_read_policy=reject template=0x1116fd0 software_engine=0");
    if(full_adf_hotshoe_register(owners.hotshoe,1,hotshoe_complete,&state) ||
       full_adf_hotshoe_set_type(owners.hotshoe,1,0) || state.faults || !owners.hotshoe->complete ||
       owners.hotshoe->type_commits!=1 || owners.hotshoe->busy || owners.hotshoe->fifo_count ||
       owners.hotshoe->callbacks_returned!=1 || state.glee_readbacks!=1 || state.control102!=1 || state.control110!=1)return -1021;
    state.hotshoe_commits=owners.hotshoe->type_commits;
    log_event("FULL_ADF_SET_INPUT_HOTSHOE ","generation=2 owner_request_generation=1 callbacks=1 callback_returned=1 fifo_popped_before_callback=1 current_type_committed_after_callback=1 current_type=0 busy=0 fifo_count=0 asynchronous_power_work=0");
    uint64_t now;
    if(now_ns(&now) || full_adf_source7_clock_continue(owners.clock,now))return -1021;
    struct full_adf_source7_snapshot cache;
    if(full_adf_source7_clock_get(owners.clock,2,5,&cache) || cache.counter!=4 || cache.epoch!=4)return -1021;
    fd=timerfd_create(CLOCK_MONOTONIC,TFD_CLOEXEC);
    if(fd<0)return -1021;
    rc=-1021;
    for(unsigned int i=0;i<4;i++) {
#ifdef FULL_ADF_SET_INPUT_TEST
        if(i>=event_limit)goto timer_done;
#endif
        uint64_t deadline=owners.clock->deadline_ns;
        struct itimerspec timer={.it_value={.tv_sec=(time_t)(deadline/UINT64_C(1000000000)),
            .tv_nsec=(long)(deadline%UINT64_C(1000000000))}};
        if(timerfd_settime(fd,TFD_TIMER_ABSTIME,&timer,0))goto timer_done;
        uint64_t expirations=0;ssize_t got;
        do {got=read(fd,&expirations,sizeof expirations);} while(got<0 && errno==EINTR);
        if(got!=(ssize_t)sizeof expirations || expirations!=1 || now_ns(&now))goto timer_done;
        struct full_adf_source7_event tick;
        if(full_adf_source7_clock_expire(owners.clock,2,now,&tick) || tick.generation!=2 || tick.sequence!=i+5u ||
           tick.deadline_ns!=deadline || tick.observed_ns<deadline || tick.hardware_source!=7 || tick.software_source!=5 ||
           tick.hardware.counter!=i+5u || tick.hardware.epoch!=i+5u || tick.fb.counter!=tick.hardware.counter ||
           tick.cache.counter!=tick.hardware.counter || tick.fb.epoch!=tick.hardware.epoch || tick.cache.epoch!=tick.hardware.epoch ||
           tick.fb.phase!=tick.hardware.phase || tick.cache.phase!=tick.hardware.phase)goto timer_done;
        state.events++;state.hardware_counter=tick.hardware.counter;state.hardware_epoch=(unsigned int)tick.hardware.epoch;
        struct full_adf_source7_event delivered;
        if(notify_source5(&tick,&delivered))goto timer_done;
        tick=delivered;
        char text[850];
        snprintf(text,sizeof text,"generation=2 event=%llu guest_timerfd_expirations=%llu deadline_ns=%llu observed_ns=%llu hardware_counter=%u epoch=%llu hardware_source=7 software_source=5 subscriber=0x9058003f sender=0x928c0786 queued=%u consumed=%u policy_period_ns=1000000 getter_advances=0",
            (unsigned long long)tick.sequence,(unsigned long long)expirations,(unsigned long long)deadline,
            (unsigned long long)tick.observed_ns,tick.hardware.counter,(unsigned long long)tick.hardware.epoch,
            state.source5_queued,state.source5_consumed);
        log_event("FULL_ADF_SET_INPUT_EVENT ",text);
        if(full_adf_aip_commands_input_flush(owners.commands,2,tick.sequence,execute_command,&state) || owners.commands->fault)goto timer_done;
        struct full_adf_aip_input_commands *batch=&owners.commands->input;
        state.aip_dispatches=batch->dispatches;state.last_task_status=batch->task_status;
        state.ring_read=batch->ring_read;state.ring_write=batch->ring_write;state.last_snapshot_count=batch->snapshot_count;
        if(i==0) {
            state.first_snapshot_count=batch->snapshot_count;state.first_checked=batch->checked;
            state.first_cursor=batch->local_cursor;state.first_task_status=batch->task_status;state.uninspected=batch->uninspected;
            if(state.first_snapshot_count!=9 || state.first_checked!=2 || state.first_cursor!=6 ||
               state.first_task_status!=FULL_ADF_AIP_TASK_ERROR || state.uninspected!=7 || state.provider_calls!=9 || state.ab_failures!=1 ||
               state.config03!=1 || state.config02!=1 || !state.config_writes || state.config_writes!=state.config_readbacks)goto timer_done;
            memcpy(failure_history,batch->failure_snapshot,sizeof failure_history);
        } else if(batch->snapshot_count || batch->task_status || memcmp(failure_history,batch->failure_snapshot,sizeof failure_history))goto timer_done;
        if(batch->ring_read!=batch->ring_write || owners.commands->command_count || owners.commands->cursor)goto timer_done;
        snprintf(text,sizeof text,"generation=2 event=%llu dispatches=%u commands_interpreted=%u AB_status=%u task_rc=%#x snapshot_count=%u checked=%u cursor_words=%u first_uninspected_preserved=%u ring_read=%u ring_write=%u failure_history_preserved=1 old_tail_rechecked=0 register_writes=%u register_readbacks=%u original_error_time_verified=0",
            (unsigned long long)tick.sequence,state.aip_dispatches,state.provider_calls,batch->failure_status,
            batch->task_status,batch->snapshot_count,batch->checked,batch->local_cursor,state.uninspected,
            batch->ring_read,batch->ring_write,state.config_writes,state.config_readbacks);
        log_event("FULL_ADF_SET_INPUT_AIP_DISPATCH ",text);
    }
    if(state.events==4 && state.hardware_counter==8 && state.hardware_epoch==8 && !owners.clock->armed &&
       state.source5_queued==4 && state.source5_consumed==4 && state.aip_dispatches==4 &&
       state.provider_calls==9 && state.ab_failures==1 && !state.ab_register_writes && !state.feature_callbacks &&
       state.last_task_status==0 && state.last_snapshot_count==0 && state.first_task_status==FULL_ADF_AIP_TASK_ERROR && state.uninspected==7 &&
       state.config_commits==1 && !state.pending_config && state.inner_queued==1 && !state.inner_consumed &&
       !memcmp(inner,"\x04\x20\x01\x84\x0c\x00\x01\x00",8))rc=0;
timer_done:
    if(close(fd))rc=-1021;
    if(rc && owners.clock->armed)full_adf_source7_clock_cancel(owners.clock,2);
    return rc;
}
static int relay_inner(void)
{
    if(state.inner_queued!=1 || state.inner_consumed ||
       memcmp(inner,"\x04\x20\x01\x84\x0c\x00\x01\x00",8))return -1021;
    state.inner_status=u32(inner+8);state.outer_status=state.inner_status|0x580000u;
    if(state.inner_status || state.outer_status!=0x580000)return -1021;
    state.inner_consumed=1;
    log_event("FULL_ADF_SET_INPUT_INNER_RELAY ","generation=2 source=0x9058003f target=0x928407b9 raw=042001840c00010000000000 status=0 outer_status=0x580000 first_AIP_task_rc=0x1004 AB_status=1 metadata_completion_independent=1 conservative_publication_after_data_work=1");
    return 0;
}
static int discard(void *pointer,unsigned int owner)
{
    int rc=transport.release(owner,pointer);state.cleanup_free_rc=rc;
    if(rc) {state.retained_cleanup=pointer;state.cleanup_owner=owner;}
    else state.cleanup_freed++;
    return rc;
}
static int publish_kikilog(void)
{
    state.kikilog_attempted=1;void *message=0;
    pthread_mutex_unlock(&mutex);
    int rc=transport.allocate(FULL_ADF_SET_INPUT_KIKILOG,&message,20,1);
    pthread_mutex_lock(&mutex);state.kikilog_allocate_rc=rc;
    if(message==state.retained_request || (!rc && !message))return -1021;
    if(rc) {
        if(message && discard(message,FULL_ADF_SET_INPUT_KIKILOG))return -1021;
        log_event("FULL_ADF_SET_INPUT_KIKILOG_OPTIONAL ","generation=2 allocated=0 metadata_completion_not_blocked=1 parameter_consumption_verified=0");return 0;
    }
    if(transport.size(message)!=20) {discard(message,FULL_ADF_SET_INPUT_KIKILOG);return -1021;}
    unsigned char body[20]={0};body[0]=0x84;body[1]=2;put32(body+2,0x2111);put32(body+6,0x81000000);body[11]=2;
    memcpy(message,body,20);state.kikilog_allocator_source=transport.source(message);
    if(memcmp(message,body,20)) {discard(message,FULL_ADF_SET_INPUT_KIKILOG);return -1021;}
    rc=transport.send(FULL_ADF_SET_INPUT_KIKILOG,message);state.kikilog_send_rc=rc;
    if(rc) {
        if(discard(message,FULL_ADF_SET_INPUT_KIKILOG))return -1021;
        log_event("FULL_ADF_SET_INPUT_KIKILOG_OPTIONAL ","generation=2 send_failed=1 temporary_freed=1 metadata_completion_not_blocked=1 parameter_consumption_verified=0");return 0;
    }
    state.kikilog_queued=1;
    char text[420];snprintf(text,sizeof text,"generation=2 destination=0x811006e9 bytes=20 raw=8402112100000000008100020000000000000000 allocator_source=%#x source_overridden=0 padding18_19=virtual_zero kernel_owns_message=1 kernel_free_observed=0 parameter_consumption_verified=0",state.kikilog_allocator_source);
    log_event("FULL_ADF_SET_INPUT_KIKILOG_QUEUED ",text);
    /* Ownership transferred to the kernel. Do not retain/dereference/free its pointer. */
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
    if(temporary && temporary!=state.retained_request)discard(temporary,state.reply_owner);
    char text[520];snprintf(text,sizeof text,"generation=2 reason=%s rc=%d request=%p request_owner=%#x events=%u applications=%u queued=%u retained_cleanup=%u faulted_pending=1 normal_completion=0 ap_consumed=0",
        reason,rc,state.retained_request,state.request_owner,state.events,state.applications,state.queued,(unsigned int)(state.retained_cleanup!=0));
    log_event("FULL_ADF_SET_INPUT_PENDING ",text);finish();
}
static void *worker(void *unused)
{
    (void)unused;pthread_mutex_lock(&mutex);
    if(!current_process() || state.generation!=2 || !state.busy || !state.retained_request) {
        pending(-1021,"worker-ownership",0);return 0;
    }
    int rc=reservation.reserve();
    if(rc) {pending(rc,"resource-reservation",0);return 0;}
    state.guard_held=1;rc=backend();
    if(rc || state.faults) {pending(rc?rc:-1021,"backend-not-complete",0);return 0;}
    if(publish_kikilog() || state.retained_cleanup) {pending(-1021,"optional-log-ownership",0);return 0;}
    if(relay_inner()) {pending(-1021,"inner-relay",0);return 0;}
    state.applications=1;
    log_event("FULL_ADF_SET_INPUT_APPLIED ","generation=2 metadata_cache=00020000 config_commits=1 hotshoe_callbacks=1 glee_callbacks=1 control1_readbacks=1 selector=2 AIP_commands_interpreted=9 AIP_first_checked=2 AIP_uninspected=7 AIP_first_task_rc=0x1004 AB_status=1 AB_register_writes=0 data_config03=1 data_config02=1 inner_consumed=1 outer_status=0x580000 events=4 global_counter=8 hardware_audio_success=0");
    void *reply=0;pthread_mutex_unlock(&mutex);
    rc=transport.allocate(state.reply_owner,&reply,12,1);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;
    if(reply==state.retained_request) {pending(-1021,"allocator-returned-original-request",0);return 0;}
    if(rc || !reply || transport.size(reply)!=12 || state.faults) {pending(rc?rc:-1021,"reply-allocation",reply);return 0;}
    unsigned char body[12]={0x0d,0x20,0x36,0x13,12,0,1,0x80,0,0,0x58,0};
    memcpy(reply,body,12);transport.set_source(reply,FULL_ADF_SET_INPUT_INPUT);
    if(transport.source(reply)!=FULL_ADF_SET_INPUT_INPUT || transport.size(reply)!=12 || memcmp(reply,body,12)) {
        pending(-1021,"reply-readback",reply);return 0;
    }
    state.live_reply=reply;rc=transport.send(state.reply_owner,reply);state.send_rc=rc;
    if(rc) {state.live_reply=0;pending(rc,"reply-send",reply);return 0;}
    state.queued=1;
    char text[320];snprintf(text,sizeof text,"generation=2 destination=%#x source=0x92840747 reply=%p bytes=12 raw=0d2036130c00018000005800 AB_status=1 AIP_task_rc=0x1004 metadata_completion=1",state.reply_owner,reply);
    log_event("FULL_ADF_SET_INPUT_QUEUED ",text);
    void *request=state.retained_request;state.request_free_rc=transport.release(state.request_owner,request);
    if(state.request_free_rc)state.faults=1;
    else {state.retained_request=0;state.request_owner=0;state.request_freed=1;}
    state.clean_completion=!state.faults && !state.retained_request && !state.retained_cleanup;
    snprintf(text,sizeof text,"generation=2 request=%p request_free_rc=%d retained_request=%u clean_completion=%u queued=1 ap_consumed=0",request,state.request_free_rc,(unsigned int)(state.retained_request!=0),state.clean_completion);
    log_event(state.faults?"FULL_ADF_SET_INPUT_FAULT ":"FULL_ADF_SET_INPUT_COMMIT ",text);finish();return 0;
}
int full_adf_set_input_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                               const struct full_adf_proc_guard *guard,int enabled,int *result)
{
    if(enabled!=1 || destination!=FULL_ADF_SET_INPUT_INPUT || !request || !io || !result)return 0;
    if(!current_process()) {*result=-1021;return 1;}
    if(!io->size)return 0;
    unsigned int bytes=io->size(request);
    if(bytes<4 || u16(request)!=0x200d || u16((unsigned char *)request+2)!=0x336)return 0;
    if(!io->source || !io->allocate || !io->release || !io->set_source || !io->send ||
       !guard || !guard->reserve || !guard->release || bytes!=14) {*result=-1021;return 1;}
    static const unsigned char expected[14]={0x0d,0x20,0x36,3,14,0,1,0x80,0,2,0,0,0,0};
    unsigned int caller=io->source(request);
    if(memcmp(request,expected,14) || (caller>>28)!=8 || !(caller&0x0fffffff)) {*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    if(state.requests || state.busy || state.faults || state.live_reply || state.retained_request || state.retained_cleanup) {
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    transport=*io;reservation=*guard;state.configured=1;state.generation=2;state.requests=1;
    state.busy=1;state.worker_active=1;state.retained_request=request;
    state.request_owner=FULL_ADF_SET_INPUT_INPUT;state.reply_owner=caller;
    char text[300];snprintf(text,sizeof text,"generation=2 caller=%#x request=%p bytes=14 raw=0d2036030e000180000200000000 known_AB_failure_preserved=1 metadata_completion_only=1 normal_completion=0",caller,request);
    log_event("FULL_ADF_SET_INPUT_REQUEST ",text);
    pthread_attr_t attr;int rc=pthread_attr_init(&attr);
    if(!rc) {
        rc=pthread_attr_setdetachstate(&attr,PTHREAD_CREATE_DETACHED);pthread_t thread;
        if(!rc)rc=pthread_create(&thread,&attr,worker,0);
        pthread_attr_destroy(&attr);
    }
    if(rc) {pending(rc,"worker-create",0);*result=0;return 1;}
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}
int full_adf_set_input_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
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
    char text[400];snprintf(text,sizeof text,"generation=2 destination=%#x expected=%#x pointer=%p kind=%s rc=%d faults=%u retained=%u ap_consumed=%u AB_status=%u AIP_task_rc=%#x metadata_completion_only=1",
        destination,expected,pointer,kind==1?"queued-reply":kind==2?"local-cleanup":"original-request",rc,state.faults,(unsigned int)(rc!=0),(unsigned int)(!rc && kind==1),state.ab_failures?1u:0u,state.first_task_status);
    event(record,rc?"FULL_ADF_SET_INPUT_FAULT ":kind==1?"FULL_ADF_SET_INPUT_REPLY_FREE ":"FULL_ADF_SET_INPUT_RECOVERY_FREE ",text);
    pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
int full_adf_set_input_claim_output(struct full_adf_proc_input_owners *out)
{
    if(!out || !current_process())return -1021;
    for(unsigned long i=0;i<sizeof *out;i++)if(((unsigned char *)out)[i])return -1021;
    pthread_mutex_lock(&mutex);
    struct full_adf_source7_snapshot cache;
    unsigned int mask=0,type=99,source=99,driver_callback=99;
    full_adf_avio_listener output_callback=0;
    if(state.output_handoff || state.busy || state.worker_active || state.guard_held || state.faults ||
       state.generation!=2 || state.requests!=1 || state.applications!=1 || state.queued!=1 ||
       state.clean_completion!=1 || state.ap_consumed!=1 || state.retained_request || state.live_reply ||
       state.retained_reply || state.retained_cleanup || state.events!=4 || state.hardware_counter!=8 ||
       state.inner_consumed!=1 || state.source5_queued!=4 || state.source5_consumed!=4 || source5_event.live ||
       !owners.output || !owners.monitor || !owners.disable || !owners.commands || !owners.clock ||
       state.software_s || owners.software_s || owners.software_k ||
       full_adf_source7_clock_get(owners.clock,2,5,&cache) || cache.counter!=8 || cache.epoch!=8 || owners.clock->armed ||
       full_adf_avio_output_control3(owners.output,&mask,&output_callback) || mask!=8 || output_callback ||
       full_adf_glee_input_control1(owners.glee,&type,&source,&driver_callback) || type || source!=1 || driver_callback ||
       owners.monitor->identity!=owners.monitor || owners.monitor->fault || owners.monitor->pending ||
       owners.monitor->prepare_count!=1 || owners.monitor->commit_count!=1 || owners.monitor->configure_count ||
       owners.monitor->flag_240 || owners.monitor->flag_242 || owners.monitor->mode || owners.monitor->path ||
       owners.disable->calls!=2 || owners.disable->writes!=14 || owners.disable->readbacks!=14 ||
       (owners.disable->registers.active0400&1) ||
       owners.commands->fault || owners.commands->busy || owners.commands->command_count || owners.commands->cursor ||
       owners.commands->input.owner!=owners.commands || owners.commands->input.generation!=2 ||
       owners.commands->input.dispatches!=4 || owners.commands->input.last_event!=8 ||
       owners.commands->input.ring_read!=9 || owners.commands->input.ring_write!=9 ||
       owners.commands->input.snapshot_count || owners.commands->input.task_status ||
       owners.commands->input.failure_opcode!=0xab || owners.commands->input.failure_status!=1 ||
       owners.commands->input.failure_task_status!=FULL_ADF_AIP_TASK_ERROR) {
        pthread_mutex_unlock(&mutex);return -1021;
    }
    state.output_handoff=1;*out=owners;pthread_mutex_unlock(&mutex);return 0;
}
void full_adf_set_input_snapshot(struct full_adf_set_input_snapshot *out)
{
    if(!out)return;
    if(!current_process()) {*out=(struct full_adf_set_input_snapshot){.faults=1,.owner_pid=atomic_load(&owner_pid)};return;}
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=atomic_load(&owner_pid);pthread_mutex_unlock(&mutex);
}
#ifdef FULL_ADF_SET_INPUT_TEST
void full_adf_set_input_test_seed_path(const char *path) {seed_path=path;}
void full_adf_set_input_test_event_limit(unsigned int limit) {event_limit=limit;}
#endif
