/* SPDX-License-Identifier: MIT
 * Only new preset cases run; the unchanged legacy source supplies existing
 * helpers and assertions without a generated test-time copy. */
#define main preserved_55_cases_not_run
#include "test-bb-timecode-control.c"
#undef main
#include <stddef.h>

static unsigned int request_bytes,unique_pool,inline_reply,new_events,new_streams,old_events,old_streams;
static unsigned int inject_stage,pre_ready_calls;
static unsigned char full_input[12];
static void *tight_input;
static unsigned int tight_size;
static const struct full_imaging_io preset_io;
static const struct full_bb_timecode_guard preset_guard;
static int preset_dispatch(void);
static void preset_prepare(unsigned int,unsigned int,unsigned int);
static void preset_consume(void);
static void reset_logs(void) {event_count=stream_count=new_events=new_streams=old_events=old_streams=0;}
static unsigned int key_count(const char *line) {
    unsigned int n=0;for(;*line;line++)if(*line=='=')n++;return n;
}
static void preset_record(const char *tag,const char *line) {
    if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_IDENTITY_REFUSED ")){io_record(tag,line);return;}
    struct full_bb_timecode_snapshot s=snap();
    if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_PRESET_EVENT ")) {
        assert(preset_command(s.command) && key_count(line)==66);
        assert(strstr(line," preset_known_mask=") && strstr(line," preset_raw4=0x") && strstr(line," ubmode_wire="));
        assert(strstr(line," tcmode=") && strstr(line," dfmode=") && strstr(line," run="));
        const char *hex=strstr(line," preset_raw4=0x")+strlen(" preset_raw4=0x");assert(strspn(hex,"0123456789abcdef")==8 && hex[8]==' ');
        new_events++;
        if(!strncmp(line,"event=BEGIN ",12) || !strncmp(line,"event=STATE_WRITTEN ",20)) {
            char pending[64];snprintf(pending,sizeof pending," result=%d ",-EINPROGRESS);assert(strstr(line,pending));
        }
        if(!strncmp(line,"event=STATE_WRITTEN ",20)) {
            assert(output && get32(output->data+8)==(uint32_t)-EINPROGRESS);
            if(inject_stage) {
                pthread_mutex_lock(&mutex);
                if(inject_stage==1)state.preset_raw4^=UINT32_C(0x80000000);
                if(inject_stage==2)state.ubmode_wire^=1;
                if(inject_stage==3)state.preset_command_generations[1]++;
                pthread_mutex_unlock(&mutex);
            }
        }
        io_record("FUNCTIONAL_BB_TIMECODE_EVENT ",line);
    } else if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_PRESET_BYTES ")) {
        assert(preset_command(s.command) && key_count(line)==16);new_streams++;
        io_record("FUNCTIONAL_BB_TIMECODE_BYTES ",line);
    } else {
        assert(!preset_command(s.command));
        if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_EVENT ")) {
            old_events++;assert(key_count(line)==59 && strstr(line," known_mask=") && !strstr(line," preset_known_mask="));
        } else {assert(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_BYTES "));old_streams++;assert(key_count(line)==16);}
        io_record(tag,line);
    }
}
static unsigned int preset_size(void *p) {if(p==tight_input)return tight_size;return io_size(p);}
static unsigned int preset_source(void *p) {
    if(p==tight_input)return 0x80000001u;
    if(p==input.data && is("preset-source-drift") && ++request_source_reads>1)return input.source+1;
    return io_source(p);
}
static int preset_allocate(unsigned int destination,void **p,unsigned int bytes,unsigned int count) {
    if(is("preset-request-alias")){callback_snapshot();allocated++;*p=input.data+alias_offset;return 0;}
    if(is("preset-allocation-null")){callback_snapshot();allocated++;return 0;}
    if(!unique_pool)history_reuse=3;
    int rc=history_allocate(destination,p,bytes,count);
    if(is("preset-allocation-error") || is("preset-cleanup-fail"))rc=-31;
    if(is("preset-allocation-short"))output->size=11;
    return rc;
}
static int preset_release(unsigned int destination,void *p) {
    if(p==input.data) {
        assert(input.size==request_bytes && !memcmp(input.data,full_input,request_bytes));
        if(is("preset-request-free-fail")){callback_snapshot();input_frees++;return -41;}
        return io_release(destination,p);
    }
    return history_release(destination,p);
}
static int preset_send(unsigned int destination,void *p) {
    assert(!io_send(destination,p));
    if(inline_reply) {
        assert(full_bb_timecode_control_observe_receive(destination,p,FULL_BB_TIMECODE_CONTROL_CP,12)==1);
        int rc=123;
        assert(full_bb_timecode_control_release_reply(destination,p,preset_release,preset_record,&rc)==1);
        assert(rc==history_release_rc);
        struct full_bb_timecode_snapshot s=snap();
        assert(s.busy && s.inflight && !s.ap_consumed);
        if(!rc)assert(s.reply_freed && s.pending_commit && !s.live_reply);
    }
    return is("preset-send-fail") || is("preset-inline-send-fail")?-33:0;
}
static int preset_ready(void) {
    pre_ready_calls++;
    if(is("preset-guard-second") && pre_ready_calls==2)return -62;
    return history_ready();
}
static void preset_guard_release(void) {
    guard_release();
    if(inline_reply) {
        assert(snap().guard_held && snap().inflight && !snap().ap_consumed);
        history_busy_observation(last_reply);
    }
}
static const struct full_imaging_io preset_io={preset_allocate,preset_release,io_set_source,preset_send,preset_size,preset_source,preset_record};
static const struct full_bb_timecode_guard preset_guard={history_reserve,preset_guard_release,preset_ready};
static void preset_prepare(unsigned int command,unsigned int payload,unsigned int source) {
    reset_logs();prepare(command,payload&255u,source);
    request_bytes=command==0x040a?12:10;input.size=request_bytes;input.data[4]=(unsigned char)request_bytes;
    if(command==0x040a)put32(input.data+8,payload);else {input.data[8]=(unsigned char)payload;input.data[9]=(unsigned char)(payload>>8);}
    memcpy(original_input,input.data,10);memcpy(full_input,input.data,request_bytes);
    pre_ready_calls=0;
}
static int preset_dispatch(void) {
    int rc=123;
    assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&preset_io,&preset_guard,1,&rc)==1);
    return rc;
}
static void preset_duplicate(void *p) {
    unsigned int frees=reply_frees,cleanup=cleanups;int rc=123;
    assert(full_bb_timecode_control_release_reply(input.source,p,preset_release,preset_record,&rc)==1 && rc==-EALREADY);
    assert(reply_frees==frees && cleanups==cleanup);
}
static void preset_consume(void) {
    struct full_bb_timecode_snapshot s=snap();assert(output && !s.guard_held && s.queued && !s.ap_consumed);
    assert(full_bb_timecode_control_observe_receive(s.source,last_reply,output->source,12)==1);
    int rc=123;assert(full_bb_timecode_control_release_reply(s.source,last_reply,preset_release,preset_record,&rc)==1 && !rc);
}
static void complete(unsigned int command,unsigned int payload,unsigned int source) {
    preset_prepare(command,payload,source);assert(!preset_dispatch());
    if(!inline_reply)preset_consume();
    struct full_bb_timecode_snapshot s=snap();
    assert(!s.busy && !s.faults && !s.guard_held && !s.inflight && !s.pending_commit && s.ap_consumed);
    assert(s.request_freed && s.reply_freed && s.reply_received && !s.send_rc && !s.request_free_rc && !s.reply_free_rc);
}
static void tc_bootstrap(unsigned int count) {
    const char *saved=test_case;test_case="preset-bootstrap";unique_pool=1;
    const unsigned int commands[]={0x0401,0x0402,0x0400};
    for(unsigned int i=0;i<count;i++)complete(commands[i],i&1u,0x81234567u+i);
    unique_pool=0;test_case=saved;
}
static void no_mutation(int expected) {
    struct full_bb_timecode_snapshot before=snap();unsigned int a=allocated,r=reserves,f=input_frees;
    assert(preset_dispatch()==expected && input.alive && !output);
    struct full_bb_timecode_snapshot after=snap();
    assert(!memcmp(&before,&after,sizeof before) && allocated==a && reserves==r && input_frees==f);
}
static void check_state(uint32_t raw,unsigned int selector,unsigned int known,uint64_t generation,uint64_t g0,uint64_t g1) {
    unsigned char bytes[48];read_preset_state(bytes);struct full_bb_timecode_snapshot s=snap();
    assert(get32(bytes)==1 && get32(bytes+4)==48 && get32(bytes+8)==(unsigned int)getpid());
    assert(get32(bytes+12)==known && get64(bytes+16)==generation && get32(bytes+24)==raw && get32(bytes+28)==selector);
    assert(!get32(bytes+32) && !get32(bytes+36) && get64(bytes+40)==generation);
    assert(s.preset_command_generations[0]==g0 && s.preset_command_generations[1]==g1);
}
static void old_state_unchanged(const unsigned char before[48],const uint64_t generations[3]) {
    unsigned char now[48];read_state(now);assert(!memcmp(now,before,48) && !get32(now+36));
    struct full_bb_timecode_snapshot s=snap();assert(s.known_mask==7 && s.generation==3 && s.applications==3);
    assert(!memcmp(s.command_generations,generations,sizeof s.command_generations));
}
static void new_order(unsigned int inline_send) {
    const char *normal[]={"BEGIN","STATE_WRITTEN","STATE_READBACK","REQUEST_FREE","REPLY_QUEUED","RECEIVE","REPLY_FREE","COMMIT"};
    const char *early[]={"BEGIN","STATE_WRITTEN","STATE_READBACK","REQUEST_FREE","RECEIVE","REPLY_FREE","REPLY_QUEUED","COMMIT"};
    assert(new_events==8 && new_streams==4 && !old_events && !old_streams && event_count==8);
    for(unsigned int i=0;i<8;i++) {
        const char *stage=inline_send?early[i]:normal[i];size_t n=strlen(stage);
        assert(!strncmp(events[i]+6,stage,n) && events[i][6+n]==' ');
    }
    char request_shape[64];snprintf(request_shape,sizeof request_shape,"kind=request total=%u offset=0 bytes=%u raw=",request_bytes,request_bytes);
    assert(strstr(streams[0],request_shape));assert(strstr(streams[3],"kind=reply total=12 offset=0 bytes=12 raw="));
    for(unsigned int i=0;i<4;i++) {
        const char *raw=strstr(streams[i]," raw=");assert(raw);raw+=5;
        unsigned int n=i==0?request_bytes:i==3?12:48;unsigned char bytes[48];
        for(unsigned int j=0;j<n;j++){unsigned int v;assert(sscanf(raw+2*j,"%2x",&v)==1);bytes[j]=(unsigned char)v;}
        assert(raw[2*n]==' ');
        if(!i)assert(!memcmp(bytes,full_input,n));
        if(i==3)assert(!memcmp(bytes,expected_reply,12) && !get32(bytes+8));
        char fingerprint[64];snprintf(fingerprint,sizeof fingerprint,"whole_fnv=%016" PRIx64,fnv(bytes,n));assert(strstr(streams[i],fingerprint));
    }
}
static void *preset_foreign_free(void *unused) {
    (void)unused;int rc=123;
    assert(full_bb_timecode_control_release_reply(input.source,last_reply,preset_release,preset_record,&rc)==1 && rc==-EPERM);
    return NULL;
}
static void refusal_validation(unsigned int command) {
    unsigned int n=command==0x040a?12:10;
    preset_prepare(command,0,0x80000001u);int rc=99;
    assert(!full_bb_timecode_control_dispatch(0x90000001u,input.data,&preset_io,&preset_guard,1,&rc) && rc==99);
    assert(!full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&preset_io,&preset_guard,0,&rc) && rc==99);
    assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&preset_io,&preset_guard,2,&rc)==1 && rc==-EINVAL);
    const unsigned int bad_sources[]={0,0x80000000u,0x90000000u,0xffffffffu};
    for(unsigned int i=0;i<4;i++){input.source=bad_sources[i];no_mutation(-EINVAL);}input.source=0x80000001u;
    const unsigned int offsets[]={0,1,4,5,6,7};
    for(unsigned int i=0;i<6;i++){input.data[offsets[i]]^=1;no_mutation(-EINVAL);input.data[offsets[i]]^=1;}
    const unsigned int sizes[]={4,8,9,10,11,12,13};
    for(unsigned int i=0;i<7;i++)if(sizes[i]!=n){input.size=sizes[i];no_mutation(-EINVAL);}
    input.size=n;
    if(command==0x0409) {
        const unsigned int bad[]={2,255,256,65535};
        for(unsigned int i=0;i<4;i++){input.data[8]=(unsigned char)bad[i];input.data[9]=(unsigned char)(bad[i]>>8);no_mutation(-EINVAL);}
    }
    preset_prepare(0x040b,0,0x80000001u);rc=99;
    assert(!full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,input.data,&preset_io,&preset_guard,1,&rc) && rc==99);
}
int main(int argc,char **argv) {
    assert(argc==2);test_case=argv[1];assert(!full_bb_timecode_control_owner_init());
    assert(offsetof(struct full_bb_timecode_snapshot,preset_generation)==offsetof(struct full_bb_timecode_snapshot,pending_commit)+sizeof(unsigned int));
    if(is("preset-preconditions")) {
        preset_prepare(0x040a,0,0x81234567u);no_mutation(-ENODATA);
        struct full_bb_timecode_snapshot saved=state;
        /* Apparent known bits and positive generations are insufficient. */
        state.known_mask=7;state.command_generations[0]=state.command_generations[1]=state.command_generations[2]=1;
        no_mutation(-ENODATA);state=saved;
        tc_bootstrap(2);preset_prepare(0x040a,0,0x81234567u);no_mutation(-ENODATA);
        preset_prepare(0x0400,0,0x81234567u);assert(!preset_dispatch());
        assert(tc_committed_mask==6 && snap().known_mask==7 && snap().generation==3);
        probe=input;probe.alive=1;probe.size=12;memcpy(probe.data,full_input,request_bytes);probe.data[2]=0x0a;probe.data[4]=12;
        int rc=123;assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,probe.data,&preset_io,&preset_guard,1,&rc)==1 && rc==-EBUSY);
        assert(!snap().preset_generation && tc_committed_mask==6);preset_consume();assert(tc_committed_mask==7);
        preset_prepare(0x0409,0,0x81234567u);no_mutation(-ENODATA);
        complete(0x040a,0,0x80000001u);new_order(0);check_state(0,0,1,1,1,0);
        complete(0x0409,1,0x8fffffffu);new_order(0);check_state(0,1,3,2,1,2);
    } else if(is("preset-tight-bounds")) {
        const unsigned int commands[]={0x0400,0x040a,0x0409};
        for(unsigned int i=0;i<3;i++) {
            tight_size=commands[i]==0x040a?12:10;tight_input=malloc(tight_size);assert(tight_input);
            unsigned char *wire=tight_input;memset(wire,0,tight_size);wire[0]=0x0d;wire[1]=0x20;wire[2]=(unsigned char)commands[i];wire[3]=4;wire[4]=(unsigned char)tight_size;wire[6]=1;wire[7]=0x80;
            /* An old command with exact10 cannot reach ownership without guards. */
            int rc=123;struct full_imaging_io io=preset_io;
            if(i==0)io.allocate=NULL;
            assert(full_bb_timecode_control_dispatch(FULL_BB_TIMECODE_CONTROL_CP,wire,&io,&preset_guard,1,&rc)==1 && rc==(i==0?-EINVAL:-ENODATA));
            free(tight_input);tight_input=NULL;
        }
    } else {
        tc_bootstrap(3);assert(tc_committed_mask==7 && snap().known_mask==7);
        unsigned char old_bytes[48];read_state(old_bytes);struct full_bb_timecode_snapshot old=snap();
        if(is("preset-validation")) {refusal_validation(0x040a);refusal_validation(0x0409);}
        else if(is("preset-pair-independent") || is("preset-raw-domain")) {
            check_state(0,0,0,0,0,0);
            if(is("preset-raw-domain")) {
                for(unsigned int i=0;i<256;i++) {
                    uint32_t raw=i|(uint32_t)(255-i)<<8|(uint32_t)(i^0xa5u)<<16|(uint32_t)i<<24;
                    complete(0x040a,raw,0x80000001u+i);check_state(raw,0,1,i+1,i+1,0);old_state_unchanged(old_bytes,old.command_generations);
                }
            } else {
                complete(0x040a,UINT32_C(0xff800100),0x80000001u);new_order(0);check_state(UINT32_C(0xff800100),0,1,1,1,0);
                complete(0x0409,1,0x8fffffffu);new_order(0);check_state(UINT32_C(0xff800100),1,3,2,1,2); /* AP input0 is wire1; no second inversion. */
                complete(0x0409,0,0x80000101u);new_order(0);check_state(UINT32_C(0xff800100),0,3,3,1,3); /* AP input1 is wire0. */
                complete(0x040a,UINT32_MAX,0x80000102u);check_state(UINT32_MAX,0,3,4,4,3);
                old_state_unchanged(old_bytes,old.command_generations);
                unsigned char preset_before[48],preset_after[48];read_preset_state(preset_before);
                complete(0x0401,0,0x80000103u);assert(old_events==8 && old_streams==4 && !new_events && !new_streams);
                read_preset_state(preset_after);assert(!memcmp(preset_before,preset_after,48) && snap().known_mask==7 && snap().generation==4);
                complete(0x040a,0,0x80000104u);new_order(0);check_state(0,0,3,5,5,3);
            }
        } else if(is("preset-history-capacity")) {
            unique_pool=1;
            for(unsigned int i=3;i<RETIRED_REPLY_CAPACITY;i++)complete(i&1u?0x040a:0x0409,i&1u?i:1,0x80000001u+i);
            assert(history_next==64 && snap().preset_generation==61);
            preset_prepare(0x040a,0,0x81234567u);no_mutation(-ENOSPC);
            for(unsigned int i=0;i<64;i++)preset_duplicate(history_pool[i].data);
            assert(full_bb_timecode_control_observe_allocate(0x90001111u,history_pool[1].data,7,1,-31)==0);
            assert(full_bb_timecode_control_observe_allocate(0x90001111u,history_pool[1].data,7,2,0)==0);
            assert(history_has(history_pool[1].data));
            void *fresh=NULL;history_reuse=1;assert(!history_allocate(0x90001111u,&fresh,7,1) && fresh==history_pool[1].data);
            assert(full_bb_timecode_control_observe_allocate(0x90001111u,fresh,7,1,0)==1 && !history_has(fresh));
            output->alive=0;output=NULL;complete(0x0409,0,0x8fffffffu);assert(history_next==65 && !snap().faults);
        } else if(is("preset-overflow")) {
            preset_prepare(0x040a,0,0x81234567u);
            uint64_t *fields[]={&state.preset_generation,&state.preset_applications,&state.preset_command_generations[0],&state.preset_command_generations[1]};
            for(unsigned int i=0;i<4;i++){uint64_t saved=*fields[i];*fields[i]=UINT64_MAX;no_mutation(-EOVERFLOW);*fields[i]=saved;}
            state.preset_generation=UINT64_MAX;complete(0x0400,1,0x81234567u);assert(snap().generation==4);
        } else {
            unsigned int command=is("preset-selector-readback")?0x0409:0x040a;
            if(command==0x0409)complete(0x040a,UINT32_C(0xff00ff00),0x80000001u);
            preset_prepare(command,command==0x040a?UINT32_C(0xff00ff00):1,0x81234567u);
            if(is("preset-readback"))inject_stage=1;
            if(is("preset-selector-readback"))inject_stage=2;
            if(is("preset-generation-readback"))inject_stage=3;
            if(is("preset-request-alias"))alias_offset=10; /* Must catch the last two request bytes. */
            if(is("preset-guard-first"))history_ready_rc=0;
            if(is("preset-reserve-fail"))history_reserve_rc=-61;
            if(is("preset-cleanup-fail"))history_release_rc=-77;
            if(is("preset-inline") || is("preset-inline-send-fail") || is("preset-inline-free-fail"))inline_reply=1;
            if(is("preset-inline-free-fail"))history_release_rc=-49;
            history_check_aliases=1;
            unsigned int base_sent=sent,base_input_frees=input_frees;
            int rc=preset_dispatch();struct full_bb_timecode_snapshot s=snap();
            if(inject_stage || is("preset-request-free-fail") || is("preset-send-fail") || is("preset-inline-send-fail") || is("preset-inline-free-fail")) {
                int expected=inject_stage?-EBADMSG:is("preset-request-free-fail")?-41:is("preset-inline-free-fail")?-49:-33;
                assert(rc==expected && s.faults && s.busy && !s.guard_held && !s.ap_consumed && !stage_count("COMMIT"));
                if(inject_stage)assert(sent==base_sent && input.alive && s.retained_request==input.data && !stage_count("STATE_READBACK"));
                if(is("preset-inline-send-fail"))assert(s.reply_freed && s.pending_commit && !output && !cleanups && s.send_rc==-33);
                if(is("preset-inline-free-fail"))assert(!s.reply_freed && output && s.retained_reply==last_reply && s.send_rc==0 && s.reply_free_rc==-49);
            } else if(is("preset-request-alias") || is("preset-allocation-null") || is("preset-allocation-error") || is("preset-allocation-short") || is("preset-source-drift") || is("preset-cleanup-fail") || is("preset-guard-first") || is("preset-guard-second") || is("preset-reserve-fail")) {
                int expected=is("preset-request-alias")?-EINVAL:is("preset-allocation-null")?-ENOMEM:is("preset-allocation-short")?-EMSGSIZE:is("preset-source-drift")?-EBADMSG:is("preset-guard-first")?-ENODATA:is("preset-guard-second")?-62:is("preset-reserve-fail")?-61:-31;
                assert(rc==expected && input.alive && !s.preset_generation && !s.retained_request && sent==base_sent);
                assert(input_frees==base_input_frees && s.generation==3 && !s.guard_held);
                if(is("preset-cleanup-fail"))assert(s.faults && s.busy && s.retained_cleanup==last_reply && s.allocate_rc==-31 && s.cleanup_rc==-77);
                else assert(!s.faults && !s.busy && !output);
            } else {
                assert(!rc);
                if(is("preset-inline")){assert(!output && s.ap_consumed);new_order(1);}
                else if(is("preset-wrong-free-thread") || is("preset-retained-alias") || is("preset-receive-content") || is("preset-receive-metadata") || is("preset-free-before-receive")) {
                    if(is("preset-receive-content")){output->data[11]=1;assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,12)==-EBADMSG);}
                    else if(is("preset-receive-metadata"))assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,10)==-EPERM);
                    else if(is("preset-free-before-receive")){int result=123;assert(full_bb_timecode_control_release_reply(input.source,last_reply,preset_release,preset_record,&result)==1 && result==-EBUSY);}
                    else {
                        assert(full_bb_timecode_control_observe_receive(input.source,last_reply,output->source,12)==1);
                        if(is("preset-wrong-free-thread")){pthread_t worker;assert(!pthread_create(&worker,NULL,preset_foreign_free,NULL));assert(!pthread_join(worker,NULL));}
                        else {history_release_rc=-49;int result=123;assert(full_bb_timecode_control_release_reply(input.source,last_reply,preset_release,preset_record,&result)==1 && result==-49);}
                    }
                    s=snap();assert(s.faults && s.busy && !s.ap_consumed && s.retained_reply==last_reply);
                    assert(full_bb_timecode_control_observe_allocate(input.source,last_reply,12,1,0)==-EBUSY);
                } else {
                    assert(is("preset-live-alias"));history_busy_observation(last_reply);preset_consume();new_order(0);
                    void *retired=last_reply;preset_duplicate(retired);
                    assert(full_bb_timecode_control_observe_receive(input.source,retired,FULL_BB_TIMECODE_CONTROL_CP,12)==-EALREADY);
                    complete(0x0409,0,0x8fffffffu);assert(last_reply==retired && !snap().faults);
                }
            }
            old_state_unchanged(old_bytes,old.command_generations);
        }
    }
    /* Pool metadata teardown only: retained failures remain in owner evidence. */
    if(output){output->alive=0;output=NULL;}
    printf("BB_TIMECODE_PRESET_CASE_PASS case=%s capture_verified=0 physical_verified=0\n",test_case);
    return 0;
}
