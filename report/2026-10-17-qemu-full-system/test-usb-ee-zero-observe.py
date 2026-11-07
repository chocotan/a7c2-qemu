#!/usr/bin/env python3
"""Host ABI, zero-publication, explicit binding and prepare-only tests; no VM."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
BUILD = runpy.run_path(str(HERE / 'usb-start-observe.py'))
CONTROL = runpy.run_path(str(HERE / 'usb-control-start.py'))
HARNESS = r'''
#define USB_OBSERVE_HOST_TEST
#define USB_EE_ZERO_OBSERVER 1
#include "usb-start-observe.c"
#include <assert.h>
static uintptr_t args[4],message;
static int32_t native_rc,native_size=12;
static unsigned native_calls;
static int32_t queue_native(uint32_t q,uintptr_t h,uintptr_t c,uintptr_t a) {
 assert(errno==31);args[0]=q;args[1]=h;args[2]=c;args[3]=a;native_calls++;
 if(!native_rc)*(uintptr_t *)h=0x123456789abcdef0UL;errno=47;return native_rc;
}
static int32_t recv_native(uint32_t q,uintptr_t o,int32_t t) {
 assert(errno==31);args[0]=q;args[1]=o;args[2]=(uintptr_t)(int64_t)t;native_calls++;
 if(!native_rc)*(uintptr_t *)o=message;errno=48;return native_rc;
}
static uint32_t source_native(uintptr_t p) {assert(errno==31&&p==message);native_calls++;errno=49;return 0x90bf0274;}
static int32_t size_native(uintptr_t p) {assert(errno==31&&p==message);native_calls++;errno=50;return native_size;}
static int32_t free_native(uint32_t owner,uintptr_t p) {assert(errno==31);args[0]=owner;args[1]=p;native_calls++;errno=51;return native_rc;}
static struct ee_pair register_native(uintptr_t m,uintptr_t k) {assert(errno==31);args[0]=m;args[1]=k;native_calls++;errno=52;return (struct ee_pair){0xabcdef1234567890UL,0xfedcba9876543210UL};}
static uintptr_t wait_native(uintptr_t f) {assert(errno==31);args[0]=f;native_calls++;errno=53;return 0x123456789abcdef0UL;}
static off_t logsize(void) {return lseek(logfd,0,SEEK_END);}
int main(int argc,char **argv) {
 assert(argc==2||argc==3);logfd=open(argv[1],O_RDWR|O_CREAT|O_TRUNC,0600);assert(logfd>=0);memfd=open("/proc/self/mem",O_RDONLY);assert(memfd>=0);
 if(argc==3)fatal("host exact guard evidence");
 ee_real_queue=queue_native;ee_real_recv=recv_native;ee_real_source=source_native;ee_real_size=size_native;ee_real_free=free_native;ee_real_register=register_native;ee_real_wait=wait_native;
 uintptr_t handle=0,out=0;unsigned char bytes[12]={6,0,0xa3,0x20,0,0,0,0,1,0,0,0};message=(uintptr_t)bytes;
 errno=31;assert(ee_queue(7,(uintptr_t)&handle,0x1111222233334444UL,0x9999aaaabbbbccccUL)==0);
 assert(errno==47&&logsize()>0&&native_calls==1&&ee_foreign_queue_calls==1&&ee_essential==0);
 assert(args[0]==7&&args[1]==(uintptr_t)&handle&&args[2]==0x1111222233334444UL&&args[3]==0x9999aaaabbbbccccUL);
 errno=31;assert(ee_queue(EE_QUEUE,(uintptr_t)&handle,0x1111222233334444UL,0x9999aaaabbbbccccUL)==0);
 assert(errno==47&&handle==0x123456789abcdef0UL&&args[0]==EE_QUEUE&&args[1]==(uintptr_t)&handle&&args[2]==0x1111222233334444UL&&args[3]==0x9999aaaabbbbccccUL);
 native_rc=-19;errno=31;assert(ee_queue(EE_QUEUE,1,0x1122334455667788UL,0x33)==-19);assert(errno==47);native_rc=0;
 off_t before=logsize();errno=31;assert(ee_recv(9,(uintptr_t)&out,-7)==0);assert(errno==48&&logsize()==before&&!ee_received.msg);
 errno=31;assert(ee_recv(EE_QUEUE,(uintptr_t)&out,-1)==0);assert(errno==48&&out==message&&args[2]==(uintptr_t)-1&&ee_received.msg==message);
 unsigned char copied[12];assert(!ee_copy12(message,copied));
 errno=31;assert(ee_source(message)==0x90bf0274&&errno==49);assert(!ee_copy12(message,copied));
 native_size=-1024;errno=31;assert(ee_size(message)==-1024&&errno==50&&!ee_copy12(message,copied));
 for(int i=-1;i<=12;i++){native_size=i;errno=31;assert(ee_size(message)==i&&errno==50);assert(ee_copy12(message,copied)==(i>=12));}
 assert(!memcmp(copied,bytes,12));assert(!ee_copy12(message+1,copied));assert(!ee_copy12(0,copied));assert(!ee_copy12(UINTPTR_MAX,copied));
 native_rc=-28;errno=31;assert(ee_free(0x80021111,message)==-28);assert(errno==51&&args[0]==0x80021111&&args[1]==message&&!ee_received.msg);assert(!ee_copy12(message,copied));
 native_rc=-19;errno=31;assert(ee_recv(EE_QUEUE,1,-1)==-19);assert(errno==48&&!ee_received.msg);native_rc=0;
 before=logsize();errno=31;struct ee_pair result=ee_register(0x1234567890UL,0xabcdef1234UL);assert(errno==52&&result.x0==0xabcdef1234567890UL&&result.x1==0xfedcba9876543210UL&&args[0]==0x1234567890UL&&args[1]==0xabcdef1234UL&&logsize()==before);
 app_base=0x100000;ee_remember_register(0x11,0x22,app_base+0x35492b8,result);assert(!ee_registration.valid&&logsize()==before);
 ee_remember_register(0x11,0x22,app_base+0x35492bc,result);assert(ee_registration.valid&&logsize()==before);
 assert(!ee_wait_enter(app_base+0x35492c8,0x33445566)&&logsize()==before);
 assert(ee_wait_enter(app_base+0x35492cc,0x33445566)&&!ee_registration.valid);
 errno=31;assert(ee_wait(0x4444555566667777UL)==0x123456789abcdef0UL&&errno==53&&args[0]==0x4444555566667777UL);
 /* Saturation cannot consume the separate first-wait proof reserve. */
 ee_first_wait=0;for(unsigned i=0;i<600;i++)ee_emit(0,"NOISE","n=%u",i);
 ee_remember_register(0x11,0x22,app_base+0x35492bc,result);assert(ee_wait_enter(app_base+0x35492cc,0x1234));
 off_t size=logsize();assert(size<180000);char *text=calloc((size_t)size+1,1);assert(pread(logfd,text,(size_t)size,0)==size);
 assert(strstr(text,"QUEUE_RETURN")&&strstr(text,"queue=0x7"));
 assert(strstr(text,"callback=0x1111222233334444 context=0x9999aaaabbbbcccc"));assert(strstr(text,"handle_read=0 callback=0x1122334455667788"));
 assert(strstr(text,"raw=0600a3200000000001000000"));assert(strstr(text,"owner=0x80021111"));assert(strstr(text,"return_x1=0xfedcba9876543210"));assert(strstr(text,"deferred_until_unlock=1"));assert(strstr(text,"USB_EE CAP bounded=1"));
 free(text);close(memfd);close(logfd);assert(native_calls>20);return 0;
}
'''


class PassiveABI(unittest.TestCase):
    def test_native_passthrough_lifetime_bounded_copy_and_deferred_register(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'harness.c').write_text(HARNESS)
            command=['cc','-std=gnu11','-O2','-Wall','-Wextra','-Wno-unused-function','-Wno-unused-variable',
                     '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(HERE),str(root/'harness.c'),'-ldl','-o',str(root/'harness')]
            build=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            result=subprocess.run([str(root/'harness'),str(root/'trace')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            mirrored=result.stderr.encode().splitlines(keepends=True)
            self.assertLessEqual(len(mirrored),16)
            for line in mirrored:self.assertIn(line,(root/'trace').read_bytes())
            self.assertIn('USB_EE QUEUE_RETURN ',result.stderr)
            self.assertIn('USB_EE PROMISE_REGISTER ',result.stderr)
            self.assertIn('USB_EE WAIT_ENTER ',result.stderr)
            failed=subprocess.run([str(root/'harness'),str(root/'fatal-trace'),'fatal'],capture_output=True,text=True,timeout=10)
            self.assertEqual(failed.returncode,79,failed.stdout+failed.stderr)
            self.assertEqual(failed.stderr,'USB_START_GUARD_FAILED reason=host exact guard evidence\n')
            self.assertIn('GUARD_FAILED',(root/'fatal-trace').read_text())

    def test_console_mirror_profiles_budgets_errno_and_same_ram_record(self):
        text=(HERE/'usb-ee-zero-observe.inc').read_text()
        emitter=text[text.index('static unsigned ee_records'):text.index('static int32_t ee_queue(')]
        fixture=r'''
#define USB_OBSERVE_HOST_TEST
#include "usb-start-observe.c"
#include <time.h>
#include <assert.h>
PROFILE
EMITTER
int main(int argc,char **argv) {
 assert(argc==2||argc==3);logfd=open(argv[1],O_RDWR|O_CREAT|O_TRUNC,0600);assert(logfd>=0);
 if(argc==3)close(STDERR_FILENO);
 errno=73;ee_emit(0,"NOISE","sample=0 caller=0x1234");assert(errno==73);
 for(unsigned i=0;i<400;i++){errno=73;ee_emit(0,"RECV_RETURN","sample=%u caller=0x1234 rc=-19 errno=47",i);assert(errno==73);}
 for(unsigned i=0;i<40;i++){errno=73;ee_emit(1,"WAIT_ENTER","sample=%u caller=0x5678 after_original_unlock=1",i);assert(errno==73);}
 printf("%ld\n",(long)getpid());close(logfd);return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for mode,define,limit in (('zero','USB_EE_ZERO_OBSERVER',16),('functional','USB_EE_NORMAL_COLD',32),('unknown','USB_EE_UNKNOWN_PROFILE',0)):
                with self.subTest(mode=mode):
                    source=root/(mode+'.c');target=root/mode;trace=root/(mode+'.log')
                    source.write_text(fixture.replace('PROFILE','#define '+define+' 1').replace('EMITTER',emitter))
                    built=subprocess.run(['cc','-std=gnu11','-O2','-I',str(HERE),str(source),'-ldl','-o',str(target)],capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stdout+built.stderr)
                    run=subprocess.run([str(target),str(trace)],capture_output=True,timeout=10)
                    self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                    lines=run.stderr.splitlines(keepends=True);ram=trace.read_bytes()
                    self.assertEqual(len(lines),limit)
                    self.assertEqual(sum(b'USB_EE RECV_RETURN ' in line for line in lines),8 if limit else 0)
                    self.assertEqual(sum(b'USB_EE WAIT_ENTER ' in line for line in lines),limit-8 if limit else 0)
                    for line in lines:
                        self.assertEqual(ram.splitlines(keepends=True).count(line),1)
                        self.assertIn(b' pid='+run.stdout.strip()+b' ',line)
                        self.assertIn(b' tid='+run.stdout.strip()+b' ',line)
                        self.assertRegex(line,rb' mono=\d+\.\d{9} clock_ok=1 ')
                    self.assertIn(b'USB_EE NOISE ',ram)
                    self.assertEqual(ram.count(b'USB_EE WAIT_ENTER '),32 if mode=='functional' else 16)
                    failed_write=subprocess.run([str(target),str(root/(mode+'-closed.log')),'closed-stderr'],capture_output=True,timeout=10)
                    self.assertEqual(failed_write.returncode,0,failed_write.stdout+failed_write.stderr)
                    self.assertEqual(failed_write.stderr,b'')

    def test_observer_has_no_publication_or_opaque_object_fields(self):
        text=(HERE/'usb-ee-zero-observe.inc').read_text()
        for name in ('osal_snd_msg','osal_valloc_msg_wait','osal_stat_msgq','set_msg_src','ee_can_publish=1','->'):
            self.assertNotIn(name,text)
        deferred=text[text.index('static void ee_remember_register'):text.index('static int ee_wait_enter')]
        for name in ('ee_emit(', 'readmem(', 'syscall(', 'memcpy(', 'malloc(', 'errno', '__tls_get_addr', 'ee_cold_'):
            self.assertNotIn(name,deferred)
        self.assertIn('struct ee_pair r=ee_real_register(map,key)',deferred)
        selection=text[text.index('    for(unsigned i=0;i<sizeof imports/sizeof *imports;i++) {'):text.index('    for(unsigned i=0;i<sizeof promises/sizeof *promises;i++)entry_install')]
        self.assertIn('ee_got(',selection)
        self.assertIn('!strcmp(imports[i].name,"osal_free_msg")&&originals[i]!=raw',selection)
        self.assertIn('old_slots[i],originals[i],raw,raw,ee_native_pins.sha256',selection)

    def test_exact_original_elf_bytes_when_private_inputs_are_supplied(self):
        paths={name:os.environ.get('A7C2_EE_'+name.upper()) for name in ('ap','uipc')}
        if not all(paths.values()):self.skipTest('private exact original ELF inputs not supplied')
        images={name:Path(path).read_bytes() for name,path in paths.items()}
        for name,expected in [('ap',BUILD['DSOS']['/usr/lib/appFw.so']),('uipc',BUILD['EE_DSO']['/usr/lib/libosal_uipc.so'])]:
            self.assertEqual(len(images[name]),expected['bytes']);self.assertEqual(hashlib.sha256(images[name]).hexdigest(),expected['sha256'])
        text=(HERE/'usb-ee-zero-observe.inc').read_text()
        pins=re.findall(r'\{(0x[0-9a-f]+),\{((?:0x[0-9a-f]+,?){4})\}',text)
        pins += re.findall(r'\{0x[0-9a-f]+,(0x[0-9a-f]+),\{((?:0x[0-9a-f]+,?){4})\}',text)
        self.assertEqual(len(pins),7)
        for address,words in pins:
            va=int(address,16);image=images['ap' if va>0x100000 else 'uipc'];phoff=struct.unpack_from('<Q',image,32)[0];phnum=struct.unpack_from('<H',image,56)[0]
            segments=[struct.unpack_from('<IIQQQQQQ',image,phoff+56*i) for i in range(phnum)]
            matches=[off+va-start for kind,_,off,start,_,size,_,_ in segments if kind==1 and start<=va and va+16<=start+size]
            self.assertEqual(len(matches),1)
            self.assertEqual(image[matches[0]:matches[0]+16],struct.pack('<4I',*(int(w,16) for w in words.split(','))))


class ExplicitMode(unittest.TestCase):
    def test_prepare_only_passes_opt_in_and_never_calls_vm_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'out';out.mkdir()
            ap=dict(CONTROL['AP'],PERSISTENT={'fresh_output':lambda *a:out},save=lambda *a:None)
            calls=[];ap['main']=lambda *a,**kw:calls.append((a,kw))
            with patch.dict(CONTROL['main'].__globals__,AP=ap,prepare_helpers=lambda *a,**kw:calls.append(kw) or root/'helpers'):
                argv=[value for name in ('instance','runtime','module','qemu-build','output') for value in ('--'+name,str(root/name))]
                self.assertEqual(CONTROL['main']([*argv,'--seconds','120','--observe-start','--observe-ee','--select-msc','--prepare-only']),0)
                self.assertEqual(calls,[dict(observe_start=True,observe_ee=True)])
                for options in (['--observe-ee'],['--observe-start','--observe-ee','--seconds','121']):
                    with self.assertRaises(SystemExit) as error:CONTROL['main']([*argv,*options,'--prepare-only'])
                    self.assertEqual(error.exception.code,2)

    def test_lower_actual_entry_rejects_over_budget_before_creating_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runtime/analysis').mkdir(parents=True)
            (root/'runtime/analysis/full-system.json').write_text(json.dumps({'usb_start_observe': {'ee_observer': BUILD['EE_CONTRACT']}}))
            argv=[value for name in ('instance','runtime','module','qemu-build','output') for value in ('--'+name,str(root/name))]
            with self.assertRaises(SystemExit) as error:
                CONTROL['AP']['main']([*argv,'--seconds','121'],observe_start=True,camera_profile=BUILD['PROFILE'])
            self.assertEqual(error.exception.code,2)
            self.assertFalse((root/'output').exists())

    def test_manifest_binds_source_compiled_mode_and_original_uipc(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();(source/'guest').mkdir()
            for name in ('usb-start-observe.py','usb-start-observe.c','usb-start-observe.map','usb-msc-sender.inc','usb-ee-zero-observe.inc','usb-ee-native-got.h','usb-sender-snapshot.c','guest/bootin-wrapper'):
                (source/name).write_bytes((HERE/name).read_bytes())
            analysis=root/'analysis';(analysis/'root/simulation').mkdir(parents=True);(analysis/'root/lib').mkdir()
            for name in ('libc-2.25.so','libdl-2.25.so'):(analysis/'root/lib'/name).write_bytes(name.encode())
            def compile_fixture(command,**kw):
                target=Path(command[command.index('-o')+1]);target.write_bytes(b'host fixture '+(BUILD['EE_PROFILE'].encode() if '-DUSB_EE_ZERO_OBSERVER=1' in command else b''))
                return subprocess.CompletedProcess(command,0,'','')
            (analysis/'root/simulation/menu-observe.so').write_bytes(b'native ELF fixture')
            (source/'native-source.c').write_bytes(b'verified native source fixture')
            native=dict(guest_path='/simulation/menu-observe.so',bytes=18,sha256='1'*64,
                        source_path=str(source/'native-source.c'),source_sha256=BUILD['digest'](source/'native-source.c'),
                        exports=[dict(name='osal_free_msg',va=0x1000,cached_va=0x2000,code_hex='00'*16)])
            globals_=BUILD['prepare'].__globals__
            with patch.dict(globals_,HERE=source,native_forwarder_contract=lambda analysis:native),patch.object(subprocess,'run',side_effect=compile_fixture):
                contract=BUILD['prepare'](analysis,observe_ee=True)
                self.assertEqual(contract['ee_observer']['ee_can_publish'],False)
                self.assertEqual(contract['dsos']['/usr/lib/libosal_uipc.so'],BUILD['EE_DSO']['/usr/lib/libosal_uipc.so'])
                manifest={'usb_start_observe':contract};path=analysis/'full-system.json';path.write_text(json.dumps(manifest))
                self.assertEqual(len(BUILD['validate'](analysis)),14)
                self.assertEqual(contract['loader_map_sha256'],BUILD['digest'](source/'usb-start-observe.map'))
                self.assertEqual(contract['command'].count('-Wl,--version-script='+str(source/'usb-start-observe.map')),1)
                for modify in (lambda c:c.pop('ee_observer'),lambda c:c['ee_observer'].update(ee_can_publish=True),lambda c:c.update(dsos=BUILD['DSOS']),lambda c:c['native_forwarder'].update(sha256='0'*64),lambda c:c['native_forwarder']['exports'][0].update(va=7)):
                    changed=json.loads(json.dumps(manifest));modify(changed['usb_start_observe']);path.write_text(json.dumps(changed))
                    with self.assertRaisesRegex(ValueError,'EE observer|wrapper/module|native forwarder'):BUILD['validate'](analysis)
                path.write_text(json.dumps(manifest));(source/'usb-ee-zero-observe.inc').write_text('drift')
                with self.assertRaisesRegex(ValueError,'source contract drift'):BUILD['validate'](analysis)
            with self.assertRaisesRegex(ValueError,'explicit --observe-start'):CONTROL['prepare_helpers'](root/'unused',root/'unused-out',observe_ee=True)


if __name__=='__main__':unittest.main()
