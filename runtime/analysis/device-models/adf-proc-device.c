/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "adf-proc-device.h"
#include "adf-public-config.h"
#include "adf-idle-resources.h"
#include "adf-input-state.h"
#include "adf-set-input-cold-owners.h"
#include "adf-hdmi-monitor.h"
#include "adf-aip-coefficients.h"
#include "adf-aip-gates.h"
#include "adf-aip-disable.h"
#include "adf-aip-commands.h"
#include "adf-avio-output.h"
#include "adf-source7-clock.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/timerfd.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static struct full_adf_proc_snapshot state;
static struct full_imaging_io transport;
static struct full_adf_proc_guard reservation;
static struct full_adf_public_config configuration;
static struct full_adf_idle_resources resources;
static struct full_adf_input_state input;
static struct full_adf_hotshoe_owner hotshoe_input;
static struct full_adf_glee_input_owner glee_input;
static struct full_adf_aip_coefficients coefficients;
static struct full_adf_aip_gates gates;
static struct full_adf_aip_disable disable_registers;
static struct full_adf_aip_commands commands;
static struct full_adf_hdmi_monitor hdmi_monitor;
static struct {unsigned int live,source,token;unsigned char bytes[12];} inner_completion;
static struct full_adf_avio_output output;
static struct full_adf_source7_clock clock_source;
static struct full_adf_delay129 delay;
static struct {
    unsigned int target, flags, source, sender, live;
    struct full_adf_source7_event event;
} subscription;
#ifdef FULL_ADF_PROC_TEST
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
int full_adf_proc_owner_init(void) {return current_process()?0:-1021;}
static unsigned int u16(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p) {return u16(p)|u16(p+2)<<16;}
static const unsigned char command_af[8]={0xaf,0,0,0,8,0,0,0};
static const unsigned char command_b0[16]={0xb0,0,0,0,16,0,0,0,0,0,0,0,0,0,0,0};
static void event(void (*record)(const char *,const char *),const char *tag,const char *text)
{
    char line[1250];
    snprintf(line,sizeof line,"%s pid=%d tid=%ld scope=virtualSource7ControlOnly original_cp_executed=0 hardware_verified=0 native_frequency_verified=0 original_event_identity_verified=0 pcm_verified=0 frames_verified=0 capture_verified=0",text,getpid(),syscall(SYS_gettid));
    if(record)record(tag,line);
}
static void log_event(const char *tag,const char *text) {event(transport.record,tag,text);}
static int now_ns(uint64_t *out)
{
    struct timespec time;
    if(clock_gettime(CLOCK_MONOTONIC,&time) || time.tv_sec<0 || time.tv_nsec<0 ||
       time.tv_nsec>=1000000000L || (uint64_t)time.tv_sec>UINT64_MAX/UINT64_C(1000000000))return -1021;
    uint64_t seconds=(uint64_t)time.tv_sec*UINT64_C(1000000000);
    if(seconds>UINT64_MAX-(uint64_t)time.tv_nsec)return -1021;
    *out=seconds+(uint64_t)time.tv_nsec;return 0;
}
/* This bounded Glee query owns the first capability word used by 6797f8/67a1a0.
 * It is a pure reference capability, not a PCM/active-mixer/ready indication. */
