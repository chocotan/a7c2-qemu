/* SPDX-License-Identifier: MIT */
#include "vef-path-device.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define CALLER 0x81cf61c9u
struct message { unsigned int size,source,owner,original;unsigned char body[]; };
static struct message *messages[64],*request,*second;
static pthread_mutex_t resource_mutex=PTHREAD_MUTEX_INITIALIZER;
static unsigned int reserve_calls,reserved,release_calls,held,pool_live,pin_work;
static unsigned int allocate_calls,sent,request_frees,reply_frees,applied_events,queued_events,ap_consumed;
static unsigned int size_calls,source_calls;
static unsigned int recursive,concurrent,nested_rejected,expected_caller;
static int reserve_error,alloc_error,error_pointer,null_reply,duplicate,reply_size;
static int send_error,request_error,reply_error,mutate_request,mutate_resources,source_error,corrupt_reply;
static void *last_reply;
static char events[256],last_fault[1400],last_pending[1400];
static unsigned int event_count;
static struct full_vef_path_snapshot snapshot(void) {
    struct full_vef_path_snapshot s;full_vef_path_snapshot(&s);return s;
}
static void status22(unsigned int value,unsigned int generation,unsigned int writes) {
    struct full_vef_path_snapshot s=snapshot();
    assert(s.runtime_status22_known==1 && s.runtime_status22==value);
    assert(s.runtime_status22_writer_generation==generation && s.runtime_status22_writes==writes);
}
static struct message *meta(void *p) {
    for (unsigned int i=0;i<64;i++) if (messages[i] && messages[i]->body==p) return messages[i];
    assert(!"callback received unknown/freed pointer");return 0;
}
static struct message *new_message(unsigned int size,unsigned int owner,unsigned int original) {
    for (unsigned int i=0;i<64;i++) if (!messages[i]) {
        struct message *m=calloc(1,sizeof(*m)+size);assert(m);
        m->size=size;m->owner=owner;m->original=original;messages[i]=m;return m;
    }
    assert(!"test allocation table full");return 0;
}
static void destroy(struct message *m) {
    for (unsigned int i=0;i<64;i++) if (messages[i]==m) { messages[i]=0;free(m);return; }
    assert(!"double free");
}
static void fixture_cleanup(void) {
    for (unsigned int i=0;i<64;i++) if (messages[i]) destroy(messages[i]);
}
static struct message *make_request(unsigned int caller) {
    static const unsigned char raw[10]={0x0d,0x20,0x49,1,10,0,1,0x80,1,0};
    struct message *m=new_message(10,FULL_VEF_PATH_INPUT,1);m->source=caller;memcpy(m->body,raw,10);return m;
}
static int reserve(void) {
    reserve_calls++;assert(!pthread_mutex_lock(&resource_mutex));
    if (reserve_error || pool_live || pin_work) {
        assert(!pthread_mutex_unlock(&resource_mutex));return reserve_error?reserve_error:-91;
    }
    assert(!held);held=1;reserved++;return 0;
}
static void release_guard(void) {
    assert(held);held=0;release_calls++;assert(!pthread_mutex_unlock(&resource_mutex));
}
static const struct full_vef_path_guard guard={reserve,release_guard};
static int allocate(unsigned int,void **,unsigned int,unsigned int);
static int release(unsigned int owner,void *p) {
    struct message *m=meta(p);assert(owner==m->owner);
    if (m->original) { request_frees++;if (request_error) return request_error; }
    else { reply_frees++;if (reply_error) return reply_error; }
    destroy(m);return 0;
}
static unsigned int size(void *p) { size_calls++;return meta(p)->size; }
static unsigned int source(void *p) { source_calls++;return meta(p)->source; }
static void set_source(void *p,unsigned int value) {
    assert(held);if (!source_error) meta(p)->source=value;
    if (corrupt_reply) ((unsigned char *)p)[8]=1;
}
static int send(unsigned int owner,void *p) {
    static const unsigned char expected[12]={0x0d,0x20,0x49,0x11,12,0,1,0x80,0,0,0x5a,0};
    assert(held && owner==expected_caller && source(p)==FULL_VEF_PATH_INPUT && size(p)==12);
    assert(!memcmp(p,expected,12) && applied_events==sent+1);
    last_reply=p;sent++;return send_error;
}
static void record(const char *tag,const char *text) {
    assert(strstr(text,"scope=virtualNoMemOnly") && strstr(text,"original_cp_executed=0"));
    assert(strstr(text,"hardware_verified=0") && strstr(text,"frames_verified=0"));
    assert(strstr(text,"capture_verified=0") && strstr(text,"global_dmm_idle_claim=0"));
    char code='U';
    if (!strcmp(tag,"FULL_VEF_PATH_REQUEST ")) code='R';
    if (!strcmp(tag,"FULL_VEF_PATH_PENDING ")) {
        assert(!held && strstr(text,"request_accepted=1") && strstr(text,"reservation_rc="));
        assert(strstr(text,"reply_queued=0 normal_completion=0 ap_consumed=0 faulted_pending=1"));
        snprintf(last_pending,sizeof last_pending,"%s",text);code='P';
    }
    if (!strcmp(tag,"FULL_VEF_PATH_APPLIED ")) {
        assert(held && strstr(text,"generation=") && strstr(text,"inner_generation="));
        assert(strstr(text,"current_path=1 phase=2 state=2") && strstr(text,"property=2 input_selection=0x38"));
        assert(strstr(text,"stage0_done=1 stage1_done=1") && strstr(text,"cache=ffffffff,ffffffff,ffffffff,ffffffff"));
        assert(strstr(text,"extra=0 context=0 work=0") && strstr(text,"outer_status=0x5a0000"));
        assert(strstr(text,"inner_completion=022001100c00010000000000"));
        char expected[80];unsigned int generation=applied_events+1;
        snprintf(expected,sizeof expected,"inner_request=02200100140001000100%02x%02x0000000000000000",
            generation&0xffu,(generation>>8)&0xffu);
        assert(strstr(text,expected));
        snprintf(expected,sizeof expected,"runtime_status22_writer_generation=%u runtime_status22_writes=%u",generation,generation);
        assert(strstr(text,"runtime_status22=1 runtime_status22_known=1") && strstr(text,expected));
        applied_events++;code='A';
    }
    if (!strcmp(tag,"FULL_VEF_PATH_QUEUED ")) { assert(held);queued_events++;code='Q'; }
    if (!strcmp(tag,"FULL_VEF_PATH_COMMIT ")) { assert(held && strstr(text,"ap_consumed=0"));code='C'; }
    if (!strcmp(tag,"FULL_VEF_PATH_REPLY_FREE ")) {
        assert(strstr(text,"ap_consumed=1") && strstr(text,"kind=queued-reply"));ap_consumed++;code='F';
    }
    if (!strcmp(tag,"FULL_VEF_PATH_CLEANUP_REPLY_FREE ") || !strcmp(tag,"FULL_VEF_PATH_REQUEST_FREE "))
        assert(strstr(text,"ap_consumed=0"));
    if (!strcmp(tag,"FULL_VEF_PATH_FAULT ")) { snprintf(last_fault,sizeof last_fault,"%s",text);code='E'; }
    assert(event_count+1<sizeof events);events[event_count++]=code;events[event_count]=0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static void *nested_dispatch(void *unused) {
    (void)unused;int rc=77;
    assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,second->body,&io,&guard,1,&rc)==1 && rc==-1021);
    nested_rejected++;return 0;
}
static int allocate(unsigned int owner,void **out,unsigned int bytes,unsigned int count) {
    assert(owner==expected_caller && bytes==12 && count==1 && held);allocate_calls++;
    struct full_vef_path_snapshot s=snapshot();assert(s.busy && s.guard_held && !s.live_replies);
    status22(s.applications?1:0,(unsigned int)s.applications,(unsigned int)s.applications);
    assert(pthread_mutex_trylock(&resource_mutex)==EBUSY);
    if (recursive || concurrent) {
        second=make_request(CALLER+9);
        if (recursive) nested_dispatch(0);
        else { pthread_t thread;assert(!pthread_create(&thread,0,nested_dispatch,0));assert(!pthread_join(thread,0)); }
    }
    if (mutate_request) { request->body[8]=0;request->source++; }
    if (mutate_resources) {
        const unsigned int handles[4]={FULL_VEF_PATH_EMPTY,0x8000,FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY};
        full_vef_path_test_resources(handles,0,0);
    }
    if (duplicate) { *out=request->body;return alloc_error; }
    if (null_reply || (alloc_error && !error_pointer)) { *out=0;return alloc_error; }
    struct message *m=new_message((unsigned int)reply_size,owner,0);*out=m->body;return alloc_error;
}
static void balanced(void) {
    struct full_vef_path_snapshot s=snapshot();assert(!s.busy && !s.guard_held && !held && reserved==release_calls);
    assert(!pthread_mutex_trylock(&resource_mutex));assert(!pthread_mutex_unlock(&resource_mutex));
}
static void reset(void) {
    balanced();fixture_cleanup();full_vef_path_test_reset();
    reserve_calls=reserved=release_calls=held=pool_live=pin_work=0;
    allocate_calls=sent=request_frees=reply_frees=applied_events=queued_events=ap_consumed=0;
    size_calls=source_calls=0;
    recursive=concurrent=nested_rejected=0;expected_caller=CALLER;
    reserve_error=alloc_error=error_pointer=null_reply=duplicate=send_error=request_error=reply_error=0;
    mutate_request=mutate_resources=source_error=corrupt_reply=0;reply_size=12;
    last_reply=0;event_count=0;events[0]=last_fault[0]=last_pending[0]=0;second=0;request=make_request(CALLER);
}
static int dispatch_with(const struct full_imaging_io *transport,const struct full_vef_path_guard *g) {
    int rc=99;expected_caller=request->source;
    assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,request->body,transport,g,1,&rc)==1);balanced();return rc;
}
static int dispatch(void) { return dispatch_with(&io,&guard); }
static int free_owned(unsigned int owner,void *p) {
    int rc=99;assert(full_vef_path_release_reply(owner,p,release,record,&rc)==1);balanced();return rc;
}
static void free_last(void) { assert(!free_owned(expected_caller,last_reply)); }
static void refuse_new(void) {
    unsigned int before=allocate_calls;request=make_request(CALLER+3);
    assert(dispatch()==-1021 && allocate_calls==before);
}
static int lock_ready[2],lock_finish[2];
static void *hold_private_lock(void *unused) {
    (void)unused;char byte=1;
    full_vef_path_test_hold_lock();
    assert(write(lock_ready[1],&byte,1)==1 && read(lock_finish[0],&byte,1)==1);
    full_vef_path_test_drop_lock();return 0;
}
static void no_completion(void) {
    struct full_vef_path_snapshot s=snapshot();
    assert(!sent && !queued_events && !request_frees && !ap_consumed && !s.reply_freed);
    status22(s.applications?1:0,(unsigned int)s.applications,(unsigned int)s.applications);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"fork-first-call")) {
        /* Reset/snapshot before this fork would hide the constructor-only bug. */
        assert(!full_vef_path_owner_init());request=make_request(CALLER);
        pid_t child=fork();assert(child>=0);
        if (!child) {
            alarm(3);int rc=77;
            assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,request->body,&io,&guard,1,&rc)==1 && rc==-1021);
            assert(!size_calls && !source_calls && !event_count && !reserve_calls && !allocate_calls);
            assert(full_vef_path_release_reply(FULL_VEF_PATH_INPUT,request->body,release,record,&rc)==1 && rc==-1021);
            assert(!request_frees && !reply_frees && full_vef_path_owner_init()==-1021);
            _exit(0);
        }
        int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
        fixture_cleanup();puts("VEF_PATH_TEST_PASS: host-only constructor PID binding before any child callbacks");return 0;
    }
    reset();
    if (!strcmp(argv[1],"normal")) {
        struct full_vef_path_snapshot s=snapshot();
        assert(s.current_path==0x14 && s.phase==1 && s.state==2 && !s.generation && !s.configured);
        status22(0,0,0);
        assert(!s.extra_resource && !s.pending_context);
        for (unsigned int i=0;i<4;i++) assert(s.cached_handles[i]==FULL_VEF_PATH_EMPTY);
        for (unsigned int i=0;i<3;i++) {
            if (i) request=make_request(CALLER+0x1000*i);
            assert(dispatch()==0);s=snapshot();
            const unsigned char inner[20]={2,0x20,1,0,20,0,1,0,1,0,(unsigned char)(i+1),0,0,0,0,0,0,0,0,0};
            const unsigned char completion[12]={2,0x20,1,0x10,12,0,1,0,0,0,0,0};
            assert(!memcmp(s.inner_request,inner,20) && !memcmp(s.inner_completion,completion,12));
            assert(s.current_path==1 && s.phase==2 && s.state==2 && s.generation==i+1 && s.inner_generation==i+1);
            status22(1,i+1,i+1);assert(s.runtime_status22!=s.state);
            assert(s.selected_object==FULL_VEF_PATH_NOMEM && s.property==2 && s.input_selection==0x38);
            assert(s.stage0_done && s.stage1_done && !s.work_pending && s.execution_status==0 && s.outer_status==0x005a0000);
            assert(s.applications==i+1 && s.queued==i+1 && s.request_freed==i+1 && s.reply_freed==i);
            assert(s.live_replies==1 && s.live_reply==last_reply && s.reply_owner==expected_caller && s.clean_completion);
            free_last();assert(snapshot().reply_freed==i+1 && !snapshot().live_replies);
        }
        assert(!strcmp(events,"RAQCFRAQCFRAQCF") && reserve_calls==3 && ap_consumed==3);
    } else if (!strcmp(argv[1],"status22-copy-fork")) {
        status22(0,0,0);assert(dispatch()==0);status22(1,1,1);
        struct full_vef_path_snapshot before=snapshot(),copy=before;
        copy.runtime_status22=15;copy.runtime_status22_known=0;
        copy.runtime_status22_writer_generation=99;copy.runtime_status22_writes=99;
        status22(1,1,1);assert(copy.runtime_status22!=snapshot().runtime_status22);
        request=make_request(CALLER+1);
        unsigned int callbacks=allocate_calls+reserve_calls+event_count+size_calls+source_calls;
        pid_t child=fork();assert(child>=0);
        if (!child) {
            alarm(3);struct full_vef_path_snapshot inherited=snapshot();int rc=77;
            assert(inherited.faults==1 && inherited.owner_pid==before.owner_pid);
            assert(!inherited.runtime_status22_known && !inherited.runtime_status22);
            assert(!inherited.runtime_status22_writer_generation && !inherited.runtime_status22_writes);
            assert(full_vef_path_owner_init()==-1021);
            assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,request->body,&io,&guard,1,&rc)==1 && rc==-1021);
            assert(full_vef_path_release_reply(CALLER,last_reply,release,record,&rc)==1 && rc==-1021);
            assert(callbacks==allocate_calls+reserve_calls+event_count+size_calls+source_calls);
            _exit(0);
        }
        int child_status;assert(waitpid(child,&child_status,0)==child);
        assert(WIFEXITED(child_status) && WEXITSTATUS(child_status)==0);
        struct full_vef_path_snapshot after=snapshot();assert(!memcmp(&before,&after,sizeof before));
        free_last();status22(1,1,1);
    } else if (!strcmp(argv[1],"status22-failed-next")) {
        assert(dispatch()==0);free_last();status22(1,1,1);
        request=make_request(CALLER+1);alloc_error=-55;assert(dispatch()==-55);
        struct full_vef_path_snapshot s=snapshot();
        assert(s.faults && s.applications==1 && s.generation==1 && s.current_path==1 && s.state==2);
        status22(1,1,1);refuse_new();status22(1,1,1);
    } else if (!strcmp(argv[1],"disabled")) {
        for (int enabled=0;enabled<3;enabled+=2) {
            int rc=77;assert(!full_vef_path_dispatch(FULL_VEF_PATH_INPUT,request->body,&io,&guard,enabled,&rc) && rc==77);
        }
        assert(!reserve_calls && !allocate_calls);no_completion();
    } else if (!strcmp(argv[1],"unrelated")) {
        for (unsigned int i=0;i<5;i++) {
            reset();unsigned int dest=FULL_VEF_PATH_INPUT;
            if (i==0) dest++;
            if (i==1) request->body[0]=0;
            if (i==2) request->body[2]=0;
            if (i==3) request->size=3;
            if (i==4) request->size=0;
            int rc=77;assert(!full_vef_path_dispatch(dest,request->body,&io,&guard,1,&rc) && rc==77);
            assert(!reserve_calls && !allocate_calls);no_completion();
        }
    } else if (!strcmp(argv[1],"invalid")) {
        const unsigned int paths[]={0,2,15,18,19,0x101,0xffff};
        for (unsigned int i=0;i<sizeof paths/sizeof paths[0];i++) {
            reset();request->body[8]=(unsigned char)paths[i];request->body[9]=(unsigned char)(paths[i]>>8);
            assert(dispatch()==-1021 && !reserve_calls && !allocate_calls);no_completion();
        }
        for (unsigned int i=0;i<8;i++) {
            reset();
            if (i==0) request->size=11;
            if (i==1) request->size=8;
            if (i==2) request->body[4]=12;
            if (i==3) request->body[5]=1;
            if (i==4) request->body[6]=0;
            if (i==5) request->body[7]=0;
            if (i==6) request->source=0x80000000;
            if (i==7) request->source=FULL_VEF_PATH_INPUT;
            assert(dispatch()==-1021 && !reserve_calls && !allocate_calls);no_completion();
        }
    } else if (!strcmp(argv[1],"missing-transport")) {
        for (unsigned int i=0;i<5;i++) {
            reset();struct full_imaging_io incomplete=io;
            if (i==0) incomplete.allocate=0;
            if (i==1) incomplete.release=0;
            if (i==2) incomplete.set_source=0;
            if (i==3) incomplete.send=0;
            if (i==4) incomplete.source=0;
            assert(dispatch_with(&incomplete,&guard)==-1021 && !reserve_calls);no_completion();
        }
    } else if (!strcmp(argv[1],"missing-guard")) {
        for (unsigned int i=0;i<3;i++) {
            reset();struct full_vef_path_guard incomplete=guard;
            if (i==1) incomplete.reserve=0;
            if (i==2) incomplete.release=0;
            assert(dispatch_with(&io,i?&incomplete:0)==-1021 && !reserve_calls && !allocate_calls);no_completion();
        }
    } else if (!strcmp(argv[1],"reservation-refused")) {
        for (unsigned int i=0;i<3;i++) {
            reset();reserve_error=i==0?-44:0;pool_live=i==1;pin_work=i==2;
            void *original=request->body;unsigned char before[10];memcpy(before,original,sizeof before);
            assert(dispatch()==0 && reserve_calls==1 && !release_calls && !allocate_calls);
            struct full_vef_path_snapshot s=snapshot();
            assert(s.retained_request==original && s.retained_request_owner==FULL_VEF_PATH_INPUT && s.faults);
            assert(!s.generation && !s.applications && !s.queued && !s.live_replies && !s.clean_completion);
            assert(s.current_path==0x14 && s.phase==1 && !s.stage0_done && !s.stage1_done);
            assert(!memcmp(before,original,sizeof before) && strstr(last_pending,"faulted_pending=1"));
            no_completion();refuse_new();assert(snapshot().retained_request==original && !allocate_calls);
            assert(free_owned(CALLER,original)==-1021 && !request_frees);
            request_error=-77;assert(free_owned(FULL_VEF_PATH_INPUT,original)==-77 && snapshot().retained_request==original);
            request_error=0;assert(!free_owned(FULL_VEF_PATH_INPUT,original));s=snapshot();
            assert(!s.retained_request && s.request_freed==1 && !s.reply_freed && !s.queued && s.faults);
            assert(!ap_consumed && !s.clean_completion);refuse_new();
        }
    } else if (!strcmp(argv[1],"owned-nonempty")) {
        for (unsigned int i=0;i<6;i++) {
            reset();unsigned int handles[4]={FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY,FULL_VEF_PATH_EMPTY};
            if (i<4) handles[i]=0x8000+i;
            full_vef_path_test_resources(handles,i==4,i==5);
            assert(dispatch()==-1021 && reserved==1 && !allocate_calls && !snapshot().generation);no_completion();
            assert(!memcmp(snapshot().cached_handles,handles,sizeof handles));
        }
    } else if (!strcmp(argv[1],"stale-generation")) {
        full_vef_path_test_generation(0,1);assert(dispatch()==-1021);no_completion();
        struct full_vef_path_snapshot s=snapshot();
        assert(s.generation==1 && s.inner_generation==0 && s.phase==0 && s.work_pending && s.current_path==0x14);
        assert(!s.stage0_done && !s.stage1_done && !s.applications && s.faults && reply_frees==1);refuse_new();
    } else if (!strcmp(argv[1],"generation-exhausted")) {
        full_vef_path_test_generation(0xffff,0);assert(dispatch()==-1021 && !allocate_calls && snapshot().faults);no_completion();
    } else if (!strcmp(argv[1],"alloc-fail")) {
        for (unsigned int i=0;i<2;i++) {
            reset();alloc_error=-55;error_pointer=(int)i;assert(dispatch()==-55);no_completion();
            assert(snapshot().allocate_rc==-55 && snapshot().faults && !snapshot().generation && reply_frees==i);
            assert(strstr(last_fault,"allocate_rc=-55"));
        }
    } else if (!strcmp(argv[1],"alloc-null")) {
        null_reply=1;assert(dispatch()==-1021 && snapshot().faults && !snapshot().applications);no_completion();
    } else if (!strcmp(argv[1],"duplicate")) {
        for (unsigned int i=0;i<2;i++) {
            reset();duplicate=1;alloc_error=i?-55:0;
            assert(dispatch()==-1021 && snapshot().faults && !reply_frees && !snapshot().retained_cleanup_reply);no_completion();
        }
    } else if (!strcmp(argv[1],"wrong-size")) {
        const int sizes[]={0,8,13};
        for (unsigned int i=0;i<3;i++) {
            reset();reply_size=sizes[i];assert(dispatch()==-1021 && reply_frees==1 && !snapshot().generation);no_completion();
        }
    } else if (!strcmp(argv[1],"immutable-request")) {
        mutate_request=1;assert(dispatch()==0 && snapshot().requested_path==1 && snapshot().reply_owner==CALLER);free_last();
    } else if (!strcmp(argv[1],"resource-race")) {
        mutate_resources=1;assert(dispatch()==-1021 && reply_frees==1 && !snapshot().generation);no_completion();
        assert(snapshot().cached_handles[1]==0x8000 && snapshot().faults);
    } else if (!strcmp(argv[1],"reply-readback")) {
        for (unsigned int i=0;i<2;i++) {
            reset();source_error=i==0;corrupt_reply=i==1;
            assert(dispatch()==-1021 && snapshot().applications==1 && snapshot().current_path==1 && reply_frees==1);no_completion();
        }
    } else if (!strcmp(argv[1],"send-fail")) {
        send_error=-66;assert(dispatch()==-66 && !request_frees && reply_frees==1);
        struct full_vef_path_snapshot s=snapshot();
        assert(s.current_path==1 && s.phase==2 && s.applications==1 && s.send_rc==-66 && s.faults && !s.queued && !s.live_replies);
        assert(!s.clean_completion && !s.reply_freed && !ap_consumed && strstr(last_fault,"send_rc=-66"));
        status22(1,1,1);refuse_new();status22(1,1,1);
    } else if (!strcmp(argv[1],"request-free-fail")) {
        void *original=request->body;request_error=-77;assert(dispatch()==0);
        struct full_vef_path_snapshot s=snapshot();
        assert(s.retained_request==original && s.retained_request_owner==FULL_VEF_PATH_INPUT && s.faults && !s.clean_completion);
        assert(!s.request_freed && s.request_free_rc==-77 && s.queued==1 && s.live_replies==1);
        free_last();unsigned int tries=request_frees;
        assert(free_owned(CALLER,original)==-1021 && request_frees==tries && snapshot().retained_request==original);
        request_error=0;assert(!free_owned(FULL_VEF_PATH_INPUT,original));
        assert(!snapshot().retained_request && !snapshot().retained_request_owner && snapshot().request_freed==1);
        assert(snapshot().faults && !snapshot().clean_completion);refuse_new();
    } else if (!strcmp(argv[1],"reply-free-fail")) {
        assert(dispatch()==0);reply_error=-88;
        assert(free_owned(CALLER,last_reply)==-88 && free_owned(CALLER,last_reply)==-88);
        struct full_vef_path_snapshot s=snapshot();
        assert(s.live_reply==last_reply && s.retained_reply==last_reply && s.reply_owner==CALLER && s.live_replies==1);
        assert(!s.reply_freed && !ap_consumed && s.reply_free_rc==-88 && !s.clean_completion);
        reply_error=0;free_last();assert(snapshot().faults && !snapshot().retained_reply && !snapshot().clean_completion);
        assert(snapshot().reply_freed==1 && ap_consumed==1);refuse_new();
    } else if (!strcmp(argv[1],"wrong-owner")) {
        assert(dispatch()==0);assert(free_owned(CALLER+1,last_reply)==-1021 && !reply_frees && !ap_consumed);
        assert(snapshot().reply_owner==CALLER && snapshot().retained_reply==last_reply);free_last();assert(snapshot().faults);
    } else if (!strcmp(argv[1],"cleanup-retention")) {
        for (unsigned int i=0;i<3;i++) {
            reset();reply_error=-88;
            if (i==0) send_error=-66;
            if (i==1) reply_size=8;
            if (i==2) { alloc_error=-55;error_pointer=1; }
            assert(dispatch()==(i==0?-66:i==1?-1021:-55));
            struct full_vef_path_snapshot s=snapshot();void *retained=s.retained_cleanup_reply;
            assert(retained && s.retained_cleanup_owner==CALLER && s.cleanup_free_rc==-88 && s.faults && !s.live_replies);
            assert(strstr(last_fault,"cleanup_free_rc=-88") && strstr(last_fault,"retained_cleanup=1"));
            assert(!s.reply_freed && !s.cleanup_freed && !ap_consumed && !request_frees);
            assert(free_owned(CALLER,retained)==-88);unsigned int tries=reply_frees;
            assert(free_owned(CALLER+1,retained)==-1021 && reply_frees==tries);
            refuse_new();assert(snapshot().retained_cleanup_reply==retained && snapshot().retained_cleanup_owner==CALLER);
            reply_error=0;assert(!free_owned(CALLER,retained));s=snapshot();
            assert(!s.retained_cleanup_reply && !s.retained_cleanup_owner && s.cleanup_freed==1 && !s.reply_freed);
            assert(s.faults && !s.clean_completion && !ap_consumed);
            int rc=77;assert(!full_vef_path_release_reply(CALLER,retained,release,record,&rc) && rc==77);
        }
    } else if (!strcmp(argv[1],"busy-recursive") || !strcmp(argv[1],"busy-concurrent")) {
        recursive=!strcmp(argv[1],"busy-recursive");concurrent=!recursive;
        assert(dispatch()==0 && nested_rejected==1 && reserve_calls==1 && sent==1 && request_frees==1);free_last();
    } else if (!strcmp(argv[1],"one-outstanding")) {
        assert(dispatch()==0);void *reply=last_reply;refuse_new();
        assert(snapshot().live_reply==reply && snapshot().reply_owner==CALLER && !snapshot().faults);
        assert(!free_owned(CALLER,reply));assert(dispatch()==0 && snapshot().generation==2);free_last();
    } else if (!strcmp(argv[1],"fork-inherited")) {
        assert(!pipe(lock_ready) && !pipe(lock_finish));
        pthread_t thread;assert(!pthread_create(&thread,0,hold_private_lock,0));
        char byte;assert(read(lock_ready[0],&byte,1)==1);
        pid_t child=fork();assert(child>=0);
        if (!child) {
            alarm(3);int rc=77;
            assert(full_vef_path_dispatch(FULL_VEF_PATH_INPUT,request->body,&io,&guard,1,&rc)==1 && rc==-1021);
            assert(!reserve_calls && !allocate_calls && !event_count);
            assert(full_vef_path_release_reply(FULL_VEF_PATH_INPUT,request->body,release,record,&rc)==1 && rc==-1021);
            struct full_vef_path_snapshot s=snapshot();assert(s.faults && s.owner_pid!=(int)getpid() && !s.current_path);
            assert(!s.runtime_status22_known && !s.runtime_status22_writer_generation && !s.runtime_status22_writes);
            full_vef_path_test_reset();full_vef_path_test_generation(0,0);
            const unsigned int handles[4]={0,0,0,0};full_vef_path_test_resources(handles,0,0);
            full_vef_path_test_hold_lock();full_vef_path_test_drop_lock();
            assert(snapshot().owner_pid==s.owner_pid && snapshot().faults);
            _exit(0);
        }
        int status;assert(waitpid(child,&status,0)==child);
        assert(write(lock_finish[1],&byte,1)==1 && !pthread_join(thread,0));
        for (unsigned int i=0;i<2;i++) { assert(!close(lock_ready[i]));assert(!close(lock_finish[i])); }
        assert(WIFEXITED(status) && WEXITSTATUS(status)==0);
        assert(snapshot().owner_pid==(int)getpid() && !snapshot().faults);
        assert(dispatch()==0);free_last();
    } else if (!strcmp(argv[1],"unknown-or-double-free")) {
        int rc=77;assert(!full_vef_path_release_reply(CALLER,request->body,release,record,&rc) && rc==77);
        assert(dispatch()==0);void *reply=last_reply;free_last();unsigned int frees=reply_frees;
        assert(!full_vef_path_release_reply(CALLER,reply,release,record,&rc) && rc==77 && reply_frees==frees);
        assert(snapshot().reply_freed==1 && !snapshot().faults);
    } else return 2;
    balanced();fixture_cleanup();full_vef_path_test_reset();
    puts("VEF_PATH_TEST_PASS: UNWIRED virtual NoMem control only; no CP/hardware/frames/capture verification");return 0;
}
