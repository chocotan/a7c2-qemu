/* SPDX-License-Identifier: MIT */
/* Compose the actual first ten edges; no predecessor snapshots are fabricated. */
#define FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN osd_ten_main
#include "test-pinmem-drawinfo-connection.c"
#undef FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN
#include "pinmem-osd-connection.h"
#include "../osdpin-registry.h"
#define caller osd_caller
#define meta osd_meta
static const unsigned int os[4]={1,3,0,FULL_OSD_PINMEM_SID},op[4]={1,3,0,FULL_OSD_PEER_SID};
struct osd_message {unsigned char *data;unsigned int bytes,owner,source,id,attempts;int freed;};
static struct osd_message om[256],*oq,*ofinal;
static unsigned int om_count,oa,ocallbacks,osends,caller=0x8c0d0193u;
static unsigned int fail_alloc,alloc_kind,bad_source,wire_alloc,wire_offset,event_fault,request_seq,reply_seq,notice_seq;
static unsigned int bad_dmm_request,bad_dmm_reply,bad_notice;
static int ready,busy,guard_mutation,send_error,request_error,reply_error,cleanup_error,inline_free,foreign_free,recursive,recursive_free;
static _Alignas(256) unsigned char unrelated_osd_backing[FULL_OSD_POOL_BYTES];
static int fork_held,mutate_request,active_mask,unknown_mask,release_resource,change_opaque;
static int threaded,thread_go,thread_started,thread_error;
static pthread_t osd_thread;
static pthread_mutex_t ot_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t ot_cond=PTHREAD_COND_INITIALIZER;
static struct pd_history osd_before;
static struct full_vef_snapshot peer_before;
static unsigned char old_pool_before[PIN_CONTROL_CAPACITY];
static const struct full_imaging_io osd_io;
static const struct full_adf_proc_guard osd_guard;
static struct full_pinmem_osd_connection_snapshot osnap(void){struct full_pinmem_osd_connection_snapshot s;full_pinmem_osd_connection_snapshot(&s);return s;}
static struct osd_message *meta(void *p){for(unsigned int i=om_count;i>0;i--)if(om[i-1].data==p && !om[i-1].freed)return &om[i-1];assert(0);return 0;}
static struct osd_message *new_message(unsigned int n,unsigned int owner,unsigned int source){
    assert(om_count<256);struct osd_message *m=&om[om_count++];*m=(struct osd_message){.data=malloc(n),.bytes=n,.owner=owner,.source=source};assert(m->data);memset(m->data,0,n);return m;
}
static void dispose(struct osd_message *m){assert(!m->freed);m->freed=1;free(m->data);}
static struct osd_message *new_request(void){
    struct osd_message *m=new_message(64,FULL_OSD_PINMEM_SID,caller);ctframe(m->data,64,1,2);ctput32(m->data,caller);ctput32(m->data+20,0x79b5e31u);
    for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,os[i]);ctput32(m->data+48+4*i,op[i]);}return m;
}
static void preserved(void){
    if(!ready)return;
    struct pd_history after;pd_capture(&after);after.previous.pinmem.pins[8]=osd_before.previous.pinmem.pins[8];after.previous.pinmem.pending=osd_before.previous.pinmem.pending;
    assert(!memcmp(&after,&osd_before,sizeof after));assert(!memcmp(old_pool_before,connect_memory,sizeof old_pool_before));
    struct full_vef_snapshot peer;native_osdpin_snapshot(&peer);peer.pins[0]=peer_before.pins[0];assert(!memcmp(&peer,&peer_before,sizeof peer));
    assert(!memcmp(&pnc_speech,&pnc_speech_state_before,sizeof pnc_speech));assert(!memcmp(pnc_speech_memory,pnc_speech_before,sizeof pnc_speech_memory));out_preserved_failure();out_check_shadow();
}
static void callback(void){assert(host_pid==getpid());ocallbacks++;(void)osnap();preserved();if(held && pthread_equal(guard_thread,pthread_self()))guarded();}
static unsigned int size_of(void *p){callback();return meta(p)->bytes;}
static unsigned int source_of(void *p){callback();return meta(p)->source;}
static int release_message(unsigned int owner,void *p){
    callback();struct osd_message *m=meta(p);assert(owner==m->owner);m->attempts++;
    if(m==oq && request_error)return -53;
    if(m==ofinal && reply_error)return -59;
    if(m->id && m!=ofinal && cleanup_error)return -47;
    if(m==ofinal && recursive_free){int r=77;unsigned int attempts=m->attempts;assert(full_pinmem_osd_connection_release(owner,p,release_message,0,&r) && r==-1021 && m->attempts==attempts);}
    dispose(m);return 0;
}
static int allocate_message(unsigned int owner,void **out,unsigned int n,unsigned int count){
    callback();assert(held && count==1 && owner==caller);oa++;
    if(oa==fail_alloc){
        if(alloc_kind==1){*out=0;return -41;}
        if(alloc_kind==3){*out=oq->data;return 0;}
        if(alloc_kind==4){for(unsigned int i=om_count;i>0;i--)if(!om[i-1].freed && &om[i-1]!=oq){*out=om[i-1].data;return 0;}*out=oq->data;return 0;}
    }
    struct osd_message *m=new_message(n,owner,ALLOCATOR_SOURCE);m->id=oa;*out=m->data;
    if(oa==fail_alloc && alloc_kind==2)m->bytes=n-1;
    if(oa==fail_alloc && alloc_kind==5)return -41;
    return 0;
}
static void set_message_source(void *p,unsigned int source){
    callback();struct osd_message *m=meta(p);m->source=m->id==bad_source?1234u:source;
    if(m->id==wire_alloc)m->data[wire_offset]^=1;
}
static int osd_dispatch(int *r){return full_pinmem_osd_connection_native_dispatch(FULL_OSD_PINMEM_SID,oq->data,&osd_io,&osd_guard,1,r);}
static int reserve_osd(void){
    callback();if(busy)return -EBUSY;
    int rc=reserve();if(!rc && guard_mutation)pin_registry_test_set_state(full_pinmem_registry(),8,2);return rc;
}
static void release_osd(void){callback();assert(held && osnap().guard_held);release_guard();}
static void log_message(const char *tag,const char *text){
    callback();fprintf(stdout,"%s%s\n",tag,text);
    if(!strcmp(tag,"FULL_PINMEM_OSD_CONNECT_REQUEST ")){
        if(mutate_request)oq->data[20]^=1;
        if(recursive){int r=77;assert(osd_dispatch(&r) && r==-1021 && osnap().requests==1);}
        if(fork_held){pid_t child=fork();assert(child>=0);if(!child){alarm(2);int r=77;assert(!osnap().initialized && full_pinmem_osd_connection_owner_init()==-1021);assert(osd_dispatch(&r) && r==-1021);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    }
    if(!strcmp(tag,"FULL_PINMEM_OSD_CONNECT_DMM_REQUEST ")){
        request_seq++;struct osd_message *m=&om[om_count-1];assert(m->bytes==40 || m->bytes==152);unsigned int command=ct16(m->data);
        assert(command==0x20 || command==0x21 || command==0x24);assert(m->owner==caller && ct32(m->data+16)==0x0061003cu+(request_seq-1)*4u && ct16(m->data+20)==0x4f00u+request_seq);
        assert(m->source==FULL_OSD_PINMEM_SID || m->source==FULL_OSD_PEER_SID);
        if(request_seq==bad_dmm_request)m->data[4]^=1;
    }
    if(!strcmp(tag,"FULL_PINMEM_OSD_CONNECT_DMM_REPLY ")){reply_seq++;if(reply_seq==bad_dmm_reply)om[om_count-1].data[24]^=1;}
    if(!strcmp(tag,"FULL_PINMEM_OSD_CONNECT_PEER_NOTIFY ") || !strcmp(tag,"FULL_PINMEM_OSD_CONNECT_SOURCE_NOTIFY ")){
        notice_seq++;struct osd_message *m=&om[om_count-1];assert(m->bytes==80);
        unsigned int producer=m->source,receiver=producer==FULL_OSD_PINMEM_SID?FULL_OSD_PEER_SID:FULL_OSD_PINMEM_SID;
        assert(ct32(m->data+32)==1 && ct32(m->data+36)==3 && ct32(m->data+44)==receiver && ct32(m->data+60)==producer && ct32(m->data+64)==0xe1700);
        if(notice_seq==bad_notice)m->data[68]^=0x10;
    }
    if(!strcmp(tag,"FULL_PINMEM_OSD_CONNECT_EVENT6_ENQUEUED ")){
        struct full_pinmem_osd_connection_snapshot s=osnap();unsigned char parameter[12]={0};ctput32(parameter,0x4f534406);
        assert(s.pending_event6 && s.event6_enqueued && !s.event6_consumed && s.phase==1 && s.wait_primary==6 && s.keep_pending==1 && s.context_kind==2);
        assert(s.event6_answer && s.event6_body==(unsigned char *)s.event6_answer+24 && !memcmp(s.event6_parameter,parameter,12));
        assert(!memcmp(s.saved_request,oq->data,64) && s.peer_notifications==4 && s.source_notifications==4);
        if(event_fault<=8 && event_fault)full_pinmem_osd_connection_test_event_corrupt(event_fault);
        if(event_fault==9)((unsigned char *)s.event6_answer)[64]=1;
        if(event_fault==10)((unsigned char *)s.event6_answer)[60]^=1;
        if(event_fault==11)((unsigned char *)s.event6_answer)[68]=1;
    }
    if(!strcmp(tag,"FULL_PINMEM_OSD_CONNECT_FORMAT_WRITTEN ")){
        struct full_pinmem_osd_connection_snapshot s=osnap();
        unsigned int h=s.resources[2][0].handle;
        if(h && !s.source_notifications && (active_mask || unknown_mask || release_resource || change_opaque))assert(0);
        /* Mutate the first source tag100 after real producer write/readback. */
        if(h && s.source_notifications==4){
            if(active_mask || unknown_mask){unsigned char b=active_mask?1:0,k=unknown_mask?0:1;assert(!full_osd_pool_write(1,h,72,&b,&k,1));}
            if(change_opaque){unsigned char b=0x6b,k=0;assert(!full_osd_pool_write(1,h,81,&b,&k,1));}
            if(release_resource)assert(!full_osd_pool_release(1,h));
        }
    }
}
static int thread_release_message(unsigned int owner,void *p){
    pthread_mutex_lock(&ot_mutex);thread_started=1;pthread_cond_signal(&ot_cond);while(!thread_go)pthread_cond_wait(&ot_cond,&ot_mutex);pthread_mutex_unlock(&ot_mutex);
    if(thread_error){callback();struct osd_message *m=meta(p);assert(owner==m->owner);m->attempts++;return -59;}
    return release_message(owner,p);
}
static void *release_other_thread(void *unused){
    (void)unused;int r=77;assert(full_pinmem_osd_connection_release(caller,ofinal->data,threaded?thread_release_message:release_message,0,&r));assert(r==(thread_error?-59:0));return 0;
}
static int send_message(unsigned int owner,void *p){
    callback();ofinal=meta(p);assert(owner==caller && ofinal->bytes==56 && ofinal->source==FULL_OSD_PINMEM_SID);unsigned char expected[56];ctframe(expected,56,0x8001,2);
    for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,os[i]);
    assert(!memcmp(p,expected,56));
    struct full_pinmem_osd_connection_snapshot s=osnap();assert(s.live_reply==p && s.canonical_references && s.history_preserved && s.metadata_ready && s.source_post_updated && s.event6_consumed);
    assert(s.dmm_requests==48 && s.dmm_replies==48 && s.consumer_reads==16 && !s.format.readiness_post_pending);osends++;
    if(inline_free){int r=77;assert(full_pinmem_osd_connection_release(owner,p,release_message,log_message,&r) && !r);}
    if(threaded){assert(!pthread_create(&osd_thread,0,release_other_thread,0));pthread_mutex_lock(&ot_mutex);while(!thread_started)pthread_cond_wait(&ot_cond,&ot_mutex);pthread_mutex_unlock(&ot_mutex);}
    return send_error;
}
static const struct full_imaging_io osd_io={allocate_message,release_message,set_message_source,send_message,size_of,source_of,log_message};
static const struct full_adf_proc_guard osd_guard={reserve_osd,release_osd};
static void get_pin(unsigned int destination,const unsigned int *key,int leave,int wrong_key){
    struct connect_message *m=cm_new(48,destination,get_destination);ctframe(m->data,48,0,2);ctput32(m->data,get_destination);
    for(unsigned int i=0;i<3;i++)ctput32(m->data+32+4*i,key[i]);
    if(wrong_key)ctput32(m->data+32,key[0]|0x100u);
    int r=77,freed=77,handled=destination==FULL_OSD_PINMEM_SID?full_pinmem_dispatch(destination,m->data,&vc_seed_io,1,&r):native_osdpin_dispatch(destination,m->data,&vc_seed_io,1,&r);
    assert(handled && !r && m->released && vc_seed_queued);if(leave){vc_seed_queued=0;return;}
    handled=destination==FULL_OSD_PINMEM_SID?full_pinmem_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed):native_osdpin_release_reply(get_destination,vc_seed_queued->data,cm_free,get_record,&freed);
    assert(handled && !freed);vc_seed_queued=0;
}
static void finish(void){
    preserved();for(unsigned int i=0;i<om_count;i++)if(!om[i].freed)dispose(&om[i]);for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);puts("PINMEM_OSD_CONNECTION_HOST_TEST_PASS");
}
static void verify_resources(void){
    struct full_pinmem_osd_connection_snapshot s=osnap();struct full_osd_pool_snapshot pool;full_osd_pool_snapshot(&pool);
    assert(pool.live==16 && pool.allocations==16 && pool.shares==16 && pool.opens==16 && !pool.releases && !pool.faults);
    assert(s.format.notices==12 && s.format.new100==4 && s.format.new101==4 && s.format.new102==4 && s.format.retained_opens==12);
    assert(s.format.ready && s.format.readiness_transitions==1 && !s.format.readiness_post_pending && s.readiness_post_checks==1 && !s.gpe_ready && !s.frames_verified && !s.capture_verified);
    assert(!s.format.reload100 && !s.format.fifo_submissions && !s.format.output_callbacks && !s.format.completion_callbacks);
    unsigned int handles[16]={0};
    for(unsigned int b=0;b<4;b++)for(unsigned int i=0;i<4;i++){
        const struct full_pinmem_osd_resource *r=&s.resources[b][i];unsigned int count=0,side=b?1:2;unsigned char data[256],known[256];struct full_osd_format_view view;
        assert(!full_osd_pool_read(side,r->handle,0,data,known,256) && !full_osd_format_parse(data,known,256,&view));
        assert(r->handle>0xffff && r->owners==2 && r->opens==2 && r->mapping.handle==r->handle && r->mapping.physical>=0x500010000ULL && r->mapping.cp_alias>=0x81000000u);
        assert(r->bytes_fnv==cthash(data,256) && r->known_fnv==cthash(known,256));for(unsigned int j=0;j<256;j++)count+=known[j];assert(count==r->known_bytes);
        const unsigned int counts[4]={128,78,71,90};assert(count==counts[b]);
        for(unsigned int j=r->used;j<256;j++)assert(data[j]==0xa5 && !known[j]);
        for(unsigned int j=0;j<b*4+i;j++)assert(handles[j]!=r->handle);
        handles[b*4+i]=r->handle;
        if(b==0){assert(!memcmp(s.source_outputs[i].payload,s.format.outputs[i].payload,64));assert(s.source_outputs[i].handle==r->handle);}
        if(b==1){assert(ct32(view.payload+4)==s.resources[0][i].handle);assert(!view.known[10] && !view.known[11]);assert(s.local_pairs[i][0]==i && s.local_pairs[i][1]==4+i);}
        if(b==2){assert(ct32(view.payload)==(i?1u:0u));assert(ct32(s.format.incoming100[i].payload)==1);}
    }
    for(unsigned int i=0;i<16;i++)assert(pool.slots[i].owners==2 && pool.slots[i].open_count==2 && pool.slots[i].creator_open==1 && pool.slots[i].consumer_open==1);
    unsigned int h=0xfeedu;assert(full_osd_pool_allocate(1,&h)==-1021 && h==0xfeedu);
    const unsigned char byte=0,known=1;assert(full_osd_pool_write(1,s.resources[2][0].handle^0x10,0,&byte,&known,1)==-1021);
    assert(s.selected_backing_count==0 && s.selected_cached_count==1 && s.peer_notifications==4 && s.source_notifications==12 && s.notifications_consumed==16 && s.reference_readbacks==48);
    for(unsigned int i=4;i<8;i++)assert(s.local_pairs[i][0]==0xffff && s.local_pairs[i][1]==0xffff);
    for(unsigned int i=0;i<5;i++)assert(!s.source_row_enabled[i] && s.source_row_known[i]==1);
    assert(s.pool.live==16 && s.pool.opens==16 && s.pool.shares==16 && !s.pool.releases);
    puts("ACTUAL_FIRST10_HISTORY_AND_OLD404_SPEECH_UNCHANGED DMM=48 NOTICES=16 LIVE=16 OWNERS=32 OPENS=32 CACHE100_COUNT=1 BACKING100_COUNT=0 capture_verified=0");
}
int main(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(35);assert(!setvbuf(stdout,0,_IONBF,0));const char *name=argv[1];
    if(strcmp(name,"uninitialized"))assert(!full_pinmem_osd_connection_owner_init());
    if(!strcmp(name,"dynamic-caller"))caller=0x8fed1023u;
    oq=new_request();int r=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short") || !strcmp(name,"other-key")){
        if(!strcmp(name,"short"))oq->bytes=63;
        if(!strcmp(name,"other-key"))ctput32(oq->data+36,2);
        assert(!full_pinmem_osd_connection_native_dispatch(!strcmp(name,"unrelated")?FULL_OSD_PEER_SID:FULL_OSD_PINMEM_SID,oq->data,&osd_io,&osd_guard,strcmp(name,"disabled")!=0,&r) && r==77);assert(!oa && !osnap().started);finish();return 0;
    }
    if(!strcmp(name,"uninitialized")){assert(osd_dispatch(&r) && r==-1021 && !ocallbacks);finish();return 0;}
    if(!strcmp(name,"fork")){pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(!osnap().initialized && full_pinmem_osd_connection_owner_init()==-1021);assert(osd_dispatch(&r) && r==-1021 && !ocallbacks);_exit(0);}int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));finish();return 0;}
    if(!strcmp(name,"missing-guard")){assert(full_pinmem_osd_connection_native_dispatch(FULL_OSD_PINMEM_SID,oq->data,&osd_io,0,1,&r) && r==-1021 && !ocallbacks);finish();return 0;}
    if(!strcmp(name,"bad-wire")){unsigned int offsets[]={0,4,8,10,12,16,24,26,28,30};for(unsigned int i=0;i<sizeof offsets/sizeof *offsets;i++){oq->data[offsets[i]]^=1;assert(osd_dispatch(&r) && r==-1021 && !osnap().faults);oq->data[offsets[i]]^=1;}finish();return 0;}
    assert(osd_dispatch(&r) && r==-1021 && !osnap().started && !osnap().faults && !oa);
    if(!strcmp(name,"no-prior")){finish();return 0;}
    dispose(oq);char *args[]={"test",!strcmp(name,"no-ten-AP-free")?"foreign-thread-free":"normal",argv[2],0};
    /* Tenth fixture lacks foreign-free switch; instead leave its actual reply
     * live by dispatching its real production owner after the nine-edge seed. */
    if(!strcmp(name,"no-ten-AP-free")){
        pd_seed(argv[2],"normal");assert(!full_pinmem_drawinfo_connection_owner_init());pd_get(FULL_PINMEM_CP,pd_s,0);pd_get(NATIVE_DRAWINFO_CP,pd_p,0);vi_clear_messages();pd_capture(&pd_before);memcpy(pd_memory_before,connect_memory,sizeof connect_memory);pd_ready=1;pd_request=pd_new_request();assert(pd_dispatch(&r) && !r && !pd_snapshot().ap_consumed);
    }else assert(!osd_ten_main(3,args));
    if(strcmp(name,"no-source-get"))get_pin(FULL_OSD_PINMEM_SID,os,!strcmp(name,"live-source-get"),!strcmp(name,"wrong-source-get"));
    if(strcmp(name,"no-peer-get"))get_pin(FULL_OSD_PEER_SID,op,!strcmp(name,"live-peer-get"),0);
    pd_capture(&osd_before);native_osdpin_snapshot(&peer_before);memcpy(old_pool_before,connect_memory,sizeof old_pool_before);ready=1;oq=new_request();
    if(!strcmp(name,"source-state"))pin_registry_test_set_state(full_pinmem_registry(),8,2);
    if(!strcmp(name,"peer-state"))pin_registry_test_set_state(native_osdpin_registry(),0,2);
    if(!strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get") || !strcmp(name,"live-source-get") || !strcmp(name,"live-peer-get") || !strcmp(name,"wrong-source-get") || !strcmp(name,"source-state") || !strcmp(name,"peer-state") || !strcmp(name,"no-ten-AP-free")){
        assert(osd_dispatch(&r) && r==-1021 && !osnap().started && !osnap().faults && !oa && !oq->freed);finish();return 0;
    }
    if(!strcmp(name,"resource-busy"))busy=1;
    if(!strcmp(name,"guard-mutation"))guard_mutation=1;
    if(!strcmp(name,"active-row"))full_pinmem_osd_connection_test_row(3,1,1);
    if(!strcmp(name,"unknown-row"))full_pinmem_osd_connection_test_row(4,0,0);
    if(!strcmp(name,"preexisting-pool") || !strcmp(name,"full-pool")){
        assert(!full_osd_pool_bind(unrelated_osd_backing,sizeof unrelated_osd_backing,0x500020000ULL,0x82000000u));
        if(!strcmp(name,"full-pool"))for(unsigned int i=0;i<16;i++){unsigned int h=0;assert(!full_osd_pool_allocate(2,&h));}
        struct full_osd_pool_snapshot before,after;full_osd_pool_snapshot(&before);
        assert(osd_dispatch(&r) && r==-1021 && !osnap().started && !osnap().faults && !oa && !oq->freed);
        full_osd_pool_snapshot(&after);assert(!memcmp(&before,&after,sizeof after));finish();return 0;
    }
    if(!strcmp(name,"send-fail") || !strcmp(name,"inline-send-fail") || !strcmp(name,"thread-send-fail") || !strcmp(name,"thread-free-fail"))send_error=-61;
    if(!strcmp(name,"request-free-fail"))request_error=1;
    if(!strcmp(name,"inline-free") || !strcmp(name,"inline-send-fail"))inline_free=1;
    if(!strcmp(name,"foreign-thread-free"))foreign_free=1;
    if(!strcmp(name,"thread-send-fail") || !strcmp(name,"thread-free-fail")){threaded=1;thread_error=!strcmp(name,"thread-free-fail");}
    if(!strcmp(name,"recursive"))recursive=1;
    if(!strcmp(name,"recursive-free"))recursive_free=1;
    if(!strcmp(name,"fork-held"))fork_held=1;
    if(!strcmp(name,"request-mutated"))mutate_request=1;
    if(!strcmp(name,"active-mask"))active_mask=1;
    if(!strcmp(name,"unknown-mask"))unknown_mask=1;
    if(!strcmp(name,"stale-resource"))release_resource=1;
    if(!strcmp(name,"opaque-mutated"))change_opaque=1;
    if(!strcmp(name,"cleanup-fail")){fail_alloc=2;alloc_kind=1;cleanup_error=1;}
    unsigned int n=0,k=0;if(sscanf(name,"alloc-%u-%u",&n,&k)==2){fail_alloc=n;alloc_kind=k;}
    if(sscanf(name,"source-%u",&n)==1)bad_source=n;
    if(sscanf(name,"wire-%u-%u",&n,&k)==2){wire_alloc=n;wire_offset=k;}
    if(sscanf(name,"event-%u",&n)==1)event_fault=n;
    if(sscanf(name,"dmm-request-%u",&n)==1)bad_dmm_request=n;
    if(sscanf(name,"dmm-reply-%u",&n)==1)bad_dmm_reply=n;
    if(sscanf(name,"notice-%u",&n)==1)bad_notice=n;
    assert(osd_dispatch(&r));struct full_pinmem_osd_connection_snapshot s=osnap();assert(!held && !s.busy && !s.guard_held);
    if(threaded){assert(s.releasing_reply && s.live_reply && s.faults);pthread_mutex_lock(&ot_mutex);thread_go=1;pthread_cond_signal(&ot_cond);pthread_mutex_unlock(&ot_mutex);assert(!pthread_join(osd_thread,0));s=osnap();assert(!s.clean_completion && !s.ap_consumed);if(!thread_error)assert(!s.live_reply && s.reply_freed);}
    if(busy || guard_mutation){assert(r==-1021 && !s.started && !s.faults && !oa);finish();return 0;}
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || inline_free || foreign_free || recursive || recursive_free || fork_held || request_error || !strcmp(name,"reply-free-fail") || !strcmp(name,"wrong-owner") || !strcmp(name,"repeat");
    if(send_error)success=0;
    if(success){
        assert(!r && s.connections==1 && s.queued && s.event6_consumed && s.canonical_references && oa==115 && osends==1);
        assert(request_error?(!s.clean_completion && s.faults && s.retained_request==oq->data && !oq->freed):(s.clean_completion && !s.faults && oq->freed && s.request_freed));verify_resources();
        if(!inline_free){int freed=77;
            if(!strcmp(name,"wrong-owner"))assert(full_pinmem_osd_connection_release(caller^1u,ofinal->data,release_message,log_message,&freed) && freed==-1021 && !ofinal->attempts);
            if(!strcmp(name,"reply-free-fail")){reply_error=1;assert(full_pinmem_osd_connection_release(caller,ofinal->data,release_message,log_message,&freed) && freed==-59);reply_error=0;}
            if(foreign_free){assert(!pthread_create(&osd_thread,0,release_other_thread,0) && !pthread_join(osd_thread,0));}
            else assert(full_pinmem_osd_connection_release(caller,ofinal->data,release_message,log_message,&freed) && !freed);
        }
        s=osnap();assert(s.ap_consumed==!foreign_free && s.reply_freed && s.native_reply_frees==1 && s.waiter_frees==!foreign_free && !s.live_reply);
        if(recursive_free || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        if(!strcmp(name,"repeat")){oq=new_request();assert(osd_dispatch(&r) && r==-1021 && oa==115 && !oq->freed);}
    }else{
        assert(r==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !oq->freed);
        if(event_fault)assert(s.pending_event6 && s.retained_cleanup==s.event6_answer && s.retained_messages>=1);
        if(inline_free || threaded)assert(ofinal->attempts==1);
        unsigned int a=oa;assert(osd_dispatch(&r) && r==-1021 && oa==a);
    }
    struct full_pinmem_osd_connection_snapshot before=osnap();assert(!full_pinmem_osd_connection_owner_init());s=osnap();assert(!memcmp(&before,&s,sizeof s));finish();return 0;
}
