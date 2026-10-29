/* SPDX-License-Identifier: MIT */
/* Host-only composed providers; this byte-array reservation is not guest evidence. */
#define FULL_BB_TEST_MAIN bb_prerequisite_main
#include "test-bb-set-mode-device.c"
#include "imaging-pin-connection.h"
#include "pin-buffer-owner.h"
#include "pin-registry-core.h"
#include "../infrabb-registry.h"

#define CONNECT_SOURCE NATIVE_INFRAIMAGING_CP
#define CONNECT_PEER NATIVE_INFRABB_CP
struct connect_message {
    unsigned int bytes,source,owner,attempts,released,allocation;
    unsigned char *data;
};
static struct connect_message cm[48];
static unsigned int cm_count,connect_caller=0x8cde7654u,connect_allocs,connect_sends;
static unsigned int connect_logs,connect_callbacks,connect_reserves,connect_releases;
static unsigned int connect_order,connect_written,connect_consumed,connect_retired,connect_sent;
static unsigned int connect_final_free,connect_notify_free,connect_bad_alloc,connect_corrupt_alloc;
static int connect_alloc_kind,connect_cleanup_error,connect_source_error,connect_send_error;
static int connect_request_error,connect_reply_error,connect_inline,connect_corrupt_notify;
static int connect_corrupt_backing,connect_busy,connect_nested,connect_fork_callback;
static int connect_send_thread,connect_thread_error,connect_thread_started,connect_thread_go;
static pthread_t connect_reply_thread;
static pthread_mutex_t connect_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t connect_thread_condition=PTHREAD_COND_INITIALIZER;
static unsigned int connect_source_at=1,connect_source_phase,connect_source_calls[9];
static unsigned int connect_bad_reply,connect_reply_field;
static struct connect_message *connect_request,*connect_final,*get_queued;
static unsigned int get_destination,get_frees;
static unsigned char connect_memory[PIN_CONTROL_CAPACITY];
static struct pin_control_snapshot connect_pool_before;
static struct full_vef_snapshot connect_source_before,connect_peer_before;
static struct full_bb_set_mode_snapshot connect_bb_before;
static unsigned int connect_old_handle;
static const unsigned int connect_s[4]={0,2,1,CONNECT_SOURCE},connect_p[4]={0,1,1,CONNECT_PEER};

static unsigned int ct16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int ct32(const unsigned char *p){return ct16(p)|ct16(p+2)<<16;}
static unsigned long long ct64(const unsigned char *p){return ct32(p)|(unsigned long long)ct32(p+4)<<32;}
static void ctput16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void ctput32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned long long cthash(const unsigned char *p,unsigned int n){
    unsigned long long h=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)h=(h^p[i])*0x100000001b3ULL;return h;
}
static struct full_imaging_pin_connection_snapshot connect_snapshot(void){
    struct full_imaging_pin_connection_snapshot s;full_imaging_pin_connection_snapshot(&s);return s;
}
static void connect_callback(void){
    assert(getpid()==host_pid);connect_callbacks++;
    struct full_imaging_pin_connection_snapshot c=connect_snapshot();
    struct full_bb_set_mode_snapshot b;full_bb_set_mode_snapshot(&b);
    if(c.initialized)assert(c.owner_pid==getpid());
    if(connect_bb_before.clean_completion)assert(b.clean_completion && b.ap_consumed==1 && !b.faults);
    if(held)guarded();
}
static struct connect_message *cm_meta(void *p){
    assert(p);for(unsigned int i=cm_count;i>0;i--)if(cm[i-1].data==p && !cm[i-1].released)return &cm[i-1];
    assert(!"unknown or already released message");return 0;
}
static struct connect_message *cm_new(unsigned int n,unsigned int owner,unsigned int source_id){
    assert(cm_count<sizeof cm/sizeof *cm);struct connect_message *m=&cm[cm_count++];
    *m=(struct connect_message){.bytes=n,.owner=owner,.source=source_id,.data=malloc(n)};
    assert(m->data);memset(m->data,0xa5,n);return m;
}
static void cm_dispose(struct connect_message *m){assert(!m->released);m->released=1;free(m->data);}
static unsigned int cm_size(void *p){return cm_meta(p)->bytes;}
static unsigned int cm_source(void *p){return cm_meta(p)->source;}
static void cm_set(void *p,unsigned int sid){cm_meta(p)->source=sid;}
static int cm_free(unsigned int owner,void *p){
    struct connect_message *m=cm_meta(p);assert(m->owner==owner);m->attempts++;cm_dispose(m);return 0;
}
static void ctframe(unsigned char *p,unsigned int n,unsigned int op,unsigned int flags){
    memset(p,0,n);ctput32(p+4,0xa0a0a0a0u);ctput16(p+8,1);ctput16(p+10,n);
    ctput32(p+12,24);ctput32(p+16,n);ctput16(p+24,0x1000);ctput16(p+26,op);
    ctput16(p+28,n-24);ctput16(p+30,flags);
}
static struct connect_message *connect_new_request(unsigned int bytes){
    struct connect_message *m=cm_new(bytes,CONNECT_SOURCE,connect_caller);
    if(bytes>=64){ctframe(m->data,64,1,2);ctput32(m->data,connect_caller);
        for(unsigned int i=0;i<4;i++){ctput32(m->data+32+4*i,connect_s[i]);ctput32(m->data+48+4*i,connect_p[i]);}}
    return m;
}
/* Registry Get holds its own mutex around callbacks, so its transport deliberately
 * stays separate from connection callbacks that snapshot both registries. */
