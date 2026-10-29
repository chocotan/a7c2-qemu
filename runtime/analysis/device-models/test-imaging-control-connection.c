/* SPDX-License-Identifier: MIT */
/* Host-only composition; the first edge's byte-array backing is never guest evidence. */
#define FULL_IMAGING_PIN_CONNECTION_TEST_MAIN first_edge_prerequisite_main
#include "test-imaging-pin-connection.c"
#undef FULL_IMAGING_PIN_CONNECTION_TEST_MAIN
#include "imaging-control-connection.h"

static const unsigned int control_s[4]={8,2,0,CONNECT_SOURCE},control_p[4]={8,1,0,CONNECT_PEER};
static const struct full_imaging_io control_io;
static const struct full_adf_proc_guard control_guard;
static struct connect_message *control_request,*control_final;
static unsigned int control_caller=0x81cf61c4u,control_allocs,control_sends,control_callbacks;
static unsigned int control_reserves,control_releases,control_peer_request,control_peer_reply,control_marker,control_posthook,control_order;
static unsigned int control_bad_alloc,control_kind,control_bad_source,control_corrupt,control_corrupt_at;
static int control_send_error,control_request_error,control_reply_error,control_cleanup_error;
static int control_inline,control_busy,control_nested,control_fork,control_release_nested,control_publish_fault,control_concurrent_get;
static int control_send_thread,control_thread_error,control_thread_started,control_thread_go;
static pthread_t control_reply_thread;
static pthread_mutex_t control_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t control_thread_condition=PTHREAD_COND_INITIALIZER;
static struct full_imaging_pin_connection_snapshot control_first_before;
static struct pin_control_snapshot control_pool_before;
static struct full_vef_snapshot control_source_before,control_peer_before;
static unsigned char control_memory_before[PIN_CONTROL_CAPACITY];
static int control_have_first;

