"""HOST_TEST only: v2 content/identity refusal cases, never actualAPI/Sony evidence."""
from pathlib import Path
import copy
import importlib.util
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checks = load('HOST_TEST_scope_v2_checks', HERE / 'scope_trace_checks_v2.py')
case = load('HOST_TEST_scope_v2_data', HERE / 'host_test_scope_v2_fixture.py')


class StrictV2TraceTests(unittest.TestCase):
    def test_complete_full64_input_caller_lazy_pc_and_raw_identity(self):
        rows, _, schema = case.joined_case()
        raw = case.encode(rows)
        parsed = checks.parse_trace(raw, schema)
        self.assertEqual(parsed['rows'], rows)
        producers = [row for row in parsed['rows'] if row['kind'] == 'M_producer']
        self.assertEqual(producers[0]['x0_raw'], '0xfedcba9800000007')
        self.assertEqual(producers[0]['caller_raw'], '0xabcdfffffeeda004')
        self.assertEqual(producers[0]['proposed_u32'], 'unknown')
        self.assertEqual(producers[1]['proposed_u32'], '0x00000007')
        self.assertNotEqual(producers[1]['event_pc'], producers[1]['gdb_pc_raw'])
        self.assertTrue(all(row['identity'] == 'unknown' and row['binding'] == 'unbound' for row in parsed['rows']))
        self.assertEqual(parsed['trace_sha256'], checks.sha(raw))

    def test_every_original_line_hash_offset_and_ordered_canonical_fields_is_complete(self):
        rows, _, schema = case.joined_case(early=True)
        raw = case.encode(rows)
        before = copy.deepcopy(rows)
        parsed = checks.parse_trace(raw, schema)
        offset = 0
        reconstructed = b''
        for row, record, line in zip(rows, parsed['raw_records'], raw.splitlines(keepends=True)):
            self.assertEqual((record['byte_offset'], record['byte_length']), (offset, len(line)))
            self.assertEqual(record['sha256'], checks.sha(line))
            self.assertEqual(bytes.fromhex(record['raw_hex']), line)
            self.assertEqual(record['raw_ascii'].encode('ascii'), line)
            self.assertEqual(dict(record['canonical_fields']), row)
            self.assertEqual((' '.join(key + '=' + value for key, value in record['canonical_fields']) + '\n').encode(), line)
            reconstructed += line
            offset += len(line)
        self.assertEqual(reconstructed, raw)
        self.assertEqual(rows, before)

    def test_schema_version_unknown_kind_and_wrong_site_exact_keys_are_refused(self):
        cases = [('schema', 'readonly_scope_v99'), ('schema', 'readonly_scope_v1')]
        for key, value in cases:
            rows, _, schema = case.joined_case()
            rows[0][key] = value
            with self.subTest(value=value), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(rows), schema)
        for change in ('unknown_site', 'entry_has_x1', 'prestore_missing_x1', 'unknown_family', 'unknown_pointer'):
            rows, _, schema = case.joined_case()
            entry = next(row for row in rows if row['kind'] == 'M_producer')
            prestore = next(row for row in rows if row.get('site') == 'pre_M_store')
            if change == 'unknown_site':
                entry['site'] = 'return'
            elif change == 'entry_has_x1':
                entry['x1_raw'] = case.h64(0)
            elif change == 'prestore_missing_x1':
                del prestore['x1_api_ok']
            elif change == 'unknown_family':
                entry['kind'] = 'M_committed'
            else:
                entry['input_kind'] = 'unknown_pointer'
            with self.subTest(change=change), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(rows), schema)

    def test_163_line_envelope_boundary_does_not_relax_fault_claim_refusal(self):
        rows, _, schema = case.joined_case()
        envelope = [rows[0]] + [dict(kind='fault', reason='HOST_TEST', **case.COMMON) for _ in range(161)] + [rows[-1]]
        raw = case.encode(envelope)
        self.assertEqual(len(checks.rows_from(raw)), 163)
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(raw, schema)
        envelope.insert(-1, dict(envelope[1]))
        with self.assertRaises(ValueError):
            checks.rows_from(case.encode(envelope))

    def test_legacy_parser_version_exact_keys_and_131_limit_remain_strict(self):
        rows, _, _ = case.joined_case(sites=())
        begin = dict(rows[0], schema='readonly_scope_v1')
        for name in ('producer_sites', 'producer_quota', 'producer_anchor_length'):
            del begin[name]
        end = dict(rows[-1], candidate_found='0x0', candidate_base=case.h64(0), lr0_records='0x0', poweron_records='0x0',
                   late0_records='0x0', late_sequence='0x0')
        for name in tuple(end):
            if name.startswith('producer'):
                del end[name]
        legacy = [begin, end]
        result = checks.V1['assert_scope_trace'](case.encode(legacy), {}, None, 0)
        self.assertTrue(result['synthetic_scope_observer_verified'])
        for change in ('version', 'key', 'family', 'limit'):
            changed = copy.deepcopy(legacy)
            if change == 'version':
                changed[0]['schema'] = 'readonly_scope_v2'
            elif change == 'key':
                changed[0]['producer_sites'] = '0x2'
            elif change == 'family':
                changed.insert(1, case.producer_row())
            else:
                changed[1:1] = [dict(kind='candidate', **case.COMMON) for _ in range(130)]
            with self.subTest(change=change), self.assertRaises(ValueError):
                checks.V1['assert_scope_trace'](case.encode(changed), {}, None, 0)

    def test_pointer_shaped_x0_is_still_direct_low32_operand_without_dereference(self):
        rows, _, schema = case.joined_case(sites=('pre_M_store',))
        row = next(row for row in rows if row['kind'] == 'M_producer')
        row.update(x0_raw='0x0000ffffc0001000', raw_input_u32='0xc0001000', proposed_u32='0xc0001000')
        parsed = checks.parse_trace(case.encode(rows), schema)
        self.assertEqual(parsed['rows'][-2]['input_kind'], 'u32_value')
        self.assertEqual(parsed['rows'][-2]['proposed_u32'], '0xc0001000')

    def test_full64_and_bool_exact_lengths_destination_and_overflow_are_required(self):
        mutations = (('x0_raw', '0x00000007'), ('caller_raw', '0x00000000feeda004'),
                     ('x0_api_ok', '0x0'), ('x0_read_length', '0x7'), ('x30_read_length', '0x9'),
                     ('gdb_pc_api_ok', '0x0'), ('gdb_pc_read_length', '0x7'),
                     ('cpsr_read_length', '0x8'), ('cpsr_api_ok', '0x0'),
                     ('x1_api_ok', '0x0'), ('x1_read_length', '0x7'), ('x1_raw', '0xfffffffffffffff0'),
                     ('effective_destination_raw', case.h64(case.BASE + 0x7e6a7c4)),
                     ('x1_raw', case.h64(case.BASE + 0x7e6a4dc)), ('destination_match', '0x0'))
        for key, value in mutations:
            rows, _, schema = case.joined_case(sites=('pre_M_store',))
            next(row for row in rows if row['kind'] == 'M_producer')[key] = value
            raw = case.encode(rows)
            with self.subTest(key=key, value=value), self.assertRaises(checks.RejectedTrace) as caught:
                checks.parse_trace(raw, schema)
            self.assertEqual(caught.exception.evidence['raw_hex'], raw.hex())
            self.assertTrue(all(record['canonical'] and record['raw_ascii'] is not None and
                                record['canonical_fields'] is not None
                                for record in caught.exception.evidence['raw_records']))
        rows, _, schema = case.joined_case(sites=())
        rows[-1]['producer_base'] = '0x0000fffff8200000'
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)

    def test_optional_absence_is_unknown_and_present_failure_rejects_whole_row(self):
        for field in ('sp', 'ttbr0_el1', 'tpidr_el0'):
            rows, _, schema = case.joined_case(sites=('entry',))
            row = next(row for row in rows if row['kind'] == 'M_producer')
            row.update({field + '_available': '0x0', field + '_raw': 'unknown', field + '_read_length': '0x0',
                        field + '_api_ok': 'unknown'})
            checks.parse_trace(case.encode(rows), schema)
            for key, value in ((field + '_raw', case.h64(0)), (field + '_api_ok', '0x0')):
                changed = copy.deepcopy(rows)
                next(item for item in changed if item['kind'] == 'M_producer')[key] = value
                with self.subTest(field=field, key=key), self.assertRaises(checks.RejectedTrace):
                    checks.parse_trace(case.encode(changed), schema)
            for suffix, value in (('_api_ok', '0x0'), ('_read_length', '0x7')):
                changed, _, schema = case.joined_case(sites=('entry',))
                next(item for item in changed if item['kind'] == 'M_producer')[field + suffix] = value
                with self.subTest(field=field, suffix=suffix), self.assertRaises(checks.RejectedTrace):
                    checks.parse_trace(case.encode(changed), schema)

    def test_raw_EL1_is_preserved_but_AArch32_reserved_and_normalized_modes_refused(self):
        rows, _, schema = case.joined_case(sites=('entry',))
        row = next(row for row in rows if row['kind'] == 'M_producer')
        row.update(case.flags(5))
        parsed = checks.parse_trace(case.encode(rows), schema)
        self.assertEqual(parsed['rows'][-2]['context_mode'], 'other_aarch64')
        self.assertIsNone(checks.context_key(parsed['rows'][-2]))
        for mode in (1, 2, 3, 6, 7, 10, 11, 14, 15, 16, 31):
            changed = copy.deepcopy(rows)
            next(item for item in changed if item['kind'] == 'M_producer').update(case.flags(mode))
            with self.subTest(mode=mode), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(changed), schema)
        row['context_mode'] = 'EL0t'
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)

    def test_store_return_claim_keys_entry_proposal_or_ordinal_pairing_are_never_accepted(self):
        for key in ('committed_M', 'current_M', 'store_completed', 'return_observed', 'instruction_retired'):
            rows, _, schema = case.joined_case()
            next(row for row in rows if row['kind'] == 'M_producer')[key] = '0x1'
            with self.subTest(key=key), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(rows), schema)
        rows, _, schema = case.joined_case()
        next(row for row in rows if row['kind'] == 'M_producer')['proposed_u32'] = '0x00000007'
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)

    def test_independent_16_row_quotas_and_global_sequence_are_strict(self):
        rows, _, schema = case.joined_case(sites=('entry',) * 16 + ('pre_M_store',) * 16)
        ordinals = {'entry': 0, 'pre_M_store': 0}
        for row in rows:
            if row['kind'] == 'M_producer':
                ordinals[row['site']] += 1
                row['ordinal'] = hex(ordinals[row['site']])
        checks.parse_trace(case.encode(rows), schema)
        extra = case.producer_row('pre_M_store')
        extra.update(ordinal='0x11', producer_sequence='0x21')
        rows.insert(-1, extra)
        rows[-1] = case.end_row(rows[:-1])
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)
        rows, _, schema = case.joined_case()
        next(row for row in rows if row['kind'] == 'M_producer')['producer_sequence'] = '0x2'
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)

    def test_duplicate_noncanonical_truncated_or_promoted_raw_bytes_are_refused(self):
        rows, _, schema = case.joined_case()
        raw = case.encode(rows)
        for changed in (raw[:-1], b'0' + raw, raw.replace(b'kind=M_producer ', b'kind=M_producer site=entry ', 1),
                        raw.replace(b'identity=unknown', b'identity=original_AP', 1),
                        raw.replace(b'vcpu=0x0 ', b'vcpu=0x00 ', 1), raw.replace(b'kind=begin ', b'kind=begin  ', 1)):
            with self.subTest(prefix=changed[:64]), self.assertRaises(checks.RejectedTrace) as caught:
                checks.parse_trace(changed, schema)
            self.assertEqual(caught.exception.evidence['trace_sha256'], checks.sha(changed))


