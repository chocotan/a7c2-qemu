/* SPDX-License-Identifier: MIT
 * Parent compiles against its patched helper/owner tree. No old main is run. */
#ifndef IDENTITY_HELPERS
#define IDENTITY_HELPERS "test-bb-timecode-control.c"
#endif
#define main identity_preserved_55_cases_not_run
#include IDENTITY_HELPERS
#undef main

struct identity_attempt {
    void *pointer;
    unsigned int destination,source,bytes,actor,free_operation;
    int result,handled;
};
static void *identity_foreign_attempt(void *opaque) {
    struct identity_attempt *a=opaque;a->actor=tid();
    if(a->free_operation) {
        a->handled=full_bb_timecode_control_release_reply(a->destination,a->pointer,history_release,history_record,&a->result);
    } else {
        a->result=full_bb_timecode_control_observe_receive(a->destination,a->pointer,a->source,a->bytes);
    }
    return NULL;
}
static void field(const char *key,const char *expected) {
    const char *p=identity_refused_line;
    while(*p) {
        const char *end=strchr(p,' ');size_t n=end?(size_t)(end-p):strlen(p);
        size_t keylen=strlen(key);
        if(n>keylen && !strncmp(p,key,keylen) && p[keylen]=='=') {
            assert(n==keylen+1+strlen(expected) && !memcmp(p+keylen+1,expected,strlen(expected)));return;
        }
        if(!end)break;
        p=end+1;
    }
    assert(!"missing identity diagnostic field");
}
static void decimal(const char *key,uint64_t value) {
    char text[40];snprintf(text,sizeof text,"%" PRIu64,value);field(key,text);
}
static void hex32(const char *key,unsigned int value) {
    char text[40];snprintf(text,sizeof text,"0x%08x",value);field(key,text);
}
static void pointer_field(const char *key,void *value) {
    char text[40];snprintf(text,sizeof text,"0x%" PRIxPTR,(uintptr_t)value);field(key,text);
}
static void business_unchanged(const struct full_bb_timecode_snapshot *before,const unsigned char old[48],const unsigned char preset[48]) {
    struct full_bb_timecode_snapshot after=snap();unsigned char now[48];
    read_state(now);assert(!memcmp(now,old,48));read_preset_state(now);assert(!memcmp(now,preset,48));
    assert(before->transaction==after.transaction && before->command==after.command && before->source==after.source);
    assert(before->sender_tid==after.sender_tid && before->receiver_tid==after.receiver_tid);
    assert(before->busy==after.busy && before->faults==after.faults && before->guard_held==after.guard_held);
    assert(before->inflight==after.inflight && before->pending_commit==after.pending_commit && before->ap_consumed==after.ap_consumed);
    assert(before->request_freed==after.request_freed && before->reply_received==after.reply_received && before->reply_freed==after.reply_freed);
    assert(before->retained_request==after.retained_request && before->live_reply==after.live_reply);
    assert(before->retained_reply==after.retained_reply && before->retained_cleanup==after.retained_cleanup);
    assert(before->requests==after.requests && before->request_free_count==after.request_free_count && before->reply_free_count==after.reply_free_count);
    assert(before->busy_count==after.busy_count && before->guard_failures==after.guard_failures);
    assert(before->send_rc==after.send_rc && before->request_free_rc==after.request_free_rc && before->reply_free_rc==after.reply_free_rc);
    assert(before->input_fnv==after.input_fnv && before->state_fnv==after.state_fnv && before->reply_fnv==after.reply_fnv);
    assert(!memcmp(before->command_generations,after.command_generations,sizeof after.command_generations));
    assert(!memcmp(before->preset_command_generations,after.preset_command_generations,sizeof after.preset_command_generations));
}
int main(int argc,char **argv) {
    assert(argc==2);test_case=argv[1];
    assert(is("identity-foreign-receive") || is("identity-foreign-free"));
    assert(!full_bb_timecode_control_owner_init());
    /* Two actual owner transactions: p remains retired while q is current. */
    void *p=history_complete(),*q=history_complete();assert(p!=q && !output);
    struct full_bb_timecode_snapshot before=snap();
    assert(before.ap_consumed && before.request_freed && before.reply_freed && before.queued && !before.busy && !before.faults);
    assert(before.generation==2 && before.applications==2 && input_frees==2 && reply_frees==2 && history_has(p) && history_has(q));
    assert(!identity_refused_count && stage_count("COMMIT")==1);
    unsigned char old[48],preset[48];read_state(old);read_preset_state(preset);
    unsigned int slot,previous_slot,free_count=reply_frees,input_count=input_frees,cleanup_count=cleanups;
    unsigned int allocations=allocated,sends=sent,source_reads=request_source_reads,size_reads=reply_size_reads;
    void *current_request,*current_reply;
    pthread_mutex_lock(&mutex);
    slot=retired_index(p);previous_slot=retired_slot;current_request=request_identity;current_reply=reply_identity;
    pthread_mutex_unlock(&mutex);
    assert(slot<RETIRED_REPLY_CAPACITY && current_reply==q);
    struct identity_attempt attempt={.pointer=p,.destination=0x8abc0123u,.source=0x92345678u,.bytes=7,
        .free_operation=is("identity-foreign-free"),.result=123,.handled=0};
    pthread_t worker;assert(!pthread_create(&worker,NULL,identity_foreign_attempt,&attempt));assert(!pthread_join(worker,NULL));
    assert(attempt.actor!=before.sender_tid && attempt.result==-EALREADY);
    assert(attempt.handled==(int)attempt.free_operation);
    assert(identity_refused_count==1 && event_count==9 && stream_count==4 && stage_count("REFUSED")==1);
    assert(!strncmp(events[8],"event=REFUSED ",14) && strstr(events[8]," rc=-114 "));
    unsigned int keys=0;for(const char *pkey=identity_refused_line;*pkey;pkey++)if(*pkey=='=')keys++;
    assert(keys==33);
    field("operation",attempt.free_operation?"free":"receive");decimal("pid",(unsigned int)getpid());
    decimal("tid",attempt.actor);decimal("owner_pid",(unsigned int)before.owner_pid);
    hex32("attempt_destination",attempt.destination);pointer_field("attempt_pointer",p);
    hex32("attempt_source",attempt.free_operation?0:attempt.source);decimal("attempt_bytes",attempt.free_operation?0:attempt.bytes);
    decimal("metadata_known",!attempt.free_operation);decimal("matched_slot",slot);pointer_field("matched_pointer",p);
    decimal("current_transaction",before.transaction);field("current_command","0x0401");
    decimal("current_sender_tid",before.sender_tid);decimal("current_receiver_tid",before.receiver_tid);
    pointer_field("current_request",current_request);pointer_field("current_reply",current_reply);
    pointer_field("current_live",before.live_reply);pointer_field("current_retained_request",before.retained_request);
    pointer_field("current_retained_reply",before.retained_reply);pointer_field("current_cleanup",before.retained_cleanup);
    decimal("current_busy",before.busy);decimal("current_guard_held",before.guard_held);decimal("current_faults",before.faults);
    decimal("current_inflight",before.inflight);decimal("current_pending_commit",before.pending_commit);
    field("rc","-114");decimal("handled",attempt.free_operation);field("real_free_called","0");field("receive_result_overridden","0");
    char digest[40];snprintf(digest,sizeof digest,"%016" PRIx64,fnv(old,48));
    field("state_before_fnv",digest);field("state_after_fnv",digest);field("owner_state_unchanged","1");
    business_unchanged(&before,old,preset);
    assert(reply_frees==free_count && input_frees==input_count && cleanups==cleanup_count && allocated==allocations && sent==sends);
    assert(request_source_reads==source_reads && reply_size_reads==size_reads);
    pthread_mutex_lock(&mutex);
    assert(retired_index(p)==slot && retired_replies[slot]==p && retired_slot==previous_slot);
    assert(request_identity==current_request && reply_identity==current_reply);
    pthread_mutex_unlock(&mutex);
    printf("BB_TIMECODE_IDENTITY_CASE_PASS case=%s capture_verified=0 formal_verified=0\n",test_case);
    return 0;
}
