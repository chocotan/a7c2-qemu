"""HOST_TEST synthetic context/receipt tests. Written for parent-only later execution."""
from pathlib import Path
import copy
import importlib.util
import json
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load('HOST_TEST_native_context_v2', HERE / 'check_run_context_v2.py')
case = load('HOST_TEST_native_context_v2_data', HERE / 'integration/host_test_scope_v2_fixture.py')


def all_producers(result):
    return result['M_producer']['entry'] + result['M_producer']['pre_M_store']


class V2ContextJoinTests(unittest.TestCase):
    def test_later_producer_joins_actual_same_run_Main_four_tuple_without_identity_claim(self):
        rows, console, schema = case.joined_case()
        result = checker.correlate(console, case.encode(rows), schema)
        self.assertTrue(result['poweron_Main_context_bound'])
        self.assertEqual(result['poweron_Main_joins'][0]['Main_raw_LF_line'], 2)
        self.assertEqual(result['poweron_Main_joins'][0]['Main_reported_tid'], 345)
        self.assertTrue(all(row['correlation'] == 'context_match_only' for row in all_producers(result)))
        for name in ('PID_TID_uniqueness_verified', 'address_space_uniqueness_verified', 'earlier_AP_identity_verified',
                     'instruction_retirement_verified', 'branchretirement', 'storecompletion',
                     'original_store_or_return_verified', 'capture_verified', 'physical_asic_compatibility_verified'):
            self.assertIs(result[name], False)
        self.assertEqual(result['normal_M_producer_call'], 'unknown')
        self.assertEqual(result['M_business_id'], 'unknown')
        self.assertEqual(result['M_event_key'], 'unknown')

    def test_early_same_base_is_retrospective_only_and_keeps_exact_original_row(self):
        rows, console, schema = case.joined_case(early=True)
        raw = case.encode(rows)
        before = copy.deepcopy(rows)
        result = checker.correlate(console, raw, schema)
        for report in all_producers(result):
            self.assertEqual(report['correlation'], 'retrospective_context_match_only')
            self.assertIs(report['earlier_AP_identity_unknown'], True)
            self.assertEqual(report['raw_fields']['scope_anchor_seen'], '0x0')
            self.assertEqual(report['raw_fields']['identity'], 'unknown')
            self.assertEqual(report['raw_fields'], rows[report['trace_index']])
            self.assertTrue(all(index > report['trace_index'] for index in report['matching_poweron_trace_indices']))
        self.assertEqual(rows, before)
        self.assertEqual(b''.join(bytes.fromhex(record['raw_hex']) for record in result['raw_records']), raw)

    def test_producer_before_poweron_but_after_scope_also_stays_retrospective(self):
        rows, console, schema = case.joined_case(sites=('entry',))
        producer = rows.pop(-2)
        rows.insert(2, producer)
        result = checker.correlate(console, case.encode(rows), schema)
        report, = result['M_producer']['entry']
        self.assertEqual(report['raw_fields']['scope_anchor_seen'], '0x1')
        self.assertEqual(report['correlation'], 'retrospective_context_match_only')
        self.assertIs(report['earlier_AP_identity_unknown'], True)

    def test_absent_TTBR_or_TLS_never_matches_absence_even_with_bound_Main(self):
        for token in ('ttbr0_el1', 'tpidr_el0'):
            for targets in (('M_producer',), ('M_producer', 'poweron_context')):
                rows, console, schema = case.joined_case(early=True)
                for row in rows:
                    if row['kind'] in targets:
                        row.update({token + '_available': '0x0', token + '_raw': 'unknown',
                                    token + '_read_length': '0x0', token + '_api_ok': 'unknown'})
                result = checker.correlate(console, case.encode(rows), schema)
                with self.subTest(token=token, targets=targets):
                    self.assertTrue(all(row['correlation'] == 'raw_uncorrelated' for row in all_producers(result)))
                    self.assertTrue(all(not row['matching_poweron_trace_indices'] for row in all_producers(result)))

    def test_wrong_token_EL1_or_missing_Main_preserves_uncorrelated_raw(self):
        for change in ('ttbr', 'tls', 'EL1', 'no_Main', 'different_Main', 'other_poweron_base'):
            rows, console, schema = case.joined_case(early=True)
            for row in rows:
                if row['kind'] == 'M_producer':
                    if change == 'ttbr':
                        row['ttbr0_el1_raw'] = case.h64(case.TOKENS['ttbr0_el1'] + 1)
                    elif change == 'tls':
                        row['tpidr_el0_raw'] = case.h64(case.TOKENS['tpidr_el0'] + 1)
                    elif change == 'EL1':
                        row.update(case.flags(5))
            if change == 'no_Main':
                console = b'HOST_TEST no dispatch\n'
            elif change == 'different_Main':
                console = console.replace(b'controller=0x0000000040010000', b'controller=0x0000000040010001')
            elif change == 'other_poweron_base':
                power = next(row for row in rows if row['kind'] == 'poweron_context')
                for field in ('candidate_base', 'actual_pc', 'translated_entry_pc'):
                    power[field] = case.h64(int(power[field], 16) + 0x1000)
            raw = case.encode(rows)
            result = checker.correlate(console, raw, schema)
            with self.subTest(change=change):
                self.assertTrue(all(row['correlation'] == 'raw_uncorrelated' for row in all_producers(result)))
                self.assertEqual(result['trace_sha256'], checker.sha(raw))
                self.assertEqual(result['normal_M_producer_call'], 'unknown')

    def test_cpu_base_conflicts_changed_anchor_and_abnormal_end_reject_whole_group_with_bytes(self):
        for change in ('CPU', 'producer_base', 'second_producer_base', 'scope_base', 'anchor_changed',
                       'producer_anchor_changed', 'producer_scope_base_conflict', 'ambiguity', 'fault', 'close'):
            rows, console, schema = case.joined_case(early=True)
            producer = next(row for row in rows if row['kind'] == 'M_producer')
            if change == 'CPU':
                producer['vcpu'] = '0x1'
            elif change == 'producer_base':
                rows[-1]['producer_base'] = case.h64(case.BASE + 0x1000)
            elif change == 'second_producer_base':
                next(row for row in rows if row.get('site') == 'pre_M_store')['candidate_base'] = case.h64(case.BASE + 0x1000)
            elif change == 'scope_base':
                rows[-1]['candidate_base'] = case.h64(case.BASE + 0x1000)
            elif change in ('anchor_changed', 'producer_anchor_changed', 'producer_scope_base_conflict'):
                rows[-1]['stop'] = change
            elif change == 'ambiguity':
                rows[-1]['ambiguous'] = '0x1'
                rows[-1]['producer_conflicting_base'] = case.h64(case.BASE + 0x1000)
            elif change == 'fault':
                rows.insert(-1, dict(kind='fault', reason='HOST_TEST', **case.COMMON))
                rows[-1]['fault_lines'] = '0x1'
                rows[-1]['faults'] = case.h64(1)
            else:
                rows[-1]['close_result'] = 'success'
            raw = case.encode(rows)
            with self.subTest(change=change), self.assertRaises(checker.RejectedTrace) as caught:
                checker.correlate(console, raw, schema)
            self.assertEqual(caught.exception.evidence['raw_hex'], raw.hex())
            self.assertIs(caught.exception.evidence['group_claim_rejected'], True)

    def test_no_M_rows_is_unknown_and_prestore_only_has_no_invented_entry_or_pair(self):
        for sites in ((), ('pre_M_store',)):
            rows, console, schema = case.joined_case(sites=sites)
            result = checker.correlate(console, case.encode(rows), schema)
            with self.subTest(sites=sites):
                self.assertEqual(result['M_producer']['entry'], [])
                self.assertEqual(len(result['M_producer']['pre_M_store']), len(sites))
                self.assertEqual(result['producer_observation_status'], 'observed_raw' if sites else 'unknown')
                self.assertEqual(result['entry_pre_store_invocation_pairing'], 'unknown')
                self.assertFalse(result['original_store_or_return_verified'])
                self.assertFalse(result['storecompletion'])

    def test_site_lists_remain_independent_with_different_ordinals(self):
        rows, console, schema = case.joined_case(sites=('entry', 'entry', 'pre_M_store'))
        entries = [row for row in rows if row['kind'] == 'M_producer' and row['site'] == 'entry']
        entries[1]['ordinal'] = '0x2'
        result = checker.correlate(console, case.encode(rows), schema)
        self.assertEqual(len(result['M_producer']['entry']), 2)
        self.assertEqual(len(result['M_producer']['pre_M_store']), 1)
        self.assertEqual(result['entry_pre_store_invocation_pairing'], 'unknown')

    def test_without_any_scope_binding_early_rows_stay_raw_uncorrelated(self):
        rows, console, schema = case.joined_case(early=True)
        rows = [row for row in rows if row['kind'] not in ('candidate', 'entry', 'late')]
        rows[-1].update(candidate_found='0x0', candidate_base=case.h64(0), lr0_records='0x0',
                        late0_records='0x0', late_sequence='0x0')
        result = checker.correlate(console, case.encode(rows), schema)
        self.assertFalse(result['poweron_Main_context_bound'])
        self.assertTrue(all(row['correlation'] == 'raw_uncorrelated' and row['earlier_AP_identity_unknown']
                            for row in all_producers(result)))

    def test_legacy_scope_and_late_still_require_earlier_bound_poweron(self):
        rows, console, schema = case.joined_case()
        power = rows.pop(2)
        rows.insert(-1, power)
        result = checker.correlate(console, case.encode(rows), schema)
        self.assertEqual(result['observations'], [])
        self.assertEqual(len(result['uncorrelated_observation_indices']), 2)
        self.assertTrue(all(row['correlation'] == 'retrospective_context_match_only' for row in all_producers(result)))

    def test_all_four_Main_fields_and_full_35_field_validation_are_preserved(self):
        for field, value in (('controller', case.h64(0x40010001)), ('caller_raw', case.h64(case.BASE + 0x1e79358)),
                             ('raw_u32', '0x01100090')):
            rows, console, schema = case.joined_case()
            next(row for row in rows if row['kind'] == 'poweron_context')[field] = value
            if field == 'raw_u32':
                next(row for row in rows if row['kind'] == 'poweron_context')['raw_x2'] = '0xaabbccdd01100090'
            result = checker.correlate(console, case.encode(rows), schema)
            with self.subTest(field=field):
                self.assertFalse(result['poweron_Main_context_bound'])
        rows, console, schema = case.joined_case()
        for changed in (console.replace(b'pid=259', b'pid=259 pid=259'),
                        console.replace(b'reads=8/2/1/1/4/4/4', b'reads=8/2/1/1/3/4/4'),
                        console.replace(b'producer_unknown=1', b'producer_unknown=0')):
            with self.assertRaises(checker.RejectedTrace):
                checker.correlate(changed, case.encode(rows), schema)


