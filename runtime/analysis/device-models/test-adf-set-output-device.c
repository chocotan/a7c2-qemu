/* SPDX-License-Identifier: MIT */
/* Reuse real 0323/0336 prerequisites without changing their test expectations. */
#define main input_prerequisite_main
#include "test-adf-set-input-device.c"
#undef main
#include "adf-set-output-device.h"
#include "adf-set-input-cold-owners.h"
#include "adf-avio-output.h"
#include "adf-hdmi-monitor.h"
#include "adf-aip-disable.h"
#include "adf-source7-clock.h"

static const unsigned char out_wire[26]={0x0d,0x20,0x2d,3,26,0,1,0x80,0,0,1,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0};
static const unsigned char out_response[12]={0x0d,0x20,0x2d,0x13,12,0,1,0x80,0,0,0x58,0};
static const unsigned char out_format[20]={0,0,0,0,1,0,1,1,1,1,0,0,0,0,0,0,0,0,0,0};
struct out_message {
    unsigned int bytes,source,owner,released,attempts,frees;
    size_t capacity;
    unsigned char body[];
};
static struct out_message *out_request,*out_second,*out_reply;
static struct full_adf_proc_input_owners out_refs;
static struct full_adf_avio_snapshot out_shadow;
static struct full_adf_aip_disable_registers out_disable_before;
static unsigned int out_changed_writes,out_touched_writes;
static struct full_adf_hdmi_monitor out_monitor_copy;
static unsigned char out_failure[FULL_ADF_AIP_SNAPSHOT_BYTES],out_ring[9][12];
static unsigned int out_caller=0x812a4b6du,out_sizes,out_sources,out_logs,out_reserves,out_guards;
static unsigned int out_claims,out_claimed,out_allocations,out_sets,out_sends,out_events,out_pending;
static unsigned int out_monitor,out_job,out_disable,out_aip,out_callbacks,out_inner,out_applied,out_queued;
static unsigned int out_order,out_monitor_order,out_job_order,out_event_order,out_disable_order,out_aip_order;
static unsigned int out_callback_order,out_inner_order,out_applied_order,out_send_order,out_queue_order;
static unsigned int out_request_order,out_guard_order,out_reply_logs,out_recovery_logs,out_recursive_checks;
static int out_reserve_error,out_resource_busy,out_alloc_error,out_error_pointer,out_null,out_alias;
static int out_reply_size=12,out_source_error,out_send_error,out_cleanup_error,out_request_error,out_reply_error;
static int out_recursive,out_block,out_unsupported_source,out_copy_owner,out_power,out_command_busy;
static int out_ready[2],out_finish[2];

static struct full_adf_set_output_snapshot out_snapshot(void)
{
    struct full_adf_set_output_snapshot s;full_adf_set_output_snapshot(&s);return s;
}
static struct out_message *out_new(unsigned int bytes,unsigned int owner,unsigned int source_id)
{
    struct out_message *m=calloc(1,sizeof *m+bytes);assert(m);
    m->bytes=bytes;m->capacity=bytes;m->owner=owner;m->source=source_id;
    memset(m->body,0xa5,bytes);return m;
}
static struct out_message *out_meta(void *body)
{
    assert(body);
    struct out_message *m=(struct out_message *)((unsigned char *)body - offsetof(struct out_message,body));
    assert((m==out_request || m==out_second || m==out_reply) && !m->released);return m;
}
static unsigned int out_size(void *body) {host_callback();out_sizes++;return out_meta(body)->bytes;}
static unsigned int out_source(void *body) {host_callback();out_sources++;return out_meta(body)->source;}
static unsigned int out_attempts(void)
{
    return out_request->attempts+out_second->attempts+(out_reply?out_reply->attempts:0);
}
static int out_reserve(void)
{
    host_callback();out_reserves++;
    if(out_reserve_error)return out_reserve_error;
    if(out_resource_busy) {assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);return -EBUSY;}
    return reserve();
}
static void out_release_guard(void)
{
    guarded();out_guards++;out_guard_order=++out_order;release_guard();
}
static const struct full_adf_proc_guard out_guard={out_reserve,out_release_guard};
static int out_release(unsigned int owner,void *body)
{
    host_callback();struct out_message *m=out_meta(body);assert(owner==m->owner);
    if(held)guarded();
    m->attempts++;
    int rc=m==out_request?out_request_error:(held?out_cleanup_error:out_reply_error);
    if(rc)return rc;
    m->released=1;m->frees++;
    if(m==out_request)out_request_order=++out_order;
    return 0;
}
static void out_set_source(void *body,unsigned int value)
{
    guarded();assert(out_meta(body)==out_reply && value==FULL_ADF_SET_OUTPUT_INPUT);
    out_sets++;if(!out_source_error)out_reply->source=value;
}
static void out_preserved_failure(void)
{
    assert(out_refs.commands && !memcmp(out_refs.commands->input.failure_snapshot,out_failure,sizeof out_failure));
    assert(!memcmp(out_refs.commands->input.ring,out_ring,sizeof out_ring));
    assert(out_refs.commands->input.failure_opcode==0xab && out_refs.commands->input.failure_status==1);
    assert(out_refs.commands->input.failure_task_status==0x1004u);
}
/* Transparent linker probe: execute the real irreversible transfer, then inspect
 * its actual owners. Selected negative cases corrupt only this test boundary. */
