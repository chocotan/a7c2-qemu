#!/usr/bin/env python3
"""Direct host fake-native consumption and original ELF pins; never starts a VM."""
import hashlib
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
ROOT = Path(os.environ.get('P1_TRUST_TEST_ROOT', str(HERE.parents[1] /
    'analysis/scratch/a7c2-functional-batch-stock-v3-20261106/execution/root')))

PREAMBLE = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/mman.h>
#include <pthread.h>
#include "p1-trust-key.h"
typedef struct {const char *file;void *base;const char *symbol;void *address;} Info;
static unsigned char sd[0x1e040];
static unsigned long host_caller;
static int init_identity=1,host_selected;
static int selected(void){return host_selected;}
static void logline(const char *text){fputs(text,stdout);errno=109;}
static void *next(const char *name);
int dladdr(const void *address,Info *info){info->base=address==(void *)0x1000?0:sd;info->file="/usr/lib/libsdfileinputupdaterapi.so";return 1;}
static int native_alloc(unsigned,void **,unsigned,int);
static int native_send(unsigned,void *);
static int native_free(unsigned,void *);
static void native_verify(void *);
'''
MAIN = r'''
extern void *dlsym(void *,const char *);
extern void host_throw(void);
static int mode,alloc_calls,send_calls,free_calls,verify_calls;
static unsigned capacity;
static void *packet;
static unsigned char *mapping;
static int native_alloc(unsigned sid,void **out,unsigned bytes,int wait){
    alloc_calls++;assert(errno==33 && wait==1 && sid==P1_TRUST_SID);
    capacity=bytes;
    if(mode==1){*out=(void *)0x1234;errno=81;return -17;}
    if(mode==6){*out=(void *)0x1000;errno=81;return 0;}
    if(mode==7){*out=mapping+4096-20;errno=81;return 0;}
    packet=mapping+4096-bytes;*out=packet;memset(packet,0xa5,bytes);errno=81;return 0;
}
static int native_send(unsigned sid,void *p){
    send_calls++;assert(errno==33 && sid==P1_TRUST_SID);
    if(mode==5 || mode==6 || mode==7){errno=82;return -71;}
    unsigned long *h=p;assert(p==packet);
    if(mode==8){errno=88;host_throw();}
    h[0]=7;
    if(mode==2)h[4]=~0ul;
    else if(mode==3)h[4]=capacity+4096;
    else if(mode==4)h[0]=0;
    else if(capacity==56){h[4]=8;for(unsigned i=0;i<8;i++)((unsigned char *)p)[40+i]=(unsigned char)(0xf0+i);}
    else for(unsigned i=0;i<capacity-40;i++)((unsigned char *)p)[40+i]=(unsigned char)(i^0x5a);
    errno=82;return mode==4?-31:0;
}
static int native_free(unsigned sid,void *p){free_calls++;assert(sid==P1_TRUST_SID && p && errno==33);errno=83;return -9;}
static void native_verify(void *p){verify_calls++;assert(p && errno==33);errno=84;if(mode==8)host_throw();}
static void *next(const char *name){
    if(!strcmp(name,"pin-refused"))return (void *)0x1000;
    if(!strcmp(name,"pin-good"))return sd+0x100;
    if(!strcmp(name,"pin-mismatch"))return sd+0x104;
    if(!strcmp(name,"pin-missing"))return 0;
    if(!strcmp(name,"osal_valloc_msg_wait"))return native_alloc;
    if(!strcmp(name,"osal_snd_sync_msg"))return native_send;
    if(!strcmp(name,"osal_free_msg"))return native_free;
    if(!strcmp(name,"_ZN7Updater15DecryptorModule9verifySumEv"))return native_verify;
    return dlsym((void *)-1,name);
}
void exercise_throw(int which){
    mode=8;host_caller=which?0x99a4:0x9434;errno=33;
    if(which){static unsigned char object[0x600];_ZN7Updater15DecryptorModule9verifySumEv(object);}
    else osal_snd_sync_msg(P1_TRUST_SID,packet);
    assert(!"original exception must escape");
}
static void *other_thread(void *unused){(void)unused;host_caller=0x9434;errno=33;
    unsigned before=passive_lines;assert(osal_snd_sync_msg(P1_TRUST_SID,packet)==-71 && errno==82);assert(passive_lines==before);return 0;}
