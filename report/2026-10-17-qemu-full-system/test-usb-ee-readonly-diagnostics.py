#!/usr/bin/env python3
"""Pure host parser and fake-QMP diagnostic checks; no VM or private log replay."""
import ast
import hashlib
import os
from pathlib import Path
import re
import runpy
import socket
import stat
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODE = 'ee-normal-wake-cold-functional-v1'
API = dict(re=re, hashlib=hashlib, os=os, Path=Path, stat=stat, struct=struct, socket=socket,
           runpy=runpy, HERE=HERE, FUNCTIONAL_MODE=MODE, MSC_PHASES=('baseline', 'vbus_on', 'msc_selected', 'vbus_off'))


def function_source(path, name):
    text = path.read_text()
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(text, node)


for name in ('functional_trace_summary', 'resource_trace_summary', 'classify_usb_message',
             'process_identity', 'peer_pid', 'capture_native_observer_log'):
    exec(compile(function_source(HERE / 'usb-ap-probe.py', name), '<canonical-host-function>', 'exec'), API)

# Reuse the public synthetic lease fixture and its three content regressions.
fixture = next(n for n in ast.parse((HERE / 'test-usb-ap-probe.py').read_text()).body
               if isinstance(n, ast.ClassDef) and n.name == 'FunctionalContracts')
fixture.name = 'PublicRegressions'
names = {'trace', 'capture', 'summary', 'test_native_send_receive_reader_and_free_match_same_lease',
         'test_retired_or_send_zero_does_not_replace_original_content_and_free',
         'test_original_event_aliases_and_missing_wait_are_business_failures'}
fixture.body = [n for n in fixture.body if isinstance(n, ast.FunctionDef) and n.name in names]
namespace = dict(unittest=unittest, API=API, hashlib=hashlib)
exec(compile(ast.fix_missing_locations(ast.Module(body=[fixture], type_ignores=[])), '<public-fixture>', 'exec'), namespace)
PublicRegressions = namespace['PublicRegressions']


def fixture_setup(self):
    self.contract = dict(ee_normal_cold=dict(generation=7, private_inputs=[
        dict(role='ee-private-envelope', sha256='a' * 64), dict(role='ee-private-model', sha256='b' * 64)]))


PublicRegressions.setUp = fixture_setup


