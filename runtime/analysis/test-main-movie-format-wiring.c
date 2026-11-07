/* SPDX-License-Identifier: MIT
 * Production Main functions/slices are inserted at exact ACTUAL_* markers.
 * Owner/Core/bridge/resource results here are explicit MOCKS; no AP/capture claim.
 */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "device-models/functional-camera-control.h"
#include "device-models/functional-still-format.h"
#include "device-models/functional-startup-control.h"
#include "device-models/cp-ee-controls-diagnostic.h"
#include "device-models/cp-movie-format-diagnostic.h"
#include "device-models/cp-output-policy.h"
#include "device-models/adf-set-input-device.h"
#include "device-models/adf-set-output-device.h"
#include "device-models/vef-resource-guard.h"
#include "device-models/pinmem-hdmi-video-connection.h"
#include "device-models/hdmi-pin-device.h"
#include "device-models/bb-timecode-control.h"
/* Timecode is inactive in this older owner-mock fixture. */
static unsigned int functional_bb_timecode_control_used;
void full_bb_timecode_control_snapshot(struct full_bb_timecode_snapshot *out){
 assert(!functional_bb_timecode_control_used);*out=(struct full_bb_timecode_snapshot){0};
}
int full_bb_timecode_control_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;assert(!functional_bb_timecode_control_used);return 0;
}
int full_bb_timecode_control_observe_allocate(unsigned int id,void *p,unsigned int bytes,unsigned int count,int rc){
 (void)id;(void)p;(void)bytes;(void)count;(void)rc;assert(!functional_bb_timecode_control_used);return 0;
}
static unsigned int functional_bb_timecode_audit_pid;

/* ACTUAL_MOVIE_TICKET_DECLARATIONS */
static int functional_camera_enabled=1,cp_owned_state_enabled=1,functional_camera_setup_error;
static unsigned int functional_cp_parameter_bank_used,functional_still_format_used,functional_startup_control_used;
static unsigned int functional_layout_stage_used,functional_vdf_path_used,functional_mpr_codec_used;
static unsigned int still_format_ticket_pid,startup_control_ticket_pid,cp_movie_format_used;
static int cp_movie_format_enabled=1;
static struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_layout_stage_ticket,functional_vdf_ticket;
static struct native_functional_camera_parameter_snapshot bank;
static struct native_functional_camera_crank_snapshot crank;
static struct native_functional_camera_movie_format_snapshot movie;
static struct native_cp_movie_format_diagnostic_snapshot early;
static struct native_cp_ee_controls_diagnostic_snapshot ee;
static struct cp_output_policy cp_output_policy_state;
static struct cp_output_policy_snapshot policy;
static unsigned long cp_parameter_batch_mutex[6],cap_lock[6],lens_pool_lock[6];
static void *cp_parameter_batch_retained_request;
static pthread_mutex_t ticket_lock=PTHREAD_MUTEX_INITIALIZER,crank_ticket_lock=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local int movie_ticket_held,crank_ticket_held;
static int request_reuse_before_return,postdispatch_pid_drift,arm_postdispatch_snapshot,expect_postdispatch_snapshot,postdispatch_snapshots,dispatch_return_locks;
static int raw_errno=ENOTTY,clobber_ticket_errno,allocate_via_receive,io_allocation_calls,io_allocation_rc,io_allocation_errno;
static void *reused_request,*io_allocated_reply;
static long reuse_tid;
static int original_pid,locks,unlocks,batch_held,cap_held,resource_held,resource_calls,resource_unlocks;
static int resource_rc,resource_admissible=1,predecessor_ready=1,ready_reads,policy_rc;
static enum full_vef_dmm_domain resource_domain=FULL_VEF_DMM_SPEECH_INITIAL;
static int bank_reads,crank_reads,movie_reads,early_reads,forbid_snapshot;
static int bridge_calls,bridge_rc,context_drift,owner_calls,owner_handled=1,owner_rc;
static int before_calls,model_calls,after_calls,before_rc,model_rc,after_rc,receipt_bytes=240,receipt_valid=1;
static int allocation_calls,allocation_rc,allocation_null,allocation_drift,send_calls,send_rc;
static int request_frees,reply_frees,ordinary_frees,free_rc,receive_calls,release_calls,receive_observed;
static int legacy_calls,legacy_rc=-777,fallback_sends,synchronous_receive,synchronous_free;
static int legacy_handled=1,sdk_calls,parameter_release_calls,crank_release_calls,transport_failure;
static uint64_t event_transaction=UINT64_C(0x100000009),last_receive_transaction,last_free_transaction;
static long sender_tid,receiver_tid,free_tid;
static struct native_functional_camera_movie_format_context expected_context={77,3,9},captured_context;
static unsigned char request_wire[24]={5,0,0,0x40,0x60,0,0,0x80,5,1,0,0,0,0,0,0,0,0,1,0};
static unsigned char reply_wire[12],foreign_wire[12],receipt240[240];
static unsigned int message_bytes=20,message_source=FUNCTIONAL_CAMERA_CONTROL_AP,reply_source=FUNCTIONAL_CAMERA_CONTROL_SID,reply_bytes=12;
static void *allocated_pointer=reply_wire;
static struct full_adf_proc_snapshot proc;
static struct full_adf_set_input_snapshot input;
static struct full_adf_set_output_snapshot output;
static struct full_vef_resource_snapshot resource_fixture;
static struct functional_still_format_snapshot still;
static struct functional_startup_control_snapshot startup;
static struct dmm_service dmm;
static int dmm_enabled=1,backup_service_enabled;
static unsigned long appfw_base;
static unsigned int pinmem_peer_connections_used;
#define LENS_POOL_SLOTS 2
static struct {unsigned int live;void *message;unsigned int borrowed_from;} lens_pool[LENS_POOL_SLOTS];
static char last_resource_tag[100];
static unsigned int movie_reserved_tags,movie_tts_tags,movie_refused_tags,movie_fault_tags;
static int actual_free(unsigned int,void *);
static void *request_reuse_thread(void *);
static int functional_cp_movie_format_reserve_resources(void);
static int functional_cp_movie_format_predecessors_ready(void);
static int native_movie_format_allocate(unsigned int,void **,unsigned int,unsigned int);
static int native_movie_format_send(unsigned int,void *);
static uint64_t native_movie_format_ticket_for(unsigned int,void *);
static void native_movie_format_allocated(unsigned int,void **,int,unsigned int);
static void native_crank_allocated(unsigned int,void **,int,unsigned int);
static void native_pin_peer_allocated(unsigned int,void **,int,unsigned int);
static void native_cp_state_received(unsigned int,void **,int);

