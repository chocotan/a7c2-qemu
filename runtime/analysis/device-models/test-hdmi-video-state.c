/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "hdmi-video-state.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

struct message {void *pointer;unsigned int owner,source,bytes,live,frees;};
static struct message messages[128];
static void *queued[128];
static unsigned int queue_count,allocations,frees,size_calls,source_calls,records;
static unsigned int default_caller=0x81c00011u,condition_queue=0x802a0116u;
static int inline_consume,send_error,allocation_error,source_error,size_error,request_free_error,free_error;
static int send_error_after_consume,alias_allocate,fork_held,short_allocate,reenter_connect,early_free,partial_allocate;
static void *alias;
static unsigned int missing_key,failed_key,config_bytes=10,upm_value=1;
static unsigned int kernel_mode,kernel_prepared,kernel_receipts,reuse_after_free;
static int threaded_failure,thread_started,thread_waiting,thread_continue,thread_free_failure;
static pthread_t receiver_thread;
static pthread_mutex_t race_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t race_condition=PTHREAD_COND_INITIALIZER;
static void *race_message;
static unsigned int race_destination;
static const struct full_imaging_io io;

static unsigned int get32(const unsigned char *p) {return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static void put32(unsigned char *p,unsigned int n) {for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(n>>(8*i));}
static struct full_hdmi_video_state_snapshot snapshot(void) {
    struct full_hdmi_video_state_snapshot out;full_hdmi_video_state_snapshot(&out);return out;
}
static struct message *message(void *pointer) {
    for(unsigned int i=0;i<128;i++)if(messages[i].pointer==pointer && messages[i].live)return &messages[i];
    assert(0);return NULL;
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int wait) {
    assert(bytes<=64 && (wait==0 || wait==1));allocations++;
    if(alias_allocate) {*out=alias;return 0;}
    if(allocation_error) {*out=NULL;return -71;}
    for(unsigned int i=0;i<128;i++)if(!messages[i].live) {
        unsigned int actual=bytes-(short_allocate?1u:0u);
        void *p=malloc(actual);assert(p);memset(p,0xa5,actual);
        messages[i]=(struct message){.pointer=p,.owner=owner,.bytes=actual,.live=1};*out=p;return partial_allocate?-71:0;
    }
    assert(0);return -1;
}
static unsigned int size(void *pointer) {size_calls++;struct message *m=message(pointer);return m->bytes-(size_error?1u:0u);}
static unsigned int source(void *pointer) {source_calls++;return message(pointer)->source;}
static void set_source(void *pointer,unsigned int value) {message(pointer)->source=value^(source_error?1u:0u);}
static int real_free(unsigned int owner,void *pointer) {
    struct message *m=message(pointer);assert(m->owner==owner && !m->frees);
    if(request_free_error && owner==FULL_HDMI_CP)return -73;
    if(free_error)return -74;
    if(threaded_failure && pointer==race_message) {
        pthread_mutex_lock(&race_mutex);thread_waiting=1;pthread_cond_broadcast(&race_condition);
        while(!thread_continue)assert(!pthread_cond_wait(&race_condition,&race_mutex));
        pthread_mutex_unlock(&race_mutex);
        if(thread_free_failure)return -75;
    }
    m->frees++;m->live=0;frees++;free(pointer);return 0;
}
static void record(const char *tag,const char *text) {
    assert(tag && text);records++;
    struct full_hdmi_video_state_snapshot current=snapshot();
    assert(!current.original_cp_executed && !current.hardware_verified && !current.capture_verified);
    if(early_free && strstr(tag,"FULL_HDMI_VIDEO_STATE_MESSAGE_PUBLISHED")) {
        void *pointer=NULL;assert(sscanf(strstr(text,"pointer="),"pointer=%p",&pointer)==1);
        int rc=99;assert(full_hdmi_video_state_release(message(pointer)->owner,pointer,real_free,NULL,&rc) && rc==-1021);
    }
    if(strstr(tag,"FULL_HDMI_VIDEO_STATE_DRIVER_CONSUMED")) {
        assert(strstr(text,"job=6 slot=4 row=0 column=8 policy=0"));
        assert(strstr(text,"completion=070000000000000000000000"));
    }
}
static int release_message(unsigned int owner,void *pointer) {
    int rc=99;
    if(full_hdmi_video_state_release(owner,pointer,real_free,record,&rc))return rc;
    if(full_hdmi_release_reply(owner,pointer,real_free,record,&rc))return rc;
    return real_free(owner,pointer);
}
static void consume(void *pointer) {
    struct message *m=message(pointer);unsigned int owner=m->owner;
    if(m->bytes==20 || owner==FULL_HDMI_VIDEO_UPM) {
        assert(full_hdmi_video_state_observe_receive(owner,pointer,m->source,m->bytes)==1);
        if(owner==FULL_HDMI_VIDEO_UPM && get32((unsigned char *)pointer+4)==2)
            put32((unsigned char *)pointer+4,snapshot().upm_effective_second_id);
    }
    assert(!release_message(owner,pointer));
}
static void *concurrent_receive(void *unused) {
    (void)unused;struct message *m=message(race_message);int rc=99;
    assert(full_hdmi_video_state_observe_receive(m->owner,race_message,m->source,m->bytes)==1);
    assert(full_hdmi_video_state_release(m->owner,race_message,real_free,record,&rc));
    assert(rc==(thread_free_failure?-75:0));return NULL;
}
static int send(unsigned int owner,void *pointer) {
    struct message *m=message(pointer);assert(m->owner==owner);
    if(reenter_connect)assert(full_hdmi_video_state_connect_begin(&io)==1);
    if(fork_held) {
        fork_held=0;pid_t child=fork();assert(child>=0);
        if(!child) {
            alarm(2);assert(full_hdmi_video_state_owner_init()==-1021);
            assert(!snapshot().initialized);assert(full_hdmi_video_state_connect_begin(&io)==-1021);
            int rc=99;unsigned int sizes=size_calls,sources=source_calls;
            assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,pointer,&io,1,&rc) && rc==-1021);
            assert(size_calls==sizes && source_calls==sources);_exit(0);
        }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
    if(threaded_failure && m->bytes==20 && !thread_started) {
        thread_started=1;race_message=pointer;race_destination=owner;
        assert(!pthread_create(&receiver_thread,NULL,concurrent_receive,NULL));
        pthread_mutex_lock(&race_mutex);
        while(!thread_waiting)assert(!pthread_cond_wait(&race_condition,&race_mutex));
        pthread_mutex_unlock(&race_mutex);return -76;
    }
    if(kernel_mode && owner==FULL_HDMI_VIDEO_UPM) {
        assert(!real_free(owner,pointer));return 0;
    }
    if(inline_consume) {
        consume(pointer);
        if(reuse_after_free){
            int result=99;unsigned int count=frees;
            assert(!full_hdmi_video_state_observe_receive(0x81cf1234,pointer,0x12345678,20));
            assert(!full_hdmi_video_state_release(0x81cf1234,pointer,real_free,record,&result));
            assert(result==99 && frees==count && !snapshot().faults);
        }
        if(send_error_after_consume)return -77;
    } else if(send_error)return -78;
    else {assert(queue_count<128);queued[queue_count++]=pointer;}
    return 0;
}
static const struct full_imaging_io io={allocate,real_free,set_source,send,size,source,record};
static void *request(unsigned int command,unsigned int payload,unsigned int caller) {
    unsigned int bytes=command==0x0101?16:command==0x0201 || command==0x020a?8:12;
    unsigned char *p=NULL;assert(!allocate(FULL_HDMI_CP,(void **)&p,bytes,1));
    memset(p,0,bytes);p[0]=0;p[1]=0x25;p[2]=(unsigned char)command;p[3]=(unsigned char)(command>>8);
    p[4]=(unsigned char)bytes;p[6]=1;message(p)->source=caller;
    if(bytes>=12)put32(p+8,payload);
    return p;
}
static void transact(unsigned int command,unsigned int payload,unsigned int caller) {
    void *p=request(command,payload,caller);unsigned int before=queue_count;int rc=99;
    assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
    assert(queue_count==before+1);void *reply=queued[--queue_count];
    assert(reply!=p && message(reply)->owner==caller && message(reply)->source==FULL_HDMI_CP);
    const unsigned char *bytes=reply;
    assert(bytes[0]==0 && bytes[1]==0x25 && bytes[2]==(command&255) && bytes[3]==((command>>8)|0x80));
    assert(!release_message(caller,reply));
}
static int backup(unsigned int key,void *out,unsigned int capacity,unsigned int *length) {
    if(key==missing_key)return 1;
    if(key==failed_key)return -79;
    unsigned char bytes[32]={0};unsigned int n;
    switch(key) {
    case 0x010d008d:bytes[0]=2;n=1;break;
    case 0x003e0005:memcpy(bytes,"ILCE-7CM2",9);n=16;break;
    case 0x009a0001:n=config_bytes;for(unsigned int i=0;i<n && i<32;i++)bytes[i]=(unsigned char)(i+1);break;
    case 0x009a0009:bytes[0]=0;n=1;break;
    case 0x009a000a:bytes[0]=1;n=1;break;
    case 0x009a000b:bytes[0]=0;n=1;break;
    case 0x009a000c:put32(bytes,300000);n=4;break;
    case 0x010704fd:bytes[0]=1;n=1;break;
    case 0x00920085:bytes[4]=(unsigned char)upm_value;n=8;break;
    default:return -80;
    }
    *length=n;memcpy(out,bytes,n<capacity?n:capacity);return 0;
}
static int kernel_receipt(unsigned int stage,unsigned long long lease,void *pointer,
    const unsigned char raw[16],const unsigned char effective[16],void (*log)(const char *,const char *)) {
    assert(lease && pointer && log==record && get32(raw)==0x00920117 && get32(raw+8)==0x009a0000);
    assert(get32(effective+4)==(get32(raw+4)?snapshot().upm_effective_second_id:0));
    if(!stage) {assert(message(pointer)->live);kernel_prepared++;return kernel_mode==2?-1021:0;}
    assert(stage==1 && kernel_prepared>kernel_receipts);kernel_receipts++;
    for(unsigned int i=0;i<128;i++)if(messages[i].pointer==pointer)assert(!messages[i].live);
    /* Another native allocation may reuse U before this receipt is ingested. */
    int result=99;unsigned int before=frees;
    assert(!full_hdmi_video_state_observe_receive(0x81cf1234,pointer,0x12345678,16));
    assert(!full_hdmi_video_state_release(0x81cf1234,pointer,real_free,record,&result));
    assert(result==99 && frees==before && !snapshot().faults);
    return kernel_mode==3?-1021:0;
}
static void seed(void) {
    transact(0x010a,0,default_caller++);
    void *p=request(0x0101,0,default_caller++);const unsigned char resolution[6]={0,0,0,0,6,5};
    memcpy((unsigned char *)p+8,resolution,6);int rc=99;
    assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
    consume(queued[--queue_count]);
    const unsigned char rates[5]={0,0,17,17,0};
    for(unsigned int i=0;i<5;i++)transact(0x0117,i|((unsigned int)rates[i]<<8),default_caller++);
    transact(0x0117,0x100,default_caller++);
    transact(0x0102,1,default_caller++);transact(0x0109,0,default_caller++);
    transact(0x0127,condition_queue,default_caller++);
    assert(!queue_count && snapshot().prefix_received==7 && snapshot().prefix_native_freed==3);
}
static void drain(void) {
    for(unsigned int i=0;i<queue_count;i++)if(queued[i]) {void *p=queued[i];queued[i]=NULL;consume(p);}
    queue_count=0;
}
static void cleanup_all(void) {
    full_hdmi_video_state_test_reset();full_hdmi_test_reset();
    for(unsigned int i=0;i<128;i++)if(messages[i].live) {free(messages[i].pointer);messages[i].live=0;}
}
static void complete_check(void) {
    struct full_hdmi_video_state_snapshot s=snapshot();
    assert(full_hdmi_video_state_connect_ready() && s.ready && !s.faults && !s.live_messages);
    assert(s.current_hpd_low && !s.current_initializing && s.state_id==FULL_HDMI_VIDEO_HPD_LOW);
    assert(s.exit_completed && s.entry_completed && s.cached_hpd_completed);
    assert(s.condition_message_count==24 && s.condition_received==24 && s.condition_consumed==24);
    assert(s.upm_message_count==2 && s.upm_received==2 && s.upm_consumed==2 && s.upm_effective_second_id==(upm_value?3u:2u));
    assert(s.video_g58==1 && s.prefix_native_freed==3 && s.prefix_waiter_freed==3 && s.request_freed==3);
    assert(s.driver_jobs==1 && s.driver_jobs_consumed==1 && s.driver_descriptors_freed==1);
    assert(s.driver_nodes_queued==2 && s.driver_nodes_read==2 && s.driver_nodes_freed==2);
    assert(s.driver_poll_calls==2 && s.driver_wake_reads==2 && s.monitor_subscription==0x6000f);
    assert(s.driver_initialization_writes==1 && s.driver_config_writes==1 && s.monitoring_enabled);
    assert(s.sync_handle!=s.monitor_handle && s.completion_owner==s.sync_handle && s.completion_index==7);
    assert(s.driver_policy_slot==4 && !s.driver_policy_row && s.driver_policy_column==8 && !s.driver_policy);
    assert(!s.driver_current_mode && !s.driver_target_mode && !s.driver_active && !s.driver_dirty);
    assert(!s.g14c && s.g14d==1 && s.g168==300000 && !s.platform_p190 && !s.g144 && !s.g13c);
    assert(s.transition_order[0] && s.transition_order[0]<s.transition_order[1] && s.transition_order[1]<s.transition_order[2] && s.transition_order[2]<s.transition_order[3]);
    assert(s.initialization[0]==6 && !memcmp(s.initialization+1,"ILCE-7CM2",9) && !s.initialization[17]);
    assert(!memcmp(s.initialization,s.platform_initialization,18) && !memcmp(s.initialization,s.driver_initialization,18));
    assert(!memcmp(s.driver_config,s.platform_config,36) && !memcmp(s.platform_config+8,s.config,28));
    assert(!get32(s.driver_config) && !get32(s.driver_config+4));
    for(unsigned int i=0;i<13;i++) {
        assert(s.condition_queues[i]==condition_queue);
        assert(s.condition_flags[i]==(i==11?0u:1u));
    }
    assert(s.diagnostics_masked==3 && !s.original_cp_executed && !s.hardware_verified && !s.capture_verified);
}
static void *other_free(void *p) {
    int rc=99;assert(full_hdmi_video_state_release(message(p)->owner,p,real_free,record,&rc) && rc==-1021);return NULL;
}
static void run(const char *name) {
    int rc=99;
    if(!strcmp(name,"disabled")) {
        unsigned char raw[12]={0};unsigned int before=size_calls;
        assert(!full_hdmi_video_state_dispatch(FULL_HDMI_CP,raw,&io,0,&rc));
        assert(!full_hdmi_video_state_dispatch(FULL_HDMI_CP+1,raw,&io,1,&rc));
        assert(size_calls==before && rc==99);return;
    }
    if(!strcmp(name,"uninitialized")) {
        unsigned char raw[12]={0};
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,raw,&io,1,&rc) && rc==-1021);
        assert(!size_calls && !source_calls && full_hdmi_video_state_connect_begin(&io)==-1021);return;
    }
    if(!strcmp(name,"late-init")) {
        void *p=request(0x010a,0,default_caller);
        assert(full_hdmi_dispatch(FULL_HDMI_CP,p,&io,FULL_HDMI_BOOT,&rc) && !rc);
        consume(queued[--queue_count]);
        assert(full_hdmi_video_state_owner_init()==-1021 && !snapshot().history_known);
        assert(!snapshot().current_initializing && snapshot().faults && !snapshot().driver_jobs);return;
    }
    assert(!full_hdmi_video_state_owner_init());
    assert(snapshot().owner_pid==getpid() && snapshot().current_initializing && snapshot().platform_p60==2);
    if(!strcmp(name,"fork")) {
        pid_t child=fork();assert(child>=0);if(!child) {alarm(2);assert(full_hdmi_video_state_owner_init()==-1021);assert(!snapshot().initialized);_exit(0);}
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));return;
    }
    if(!strcmp(name,"metadata") || !strcmp(name,"unknown-dataflow")) {
        unsigned char *p=NULL;assert(!allocate(FULL_HDMI_CP,(void **)&p,48,1));memset(p,0,48);
        put32(p,default_caller);put32(p+4,0xa0a0a0a0u);p[8]=1;p[10]=48;
        put32(p+12,24);put32(p+16,48);p[25]=0x10;p[28]=24;p[30]=2;
        put32(p+32,4);put32(p+36,1);
        struct full_hdmi_video_state_snapshot before=snapshot();
        if(!strcmp(name,"unknown-dataflow")) {
            p[26]=1;assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
            assert(snapshot().faults && !snapshot().history_known && message(p)->live);return;
        }
        assert(!full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc));
        struct full_hdmi_video_state_snapshot after=snapshot();assert(!memcmp(&before,&after,sizeof before));real_free(FULL_HDMI_CP,p);return;
    }
    if(!strcmp(name,"unknown-input")) {
        void *p=request(0x0110,1,default_caller);
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
        assert(!snapshot().history_known && snapshot().faults && message(p)->live && !queue_count);
        assert(full_hdmi_video_state_owner_init()==-1021 && !snapshot().history_known);return;
    }
    if(!strcmp(name,"missing-io")) {
        void *p=request(0x0102,1,default_caller);struct full_imaging_io bad=io;bad.send=NULL;
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&bad,1,&rc) && rc==-1021);
        assert(!snapshot().history_known && message(p)->live);return;
    }
    if(!strcmp(name,"prefix-normalization")) {
        transact(0x0102,0x112233ff,default_caller);
        assert(snapshot().stored_g98==255 && !snapshot().platform_p60 && !snapshot().driver_jobs && snapshot().platform_p28_known && !snapshot().platform_p28);
        return;
    }
    if(!strcmp(name,"invalid0109")) {
        void *p=request(0x0109,2,default_caller);
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
        assert(queue_count==1 && get32((unsigned char *)queued[0]+8)==0xe0000001u);
        consume(queued[0]);queue_count=0;
        assert(!snapshot().prefix_received && !snapshot().platform_p7c && !snapshot().faults);return;
    }
    if(!strcmp(name,"malformed")) {
        unsigned char *p=request(0x0102,1,default_caller);p[4]=11;
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
        assert(!queue_count && message(p)->live && !snapshot().history_known);return;
    }
    if(!strcmp(name,"request-alias")) {
        void *p=request(0x0102,1,default_caller);alias_allocate=1;alias=p;
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
        assert(message(p)->live && !frees && snapshot().faults);return;
    }
    if(!strcmp(name,"prefix-source-fail")) {
        void *p=request(0x0102,1,default_caller);source_error=1;
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && rc==-1021);
        assert(message(p)->live && snapshot().faults && !snapshot().live_messages);return;
    }
    if(!strcmp(name,"prefix-request-free-fail")) {
        void *p=request(0x0102,1,default_caller);request_free_error=1;
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
        assert(snapshot().retained_request==p && snapshot().faults && message(p)->live);return;
    }
    if(!strcmp(name,"prefix-reply-free-fail")) {
        void *p=request(0x0102,1,default_caller);
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);free_error=1;
        assert(release_message(default_caller,queued[0])==-74);
        assert(snapshot().live_messages==1 && !snapshot().prefix_native_freed && snapshot().faults);return;
    }
    if(!strcmp(name,"incomplete-prefix")) {
        transact(0x0102,1,default_caller);assert(!full_hdmi_video_state_bind_backup(backup));
        assert(full_hdmi_video_state_connect_begin(&io)==1 && !snapshot().video_g58 && !snapshot().driver_jobs);
        assert(snapshot().current_initializing && snapshot().prefix_received==1);return;
    }
    if(!strcmp(name,"dynamic-queue"))condition_queue=0x8fed0321u;
    if(!strcmp(name,"fork-held"))fork_held=1;
    if(!strcmp(name,"reenter-connect"))reenter_connect=1;
    seed();
    if(!strcmp(name,"live-shared-reply")) {
        /* A later query reply must be genuinely freed in the shared owner. */
        void *p=request(0x020a,0,default_caller);
        assert(full_hdmi_video_state_dispatch(FULL_HDMI_CP,p,&io,1,&rc) && !rc);
        assert(full_hdmi_video_state_connect_begin(&io)==1 && !snapshot().video_g58);
        consume(queued[--queue_count]);return;
    }
    struct full_hdmi_snapshot before;full_hdmi_snapshot(&before);
    if(!strcmp(name,"delegated-preserves"))assert(!full_hdmi_audio_pin_connected_one());
    if(!strcmp(name,"no-backup")) {assert(full_hdmi_video_state_connect_begin(&io)==1 && !snapshot().connect_started);return;}
    assert(!full_hdmi_video_state_bind_backup(backup));
    if(!strcmp(name,"missing-required"))missing_key=0x009a0009;
    if(!strcmp(name,"failed-required"))failed_key=0x009a000c;
    if(!strcmp(name,"missing-upm"))missing_key=0x00920085;
    if(!strcmp(name,"default-config"))missing_key=0x009a0001;
    if(!strcmp(name,"full-config"))config_bytes=28;
    if(!strcmp(name,"upm-no-remap"))upm_value=0;
    if(!strcmp(name,"inline") || !strcmp(name,"inline-send-fail") || !strcmp(name,"inline-reuse"))inline_consume=1;
    if(!strcmp(name,"inline-reuse"))reuse_after_free=1;
    if(!strcmp(name,"inline-send-fail"))send_error_after_consume=1;
    if(!strcmp(name,"send-fail"))send_error=1;
    if(!strcmp(name,"alloc-fail"))allocation_error=1;
    if(!strcmp(name,"alloc-partial"))partial_allocate=1;
    if(!strcmp(name,"cleanup-fail")) {send_error=1;free_error=1;}
    if(!strcmp(name,"alloc-short"))short_allocate=1;
    if(!strcmp(name,"early-free"))early_free=1;
    if(!strcmp(name,"inflight-send-fail") || !strcmp(name,"inflight-free-fail")) {
        threaded_failure=1;thread_free_failure=!strcmp(name,"inflight-free-fail");
    }
    if(!strncmp(name,"kernel-receipt",14)) {
        kernel_mode=!strcmp(name,"kernel-receipt-prepare-fail")?2:!strcmp(name,"kernel-receipt-incomplete")?3:1;
        assert(!full_hdmi_video_state_bind_kernel_observer(kernel_receipt));
    }
    struct full_hdmi_video_state_snapshot before_init=snapshot();
    assert(!full_hdmi_video_state_owner_init());
    struct full_hdmi_video_state_snapshot same=snapshot();assert(!memcmp(&before_init,&same,sizeof same));
    rc=full_hdmi_video_state_connect_begin(&io);
    if(kernel_mode) {
        if(kernel_mode==1) {
            assert(rc==1 && kernel_prepared==2 && kernel_receipts==2 && snapshot().upm_consumed==2);
            assert(snapshot().live_messages==24 && queue_count==24 && !snapshot().ready);
            drain();complete_check();assert(!snapshot().live_messages && !snapshot().retained_messages);
        } else {
            assert(rc==-1021 && kernel_prepared==1 && snapshot().faults && !snapshot().upm_consumed && !snapshot().ready);
            if(kernel_mode==2)assert(!kernel_receipts && !snapshot().live_messages);
            else assert(kernel_receipts==1 && snapshot().live_messages==1 && snapshot().retained_messages==1);
        }
        return;
    }
    if(!strcmp(name,"missing-required") || !strcmp(name,"missing-upm")) {
        assert(rc==1 && !snapshot().faults && snapshot().current_initializing && !snapshot().connect_started && !snapshot().driver_jobs && !queue_count);return;
    }
    if(!strcmp(name,"failed-required")) {
        assert(rc==-1021 && snapshot().faults && snapshot().current_initializing && !snapshot().driver_jobs);return;
    }
    if(!strcmp(name,"cleanup-fail")) {
        assert(rc==-1021 && snapshot().faults && snapshot().retained_messages==1 && snapshot().live_messages==1);
        assert(!snapshot().upm_consumed && !snapshot().ready);return;
    }
    if(!strcmp(name,"alloc-fail") || !strcmp(name,"alloc-partial") || !strcmp(name,"alloc-short") || !strcmp(name,"early-free") || !strcmp(name,"send-fail") || !strcmp(name,"inline-send-fail")) {
        assert(rc==-1021 && snapshot().faults && !full_hdmi_video_state_connect_ready());
        assert(full_hdmi_video_state_owner_init()==-1021);return;
    }
    if(threaded_failure) {
        assert(rc==-1021 && thread_started && snapshot().faults && !full_hdmi_video_state_connect_ready());
        pthread_mutex_lock(&race_mutex);thread_continue=1;pthread_cond_broadcast(&race_condition);pthread_mutex_unlock(&race_mutex);
        assert(!pthread_join(receiver_thread,NULL));
        assert(snapshot().condition_consumed==(thread_free_failure?0u:1u));
        assert(!snapshot().ready && race_destination==condition_queue);
        if(thread_free_failure)assert(message(race_message)->live);
        return;
    }
    if(!strcmp(name,"inline") || !strcmp(name,"inline-reuse")) {assert(!rc);complete_check();return;}
    assert(rc==1 && !full_hdmi_video_state_connect_ready() && snapshot().live_messages==26 && queue_count==26);
    assert(snapshot().condition_message_count==24 && !snapshot().condition_consumed && !snapshot().upm_consumed);
    assert(snapshot().driver_jobs_consumed==1 && snapshot().driver_nodes_freed==2 && snapshot().current_hpd_low);
    void *condition=queued[2];struct message *cm=message(condition);assert(cm->bytes==20 && cm->owner==condition_queue);
    assert(get32(condition)==2 && !get32((unsigned char *)condition+4) && get32((unsigned char *)condition+8)==1);
    assert(!memcmp(queued[2],queued[14],20) && queued[2]!=queued[14]);
    if(!strcmp(name,"wrong-source")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source^1u,20)==-1021);
        assert(!snapshot().condition_received && message(condition)->live && !snapshot().ready);return;
    }
    if(!strcmp(name,"wrong-length")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,19)==-1021);
        assert(!snapshot().condition_received && message(condition)->live && !snapshot().ready);return;
    }
    if(!strcmp(name,"wrong-payload")) {
        ((unsigned char *)condition)[8]=0;
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==-1021);
        assert(!snapshot().condition_received && message(condition)->live && !snapshot().ready);return;
    }
    if(!strcmp(name,"no-receive")) {
        assert(release_message(condition_queue,condition)==-1021);
        assert(!snapshot().condition_received && !snapshot().condition_consumed && message(condition)->live);return;
    }
    if(!strcmp(name,"wrong-owner")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==1);
        assert(release_message(condition_queue+1,condition)==-1021);
        assert(!snapshot().condition_consumed && message(condition)->live);return;
    }
    if(!strcmp(name,"wrong-thread")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==1);
        pthread_t worker;assert(!pthread_create(&worker,NULL,other_free,condition));assert(!pthread_join(worker,NULL));
        assert(!snapshot().condition_consumed && message(condition)->live);return;
    }
    if(!strcmp(name,"free-fail")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==1);free_error=1;
        assert(release_message(condition_queue,condition)==-74 && !snapshot().condition_consumed && message(condition)->live);return;
    }
    if(!strcmp(name,"mutated-after-receive")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==1);
        ((unsigned char *)condition)[16]=1;assert(release_message(condition_queue,condition)==-1021);
        assert(!snapshot().condition_consumed && message(condition)->live);return;
    }
    if(!strcmp(name,"repeat-receive")) {
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==1);
        assert(full_hdmi_video_state_observe_receive(condition_queue,condition,cm->source,20)==-1021);
        assert(snapshot().condition_received==1 && !snapshot().condition_consumed);return;
    }
    if(!strcmp(name,"bad-upm-remap")) {
        struct message *m=message(queued[1]);
        assert(full_hdmi_video_state_observe_receive(m->owner,queued[1],m->source,m->bytes)==1);
        /* Backup says3, but an unmodified body2 cannot prove k_psave_api ran. */
        assert(release_message(m->owner,queued[1])==-1021 && !snapshot().upm_consumed && message(queued[1])->live);return;
    }
    unsigned int previous_allocations=allocations;
    assert(full_hdmi_video_state_connect_begin(&io)==1 && allocations==previous_allocations);
    drain();complete_check();
    if(!strcmp(name,"default-config")) {
        const unsigned char expected[10]={0x92,0x9b,0x52,0xf4,0x8d,0x72,0x96,0x8c,0xc2,0x92};
        assert(!memcmp(snapshot().config,expected,10));
    } else for(unsigned int i=0;i<28;i++)assert(snapshot().config[i]==(i<config_bytes?i+1:0));
    struct full_hdmi_snapshot after;full_hdmi_snapshot(&after);
    if(!strcmp(name,"delegated-preserves")) {
        assert(after.audio_pin_connected_known && after.audio_pin_connected==1 && after.audio_pin_connected_writes==1);
        after.audio_pin_connected=before.audio_pin_connected;after.audio_pin_connected_known=before.audio_pin_connected_known;
        after.audio_pin_connected_writes=before.audio_pin_connected_writes;after.audio_pin_connected_owner_pid=before.audio_pin_connected_owner_pid;
    }
    assert(!memcmp(&before,&after,sizeof before));
    assert(full_hdmi_video_state_connect_begin(&io)==0 && allocations==previous_allocations);
    struct full_hdmi_video_state_snapshot before_reinit=snapshot();assert(!full_hdmi_video_state_owner_init());
    same=snapshot();assert(!memcmp(&before_reinit,&same,sizeof same));
}
int main(int argc,char **argv) {
    assert(argc==2);alarm(20);run(argv[1]);cleanup_all();
    puts("HDMI_VIDEO_STATE_HOST_TEST_PASS");return 0;
}
