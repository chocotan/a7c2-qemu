"""Public synthetic checks for full-write admission and four opt-in EE checkpoints. No VM."""
import copy
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODEL = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
BUILD = runpy.run_path(str(HERE / 'usb-start-observe.py'))
FIXTURE = runpy.run_path(str(HERE / 'test-usb-ee-normal-cold.py'))
PROBE = runpy.run_path(str(HERE / 'usb-ap-probe.py'))


def c_function(text, name):
    start = re.search(r'static [^\n]*\b' + name + r'\([^\n]*\) \{', text).start()
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


LOG_PREFIX = r'''
#define _GNU_SOURCE
#define USB_EE_NORMAL_COLD 1
#define EE_ESSENTIAL_LIMIT 32u
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
static int logfd=-1,short_write,resources=1;
static unsigned ee_records,ee_essential,ee_capped,ee_console_records,ee_console_essential,calls;
static long fixture_syscall(long op,...) {
    if(op==SYS_gettid)return syscall(op);
    assert(op==SYS_write);va_list a;va_start(a,op);int fd=va_arg(a,int);const void *p=va_arg(a,const void *);size_t n=va_arg(a,size_t);va_end(a);
    if(fd==logfd&&short_write)return (long)n-1;
    return syscall(op,fd,p,n);
}
#define syscall fixture_syscall
#define EE_COLD_MODE "ee-normal-wake-cold-functional-v1"
static const struct {uint64_t generation;} ee_nwc_prepared_assets={7};
static const char *ee_cold_source_class(void){return "callback";}
static int ee_cold_resources(void){return resources;}
static int ee_cold_native_allocate(unsigned d,void **m,unsigned n,unsigned f){assert(d==0x80020002&&m&&n==12&&f==1&&errno==71);calls++;*m=(void *)0x123400;errno=83;return 37;}
'''
LOG_MAIN = r'''
int main(int argc,char **argv){assert(argc==3);int mode=atoi(argv[2]);logfd=open(argv[1],O_CREAT|O_RDWR|O_EXCL,0600);assert(logfd>=0);int pipefd[2]={-1,-1};
 if(mode==1){close(logfd);logfd=-1;} /* no log fd */
 if(mode==2)close(logfd); /* EBADF */
 if(mode==3){close(logfd);assert(!pipe2(pipefd,O_NONBLOCK));logfd=pipefd[1];char b[4096]={0};while(write(logfd,b,sizeof b)>0){}assert(errno==EAGAIN);}
 if(mode==4)ee_essential=32;
 if(mode==5)resources=0;
 if(mode==6)short_write=1;
 void *message=NULL;errno=71;int rc=ee_cold_allocate(0x80020002,&message,12,1);
 assert(calls==(mode==0));assert(rc==(mode==0?37:-1023));assert(errno==(mode==0?83:71));
 if(mode==0)assert(message==(void *)0x123400);else assert(!message);
 if(mode!=1&&mode!=2)close(logfd);if(pipefd[0]>=0)close(pipefd[0]);return 0;}
'''

