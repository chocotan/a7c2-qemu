/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "adf-set-input-device.h"
#include "adf-public-config.h"
#include "adf-aip-commands.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define CALLER 0x81234567u
#define ALLOCATOR_SOURCE 0x8a110c01u
static const unsigned char proc_request[12]={0x0d,0x20,0x23,3,12,0,1,0x80,0,0,0,0};
static const unsigned char proc_reply[12]={0x0d,0x20,0x23,0x13,12,0,1,0x80,0,0,0x58,0};
static const unsigned char input_request[14]={0x0d,0x20,0x36,3,14,0,1,0x80,0,2,0,0,0,0};
static const unsigned char input_reply[12]={0x0d,0x20,0x36,0x13,12,0,1,0x80,0,0,0x58,0};
static const unsigned char kikilog_body[20]={0x84,2,0x11,0x21,0,0,0,0,0,0x81,0,2,0,0,0,0,0,0,0,0};
enum kind { PROC_REQUEST, INPUT_REQUEST, SECOND_REQUEST, PROC_REPLY, INPUT_REPLY, KIKILOG };
struct message { unsigned int bytes,source,owner,released; enum kind kind; unsigned char body[24]; };
static struct message old_request,request,second,*old_reply,*reply,*kikilog;
static pthread_mutex_t resource_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_t guard_thread;
static pid_t host_pid;
static unsigned int caller=CALLER,phase,held,reserves,guard_releases,callback_order;
static unsigned int size_calls,source_calls,records,allocations[3],sends[3],set_sources[3];
static unsigned int free_attempts[6],frees[6],source5_old,source5_new,old_events,new_events;
static unsigned int old_ctor,old_history,old_af,old_b0,old_disable,old_stages,old_input,old_inner;
static unsigned int dependencies,metadata,glee,control102,hotshoe,config03,config02,dispatches;
static unsigned int metadata_order,glee_order,control102_order,hotshoe_order,applied_order;
static unsigned int queued_order,request_free_order,guard_release_order,kikilog_order,relay_order;
static unsigned int reply_free_logs,recovery_logs,pending_logs,reentrant_checks,kernel_frees;
static uint64_t previous_deadline;
static int reserve_error,allocate_error,error_pointer,null_reply,original_reply,reply_bytes=12;
static int source_error,send_error,cleanup_error,request_error,reply_error,reenter;
static int kiki_allocate_error,kiki_pointer,kiki_null,kiki_alias,kiki_bytes=20,kiki_send_error,kiki_cleanup_error;
static void *sent_reply;
static unsigned char kernel_copy[20];
static int ready_pipe[2],finish_pipe[2],block_request;

