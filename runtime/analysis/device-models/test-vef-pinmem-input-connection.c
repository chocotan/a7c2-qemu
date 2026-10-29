/* SPDX-License-Identifier: MIT */
/* Actual first-five providers and byte-array backing; no VM/capture evidence. */
#define FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN vi_control_prerequisite_main
#include "test-imaging-control-connection.c"
#undef FULL_IMAGING_CONTROL_CONNECTION_TEST_MAIN
#include "imaging-adf-connection.h"
#include "adf-device.h"
#include "infrabb-vef-connection.h"
#include "infrabb-vef-control-connection.h"
#include "pin-connection.h"
#include "pinmem-device.h"
#include "vef-path-device.h"
#include "vef-pinmem-input-connection.h"
#include "pin-format.h"
static const unsigned int vc_s[4]={8,2,0,NATIVE_INFRABB_CP},vc_p[4]={8,1,0,FULL_VEF_CP};
static unsigned int vc_caller=0x81ce1234;
static struct connect_message *vc_seed_queued;
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
    char *old[]={"test","normal",(char *)seed,0};assert(!vi_control_prerequisite_main(3,old));alarm(30);
    for(unsigned int i=0;i<cm_count;i++)assert(cm[i].released);
    cm_count=0;
    const unsigned int s[4]={3,2,0,NATIVE_INFRAIMAGING_CP},p[4]={3,1,0,FULL_ADF_CP};
    vc_get(NATIVE_INFRAIMAGING_CP,s,1,0);vc_get(FULL_ADF_CP,p,1,0);assert(!full_imaging_adf_connection_owner_init());
    struct connect_message *m=vc_pair_request(NATIVE_INFRAIMAGING_CP,s,p);const struct full_adf_proc_guard g={reserve,release_guard};int rc=77,freed=77;
    assert(full_imaging_adf_connection_dispatch(NATIVE_INFRAIMAGING_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);
    assert(full_imaging_adf_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);vc_seed_queued=0;
    const unsigned int os[4]={0,2,3,FULL_VEF_CP},op[4]={0,1,1,FULL_PINMEM_CP};
    vc_get(FULL_VEF_CP,os,1,0);vc_get(FULL_PINMEM_CP,op,1,0);m=vc_pair_request(FULL_VEF_CP,os,op);
    assert(full_pin_connection_dispatch(FULL_VEF_CP,m->data,&vc_seed_io,2,&rc) && !rc && m->released && vc_seed_queued);
    assert(full_pin_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);vc_seed_queued=0;
    static const unsigned char wire[10]={0x0d,0x20,0x49,1,10,0,1,0x80,1,0};
    m=cm_new(10,FULL_VEF_PATH_INPUT,vc_caller);memcpy(m->data,wire,10);const struct full_vef_path_guard pg={reserve,release_guard};assert(!full_vef_path_owner_init());
    assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,m->data,&vc_seed_io,&pg,1,&rc) && !rc && m->released && vc_seed_queued);
    assert(full_vef_path_release_reply(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);vc_seed_queued=0;
    const unsigned int fs[4]={0,2,1,NATIVE_INFRABB_CP},fp[4]={0,1,1,FULL_VEF_CP};
    vc_get(NATIVE_INFRABB_CP,fs,1,0);vc_get(FULL_VEF_CP,fp,1,0);assert(!full_infrabb_vef_connection_owner_init());m=vc_pair_request(NATIVE_INFRABB_CP,fs,fp);
    assert(full_infrabb_vef_connection_dispatch(NATIVE_INFRABB_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);
    if(!leave_fourth)assert(full_infrabb_vef_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);
    vc_seed_queued=0;
}
static const unsigned int vi_s[4]={0,2,2,FULL_VEF_CP},vi_p[4]={0,1,0,FULL_PINMEM_CP};
static const unsigned int vi_sizes[15]={64,72,152,152,152,80,152,152,80,216,216,80,216,216,56};
static struct connect_message *vi_request,*vi_final;
static unsigned int vi_caller=0x81ce1234,vi_allocs,vi_sends,vi_callbacks,vi_bad_alloc,vi_bad_kind,vi_bad_source,vi_corrupt,vi_offset,vi_source_phase[16],vi_bad_phase;
static unsigned int vi_backing_hop,vi_backing_offset,vi_status_fault,vi_notify_order,vi_consumed,vi_retired;
static int vi_inline,vi_send_error,vi_request_error,vi_reply_error,vi_cleanup_error,vi_recursive,vi_busy,vi_recursive_free,vi_publish_fault,vi_fork_held;
static int vi_threaded,vi_thread_error,vi_thread_started,vi_thread_go,vi_history_ready;
static pthread_t vi_reply_thread;
static pthread_mutex_t vi_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t vi_thread_condition=PTHREAD_COND_INITIALIZER;
static struct full_imaging_pin_connection_snapshot vi_first_before;
static struct full_imaging_control_connection_snapshot vi_control_before;
static struct full_imaging_adf_connection_snapshot vi_audio_before;
static struct full_infrabb_vef_connection_snapshot vi_fourth_before;
static struct full_infrabb_vef_control_connection_snapshot vi_fifth_before;
static struct pin_connection_snapshot vi_old_before;
static struct full_vef_path_snapshot vi_path_before;
static struct pin_control_snapshot vi_pool_before;
static const struct full_imaging_io vi_io;
static const struct full_adf_proc_guard vi_guard;
void __real_full_vef_path_snapshot(struct full_vef_path_snapshot *);
void __wrap_full_vef_path_snapshot(struct full_vef_path_snapshot *out){
    __real_full_vef_path_snapshot(out);
    if(vi_status_fault==1)out->runtime_status22_known=0;
    if(vi_status_fault==2)out->runtime_status22=0xf;
    if(vi_status_fault==3)out->runtime_status22=0x11;
    if(vi_status_fault==4)out->runtime_status22_writer_generation=0;
    if(vi_status_fault==5)out->runtime_status22_writes=0;
}
static struct full_vef_pinmem_input_connection_snapshot vi_snapshot(void){
    struct full_vef_pinmem_input_connection_snapshot s;full_vef_pinmem_input_connection_snapshot(&s);return s;
}
static void vi_clear_messages(void){for(unsigned int i=0;i<cm_count;i++)assert(cm[i].released);cm_count=0;}
static void vi_history(const char *seed,int leave_fifth){
    vc_history(seed,0);vi_clear_messages();
    vc_get(NATIVE_INFRABB_CP,vc_s,1,0);vc_get(FULL_VEF_CP,vc_p,1,0);assert(!full_infrabb_vef_control_connection_owner_init());
    const struct full_adf_proc_guard g={reserve,release_guard};struct connect_message *m=vc_pair_request(NATIVE_INFRABB_CP,vc_s,vc_p);int rc=77,freed=77;
    assert(full_infrabb_vef_control_connection_dispatch(NATIVE_INFRABB_CP,m->data,&vc_seed_io,&g,1,&rc) && !rc && m->released && vc_seed_queued);
    if(!leave_fifth)assert(full_infrabb_vef_control_connection_release(vc_caller,vc_seed_queued->data,cm_free,get_record,&freed) && !freed);
    vc_seed_queued=0;
    if(!leave_fifth)vi_clear_messages();
}
static void vi_save(void){
    full_imaging_pin_connection_snapshot(&vi_first_before);full_imaging_control_connection_snapshot(&vi_control_before);
    full_imaging_adf_connection_snapshot(&vi_audio_before);full_infrabb_vef_connection_snapshot(&vi_fourth_before);
    full_infrabb_vef_control_connection_snapshot(&vi_fifth_before);full_pin_connection_snapshot(&vi_old_before);
    full_vef_path_snapshot(&vi_path_before);pin_control_snapshot(&vi_pool_before);vi_history_ready=1;
    assert(vi_pool_before.allocations==4 && vi_pool_before.releases==4 && !vi_pool_before.live);
}
static void vi_historical(void){
    if(!vi_history_ready)return;
    struct full_imaging_pin_connection_snapshot f;full_imaging_pin_connection_snapshot(&f);
    f.format=vi_first_before.format;f.forwarded_formats=vi_first_before.forwarded_formats;f.forwarded_handle=vi_first_before.forwarded_handle;
    assert(!memcmp(&f,&vi_first_before,sizeof f));
    struct full_infrabb_vef_connection_snapshot v;full_infrabb_vef_connection_snapshot(&v);
    memcpy(v.format.current,vi_fourth_before.format.current,20);memcpy(v.format.expected,vi_fourth_before.format.expected,16);
    v.format.current_fnv=vi_fourth_before.format.current_fnv;v.format.forwarded_vef_payload_fnv=vi_fourth_before.format.forwarded_vef_payload_fnv;
    v.format.forwarded_bb_payload_fnv=vi_fourth_before.format.forwarded_bb_payload_fnv;
    v.forwarded_vef_formats=vi_fourth_before.forwarded_vef_formats;v.forwarded_bb_formats=vi_fourth_before.forwarded_bb_formats;v.forwarded_format_handle=vi_fourth_before.forwarded_format_handle;
    assert(!memcmp(&v,&vi_fourth_before,sizeof v));
    struct full_imaging_control_connection_snapshot c;full_imaging_control_connection_snapshot(&c);assert(!memcmp(&c,&vi_control_before,sizeof c));
    struct full_imaging_adf_connection_snapshot a;full_imaging_adf_connection_snapshot(&a);assert(!memcmp(&a,&vi_audio_before,sizeof a));
    struct full_infrabb_vef_control_connection_snapshot z;full_infrabb_vef_control_connection_snapshot(&z);assert(!memcmp(&z,&vi_fifth_before,sizeof z));
    struct pin_connection_snapshot o;full_pin_connection_snapshot(&o);assert(!memcmp(&o,&vi_old_before,sizeof o));
    struct full_vef_path_snapshot p;__real_full_vef_path_snapshot(&p);assert(!memcmp(&p,&vi_path_before,sizeof p));out_preserved_failure();out_check_shadow();
}
static void vi_callback(void){assert(host_pid==getpid());vi_callbacks++;(void)vi_snapshot();vi_historical();if(held)guarded();}
static unsigned int vi_size(void *p){vi_callback();return cm_size(p);}
static unsigned int vi_source(void *p){vi_callback();return cm_source(p);}
static int vi_free(unsigned int owner,void *p){
    vi_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==vi_request && vi_request_error)return -53;
    if(m==vi_final && vi_reply_error)return -59;
    if(m->allocation && m!=vi_final && vi_cleanup_error)return -47;
    if(m==vi_final && vi_recursive_free){int rc=77;unsigned int attempts=m->attempts;
        assert(full_vef_pinmem_input_connection_release(owner,p,vi_free,0,&rc) && rc==-1021 && m->attempts==attempts);}
    cm_dispose(m);return 0;
}
static void vi_set(void *p,unsigned int sid){
    vi_callback();struct connect_message *m=cm_meta(p);assert(m->allocation<=15);unsigned int phase=++vi_source_phase[m->allocation];
    m->source=m->allocation==vi_bad_source && (!vi_bad_phase || phase==vi_bad_phase)?1234:sid;
    if(m->allocation==vi_corrupt && (!vi_bad_phase || phase==vi_bad_phase))m->data[vi_offset]^=1;
}
static int vi_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    vi_callback();assert(held && owner==vi_caller && count==1);vi_allocs++;assert(vi_allocs<=15 && n==vi_sizes[vi_allocs-1]);
    if(vi_allocs==vi_bad_alloc){
        if(vi_bad_kind==1){*out=0;return -41;}if(vi_bad_kind==2){*out=0;return 0;}if(vi_bad_kind==3){*out=vi_request->data;return 0;}
        if(vi_bad_kind==6){assert(vi_allocs==2);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=vi_allocs;*out=m->data;
    if(vi_allocs==vi_bad_alloc){if(vi_bad_kind==4)m->bytes=n-1;if(vi_bad_kind==5)return -43;}return 0;
}
static int vi_reserve(void){vi_callback();return vi_busy?-EBUSY:reserve();}
static void vi_release_guard(void){vi_callback();assert(held && vi_snapshot().guard_held);release_guard();}
static void vi_record(const char *tag,const char *text){
    vi_callback();fprintf(stdout,"%s%s\n",tag,text);
    if(!strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_PEER_REQUEST ") || !strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_PEER_REPLY ")){
        struct full_vef_snapshot a,b;full_vef_snapshot(&a);full_pinmem_snapshot(&b);
        assert(a.pins[9].state==2 && a.pending==1 && !b.pending);
        assert(b.pins[0].state==(!strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_PEER_REQUEST ")?1u:0u));
        assert(!memcmp(a.pins[9].self,vi_s,sizeof vi_s) && !memcmp(a.pins[9].peer,vi_p,sizeof vi_p));
        if(!b.pins[0].state)assert(!memcmp(b.pins[0].peer,vi_s,sizeof vi_s));
    }
    if(!strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_FORMAT_NOTIFY ")){
        vi_notify_order++;assert(vi_notify_order<=3);
        if(vi_backing_hop==vi_notify_order){unsigned int slot=vi_snapshot().buffer_handle&0x3ff;connect_memory[slot*PIN_CONTROL_SLOT_BYTES+vi_backing_offset]^=1;}
    }
    if(!strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_FORMAT_CONSUMED "))vi_consumed++;
    if(!strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_BUFFER_RETIRED ")){assert(vi_consumed==3);vi_retired=1;}
    if(vi_publish_fault && !strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_REPLY_QUEUED ")){int rc=77;
        assert(full_vef_pinmem_input_connection_release(vi_caller^1u,vi_final->data,vi_free,0,&rc) && rc==-1021);}
    if(vi_recursive && !strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_REQUEST ")){int rc=77;
        assert(full_vef_pinmem_input_connection_dispatch(FULL_VEF_CP,vi_request->data,&vi_io,&vi_guard,1,&rc) && rc==-1021);assert(vi_snapshot().requests==1);}
    if(vi_fork_held && !strcmp(tag,"FULL_VEF_PINMEM_INPUT_CONNECT_REQUEST ")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);int rc=77;assert(!vi_snapshot().initialized);
            assert(full_vef_pinmem_input_connection_owner_init()==-1021);
            assert(full_vef_pinmem_input_connection_dispatch(FULL_VEF_CP,vi_request->data,&vi_io,&vi_guard,1,&rc) && rc==-1021);
            assert(!full_vef_pinmem_input_connection_release(vi_caller,vi_request->data,vi_free,vi_record,&rc));_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
}
static int vi_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&vi_thread_mutex));vi_thread_started=1;assert(!pthread_cond_signal(&vi_thread_condition));
    while(!vi_thread_go)assert(!pthread_cond_wait(&vi_thread_condition,&vi_thread_mutex));
    assert(!pthread_mutex_unlock(&vi_thread_mutex));return vi_thread_error?-59:cm_free(owner,p);
}
static void *vi_thread_release(void *unused){
    (void)unused;int rc=77;assert(full_vef_pinmem_input_connection_release(vi_caller,vi_final->data,vi_thread_free,0,&rc));assert(rc==(vi_thread_error?-59:0));return 0;
}
static void vi_effects(void){
    struct full_vef_pinmem_input_connection_snapshot s=vi_snapshot();assert(s.record_bound && !s.record_index && s.peer_ordinal==0 && s.source_slot==9);
    assert(s.record.raw_flags==3 && s.record.code==1 && s.record.component==1 && s.record.width==1920 && s.record.height==1080);
    assert(s.runtime_status22_known && s.runtime_status22==1 && s.runtime_status22_writer_generation==1 && s.runtime_status22_writes==1);
    assert(s.buffer_freed && s.buffer_written && s.payload_fnv==0x37228cd728b41c0dULL && s.peer_requests==1 && s.peer_replies==1);
    assert(s.dmm_requests==9 && s.dmm_replies==9 && s.dmm_allocations==1 && s.dmm_shares==1 && s.dmm_creator_releases==1 && s.dmm_opens==3 && s.dmm_consumer_closes==3 && s.dmm_frees==1);
    assert(s.notifications==3 && s.notifications_consumed==3 && s.reference_readbacks==9 && !s.current_consumer_sid && !s.owners && !s.opens && !s.creator && !s.consumer && !s.consumer_open);
    assert(s.vef_format_consumed && s.bb_format_consumed && s.bb_format_changed==1 && s.imaging_format_consumed && vi_retired && vi_consumed==3);
    struct pin_control_snapshot pool,expected=vi_pool_before;pin_control_snapshot(&pool);
    expected.allocations++;expected.releases++;expected.payload_writes++;expected.consumer_reads+=3;expected.shares++;expected.creator_releases++;
    expected.consumer_opens+=3;expected.consumer_closes+=3;expected.consumer_releases++;assert(!memcmp(&pool,&expected,sizeof pool));
    unsigned int slot=s.buffer_handle&0x3ff;assert(s.buffer_physical==PIN_CONTROL_PHYSICAL+slot*PIN_CONTROL_SLOT_BYTES && s.buffer_cp_virtual==PIN_CONTROL_CP_VIRTUAL+slot*PIN_CONTROL_SLOT_BYTES);
    assert(s.buffer_fnv==cthash(connect_memory+slot*PIN_CONTROL_SLOT_BYTES,80));
    static const unsigned char payload[16]={1,1,3,0,0,0,0,0,0x80,7,0,0,0x38,4,0,0};assert(!memcmp(connect_memory+slot*PIN_CONTROL_SLOT_BYTES+64,payload,16));
    struct full_infrabb_vef_connection_snapshot v;full_infrabb_vef_connection_snapshot(&v);
    unsigned char current[20]={1,0,0,0,0,0,0,0,1,1,3,0,0x80,7,0,0,0x38,4,0,0};
    assert(!memcmp(v.format.current,current,20) && !memcmp(v.format.expected,payload,16));assert(v.forwarded_vef_formats==1 && v.forwarded_bb_formats==1 && v.forwarded_format_handle==s.buffer_handle);
    assert(v.format.forwarded_vef_payload_fnv==s.payload_fnv && v.format.forwarded_bb_payload_fnv==s.payload_fnv);
    struct full_imaging_pin_connection_snapshot f;full_imaging_pin_connection_snapshot(&f);const unsigned int cache[5]={1,1,1920,1080,3};
    assert(!memcmp(f.format.cache,cache,sizeof cache) && f.format.consumed==2 && f.format.payload_fnv64==s.payload_fnv && f.forwarded_formats==1 && f.forwarded_handle==s.buffer_handle);
    struct full_vef_snapshot a,b;full_vef_snapshot(&a);full_pinmem_snapshot(&b);
    assert(!a.pins[9].state && !b.pins[0].state && !memcmp(a.pins[9].peer,vi_p,sizeof vi_p) && !memcmp(b.pins[0].peer,vi_s,sizeof vi_s));vi_historical();
}
static int vi_send(unsigned int owner,void *p){
    vi_callback();struct full_vef_pinmem_input_connection_snapshot s=vi_snapshot();vi_final=cm_meta(p);
    assert(owner==vi_caller && vi_final->allocation==15 && vi_final->bytes==56 && vi_final->source==FULL_VEF_CP);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,vi_s[i]);assert(!memcmp(p,expected,56));
    assert(s.live_reply==p && s.predecessor_preserved && !s.faults);vi_effects();vi_sends++;
    if(vi_threaded){assert(!pthread_mutex_lock(&vi_thread_mutex));assert(!pthread_create(&vi_reply_thread,0,vi_thread_release,0));
        while(!vi_thread_started)assert(!pthread_cond_wait(&vi_thread_condition,&vi_thread_mutex));
        assert(!pthread_mutex_unlock(&vi_thread_mutex));}
    if(vi_inline){int rc=77;assert(full_vef_pinmem_input_connection_release(owner,p,vi_free,vi_record,&rc) && !rc);}return vi_send_error;
}
static const struct full_imaging_io vi_io={vi_allocate,vi_free,vi_set,vi_send,vi_size,vi_source,vi_record};
static const struct full_adf_proc_guard vi_guard={vi_reserve,vi_release_guard};
static struct connect_message *vi_new_request(void){
    struct connect_message *m=cm_new(64,FULL_VEF_CP,vi_caller);ctframe(m->data,64,1,2);ctput32(m->data,vi_caller);ctput32(m->data+20,0x64c10);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,vi_s[i]);ctput32(m->data+48+4*i,vi_p[i]);}return m;
}
static int vi_dispatch(int *rc){return full_vef_pinmem_input_connection_dispatch(FULL_VEF_CP,vi_request->data,&vi_io,&vi_guard,1,rc);}
static void vi_finish(void){vi_historical();for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("VEF_PINMEM_INPUT_CONNECTION_HOST_TEST_PASS");}
#ifndef FULL_VEF_PINMEM_INPUT_CONNECTION_TEST_MAIN
#define FULL_VEF_PINMEM_INPUT_CONNECTION_TEST_MAIN main
#endif
int FULL_VEF_PINMEM_INPUT_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    if(strcmp(name,"uninitialized")){assert(!full_vef_pinmem_input_connection_owner_init());struct full_vef_pinmem_input_connection_snapshot s=vi_snapshot();
        assert(!full_vef_pinmem_input_connection_owner_init());struct full_vef_pinmem_input_connection_snapshot same=vi_snapshot();assert(!memcmp(&s,&same,sizeof s));}
    if(!strcmp(name,"dynamic-caller"))vi_caller=0x8fed1023;
    vi_request=vi_new_request();int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"long") || !strcmp(name,"old-edge")){
        if(!strcmp(name,"short"))vi_request->bytes=63;
        if(!strcmp(name,"long"))vi_request->bytes=65;
        if(!strcmp(name,"old-edge")){ctput32(vi_request->data+40,3);ctput32(vi_request->data+56,1);}
        assert(!full_vef_pinmem_input_connection_dispatch(!strcmp(name,"unrelated")?FULL_PINMEM_CP:FULL_VEF_CP,vi_request->data,&vi_io,&vi_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!vi_snapshot().requests && !vi_allocs && !vi_request->released);vi_finish();return 0;
    }
    if(!strcmp(name,"fork") || !strcmp(name,"uninitialized")){
        if(!strcmp(name,"uninitialized")){assert(vi_dispatch(&rc) && rc==-1021 && !vi_callbacks);vi_finish();return 0;}
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(full_vef_pinmem_input_connection_owner_init()==-1021);assert(!vi_snapshot().initialized);
            assert(vi_dispatch(&rc) && rc==-1021 && !vi_callbacks);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));vi_finish();return 0;
    }
    if(!strcmp(name,"missing-transport")){
        for(unsigned int i=0;i<7;i++){struct full_imaging_io bad=vi_io;
            if(i==0)bad.allocate=0;else if(i==1)bad.release=0;else if(i==2)bad.send=0;else if(i==3)bad.set_source=0;else if(i==4)bad.size=0;else if(i==5)bad.source=0;else bad.record=0;
            assert(full_vef_pinmem_input_connection_dispatch(FULL_VEF_CP,vi_request->data,&bad,&vi_guard,1,&rc) && rc==-1021);}
        assert(!vi_callbacks && !vi_snapshot().requests && !vi_snapshot().faults);vi_finish();return 0;
    }
    if(!strcmp(name,"invalid-source")){vi_request->source^=1;assert(vi_dispatch(&rc) && rc==-1021 && !vi_snapshot().requests && !vi_snapshot().faults);vi_finish();return 0;}
    assert(vi_dispatch(&rc) && rc==-1021);struct full_vef_pinmem_input_connection_snapshot early=vi_snapshot();
    assert(!early.requests && !early.faults && early.unadmitted_count==1 && !vi_allocs && !vi_request->released);
    if(!strcmp(name,"no-prior")){assert(vi_dispatch(&rc) && rc==-1021 && vi_snapshot().unadmitted_count==2);vi_finish();return 0;}
    vi_history(argv[2],!strcmp(name,"no-fifth-AP-free"));
    if(strcmp(name,"no-source-get"))vc_get(FULL_VEF_CP,vi_s,1,0);
    if(strcmp(name,"no-peer-get"))vc_get(FULL_PINMEM_CP,vi_p,1,!strcmp(name,"live-peer-get"));
    if(!strcmp(name,"no-fifth-AP-free") || !strcmp(name,"live-peer-get") || !strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get")){
        vi_request=vi_new_request();assert(vi_dispatch(&rc) && rc==-1021 && !vi_snapshot().requests && !vi_snapshot().faults && !vi_allocs && !vi_request->released);vi_finish();return 0;
    }
    vi_clear_messages();vi_save();vi_request=vi_new_request();
    unsigned int nth=0,kind=0,offset=0,phase=0;
    if(sscanf(name,"status-%u",&nth)==1){vi_status_fault=nth;assert(vi_dispatch(&rc) && rc==-1021 && !vi_snapshot().requests && !vi_snapshot().faults && !vi_allocs);vi_status_fault=0;vi_finish();return 0;}
    if(!strcmp(name,"resource-busy"))vi_busy=1;
    if(!strcmp(name,"send-fail"))vi_send_error=-61;
    if(!strcmp(name,"inline-free"))vi_inline=1;
    if(!strcmp(name,"inline-send-fail")){vi_inline=1;vi_send_error=-61;}
    if(!strcmp(name,"request-free-fail"))vi_request_error=1;
    if(!strcmp(name,"recursive"))vi_recursive=1;
    if(!strcmp(name,"fork-held"))vi_fork_held=1;
    if(!strcmp(name,"recursive-free"))vi_recursive_free=1;
    if(!strcmp(name,"queued-fault"))vi_publish_fault=1;
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){vi_threaded=1;vi_send_error=-61;vi_thread_error=!strcmp(name,"in-flight-free-fail");}
    if(!strcmp(name,"cleanup-fail"))vi_cleanup_error=1;
    if(sscanf(name,"alloc-%u-%u",&nth,&kind)==2){vi_bad_alloc=nth;vi_bad_kind=kind;}
    if(sscanf(name,"source-%u-%u",&nth,&phase)==2){vi_bad_source=nth;vi_bad_phase=phase;}
    if(sscanf(name,"wire-%u-%u-%u",&nth,&phase,&offset)==3){vi_corrupt=nth;vi_bad_phase=phase;vi_offset=offset;}
    if(sscanf(name,"backing-%u-%u",&nth,&offset)==2){vi_backing_hop=nth;vi_backing_offset=offset;}
    assert(vi_dispatch(&rc));struct full_vef_pinmem_input_connection_snapshot s=vi_snapshot();
    assert(!held && !s.busy && !s.guard_held && s.owner_pid==getpid());
    if(vi_busy){assert(rc==-1021 && !s.requests && !s.faults && s.unadmitted_count==2 && !vi_sends && !vi_allocs);vi_finish();return 0;}
    assert(s.requests==1 && s.unadmitted_count==1);
    if(vi_threaded){
        assert(rc==-1021 && s.faults && !s.clean_completion && s.live_reply==vi_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !vi_final->released && !vi_final->attempts);
        assert(!pthread_mutex_lock(&vi_thread_mutex));vi_thread_go=1;assert(!pthread_cond_signal(&vi_thread_condition));assert(!pthread_mutex_unlock(&vi_thread_mutex));
        assert(!pthread_join(vi_reply_thread,0));s=vi_snapshot();assert(!s.releasing_reply && s.faults && !s.clean_completion);
        if(vi_thread_error){assert(s.live_reply==vi_final->data && s.retained_messages==1 && !s.ap_consumed && !vi_final->released);
            int f=77;assert(full_vef_pinmem_input_connection_release(vi_caller,vi_final->data,vi_free,vi_record,&f) && !f);}
        s=vi_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages && vi_final->released);vi_finish();return 0;
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") || !strcmp(name,"recursive") || !strcmp(name,"fork-held") ||
        !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"repeat") || !strcmp(name,"request-free-fail") || !strcmp(name,"recursive-free") || !strcmp(name,"queued-fault");
    if(success){
        assert(!rc && s.connections==1 && s.queued && vi_allocs==15 && vi_sends==1);vi_effects();
        if(vi_request_error)assert(s.faults && !s.clean_completion && s.retained_request==vi_request->data && !vi_request->released);
        else if(vi_publish_fault)assert(!s.clean_completion && s.faults && vi_request->released && s.request_freed);
        else assert(s.clean_completion && !s.faults && vi_request->released && s.request_freed);
        if(!vi_inline){
            if(!strcmp(name,"wrong-owner")){int f=77;assert(full_vef_pinmem_input_connection_release(vi_caller^1u,vi_final->data,vi_free,vi_record,&f) && f==-1021 && !vi_final->attempts);}
            if(!strcmp(name,"reply-free-fail")){int f=77;vi_reply_error=1;assert(full_vef_pinmem_input_connection_release(vi_caller,vi_final->data,vi_free,vi_record,&f) && f==-59);vi_reply_error=0;}
            int f=77;assert(full_vef_pinmem_input_connection_release(vi_caller,vi_final->data,vi_free,vi_record,&f) && !f);
        }
        s=vi_snapshot();assert(s.ap_consumed && s.reply_freed && !s.live_reply && !s.retained_messages);
        if(vi_recursive_free || vi_publish_fault || vi_request_error || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        int f=77;assert(!full_vef_pinmem_input_connection_release(vi_caller,vi_final->data,vi_free,vi_record,&f) && f==77);
        if(!strcmp(name,"repeat")){vi_request=vi_new_request();assert(vi_dispatch(&f) && f==-1021 && vi_allocs==15 && vi_sends==1 && !vi_request->released);}
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !vi_request->released && !vi_request->attempts && !s.retained_request);
        if(vi_cleanup_error)assert(s.retained_messages && s.retained_cleanup);
        if(vi_backing_hop){struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(pool.live==1 && !s.buffer_freed && !vi_sends && s.notifications_consumed==vi_backing_hop);
            assert(s.dmm_opens==vi_backing_hop && s.dmm_consumer_closes==vi_backing_hop-1);}
        unsigned int allocations=vi_allocs;int f=77;assert(vi_dispatch(&f) && f==-1021 && vi_allocs==allocations);
        assert(!cm_free(FULL_VEF_CP,vi_request->data));struct full_vef_pinmem_input_connection_snapshot after=vi_snapshot();assert(!memcmp(&s,&after,sizeof s));
    }
    vi_finish();return 0;
}