DIAG_HARNESS = r'''
#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <stdint.h>
static ssize_t fixture_pread(int,void *,size_t,off_t);
static ssize_t fixture_readlink(const char *,char *,size_t);
static FILE *fixture_fopen(const char *,const char *);
#define pread fixture_pread
#define readlink fixture_readlink
#define fopen fixture_fopen
#define USB_OBSERVE_HOST_TEST 1
#define USB_EE_NORMAL_COLD 1
#include "usb-start-observe.c"
#undef pread
#undef readlink
#undef fopen
#include <assert.h>
#include <stdlib.h>
static unsigned mode,reads,links,opens,recv_calls,source_calls,size_calls,free_calls,freed;
static int mutate_byte=-1;
static int stable_byte(unsigned n){return n<4||(n>=8&&n<20)||(n>=24&&n<40)||(n>=48&&n<52);}
static unsigned char uconf[56];
static const uintptr_t message=0x100100;
static ssize_t fixture_pread(int fd,void *out,size_t n,off_t p){
 assert(fd==memfd);if(p!=(off_t)(uintptr_t)uconf){assert(!freed);if(p==(off_t)message){assert(n==12);errno=EFAULT;return -1;}assert(n==sizeof(uintptr_t));memcpy(out,(const void *)(uintptr_t)p,n);return (ssize_t)n;}assert(n==56);reads++;
 if(mode==2){errno=EIO;return -1;}if(mode==6&&!(reads&1)){errno=EBADF;return -1;}
 if(mode==10){errno=ENOSPC;return 28;}
 if(mode==40&&reads>2){errno=EIO;return -1;}
 if(mode==41&&reads==4){errno=EBADF;return -1;}
 memcpy(out,uconf,n);if((mode==7&&!(reads&1))||(mode==42&&reads==4))((char *)out)[0]^=1;
 if(mutate_byte>=0&&!(reads&1))((unsigned char *)out)[mutate_byte]^=1;
 errno=(reads&1)?91:94;return (ssize_t)n;
}
static ssize_t fixture_readlink(const char *path,char *out,size_t n){assert(!strncmp(path,"/proc/self/fd/",14)&&n==63);links++;if(mode==3||(mode==45&&links>1)){errno=ENOENT;return -1;}const char *target=mode==9?"/dev/other":"/dev/uipc";strcpy(out,target);errno=92;return (ssize_t)strlen(target);}
static FILE *fixture_fopen(const char *path,const char *how){assert(!strcmp(path,"/proc/self/maps")&&!strcmp(how,"r"));opens++;if(mode==4){errno=EACCES;return NULL;}FILE *f=tmpfile();assert(f);fputs(mode==5?"invalid map\n":"100000-300000 rw-s 00000000 00:00 1 /dev/uipc\n",f);rewind(f);errno=93;return f;}
static int32_t native_recv(uint32_t q,uintptr_t out,int32_t timeout){assert(q==EE_QUEUE&&timeout==-1);recv_calls++;*(uintptr_t *)out=message;errno=48;return 0;}
static uint32_t native_source(uintptr_t p){assert(p==message&&!freed);source_calls++;errno=49;return 0x90040193;}
static int32_t native_size(uintptr_t p){assert(p==message&&!freed);size_calls++;errno=50;return 12;}
static int32_t native_free(uint32_t owner,uintptr_t p){assert(owner==EE_QUEUE&&p==message&&!freed);free_calls++;freed=1;errno=51;return 0;}
static void *free_thread(void *unused){(void)unused;errno=31;assert(!ee_free(EE_QUEUE,message)&&errno==51);return NULL;}
int main(int argc,char **argv){assert(argc==3);mode=(unsigned)atoi(argv[2]);logfd=open(argv[1],O_CREAT|O_EXCL|O_RDWR,0600);assert(logfd>=0);memfd=mode==11?-1:123;
 ee_uipc_base=(uintptr_t)uconf-0x1b560;ee_cold_abi_verified=mode!=1;
 int fd=7;uintptr_t map=0x100000,allocator=0x400000;unsigned bytes=mode==8?1:0x200000,pool0=0x80000,pool1=0x20000,dynamic=9;
 memcpy(uconf,&fd,4);memcpy(uconf+8,&map,8);memcpy(uconf+16,&bytes,4);memcpy(uconf+24,&allocator,8);memcpy(uconf+32,&pool0,4);memcpy(uconf+36,&pool1,4);memcpy(uconf+48,&dynamic,4);
 errno=37;
 if(mode==12){
  for(unsigned i=0;i<56;i++){struct ee_nwc_init init;unsigned before=reads;mutate_byte=(int)i;assert(ee_cold_read_init(&init)==!stable_byte(i));assert(reads==before+2);}
  mutate_byte=-1;
 }else if(mode>=100&&mode<156){
  unsigned byte=mode-100;assert(ee_cold_resources());uconf[byte]^=1;
  assert(ee_cold_resources()==!stable_byte(byte));uconf[byte]^=1;
  assert(ee_cold_resources()==!stable_byte(byte)); /* A restored identity never clears a sticky failure. */
 }else if(mode>=40&&mode<=45){
  assert(ee_cold_resources());ee_cold_consumer=746;ee_cold_reading.active=1;ee_registration.valid=1;
  if(mode==43)uconf[48]^=1;
  if(mode==44){ee_cold_slots[0]=(struct ee_cold_slot){.pid=getpid(),.epoch=7,.message=message,.state=1};ee_cold_metadata(message,0,0x90040193);ee_cold_metadata(message,0,0x90040194);}
  ee_cold_wait(0x123);ee_cold_wait(0x123);assert(!ee_cold_service&&!ee_cold_attempted&&ee_cold_failed);
 }else if(mode<20){struct ee_nwc_init init;int ok=ee_cold_read_init(&init);assert(ok==(mode==0));if(mode==0)assert(init.fd==7&&init.map_verified&&init.fd_verified&&init.bytes==0x200000);ee_cold_read_init(&init);}
 else if(mode<30){ee_cold_consumer=746;ee_cold_reading.active=mode!=20;ee_registration.valid=1;if(mode==22)ee_cold_failed=42;ee_cold_wait(0x123);ee_cold_wait(0x123);assert(!ee_cold_service&&!ee_cold_attempted);}
 else {ee_real_recv=native_recv;ee_real_source=native_source;ee_real_size=native_size;ee_real_free=native_free;
  uintptr_t out=0;assert(!ee_recv(EE_QUEUE,(uintptr_t)&out,-1)&&errno==48&&out==message);ee_source(message);ee_size(message);
  ee_cold_reading.active=0;ee_registration.valid=1;ee_cold_wait(0x123);
  pthread_t thread;assert(!pthread_create(&thread,NULL,free_thread,NULL));assert(!pthread_join(thread,NULL));
  assert(ee_cold_prime.free_returned==1&&ee_cold_prime.receiver_tid!=ee_cold_prime.free_actor_tid);
  assert(recv_calls==1&&source_calls==1&&size_calls==1&&free_calls==1&&freed);
 }
 printf("%u %u %u %u %u %u %u %u %u %d\n",reads,links,opens,recv_calls,source_calls,size_calls,free_calls,ee_essential,ee_records,errno);close(logfd);return 0;}
'''