static struct full_imaging_control_connection_snapshot control_snapshot(void){
    struct full_imaging_control_connection_snapshot s;full_imaging_control_connection_snapshot(&s);return s;
}
static void control_preserved(void){
    if(!control_have_first)return;
    struct full_imaging_pin_connection_snapshot f=connect_snapshot();struct pin_control_snapshot p;pin_control_snapshot(&p);
    assert(!memcmp(&f,&control_first_before,sizeof f));assert(!memcmp(&p,&control_pool_before,sizeof p));
    assert(!memcmp(connect_memory,control_memory_before,sizeof connect_memory));connect_preserved();
}
static void control_callback(void){
    assert(getpid()==host_pid);control_callbacks++;struct full_imaging_control_connection_snapshot s=control_snapshot();
    if(s.initialized)assert(s.owner_pid==getpid());
    if(held)guarded();
    control_preserved();
}
static void control_check_pins(unsigned int a,unsigned int b,unsigned int pending){
    struct full_vef_snapshot x,y;native_infraimaging_snapshot(&x);native_infrabb_snapshot(&y);
    assert(x.pins[5].state==a && y.pins[8].state==b && x.pending==pending && !y.pending && !x.faults && !y.faults);
    if(a!=1)assert(!memcmp(x.pins[5].peer,control_p,sizeof control_p));
    if(b!=1)assert(!memcmp(y.pins[8].peer,control_s,sizeof control_s));
    x.pins[5]=control_source_before.pins[5];x.pending=control_source_before.pending;y.pins[8]=control_peer_before.pins[8];
    assert(!memcmp(&x,&control_source_before,sizeof x));assert(!memcmp(&y,&control_peer_before,sizeof y));
}
static struct connect_message *control_new_request(void){
    struct connect_message *m=cm_new(64,CONNECT_SOURCE,control_caller);ctframe(m->data,64,1,2);ctput32(m->data,control_caller);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,control_s[i]);ctput32(m->data+48+4*i,control_p[i]);}return m;
}
static void control_get(unsigned int sid,int leave_reply){
    struct full_vef_snapshot before;
    if(sid==CONNECT_SOURCE)native_infraimaging_snapshot(&before);else native_infrabb_snapshot(&before);
    unsigned int expected_state=before.pins[sid==CONNECT_SOURCE?5:8].state;
    get_destination=sid==CONNECT_SOURCE?0x8ab12345u:0x8dc98765u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    ctput32(m->data+32,8);ctput32(m->data+36,sid==CONNECT_SOURCE?2:1);
    int rc=77;assert((sid==CONNECT_SOURCE?native_infraimaging_dispatch(sid,m->data,&connect_get_io,1,&rc):
        native_infrabb_dispatch(sid,m->data,&connect_get_io,1,&rc)) && !rc && m->released);
    assert(get_queued && get_queued->bytes==56 && get_queued->source==sid);
    assert(ct32(get_queued->data+32)==8 && ct32(get_queued->data+36)==(sid==CONNECT_SOURCE?2u:1u) && !ct32(get_queued->data+40));
    assert(ct32(get_queued->data+44)==expected_state && ct32(get_queued->data+48)==sid && !ct32(get_queued->data+52));
    if(!leave_reply){int freed=77;assert((sid==CONNECT_SOURCE?
        native_infraimaging_release_reply(get_destination,get_queued->data,get_free,get_record,&freed):
        native_infrabb_release_reply(get_destination,get_queued->data,get_free,get_record,&freed)) && !freed);get_queued=0;}
}
static unsigned int control_size(void *p){control_callback();return cm_size(p);}
static unsigned int control_source(void *p){control_callback();return cm_source(p);}
static void control_set(void *p,unsigned int sid){
    control_callback();struct connect_message *m=cm_meta(p);m->source=m->allocation==control_bad_source?0x1234u:sid;
    if(m->allocation==control_corrupt)m->data[control_corrupt_at]^=1;
}
static int control_free(unsigned int owner,void *p){
    control_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==control_request && control_request_error)return -53;
    if(m==control_final && control_reply_error)return -59;
    if(m->allocation && m!=control_final && control_cleanup_error)return -47;
    if(m==control_final && control_release_nested){int rc=77;unsigned int attempts=m->attempts;
        assert(full_imaging_control_connection_release(owner,p,control_free,0,&rc) && rc==-1021 && m->attempts==attempts);
    }
    cm_dispose(m);return 0;
}
static int control_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    control_callback();assert(owner==control_caller && count==1 && held);control_allocs++;
    static const unsigned int sizes[3]={64,72,56};assert(control_allocs<=3 && n==sizes[control_allocs-1]);
    if(control_allocs==control_bad_alloc){
        if(control_kind==1){*out=0;return -41;}
        if(control_kind==2){*out=0;return 0;}
        if(control_kind==3){*out=control_request->data;return 0;}
        if(control_kind==6){assert(control_allocs==2);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=control_allocs;*out=m->data;
    if(control_allocs==control_bad_alloc){if(control_kind==4)m->bytes=n-1;if(control_kind==5)return -43;}
    return 0;
}
static int control_reserve(void){
    control_callback();control_reserves++;
    if(control_busy){assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);return -EBUSY;}
    return reserve();
}
static void control_release_guard(void){
    control_callback();assert(held && control_snapshot().guard_held);control_releases++;release_guard();
}
static void control_record(const char *tag,const char *text){
    control_callback();control_order++;fprintf(stdout,"%s%s\n",tag,text);
    struct full_imaging_control_connection_snapshot s=control_snapshot();
    if(!strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_PEER_REQUEST ")){control_check_pins(2,1,1);control_peer_request=control_order;}
    if(!strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_PEER_REPLY ")){control_check_pins(2,0,1);control_peer_reply=control_order;}
    if(!strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_PEER_MARKER_WRITTEN ")){
        control_check_pins(0,0,1);assert(s.peer_marker_known==1 && s.peer_marker==1 && s.peer_marker_writes==1);
        assert(strstr(text,"source_CP_VA=0x01acad0f ") && strstr(text,"old_value_known=0 ") && strstr(text,"readback=1 "));control_marker=control_order;
    }
    if(!strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_POSTHOOK_NO_FORMAT ")){
        assert(s.posthook_checked && s.posthook_no_format && control_marker && !s.queued && !s.ap_consumed);control_posthook=control_order;
        if(control_concurrent_get)control_get(CONNECT_PEER,0);
    }
    if(control_nested && !strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_REQUEST ")){int rc=77;
        assert(full_imaging_control_connection_dispatch(CONNECT_SOURCE,control_request->data,&control_io,&control_guard,1,&rc) && rc==-1021);
        assert(control_snapshot().requests==1);
    }
    if(control_fork && !strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_REQUEST ")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!control_snapshot().initialized);
            assert(full_imaging_control_connection_owner_init()==-1021);int rc=77;
            assert(full_imaging_control_connection_dispatch(CONNECT_SOURCE,control_request->data,&control_io,&control_guard,1,&rc) && rc==-1021);
            assert(!full_imaging_control_connection_release(control_caller,control_request->data,control_free,control_record,&rc));_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
    if(control_publish_fault && !strcmp(tag,"FULL_IMAGING_CONTROL_CONNECT_REPLY_QUEUED ")){int rc=77;
        assert(full_imaging_control_connection_release(control_caller^1u,control_final->data,control_free,0,&rc) && rc==-1021);
    }
}
static int control_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&control_thread_mutex));control_thread_started=1;
    assert(!pthread_cond_signal(&control_thread_condition));
    while(!control_thread_go)assert(!pthread_cond_wait(&control_thread_condition,&control_thread_mutex));
    assert(!pthread_mutex_unlock(&control_thread_mutex));
    return control_thread_error?-59:cm_free(owner,p);
}
static void *control_thread_release(void *unused){
    (void)unused;int rc=77;
    assert(full_imaging_control_connection_release(control_caller,control_final->data,control_thread_free,0,&rc));
    assert(rc==(control_thread_error?-59:0));return 0;
}
static int control_send(unsigned int owner,void *p){
    control_callback();struct connect_message *m=cm_meta(p);assert(owner==control_caller && m->owner==owner && m->bytes==56 && m->allocation==3);
    assert(m->source==CONNECT_SOURCE && p!=control_request->data);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,control_s[i]);
    assert(!memcmp(p,expected,sizeof expected));struct full_imaging_control_connection_snapshot s=control_snapshot();
    assert(s.live_reply==p && !s.queued && !s.request_freed && !s.ap_consumed && !s.reply_freed && !s.clean_completion && !s.faults);
    assert(s.peer_requests==1 && s.peer_replies==1 && s.peer_marker_known==1 && s.peer_marker==1 && s.peer_marker_writes==1);
    assert(s.posthook_checked && s.posthook_no_format && control_peer_request<control_peer_reply && control_peer_reply<control_marker && control_marker<control_posthook);
    control_check_pins(0,0,1);control_final=m;control_sends++;
    if(control_send_thread){
        assert(!pthread_mutex_lock(&control_thread_mutex));assert(!pthread_create(&control_reply_thread,0,control_thread_release,0));
        while(!control_thread_started)assert(!pthread_cond_wait(&control_thread_condition,&control_thread_mutex));
        assert(!pthread_mutex_unlock(&control_thread_mutex));
    }
    if(control_inline){int rc=77;assert(full_imaging_control_connection_release(owner,p,control_free,control_record,&rc) && !rc);}
    return control_send_error;
}
static const struct full_imaging_io control_io={control_allocate,control_free,control_set,control_send,control_size,control_source,control_record};
static const struct full_adf_proc_guard control_guard={control_reserve,control_release_guard};
static int control_dispatch(const struct full_imaging_io *transport,const struct full_adf_proc_guard *g,int enabled,int *rc){
    return full_imaging_control_connection_dispatch(CONNECT_SOURCE,control_request->data,transport,g,enabled,rc);
}
static void control_finish(void){
    control_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);
    printf("IMAGING_CONTROL_CONNECTION_HOST_TEST_PASS: callbacks=%u allocations=%u sends=%u; byte-array fixture, no VM or capture evidence\n",control_callbacks,control_allocs,control_sends);
}
#ifndef FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN
#define FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN main
#endif
int FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(20);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    int early=!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"first-type0") ||
        !strcmp(name,"bad-wire") || !strcmp(name,"invalid-source") || !strcmp(name,"missing-transport") || !strcmp(name,"missing-guard") ||
        !strcmp(name,"uninitialized") || !strcmp(name,"fork") || !strcmp(name,"no-first");
    if(strcmp(name,"uninitialized")){
        assert(!full_imaging_control_connection_owner_init());
        struct full_imaging_control_connection_snapshot initial=control_snapshot();
        assert(initial.initialized && initial.owner_pid==getpid() && !initial.peer_marker_known && !initial.peer_marker_writes);
        assert(!initial.requests && !initial.faults && !initial.clean_completion);
        assert(!full_imaging_control_connection_owner_init());
        struct full_imaging_control_connection_snapshot again=control_snapshot();assert(!memcmp(&initial,&again,sizeof initial));
    }
    if(!early){char *old[]={"test","normal",argv[2],0};assert(!first_edge_prerequisite_main(3,old));alarm(20);
        control_first_before=connect_snapshot();pin_control_snapshot(&control_pool_before);memcpy(control_memory_before,connect_memory,sizeof connect_memory);
        assert(control_first_before.clean_completion && control_first_before.ap_consumed==1 && control_pool_before.allocations==2);control_have_first=1;
        if(strcmp(name,"no-get")){control_get(CONNECT_SOURCE,!strcmp(name,"live-source-get"));if(strcmp(name,"live-source-get"))control_get(CONNECT_PEER,!strcmp(name,"live-peer-get"));}
        native_infraimaging_snapshot(&control_source_before);native_infrabb_snapshot(&control_peer_before);
    }
    if(!strcmp(name,"dynamic-caller"))control_caller=0x8fedab01u;
    control_request=control_new_request();int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"first-type0")){
        unsigned int dst=!strcmp(name,"unrelated")?CONNECT_PEER:CONNECT_SOURCE;
        if(!strcmp(name,"short"))control_request->bytes=63;
        if(!strcmp(name,"first-type0"))for(unsigned int i=0;i<4;i++){ctput32(control_request->data+32+4*i,connect_s[i]);ctput32(control_request->data+48+4*i,connect_p[i]);}
        assert(!full_imaging_control_connection_dispatch(dst,control_request->data,&control_io,&control_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!control_snapshot().requests && !control_allocs && !control_request->released);control_finish();return 0;
    }
    if(!strcmp(name,"bad-wire")){
        static const unsigned int positions[]={0,4,8,10,12,16,24,26,28,30,32,36,40,44,48,52,56,60,33,37,41,45,49,53,57,61};
        for(unsigned int i=0;i<sizeof positions/sizeof *positions;i++){unsigned int at=positions[i];control_request->data[at]^=1;
            assert(control_dispatch(&control_io,&control_guard,1,&rc) && rc==-1021);control_request->data[at]^=1;}
        assert(!control_snapshot().requests && !control_allocs && !control_request->released);control_finish();return 0;
    }
    if(!strcmp(name,"invalid-source")){
        control_request->source^=1;assert(control_dispatch(&control_io,&control_guard,1,&rc) && rc==-1021);
        assert(!control_snapshot().requests && !control_allocs);control_finish();return 0;
    }
    if(!strcmp(name,"missing-transport")){
        for(unsigned int i=0;i<6;i++){struct full_imaging_io bad=control_io;
            if(i==0)bad.allocate=0;else if(i==1)bad.release=0;else if(i==2)bad.send=0;else if(i==3)bad.set_source=0;else if(i==4)bad.size=0;else bad.source=0;
            assert(control_dispatch(&bad,&control_guard,1,&rc) && rc==-1021);}
        assert(!control_snapshot().requests && !control_allocs);control_finish();return 0;
    }
    if(!strcmp(name,"missing-guard")){
        struct full_adf_proc_guard a={0,control_release_guard},b={control_reserve,0};const struct full_adf_proc_guard *guards[]={0,&a,&b};
        for(unsigned int i=0;i<3;i++)assert(control_dispatch(&control_io,guards[i],1,&rc) && rc==-1021);
        assert(!control_snapshot().requests && !control_allocs);control_finish();return 0;
    }
    if(!strcmp(name,"uninitialized")){assert(control_dispatch(&control_io,&control_guard,1,&rc) && rc==-1021);
        assert(!control_callbacks && !control_snapshot().requests);control_finish();return 0;}
    if(!strcmp(name,"fork")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!control_snapshot().initialized);
            assert(full_imaging_control_connection_owner_init()==-1021);assert(control_dispatch(&control_io,&control_guard,1,&rc) && rc==-1021);assert(!control_callbacks);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));control_finish();return 0;
    }
    if(!strcmp(name,"resource-busy")){control_busy=1;assert(!pthread_mutex_lock(&resource_mutex));}
    if(!strcmp(name,"source-error"))control_bad_source=1;
    if(!strcmp(name,"peer-wire")){control_corrupt=1;control_corrupt_at=26;}
    if(!strcmp(name,"peer-reply-wire")){control_corrupt=2;control_corrupt_at=26;}
    if(!strcmp(name,"send-fail"))control_send_error=-61;
    if(!strcmp(name,"request-free-fail"))control_request_error=1;
    if(!strcmp(name,"inline-free"))control_inline=1;
    if(!strcmp(name,"inline-send-fail")){control_inline=1;control_send_error=-61;}
    if(!strcmp(name,"recursive"))control_nested=1;
    if(!strcmp(name,"fork-held"))control_fork=1;
    if(!strcmp(name,"recursive-free"))control_release_nested=1;
    if(!strcmp(name,"queued-fault"))control_publish_fault=1;
    if(!strcmp(name,"concurrent-peer-get"))control_concurrent_get=1;
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){
        control_send_thread=1;control_send_error=-61;control_thread_error=!strcmp(name,"in-flight-free-fail");
    }
    unsigned int nth=0,kind=0,offset=0;
    if(sscanf(name,"alloc-%u-%u",&nth,&kind)==2){assert(nth>=1 && nth<=3 && kind>=1 && kind<=5);control_bad_alloc=nth;control_kind=kind;}
    if(sscanf(name,"source-%u",&nth)==1){assert(nth>=1 && nth<=3);control_bad_source=nth;}
    if(sscanf(name,"wire-%u-%u",&nth,&offset)==2){assert(nth>=1 && nth<=3 && offset<(nth==1?64u:nth==2?72u:56u));control_corrupt=nth;control_corrupt_at=offset;}
    if(!strcmp(name,"internal-free-fail"))control_cleanup_error=1;
    if(!strcmp(name,"alloc-cleanup-fail")){control_bad_alloc=2;control_kind=5;control_cleanup_error=1;}
    if(!strcmp(name,"alloc-live-alias")){control_bad_alloc=2;control_kind=6;}
    assert(control_dispatch(&control_io,&control_guard,1,&rc));if(control_busy)assert(!pthread_mutex_unlock(&resource_mutex));
    struct full_imaging_control_connection_snapshot s=control_snapshot();
    assert(!full_imaging_control_connection_owner_init());
    struct full_imaging_control_connection_snapshot after_init=control_snapshot();assert(!memcmp(&s,&after_init,sizeof s));
    assert(!s.busy && !s.guard_held && !held && s.requests==1 && s.owner_pid==getpid());
    assert(control_reserves==control_releases+(unsigned int)control_busy || (!control_reserves && !control_releases));
    if(control_send_thread){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.live_reply==control_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !control_final->released && !control_final->attempts);
        assert(!pthread_mutex_lock(&control_thread_mutex));control_thread_go=1;assert(!pthread_cond_signal(&control_thread_condition));
        assert(!pthread_mutex_unlock(&control_thread_mutex));assert(!pthread_join(control_reply_thread,0));s=control_snapshot();
        assert(!s.releasing_reply && s.faults && !s.clean_completion);
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") ||
        !strcmp(name,"fork-held") || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail") || !strcmp(name,"repeat") ||
        !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault");
    if(success || control_request_error){
        assert(!rc && s.connections==1 && s.queued && control_allocs==3 && control_sends==1 && !s.retained_messages && !s.retained_cleanup);
        assert(s.peer_requests==1 && s.peer_replies==1 && s.peer_marker_known==1 && s.peer_marker==1 && s.peer_marker_writes==1);
        assert(s.posthook_checked && s.posthook_no_format);control_check_pins(0,0,0);
        if(control_request_error)assert(s.faults && !s.clean_completion && s.retained_request==control_request->data && !s.request_freed && !control_request->released);
        else assert(s.request_freed && !s.retained_request && control_request->released);
        if(control_publish_fault)assert(s.faults && !s.clean_completion);
        else if(!control_request_error)assert(!s.faults && s.clean_completion);
        if(!control_inline){
            assert(s.live_reply==control_final->data && !s.ap_consumed && !s.reply_freed);
            if(!strcmp(name,"wrong-owner")){int freed=77;unsigned int attempts=control_final->attempts;
                assert(full_imaging_control_connection_release(control_caller^1u,control_final->data,control_free,control_record,&freed) && freed==-1021);
                assert(control_final->attempts==attempts && !control_snapshot().clean_completion && control_snapshot().faults);}
            if(!strcmp(name,"reply-free-fail")){int freed=77;control_reply_error=1;
                assert(full_imaging_control_connection_release(control_caller,control_final->data,control_free,control_record,&freed) && freed==-59);
                assert(!control_final->released && !control_snapshot().clean_completion && !control_snapshot().ap_consumed);control_reply_error=0;}
            int freed=77;assert(full_imaging_control_connection_release(control_caller,control_final->data,control_free,control_record,&freed) && !freed);
        }
        s=control_snapshot();assert(s.ap_consumed==1 && s.reply_freed && !s.live_reply && !s.retained_messages && control_final->released);
        if(control_request_error || control_publish_fault || control_release_nested || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        else assert(!s.faults && s.clean_completion);
        int freed=77;assert(!full_imaging_control_connection_release(control_caller,control_final->data,control_free,control_record,&freed) && freed==77);
        if(!strcmp(name,"repeat")){struct connect_message *again=control_new_request();int repeated=77;
            assert(full_imaging_control_connection_dispatch(CONNECT_SOURCE,again->data,&control_io,&control_guard,1,&repeated) && repeated==-1021);
            assert(!again->released && control_allocs==3 && control_sends==1 && control_snapshot().requests==1);}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !s.request_freed);
        assert(!control_request->released && !control_request->attempts && !s.retained_request);
        if(control_inline || (control_send_thread && !control_thread_error))assert(s.ap_consumed==1 && s.reply_freed && !s.live_reply && control_final->released);
        else assert(!s.ap_consumed);
        if(early || !strcmp(name,"no-get") || get_queued || control_busy)assert(!control_allocs && !control_sends);
        if(control_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        if(control_concurrent_get){
            struct full_vef_snapshot peer;native_infrabb_snapshot(&peer);
            assert(peer.queries==control_peer_before.queries+1 && !peer.faults && !peer.pending && !peer.live_replies);
            assert(s.peer_replies==1 && s.posthook_no_format && !control_sends && control_allocs==2 && !s.retained_messages);
        }
        unsigned int before_allocs=control_allocs,before_sends=control_sends;int retry=77;
        assert(control_dispatch(&control_io,&control_guard,1,&retry) && retry==-1021);
        struct full_imaging_control_connection_snapshot after=control_snapshot();assert(!memcmp(&after,&s,sizeof s));
        assert(control_allocs==before_allocs && control_sends==before_sends);
        assert(!cm_free(CONNECT_SOURCE,control_request->data) && control_request->released);
        struct full_imaging_control_connection_snapshot after_caller_free=control_snapshot();
        assert(!after_caller_free.retained_request && !memcmp(&after_caller_free,&s,sizeof s));
        if(control_send_thread && control_thread_error){
            assert(s.live_reply==control_final->data && s.retained_messages==1 && !control_final->released);
            int freed=77;assert(full_imaging_control_connection_release(control_caller,control_final->data,control_free,control_record,&freed) && !freed);
            struct full_imaging_control_connection_snapshot recovered=control_snapshot();
            assert(recovered.ap_consumed==1 && recovered.faults && !recovered.clean_completion && !recovered.live_reply && !recovered.retained_messages);
        }
    }
    control_finish();return 0;
}
