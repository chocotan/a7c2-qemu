/* SPDX-License-Identifier: MIT */
/* Actual first four providers and retired byte-array backing; no VM evidence. */
#define FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN vc_control_prerequisite_main
#include "test-imaging-control-connection.c"
#undef FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN
#include "imaging-adf-connection.h"
#include "adf-device.h"
#include "infrabb-vef-connection.h"
#include "infrabb-vef-control-connection.h"
#include "pin-connection.h"
#include "pinmem-device.h"
#include "vef-path-device.h"
static const unsigned int vc_s[4]={8,2,0,NATIVE_INFRABB_CP},vc_p[4]={8,1,0,FULL_VEF_CP};
static struct connect_message *vc_request,*vc_final,*vc_seed_queued;
static unsigned int vc_caller=0x81ce1234,vc_allocs,vc_sends,vc_callbacks,vc_bad_alloc,vc_bad_kind,vc_bad_source,vc_corrupt,vc_offset;
static int vc_inline,vc_send_error,vc_request_error,vc_reply_error,vc_cleanup_error,vc_recursive,vc_busy;
static int vc_threaded,vc_thread_error,vc_thread_started,vc_thread_go,vc_recursive_free,vc_publish_fault,vc_concurrent_get,vc_fork_held;
static pthread_t vc_reply_thread;
static pthread_mutex_t vc_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t vc_thread_condition=PTHREAD_COND_INITIALIZER;
static unsigned int vc_order,vc_peer_request,vc_peer_reply,vc_source_hook,vc_sink_hook;
static int vc_have_history;
static struct full_imaging_pin_connection_snapshot vc_first_before;
static struct full_imaging_control_connection_snapshot vc_control_before;
static struct full_imaging_adf_connection_snapshot vc_audio_before;
static struct full_infrabb_vef_connection_snapshot vc_fourth_before;
static struct pin_connection_snapshot vc_old_before;
static struct full_vef_path_snapshot vc_path_before;
static struct full_adf_set_input_snapshot vc_input_before;
static struct full_adf_set_output_snapshot vc_output_before;
static struct full_adf_proc_snapshot vc_proc_before;
static struct full_bb_set_mode_snapshot vc_bb_before;
static struct pin_control_snapshot vc_pool_before;
static struct full_vef_snapshot vc_imaging_before,vc_source_before,vc_peer_before,vc_adf_before,vc_pinmem_before;
static unsigned char vc_memory_before[PIN_CONTROL_CAPACITY];
static const struct full_imaging_io vc_io;
static const struct full_adf_proc_guard vc_guard;
static struct full_infrabb_vef_control_connection_snapshot vc_snapshot(void){
    struct full_infrabb_vef_control_connection_snapshot s;full_infrabb_vef_control_connection_snapshot(&s);return s;
}
static int vc_seed_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){assert(count==1);*out=cm_new(n,owner,ALLOCATOR_SOURCE)->data;return 0;}
static int vc_seed_send(unsigned int owner,void *p){assert(cm_meta(p)->owner==owner && !vc_seed_queued);vc_seed_queued=cm_meta(p);return 0;}
static const struct full_imaging_io vc_seed_io={vc_seed_allocate,cm_free,cm_set,vc_seed_send,cm_size,cm_source,get_record};
static void vc_get(unsigned int sid,const unsigned int key[4],unsigned int status,int leave){
    get_destination=0x8a0bc001u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    int rc=77,handled=0;
    if(sid==FULL_VEF_CP)handled=full_vef_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else if(sid==FULL_PINMEM_CP)handled=full_pinmem_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else if(sid==NATIVE_INFRAIMAGING_CP)handled=native_infraimaging_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else if(sid==FULL_ADF_CP)handled=full_adf_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else handled=native_infrabb_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    assert(handled && !rc && m->released && vc_seed_queued);
    for(unsigned int i=0;i<3;i++)assert(ct32(vc_seed_queued->data+32+4*i)==key[i]);
    assert(ct32(vc_seed_queued->data+44)==status && ct32(vc_seed_queued->data+48)==sid);
    if(leave)return;
    int freed=77;
    if(sid==FULL_VEF_CP)handled=full_vef_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==FULL_PINMEM_CP)handled=full_pinmem_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==NATIVE_INFRAIMAGING_CP)handled=native_infraimaging_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==FULL_ADF_CP)handled=full_adf_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else handled=native_infrabb_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    assert(handled && !freed);vc_seed_queued=0;
}
static struct connect_message *vc_pair_request(unsigned int sid,const unsigned int *s,const unsigned int *p){
    struct connect_message *m=cm_new(64,sid,vc_caller);ctframe(m->data,64,1,2);ctput32(m->data,vc_caller);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,s[i]);ctput32(m->data+48+4*i,p[i]);}return m;
}
static void vc_history(const char *seed,int leave_fourth){
    char *old[]={"test","normal",(char *)seed,0};assert(!vc_control_prerequisite_main(3,old));alarm(30);
    for(unsigned int i=0;i<cm_count;i++)assert(cm[i].released);
    cm_count=0;
    const unsigned int s[4]={3,2,0,NATIVE_INFRAIMAGING_CP},p[4]={3,1,0,FULL_ADF_CP};
    vc_get(NATIVE_INFRAIMAGING_CP,s,1,0);vc_get(FULL_ADF_CP,p,1,0);
    assert(!full_imaging_adf_connection_owner_init());
    struct connect_message *m=vc_pair_request(NATIVE_INFRAIMAGING_CP,s,p);
    const struct full_adf_proc_guard g={reserve,release_guard};int rc=77,freed=77;
    assert(full_imaging_adf_connection_dispatch(NATIVE_INFRAIMAGING_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);
    assert(full_imaging_adf_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);vc_seed_queued=0;
    const unsigned int os[4]={0,2,3,FULL_VEF_CP},op[4]={0,1,1,FULL_PINMEM_CP};
    vc_get(FULL_VEF_CP,os,1,0);vc_get(FULL_PINMEM_CP,op,1,0);m=vc_pair_request(FULL_VEF_CP,os,op);
    assert(full_pin_connection_dispatch(FULL_VEF_CP,m->data,&vc_seed_io,2,&rc) && !rc && m->released && vc_seed_queued);
    assert(full_pin_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);vc_seed_queued=0;
    static const unsigned char wire[10]={0x0d,0x20,0x49,1,10,0,1,0x80,1,0};
    m=cm_new(10,FULL_VEF_PATH_INPUT,vc_caller);memcpy(m->data,wire,10);
    const struct full_vef_path_guard pg={reserve,release_guard};assert(!full_vef_path_owner_init());
    assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,m->data,&vc_seed_io,&pg,1,&rc) && !rc && m->released && vc_seed_queued);
    assert(full_vef_path_release_reply(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);vc_seed_queued=0;
    const unsigned int fs[4]={0,2,1,NATIVE_INFRABB_CP},fp[4]={0,1,1,FULL_VEF_CP};
    vc_get(NATIVE_INFRABB_CP,fs,1,0);vc_get(FULL_VEF_CP,fp,1,0);assert(!full_infrabb_vef_connection_owner_init());
    m=vc_pair_request(NATIVE_INFRABB_CP,fs,fp);
    assert(full_infrabb_vef_connection_dispatch(NATIVE_INFRABB_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);
    if(!leave_fourth)assert(full_infrabb_vef_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);
    vc_seed_queued=0;
}
static void vc_save(void){
    full_imaging_pin_connection_snapshot(&vc_first_before);full_imaging_control_connection_snapshot(&vc_control_before);
    full_imaging_adf_connection_snapshot(&vc_audio_before);full_infrabb_vef_connection_snapshot(&vc_fourth_before);
    full_pin_connection_snapshot(&vc_old_before);full_vef_path_snapshot(&vc_path_before);full_adf_proc_snapshot(&vc_proc_before);
    full_adf_set_input_snapshot(&vc_input_before);full_adf_set_output_snapshot(&vc_output_before);full_bb_set_mode_snapshot(&vc_bb_before);
    pin_control_snapshot(&vc_pool_before);native_infraimaging_snapshot(&vc_imaging_before);native_infrabb_snapshot(&vc_source_before);
    full_vef_snapshot(&vc_peer_before);full_adf_snapshot(&vc_adf_before);full_pinmem_snapshot(&vc_pinmem_before);
    memcpy(vc_memory_before,connect_memory,sizeof vc_memory_before);vc_have_history=1;
}
static void vc_preserved(void){
    if(!vc_have_history)return;
    struct full_imaging_pin_connection_snapshot f;full_imaging_pin_connection_snapshot(&f);assert(!memcmp(&f,&vc_first_before,sizeof f));
    struct full_imaging_control_connection_snapshot c;full_imaging_control_connection_snapshot(&c);assert(!memcmp(&c,&vc_control_before,sizeof c));
    struct full_imaging_adf_connection_snapshot a;full_imaging_adf_connection_snapshot(&a);assert(!memcmp(&a,&vc_audio_before,sizeof a));
    struct full_infrabb_vef_connection_snapshot v;full_infrabb_vef_connection_snapshot(&v);assert(!memcmp(&v,&vc_fourth_before,sizeof v));
    struct pin_connection_snapshot o;full_pin_connection_snapshot(&o);assert(!memcmp(&o,&vc_old_before,sizeof o));
    struct full_vef_path_snapshot path;full_vef_path_snapshot(&path);assert(!memcmp(&path,&vc_path_before,sizeof path));
    struct full_adf_proc_snapshot proc;full_adf_proc_snapshot(&proc);assert(!memcmp(&proc,&vc_proc_before,sizeof proc));
    struct full_adf_set_input_snapshot i;full_adf_set_input_snapshot(&i);assert(!memcmp(&i,&vc_input_before,sizeof i));
    struct full_adf_set_output_snapshot out;full_adf_set_output_snapshot(&out);assert(!memcmp(&out,&vc_output_before,sizeof out));
    struct full_bb_set_mode_snapshot bb;full_bb_set_mode_snapshot(&bb);assert(!memcmp(&bb,&vc_bb_before,sizeof bb));
    struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(!memcmp(&pool,&vc_pool_before,sizeof pool));
    assert(!memcmp(connect_memory,vc_memory_before,sizeof connect_memory));
    struct full_vef_snapshot im,adf,pm;native_infraimaging_snapshot(&im);full_adf_snapshot(&adf);full_pinmem_snapshot(&pm);
    assert(!memcmp(&im,&vc_imaging_before,sizeof im) && !memcmp(&adf,&vc_adf_before,sizeof adf) && !memcmp(&pm,&vc_pinmem_before,sizeof pm));
    assert(vc_input_before.ab_failures==1 && !vc_input_before.software_s && !vc_input_before.ab_register_writes);out_preserved_failure();out_check_shadow();
}
static void vc_pins(unsigned int source,unsigned int peer,unsigned int pending){
    struct full_vef_snapshot a,b;native_infrabb_snapshot(&a);full_vef_snapshot(&b);
    assert(a.pins[9].state==source && b.pins[14].state==peer && a.pending==pending && !b.pending);
    if(source!=1)assert(!memcmp(a.pins[9].peer,vc_p,sizeof vc_p));
    if(peer!=1)assert(!memcmp(b.pins[14].peer,vc_s,sizeof vc_s));
    a.pins[9]=vc_source_before.pins[9];a.pending=vc_source_before.pending;b.pins[14]=vc_peer_before.pins[14];
    assert(!memcmp(&a,&vc_source_before,sizeof a) && !memcmp(&b,&vc_peer_before,sizeof b));
}
static void vc_callback(void){assert(host_pid==getpid());vc_callbacks++;(void)vc_snapshot();vc_preserved();if(held)guarded();}
static unsigned int vc_size(void *p){vc_callback();return cm_size(p);}
static unsigned int vc_source(void *p){vc_callback();return cm_source(p);}
static int vc_free(unsigned int owner,void *p){
    vc_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==vc_request && vc_request_error)return -53;
    if(m==vc_final && vc_reply_error)return -59;
    if(m->allocation && m!=vc_final && vc_cleanup_error)return -47;
    if(m==vc_final && vc_recursive_free){int rc=77;unsigned int attempts=m->attempts;
        assert(full_infrabb_vef_control_connection_release(owner,p,vc_free,0,&rc) && rc==-1021 && m->attempts==attempts);}
    cm_dispose(m);return 0;
}
static void vc_set(void *p,unsigned int sid){
    vc_callback();struct connect_message *m=cm_meta(p);m->source=m->allocation==vc_bad_source?1234:sid;
    if(m->allocation==vc_corrupt)m->data[vc_offset]^=1;
}
static int vc_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    vc_callback();assert(held && owner==vc_caller && count==1);vc_allocs++;
    static const unsigned int sizes[3]={64,72,56};assert(vc_allocs<=3 && n==sizes[vc_allocs-1]);
    if(vc_allocs==vc_bad_alloc){
        if(vc_bad_kind==1){*out=0;return -41;}if(vc_bad_kind==2){*out=0;return 0;}if(vc_bad_kind==3){*out=vc_request->data;return 0;}
        if(vc_bad_kind==6){assert(vc_allocs==2);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=vc_allocs;*out=m->data;
    if(vc_allocs==vc_bad_alloc){if(vc_bad_kind==4)m->bytes=n-1;if(vc_bad_kind==5)return -43;}return 0;
}
static int vc_reserve(void){vc_callback();if(vc_busy)return -EBUSY;return reserve();}
static void vc_release_guard(void){vc_callback();assert(held && vc_snapshot().guard_held);release_guard();}
static void vc_record(const char *tag,const char *text){
    vc_callback();fprintf(stdout,"%s%s\n",tag,text);vc_order++;
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_PEER_REQUEST ")){vc_pins(2,1,1);vc_peer_request=vc_order;}
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_PEER_REPLY ")){vc_pins(2,0,1);vc_peer_reply=vc_order;}
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_SOURCE_POSTHOOK ")){vc_pins(0,0,1);vc_source_hook=vc_order;assert(vc_snapshot().source_marker_skipped);}
    if(!strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_POSTHOOK_NO_FORMAT ")){
        vc_pins(0,0,1);vc_sink_hook=vc_order;assert(vc_snapshot().peer_ordinal==14 && !vc_snapshot().callback_selected);
        if(vc_concurrent_get)vc_get(FULL_VEF_CP,vc_p,0,0);
    }
    if(vc_publish_fault && !strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_REPLY_QUEUED ")){int rc=77;
        assert(full_infrabb_vef_control_connection_release(vc_caller^1u,vc_final->data,vc_free,0,&rc) && rc==-1021);}
    if(vc_recursive && !strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_REQUEST ")){int rc=77;
        assert(full_infrabb_vef_control_connection_dispatch(NATIVE_INFRABB_CP,vc_request->data,&vc_io,&vc_guard,1,&rc) && rc==-1021);assert(vc_snapshot().requests==1);}
    if(vc_fork_held && !strcmp(tag,"FULL_INFRABB_VEF_CONTROL_CONNECT_REQUEST ")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);int rc=77;assert(!vc_snapshot().initialized);
            assert(full_infrabb_vef_control_connection_owner_init()==-1021);
            assert(full_infrabb_vef_control_connection_dispatch(NATIVE_INFRABB_CP,vc_request->data,&vc_io,&vc_guard,1,&rc) && rc==-1021);
            assert(!full_infrabb_vef_control_connection_release(vc_caller,vc_request->data,vc_free,vc_record,&rc));_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
}
static int vc_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&vc_thread_mutex));vc_thread_started=1;assert(!pthread_cond_signal(&vc_thread_condition));
    while(!vc_thread_go)assert(!pthread_cond_wait(&vc_thread_condition,&vc_thread_mutex));
    assert(!pthread_mutex_unlock(&vc_thread_mutex));return vc_thread_error?-59:cm_free(owner,p);
}
static void *vc_thread_release(void *unused){
    (void)unused;int rc=77;assert(full_infrabb_vef_control_connection_release(vc_caller,vc_final->data,vc_thread_free,0,&rc));assert(rc==(vc_thread_error?-59:0));return 0;
}
static int vc_send(unsigned int owner,void *p){
    vc_callback();struct full_infrabb_vef_control_connection_snapshot s=vc_snapshot();
    vc_final=cm_meta(p);assert(owner==vc_caller && vc_final->allocation==3 && vc_final->bytes==56 && vc_final->source==NATIVE_INFRABB_CP);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,vc_s[i]);assert(!memcmp(p,expected,56));
    assert(s.live_reply==p && s.predecessor_preserved && !s.faults && s.peer_requests==1 && s.peer_replies==1 && s.source_marker_skipped);
    assert(s.source_posthook_checked && s.source_posthook_no_format && s.posthook_checked && s.posthook_no_format && s.peer_ordinal==14 && !s.callback_selected);
    assert(!s.dmm_allocations && !s.notifications && !s.cache_writes && !s.marker_writes && !s.clock_writes && !s.mmio_writes);
    assert(vc_peer_request<vc_peer_reply && vc_peer_reply<vc_source_hook && vc_source_hook<vc_sink_hook);vc_pins(0,0,1);vc_sends++;
    if(vc_threaded){assert(!pthread_mutex_lock(&vc_thread_mutex));assert(!pthread_create(&vc_reply_thread,0,vc_thread_release,0));
        while(!vc_thread_started)assert(!pthread_cond_wait(&vc_thread_condition,&vc_thread_mutex));
        assert(!pthread_mutex_unlock(&vc_thread_mutex));}
    if(vc_inline){int rc=77;assert(full_infrabb_vef_control_connection_release(owner,p,vc_free,vc_record,&rc) && !rc);}return vc_send_error;
}
static const struct full_imaging_io vc_io={vc_allocate,vc_free,vc_set,vc_send,vc_size,vc_source,vc_record};
static const struct full_adf_proc_guard vc_guard={vc_reserve,vc_release_guard};
static int vc_dispatch(int *rc){return full_infrabb_vef_control_connection_dispatch(NATIVE_INFRABB_CP,vc_request->data,&vc_io,&vc_guard,1,rc);}
static void vc_finish(void){vc_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("INFRABB_VEF_CONTROL_CONNECTION_HOST_TEST_PASS");}
int main(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    if(strcmp(name,"uninitialized")){assert(!full_infrabb_vef_control_connection_owner_init());struct full_infrabb_vef_control_connection_snapshot s=vc_snapshot();
        assert(!full_infrabb_vef_control_connection_owner_init());struct full_infrabb_vef_control_connection_snapshot same=vc_snapshot();assert(!memcmp(&s,&same,sizeof s));}
    if(!strcmp(name,"dynamic-caller"))vc_caller=0x8fed1023;
    vc_request=vc_pair_request(NATIVE_INFRABB_CP,vc_s,vc_p);int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"long") || !strcmp(name,"other-BB-type0")){
        if(!strcmp(name,"short"))vc_request->bytes=63;
        if(!strcmp(name,"long"))vc_request->bytes=65;
        if(!strcmp(name,"other-BB-type0")){ctput32(vc_request->data+32,0);ctput32(vc_request->data+48,0);}
        assert(!full_infrabb_vef_control_connection_dispatch(!strcmp(name,"unrelated")?FULL_VEF_CP:NATIVE_INFRABB_CP,vc_request->data,&vc_io,&vc_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!vc_snapshot().requests && !vc_allocs && !vc_request->released);vc_finish();return 0;
    }
    if(!strcmp(name,"fork") || !strcmp(name,"uninitialized")){
        if(!strcmp(name,"uninitialized")){assert(vc_dispatch(&rc) && rc==-1021 && !vc_callbacks);vc_finish();return 0;}
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(full_infrabb_vef_control_connection_owner_init()==-1021);assert(!vc_snapshot().initialized);
            assert(vc_dispatch(&rc) && rc==-1021 && !vc_callbacks);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));vc_finish();return 0;
    }
    if(!strcmp(name,"missing-transport")){
        for(unsigned int i=0;i<6;i++){struct full_imaging_io bad=vc_io;
            if(i==0)bad.allocate=0;else if(i==1)bad.release=0;else if(i==2)bad.send=0;else if(i==3)bad.set_source=0;else if(i==4)bad.size=0;else bad.source=0;
            assert(full_infrabb_vef_control_connection_dispatch(NATIVE_INFRABB_CP,vc_request->data,&bad,&vc_guard,1,&rc) && rc==-1021);}
        assert(!vc_callbacks && !vc_snapshot().requests && !vc_snapshot().faults);vc_finish();return 0;
    }
    if(!strcmp(name,"missing-guard")){
        struct full_adf_proc_guard a={0,vc_release_guard},b={vc_reserve,0};const struct full_adf_proc_guard *guards[]={0,&a,&b};
        for(unsigned int i=0;i<3;i++)assert(full_infrabb_vef_control_connection_dispatch(NATIVE_INFRABB_CP,vc_request->data,&vc_io,guards[i],1,&rc) && rc==-1021);
        assert(!vc_callbacks && !vc_snapshot().requests && !vc_snapshot().faults);vc_finish();return 0;
    }
    if(!strcmp(name,"invalid-source")){vc_request->source^=1;assert(vc_dispatch(&rc) && rc==-1021 && !vc_snapshot().requests && !vc_snapshot().faults);vc_finish();return 0;}
    if(!strcmp(name,"bad-wire")){
        static const unsigned int positions[]={0,4,8,10,12,16,24,26,28,30,32,36,40,44,48,52,56,60,33,37,41,45,49,53,57,61};
        for(unsigned int i=0;i<sizeof positions/sizeof *positions;i++){unsigned int at=positions[i];vc_request->data[at]^=1;
            assert(vc_dispatch(&rc) && rc==-1021);vc_request->data[at]^=1;}
        assert(!vc_snapshot().requests && !vc_snapshot().faults && !vc_allocs);vc_finish();return 0;
    }
    assert(vc_dispatch(&rc) && rc==-1021);struct full_infrabb_vef_control_connection_snapshot early=vc_snapshot();
    assert(!early.requests && !early.faults && early.unadmitted_count==1 && !vc_allocs && !vc_request->released);
    if(!strcmp(name,"no-prior")){assert(vc_dispatch(&rc) && rc==-1021 && vc_snapshot().unadmitted_count==2);vc_finish();return 0;}
    vc_history(argv[2],!strcmp(name,"no-fourth-AP-free"));
    if(strcmp(name,"no-source-get"))vc_get(NATIVE_INFRABB_CP,vc_s,1,0);
    if(strcmp(name,"no-peer-get"))vc_get(FULL_VEF_CP,vc_p,1,!strcmp(name,"live-peer-get"));
    if(!strcmp(name,"no-fourth-AP-free") || !strcmp(name,"live-peer-get") || !strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get")){
        vc_request=vc_pair_request(NATIVE_INFRABB_CP,vc_s,vc_p);assert(vc_dispatch(&rc) && rc==-1021 && !vc_snapshot().requests && !vc_snapshot().faults && !vc_allocs && !vc_request->released);vc_finish();return 0;
    }
    for(unsigned int i=0;i<cm_count;i++)assert(cm[i].released);
    cm_count=0;vc_save();vc_request=vc_pair_request(NATIVE_INFRABB_CP,vc_s,vc_p);
    if(!strcmp(name,"resource-busy"))vc_busy=1;
    if(!strcmp(name,"send-fail"))vc_send_error=-61;
    if(!strcmp(name,"inline-free"))vc_inline=1;
    if(!strcmp(name,"inline-send-fail")){vc_inline=1;vc_send_error=-61;}
    if(!strcmp(name,"request-free-fail"))vc_request_error=1;
    if(!strcmp(name,"recursive"))vc_recursive=1;
    if(!strcmp(name,"fork-held"))vc_fork_held=1;
    if(!strcmp(name,"recursive-free"))vc_recursive_free=1;
    if(!strcmp(name,"queued-fault"))vc_publish_fault=1;
    if(!strcmp(name,"concurrent-peer-get"))vc_concurrent_get=1;
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){vc_threaded=1;vc_send_error=-61;vc_thread_error=!strcmp(name,"in-flight-free-fail");}
    if(!strcmp(name,"cleanup-fail"))vc_cleanup_error=1;
    unsigned int nth=0,kind=0,offset=0;
    if(sscanf(name,"alloc-%u-%u",&nth,&kind)==2){vc_bad_alloc=nth;vc_bad_kind=kind;}
    if(sscanf(name,"source-%u",&nth)==1)vc_bad_source=nth;
    if(sscanf(name,"wire-%u-%u",&nth,&offset)==2){vc_corrupt=nth;vc_offset=offset;}
    assert(vc_dispatch(&rc));struct full_infrabb_vef_control_connection_snapshot s=vc_snapshot();
    assert(!held && !s.busy && !s.guard_held && s.owner_pid==getpid());
    if(vc_busy){assert(rc==-1021 && !s.requests && !s.faults && s.unadmitted_count==2 && !vc_sends && !vc_allocs);vc_finish();return 0;}
    assert(s.requests==1 && s.unadmitted_count==1);
    if(vc_threaded){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.live_reply==vc_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !vc_final->released && !vc_final->attempts);
        assert(!pthread_mutex_lock(&vc_thread_mutex));vc_thread_go=1;assert(!pthread_cond_signal(&vc_thread_condition));
        assert(!pthread_mutex_unlock(&vc_thread_mutex));assert(!pthread_join(vc_reply_thread,0));s=vc_snapshot();assert(!s.releasing_reply && s.faults && !s.clean_completion);
        if(vc_thread_error){assert(s.live_reply==vc_final->data && s.retained_messages==1 && !s.ap_consumed && !vc_final->released);
            int f=77;assert(full_infrabb_vef_control_connection_release(vc_caller,vc_final->data,vc_free,vc_record,&f) && !f);}
        s=vc_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages && vc_final->released);
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"peek-status") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") || !strcmp(name,"fork-held") ||
        !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"repeat") || !strcmp(name,"request-free-fail") || !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault");
    if(success){
        assert(!rc && s.connections==1 && s.queued && vc_allocs==3 && vc_sends==1 && s.posthook_no_format && s.peer_ordinal==14 && s.source_marker_skipped);vc_pins(0,0,0);
        if(vc_request_error)assert(s.faults && !s.clean_completion && s.retained_request==vc_request->data && !vc_request->released);
        else if(vc_publish_fault)assert(!s.clean_completion && s.faults && vc_request->released && s.request_freed);
        else assert(s.clean_completion && !s.faults && vc_request->released && s.request_freed);
        if(!vc_inline){
            if(!strcmp(name,"wrong-owner")){int f=77;assert(full_infrabb_vef_control_connection_release(vc_caller^1u,vc_final->data,vc_free,vc_record,&f) && f==-1021 && !vc_final->attempts);}
            if(!strcmp(name,"reply-free-fail")){int f=77;vc_reply_error=1;assert(full_infrabb_vef_control_connection_release(vc_caller,vc_final->data,vc_free,vc_record,&f) && f==-59);vc_reply_error=0;}
            int f=77;assert(full_infrabb_vef_control_connection_release(vc_caller,vc_final->data,vc_free,vc_record,&f) && !f);
        }
        s=vc_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages);
        if(vc_recursive_free || vc_publish_fault || vc_request_error || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        int f=77;assert(!full_infrabb_vef_control_connection_release(vc_caller,vc_final->data,vc_free,vc_record,&f) && f==77);
        if(!strcmp(name,"peek-status")){vc_get(NATIVE_INFRABB_CP,vc_s,0,0);vc_get(FULL_VEF_CP,vc_p,0,0);}
        if(!strcmp(name,"repeat")){vc_request=vc_pair_request(NATIVE_INFRABB_CP,vc_s,vc_p);assert(vc_dispatch(&f) && f==-1021 && vc_allocs==3 && vc_sends==1 && !vc_request->released);}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !vc_request->released && !vc_request->attempts && !s.retained_request);
        if(vc_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        unsigned int allocations=vc_allocs;int f=77;assert(vc_dispatch(&f) && f==-1021 && vc_allocs==allocations);
        assert(!cm_free(NATIVE_INFRABB_CP,vc_request->data));struct full_infrabb_vef_control_connection_snapshot after=vc_snapshot();assert(!memcmp(&s,&after,sizeof s));
    }
    vc_finish();return 0;
}