static long actual_tid(void){return syscall(SYS_gettid);}
static long fixture_syscall(long number){assert(number==178);return actual_tid();}
#define syscall fixture_syscall
static int fixture_mutex_lock(void *mutex){
 assert(getpid()==original_pid);++locks;
 if(mutex==functional_cp_movie_format_ticket_mutex){
  assert(!movie_ticket_held);int rc=pthread_mutex_lock(&ticket_lock);if(!rc)movie_ticket_held=1;return rc;
 }
 if(mutex==functional_cp_crank_control_ticket_mutex){
  assert(!crank_ticket_held);int rc=pthread_mutex_lock(&crank_ticket_lock);if(!rc)crank_ticket_held=1;return rc;
 }
 if(mutex==cp_parameter_batch_mutex){assert(!batch_held);batch_held=1;return 0;}
 if(mutex==cap_lock){assert(resource_held && !cap_held);cap_held=1;return 0;}
 assert(mutex==lens_pool_lock);return 0;
}
static int fixture_mutex_unlock(void *mutex){
 assert(getpid()==original_pid);++unlocks;
 if(mutex==functional_cp_movie_format_ticket_mutex){
  assert(movie_ticket_held);movie_ticket_held=0;int rc=pthread_mutex_unlock(&ticket_lock);
  if(clobber_ticket_errno)errno=EINTR;
  return rc;
 }
 if(mutex==functional_cp_crank_control_ticket_mutex){
  assert(crank_ticket_held);crank_ticket_held=0;return pthread_mutex_unlock(&crank_ticket_lock);
 }
 if(mutex==cp_parameter_batch_mutex){assert(batch_held);batch_held=0;return 0;}
 if(mutex==cap_lock){assert(cap_held);cap_held=0;return 0;}
 assert(mutex==lens_pool_lock);return 0;
}
static void hold_fork_lock(void){assert(!pthread_mutex_lock(&ticket_lock));}
static void drop_fork_lock(void){assert(!pthread_mutex_unlock(&ticket_lock));}
#define pthread_mutex_lock fixture_mutex_lock
#define pthread_mutex_unlock fixture_mutex_unlock
static int fixture_open(const char *path,int flags){assert(!strcmp(path,"/proc/self/mem") && !flags);return -1;}
static long fixture_pread(int fd,void *out,size_t bytes,long offset){(void)fd;(void)out;(void)bytes;(void)offset;assert(0);return -1;}
static int fixture_close(int fd){(void)fd;assert(0);return -1;}
#define open fixture_open
#define pread fixture_pread
#define close fixture_close
static void record(const char *tag,const char *text){
 assert(tag && *tag && text && *text);
 const char *event=tag;
 if(!strncmp(event,"FUNCTIONAL_BACKGROUND_START_",sizeof "FUNCTIONAL_BACKGROUND_START_"-1))event+=sizeof "FUNCTIONAL_BACKGROUND_START_"-1;
 assert(!strstr(event,"ACK") && !strstr(tag,"_MODEL"));
 if(strstr(tag,"_RESOURCE")){assert(strlen(tag)<sizeof last_resource_tag);strcpy(last_resource_tag,tag);}
 if(!strcmp(tag,"FUNCTIONAL_CP_MOVIE_FORMAT_RESOURCES_RESERVED "))++movie_reserved_tags;
 if(!strcmp(tag,"FUNCTIONAL_CP_MOVIE_FORMAT_RESOURCES_TTS_TABLE "))++movie_tts_tags;
 if(!strcmp(tag,"FUNCTIONAL_CP_MOVIE_FORMAT_RESOURCES_REFUSED "))++movie_refused_tags;
 if(!strcmp(tag,"FUNCTIONAL_CP_MOVIE_FORMAT_RESOURCES_FAULT "))++movie_fault_tags;
}
void native_functional_camera_parameter_snapshot(struct native_functional_camera_parameter_snapshot *out){assert(!forbid_snapshot && !batch_held);++bank_reads;*out=bank;}
void native_functional_camera_crank_snapshot(struct native_functional_camera_crank_snapshot *out){assert(!forbid_snapshot && !batch_held);++crank_reads;*out=crank;}
void native_functional_camera_movie_format_snapshot(struct native_functional_camera_movie_format_snapshot *out){
 assert(!forbid_snapshot && !batch_held);
 if(expect_postdispatch_snapshot){assert(movie_ticket_held);++postdispatch_snapshots;}
 ++movie_reads;*out=movie;
}
void native_cp_movie_format_diagnostic_snapshot(struct native_cp_movie_format_diagnostic_snapshot *out){assert(!forbid_snapshot && !batch_held);++early_reads;*out=early;}
void native_cp_ee_controls_diagnostic_snapshot(struct native_cp_ee_controls_diagnostic_snapshot *out){assert(!batch_held);*out=ee;}
int cp_output_policy_snapshot(const struct cp_output_policy *state,uint32_t mask,struct cp_output_policy_snapshot *out){
 assert(state==&cp_output_policy_state && mask==CP_OUTPUT_POLICY_KNOWN_MASK && batch_held);*out=policy;return policy_rc;
}
/* Lower all13/current-mode predicates have their own actual-source fixtures. */
static int functional_cp_parameter_bank_predecessors_ready(void){++ready_reads;return predecessor_ready;}
void functional_still_format_snapshot(struct functional_still_format_snapshot *out){assert(!resource_held);*out=still;}
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *out){assert(!resource_held);*out=startup;}
void full_adf_proc_snapshot(struct full_adf_proc_snapshot *out){assert(!resource_held);*out=proc;}
void full_adf_set_input_snapshot(struct full_adf_set_input_snapshot *out){assert(!resource_held);*out=input;}
void full_adf_set_output_snapshot(struct full_adf_set_output_snapshot *out){assert(!resource_held);*out=output;}
int full_vef_resources_lock(void){
 assert(!resource_held);++resource_calls;if(resource_rc)return resource_rc;resource_held=1;
 if(context_drift==4){bank.model_instance++;crank.model_instance++;bank.bank_generation++;crank.bank_generation++;crank.crank_generation++;}
 return 0;
}
void full_vef_resources_unlock(void){assert(resource_held);resource_held=0;++resource_unlocks;}
void pin_control_snapshot(struct pin_control_snapshot *out){assert(resource_held);*out=resource_fixture.control;}
void full_pin_connection_snapshot(struct pin_connection_snapshot *out){assert(resource_held);*out=resource_fixture.connection;}
void full_vef_snapshot(struct full_vef_snapshot *out){assert(resource_held);*out=resource_fixture.vef;}
void full_pinmem_snapshot(struct full_vef_snapshot *out){assert(resource_held);*out=resource_fixture.pinmem;}
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out){assert(resource_held);memset(out,0,sizeof *out);}
void full_hdmi_pin_snapshot(struct full_vef_snapshot *out){assert(resource_held);memset(out,0,sizeof *out);}
enum full_vef_dmm_domain full_vef_resource_dmm_domain(const struct full_vef_resource_snapshot *s){
 assert(resource_held && s && s->dmm.slots[0].handle==0x41 && s->dmm.slots[1].handle==0x42);return resource_domain;
}
int full_vef_resources_admissible(const struct full_vef_resource_snapshot *s){assert(resource_held && s);return resource_admissible;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){
 assert(logger==record);++bridge_calls;
 if(context_drift==1){bank.model_instance++;crank.model_instance++;}
 if(context_drift==2){bank.bank_generation++;crank.bank_generation++;}
 if(context_drift==3)crank.crank_generation++;
 return bridge_rc;
}
static unsigned int size_api(void *p){assert(p);return p==request_wire?message_bytes:reply_bytes;}
static unsigned int source_api(void *p){assert(p);return p==request_wire?message_source:reply_source;}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static int free_api(unsigned int id,void *p){
 assert(id && p && !batch_held);
 if(p==request_wire)++request_frees;else if(p==reply_wire)++reply_frees;else{assert(p==foreign_wire);++ordinary_frees;}
 return free_rc;
}
static int (*real_free_msg)(unsigned int,void *)=free_api;
static int allocate_api(unsigned int id,void **out,unsigned int bytes,unsigned int count){
 assert(id && bytes && count && !batch_held);++allocation_calls;
 if(out)*out=allocation_null?NULL:allocated_pointer;
 if(allocation_drift)movie.transaction++;
 errno=raw_errno;return allocation_rc;
}
/* ACTUAL_MOVIE_ALLOCATOR_DECLARATIONS */
static void set_source_api(void *p,unsigned int source){assert(p==reply_wire && source==FUNCTIONAL_CAMERA_CONTROL_SID && movie.verified);}
static void (*real_set_source)(void *,unsigned int)=set_source_api;
static int transport_send_api(unsigned int id,void *p){
 assert(id==FUNCTIONAL_CAMERA_CONTROL_AP && p==reply_wire && movie.verified);++send_calls;
 assert(native_movie_format_ticket_for(id,p)==event_transaction);
 assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==event_transaction);
 forbid_snapshot=1;
 if(synchronous_receive){void *message=p;native_cp_state_received(id,&message,0);}
 if(synchronous_free)assert(!actual_free(id,p));
 forbid_snapshot=0;return send_rc;
}
static int (*real_send_msg)(unsigned int,void *)=transport_send_api;
#define PEER_ALLOCATE(name) unsigned long long name(unsigned int id,void *p){(void)id;(void)p;assert(0);return 0;}
PEER_ALLOCATE(full_scalar_connection_observe_allocate)
PEER_ALLOCATE(full_adf_connection_observe_allocate)
PEER_ALLOCATE(full_pinmem_drawinfo_connection_observe_allocate)
static void native_face_sdk_observation(unsigned int kind,unsigned int id,void *p,unsigned int bytes,int result,void *caller){
 (void)id;(void)p;(void)bytes;(void)result;assert(kind==1 && caller);++sdk_calls;
}
#define INACTIVE_RECEIVE(name) static void name(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
INACTIVE_RECEIVE(native_crank_received)
INACTIVE_RECEIVE(native_startup_control_received)
INACTIVE_RECEIVE(native_still_format_received)
INACTIVE_RECEIVE(native_background_start_received)
INACTIVE_RECEIVE(native_histogram_received)
static void native_functional_face_received(unsigned int id,void *p){(void)id;(void)p;}
int functional_vdf_layout_stage_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){(void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;}
int functional_vdf_path_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){(void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;}
static int functional_camera_events_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
static int functional_jpeg_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){
 (void)id;(void)p;assert(io->allocate==real_allocate_msg);
 if(allocate_via_receive){
  assert(io->allocate==native_tracked_allocate_msg);++io_allocation_calls;
  io_allocation_rc=io->allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&io_allocated_reply,12,1);
  io_allocation_errno=errno;
 }
 return 0;
}
static int functional_mpr_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;(void)io;assert(0);return 0;}
static void functional_capture_observe_received(unsigned int id,void *p){(void)id;(void)p;}
void full_imaging_functional_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
int native_cp_state_publication_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
int native_functional_camera_parameter_release(unsigned int id,void *p,int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result,uint64_t transaction){
 (void)id;(void)p;(void)release;(void)logger;(void)result;(void)transaction;++parameter_release_calls;return 0;
}
int native_functional_camera_crank_release(unsigned int id,void *p,int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result,uint64_t transaction,const struct native_functional_camera_crank_receive *event){
 (void)id;(void)p;(void)release;(void)logger;(void)result;(void)transaction;(void)event;++crank_release_calls;return 0;
}
int native_functional_camera_movie_format_release(unsigned int id,void *p,int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result,uint64_t transaction,const struct native_functional_camera_movie_format_receive *event){
 assert(logger==record && result);
 if(event){
  assert(!release);++receive_calls;last_receive_transaction=transaction;receiver_tid=actual_tid();
  if(id==FUNCTIONAL_CAMERA_CONTROL_AP && p==reply_wire && transaction==event_transaction &&
     event->source==FUNCTIONAL_CAMERA_CONTROL_SID && event->bytes==12 && !movie.complete){receive_observed=1;*result=0;}
  else *result=-ESTALE;
  return 1;
 }
 assert(release==real_free_msg);++release_calls;last_free_transaction=transaction;free_tid=actual_tid();
 if(!transaction){
  if((p!=reply_wire && p!=request_wire) || movie.complete ||
     (p==request_wire && movie.request_freed && !movie.retained_request))return 0;
  *result=-ESTALE;return 1;
 }
 if(transaction!=event_transaction || movie.complete || id!=FUNCTIONAL_CAMERA_CONTROL_AP || p!=reply_wire || !receive_observed || free_tid!=sender_tid){*result=-ESTALE;return 1;}
 *result=release(id,p);
 if(!*result){movie.complete=movie.reply_freed=movie.reply_consumed=1;movie.retained_reply=NULL;}
 else movie.faults=1;
 return 1;
}
static int cp_movie_format_reserve_resources(void){assert(0);return -ENODATA;}
static int cp_movie_format_predecessors_ready(void){assert(0);return 0;}
int native_cp_movie_format_diagnostic_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,const struct native_cp_movie_format_diagnostic_guard *guard,int enabled,int *result){
 assert(enabled==1 && cp_movie_format_used==1 && id==NATIVE_CP_MOVIE_FORMAT_SID && p==request_wire);
 assert(io->allocate==real_allocate_msg && io->send==real_send_msg && guard->reserve==cp_movie_format_reserve_resources && guard->predecessor_ready==cp_movie_format_predecessors_ready);
 assert(!owner_calls && !model_calls);++legacy_calls;if(!legacy_handled)return 0;*result=legacy_rc;return 1;
}
int native_functional_camera_movie_format_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,const struct native_cp_state_publication_guard *guard,const struct native_functional_camera_movie_format_context *context,int enabled,int *result){
 assert(id==NATIVE_CP_MOVIE_FORMAT_SID && p==request_wire && enabled==1 && context);
 assert(io->allocate==native_movie_format_allocate && io->release==real_free_msg && io->set_source==real_set_source && io->send==native_movie_format_send);
 assert(io->size==real_msg_size && io->source==real_get_source && io->record==record);
 assert(guard->reserve==functional_cp_movie_format_reserve_resources && guard->release==full_vef_resources_unlock && guard->predecessor_ready==functional_cp_movie_format_predecessors_ready);
 assert(functional_cp_movie_format_used==1 && !resource_held);++owner_calls;captured_context=*context;
 assert(!memcmp(context,&expected_context,sizeof *context));
 if(!owner_handled)return 0;
 *result=owner_rc;if(*result)return 1;
 /* Mock only the owner's boundary: actual Main guards and snapshots supply context. */
 if(request_wire[8]!=5 || request_wire[9]!=1 || request_wire[10] || request_wire[12] || request_wire[13] || request_wire[14] || request_wire[15] || request_wire[16] || request_wire[17] || request_wire[18]!=1){*result=-ENOTSUP;return 1;}
 *result=guard->reserve();if(*result)return 1;
 if(!guard->predecessor_ready()){*result=-ENODATA;guard->release();return 1;}
 struct native_functional_camera_parameter_snapshot observed_bank={0};
 struct native_functional_camera_crank_snapshot observed_crank={0};
 native_functional_camera_parameter_snapshot(&observed_bank);native_functional_camera_crank_snapshot(&observed_crank);
 assert(!memcmp(context,&captured_context,sizeof *context));
 if(context->model_instance!=observed_bank.model_instance || context->bank_generation!=observed_bank.bank_generation || context->crank_generation!=observed_crank.crank_generation){*result=-ESTALE;guard->release();return 1;}
 ++before_calls;*result=before_rc;
 if(!*result){++model_calls;movie.model_called=1;movie.model_rc=model_rc;movie.model_committed=!model_rc;*result=model_rc;}
 if(!*result && (receipt_bytes!=240 || !receipt_valid))*result=-EPROTO;
 if(!*result){++after_calls;*result=after_rc;}
 if(*result){guard->release();return 1;}
 movie.verified=movie.owned=1;movie.request_pointer=movie.retained_request=p;movie.transaction=event_transaction;
 movie.origin.destination=id;movie.model_instance=context->model_instance;movie.bank_generation=context->bank_generation;movie.crank_generation=context->crank_generation;
 memcpy(movie.receipt,receipt240,240);sender_tid=actual_tid();movie.sender_tid=sender_tid;
 void *reply=NULL;int rc=io->allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&reply,12,1);
 if(!rc && reply){
  movie.reply_pointer=movie.allocation_pointer=movie.retained_reply=reply;
  memcpy(reply,request_wire,8);reply_wire[0]=1;reply_wire[1]=0;memcpy(reply_wire+8,"\0\xf0\0\0",4);
  io->set_source(reply,FUNCTIONAL_CAMERA_CONTROL_SID);rc=io->send(FUNCTIONAL_CAMERA_CONTROL_AP,reply);
 }
 if(!rc){
  rc=io->release(id,p);
  if(!rc){
   movie.request_freed=1;movie.retained_request=NULL;
   if(request_reuse_before_return){
    allocated_pointer=p;pthread_t thread;
    assert(!pthread_create(&thread,NULL,request_reuse_thread,NULL));assert(!pthread_join(thread,NULL));
   }
  }
 }
 if(rc || !reply){movie.faults=1;movie.retained_request=p;if(reply)movie.retained_reply=reply;}
 guard->release();expect_postdispatch_snapshot=arm_postdispatch_snapshot;
 if(postdispatch_pid_drift)++functional_cp_movie_format_ticket_pid;
 dispatch_return_locks=locks;*result=0;return 1;
}
static int control_init_calls,parameter_init_calls,crank_init_calls,movie_init_calls,still_init_calls,startup_init_calls,movie_init_rc;
static int same_name(const char *a,const char *b){return a && b && !strcmp(a,b);}
int native_functional_camera_control_owner_init(void){++control_init_calls;return 0;}
int native_functional_camera_parameter_owner_init(void){assert(control_init_calls==1);++parameter_init_calls;return 0;}
int native_functional_camera_crank_owner_init(void){assert(parameter_init_calls==1);++crank_init_calls;return 0;}
int native_functional_camera_movie_format_owner_init(void){assert(crank_init_calls==1 && !still_init_calls);++movie_init_calls;return movie_init_rc;}
/* Constructor compatibility only; no timecode business result is established. */
int full_bb_timecode_control_owner_init(void){return 0;}
int functional_still_format_owner_init(void){assert(movie_init_calls==1 && !movie_init_rc);++still_init_calls;return 0;}
int functional_startup_control_owner_init(void){assert(still_init_calls==1);++startup_init_calls;return 0;}