static struct full_adf_set_input_snapshot snapshot(void) {
    struct full_adf_set_input_snapshot s;full_adf_set_input_snapshot(&s);return s;
}
static struct full_adf_proc_snapshot proc_snapshot(void) {
    struct full_adf_proc_snapshot s;full_adf_proc_snapshot(&s);return s;
}
static void host_callback(void) {assert(getpid()==host_pid);}
static void guarded(void) {
    host_callback();assert(held && pthread_equal(guard_thread,pthread_self()));
    assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);
}
static struct message *meta(void *body) {
    assert(body);struct message *m=(struct message *)((unsigned char *)body - offsetof(struct message,body));
    assert(m==&old_request || m==&request || m==&second || m==old_reply || m==reply || m==kikilog);
    assert(!m->released);return m;
}
static unsigned int size(void *body) {host_callback();size_calls++;return meta(body)->bytes;}
static unsigned int source(void *body) {host_callback();source_calls++;return meta(body)->source;}
static int reserve(void) {
    host_callback();reserves++;assert(!pthread_mutex_lock(&resource_mutex));
    if(reserve_error) {assert(!pthread_mutex_unlock(&resource_mutex));return reserve_error;}
    assert(!held);held=1;guard_thread=pthread_self();return 0;
}
static void release_guard(void) {
    guarded();held=0;guard_releases++;guard_release_order=++callback_order;
    assert(!pthread_mutex_unlock(&resource_mutex));
}
static const struct full_adf_proc_guard guard={reserve,release_guard};
static int release(unsigned int owner,void *body) {
    host_callback();struct message *m=meta(body);assert(owner==m->owner);
    if(held)guarded();
    free_attempts[m->kind]++;
    if(m->kind==INPUT_REQUEST && request_error)return request_error;
    if(m->kind==INPUT_REPLY && (held?cleanup_error:reply_error))return held?cleanup_error:reply_error;
    if(m->kind==KIKILOG && kiki_cleanup_error)return kiki_cleanup_error;
    frees[m->kind]++;
    if(m->kind<=SECOND_REQUEST) {m->released=1;if(m==&request)request_free_order=++callback_order;}
    else {
        if(m==old_reply)old_reply=0;else if(m==reply)reply=0;else {assert(m==kikilog);kikilog=0;}
        free(m);
    }
    return 0;
}
static void set_source(void *body,unsigned int value) {
    guarded();struct message *m=meta(body);assert(value==FULL_ADF_SET_INPUT_INPUT);
    assert(m==old_reply || m==reply);set_sources[m==old_reply?0:1]++;
    if(m==old_reply || !source_error)m->source=value;
}
static int send(unsigned int owner,void *body) {
    guarded();struct message *m=meta(body);assert(owner==m->owner);
    if(m==kikilog) {
        assert(phase==1 && owner==FULL_ADF_SET_INPUT_KIKILOG && m->bytes==20);
        assert(m->source==ALLOCATOR_SOURCE && !memcmp(body,kikilog_body,20));
        assert(new_events==4 && dispatches==4 && !relay_order && !set_sources[2]);sends[2]++;
        if(kiki_send_error)return kiki_send_error;
        /* This fake kernel sink owns a successful notification immediately. */
        memcpy(kernel_copy,body,20);free(m);kikilog=0;kernel_frees++;return 0;
    }
    assert(owner==caller && m->bytes==12 && m->source==FULL_ADF_SET_INPUT_INPUT);
    if(m==old_reply) {
        assert(!phase && old_events==4 && old_af==1 && old_b0==1 && old_disable==14);
        assert(old_ctor==1 && old_history==1 && old_input==1 && old_inner==1);
        assert(!memcmp(body,proc_reply,12));sends[0]++;return 0;
    }
    assert(m==reply && phase==1 && body!=request.body && !memcmp(body,input_reply,12));
    assert(new_events==4 && dispatches==4 && config03==1 && config02==1 && applied_order);
    sends[1]++;sent_reply=body;return send_error;
}
static uint64_t field(const char *text,const char *key) {
    const char *p=text;
    while((p=strstr(p,key)) && p!=text && p[-1]!=' ')p++;
    if(!p)fprintf(stderr,"missing %s in %s\n",key,text);
    assert(p);p+=strlen(key);char *end;unsigned long long value=strtoull(p,&end,0);
    assert(end!=p && (!*end || *end==' '));return (uint64_t)value;
}
static void tick(const char *text,int old) {
    guarded();unsigned int n=old?old_events+1:new_events+5;
    assert(field(text,"event=")==n && field(text,"guest_timerfd_expirations=")==1);
    uint64_t deadline=field(text,"deadline_ns="),observed=field(text,"observed_ns=");
    assert(observed>=deadline && (!previous_deadline || deadline>=previous_deadline+1000000));
    assert(field(text,"hardware_counter=")==n && field(text,"hardware_source=")==7);
    assert(field(text,"software_source=")==5 && field(text,"policy_period_ns=")==1000000);
    if(old) {
        assert(field(text,"hardware_epoch=")==n && field(text,"cache_epoch=")==n && field(text,"fb_epoch=")==n);
        assert(field(text,"cache_counter=")==n && field(text,"fb_counter=")==n);old_events++;
    } else {
        assert(field(text,"generation=")==2 && field(text,"epoch=")==n);
        assert(field(text,"subscriber=")==0x9058003fu && field(text,"sender=")==0x928c0786u);
        assert(field(text,"queued=")==new_events+1 && field(text,"consumed=")==new_events+1);
        assert(field(text,"getter_advances=")==0 && hotshoe==1);new_events++;source5_new++;
    }
    previous_deadline=deadline;
}
static void record(const char *tag,const char *text) {
    host_callback();records++;callback_order++;
    fprintf(stdout,"%s%s\n",tag,text);
    assert(strstr(text,"original_cp_executed=0") && strstr(text,"hardware_verified=0"));
    assert(strstr(text,"native_frequency_verified=0") && strstr(text,"original_event_identity_verified=0"));
    assert(strstr(text,"pcm_verified=0") && strstr(text,"frames_verified=0") && strstr(text,"capture_verified=0"));
    if(!strncmp(tag,"FULL_ADF_PROC_",14)) {
        assert(strstr(text,"scope=virtualSource7ControlOnly"));
        if(!strcmp(tag,"FULL_ADF_PROC_EVENT "))tick(text,1);
        else if(!strcmp(tag,"FULL_ADF_PROC_COLD_OWNERS ")) {
            guarded();assert(!old_events && !old_ctor && field(text,"initializations=")==1);old_ctor++;
        } else if(!strcmp(tag,"FULL_ADF_PROC_COLD_INPUT_HISTORY ")) {
            guarded();assert(old_events==4 && old_ctor==1 && !old_history);
            assert(field(text,"same_initialized_owner=")==1 && field(text,"control30_notes=")==1);
            assert(field(text,"actual_readbacks=")==1 && field(text,"actual_complete=")==1);old_history++;
        } else if(!strcmp(tag,"FULL_ADF_PROC_COMMAND_CONSUMED ")) {
            guarded();assert(field(text,"AF_consumed=")==1);
            if(old_events==1)old_af++;else {assert(old_events==4 && field(text,"B0_consumed=")==1);old_b0++;}
        } else if(!strcmp(tag,"FULL_ADF_PROC_DISABLE_READBACK ")) {
            guarded();old_disable=(unsigned int)field(text,"readbacks=");assert(field(text,"writes=")==old_disable);
        } else if(!strcmp(tag,"FULL_ADF_PROC_AVIO_STAGE ")) {guarded();old_stages++;}
        else if(!strcmp(tag,"FULL_ADF_PROC_INPUT_DRAINED ")) {guarded();old_input++;}
        else if(!strcmp(tag,"FULL_ADF_PROC_INNER_RELAY ")) {guarded();old_inner++;}
        else if(!strcmp(tag,"FULL_ADF_PROC_SOURCE5_CONSUMED ")) {guarded();source5_old++;}
        return;
    }
    assert(!strncmp(tag,"FULL_ADF_SET_INPUT_",19) && strstr(text,"scope=virtualInputConfigurationS0"));
    if(!strcmp(tag,"FULL_ADF_SET_INPUT_REQUEST ")) {
        assert(field(text,"caller=")==caller && field(text,"bytes=")==14);
        if(block_request) {char byte=1;assert(write(ready_pipe[1],&byte,1)==1);assert(read(finish_pipe[0],&byte,1)==1);}
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_DEPENDENCIES ")) {
        guarded();assert(old_ctor==1 && old_history==1 && frees[PROC_REPLY]==1 && !dependencies);
        assert(field(text,"counter_before=")==4 && field(text,"epoch_before=")==4);
        assert(field(text,"same_hotshoe_owner=")==1 && field(text,"same_glee_owner=")==1);
        assert(field(text,"same_command_buffer=")==1 && field(text,"same_source7_clock=")==1);
        assert(field(text,"capability_word7=")==0 && field(text,"capability_word8=")==1);dependencies++;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_PUBLIC_CONFIG ")) {
        guarded();assert(dependencies==1 && field(text,"asset_bytes=")==393 && field(text,"known_bytes=")==362);
        assert(field(text,"unknown_bytes=")==31 && field(text,"init_selector=")==2);
        assert(strstr(text,"unknown_read_policy=reject") && strstr(text,"source=public_ALLLANG_3dab"));
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_CONTROL139 ")) {
        guarded();assert(!metadata && !glee && !hotshoe && !new_events && field(text,"command_count=")==3);
        assert(strstr(text,"queued=AD/AB0/AE0") && field(text,"opcode48_queued=")==0);
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_METADATA ")) {
        guarded();assert(!metadata && !glee && !control102 && !hotshoe && !new_events);
        assert(field(text,"owner_request_generation=")==1 && field(text,"hotshoe_callback_running=")==1);
        assert(field(text,"queued_commands=")==3 && field(text,"AIP102_queued=")==0);
        assert(field(text,"config_commits=")==1 && field(text,"digital_pending=")==0);
        assert(strstr(text,"active_cache=00020000") && strstr(text,"inner_raw=042001840c00010000000000"));
        metadata++;metadata_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_GLEE ")) {
        guarded();assert(metadata==1 && !glee && !control102 && !hotshoe);
        assert(field(text,"owner_request_generation=")==1 && field(text,"control30_notes=")==1);
        assert(field(text,"control0_callbacks=")==1 && field(text,"control1_type=")==0);
        assert(field(text,"control1_source=")==1 && field(text,"control1_callback=")==0);
        assert(field(text,"synchronous_reference_branch=")==1);glee++;glee_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_CONTROL102 ")) {
        guarded();assert(glee==1 && metadata==1 && !control102 && !hotshoe);
        assert(field(text,"metadata_already_committed=")==1 && field(text,"selector=")==2);
        assert(field(text,"command_count=")==9 && field(text,"body_bytes=")==132);
        assert(strstr(text,"queued=B8/03/02/11/B6/B7") && field(text,"opcode42_queued=")==0);
        control102++;control102_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_HOTSHOE ")) {
        guarded();assert(control102==1 && !hotshoe && !new_events);
        assert(field(text,"owner_request_generation=")==1 && field(text,"fifo_popped_before_callback=")==1);
        assert(field(text,"current_type_committed_after_callback=")==1 && field(text,"callback_returned=")==1);
        assert(field(text,"busy=")==0 && field(text,"fifo_count=")==0);hotshoe++;hotshoe_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_EVENT "))tick(text,0);
    else if(!strcmp(tag,"FULL_ADF_SET_INPUT_CONFIG_READBACK ")) {
        guarded();assert(new_events==1 && !dispatches && field(text,"selector=")==2);
        if(field(text,"opcode=")==3) {
            assert(!config03 && !config02 && field(text,"writes=")==109 && field(text,"public_reads=")==79);
            assert(field(text,"classification2008=")==3 && field(text,"classification200c=")==3);
            assert(field(text,"route2060=")==0 && field(text,"route2064=")==0);config03++;
        } else {
            assert(field(text,"opcode=")==2 && config03==1 && !config02);
            assert(field(text,"writes=")==222 && field(text,"public_reads=")==131);
            assert(field(text,"cache0=")==0x08080100 && field(text,"cache1=")==0x20011ff7);
            assert(field(text,"cache7=")==0 && field(text,"cache8=")==0x43211121);
            assert(field(text,"route2060=")==0 && field(text,"route2064=")==1);
            assert(field(text,"route2068=")==8 && field(text,"route206c=")==8);
            assert(field(text,"classification2008=")==0 && field(text,"classification200c=")==1);config02++;
        }
        assert(field(text,"readbacks=")==field(text,"writes="));
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_AIP_DISPATCH ")) {
        guarded();assert(new_events==dispatches+1 && field(text,"event=")==new_events+4);
        assert(field(text,"commands_interpreted=")==9 && field(text,"AB_status=")==1);
        assert(field(text,"ring_read=")==9 && field(text,"ring_write=")==9);
        assert(field(text,"failure_history_preserved=")==1 && field(text,"old_tail_rechecked=")==0);
        assert(field(text,"first_uninspected_preserved=")==7);
        if(!dispatches) {
            assert(field(text,"snapshot_count=")==9 && field(text,"checked=")==2 && field(text,"cursor_words=")==6);
            assert(field(text,"task_rc=")==FULL_ADF_AIP_TASK_ERROR);
        } else assert(!field(text,"snapshot_count=") && !field(text,"checked=") && !field(text,"cursor_words=") && !field(text,"task_rc="));
        assert(field(text,"register_writes=")==222 && field(text,"register_readbacks=")==222);dispatches++;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_KIKILOG_QUEUED ")) {
        guarded();assert(kernel_frees==1 && !kikilog && !memcmp(kernel_copy,kikilog_body,20));
        assert(field(text,"allocator_source=")==ALLOCATOR_SOURCE && field(text,"source_overridden=")==0);
        assert(strstr(text,"padding18_19=virtual_zero") && field(text,"parameter_consumption_verified=")==0);
        kikilog_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_INNER_RELAY ")) {
        guarded();assert(new_events==4 && dispatches==4 && !relay_order);
        assert(field(text,"outer_status=")==0x580000 && field(text,"status=")==0);
        assert(field(text,"first_AIP_task_rc=")==FULL_ADF_AIP_TASK_ERROR && field(text,"AB_status=")==1);relay_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_APPLIED ")) {
        guarded();assert(relay_order && !applied_order && metadata_order<glee_order && glee_order<control102_order);
        assert(control102_order<hotshoe_order && field(text,"AIP_first_task_rc=")==FULL_ADF_AIP_TASK_ERROR);
        assert(field(text,"AB_status=")==1 && field(text,"AB_register_writes=")==0);
        assert(field(text,"outer_status=")==0x580000);applied_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_QUEUED ")) {
        guarded();assert(sends[1]==1 && !send_error && !frees[INPUT_REQUEST] && !queued_order);
        assert(field(text,"destination=")==caller && strstr(text,"raw=0d2036130c00018000005800"));queued_order=callback_order;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_COMMIT ")) {
        guarded();assert(frees[INPUT_REQUEST]==1 && queued_order && strstr(text,"ap_consumed=0"));
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_PENDING ")) {
        assert(strstr(text,"faulted_pending=1") && strstr(text,"normal_completion=0"));pending_logs++;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_REPLY_FREE ")) {
        assert(!held && field(text,"ap_consumed=")==1 && strstr(text,"kind=queued-reply"));reply_free_logs++;
    } else if(!strcmp(tag,"FULL_ADF_SET_INPUT_RECOVERY_FREE ")) {assert(!held && !field(text,"ap_consumed="));recovery_logs++;}
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count);
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count) {
    guarded();assert(count==1);unsigned int slot=phase?(owner==FULL_ADF_SET_INPUT_KIKILOG?2u:1u):0u;
    allocations[slot]++;
    if(!phase) {
        struct full_adf_proc_snapshot s=proc_snapshot();assert(s.busy && s.worker_active && s.guard_held && !s.live_reply);
        assert(owner==caller && bytes==12 && !old_reply);old_reply=calloc(1,sizeof *old_reply);assert(old_reply);
        old_reply->kind=PROC_REPLY;old_reply->bytes=bytes;old_reply->owner=owner;old_reply->source=ALLOCATOR_SOURCE;
        *out=old_reply->body;return 0;
    }
    struct full_adf_set_input_snapshot s=snapshot();
    assert(s.busy && s.worker_active && s.guard_held && !s.live_reply && s.events==4);
    if(reenter) {
        int rc=77;assert(full_adf_set_input_dispatch(FULL_ADF_SET_INPUT_INPUT,second.body,&io,&guard,1,&rc)==1 && rc==-1021);
        reentrant_checks++;
    }
    struct message **target=slot==2?&kikilog:&reply;
    int rc=slot==2?kiki_allocate_error:allocate_error;
    int pointer=slot==2?kiki_pointer:error_pointer;
    int null=slot==2?kiki_null:null_reply;
    int alias=slot==2?kiki_alias:original_reply;
    assert(owner==(slot==2?FULL_ADF_SET_INPUT_KIKILOG:caller) && bytes==(slot==2?20u:12u));
    if(slot==1)assert(s.applications==1 && s.inner_consumed==1);
    else assert(!s.applications && !s.inner_consumed && s.inner_queued==1);
    if(alias) {*out=request.body;return rc;}
    if(null || (rc && !pointer)) {*out=0;return rc;}
    assert(!*target);*target=calloc(1,sizeof **target);assert(*target);
    (*target)->kind=slot==2?KIKILOG:INPUT_REPLY;(*target)->bytes=(unsigned int)(slot==2?kiki_bytes:reply_bytes);
    (*target)->owner=owner;(*target)->source=ALLOCATOR_SOURCE;*out=(*target)->body;return rc;
}
static void init_message(struct message *m,enum kind kind,unsigned int source_id) {
    memset(m,0,sizeof *m);m->kind=kind;m->source=source_id;m->owner=FULL_ADF_SET_INPUT_INPUT;
    m->bytes=kind==PROC_REQUEST?12:14;memcpy(m->body,kind==PROC_REQUEST?proc_request:input_request,m->bytes);
}
static void pause_once(void) {const struct timespec t={0,1000000};assert(!nanosleep(&t,0));}
static struct full_adf_set_input_snapshot wait_finish(void) {
    for(unsigned int i=0;i<2000;i++) {
        struct full_adf_set_input_snapshot s=snapshot();
        if(!s.busy) {assert(!s.worker_active && !s.guard_held && !held);return s;}pause_once();
    }
    assert(!"input worker did not finish");return snapshot();
}
static void prior(int consume) {
    int rc=77;assert(!phase && !reserves);
    assert(full_adf_proc_dispatch(FULL_ADF_PROC_INPUT,old_request.body,&io,&guard,1,&rc)==1 && !rc);
    struct full_adf_proc_snapshot s={0};
    for(unsigned int i=0;i<2000;i++) {s=proc_snapshot();if(!s.busy)break;pause_once();}
    assert(!s.busy && !s.worker_active && !s.guard_held && !held && !s.faults && s.clean_completion);
    assert(s.events==4 && s.source5_queued==4 && s.source5_consumed==4 && source5_old==4);
    assert(s.cold_owners_initialized==1 && s.cold_control30_notes==1 && old_ctor==1 && old_history==1);
    assert(s.af_consumed==1 && s.b0_consumed==1 && s.disable_writes==14 && s.disable_readbacks==14);
    assert(s.avio_stages==3 && old_stages==3 && s.input_readbacks==1 && s.input_complete==1);
    assert(s.inner_queued==1 && s.inner_consumed==1 && !s.inner_status && s.outer_status==0x580000);
    assert(sends[0]==1 && frees[PROC_REQUEST]==1 && old_reply && s.live_reply==old_reply->body && !s.ap_consumed);
    assert(guard_releases==1 && !memcmp(old_reply->body,proc_reply,12));
    if(consume) {
        assert(full_adf_proc_release_reply(caller,old_reply->body,release,record,&rc)==1 && !rc);
        s=proc_snapshot();assert(s.ap_consumed==1 && s.reply_freed==1 && !old_reply && frees[PROC_REPLY]==1);
    }
    phase=1;
}
static int free_owned(unsigned int owner,void *body) {
    int rc=77;assert(full_adf_set_input_release_reply(owner,body,release,record,&rc)==1);return rc;
}
static unsigned int total_attempts(void) {
    unsigned int total=0;for(unsigned int i=0;i<6;i++)total+=free_attempts[i];return total;
}
static void reject_owner(unsigned int correct,void *body) {
    unsigned int before=total_attempts();assert(free_owned(correct+1,body)==-1021);
    assert(total_attempts()==before && !snapshot().ap_consumed);
}
static void recover(void) {
    struct full_adf_set_input_snapshot s=snapshot();assert(!s.busy && !held);
    request_error=reply_error=cleanup_error=kiki_cleanup_error=0;
    if(s.live_reply)assert(!free_owned(s.reply_owner,s.live_reply));
    s=snapshot();if(s.retained_cleanup) {reject_owner(s.cleanup_owner,s.retained_cleanup);assert(!free_owned(s.cleanup_owner,s.retained_cleanup));}
    s=snapshot();if(s.retained_request) {reject_owner(s.request_owner,s.retained_request);assert(!free_owned(s.request_owner,s.retained_request));}
    s=snapshot();assert(!s.live_reply && !s.retained_reply && !s.retained_request && !s.retained_cleanup && !reply && !kikilog);
    if(old_reply) {int rc=77;assert(full_adf_proc_release_reply(caller,old_reply->body,release,record,&rc)==1 && !rc);}
    assert(!old_reply && !pthread_mutex_trylock(&resource_mutex));assert(!pthread_mutex_unlock(&resource_mutex));
}
static int dispatch_with(const struct full_imaging_io *transport,const struct full_adf_proc_guard *g) {
    int rc=77;assert(full_adf_set_input_dispatch(FULL_ADF_SET_INPUT_INPUT,request.body,transport,g,1,&rc)==1);return rc;
}
static void no_acceptance(void) {
    struct full_adf_set_input_snapshot s=snapshot();assert(!s.requests && !s.busy && !s.configured);
    assert(!reserves && !records && !allocations[1] && !allocations[2] && !total_attempts());
}
static void invalid_cases(const char *name) {
    if(!strcmp(name,"disabled")) {
        for(int enabled=0;enabled<=2;enabled+=2) {int rc=77;assert(!full_adf_set_input_dispatch(FULL_ADF_SET_INPUT_INPUT,request.body,&io,&guard,enabled,&rc) && rc==77);}
    } else if(!strcmp(name,"unrelated")) {
        for(unsigned int i=0;i<7;i++) {
            init_message(&request,INPUT_REQUEST,caller);unsigned int destination=FULL_ADF_SET_INPUT_INPUT;
            if(i==0)destination++;
            if(i==1)request.body[0]=0;
            if(i==2)request.body[2]=0;
            if(i==3)request.body[3]=4;
            if(i==4)request.bytes=3;
            if(i==5)request.bytes=0;
            int rc=77;assert(!full_adf_set_input_dispatch(destination,i==6?0:request.body,&io,&guard,1,&rc) && rc==77);
        }
    } else if(!strcmp(name,"invalid-envelope")) {
        for(unsigned int i=4;i<16;i++) {
            init_message(&request,INPUT_REQUEST,caller);if(i<14)request.body[i]^=1;else request.bytes=i==14?13:15;
            assert(dispatch_with(&io,&guard)==-1021);
        }
    } else if(!strcmp(name,"invalid-caller")) {
        const unsigned int invalid[]={0,0x80000000,FULL_ADF_SET_INPUT_INPUT,0x71234567,0xf1234567};
        for(unsigned int i=0;i<sizeof invalid/sizeof *invalid;i++) {init_message(&request,INPUT_REQUEST,invalid[i]);assert(dispatch_with(&io,&guard)==-1021);}
    } else if(!strcmp(name,"missing-transport")) {
        for(unsigned int i=0;i<8;i++) {
            struct full_imaging_io incomplete=io;
            if(i==0)incomplete.allocate=0;
            if(i==1)incomplete.release=0;
            if(i==2)incomplete.set_source=0;
            if(i==3)incomplete.send=0;
            if(i==4)incomplete.source=0;
            if(i==5)incomplete.size=0;
            int rc=77;
            if(i<5)assert(dispatch_with(&incomplete,&guard)==-1021);
            else assert(!full_adf_set_input_dispatch(FULL_ADF_SET_INPUT_INPUT,request.body,i==6?0:&incomplete,&guard,1,i==7?0:&rc) && rc==77);
        }
    } else {
        assert(!strcmp(name,"missing-guard"));
        for(unsigned int i=0;i<3;i++) {struct full_adf_proc_guard incomplete=guard;if(i==1)incomplete.reserve=0;if(i==2)incomplete.release=0;assert(dispatch_with(&io,i?&incomplete:0)==-1021);}
    }
    no_acceptance();
}
static void *blocked_dispatch(void *unused) {(void)unused;assert(!dispatch_with(&io,&guard));return 0;}
static void fork_case(int locked) {
    pthread_t thread;char byte=1;
    if(locked) {
        phase=1;block_request=1;assert(!pipe(ready_pipe) && !pipe(finish_pipe));
        assert(!pthread_create(&thread,0,blocked_dispatch,0));assert(read(ready_pipe[0],&byte,1)==1);
    }
    unsigned int sizes=size_calls,sources=source_calls,logs=records;
    pid_t child=fork();assert(child>=0);
    if(!child) {
        alarm(2);int rc=77;
        assert(full_adf_set_input_dispatch(FULL_ADF_SET_INPUT_INPUT,request.body,&io,&guard,1,&rc)==1 && rc==-1021);
        struct full_adf_set_input_snapshot s=snapshot();assert(s.faults && s.owner_pid==(int)host_pid && !s.configured);
        assert(full_adf_set_input_release_reply(FULL_ADF_SET_INPUT_INPUT,request.body,release,record,&rc)==1 && rc==-1021);
        assert(full_adf_set_input_owner_init()==-1021 && size_calls==sizes && source_calls==sources && records==logs);
        assert(!reserves && !total_attempts() && !allocations[1] && !allocations[2]);_exit(0);
    }
    int status=0;assert(waitpid(child,&status,0)==child);assert(WIFEXITED(status) && WEXITSTATUS(status)==0);
    if(locked) {
        assert(write(finish_pipe[1],&byte,1)==1);assert(!pthread_join(thread,0));
        for(unsigned int i=0;i<2;i++) {assert(!close(ready_pipe[i]));assert(!close(finish_pipe[i]));}
        struct full_adf_set_input_snapshot s=wait_finish();assert(s.faults && s.retained_request==request.body && !s.queued);
        recover();
    } else no_acceptance();
}
static void applied_backend(struct full_adf_set_input_snapshot s) {
    assert(s.dependency_claimed==1 && s.capability_word7==0 && s.capability_word8==1 && s.init_selector==2);
    assert(s.hotshoe_callbacks==1 && s.hotshoe_commits==1 && s.glee_callbacks==1 && s.glee_readbacks==1);
    assert(!s.pending_config && s.config_commits==1 && !s.completion_mask && !s.digital_pending);
    assert(!s.active_type && s.active_channels==2 && !s.active_sampling && !s.active_depth);
    assert(s.control139==1 && s.control131==1 && s.control141==2 && s.control102==1 && s.control110==1);
    assert(!s.mask650 && s.value7c==1 && !s.abb65c && s.abb660==1 && !s.abb_bb && !s.abb_c0 && !s.software_s);
    assert(!s.soft74490 && !s.soft743ac && !s.soft744c0 && !s.soft743d0 && !s.soft743d4);
    assert(s.provider_calls==9 && s.ab_failures==1 && !s.ab_register_writes && !s.feature_callbacks);
    assert(s.events==4 && s.hardware_counter==8 && s.hardware_epoch==8 && s.source5_queued==4 && s.source5_consumed==4);
    assert(s.aip_dispatches==4 && s.first_snapshot_count==9 && s.first_checked==2 && s.first_cursor==6 && s.uninspected==7);
    assert(s.first_task_status==FULL_ADF_AIP_TASK_ERROR && !s.last_task_status && s.ring_read==9 && s.ring_write==9 && !s.last_snapshot_count);
    assert(s.config03==1 && s.config02==1 && s.config_writes==222 && s.config_readbacks==222 && s.config_public_reads==131);
    assert(s.config_write_hash==0x5426b1385bec3f14ULL);
    assert(source5_new==4 && config03==1 && config02==1 && metadata==1 && hotshoe==1 && glee==1 && control102==1);
    assert(proc_snapshot().input_handoff==1 && full_adf_proc_test_reset()==-1021);
}
int main(int argc,char **argv) {
    assert(argc==4);assert(!setvbuf(stdout,0,_IONBF,0));
    const char *name=argv[1];host_pid=getpid();
    assert(!full_adf_proc_owner_init() && !full_adf_set_input_owner_init());
    assert(!full_adf_proc_test_reset());full_adf_proc_test_seed_path(argv[2]);full_adf_set_input_test_seed_path(argv[3]);
    if(!strcmp(name,"dynamic-caller"))caller=0x8fedcba9u;
    init_message(&old_request,PROC_REQUEST,caller);init_message(&request,INPUT_REQUEST,caller);init_message(&second,SECOND_REQUEST,caller+91);
    if(!strncmp(name,"fork-",5)) {fork_case(!strcmp(name,"fork-locked"));goto passed;}
    if(!strcmp(name,"disabled") || !strcmp(name,"unrelated") || !strcmp(name,"invalid-envelope") ||
       !strcmp(name,"invalid-caller") || !strcmp(name,"missing-transport") || !strcmp(name,"missing-guard")) {invalid_cases(name);goto passed;}
    if(strcmp(name,"no-prior"))prior(strcmp(name,"no-ap-free")!=0);else phase=1;
    if(!strcmp(name,"reservation-refused"))reserve_error=-39;
    if(!strcmp(name,"event0"))full_adf_set_input_test_event_limit(0);
    if(!strcmp(name,"event2"))full_adf_set_input_test_event_limit(2);
    if(!strcmp(name,"alloc-rc"))allocate_error=-41;
    if(!strcmp(name,"alloc-rc-pointer")) {allocate_error=-41;error_pointer=1;}
    if(!strcmp(name,"alloc-null"))null_reply=1;
    if(!strcmp(name,"alloc-size"))reply_bytes=13;
    if(!strcmp(name,"alloc-original"))original_reply=1;
    if(!strcmp(name,"set-source"))source_error=1;
    if(!strcmp(name,"send-fail"))send_error=-43;
    if(!strcmp(name,"cleanup-fail")) {send_error=-43;cleanup_error=-44;}
    if(!strcmp(name,"request-free-fail"))request_error=-45;
    if(!strcmp(name,"recursive"))reenter=1;
    if(!strcmp(name,"kiki-alloc-rc"))kiki_allocate_error=-51;
    if(!strcmp(name,"kiki-alloc-rc-pointer")) {kiki_allocate_error=-51;kiki_pointer=1;}
    if(!strcmp(name,"kiki-alloc-null"))kiki_null=1;
    if(!strcmp(name,"kiki-alloc-size"))kiki_bytes=21;
    if(!strcmp(name,"kiki-alloc-original"))kiki_alias=1;
    if(!strcmp(name,"kiki-send-fail"))kiki_send_error=-52;
    if(!strcmp(name,"kiki-cleanup-fail")) {kiki_send_error=-52;kiki_cleanup_error=-53;}
    assert(!dispatch_with(&io,&guard));struct full_adf_set_input_snapshot s=wait_finish();
    assert(s.requests==1 && s.generation==2 && s.reply_owner==caller && !s.ap_consumed);
    assert(!memcmp(request.body,input_request,14) && !memcmp(old_request.body,proc_request,12));
    unsigned int prior_runs=strcmp(name,"no-prior")!=0;
    assert(reserves==prior_runs+1 && guard_releases==prior_runs+(reserve_error?0u:1u));
    unsigned int reply_cleanup=!strcmp(name,"alloc-rc-pointer") || !strcmp(name,"alloc-size") ||
        !strcmp(name,"set-source") || !strcmp(name,"send-fail");
    assert(!s.retained_reply && !s.reply_freed && frees[INPUT_REPLY]==reply_cleanup);
    if(reply_cleanup)assert(s.cleanup_freed==1 && !s.retained_cleanup && !s.queued && !s.ap_consumed);
    if(s.events==4 && s.aip_dispatches==4)applied_backend(s);
    if(!strcmp(name,"no-prior") || !strcmp(name,"no-ap-free") || reserve_error ||
       !strcmp(name,"seed-missing") || !strcmp(name,"seed-bad") || !strncmp(name,"event",5)) {
        assert(s.faults && !s.applications && !s.queued && !allocations[1] && !allocations[2] && pending_logs==1);
        assert(!s.clean_completion && s.retained_request==request.body && !s.request_freed && !s.live_reply);
        if(!strcmp(name,"no-prior") || !strcmp(name,"no-ap-free"))assert(!s.dependency_claimed && !s.events);
        if(!strncmp(name,"event",5)) {
            unsigned int count=!strcmp(name,"event0")?0u:2u;
            assert(s.events==count && new_events==count && s.source5_queued==count && s.source5_consumed==count);
            assert(s.config_commits==1 && s.inner_queued==1 && !s.inner_consumed);
            if(count)assert(s.provider_calls==9 && s.first_task_status==FULL_ADF_AIP_TASK_ERROR && s.uninspected==7);
        }
    } else if(allocate_error || null_reply || reply_bytes!=12 || original_reply || source_error || send_error ||
              kiki_null || kiki_bytes!=20 || kiki_alias || kiki_cleanup_error) {
        applied_backend(s);assert(s.faults && !s.clean_completion && !s.queued && !s.live_reply && !s.request_freed);
        assert(s.retained_request==request.body && pending_logs==1 && !s.ap_consumed);
        if(kiki_null || kiki_bytes!=20 || kiki_alias || kiki_cleanup_error)assert(!s.applications && !allocations[1] && !s.inner_consumed);
        else assert(s.applications==1 && s.inner_consumed==1 && s.allocate_rc==allocate_error && s.send_rc==send_error);
        if(original_reply || kiki_alias)assert(!free_attempts[INPUT_REQUEST] && !s.cleanup_freed);
        if(cleanup_error)assert(s.retained_cleanup==reply->body && s.cleanup_owner==caller && s.cleanup_free_rc==-44);
        if(kiki_cleanup_error)assert(s.retained_cleanup==kikilog->body && s.cleanup_owner==FULL_ADF_SET_INPUT_KIKILOG && s.cleanup_free_rc==-53);
    } else {
        applied_backend(s);assert(s.applications==1 && s.inner_consumed==1 && !s.inner_status && s.outer_status==0x580000);
        assert(s.queued==1 && sends[1]==1 && s.live_reply==sent_reply && reply && !memcmp(reply->body,input_reply,12));
        assert(applied_order<queued_order && queued_order<guard_release_order);
        assert(s.kikilog_attempted==1 && s.kikilog_allocate_rc==kiki_allocate_error && s.kikilog_send_rc==kiki_send_error);
        if(kiki_allocate_error || kiki_send_error)assert(!s.kikilog_queued && !kernel_frees);
        else assert(s.kikilog_queued==1 && kernel_frees==1 && s.kikilog_allocator_source==ALLOCATOR_SOURCE && kikilog_order<relay_order);
        if(request_error) {
            assert(s.faults && !s.clean_completion && s.retained_request==request.body && s.request_free_rc==-45);
            assert(free_attempts[INPUT_REQUEST]==1 && !frees[INPUT_REQUEST]);
            request_error=0;reject_owner(FULL_ADF_SET_INPUT_INPUT,request.body);assert(!free_owned(FULL_ADF_SET_INPUT_INPUT,request.body));
        } else assert(!s.faults && s.clean_completion && s.request_freed==1 && queued_order<request_free_order && request_free_order<guard_release_order);
        if(reenter)assert(reentrant_checks==2 && !second.released);
        if(!strcmp(name,"wrong-owner"))reject_owner(caller,sent_reply);
        if(!strcmp(name,"reply-free-fail")) {
            reply_error=-46;assert(free_owned(caller,sent_reply)==-46);s=snapshot();
            assert(!s.ap_consumed && s.live_reply==sent_reply && s.retained_reply==sent_reply && s.reply_free_rc==-46);reply_error=0;
        }
        assert(!free_owned(caller,sent_reply));s=snapshot();
        assert(s.ap_consumed==1 && s.reply_freed==1 && !s.live_reply && !s.retained_reply && frees[INPUT_REPLY]==1 && reply_free_logs==1);
        unsigned int before=total_attempts();int rc=77;
        assert(!full_adf_set_input_release_reply(caller,sent_reply,release,record,&rc) && rc==77 && total_attempts()==before);
    }
    recover();
    {int rc=77;assert(full_adf_set_input_dispatch(FULL_ADF_SET_INPUT_INPUT,second.body,&io,&guard,1,&rc)==1 && rc==-1021);}
passed:
    printf("ADF_SET_INPUT_HOST_TEST_PASS: %s; host Linux timer/transport only, no original AP, VM, PCM or capture claim\n",name);
    return 0;
}
