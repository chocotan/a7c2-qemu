/* SPDX-License-Identifier: MIT
 * Actual Main extraction harness. Owner/Core/resource snapshots are explicit mocks.
 * Draft only: no original AP, physical ASIC, media or capture success claim.
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
static unsigned int functional_bb_timecode_audit_pid;

/* ACTUAL_TICKET_DECLARATIONS */
static int functional_camera_enabled=1,cp_owned_state_enabled=1,functional_camera_setup_error;
static unsigned int functional_cp_parameter_bank_used;
static unsigned int functional_cp_movie_format_used,functional_cp_movie_format_ticket_pid;
static unsigned int functional_still_format_used,functional_startup_control_used;
static unsigned int functional_layout_stage_used,functional_vdf_path_used,functional_mpr_codec_used;
static unsigned int still_format_ticket_pid,startup_control_ticket_pid;
static struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_layout_stage_ticket,functional_vdf_ticket;
static struct native_functional_camera_crank_snapshot crank;
static struct native_functional_camera_parameter_snapshot bank;
static struct native_cp_ee_controls_diagnostic_snapshot ee;
static struct cp_output_policy cp_output_policy_state;
static struct cp_output_policy_snapshot policy;
static unsigned long cp_parameter_batch_mutex[6],cap_lock[6],lens_pool_lock[6];
static void *cp_parameter_batch_retained_request;
static int original_pid,forbid_snapshot,crank_snapshots,bank_snapshots,locks,unlocks;
static pthread_mutex_t ticket_lock=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local int crank_ticket_held;
static int request_reuse_before_return,postdispatch_pid_drift,arm_postdispatch_snapshot,expect_postdispatch_snapshot,postdispatch_snapshots,dispatch_return_locks;
static void *reused_request;
static long reuse_tid;
static int batch_held,cap_held,resource_held,resource_calls,resource_unlocks,predecessor_ready=1;
static int ready_reads,resource_rc,bridge_calls,bridge_rc,owner_calls,owner_handled=1,owner_rc;
static int before_calls,model_calls,after_calls,before_rc,model_rc,after_rc,receipt_bytes=208,receipt_valid=1;
static int consumed_before_reply,request_frees,reply_frees,ordinary_frees,free_rc,send_rc;
static int allocation_calls,allocation_rc,allocation_null,allocation_snapshot_drift,send_calls,synchronous_receive,synchronous_free;
static int legacy_calls,legacy_rc=-777,fallback_sends,receive_calls,release_calls,parameter_releases;
static int receive_observed,release_override,complete,used_reads,sdk_calls,strict_enabled=1;
static int cp_ee_controls_enabled=1,cp_movie_format_enabled;
static unsigned int cp_ee_controls_used;
static uint64_t event_transaction,last_receive_transaction,last_free_transaction;
static long sender_tid,receiver_tid,free_tid;
static unsigned char request_wire[16]={5,0xa5,0x9d,0x40,0x67,0x45,0x23,0x81};
static unsigned char reply_wire[12],foreign_wire[12],receipt208[208];
static unsigned int message_bytes=12,message_source=FUNCTIONAL_CAMERA_CONTROL_AP;
static void *allocated_pointer=reply_wire;
static struct full_adf_proc_snapshot proc;
static struct full_adf_set_input_snapshot input;
static struct full_adf_set_output_snapshot output;
static struct full_vef_resource_snapshot resource_fixture;
static struct dmm_service dmm;
static int dmm_enabled=1;
static unsigned long appfw_base;
static char last_resource_tag[100];
#define LENS_POOL_SLOTS 2
static struct {unsigned int live;void *message;unsigned int borrowed_from;} lens_pool[LENS_POOL_SLOTS];
static int backup_service_enabled;
static int actual_free(unsigned int,void *);
static void *request_reuse_thread(void *);
static void native_crank_received(unsigned int,void *,unsigned int,unsigned int);
static uint64_t native_crank_ticket_for(unsigned int,void *);
static void native_crank_allocated(unsigned int,void **,int,unsigned int);
static void native_pin_peer_allocated(unsigned int,void **,int,unsigned int);
static int native_crank_allocate(unsigned int,void **,unsigned int,unsigned int);
static int native_crank_send(unsigned int,void *);
static void native_cp_state_received(unsigned int,void **,int);
static int functional_cp_crank_control_reserve_resources(void);
static int functional_cp_crank_control_predecessors_ready(void);

