# SPDX-License-Identifier: MIT
"""Actual observer ticket/guard code; stub owner tests wiring, not firmware capture."""
import os
from pathlib import Path
import shlex
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent
MODES = (
    'normal', 'repeat', 'receiver-thread', 'inline', 'free-failure', 'send-failure',
    'stale-cycle', 'missing-ticket', 'wrong-destination', 'wrong-source', 'wrong-size',
    'wrong-wire', 'incomplete-model', 'unowned-request', 'request-not-freed', 'wrong-pid',
    'zero-cycle', 'not-inflight', 'faulted', 'occupied-slot', 'fork', 'concurrent-slot',
    'predecessors', 'other-resources', 'post-admission-fault',
)


def actual_source():
    source = (HERE / 'menu-observe.c').read_text()
    names = ('native_still_format_report_fault', 'native_still_format_real_free', 'native_still_format_send', 'native_still_format_received',
             'native_functional_still_format_release', 'functional_still_format_predecessors_ready')
    prefix = '\n'.join(line for line in source.splitlines() if line.startswith('static ') and
                       any(word in line for word in ('functional_still_format_used,',
                           'still_format_ticket_pointer;', 'still_format_ticket_destination;',
                           'still_format_ticket_cycle;')))
    assert prefix.count(';') == 4
    start = source.index('    if(adf!=30 && __atomic_load_n(&functional_still_format_used')
    end = source.index('    /* Only prior owners are inspected;', start)
    guard = ('static int actual_other_resources(int adf) {\n'
             ' const char *prefix="TEST";char tag[100];\n' + source[start:end] + ' return 0;\n}\n')
    ticket_start = source.index('static uint64_t native_still_format_ticket_for(')
    ticket_end = source.index('static void native_still_format_report_fault(', ticket_start)
    return prefix + '\n' + source[ticket_start:ticket_end] + '\n'.join(function(source, name) for name in names) + '\n' + guard


