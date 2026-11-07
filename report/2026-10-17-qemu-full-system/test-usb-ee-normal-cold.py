"""Functional EE adapter host/ABI/private build checks; no VM or physical IO."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
PREPARE=runpy.run_path(str(HERE/'prepare-ee-normal-wake-cold.py'))
BUILD=runpy.run_path(str(HERE/'usb-start-observe.py'))
MODEL=runpy.run_path(str(HERE/'usb-ee-normal-cold.py'))
HARNESS=r'''
#define USB_OBSERVE_HOST_TEST 1
#define USB_EE_NORMAL_COLD 1
#include "usb-start-observe.c"
#include <assert.h>
static pthread_mutex_t native_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t native_cond=PTHREAD_COND_INITIALIZER;
static unsigned entered,available,freed,allocations,sends,mode,source_value;
static uintptr_t message;
static int32_t native_queue(uint32_t q,uintptr_t h,uintptr_t cb,uintptr_t ctx){assert(q==EE_QUEUE&&cb==0&&ctx==0);if(h)*(uintptr_t *)h=0;return mode==1?-19:0;}
static int32_t native_recv(uint32_t q,uintptr_t o,int32_t t){assert(q==EE_QUEUE&&t==-1);pthread_mutex_lock(&native_lock);entered=1;pthread_cond_broadcast(&native_cond);while(!available)pthread_cond_wait(&native_cond,&native_lock);*(uintptr_t *)o=message;pthread_mutex_unlock(&native_lock);return 0;}
static uint32_t native_source(uintptr_t p){assert(p==message);return mode==4?0:source_value;}
static int32_t native_size(uintptr_t p){assert(p==message);return mode==5?11:12;}
static int32_t native_free(uint32_t o,uintptr_t p){assert(o==EE_QUEUE&&p==message);if(mode==10)return -28;free((void *)p);return 0;}
static int allocate_native(unsigned d,void **p,unsigned n,unsigned f){assert(d==EE_QUEUE&&n==12&&f==1);*p=malloc(n);assert(*p);message=(uintptr_t)*p;allocations++;return 0;}
static void set_source_native(void *p,unsigned s){assert((uintptr_t)p==message);source_value=s;}
static unsigned io_size(void *p){assert((uintptr_t)p==message);return 12;}
static unsigned io_source(void *p){assert((uintptr_t)p==message);return source_value;}
static int forbidden_release(unsigned d,void *p){(void)d;(void)p;assert(0);return -1;}
static void *receiver(void *arg){(void)arg;uintptr_t out=0;assert(ee_recv(EE_QUEUE,(uintptr_t)&out,-1)==0);assert(out==message);
 if(mode==6){ /* An alias never supplies the matching native size. */ ee_real_size(message+1); }
 else if(mode==7){assert(ee_size(message)==12);assert(ee_source(message)==source_value);}
 else {ee_source(message);ee_size(message);}
 assert(ee_free(EE_QUEUE,message)==(mode==10?-28:0));pthread_mutex_lock(&native_lock);freed=1;pthread_cond_broadcast(&native_cond);pthread_mutex_unlock(&native_lock);return NULL;}
static int send_native(unsigned d,void *p){assert(d==EE_QUEUE&&(uintptr_t)p==message);const uint8_t expected[12]={6,0,0xa3,0x20};assert(!memcmp(p,expected,12));sends++;
 pthread_mutex_lock(&native_lock);available=1;pthread_cond_broadcast(&native_cond);while(!freed)pthread_cond_wait(&native_cond,&native_lock);pthread_mutex_unlock(&native_lock);
 /* The free attempt has returned; neither adapter nor service may read p after send. */
 return mode==8?-28:0;}
static uintptr_t reader_native(uintptr_t x,uintptr_t output){assert(x==0x1122334455667788UL);struct ee_pair result={0x1234,1};
 ee_remember_register(0x11,0x22,app_base+(mode==2?0x35492b8:0x35492bc),result);
 assert(ee_wait_enter(app_base+0x35492cc,0x33445566));
 *(uint32_t *)output=mode==9?2:1;errno=71;return 0x8877665544332211UL;}
int main(int argc,char **argv){assert(argc==3);mode=(unsigned)strtoul(argv[2],0,10);logfd=open(argv[1],O_RDWR|O_CREAT|O_TRUNC,0600);memfd=open("/proc/self/mem",O_RDONLY);assert(logfd>=0&&memfd>=0);app_base=0x100000;ee_installed=1;
 ee_real_queue=native_queue;ee_real_recv=native_recv;ee_real_source=native_source;ee_real_size=native_size;ee_real_free=native_free;ee_cold_real_reader=reader_native;
 ee_cold_native_allocate=allocate_native;ee_cold_native_send=send_native;
 ee_cold_io=(struct full_imaging_io){ee_cold_allocate,forbidden_release,set_source_native,ee_cold_send,io_size,io_source,NULL};
 uintptr_t handle=99;assert(ee_queue(EE_QUEUE,mode==11?0:(uintptr_t)&handle,0,0)==(mode==1?-19:0));
 pthread_t thread;assert(!pthread_create(&thread,NULL,receiver,NULL));pthread_mutex_lock(&native_lock);while(!entered)pthread_cond_wait(&native_cond,&native_lock);pthread_mutex_unlock(&native_lock);
 uint32_t value=0;errno=37;
 if(mode==3){ /* A bare wait has no whole-reader invocation evidence. */ ee_remember_register(0x11,0x22,app_base+0x35492bc,(struct ee_pair){1,1});ee_wait_enter(app_base+0x35492cc,0x33445566);}
 else {assert(ee_cold_reader(0x1122334455667788UL,(uintptr_t)&value)==0x8877665544332211UL);assert(errno==71);}
 if(mode==1||mode==2||mode==3){assert(!allocations&&!sends&&!ee_cold_service);pthread_mutex_lock(&native_lock);available=1;message=(uintptr_t)malloc(12);assert(message);pthread_cond_broadcast(&native_cond);pthread_mutex_unlock(&native_lock);}
 assert(!pthread_join(thread,NULL));
 if(ee_cold_service){struct ee_nwc_snapshot s;assert(!ee_nwc_snapshot(ee_cold_service,&s));assert(allocations==1&&sends==1&&!s.selection.can_publish);assert(s.gate.consumer!=(uintptr_t)syscall(SYS_gettid));
 assert(s.reader_output==value);assert(s.retired==(mode==0||mode==7||mode==11));assert(s.pending==!s.retired);assert(s.free_returned==(mode!=4&&mode!=5&&mode!=6));
 if(mode==10)assert(s.free_rc==-28&&s.fault==EE_NWC_FREE&&s.pending);
 ee_cold_reading.active=1;ee_remember_register(1,2,app_base+0x35492bc,(struct ee_pair){1,1});ee_cold_wait(0x33);assert(allocations==1&&sends==1);
 assert(!ee_nwc_destroy(ee_cold_service,&s));ee_cold_service=NULL;}
 if(mode==10)free((void *)message); /* Fixture owner cleanup after an explicit failed-free handoff. */
 close(logfd);close(memfd);return 0;}
'''


def fixture_header():
    rows=bytearray(128)
    for i in range(2):
        off=i*64
        struct.pack_into('<III',rows,off+4,1,23 if i else 0,0)
        struct.pack_into('<H',rows,off+20,100);struct.pack_into('<H',rows,off+24,200)
        struct.pack_into('<II',rows,off+36,0x71c9+i,4 if i else 3);rows[off+44]=i
    raw=b'BIN!'+bytes(12)+struct.pack('<II',1,len(rows))+rows
    result=dict(backup_sha256=PREPARE['BACKUP_SHA'],cp_bank_sha256=PREPARE['BANK_SHA'],
                cp_bank_offset=970752,backup_bytes=123,unknown=[],
                records={0x1120000:raw,0x30162:struct.pack('<II',1,4)+bytes(56),0x30a01:bytes(4)})
    e=PREPARE['make_envelope'](result,b'\x0c\0\0\0',7)
    adc=bytearray(48);adc[0]=adc[46]=150
    return (PREPARE['render_header'](e)+'static const uint8_t ee_cold_state[32]={0};\n'
            +'static const uint8_t ee_cold_adc[48]={'+','.join(map(str,adc))+'};\n'
            +'static const uint8_t ee_cold_force=0,ee_cold_be9=0;\n'
            +'static const char ee_cold_input_sha256[]="host-fixture-only";\n'
            +'static const char ee_cold_model_sha256[]="host-model-fixture-only";\n')


class FunctionalAdapter(unittest.TestCase):
    def test_foreign_queue_actual_c_arguments_errno_once_bound_and_no_admission(self):
        observer=(HERE/'usb-ee-zero-observe.inc').read_text()
        emit='static int ee_emit('+observer.split('static int ee_emit(',1)[1].split('static int32_t ee_queue(',1)[0]
        queue='static int32_t ee_queue('+observer.split('static int32_t ee_queue(',1)[1].split('static int32_t ee_recv(',1)[0]
        fixture=r'''
#define _GNU_SOURCE
#define USB_EE_NORMAL_COLD 1
#define EE_QUEUE UINT32_C(0x80020002)
#define EE_ESSENTIAL_LIMIT 32u
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
static int logfd;
static unsigned ee_records,ee_essential,ee_capped,ee_console_records,ee_console_essential,ee_foreign_queue_calls;
static unsigned calls,cold_calls,reads;
static uint32_t expected_id;
static uintptr_t handle,expected_out;
static int32_t expected_rc;
static const uintptr_t callback=UINT64_C(0x1122334455667788),context=UINT64_C(0x8877665544332211);
static int readmem(uintptr_t p,void *out,size_t n){reads++;errno=EFAULT;if(p!=(uintptr_t)&handle)return 0;assert(n==sizeof handle);memcpy(out,&handle,n);return 1;}
static void ee_cold_queue(uintptr_t h,uintptr_t cb,uintptr_t ctx,int valid){assert(expected_id==EE_QUEUE&&h==0xabcdef&&cb==callback&&ctx==context&&valid);cold_calls++;errno=EIO;}
static int32_t native(uint32_t id,uintptr_t out,uintptr_t cb,uintptr_t ctx){assert(id==expected_id&&out==expected_out&&cb==callback&&ctx==context&&errno==37);calls++;if(out==(uintptr_t)&handle)handle=0xabcdef;errno=71;return expected_rc;}
static int32_t (*ee_real_queue)(uint32_t,uintptr_t,uintptr_t,uintptr_t)=native;
'''
        main=r'''
static void invoke(uint32_t id,uintptr_t out,int32_t rc){expected_id=id;expected_out=out;expected_rc=rc;unsigned before=calls;errno=37;assert(ee_queue(id,out,callback,context)==rc);assert(errno==71&&calls==before+1);}
int main(int argc,char **argv){assert(argc==3);logfd=open(argv[1],O_RDWR|O_CREAT|O_EXCL,0600);assert(logfd>=0);int saturated=argv[2][0]=='1';if(saturated)ee_records=384;
 for(unsigned i=0;i<8;i++)invoke(0x81000000+i,i==1?1:i==3?0:(uintptr_t)&handle,i==2?-19:0);
 assert(!cold_calls&&ee_essential==0&&ee_foreign_queue_calls==8&&reads==7);
 off_t before=lseek(logfd,0,SEEK_END);assert(before>0);
 for(unsigned i=0;i<1024;i++)invoke(0x82000000+i,1,0);
 assert(ee_foreign_queue_calls==8&&lseek(logfd,0,SEEK_END)==before&&!cold_calls&&reads==7);
 invoke(EE_QUEUE,(uintptr_t)&handle,0);assert(cold_calls==1&&ee_essential==2&&reads==8);
 assert(ee_records==(saturated?400:16));assert(ee_capped==(unsigned)saturated);assert(calls==1033);
 assert(!close(logfd));return 0;}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'queue.c';source.write_text(fixture+emit+queue+main)
            compiled=subprocess.run(['cc','-std=gnu11','-O2','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',str(source),'-o',str(root/'queue')],capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            for saturated in (0,1):
                trace=root/f'queue-{saturated}.log'
                result=subprocess.run([str(root/'queue'),str(trace),str(saturated)],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                lines=trace.read_text().splitlines()
                foreign=[line for line in lines if ' queue=0x8' in line and 'queue=0x80020002 ' not in line]
                self.assertEqual(len(foreign),0 if saturated else 16)
                self.assertEqual(sum('queue=0x80020002 ' in line for line in lines),2)
                if not saturated:
                    unknown=next(line for line in lines if 'QUEUE_RETURN ' in line and 'queue=0x81000001 ' in line)
                    self.assertIn('handle_out=0x1 handle=0 handle_read=0',unknown)
                    self.assertIn('rc=0 errno=71',unknown)
                    failed=next(line for line in lines if 'QUEUE_RETURN ' in line and 'queue=0x81000002 ' in line)
                    self.assertIn('handle=0 handle_read=0',failed);self.assertIn('rc=-19 errno=71',failed)

    def test_native_tid_gate_reader_output_and_freed_before_send_return(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'input.h').write_text(fixture_header());(root/'host.c').write_text(HARNESS)
            # alias case must return metadata without dereferencing its deliberately wrong pointer.
            text=(root/'host.c').read_text().replace('assert(p==message);return mode==5?11:12;', 'assert(p==message||(mode==6&&p==message+1));return mode==5?11:12;')
            (root/'host.c').write_text(text)
            command=['cc','-std=gnu11','-O1','-g','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',
                     '-Wno-unused-function','-Wno-unused-variable','-I',str(HERE),'-DUSB_EE_NORMAL_COLD_INPUT="'+str(root/'input.h')+'"',
                     str(root/'host.c'),str(HERE/'ee-normal-wake-cold.c'),str(HERE/'ee-capability-input.c'),'-ldl','-o',str(root/'host')]
            subprocess.run(command,check=True,capture_output=True,text=True,timeout=30)
            for mode in (0,1,2,3,4,5,6,7,8,9,10,11):
                run=subprocess.run([str(root/'host'),str(root/f'log-{mode}'),str(mode)],capture_output=True,text=True,timeout=10)
                self.assertEqual(run.returncode,0,f'mode={mode}\n'+run.stdout+run.stderr)
            text=(root/'log-0').read_text()
            self.assertIn('callback=0 context=0',text);self.assertIn('FUNCTIONAL_READER',text)
            self.assertIn('retired=1',text);self.assertIn('strict_can_publish=0',text)
            self.assertNotIn('ee-zero-publication',text)

    def test_model_rejects_unknown_inputs_and_generation_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'model.json'
            base=dict(schema=1,profile=MODEL['PROFILE'],generation=7,force_e0=0,be9bae_byte9=0,
                      stable_state_hex='00'*32,adc_hex='ff'*48)
            p.write_text(json.dumps(base));self.assertEqual(MODEL['load_model'](p)[0]['generation'],7)
            for key,value in [('generation',0),('generation',True),('force_e0',256),('be9bae_byte9',None),('adc_hex','00'),('profile',BUILD['EE_PROFILE'])]:
                p.write_text(json.dumps(dict(base,**{key:value})))
                with self.assertRaises(ValueError):MODEL['load_model'](p)
            p.write_text(json.dumps(dict(base,can_publish=True)))
            with self.assertRaises(ValueError):MODEL['load_model'](p)
            with self.assertRaises(ValueError):BUILD['prepare'](folder,observe_ee=True,ee_normal_cold={})

    def test_real_private_prepare_cross_build_bindings_and_drift(self):
        names=('EE_NWC_BACKUP','EE_NWC_VENDOR','EE_NWC_CP','EE_NWC_GUEST_LIBS','EE_NWC_NATIVE_ANALYSIS')
        if not all(os.environ.get(name) for name in names):
            self.skipTest('Provide exact private Backup/CP/vendor and guest library inputs')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);analysis=root/'analysis';(analysis/'root/simulation').mkdir(parents=True);(analysis/'root/lib').mkdir()
            native_analysis=Path(os.environ['EE_NWC_NATIVE_ANALYSIS'])
            shutil.copyfile(native_analysis/'root/simulation/menu-observe.so',analysis/'root/simulation/menu-observe.so')
            shutil.copyfile(native_analysis/'full-system.json',analysis/'full-system.json')
            for name in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so'):
                shutil.copyfile(Path(os.environ['EE_NWC_GUEST_LIBS'])/name,analysis/'root/lib'/name)
            model=dict(schema=1,profile=MODEL['PROFILE'],generation=7,force_e0=0,be9bae_byte9=0,
                       stable_state_hex='00'*176,
                       adc_hex='ffffffffffffffffffffffffffffffffffffffffffff7f00ffffffffffffffffffff2d00ffffffffffffffffffffffff')
            path=root/'model.json';path.write_text(json.dumps(model));path.chmod(0o600)
            inputs=dict(backup=Path(os.environ['EE_NWC_BACKUP']),cp=Path(os.environ['EE_NWC_CP']),
                        vendor=Path(os.environ['EE_NWC_VENDOR']),model=path)
            contract=BUILD['prepare'](analysis,ee_normal_cold=inputs)
            manifest=analysis/'full-system.json';prepared=json.loads(manifest.read_text());prepared['usb_start_observe']=contract;manifest.write_text(json.dumps(prepared))
            bindings=BUILD['validate'](analysis)
            self.assertEqual(contract['ee_observer']['profile'],MODEL['PROFILE'])
            self.assertTrue(contract['ee_observer']['publication_api']);self.assertFalse(contract['ee_observer']['ee_can_publish'])
            self.assertEqual(contract['ee_normal_cold']['generation'],7)
            self.assertEqual(contract['ee_normal_cold']['rows_bytes'],704)
            self.assertFalse(contract['ee_normal_cold']['stage_actual'])
            self.assertTrue(any(b['role']=='ee-private-model' for b in bindings))
            image=(analysis/'root/simulation/usb-start-observe.so').read_bytes()
            self.assertIn(MODEL['PROFILE'].encode(),image);self.assertNotIn(BUILD['EE_PROFILE'].encode(),image)
            host=root/'actual-host.c';host.write_text(HARNESS)
            subprocess.run(['cc','-std=gnu11','-O1','-g','-pthread','-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',
                            '-Wno-unused-function','-Wno-unused-variable','-I',str(HERE),
                            '-DUSB_EE_NORMAL_COLD_INPUT="'+contract['ee_normal_cold']['private_header']+'"',
                            str(host),str(HERE/'ee-normal-wake-cold.c'),str(HERE/'ee-capability-input.c'),'-ldl','-o',str(root/'actual-host')],
                           check=True,capture_output=True,text=True,timeout=30)
            consumed=subprocess.run([str(root/'actual-host'),str(root/'actual.log'),'0'],capture_output=True,text=True,timeout=10)
            self.assertEqual(consumed.returncode,0,consumed.stdout+consumed.stderr)
            trace=(root/'actual.log').read_text();self.assertIn('current=3,6 reason=1 raw=0',trace);self.assertIn('retired=1',trace)
            original=path.read_bytes();path.write_bytes(original+b' ')
            with self.assertRaisesRegex(ValueError,'private input identity drift'):BUILD['validate'](analysis)
            path.write_bytes(original)
            h=analysis/'private-ee-normal-cold-input.h';original=h.read_bytes();h.write_bytes(original+b'\n')
            with self.assertRaisesRegex(ValueError,'private input identity drift'):BUILD['validate'](analysis)
            h.write_bytes(original)
            contract['ee_normal_cold']['generation']=0;manifest.write_text(json.dumps(dict(usb_start_observe=contract)))
            with self.assertRaisesRegex(ValueError,'source/profile identity drift'):BUILD['validate'](analysis)

    def test_cli_passes_only_explicit_complete_functional_inputs(self):
        control=runpy.run_path(str(HERE/'usb-control-start.py'))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);calls=[]
            ap=dict(control['AP'],PERSISTENT={'fresh_output':lambda *a:root},save=lambda *a:None)
            ap['main']=lambda *a,**kw:self.fail('prepare-only reached VM entry')
            argv=[value for name in ('instance','runtime','module','qemu-build','output') for value in ('--'+name,str(root/name))]
            flags=[value for name in ('ee-normal-cold-model','ee-backup','ee-vendor','ee-cp') for value in ('--'+name,str(root/name))]
            with patch.dict(control['main'].__globals__,AP=ap,prepare_helpers=lambda *a,**kw:calls.append(kw) or root/'helpers'):
                self.assertEqual(control['main']([*argv,*flags,'--seconds','120','--observe-start','--prepare-only']),0)
                self.assertEqual(calls,[dict(observe_start=True,observe_ee=False,ee_normal_cold=dict(model=root/'ee-normal-cold-model',backup=root/'ee-backup',vendor=root/'ee-vendor',cp=root/'ee-cp'))])
                for suffix in (['--observe-start','--prepare-only','--observe-ee'],['--prepare-only'],['--observe-start','--prepare-only','--seconds','121']):
                    with self.assertRaises(SystemExit) as error:control['main']([*argv,*flags,'--seconds','120',*suffix])
                    self.assertEqual(error.exception.code,2)
                self.assertEqual(len(calls),1)

    def test_source_proven_reader_and_transport_bytes(self):
        ap=os.environ.get('A7C2_EE_AP');uipc=os.environ.get('A7C2_EE_UIPC')
        if not ap or not uipc:self.skipTest('Exact private AP/UIPC inputs not supplied')
        def window(path,va,n):
            data=Path(path).read_bytes();phoff=struct.unpack_from('<Q',data,32)[0]
            for i in range(struct.unpack_from('<H',data,56)[0]):
                k,_,off,start,_,size,_,_=struct.unpack_from('<IIQQQQQQ',data,phoff+56*i)
                if k==1 and start<=va and va+n<=start+size:return data[off+va-start:off+va-start+n]
            self.fail('Unmapped original source range')
        self.assertEqual(hashlib.sha256(Path(ap).read_bytes()).hexdigest(),BUILD['DSOS']['/usr/lib/appFw.so']['sha256'])
        self.assertEqual(hashlib.sha256(Path(uipc).read_bytes()).hexdigest(),BUILD['EE_DSO']['/usr/lib/libosal_uipc.so']['sha256'])
        self.assertEqual(hashlib.sha256(window(ap,0x3549218,0x110)).hexdigest(),'1f30cbce7adcbe1987d365e81f08769cda1f75c5a5ca35d1eb790be1cc6efd43')
        self.assertEqual(window(ap,0x3549218,16),struct.pack('<4I',0xd11c83ff,0xb002de60,0xa9ba7bfd,0x910003fd))
        for va,words in [(0x67b0,(0xa9ac7bfd,0x910003fd,0xa90153f3,0xa9025bf5)),
                         (0x5e60,(0xa9ab7bfd,0x910003fd,0xa90363f7,0x72003817)),
                         (0x7e20,(0xb81f4001,0xd65f03c0,0xb85f4000,0xd65f03c0))]:
            self.assertEqual(window(uipc,va,16),struct.pack('<4I',*words))


if __name__=='__main__':unittest.main(verbosity=2)
