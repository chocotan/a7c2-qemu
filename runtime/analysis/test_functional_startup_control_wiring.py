# SPDX-License-Identifier: MIT
"""Host-only startup Main helpers extracted verbatim; owner/OSAL are bounded stubs.

This checks transport wiring, not the separate owner/Core receipt suites or capture.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent
LOGS = HERE / 'scratch/functional-startup-control-main-tests/logs'
MODES = (
    'normal', 'repeat', 'same-cookie-address-reuse', 'receiver-thread', 'inline',
    'free-failure', 'send-failure', 'stale-cycle', 'missing-ticket',
    'wrong-destination', 'wrong-source', 'wrong-size', 'wrong-wire', 'wrong-cookie',
    'incomplete-model', 'unowned-request', 'request-not-freed', 'wrong-pid',
    'zero-cycle', 'not-inflight', 'faulted', 'occupied-slot', 'binding-slot',
    'wrong-sender', 'lease-pointer', 'lease-destination', 'lease-source', 'lease-size',
    'missing-size-api', 'missing-source-api', 'fork', 'concurrent-slot',
    'other-resources', 'predecessors', 'post-admission-fault', 'setup-error', 'successful-no-fault',
    'ticket-identity', 'free-clear-cycle-change', 'free-clear-busy',
)
assert len(MODES) == len(set(MODES))


def actual_source(source):
    names = ('native_startup_control_report_fault', 'native_startup_control_real_free',
             'native_startup_control_send', 'native_startup_control_received',
             'native_functional_startup_control_release', 'functional_startup_control_predecessors_ready')
    prefix = '\n'.join(line for line in source.splitlines() if line.startswith('static ') and
                       any(word in line for word in ('functional_startup_control_used,',
                           'startup_control_ticket_pointer;', 'startup_control_ticket_destination;',
                           'startup_control_ticket_cycle;')))
    assert prefix.count(';') == 4, 'actual startup globals have not landed or changed schema'
    start = source.index('    if(adf!=31 && __atomic_load_n(&functional_startup_control_used')
    end = source.index('{', start) + 1
    level = 1
    while level:
        level += (source[end] == '{') - (source[end] == '}')
        end += 1
    guard = ('static int actual_other_resources(int adf) {\n'
             ' const char *prefix="TEST";char tag[100];\n' + source[start:end] + ' return 0;\n}\n')
    ticket_start = source.index('static uint64_t native_startup_control_ticket_for(')
    ticket_end = source.index('static void native_startup_control_report_fault(', ticket_start)
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
#include "device-models/functional-startup-control.h"
#include "device-models/functional-still-format.h"
#include "device-models/functional-vdf-path.h"
#include "device-models/cp-startup-controls-diagnostic.h"
static _Thread_local long fixture_tid=384;
#define syscall(number) ((void)(number),fixture_tid)
static int functional_camera_setup_error,send_calls,free_calls,inline_mode,fault_records,snapshots,clear_refused;
static int send_rc,free_rc,received_calls,released_calls,free_tamper;
static uint64_t received_ticket,released_ticket;
static unsigned int actual_size=12,actual_source=FUNCTIONAL_STARTUP_CONTROL_SID;
static unsigned char wire[12]={1,0,0x14,0x40,0x3b,0,0,0x80,0,0xf0,0,0};
static struct functional_startup_control_snapshot candidate;
static struct functional_still_format_snapshot format;
static struct functional_vdf_path_snapshot path;
static struct native_cp_startup_controls_diagnostic_snapshot prior;
static int ee_ready=1,graph_ready=1;
static uint64_t native_startup_control_ticket_for(unsigned int,void *);
static void native_startup_control_received(unsigned int,void *,unsigned int,unsigned int);
static int native_functional_startup_control_release(unsigned int,void *,int *);
static void tamper_slot(void);
static unsigned int size_api(void *p) {assert(p==wire);return actual_size;}
static unsigned int source_api(void *p) {assert(p==wire);return actual_source;}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static void record(const char *tag,const char *text) {
 assert(tag && text);
 if(!strcmp(tag,"FUNCTIONAL_STARTUP_CONTROL_INTEGRATION_FAULT ")) {
  assert(strstr(text,"original_state_preserved=1") && strstr(text,"capture_verified=0"));
  assert(candidate.request_owned || functional_camera_setup_error);fault_records++;errno=EDOM;
 }
 if(!strcmp(tag,"FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND ")) {
  assert(strstr(text,"before_actual_send=1") && strstr(text,"cookie=0x8000003b") && !send_calls);
  assert(native_startup_control_ticket_for(FUNCTIONAL_STARTUP_CONTROL_AP,wire)==candidate.cycle);
 }
 if(!strcmp(tag,"FUNCTIONAL_STARTUP_CONTROL_TICKET_CLEAR_REFUSED "))clear_refused++;
}
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *s){snapshots++;*s=candidate;}
void functional_still_format_snapshot(struct functional_still_format_snapshot *s){*s=format;}
void functional_vdf_path_snapshot(struct functional_vdf_path_snapshot *s){*s=path;}
void native_cp_startup_controls_diagnostic_snapshot(struct native_cp_startup_controls_diagnostic_snapshot *s){*s=prior;}
static int cp_ee_controls_predecessors_ready(void){return ee_ready;}
static int cp302c_no_transition_predecessors_ready(void){return graph_ready;}
int functional_startup_control_observe_receive_cycle(unsigned int dst,void *p,unsigned int src,unsigned int bytes,uint64_t cycle){
 received_calls++;received_ticket=cycle;
 assert(dst==FUNCTIONAL_STARTUP_CONTROL_AP && p==wire && src==FUNCTIONAL_STARTUP_CONTROL_SID && bytes==12);
 if(!cycle || cycle!=candidate.cycle)return -ESTALE;
 candidate.leases[1].received=1;candidate.leases[1].receiver_tid=fixture_tid;return 1;
}
int functional_startup_control_release_cycle(unsigned int dst,void *p,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result,uint64_t cycle){
 (void)logger;released_calls++;released_ticket=cycle;
 if(p!=wire)return 0;
 if(!cycle || cycle!=candidate.cycle){*result=-ESTALE;return 1;}
 if(dst!=FUNCTIONAL_STARTUP_CONTROL_AP || !candidate.leases[1].received || fixture_tid!=384){*result=-EPROTO;return 1;}
 int rc=release(dst,p);
 if(!rc) {
  /* Owner publication follows real-free0; setup errors preserve the freed fact. */
  if(!functional_camera_setup_error)assert(!native_startup_control_ticket_for(dst,p));
  candidate.leases[1].freed=1;candidate.leases[1].pointer=NULL;
  candidate.ap_consumed=!candidate.leases[1].send_inflight;
 } else {candidate.faults=1;candidate.retained=1;candidate.transport_rc=rc;}
 *result=rc;return 1;
}
static int real_free_api(unsigned int dst,void *p){
 assert(dst==FUNCTIONAL_STARTUP_CONTROL_AP && p==wire && !candidate.ap_consumed);
 assert(native_startup_control_ticket_for(dst,p)==candidate.cycle);free_calls++;errno=EIO;
 if(free_tamper)tamper_slot();
 return free_rc;
}
static int (*real_free_msg)(unsigned int,void *)=real_free_api;
static int real_send_api(unsigned int dst,void *p){
 assert(dst==FUNCTIONAL_STARTUP_CONTROL_AP && p==wire);
 assert(native_startup_control_ticket_for(dst,p)==candidate.cycle);send_calls++;
 if(inline_mode) {
  native_startup_control_received(dst,p,FUNCTIONAL_STARTUP_CONTROL_SID,12);
  int result=17;assert(native_functional_startup_control_release(dst,p,&result)==1 && !result);
  assert(!candidate.ap_consumed && candidate.leases[1].send_inflight);
 }
 errno=EAGAIN;return send_rc;
}
static int (*real_send_msg)(unsigned int,void *)=real_send_api;
'''

SUFFIX = r'''
static void tamper_slot(void){
 if(free_tamper==1)__atomic_fetch_add(&startup_control_ticket_cycle,1,__ATOMIC_RELAXED);
 else __atomic_store_n(&startup_control_ticket_ready,1,__ATOMIC_RELEASE);
}
static void setup(void) {
 candidate=(struct functional_startup_control_snapshot){.owner_pid=getpid(),.initialized=1,.request_owned=1,
  .model_complete=1,.cycle=1,.model_instance=77};
 candidate.leases[0].freed=1;
 candidate.leases[1]=(struct native_cp_state_publication_lease){.pointer=wire,.destination=FUNCTIONAL_STARTUP_CONTROL_AP,
  .source=FUNCTIONAL_STARTUP_CONTROL_SID,.bytes=12,.sender_tid=384,.send_inflight=1};
 memcpy(candidate.reply_wire,wire,12);startup_control_ticket_pid=(unsigned int)getpid();
 path=(struct functional_vdf_path_snapshot){.owner_pid=getpid(),.initialized=1,.model_initialized=1,
  .model_complete=1,.ap_consumed=1,.model_instance=77};
 path.canonical_config[0]=1;path.canonical_config[1]=path.canonical_config[2]=5;
 format=(struct functional_still_format_snapshot){.owner_pid=getpid(),.initialized=1,.state_valid=1,
  .model_complete=1,.requests=1,.completed_cycles=1,.ap_consumed=1,.model_instance=77};
 format.leases[0].freed=format.leases[1].freed=1;
 prior.leases[0].opcode=0x4014;prior.leases[1].opcode=0x4057;prior.leases[2].opcode=0x40c8;
 prior.leases[0].requests=prior.leases[1].requests=1;
 prior.leases[0].ap_consumed=prior.leases[1].ap_consumed=1;
}
static void *receive_thread(void *p){
 fixture_tid=355;native_startup_control_received(FUNCTIONAL_STARTUP_CONTROL_AP,p,FUNCTIONAL_STARTUP_CONTROL_SID,12);return NULL;
}
static _Atomic int stopping;
static void *ticket_reader(void *p){
 while(!atomic_load(&stopping))assert(native_startup_control_ticket_for(FUNCTIONAL_STARTUP_CONTROL_AP,p)<=2001);
 return NULL;
}
static void resources(void){
 assert(!actual_other_resources(26));functional_startup_control_used=1;
 candidate.request_owned=0;assert(!actual_other_resources(26));
 candidate.requests=1;assert(actual_other_resources(26)==-ENODATA);
 int before=snapshots;assert(!actual_other_resources(31) && snapshots==before);
 for(int tag=0;tag<31;tag++)assert(actual_other_resources(tag)==-ENODATA);
 candidate.ap_consumed=1;assert(!actual_other_resources(26));
 unsigned int *blocked[]={&candidate.retained,&candidate.faults,&candidate.busy,&candidate.guard_held};
 for(size_t i=0;i<sizeof blocked/sizeof blocked[0];i++){
  *blocked[i]=1;assert(actual_other_resources(26)==-ENODATA);
  before=snapshots;assert(!actual_other_resources(31) && snapshots==before);*blocked[i]=0;
 }
 candidate.owner_pid++;assert(actual_other_resources(26)==-ENODATA);candidate.owner_pid--;
 candidate.initialized=0;assert(actual_other_resources(26)==-ENODATA);
}
static void predecessors(void){
 assert(functional_startup_control_predecessors_ready());
 candidate.model_instance++;assert(functional_startup_control_predecessors_ready());
 candidate.state_valid=1;assert(!functional_startup_control_predecessors_ready());candidate.model_instance--;
 assert(functional_startup_control_predecessors_ready());
 unsigned int *required[]={&path.initialized,&path.model_initialized,&path.model_complete,&path.ap_consumed,
  &format.initialized,&format.state_valid,&format.model_complete,&format.requests,&format.completed_cycles,
  &format.ap_consumed,&format.leases[0].freed,&format.leases[1].freed,&candidate.initialized,
  &prior.leases[0].requests,&prior.leases[0].ap_consumed,&prior.leases[1].requests,&prior.leases[1].ap_consumed};
 for(size_t i=0;i<sizeof required/sizeof required[0];i++){
  unsigned int before=*required[i];*required[i]=0;assert(!functional_startup_control_predecessors_ready());*required[i]=before;
 }
 unsigned int *blocked[]={&path.busy,&path.guard_held,&path.faults,&path.leases[0].releasing,
  &path.leases[1].releasing,&path.leases[1].send_inflight,&format.busy,&format.guard_held,&format.faults,
  &format.retained,&format.leases[0].releasing,&format.leases[1].releasing,&format.leases[1].send_inflight};
 for(size_t i=0;i<sizeof blocked/sizeof blocked[0];i++){
  *blocked[i]=1;assert(!functional_startup_control_predecessors_ready());*blocked[i]=0;
 }
 void **pointers[]={&path.leases[0].pointer,&path.leases[1].pointer,&format.leases[0].pointer,&format.leases[1].pointer};
 for(size_t i=0;i<sizeof pointers/sizeof pointers[0];i++){
  *pointers[i]=wire;assert(!functional_startup_control_predecessors_ready());*pointers[i]=NULL;
 }
 for(unsigned int i=0;i<3;i++){
  path.canonical_config[i]++;assert(!functional_startup_control_predecessors_ready());path.canonical_config[i]--;
 }
 int *pids[]={&path.owner_pid,&format.owner_pid,&candidate.owner_pid};
 for(size_t i=0;i<sizeof pids/sizeof pids[0];i++){
  (*pids[i])++;assert(!functional_startup_control_predecessors_ready());(*pids[i])--;
 }
 format.model_instance++;assert(!functional_startup_control_predecessors_ready());format.model_instance--;
 path.model_instance=0;assert(!functional_startup_control_predecessors_ready());path.model_instance=77;
 format.completed_cycles++;assert(!functional_startup_control_predecessors_ready());format.completed_cycles--;
 for(int value=0;value<=2;value+=2){
  ee_ready=value;assert(!functional_startup_control_predecessors_ready());ee_ready=1;
  graph_ready=value;assert(!functional_startup_control_predecessors_ready());graph_ready=1;
 }
 assert(functional_startup_control_predecessors_ready());
}
int main(int argc,char **argv){
 assert(argc==2);setup();const char *mode=argv[1];
 if(!strcmp(mode,"post-admission-fault")) {
  candidate.faults=1;candidate.request_owned=0;native_startup_control_report_fault();assert(!fault_records);
  candidate.request_owned=1;candidate.retained=1;candidate.transport_rc=-EIO;errno=EIO;native_startup_control_report_fault();
  assert(fault_records==1 && errno==EIO && candidate.faults && candidate.retained && candidate.transport_rc==-EIO);
 } else if(!strcmp(mode,"setup-error")){
  functional_camera_setup_error=-ESTALE;candidate.request_owned=0;errno=ERANGE;native_startup_control_report_fault();
  assert(fault_records==1 && errno==ERANGE && functional_camera_setup_error==-ESTALE);
 } else if(!strcmp(mode,"successful-no-fault")){
  errno=ERANGE;native_startup_control_report_fault();assert(!fault_records && errno==ERANGE);
 } else if(!strcmp(mode,"other-resources"))resources();
 else if(!strcmp(mode,"predecessors"))predecessors();
 else if(!strcmp(mode,"concurrent-slot")) {
  pthread_t reader;assert(!pthread_create(&reader,NULL,ticket_reader,wire));
  for(uint64_t n=1;n<=2000;n++) {
   candidate.cycle=n;send_calls=0;assert(!native_startup_control_send(FUNCTIONAL_STARTUP_CONTROL_AP,wire));
   assert(!native_startup_control_real_free(FUNCTIONAL_STARTUP_CONTROL_AP,wire));
  }
  atomic_store(&stopping,1);assert(!pthread_join(reader,NULL));assert(!startup_control_ticket_ready);
 } else if(!strcmp(mode,"fork")) {
  assert(!native_startup_control_send(FUNCTIONAL_STARTUP_CONTROL_AP,wire));
  pid_t child=fork();assert(child>=0);
  if(!child){
   assert(!native_startup_control_ticket_for(FUNCTIONAL_STARTUP_CONTROL_AP,wire));
   assert(native_startup_control_send(FUNCTIONAL_STARTUP_CONTROL_AP,wire)==-EPROTO && send_calls==1 && !free_calls);_exit(0);
  }
  int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
  assert(native_startup_control_ticket_for(FUNCTIONAL_STARTUP_CONTROL_AP,wire)==1);
 } else {
  unsigned int dst=FUNCTIONAL_STARTUP_CONTROL_AP;int bad=0;
  if(!strcmp(mode,"wrong-destination")){dst++;bad=1;}
  if(!strcmp(mode,"wrong-source")){actual_source++;bad=1;}
  if(!strcmp(mode,"wrong-size")){actual_size--;bad=1;}
  if(!strcmp(mode,"wrong-wire")){wire[8]^=1;bad=1;}
  if(!strcmp(mode,"wrong-cookie")){wire[4]^=1;bad=1;}
  if(!strcmp(mode,"incomplete-model")){candidate.model_complete=0;bad=1;}
  if(!strcmp(mode,"unowned-request")){candidate.request_owned=0;bad=1;}
  if(!strcmp(mode,"request-not-freed")){candidate.leases[0].freed=0;bad=1;}
  if(!strcmp(mode,"wrong-pid")){candidate.owner_pid++;bad=1;}
  if(!strcmp(mode,"zero-cycle")){candidate.cycle=0;bad=1;}
  if(!strcmp(mode,"not-inflight")){candidate.leases[1].send_inflight=0;bad=1;}
  if(!strcmp(mode,"faulted")){candidate.faults=1;bad=1;}
  if(!strcmp(mode,"occupied-slot")){startup_control_ticket_ready=2;bad=2;}
  if(!strcmp(mode,"binding-slot")){startup_control_ticket_ready=1;bad=2;}
  if(!strcmp(mode,"wrong-sender")){fixture_tid=355;bad=1;}
  if(!strcmp(mode,"lease-pointer")){candidate.leases[1].pointer=wire+1;bad=1;}
  if(!strcmp(mode,"lease-destination")){candidate.leases[1].destination++;bad=1;}
  if(!strcmp(mode,"lease-source")){candidate.leases[1].source++;bad=1;}
  if(!strcmp(mode,"lease-size")){candidate.leases[1].bytes--;bad=1;}
  if(!strcmp(mode,"missing-size-api")){real_msg_size=NULL;bad=1;}
  if(!strcmp(mode,"missing-source-api")){real_get_source=NULL;bad=1;}
  if(!strcmp(mode,"send-failure"))send_rc=-EIO;
  if(!strcmp(mode,"free-failure"))free_rc=-EIO;
  if(!strcmp(mode,"free-clear-cycle-change"))free_tamper=1;
  if(!strcmp(mode,"free-clear-busy"))free_tamper=2;
  if(!strcmp(mode,"inline"))inline_mode=1;
  errno=ERANGE;int rc=native_startup_control_send(dst,wire);
  if(bad)assert(rc==(bad==2?-EBUSY:-EPROTO) && !send_calls && errno==ERANGE);
  else {
   assert(rc==send_rc && send_calls==1 && errno==EAGAIN);
   if(send_rc) {
    assert(startup_control_ticket_ready==2 && !free_calls && !candidate.ap_consumed);
    candidate.faults=1;candidate.retained=1;candidate.transport_rc=send_rc;native_startup_control_report_fault();
    assert(native_startup_control_send(dst,wire)==-EPROTO && send_calls==1);
    assert(fault_records==1 && candidate.transport_rc==-EIO && startup_control_ticket_ready==2);
   } else if(!inline_mode){
    if(!strcmp(mode,"ticket-identity")){
     assert(!native_startup_control_ticket_for(dst+1,wire));
     assert(!native_startup_control_ticket_for(dst,wire+1));
     startup_control_ticket_pid++;assert(!native_startup_control_ticket_for(dst,wire));startup_control_ticket_pid--;
     startup_control_ticket_ready=1;assert(!native_startup_control_ticket_for(dst,wire));startup_control_ticket_ready=2;
    }
    if(!strcmp(mode,"stale-cycle"))candidate.cycle++;
    if(!strcmp(mode,"missing-ticket"))__atomic_store_n(&startup_control_ticket_ready,0,__ATOMIC_RELEASE);
    if(!strcmp(mode,"receiver-thread")){
     pthread_t receiver;assert(!pthread_create(&receiver,NULL,receive_thread,wire));assert(!pthread_join(receiver,NULL));
     assert(candidate.leases[1].receiver_tid==355 && fixture_tid==384);
    } else native_startup_control_received(dst,wire,FUNCTIONAL_STARTUP_CONTROL_SID,12);
    candidate.leases[1].send_inflight=0;int result=17;
    assert(native_functional_startup_control_release(dst,wire,&result)==1);
    if(!strcmp(mode,"stale-cycle") || !strcmp(mode,"missing-ticket"))assert(result==-ESTALE && !free_calls);
    else if(free_rc){
     assert(result==free_rc && free_calls==1 && startup_control_ticket_ready==2 && !candidate.ap_consumed);
     assert(candidate.faults && candidate.retained && fault_records==1);
     assert(native_startup_control_send(dst,wire)==-EPROTO && send_calls==1 && free_calls==1);
    } else if(free_tamper){
     assert(!result && free_calls==1 && clear_refused==1 && functional_camera_setup_error==-ESTALE);
     assert(fault_records==1 && candidate.leases[1].freed && startup_control_ticket_ready);
    } else {
     assert(!result && free_calls==1 && !startup_control_ticket_ready && candidate.ap_consumed);
     if(!strcmp(mode,"repeat") || !strcmp(mode,"same-cookie-address-reuse")){
      uint64_t old=received_ticket;candidate.ap_consumed=0;candidate.cycle++;candidate.leases[1].pointer=wire;
      candidate.leases[1].received=0;candidate.leases[1].send_inflight=1;
      if(!strcmp(mode,"repeat")){wire[2]=0x57;memcpy(candidate.reply_wire,wire,12);}
      send_calls=0;assert(!native_startup_control_send(dst,wire));native_startup_control_received(dst,wire,FUNCTIONAL_STARTUP_CONTROL_SID,12);
      candidate.leases[1].send_inflight=0;assert(native_functional_startup_control_release(dst,wire,&result)==1 && !result);
      assert(received_ticket==old+1 && released_ticket==old+1 && free_calls==2 && !startup_control_ticket_ready);
     }
    }
   } else assert(free_calls==1 && !startup_control_ticket_ready && !candidate.ap_consumed);
  }
 }
 if(!free_tamper && strcmp(mode,"setup-error"))assert(!functional_camera_setup_error);
 if(!candidate.faults && !functional_camera_setup_error)assert(!fault_records);
 printf("ACTUAL_STARTUP_CONTROL_WIRING_PASS %s capture_verified=false physical_asic_verified=false\n",mode);return 0;
}
'''


def save_log(name, value):
    LOGS.mkdir(parents=True, exist_ok=True)
    # Preserve previous failures and source revisions across development reruns.
    with tempfile.NamedTemporaryFile(mode='w', prefix=name + '-', suffix='.json', dir=LOGS,
                                     encoding='utf-8', delete=False) as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write('\n')


@pytest.fixture(scope='module', params=['c11', 'asan-ubsan'])
def wiring_binary(request):
    mode = request.param
    LOGS.mkdir(parents=True, exist_ok=True)
    production = (HERE / 'menu-observe.c').read_bytes()
    extracted = actual_source(production.decode('utf-8'))
    code = PREFIX + extracted + SUFFIX
    save_log('inputs-' + mode, {'source': 'menu-observe.c',
             'production_sha256': hashlib.sha256(production).hexdigest(),
             'extracted_production': extracted,
             'extracted_harness_sha256': hashlib.sha256(code.encode()).hexdigest(),
             'capture_verified': False, 'physical_asic_verified': False})
    with tempfile.TemporaryDirectory(prefix='build-' + mode + '-', dir=LOGS) as folder:
        source = Path(folder) / 'actual.c'
        source.write_text(code)
        binary = Path(folder) / 'actual'
        flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
        if mode == 'asan-ubsan':
            flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                      '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
        command = [*shlex.split(os.environ.get('CC', 'cc')), *flags, '-I', str(HERE), str(source), '-o', str(binary)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        save_log('build-' + mode, {'argv': command, 'returncode': result.returncode,
                                  'stdout': result.stdout, 'stderr': result.stderr})
        assert result.returncode == 0, result.stdout + result.stderr
        yield binary, mode


@pytest.mark.parametrize('scenario', MODES)
def test_actual_startup_control_main_tickets(wiring_binary, scenario):
    binary, mode = wiring_binary
    command = [str(binary), scenario]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10,
                            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:abort_on_error=1',
                                     UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    save_log(mode + '-' + scenario, {'argv': command, 'returncode': result.returncode,
                                    'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'Sanitizer' not in result.stderr and 'runtime error:' not in result.stderr
    assert f'ACTUAL_STARTUP_CONTROL_WIRING_PASS {scenario} capture_verified=false physical_asic_verified=false' in result.stdout