PREFIX = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include "device-models/functional-still-format.h"
#include "device-models/functional-vdf-path.h"
#include "device-models/cp-capture-format.h"
static _Thread_local long fixture_tid=383;
#define syscall(number) ((void)(number),fixture_tid)
static int functional_camera_setup_error,send_calls,free_calls,record_calls,inline_mode,fault_records;
static int send_rc,free_rc,received_calls,released_calls,prior_ready=1,all13_ready=1;
static uint64_t received_ticket,released_ticket;
static unsigned int actual_size=12,actual_source=FUNCTIONAL_STILL_FORMAT_SID;
static unsigned char wire[12]={1,0,0x2d,0x40,0x3b,0,0,0x80,0,0xf0,0,0};
static struct functional_still_format_snapshot candidate;
static struct functional_vdf_path_snapshot path;
static struct native_cp_capture_format_diagnostic_snapshot prior;
static uint64_t native_still_format_ticket_for(unsigned int,void *);
static void native_still_format_received(unsigned int,void *,unsigned int,unsigned int);
static int native_functional_still_format_release(unsigned int,void *,int *);
static unsigned int size_api(void *p) {assert(p==wire);return actual_size;}
static unsigned int source_api(void *p) {assert(p==wire);return actual_source;}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static void record(const char *tag,const char *text) {
 assert(tag && text);record_calls++;
 if(!strcmp(tag,"FUNCTIONAL_STILL_FORMAT_INTEGRATION_FAULT ")) {
  assert(strstr(text,"original_state_preserved=1") && candidate.request_owned);fault_records++;errno=EDOM;
 }
 if(!strcmp(tag,"FUNCTIONAL_STILL_FORMAT_TICKET_BOUND ")) {
  assert(strstr(text,"before_actual_send=1") && !send_calls);
  assert(native_still_format_ticket_for(FUNCTIONAL_STILL_FORMAT_AP,wire)==candidate.cycle);
 }
}
void functional_still_format_snapshot(struct functional_still_format_snapshot *s){*s=candidate;}
void functional_vdf_path_snapshot(struct functional_vdf_path_snapshot *s){*s=path;}
void native_cp_capture_format_diagnostic_snapshot(struct native_cp_capture_format_diagnostic_snapshot *s){*s=prior;}
static int cp_capture_format_predecessors_ready_for(long sender){assert(sender==fixture_tid);return prior_ready;}
static int cp302c_no_transition_predecessors_ready(void){return all13_ready;}
int functional_still_format_observe_receive_cycle(unsigned int dst,void *p,unsigned int src,unsigned int bytes,uint64_t cycle){
 received_calls++;received_ticket=cycle;
 assert(dst==FUNCTIONAL_STILL_FORMAT_AP && p==wire && src==FUNCTIONAL_STILL_FORMAT_SID && bytes==12);
 if(cycle!=candidate.cycle)return -ESTALE;
 candidate.leases[1].received=1;candidate.leases[1].receiver_tid=fixture_tid;return 1;
}
int functional_still_format_release_cycle(unsigned int dst,void *p,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result,uint64_t cycle){
 (void)logger;released_calls++;released_ticket=cycle;
 if(p!=wire)return 0;
 if(!cycle || cycle!=candidate.cycle){*result=-ESTALE;return 1;}
 if(dst!=FUNCTIONAL_STILL_FORMAT_AP || !candidate.leases[1].received || fixture_tid!=383){*result=-EPROTO;return 1;}
 int rc=release(dst,p);
 if(!rc) {
  /* Actual free callback must clear its ticket before owner admits the next cycle. */
  assert(!native_still_format_ticket_for(dst,p));candidate.leases[1].freed=1;
  candidate.leases[1].pointer=NULL;candidate.ap_consumed=!candidate.leases[1].send_inflight;
 }
 *result=rc;return 1;
}
static int real_free_api(unsigned int dst,void *p){
 assert(dst==FUNCTIONAL_STILL_FORMAT_AP && p==wire && !candidate.ap_consumed);
 assert(native_still_format_ticket_for(dst,p)==candidate.cycle);free_calls++;errno=EIO;return free_rc;
}
static int (*real_free_msg)(unsigned int,void *)=real_free_api;
static int real_send_api(unsigned int dst,void *p){
 assert(dst==FUNCTIONAL_STILL_FORMAT_AP && p==wire);
 assert(native_still_format_ticket_for(dst,p)==candidate.cycle);send_calls++;
 if(inline_mode) {
  native_still_format_received(dst,p,FUNCTIONAL_STILL_FORMAT_SID,12);
  int result=17;assert(native_functional_still_format_release(dst,p,&result)==1 && !result);
  assert(!candidate.ap_consumed && candidate.leases[1].send_inflight);
 }
 errno=EAGAIN;return send_rc;
}
static int (*real_send_msg)(unsigned int,void *)=real_send_api;
'''

SUFFIX = r'''
static void setup(void) {
 candidate=(struct functional_still_format_snapshot){.owner_pid=getpid(),.initialized=1,.request_owned=1,
  .model_complete=1,.cycle=1,.model_instance=77};
 candidate.leases[0].freed=1;
 candidate.leases[1]=(struct native_cp_state_publication_lease){.pointer=wire,.destination=FUNCTIONAL_STILL_FORMAT_AP,
  .source=FUNCTIONAL_STILL_FORMAT_SID,.bytes=12,.sender_tid=383,.send_inflight=1};
 memcpy(candidate.reply_wire,wire,12);still_format_ticket_pid=(unsigned int)getpid();
 path=(struct functional_vdf_path_snapshot){.owner_pid=getpid(),.initialized=1,.model_initialized=1,
  .model_complete=1,.ap_consumed=1,.model_instance=77};
 path.canonical_config[0]=1;path.canonical_config[1]=path.canonical_config[2]=5;
 prior=(struct native_cp_capture_format_diagnostic_snapshot){.owner_pid=getpid(),.initialized=1,.requests=1,
  .diagnostic_only=1,.no_publication=1,.clean_completion=1,.ap_consumed=1,.request_freed=1,.reply_freed=1,
  .sender_tid=383,.waiter_tid=383,.reply_free_destination=FUNCTIONAL_STILL_FORMAT_AP,
  .reply_free_source=FUNCTIONAL_STILL_FORMAT_SID,.reply_free_bytes=12};
}
static void *receive_thread(void *p){
 fixture_tid=355;native_still_format_received(FUNCTIONAL_STILL_FORMAT_AP,p,FUNCTIONAL_STILL_FORMAT_SID,12);return NULL;
}
static _Atomic int stopping;
static void *ticket_reader(void *p){
 while(!atomic_load(&stopping))assert(native_still_format_ticket_for(FUNCTIONAL_STILL_FORMAT_AP,p)<=2001);
 return NULL;
}
int main(int argc,char **argv){
 assert(argc==2);setup();const char *mode=argv[1];
 if(!strcmp(mode,"post-admission-fault")) {
  candidate.faults=1;candidate.request_owned=0;native_still_format_report_fault();assert(!fault_records);
  candidate.request_owned=1;candidate.retained=1;errno=EIO;native_still_format_report_fault();
  assert(fault_records==1 && errno==EIO && candidate.faults && candidate.retained);
 } else if(!strcmp(mode,"predecessors")) {
  assert(functional_still_format_predecessors_ready());
  candidate.state_valid=1;assert(functional_still_format_predecessors_ready());
  candidate.model_instance++;assert(!functional_still_format_predecessors_ready());candidate.model_instance--;
  path.faults=1;assert(!functional_still_format_predecessors_ready());path.faults=0;
  prior.ap_consumed=0;assert(!functional_still_format_predecessors_ready());prior.ap_consumed=1;
  all13_ready=0;assert(!functional_still_format_predecessors_ready());all13_ready=1;
  prior_ready=0;assert(!functional_still_format_predecessors_ready());
 } else if(!strcmp(mode,"other-resources")) {
  assert(!actual_other_resources(26));functional_still_format_used=1;
  candidate.request_owned=0;assert(!actual_other_resources(26));
  candidate.requests=1;assert(actual_other_resources(26)==-ENODATA);
  assert(!actual_other_resources(30));candidate.ap_consumed=1;assert(!actual_other_resources(26));
  candidate.retained=1;assert(actual_other_resources(26)==-ENODATA);candidate.retained=0;
  candidate.faults=1;assert(actual_other_resources(26)==-ENODATA);
 } else if(!strcmp(mode,"concurrent-slot")) {
  pthread_t reader;assert(!pthread_create(&reader,NULL,ticket_reader,wire));
  for(uint64_t n=1;n<=2000;n++) {
   candidate.cycle=n;send_calls=0;assert(!native_still_format_send(FUNCTIONAL_STILL_FORMAT_AP,wire));
   assert(!native_still_format_real_free(FUNCTIONAL_STILL_FORMAT_AP,wire));
  }
  atomic_store(&stopping,1);assert(!pthread_join(reader,NULL));assert(!still_format_ticket_ready);
 } else if(!strcmp(mode,"fork")) {
  pid_t child=fork();assert(child>=0);
  if(!child){assert(native_still_format_send(FUNCTIONAL_STILL_FORMAT_AP,wire)==-EPROTO && !send_calls);_exit(0);}
  int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
 } else {
  unsigned int dst=FUNCTIONAL_STILL_FORMAT_AP;int bad=0;
  if(!strcmp(mode,"wrong-destination")){dst++;bad=1;}
  if(!strcmp(mode,"wrong-source")){actual_source++;bad=1;}
  if(!strcmp(mode,"wrong-size")){actual_size--;bad=1;}
  if(!strcmp(mode,"wrong-wire")){wire[8]^=1;bad=1;}
  if(!strcmp(mode,"incomplete-model")){candidate.model_complete=0;bad=1;}
  if(!strcmp(mode,"unowned-request")){candidate.request_owned=0;bad=1;}
  if(!strcmp(mode,"request-not-freed")){candidate.leases[0].freed=0;bad=1;}
  if(!strcmp(mode,"wrong-pid")){candidate.owner_pid++;bad=1;}
  if(!strcmp(mode,"zero-cycle")){candidate.cycle=0;bad=1;}
  if(!strcmp(mode,"not-inflight")){candidate.leases[1].send_inflight=0;bad=1;}
  if(!strcmp(mode,"faulted")){candidate.faults=1;bad=1;}
  if(!strcmp(mode,"occupied-slot")){still_format_ticket_ready=2;bad=2;}
  if(!strcmp(mode,"send-failure"))send_rc=-EIO;
  if(!strcmp(mode,"free-failure"))free_rc=-EIO;
  if(!strcmp(mode,"inline"))inline_mode=1;
  errno=ERANGE;int rc=native_still_format_send(dst,wire);
  if(bad)assert(rc==(bad==2?-EBUSY:-EPROTO) && !send_calls && errno==ERANGE);
  else {
   assert(rc==send_rc && send_calls==1 && errno==EAGAIN);
   if(send_rc) {
    assert(still_format_ticket_ready==2 && !free_calls && !candidate.ap_consumed);
    printf("ACTUAL_STILL_FORMAT_WIRING_PASS %s\n",mode);return 0;
   }
   if(!inline_mode){
    if(!strcmp(mode,"stale-cycle"))candidate.cycle++;
    if(!strcmp(mode,"missing-ticket"))__atomic_store_n(&still_format_ticket_ready,0,__ATOMIC_RELEASE);
    if(!strcmp(mode,"receiver-thread")){
     pthread_t receiver;assert(!pthread_create(&receiver,NULL,receive_thread,wire));assert(!pthread_join(receiver,NULL));
     assert(candidate.leases[1].receiver_tid==355);
    } else native_still_format_received(dst,wire,FUNCTIONAL_STILL_FORMAT_SID,12);
    candidate.leases[1].send_inflight=0;int result=17;
    assert(native_functional_still_format_release(dst,wire,&result)==1);
    if(!strcmp(mode,"stale-cycle") || !strcmp(mode,"missing-ticket"))assert(result==-ESTALE && !free_calls);
    else if(free_rc)assert(result==free_rc && free_calls==1 && still_format_ticket_ready==2 && !candidate.ap_consumed);
    else {
     assert(!result && free_calls==1 && !still_format_ticket_ready && candidate.ap_consumed);
     if(!strcmp(mode,"repeat")){
      candidate.ap_consumed=0;candidate.cycle++;candidate.leases[1].pointer=wire;
      candidate.leases[1].received=0;candidate.leases[1].send_inflight=1;wire[4]++;memcpy(candidate.reply_wire,wire,12);
      send_calls=0;assert(!native_still_format_send(dst,wire));native_still_format_received(dst,wire,FUNCTIONAL_STILL_FORMAT_SID,12);
      candidate.leases[1].send_inflight=0;assert(native_functional_still_format_release(dst,wire,&result)==1 && !result);
      assert(received_ticket==2 && released_ticket==2 && free_calls==2 && !still_format_ticket_ready);
     }
    }
   } else assert(free_calls==1 && !still_format_ticket_ready && !candidate.ap_consumed);
  }
 }
 assert(!functional_camera_setup_error);printf("ACTUAL_STILL_FORMAT_WIRING_PASS %s\n",mode);return 0;
}
'''


@pytest.fixture(scope='module', params=[False, True], ids=['c11', 'asan-ubsan'])
def wiring_binary(tmp_path_factory, request):
    folder = tmp_path_factory.mktemp('actual-still-format-wiring')
    source = folder / 'actual.c'
    source.write_text(PREFIX + actual_source() + SUFFIX)
    binary = folder / 'actual'
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
    if request.param:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    command = [*shlex.split(os.environ.get('CC', 'cc')), *flags, '-I', str(HERE), str(source), '-o', str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', MODES)
def test_actual_still_format_main_tickets(wiring_binary, mode):
    result = subprocess.run([str(wiring_binary), mode], capture_output=True, text=True, timeout=10,
                            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
                                     UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'ACTUAL_STILL_FORMAT_WIRING_PASS {mode}' in result.stdout


@pytest.fixture(scope='module', params=[False, True], ids=['c11', 'asan-ubsan'])
def mirror_binary(tmp_path_factory, request):
    folder = tmp_path_factory.mktemp('actual-record-mirror')
    source = folder / 'actual.c'
    prefix = r'''
