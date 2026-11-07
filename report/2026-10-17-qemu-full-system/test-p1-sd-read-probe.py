#!/usr/bin/env python3
"""No VM: profile admission, CPIO/input bindings and passive observer ABI."""
import copy
import gzip
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'p1-sd-read-probe.py'))
U=runpy.run_path(str(HERE/'update-boot.py'))


class Contracts(unittest.TestCase):
    def test_only_explicit_stock_sd_readonly_combination_is_admitted(self):
        valid=dict(mode='official',read_only=True,media={'bound':1},sd={'image':1},
                   module=dict(module_sha256=U['CURRENT_MODULE_SHA'],large_io_fix_bound=True))
        M['admit'](M['PROFILE'],**valid)
        for key,value in [('mode','virtual-dev-sd-update-v1'),('read_only',False),('read_only',1),
                          ('media',None),('sd',None),('module',{})]:
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                M['admit'](M['PROFILE'],**dict(valid,**{key:value}))
        for value in (None,'original-p1-media-readonly-v1','official','allow'):
            with self.assertRaises(ValueError): M['admit'](value,**valid)

    def test_builder_profile_mismatch_rejected_before_output_or_instance(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'absent'
            for kwargs in ({},dict(mode='virtual-dev-sd-update-v1'),dict(media_resources=None),dict(original_resources=False)):
                values=dict(mode='official',media_resources='/receipt',original_resources=True,bodydata='/input',sd_read_profile='wrong')
                values.update(kwargs)
                with self.assertRaises(ValueError): U['build']('/not-an-instance','/runtime',out,**values)
            self.assertFalse(out.exists())

    def test_real_fat_root_is_not_an_extra_file(self):
        paths=[shutil.which(name) for name in ('mformat','mcopy','mmd','mdel')]
        if not all(paths):self.skipTest('Install host mtools for synthetic FAT fixtures')
        directories={Path(path).parent for path in paths}
        self.assertEqual(len(directories),1,'host mtools must share one bin directory')
        tools=directories.pop()
        with tempfile.TemporaryDirectory() as td, patch.dict(U['prepare_sd'].__globals__, tools=lambda _runtime:tools):
            p=Path(td);body=p/'body';body.write_bytes(b'\x89UFU\r\n\x1a\n'+b'original input')
            out=p/'card';out.mkdir();runtime=HERE.parents[1]/'runtime/analysis'
            sd=U['prepare_sd'](body,None,runtime,out)
            M['single_body_fat'](sd['image']['path'],out)
            subprocess.run([str(tools/'mcopy'),'-i',sd['image']['path'],str(body),'::/EXTRA.DAT'],
                check=True,capture_output=True,env=dict(PATH=os.defpath,MTOOLSRC='/dev/null',MTOOLS_SKIP_CHECK='1'))
            with self.assertRaisesRegex(ValueError,'single root BODYDATA'):
                M['single_body_fat'](sd['image']['path'],out)

    def test_exact_cpio_readback_rejects_environment_drift_duplicate_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);root=p/'root';root.mkdir();(root/'env').write_bytes(b'A7C2_FILE_MEDIA_TEST=1\n')
            archive=p/'good.gz';U['archive'](root,archive)
            file=root/'env';expected={'env':dict(mode=file.stat().st_mode,bytes=file.stat().st_size,
                                              sha256=hashlib.sha256(file.read_bytes()).hexdigest())}
            self.assertEqual(M['cpio_readback'](archive,expected),expected)
            changed=copy.deepcopy(expected);changed['env']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'differs'): M['cpio_readback'](archive,changed)
            with self.assertRaisesRegex(ValueError,'Missing'): M['cpio_readback'](archive,dict(expected,absent=expected['env']))
            with archive.open('ab') as raw,gzip.GzipFile(fileobj=raw,mode='wb') as z:
                U['cpio_entry'](z,'env',file.stat().st_mode,file.stat().st_size,file)
            with self.assertRaisesRegex(ValueError,'Duplicate'): M['cpio_readback'](archive,expected)

    def test_no_install_binding_cannot_be_replaced_with_ro_claim(self):
        with tempfile.TemporaryDirectory() as td:
            update=dict(mode='official',sd={'image':1},module_contract=dict(module_sha256=U['CURRENT_MODULE_SHA'],large_io_fix_bound=True))
            for binding in ({},dict(profile=M['PROFILE'],no_install=False),dict(profile=M['PROFILE'],no_install=True,
                source_kind='functional-adapter',environment=M['ENV'],target_block_readonly_count=19)):
                with self.assertRaisesRegex(ValueError,'no-install binding'):
                    M['preflight'](dict(update,sd_read_observation=binding),Path(td),True,{'bound':1},M['PROFILE'])

    def test_receiver_guard_runs_before_original_and_requires_real_twenty_ro_gets(self):
        text=(HERE/'guest/update-storage-bootstrap').read_text()
        self.assertLess(text.index('sd_read_guard || exit 125'),text.index('/usr/bin/sdfileinput.elf "$@" &'))
        self.assertIn('argc!=21',M['RO_GUARD'])
        self.assertIn('ioctl(fd,0x125eUL,&ro)',M['RO_GUARD'])
        self.assertNotIn('0x125d',M['RO_GUARD'])
        self.assertIn('if(rc || ro!=1)failed=1',M['RO_GUARD'])
        self.assertIn('export A7C2_P1_FILE_MEDIA_PROFILE=original-sd-v1',text)

    def test_missing_or_empty_guest_binding_file_is_not_a_ro_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'root';(root/'simulation').mkdir(parents=True)
            data=b'/original 1 '+b'a'*64+b'\n'
            value=dict(profile=M['PROFILE'],no_install=True,source_kind='functional-adapter',environment=M['ENV'],
                target_block_readonly_count=20,cpio_bindings={'simulation/sd-read-bindings':dict(
                    mode=stat.S_IFREG|0o644,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())})
            update=dict(output=td,mode='official',sd={'image':1},bypass_configured=False,sd_read_observation=value,
                module_contract=dict(module_sha256=U['CURRENT_MODULE_SHA'],large_io_fix_bound=True))
            with self.assertRaises(FileNotFoundError): M['preflight'](update,root,True,{'bound':1},M['PROFILE'])
            (root/'simulation/sd-read-bindings').touch()
            with self.assertRaisesRegex(ValueError,'CPIO binding drift'):
                M['preflight'](update,root,True,{'bound':1},M['PROFILE'])

    def test_ro_guard_rejects_regular_files_and_missing_environment(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);source=p/'guard.c'
            source.write_text(M['RO_GUARD']+'\nint main(int c,char **v){return run(c,v);}\n')
            subprocess.run(['cc',str(source),'-o',str(p/'guard')],check=True,capture_output=True)
            files=[]
            for i in range(20):
                path=p/str(i);path.touch();files.append(str(path))
            result=subprocess.run([str(p/'guard'),*files],env=dict(os.environ,**M['ENV']),capture_output=True)
            self.assertEqual(result.returncode,125)
            self.assertEqual(result.stdout.count(b'get_rc=-1 readonly=0'),20)
            env=dict(os.environ);env.pop('A7C2_FILE_MEDIA_TEST',None);env.pop('A7C2_P1_FILE_MEDIA_PROFILE',None)
            result=subprocess.run([str(p/'guard'),*files],env=env,capture_output=True)
            self.assertEqual(result.returncode,125)
            self.assertFalse(result.stdout)

    def test_frozen_hook_is_unchanged_and_retains_original_param_abi(self):
        data=(HERE/'file-media-config.c').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),M['HOOK_SHA'])
        text=data.decode()
        self.assertIn('unsigned (*get)(int)',text)
        self.assertIn('void (*set)(int, unsigned)',text)
        self.assertLess(text.index('original();'),text.index('set((int)PARAM_EXISTMEDIADRIVER, 0);'))
        self.assertIn('#define P1_PARAM_DBG_OMIT_WRITE 0xf6u',text)
        self.assertIn('_exit(126)',text)

    def test_default_readonly_sd_receiver_is_still_rejected(self):
        e=runpy.run_path(str(HERE/'p1-update-execution.py'))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'input').mkdir(); source=p/'input/manifest.json';source.write_text('{}')
            module=dict(build_bound=True,module_sha256=U['CURRENT_MODULE_SHA'],large_io_fix_bound=True,receipts=[{'path':'/receipt'}])
            update=dict(status='built',schema='a7c2-p1-update-boot-v1',instance={'path':str(p/'instance')},
                mode='official',p1={'kernel.img':{'path':'/kernel','sha256':U['KERNEL_SHA'],'bytes':1}},
                persistent_module={'path':'/module','bytes':1,'sha256':U['CURRENT_MODULE_SHA']},
                module_contract=module,sd={'image':1})
            with patch.dict(e['UPDATE'],checked_json=lambda _: (update,{}),record=lambda p: update['p1']['kernel.img'] if p=='/kernel' else update['persistent_module'],
                            module_contract=lambda *args: module):
                with self.assertRaisesRegex(ValueError,'Read-only init probe'):
                    e['build'](source,p/'output')
            self.assertFalse((p/'output/manifest.json').exists())

    def test_returned_read_slices_do_not_promote_coverage_or_installation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'body';p.write_bytes(b'actual bytes')
            raw=('UPDATE_SD_RECEIVER_START pid=752 original=/usr/bin/sdfileinput.elf\n'
                 'P1_SD_NATIVE pid=752 op=open64 path=/dev/mcmn flags=2 rc=-1 errno=2 caller=0x123 callee=0x456\n'
                 'P1_BODY_READ pid=752 handle=abc generation=1 offset=0 requested=12 actual=12 hashed=12 known=1 actor=1 sha256='
                 +hashlib.sha256(p.read_bytes()).hexdigest()+'\nUPDATE_SD_RECEIVER_EXIT pid=752 rc=1\n').encode()
            result=M['observations'](raw,dict(sd_read_observation={'package_source':{'path':str(p)}}))
            self.assertEqual(result['receiver_exits'],[dict(pid=752,rc=1)])
            self.assertTrue(result['p1body_observations']['observed_byte_coverage'])
            self.assertIn('op=open64',result['first_verified_blocker'])
            for name in ('read_verified','coverage','installation_verified','bodywriter_completed','bypass_executed',
                         'target_ro_before_receiver_verified'):
                self.assertFalse(result[name],name)

    def test_passive_native_returns_arguments_errno_and_real_open_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            source=M['OBSERVER'].replace('GLIBC_2.17','GLIBC_2.2.5').replace('/dev/console',str(p/'console'))
            source=source.replace('op("'+str(p/'console')+'",1)','op("'+str(p/'console')+'",1025)')
            source=source.replace('"/usr/bin/sdfileinput.elf"','"'+str(p/'main')+'"')
            (p/'console').touch()
            (p/'observer.c').write_text(source)
            (p/'original.c').write_text('#include <errno.h>\nint Fsys_Init(void){errno=30;return -37;}\n'
                'int Fsys_FindFirst(const char *p,int f,void *o){if(p[0]!=65 || f!=-128)return 99;*(int *)o=1234;errno=5;return -18;}\n')
            (p/'main.c').write_text('#include <sys/prctl.h>\n#include <errno.h>\n#include <fcntl.h>\n#include <assert.h>\n'
                'int Fsys_Init(void),Fsys_FindFirst(const char *,int,void *);\nint main(void){prctl(PR_SET_NAME,"sdfileinput.elf");'
                'assert(Fsys_Init()==-37 && errno==30);int out=0;assert(Fsys_FindFirst("A:/BODYDATA.DAT",-128,&out)==-18 && out==1234 && errno==5);'
                'assert(open("/dev/mcmn",O_RDONLY)==-1 && errno==2);return 0;}')
            commands=[['cc','-shared','-fPIC',str(p/'original.c'),'-o',str(p/'original.so')],
                ['cc','-shared','-fPIC','-O2',str(p/'observer.c'),'-ldl','-o',str(p/'observer.so')],
                ['cc',str(p/'main.c'),str(p/'original.so'),'-o',str(p/'main')]]
            for argv in commands: subprocess.run(argv,check=True,capture_output=True)
            result=subprocess.run([str(p/'main')],env=dict(os.environ,LD_PRELOAD=str(p/'observer.so')),capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            text=(p/'console').read_text()
            self.assertIn('op=Fsys_Init rc=-37 errno=30',text)
            self.assertIn('op=Fsys_FindFirst path=A:/BODYDATA.DAT flags=ffffff80 rc=-18 errno=5',text)
            self.assertIn('op=open path=/dev/mcmn flags=0 rc=-1 errno=2',text)


    def test_initializer_once_abi_errno_exceptions_identity_and_budget(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);binary=p/'sdfileinput.elf';console=p/'console';console.touch()
            symbols={row[0]:row[2] for row in M['INIT_SYMBOLS']}
            # A real C++ exception crosses the C observer and is caught by its original caller.
            original=r'''
#include <errno.h>
#include <assert.h>
namespace Updater { struct ApiException {virtual ~ApiException(){}; unsigned code;unsigned char detail;ApiException():code(0x3000e),detail(9){} }; }
static int calls[6],destroyed;
extern "C" {
int manager(void *a,const char *b,const char *c) asm("MANAGER");
void buffer(void *a) asm("BUFFER");
int sdfile(void *a) asm("SDFILE");
void module(void *a,void *b,void *c,void *d) asm("MODULE");
void information(void *a,void *b) asm("INFORMATION");
unsigned char mountpoint(void *a,const char *b,unsigned c) asm("MOUNTPOINT");
int manager(void *a,const char *b,const char *c){calls[0]++;assert(a==(void*)11&&b==(char*)22&&c==(char*)33&&errno==13);try{information(a,(void*)44);}catch(const Updater::ApiException &e){assert(e.code==0x3000e&&e.detail==9);return 4;}return 99;}
void buffer(void *a){calls[1]++;assert(a==(void*)11);errno=21;}
int sdfile(void *a){calls[2]++;assert(a==(void*)11);errno=22;return -19;}
void module(void *a,void *b,void *c,void *d){calls[3]++;assert(a==(void*)11&&b==(void*)22&&c==(void*)33&&d==(void*)44);errno=23;}
void information(void *a,void *b){calls[4]++;assert(a==(void*)11&&b==(void*)44);errno=30;throw Updater::ApiException();}
unsigned char mountpoint(void *a,const char *b,unsigned c){calls[5]++;assert(a==(void*)11&&b==(char*)22&&c==0x400);errno=30;return 0;}
void *slots[]={ (void*)manager,(void*)buffer,(void*)sdfile,(void*)module,(void*)information,(void*)mountpoint };
int count(int n){return calls[n];}
}
'''
            for op,symbol in symbols.items():original=original.replace(op.upper(),symbol)
            (p/'original.cpp').write_text(original)
            subprocess.run(['c++','-shared','-fPIC','-O2',str(p/'original.cpp'),'-o',str(p/'original.so')],check=True,capture_output=True)
            elf=subprocess.check_output(['readelf','-Ws',str(p/'original.so')],text=True)
            import re,struct
            data=(p/'original.so').read_bytes();ph=struct.unpack_from('<Q',data,32)[0]
            def code(va,size):
                for i in range(struct.unpack_from('<H',data,56)[0]):
                    kind,_,offset,address,_,length,_,_=struct.unpack_from('<IIQQQQQQ',data,ph+i*56)
                    if kind==1 and address<=va and va+size<=address+length:return data[offset+va-address:offset+va-address+size]
                raise AssertionError('fixture text not backed')
            slot=int(re.search(r'\s([0-9a-f]+)\s+48\s+OBJECT\s+GLOBAL\s+DEFAULT\s+\d+\s+slots\b',elf)[1],16)
            pins=[]
            for i,(op,symbol) in enumerate(symbols.items()):
                match=re.search(r'\s([0-9a-f]+)\s+(\d+)\s+FUNC\s+GLOBAL\s+DEFAULT\s+\d+\s+'+symbol+r'\b',elf)
                va,size=int(match[1],16),int(match[2]);pins.append(dict(op=op,symbol=symbol,path=str(p/'original.so'),sha256='fixture',va=va,size=size,slot=slot+i*8,code=code(va,size).hex()))
            main=r'''
#include <errno.h>
#include <assert.h>
extern "C" {
int manager(void*,const char*,const char*) asm("MANAGER");void buffer(void*) asm("BUFFER");int sdfile(void*) asm("SDFILE");
void module(void*,void*,void*,void*) asm("MODULE");unsigned char mountpoint(void*,const char*,unsigned) asm("MOUNTPOINT");int count(int);
}
int main(){errno=13;assert(manager((void*)11,(char*)22,(char*)33)==4&&errno==30);buffer((void*)11);assert(errno==21);
assert(sdfile((void*)11)==-19&&errno==22);assert(mountpoint((void*)11,(char*)22,0x400)==0&&errno==30);
for(int i=0;i<128;i++){module((void*)11,(void*)22,(void*)33,(void*)44);assert(errno==23);}
assert(count(0)==1&&count(1)==1&&count(2)==1&&count(3)==128&&count(4)==1&&count(5)==1);return 0;}
'''
            for op,symbol in symbols.items():main=main.replace(op.upper(),symbol)
            (p/'main.cpp').write_text(main)
            subprocess.run(['c++',str(p/'main.cpp'),str(p/'original.so'),'-o',str(binary)],check=True,capture_output=True)
            source=M['observer_source']({'pins':pins}).replace('GLIBC_2.17','GLIBC_2.2.5')
            source=source.replace('"/usr/bin/sdfileinput.elf"','"'+str(binary)+'"').replace('/dev/console',str(console))
            source=source.replace('op("'+str(console)+'",1)','op("'+str(console)+'",1025)')
            for mode in ('bound','text-drift','wrong-exe'):
                console.write_text('');c=source
                if mode=='text-drift':
                    altered=copy.deepcopy(pins);altered[0]['code']='00'+altered[0]['code'][2:]
                    c=c.replace(M['observer_source']({'pins':pins}).split('init_pins[] = { ',1)[1].split(' };',1)[0],
                                M['observer_source']({'pins':altered}).split('init_pins[] = { ',1)[1].split(' };',1)[0])
                if mode=='wrong-exe':c=c.replace('"'+str(binary)+'"','"/wrong/exe"')
                (p/'observer.c').write_text(c)
                subprocess.run(['cc','-shared','-fPIC','-O2','-fexceptions','-funwind-tables',str(p/'observer.c'),'-ldl','-o',str(p/'observer.so')],check=True,capture_output=True)
                result=subprocess.run([str(binary)],env=dict(os.environ,LD_PRELOAD=str(p/'observer.so')),capture_output=True)
                self.assertEqual(result.returncode,0,(mode,result.stderr))
                text=console.read_text()
                if mode=='wrong-exe':self.assertEqual(text,'');continue
                self.assertIn('identity='+str(int(mode=='bound'))+' taps=6',text)
                self.assertEqual(text.count('P1_SD_INIT ')+text.count('P1_SD_EXCEPTION '),96)
                self.assertIn('op=manager phase=return',text);self.assertIn('rc=4 errno=30',text)
                self.assertIn('op=buffer_void phase=return',text);self.assertIn('rc=void errno=21',text)
                self.assertIn('code_known=1 code=3000e' if mode=='bound' else 'name=opaque code_known=0',text)
                if mode=='bound':
                    # The second preload pins RTLD_NEXT to the original DSO, as the real file-media hook does.
                    media=r'''
#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>
#include <unistd.h>
static void check(void) __attribute__((constructor));
static void check(void){Dl_info i={0};void *fn=dlsym(RTLD_NEXT,"SDFILE");
if(!fn||!dladdr(fn,&i)||strcmp(i.dli_fname,"ORIGINAL"))_exit(126);}
'''.replace('SDFILE',symbols['sdfile']).replace('ORIGINAL',str(p/'original.so'))
                    (p/'media.c').write_text(media)
                    subprocess.run(['cc','-shared','-fPIC',str(p/'media.c'),'-ldl','-o',str(p/'media.so')],check=True,capture_output=True)
                    files={'/simulation/file-media-config.so':p/'media.so',
                           '/simulation/p1-sd-observer.so':p/'observer.so'}
                    configured=M['PRELOAD'].splitlines()
                    for order,expected in ((configured,0),(configured[::-1],126)):
                        console.write_text('')
                        result=subprocess.run([str(binary)],env=dict(os.environ,
                            LD_PRELOAD=':'.join(str(files[name]) for name in order)),capture_output=True)
                        self.assertEqual(result.returncode,expected,(order,result.stderr))
                        if not expected:
                            self.assertIn('identity=1 taps=6',console.read_text())


    def test_trust_observations_are_passive_and_preserve_actual_false(self):
        raw = b'P1_TRUST_KEY pid=752 op=strncmp length=20 left=aa right=bb rc=-1 errno=9 caller=0x123 source_class=original-passive\n'
        result = M['observations'](raw, {})
        self.assertEqual(len(result['trust_key_observations']), 1)
        self.assertIn('rc=-1 errno=9', result['trust_key_observations'][0])
        self.assertFalse(result['installation_verified'])
        self.assertFalse(result['read_verified'])


if __name__=='__main__': unittest.main()
