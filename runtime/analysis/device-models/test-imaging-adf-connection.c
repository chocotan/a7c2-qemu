/* SPDX-License-Identifier: MIT */
/* Host-only composition of the actual first/control providers; no VM claim. */
#define FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN control_edge_prerequisite_main
#include "test-imaging-control-connection.c"
#undef FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN
#include "imaging-adf-connection.h"
#include "adf-device.h"

static const unsigned int audio_s[4]={3,2,0,CONNECT_SOURCE},audio_p[4]={3,1,0,FULL_ADF_CP};
static const struct full_imaging_io audio_io;
static const struct full_adf_proc_guard audio_guard;
static struct connect_message *audio_request,*audio_final;
static unsigned int audio_caller=0x81cf61c4u,audio_allocs,audio_sends,audio_callbacks;
static unsigned int audio_reserves,audio_releases,audio_peer_request,audio_peer_reply,audio_skipped,audio_order;
static unsigned int audio_bad_alloc,audio_kind,audio_bad_source,audio_corrupt,audio_corrupt_at;
static int audio_send_error,audio_request_error,audio_reply_error,audio_cleanup_error;
static int audio_inline,audio_busy,audio_nested,audio_fork,audio_release_nested,audio_publish_fault,audio_concurrent_get;
static int audio_send_thread,audio_thread_error,audio_thread_started,audio_thread_go;
static pthread_t audio_reply_thread;
static pthread_mutex_t audio_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t audio_thread_condition=PTHREAD_COND_INITIALIZER;
static struct full_imaging_control_connection_snapshot audio_control_before;
static struct full_imaging_pin_connection_snapshot audio_first_before;
static struct pin_control_snapshot audio_pool_before;
static struct full_vef_snapshot audio_source_before,audio_peer_before,audio_bb_before;
static unsigned char audio_memory_before[PIN_CONTROL_CAPACITY];
static unsigned char audio_commands_before[sizeof *out_refs.commands],audio_clock_before[sizeof *out_refs.clock];
static unsigned char audio_output_before[sizeof *out_refs.output],audio_monitor_before[sizeof *out_refs.monitor];
static unsigned char audio_disable_before[sizeof *out_refs.disable],audio_glee_before[sizeof *out_refs.glee];
static int audio_have_prior;