static int query_capability(unsigned int *out)
{
    if(!out || configuration.system_selector!=0x20 || !configuration.known)return -1021;
    state.capability_word0=1;state.capability_word7=0;state.capability_word8=1;
    *out=state.capability_word0;
    return *out==1?0:-1021;
}
static void output_listener(void *context,unsigned int status)
{
    if(context!=&state || status || output.callback_calls!=1 || output.output_finished ||
       output.pending_events!=1 || output.consumed!=2 || output.source_cache!=0xff ||
       state.output_requests!=1 || state.avio_pending_mask!=2) {
        state.faults=1;return;
    }
    state.avio_callbacks++;state.avio_pending_mask&=~2u;
    log_event("FULL_ADF_PROC_AVIO_CALLBACK ","stage2_applied=1 callback_running=1 queue_commit_pending=1 source_cache=0xff output_requests=1 avio_pending_mask=0");
}
static int disable_command(void *context)
{
    if(context!=&gates || gates.software_s)return -1021;
    int rc=full_adf_aip_disable_apply(&disable_registers,gates.software_s);
    if(rc)return rc;
    state.disable_writes=disable_registers.writes;state.disable_readbacks=disable_registers.readbacks;
    char line[500];
    snprintf(line,sizeof line,"generation=1 event=%u calls=%u active0400=%#x software_byte=%u completion_byte=%u route8828=%#x route882c=%#x route8830=%#x route8928=%#x route892c=%#x route8930=%#x controla000=%#x writes=%u readbacks=%u",
        state.events,disable_registers.calls,disable_registers.registers.active0400,disable_registers.software_byte,
        disable_registers.completion_byte,disable_registers.registers.route8828,disable_registers.registers.route882c,
        disable_registers.registers.route8830,disable_registers.registers.route8928,disable_registers.registers.route892c,
        disable_registers.registers.route8930,disable_registers.registers.controla000,state.disable_writes,state.disable_readbacks);
    log_event("FULL_ADF_PROC_DISABLE_READBACK ",line);return 0;
}
static int monitor_enqueue(void *context,unsigned int mode,unsigned int enable,unsigned int channel)
{
    if(context!=&state || mode>1 || enable || channel || gates.software_s || gates.software_k)return -1021;
    if(mode==0) {
        if(state.events || state.global_state!=3 || state.af_queued ||
           full_adf_aip_commands_enqueue(&commands,command_af,8,1))return -1021;
        state.af_queued++;
        log_event("FULL_ADF_PROC_COMMAND_QUEUED ","generation=1 opcode=0xaf bytes=8 raw=af00000008000000 queued=1 consumed=0 canonical_cache_equal=1 owned_allocation=0 routing_pending=1");
    } else {
        if(state.events!=4 || state.global_state!=2 || state.b0_queued ||
           full_adf_aip_commands_enqueue(&commands,command_b0,16,1))return -1021;
        state.b0_queued++;
        log_event("FULL_ADF_PROC_COMMAND_QUEUED ","generation=1 event=4 opcode=0xb0 bytes=16 raw=b0000000100000000000000000000000 queued=1 consumed=0 canonical_cache_equal=1 owned_allocation=0 routing_pending=0");
    }
    return 0;
}
static void monitor_readback(unsigned int reason)
{
    char text[620];
    snprintf(text,sizeof text,"generation=1 reason=%u same_owned_monitor=1 initializations=%u mode=%u path=%u prepare=%u commit=%u configure=%u flag208=%u flag240=%u flag242=%u emitted_AF=%u emitted_B0=%u unknown243_known=0",
        reason,state.monitor_initializations,hdmi_monitor.mode,hdmi_monitor.path,hdmi_monitor.prepare_count,
        hdmi_monitor.commit_count,hdmi_monitor.configure_count,hdmi_monitor.flag_208,hdmi_monitor.flag_240,
        hdmi_monitor.flag_242,hdmi_monitor.emitted_af,hdmi_monitor.emitted_b0);
    log_event("FULL_ADF_PROC_HDMI_MONITOR ",text);
}
static int routing_prepare(void)
{
    if(state.routing_initialized!=1 || state.routing_pending || state.routing_prepared || gates.software_s || gates.software_k)return -1021;
    state.routing_pending=1;state.routing_prepared=1;
    if(full_adf_hdmi_monitor_prepare(&hdmi_monitor,1,monitor_enqueue,&state))return -1021;
    state.monitor_prepares=hdmi_monitor.prepare_count;monitor_readback(1);return 0;
}
static int routing_commit(void)
{
    if(state.routing_initialized!=1 || state.routing_pending!=1 || state.routing_prepared!=1 || gates.software_s || gates.software_k)return -1021;
    state.routing_pending=0;state.routing_prepared=0;
    if(full_adf_hdmi_monitor_commit(&hdmi_monitor,1,monitor_enqueue,&state))return -1021;
    state.monitor_commits=hdmi_monitor.commit_count;monitor_readback(4);return 0;
}
static int consume_commands(unsigned int event_sequence)
{
    if(full_adf_aip_commands_consume(&commands,1,event_sequence,disable_command,&gates))return -1021;
    state.af_consumed=commands.af_applied;state.b0_consumed=commands.b0_applied;state.command_sequence=commands.sequence;
    char line[360];
    snprintf(line,sizeof line,"generation=1 event=%u priority=4 AF_consumed=%u B0_consumed=%u command_sequence=%u command_count=%u cursor=%u response_pending=%u disable_writes=%u disable_readbacks=%u stateflag=%u",
        event_sequence,state.af_consumed,state.b0_consumed,state.command_sequence,commands.command_count,commands.cursor,
        commands.response_pending,state.disable_writes,state.disable_readbacks,commands.stateflag);
    log_event("FULL_ADF_PROC_COMMAND_CONSUMED ",line);
    return commands.command_count || commands.cursor || commands.response_pending || commands.fault?-1021:0;
}
static void input_listener(void *context,unsigned int status)
{
    if(context!=&state || status || input.pending!=1 || !input.submitted || input.driver_callback ||
       input.listeners_removed!=1 || input.complete || state.global_state!=1 || state.idle_stage!=5 ||
       state.pending_config!=1 || state.notify2 || state.notify0 || inner_completion.live) {state.faults=1;return;}
    state.input_callbacks++;
    log_event("FULL_ADF_PROC_INPUT_CALLBACK ","control30_consumed=1 driver_callback=0 owner_pending=1 submitted_callback=1 listener_removed=1 drain_pending=1");
    state.notify2=1;state.input_pending_at_notify2=input.pending;state.config_pending_at_notify2=state.pending_config;
    static const unsigned char completed[12]={4,0x20,2,0x81,12,0,1,0,0,0,0,0};
    memcpy(inner_completion.bytes,completed,12);inner_completion.source=0x9058003f;
    inner_completion.token=state.pending_token;inner_completion.live=1;state.inner_queued++;
    log_event("FULL_ADF_PROC_INNER_QUEUED ","generation=1 notification=2 source=0x9058003f pending_config=1 input_pending=1 inner_queued=1 bytes=12 raw=042002810c00010000000000 outer_reply_queued=0");
    state.idle_stage=7;state.notify0=1;state.global_state=2;
    state.active_path=state.pending_path;state.active_mode=state.pending_mode;
    state.active_format=state.pending_format;state.active_notify=state.pending_notify;
    state.pending_config=0;state.config_commits++;
    if(routing_commit()) {state.faults=1;return;}
    log_event("FULL_ADF_PROC_CONFIG_COMMIT ","generation=1 event=4 notification=0 after_notification=2 stage=7 path=0 mode=0 format=0 notify=0 pending_valid=0 commits=1 input_pending=1 no_stage24_execution=1 global_state=2");
}
static int source5_subscribe(void)
{
    static const unsigned int request[4]={1,0x9058003f,1,5};
    if(state.source5_registered || subscription.live || !clock_source.bound ||
       request[0]!=1 || request[2]!=1 || request[3]!=5)return -1021;
    subscription.target=request[1];subscription.flags=request[2];subscription.source=request[3];
    state.source5_registered=1;
    log_event("FULL_ADF_PROC_SOURCE5_SUBSCRIBE ","generation=1 command=1 target=0x9058003f flags=1 software_source=5 registered=1 virtual_subscription=1");
    return subscription.target==0x9058003f && subscription.flags==1 && subscription.source==5?0:-1021;
}
static int source5_notify(const struct full_adf_source7_event *produced,
                           struct full_adf_source7_event *consumed)
{
    struct full_adf_source7_snapshot cache;
    if(!produced || !consumed || state.source5_registered!=1 || subscription.live || state.source5_pending ||
       subscription.target!=0x9058003f || subscription.flags!=1 || subscription.source!=5 ||
       produced->generation!=1 || produced->sequence!=state.source5_consumed+1u ||
       produced->software_source!=5 || produced->hardware_source!=7 ||
       full_adf_source7_clock_get(&clock_source,1,5,&cache) || cache.epoch!=produced->cache.epoch ||
       cache.counter!=produced->cache.counter || cache.phase!=produced->cache.phase)return -1021;
    subscription.event=*produced;subscription.sender=0x928c0786;subscription.live=1;
    state.source5_pending=1;state.source5_queued++;
    char line[420];
    snprintf(line,sizeof line,"generation=1 event=%llu sender=%#x target=%#x software_source=%u counter=%u phase=%u epoch=%llu queued=%u pending=1 virtual_notification=1 original_message_layout_verified=0",
        (unsigned long long)subscription.event.sequence,subscription.sender,subscription.target,subscription.source,
        subscription.event.cache.counter,(unsigned int)subscription.event.cache.phase,
        (unsigned long long)subscription.event.cache.epoch,state.source5_queued);
    log_event("FULL_ADF_PROC_SOURCE5_QUEUED ",line);
    if(subscription.live!=1 || subscription.sender!=0x928c0786 || subscription.event.generation!=1 ||
       subscription.event.sequence!=state.source5_consumed+1u ||
       subscription.event.cache.counter!=cache.counter || subscription.event.cache.epoch!=cache.epoch)return -1021;
    *consumed=subscription.event;subscription.live=0;state.source5_pending=0;state.source5_consumed++;
    snprintf(line,sizeof line,"generation=1 event=%llu sender=0x928c0786 target=0x9058003f software_source=5 counter=%u epoch=%llu consumed=%u pending=0 audio_dispatch_order=AIP1-before-Glee virtual_notification=1 original_message_layout_verified=0",
        (unsigned long long)consumed->sequence,consumed->cache.counter,(unsigned long long)consumed->cache.epoch,
        state.source5_consumed);
    log_event("FULL_ADF_PROC_SOURCE5_CONSUMED ",line);
    return 0;
}
static int cold_stop(void)
{
    if(state.global_state || state.active_path || state.active_mode || state.active_format || state.active_notify ||
       state.pending_config || state.queued_config!=1 || state.start_job_registered ||
       (state.output_requests&3) || !full_adf_idle_resources_admissible(&resources) ||
       state.prelude_current!=1 || state.prelude_calls || configuration.prelude_flag!=1)return -1021;
    state.prelude_requested=1;state.prelude_config=configuration.prelude_flag!=0;state.prelude_calls++;
    log_event("FULL_ADF_PROC_PRELUDE ","generation=1 owner_requested=1 owner_current=1 key=0x58007b config_bool=1 control12d_calls=0 synchronous_consumption=1");
    state.global_state=3;
    if(routing_prepare())return -1021;
    state.start_job_registered=1;state.idle_stage=0;
    /* Old path0's low two request bits are both observed clear, not forcibly cleared. */
    if(state.output_requests&3)return -1021;
    state.stop_phase1=1;state.global_state=4;
    for(unsigned int cleanup=0;cleanup<3;cleanup++) {
        if(state.active_path)return -1021;
        state.stop_cleanup_calls++;
    }
    log_event("FULL_ADF_PROC_COLD_STOP ","generation=1 old_path=0 global_before=0 stop_state=3 notification=1 global_after=4 low_request_bits=0 cleanups=3 AIP_cancel_calls=0 AVIO_jobs=0 input_jobs=0 queued_config=1 start_priority=2 start_registered=1");
    return state.stop_cleanup_calls==3?0:-1021;
}
static int start_queued_request(unsigned int event_sequence)
{
    if(event_sequence!=1 || state.events!=1 || state.source5_consumed!=1 || state.global_state!=4 ||
       state.start_job_registered!=1 || state.start_job_consumed || state.queued_config!=1 ||
       state.pending_config || state.config_commits || state.requested_path || state.requested_mode ||
       state.requested_format || state.requested_notify)return -1021;
    state.start_job_registered=0;state.start_job_consumed=1;state.queued_config=0;
    state.pending_path=state.requested_path;state.pending_mode=state.requested_mode;
    state.pending_format=state.requested_format;state.pending_notify=state.requested_notify;
    state.pending_token=state.generation;state.pending_config=1;state.global_state=1;state.idle_stage=1;
    if(full_adf_idle_resources_prepare(&resources,1))return -1021;
    state.resource_preparations=resources.preparations;state.idle_stage=4;
    if(full_adf_aip_gates_mode0(&gates,1) || full_adf_aip_coefficients_mode0(&coefficients,1) ||
       full_adf_delay129_register(&delay,1,&clock_source) ||
       full_adf_avio_output_enqueue(&output,1,8,output_listener,&state))return -1021;
    state.output_requests=1;state.avio_pending_mask=2;
    state.coefficients=coefficients.writes;state.gate_writes=gates.writes;
    if(state.resource_preparations!=1 || state.coefficients!=16 || state.gate_writes!=5 ||
       coefficients.readbacks!=16 || gates.readbacks!=5 || gates.init_parameter_f!=state.init_f ||
       delay.control_state!=1 || !delay.registered || !delay.pending || state.pending_config!=1)return -1021;
    char line[900];
    snprintf(line,sizeof line,"generation=1 event=1 start_priority=2 queued_config=0 pending_config=1 global_state=1 idle_stage=4 controllers=2 stockers=5 pins=3 resources_prepared=1 coefficients=%u coefficient_readbacks=%u gate_writes=%u gate_readbacks=%u reset3900=%#x gate0c50=%#x gate8814=%#x classification0c54=%#x gate23e0=%#x control3904=%#x S=%u K=%u F=%u saved_counter=%u delay_state=1 pending=1 no_new_counter_no_completion=1",
        coefficients.writes,coefficients.readbacks,gates.writes,gates.readbacks,gates.registers.reset3900,
        gates.registers.gate0c50,gates.registers.gate8814,gates.registers.classification0c54,gates.registers.gate23e0,
        coefficients.control3904,gates.software_s,gates.software_k,gates.init_parameter_f,delay.saved74);
    log_event("FULL_ADF_PROC_PREPARED ",line);
    return 0;
}
static int backend(void)
{
    int fd=open(seed_path,O_RDONLY|O_CLOEXEC);
    if(fd<0)return -1021;
    int rc=full_adf_public_config_load(&configuration,fd),closed=close(fd);
    if(rc || closed)return -1021;
    unsigned int selector,source,pin,capability,prelude;
    if(full_adf_public_config_read(&configuration,0x58014a,&pin) ||
       full_adf_public_config_read(&configuration,0x5e028a,&selector) ||
       full_adf_public_config_read(&configuration,0xf900d2,&source) ||
       full_adf_public_config_read(&configuration,0x58007b,&prelude) ||
       selector!=0x20 || pin!=1 || source!=1 || prelude!=1 || query_capability(&capability))return -1021;
    state.pin_immediately=pin;state.output_source=source;state.config_fnv=configuration.fnv;
    state.init_f=capability==0?1:0; /* Full u32 comparison, original 67a1a0. */
    char line[900];
    snprintf(line,sizeof line,"generation=1 seed_bytes=%lu seed_fnv=%016llx cp_pin=1 selector=0x20 source=1 capability_word0=%u capability_word7=%u capability_word8=%u capability_query_rc=0 init_F=%u optional_branch=1 config_queries=%llu",
        configuration.bytes,configuration.fnv,capability,state.capability_word7,state.capability_word8,state.init_f,configuration.queries);
    log_event("FULL_ADF_PROC_OWNERS ",line);
    /* These are fresh owned virtual reset banks, never a claim about original CP RAM/MMIO. */
    unsigned int reset_coefficients[16]={0};
    const struct full_adf_aip_gate_registers reset_gates={0};
    const struct full_adf_aip_disable_registers reset_disable={0};
    unsigned char shadow[FULL_ADF_AVIO_SHADOW_BYTES]={0},bitmap[FULL_ADF_AVIO_BITMAP_BYTES]={0};
    hdmi_monitor.unknown_243=0xa5; /* Owned unknown-byte marker, not original CP RAM. */
    if(full_adf_hdmi_monitor_init(&hdmi_monitor) || full_adf_idle_resources_init(&resources) || full_adf_aip_gates_init(&gates,&reset_gates,state.init_f) ||
       full_adf_aip_coefficients_init(&coefficients,reset_coefficients,0) ||
       full_adf_aip_disable_init(&disable_registers,&reset_disable,0) || full_adf_aip_commands_init(&commands) ||
       full_adf_input_init(&input) || full_adf_hotshoe_owner_init(&hotshoe_input) ||
       full_adf_glee_input_owner_init(&glee_input) || full_adf_avio_output_init(&output,shadow,bitmap,bitmap,source) ||
       full_adf_source7_clock_init(&clock_source,0,0) ||
       full_adf_source7_clock_bind(&clock_source,1,5,7) || full_adf_delay129_init(&delay))return -1021;
    state.cold_owners_initialized=1;
    snprintf(line,sizeof line,"generation=1 owned_virtual_constructor=1 initializations=%u hotshoe_type=%u hotshoe_busy=%u hotshoe_fifo=%u input_type=%u input_source=%u input_callback=%u input_kind_cache=%u input_ring=%u power20=%u power21=%u power22=%u power_state=%u control30_notes=%u control0_calls=%u",
        state.cold_owners_initialized,hotshoe_input.current_type,hotshoe_input.busy,hotshoe_input.fifo_count,
        glee_input.input_type,glee_input.input_source,glee_input.input_callback_field,glee_input.kind_cache,
        glee_input.ring_count,glee_input.power.flag_20,glee_input.power.flag_21,glee_input.power.flag_22,
        glee_input.power.field_14,glee_input.control30_notes,glee_input.callbacks_started);
    log_event("FULL_ADF_PROC_COLD_OWNERS ",line);
    state.monitor_initializations=1;state.routing_initialized=1;monitor_readback(0);
    state.prelude_current=1; /* Explicit owned reset for the original {1,1,0} prelude object. */
    if(source5_subscribe() || cold_stop())return -1021;
    struct full_adf_source7_snapshot stable;
    if(full_adf_source7_clock_get(&clock_source,1,5,&stable) || stable.counter || stable.epoch ||
       delay.registered || delay.pending || delay.control_state || clock_source.events_delivered ||
       state.global_state!=4 || state.start_job_registered!=1 || state.pending_config || state.queued_config!=1)return -1021;
    log_event("FULL_ADF_PROC_START_PENDING ","generation=1 global_state=4 queued_config=1 start_priority=2 start_registered=1 events=0 no_expiry_no_start=1 no_inner_completion=1");
    uint64_t now;
    if(now_ns(&now) || full_adf_source7_clock_arm(&clock_source,1,now))return -1021;
    fd=timerfd_create(CLOCK_MONOTONIC,TFD_CLOEXEC);
    if(fd<0)return -1021;
    rc=-1021;
    for(unsigned int i=0;i<4;i++) {
#ifdef FULL_ADF_PROC_TEST
        if(i>=event_limit)goto timer_done;
#endif
        uint64_t deadline=clock_source.deadline_ns;
        struct itimerspec timer={.it_value={.tv_sec=(time_t)(deadline/UINT64_C(1000000000)),
            .tv_nsec=(long)(deadline%UINT64_C(1000000000))}};
        if(timerfd_settime(fd,TFD_TIMER_ABSTIME,&timer,0))goto timer_done;
        uint64_t expirations=0;ssize_t got;
        do {got=read(fd,&expirations,sizeof expirations);} while(got<0 && errno==EINTR);
        if(got!=(ssize_t)sizeof expirations || expirations!=1 || now_ns(&now))goto timer_done;
        struct full_adf_source7_event tick,notified;
        if(full_adf_source7_clock_expire(&clock_source,1,now,&tick) || tick.generation!=1 ||
           tick.sequence!=i+1 || tick.hardware_source!=7 || tick.software_source!=5 ||
           tick.deadline_ns!=deadline || tick.observed_ns<deadline ||
           tick.hardware.epoch!=tick.sequence || tick.fb.epoch!=tick.sequence || tick.cache.epoch!=tick.sequence ||
           tick.hardware.counter!=tick.fb.counter || tick.hardware.counter!=tick.cache.counter ||
           tick.hardware.phase!=tick.fb.phase || tick.hardware.phase!=tick.cache.phase)goto timer_done;
        state.events=clock_source.events_delivered;state.hardware_counter=tick.hardware.counter;
        state.cached_counter=tick.cache.counter;
        snprintf(line,sizeof line,"generation=1 event=%llu guest_timerfd_expirations=%llu deadline_ns=%llu observed_ns=%llu policy_period_ns=1000000 hardware_source=7 software_source=5 hardware_counter=%u phase=%u hardware_epoch=%llu fb_counter=%u fb_epoch=%llu cache_counter=%u cache_epoch=%llu getter_advances=0",
            (unsigned long long)tick.sequence,(unsigned long long)expirations,(unsigned long long)tick.deadline_ns,
            (unsigned long long)tick.observed_ns,tick.hardware.counter,(unsigned int)tick.hardware.phase,
            (unsigned long long)tick.hardware.epoch,tick.fb.counter,(unsigned long long)tick.fb.epoch,
            tick.cache.counter,(unsigned long long)tick.cache.epoch);
        log_event("FULL_ADF_PROC_EVENT ",line);
        if(source5_notify(&tick,&notified))goto timer_done;
        tick=notified;
        if(i==0 && start_queued_request((unsigned int)tick.sequence))goto timer_done;
        if(i==3) {
            if(state.input_enqueued_event!=3 || state.input_controls || state.input_complete ||
               full_adf_input_pump(&input,1) || state.faults || !input.complete || input.fault || input.request ||
               input.pending || input.registered || input.submitted || input.driver_callback || input.driver_parameter ||
               input.controls!=1 || input.callbacks!=1 || input.readbacks!=1 || state.input_callbacks!=1)goto timer_done;
            state.input_controls=input.controls;state.input_readbacks=input.readbacks;state.input_complete=input.complete;
            state.input_consumed_event=(unsigned int)tick.sequence;
            log_event("FULL_ADF_PROC_INPUT_DRAINED ","generation=1 event=4 priority=2 scheduler_consumed=1 control30_consumed=1 callback_status=0 callbacks=1 control31_parameter=0 control31_callback=0 request=0 pending=0 submitted=0 registered=0 listener_removed=1 complete=1");
            /* The typed driver callback was proved empty by the pump/readback checks above. */
            if(full_adf_glee_input_note_control30(&glee_input,1,input.driver_parameter,0,input.complete))goto timer_done;
            state.cold_control30_notes=glee_input.control30_notes;
            snprintf(line,sizeof line,"generation=1 event=4 same_initialized_owner=1 initializations=%u control30_notes=%u driver_parameter=%u driver_callback_empty=%u actual_readbacks=%u actual_complete=%u input_type=%u input_source=%u input_callback=%u input_kind_cache=%u input_ring=%u power20=%u power21=%u power22=%u power_state=%u control0_calls=%u",
                state.cold_owners_initialized,state.cold_control30_notes,glee_input.driver_parameter,
                (unsigned int)(glee_input.driver_callback==0),input.readbacks,input.complete,glee_input.input_type,
                glee_input.input_source,glee_input.input_callback_field,glee_input.kind_cache,glee_input.ring_count,
                glee_input.power.flag_20,glee_input.power.flag_21,glee_input.power.flag_22,glee_input.power.field_14,
                glee_input.callbacks_started);
            log_event("FULL_ADF_PROC_COLD_INPUT_HISTORY ",line);
        }
        if((i==0 || i==3) && consume_commands((unsigned int)tick.sequence))goto timer_done;
        if(delay.pending) {
            unsigned int saved=delay.saved74,start=delay.start7c;
            int polled=full_adf_delay129_poll(&delay,1,&clock_source);
            state.delay_state=delay.control_state;
            if(polled==FULL_ADF_SOURCE7_PENDING) {
                if(i || tick.cache.counter!=saved || delay.control_state!=1 || !delay.registered || !delay.pending)goto timer_done;
                state.delay_same_tick_waits++;
                log_event("FULL_ADF_PROC_AIP_DELAY_WAIT ","generation=1 event=1 current=1 saved=1 start=1 delay=0 counter_changed=0 control_state=1 registered=1 pending=1 same_pass_start=1");
            } else {
                if(polled || i!=1 || delay.control_state!=2 || delay.pending || delay.registered ||
                   delay.pending_work || delay.saved74 || delay.start7c || delay.delay78)goto timer_done;
                state.delay_completed_event=(unsigned int)tick.sequence;
                snprintf(line,sizeof line,"generation=1 event=%llu current=%u saved=%u start=%u elapsed24=%u delay=0 counter_changed=%u control_state=2 registered=0 pending=0 work=0",
                    (unsigned long long)tick.sequence,tick.cache.counter,saved,start,(tick.cache.counter-start)&0xffffffu,
                    (unsigned int)(tick.cache.counter!=saved));
                log_event("FULL_ADF_PROC_AIP_DELAY ",line);
            }
        }
        if(i<3) {
            if(full_adf_avio_output_consume_vsync(&output,1,tick.sequence) || state.faults)goto timer_done;
            state.avio_stages=output.consumed;
            snprintf(line,sizeof line,"generation=1 event=%llu priority=4 stage=%u consumed=%u remaining=%u output_finished=%u callbacks=%u source_cache=%#x source=%u shadow_writes=%u changed_writes=%u touched_writes=%u requested_mask=%#x current_mask=%#x",
                (unsigned long long)tick.sequence,i,output.consumed,output.count,output.output_finished,
                output.callback_calls,output.source_cache,output.public_source,output.shadow_writes,
                output.changed_writes,output.touched_writes,output.requested_mask,output.current_mask);
            log_event("FULL_ADF_PROC_AVIO_STAGE ",line);
            if(i==2) {
                if(!output.output_finished || state.avio_callbacks!=1)goto timer_done;
                state.idle_stage=5;
                if(full_adf_input_begin(&input,1,input_listener,&state))goto timer_done;
                state.input_enqueued_event=(unsigned int)tick.sequence;
                log_event("FULL_ADF_PROC_INPUT_QUEUED ","generation=1 event=3 after_priority=4 selector=0 input_state=1 parameter=0 priority=2 registered=1 scheduler_consumed=0 next_source5_pass_required=1");
            }
        } else {
            if(output.count || !output.output_finished || output.fault || output.consumed!=3)goto timer_done;
            log_event("FULL_ADF_PROC_AVIO_EMPTY_VISIT ","generation=1 event=4 priority=4 remaining=0 consumed=3 extra_job_consumed=0");
        }
    }
    if(clock_source.events_delivered==4 && !clock_source.armed && delay.control_state==2 && !delay.pending &&
       output.output_finished && !output.fault && !output.count && output.callback_calls==1 && state.avio_callbacks==1 &&
       state.output_requests==1 && !state.avio_pending_mask && state.source5_registered==1 &&
       state.source5_queued==4 && state.source5_consumed==4 && !state.source5_pending &&
       state.input_enqueued_event==3 && state.input_consumed_event==4 && state.input_complete &&
       state.cold_owners_initialized==1 && state.cold_control30_notes==1 &&
       glee_input.control30_notes==1 && !glee_input.fault && !hotshoe_input.fault &&
       !glee_input.callbacks_started && !hotshoe_input.registered &&
       state.global_state==2 && state.idle_stage==7 && state.stop_phase1==1 && state.stop_cleanup_calls==3 &&
       state.start_job_consumed==1 && !state.start_job_registered && !state.queued_config &&
       state.notify2==1 && state.notify0==1 && state.input_pending_at_notify2==1 && state.config_pending_at_notify2==1 &&
       state.af_consumed==1 && state.b0_consumed==1 && state.command_sequence==2 &&
       state.disable_writes==14 && state.disable_readbacks==14 && state.delay_same_tick_waits==1 && state.delay_completed_event==2)
        rc=0;
timer_done:
    if(close(fd))rc=-1021;
    if(rc) {
        full_adf_source7_clock_cancel(&clock_source,1);
        if(delay.pending)full_adf_delay129_cancel(&delay,1);
        return rc;
    }
    if(state.pending_config || state.config_commits!=1 || state.active_path!=state.pending_path ||
       state.active_mode!=state.pending_mode || state.active_format!=state.pending_format ||
       state.active_notify!=state.pending_notify || state.active_path!=state.requested_path ||
       state.output_requests!=1 || state.avio_pending_mask || state.input_enqueued_event!=3 ||
       state.input_consumed_event!=4 || !state.input_complete || state.inner_queued!=1 || state.inner_consumed ||
       inner_completion.live!=1 || inner_completion.source!=0x9058003f || inner_completion.token!=state.pending_token ||
       memcmp(inner_completion.bytes,"\x04\x20\x02\x81\x0c\x00\x01\x00",8))return -1021;
    state.inner_status=u32(inner_completion.bytes+8);state.outer_status=state.inner_status|0x580000u;
    if(state.inner_status || state.outer_status!=0x580000)return -1021;
    inner_completion.live=0;state.inner_consumed++;
    log_event("FULL_ADF_PROC_INNER_RELAY ","generation=1 source=0x9058003f bytes=12 raw=042002810c00010000000000 status=0 token=1 inner_consumed=1 outer_status=0x580000 input_pending=0 pending_config=0");
    state.delay_state=delay.control_state;
    return 0;
}
static void finish(void)
{
    if(state.guard_held) {reservation.release();state.guard_held=0;}
    state.busy=0;state.worker_active=0;
    pthread_mutex_unlock(&mutex);
}
static void pending_fault(int rc,const char *why,void *temporary)
{
    state.faults=1;state.clean_completion=0;
    if(temporary && temporary!=state.retained_request) {
        state.cleanup_free_rc=transport.release(state.reply_owner,temporary);
        if(state.cleanup_free_rc) {state.retained_cleanup=temporary;state.cleanup_owner=state.reply_owner;}
        else state.cleanup_freed++;
    }
    char line[560];
    snprintf(line,sizeof line,"reason=%s rc=%d request=%p request_owner=%#x events=%u applications=%u queued=%u allocate_rc=%d send_rc=%d cleanup_free_rc=%d retained_cleanup=%u reply_queued=%u normal_completion=0 ap_consumed=0 faulted_pending=1",
        why,rc,state.retained_request,state.request_owner,state.events,state.applications,state.queued,
        state.allocate_rc,state.send_rc,state.cleanup_free_rc,(unsigned int)(state.retained_cleanup!=0),state.queued);
    log_event("FULL_ADF_PROC_PENDING ",line);finish();
}
static void *worker(void *unused)
{
    (void)unused;pthread_mutex_lock(&mutex);
    if(!current_process() || !state.busy || state.generation!=1 || !state.retained_request) {
        pending_fault(-1021,"worker-ownership",0);return 0;
    }
    int rc=reservation.reserve();
    if(rc) {pending_fault(rc,"resource-reservation",0);return 0;}
    state.guard_held=1;
    rc=backend();
    if(rc || state.faults) {pending_fault(rc?rc:-1021,"backend-not-complete",0);return 0;}
    state.applications++;
    char line[900];
    snprintf(line,sizeof line,"generation=1 requested_path=%u active_path=%u mode=%u format=%u notify=%u config_commits=%u pending_config=%u global_state=%u idle_stage=%u cold_stop_phase1=%u stop_cleanups=%u start_consumed=%u notification2=%u notification0=%u inner_queued=%u inner_consumed=%u AIP_control_state=%u delay_ready_event=%u events=%u avio_stages=%u avio_callbacks=%u output_requests=%u avio_pending_mask=%u input_complete=%u AF_consumed=%u B0_consumed=%u command_sequence=%u disable_writes=%u common_guard_held=1 inner_request=042002010c00010000000000 inner_completion=042002810c00010000000000 outer_status=%#x",
        state.requested_path,state.active_path,state.active_mode,state.active_format,state.active_notify,
        state.config_commits,state.pending_config,state.global_state,state.idle_stage,state.stop_phase1,state.stop_cleanup_calls,
        state.start_job_consumed,state.notify2,state.notify0,state.inner_queued,state.inner_consumed,
        state.delay_state,state.delay_completed_event,state.events,state.avio_stages,state.avio_callbacks,state.output_requests,
        state.avio_pending_mask,state.input_complete,state.af_consumed,state.b0_consumed,state.command_sequence,state.disable_writes,state.outer_status);
    log_event("FULL_ADF_PROC_APPLIED ",line);
    pthread_mutex_unlock(&mutex);
    void *reply=0;rc=transport.allocate(state.reply_owner,&reply,12,1);
    pthread_mutex_lock(&mutex);state.allocate_rc=rc;
    if(reply==state.retained_request) {pending_fault(-1021,"allocator-returned-original-request",0);return 0;}
    if(rc || !reply || transport.size(reply)!=12 || state.faults) {
        pending_fault(rc?rc:-1021,"reply-allocation-or-state",reply);return 0;
    }
    unsigned char response[12]={0x0d,0x20,0x23,0x13,12,0,1,0x80,0,0,0,0};
    for(unsigned int i=0;i<4;i++)response[8+i]=(unsigned char)(state.outer_status>>(8*i));
    memcpy(reply,response,12);transport.set_source(reply,FULL_ADF_PROC_INPUT);
    if(transport.source(reply)!=FULL_ADF_PROC_INPUT || transport.size(reply)!=12 || memcmp(reply,response,12)) {
        pending_fault(-1021,"reply-readback",reply);return 0;
    }
    state.live_reply=reply;
    rc=transport.send(state.reply_owner,reply);state.send_rc=rc;
    if(rc) {state.live_reply=0;pending_fault(rc,"reply-send",reply);return 0;}
    state.queued++;
    snprintf(line,sizeof line,"generation=1 destination=%#x source=0x92840747 reply=%p bytes=12 raw=0d2023130c00018000005800 events=%u queued=%u",
        state.reply_owner,reply,state.events,state.queued);
    log_event("FULL_ADF_PROC_QUEUED ",line);
    void *request=state.retained_request;
    state.request_free_rc=transport.release(state.request_owner,request);
    if(state.request_free_rc)state.faults=1;
    else {state.retained_request=0;state.request_owner=0;state.request_freed++;}
    state.clean_completion=!state.faults && !state.retained_request;
    snprintf(line,sizeof line,"generation=1 request=%p request_free_rc=%d retained_request=%u clean_completion=%u queued=%u ap_consumed=0 events=%u work_complete=1",
        request,state.request_free_rc,(unsigned int)(state.retained_request!=0),state.clean_completion,state.queued,state.events);
    log_event(state.faults?"FULL_ADF_PROC_FAULT ":"FULL_ADF_PROC_COMMIT ",line);
    finish();return 0;
}
int full_adf_proc_dispatch(unsigned int destination,void *request,const struct full_imaging_io *io,
                            const struct full_adf_proc_guard *guard,int enabled,int *result)
{
    if(enabled!=1 || destination!=FULL_ADF_PROC_INPUT || !request || !io || !result)return 0;
    if(!current_process()) {*result=-1021;return 1;}
    if(!io->size)return 0;
    unsigned int bytes=io->size(request);
    if(bytes<4 || u16(request)!=0x200d || u16((unsigned char *)request+2)!=0x323)return 0;
    if(!io->source || !io->allocate || !io->release || !io->set_source || !io->send ||
       !guard || !guard->reserve || !guard->release || bytes!=12) {*result=-1021;return 1;}
    static const unsigned char expected[12]={0x0d,0x20,0x23,3,12,0,1,0x80,0,0,0,0};
    unsigned char envelope[12];memcpy(envelope,request,sizeof envelope);
    unsigned int caller=io->source(request);
    if(memcmp(envelope,expected,12) || (caller>>28)!=8 || !(caller&0x0fffffff)) {*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    if(state.busy || state.faults || state.requests || state.live_reply || state.retained_request || state.retained_cleanup) {
        pthread_mutex_unlock(&mutex);*result=-1021;return 1;
    }
    transport=*io;reservation=*guard;
    state.configured=1;state.busy=1;state.worker_active=1;state.requests=1;state.generation=1;
    state.retained_request=request;state.request_owner=FULL_ADF_PROC_INPUT;state.reply_owner=caller;
    state.requested_path=envelope[8];
    state.requested_mode=envelope[9];
    state.requested_format=envelope[10];
    state.requested_notify=0;state.queued_config=1;state.pending_config=0;
    char line[320];
    snprintf(line,sizeof line,"generation=1 caller=%#x request=%p bytes=12 raw=0d2023030c00018000000000 request_accepted=1 policy=virtual-source7-control-events-v1 policy_period_ns=1000000 normal_completion=0",
        caller,request);
    log_event("FULL_ADF_PROC_REQUEST ",line);
    pthread_attr_t attr;int rc=pthread_attr_init(&attr);
    if(!rc) {
        rc=pthread_attr_setdetachstate(&attr,PTHREAD_CREATE_DETACHED);
        pthread_t thread;
        if(!rc)rc=pthread_create(&thread,&attr,worker,0);
        pthread_attr_destroy(&attr);
    }
    if(rc) {pending_fault(rc,"worker-create",0);*result=0;return 1;}
    pthread_mutex_unlock(&mutex);*result=0;return 1;
}
int full_adf_proc_release_reply(unsigned int destination,void *pointer,int (*release)(unsigned int,void *),
                                void (*record)(const char *,const char *),int *result)
{
    if(!pointer || !release || !result)return 0;
    if(!current_process()) {*result=-1021;return 1;}
    pthread_mutex_lock(&mutex);
    int kind;unsigned int expected;
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
    char line[360];
    snprintf(line,sizeof line,"generation=%u destination=%#x expected=%#x pointer=%p kind=%s rc=%d faults=%u retained=%u ap_consumed=%u events=%u",
        state.generation,destination,expected,pointer,kind==1?"queued-reply":kind==2?"local-cleanup":"original-request",
        rc,state.faults,(unsigned int)(rc!=0),(unsigned int)(!rc && kind==1),state.events);
    event(record,rc?"FULL_ADF_PROC_FAULT ":kind==1?"FULL_ADF_PROC_REPLY_FREE ":"FULL_ADF_PROC_RECOVERY_FREE ",line);
    pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
int full_adf_proc_claim_input(struct full_adf_proc_input_owners *out)
{
    if(!out || !current_process())return -1021;
    for(unsigned long i=0;i<sizeof *out;i++)if(((unsigned char *)out)[i])return -1021;
    pthread_mutex_lock(&mutex);
    struct full_adf_source7_snapshot cache;
    if(state.input_handoff || state.busy || state.worker_active || state.guard_held || state.faults ||
       state.generation!=1 || state.requests!=1 || state.applications!=1 || state.queued!=1 ||
       state.clean_completion!=1 || state.ap_consumed!=1 || state.retained_request || state.live_reply ||
       state.retained_reply || state.retained_cleanup || state.global_state!=2 || state.config_commits!=1 ||
       state.pending_config || state.active_path || state.active_mode || state.active_format || state.active_notify ||
       state.cold_owners_initialized!=1 || state.cold_control30_notes!=1 || !input.complete || input.fault ||
       input.request || input.pending || input.registered || input.submitted || input.driver_callback || input.driver_parameter ||
       input.controls!=1 || input.readbacks!=1 || glee_input.fault || glee_input.control30_notes!=1 ||
       glee_input.identity!=&glee_input || hotshoe_input.identity!=&hotshoe_input || hotshoe_input.fault ||
       hotshoe_input.registered || hotshoe_input.fifo_count || hotshoe_input.busy || hotshoe_input.current_type ||
       state.monitor_initializations!=1 || state.monitor_prepares!=1 || state.monitor_commits!=1 ||
       hdmi_monitor.fault || hdmi_monitor.pending || hdmi_monitor.configure_count || hdmi_monitor.flag_240 || hdmi_monitor.flag_242 ||
       state.capability_word0!=1 || state.capability_word7 || state.capability_word8!=1 ||
       gates.software_s || gates.software_k ||
       output.fault || !output.output_finished || output.count || output.requested_mask!=8 || state.avio_pending_mask ||
       commands.fault || commands.busy || commands.interpreter_state || commands.sequence!=2 || commands.events!=2 ||
       commands.stateflag!=1 || commands.generation!=1 || commands.af_applied!=1 || commands.b0_applied!=1 ||
       commands.af_event!=1 || commands.b0_event!=4 || commands.dispatch_event!=4 ||
       commands.response.opcode!=0xb0 || commands.response.status || commands.response.sequence!=2 ||
       commands.response.generation!=1 || commands.response.event_sequence!=4 ||
       commands.command_count || commands.cursor || commands.response_pending ||
       clock_source.armed || clock_source.events_delivered!=4 ||
       full_adf_source7_clock_get(&clock_source,1,5,&cache) || cache.counter!=4 || cache.epoch!=4 ||
       delay.fault || delay.control_state!=2 || delay.pending || delay.registered || delay.pending_work ||
       subscription.live || state.source5_pending || state.source5_registered!=1 ||
       state.source5_queued!=4 || state.source5_consumed!=4 || subscription.target!=0x9058003f ||
       subscription.flags!=1 || subscription.source!=5 || subscription.sender!=0x928c0786) {
        pthread_mutex_unlock(&mutex);return -1021;
    }
    for(unsigned long i=0;i<sizeof commands.buffer;i++)if(commands.buffer[i]) {
        pthread_mutex_unlock(&mutex);return -1021;
    }
    state.input_handoff=1;
    *out=(struct full_adf_proc_input_owners){.hotshoe=&hotshoe_input,.glee=&glee_input,
        .output=&output,.monitor=&hdmi_monitor,.disable=&disable_registers,
        .commands=&commands,.clock=&clock_source,.capability_word0=state.capability_word0,
        .capability_word7=state.capability_word7,.capability_word8=state.capability_word8,
        .software_s=gates.software_s,.software_k=gates.software_k,
        .output_target=output.requested_mask,.source5_target=subscription.target,.source5_flags=subscription.flags,
        .source5_software=subscription.source,.source5_sender=subscription.sender};
    pthread_mutex_unlock(&mutex);return 0;
}
void full_adf_proc_snapshot(struct full_adf_proc_snapshot *out)
{
    if(!out)return;
    if(!current_process()) {*out=(struct full_adf_proc_snapshot){.faults=1,.owner_pid=atomic_load(&owner_pid)};return;}
    pthread_mutex_lock(&mutex);*out=state;out->owner_pid=atomic_load(&owner_pid);pthread_mutex_unlock(&mutex);
}
#ifdef FULL_ADF_PROC_TEST
int full_adf_proc_test_reset(void)
{
    pthread_mutex_lock(&mutex);
    if(state.input_handoff || state.busy || state.worker_active || state.live_reply || state.retained_request || state.retained_cleanup) {
        pthread_mutex_unlock(&mutex);return -1021;
    }
    memset(&state,0,sizeof state);memset(&configuration,0,sizeof configuration);memset(&resources,0,sizeof resources);
    memset(&input,0,sizeof input);memset(&hotshoe_input,0,sizeof hotshoe_input);memset(&glee_input,0,sizeof glee_input);
    memset(&coefficients,0,sizeof coefficients);memset(&gates,0,sizeof gates);
    memset(&disable_registers,0,sizeof disable_registers);memset(&commands,0,sizeof commands);
    memset(&hdmi_monitor,0,sizeof hdmi_monitor);memset(&inner_completion,0,sizeof inner_completion);
    memset(&output,0,sizeof output);memset(&clock_source,0,sizeof clock_source);memset(&delay,0,sizeof delay);
    memset(&subscription,0,sizeof subscription);
    event_limit=4;pthread_mutex_unlock(&mutex);return 0;
}
void full_adf_proc_test_event_limit(unsigned int n) {event_limit=n;}
void full_adf_proc_test_seed_path(const char *path) {seed_path=path;}
void full_adf_proc_test_hold_lock(void) {pthread_mutex_lock(&mutex);}
void full_adf_proc_test_drop_lock(void) {pthread_mutex_unlock(&mutex);}
#endif
