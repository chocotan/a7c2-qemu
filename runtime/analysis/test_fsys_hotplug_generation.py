"""Original call entry token survives a delayed completion; host ABI fixture."""
from pathlib import Path
import os
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
FIXTURE=r'''
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
static unsigned long long generation=7;
static unsigned mount_mask=1,observed,unmounts,mounts;
static unsigned long long get_generation(void){return generation;}
static unsigned get_mask(void){errno=63;return mount_mask;}
static int original_unmount(unsigned char drive,unsigned flags){
 assert(drive=='A' && flags==0x12);unmounts++;generation=9;mount_mask=0;errno=39;return 0;
}
static int original_mount(const char *path,unsigned flags,char *drive,const void *extra){
 assert(!strcmp(path,"/nondev/rm2") && flags==0x100 && !extra);
 mounts++;generation=12;*drive='B';mount_mask=2;errno=40;return 0;
}
static void observation(unsigned long long token,unsigned kind,unsigned drive,int rc,
                        unsigned before,unsigned after,int validated){
 assert(rc==0);observed++;
 if(kind==1)assert(token==7 && generation==9 && drive=='A' && before==1 && !after && !validated);
 else assert(token==9 && generation==12 && drive=='B' && !before && after==2 && validated);
}
static void *lookup(void *handle,const char *name){
 (void)handle;
 if(!strcmp(name,"native_rm_file_media_generation"))return get_generation;
 if(!strcmp(name,"native_rm_file_fsys_observed"))return observation;
 if(!strcmp(name,"Fsys_GetMountDrives"))return get_mask;
 if(!strcmp(name,"Fsys_Unmount"))return original_unmount;
 if(!strcmp(name,"Fsys_Mount"))return original_mount;
 assert(0);return 0;
}
static void *fake_dlvsym(void *handle,const char *name,const char *version){
 (void)handle;assert(!strcmp(name,"dlsym") && !strcmp(version,"GLIBC_2.17"));return lookup;
}
#define dlvsym fake_dlvsym
#include "file-media-config.c"
int main(void){
 assert(!setenv("A7C2_SD_HOTPLUG","1",1));unsetenv("A7C2_FILE_MEDIA_TEST");
 mounted_media_owner=getpid();mounted_media_drive='A';
 assert(!Fsys_Unmount('A',0x12) && observed==1 && unmounts==1);
 assert(!mounted_media_drive && retired_media_drive=='A' && errno==39);
 char drive=0;assert(!Fsys_Mount("/nondev/rm2",0x100,&drive,0));
 assert(observed==2 && mounts==1 && drive=='B' && mounted_media_drive=='B' && !retired_media_drive && errno==40);
 return 0;
}
'''


def test_generation_is_captured_before_original_mount_and_unmount():
    with tempfile.TemporaryDirectory(prefix='fsys-generation-',dir='/var/tmp') as tmp:
        binary=Path(tmp)/'generation'
        env={**os.environ,'TMPDIR':tmp,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1',
             'UBSAN_OPTIONS':'halt_on_error=1'}
        subprocess.run(['cc','-x','c','-',str(HERE/'fsys-write-trace.c'),'-I',str(HERE),'-o',str(binary),
                        '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie'],
                       input=FIXTURE,text=True,capture_output=True,check=True,env=env)
        subprocess.run([str(binary)],check=True,timeout=10,env=env)
