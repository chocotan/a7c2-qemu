"""Execute actual VDF/local layout setup, receive/free tickets and late bind without a VM."""
from pathlib import Path
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def vdf_wiring_binary(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    received = function(source, 'native_cp_state_received')
    freed = function(source, 'osal_free_msg')
    freed = freed[freed.index('    if(__atomic_load_n(&functional_layout_stage_used'):freed.index('    if(__atomic_load_n(&functional_camera_control_used')]
    sent = function(source, 'osal_snd_msg')
    sent = sent[sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_VDF_PATH_SID'):sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_JPEG_CODEC_SID)')]
    sent = sent.replace('__builtin_return_address(0)', 'fixture_caller')
    tickets = '\n'.join(next(line for line in source.splitlines()
                             if line.startswith('static _Thread_local struct') and name in line)
                        for name in ('functional_layout_stage_ticket', 'functional_vdf_ticket'))
    snippets = '\n'.join(function(source, name) for name in (
        'functional_cp_zoom_prepare', 'functional_cp_zoom_reserve_resources',
        'functional_cp_zoom_release_resources', 'functional_layout_stage_prepare',
        'functional_layout_stage_bind_model', 'functional_camera_global_queue_bind', 'functional_vdf_prepare'))
    snippets += '\n' + received + '\n' + function(source, 'u_osal_rcv_msg_tmo')
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "device-models/functional-vdf-path.h"
#include "device-models/functional-vdf-layout-stage.h"
#include "device-models/functional-cp-zoom.h"
static int functional_camera_setup_error,owner_result,bridge_result,owner_calls,bridge_calls,release_result;
static int functional_camera_enabled=1,graph_ready=1,dispatch_calls,path_dispatch_result;
static unsigned char request_storage[40],*request_wire=request_storage;static unsigned int request_bytes=24;
static int release_request_in_dispatch;
static unsigned long appfw_base=0x10000000UL;
static void *fixture_caller=(void *)(0x10000000UL+0x34e4f3cUL);
static unsigned int request_source=0x81cf61c4,expected_destination=0x81cf61c4;
static unsigned int refresh_globals[2]={0x80946189,0x80946189},refresh_bound_source;
static int refresh_open_calls,refresh_read_calls,refresh_close_calls,refresh_bind_calls,refresh_bind_result;
static int refresh_open_failure,refresh_bad_read=-1,refresh_read_result,refresh_logs;
static char refresh_log[512];
static int refresh_open(const char *path,int flags){
 assert(!strcmp(path,"/proc/self/mem") && !flags);refresh_open_calls++;errno=EACCES;
 return refresh_open_failure?-1:23;
}
static long refresh_read(int fd,void *out,size_t bytes,long offset){
 assert(fd==23 && out && bytes==4 && (unsigned long)offset==appfw_base+0x910fa30UL);
 int index=refresh_read_calls++;errno=EIO;
 if(index==refresh_bad_read)return refresh_read_result;
 memcpy(out,&refresh_globals[(unsigned int)index%2],4);return 4;
}
static int refresh_close(int fd){assert(fd==23);refresh_close_calls++;errno=EBADF;return 0;}
#define open refresh_open
#define pread refresh_read
#define close refresh_close
static long refresh_tid(long number){assert(number==178);return (long)getpid();}
#define syscall refresh_tid
int functional_vdf_path_bind_refresh_queue(unsigned int source){
 assert(source==request_source && source==refresh_globals[0] && source==refresh_globals[1]);
 refresh_bind_calls++;refresh_bound_source=source;errno=E2BIG;return refresh_bind_result;
}
int functional_histogram_bind_queue(unsigned int source){(void)source;assert(0);return -EINVAL;}
static unsigned int functional_still_format_used,functional_startup_control_used;
static void native_startup_control_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;assert(!"startup-control is disabled in this VDF fixture");
}
static void native_still_format_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;assert(0);
}
static void native_functional_face_received(unsigned int id,void *p){(void)id;(void)p;}
static void native_background_start_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;
}
static void native_histogram_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;
}
static unsigned int functional_vdf_binding,functional_vdf_path_used=1,receive_calls,free_calls;
static uint64_t supplied_cycle=7,last_free_cycle;
static unsigned int functional_layout_stage_binding,functional_layout_stage_used;
static int functional_layout_stage_error,stage_owner_result,stage_owner_calls,stage_dispatch_calls;
static int stage_dispatch_result,stage_dispatch_handled=1,stage_receive_result=1,stage_receive_calls;
static int stage_release_result,stage_release_calls,stage_snapshot_calls,path_snapshot_calls,read_bank_calls,bind_calls;
static int read_bank_result,bind_result,bind_failed_logs,stage_retained_logs,full_bb_set_mode_enabled=1,bb_result,bb_calls;
static uint64_t supplied_stage_cycle=23,last_stage_free_cycle,read_bank_digest;
static struct functional_vdf_layout_stage_snapshot staged_state;
static struct functional_vdf_path_snapshot path_state,*last_path_snapshot;
static unsigned char read_bank_data[FCAM_LAYOUT_INPUT_BYTES];
/* B=BB prefix, O=local owner, S=stage, D=VDF, L/P=snapshots, R=read bank, A=bind applied. */
static char call_order[96];static unsigned int call_order_bytes;
static const unsigned char canonical_request[40]={
 0x0d,0x20,0x4c,1,40,0,1,0x80,7,1,1,0,0,0,0,0,0x80,2,0xe0,1,
 0,0,0,0,0,0,0,0,0,0,0,0,3,0,0,0,0,0,0,0
};
static int cp_owned_state_enabled,native_receive_result,native_receive_calls;
static unsigned int functional_cp_zoom_used,functional_mpr_codec_used;
static _Thread_local unsigned int native_receive_depth;
static void *received_pointer;
static struct cp_parameter_state cp_owned_parameters;
static unsigned long cp_owned_state_mutex[6];
static unsigned int functional_cp_zoom_binding;
static int functional_cp_zoom_setup_error,zoom_bind_calls,zoom_owner_result;
static int zoom_parameter_held,zoom_dmm_held,zoom_lock_failure,zoom_locks;
static int parameter_lock(void *p){
 assert(p==cp_owned_state_mutex && !zoom_parameter_held);zoom_locks++;
 if(zoom_lock_failure)return EBUSY;
 zoom_parameter_held=1;return 0;
}
static int parameter_unlock(void *p){assert(p==cp_owned_state_mutex && zoom_parameter_held);zoom_parameter_held=0;return 0;}
#define pthread_mutex_lock parameter_lock
#define pthread_mutex_unlock parameter_unlock
static int tracked_native_reserve_resources(int requester){assert(requester==27 && !zoom_dmm_held);zoom_dmm_held=1;return 0;}
int functional_cp_zoom_owner_init(struct cp_parameter_state *p){
 assert(p==&cp_owned_parameters && zoom_parameter_held);zoom_bind_calls++;return zoom_owner_result;
}
static void record(const char *tag,const char *text){
 assert(tag && text);
 if(!strcmp(tag,"FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND ")){
  assert(strstr(text,"global_va=0x910fa30") && strstr(text,"capture_verified=0"));
  assert(strlen(text)<sizeof refresh_log);strcpy(refresh_log,text);refresh_logs++;
 }
 if(!strcmp(tag,"FUNCTIONAL_LAYOUT_STAGE_BIND_FAILED ")){
  char expected[32];snprintf(expected,sizeof expected,"rc=%d ",functional_layout_stage_error);
  assert(functional_camera_setup_error==functional_layout_stage_error && strstr(text,expected) && strstr(text,"capture_verified=0"));
  bind_failed_logs++;
 }
 if(!strcmp(tag,"FUNCTIONAL_LAYOUT_STAGE_TICKET_RETAINED ")){
  assert(strstr(text,"no_refresh=1") && strstr(text,"capture_verified=0"));stage_retained_logs++;
 }
}
int functional_vdf_path_owner_init(void){owner_calls++;return owner_result;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){
 assert(logger==record);bridge_calls++;return bridge_result;
}
static unsigned int source_api(void *message){assert(message);return message==request_wire?request_source:FUNCTIONAL_VDF_PATH_SID;}
static unsigned int (*real_get_source)(void *)=source_api;
static unsigned int message_size_api(void *message){assert(message);return message==request_wire?request_bytes:12;}
static unsigned int (*real_msg_size)(void *)=message_size_api;
static int real_free_msg(unsigned int id,void *message){assert(id && message);free_calls++;return 0;}
static int real_allocate_msg(unsigned int id,void **p,unsigned int bytes,unsigned int option){
 assert(id && p && bytes && option);return -ENOMEM;
}
static void real_set_source(void *p,unsigned int id){assert(p && id);}
static int real_send_msg(unsigned int id,void *p){assert(id && p);return 0;}
static int cp302c_no_transition_predecessors_ready(void){return graph_ready;}
static int functional_vdf_path_reserve_resources(void){return 0;}
static void full_vef_resources_unlock(void){assert(zoom_dmm_held && !zoom_parameter_held);zoom_dmm_held=0;}
static void step(char c){assert(call_order_bytes+1<sizeof call_order);call_order[call_order_bytes++]=c;}
static void check_io(const struct full_imaging_io *io){
 assert(io && io->allocate==real_allocate_msg && io->release==real_free_msg && io->set_source==real_set_source);
 assert(io->send==real_send_msg && io->size==real_msg_size && io->source==real_get_source && io->record==record);
}
int functional_vdf_path_dispatch(unsigned int id,void *message,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 assert(id==FUNCTIONAL_VDF_PATH_SID && message==request_wire && guard && enabled==1);
 check_io(io);assert(functional_vdf_binding==2 && graph_ready);
 assert(guard->reserve==functional_vdf_path_reserve_resources && guard->release==full_vef_resources_unlock);
 assert(guard->predecessor_ready==cp302c_no_transition_predecessors_ready);
 step('D');dispatch_calls++;*result=path_dispatch_result;
 if(request_bytes==8 && ((unsigned char *)message)[2]==0x41)
  assert(refresh_bind_calls==1 && refresh_bound_source==0x80946189 && refresh_logs==1);
 if(release_request_in_dispatch){free(message);request_wire=0;}
 return 1;
}
int functional_vdf_path_observe_receive_cycle(unsigned int id,void *message,unsigned int origin,unsigned int bytes,uint64_t *cycle){
 assert(id==expected_destination && message && origin==FUNCTIONAL_VDF_PATH_SID && bytes==12);
 assert(native_receive_calls && !native_receive_depth && !native_receive_result);
 receive_calls++;*cycle=supplied_cycle;return 1;
}
int functional_vdf_path_release_cycle(unsigned int id,void *message,uint64_t cycle,int (*free_message)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result){
 assert(id && message && free_message==real_free_msg && logger==record);
 last_free_cycle=cycle;*result=release_result;return 1;
}
static int full_bb_set_mode_observe_input(unsigned int id,void *message,const struct full_imaging_io *io){
 assert(id==FUNCTIONAL_LAYOUT_STAGE_SID && message==request_wire && !graph_ready);
 check_io(io);step('B');bb_calls++;return bb_result;
}
int functional_vdf_layout_stage_owner_init(void){
 assert(!owner_calls && !bridge_calls);step('O');stage_owner_calls++;return stage_owner_result;
}
int functional_vdf_layout_stage_dispatch(unsigned int id,void *message,const struct full_imaging_io *io,
 int enabled,int route_ready,int *result){
 assert(id==FUNCTIONAL_LAYOUT_STAGE_SID && message==request_wire && request_bytes==40);
 assert(enabled==1 && route_ready==0 && !graph_ready && functional_layout_stage_binding==2 && functional_layout_stage_used==1);
 check_io(io);step('S');stage_dispatch_calls++;
 /* The module tests own bank validation; this mock requires an explicit canonical fixture. */
 *result=memcmp(message,canonical_request,sizeof canonical_request)?-EINVAL:stage_dispatch_result;
 return stage_dispatch_handled;
}
int functional_vdf_layout_stage_observe_receive_cycle(unsigned int id,void *message,unsigned int origin,
 unsigned int bytes,uint64_t *ticket){
 assert(id==0x81cf61c4 && message==received_pointer && origin==FUNCTIONAL_LAYOUT_STAGE_SID && bytes==12 && ticket);
 assert(native_receive_calls && !native_receive_depth && !native_receive_result);
 stage_receive_calls++;if(stage_receive_result==1)*ticket=supplied_stage_cycle;errno=EDOM;return stage_receive_result;
}
int functional_vdf_layout_stage_release_cycle(unsigned int id,void *message,uint64_t ticket,
 int (*free_message)(unsigned int,void *),void (*logger)(const char *,const char *),int *result){
 assert(id && message && free_message==real_free_msg && logger==record);
 stage_release_calls++;last_stage_free_cycle=ticket;*result=stage_release_result;return 1;
}
void functional_vdf_layout_stage_snapshot(struct functional_vdf_layout_stage_snapshot *out){
 assert(out);step('L');stage_snapshot_calls++;*out=staged_state;
}
void functional_vdf_path_snapshot(struct functional_vdf_path_snapshot *out){
 assert(out && stage_snapshot_calls>path_snapshot_calls);step('P');path_snapshot_calls++;
 *out=path_state;last_path_snapshot=out;
}
int functional_vdf_layout_stage_read_bank(uint64_t generation,void *out,size_t bytes,uint64_t *digest){
 assert(generation==staged_state.stage_generation && out && out!=staged_state.bank32 && digest);
 assert(bytes==FCAM_LAYOUT_INPUT_BYTES && path_snapshot_calls>read_bank_calls);
 step('R');read_bank_calls++;if(read_bank_result)return read_bank_result;
 memcpy(out,read_bank_data,bytes);*digest=read_bank_digest;return 0;
}
int functional_vdf_layout_stage_bind_applied(uint64_t generation,int pid,uint64_t instance,
 const void *model,size_t bytes,const struct fcam_bridge_result *metadata){
 assert(generation==staged_state.stage_generation && pid==getpid() && instance==path_state.model_instance);
 assert(last_path_snapshot && model==last_path_snapshot->model_result && model!=path_state.model_result);
 assert(bytes==FCAM_LAYOUT_RESULT_BYTES && !memcmp(model,path_state.model_result,bytes));
 assert(metadata && metadata->used==192 && metadata->required==192 && metadata->model_instance==instance && !metadata->result_token);
 assert(read_bank_calls>bind_calls);step('A');bind_calls++;return bind_result;
}
int functional_cp_zoom_release(unsigned int id,void *message,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result){
 assert(id && message && release==real_free_msg && logger==record && result);return 0;
}
static int functional_camera_events_observe_receive(unsigned int id,void *message,unsigned int origin,unsigned int bytes){
 assert(id && message && origin==FUNCTIONAL_VDF_PATH_SID && bytes==12);return 0;
}
static int functional_jpeg_codec_observe_received(unsigned int id,void *message,const struct full_imaging_io *io){
 assert(id && message);check_io(io);return 0;
}
static int functional_mpr_codec_observe_received(unsigned int id,void *message,const struct full_imaging_io *io){
 assert(id && message);check_io(io);return 0;
}
int native_cp_state_publication_observe_receive(unsigned int id,void *message,unsigned int origin,unsigned int bytes){
 assert(id && message && origin==FUNCTIONAL_VDF_PATH_SID && bytes==12);return 0;
}
static void native_hdmi_video_received(unsigned int id,void **message,int result){(void)id;(void)message;(void)result;}
static int receive_api(unsigned int id,void **message,long timeout){
 assert(id && timeout==27 && native_receive_depth);native_receive_calls++;
 if(message)*message=received_pointer;
 errno=ERANGE;return native_receive_result;
}
static int (*real_u_rcv_msg_tmo)(unsigned int,void **,long)=receive_api;
''' + tickets + '\n' + snippets + r'''
static int actual_send(unsigned int id,void *message){
''' + sent + r'''
 return -999;
}
static int actual_receive(unsigned int id,void **message){
 received_pointer=message?*message:0;return u_osal_rcv_msg_tmo(id,message,27);
}
static int actual_free(unsigned int id,void *message){
 int vdf_result;
''' + freed + r'''
 return -999;
}
static void layout_request(void){request_bytes=sizeof canonical_request;memcpy(request_wire,canonical_request,sizeof canonical_request);}
static uint64_t fnv(const unsigned char *p,size_t bytes){
 uint64_t digest=UINT64_C(14695981039346656037);
 for(size_t i=0;i<bytes;i++)digest=(digest^p[i])*UINT64_C(1099511628211);
 return digest;
}
static void bind_input(void){
 layout_request();functional_layout_stage_used=1;
 staged_state.stage_generation=UINT64_C(0x123456789);staged_state.bank_fnv1a64=fnv(canonical_request+8,32);
 /* The read_bank copy is independent of snapshot.bank32; these are interface inputs, no frame proof. */
 memset(staged_state.bank32,0xa5,sizeof staged_state.bank32);
 memcpy(read_bank_data,canonical_request+8,sizeof read_bank_data);read_bank_digest=staged_state.bank_fnv1a64;
 path_state.origin.command=0x014c;path_state.model_complete=1;path_state.model_result_bytes=192;
 path_state.model_instance=UINT64_C(0xfedcba9876543210);
 memcpy(path_state.canonical_layout32,canonical_request+8,sizeof path_state.canonical_layout32);
 for(size_t i=0;i<sizeof path_state.model_result;i++)path_state.model_result[i]=(unsigned char)(i+0x80u);
}
static void expect_bind_failure(int expected){
 assert(!actual_send(FUNCTIONAL_VDF_PATH_SID,request_wire));
 assert(functional_layout_stage_error==expected && functional_camera_setup_error==expected);
 int previous_dispatch=dispatch_calls,previous_logs=bind_failed_logs;unsigned int previous_order=call_order_bytes;
 assert(actual_send(FUNCTIONAL_VDF_PATH_SID,request_wire)==expected);
 assert(dispatch_calls==previous_dispatch && bind_failed_logs==previous_logs && call_order_bytes==previous_order);
 /* Each next probe is an independent fixture input, after verifying the production sticky failure. */
 functional_camera_setup_error=0;functional_layout_stage_error=0;
}
int main(int argc,char **argv){
 assert(argc==2);unsigned char storage[12]={0};void *message=storage;
 if(!strcmp(argv[1],"success")){
  assert(!functional_vdf_prepare() && owner_calls==1 && bridge_calls==1 && functional_vdf_binding==2);
  assert(!functional_vdf_prepare() && owner_calls==1 && bridge_calls==1);
 }else if(!strcmp(argv[1],"owner-failure")){
  owner_result=-ENOMEM;assert(functional_vdf_prepare()==-ENOMEM && !bridge_calls);
  assert(functional_vdf_prepare()==-ENOMEM && owner_calls==1 && functional_vdf_binding==3);
 }else if(!strcmp(argv[1],"bridge-failure")){
  bridge_result=-EIO;assert(functional_vdf_prepare()==-EIO && owner_calls==1 && bridge_calls==1);
  assert(functional_vdf_prepare()==-EIO && owner_calls==1 && bridge_calls==1);
 }else if(!strcmp(argv[1],"busy")){
  functional_vdf_binding=1;assert(functional_vdf_prepare()==-EBUSY && !owner_calls && !bridge_calls);
 }else if(!strcmp(argv[1],"ticket")){
  actual_receive(0x81cf61c4,&message);assert(functional_vdf_ticket.pointer==message && functional_vdf_ticket.cycle==7);
  supplied_cycle=8;actual_receive(0x81cf61c4,&message);assert(receive_calls==2 && functional_vdf_ticket.cycle==7);
  release_result=-EIO;assert(actual_free(0x81cf61c4,message)==-EIO && last_free_cycle==7 && functional_vdf_ticket.pointer==message);
  release_result=0;assert(!actual_free(0x81cf61c4,message) && last_free_cycle==7 && !functional_vdf_ticket.pointer && !free_calls);
 }else if(!strcmp(argv[1],"ticket-global")){
  expected_destination=0x80946189;
  assert(!actual_receive(expected_destination,&message) && receive_calls==1);
  assert(functional_vdf_ticket.destination==expected_destination && functional_vdf_ticket.pointer==message);
  assert(!actual_free(expected_destination,message) && last_free_cycle==7 && !functional_vdf_ticket.pointer);
 }else if(!strncmp(argv[1],"refresh-origin-",15)){
  request_source=0x80946189;errno=EDOM;int expected=0;
  if(!strcmp(argv[1],"refresh-origin-caller")){fixture_caller=(void *)(appfw_base+0x34e4f38UL);expected=-ELIBBAD;}
  else if(!strcmp(argv[1],"refresh-origin-base")){appfw_base=0;expected=-ENODATA;}
  else if(!strcmp(argv[1],"refresh-origin-open")){refresh_open_failure=1;expected=-ENODATA;}
  else if(!strcmp(argv[1],"refresh-origin-short-first")){refresh_bad_read=0;refresh_read_result=3;expected=-ENODATA;}
  else if(!strcmp(argv[1],"refresh-origin-short-second")){refresh_bad_read=1;refresh_read_result=3;expected=-ENODATA;}
  else if(!strcmp(argv[1],"refresh-origin-read-error")){refresh_bad_read=0;refresh_read_result=-1;expected=-ENODATA;}
  else if(!strcmp(argv[1],"refresh-origin-changing")){refresh_globals[1]^=1;expected=-ESTALE;}
  else if(!strcmp(argv[1],"refresh-origin-source")){request_source^=1;expected=-ESTALE;}
  else if(!strcmp(argv[1],"refresh-origin-zero")){request_source=refresh_globals[0]=refresh_globals[1]=0;expected=-ESTALE;}
  else if(!strcmp(argv[1],"refresh-origin-sentinel")){request_source=refresh_globals[0]=refresh_globals[1]=0xffffffffu;expected=-ESTALE;}
  else if(!strcmp(argv[1],"refresh-origin-service")){request_source=refresh_globals[0]=refresh_globals[1]=FUNCTIONAL_VDF_PATH_SID;expected=-ESTALE;}
  else if(!strcmp(argv[1],"refresh-origin-bind-failure")){refresh_bind_result=-ESTALE;expected=-ESTALE;}
  else assert(!strcmp(argv[1],"refresh-origin-good"));
  assert(functional_camera_global_queue_bind(request_wire,fixture_caller,0x141)==expected && errno==EDOM && refresh_logs==1);
  assert(strstr(refresh_log,expected?"readback_verified=0":"readback_verified=1"));
  if(!expected || refresh_bind_result){
   assert(refresh_open_calls==1 && refresh_read_calls==2 && refresh_close_calls==1 && refresh_bind_calls==1);
   assert(refresh_bound_source==0x80946189 && strstr(refresh_log,"source=0x80946189"));
  }else{
   assert(!refresh_bind_calls);
   if(expected==-ELIBBAD || !appfw_base)assert(!refresh_open_calls && !refresh_read_calls && !refresh_close_calls);
   else if(refresh_open_failure)assert(refresh_open_calls==1 && !refresh_read_calls && !refresh_close_calls);
   else assert(refresh_open_calls==1 && refresh_read_calls==2 && refresh_close_calls==1);
  }
  assert(!owner_calls && !bridge_calls && !dispatch_calls && !free_calls);
 }else if(!strcmp(argv[1],"missing-ticket")){
  release_result=-ESTALE;assert(actual_free(0x81cf61c4,message)==-ESTALE && !last_free_cycle && !functional_vdf_ticket.pointer);
 }else if(!strcmp(argv[1],"wrong-destination")){
  actual_receive(0x81cf61c4,&message);release_result=-ESTALE;
  assert(actual_free(0x81cf61c5,message)==-ESTALE && !last_free_cycle && functional_vdf_ticket.cycle==7);
 }else if(!strncmp(argv[1],"stage-early-",12)){
  layout_request();graph_ready=0;functional_vdf_path_used=0;
  if(!strcmp(argv[1],"stage-early-layout")){
   for(unsigned int i=0;i<3;i++){
    assert(!actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire));
    assert(stage_owner_calls==1 && stage_dispatch_calls==(int)i+1 && bb_calls==(int)i+1);
   }
   assert(!strcmp(call_order,"BOSBSBS") && functional_layout_stage_binding==2 && functional_layout_stage_used==1);
  }else if(!strcmp(argv[1],"stage-early-no-bb")){
   full_bb_set_mode_enabled=0;assert(!actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire));
   assert(!bb_calls && stage_owner_calls==1 && stage_dispatch_calls==1 && !strcmp(call_order,"OS"));
  }else if(!strcmp(argv[1],"stage-early-reject")){
   request_wire[4]=24;assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENOTSUP);
   layout_request();request_bytes=39;assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENOTSUP);
   const unsigned int commands[]={0x38,0x53,0x52,0x62,0x41,0x5e},sizes[]={24,14,16,10,8,10};
   for(size_t i=0;i<sizeof commands/sizeof *commands;i++){
    layout_request();request_wire[2]=(unsigned char)commands[i];request_wire[4]=(unsigned char)sizes[i];request_bytes=sizes[i];
    assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENODATA);
   }
   layout_request();functional_camera_enabled=0;assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-999);
   assert(!stage_owner_calls && !stage_dispatch_calls && !bb_calls && !functional_layout_stage_used);
   functional_camera_enabled=1;memset(request_wire+8,0,32);
   assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-EINVAL);
   assert(stage_owner_calls==1 && stage_dispatch_calls==1 && bb_calls==1 && !strcmp(call_order,"BOS"));
  }else if(!strcmp(argv[1],"stage-early-bb-failure")){
   bb_result=-EIO;assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-EIO);
   assert(bb_calls==1 && !stage_owner_calls && !stage_dispatch_calls && !functional_layout_stage_used && !strcmp(call_order,"B"));
  }else if(!strcmp(argv[1],"stage-early-owner-failure")){
   stage_owner_result=-ENOMEM;
   assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENOMEM);
   assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENOMEM);
   assert(stage_owner_calls==1 && bb_calls==2 && !stage_dispatch_calls && functional_layout_stage_binding==3);
   assert(functional_layout_stage_error==-ENOMEM && !functional_layout_stage_used && !strcmp(call_order,"BOB"));
  }else if(!strcmp(argv[1],"stage-early-dispatch-errors")){
   stage_dispatch_handled=0;assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENOTSUP);
   stage_dispatch_handled=1;stage_dispatch_result=-ENODATA;
   assert(actual_send(FUNCTIONAL_LAYOUT_STAGE_SID,request_wire)==-ENODATA);
   assert(stage_owner_calls==1 && bb_calls==2 && stage_dispatch_calls==2 && !strcmp(call_order,"BOSBS"));
  }else return 2;
  assert(!graph_ready && !owner_calls && !bridge_calls && !dispatch_calls && !functional_vdf_binding && !functional_vdf_path_used);
  assert(!stage_snapshot_calls && !path_snapshot_calls && !read_bank_calls && !bind_calls && !free_calls);
 }else if(!strcmp(argv[1],"stage-ticket")){
  functional_layout_stage_used=1;functional_vdf_path_used=0;
  assert(!actual_receive(0x81cf61c4,&message) && stage_receive_calls==1 && errno==ERANGE);
  assert(functional_layout_stage_ticket.pointer==message && functional_layout_stage_ticket.destination==0x81cf61c4 && functional_layout_stage_ticket.cycle==23);
  supplied_stage_cycle=24;assert(!actual_receive(0x81cf61c4,&message) && stage_receive_calls==2);
  assert(functional_layout_stage_ticket.cycle==23 && stage_retained_logs==1);
  stage_release_result=-ESTALE;
  assert(actual_free(0x81cf61c5,message)==-ESTALE && !last_stage_free_cycle);
  assert(actual_free(0x81cf61c4,storage+1)==-ESTALE && !last_stage_free_cycle);
  stage_release_result=-EIO;assert(actual_free(0x81cf61c4,message)==-EIO && last_stage_free_cycle==23);
  assert(functional_layout_stage_ticket.pointer==message && functional_layout_stage_ticket.destination==0x81cf61c4 && functional_layout_stage_ticket.cycle==23);
  stage_release_result=0;assert(!actual_free(0x81cf61c4,message) && last_stage_free_cycle==23 && stage_release_calls==4);
  assert(!functional_layout_stage_ticket.pointer && !functional_layout_stage_ticket.destination && !functional_layout_stage_ticket.cycle);
  assert(!stage_snapshot_calls && !path_snapshot_calls && !free_calls && !receive_calls);
 }else if(!strcmp(argv[1],"stage-receive-gates")){
  functional_vdf_path_used=0;assert(!actual_receive(0x81cf61c4,&message) && !stage_receive_calls);
  assert(!functional_layout_stage_ticket.pointer && !functional_layout_stage_ticket.destination && !functional_layout_stage_ticket.cycle);
  functional_layout_stage_used=1;native_receive_result=-EAGAIN;
  assert(actual_receive(0x81cf61c4,&message)==-EAGAIN && !stage_receive_calls);
  native_receive_result=0;functional_camera_enabled=0;assert(!actual_receive(0x81cf61c4,&message) && !stage_receive_calls);
  functional_camera_enabled=1;assert(!actual_receive(0x81cf61c4,0) && !stage_receive_calls);
  void *empty=0;assert(!actual_receive(0x81cf61c4,&empty) && !stage_receive_calls);
  stage_receive_result=0;assert(!actual_receive(0x81cf61c4,&message) && stage_receive_calls==1 && !functional_layout_stage_ticket.pointer);
  stage_receive_result=-ESTALE;assert(!actual_receive(0x81cf61c4,&message) && stage_receive_calls==2 && !functional_layout_stage_ticket.pointer);
  stage_release_result=-ESTALE;assert(actual_free(0x81cf61c4,message)==-ESTALE && !last_stage_free_cycle);
  assert(!functional_layout_stage_ticket.destination && !functional_layout_stage_ticket.cycle);
  stage_receive_result=1;assert(!actual_receive(0x81cf61c4,&message) && stage_receive_calls==3);
  assert(functional_layout_stage_ticket.pointer==message && functional_layout_stage_ticket.cycle==23 && native_receive_calls==8);
  assert(!stage_snapshot_calls && !path_snapshot_calls && !free_calls && errno==ERANGE);
 }else if(!strncmp(argv[1],"stage-bind",10)){
  bind_input();
  if(!strcmp(argv[1],"stage-bind")){
   request_wire=malloc(sizeof canonical_request);assert(request_wire);layout_request();release_request_in_dispatch=1;
   assert(!actual_send(FUNCTIONAL_VDF_PATH_SID,request_wire) && !request_wire);
   assert(owner_calls==1 && bridge_calls==1 && dispatch_calls==1 && functional_vdf_binding==2);
   assert(stage_snapshot_calls==1 && path_snapshot_calls==1 && read_bank_calls==1 && bind_calls==1 && !strcmp(call_order,"DLPRA"));
   assert(!functional_layout_stage_error && !bind_failed_logs);
  }else if(!strcmp(argv[1],"stage-bind-skip")){
   functional_layout_stage_used=0;assert(!functional_layout_stage_bind_model() && !stage_snapshot_calls);
   functional_layout_stage_used=1;uint64_t generation=staged_state.stage_generation;staged_state.stage_generation=0;
   assert(!functional_layout_stage_bind_model() && stage_snapshot_calls==1 && !path_snapshot_calls);
   staged_state.stage_generation=generation;staged_state.applied.verified=1;
   assert(!functional_layout_stage_bind_model() && stage_snapshot_calls==2 && !path_snapshot_calls && !read_bank_calls && !bind_calls);
   assert(!strcmp(call_order,"LL"));
  }else if(!strcmp(argv[1],"stage-bind-invalid-path")){
   path_state.origin.command=0x0153;expect_bind_failure(-EPROTO);
   path_state.origin.command=0x014c;path_state.model_complete=0;expect_bind_failure(-EPROTO);
   path_state.model_complete=1;path_state.faults=1;expect_bind_failure(-EPROTO);
   path_state.faults=0;path_state.model_result_bytes=191;expect_bind_failure(-EPROTO);
   assert(stage_snapshot_calls==4 && path_snapshot_calls==4 && !read_bank_calls && !bind_calls && bind_failed_logs==4);
   assert(!strcmp(call_order,"DLPDLPDLPDLP"));
  }else if(!strcmp(argv[1],"stage-bind-readback-errors")){
   read_bank_data[31]^=1;expect_bind_failure(-ESTALE);
   read_bank_data[31]^=1;read_bank_digest^=1;expect_bind_failure(-ESTALE);
   read_bank_digest^=1;read_bank_result=-EIO;expect_bind_failure(-EIO);
   assert(stage_snapshot_calls==3 && path_snapshot_calls==3 && read_bank_calls==3 && !bind_calls && bind_failed_logs==3);
   assert(!strcmp(call_order,"DLPRDLPRDLPR"));
  }else if(!strcmp(argv[1],"stage-bind-apply-error")){
   bind_result=-EACCES;expect_bind_failure(-EACCES);
   assert(bind_failed_logs==1 && bind_calls==1 && !strcmp(call_order,"DLPRA"));
  }else if(!strcmp(argv[1],"stage-bind-send-error")){
   path_dispatch_result=-EIO;assert(actual_send(FUNCTIONAL_VDF_PATH_SID,request_wire)==-EIO);
   path_dispatch_result=0;request_bytes=14;request_wire[2]=0x53;request_wire[4]=14;
   assert(!actual_send(FUNCTIONAL_VDF_PATH_SID,request_wire));
   assert(dispatch_calls==2 && !stage_snapshot_calls && !path_snapshot_calls && !read_bank_calls && !bind_calls && !strcmp(call_order,"DD"));
  }else return 2;
  assert(!bb_calls && !stage_owner_calls && !stage_dispatch_calls && !staged_state.applied.frame_consumed && !staged_state.capture_verified);
 }else if(!strncmp(argv[1],"zoom-",5)){
  cp_owned_parameters.batch.owner_pid=getpid();
  if(!strcmp(argv[1],"zoom-uninitialized")){
   cp_owned_parameters.batch.owner_pid=0;assert(functional_cp_zoom_prepare()==-ENODATA && !zoom_locks && !zoom_bind_calls);
  }else if(!strcmp(argv[1],"zoom-foreign-pid")){
   cp_owned_parameters.batch.owner_pid++;assert(functional_cp_zoom_prepare()==-EXDEV && !zoom_locks && !zoom_bind_calls);
  }else if(!strcmp(argv[1],"zoom-order")){
   assert(!functional_cp_zoom_reserve_resources() && zoom_dmm_held && zoom_parameter_held);
   functional_cp_zoom_release_resources();assert(!zoom_dmm_held && !zoom_parameter_held);
  }else if(!strcmp(argv[1],"zoom-lock-failure")){
   zoom_lock_failure=1;assert(functional_cp_zoom_reserve_resources()==-EIO && !zoom_dmm_held && !zoom_parameter_held);
  }else{
   if(!strcmp(argv[1],"zoom-owner-failure"))zoom_owner_result=-EIO;
   int rc=functional_cp_zoom_prepare();assert(rc==zoom_owner_result && zoom_bind_calls==1 && zoom_locks==1 && !zoom_parameter_held);
   assert(functional_cp_zoom_prepare()==rc && zoom_bind_calls==1 && zoom_locks==1);
  }
 }else if(!strncmp(argv[1],"send-",5)){
  unsigned int id=FUNCTIONAL_VDF_PATH_SID;
  request_wire[0]=0x0d;request_wire[1]=0x20;request_wire[2]=0x38;request_wire[3]=1;
  request_wire[4]=24;request_wire[6]=1;request_wire[7]=0x80;
  if(!strcmp(argv[1],"send-zebra")){request_bytes=14;request_wire[2]=0x53;request_wire[4]=14;}
  if(!strncmp(argv[1],"send-layout",11))layout_request();
  if(!strcmp(argv[1],"send-layout-short"))request_bytes=39;
  if(!strcmp(argv[1],"send-layout-bad-header"))request_wire[4]=24;
  if(!strncmp(argv[1],"send-peaking",12)){request_bytes=16;request_wire[2]=0x52;request_wire[4]=16;}
  if(!strncmp(argv[1],"send-flag",9)){request_bytes=10;request_wire[2]=0x62;request_wire[4]=10;}
  if(!strcmp(argv[1],"send-peaking-short"))request_bytes=15;
  if(!strcmp(argv[1],"send-flag-short"))request_bytes=9;
  if(!strncmp(argv[1],"send-refresh",12)){request_bytes=8;request_wire[2]=0x41;request_wire[4]=8;request_source=0x80946189;}
  if(!strcmp(argv[1],"send-refresh-short"))request_bytes=7;
  if(!strncmp(argv[1],"send-bb-",8)){
   const unsigned int commands[]={0x11,0x66,0x67,0x5f,0x28},sizes[]={36,36,10,12,20};
   unsigned int index=strstr(argv[1],"look")?1u:strstr(argv[1],"gamut")?2u:strstr(argv[1],"gain")?3u:strstr(argv[1],"interval")?4u:0u;
   request_wire[2]=(unsigned char)commands[index];request_bytes=sizes[index];request_wire[4]=(unsigned char)request_bytes;
   if(strstr(argv[1],"-short"))request_bytes--;
  }
  if(!strncmp(argv[1],"send-bit-width",14)){
   request_bytes=10;request_wire[2]=0x5e;request_wire[4]=10;
   if(strstr(argv[1],"-short"))request_bytes=9;
   if(strstr(argv[1],"-long"))request_bytes=11;
   if(strstr(argv[1],"-bad-header"))request_wire[4]=12;
   if(strstr(argv[1],"-not-ready"))graph_ready=0;
   if(strstr(argv[1],"-disabled"))functional_camera_enabled=0;
  }
  if(!strcmp(argv[1],"send-short"))request_bytes=4;
  if(!strcmp(argv[1],"send-bad-header"))request_wire[4]=14;
  if(!strcmp(argv[1],"send-unrelated"))request_wire[2]=0x54;
  if(!strcmp(argv[1],"send-not-ready"))graph_ready=0;
  if(!strcmp(argv[1],"send-disabled"))functional_camera_enabled=0;
  int rc=actual_send(id,request_wire);
  if(!strcmp(argv[1],"send-bit-width") || !strcmp(argv[1],"send-path") || !strcmp(argv[1],"send-zebra") || !strcmp(argv[1],"send-layout") || !strcmp(argv[1],"send-peaking") || !strcmp(argv[1],"send-flag") || !strcmp(argv[1],"send-refresh") || (!strncmp(argv[1],"send-bb-",8) && !strstr(argv[1],"-short")))
   assert(!rc && owner_calls==1 && bridge_calls==1 && dispatch_calls==1);
  else{
   int expected=(strstr(argv[1],"-short") || strstr(argv[1],"-long") || strstr(argv[1],"-bad-header"))?-ENOTSUP:
       strstr(argv[1],"-not-ready")?-ENODATA:-999;
   assert(rc==expected && !owner_calls && !bridge_calls && !dispatch_calls);
  }
 }else return 2;
 assert(!functional_startup_control_used);
 puts("PASS actual VDF setup/ticket hooks");return 0;
}
'''
    work = tmp_path_factory.mktemp('actual-vdf-wiring')
    path, binary = work / 'actual.c', work / 'actual'
    path.write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', ['success', 'owner-failure', 'bridge-failure', 'busy',
                                 'ticket', 'ticket-global', 'missing-ticket', 'wrong-destination',
                                 'refresh-origin-good', 'refresh-origin-caller', 'refresh-origin-base',
                                 'refresh-origin-open', 'refresh-origin-short-first', 'refresh-origin-short-second',
                                 'refresh-origin-read-error', 'refresh-origin-changing', 'refresh-origin-source',
                                 'refresh-origin-zero', 'refresh-origin-sentinel', 'refresh-origin-service',
                                 'refresh-origin-bind-failure',
                                 'send-bit-width', 'send-bit-width-short', 'send-bit-width-long',
                                 'send-bit-width-bad-header', 'send-bit-width-not-ready', 'send-bit-width-disabled',
                                 'send-path', 'send-zebra', 'send-layout', 'send-layout-short',
                                 'send-layout-bad-header', 'send-peaking', 'send-peaking-short',
                                 'send-flag', 'send-flag-short', 'send-refresh', 'send-refresh-short',
                                 'send-bb-sq', 'send-bb-sq-short', 'send-bb-look', 'send-bb-look-short',
                                 'send-bb-gamut', 'send-bb-gamut-short', 'send-bb-gain', 'send-bb-gain-short',
                                 'send-bb-interval', 'send-bb-interval-short',
                                 'send-short', 'send-bad-header',
                                 'send-unrelated', 'send-not-ready', 'send-disabled',
                                 'zoom-success', 'zoom-owner-failure', 'zoom-uninitialized',
                                 'zoom-foreign-pid', 'zoom-order', 'zoom-lock-failure',
                                 'stage-early-layout', 'stage-early-no-bb', 'stage-early-reject',
                                 'stage-early-bb-failure', 'stage-early-owner-failure', 'stage-early-dispatch-errors',
                                 'stage-ticket', 'stage-receive-gates', 'stage-bind', 'stage-bind-skip',
                                 'stage-bind-invalid-path', 'stage-bind-readback-errors',
                                 'stage-bind-apply-error', 'stage-bind-send-error'])
def test_actual_vdf_setup_and_immutable_ticket_hooks(vdf_wiring_binary, case):
    done = subprocess.run([str(vdf_wiring_binary), case], capture_output=True, text=True, timeout=5)
    assert done.returncode == 0, f'{case}: rc={done.returncode}\n{done.stdout}\n{done.stderr}'
    assert done.stdout.endswith('PASS actual VDF setup/ticket hooks\n')
