#!/usr/bin/env python3
"""Compile real adapter callbacks with small host Fsys providers; no VM."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1] / 'analysis/scratch/p1-original-update-resources-20261106/update-build-v3/root'

C = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
static int calls, result=3, init_calls, set_calls;
static unsigned parameter=1;
static char receipt[1024];
static int provider_mount(const char *p,unsigned f,char *d,const void *x) {
    assert(!strcmp(p,"/dev/mmca") && f==3 && !x);*d='A';errno=EACCES;return -9;
}
static int provider_open(const char *p,unsigned long long *h,unsigned f) {
    (void)p;assert(f==3);*h=1;errno=EAGAIN;return 0;
}
static int provider_read(unsigned long long h,void *b,int n) {
    assert(h==1);calls++;if(result>0 && result<=n)memset(b,'x',(size_t)result);
    errno=EINTR;return result;
}
static int provider_seek(unsigned long long h,long long o,unsigned w,void *p) {
    (void)h;(void)o;(void)w;if(p)*(unsigned long long *)p=9;errno=ERANGE;return 0;
}
static int provider_close(unsigned long long h) {(void)h;errno=EIO;return -7;}
static void provider_init(void){init_calls++;parameter=1;errno=EADDRNOTAVAIL;}
static unsigned provider_get(int id){assert(id==0x69 || id==0xf9);return id==0x69?parameter:0;}
static void provider_set(int id,unsigned value){assert(init_calls && id==0x69 && !value);set_calls++;parameter=value;}
static void *lookup(void *h,const char *n) {
    (void)h;
    if(!strcmp(n,"Fsys_Mount"))return provider_mount;
    if(!strcmp(n,"Fsys_Open"))return provider_open;
    if(!strcmp(n,"Fsys_Read"))return provider_read;
    if(!strcmp(n,"Fsys_Seek"))return provider_seek;
    if(!strcmp(n,"Fsys_Close"))return provider_close;
    if(!strcmp(n,"mcmn_param_init"))return provider_init;
    if(!strcmp(n,"mcmn_param_getul"))return provider_get;
    if(!strcmp(n,"mcmn_param_setul"))return provider_set;
    abort();
}
static void *fake_dlvsym(void *h,const char *n,const char *v){(void)h;(void)n;(void)v;return lookup;}
static int fake_open(const char *p,int f,...) {return !strcmp(p,"/dev/console")?999:open(p,f,0600);}
static long fake_write(int fd,const void *data,unsigned long n){
    if(fd!=999)return write(fd,data,n);
    assert(n<sizeof receipt);memcpy(receipt,data,n);receipt[n]=0;errno=ENOSPC;return (long)n;
}
static int fake_close(int fd){return fd==999?0:close(fd);}
static int fake_fflush(void *p){(void)p;return 0;}
struct media_dl_info;
static int fake_dladdr(const void *,struct media_dl_info *);
#define dlvsym fake_dlvsym
#define dladdr fake_dladdr
#define open fake_open
#define write fake_write
#define close fake_close
#define fflush fake_fflush
#include "file-media-config.c"
static void *image_base;
static const char *image_path;
static int fake_dladdr(const void *p,struct media_dl_info *info){
    if(!image_base || p!=(char *)image_base+0x418b4)return 0;
    *info=(struct media_dl_info){.name=image_path,.base=image_base};return 1;
}
__attribute__((noinline)) static int body_read(void *buffer,int requested){
    p1_common_base=(void *)((unsigned long)body_read-0x8f2c);
    p1_fsys_base=(void *)((unsigned long)provider_read-0x2edc0);
    volatile int rc=Fsys_Read(1,buffer,requested);return rc;
}
__attribute__((noinline)) static int body_seek(long long offset,void *output){
    p1_common_base=(void *)((unsigned long)body_seek-0x8fe4);
    p1_fsys_base=(void *)((unsigned long)provider_seek-0x2f8b0);
    volatile int rc=Fsys_Seek(1,offset,0,output);return rc;
}
int main(int argc,char **argv){
    assert(!setenv("A7C2_FILE_MEDIA_TEST","1",1));
    assert(!observed_path("A:/BODYDATA.DAT"));
    char drive=0;assert(Fsys_Mount("/dev/mmca",3,&drive,0)==-9 && errno==EACCES);
    assert(strstr(receipt,"op=Mount") && strstr(receipt,"result=-9"));
    mcmn_param_init();assert(init_calls==1 && set_calls==1 && !parameter && errno==EADDRNOTAVAIL);
    unsetenv("A7C2_FILE_MEDIA_TEST");mcmn_param_init();assert(init_calls==2 && set_calls==1 && errno==EADDRNOTAVAIL);
    assert(!setenv("A7C2_FILE_MEDIA_TEST","1",1));
    assert(!setenv("A7C2_P1_FILE_MEDIA_PROFILE","original-sd-v1",1));
    assert(!observed_path("A:/BODYDATA.DAT"));
    pid_t child=fork();assert(child>=0);
    if(!child){mcmn_param_init();_exit(99);}
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==126);
    /* Host-only state fixture: production activation requires all five original hashes. */
    p1_body_owner=getpid();assert(observed_path("A:/BODYDATA.DAT")==3);
    assert(!observed_path("/image_mmca") && !observed_path("A:/BODYDATA.DAT.extra"));
    assert(!observed_path("A:/dir/BODYDATA.DAT") && !observed_path("a:/BODYDATA.DAT"));
    read_opened(1,3);char bytes[70000];receipt[0]=0;
    assert(body_read(bytes,10)==3 && errno==EINTR && calls==1);
    assert(strstr(receipt,"actual=3 hashed=3 known=1 actor=1"));
    assert(strstr(receipt,"sha256=cd2eb0837c9b4c962c22d2ff8b5441b7b45805887f051d39bf133b583baf6860"));
    assert(body_read(bytes,10)==3 && strstr(receipt,"offset=3 "));
    unsigned long long position=0;
    assert(!body_seek(12,&position) && position==9 && errno==ERANGE);
    assert(body_read(bytes,10)==3 && strstr(receipt,"offset=9 "));
    assert(!body_seek(12,0));
    assert(body_read(bytes,10)==3 && strstr(receipt,"known=0 "));
    assert(!body_seek(0,0));
    assert(body_read(bytes,10)==3 && strstr(receipt,"offset=0 "));
    result=-9;assert(body_read(0,10)==-9 && strstr(receipt,"hashed=0 "));
    result=3;assert(body_read(bytes,10)==3 && strstr(receipt,"known=0 "));
    /* Absolute seek restores known state; an unassociated seek remains unknown. */
    struct read_token t=read_begin(1);read_end(t,1,0,0,0);
    assert(body_read(bytes,10)==3 && strstr(receipt,"offset=0 "));
    result=11;assert(body_read(bytes,10)==11 && strstr(receipt,"hashed=0 "));
    t=read_begin(1);read_end(t,1,0,0,0);result=70000;
    assert(body_read(bytes,70000)==70000 && strstr(receipt,"actual=70000 hashed=65536 "));
    result=3;assert(Fsys_Close(1)==-7 && errno==EIO);receipt[0]=0;
    assert(body_read(bytes,10)==3 && !receipt[0]);
    read_opened(1,3);assert(read_begin(1).generation>1);
    struct sha hash;char digest[65];start(&hash);update(&hash,(const u8 *)"abc",3);finish(&hash,digest);
    assert(!strcmp(digest,"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    if(argc==2){
        image_path=argv[1];FILE *f=fopen(image_path,"rb");assert(f);
        image_base=malloc(488280);assert(image_base && fread(image_base,1,488280,f)==488280);fclose(f);
        assert(p1_symbol((char *)image_base+0x418b4,0x418b4,488280,
          "efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec",564,
          "0565daadc6a5ac9a77e806fbeeed26dce4b29006be92182369c758693d465288",0));
        ((u8 *)image_base)[0x418b4]^=1;
        assert(!p1_symbol((char *)image_base+0x418b4,0x418b4,488280,
          "efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec",564,
          "0565daadc6a5ac9a77e806fbeeed26dce4b29006be92182369c758693d465288",0));
        free(image_base);
    }
    return 0;
}
'''


@unittest.skipUnless(shutil.which('gcc'), 'requires a host C compiler')
class Callbacks(unittest.TestCase):
    def test_real_callbacks_and_identity_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'callbacks.c'
            source.write_text(C)
            executable = Path(directory) / 'callbacks'
            subprocess.run(['gcc', '-O0', '-Wall', '-Wextra', '-Werror', '-pthread', '-I', str(HERE),
                            str(source), '-ldl', '-o', str(executable)], check=True, capture_output=True)
            arguments = [str(executable)]
            if ROOT.exists():
                arguments.append(str(ROOT / 'usr/lib/libInfraMediaCommon.so'))
            subprocess.run(arguments, check=True, capture_output=True, timeout=10)

    def test_existing_read_and_flush_callbacks_stay_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('read', 'flush'):
                executable = Path(directory) / name
                subprocess.run(['gcc', '-O0', '-Wall', '-Wextra', '-Werror', '-pthread',
                                str(HERE / f'test-file-media-{name}.c'), '-ldl', '-o', str(executable)],
                               check=True, capture_output=True)
                if name == 'read':
                    subprocess.run([str(executable)], check=True, capture_output=True, timeout=10)
                else:
                    for mode in range(6):
                        mailbox = Path(directory) / f'mailbox-{mode}'
                        mailbox.mkdir()
                        subprocess.run([str(executable), str(mode), str(mailbox)],
                                       check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