def adapter_vector(sites=('entry', 'pre_M_store'), early=True):
    """HOST_TEST independently frozen expectations; later mutations affect only raw rows."""
    rows, _, _ = case.joined_case(early=early, sites=sites)
    rows = [row for row in rows if row['kind'] not in ('poweron_context', 'late')]
    for row in rows:
        if row['kind'] in ('entry', 'M_producer'):
            row.update(case.flags(5))
    rows[-1] = case.end_row(rows[:-1])
    if not sites:
        rows[-1].update(producer_anchor_found='0x0', producer_base=case.h64(0))
    scope = next(row for row in rows if row['kind'] == 'entry')
    scope_names = (*case.GPRS, 'actual_pc', 'translated_entry_pc', 'candidate_base', 'lr', 'sp', 'nzcv', 'cpsr_m')
    entries = {(0, 1): {name: int(scope[name], 16) for name in scope_names}}
    entries[0, 1]['context_mode'] = 'other_aarch64'
    producers = {}
    for row in rows:
        if row['kind'] != 'M_producer':
            continue
        names = ('vcpu', 'producer_sequence', 'event_pc', 'candidate_base', 'scope_anchor_seen',
                 'x0_raw', 'raw_input_u32', 'x30_raw', 'caller_raw', 'cpsr_raw', 'cpsr_m', 'nzcv', 'nzcv_mask')
        wanted = {name: int(row[name], 16) for name in names}
        wanted['proposed_u32'] = 'unknown' if row['site'] == 'entry' else int(row['proposed_u32'], 16)
        wanted['context_mode'] = 'other_aarch64'
        wanted['optional_raw'] = {name: int(row[name + '_raw'], 16) for name in ('sp', *checks.TOKENS)}
        if row['site'] == 'pre_M_store':
            wanted.update({name: int(row[name], 16) for name in ('x1_raw', 'effective_destination_raw', 'destination_match')})
        producers[row['site'], int(row['ordinal'], 16)] = wanted
    return rows, entries, producers


