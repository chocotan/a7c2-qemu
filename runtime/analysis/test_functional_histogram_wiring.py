"""Execute actual histogram main wiring and receive-ticket handoff; no VM or fake camera product."""
from pathlib import Path
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def histogram_wiring_binary(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    names = ('functional_camera_global_queue_bind', 'functional_histogram_prepare',
             'functional_histogram_reserve_resources', 'native_histogram_received', 'native_histogram_release')
    snippets = '\n'.join(function(source, name) for name in names)
    sent = function(source, 'osal_snd_msg')
    sent = sent[sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_HISTOGRAM_SID'):
                sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_VDF_PATH_SID')]
    sent = sent.replace('__builtin_return_address(0)', 'fixture_caller')
    code = r'''
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
#include "device-models/functional-histogram.h"
#include "device-models/functional-vdf-path.h"
static int functional_histogram_reserve_resources(void);
static int functional_camera_enabled=1,functional_camera_setup_error,graph_ready=1;
static unsigned int functional_histogram_binding,functional_histogram_used;
static int functional_histogram_owner_pid;
struct functional_histogram_receive_ticket {void *pointer;unsigned int destination;uint64_t cycle;unsigned int ready;};
static struct functional_histogram_receive_ticket functional_histogram_tickets[2];
static unsigned long appfw_base=0x10000000UL;
static void *fixture_caller=(void *)(0x10000000UL+0x34e53acUL);
static unsigned int request_source=0x80946187,global_sources[2]={0x80946187,0x80946187},request_bytes=12;
static unsigned char request_wire[12]={0x0d,0x20,0x48,1,12,0,1,0x80,1,1,0,0};
static unsigned char ack[12],notification[1034],foreign[12];
static int owner_result,bridge_result,bind_result,owner_calls,bridge_calls,bind_calls;
static int open_calls,read_calls,close_calls,open_failure,bad_read=-1,read_result;
static int bound_logs,retained_logs,dispatch_calls,dispatch_handled=1,dispatch_result;
static int guard_held,guard_calls,guard_error,observe_calls,observe_result=1,release_calls,free_calls;
static int free_result,release_handled=1,failed_free;
static uint64_t observed_cycle=1,last_release_cycle;
static void *last_release_pointer;
static char binding_log[512];
static long guest_syscall(long number){assert(number==178);return syscall(SYS_gettid);}
#define syscall guest_syscall
static int memory_open(const char *path,int flags){
 assert(!strcmp(path,"/proc/self/mem") && !flags);open_calls++;errno=EACCES;return open_failure?-1:23;
}
static long memory_read(int fd,void *out,size_t size,long offset){
 assert(fd==23 && out && size==4 && (unsigned long)offset==appfw_base+0x910fa20UL);
 int index=read_calls++;errno=EIO;if(index==bad_read)return read_result;
 memcpy(out,&global_sources[(unsigned int)index%2],4);return 4;
}
static int memory_close(int fd){assert(fd==23);close_calls++;errno=EBADF;return 0;}
#define open memory_open
#define pread memory_read
#define close memory_close
static unsigned int source_api(void *p){assert(p);return request_source;}
static unsigned int (*real_get_source)(void *)=source_api;
static unsigned int size_api(void *p){assert(p);return request_bytes;}
static unsigned int (*real_msg_size)(void *)=size_api;
static int real_free_msg(unsigned int id,void *p){assert(id && p);free_calls++;errno=EINTR;return free_result;}
static int real_allocate_msg(unsigned int id,void **p,unsigned int size,unsigned int option){
 assert(id && p && size && option);return -ENOMEM;
}
static void real_set_source(void *p,unsigned int source){assert(p && source);}
static int real_send_msg(unsigned int id,void *p){assert(id && p);return 0;}
static void record(const char *tag,const char *text){
 assert(tag && text);
 if(!strcmp(tag,"FUNCTIONAL_HISTOGRAM_QUEUE_BOUND ")){
  assert(strstr(text,"global_va=0x910fa20") && strstr(text,"capture_verified=0"));
  assert(strlen(text)<sizeof binding_log);strcpy(binding_log,text);bound_logs++;
 }else if(!strcmp(tag,"FUNCTIONAL_HISTOGRAM_TICKET_RETAINED ")){
  assert(strstr(text,"no_refresh=1"));retained_logs++;
 }else assert(0);
}
int functional_histogram_owner_init(void){owner_calls++;return owner_result;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){assert(logger==record);bridge_calls++;return bridge_result;}
int functional_histogram_bind_queue(unsigned int source){
 assert(source==request_source && source==global_sources[0] && source==global_sources[1]);bind_calls++;return bind_result;
}
int functional_vdf_path_bind_refresh_queue(unsigned int source){(void)source;assert(0);return -EINVAL;}
static int tracked_native_reserve_resources(int requester){assert(requester==28 && !guard_held);guard_calls++;if(guard_error)return guard_error;guard_held=1;return 0;}
static void full_vef_resources_unlock(void){assert(guard_held);guard_held=0;}
static int cp302c_no_transition_predecessors_ready(void){return graph_ready;}
int functional_histogram_dispatch(unsigned int id,void *message,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 assert(id==FUNCTIONAL_HISTOGRAM_SID && message==request_wire && enabled==1 && functional_histogram_used==1);
 assert(io && io->allocate==real_allocate_msg && io->release==real_free_msg && io->source==real_get_source);
 assert(io->size==real_msg_size && io->set_source==real_set_source && io->send==real_send_msg && io->record==record);
 assert(guard && guard->reserve==functional_histogram_reserve_resources && guard->release==full_vef_resources_unlock);
 assert(guard->predecessor_ready==cp302c_no_transition_predecessors_ready && functional_histogram_binding==2);
 assert(bind_calls==1 && bound_logs==1 && strstr(binding_log,"readback_verified=1"));dispatch_calls++;
 int rc=guard->reserve();if(!rc){assert(guard->predecessor_ready()==1);guard->release();}
 *result=rc?rc:dispatch_result;return dispatch_handled;
}
int functional_histogram_observe_receive_cycle(unsigned int id,void *message,unsigned int source,unsigned int bytes,uint64_t *ticket){
 assert(id==request_source && source==FUNCTIONAL_HISTOGRAM_SID && ticket);
 assert((message==ack && bytes==12) || (message==notification && bytes==1034));observe_calls++;errno=EDOM;
 if(observe_result==1){*ticket=observed_cycle;}return observe_result;
}
int functional_histogram_release_cycle(unsigned int id,void *message,uint64_t cycle,
 int (*release)(unsigned int,void *),void (*logger)(const char *,const char *),int *result){
 assert(release==real_free_msg && logger==record && result);release_calls++;last_release_cycle=cycle;last_release_pointer=message;
 if(!release_handled || message==foreign)return 0;
 if(id!=request_source || !cycle){*result=-ESTALE;return 1;}
 if(failed_free){*result=-EALREADY;return 1;}
 *result=release(id,message);if(*result)failed_free=1;return 1;
}
''' + snippets + r'''
static int actual_send(unsigned int id,void *message){
''' + sent + r'''
 return -999;
}
static void *receiver(void *unused){
 (void)unused;errno=ERANGE;
 native_histogram_received(request_source,ack,FUNCTIONAL_HISTOGRAM_SID,12);
 assert(errno==ERANGE);return NULL;
}
int main(int argc,char **argv){
 assert(argc==2);
 if(!strncmp(argv[1],"prepare-",8)){
  if(!strcmp(argv[1],"prepare-busy"))functional_histogram_binding=1;
  if(!strcmp(argv[1],"prepare-owner-failure"))owner_result=-ENOMEM;
  if(!strcmp(argv[1],"prepare-bridge-failure"))bridge_result=-EIO;
  int expected=functional_histogram_binding?-EBUSY:owner_result?owner_result:bridge_result;
  assert(functional_histogram_prepare()==expected);
  if(expected==-EBUSY)assert(!owner_calls && !bridge_calls);
  else if(expected)assert(functional_histogram_prepare()==expected && owner_calls==1 && bridge_calls==!owner_result);
  else{
   assert(functional_histogram_owner_pid==getpid() && owner_calls==1 && bridge_calls==1);
   assert(!functional_histogram_prepare() && owner_calls==1 && bridge_calls==1);
   if(!strcmp(argv[1],"prepare-fork")){
    pid_t child=fork();assert(child>=0);if(!child)_exit(functional_histogram_prepare()==-EXDEV?0:1);
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
   }
  }
 }else if(!strncmp(argv[1],"send-",5)){
  int expected=0;unsigned int id=FUNCTIONAL_HISTOGRAM_SID;
  if(!strcmp(argv[1],"send-short")){request_bytes=11;expected=-ENOTSUP;}
  if(!strcmp(argv[1],"send-header")){request_wire[4]=11;expected=-ENOTSUP;}
  if(!strcmp(argv[1],"send-not-ready")){graph_ready=0;expected=-ENODATA;}
  if(!strcmp(argv[1],"send-disabled")){functional_camera_enabled=0;expected=-999;}
  if(!strcmp(argv[1],"send-unrelated")){id++;expected=-999;}
  if(!strcmp(argv[1],"send-caller")){fixture_caller=(void *)(appfw_base+0x34e53a8UL);expected=-ELIBBAD;}
  if(!strcmp(argv[1],"send-open")){open_failure=1;expected=-ENODATA;}
  if(!strcmp(argv[1],"send-first-short")){bad_read=0;read_result=3;expected=-ENODATA;}
  if(!strcmp(argv[1],"send-second-short")){bad_read=1;read_result=3;expected=-ENODATA;}
  if(!strcmp(argv[1],"send-changing")){global_sources[1]^=1;expected=-ESTALE;}
  if(!strcmp(argv[1],"send-source")){request_source^=1;expected=-ESTALE;}
  if(!strcmp(argv[1],"send-zero")){request_source=global_sources[0]=global_sources[1]=0;expected=-ESTALE;}
  if(!strcmp(argv[1],"send-bind-error")){bind_result=-ESTALE;expected=-ESTALE;}
  if(!strcmp(argv[1],"send-guard")){guard_error=-EBUSY;expected=-EBUSY;}
  if(!strcmp(argv[1],"send-owner-refusal")){dispatch_result=-ENOTSUP;expected=-ENOTSUP;}
  if(!strcmp(argv[1],"send-unhandled")){dispatch_handled=0;expected=-ENOTSUP;}
  errno=EDOM;assert(actual_send(id,request_wire)==expected && !guard_held);
  if(dispatch_calls){assert(owner_calls==1 && bridge_calls==1 && bind_calls==1 && guard_calls==1);}
  else assert(!functional_histogram_used && !free_calls);
 }else{
  functional_histogram_owner_pid=getpid();functional_histogram_used=1;
  if(!strcmp(argv[1],"receive-gates")){
   functional_histogram_used=0;native_histogram_received(request_source,ack,FUNCTIONAL_HISTOGRAM_SID,12);
   functional_histogram_used=1;functional_histogram_owner_pid++;native_histogram_received(request_source,ack,FUNCTIONAL_HISTOGRAM_SID,12);
   assert(!observe_calls && !functional_histogram_tickets[0].ready);
  }else if(!strcmp(argv[1],"missing-ticket")){
   int result=-77;assert(native_histogram_release(request_source,ack,&result)==1 && result==-ESTALE);
   assert(!last_release_cycle && !free_calls && !functional_histogram_tickets[0].ready);
  }else if(!strcmp(argv[1],"receive-not-owned")){
   observe_result=0;native_histogram_received(request_source,ack,FUNCTIONAL_HISTOGRAM_SID,12);
   assert(observe_calls==1 && !functional_histogram_tickets[0].ready);
  }else{
   pthread_t thread;assert(!pthread_create(&thread,NULL,receiver,NULL));assert(!pthread_join(thread,NULL));
   assert(functional_histogram_tickets[0].ready==2 && functional_histogram_tickets[0].pointer==ack && functional_histogram_tickets[0].cycle==1);
   int result=-77;
   if(!strcmp(argv[1],"immutable-ticket")){
    observed_cycle=2;native_histogram_received(request_source,ack,FUNCTIONAL_HISTOGRAM_SID,12);
    assert(retained_logs==1 && functional_histogram_tickets[0].cycle==1);
    assert(native_histogram_release(request_source,ack,&result)==1 && !result && last_release_cycle==1 && !functional_histogram_tickets[0].ready);
   }else if(!strcmp(argv[1],"failed-free")){
    free_result=-EIO;assert(native_histogram_release(request_source,ack,&result)==1 && result==-EIO && free_calls==1);
    assert(functional_histogram_tickets[0].ready==2);
    assert(native_histogram_release(request_source,ack,&result)==1 && result==-EALREADY && free_calls==1 && last_release_cycle==1);
   }else if(!strcmp(argv[1],"wrong-destination")){
    assert(native_histogram_release(request_source+1,ack,&result)==1 && result==-ESTALE && !last_release_cycle && !free_calls);
    assert(functional_histogram_tickets[0].ready==2);
   }else if(!strcmp(argv[1],"foreign-reuse")){
    assert(native_histogram_release(request_source,ack,&result)==1 && !result && !functional_histogram_tickets[0].ready);
    release_handled=0;result=-77;assert(!native_histogram_release(request_source,ack,&result) && result==-77 && !last_release_cycle);
   }else{
    assert(!strcmp(argv[1],"future-and-notification"));
    assert(native_histogram_release(request_source,ack,&result)==1 && !result && last_release_pointer==ack && last_release_cycle==1);
    native_histogram_received(request_source,notification,FUNCTIONAL_HISTOGRAM_SID,1034);
    assert(functional_histogram_tickets[1].ready==2 && functional_histogram_tickets[1].cycle==1);
    assert(native_histogram_release(request_source,foreign,&result)==0 && !last_release_cycle && functional_histogram_tickets[1].ready==2);
    assert(native_histogram_release(request_source,notification,&result)==1 && !result && last_release_cycle==1);
    assert(!functional_histogram_tickets[0].ready && !functional_histogram_tickets[1].ready && free_calls==2);
   }
  }
 }
 puts("PASS actual histogram main wiring");return 0;
}
'''
    work = tmp_path_factory.mktemp('actual-histogram-wiring')
    path, binary = work / 'actual.c', work / 'actual'
    path.write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
                            '-fno-pie', '-no-pie', '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', ['prepare-good', 'prepare-busy', 'prepare-owner-failure', 'prepare-bridge-failure',
                                 'prepare-fork', 'send-good', 'send-short', 'send-header', 'send-not-ready',
                                 'send-disabled', 'send-unrelated', 'send-caller', 'send-open', 'send-first-short',
                                 'send-second-short', 'send-changing', 'send-source', 'send-zero', 'send-bind-error',
                                 'send-guard', 'send-owner-refusal', 'send-unhandled', 'receive-gates',
                                 'receive-not-owned', 'missing-ticket', 'immutable-ticket', 'failed-free', 'wrong-destination',
                                 'foreign-reuse', 'future-and-notification'])
def test_actual_histogram_main_origin_and_immutable_handoff(histogram_wiring_binary, case):
    done = subprocess.run([str(histogram_wiring_binary), case], capture_output=True, text=True, timeout=8)
    assert done.returncode == 0, f'{case}: rc={done.returncode}\n{done.stdout}\n{done.stderr}'
    assert done.stdout.endswith('PASS actual histogram main wiring\n')