int __real_full_adf_set_input_claim_output(struct full_adf_proc_input_owners *);
int __wrap_full_adf_set_input_claim_output(struct full_adf_proc_input_owners *out)
{
    guarded();out_claims++;
    int rc=__real_full_adf_set_input_claim_output(out);
    if(rc)return rc;
    out_claimed++;assert(out_claimed==1 && frees[INPUT_REPLY]==1 && snapshot().ap_consumed==1);
    assert(out->output && out->clock && out->monitor && out->disable && out->commands && out->glee);
    out_refs=*out;
    assert(out->output->generation==1 && out->output->read_index==3 && out->output->write_index==3);
    assert(!out->output->count && out->output->consumed==3 && out->output->current_mask==8);
    assert(out->output->output_finished==1 && out->output->shadow_writes==7 && out->output->callback_calls==1);
    out_shadow=out->output->snapshot;
    out_changed_writes=out->output->changed_writes;out_touched_writes=out->output->touched_writes;
    assert(out->clock->generation==2 && out->clock->events_delivered==8 && !out->clock->armed);
    assert(out->clock->hardware7.counter==8 && out->clock->cache5.counter==8 && out->clock->cache5.epoch==8);
    assert(out->monitor->identity==out->monitor && out->monitor->prepare_count==1 && out->monitor->commit_count==1);
    assert(!out->monitor->configure_count && out->monitor->emitted_af==1 && out->monitor->emitted_b0==1);
    assert(out->disable->calls==2 && out->disable->writes==14 && out->disable->readbacks==14);
    out_disable_before=out->disable->registers;
    assert(out->commands->input.ring_read==9 && out->commands->input.ring_write==9);
    assert(out->commands->input.dispatches==4 && out->commands->input.last_event==8);
    memcpy(out_failure,out->commands->input.failure_snapshot,sizeof out_failure);
    memcpy(out_ring,out->commands->input.ring,sizeof out_ring);out_preserved_failure();
    assert(!out->glee->power.flag_20 && !out->glee->power.flag_22 && out->glee->power.field_14==2);
    if(out_unsupported_source)out->source5_software=6;
    if(out_copy_owner) {out_monitor_copy=*out->monitor;out->monitor=&out_monitor_copy;}
    if(out_power)out->glee->power.flag_20=1;
    if(out_command_busy)out->commands->busy=1;
    return 0;
}
static void out_check_shadow(void)
{
    assert(out_refs.output->current_mask==8 && out_refs.output->requested_mask==8);
    assert(out_refs.output->shadow_writes==7 && !memcmp(&out_refs.output->snapshot,&out_shadow,sizeof out_shadow));
    assert(out_refs.output->changed_writes==out_changed_writes && out_refs.output->touched_writes==out_touched_writes);
}
static int out_send(unsigned int owner,void *body)
{
    guarded();assert(out_meta(body)==out_reply && body!=out_request->body);
    assert(owner==out_caller && out_reply->owner==owner && out_reply->bytes==12);
    assert(out_reply->source==0x92840747u && !memcmp(body,out_response,12));
    assert(out_events==1 && out_aip==1 && out_callbacks==1 && out_inner==1 && out_applied==1);
    out_preserved_failure();out_check_shadow();out_sends++;out_send_order=++out_order;return out_send_error;
}
static void out_record(const char *tag,const char *text)
{
    host_callback();out_logs++;out_order++;fprintf(stdout,"%s%s\n",tag,text);
    assert(strstr(text,"scope=virtualOutputConfigurationNoChange") && strstr(text,"original_cp_executed=0"));
    assert(strstr(text,"hardware_verified=0") && strstr(text,"native_frequency_verified=0"));
    assert(strstr(text,"original_event_identity_verified=0") && strstr(text,"pcm_verified=0"));
    assert(strstr(text,"frames_verified=0") && strstr(text,"capture_verified=0"));
    if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_REQUEST ")) {
        assert(field(text,"caller=")==out_caller && field(text,"bytes=")==26);
        assert(strstr(text,"raw=0d202d031a000180000001000101010100000000000000000000"));
        if(out_block) {char b=1;assert(write(out_ready[1],&b,1)==1 && read(out_finish[0],&b,1)==1);}
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_DEPENDENCIES ")) {
        guarded();assert(out_claimed==1 && out_events==0 && field(text,"counter_before=")==8);
        assert(field(text,"epoch_before=")==8 && field(text,"control3_callback=")==0);
        assert(field(text,"control3_mask=")==8 && field(text,"computed_mask=")==8);
        assert(field(text,"system_sound_activity_snapshot_known=")==0 && field(text,"mask_invariant_W0_O8=")==1);
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_MONITOR_COMMAND ")) {
        guarded();assert(out_claimed==1 && !out_events && !out_monitor && field(text,"opcode=")==0xb0);
        assert(field(text,"monitor_generation=")==2 && field(text,"newly_queued=")==1);
        assert(out_refs.commands->command_count==1 && out_refs.commands->output.enqueued==1);
        static const unsigned char b0[16]={0xb0,0,0,0,16,0,0,0,0,0,0,0,0,0,0,0};
        assert(!memcmp(out_refs.commands->buffer+8,b0,16));
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_MONITOR ")) {
        guarded();assert(!out_monitor && !out_job && !out_events);
        assert(out_refs.monitor->generation==2 && out_refs.monitor->config_copies==1);
        assert(out_refs.monitor->config_readbacks==1 && !memcmp(out_refs.monitor->config,out_format,20));
        assert(out_refs.monitor->prepare_count==1 && out_refs.monitor->commit_count==1 && out_refs.monitor->configure_count==1);
        assert(out_refs.monitor->emit_calls==3 && out_refs.monitor->emitted_af==1 && out_refs.monitor->emitted_b0==2);
        out_monitor++;out_monitor_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_AVIO_QUEUED ")) {
        guarded();assert(out_monitor==1 && !out_job && !out_events);
        const struct full_adf_avio_output *o=out_refs.output;
        assert(o->generation==2 && o->read_index==3 && o->write_index==4 && o->count==1 && o->consumed==3);
        assert(o->same.cache_stores==1 && o->same.cache_clears==1 && !o->same.cache_callback);
        assert(o->jobs[3].active==1 && o->jobs[3].change_mask==0 && o->jobs[3].target==8);
        assert(o->jobs[3].original_callback==0x00666f61 && !o->output_finished && o->callback_calls==1);
        assert(!o->pending_events && !o->callback_running);out_check_shadow();
        unsigned int mask=99;full_adf_avio_listener cb=o->listener;
        assert(!full_adf_avio_output_control3(o,&mask,&cb) && mask==8 && !cb);
        out_job++;out_job_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_EVENT ")) {
        guarded();assert(out_job==1 && !out_events && field(text,"generation=")==3 && field(text,"event=")==9);
        assert(field(text,"guest_timerfd_expirations=")==1 && field(text,"hardware_counter=")==9 && field(text,"epoch=")==9);
        uint64_t deadline=field(text,"deadline_ns="),observed=field(text,"observed_ns=");
        assert(observed>=deadline && deadline>=previous_deadline+1000000);
        assert(field(text,"hardware_source=")==7 && field(text,"software_source=")==5);
        assert(field(text,"queued=")==1 && field(text,"consumed=")==1 && field(text,"getter_advances=")==0);
        assert(out_refs.clock->events_delivered==9 && out_refs.clock->generation==3 && !out_refs.clock->armed);
        out_events++;out_event_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_DISABLE_READBACK ")) {
        guarded();assert(out_events==1 && !out_disable && !out_callbacks);
        assert(field(text,"calls=")==3 && field(text,"writes=")==21 && field(text,"readbacks=")==21);
        assert(out_refs.disable->calls==3 && out_refs.disable->writes==21 && out_refs.disable->readbacks==21);
        const struct full_adf_aip_disable_registers *r=&out_refs.disable->registers;
        assert(r->active0400==out_disable_before.active0400 && !r->route8828 && !r->route882c && !r->route8830);
        assert(!r->route8928 && !r->route892c && !r->route8930 && !r->controla000);
        assert(!out_refs.disable->software_byte && out_refs.disable->completion_byte==1);
        out_disable++;out_disable_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_AIP_CONSUMED ")) {
        guarded();assert(out_disable==1 && !out_aip && !out_callbacks);
        assert(field(text,"snapshot_count=")==1 && field(text,"checked=")==1 && field(text,"cursor_words=")==3);
        assert(field(text,"task_rc=")==0 && field(text,"ring_read=")==10 && field(text,"ring_write=")==10);
        assert(out_refs.commands->output.dispatches==1 && out_refs.commands->output.last_event==9);
        assert(out_refs.commands->input.ring_read==10 && out_refs.commands->input.ring_write==10);
        static const unsigned char b0_response[12]={0xb0,0,0,0,12,0,0,0,0,0,0,0};
        assert(!memcmp(out_refs.commands->input.ring[9],b0_response,12));
        assert(!memcmp(out_refs.commands->input.snapshot+8,b0_response,12));
        assert(!memcmp(out_refs.commands->input.snapshot+24,out_failure+24,sizeof out_failure-24));
        assert(!out_refs.commands->command_count && !out_refs.commands->cursor);
        out_preserved_failure();out_aip++;out_aip_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_CALLBACK ")) {
        guarded();assert(out_aip==1 && !out_callbacks && !out_inner);
        const struct full_adf_avio_output *o=out_refs.output;
        assert(o->read_index==4 && o->write_index==4 && !o->count && o->consumed==4);
        assert(o->callback_running==1 && o->callback_calls==2 && !o->output_finished && o->pending_events==1);
        assert(!o->jobs[3].active && !o->same.cache_callback);
        assert(field(text,"controller_callback_slot=")==0 && field(text,"status=")==0);
        out_check_shadow();out_callbacks++;out_callback_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_INNER_RELAY ")) {
        guarded();assert(out_callbacks==1 && !out_inner && !out_applied);
        assert(field(text,"outer_status=")==0x580000 && strstr(text,"raw=042001830c00010000000000"));
        assert(out_refs.output->output_finished==1 && !out_refs.output->pending_events && !out_refs.output->listener);
        out_inner++;out_inner_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_APPLIED ")) {
        guarded();assert(out_inner==1 && !out_applied && !out_allocations);
        assert(field(text,"global_event=")==9 && field(text,"shadow_writes_added=")==0);
        out_applied++;out_applied_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_QUEUED ")) {
        guarded();assert(out_sends==1 && !out_send_error && !out_queued && !out_request->released);
        assert(field(text,"destination=")==out_caller && strstr(text,"raw=0d202d130c00018000005800"));
        out_queued++;out_queue_order=out_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_COMMIT ")) {
        guarded();assert(out_request->released && out_queued==1 && field(text,"clean_completion=")==1);
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_PENDING ")) {
        assert(strstr(text,"faulted_pending=1") && strstr(text,"normal_completion=0") && strstr(text,"ap_consumed=0"));
        out_pending++;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_REPLY_FREE ")) {
        assert(!held && field(text,"ap_consumed=")==1 && strstr(text,"kind=queued-reply"));out_reply_logs++;
    } else if(!strcmp(tag,"FULL_ADF_SET_OUTPUT_RECOVERY_FREE ")) {
        assert(!held && !field(text,"ap_consumed="));out_recovery_logs++;
    } else assert(!strcmp(tag,"FULL_ADF_SET_OUTPUT_FAULT "));
}
static int out_allocate(unsigned int,void **,unsigned int,unsigned int);
static const struct full_imaging_io out_io={out_allocate,out_release,out_set_source,out_send,out_size,out_source,out_record};
static int out_dispatch_with(const struct full_imaging_io *transport,const struct full_adf_proc_guard *g)
{
    int rc=77;assert(full_adf_set_output_dispatch(0x92840747u,out_request->body,transport,g,1,&rc)==1);return rc;
}
static int out_allocate(unsigned int owner,void **pointer,unsigned int bytes,unsigned int count)
{
    guarded();out_allocations++;assert(owner==out_caller && bytes==12 && count==1 && !out_reply);
    struct full_adf_set_output_snapshot s=out_snapshot();
    assert(s.busy && s.worker_active && s.guard_held && s.applications==1 && s.inner_consumed==1);
    assert(s.events==1 && !s.live_reply && !s.queued && !s.ap_consumed);
    if(out_recursive) {
        int rc=77;struct full_adf_set_output_snapshot before=s;
        assert(full_adf_set_output_dispatch(0x92840747u,out_second->body,&out_io,&out_guard,1,&rc)==1 && rc==-1021);
        s=out_snapshot();assert(!memcmp(&s,&before,sizeof s));out_recursive_checks++;
    }
    if(out_alias) {*pointer=out_request->body;return out_alloc_error;}
    if(out_null || (out_alloc_error && !out_error_pointer)) {*pointer=0;return out_alloc_error;}
    out_reply=out_new((unsigned int)out_reply_size,owner,ALLOCATOR_SOURCE);*pointer=out_reply->body;
    return out_alloc_error;
}
static struct full_adf_set_output_snapshot out_wait(void)
{
    for(unsigned int i=0;i<2000;i++) {
        struct full_adf_set_output_snapshot s=out_snapshot();
        if(!s.busy) {assert(!s.worker_active && !s.guard_held && !held);return s;}pause_once();
    }
    assert(!"032d worker did not finish");return out_snapshot();
}
static int out_free(unsigned int owner,void *pointer)
{
    int rc=77;assert(full_adf_set_output_release_reply(owner,pointer,out_release,out_record,&rc)==1);return rc;
}
static void out_wrong_owner(unsigned int owner,void *pointer)
{
    unsigned int attempts=out_attempts(),consumed=out_snapshot().ap_consumed;
    assert(out_free(owner^1u,pointer)==-1021);
    assert(out_attempts()==attempts && out_snapshot().ap_consumed==consumed);
}
static void out_retry_rejected(void)
{
    struct full_adf_set_output_snapshot before=out_snapshot();unsigned int logs=out_logs,attempts=out_attempts();
    int rc=77;
    assert(full_adf_set_output_dispatch(0x92840747u,out_second->body,&out_io,&out_guard,1,&rc)==1 && rc==-1021);
    struct full_adf_set_output_snapshot after=out_snapshot();assert(!memcmp(&before,&after,sizeof before));
    assert(out_logs==logs && out_attempts()==attempts && !out_second->released);
    assert(!full_adf_set_output_owner_init());after=out_snapshot();assert(!memcmp(&before,&after,sizeof before));
}
static void out_recover(void)
{
    struct full_adf_set_output_snapshot s=out_snapshot();assert(!s.busy && !held);
    out_request_error=out_reply_error=out_cleanup_error=0;
    if(s.live_reply)assert(!out_free(s.reply_owner,s.live_reply));
    s=out_snapshot();
    if(s.retained_cleanup) {out_wrong_owner(s.cleanup_owner,s.retained_cleanup);assert(!out_free(s.cleanup_owner,s.retained_cleanup));}
    s=out_snapshot();
    if(s.retained_request) {out_wrong_owner(s.request_owner,s.retained_request);assert(!out_free(s.request_owner,s.retained_request));}
    s=out_snapshot();assert(!s.live_reply && !s.retained_reply && !s.retained_cleanup && !s.retained_request);
    assert(out_request->released && (!out_reply || out_reply->released));
    assert(!pthread_mutex_trylock(&resource_mutex) && !pthread_mutex_unlock(&resource_mutex));
}
static void out_prerequisites(char **argv,int input,int consume)
{
    assert(!full_adf_proc_owner_init() && !full_adf_set_input_owner_init());
    full_adf_proc_test_seed_path(argv[2]);full_adf_set_input_test_seed_path(argv[2]);
    init_message(&old_request,PROC_REQUEST,caller);init_message(&request,INPUT_REQUEST,caller);
    init_message(&second,SECOND_REQUEST,caller+91);prior(1);
    if(!input)return;
    assert(!dispatch_with(&io,&guard));struct full_adf_set_input_snapshot s=wait_finish();applied_backend(s);
    assert(!s.faults && s.clean_completion && s.requests==1 && s.generation==2 && s.applications==1 && s.queued==1);
    assert(s.request_freed==1 && s.live_reply==sent_reply && !s.ap_consumed && reply);
    if(consume) {
        assert(!free_owned(caller,sent_reply));s=snapshot();
        assert(s.ap_consumed==1 && s.reply_freed==1 && !s.live_reply && !s.retained_reply && !reply);
    }
    assert(reserves==2 && guard_releases==2 && old_events==4 && new_events==4 && !held);
}
static void out_no_acceptance(void)
{
    struct full_adf_set_output_snapshot s=out_snapshot();
    assert(!s.requests && !s.configured && !s.busy && !s.faults && !s.ap_consumed);
    assert(!out_logs && !out_reserves && !out_guards && !out_allocations && !out_attempts() && !out_claims);
}
static int out_invalid(const char *name)
{
    if(!strcmp(name,"disabled")) {
        for(int enabled=0;enabled<=2;enabled+=2) {
            int rc=77;assert(!full_adf_set_output_dispatch(0x92840747u,out_request->body,&out_io,&out_guard,enabled,&rc) && rc==77);
        }
        assert(!out_sizes && !out_sources);
    } else if(!strcmp(name,"unrelated")) {
        for(unsigned int i=0;i<8;i++) {
            memcpy(out_request->body,out_wire,26);out_request->bytes=26;
            unsigned int destination=0x92840747u;int rc=77;
            if(i==0)destination++;
            if(i>=1 && i<=4)out_request->body[i-1]^=1;
            if(i==5)out_request->bytes=3;
            if(i==6)out_request->bytes=0;
            assert(!full_adf_set_output_dispatch(destination,i==7?0:out_request->body,&out_io,&out_guard,1,&rc) && rc==77);
        }
    } else if(!strcmp(name,"invalid-envelope")) {
        for(unsigned int i=4;i<26;i++) {
            memcpy(out_request->body,out_wire,26);out_request->body[i]^=0xff;
            assert(out_dispatch_with(&out_io,&out_guard)==-1021);
        }
        memcpy(out_request->body,out_wire,26);
        const unsigned int lengths[]={4,5,8,12,25,27,~0u};
        for(unsigned int i=0;i<sizeof lengths/sizeof *lengths;i++) {
            out_request->bytes=lengths[i];assert(out_dispatch_with(&out_io,&out_guard)==-1021);
        }
    } else if(!strcmp(name,"short-allocation")) {
        free(out_request);out_request=out_new(4,0x92840747u,out_caller);memcpy(out_request->body,out_wire,4);
        assert(out_dispatch_with(&out_io,&out_guard)==-1021);
    } else if(!strcmp(name,"invalid-caller")) {
        const unsigned int invalid[]={0,0x80000000,0x92840747u,0x71234567u,0xf1234567u};
        for(unsigned int i=0;i<sizeof invalid/sizeof *invalid;i++) {
            out_request->source=invalid[i];assert(out_dispatch_with(&out_io,&out_guard)==-1021);
        }
    } else if(!strcmp(name,"missing-transport")) {
        for(unsigned int i=0;i<8;i++) {
            struct full_imaging_io incomplete=out_io;int rc=77;
            if(i==0)incomplete.allocate=0;
            if(i==1)incomplete.release=0;
            if(i==2)incomplete.set_source=0;
            if(i==3)incomplete.send=0;
            if(i==4)incomplete.source=0;
            if(i==5)incomplete.size=0;
            if(i<5)assert(out_dispatch_with(&incomplete,&out_guard)==-1021);
            else assert(!full_adf_set_output_dispatch(0x92840747u,out_request->body,i==6?0:&incomplete,&out_guard,1,i==7?0:&rc) && rc==77);
        }
    } else if(!strcmp(name,"missing-guard")) {
        for(unsigned int i=0;i<3;i++) {
            struct full_adf_proc_guard incomplete=out_guard;
            if(i==1)incomplete.reserve=0;
            if(i==2)incomplete.release=0;
            assert(out_dispatch_with(&out_io,i?&incomplete:0)==-1021);
        }
    } else if(!strcmp(name,"uninitialized"))assert(out_dispatch_with(&out_io,&out_guard)==-1021);
    else return 0;
    out_no_acceptance();return 1;
}
static void *out_blocked_dispatch(void *unused) {(void)unused;assert(!out_dispatch_with(&out_io,&out_guard));return 0;}
static void out_fork(int locked)
{
    pthread_t thread;char b=1;
    if(locked) {
        out_block=1;assert(!pipe(out_ready) && !pipe(out_finish));
        assert(!pthread_create(&thread,0,out_blocked_dispatch,0));assert(read(out_ready[0],&b,1)==1);
    }
    unsigned int sizes=out_sizes,sources=out_sources,logs=out_logs;
    pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);int rc=77;
        assert(full_adf_set_output_dispatch(0x92840747u,out_request->body,&out_io,&out_guard,1,&rc)==1 && rc==-1021);
        struct full_adf_set_output_snapshot s=out_snapshot();assert(s.faults && s.owner_pid==(int)host_pid && !s.configured);
        assert(full_adf_set_output_release_reply(0x92840747u,out_request->body,out_release,out_record,&rc)==1 && rc==-1021);
        assert(full_adf_set_output_owner_init()==-1021 && out_sizes==sizes && out_sources==sources && out_logs==logs);
        assert(!out_reserves && !out_attempts() && !out_allocations && !out_claims);_exit(0);
    }
    int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    if(locked) {
        assert(write(out_finish[1],&b,1)==1 && !pthread_join(thread,0));
        for(unsigned int i=0;i<2;i++) {assert(!close(out_ready[i]) && !close(out_finish[i]));}
        struct full_adf_set_output_snapshot s=out_wait();assert(s.faults && s.retained_request==out_request->body && !s.queued);
        out_retry_rejected();out_recover();
    } else out_no_acceptance();
}
static void out_applied_backend(struct full_adf_set_output_snapshot s)
{
    assert(s.known==1 && s.initialized==1 && s.configured==1 && s.generation==3 && s.requests==1 && s.dependency_claimed==1);
    assert(s.format_copies==1 && s.format_readbacks==1 && !memcmp(s.format,out_format,20));
    assert(s.control3_reads==3 && s.old_mask==8 && s.target_mask==8 && !s.power20 && !s.power22 && !s.system_sound_snapshot_known);
    assert(s.monitor_configures==1 && s.monitor_b0_queued==1 && s.aip_b0_consumed==1);
    assert(s.aip_checked==1 && s.aip_cursor==3 && !s.aip_task_status && s.disable_calls==3 && s.disable_writes==21 && s.disable_readbacks==21);
    assert(s.events==1 && s.hardware_counter==9 && s.hardware_epoch==9 && s.source5_queued==1 && s.source5_consumed==1);
    assert(s.avio_enqueued==1 && s.avio_consumed==1 && s.callbacks==1 && !s.callback_slot && !s.completion_status);
    assert(s.callback_read_index==4 && s.callback_write_index==4 && !s.callback_count);
    assert(s.shadow_writes_before==7 && s.shadow_writes_after==7 && s.inner_queued==1 && s.inner_consumed==1 && s.outer_status==0x580000);
    assert(out_events==1 && out_callbacks==1 && out_disable==1 && out_aip==1 && out_applied==1 && out_claims==1 && out_claimed==1);
    assert(snapshot().output_handoff==1 && out_refs.clock->events_delivered==9 && !out_refs.clock->armed);
    struct full_adf_source7_clock before=*out_refs.clock;
    for(unsigned int i=0;i<3;i++) {
        struct full_adf_source7_snapshot cache;
        assert(!full_adf_source7_clock_get(out_refs.clock,3,5,&cache));
        assert(cache.counter==9 && cache.epoch==9 && cache.phase==before.hardware7.phase);
    }
    assert(!memcmp(&before,out_refs.clock,sizeof before));
    assert(before.hardware7.counter==9 && before.hardware7.epoch==9 && before.published_fb.counter==9 && before.published_fb.epoch==9);
    assert(out_monitor_order<out_job_order && out_job_order<out_event_order && out_event_order<out_disable_order);
    assert(out_disable_order<out_aip_order && out_aip_order<out_callback_order && out_callback_order<out_inner_order);
    assert(out_inner_order<out_applied_order);out_preserved_failure();out_check_shadow();
    assert(out_refs.commands->output.snapshot_count==1 && out_refs.commands->output.checked==1 && out_refs.commands->output.local_cursor==3);
    assert(!out_refs.commands->output.task_status && !out_refs.commands->input.task_status);
    assert(out_refs.commands->input.failure_task_status==0x1004u);
}
#ifndef FULL_ADF_OUTPUT_TEST_MAIN
#define FULL_ADF_OUTPUT_TEST_MAIN main
#endif
int FULL_ADF_OUTPUT_TEST_MAIN(int argc,char **argv)
{
    assert(argc==3);assert(!setvbuf(stdout,0,_IONBF,0));alarm(8);host_pid=getpid();const char *name=argv[1];
    if(!strcmp(name,"dynamic-caller"))out_caller=0x8edc3179u;
    out_request=out_new(26,0x92840747u,out_caller);memcpy(out_request->body,out_wire,26);
    out_second=out_new(26,0x92840747u,out_caller^0x123u);memcpy(out_second->body,out_wire,26);
    if(strcmp(name,"uninitialized"))assert(!full_adf_set_output_owner_init());
    if(out_invalid(name))goto done;
    if(!strncmp(name,"fork-",5)) {out_fork(!strcmp(name,"fork-locked"));goto done;}
    if(strcmp(name,"no-prior"))out_prerequisites(argv,strcmp(name,"no-input")!=0,strcmp(name,"early-1336-free")!=0);
    if(!strcmp(name,"nonempty-handoff")) {
        struct full_adf_proc_input_owners invalid;memset(&invalid,0xa5,sizeof invalid);
        struct full_adf_proc_input_owners before=invalid;struct full_adf_set_input_snapshot s=snapshot();
        assert(__real_full_adf_set_input_claim_output(&invalid)==-1021 && !memcmp(&invalid,&before,sizeof invalid));
        assert(__real_full_adf_set_input_claim_output(0)==-1021);
        struct full_adf_set_input_snapshot after=snapshot();assert(!memcmp(&after,&s,sizeof s));
    }
    if(!strcmp(name,"reservation-refused"))out_reserve_error=-39;
    if(!strcmp(name,"resource-busy")) {out_resource_busy=1;assert(!pthread_mutex_lock(&resource_mutex));}
    if(!strcmp(name,"event0"))full_adf_set_output_test_event_limit(0);
    if(!strcmp(name,"unsupported-source"))out_unsupported_source=1;
    if(!strcmp(name,"copied-monitor"))out_copy_owner=1;
    if(!strcmp(name,"power-active"))out_power=1;
    if(!strcmp(name,"commands-busy"))out_command_busy=1;
    if(!strcmp(name,"alloc-rc"))out_alloc_error=-41;
    if(!strcmp(name,"alloc-rc-pointer")) {out_alloc_error=-41;out_error_pointer=1;}
    if(!strcmp(name,"alloc-rc-cleanup-fail")) {out_alloc_error=-41;out_error_pointer=1;out_cleanup_error=-44;}
    if(!strcmp(name,"alloc-null"))out_null=1;
    if(!strcmp(name,"alloc-size"))out_reply_size=13;
    if(!strcmp(name,"alloc-small"))out_reply_size=11;
    if(!strcmp(name,"alloc-original"))out_alias=1;
    if(!strcmp(name,"set-source"))out_source_error=1;
    if(!strcmp(name,"send-fail"))out_send_error=-43;
    if(!strcmp(name,"cleanup-fail")) {out_send_error=-43;out_cleanup_error=-44;}
    if(!strcmp(name,"request-free-fail"))out_request_error=-45;
    if(!strcmp(name,"recursive"))out_recursive=1;
    assert(!out_dispatch_with(&out_io,&out_guard));struct full_adf_set_output_snapshot s=out_wait();
    if(out_resource_busy)assert(!pthread_mutex_unlock(&resource_mutex));
    assert(s.requests==1 && s.generation==3 && s.reply_owner==out_caller && !s.ap_consumed);
    assert(!memcmp(out_request->body,out_wire,26) && out_reserves==1);
    assert(out_guards==(out_reserve_error || out_resource_busy?0u:1u));
    if(s.applications)out_applied_backend(s);
    if(!s.queued) {
        assert(s.faults && !s.clean_completion && s.retained_request==out_request->body && !s.live_reply && !s.request_freed);
        assert(out_pending==1 && !s.reply_freed && !s.ap_consumed && !out_request->attempts);
        if(!s.applications)assert(!out_allocations && !out_sends && !out_callbacks && !s.inner_consumed);
        else assert(out_allocations==1 && s.allocate_rc==out_alloc_error && s.send_rc==out_send_error);
        if(!strcmp(name,"no-prior") || !strcmp(name,"no-input") || !strcmp(name,"early-1336-free"))
            assert(!s.dependency_claimed && !s.events && !s.avio_enqueued && !out_claimed);
        if(!strcmp(name,"event0")) {
            assert(s.dependency_claimed==1 && !s.events && s.avio_enqueued==1 && !s.avio_consumed && !s.callbacks && s.callback_slot==1);
            assert(!s.source5_queued && !s.source5_consumed && !s.aip_b0_consumed);
            assert(out_refs.clock->events_delivered==8 && out_refs.clock->fault && !out_refs.clock->armed);
            assert(out_refs.output->read_index==3 && out_refs.output->write_index==4 && out_refs.output->count==1);
            assert(out_refs.commands->command_count==1 && !out_refs.commands->output.dispatches && out_refs.disable->readbacks==14);
            out_check_shadow();out_preserved_failure();
        }
        if(out_reserve_error || out_resource_busy)assert(!out_claims && !s.dependency_claimed && !s.events);
        if(out_unsupported_source) {
            assert(s.dependency_claimed==1 && s.avio_enqueued==1 && !s.events && !s.source5_queued && !s.source5_consumed);
            assert(out_refs.clock->events_delivered==9 && out_refs.clock->hardware7.counter==9 && !out_refs.clock->armed);
            assert(out_refs.output->read_index==3 && out_refs.output->write_index==4 && out_refs.output->count==1);
            assert(out_refs.commands->command_count==1 && !out_refs.commands->output.dispatches && out_refs.disable->readbacks==14);
            out_check_shadow();out_preserved_failure();
        }
        if(out_copy_owner) {
            assert(s.dependency_claimed==1 && !s.events && !s.monitor_configures && !s.avio_enqueued);
            assert(out_monitor_copy.identity==out_refs.monitor && out_monitor_copy.fault && out_monitor_copy.pending);
            assert(!out_refs.monitor->fault && !out_refs.monitor->configure_count && out_refs.clock->events_delivered==8);
            assert(!out_refs.commands->command_count && out_refs.disable->readbacks==14);
        }
        if(out_power) {
            assert(s.dependency_claimed==1 && s.control3_reads==1 && s.power20==1 && !s.power22);
            assert(!s.events && !s.monitor_configures && !s.avio_enqueued && out_refs.glee->power.flag_20==1);
            assert(out_refs.clock->events_delivered==8 && out_refs.disable->readbacks==14);
        }
        if(out_command_busy) {
            assert(s.dependency_claimed==1 && !s.events && !s.monitor_configures && !s.avio_enqueued);
            assert(out_refs.commands->busy && out_refs.commands->fault && !out_refs.commands->command_count);
            assert(out_refs.clock->events_delivered==8 && out_refs.disable->readbacks==14);
        }
        if(out_alias)assert(!out_attempts() && !s.cleanup_freed && !s.retained_cleanup);
        if(out_cleanup_error)assert(out_reply && s.retained_cleanup==out_reply->body && s.cleanup_owner==out_caller && s.cleanup_free_rc==-44);
        else if(out_reply)assert(out_reply->released && s.cleanup_freed==1 && !s.retained_cleanup);
    } else {
        out_applied_backend(s);assert(s.applications==1 && out_sends==1 && out_queued==1 && out_reply && s.live_reply==out_reply->body);
        assert(!memcmp(out_reply->body,out_response,12) && out_reply->body!=out_request->body && out_sets==1);
        assert(out_applied_order<out_send_order && out_send_order<out_queue_order && out_queue_order<out_guard_order);
        if(out_request_error) {
            assert(s.faults && !s.clean_completion && s.retained_request==out_request->body && s.request_free_rc==-45);
            assert(out_request->attempts==1 && !out_request->frees);
        } else {
            assert(!s.faults && s.clean_completion==1 && s.request_freed==1 && !s.retained_request);
            assert(out_queue_order<out_request_order && out_request_order<out_guard_order);
        }
        if(out_recursive)assert(out_recursive_checks==1 && !out_second->released);
        out_retry_rejected();
        if(!strcmp(name,"release-pass-through")) {
            int rc=77;unsigned int attempts=out_attempts();
            assert(!full_adf_set_output_release_reply(out_caller,0,out_release,out_record,&rc) && rc==77);
            assert(!full_adf_set_output_release_reply(out_caller,out_reply->body,0,out_record,&rc) && rc==77);
            assert(!full_adf_set_output_release_reply(out_caller,out_reply->body,out_release,out_record,0));
            assert(!full_adf_set_output_release_reply(out_caller,out_second->body,out_release,out_record,&rc) && rc==77);
            assert(out_attempts()==attempts && !out_snapshot().ap_consumed);
        }
        if(!strcmp(name,"wrong-owner"))out_wrong_owner(out_caller,out_reply->body);
        if(!strcmp(name,"reply-free-fail")) {
            out_reply_error=-46;assert(out_free(out_caller,out_reply->body)==-46);s=out_snapshot();
            assert(s.faults && !s.clean_completion && !s.ap_consumed && s.live_reply==out_reply->body && s.retained_reply==out_reply->body);
            assert(s.reply_free_rc==-46 && !s.reply_freed && !out_reply->frees);out_retry_rejected();out_reply_error=0;
        }
        assert(!out_free(out_caller,out_reply->body));s=out_snapshot();
        assert(s.ap_consumed==1 && s.reply_freed==1 && !s.live_reply && !s.retained_reply && out_reply_logs==1 && out_reply->frees==1);
        if(out_request_error || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        int rc=77;unsigned int attempts=out_attempts();
        assert(!full_adf_set_output_release_reply(out_caller,out_reply->body,out_release,out_record,&rc) && rc==77 && out_attempts()==attempts);
    }
    out_retry_rejected();unsigned int was_faulted=out_snapshot().faults;out_recover();s=out_snapshot();
    if(was_faulted)assert(s.faults && !s.clean_completion);
    else assert(s.clean_completion==1 && !s.faults && s.ap_consumed==1);
    if(reply) {assert(!free_owned(caller,reply->body));assert(!reply);}
    if(out_claimed) {
        struct full_adf_proc_input_owners empty={0};assert(__real_full_adf_set_input_claim_output(&empty)==-1021);
        assert(snapshot().output_handoff==1);out_preserved_failure();
    }
    out_retry_rejected();
done:
    free(out_request);free(out_second);free(out_reply);
    printf("ADF_SET_OUTPUT_HOST_TEST_PASS: %s; host Linux timer/transport only, no original AP, VM, PCM or capture claim\n",name);
    return 0;
}
