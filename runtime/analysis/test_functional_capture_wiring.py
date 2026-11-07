"""Execute actual main capture routing/guard; this host fixture is not a Sony run."""
from pathlib import Path
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def capture_wiring_binary(tmp_path_factory):
    source = (HERE / 'menu-observe.c').read_text()
    sent = function(source, 'osal_snd_msg')
    sent = sent[:sent.index('    if(cp302c_no_transition_enabled')]
    sent += '    return 919;\n}\n'
    snippets = '\n'.join(function(source, name) for name in (
        'functional_capture_reserve_resources', 'functional_capture_predecessors_ready'))
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "functional-capture.h"
#include "device-models/functional-camera-control.h"
#include "device-models/functional-vdf-path.h"
#include "device-models/functional-still-format.h"
static int functional_camera_enabled=1,functional_camera_setup_error,prior_ready=1,selected,position;
static unsigned audits,reserves,unlocks;
static uint8_t message[16];
static struct native_functional_camera_control_snapshot control;
static struct functional_vdf_path_snapshot path;
static struct functional_still_format_snapshot format;
static struct full_imaging_snapshot imaging;
static int tracked_native_reserve_resources(int id){assert(id==32);++reserves;return 0;}
static void full_vef_resources_unlock(void){++unlocks;}
static int cp302c_no_transition_predecessors_ready(void){return prior_ready;}
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *out){*out=control;}
void functional_vdf_path_snapshot(struct functional_vdf_path_snapshot *out){*out=path;}
void functional_still_format_snapshot(struct functional_still_format_snapshot *out){*out=format;}
void full_imaging_snapshot(struct full_imaging_snapshot *out){*out=imaging;}
static int (*real_allocate_msg)(unsigned,void **,unsigned,unsigned);
static int (*real_free_msg)(unsigned,void *);
static void (*real_set_source)(void *,unsigned);
static int (*real_send_msg)(unsigned,void *);
static unsigned (*real_msg_size)(void *),(*real_get_source)(void *);
static void record(const char *tag,const char *text){(void)tag;(void)text;assert(0);}
static void audit_cp_background_input(unsigned id,void *p,const char *kind,void *caller){assert(id==27 && p==message && !strcmp(kind,"async") && caller);++audits;}
static void check_io(const struct full_imaging_io *io){assert(io && io->allocate==real_allocate_msg && io->release==real_free_msg && io->send==real_send_msg && io->set_source==real_set_source && io->size==real_msg_size && io->source==real_get_source && io->record==record);}
int functional_capture_terminal_send(unsigned id,void *p,const struct full_imaging_io *io,int *rc){assert(id==27 && p==message && rc && position++==0);check_io(io);if(selected==1){*rc=-17;return 1;}return 0;}
int functional_capture_dmm(unsigned id,void *p,const struct full_imaging_io *io,uintptr_t caller,int *rc){assert(id==27 && p==message && caller && rc && position++==1);check_io(io);if(selected==2){*rc=-5;return 1;}return 0;}
int functional_capture_dispatch(unsigned id,void *p,const struct full_imaging_io *io,const struct native_cp_state_publication_guard *guard,int *rc){
 assert(id==27 && p==message && rc && position++==2);check_io(io);assert(guard && guard->release==full_vef_resources_unlock);
 assert(!guard->reserve() && guard->predecessor_ready());guard->release();if(selected==3){*rc=0;return 1;}return 0;
}
int full_imaging_functional_dispatch(unsigned id,void *p,const struct full_imaging_io *io,int *rc){
 assert(id==27 && p==message && rc && position++==3);check_io(io);if(selected==19){*rc=0;return 1;}return 0;
}
''' + snippets + '\n' + sent + r'''
static void defaults(void){
 control.owner_pid=path.owner_pid=format.owner_pid=getpid();
 control.initialized=control.model_initialized=control.start_complete=control.mode1_complete=control.mode_complete=control.notification_ap_consumed=1;control.model_instance=31;
 path.initialized=path.model_complete=path.ap_consumed=1;path.model_instance=31;
 format.initialized=format.state_valid=format.model_complete=format.ap_consumed=format.completed_cycles=1;format.model_instance=31;
 imaging.functional_enabled=1;imaging.functional_owner_pid=getpid();
 imaging.requested=imaging.effective=FULL_IMAGING_POWER_ON_INHIBIT;
}
int main(int argc,char **argv){assert(argc==2);int mode=atoi(argv[1]);defaults();
 if(mode<5 || mode==19){selected=mode;functional_camera_enabled=mode!=4;uint8_t saved[16];memcpy(saved,message,16);
  int result=osal_snd_msg(27,message);assert(result==(mode==1?-17:mode==2?-5:mode==3 || mode==19?0:919));
  assert(audits==1 && !memcmp(saved,message,16) && position==(mode==4?0:mode==1?1:mode==2?2:mode==3?3:4));
  assert(reserves==(mode==0 || mode==3 || mode==19) && unlocks==reserves);
 }else{
  switch(mode){
   case 5:functional_camera_setup_error=-5;break;
   case 6:prior_ready=0;break;
   case 7:control.owner_pid++;break;
   case 8:control.notification_ap_consumed=0;break;
   case 9:control.busy=1;break;
   case 10:path.model_instance++;break;
   case 11:path.faults=1;break;
   case 12:format.state_valid=0;break;
   case 13:format.ap_consumed=0;break;
   case 14:format.retained=1;break;
   case 15:imaging.functional_enabled=0;break;
   case 16:imaging.effective=1;break;
   case 17:imaging.suppressed=1;break;
   case 18:imaging.faults=1;break;
   case 20:imaging.functional_owner_pid++;break;
   case 21:imaging.functional_busy=1;break;
   case 22:imaging.live_replies=1;break;
   case 23:control.mode0_requests=1;control.mode_complete=0;break;
   case 24:control.mode1_complete=0;break;
   default:assert(0);
  }
  assert(!functional_capture_predecessors_ready() && !reserves && !unlocks);
 }
 puts("PASS actual main capture boundary/guard HOST_ONLY original_AP=0 capture_verified=0");return 0;
}
'''
    work = tmp_path_factory.mktemp('capture-main')
    (work / 'actual.c').write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-pie', '-no-pie', '-I', str(HERE),
                            str(work / 'actual.c'), '-o', str(work / 'actual')],
                           capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return work / 'actual'


@pytest.mark.parametrize('mode', range(25))
def test_actual_main_capture_routing_and_existing_gate(capture_wiring_binary, mode):
    ran = subprocess.run([str(capture_wiring_binary), str(mode)], capture_output=True,
                         text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert 'PASS actual main capture boundary/guard HOST_ONLY' in ran.stdout


def test_linked_imaging_provider_retains_cold_capture_inhibit(tmp_path):
    source = tmp_path / 'imaging-gate.c'
    source.write_text(r'''
