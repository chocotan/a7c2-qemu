/* SPDX-License-Identifier: MIT
 * Actual Main snippets + real bb-timecode-control.c. External OSAL IO, caller
 * PC/module identity and predecessor snapshots are LAB fixtures, not original AP.
 * shortcut: only TC receive/free blocks and resource37 wrapper are extracted;
 * parent full suites validate the complete shared resource/receive/free chains.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "device-models/bb-timecode-control.h"
#include "device-models/bb-set-mode-device.h"
#include "device-models/functional-camera-control.h"

typedef struct {const char *dli_fname;void *dli_fbase;const char *dli_sname;void *dli_saddr;} Dl_info;
static int functional_camera_enabled=1,cp_owned_state_enabled=1;
static unsigned int functional_bb_timecode_control_used,functional_bb_timecode_audit_pid;
static unsigned long long functional_bb_timecode_audit_sequence;
static unsigned long long functional_bb_timecode_preset_audit_sequence;
static int preset_mode,preset_audits,preset_commits;
static unsigned int functional_cp_ou_crank_control_ticket_pid,functional_cp_crank_control_ticket_pid;
static unsigned int functional_cp_movie_format_ticket_pid,still_format_ticket_pid,startup_control_ticket_pid;
static unsigned int bb_set_mode_used=1;
static unsigned long appfw_base=0x10000000UL;
static void *fixture_caller;
static const char *fixture_module="/lab/appFw.so";
static unsigned long fixture_module_base=0x10000000UL;
static int fixture_dladdr_ok=1,ou_chain_ready=1;
static struct native_functional_camera_ou_crank_snapshot ou;
static struct native_functional_camera_control_snapshot control;
static struct full_bb_set_mode_snapshot bb;
static int resource_rc,resource_calls,resource_held,resource_releases,last_resource;
static int raw_calls,raw_rc,raw_errno=ENOTTY,raw_null,request_frees,reply_frees,other_frees;
static int old_bb_frees,fallback_sends,send_calls,legacy_allocate_observations;
static int queued,receive_rc,commit_events,receive_events,state_before_seen,state_after_seen;
static int begin_events,audit_events,init_stage,timecode_init_calls,last_init_rc;
static char audit_line[800];
static unsigned char state_before[48],state_after[48];
static struct lab_message {unsigned int source,bytes;unsigned char wire[32];} request,reply,foreign;
static void *raw_pointer;
static long host_tid(void){return syscall(SYS_gettid);}
static long lab_syscall(long number){assert(number==178);return host_tid();}
#define syscall lab_syscall

static uint64_t hash_bytes(const unsigned char *p,size_t n){
 uint64_t h=UINT64_C(14695981039346656037);
 for(size_t i=0;i<n;i++)h=(h^p[i])*UINT64_C(1099511628211);
 return h;
}
static uint64_t load_le(const unsigned char *p,unsigned int n){
 uint64_t value=0;for(unsigned int i=0;i<n;i++)value|=(uint64_t)p[i]<<(8*i);return value;
}
static void read_hex48(const char *line,unsigned char *out){
 const char *raw=strstr(line," raw=");assert(raw);raw+=5;
 for(unsigned int i=0;i<48;i++){unsigned int value=0;assert(sscanf(raw+2*i,"%2x",&value)==1);out[i]=(unsigned char)value;}
}
static void record(const char *tag,const char *text){
 assert(tag && text);
 if(!strcmp(tag,"NATIVE_BB_TIMECODE_INPUT_AUDIT ") || !strcmp(tag,"NATIVE_BB_TIMECODE_PRESET_INPUT_AUDIT ")){
  assert(strlen(text)<sizeof audit_line);strcpy(audit_line,text);audit_events++;
  if(!strcmp(tag,"NATIVE_BB_TIMECODE_PRESET_INPUT_AUDIT "))preset_audits++;
 }
 if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_PRESET_EVENT ") && strstr(text,"event=COMMIT "))preset_commits++;
 if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_EVENT ")){
  if(strstr(text,"event=BEGIN ")){assert(audit_events>0);begin_events++;}
  if(strstr(text,"event=RECEIVE "))receive_events++;
  if(strstr(text,"event=COMMIT "))commit_events++;
 }
 if(!strcmp(tag,"FUNCTIONAL_BB_TIMECODE_BYTES ")){
  if(strstr(text,"kind=state_before ")){read_hex48(text,state_before);state_before_seen++;}
  if(strstr(text,"kind=state_after ")){read_hex48(text,state_after);state_after_seen++;}
 }
 errno=EINTR;
}
static struct lab_message *metadata(void *p){
 if(p==request.wire)return &request;
 if(p==reply.wire)return &reply;
 assert(p==foreign.wire);return &foreign;
}
static unsigned int size_api(void *p){return metadata(p)->bytes;}
static unsigned int source_api(void *p){return metadata(p)->source;}
static void set_source_api(void *p,unsigned int source){metadata(p)->source=source;}
static int raw_allocate(unsigned int id,void **out,unsigned int bytes,unsigned int count){
 (void)id;(void)bytes;(void)count;raw_calls++;if(out)*out=raw_null?NULL:raw_pointer;errno=raw_errno;return raw_rc;
}
static int raw_free(unsigned int id,void *p){
 assert(id && p);
 if(p==request.wire){assert(id==FULL_BB_TIMECODE_CONTROL_CP);request_frees++;}
 else if(p==reply.wire)reply_frees++;
 else {assert(p==foreign.wire);other_frees++;}
 errno=ENOTTY;return 0;
}
static int send_api(unsigned int destination,void *p){
 assert(destination==request.source && p==reply.wire && p!=request.wire && reply.bytes==12);
 unsigned char expected[12]={0x0d,0x20,1,0x14,12,0,1,0x80,0,0,0,0};
 if(preset_mode)expected[2]=request.wire[2];
 assert(!memcmp(p,expected,12) && reply.source==FULL_BB_TIMECODE_CONTROL_CP);
 if(preset_mode)assert(request_frees==reply_frees+1);
 else assert(request_frees==1 && !reply_frees);
 send_calls++;queued=1;return 0;
}
static int dladdr_api(void *p,Dl_info *out){
 assert(p==fixture_caller);out->dli_fname=fixture_module;out->dli_fbase=(void *)(uintptr_t)fixture_module_base;
 return fixture_dladdr_ok;
}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static void (*real_set_source)(void *,unsigned int)=set_source_api;
static int (*real_free_msg)(unsigned int,void *)=raw_free;
static int (*real_send_msg)(unsigned int,void *)=send_api;
static int (*real_dladdr)(void *,Dl_info *)=dladdr_api;
static int (*native_real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int);
static int (*real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int);
static void native_movie_format_allocated(unsigned int id,void **p,int rc,unsigned int count){
 (void)id;(void)p;(void)rc;(void)count;legacy_allocate_observations++;errno=EINTR;
}
static void native_ou_crank_allocated(unsigned int id,void **p,int rc,unsigned int count){
 (void)id;(void)p;(void)rc;(void)count;legacy_allocate_observations++;errno=EINTR;
}
static int tracked_native_reserve_resources(int index){
 assert(index==37 && !resource_held);last_resource=index;resource_calls++;
 if(resource_rc)return resource_rc;
 resource_held=1;return 0;
}
static void full_vef_resources_unlock(void){assert(resource_held);resource_held=0;resource_releases++;}
static int functional_cp_ou_crank_control_predecessors_ready(void){return ou_chain_ready;}
void native_functional_camera_ou_crank_snapshot(struct native_functional_camera_ou_crank_snapshot *out){*out=ou;}
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *out){*out=control;}
void full_bb_set_mode_snapshot(struct full_bb_set_mode_snapshot *out){*out=bb;}
int full_bb_set_mode_release_reply(unsigned int id,void *p,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result){
 (void)id;(void)p;(void)result;assert(release==raw_free && logger==record);old_bb_frees++;return 0;
}
static int same_name(const char *a,const char *b){return a && b && !strcmp(a,b);}
int native_functional_camera_control_owner_init(void){assert(init_stage==0);init_stage++;return 0;}
int native_functional_camera_parameter_owner_init(void){assert(init_stage==1);init_stage++;return 0;}
int native_functional_camera_crank_owner_init(void){assert(init_stage==2);init_stage++;return 0;}
int native_functional_camera_movie_format_owner_init(void){assert(init_stage==3);init_stage++;return 0;}
int native_functional_camera_ou_crank_owner_init(void){assert(init_stage==4);init_stage++;return 0;}
static int observed_timecode_init(void){
 assert(init_stage==5);init_stage++;timecode_init_calls++;
 last_init_rc=full_bb_timecode_control_owner_init();return last_init_rc;
}
int functional_still_format_owner_init(void){assert(init_stage==6);init_stage++;return 0;}
int functional_startup_control_owner_init(void){assert(init_stage==7);init_stage++;return 0;}

/* ACTUAL_MAIN_HELPERS */

