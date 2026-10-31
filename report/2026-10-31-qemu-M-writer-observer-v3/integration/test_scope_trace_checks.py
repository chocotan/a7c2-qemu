"""HOST_TEST synthetic data and reader cases only; never a Sony run or actualAPI replay."""
from pathlib import Path
import copy
import hashlib
import json

HERE = Path(__file__).resolve().parent
BASE = 0x4000000000
TOKENS = {'ttbr0_el1': 0x1234000400100000, 'tpidr_el0': 0xabcd000040208000}
COMMON = {'status': 'native_unverified', 'identity': 'unknown', 'binding': 'unbound',
          'pid': 'unknown', 'tid': 'unknown', 'capture': '0x0', 'physical': '0x0'}
GPRS = ('x0', 'x19', 'x20', 'x21', 'x23', 'x24', 'x29', 'x30')


def h64(value):
    return '0x%016x' % value


def flags(mode=0):
    cpsr = 0xa00003c0 | mode
    return {'cpsr_raw': '0x%08x' % cpsr, 'cpsr_m': '0x%02x' % mode,
            'context_mode': 'EL0t' if mode == 0 else 'other_aarch64',
            'nzcv': '0xa0000000', 'nzcv_mask': '0xf0000000'}


def optionals(include_sp=True, individual_ok=True):
    result = {}
    values = dict(TOKENS, **({'sp': BASE + 0x200000} if include_sp else {}))
    for name, value in values.items():
        result.update({name + '_available': '0x1', name + '_raw': h64(value), name + '_read_length': '0x8'})
        if individual_ok:
            result[name + '_api_ok'] = '0x1'
    return result


def begin_row():
    schema = json.loads((HERE.parent / 'log-schema-v3.json').read_bytes())
    return dict(schema['kinds']['begin'], kind='begin', **COMMON)


def candidate_row():
    return dict(kind='candidate', candidate_base=h64(BASE), translated_entry_pc=h64(BASE + 0x2e068cc),
                anchor_length='0x18', **COMMON)


def scope_row():
    row = dict(kind='entry', vcpu='0x0', lr_slot='0x0', ordinal='0x1',
               actual_pc=h64(BASE + 0x2e068cc), translated_entry_pc=h64(BASE + 0x2e068cc),
               candidate_base=h64(BASE), lr=h64(BASE + 0x209ee80), sp=h64(BASE + 0x200000),
               sp_read_length='0x8', api_ok='0x1', **COMMON)
    row.update({name: h64(0x1234567800000000 + index) for index, name in enumerate(GPRS)})
    row['x30'] = row['lr']
    row.update({name + '_read_length': '0x8' for name in ('pc', 'lr', *GPRS)})
    row['cpsr_read_length'] = '0x4'
    row.update(flags())
    row.update(optionals(False, False))
    return row


def power_row():
    row = dict(kind='poweron_context', site='dispatch', vcpu='0x0', ordinal='0x1',
               actual_pc=h64(BASE + 0x1951844), translated_entry_pc=h64(BASE + 0x1951844),
               candidate_base=h64(BASE), anchor_length='0x8', controller=h64(0x40010000),
               raw_x2='0xaabbccdd01000090', raw_u32='0x01000090', caller_raw=h64(BASE + 0x1e79354),
               api_ok='0x1', cpsr_read_length='0x4', **COMMON)
    row.update({name + '_read_length': '0x8' for name in ('pc', 'x0', 'x2', 'x30')})
    row.update(flags())
    row.update(optionals(False))
    return row


def producer_row(site='entry', scope_seen=True):
    row = dict(kind='M_producer', site=site, vcpu='0x0', ordinal='0x1', producer_sequence='0x1',
               callback_phase='before_instruction', event_pc=h64(BASE + {'entry': 0x276e710, 'pre_M_store': 0x276e71c, 'second_entry': 0x2845430}[site]),
               gdb_pc_raw=h64(BASE + 0x276e710), candidate_base=h64(BASE),
               scope_anchor_seen='0x1' if scope_seen else '0x0', anchor_length='0x18', input_kind='u32_value',
               x0_raw='0xfedcba9800000007', raw_input_u32='0x00000007', proposed_u32='unknown',
               x30_raw='0xabcdfffffeeda004', caller_raw='0xabcdfffffeeda004', api_ok='0x1', **COMMON)
    row.update(flags())
    row.update(optionals())
    for name in ('gdb_pc', 'x0', 'x30', 'cpsr'):
        row[name + '_read_length'] = '0x4' if name == 'cpsr' else '0x8'
        row[name + '_api_ok'] = '0x1'
    if site == 'pre_M_store':
        row.update(proposed_u32=row['raw_input_u32'], x1_raw=h64(BASE + 0x7e6a4d8), x1_read_length='0x8',
                   x1_api_ok='0x1', effective_destination_raw=h64(BASE + 0x7e6a7c8), destination_match='0x1')
    return row


