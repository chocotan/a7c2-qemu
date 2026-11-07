/* SPDX-License-Identifier: MIT
 * Exact Main source slices replace ACTUAL_OU_* markers. Native owner/bridge and
 * resource providers are MOCKS; this fixture establishes no AP or capture result.
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
#include "device-models/functional-startup-control.h"
#include "device-models/functional-still-format.h"
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
int full_bb_timecode_control_observe_allocate(unsigned int id,void *p,unsigned int bytes,unsigned int count,int rc){
 (void)id;(void)p;(void)bytes;(void)count;(void)rc;assert(!functional_bb_timecode_control_used);return 0;
}
static unsigned int functional_bb_timecode_audit_pid;

/* ACTUAL_OU_DECLARATIONS */
static int functional_camera_enabled=1,functional_camera_setup_error,cp_owned_state_enabled=1;
static unsigned int functional_cp_parameter_bank_used,functional_cp_crank_control_used,functional_cp_movie_format_used;
static unsigned int functional_startup_control_used,functional_still_format_used;
static unsigned int functional_cp_crank_control_ticket_pid,functional_cp_movie_format_ticket_pid;
static unsigned int still_format_ticket_pid,startup_control_ticket_pid,cp_ee_controls_used;
static int cp_ee_controls_enabled=1,cp_movie_format_enabled=1;
static struct native_functional_camera_control_snapshot control;
static struct native_functional_camera_parameter_snapshot bank;
static struct native_functional_camera_crank_snapshot crank;
static struct native_functional_camera_movie_format_snapshot movie;
static struct native_functional_camera_ou_crank_snapshot ou;
static struct native_cp_ee_controls_diagnostic_snapshot strict;
static struct native_cp_movie_format_diagnostic_snapshot early;
static struct functional_startup_control_snapshot startup;
static struct functional_still_format_snapshot still;
static struct cp_output_policy cp_output_policy_state;
static struct cp_output_policy_snapshot policy;
static void *cp_parameter_batch_retained_request;
static unsigned long cp_parameter_batch_mutex[6],cap_lock[6],lens_pool_lock[6];
#define LENS_POOL_SLOTS 2
static struct {unsigned int live;void *message;unsigned int borrowed_from;} lens_pool[LENS_POOL_SLOTS];
static int backup_service_enabled;
static unsigned int peer_allocation_observations,crank_allocation_observations,sdk_observations;
static pthread_mutex_t ticket_lock=PTHREAD_MUTEX_INITIALIZER;
static _Thread_local int ticket_held;
static int original_pid,locks,unlocks,batch_held,resource_held,resource_calls,resource_unlocks,ticket_lock_rc;
static int graph_ready=1,resource_rc,admissible=1,domain=FULL_VEF_DMM_SPEECH_INITIAL,policy_rc;
static int bridge_calls,bridge_rc,owner_calls,owner_handled=1,owner_rc,legacy_calls,fallback_calls;
static int before_calls,model_calls,after_calls,before_rc,model_rc,after_rc,validation_rc;
static int free_calls,free_rc,ordinary_frees,release_calls,source_calls,size_calls,ou_reads,forbid_snapshot;
static int allocation_calls,allocation_rc,allocation_null,raw_errno=ERANGE,clobber_errno=1,movie_observations;
static int dispatch_active,reuse_before_return,skip_free,postdispatch_drift,expect_postdispatch_snapshot,postdispatch_reads;
static int context_drift,ou_init_calls,ou_init_rc,control_init_calls,parameter_init_calls,crank_init_calls,movie_init_calls;
static int still_init_calls,startup_init_calls;
static uint64_t event_transaction=UINT64_C(0x100000017),last_release_ticket;
static struct native_functional_camera_ou_crank_context expected_context,captured_context;
static unsigned char request_wire[16]={5,0xa5,0x72,0x40,0x61,0,0,0x80};
static unsigned char foreign_wire[16];
static unsigned int message_bytes=12,message_source=FUNCTIONAL_CAMERA_CONTROL_AP;
static void *allocated_pointer=request_wire;
static struct full_adf_proc_snapshot proc;
static struct full_adf_set_input_snapshot input;
static struct full_adf_set_output_snapshot output;
static struct full_vef_resource_snapshot fixture;
static struct dmm_service dmm;
static unsigned long appfw_base;
static int dmm_enabled=1;
static unsigned int reserved_tags,tts_tags,refused_tags,fault_tags;
static int native_ou_crank_real_free(unsigned int,void *);
static int native_ou_crank_ticket_for(unsigned int,void *,uint64_t *);
static int native_functional_ou_crank_release(unsigned int,void *,int *);
static void native_ou_crank_allocated(unsigned int,void **,int,unsigned int);
static int native_tracked_allocate_msg(unsigned int,void **,unsigned int,unsigned int);
static int functional_cp_ou_crank_control_reserve_resources(void);
static int functional_cp_ou_crank_control_predecessors_ready(void);
static int actual_free(unsigned int,void *);
static long actual_tid(void){return syscall(SYS_gettid);}
static long fixture_syscall(long number){assert(number==178);return actual_tid();}
#define syscall fixture_syscall
static int fixture_lock(void *mutex){
    assert(getpid()==original_pid);
    if(mutex==functional_cp_ou_crank_control_ticket_mutex && ticket_lock_rc)return ticket_lock_rc;
    ++locks;
    if(mutex==functional_cp_ou_crank_control_ticket_mutex){
        assert(!ticket_held);
        int rc=pthread_mutex_lock(&ticket_lock);
        if(!rc)ticket_held=1;
        return rc;
    }
    if(mutex==cp_parameter_batch_mutex){assert(!batch_held);batch_held=1;return 0;}
    if(mutex==lens_pool_lock)return 0;
    assert(mutex==cap_lock && resource_held);return 0;
}
static int fixture_unlock(void *mutex){
    assert(getpid()==original_pid);++unlocks;
    if(mutex==functional_cp_ou_crank_control_ticket_mutex){
        assert(ticket_held);ticket_held=0;
        int rc=pthread_mutex_unlock(&ticket_lock);
        if(clobber_errno)errno=EINTR;
        return rc;
    }
    if(mutex==cp_parameter_batch_mutex){assert(batch_held);batch_held=0;return 0;}
    if(mutex==lens_pool_lock)return 0;
    assert(mutex==cap_lock && resource_held);return 0;
}
static void hold_ticket_lock(void){assert(!pthread_mutex_lock(&ticket_lock));}
static void drop_ticket_lock(void){assert(!pthread_mutex_unlock(&ticket_lock));}
#define pthread_mutex_lock fixture_lock
#define pthread_mutex_unlock fixture_unlock
static int fixture_open(const char *path,int flags){assert(!strcmp(path,"/proc/self/mem") && !flags);return -1;}
static long fixture_pread(int fd,void *out,size_t bytes,long offset){(void)fd;(void)out;(void)bytes;(void)offset;assert(0);return -1;}
static int fixture_close(int fd){(void)fd;assert(0);return -1;}
#define open fixture_open
#define pread fixture_pread
#define close fixture_close
static void record(const char *tag,const char *text){
    assert(tag && text && *text);
    if(!strcmp(tag,"FUNCTIONAL_CP_OU_CRANK_CONTROL_RESOURCES_RESERVED "))++reserved_tags;
    if(!strcmp(tag,"FUNCTIONAL_CP_OU_CRANK_CONTROL_RESOURCES_TTS_TABLE "))++tts_tags;
    if(!strcmp(tag,"FUNCTIONAL_CP_OU_CRANK_CONTROL_RESOURCES_REFUSED "))++refused_tags;
    if(!strcmp(tag,"FUNCTIONAL_CP_OU_CRANK_CONTROL_RESOURCES_FAULT "))++fault_tags;
}
#define SNAPSHOT(name,type,value) void name(struct type *out){assert(!forbid_snapshot && !batch_held);*out=value;}
SNAPSHOT(native_functional_camera_control_snapshot,native_functional_camera_control_snapshot,control)
SNAPSHOT(native_functional_camera_parameter_snapshot,native_functional_camera_parameter_snapshot,bank)
SNAPSHOT(native_functional_camera_crank_snapshot,native_functional_camera_crank_snapshot,crank)
SNAPSHOT(native_functional_camera_movie_format_snapshot,native_functional_camera_movie_format_snapshot,movie)
SNAPSHOT(native_cp_ee_controls_diagnostic_snapshot,native_cp_ee_controls_diagnostic_snapshot,strict)
SNAPSHOT(native_cp_movie_format_diagnostic_snapshot,native_cp_movie_format_diagnostic_snapshot,early)
SNAPSHOT(functional_startup_control_snapshot,functional_startup_control_snapshot,startup)
SNAPSHOT(functional_still_format_snapshot,functional_still_format_snapshot,still)
SNAPSHOT(full_adf_proc_snapshot,full_adf_proc_snapshot,proc)
SNAPSHOT(full_adf_set_input_snapshot,full_adf_set_input_snapshot,input)
SNAPSHOT(full_adf_set_output_snapshot,full_adf_set_output_snapshot,output)
#undef SNAPSHOT
void native_functional_camera_ou_crank_snapshot(struct native_functional_camera_ou_crank_snapshot *out){
    assert(!forbid_snapshot && !batch_held);++ou_reads;
    if(expect_postdispatch_snapshot){assert(ticket_held);++postdispatch_reads;}
    *out=ou;
}
int cp_output_policy_snapshot(const struct cp_output_policy *state,uint32_t mask,struct cp_output_policy_snapshot *out){
    assert(state==&cp_output_policy_state && mask==CP_OUTPUT_POLICY_KNOWN_MASK && batch_held);*out=policy;return policy_rc;
}
static int functional_cp_parameter_bank_predecessors_ready(void){assert(!batch_held);return graph_ready;}
int full_vef_resources_lock(void){
    assert(!resource_held);++resource_calls;
    if(resource_rc)return resource_rc;
    resource_held=1;
    if(context_drift==2)++movie.movie_generation;
    return 0;
}
void full_vef_resources_unlock(void){assert(resource_held);resource_held=0;++resource_unlocks;}
void pin_control_snapshot(struct pin_control_snapshot *out){assert(resource_held);*out=fixture.control;}
void full_pin_connection_snapshot(struct pin_connection_snapshot *out){assert(resource_held);*out=fixture.connection;}
void full_vef_snapshot(struct full_vef_snapshot *out){assert(resource_held);*out=fixture.vef;}
void full_pinmem_snapshot(struct full_vef_snapshot *out){assert(resource_held);*out=fixture.pinmem;}
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out){assert(resource_held);memset(out,0,sizeof *out);}
void full_hdmi_pin_snapshot(struct full_vef_snapshot *out){assert(resource_held);memset(out,0,sizeof *out);}
enum full_vef_dmm_domain full_vef_resource_dmm_domain(const struct full_vef_resource_snapshot *s){
    assert(resource_held && s->dmm.slots[0].handle==0x41 && s->dmm.slots[1].handle==0x42);
    return (enum full_vef_dmm_domain)domain;
}
int full_vef_resources_admissible(const struct full_vef_resource_snapshot *s){assert(resource_held && s);return admissible;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){
    assert(logger==record);++bridge_calls;
    if(context_drift==1)++movie.movie_generation;
    return bridge_rc;
}
static unsigned int size_api(void *p){assert(p==request_wire && !forbid_snapshot);++size_calls;return message_bytes;}
static unsigned int source_api(void *p){assert(p==request_wire && !forbid_snapshot);++source_calls;return message_source;}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static int free_api(unsigned int id,void *p){
    assert(id && p && !ticket_held && !batch_held);
    if(p==request_wire)++free_calls;else{assert(p==foreign_wire);++ordinary_frees;}
    errno=ENOTTY;return free_rc;
}
static int (*real_free_msg)(unsigned int,void *)=free_api;
static int allocate_api(unsigned int id,void **out,unsigned int bytes,unsigned int count){
    assert(!dispatch_active && id && bytes && count);++allocation_calls;
    if(out)*out=allocation_null?NULL:allocated_pointer;
    errno=raw_errno;return allocation_rc;
}
/* ACTUAL_OU_ALLOCATOR_DECLARATIONS */
static void native_movie_format_allocated(unsigned int id,void **out,int result,unsigned int count){
    (void)id;(void)out;(void)result;(void)count;++movie_observations;
    if(movie_observations==1)errno=EDOM;
}
static void native_pin_peer_allocated(unsigned int id,void **out,int result,unsigned int count){
    (void)id;(void)out;(void)result;(void)count;++peer_allocation_observations;
}
static void native_crank_allocated(unsigned int id,void **out,int result,unsigned int count){
    (void)id;(void)out;(void)result;(void)count;++crank_allocation_observations;
}
static void native_face_sdk_observation(unsigned int kind,unsigned int id,void *p,unsigned int bytes,int result,void *caller){
    (void)id;(void)p;(void)bytes;(void)result;assert(kind==1 && caller);++sdk_observations;
}
static void source_set_api(void *p,unsigned int id){(void)p;(void)id;assert(!"OU must not set reply source");}
static void (*real_set_source)(void *,unsigned int)=source_set_api;
static int send_api(unsigned int id,void *p){(void)id;(void)p;assert(!"OU must not send ACK or notification");return -ENOSYS;}
static int (*real_send_msg)(unsigned int,void *)=send_api;
static int cp_ee_controls_reserve_resources(void){assert(0);return -ENODATA;}
static int cp_ee_controls_predecessors_ready(void){assert(0);return 0;}
static int cp_ee_controls_after_movie_predecessors_ready(void){assert(0);return 0;}
int native_cp_ee_controls_diagnostic_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
    const struct native_cp_ee_controls_diagnostic_guard *guard,int enabled,int *result){
    assert(enabled==1 && cp_ee_controls_used && id==NATIVE_CP_EE_CONTROLS_SID && p==request_wire);
    assert(io->release==real_free_msg && io->allocate==real_allocate_msg && io->send==real_send_msg);
    assert(guard->reserve==cp_ee_controls_reserve_resources && guard->predecessor_ready==cp_ee_controls_after_movie_predecessors_ready);
    ++legacy_calls;*result=-777;return 1;
}
int native_functional_camera_ou_crank_release(unsigned int id,void *p,int (*release)(unsigned int,void *),
    void (*logger)(const char *,const char *),int *result,uint64_t transaction){
    assert(release==real_free_msg && logger==record && result && !ticket_held);
    ++release_calls;last_release_ticket=transaction;
    if(!transaction){
        if(p!=ou.retained_request)return 0;
        *result=-ESTALE;return 1;
    }
    if(transaction!=event_transaction || ou.transaction!=transaction || ou.complete || ou.request_freed ||
       id!=FUNCTIONAL_CAMERA_CONTROL_SID || p!=request_wire || ou.sender_tid!=actual_tid()){
        *result=-ESTALE;return 1;
    }
    *result=release(id,p);
    if(!*result){ou.request_freed=1;ou.retained_request=NULL;ou.free_tid=actual_tid();ou.complete=!ou.faults;}
    else ou.faults=1;
    return 1;
}
int native_functional_camera_ou_crank_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard,const struct native_functional_camera_ou_crank_context *context,
    int enabled,int *result){
    assert(enabled==1 && id==FUNCTIONAL_CAMERA_CONTROL_SID && p==request_wire && context);
    assert(functional_cp_ou_crank_control_used && io->release==native_ou_crank_real_free);
    assert(io->allocate==real_allocate_msg && io->set_source==real_set_source && io->send==real_send_msg);
    assert(io->size==real_msg_size && io->source==real_get_source && io->record==record);
    assert(guard->reserve==functional_cp_ou_crank_control_reserve_resources &&
           guard->predecessor_ready==functional_cp_ou_crank_control_predecessors_ready && guard->release==full_vef_resources_unlock);
    ++owner_calls;captured_context=*context;
    assert(!memcmp(context,&expected_context,sizeof *context));
    if(!owner_handled)return 0;
    *result=owner_rc;
    if(*result)return 1;
    if(request_wire[8] || request_wire[9] || request_wire[10] || request_wire[11]){*result=-ENOTSUP;return 1;}
    *result=guard->reserve();
    if(*result)return 1;
    if(context->model_instance!=bank.model_instance || context->bank_generation!=bank.bank_generation ||
       context->crank_generation!=crank.crank_generation || context->movie_generation!=movie.movie_generation){
        *result=-ESTALE;guard->release();return 1;
    }
    if(guard->predecessor_ready()!=1){*result=-ENODATA;guard->release();return 1;}
    dispatch_active=1;++before_calls;*result=before_rc;
    if(!*result){++model_calls;ou.model_called=1;ou.model_rc=model_rc;ou.model_committed=!model_rc;*result=model_rc;}
    if(!*result)*result=validation_rc;
    if(!*result){++after_calls;*result=after_rc;}
    if(*result){dispatch_active=0;guard->release();return 1;}
    ou.owned=ou.verified=1;ou.request_pointer=ou.retained_request=p;ou.transaction=event_transaction;
    ou.origin.destination=id;ou.sender_tid=actual_tid();
    if(!skip_free){
        ou.releasing=1;
        int rc=io->release(id,p);
        assert(errno==ENOTTY);
        ou.releasing=0;ou.free_rc=rc;
        if(!rc){ou.request_freed=1;ou.retained_request=NULL;ou.free_tid=actual_tid();ou.complete=1;}
        else ou.faults=1;
    }
    dispatch_active=0;
    if(reuse_before_return){
        void *reused=NULL;
        assert(!real_allocate_msg(id,&reused,12,1) && reused==p);
    }
    guard->release();
    expect_postdispatch_snapshot=1;
    if(postdispatch_drift)++functional_cp_ou_crank_control_ticket_pid;
    *result=0;return 1;
}
static int same_name(const char *a,const char *b){return a && b && !strcmp(a,b);}
int native_functional_camera_control_owner_init(void){++control_init_calls;return 0;}
int native_functional_camera_parameter_owner_init(void){assert(control_init_calls==1);++parameter_init_calls;return 0;}
int native_functional_camera_crank_owner_init(void){assert(parameter_init_calls==1);++crank_init_calls;return 0;}
int native_functional_camera_movie_format_owner_init(void){assert(crank_init_calls==1);++movie_init_calls;return 0;}
int native_functional_camera_ou_crank_owner_init(void){assert(movie_init_calls==1 && !still_init_calls);++ou_init_calls;return ou_init_rc;}
/* Constructor compatibility only; no timecode business result is established. */
int full_bb_timecode_control_owner_init(void){return 0;}
int functional_still_format_owner_init(void){assert(ou_init_calls==1 && !ou_init_rc);++still_init_calls;return 0;}
int functional_startup_control_owner_init(void){assert(still_init_calls==1);++startup_init_calls;return 0;}