static struct full_imaging_adf_connection_snapshot audio_snapshot(void){
    struct full_imaging_adf_connection_snapshot s;full_imaging_adf_connection_snapshot(&s);return s;
}
static void audio_preserved(void){
    if(!audio_have_prior)return;
    struct full_imaging_control_connection_snapshot c=control_snapshot();
    struct full_imaging_pin_connection_snapshot f=connect_snapshot();struct pin_control_snapshot p;pin_control_snapshot(&p);
    struct full_vef_snapshot b;native_infrabb_snapshot(&b);
    assert(!memcmp(&c,&audio_control_before,sizeof c) && !memcmp(&f,&audio_first_before,sizeof f));
    assert(!memcmp(&p,&audio_pool_before,sizeof p) && !memcmp(&b,&audio_bb_before,sizeof b));
    assert(!memcmp(connect_memory,audio_memory_before,sizeof connect_memory));
    assert(!memcmp(out_refs.commands,audio_commands_before,sizeof audio_commands_before));
    assert(!memcmp(out_refs.clock,audio_clock_before,sizeof audio_clock_before));
    assert(!memcmp(out_refs.output,audio_output_before,sizeof audio_output_before));
    assert(!memcmp(out_refs.monitor,audio_monitor_before,sizeof audio_monitor_before));
    assert(!memcmp(out_refs.disable,audio_disable_before,sizeof audio_disable_before));
    assert(!memcmp(out_refs.glee,audio_glee_before,sizeof audio_glee_before));connect_preserved();
}
static void audio_callback(void){
    assert(getpid()==host_pid);audio_callbacks++;struct full_imaging_adf_connection_snapshot s=audio_snapshot();
    if(s.initialized)assert(s.owner_pid==getpid());
    if(held)guarded();
    audio_preserved();
}
static void audio_check_pins(unsigned int a,unsigned int b,unsigned int pending){
    struct full_vef_snapshot x,y;native_infraimaging_snapshot(&x);full_adf_snapshot(&y);
    assert(x.pins[4].state==a && y.pins[4].state==b && x.pending==pending && !y.pending && !x.faults && !y.faults);
    assert(!memcmp(x.pins[4].self,audio_s,sizeof audio_s) && !memcmp(y.pins[4].self,audio_p,sizeof audio_p));
    if(a!=1)assert(!memcmp(x.pins[4].peer,audio_p,sizeof audio_p));
    if(b!=1)assert(!memcmp(y.pins[4].peer,audio_s,sizeof audio_s));
    x.pins[4]=audio_source_before.pins[4];x.pending=audio_source_before.pending;y.pins[4]=audio_peer_before.pins[4];
    assert(!memcmp(&x,&audio_source_before,sizeof x) && !memcmp(&y,&audio_peer_before,sizeof y));
}
static struct connect_message *audio_new_request(void){
    struct connect_message *m=cm_new(64,CONNECT_SOURCE,audio_caller);ctframe(m->data,64,1,2);ctput32(m->data,audio_caller);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,audio_s[i]);ctput32(m->data+48+4*i,audio_p[i]);}return m;
}
static void audio_get(unsigned int sid,int leave_reply){
    struct full_vef_snapshot before;
    if(sid==CONNECT_SOURCE)native_infraimaging_snapshot(&before);else full_adf_snapshot(&before);
    unsigned int expected_state=before.initialized?before.pins[4].state:1;
    get_destination=sid==CONNECT_SOURCE?0x8ab12345u:0x8dc98765u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    ctput32(m->data+32,3);ctput32(m->data+36,sid==CONNECT_SOURCE?2:1);
    int rc=77;assert((sid==CONNECT_SOURCE?native_infraimaging_dispatch(sid,m->data,&connect_get_io,1,&rc):
        full_adf_dispatch(sid,m->data,&connect_get_io,1,&rc)) && !rc && m->released);
    assert(get_queued && get_queued->bytes==56 && get_queued->source==sid);
    assert(ct32(get_queued->data+32)==3 && ct32(get_queued->data+36)==(sid==CONNECT_SOURCE?2u:1u) && !ct32(get_queued->data+40));
    assert(ct32(get_queued->data+44)==expected_state && ct32(get_queued->data+48)==sid && !ct32(get_queued->data+52));
    if(!leave_reply){int freed=77;assert((sid==CONNECT_SOURCE?
        native_infraimaging_release_reply(get_destination,get_queued->data,get_free,get_record,&freed):
        full_adf_release_reply(get_destination,get_queued->data,get_free,get_record,&freed)) && !freed);get_queued=0;}
}
static unsigned int audio_size(void *p){audio_callback();return cm_size(p);}
static unsigned int audio_source(void *p){audio_callback();return cm_source(p);}
static void audio_set(void *p,unsigned int sid){
    audio_callback();struct connect_message *m=cm_meta(p);m->source=m->allocation==audio_bad_source?0x1234u:sid;
    if(m->allocation==audio_corrupt)m->data[audio_corrupt_at]^=1;
}
static int audio_free(unsigned int owner,void *p){
    audio_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==audio_request && audio_request_error)return -53;
    if(m==audio_final && audio_reply_error)return -59;
    if(m->allocation && m!=audio_final && audio_cleanup_error)return -47;
    if(m==audio_final && audio_release_nested){int rc=77;unsigned int attempts=m->attempts;
        assert(full_imaging_adf_connection_release(owner,p,audio_free,0,&rc) && rc==-1021 && m->attempts==attempts);
    }
    cm_dispose(m);return 0;
}
static int audio_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    audio_callback();assert(owner==audio_caller && count==1 && held);audio_allocs++;
    static const unsigned int sizes[3]={64,72,56};assert(audio_allocs<=3 && n==sizes[audio_allocs-1]);
    if(audio_allocs==audio_bad_alloc){
        if(audio_kind==1){*out=0;return -41;}
        if(audio_kind==2){*out=0;return 0;}
        if(audio_kind==3){*out=audio_request->data;return 0;}
        if(audio_kind==6){assert(audio_allocs==2);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=audio_allocs;*out=m->data;
    if(audio_allocs==audio_bad_alloc){if(audio_kind==4)m->bytes=n-1;if(audio_kind==5)return -43;}
    return 0;
}
static int audio_reserve(void){
    audio_callback();audio_reserves++;
    if(audio_busy){assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);return -EBUSY;}
    return reserve();
}
static void audio_release_guard(void){
    audio_callback();assert(held && audio_snapshot().guard_held);audio_releases++;release_guard();
}
static void audio_record(const char *tag,const char *text){
    audio_callback();audio_order++;fprintf(stdout,"%s%s\n",tag,text);
    struct full_imaging_adf_connection_snapshot s=audio_snapshot();
    if(!strcmp(tag,"FULL_IMAGING_ADF_CONNECT_PEER_REQUEST ")){audio_check_pins(2,1,1);audio_peer_request=audio_order;}
    if(!strcmp(tag,"FULL_IMAGING_ADF_CONNECT_CALLBACK_SKIPPED ")){
        audio_check_pins(2,0,1);assert(s.callback_guard_checked && !s.callback_selected && s.no_format_checked);
        assert(strstr(text,"CP_VA=0x0019743a ") && strstr(text,"marker_writes=0 DMM_allocations=0 notifications=0 cache_writes=0"));audio_skipped=audio_order;
        if(audio_concurrent_get)audio_get(FULL_ADF_CP,0);
    }
    if(!strcmp(tag,"FULL_IMAGING_ADF_CONNECT_PEER_REPLY ")){if(!audio_concurrent_get)audio_check_pins(2,0,1);audio_peer_reply=audio_order;}
    if(audio_nested && !strcmp(tag,"FULL_IMAGING_ADF_CONNECT_REQUEST ")){int rc=77;
        assert(full_imaging_adf_connection_dispatch(CONNECT_SOURCE,audio_request->data,&audio_io,&audio_guard,1,&rc) && rc==-1021);
        assert(audio_snapshot().requests==1);
    }
    if(audio_fork && !strcmp(tag,"FULL_IMAGING_ADF_CONNECT_REQUEST ")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!audio_snapshot().initialized);
            assert(full_imaging_adf_connection_owner_init()==-1021);int rc=77;
            assert(full_imaging_adf_connection_dispatch(CONNECT_SOURCE,audio_request->data,&audio_io,&audio_guard,1,&rc) && rc==-1021);
            assert(!full_imaging_adf_connection_release(audio_caller,audio_request->data,audio_free,audio_record,&rc));_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
    if(audio_publish_fault && !strcmp(tag,"FULL_IMAGING_ADF_CONNECT_REPLY_QUEUED ")){int rc=77;
        assert(full_imaging_adf_connection_release(audio_caller^1u,audio_final->data,audio_free,0,&rc) && rc==-1021);
    }
}
static int audio_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&audio_thread_mutex));audio_thread_started=1;
    assert(!pthread_cond_signal(&audio_thread_condition));
    while(!audio_thread_go)assert(!pthread_cond_wait(&audio_thread_condition,&audio_thread_mutex));
    assert(!pthread_mutex_unlock(&audio_thread_mutex));
    return audio_thread_error?-59:cm_free(owner,p);
}
static void *audio_thread_release(void *unused){
    (void)unused;int rc=77;
    assert(full_imaging_adf_connection_release(audio_caller,audio_final->data,audio_thread_free,0,&rc));
    assert(rc==(audio_thread_error?-59:0));return 0;
}
static int audio_send(unsigned int owner,void *p){
    audio_callback();struct connect_message *m=cm_meta(p);assert(owner==audio_caller && m->owner==owner && m->bytes==56 && m->allocation==3);
    assert(m->source==CONNECT_SOURCE && p!=audio_request->data);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,audio_s[i]);
    assert(!memcmp(p,expected,sizeof expected));struct full_imaging_adf_connection_snapshot s=audio_snapshot();
    assert(s.live_reply==p && !s.queued && !s.request_freed && !s.ap_consumed && !s.reply_freed && !s.clean_completion && !s.faults);
    assert(s.peer_requests==1 && s.peer_replies==1 && s.callback_guard_checked && !s.callback_selected && s.no_format_checked && s.predecessor_preserved);
    assert(audio_peer_request<audio_skipped && audio_skipped<audio_peer_reply);audio_check_pins(0,0,1);audio_final=m;audio_sends++;
    if(audio_send_thread){
        assert(!pthread_mutex_lock(&audio_thread_mutex));assert(!pthread_create(&audio_reply_thread,0,audio_thread_release,0));
        while(!audio_thread_started)assert(!pthread_cond_wait(&audio_thread_condition,&audio_thread_mutex));
        assert(!pthread_mutex_unlock(&audio_thread_mutex));
    }
    if(audio_inline){int rc=77;assert(full_imaging_adf_connection_release(owner,p,audio_free,audio_record,&rc) && !rc);}
    return audio_send_error;
}
static const struct full_imaging_io audio_io={audio_allocate,audio_free,audio_set,audio_send,audio_size,audio_source,audio_record};
static const struct full_adf_proc_guard audio_guard={audio_reserve,audio_release_guard};
static int audio_dispatch(const struct full_imaging_io *transport,const struct full_adf_proc_guard *g,int enabled,int *rc){
    return full_imaging_adf_connection_dispatch(CONNECT_SOURCE,audio_request->data,transport,g,enabled,rc);
}
static void audio_finish(void){
    audio_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);
    printf("IMAGING_ADF_CONNECTION_HOST_TEST_PASS: callbacks=%u allocations=%u sends=%u; actual composed host providers, no VM or capture evidence\n",audio_callbacks,audio_allocs,audio_sends);
}
#ifndef FULL_IMAGING_ADF_CONNECTION_TEST_MAIN
#define FULL_IMAGING_ADF_CONNECTION_TEST_MAIN main
#endif
int FULL_IMAGING_ADF_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(25);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    int early=!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"first-type0") ||
        !strcmp(name,"control-type8") || !strcmp(name,"get-fallthrough") || !strcmp(name,"other-type") ||
        !strcmp(name,"bad-wire") || !strcmp(name,"invalid-source") || !strcmp(name,"missing-transport") || !strcmp(name,"missing-guard") ||
        !strcmp(name,"uninitialized") || !strcmp(name,"fork") || !strcmp(name,"no-prior");
    if(strcmp(name,"uninitialized")){
        assert(!full_imaging_adf_connection_owner_init());
        struct full_imaging_adf_connection_snapshot initial=audio_snapshot();
        assert(initial.initialized && initial.owner_pid==getpid() && !initial.callback_guard_checked && !initial.callback_selected && !initial.no_format_checked);
        assert(!initial.requests && !initial.faults && !initial.clean_completion);
        assert(!full_imaging_adf_connection_owner_init());
        struct full_imaging_adf_connection_snapshot again=audio_snapshot();assert(!memcmp(&initial,&again,sizeof initial));
    }
    if(!early){char *old[]={"test","normal",argv[2],0};
        assert(!(!strcmp(name,"no-control")?first_edge_prerequisite_main(3,old):control_edge_prerequisite_main(3,old)));alarm(25);
        audio_control_before=control_snapshot();audio_first_before=connect_snapshot();pin_control_snapshot(&audio_pool_before);
        native_infrabb_snapshot(&audio_bb_before);memcpy(audio_memory_before,connect_memory,sizeof connect_memory);
        assert(audio_first_before.clean_completion && audio_first_before.ap_consumed==1 && audio_pool_before.allocations==2);
        memcpy(audio_commands_before,out_refs.commands,sizeof audio_commands_before);memcpy(audio_clock_before,out_refs.clock,sizeof audio_clock_before);
        memcpy(audio_output_before,out_refs.output,sizeof audio_output_before);memcpy(audio_monitor_before,out_refs.monitor,sizeof audio_monitor_before);
        memcpy(audio_disable_before,out_refs.disable,sizeof audio_disable_before);memcpy(audio_glee_before,out_refs.glee,sizeof audio_glee_before);audio_have_prior=1;
        if(strcmp(name,"no-get")){
            if(strcmp(name,"no-source-get"))audio_get(CONNECT_SOURCE,!strcmp(name,"live-source-get"));
            if(strcmp(name,"live-source-get") && strcmp(name,"no-peer-get"))audio_get(FULL_ADF_CP,!strcmp(name,"live-peer-get"));
        }
        if(!strcmp(name,"not-ready-source"))pin_registry_test_set_state(native_infraimaging_registry(),4,0);
        if(!strcmp(name,"not-ready-peer"))full_adf_test_set_state(4,0);
        native_infraimaging_snapshot(&audio_source_before);full_adf_snapshot(&audio_peer_before);
    }
    if(!strcmp(name,"dynamic-caller"))audio_caller=0x8fedab01u;
    audio_request=audio_new_request();int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"first-type0") ||
       !strcmp(name,"control-type8") || !strcmp(name,"get-fallthrough") || !strcmp(name,"other-type")){
        unsigned int dst=!strcmp(name,"unrelated")?FULL_ADF_CP:CONNECT_SOURCE;
        if(!strcmp(name,"short"))audio_request->bytes=63;
        if(!strcmp(name,"get-fallthrough")){audio_request->bytes=48;ctframe(audio_request->data,48,0,2);}
        if(!strcmp(name,"first-type0") || !strcmp(name,"control-type8"))for(unsigned int i=0;i<4;i++){
            const unsigned int *s=!strcmp(name,"first-type0")?connect_s:control_s,*p=!strcmp(name,"first-type0")?connect_p:control_p;
            ctput32(audio_request->data+32+4*i,s[i]);ctput32(audio_request->data+48+4*i,p[i]);
        }
        if(!strcmp(name,"other-type")){ctput32(audio_request->data+32,2);ctput32(audio_request->data+48,2);}
        assert(!full_imaging_adf_connection_dispatch(dst,audio_request->data,&audio_io,&audio_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!audio_snapshot().requests && !audio_allocs && !audio_request->released);audio_finish();return 0;
    }
    if(!strcmp(name,"bad-wire")){
        static const unsigned int positions[]={0,4,8,10,12,16,24,26,28,30,32,36,40,44,48,52,56,60,33,37,41,45,49,53,57,61};
        for(unsigned int i=0;i<sizeof positions/sizeof *positions;i++){unsigned int at=positions[i];audio_request->data[at]^=1;
            assert(audio_dispatch(&audio_io,&audio_guard,1,&rc) && rc==-1021);audio_request->data[at]^=1;}
        static const unsigned int aliases[]={0x103u,0x10003u,0x1000003u};
        for(unsigned int i=0;i<sizeof aliases/sizeof *aliases;i++){
            ctput32(audio_request->data+32,aliases[i]);ctput32(audio_request->data+48,aliases[i]);
            assert(audio_dispatch(&audio_io,&audio_guard,1,&rc) && rc==-1021);
        }
        ctput32(audio_request->data+32,3);ctput32(audio_request->data+48,3);
        static const unsigned int callers[]={0,0x80000000u,0x91234567u};
        for(unsigned int i=0;i<sizeof callers/sizeof *callers;i++){
            audio_request->source=callers[i];ctput32(audio_request->data,callers[i]);
            assert(audio_dispatch(&audio_io,&audio_guard,1,&rc) && rc==-1021);
        }
        assert(!audio_snapshot().requests && !audio_allocs && !audio_request->released);audio_finish();return 0;
    }
    if(!strcmp(name,"invalid-source")){
        audio_request->source^=1;assert(audio_dispatch(&audio_io,&audio_guard,1,&rc) && rc==-1021);
        assert(!audio_snapshot().requests && !audio_allocs);audio_finish();return 0;
    }
    if(!strcmp(name,"missing-transport")){
        for(unsigned int i=0;i<6;i++){struct full_imaging_io bad=audio_io;
            if(i==0)bad.allocate=0;else if(i==1)bad.release=0;else if(i==2)bad.send=0;else if(i==3)bad.set_source=0;else if(i==4)bad.size=0;else bad.source=0;
            assert(audio_dispatch(&bad,&audio_guard,1,&rc) && rc==-1021);}
        assert(!audio_snapshot().requests && !audio_allocs);audio_finish();return 0;
    }
    if(!strcmp(name,"missing-guard")){
        struct full_adf_proc_guard a={0,audio_release_guard},b={audio_reserve,0};const struct full_adf_proc_guard *guards[]={0,&a,&b};
        for(unsigned int i=0;i<3;i++)assert(audio_dispatch(&audio_io,guards[i],1,&rc) && rc==-1021);
        assert(!audio_snapshot().requests && !audio_allocs);audio_finish();return 0;
    }
    if(!strcmp(name,"uninitialized")){assert(audio_dispatch(&audio_io,&audio_guard,1,&rc) && rc==-1021);
        assert(!audio_callbacks && !audio_snapshot().requests);audio_finish();return 0;}
    if(!strcmp(name,"fork")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!audio_snapshot().initialized);
            assert(full_imaging_adf_connection_owner_init()==-1021);assert(audio_dispatch(&audio_io,&audio_guard,1,&rc) && rc==-1021);assert(!audio_callbacks);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));audio_finish();return 0;
    }
    if(!strcmp(name,"resource-busy")){audio_busy=1;assert(!pthread_mutex_lock(&resource_mutex));}
    if(!strcmp(name,"source-error"))audio_bad_source=1;
    if(!strcmp(name,"peer-wire")){audio_corrupt=1;audio_corrupt_at=26;}
    if(!strcmp(name,"peer-reply-wire")){audio_corrupt=2;audio_corrupt_at=26;}
    if(!strcmp(name,"send-fail"))audio_send_error=-61;
    if(!strcmp(name,"request-free-fail"))audio_request_error=1;
    if(!strcmp(name,"inline-free"))audio_inline=1;
    if(!strcmp(name,"inline-send-fail")){audio_inline=1;audio_send_error=-61;}
    if(!strcmp(name,"recursive"))audio_nested=1;
    if(!strcmp(name,"fork-held"))audio_fork=1;
    if(!strcmp(name,"recursive-free"))audio_release_nested=1;
    if(!strcmp(name,"queued-fault"))audio_publish_fault=1;
    if(!strcmp(name,"concurrent-peer-get"))audio_concurrent_get=1;
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){
        audio_send_thread=1;audio_send_error=-61;audio_thread_error=!strcmp(name,"in-flight-free-fail");
    }
    unsigned int nth=0,kind=0,offset=0;
    if(sscanf(name,"alloc-%u-%u",&nth,&kind)==2){assert(nth>=1 && nth<=3 && kind>=1 && kind<=5);audio_bad_alloc=nth;audio_kind=kind;}
    if(sscanf(name,"source-%u",&nth)==1){assert(nth>=1 && nth<=3);audio_bad_source=nth;}
    if(sscanf(name,"wire-%u-%u",&nth,&offset)==2){assert(nth>=1 && nth<=3 && offset<(nth==1?64u:nth==2?72u:56u));audio_corrupt=nth;audio_corrupt_at=offset;}
    if(!strcmp(name,"internal-free-fail"))audio_cleanup_error=1;
    if(!strcmp(name,"alloc-cleanup-fail")){audio_bad_alloc=2;audio_kind=5;audio_cleanup_error=1;}
    if(!strcmp(name,"alloc-live-alias")){audio_bad_alloc=2;audio_kind=6;}
    assert(audio_dispatch(&audio_io,&audio_guard,1,&rc));if(audio_busy)assert(!pthread_mutex_unlock(&resource_mutex));
    struct full_imaging_adf_connection_snapshot s=audio_snapshot();
    assert(!full_imaging_adf_connection_owner_init());
    struct full_imaging_adf_connection_snapshot after_init=audio_snapshot();assert(!memcmp(&s,&after_init,sizeof s));
    assert(!s.busy && !s.guard_held && !held && s.requests==1 && s.owner_pid==getpid());
    assert(audio_reserves==audio_releases+(unsigned int)audio_busy || (!audio_reserves && !audio_releases));
    if(audio_send_thread){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.live_reply==audio_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !audio_final->released && !audio_final->attempts);
        assert(!pthread_mutex_lock(&audio_thread_mutex));audio_thread_go=1;assert(!pthread_cond_signal(&audio_thread_condition));
        assert(!pthread_mutex_unlock(&audio_thread_mutex));assert(!pthread_join(audio_reply_thread,0));s=audio_snapshot();
        assert(!s.releasing_reply && s.faults && !s.clean_completion);
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") ||
        !strcmp(name,"fork-held") || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail") || !strcmp(name,"repeat") ||
        !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault");
    if(success || audio_request_error){
        assert(!rc && s.connections==1 && s.queued && audio_allocs==3 && audio_sends==1 && !s.retained_messages && !s.retained_cleanup);
        assert(s.peer_requests==1 && s.peer_replies==1 && s.callback_guard_checked && !s.callback_selected && s.no_format_checked && s.predecessor_preserved);
        audio_check_pins(0,0,0);
        if(audio_request_error)assert(s.faults && !s.clean_completion && s.retained_request==audio_request->data && !s.request_freed && !audio_request->released);
        else assert(s.request_freed && !s.retained_request && audio_request->released);
        if(audio_publish_fault)assert(s.faults && !s.clean_completion);
        else if(!audio_request_error)assert(!s.faults && s.clean_completion);
        if(!audio_inline){
            assert(s.live_reply==audio_final->data && !s.ap_consumed && !s.reply_freed);
            if(!strcmp(name,"wrong-owner")){int freed=77;unsigned int attempts=audio_final->attempts;
                assert(full_imaging_adf_connection_release(audio_caller^1u,audio_final->data,audio_free,audio_record,&freed) && freed==-1021);
                assert(audio_final->attempts==attempts && !audio_snapshot().clean_completion && audio_snapshot().faults);}
            if(!strcmp(name,"reply-free-fail")){int freed=77;audio_reply_error=1;
                assert(full_imaging_adf_connection_release(audio_caller,audio_final->data,audio_free,audio_record,&freed) && freed==-59);
                assert(!audio_final->released && !audio_snapshot().clean_completion && !audio_snapshot().ap_consumed);audio_reply_error=0;}
            int freed=77;assert(full_imaging_adf_connection_release(audio_caller,audio_final->data,audio_free,audio_record,&freed) && !freed);
        }
        s=audio_snapshot();assert(s.ap_consumed==1 && s.reply_freed && !s.live_reply && !s.retained_messages && audio_final->released);
        if(audio_request_error || audio_publish_fault || audio_release_nested || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        else assert(!s.faults && s.clean_completion);
        int freed=77;assert(!full_imaging_adf_connection_release(audio_caller,audio_final->data,audio_free,audio_record,&freed) && freed==77);
        if(!strcmp(name,"repeat")){struct connect_message *again=audio_new_request();int repeated=77;
            assert(full_imaging_adf_connection_dispatch(CONNECT_SOURCE,again->data,&audio_io,&audio_guard,1,&repeated) && repeated==-1021);
            assert(!again->released && audio_allocs==3 && audio_sends==1 && audio_snapshot().requests==1);}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !s.request_freed);
        assert(!audio_request->released && !audio_request->attempts && !s.retained_request);
        if(audio_inline || (audio_send_thread && !audio_thread_error))assert(s.ap_consumed==1 && s.reply_freed && !s.live_reply && audio_final->released);
        else assert(!s.ap_consumed);
        if(early || !strcmp(name,"no-control") || !strcmp(name,"no-get") || !strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get") ||
           !strcmp(name,"not-ready-source") || !strcmp(name,"not-ready-peer") || get_queued || audio_busy)assert(!audio_allocs && !audio_sends);
        if(audio_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        if(audio_concurrent_get){
            struct full_vef_snapshot peer;full_adf_snapshot(&peer);
            assert(peer.queries==audio_peer_before.queries+1 && !peer.faults && !peer.pending && !peer.live_replies);
            assert(s.peer_replies==1 && s.no_format_checked && !audio_sends && audio_allocs==2 && !s.retained_messages);
        }
        unsigned int before_allocs=audio_allocs,before_sends=audio_sends;int retry=77;
        assert(audio_dispatch(&audio_io,&audio_guard,1,&retry) && retry==-1021);
        struct full_imaging_adf_connection_snapshot after=audio_snapshot();assert(!memcmp(&after,&s,sizeof s));
        assert(audio_allocs==before_allocs && audio_sends==before_sends);
        assert(!cm_free(CONNECT_SOURCE,audio_request->data) && audio_request->released);
        struct full_imaging_adf_connection_snapshot after_caller_free=audio_snapshot();assert(!after_caller_free.retained_request && !memcmp(&after_caller_free,&s,sizeof s));
        if(audio_send_thread && audio_thread_error){
            assert(s.live_reply==audio_final->data && s.retained_messages==1 && !audio_final->released);
            int freed=77;assert(full_imaging_adf_connection_release(audio_caller,audio_final->data,audio_free,audio_record,&freed) && !freed);
            struct full_imaging_adf_connection_snapshot recovered=audio_snapshot();
            assert(recovered.ap_consumed==1 && recovered.faults && !recovered.clean_completion && !recovered.live_reply && !recovered.retained_messages);
        }
    }
    audio_finish();return 0;
}
