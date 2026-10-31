"""HOSTTEST actual main C background hooks; API stubs do not prove native/Core behavior."""
from pathlib import Path
import importlib.util
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('background_graph_fixture', HERE / 'test_final_graph_observer_wiring.py')
assert _spec is not None and _spec.loader is not None
_graph_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_graph_fixture)
function = _graph_fixture.function


@pytest.fixture(scope='module', params=['strict', 'asan-ubsan'])
def background_wiring_binary(tmp_path_factory, request):
    source = (HERE / 'menu-observe.c').read_text()
    snippets = '\n'.join(function(source, name) for name in (
        'functional_background_start_prepare', 'functional_background_start_bind_original_source',
        'functional_background_start_reserve_resources', 'native_background_start_progress',
        'native_background_start_received', 'native_background_start_release',
        'native_cp_state_received', 'u_osal_rcv_msg_tmo'))
    ticket = next(line for line in source.splitlines()
                  if line.startswith('static _Thread_local struct') and 'functional_background_start_ticket' in line)
    sent = function(source, 'osal_snd_msg')
    sent = sent[sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_CAMERA_CONTROL_SID)'):
                sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_MPR_CODEC_DESTINATION')]
    sent = sent.replace('__builtin_return_address(0)', 'fixture_caller')
    freed = function(source, 'osal_free_msg')
    audio = freed[freed.index('    if (__atomic_load_n(&adf_hdmi_audio_connection_used'):
                  freed.index('    if (__atomic_load_n(&vef_pinmem_input_connection_used')]
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "device-models/functional-background-start.h"
#include "device-models/functional-camera-control.h"
#include "device-models/functional-cp-zoom.h"
#define CALLER_OFFSET 0xeda50u
static unsigned int functional_background_start_binding,functional_background_start_used;
static int functional_background_start_owner_pid,functional_camera_setup_error,functional_camera_enabled=1;
static int owner_calls,owner_result,bridge_calls,bridge_result,reserve_calls,reserve_result,guard_held,unlock_calls;
static int progress_calls,progress_result,bind_calls,bind_result,bound_logs,retained_logs,dispatch_calls;
static int dispatch_result,dispatch_handled=1,control_calls,control_result=-777,graph_ready;
static unsigned int bound_source;
static char order[64],binding_log[512];static size_t order_size;
static unsigned char *object,*request_wire;static void *fixture_caller;
static const char *library_name="/system/lib/libObj.so";
static int dl_result=1,null_base,null_name,wrong_base,dl_calls,open_failure,open_calls,read_calls,close_calls;
static int read_mode; /* 1/2=short read, 3=actual mutation between reads, 4=read error. */
static unsigned int request_source=0x81020017u,request_bytes=24;
static int cp_owned_state_enabled,receive_result,receive_calls,free_calls,free_result;
static int observe_calls,observe_result=1,release_calls,release_handled=1,release_result,snapshot_calls;
static _Thread_local uint64_t supplied_cycle=UINT64_C(0x123456789),last_release_cycle,expected_release_cycle;
static _Thread_local unsigned int native_receive_depth;
static _Thread_local void *received_pointer;
static _Thread_local unsigned int received_destination;
static _Thread_local uintptr_t last_free_pointer;
static unsigned int functional_mpr_codec_used,functional_vdf_path_used,functional_layout_stage_used;
static _Thread_local struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_vdf_ticket;
static _Thread_local struct {void *pointer;unsigned int destination;uint64_t cycle;} functional_layout_stage_ticket;
static unsigned int functional_camera_control_used,functional_cp_zoom_used;
static uint64_t functional_cp_zoom_sequence;
static unsigned int adf_hdmi_audio_connection_used=1;
static int audio_calls,audio_handled=1;
static int functional_background_start_reserve_resources(void);
static void record(const char *tag,const char *text);
static void step(char c){assert(order_size+1<sizeof order);order[order_size++]=c;}
static long fixture_syscall(long number){assert(number==178);return syscall(SYS_gettid);}
#define syscall fixture_syscall
/* Only transport faults are injected: successful and racing reads use real /proc/self/mem. */
static int memory_open(const char *path,int flags){
 assert(!strcmp(path,"/proc/self/mem") && !flags);open_calls++;
 if(open_failure){errno=EACCES;return -1;}int fd=open(path,flags);assert(fd>=0);errno=EDOM;return fd;
}
static ssize_t memory_read(int fd,void *out,size_t bytes,off_t offset){
 assert(bytes==4 && (uintptr_t)offset==(uintptr_t)fixture_caller-4);read_calls++;
 ssize_t rc=pread(fd,out,bytes,offset);assert(rc==4);
 if(read_mode==3 && read_calls==1)object[CALLER_OFFSET-4]^=1;
 errno=EIO;if(read_mode==4)return -1;
 if(read_mode==read_calls && (read_mode==1 || read_mode==2))return 3;
 return rc;
}
static int memory_close(int fd){close_calls++;int rc=close(fd);assert(!rc);errno=EBADF;return rc;}
#define open memory_open
#define pread memory_read
#define close memory_close
static int dladdr_api(const void *caller,Dl_info *info){
 assert(caller==fixture_caller && info);dl_calls++;errno=EDOM;
 info->dli_fbase=null_base?NULL:object+wrong_base;
 info->dli_fname=null_name?NULL:library_name;return dl_result;
}
static int (*real_dladdr)(const void *,Dl_info *)=dladdr_api;
static void record(const char *tag,const char *text){
 assert(tag && text);
 if(!strcmp(tag,"FUNCTIONAL_BACKGROUND_START_SOURCE_BOUND ")){
  assert(strstr(text,"caller_va=0xeda50") && strstr(text,"capture_verified=0"));
  assert(strlen(text)<sizeof binding_log);strcpy(binding_log,text);bound_logs++;
 }else if(!strcmp(tag,"FUNCTIONAL_BACKGROUND_START_TICKET_RETAINED ")){
  assert(strstr(text,"no_refresh=1"));retained_logs++;
 }else assert(0);
 errno=ERANGE;
}
int functional_background_start_owner_init(void){owner_calls++;step('O');errno=EDOM;return owner_result;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){
 assert(logger==record && guard_held);bridge_calls++;step('B');return bridge_result;
}
static int tracked_native_reserve_resources(int requester){
 assert(requester==29 && !guard_held);reserve_calls++;step('R');if(reserve_result)return reserve_result;guard_held=1;return 0;
}
static void full_vef_resources_unlock(void){assert(guard_held);guard_held=0;unlock_calls++;step('U');}
int functional_background_start_bind_source_once(unsigned int source){
 assert((source>>16)==0x8102u);bind_calls++;bound_source=source;step('Q');errno=E2BIG;return bind_result;
}
int functional_background_start_progress(void){
 assert(functional_background_start_used && functional_background_start_owner_pid==getpid());
 __atomic_add_fetch(&progress_calls,1,__ATOMIC_RELAXED);step('P');errno=EDOM;return progress_result;
}
void functional_background_start_snapshot(struct functional_background_start_snapshot *out){
 (void)out;snapshot_calls++;assert(!"parent hook must never refresh a receive ticket from a snapshot");
}
static unsigned int source_api(void *p){assert(p);errno=EDOM;return p==request_wire?request_source:FUNCTIONAL_BACKGROUND_START_SID;}
static unsigned int size_api(void *p){assert(p);errno=EDOM;return p==request_wire?request_bytes:12;}
static unsigned int (*real_get_source)(void *)=source_api,(*real_msg_size)(void *)=size_api;
static int real_free_msg(unsigned int id,void *p){
 assert(id && p);__atomic_add_fetch(&free_calls,1,__ATOMIC_RELAXED);last_free_pointer=(uintptr_t)p;
 if(!free_result)free(p);
 errno=EINTR;return free_result;
}
static int real_allocate_msg(unsigned int id,void **p,unsigned int bytes,unsigned int count){
 (void)id;(void)p;(void)bytes;(void)count;assert(!"main wiring must not allocate backend messages");return -ENOMEM;
}
static void real_set_source(void *p,unsigned int source){(void)p;(void)source;assert(0);}
static int real_send_msg(unsigned int id,void *p){(void)id;(void)p;assert(0);return -ENOTSUP;}
static int cp302c_no_transition_predecessors_ready(void){return graph_ready;}
static int cp_owned_state_predecessors_ready(void){return 0;}
static int functional_camera_control_reserve_resources(void){assert(0);return -ENOTSUP;}
static int functional_cp_zoom_prepare(void){assert(0);return -ENOTSUP;}
static int functional_cp_zoom_reserve_resources(void){assert(0);return -ENOTSUP;}
static void functional_cp_zoom_release_resources(void){assert(0);}
int functional_cp_zoom_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,const struct cp_start_state_guard *data,int enabled,int *result){
 (void)id;(void)p;(void)io;(void)guard;(void)data;(void)enabled;(void)result;assert(0);return 0;
}
int functional_background_start_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 assert(id==FUNCTIONAL_BACKGROUND_START_SID && p==request_wire && enabled==1 && result);
 assert(io && io->allocate==real_allocate_msg && io->release==real_free_msg && io->send==real_send_msg);
 assert(io->set_source==real_set_source && io->source==real_get_source && io->size==real_msg_size && io->record==record);
 assert(guard && guard->reserve==functional_background_start_reserve_resources && guard->release==full_vef_resources_unlock);
 assert(guard->predecessor_ready==cp302c_no_transition_predecessors_ready);
 assert(functional_background_start_used==1 && functional_background_start_binding==2);
 assert(owner_calls==1 && bind_calls==1 && bound_source==request_source && !bridge_calls && !reserve_calls && !control_calls);
 dispatch_calls++;step('D');*result=dispatch_result;return dispatch_handled;
}
int native_functional_camera_control_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 assert(id==FUNCTIONAL_CAMERA_CONTROL_SID && p==request_wire && io && guard && enabled==1 && result);
 assert(!dispatch_calls && !functional_background_start_used);control_calls++;*result=control_result;return 1;
}
int functional_background_start_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *cycle){
 assert(id==received_destination && p==received_pointer && source==FUNCTIONAL_BACKGROUND_START_SID && bytes==12 && cycle);
 __atomic_add_fetch(&observe_calls,1,__ATOMIC_RELAXED);*cycle=supplied_cycle;errno=EDOM;return observe_result;
}
int functional_background_start_release_cycle(unsigned int id,void *p,uint64_t cycle,
 int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result){
 assert(p && release==real_free_msg && logger==record && result && !snapshot_calls);
 assert(cycle==expected_release_cycle);last_release_cycle=cycle;__atomic_add_fetch(&release_calls,1,__ATOMIC_RELAXED);
 errno=E2BIG;if(!release_handled)return 0;
 *result=release_result?release_result:!cycle?-ESTALE:release(id,p);return 1;
}
/* Unrelated receive observers are deliberately inert; the actual parent receive gate is executed. */
static unsigned int functional_still_format_used,functional_startup_control_used;
static void native_startup_control_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;assert(!"startup-control is disabled in this background fixture");
}
static void native_still_format_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){
 (void)id;(void)p;(void)source;(void)bytes;assert(0);
}
static void native_functional_face_received(unsigned int id,void *p){(void)id;(void)p;}
static void native_histogram_received(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;}
int functional_vdf_layout_stage_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){
 (void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;
}
int functional_vdf_path_observe_receive_cycle(unsigned int id,void *p,unsigned int source,unsigned int bytes,uint64_t *ticket){
 (void)id;(void)p;(void)source;(void)bytes;(void)ticket;assert(0);return 0;
}
static int functional_camera_events_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
static int functional_jpeg_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;(void)io;return 0;}
static int functional_mpr_codec_observe_received(unsigned int id,void *p,const struct full_imaging_io *io){(void)id;(void)p;(void)io;assert(0);return 0;}
int native_cp_state_publication_observe_receive(unsigned int id,void *p,unsigned int source,unsigned int bytes){(void)id;(void)p;(void)source;(void)bytes;return 0;}
static void native_hdmi_video_received(unsigned int id,void **p,int result){(void)id;(void)p;(void)result;}
static int receive_api(unsigned int id,void **p,long timeout){
 assert(id==received_destination && timeout==27 && native_receive_depth);receive_calls++;if(p)*p=received_pointer;errno=ERANGE;return receive_result;
}
static int (*real_u_rcv_msg_tmo)(unsigned int,void **,long)=receive_api;
static int full_adf_hdmi_audio_connection_release(unsigned int id,void *p,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result){
 assert(id && p && release==real_free_msg && logger==record && result && !progress_calls);
 audio_calls++;if(!audio_handled)return 0;step('A');*result=release(id,p);step('F');return 1;
}
''' + ticket + '\n' + snippets + r'''
static int actual_send(unsigned int id,void *message){
''' + sent + r'''
 return -999;
}
static int actual_last13_free(unsigned int id,void *message){
 int vdf_result;
''' + audio + r'''
 return -999;
}
static void setup_origin(void){
 object=calloc(1,CALLER_OFFSET+8);assert(object);fixture_caller=object+CALLER_OFFSET;
 const uint32_t original=UINT32_C(0x97fdb339);memcpy(object+CALLER_OFFSET-4,&original,4);
 request_wire=calloc(1,24);assert(request_wire);request_wire[2]=6;request_wire[3]=0x30;
}
static void active(void){functional_background_start_owner_pid=getpid();functional_background_start_used=1;}
static void setup_receive(void){
 active();received_pointer=malloc(12);assert(received_pointer);memset(received_pointer,0xa5,12);received_destination=0x81027ab3u;
}
static void assert_ticket(void *p,unsigned int id,uint64_t cycle){
 assert(functional_background_start_ticket.pointer==p && functional_background_start_ticket.destination==id && functional_background_start_ticket.cycle==cycle);
}
static void original_receive(void){
 void *p=NULL;errno=EINTR;assert(!u_osal_rcv_msg_tmo(received_destination,&p,27) && p==received_pointer && errno==ERANGE);
 assert_ticket(p,received_destination,supplied_cycle);
}
struct thread_input {pthread_barrier_t *barrier;uint64_t cycle;unsigned int destination;};
static void rendezvous(pthread_barrier_t *barrier){int rc=pthread_barrier_wait(barrier);assert(!rc || rc==PTHREAD_BARRIER_SERIAL_THREAD);}
static void *thread_receive_release(void *arg){
 struct thread_input *in=arg;assert_ticket(NULL,0,0);
 received_pointer=malloc(12);assert(received_pointer);received_destination=in->destination;supplied_cycle=in->cycle;
 errno=EAGAIN;native_background_start_received(received_destination,received_pointer,FUNCTIONAL_BACKGROUND_START_SID,12);
 assert(errno==EAGAIN);assert_ticket(received_pointer,in->destination,in->cycle);rendezvous(in->barrier);rendezvous(in->barrier);
 expected_release_cycle=in->cycle;int result=-99;errno=EDOM;
 assert(native_background_start_release(in->destination,received_pointer,&result)==1 && !result && errno==EDOM);
 assert(last_release_cycle==in->cycle && last_free_pointer==(uintptr_t)received_pointer);assert_ticket(NULL,0,0);return NULL;
}
int main(int argc,char **argv){
 assert(argc==2);const char *test=argv[1];setup_origin();
 if(!strncmp(test,"prepare-",8)){
  int expected=0;
  if(!strcmp(test,"prepare-busy")){functional_background_start_binding=1;expected=-EBUSY;}
  else if(!strcmp(test,"prepare-root-error")){functional_camera_setup_error=-EACCES;expected=-EACCES;}
  else if(!strcmp(test,"prepare-owner-error")){owner_result=-ENOMEM;expected=-ENOMEM;}
  else if(!strcmp(test,"prepare-foreign-pid")){functional_background_start_binding=2;functional_background_start_owner_pid=getpid()+1;expected=-EXDEV;}
  assert(functional_background_start_prepare()==expected && !bridge_calls && !reserve_calls && !dispatch_calls);
  assert(functional_background_start_prepare()==expected);
  if(owner_result){assert(owner_calls==1 && functional_background_start_binding==3 && functional_camera_setup_error==-ENOMEM && !functional_background_start_owner_pid);}
  else if(!expected){
   assert(owner_calls==1 && functional_background_start_owner_pid==getpid() && functional_background_start_binding==2 && !strcmp(order,"O"));
   if(!strcmp(test,"prepare-fork")){
    pid_t child=fork();assert(child>=0);
    if(!child)_exit(functional_background_start_prepare()==-EXDEV && owner_calls==1 && !bridge_calls?0:1);
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
   }
  }else assert(!owner_calls);
 }else if(!strncmp(test,"bind-",5)){
  int expected=0;
  if(!strcmp(test,"bind-second-dynamic"))request_source=0x8102f9cdu;
  else if(!strcmp(test,"bind-bare-name"))library_name="libObj.so";
  else if(!strcmp(test,"bind-bad-suffix")){library_name="/lib/xxxlibObj.so";expected=-EPERM;}
  else if(!strcmp(test,"bind-trailing")){library_name="/lib/libObj.so.extra";expected=-EPERM;}
  else if(!strcmp(test,"bind-null-filename")){null_name=1;expected=-EPERM;}
  else if(!strcmp(test,"bind-null-base")){null_base=1;expected=-EPERM;}
  else if(!strcmp(test,"bind-wrong-base")){wrong_base=4;expected=-EPERM;}
  else if(!strcmp(test,"bind-null-dladdr")){real_dladdr=NULL;expected=-EPERM;}
  else if(!strcmp(test,"bind-no-info")){dl_result=0;expected=-EPERM;}
  else if(!strcmp(test,"bind-pc-plus4")){fixture_caller=object+CALLER_OFFSET+4;expected=-EPERM;}
  else if(!strcmp(test,"bind-null-caller")){fixture_caller=NULL;expected=-EPERM;}
  else if(!strcmp(test,"bind-corrupt")){object[CALLER_OFFSET-4]^=1;expected=-ELIBBAD;}
  else if(!strcmp(test,"bind-open-failure")){open_failure=1;expected=-ELIBBAD;}
  else if(!strcmp(test,"bind-short-first")){read_mode=1;expected=-ELIBBAD;}
  else if(!strcmp(test,"bind-short-second")){read_mode=2;expected=-ELIBBAD;}
  else if(!strcmp(test,"bind-read-error")){read_mode=4;expected=-ELIBBAD;}
  else if(!strcmp(test,"bind-real-race")){read_mode=3;expected=-ELIBBAD;}
  else if(!strcmp(test,"bind-wrong-source")){request_source=0x81030017;expected=-EPERM;}
  else if(!strcmp(test,"bind-zero-source")){request_source=0;expected=-EPERM;}
  else if(!strcmp(test,"bind-backend-error")){bind_result=-ESTALE;expected=-ESTALE;}
  else assert(!strcmp(test,"bind-good"));
  errno=EINTR;assert(functional_background_start_bind_original_source(fixture_caller,request_source)==expected && errno==EINTR);
  assert(bound_logs==1 && !owner_calls && !bridge_calls && !dispatch_calls);
  char rc_text[40];snprintf(rc_text,sizeof rc_text,"bind_rc=%d ",expected);assert(strstr(binding_log,rc_text));
  if(!expected || bind_result)assert(bind_calls==1 && bound_source==request_source && open_calls==1 && read_calls==2 && close_calls==1);
  else{
   assert(!bind_calls);
   if(expected==-EPERM)assert(!open_calls && !read_calls && !close_calls);
   else if(open_failure)assert(open_calls==1 && !read_calls && !close_calls);
   else assert(open_calls==1 && read_calls==2 && close_calls==1);
  }
 }else if(!strncmp(test,"reserve-",8)){
  if(!strcmp(test,"reserve-lock-failure"))reserve_result=-EBUSY;
  if(!strcmp(test,"reserve-bridge-failure"))bridge_result=-EIO;
  int expected=reserve_result?reserve_result:bridge_result;
  assert(functional_background_start_reserve_resources()==expected && reserve_calls==1);
  if(reserve_result)assert(!bridge_calls && !guard_held && !unlock_calls && !strcmp(order,"R"));
  else if(bridge_result)assert(bridge_calls==1 && !guard_held && unlock_calls==1 && !strcmp(order,"RBU"));
  else{assert(bridge_calls==1 && guard_held && !unlock_calls && !strcmp(order,"RB"));full_vef_resources_unlock();}
  assert(!owner_calls && !dispatch_calls);
 }else if(!strncmp(test,"send-",5)){
  unsigned int id=FUNCTIONAL_BACKGROUND_START_SID;int expected=0;
  if(!strcmp(test,"send-short")){request_bytes=23;expected=-ENOTSUP;}
  else if(!strcmp(test,"send-long")){request_bytes=25;expected=-ENOTSUP;}
  else if(!strcmp(test,"send-disabled")){functional_camera_enabled=0;expected=-999;}
  else if(!strcmp(test,"send-wrong-id")){id++;expected=-999;}
  else if(!strcmp(test,"send-owner-error")){owner_result=-ENOMEM;expected=-ENOMEM;}
  else if(!strcmp(test,"send-root-error")){functional_camera_setup_error=-EIO;expected=-EIO;}
  else if(!strcmp(test,"send-bind-error")){bind_result=-ESTALE;expected=-ESTALE;}
  else if(!strcmp(test,"send-unhandled")){dispatch_handled=0;expected=-ENOTSUP;}
  else if(!strcmp(test,"send-backend-error")){dispatch_result=-EBUSY;expected=-EBUSY;}
  else if(!strcmp(test,"send-source-wrong")){request_source^=0x10000u;expected=-EPERM;}
  else if(!strcmp(test,"send-second-dynamic"))request_source=0x8102a987u;
  else if(!strcmp(test,"send-old-3003")){request_wire[2]=3;expected=control_result;}
  else if(!strcmp(test,"send-old-3000")){request_wire[2]=0;expected=control_result;}
  else if(!strcmp(test,"send-wrong-type")){request_wire[0]=1;expected=control_result;}
  else assert(!strcmp(test,"send-good-pending"));
  assert(actual_send(id,request_wire)==expected && !bridge_calls && !reserve_calls && !free_calls && !progress_calls);
  if(dispatch_calls){assert(dispatch_calls==1 && !control_calls && !strcmp(order,"OQD") && !graph_ready);}
  else assert(!functional_background_start_used);
  if(control_calls)assert(control_calls==1 && !owner_calls && !bind_calls && functional_camera_control_used);
 }else if(!strncmp(test,"progress-",9)){
  active();if(!strcmp(test,"progress-unused"))functional_background_start_used=0;
  else if(!strcmp(test,"progress-foreign-pid"))functional_background_start_owner_pid++;
  else if(!strcmp(test,"progress-backend-error"))progress_result=-EIO;
  errno=EINTR;native_background_start_progress();assert(errno==EINTR && !bridge_calls && !reserve_calls);
  assert(progress_calls==(functional_background_start_used && functional_background_start_owner_pid==getpid()));
 }else if(!strncmp(test,"audio-free-",11)){
  active();void *p=malloc(12);assert(p);int expected=0;
  if(!strcmp(test,"audio-free-error")){free_result=-EIO;expected=-EIO;}
  else if(!strcmp(test,"audio-free-strict"))functional_background_start_used=0;
  else if(!strcmp(test,"audio-free-foreign-pid"))functional_background_start_owner_pid++;
  else if(!strcmp(test,"audio-free-unhandled")){audio_handled=0;expected=-999;}
  else if(!strcmp(test,"audio-free-unused")){adf_hdmi_audio_connection_used=0;expected=-999;}
  errno=EAGAIN;assert(actual_last13_free(0x81026789u,p)==expected);
  int did_free=audio_calls && audio_handled;
  int should_progress=did_free && !free_result && functional_background_start_used && functional_background_start_owner_pid==getpid();
  assert(free_calls==did_free && progress_calls==should_progress && !bridge_calls && !reserve_calls);
  if(did_free)assert(errno==EINTR && !strcmp(order,should_progress?"AFP":"AF"));
  else assert(errno==EAGAIN && !order_size);
  if(!did_free || free_result)free(p);
 }else if(!strcmp(test,"thread-isolation")){
  active();pthread_barrier_t barrier;assert(!pthread_barrier_init(&barrier,NULL,3));pthread_t threads[2];
  struct thread_input inputs[2]={{&barrier,UINT64_C(0x100000007),0x81020017u},{&barrier,UINT64_C(0x200000009),0x8102fbcdu}};
  for(unsigned int i=0;i<2;i++)assert(!pthread_create(&threads[i],NULL,thread_receive_release,&inputs[i]));
  rendezvous(&barrier);assert_ticket(NULL,0,0);rendezvous(&barrier);
  for(unsigned int i=0;i<2;i++)assert(!pthread_join(threads[i],NULL));
  assert(!pthread_barrier_destroy(&barrier) && observe_calls==2 && release_calls==2 && free_calls==2 && !snapshot_calls);
 }else{
  setup_receive();void *p=received_pointer;int result=-99;
  if(!strcmp(test,"receive-gates")){
   functional_background_start_used=0;native_background_start_received(received_destination,p,FUNCTIONAL_BACKGROUND_START_SID,12);
   functional_background_start_used=1;functional_background_start_owner_pid++;native_background_start_received(received_destination,p,FUNCTIONAL_BACKGROUND_START_SID,12);
   assert(!observe_calls);functional_background_start_owner_pid=getpid();
   functional_camera_enabled=0;void *out=p;native_cp_state_received(received_destination,&out,0);
   functional_camera_enabled=1;native_cp_state_received(received_destination,&out,-EAGAIN);
   native_cp_state_received(received_destination,NULL,0);out=NULL;native_cp_state_received(received_destination,&out,0);
   out=p;real_get_source=NULL;native_cp_state_received(received_destination,&out,0);real_get_source=source_api;
   real_msg_size=NULL;native_cp_state_received(received_destination,&out,0);real_msg_size=size_api;
   native_receive_depth=1;assert(!u_osal_rcv_msg_tmo(received_destination,&out,27));native_receive_depth=0;
   receive_result=-EIO;assert(u_osal_rcv_msg_tmo(received_destination,&out,27)==-EIO);receive_result=0;
   assert(!observe_calls);assert_ticket(NULL,0,0);free(p);
  }else if(!strcmp(test,"receive-zero-cycle") || !strcmp(test,"receive-unhandled") || !strcmp(test,"receive-error")){
   if(!strcmp(test,"receive-zero-cycle"))supplied_cycle=0;
   else observe_result=!strcmp(test,"receive-error")?-ESTALE:0;
   errno=EINTR;native_background_start_received(received_destination,p,FUNCTIONAL_BACKGROUND_START_SID,12);
   assert(errno==EINTR && observe_calls==1);assert_ticket(NULL,0,0);free(p);
  }else if(!strcmp(test,"release-gates")){
   active();functional_background_start_used=0;errno=EINTR;
   assert(!native_background_start_release(received_destination,p,&result) && result==-99 && errno==EINTR);
   functional_background_start_used=1;functional_background_start_owner_pid++;
   assert(!native_background_start_release(received_destination,p,&result) && !release_calls && !observe_calls && errno==EINTR);free(p);
  }else if(!strcmp(test,"release-no-ticket")){
   errno=EINTR;assert(native_background_start_release(received_destination,p,&result)==1 && result==-ESTALE && errno==EINTR);
   assert(!last_release_cycle && !observe_calls && !free_calls && !snapshot_calls);assert_ticket(NULL,0,0);free(p);
  }else{
   original_receive();uint64_t original=supplied_cycle;uintptr_t address=(uintptr_t)p;
   if(!strncmp(test,"immutable-ticket",16)){
    supplied_cycle++;
    if(!strcmp(test,"immutable-ticket-same-pointer")){
     native_background_start_received(received_destination,p,FUNCTIONAL_BACKGROUND_START_SID,12);
    }else{
     void *next=malloc(12);assert(next);received_pointer=next;
     native_background_start_received(received_destination,next,FUNCTIONAL_BACKGROUND_START_SID,12);
     free(next);received_pointer=p;
    }
    assert_ticket(p,received_destination,original);assert(retained_logs==1 && observe_calls==2);
   }
   expected_release_cycle=original;
   if(!strcmp(test,"release-wrong-destination")){
    expected_release_cycle=0;assert(native_background_start_release(received_destination+1,p,&result)==1 && result==-ESTALE);
    assert_ticket(p,received_destination,original);expected_release_cycle=original;
   }else if(!strcmp(test,"release-wrong-pointer")){
    void *wrong=malloc(12);assert(wrong);expected_release_cycle=0;
    assert(native_background_start_release(received_destination,wrong,&result)==1 && result==-ESTALE);
    assert_ticket(p,received_destination,original);free(wrong);expected_release_cycle=original;
   }else if(!strcmp(test,"release-free-error"))free_result=-EIO;
   else if(!strcmp(test,"release-backend-error"))release_result=-EALREADY;
   else if(!strcmp(test,"release-unhandled"))release_handled=0;
   else if(!strcmp(test,"release-unhandled-zero")){release_handled=0;result=0;}
   int expected_result=release_handled?(release_result?release_result:free_result):result;
   errno=EINTR;int handled=native_background_start_release(received_destination,p,&result);
   assert(handled==release_handled && result==expected_result && errno==EINTR && last_release_cycle==original && !snapshot_calls);
   if(!release_handled || release_result || free_result){assert_ticket(p,received_destination,original);free(p);}
   else{
    assert(!result && free_calls==1 && last_free_pointer==address);assert_ticket(NULL,0,0);
    /* A later plain-pointer free cannot manufacture a ticket, even after a new backend cycle. */
    supplied_cycle++;expected_release_cycle=0;result=-99;
    void *fresh=malloc(12);assert(fresh);assert(native_background_start_release(received_destination,fresh,&result)==1 && result==-ESTALE);
    assert(!last_release_cycle && free_calls==1 && observe_calls==(!strncmp(test,"immutable-ticket",16)?2:1));assert_ticket(NULL,0,0);free(fresh);
   }
  }
 }
 assert(!functional_startup_control_used);
 free(request_wire);free(object);puts("PASS HOSTTEST actual background main C wiring; native/Core not verified");return 0;
}
'''
    work = tmp_path_factory.mktemp('actual-background-wiring-' + request.param)
    path, binary = work / 'actual.c', work / 'actual'
    path.write_text(code)
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread', '-DHOST_TEST']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
    built = subprocess.run(['cc', *flags, '-fno-pie', '-no-pie', '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', [
    'prepare-good', 'prepare-fork', 'prepare-busy', 'prepare-root-error', 'prepare-owner-error', 'prepare-foreign-pid',
    'bind-good', 'bind-second-dynamic', 'bind-bare-name', 'bind-bad-suffix', 'bind-trailing', 'bind-null-filename',
    'bind-null-base', 'bind-wrong-base', 'bind-null-dladdr', 'bind-no-info', 'bind-pc-plus4', 'bind-null-caller',
    'bind-corrupt', 'bind-open-failure', 'bind-short-first', 'bind-short-second', 'bind-read-error', 'bind-real-race',
    'bind-wrong-source', 'bind-zero-source', 'bind-backend-error',
    'reserve-good', 'reserve-lock-failure', 'reserve-bridge-failure',
    'send-good-pending', 'send-second-dynamic', 'send-short', 'send-long', 'send-disabled', 'send-wrong-id',
    'send-owner-error', 'send-root-error', 'send-bind-error', 'send-unhandled', 'send-backend-error', 'send-source-wrong',
    'send-old-3003', 'send-old-3000', 'send-wrong-type',
    'progress-good', 'progress-unused', 'progress-foreign-pid', 'progress-backend-error',
    'audio-free-good', 'audio-free-error', 'audio-free-strict', 'audio-free-foreign-pid', 'audio-free-unhandled', 'audio-free-unused',
    'receive-gates', 'receive-zero-cycle', 'receive-unhandled', 'receive-error', 'immutable-ticket', 'immutable-ticket-same-pointer',
    'release-good', 'release-gates', 'release-no-ticket', 'release-wrong-destination', 'release-wrong-pointer',
    'release-free-error', 'release-backend-error', 'release-unhandled', 'release-unhandled-zero', 'thread-isolation',
])
def test_actual_background_main_wiring(background_wiring_binary, case):
    ran = subprocess.run([str(background_wiring_binary), case], capture_output=True, text=True, timeout=8)
    assert ran.returncode == 0, f'{case}: rc={ran.returncode}\n{ran.stdout}\n{ran.stderr}'
    assert ran.stdout == 'PASS HOSTTEST actual background main C wiring; native/Core not verified\n'


def test_background_main_hook_source_order():
    """Only ordering outside the executed slices is checked by source shape."""
    source = (HERE / 'menu-observe.c').read_text()
    sent, freed = (function(source, name) for name in ('osal_snd_msg', 'osal_free_msg'))
    assert 'functional_background_start_bind_original_source(__builtin_return_address(0),' in sent
    assert sent.index('functional_background_start_dispatch(') < sent.index('native_functional_camera_control_dispatch(')
    assert sent.index('functional_background_start_dispatch(') < sent.index('if(cp_owned_state_enabled && !functional_camera_enabled')
    assert freed.index('native_background_start_release(') < freed.index('full_adf_hdmi_audio_connection_release(')
    assert freed.index('full_adf_hdmi_audio_connection_release(') < freed.index('native_background_start_progress(')