static long actual_tid(void){return syscall(SYS_gettid);}
static long fixture_syscall(long number){assert(number==178);return actual_tid();}
#define syscall fixture_syscall
static int fixture_mutex_lock(void *mutex){
 assert(getpid()==original_pid);++locks;
 if(mutex==functional_cp_crank_control_ticket_mutex){
  assert(!crank_ticket_held);int rc=pthread_mutex_lock(&ticket_lock);if(!rc)crank_ticket_held=1;return rc;
 }
 if(mutex==cp_parameter_batch_mutex){assert(!batch_held);batch_held=1;return 0;}
 if(mutex==cap_lock){assert(resource_held && !cap_held);cap_held=1;return 0;}
 assert(mutex==lens_pool_lock);return 0;
}
static int fixture_mutex_unlock(void *mutex){
 assert(getpid()==original_pid);++unlocks;
 if(mutex==functional_cp_crank_control_ticket_mutex){
  assert(crank_ticket_held);crank_ticket_held=0;return pthread_mutex_unlock(&ticket_lock);
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
 if(!strncmp(event,"FUNCTIONAL_BACKGROUND_START_",sizeof "FUNCTIONAL_BACKGROUND_START_"-1))
  event+=sizeof "FUNCTIONAL_BACKGROUND_START_"-1;
 assert(!strstr(event,"ACK") && !strstr(tag,"_MODEL"));
 if(strstr(tag,"_RESOURCE")){assert(strlen(tag)<sizeof last_resource_tag);strcpy(last_resource_tag,tag);}
}
void native_functional_camera_movie_format_snapshot(struct native_functional_camera_movie_format_snapshot *out){
 (void)out;assert(!functional_cp_movie_format_used && !"disabled movie owner must not be queried");
}
static void native_movie_format_allocated(unsigned int id,void **p,int result,unsigned int count){
 (void)id;(void)p;(void)result;(void)count;assert(!functional_cp_movie_format_used);
}
static void native_movie_format_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;assert(!"movie owner disabled in old crank fixture");
}
void native_functional_camera_crank_snapshot(struct native_functional_camera_crank_snapshot *out){
 assert(!forbid_snapshot && !batch_held);
 if(expect_postdispatch_snapshot){assert(crank_ticket_held);++postdispatch_snapshots;}
 ++crank_snapshots;*out=crank;
}
void native_functional_camera_parameter_snapshot(struct native_functional_camera_parameter_snapshot *out){
 assert(!forbid_snapshot && !batch_held);++bank_snapshots;*out=bank;
}
void native_cp_ee_controls_diagnostic_snapshot(struct native_cp_ee_controls_diagnostic_snapshot *out){assert(!batch_held);*out=ee;}
int cp_output_policy_snapshot(const struct cp_output_policy *state,uint32_t mask,struct cp_output_policy_snapshot *out){
 assert(state==&cp_output_policy_state && mask==CP_OUTPUT_POLICY_KNOWN_MASK && batch_held);*out=policy;return 0;
}
static int functional_cp_parameter_bank_predecessors_ready(void){++ready_reads;return predecessor_ready;}
void functional_still_format_snapshot(struct functional_still_format_snapshot *out){(void)out;assert(0);}
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *out){(void)out;assert(0);}
void full_adf_proc_snapshot(struct full_adf_proc_snapshot *out){assert(!resource_held);*out=proc;}
void full_adf_set_input_snapshot(struct full_adf_set_input_snapshot *out){assert(!resource_held);*out=input;}
void full_adf_set_output_snapshot(struct full_adf_set_output_snapshot *out){assert(!resource_held);*out=output;}
int full_vef_resources_lock(void){assert(!resource_held);++resource_calls;if(resource_rc)return resource_rc;resource_held=1;return 0;}
void full_vef_resources_unlock(void){assert(resource_held);resource_held=0;++resource_unlocks;}
void pin_control_snapshot(struct pin_control_snapshot *out){assert(resource_held);*out=resource_fixture.control;}
void full_pin_connection_snapshot(struct pin_connection_snapshot *out){assert(resource_held);*out=resource_fixture.connection;}
void full_vef_snapshot(struct full_vef_snapshot *out){assert(resource_held);*out=resource_fixture.vef;}
void full_pinmem_snapshot(struct full_vef_snapshot *out){assert(resource_held);*out=resource_fixture.pinmem;}
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out){assert(resource_held);memset(out,0,sizeof *out);}
void full_hdmi_pin_snapshot(struct full_vef_snapshot *out){assert(resource_held);memset(out,0,sizeof *out);}
enum full_vef_dmm_domain full_vef_resource_dmm_domain(const struct full_vef_resource_snapshot *snapshot){assert(resource_held && snapshot);return FULL_VEF_DMM_SPEECH_INITIAL;}
int full_vef_resources_admissible(const struct full_vef_resource_snapshot *snapshot){assert(resource_held && snapshot);return 1;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){assert(logger==record);++bridge_calls;return bridge_rc;}
static unsigned int size_api(void *p){assert(p);return p==request_wire?message_bytes:12;}
static unsigned int source_api(void *p){assert(p);return p==request_wire?message_source:FUNCTIONAL_CAMERA_CONTROL_SID;}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static int free_api(unsigned int id,void *p){
 assert(id && p && !batch_held);
 if(p==request_wire)++request_frees;
 else if(p==reply_wire)++reply_frees;
 else {assert(p==foreign_wire);++ordinary_frees;}
 return free_rc;
}
static int (*real_free_msg)(unsigned int,void *)=free_api;
static int allocate_api(unsigned int id,void **out,unsigned int bytes,unsigned int count){
 assert(id && bytes && count && !batch_held);++allocation_calls;
 if(consumed_before_reply)assert(before_calls==1 && model_calls==1 && !before_rc && !model_rc && after_calls==1 && !after_rc && receipt_bytes==208 && receipt_valid);
 if(out)*out=allocation_null?NULL:allocated_pointer;
 if(allocation_snapshot_drift)crank.transaction++;
 return allocation_rc;
}
static int (*real_allocate_msg)(unsigned int,void **,unsigned int,unsigned int)=allocate_api;
static void set_source_api(void *p,unsigned int source){assert(p==reply_wire && source==FUNCTIONAL_CAMERA_CONTROL_SID && consumed_before_reply);}
static void (*real_set_source)(void *,unsigned int)=set_source_api;
static int transport_send_api(unsigned int id,void *p){
 assert(id==FUNCTIONAL_CAMERA_CONTROL_AP && p==reply_wire && consumed_before_reply && crank.verified);
 ++send_calls;assert(event_transaction && native_crank_ticket_for(id,p)==event_transaction);
 assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==event_transaction);
 forbid_snapshot=1;
 if(synchronous_receive){void *message=p;native_cp_state_received(id,&message,0);}
 if(synchronous_free)assert(!actual_free(id,p));
 forbid_snapshot=0;return send_rc;
}
static int (*real_send_msg)(unsigned int,void *)=transport_send_api;
static unsigned int pinmem_peer_connections_used;
#define PEER_ALLOCATE(name) unsigned long long name(unsigned int id,void *p){(void)id;(void)p;assert(0);return 0;}
PEER_ALLOCATE(full_scalar_connection_observe_allocate)
PEER_ALLOCATE(full_adf_connection_observe_allocate)
PEER_ALLOCATE(full_pinmem_drawinfo_connection_observe_allocate)
static void native_face_sdk_observation(unsigned int kind,unsigned int id,void *p,unsigned int bytes,int result,void *caller){
 (void)id;(void)p;(void)bytes;(void)result;assert(kind==1 && caller);++sdk_calls;
}
#define INACTIVE_RECEIVE(name) static void name(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
INACTIVE_RECEIVE(native_startup_control_received)
INACTIVE_RECEIVE(native_still_format_received)
INACTIVE_RECEIVE(native_background_start_received)
INACTIVE_RECEIVE(native_histogram_received)
static void native_functional_face_received(unsigned int id,void *p){(void)id;(void)p;}
int functional_vdf_layout_stage_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){(void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;}
int functional_vdf_path_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){(void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;}
static int functional_camera_events_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
static int functional_jpeg_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;assert(io->allocate==real_allocate_msg);return 0;}
static int functional_mpr_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;(void)io;assert(0);return 0;}
static void functional_capture_observe_received(unsigned int id,void *p){(void)id;(void)p;}
void full_imaging_functional_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
int native_cp_state_publication_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
int native_functional_camera_parameter_release(unsigned int id,void *p,int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result,uint64_t transaction){
 (void)id;(void)p;(void)release;(void)logger;(void)result;(void)transaction;++parameter_releases;return 0;
}
int native_functional_camera_crank_release(unsigned int id,void *p,int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result,uint64_t transaction,const struct native_functional_camera_crank_receive *event){
 assert(logger==record && result);used_reads++;
 if(event){
  assert(!release);++receive_calls;last_receive_transaction=transaction;receiver_tid=actual_tid();
  if(id==FUNCTIONAL_CAMERA_CONTROL_AP && p==reply_wire && transaction==event_transaction &&
     event->source==FUNCTIONAL_CAMERA_CONTROL_SID && event->bytes==12){receive_observed=1;*result=0;}
  else *result=-ESTALE;
  return 1;
 }
 assert(release==real_free_msg);++release_calls;last_free_transaction=transaction;free_tid=actual_tid();
 if(release_override){*result=release_override;return 1;}
 if(!transaction){
  if((p!=reply_wire && p!=request_wire) || complete ||
     (p==request_wire && crank.request_freed && !crank.retained_request))return 0;
  *result=-ESTALE;return 1;
 }
 if(transaction!=event_transaction || complete || id!=FUNCTIONAL_CAMERA_CONTROL_AP || p!=reply_wire || !receive_observed || free_tid!=sender_tid){*result=-ESTALE;return 1;}
 *result=release(id,p);if(!*result)complete=1;return 1;
}
static int legacy_dispatch(unsigned int id,void *p){
 assert(strict_enabled && id==NATIVE_CP_EE_CONTROLS_SID && p==request_wire);++legacy_calls;return legacy_rc;
}
static int cp_ee_controls_reserve_resources(void){assert(0);return -ENODATA;}
static int cp_ee_controls_predecessors_ready(void){assert(0);return 0;}
static int cp_ee_controls_after_movie_predecessors_ready(void){assert(0);return 0;}
int native_cp_ee_controls_diagnostic_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_ee_controls_diagnostic_guard *guard,int enabled,int *result){
 assert(enabled==1 && cp_ee_controls_used==1 && io && guard);
 assert(io->allocate==real_allocate_msg && io->send==real_send_msg);
 assert(guard->predecessor_ready==cp_ee_controls_predecessors_ready && !owner_calls && !model_calls);
 *result=legacy_dispatch(id,p);return 1;
}
int native_functional_camera_crank_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 assert(id==NATIVE_CP_EE_CONTROLS_SID && p==request_wire && enabled==1 && bank.model_called);
 assert(io->allocate==native_crank_allocate && io->release==real_free_msg && io->set_source==real_set_source);
 assert(io->send==native_crank_send && io->size==real_msg_size && io->source==real_get_source && io->record==record);
 assert(guard->reserve==functional_cp_crank_control_reserve_resources && guard->release==full_vef_resources_unlock);
 assert(guard->predecessor_ready==functional_cp_crank_control_predecessors_ready && functional_cp_crank_control_used==1);
 ++owner_calls;if(!owner_handled)return 0;
 *result=owner_rc;if(owner_rc)return 1;
 if(!real_get_source || real_get_source(p)!=FUNCTIONAL_CAMERA_CONTROL_AP){*result=-EPERM;return 1;}
 if(request_wire[8] || request_wire[9] || request_wire[10] || request_wire[11]){*result=-ENOTSUP;return 1;}
 *result=guard->reserve();if(*result)return 1;
 if(!guard->predecessor_ready()){*result=-ENODATA;guard->release();return 1;}
 ++before_calls;*result=before_rc;
 if(!*result){++model_calls;crank.model_called=1;crank.model_rc=model_rc;crank.model_committed=!model_rc;*result=model_rc;}
 if(!*result && (receipt_bytes!=208 || !receipt_valid))*result=-EPROTO;
 if(!*result){++after_calls;*result=after_rc;}
 if(*result){guard->release();return 1;}
 consumed_before_reply=1;crank.verified=crank.owned=1;crank.request_pointer=crank.retained_request=p;
 crank.transaction=event_transaction=UINT64_C(0x100000007);crank.origin.destination=id;
 memcpy(crank.receipt,receipt208,208);sender_tid=actual_tid();crank.sender_tid=sender_tid;
 void *reply=NULL;int rc=io->allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&reply,12,1);
 if(!rc && reply){
  assert(reply==reply_wire);crank.reply_pointer=reply;crank.allocation_pointer=reply;
  memcpy(reply,request_wire,8);reply_wire[0]=1;reply_wire[1]=0;memcpy(reply_wire+8,"\0\xf0\0\0",4);
  io->set_source(reply,FUNCTIONAL_CAMERA_CONTROL_SID);rc=io->send(FUNCTIONAL_CAMERA_CONTROL_AP,reply);
 }
 if(!rc){
  rc=io->release(id,p);
  if(!rc){
   crank.request_freed=1;crank.retained_request=NULL;
   if(request_reuse_before_return){
    allocated_pointer=p;pthread_t thread;
    assert(!pthread_create(&thread,NULL,request_reuse_thread,NULL));assert(!pthread_join(thread,NULL));
   }
  }
 }
 if(rc){crank.faults=1;crank.retained_request=p;}
 guard->release();expect_postdispatch_snapshot=arm_postdispatch_snapshot;
 if(postdispatch_pid_drift)++functional_cp_crank_control_ticket_pid;
 dispatch_return_locks=locks;*result=0;return 1;
}
static int control_init_calls,parameter_init_calls,crank_init_calls,still_init_calls,startup_init_calls,crank_init_rc;
static int same_name(const char *a,const char *b){return a && b && !strcmp(a,b);}
int native_functional_camera_control_owner_init(void){++control_init_calls;return 0;}
int native_functional_camera_parameter_owner_init(void){assert(control_init_calls==1);++parameter_init_calls;return 0;}
int native_functional_camera_crank_owner_init(void){assert(parameter_init_calls==1 && !still_init_calls);++crank_init_calls;return crank_init_rc;}
int native_functional_camera_movie_format_owner_init(void){assert(crank_init_calls==1 && !crank_init_rc && !still_init_calls);return 0;}
/* Constructor compatibility only; no timecode business result is established. */
int full_bb_timecode_control_owner_init(void){return 0;}
int functional_still_format_owner_init(void){assert(crank_init_calls==1 && !crank_init_rc);++still_init_calls;return 0;}
int functional_startup_control_owner_init(void){assert(still_init_calls==1);++startup_init_calls;return 0;}