class V2ReceiptBindingTests(unittest.TestCase):
    def test_actual_explicit_receipt_schema_source_and_normal_exit_bind(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
            run, expected = case.write_run(directory, checker)
            before = {path.name: path.read_bytes() for path in run.iterdir()}
            result = checker.check_run(run, expected)
            self.assertIs(result['runtime_receipt_bound'], True)
            self.assertIs(result['original_artifacts_unchanged'], True)
            self.assertEqual(result['build_source_sha256'], expected['source_sha256'])
            self.assertEqual(result['trace_schema_sha256'], expected['schema_sha256'])
            self.assertEqual(result['source_contract_sha256'], expected['source_sha256']['source-contract-v2.json'])
            self.assertNotIn('schema_sha256', result)
            self.assertEqual(before, {path.name: path.read_bytes() for path in run.iterdir()})

    def test_v2_under_old_pin_or_v1_receipt_or_unknown_profile_is_refused(self):
        for change in ('old_pin', 'v1_profile', 'unknown_profile', 'v1_receipt', 'wrong_build_source',
                       'unbound_schema', 'unreviewed_receipt', 'missing_reader_source'):
            with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
                run, expected = case.write_run(directory, checker)
                manifest_path = run / 'runtime-manifest.json'
                manifest = json.loads(manifest_path.read_bytes())
                profile = manifest['readonly_scope_observer']
                if change == 'old_pin':
                    expected['schema_sha256'] = checker.FORMAT['V1_SCHEMA_SHA256']
                elif change in ('v1_profile', 'unknown_profile'):
                    profile['profile'] = 'qemu-readonly-scope-v1' if change == 'v1_profile' else 'qemu-readonly-scope-v99'
                elif change == 'v1_receipt':
                    receipt_path = Path(profile['build_receipt'])
                    receipt = json.loads(receipt_path.read_bytes())
                    receipt['schema'] = 'qemu-readonly-scope-v1'
                    raw = json.dumps(receipt).encode()
                    receipt_path.write_bytes(raw)
                    profile['build_receipt_sha256'] = expected['build_receipt_sha256'] = checker.sha(raw)
                elif change == 'wrong_build_source':
                    profile['source_sha256'] = {'scope-observer.c': 'f' * 64}
                elif change == 'unbound_schema':
                    del profile['trace_schema']
                elif change == 'unreviewed_receipt':
                    expected['build_receipt_sha256'] = 'f' * 64
                else:
                    del expected['source_sha256']['check_run_context_v2.py']
                manifest_path.write_text(json.dumps(manifest), encoding='ascii')
                with self.subTest(change=change), self.assertRaises(checker.RejectedTrace):
                    checker.check_run(run, expected)

    def test_external_schema_digest_has_one_name_and_source_contract_must_be_bound(self):
        for target in ('profile', 'receipt'):
            for change in ('missing_digest', 'schema_alias_only', 'log_schema_alias_only', 'extra_schema_alias',
                           'extra_log_schema_alias', 'old_digest', 'wrong_trace_schema', 'missing_trace_schema',
                           'wrong_source_contract', 'missing_source_contract', 'capture_true', 'physical_true'):
                with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
                    run, expected = case.write_run(directory, checker)
                    manifest_path = run / 'runtime-manifest.json'
                    manifest = json.loads(manifest_path.read_bytes())
                    profile = manifest['readonly_scope_observer']
                    receipt_path = Path(profile['build_receipt'])
                    receipt = json.loads(receipt_path.read_bytes())
                    record = profile if target == 'profile' else receipt
                    if change == 'missing_digest':
                        del record['trace_schema_sha256']
                    elif change.endswith('alias_only'):
                        name = 'schema_sha256' if change == 'schema_alias_only' else 'log_schema_sha256'
                        record[name] = record.pop('trace_schema_sha256')
                    elif change.startswith('extra_'):
                        name = 'schema_sha256' if change == 'extra_schema_alias' else 'log_schema_sha256'
                        record[name] = record['trace_schema_sha256']
                    elif change == 'old_digest':
                        record['trace_schema_sha256'] = checker.FORMAT['V1_SCHEMA_SHA256']
                    elif change == 'wrong_trace_schema':
                        record['trace_schema'] = 'readonly_scope_v1'
                    elif change == 'missing_trace_schema':
                        del record['trace_schema']
                    elif change == 'wrong_source_contract':
                        record['source_contract_sha256'] = 'f' * 64
                    elif change == 'missing_source_contract':
                        del record['source_contract_sha256']
                    else:
                        record['capture_verified' if change == 'capture_true' else 'physical_asic_compatibility_verified'] = True
                    if target == 'receipt':
                        raw = json.dumps(receipt).encode('ascii')
                        receipt_path.write_bytes(raw)
                        profile['build_receipt_sha256'] = expected['build_receipt_sha256'] = checker.sha(raw)
                    manifest_path.write_text(json.dumps(manifest), encoding='ascii')
                    with self.subTest(target=target, change=change), self.assertRaises(checker.RejectedTrace):
                        checker.check_run(run, expected)

    def test_runtime_source_map_remains_exact9_without_fixture_extensions(self):
        for target in ('expected', 'profile', 'receipt'):
            for change in ('extra_fixture', 'missing_legacy_reader'):
                with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
                    run, expected = case.write_run(directory, checker)
                    path = run / 'runtime-manifest.json'
                    manifest = json.loads(path.read_bytes())
                    profile = manifest['readonly_scope_observer']
                    receipt_path = Path(profile['build_receipt'])
                    receipt = json.loads(receipt_path.read_bytes())
                    record = {'expected': expected, 'profile': profile, 'receipt': receipt}[target]
                    if change == 'extra_fixture':
                        record['source_sha256']['integration/fixture.S'] = 'f' * 64
                    else:
                        del record['source_sha256']['check_run_context.py']
                    if target == 'receipt':
                        raw = json.dumps(receipt).encode('ascii')
                        receipt_path.write_bytes(raw)
                        profile['build_receipt_sha256'] = expected['build_receipt_sha256'] = checker.sha(raw)
                    path.write_text(json.dumps(manifest), encoding='ascii')
                    with self.subTest(target=target, change=change), self.assertRaises(checker.RejectedTrace):
                        checker.check_run(run, expected)

    def test_abnormal_exit_unowned_or_stale_log_receipt_never_pass(self):
        for field, value in (('returncode', -15), ('returncode', 1), ('returncode', False),
                             ('owned_wrapper_pid', 0), ('owned_wrapper_pid', True), ('log_available', False),
                             ('log_sha256', 'f' * 64), ('profile', 'qemu-readonly-scope-v1'),
                             ('capture_verified', True), ('physical_asic_compatibility_verified', True)):
            with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
                run, expected = case.write_run(directory, checker)
                path = run / 'readonly-scope-exit.json'
                record = json.loads(path.read_bytes())
                record[field] = value
                path.write_text(json.dumps(record), encoding='ascii')
                raw = (run / 'readonly-scope-trace.log').read_bytes()
                with self.subTest(field=field, value=value), self.assertRaises(checker.RejectedTrace) as caught:
                    checker.check_run(run, expected)
                self.assertEqual(caught.exception.evidence['raw_hex'], raw.hex())

    def test_changed_log_during_read_only_check_rejects_and_retains_initial_bytes(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
            run, expected = case.write_run(directory, checker)
            path = run / 'readonly-scope-trace.log'
            initial = path.read_bytes()
            original_correlate = checker.correlate

            def mutate_after_read(*args):
                result = original_correlate(*args)
                path.write_bytes(initial + b'HOST_TEST changed after snapshot\n')
                return result

            with mock.patch.object(checker, 'correlate', side_effect=mutate_after_read):
                with self.assertRaisesRegex(checker.RejectedTrace, 'changed during') as caught:
                    checker.check_run(run, expected)
            self.assertEqual(caught.exception.evidence['raw_hex'], initial.hex())

    def test_changed_staged_library_host_error_or_missing_receipt_refused(self):
        for change in ('library', 'host_error', 'receipt', 'missing_exit'):
            with tempfile.TemporaryDirectory(prefix='HOST_TEST-v2-reader-') as directory:
                run, expected = case.write_run(directory, checker)
                if change == 'library':
                    (run / 'readonly-scope-observer.so').write_bytes(b'HOST_TEST changed library')
                elif change == 'host_error':
                    with (run / 'console.log').open('ab') as stream:
                        stream.write(b'scope_observer_host_error stage=close\n')
                elif change == 'missing_exit':
                    (run / 'readonly-scope-exit.json').unlink()
                else:
                    manifest = json.loads((run / 'runtime-manifest.json').read_bytes())
                    Path(manifest['readonly_scope_observer']['build_receipt']).unlink()
                raw = (run / 'readonly-scope-trace.log').read_bytes()
                with self.subTest(change=change), self.assertRaises(checker.RejectedTrace) as caught:
                    checker.check_run(run, expected)
                self.assertEqual(caught.exception.evidence['raw_hex'], raw.hex())


if __name__ == '__main__':
    unittest.main()