class TraceRepair(unittest.TestCase):
    def setUp(self):
        self.fixture = PublicRegressions()
        self.fixture.setUp()
        self.contract = self.fixture.contract

    def summary(self, trace):
        return API['functional_trace_summary'](self.fixture.capture(trace), self.contract)

    def noallocation(self):
        keep = (b'USB_START ', b'USB_EE PREINIT ', b'USB_EE PROMISE_REGISTER ',
                b'USB_EE WAIT_ENTER ', b'USB_EE RECV_ENTER ')
        return b''.join(line for line in self.fixture.trace().splitlines(keepends=True) if line.startswith(keep))

    def assert_refused(self, result):
        self.assertFalse(result['resource_safe_to_close'], result)
        self.assertFalse(result['no_allocation_proven'], result)
        self.assertFalse(result['business_complete'], result)
        self.assertIn('error', result)

    def test_38_initializations_select_only_unique_preinit_actor_and_keep_every_record(self):
        for trace, business in ((self.noallocation(), False), (self.fixture.trace(), True)):
            others = b''.join((f'USB_START INITIALIZED tid={pid} pid={pid} passive=0 functional_model=1 mode={MODE}\n').encode()
                              for pid in range(60, 97))
            trace = others + trace
            result = self.summary(trace)
            self.assertEqual(result['target_actor'], dict(pid=11, app_base='0x100000'))
            self.assertEqual(result['initializations']['total'], 38)
            self.assertEqual(result['initializations']['target'], 1)
            self.assertEqual(result['initializations']['unselected'], 37)
            self.assertEqual(result['initializations']['unselected_pids'], list(range(60, 97)))
            self.assertEqual(len(result['initializations']['records']), 38)
            self.assertEqual(sum(row['selected'] for row in result['initializations']['records']), 1)
            self.assertEqual(result['trace_sha256'], hashlib.sha256(trace).hexdigest())
            self.assertEqual(result['resource_safe_to_close'], business, result)
            self.assertFalse(result['no_allocation_proven'], result)
            self.assertEqual(result['business_complete'], business)

    def test_actor_ambiguity_unknown_events_duplicate_fields_and_caps_reject(self):
        for trace in (self.noallocation(), self.fixture.trace()):
            lines = trace.splitlines(keepends=True)
            pre = next(line for line in lines if line.startswith(b'USB_EE PREINIT '))
            app = next(line for line in lines if line.startswith(b'USB_START AP_PREINIT_CONFIRMED '))
            recv = next(line for line in lines if line.startswith(b'USB_EE RECV_ENTER '))
            init = lines[0]
            changes = (
                trace.replace(recv, recv.replace(b'pid=11', b'pid=12')), trace + init, trace + pre,
                trace.replace(app, b''), trace + app, trace.replace(app, app.replace(b'base=0x100000', b'base=0x100008')),
                trace.replace(app, app.replace(b'pid=11', b'pid=12')),
                trace.replace(pre, pre.replace(b'pid=11 ', b'pid=11 pid=11 ', 1)),
                trace.replace(pre, pre.replace(b'pid=11 ', b'pid=11 pid=12 ', 1)),
                trace.replace(recv, recv.replace(b'pid=11 ', b'pid=11 pid=11 ', 1)),
                trace.replace(recv, recv.replace(b'pid=11 ', b'')),
                trace + b'USB_EE UNKNOWN tid=11 mono=2.000000000 clock_ok=1 pid=11\n',
                trace.replace(init, init.replace(b'passive=0', b'passive=1')),
                trace.replace(init, init.replace(b'functional_model=1', b'functional_model=0')),
                trace.replace(init, init.replace(MODE.encode(), b'unknown')),
                trace.replace(pre, b''), trace.replace(init, b''),
                trace + b'USB_START INITIALIZED tid=60 pid=60 passive=0 pid=61\n',
                trace + b'USB_EE CAP bounded=1\n', trace + b'USB_START CAP bounded=1\n')
            for i, changed in enumerate(changes):
                with self.subTest(allocation=b'FUNCTIONAL_ALLOCATE_ENTER' in trace, case=i):
                    self.assert_refused(self.summary(changed))

    def test_required_fields_and_generation_remain_strict(self):
        trace = self.fixture.trace()
        for line in trace.splitlines(keepends=True):
            if line.startswith(b'USB_EE '):
                missing = line.split(b'clock_ok=1 ', 1)[1].split()[1]
                with self.subTest(event=line.split()[1]):
                    self.assert_refused(self.summary(trace.replace(line, line.replace(missing + b' ', b'', 1))))
        self.assert_refused(self.summary(trace.replace(b'generation=7', b'generation=8', 1)))
        self.assert_refused(self.summary(self.noallocation().replace(b'functional_model=1 mode=', b'functional_model=1 generation=8 mode=', 1)))

    def test_sha_after_obs_is_conservatively_rejected_and_hashes_stay_exact(self):
        for trace in (self.noallocation(), self.fixture.trace()):
            raw = self.fixture.capture(trace)
            digest = hashlib.sha256(trace).hexdigest().encode()
            obs = b'OBS FULL_REMOTE_STATE_REQUEST tid=724 source=0xa1e057 bytes=1504 command=0x2300 caller=0x7f7b6f4a04\n'
            self.assertEqual(API['functional_trace_summary'](raw, self.contract)['resource_safe_to_close'], trace == self.fixture.trace())
            for i, changed in enumerate((raw.replace(digest, b'0' * 64, 1),
                    raw.rsplit(digest, 1)[0] + b'0' * 64 + raw.rsplit(digest, 1)[1],
                    self.fixture.capture(trace, cat_rc=1), raw.replace(b'SHA_AFTER_RC=0', b'SHA_AFTER_RC=1'),
                    raw.replace(b'USB_AP_START_TRACE_SHA_BEFORE\n', b''), raw + raw,
                    raw.replace(b'app_base=0x100000', b'app_base=0x100008'),
                    raw.replace(b'USB_AP_START_TRACE_SHA_AFTER\n', b'USB_AP_START_TRACE_SHA_AFTER\n' + obs),
                    self.fixture.capture(trace + obs))):
                with self.subTest(case=i):
                    self.assert_refused(API['functional_trace_summary'](changed, self.contract))

    def test_unique_early_guard_still_requires_one_actor(self):
        init = self.fixture.trace().splitlines(keepends=True)[0]
        guard = init + b'USB_START GUARD_FAILED tid=11 reason=EE UIPC original path/size/SHA256\n'
        self.assertFalse(self.summary(guard)['no_allocation_proven'])
        for bad in (guard + init, init.replace(b'pid=11 ', b'pid=60 ') + guard,
                    guard.replace(b'EE UIPC original path/size/SHA256', b'unknown later failure')):
            self.assert_refused(self.summary(bad))

    def test_foreign_queue_pairs_stay_passive_and_pid_strict(self):
        trace = self.fixture.trace()
        pair = b''.join(line.replace(b'queue=0x80020002', b'queue=0x81000001')
                        for line in trace.splitlines(keepends=True) if line.startswith((b'USB_EE QUEUE_ENTER ', b'USB_EE QUEUE_RETURN ')))
        self.assertTrue(self.summary(pair + trace)['business_complete'])
        self.assert_refused(self.summary(pair.replace(b'pid=11', b'pid=12') + trace))
        self.assertFalse(self.summary(trace.replace(b'queue=0x80020002 handle_out=', b'queue=0x81000001 handle_out='))['business_complete'])

    def test_real_preinit_emitter_one_common_pid_both_profiles(self):
        source = (HERE / 'usb-ee-zero-observe.inc').read_text()
        emit = 'static int ee_emit(' + source.split('static int ee_emit(', 1)[1].split('static int32_t ee_queue(', 1)[0]
        preinit = re.search(r'static void ee_preinit\(void\) \{.*?\n\}', source, re.S)[0]
        prefix = r'''
#define _GNU_SOURCE
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
static int logfd=-1;
static unsigned ee_records,ee_essential,ee_capped,ee_console_records,ee_console_essential;
static unsigned ee_installed=1;
static uintptr_t app_base=0x100000,ee_uipc_base=0x200000;
static void fatal(const char *why){(void)why;assert(0);}
'''
        main = r'''
int main(int argc,char **argv){assert(argc==2);logfd=open(argv[1],O_CREAT|O_EXCL|O_WRONLY,0600);assert(logfd>=0);errno=74;ee_preinit();assert(errno==74);assert(!close(logfd));return 0;}
'''
        for define, profile, limit in (('USB_EE_NORMAL_COLD', MODE, 32), ('USB_EE_ZERO_OBSERVER', 'ee-zero-publication-passive-v1', 16)):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                c = root / 'emitter.c'
                c.write_text(f'#define {define} 1\n#define EE_ESSENTIAL_LIMIT {limit}u\n' + prefix + emit + preinit + main)
                compiled = subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(root / 'emitter')], capture_output=True, text=True, timeout=30)
                self.assertEqual(compiled.returncode, 0, compiled.stderr)
                run = subprocess.run([str(root / 'emitter'), str(root / 'trace')], capture_output=True, timeout=10)
                self.assertEqual(run.returncode, 0, run.stderr)
                line = (root / 'trace').read_bytes()
                self.assertEqual(line, run.stderr)
                self.assertEqual(line.count(b' pid='), 1)
                self.assertIn(('mode=' + profile).encode(), line)
                self.assertIn(b'ee_can_publish=0', line)


