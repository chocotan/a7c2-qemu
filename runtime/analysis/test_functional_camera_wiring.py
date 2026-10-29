"""Execute the actual functional application setup and lazy MPR binding boundaries."""
from pathlib import Path
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


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
static int functional_camera_enabled,functional_camera_setup_error,memory_result,memory_calls,jpeg_calls,jpeg_result;
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
  assert(functional_camera_enabled && functional_camera_setup_error==-EIO && memory_calls==1 && !jpeg_calls);
  assert(functional_mpr_prepare()==-EIO && !owner_calls && !loader_calls && !bind_calls);
 }else if(!strcmp(argv[1],"jpeg-setup-failure")){
  functional_camera_enabled=1;jpeg_result=-ENOSYS;application_setup();
  assert(functional_camera_enabled && functional_camera_setup_error==-ENOSYS && memory_calls==1 && jpeg_calls==1);
  assert(functional_mpr_prepare()==-ENOSYS && !owner_calls && !loader_calls && !bind_calls);
 }else if(!strcmp(argv[1],"default-off")){
  application_setup();assert(!memory_calls && !jpeg_calls && !functional_camera_setup_error);
 }else if(!strcmp(argv[1],"unready")){
  model_ready=0;assert(functional_mpr_prepare()==-ENODATA && !owner_calls && !loader_calls);
 }else if(!strcmp(argv[1],"success")){
  functional_camera_enabled=1;application_setup();assert(memory_calls==1 && jpeg_calls==1 && !functional_camera_setup_error);
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


@pytest.mark.parametrize('case', ['setup-failure', 'jpeg-setup-failure', 'default-off', 'unready', 'success',
                                 'owner-failure', 'symbol-mismatch'])
def test_actual_functional_setup_and_binding(executable, case):
    result = subprocess.run([str(executable), case], check=True, capture_output=True, text=True, timeout=5)
    assert result.stdout.endswith('PASS actual functional application/lazy binding boundary\n')
