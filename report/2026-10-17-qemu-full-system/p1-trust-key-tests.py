#!/usr/bin/env python3
"""Host only: fixed PEM content, borrowed packet bounds, and original-call ABI.

P1_TRUST_TEST_ROOT optionally supplies an extracted original P1 tree. No VM,
package decoding, target disk or original-root writes occur in these tests.
"""
import copy
import ctypes as C
import ctypes.util
import errno
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

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
ROOT = Path(os.environ.get('P1_TRUST_TEST_ROOT', str(HERE.parents[1] /
    'analysis/scratch/p1-virtual-install-version-fixture-20261106/execution/root')))


class Borrow(C.Structure):
    _fields_ = [('message', C.c_void_p), ('bytes', C.c_size_t), ('sid', C.c_uint),
                ('owner_pid', C.c_int), ('allocation_return', C.c_ulong), ('live', C.c_int)]


class Core(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
            '-fno-builtin', str(HERE / 'p1-trust-key.c'), '-o', str(cls.directory / 'core.so')],
            check=True, capture_output=True)
        cls.core = C.CDLL(str(cls.directory / 'core.so'), use_errno=True)
        cls.crypto = C.CDLL(ctypes.util.find_library('crypto'))
        cls.core.p1_trust_key_read.argtypes = [C.c_char_p, C.c_char_p, C.c_void_p, C.c_void_p, C.c_void_p]
        cls.core.p1_trust_key_reply.argtypes = [C.c_char_p, C.POINTER(Borrow), C.c_uint,
                                               C.c_void_p, C.c_ulong, C.c_void_p]
        cls.profile = M['TRUST_PROFILE'].encode()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def read_key(self, path, profile=None, explicit=True):
        result = (C.c_ubyte * 20)(*([0xa5] * 20))
        C.set_errno(errno.EDOM)
        rc = self.core.p1_trust_key_read(self.profile if explicit else profile, os.fsencode(path),
            C.cast(self.crypto.SHA1, C.c_void_p), C.cast(self.crypto.SHA256, C.c_void_p), result)
        self.assertEqual(C.get_errno(), errno.EDOM)
        return rc, bytes(result)

    def packet(self):
        buffer = (C.c_ubyte * 80)(*([0xa5] * 80))
        pointer = C.addressof(buffer) + 8
        C.memmove(pointer, struct.pack('<5Q', 1, 0, 0, 0, 20), 40)
        borrow = Borrow(pointer, 60, 0x025906be, os.getpid(), 0xabc4, 1)
        return buffer, pointer, borrow

    def test_only_exact_observed_query_is_consumed_once_in_place(self):
        buffer, pointer, borrow = self.packet()
        before = bytes(buffer)
        digest = C.create_string_buffer(bytes.fromhex('bcbcd4528bd6a47463e8498a1a7db3073e3a33d2'))
        C.set_errno(errno.EBUSY)
        self.assertEqual(self.core.p1_trust_key_reply(self.profile, C.byref(borrow), 0x025906be,
            pointer, 0xabf4, digest), 1)
        self.assertEqual(C.get_errno(), errno.EBUSY)
        after = bytes(buffer)
        self.assertEqual(after[:8], before[:8]); self.assertEqual(after[68:], before[68:])
        self.assertEqual(after[16:40], before[16:40])
        self.assertEqual(after[8:16], struct.pack('<Q', 1))
        self.assertEqual(after[40:48], struct.pack('<Q', 20))
        self.assertEqual(after[48:68], digest.raw[:20])
        self.assertFalse(borrow.live)
        self.assertEqual(self.core.p1_trust_key_reply(self.profile, C.byref(borrow), 0x025906be,
            pointer, 0xabf4, digest), 0)
        self.assertEqual(bytes(buffer), after)

    def test_short_unowned_unknown_caller_sid_profile_and_fields_are_atomic_refusals(self):
        cases = [('bytes', n) for n in (0, 20, 40, 59, 61, 4096)] + [
            ('sid', 0), ('owner_pid', os.getpid() + 1), ('allocation_return', 0xabc0), ('live', 0),
            ('message', 0), ('caller', 0xac94), ('send_sid', 0), ('profile', None),
            ('profile', b'official'), ('profile', b'virtual-p1-pinned-key-v2')]
        cases += [('query', i) for i in range(5)]
        for name, value in cases:
            with self.subTest(name=name, value=value):
                buffer, pointer, borrow = self.packet()
                caller, sid, profile = 0xabf4, 0x025906be, self.profile
                if name == 'caller': caller = value
                elif name == 'send_sid': sid = value
                elif name == 'profile': profile = value
                elif name == 'query': C.c_ubyte.from_address(pointer + value * 8).value ^= 2
                else: setattr(borrow, name, value)
                before = bytes(buffer)
                C.set_errno(errno.ERANGE)
                self.assertEqual(self.core.p1_trust_key_reply(profile, C.byref(borrow), sid,
                    pointer, caller, C.create_string_buffer(b'0' * 20)), 0)
                self.assertEqual(C.get_errno(), errno.ERANGE)
                self.assertEqual(bytes(buffer), before)

    def test_wrong_short_long_writable_symlink_and_non_regular_pem_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            for name, data, mode in [('wrong', b'x' * 451, 0o444), ('short', b'x' * 450, 0o444),
                                      ('long', b'x' * 452, 0o444), ('writable', b'x' * 451, 0o644)]:
                target = p / name; target.write_bytes(data); target.chmod(mode)
                self.assertEqual(self.read_key(target), (0, b'\xa5' * 20))
            (p / 'link').symlink_to(p / 'wrong')
            os.mkfifo(p / 'fifo')
            for name in ('link', 'fifo', 'missing', '.'):
                self.assertEqual(self.read_key(p / name), (0, b'\xa5' * 20))
            for profile in (None, b'official', b'strict'):
                self.assertEqual(self.read_key(p / 'wrong', profile, explicit=False), (0, b'\xa5' * 20))

    @unittest.skipUnless((ROOT / M['KEY'][0]).exists(), 'provide extracted P1 root for real Sony PEM test')
    def test_real_independent_readonly_snapshot_derives_sha1_and_rejects_mutation(self):
        original = ROOT / M['KEY'][0]
        data = original.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), M['KEY'][2])
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / 'independently-provisioned.pem'
            snapshot.write_bytes(data); snapshot.chmod(0o444)
            accepted, digest = self.read_key(snapshot)
            self.assertEqual((accepted, digest), (1, hashlib.sha1(data).digest()))
            buffer, pointer, borrow = self.packet()
            self.assertEqual(self.core.p1_trust_key_reply(self.profile, C.byref(borrow), 0x025906be,
                pointer, 0xabf4, C.create_string_buffer(digest)), 1)
            libc = C.CDLL(None, use_errno=True)
            libc.strncmp.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
            self.assertEqual(libc.strncmp(C.create_string_buffer(hashlib.sha1(data).digest()),
                pointer + 40, 20), 0)
            changed_caller = bytes([data[0] ^ 1]) + data[1:]
            self.assertNotEqual(libc.strncmp(C.create_string_buffer(hashlib.sha1(changed_caller).digest()),
                pointer + 40, 20), 0)
            self.assertEqual(bytes(buffer)[48:68], digest)
            os.link(snapshot, Path(td) / 'alias')
            self.assertEqual(self.read_key(snapshot), (0, b'\xa5' * 20))
            (Path(td) / 'alias').unlink()
            snapshot.chmod(0o644); snapshot.write_bytes(data[:-1] + bytes([data[-1] ^ 1])); snapshot.chmod(0o444)
            self.assertEqual(self.read_key(snapshot), (0, b'\xa5' * 20))
            self.assertEqual(original.read_bytes(), data)


