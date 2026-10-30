"""Execute the actual generic free tail: observe only after native free, preserve rc/errno."""
from pathlib import Path
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='module')
def jpeg_free_binary(tmp_path_factory):
    source = function((HERE / 'menu-observe.c').read_text(), 'osal_free_msg')
    tail = source[source.index('    int result=real_free_msg(id,message),saved_errno='):source.rfind('}')]
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "functional-jpeg-codec.h"
#include "functional-face-ap-observer.h"
static _Thread_local struct functional_face_ap_observer functional_face_ap_state;
static void functional_face_ap_record_event(enum functional_face_ap_event event,const struct functional_face_ap_observer *s){
 (void)event;(void)s;assert(!"AP observer is inactive in this JPEG-only fixture");
}
static void native_face_sdk_observation(unsigned int stage,unsigned int id,void *message,unsigned int bytes,int result,void *caller){
 (void)stage;(void)id;(void)message;(void)bytes;(void)result;(void)caller;assert(!"SDK trace is inactive in this JPEG-only fixture");
}
static int functional_camera_enabled,native_calls,observed_calls,trace_calls;
static int native_rc,observer_rc,actually_freed;
static unsigned int saved_id;
static uintptr_t saved_pointer;
static long fixture_syscall(long number,...){assert(number==178);return 777;}
#define syscall fixture_syscall
static int real_free_msg(unsigned int id,void *message){
 assert(id==saved_id && (uintptr_t)message==saved_pointer && !native_calls);
 native_calls++;
 if(!native_rc){free(message);actually_freed=1;}
 errno=EAGAIN;return native_rc;
}
int functional_jpeg_codec_observe_freed(unsigned int id,void *pointer,int result){
 assert(native_calls==1 && !observed_calls && id==saved_id && (uintptr_t)pointer==saved_pointer);
 assert(result==native_rc && actually_freed==!native_rc);
 observed_calls++;errno=EDOM;return observer_rc;
}
static void record(const char *tag,const char *text){
 assert(!strcmp(tag,"FULL_MEDIA_MOUNT_FREE_RETURN ") && strstr(text,"result=") && native_calls==1);
 assert(observed_calls==functional_camera_enabled);trace_calls++;errno=ERANGE;
}
static int actual_generic_tail(unsigned int id,void *message,int media_mount_trace){
''' + tail + r'''
}
int main(int argc,char **argv){
 assert(argc==6);functional_camera_enabled=atoi(argv[1]);native_rc=atoi(argv[2]);observer_rc=atoi(argv[3]);
 int tracing=atoi(argv[4]),null_pointer=atoi(argv[5]);
 void *pointer=null_pointer?NULL:malloc(17);assert(pointer || null_pointer);
 saved_pointer=(uintptr_t)pointer;saved_id=0x81cf64ab;errno=EINTR;
 assert(actual_generic_tail(saved_id,pointer,tracing)==native_rc);
 assert(errno==EAGAIN && native_calls==1 && observed_calls==functional_camera_enabled && trace_calls==tracing);
 if(native_rc)free(pointer);
 puts("actual native-free result/errno/order preserved");return 0;
}
'''
    work = tmp_path_factory.mktemp('actual-jpeg-free')
    path, binary = work / 'actual.c', work / 'actual'
    path.write_text(code)
    built = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                            '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                            '-I', str(HERE), str(path), str(HERE / 'functional-face-ap-observer.c'),
                            '-o', str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize('enabled,result,observed,trace,null', [
    (0, 0, 1, 0, 0), (0, -5, 1, 1, 0),
    (1, 0, 1, 0, 0), (1, 0, -71, 1, 0),
    (1, -5, 1, 0, 0), (1, -5, -71, 1, 0),
    (1, 0, 0, 1, 1), (0, -22, 1, 0, 1),
])
def test_actual_native_free_observer_keeps_result_errno_and_order(jpeg_free_binary, enabled, result, observed, trace, null):
    ran = subprocess.run([str(jpeg_free_binary), *map(str, (enabled, result, observed, trace, null))],
                         capture_output=True, text=True, timeout=10)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert ran.stdout.strip() == 'actual native-free result/errno/order preserved'
