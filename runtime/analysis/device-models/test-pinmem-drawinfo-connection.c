/* SPDX-License-Identifier: MIT */
/* Actual nine-edge fixture and production native type6 tenth edge. */
#define FULL_PINMEM_NATIVE_PEER_CONNECTION_TEST_MAIN pd_nine_main
#include "test-pinmem-native-peer-connections.c"
#undef FULL_PINMEM_NATIVE_PEER_CONNECTION_TEST_MAIN
#include "pinmem-drawinfo-connection.h"
#include "adf-connection.h"
#include "scalar-device.h"
#include "../drawinfo-registry.h"
static const unsigned int pd_s[4]={6,2,0,FULL_PINMEM_CP},pd_p[4]={6,1,0,NATIVE_DRAWINFO_CP};
static struct connect_message *pd_request,*pd_final;
static unsigned int pd_caller=0x81cf61c4u,pd_allocs,pd_sends,pd_callbacks,pd_bad_alloc,pd_bad_source,pd_corrupt,pd_offset;
static int pd_ready,pd_busy,pd_send_error,pd_request_error,pd_reply_error,pd_inline,pd_recursive,pd_fork_held;
static int pd_mutate_request,pd_cleanup_error;
static unsigned int pd_event_fault,pd_event_order,pd_consumed_order,pd_manager_order,pd_answer_free_order,pd_clock;
static const struct full_imaging_io pd_io;
static const struct full_adf_proc_guard pd_guard;
struct pd_history {
    struct vpc_history previous;
    struct full_vef_pinmem_control_connection_snapshot seventh;
    struct scalar_connection_snapshot eighth,ninth;
    struct full_vef_snapshot scalar,drawinfo;
};
static struct pd_history pd_before;
static unsigned char pd_memory_before[PIN_CONTROL_CAPACITY];
static void pd_capture(struct pd_history *h){
    memset(h,0,sizeof *h);vpc_capture(&h->previous);full_vef_pinmem_control_connection_snapshot(&h->seventh);
    full_scalar_connection_snapshot(&h->eighth);full_adf_connection_snapshot(&h->ninth);
    full_scalar_snapshot(&h->scalar);native_drawinfo_snapshot(&h->drawinfo);
}
static struct scalar_connection_snapshot pd_snapshot(void){
    struct scalar_connection_snapshot s;full_pinmem_drawinfo_connection_snapshot(&s);return s;
}
static void pd_preserved(void){
    if(!pd_ready)return;
    struct pd_history after;pd_capture(&after);
    after.previous.pinmem.pins[10]=pd_before.previous.pinmem.pins[10];
    after.previous.pinmem.pending=pd_before.previous.pinmem.pending;
    after.previous.pinmem.faults=pd_before.previous.pinmem.faults;
    after.drawinfo.pins[1]=pd_before.drawinfo.pins[1];after.drawinfo.faults=pd_before.drawinfo.faults;
    assert(!memcmp(&after,&pd_before,sizeof after));
    assert(!memcmp(connect_memory,pd_memory_before,sizeof connect_memory));out_preserved_failure();out_check_shadow();
}
static void pd_callback(void){assert(host_pid==getpid());pd_callbacks++;(void)pd_snapshot();pd_preserved();if(held)guarded();}
/* Get uses the real registry owner and its independent release lease. */
static void pd_get(unsigned int sid,const unsigned int *key,int leave){
    get_destination=0x8a0bc017u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    int rc=77,freed=77,handled;
    if(sid==FULL_SCALAR_CP)handled=full_scalar_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else if(sid==NATIVE_DRAWINFO_CP)handled=native_drawinfo_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else if(sid==FULL_ADF_CP)handled=full_adf_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else handled=full_pinmem_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    assert(handled && !rc && m->released && vc_seed_queued);
    for(unsigned int i=0;i<3;i++)assert(ct32(vc_seed_queued->data+32+4*i)==key[i]);
    assert(ct32(vc_seed_queued->data+44)==1 && ct32(vc_seed_queued->data+48)==sid);
    if(sid==NATIVE_DRAWINFO_CP)assert(ct32(vc_seed_queued->data)==0);
    if(leave){vc_seed_queued=0;return;}
    if(sid==FULL_SCALAR_CP)handled=full_scalar_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==NATIVE_DRAWINFO_CP)handled=native_drawinfo_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else if(sid==FULL_ADF_CP)handled=full_adf_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    else handled=full_pinmem_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    assert(handled && !freed);vc_seed_queued=0;
}
static void pd_seed(const char *seed,const char *name){
    char *args[]={"test","normal",(char *)seed,0};
    if(strcmp(name,"no-ninth") && strcmp(name,"no-ninth-AP-free")){
        assert(!pd_nine_main(3,args));vi_clear_messages();alarm(30);return;
    }
    assert(!pnc_seventh_prerequisite_main(3,args));vi_clear_messages();alarm(30);
    assert(!full_scalar_connection_owner_init() && !full_adf_connection_owner_init());
    pnc_get(FULL_PINMEM_CP,pnc_s,0);pnc_get(FULL_SCALAR_CP,pnc_p,0);vi_clear_messages();pnc_save();pnc_request=pnc_new_request();pnc_complete_current();
    if(!strcmp(name,"no-ninth"))return;
    pnc_select_adf();vi_clear_messages();pnc_get(FULL_PINMEM_CP,pnc_s,0);pnc_get(FULL_ADF_CP,pnc_p,0);vi_clear_messages();pnc_save();pnc_request=pnc_new_request();
    int rc=77;assert(pnc_dispatch(&rc) && !rc && pnc_snapshot().clean_completion && pnc_snapshot().live_reply==pnc_final->data && !pnc_snapshot().ap_consumed);
}
static struct connect_message *pd_new_request(void){
    struct connect_message *m=cm_new(64,FULL_PINMEM_CP,pd_caller);ctframe(m->data,64,1,2);ctput32(m->data,pd_caller);ctput32(m->data+20,0x7855c);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,pd_s[i]);ctput32(m->data+48+4*i,pd_p[i]);}return m;
}
static unsigned int pd_size(void *p){pd_callback();return cm_size(p);}
static unsigned int pd_source(void *p){pd_callback();return cm_source(p);}
static int pd_free(unsigned int owner,void *p){
    pd_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==pd_request && pd_request_error)return -53;
    if(m==pd_final && pd_reply_error)return -59;
    if(m->allocation && m!=pd_final && pd_cleanup_error)return -47;
    if(m->allocation==2){struct scalar_connection_snapshot s=pd_snapshot();if(s.event6_consumed){assert(!s.pending_event6 && s.manager_calls==1);pd_answer_free_order=++pd_clock;}}
    cm_dispose(m);return 0;
}
static void pd_set(void *p,unsigned int sid){
    pd_callback();struct connect_message *m=cm_meta(p);m->source=m->allocation==pd_bad_source?1234:sid;
    if(m->allocation==pd_corrupt)m->data[pd_offset]^=1;
}
static int pd_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    pd_callback();assert(held && owner==pd_caller && count==1);pd_allocs++;
    const unsigned int sizes[3]={64,72,56};assert(pd_allocs<=3 && n==sizes[pd_allocs-1]);
    if(pd_allocs==pd_bad_alloc){*out=0;return -41;}
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=pd_allocs;*out=m->data;return 0;
}
static int pd_reserve(void){pd_callback();return pd_busy?-EBUSY:reserve();}
static void pd_release_guard(void){pd_callback();assert(held);release_guard();}
static int pd_dispatch(int *rc){return full_pinmem_drawinfo_connection_native_dispatch(FULL_PINMEM_CP,pd_request->data,&pd_io,&pd_guard,1,rc);}
static void pd_record(const char *tag,const char *text){
    pd_callback();fprintf(stdout,"%s%s\n",tag,text);pd_clock++;
    if(!strcmp(tag,"FULL_PINMEM_DRAWINFO_CONNECT_EVENT6_ENQUEUED ")){
        struct scalar_connection_snapshot s=pd_snapshot();unsigned char expected[12]={0};ctput32(expected,s.event6_token);
        assert(s.pending_event6 && s.event6_enqueued==1 && !s.event6_consumed && !s.event6_inflight && s.event6_token && s.event6_answer);
        assert(s.event6_body==(unsigned char *)s.event6_answer+24 && !memcmp(s.event6_parameter,expected,12));
        assert(!memcmp(s.saved_request,pd_request->data,64) && s.context_kind==2 && s.phase==1 && s.wait_primary==6 && !s.wait_secondary && s.keep_pending==1);
        assert(!s.original_CP_event_pointer_identity_verified && !s.original_RTOS_scheduling_verified);pd_event_order=pd_clock;
        if(pd_event_fault)full_pinmem_drawinfo_connection_test_event_corrupt(pd_event_fault);
    }
    if(!strcmp(tag,"FULL_PINMEM_DRAWINFO_CONNECT_EVENT6_CONSUMED ")){
        struct scalar_connection_snapshot s=pd_snapshot();assert(s.event6_consumed==1 && !s.pending_event6 && !s.event6_answer && !s.event6_body && s.event6_token_verified && s.event6_peer_verified);pd_consumed_order=pd_clock;
    }
    if(!strcmp(tag,"FULL_PINMEM_DRAWINFO_CONNECT_DRAWINFO_MANAGER ")){
        struct scalar_connection_snapshot s=pd_snapshot();assert(s.post_callback_type==6 && s.manager_calls==1 && !s.manager_return && !s.yc_callback_seen && !s.yc_format_published);pd_manager_order=pd_clock;
    }
    if(!strcmp(tag,"FULL_PINMEM_DRAWINFO_CONNECT_REQUEST ")){
        if(pd_mutate_request)pd_request->data[20]^=1;
        if(pd_recursive){int rc=77;assert(pd_dispatch(&rc) && rc==-1021);}
        if(pd_fork_held){pid_t child=fork();assert(child>=0);if(!child){alarm(2);int rc=77;assert(!pd_snapshot().initialized);
                assert(full_pinmem_drawinfo_connection_owner_init()==-1021);assert(pd_dispatch(&rc) && rc==-1021);
                assert(!full_pinmem_drawinfo_connection_release(pd_caller,pd_request->data,pd_free,pd_record,&rc));_exit(0);}
            int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    }
}
static int pd_send(unsigned int owner,void *p){
    pd_callback();pd_final=cm_meta(p);assert(owner==pd_caller && pd_final->allocation==3 && pd_final->bytes==56 && pd_final->source==FULL_PINMEM_CP);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,pd_s[i]);assert(!memcmp(expected,p,56));
    struct scalar_connection_snapshot s=pd_snapshot();assert(s.event6_consumed && !s.pending_event6 && !s.yc_callback_seen && !s.yc_format_published);
    assert(s.manager_calls==1 && !s.manager_return && s.live_reply==p);
    assert(pd_event_order<pd_consumed_order && pd_consumed_order<pd_manager_order && pd_manager_order<pd_answer_free_order);pd_sends++;
    if(pd_inline){int rc=77;assert(full_pinmem_drawinfo_connection_release(owner,p,pd_free,pd_record,&rc) && !rc);}return pd_send_error;
}
static const struct full_imaging_io pd_io={pd_allocate,pd_free,pd_set,pd_send,pd_size,pd_source,pd_record};
static const struct full_adf_proc_guard pd_guard={pd_reserve,pd_release_guard};
static void pd_finish(void){pd_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("PINMEM_DRAWINFO_CONNECTION_HOST_TEST_PASS");}
#ifndef FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN
#define FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN main
#endif
int FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);assert(!setvbuf(stdout,0,_IONBF,0));const char *name=argv[1];
    if(strcmp(name,"uninitialized"))assert(!full_pinmem_drawinfo_connection_owner_init());
    if(!strcmp(name,"dynamic-caller"))pd_caller=0x8fed1023u;
    pd_request=pd_new_request();int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"other-key")){
        if(!strcmp(name,"short"))pd_request->bytes=63;
        if(!strcmp(name,"other-key"))ctput32(pd_request->data+32,0);
        assert(!full_pinmem_drawinfo_connection_native_dispatch(!strcmp(name,"unrelated")?NATIVE_DRAWINFO_CP:FULL_PINMEM_CP,pd_request->data,&pd_io,&pd_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!pd_allocs && !pd_snapshot().started && !pd_request->released);pd_finish();return 0;
    }
    if(!strcmp(name,"uninitialized") || !strcmp(name,"fork")){
        if(!strcmp(name,"uninitialized")){assert(pd_dispatch(&rc) && rc==-1021 && !pd_callbacks);pd_finish();return 0;}
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!pd_snapshot().initialized);assert(full_pinmem_drawinfo_connection_owner_init()==-1021);
            assert(pd_dispatch(&rc) && rc==-1021 && !pd_callbacks);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));pd_finish();return 0;
    }
    if(!strcmp(name,"bad-wire") || !strcmp(name,"future-data") || !strcmp(name,"missing-guard")){
        if(!strcmp(name,"missing-guard"))assert(full_pinmem_drawinfo_connection_native_dispatch(FULL_PINMEM_CP,pd_request->data,&pd_io,0,1,&rc) && rc==-1021 && !pd_callbacks);
        else if(!strcmp(name,"future-data")){unsigned int controls[]={2,3,4,0x104,0x8100};for(unsigned int i=0;i<sizeof controls/sizeof *controls;i++){ctput16(pd_request->data+26,controls[i]);assert(pd_dispatch(&rc) && rc==-1021);}}
        else{
            unsigned int offsets[]={0,4,8,10,12,16,24,26,28,30};
            for(unsigned int i=0;i<sizeof offsets/sizeof *offsets;i++){pd_request->data[offsets[i]]^=1;assert(pd_dispatch(&rc) && rc==-1021);pd_request->data[offsets[i]]^=1;}
            for(unsigned int i=32;i<64;i+=4){pd_request->data[i+2]^=1;rc=77;assert(!pd_dispatch(&rc) && rc==77);pd_request->data[i+2]^=1;}
        }
        assert(!pd_allocs && !pd_snapshot().started && !pd_snapshot().faults && !pd_request->released);pd_finish();return 0;
    }
    assert(pd_dispatch(&rc) && rc==-1021 && !pd_snapshot().started && !pd_snapshot().faults && pd_snapshot().unadmitted_count==1 && !pd_allocs);
    if(!strcmp(name,"no-prior")){pd_finish();return 0;}
    assert(!cm_free(FULL_PINMEM_CP,pd_request->data));vi_clear_messages();pd_seed(argv[2],name);
    if(strcmp(name,"no-source-get"))pd_get(FULL_PINMEM_CP,pd_s,!strcmp(name,"live-source-get"));
    if(strcmp(name,"no-peer-get"))pd_get(NATIVE_DRAWINFO_CP,pd_p,!strcmp(name,"live-peer-get"));
    if(!strcmp(name,"no-ninth") || !strcmp(name,"no-ninth-AP-free") || !strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get") || !strcmp(name,"live-source-get") || !strcmp(name,"live-peer-get")){
        pd_request=pd_new_request();assert(pd_dispatch(&rc) && rc==-1021 && !pd_snapshot().started && !pd_snapshot().faults && !pd_allocs && !pd_request->released);pd_finish();return 0;
    }
    vi_clear_messages();pd_capture(&pd_before);memcpy(pd_memory_before,connect_memory,sizeof connect_memory);pd_ready=1;pd_request=pd_new_request();
    assert(pd_before.ninth.ap_consumed && pd_before.ninth.clean_completion && pd_before.previous.sixth.dmm_requests==9 && pd_before.previous.sixth.buffer_freed);
    assert(!pd_before.previous.pool.live && pd_before.drawinfo.registry_objects==2 && pd_before.previous.pinmem.registry_objects==13);
    const unsigned int cache[5]={1,1,1920,1080,3};assert(!memcmp(pd_before.previous.first.format.cache,cache,sizeof cache));
    if(!strcmp(name,"source-status"))pin_registry_test_set_state(full_pinmem_registry(),10,2);
    if(!strcmp(name,"peer-status"))pin_registry_test_set_state(native_drawinfo_registry(),1,2);
    if(!strcmp(name,"source-status") || !strcmp(name,"peer-status")){
        assert(pd_dispatch(&rc) && rc==-1021 && !pd_snapshot().started && !pd_snapshot().faults && !pd_allocs);pd_finish();return 0;
    }
    if(!strcmp(name,"resource-busy"))pd_busy=1;
    if(!strcmp(name,"send-fail"))pd_send_error=-61;
    if(!strcmp(name,"request-free-fail"))pd_request_error=1;
    if(!strcmp(name,"inline-free"))pd_inline=1;
    if(!strcmp(name,"recursive"))pd_recursive=1;
    if(!strcmp(name,"fork-held"))pd_fork_held=1;
    if(!strcmp(name,"request-mutated"))pd_mutate_request=1;
    if(!strcmp(name,"cleanup-fail")){pd_bad_alloc=2;pd_cleanup_error=1;}
    unsigned int n=0,offset=0;
    if(sscanf(name,"alloc-%u",&n)==1)pd_bad_alloc=n;
    if(sscanf(name,"source-%u",&n)==1)pd_bad_source=n;
    if(sscanf(name,"wire-%u-%u",&n,&offset)==2){pd_corrupt=n;pd_offset=offset;}
    if(sscanf(name,"event-%u",&n)==1)pd_event_fault=n;
    assert(pd_dispatch(&rc));struct scalar_connection_snapshot s=pd_snapshot();assert(!held && !s.busy && s.owner_pid==getpid());
    if(pd_busy){assert(rc==-1021 && !s.started && !s.faults && !pd_allocs);pd_finish();return 0;}
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || pd_inline || pd_recursive || pd_fork_held || pd_request_error || !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"repeat");
    if(success){
        assert(!rc && s.connections==1 && s.queued==1 && pd_sends==1 && pd_allocs==3 && s.event6_consumed && !s.pending_event6 && !s.yc_callback_seen && !s.yc_format_published && s.manager_calls==1 && !s.manager_return);
        assert(pd_request_error?(!s.clean_completion && s.faults && s.retained_request==pd_request->data && !pd_request->released):(s.clean_completion && !s.faults && pd_request->released && s.request_freed));
        if(!pd_inline){
            int freed=77;
            if(!strcmp(name,"wrong-owner"))assert(full_pinmem_drawinfo_connection_release(pd_caller^1u,pd_final->data,pd_free,pd_record,&freed) && freed==-1021 && !pd_final->attempts);
            if(!strcmp(name,"reply-free-fail")){pd_reply_error=1;assert(full_pinmem_drawinfo_connection_release(pd_caller,pd_final->data,pd_free,pd_record,&freed) && freed==-59);pd_reply_error=0;}
            assert(full_pinmem_drawinfo_connection_release(pd_caller,pd_final->data,pd_free,pd_record,&freed) && !freed);
        }
        s=pd_snapshot();assert(s.ap_consumed==1 && s.reply_freed==1 && s.native_reply_frees==1 && s.waiter_frees==1 && !s.live_reply);
        struct full_vef_snapshot a,b;full_pinmem_snapshot(&a);native_drawinfo_snapshot(&b);
        assert(!a.pending && !a.pins[10].state && !b.pins[1].state && !memcmp(a.pins[10].peer,pd_p,sizeof pd_p) && !memcmp(b.pins[1].peer,pd_s,sizeof pd_s));
        if(!strcmp(name,"repeat")){pd_request=pd_new_request();assert(pd_dispatch(&rc) && rc==-1021 && pd_sends==1 && pd_allocs==3 && !pd_request->released);}
        puts("PRIOR_NINE_NATIVE_EDGES_BACKING_DMM_CACHES_HISTORY_PRESERVED metadata_only=1 capture_verified=0");
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !pd_request->released);
        assert(pd_sends==(pd_send_error?1u:0u));
        if(pd_cleanup_error)assert(s.retained_messages);
        if(pd_event_fault)assert(s.pending_event6 && !s.event6_consumed && s.retained_messages==1 && s.retained_cleanup==s.event6_answer && !cm_meta(s.event6_answer)->attempts);
        unsigned int allocations=pd_allocs;assert(pd_dispatch(&rc) && rc==-1021 && pd_allocs==allocations);
    }
    struct scalar_connection_snapshot before=pd_snapshot();assert(!full_pinmem_drawinfo_connection_owner_init());s=pd_snapshot();assert(!memcmp(&before,&s,sizeof s));
    pd_finish();return 0;
}
