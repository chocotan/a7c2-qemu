#!/usr/bin/env python3
"""Public synthetic host tests: real /bin/sh + openssl, explicit local fixtures only."""
import ast
import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'p1-rawlog-collector.py'))
TAIL = runpy.run_path(str(HERE / 'p1-tail-source.py'))
FIXTURES = Path(os.environ.get('P1_RAWLOG_TEST_OUTPUT', tempfile.gettempdir()))


class Rawlogs(unittest.TestCase):
    def setUp(self):
        FIXTURES.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='synthetic-', dir=FIXTURES))
        self.paths = {name: str(self.root / (name + '.source')) for name in ('tail', 'broker')}

    def produce(self, *, defect='', broker=True):
        tail = self.paths['tail']
        pmbp = self.paths['broker']
        child = self.root / 'fixture-receiver.sh'
        child.write_text('''#!/bin/sh
pid=$$
line="P1_TAIL pid=$pid family=0 op=identity fixture=1 rc=0 errno=0 caller=0x1"
echo "$line" > "$1"
echo "$line"
line="P1_TAIL pid=$pid family=7 op=receipt records=1 bytes=1 seen=1,0,0,0,0,0,0,0 dropped=0,0,0,0,0,0,0,0 epoch_closed=1 install_verified=0 rc=0 errno=0 caller=(nil)"
echo "$line" >> "$1"
echo "$line"
echo "PMBP_RAW pid=$pid PMBP_IO class=explicit-functional op=1 gen=1 ordinal=0 offset=0 requested=0 observed=0 rc=-1 errno=95 poison=1" > "$2"
exit 37
''', encoding='ascii')
        source = (HERE / 'guest/update-storage-bootstrap').read_text(encoding='ascii')
        decorated = TAIL['bootstrap_source'](source, API['TAIL'])
        self.assertEqual(source.count('wait "$receiver_pid"'), 1)
        self.assertEqual(decorated.count('wait "$receiver_pid"'), 1)
        block = decorated[decorated.index('        receiver_pid=$!'):decorated.index('    */insmod|*/rmmod)')]
        block = block.replace('exit "$receiver_rc" ;;', 'exit "$receiver_rc"')
        block = block.replace('receiver_snapshot "$receiver_pid"', ':')
        collector = (HERE / 'p1-rawlog-collector.sh').read_text(encoding='ascii')
        collector = collector.replace('/simulation/p1-tail/receiver.log', tail).replace('/simulation/pmbp-runtime/receiver.log', pmbp)
        if defect == 'changed':
            shim = self.root / 'fixture-openssl.sh'
            shim.write_text('#!/bin/sh\n/usr/bin/openssl "$@"\nrc=$?\nif [ "$1" = enc ]; then echo changed >> "' + tail + '"; fi\nexit "$rc"\n')
            shim.chmod(0o700)
            collector = collector.replace('/usr/bin/openssl', str(shim))
        collector_path = self.root / 'fixture-collector.sh'
        collector_path.write_text(collector, encoding='ascii')
        block = block.replace('/simulation/p1-tail/sources/p1-rawlog-collector.sh', str(collector_path))
        mutation = {'missing': 'rm -f "' + tail + '"', 'empty': ': > "' + tail + '"',
                    'large': 'dd if=/dev/zero of="' + tail + '" bs=262145 count=1 2>/dev/null',
                    'symlink': 'mv "' + tail + '" "' + tail + '.real"; ln -s "' + tail + '.real" "' + tail + '"',
                    'receipt': 'sed -i /op=receipt/d "' + tail + '"',
                    'crosspid': "sed -i 's/^PMBP_RAW pid=[0-9]*/PMBP_RAW pid=1/' \"" + pmbp + '\"'}.get(defect, ':')
        block = block.replace('        (\n', '        ' + mutation + '\n        (\n')
        # Install inherited preload only after the receiver exit; the real first subshell action clears it.
        block = block.replace('            unset LD_PRELOAD', '            LD_PRELOAD=/synthetic-must-be-unset.so\n            export LD_PRELOAD\n            unset LD_PRELOAD')
        profile = API['BROKER'] if broker else 'off'
        script = self.root / 'fixture-parent.sh'
        script.write_text('''#!/bin/sh
bb=fixture_bb
fixture_bb() { "$@"; }
A7C2_P1_TAIL_PROFILE=''' + API['TAIL'] + '''
A7C2_P1_TAIL_PMBP_PROFILE=''' + profile + '''
A7C2_P1_PMBP_PROFILE=''' + profile + '''
/bin/sh "''' + str(child) + '" "' + tail + '" "' + pmbp + '" &\n' + block, encoding='ascii')
        proc = subprocess.run(['/bin/sh', str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        (self.root / 'serial.raw').write_bytes(proc.stdout)
        (self.root / 'stderr.raw').write_bytes(proc.stderr)
        (self.root / 'returncode.txt').write_text(str(proc.returncode) + '\n')
        self.assertEqual(proc.returncode, 37)
        self.assertNotIn(b'synthetic-must-be-unset', proc.stdout + proc.stderr)
        return proc.stdout

    def decode(self, raw, broker=True):
        return API['decode'](raw, tail_profile=API['TAIL'], pmbp_profile=API['BROKER'] if broker else None, paths=self.paths)

    def test_two_full_files_and_real_exit(self):
        raw = self.produce()
        result = self.decode(raw)
        self.assertEqual(result['receiver_returncode'], 37)
        self.assertGreater(result['receiver_pid'], 0)
        for name, data in result['payloads'].items():
            self.assertEqual(data, Path(self.paths[name]).read_bytes())
        self.assertTrue(API['terminal'](raw))
        self.assertEqual(raw.count(b'UPDATE_SD_RECEIVER_WAIT '), 1)

    def test_tail_only_and_default_off(self):
        result = self.decode(self.produce(broker=False), broker=False)
        self.assertEqual(set(result['payloads']), {'tail'})
        source = (HERE / 'guest/update-storage-bootstrap').read_text()
        self.assertEqual(TAIL['bootstrap_source'](source), source)
        self.assertNotIn('P1_RAWLOG', source)
        with self.assertRaises(ValueError):
            API['decode'](b'', tail_profile=None)

    def test_source_failures_keep_original_rc_and_raw(self):
        for defect in ('missing', 'empty', 'large', 'symlink'):
            with self.subTest(defect=defect):
                self.setUp()
                raw = self.produce(defect=defect)
                self.assertIn(b' rc=37\n', raw)
                self.assertIn(b'P1_RAWLOG ERROR ', raw)
                with self.assertRaises(ValueError):
                    self.decode(raw)

    def test_changed_or_actor_invalid_files(self):
        for defect in ('changed', 'receipt', 'crosspid'):
            with self.subTest(defect=defect):
                self.setUp()
                raw = self.produce(defect=defect)
                with self.assertRaises(ValueError):
                    self.decode(raw)
                if defect == 'changed':
                    self.assertIn(b' rc=74\n', raw)

    def test_tail_mirror_uses_production_declarations(self):
        sd = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
        preamble = sd['OBSERVER'].split('static int watched(', 1)[0]
        tail = (HERE / 'p1-tail-observer.inc').read_text().split('#include "p1-tail-budget.h"', 1)[0]
        source = self.root / 'production-declarations.c'
        source.write_text(preamble + tail, encoding='ascii')
        argv = ['cc', '-std=c11', '-fno-builtin', '-fsyntax-only',
                '-Werror=implicit-function-declaration', str(source)]
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        (self.root / 'production-declarations.command.txt').write_text(repr(argv) + '\n')
        (self.root / 'production-declarations.raw').write_bytes(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_original_c_mirror_helpers(self):
        observer = (HERE / 'p1-tail-observer.inc').read_text()
        tail = observer[observer.index('static void tail_rawlog('):observer.index('\n}', observer.index('static void tail_rawlog(')) + 2]
        broker = (HERE / 'pmbp-broker.c').read_text()
        pmbp = broker[broker.index('static void pmbp_rawlog('):broker.index('\n}', broker.index('static void pmbp_rawlog(')) + 2]
        source = '''#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#define PMBP_PROFILE "virtual-p1-pmbp-block-slice-v1"
static struct {int enabled;} state;
static int selected(void){return 1;}
static int rawclose(int fd){return (int)syscall(SYS_close,fd);}
static void *next(const char *name){return dlsym(RTLD_DEFAULT,name);}
''' + tail.replace('/simulation/p1-tail/receiver.log', self.paths['tail']) + '\n' + pmbp.replace('/simulation/pmbp-runtime/receiver.log', self.paths['broker']) + '''
int main(void) {
 errno=91;tail_rawlog("original-tail-bytes\\n");assert(errno==91);
 state.enabled=1;unsetenv("A7C2_P1_PMBP_PROFILE");
 errno=92;pmbp_rawlog("PMBP_IO fixture=1\\n");assert(errno==92);
 assert(access("''' + self.paths['broker'] + '''",F_OK)==-1);
 setenv("A7C2_P1_PMBP_PROFILE",PMBP_PROFILE,1);
 errno=93;pmbp_rawlog("PMBP_IO fixture=1\\n");assert(errno==93);
 return 0;
}
'''
        src = self.root / 'exact-helper-fixture.c'
        src.write_text(source, encoding='ascii')
        argv = ['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(src), '-ldl', '-o', str(self.root / 'helper')]
        (self.root / 'compile-command.txt').write_text(repr(argv) + '\n')
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        (self.root / 'compile.raw').write_bytes(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        subprocess.run([str(self.root / 'helper')], check=True, timeout=10)
        self.assertEqual(Path(self.paths['tail']).read_bytes(), b'original-tail-bytes\n')
        self.assertRegex(Path(self.paths['broker']).read_text(), r'^PMBP_RAW pid=[1-9][0-9]* PMBP_IO fixture=1\n$')

    def test_mutation_matrix(self):
        raw = self.produce()
        first_data = next(line for line in raw.splitlines(keepends=True) if line.startswith(b'P1_RAWLOG DATA '))
        after = next(line for line in raw.splitlines(keepends=True) if line.startswith(b'P1_RAWLOG AFTER '))
        begin = next(line for line in raw.splitlines(keepends=True) if line.startswith(b'P1_RAWLOG BEGIN '))
        done = next(line for line in raw.splitlines(keepends=True) if line.startswith(b'P1_RAWLOG DONE '))
        nonce = re.search(rb'nonce=([^ ]+)', begin)[1]
        mutations = {
            'duplicate-data': raw.replace(first_data, first_data*2, 1),
            'duplicate-begin': raw.replace(begin, begin*2, 1),
            'duplicate-end': raw.replace(done, done*2, 1),
            'bad-payload-hash': re.sub(rb'sha256=[0-9a-f]{64}', b'sha256=' + b'0'*64, raw),
            'bad-hash': raw.replace(after, re.sub(rb'sha256=[0-9a-f]{64}', b'sha256=' + b'0'*64, after), 1),
            'changed-inode': raw.replace(after, re.sub(rb'inode=[0-9]+', b'inode=1', after), 1),
            'bad-pid': raw.replace(done, re.sub(rb'pid=[0-9]+', b'pid=1', done), 1),
            'bad-nonce': raw.replace(done, done.replace(nonce, b'00000000-0000-4000-8000-000000000000'), 1),
            'base64': raw.replace(first_data, first_data.replace(b'b64=', b'b64=!'), 1),
            'partial': raw[:raw.index(done)],
            'partial-last': raw.rstrip(b'\n'),
            'injection': raw.replace(after, b'arbitrary-line\n' + after, 1),
            'out-of-order': raw.replace(first_data, b'', 1).replace(after, first_data + after, 1),
            'bad-actor': raw.replace(b'actor=guest-postwait', b'actor=host', 1),
            'bad-length': raw.replace(after, re.sub(rb'bytes=[0-9]+', b'bytes=1', after), 1),
            'missing-start': raw.replace(b'UPDATE_SD_RECEIVER_START ', b'unknown-start ', 1),
        }
        for name, changed in mutations.items():
            with self.subTest(name=name):
                (self.root / (name + '.raw')).write_bytes(changed)
                with self.assertRaises(ValueError):
                    self.decode(changed)

    def test_host_postrun_real_call_and_independent_ledger(self):
        raw = self.produce()
        # Explicit fixture path binding; production never takes a path override.
        globals_ = API['collect_postrun'].__globals__
        old = globals_['PATHS']; globals_['PATHS'] = self.paths
        ledger = {'partition_before': [{'id': 23, 'offset': 1024, 'bytes': 512, 'sha256': 'a'*64}],
                  'partition_after': [{'id': 23, 'offset': 1024, 'bytes': 512, 'sha256': 'b'*64}]}
        try:
            result = API['collect_postrun'](raw, self.root / 'readback', tail_profile=API['TAIL'], pmbp_profile=API['BROKER'], ledger=ledger)
            self.assertTrue(result['rawlogs_complete'], result)
            merged = result['tail_postrun']['tail_merge']
            self.assertEqual(merged['postrun_ledger'], ledger)
            self.assertTrue(merged['receipt_present'])
            for row in result['files'].values():
                path = Path(row['local_path'])
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row['sha256'])
            failed = API['collect_postrun'](raw.replace(b'P1_RAWLOG DONE ', b'broken '), self.root / 'refused', tail_profile=API['TAIL'], pmbp_profile=API['BROKER'], ledger=ledger)
            self.assertFalse(failed['rawlogs_complete'])
            self.assertFalse((self.root / 'refused').exists())
            no_ledger = API['collect_postrun'](raw, self.root / 'without-ledger', tail_profile=API['TAIL'], pmbp_profile=API['BROKER'])
            self.assertIsNone(no_ledger['tail_postrun']['tail_merge'])
        finally:
            globals_['PATHS'] = old

    def test_popen_failure_cleanup_and_live_context_guards(self):
        api = runpy.run_path(str(HERE / 'pmbp-integration.py'))
        contexts = api['forget_actual'].__globals__['_ACTUAL']
        source = (HERE / 'p1-update-execution.py').read_text()
        tree = ast.parse(source)
        cleanup = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                       and ast.unparse(node.test) == 'pmbp_actual is not None and (process is None or process.poll() is not None)')
        code = compile(ast.Module(body=[cleanup], type_ignores=[]), 'exact-E-finally-cleanup', 'exec')
        token = object()
        # Explicit synthetic prepared capability; the real false source-coverage gate is unchanged.
        contexts[token] = {'fixture': 'prepared-before-Popen'}
        process = None
        argv = [str(self.root / 'nonexistent-Popen-fixture')]
        (self.root / 'popen-command.txt').write_text(repr(argv) + '\n')
        with self.assertRaises(FileNotFoundError):
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        exec(code, {'pmbp_actual': token, 'process': process, 'PMBP': api})
        self.assertNotIn(token, contexts)
        class Owner:
            def __init__(self, rc): self.rc = rc
            def poll(self): return self.rc
        for context in ({'owner': (1, 1)}, {'commands': []}, {'activated': False}, {'activated': True}):
            with self.subTest(context=context):
                token = object(); contexts[token] = context
                with self.assertRaises(ValueError):
                    api['forget_actual'](token, owner=None)
                self.assertIn(token, contexts)
                contexts.pop(token)
        token = object(); contexts[token] = {}
        with self.assertRaises(ValueError):
            api['forget_actual'](token, owner=Owner(None))
        self.assertIn(token, contexts)
        exec(code, {'pmbp_actual': token, 'process': Owner(None), 'PMBP': api})
        self.assertIn(token, contexts)
        exec(code, {'pmbp_actual': token, 'process': Owner(1), 'PMBP': api})
        self.assertNotIn(token, contexts)
        with self.assertRaises(ValueError):
            api['forget_actual'](object(), owner=None)

    def test_source_seams_and_guest_limits(self):
        collector = (HERE / 'p1-rawlog-collector.sh').read_bytes()
        collector.decode('ascii')
        self.assertLessEqual(max(map(len, collector.splitlines())), 512)
        self.assertIsNotNone(re.search(rb'nonce.* /proc/sys/kernel/random/uuid', collector))
        subprocess.run(['/bin/sh', '-n', str(HERE / 'p1-rawlog-collector.sh')], check=True)
        source = (HERE / 'p1-update-execution.py').read_text()
        self.assertLess(source.index("result['partition_after']"), source.index("['collect_postrun']("))
        self.assertLess(source.index("PMBP['prepare_actual']"), source.index('subprocess.Popen('))
        self.assertIn('stdin=subprocess.DEVNULL', source)
        self.assertIn("'p1-rawlog-collector.sh'", (HERE / 'p1-tail-source.py').read_text())
        self.assertIn('/simulation/p1-tail/receiver.log', (HERE / 'p1-tail-observer.inc').read_text())
        self.assertIn('/simulation/pmbp-runtime/receiver.log', (HERE / 'pmbp-broker.c').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