#define _GNU_SOURCE
#define MENU_OBSERVE_TRANSPORT_SELFTEST 1
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static char *memory_log;
static char captured[4096];
static int writes,opens;
static int fixture_open(const char *path,int flags,...) {
 assert(!strcmp(path,"/dev/console") && flags==1);opens++;return 73;
}
static ssize_t fixture_write(int fd,const void *data,size_t bytes) {
 assert(fd==73 && bytes<sizeof captured);memcpy(captured,data,bytes);captured[bytes]=0;writes++;return (ssize_t)bytes;
}
static int fixture_close(int fd) {(void)fd;assert(0);return -1;}
#define open fixture_open
#define write fixture_write
#define close fixture_close
'''
    suffix = r'''
static void expect(const char *tag,const char *body,int mirror) {
 writes=0;captured[0]=0;errno=ERANGE;record(tag,body);assert(errno==ERANGE && writes==mirror);
 if(mirror) {
  char expected[4096];int bytes=snprintf(expected,sizeof expected,"OBS %s%s\n",tag,body?body:"");
  assert(bytes>0 && (size_t)bytes<sizeof expected && !strcmp(captured,expected));
 } else assert(!captured[0]);
}
int main(int argc,char **argv) {
 assert(argc==2);
 if(!strcmp(argv[1],"positive")) {
  const char *families[]={"FUNCTIONAL_STILL_FORMAT ","FUNCTIONAL_STARTUP_CONTROL "};
  const char *events[]={"event=REQUEST_FREE","event=RECEIVE","event=SENDER_FREE","event=CYCLE"};
  for(size_t i=0;i<sizeof families/sizeof families[0];i++)
   for(size_t j=0;j<sizeof events/sizeof events[0];j++)expect(families[i],events[j],1);
  const char *tags[]={"FUNCTIONAL_STILL_FORMAT_PREDECESSORS ","FUNCTIONAL_STILL_FORMAT_RESOURCES_TTS_TABLE ",
   "FUNCTIONAL_STILL_FORMAT_TICKET_BOUND ","FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS ",
   "FUNCTIONAL_STARTUP_CONTROL_RESOURCES_TTS_TABLE ","FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND ",
   "FUNCTIONAL_CAMERA_BRIDGE ","NATIVE_CP_STARTUP_DIAGNOSTIC_REQUEST ","FULL_SCALAR_CONNECT_REQUEST ",
   "FULL_HDMIPIN_NATIVE_REPLY_FREE ","FULL_OSDPIN_NATIVE_REPLY_FREE ","PIN_QUERY "};
  for(size_t i=0;i<sizeof tags/sizeof tags[0];i++)expect(tags[i],"existing=1",1);
  expect("FUNCTIONAL_STILL_FORMAT ",NULL,1);assert(opens==1);
 } else {
  assert(!strcmp(argv[1],"negative"));
  const char *tags[]={NULL,"","FUNCTIONAL_STILL_FORMAT","FUNCTIONAL_STARTUP_CONTROL",
   "FUNCTIONAL_STILL_FORMATX ","FUNCTIONAL_STILL_FORMAT-REQUEST ","FUNCTIONAL_STILL_FORMAT\t",
   "FUNCTIONAL_STARTUP_CONTROLS ","FUNCTIONAL_STARTUP_CONTROL-REQUEST ","FUNCTIONAL_STARTUP_CONTROL\t",
   "\"FUNCTIONAL_STILL_FORMAT ","'FUNCTIONAL_STARTUP_CONTROL ","prefix FUNCTIONAL_STILL_FORMAT ",
   "prefix FUNCTIONAL_STARTUP_CONTROL_","UNKNOWN_TAG ","FUNCTIONAL_UNKNOWN ","BEGIN "};
  for(size_t i=0;i<sizeof tags/sizeof tags[0];i++)expect(tags[i],"FUNCTIONAL_STILL_FORMAT event=RECEIVE",0);
  assert(!opens);
 }
 printf("ACTUAL_RECORD_MIRROR_PASS %s\n",argv[1]);return 0;
}
'''
    source.write_text(prefix + function((HERE / 'menu-observe.c').read_text(), 'record') + suffix)
    binary = folder / 'actual'
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic']
    if request.param:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    command = [*shlex.split(os.environ.get('CC', 'cc')), *flags, str(source), '-o', str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('mode', ['positive', 'negative'])
def test_actual_record_mirror_gate(mirror_binary, mode):
    result = subprocess.run([str(mirror_binary), mode], capture_output=True, text=True, timeout=10,
                            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
                                     UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f'ACTUAL_RECORD_MIRROR_PASS {mode}' in result.stdout
