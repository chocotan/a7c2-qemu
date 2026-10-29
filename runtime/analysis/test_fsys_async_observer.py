from pathlib import Path
import os
import subprocess

HERE = Path(__file__).resolve().parent


def test_async_write_observer_is_explicit_passthrough_and_profile_gated():
    source = (HERE / 'file-media-config.c').read_text()
    assert 'int Fsys_WriteDirectFileAsyncV2(void *request)' in source
    assert 'original_fsys("Fsys_WriteDirectFileAsyncV2")' in source
    assert 'A7C2_FSYS_ASYNC_OBSERVE' in source
    assert 'request_fnv1a64' in source
    assert 'function(request)' in source
    assert 'unsigned char snapshot[0x508]' in source
    assert 'if(captured)async_write_trace(snapshot,rc)' in source
    assert 'async_write_trace(request,rc)' not in source  # no post-return dereference
    env = {k:v for k,v in os.environ.items() if not k.startswith(('A7C2_', 'MENU_'))}
    result = subprocess.run(['python3', str(HERE/'qemu-menu-probe.py')],
                            env=dict(env, A7C2_FSYS_ASYNC_OBSERVE='1'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'requires MENU_RM_FILE=1' in result.stderr


def test_compiled_async_passthrough_snapshot_lifetime_and_bounds(tmp_path):
    source = (HERE/'file-media-config.c').read_text()
    helper = source[source.index('static void async_write_trace('):source.index('/* Optional content observation')]
    fixture = r'''
#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static unsigned reads, logs, calls;
static void *expected;
static unsigned char *mapping;
static int invalidate;
static int fake_original(void *request){
 assert(request==expected && errno==31);calls++;
 if(invalidate)assert(!mprotect(mapping,4096,PROT_NONE));
 errno=47;return -17;
}
static void *original_fsys(const char *name){
 assert(!strcmp(name,"Fsys_WriteDirectFileAsyncV2"));errno=88;return fake_original;
}
static int test_open(const char *path,int flags){
 if(!strcmp(path,"/dev/console"))return 999;
 assert(!strcmp(path,"/proc/self/mem"));return open(path,flags);
}
static long test_pread(int fd,void *out,unsigned long count,long offset){
 reads++;assert(count==0x508);return pread(fd,out,count,offset);
}
static long test_write(int fd,const void *data,unsigned long count){
 assert(fd==999);assert(strstr(data,"FSYS_ASYNC_WRITE") && strstr(data,"areas=8"));
 assert(strstr(data,"path=A:/DCIM/TEST.JPG"));logs++;errno=77;return count;
}
static int test_close(int fd){if(fd==999)return 0;return close(fd);}
#define open test_open
#define pread test_pread
#define write test_write
#define close test_close
'''
    main = r'''
static void invoke(void *pointer){expected=pointer;errno=31;
 assert(Fsys_WriteDirectFileAsyncV2(pointer)==-17 && errno==47);
}
int main(void){
 mapping=mmap(0,8192,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 assert(mapping!=MAP_FAILED);
 memcpy(mapping,"A:/DCIM/TEST.JPG",16);unsigned int count=8;memcpy(mapping+0x4f0,&count,4);
 unsigned char before[0x508];memcpy(before,mapping,sizeof before);
 unsetenv("A7C2_FSYS_ASYNC_OBSERVE");invoke((void *)1);
 setenv("A7C2_FSYS_ASYNC_OBSERVE","yes",1);invoke(mapping);
 assert(!reads && !logs && !memcmp(before,mapping,sizeof before));
 setenv("A7C2_FSYS_ASYNC_OBSERVE","1",1);invoke(0);assert(!reads);
 invalidate=1;invoke(mapping);assert(reads==1 && logs==1);
 assert(!mprotect(mapping,4096,PROT_READ|PROT_WRITE));invalidate=0;
 assert(!memcmp(before,mapping,sizeof before));
 invoke((void *)1);assert(reads==2 && logs==1);
 assert(!munmap(mapping+4096,4096));invoke(mapping+4096-16);
 assert(reads==3 && logs==1); /* Partial request cannot be logged as valid. */
 for(int i=0;i<40;i++)invoke(mapping);
 assert(reads==32 && logs==30); /* No reads or logs after the explicit bound. */
 assert(calls==46);assert(!munmap(mapping,4096));return 0;
}
'''
    path=tmp_path/'async.c';path.write_text(fixture+helper+main)
    binary=tmp_path/'async'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer','-no-pie','-I',str(HERE),str(path),
                    str(HERE/'fsys-write-trace.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_mpr_callback_wrappers_preserve_arguments_errno_and_freed_input(tmp_path):
    source = (HERE/'file-media-config.c').read_text()
    helpers = source[source.index('static void async_write_trace('):source.index('/* Optional content observation')]
    fixture = r'''
#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static void *expected_result, *expected_work;
static unsigned callbacks, workers;
static int fake_submit(void *request) { (void)request; assert(0); return -1; }
static void fake_callback(void *cookie, int status, const void *result) {
    assert(cookie == (void *)0x1234 && status == -17 && result == expected_result && errno == 31);
    callbacks++; errno = 47;
}
static void fake_finished(void *work) {
    assert(work == expected_work && errno == 31); workers++;
    assert(!munmap(work, 4096)); errno = 53;
}
static void *original_fsys(const char *name) {
    errno = 88;
    if (!strcmp(name, MPR_FSYS_CALLBACK_SYMBOL)) return fake_callback;
    if (!strcmp(name, MPR_WRITE_FINISHED_SYMBOL)) return fake_finished;
    assert(!strcmp(name, "Fsys_WriteDirectFileAsyncV2")); return fake_submit;
}
'''
    main = r'''
int main(void) {
    unsigned char result[FSYS_WRITE_RESULT_BYTES] = {0}; expected_result = result;
    setenv("A7C2_FSYS_ASYNC_OBSERVE", "1", 1); errno = 31;
    native_mpr_fsys_callback((void *)0x1234, -17, result);
    assert(callbacks == 1 && errno == 47);
    unsigned char *work = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(work != MAP_FAILED); expected_work = work;
    unsigned long long cookie = 0x1234; memcpy(work, &cookie, 8);
    errno = 31; native_mpr_write_finished(work);
    assert(workers == 1 && errno == 53);
    return 0;
}
'''
    path = tmp_path/'callbacks.c'; path.write_text(fixture + helpers + main)
    binary = tmp_path/'callbacks'
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-no-pie', '-I', str(HERE), str(path),
                    str(HERE/'fsys-write-trace.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
