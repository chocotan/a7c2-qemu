#!/usr/bin/env python3
"""Host C wrappers with real heap pread64; optional pinned ELF/AArch64 checks. No VM."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SRC = HERE
ROOT_VALUE = os.environ.get('P1_TRUST_TEST_ROOT')
ROOT = Path(ROOT_VALUE).resolve() if ROOT_VALUE else None

PREAMBLE = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include "p1-trust-key.h"
typedef struct {const char *file;void *base;const char *symbol;void *address;} Info;
extern void *dlsym(void *,const char *);
static unsigned char sd[0x1e040];
static __thread unsigned long host_caller;
static int init_identity=1,host_selected,mapped=1,wrong_path;
static unsigned char *message,*input,*output;
static unsigned capacity;
static int alloc_calls,send_calls,free_calls,copy_calls,alloc_rc,send_rc,copy_noop,heap_fail,heap_short;
static int opens,closes,message_reads,heap_reads,stage;
static void *copy_return;
static char logs[300][1600];static unsigned log_count;
static int selected(void){return host_selected;}
static void logline(const char *text){assert(log_count<300);snprintf(logs[log_count++],1600,"%s",text);fputs(text,stdout);errno=109;}
int dladdr(const void *p,Info *i){(void)p;i->base=sd;i->file=wrong_path?"/wrong/library.so":"/usr/lib/libsdfileinputupdaterapi.so";return mapped;}
static void *next(const char *);
static int native_alloc(unsigned,void **,unsigned,int);
static int native_send(unsigned,void *);
static int native_free(unsigned,void *);
static void *native_copy(void *,const void *,size_t);
#define memcpy observed_memcpy
#define strncmp observed_strncmp
#define osal_valloc_msg_wait observed_allocate
#define osal_snd_sync_msg observed_send
#define osal_free_msg observed_free
#define SHA1_Final observed_SHA1_Final
#define SHA256 observed_SHA256
#define RSA_verify observed_RSA_verify
#define _ZN7Updater15DecryptorModule9verifySumEv observed_verify
'''
MAIN = r'''
#undef memcpy
#undef strncmp
#undef osal_valloc_msg_wait
#undef osal_snd_sync_msg
#undef osal_free_msg
#undef SHA1_Final
#undef SHA256
#undef RSA_verify
#undef _ZN7Updater15DecryptorModule9verifySumEv
static int ropen(const char *path,int flags,...){
    assert(!strcmp(path,"/proc/self/mem") && flags==(O_RDONLY|O_CLOEXEC|O_NOFOLLOW));
    opens++;return open(path,flags);
}
static long rpread(int fd,void *out,unsigned long n,long long offset){
    uintptr_t a=(uintptr_t)offset;
    if(a>=(uintptr_t)message && a<(uintptr_t)message+1064){message_reads++;errno=EIO;return -1;}
    heap_reads++;
    if(a==(uintptr_t)input)assert(stage==0);
    if(a==(uintptr_t)output)assert(stage==2);
    if(heap_fail){errno=EIO;return -1;}
    return pread64(fd,out,heap_short?n-1:n,offset);
}
static int rclose(int fd){closes++;int rc=close(fd);errno=EINTR;return rc;}
static int native_alloc(unsigned sid,void **out,unsigned n,int wait){
    (void)sid;(void)wait;assert(errno==33);alloc_calls++;capacity=n;*out=message;errno=81;return alloc_rc;
}
static int native_send(unsigned sid,void *p){
    assert(errno==33 && sid==P1_TRUST_SID && p==message);send_calls++;
    for(unsigned i=0;i<(capacity==56?8:capacity-40);i++)message[40+i]=(unsigned char)(i^0x5a);
    errno=82;return send_rc;
}
static int native_free(unsigned sid,void *p){
    assert(errno==33 && sid==P1_TRUST_SID && p==message);free_calls++;errno=83;return -9;
}
static void *native_copy(void *d,const void *s,size_t n){
    assert(errno==33);copy_calls++;stage=host_caller==0x9428?1:2;
    if(!copy_noop)memcpy(d,s,n);
    errno=84;return copy_return?copy_return:d;
}
static void *next(const char *name){
    if(!strcmp(name,"open"))return ropen;
    if(!strcmp(name,"pread64"))return rpread;
    if(!strcmp(name,"close"))return rclose;
    if(!strcmp(name,"memcpy"))return native_copy;
    if(!strcmp(name,"osal_valloc_msg_wait"))return native_alloc;
    if(!strcmp(name,"osal_snd_sync_msg"))return native_send;
    if(!strcmp(name,"osal_free_msg"))return native_free;
    return dlsym((void *)-1,name);
}
static void allocate(unsigned n){
    void *p=0;host_caller=0x93d0;errno=33;int before=alloc_calls;
    assert(observed_allocate(P1_TRUST_SID,&p,n,1)==alloc_rc && errno==81 && p==message);
    assert(alloc_calls==before+1);
}
static void copy_at(unsigned long site,void *d,const void *s,size_t n){
    host_caller=site;stage=0;errno=33;int before=copy_calls;
    assert(observed_memcpy(d,s,n)==(copy_return?copy_return:d) && errno==84);
    assert(copy_calls==before+1);
}
static void rejected(unsigned long site,void *d,const void *s,size_t n){
    int reads=heap_reads+message_reads;unsigned lines=log_count;copy_noop=1;
    copy_at(site,d,s,n);copy_noop=0;
    assert(reads==heap_reads+message_reads && lines==log_count);
}
static struct PassiveBorrow lease;
static void *thread_case(void *unused){
    (void)unused;passive_borrow=lease;
    rejected(0x9428,message+40,input,16);return 0;
}
int main(void){
    unsetenv("A7C2_P1_TRUST_PROFILE");setvbuf(stdout,0,_IONBF,0);
    message=malloc(1064);input=malloc(1024);output=malloc(1024);assert(message && input && output);
    for(unsigned i=0;i<1024;i++)input[i]=(unsigned char)(i*7+3);
    host_selected=1;trust_identity=passive_identity=1;
    trust_borrow=(struct p1_trust_borrow){(void *)0x999,60,P1_TRUST_SID,getpid(),P1_TRUST_ALLOC_RETURN,1};
    struct p1_trust_borrow op1=trust_borrow;
    unsigned sizes[]={56,552,1064};
    for(unsigned i=0;i<3;i++){
        unsigned n=sizes[i]-40;allocate(sizes[i]);assert(passive_borrow.live);
        copy_at(0x9428,message+40,input,n);
        assert(!memcmp(message+40,input,n));
        host_caller=0x9434;errno=33;int sends=send_calls;
        assert(!observed_send(P1_TRUST_SID,message) && errno==82 && send_calls==sends+1);
        assert(!passive_borrow.operation && passive_borrow.sends==1);
        memset(output,0xa5,1024);copy_return=(void *)0x2468;
        copy_at(0x9460,output,message+40,i?n:8);copy_return=0;
        for(unsigned j=0;j<(i?n:8);j++)assert(output[j]==(unsigned char)(j^0x5a));
        host_caller=0x949c;errno=33;int frees=free_calls;
        assert(observed_free(P1_TRUST_SID,message)==-9 && errno==83 && free_calls==frees+1);
        assert(!passive_borrow.live && passive_borrow.free_calls==1);
        rejected(0x9460,output,message+40,i?n:8);
        assert(!memcmp(&op1,&trust_borrow,sizeof op1));
    }
    allocate(56);lease=passive_borrow;lease.sends=1;
    for(int c=0;c<25;c++){
        passive_borrow=lease;unsigned long site=0x9428;void *d=message+40;const void *s=input;size_t n=16;
        switch(c){
        case 0:site=0x942c;break;
        case 1:d=message+41;break;
        case 2:passive_borrow.sid++;break;
        case 3:passive_borrow.pid++;break;
        case 4:passive_borrow.tid++;break;
        case 5:passive_borrow.live=0;break;
        case 6:passive_borrow.free_calls=1;break;
        case 7:passive_borrow.bytes=60;break;
        case 8:passive_borrow.operation=1;break;
        case 9:n=0;break;
        case 10:n=17;break;
        case 11:n=~(size_t)0;break;
        case 12:s=(void *)(~0ul>>1);break;
        case 13:s=(void *)(~0ul-7);break;
        case 14:s=0;break;
        case 15:s=message+40;break;
        case 16:passive_borrow.message=(void *)(~0ul-7);d=(void *)32;break;
        case 17:passive_identity=0;break;
        case 18:trust_identity=0;break;
        case 19:init_identity=0;break;
        case 20:host_selected=0;break;
        case 21:wrong_path=1;break;
        case 22:mapped=0;break;
        case 23:trust_internal=1;break;
        case 24:site=0x9460;d=output;s=message+40;n=8;passive_borrow.sends=0;break;
        }
        rejected(site,d,s,n);
        passive_identity=trust_identity=init_identity=host_selected=mapped=1;wrong_path=trust_internal=0;
    }
    passive_borrow=lease;rejected(0x9464,output,message+40,8);
    rejected(0x9460,output,message+41,8);rejected(0x9460,output,message+40,16);
    rejected(0x9460,(void *)(~0ul>>1),message+40,8);
    rejected(0x9460,0,message+40,8);rejected(0x9460,message+40,message+40,8);
    passive_borrow=lease;pthread_t thread;assert(!pthread_create(&thread,0,thread_case,0));assert(!pthread_join(thread,0));
    pid_t child=fork();assert(child>=0);
    if(!child){passive_borrow=lease;rejected(0x9428,message+40,input,16);_exit(0);}
    int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    passive_borrow=lease;heap_fail=1;copy_at(0x9428,message+40,input,16);heap_fail=0;
    heap_short=1;copy_at(0x9428,message+40,input,16);heap_short=0;
    heap_fail=1;copy_at(0x9460,output,message+40,8);heap_fail=0;
    heap_short=1;copy_at(0x9460,output,message+40,8);heap_short=0;
    assert(!memcmp(message+40,input,16));
    passive_borrow=lease;alloc_rc=-17;allocate(56);assert(!passive_borrow.live);alloc_rc=0;
    passive_borrow=lease;allocate(60);assert(!passive_borrow.live);
    passive_borrow=lease;void *p=0;host_caller=0x93d0;errno=33;
    assert(!observed_allocate(P1_TRUST_SID+1,&p,56,1) && errno==81 && !passive_borrow.live);
    passive_borrow=lease;host_caller=0x1234;errno=33;int frees=free_calls;
    assert(observed_free(P1_TRUST_SID,message)==-9 && errno==83 && free_calls==frees+1 && !passive_borrow.live);
    rejected(0x9428,message+40,input,16);
    passive_borrow=lease;passive_lines=95;unsigned lines=log_count;
    copy_at(0x9428,message+40,input,16);copy_at(0x9428,message+40,input,16);
    assert(passive_lines==96 && log_count==lines+1 && opens==closes);
    assert(!memcmp(&op1,&trust_borrow,sizeof op1));
    printf("NATIVE_COPY_PASS reject_guards=passed pid_fork=1 tid_thread=1 free_once=1 errno_preserved=1 real_heap_pread=1 opens=%d closes=%d\n",opens,closes);
    free(message);free(input);free(output);return 0;
}
'''


def command(argv, label, **kwargs):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=90, **kwargs)
    (ART / (label + '.log')).write_text('$ ' + ' '.join(map(str, argv)) + '\n' + result.stdout + result.stderr)
    if result.returncode:
        raise AssertionError(f'{label}: rc={result.returncode}\n{result.stdout}\n{result.stderr}')
    return result.stdout


class CopyObserver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix='p1-native-caller-copy-')
        cls.addClassCleanup(temporary.cleanup)
        global ART
        ART = Path(temporary.name)

    def test_compiled_native_copy_and_proc_heap_reader(self):
        source = (SRC / 'p1-trust-key.inc').read_text()
        source = source.replace('__builtin_return_address(0)', '(void *)(sd+host_caller)')
        harness = ART / 'native-caller-copy.c'
        harness.write_text(PREAMBLE + source + MAIN)
        flags = ['-fno-builtin', '-fexceptions', '-funwind-tables', '-Wall', '-Wextra', '-Werror',
                 '-Wno-misleading-indentation', '-Wno-sign-compare', '-Wno-type-limits', '-Wno-unused-function']
        for label, compiler, extra in (
                ('strict-o2', 'gcc', ['-O2', '-fstrict-aliasing']),
                ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'])):
            executable = ART / label
            command([compiler, *flags, *extra, '-I', str(SRC), str(harness), str(SRC/'p1-trust-key.c'),
                     '-Wl,--no-as-needed', '-lcrypto', '-ldl', '-pthread', '-o', str(executable)], label+'-compile')
            text = command([str(executable)], label+'-run', env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
            self.assertIn('NATIVE_COPY_PASS', text)
            rows = [dict(x.split('=', 1) for x in line.split()[1:]) for line in text.splitlines() if line.startswith('P1_DECRYPT_PASSIVE ')]
            copies = [r for r in rows if r['op']=='copy']
            for size in (16,512,1024):
                payload = bytes((i*7+3)&255 for i in range(size))
                row = next(r for r in copies if r['direction']=='input' and r['length']==str(size) and r['payload_state']=='observed')
                self.assertEqual((row['phase'],row['sha256'],row['first16']), ('before',hashlib.sha256(payload).hexdigest(),payload[:16].hex()))
                self.assertEqual((row['original_copy_called'],row['original_copy_called_next']), ('0','1'))
                self.assertEqual(row['read_source'],'original-memcpy-source')
            for size in (8,512,1024):
                payload = bytes((i^0x5a)&255 for i in range(size))
                row = next(r for r in copies if r['direction']=='output' and r['length']==str(size))
                self.assertEqual((row['phase'],row['sha256'],row['first16']), ('after',hashlib.sha256(payload).hexdigest(),payload[:16].hex()))
                self.assertEqual((row['original_copy_called'],row['original_copy_called_next'],row['errno']), ('1','0','84'))
                self.assertEqual(row['rc'],str(0x2468))
                self.assertEqual(row['read_source'],'original-memcpy-destination')
                self.assertEqual(row['expected_operation'], '2' if size==8 else '3')
                if size==8:self.assertEqual(row['opaque8'],payload.hex())
            self.assertTrue(all(r['operation']=='0' and r['operation_known']=='0' and r['observed_opcode']=='unknown' for r in copies))
            self.assertTrue(all(r['source_class']=='original-passive' for r in copies))
            for direction,short in (('input','15'),('output','7')):
                self.assertTrue(any(r['direction']==direction and r['payload_actual']=='-1' and r['read_errno']=='5' and r['payload_state']=='unknown' and not r['sha256'] and not r['first16'] for r in copies))
                self.assertTrue(any(r['direction']==direction and r['payload_actual']==short and r['read_errno']=='0' and r['payload_state']=='unknown' and not r['sha256'] and not r['first16'] for r in copies))
            sync = [r for r in rows if r['op']=='sync']
            self.assertEqual(len(sync),6)
            self.assertTrue(all(r['header_actual']=='-1' and r['read_errno']=='5' and r['operation_known']=='0' for r in sync))
            self.assertLessEqual(len(rows),128)

    @unittest.skipUnless(ROOT, 'set P1_TRUST_TEST_ROOT for pinned original ELF and AArch64 checks')
    def test_original_contract_and_aarch64_compile(self):
        module = runpy.run_path(str(SRC/'p1-sd-read-probe.py'))
        contract = module['trust_contract'](ROOT)
        self.assertEqual(json.loads(json.dumps(contract)),contract)
        after = contract['passive']
        self.assertEqual([p['size'] for p in after['windows']],[348,284,1084,288])
        self.assertEqual(after['log_budget'],dict(total=128,pin_identity=32,observations=96))
        self.assertEqual(after['caller_returns']['input_copy'],0x9428)
        self.assertEqual(after['caller_returns']['copy'],0x9460)
        self.assertFalse(after['copy_observer']['actual_verified'])
        self.assertEqual(after['verify_signature_coverage'],'unknown')
        self.assertEqual(after['verify_sum_abi'],'void(this)')
        self.assertEqual(after['helper_args'],9)
        self.assertEqual(after['reader']['backend'],'proc-self-mem-pread64')
        code = bytes.fromhex(after['windows'][0]['code'])
        self.assertEqual(code[0x9424-0x9368:0x9428-0x9368].hex(),'27f7ff97')
        self.assertEqual(code[0x945c-0x9368:0x9460-0x9368].hex(),'19f7ff97')
        (ART/'contract.json').write_text(json.dumps(contract,indent=2)+'\n')
        initializer = module['initialize_contract'](ROOT)
        for label, emitted in (
                ('observer',module['observer_source'](initializer,contract)),
                ('service',module['trust_service_source'](initializer,contract))):
            path = ART/(label+'.c');path.write_text(emitted)
            command(['aarch64-linux-gnu-gcc','-shared','-fPIC','-O2','-fno-builtin','-fexceptions','-funwind-tables',
                     '-I',str(SRC),str(path),str(SRC/'p1-trust-key.c'),'-ldl','-o',str(ART/(label+'.so'))],label+'-aarch64-compile')
        source = (SRC/'p1-trust-key.inc').read_text()
        helper = source[source.index('static void passive_copy('):source.index('void *memcpy(')]
        self.assertNotIn('malloc',helper);self.assertNotIn('memcpy(',helper)
        self.assertNotIn('process_vm_readv',source)
        self.assertIn('passive_read(payload,(const void *)ordinary,n,&read_error)',helper)


if __name__ == '__main__':
    unittest.main(verbosity=2)