/* ACTUAL_MOVIE_MAIN_HELPERS */
static void bind_initial_allocator_slot(int available){
 native_real_allocate_msg=available?allocate_api:NULL;
/* ACTUAL_MOVIE_INITIAL_ALLOCATOR_SLOT */
}
static void bind_dlsym_allocator_slot(void){
 native_real_allocate_msg=allocate_api;
/* ACTUAL_MOVIE_DLSYM_ALLOCATOR_SLOT */
}
static void *request_reuse_thread(void *unused){
 (void)unused;assert(request_frees==1 && movie.request_freed && !movie.retained_request);
 reuse_tid=actual_tid();assert(reuse_tid!=sender_tid);
 assert(!osal_valloc_msg_wait(FUNCTIONAL_CAMERA_CONTROL_SID,&reused_request,20,1));
 assert(reused_request==request_wire && !native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,reused_request));
 return NULL;
}
static int actual_send(unsigned int id,void *message){
/* ACTUAL_MOVIE_ROUTE */
/* ACTUAL_STRICT4000_ROUTE */
 ++fallback_sends;return -999;
}
static int actual_free(unsigned int id,void *message){
 int vdf_result;
/* ACTUAL_MOVIE_FREE */
 return real_free_msg(id,message);
}
static void actual_init(const char *functional_profile){
/* ACTUAL_MOVIE_INIT */
}
static void ready(void){
 original_pid=getpid();functional_cp_movie_format_ticket_pid=functional_cp_crank_control_ticket_pid=(unsigned int)getpid();
 bind_initial_allocator_slot(1);assert(native_real_allocate_msg==allocate_api && real_allocate_msg==native_tracked_allocate_msg);
 proc.owner_pid=input.owner_pid=output.owner_pid=getpid();proc.configured=input.configured=output.configured=1;
 proc.clean_completion=input.clean_completion=output.clean_completion=proc.ap_consumed=input.ap_consumed=output.ap_consumed=1;
 proc.request_freed=input.request_freed=output.request_freed=proc.reply_freed=input.reply_freed=output.reply_freed=1;
 bank.owner_pid=crank.owner_pid=movie.owner_pid=getpid();bank.initialized=crank.initialized=movie.initialized=1;
 bank.model_called=bank.model_committed=bank.verified=bank.owned=bank.request_freed=1;
 bank.model_instance=77;bank.bank_generation=3;bank.transaction=7;bank.commits=bank.released=1;
 crank.model_called=crank.model_committed=crank.verified=crank.owned=crank.complete=1;
 crank.reply_received=crank.reply_consumed=crank.request_freed=crank.reply_freed=1;
 crank.requests=crank.commits=crank.verified_commits=crank.completions=1;
 crank.model_instance=77;crank.bank_generation=3;crank.crank_generation=9;crank.transaction=8;
 crank.bank_transaction=7;crank.bank_commits=crank.bank_released=1;
 crank.sender_tid=crank.request_free_tid=crank.reply_free_tid=62;crank.receiver_tid=57;
 cp_output_policy_state.owner_pid=getpid();policy.config_consumed=1;
 memcpy(bank.request+4,request_wire+4,4);memcpy(policy.bytes+4,request_wire+4,4);
 ee.owner_pid=getpid();ee.initialized=1;
 struct native_cp_ee_controls_diagnostic_lease *initial=&ee.leases[0];
 initial->opcode=0x409d;initial->attempts=initial->requests=initial->queued=1;
 initial->clean_completion=initial->ap_consumed=initial->request_freed=initial->reply_freed=1;
 initial->sender_tid=initial->waiter_tid=19;
 early.owner_pid=getpid();early.initialized=early.diagnostic_only=early.no_publication=1;
 early.opcode=0x4000;early.attempts=early.requests=early.queued=early.request_freed=early.reply_freed=early.clean_completion=early.ap_consumed=1;
 early.sender_tid=early.waiter_tid=382;early.source=early.destination=FUNCTIONAL_CAMERA_CONTROL_AP;
 early.request_destination=NATIVE_CP_MOVIE_FORMAT_SID;early.request_bytes=20;
 early.known_field_mask=early.virtual_field_mask=early.virtual_fields_consumed=CP_MOVIE_FORMAT_KNOWN_MASK;early.virtual_fields_readback=1;
 startup.owner_pid=still.owner_pid=getpid();startup.initialized=still.initialized=1;
 dmm.physical=DMM_TEST_PHYSICAL;dmm.slots[0].handle=0x41;dmm.slots[1].handle=0x42;
 for(size_t i=0;i<sizeof receipt240;i++)receipt240[i]=(unsigned char)(i^0xa7u);
}
static void seed_ticket(void){
 functional_cp_movie_format_used=1;movie.owned=movie.verified=1;movie.transaction=event_transaction;
 movie.request_pointer=request_wire;movie.reply_pointer=reply_wire;movie.origin.destination=FUNCTIONAL_CAMERA_CONTROL_SID;
 functional_cp_movie_format_ticket.request=request_wire;functional_cp_movie_format_ticket.reply=reply_wire;
 functional_cp_movie_format_ticket.request_destination=FUNCTIONAL_CAMERA_CONTROL_SID;
 functional_cp_movie_format_ticket.reply_destination=FUNCTIONAL_CAMERA_CONTROL_AP;
 functional_cp_movie_format_ticket.transaction=event_transaction;sender_tid=actual_tid();
}
static void receive_reply(unsigned int destination,void *pointer){
 void *message=pointer;forbid_snapshot=1;native_cp_state_received(destination,&message,0);forbid_snapshot=0;
}
static void *transport_thread(void *unused){(void)unused;receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);return NULL;}
static void *foreign_free_thread(void *unused){(void)unused;assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE);return NULL;}
static void check_route(const char *test){
 int expected=0,delegated=0,called=1;unsigned int id=NATIVE_CP_MOVIE_FORMAT_SID;void *message=request_wire;
 if(!strcmp(test,"cold")){bank.model_called=crank.model_called=0;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"cold-fault-no-model")){bank.model_called=crank.model_called=0;bank.faults=crank.faults=1;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"disabled")){functional_camera_enabled=0;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"cold-strict-unhandled")){bank.model_called=crank.model_called=0;legacy_handled=0;expected=-999;delegated=1;called=0;}
 else if(!strcmp(test,"short")){message_bytes=19;expected=-EMSGSIZE;called=0;}
 else if(!strcmp(test,"long")){message_bytes=21;expected=-EMSGSIZE;called=0;}
 else if(!strcmp(test,"prefix-only")){message_bytes=4;expected=-EMSGSIZE;called=0;}
 else if(!strcmp(test,"truncated-prefix")){message_bytes=3;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"other-type")){request_wire[0]=6;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"other-command")){request_wire[2]=1;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"other-id")){id++;expected=-999;called=0;}
 else if(!strcmp(test,"null-message")){message=NULL;cp_movie_format_enabled=0;expected=-999;called=0;}
 else if(!strcmp(test,"missing-size")){real_msg_size=NULL;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"source-error")){message_source++;expected=-EPERM;called=0;}
 else if(!strcmp(test,"missing-source")){real_get_source=NULL;expected=-EPERM;called=0;}
 else if(!strcmp(test,"setup-error")){functional_camera_setup_error=-ELIBBAD;expected=-ELIBBAD;called=0;}
 else if(!strcmp(test,"bridge-error")){bridge_rc=-EIO;expected=-EIO;called=0;}
 else if(!strcmp(test,"owner-unhandled")){owner_handled=0;expected=-ENOTSUP;}
 else if(!strcmp(test,"owner-error")){owner_rc=-ESTALE;expected=-ESTALE;}
 else if(!strcmp(test,"format-error")){request_wire[8]=6;expected=-ENOTSUP;}
 else if(!strcmp(test,"raw-rate-error")){request_wire[10]=1;expected=-ENOTSUP;}
 else if(!strcmp(test,"before-error")){before_rc=-EIO;expected=-EIO;}
 else if(!strcmp(test,"model-error")){model_rc=-EUCLEAN;expected=-EUCLEAN;}
 else if(!strcmp(test,"receipt-short")){receipt_bytes--;expected=-EPROTO;}
 else if(!strcmp(test,"receipt-mutated")){receipt_valid=0;expected=-EPROTO;}
 else if(!strcmp(test,"after-error")){after_rc=-ESTALE;expected=-ESTALE;}
 else if(!strcmp(test,"predecessor")){predecessor_ready=0;expected=-ENODATA;}
 else if(!strcmp(test,"late-bank-only")){crank.model_called=0;}
 else if(!strcmp(test,"late-crank-only")){bank.model_called=0;}
 else if(!strcmp(test,"late-used-only")){bank.model_called=crank.model_called=0;functional_cp_movie_format_used=1;}
 else if(!strcmp(test,"opaque-fields")){request_wire[1]=0xa5;request_wire[4]^=0x19;request_wire[11]=0xfe;request_wire[19]=0x87;}
 else if(!strcmp(test,"context-current-values")){
  bank.model_instance=crank.model_instance=UINT64_C(0x110000004d);
  bank.bank_generation=crank.bank_generation=UINT64_C(0x2100000003);crank.crank_generation=UINT64_C(0x3100000009);
 }
 else if(!strcmp(test,"context-instance-drift")){context_drift=1;expected=-ESTALE;}
 else if(!strcmp(test,"context-bank-drift")){context_drift=2;expected=-ESTALE;}
 else if(!strcmp(test,"context-crank-drift")){context_drift=3;expected=-ESTALE;}
 else if(!strcmp(test,"context-reserve-drift")){context_drift=4;expected=-ESTALE;}
 else if(!strcmp(test,"resource-error")){resource_rc=-EBUSY;expected=-EBUSY;}
 else if(!strcmp(test,"allocate-error")){allocation_rc=-ENOMEM;transport_failure=1;}
 else if(!strcmp(test,"send-error")){send_rc=-EIO;transport_failure=2;}
 else if(!strcmp(test,"request-free-error")){free_rc=-EACCES;transport_failure=3;}
 else if(!strcmp(test,"synchronous"))synchronous_receive=synchronous_free=1;
 else assert(!strcmp(test,"late"));
 expected_context=(struct native_functional_camera_movie_format_context){bank.model_instance,bank.bank_generation,crank.crank_generation};
 struct native_cp_movie_format_diagnostic_snapshot early_before=early;
 struct native_cp_ee_controls_diagnostic_snapshot ee_before=ee;
 assert(actual_send(id,message)==expected && owner_calls==called && legacy_calls==delegated);
 assert(!memcmp(&early,&early_before,sizeof early) && !memcmp(&ee,&ee_before,sizeof ee));
 assert(fallback_sends==(expected==-999));
 assert(functional_cp_movie_format_used==(unsigned int)called);
 if(called)assert(!memcmp(&captured_context,&expected_context,sizeof captured_context));
 if(expected){
  assert(!allocation_calls && !send_calls && !request_frees && !reply_frees);
  if(context_drift)assert(resource_calls==1 && resource_unlocks==1 && !before_calls && !model_calls && !after_calls);
  if(!strcmp(test,"model-error"))assert(model_calls==1 && movie.model_called && !movie.model_committed);
  if(!strcmp(test,"receipt-short") || !strcmp(test,"receipt-mutated") || !strcmp(test,"after-error"))assert(model_calls==1 && movie.model_committed);
 }else{
  assert(before_calls==1 && model_calls==1 && after_calls==1 && allocation_calls==1);
  assert(send_calls==(transport_failure!=1) && request_frees==(!transport_failure || transport_failure==3));
  assert(bridge_calls==1 && resource_calls==1 && resource_unlocks==1 && !legacy_calls);
  assert(movie_reserved_tags==1 && movie_tts_tags==1 && !movie_refused_tags && !movie_fault_tags);
  assert(!memcmp(movie.receipt,receipt240,240));
  if(transport_failure){
   assert(movie.owned && movie.faults && movie.retained_request==request_wire && !movie.complete);
   assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==event_transaction);
  }else{
   assert(reply_wire[0]==1 && reply_wire[1]==0 && !memcmp(reply_wire+4,request_wire+4,4));
   assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
  }
  if(synchronous_free)assert(receive_calls==1 && release_calls==1 && movie.complete && reply_frees==1);
 }
}
#define MUTATE(label,expression) if(!strcmp(test,label)){expression;return;}
static void mutate_predecessor(const char *test){
 MUTATE("all13-current-mode",predecessor_ready=0)
 MUTATE("policy-error",policy_rc=-EIO)
 MUTATE("policy-cookie",policy.bytes[4]^=1)
 MUTATE("initial409d-repeat",ee.leases[0].attempts++)
 MUTATE("bank-owner",bank.owner_pid++)
 MUTATE("bank-init",bank.initialized=0)
 MUTATE("bank-commit",bank.model_committed=0)
 MUTATE("bank-verified",bank.verified=0)
 MUTATE("bank-owned",bank.owned=0)
 MUTATE("bank-free",bank.request_freed=0)
 MUTATE("bank-busy",bank.busy=1)
 MUTATE("bank-guard",bank.guard_held=1)
 MUTATE("bank-fault",bank.faults=1)
 MUTATE("bank-releasing",bank.releasing=1)
 MUTATE("bank-retained",bank.retained_request=request_wire)
 MUTATE("bank-instance",bank.model_instance=0)
 MUTATE("bank-generation",bank.bank_generation=0)
 MUTATE("bank-transaction",bank.transaction=0)
 MUTATE("crank-owner",crank.owner_pid++)
 MUTATE("crank-init",crank.initialized=0)
 MUTATE("crank-commit",crank.model_committed=0)
 MUTATE("crank-verified",crank.verified=0)
 MUTATE("crank-owned",crank.owned=0)
 MUTATE("crank-complete",crank.complete=0)
 MUTATE("crank-instance",crank.model_instance++)
 MUTATE("crank-bank-generation",crank.bank_generation++)
 MUTATE("crank-bank-transaction",crank.bank_transaction++)
 MUTATE("crank-bank-commits",crank.bank_commits++)
 MUTATE("crank-bank-released",crank.bank_released++)
 MUTATE("crank-transaction",crank.transaction=0)
 MUTATE("crank-generation",crank.crank_generation=0)
 MUTATE("crank-completions",crank.completions=0)
 MUTATE("crank-counts",crank.requests++)
 MUTATE("crank-verified-count",crank.verified_commits++)
 MUTATE("crank-receive",crank.reply_received=0)
 MUTATE("crank-consume",crank.reply_consumed=0)
 MUTATE("crank-request-free",crank.request_freed=0)
 MUTATE("crank-reply-free",crank.reply_freed=0)
 MUTATE("crank-sender",crank.sender_tid=0)
 MUTATE("crank-receiver",crank.receiver_tid=0)
 MUTATE("crank-request-free-tid",crank.request_free_tid++)
 MUTATE("crank-reply-free-tid",crank.reply_free_tid++)
 MUTATE("crank-busy",crank.busy=1)
 MUTATE("crank-guard",crank.guard_held=1)
 MUTATE("crank-fault",crank.faults=1)
 MUTATE("crank-before-rc",crank.before_rc=-EIO)
 MUTATE("crank-model-rc",crank.model_rc=-EIO)
 MUTATE("crank-after-rc",crank.after_rc=-EIO)
 MUTATE("crank-allocate-rc",crank.allocate_rc=-EIO)
 MUTATE("crank-send-rc",crank.send_rc=-EIO)
 MUTATE("crank-request-free-rc",crank.request_free_rc=-EIO)
 MUTATE("crank-reply-free-rc",crank.reply_free_rc=-EIO)
 MUTATE("crank-receive-rc",crank.receive_rc=-EIO)
 MUTATE("crank-request-releasing",crank.request_releasing=1)
 MUTATE("crank-reply-releasing",crank.reply_releasing=1)
 MUTATE("crank-inspecting",crank.reply_inspecting=1)
 MUTATE("crank-send-inflight",crank.send_inflight=1)
 MUTATE("crank-retained-request",crank.retained_request=request_wire)
 MUTATE("crank-retained-reply",crank.retained_reply=reply_wire)
 MUTATE("strict-owner",early.owner_pid++)
 MUTATE("strict-init",early.initialized=0)
 MUTATE("strict-opcode",early.opcode++)
 MUTATE("strict-attempts",early.attempts++)
 MUTATE("strict-requests",early.requests++)
 MUTATE("strict-queued",early.queued=0)
 MUTATE("strict-request-free",early.request_freed=0)
 MUTATE("strict-reply-free",early.reply_freed=0)
 MUTATE("strict-clean",early.clean_completion=0)
 MUTATE("strict-consumed",early.ap_consumed=0)
 MUTATE("strict-sender",early.sender_tid=0)
 MUTATE("strict-waiter",early.waiter_tid++)
 MUTATE("strict-allocate-rc",early.allocate_rc=-EIO)
 MUTATE("strict-send-rc",early.send_rc=-EIO)
 MUTATE("strict-request-free-rc",early.request_free_rc=-EIO)
 MUTATE("strict-reply-free-rc",early.reply_free_rc=-EIO)
 MUTATE("strict-busy",early.busy=1)
 MUTATE("strict-guard",early.guard_held=1)
 MUTATE("strict-fault",early.faults=1)
 MUTATE("strict-retained-request",early.retained_request=request_wire)
 MUTATE("strict-live-reply",early.live_reply=reply_wire)
 MUTATE("strict-retained-cleanup",early.retained_cleanup=reply_wire)
 MUTATE("strict-source",early.source++)
 MUTATE("strict-request-destination",early.request_destination++)
 MUTATE("strict-destination",early.destination++)
 MUTATE("strict-request-bytes",early.request_bytes--)
 MUTATE("strict-known-mask",early.known_field_mask--)
 MUTATE("strict-virtual-mask",early.virtual_field_mask--)
 MUTATE("strict-readback",early.virtual_fields_readback=0)
 MUTATE("strict-fields-consumed",early.virtual_fields_consumed--)
 MUTATE("strict-readback-bytes",early.virtual_readback[6]++)
 assert(!strcmp(test,"ready") || !strcmp(test,"historical-sender"));
}
#undef MUTATE
static void check_predecessor(const char *test){
 mutate_predecessor(test);
 struct native_functional_camera_parameter_snapshot saved_bank=bank;
 struct native_functional_camera_crank_snapshot saved_crank=crank;
 struct native_cp_movie_format_diagnostic_snapshot saved_early=early;
 struct native_cp_ee_controls_diagnostic_snapshot saved_ee=ee;
 struct cp_output_policy_snapshot saved_policy=policy;
 int expected=!strcmp(test,"ready") || !strcmp(test,"historical-sender");
 assert(functional_cp_movie_format_predecessors_ready()==expected);
 assert(!memcmp(&bank,&saved_bank,sizeof bank) && !memcmp(&crank,&saved_crank,sizeof crank));
 assert(!memcmp(&early,&saved_early,sizeof early) && !memcmp(&ee,&saved_ee,sizeof ee) && !memcmp(&policy,&saved_policy,sizeof policy));
 assert(!resource_calls && !bridge_calls && !owner_calls && !model_calls && !request_frees && !reply_frees);
 if(expected)assert(early.sender_tid!=actual_tid() && crank.sender_tid!=early.sender_tid && crank.receiver_tid!=crank.sender_tid);
}
static void check_resource(const char *test,int requester){
 functional_cp_movie_format_used=1;int expected=0;
 if(!strcmp(test,"idle")){}
 else if(!strcmp(test,"movie-busy")){movie.busy=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-owner")){movie.owner_pid++;expected=-ENODATA;}
 else if(!strcmp(test,"movie-init")){movie.initialized=0;expected=-ENODATA;}
 else if(!strcmp(test,"movie-guard")){movie.guard_held=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-fault")){movie.faults=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-retained-request")){movie.retained_request=request_wire;expected=-ENODATA;}
 else if(!strcmp(test,"movie-retained-reply")){movie.retained_reply=reply_wire;expected=-ENODATA;}
 else if(!strcmp(test,"movie-request-releasing")){movie.request_releasing=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-reply-releasing")){movie.reply_releasing=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-inspecting")){movie.reply_inspecting=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-send-inflight")){movie.send_inflight=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-owned-live")){movie.owned=1;expected=-ENODATA;}
 else if(!strcmp(test,"movie-complete")){movie.owned=movie.complete=movie.reply_received=movie.reply_consumed=movie.request_freed=movie.reply_freed=1;}
 else if(!strcmp(test,"unused")){functional_cp_movie_format_used=0;movie.faults=1;}
 else if(!strcmp(test,"selfskip")){assert(requester==35);movie.owner_pid++;movie.initialized=0;movie.busy=movie.faults=movie.owned=movie.guard_held=1;movie.retained_reply=reply_wire;}
 else if(!strcmp(test,"bank-live")){functional_cp_parameter_bank_used=1;bank.request_freed=0;expected=-ENODATA;}
 else if(!strcmp(test,"crank-live")){functional_cp_crank_control_used=1;crank.complete=0;expected=-ENODATA;}
 else if(!strcmp(test,"startup-live")){functional_startup_control_used=1;startup.busy=1;expected=-ENODATA;}
 else if(!strcmp(test,"still-live")){functional_still_format_used=1;still.busy=1;expected=-ENODATA;}
 else if(!strcmp(test,"proc-live")){proc.busy=1;expected=-1021;}
 else if(!strcmp(test,"input-retained")){input.retained_request=request_wire;expected=-1021;}
 else if(!strcmp(test,"output-fault")){output.faults=1;expected=-1021;}
 else if(!strcmp(test,"lock-error")){resource_rc=-EBUSY;expected=-EBUSY;}
 else if(!strcmp(test,"dmm-empty")){resource_domain=FULL_VEF_DMM_EMPTY;expected=-1021;}
 else if(!strcmp(test,"inadmissible")){resource_admissible=0;expected=-1021;}
 else if(!strcmp(test,"invalid-low") || !strcmp(test,"invalid-high")){expected=-1021;}
 else assert(0);
 struct native_functional_camera_movie_format_snapshot saved=movie;
 assert(tracked_native_reserve_resources(requester)==expected && !memcmp(&movie,&saved,sizeof movie));
 assert(!bridge_calls && !model_calls && !allocation_calls && !send_calls);
 int reads=requester>=0 && requester<38 && requester!=35 && functional_cp_movie_format_used;assert(movie_reads==reads);
 if(!expected){assert(resource_calls==1 && resource_held);full_vef_resources_unlock();}
 else assert(!resource_held);
 if(expected==-ENODATA)assert(!resource_calls);
 if(requester==35){
  if(!expected)assert(movie_reserved_tags==1 && movie_tts_tags==1);
  if(expected==-ENODATA)assert(movie_refused_tags==1);
  if(resource_rc)assert(movie_fault_tags==1 && !movie_tts_tags);
 }
}
static void check_allocation(const char *test){
 seed_ticket();movie.complete=1;unsigned int count=1,id=FUNCTIONAL_CAMERA_CONTROL_AP;void *out=NULL;int expected_clear=1;
 functional_cp_parameter_bank_ticket.pointer=reply_wire;functional_cp_parameter_bank_ticket.transaction=11;
 functional_cp_crank_control_used=1;functional_cp_crank_control_ticket.reply=reply_wire;functional_cp_crank_control_ticket.transaction=12;
 if(!strcmp(test,"failed")){allocation_rc=-ENOMEM;expected_clear=0;}
 else if(!strcmp(test,"multi")){count=2;expected_clear=0;}
 else if(!strcmp(test,"null")){allocation_null=1;expected_clear=0;}
 else if(!strcmp(test,"foreign")){allocated_pointer=foreign_wire;expected_clear=0;}
 else if(!strcmp(test,"unused")){functional_cp_movie_format_used=0;expected_clear=0;}
 else if(!strcmp(test,"borrowed"))id=0x912503d0;
 else if(!strcmp(test,"request-reuse"))allocated_pointer=request_wire;
 else assert(!strcmp(test,"reuse"));
 assert(osal_valloc_msg_wait(id,&out,20,count)==allocation_rc && allocation_calls==1);
 if(!strcmp(test,"request-reuse")){
  assert(!functional_cp_movie_format_ticket.request && functional_cp_movie_format_ticket.reply==reply_wire && functional_cp_movie_format_ticket.transaction==event_transaction);
 }else{
  assert((functional_cp_movie_format_ticket.reply==NULL)==expected_clear);
  int others_clear=!allocation_rc && count==1 && !allocation_null && allocated_pointer==reply_wire;
  assert((functional_cp_parameter_bank_ticket.pointer==NULL)==others_clear && (functional_cp_crank_control_ticket.reply==NULL)==others_clear);
  if(expected_clear)assert(!native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
  else assert(functional_cp_movie_format_ticket.transaction==event_transaction);
 }
 assert(!movie_reads && !bank_reads && !crank_reads && !send_calls && !owner_calls);
}
static void check_adapter(const char *test){
 seed_ticket();
 if(!strcmp(test,"allocate-captured-snapshot")){
  movie.transaction=event_transaction+2;uint64_t captured=movie.transaction;allocation_drift=1;
  void *pointer=NULL;assert(!native_movie_format_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&pointer,12,1));
  assert(pointer==reply_wire && allocation_calls==1 && movie.transaction==captured+1);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,pointer)==captured);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==captured);
 }else if(!strncmp(test,"allocate-",9)){
  void *pointer=NULL;
  if(!strcmp(test,"allocate-unowned"))movie.owned=0;
  else if(!strcmp(test,"allocate-unverified"))movie.verified=0;
  else if(!strcmp(test,"allocate-no-api"))real_allocate_msg=NULL;
  else if(!strcmp(test,"allocate-zero-transaction"))movie.transaction=0;
  else assert(0);
  assert(native_movie_format_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&pointer,12,1)==-ESTALE && !pointer && !allocation_calls);
 }else{
  unsigned int destination=FUNCTIONAL_CAMERA_CONTROL_AP;
  if(!strcmp(test,"send-missing-ticket"))functional_cp_movie_format_ticket.reply=NULL;
  else if(!strcmp(test,"send-wrong-destination"))destination++;
  else if(!strcmp(test,"send-stale-transaction"))movie.transaction++;
  else if(!strcmp(test,"send-unverified"))movie.verified=0;
  else if(!strcmp(test,"send-unowned"))movie.owned=0;
  else if(!strcmp(test,"send-foreign-pointer"))movie.reply_pointer=foreign_wire;
  else if(!strcmp(test,"send-no-api"))real_send_msg=NULL;
  else assert(0);
  assert(native_movie_format_send(destination,reply_wire)==-ESTALE && !send_calls && !allocation_calls);
 }
 assert(movie_reads==1 && !bank_reads && !crank_reads && !owner_calls && !model_calls);
}
static void check_ticket(const char *test){
 seed_ticket();
 if(!strcmp(test,"cross-receive")){
  pthread_t thread;assert(!pthread_create(&thread,NULL,transport_thread,NULL));assert(!pthread_join(thread,NULL));
  assert(receiver_tid!=sender_tid && last_receive_transaction==event_transaction && receive_observed);
  movie.transaction++;forbid_snapshot=1;assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));forbid_snapshot=0;
  assert(free_tid==sender_tid && last_free_transaction==event_transaction && reply_frees==1);
 }else if(!strcmp(test,"wrong-free-thread")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);pthread_t thread;
  assert(!pthread_create(&thread,NULL,foreign_free_thread,NULL));assert(!pthread_join(thread,NULL));
  assert(!reply_frees && last_free_transaction==event_transaction);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
 }else if(!strcmp(test,"wrong-destination")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP+1,reply_wire);assert(!last_receive_transaction && !receive_observed);
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP+1,reply_wire)==-ESTALE && !reply_frees);
 }else if(!strcmp(test,"receive-source")){
  reply_source++;receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!receive_observed);
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE && !reply_frees);
 }else if(!strcmp(test,"receive-bytes")){
  reply_bytes--;receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!receive_observed);
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE && !reply_frees);
 }else if(!strcmp(test,"foreign-pointer")){
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,foreign_wire) && !last_free_transaction && ordinary_frees==1);
 }else if(!strcmp(test,"stale")){
  event_transaction++;assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE && last_free_transaction==event_transaction-1 && !reply_frees);
 }else if(!strcmp(test,"completed-duplicate")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE && reply_frees==1);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
 }else if(!strcmp(test,"free-error")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);free_rc=-EIO;
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-EIO && !movie.complete && movie.faults);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
 }else if(!strcmp(test,"receive-failure")){
  void *p=reply_wire;native_cp_state_received(FUNCTIONAL_CAMERA_CONTROL_AP,&p,-EAGAIN);assert(!receive_calls);
 }else if(!strcmp(test,"free-before-receive")){
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE && !reply_frees && !receive_observed);
 }else if(!strcmp(test,"reuse-after-complete")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
  void *p=NULL;assert(!osal_valloc_msg_wait(FUNCTIONAL_CAMERA_CONTROL_AP,&p,12,1) && p==reply_wire);
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,p) && reply_frees==2 && !last_free_transaction);
 }else if(!strcmp(test,"wrong-pid")){
  functional_cp_movie_format_ticket_pid++;int before=locks;void *p=reply_wire;
  assert(!native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,p));native_movie_format_allocated(FUNCTIONAL_CAMERA_CONTROL_AP,&p,0,1);
  assert(native_movie_format_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&p,12,1)==-ESTALE);
  assert(native_movie_format_send(FUNCTIONAL_CAMERA_CONTROL_AP,p)==-ESTALE && locks==before && functional_cp_movie_format_ticket.reply==reply_wire);
 }else if(!strcmp(test,"fork-before-lock")){
  hold_fork_lock();pid_t child=fork();assert(child>=0);
  if(!child){
   int before=locks;void *p=reply_wire;assert(!native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,p));
   native_movie_format_allocated(FUNCTIONAL_CAMERA_CONTROL_AP,&p,0,1);
   assert(native_movie_format_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&p,12,1)==-ESTALE);
   assert(native_movie_format_send(FUNCTIONAL_CAMERA_CONTROL_AP,p)==-ESTALE && locks==before);
   assert(functional_cp_movie_format_ticket.reply==reply_wire);_exit(0);
  }
  drop_fork_lock();int status=-1;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 }else assert(0);
 assert(!bank_reads && !crank_reads && !owner_calls && !model_calls);
 if(strcmp(test,"wrong-pid"))assert(!movie_reads);
}
static void check_rootfix(const char *test){
 if(!strcmp(test,"io-reply-reuse")){
  assert(!actual_send(NATIVE_CP_MOVIE_FORMAT_SID,request_wire));
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
  assert(movie.complete && movie.request_freed && request_frees==1 && reply_frees==1);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
  int before=allocation_calls;raw_errno=ERANGE;clobber_ticket_errno=1;allocate_via_receive=1;
  void *message=foreign_wire;native_cp_state_received(FUNCTIONAL_CAMERA_CONTROL_AP,&message,0);allocate_via_receive=0;
  assert(io_allocation_calls==1 && !io_allocation_rc && io_allocation_errno==ERANGE);
  assert(io_allocated_reply==reply_wire && allocation_calls==before+1);
  assert(!native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,io_allocated_reply));
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,io_allocated_reply);
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,io_allocated_reply));
  assert(reply_frees==2 && request_frees==1 && !last_free_transaction);return;
 }
 if(!strcmp(test,"postdispatch-fork-before-lock")){
  hold_fork_lock();pid_t child=fork();assert(child>=0);
  if(!child){
   int before=locks;owner_rc=-EIO;
   assert(actual_send(NATIVE_CP_MOVIE_FORMAT_SID,request_wire)==-EIO);
   assert(owner_calls==1 && !movie_reads && locks==before && !allocation_calls);_exit(0);
  }
  drop_fork_lock();int status=-1;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));return;
 }
 if(!strcmp(test,"request-reuse-before-return"))request_reuse_before_return=1;
 else if(!strcmp(test,"request-retained-before-return"))allocation_rc=-ENOMEM;
 else if(!strcmp(test,"postdispatch-pid-mismatch"))postdispatch_pid_drift=1;
 else assert(0);
 arm_postdispatch_snapshot=1;
 assert(!actual_send(NATIVE_CP_MOVIE_FORMAT_SID,request_wire));
 if(postdispatch_pid_drift){assert(locks==dispatch_return_locks && !postdispatch_snapshots);return;}
 assert(postdispatch_snapshots==1);
 if(request_reuse_before_return){
  assert(reuse_tid!=sender_tid && reused_request==request_wire && allocation_calls==2);
  assert(movie.request_pointer==request_wire && movie.request_freed && !movie.retained_request);
  assert(!native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,reused_request));
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_SID,reused_request) && request_frees==2 && !last_free_transaction);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
 }else{
  assert(movie.retained_request==request_wire && !movie.request_freed && movie.faults && !request_frees);
  assert(native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==event_transaction);
 }
}
static void check_shared_allocator(const char *test){
 seed_ticket();movie.complete=1;
 unsigned char saved_ticket[sizeof functional_cp_movie_format_ticket];
 memcpy(saved_ticket,&functional_cp_movie_format_ticket,sizeof saved_ticket);
 void *out=NULL;void **output=&out;unsigned int count=1;int expected_clear=1;
 raw_errno=ERANGE;clobber_ticket_errno=1;
 if(!strcmp(test,"negative-rc")){allocation_rc=-ENOMEM;expected_clear=0;}
 else if(!strcmp(test,"positive-rc")){allocation_rc=7;expected_clear=0;}
 else if(!strcmp(test,"null-out")){output=NULL;expected_clear=0;}
 else if(!strcmp(test,"null-message")){allocation_null=1;expected_clear=0;}
 else if(!strcmp(test,"multi-count")){count=2;expected_clear=0;}
 else if(!strcmp(test,"foreign-pointer")){allocated_pointer=foreign_wire;expected_clear=0;}
 else if(!strcmp(test,"unused")){functional_cp_movie_format_used=0;expected_clear=0;}
 else if(!strcmp(test,"pid-mismatch")){++functional_cp_movie_format_ticket_pid;expected_clear=0;}
 else if(!strcmp(test,"missing-raw")){
  bind_initial_allocator_slot(0);assert(!native_real_allocate_msg && !real_allocate_msg);
  assert(native_movie_format_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&out,12,1)==-ESTALE && !out && !allocation_calls);
  assert(!memcmp(saved_ticket,&functional_cp_movie_format_ticket,sizeof saved_ticket));return;
 }else if(!strcmp(test,"dlsym-slot"))bind_dlsym_allocator_slot();
 else if(!strcmp(test,"fork-before-lock")){
  hold_fork_lock();pid_t child=fork();assert(child>=0);
  if(!child){
   int before=locks;errno=EDOM;
   assert(!real_allocate_msg(FUNCTIONAL_CAMERA_CONTROL_AP,&out,12,1));
   assert(out==reply_wire && allocation_calls==1 && errno==ERANGE && locks==before);
   assert(!memcmp(saved_ticket,&functional_cp_movie_format_ticket,sizeof saved_ticket));_exit(0);
  }
  drop_fork_lock();int status=-1;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
  assert(!allocation_calls && !memcmp(saved_ticket,&functional_cp_movie_format_ticket,sizeof saved_ticket));return;
 }else assert(!strcmp(test,"success"));
 assert(native_real_allocate_msg==allocate_api && real_allocate_msg==native_tracked_allocate_msg);
 int before=locks;errno=EDOM;int rc=real_allocate_msg(FUNCTIONAL_CAMERA_CONTROL_AP,output,12,count),observed_errno=errno;
 assert(rc==allocation_rc && observed_errno==ERANGE && allocation_calls==1);
 if(expected_clear){
  assert(!functional_cp_movie_format_ticket.reply && !functional_cp_movie_format_ticket.reply_destination);
  assert(functional_cp_movie_format_ticket.request==request_wire && functional_cp_movie_format_ticket.transaction==event_transaction);
  assert(!native_movie_format_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
 }else{
  assert(!memcmp(saved_ticket,&functional_cp_movie_format_ticket,sizeof saved_ticket));
  if(strcmp(test,"foreign-pointer"))assert(locks==before);
 }
 assert(!movie_reads && !bank_reads && !crank_reads && !owner_calls && !model_calls && !request_frees && !reply_frees);
}
int main(int argc,char **argv){
 assert(argc>=3);ready();
 if(!strcmp(argv[1],"rootfix"))check_rootfix(argv[2]);
 else if(!strcmp(argv[1],"shared-allocator"))check_shared_allocator(argv[2]);
 else if(!strcmp(argv[1],"route"))check_route(argv[2]);
 else if(!strcmp(argv[1],"predecessor"))check_predecessor(argv[2]);
 else if(!strcmp(argv[1],"resource")){assert(argc==4);check_resource(argv[2],atoi(argv[3]));}
 else if(!strcmp(argv[1],"allocation"))check_allocation(argv[2]);
 else if(!strcmp(argv[1],"adapter"))check_adapter(argv[2]);
 else if(!strcmp(argv[1],"ticket"))check_ticket(argv[2]);
 else if(!strcmp(argv[1],"init")){
  const char *profile=FCAM_PROFILE;
  if(!strcmp(argv[2],"movie-error"))movie_init_rc=-ENOMEM;
  else if(!strcmp(argv[2],"disabled"))profile=NULL;
  else if(!strcmp(argv[2],"wrong-profile"))profile="wrong";
  else if(!strcmp(argv[2],"no-owned-state"))cp_owned_state_enabled=0;
  else assert(!strcmp(argv[2],"local"));
  actual_init(profile);int selected=profile && !strcmp(profile,FCAM_PROFILE) && cp_owned_state_enabled;
  assert(control_init_calls==selected && parameter_init_calls==selected && crank_init_calls==selected && movie_init_calls==selected);
  assert(still_init_calls==(selected && !movie_init_rc) && startup_init_calls==still_init_calls);
  assert(functional_camera_enabled==(selected && !movie_init_rc) && functional_cp_movie_format_ticket_pid==(unsigned int)getpid());
  assert(!bridge_calls && !model_calls && !allocation_calls && !send_calls);
 }else assert(0);
 assert(locks==unlocks && !batch_held && !cap_held && !resource_held);
 puts("PASS actual Main movie-format wiring MOCK; Core/native AP/capture unverified");return 0;
}