#include <assert.h>
#include "device-models/imaging-device.h"
int main(void){
 struct full_imaging_snapshot before={0},after={0};
 full_imaging_snapshot(&before);
 assert(before.requested==FULL_IMAGING_POWER_ON_INHIBIT && !before.suppressed &&
        before.effective==FULL_IMAGING_POWER_ON_INHIBIT && !before.active_capture && !before.faults);
 assert(full_imaging_capture_begin()==-16);
 full_imaging_snapshot(&after);
 assert(after.requested==before.requested && after.effective==before.effective &&
        !after.active_capture && !after.faults);
 return 0;
}
''')
    binary = tmp_path / 'imaging-gate'
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-pie', '-no-pie', '-pthread',
                            '-I', str(HERE), str(source), str(HERE / 'device-models/imaging-device.c'),
                            '-o', str(binary)], capture_output=True, text=True, timeout=30)
    assert built.returncode == 0, built.stdout + built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert not ran.stdout and not ran.stderr


@pytest.mark.parametrize('record', [
    b'OBS FUNCTIONAL_CAMERA_CAPTURE operation=natural-request-owned rc=0 job=1\n',
    b'OBS FUNCTIONAL_CAMERA_CAPTURE operation=notifications-consumed-unsaved rc=0 job=1\n',
    b'OBS FUNCTIONAL_CAMERA_CAPTURE operation=fault-retained rc=-5 job=1\n',
    b'OBS FUNCTIONAL_CAPTURE operation=notifications-queued-unsaved rc=0\n',
    b'OBS FUNCTIONAL_CAMERA_CAPTURE',
])
def test_unsaved_capture_owner_blocks_host_teardown(tmp_path, record):
    from functional_camera_runner import require_capture_closed
    (tmp_path / 'console.log').write_bytes(record)
    with pytest.raises(ValueError, match='Natural (?:still capture owner is active or unsaved|capture incomplete/duplicate fields)'):
        require_capture_closed(tmp_path)
