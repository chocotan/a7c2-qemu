"""Execute the actual functional application setup and lazy MPR binding boundaries."""
from pathlib import Path
import hashlib
import re
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent

# Older extracted Main fixtures keep OU disabled while retaining their original assertions.
INACTIVE_OU_FIXTURE = r'''
static unsigned int functional_cp_ou_crank_control_used,functional_cp_ou_crank_control_ticket_pid;
void native_functional_camera_ou_crank_snapshot(struct native_functional_camera_ou_crank_snapshot *out){
 assert(!functional_cp_ou_crank_control_used);memset(out,0,sizeof *out);
}
int native_functional_camera_ou_crank_owner_init(void){return 0;}
'''


@pytest.fixture(scope='module')
def executable(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    entry = source.index('static void *observe_application_init(void *argument) {')
    begin = source.index('    if(functional_camera_enabled){', entry)
    end = source.index('    if (getenv("MENU_MEDIA_INIT_WATCH")', begin)
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "device-models/functional-camera-control.h"
#include "functional-mpr-codec.h"
#include "device-models/imaging-device.h"
static int functional_camera_enabled,functional_camera_setup_error,memory_result,memory_calls,jpeg_calls,jpeg_result,capture_calls,capture_result,imaging_calls,imaging_result;
static int focus_binding_calls,focus_binding_result,query_binding_calls,query_binding_result;
static int functional_focus_query_read(const unsigned char wire[12],unsigned char state[128]){
 (void)wire;(void)state;assert(0);return -ENOSYS;
}
static int functional_focus_reset_apply(const unsigned char wire[16],struct full_imaging_focus_reset_receipt *out){
 (void)wire;(void)out;assert(0);return -ENOSYS;
}
static unsigned int functional_mpr_binding;
static void *functional_mpr_library_handle;
static int owner_calls,owner_result,bind_calls,loader_calls,model_ready=1,bad_symbol;
typedef struct {const char *dli_fname;void *dli_fbase;const char *dli_sname;void *dli_saddr;} Dl_info;
static void record(const char *tag,const char *text){assert(tag && text);}
int functional_mpr_memory_enable(void (*logger)(const char *,const char *)){
 assert(logger==record);memory_calls++;return memory_result;
}
int functional_jpeg_codec_enable(void (*logger)(const char *,const char *)){
 assert(logger==record);jpeg_calls++;return jpeg_result;
}
int full_imaging_functional_enable(void){assert(memory_calls==1 && jpeg_calls==1 && !memory_result && !jpeg_result);++imaging_calls;return imaging_result;}
int full_imaging_functional_bind_focus_reset(full_imaging_focus_reset_backend backend){
 assert(imaging_calls==1 && !imaging_result && backend==functional_focus_reset_apply);++focus_binding_calls;return focus_binding_result;
}
int full_imaging_functional_bind_focus_query(full_imaging_focus_query_backend backend){
 assert(focus_binding_calls==1 && !focus_binding_result && backend==functional_focus_query_read);++query_binding_calls;return query_binding_result;
}
int functional_capture_enable(void (*logger)(const char *,const char *)){
 assert(logger==record && memory_calls==1 && jpeg_calls==1 && imaging_calls==1 && focus_binding_calls==1 && query_binding_calls==1 && !query_binding_result && !focus_binding_result && !imaging_result && !memory_result && !jpeg_result);capture_calls++;return capture_result;
}
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *out){
 memset(out,0,sizeof *out);out->model_initialized=out->start_complete=(unsigned int)model_ready;
}
int functional_mpr_codec_owner_init(void){owner_calls++;return owner_result;}
int functional_mpr_codec_bind(uintptr_t base,const char *hash){
 assert(base==0x10000000 && !strcmp(hash,FUNCTIONAL_MPR_CODEC_LIBRARY_SHA256));bind_calls++;return 0;
}
static void *load_library(const char *name,int flags){
 assert(!strcmp(name,"libmpr.so") && flags==6);loader_calls++;return (void *)0x1234;
}
static void *find_symbol(void *handle,const char *name){
 assert(handle==(void *)0x1234 && !strcmp(name,"_ZN3mpr5Codec17CallbackFromAvbbcEPvS1_"));
 return (void *)(uintptr_t)(0x10283e74u+(unsigned int)bad_symbol);
}
static int symbol_info(void *anchor,Dl_info *out){
 assert(anchor);out->dli_fbase=(void *)0x10000000;return 1;
}
static void *(*real_dlopen)(const char *,int)=load_library;
static void *(*real_dlsym)(void *,const char *)=find_symbol;
static int (*real_dladdr)(void *,Dl_info *)=symbol_info;
static void application_setup(void){
''' + source[begin:end] + '\n}\n' + function(source, 'functional_mpr_prepare') + r'''
int main(int argc,char **argv){
 assert(argc==2);
 if(!strcmp(argv[1],"setup-failure")){
  functional_camera_enabled=1;memory_result=-EIO;application_setup();
  assert(functional_camera_enabled && functional_camera_setup_error==-EIO && memory_calls==1 && !jpeg_calls && !capture_calls);
  assert(functional_mpr_prepare()==-EIO && !owner_calls && !loader_calls && !bind_calls);
 }else if(!strcmp(argv[1],"jpeg-setup-failure")){
  functional_camera_enabled=1;jpeg_result=-ENOSYS;application_setup();
  assert(functional_camera_enabled && functional_camera_setup_error==-ENOSYS && memory_calls==1 && jpeg_calls==1 && !capture_calls);
  assert(functional_mpr_prepare()==-ENOSYS && !owner_calls && !loader_calls && !bind_calls);
 }else if(!strcmp(argv[1],"imaging-setup-failure")){
  functional_camera_enabled=1;imaging_result=-EBUSY;application_setup();
  assert(functional_camera_setup_error==-EBUSY && memory_calls==1 && jpeg_calls==1 && imaging_calls==1 && !capture_calls);
 }else if(!strcmp(argv[1],"focus-bind-failure")){
  functional_camera_enabled=1;focus_binding_result=-EBUSY;application_setup();
  assert(functional_camera_setup_error==-EBUSY && imaging_calls==1 && focus_binding_calls==1 && !capture_calls);
 }else if(!strcmp(argv[1],"query-bind-failure")){
  functional_camera_enabled=1;query_binding_result=-EBUSY;application_setup();
  assert(functional_camera_setup_error==-EBUSY && focus_binding_calls==1 && query_binding_calls==1 && !capture_calls);
 }else if(!strcmp(argv[1],"capture-setup-failure")){
  functional_camera_enabled=1;capture_result=-ELIBBAD;application_setup();
  assert(functional_camera_setup_error==-ELIBBAD && memory_calls==1 && jpeg_calls==1 && capture_calls==1);
  assert(functional_mpr_prepare()==-ELIBBAD && !owner_calls && !loader_calls && !bind_calls);
 }else if(!strcmp(argv[1],"default-off")){
  application_setup();assert(!memory_calls && !jpeg_calls && !imaging_calls && !focus_binding_calls && !capture_calls && !functional_camera_setup_error);
 }else if(!strcmp(argv[1],"unready")){
  model_ready=0;assert(functional_mpr_prepare()==-ENODATA && !owner_calls && !loader_calls);
 }else if(!strcmp(argv[1],"success")){
  functional_camera_enabled=1;application_setup();assert(memory_calls==1 && jpeg_calls==1 && capture_calls==1 && !functional_camera_setup_error);
  assert(!functional_mpr_prepare() && functional_mpr_binding==2 && owner_calls==1 && bind_calls==1 && loader_calls==1);
  assert(!functional_mpr_prepare() && owner_calls==1 && bind_calls==1 && loader_calls==1);
 }else if(!strcmp(argv[1],"owner-failure")){
  owner_result=-ENOMEM;assert(functional_mpr_prepare()==-ENOMEM && functional_mpr_binding==3 && !loader_calls);
 }else if(!strcmp(argv[1],"symbol-mismatch")){
  bad_symbol=1;assert(functional_mpr_prepare()==-ELIBBAD && functional_mpr_binding==3 && !bind_calls);
 }else return 2;
 puts("PASS actual functional application/lazy binding boundary");return 0;
}
'''
    directory = tmp_path_factory.mktemp('functional-camera-wiring')
    path, binary = directory / 'actual.c', directory / 'actual'
    path.write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                    '-I', str(HERE), str(path), '-o', str(binary)],
                   check=True, capture_output=True, text=True)
    return binary


@pytest.mark.parametrize('case', ['setup-failure', 'jpeg-setup-failure', 'imaging-setup-failure', 'focus-bind-failure', 'query-bind-failure', 'capture-setup-failure', 'default-off', 'unready', 'success',
                                 'owner-failure', 'symbol-mismatch'])
def test_actual_functional_setup_and_binding(executable, case):
    result = subprocess.run([str(executable), case], check=True, capture_output=True, text=True, timeout=5)
    assert result.stdout.endswith('PASS actual functional application/lazy binding boundary\n')


@pytest.fixture(scope='module')
def query_executable(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    start = source.index('static uint64_t functional_focus_reset_hash(')
    end = source.index('static int functional_focus_reset_apply(', start)
    query = source.index('static int functional_focus_query_read(', end)
    stop = source.index('static int functional_mpr_prepare(', query)
    actual = source[start:end] + source[query:stop]
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "device-models/imaging-device.h"
#include "device-models/functional-camera-control.h"
#include "functional-camera-bridge.h"
static int functional_camera_enabled=1,functional_camera_setup_error,mode,calls,logs;
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *out){
 *out=(struct native_functional_camera_control_snapshot){.owner_pid=getpid(),.model_initialized=1,.start_complete=1,.model_instance=77};
 if(mode==8)out->owner_pid++;
 if(mode==9)out->model_initialized=0;
 if(mode==10)out->start_complete=0;
 if(mode==11)out->model_instance=0;
 if(mode==12)out->faults=1;
}
static void record(const char *tag,const char *text){
 assert(!strcmp(tag,"FUNCTIONAL_CAMERA_FOCUS_QUERY_MODEL ") && strstr(text,"capture_verified=0") && strstr(text,FULL_IMAGING_FOCUS_QUERY_POLICY));++logs;
}
int fcam_bridge_call(const struct fcam_native_origin *origin,uint32_t op,const void *input,size_t bytes,void *out,size_t capacity,struct fcam_bridge_result *r){
 assert(origin->source==FULL_IMAGING_AP && origin->destination==FULL_IMAGING_CP && origin->command==0x403e && origin->bytes==12 && origin->wire_fnv1a64);
 assert(op==FCAM_OP_STATE && !input && !bytes && capacity==128);++calls;
 unsigned char *p=out;for(unsigned i=0;i<128;++i)assert(!p[i]);p[48]=mode==18?78:77;
 *r=(struct fcam_bridge_result){.used=mode==14?127:128,.required=mode==15?129:128,.model_instance=mode==17?78:77,.result_token=mode==16?1:0};
 return mode==13?-EIO:0;
}
''' + actual + r'''
int main(int argc,char **argv){
 assert(argc==2);mode=atoi(argv[1]);unsigned char request[12]={5,0,0x3e,0x40,0x5a,0,0,0x80,1,0x0f,1,0},out[128];memset(out,0xa5,128);
 if(mode==1)functional_camera_enabled=0;
 if(mode==2)functional_camera_setup_error=-EIO;
 if(mode==4)request[0]=0;
 if(mode==5)request[1]=1;
 if(mode==6)request[2]=0x3f;
 if(mode==7)request[8]=2;
 int rc=functional_focus_query_read(mode==3?NULL:request,mode==19?NULL:out);
 int called=mode==0 || (mode>=13 && mode<=18);assert(calls==called && logs==called);
 if(mode==0)assert(!rc && out[48]==77);
 else if(mode<=3 || mode==19)assert(rc==-ENODEV);
 else if(mode<=7)assert(rc==-ENOTSUP);
 else if(mode<=12)assert(rc==-ENODATA);
 else if(mode==13)assert(rc==-EIO);
 else assert(rc==-EPROTO);
 if(!called)for(unsigned i=0;i<128;++i)assert(out[i]==0xa5);
 puts("PASS actual readonly query helper wiring only");return 0;
}
'''
    folder = tmp_path_factory.mktemp('actual-focus-query-helper')
    path, binary = folder / 'actual.c', folder / 'actual'
    path.write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                    '-I', str(HERE), str(path), '-o', str(binary)],
                   check=True, capture_output=True, text=True)
    return binary