def late_row(site='M_cmp_pre'):
    offsets = {'M_cmp_pre': 0x209ee58, 'M_bne_pre': 0x209ee5c, 'request0_bl_pre': 0x209ee9c}
    row = dict(kind='late', site=site, vcpu='0x0', ordinal='0x1', late_sequence='0x1',
               callback_phase='before_instruction', event_pc=h64(BASE + offsets[site]),
               gdb_pc_raw=h64(BASE + 0x209ee54), candidate_base=h64(BASE), anchor_length='0xc',
               x0='0x1234567800000000', x19=h64(BASE + 0x1000), x23='0x0000000000000000',
               x30='0xabcdfffffeeda004', api_ok='0x1', **COMMON)
    row.update(flags())
    row.update(optionals())
    for name in ('gdb_pc', 'x0', 'x19', 'x23', 'x30', 'cpsr'):
        row[name + '_read_length'] = '0x4' if name == 'cpsr' else '0x8'
        row[name + '_api_ok'] = '0x1'
    if site == 'request0_bl_pre':
        row.update(x1='0x1234567800000000', w1='0x00000000', x1_read_length='0x8', x1_api_ok='0x1', lr_phase='before_bl')
    else:
        row.update(loaded_M_u32='0x00000000', flags_phase='before_cmp')
        if site == 'M_bne_pre':
            row.update(flags_phase='after_cmp_before_bne', z='0x0', source_next_pc=h64(BASE + 0x209ee80), source_next_basis='cpsr_Z')
    return row


def end_row(rows):
    return dict(kind='end', stop='none', ambiguous='0x0', candidate_found='0x1', candidate_base=h64(BASE),
                conflicting_base=h64(0), producer_anchor_found='0x1', producer_base=h64(BASE),
                producer_conflicting_base=h64(0), producer2_anchor_found='0x1', producer2_base=h64(BASE),
                producer2_conflicting_base=h64(0),
                producer2_records=hex(sum(row['kind'] == 'M_producer' and row['site'] == 'second_entry' for row in rows)),
                lr0_records=hex(sum(row['kind'] == 'entry' and row['lr_slot'] == '0x0' for row in rows)),
                lr1_records=hex(sum(row['kind'] == 'entry' and row['lr_slot'] == '0x1' for row in rows)),
                poweron_records=hex(sum(row['kind'] == 'poweron_context' for row in rows)),
                producer0_records=hex(sum(row['kind'] == 'M_producer' and row['site'] == 'entry' for row in rows)),
                producer1_records=hex(sum(row['kind'] == 'M_producer' and row['site'] == 'pre_M_store' for row in rows)),
                producer_sequence=hex(sum(row['kind'] == 'M_producer' for row in rows)),
                late0_records=hex(sum(row['kind'] == 'late' and row['site'] == 'M_cmp_pre' for row in rows)),
                late1_records=hex(sum(row['kind'] == 'late' and row['site'] == 'M_bne_pre' for row in rows)),
                late2_records=hex(sum(row['kind'] == 'late' and row['site'] == 'request0_bl_pre' for row in rows)),
                late_sequence=hex(sum(row['kind'] == 'late' for row in rows)),
                fault_lines='0x0', faults=h64(0), suppressed_faults=h64(0), other_lr=h64(0), close_result='unknown', **COMMON)


def encode(rows):
    return ''.join('kind=' + row['kind'] + ' ' + ' '.join(key + '=' + value for key, value in row.items() if key != 'kind') + '\n'
                   for row in rows).encode('ascii')