class StrictV2AdapterTests(unittest.TestCase):
    def assert_vector(self, rows, entries, producers):
        return checks.assert_scope_trace_v2(case.encode(rows), entries, case.BASE, 0,
            expected_producers=producers, producer_base=case.BASE if producers else None)

    def test_adapter_keeps_original_v2_bytes_EL1_and_lazy_PC_with_all_operands(self):
        rows, entries, producers = adapter_vector()
        raw = case.encode(rows)
        before = copy.deepcopy(rows)
        result = self.assert_vector(rows, entries, producers)
        self.assertEqual(result['rows'], before)
        self.assertEqual(result['trace_sha256'], checks.sha(raw))
        self.assertEqual(b''.join(bytes.fromhex(item['raw_hex']) for item in result['raw_records']), raw)
        self.assertTrue(result['synthetic_M_producer_observer_verified'])
        prestore = next(row for row in result['rows'] if row.get('site') == 'pre_M_store')
        self.assertNotEqual(prestore['gdb_pc_raw'], prestore['event_pc'])
        self.assertEqual(prestore['context_mode'], 'other_aarch64')
        for name in ('original_Main_identity_verified', 'instruction_retirement_verified', 'branchretirement',
                     'storecompletion', 'capture_verified', 'physical_asic_compatibility_verified'):
            self.assertIs(result[name], False)

    def test_correct_eventPC_with_wrong_full64_scope_or_producer_operand_is_rejected(self):
        for kind, field in (('entry', 'x0'), ('entry', 'x19'), ('entry', 'x20'), ('entry', 'x21'),
                            ('entry', 'x23'), ('entry', 'x24'), ('entry', 'x29'), ('entry', 'sp'),
                            ('M_producer', 'x0_raw'), ('M_producer', 'x30_raw')):
            rows, entries, producers = adapter_vector()
            row = next(row for row in rows if row['kind'] == kind)
            row[field] = case.h64(int(row[field], 16) ^ (1 << 48))
            if field == 'x30_raw':
                row['caller_raw'] = row[field]
            raw = case.encode(rows)
            schema = case.joined_case()[2]
            checks.parse_trace(raw, schema)
            with self.subTest(kind=kind, field=field), self.assertRaises(checks.RejectedTrace) as caught:
                self.assert_vector(rows, entries, producers)
            self.assertEqual(caught.exception.evidence['raw_hex'], raw.hex())

    def test_scope_full_flags_mode_LR_and_prestore_destination_expectations_are_checked(self):
        for family, field in (('scope', 'x30'), ('scope', 'lr'), ('scope', 'nzcv'), ('scope', 'cpsr_m'),
                              ('producer', 'x1_raw'), ('producer', 'effective_destination_raw'),
                              ('producer', 'proposed_u32'), ('producer', 'raw_input_u32'),
                              ('producer', 'cpsr_raw'), ('producer', 'cpsr_m')):
            rows, entries, producers = adapter_vector()
            target = entries[0, 1] if family == 'scope' else producers['pre_M_store', 1]
            target[field] ^= 1
            with self.subTest(family=family, field=field), self.assertRaises(checks.RejectedTrace):
                self.assert_vector(rows, entries, producers)
        rows, entries, producers = adapter_vector()
        del producers['entry', 1]['x0_raw']
        with self.assertRaisesRegex(checks.RejectedTrace, 'incomplete fixture'):
            self.assert_vector(rows, entries, producers)

    def test_optional_unknown_stays_missing_and_only_available_actual_values_compare(self):
        for field in ('sp', *checks.TOKENS):
            rows, entries, producers = adapter_vector()
            row = next(row for row in rows if row['kind'] == 'M_producer')
            row.update({field + '_available': '0x0', field + '_raw': 'unknown',
                        field + '_read_length': '0x0', field + '_api_ok': 'unknown'})
            result = self.assert_vector(rows, entries, producers)
            actual = next(row for row in result['rows'] if row['kind'] == 'M_producer')
            self.assertEqual(actual[field + '_raw'], 'unknown')
            self.assertEqual(actual[field + '_api_ok'], 'unknown')
            row.update({field + '_available': '0x1', field + '_raw': case.h64(0),
                        field + '_read_length': '0x8', field + '_api_ok': '0x1'})
            with self.subTest(field=field), self.assertRaises(checks.RejectedTrace):
                self.assert_vector(rows, entries, producers)
            row[field + '_api_ok'] = '0x0'
            with self.assertRaises(checks.RejectedTrace):
                self.assert_vector(rows, entries, producers)

    def test_no_M_and_prestore_only_never_invent_entry_pair_or_completion(self):
        for sites in ((), ('pre_M_store',)):
            rows, entries, producers = adapter_vector(sites=sites)
            result = self.assert_vector(rows, entries, producers)
            self.assertEqual(sum(row['kind'] == 'M_producer' and row['site'] == 'entry' for row in result['rows']), 0)
            self.assertEqual(result['producer_observation_status'], 'observed_raw' if sites else 'unknown')
            self.assertEqual(result['entry_pre_store_invocation_pairing'], 'unknown')
            self.assertIs(result['storecompletion'], False)

    def test_adapter_strict_parser_rejects_old_schema_unknown_family_and_every_fault(self):
        for change in ('old_schema', 'unknown_family', 'fault', 'extra_identity'):
            rows, entries, producers = adapter_vector()
            if change == 'old_schema':
                rows[0]['schema'] = 'readonly_scope_v1'
            elif change == 'unknown_family':
                next(row for row in rows if row['kind'] == 'M_producer')['kind'] = 'M_committed'
            elif change == 'fault':
                rows.insert(-1, dict(kind='fault', reason='producer_destination_mismatch', **case.COMMON))
            else:
                next(row for row in rows if row['kind'] == 'M_producer')['identity'] = 'original_AP'
            with self.subTest(change=change), self.assertRaises(checks.RejectedTrace):
                self.assert_vector(rows, entries, producers)


if __name__ == '__main__':
    unittest.main()
