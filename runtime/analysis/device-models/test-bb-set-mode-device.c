/* SPDX-License-Identifier: MIT */
#define FULL_ADF_OUTPUT_TEST_MAIN output_prerequisite_main
#include "test-adf-set-output-device.c"
#include "bb-set-mode-device.h"

struct bb_message {unsigned int bytes,source,owner,released,attempts;unsigned char data[680];};
static struct bb_message bb_req,bb_resp,bb_other;
static unsigned int bb_caller=0x8123abcd,bb_allocs,bb_sends,bb_frees,bb_logs,bb_sequence;
static unsigned int bb_first,bb_outer,bb_second,bb_applied,bb_sent;
static int bb_alloc_error,bb_alloc_null,bb_alias,bb_size=12,bb_send_error,bb_free_error;
static int bb_request_error,bb_source_error,bb_inject_prefix,bb_inline_free,bb_reserve_error;
static unsigned int bb_snapshots;
static int bb_send_thread,bb_thread_error,bb_thread_started,bb_thread_go;
static pthread_t bb_reply_thread;
static pthread_mutex_t bb_thread_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t bb_thread_condition=PTHREAD_COND_INITIALIZER;
static struct full_bb_set_mode_snapshot bb_snap(void){
 struct full_bb_set_mode_snapshot s;full_bb_set_mode_snapshot(&s);bb_snapshots++;return s;
}
static struct bb_message *bb_meta(void *data){
 struct bb_message *m=(void *)((unsigned char *)data - offsetof(struct bb_message,data));
 assert((m==&bb_req || m==&bb_resp || m==&bb_other) && !m->released);return m;
}
static unsigned int bb_bytes(void *data){return bb_meta(data)->bytes;}
static unsigned int bb_source(void *data){return bb_meta(data)->source;}
static int bb_release(unsigned int owner,void *data){
 struct full_bb_set_mode_snapshot s=bb_snap();assert(s.owner_pid==getpid());
 assert(!pthread_mutex_lock(&bb_thread_mutex));
 struct bb_message *m=bb_meta(data);assert(owner==m->owner);bb_frees++;m->attempts++;
 int rc=m==&bb_req?bb_request_error:m==&bb_resp?bb_free_error:0;
 if(!rc)m->released=1;
 assert(!pthread_mutex_unlock(&bb_thread_mutex));return rc;
}
static void bb_record(const char *tag,const char *text){
 struct full_bb_set_mode_snapshot s=bb_snap();assert(s.owner_pid==getpid());
 bb_logs++;bb_sequence++;fprintf(stdout,"%s%s\n",tag,text);
 if(!strcmp(tag,"FULL_BB_MODE_FIRST_COMPLETION ")){assert(!bb_first && !s.outer_popped);bb_first=bb_sequence;}
 if(!strcmp(tag,"FULL_BB_MODE_OUTER_WORK ")){assert(bb_first && !bb_outer && s.outer_inflight && s.inner_accepted);bb_outer=bb_sequence;}
 if(!strcmp(tag,"FULL_BB_MODE_SECOND_COMPLETION ")){assert(bb_outer && !bb_second && s.inner_inflight);bb_second=bb_sequence;}
 if(!strcmp(tag,"FULL_BB_SET_MODE_APPLIED ")){assert(bb_second && s.queue_finished && s.outer_returned && s.inner_returned);bb_applied=bb_sequence;}
}
static int bb_reserve(void){if(bb_reserve_error)return bb_reserve_error;return reserve();}
static void bb_release_guard(void){assert(bb_snap().guard_held);release_guard();}
static const struct full_adf_proc_guard bb_guard={bb_reserve,bb_release_guard};
static int bb_allocate(unsigned int owner,void **data,unsigned int bytes,unsigned int count){
 assert(owner==bb_caller && bytes==12 && count==1);bb_allocs++;
 assert(bb_snap().applications==1 && bb_applied);
 if(bb_alias){*data=bb_req.data;return bb_alloc_error;}
 if(bb_alloc_null || bb_alloc_error){*data=NULL;return bb_alloc_error;}
 memset(&bb_resp,0,sizeof bb_resp);bb_resp.owner=owner;bb_resp.source=ALLOCATOR_SOURCE;
 bb_resp.bytes=(unsigned int)bb_size;*data=bb_resp.data;return 0;
}
static void bb_set(void *data,unsigned int source_id);
static int bb_thread_free(unsigned int owner,void *data){
 assert(!pthread_mutex_lock(&bb_thread_mutex));
 struct bb_message *m=bb_meta(data);assert(m==&bb_resp && owner==m->owner);bb_frees++;m->attempts++;
 bb_thread_started=1;assert(!pthread_cond_signal(&bb_thread_condition));
 while(!bb_thread_go)assert(!pthread_cond_wait(&bb_thread_condition,&bb_thread_mutex));
 if(!bb_thread_error)m->released=1;
 assert(!pthread_mutex_unlock(&bb_thread_mutex));return bb_thread_error?-49:0;
}
static void *bb_thread_release(void *unused){
 (void)unused;int rc=99;
 assert(full_bb_set_mode_release_reply(bb_caller,bb_resp.data,bb_thread_free,0,&rc));
 assert(rc==(bb_thread_error?-49:0));return 0;
}
static int bb_send(unsigned int owner,void *data){
 static const unsigned char answer[12]={0x0d,0x20,0x10,0x11,12,0,1,0x80,0,0,0,0};
 assert(bb_meta(data)==&bb_resp && owner==bb_caller && bb_resp.bytes==12 && bb_resp.source==0x92840747u);
 assert(!memcmp(data,answer,12) && data!=bb_req.data && bb_applied);bb_sends++;bb_sent=++bb_sequence;
 assert(bb_snap().first_internal_completion==1 && bb_snap().second_internal_completion==1);
 if(bb_send_thread){
  assert(!pthread_mutex_lock(&bb_thread_mutex));assert(!pthread_create(&bb_reply_thread,0,bb_thread_release,0));
  while(!bb_thread_started)assert(!pthread_cond_wait(&bb_thread_condition,&bb_thread_mutex));
  assert(!pthread_mutex_unlock(&bb_thread_mutex));
 }
 if(bb_inline_free){int rc=99;assert(full_bb_set_mode_release_reply(owner,data,bb_release,bb_record,&rc)==1 && !rc);}
 return bb_send_error;
}
static const struct full_imaging_io bb_io={bb_allocate,bb_release,bb_set,bb_send,bb_bytes,bb_source,bb_record};
static void bb_set(void *data,unsigned int source_id){
 assert(bb_meta(data)==&bb_resp);bb_resp.source=bb_source_error?123:source_id;
 if(bb_inject_prefix){
  bb_other.bytes=10;bb_other.source=bb_caller;bb_other.owner=0x92840747u;
  const unsigned char prefix[10]={0x0d,0x20,0x3d,1,10,0,1,0x80,0,1};memcpy(bb_other.data,prefix,10);
  assert(full_bb_set_mode_observe_input(0x92840747u,bb_other.data,&bb_io)==-1021);
 }
}
static void bb_init_request(void){
 const unsigned char wire[10]={0x0d,0x20,0x10,1,10,0,1,0x80,0,0};
 memset(&bb_req,0,sizeof bb_req);bb_req.bytes=10;bb_req.owner=0x92840747u;bb_req.source=bb_caller;memcpy(bb_req.data,wire,10);
}
static void bb_prefix(void){
 const unsigned char panel[22]={0x0d,0x20,0x18,1,22,0,1,0x80,3,1,0,0,0,0,0,0,0,0,0,0,1,0};
 memset(&bb_other,0,sizeof bb_other);bb_other.owner=0x92840747u;bb_other.source=bb_caller;
 bb_other.bytes=22;memcpy(bb_other.data,panel,22);
 assert(!full_bb_set_mode_observe_input(0x92840747u,bb_other.data,&bb_io));
 const unsigned char slope[10]={0x0d,0x20,0x3d,1,10,0,1,0x80,0,1};
 bb_other.bytes=10;memcpy(bb_other.data,slope,10);
 assert(!full_bb_set_mode_observe_input(0x92840747u,bb_other.data,&bb_io));
 assert(bb_snap().prefix_messages==2 && !bb_snap().unknown_prefix_messages);
}
#ifndef FULL_BB_TEST_MAIN
#define FULL_BB_TEST_MAIN main
#endif
int FULL_BB_TEST_MAIN(int argc,char **argv){
 assert(argc==3);const char *name=argv[1];host_pid=getpid();alarm(12);
 if(!strcmp(name,"dynamic-caller"))bb_caller=0x8fed0987u;
 if(strcmp(name,"uninitialized"))assert(!full_bb_set_mode_owner_init());
 bb_init_request();
 if(!strcmp(name,"disabled")){int rc=77;assert(!full_bb_set_mode_dispatch(0x92840747u,bb_req.data,&bb_io,&bb_guard,0,&rc) && rc==77);return 0;}
 if(!strcmp(name,"invalid")){
  for(unsigned int n=4;n<10;n++){bb_init_request();bb_req.data[n]^=1;int rc=77;assert(full_bb_set_mode_dispatch(0x92840747u,bb_req.data,&bb_io,&bb_guard,1,&rc) && rc==-1021);}
  assert(!bb_snap().requests && !bb_allocs && !bb_sends);return 0;
 }
 if(!strcmp(name,"fork")){
  pid_t p=fork();assert(p>=0);if(!p){int rc=77;alarm(2);assert(full_bb_set_mode_dispatch(0x92840747u,bb_req.data,&bb_io,&bb_guard,1,&rc) && rc==-1021);assert(bb_snap().faults);_exit(0);}
  int code;assert(waitpid(p,&code,0)==p && WIFEXITED(code) && !WEXITSTATUS(code));return 0;
 }
 if(!strcmp(name,"uninitialized")){int rc=77;assert(full_bb_set_mode_dispatch(0x92840747u,bb_req.data,&bb_io,&bb_guard,1,&rc) && rc==-1021);return 0;}
 bb_prefix();
 if(!strcmp(name,"plane-prefix") || !strcmp(name,"unknown-large-prefix")){
  memset(bb_other.data,0,sizeof bb_other.data);bb_other.bytes=680;
  const unsigned char plane_header[8]={0x0d,0x20,0x47,1,0xa8,2,1,0x80};
  memcpy(bb_other.data,plane_header,8);
  if(!strcmp(name,"unknown-large-prefix"))bb_other.data[2]=0x48;
  assert(!full_bb_set_mode_observe_input(0x92840747u,bb_other.data,&bb_io));
  assert(bb_snap().state_known==(!strcmp(name,"plane-prefix")));
 }
 if(strcmp(name,"no-prior")){
  char *old[]={"test","normal",argv[2],NULL};assert(!output_prerequisite_main(3,old));alarm(12);
 }
 if(!strcmp(name,"unknown-prefix")){
  bb_other.bytes=10;bb_other.data[2]=0x99;bb_other.data[3]=1;
  assert(!full_bb_set_mode_observe_input(0x92840747u,bb_other.data,&bb_io));
 }
 if(!strcmp(name,"reserve-fail"))bb_reserve_error=-31;
 if(!strcmp(name,"alloc-rc"))bb_alloc_error=-41;
 if(!strcmp(name,"alloc-null"))bb_alloc_null=1;
 if(!strcmp(name,"alloc-size"))bb_size=11;
 if(!strcmp(name,"alloc-alias"))bb_alias=1;
 if(!strcmp(name,"set-source"))bb_source_error=1;
 if(!strcmp(name,"prefix-during-source"))bb_inject_prefix=1;
 if(!strcmp(name,"send-fail"))bb_send_error=-43;
 if(!strcmp(name,"in-flight-send-fail") || !strcmp(name,"in-flight-free-fail")){
  bb_send_thread=1;bb_send_error=-43;bb_thread_error=!strcmp(name,"in-flight-free-fail");
 }
 if(!strcmp(name,"request-free-fail"))bb_request_error=-45;
 if(!strcmp(name,"inline-free"))bb_inline_free=1;
 int rc=77;assert(full_bb_set_mode_dispatch(0x92840747u,bb_req.data,&bb_io,&bb_guard,1,&rc)==1);
 struct full_bb_set_mode_snapshot s=bb_snap();
 if(!strcmp(name,"unknown-prefix") || !strcmp(name,"unknown-large-prefix")){assert(rc==-1021 && !s.requests && !bb_allocs && !bb_sends && !s.state_known);return 0;}
 assert(!rc && s.requests==1 && !s.busy && !s.guard_held);
 if(!strcmp(name,"no-prior") || bb_reserve_error){assert(s.faults && s.pending && s.retained_request==bb_req.data && !bb_sends && !s.applications);}
 else {
  assert(s.outer_accepted==1 && s.outer_popped==1 && s.outer_returned==1 && !s.outer_inflight);
  assert(s.inner_accepted==1 && s.inner_popped==1 && s.inner_returned==1 && !s.inner_inflight && s.queue_finished);
  assert(s.first_internal_completion==1 && s.second_internal_completion==1 && s.state_word==1 && s.target==3 && !s.operation_mode);
  assert(s.config_snapshot_copies==1 && s.config_snapshot_known_bytes==4 && s.config_snapshot_unknown_bytes==1756);
  assert(s.config_live_fnv==s.config_snapshot_fnv && s.config_known_fnv==s.config_snapshot_known_fnv);
  assert(s.semaphore_acquires==1 && s.semaphore_releases==1 && !s.semaphore_busy);
  assert(bb_first<bb_outer && bb_outer<bb_second && bb_second<bb_applied);
  if(bb_send_thread){
   assert(s.faults && s.pending && !s.clean_completion && !s.queued && !s.ap_consumed && !s.reply_freed && !s.request_freed);
   assert(s.send_rc==-43 && bb_allocs==1 && bb_sends==1 && bb_frees==1 && !held && !s.guard_held);
   assert(s.live_reply==bb_resp.data && s.retained_request==bb_req.data && !s.retained_reply && !s.retained_cleanup);
   assert(bb_resp.attempts==1 && !bb_resp.released && !bb_req.attempts && !bb_req.released);
   assert(!pthread_mutex_trylock(&resource_mutex));assert(!pthread_mutex_unlock(&resource_mutex));
   int retry=99;assert(full_bb_set_mode_dispatch(0x92840747u,bb_req.data,&bb_io,&bb_guard,1,&retry) && retry==-1021);
   struct full_bb_set_mode_snapshot after_retry=bb_snap();assert(!memcmp(&s,&after_retry,sizeof s) && bb_frees==1);
   assert(!pthread_mutex_lock(&bb_thread_mutex));bb_thread_go=1;assert(!pthread_cond_signal(&bb_thread_condition));
   assert(!pthread_mutex_unlock(&bb_thread_mutex));assert(!pthread_join(bb_reply_thread,0));s=bb_snap();
   assert(s.faults && s.pending && !s.clean_completion && !s.queued && !s.busy && !s.guard_held && !held);
   assert(s.retained_request==bb_req.data && !s.request_freed && !bb_req.released && !bb_req.attempts && !s.retained_cleanup);
   assert(bb_frees==1 && bb_resp.attempts==1);
   if(bb_thread_error){
    assert(s.live_reply==bb_resp.data && s.retained_reply==bb_resp.data && !s.ap_consumed && !s.reply_freed && !bb_resp.released);
    int freed=99;assert(full_bb_set_mode_release_reply(bb_caller,bb_resp.data,bb_release,bb_record,&freed) && !freed);
   }
   s=bb_snap();assert(s.ap_consumed==1 && s.reply_freed==1 && !s.live_reply && !s.retained_reply && !s.retained_cleanup);
   assert(s.faults && s.pending && !s.clean_completion && !s.queued && s.retained_request==bb_req.data && !bb_req.released);
   assert(bb_resp.released && bb_resp.attempts==(bb_thread_error?2u:1u) && bb_frees==bb_resp.attempts);
   int freed=99;assert(full_bb_set_mode_release_reply(0x92840747u,bb_req.data,bb_release,bb_record,&freed) && !freed);
   s=bb_snap();assert(s.faults && !s.clean_completion && s.request_freed==1 && !s.retained_request && !s.retained_cleanup);
   assert(bb_req.released && bb_req.attempts==1 && bb_frees==bb_resp.attempts+1);
   freed=99;assert(!full_bb_set_mode_release_reply(bb_caller,bb_resp.data,bb_release,bb_record,&freed) && freed==99);
   assert(!full_bb_set_mode_release_reply(0x92840747u,bb_req.data,bb_release,bb_record,&freed) && freed==99);
   printf("BB_SET_MODE_IN_FLIGHT_PASS: dispatch_rc=0 first_free_rc=%d attempts=%u ap_consumed=1 clean_completion=0 owned_request_recovered=1\n",bb_thread_error?-49:0,bb_resp.attempts);
  } else if(bb_alloc_error || bb_alloc_null || bb_size!=12 || bb_alias || bb_source_error || bb_inject_prefix || bb_send_error){
   assert(s.faults && !s.clean_completion && s.retained_request==bb_req.data && !s.ap_consumed);
   if(!bb_send_error)assert(!bb_sends);
  } else {
   assert(bb_sends==1 && bb_sent>bb_applied && s.queued==1);
   if(bb_request_error)assert(s.faults && !s.clean_completion && !s.request_freed && s.retained_request==bb_req.data);
   else assert(s.clean_completion && !s.faults && s.request_freed && bb_req.released);
   if(!bb_inline_free){
    if(!strcmp(name,"wrong-owner")){int free_rc=99;assert(full_bb_set_mode_release_reply(bb_caller+1,bb_resp.data,bb_release,bb_record,&free_rc) && free_rc==-1021);}
    if(!strcmp(name,"reply-free-fail")){bb_free_error=-49;int free_rc=99;assert(full_bb_set_mode_release_reply(bb_caller,bb_resp.data,bb_release,bb_record,&free_rc) && free_rc==-49);bb_free_error=0;}
    int free_rc=99;assert(full_bb_set_mode_release_reply(bb_caller,bb_resp.data,bb_release,bb_record,&free_rc) && !free_rc);
   }
   assert(bb_snap().ap_consumed==1 && bb_resp.released && bb_snap().reply_freed==1);
  }
 }
 assert(bb_snapshots && bb_logs);
 puts("BB_SET_MODE_HOST_TEST_PASS");return 0;
}