def joined_case(early=False, sites=('entry', 'pre_M_store')):
    rows = [begin_row(), candidate_row(), power_row(), scope_row(), late_row()]
    producers = [producer_row(site, not early) for site in sites]
    ordinals = dict.fromkeys(('entry', 'pre_M_store', 'second_entry'), 0)
    for sequence, row in enumerate(producers, 1):
        ordinals[row['site']] += 1
        row['ordinal'] = hex(ordinals[row['site']])
        row['producer_sequence'] = hex(sequence)
    if early:
        rows[1:1] = producers
    else:
        rows.extend(producers)
    rows.append(end_row(rows))
    main = dict.fromkeys(('site n pid tid base controller caller_raw caller_app raw_u32 raw_known numeric_route_match '
                         'vptr field300 field302 field303 current17c model_m model_k open_rc open_errno reads read_errno '
                         'close_rc close_errno quota observation_only atomic_snapshot phase original_branch_observed '
                         'original_store_observed original_return_observed event_id_unverified producer_unknown capture_verified').split(), '0')
    power = next(row for row in rows if row['kind'] == 'poweron_context')
    main.update(site='dispatch', n='1', pid='259', tid='345', base=h64(BASE), controller=power['controller'],
                caller_raw=power['caller_raw'], caller_app='0x1e79354', raw_u32='0x01000090', raw_known='1',
                numeric_route_match='1', observation_only='1', phase='entry', event_id_unverified='1', producer_unknown='1',
                quota='poweron_entry16', open_rc='7', reads='8/2/1/1/4/4/4', read_errno='0/0/0/0/0/0/0')
    console = ('HOST_TEST synthetic console\nOBS SHUTTER_DETAIL_POWERON ' +
               ' '.join(key + '=' + value for key, value in main.items()) + '\r\n').encode('ascii')
    schema = json.loads((HERE.parent / 'log-schema-v3.json').read_bytes())
    return rows, console, schema


