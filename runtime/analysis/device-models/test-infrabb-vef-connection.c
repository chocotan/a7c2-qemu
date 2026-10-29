/* SPDX-License-Identifier: MIT */
/* Real predecessor composition; byte-array pool, not VM evidence. */
#define FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN control_edge_prerequisite_main
#include "test-imaging-control-connection.c"
#undef FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN
#include "imaging-adf-connection.h"
#include "adf-device.h"
#include "infrabb-vef-connection.h"
#include "pin-connection.h"
#include "pinmem-device.h"
#include "vef-path-device.h"
static const unsigned int iv_s[4]={0,2,1,0x9284074a},iv_p[4]={0,1,1,0x905a0048};
static struct connect_message *iv_request,*iv_final,*iv_seed_queued;
static unsigned int iv_caller=0x81ce1234,iv_allocs,iv_sends,iv_callbacks,iv_bad_alloc,iv_bad_kind,iv_bad_source,iv_corrupt,iv_offset;
static int iv_inline,iv_send_error,iv_request_error,iv_reply_error,iv_cleanup_error,iv_recursive,iv_mismatch,iv_resource_busy;
static int iv_threaded,iv_thread_error,iv_thread_started,iv_thread_go,iv_recursive_free,iv_publish_fault;
static pthread_t iv_reply_thread;
static pthread_mutex_t iv_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t iv_thread_condition=PTHREAD_COND_INITIALIZER;
static unsigned int iv_prepared,iv_written,iv_consumed,iv_retired,iv_returned,iv_order;
static struct full_imaging_pin_connection_snapshot iv_first_before;
static struct full_imaging_control_connection_snapshot iv_control_before;
static struct full_imaging_adf_connection_snapshot iv_audio_before;
static struct pin_connection_snapshot iv_old_before;
static struct full_vef_path_snapshot iv_path_before;
static struct full_adf_set_input_snapshot iv_input_before;
static struct pin_control_snapshot iv_pool_before;
static const struct full_imaging_io iv_io;
static const struct full_adf_proc_guard iv_guard;
static struct full_infrabb_vef_connection_snapshot iv_snapshot(void){
    struct full_infrabb_vef_connection_snapshot s;full_infrabb_vef_connection_snapshot(&s);return s;
}
static int iv_seed_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){assert(count==1);*out=cm_new(n,owner,ALLOCATOR_SOURCE)->data;return 0;}
static int iv_seed_send(unsigned int owner,void *p){assert(cm_meta(p)->owner==owner && !iv_seed_queued);iv_seed_queued=cm_meta(p);return 0;}
static const struct full_imaging_io iv_seed_io={iv_seed_allocate,cm_free,cm_set,iv_seed_send,cm_size,cm_source,get_record};
static void iv_get(unsigned int sid,const unsigned int key[4]){
    get_destination=0x8a0bc001u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    int rc=77,handled=0;
    if(sid==FULL_VEF_CP)handled=full_vef_dispatch(sid,m->data,&iv_seed_io,1,&rc);
    else if(sid==FULL_PINMEM_CP)handled=full_pinmem_dispatch(sid,m->data,&iv_seed_io,1,&rc);
    else if(sid==NATIVE_INFRAIMAGING_CP)handled=native_infraimaging_dispatch(sid,m->data,&iv_seed_io,1,&rc);
    else if(sid==FULL_ADF_CP)handled=full_adf_dispatch(sid,m->data,&iv_seed_io,1,&rc);
    else handled=native_infrabb_dispatch(sid,m->data,&iv_seed_io,1,&rc);
    assert(handled && !rc && m->released && iv_seed_queued);
    for(unsigned int i=0;i<3;i++)assert(ct32(iv_seed_queued->data+32+4*i)==key[i]);
    assert(ct32(iv_seed_queued->data+44)==1 && ct32(iv_seed_queued->data+48)==sid);
    int freed=77;
    if(sid==FULL_VEF_CP)handled=full_vef_release_reply(get_destination,iv_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==FULL_PINMEM_CP)handled=full_pinmem_release_reply(get_destination,iv_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==NATIVE_INFRAIMAGING_CP)handled=native_infraimaging_release_reply(get_destination,iv_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==FULL_ADF_CP)handled=full_adf_release_reply(get_destination,iv_seed_queued->data,cm_free,get_record,&freed);
    else handled=native_infrabb_release_reply(get_destination,iv_seed_queued->data,cm_free,get_record,&freed);
    assert(handled && !freed);iv_seed_queued=0;
}
static void iv_third_history(void){
    const unsigned int s[4]={3,2,0,NATIVE_INFRAIMAGING_CP},p[4]={3,1,0,FULL_ADF_CP};
    iv_get(NATIVE_INFRAIMAGING_CP,s);iv_get(FULL_ADF_CP,p);
    assert(!full_imaging_adf_connection_owner_init());
    struct connect_message *m=cm_new(64,NATIVE_INFRAIMAGING_CP,iv_caller);ctframe(m->data,64,1,2);ctput32(m->data,iv_caller);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,s[i]);ctput32(m->data+48+4*i,p[i]);}
    const struct full_adf_proc_guard g={reserve,release_guard};int rc=77;
    assert(full_imaging_adf_connection_dispatch(NATIVE_INFRAIMAGING_CP,m->data,&iv_seed_io,&g,1,&rc) && !rc && m->released && iv_seed_queued);
    int freed=77;assert(full_imaging_adf_connection_release(iv_caller,iv_seed_queued->data,cm_free,get_record,&freed) && !freed);iv_seed_queued=0;
}
static void iv_old_history(void){
    const unsigned int s[4]={0,2,3,FULL_VEF_CP},p[4]={0,1,1,FULL_PINMEM_CP};iv_get(FULL_VEF_CP,s);iv_get(FULL_PINMEM_CP,p);
    struct connect_message *m=cm_new(64,FULL_VEF_CP,iv_caller);ctframe(m->data,64,1,2);ctput32(m->data,iv_caller);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,s[i]);ctput32(m->data+48+4*i,p[i]);}
    int rc=77;assert(full_pin_connection_dispatch(FULL_VEF_CP,m->data,&iv_seed_io,2,&rc) && !rc && m->released && iv_seed_queued);
    int freed=77;assert(full_pin_connection_release(iv_caller,iv_seed_queued->data,cm_free,get_record,&freed) && !freed);iv_seed_queued=0;
    static const unsigned char wire[10]={0x0d,0x20,0x49,1,10,0,1,0x80,1,0};
    m=cm_new(10,FULL_VEF_PATH_INPUT,iv_caller);memcpy(m->data,wire,10);
    const struct full_vef_path_guard g={reserve,release_guard};
    assert(!full_vef_path_owner_init());assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,m->data,&iv_seed_io,&g,1,&rc) && !rc && m->released && iv_seed_queued);
    assert(full_vef_path_release_reply(iv_caller,iv_seed_queued->data,cm_free,get_record,&freed) && !freed);iv_seed_queued=0;
}
static void iv_save(void){
    full_imaging_pin_connection_snapshot(&iv_first_before);full_imaging_control_connection_snapshot(&iv_control_before);
    full_imaging_adf_connection_snapshot(&iv_audio_before);full_pin_connection_snapshot(&iv_old_before);
    full_vef_path_snapshot(&iv_path_before);full_adf_set_input_snapshot(&iv_input_before);pin_control_snapshot(&iv_pool_before);
}
static void iv_preserved(void){
    if(!iv_first_before.connections)return;
    struct full_imaging_pin_connection_snapshot f;full_imaging_pin_connection_snapshot(&f);assert(!memcmp(&f,&iv_first_before,sizeof f));
    struct full_imaging_control_connection_snapshot c;full_imaging_control_connection_snapshot(&c);assert(!memcmp(&c,&iv_control_before,sizeof c));
    struct full_imaging_adf_connection_snapshot a;full_imaging_adf_connection_snapshot(&a);assert(!memcmp(&a,&iv_audio_before,sizeof a));
    struct pin_connection_snapshot o;full_pin_connection_snapshot(&o);assert(!memcmp(&o,&iv_old_before,sizeof o));
    struct full_vef_path_snapshot v;full_vef_path_snapshot(&v);assert(!memcmp(&v,&iv_path_before,sizeof v));
    struct full_adf_set_input_snapshot i;full_adf_set_input_snapshot(&i);assert(!memcmp(&i,&iv_input_before,sizeof i));
    assert(iv_input_before.ab_failures==1 && !iv_input_before.software_s && !iv_input_before.ab_register_writes);out_preserved_failure();out_check_shadow();
}
static void iv_callback(void){assert(host_pid==getpid());iv_callbacks++;(void)iv_snapshot();iv_preserved();if(held)guarded();}
static unsigned int iv_size(void *p){iv_callback();return cm_size(p);}
static unsigned int iv_source(void *p){iv_callback();return cm_source(p);}
static int iv_free(unsigned int owner,void *p){
    iv_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==iv_request && iv_request_error)return -53;
    if(m==iv_final && iv_reply_error)return -59;
    if(m->allocation && m!=iv_final && iv_cleanup_error)return -47;
    if(m==iv_final && iv_recursive_free){int rc=77;unsigned int attempts=m->attempts;
        assert(full_infrabb_vef_connection_release(owner,p,iv_free,0,&rc) && rc==-1021 && m->attempts==attempts);}
    cm_dispose(m);return 0;
}
static void iv_set(void *p,unsigned int sid){
    iv_callback();struct connect_message *m=cm_meta(p);m->source=m->allocation==iv_bad_source?1234:sid;
    if(m->allocation==iv_corrupt)m->data[iv_offset]^=1;
}
static int iv_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    iv_callback();assert(held && owner==iv_caller && count==1);iv_allocs++;
    static const unsigned int sizes[10]={64,72,36,152,152,80,216,216,216,56};assert(iv_allocs<=10 && n==sizes[iv_allocs-1]);
    if(iv_allocs==iv_bad_alloc){
        if(iv_bad_kind==1){*out=0;return -41;}if(iv_bad_kind==2){*out=0;return 0;}if(iv_bad_kind==3){*out=iv_request->data;return 0;}
        if(iv_bad_kind==6){assert(iv_allocs==2);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=iv_allocs;*out=m->data;
    if(iv_allocs==iv_bad_alloc){if(iv_bad_kind==4)m->bytes=n-1;if(iv_bad_kind==5)return -43;}
    return 0;
}
static int iv_reserve(void){iv_callback();if(iv_resource_busy)return -EBUSY;return reserve();}
static void iv_release_guard(void){iv_callback();assert(held && iv_snapshot().guard_held);release_guard();}
static void iv_record(const char *tag,const char *text){
    iv_callback();fprintf(stdout,"%s%s\n",tag,text);iv_order++;
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONNECT_COMMAND_PREPARED ")){assert(iv_snapshot().command_prepared);iv_prepared=iv_order;}
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONNECT_FORMAT_WRITTEN ")){
        assert(iv_prepared);iv_written=iv_order;
        if(iv_mismatch)connect_memory[0x48]^=1;
    }
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONNECT_FORMAT_CONSUMED ")){assert(iv_written && iv_snapshot().format.matches);iv_consumed=iv_order;}
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONNECT_BUFFER_RETIRED ")){assert(iv_consumed && iv_snapshot().buffer_freed);iv_retired=iv_order;}
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONNECT_COMMAND_RETURNED ")){assert(iv_retired && !iv_snapshot().local_commands_inflight);iv_returned=iv_order;}
    if(iv_publish_fault && !strcmp(tag,"FULL_INFRABB_VEF_CONNECT_REPLY_QUEUED ")){int rc=77;
        assert(full_infrabb_vef_connection_release(iv_caller^1u,iv_final->data,iv_free,0,&rc) && rc==-1021);}
    if(iv_recursive && !strcmp(tag,"FULL_INFRABB_VEF_CONNECT_REQUEST ")){int rc=77;
        assert(full_infrabb_vef_connection_dispatch(0x9284074a,iv_request->data,&iv_io,&iv_guard,1,&rc) && rc==-1021);assert(iv_snapshot().requests==1);}
}
static int iv_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&iv_thread_mutex));iv_thread_started=1;assert(!pthread_cond_signal(&iv_thread_condition));
    while(!iv_thread_go)assert(!pthread_cond_wait(&iv_thread_condition,&iv_thread_mutex));
    assert(!pthread_mutex_unlock(&iv_thread_mutex));return iv_thread_error?-59:cm_free(owner,p);
}
static void *iv_thread_release(void *unused){
    (void)unused;int rc=77;assert(full_infrabb_vef_connection_release(iv_caller,iv_final->data,iv_thread_free,0,&rc));
    assert(rc==(iv_thread_error?-59:0));return 0;
}
static int iv_send(unsigned int owner,void *p){
    iv_callback();struct full_infrabb_vef_connection_snapshot s=iv_snapshot();
    iv_final=cm_meta(p);assert(owner==iv_caller && iv_final->allocation==10 && iv_final->bytes==56 && iv_final->source==0x9284074a);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,iv_s[i]);assert(!memcmp(p,expected,56));
    assert(s.live_reply==p && s.format_consumed && s.buffer_freed && s.buffer_closed && s.buffer_transferred && s.predecessor_preserved && !s.faults);
    assert(iv_prepared<iv_written && iv_written<iv_consumed && iv_consumed<iv_retired && iv_retired<iv_returned);
    assert(!s.local_commands_inflight && s.local_commands_returned==1 && s.command_prepared && s.command_executed);
    struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(pool.allocations==iv_pool_before.allocations+1 && pool.releases==pool.allocations && !pool.live && !pool.faults);
    assert(pool.creator_closes==iv_pool_before.creator_closes+1 && pool.creator_transfers==iv_pool_before.creator_transfers+1 && pool.shares==iv_pool_before.shares);
    assert(pool.consumer_closes==iv_pool_before.consumer_closes+1 && pool.consumer_releases==iv_pool_before.consumer_releases+1);
    iv_sends++;
    if(iv_threaded){assert(!pthread_mutex_lock(&iv_thread_mutex));assert(!pthread_create(&iv_reply_thread,0,iv_thread_release,0));
        while(!iv_thread_started)assert(!pthread_cond_wait(&iv_thread_condition,&iv_thread_mutex));
        assert(!pthread_mutex_unlock(&iv_thread_mutex));}
    if(iv_inline){int rc=77;assert(full_infrabb_vef_connection_release(owner,p,iv_free,iv_record,&rc) && !rc);}return iv_send_error;
}
static const struct full_imaging_io iv_io={iv_allocate,iv_free,iv_set,iv_send,iv_size,iv_source,iv_record};
static const struct full_adf_proc_guard iv_guard={iv_reserve,iv_release_guard};
static struct connect_message *iv_new_request(void){
    struct connect_message *m=cm_new(64,0x9284074a,iv_caller);ctframe(m->data,64,1,2);ctput32(m->data,iv_caller);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,iv_s[i]);ctput32(m->data+48+4*i,iv_p[i]);}return m;
}
static int iv_dispatch(int *rc){return full_infrabb_vef_connection_dispatch(0x9284074a,iv_request->data,&iv_io,&iv_guard,1,rc);}
static void iv_finish(void){iv_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("INFRABB_VEF_CONNECTION_HOST_TEST_PASS");}
#ifndef FULL_INFRABB_VEF_CONNECTION_TEST_MAIN
#define FULL_INFRABB_VEF_CONNECTION_TEST_MAIN main
#endif
int FULL_INFRABB_VEF_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    assert(!full_infrabb_vef_connection_owner_init());
    if(!strcmp(name,"dynamic-caller"))iv_caller=0x8fed1023;
    iv_request=iv_new_request();int rc=77;
    if(!strcmp(name,"disabled")){assert(!full_infrabb_vef_connection_dispatch(0x9284074a,iv_request->data,&iv_io,&iv_guard,0,&rc) && rc==77);iv_finish();return 0;}
    if(!strcmp(name,"fork")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(full_infrabb_vef_connection_owner_init()==-1021);assert(!iv_snapshot().initialized);
            assert(iv_dispatch(&rc) && rc==-1021 && !iv_callbacks);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));iv_finish();return 0;}
    if(!strcmp(name,"invalid-source")){iv_request->source^=1;assert(iv_dispatch(&rc) && rc==-1021 && !iv_snapshot().requests && !iv_snapshot().faults);iv_finish();return 0;}
    assert(iv_dispatch(&rc) && rc==-1021);struct full_infrabb_vef_connection_snapshot early=iv_snapshot();
    assert(!early.requests && !early.faults && early.unadmitted_count==1 && !iv_allocs && !iv_request->released);
    if(!strcmp(name,"no-prior")){assert(iv_dispatch(&rc) && rc==-1021 && iv_snapshot().unadmitted_count==2);iv_finish();return 0;}
    char *old[]={"test","normal",argv[2],0};assert(!control_edge_prerequisite_main(3,old));alarm(30);
    for(unsigned int i=0;i<cm_count;i++)assert(cm[i].released);
    cm_count=0;
    /* Invoke the actual third-edge dispatcher, then the actual old VEF/PinMem
     * and NoMem owners; no predecessor completion snapshot is stubbed. */
    iv_third_history();iv_old_history();iv_get(0x9284074a,iv_s);iv_get(FULL_VEF_CP,iv_p);iv_save();iv_request=iv_new_request();
    if(!strcmp(name,"resource-busy"))iv_resource_busy=1;
    if(!strcmp(name,"send-fail"))iv_send_error=-61;
    if(!strcmp(name,"inline-free"))iv_inline=1;
    if(!strcmp(name,"inline-send-fail")){iv_inline=1;iv_send_error=-61;}
    if(!strcmp(name,"request-free-fail"))iv_request_error=1;
    if(!strcmp(name,"recursive"))iv_recursive=1;
    if(!strcmp(name,"recursive-free"))iv_recursive_free=1;
    if(!strcmp(name,"queued-fault"))iv_publish_fault=1;
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){
        iv_threaded=1;iv_send_error=-61;iv_thread_error=!strcmp(name,"in-flight-free-fail");}
    if(!strcmp(name,"mismatch"))iv_mismatch=1;
    if(!strcmp(name,"cleanup-fail"))iv_cleanup_error=1;
    unsigned int nth=0,kind=0,offset=0;
    if(sscanf(name,"alloc-%u-%u",&nth,&kind)==2){iv_bad_alloc=nth;iv_bad_kind=kind;}
    if(sscanf(name,"source-%u",&nth)==1)iv_bad_source=nth;
    if(sscanf(name,"wire-%u-%u",&nth,&offset)==2){iv_corrupt=nth;iv_offset=offset;}
    assert(iv_dispatch(&rc));struct full_infrabb_vef_connection_snapshot s=iv_snapshot();
    assert(!held && !s.busy && !s.guard_held && s.owner_pid==getpid());
    if(iv_resource_busy){assert(rc==-1021 && !s.requests && !s.faults && s.unadmitted_count==2 && !iv_sends && !iv_allocs);iv_finish();return 0;}
    assert(s.requests==1 && s.unadmitted_count==1);
    if(iv_threaded){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.live_reply==iv_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !iv_final->released && !iv_final->attempts);
        assert(!pthread_mutex_lock(&iv_thread_mutex));iv_thread_go=1;assert(!pthread_cond_signal(&iv_thread_condition));
        assert(!pthread_mutex_unlock(&iv_thread_mutex));assert(!pthread_join(iv_reply_thread,0));s=iv_snapshot();
        assert(!s.releasing_reply && s.faults && !s.clean_completion);
        if(iv_thread_error){assert(s.live_reply==iv_final->data && s.retained_messages==1 && !s.ap_consumed && !iv_final->released);
            int f=77;assert(full_infrabb_vef_connection_release(iv_caller,iv_final->data,iv_free,iv_record,&f) && !f);}
        s=iv_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages && iv_final->released);
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") ||
        !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"repeat") || !strcmp(name,"request-free-fail") ||
        !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault");
    if(success){
        assert(!rc && s.connections==1 && s.queued && iv_allocs==10 && iv_sends==1 && s.command_executed && s.format.matches==1 && s.buffer_freed);
        if(iv_request_error)assert(s.faults && !s.clean_completion && s.retained_request==iv_request->data && !iv_request->released);
        else if(iv_publish_fault)assert(!s.clean_completion && s.faults && iv_request->released && s.request_freed);
        else assert(s.clean_completion && !s.faults && iv_request->released && s.request_freed);
        if(!iv_inline){
            if(!strcmp(name,"wrong-owner")){int f=77;assert(full_infrabb_vef_connection_release(iv_caller^1u,iv_final->data,iv_free,iv_record,&f) && f==-1021 && !iv_final->attempts);}
            if(!strcmp(name,"reply-free-fail")){int f=77;iv_reply_error=1;assert(full_infrabb_vef_connection_release(iv_caller,iv_final->data,iv_free,iv_record,&f) && f==-59);iv_reply_error=0;}
            int f=77;assert(full_infrabb_vef_connection_release(iv_caller,iv_final->data,iv_free,iv_record,&f) && !f);
        }
        s=iv_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages);
        if(iv_recursive_free || iv_publish_fault)assert(s.faults && !s.clean_completion);
        if(!strcmp(name,"repeat")){iv_request=iv_new_request();int f=77;assert(iv_dispatch(&f) && f==-1021 && iv_allocs==10 && iv_sends==1 && !iv_request->released);}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !iv_request->released && !s.retained_request);
        if(iv_mismatch){struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(pool.live==1 && s.buffer_opened && !s.buffer_freed && !s.buffer_closed && !iv_sends);}
        if(iv_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        unsigned int allocations=iv_allocs;int f=77;assert(iv_dispatch(&f) && f==-1021 && iv_allocs==allocations);
    }
    iv_finish();return 0;
}