/* ACTUAL_OU_HELPERS */
static int actual_send(unsigned int id,void *message){
/* ACTUAL_OU_ROUTE */
/* ACTUAL_OU_STRICT_ROUTE */
    ++fallback_calls;return -999;
}
static int actual_free(unsigned int id,void *message){
/* ACTUAL_OU_FREE */
    return real_free_msg(id,message);
}
static void actual_init(const char *functional_profile){
/* ACTUAL_OU_INIT */
}
static void put64(unsigned char *p,uint64_t value){for(unsigned int i=0;i<8;i++)p[i]=(unsigned char)(value>>(8*i));}
static void ready(void){
    original_pid=getpid();functional_cp_ou_crank_control_ticket_pid=(unsigned int)getpid();
    native_real_allocate_msg=allocate_api;real_allocate_msg=native_tracked_allocate_msg;
    proc.owner_pid=input.owner_pid=output.owner_pid=getpid();proc.configured=input.configured=output.configured=1;
    proc.clean_completion=input.clean_completion=output.clean_completion=proc.ap_consumed=input.ap_consumed=output.ap_consumed=1;
    proc.request_freed=input.request_freed=output.request_freed=proc.reply_freed=input.reply_freed=output.reply_freed=1;
    control.owner_pid=bank.owner_pid=crank.owner_pid=movie.owner_pid=ou.owner_pid=getpid();
    control.initialized=control.functional_model=control.business_ready=control.model_initialized=control.start_complete=control.mode1_complete=control.mode_complete=control.notification_ap_consumed=1;
    control.mode1_cycles_completed=1;control.model_instance=77;
    for(unsigned int i=0;i<FUNCTIONAL_CAMERA_CONTROL_LEASES;i++)control.leases[i].freed=1;
    control.leases[1].consumed=control.leases[3].consumed=control.leases[4].consumed=1;
    bank.initialized=bank.model_called=bank.model_committed=bank.verified=bank.owned=bank.request_freed=1;
    bank.model_instance=77;bank.bank_generation=3;bank.transaction=7;bank.commits=bank.released=1;bank.sender_tid=bank.free_tid=62;
    crank.initialized=crank.model_called=crank.model_committed=crank.verified=crank.owned=crank.complete=1;
    crank.reply_received=crank.reply_consumed=crank.request_freed=crank.reply_freed=1;
    crank.requests=crank.commits=crank.verified_commits=crank.completions=1;
    crank.model_instance=77;crank.bank_generation=crank.last_bank_generation=3;
    crank.crank_generation=crank.last_crank_generation=9;crank.transaction=8;
    crank.bank_transaction=7;crank.bank_commits=crank.bank_released=1;
    crank.sender_tid=crank.request_free_tid=crank.reply_free_tid=62;crank.receiver_tid=57;
    movie.initialized=movie.model_called=movie.model_committed=movie.verified=movie.owned=movie.complete=1;
    movie.reply_received=movie.reply_consumed=movie.request_freed=movie.reply_freed=1;
    movie.requests=movie.commits=movie.verified_commits=movie.completions=1;
    movie.model_instance=77;movie.bank_generation=movie.last_bank_generation=3;
    movie.crank_generation=movie.last_crank_generation=9;movie.movie_generation=movie.last_movie_generation=11;
    movie.transaction=12;movie.bank_transaction=7;movie.bank_commits=movie.bank_released=1;
    movie.crank_transaction=8;movie.crank_completions=1;movie.config_generation=24;
    movie.sender_tid=movie.request_free_tid=movie.reply_free_tid=382;movie.receiver_tid=57;
    ou.initialized=1;
    strict.owner_pid=getpid();strict.initialized=1;
    struct native_cp_ee_controls_diagnostic_lease *s=&strict.leases[0];
    s->opcode=0x409d;s->attempts=s->requests=s->queued=s->clean_completion=s->ap_consumed=s->request_freed=s->reply_freed=1;
    s->sender_tid=s->waiter_tid=19;
    s=&strict.leases[1];s->opcode=0x4072;
    s->attempts=s->requests=s->oneway=s->oneway_consumed=s->request_freed=s->clean_completion=1;
    early.owner_pid=getpid();early.initialized=early.diagnostic_only=early.no_publication=1;
    early.opcode=0x4000;early.attempts=early.requests=early.queued=early.clean_completion=early.ap_consumed=early.request_freed=early.reply_freed=1;
    early.sender_tid=early.waiter_tid=382;early.source=early.destination=FULL_IMAGING_AP;
    early.request_destination=NATIVE_CP_MOVIE_FORMAT_SID;early.request_bytes=20;
    early.known_field_mask=early.virtual_field_mask=early.virtual_fields_consumed=CP_MOVIE_FORMAT_KNOWN_MASK;early.virtual_fields_readback=1;
    startup.owner_pid=still.owner_pid=getpid();startup.initialized=still.initialized=1;
    startup.functional_only=startup.state_valid=startup.operation_attempted=startup.model_complete=startup.mode_applied=startup.request_owned=startup.ap_consumed=1;
    startup.command=0x4057;startup.original_wire_bytes=12;startup.model_instance=77;
    startup.cycle=startup.requests=startup.completed_cycles=2;
    startup.command_requests[0]=startup.command_requests[1]=startup.command_completed[0]=startup.command_completed[1]=1;
    startup.before_config_generation=24;startup.config_generation=25;startup.before_frame_generation=21;startup.frame_generation=22;
    startup.before_lease_generation=21;startup.lease_generation=22;
    startup.original_wire[0]=5;startup.original_wire[2]=0x57;startup.original_wire[3]=0x40;
    startup.reply_wire[0]=1;startup.reply_wire[2]=0x57;startup.reply_wire[3]=0x40;startup.reply_wire[9]=0xf0;
    put64(startup.model_state+FCAM_S_INSTANCE,77);
    put64(startup.model_state+FCAM_S_GENERATION,24);put64(startup.model_state+FCAM_S_FRAME_GENERATION,21);
    put64(startup.model_result+8,77);
    put64(startup.model_result+16,25);put64(startup.model_result+24,22);put64(startup.model_result+32,22);
    startup.state_response=(struct fcam_bridge_result){.used=128,.required=128,.model_instance=77};
    startup.control_response=(struct fcam_bridge_result){.used=192,.required=192,.model_instance=77};
    startup.origin=(struct fcam_native_origin){FUNCTIONAL_CAMERA_CONTROL_AP,FUNCTIONAL_CAMERA_CONTROL_SID,0x4057,12,
        native_ou_crank_hash(startup.original_wire,12)};
    startup.actual_origin_fnv=startup.origin.wire_fnv1a64;
    startup.result_fnv=native_ou_crank_hash(startup.model_result,sizeof startup.model_result);
    startup.current_config40_fnv=native_ou_crank_hash(startup.model_state+8,40);
    for(unsigned int i=0;i<2;i++){
        struct native_cp_state_publication_lease *l=&startup.leases[i];
        l->role=i+1;l->bytes=12;l->freed=1;l->sender_tid=l->free_tid=384;
        l->wire_fnv1a64=native_ou_crank_hash(i?startup.reply_wire:startup.original_wire,12);
        if(i){l->queued=l->received=l->consumed=1;l->receiver_tid=57;}
    }
    cp_output_policy_state.owner_pid=getpid();policy.config_consumed=1;
    dmm.physical=DMM_TEST_PHYSICAL;dmm.slots[0].handle=0x41;dmm.slots[1].handle=0x42;
}
static void seed_ticket(void){
    functional_cp_ou_crank_control_used=1;ou.owned=ou.verified=1;ou.transaction=event_transaction;
    ou.request_pointer=ou.retained_request=request_wire;ou.origin.destination=FUNCTIONAL_CAMERA_CONTROL_SID;ou.sender_tid=actual_tid();
    functional_cp_ou_crank_control_ticket.request=request_wire;
    functional_cp_ou_crank_control_ticket.destination=FUNCTIONAL_CAMERA_CONTROL_SID;
    functional_cp_ou_crank_control_ticket.transaction=event_transaction;
}
static void check_route(const char *test){
    int expected=0,called=1,legacy=0;
    if(!strcmp(test,"cold")){bank.model_called=crank.model_called=movie.model_called=0;expected=-777;called=0;legacy=1;}
    else if(!strcmp(test,"disabled")){functional_camera_enabled=0;expected=-777;called=0;legacy=1;}
    else if(!strcmp(test,"late-used-only")){bank.model_called=crank.model_called=movie.model_called=0;functional_cp_movie_format_used=1;expected=-ENODATA;}
    else if(!strcmp(test,"short")){message_bytes=11;expected=-EMSGSIZE;called=0;}
    else if(!strcmp(test,"source")){message_source++;expected=-EPERM;called=0;}
    else if(!strcmp(test,"setup")){functional_camera_setup_error=-EIO;expected=-EIO;called=0;}
    else if(!strcmp(test,"bridge")){bridge_rc=-EIO;expected=-EIO;called=0;}
    else if(!strcmp(test,"body")){request_wire[11]=1;expected=-ENOTSUP;}
    else if(!strcmp(test,"before")){before_rc=-EIO;expected=-EIO;}
    else if(!strcmp(test,"model")){model_rc=-EUCLEAN;expected=-EUCLEAN;}
    else if(!strcmp(test,"postvalidation")){validation_rc=-EPROTO;expected=-EPROTO;}
    else if(!strcmp(test,"after")){after_rc=-ESTALE;expected=-ESTALE;}
    else if(!strcmp(test,"predecessor")){graph_ready=0;expected=-ENODATA;}
    else if(!strcmp(test,"reserve")){resource_rc=-EBUSY;expected=-EBUSY;}
    else if(!strcmp(test,"context-init-drift")){context_drift=1;expected=-ESTALE;}
    else if(!strcmp(test,"context-reserve-drift")){context_drift=2;expected=-ESTALE;}
    else if(!strcmp(test,"owner-unhandled")){owner_handled=0;expected=-ENOTSUP;}
    else if(!strcmp(test,"owner-error")){owner_rc=-ESTALE;expected=-ESTALE;}
    else if(!strcmp(test,"real-free-error"))free_rc=-EACCES;
    else if(!strcmp(test,"real-free-positive"))free_rc=7;
    else if(!strcmp(test,"postdispatch-retained"))skip_free=1;
    else if(!strcmp(test,"postdispatch-historical"))reuse_before_return=1;
    else if(!strcmp(test,"postdispatch-pid"))postdispatch_drift=1;
    else assert(!strcmp(test,"late"));
    expected_context=(struct native_functional_camera_ou_crank_context){bank.model_instance,bank.bank_generation,crank.crank_generation,movie.movie_generation};
    struct native_cp_ee_controls_diagnostic_snapshot saved=strict;
    assert(actual_send(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==expected);
    assert(owner_calls==called && legacy_calls==legacy && !fallback_calls && !resource_held);
    assert(!memcmp(&strict,&saved,sizeof saved));
    assert(!allocation_calls || reuse_before_return);
    if(!expected){
        assert(before_calls==1 && model_calls==1 && after_calls==1 && reserved_tags==1 && tts_tags==1);
        if(!postdispatch_drift){
            assert(postdispatch_reads==1);
            uint64_t ticket=0;
            assert(!native_ou_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire,&ticket));
            assert(ticket==(reuse_before_return?0:event_transaction));
        }
        if(free_rc)assert(ou.retained_request==request_wire && ou.faults && !ou.complete);
        else if(skip_free)assert(ou.retained_request==request_wire && !free_calls);
        else assert(ou.request_freed && !ou.retained_request && free_calls==1);
    }else{
        assert(!free_calls && !allocation_calls);
        if(validation_rc || after_rc)assert(ou.model_committed && !ou.owned);
    }
}
#define MUTATE(label,expression) if(!strcmp(test,label)){expression;}
static void check_predecessor(const char *test){
    if(!strcmp(test,"ready")){}
    else MUTATE("bank-free-thread",bank.free_tid++)
    else MUTATE("bank-unfreed",bank.request_freed=0)
    else MUTATE("crank-bank-transaction",crank.bank_transaction++)
    else MUTATE("movie-commit",movie.model_committed=0)
    else MUTATE("movie-complete",movie.complete=0)
    else MUTATE("movie-generation",movie.movie_generation++)
    else MUTATE("movie-crank-transaction",movie.crank_transaction++)
    else MUTATE("movie-bank-transaction",movie.bank_transaction++)
    else MUTATE("movie-free-thread",movie.reply_free_tid++)
    else MUTATE("movie-receive",movie.reply_received=0)
    else MUTATE("movie-retained",movie.retained_request=request_wire)
    else MUTATE("mode-lease",control.leases[4].pointer=request_wire)
    else MUTATE("strict-attempt",strict.leases[1].attempts++)
    else MUTATE("strict-consumed",strict.leases[1].oneway_consumed=0)
    else MUTATE("strict-free",strict.leases[1].request_freed=0)
    else MUTATE("strict-fault",strict.leases[1].faults=1)
    else MUTATE("settings-command",startup.command=0x4014)
    else MUTATE("settings-cycle",startup.completed_cycles--)
    else MUTATE("settings-generation",startup.config_generation++)
    else MUTATE("settings-seal",startup.result_fnv++)
    else MUTATE("settings-config40",startup.current_config40_fnv++)
    else MUTATE("settings-request-free",startup.leases[0].freed=0)
    else MUTATE("settings-reply-free",startup.leases[1].freed=0)
    else MUTATE("settings-free-thread",startup.leases[1].free_tid++)
    else MUTATE("settings-receive",startup.leases[1].received=0)
    else MUTATE("settings-state",startup.model_state[FCAM_S_GENERATION]++)
    else assert(0);
    assert(functional_cp_ou_crank_control_predecessors_ready()==!strcmp(test,"ready"));
    assert(!bridge_calls && !model_calls && !free_calls && !resource_calls);
}
#undef MUTATE
static void check_resource(const char *test,int index){
    functional_cp_ou_crank_control_used=1;int expected=0;
    if(!strcmp(test,"busy")){ou.busy=1;expected=-ENODATA;}
    else if(!strcmp(test,"fault")){ou.faults=1;expected=-ENODATA;}
    else if(!strcmp(test,"guard")){ou.guard_held=1;expected=-ENODATA;}
    else if(!strcmp(test,"guard-fault")){ou.guard_fault=1;expected=-ENODATA;}
    else if(!strcmp(test,"retained")){ou.retained_request=request_wire;expected=-ENODATA;}
    else if(!strcmp(test,"releasing")){ou.releasing=1;expected=-ENODATA;}
    else if(!strcmp(test,"owned")){ou.owned=1;expected=-ENODATA;}
    else if(!strcmp(test,"wrong-pid")){ou.owner_pid++;expected=-ENODATA;}
    else if(!strcmp(test,"uninitialized")){ou.initialized=0;expected=-ENODATA;}
    else if(!strcmp(test,"self")){assert(index==36);ou.busy=ou.faults=ou.guard_held=ou.owned=ou.releasing=1;ou.retained_request=request_wire;}
    else if(!strcmp(test,"complete")){ou.owned=ou.complete=ou.request_freed=1;}
    else if(!strcmp(test,"dmm")){domain=FULL_VEF_DMM_EMPTY;expected=-1021;}
    else if(!strcmp(test,"resource-error")){resource_rc=-EBUSY;expected=-EBUSY;}
    else if(!strcmp(test,"invalid"))expected=-1021;
    else assert(!strcmp(test,"idle"));
    assert(tracked_native_reserve_resources(index)==expected);
    if(!expected){assert(resource_held);full_vef_resources_unlock();}
    if(expected==-ENODATA)assert(!resource_calls);
    if(index==36 && !expected)assert(reserved_tags==1 && tts_tags==1);
    if(index==36 && resource_rc)assert(fault_tags==1);
}
static void check_ticket(const char *test){
    seed_ticket();int expected=0;
    if(!strcmp(test,"stale")){ou.transaction++;expected=-ESTALE;}
    else if(!strcmp(test,"duplicate")){ou.request_freed=ou.complete=1;ou.retained_request=NULL;expected=-ESTALE;}
    else if(!strcmp(test,"wrong-pid")){functional_cp_ou_crank_control_ticket_pid++;expected=-ESTALE;}
    else if(!strcmp(test,"mutex-error")){ticket_lock_rc=EINVAL;expected=-EIO;}
    else if(!strcmp(test,"free-error")){free_rc=-EACCES;expected=-EACCES;}
    else assert(!strcmp(test,"free"));
    int reads=ou_reads,before=locks;forbid_snapshot=1;
    assert(actual_free(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==expected && ou_reads==reads);
    forbid_snapshot=0;
    assert(last_release_ticket==event_transaction || !strcmp(test,"wrong-pid") || !strcmp(test,"mutex-error"));
    if(!strcmp(test,"wrong-pid") || !strcmp(test,"mutex-error"))assert(locks==before && !release_calls);
    if(expected==-ESTALE || expected==-EIO)assert(!free_calls);
    else assert(free_calls==1 && errno==ENOTTY);
    assert(functional_cp_ou_crank_control_ticket.transaction==event_transaction);
}
static void check_allocation(const char *test){
    seed_ticket();ou.request_freed=ou.complete=1;ou.retained_request=NULL;
    int expected_clear=1,outer=0;unsigned int count=1,id=FUNCTIONAL_CAMERA_CONTROL_SID;void *out=NULL;void **target=&out;
    if(!strcmp(test,"negative")){allocation_rc=-ENOMEM;expected_clear=0;}
    else if(!strcmp(test,"positive")){allocation_rc=7;expected_clear=0;}
    else if(!strcmp(test,"multi")){count=2;expected_clear=0;}
    else if(!strcmp(test,"null")){allocation_null=1;expected_clear=0;}
    else if(!strcmp(test,"null-output")){target=NULL;expected_clear=0;}
    else if(!strcmp(test,"foreign")){allocated_pointer=foreign_wire;expected_clear=0;}
    else if(!strcmp(test,"wrong-pid")){functional_cp_ou_crank_control_ticket_pid++;expected_clear=0;}
    else if(!strcmp(test,"public"))outer=1;
    else if(!strcmp(test,"borrowed")){outer=1;id=0x912503d0;}
    else assert(!strcmp(test,"reuse"));
    int before=locks;forbid_snapshot=1;errno=ENOTTY;
    int rc=outer?osal_valloc_msg_wait(id,target,20,count):real_allocate_msg(id,target,12,count);
    assert(rc==allocation_rc && errno==raw_errno);
    forbid_snapshot=0;
    assert(allocation_calls==1 && movie_observations==(outer?2:1) && !ou_reads);
    assert(peer_allocation_observations==(unsigned int)outer && crank_allocation_observations==(unsigned int)outer);
    assert(sdk_observations==(unsigned int)(outer && id!=0x912503d0));
    assert((functional_cp_ou_crank_control_ticket.transaction==0)==expected_clear);
    if(!expected_clear && strcmp(test,"foreign"))assert(locks==before);
    if(expected_clear){
        forbid_snapshot=1;assert(!actual_free(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire));forbid_snapshot=0;
        assert(free_calls==1 && !last_release_ticket);
    }
}
static void check_fork(void){
    seed_ticket();hold_ticket_lock();pid_t child=fork();assert(child>=0);
    if(!child){
        int before=locks,result=0;void *out=NULL;uint64_t ticket=99;
        assert(native_ou_crank_ticket_for(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire,&ticket)==-ESTALE && !ticket);
        assert(native_functional_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire,&result) && result==-ESTALE);
        assert(native_ou_crank_real_free(FUNCTIONAL_CAMERA_CONTROL_SID,request_wire)==-ESTALE);
        assert(!real_allocate_msg(FUNCTIONAL_CAMERA_CONTROL_SID,&out,12,1) && errno==raw_errno);
        assert(out==request_wire && locks==before && !ou_reads && !free_calls);_exit(0);
    }
    drop_ticket_lock();int status=-1;
    assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
}
int main(int argc,char **argv){
    assert(argc>=3);ready();
    if(!strcmp(argv[1],"route"))check_route(argv[2]);
    else if(!strcmp(argv[1],"predecessor"))check_predecessor(argv[2]);
    else if(!strcmp(argv[1],"resource")){assert(argc==4);check_resource(argv[2],atoi(argv[3]));}
    else if(!strcmp(argv[1],"ticket"))check_ticket(argv[2]);
    else if(!strcmp(argv[1],"allocation"))check_allocation(argv[2]);
    else if(!strcmp(argv[1],"fork"))check_fork();
    else if(!strcmp(argv[1],"init")){
        const char *profile=FCAM_PROFILE;
        if(!strcmp(argv[2],"failed"))ou_init_rc=-ENOMEM;
        else if(!strcmp(argv[2],"disabled"))profile=NULL;
        else assert(!strcmp(argv[2],"local"));
        actual_init(profile);int enabled=profile && !ou_init_rc;
        assert(ou_init_calls==(profile!=NULL) && still_init_calls==enabled && startup_init_calls==enabled);
        assert(functional_camera_enabled==enabled && functional_cp_ou_crank_control_ticket_pid==(unsigned int)getpid());
        assert(!bridge_calls && !allocation_calls && !free_calls);
    }else assert(0);
    assert(locks==unlocks && !ticket_held && !batch_held && !resource_held);
    puts("PASS actual Main OU wiring MOCK; Core/native AP/capture unverified");return 0;
}
