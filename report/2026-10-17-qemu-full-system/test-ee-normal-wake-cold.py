"""Compile and exercise service ownership/concurrency, plus finite helper guards."""
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
PREPARE=runpy.run_path(str(HERE/'prepare-ee-normal-wake-cold.py'))

class ColdServiceTests(unittest.TestCase):
    def test_host_and_sanitizers(self):
        with tempfile.TemporaryDirectory(prefix='ee-normal-cold-') as directory:
            for name,flags in [('strict',['-O2','-fstrict-aliasing']),
                               ('asan-ubsan',['-O1','-g','-fsanitize=address,undefined',
                                              '-fno-omit-frame-pointer','-no-pie'])]:
                target=Path(directory)/name
                subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pthread',*flags,
                                str(HERE/'ee-normal-wake-cold.c'),str(HERE/'ee-capability-input.c'),
                                str(HERE/'test-ee-normal-wake-cold.c'),'-o',str(target)],check=True)
                subprocess.run([str(target)],check=True,timeout=30,
                               env={**os.environ,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1',
                                    'UBSAN_OPTIONS':'halt_on_error=1'})
    def test_aarch64_compile(self):
        cc=shutil.which('aarch64-linux-gnu-gcc')
        if not cc:self.skipTest('Cross compiler unavailable')
        with tempfile.TemporaryDirectory(prefix='ee-normal-cross-') as directory:
            subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-fPIC','-pthread',
                            '-c',str(HERE/'ee-normal-wake-cold.c'),'-o',str(Path(directory)/'cold.o')],check=True)
    def result(self):
        rows=bytearray(128)
        for offset in (0,64):struct.pack_into('<I',rows,offset+4,1)
        keymap=b'BIN!'+bytes(12)+struct.pack('<II',1,128)+rows
        return dict(backup_sha256=PREPARE['BACKUP_SHA'],cp_bank_sha256=PREPARE['BANK_SHA'],
                    cp_bank_offset=970752,backup_bytes=123,unknown=[],
                    records={0x1120000:keymap,0x30162:bytes(64),0x30a01:bytes(4)})
    def test_envelope_and_generated_header(self):
        e=PREPARE['make_envelope'](self.result(),b'\x0c\0\0\0',7)
        self.assertEqual(e['object_10bf'],1)
        self.assertEqual(bytes.fromhex(e['records']['00030162']['hex']),bytes(64))
        for flag in ('original_cp_runtime_consumed','actual_native_registered',
                     'notification_published','current_adc_supplied'):self.assertFalse(e[flag])
        with tempfile.TemporaryDirectory(prefix='ee-normal-envelope-') as directory:
            path=Path(directory)/'input.h'
            PREPARE['private_write'](path,PREPARE['render_header'](e).encode())
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):PREPARE['private_write'](path,b'bad')
            src=Path(directory)/'check.c'
            src.write_text('#include "input.h"\nint main(void){return ee_nwc_prepared_assets.generation!=7;}\n')
            binary=Path(directory)/'check'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HERE),
                            str(src),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
    def test_actual_current_bank(self):
        backup=os.environ.get('EE_NWC_BACKUP');vendor=os.environ.get('EE_NWC_VENDOR')
        if not backup or not vendor:
            self.skipTest('Provide private EE_NWC_BACKUP and EE_NWC_VENDOR for fixed-current-bank test')
        import ctypes as C
        import itertools
        input_test=runpy.run_path(str(HERE/'test-ee-capability-input.py'))
        envelope=PREPARE['prepare'](backup,vendor,7)
        rows=bytes.fromhex(envelope['rows_hex'])
        channels=[]
        for key in (0x71c9,0x71ca):
            matching=[struct.unpack_from('<I',rows,i+8)[0] for i in range(0,len(rows),64)
                      if struct.unpack_from('<I',rows,i+36)[0]==key]
            self.assertTrue(matching,'Actual keymap lacks required key')
            channels.append(matching[-1])
        # Platform test positions come only from the keymap ADC ranges, never Backup keys.
        levels=[]
        for channel in channels:
            levels.append(sorted({65535}|{(struct.unpack_from('<H',rows,i+20)[0]+
                                           struct.unpack_from('<H',rows,i+24)[0])//2
                          for i in range(0,len(rows),64)
                          if struct.unpack_from('<I',rows,i+8)[0]==channel}))
        with tempfile.TemporaryDirectory(prefix='ee-normal-actual-') as directory:
            work=Path(directory);library=work/'input.so'
            subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC',
                            str(HERE/'ee-capability-input.c'),'-o',str(library)],check=True)
            lib=C.CDLL(str(library));U8=C.c_uint8;Sample=input_test['Sample'];array=input_test['array']
            lib.ee_adc_consume.argtypes=[C.POINTER(U8),C.c_size_t,C.POINTER(U8),C.c_size_t,
                                        C.c_uint,C.POINTER(Sample),C.c_uint64,C.c_uint64]
            lib.ee_adc_read_key.argtypes=[C.POINTER(U8),C.c_size_t,C.POINTER(U8),C.c_size_t,
                                         C.c_uint32,C.POINTER(C.c_uint32)]
            chosen=None
            for positions in itertools.product(*levels):
                adc=[65535]*24
                for channel,value in zip(channels,positions):adc[channel]=value
                raw=struct.pack('<24H',*adc);r=array(rows);state=array(bytes(len(rows)//4))
                buffers=[array(raw[:24]),array(raw[24:])]
                samples=(Sample*2)(*[Sample(buffers[i],24,100,7,i,1,1,1) for i in range(2)])
                self.assertEqual(lib.ee_adc_consume(r,len(r),state,len(state),1,samples,100,5),0)
                current=[C.c_uint32(),C.c_uint32()]
                status=[lib.ee_adc_read_key(r,len(r),state,len(state),key,C.byref(value))
                        for key,value in zip((0x71c9,0x71ca),current)]
                if status==[0,0]:
                    chosen=(raw,[value.value for value in current]);break
            self.assertIsNotNone(chosen,'No known CURRENT in finite model-defined ADC positions')
            raw,current=chosen
            PREPARE['private_write'](work/'actual-input.h',PREPARE['render_header'](envelope).encode())
            code=r'''#include "actual-input.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
static void *message;static unsigned src,allocated,sent;
static int alloc(unsigned d,void **m,unsigned n,unsigned f){assert(d==EE_NWC_DEST&&n==12&&f==1);*m=message=malloc(n);++allocated;return message?0:-1;}
static int release(unsigned d,void *m){(void)d;(void)m;assert(0);return -1;}
static void source(void *m,unsigned s){assert(m==message);src=s;}
static int send(unsigned d,void *m){const unsigned char wire[12]={6,0,0xa3,0x20};assert(d==EE_NWC_DEST&&m==message&&!memcmp(m,wire,12)&&src==EE_NWC_SOURCE);++sent;return 0;}
static unsigned size(void *m){assert(m==message);return 12;}
static unsigned get_source(void *m){assert(m==message);return src;}
int main(void){
 struct full_imaging_io io={alloc,release,source,send,size,get_source,NULL};
 struct ee_nwc *s;struct ee_nwc_snapshot snapshot;
 struct ee_nwc_assets a=ee_nwc_prepared_assets;
 unsigned char state[sizeof(ee_nwc_prepared_rows)/4]={0};
 unsigned char adc[48]={ADC_BYTES};
 struct ee_nwc_initial in={getpid(),7,15,15,"model-defined:actual-bank-host-adc-positions-v1",0,0,state,sizeof(state)};
 struct ee_adc_sample samples[2]={{adc,24,100,7,0,1,1,1},{adc+24,24,100,7,1,1,1,1}};
 struct ee_nwc_gate gate={getpid(),7,0x100,0x200,0x300,10,11,1,1,1,0x20a3,0};
 int rc;a.pid=getpid();
 assert(!ee_nwc_create(&s,EE_NWC_PROFILE,getpid(),7,&io));assert(!ee_nwc_configure(s,&a,&in));assert(!ee_nwc_arm(s,&gate));
 rc=ee_nwc_trigger(s,7,samples,100,5);assert(!ee_nwc_snapshot(s,&snapshot));
 assert(snapshot.current[0]==EXPECTED_A&&snapshot.current[1]==EXPECTED_B);
 assert(snapshot.selection.can_publish==0&&!snapshot.retired);
 if(snapshot.selection.decision==EE_NORMAL_SPINAL_OFF){assert(rc==0&&allocated==1&&sent==1&&snapshot.pending);}
 else{assert(rc==EE_NWC_NO_DELIVERY&&!allocated&&!sent);}
 printf("actual-bank host CURRENT=%u,%u decision=%u reason=%u; native/AP/CP execution=false\n",snapshot.current[0],snapshot.current[1],snapshot.selection.decision,snapshot.selection.reason);
 assert(!ee_nwc_destroy(s,&snapshot));free(message);return 0;
}
'''
            code=code.replace('ADC_BYTES',','.join(str(x) for x in raw))
            code=code.replace('EXPECTED_A',str(current[0])+'u').replace('EXPECTED_B',str(current[1])+'u')
            (work/'actual.c').write_text(code)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O1','-g','-pthread',
                            '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',
                            '-I',str(HERE),str(work/'actual.c'),str(HERE/'ee-normal-wake-cold.c'),
                            str(HERE/'ee-capability-input.c'),'-o',str(work/'actual')],check=True)
            subprocess.run([str(work/'actual')],check=True,timeout=30)
            print(json.dumps(dict(scope='host fixture only',adc_hex=raw.hex(),current=current,
                                  initial_known=15,model_defined=15,generation=7,
                                  actual_native_registered=False,original_cp_runtime_consumed=False)))

    def test_envelope_refuses_unknown_and_mixed_assets(self):
        for value in (0,-1,True,2**64):
            with self.assertRaises(ValueError):PREPARE['make_envelope'](self.result(),bytes(4),value)
        for field,value in [('backup_sha256','0'*64),('cp_bank_sha256','0'*64),
                            ('cp_bank_offset',0),('unknown',[{'key':'0092001c'}])]:
            result=self.result();result[field]=value
            with self.assertRaises(ValueError):PREPARE['make_envelope'](result,bytes(4),7)
        with self.assertRaises(ValueError):PREPARE['make_envelope'](self.result(),bytes(3),7)
        for key in (0x30162,0x30a01,0x1120000):
            result=self.result();result['records'][key]=b'bad'
            with self.assertRaises(ValueError):PREPARE['make_envelope'](result,bytes(4),7)

if __name__=='__main__':unittest.main(verbosity=2)