class NativeLogSnapshot(unittest.TestCase):
    def fixture(self, folder):
        run = Path(folder) / 'launch/run'
        run.mkdir(parents=True, mode=0o700)
        launch = dict(qmp_socket=str(run / 'qmp.sock'), qmp_parent=str(run), env=dict(QEMU_OUTPUT_DIR=str(run)))
        class Connection:
            def getsockopt(self, *args):
                return struct.pack('3i', os.getpid(), os.getuid(), 0)
        return run, launch, Connection(), API['process_identity'](os.getpid())

    def test_fixed_physical_size_fresh_path_real_bytes_and_reply_are_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            run, launch, connection, identity = self.fixture(folder)
            # Synthetic bytes exercise collection only; they are never actual VM evidence.
            data = bytes(range(256)) * 256
            calls = []
            def qmp(name, args):
                calls.append((name, dict(args)))
                self.assertEqual(name, 'pmemsave')
                self.assertEqual(args, dict(val=0x4102d0000, size=65536, filename='/out/baseline-native-observer-log.bin'))
                (run / Path(args['filename']).name).write_bytes(data)
                return {'return': {}}
            result = API['capture_native_observer_log'](qmp, connection, launch, 'baseline', identity)
            self.assertTrue(result['received'], result)
            self.assertEqual(result['qmp_reply'], {'return': {}})
            self.assertEqual(result['path'], str(run / 'baseline-native-observer-log.bin'))
            self.assertEqual(result['bytes'], 65536)
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(stat.S_IMODE(Path(result['path']).stat().st_mode), 0o600)
            self.assertTrue(result['diagnostic_only']); self.assertTrue(result['raw_log_private'])
            self.assertFalse(result['atomic']); self.assertFalse(result['resource_safe_to_close']); self.assertFalse(result['business_complete'])
            self.assertEqual(len(calls), 1)
            again = API['capture_native_observer_log'](qmp, connection, launch, 'baseline', identity)
            self.assertFalse(again['received']); self.assertEqual(len(calls), 1)
            self.assertEqual(Path(result['path']).read_bytes(), data)

    def test_error_reply_and_transport_failure_keep_raw_failure_and_partial_bytes(self):
        for reply in ({'error': {'class': 'GenericError', 'desc': 'read failed'}}, {'return': -5}, None):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as folder:
                run, launch, connection, identity = self.fixture(folder)
                def qmp(name, args):
                    (run / Path(args['filename']).name).write_bytes(b'partial-original-read')
                    if reply is None:
                        raise RuntimeError('QMP pmemsave: original injected transport failure')
                    return reply
                result = API['capture_native_observer_log'](qmp, connection, launch, 'failure', identity)
                self.assertFalse(result['received']); self.assertIn('error', result)
                self.assertEqual(result['qmp_reply'], reply)
                self.assertEqual(result['sha256'], hashlib.sha256(b'partial-original-read').hexdigest())
                self.assertEqual(Path(result['path']).read_bytes(), b'partial-original-read')
                if reply is None:
                    self.assertIn('original injected transport failure', result['error'])

    def test_ownerwrong_missing_connection_and_invalid_phases_refuse_before_qmp(self):
        with tempfile.TemporaryDirectory() as folder:
            run, launch, connection, identity = self.fixture(folder)
            def forbidden(*args):
                self.fail('Rejected diagnostic issued a QMP command')
            for conn, phase, expected in ((connection, 'baseline', dict(identity, pid=identity['pid'] + 1)),
                    (connection, 'baseline', dict(identity, start_ticks=identity['start_ticks'] + 1)),
                    (None, 'baseline', identity), (connection, '../../dev/sda', identity),
                    (connection, '/dev/mem', identity)):
                result = API['capture_native_observer_log'](forbidden, conn, launch, phase, expected)
                self.assertFalse(result['received']); self.assertRegex(result['error'], r'owner mismatch|connection|phase')
            self.assertEqual(list(run.iterdir()), [])

    def test_mapping_symlinks_old_files_and_shared_run_refuse_before_qmp(self):
        for case in ('mapping', 'qmp_parent', 'symlink', 'existing', 'writable'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                run, launch, connection, identity = self.fixture(folder)
                target = run / 'baseline-native-observer-log.bin'
                original = Path(folder) / 'old'; original.write_bytes(b'preserved')
                if case == 'mapping': launch['env']['QEMU_OUTPUT_DIR'] = str(Path(folder))
                if case == 'qmp_parent': launch['qmp_parent'] = str(Path(folder))
                if case == 'symlink': target.symlink_to(original)
                if case == 'existing': target.write_bytes(b'old snapshot')
                if case == 'writable': run.chmod(0o777)
                def forbidden(*args): self.fail('Rejected mapping issued QMP')
                result = API['capture_native_observer_log'](forbidden, connection, launch, 'baseline', identity)
                self.assertFalse(result['received']); self.assertRegex(result['error'], r'mapping|FileExistsError|directory')
                self.assertEqual(original.read_bytes(), b'preserved')
                if case == 'existing': self.assertEqual(target.read_bytes(), b'old snapshot')

    def test_success_reply_with_wrong_size_cannot_claim_received(self):
        for data in (b'', b'x' * 65537):
            with self.subTest(size=len(data)), tempfile.TemporaryDirectory() as folder:
                run, launch, connection, identity = self.fixture(folder)
                def qmp(name, args):
                    (run / Path(args['filename']).name).write_bytes(data)
                    return {'return': {}}
                result = API['capture_native_observer_log'](qmp, connection, launch, 'failure', identity)
                self.assertFalse(result['received']); self.assertEqual(result['file_bytes'], len(data))
                self.assertIn('65536', result.get('error', result.get('readback_error', '')))
                self.assertFalse(result['resource_safe_to_close'])
                if data:
                    self.assertNotIn('sha256', result)
                else:
                    self.assertEqual(result['bytes'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