@pytest.mark.parametrize('mode', range(20))
def test_actual_readonly_query_helper_boundaries(query_executable, mode):
    result = subprocess.run([str(query_executable), str(mode)], check=True, capture_output=True, text=True, timeout=5)
    assert result.stdout == 'PASS actual readonly query helper wiring only\n'
    assert not result.stderr


@pytest.fixture(scope='module')
def control_selector_executable(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    begin = source.index('        int selected=bytes>=12 &&')
    end = source.index('        __atomic_store_n(&functional_camera_control_used', begin)
    actual = source[begin:end]
    code = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "device-models/functional-camera-control.h"
static int functional_camera_setup_error,source_calls,ready_calls,init_calls,ready=1,init_result;
static unsigned int source_id=FUNCTIONAL_CAMERA_CONTROL_AP;
static void record(const char *tag,const char *text){(void)tag;(void)text;assert(0);}
static unsigned int source_of(void *message){assert(message);++source_calls;return source_id;}
static unsigned int (*real_get_source)(void *)=source_of;
static int cp_owned_state_predecessors_ready(void){++ready_calls;return ready;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){
 assert(logger==record);++init_calls;return init_result;
}
static int route(unsigned char *wire,unsigned int bytes,unsigned int command){
 void *message=wire;
''' + actual + r'''
 return 0;
}
int main(int argc,char **argv){
 assert(argc==2);unsigned char wire[24]={5,0,0x73,0x40,0x60,0,0,0x80};
 unsigned int bytes=12,command=0x4073;int expected=0,selected=1;
 const char *scenario=argv[1];
 if(!strcmp(scenario,"one"))wire[8]=1;
 else if(!strcmp(scenario,"setup-zero")){functional_camera_setup_error=-EIO;expected=-EIO;}
 else if(!strcmp(scenario,"setup-one")){wire[8]=1;functional_camera_setup_error=-EIO;expected=-EIO;}
 else if(!strcmp(scenario,"foreign"))source_id++;
 else if(!strcmp(scenario,"unready"))ready=0;
 else if(!strcmp(scenario,"bridge-error")){init_result=-EIO;expected=-EIO;}
 else if(!strcmp(scenario,"missing-source"))real_get_source=NULL;
 else if(!strcmp(scenario,"two")){wire[8]=2;selected=0;}
 else if(!strcmp(scenario,"wide-zero")){wire[9]=1;selected=0;}
 else if(!strcmp(scenario,"wide-one")){wire[8]=1;wire[11]=1;selected=0;}
 else if(!strcmp(scenario,"short")){bytes=11;selected=0;}
 else if(!strcmp(scenario,"long")){bytes=13;selected=0;}
 else if(!strcmp(scenario,"other-command")){command++;selected=0;}
 else if(!strcmp(scenario,"other-type")){wire[0]=6;selected=0;}
 else assert(!strcmp(scenario,"zero"));
 assert(route(wire,bytes,command)==expected);
 if(!selected || functional_camera_setup_error || !real_get_source){assert(!init_calls && !source_calls && !ready_calls);}
 else {assert(source_calls==1);assert(ready_calls==(source_id==FUNCTIONAL_CAMERA_CONTROL_AP));assert(init_calls==(source_id==FUNCTIONAL_CAMERA_CONTROL_AP && ready==1));}
 puts("PASS actual native control selector admission only");return 0;
}
'''
    folder = tmp_path_factory.mktemp('actual-native-control-selector')
    path, binary = folder / 'actual.c', folder / 'actual'
    path.write_text(code)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                    '-I', str(HERE), str(path), '-o', str(binary)],
                   check=True, capture_output=True, text=True)
    return binary


@pytest.mark.parametrize('scenario', ['zero', 'one', 'setup-zero', 'setup-one', 'foreign',
                                    'unready', 'bridge-error', 'missing-source', 'two',
                                    'wide-zero', 'wide-one', 'short', 'long',
                                    'other-command', 'other-type'])
def test_actual_native_control_selector_admission(control_selector_executable, scenario):
    result = subprocess.run([str(control_selector_executable), scenario], check=True,
                            capture_output=True, text=True, timeout=5)
    assert result.stdout == 'PASS actual native control selector admission only\n'
    assert not result.stderr


@pytest.fixture(scope='module')
def parameter_main_executable(tmp_path_factory):
    """Execute production Main slices; owner/Core replies below are wiring mocks."""
    source = (HERE / 'menu-observe.c').read_text()
    sent = function(source, 'osal_snd_msg')
    begin = sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_CAMERA_CONTROL_SID && message && real_msg_size)')
    end = sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_MPR_CODEC_DESTINATION', begin)
    route = sent[begin:end]
    begin = sent.index('    if(cp_notification_control_enabled && id==NATIVE_CP_NOTIFICATION_SID)')
    end = sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_STILL_FORMAT_SID', begin)
    legacy = sent[begin:end]
    freed = function(source, 'osal_free_msg')
    begin = freed.index('    if(__atomic_load_n(&functional_cp_parameter_bank_used')
    end = freed.index('    if(__atomic_load_n(&functional_mpr_codec_used', begin)
    release = freed[begin:end]
    begin = source.index('    functional_camera_enabled=same_name(functional_profile,FCAM_PROFILE)')
    end = source.index('    if(functional_profile){', begin)
    init = source[begin:end]
    ticket = next(line for line in source.splitlines()
                  if line.startswith('static _Thread_local struct') and 'functional_cp_parameter_bank_ticket' in line)
    allocation = function(source, 'native_pin_peer_allocated')
    allocation = allocation[:allocation.index('    if(!__atomic_load_n(&pinmem_peer_connections_used')] + '    (void)id;\n}\n'
    snippets = '\n'.join(function(source, name) for name in (
        'functional_cp_parameter_bank_reserve_resources',
        'functional_cp_parameter_bank_predecessors_ready'))
    code = r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "device-models/functional-camera-control.h"
#include "device-models/cp-parameter-batch.h"
#include "device-models/cp-notification-control.h"
#include "device-models/functional-background-start.h"
#include "device-models/functional-cp-zoom.h"
static int functional_camera_enabled=1,functional_camera_setup_error,cp_owned_state_enabled=1;
static unsigned int functional_cp_parameter_bank_used,functional_camera_control_used;
static unsigned int functional_background_start_used,functional_cp_zoom_used;
static unsigned int still_format_ticket_pid,startup_control_ticket_pid,functional_cp_crank_control_ticket_pid;
static unsigned int functional_cp_movie_format_ticket_pid,functional_bb_timecode_audit_pid;
static int cp_notification_control_enabled=1;
static uint64_t functional_cp_zoom_sequence;
static struct cp_parameter_batch cp_parameter_batch_state;
static unsigned long cp_parameter_batch_mutex[6];
static int mutex_held,locks,unlocks;
static int batch_lock(void *mutex){assert(mutex==cp_parameter_batch_mutex && !mutex_held);mutex_held=1;locks++;return 0;}
static int batch_unlock(void *mutex){assert(mutex==cp_parameter_batch_mutex && mutex_held);mutex_held=0;unlocks++;return 0;}
#define pthread_mutex_lock batch_lock
#define pthread_mutex_unlock batch_unlock
static unsigned char wire[CP_PARAMETER_BATCH_BYTES+16],foreign[8];
static unsigned int message_bytes=CP_PARAMETER_BATCH_BYTES,message_source=CP_PARAMETER_BATCH_SOURCE;
static int source_calls,size_calls,bridge_calls,bridge_rc,dispatch_calls,dispatch_rc,dispatch_handled=1;
static int capture_ready=1,owned_ready=1,capture_reads,owned_reads,resource_rc,reserves,guard_held,guard_releases;
static int old_control_calls,old_stager_calls,legacy_notification_calls,fallback_calls,free_calls,free_rc;
static int snapshot_calls,free_active,release_calls,release_handled=1,release_rc,old_release_calls;
static uint64_t expected_ticket,last_ticket;
static int control_init_calls,parameter_init_calls,still_init_calls,startup_init_calls,control_init_rc,parameter_init_rc;
static struct native_functional_camera_parameter_snapshot bank;
static int actual_free(unsigned int,void *);
static void record(const char *tag,const char *text){(void)tag;(void)text;assert(!"Main parameter route must not manufacture model logs");}
static unsigned int size_api(void *p){assert(p==wire);size_calls++;return message_bytes;}
static unsigned int source_api(void *p){assert(p==wire && !mutex_held);source_calls++;return message_source;}
static unsigned int (*real_msg_size)(void *)=size_api,(*real_get_source)(void *)=source_api;
static int real_allocate_msg(unsigned int id,void **p,unsigned int bytes,unsigned int option){
 (void)id;(void)p;(void)bytes;(void)option;assert(!"4063 is one-way; Main must not allocate an ACK");return -ENOMEM;
}
static int real_free_msg(unsigned int id,void *p){assert(id && p);free_calls++;return free_rc;}
static void real_set_source(void *p,unsigned int id){(void)p;(void)id;assert(0);}
static int real_send_msg(unsigned int id,void *p){(void)id;(void)p;fallback_calls++;return -999;}
static int tracked_native_reserve_resources(int index){
 assert(index==33 && !guard_held && !mutex_held);reserves++;if(resource_rc)return resource_rc;guard_held=1;return 0;
}
static void full_vef_resources_unlock(void){assert(guard_held);guard_held=0;guard_releases++;}
static int cp_capture_format_predecessors_ready(void){assert(!mutex_held);capture_reads++;return capture_ready;}
static int cp_owned_state_predecessors_ready(void){assert(!mutex_held);owned_reads++;return owned_ready;}
int fcam_bridge_init(void (*logger)(const char *,const char *)){
 assert(logger==record && !mutex_held && !guard_held);bridge_calls++;return bridge_rc;
}
static int functional_cp_parameter_bank_reserve_resources(void);
static int functional_cp_parameter_bank_predecessors_ready(void);
int native_functional_camera_parameter_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 assert(id==FUNCTIONAL_CAMERA_CONTROL_SID && p==wire && message_bytes==FCAM_CP_PARAMETER_BANK_BYTES && enabled==1);
 assert(bridge_calls==1 && !bridge_rc && !mutex_held && !old_control_calls && !old_stager_calls);
 assert(io && io->allocate==real_allocate_msg && io->release==real_free_msg && io->set_source==real_set_source);
 assert(io->send==real_send_msg && io->size==real_msg_size && io->source==real_get_source && io->record==record);
 assert(guard && guard->reserve==functional_cp_parameter_bank_reserve_resources && guard->release==full_vef_resources_unlock);
 assert(guard->predecessor_ready==functional_cp_parameter_bank_predecessors_ready && functional_cp_parameter_bank_used==1);
 dispatch_calls++;if(!dispatch_handled)return 0;
 int rc=guard->reserve();
 if(!rc){assert(guard->predecessor_ready()==1);rc=dispatch_rc;guard->release();}
 *result=rc;return 1;
}
void native_functional_camera_parameter_snapshot(struct native_functional_camera_parameter_snapshot *out){
 assert(!free_active && dispatch_calls==1);snapshot_calls++;*out=bank;
}
/* These handled errors are supplied by the owner mock, not inferred Main ownership. */
int native_functional_camera_parameter_release(unsigned int id,void *p,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result,uint64_t transaction){
 assert(free_active && p==wire && release==real_free_msg && logger==record && result);
 assert(transaction==expected_ticket);release_calls++;last_ticket=transaction;
 if(!release_handled)return 0;
 *result=release_rc?release_rc:release(id,p);return 1;
}
static int functional_camera_events_release(unsigned int id,void *p,int (*release)(unsigned int,void *),
 void (*logger)(const char *,const char *),int *result){
 assert(id && p && release==real_free_msg && logger==record && result);old_release_calls++;return 0;
}
static int functional_camera_control_reserve_resources(void){assert(0);return -ENOTSUP;}
static int functional_background_start_prepare(void){assert(0);return -ENOTSUP;}
static int functional_background_start_bind_original_source(void *caller,unsigned int id){(void)caller;(void)id;assert(0);return -ENOTSUP;}
static int functional_background_start_reserve_resources(void){assert(0);return -ENOTSUP;}
static int cp302c_no_transition_predecessors_ready(void){assert(0);return 0;}
static int functional_cp_zoom_prepare(void){assert(0);return -ENOTSUP;}
static int functional_cp_zoom_reserve_resources(void){assert(0);return -ENOTSUP;}
static void functional_cp_zoom_release_resources(void){assert(0);}
int functional_background_start_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 (void)id;(void)p;(void)io;(void)guard;(void)enabled;(void)result;assert(0);return 0;
}
int functional_cp_zoom_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,const struct cp_start_state_guard *data,int enabled,int *result){
 (void)id;(void)p;(void)io;(void)guard;(void)data;(void)enabled;(void)result;assert(0);return 0;
}
int native_functional_camera_control_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_state_publication_guard *guard,int enabled,int *result){
 (void)result;assert(id==FUNCTIONAL_CAMERA_CONTROL_SID && p==wire && enabled==1);
 assert(io && guard && guard->reserve==functional_camera_control_reserve_resources);
 assert(!dispatch_calls);old_control_calls++;return 0;
}
static int cp_notification_reserve_resources(void){assert(0);return -ENOTSUP;}
static int cp_notification_predecessors_ready(void){assert(0);return 0;}
int native_cp_notification_dispatch(unsigned int id,void *p,const struct full_imaging_io *io,
 const struct native_cp_notification_guard *guard,int enabled,int *result){
 (void)result;assert(id==NATIVE_CP_NOTIFICATION_SID && p==wire && io && guard && enabled==1);
 assert(!dispatch_calls);legacy_notification_calls++;return 0;
}
static unsigned int cp_notification_control_used;
static int cp_parameter_config_receive(unsigned int id,void *p,int *result){
 assert(id==NATIVE_CP_NOTIFICATION_SID && p==wire && result && !dispatch_calls);old_stager_calls++;
 if(message_bytes<4 || wire[0]!=5)return 0;
 unsigned int command=wire[2]|(unsigned int)wire[3]<<8;
 if(command!=0x4063 && command!=0x40f9)return 0;
 *result=-777;return 1;
}
static int same_name(const char *a,const char *b){return a && b && !strcmp(a,b);}
int native_functional_camera_control_owner_init(void){assert(!parameter_init_calls);control_init_calls++;return control_init_rc;}
int native_functional_camera_parameter_owner_init(void){assert(control_init_calls==1 && !control_init_rc && !still_init_calls);parameter_init_calls++;return parameter_init_rc;}
int native_functional_camera_crank_owner_init(void){assert(parameter_init_calls==1 && !parameter_init_rc && !still_init_calls);return 0;}
int native_functional_camera_movie_format_owner_init(void){assert(parameter_init_calls==1 && !parameter_init_rc && !still_init_calls);return 0;}
/* Constructor compatibility only; no timecode business result is established. */
int full_bb_timecode_control_owner_init(void){return 0;}
int functional_still_format_owner_init(void){assert(parameter_init_calls==1 && !parameter_init_rc);still_init_calls++;return 0;}
int functional_startup_control_owner_init(void){assert(still_init_calls==1);startup_init_calls++;return 0;}
''' + ticket + '\n' + allocation + '\n' + snippets + r'''
static int actual_send(unsigned int id,void *message){
''' + route + legacy + r'''
 return real_send_msg(id,message);
}
static int actual_free(unsigned int id,void *message){
 int vdf_result;
''' + release + r'''
 return real_free_msg(id,message);
}
static void actual_init(const char *functional_profile){
''' + init + r'''
}
static void no_ticket(void){
 assert(!functional_cp_parameter_bank_ticket.pointer && !functional_cp_parameter_bank_ticket.destination && !functional_cp_parameter_bank_ticket.transaction);
}
static void saved_ticket(uint64_t transaction){
 assert(functional_cp_parameter_bank_ticket.pointer==wire && functional_cp_parameter_bank_ticket.destination==FUNCTIONAL_CAMERA_CONTROL_SID);
 assert(functional_cp_parameter_bank_ticket.transaction==transaction);
}
static int free_event(unsigned int id){free_active=1;int rc=actual_free(id,wire);free_active=0;return rc;}
static void *other_thread(void *unused){
 (void)unused;no_ticket();expected_ticket=0;assert(free_event(FUNCTIONAL_CAMERA_CONTROL_SID)==-ESTALE);no_ticket();return NULL;
}
int main(int argc,char **argv){
 assert(argc==2);const char *test=argv[1];wire[0]=5;wire[1]=0xa5;wire[2]=0x63;wire[3]=0x40;
 wire[4]=0x67;wire[5]=0x45;wire[6]=0x23;wire[7]=0x81;
 cp_parameter_batch_state.owner_pid=getpid();cp_parameter_batch_state.staged=1;
 bank.owner_pid=getpid();bank.initialized=1;bank.owned=1;bank.request_freed=1;bank.transaction=UINT64_C(0x100000003);
 if(!strncmp(test,"init-",5)){
  const char *profile=FCAM_PROFILE;
  if(!strcmp(test,"init-disabled"))profile=NULL;
  else if(!strcmp(test,"init-wrong-profile"))profile="wrong";
  else if(!strcmp(test,"init-no-owned-state"))cp_owned_state_enabled=0;
  else if(!strcmp(test,"init-control-error"))control_init_rc=-EIO;
  else if(!strcmp(test,"init-parameter-error"))parameter_init_rc=-ENOMEM;
  else assert(!strcmp(test,"init-local"));
  actual_init(profile);int selected=profile && !strcmp(profile,FCAM_PROFILE) && cp_owned_state_enabled;
  assert(control_init_calls==selected && parameter_init_calls==(selected && !control_init_rc));
  assert(still_init_calls==(selected && !control_init_rc && !parameter_init_rc) && startup_init_calls==still_init_calls);
  assert(functional_camera_enabled==(selected && !control_init_rc && !parameter_init_rc));
  assert(!bridge_calls && !dispatch_calls && !reserves && !source_calls && !free_calls);
 }else if(!strncmp(test,"ticket-",7)){
  bank.retained_request=wire;bank.request_pointer=wire;bank.request_freed=0;
  if(!strcmp(test,"ticket-completed-duplicate") || !strncmp(test,"ticket-allocation-",18)) {
   bank.retained_request=NULL;bank.request_freed=1;
  }
  if(!strcmp(test,"ticket-unowned"))bank.owned=0;
  else if(!strcmp(test,"ticket-foreign-pointer"))bank.retained_request=foreign;
  else if(!strcmp(test,"ticket-zero-transaction"))bank.transaction=0;
  assert(!actual_send(FUNCTIONAL_CAMERA_CONTROL_SID,wire) && dispatch_calls==1 && snapshot_calls==1 && !old_control_calls && !old_stager_calls);
  functional_camera_control_used=1;
  if(!bank.owned || !bank.transaction || (bank.retained_request!=wire &&
     (!bank.request_freed || bank.request_pointer!=wire)))no_ticket();
  else {
   uint64_t original=bank.transaction;saved_ticket(original);expected_ticket=original;
   if(!strcmp(test,"ticket-completed-duplicate")){
    release_rc=-ESTALE;assert(free_event(FUNCTIONAL_CAMERA_CONTROL_SID)==-ESTALE);
    assert(release_calls==1 && !free_calls && !old_release_calls);saved_ticket(original);
   }else if(!strncmp(test,"ticket-allocation-",18)){
    void *allocated=!strcmp(test,"ticket-allocation-foreign")?foreign:wire;
    int allocation_rc=!strcmp(test,"ticket-allocation-failed")?-ENOMEM:0;
    native_pin_peer_allocated(FUNCTIONAL_CAMERA_CONTROL_SID,&allocated,allocation_rc,1);
    if(!allocation_rc && allocated==wire){
     no_ticket();expected_ticket=0;release_handled=0;
     assert(!free_event(FUNCTIONAL_CAMERA_CONTROL_SID) && free_calls==1 && old_release_calls==1);
    }else saved_ticket(original);
   }else if(!strcmp(test,"ticket-capture")){}
   else if(!strcmp(test,"ticket-thread")){
    pthread_t thread;release_rc=-ESTALE;assert(!pthread_create(&thread,NULL,other_thread,NULL));assert(!pthread_join(thread,NULL));
    saved_ticket(original);assert(release_calls==1 && !free_calls && !old_release_calls);
   }else {
    unsigned int id=FUNCTIONAL_CAMERA_CONTROL_SID;
    if(!strcmp(test,"ticket-wrong-id")){id++;expected_ticket=0;release_rc=-ESTALE;}
    else if(!strcmp(test,"ticket-stale-generation")){bank.transaction++;release_rc=-ESTALE;}
    else if(!strcmp(test,"ticket-missing")){
     functional_cp_parameter_bank_ticket.pointer=NULL;functional_cp_parameter_bank_ticket.destination=0;
     functional_cp_parameter_bank_ticket.transaction=0;expected_ticket=0;release_rc=-ESTALE;
    }else if(!strcmp(test,"ticket-release-error"))release_rc=-EIO;
    else if(!strcmp(test,"ticket-native-free-error"))free_rc=-EACCES;
    else if(!strcmp(test,"ticket-owner-delegates"))release_handled=0;
    else assert(!strcmp(test,"ticket-release") || !strcmp(test,"ticket-duplicate"));
    int expected=release_rc?release_rc:free_rc;
    assert(free_event(id)==expected && last_ticket==expected_ticket && release_calls==1);
    assert(snapshot_calls==1 && !fallback_calls && old_release_calls==!release_handled);
    if(!release_handled || expected){if(expected_ticket)saved_ticket(original);else if(id!=FUNCTIONAL_CAMERA_CONTROL_SID)saved_ticket(original);else no_ticket();}
    else {
     saved_ticket(original);assert(free_calls==1);
     if(!strcmp(test,"ticket-duplicate")){
      /* The captured completed event remains stale until actual pointer reallocation. */
      expected_ticket=original;release_rc=-ESTALE;assert(free_event(id)==-ESTALE && release_calls==2 && free_calls==1);
      assert(!old_release_calls && snapshot_calls==1);saved_ticket(original);
     }
    }
   }
  }
 }else {
  unsigned int id=FUNCTIONAL_CAMERA_CONTROL_SID;void *message=wire;int expected=0,bank_called=0,delegated=0,old_route=0;
  if(!strcmp(test,"strict-off")){functional_camera_enabled=0;expected=-777;delegated=1;}
  else if(!strcmp(test,"first-cold")){cp_parameter_batch_state.staged=0;expected=-777;delegated=old_route=1;}
  else if(!strcmp(test,"foreign-initial-owner")){cp_parameter_batch_state.owner_pid++;expected=-777;delegated=old_route=1;}
  else if(!strcmp(test,"40f9")){wire[2]=0xf9;message_bytes=20;expected=-777;delegated=old_route=1;}
  else if(!strcmp(test,"unrelated")){wire[2]=0x74;expected=-999;delegated=old_route=1;}
  else if(!strcmp(test,"other-type")){wire[0]=6;expected=-999;delegated=old_route=1;}
  else if(!strcmp(test,"other-id")){id++;expected=-999;}
  else if(!strcmp(test,"short-prefix")){message_bytes=3;expected=-999;delegated=old_route=1;}
  else if(!strcmp(test,"size-four")){message_bytes=4;expected=-EMSGSIZE;}
  else if(!strcmp(test,"short-bank")){message_bytes--;expected=-EMSGSIZE;}
  else if(!strcmp(test,"long-bank")){message_bytes++;expected=-EMSGSIZE;}
  else if(!strcmp(test,"setup-error")){functional_camera_setup_error=-ELIBBAD;expected=-ELIBBAD;}
  else if(!strcmp(test,"foreign-source")){message_source++;expected=-EPERM;}
  else if(!strcmp(test,"missing-source")){real_get_source=NULL;expected=-EPERM;}
  else if(!strcmp(test,"capture-predecessor")){capture_ready=0;expected=-ENODATA;}
  else if(!strcmp(test,"owned-predecessor")){owned_ready=0;expected=-ENODATA;}
  else if(!strcmp(test,"bridge-error")){bridge_rc=-EIO;expected=-EIO;}
  else if(!strcmp(test,"resource-error")){resource_rc=-EBUSY;expected=-EBUSY;bank_called=1;}
  else if(!strcmp(test,"model-error")){dispatch_rc=-EUCLEAN;expected=-EUCLEAN;bank_called=1;}
  else if(!strcmp(test,"owner-unhandled")){dispatch_handled=0;expected=-ENOTSUP;bank_called=1;}
  else {assert(!strcmp(test,"post-initial"));bank_called=1;}
  assert(actual_send(id,message)==expected && dispatch_calls==bank_called);
  assert(old_control_calls==old_route && old_stager_calls==delegated && legacy_notification_calls==delegated);
  assert(fallback_calls==(expected==-999) && !free_calls && !release_calls && !guard_held && locks==unlocks);
  assert(functional_cp_parameter_bank_used==(unsigned int)bank_called && snapshot_calls==(bank_called && dispatch_handled));
  if(bank_called){assert(bridge_calls==1 && !old_control_calls && !old_stager_calls);assert(reserves==dispatch_handled);}
  if(!strcmp(test,"capture-predecessor"))assert(capture_reads==1 && !owned_reads && !bridge_calls);
  if(!strcmp(test,"owned-predecessor"))assert(capture_reads==1 && owned_reads==1 && !bridge_calls);
  if(!strcmp(test,"bridge-error"))assert(bridge_calls==1 && !reserves);
  if(expected==-EMSGSIZE || functional_camera_setup_error)assert(!source_calls && !capture_reads && !bridge_calls);
  no_ticket();
 }
 assert(!mutex_held && locks==unlocks && !guard_held);
 puts("PASS actual Main parameter wiring MOCK; Core/AP/capture unverified");return 0;
}
'''
    code = code.replace('#include "device-models/functional-camera-control.h"\n',
                        '#include "device-models/functional-camera-control.h"\n' + INACTIVE_OU_FIXTURE)
    folder = tmp_path_factory.mktemp('actual-main-parameter-wiring')
    path, binary = folder / 'actual.c', folder / 'actual'
    path.write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', [
    'strict-off', 'first-cold', 'foreign-initial-owner', 'post-initial', '40f9', 'unrelated',
    'other-type', 'other-id', 'short-prefix', 'size-four', 'short-bank', 'long-bank',
    'setup-error', 'foreign-source', 'missing-source', 'capture-predecessor', 'owned-predecessor',
    'bridge-error', 'resource-error', 'model-error', 'owner-unhandled',
    'ticket-capture', 'ticket-unowned', 'ticket-foreign-pointer', 'ticket-zero-transaction',
    'ticket-release', 'ticket-wrong-id', 'ticket-stale-generation', 'ticket-missing',
    'ticket-release-error', 'ticket-native-free-error', 'ticket-owner-delegates',
    'ticket-duplicate', 'ticket-thread', 'init-local', 'init-disabled', 'init-wrong-profile',
    'init-no-owned-state', 'init-control-error', 'init-parameter-error',
    'ticket-completed-duplicate', 'ticket-allocation-reuse', 'ticket-allocation-foreign', 'ticket-allocation-failed',
])
def test_actual_main_parameter_route_ticket_and_init(parameter_main_executable, case):
    result = subprocess.run([str(parameter_main_executable), case], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, f'{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main parameter wiring MOCK; Core/AP/capture unverified\n'
    assert not result.stderr


@pytest.fixture(scope='module')
def parameter_resource_executable(tmp_path_factory):
    """Run the whole Main reservation function with explicit resource snapshot mocks."""
    actual = function((HERE / 'menu-observe.c').read_text(), 'tracked_native_reserve_resources')
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "device-models/functional-camera-control.h"
#include "device-models/functional-still-format.h"
#include "device-models/functional-startup-control.h"
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
static unsigned int functional_cp_parameter_bank_used=1,functional_still_format_used,functional_startup_control_used;
static unsigned int functional_cp_crank_control_used,functional_cp_movie_format_used;
void native_functional_camera_movie_format_snapshot(struct native_functional_camera_movie_format_snapshot *out){
 (void)out;assert(!"movie-format is disabled in this parameter resource fixture");
}
void native_functional_camera_crank_snapshot(struct native_functional_camera_crank_snapshot *out){
 (void)out;assert(!"crank-control is disabled in this parameter resource fixture");
}
static struct native_functional_camera_parameter_snapshot bank;
static struct functional_still_format_snapshot still;
static struct functional_startup_control_snapshot startup;
static struct full_adf_proc_snapshot proc;
static struct full_adf_set_input_snapshot input;
static struct full_adf_set_output_snapshot output;
static struct full_vef_resource_snapshot fixture;
static struct dmm_service dmm;
static int dmm_enabled=1;
static unsigned long appfw_base,cap_lock[6];
static unsigned char retained;
static int bank_reads,proc_reads,input_reads,output_reads,resource_locks,resource_unlocks,held;
static int resource_rc,admissible=1,domain_calls,admissible_calls,logs;
static enum full_vef_dmm_domain domain=FULL_VEF_DMM_SPEECH_INITIAL;
static long fixture_syscall(long number){assert(number==178);return 99;}
#define syscall fixture_syscall
static int fixture_open(const char *path,int flags){assert(!strcmp(path,"/proc/self/mem") && !flags);return -1;}
static long fixture_read(int fd,void *out,size_t bytes,long offset){(void)fd;(void)out;(void)bytes;(void)offset;assert(0);return -1;}
static int fixture_close(int fd){(void)fd;assert(0);return -1;}
#define open fixture_open
#define pread fixture_read
#define close fixture_close
static int cap_lock_api(void *lock){assert(lock==cap_lock && held);return 0;}
#define pthread_mutex_lock cap_lock_api
#define pthread_mutex_unlock cap_lock_api
static void record(const char *tag,const char *text){assert(tag && *tag && text && *text);logs++;}
void native_functional_camera_parameter_snapshot(struct native_functional_camera_parameter_snapshot *out){assert(!held);bank_reads++;*out=bank;}
void functional_still_format_snapshot(struct functional_still_format_snapshot *out){assert(!held);*out=still;}
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *out){assert(!held);*out=startup;}
void full_adf_proc_snapshot(struct full_adf_proc_snapshot *out){assert(!held);proc_reads++;*out=proc;}
void full_adf_set_input_snapshot(struct full_adf_set_input_snapshot *out){assert(!held);input_reads++;*out=input;}
void full_adf_set_output_snapshot(struct full_adf_set_output_snapshot *out){assert(!held);output_reads++;*out=output;}
int full_vef_resources_lock(void){assert(!held);resource_locks++;if(resource_rc)return resource_rc;held=1;return 0;}
void full_vef_resources_unlock(void){assert(held);resource_unlocks++;held=0;}
void pin_control_snapshot(struct pin_control_snapshot *out){assert(held);*out=fixture.control;}
void full_pin_connection_snapshot(struct pin_connection_snapshot *out){assert(held);*out=fixture.connection;}
void full_vef_snapshot(struct full_vef_snapshot *out){assert(held);*out=fixture.vef;}
void full_pinmem_snapshot(struct full_vef_snapshot *out){assert(held);*out=fixture.pinmem;}
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out){assert(held);memset(out,0,sizeof *out);}
void full_hdmi_pin_snapshot(struct full_vef_snapshot *out){assert(held);memset(out,0,sizeof *out);}
/* Only guard wiring is modeled here; these results do not establish DMM admissibility. */
enum full_vef_dmm_domain full_vef_resource_dmm_domain(const struct full_vef_resource_snapshot *snapshot){
 assert(held && snapshot && snapshot->dmm_enabled==1 && snapshot->dmm.physical==DMM_TEST_PHYSICAL);
 domain_calls++;return domain;
}
int full_vef_resources_admissible(const struct full_vef_resource_snapshot *snapshot){
 assert(held && domain_calls==1 && snapshot && snapshot->control.bound==1);
 admissible_calls++;return admissible;
}
''' + actual + r'''
static void ready(void){
 proc.owner_pid=input.owner_pid=output.owner_pid=getpid();proc.configured=input.configured=output.configured=1;
 proc.clean_completion=input.clean_completion=output.clean_completion=1;
 proc.ap_consumed=input.ap_consumed=output.ap_consumed=1;
 proc.request_freed=input.request_freed=output.request_freed=1;
 proc.reply_freed=input.reply_freed=output.reply_freed=1;
 bank.owner_pid=getpid();bank.initialized=1;
 startup.owner_pid=still.owner_pid=getpid();startup.initialized=still.initialized=1;
 fixture.control.bound=1;dmm.physical=DMM_TEST_PHYSICAL;
}
int main(int argc,char **argv){
 assert(argc==3);const char *test=argv[1];int requester=atoi(argv[2]);ready();int expected=0,early=0,bank_blocked=0;
 if(!strcmp(test,"idle")){}
 else if(!strcmp(test,"unused")){functional_cp_parameter_bank_used=0;bank.faults=1;}
 else if(!strcmp(test,"prestate-refused-idle")){
  bank.transaction=2;bank.error=bank.model_rc=-EIO;assert(!bank.verified && !bank.commits && !bank.model_called);
 }else if(!strcmp(test,"retired-owned")){
  bank.owned=bank.request_freed=bank.verified=1;bank.transaction=4;bank.commits=bank.released=3;
 }else if(!strcmp(test,"self-all-invalid")){
  assert(requester==33);bank.owner_pid++;bank.initialized=0;bank.busy=bank.guard_held=bank.faults=bank.releasing=bank.owned=1;
  bank.retained_request=&retained;
 }else if(!strcmp(test,"busy")){bank.busy=1;bank_blocked=1;}
 else if(!strcmp(test,"foreign-owner")){bank.owner_pid++;bank_blocked=1;}
 else if(!strcmp(test,"uninitialized")){bank.initialized=0;bank_blocked=1;}
 else if(!strcmp(test,"guard-held")){bank.guard_held=1;bank_blocked=1;}
 else if(!strcmp(test,"fault")){bank.faults=1;bank_blocked=1;}
 else if(!strcmp(test,"releasing")){bank.releasing=1;bank_blocked=1;}
 else if(!strcmp(test,"retained")){bank.retained_request=&retained;bank_blocked=1;}
 else if(!strcmp(test,"unfreed-owned")){bank.owned=1;bank_blocked=1;}
 else if(!strcmp(test,"startup-busy")){functional_startup_control_used=1;startup.busy=1;expected=-ENODATA;early=1;}
 else if(!strcmp(test,"still-busy")){functional_still_format_used=1;still.busy=1;expected=-ENODATA;early=1;}
 else if(!strcmp(test,"proc-busy")){proc.busy=1;expected=-1021;early=1;}
 else if(!strcmp(test,"input-retained")){input.retained_request=&retained;expected=-1021;early=1;}
 else if(!strcmp(test,"output-fault")){output.faults=1;expected=-1021;early=1;}
 else if(!strcmp(test,"resource-error")){resource_rc=-EBUSY;expected=-EBUSY;}
 else if(!strcmp(test,"empty-dmm-domain")){domain=FULL_VEF_DMM_EMPTY;expected=-1021;}
 else if(!strcmp(test,"unknown-dmm-domain")){domain=FULL_VEF_DMM_UNKNOWN;expected=-1021;}
 else if(!strcmp(test,"resource-inadmissible")){admissible=0;expected=-1021;}
 else assert(!"unknown case");
 if(bank_blocked){assert(requester!=33);expected=-ENODATA;early=1;}
 struct native_functional_camera_parameter_snapshot bank_before=bank;
 struct full_adf_proc_snapshot proc_before=proc;struct full_adf_set_input_snapshot input_before=input;
 struct full_adf_set_output_snapshot output_before=output;struct dmm_service dmm_before=dmm;
 assert(tracked_native_reserve_resources(requester)==expected);
 assert(!memcmp(&bank,&bank_before,sizeof bank) && !memcmp(&proc,&proc_before,sizeof proc));
 assert(!memcmp(&input,&input_before,sizeof input) && !memcmp(&output,&output_before,sizeof output));
 assert(!memcmp(&dmm,&dmm_before,sizeof dmm));
 assert(bank_reads==(requester!=33 && functional_cp_parameter_bank_used));
 if(bank_blocked)assert(!proc_reads && !input_reads && !output_reads && !resource_locks && !held);
 if(early)assert(!resource_locks && !domain_calls && !admissible_calls && !resource_unlocks);
 else {
  assert(resource_locks==1 && domain_calls==!resource_rc && admissible_calls==!resource_rc);
  assert(proc_reads==(requester>=2) && input_reads==(requester>=3) && output_reads==(requester>=4));
  if(!expected){assert(held && !resource_unlocks);full_vef_resources_unlock();}
  else assert(!held && resource_unlocks==!resource_rc);
 }
 assert(logs>0);
 puts("PASS actual Main parameter resource33 wiring MOCK; DMM/Core/AP unverified");return 0;
}
'''
    # This fixture does not extract the constructor, so it needs no ticket PID.
    code = code.replace('#include "device-models/functional-camera-control.h"\n',
                        '#include "device-models/functional-camera-control.h"\n' +
                        INACTIVE_OU_FIXTURE.replace(',functional_cp_ou_crank_control_ticket_pid', ''))
    folder = tmp_path_factory.mktemp('actual-main-parameter-resource33')
    path, binary = folder / 'actual.c', folder / 'actual'
    path.write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case,requester', [
    *[('idle', index) for index in range(34)],
    *[('busy', index) for index in range(33)],
    ('self-all-invalid', 33), ('unused', 32), ('prestate-refused-idle', 32), ('retired-owned', 32),
    *[(case, 32) for case in ['foreign-owner', 'uninitialized', 'guard-held', 'fault',
                             'releasing', 'retained', 'unfreed-owned']],
    *[(case, 33) for case in ['startup-busy', 'still-busy', 'proc-busy', 'input-retained',
                             'output-fault', 'resource-error', 'empty-dmm-domain',
                             'unknown-dmm-domain', 'resource-inadmissible']],
])
def test_actual_main_parameter_bank_resource_guard(parameter_resource_executable, case, requester):
    result = subprocess.run([str(parameter_resource_executable), case, str(requester)],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, f'{case}/{requester}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main parameter resource33 wiring MOCK; DMM/Core/AP unverified\n'
    assert not result.stderr


@pytest.fixture(scope='module')
def parameter_predecessor_executable(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    actual = '\n'.join(function(source, name) for name in (
        'cp_notification_predecessors_ready_for', 'cp_capture_format_predecessors_ready_for',
        'cp_capture_format_predecessors_ready', 'cp_owned_state_predecessors_ready',
        'functional_cp_parameter_bank_predecessors_ready'))
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "device-models/cp302c-no-transition.h"
#include "device-models/cp-notification-control.h"
#include "device-models/cp-ee-controls-diagnostic.h"
#include "device-models/cp-output-policy.h"
#include "device-models/cp-parameter-batch.h"
static struct native_cp302c_snapshot cp302c;
static struct native_cp_notification_snapshot notification;
static struct native_cp_ee_controls_diagnostic_snapshot ee;
static struct cp_output_policy cp_output_policy_state;
static struct cp_output_policy_snapshot policy;
static struct cp_parameter_batch cp_parameter_batch_state;
static unsigned long cp_parameter_batch_mutex[6];
static void *cp_parameter_batch_retained_request;
static unsigned char retained;
static int graph_ready=1,ee_movie_ready=1,policy_rc,locked,locks,unlocks,graph_reads,ee_reads,policy_reads;
static long fixture_syscall(long number){assert(number==178);return 99;}
#define syscall fixture_syscall
static int fixture_lock(void *p){assert(p==cp_parameter_batch_mutex && !locked);locked=1;locks++;return 0;}
static int fixture_unlock(void *p){assert(p==cp_parameter_batch_mutex && locked);locked=0;unlocks++;return 0;}
#define pthread_mutex_lock fixture_lock
#define pthread_mutex_unlock fixture_unlock
static void record(const char *tag,const char *text){assert(tag && text && strstr(text,"capture_verified=0"));}
void native_cp302c_snapshot(struct native_cp302c_snapshot *out){assert(!locked);*out=cp302c;}
void native_cp_notification_snapshot(struct native_cp_notification_snapshot *out){assert(!locked);*out=notification;}
void native_cp_ee_controls_diagnostic_snapshot(struct native_cp_ee_controls_diagnostic_snapshot *out){assert(!locked);ee_reads++;*out=ee;}
static int cp302c_no_transition_predecessors_ready(void){graph_reads++;return graph_ready;}
static int cp_ee_controls_after_movie_predecessors_ready(void){return ee_movie_ready;}
int cp_output_policy_snapshot(const struct cp_output_policy *owner,uint32_t mask,struct cp_output_policy_snapshot *out){
 assert(locked && owner==&cp_output_policy_state && mask==CP_OUTPUT_POLICY_KNOWN_MASK);policy_reads++;*out=policy;return policy_rc;
}
''' + actual + r'''
static void ready(void){
 cp302c.owner_pid=getpid();cp302c.initialized=cp302c.diagnostic=cp302c.diagnostic_transport=1;
 cp302c.requests=cp302c.clean_completion=cp302c.ap_consumed=cp302c.request_freed=cp302c.reply_freed=1;
 cp302c.sender_tid=cp302c.waiter_tid=99;
 notification.owner_pid=getpid();notification.initialized=notification.requests=notification.clean_completion=1;
 notification.ap_consumed=notification.request_freed=notification.reply_freed=1;
 notification.d018_consumed=notification.d018_readback=notification.startup_sticky=1;
 notification.sender_tid=notification.waiter_tid=99;
 cp_parameter_batch_state.owner_pid=getpid();cp_parameter_batch_state.staged=1;
 policy.known_mask=CP_OUTPUT_POLICY_KNOWN_MASK;policy.config_consumed=1;
 ee.owner_pid=getpid();ee.initialized=1;
 struct native_cp_ee_controls_diagnostic_lease *p=&ee.leases[1];
 p->opcode=0x4072;p->requests=p->oneway=p->oneway_consumed=p->request_freed=p->clean_completion=1;
 p->virtual_field_mask=p->virtual_fields_consumed=3;p->virtual_fields_readback=1;
 p->source=0x80020002u;p->request_destination=NATIVE_CP_EE_CONTROLS_SID;
}
int main(int argc,char **argv){
 assert(argc==2);const char *test=argv[1];ready();int expected=0;
 struct native_cp_ee_controls_diagnostic_lease *p=&ee.leases[1];
 if(!strcmp(test,"ready"))expected=1;
 else if(!strcmp(test,"all13-missing"))graph_ready=0;
 else if(!strcmp(test,"302c-inflight"))cp302c.busy=1;
 else if(!strcmp(test,"302c-foreign-sender"))cp302c.sender_tid++;
 else if(!strcmp(test,"finite4073-repeat"))notification.requests++;
 else if(!strcmp(test,"finite4073-not-consumed"))notification.ap_consumed=0;
 else if(!strcmp(test,"finite4073-free-error"))notification.reply_free_rc=-EIO;
 else if(!strcmp(test,"finite4073-not-freed"))notification.request_freed=0;
 else if(!strcmp(test,"finite4073-retained"))notification.retained_request=&retained;
 else if(!strcmp(test,"finite4073-inflight"))notification.guard_held=1;
 else if(!strcmp(test,"finite4073-fault"))notification.faults=1;
 else if(!strcmp(test,"finite4073-sticky-missing"))notification.startup_sticky=0;
 else if(!strcmp(test,"finite4073-readback-missing"))notification.d018_readback=0;
 else if(!strcmp(test,"finite4073-foreign-sender"))notification.sender_tid++;
 else if(!strcmp(test,"initial-batch-missing"))cp_parameter_batch_state.staged=0;
 else if(!strcmp(test,"initial-batch-applied"))cp_parameter_batch_state.semantic_applied=1;
 else if(!strcmp(test,"initial-batch-foreign-owner"))cp_parameter_batch_state.owner_pid++;
 else if(!strcmp(test,"initial-batch-retained"))cp_parameter_batch_retained_request=&retained;
 else if(!strcmp(test,"policy-error"))policy_rc=-EIO;
 else if(!strcmp(test,"policy-incomplete"))policy.known_mask--;
 else if(!strcmp(test,"policy-not-consumed"))policy.config_consumed=0;
 else if(!strcmp(test,"policy-applied"))policy.semantic_applied=1;
 else if(!strcmp(test,"policy-published"))policy.published=1;
 else if(!strcmp(test,"policy-ee"))policy.ee=1;
 else if(!strcmp(test,"policy-capture"))policy.capture=1;
 else if(!strcmp(test,"earlier-ee-movie-unready"))ee_movie_ready=0;
 else if(!strcmp(test,"finite4072-foreign-owner"))ee.owner_pid++;
 else if(!strcmp(test,"finite4072-inflight"))ee.busy=1;
 else if(!strcmp(test,"finite4072-repeat"))p->requests++;
 else if(!strcmp(test,"finite4072-other-opcode"))p->opcode++;
 else if(!strcmp(test,"finite4072-not-oneway"))p->oneway=0;
 else if(!strcmp(test,"finite4072-not-consumed"))p->oneway_consumed=0;
 else if(!strcmp(test,"finite4072-not-freed"))p->request_freed=0;
 else if(!strcmp(test,"finite4072-free-error"))p->request_free_rc=-EIO;
 else if(!strcmp(test,"finite4072-fault"))p->faults=1;
 else if(!strcmp(test,"finite4072-retained"))p->retained_request=&retained;
 else if(!strcmp(test,"finite4072-live"))p->live_reply=&retained;
 else if(!strcmp(test,"finite4072-queued"))p->queued=1;
 else if(!strcmp(test,"finite4072-reply-freed"))p->reply_freed=1;
 else if(!strcmp(test,"finite4072-ap-consumed"))p->ap_consumed=1;
 else if(!strcmp(test,"finite4072-mask"))p->virtual_field_mask=1;
 else if(!strcmp(test,"finite4072-readback"))p->virtual_readback[0]=1;
 else if(!strcmp(test,"finite4072-fields-not-consumed"))p->virtual_fields_consumed=1;
 else if(!strcmp(test,"finite4072-source"))p->source++;
 else if(!strcmp(test,"finite4072-destination"))p->request_destination++;
 else assert(!"unknown case");
 unsigned char batch_before[sizeof cp_parameter_batch_state],ee_before[sizeof ee],policy_before[sizeof policy];
 memcpy(batch_before,&cp_parameter_batch_state,sizeof batch_before);memcpy(ee_before,&ee,sizeof ee_before);memcpy(policy_before,&policy,sizeof policy_before);
 assert(functional_cp_parameter_bank_predecessors_ready()==expected && !locked && locks==unlocks);
 assert(!memcmp(batch_before,&cp_parameter_batch_state,sizeof batch_before) && !memcmp(ee_before,&ee,sizeof ee_before));
 assert(!memcmp(policy_before,&policy,sizeof policy_before));
 if(expected)assert(graph_reads==1 && policy_reads==1 && ee_reads==1);
 if(!strcmp(test,"all13-missing"))assert(graph_reads==1 && !policy_reads && !ee_reads && !locks);
 if(!strncmp(test,"finite4072-",11))assert(policy_reads==1 && ee_reads==1);
 puts("PASS actual Main parameter predecessor predicates MOCK; native evidence unverified");return 0;
}
'''
    folder = tmp_path_factory.mktemp('actual-main-parameter-predecessors')
    path, binary = folder / 'actual.c', folder / 'actual'
    path.write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                            '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('case', [
    'ready', 'all13-missing', '302c-inflight', '302c-foreign-sender',
    'finite4073-repeat', 'finite4073-not-consumed', 'finite4073-free-error',
    'finite4073-not-freed', 'finite4073-retained', 'finite4073-inflight', 'finite4073-fault',
    'finite4073-sticky-missing', 'finite4073-readback-missing', 'finite4073-foreign-sender',
    'initial-batch-missing', 'initial-batch-applied', 'initial-batch-foreign-owner', 'initial-batch-retained',
    'policy-error', 'policy-incomplete', 'policy-not-consumed', 'policy-applied', 'policy-published',
    'policy-ee', 'policy-capture', 'earlier-ee-movie-unready', 'finite4072-foreign-owner',
    'finite4072-inflight', 'finite4072-repeat', 'finite4072-other-opcode', 'finite4072-not-oneway',
    'finite4072-not-consumed', 'finite4072-not-freed', 'finite4072-free-error', 'finite4072-fault',
    'finite4072-retained', 'finite4072-live', 'finite4072-queued', 'finite4072-reply-freed',
    'finite4072-ap-consumed', 'finite4072-mask', 'finite4072-readback',
    'finite4072-fields-not-consumed', 'finite4072-source', 'finite4072-destination',
])
def test_actual_main_parameter_finite_predecessors(parameter_predecessor_executable, case):
    result = subprocess.run([str(parameter_predecessor_executable), case], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, f'{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main parameter predecessor predicates MOCK; native evidence unverified\n'
    assert not result.stderr


def crank_main_source(source):
    """Insert unchanged production functions/slices into the explicit owner-mock harness."""
    sent = function(source, 'osal_snd_msg')
    begin = sent.index('    if(functional_camera_enabled && id==NATIVE_CP_EE_CONTROLS_SID && message && real_msg_size)')
    end = sent.index('    if(cp_ee_controls_enabled && id==NATIVE_CP_EE_CONTROLS_SID)', begin)
    ou_begin = sent.index('    if(functional_camera_enabled && id==NATIVE_CP_EE_CONTROLS_SID && message && real_msg_size)', begin + 1)
    crank_route = sent[begin:ou_begin]
    legacy_end = sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_STARTUP_CONTROL_SID', end)
    legacy_route = sent[end:legacy_end]
    freed = function(source, 'osal_free_msg')
    begin = freed.index('    if(__atomic_load_n(&functional_cp_crank_control_used')
    end = freed.index('    if(__atomic_load_n(&functional_camera_control_used', begin)
    release = freed[begin:end]
    begin = source.index('    functional_camera_enabled=same_name(functional_profile,FCAM_PROFILE)')
    end = source.index('    if(functional_profile){', begin)
    init = source[begin:end]
    declarations = '\n'.join(line for line in source.splitlines()
                             if line.startswith('static ') and any(name in line for name in (
                                 'functional_cp_crank_control_used,',
                                 'functional_cp_crank_control_ticket_mutex[',
                                 '} functional_cp_crank_control_ticket;',
                                 '} functional_cp_parameter_bank_ticket;')))
    begin = source.index('static uint64_t native_crank_ticket_for(')
    end = source.index('static void native_crank_received(', begin)
    ticket_for = source[begin:end]
    helpers = '\n'.join(function(source, name) for name in (
        'tracked_native_reserve_resources', 'functional_cp_crank_control_reserve_resources',
        'functional_cp_crank_control_predecessors_ready', 'native_pin_peer_allocated',
        'native_crank_allocated', 'osal_valloc_msg_wait', 'native_crank_allocate',
        'native_crank_send'))
    helpers += '\n' + ticket_for + '\n' + function(source, 'native_crank_received')
    helpers += '\n' + function(source, 'native_cp_state_received')
    code = (HERE / 'test-main-crank-wiring.c').read_text()
    declarations += '\n' + INACTIVE_OU_FIXTURE
    for marker, actual in {
        '/* ACTUAL_TICKET_DECLARATIONS */': declarations,
        '/* ACTUAL_MAIN_HELPERS */': helpers,
        '/* ACTUAL_CRANK_ROUTE */': crank_route,
        '/* ACTUAL_EE_ROUTE */': legacy_route,
        '/* ACTUAL_CRANK_FREE */': release,
        '/* ACTUAL_CRANK_INIT */': init,
    }.items():
        assert code.count(marker) == 1, marker
        code = code.replace(marker, actual)
    return '/* Main SHA256: ' + hashlib.sha256(source.encode()).hexdigest() + ' */\n' + code


@pytest.fixture(scope='module', params=['strict', 'asan-ubsan'])
def crank_main_executable(tmp_path_factory, request):
    """Only parent integration may execute this draft; Core/owner remain explicit mocks."""
    code = crank_main_source((HERE / 'menu-observe.c').read_text())
    directory = tmp_path_factory.mktemp('actual-main-crank-' + request.param)
    path, binary = directory / 'actual.c', directory / 'actual'
    path.write_text(code)
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    built = subprocess.run(['cc', *flags, '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('category,case', [
    *[('route', case) for case in [
        'cold', 'cold-fault-without-model', 'late', 'late-uncommitted', 'disabled',
        'short', 'long', 'setup-error', 'bridge-error', 'source-error', 'missing-source',
        'mode-error', 'owner-unhandled', 'owner-error', 'before-error', 'model-error',
        'receipt-short', 'receipt-mutated', 'after-error', 'bank-unfreed', 'bank-fault',
        'initial-repeat', 'policy-cookie', 'predecessor', 'synchronous']],
    *[('allocation', case) for case in ['reuse', 'failed', 'multi', 'null', 'foreign',
                                      'unused', 'borrowed']],
    *[('ticket', case) for case in ['cross-receive', 'wrong-free-thread', 'wrong-destination',
                                  'foreign-pointer', 'stale', 'completed-duplicate',
                                  'free-error', 'receive-failure', 'reuse-after-complete',
                                  'fork-before-lock']],
    *[('adapter', case) for case in ['allocate-captured-snapshot', 'allocate-unowned',
                                   'send-missing-ticket', 'send-wrong-destination',
                                   'send-stale-transaction', 'send-unverified']],
    ('init', 'local'), ('init', 'crank-error'),
])
def test_actual_main_crank_route_transport_and_allocation(crank_main_executable, category, case):
    result = subprocess.run([str(crank_main_executable), category, case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{category}/{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main crank wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


@pytest.mark.parametrize('case,requester', [
    *[('idle', index) for index in range(35)],
    ('selfskip', 34), ('bank-unfreed', 34), ('bank-fault', 34),
    *[(case, index) for case in ['crank-busy', 'crank-foreign', 'crank-uninitialized',
                                'crank-request-releasing', 'crank-guard', 'crank-fault',
                                'crank-retained-request', 'crank-retained-reply',
                                'crank-releasing', 'crank-inspecting', 'crank-inflight',
                                'crank-owned-live', 'crank-complete'] for index in range(34)],
])
def test_actual_main_crank_resource34_and_other_endpoints(crank_main_executable, case, requester):
    result = subprocess.run([str(crank_main_executable), 'resource', case, str(requester)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}/{requester}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main crank wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


def movie_allocator_binding_source(source):
    """Keep the real shared slot connected to both production symbol-resolution paths."""
    initial = ('    native_real_allocate_msg = real_dlsym((void *)-1, "osal_valloc_msg_wait");\n'
               '    real_allocate_msg = native_real_allocate_msg ? native_tracked_allocate_msg : 0;')
    assert function(source, 'initialize').count(initial) == 1
    dynamic = ('    if (symbol && same_name(name, "osal_valloc_msg_wait")) {\n'
               '        native_real_allocate_msg = symbol;\n'
               '        real_allocate_msg = native_tracked_allocate_msg;\n'
               '        return osal_valloc_msg_wait;\n'
               '    }')
    assert source.count(dynamic) == 1
    return initial.splitlines()[1], dynamic.splitlines()[2]


def movie_main_source(source):
    """Extract Main verbatim; owner/bridge/resource fixtures are explicit mocks."""
    sent = function(source, 'osal_snd_msg')
    begin = sent.index('    if(functional_camera_enabled && id==NATIVE_CP_MOVIE_FORMAT_SID && message && real_msg_size)')
    strict = sent.index('    if(cp_movie_format_enabled && id==NATIVE_CP_MOVIE_FORMAT_SID)', begin)
    end = sent.index('    if(functional_camera_enabled && id==NATIVE_CP_EE_CONTROLS_SID && message && real_msg_size)', strict)
    freed = function(source, 'osal_free_msg')
    free_begin = freed.index('    if(__atomic_load_n(&functional_cp_movie_format_used')
    free_end = freed.index('    if(__atomic_load_n(&functional_camera_control_used', free_begin)
    init_begin = source.index('    functional_camera_enabled=same_name(functional_profile,FCAM_PROFILE)')
    init_end = source.index('    if(functional_profile){', init_begin)
    declarations = '\n'.join(line for line in source.splitlines()
                             if line.startswith('static ') and any(name in line for name in (
                                 'functional_cp_crank_control_used,',
                                 'functional_cp_crank_control_ticket_mutex[',
                                 '} functional_cp_crank_control_ticket;',
                                 'functional_cp_movie_format_used,',
                                 'functional_cp_movie_format_ticket_mutex[',
                                 '} functional_cp_movie_format_ticket;',
                                 '} functional_cp_parameter_bank_ticket;')))
    assert len(declarations.splitlines()) == 7
    declarations += '\n' + INACTIVE_OU_FIXTURE + r'''
static void native_ou_crank_allocated(unsigned int id,void **out,int result,unsigned int count){
 (void)id;(void)out;(void)result;(void)count;assert(!functional_cp_ou_crank_control_used);
}
'''
    names = (
        'tracked_native_reserve_resources', 'functional_cp_movie_format_reserve_resources',
        'functional_cp_crank_control_predecessors_ready',
        'functional_cp_movie_format_predecessors_ready',
        'native_pin_peer_allocated', 'native_crank_allocated', 'native_movie_format_allocated',
        'native_tracked_allocate_msg', 'osal_valloc_msg_wait',
        'native_movie_format_allocate', 'native_movie_format_send',
    )
    helpers = {name: function(source, name) for name in names}
    # The shared extractor accepts int/void, so preserve uint64 functions by exact boundaries.
    for prefix in ('crank', 'movie_format'):
        name = 'native_' + prefix + '_ticket_for'
        start = source.index('static uint64_t ' + name + '(')
        stop = source.index('static void native_' + prefix + '_received(', start)
        helpers[name] = source[start:stop]
    for name in ('native_movie_format_received', 'native_cp_state_received'):
        helpers[name] = function(source, name)
    initial_binding, dynamic_binding = movie_allocator_binding_source(source)
    allocator_declarations = '\n'.join(line for line in source.splitlines() if line in (
        'static int (*real_allocate_msg)(unsigned int, void **, unsigned int, unsigned int);',
        'static int (*native_real_allocate_msg)(unsigned int, void **, unsigned int, unsigned int);',
        'static int native_tracked_allocate_msg(unsigned int, void **, unsigned int, unsigned int);'))
    assert len(allocator_declarations.splitlines()) == 3
    replacements = {
        '/* ACTUAL_MOVIE_TICKET_DECLARATIONS */': declarations,
        '/* ACTUAL_MOVIE_ALLOCATOR_DECLARATIONS */': allocator_declarations,
        '/* ACTUAL_MOVIE_INITIAL_ALLOCATOR_SLOT */': initial_binding,
        '/* ACTUAL_MOVIE_DLSYM_ALLOCATOR_SLOT */': dynamic_binding,
        '/* ACTUAL_MOVIE_MAIN_HELPERS */': '\n'.join(helpers.values()),
        '/* ACTUAL_MOVIE_ROUTE */': sent[begin:strict],
        '/* ACTUAL_STRICT4000_ROUTE */': sent[strict:end],
        '/* ACTUAL_MOVIE_FREE */': freed[free_begin:free_end],
        '/* ACTUAL_MOVIE_INIT */': source[init_begin:init_end],
    }
    code = (HERE / 'test-main-movie-format-wiring.c').read_text()
    provenance = ['Main SHA256: ' + hashlib.sha256(source.encode()).hexdigest()]
    for name, actual in {**helpers, **replacements}.items():
        provenance.append(name.strip('/* ') + ': ' + hashlib.sha256(actual.encode()).hexdigest())
    for marker, actual in replacements.items():
        assert code.count(marker) == 1, marker
        assert actual, marker
        code = code.replace(marker, actual)
    return '/* ' + '\n * '.join(provenance) + ' */\n' + code


@pytest.fixture(scope='module', params=['strict', 'asan-ubsan'])
def movie_main_executable(tmp_path_factory, request):
    """Host wiring only: Main is actual source; native owner and Core are mocks."""
    code = movie_main_source((HERE / 'menu-observe.c').read_text())
    directory = tmp_path_factory.mktemp('actual-main-movie-format-' + request.param)
    path, binary = directory / 'actual.c', directory / 'actual'
    path.write_text(code)
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    built = subprocess.run(['cc', *flags, '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


MOVIE_ROUTE_CASES = [
    'cold', 'cold-fault-no-model', 'disabled', 'cold-strict-unhandled', 'late',
    'short', 'long', 'prefix-only', 'truncated-prefix', 'other-type', 'other-command',
    'other-id', 'null-message', 'missing-size', 'source-error', 'missing-source',
    'setup-error', 'bridge-error', 'owner-unhandled', 'owner-error', 'format-error',
    'raw-rate-error', 'before-error', 'model-error', 'receipt-short', 'receipt-mutated',
    'after-error', 'predecessor', 'late-bank-only', 'late-crank-only', 'late-used-only',
    'opaque-fields', 'context-current-values', 'context-instance-drift', 'context-bank-drift', 'context-crank-drift',
    'context-reserve-drift', 'resource-error', 'allocate-error', 'send-error', 'request-free-error', 'synchronous',
]
MOVIE_PREDECESSOR_CASES = [
    'ready', 'historical-sender', 'all13-current-mode', 'policy-error', 'policy-cookie',
    'initial409d-repeat', 'bank-owner', 'bank-init', 'bank-commit', 'bank-verified',
    'bank-owned', 'bank-free', 'bank-busy', 'bank-guard', 'bank-fault', 'bank-releasing',
    'bank-retained', 'bank-instance', 'bank-generation', 'bank-transaction',
    'crank-owner', 'crank-init', 'crank-commit', 'crank-verified', 'crank-owned',
    'crank-complete', 'crank-instance', 'crank-bank-generation', 'crank-bank-transaction',
    'crank-bank-commits', 'crank-bank-released', 'crank-transaction', 'crank-generation',
    'crank-completions', 'crank-counts', 'crank-verified-count', 'crank-receive',
    'crank-consume', 'crank-request-free', 'crank-reply-free', 'crank-sender', 'crank-receiver',
    'crank-request-free-tid', 'crank-reply-free-tid', 'crank-busy', 'crank-guard',
    'crank-fault', 'crank-before-rc', 'crank-model-rc', 'crank-after-rc', 'crank-allocate-rc',
    'crank-send-rc', 'crank-request-free-rc', 'crank-reply-free-rc', 'crank-receive-rc',
    'crank-request-releasing', 'crank-reply-releasing', 'crank-inspecting',
    'crank-send-inflight', 'crank-retained-request', 'crank-retained-reply',
    'strict-owner', 'strict-init', 'strict-opcode', 'strict-attempts', 'strict-requests',
    'strict-queued', 'strict-request-free', 'strict-reply-free', 'strict-clean', 'strict-consumed',
    'strict-sender', 'strict-waiter', 'strict-allocate-rc', 'strict-send-rc',
    'strict-request-free-rc', 'strict-reply-free-rc', 'strict-busy', 'strict-guard', 'strict-fault',
    'strict-retained-request', 'strict-live-reply', 'strict-retained-cleanup', 'strict-source',
    'strict-request-destination', 'strict-destination', 'strict-request-bytes',
    'strict-known-mask', 'strict-virtual-mask', 'strict-readback', 'strict-fields-consumed',
    'strict-readback-bytes',
]
MOVIE_TICKET_CASES = [
    'cross-receive', 'wrong-free-thread', 'wrong-destination', 'receive-source', 'receive-bytes',
    'foreign-pointer', 'stale', 'completed-duplicate', 'free-error', 'receive-failure',
    'free-before-receive', 'reuse-after-complete', 'wrong-pid', 'fork-before-lock',
]
MOVIE_ALLOCATION_CASES = ['reuse', 'failed', 'multi', 'null', 'foreign', 'unused', 'borrowed', 'request-reuse']
MOVIE_ADAPTER_CASES = [
    'allocate-captured-snapshot', 'allocate-unowned', 'allocate-unverified', 'allocate-no-api',
    'allocate-zero-transaction', 'send-missing-ticket', 'send-wrong-destination',
    'send-stale-transaction', 'send-unverified', 'send-unowned', 'send-foreign-pointer', 'send-no-api',
]
MOVIE_BLOCKING_RESOURCE_CASES = [
    'movie-busy', 'movie-owner', 'movie-init', 'movie-guard', 'movie-fault',
    'movie-retained-request', 'movie-retained-reply', 'movie-request-releasing',
    'movie-reply-releasing', 'movie-inspecting', 'movie-send-inflight', 'movie-owned-live',
]


@pytest.mark.parametrize('category,case', [
    *[('route', case) for case in MOVIE_ROUTE_CASES],
    *[('predecessor', case) for case in MOVIE_PREDECESSOR_CASES],
    *[('ticket', case) for case in MOVIE_TICKET_CASES],
    *[('allocation', case) for case in MOVIE_ALLOCATION_CASES],
    *[('adapter', case) for case in MOVIE_ADAPTER_CASES],
    *[('init', case) for case in ['local', 'movie-error', 'disabled', 'wrong-profile', 'no-owned-state']],
])
def test_actual_main_movie_format_route_context_and_transport(movie_main_executable, category, case):
    result = subprocess.run([str(movie_main_executable), category, case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{category}/{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main movie-format wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


@pytest.mark.parametrize('case,requester', [
    *[('idle', index) for index in range(38)],
    *[(case, index) for case in MOVIE_BLOCKING_RESOURCE_CASES for index in range(35)],
    *[('movie-complete', index) for index in range(35)],
    ('selfskip', 35), ('unused', 34),
    *[(case, 35) for case in ['bank-live', 'crank-live', 'startup-live', 'still-live', 'proc-live',
                             'input-retained', 'output-fault', 'lock-error', 'dmm-empty', 'inadmissible']],
    ('invalid-low', -1), ('invalid-high', 36),
])
def test_actual_main_movie_format_resource35_and_other_endpoints(movie_main_executable, case, requester):
    # Keep the case identity; endpoints 0..37 are valid, so probe the first invalid endpoint.
    if case == 'invalid-high':
        requester = 38
    result = subprocess.run([str(movie_main_executable), 'resource', case, str(requester)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}/{requester}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main movie-format wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


@pytest.mark.parametrize('case', ['request-reuse-before-return', 'request-retained-before-return',
                                  'postdispatch-pid-mismatch', 'postdispatch-fork-before-lock'])
def test_actual_main_crank_request_ticket_rootfix(crank_main_executable, case):
    result = subprocess.run([str(crank_main_executable), 'rootfix', case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main crank wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


@pytest.mark.parametrize('case', ['request-reuse-before-return', 'request-retained-before-return',
                                  'postdispatch-pid-mismatch', 'postdispatch-fork-before-lock',
                                  'io-reply-reuse'])
def test_actual_main_movie_format_ticket_rootfix(movie_main_executable, case):
    result = subprocess.run([str(movie_main_executable), 'rootfix', case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main movie-format wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


@pytest.mark.parametrize('case', ['success', 'negative-rc', 'positive-rc', 'null-out',
                                  'null-message', 'multi-count', 'foreign-pointer', 'unused',
                                  'pid-mismatch', 'fork-before-lock', 'missing-raw', 'dlsym-slot'])
def test_actual_main_shared_allocator_ticket_rootfix(movie_main_executable, case):
    result = subprocess.run([str(movie_main_executable), 'shared-allocator', case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main movie-format wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


def test_actual_main_shared_allocator_initial_binding_source():
    source = (HERE / 'menu-observe.c').read_text()
    initial, _ = movie_allocator_binding_source(source)
    assert initial.strip() == 'real_allocate_msg = native_real_allocate_msg ? native_tracked_allocate_msg : 0;'
    wrapper = function(source, 'native_tracked_allocate_msg')
    assert 'if(!native_real_allocate_msg)__builtin_trap();' in wrapper
    assert wrapper.count('native_real_allocate_msg(id,message,size,count)') == 1
    assert wrapper.count('native_movie_format_allocated(id,message,result,count)') == 1
    assert wrapper.count('native_ou_crank_allocated(id,message,result,count)') == 1
    assert 'native_pin_peer_allocated' not in wrapper and 'native_crank_allocated' not in wrapper


def test_actual_main_shared_allocator_dlsym_binding_source():
    source = (HERE / 'menu-observe.c').read_text()
    initial, dynamic = movie_allocator_binding_source(source)
    assignments = [line.strip() for line in re.findall(
        r'(?m)^[ \t]*real_allocate_msg[ \t]*=[^;]+;', source)]
    assert assignments == [initial.strip(), dynamic.strip()]
    raw_assignments = [line.strip() for line in re.findall(
        r'(?m)^[ \t]*native_real_allocate_msg[ \t]*=[^;]+;', source)]
    assert raw_assignments == [
        'native_real_allocate_msg = real_dlsym((void *)-1, "osal_valloc_msg_wait");',
        'native_real_allocate_msg = symbol;',
    ]
    received = function(source, 'native_cp_state_received')
    assert ('const struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
            '            real_send_msg,real_msg_size,real_get_source,record};') in received
    assert 'functional_jpeg_codec_observe_received(id,*message,&io);' in received


def ou_main_source(source):
    """Extract actual Main resource36/guard/ticket/free/allocator code into owner mocks."""
    sent = function(source, 'osal_snd_msg')
    strict = sent.index('    if(cp_ee_controls_enabled && id==NATIVE_CP_EE_CONTROLS_SID)')
    begin = sent.rindex('    if(functional_camera_enabled && id==NATIVE_CP_EE_CONTROLS_SID && message && real_msg_size)', 0, strict)
    end = sent.index('    if(functional_camera_enabled && id==FUNCTIONAL_STARTUP_CONTROL_SID', strict)
    freed = function(source, 'osal_free_msg')
    free_begin = freed.index('    int ou_result;')
    free_end = freed.index('    int media_mount_trace=', free_begin)
    init_begin = source.index('    functional_camera_enabled=same_name(functional_profile,FCAM_PROFILE)')
    init_end = source.index('    if(functional_profile){', init_begin)
    declarations = '\n'.join(line for line in source.splitlines() if line.startswith('static ') and any(
        name in line for name in ('functional_cp_ou_crank_control_used,',
                                 'functional_cp_ou_crank_control_ticket_mutex[',
                                 '} functional_cp_ou_crank_control_ticket;')))
    assert len(declarations.splitlines()) == 3
    allocator = '\n'.join(line for line in source.splitlines() if line in (
        'static int (*real_allocate_msg)(unsigned int, void **, unsigned int, unsigned int);',
        'static int (*native_real_allocate_msg)(unsigned int, void **, unsigned int, unsigned int);'))
    assert len(allocator.splitlines()) == 2
    number_begin = source.index('static uint64_t native_ou_crank_u64(')
    number_end = source.index('static int functional_cp_ou_crank_control_predecessors_ready(', number_begin)
    ticket_begin = source.index('static int native_ou_crank_ticket_for(')
    ticket_end = source.index('static int native_functional_ou_crank_release(', ticket_begin)
    names = ('tracked_native_reserve_resources', 'functional_cp_ou_crank_control_reserve_resources',
             'functional_cp_crank_control_predecessors_ready', 'functional_cp_movie_format_predecessors_ready',
             'functional_cp_ou_crank_control_predecessors_ready', 'native_ou_crank_real_free',
             'native_functional_ou_crank_release', 'native_ou_crank_allocated', 'native_tracked_allocate_msg',
             'osal_valloc_msg_wait')
    helpers = {name: function(source, name) for name in names}
    replacements = {
        '/* ACTUAL_OU_DECLARATIONS */': declarations,
        '/* ACTUAL_OU_ALLOCATOR_DECLARATIONS */': allocator,
        '/* ACTUAL_OU_HELPERS */': (source[number_begin:number_end] + source[ticket_begin:ticket_end] +
                                    '\n'.join(helpers.values())),
        '/* ACTUAL_OU_ROUTE */': sent[begin:strict],
        '/* ACTUAL_OU_STRICT_ROUTE */': sent[strict:end],
        '/* ACTUAL_OU_FREE */': freed[free_begin:free_end],
        '/* ACTUAL_OU_INIT */': source[init_begin:init_end],
    }
    code = (HERE / 'test-main-ou-crank-wiring.c').read_text()
    provenance = ['Main SHA256: ' + hashlib.sha256(source.encode()).hexdigest()]
    for name, actual in {**helpers, **replacements}.items():
        provenance.append(name.strip('/* ') + ': ' + hashlib.sha256(actual.encode()).hexdigest())
    for marker, actual in replacements.items():
        assert code.count(marker) == 1 and actual, marker
        code = code.replace(marker, actual)
    return '/* ' + '\n * '.join(provenance) + ' */\n' + code


@pytest.fixture(scope='module', params=['strict', 'asan-ubsan'])
def ou_main_executable(tmp_path_factory, request):
    code = ou_main_source((HERE / 'menu-observe.c').read_text())
    directory = tmp_path_factory.mktemp('actual-main-ou-crank-' + request.param)
    path, binary = directory / 'actual.c', directory / 'actual'
    path.write_text(code)
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    built = subprocess.run(['cc', *flags, '-I', str(HERE), str(path), '-o', str(binary)],
                           capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('category,case', [
    *[('route', case) for case in [
        'cold', 'disabled', 'late', 'late-used-only', 'short', 'source', 'setup', 'bridge',
        'body', 'before', 'model', 'postvalidation', 'after', 'predecessor', 'reserve',
        'context-init-drift', 'context-reserve-drift', 'owner-unhandled', 'owner-error',
        'real-free-error', 'real-free-positive', 'postdispatch-retained', 'postdispatch-historical', 'postdispatch-pid']],
    *[('predecessor', case) for case in [
        'ready', 'bank-free-thread', 'bank-unfreed', 'crank-bank-transaction', 'movie-commit',
        'movie-complete', 'movie-generation', 'movie-crank-transaction', 'movie-bank-transaction',
        'movie-free-thread', 'movie-receive', 'movie-retained', 'mode-lease', 'strict-attempt',
        'strict-consumed', 'strict-free', 'strict-fault', 'settings-command', 'settings-cycle',
        'settings-generation', 'settings-seal', 'settings-config40', 'settings-request-free',
        'settings-reply-free', 'settings-free-thread', 'settings-receive', 'settings-state']],
    *[('ticket', case) for case in ['free', 'stale', 'duplicate', 'wrong-pid', 'mutex-error', 'free-error']],
    *[('allocation', case) for case in ['reuse', 'negative', 'positive', 'multi', 'null',
                                       'null-output', 'foreign', 'wrong-pid', 'public', 'borrowed']],
    *[('init', case) for case in ['local', 'failed', 'disabled']],
    ('fork', 'before-inherited-ticket-lock'),
])
def test_actual_main_ou_crank_wiring(ou_main_executable, category, case):
    result = subprocess.run([str(ou_main_executable), category, case],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{category}/{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main OU wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


@pytest.mark.parametrize('case,requester', [
    *[('busy', index) for index in range(36)],
    *[(case, 35) for case in ['fault', 'guard', 'guard-fault', 'retained', 'releasing',
                             'owned', 'wrong-pid', 'uninitialized']],
    *[('idle', index) for index in range(38)],
    ('self', 36), ('complete', 35), ('dmm', 36), ('resource-error', 36),
    ('invalid', -1), ('invalid', 38),
])
def test_actual_main_ou_resource36_and_other_endpoints(ou_main_executable, case, requester):
    result = subprocess.run([str(ou_main_executable), 'resource', case, str(requester)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}/{requester}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main OU wiring MOCK; Core/native AP/capture unverified\n'
    assert not result.stderr


def test_actual_main_ou_oneway_ticket_source_boundaries():
    source = (HERE / 'menu-observe.c').read_text()
    release = function(source, 'native_functional_ou_crank_release')
    assert 'native_ou_crank_ticket_for(destination,pointer,&ticket)' in release
    assert 'snapshot' not in release and 'receive' not in release
    freed = function(source, 'osal_free_msg')
    assert freed.index('native_functional_ou_crank_release') < freed.index('trace_media_mount_completion')
    received = function(source, 'native_cp_state_received')
    assert 'ou_crank' not in received
    observer = function(source, 'native_ou_crank_allocated')
    assert 'result || count!=1 || !message || !*message' in observer
    assert observer.index('ticket_pid!=') < observer.index('pthread_mutex_lock')
    assert 'snapshot' not in observer


