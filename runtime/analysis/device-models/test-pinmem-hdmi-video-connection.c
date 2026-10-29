/* SPDX-License-Identifier: MIT */
/* Actual ten production edges plus the asynchronous video endpoint; host only. */
#define FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN hv_tenth_main
#include "test-pinmem-drawinfo-connection.c"
#undef FULL_PINMEM_DRAWINFO_CONNECTION_TEST_MAIN
#include "pinmem-hdmi-video-connection.h"
#include "hdmi-video-state.h"
#include "hdmi-pin-device.h"
#include "adf-hdmi-audio-connection.h"

static const unsigned int hv_s[4]={4,2,0,FULL_PINMEM_CP},hv_p[4]={4,1,0,FULL_HDMI_PIN_CP};
struct hv_message {void *data;unsigned int bytes,owner,source,live,attempts,allocation;};
static struct hv_message hv_messages[128],*hv_request,*hv_final,*hv_seed_reply,*hv_notifications[32];
static unsigned int hv_count,hv_allocations,hv_sends,hv_notifications_count,hv_callbacks,hv_guard_calls,hv_guard_releases,hv_guard_refusals;
static unsigned int hv_caller=0x81cf62a1u,hv_condition_sid=0x802a0116u,hv_bad_alloc,hv_bad_source,hv_bad_size,hv_alias;
static int hv_ready,hv_busy,hv_recursive,hv_fork_held,hv_send_error,hv_inline_ap,hv_inline_notifications;
static int hv_request_error,hv_reply_error,hv_cleanup_error,hv_threaded_send,hv_thread_free_error;
static int hv_thread_waiting,hv_thread_continue,hv_exit_window;
static int hv_drain(void);
static pthread_t hv_thread;
static pthread_mutex_t hv_race_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t hv_race_condition=PTHREAD_COND_INITIALIZER;
static struct pd_history hv_history;
static struct full_vef_snapshot hv_hdmi_pins;
static struct full_hdmi_snapshot hv_shared;
static struct full_adf_hdmi_audio_connection_snapshot hv_audio;
static unsigned char hv_memory[PIN_CONTROL_CAPACITY],*hv_seed;
static const struct full_imaging_io hv_io;
static const struct full_adf_proc_guard hv_guard;
static struct full_pinmem_hdmi_video_connection_snapshot hv_snapshot(void){
    struct full_pinmem_hdmi_video_connection_snapshot s;full_pinmem_hdmi_video_connection_snapshot(&s);return s;
}
static struct full_hdmi_video_state_snapshot hv_state(void){
    struct full_hdmi_video_state_snapshot s;full_hdmi_video_state_snapshot(&s);return s;
}
static struct hv_message *hv_meta(void *p){
    for(unsigned int i=hv_count;i>0;i--)if(hv_messages[i-1].data==p && hv_messages[i-1].live)return &hv_messages[i-1];
    assert(!"unknown or already freed message");return NULL;
}
static struct hv_message *hv_new(unsigned int owner,unsigned int bytes,unsigned int source){
    assert(hv_count<128);struct hv_message *m=&hv_messages[hv_count++];
    *m=(struct hv_message){.owner=owner,.bytes=bytes,.source=source,.live=1,.data=malloc(bytes)};
    assert(m->data);memset(m->data,0xa5,bytes);return m;
}
static void hv_preserved(void){
    if(!hv_ready)return;
    struct pd_history after;pd_capture(&after);
    after.previous.pinmem.pins[7]=hv_history.previous.pinmem.pins[7];after.previous.pinmem.pending=hv_history.previous.pinmem.pending;
    assert(!memcmp(&after,&hv_history,sizeof after));
    struct full_vef_snapshot pins;full_hdmi_pin_snapshot(&pins);pins.pins[0]=hv_hdmi_pins.pins[0];
    assert(!memcmp(&pins,&hv_hdmi_pins,sizeof pins));
    struct full_hdmi_snapshot shared;full_hdmi_snapshot(&shared);assert(!memcmp(&shared,&hv_shared,sizeof shared));
    struct full_adf_hdmi_audio_connection_snapshot audio;full_adf_hdmi_audio_connection_snapshot(&audio);assert(!memcmp(&audio,&hv_audio,sizeof audio));
    assert(!memcmp(connect_memory,hv_memory,sizeof hv_memory));out_preserved_failure();out_check_shadow();
    if(pnc_speech_ready){assert(!memcmp(&pnc_speech,&pnc_speech_state_before,sizeof pnc_speech));assert(!memcmp(pnc_speech_memory,pnc_speech_before,sizeof pnc_speech_memory));}
}
static void hv_callback(void){
    assert(host_pid==getpid());hv_callbacks++;(void)hv_snapshot();hv_preserved();
    if(held && pthread_equal(guard_thread,pthread_self()))guarded();
}
static unsigned int hv_size(void *p){hv_callback();return hv_meta(p)->bytes;}
static unsigned int hv_source(void *p){hv_callback();return hv_meta(p)->source;}
static int hv_free(unsigned int owner,void *p){
    hv_callback();struct hv_message *m=hv_meta(p);assert(owner==m->owner);m->attempts++;
    if(m==hv_request && hv_request_error)return -53;
    if(m==hv_final && hv_reply_error)return -59;
    if(m->allocation && m!=hv_final && hv_cleanup_error)return -47;
    m->live=0;free(m->data);return 0;
}
static void hv_set(void *p,unsigned int source){
    hv_callback();struct hv_message *m=hv_meta(p);m->source=m->allocation && m->allocation==hv_bad_source?source^1u:source;
}
static int hv_allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count){
    hv_callback();assert(count==1 || (count==0 && bytes==20));
    unsigned int allocation=0;
    if(bytes==64 || bytes==72 || bytes==56){
        assert(held && owner==hv_caller);allocation=++hv_allocations;
        const unsigned int sizes[3]={64,72,56};assert(allocation<=3 && bytes==sizes[allocation-1]);
        if(allocation==hv_bad_alloc){*out=NULL;return -41;}
        if(allocation==hv_alias){*out=hv_request->data;return 0;}
    }
    struct hv_message *m=hv_new(owner,bytes,ALLOCATOR_SOURCE);m->allocation=allocation;
    if(allocation && allocation==hv_bad_size)m->bytes--;
    *out=m->data;return 0;
}
static void hv_record(const char *tag,const char *text){
    hv_callback();fprintf(stdout,"%s%s\n",tag,text);
    if(!strcmp(tag,"FULL_PINMEM_HDMI_VIDEO_CONNECT_REQUEST ")){
        if(hv_recursive){int rc=77;assert(full_pinmem_hdmi_video_connection_dispatch(FULL_PINMEM_CP,hv_request->data,&hv_io,&hv_guard,1,&rc) && rc==-1021);}
        if(hv_fork_held){pid_t child=fork();assert(child>=0);if(!child){alarm(2);int rc=77;unsigned int callbacks=hv_callbacks;
                assert(!hv_snapshot().connection.initialized && full_pinmem_hdmi_video_connection_owner_init()==-1021);
                assert(full_pinmem_hdmi_video_connection_dispatch(FULL_PINMEM_CP,hv_request->data,&hv_io,&hv_guard,1,&rc) && rc==-1021);
                assert(full_pinmem_hdmi_video_connection_progress()==-1021);
                assert(!full_pinmem_hdmi_video_connection_release(hv_caller,hv_request->data,hv_free,hv_record,&rc));
                assert(hv_callbacks==callbacks);_exit(0);}
            int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));}
    }
    if(hv_recursive && !strcmp(tag,"FULL_HDMI_VIDEO_STATE_MESSAGE_SENT "))assert(full_pinmem_hdmi_video_connection_progress()==1);
}
static int hv_release_endpoint(unsigned int owner,void *p,int (*release)(unsigned int,void *)){
    int rc=77;assert(full_pinmem_hdmi_video_connection_release(owner,p,release,hv_record,&rc));return rc;
}
static int hv_blocked_free(unsigned int owner,void *p){
    pthread_mutex_lock(&hv_race_mutex);hv_thread_waiting=1;pthread_cond_broadcast(&hv_race_condition);
    while(!hv_thread_continue)assert(!pthread_cond_wait(&hv_race_condition,&hv_race_mutex));
    pthread_mutex_unlock(&hv_race_mutex);return hv_thread_free_error?-59:hv_free(owner,p);
}
static void *hv_foreign_free(void *unused){
    (void)unused;assert(syscall(SYS_gettid)!=hv_snapshot().sender_tid);
    assert(hv_release_endpoint(hv_caller,hv_final->data,hv_threaded_send?hv_blocked_free:hv_free)==(hv_thread_free_error?-59:0));return NULL;
}
static int hv_consume(struct hv_message *m){
    assert(m->live && (m->bytes==20 || m->owner==FULL_HDMI_VIDEO_UPM));
    assert(full_hdmi_video_state_observe_receive(m->owner,m->data,m->source,m->bytes)==1);
    if(m->owner==FULL_HDMI_VIDEO_UPM && ct32((unsigned char *)m->data+4)==2)ctput32((unsigned char *)m->data+4,hv_state().upm_effective_second_id);
    int rc=77;assert(full_hdmi_video_state_release(m->owner,m->data,hv_free,hv_record,&rc) && !rc);
    return full_pinmem_hdmi_video_connection_progress();
}
static int hv_send(unsigned int owner,void *p){
    hv_callback();struct hv_message *m=hv_meta(p);assert(m->owner==owner);
    if(m->bytes==16 || m->bytes==20){
        assert(hv_notifications_count<32);hv_notifications[hv_notifications_count++]=m;
        if(m->bytes==20){unsigned char expected[20]={0};ctput32(expected,2);ctput32(expected+4,ct32((unsigned char *)p+4));ctput32(expected+8,1);
            assert(owner==hv_condition_sid && m->source==FULL_HDMI_VIDEO_CONDITION_SOURCE && !memcmp(expected,p,20));}
        else assert(owner==FULL_HDMI_VIDEO_UPM && m->source==FULL_HDMI_CP && ct32(p)==0x00920117u);
        if(hv_inline_notifications)assert(hv_consume(m)==1);
        return 0;
    }
    hv_final=m;assert(m->allocation==3 && m->bytes==56 && owner==hv_caller && m->source==FULL_PINMEM_CP);
    unsigned char expected[56];ctframe(expected,56,0x8001,2);for(unsigned int i=0;i<4;i++)ctput32(expected+32+4*i,hv_s[i]);assert(!memcmp(expected,p,56));
    struct full_pinmem_hdmi_video_connection_snapshot s=hv_snapshot();assert(s.peer_ready && !s.peer_waiting && s.connection.event6_consumed && s.connection.manager_calls==1 && s.connection.post_callback_type==4);
    assert(!s.connection.yc_callback_seen && !s.connection.yc_format_published && s.connection.live_reply==p && full_hdmi_video_state_connect_ready());hv_sends++;
    if(hv_inline_ap)assert(!hv_release_endpoint(owner,p,hv_free));
    if(hv_threaded_send){pthread_mutex_lock(&hv_race_mutex);assert(!pthread_create(&hv_thread,NULL,hv_foreign_free,NULL));
        while(!hv_thread_waiting)assert(!pthread_cond_wait(&hv_race_condition,&hv_race_mutex));
        pthread_mutex_unlock(&hv_race_mutex);}
    return hv_send_error;
}
static int hv_reserve(void){
    hv_callback();hv_guard_calls++;if(hv_busy){hv_guard_refusals++;return -EBUSY;}
    struct full_pinmem_hdmi_video_connection_snapshot s=hv_snapshot();
    if(s.request_owned){struct full_vef_snapshot a,b;full_pinmem_snapshot(&a);full_hdmi_pin_snapshot(&b);
        assert(s.connection.busy && s.connection.pending_event6 && a.pending && a.pins[7].state==2 && !b.pins[0].state);}
    return reserve();
}
static void hv_release_guard(void){
    hv_callback();assert(hv_snapshot().connection.guard_held && held);hv_guard_releases++;release_guard();
    if(hv_exit_window){
        hv_exit_window=0;assert(hv_notifications_count==26);
        assert(hv_drain()==1 && full_hdmi_video_state_connect_ready());
    }
}
static const struct full_imaging_io hv_io={hv_allocate,hv_free,hv_set,hv_send,hv_size,hv_source,hv_record};
static const struct full_adf_proc_guard hv_guard={hv_reserve,hv_release_guard};

