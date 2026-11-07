"""Host and optional original-Thumb differential tests; all fixtures stay private."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import random
import runpy
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CONTRACT = runpy.run_path(str(HERE/'ee-capability-contract.py'))
U8 = C.c_uint8

class Sample(C.Structure):
    _fields_ = [('data', C.POINTER(U8)), ('bytes', C.c_size_t), ('sampled_at', C.c_uint64),
                ('generation', C.c_uint64), ('selector', C.c_uint), ('known', C.c_uint),
                ('calibrated', C.c_uint), ('virtual_input_state', C.c_uint)]
class Normal(C.Structure):
    _fields_ = [('known', C.c_uint), ('current', C.c_uint32*2), ('backup', C.POINTER(U8)),
                ('backup_bytes', C.c_size_t), ('policy', C.c_uint32), ('object_110c', C.c_uint32),
                ('force', U8), ('be9', U8), ('object_10bf', U8)]
class Result(C.Structure):
    _fields_ = [(name, C.c_uint) for name in ('decision', 'unknown', 'reason', 'raw_valid', 'raw', 'publish')]

def array(data):
    return (U8*len(data)).from_buffer_copy(data)

def rows_fixture(n=2):
    rows=bytearray(64*n)
    for i in range(n):
        struct.pack_into('<I', rows, i*64+8, i*23)
        struct.pack_into('<H', rows, i*64+20, 100)
        struct.pack_into('<H', rows, i*64+24, 200)
        struct.pack_into('<IIHBB', rows, i*64+36, 0x71c9+i, 3+i, i, 0, 0)
    return rows

class InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work=tempfile.TemporaryDirectory(prefix='ee-input-')
        cls.build=Path(cls.work.name)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O2','-shared','-fPIC',
                        str(HERE/'ee-capability-input.c'),'-o',str(cls.build/'input.so')],check=True)
        cls.lib=C.CDLL(str(cls.build/'input.so'))
        cls.lib.ee_adc_consume.argtypes=[C.POINTER(U8),C.c_size_t,C.POINTER(U8),C.c_size_t,C.c_uint,C.POINTER(Sample),C.c_uint64,C.c_uint64]
        cls.lib.ee_adc_read_key.argtypes=[C.POINTER(U8),C.c_size_t,C.POINTER(U8),C.c_size_t,C.c_uint32,C.POINTER(C.c_uint32)]
        cls.lib.ee_normal_select.argtypes=[C.POINTER(Normal)];cls.lib.ee_normal_select.restype=Result
    @classmethod
    def tearDownClass(cls):
        cls.work.cleanup()
    def consume(self, rows, state, adc=None, mutate=None):
        adc=adc if adc is not None else [150]*24
        r,s=array(rows),array(state)
        buffers=[array(struct.pack('<12H',*adc[i*12:i*12+12])) for i in range(2)]
        samples=(Sample*2)(*[Sample(buffers[i],24,100,7,i,1,1,1) for i in range(2)])
        if mutate:mutate(samples)
        status=self.lib.ee_adc_consume(r,len(r),s,len(s),1,samples,100,5)
        return status,bytes(r),bytes(s)
    def test_guards_and_readback(self):
        rows=rows_fixture();state=bytes(32)
        rc,r,s=self.consume(rows,state)
        self.assertEqual(rc,0)
        for i in range(2):
            value=C.c_uint32(0xeeeeeeee)
            self.assertEqual(self.lib.ee_adc_read_key(array(r),len(r),array(s),len(s),0x71c9+i,C.byref(value)),0)
            self.assertEqual(value.value,3+i)
        for field,value,expected in [('selector',1,2),('bytes',23,2),('known',0,1),('calibrated',0,1),
                                     ('virtual_input_state',0,1),('sampled_at',94,3),('sampled_at',101,3),('generation',8,2)]:
            rc,r,s=self.consume(rows,state,mutate=lambda a:setattr(a[0],field,value))
            self.assertEqual((rc,r,s),(expected,bytes(rows),state),field)
        bad=bytearray(rows);struct.pack_into('<I',bad,8,24)
        self.assertEqual(self.consume(bad,state)[0],2)
        value=C.c_uint32(99)
        self.assertEqual(self.lib.ee_adc_read_key(array(rows),len(rows),array(state),len(state),0x71c9,C.byref(value)),1)
        huge=C.c_size_t(-1).value
        self.assertEqual(self.lib.ee_adc_consume(array(rows),huge,array(state),32,1,None,100,5),1)
    def test_normal(self):
        backup=array(struct.pack('<2I',3,4)+bytes(56))
        n=Normal(63,(C.c_uint32*2)(3,4),backup,64,0,0,0,0,1)
        self.assertEqual(self.lib.ee_normal_select(C.byref(n)).decision,4)
        n.current[1]=2
        self.assertEqual(self.lib.ee_normal_select(C.byref(n)).decision,4)
        for policy,reason in [(1,2),(2,3),(3,5),(4,255)]:
            n.policy=policy;r=self.lib.ee_normal_select(C.byref(n));self.assertEqual((r.decision,r.reason,r.raw_valid,r.raw,r.publish),(3,reason,1,0,0))
        n.policy=0;n.current[0]=8
        self.assertEqual(self.lib.ee_normal_select(C.byref(n)).reason,1)
        n.be9=1;self.assertEqual(self.lib.ee_normal_select(C.byref(n)).reason,4)
        n.force=4;self.assertEqual(self.lib.ee_normal_select(C.byref(n)).reason,255)
        for bit in (1,2,4,8,16,32):
            n.known=63^bit;r=self.lib.ee_normal_select(C.byref(n));self.assertEqual((r.decision,r.unknown,r.raw_valid,r.publish),(0,bit|64,0,0))
        n.known=63;n.current[0]=0xffffffff
        self.assertEqual(self.lib.ee_normal_select(C.byref(n)).unknown,65)
        n.current[0]=3;n.backup_bytes=63
        self.assertEqual(self.lib.ee_normal_select(C.byref(n)).decision,1)
    def test_keymap_parser(self):
        rows=rows_fixture();struct.pack_into('<I',rows,4,1);struct.pack_into('<I',rows,68,1)
        blob=b'BIN!'+struct.pack('<5I',152,1,152,1,128)+rows
        self.assertEqual(CONTRACT['parse_keymap'](blob),{1:bytes(rows)})
        for broken in (blob[:23],blob[:100],blob[:20]+struct.pack('<I',127)+rows,blob[:16]+b'\xff'*4+blob[20:]):
            with self.assertRaises(ValueError):CONTRACT['parse_keymap'](broken)
    def test_host_boundaries(self):
        rows=rows_fixture();state=bytearray(32);state[15]=0xa5;state[31]=0x5a
        rc,r,s=self.consume(rows,state)
        self.assertEqual((rc,s[15],s[31]),(0,0xa5,0x5a))
        for offset,value in ((12,101),(12,155),(14,2),(28,101),(30,2)):
            bad=bytearray(state);bad[offset]=value
            self.assertEqual(self.consume(rows,bad),(2,bytes(rows),bytes(bad)))
        for offset,value in ((8,24),(20,201),(46,2)):
            bad=bytearray(rows);bad[offset]=value
            if offset==46:bad[44]=2
            self.assertEqual(self.consume(bad,state),(2,bytes(bad),bytes(state)))
        for bad in (rows[:-1],bytearray()):
            self.assertEqual(self.consume(bad,state)[0],2)
        self.assertEqual(self.consume(rows,state[:-1])[0],2)
        self.assertEqual(self.consume(rows,state,mutate=lambda a:setattr(a[0],'data',C.POINTER(U8)()))[0],2)
        self.assertEqual(self.lib.ee_adc_consume(array(rows),128,array(state),32,0,None,100,5),1)
        # Sizes, not trailing zero-filled storage, select records from the BIN! resource.
        grouped=bytearray(rows)
        struct.pack_into('<I',grouped,4,1);struct.pack_into('<I',grouped,68,1)
        blob=b'BIN!'+bytes(12)+struct.pack('<II',1,len(grouped))+grouped+bytes(64)
        self.assertEqual(CONTRACT['parse_keymap'](blob),{1:bytes(grouped)})
        for broken in (blob[:20]+struct.pack('<I',192)+grouped,blob[:20]+struct.pack('<I',65)+grouped):
            with self.assertRaises(ValueError):CONTRACT['parse_keymap'](broken)
        backup=array(bytes(64));n=Normal(63,(C.c_uint32*2)(0,0),backup,64,0,0,0,0,1)
        for field,value in (('known',127),('object_110c',1),('object_10bf',0)):
            setattr(n,field,value);r=self.lib.ee_normal_select(C.byref(n))
            self.assertEqual((r.raw_valid,r.publish),(0,0));setattr(n,field,{'known':63,'object_110c':0,'object_10bf':1}[field])
        self.assertEqual(self.lib.ee_normal_select(None).publish,0)
    def test_original_normal_thumb(self):
        cp=os.environ.get('EE_CP')
        if not cp:self.skipTest('Provide private EE_CP and existing Unicorn environment')
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R4,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
        CONTRACT['verify_cp'](cp)
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(0x100000,0x3000000)
        u.mem_write(0x108000,Path(cp).read_bytes())
        supplied={};observed=[];be9=0x2d00000
        u.mem_write(0x1a7e85c,struct.pack('<I',be9))
        def hook(uc,address,size,unused):
            if address in (0x424b4e,0x424b86):
                observed.append((address,uc.reg_read(UC_ARM_REG_R4)));uc.emu_stop();return
            r0,r1,r2=[uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
            if address==0xac3cd0:uc.mem_write(r0,struct.pack('<2I',*supplied['current']))
            elif address==0x42506c:uc.mem_write(r0,supplied['backup'])
            elif address==0x510728:
                self.assertEqual((r0,r2),(0x30a01,4));uc.mem_write(r1,struct.pack('<I',supplied['policy']))
            elif address not in (0x424c2c,0xb4457a):return
            uc.reg_write(UC_ARM_REG_R0,0);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE,hook)
        cases=[(3,b,3,d,0,0,0) for b in (0,1,2,3,4,5,6,7,0xfffffffe)
               for d in (0,1,2,3,4,5,6,7,0xfffffffe)]
        cases.extend([(a,4,c,4,policy,force,flag) for a,c in ((3,3),(3,8),(0xfffffffe,0xfffffffe))
                      for policy in range(5) for force in (0,4) for flag in (0,1)])
        for a,b,c,d,policy,force,flag in cases:
            data=struct.pack('<2I',c,d)+bytes(56);backup=array(data)
            supplied.update(current=(a,b),backup=data,policy=policy)
            n=Normal(63,(C.c_uint32*2)(a,b),backup,64,policy,0,force,flag,1)
            expected=self.lib.ee_normal_select(C.byref(n));observed.clear()
            u.mem_write(be9+9,bytes([flag]));u.mem_write(0x1a533a4+0xe0,bytes([force]))
            u.reg_write(UC_ARM_REG_SP,0x2f00000);u.reg_write(UC_ARM_REG_LR,0x3000001)
            u.emu_start(0x424abd,0x3000000,count=2000)
            self.assertEqual(observed,[(0x424b4e if expected.raw_valid else 0x424b86,expected.reason)])
            self.assertEqual((expected.raw,expected.publish),(0,0))
        print(f'NormalWake Thumb differential: {len(cases)} supplied-input cases; stopped before notification/transport')
    def test_assets(self):
        cp=os.environ.get('EE_CP');backup=os.environ.get('EE_BACKUP');vendor=os.environ.get('EE_VENDOR')
        if not all((cp,backup,vendor)):self.skipTest('Provide private EE_CP/EE_BACKUP/EE_VENDOR')
        self.assertEqual(CONTRACT['verify_cp'](cp)['windows_verified'],13)
        path=Path(backup);digest=hashlib.sha256(path.read_bytes()).hexdigest()
        result=CONTRACT['read_backup'](path,digest,vendor,cp_bank_offset=0xed000)
        self.assertEqual(len(result['records'][0x01120000]),4632)
        self.assertEqual(len(CONTRACT['parse_keymap'](result['records'][0x01120000])[1]),11*64)
        self.assertEqual(result['unknown'],[])
        self.assertIn(struct.pack('<I',0x71c9),result['records'][0x01120000])
        self.assertEqual(len(result['records'][0x30162]),64)
        with self.assertRaises(ValueError):CONTRACT['read_backup'](path,digest,vendor,cp_bank_offset=0)
        with self.assertRaises(ValueError):CONTRACT['read_backup'](path,'0'*64,vendor,cp_bank_offset=0xed000)
        producer=json.loads((HERE/'runtime/analysis/ee-3003-check/ee-cap-cp-notification-producer-original.json').read_bytes())
        binary=Path(cp).read_bytes();count=0
        for block in producer['instruction_ranges'].values():
            for insn in block['instructions']:
                start=int(insn['va'],16)-0x108000;expected=bytes.fromhex(insn['bytes'])
                self.assertEqual(binary[start:start+len(expected)],expected);count+=1
        self.assertEqual(count,50)
    def test_sanitizers(self):
        code=r'''#include "ee-capability-input.h"
#include <assert.h>
#include <string.h>
#include <stdint.h>
int main(void) {
 uint8_t r[128]={0},s[32]={0},a[24]={0},b[24]={0},backup[64]={0};
 struct ee_adc_sample in[2]={{a,24,100,1,0,1,1,1},{b,24,100,1,1,1,1,1}};
 struct ee_normal_inputs n={0};struct ee_normal_result out;uint32_t v;
 unsigned i;r[20]=100;r[24]=200;r[36]=0xc9;r[37]=0x71;r[40]=7;r[46]=1;
 memcpy(r+64,r,64);r[72]=23;r[100]=0xca;
 for(i=0;i<600;i++){a[0]=(uint8_t)(i%256);b[22]=a[0];assert(ee_adc_consume(r,128,s,32,1,in,100,1)==0);}
 assert(ee_adc_read_key(r,128,s,32,0x71c9,&v)==0);
 assert(ee_adc_consume(r,SIZE_MAX,s,32,1,in,100,1)==EE_INPUT_INVALID);
 in[1].bytes=23;assert(ee_adc_consume(r,128,s,32,1,in,100,1)==EE_INPUT_INVALID);
 n.known=63;n.backup_00030162=backup;n.backup_bytes=64;n.object_10bf=1;
 for(i=0;i<512;i++){n.current[0]=i;n.current[1]=i^7;n.policy_00030a01=i%5;out=ee_normal_select(&n);assert(out.can_publish==0);}
 return 0;
}'''
        main=self.build/'check.c';main.write_text(code)
        binary=self.build/'asan'
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-g','-I',str(HERE),str(main),str(HERE/'ee-capability-input.c'),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    def test_original_thumb(self):
        cp=os.environ.get('EE_CP')
        if not cp:self.skipTest('Provide private EE_CP and existing Unicorn environment')
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
        CONTRACT['verify_cp'](cp)
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(0x100000,0x3000000)
        binary=Path(cp).read_bytes();u.mem_write(0x108000,binary)
        MAP,STATE,MSG,OUT,STACK,STOP=0x2d00000,0x2c00000,0x2e00000,0x2b00000,0x2f00000,0x3000000
        values={'adc':bytes(48),'backup':bytes(64)};calls=[]
        def hook(uc,address,size,unused):
            if address==STOP:uc.emu_stop();return
            regs=[uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
            r0,r1,r2,r3=regs
            if address==0x565204:
                self.assertEqual((r0,r2,r3),(0x720018,0x28,1));uc.mem_write(r1,struct.pack('<I',MSG))
            elif address==0xbec01c:
                selector=uc.mem_read(MSG+4,1)[0];self.assertEqual(r0,0x720018);self.assertEqual(uc.mem_read(MSG,4),struct.pack('<I',0xfff1));self.assertIn(selector,(0,1));calls.append(selector)
                uc.mem_write(MSG+6,values['adc'][selector*24:selector*24+24])
            elif address==0x61e60c:uc.mem_write(r0,bytes(uc.mem_read(r1,r2)))
            elif address==0x565300:self.assertEqual((r0,r1),(0x720018,MSG))
            elif address==0x510728:
                self.assertEqual((r0,r2),(0x30162,64));uc.mem_write(r1,values['backup']);calls.append('backup-copy')
            else:return
            uc.reg_write(UC_ARM_REG_R0,0);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE,hook)
        def run(address,r0=0):
            u.reg_write(UC_ARM_REG_R0,r0);u.reg_write(UC_ARM_REG_SP,STACK);u.reg_write(UC_ARM_REG_LR,STOP|1)
            u.emu_start(address|1,STOP,count=20000)
            self.assertEqual(u.reg_read(UC_ARM_REG_PC),STOP)
        rng=random.Random(0x20a3)
        cases=[]
        for adc in (0,99,100,101,199,200,201,65535):
            for count in (-100,-1,0,1,100):cases.append((adc,count))
        for _ in range(216):cases.append((rng.randrange(65536),rng.randint(-100,100)))
        for index,(adc,count) in enumerate(cases):
            rows=rows_fixture();state=bytearray(32)
            for i in range(2):
                rows[i*64+46]=(index+i)%5;rows[i*64+47]=(index//5)%2
                state[i*16+12]=count&255;state[i*16+13]=255 if index%3==0 else index%255
                struct.pack_into('<I',state,i*16+8,0x12345678+i)
            samples=[adc]*24;rc,cr,cs=self.consume(rows,state,samples);self.assertEqual(rc,0)
            values['adc']=struct.pack('<24H',*samples);calls.clear()
            u.mem_write(MAP,bytes(rows));u.mem_write(STATE,bytes(state))
            u.mem_write(0x1a0b8e8,struct.pack('<II',MAP,2));u.mem_write(0x1a0b8dc,struct.pack('<I',STATE))
            run(0x4245d0)
            self.assertEqual(calls,[0,1]);self.assertEqual(bytes(u.mem_read(MAP,128)),cr,f'rows case {index}');self.assertEqual(bytes(u.mem_read(STATE,32)),cs,f'state case {index}')
        actual_cases=0
        if os.environ.get('EE_BACKUP') and os.environ.get('EE_VENDOR'):
            source=Path(os.environ['EE_BACKUP']);digest=hashlib.sha256(source.read_bytes()).hexdigest()
            actual=CONTRACT['read_backup'](source,digest,os.environ['EE_VENDOR'],cp_bank_offset=0xed000)
            rows=CONTRACT['parse_keymap'](actual['records'][0x01120000])[1]
            n=len(rows)//64;state=bytes(n*16)
            # Sequential boundary/jitter inputs come from virtual input state, never Backup keys.
            for phase in range(32):
                samples=[65535]*24
                for j in range(n):
                    channel=struct.unpack_from('<I',rows,64*j+8)[0]
                    low=struct.unpack_from('<H',rows,64*j+20)[0]
                    high=struct.unpack_from('<H',rows,64*j+24)[0]
                    samples[channel]=max(0,min(65535,[low-1,low,low+1,high-1,high,high+1,low,high][phase%8]))
                rc,cr,cs=self.consume(rows,state,samples);self.assertEqual(rc,0)
                values['adc']=struct.pack('<24H',*samples);calls.clear()
                u.mem_write(MAP,rows);u.mem_write(STATE,state)
                u.mem_write(0x1a0b8e8,struct.pack('<II',MAP,n));u.mem_write(0x1a0b8dc,struct.pack('<I',STATE))
                run(0x4245d0)
                self.assertEqual(calls,[0,1]);self.assertEqual(bytes(u.mem_read(MAP,len(rows))),cr)
                self.assertEqual(bytes(u.mem_read(STATE,len(state))),cs)
                for key in (0x71c9,0x71ca):
                    keyvalue=C.c_uint32(0)
                    rc=self.lib.ee_adc_read_key(array(cr),len(cr),array(cs),len(cs),key,C.byref(keyvalue))
                    self.assertIn(rc,(0,1))
                    u.mem_write(OUT,struct.pack('<IIIII',0,key,0,0xdddddddd,0))
                    run(0xac3ae0,OUT)
                    self.assertEqual(u.reg_read(UC_ARM_REG_R0),1)
                    self.assertEqual(struct.unpack('<I',u.mem_read(OUT+12,4))[0],keyvalue.value)
                rows,state=cr,cs;actual_cases+=1
        # Original Backup caching and 64-byte copy; external read stub copies supplied data only.
        values['backup']=bytes(rng.randrange(256) for _ in range(64));u.mem_write(0x1b1d851,b'\0');u.mem_write(0x1a53484,b'\0');calls.clear()
        run(0x42506c,OUT);self.assertEqual(bytes(u.mem_read(OUT,64)),values['backup']);self.assertEqual(calls,['backup-copy'])
        values['backup']=b'\xcc'*64;run(0x42506c,OUT+64)
        self.assertEqual(bytes(u.mem_read(OUT+64,64)),bytes(u.mem_read(OUT,64)));self.assertEqual(calls,['backup-copy'])
        print(f'Thumb differential: 256 synthetic + {actual_cases} actual-keymap ADC batches; {actual_cases*2} actual-table key queries; Backup cache 2 calls / 1 explicit external copy')

if __name__=='__main__':unittest.main(verbosity=2)