class Integration(unittest.TestCase):
    def test_explicit_environment_clears_inherited_model_and_preserves_default(self):
        original = copy.deepcopy(M['ENV'])
        self.assertEqual(M['effective_env'](), original)
        env = M['effective_env'](inherited={M['TRUST_ENV']: M['TRUST_PROFILE'], 'OTHER': 'keep'})
        self.assertNotIn(M['TRUST_ENV'], env); self.assertEqual(env['OTHER'], 'keep')
        self.assertEqual(M['effective_env'](M['TRUST_PROFILE'])[M['TRUST_ENV']], M['TRUST_PROFILE'])
        self.assertEqual(M['ENV'], original)
        for value in ('official', 'strict', False, ''):
            with self.assertRaises(ValueError): M['effective_env'](value)
        with self.assertRaisesRegex(ValueError, 'virtual-install'):
            M['configure']('/absent', {}, '/absent', trust_profile=M['TRUST_PROFILE'])

    def test_all_unknown_calls_forward_full_abi_once_with_return_and_errno(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            original = r'''
#include <assert.h>
#include <errno.h>
#include <string.h>
static int calls[5]; static unsigned char packet[60];
int osal_valloc_msg_wait(unsigned sid,void **out,unsigned n,int wait){calls[0]++;assert(sid==0x25906be && n==60 && wait==-3 && errno==33);*out=packet;errno=5;return -77;}
int osal_snd_sync_msg(unsigned sid,void *p){calls[1]++;assert(sid==0x25906be && p==packet && errno==33);errno=30;return -71;}
int osal_free_msg(unsigned sid,void *p){calls[2]++;assert(sid==0x25906be && p==packet && errno==33);errno=19;return -9;}
int SHA1_Final(unsigned char *d,void *ctx){calls[3]++;assert(ctx==(void*)99 && errno==33);memset(d,0xbc,20);errno=23;return 1;}
int RSA_verify(int type,const unsigned char *d,unsigned dn,const unsigned char *s,unsigned sn,void *rsa){calls[4]++;assert(type==672 && d==(void*)11 && dn==32 && s==(void*)22 && sn==256 && rsa==(void*)33 && errno==33);errno=37;return 0;}
int count(int n){return calls[n];}
'''
            main = r'''
#include <assert.h>
#include <errno.h>
#include <string.h>
int osal_valloc_msg_wait(unsigned,void **,unsigned,int),osal_snd_sync_msg(unsigned,void *),osal_free_msg(unsigned,void *);
int SHA1_Final(unsigned char *,void *),RSA_verify(int,const unsigned char *,unsigned,const unsigned char *,unsigned,void *),count(int);
int main(void){void *p=0;errno=33;assert(osal_valloc_msg_wait(0x25906be,&p,60,-3)==-77 && p && errno==5);
errno=33;assert(osal_snd_sync_msg(0x25906be,p)==-71 && errno==30);errno=33;assert(osal_free_msg(0x25906be,p)==-9 && errno==19);
unsigned char digest[20];errno=33;assert(SHA1_Final(digest,(void*)99)==1 && digest[19]==0xbc && errno==23);
errno=33;assert(RSA_verify(672,(void*)11,32,(void*)22,256,(void*)33)==0 && errno==37);
char dest[6];errno=33;assert(memcpy(dest,"hello",6)==dest && !strcmp(dest,"hello") && errno==33);
assert(strncmp("abc","abd",3)<0 && errno==33);for(int i=0;i<5;i++)assert(count(i)==1);return 0;}
'''
            source = M['observer_source']({'pins': []}, {'pins': []}).replace('GLIBC_2.17', 'GLIBC_2.2.5')
            (p / 'observer.c').write_text(source); (p / 'original.c').write_text(original); (p / 'main.c').write_text(main)
            commands = [
                ['cc', '-shared', '-fPIC', '-fno-builtin', str(p / 'original.c'), '-o', str(p / 'original.so')],
                ['cc', '-shared', '-fPIC', '-O2', '-fno-builtin', '-I', str(HERE), str(p / 'observer.c'),
                 str(HERE / 'p1-trust-key.c'), '-ldl', '-o', str(p / 'observer.so')],
                ['cc', '-fno-builtin', str(p / 'main.c'), str(p / 'original.so'), '-o', str(p / 'main')]]
            for argv in commands: subprocess.run(argv, check=True, capture_output=True)
            for profile in (None, 'official', M['TRUST_PROFILE']):
                env = dict(os.environ, LD_PRELOAD=str(p / 'observer.so'))
                env.pop(M['TRUST_ENV'], None)
                if profile is not None: env[M['TRUST_ENV']] = profile
                result = subprocess.run([str(p / 'main')], env=env, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, (profile, result.stderr))

    def test_passive_compare_copy_records_both_sides_and_keeps_original_result(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); console = p / 'console'; console.touch()
            source = M['observer_source']({'pins': []}, {'pins': []}).replace('GLIBC_2.17', 'GLIBC_2.2.5')
            start = source.index('static int trust_caller(')
            end = source.index('static void trust_hex(', start)
            # Host fixture exercises logging after its gate; native identity is separately pinned/tested.
            source = source[:start] + '''static int trust_caller(void *caller,unsigned long va) {
    Info i={0};return dladdr(caller,&i) && !strcmp(i.file,"HOST_MAIN") && (va==0xac94 || va==0xac18);
}
'''.replace('HOST_MAIN', str(p / 'main')) + source[end:]
            source = source.replace('/dev/console', str(console)).replace('op("' + str(console) + '",1)',
                'op("' + str(console) + '",1025)')
            (p / 'observer.c').write_text(source)
            (p / 'main.c').write_text(r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
int main(void){char a[21]="abcdefghijklmnopqrst",b[21]="abcdefghijklmnopqrsz",out[21];
errno=33;int rc=strncmp(a,b,20);assert(rc<0 && errno==33);printf("%d\n",rc);
errno=33;assert(memcpy(out,a,20)==out && errno==33 && !memcmp(out,a,20));return 0;}
''')
            for argv in (
                ['cc', '-shared', '-fPIC', '-O2', '-fno-builtin', '-I', str(HERE), str(p / 'observer.c'),
                 str(HERE / 'p1-trust-key.c'), '-ldl', '-o', str(p / 'observer.so')],
                ['cc', '-fno-builtin', str(p / 'main.c'), '-o', str(p / 'main')]):
                subprocess.run(argv, check=True, capture_output=True)
            env = dict(os.environ, LD_PRELOAD=str(p / 'observer.so')); env.pop(M['TRUST_ENV'], None)
            result = subprocess.run([str(p / 'main')], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = console.read_text()
            self.assertEqual(text.count('op=strncmp '), 1); self.assertEqual(text.count('op=memcpy '), 1)
            self.assertIn('left=' + b'abcdefghijklmnopqrst'.hex(), text)
            self.assertIn('right=' + b'abcdefghijklmnopqrsz'.hex(), text)
            self.assertIn('rc=' + result.stdout.decode().strip() + ' errno=33', text)
            self.assertIn('length=20 recorded=20 data=' + b'abcdefghijklmnopqrst'.hex(), text)

    def test_sha256_passive_digest_passthrough_and_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); console = p / 'console'; console.touch()
            source = M['observer_source']({'pins': []}, {'pins': []}).replace('GLIBC_2.17', 'GLIBC_2.2.5')
            start = source.index('static int trust_caller(')
            end = source.index('static void trust_hex(', start)
            # Host fixture gates on the original call site symbol; native pins are tested separately.
            source = source[:start] + '''static int trust_caller(void *caller,unsigned long va) {
    Info i={0};return va==0xadf0 && dladdr(caller,&i) && !strcmp(i.file,"HOST_MAIN") &&
        i.symbol && !strcmp(i.symbol,"observed_sha256_call");
}
'''.replace('HOST_MAIN', str(p / 'main')) + source[end:]
            source = source.replace('/dev/console', str(console)).replace('op("' + str(console) + '",1)',
                'op("' + str(console) + '",1025)')
            (p / 'observer.c').write_text(source)
            (p / 'original.c').write_text(r'''
#include <errno.h>
#include <string.h>
static int calls,mode;static const void *arg_data;static size_t arg_bytes;static unsigned char *arg_out;
unsigned char *SHA256(const void *data,size_t bytes,unsigned char *out){
    calls++;arg_data=data;arg_bytes=bytes;arg_out=out;
    if(mode==1){errno=91;return 0;}
    if(mode==2){errno=92;return (unsigned char *)0x1000;}
    memset(out,0x5a,32);errno=23;return out;
}
void use_mode(int m){mode=m;}
int calls_made(void){return calls;}
const void *got_data(void){return arg_data;}
size_t got_bytes(void){return arg_bytes;}
unsigned char *got_out(void){return arg_out;}
''')
            (p / 'main.c').write_text(r'''
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <string.h>
unsigned char *SHA256(const void *,size_t,unsigned char *);
void use_mode(int);int calls_made(void);const void *got_data(void);size_t got_bytes(void);unsigned char *got_out(void);
unsigned char *observed_sha256_call(const void *d,size_t n,unsigned char *o){return SHA256(d,n,o);}
unsigned char *other_sha256_call(const void *d,size_t n,unsigned char *o){return SHA256(d,n,o);}
int main(void){
    static const unsigned char data[5]={1,2,3,4,5};
    unsigned char out[32],other[32];
    memset(out,0xa5,sizeof out);memset(other,0xa5,sizeof other);
    errno=33;assert(observed_sha256_call(data,5,out)==out && errno==23);
    assert(got_data()==data && got_bytes()==5 && got_out()==out);
    assert(out[0]==0x5a && out[31]==0x5a);
    use_mode(1);errno=33;assert(observed_sha256_call(data,5,other)==0 && errno==91);
    use_mode(2);errno=33;assert(observed_sha256_call((void*)11,0,(unsigned char*)22)==(unsigned char*)0x1000 && errno==92);
    use_mode(0);errno=33;assert(other_sha256_call(data,5,other)==other && errno==23);
    assert(calls_made()==4);return 0;}
''')
            for argv in (
                ['cc', '-shared', '-fPIC', '-fno-builtin', str(p / 'original.c'), '-o', str(p / 'original.so')],
                ['cc', '-shared', '-fPIC', '-O2', '-fno-builtin', '-I', str(HERE), str(p / 'observer.c'),
                 str(HERE / 'p1-trust-key.c'), '-ldl', '-o', str(p / 'observer.so')],
                ['cc', '-fno-builtin', '-rdynamic', str(p / 'main.c'), str(p / 'original.so'), '-o', str(p / 'main')]):
                subprocess.run(argv, check=True, capture_output=True)
            env = dict(os.environ, LD_PRELOAD=str(p / 'observer.so')); env.pop(M['TRUST_ENV'], None)
            result = subprocess.run([str(p / 'main')], env=env, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = [line for line in console.read_text().splitlines() if line.startswith('P1_TRUST_KEY ')]
            self.assertEqual(len(lines), 3, console.read_text())
            def fields(line): return dict(part.split('=', 1) for part in line.split(' ')[3:])
            digest = fields(lines[0])
            self.assertEqual(digest['bytes'], '5'); self.assertEqual(digest['actual'], '32')
            self.assertEqual(digest['digest'], '5a' * 32); self.assertEqual(digest['errno'], '23')
            self.assertEqual(digest['out'], digest['returned'])
            self.assertEqual(digest['source_class'], 'original-passive'); self.assertEqual(digest['digest_verified'], '0')
            self.assertEqual((digest['backend'], digest['read_errno']), ('proc-self-mem-pread64', '0'))
            failed, refused = fields(lines[1]), fields(lines[2])
            self.assertEqual((failed['returned'], failed['actual'], failed['digest'], failed['errno']),
                             ('(nil)', '0', '', '91'))
            self.assertEqual((refused['returned'], refused['actual'], refused['digest'], refused['errno']),
                             ('0x1000', '-1', '', '92'))
            self.assertEqual((refused['backend'], refused['read_errno']), ('proc-self-mem-pread64', str(errno.EIO)))

    @unittest.skipUnless((ROOT / M['KEY'][0]).exists(), 'provide extracted P1 root for inverse dev proof')
    def test_dev_contract_pins_actual_receiver_without_relaxing_stock(self):
        D = runpy.run_path(str(HERE / 'dev-update-profile.py'))
        stock = M['trust_contract'](ROOT)
        initializer = M['initialize_contract'](ROOT)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); root = p / 'derived-root'; root.mkdir()
            for name in stock['files']:
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                if name != 'usr/lib/libsdfileinputupdaterapi.so': shutil.copyfile(ROOT / name, target)
            receiver = root / 'usr/lib/libsdfileinputupdaterapi.so'
            receipt = D['derive_receiver'](ROOT / 'usr/lib/libsdfileinputupdaterapi.so', receiver)
            with self.assertRaisesRegex(ValueError, 'identity differs'): M['trust_contract'](root)
            contract = M['dev_trust_contract'](root, receipt)
            self.assertEqual(contract['schema'], 'p1-dev-trust-key-abi-v1')
            self.assertEqual(contract['receiver_proof']['all_other_bytes_identical'], True)
            self.assertEqual(contract['files']['usr/lib/libsdfileinputupdaterapi.so']['sha256'], receipt['output']['sha256'])
            old = {row['symbol']: row for row in stock['pins']}
            new = {row['symbol']: row for row in contract['pins']}
            verify = '_ZN7Updater21SignatureVerification9verifyKeyEPKc'
            signature = '_ZN7Updater21SignatureVerification15VerifySignatureENS_13verify_info_tEPKc'
            self.assertEqual(new[verify], old[verify])
            self.assertNotEqual(new[signature]['text_sha256'], old[signature]['text_sha256'])
            window = bytes.fromhex(new[signature]['code']); offset = 0xae08 - 0xace8
            self.assertEqual(window[offset:offset + 4], bytes.fromhex('20008052'))
            self.assertEqual(window[:offset] + bytes.fromhex('72f1ff97') + window[offset + 4:], bytes.fromhex(old[signature]['code']))
            passive_source = M['trust_service_source'](initializer, contract)
            self.assertNotIn('service_select_profile', passive_source)
            source = M['trust_service_source'](initializer, contract, trust_profile=M['TRUST_PROFILE'])
            self.assertIn('service_select_profile', source)
            self.assertIn('selected() && init_identity && trust_identity && trust_marker()', source)
            self.assertNotIn('int _ZN7Updater25SDFileInputUpdaterManager10Initialize', source)
            self.assertNotIn('int open(', source)
            for name in ('lib/libc-2.25.so', 'lib/libdl-2.25.so', 'lib/ld-2.25.so'):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
            c = p / 'provider.c'; c.write_text(source)
            subprocess.run(['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
                '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-builtin', '-fexceptions', '-funwind-tables', '-shared', '-fPIC',
                '-mno-outline-atomics', '-Wl,--no-undefined', '-I', str(HERE), str(c), str(HERE / 'p1-trust-key.c'),
                str(root / 'lib/libc-2.25.so'), str(root / 'lib/libdl-2.25.so'), str(root / 'lib/ld-2.25.so'),
                '-o', str(p / 'provider.so')], check=True, capture_output=True)
            bad = copy.deepcopy(receipt); bad['output']['sha256'] = '0' * 64
            with self.assertRaises(ValueError): M['dev_trust_contract'](root, bad)
            data = bytearray(receiver.read_bytes()); data[0xaaa0] ^= 1; receiver.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'outside'): M['dev_trust_contract'](root, receipt)
            with self.assertRaisesRegex(ValueError, 'identity differs'): M['trust_contract'](root)

    @unittest.skipUnless((ROOT / M['KEY'][0]).exists(), 'provide extracted P1 public key for activation test')
    def test_explicit_stock_activation_runs_guarded_constructor_with_real_pinned_key(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td); snapshot = p / 'independent.pem'
            original = (ROOT / M['KEY'][0]).read_bytes()
            snapshot.write_bytes(original); snapshot.chmod(0o444)
            source = r'''
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <errno.h>
#include "p1-trust-key.h"
static int init_identity,trust_identity;
static int flag(const char *name){const char *v=getenv(name);return v&&!strcmp(v,"1");}
static void prepare(void) __attribute__((constructor(101)));
static void prepare(void){init_identity=flag("INIT");trust_identity=flag("IDENTITY");}
static int selected(void){return flag("SELECTED");}
static int trust_marker(void){return flag("MARKER");}
static void *next(const char *name){return dlsym(RTLD_DEFAULT,name);}
'''
            source += M['TRUST_ACTIVATION_SOURCE'].replace('P1_TRUST_ASSET', json.dumps(str(snapshot)))
            source += r'''
int main(int argc,char **argv){const char *v=getenv("A7C2_P1_TRUST_PROFILE");
return argc==2&&((v&&!strcmp(v,P1_TRUST_PROFILE))==atoi(argv[1]))?0:86;}
'''
            (p / 'activation.c').write_text(source)
            subprocess.run(['cc', '-O2', '-I', str(HERE), str(p / 'activation.c'),
                str(HERE / 'p1-trust-key.c'), '-Wl,--no-as-needed', '-lcrypto', '-ldl', '-o', str(p / 'activation')],
                check=True, capture_output=True)
            enabled = dict(SELECTED='1', INIT='1', IDENTITY='1', MARKER='1')
            cases = [(enabled, True)] + [(dict(enabled, **{key:'0'}), False) for key in enabled]
            for flags, expected in cases:
                env = dict(os.environ, **flags); env.pop(M['TRUST_ENV'], None)
                result = subprocess.run([str(p / 'activation'), str(int(expected))], env=env, capture_output=True)
                self.assertEqual(result.returncode, 0, (flags, result.stderr))
            snapshot.chmod(0o600); snapshot.write_bytes(original[:-1] + bytes([original[-1] ^ 1])); snapshot.chmod(0o444)
            env = dict(os.environ, **enabled); env.pop(M['TRUST_ENV'], None)
            result = subprocess.run([str(p / 'activation'), '0'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless((ROOT / M['KEY'][0]).exists(), 'provide extracted P1 root for native build test')
    def test_real_contract_build_default_and_explicit_assets_cpio_and_drift(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            snapshot = p / 'provisioned.pem'; snapshot.write_bytes((ROOT / M['KEY'][0]).read_bytes()); snapshot.chmod(0o444)
            signature = M['trust_contract'](ROOT)
            self.assertEqual(len(signature['pins']), 10)
            for profile in (None, M['TRUST_PROFILE']):
                build = p / (profile or 'strict'); build.mkdir(); root = build / 'root'; root.mkdir()
                names = set(signature['files']) | {M['CORE'][0]}
                names |= {row[0] for row in runpy.run_path(str(HERE / 'p1-file-media-contract.py'))['SAMPLES'].values()}
                names |= {'lib/libc-2.25.so', 'lib/libdl-2.25.so', 'lib/ld-2.25.so'}
                for name in names:
                    target = root / name; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
                value = M['install'](root, build, trust_profile=profile, pinned_key=snapshot if profile else None)
                self.assertEqual(M['trust_preflight'](root, value), value)
                self.assertEqual(value['guest_verified'], False)
                self.assertEqual('service_select_profile' in (build / 'p1-sd-observer.c').read_text(), bool(profile))
                if profile:
                    self.assertEqual((root / value['asset']['path'][1:]).stat().st_mode & 0o777, 0o444)
                else:
                    self.assertFalse((root / 'simulation/p1-trust-key/sony-original.pem').exists())
                archive = build / 'trust.gz'; expected = {}
                for name in value['runtime_files']:
                    file = root / name; data = file.read_bytes()
                    expected[name] = dict(mode=file.stat().st_mode, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                U = M['api'](); U['archive'](root, archive)
                self.assertEqual(M['cpio_readback'](archive, expected), expected)
                (root / 'simulation/p1-trust-key/profile').write_text('official\n')
                with self.assertRaisesRegex(ValueError, 'profile drift'): M['trust_preflight'](root, value)
            with self.assertRaisesRegex(ValueError, 'caller mutable'):
                M['install'](ROOT, p, trust_profile=M['TRUST_PROFILE'], pinned_key=ROOT / M['KEY'][0])
            with self.assertRaisesRegex(ValueError, 'independently provisioned'):
                M['install'](ROOT, p, trust_profile=M['TRUST_PROFILE'])


if __name__ == '__main__':
    unittest.main()
