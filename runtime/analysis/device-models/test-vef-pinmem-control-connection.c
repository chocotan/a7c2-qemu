/* SPDX-License-Identifier: MIT */
/* Actual first-six providers and retired byte-array backing; no VM evidence. */
#define FULL_VEF_PINMEM_INPUT_CONNECTION_TEST_MAIN vpc_six_prerequisite_main
#include "test-vef-pinmem-input-connection.c"
#undef FULL_VEF_PINMEM_INPUT_CONNECTION_TEST_MAIN
#include "vef-pinmem-control-connection.h"
#include <sys/syscall.h>
extern long syscall(long,...);
static const unsigned int vpc_s[4]={8,2,0,FULL_VEF_CP},vpc_p[4]={8,1,0,FULL_PINMEM_CP};
static struct connect_message *vpc_request,*vpc_final;
static unsigned int vpc_caller=0x81ce1234,vpc_allocs,vpc_sends,vpc_callbacks,vpc_reserves,vpc_releases;
static unsigned int vpc_bad_alloc,vpc_bad_kind,vpc_bad_source,vpc_corrupt,vpc_offset,vpc_event_fault;
static unsigned int vpc_order,vpc_manager_order,vpc_enqueue_order,vpc_consume_order,vpc_posthook_order,vpc_answer_free_order;
static int vpc_ready,vpc_inline,vpc_send_error,vpc_request_error,vpc_reply_error,vpc_cleanup_error,vpc_recursive,vpc_busy,vpc_fork_held;
static int vpc_recursive_free,vpc_queued_fault,vpc_duplicate_event,vpc_mutate_request;
static int vpc_threaded,vpc_thread_error,vpc_thread_started,vpc_thread_go;
static pthread_t vpc_reply_thread;
static pthread_mutex_t vpc_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t vpc_thread_condition=PTHREAD_COND_INITIALIZER;
static const struct full_imaging_io vpc_io;
static const struct full_adf_proc_guard vpc_guard;
struct vpc_history {
    struct full_imaging_pin_connection_snapshot first;
    struct full_imaging_control_connection_snapshot control;
    struct full_imaging_adf_connection_snapshot audio;
    struct full_infrabb_vef_connection_snapshot fourth;
    struct full_infrabb_vef_control_connection_snapshot fifth;
    struct full_vef_pinmem_input_connection_snapshot sixth;
    struct pin_connection_snapshot old;
    struct full_vef_path_snapshot path;
    struct full_adf_proc_snapshot proc;
    struct full_adf_set_input_snapshot input;
    struct full_adf_set_output_snapshot output;
    struct full_bb_set_mode_snapshot bb;
    struct pin_control_snapshot pool;
    struct full_vef_snapshot imaging,bb_registry,vef,pinmem,adf;
};
static struct vpc_history vpc_before;
static unsigned char vpc_memory_before[PIN_CONTROL_CAPACITY];
static unsigned long long vpc_backing_hash;
static void vpc_capture(struct vpc_history *p){
    memset(p,0,sizeof *p);full_imaging_pin_connection_snapshot(&p->first);full_imaging_control_connection_snapshot(&p->control);
    full_imaging_adf_connection_snapshot(&p->audio);full_infrabb_vef_connection_snapshot(&p->fourth);full_infrabb_vef_control_connection_snapshot(&p->fifth);
    full_vef_pinmem_input_connection_snapshot(&p->sixth);full_pin_connection_snapshot(&p->old);full_vef_path_snapshot(&p->path);
    full_adf_proc_snapshot(&p->proc);full_adf_set_input_snapshot(&p->input);full_adf_set_output_snapshot(&p->output);full_bb_set_mode_snapshot(&p->bb);
    pin_control_snapshot(&p->pool);native_infraimaging_snapshot(&p->imaging);native_infrabb_snapshot(&p->bb_registry);
    full_vef_snapshot(&p->vef);full_pinmem_snapshot(&p->pinmem);full_adf_snapshot(&p->adf);
}
static struct full_vef_pinmem_control_connection_snapshot vpc_snapshot(void){
    struct full_vef_pinmem_control_connection_snapshot s;full_vef_pinmem_control_connection_snapshot(&s);return s;
}
static void vpc_preserved(void){
    if(!vpc_ready)return;
    struct vpc_history after;vpc_capture(&after);
    after.vef.pins[15]=vpc_before.vef.pins[15];after.vef.pending=vpc_before.vef.pending;after.pinmem.pins[12]=vpc_before.pinmem.pins[12];
    assert(!memcmp(&after,&vpc_before,sizeof after));
    assert(cthash(connect_memory,sizeof connect_memory)==vpc_backing_hash && !memcmp(connect_memory,vpc_memory_before,sizeof connect_memory));
    out_preserved_failure();out_check_shadow();
}
static void vpc_get(unsigned int sid,const unsigned int *key,int leave){
    get_destination=sid==FULL_VEF_CP?0x8a0bc001u:0x8a0bc002u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    int rc=77,freed=77;int handled=sid==FULL_VEF_CP?full_vef_dispatch(sid,m->data,&vc_seed_io,1,&rc):full_pinmem_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    assert(handled && !rc && m->released && vc_seed_queued && vc_seed_queued!=m);
    for(unsigned int i=0;i<3;i++)assert(ct32(vc_seed_queued->data+32+4*i)==key[i]);
    assert(ct32(vc_seed_queued->data+44)==1 && ct32(vc_seed_queued->data+48)==sid);
    if(leave){vc_seed_queued=0;return;}
    handled=sid==FULL_VEF_CP?full_vef_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed):full_pinmem_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    assert(handled && !freed);vc_seed_queued=0;
}
static void vpc_seed(const char *seed,const char *name){
    if(!strcmp(name,"no-sixth") || !strcmp(name,"no-sixth-AP-free")){
        vi_history(seed,0);vi_clear_messages();
        if(!strcmp(name,"no-sixth-AP-free")){
            vc_get(FULL_VEF_CP,vi_s,1,0);vc_get(FULL_PINMEM_CP,vi_p,1,0);assert(!full_vef_pinmem_input_connection_owner_init());
            struct connect_message *m=vc_pair_request(FULL_VEF_CP,vi_s,vi_p);const struct full_adf_proc_guard g={reserve,release_guard};int rc=77;
            assert(full_vef_pinmem_input_connection_dispatch(FULL_VEF_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);vc_seed_queued=0;
        }
    }else{char *args[]={"test","normal",(char *)seed,0};assert(!vpc_six_prerequisite_main(3,args));vi_clear_messages();}
    alarm(30);
    if(strcmp(name,"no-source-get"))vpc_get(FULL_VEF_CP,vpc_s,!strcmp(name,"live-source-get"));
    if(strcmp(name,"no-peer-get"))vpc_get(FULL_PINMEM_CP,vpc_p,!strcmp(name,"live-peer-get"));
}
static void vpc_save(void){
    vpc_capture(&vpc_before);memcpy(vpc_memory_before,connect_memory,sizeof connect_memory);vpc_backing_hash=cthash(connect_memory,sizeof connect_memory);vpc_ready=1;
    assert(vpc_before.sixth.clean_completion && vpc_before.sixth.ap_consumed==1 && vpc_before.sixth.buffer_freed);
    assert(vpc_before.sixth.dmm_requests==9 && vpc_before.sixth.notifications_consumed==3 && vpc_before.sixth.reference_readbacks==9);
    assert(vpc_before.first.format.consumed==2 && vpc_before.first.forwarded_formats==1 && vpc_before.fourth.forwarded_vef_formats==1 && vpc_before.fourth.forwarded_bb_formats==1);
    assert(vpc_before.pool.allocations>=4 && vpc_before.pool.allocations==vpc_before.pool.releases && !vpc_before.pool.live);
}
static struct connect_message *vpc_new_request(void){
    struct connect_message *m=cm_new(64,FULL_VEF_CP,vpc_caller);ctframe(m->data,64,1,2);ctput32(m->data,vpc_caller);ctput32(m->data+20,0x7855c);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,vpc_s[i]);ctput32(m->data+48+4*i,vpc_p[i]);}return m;
}
static void vpc_callback(void){assert(host_pid==getpid());vpc_callbacks++;(void)vpc_snapshot();vpc_preserved();if(held)guarded();}
static unsigned int vpc_size(void *p){vpc_callback();return cm_size(p);}
static unsigned int vpc_source(void *p){vpc_callback();return cm_source(p);}
static int vpc_free(unsigned int owner,void *p){
    vpc_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==vpc_request && vpc_request_error)return -53;
    if(m==vpc_final && vpc_reply_error)return -59;
    if(m->allocation==2 && vpc_snapshot().event8_enqueued){assert(vpc_snapshot().event8_consumed==1 && !vpc_snapshot().event8_pending);vpc_answer_free_order=++vpc_order;}
    if(m->allocation && m!=vpc_final && vpc_cleanup_error)return -47;
    if(m==vpc_final && vpc_recursive_free){int rc=77;unsigned int attempts=m->attempts;
        assert(full_vef_pinmem_control_connection_release(owner,p,vpc_free,0,&rc) && rc==-1021 && m->attempts==attempts);}
    cm_dispose(m);return 0;
}
static void vpc_set(void *p,unsigned int sid){
    vpc_callback();struct connect_message *m=cm_meta(p);m->source=m->allocation==vpc_bad_source?1234:sid;
    if(m->allocation==vpc_corrupt)m->data[vpc_offset]^=1;
}
static int vpc_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    vpc_callback();assert(held && owner==vpc_caller && count==1);vpc_allocs++;
    static const unsigned int sizes[3]={64,72,56};assert(vpc_allocs<=3 && n==sizes[vpc_allocs-1]);
    if(vpc_allocs==vpc_bad_alloc){
        if(vpc_bad_kind==1){*out=0;return -41;}if(vpc_bad_kind==2){*out=0;return 0;}if(vpc_bad_kind==3){*out=vpc_request->data;return 0;}
        if(vpc_bad_kind==6){assert(vpc_allocs==2);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=vpc_allocs;*out=m->data;
    if(vpc_allocs==vpc_bad_alloc){if(vpc_bad_kind==4)m->bytes=n-1;if(vpc_bad_kind==5)return -43;}return 0;
}
static int vpc_reserve(void){vpc_callback();vpc_reserves++;return vpc_busy?-EBUSY:reserve();}
static void vpc_release_guard(void){vpc_callback();assert(held && vpc_snapshot().guard_held);vpc_releases++;release_guard();}
static int vpc_dispatch(int *rc){return full_vef_pinmem_control_connection_dispatch(FULL_VEF_CP,vpc_request->data,&vpc_io,&vpc_guard,1,rc);}
static void vpc_pins(unsigned int source,unsigned int peer,unsigned int pending){
    struct full_vef_snapshot a,b;full_vef_snapshot(&a);full_pinmem_snapshot(&b);
    assert(a.pins[15].state==source && b.pins[12].state==peer && a.pending==pending && !b.pending);
    if(source!=1)assert(!memcmp(a.pins[15].peer,vpc_p,sizeof vpc_p));
    if(peer!=1)assert(!memcmp(b.pins[12].peer,vpc_s,sizeof vpc_s));
}
static void vpc_record(const char *tag,const char *text){
    vpc_callback();vpc_order++;fprintf(stdout,"%s%s\n",tag,text);
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_PEER_REQUEST "))vpc_pins(2,1,1);
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_SINK_MANAGER ")){vpc_pins(2,0,1);assert(vpc_snapshot().manager_calls==1 && !vpc_snapshot().manager_return);vpc_manager_order=vpc_order;}
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_PEER_REPLY "))vpc_pins(2,0,1);
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_EVENT8_ENQUEUED ")){
        struct full_vef_pinmem_control_connection_snapshot s=vpc_snapshot();vpc_pins(2,0,1);
        assert(s.event8_pending==1 && s.event8_enqueued==1 && !s.event8_consumed && s.event8_body==(unsigned char *)s.event8_answer+24);
        unsigned char parameter[32]={0};ctput32(parameter,0x56450001);assert(!memcmp(parameter,s.event8_parameter,32));
        assert(s.event8_token==0x56450001 && !s.original_CP_event_pointer_identity_verified);vpc_enqueue_order=vpc_order;
        if(vpc_event_fault<=5 && vpc_event_fault)full_vef_pinmem_control_connection_test_event_corrupt(vpc_event_fault);
        if(vpc_event_fault==6)((unsigned char *)s.event8_answer)[64]^=1;
        if(vpc_event_fault==7)((unsigned char *)s.event8_answer)[48]^=1;
        if(vpc_event_fault==8)((unsigned char *)s.event8_answer)[60]^=1;
        if(vpc_event_fault==9)((unsigned char *)s.event8_answer)[68]^=1;
    }
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_EVENT8_CONSUMED ")){
        struct full_vef_pinmem_control_connection_snapshot s=vpc_snapshot();vpc_pins(0,0,1);
        assert(s.event8_consumed==1 && !s.event8_pending && !s.event8_body && !s.event8_answer && s.event8_token_verified && s.event8_peer_verified);vpc_consume_order=vpc_order;
        if(vpc_duplicate_event)assert(full_vef_pinmem_control_connection_test_event_consume(&vpc_io)==-1);
    }
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_POSTHOOK_NO_FORMAT ")){
        vpc_pins(0,0,1);assert(vpc_snapshot().source_ordinal==15 && !vpc_snapshot().callback_selected);vpc_posthook_order=vpc_order;
    }
    if(vpc_queued_fault && !strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_REPLY_QUEUED ")){int rc=77;
        assert(full_vef_pinmem_control_connection_release(vpc_caller^1u,vpc_final->data,vpc_free,0,&rc) && rc==-1021);}
    if(!strcmp(tag,"FULL_VEF_PINMEM_CONTROL_CONNECT_REQUEST ")){
        if(vpc_mutate_request)vpc_request->data[20]^=1;
        if(vpc_recursive){int rc=77;assert(vpc_dispatch(&rc) && rc==-1021 && vpc_snapshot().requests==1);}
        if(vpc_fork_held){pid_t child=fork();assert(child>=0);if(!child){alarm(2);int rc=77;assert(!vpc_snapshot().initialized);
                assert(full_vef_pinmem_control_connection_owner_init()==-1021);assert(vpc_dispatch(&rc) && rc==-1021);
                assert(!full_vef_pinmem_control_connection_release(vpc_caller,vpc_request->data,vpc_free,vpc_record,&rc));_exit(0);}
            int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    }
}
static int vpc_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&vpc_thread_mutex));vpc_thread_started=1;assert(!pthread_cond_signal(&vpc_thread_condition));
    while(!vpc_thread_go)assert(!pthread_cond_wait(&vpc_thread_condition,&vpc_thread_mutex));
    assert(!pthread_mutex_unlock(&vpc_thread_mutex));return vpc_thread_error?-59:cm_free(owner,p);
}
static void *vpc_thread_release(void *unused){
    (void)unused;assert(syscall(SYS_gettid)!=vpc_snapshot().sender_tid);int rc=77;assert(full_vef_pinmem_control_connection_release(vpc_caller,vpc_final->data,vpc_thread_free,0,&rc));assert(rc==(vpc_thread_error?-59:0));return 0;
}
static int vpc_send(unsigned int owner,void *p){
    vpc_callback();vpc_final=cm_meta(p);struct full_vef_pinmem_control_connection_snapshot s=vpc_snapshot();
    assert(owner==vpc_caller && vpc_final->allocation==3 && vpc_final->bytes==56 && vpc_final->source==FULL_VEF_CP && p!=vpc_request->data);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,vpc_s[i]);assert(!memcmp(p,expected,56));
    assert(s.live_reply==p && s.predecessor_preserved && !s.faults && s.peer_requests==1 && s.peer_replies==1 && s.manager_calls==1 && !s.manager_return);
    assert(s.source_slot==15 && s.peer_ordinal==12 && s.source_ordinal==15 && s.posthook_checked && s.posthook_no_format && !s.callback_selected);
    assert(s.event8_enqueued==1 && s.event8_consumed==1 && !s.event8_pending && !s.event8_inflight && s.event8_token_verified && s.event8_peer_verified);
    assert(!s.dmm_allocations && !s.notifications && !s.cache_writes && !s.marker_writes && !s.clock_writes && !s.mmio_writes);
    assert(vpc_manager_order<vpc_enqueue_order && vpc_enqueue_order<vpc_consume_order && vpc_consume_order<vpc_posthook_order && vpc_posthook_order<vpc_answer_free_order);
    vpc_pins(0,0,1);vpc_sends++;
    if(vpc_threaded){assert(!pthread_mutex_lock(&vpc_thread_mutex));assert(!pthread_create(&vpc_reply_thread,0,vpc_thread_release,0));
        while(!vpc_thread_started){assert(!pthread_cond_wait(&vpc_thread_condition,&vpc_thread_mutex));}
        assert(!pthread_mutex_unlock(&vpc_thread_mutex));}
    if(vpc_inline){int rc=77;assert(full_vef_pinmem_control_connection_release(owner,p,vpc_free,vpc_record,&rc) && !rc);}return vpc_send_error;
}
static const struct full_imaging_io vpc_io={vpc_allocate,vpc_free,vpc_set,vpc_send,vpc_size,vpc_source,vpc_record};
static const struct full_adf_proc_guard vpc_guard={vpc_reserve,vpc_release_guard};
static void vpc_finish(void){vpc_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("VEF_PINMEM_CONTROL_CONNECTION_HOST_TEST_PASS");}
#ifndef FULL_VEF_PINMEM_CONTROL_CONNECTION_TEST_MAIN
#define FULL_VEF_PINMEM_CONTROL_CONNECTION_TEST_MAIN main
#endif
int FULL_VEF_PINMEM_CONTROL_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    if(strcmp(name,"uninitialized")){assert(!full_vef_pinmem_control_connection_owner_init());struct full_vef_pinmem_control_connection_snapshot s=vpc_snapshot();
        assert(!full_vef_pinmem_control_connection_owner_init());struct full_vef_pinmem_control_connection_snapshot same=vpc_snapshot();assert(!memcmp(&s,&same,sizeof s));}
    if(!strcmp(name,"dynamic-caller"))vpc_caller=0x8fed1023;
    vpc_request=vpc_new_request();int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"long") || !strcmp(name,"other-edge")){
        if(!strcmp(name,"short"))vpc_request->bytes=63;
        if(!strcmp(name,"long"))vpc_request->bytes=65;
        if(!strcmp(name,"other-edge"))ctput32(vpc_request->data+40,1);
        assert(!full_vef_pinmem_control_connection_dispatch(!strcmp(name,"unrelated")?FULL_PINMEM_CP:FULL_VEF_CP,vpc_request->data,&vpc_io,&vpc_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!vpc_snapshot().requests && !vpc_allocs && !vpc_request->released);vpc_finish();return 0;
    }
    if(!strcmp(name,"fork") || !strcmp(name,"uninitialized")){
        if(!strcmp(name,"uninitialized")){assert(vpc_dispatch(&rc) && rc==-1021 && !vpc_callbacks);vpc_finish();return 0;}
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(full_vef_pinmem_control_connection_owner_init()==-1021);assert(!vpc_snapshot().initialized);
            assert(vpc_dispatch(&rc) && rc==-1021 && !vpc_callbacks);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));vpc_finish();return 0;
    }
    if(!strcmp(name,"missing-transport")){
        for(unsigned int i=0;i<6;i++){struct full_imaging_io bad=vpc_io;
            if(i==0)bad.allocate=0;else if(i==1)bad.release=0;else if(i==2)bad.send=0;else if(i==3)bad.set_source=0;else if(i==4)bad.size=0;else bad.source=0;
            assert(full_vef_pinmem_control_connection_dispatch(FULL_VEF_CP,vpc_request->data,&bad,&vpc_guard,1,&rc) && rc==-1021);}
        assert(!vpc_callbacks && !vpc_snapshot().requests && !vpc_snapshot().faults);vpc_finish();return 0;
    }
    if(!strcmp(name,"missing-guard")){
        struct full_adf_proc_guard a={0,vpc_release_guard},b={vpc_reserve,0};const struct full_adf_proc_guard *guards[]={0,&a,&b};
        for(unsigned int i=0;i<3;i++)assert(full_vef_pinmem_control_connection_dispatch(FULL_VEF_CP,vpc_request->data,&vpc_io,guards[i],1,&rc) && rc==-1021);
        assert(!vpc_callbacks && !vpc_snapshot().requests && !vpc_snapshot().faults);vpc_finish();return 0;
    }
    if(!strcmp(name,"unsupported-controls")){
        unsigned int controls[]={2,3,4,0x100,0x104,0x8100,0x8001};
        for(unsigned int i=0;i<sizeof controls/sizeof *controls;i++){ctput16(vpc_request->data+26,controls[i]);assert(vpc_dispatch(&rc) && rc==-1021);}
        assert(!vpc_snapshot().requests && !vpc_snapshot().faults && !vpc_allocs && !vpc_sends && !vpc_request->released);vpc_finish();return 0;
    }
    if(!strcmp(name,"bad-wire")){
        unsigned int offsets[]={0,4,8,10,12,16,24,26,28,30};
        for(unsigned int i=0;i<sizeof offsets/sizeof *offsets;i++){vpc_request->data[offsets[i]]^=1;assert(vpc_dispatch(&rc) && rc==-1021);vpc_request->data[offsets[i]]^=1;}
        for(unsigned int i=32;i<64;i+=4){vpc_request->data[i]^=1;rc=77;assert(!vpc_dispatch(&rc) && rc==77);vpc_request->data[i]^=1;}
        assert(!vpc_snapshot().requests && !vpc_snapshot().faults && !vpc_allocs);vpc_finish();return 0;
    }
    if(!strcmp(name,"invalid-source")){vpc_request->source^=1;assert(vpc_dispatch(&rc) && rc==-1021 && !vpc_snapshot().requests && !vpc_snapshot().faults);vpc_finish();return 0;}
    assert(vpc_dispatch(&rc) && rc==-1021);struct full_vef_pinmem_control_connection_snapshot early=vpc_snapshot();
    assert(!early.requests && !early.faults && early.unadmitted_count==1 && !vpc_allocs && !vpc_request->released);
    if(!strcmp(name,"no-prior")){assert(vpc_dispatch(&rc) && rc==-1021 && vpc_snapshot().unadmitted_count==2);vpc_finish();return 0;}
    assert(!cm_free(FULL_VEF_CP,vpc_request->data));vpc_request=0;vi_clear_messages();vpc_seed(argv[2],name);
    if(!strcmp(name,"no-sixth") || !strcmp(name,"no-sixth-AP-free") || !strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get") || !strcmp(name,"live-source-get") || !strcmp(name,"live-peer-get")){
        vpc_request=vpc_new_request();assert(vpc_dispatch(&rc) && rc==-1021 && !vpc_snapshot().requests && !vpc_snapshot().faults && !vpc_allocs && !vpc_request->released);vpc_finish();return 0;
    }
    vi_clear_messages();vpc_save();vpc_request=vpc_new_request();
    if(!strcmp(name,"resource-busy"))vpc_busy=1;
    if(!strcmp(name,"send-fail"))vpc_send_error=-61;
    if(!strcmp(name,"inline-free"))vpc_inline=1;
    if(!strcmp(name,"inline-send-fail")){vpc_inline=1;vpc_send_error=-61;}
    if(!strcmp(name,"request-free-fail"))vpc_request_error=1;
    if(!strcmp(name,"recursive"))vpc_recursive=1;
    if(!strcmp(name,"fork-held"))vpc_fork_held=1;
    if(!strcmp(name,"recursive-free"))vpc_recursive_free=1;
    if(!strcmp(name,"queued-fault"))vpc_queued_fault=1;
    if(!strcmp(name,"duplicate-event"))vpc_duplicate_event=1;
    if(!strcmp(name,"request-mutated"))vpc_mutate_request=1;
    if(!strcmp(name,"cleanup-fail"))vpc_cleanup_error=1;
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){vpc_threaded=1;vpc_send_error=-61;vpc_thread_error=!strcmp(name,"in-flight-free-fail");}
    unsigned int nth=0,kind=0,offset=0;
    if(sscanf(name,"alloc-%u-%u",&nth,&kind)==2){vpc_bad_alloc=nth;vpc_bad_kind=kind;}
    if(sscanf(name,"source-%u",&nth)==1)vpc_bad_source=nth;
    if(sscanf(name,"wire-%u-%u",&nth,&offset)==2){vpc_corrupt=nth;vpc_offset=offset;}
    if(sscanf(name,"event-%u",&nth)==1)vpc_event_fault=nth;
    assert(vpc_dispatch(&rc));struct full_vef_pinmem_control_connection_snapshot s=vpc_snapshot();
    assert(!held && !s.busy && !s.guard_held && s.owner_pid==getpid() && vpc_reserves==vpc_releases+(unsigned int)vpc_busy);
    if(vpc_busy){assert(rc==-1021 && !s.requests && !s.faults && s.unadmitted_count==2 && !vpc_sends && !vpc_allocs);vpc_finish();return 0;}
    assert(s.requests==1 && s.unadmitted_count==1);
    if(vpc_threaded){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.live_reply==vpc_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !vpc_final->released && !vpc_final->attempts);
        assert(!pthread_mutex_lock(&vpc_thread_mutex));vpc_thread_go=1;assert(!pthread_cond_signal(&vpc_thread_condition));assert(!pthread_mutex_unlock(&vpc_thread_mutex));
        assert(!pthread_join(vpc_reply_thread,0));s=vpc_snapshot();assert(!s.releasing_reply && s.faults && !s.clean_completion);
        if(vpc_thread_error){assert(s.live_reply==vpc_final->data && s.retained_messages==1 && !s.ap_consumed && !vpc_final->released);
            int f=77;assert(full_vef_pinmem_control_connection_release(vpc_caller,vpc_final->data,vpc_free,vpc_record,&f) && !f);}
        s=vpc_snapshot();assert(s.ap_consumed==(unsigned int)vpc_thread_error && s.reply_freed && !s.live_reply && !s.retained_messages && vpc_final->released);vpc_finish();return 0;
    }
    if(!strcmp(name,"foreign-thread-free")){
        assert(!rc && s.connections==1 && s.queued && s.clean_completion && !s.faults && !s.ap_consumed && s.sender_tid==syscall(SYS_gettid));
        vpc_thread_go=1;assert(!pthread_create(&vpc_reply_thread,0,vpc_thread_release,0));assert(!pthread_join(vpc_reply_thread,0));
        s=vpc_snapshot();assert(s.clean_completion && !s.faults && !s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages && vpc_final->released);
        vpc_finish();return 0;
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") || !strcmp(name,"fork-held") ||
        !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"repeat") || !strcmp(name,"request-free-fail") || !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault");
    if(success){
        assert(!rc && s.connections==1 && s.queued && vpc_allocs==3 && vpc_sends==1);vpc_pins(0,0,0);
        if(vpc_request_error)assert(s.faults && !s.clean_completion && s.retained_request==vpc_request->data && !vpc_request->released);
        else if(vpc_queued_fault)assert(!s.clean_completion && s.faults && vpc_request->released && s.request_freed);
        else assert(s.clean_completion && !s.faults && vpc_request->released && s.request_freed);
        if(!vpc_inline){
            if(!strcmp(name,"wrong-owner")){int f=77;assert(full_vef_pinmem_control_connection_release(vpc_caller^1u,vpc_final->data,vpc_free,vpc_record,&f) && f==-1021 && !vpc_final->attempts);}
            if(!strcmp(name,"reply-free-fail")){int f=77;vpc_reply_error=1;assert(full_vef_pinmem_control_connection_release(vpc_caller,vpc_final->data,vpc_free,vpc_record,&f) && f==-59);vpc_reply_error=0;}
            int f=77;assert(full_vef_pinmem_control_connection_release(vpc_caller,vpc_final->data,vpc_free,vpc_record,&f) && !f);
        }
        s=vpc_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages);
        if(vpc_recursive_free || vpc_queued_fault || vpc_request_error || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        int f=77;assert(!full_vef_pinmem_control_connection_release(vpc_caller,vpc_final->data,vpc_free,vpc_record,&f) && f==77);
        if(!strcmp(name,"repeat")){vpc_request=vpc_new_request();assert(vpc_dispatch(&f) && f==-1021 && vpc_allocs==3 && vpc_sends==1 && !vpc_request->released);}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !vpc_request->released && !vpc_request->attempts && !s.retained_request);
        if(vpc_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        if(vpc_event_fault || vpc_mutate_request)assert(s.event8_pending==1 && !s.event8_consumed && s.retained_messages==1 && s.retained_cleanup==s.event8_answer && !cm_meta(s.event8_answer)->attempts && !vpc_sends);
        if(vpc_duplicate_event)assert(s.event8_consumed==1 && !s.event8_pending && !vpc_sends);
        unsigned int allocations=vpc_allocs;int f=77;assert(vpc_dispatch(&f) && f==-1021 && vpc_allocs==allocations);
        assert(!cm_free(FULL_VEF_CP,vpc_request->data));struct full_vef_pinmem_control_connection_snapshot after=vpc_snapshot();assert(!memcmp(&s,&after,sizeof s));
    }
    struct full_vef_pinmem_control_connection_snapshot before_init=vpc_snapshot();assert(!full_vef_pinmem_control_connection_owner_init());
    struct full_vef_pinmem_control_connection_snapshot after_init=vpc_snapshot();assert(!memcmp(&before_init,&after_init,sizeof before_init));
    vpc_finish();return 0;
}
