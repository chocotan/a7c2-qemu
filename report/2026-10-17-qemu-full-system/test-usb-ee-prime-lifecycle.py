"""Synthetic host regressions for prime pointer reuse; private replay is opt-in only."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import unittest

CANONICAL = Path(__file__).with_name('usb-ap-probe.py')
API = runpy.run_path(str(CANONICAL))
MODE = API['FUNCTIONAL_MODE']
PARSE = API['functional_trace_summary']
MODEL = runpy.run_path(str(CANONICAL.with_name('usb-ee-normal-cold.py')))
NATIVE_EVENTS = ('RECV_RETURN', 'SOURCE', 'SIZE', 'FREE_ENTER', 'FREE_RETURN')
PRIME_POINTER = b'0x123480'
MODEL_POINTER = b'0x123400'


def public_fixture():
    source = CANONICAL.with_name('test-usb-ap-probe.py').read_text()
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.ClassDef) and n.name == 'FunctionalContracts')
    node.body = [n for n in node.body if isinstance(n, ast.FunctionDef) and n.name in ('trace', 'capture')]
    namespace = dict(unittest=unittest, API=dict(FUNCTIONAL_MODE=MODE), hashlib=hashlib)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), '<public-host-fixture>', 'exec'), namespace)
    return namespace['FunctionalContracts']()


FIXTURE = public_fixture()
CONTRACT = dict(ee_normal_cold=dict(profile=MODE, generation=7, admission_source='kerneldefault',
    admission_version=1, kernel_uipc=MODEL['KERNEL_UIPC'], private_inputs=[
        dict(role='ee-private-envelope', sha256='a' * 64), dict(role='ee-private-model', sha256='b' * 64)]))


def field(row, key, value):
    changed, count = re.subn(rb'(?<= )' + key.encode() + rb'=[^ \n]+', key.encode() + b'=' + str(value).encode(), row)
    assert count == 1, (key, row)
    return changed


def event_rows(trace, event, pointer=None):
    return [row for row in trace.splitlines(keepends=True)
            if row.startswith(b'USB_EE ' + event.encode() + b' ') and
            (pointer is None or b' message=' + pointer + b' ' in row)]


def change_event(trace, event, key, value, occurrence=-1, pointer=None):
    row = event_rows(trace, event, pointer)[occurrence]
    lines = trace.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line == row]
    assert len(matches) == 1
    lines[matches[0]] = field(row, key, value)
    return b''.join(lines)


def kernel_trace(cycles=1, same_pointer=False, size_first=False):
    """Extend the public callback fixture with explicit kernel lease evidence."""
    lines = []
    prefix = f'mode={MODE} source_class=kerneldefault generation=7 '

    def ee(event, body, tid=11):
        return f'USB_EE {event} tid={tid} mono=1.000000000 clock_ok=1 pid=11 {body}\n'.encode()

    def lifecycle():
        entry = ee('RECV_ENTER', 'queue=0x80020002 output=0x8000 timeout=-1 caller=0x1000', 22)
        receive = ee('RECV_RETURN', 'queue=0x80020002 output=0x8000 message=0x123480 message_read=1 caller=0x1000 rc=0 errno=0', 22)
        source = ee('SOURCE', 'queue=0x80020002 message=0x123480 source=0x90040193 caller=0x1000', 22)
        size = ee('SIZE', 'queue=0x80020002 message=0x123480 source=0x90040193 source_known=1 size=12 copy12=0 raw=unavailable caller=0x1000', 22)
        metadata = [source, size]
        if size_first:
            metadata = [field(field(size, 'source', 0), 'source_known', 0), source]
        return [entry, receive, *metadata,
            ee('FREE_ENTER', 'owner=0x80020002 message=0x123480 recv_match=0 source=0 source_known=0 size=0 size_known=0 caller=0x1000', 33),
            ee('FREE_RETURN', 'owner=0x80020002 message=0x123480 recv_match=0 caller=0x1000 rc=0 errno=2', 33)]

    for row in FIXTURE.trace().splitlines(keepends=True):
        if row.startswith((b'USB_EE QUEUE_', b'USB_EE RECV_ENTER ')):
            continue
        if row.startswith(b'USB_EE FUNCTIONAL_GATE '):
            for _ in range(cycles):
                lines.extend(lifecycle())
            lines.extend([
                ee('FUNCTIONAL_INIT', prefix + 'fd=7 map=0x120000 bytes=2097152 allocator=0x124000 pool0=524288 pool1=131072 dynamic_id=0x1234 abi_verified=1 fd_verified=1 map_verified=1'),
                ee('FUNCTIONAL_PRIME', prefix + 'message=0x123480 message_generation=13 receive_event=13 free_event=14 receiver_tid=0x16 free_actor_tid=0x21 source=0x90040193 size=12 source_known=1 size_known=1 receive_rc=0 free_rc=0 free_returned=1'),
                ee('FUNCTIONAL_GATE', prefix + 'registration=not_applicable receiver_tid=0x16 waiter_tid=0xb promise=0x3344 reader=0x3649218 registration_event=0 unlock_event=15 original_rc=5 original_20a3_return=1 original_wait_unlocked=1 envelope_sha256=' + 'a' * 64 + ' model_sha256=' + 'b' * 64)])
            continue
        if row.startswith(b'USB_EE FUNCTIONAL_'):
            row = row.replace(f'mode={MODE} generation=7 '.encode(), prefix.encode())
        if row.startswith(b'USB_EE FUNCTIONAL_ALLOCATE_RETURN '):
            row = row.rstrip(b'\n') + b' resources_valid=1\n'
        if row.startswith(b'USB_EE RECV_RETURN '):
            lines.append(ee('RECV_ENTER', 'queue=0x80020002 output=0x8000 timeout=-1 caller=0x1000', 22))
        if row.startswith(b'USB_EE SIZE '):
            row = row.replace(b'copy12=1 raw=0600a3200000000000000000', b'copy12=0 raw=unavailable')
        if row.startswith(b'USB_EE FUNCTIONAL_RECEIVE '):
            lines.append(ee('FUNCTIONAL_COPY', prefix + 'method=model-owned-native-cpu-copy message=0x123400 message_generation=15 receive_event=16 receiver_tid=0x16 source=0x90bf0274 bytes=12 rc=0', 22))
        if b' attempted=' in row:
            received = b' received=1 ' in row
            free = b' free=1 ' in row
            waited = row.startswith(b'USB_EE FUNCTIONAL_READER ')
            row = row.rstrip(b'\n') + (f' owned_copy={int(received)} wait_returned={int(waited)} message_generation=15 lease_pid=11 lease_generation=7 free_actor_tid={"0x16" if free else "0"}\n').encode()
        if row.startswith(b'USB_EE WAIT_RETURN '):
            reader = next(r for r in FIXTURE.trace().splitlines(keepends=True) if r.startswith(b'USB_EE FUNCTIONAL_READER '))
            reader = reader.replace(b'FUNCTIONAL_READER ', b'FUNCTIONAL_WAIT_RETURN ').replace(f'mode={MODE} generation=7 '.encode(), prefix.encode())
            for key, value in (('reader', 0), ('output', 0), ('retired', 0), ('pending', 1)):
                reader = field(reader, key, value)
            lines.append(reader.rstrip(b'\n') + b' owned_copy=1 wait_returned=1 message_generation=15 lease_pid=11 lease_generation=7 free_actor_tid=0x16\n')
        lines.append(row)
        if row.startswith(b'USB_EE FREE_ENTER '):
            lines.append(ee('FUNCTIONAL_FREE_TICKET', prefix + 'message=0x123400 message_generation=15 receive_event=16 slot=0 owner=0x80020002 receiver_tid=0x16 free_actor_tid=0x16 source=0x90bf0274 size=12 observed=1 state=2', 22))
    if same_pointer:
        lines = [row.replace(MODEL_POINTER, PRIME_POINTER) for row in lines]
    return b''.join(re.sub(rb'mono=\d+\.\d{9}', f'mono=1.{i:09d}'.encode(), row)
                    for i, row in enumerate(lines))


class PrimeLifecycleTests(unittest.TestCase):
    def summary(self, trace, contract=CONTRACT):
        return PARSE(FIXTURE.capture(trace), contract, diagnostic_only=True)

    def refused(self, trace, contract=CONTRACT):
        result = self.summary(trace, contract)
        self.assertFalse(result['business_complete'], result)
        self.assertFalse(result['native_content_verified'], result)
        self.assertFalse(result['resource_safe_to_close'], result)
        return result

    def cycle(self, trace, occurrence=-1):
        selected = [event_rows(trace, event, PRIME_POINTER)[occurrence] for event in NATIVE_EVENTS]
        return b''.join(row for row in trace.splitlines(keepends=True) if row in selected)

    def test_single_and_completed_historical_reuses_preserve_all_trace_bytes(self):
        for cycles in (1, 2, 3):
            for size_first in (False, True):
                with self.subTest(cycles=cycles, size_first=size_first):
                    trace = kernel_trace(cycles=cycles, size_first=size_first)
                    result = self.summary(trace)
                    self.assertTrue(result['native_content_verified'], result)
                    self.assertTrue(result['resource_safe_to_close'], result)
                    self.assertTrue(result['native_message_released'], result)
                    self.assertFalse(result['business_complete'])
                    self.assertEqual(result['trace_sha256'], hashlib.sha256(trace).hexdigest())
                    self.assertEqual(len(result['prime_native_lifecycles']), cycles)
                    self.assertEqual([cycle['selected'] for cycle in result['prime_native_lifecycles']], [False] * (cycles - 1) + [True])
                    self.assertTrue(all(result['checks'].values()), result)

    def test_prime_pointer_can_be_reallocated_as_one_distinct_model_lease(self):
        trace = kernel_trace(cycles=2, same_pointer=True)
        result = self.summary(trace)
        self.assertTrue(result['native_content_verified'], result)
        self.assertTrue(result['resource_safe_to_close'], result)
        self.assertEqual(len(result['prime_native_lifecycles']), 2)

    def test_historical_lifecycles_may_have_distinct_valid_sources_and_sizes(self):
        trace = kernel_trace(cycles=2)
        trace = change_event(trace, 'SOURCE', 'source', '0x90030001', 0, PRIME_POINTER)
        trace = change_event(trace, 'SIZE', 'source', '0x90030001', 0, PRIME_POINTER)
        trace = change_event(trace, 'SIZE', 'size', 16, 0, PRIME_POINTER)
        result = self.summary(trace)
        self.assertTrue(result['native_content_verified'], result)
        self.assertEqual([(c['source'], c['size']) for c in result['prime_native_lifecycles']], [('0x90030001', 16), ('0x90040193', 12)])

    def test_missing_records_in_any_prior_or_latest_lifecycle_are_rejected(self):
        trace = kernel_trace(cycles=2)
        for occurrence in (0, 1):
            for event in NATIVE_EVENTS:
                row = event_rows(trace, event, PRIME_POINTER)[occurrence]
                with self.subTest(occurrence=occurrence, event=event):
                    self.refused(trace.replace(row, b''))
        for occurrence in (0, 1):
            row = event_rows(trace, 'RECV_ENTER')[occurrence]
            with self.subTest(entry=occurrence):
                self.refused(trace.replace(row, b''))

    def test_overlapping_or_orphaned_native_uses_are_rejected(self):
        trace = kernel_trace(cycles=2)
        newest = self.cycle(trace)
        pr = event_rows(trace, 'RECV_RETURN', PRIME_POINTER)[-1]
        for event in NATIVE_EVENTS:
            row = event_rows(trace, event, PRIME_POINTER)[0]
            with self.subTest(event=event):
                self.refused(trace.replace(pr, row + pr))
        self.refused(trace.replace(newest, newest + newest))
        source = event_rows(trace, 'SOURCE', PRIME_POINTER)[-1]
        self.refused(trace.replace(pr, pr + source))

    def test_all_order_permutations_except_source_size_swap_are_rejected(self):
        import itertools
        trace = kernel_trace()
        cycle = self.cycle(trace)
        rows = {event: event_rows(trace, event, PRIME_POINTER)[0] for event in NATIVE_EVENTS}
        for order in itertools.permutations(NATIVE_EVENTS):
            if order in (NATIVE_EVENTS, ('RECV_RETURN', 'SIZE', 'SOURCE', 'FREE_ENTER', 'FREE_RETURN')):
                continue
            with self.subTest(order=order):
                self.refused(trace.replace(cycle, b''.join(rows[event] for event in order)))

    def test_future_prime_records_and_complete_future_uses_are_rejected(self):
        trace = kernel_trace(cycles=2)
        prime = event_rows(trace, 'FUNCTIONAL_PRIME')[0]
        for event in (*NATIVE_EVENTS, 'complete'):
            fragment = self.cycle(trace) if event == 'complete' else event_rows(trace, event, PRIME_POINTER)[-1]
            for where in ('after-prime', 'end'):
                with self.subTest(event=event, where=where):
                    changed = trace.replace(prime, prime + fragment) if where == 'after-prime' else trace + fragment
                    self.refused(changed)
        self.refused(trace.replace(self.cycle(trace), b'') + self.cycle(trace))

    def test_same_pointer_reuse_between_prime_and_model_allocation_is_rejected(self):
        trace = kernel_trace(same_pointer=True)
        prime = event_rows(trace, 'FUNCTIONAL_PRIME')[0]
        fragment = event_rows(trace, 'RECV_RETURN', PRIME_POINTER)[0]
        self.refused(trace.replace(prime, prime + fragment))

    def test_model_pointer_reuse_does_not_hide_behind_prime_partition(self):
        for same_pointer in (False, True):
            trace = kernel_trace(cycles=2, same_pointer=same_pointer)
            pointer = PRIME_POINTER if same_pointer else MODEL_POINTER
            for event in NATIVE_EVENTS:
                row = event_rows(trace, event, pointer)[-1]
                with self.subTest(same_pointer=same_pointer, event=event):
                    self.refused(trace + row)
            rows = b''.join(event_rows(trace, event, pointer)[-1] for event in NATIVE_EVENTS)
            self.refused(trace + rows)

    def test_every_historical_actor_field_source_size_and_return_is_checked(self):
        trace = kernel_trace(cycles=2)
        cases = (
            ('RECV_RETURN', 'tid', 99), ('RECV_RETURN', 'pid', 12), ('RECV_RETURN', 'queue', 0),
            ('RECV_RETURN', 'rc', -28), ('RECV_RETURN', 'message_read', 0), ('RECV_RETURN', 'output', 0),
            ('SOURCE', 'tid', 99), ('SOURCE', 'pid', 12), ('SOURCE', 'queue', 0), ('SOURCE', 'source', 0),
            ('SIZE', 'tid', 99), ('SIZE', 'queue', 0), ('SIZE', 'source', '0x90030001'),
            ('SIZE', 'source_known', 0), ('SIZE', 'size', 0), ('SIZE', 'size', 2097152),
            ('FREE_ENTER', 'tid', 99), ('FREE_ENTER', 'pid', 12), ('FREE_ENTER', 'owner', 0),
            ('FREE_ENTER', 'recv_match', 1), ('FREE_ENTER', 'source', 1), ('FREE_ENTER', 'size', 1),
            ('FREE_RETURN', 'tid', 99), ('FREE_RETURN', 'pid', 12), ('FREE_RETURN', 'owner', 0),
            ('FREE_RETURN', 'rc', -28), ('FREE_RETURN', 'recv_match', 1), ('FREE_RETURN', 'caller', 0))
        for occurrence in (0, 1):
            for event, key, value in cases:
                with self.subTest(occurrence=occurrence, event=event, key=key):
                    self.refused(change_event(trace, event, key, value, occurrence, PRIME_POINTER))

    def test_latest_cycle_must_match_prime_snapshot_actor_source_size_and_generation(self):
        trace = kernel_trace(cycles=2)
        for key, value in (('source', '0x90030001'), ('size', 16), ('receiver_tid', '0x17'),
                           ('free_actor_tid', '0x22'), ('message_generation', 12), ('receive_event', 12),
                           ('free_event', 13), ('free_event', 15), ('free_returned', 0),
                           ('receive_rc', -28), ('free_rc', -28), ('source_known', 0), ('size_known', 0)):
            with self.subTest(key=key, value=value):
                self.refused(change_event(trace, 'FUNCTIONAL_PRIME', key, value))

    def test_epoch_pid_and_immutable_model_lease_gates_remain_strict(self):
        trace = kernel_trace(cycles=2)
        for event, key, value in (
            ('FUNCTIONAL_PRIME', 'generation', 8), ('FUNCTIONAL_GATE', 'generation', 8),
            ('FUNCTIONAL_COPY', 'pid', 12), ('FUNCTIONAL_COPY', 'generation', 8),
            ('FUNCTIONAL_COPY', 'message_generation', 999), ('FUNCTIONAL_COPY', 'receive_event', 15),
            ('FUNCTIONAL_FREE_TICKET', 'generation', 8), ('FUNCTIONAL_FREE_TICKET', 'pid', 12),
            ('FUNCTIONAL_FREE_TICKET', 'message_generation', 999), ('FUNCTIONAL_FREE_TICKET', 'receive_event', 999),
            ('FUNCTIONAL_FREE_TICKET', 'receiver_tid', '0x17'), ('FUNCTIONAL_FREE_TICKET', 'free_actor_tid', '0x17'),
            ('FUNCTIONAL_FREE_TICKET', 'owner', 0), ('FUNCTIONAL_FREE_TICKET', 'observed', 0),
            ('FUNCTIONAL_FREE_TICKET', 'state', 1), ('FUNCTIONAL_FREE_TICKET', 'slot', 8),
            ('FUNCTIONAL_FREE', 'lease_pid', 12), ('FUNCTIONAL_FREE', 'lease_generation', 8),
            ('FUNCTIONAL_FREE', 'message_generation', 999)):
            with self.subTest(event=event, key=key):
                self.refused(change_event(trace, event, key, value))
        self.refused(change_event(trace, 'FREE_RETURN', 'rc', -28, pointer=MODEL_POINTER))
        self.refused(trace + b'USB_EE CAP bounded=1\n')
        bad = copy.deepcopy(CONTRACT)
        bad['ee_normal_cold']['generation'] = 8
        self.refused(trace, bad)

    def test_sha_cannot_be_rewritten_or_ignored(self):
        trace = kernel_trace(cycles=2)
        raw = FIXTURE.capture(trace)
        digest = hashlib.sha256(trace).hexdigest().encode()
        for changed in (raw.replace(digest, b'0' * 64, 1), raw + raw,
                        raw.replace(b'TRACE_SHA_AFTER_RC=0', b'TRACE_SHA_AFTER_RC=1')):
            result = PARSE(changed, CONTRACT, diagnostic_only=True)
            self.assertFalse(result['trace_integrity'])
            self.assertFalse(result['resource_safe_to_close'])

    @unittest.skipUnless(os.environ.get('USB_V10_PRIME_ACTUAL_RAW'), 'private replay requires explicit environment paths')
    def test_explicit_private_replay_stays_diagnostic_only(self):
        raw = Path(os.environ['USB_V10_PRIME_ACTUAL_RAW']).read_bytes()
        manifest = json.loads(Path(os.environ['USB_V10_PRIME_ACTUAL_MANIFEST']).read_text())
        result = PARSE(raw, manifest['usb_start_observe'], diagnostic_only=True)
        self.assertTrue(result['trace_integrity'], result)
        self.assertTrue(result['native_content_verified'], result)
        self.assertTrue(result['resource_safe_to_close'], result)
        self.assertTrue(result['diagnostic_only'])
        self.assertFalse(result['business_complete'])
        self.assertEqual(len(result['prime_native_lifecycles']), 2)
        for key in ('physical_compatibility_verified', 'original_cp_history_verified', 'stage_actual',
                    'full_boot_verified', 'capture_verified', 'host_enumerated', 'authentication_verified',
                    'guest_root_over_usb_verified', 'strict_can_publish'):
            self.assertFalse(result[key], key)


if __name__ == '__main__':
    unittest.main(verbosity=2)