/* Plain transport for legacy handlers which call IO under their own mutex. */
static unsigned int hv_seed_size(void *p){return hv_meta(p)->bytes;}
static unsigned int hv_seed_source(void *p){return hv_meta(p)->source;}
static void hv_seed_set(void *p,unsigned int source){hv_meta(p)->source=source;}
static int hv_seed_free(unsigned int owner,void *p){struct hv_message *m=hv_meta(p);assert(m->owner==owner);m->live=0;free(p);return 0;}
static int hv_seed_allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count){assert(count==1);*out=hv_new(owner,bytes,ALLOCATOR_SOURCE)->data;return 0;}
static int hv_seed_send(unsigned int owner,void *p){assert(hv_meta(p)->owner==owner && !hv_seed_reply);hv_seed_reply=hv_meta(p);return 0;}
static const struct full_imaging_io hv_seed_io={hv_seed_allocate,hv_seed_free,hv_seed_set,hv_seed_send,hv_seed_size,hv_seed_source,NULL};
static void hv_transact(unsigned int command,unsigned int payload){
    unsigned int caller=0x81cf1200u+hv_count,bytes=command==0x0101?16:12;
    struct hv_message *m=hv_new(FULL_HDMI_CP,bytes,caller);unsigned char *p=m->data;memset(p,0,bytes);
    ctput16(p,0x2500);ctput16(p+2,command);ctput16(p+4,bytes);ctput16(p+6,1);ctput32(p+8,payload);
    if(command==0x0101){const unsigned char resolution[6]={0,0,0,0,6,5};memcpy(p+8,resolution,6);}
    int rc=77;assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&hv_seed_io,1,&rc) && !rc && !m->live && hv_seed_reply);
    p=hv_seed_reply->data;assert(hv_seed_reply->owner==caller && hv_seed_reply->source==FULL_HDMI_CP);
    if(!full_hdmi_video_state_release(caller,p,hv_seed_free,NULL,&rc))assert(full_hdmi_release_reply(caller,p,hv_seed_free,NULL,&rc));
    assert(!rc && !hv_seed_reply->live);hv_seed_reply=NULL;
}
static void hv_prefix(int incomplete){
    hv_transact(0x010a,0);hv_transact(0x0101,0);
    const unsigned int rates[5]={0,0,17,17,0};for(unsigned int i=0;i<5;i++)hv_transact(0x0117,i|(rates[i]<<8));hv_transact(0x0117,0x100);
    hv_transact(0x0102,1);hv_transact(0x0109,0);if(!incomplete)hv_transact(0x0127,hv_condition_sid);
}
static void hv_get(unsigned int sid,const unsigned int *key,int leave){
    unsigned int caller=0x8a003456u;struct hv_message *m=hv_new(sid,48,caller);ctframe(m->data,48,0,2);ctput32(m->data,caller);
    for(unsigned int i=0;i<3;i++)ctput32((unsigned char *)m->data+32+4*i,key[i]);
    if(sid==FULL_PINMEM_CP)assert(!full_pinmem_hdmi_video_connection_observe_input(sid,m->data,48));
    int rc=77,handled;
    if(sid==FULL_PINMEM_CP)handled=full_pinmem_dispatch(sid,m->data,&hv_seed_io,1,&rc);
    else if(sid==FULL_ADF_CP)handled=full_adf_dispatch(sid,m->data,&hv_seed_io,1,&rc);
    else handled=full_hdmi_pin_dispatch(sid,m->data,&hv_seed_io,1,&rc);
    assert(handled && !rc && !m->live && hv_seed_reply);
    if(!leave){
        if(sid==FULL_PINMEM_CP)handled=full_pinmem_release_reply(caller,hv_seed_reply->data,hv_seed_free,NULL,&rc);
        else if(sid==FULL_ADF_CP)handled=full_adf_release_reply(caller,hv_seed_reply->data,hv_seed_free,NULL,&rc);
        else handled=full_hdmi_pin_release_reply(caller,hv_seed_reply->data,hv_seed_free,NULL,&rc);
        assert(handled && !rc);
    }
    hv_seed_reply=NULL;
}
static void hv_connect_audio(void){
    const unsigned int source[4]={5,2,0,FULL_ADF_CP},peer[4]={5,1,0,FULL_HDMI_PIN_CP};
    assert(!full_adf_hdmi_audio_connection_owner_init());hv_get(FULL_ADF_CP,source,0);hv_get(FULL_HDMI_PIN_CP,peer,0);
    struct hv_message *m=hv_new(FULL_ADF_CP,64,hv_caller);ctframe(m->data,64,1,2);ctput32(m->data,hv_caller);
    for(unsigned int i=0;i<4;i++){ctput32((unsigned char *)m->data+32+4*i,source[i]);ctput32((unsigned char *)m->data+48+4*i,peer[i]);}
    const struct full_adf_proc_guard guard={reserve,release_guard};int rc=77;
    assert(full_adf_hdmi_audio_connection_dispatch(FULL_ADF_CP,m->data,&hv_seed_io,&guard,1,&rc) && !rc && !m->live && hv_seed_reply);
    assert(full_adf_hdmi_audio_connection_release(hv_caller,hv_seed_reply->data,hv_seed_free,NULL,&rc) && !rc);hv_seed_reply=NULL;
    full_adf_hdmi_audio_connection_snapshot(&hv_audio);assert(hv_audio.ap_consumed && hv_audio.clean_completion && hv_audio.marker_value==1 && hv_audio.marker_writes==1);
}
static void *hv_foreign_get_free(void *p){
    int rc=77;assert(full_pinmem_release_reply(0x8a003456u,p,hv_seed_free,NULL,&rc) && !rc);return NULL;
}
static void hv_tenth_pending(const char *seed){
    assert(!full_pinmem_drawinfo_connection_owner_init());pd_seed(seed,"normal");
    pd_get(FULL_PINMEM_CP,pd_s,0);pd_get(NATIVE_DRAWINFO_CP,pd_p,0);vi_clear_messages();
    pd_capture(&pd_before);memcpy(pd_memory_before,connect_memory,sizeof pd_memory_before);pd_ready=1;
    pd_request=pd_new_request();int rc=77;assert(pd_dispatch(&rc) && !rc);
    assert(pd_snapshot().clean_completion && !pd_snapshot().ap_consumed && pd_snapshot().live_reply);
}
static void hv_load_seed(const char *path){
    FILE *f=fopen(path,"rb");assert(f);hv_seed=malloc(FULL_ADF_PUBLIC_SEED_BYTES);assert(hv_seed);
    assert(fread(hv_seed,1,FULL_ADF_PUBLIC_SEED_BYTES,f)==FULL_ADF_PUBLIC_SEED_BYTES && fgetc(f)==EOF && !fclose(f));
    assert(cthash(hv_seed,FULL_ADF_PUBLIC_SEED_BYTES)==FULL_ADF_PUBLIC_SEED_FNV);
}
static int hv_backup(unsigned int key,void *out,unsigned int capacity,unsigned int *length){
    const unsigned char *r=hv_seed+0xed000;assert(hv_seed && !memcmp(r+12,"BK4",4));
    unsigned int sections=ct32(r+16),properties=ct32(r+20),header=ct32(r+24),size=header+ct32(r+28);
    assert(size<=FULL_ADF_PUBLIC_SEED_BYTES-0xed000 && 0x100+sections*6+properties*6<=header);
    unsigned int section=key>>16,index=key&0xffff;if(section>=sections)return 1;
    const unsigned char *s=r+0x100+section*6;unsigned int count=ct16(s),first=ct32(s+2);assert(first+count<=properties);
    if(index>=count)return 1;
    unsigned int pointer=ct32(r+0x100+sections*6+(first+index)*6+2);if(pointer==0xffffffffu)return 1;
    unsigned int at=pointer&0xffffff,n=pointer>>24,maximum=n;assert(at>=header && at<size);
    if(!n || n==255){unsigned int prefix=n?2:4;assert(at+prefix<=size);maximum=n?ct16(r+at):ct16(r+at+2);n=ct16(r+at);at+=prefix;}
    assert(n<=maximum && at+maximum<=size);*length=n;memcpy(out,r+at,n<capacity?n:capacity);return 0;
}
static struct hv_message *hv_new_request(void){
    struct hv_message *m=hv_new(FULL_PINMEM_CP,64,hv_caller);ctframe(m->data,64,1,2);ctput32(m->data,hv_caller);ctput32((unsigned char *)m->data+20,0x7855c);
    for(unsigned int i=0;i<4;i++){ctput32((unsigned char *)m->data+32+4*i,hv_s[i]);ctput32((unsigned char *)m->data+48+4*i,hv_p[i]);}return m;
}
static int hv_dispatch(int *rc){return full_pinmem_hdmi_video_connection_dispatch(FULL_PINMEM_CP,hv_request->data,&hv_io,&hv_guard,1,rc);}
static int hv_drain(void){
    int rc=1;for(unsigned int i=0;i<hv_notifications_count;i++)if(hv_notifications[i]->live)rc=hv_consume(hv_notifications[i]);return rc;
}
static void *hv_other_progress(void *unused){(void)unused;assert(!hv_drain());return NULL;}
static void *hv_wrong_condition_free(void *p){
    struct hv_message *m=p;int rc=77;assert(full_hdmi_video_state_release(m->owner,m->data,hv_free,hv_record,&rc) && rc==-1021);return NULL;
}
static void hv_finish(void){
    hv_preserved();assert(!held && !hv_snapshot().connection.guard_held);
    full_hdmi_video_state_test_reset();
    for(unsigned int i=0;i<hv_count;i++)if(hv_messages[i].live){hv_messages[i].live=0;free(hv_messages[i].data);}
    for(unsigned int i=0;i<cm_count;i++)if(!cm[i].released)cm_dispose(&cm[i]);
    free(hv_seed);puts("PINMEM_HDMI_VIDEO_CONNECTION_HOST_TEST_PASS");
}
int main(int argc,char **argv){
    assert(argc==3);host_pid=getpid();alarm(30);assert(!setvbuf(stdout,NULL,_IONBF,0));const char *name=argv[1];int rc=77;
    int finish_window=!strncmp(name,"finish-window",13);
    if(!strcmp(name,"dynamic-caller"))hv_caller=0x8fed1023u;
    if(!strcmp(name,"dynamic-queue"))hv_condition_sid=0x8acd1006u;
    hv_request=hv_new_request();
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated")){
        assert(!full_pinmem_hdmi_video_connection_dispatch(!strcmp(name,"unrelated")?FULL_HDMI_CP:FULL_PINMEM_CP,hv_request->data,&hv_io,&hv_guard,strcmp(name,"disabled")!=0,&rc) && rc==77 && !hv_callbacks);hv_finish();return 0;
    }
    if(!strcmp(name,"uninitialized")){assert(hv_dispatch(&rc) && rc==-1021 && !hv_callbacks);hv_finish();return 0;}
    assert(!full_pinmem_hdmi_video_connection_owner_init());assert(!full_hdmi_video_state_owner_init());
    if(!strcmp(name,"fork")){pid_t child=fork();assert(child>=0);if(!child){alarm(2);assert(full_pinmem_hdmi_video_connection_owner_init()==-1021 && full_pinmem_hdmi_video_connection_progress()==-1021 && !hv_snapshot().connection.initialized);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));hv_finish();return 0;}
    if(!strcmp(name,"bad-wire") || !strcmp(name,"bad-source") || !strcmp(name,"bad-key") || !strcmp(name,"short")){
        if(!strcmp(name,"bad-wire"))((unsigned char *)hv_request->data)[4]^=1;
        if(!strcmp(name,"bad-source"))hv_request->source^=1;
        if(!strcmp(name,"bad-key"))((unsigned char *)hv_request->data)[46]^=1;
        if(!strcmp(name,"short"))hv_request->bytes--;
        int handled=hv_dispatch(&rc);assert((!strcmp(name,"bad-key") || !strcmp(name,"short"))?(!handled && rc==77):(handled && rc==-1021));
        assert(!hv_allocations && !hv_snapshot().connection.started && hv_request->live);hv_finish();return 0;
    }
    assert(hv_dispatch(&rc) && rc==-1021 && !hv_allocations && !hv_snapshot().request_owned && !hv_snapshot().connection.retained_request);
    if(!strcmp(name,"no-tenth")){hv_finish();return 0;}
    assert(!hv_seed_free(FULL_PINMEM_CP,hv_request->data));
    if(!strcmp(name,"tenth-not-AP-free"))hv_tenth_pending(argv[2]);
    else{char *args[]={"test","normal",argv[2],NULL};assert(!hv_tenth_main(3,args));vi_clear_messages();}
    alarm(30);pd_ready=0;hv_load_seed(argv[2]);hv_prefix(!strcmp(name,"missing-prefix"));
    if(!strcmp(name,"audio-already-connected"))hv_connect_audio();
    if(strcmp(name,"no-backup"))assert(!full_hdmi_video_state_bind_backup(hv_backup));
    if(strcmp(name,"no-source-get"))hv_get(FULL_PINMEM_CP,!strcmp(name,"wrong-key-get")?(const unsigned int[4]){0,2,3,FULL_PINMEM_CP}:hv_s,!strcmp(name,"live-source-get"));
    if(strcmp(name,"no-peer-get"))hv_get(FULL_HDMI_PIN_CP,hv_p,!strcmp(name,"live-peer-get"));
    if(!strcmp(name,"foreign-Get-free")){
        hv_get(FULL_PINMEM_CP,(const unsigned int[4]){0,2,3,FULL_PINMEM_CP},1);
        assert(!pthread_create(&hv_thread,NULL,hv_foreign_get_free,hv_messages[hv_count-1].data));assert(!pthread_join(hv_thread,NULL));
    }
    pd_capture(&hv_history);full_hdmi_pin_snapshot(&hv_hdmi_pins);full_hdmi_snapshot(&hv_shared);memcpy(hv_memory,connect_memory,sizeof hv_memory);hv_ready=1;
    hv_request=hv_new_request();assert(hv_snapshot().source_gate_known && !hv_snapshot().source_gate && hv_snapshot().source_history_known);
    if(!strcmp(name,"source-gate-unknown")){unsigned char input[12]={0x1f,0xf0,2};assert(full_pinmem_hdmi_video_connection_observe_input(FULL_PINMEM_CP,input,12)==-1021);assert(full_pinmem_hdmi_video_connection_owner_init()==-1021);}
    if(!strcmp(name,"source-status"))pin_registry_test_set_state(full_pinmem_registry(),7,2);
    if(!strcmp(name,"peer-status"))pin_registry_test_set_state(full_hdmi_pin_registry(),0,2);
    if(!strcmp(name,"source-status") || !strcmp(name,"peer-status")){assert(hv_dispatch(&rc) && rc==-1021 && !hv_snapshot().connection.started);hv_finish();return 0;}
    if(!strcmp(name,"resource-busy"))hv_busy=1;
    if(!strcmp(name,"recursive") || !strcmp(name,"finish-window-recursive"))hv_recursive=1;
    if(finish_window)hv_exit_window=1;
    if(!strcmp(name,"fork-held"))hv_fork_held=1;
    if(!strcmp(name,"inline-notifications"))hv_inline_notifications=1;
    if(!strcmp(name,"inline-AP-free") || !strcmp(name,"inline-send-fail"))hv_inline_ap=1;
    if(!strcmp(name,"send-fail") || !strcmp(name,"inline-send-fail") || !strncmp(name,"inflight-",9))hv_send_error=-61;
    if(!strncmp(name,"inflight-",9)){hv_threaded_send=1;hv_thread_free_error=!strcmp(name,"inflight-free-fail");}
    if(!strcmp(name,"request-free-fail"))hv_request_error=1;
    if(!strcmp(name,"cleanup-fail")){hv_bad_alloc=2;hv_cleanup_error=1;}
    unsigned int n=0;if(sscanf(name,"alloc-%u",&n)==1)hv_bad_alloc=n;
    if(sscanf(name,"source-%u",&n)==1)hv_bad_source=n;
    if(sscanf(name,"size-%u",&n)==1)hv_bad_size=n;
    if(sscanf(name,"alias-%u",&n)==1)hv_alias=n;
    assert(hv_dispatch(&rc));struct full_pinmem_hdmi_video_connection_snapshot s=hv_snapshot();
    assert(!held && !s.connection.guard_held && !s.progressing);
    int denied=!strcmp(name,"tenth-not-AP-free") || !strcmp(name,"no-source-get") || !strcmp(name,"no-peer-get") ||
        !strcmp(name,"wrong-key-get") || !strcmp(name,"live-source-get") || !strcmp(name,"live-peer-get") ||
        !strcmp(name,"foreign-Get-free") || !strcmp(name,"source-gate-unknown") || !strcmp(name,"resource-busy");
    assert(denied?!s.connection.started:s.connection.started);
    if(!s.connection.started){assert(rc==-1021 && !hv_allocations && !s.request_owned && !s.connection.retained_request && hv_request->live);hv_finish();return 0;}
    assert(!rc && s.request_owned==(hv_request->live!=0));
    if(s.connection.faults){assert(!s.connection.queued && !hv_sends && hv_request->live && s.connection.retained_request==hv_request->data && s.request_owned && !s.connection.busy);hv_finish();return 0;}
    if(!hv_inline_notifications && !finish_window){
        assert(s.connection.busy && s.peer_waiting && !s.peer_ready && !s.connection.queued && !s.connection.event6_consumed && s.connection.pending_event6 && s.connection.retained_messages==1 && s.request_owned);
        assert(s.connection.event6_answer && s.connection.event6_body==(unsigned char *)s.connection.event6_answer+24);
        unsigned char parameter[12]={0};ctput32(parameter,0x504d4000);assert(!memcmp(s.connection.event6_parameter,parameter,12));
        assert(s.connection.context_kind==2 && s.connection.phase==1 && s.connection.wait_primary==6 && !s.connection.wait_secondary && s.connection.keep_pending==1);
        assert(full_pinmem_hdmi_video_connection_progress()==1 && !hv_sends && hv_request->live && !held);
        if(!strcmp(name,"resource-busy-while-pending")){hv_busy=1;unsigned int attempts=hv_guard_calls;
            assert(full_pinmem_hdmi_video_connection_progress()==1 && hv_guard_calls==attempts+1 && !hv_sends && hv_snapshot().request_owned && !held);hv_busy=0;}
    }
    if(!strcmp(name,"missing-prefix") || !strcmp(name,"no-backup")){assert(!hv_notifications_count && hv_snapshot().connection.busy);hv_finish();return 0;}
    if(!strcmp(name,"no-condition-free") || !strcmp(name,"no-upm-receive")){
        for(unsigned int i=0;i<hv_notifications_count;i++){struct hv_message *m=hv_notifications[i];
            if(!strcmp(name,"no-condition-free"))assert(full_hdmi_video_state_observe_receive(m->owner,m->data,m->source,m->bytes)==1);
            else if(m->bytes==20)assert(hv_consume(m)==1);}
        assert(full_pinmem_hdmi_video_connection_progress()==1 && !hv_sends && !hv_snapshot().peer_ready);hv_finish();return 0;
    }
    if(!strcmp(name,"wrong-condition-source") || !strcmp(name,"wrong-condition-payload") || !strcmp(name,"wrong-condition-thread") || !strcmp(name,"direct-condition-free")){
        struct hv_message *m=hv_notifications[2];int out=77;
        if(!strcmp(name,"wrong-condition-source"))assert(full_hdmi_video_state_observe_receive(m->owner,m->data,m->source^1u,m->bytes)==-1021);
        if(!strcmp(name,"wrong-condition-payload")){((unsigned char *)m->data)[8]^=1;assert(full_hdmi_video_state_observe_receive(m->owner,m->data,m->source,m->bytes)==-1021);}
        if(!strcmp(name,"direct-condition-free"))assert(full_hdmi_video_state_release(m->owner,m->data,hv_free,hv_record,&out) && out==-1021 && !m->attempts);
        if(!strcmp(name,"wrong-condition-thread")){assert(full_hdmi_video_state_observe_receive(m->owner,m->data,m->source,m->bytes)==1);assert(!pthread_create(&hv_thread,NULL,hv_wrong_condition_free,m));assert(!pthread_join(hv_thread,NULL));}
        assert(full_pinmem_hdmi_video_connection_progress()==-1021 && hv_snapshot().connection.faults && !hv_sends && hv_snapshot().request_owned);hv_finish();return 0;
    }
    if(sscanf(name,"event-%u",&n)==1)full_pinmem_hdmi_video_connection_test_event_corrupt(n);
    if(!strcmp(name,"answer-tail"))((unsigned char *)hv_snapshot().connection.event6_answer)[68]^=1;
    if(!strcmp(name,"request-mutated"))((unsigned char *)hv_request->data)[20]^=1;
    if(!strcmp(name,"source-changed-while-pending")){unsigned char input[12]={0x1f,0xf0,2};assert(full_pinmem_hdmi_video_connection_observe_input(FULL_PINMEM_CP,input,12)==-1021);
        assert(full_pinmem_hdmi_video_connection_progress()==-1021 && !hv_sends && !held);hv_finish();return 0;}
    if(!strcmp(name,"registry-changed-while-pending")){
        pin_registry_test_set_state(full_pinmem_registry(),11,2);hv_history.previous.pinmem.pins[11].state=2;
        assert(full_pinmem_hdmi_video_connection_progress()==-1021 && hv_snapshot().connection.faults && hv_snapshot().request_owned && !hv_sends && !held);hv_finish();return 0;
    }
    int complete;
    if(!strcmp(name,"other-thread-progress")){assert(!pthread_create(&hv_thread,NULL,hv_other_progress,NULL));assert(!pthread_join(hv_thread,NULL));complete=0;}
    else complete=(hv_inline_notifications || finish_window)?0:hv_drain();
    if(hv_threaded_send){pthread_mutex_lock(&hv_race_mutex);hv_thread_continue=1;pthread_cond_broadcast(&hv_race_condition);pthread_mutex_unlock(&hv_race_mutex);assert(!pthread_join(hv_thread,NULL));}
    s=hv_snapshot();assert(!held && !s.progressing && !s.connection.guard_held);
    int expected_fault=hv_bad_alloc || hv_bad_source || hv_bad_size || hv_alias || hv_send_error || hv_request_error || hv_cleanup_error ||
        !strncmp(name,"event-",6) || !strcmp(name,"answer-tail") || !strcmp(name,"request-mutated");
    assert(expected_fault?(s.connection.faults!=0):!s.connection.faults);
    if(s.connection.faults){assert(complete==-1021 && !s.connection.clean_completion && !s.connection.busy);
        if(!s.connection.queued)assert(s.request_owned && s.connection.retained_request==hv_request->data && hv_request->live);
        assert(full_pinmem_hdmi_video_connection_progress()==-1021);hv_finish();return 0;}
    assert(!complete && s.connection.connections==1 && s.connection.queued==1 && s.connection.clean_completion && !s.request_owned && !s.connection.retained_request && !hv_request->live);
    assert(hv_allocations==3 && hv_sends==1 && s.connection.event6_consumed && s.peer_ready && s.connection.manager_calls==1);
    assert(s.source_gate_known && !s.source_gate && s.source_history_known && !s.connection.retained_messages && hv_guard_calls==hv_guard_releases+hv_guard_refusals);
    assert(!s.connection.original_CP_event_pointer_identity_verified && !s.connection.original_RTOS_scheduling_verified);
    if(!strcmp(name,"other-thread-progress"))assert(s.producer_tid!=s.sender_tid && s.sender_tid==syscall(SYS_gettid));
    if(!strcmp(name,"foreign-AP-free")){assert(!pthread_create(&hv_thread,NULL,hv_foreign_free,NULL));assert(!pthread_join(hv_thread,NULL));assert(!hv_snapshot().connection.ap_consumed && !hv_snapshot().connection.waiter_frees);}
    else if(!hv_inline_ap){
        if(!strcmp(name,"wrong-AP-owner"))assert(hv_release_endpoint(hv_caller^1u,hv_final->data,hv_free)==-1021 && !hv_final->attempts);
        if(!strcmp(name,"AP-free-fail")){hv_reply_error=1;assert(hv_release_endpoint(hv_caller,hv_final->data,hv_free)==-59);hv_reply_error=0;}
        assert(!hv_release_endpoint(hv_caller,hv_final->data,hv_free));
    }
    s=hv_snapshot();assert(s.connection.native_reply_frees==1 && s.connection.reply_freed && !s.connection.live_reply);
    if(strcmp(name,"foreign-AP-free"))assert(s.connection.ap_consumed && s.connection.waiter_frees==1);
    if(!strcmp(name,"repeat")){hv_request=hv_new_request();assert(hv_dispatch(&rc) && rc==-1021 && hv_allocations==3 && hv_request->live);}
    if(!s.connection.faults)assert(!full_pinmem_hdmi_video_connection_progress());
    puts("PRIOR_TEN_PORTS_BACKING_DMM_CACHES_SPEECH_AND_HDMI_AUDIO_PRESERVED actual_hdmi_notifications_consumed=26 frames=0 capture_verified=0");
    hv_finish();return 0;
}
