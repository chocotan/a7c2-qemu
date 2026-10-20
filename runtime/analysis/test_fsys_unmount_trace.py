"""Observe original Unmount only; no VM, real signals, devices or hotplug."""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <unistd.h>
static int unmount_calls, original_result, trace_opened, trace_closed, trace_written;
static unsigned char actual_drive;
static unsigned int actual_flags;
static char trace[512];
static int original_unmount(unsigned char drive,unsigned int flags){
 unmount_calls++;actual_drive=drive;actual_flags=flags;return original_result;
}
static void *lookup(void *handle,const char *name){
 (void)handle;assert(!strcmp(name,"Fsys_Unmount"));return original_unmount;
}
static void *fake_dlvsym(void *handle,const char *name,const char *version){
 (void)handle;assert(!strcmp(name,"dlsym"));assert(!strcmp(version,"GLIBC_2.17"));return lookup;
}
static int fake_open(const char *path,int flags,...){
 assert(!strcmp(path,"/dev/console") && flags==1);trace_opened++;return 91;
}
static long fake_write(int fd,const void *data,unsigned long bytes){
 assert(fd==91 && bytes<sizeof trace);memcpy(trace,data,bytes);trace[bytes]=0;
 trace_written++;return (long)bytes;
}
static int fake_close(int fd){assert(fd==91);trace_closed++;return 0;}
static int fake_fflush(void *stream){(void)stream;return 0;}
#define dlvsym fake_dlvsym
#define open fake_open
#define write fake_write
#define close fake_close
#define fflush fake_fflush
'''

MAIN = r'''
int main(int argc,char **argv){
 assert(argc==2);int scenario=atoi(argv[1]);
 unsetenv("A7C2_FILE_MEDIA_TEST");
 if(scenario==1 || scenario==2)setenv("A7C2_FILE_MEDIA_TEST","1",1);
 if(scenario==3)setenv("A7C2_FILE_MEDIA_TEST","10",1);
 original_result=scenario==2?-19:0;
 mounted_media_owner=1234;mounted_media_drive='A';
 unsigned char drive=scenario==4?255:'A';unsigned int flags=0xdeadbeefU;
 int result=Fsys_Unmount(drive,flags);
 assert(unmount_calls==1 && actual_drive==drive && actual_flags==flags);
 assert(result==original_result);
 assert(mounted_media_owner==1234 && mounted_media_drive=='A');
 assert(!busy && !cancel_pending && !previous);
 int enabled=scenario==1 || scenario==2;
 assert(trace_opened==enabled && trace_written==enabled && trace_closed==enabled);
 if(enabled){
  char expected[256];snprintf(expected,sizeof expected,
   "FSYS_FILE_TRACE op=Unmount path=- handle=41 flags=%#x result=%d hex=%#x\n",
   flags,original_result,(unsigned int)original_result);
  assert(!strcmp(trace,expected));
 }
 return 0;
}
'''


class UnmountTraceTests(unittest.TestCase):
    def test_original_arguments_result_and_optin_trace_without_state_changes(self):
        source = FIXTURE + '\n#include "file-media-config.c"\n' + MAIN
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'test-unmount'
            subprocess.run(['cc', '-x', 'c', '-', '-I', str(HERE), '-o', str(binary),
                            '-Wall', '-Wextra', '-Werror', '-pthread',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'],
                           input=source, text=True, capture_output=True, check=True)
            for scenario in range(5):
                with self.subTest(scenario=scenario):
                    result = subprocess.run([str(binary), str(scenario)], capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