/* ACTUAL_MAIN_HELPERS */
static void *request_reuse_thread(void *unused){
 (void)unused;assert(request_frees==1 && crank.request_freed && !crank.retained_request);
 reuse_tid=actual_tid();assert(reuse_tid!=sender_tid);
 assert(!osal_valloc_msg_wait(FUNCTIONAL_CAMERA_CONTROL_SID,&reused_request,12,1));
 assert(reused_request==request_wire && !native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,reused_request));
 return NULL;
}
static int actual_send(unsigned int id,void *message){
/* ACTUAL_CRANK_ROUTE */
/* ACTUAL_EE_ROUTE */
 ++fallback_sends;return -999;
}
static int actual_free(unsigned int id,void *message){
 int vdf_result;
/* ACTUAL_CRANK_FREE */
 return real_free_msg(id,message);
}
static void actual_init(const char *functional_profile){
/* ACTUAL_CRANK_INIT */
}
static void ready(void){
 original_pid=getpid();functional_cp_crank_control_ticket_pid=(unsigned int)getpid();
 functional_cp_movie_format_ticket_pid=(unsigned int)getpid();assert(!functional_cp_movie_format_used);
 proc.owner_pid=input.owner_pid=output.owner_pid=getpid();proc.configured=input.configured=output.configured=1;
 proc.clean_completion=input.clean_completion=output.clean_completion=1;proc.ap_consumed=input.ap_consumed=output.ap_consumed=1;
 proc.request_freed=input.request_freed=output.request_freed=1;proc.reply_freed=input.reply_freed=output.reply_freed=1;
 bank.owner_pid=crank.owner_pid=getpid();bank.initialized=crank.initialized=1;
 bank.model_called=bank.model_committed=bank.verified=bank.owned=bank.request_freed=1;
 bank.model_instance=77;bank.bank_generation=3;bank.transaction=7;
 cp_output_policy_state.owner_pid=getpid();policy.config_consumed=1;
 memcpy(bank.request+4,request_wire+4,4);memcpy(policy.bytes+4,request_wire+4,4);
 ee.owner_pid=getpid();ee.initialized=1;struct native_cp_ee_controls_diagnostic_lease *initial=&ee.leases[0];
 initial->opcode=0x409d;initial->attempts=initial->requests=initial->queued=1;
 initial->clean_completion=initial->ap_consumed=initial->request_freed=initial->reply_freed=1;
 initial->sender_tid=initial->waiter_tid=19;
 for(size_t i=0;i<sizeof receipt208;i++)receipt208[i]=(unsigned char)(i^0xa7u);
}
static void seed_ticket(void){
 functional_cp_crank_control_used=1;event_transaction=UINT64_C(0x100000007);
 functional_cp_crank_control_ticket.request=request_wire;functional_cp_crank_control_ticket.reply=reply_wire;
 functional_cp_crank_control_ticket.request_destination=FUNCTIONAL_CAMERA_CONTROL_SID;
 functional_cp_crank_control_ticket.reply_destination=FUNCTIONAL_CAMERA_CONTROL_AP;
 functional_cp_crank_control_ticket.transaction=event_transaction;sender_tid=actual_tid();
 crank.transaction=event_transaction;crank.owned=crank.verified=1;
 crank.request_pointer=request_wire;crank.reply_pointer=reply_wire;crank.origin.destination=FUNCTIONAL_CAMERA_CONTROL_SID;
}
static void receive_reply(unsigned int destination,void *pointer){
 void *message=pointer;int saved=crank_snapshots;forbid_snapshot=1;
 native_cp_state_received(destination,&message,0);forbid_snapshot=0;assert(crank_snapshots==saved);
}
static void *transport_thread(void *unused){(void)unused;receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);return NULL;}
static void *foreign_free_thread(void *unused){(void)unused;assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE);return NULL;}
static void check_route(const char *test){
 int expected=0,delegated=0,called=1;
 if(!strcmp(test,"cold")){bank.model_called=0;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"cold-fault-without-model")){bank.model_called=0;bank.faults=1;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"late-uncommitted")){bank.model_committed=bank.verified=0;owner_rc=-ENODATA;expected=-ENODATA;}
 else if(!strcmp(test,"disabled")){functional_camera_enabled=0;expected=legacy_rc;delegated=1;called=0;}
 else if(!strcmp(test,"short")){message_bytes=11;expected=-EMSGSIZE;called=0;}
 else if(!strcmp(test,"long")){message_bytes=13;expected=-EMSGSIZE;called=0;}
 else if(!strcmp(test,"setup-error")){functional_camera_setup_error=-ELIBBAD;expected=-ELIBBAD;called=0;}
 else if(!strcmp(test,"bridge-error")){bridge_rc=-EIO;expected=-EIO;called=0;}
 else if(!strcmp(test,"source-error")){message_source++;expected=-EPERM;called=0;}
 else if(!strcmp(test,"missing-source")){real_get_source=NULL;expected=-EPERM;called=0;}
 else if(!strcmp(test,"mode-error")){request_wire[11]=1;expected=-ENOTSUP;}
 else if(!strcmp(test,"owner-unhandled")){owner_handled=0;expected=-ENOTSUP;}
 else if(!strcmp(test,"owner-error")){owner_rc=-ESTALE;expected=-ESTALE;}
 else if(!strcmp(test,"before-error")){before_rc=-EIO;expected=-EIO;}
 else if(!strcmp(test,"model-error")){model_rc=-EUCLEAN;expected=-EUCLEAN;}
 else if(!strcmp(test,"receipt-short")){receipt_bytes=207;expected=-EPROTO;}
 else if(!strcmp(test,"receipt-mutated")){receipt_valid=0;expected=-EPROTO;}
 else if(!strcmp(test,"after-error")){after_rc=-ESTALE;expected=-ESTALE;}
 else if(!strcmp(test,"bank-unfreed")){functional_cp_parameter_bank_used=1;bank.request_freed=0;expected=-ENODATA;}
 else if(!strcmp(test,"bank-fault")){functional_cp_parameter_bank_used=1;bank.faults=1;expected=-ENODATA;}
 else if(!strcmp(test,"initial-repeat")){ee.leases[0].attempts++;expected=-ENODATA;}
 else if(!strcmp(test,"policy-cookie")){policy.bytes[4]^=1;expected=-ENODATA;}
 else if(!strcmp(test,"predecessor")){predecessor_ready=0;expected=-ENODATA;}
 else if(!strcmp(test,"synchronous"))synchronous_receive=synchronous_free=1;
 else assert(!strcmp(test,"late"));
 assert(actual_send(NATIVE_CP_EE_CONTROLS_SID,request_wire)==expected);
 assert(owner_calls==called && legacy_calls==delegated && !fallback_sends);
 assert(functional_cp_crank_control_used==(unsigned int)called);
 if(!strcmp(test,"source-error") || !strcmp(test,"missing-source"))assert(!bridge_calls && !resource_calls && !owner_calls);
 assert(ee.leases[0].attempts==(!strcmp(test,"initial-repeat")?2u:1u));
 if(expected){
  assert(!allocation_calls && !send_calls && !request_frees && !reply_frees && !consumed_before_reply);
  if(!strcmp(test,"before-error"))assert(before_calls==1 && !model_calls && !after_calls && !crank.model_called);
  if(!strcmp(test,"model-error"))assert(model_calls==1 && crank.model_called && !crank.model_committed && crank.model_rc==model_rc);
  if(!strcmp(test,"receipt-short") || !strcmp(test,"receipt-mutated"))assert(model_calls==1 && crank.model_committed && !after_calls);
  if(!strcmp(test,"after-error"))assert(model_calls==1 && after_calls==1 && crank.model_committed && !crank.model_rc);
 }
 else{
  assert(before_calls==1 && model_calls==1 && after_calls==1 && consumed_before_reply);
  assert(allocation_calls==1 && send_calls==1 && request_frees==1 && !legacy_calls);
  assert(crank_snapshots==3 && bridge_calls==1 && resource_calls==1 && resource_unlocks==1);
  assert(!memcmp(crank.receipt,receipt208,208) && request_wire[1]==0xa5 && reply_wire[1]==0);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
  if(synchronous_free)assert(receive_calls==1 && release_calls==1 && complete && reply_frees==1);
 }
}
static void check_allocation(const char *test){
 seed_ticket();complete=1;functional_cp_parameter_bank_ticket.pointer=reply_wire;
 functional_cp_parameter_bank_ticket.destination=FUNCTIONAL_CAMERA_CONTROL_AP;
 functional_cp_parameter_bank_ticket.transaction=13;
 unsigned int count=1,id=FUNCTIONAL_CAMERA_CONTROL_AP;void *out=NULL;int expected_clear=1;
 if(!strcmp(test,"failed")){allocation_rc=-ENOMEM;expected_clear=0;}
 else if(!strcmp(test,"multi")){count=2;expected_clear=0;}
 else if(!strcmp(test,"null")){allocation_null=1;expected_clear=0;}
 else if(!strcmp(test,"foreign")){allocated_pointer=foreign_wire;expected_clear=0;}
 else if(!strcmp(test,"unused")){functional_cp_crank_control_used=0;expected_clear=0;}
 else if(!strcmp(test,"borrowed"))id=0x912503d0;
 else assert(!strcmp(test,"reuse"));
 int before=locks;assert(osal_valloc_msg_wait(id,&out,20,count)==allocation_rc && allocation_calls==1);
 assert((functional_cp_crank_control_ticket.reply==NULL)==expected_clear);
 int parameter_cleared=!allocation_rc && count==1 && !allocation_null && allocated_pointer==reply_wire;
 assert((functional_cp_parameter_bank_ticket.pointer==NULL)==parameter_cleared);
 if(expected_clear){assert(!native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));assert(reply_frees==1);}
 else{
  assert(functional_cp_crank_control_ticket.reply==reply_wire && functional_cp_crank_control_ticket.transaction==event_transaction);
  if(!functional_cp_crank_control_used || allocation_rc || count!=1 || allocation_null)assert(locks==before);
 }
 assert(!crank_snapshots && !bank_snapshots && !send_calls && !owner_calls);
}
static void check_adapter(const char *test){
 seed_ticket();int expected=-ESTALE;
 if(!strcmp(test,"allocate-captured-snapshot")){
  crank.transaction=event_transaction+2;uint64_t captured=crank.transaction;allocation_snapshot_drift=1;
  functional_cp_parameter_bank_ticket.pointer=reply_wire;functional_cp_parameter_bank_ticket.transaction=9;
  void *pointer=NULL;assert(!native_crank_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&pointer,12,1));
  assert(pointer==reply_wire && allocation_calls==1 && crank.transaction==captured+1);
  assert(!functional_cp_parameter_bank_ticket.pointer && !functional_cp_parameter_bank_ticket.transaction);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,pointer)==captured);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==captured);
 }else if(!strcmp(test,"allocate-unowned")){
  crank.owned=0;void *pointer=NULL;assert(native_crank_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&pointer,12,1)==-ESTALE);
  assert(!allocation_calls && !locks && !pointer);
 }else{
  unsigned int destination=FUNCTIONAL_CAMERA_CONTROL_AP;
  if(!strcmp(test,"send-missing-ticket"))functional_cp_crank_control_ticket.reply=NULL;
  else if(!strcmp(test,"send-wrong-destination"))destination++;
  else if(!strcmp(test,"send-stale-transaction"))crank.transaction++;
  else if(!strcmp(test,"send-unverified"))crank.verified=0;
  else assert(0);
  assert(native_crank_send(destination,reply_wire)==expected);
  assert(!send_calls && !allocation_calls);
 }
 assert(crank_snapshots==1 && !bank_snapshots && !owner_calls && !model_calls);
}
static void check_ticket(const char *test){
 seed_ticket();int snapshots=crank_snapshots;
 if(!strcmp(test,"cross-receive")){
  pthread_t thread;assert(!pthread_create(&thread,NULL,transport_thread,NULL));assert(!pthread_join(thread,NULL));
  assert(receiver_tid!=sender_tid && last_receive_transaction==event_transaction && receive_observed);
  crank.transaction=event_transaction+1;forbid_snapshot=1;
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));forbid_snapshot=0;
  assert(free_tid==sender_tid && last_free_transaction==event_transaction && reply_frees==1);
 }else if(!strcmp(test,"wrong-free-thread")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);pthread_t thread;
  assert(!pthread_create(&thread,NULL,foreign_free_thread,NULL));assert(!pthread_join(thread,NULL));
  assert(!reply_frees && last_free_transaction==event_transaction);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
 }else if(!strcmp(test,"wrong-destination")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP+1,reply_wire);assert(!last_receive_transaction && !receive_observed);
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP+1,reply_wire)==-ESTALE && !last_free_transaction && !reply_frees);
 }else if(!strcmp(test,"foreign-pointer")){
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,foreign_wire) && !last_free_transaction && ordinary_frees==1);
 }else if(!strcmp(test,"stale")){
  event_transaction++;assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE);
  assert(last_free_transaction==event_transaction-1 && !reply_frees);
 }else if(!strcmp(test,"completed-duplicate")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-ESTALE && reply_frees==1);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
 }else if(!strcmp(test,"free-error")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);free_rc=-EIO;
  assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==-EIO && !complete);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
 }else if(!strcmp(test,"receive-failure")){
  void *p=reply_wire;native_cp_state_received(FUNCTIONAL_CAMERA_CONTROL_AP,&p,-EAGAIN);assert(!receive_calls);
 }else if(!strcmp(test,"reuse-after-complete")){
  receive_reply(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire);assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire));
  void *p=NULL;assert(!osal_valloc_msg_wait(FUNCTIONAL_CAMERA_CONTROL_AP,&p,12,1) && p==reply_wire);
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_AP,p) && reply_frees==2 && !last_free_transaction);
 }else if(!strcmp(test,"fork-before-lock")){
  hold_fork_lock();pid_t child=fork();assert(child>=0);
  if(!child){
   int lock_count=locks;void *p=reply_wire;assert(!native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,p));
   native_crank_allocated(FUNCTIONAL_CAMERA_CONTROL_AP,&p,0,1);
   assert(native_crank_allocate(FUNCTIONAL_CAMERA_CONTROL_AP,&p,12,1)==-ESTALE);
   assert(native_crank_send(FUNCTIONAL_CAMERA_CONTROL_AP,p)==-ESTALE && locks==lock_count);
   assert(functional_cp_crank_control_ticket.reply==reply_wire);_exit(0);
  }
  drop_fork_lock();int status=-1;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 }else assert(0);
 assert(crank_snapshots==snapshots && !bank_snapshots);
}
static void check_resource(const char *test,unsigned int requester){
 functional_cp_crank_control_used=1;functional_cp_parameter_bank_used=1;
 int expected=0;
 if(!strcmp(test,"idle")){}
 else if(!strcmp(test,"selfskip")){assert(requester==34);crank.owner_pid++;crank.initialized=0;crank.busy=crank.guard_held=crank.faults=crank.owned=1;crank.retained_reply=reply_wire;}
 else if(!strcmp(test,"bank-unfreed")){bank.request_freed=0;expected=-ENODATA;}
 else if(!strcmp(test,"bank-fault")){bank.faults=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-busy")){crank.busy=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-foreign")){crank.owner_pid++;expected=-ENODATA;}
 else if(!strcmp(test,"crank-uninitialized")){crank.initialized=0;expected=-ENODATA;}
 else if(!strcmp(test,"crank-request-releasing")){crank.request_releasing=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-guard")){crank.guard_held=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-fault")){crank.faults=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-retained-request")){crank.retained_request=request_wire;expected=-ENODATA;}
 else if(!strcmp(test,"crank-retained-reply")){crank.retained_reply=reply_wire;expected=-ENODATA;}
 else if(!strcmp(test,"crank-releasing")){crank.reply_releasing=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-inspecting")){crank.reply_inspecting=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-inflight")){crank.send_inflight=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-owned-live")){crank.owned=1;expected=-ENODATA;}
 else if(!strcmp(test,"crank-complete")){crank.owned=crank.complete=1;}
 else assert(0);
 struct native_functional_camera_crank_snapshot saved=crank;
 assert(tracked_native_reserve_resources((int)requester)==expected);
 assert(!memcmp(&crank,&saved,sizeof crank));assert(crank_snapshots==(requester!=34));
 if(!expected){assert(resource_calls==1 && resource_held);full_vef_resources_unlock();}
 else assert(!resource_calls && !resource_held);
 if(requester==34)assert(strstr(last_resource_tag,"FUNCTIONAL_CP_CRANK_CONTROL_RESOURCES_"));
}
static void check_rootfix(const char *test){
 if(!strcmp(test,"postdispatch-fork-before-lock")){
  hold_fork_lock();pid_t child=fork();assert(child>=0);
  if(!child){
   int before=locks;owner_rc=-EIO;
   assert(actual_send(NATIVE_CP_EE_CONTROLS_SID,request_wire)==-EIO);
   assert(owner_calls==1 && !crank_snapshots && locks==before && !allocation_calls);_exit(0);
  }
  drop_fork_lock();int status=-1;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));return;
 }
 if(!strcmp(test,"request-reuse-before-return"))request_reuse_before_return=1;
 else if(!strcmp(test,"request-retained-before-return"))allocation_rc=-ENOMEM;
 else if(!strcmp(test,"postdispatch-pid-mismatch"))postdispatch_pid_drift=1;
 else assert(0);
 arm_postdispatch_snapshot=1;assert(!actual_send(NATIVE_CP_EE_CONTROLS_SID,request_wire));
 if(postdispatch_pid_drift){assert(locks==dispatch_return_locks && !postdispatch_snapshots);return;}
 assert(postdispatch_snapshots==1);
 if(request_reuse_before_return){
  assert(reuse_tid!=sender_tid && reused_request==request_wire && allocation_calls==2);
  assert(crank.request_pointer==request_wire && crank.request_freed && !crank.retained_request);
  assert(!native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,reused_request));
  assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_SID,reused_request) && request_frees==2 && !last_free_transaction);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_AP,reply_wire)==event_transaction);
 }else{
  assert(crank.retained_request==request_wire && !crank.request_freed && crank.faults && !request_frees);
  assert(native_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==event_transaction);
 }
}
int main(int argc,char **argv){
 assert(argc>=3);ready();
 if(!strcmp(argv[1],"rootfix"))check_rootfix(argv[2]);
 else if(!strcmp(argv[1],"route"))check_route(argv[2]);
 else if(!strcmp(argv[1],"allocation"))check_allocation(argv[2]);
 else if(!strcmp(argv[1],"adapter"))check_adapter(argv[2]);
 else if(!strcmp(argv[1],"ticket"))check_ticket(argv[2]);
 else if(!strcmp(argv[1],"resource")){assert(argc==4);check_resource(argv[2],(unsigned int)atoi(argv[3]));}
 else if(!strcmp(argv[1],"init")){
  if(!strcmp(argv[2],"crank-error"))crank_init_rc=-ENOMEM;
  else assert(!strcmp(argv[2],"local"));
  actual_init(FCAM_PROFILE);assert(control_init_calls==1 && parameter_init_calls==1 && crank_init_calls==1);
  assert(still_init_calls==!crank_init_rc && startup_init_calls==!crank_init_rc);
  assert(functional_camera_enabled==!crank_init_rc && functional_cp_crank_control_ticket_pid==(unsigned int)getpid());
  assert(!bridge_calls && !model_calls && !allocation_calls && !send_calls);
 }else assert(0);
 assert(locks==unlocks && !batch_held && !cap_held && !resource_held);
 puts("PASS actual Main crank wiring MOCK; Core/native AP/capture unverified");return 0;
}
