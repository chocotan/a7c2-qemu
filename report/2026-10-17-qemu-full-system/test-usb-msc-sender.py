#!/usr/bin/env python3
"""Concentrated sender ABI and read-only snapshot checks; no VM."""
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
AP=runpy.run_path(str(HERE/'usb-ap-probe.py'))
HARNESS=r'''
#define main snapshot_program_main
#include "usb-sender-snapshot.c"
#undef main
#include <assert.h>
static unsigned calls;static uintptr_t arguments[5];
static uint32_t five(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e){assert(errno==31);calls++;arguments[0]=a;arguments[1]=b;arguments[2]=c;arguments[3]=d;arguments[4]=e;errno=41;return 0x81234567;}
static uint32_t getcategory(uintptr_t a){five(a,0,0,0,0);return 0x6104;}
static uint32_t getmid(uintptr_t a){five(a,0,0,0,0);return 0x1003;}
static uint32_t two(uintptr_t a,uintptr_t b){return five(a,b,0,0,0);}
static uint32_t one(uintptr_t a){return five(a,0,0,0,0);}
static uint32_t three(uintptr_t a,uintptr_t b,uint32_t c){return five(a,b,c,0,0);}
static uint32_t sendthree(uintptr_t a,uintptr_t b,uintptr_t c){return five(a,b,c,0,0);}
static uintptr_t process(uintptr_t a,uint32_t b,uintptr_t c){return five(a,b,c,0,0);}
static void connectcall(uintptr_t a,int32_t b,uintptr_t c){five(a,(uintptr_t)b,c,0,0);}
static void voidone(uintptr_t a){five(a,0,0,0,0);}
#define CHECK(call) do{unsigned old=calls;errno=31;assert((call)==0x81234567);assert(calls==old+1 && errno==41);}while(0)
int main(int argc,char **argv){
 assert(argc==2);memfd=open("/proc/self/mem",O_RDONLY);logfd=open(argv[1],O_CREAT|O_TRUNC|O_RDWR,0600);assert(memfd>=0&&logfd>=0);
 uintptr_t storage[0x600/8]={0};uintptr_t self=(uintptr_t)storage;storage[0x468/8]=1;
 real_async_wait=five;CHECK(u_async_wait(1,2,3,4,5));for(unsigned i=0;i<5;i++)assert(arguments[i]==i+1);
 real_configure=two;CHECK(u_configure(self,0x123456));assert(arguments[0]==self&&arguments[1]==0x123456);
 real_lower=three;CHECK(u_lower(self,0x123456,0x83001));assert(arguments[0]==self&&arguments[1]==0x123456&&arguments[2]==0x83001);
 real_upper=three;CHECK(u_upper(self,0x123456,0x1001002));assert(arguments[2]==0x1001002);
 real_check=one;CHECK(u_check(0x123));assert(arguments[0]==0x123);
 real_sendcmd=sendthree;CHECK(u_sendcmd(0x123,0x456,0x789));assert(arguments[2]==0x789);
 real_msc_process=process;CHECK(u_msc_process(self,0x80020002,0x1234));assert(arguments[0]==self&&arguments[1]==0x80020002&&arguments[2]==0x1234);
 msc_context.self=self;msc_context.source=0x80020002;msc_context.msg=0x1234;real_msc_category=getcategory;real_msc_mid=getmid;
 unsigned previous_calls=calls;errno=31;assert(u_msc_category(0x1234)==0x6104&&errno==41&&calls==previous_calls+1);errno=31;assert(u_msc_mid(0x1234)==0x1003&&errno==41&&calls==previous_calls+2);assert(msc_context.category==0x6104);
 unsigned char bytes[64];assert(readmem(self,bytes,sizeof bytes));assert(!readmem(0,bytes,sizeof bytes));
 void *window=mmap(0,8192,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(window!=MAP_FAILED);assert(!munmap((char *)window+4096,4096));
 assert(readmem((uintptr_t)window+4096-64,bytes,64));assert(!readmem((uintptr_t)window+4096-63,bytes,64));assert(!munmap(window,4096));
 real_connect=connectcall;errno=31;unsigned old=calls;u_connect(0x123,-7,self);assert(calls==old+1&&errno==41&&arguments[0]==0x123&&(int32_t)arguments[1]==-7&&arguments[2]==self);
 real_ap_run=voidone;errno=31;old=calls;u_ap_run(self);assert(calls==old+1&&errno==41&&arguments[0]==self);
 real_ap_send=voidone;errno=31;old=calls;u_ap_send(self);assert(calls==old+1&&errno==41&&arguments[0]==self);
 assert(slot_matches(0x100000,(void *)0x105090,(void *)0x200000,0x5090));assert(!slot_matches(0x100000,(void *)0x105080,(void *)0x200000,0x5090));
 unsigned char group[0x90]={0},control[0x1b8]={0};uintptr_t table[3]={0},object[2]={(uintptr_t)table,(uintptr_t)control};
 uintptr_t base=(uintptr_t)group-0x910a418,manager=base+0x910a108,head=(uintptr_t)group+0x10;
 memcpy(group,&manager,8);memcpy(group+0x10,&head,8);memcpy(group+0x18,&head,8);uintptr_t obj=(uintptr_t)object;memcpy(group+0x88,&obj,8);uint32_t id=0x42;memcpy(control+8,&id,4);table[2]=base+0x34796b0;
 unsigned char before[0x90];memcpy(before,group,sizeof before);scheduler(base);assert(!memcmp(before,group,sizeof before));
 group[0]=0;scheduler(base);group[0]=before[0];assert(snapshot_program_main(1,argv)==64);
 off_t size=lseek(logfd,0,SEEK_END);char *text=calloc(size+1,1);assert(pread(logfd,text,size,0)==size);assert(strstr(text,"msc_run=1"));assert(strstr(text,"header_equal=1 visited=0 pending=0 complete=1 atomic=0"));assert(strstr(text,"MSC_PARAMCHECK_RETURN"));free(text);return 0;
}
'''

