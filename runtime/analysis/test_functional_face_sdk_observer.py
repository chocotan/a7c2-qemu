# SPDX-License-Identifier: MIT
"""Execute actual SDK passive log helper and actual alloc/sync forward tails."""
import os
from pathlib import Path
import subprocess

import pytest
from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def sdk_observer_binary(tmp_path_factory, request):
    source = (HERE / "menu-observe.c").read_text()
    helper = function(source, "native_face_sdk_observation")
    alloc = function(source, "osal_valloc_msg_wait")
    alloc = alloc[alloc.index("    int result=real_allocate_msg(id, message, size, count),saved_errno="):alloc.rfind("}")]
    sync = function(source, "osal_snd_sync_msg")
    enter = sync[sync.index("    if(functional_camera_enabled && id==0x02820746u"):sync.index('    trace_media_mount_sync("FULL_MEDIA_MOUNT_ENTER')]
    returned = sync[sync.index("    int result = real_send_sync(id, message);"):sync.index('    trace_media_mount_sync("FULL_MEDIA_MOUNT_RETURN')]
    body = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int functional_camera_enabled=1,allocation_rc,sync_rc,allocations,syncs,records;
static void *fixture_caller;static unsigned int stages[5];static char last[1000];
static long fixture_syscall(long n){assert(n==178);return 777;}
#define syscall fixture_syscall
static int dladdr_api(const void *p,Dl_info *d){assert(p==fixture_caller);d->dli_fbase=(void *)(uintptr_t)0x100000;errno=EDOM;return 1;}
static int (*real_dladdr)(const void *,Dl_info *)=dladdr_api;
static void record(const char *prefix,const char *text){
 assert(!strcmp(prefix,"FUNCTIONAL_FACE_DMM_SDK_OBSERVATION ") && strlen(text)<sizeof last);
 unsigned int stage=0;assert(sscanf(strstr(text,"stage="),"stage=%u",&stage)==1 && stage>=1 && stage<=4);
 stages[stage]++;records++;strcpy(last,text);
 assert(strstr(text,"observation_only=1") && strstr(text,"source_memory_ready=0") && strstr(text,"native_pin=0"));
 assert(strstr(text,"physical_verified=0") && strstr(text,"capture_verified=0"));
 if(stage==2)assert(strstr(text,"actual_rc_defined=0") && strstr(text,"kernel_result_defined=0"));
 if(stage==1 || stage==4)assert(strstr(text,"sampled=0") && strstr(text,"kernel_result_defined=0"));
 errno=ERANGE;
}
static int real_allocate_msg(unsigned int id,void **out,unsigned int bytes,unsigned int count){
 (void)id;assert(bytes==48 && count==1);allocations++;
 if(!allocation_rc){*out=malloc(bytes);assert(*out);memset(*out,0xa7,bytes);}errno=EAGAIN;return allocation_rc;
}
static unsigned int size_api(void *p){assert(p);errno=EBADF;return 48;}
static unsigned int (*real_msg_size)(void *)=size_api;
static int real_send_sync(unsigned int id,void *p){
 (void)id;assert(p);syncs++;if(!sync_rc){unsigned int result=0x11223344;memcpy((char *)p+40,&result,4);}errno=EAGAIN;return sync_rc;
}
/* ACTUAL_HELPER */
static int actual_allocate(unsigned int id,void **message,unsigned int size,unsigned int count){
/* ACTUAL_ALLOC */
}
static int actual_sync(unsigned int id,void *message){
/* ACTUAL_ENTER */
/* ACTUAL_RETURN */
 return result;
}
int main(int argc,char **argv){
 assert(argc==2);const char *mode=argv[1];unsigned int id=0x02820746u;int active=1;
 if(!strcmp(mode,"disabled")){functional_camera_enabled=0;active=0;}
 if(!strcmp(mode,"other")){id=0x02820745u;active=0;}
 if(!strcmp(mode,"allocfail"))allocation_rc=-31;
 if(!strcmp(mode,"syncfail"))sync_rc=-71;
 void *message=(void *)(uintptr_t)0x1234;fixture_caller=(void *)(uintptr_t)0x1009b8;
 assert(actual_allocate(id,&message,48,1)==allocation_rc && allocations==1 && errno==EAGAIN);
 assert(records==active);
 if(allocation_rc){assert(strstr(last,"actual_rc=-31") && strstr(last,"sampled=0") && strstr(last,"kernel_result_defined=0"));}
 else{
  unsigned char before[40];memcpy(before,message,40);fixture_caller=(void *)(uintptr_t)0x1009ec;
  assert(actual_sync(id,message)==sync_rc && syncs==1 && errno==EAGAIN);
  assert(!memcmp(before,message,40));
  if(active){assert(stages[1]==1 && stages[2]==1 && stages[3]==1);
   assert(strstr(last,"actual_rc_defined=1"));assert(strstr(last,sync_rc?"kernel_result_defined=0":"kernel_result_defined=1"));}
  uintptr_t old=(uintptr_t)message;free(message);fixture_caller=(void *)(uintptr_t)0x100a04;errno=EAGAIN;
  native_face_sdk_observation(4,id,(void *)old,0,0,fixture_caller);
  assert(errno==EAGAIN);if(active){assert(stages[4]==1 && strstr(last,"sampled=0") && strstr(last,"kernel_result_defined=0"));}
 }
 printf("SDK_OBSERVER_HOSTTEST_PASS mode=%s originals_preserved=1 no_freed_dereference=1 native_pin=0 capture_verified=0\n",mode);return 0;
}
'''
    replacements = {"/* ACTUAL_HELPER */": helper, "/* ACTUAL_ALLOC */": alloc,
                    "/* ACTUAL_ENTER */": enter, "/* ACTUAL_RETURN */": returned}
    for marker, value in replacements.items():
        assert body.count(marker) == 1
        body = body.replace(marker, value.replace("__builtin_return_address(0)", "fixture_caller"))
    work = tmp_path_factory.mktemp("actual-sdk-observer")
    path, binary = work / "actual.c", work / "actual"
    path.write_text(body)
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    if request.param:
        flags += ["-fsanitize=address,undefined", "-fno-pie", "-no-pie", "-fno-omit-frame-pointer"]
    built = subprocess.run(["cc", *flags, str(path), "-o", str(binary)], capture_output=True, text=True, timeout=60)
    assert built.returncode == 0, built.stdout + built.stderr
    return binary


@pytest.mark.parametrize("mode", ["success", "allocfail", "syncfail", "disabled", "other"])
def test_actual_sdk_original_results_and_passive_fields(sdk_observer_binary, mode):
    result = subprocess.run([str(sdk_observer_binary), mode], capture_output=True, text=True, timeout=20,
                            env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                                     UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"SDK_OBSERVER_HOSTTEST_PASS mode={mode}" in result.stdout