class GateCheckpoints(unittest.TestCase):
    def compile(self, root, name, text, *, flags=(), core=False):
        source = root / (name + '.c'); source.write_text(text)
        command = ['cc', '-std=gnu11', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-function', '-Wno-unused-variable', '-Wno-misleading-indentation',
            '-I', str(HERE), '-DUSB_EE_NORMAL_COLD_INPUT="' + str(root / 'input.h') + '"',
            *flags, str(source), *([str(HERE / n) for n in ('ee-normal-wake-cold.c', 'ee-capability-input.c')] if core else []),
            '-ldl', '-o', str(root / name)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=40)
        self.assertEqual(run.returncode, 0, run.stderr)
        return root / name

    def test_full_write_four_args_rc_errno_and_six_rejections(self):
        emit = c_function((HERE / 'usb-ee-zero-observe.inc').read_text(), 'ee_emit')
        allocate = c_function((HERE / 'usb-ee-normal-cold.inc').read_text(), 'ee_cold_allocate')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary = self.compile(root, 'log', LOG_PREFIX.replace('#include <stdint.h>', '#include <stdint.h>\n#include <stdlib.h>') + emit + allocate + LOG_MAIN)
            for mode in range(7):
                run = subprocess.run([str(binary), str(root / f'log-{mode}'), str(mode)], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 0, (mode, run.stderr))
            text = (root / 'log-0').read_text()
            self.assertIn('FUNCTIONAL_ALLOCATE_ENTER', text)
            self.assertIn('FUNCTIONAL_ALLOCATE_RETURN', text)
            self.assertIn('rc=37 errno=83', text)

    def test_read_init_real_call_results_default_parity_and_bounded_diagnostics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binaries = {}
            for enabled in (False, True):
                (root / 'input.h').write_text(FIXTURE['fixture_header']() + f'#define EE_COLD_DIAGNOSTICS {int(enabled)}\n')
                binaries[enabled] = self.compile(root, f'diag-{enabled}', DIAG_HARNESS,
                    flags=['-DEE_COLD_ADMISSION_SOURCE=EE_NWC_KERNELDEFAULT'], core=True)
            outputs = {}
            for enabled, binary in binaries.items():
                for mode in (*range(13), 20, 21, 30, *range(40,46), *range(100,156)):
                    log = root / f'diag-{enabled}-{mode}.log'
                    run = subprocess.run([str(binary), str(log), str(mode)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(run.returncode, 0, (enabled, mode, run.stderr))
                    outputs[enabled, mode] = run.stdout
                    diag = [line for line in log.read_text().splitlines() if line.startswith('USB_EE_DIAG ')]
                    expected=4 if mode==30 else 2 if mode==21 or 40<=mode<=45 else 1
                    self.assertEqual(len(diag), expected if enabled else 0)
                    self.assertEqual(len({line.split()[1] for line in diag}), len(diag))
                    self.assertTrue(all(len(line)<1024 for line in diag))
                    if enabled:
                        fields = dict(token.split('=', 1) for token in diag[0].split()[2:])
                        if mode in (2, 10, 11):
                            self.assertEqual((fields['read_rc'], fields['read_errno']), {2:('-1','5'),10:('28','28'),11:('-2','-1')}[mode])
                        if mode==3:self.assertIn('readlink_rc=-1 readlink_errno=2', diag[0])
                        if mode==4:self.assertIn('fopen_ok=0 fopen_errno=13', diag[0])
                        if mode==5:self.assertIn('stage=maps_parse', diag[0]);self.assertIn('maps_parse_rc=0', diag[0])
                        if mode==6:self.assertIn('read2_rc=-1 read2_errno=9', diag[0])
                        if mode==7:self.assertIn('stage=equality', diag[0]);self.assertIn('equality=0 init_valid=-1', diag[0])
                        if mode==8:self.assertIn('stage=init_valid', diag[0])
                        if mode==20:self.assertIn('reason=reading_active ledger_known=1', diag[0])
                        if 40<=mode<=45:
                            wait=next(line for line in diag if ' WAIT_ADMISSION ' in line)
                            self.assertIn('stage=success result=1',diag[0])
                            self.assertIn('reason=resources ledger_known=1 consumer=0x2ea',wait)
                            self.assertIn('init_known=1 queue_known=0',wait)
                            self.assertIn('first_sticky='+('12' if mode==44 else '4'),wait)
                            self.assertIn('first_site=ee_cold_'+('metadata' if mode==44 else 'resources'),wait)
                            if mode in (40,41,42,45):
                                self.assertIn('resource_fault=read_init',wait)
                                self.assertIn('last_init_known=1',wait)
                                self.assertIn('last_init_stage='+{40:'read1',41:'read2',42:'equality',45:'readlink'}[mode],wait)
                            if mode==40:self.assertIn('last_read_rc=-1 last_read_errno=5',wait)
                            if mode==41:self.assertIn('last_read2_rc=-1 last_read2_errno=9',wait)
                            if mode==42:self.assertIn('stable_diff=1',wait)
                            if mode==45:self.assertIn('last_init_stage=readlink last_init_errno=2',wait)
                            if mode==43:self.assertIn('resource_fault=bound_identity bound_diff=64 last_init_known=0',wait)
                            if mode==44:self.assertIn('resource_fault=unknown bound_diff=0 last_init_known=0',wait)
                        if mode==21:self.assertIn('reason=prime ledger_known=1', diag[-1]);self.assertIn('prime_free_returned=0', diag[-1])
                        if mode==30:
                            self.assertIn('source_known=0', next(line for line in diag if ' RECV_SLOT ' in line))
                            free = next(line for line in diag if ' FREE_RETURN ' in line)
                            self.assertIn('source_known=1 source=0x90040193 size_known=1 size=12', free)
                            self.assertIn('rc=0 errno=51 resources=1', free)
                            self.assertIn('slot_generation=7 receive_event=1', free)
                if enabled:
                    # Saturation and log failures are wholly separate from essential records.
                    self.assertNotIn('USB_EE CAP ', (root / 'diag-True-30.log').read_text())
            for mode in (*range(13), 20, 21, 30, *range(40,46), *range(100,156)):
                self.assertEqual(outputs[False, mode], outputs[True, mode], mode)
            (root / 'input.h').write_text(FIXTURE['fixture_header']() + '#define EE_COLD_DIAGNOSTICS 1\n')
            binary = self.compile(root, 'callback-fault', DIAG_HARNESS, core=True)
            log = root / 'callback-fault.log'
            run = subprocess.run([str(binary), str(log), '22'], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('reason=sticky_fault ledger_known=1 consumer=0x2ea attempted=0 failed=42', log.read_text())

    def test_diagnostic_write_failure_and_cap_never_spend_functional_budget(self):
        main = r'''
int main(int argc,char **argv){assert(argc==2);errno=77;logfd=-1;
 assert(ee_diag_claim(0));ee_diag_emit("READ_INIT","generation=7 result=0");assert(errno==77&&ee_diag_write_failures==1);
 assert(!ee_diag_claim(0)&&ee_diag_cap==1);logfd=open(argv[1],O_CREAT|O_EXCL|O_RDWR,0600);assert(logfd>=0);errno=77;
 assert(ee_diag_claim(1));ee_diag_emit("WAIT_ADMISSION","generation=7 reason=prime");assert(errno==77);
 char large[1100];memset(large,'x',sizeof large-1);large[sizeof large-1]=0;
 assert(ee_diag_claim(2));ee_diag_emit("RECV_SLOT","data=%s",large);assert(errno==77&&ee_diag_write_failures==2);
 assert(ee_diag_claim(3));ee_diag_emit("FREE_RETURN","generation=7 ticket_valid=0");assert(errno==77);
 assert(ee_diag_seen==15&&!ee_records&&!ee_essential&&!ee_capped);close(logfd);return 0;}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'input.h').write_text(FIXTURE['fixture_header']()+'#define EE_COLD_DIAGNOSTICS 1\n')
            binary=self.compile(root,'diag-failure',DIAG_HARNESS.split('int main(',1)[0]+main,core=True)
            log=root/'diag-failure.log';run=subprocess.run([str(binary),str(log)],capture_output=True,text=True,timeout=10)
            self.assertEqual(run.returncode,0,run.stderr)
            lines=log.read_text().splitlines();self.assertEqual(len(lines),2)
            self.assertIn('write_failures=1 cap_mask=1',lines[0]);self.assertIn('write_failures=2 cap_mask=1',lines[1])

    def test_old_models_default_off_and_option_is_typed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.json'
            old = dict(schema=1, profile=MODEL['PROFILE'], generation=7, force_e0=0, be9bae_byte9=0, stable_state_hex='00'*32, adc_hex='00'*48)
            for source in (None, 'callback', 'kerneldefault'):
                data = dict(old, **({'admission_source':source} if source else {}));path.write_text(json.dumps(data))
                self.assertIs(MODEL['load_model'](path)[0]['diagnostic_checkpoints'], False)
                path.write_text(json.dumps(dict(data, diagnostic_checkpoints=True)))
                self.assertIs(MODEL['load_model'](path)[0]['diagnostic_checkpoints'], True)
                for bad in (0, 1, 'true', None):
                    path.write_text(json.dumps(dict(data, diagnostic_checkpoints=bad)))
                    with self.assertRaises(ValueError):MODEL['load_model'](path)

    def test_source_header_actual_dso_provenance_and_strict_trace_envelope(self):
        if not shutil.which('clang') or not Path('/usr/aarch64-linux-gnu/lib/libc.so').exists():
            self.skipTest('AArch64 cross-link toolchain not installed')
        fixture = runpy.run_path(str(HERE / 'test-usb-ap-probe.py'))['FunctionalContracts']();fixture.setUp()
        trace = b''.join(line for line in fixture.trace().splitlines(keepends=True) if line.startswith((b'USB_START ', b'USB_EE PREINIT ')))
        pre = next(line for line in trace.splitlines(keepends=True) if line.startswith(b'USB_EE PREINIT '))
        trace = trace.replace(pre, pre.rstrip()+b' native_allocation_log_commit_required=1 native_allocation_log_commit_version=1\n')
        self.assertFalse(PROBE['functional_trace_summary'](fixture.capture(trace), fixture.contract)['resource_safe_to_close'])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder);(root / 'root/simulation').mkdir(parents=True)
            header = root / 'private-ee-normal-cold-input.h'
            header.write_text(FIXTURE['fixture_header']() + '#define EE_COLD_DIAGNOSTICS 0\n#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1\n');header.chmod(0o600)
            native = root / 'native.h';native.write_text('static const struct ee_native_contract ee_native_pins={0};\n')
            observer = root / 'root/simulation/usb-start-observe.so'
            command = ['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-shared','-fPIC','-O2','-fno-stack-protector','-mno-outline-atomics','-Wl,--no-undefined','-I',str(HERE),
                '-DUSB_EE_NORMAL_COLD=1','-DUSB_EE_NATIVE_INPUT="'+str(native)+'"','-DUSB_EE_NORMAL_COLD_INPUT="'+str(header)+'"',
                *[str(HERE/n) for n in ('usb-start-observe.c','ee-normal-wake-cold.c','ee-capability-input.c')],
                '/usr/aarch64-linux-gnu/lib/libc.so.6','/usr/aarch64-linux-gnu/lib/libdl.a','/usr/aarch64-linux-gnu/lib/libpthread.a','-o',str(observer)]
            linked = subprocess.run(command,capture_output=True,text=True,timeout=40)
            self.assertEqual(linked.returncode,0,linked.stderr)
            contract = copy.deepcopy(fixture.contract)
            contract.update(source_sha256=MODEL['digest'](HERE/'usb-start-observe.c'),builder_sha256=MODEL['digest'](HERE/'usb-start-observe.py'),observer_sha256=MODEL['digest'](observer),command=command)
            contract['ee_normal_cold'].update(native_allocation_log_commit_required=True,native_allocation_log_commit_version=1,diagnostic_checkpoints=False,
                public_sources={name:MODEL['digest'](HERE/name) for name in MODEL['PUBLIC']},private_header=str(header))
            contract['ee_normal_cold']['private_inputs'].append(MODEL['binding']('ee-private-header',header))
            self.assertTrue(MODEL['allocation_log_commit_proven'](contract))
            result = PROBE['functional_trace_summary'](fixture.capture(trace),contract)
            self.assertTrue(result['no_allocation_proven'],result);self.assertFalse(result['business_complete'])
            for field,value in [('native_allocation_log_commit_required',1),('native_allocation_log_commit_version',True),('public_sources',{}),('diagnostic_checkpoints',1)]:
                bad=copy.deepcopy(contract);bad['ee_normal_cold'][field]=value
                self.assertFalse(PROBE['functional_trace_summary'](fixture.capture(trace),bad)['resource_safe_to_close'])
            original=observer.read_bytes();observer.write_bytes(original+b'tamper')
            self.assertFalse(MODEL['allocation_log_commit_proven'](contract));observer.write_bytes(original)
            original=header.read_text();header.write_text(original+'\n')
            self.assertFalse(MODEL['allocation_log_commit_proven'](contract));header.write_text(original)
            for damaged in (fixture.capture(trace)+fixture.capture(trace),fixture.capture(trace).replace(b'SHA_AFTER_RC=0',b'SHA_AFTER_RC=1'),fixture.capture(trace+pre)):
                self.assertFalse(PROBE['functional_trace_summary'](damaged,contract)['resource_safe_to_close'])
            diag=b'USB_EE_DIAG WAIT_ADMISSION pid=11 tid=11 write_failures=1 cap_mask=2 generation=7 reason=prime\n'
            result=PROBE['functional_trace_summary'](fixture.capture(trace+diag),contract)
            self.assertTrue(result['no_allocation_proven'],result);self.assertEqual(result['diagnostics'][0]['raw'],diag.decode().rstrip())
            self.assertFalse(PROBE['functional_trace_summary'](fixture.capture(trace+diag+diag),contract)['resource_safe_to_close'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