class Sender(unittest.TestCase):
    def test_typed_original_single_calls_errno_and_readonly_stable_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'check.c').write_text(HARNESS)
            compile=subprocess.run(['cc','-O2','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined','-Wno-unused-function','-Wno-unused-variable','-I',str(HERE),str(root/'check.c'),'-ldl','-o',str(root/'check')],capture_output=True,text=True,timeout=30)
            self.assertEqual(compile.returncode,0,compile.stderr)
            checked=subprocess.run([str(root/'check'),str(root/'trace')],capture_output=True,text=True,timeout=15)
            self.assertEqual(checked.returncode,0,checked.stderr)

    def test_both_app_entries_and_preinit_required_but_unloaded_msc_not_claimed(self):
        raw=b'''USB_AP_START_TRACE_BEGIN
USB_START INSTALLED tid=1 dso=libInfraUsbCmn.so before_init=1
USB_START INSTALLED tid=1 dso=libUsbControl.so before_init=1
USB_START INSTALLED tid=1 dso=appFw.so before_init=1
USB_START ENTRY_ARMED tid=1 base=0x100000 offset=0x34796b0 original=0x1
USB_START ENTRY_ARMED tid=1 base=0x100000 offset=0x354db04 original=0x2
USB_START AP_PREINIT_CONFIRMED tid=1 pid=5 base=0x100000 resolved=0xabc both_entries=1
USB_AP_START_TRACE_RC=0
USB_AP_START_TRACE_END
'''
        observed=AP['start_trace_summary'](raw);self.assertTrue(observed['app_taps_preinit']);self.assertFalse(observed['msc_loaded'])
        for changed in (raw.replace(b'offset=0x34796b0',b'offset=0x34796b4'),raw.replace(b'base=0x100000 resolved',b'base=0x200000 resolved'),raw.replace(b'AP_PREINIT_CONFIRMED',b'MISSING')):
            self.assertFalse(AP['start_trace_summary'](changed)['app_taps_preinit'])
        script=AP['capture_script']('msc_selected','a'*24,observe_start=True)
        self.assertLess(script.index('before-enter'),script.index('/simulation/inject-key'))
        self.assertGreater(script.index('after-enter'),script.index('sleep 2'))
        self.assertIn('lib(UsbControl|InfraUsbCmn|InfraMscServer)',script)
        subprocess.run(['sh','-n'],input=script,text=True,capture_output=True,check=True)

if __name__=='__main__':unittest.main()
