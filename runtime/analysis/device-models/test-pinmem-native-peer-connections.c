/* SPDX-License-Identifier: MIT */
/* Reuse the actual seven-edge history, then switch to independent reentrant IO. */
#define FULL_VEF_PINMEM_CONTROL_CONNECTION_TEST_MAIN pnc_seventh_prerequisite_main
#include "test-vef-pinmem-control-connection.c"
#undef FULL_VEF_PINMEM_CONTROL_CONNECTION_TEST_MAIN
#include "scalar-connection.h"
#include "scalar-device.h"
#include "adf-connection.h"
#include "../dmm-service.h"
static unsigned char pnc_speech_memory[DMM_TEST_SIZE],pnc_speech_before[DMM_TEST_SIZE];
static struct dmm_service pnc_speech,pnc_speech_state_before;
static int pnc_speech_ready;
static void pnc_speech_seed(void){
    pnc_speech=(struct dmm_service){.memory=pnc_speech_memory,.physical=DMM_TEST_PHYSICAL};
    unsigned char request_wire[40]={0x20},reply_wire[40];ctput32(request_wire+4,0x63a);ctput16(request_wire+22,1);
    const unsigned long pcs[4]={0x35522a4UL,0x35527b4UL,0x34d3614UL,0x17b2c08UL};
    for(unsigned int i=0;i<2;i++){
        assert(!dmm_service_reply(&pnc_speech,request_wire,sizeof request_wire,reply_wire) && !ct16(reply_wire+2));
        assert(pnc_speech.slots[i].allocated && pnc_speech.slots[i].open_count==1);
        pnc_speech.slots[i].creator_kind=dmm_speech_initial_creator(pcs,4); /* Host producer-provenance fixture. */
        assert(pnc_speech.slots[i].creator_kind==DMM_CREATOR_SPEECH_INITIAL);
    }
    for(unsigned int i=0;i<sizeof pnc_speech_memory;i++)pnc_speech_memory[i]=(unsigned char)(i*19u+0x84u);
    pnc_speech_state_before=pnc_speech;memcpy(pnc_speech_before,pnc_speech_memory,sizeof pnc_speech_memory);pnc_speech_ready=1;
}
static const unsigned int pnc_scalar_s[4]={0,2,1,FULL_PINMEM_CP},pnc_scalar_p[4]={0,1,4,FULL_SCALAR_CP};
static const unsigned int pnc_adf_s[4]={0,2,2,FULL_PINMEM_CP},pnc_adf_p[4]={0,1,0,FULL_ADF_CP};
static const unsigned int *pnc_s=pnc_scalar_s,*pnc_p=pnc_scalar_p;
static struct connect_message *pnc_request,*pnc_final;
static unsigned int pnc_caller=0x8abc7601,pnc_allocs,pnc_sends,pnc_callbacks,pnc_reserves,pnc_releases;
static unsigned int pnc_alloc_fail,pnc_alloc_alias,pnc_alloc_short,pnc_event_fault,pnc_event_consumes,pnc_posthooks;
static int pnc_adf,pnc_history_ready,pnc_busy,pnc_guard_mutation,pnc_inline,pnc_send_error,pnc_request_error,pnc_cleanup_error,pnc_reply_error;
static int pnc_recursive,pnc_recursive_free,pnc_queued_fault,pnc_fork_held,pnc_duplicate,pnc_mutate_request;
static int pnc_threaded,pnc_thread_error,pnc_thread_started,pnc_thread_go;
static unsigned int pnc_release_rejects,pnc_send_release_faults;
static int pnc_reuse;
static unsigned char *pnc_retired,*pnc_reuse_pointer;
static pthread_t pnc_thread;
static pthread_mutex_t pnc_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pnc_thread_condition=PTHREAD_COND_INITIALIZER;
static const struct full_imaging_io pnc_io;
static const struct full_adf_proc_guard pnc_guard;
static void pnc_record(const char *,const char *);
struct pnc_history {
    struct vpc_history prior;
    struct full_vef_pinmem_control_connection_snapshot seventh;
    struct full_vef_snapshot scalar;
    struct scalar_connection_snapshot eighth;
};
static struct pnc_history pnc_before;
static unsigned char pnc_memory_before[PIN_CONTROL_CAPACITY];
static void pnc_capture(struct pnc_history *p){
    memset(p,0,sizeof *p);vpc_capture(&p->prior);full_vef_pinmem_control_connection_snapshot(&p->seventh);full_scalar_snapshot(&p->scalar);
    if(pnc_adf)full_scalar_connection_snapshot(&p->eighth);
}
static struct scalar_connection_snapshot pnc_snapshot(void){
    struct scalar_connection_snapshot s;if(pnc_adf)full_adf_connection_snapshot(&s);else full_scalar_connection_snapshot(&s);return s;
}
static int pnc_init(void){return pnc_adf?full_adf_connection_owner_init():full_scalar_connection_owner_init();}
static int pnc_dispatch(int *rc){
    return pnc_adf?full_adf_connection_native_dispatch(FULL_PINMEM_CP,pnc_request->data,&pnc_io,&pnc_guard,1,rc):
        full_scalar_connection_native_dispatch(FULL_PINMEM_CP,pnc_request->data,&pnc_io,&pnc_guard,1,rc);
}
static int pnc_release(unsigned int owner,void *p,int (*free_message)(unsigned int,void *),void (*record_message)(const char *,const char *),int *rc){
    if(full_scalar_connection_release(owner,p,free_message,record_message,rc))return 1;
    return pnc_adf?full_adf_connection_release(owner,p,free_message,record_message,rc):0;
}
static void pnc_preserved(void){
    if(pnc_speech_ready){assert(!memcmp(&pnc_speech,&pnc_speech_state_before,sizeof pnc_speech));assert(!memcmp(pnc_speech_memory,pnc_speech_before,sizeof pnc_speech_memory));}
    if(!pnc_history_ready)return;
    struct pnc_history after;pnc_capture(&after);unsigned int slot=pnc_adf?5u:4u;
    after.prior.pinmem.pins[slot]=pnc_before.prior.pinmem.pins[slot];after.prior.pinmem.pending=pnc_before.prior.pinmem.pending;
    if(pnc_adf)after.prior.adf.pins[0]=pnc_before.prior.adf.pins[0];else after.scalar.pins[4]=pnc_before.scalar.pins[4];
    assert(!memcmp(&after,&pnc_before,sizeof after));
    assert(!memcmp(connect_memory,pnc_memory_before,sizeof connect_memory));out_preserved_failure();out_check_shadow();
}
static void pnc_callback(void){
    assert(host_pid==getpid());pnc_callbacks++;(void)pnc_snapshot();pnc_preserved();
    if(held && pthread_equal(guard_thread,pthread_self()))guarded();
}
static unsigned int pnc_size(void *p){pnc_callback();return cm_size(p);}
static unsigned int pnc_source(void *p){pnc_callback();return cm_source(p);}
static int pnc_free(unsigned int owner,void *p){
    pnc_callback();struct connect_message *m=cm_meta(p);assert(m->owner==owner);m->attempts++;
    if(m==pnc_request && pnc_request_error)return -53;
    if(m==pnc_final && pnc_reply_error)return -59;
    if(m->allocation && m!=pnc_final && pnc_cleanup_error)return -47;
    if(m==pnc_final && pnc_recursive_free){int rc=77;unsigned int attempts=m->attempts;assert(pnc_release(owner,p,pnc_free,pnc_record,&rc) && rc==-1021 && m->attempts==attempts);}
    /* Deterministic allocator pool: retirement ends the lease, retaining storage for reuse. */
    if(m==pnc_final && pnc_reuse){assert(!pnc_retired);m->released=1;pnc_retired=m->data;return 0;}
    cm_dispose(m);return 0;
}
static void pnc_set(void *p,unsigned int sid){pnc_callback();cm_set(p,sid);}
static int pnc_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    pnc_callback();assert(held && owner==pnc_caller && count==1);pnc_allocs++;
    static const unsigned int sizes[3]={64,72,56};assert(pnc_allocs<=3 && n==sizes[pnc_allocs-1]);
    if(pnc_allocs==pnc_alloc_fail){*out=0;return -41;}
    if(pnc_allocs==pnc_alloc_alias){*out=pnc_allocs==2?cm[cm_count-1].data:pnc_request->data;return 0;}
    struct connect_message *m;
    if(pnc_reuse && pnc_adf && pnc_allocs==3){
        assert(pnc_retired && cm_count<sizeof cm/sizeof *cm);m=&cm[cm_count++];
        *m=(struct connect_message){.bytes=n,.owner=owner,.source=ALLOCATOR_SOURCE,.data=pnc_retired};pnc_retired=0;
    }else m=cm_new(n,owner,ALLOCATOR_SOURCE);
    m->allocation=pnc_allocs;*out=m->data;
    if(pnc_allocs==pnc_alloc_short)m->bytes=n-1;
    return 0;
}
static int pnc_reserve(void){
    pnc_callback();pnc_reserves++;if(pnc_busy)return -EBUSY;
    int rc=reserve();if(!rc && pnc_guard_mutation)pin_registry_test_set_state(full_pinmem_registry(),pnc_adf?5u:4u,2);return rc;
}
static void pnc_release_guard(void){pnc_callback();assert(held && pnc_snapshot().guard_held);pnc_releases++;release_guard();}
static void pnc_record(const char *tag,const char *text){
    pnc_callback();fprintf(stdout,"%s%s\n",tag,text);const char *prefix=pnc_adf?"FULL_ADF_CONNECT_":"FULL_SCALAR_CONNECT_";
    if(strncmp(tag,prefix,strlen(prefix)))return;
    const char *kind=tag+strlen(prefix);
    if(!strcmp(kind,"RELEASE_REJECT_FAULT ")){assert(pnc_snapshot().faults && !pnc_snapshot().clean_completion);pnc_release_rejects++;}
    if(!strcmp(kind,"SEND_RELEASE_FAULT ")){assert(pnc_snapshot().faults && !pnc_snapshot().clean_completion);pnc_send_release_faults++;}
    if(!strcmp(kind,"REQUEST ") && pnc_recursive){int rc=77;assert(pnc_dispatch(&rc) && rc==-1021 && pnc_snapshot().requests==1);}
    if(!strcmp(kind,"REQUEST ") && pnc_fork_held){pid_t child=fork();assert(child>=0);if(!child){alarm(2);int rc=77;assert(pnc_init()==-1021 && !pnc_snapshot().initialized);
            assert(pnc_dispatch(&rc) && rc==-1021);assert(!pnc_release(pnc_caller,pnc_request->data,pnc_free,pnc_record,&rc));_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    if(!strcmp(kind,"EVENT6_ENQUEUED ")){
        struct scalar_connection_snapshot s=pnc_snapshot();unsigned char parameter[12]={0};ctput32(parameter,0x504d0000u|pnc_s[2]);
        assert(s.pending_event6 && !s.event6_consumed && s.phase==1 && s.context_kind==2 && s.wait_primary==6 && !s.wait_secondary && s.keep_pending==1);
        assert(s.event6_answer && s.event6_body==(unsigned char *)s.event6_answer+24 && !memcmp(s.event6_parameter,parameter,12));
        assert(!memcmp(s.saved_request,pnc_request->data,64) && s.saved_request_fnv==cthash(pnc_request->data,64) && s.event6_parameter_fnv==cthash(parameter,12));
        if(pnc_event_fault && pnc_event_fault<=8){if(pnc_adf)full_adf_connection_test_event_corrupt(pnc_event_fault);else full_scalar_connection_test_event_corrupt(pnc_event_fault);}
        if(pnc_event_fault==9)((unsigned char *)s.event6_answer)[64]^=1;
        if(pnc_event_fault==10)((unsigned char *)s.event6_answer)[60]^=1;
        if(pnc_event_fault==11)((unsigned char *)s.event6_answer)[68]^=1;
        if(pnc_mutate_request)pnc_request->data[20]^=1;
    }
    if(!strcmp(kind,"EVENT6_CONSUMED ")){
        struct scalar_connection_snapshot s=pnc_snapshot();assert(s.event6_consumed && !s.pending_event6 && !s.context_kind && !s.event6_answer && !s.event6_body && s.event6_token_verified && s.event6_peer_verified);pnc_event_consumes++;
        if(pnc_duplicate){int rc=pnc_adf?full_adf_connection_test_event_consume(&pnc_io):full_scalar_connection_test_event_consume(&pnc_io);assert(rc==-1);}
    }
    if(!strcmp(kind,"YC_DIRECTION_CHECK ")){assert(pnc_snapshot().yc_callback_seen && !pnc_snapshot().yc_format_published);pnc_posthooks++;}
    if(!strcmp(kind,"REPLY_QUEUED ") && pnc_queued_fault){int rc=77;assert(pnc_release(pnc_caller^1u,pnc_final->data,pnc_free,pnc_record,&rc) && rc==-1021);}
}
static int pnc_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&pnc_thread_mutex));pnc_thread_started=1;assert(!pthread_cond_signal(&pnc_thread_condition));
    while(!pnc_thread_go)assert(!pthread_cond_wait(&pnc_thread_condition,&pnc_thread_mutex));
    assert(!pthread_mutex_unlock(&pnc_thread_mutex));return pnc_thread_error?-59:cm_free(owner,p);
}
static void *pnc_thread_release(void *unused){(void)unused;int rc=77;assert(pnc_release(pnc_caller,pnc_final->data,pnc_thread_free,0,&rc));assert(rc==(pnc_thread_error?-59:0));return 0;}
static int pnc_send(unsigned int owner,void *p){
    pnc_callback();pnc_final=cm_meta(p);struct scalar_connection_snapshot s=pnc_snapshot();
    assert(owner==pnc_caller && pnc_final->allocation==3 && pnc_final->bytes==56 && pnc_final->source==FULL_PINMEM_CP);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,pnc_s[i]);assert(!memcmp(p,expected,56));
    assert(s.live_reply==p && !s.faults && s.event6_consumed==1 && s.yc_callback_seen && !s.yc_format_published && !s.manager_calls && pnc_event_consumes==1 && pnc_posthooks==1);pnc_sends++;
    if(pnc_reuse && pnc_adf){
        struct scalar_connection_snapshot before,after;full_scalar_connection_snapshot(&before);unsigned int callbacks=pnc_callbacks;int f=77;
        assert(p==pnc_reuse_pointer && !before.live_reply);
        assert(!full_scalar_connection_release(owner^1u,p,pnc_free,pnc_record,&f) && f==77 && pnc_callbacks==callbacks);
        full_scalar_connection_snapshot(&after);assert(!memcmp(&before,&after,sizeof before));
        fprintf(stdout,"PINMEM_NATIVE_RETIRED_REUSE_SAME_ADDRESS reply=%p scalar_claimed=0 adf_live=1 capture_verified=0\n",p);
    }
    if(pnc_fork_held){
        struct scalar_connection_snapshot before=pnc_snapshot();unsigned int callbacks_before=pnc_callbacks;
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);int f=77;
            assert(!pnc_release(owner,p,pnc_free,pnc_record,&f) && f==77 && !pnc_snapshot().initialized);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
        struct scalar_connection_snapshot after=pnc_snapshot();assert(!memcmp(&before,&after,sizeof before) && pnc_callbacks==callbacks_before);
    }
    if(pnc_threaded){assert(!pthread_mutex_lock(&pnc_thread_mutex));assert(!pthread_create(&pnc_thread,0,pnc_thread_release,0));
        while(!pnc_thread_started){assert(!pthread_cond_wait(&pnc_thread_condition,&pnc_thread_mutex));}
        assert(!pthread_mutex_unlock(&pnc_thread_mutex));}
    if(pnc_inline){int rc=77;assert(pnc_release(owner,p,pnc_free,pnc_record,&rc) && !rc);}
    return pnc_send_error;
}
static const struct full_imaging_io pnc_io={pnc_allocate,pnc_free,pnc_set,pnc_send,pnc_size,pnc_source,pnc_record};
static const struct full_adf_proc_guard pnc_guard={pnc_reserve,pnc_release_guard};
static void pnc_get(unsigned int sid,const unsigned int *key,int leave){
    get_destination=sid==FULL_PINMEM_CP?0x8f001001u:0x8f001002u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    int rc=77,freed=77,handled;
    if(sid==FULL_PINMEM_CP)handled=full_pinmem_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else if(sid==FULL_SCALAR_CP)handled=full_scalar_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    else handled=full_adf_dispatch(sid,m->data,&vc_seed_io,1,&rc);
    assert(handled && !rc && m->released && vc_seed_queued);
    for(unsigned int i=0;i<3;i++)assert(ct32(vc_seed_queued->data+32+4*i)==key[i]);
    assert(ct32(vc_seed_queued->data+44)==1 && ct32(vc_seed_queued->data+48)==sid);
    if(!leave){
        if(sid==FULL_PINMEM_CP)handled=full_pinmem_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
        else if(sid==FULL_SCALAR_CP)handled=full_scalar_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
        else handled=full_adf_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
        assert(handled && !freed);
    }
    vc_seed_queued=0;
}
static struct connect_message *pnc_new_request(void){
    struct connect_message *m=cm_new(64,FULL_PINMEM_CP,pnc_caller);ctframe(m->data,64,1,2);ctput32(m->data,pnc_caller);ctput32(m->data+20,0x82c73);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,pnc_s[i]);ctput32(m->data+48+4*i,pnc_p[i]);}return m;
}
static void pnc_save(void){pnc_capture(&pnc_before);memcpy(pnc_memory_before,connect_memory,sizeof connect_memory);pnc_history_ready=1;}
static void pnc_select_adf(void){
    pnc_adf=1;pnc_s=pnc_adf_s;pnc_p=pnc_adf_p;pnc_caller=0x8def3202;
    pnc_allocs=pnc_sends=pnc_callbacks=pnc_reserves=pnc_releases=pnc_event_consumes=pnc_posthooks=0;pnc_history_ready=0;
    pnc_release_rejects=pnc_send_release_faults=0;
    if(pnc_reuse){
        struct scalar_connection_snapshot before,after;full_scalar_connection_snapshot(&before);int f=77;
        pnc_reuse_pointer=pnc_retired;assert(pnc_retired && !before.live_reply && before.ap_consumed==1);
        assert(!pnc_release(pnc_caller^1u,pnc_retired,pnc_free,pnc_record,&f) && f==77 && !pnc_callbacks);
        full_scalar_connection_snapshot(&after);assert(!memcmp(&before,&after,sizeof before));
    }
}
static void pnc_complete_current(void){
    int rc=77;assert(pnc_dispatch(&rc) && !rc);struct scalar_connection_snapshot s=pnc_snapshot();
    assert(s.clean_completion && s.connections==1 && !s.faults && s.native_guarded && !held);
    assert(pnc_release(pnc_caller,pnc_final->data,pnc_free,pnc_record,&rc) && !rc);s=pnc_snapshot();
    assert(s.ap_consumed==1 && s.native_reply_frees==1 && s.waiter_frees==1 && s.reply_freed && !s.live_reply && !s.retained_messages);pnc_preserved();
}
static void pnc_finish(void){pnc_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);free(pnc_retired);pnc_retired=0;puts("PINMEM_NATIVE_PEER_CONNECTIONS_HOST_TEST_PASS");}
#ifndef FULL_PINMEM_NATIVE_PEER_CONNECTION_TEST_MAIN
#define FULL_PINMEM_NATIVE_PEER_CONNECTION_TEST_MAIN main
#endif
int FULL_PINMEM_NATIVE_PEER_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);assert(!setvbuf(stdout,0,_IONBF,0));
    const char *name=argv[1];int target_adf=!strncmp(name,"adf-",4);if(target_adf)name+=4;
    pnc_reuse=target_adf && !strncmp(name,"retired-reuse",13);
    int rc=77;
    if(!strcmp(name,"uninitialized")){
        pnc_request=pnc_new_request();assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_callbacks && !pnc_snapshot().initialized);pnc_finish();return 0;
    }
    assert(!full_scalar_connection_owner_init() && !full_adf_connection_owner_init());
    pnc_request=pnc_new_request();assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_snapshot().started && !pnc_snapshot().faults && !pnc_request->released);
    assert(!cm_free(FULL_PINMEM_CP,pnc_request->data));vi_clear_messages();
    void *predecessor_reply=0;
    if(!target_adf && !strcmp(name,"predecessor-no-ap-free")){
        assert(!full_vef_pinmem_control_connection_owner_init());vpc_seed(argv[2],"normal");
        struct connect_message *m=vpc_new_request();const struct full_adf_proc_guard g={reserve,release_guard};
        assert(full_vef_pinmem_control_connection_dispatch(FULL_VEF_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);
        predecessor_reply=vc_seed_queued->data;vc_seed_queued=0;
    }else{char *old[]={(char *)"test",(char *)(!target_adf && !strcmp(name,"predecessor-foreign-thread-free")?"foreign-thread-free":"normal"),argv[2],0};assert(!pnc_seventh_prerequisite_main(3,old));vi_clear_messages();}
    pnc_speech_seed();
    /* Old callbacks compare their own source slots and must not run after edge8. */
    pnc_get(FULL_PINMEM_CP,pnc_s,!strcmp(name,"live-source-get") && !target_adf);
    pnc_get(FULL_SCALAR_CP,pnc_p,!strcmp(name,"live-peer-get") && !target_adf);
    if(strcmp(name,"live-source-get") && strcmp(name,"live-peer-get") && !predecessor_reply)vi_clear_messages();
    pnc_save();pnc_request=pnc_new_request();
    if(!target_adf && !strcmp(name,"predecessor-foreign-thread-free")){
        struct full_vef_pinmem_control_connection_snapshot prior=vpc_snapshot();
        assert(prior.clean_completion && !prior.faults && prior.reply_freed && !prior.ap_consumed && !prior.live_reply);
        unsigned int allocations=pnc_allocs;assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_snapshot().started && !pnc_snapshot().faults && !pnc_request->released && pnc_allocs==allocations);
        pnc_finish();return 0;
    }
    if(target_adf){
        if(!strcmp(name,"predecessor-no-ap-free")){
            assert(pnc_dispatch(&rc) && !rc && pnc_snapshot().clean_completion && !pnc_snapshot().ap_consumed);predecessor_reply=pnc_final->data;
        }else pnc_complete_current();
        pnc_select_adf();if(!predecessor_reply)vi_clear_messages();
        pnc_get(FULL_PINMEM_CP,pnc_s,!strcmp(name,"live-source-get"));pnc_get(FULL_ADF_CP,pnc_p,!strcmp(name,"live-peer-get"));
        if(strcmp(name,"live-source-get") && strcmp(name,"live-peer-get") && !predecessor_reply)vi_clear_messages();
        pnc_save();pnc_request=pnc_new_request();}
    if(pnc_reuse){
        if(!strcmp(name,"retired-reuse"))name="normal";
        else if(!strcmp(name,"retired-reuse-wrong-owner"))name="wrong-owner";
        else{assert(!strcmp(name,"retired-reuse-inflight"));name="recursive-free";}
    }
    if(predecessor_reply){
        unsigned int allocations_before=pnc_allocs;assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_snapshot().started && !pnc_snapshot().faults && !pnc_request->released && pnc_allocs==allocations_before);
        pnc_history_ready=0;
        if(target_adf)assert(full_scalar_connection_release(0x8abc7601,predecessor_reply,cm_free,get_record,&rc) && !rc);
        else assert(full_vef_pinmem_control_connection_release(vpc_caller,predecessor_reply,cm_free,get_record,&rc) && !rc);
        pnc_save();name="normal";
    }
    if(!strcmp(name,"dynamic-caller")){pnc_caller=0x8ff01929;pnc_request->source=pnc_caller;ctput32(pnc_request->data,pnc_caller);}
    if(!strcmp(name,"disabled-or-unrelated")){
        assert(!(target_adf?full_adf_connection_native_dispatch(FULL_PINMEM_CP,pnc_request->data,&pnc_io,&pnc_guard,0,&rc):full_scalar_connection_native_dispatch(FULL_PINMEM_CP,pnc_request->data,&pnc_io,&pnc_guard,0,&rc)));
        for(unsigned int i=32;i<64;i+=4){pnc_request->data[i+1]^=1;rc=77;assert(!pnc_dispatch(&rc) && rc==77 && !pnc_snapshot().started);pnc_request->data[i+1]^=1;}
        pnc_request->bytes=63;assert(!pnc_dispatch(&rc));pnc_request->bytes=64;pnc_finish();return 0;}
    if(!strcmp(name,"bad-wire")){
        unsigned int callbacks_before=pnc_callbacks;
        for(unsigned int i=0;i<6;i++){
            struct full_imaging_io bad=pnc_io;
            if(i==0)bad.size=0;else if(i==1)bad.source=0;else if(i==2)bad.allocate=0;else if(i==3)bad.release=0;else if(i==4)bad.set_source=0;else bad.send=0;
            assert((target_adf?full_adf_connection_native_dispatch(FULL_PINMEM_CP,pnc_request->data,&bad,&pnc_guard,1,&rc):full_scalar_connection_native_dispatch(FULL_PINMEM_CP,pnc_request->data,&bad,&pnc_guard,1,&rc)) && rc==-1021);
        }
        assert(pnc_callbacks==callbacks_before);
        unsigned int offsets[]={0,4,8,10,12,16,24,26,28,30};for(unsigned int i=0;i<sizeof offsets/sizeof *offsets;i++){
            pnc_request->data[offsets[i]]^=1;assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_snapshot().started && !pnc_snapshot().faults);pnc_request->data[offsets[i]]^=1;}
        pnc_finish();return 0;}
    if(!strcmp(name,"live-source-get") || !strcmp(name,"live-peer-get")){
        assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_snapshot().started && !pnc_snapshot().faults && !pnc_allocs && !pnc_request->released);pnc_finish();return 0;}
    if(!strcmp(name,"guard-recheck")){
        pnc_guard_mutation=1;assert(pnc_dispatch(&rc) && rc==-1021 && !pnc_snapshot().started && !pnc_snapshot().faults && !pnc_snapshot().guard_held && !pnc_allocs && !held);
        assert(pnc_reserves==pnc_releases);pin_registry_test_set_state(full_pinmem_registry(),pnc_adf?5u:4u,1);pnc_guard_mutation=0;name="normal";
    }
    pnc_busy=!strcmp(name,"resource-busy");pnc_inline=!strcmp(name,"inline-free") || !strcmp(name,"inline-send-fail");
    pnc_send_error=(!strcmp(name,"send-fail") || !strcmp(name,"inline-send-fail"))?-61:0;
    pnc_request_error=!strcmp(name,"request-free-fail");pnc_cleanup_error=!strcmp(name,"cleanup-fail");
    pnc_recursive=!strcmp(name,"recursive");pnc_recursive_free=!strcmp(name,"recursive-free");pnc_queued_fault=!strcmp(name,"queued-fault");
    pnc_fork_held=!strcmp(name,"fork-held");pnc_duplicate=!strcmp(name,"duplicate-event");pnc_mutate_request=!strcmp(name,"request-mutated");
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){pnc_threaded=1;pnc_send_error=-61;pnc_thread_error=!strcmp(name,"in-flight-free-fail");}
    unsigned int n=0;if(sscanf(name,"alloc-fail-%u",&n)==1)pnc_alloc_fail=n;
    if(sscanf(name,"alloc-alias-%u",&n)==1)pnc_alloc_alias=n;
    if(sscanf(name,"alloc-short-%u",&n)==1)pnc_alloc_short=n;
    if(sscanf(name,"event-%u",&n)==1)pnc_event_fault=n;
    assert(pnc_dispatch(&rc));struct scalar_connection_snapshot s=pnc_snapshot();assert(!held && !s.busy && !s.guard_held);
    assert(pnc_reserves==pnc_releases+(unsigned int)pnc_busy);
    if(pnc_busy){assert(rc==-1021 && !s.started && !s.faults && !pnc_allocs && !pnc_sends);pnc_finish();return 0;}
    assert(s.owner_pid==getpid() && s.initialized && s.native_guarded && s.started && s.requests==1);
    if(pnc_threaded){
        assert(pnc_send_release_faults==1 && !pnc_release_rejects);
        assert(rc==-1021 && s.faults && !s.clean_completion && s.releasing_reply && s.live_reply==pnc_final->data && s.retained_messages==1 && !s.ap_consumed && !pnc_final->released);
        assert(!pthread_mutex_lock(&pnc_thread_mutex));pnc_thread_go=1;assert(!pthread_cond_signal(&pnc_thread_condition));assert(!pthread_mutex_unlock(&pnc_thread_mutex));assert(!pthread_join(pnc_thread,0));
        s=pnc_snapshot();assert(s.faults && !s.clean_completion && !s.releasing_reply && !s.ap_consumed && !s.waiter_frees);
        if(pnc_thread_error){assert(s.live_reply==pnc_final->data && s.retained_messages==1);int f=77;assert(pnc_release(pnc_caller,pnc_final->data,pnc_free,pnc_record,&f) && !f);}
        s=pnc_snapshot();assert(s.reply_freed && s.native_reply_frees==1 && !s.live_reply && !s.retained_messages);pnc_finish();return 0;
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") || !strcmp(name,"fork-held") ||
        !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault") || !strcmp(name,"request-free-fail") || !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"foreign-thread-free");
    if(success){
        assert(!rc && s.connections==1 && s.queued && pnc_allocs==3 && pnc_sends==1 && s.event6_consumed==1);
        if(pnc_request_error)assert(s.faults && !s.clean_completion && !s.request_freed && s.retained_request==pnc_request->data && !pnc_request->released);
        else if(pnc_queued_fault)assert(s.faults && !s.clean_completion && s.request_freed);
        else assert(s.clean_completion && !s.faults && s.request_freed);
        if(!pnc_inline){int f=77;
            if(!strcmp(name,"wrong-owner"))assert(pnc_release(pnc_caller^1u,pnc_final->data,pnc_free,pnc_record,&f) && f==-1021 && !pnc_final->attempts);
            if(!strcmp(name,"reply-free-fail")){pnc_reply_error=1;assert(pnc_release(pnc_caller,pnc_final->data,pnc_free,pnc_record,&f) && f==-59);pnc_reply_error=0;}
            if(!strcmp(name,"foreign-thread-free")){pnc_thread_go=1;assert(!pthread_create(&pnc_thread,0,pnc_thread_release,0));assert(!pthread_join(pnc_thread,0));}
            else assert(pnc_release(pnc_caller,pnc_final->data,pnc_free,pnc_record,&f) && !f);
        }
        s=pnc_snapshot();assert(s.reply_freed && !s.live_reply && !s.retained_messages && s.native_reply_frees==1);
        if(!strcmp(name,"foreign-thread-free"))assert(!s.ap_consumed && !s.waiter_frees);else assert(s.ap_consumed==1 && s.waiter_frees==1);
        if(pnc_recursive_free || pnc_queued_fault || pnc_request_error || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        int f=77;assert(!pnc_release(pnc_caller,pnc_final->data,pnc_free,pnc_record,&f));
        if(pnc_reuse){
            struct scalar_connection_snapshot before=pnc_snapshot();unsigned int callbacks=pnc_callbacks;
            assert(!pnc_release(pnc_caller^1u,pnc_retired,pnc_free,pnc_record,&f) && f==77 && pnc_callbacks==callbacks);
            s=pnc_snapshot();assert(!memcmp(&before,&s,sizeof before));
        }
        pnc_request=pnc_new_request();unsigned int before=pnc_allocs;assert(pnc_dispatch(&f) && f==-1021 && pnc_allocs==before && !pnc_request->released);
        if(!target_adf && !strcmp(name,"normal")){
            pnc_preserved();assert(!cm_free(FULL_PINMEM_CP,pnc_request->data));vi_clear_messages();pnc_select_adf();
            pnc_get(FULL_PINMEM_CP,pnc_s,0);pnc_get(FULL_ADF_CP,pnc_p,0);vi_clear_messages();pnc_save();pnc_request=pnc_new_request();pnc_complete_current();}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !pnc_request->released && !pnc_request->attempts && !s.retained_request);
        if(pnc_event_fault || pnc_mutate_request)assert(s.pending_event6 && !s.event6_consumed && s.retained_messages==1 && s.retained_cleanup==s.event6_answer && !cm_meta(s.event6_answer)->attempts && !pnc_sends);
        if(pnc_duplicate)assert(s.event6_consumed && !s.pending_event6 && !pnc_sends);
        if(pnc_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        unsigned int before=pnc_allocs;int f=77;assert(pnc_dispatch(&f) && f==-1021 && pnc_allocs==before);
    }
    assert(pnc_release_rejects==(unsigned int)(pnc_recursive_free || pnc_queued_fault || !strcmp(name,"wrong-owner")));
    assert(pnc_send_release_faults==(unsigned int)(pnc_inline && pnc_send_error));
    struct scalar_connection_snapshot before=pnc_snapshot();assert(!pnc_init());s=pnc_snapshot();assert(!memcmp(&before,&s,sizeof s));
    pnc_finish();return 0;
}
