/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "adf-proc-device.h"
#include "adf-public-config.h"
#include "adf-set-input-cold-owners.h"
#include "adf-aip-commands.h"
#include "adf-source7-clock.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define CALLER 0x81234567u
static const unsigned char raw_request[12]={0x0d,0x20,0x23,3,12,0,1,0x80,0,0,0,0};
static const unsigned char raw_reply[12]={0x0d,0x20,0x23,0x13,12,0,1,0x80,0,0,0x58,0};
struct message { unsigned int bytes,source,owner,released; unsigned char body[12]; };
static struct message request,second,*heap_reply;
static pthread_mutex_t resource_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_t guard_thread;
static pid_t host_pid;
static unsigned int caller=CALLER,held,reserves,guard_releases,size_calls,source_calls,records;
static unsigned int allocations,sends,request_attempts,request_frees,reply_attempts,reply_frees;
static unsigned int events,stages,avio_callbacks,input_queued,input_callbacks,input_drained,applied,queued;
static unsigned int source5_registered,source5_queued,source5_consumed,source5_pending,event_counter;
static unsigned int prelude_applied,cold_stopped,start_pending,prepared,config_committed;
static unsigned int af_queued,b0_queued,af_consumed,b0_consumed,disable_readbacks,delay_waits,delay_ready;
static unsigned int inner_queued,inner_relayed,empty_visits,cold_owners_initialized,cold_control30_notes;
static unsigned int inner_queued_order,config_commit_order,input_drain_order,b0_consumed_order,inner_relay_order;
static unsigned int recovery_events,reply_free_events,nested_rejected,callback_order;
static unsigned int applied_order,queued_order,request_free_order,guard_release_order;
static uint64_t previous_deadline;
static int reserve_error,allocate_error,null_reply,original_reply,reply_bytes=12,source_error;
static int send_error,request_error,reply_error,recurse,error_pointer;
static void *sent_reply;
static char pending[1500];
static struct full_adf_proc_snapshot snapshot(void) {
    struct full_adf_proc_snapshot s;full_adf_proc_snapshot(&s);return s;
}
static void host_callback(void) {assert(getpid()==host_pid);}
static void guarded(void) {
    host_callback();assert(held && pthread_equal(guard_thread,pthread_self()));
    assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);
}
static struct message *meta(void *body) {
    assert(body);struct message *m=(struct message *)((unsigned char *)body-offsetof(struct message,body));
    assert(m==&request || m==&second || m==heap_reply);assert(!m->released);return m;
}
static unsigned int size(void *body) {host_callback();size_calls++;return meta(body)->bytes;}
static unsigned int source(void *body) {host_callback();source_calls++;return meta(body)->source;}
static int reserve(void) {
    host_callback();reserves++;assert(!pthread_mutex_lock(&resource_mutex));
    if(reserve_error) {assert(!pthread_mutex_unlock(&resource_mutex));return reserve_error;}
    assert(!held);held=1;guard_thread=pthread_self();return 0;
}
static void release_guard(void) {
    guarded();held=0;guard_releases++;guard_release_order=++callback_order;
    assert(!pthread_mutex_unlock(&resource_mutex));
}
static const struct full_adf_proc_guard guard={reserve,release_guard};
static int allocate(unsigned int,void **,unsigned int,unsigned int);
static int release(unsigned int owner,void *body) {
    host_callback();struct message *m=meta(body);assert(owner==m->owner);
    if(m==&request) {
        request_attempts++;if(held)guarded();
        if(request_error)return request_error;
        request_frees++;request_free_order=++callback_order;m->released=1;
    } else {
        assert(m==heap_reply);reply_attempts++;if(held)guarded();
        if(reply_error)return reply_error;
        reply_frees++;heap_reply=0;free(m);
    }
    return 0;
}
static void set_source(void *body,unsigned int value) {
    guarded();assert(value==FULL_ADF_PROC_INPUT && meta(body)==heap_reply);
    if(!source_error)meta(body)->source=value;
}
static int send(unsigned int owner,void *body) {
    guarded();assert(owner==caller && source(body)==FULL_ADF_PROC_INPUT && size(body)==12);
    assert(body!=request.body && !memcmp(body,raw_reply,12) && applied==1 && events==4);
    assert(input_drained==1 && !sends);sends++;sent_reply=body;return send_error;
}
static uint64_t field(const char *text,const char *key) {
    const char *p=text;
    while((p=strstr(p,key)) && p!=text && p[-1]!=' ')p++;
    assert(p);p+=strlen(key);char *end;
    unsigned long long value=strtoull(p,&end,0);
    assert(end!=p && (!*end || *end==' '));return (uint64_t)value;
}
static void record(const char *tag,const char *text) {
    host_callback();records++;callback_order++;
    assert(strstr(text,"scope=virtualSource7ControlOnly") && strstr(text,"original_cp_executed=0"));
    assert(strstr(text,"hardware_verified=0") && strstr(text,"native_frequency_verified=0"));
    assert(strstr(text,"original_event_identity_verified=0") && strstr(text,"pcm_verified=0"));
    assert(strstr(text,"frames_verified=0") && strstr(text,"capture_verified=0"));
    if(!strcmp(tag,"FULL_ADF_PROC_OWNERS ")) {
        guarded();assert(!events && field(text,"seed_bytes=")==FULL_ADF_PUBLIC_SEED_BYTES);
        assert(field(text,"cp_pin=")==1 && field(text,"selector=")==0x20 && field(text,"source=")==1);
        assert(field(text,"capability_word0=")==1 && field(text,"capability_word7=")==0 && field(text,"capability_word8=")==1);
        assert(field(text,"init_F=")==0 && field(text,"config_queries=")==4);
    } else if(!strcmp(tag,"FULL_ADF_PROC_COLD_OWNERS ")) {
        guarded();assert(!events && !source5_registered && !cold_owners_initialized && !cold_control30_notes);
        assert(field(text,"initializations=")==1 && field(text,"owned_virtual_constructor=")==1);
        assert(field(text,"hotshoe_type=")==0 && field(text,"hotshoe_busy=")==0 && field(text,"hotshoe_fifo=")==0);
        assert(field(text,"input_type=")==0 && field(text,"input_source=")==1 && field(text,"input_callback=")==0);
        assert(field(text,"input_kind_cache=")==0 && field(text,"input_ring=")==0);
        assert(field(text,"power20=")==0 && field(text,"power21=")==0 && field(text,"power22=")==0);
        assert(field(text,"power_state=")==2 && field(text,"control30_notes=")==0 && field(text,"control0_calls=")==0);
        cold_owners_initialized++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_PRELUDE ")) {
        guarded();assert(cold_owners_initialized==1 && !cold_control30_notes);
        assert(!events && source5_registered==1 && !prelude_applied && !cold_stopped && !af_queued);
        assert(field(text,"owner_requested=")==1 && field(text,"owner_current=")==1);
        assert(field(text,"key=")==0x58007b && field(text,"config_bool=")==1);
        assert(field(text,"control12d_calls=")==0 && field(text,"synchronous_consumption=")==1);prelude_applied++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_COMMAND_QUEUED ")) {
        guarded();assert(field(text,"queued=")==1 && field(text,"consumed=")==0);
        assert(field(text,"canonical_cache_equal=")==1 && field(text,"owned_allocation=")==0);
        if(field(text,"opcode=")==0xaf) {
            assert(!events && prelude_applied==1 && !cold_stopped && !prepared && !af_queued && !af_consumed);
            assert(field(text,"bytes=")==8 && field(text,"routing_pending=")==1);
            assert(strstr(text,"raw=af00000008000000 "));af_queued++;
        } else {
            assert(field(text,"opcode=")==0xb0 && field(text,"event=")==4 && events==4);
            assert(inner_queued==1 && input_callbacks==1 && !config_committed && !input_drained);
            assert(af_consumed==1 && !b0_queued && !b0_consumed);
            assert(field(text,"bytes=")==16 && field(text,"routing_pending=")==0);
            assert(strstr(text,"raw=b0000000100000000000000000000000 "));b0_queued++;
        }
    } else if(!strcmp(tag,"FULL_ADF_PROC_COLD_STOP ")) {
        guarded();assert(!events && prelude_applied==1 && af_queued==1 && !af_consumed && !prepared && !cold_stopped);
        assert(field(text,"old_path=")==0 && field(text,"global_before=")==0 && field(text,"stop_state=")==3);
        assert(field(text,"notification=")==1 && field(text,"global_after=")==4 && field(text,"low_request_bits=")==0);
        assert(field(text,"cleanups=")==3 && field(text,"AIP_cancel_calls=")==0);
        assert(field(text,"AVIO_jobs=")==0 && field(text,"input_jobs=")==0);
        assert(field(text,"queued_config=")==1 && field(text,"start_priority=")==2 && field(text,"start_registered=")==1);
        cold_stopped++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_START_PENDING ")) {
        guarded();assert(!events && cold_stopped==1 && !start_pending && !prepared && !inner_queued);
        assert(field(text,"global_state=")==4 && field(text,"queued_config=")==1);
        assert(field(text,"start_priority=")==2 && field(text,"start_registered=")==1);
        assert(field(text,"no_expiry_no_start=")==1 && field(text,"no_inner_completion=")==1);start_pending++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_CONFIG_COMMIT ")) {
        guarded();assert(events==4 && input_callbacks==1 && inner_queued==1 && b0_queued==1);
        assert(!config_committed && !input_drained && !b0_consumed && !inner_relayed);
        assert(field(text,"event=")==4 && field(text,"notification=")==0 && field(text,"after_notification=")==2);
        assert(field(text,"stage=")==7 && field(text,"global_state=")==2);
        assert(strstr(text,"path=0 mode=0 format=0 notify=0"));
        assert(field(text,"pending_valid=")==0 && field(text,"commits=")==1 && field(text,"input_pending=")==1);
        assert(field(text,"no_stage24_execution=")==1);config_committed++;config_commit_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_PROC_PREPARED ")) {
        guarded();assert(events==1 && source5_consumed==1 && !source5_pending && !prepared && !stages);
        assert(cold_stopped==1 && start_pending==1 && af_queued==1 && !af_consumed && !config_committed);
        assert(field(text,"event=")==1 && field(text,"start_priority=")==2 && field(text,"queued_config=")==0);
        assert(field(text,"pending_config=")==1 && field(text,"global_state=")==1 && field(text,"idle_stage=")==4);
        assert(field(text,"controllers=")==2 && field(text,"stockers=")==5 && field(text,"pins=")==3);
        assert(field(text,"resources_prepared=")==1 && field(text,"coefficients=")==16 && field(text,"coefficient_readbacks=")==16);
        assert(field(text,"gate_writes=")==5 && field(text,"gate_readbacks=")==5 && field(text,"F=")==0);
        assert(field(text,"saved_counter=")==event_counter && event_counter==1);
        assert(strstr(text,"delay_state=1 pending=1 no_new_counter_no_completion=1"));prepared++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_DISABLE_READBACK ")) {
        guarded();unsigned int calls=events==1?1u:2u;
        assert(prepared==1 && field(text,"event=")==events && field(text,"calls=")==calls);
        if(events==1)assert(af_queued==1 && !af_consumed && !stages && !delay_waits);
        else assert(events==4 && input_drained==1 && config_committed==1 && b0_queued==1 && !b0_consumed);
        assert(field(text,"active0400=")==0 && field(text,"software_byte=")==0 && field(text,"completion_byte=")==1);
        assert(field(text,"route8828=")==0 && field(text,"route882c=")==0 && field(text,"route8830=")==0);
        assert(field(text,"route8928=")==0 && field(text,"route892c=")==0 && field(text,"route8930=")==0);
        assert(field(text,"controla000=")==0 && field(text,"writes=")==calls*7 && field(text,"readbacks=")==calls*7);
        assert(disable_readbacks==(calls-1)*7);disable_readbacks=calls*7;
    } else if(!strcmp(tag,"FULL_ADF_PROC_COMMAND_CONSUMED ")) {
        guarded();assert(field(text,"event=")==events && field(text,"priority=")==4);
        assert(field(text,"AF_consumed=")==1 && field(text,"command_count=")==0);
        assert(field(text,"cursor=")==0 && field(text,"response_pending=")==0);
        if(events==1) {
            assert(af_queued==1 && !af_consumed && !b0_queued && disable_readbacks==7);
            assert(field(text,"B0_consumed=")==0 && field(text,"command_sequence=")==1 && field(text,"stateflag=")==0);
            af_consumed++;
        } else {
            assert(events==4 && af_consumed==1 && b0_queued==1 && !b0_consumed && input_drained==1 && disable_readbacks==14);
            assert(field(text,"B0_consumed=")==1 && field(text,"command_sequence=")==2 && field(text,"stateflag=")==1);
            b0_consumed++;b0_consumed_order=callback_order;
        }
        assert(field(text,"disable_writes=")==disable_readbacks && field(text,"disable_readbacks=")==disable_readbacks);
    } else if(!strcmp(tag,"FULL_ADF_PROC_AIP_DELAY_WAIT ")) {
        guarded();assert(events==1 && prepared==1 && af_consumed==1 && !stages && !delay_waits && !delay_ready);
        assert(field(text,"event=")==1 && field(text,"current=")==event_counter && field(text,"saved=")==1);
        assert(field(text,"start=")==1 && field(text,"delay=")==0 && field(text,"counter_changed=")==0);
        assert(field(text,"control_state=")==1 && field(text,"registered=")==1 && field(text,"pending=")==1);
        assert(field(text,"same_pass_start=")==1);delay_waits++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_AIP_DELAY ")) {
        guarded();assert(events==2 && stages==1 && delay_waits==1 && !delay_ready);
        assert(field(text,"event=")==2 && field(text,"counter_changed=")==1);
        assert(field(text,"current=")==event_counter && field(text,"saved=")==1 && field(text,"start=")==1);
        assert(field(text,"elapsed24=")==1 && field(text,"delay=")==0);
        assert(strstr(text,"control_state=2 registered=0 pending=0 work=0"));delay_ready++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_SOURCE5_SUBSCRIBE ")) {
        guarded();assert(!events && !source5_registered);
        assert(field(text,"command=")==1 && field(text,"target=")==0x9058003fu);
        assert(field(text,"flags=")==1 && field(text,"software_source=")==5 && field(text,"registered=")==1);
        assert(strstr(text,"virtual_subscription=1"));source5_registered++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_SOURCE5_QUEUED ")) {
        guarded();assert(source5_registered==1 && !source5_pending && source5_consumed==source5_queued);
        assert(events==source5_queued+1 && field(text,"event=")==events && field(text,"queued=")==events);
        assert(field(text,"sender=")==0x928c0786u && field(text,"target=")==0x9058003fu);
        assert(field(text,"software_source=")==5 && field(text,"counter=")==event_counter);
        assert(field(text,"epoch=")==events && field(text,"pending=")==1);
        assert(strstr(text,"virtual_notification=1") && strstr(text,"original_message_layout_verified=0"));
        source5_queued++;source5_pending=1;
    } else if(!strcmp(tag,"FULL_ADF_PROC_SOURCE5_CONSUMED ")) {
        guarded();assert(source5_pending==1 && source5_queued==events && source5_consumed+1==events);
        assert(field(text,"event=")==events && field(text,"consumed=")==events && field(text,"pending=")==0);
        assert(field(text,"sender=")==0x928c0786u && field(text,"target=")==0x9058003fu);
        assert(field(text,"software_source=")==5 && field(text,"counter=")==event_counter && field(text,"epoch=")==events);
        assert(!input_callbacks && !input_drained);source5_consumed++;source5_pending=0;
    } else if(!strcmp(tag,"FULL_ADF_PROC_EVENT ")) {
        guarded();assert(start_pending==1 && field(text,"event=")==events+1 && field(text,"guest_timerfd_expirations=")==1);
        assert(source5_registered==1 && source5_queued==events && source5_consumed==events && !source5_pending);
        assert(!input_callbacks && !input_drained && !config_committed && !inner_queued);
        if(!events)assert(!prepared && !af_consumed && !delay_waits);
        else assert(prepared==1 && af_consumed==1 && delay_waits==1);
        if(events==3)assert(stages==3 && avio_callbacks==1 && input_queued==1);
        else assert(!input_queued);
        uint64_t deadline=field(text,"deadline_ns="),observed=field(text,"observed_ns=");
        assert(observed>=deadline && (!previous_deadline || deadline>=previous_deadline+1000000));
        assert(field(text,"policy_period_ns=")==1000000 && field(text,"hardware_source=")==7);
        assert(field(text,"software_source=")==5 && field(text,"getter_advances=")==0);
        assert(field(text,"hardware_counter=")==field(text,"cache_counter="));
        assert(field(text,"hardware_counter=")==field(text,"fb_counter="));
        assert(field(text,"hardware_epoch=")==events+1 && field(text,"fb_epoch=")==events+1);
        assert(field(text,"cache_epoch=")==events+1);event_counter=(unsigned int)field(text,"cache_counter=");
        events++;previous_deadline=deadline;
    } else if(!strcmp(tag,"FULL_ADF_PROC_AVIO_STAGE ")) {
        guarded();assert(stages<3 && events==stages+1 && field(text,"stage=")==stages);
        assert(prepared==1 && af_consumed==1 && delay_waits==1 && delay_ready==(events>=2));
        assert(source5_consumed==events && !source5_pending);
        assert(field(text,"event=")==events && field(text,"priority=")==4);
        assert(field(text,"consumed=")==stages+1 && field(text,"remaining=")==2-stages);
        assert(field(text,"callbacks=")== (stages==2?1u:0u));
        assert(field(text,"output_finished=")== (stages==2?1u:0u));stages++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_AVIO_CALLBACK ")) {
        guarded();assert(events==3 && stages==2 && !avio_callbacks);
        assert(strstr(text,"queue_commit_pending=1") && strstr(text,"output_requests=1 avio_pending_mask=0"));
        avio_callbacks++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_INPUT_QUEUED ")) {
        guarded();assert(events==3 && source5_consumed==3 && !source5_pending);
        assert(stages==3 && avio_callbacks==1 && !input_queued && !input_callbacks && !config_committed && !inner_queued);
        assert(field(text,"priority=")==2 && field(text,"after_priority=")==4 && field(text,"registered=")==1);
        assert(strstr(text,"scheduler_consumed=0"));input_queued++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_INPUT_CALLBACK ")) {
        guarded();assert(events==4 && source5_consumed==4 && !source5_pending);
        assert(input_queued==1 && !input_callbacks && !input_drained && !config_committed && !inner_queued && !b0_queued);
        assert(field(text,"control30_consumed=")==1 && field(text,"driver_callback=")==0);
        assert(field(text,"owner_pending=")==1 && field(text,"submitted_callback=")==1);
        assert(field(text,"listener_removed=")==1 && field(text,"drain_pending=")==1);input_callbacks++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_INNER_QUEUED ")) {
        guarded();assert(events==4 && input_callbacks==1 && !input_drained && !inner_queued && !config_committed && !b0_queued);
        assert(field(text,"notification=")==2 && field(text,"source=")==0x9058003fu);
        assert(field(text,"pending_config=")==1 && field(text,"input_pending=")==1 && field(text,"inner_queued=")==1);
        assert(field(text,"bytes=")==12 && field(text,"outer_reply_queued=")==0);
        assert(strstr(text,"raw=042002810c00010000000000 "));inner_queued++;inner_queued_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_PROC_INPUT_DRAINED ")) {
        guarded();assert(events==4 && source5_consumed==4 && input_callbacks==1 && !input_drained);
        assert(config_committed==1 && inner_queued==1 && b0_queued==1 && !b0_consumed && !inner_relayed);
        assert(field(text,"priority=")==2 && field(text,"scheduler_consumed=")==1 && field(text,"callbacks=")==1);
        assert(field(text,"control31_parameter=")==0 && field(text,"control31_callback=")==0);
        assert(field(text,"request=")==0 && field(text,"pending=")==0 && field(text,"submitted=")==0);
        assert(field(text,"registered=")==0 && field(text,"listener_removed=")==1 && field(text,"complete=")==1);
        input_drained++;input_drain_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_PROC_COLD_INPUT_HISTORY ")) {
        guarded();assert(events==4 && input_drained==1 && config_committed==1 && b0_queued==1 && !b0_consumed);
        assert(cold_owners_initialized==1 && !cold_control30_notes);
        assert(field(text,"same_initialized_owner=")==1 && field(text,"initializations=")==1);
        assert(field(text,"control30_notes=")==1 && field(text,"driver_parameter=")==0);
        assert(field(text,"driver_callback_empty=")==1 && field(text,"actual_readbacks=")==1 && field(text,"actual_complete=")==1);
        assert(field(text,"input_type=")==0 && field(text,"input_source=")==1 && field(text,"input_callback=")==0);
        assert(field(text,"input_kind_cache=")==0 && field(text,"input_ring=")==0);
        assert(field(text,"power20=")==0 && field(text,"power21=")==0 && field(text,"power22=")==0);
        assert(field(text,"power_state=")==2 && field(text,"control0_calls=")==0);cold_control30_notes++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_AVIO_EMPTY_VISIT ")) {
        guarded();assert(events==4 && stages==3 && input_drained==1 && b0_consumed==1 && !empty_visits && !inner_relayed);
        assert(field(text,"event=")==4 && field(text,"priority=")==4 && field(text,"remaining=")==0);
        assert(field(text,"consumed=")==3 && field(text,"extra_job_consumed=")==0);empty_visits++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_INNER_RELAY ")) {
        guarded();assert(events==4 && inner_queued==1 && config_committed==1 && input_drained==1 && b0_consumed==1);
        assert(empty_visits==1 && !inner_relayed && !applied && !allocations && !sends);
        assert(field(text,"source=")==0x9058003fu && field(text,"bytes=")==12 && field(text,"status=")==0);
        assert(field(text,"token=")==1 && field(text,"inner_consumed=")==1 && field(text,"outer_status=")==0x580000);
        assert(field(text,"input_pending=")==0 && field(text,"pending_config=")==0);
        assert(strstr(text,"raw=042002810c00010000000000 "));inner_relayed++;inner_relay_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_PROC_APPLIED ")) {
        guarded();assert(events==4 && stages==3 && avio_callbacks==1 && input_drained==1 && !applied);
        assert(config_committed==1 && inner_relayed==1 && b0_consumed==1 && disable_readbacks==14);
        assert(inner_queued_order<config_commit_order && config_commit_order<input_drain_order);
        assert(input_drain_order<b0_consumed_order && b0_consumed_order<inner_relay_order && inner_relay_order<callback_order);
        assert(field(text,"global_state=")==2 && field(text,"idle_stage=")==7);
        assert(field(text,"cold_stop_phase1=")==1 && field(text,"stop_cleanups=")==3 && field(text,"start_consumed=")==1);
        assert(field(text,"notification2=")==1 && field(text,"notification0=")==1);
        assert(field(text,"inner_queued=")==1 && field(text,"inner_consumed=")==1);
        assert(field(text,"config_commits=")==1 && field(text,"pending_config=")==0 && field(text,"delay_ready_event=")==2);
        assert(field(text,"AF_consumed=")==1 && field(text,"B0_consumed=")==1 && field(text,"command_sequence=")==2);
        assert(field(text,"disable_writes=")==14 && field(text,"outer_status=")==0x580000 && field(text,"common_guard_held=")==1);
        applied++;applied_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_PROC_QUEUED ")) {
        guarded();assert(sends==1 && !send_error && !queued && !request_frees);
        assert(strstr(text,"raw=0d2023130c00018000005800"));queued++;queued_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_PROC_COMMIT ")) {
        guarded();assert(queued && request_frees && strstr(text,"ap_consumed=0"));
    } else if(!strcmp(tag,"FULL_ADF_PROC_PENDING ")) {
        assert(strstr(text,"normal_completion=0") && strstr(text,"faulted_pending=1"));
        snprintf(pending,sizeof pending,"%s",text);
    } else if(!strcmp(tag,"FULL_ADF_PROC_REPLY_FREE ")) {
        assert(!held && strstr(text,"kind=queued-reply") && strstr(text,"ap_consumed=1"));reply_free_events++;
    } else if(!strcmp(tag,"FULL_ADF_PROC_RECOVERY_FREE ")) {
        assert(!held && strstr(text,"ap_consumed=0"));recovery_events++;
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count) {
    guarded();assert(owner==caller && bytes==12 && count==1 && applied==1);allocations++;
    struct full_adf_proc_snapshot s=snapshot();assert(s.busy && s.worker_active && s.guard_held && !s.live_reply);
    assert(full_adf_proc_test_reset()==-1021);
    if(recurse) {
        int rc=77;assert(full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,second.body,&io,&guard,1,&rc)==1);
        assert(rc==-1021);nested_rejected++;
    }
    if(original_reply) {*out=request.body;return allocate_error;}
    if(null_reply || (allocate_error && !error_pointer)) {*out=0;return allocate_error;}
    assert(!heap_reply);heap_reply=calloc(1,sizeof *heap_reply);assert(heap_reply);
    heap_reply->bytes=(unsigned int)reply_bytes;heap_reply->owner=owner;*out=heap_reply->body;return allocate_error;
}
static struct full_adf_proc_snapshot wait_finish(void) {
    for(unsigned int i=0;i<1000;i++) {
        struct full_adf_proc_snapshot s=snapshot();
        if(!s.busy) {
            assert(!s.worker_active && !s.guard_held && !held && guard_releases==(reserves && !reserve_error?1u:0u));
            assert(!pthread_mutex_trylock(&resource_mutex));assert(!pthread_mutex_unlock(&resource_mutex));return s;
        }
        const struct timespec pause={0,1000000};assert(!nanosleep(&pause,0));
    }
    assert(!"worker did not finish within bounded wait");return snapshot();
}
static void init_message(struct message *m,unsigned int source_id) {
    memset(m,0,sizeof *m);m->bytes=12;m->source=source_id;m->owner=FULL_ADF_PROC_INPUT;
    memcpy(m->body,raw_request,12);
}
static int dispatch_with(const struct full_imaging_io *transport,const struct full_adf_proc_guard *g) {
    int rc=77;assert(full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,request.body,transport,g,1,&rc)==1);return rc;
}
static uint64_t monotonic_ns(void) {
    struct timespec t;assert(!clock_gettime(CLOCK_MONOTONIC,&t));
    return (uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint64_t)t.tv_nsec;
}
static struct full_adf_proc_snapshot accepted(void) {
    unsigned char before[12];memcpy(before,request.body,12);uint64_t start=monotonic_ns();
    assert(dispatch_with(&io,&guard)==0);struct full_adf_proc_snapshot s=wait_finish();
    assert(monotonic_ns()-start>=(uint64_t)s.events*UINT64_C(1000000));
    assert(!memcmp(before,request.body,12));assert(s.requests==1 && s.generation==1 && s.reply_owner==caller);return s;
}
static int free_owned(unsigned int owner,void *body) {
    int rc=77;assert(full_adf_proc_release_reply(owner,body,release,record,&rc)==1);return rc;
}
static void no_acceptance(void) {
    struct full_adf_proc_snapshot s=snapshot();assert(!s.requests && !s.busy && !s.configured);
    assert(!allocations && !sends && !reserves && !request_attempts && !reply_attempts && !records);
}
static void applied_backend(struct full_adf_proc_snapshot s) {
    assert(s.events==4 && events==4 && s.avio_stages==3 && stages==3);
    assert(s.source5_registered==1 && s.source5_queued==4 && s.source5_consumed==4 && !s.source5_pending);
    assert(source5_registered==1 && source5_queued==4 && source5_consumed==4 && !source5_pending);
    assert(s.pin_immediately==1 && s.capability_word0==1 && !s.init_f && s.output_source==1);
    assert(s.config_fnv==FULL_ADF_PUBLIC_SEED_FNV && s.resource_preparations==1);
    assert(s.prelude_requested==1 && s.prelude_current==1 && s.prelude_config==1 && s.prelude_calls==1);
    assert(prelude_applied==1 && cold_stopped==1 && start_pending==1 && prepared==1 && config_committed==1);
    assert(s.global_state==2 && s.idle_stage==7 && s.stop_phase1==1 && s.stop_cleanup_calls==3);
    assert(!s.queued_config && !s.start_job_registered && s.start_job_consumed==1 && s.notify2==1 && s.notify0==1);
    assert(s.input_pending_at_notify2==1 && s.config_pending_at_notify2==1);
    assert(s.routing_initialized==1 && !s.routing_pending && !s.routing_prepared);
    assert(s.af_queued==1 && s.b0_queued==1 && s.af_consumed==1 && s.b0_consumed==1 && s.command_sequence==2);
    assert(af_queued==1 && b0_queued==1 && af_consumed==1 && b0_consumed==1);
    assert(s.disable_writes==14 && s.disable_readbacks==14 && disable_readbacks==14);
    assert(s.coefficients==16 && s.gate_writes==5 && s.delay_state==2);
    assert(s.delay_same_tick_waits==1 && s.delay_completed_event==2 && delay_waits==1 && delay_ready==1);
    assert(!s.requested_path && !s.requested_mode && !s.requested_format && !s.requested_notify);
    assert(!s.active_path && !s.active_mode && !s.active_format && !s.active_notify);
    assert(!s.pending_path && !s.pending_mode && !s.pending_format && !s.pending_notify && s.pending_token==1);
    assert(!s.pending_config && s.config_commits==1 && s.output_requests==1 && !s.avio_pending_mask);
    assert(s.inner_queued==1 && s.inner_consumed==1 && !s.inner_status && s.outer_status==0x580000);
    assert(inner_queued==1 && inner_relayed==1 && empty_visits==1);
    assert(s.avio_callbacks==1 && avio_callbacks==1 && s.input_controls==1 && s.input_callbacks==1);
    assert(s.input_readbacks==1 && s.input_complete==1 && input_queued==1 && input_drained==1);
    assert(s.input_enqueued_event==3 && s.input_consumed_event==4);
    assert(s.cold_owners_initialized==1 && cold_owners_initialized==1);
    assert(s.cold_control30_notes==1 && cold_control30_notes==1);
    assert(s.hardware_counter==s.cached_counter && s.applications==1 && applied==1);
}
static void pending_request(struct full_adf_proc_snapshot s) {
    assert(s.faults && !s.clean_completion && !s.ap_consumed && !s.queued && !queued);
    assert(s.retained_request==request.body && s.request_owner==FULL_ADF_PROC_INPUT);
    assert(!s.live_reply && !s.retained_reply && !s.request_freed && !s.reply_freed && !request_frees);
    assert(strstr(pending,"faulted_pending=1") && full_adf_proc_test_reset()==-1021);
}
static void recover_all(void) {
    struct full_adf_proc_snapshot s=snapshot();assert(!s.busy);
    unsigned int consumed=s.ap_consumed || s.live_reply!=0;
    if(s.live_reply || s.retained_request || s.retained_cleanup)assert(full_adf_proc_test_reset()==-1021);
    reply_error=request_error=0;
    if(s.live_reply)assert(!free_owned(s.reply_owner,s.live_reply));
    s=snapshot();if(s.retained_cleanup)assert(!free_owned(s.cleanup_owner,s.retained_cleanup));
    s=snapshot();if(s.retained_request)assert(!free_owned(s.request_owner,s.retained_request));
    s=snapshot();assert(!heap_reply && !s.live_reply && !s.retained_reply && !s.retained_request && !s.retained_cleanup);
    assert(s.ap_consumed==consumed && s.reply_freed==consumed && reply_free_events==consumed);
    assert(!full_adf_proc_test_reset());
}
static void invalid_cases(const char *name) {
    if(!strcmp(name,"disabled")) {
        for(int enabled=0;enabled<=2;enabled+=2) {
            int rc=77;assert(!full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,request.body,&io,&guard,enabled,&rc) && rc==77);
        }
    } else if(!strcmp(name,"unrelated")) {
        for(unsigned int i=0;i<7;i++) {
            init_message(&request,caller);unsigned int destination=FULL_ADF_PROC_INPUT;
            if(i==0)destination++;
            if(i==1)request.body[0]=0;
            if(i==2)request.body[2]=0;
            if(i==3)request.body[3]=4;
            if(i==4)request.bytes=3;
            if(i==5)request.bytes=0;
            int rc=77;assert(!full_adf_proc_dispatch(destination,i==6?0:request.body,&io,&guard,1,&rc) && rc==77);
        }
    } else if(!strcmp(name,"invalid-envelope")) {
        for(unsigned int i=4;i<14;i++) {
            init_message(&request,caller);
            if(i<12)request.body[i]^=1;
            else request.bytes=i==12?11:13;
            assert(dispatch_with(&io,&guard)==-1021);
        }
    } else if(!strcmp(name,"invalid-caller")) {
        const unsigned int invalid[]={0,0x80000000,FULL_ADF_PROC_INPUT,0x71234567,0xf1234567};
        for(unsigned int i=0;i<sizeof invalid/sizeof invalid[0];i++) {
            init_message(&request,invalid[i]);assert(dispatch_with(&io,&guard)==-1021);
        }
    } else if(!strcmp(name,"missing-transport")) {
        for(unsigned int i=0;i<8;i++) {
            struct full_imaging_io incomplete=io;
            if(i==0)incomplete.allocate=0;
            if(i==1)incomplete.release=0;
            if(i==2)incomplete.set_source=0;
            if(i==3)incomplete.send=0;
            if(i==4)incomplete.source=0;
            if(i==5)incomplete.size=0;
            int rc=77;
            if(i<5)assert(dispatch_with(&incomplete,&guard)==-1021);
            else assert(!full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,request.body,i==6?0:&incomplete,&guard,1,i==7?0:&rc) && rc==77);
        }
    } else {
        assert(!strcmp(name,"missing-guard"));
        for(unsigned int i=0;i<3;i++) {
            struct full_adf_proc_guard incomplete=guard;
            if(i==1)incomplete.reserve=0;
            if(i==2)incomplete.release=0;
            assert(dispatch_with(&io,i?&incomplete:0)==-1021);
        }
    }
    no_acceptance();
}
static int ready_pipe[2],finish_pipe[2];
static void *hold_lock(void *unused) {
    (void)unused;char byte=1;full_adf_proc_test_hold_lock();
    assert(write(ready_pipe[1],&byte,1)==1 && read(finish_pipe[0],&byte,1)==1);
    full_adf_proc_test_drop_lock();return 0;
}
static void fork_case(int locked) {
    pthread_t holder;char byte=1;
    if(locked) {
        assert(!pipe(ready_pipe) && !pipe(finish_pipe));assert(!pthread_create(&holder,0,hold_lock,0));
        assert(read(ready_pipe[0],&byte,1)==1);
    }
    pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);int rc=77;
        assert(full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,request.body,&io,&guard,1,&rc)==1 && rc==-1021);
        assert(!size_calls && !source_calls && !records && !reserves && !allocations);
        struct full_adf_proc_snapshot s=snapshot();assert(s.faults && s.owner_pid==(int)host_pid && !s.configured);
        assert(full_adf_proc_release_reply(FULL_ADF_PROC_INPUT,request.body,release,record,&rc)==1 && rc==-1021);
        struct full_adf_proc_input_owners owners={0};
        assert(full_adf_proc_claim_input(&owners)==-1021 && !owners.clock);
        assert(!request_attempts && !reply_attempts && full_adf_proc_owner_init()==-1021);_exit(0);
    }
    int status=0;pid_t done=0;
    for(unsigned int i=0;i<3000 && !done;i++) {
        done=waitpid(child,&status,WNOHANG);assert(done>=0);
        if(!done) {const struct timespec pause={0,1000000};assert(!nanosleep(&pause,0));}
    }
    assert(done==child);
    if(locked) {
        assert(write(finish_pipe[1],&byte,1)==1);assert(!pthread_join(holder,0));
        for(unsigned int i=0;i<2;i++) {assert(!close(ready_pipe[i]));assert(!close(finish_pipe[i]));}
    }
    assert(WIFEXITED(status) && WEXITSTATUS(status)==0);no_acceptance();
}
int main(int argc,char **argv) {
    assert(field("after_priority=4 priority=2 registered=1","priority=")==2);
    assert(field("software_source=5 source=1","source=")==1);
    assert(argc==3);host_pid=getpid();assert(!full_adf_proc_owner_init());
    init_message(&request,caller);init_message(&second,caller+91);const char *name=argv[1];
    if(!strncmp(name,"fork-",5)) {
        fork_case(!strcmp(name,"fork-locked"));puts("ADF_PROC_HOST_TEST_PASS: fork rejects before inherited lock and callbacks");return 0;
    }
    assert(!full_adf_proc_test_reset());full_adf_proc_test_seed_path(argv[2]);
    struct full_adf_proc_input_owners early={0},empty=early;
    assert(full_adf_proc_claim_input(0)==-1021);
    assert(full_adf_proc_claim_input(&early)==-1021 && !memcmp(&early,&empty,sizeof early));
    assert(!snapshot().input_handoff);
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"invalid-envelope") ||
       !strcmp(name,"invalid-caller") || !strcmp(name,"missing-transport") || !strcmp(name,"missing-guard")) {
        invalid_cases(name);puts("ADF_PROC_HOST_TEST_PASS: admission refused without acceptance or ownership transfer");return 0;
    }
    if(!strcmp(name,"event0"))full_adf_proc_test_event_limit(0);
    if(!strcmp(name,"event2"))full_adf_proc_test_event_limit(2);
    if(!strcmp(name,"event3"))full_adf_proc_test_event_limit(3);
    if(!strcmp(name,"reservation-refused"))reserve_error=-39;
    if(!strcmp(name,"alloc-rc"))allocate_error=-41;
    if(!strcmp(name,"alloc-rc-pointer")) {allocate_error=-41;error_pointer=1;}
    if(!strcmp(name,"alloc-null"))null_reply=1;
    if(!strcmp(name,"alloc-size"))reply_bytes=13;
    if(!strcmp(name,"alloc-original"))original_reply=1;
    if(!strcmp(name,"set-source"))source_error=1;
    if(!strcmp(name,"send-fail"))send_error=-43;
    if(!strcmp(name,"cleanup-fail")) {send_error=-43;reply_error=-44;}
    if(!strcmp(name,"request-free-fail"))request_error=-45;
    if(!strcmp(name,"recursive"))recurse=1;
    if(!strcmp(name,"dynamic-caller")) {caller=0x8fedcba9u;request.source=caller;}
    struct full_adf_proc_snapshot s=accepted();
    if(!strcmp(name,"event0") || !strcmp(name,"event2") || !strcmp(name,"event3") ||
       !strcmp(name,"reservation-refused") || !strcmp(name,"seed-missing")) {
        pending_request(s);assert(!s.applications && !sends && !allocations && !applied);
        if(!strncmp(name,"event",5)) {
            assert(s.source5_registered==1 && s.source5_queued==s.events && s.source5_consumed==s.events && !s.source5_pending);
            assert(source5_registered==1 && source5_queued==events && source5_consumed==events && !source5_pending);
            assert(s.prelude_requested==1 && s.prelude_current==1 && s.prelude_config==1 && s.prelude_calls==1);
            assert(prelude_applied==1 && cold_stopped==1 && start_pending==1 && s.stop_phase1==1 && s.stop_cleanup_calls==3);
            assert(s.routing_initialized==1 && s.routing_pending==1 && s.routing_prepared==1 && s.af_queued==1 && af_queued==1);
            assert(!s.b0_queued && !s.b0_consumed && !b0_queued && !b0_consumed);
            assert(!s.config_commits && !config_committed && !s.notify2 && !s.notify0);
            assert(!s.inner_queued && !s.inner_consumed && !inner_queued && !inner_relayed && !empty_visits);
            assert(!s.input_controls && !s.input_callbacks && !s.input_readbacks && !s.input_complete);
            assert(!input_callbacks && !input_drained && !s.input_consumed_event);
            assert(s.cold_owners_initialized==1 && cold_owners_initialized==1);
            assert(!s.cold_control30_notes && !cold_control30_notes);
        }
        if(!strcmp(name,"event0")) {
            assert(!s.events && !events && !stages && !input_queued && !s.input_enqueued_event);
            assert(s.global_state==4 && !s.idle_stage && s.queued_config==1 && !s.pending_config);
            assert(s.start_job_registered==1 && !s.start_job_consumed && !prepared);
            assert(!s.resource_preparations && !s.coefficients && !s.gate_writes && !s.delay_state);
            assert(!s.delay_same_tick_waits && !s.delay_completed_event && !delay_waits && !delay_ready);
            assert(!s.af_consumed && !af_consumed && !s.command_sequence && !s.disable_writes && !s.disable_readbacks);
            assert(!disable_readbacks && !s.output_requests && !s.avio_pending_mask);
        }
        if(!strcmp(name,"event2") || !strcmp(name,"event3")) {
            assert(s.global_state==1 && !s.queued_config && s.pending_config==1 && s.pending_token==1);
            assert(!s.start_job_registered && s.start_job_consumed==1 && prepared==1);
            assert(s.resource_preparations==1 && s.coefficients==16 && s.gate_writes==5);
            assert(s.af_consumed==1 && af_consumed==1 && s.command_sequence==1);
            assert(s.disable_writes==7 && s.disable_readbacks==7 && disable_readbacks==7);
            assert(s.delay_state==2 && s.delay_same_tick_waits==1 && s.delay_completed_event==2);
            assert(delay_waits==1 && delay_ready==1 && s.output_requests==1);
        }
        if(!strcmp(name,"event2")) {
            assert(s.events==2 && events==2 && s.avio_stages==2 && stages==2 && s.avio_pending_mask==2);
            assert(s.idle_stage==4 && !s.avio_callbacks && !avio_callbacks && !input_queued && !s.input_enqueued_event);
        }
        if(!strcmp(name,"event3")) {
            assert(s.events==3 && events==3 && s.avio_stages==3 && stages==3 && s.idle_stage==5);
            assert(s.avio_callbacks==1 && avio_callbacks==1 && !s.avio_pending_mask);
            assert(input_queued==1 && s.input_enqueued_event==3);
        }
        if(reserve_error)assert(!guard_releases && !s.events && strstr(pending,"rc=-39"));
        assert(!s.ap_consumed);assert(free_owned(caller,request.body)==-1021 && !request_attempts);
        assert(!free_owned(FULL_ADF_PROC_INPUT,request.body));s=snapshot();
        assert(s.faults && !s.ap_consumed && !s.reply_freed && !reply_free_events && recovery_events==1);
    } else {
        applied_backend(s);assert(guard_releases==1 && applied_order<guard_release_order);
        if(allocate_error || null_reply || reply_bytes!=12 || original_reply || source_error || send_error) {
            pending_request(s);assert(s.allocate_rc==allocate_error && s.send_rc==send_error);
            assert(sends==(send_error?1u:0u) && !s.ap_consumed && !s.request_freed);
            if(original_reply)assert(!reply_attempts && !request_attempts && !s.cleanup_freed);
            if(error_pointer || reply_bytes!=12 || source_error || send_error)assert(reply_attempts==1);
            if(reply_error) {
                assert(s.retained_cleanup==heap_reply->body && s.cleanup_owner==caller && s.cleanup_free_rc==-44);
                reply_error=0;assert(!free_owned(caller,s.retained_cleanup));s=snapshot();
                assert(s.faults && !s.ap_consumed && s.cleanup_freed==1 && !s.retained_cleanup && recovery_events==1);
            } else assert(!s.retained_cleanup && !heap_reply);
        } else {
            assert(sends==1 && queued==1 && s.queued==1 && s.live_reply==sent_reply && !s.ap_consumed);
            assert(!reply_attempts && !s.reply_freed && full_adf_proc_test_reset()==-1021);
            assert(full_adf_proc_claim_input(&early)==-1021 && !memcmp(&early,&empty,sizeof early));
            assert(!snapshot().input_handoff);
            assert(applied_order<queued_order && queued_order<guard_release_order);
            if(request_error) {
                assert(s.faults && !s.clean_completion && s.request_free_rc==-45 && s.retained_request==request.body);
                assert(request_attempts==1 && !request_frees);request_error=0;
                assert(!free_owned(FULL_ADF_PROC_INPUT,request.body));assert(!snapshot().ap_consumed);
            } else {
                assert(!s.faults && s.clean_completion && request_frees==1 && !s.retained_request);
                assert(request_free_order>queued_order && request_free_order<guard_release_order);
            }
            if(recurse)assert(nested_rejected==1 && !second.released);
            if(!strcmp(name,"wrong-owner")) {
                unsigned int before=reply_attempts;assert(free_owned(caller+1,sent_reply)==-1021);
                assert(reply_attempts==before && snapshot().retained_reply==sent_reply && !snapshot().ap_consumed);
            }
            if(!strcmp(name,"reply-free-fail")) {
                reply_error=-46;assert(free_owned(caller,sent_reply)==-46);s=snapshot();
                assert(s.reply_free_rc==-46 && s.retained_reply==sent_reply && s.live_reply==sent_reply && !s.ap_consumed);
                assert(full_adf_proc_test_reset()==-1021);reply_error=0;
            }
            assert(!free_owned(caller,sent_reply));s=snapshot();
            assert(s.ap_consumed==1 && s.reply_freed==1 && reply_frees==1 && reply_free_events==1 && !s.live_reply);
            if(request_attempts>1 || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
            unsigned int before=reply_attempts;int rc=77;
            assert(!full_adf_proc_release_reply(caller,sent_reply,release,record,&rc) && rc==77 && reply_attempts==before);
            assert(full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,second.body,&io,&guard,1,&rc)==1 && rc==-1021);
        }
    }
    if(!strcmp(name,"input-handoff")) {
        struct full_adf_proc_input_owners owners={0},again={0};
        assert(!full_adf_proc_claim_input(&owners));
        assert(owners.hotshoe && owners.hotshoe->identity==owners.hotshoe && !owners.hotshoe->registered);
        assert(owners.glee && owners.glee->identity==owners.glee && owners.glee->control30_notes==1);
        assert(!owners.glee->generation && !owners.glee->callbacks_started && !owners.glee->complete);
        assert(owners.commands && owners.commands->sequence==2 && owners.commands->stateflag==1);
        assert(!owners.commands->cursor && !owners.commands->command_count && !owners.commands->response_pending);
        assert(owners.clock && owners.clock->generation==1 && owners.clock->events_delivered==4 && !owners.clock->armed);
        assert(owners.clock->hardware7.counter==4 && owners.clock->hardware7.epoch==4);
        assert(owners.capability_word0==1 && !owners.capability_word7 && owners.capability_word8==1);
        assert(owners.output_target==8 && owners.source5_target==0x9058003fu && owners.source5_flags==1);
        assert(owners.source5_software==5 && owners.source5_sender==0x928c0786u && snapshot().input_handoff==1);
        assert(full_adf_proc_claim_input(&again)==-1021 && !memcmp(&again,&empty,sizeof again));
        struct full_adf_proc_input_owners before=owners;
        assert(full_adf_proc_claim_input(&owners)==-1021 && !memcmp(&owners,&before,sizeof owners));
        assert(full_adf_proc_test_reset()==-1021 && !heap_reply && !held);
        puts("ADF_PROC_HOST_TEST_PASS: original AP free before same-owner input handoff, no reset or tick");return 0;
    }
    recover_all();assert(!snapshot().requests && !snapshot().faults);
    printf("ADF_PROC_HOST_TEST_PASS: %s; host transport only, no original AP consumption or capture claim\n",name);return 0;
}