def write_run(directory, checker):
    """Write only a caller-owned HOST_TEST tempdir; these are deliberately fake assets."""
    directory = Path(directory).resolve()
    run = directory / 'HOST_TEST-run'
    run.mkdir()
    rows, console, _ = joined_case()
    trace = encode(rows)
    library = b'HOST_TEST fake library, never loaded or built\n'
    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    closure = {name: digest((checker.HERE / name).read_bytes()) for name in checker.BUILD_SOURCES}
    expected = {'schema_sha256': closure['log-schema-v3.json'], 'qemu_sha256': digest(b'HOST_TEST QEMU'),
                'library_sha256': digest(library), 'qemu_header_sha256': digest(b'HOST_TEST header'),
                'source_sha256': closure,
                'observer_sha256': digest(b'HOST_TEST Main library'), 'Main_source_sha256': digest(b'HOST_TEST Main source'),
                'original_appfw_sha256': digest(b'HOST_TEST appFw identity only'),
                'readonly_import_audit_sha256': digest(b'HOST_TEST import audit')}
    receipt = {key: copy.deepcopy(expected[key]) for key in checker.ASSET_FIELDS}
    receipt.update(schema=checker.PROFILE, trace_schema=checker.SCHEMA,
                   trace_schema_sha256=expected['schema_sha256'], source_contract_sha256=closure['source-contract-v3.json'],
                   plugin_api=7, readonly_imports_verified=True,
                   readonly_import_audit_sha256=expected['readonly_import_audit_sha256'],
                   runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
    receipt_path = directory / 'HOST_TEST-build-receipt.json'
    receipt_raw = (json.dumps(receipt, indent=2) + '\n').encode()
    receipt_path.write_bytes(receipt_raw)
    expected['build_receipt_sha256'] = digest(receipt_raw)
    profile = dict(receipt, profile=checker.PROFILE, identity_binding='unverified', build_receipt=str(receipt_path),
                   build_receipt_sha256=expected['build_receipt_sha256'], library=str(run / 'readonly-scope-observer.so'),
                   log=str(run / 'readonly-scope-trace.log'))
    manifest = {'readonly_scope_observer': profile,
                'compiled_observer': {'observer_sha256': expected['observer_sha256'],
                                      'sources': {'HOST_TEST/menu-observe.c': {'sha256': expected['Main_source_sha256']}}},
                'files': {'HOST_TEST/appFw.so': expected['original_appfw_sha256']}}
    exit_record = {'profile': checker.PROFILE, 'run': str(run), 'owned_wrapper_pid': 123,
                   'returncode': 0, 'log_available': True, 'log_sha256': digest(trace), 'library_sha256': digest(library),
                   'capture_verified': False, 'physical_asic_compatibility_verified': False}
    for name, raw in (('console.log', console), ('readonly-scope-trace.log', trace), ('readonly-scope-observer.so', library),
                      ('runtime-manifest.json', json.dumps(manifest).encode()),
                      ('readonly-scope-exit.json', json.dumps(exit_record).encode())):
        (run / name).write_bytes(raw)
    return run, expected


"""HOST_TEST only: v3 content/identity refusal cases, never actualAPI/Sony evidence."""
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


checks = load('HOST_TEST_scope_v3_checks', HERE / 'scope_trace_checks_v3.py')
from types import SimpleNamespace
case = SimpleNamespace(**globals())


class StrictV3TraceTests(unittest.TestCase):
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

    def test_179_line_envelope_boundary_does_not_relax_fault_claim_refusal(self):
        rows, _, schema = case.joined_case()
        envelope = [rows[0]] + [dict(kind='fault', reason='HOST_TEST', **case.COMMON) for _ in range(177)] + [rows[-1]]
        raw = case.encode(envelope)
        self.assertEqual(len(checks.rows_from(raw)), 179)
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(raw, schema)
        envelope.insert(-1, dict(envelope[1]))
        with self.assertRaises(ValueError):
            checks.rows_from(case.encode(envelope))

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
    scope_names = (*case.GPRS, 'actual_pc', 'translated_entry_pc', 'candidate_base', 'lr', 'sp',
                   'cpsr_raw', 'nzcv', 'nzcv_mask', 'cpsr_m')
    entries = {(0, 1): {name: int(scope[name], 16) for name in scope_names}}
    entries[0, 1]['context_mode'] = 'other_aarch64'
    producers = {}
    for row in rows:
        if row['kind'] != 'M_producer':
            continue
        names = ('vcpu', 'producer_sequence', 'event_pc', 'candidate_base', 'scope_anchor_seen',
                 'x0_raw', 'raw_input_u32', 'x30_raw', 'caller_raw', 'cpsr_raw', 'cpsr_m', 'nzcv', 'nzcv_mask')
        wanted = {name: int(row[name], 16) for name in names}
        wanted['proposed_u32'] = 'unknown' if row['site'] != 'pre_M_store' else int(row['proposed_u32'], 16)
        wanted['context_mode'] = 'other_aarch64'
        wanted['optional_raw'] = {name: int(row[name + '_raw'], 16) for name in ('sp', *checks.TOKENS)}
        if row['site'] == 'pre_M_store':
            wanted.update({name: int(row[name], 16) for name in ('x1_raw', 'effective_destination_raw', 'destination_match')})
        producers[row['site'], int(row['ordinal'], 16)] = wanted
    return rows, entries, producers


class StrictV3AdapterTests(unittest.TestCase):
    def assert_vector(self, rows, entries, producers):
        return checks.assert_scope_trace_v3(case.encode(rows), entries, case.BASE, 0,
            expected_producers=producers, producer_base=case.BASE if producers else None, producer2_base=case.BASE)

    def test_adapter_keeps_original_v3_bytes_EL1_and_lazy_PC_with_all_operands(self):
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


class V3IndependentWritersTests(unittest.TestCase):
    def test_each_same_base_discovery_order_keeps_original_early_rows(self):
        from itertools import permutations
        for order in permutations(('scope', 'first', 'second')):
            rows = [begin_row()]
            for item in order:
                if item == 'scope':
                    rows.append(candidate_row())
                else:
                    rows.append(producer_row('entry' if item == 'first' else 'second_entry',
                                             scope_seen=any(row['kind'] == 'candidate' for row in rows)))
            sequence = 0
            for row in rows:
                if row['kind'] == 'M_producer':
                    sequence += 1
                    row['producer_sequence'] = hex(sequence)
            rows.append(end_row(rows))
            raw = encode(rows)
            result = checks.parse_trace(raw, json.loads((HERE.parent / 'log-schema-v3.json').read_bytes()))
            with self.subTest(order=order):
                self.assertEqual(result['rows'], rows)
                self.assertEqual(b''.join(bytes.fromhex(record['raw_hex']) for record in result['raw_records']), raw)
                self.assertEqual([row['scope_anchor_seen'] for row in result['rows'] if row['kind'] == 'M_producer'],
                                 ['0x1' if order.index('scope') < order.index(item) else '0x0'
                                  for item in order if item != 'scope'])

    def test_any_base_conflict_rejects_every_order_and_retains_raw(self):
        from itertools import permutations
        fields = ('candidate_base', 'producer_base', 'producer2_base')
        for order in permutations(('scope', 'entry', 'second_entry')):
            rows = [begin_row()]
            for item in order:
                rows.append(candidate_row() if item == 'scope' else producer_row(
                    item, scope_seen=any(row['kind'] == 'candidate' for row in rows)))
            for sequence, row in enumerate((row for row in rows if row['kind'] == 'M_producer'), 1):
                row['producer_sequence'] = hex(sequence)
            rows.append(end_row(rows))
            schema = json.loads((HERE.parent / 'log-schema-v3.json').read_bytes())
            for field in fields:
                changed = copy.deepcopy(rows)
                changed[-1][field] = h64(BASE + 0x1000)
                raw = encode(changed)
                with self.subTest(order=order, field=field), self.assertRaises(checks.RejectedTrace) as caught:
                    checks.parse_trace(raw, schema)
                self.assertEqual(caught.exception.evidence['raw_hex'], raw.hex())

    def test_only_second_found_with_real_rows_does_not_require_first_or_scope(self):
        rows = [begin_row(), producer_row('second_entry', False)]
        rows.append(end_row(rows))
        rows[-1].update(candidate_found='0x0', candidate_base=h64(0),
                        producer_anchor_found='0x0', producer_base=h64(0))
        schema = json.loads((HERE.parent / 'log-schema-v3.json').read_bytes())
        result = checks.parse_trace(encode(rows), schema)
        self.assertEqual(result['rows'][1]['site'], 'second_entry')
        for flag, base in (('candidate_found', 'candidate_base'), ('producer_anchor_found', 'producer_base'),
                           ('producer2_anchor_found', 'producer2_base')):
            for value in ('unknown', h64(BASE)):
                changed = copy.deepcopy(rows)
                changed[-1].update({flag: '0x0', base: value})
                with self.subTest(flag=flag, value=value), self.assertRaises(checks.RejectedTrace):
                    checks.parse_trace(encode(changed), schema)
        for site in ('entry', 'pre_M_store'):
            changed = copy.deepcopy(rows)
            changed[1] = producer_row(site, False)
            changed[-1] = end_row(changed[:-1])
            changed[-1].update(candidate_found='0x0', candidate_base=h64(0),
                               producer_anchor_found='0x0', producer_base=h64(0))
            with self.subTest(site=site), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(encode(changed), schema)
        rows[-1].update(producer2_anchor_found='0x0', producer2_base=h64(0))
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(encode(rows), schema)

    def test_second_site_exact_keys_full64_low32_modes_and_read_widths(self):
        rows, _, schema = joined_case(sites=('second_entry',), early=True)
        second = next(row for row in rows if row['kind'] == 'M_producer')
        for raw_x0 in (0, 0xffffffff, 0x1234567880000000, 0xffffffffffffffff):
            for mode in (0, 4, 5, 8, 9, 12, 13):
                changed = copy.deepcopy(rows)
                row = next(row for row in changed if row['kind'] == 'M_producer')
                row.update(flags(mode), x0_raw=h64(raw_x0), raw_input_u32='0x%08x' % (raw_x0 & 0xffffffff))
                parsed = checks.parse_trace(encode(changed), schema)
                self.assertEqual(next(row for row in parsed['rows'] if row['kind'] == 'M_producer')['x0_raw'], h64(raw_x0))
        changes = [('site', 'second_pre_M_store'), ('x1_raw', h64(0)), ('effective_destination_raw', h64(0)),
                   ('destination_match', '0x1'), ('proposed_u32', '0x00000007'),
                   ('raw_input_u32', '0x100000007'), ('raw_input_u32', '-1'),
                   ('x0_raw', '0x00000007'), ('x30_raw', '0xfeeda004'),
                   ('caller_raw', '0x00000000feeda004'), ('scope_anchor_seen', '0x1'), ('ordinal', '0x0')]
        changes += [(name + '_api_ok', '0x0') for name in ('gdb_pc', 'x0', 'x30', 'cpsr')]
        changes += [(name + '_read_length', length) for name in ('gdb_pc', 'x0', 'x30', 'cpsr')
                    for length in ('0x0', '0x3', '0x7', '0x9')]
        for key, value in changes:
            changed = copy.deepcopy(rows)
            next(row for row in changed if row['kind'] == 'M_producer')[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(encode(changed), schema)
        self.assertNotEqual(second['gdb_pc_raw'], second['event_pc'])
        for field in ('sp', *checks.TOKENS):
            absent = copy.deepcopy(rows)
            row = next(row for row in absent if row['kind'] == 'M_producer')
            row.update({field + '_available': '0x0', field + '_raw': 'unknown',
                        field + '_read_length': '0x0', field + '_api_ok': 'unknown'})
            checks.parse_trace(encode(absent), schema)
            for suffix, value in (('_api_ok', '0x0'), ('_read_length', '0x7')):
                changed = copy.deepcopy(rows)
                next(row for row in changed if row['kind'] == 'M_producer')[field + suffix] = value
                with self.subTest(field=field, suffix=suffix), self.assertRaises(checks.RejectedTrace):
                    checks.parse_trace(encode(changed), schema)

    def test_three_independent_quotas_48_sequence_and_second_end_counters(self):
        sites = ('second_entry',) * 16 + ('entry',) * 16 + ('pre_M_store',) * 16
        rows, _, schema = joined_case(early=True, sites=sites)
        checks.parse_trace(encode(rows), schema)
        self.assertEqual(rows[-1]['producer_sequence'], '0x30')
        self.assertEqual(rows[-1]['producer2_records'], '0x10')
        for key, value in (('producer_sequence', '0x31'), ('producer2_records', '0xf'),
                           ('producer2_anchor_found', '0x0'), ('producer2_base', h64(0)),
                           ('producer2_conflicting_base', h64(BASE + 0x1000)),
                           ('stop', 'producer2_anchor_changed'), ('stop', 'producer2_base_conflict')):
            changed = copy.deepcopy(rows)
            changed[-1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(encode(changed), schema)
        extra = producer_row('second_entry', False)
        extra.update(ordinal='0x11', producer_sequence='0x31')
        rows.insert(49, extra)
        rows[-1] = end_row(rows[:-1])
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(encode(rows), schema)

    def test_old_readers_still_refuse_v3_and_new_reader_requires_explicit_v3(self):
        rows, _, schema = joined_case(sites=('second_entry',))
        raw = encode(rows)
        with self.assertRaises(ValueError):
            checks.V1['assert_scope_trace'](raw, {}, None, 0)
        old_name = '2026-10-30-qemu-readonly-scope-observer'
        historical = HERE.parent.with_name(old_name) / 'integration/scope_trace_checks_v2.py'
        old = load('HOST_TEST_historical_scope_v2_reader', historical)
        old_schema = json.loads((historical.parents[1] / 'log-schema-v2.json').read_bytes())
        with self.assertRaises(ValueError):
            old.parse_trace(raw, old_schema)
        for old_version in ('readonly_scope_v1', 'readonly_scope_v2'):
            changed = copy.deepcopy(rows)
            changed[0]['schema'] = old_version
            with self.subTest(version=old_version), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(encode(changed), schema)


class V3SecondAdapterTests(unittest.TestCase):
    def test_actual_raw_second_entry_operands_are_compared_independently(self):
        rows, entries, producers = adapter_vector(sites=('second_entry',))
        rows[-1].update(producer_anchor_found='0x0', producer_base=h64(0))
        raw = encode(rows)
        result = checks.assert_scope_trace_v3(raw, entries, BASE, 0,
            expected_producers=producers, producer_base=None, producer2_base=BASE)
        self.assertEqual(result['trace_sha256'], checks.sha(raw))
        self.assertEqual(result['rows'], rows)
        self.assertEqual(b''.join(bytes.fromhex(record['raw_hex']) for record in result['raw_records']), raw)
        for field in ('x0_raw', 'x30_raw', 'caller_raw', 'raw_input_u32', 'cpsr_raw', 'nzcv'):
            wanted = copy.deepcopy(producers)
            wanted['second_entry', 1][field] ^= 1
            with self.subTest(field=field), self.assertRaises(checks.RejectedTrace):
                checks.assert_scope_trace_v3(raw, entries, BASE, 0,
                    expected_producers=wanted, producer_base=None, producer2_base=BASE)
        with self.assertRaises(checks.RejectedTrace):
            checks.assert_scope_trace_v3(raw, entries, BASE, 0,
                expected_producers=producers, producer_base=BASE, producer2_base=None)
        for field in ('x0_raw', 'x30_raw'):
            changed = copy.deepcopy(rows)
            row = next(row for row in changed if row['kind'] == 'M_producer')
            row[field] = h64(int(row[field], 16) ^ (1 << 48))
            if field == 'x30_raw':
                row['caller_raw'] = row[field]
            schema = json.loads((HERE.parent / 'log-schema-v3.json').read_bytes())
            checks.parse_trace(encode(changed), schema)
            with self.subTest(high32_field=field), self.assertRaises(checks.RejectedTrace):
                checks.assert_scope_trace_v3(encode(changed), entries, BASE, 0,
                    expected_producers=producers, producer_base=None, producer2_base=BASE)


if __name__ == '__main__':
    unittest.main()
