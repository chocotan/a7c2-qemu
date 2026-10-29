/* SPDX-License-Identifier: MIT */
/* Actual first-ten fixture, then independent ADF/HDMI transport. No VM claim. */
#define FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN aha_ten_main
#include "test-pinmem-drawinfo-connection.c"
#undef FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN
#include "adf-hdmi-audio-connection.h"
#include "hdmi-device.h"
#include "hdmi-pin-device.h"
static const unsigned int aha_s[4]={5,2,0,FULL_ADF_CP},aha_p[4]={5,1,0,FULL_HDMI_PIN_CP};
static struct connect_message *aha_request,*aha_final;
static unsigned int aha_caller=0x81cf61d3u,aha_allocs,aha_sends,aha_callbacks,aha_reserves,aha_releases;
static unsigned int aha_bad_alloc,aha_alias,aha_bad_size,aha_bad_peer,aha_order,aha_peer_order,aha_marker_order,aha_complete_order;
static int aha_ready,aha_inline,aha_send_error,aha_request_error,aha_cleanup_error,aha_reply_error,aha_busy,aha_mutate,aha_fork_held,aha_recursive_free,aha_guard_fault;
static int aha_bad_readback,aha_threaded,aha_thread_error,aha_thread_started,aha_thread_go;
static pthread_t aha_thread;
static pthread_mutex_t aha_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t aha_condition=PTHREAD_COND_INITIALIZER;
static const struct full_imaging_io aha_io;
static const struct full_adf_proc_guard aha_guard;
struct aha_history {
    struct pd_history previous;
    struct scalar_connection_snapshot tenth;
    struct full_hdmi_snapshot hdmi;
    struct full_vef_snapshot hdmi_pins;
};
static struct aha_history aha_before;
static unsigned char aha_memory[PIN_CONTROL_CAPACITY];
void __real_full_hdmi_snapshot(struct full_hdmi_snapshot *);
void __wrap_full_hdmi_snapshot(struct full_hdmi_snapshot *p){
    __real_full_hdmi_snapshot(p);if(aha_bad_readback && p->audio_pin_connected_known)p->audio_pin_connected=0;
}
static struct full_adf_hdmi_audio_connection_snapshot aha_snapshot(void){
    struct full_adf_hdmi_audio_connection_snapshot s;full_adf_hdmi_audio_connection_snapshot(&s);return s;
}
static void aha_capture(struct aha_history *p){
    memset(p,0,sizeof *p);pd_capture(&p->previous);full_pinmem_drawinfo_connection_snapshot(&p->tenth);__real_full_hdmi_snapshot(&p->hdmi);full_hdmi_pin_snapshot(&p->hdmi_pins);
}
static void aha_preserved(void){
    if(!aha_ready)return;
    struct aha_history a;aha_capture(&a);
    a.previous.previous.adf.pins[9]=aha_before.previous.previous.adf.pins[9];a.previous.previous.adf.pending=aha_before.previous.previous.adf.pending;
    a.hdmi_pins.pins[1]=aha_before.hdmi_pins.pins[1];
    a.hdmi.audio_pin_connected=aha_before.hdmi.audio_pin_connected;a.hdmi.audio_pin_connected_known=aha_before.hdmi.audio_pin_connected_known;
    a.hdmi.audio_pin_connected_writes=aha_before.hdmi.audio_pin_connected_writes;a.hdmi.audio_pin_connected_owner_pid=aha_before.hdmi.audio_pin_connected_owner_pid;
    assert(!memcmp(&a,&aha_before,sizeof a) && !memcmp(connect_memory,aha_memory,sizeof connect_memory));out_preserved_failure();out_check_shadow();
}
static void aha_callback(void){assert(host_pid==getpid());aha_callbacks++;(void)aha_snapshot();aha_preserved();if(held)guarded();}
static unsigned int aha_size(void *p){aha_callback();return cm_size(p);}
static unsigned int aha_source(void *p){aha_callback();return cm_source(p);}
static int aha_free(unsigned int owner,void *p){
    aha_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==aha_request && aha_request_error)return -53;
    if(m==aha_final && aha_reply_error)return -59;
    if(m->allocation && m!=aha_final && aha_cleanup_error)return -47;
    if(m==aha_final && aha_recursive_free){int rc=77;unsigned int n=m->attempts;assert(full_adf_hdmi_audio_connection_release(owner,p,aha_free,0,&rc) && rc==-1021 && n==m->attempts);}
    cm_dispose(m);return 0;
}
static void aha_set(void *p,unsigned int source){
    aha_callback();struct connect_message *m=cm_meta(p);m->source=source;
    if(m->allocation==2){if(aha_bad_peer==1)m->data[64]=1;if(aha_bad_peer==2)m->data[40]=1;if(aha_bad_peer==3)m->source^=1;}
}
static int aha_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    aha_callback();assert(held && owner==aha_caller && count==1);aha_allocs++;
    const unsigned int sizes[3]={64,72,56};assert(aha_allocs<=3 && n==sizes[aha_allocs-1]);
    if(aha_allocs==aha_bad_alloc){*out=0;return -41;}
    if(aha_alias==1){*out=aha_request->data;return 0;}
    if(aha_alias==2 && aha_allocs==2){*out=cm[cm_count-1].data;return 0;}
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=aha_allocs;*out=m->data;if(aha_bad_size)m->bytes--;return 0;
}
static int aha_seed_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){assert(count==1);*out=cm_new(n,owner,ALLOCATOR_SOURCE)->data;return 0;}
static int aha_seed_send(unsigned int dst,void *p){assert(dst==cm_meta(p)->owner && !vc_seed_queued);vc_seed_queued=cm_meta(p);return 0;}
static const struct full_imaging_io aha_seed_io={aha_seed_allocate,cm_free,cm_set,aha_seed_send,cm_size,cm_source,0};
static void aha_get(unsigned int sid,const unsigned int *key,int leave){
    unsigned int dst=0x8a0bcd13u;struct connect_message *m=cm_new(48,sid,dst);ctframe(m->data,48,0,2);ctput32(m->data,dst);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    int rc=77,freed=77,handled=sid==FULL_ADF_CP?full_adf_dispatch(sid,m->data,&aha_seed_io,1,&rc):full_hdmi_pin_dispatch(sid,m->data,&aha_seed_io,1,&rc);
    assert(handled && !rc && m->released && vc_seed_queued);for(unsigned int i=0;i<3;i++)assert(ct32(vc_seed_queued->data+32+4*i)==key[i]);
    assert(ct32(vc_seed_queued->data+44)==1 && ct32(vc_seed_queued->data+48)==sid);
    if(!leave){handled=sid==FULL_ADF_CP?full_adf_release_reply(dst,vc_seed_queued->data,cm_free,0,&freed):full_hdmi_pin_release_reply(dst,vc_seed_queued->data,cm_free,0,&freed);assert(handled && !freed);}vc_seed_queued=0;
}
static void aha_seed_hdmi(void){
    const unsigned int commands[4]={0x10a,0x101,0x117,0x20a},lengths[4]={12,16,12,8};
    for(unsigned int i=0;i<4;i++){
        struct connect_message *m=cm_new(lengths[i],FULL_HDMI_CP,0x8a0bcf13u);memset(m->data,0,m->bytes);
        ctput16(m->data,0x2500);ctput16(m->data+2,commands[i]);ctput16(m->data+4,m->bytes);ctput16(m->data+6,1);
        if(m->bytes>8)m->data[8]=3;
        if(i==1){m->data[9]=4;m->data[10]=5;m->data[11]=6;m->data[12]=7;m->data[13]=8;}
        if(i==2)m->data[9]=17;
        int rc=77;assert(full_hdmi_dispatch(FULL_HDMI_CP,m->data,&aha_seed_io,FULL_HDMI_BOOT,&rc) && !rc && m->released && vc_seed_queued);
        assert(full_hdmi_release_reply(0x8a0bcf13u,vc_seed_queued->data,cm_free,0,&rc) && !rc);vc_seed_queued=0;
    }
}
static struct connect_message *aha_new_request(void){
    struct connect_message *m=cm_new(64,FULL_ADF_CP,aha_caller);ctframe(m->data,64,1,2);ctput32(m->data,aha_caller);ctput32(m->data+20,0x0017855c);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,aha_s[i]);ctput32(m->data+48+4*i,aha_p[i]);}return m;
}
static int aha_reserve(void){aha_callback();aha_reserves++;return aha_busy?-EBUSY:reserve();}
static void aha_release_guard(void){
    aha_callback();assert(held && aha_snapshot().guard_held);aha_releases++;
    if(aha_guard_fault){int rc=77;assert(full_adf_hdmi_audio_connection_release(aha_caller^1u,aha_final->data,aha_free,0,&rc) && rc==-1021);}release_guard();
}
static int aha_dispatch(int *rc){return full_adf_hdmi_audio_connection_dispatch(FULL_ADF_CP,aha_request->data,&aha_io,&aha_guard,1,rc);}
static void aha_pins(unsigned int source,unsigned int peer,unsigned int pending){
    struct full_vef_snapshot a,b;full_adf_snapshot(&a);full_hdmi_pin_snapshot(&b);assert(a.pins[9].state==source && b.pins[1].state==peer && a.pending==pending && !b.pending);
}
static void aha_record(const char *tag,const char *text){
    aha_callback();aha_order++;fprintf(stdout,"%s%s\n",tag,text);
    if(!strcmp(tag,"FULL_ADF_HDMI_AUDIO_CONNECT_PEER_REQUEST "))aha_pins(2,1,1);
    if(!strcmp(tag,"FULL_ADF_HDMI_AUDIO_CONNECT_PEER_REPLY ")){aha_pins(2,0,1);aha_peer_order=aha_order;assert(!aha_snapshot().marker_readbacks);}
    if(!strcmp(tag,"FULL_ADF_HDMI_AUDIO_CONNECT_HDMI_MARKER_READBACK ")){aha_pins(2,0,1);aha_marker_order=aha_order;assert(aha_snapshot().marker_value==1 && aha_snapshot().marker_known && aha_snapshot().marker_writes==1);}
    if(!strcmp(tag,"FULL_ADF_HDMI_AUDIO_CONNECT_SOURCE_COMPLETED ")){aha_pins(0,0,1);aha_complete_order=aha_order;assert(aha_snapshot().source_handler_completed);}
    if(!strcmp(tag,"FULL_ADF_HDMI_AUDIO_CONNECT_REQUEST ")){
        if(aha_mutate)aha_request->data[20]^=1;
        int rc=77;assert(aha_dispatch(&rc) && rc==-1021 && aha_snapshot().requests==1);
        if(aha_fork_held){pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!aha_snapshot().initialized && full_adf_hdmi_audio_connection_owner_init()==-1021);assert(aha_dispatch(&rc) && rc==-1021);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    }
}
static int aha_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&aha_thread_mutex));aha_thread_started=1;assert(!pthread_cond_signal(&aha_condition));
    while(!aha_thread_go)assert(!pthread_cond_wait(&aha_condition,&aha_thread_mutex));
    assert(!pthread_mutex_unlock(&aha_thread_mutex));return aha_thread_error?-59:cm_free(owner,p);
}
static void *aha_thread_release(void *unused){
    (void)unused;int rc=77;assert(full_adf_hdmi_audio_connection_release(aha_caller,aha_final->data,aha_thread_free,0,&rc) && rc==(aha_thread_error?-59:0));return 0;
}
static int aha_send(unsigned int dst,void *p){
    aha_callback();aha_final=cm_meta(p);assert(dst==aha_caller && aha_final->allocation==3 && aha_final->bytes==56 && aha_final->source==FULL_ADF_CP);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,aha_s[i]);assert(!memcmp(p,expected,56));
    struct full_adf_hdmi_audio_connection_snapshot s=aha_snapshot();assert(s.marker_value==1 && s.marker_known && s.marker_writes==1 && s.marker_readbacks==1 && !s.marker_old_known);
    assert(s.source_handler_completed && s.posthook_checked && !s.callback_selected && s.predecessor_preserved && s.live_reply==p);
    assert(!s.dmm_allocations && !s.notifications && !s.clock_writes && !s.cache_writes && !s.mmio_writes && !s.original_CP_memory_identity_verified);
    assert(aha_peer_order<aha_marker_order && aha_marker_order<aha_complete_order);aha_pins(0,0,1);aha_sends++;
    if(aha_threaded){assert(!pthread_mutex_lock(&aha_thread_mutex));assert(!pthread_create(&aha_thread,0,aha_thread_release,0));while(!aha_thread_started)assert(!pthread_cond_wait(&aha_condition,&aha_thread_mutex));assert(!pthread_mutex_unlock(&aha_thread_mutex));}
    if(aha_inline){int rc=77;assert(full_adf_hdmi_audio_connection_release(dst,p,aha_free,aha_record,&rc) && !rc);}return aha_send_error;
}
static const struct full_imaging_io aha_io={aha_allocate,aha_free,aha_set,aha_send,aha_size,aha_source,aha_record};
static const struct full_adf_proc_guard aha_guard={aha_reserve,aha_release_guard};
static void aha_finish(void){aha_preserved();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("ADF_HDMI_AUDIO_CONNECTION_HOST_TEST_PASS");}
int main(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);assert(!setvbuf(stdout,0,_IONBF,0));const char *name=argv[1];int rc=77;
    if(strcmp(name,"uninitialized"))assert(!full_adf_hdmi_audio_connection_owner_init());
    if(!strcmp(name,"dynamic-caller"))aha_caller=0x8fed1023u;
    aha_request=aha_new_request();
    if(!strcmp(name,"disabled")){assert(!full_adf_hdmi_audio_connection_dispatch(FULL_ADF_CP,aha_request->data,&aha_io,&aha_guard,0,&rc) && rc==77);aha_finish();return 0;}
    if(!strcmp(name,"uninitialized") || !strcmp(name,"fork")){
        if(!strcmp(name,"uninitialized")){assert(aha_dispatch(&rc) && rc==-1021 && !aha_callbacks);aha_finish();return 0;}
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!aha_snapshot().initialized && full_adf_hdmi_audio_connection_owner_init()==-1021);assert(aha_dispatch(&rc) && rc==-1021 && !aha_callbacks);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));aha_finish();return 0;
    }
    if(!strcmp(name,"missing-io")){
        for(unsigned int i=0;i<6;i++){struct full_imaging_io bad=aha_io;if(i==0)bad.allocate=0;if(i==1)bad.release=0;if(i==2)bad.set_source=0;if(i==3)bad.send=0;if(i==4)bad.size=0;if(i==5)bad.source=0;assert(full_adf_hdmi_audio_connection_dispatch(FULL_ADF_CP,aha_request->data,&bad,&aha_guard,1,&rc) && rc==-1021);}
        const struct full_adf_proc_guard bad={0,aha_release_guard};assert(full_adf_hdmi_audio_connection_dispatch(FULL_ADF_CP,aha_request->data,&aha_io,&bad,1,&rc) && rc==-1021);assert(!aha_callbacks && !aha_snapshot().requests);aha_finish();return 0;
    }
    if(!strcmp(name,"malformed")){
        for(unsigned int i=32;i<64;i+=4){aha_request->data[i]^=1;rc=77;assert(!aha_dispatch(&rc) && rc==77);aha_request->data[i]^=1;}
        const unsigned int offsets[]={0,4,8,10,12,16,24,26,28,30};for(unsigned int i=0;i<sizeof offsets/sizeof *offsets;i++){aha_request->data[offsets[i]]^=1;assert(aha_dispatch(&rc) && rc==-1021);aha_request->data[offsets[i]]^=1;}
        aha_request->source^=1;assert(aha_dispatch(&rc) && rc==-1021);assert(!aha_snapshot().faults && !aha_snapshot().requests && !aha_allocs);aha_finish();return 0;
    }
    assert(aha_dispatch(&rc) && rc==-1021 && aha_snapshot().unadmitted_count==1 && !aha_snapshot().faults && !aha_snapshot().requests && !aha_allocs && !aha_request->released);
    if(!strcmp(name,"no-prior")){aha_finish();return 0;}
    assert(!cm_free(FULL_ADF_CP,aha_request->data));vi_clear_messages();
    if(!strcmp(name,"no-ten") || !strcmp(name,"ten-not-freed")){
        pd_seed(argv[2],"normal");pd_get(FULL_PINMEM_CP,pd_s,0);pd_get(NATIVE_DRAWINFO_CP,pd_p,0);
        if(!strcmp(name,"ten-not-freed")){assert(!full_pinmem_drawinfo_connection_owner_init());pd_request=pd_new_request();assert(pd_dispatch(&rc) && !rc && pd_final);}
    }else{char *args[]={"test","normal",argv[2],0};assert(!aha_ten_main(3,args));vi_clear_messages();}
    alarm(30);aha_get(FULL_ADF_CP,aha_s,0);aha_get(FULL_HDMI_PIN_CP,aha_p,!strcmp(name,"live-get"));aha_seed_hdmi();
    if(!strcmp(name,"no-ten") || !strcmp(name,"ten-not-freed") || !strcmp(name,"live-get")){aha_request=aha_new_request();assert(aha_dispatch(&rc) && rc==-1021 && !aha_snapshot().requests && !aha_snapshot().faults && !aha_allocs);aha_finish();return 0;}
    if(!strcmp(name,"video-preserved"))full_hdmi_pin_test_set_state(0,0);
    vi_clear_messages();aha_capture(&aha_before);memcpy(aha_memory,connect_memory,sizeof connect_memory);aha_ready=1;aha_request=aha_new_request();
    assert(aha_before.tenth.clean_completion && aha_before.tenth.ap_consumed==1 && aha_before.tenth.native_guarded && !aha_before.hdmi.audio_pin_connected_known && !aha_before.hdmi.audio_pin_connected_writes);
    if(!strcmp(name,"guard-busy"))aha_busy=1;
    if(!strcmp(name,"inline-free"))aha_inline=1;
    if(!strcmp(name,"send-fail"))aha_send_error=-61;
    if(!strcmp(name,"inline-send-fail")){aha_inline=1;aha_send_error=-61;}
    if(!strcmp(name,"request-free-fail"))aha_request_error=1;
    if(!strcmp(name,"request-mutated"))aha_mutate=1;
    if(!strcmp(name,"cleanup-fail")){aha_bad_alloc=2;aha_cleanup_error=1;}
    if(!strcmp(name,"size-alias"))aha_bad_size=1;
    if(!strcmp(name,"request-alias"))aha_alias=1;
    if(!strcmp(name,"answer-alias"))aha_alias=2;
    if(!strcmp(name,"peer-status"))aha_bad_peer=1;
    if(!strcmp(name,"peer-key"))aha_bad_peer=2;
    if(!strcmp(name,"peer-sid"))aha_bad_peer=3;
    if(!strcmp(name,"marker-readback"))aha_bad_readback=1;
    if(!strcmp(name,"fork-held"))aha_fork_held=1;
    if(!strcmp(name,"recursive-free"))aha_recursive_free=1;
    if(!strcmp(name,"guard-release-fault"))aha_guard_fault=1;
    if(!strcmp(name,"inflight-send-fail") || !strcmp(name,"inflight-free-fail")){aha_threaded=1;aha_send_error=-61;aha_thread_error=!strcmp(name,"inflight-free-fail");}
    unsigned int n=0;if(sscanf(name,"alloc-%u",&n)==1)aha_bad_alloc=n;
    assert(aha_dispatch(&rc));struct full_adf_hdmi_audio_connection_snapshot s=aha_snapshot();assert(!held && !s.busy && !s.guard_held && aha_reserves==aha_releases+(unsigned int)aha_busy);
    if(aha_busy){assert(rc==-1021 && !s.requests && !s.faults && !aha_allocs);aha_finish();return 0;}
    if(aha_threaded){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.releasing_reply && s.live_reply==aha_final->data && !aha_final->attempts && !aha_final->released);
        assert(!pthread_mutex_lock(&aha_thread_mutex));aha_thread_go=1;assert(!pthread_cond_signal(&aha_condition));assert(!pthread_mutex_unlock(&aha_thread_mutex));assert(!pthread_join(aha_thread,0));s=aha_snapshot();
        if(aha_thread_error){assert(s.live_reply==aha_final->data && s.retained_messages==1);int freed=77;assert(full_adf_hdmi_audio_connection_release(aha_caller,aha_final->data,aha_free,aha_record,&freed) && !freed);}
        s=aha_snapshot();assert(s.faults && !s.clean_completion && !s.live_reply && !s.retained_messages);aha_finish();return 0;
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"video-preserved") || !strcmp(name,"duplicate") || !strcmp(name,"early-then-ready") || aha_inline || aha_request_error || aha_fork_held || aha_recursive_free || aha_guard_fault || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-tid-free");
    if(aha_send_error)success=0;
    if(success){
        assert(!rc && s.connections==1 && s.queued==1 && aha_sends==1 && aha_allocs==3 && s.request_freed==!aha_request_error);aha_pins(0,0,0);
        if(aha_request_error)assert(s.faults && !s.clean_completion && s.retained_request==aha_request->data && !aha_request->released);else if(!aha_guard_fault)assert(s.clean_completion && !s.faults);
        if(!aha_inline){
            int freed=77;if(!strcmp(name,"wrong-owner"))assert(full_adf_hdmi_audio_connection_release(aha_caller^1u,aha_final->data,aha_free,aha_record,&freed) && freed==-1021 && !aha_final->attempts);
            if(!strcmp(name,"reply-free-fail")){aha_reply_error=1;assert(full_adf_hdmi_audio_connection_release(aha_caller,aha_final->data,aha_free,aha_record,&freed) && freed==-59);aha_reply_error=0;}
            if(!strcmp(name,"wrong-tid-free")){aha_thread_go=1;assert(!pthread_create(&aha_thread,0,aha_thread_release,0));assert(!pthread_join(aha_thread,0));}else assert(full_adf_hdmi_audio_connection_release(aha_caller,aha_final->data,aha_free,aha_record,&freed) && !freed);
        }
        s=aha_snapshot();assert(s.reply_freed==1 && s.native_reply_frees==1 && !s.live_reply && !s.retained_messages);
        if(!strcmp(name,"wrong-tid-free"))assert(!s.ap_consumed && !s.waiter_frees && s.faults && !s.clean_completion);else assert(s.ap_consumed==1 && s.waiter_frees==1);
        if(aha_request_error || aha_recursive_free || aha_guard_fault || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        if(!strcmp(name,"duplicate")){aha_request=aha_new_request();assert(aha_dispatch(&rc) && rc==-1021 && aha_allocs==3 && aha_sends==1 && !aha_request->released);}
        puts("FIRST_TEN_PLUS_EDGE13_ELEVEN_CONNECTIONS no_claim_for_edges11_12=1 capture_verified=0");
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.queued && !s.connections && !aha_request->released && !aha_request->attempts && !s.retained_request);
        if(aha_cleanup_error)assert(s.retained_cleanup && s.retained_messages);
        if(aha_bad_peer){struct full_hdmi_snapshot h;__real_full_hdmi_snapshot(&h);assert(!h.audio_pin_connected_known && !h.audio_pin_connected_writes && !aha_sends);}
        if(aha_bad_readback){struct full_hdmi_snapshot h;__real_full_hdmi_snapshot(&h);assert(h.audio_pin_connected_known==1 && h.audio_pin_connected==1 && h.audio_pin_connected_writes==1 && !aha_sends);}
        unsigned int allocated=aha_allocs;assert(aha_dispatch(&rc) && rc==-1021 && aha_allocs==allocated);
    }
    struct full_adf_hdmi_audio_connection_snapshot saved=aha_snapshot();assert(!full_adf_hdmi_audio_connection_owner_init());s=aha_snapshot();assert(!memcmp(&s,&saved,sizeof s));aha_finish();return 0;
}
