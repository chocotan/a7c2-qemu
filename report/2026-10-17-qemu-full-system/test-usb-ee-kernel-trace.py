#!/usr/bin/env python3
"""HostFixture traces from current C wrappers -> production parser; no guest/VM.

USB_EE_KERNEL_TRACE_HOST_FIXTURE_DIR may reuse the retained output of the
canonical kernelqueue host test in a single combined regression run.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'usb-ap-probe.py'))
MODEL = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
HARNESS = runpy.run_path(str(HERE / 'test-usb-ee-kernelqueue.py'))


class KernelTraceHost(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = None
        reuse = os.environ.get('USB_EE_KERNEL_TRACE_HOST_FIXTURE_DIR')
        if reuse:
            root = Path(reuse)
            receipt = json.loads((root / 'summary.json').read_text())
            assert receipt['host_only'] and not receipt['vm_started'] and not receipt['guest_executed']
        else:
            cls.temporary = tempfile.TemporaryDirectory(prefix='usb-ee-kernel-trace-host-')
            root = Path(cls.temporary.name)
            (root / 'input.h').write_text(HARNESS['trace_fixture_header']())
            observer = (HERE / 'usb-ee-zero-observe.inc').read_text()
            wait = 'static uintptr_t fixture_target_wait(' + observer.split('static uintptr_t ee_wait(', 1)[1].split('\n#ifndef USB_OBSERVE_HOST_TEST', 1)[0]
            assert wait.count('(uintptr_t)__builtin_return_address(0)') == 1
            (root / 'fixture-target-wait.inc').write_text(wait.replace('(uintptr_t)__builtin_return_address(0)', '(app_base+0x35492cc)'))
            for kind, flags in (('strict', ['-O2', '-fstrict-aliasing']),
                                ('asan', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'])):
                binary = root / kind
                command = ['cc', '-std=gnu11', '-pthread', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-Wno-unused-variable', '-Wno-misleading-indentation',
                    '-Wno-missing-field-initializers', '-I', str(HERE), '-I', str(root),
                    '-DUSB_EE_NORMAL_COLD_INPUT="' + str(root / 'input.h') + '"',
                    '-DEE_COLD_ADMISSION_SOURCE=EE_NWC_KERNELDEFAULT', *flags,
                    str(HERE / 'test-usb-ee-kernelqueue.c'), str(HERE / 'ee-normal-wake-cold.c'),
                    str(HERE / 'ee-capability-input.c'), '-ldl', '-o', str(binary)]
                subprocess.run(command, check=True, capture_output=True, timeout=40)
                for mode in (0, 27):
                    subprocess.run([str(binary), str(root / f'kernel-{kind}-{mode}.log'), str(mode)],
                        check=True, capture_output=True, timeout=10,
                        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
        cls.traces = {kind: (root / f'kernel-{kind}-0.log').read_bytes() for kind in ('strict', 'asan')}
        cls.registration_trace = (root / 'kernel-strict-27.log').read_bytes()
        cls.contract = dict(ee_normal_cold=dict(profile=API['FUNCTIONAL_MODE'], generation=7,
            admission_source='kerneldefault', admission_version=1, kernel_uipc=MODEL['KERNEL_UIPC'],
            private_inputs=[dict(role='ee-private-' + name, sha256=value) for name, value in HARNESS['HOST_TRACE_HASHES'].items()]))

    @classmethod
    def tearDownClass(cls):
        if cls.temporary:
            cls.temporary.cleanup()

    def capture(self, trace):
        sha = hashlib.sha256(trace).hexdigest()
        path = '/dev/qemu-simulation/usb-start-observe.log'
        return (f'USB_AP_START_TRACE_SHA_BEFORE\nSHA256({path})= {sha}\nUSB_AP_START_TRACE_SHA_BEFORE_RC=0\n'.encode() +
            b'USB_AP_START_TRACE_BEGIN\n' + trace + b'USB_AP_START_TRACE_RC=0\nUSB_AP_START_TRACE_END\n' +
            f'USB_AP_START_TRACE_SHA_AFTER\nSHA256({path})= {sha}\nUSB_AP_START_TRACE_SHA_AFTER_RC=0\n'.encode())

    def summary(self, trace=None, contract=None, **kwargs):
        return API['functional_trace_summary'](self.capture(self.traces['strict'] if trace is None else trace),
                                              self.contract if contract is None else contract, **kwargs)

    def row(self, trace, event):
        rows = [row for row in trace.splitlines(keepends=True) if row.startswith(b'USB_EE ' + event.encode() + b' ')]
        self.assertEqual(len(rows), 1, event)
        return rows[0]

    def mutate(self, trace, event, field, value):
        row = self.row(trace, event)
        changed, count = re.subn(rb'(?<= )' + field.encode() + rb'=[^ \n]+', field.encode() + b'=' + str(value).encode(), row)
        self.assertEqual(count, 1, (event, field))
        return trace.replace(row, changed)

    def test_executed_strict_and_asan_wrapper_logs_are_consumed(self):
        for kind, trace in self.traces.items():
            with self.subTest(kind=kind):
                result = self.summary(trace)
                self.assertTrue(result['business_complete'], result)
                self.assertTrue(result['native_content_verified'])
                self.assertTrue(result['native_message_released'])
                self.assertEqual(result['kernel_registration'], 'not_applicable')
                self.assertEqual(result['resource_proof'], 'pre-free-generation-ticket-native-free-zero')
                self.assertIn(b'copy12=0 raw=unavailable', trace)
                self.assertIn(b'method=model-owned-native-cpu-copy', trace)
                self.assertIn(b'owned_copy=1 wait_returned=1', trace)
                for row in trace.splitlines():
                    self.assertLess(len(row), 1024, row)
                for name in ('strict_can_publish', 'stage_actual', 'original_cp_history_verified',
                             'physical_compatibility_verified', 'full_boot_verified', 'capture_verified',
                             'host_enumerated', 'authentication_verified', 'guest_root_over_usb_verified'):
                    self.assertFalse(result[name], name)
                diagnostic = self.summary(trace, diagnostic_only=True)
                self.assertTrue(diagnostic['native_content_verified'])
                self.assertFalse(diagnostic['business_complete'])

    def test_every_required_proof_and_duplicate_is_rejected(self):
        trace = self.traces['strict']
        for event in ('PREINIT', 'FUNCTIONAL_INIT', 'FUNCTIONAL_PRIME', 'FUNCTIONAL_GATE',
                      'FUNCTIONAL_ALLOCATE_ENTER', 'FUNCTIONAL_ALLOCATE_RETURN', 'FUNCTIONAL_SEND_ENTER',
                      'FUNCTIONAL_SEND_RETURN', 'FUNCTIONAL_TRIGGER', 'FUNCTIONAL_COPY', 'FUNCTIONAL_RECEIVE',
                      'FUNCTIONAL_FREE_TICKET', 'FUNCTIONAL_FREE', 'FUNCTIONAL_WAIT_RETURN', 'FUNCTIONAL_READER',
                      'PROMISE_REGISTER', 'WAIT_ENTER', 'WAIT_RETURN'):
            row = self.row(trace, event)
            for changed in (trace.replace(row, b''), trace + row):
                with self.subTest(event=event, duplicate=changed.endswith(row)):
                    self.assertFalse(self.summary(changed)['business_complete'])
        for event in ('RECV_RETURN', 'SOURCE', 'SIZE', 'FREE_ENTER', 'FREE_RETURN'):
            rows = [row for row in trace.splitlines(keepends=True) if row.startswith(b'USB_EE ' + event.encode() + b' ')]
            self.assertEqual(len(rows), 2)
            for row in rows:
                with self.subTest(event=event, row=row):
                    self.assertFalse(self.summary(trace.replace(row, b''))['business_complete'])
                    self.assertFalse(self.summary(trace + row)['business_complete'])

    def test_typed_source_payload_pid_epoch_reference_and_native_returns(self):
        trace = self.traces['strict']
        cases = [
            ('FUNCTIONAL_GATE', 'source_class', 'callback'), ('FUNCTIONAL_GATE', 'registration_event', 1),
            ('FUNCTIONAL_GATE', 'registration', 'callback'), ('FUNCTIONAL_GATE', 'original_rc', 0),
            ('FUNCTIONAL_GATE', 'original_20a3_return', 0), ('FUNCTIONAL_GATE', 'original_wait_unlocked', 0),
            ('FUNCTIONAL_GATE', 'envelope_sha256', 'c' * 64), ('FUNCTIONAL_GATE', 'model_sha256', 'c' * 64),
            ('FUNCTIONAL_INIT', 'fd_verified', 0), ('FUNCTIONAL_INIT', 'abi_verified', 0),
            ('FUNCTIONAL_INIT', 'map_verified', 0), ('FUNCTIONAL_INIT', 'map', 0),
            ('FUNCTIONAL_INIT', 'allocator', 0), ('FUNCTIONAL_INIT', 'dynamic_id', 0),
            ('FUNCTIONAL_INIT', 'bytes', 2097151), ('FUNCTIONAL_INIT', 'pool0', 1), ('FUNCTIONAL_INIT', 'pool1', 1),
            ('FUNCTIONAL_PRIME', 'free_returned', 0), ('FUNCTIONAL_PRIME', 'free_rc', -28),
            ('FUNCTIONAL_PRIME', 'source', 0), ('FUNCTIONAL_PRIME', 'source_known', 0),
            ('FUNCTIONAL_PRIME', 'size', 0), ('FUNCTIONAL_PRIME', 'receive_event', 0),
            ('FUNCTIONAL_ALLOCATE_RETURN', 'resources_valid', 0),
            ('FUNCTIONAL_COPY', 'generation', 8), ('FUNCTIONAL_COPY', 'pid', 1),
            ('FUNCTIONAL_COPY', 'message_generation', 999), ('FUNCTIONAL_COPY', 'method', 'readmem'),
            ('FUNCTIONAL_COPY', 'source', '0x90bf0275'), ('FUNCTIONAL_COPY', 'bytes', 11),
            ('FUNCTIONAL_COPY', 'rc', 12), ('FUNCTIONAL_COPY', 'receiver_tid', 1),
            ('FUNCTIONAL_RECEIVE', 'actual_wire', '0600a3200000000001000000'),
            ('FUNCTIONAL_RECEIVE', 'actual_bytes', 13), ('FUNCTIONAL_RECEIVE', 'actual_source', '0x90040193'),
            ('FUNCTIONAL_RECEIVE', 'actual_consumer', 1), ('FUNCTIONAL_RECEIVE', 'owned_copy', 0),
            ('FUNCTIONAL_FREE_TICKET', 'slot', 8), ('FUNCTIONAL_FREE_TICKET', 'receive_event', 999),
            ('FUNCTIONAL_FREE_TICKET', 'message_generation', 999), ('FUNCTIONAL_FREE_TICKET', 'owner', 1),
            ('FUNCTIONAL_FREE_TICKET', 'free_actor_tid', 1), ('FUNCTIONAL_FREE_TICKET', 'observed', 0),
            ('FUNCTIONAL_FREE_TICKET', 'state', 1), ('FUNCTIONAL_FREE', 'free_rc', -28),
            ('FUNCTIONAL_FREE', 'lease_generation', 8), ('FUNCTIONAL_FREE', 'lease_pid', 1),
            ('FUNCTIONAL_SEND_RETURN', 'rc', -28), ('FUNCTIONAL_WAIT_RETURN', 'wait_returned', 0),
            ('FUNCTIONAL_WAIT_RETURN', 'rc', 13), ('FUNCTIONAL_READER', 'wait_returned', 0),
            ('FUNCTIONAL_READER', 'reader', 0), ('FUNCTIONAL_READER', 'output', 2),
            ('PROMISE_REGISTER', 'caller', '0x36492b8'), ('WAIT_RETURN', 'future', '0x33445567'),
            ('WAIT_RETURN', 'caller', '0x36492c8'),
        ]
        for event, field, value in cases:
            with self.subTest(event=event, field=field):
                self.assertFalse(self.summary(self.mutate(trace, event, field, value))['business_complete'])
        # TLS metadata on the other free thread is unavailable; its return must still be real zero.
        free = [row for row in trace.splitlines(keepends=True) if row.startswith(b'USB_EE FREE_RETURN ')][-1]
        bad = trace.replace(free, free.replace(b'rc=0 ', b'rc=-28 '))
        self.assertFalse(self.summary(bad)['native_message_released'])
        for name in ('FUNCTIONAL_COPY', 'FUNCTIONAL_FREE_TICKET'):
            self.assertFalse(self.summary(trace.replace(self.row(trace, name), b''))['resource_safe_to_close'])

    def test_source_selection_and_target_registration_never_fallback(self):
        trace = self.traces['strict']
        callback = runpy.run_path(str(HERE / 'test-usb-ap-probe.py'))['FunctionalContracts']()
        callback.setUp()
        self.assertFalse(self.summary(callback.trace())['business_complete'])
        self.assertTrue(API['functional_trace_summary'](callback.capture(callback.trace()), callback.contract)['business_complete'])
        for changes in (dict(admission_source='callback', kernel_uipc=None), dict(admission_source='unknown'),
                        dict(admission_version=True), dict(kernel_uipc=None)):
            contract = copy.deepcopy(self.contract)
            contract['ee_normal_cold'].update(changes)
            self.assertFalse(self.summary(trace, contract)['business_complete'])
        for event in ('FUNCTIONAL_INIT', 'FUNCTIONAL_PRIME', 'FUNCTIONAL_COPY', 'FUNCTIONAL_FREE_TICKET', 'FUNCTIONAL_WAIT_RETURN'):
            row = self.row(trace, event)
            self.assertFalse(self.summary(trace.replace(row, row.replace(b'source_class=kerneldefault ', b'')))['business_complete'])
        queue = b''.join(row for row in self.registration_trace.splitlines(keepends=True) if row.startswith((b'USB_EE QUEUE_ENTER ', b'USB_EE QUEUE_RETURN ')))
        # Keep actor identity correct while introducing the real registration event body.
        pid = re.search(rb' pid=(\d+) ', trace)[1]
        queue = re.sub(rb' pid=\d+ ', b' pid=' + pid + b' ', queue)
        self.assertFalse(self.summary(trace.replace(self.row(trace, 'FUNCTIONAL_GATE'), queue + self.row(trace, 'FUNCTIONAL_GATE')))['business_complete'])

    def test_target_preinit_binding_initializations_and_sha_remain_strict(self):
        trace = self.traces['strict']
        extra = b'USB_START INITIALIZED tid=9 pid=9 passive=1\n'
        result = self.summary(extra + trace + extra.replace(b'pid=9', b'pid=8'))
        self.assertTrue(result['business_complete'], result)
        self.assertEqual(result['initializations']['total'], 3)
        self.assertEqual(result['initializations']['unselected_pids'], [8, 9])
        self.assertFalse(self.summary(trace + trace.splitlines(keepends=True)[0])['business_complete'])
        self.assertFalse(self.summary(trace.replace(b'both_entries=1', b'both_entries=0'))['business_complete'])
        raw = self.capture(trace).replace(b'USB_AP_START_TRACE_SHA_AFTER\n', b'USB_AP_START_TRACE_SHA_AFTER\nOBS interleaved\n')
        result = API['functional_trace_summary'](raw, self.contract)
        self.assertFalse(result['trace_integrity'])
        self.assertFalse(result['resource_safe_to_close'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
