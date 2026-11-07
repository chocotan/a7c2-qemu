#!/usr/bin/env python3
"""Execute the actual typed wrappers on the host; exercise fresh identity guards."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'usb-start-observe.py'))
AP = runpy.run_path(str(HERE / 'usb-ap-probe.py'))

HARNESS = r'''
#define USB_OBSERVE_HOST_TEST
#include "usb-start-observe.c"
#include <assert.h>
static unsigned calls;
static uintptr_t a[5];
static uint32_t fake5(uintptr_t p,uint32_t d,uintptr_t arg,uint32_t len,uintptr_t cb) {
    assert(errno==31);a[0]=p;a[1]=d;a[2]=arg;a[3]=len;a[4]=cb;
    calls++;errno=45;return 7;
}
static uintptr_t fake3(uintptr_t p,uint32_t d,uintptr_t cb) {assert(errno==31);a[0]=p;a[1]=d;a[2]=cb;calls++;errno=46;return 0x87654321;}
static uintptr_t callback(uint32_t ev,uintptr_t arg,int32_t status) {assert(errno==31);a[0]=ev;a[1]=arg;a[2]=(uintptr_t)status;calls++;errno=47;return 0xabc;}
static int fakeio(int fd,unsigned long req,...) {
    assert(errno==31);a[0]=(uintptr_t)fd;a[1]=req;
    if(_IOC_DIR(req)||_IOC_SIZE(req)){va_list ap;va_start(ap,req);a[2]=va_arg(ap,uintptr_t);va_end(ap);}else a[2]=0;
    calls++;errno=49;return -1;
}
static int fakeopen(const char *p,int flags,...) {assert(errno==31);a[0]=(uintptr_t)p;a[1]=(uintptr_t)flags;if(flags&O_CREAT){va_list ap;va_start(ap,flags);a[2]=(uintptr_t)va_arg(ap,int);va_end(ap);}calls++;errno=50;return 13;}
int main(int argc,char **argv) {
    assert(argc==4);
    assert(slot_matches(0x100000,(void *)0x10df80,(void *)0x200000,0xdf80));
    assert(slot_matches(0x100000,(void *)0x200000,(void *)0x200000,0xdf80));
    assert(!slot_matches(0x100000,(void *)0x10df84,(void *)0x200000,0xdf80));
    assert(!slot_matches(0x100000,(void *)0x101000,(void *)0x200000,0xdf80));
    memfd=open("/proc/self/mem",O_RDONLY);assert(memfd>=0);
    logfd=open(argv[1],O_RDWR|O_CREAT|O_TRUNC,0600);assert(logfd>=0);
    uint32_t svc[80]={0};svc[0xe4/4]=5;
    real_start=fake5;errno=31;
    assert(u_start((uintptr_t)svc,0,(uintptr_t)0xdeadbeef,8,(uintptr_t)0x12345678)==7);
    assert(errno==45 && calls==1 && a[0]==(uintptr_t)svc && a[1]==0 && a[2]==0xdeadbeef && a[3]==8 && a[4]==0x12345678);
    real_infra=fake3;errno=31;assert(u_infra(0x2000,11,0x3000)==0x87654321);assert(errno==46 && a[0]==0x2000 && a[1]==11 && a[2]==0x3000);
    real_complete=callback;errno=31;assert(u_complete(0x10000,0x1234,-5)==0xabc);assert(errno==47 && a[0]==0x10000 && a[1]==0x1234 && (int32_t)a[2]==-5);
    real_ioctl=fakeio;errno=31;assert(u_ioctl(6,0xe304)==-1);assert(errno==49 && a[0]==6 && a[1]==0xe304 && a[2]==0);
    errno=31;assert(u_ioctl(7,0x4001e30c,(uintptr_t)0x123456)==-1);assert(errno==49 && a[2]==0x123456);
    real_open=fakeopen;errno=31;assert(u_open("/dev/usb/sen",O_RDWR)==13);assert(errno==50);
    errno=31;assert(u_open("/dev/usb/sen",O_CREAT|O_RDWR,0640)==13);assert(errno==50 && a[2]==0640);
    assert(identity(argv[2],3,argv[3]));
    assert(!identity(argv[2],4,argv[3]));
    assert(!identity(argv[2],3,"0000000000000000000000000000000000000000000000000000000000000000"));
    for(unsigned i=0;i<1000;i++)emit(0,"NOISE","i=%u",i);
    errno=31;assert(u_ioctl(8,0xe305)==-1);assert(errno==49);
    off_t size=lseek(logfd,0,SEEK_END);assert(size>0 && size<100000);char *text=calloc((size_t)size+1,1);assert(pread(logfd,text,(size_t)size,0)==size);
    assert(strstr(text,"USB_START CAP bounded=1\n"));assert(strstr(text,"req=0xe305 rc=-1 errno=49"));
    assert(strstr(text,"USB_START SVC_START_ENTER") && strstr(text,"length=8 callback=0x12345678"));
    free(text);close(memfd);close(logfd);return 0;
}
'''


CHAIN_HEADER = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum {REG,RECV,SOURCE,SIZE,FREE,SEND,API_COUNT};
struct fixture_taps {
 int32_t (*queue)(uint32_t,uintptr_t,uintptr_t,uintptr_t);
 int32_t (*recv)(uint32_t,uintptr_t,int32_t);
 uint32_t (*source)(uintptr_t);
 int32_t (*size)(uintptr_t);
 int32_t (*free_msg)(uint32_t,uintptr_t);
};
extern unsigned fixture_original[API_COUNT],fixture_original_init;
extern int32_t fixture_queue_rc;
extern unsigned char fixture_message[12];
void fixture_set_taps(struct fixture_taps);
int32_t fixture_queue(uint32_t,uintptr_t,uintptr_t,uintptr_t);
int32_t fixture_recv(uint32_t,uintptr_t,int32_t);
uint32_t fixture_source(uintptr_t);
int32_t fixture_size(uintptr_t);
int32_t fixture_free(uint32_t,uintptr_t);
int32_t osal_reg_msg_queue_cb(uint32_t,uintptr_t,uintptr_t,uintptr_t);
int32_t osal_rcv_msg_tmo(uint32_t,uintptr_t,int32_t);
uint32_t osal_get_msg_src(uintptr_t);
int32_t osal_msg_size(uintptr_t);
int32_t osal_free_msg(uint32_t,uintptr_t);
int32_t osal_snd_msg(uint32_t,uintptr_t);
'''

CHAIN_UIPC = r'''
#include "chain.h"
unsigned fixture_original[API_COUNT],fixture_original_init;
int32_t fixture_queue_rc;
unsigned char fixture_message[12]={0x3a,0x12,0x45,0x67};
static struct fixture_taps taps;
void fixture_set_taps(struct fixture_taps t){taps=t;}
int32_t fixture_queue(uint32_t id,uintptr_t out,uintptr_t cb,uintptr_t context){
 assert(errno==31&&id==0x80020002&&out&&cb&&context==0x9999aaaabbbbccccUL);
 fixture_original[REG]++;*(uintptr_t *)out=0x123456789abcdef0UL;
 assert(((uintptr_t (*)(uint32_t,uintptr_t,int32_t))cb)(id,context,-7)==0xabcdef1234567890UL);
 assert(errno==46);errno=47;return fixture_queue_rc;
}
int32_t fixture_recv(uint32_t id,uintptr_t out,int32_t timeout){
 assert(errno==31&&id==0x80020002&&out&&timeout==-7);fixture_original[RECV]++;
 *(uintptr_t *)out=(uintptr_t)fixture_message;errno=48;return 0;
}
uint32_t fixture_source(uintptr_t msg){assert(errno==31&&msg==(uintptr_t)fixture_message);fixture_original[SOURCE]++;errno=49;return 0x90bf0274;}
int32_t fixture_size(uintptr_t msg){assert(errno==31&&msg==(uintptr_t)fixture_message);fixture_original[SIZE]++;errno=50;return 12;}
int32_t fixture_free(uint32_t owner,uintptr_t msg){assert(errno==31&&owner==0x80021111&&msg==(uintptr_t)fixture_message);fixture_original[FREE]++;errno=51;return -28;}
/* Host dispatch slots stand in for the production AArch64 entry/GOT taps. */
int32_t osal_reg_msg_queue_cb(uint32_t id,uintptr_t out,uintptr_t cb,uintptr_t context){return taps.queue?taps.queue(id,out,cb,context):fixture_queue(id,out,cb,context);}
int32_t osal_rcv_msg_tmo(uint32_t id,uintptr_t out,int32_t timeout){return taps.recv?taps.recv(id,out,timeout):fixture_recv(id,out,timeout);}
uint32_t osal_get_msg_src(uintptr_t msg){return taps.source?taps.source(msg):fixture_source(msg);}
int32_t osal_msg_size(uintptr_t msg){return taps.size?taps.size(msg):fixture_size(msg);}
int32_t osal_free_msg(uint32_t owner,uintptr_t msg){return taps.free_msg?taps.free_msg(owner,msg):fixture_free(owner,msg);}
int32_t osal_snd_msg(uint32_t id,uintptr_t msg){assert(errno==31&&id==0x80023333&&msg==(uintptr_t)fixture_message);fixture_original[SEND]++;errno=52;return -19;}
'''

CHAIN_NATIVE = r'''
#include "chain.h"
static void *(*native_lookup)(void *,const char *);
static void *(*native_open)(const char *,int);
static void *native_cached_lookup,*native_versioned_open;
static int32_t (*queue_next)(uint32_t,uintptr_t,uintptr_t,uintptr_t);
static int32_t (*recv_next)(uint32_t,uintptr_t,int32_t);
static int32_t (*free_next)(uint32_t,uintptr_t),(*send_next)(uint32_t,uintptr_t);
static uintptr_t (*application_next)(void);
unsigned fixture_native[API_COUNT],fixture_native_selected,fixture_native_init,fixture_native_dlopen;
extern unsigned fixture_usb_installed;
__attribute__((constructor)) static void native_initialize(void){
 native_lookup=dlvsym(RTLD_NEXT,"dlsym",HOST_DLSYM_VERSION);assert(native_lookup);
 native_open=native_lookup(RTLD_NEXT,"dlopen");
 native_cached_lookup=native_lookup(RTLD_NEXT,"dlsym");
 native_versioned_open=dlvsym(RTLD_NEXT,"dlopen",HOST_DLSYM_VERSION);
 queue_next=native_lookup(RTLD_NEXT,"osal_reg_msg_queue_cb");
 recv_next=native_lookup(RTLD_NEXT,"osal_rcv_msg_tmo");
 free_next=native_lookup(RTLD_NEXT,"osal_free_msg");
 send_next=native_lookup(RTLD_NEXT,"osal_snd_msg");
 assert(native_open&&queue_next&&recv_next&&free_next&&send_next);
}
int32_t osal_reg_msg_queue_cb(uint32_t id,uintptr_t out,uintptr_t cb,uintptr_t context){
 fixture_native[REG]++;int32_t result=queue_next(id,out,cb,context);int saved=errno;
 fprintf(stderr,"REG_ASYNC id=%#x result=%d callback=%#lx context=%#lx handle=%#lx\n",id,result,cb,context,*(uintptr_t *)out);
 errno=saved;return result;
}
int32_t osal_rcv_msg_tmo(uint32_t id,uintptr_t out,int32_t timeout){fixture_native[RECV]++;return recv_next(id,out,timeout);}
int32_t osal_free_msg(uint32_t owner,uintptr_t msg){fixture_native[FREE]++;return free_next(owner,msg);}
int32_t osal_snd_msg(uint32_t id,uintptr_t msg){fixture_native[SEND]++;return send_next(id,msg);}
static uintptr_t native_application(void){fixture_native_init++;return application_next();}
void *dlopen(const char *name,int flags){fixture_native_dlopen++;void *result=native_open(name,flags&~RTLD_DEEPBIND);return result;}
void *dlsym(void *handle,const char *name){
 void *result=native_lookup(handle,name);
 if(result&&!strcmp(name,"Application_System_Init")){
  assert(fixture_usb_installed);fixture_native_selected++;application_next=result;return native_application;
 }
 return result;
}
const char *fixture_native_lookup_path(void){Dl_info info;assert(dladdr(native_lookup,&info));return info.dli_fname;}
const char *fixture_native_open_path(void){Dl_info info;assert(dladdr(native_open,&info));return info.dli_fname;}
const char *fixture_native_cached_lookup_path(void){Dl_info info;assert(dladdr(native_cached_lookup,&info));return info.dli_fname;}
const char *fixture_native_versioned_open_path(void){Dl_info info;assert(dladdr(native_versioned_open,&info));return info.dli_fname;}
'''

CHAIN_USB = r'''
#define USB_OBSERVE_HOST_TEST
#define USB_EE_ZERO_OBSERVER 1
#include "usb-start-observe.c"
#include "chain.h"
unsigned fixture_usb[API_COUNT],fixture_usb_installed,fixture_usb_preinit,fixture_usb_dlopen;
static int32_t tap_queue(uint32_t id,uintptr_t out,uintptr_t cb,uintptr_t context){fixture_usb[REG]++;return ee_queue(id,out,cb,context);}
static int32_t tap_recv(uint32_t id,uintptr_t out,int32_t timeout){fixture_usb[RECV]++;return ee_recv(id,out,timeout);}
static uint32_t tap_source(uintptr_t msg){fixture_usb[SOURCE]++;return ee_source(msg);}
static int32_t tap_size(uintptr_t msg){fixture_usb[SIZE]++;return ee_size(msg);}
static int32_t tap_free(uint32_t owner,uintptr_t msg){fixture_usb[FREE]++;return ee_free(owner,msg);}
/* GUARD_IMPLEMENTATION */
static void install_fixture_taps(void){
 if(fixture_usb_installed)return;
 const char *names[]={"osal_reg_msg_queue_cb","osal_rcv_msg_tmo","osal_get_msg_src","osal_msg_size","osal_free_msg","osal_snd_msg"};
 for(unsigned i=0;i<API_COUNT;i++){
  void *target=lookup(RTLD_NEXT,names[i]);Dl_info info={0};
  if(!target)ee_guard_api("lookup",names[i],0,0,0);
  if(!dladdr(target,&info)||strcmp(info.dli_fname,FIXTURE_UIPC))ee_guard_api("lookup-path",names[i],0,0,(uintptr_t)target);
  assert(info.dli_saddr==target&&!strcmp(info.dli_sname,names[i]));
 }
 ee_real_queue=fixture_queue;ee_real_recv=fixture_recv;ee_real_source=fixture_source;
 ee_real_size=fixture_size;ee_real_free=fixture_free;
 fixture_set_taps((struct fixture_taps){tap_queue,tap_recv,tap_source,tap_size,tap_free});
 fixture_usb_installed=1;
}
__attribute__((constructor)) static void initialize(void){
 int saved=errno;lookup=dlvsym(RTLD_NEXT,"dlsym",HOST_DLSYM_VERSION);assert(lookup);
 next_dlopen=lookup(RTLD_NEXT,"dlopen");next_dlsym=lookup(RTLD_NEXT,"dlsym");assert(next_dlopen&&next_dlsym);
 memfd=open("/proc/self/mem",O_RDONLY);assert(memfd>=0);errno=saved;
}
static int find_dso(struct dl_phdr_info *info,size_t size,void *arg){
 (void)size;(void)arg;
 if(!strcmp(info->dlpi_name,FIXTURE_APP)){install_fixture_taps();app_base=info->dlpi_addr;}
 return 0;
}
static void ee_preinit(void){assert(fixture_usb_installed&&app_base);fixture_usb_preinit++;}
void *dlopen(const char *name,int flags){
 void *handle=next_dlopen(name,flags);int saved=errno;
 if(handle){fixture_usb_dlopen++;install_fixture_taps();}errno=saved;return handle;
}
void *dlsym(void *handle,const char *name){
 void *result=next_dlsym(handle,name);int saved=errno;
 if(result&&!strcmp(name,"Application_System_Init")){assert(fixture_usb_installed);fixture_usb_preinit++;}
 errno=saved;return result;
}
'''

CHAIN_APP = r'''
#include "chain.h"
static unsigned callback_calls;
static uintptr_t callback(uint32_t id,uintptr_t context,int32_t status){
 assert(errno==31&&id==0x80020002&&context==0x9999aaaabbbbccccUL&&status==-7);
 callback_calls++;errno=46;return 0xabcdef1234567890UL;
}
int main(int argc,char **argv){
 assert(argc==3);fixture_queue_rc=atoi(argv[1]);
 void *handle=dlopen(argv[2],RTLD_NOW|RTLD_LOCAL|RTLD_DEEPBIND);assert(handle);
 uintptr_t (*initialize)(void)=dlsym(handle,"Application_System_Init");assert(initialize);
 assert(!dlsym(handle,"fixture_missing_symbol")&&dlerror());
 assert(initialize()==0xfedcba9876543210UL&&fixture_original_init==1);
 uintptr_t out=0,msg=0;errno=31;
 assert(osal_reg_msg_queue_cb(0x80020002,(uintptr_t)&out,(uintptr_t)callback,0x9999aaaabbbbccccUL)==fixture_queue_rc);
 assert(errno==47&&out==0x123456789abcdef0UL&&callback_calls==1);
 errno=31;assert(osal_rcv_msg_tmo(0x80020002,(uintptr_t)&msg,-7)==0&&errno==48&&msg==(uintptr_t)fixture_message);
 errno=31;assert(osal_get_msg_src(msg)==0x90bf0274&&errno==49);
 errno=31;assert(osal_msg_size(msg)==12&&errno==50);
 errno=31;assert(osal_free_msg(0x80021111,msg)==-28&&errno==51);
 errno=31;assert(osal_snd_msg(0x80023333,msg)==-19&&errno==52);
 unsigned *native=dlsym(RTLD_DEFAULT,"fixture_native"),*usb=dlsym(RTLD_DEFAULT,"fixture_usb");assert(native&&usb);
 const unsigned expected_native[]={1,1,0,0,1,1},expected_usb[]={1,1,1,1,1,0};
 for(unsigned i=0;i<API_COUNT;i++)assert(native[i]==expected_native[i]&&usb[i]==expected_usb[i]&&fixture_original[i]==1);
 unsigned *preinit=dlsym(RTLD_DEFAULT,"fixture_usb_preinit"),*opens=dlsym(RTLD_DEFAULT,"fixture_usb_dlopen");
 unsigned *selected=dlsym(RTLD_DEFAULT,"fixture_native_selected"),*inits=dlsym(RTLD_DEFAULT,"fixture_native_init");
 assert(preinit&&opens&&*opens==1&&selected&&*selected==1&&inits&&*inits==1);
 const char *(*sympath)(void)=dlsym(RTLD_DEFAULT,"fixture_native_lookup_path");
 const char *(*openpath)(void)=dlsym(RTLD_DEFAULT,"fixture_native_open_path");
 const char *(*cachedpath)(void)=dlsym(RTLD_DEFAULT,"fixture_native_cached_lookup_path");
 const char *(*versionedpath)(void)=dlsym(RTLD_DEFAULT,"fixture_native_versioned_open_path");
 unsigned *native_opens=dlsym(RTLD_DEFAULT,"fixture_native_dlopen");assert(native_opens&&*native_opens==1);
 printf("REG native=%u usb=%u original=%u callback=%u rc=%d errno=47 out=%#lx\n",native[REG],usb[REG],fixture_original[REG],callback_calls,fixture_queue_rc,out);
 printf("LOADER native_dlsym=%s native_dlopen=%s usb_dlopen=%u usb_preinit=%u native_selected=%u native_init=%u original_init=%u\n",sympath(),openpath(),*opens,*preinit,*selected,*inits,fixture_original_init);
 printf("CACHE native_dlopen_count=%u cached_dlsym=%s versioned_dlopen=%s\n",*native_opens,cachedpath(),versionedpath());
 return 0;
}
'''


class NativeWrappers(unittest.TestCase):
    def test_real_typed_passthrough_errno_noarg_and_bounded_error_reserve(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'harness.c').write_text(HARNESS)
            (root / 'identity').write_bytes(b'abc')
            target = root / 'harness'
            subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Wno-unused-function',
                            '-Wno-unused-variable', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I', str(HERE), str(root / 'harness.c'), '-ldl', '-o', str(target)],
                           capture_output=True, text=True, check=True, timeout=30)
            result = subprocess.run([str(target), str(root / 'trace'), str(root / 'identity'),
                                     hashlib.sha256(b'abc').hexdigest()], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_versioned_loader_chain_preserves_callbacks_and_preinit(self):
        # Use the host's real version only for this fixture, never for AArch64 production.
        versions = {'x86_64': 'GLIBC_2.2.5', 'aarch64': 'GLIBC_2.17'}
        if os.uname().machine not in versions:
            self.skipTest('Host loader fixture supports x86_64 and AArch64 glibc')
        version = versions[os.uname().machine]
        evidence = []
        destination = os.environ.get('A7C2_USB_PRELOAD_CHAIN_EVIDENCE')
        if destination:
            self.addCleanup(lambda: Path(destination).write_text(
                'HOST FIXTURE ONLY; production loader code, host version ' + version + '\n' + '\n'.join(evidence)))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            if destination:
                root = Path(destination).parent / 'host-fixture'
                root.mkdir(exist_ok=False)
            (root / 'chain.h').write_text(CHAIN_HEADER)
            loader_map = (HERE / 'usb-start-observe.map').read_text()
            self.assertEqual(loader_map.split(), ['GLIBC_2.17', '{', 'global:', 'dlopen;', 'dlsym;', '};'])
            host_map = root / 'host-loader.map'
            host_map.write_text(loader_map.replace('GLIBC_2.17', version))
            guard = (HERE / 'usb-ee-zero-observe.inc').read_text()
            guard = guard[guard.index('static void ee_guard_api('):guard.index('static void ee_install(')]
            legacy_usb = CHAIN_USB.replace('/* GUARD_IMPLEMENTATION */', guard)
            production = (HERE / 'usb-start-observe.c').read_text()
            loader = production[production.index('static void *usb_loader_dlopen('):production.rindex('\n#endif')]
            # Count entry only; execute the production loader and symbol-selection code verbatim.
            loader = loader.replace('void *handle=next_dlopen(name,flags);',
                                    'fixture_usb_dlopen++;void *handle=next_dlopen(name,flags);')
            sources = {'uipc': CHAIN_UIPC, 'native': CHAIN_NATIVE, 'usb': legacy_usb,
                       'fixed': legacy_usb[:legacy_usb.index('void *dlopen(')] + loader,
                       'plugin': '#include "chain.h"\nuintptr_t Application_System_Init(void){fixture_original_init++;return 0xfedcba9876543210UL;}\n',
                       'app': CHAIN_APP}
            targets = {'uipc': root / 'libfixture-uipc.so', 'native': root / 'menu-observe.so',
                       'usb': root / 'usb-start-observe.so', 'fixed': root / 'usb-start-fixed.so',
                       'plugin': root / 'fixture-app.so', 'app': root / 'app'}
            for name, source in sources.items():
                path = root / (name + '.c'); path.write_text(source)
                command = ['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra',
                           '-Wno-unused-function', '-Wno-unused-variable', '-fno-omit-frame-pointer',
                           '-I', str(root), '-I', str(HERE),
                           '-DHOST_DLSYM_VERSION="' + version + '"',
                           '-DFIXTURE_UIPC="' + str(targets['uipc']) + '"',
                           '-DFIXTURE_APP="' + str(targets['plugin']) + '"',
                           *(['-shared', '-fPIC'] if name != 'app' else []), str(path),
                           *(['-L', str(root), '-lfixture-uipc', '-Wl,-rpath,$ORIGIN'] if name != 'uipc' else []),
                           *(['-Wl,--version-script=' + str(host_map)] if name == 'fixed' else []),
                           '-Wl,-z,now', '-ldl', '-o', str(targets[name])]
                built = subprocess.run(command, capture_output=True, text=True, timeout=30)
                evidence.append('BUILD ' + name + ' command=' + repr(command) + ' rc=' + str(built.returncode) + '\n' + built.stdout + built.stderr)
                self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            for option in ('-Ws', '--version-info'):
                symbols = subprocess.run(['readelf', option, str(targets['fixed'])],
                                         capture_output=True, text=True, check=True, timeout=10).stdout
                evidence.append('FIXED HOST ELF ' + option + '\n' + symbols)
                if option == '-Ws':
                    for name in ('dlopen', 'dlsym'):
                        self.assertIn(name + '@@' + version, symbols)
                    self.assertIn('fixture_usb_installed', symbols)
                else:
                    self.assertIn('Name: ' + version, symbols)
            old = subprocess.run([str(targets['app']), '0', str(targets['plugin'])],
                                 env=dict(os.environ, LD_PRELOAD=str(targets['usb']) + ':' + str(targets['native'])),
                                 capture_output=True, text=True, timeout=10)
            evidence.append('OLD PREPEND rc=' + str(old.returncode) + '\n' + old.stdout + old.stderr)
            self.assertEqual(old.returncode, 79, old.stdout + old.stderr)
            self.assertIn('USB_START_GUARD_FAILED reason=EE lookup-path api=osal_reg_msg_queue_cb', old.stderr)
            self.assertIn('path=' + str(targets['native']), old.stderr)
            self.assertNotIn('REG_ASYNC', old.stderr)
            for key, expected_preinit in (('usb', 0), ('fixed', 1)):
                for rc in (0, -19):
                    with self.subTest(loader=key, original_rc=rc):
                        appended = subprocess.run([str(targets['app']), str(rc), str(targets['plugin'])],
                                                 env=dict(os.environ, LD_PRELOAD=str(targets['native']) + ':' + str(targets[key])),
                                                 capture_output=True, text=True, timeout=10)
                        evidence.append(key.upper() + ' APPEND rc=' + str(appended.returncode) + '\n' + appended.stdout + appended.stderr)
                        self.assertEqual(appended.returncode, 0, appended.stdout + appended.stderr)
                        self.assertIn(f'REG native=1 usb=1 original=1 callback=1 rc={rc} errno=47 out=0x123456789abcdef0', appended.stdout)
                        self.assertIn('REG_ASYNC', appended.stderr)
                        self.assertIn('native_dlopen=' + str(targets[key]), appended.stdout)
                        self.assertIn(f'usb_dlopen=1 usb_preinit={expected_preinit} native_selected=1 native_init=1 original_init=1', appended.stdout)
                        self.assertIn('CACHE native_dlopen_count=1 cached_dlsym=' + str(targets[key]), appended.stdout)
                        if key == 'fixed':
                            self.assertIn('native_dlsym=' + str(targets[key]), appended.stdout)
                            self.assertIn('versioned_dlopen=' + str(targets[key]), appended.stdout)
                        else:
                            self.assertRegex(appended.stdout, r'native_dlsym=\S*/libc\.so\.6 ')

    def test_wrapper_exact_anchor_and_complete_transparent_handoff(self):
        original = (HERE / 'guest/bootin-wrapper').read_text()
        derived = API['wrapper'](original)
        self.assertIn('exec "$original_elf" "$@"', derived)
        self.assertIn('*" fullsystem.usb-service=original-sen-observe-v1 "*', derived)
        self.assertEqual(derived.count('export LD_PRELOAD=$LD_PRELOAD:/simulation/usb-start-observe.so'), 1)
        subprocess.run(['sh', '-n'], input=derived, text=True, check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, 'preload anchor'):
            API['wrapper'](original + API['PRELOAD'])

    def test_identity_drift_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'; source.mkdir()
            (source / 'guest').mkdir()
            for name in ('usb-start-observe.py', 'usb-start-observe.c', 'usb-start-observe.map', 'usb-msc-sender.inc', 'usb-sender-snapshot.c', 'guest/bootin-wrapper'):
                (source / name).write_bytes((HERE / name).read_bytes())
            analysis = root / 'analysis'; analysis.mkdir()
            (analysis / 'root/simulation').mkdir(parents=True)
            (analysis / 'root/lib').mkdir()
            (analysis / 'root/simulation/usb-start-observe.so').write_bytes(b'compiled fixture')
            (analysis / 'root/simulation/usb-sender-snapshot').write_bytes(b'compiled snapshot fixture')
            (analysis / 'usb-start-bootin-wrapper').write_text(API['wrapper']((source / 'guest/bootin-wrapper').read_text()))
            for name in ('libc-2.25.so', 'libdl-2.25.so'):
                (analysis / 'root/lib' / name).write_bytes(name.encode())
            contract = dict(sender_source_sha256=API['digest'](source / 'usb-msc-sender.inc'),
                            snapshot_source_sha256=API['digest'](source / 'usb-sender-snapshot.c'),
                            snapshot_sha256=API['digest'](analysis / 'root/simulation/usb-sender-snapshot'),
                            source_sha256=API['digest'](source / 'usb-start-observe.c'),
                            loader_map_sha256=API['digest'](source / 'usb-start-observe.map'),
                            command=['-Wl,--version-script=' + str(source / 'usb-start-observe.map')],
                            builder_sha256=API['digest'](source / 'usb-start-observe.py'),
                            observer_sha256=API['digest'](analysis / 'root/simulation/usb-start-observe.so'),
                            wrapper_source_sha256=API['digest'](source / 'guest/bootin-wrapper'),
                            wrapper_sha256=API['digest'](analysis / 'usb-start-bootin-wrapper'),
                            sen=API['SEN'], dsos=API['DSOS'],
                            libraries={name: API['digest'](analysis / 'root/lib' / name) for name in ('libc-2.25.so', 'libdl-2.25.so')})
            (analysis / 'full-system.json').write_text(json.dumps({'usb_start_observe': contract}))
            with patch.dict(API['validate'].__globals__, HERE=source):
                self.assertEqual(len(API['validate'](analysis)), 9)
                manifest = analysis / 'full-system.json'
                for command in ([], contract['command'] * 2, ['-Wl,--version-script=other.map']):
                    manifest.write_text(json.dumps({'usb_start_observe': dict(contract, command=command)}))
                    with self.assertRaisesRegex(ValueError, 'version-script linkage drift'):
                        API['validate'](analysis)
                manifest.write_text(json.dumps({'usb_start_observe': contract}))
                loader_map = source / 'usb-start-observe.map'
                original_map = loader_map.read_bytes(); loader_map.write_bytes(original_map + b'\n')
                with self.assertRaisesRegex(ValueError, 'identity drift: loader_map_sha256'):
                    API['validate'](analysis)
                loader_map.write_bytes(original_map)
                (analysis / 'root/simulation/usb-start-observe.so').write_bytes(b'drift')
                with self.assertRaisesRegex(ValueError, 'identity drift'):
                    API['validate'](analysis)

    def test_trace_does_not_promote_method_zero_or_ready(self):
        trace = b'''USB_AP_START_TRACE_BEGIN
USB_START INSTALLED tid=17 dso=libInfraUsbCmn.so before_init=1
USB_START INSTALLED tid=17 dso=libUsbControl.so before_init=1
USB_START CREATE_RETURN tid=17 message=0x1 svc=0x2 state=3 rc=0 errno=2
USB_START IOCTL_RETURN tid=17 fd=8 req=0x4018e203 rc=-19 errno=19
USB_AP_START_TRACE_RC=0
USB_AP_START_TRACE_END
'''
        result = AP['start_trace_summary'](trace)
        self.assertTrue(result['installed_before_init'])
        self.assertFalse(result['start_syscall_actual_zero'])
        self.assertEqual(result['start_syscalls'], [dict(fd=8, rc=-19, errno=19)])
        self.assertTrue(AP['start_trace_summary'](trace.replace(b'rc=-19 errno=19', b'rc=0 errno=19'))['start_syscall_actual_zero'])
        self.assertFalse(AP['start_trace_summary'](trace.replace(b'TRACE_RC=0', b'TRACE_RC=1'))['available'])

    def test_observation_is_explicit_and_read_only(self):
        normal = AP['capture_script']('msc_selected', 'a'*24)
        observed = AP['capture_script']('msc_selected', 'a'*24, observe_start=True)
        self.assertNotIn('usb-start-observe.log', normal)
        self.assertIn('cat /dev/qemu-simulation/usb-start-observe.log', observed)
        self.assertIn('"$t/wchan" "$t/stack"', observed)
        self.assertNotIn('insmod', observed)
        self.assertNotIn('power/control >', observed)


if __name__ == '__main__':
    unittest.main()