static void bind_initial_allocator(void){
 native_real_allocate_msg=raw_allocate;
/* ACTUAL_INITIAL_ALLOCATOR_BINDING */
}
static void bind_dynamic_allocator(void){
 native_real_allocate_msg=raw_allocate;
/* ACTUAL_DYNAMIC_ALLOCATOR_BINDING */
}
static int actual_timecode_shared_guard(int adf){
/* ACTUAL_MAIN_TC_SHARED_GUARD */
 return 0;
}
static int actual_send(unsigned int id,void *message){
/* ACTUAL_MAIN_ROUTE */
 fallback_sends++;return -777;
}
static int actual_free(unsigned int id,void *message){
 int vdf_result;
/* ACTUAL_MAIN_FREE */
 return real_free_msg(id,message);
}
#define full_bb_timecode_control_owner_init observed_timecode_init
static void actual_init(const char *functional_profile){
/* ACTUAL_MAIN_INIT */
}
#undef full_bb_timecode_control_owner_init

static struct full_bb_timecode_snapshot snapshot(void){
 struct full_bb_timecode_snapshot out={0};full_bb_timecode_control_snapshot(&out);return out;
}
static void seed(void){
 request.source=0x80000061u;request.bytes=10;
 const unsigned char wire[10]={0x0d,0x20,1,4,10,0,1,0x80,1,0};memcpy(request.wire,wire,10);
 reply.bytes=12;raw_pointer=reply.wire;foreign.source=0x80000079u;foreign.bytes=23;
 fixture_caller=(void *)(uintptr_t)(appfw_base+0x34e56e8UL);
 functional_bb_timecode_audit_pid=(unsigned int)getpid();
 bb.owner_pid=getpid();bb.initialized=bb.clean_completion=bb.ap_consumed=1;
 control.model_instance=0x10203040u;
 ou.owner_pid=getpid();ou.initialized=ou.model_called=ou.model_committed=ou.verified=1;
 ou.owned=ou.complete=ou.request_freed=1;ou.model_instance=control.model_instance;
 ou.transaction=ou.ou_generation=1;ou.requests=ou.commits=ou.verified_commits=ou.completions=ou.released=1;
 ou.sender_tid=(unsigned int)host_tid();ou.free_tid=ou.sender_tid;
 ou.before_config_generation=7;ou.config_generation=8;
 memcpy(ou.receipt+80,ou.after_state,sizeof ou.after_state);ou.receipt_fnv1a64=hash_bytes(ou.receipt,sizeof ou.receipt);
 bind_initial_allocator();
}
static void dispatch_one(void){
 assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==0);
 struct full_bb_timecode_snapshot s=snapshot();
 assert(s.busy && s.queued && s.request_freed && !s.reply_received && !s.reply_freed && !s.ap_consumed);
 assert(s.known_mask==2 && s.dfmode==1 && s.generation==1 && s.applications==1);
 assert(s.live_reply==reply.wire && !s.retained_request && send_calls==1 && request_frees==1);
 assert(!resource_held && last_resource==37 && resource_calls==1 && resource_releases==1);
 assert(raw_calls==1 && legacy_allocate_observations==2 && begin_events==1 && !commit_events);
}
/* External OSAL receive fixture; the actual Main post-return TC block follows. */
static int receive_reply(void){
 void *p=queued?reply.wire:NULL;int rc=receive_rc;
 native_cp_state_received(request.source,&p,rc);return rc;
}
static void finish_one(void){
 assert(!receive_reply());struct full_bb_timecode_snapshot s=snapshot();
 assert(s.reply_received && !s.ap_consumed && receive_events==1 && !commit_events);
 assert(actual_free(request.source,reply.wire)==0);s=snapshot();
 assert(s.ap_consumed && s.reply_freed && !s.busy && !s.live_reply && !s.retained_reply && !s.faults);
 assert(s.sender_tid==(unsigned int)host_tid() && s.receiver_tid==s.sender_tid);
 assert(request_frees==1 && reply_frees==1 && !old_bb_frees && commit_events==1);
}
static void check_success(void){
 dispatch_one();assert(state_before_seen==1 && state_after_seen==1);
 assert(load_le(state_before,4)==1 && load_le(state_before+4,4)==48);
 assert(load_le(state_after+8,4)==(unsigned int)getpid());
 assert(load_le(state_before+12,4)==0 && load_le(state_after+12,4)==2);
 assert(load_le(state_after+16,8)==load_le(state_before+16,8)+1);
 assert(load_le(state_after+28,4)==1 && !load_le(state_after+24,4) && !load_le(state_after+32,4));
 assert(load_le(state_after+40,8)==load_le(state_before+40,8)+1);
 char digest[64];snprintf(digest,sizeof digest,"fnv1a64=%016" PRIx64,hash_bytes(request.wire,10));
 assert(strstr(audit_line,"raw=0d2001040a0001800100 ") && strstr(audit_line,digest));
 assert(strstr(audit_line,"caller_raw=0x34e56e8 ") && strstr(audit_line,"original_sender_bound=1 "));
 assert(strstr(audit_line,"consumed=0 state_verified=0 diagnostic_only=1"));
 assert(snapshot().state_fnv==hash_bytes(state_after,48));finish_one();
}
static void check_input_rejections(void){
 struct lab_message original=request;
 for(unsigned int i=0;i<13;i++){
  request=original;fixture_caller=(void *)(uintptr_t)(appfw_base+0x34e56e8UL);
  fixture_module="/lab/appFw.so";fixture_module_base=appfw_base;fixture_dladdr_ok=1;
  int expected=-ELIBBAD;
  if(i==0)fixture_caller=(void *)(uintptr_t)(appfw_base+0x34e56e4UL);
  else if(i==1)fixture_module="/lab/not-appFw.so";
  else if(i==2)fixture_module_base++;
  else if(i==3){request.bytes=9;expected=-ENOTSUP;}
  else if(i==4)request.source=0;
  else if(i==5)request.source=0x80000000u;
  else if(i==6){request.wire[6]=0;expected=-EINVAL;}
  else if(i==7){request.wire[0]=0x0c;expected=-777;}
  else if(i==8)fixture_dladdr_ok=0;
  else if(i==9){request.wire[4]=11;expected=-EINVAL;}
  else if(i==10){request.wire[8]=2;expected=-EINVAL;}
  else if(i==11){request.wire[9]=1;expected=-EINVAL;}
  else request.source=FULL_BB_TIMECODE_CONTROL_CP;
  assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==expected);
  assert(!request_frees && !raw_calls && !send_calls && !snapshot().generation && !snapshot().busy);
 }
 request=original;fixture_dladdr_ok=1;functional_camera_enabled=0;
 assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==-777 && !raw_calls);
 functional_camera_enabled=1;functional_bb_timecode_audit_sequence=UINT64_MAX;errno=EDOM;
 assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==-EOVERFLOW && errno==EINTR);
 /* The refusal logger owns the final errno; the audit itself must preserve it. */
 errno=EDOM;assert(native_bb_timecode_input_audit(FULL_BB_TIMECODE_CONTROL_CP,request.wire,fixture_caller)==-EOVERFLOW);
 assert(errno==EDOM && !snapshot().generation && !request_frees);
}
static void *wrong_receive_thread(void *unused){
 (void)unused;assert(!receive_reply());return NULL;
}
static void check_receive(const char *test){
 dispatch_one();
 if(!strcmp(test,"receive-failure")){
  receive_rc=-EIO;errno=ERANGE;assert(receive_reply()==-EIO && errno==ERANGE);
  assert(!snapshot().reply_received && !snapshot().ap_consumed && !snapshot().faults && !receive_events);
  receive_rc=0;finish_one();return;
 }
 if(!strcmp(test,"receive-metadata")){reply.source++;assert(!receive_reply());}
 else {pthread_t thread;assert(!pthread_create(&thread,NULL,wrong_receive_thread,NULL));assert(!pthread_join(thread,NULL));}
 struct full_bb_timecode_snapshot s=snapshot();
 assert(s.faults && !s.reply_received && !s.ap_consumed && s.live_reply==reply.wire && !reply_frees && !commit_events);
 assert(actual_free(request.source,reply.wire)<0 && !reply_frees && !old_bb_frees);
 assert(actual_timecode_shared_guard(36)==-ENODATA && !actual_timecode_shared_guard(37));
}
static void check_allocator_reuse(void){
 dispatch_one();finish_one();int frees=reply_frees;
 assert(actual_free(request.source,reply.wire)==-EALREADY && reply_frees==frees && !old_bb_frees);
 /* A successful foreign allocation at the same address ends the old identity. */
 raw_pointer=reply.wire;reply.bytes=23;reply.source=foreign.source;bind_dynamic_allocator();
 void *p=NULL;errno=EDOM;assert(!real_allocate_msg(0x80000079u,&p,23,1) && p==reply.wire && errno==raw_errno);
 assert(!actual_free(0x80000079u,p) && reply_frees==frees+1 && old_bb_frees==1);
 assert(snapshot().ap_consumed && !snapshot().faults && commit_events==1);
}
static void check_allocator_return(void){
 dispatch_one();finish_one();int frees=reply_frees;
 for(unsigned int i=0;i<5;i++){
  raw_rc=i==0?-EIO:(i==1?7:0);raw_null=i==3;unsigned int count=i==2?2:1;
  void *p=NULL;void **out=i==4?NULL:&p;int calls=raw_calls,observers=legacy_allocate_observations;
  errno=EDOM;assert(real_allocate_msg(0x80000079u,out,23,count)==raw_rc && errno==raw_errno);
  assert(raw_calls==calls+1 && legacy_allocate_observations==observers+2);
  assert(actual_free(request.source,reply.wire)==-EALREADY && reply_frees==frees && !old_bb_frees);
 }
}
static void check_allocator_live_alias(void){
 dispatch_one();struct full_bb_timecode_snapshot before=snapshot();void *p=NULL;errno=EDOM;
 assert(!real_allocate_msg(0x80000079u,&p,23,1) && p==reply.wire && errno==raw_errno);
 struct full_bb_timecode_snapshot after=snapshot();
 assert(after.live_reply==before.live_reply && after.retained_reply==before.retained_reply && after.busy==before.busy);
 assert(after.generation==before.generation && after.applications==before.applications && after.faults==before.faults);
 assert(!after.reply_received && !after.reply_freed && !after.ap_consumed);
 /* The central wrapper preserves rc/errno; the owner refuses retirement of a live alias. */
 assert(full_bb_timecode_control_observe_allocate(0x80000079u,p,23,1,0)==-EBUSY);
 finish_one();
}
static void check_resource_predecessors(void){
 assert(functional_bb_timecode_predecessors_ready()==1);
 assert(!functional_bb_timecode_reserve_resources() && resource_held && last_resource==37);
 full_vef_resources_unlock();resource_rc=-EBUSY;
 assert(functional_bb_timecode_reserve_resources()==-EBUSY && !resource_held);
 struct native_functional_camera_ou_crank_snapshot original=ou;
 ou_chain_ready=0;assert(!functional_bb_timecode_predecessors_ready());ou_chain_ready=1;
 ou.complete=0;assert(!functional_bb_timecode_predecessors_ready());ou=original;
 ou.model_instance++;assert(!functional_bb_timecode_predecessors_ready());ou=original;
 ou.request_freed=0;assert(!functional_bb_timecode_predecessors_ready());ou=original;
 ou.free_tid++;assert(!functional_bb_timecode_predecessors_ready());ou=original;
 ou.retained_request=request.wire;assert(!functional_bb_timecode_predecessors_ready());ou=original;
 int *errors[]={&ou.before_rc,&ou.model_rc,&ou.after_rc,&ou.validation_rc,&ou.free_rc,&ou.error};
 for(unsigned int i=0;i<sizeof errors/sizeof errors[0];i++){
  *errors[i]=-EIO;assert(!functional_bb_timecode_predecessors_ready());*errors[i]=0;
 }
 ou.receipt[0]^=1;assert(!functional_bb_timecode_predecessors_ready());ou=original;
 bb.ap_consumed=0;assert(!functional_bb_timecode_predecessors_ready());bb.ap_consumed=1;
 assert(functional_bb_timecode_predecessors_ready()==1 && !snapshot().applications);
 /* Real route + real owner must propagate reserve refusal without taking request ownership. */
 assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==-EBUSY);
 assert(!raw_calls && !request_frees && !send_calls && !snapshot().applications && !snapshot().busy);
 resource_rc=0;ou.complete=0;
 assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==-ENODATA);
 assert(!raw_calls && !request_frees && !send_calls && !resource_held && !snapshot().applications);
}
static void check_shared_guard(void){
 assert(!actual_timecode_shared_guard(36) && !actual_timecode_shared_guard(37));
 assert(actual_timecode_shared_guard(-1)==-1021 && actual_timecode_shared_guard(38)==-1021);
 dispatch_one();struct full_bb_timecode_snapshot before=snapshot();
 for(int index=0;index<37;index++)assert(actual_timecode_shared_guard(index)==-ENODATA);
 assert(!actual_timecode_shared_guard(37));
 struct full_bb_timecode_snapshot after=snapshot();
 assert(after.busy==before.busy && after.live_reply==before.live_reply && after.generation==before.generation);
 assert(!after.faults && !after.reply_received && !after.ap_consumed);
 finish_one();
 for(int index=0;index<38;index++)assert(!actual_timecode_shared_guard(index));
}
static void check_constructor(void){
 actual_init(FCAM_PROFILE);
 assert(functional_camera_enabled && init_stage==8 && timecode_init_calls==1 && !last_init_rc);
 assert(functional_bb_timecode_audit_pid==(unsigned int)getpid() && snapshot().initialized);
 init_stage=0;actual_init(FCAM_PROFILE);
 assert(!functional_camera_enabled && init_stage==6 && timecode_init_calls==2 && last_init_rc==-EALREADY);
 assert(!request_frees && !raw_calls && !snapshot().applications);
}
static void preset_main_cycle(unsigned int command,unsigned int body){
 request.bytes=command==0x040au?12u:10u;
 const unsigned char header[8]={0x0d,0x20,0,4,0,0,1,0x80};memcpy(request.wire,header,8);
 request.wire[2]=(unsigned char)command;request.wire[4]=(unsigned char)request.bytes;
 for(unsigned int i=8;i<request.bytes;i++)request.wire[i]=(unsigned char)(body>>(8*(i-8)));
 assert(actual_send(FULL_BB_TIMECODE_CONTROL_CP,request.wire)==0);
 assert(!receive_reply());assert(actual_free(request.source,reply.wire)==0);
 struct full_bb_timecode_snapshot s=snapshot();assert(s.ap_consumed && !s.busy && !s.faults);
}
static void check_preset_pair(void){
 preset_mode=1;preset_main_cycle(0x0401u,1);preset_main_cycle(0x0402u,0);preset_main_cycle(0x0400u,0);
 struct full_bb_timecode_snapshot before=snapshot();assert(before.known_mask==7 && before.generation==3);
 preset_main_cycle(0x040au,0xff00807fu);
 assert(strstr(audit_line,"command=0x40a bytes=12 raw=0d200a040c0001807f8000ff "));
 struct full_bb_timecode_snapshot middle=snapshot();
 assert(middle.preset_raw4==0xff00807fu && middle.preset_known_mask==1 && middle.preset_generation==1);
 preset_main_cycle(0x0409u,1);
 assert(strstr(audit_line,"command=0x409 bytes=10 raw=0d2009040a0001800100 "));
 struct full_bb_timecode_snapshot after=snapshot();
 assert(after.preset_raw4==middle.preset_raw4 && after.ubmode_wire==1 && after.preset_known_mask==3);
 assert(after.preset_generation==2 && after.preset_applications==2 && after.preset_command_generations[0]==1 && after.preset_command_generations[1]==2);
 assert(after.generation==before.generation && after.applications==before.applications && after.known_mask==before.known_mask);
 assert(!memcmp(after.command_generations,before.command_generations,sizeof after.command_generations));
 assert(preset_audits==2 && preset_commits==2 && request_frees==5 && reply_frees==5 && send_calls==5);
}
static void check_preset_audit_rejections(void){
 const unsigned char valid[12]={0x0d,0x20,0x0a,4,12,0,1,0x80,0xff,0,0x80,0x7f};
 request.bytes=12;memcpy(request.wire,valid,12);
 for(unsigned int i=0;i<12;i++){
  request.bytes=12;memcpy(request.wire,valid,12);request.source=0x80000061u;
  fixture_caller=(void *)(uintptr_t)(appfw_base+0x34e56e8UL);fixture_module="/lab/appFw.so";
  int expected=-EINVAL;
  if(i==0)request.bytes=10;
  else if(i==1)request.wire[0]^=1;
  else if(i==2)request.wire[4]=10;
  else if(i==3)request.wire[5]=1;
  else if(i==4)request.wire[6]=0;
  else if(i==5)request.wire[7]=0;
  else if(i==6){request.bytes=10;request.wire[2]=9;request.wire[4]=10;request.wire[8]=2;request.wire[9]=0;}
  else if(i==7){request.bytes=10;request.wire[2]=9;request.wire[4]=10;request.wire[8]=0;request.wire[9]=1;}
  else if(i==8){request.source=0;expected=-ELIBBAD;}
  else if(i==9){fixture_caller=(void *)(uintptr_t)(appfw_base+0x34eee18UL);expected=-ELIBBAD;}
  else if(i==10){fixture_module="/lab/not-appFw.so";expected=-ELIBBAD;}
  else {functional_bb_timecode_preset_audit_sequence=UINT64_MAX;expected=-EOVERFLOW;}
  assert(native_bb_timecode_preset_input_audit(FULL_BB_TIMECODE_CONTROL_CP,request.wire,fixture_caller)==expected);
  assert(!raw_calls && !snapshot().requests && !snapshot().applications && !snapshot().preset_applications);
 }
}
int main(int argc,char **argv){
 assert(argc==2);seed();
 if(!strcmp(argv[1],"constructor"))check_constructor();
 else {
  assert(!full_bb_timecode_control_owner_init());
  if(!strcmp(argv[1],"success"))check_success();
  else if(!strcmp(argv[1],"preset-pair"))check_preset_pair();
  else if(!strcmp(argv[1],"preset-audit-rejections"))check_preset_audit_rejections();
  else if(!strcmp(argv[1],"input-rejections"))check_input_rejections();
  else if(!strncmp(argv[1],"receive-",8))check_receive(argv[1]);
  else if(!strcmp(argv[1],"allocator-reuse"))check_allocator_reuse();
  else if(!strcmp(argv[1],"allocator-return"))check_allocator_return();
  else if(!strcmp(argv[1],"allocator-live-alias"))check_allocator_live_alias();
  else if(!strcmp(argv[1],"shared-guard"))check_shared_guard();
  else {assert(!strcmp(argv[1],"resource-predecessors"));check_resource_predecessors();}
 }
 assert(!resource_held);
 puts("PASS actual Main timecode slices + real owner LAB; original AP/CP/physical/capture unverified");return 0;
}