extern void run_throw_tests(void);
int main(void){
    setvbuf(stdout,0,_IONBF,0);unsetenv("A7C2_P1_TRUST_PROFILE");
    mapping=mmap(0,8192,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(mapping!=MAP_FAILED);
    /* proc/self/mem can read PROT_NONE via FOLL_FORCE: use a real hole for short-read coverage. */
    assert(!munmap(mapping+4096,4096));
    trust_identity=1;host_selected=1;errno=33;passive_check();
    assert(errno==33 && !passive_identity && passive_lines==0);
    for(unsigned i=0;i<40;i++)passive_check();
    assert(passive_pin_lines==32 && passive_lines==0);host_selected=0;
    trust_identity=passive_identity=1;passive_verify_callee=native_verify;
    void *wrapper=(void *)_ZN7Updater15DecryptorModule9verifySumEv;
    memcpy(sd+0x1e030,&wrapper,sizeof wrapper);
    trust_borrow=(struct p1_trust_borrow){(void *)0x999,60,P1_TRUST_SID,getpid(),P1_TRUST_ALLOC_RETURN,1};
    struct p1_trust_borrow op1=trust_borrow;
    unsigned sizes[]={56,552,1064};
    for(unsigned i=0;i<3;i++){
        void *out=0;mode=0;host_caller=0x93d0;errno=33;
        assert(!osal_valloc_msg_wait(P1_TRUST_SID,&out,sizes[i],1) && out && errno==81);
        unsigned long h[5]={i?3:2,i?0x1122334455667788ul:0,i?0:8,0,sizes[i]-40};memcpy(out,h,40);
        for(unsigned j=0;j<sizes[i]-40;j++)((unsigned char *)out)[40+j]=(unsigned char)j;
        host_caller=0x9434;errno=33;assert(!osal_snd_sync_msg(P1_TRUST_SID,out) && errno==82);
        if(!i){unsigned char context[8];host_caller=0x9460;errno=33;assert(memcpy(context,(char *)out+40,8)==context && errno==33 && context[7]==0xf7);}
        host_caller=0x949c;errno=33;assert(osal_free_msg(P1_TRUST_SID,out)==-9 && errno==83);
        assert(!memcmp(&trust_borrow,&op1,sizeof op1));
    }
    for(mode=1;mode<=7;mode++){
        void *out=0;host_caller=0x93d0;errno=33;int rc=osal_valloc_msg_wait(P1_TRUST_SID,&out,552,1);assert(errno==81);
        if(mode==1){assert(rc==-17 && !passive_borrow.live);continue;}
        if(mode<6){unsigned long h[5]={3,0x12345678,0,0,512};memcpy(out,h,40);}
        host_caller=0x9434;errno=33;int sent=osal_snd_sync_msg(P1_TRUST_SID,out);assert(sent==(mode>=4?(mode==4?-31:-71):0) && errno==82);
        if(mode==5){pthread_t thread;assert(!pthread_create(&thread,0,other_thread,0));assert(!pthread_join(thread,0));}
        host_caller=0x949c;errno=33;assert(osal_free_msg(P1_TRUST_SID,out)==-9 && errno==83);
    }
    mode=0;void *out=0;host_caller=0x93d0;errno=33;assert(!osal_valloc_msg_wait(P1_TRUST_SID,&out,552,1));
    unsigned long h[5]={3,1,0,0,512};memcpy(out,h,40);host_caller=0x9434;errno=33;
    unsigned before=passive_lines;passive_identity=0;assert(!osal_snd_sync_msg(P1_TRUST_SID,out) && errno==82 && passive_lines==before);
    passive_identity=1;host_caller=0x1234;errno=33;assert(!osal_snd_sync_msg(P1_TRUST_SID,out) && errno==82 && passive_lines==before);
    host_caller=0x9434;errno=33;assert(!osal_snd_sync_msg(P1_TRUST_SID,out) && errno==82);
    static unsigned char object[0x600];for(unsigned i=0;i<1024;i++)object[0xb0+i]=(unsigned char)(i*7+3);
    unsigned long progress=512,length=1024;memcpy(object+0x60,&progress,8);memcpy(object+0x4b0,&length,8);
    host_caller=0x99a4;errno=33;_ZN7Updater15DecryptorModule9verifySumEv(object);assert(errno==84 && verify_calls==1);
    host_caller=0x99a4;errno=33;_ZN7Updater15DecryptorModule9verifySumEv((void *)0x1000);assert(errno==84 && verify_calls==2);
    run_throw_tests();assert(errno==84);
    assert(!memcmp(&trust_borrow,&op1,sizeof op1));
    printf("COUNTS alloc=%d send=%d free=%d verify=%d\n",alloc_calls,send_calls,free_calls,verify_calls);
    return 0;
}
'''
THROW = r'''
#include <cassert>
#include <cerrno>
extern "C" void exercise_throw(int);
extern "C" void host_throw(void){throw 0x123456;}
extern "C" void run_throw_tests(void){for(int i=0;i<2;i++){try{exercise_throw(i);assert(false);}catch(int value){assert(value==0x123456 && errno==(i?84:88));}}}
'''


class Passive(unittest.TestCase):
    def test_real_proc_reader_boundaries_errno_and_no_process_vm_dependency(self):
        source = (HERE / 'p1-trust-key.inc').read_text()
        self.assertNotIn('process_vm_readv', source)
        reader = source[source.index('static long passive_read('):source.index('struct PassivePin {')]
        main = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static int opens,closes,reads,missing,deny;
static int ropen(const char *path,int flags,...){
    assert(!strcmp(path,"/proc/self/mem") && flags==(O_RDONLY|O_CLOEXEC|O_NOFOLLOW));
    opens++;if(deny){errno=EACCES;return -1;}
    int fd=open(path,flags);assert(fd>=0 && (fcntl(fd,F_GETFD)&FD_CLOEXEC));return fd;
}
static long rread(int fd,void *out,unsigned long n,long long offset){reads++;return pread64(fd,out,n,offset);}
static int rclose(int fd){closes++;int rc=close(fd);assert(!rc);errno=EINTR;return rc;}
static void *next(const char *name){
    if(!strcmp(name,"open"))return ropen;
    if(!strcmp(name,"pread64"))return missing?0:rread;
    if(!strcmp(name,"close"))return rclose;
    assert(!"unexpected reader dependency");return 0;
}
'''
        main += reader + r'''
static void rejected(void *out,const void *in,unsigned long n,int want){
    int error=0;errno=EDOM;assert(passive_read(out,in,n,&error)==-1 && error==want && errno==EDOM);
}
int main(void){
    unsigned char known[1084],out[1084];for(unsigned i=0;i<sizeof known;i++)known[i]=(unsigned char)(i*17);
    int error=99;errno=ERANGE;
    assert(passive_read(out,known,sizeof known,&error)==(long)sizeof known && error==0 && errno==ERANGE);
    assert(!memcmp(out,known,sizeof known) && opens==1 && closes==1 && reads==1);
    rejected(out,(void *)0x1000,32,EIO);
    rejected(out,0,32,EFAULT);rejected(out,(void *)1,32,EFAULT);rejected(0,known,32,EFAULT);
    rejected(out,known,0,EINVAL);rejected(out,known,1085,EINVAL);rejected(out,known,~0ul,EINVAL);
    rejected(out,(void *)(~0ul>>1),2,EOVERFLOW);rejected(out,(void *)(~0ul-7),16,EOVERFLOW);
    rejected((void *)(~0ul>>1),known,2,EOVERFLOW);
    long page=sysconf(_SC_PAGESIZE);assert(page>=1084);
    unsigned char *p=mmap(0,(size_t)page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(p!=MAP_FAILED);
    memcpy(p+page-16,known,16);assert(!munmap(p+page,(size_t)page));
    memset(out,0xa5,sizeof out);errno=EBUSY;
    assert(passive_read(out,p+page-16,32,&error)==16 && error==0 && errno==EBUSY);
    assert(!memcmp(out,known,16) && out[16]==0xa5);assert(!munmap(p,(size_t)page));
    missing=1;rejected(out,known,32,ENOSYS);missing=0;
    deny=1;rejected(out,known,32,EACCES);deny=0;
    int fd=open("/dev/null",O_RDONLY|O_CLOEXEC);assert(fd>=0);errno=EDOM;
    assert(passive_read(out,known,32,&error)==32 && !error && errno==EDOM);
    assert(fcntl(fd,F_GETFD)>=0 && !close(fd));
    assert(opens==5 && closes==4 && reads==4);
    puts("REAL_PROC_READER full short refused overflow errno per-read-fd passed");return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder); (p / 'reader.c').write_text(main)
            build = subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(p/'reader.c'), '-ldl', '-o', str(p/'reader')], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(p/'reader')], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('REAL_PROC_READER full short refused overflow errno per-read-fd passed', result.stdout)

    def test_fake_native_bounds_errno_ownership_block_digest_and_cpp_unwind(self):
        source = (HERE / 'p1-trust-key.inc').read_text()
        # Host pins test every diagnostic outcome after explicit fake dladdr/RTLD_NEXT gates.
        source = source.replace('/* __PASSIVE_PINS__ */', '''
{"pin-refused","/usr/lib/libsdfileinputupdaterapi.so",0x1000,0x1000,4,{0}},
{"pin-good","/usr/lib/libsdfileinputupdaterapi.so",0x100,0x100,4,{0}},
{"pin-mismatch","/usr/lib/libsdfileinputupdaterapi.so",0x104,0x104,4,{1}},
{"pin-missing","/usr/lib/libsdfileinputupdaterapi.so",0,0,4,{0}}
''')
        start, end = source.index('static int trust_caller('), source.index('static void trust_hex(')
        source = source[:start] + '''static int trust_caller(void *caller,unsigned long va) {
    (void)caller;return va==host_caller;
}
''' + source[end:]
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p / 'host.c').write_text(PREAMBLE + source + MAIN)
            (p / 'throw.cpp').write_text(THROW)
            commands = [
                ['cc', '-O2', '-fno-builtin', '-fexceptions', '-funwind-tables', '-I', str(HERE), '-c', str(p/'host.c'), '-o', str(p/'host.o')],
                ['g++', '-O2', '-c', str(p/'throw.cpp'), '-o', str(p/'throw.o')],
                ['cc', '-O2', '-I', str(HERE), '-c', str(HERE/'p1-trust-key.c'), '-o', str(p/'core.o')],
                ['g++', str(p/'host.o'), str(p/'throw.o'), str(p/'core.o'), '-Wl,--no-as-needed', '-lcrypto', '-ldl', '-pthread', '-o', str(p/'host')],
            ]
            for argv in commands:
                result = subprocess.run(argv, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(p/'host')], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('COUNTS alloc=11 send=14 free=9 verify=3', result.stdout)
            lines = [dict(v.split('=', 1) for v in line.split()[1:]) for line in result.stdout.splitlines() if line.startswith('P1_DECRYPT_PASSIVE ')]
            pins = [x for x in lines if x['op']=='pin']
            self.assertEqual([x['symbol'] for x in pins[:4]], ['pin-refused','pin-good','pin-mismatch','pin-missing'])
            self.assertEqual([x['compare'] for x in pins[:4]], ['unknown','match','mismatch','unknown'])
            self.assertEqual((pins[0]['actual'], pins[0]['read_errno']), ('-1','5'))
            self.assertEqual((pins[1]['actual'], pins[1]['read_errno']), ('4','0'))
            self.assertEqual((pins[3]['resolved'], pins[3]['read_attempted']), ('0','0'))
            self.assertEqual(len([x for x in lines if x['op'] in ('pin','identity')]), 32)
            self.assertLessEqual(len(lines), 128)
            sync = [x for x in lines if x['op']=='sync']
            for size in (16,512,1024):
                expected = bytes(i & 255 for i in range(size))
                self.assertTrue(any(x.get('phase')=='before' and x['bounded']==str(size) and x['sha256']==hashlib.sha256(expected).hexdigest() for x in sync))
            for size in (512,1024):
                expected = bytes((i ^ 0x5a) & 255 for i in range(size))
                self.assertTrue(any(x.get('phase')=='after' and x['bounded']==str(size) and x['sha256']==hashlib.sha256(expected).hexdigest() and x['errno']=='82' for x in sync))
            self.assertTrue(any(x.get('bounds')=='negative-length' and x['bounded']=='0' and not x['sha256'] for x in sync))
            self.assertTrue(any(x.get('bounds')=='over-capacity' and x['bounded']=='512' for x in sync))
            self.assertTrue(any(x.get('header_actual')=='-1' and x['read_errno']=='5' for x in sync))
            self.assertTrue(any(x.get('header_actual')=='20' and not x['sha256'] for x in sync))
            self.assertTrue(any(x.get('opaque8')=='f0f1f2f3f4f5f6f7' and x['actual']=='8' for x in lines))
            self.assertTrue(all(x['native_free_count']=='1' and x['rc']=='-9' and x['errno']=='83' for x in lines if x['op']=='free'))
            blocks = [x for x in lines if x['op']=='verifySum' and x.get('phase')=='before']
            block = bytes((i*7+3)&255 for i in range(1024))
            self.assertEqual(blocks[0]['sha256'], hashlib.sha256(block).hexdigest())
            self.assertEqual(int(blocks[0]['sum511']), sum(struct.unpack('<511H',block[2:]))&65535)
            self.assertEqual(blocks[0]['first4'],block[:4].hex())
            self.assertEqual(blocks[1]['block_actual'],'-1')
            self.assertEqual(len([x for x in lines if x['op']=='verifySum' and x.get('phase')=='return']),2)

    @unittest.skipUnless((ROOT / M['KEY'][0]).exists(), 'provide original extracted P1 root')
    def test_original_nine_arg_callsites_windows_and_tamper_rejection(self):
        contract = M['trust_contract'](ROOT)
        self.assertEqual(contract['passive']['helper_args'],9)
        self.assertFalse(contract['passive']['helper_interposed'])
        reader = contract['passive']['reader']
        self.assertEqual(reader['backend'], 'proc-self-mem-pread64')
        self.assertEqual(reader['flags'], ['O_RDONLY', 'O_CLOEXEC', 'O_NOFOLLOW'])
        self.assertEqual((reader['max_read_bytes'], reader['max_packet_payload_bytes'], reader['offset_bits']), (1084, 1024, 64))
        self.assertTrue(reader['caller_errno_preserved'] and reader['per_read_open_close'])
        self.assertFalse(reader['actual_verified'] or reader['alternate_backend'])
        self.assertEqual(contract['passive']['log_budget'], dict(total=128, pin_identity=32, observations=96))
        self.assertEqual(len(contract['passive']['windows']),4)
        original = runpy.run_path(str(HERE/'p1-file-media-contract.py'))
        sd = (ROOT / original['SAMPLES']['sd'][0]).read_bytes()
        for va, expected in ((0x93cc,'11f8ff97'),(0x9430,'28f9ff97'),(0x9498,'4af9ff97'),(0x95fc,'5bffff97'),(0x98f0,'9efeff97'),(0x99a0,'dcf5ff97')):
            offset = original['va_offset'](sd,va,4)
            self.assertEqual(sd[offset:offset+4].hex(),expected)
        self.assertEqual(sd[0x9380:0x9384].hex(),'b74340f9')  # ninth arg load from original caller stack
        self.assertEqual(sd[0x98c8:0x98cc].hex(),'f60300f9')  # original op2 stack[0]
        source = M['observer_source'](M['initialize_contract'](ROOT),contract)
        self.assertIn('void (*fn)(void *)=next("'+M['VERIFY_SUM']+'")',source)
        self.assertNotIn('int _ZN7Updater17SDDecryptorModule18DecScrambleWrapper',source)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in contract['files']:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
            core=root/M['CORE'][0];data=bytearray(core.read_bytes());data[0xb668]^=1;core.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'identity differs'):M['trust_contract'](root)


if __name__=='__main__':unittest.main()