static int get_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    assert(owner==get_destination && n==56 && count==1);*out=cm_new(n,owner,ALLOCATOR_SOURCE)->data;return 0;
}
static int get_send(unsigned int owner,void *p){
    assert(owner==get_destination && !get_queued);get_queued=cm_meta(p);return 0;
}
static int get_free(unsigned int owner,void *p){get_frees++;return cm_free(owner,p);}
static void get_record(const char *tag,const char *text){fprintf(stdout,"%s%s\n",tag,text);}
static const struct full_imaging_io connect_get_io={get_allocate,get_free,cm_set,get_send,cm_size,cm_source,get_record};
static void connect_get(unsigned int sid,int leave_reply){
    get_destination=sid==CONNECT_SOURCE?0x8ab12345u:0x8dc98765u;
    struct connect_message *m=cm_new(48,sid,get_destination);ctframe(m->data,48,0,2);
    ctput32(m->data,get_destination);ctput32(m->data+20,0x6d7f);
    ctput32(m->data+36,sid==CONNECT_SOURCE?2:1);ctput32(m->data+40,1);
    int rc=77;int handled=sid==CONNECT_SOURCE?
        native_infraimaging_dispatch(sid,m->data,&connect_get_io,1,&rc):
        native_infrabb_dispatch(sid,m->data,&connect_get_io,1,&rc);
    assert(handled && !rc && m->released && get_queued && get_queued!=m);
    assert(get_queued->source==sid && get_queued->owner==get_destination && get_queued->bytes==56);
    assert(ct32(get_queued->data)==sid && ct16(get_queued->data+26)==0x8000);
    assert(ct32(get_queued->data+44)==1 && ct32(get_queued->data+48)==sid && !ct32(get_queued->data+52));
    if(!leave_reply){
        int freed=77;assert((sid==CONNECT_SOURCE?
            native_infraimaging_release_reply(get_destination,get_queued->data,get_free,get_record,&freed):
            native_infrabb_release_reply(get_destination,get_queued->data,get_free,get_record,&freed)) && !freed);
        assert(get_queued->released);get_queued=0;
    }
}
static void connect_old_pool(void){
    assert(!pin_control_bind_reserved(connect_memory,sizeof connect_memory,PIN_CONTROL_PHYSICAL));
    struct pin_control_lease old={0},opened={0};unsigned long long digest=0;unsigned char readback[32];
    assert(!pin_control_allocate(PIN_CONTROL_UNIT,&old));connect_old_handle=old.handle;
    assert(!pin_control_write_ssyn(old.handle,&digest));assert(digest==cthash(connect_memory,32));
    assert(!pin_control_share(old.handle,PIN_CONTROL_UNIT));assert(!pin_control_release(old.handle));
    assert(!pin_control_open_consumer(old.handle,PIN_CONTROL_UNIT,&opened));
    assert(opened.handle==old.handle && opened.physical==PIN_CONTROL_PHYSICAL && opened.cp_virtual==PIN_CONTROL_CP_VIRTUAL);
    assert(!pin_control_read_consumer(old.handle,0,readback,sizeof readback));assert(!memcmp(readback,connect_memory,sizeof readback));
    assert(!pin_control_release_consumer(old.handle));pin_control_snapshot(&connect_pool_before);
    assert(connect_pool_before.bound && !connect_pool_before.live && !connect_pool_before.faults);
    assert(connect_pool_before.allocations==1 && connect_pool_before.releases==1 && connect_pool_before.header_writes==1);
    assert(connect_pool_before.shares==1 && connect_pool_before.consumer_opens==1 && connect_pool_before.consumer_closes==1);
    assert(connect_pool_before.creator_releases==1 && connect_pool_before.consumer_releases==1 && connect_pool_before.consumer_reads==1);
}
static unsigned int connect_size(void *p){connect_callback();return cm_size(p);}
static unsigned int connect_source(void *p){connect_callback();return cm_source(p);}
static int connect_free(unsigned int owner,void *p){
    connect_callback();struct connect_message *m=cm_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==connect_request && connect_request_error)return -53;
    if(m==connect_final && connect_reply_error)return -59;
    if(m->allocation && m!=connect_final && connect_cleanup_error)return -47;
    if(m==connect_final)connect_final_free=++connect_order;
    if(m->allocation==5)connect_notify_free=++connect_order;
    cm_dispose(m);return 0;
}
static void connect_set(void *p,unsigned int sid){
    connect_callback();struct connect_message *m=cm_meta(p);assert(m->allocation<=8);
    unsigned int phase=++connect_source_calls[m->allocation];
    int bad=connect_source_error && m->allocation==connect_source_at && (!connect_source_phase || phase==connect_source_phase);
    m->source=bad?0x1234u:sid;
    if(connect_corrupt_notify && m->allocation==5 && sid==CONNECT_PEER)m->data[68]^=1;
    if(connect_corrupt_alloc && m->allocation==connect_corrupt_alloc)m->data[26]^=1;
}
static int connect_reserve(void){
    connect_callback();connect_reserves++;
    if(connect_busy){assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);return -EBUSY;}
    return reserve();
}
static void connect_release_guard(void){
    connect_callback();assert(held && connect_snapshot().guard_held);connect_releases++;release_guard();
}
static const struct full_adf_proc_guard connect_guard={connect_reserve,connect_release_guard};
static int connect_allocate(unsigned int owner,void **out,unsigned int n,unsigned int count){
    connect_callback();assert(owner==connect_caller && count==1 && held);connect_allocs++;
    static const unsigned int sizes[8]={64,72,216,216,80,216,216,56};
    assert(connect_allocs<=8 && n==sizes[connect_allocs-1]);
    if(connect_allocs==connect_bad_alloc){
        if(connect_alloc_kind==1){*out=0;return -41;}
        if(connect_alloc_kind==2){*out=0;return 0;}
        if(connect_alloc_kind==3){*out=connect_request->data;return 0;}
        if(connect_alloc_kind==6){assert(connect_allocs>1);*out=cm[cm_count-1].data;return 0;}
    }
    struct connect_message *m=cm_new(n,owner,ALLOCATOR_SOURCE);m->allocation=connect_allocs;*out=m->data;
    if(connect_allocs==connect_bad_alloc){
        if(connect_alloc_kind==4)m->bytes=n-1;
        if(connect_alloc_kind==5)return -43;
    }
    return 0;
}
static int connect_thread_free(unsigned int owner,void *p){
    assert(!pthread_mutex_lock(&connect_thread_mutex));
    struct connect_message *m=cm_meta(p);assert(m==connect_final && owner==m->owner);m->attempts++;
    connect_thread_started=1;assert(!pthread_cond_signal(&connect_thread_condition));
    while(!connect_thread_go)assert(!pthread_cond_wait(&connect_thread_condition,&connect_thread_mutex));
    if(!connect_thread_error)cm_dispose(m);
    assert(!pthread_mutex_unlock(&connect_thread_mutex));return connect_thread_error?-59:0;
}
static void *connect_thread_release(void *unused){
    (void)unused;int rc=77;
    assert(full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_thread_free,0,&rc));
    assert(rc==(connect_thread_error?-59:0));return 0;
}
static int connect_send(unsigned int owner,void *p){
    connect_callback();struct connect_message *m=cm_meta(p);assert(owner==connect_caller && m->owner==owner);
    assert(m->allocation==8 && m->bytes==56 && p!=connect_request->data && m->source==CONNECT_SOURCE);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);
    for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,connect_s[i]);
    assert(!memcmp(p,expected,sizeof expected));
    struct full_imaging_pin_connection_snapshot s=connect_snapshot();struct pin_control_snapshot pool;
    pin_control_snapshot(&pool);assert(s.buffer_freed && s.format_consumed && connect_consumed && connect_retired);
    assert(!pool.live && pool.allocations==pool.releases && !pool.faults);
    assert(s.dmm_allocations==1 && s.dmm_creator_closes==1 && s.dmm_opens==1 && s.dmm_frees==1);
    assert(s.format.consumed==1 && !s.ap_consumed && !s.reply_freed && !s.request_freed);
    assert(connect_notify_free && connect_notify_free>connect_retired);
    connect_final=m;connect_sends++;connect_sent=++connect_order;
    if(connect_send_thread){
        assert(!pthread_mutex_lock(&connect_thread_mutex));assert(!pthread_create(&connect_reply_thread,0,connect_thread_release,0));
        while(!connect_thread_started)assert(!pthread_cond_wait(&connect_thread_condition,&connect_thread_mutex));
        assert(!pthread_mutex_unlock(&connect_thread_mutex));
    }
    if(connect_inline){int rc=77;assert(full_imaging_pin_connection_release(owner,p,connect_free,get_record,&rc) && !rc);}
    return connect_send_error;
}
static void connect_check_pins(unsigned int a,unsigned int b,unsigned int pending){
    struct full_vef_snapshot x,y;native_infraimaging_snapshot(&x);native_infrabb_snapshot(&y);
    assert(x.pins[1].state==a && y.pins[1].state==b && x.pending==pending && !y.pending);
    assert(x.registry_objects==6 && x.owner_sid==CONNECT_SOURCE && y.registry_objects==21 && y.owner_sid==CONNECT_PEER);
    for(unsigned int i=0;i<6;i++)if(i!=1)assert(!memcmp(&x.pins[i],&connect_source_before.pins[i],sizeof x.pins[i]));
    for(unsigned int i=0;i<21;i++)if(i!=1)assert(!memcmp(&y.pins[i],&connect_peer_before.pins[i],sizeof y.pins[i]));
    if(a!=1)assert(!memcmp(x.pins[1].peer,connect_p,sizeof connect_p));
    if(b!=1)assert(!memcmp(y.pins[1].peer,connect_s,sizeof connect_s));
}
static void connect_record(const char *tag,const char *text){
    connect_callback();connect_logs++;connect_order++;fprintf(stdout,"%s%s\n",tag,text);
    struct full_imaging_pin_connection_snapshot s=connect_snapshot();
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_PEER_REQUEST "))connect_check_pins(2,1,1);
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_PEER_REPLY "))connect_check_pins(2,0,1);
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_REFERENCE_READBACK ")){
        struct pin_control_references r;assert(!pin_control_references(s.buffer_handle,&r));
        assert(field(text,"owners=")==1 && r.owners==1);
        if(strstr(text,"phase=allocated "))assert(r.opens==1 && r.creator && !r.consumer);
        else if(strstr(text,"phase=creator-closed "))assert(!r.opens && r.creator && !r.consumer);
        else if(strstr(text,"phase=transferred "))assert(!r.opens && !r.creator && r.consumer);
        else {assert(strstr(text,"phase=consumer-open "));assert(r.opens==1 && !r.creator && r.consumer && r.consumer_open);}
    }
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_FORMAT_WRITTEN ")){
        connect_check_pins(0,0,1);connect_written=connect_order;
        unsigned char expected[80];assert(!full_infraimaging_format_build(expected,sizeof expected));
        assert(s.buffer_handle!=connect_old_handle && s.buffer_handle==(connect_old_handle|0x400u));
        assert(s.buffer_physical==PIN_CONTROL_PHYSICAL && s.buffer_cp_virtual==PIN_CONTROL_CP_VIRTUAL);
        assert(!memcmp(connect_memory,expected,sizeof expected) && s.buffer_fnv==cthash(expected,sizeof expected));
        assert(!s.format.consumed && s.format.cache[0]==1 && !s.format.cache[1]);
        assert(!s.format.cache[2] && !s.format.cache[3] && !s.format.cache[4]);
        if(connect_corrupt_backing)connect_memory[0]^=1;
    }
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_DMM_REQUEST ")){
        unsigned int n=connect_allocs;assert(n==3 || n==4 || n==6 || n==7);
        struct connect_message *m=&cm[cm_count-1];assert(m->allocation==n && m->bytes==216);
        unsigned int cmd=n==3?0x20:n==4?0x25:n==6?0x24:0x23;
        assert(ct16(m->data)==cmd && ct16(m->data+20)==0x55);
        if(cmd==0x20)assert(ct32(m->data+4)==0x404 && ct32(m->data+12)==0xffffffffu && ct16(m->data+22)==1);
        else assert(ct32(m->data+8)==s.buffer_handle);
        if(cmd==0x23)assert(ct16(m->data+22)==2);
    }
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_DMM_REPLY ")){
        struct connect_message *m=&cm[cm_count-1];unsigned int cmd=ct16(m->data);
        assert(ct16(m->data+6)==0x55 && !ct16(m->data+2) && ct32(m->data+12)==s.buffer_handle);
        if(cmd==0x8020 || cmd==0x8024){
            assert(ct16(m->data+8)==1 && ct64(m->data+24)==s.buffer_physical && ct32(m->data+32)==PIN_CONTROL_SLOT_BYTES);
            assert(ct64(m->data+24)>=PIN_CONTROL_PHYSICAL && ct64(m->data+24)+ct32(m->data+32)<=PIN_CONTROL_PHYSICAL+sizeof connect_memory);
        }
        if(connect_bad_reply==m->allocation){
            assert(connect_reply_field<216);m->data[connect_reply_field]^=1;
        }
    }
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_FORMAT_NOTIFY ")){
        struct connect_message *m=&cm[cm_count-1];assert(m->allocation==5);
        assert((s.buffer_handle^(connect_corrupt_notify?1u:0u))==ct32(m->data+68));
        assert(ct16(m->data+26)==0x104 && ct32(m->data+64)==0x404);
        for(unsigned int i=0;i<4;i++){assert(ct32(m->data+32+4*i)==connect_p[i]);assert(ct32(m->data+48+4*i)==connect_s[i]);}
    }
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_FORMAT_CONSUMED ")){
        static const unsigned int cache[5]={0,1,1920,1080,0};
        assert(connect_written && s.format.consumed==1 && !memcmp(s.format.cache,cache,sizeof cache));
        assert(s.synchronization_acquires==1 && s.synchronization_releases==1 && !s.buffer_freed);
        assert(s.format.payload_fnv64==cthash(connect_memory+64,16));connect_consumed=connect_order;
    }
    if(!strcmp(tag,"FULL_IMAGING_PIN_CONNECT_BUFFER_RETIRED ")){
        struct pin_control_snapshot pool;struct pin_control_references r;pin_control_snapshot(&pool);
        assert(connect_consumed && !pool.live && pool.allocations==2 && pool.releases==2);
        assert(pin_control_references(s.buffer_handle,&r));connect_retired=connect_order;
    }
    if(connect_nested && !strcmp(tag,"FULL_IMAGING_PIN_CONNECT_REQUEST ")){
        int rc=77;extern const struct full_imaging_io connect_io;
        assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && rc==-1021);
        assert(connect_snapshot().requests==1);
    }
    if(connect_fork_callback && !strcmp(tag,"FULL_IMAGING_PIN_CONNECT_REQUEST ")){
        pid_t pid=fork();assert(pid>=0);if(!pid){
            alarm(2);int rc=77;extern const struct full_imaging_io connect_io;
            assert(!connect_snapshot().initialized);
            assert(full_imaging_pin_connection_owner_init()==-1021);
            struct full_imaging_io child_io=connect_io;child_io.size=cm_size;child_io.source=cm_source;
            assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&child_io,&connect_guard,1,&rc) && rc==-1021);_exit(0);
        }
        int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
    }
}
const struct full_imaging_io connect_io={connect_allocate,connect_free,connect_set,connect_send,connect_size,connect_source,connect_record};
static void connect_preserved(void){
    struct full_bb_set_mode_snapshot b;full_bb_set_mode_snapshot(&b);
    assert(!memcmp(&b,&connect_bb_before,sizeof b));out_preserved_failure();out_check_shadow();
    struct pin_control_snapshot p;pin_control_snapshot(&p);
    assert(p.header_writes==connect_pool_before.header_writes && p.shares==connect_pool_before.shares);
    assert(p.creator_releases==connect_pool_before.creator_releases && !p.faults);
    assert(!memcmp(connect_memory+PIN_CONTROL_SLOT_BYTES,(unsigned char[PIN_CONTROL_CAPACITY-PIN_CONTROL_SLOT_BYTES]){0},PIN_CONTROL_CAPACITY-PIN_CONTROL_SLOT_BYTES));
}
static void connect_finish(void){
    for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);
    printf("IMAGING_PIN_CONNECTION_HOST_TEST_PASS: callbacks=%u logs=%u allocations=%u sends=%u; byte-array fixture, no guest, frames or capture evidence\n",connect_callbacks,connect_logs,connect_allocs,connect_sends);
}
#ifndef FULL_IMAGING_PIN_CONNECTION_TEST_MAIN
#define FULL_IMAGING_PIN_CONNECTION_TEST_MAIN main
#endif
int FULL_IMAGING_PIN_CONNECTION_TEST_MAIN(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(15);const char *name=argv[1];assert(!setvbuf(stdout,0,_IONBF,0));
    int no_prior=!strcmp(name,"no-prior"),no_get=!strcmp(name,"no-get"),no_pool=!strcmp(name,"no-pool");
    if(strcmp(name,"uninitialized"))assert(!full_imaging_pin_connection_owner_init());
    connect_request=connect_new_request(!strcmp(name,"short")?63:64);
    if(!strcmp(name,"uninitialized")){
        int rc=77;assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && rc==-1021);
        assert(!connect_allocs && !connect_sends);connect_finish();return 0;
    }
    int rc=77;
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"short")){
        unsigned int dest=!strcmp(name,"unrelated")?CONNECT_PEER:CONNECT_SOURCE;
        assert(!full_imaging_pin_connection_dispatch(dest,connect_request->data,&connect_io,&connect_guard,strcmp(name,"disabled")!=0,&rc) && rc==77);
        assert(!connect_snapshot().requests && !connect_allocs && !connect_request->released);connect_finish();return 0;
    }
    if(!strcmp(name,"missing-transport")){
        for(unsigned int i=0;i<6;i++){
            struct full_imaging_io broken=connect_io;
            if(i==0)broken.allocate=0;else if(i==1)broken.release=0;else if(i==2)broken.set_source=0;
            else if(i==3)broken.send=0;else if(i==4)broken.size=0;else broken.source=0;
            rc=77;assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&broken,&connect_guard,1,&rc) && rc==-1021);
        }
        assert(!connect_snapshot().requests && !connect_allocs && !connect_sends);connect_finish();return 0;
    }
    if(!strcmp(name,"missing-guard")){
        struct full_adf_proc_guard bad_reserve={0,connect_release_guard},bad_release={connect_reserve,0};
        const struct full_adf_proc_guard *guards[3]={0,&bad_reserve,&bad_release};
        for(unsigned int i=0;i<3;i++){rc=77;assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,guards[i],1,&rc) && rc==-1021);}
        assert(!connect_snapshot().requests && !connect_allocs && !connect_sends);connect_finish();return 0;
    }
    if(!strcmp(name,"bad-wire")){
        static const unsigned int positions[]={0,4,8,10,12,16,24,26,28,30,32,36,40,44,48,52,56,60};
        for(unsigned int i=0;i<sizeof positions/sizeof *positions;i++){
            unsigned int at=positions[i];connect_request->data[at]^=1;rc=77;
            assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && rc==-1021);
            connect_request->data[at]^=1;
        }
        for(unsigned int word=32;word<64;word+=4){
            connect_request->data[word+1]^=1;
            assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && rc==-1021);
            connect_request->data[word+1]^=1;
        }
        ctput16(connect_request->data+26,0x100);ctput16(connect_request->data+30,1);
        assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && rc==-1021);
        assert(!connect_snapshot().requests && !connect_allocs && !connect_sends && !connect_request->released);connect_finish();return 0;
    }
    if(!strcmp(name,"invalid-source")){
        connect_request->source=0x81234567u;
        assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc) && rc==-1021);
        assert(!connect_snapshot().requests && !connect_allocs && !connect_sends);connect_finish();return 0;
    }
    if(!strcmp(name,"fork")){
        pid_t pid=fork();assert(pid>=0);if(!pid){alarm(2);assert(!connect_snapshot().initialized);
            assert(full_imaging_pin_connection_owner_init()==-1021);
            struct full_imaging_io child_io=connect_io;child_io.size=cm_size;child_io.source=cm_source;
            assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&child_io,&connect_guard,1,&rc) && rc==-1021);_exit(0);}
        int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));connect_finish();return 0;
    }
    if(!no_prior){char *old[]={"test","normal",argv[2],0};assert(!bb_prerequisite_main(3,old));alarm(15);
        full_bb_set_mode_snapshot(&connect_bb_before);assert(connect_bb_before.clean_completion && connect_bb_before.ap_consumed==1);}
    if(!no_get){connect_get(CONNECT_SOURCE,!strcmp(name,"live-source-get"));
        if(strcmp(name,"live-source-get"))connect_get(CONNECT_PEER,!strcmp(name,"live-peer-get"));}
    native_infraimaging_snapshot(&connect_source_before);native_infrabb_snapshot(&connect_peer_before);
    if(!no_pool){
        if(!strcmp(name,"virgin-pool")){assert(!pin_control_bind_reserved(connect_memory,sizeof connect_memory,PIN_CONTROL_PHYSICAL));pin_control_snapshot(&connect_pool_before);}
        else connect_old_pool();
    }
    if(!strcmp(name,"dynamic-caller")){connect_caller=0x8fedab01u;connect_request->source=connect_caller;ctput32(connect_request->data,connect_caller);}
    if(!strcmp(name,"resource-busy")){connect_busy=1;assert(!pthread_mutex_lock(&resource_mutex));}
    if(!strcmp(name,"source-error"))connect_source_error=1;
    if(!strcmp(name,"corrupt-notify"))connect_corrupt_notify=1;
    if(!strcmp(name,"corrupt-backing"))connect_corrupt_backing=1;
    if(!strcmp(name,"peer-wire"))connect_corrupt_alloc=1;
    if(!strcmp(name,"peer-reply-wire"))connect_corrupt_alloc=2;
    if(!strcmp(name,"send-fail"))connect_send_error=-61;
    if(!strcmp(name,"request-free-fail"))connect_request_error=1;
    if(!strcmp(name,"inline-free"))connect_inline=1;
    if(!strcmp(name,"inline-send-fail")){connect_inline=1;connect_send_error=-61;}
    if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){
        connect_send_thread=1;connect_send_error=-61;connect_thread_error=!strcmp(name,"in-flight-free-fail");
    }
    if(!strcmp(name,"recursive"))connect_nested=1;
    if(!strcmp(name,"fork-held"))connect_fork_callback=1;
    unsigned int nth=0;int kind=0;
    if(sscanf(name,"alloc-%u-%d",&nth,&kind)==2){assert(nth>=1 && nth<=8 && kind>=1 && kind<=5);connect_bad_alloc=nth;connect_alloc_kind=kind;}
    unsigned int phase=0;
    if(sscanf(name,"source-%u-%u",&nth,&phase)==2){assert(nth>=1 && nth<=8 && phase>=1 && phase<=2);connect_source_error=1;connect_source_at=nth;connect_source_phase=phase;}
    unsigned int offset=0;
    if(sscanf(name,"dmm-reply-%u-%u",&nth,&offset)==2){assert(nth==3 || nth==6);assert(offset<216);connect_bad_reply=nth;connect_reply_field=offset;}
    if(!strcmp(name,"alloc-cleanup-fail")){connect_bad_alloc=3;connect_alloc_kind=5;connect_cleanup_error=1;}
    if(!strcmp(name,"internal-free-fail"))connect_cleanup_error=1;
    if(!strcmp(name,"alloc-live-alias")){connect_bad_alloc=2;connect_alloc_kind=6;}
    assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&rc));
    if(connect_busy)assert(!pthread_mutex_unlock(&resource_mutex));
    struct full_imaging_pin_connection_snapshot s=connect_snapshot();
    assert(!s.busy && !s.guard_held && !held && s.requests==1 && s.owner_pid==getpid());
    assert(connect_reserves==connect_releases+(unsigned int)connect_busy || (!connect_reserves && !connect_releases));
    if(connect_send_thread){
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued && !s.request_freed && !s.retained_request);
        assert(connect_sends==1 && connect_allocs==8 && s.live_reply==connect_final->data && s.releasing_reply==1);
        assert(s.retained_messages==1 && !s.ap_consumed && !s.reply_freed && !connect_final->released && connect_final->attempts==1);
        assert(!connect_request->released && !connect_request->attempts && !connect_final_free);
        assert(!pthread_mutex_trylock(&resource_mutex));assert(!pthread_mutex_unlock(&resource_mutex));
        assert(!pthread_mutex_lock(&connect_thread_mutex));connect_thread_go=1;assert(!pthread_cond_signal(&connect_thread_condition));
        assert(!pthread_mutex_unlock(&connect_thread_mutex));assert(!pthread_join(connect_reply_thread,0));s=connect_snapshot();
        assert(!s.releasing_reply && s.faults && !s.clean_completion && !s.connections && !s.queued);
        assert(connect_final->attempts==1 && !connect_request->released && !connect_request->attempts);
    }
    int success=!strcmp(name,"normal") || !strcmp(name,"dynamic-caller") || !strcmp(name,"inline-free") ||
        !strcmp(name,"recursive") || !strcmp(name,"fork-held") || !strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail") || !strcmp(name,"repeat");
    if(success || connect_request_error){
        assert(!rc && connect_sends==1 && connect_allocs==8 && s.queued && s.connections==1);
        assert(s.peer_requests==1 && s.peer_replies==1 && s.format_consumed && s.buffer_freed && s.buffer_transferred);
        assert(s.peer_connected_marker_known==1 && s.peer_connected_marker==1 && s.peer_marker_writes==1);
        assert(s.buffer_opened && s.dmm_allocations==1 && s.dmm_creator_closes==1 && s.dmm_opens==1 && s.dmm_frees==1);
        assert(s.synchronization_acquires==1 && s.synchronization_releases==1 && s.format.consumed==1);
        assert(connect_written<connect_consumed && connect_consumed<connect_retired && connect_retired<connect_sent);
        assert(!s.retained_messages && connect_final && s.reply_destination==connect_caller);
        connect_check_pins(0,0,0);
        if(connect_request_error)assert(s.faults && !s.clean_completion && !s.request_freed && s.retained_request==connect_request->data);
        else assert(!s.faults && s.clean_completion && s.request_freed && connect_request->released);
        if(!connect_inline){
            assert(!s.ap_consumed && s.live_reply==connect_final->data && !connect_final->released);
            if(!strcmp(name,"wrong-owner")){
                int freed=77;unsigned int attempts=connect_final->attempts;
                assert(full_imaging_pin_connection_release(connect_caller^1u,connect_final->data,connect_free,connect_record,&freed) && freed==-1021);
                assert(connect_final->attempts==attempts && !connect_final->released && connect_snapshot().faults && !connect_snapshot().clean_completion);
            }
            if(!strcmp(name,"reply-free-fail")){
                connect_reply_error=1;int freed=77;
                assert(full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_free,connect_record,&freed) && freed==-59);
                assert(!connect_final->released && connect_snapshot().live_reply==connect_final->data && !connect_snapshot().ap_consumed && !connect_snapshot().clean_completion);
                connect_reply_error=0;
            }
            int freed=77;assert(full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_free,connect_record,&freed) && !freed);
        }
        s=connect_snapshot();assert(s.ap_consumed==1 && s.reply_freed && !s.live_reply && !s.retained_messages && connect_final->released);
        if(!strcmp(name,"wrong-owner") || !strcmp(name,"reply-free-fail"))assert(s.faults && !s.clean_completion);
        int freed=77;assert(!full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_free,connect_record,&freed) && freed==77);
        struct pin_control_snapshot pool;pin_control_snapshot(&pool);
        assert(pool.allocations==2 && pool.releases==2 && pool.consumer_opens==2 && pool.consumer_closes==2);
        assert(pool.consumer_releases==2 && pool.consumer_reads==2 && pool.payload_writes==1);
        assert(pool.creator_closes==1 && pool.creator_transfers==1 && !pool.live);
        if(!strcmp(name,"repeat")){
            struct connect_message *again=connect_new_request(64);unsigned int before=connect_allocs;
            int repeat=77;assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,again->data,&connect_io,&connect_guard,1,&repeat) && repeat==-1021);
            assert(!again->released && connect_allocs==before && connect_snapshot().requests==1);connect_check_pins(0,0,0);
        }
    }else{
        assert(rc==-1021 && s.faults && !s.clean_completion && !s.connections && !s.queued);
        assert(!connect_request->released && !s.request_freed);
        if(connect_inline || (connect_send_thread && !connect_thread_error))assert(s.ap_consumed==1 && s.reply_freed && !s.live_reply && connect_final->released);
        else assert(!s.ap_consumed);
        if(no_prior || no_get || no_pool || connect_busy || get_queued || !strcmp(name,"virgin-pool"))assert(!connect_allocs && !connect_sends);
        if(connect_bad_reply){
            struct pin_control_snapshot pool;pin_control_snapshot(&pool);
            assert(s.buffer_handle && pool.live==1 && pool.allocations==2 && pool.releases==1);
            assert(!s.format_consumed && !s.buffer_freed && !connect_sends);connect_check_pins(0,0,1);
        }
        if(connect_corrupt_backing){
            struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(s.buffer_opened && !s.format_consumed && !s.buffer_freed && pool.live==1);
            assert(pool.allocations==2 && pool.releases==1);connect_check_pins(0,0,1);
        }
        if(connect_cleanup_error)assert(s.retained_messages && !connect_sends);
        if(connect_bad_alloc>=3 || connect_corrupt_notify || connect_send_error)connect_check_pins(0,0,1);
        unsigned int before_allocs=connect_allocs,before_sends=connect_sends;
        int retry=77;assert(full_imaging_pin_connection_dispatch(CONNECT_SOURCE,connect_request->data,&connect_io,&connect_guard,1,&retry) && retry==-1021);
        struct full_imaging_pin_connection_snapshot after=connect_snapshot();
        assert(after.requests==1 && after.faults==s.faults && after.buffer_handle==s.buffer_handle);
        assert(after.retained_messages==s.retained_messages && connect_allocs==before_allocs && connect_sends==before_sends);
        if(connect_send_thread){
            assert(!memcmp(&after,&s,sizeof s) && !s.retained_request && !connect_request->attempts);
            assert(!cm_free(CONNECT_SOURCE,connect_request->data) && connect_request->released && connect_request->attempts==1);
            struct full_imaging_pin_connection_snapshot caller_freed=connect_snapshot();assert(!memcmp(&caller_freed,&s,sizeof s));
            if(connect_thread_error){
                assert(!connect_final->released && s.live_reply==connect_final->data && s.retained_messages==1 && !s.ap_consumed && !s.reply_freed);
                int freed=77;assert(full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_free,connect_record,&freed) && !freed);
            }
            struct full_imaging_pin_connection_snapshot recovered=connect_snapshot();
            assert(recovered.ap_consumed==1 && recovered.reply_freed==1 && recovered.faults && !recovered.clean_completion);
            assert(!recovered.live_reply && !recovered.retained_messages && !recovered.retained_request && !recovered.request_freed);
            assert(!recovered.connections && !recovered.queued && !recovered.busy && !recovered.guard_held);
            assert(connect_final->released && connect_final->attempts==(connect_thread_error?2u:1u));
            int freed=77;assert(!full_imaging_pin_connection_release(connect_caller,connect_final->data,connect_free,connect_record,&freed) && freed==77);
            printf("IMAGING_PIN_CONNECTION_IN_FLIGHT_PASS: first_free_rc=%d attempts=%u ap_consumed=1 clean_completion=0 caller_request_freed=1\n",connect_thread_error?-59:0,connect_final->attempts);
        }
    }
    if(!no_prior && !no_pool)connect_preserved();
    assert(connect_callbacks && (connect_logs || no_prior || no_get));connect_finish();return 0;
}
