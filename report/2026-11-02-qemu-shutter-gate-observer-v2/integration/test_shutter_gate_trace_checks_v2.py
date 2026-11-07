# SPDX-License-Identifier: MIT
"""Direct v2 parser tests using C formatter output and explicit synthetic negatives."""
from pathlib import Path
import copy
import hashlib
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('shutter_v2_host_test_support', ROOT / 'test_scope_observer.py')
HOST = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HOST)
observer_binary = HOST.observer_binary
run_case, declaration = HOST.run_case, HOST.schema
SITES = ('final_entry', 'd570_cbnz_pre', 'successor_1724_pre', 'successor_1838_pre', 'd570_ldr_pre')
B = 0x5500000000
EVENTS = dict(zip(SITES, (0x1af16dc, 0x1af1834, 0x1af1724, 0x1af1838, 0x1af1830)))


def parser_module():
    return HOST.load_parser()


def independent_row(site, *, stub=False, x0=0x1122334455667788, cpsr=0xa00003c0):
    """Known input operands of the self-owned C mock, never obtained from raw rows."""
    registers = {'x0': x0, 'x30': 0xabcd005501af1830}
    if site == 'final_entry':
        registers.update(x1=0xaabbccdd80000000, x2=0x9988776655443322, x3=0x8877665544332211)
    else:
        registers.update(x19=0x7ffffffcf8, x22=0xabcdef0180000000,
                         x23=0x1122334455667788, x29=0x7ffffffcb0)
    return {'event_pc': B + EVENTS[site], 'registers': registers, 'cpsr': cpsr,
            'sp': 0x7ffffffd00 if site == 'final_entry' else 0x7ffffffcb0,
            'ttbr0_el1': 0x1234005500456000, 'tpidr_el0': 0xfedcba9876543210,
            'entry_anchor': ('existing_main_stub8' if stub else 'original16')
                            if site == 'final_entry' else 'not_applicable'}


def independent_expected(*, stub=False, empty=False):
    return {'case': 'existing_main_stub_entry' if stub else 'original_entry',
            'site_rows': {site: [] if empty else [independent_row(site, stub=stub)] for site in SITES},
            'minimum_suppressed': dict.fromkeys(SITES, 0), 'discriminator_expected': True}


@pytest.mark.parametrize('scenario,stub', [('success', False), ('stub', True), ('absent', False)])
def test_direct_actual_c_full_operand_assertion(observer_binary, scenario, stub):
    raw, errors = run_case(observer_binary, scenario)
    assert not errors
    parser = parser_module()
    parsed = parser.assert_shutter_gate_trace_v2(raw, declaration(), independent_expected(stub=stub))
    assert parsed['synthetic_shutter_gate_observer_verified'] is True
    assert all(parsed[key] is False for key in parser.FALSE_FLAGS)
    assert parsed['invocation_pairing'] == 'unknown'
    offset = 0
    for item, line in zip(parsed['raw_ledger'], raw.splitlines(keepends=True)):
        assert item['byte_offset'] == offset and item['byte_length'] == len(line)
        assert bytes.fromhex(item['raw_hex']) == line and item['sha256'] == hashlib.sha256(line).hexdigest()
        assert item['canonical_fields'] == list(parser.fields_from_line(line[:-1]).items())
        offset += len(line)
    assert offset == len(raw)


@pytest.mark.parametrize('site,name', [(s, r) for s in SITES for r in (
    ('x0', 'x1', 'x2', 'x3', 'x30') if s == 'final_entry' else ('x0', 'x19', 'x22', 'x23', 'x29', 'x30'))])
@pytest.mark.parametrize('replacement', ('different', 'bool'))
def test_independent_every_raw_gpr_family_mutation_rejects(observer_binary, site, name, replacement):
    raw, _ = run_case(observer_binary, 'success')
    expected = independent_expected()
    expected['site_rows'][site][0]['registers'][name] = (
        True if replacement == 'bool' else expected['site_rows'][site][0]['registers'][name] ^ (1 << 40))
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


@pytest.mark.parametrize('site', SITES)
@pytest.mark.parametrize('name', ('event_pc', 'cpsr', 'sp', 'ttbr0_el1', 'tpidr_el0', 'entry_anchor'))
def test_independent_context_and_event_mutations_reject(observer_binary, site, name):
    raw, _ = run_case(observer_binary, 'success')
    expected = independent_expected()
    wanted = expected['site_rows'][site][0]
    wanted[name] = 'unsupported' if name == 'entry_anchor' else wanted[name] ^ 1
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


@pytest.mark.parametrize('name', ('sp', 'ttbr0_el1', 'tpidr_el0'))
def test_present_optional_requires_real_independent_value(observer_binary, name):
    raw, _ = run_case(observer_binary, 'success')
    expected = independent_expected()
    expected['site_rows']['d570_cbnz_pre'][0][name] = None
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


def test_low32_condition_ignores_high32_and_contradictory_nzcv(observer_binary):
    raw, _ = run_case(observer_binary, 'low32')
    expected = independent_expected(empty=True)
    values = (0xfeedface00000000, 0xfeedface00000001, 0xfeedfaceffffffff, 0xfeedface80000000)
    expected['site_rows']['d570_cbnz_pre'] = [
        independent_row('d570_cbnz_pre', x0=value, cpsr=0x400003c0 if i % 2 else 0x800003c0)
        for i, value in enumerate(values)]
    parser_module().assert_shutter_gate_trace_v2(raw, declaration(), expected)
    wrong = copy.deepcopy(expected)
    wrong['site_rows']['d570_cbnz_pre'].reverse()
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), wrong)


@pytest.mark.parametrize('scenario,case', [('mutation', 'one_byte_gate_mutation'), ('short_tb', 'short_tb')])
def test_unbound_mutation_and_short_tb_allow_no_success_rows(observer_binary, scenario, case):
    raw, _ = run_case(observer_binary, scenario)
    expected = independent_expected(empty=True)
    expected.update(case=case, discriminator_expected=False)
    parsed = parser_module().assert_shutter_gate_trace_v2(raw, declaration(), expected)
    assert parsed['end']['candidate_found'] == '0x0'
    assert all(not row for row in expected['site_rows'].values())


@pytest.mark.parametrize('scenario', ('quotas', 'longest'))
def test_real_formatter_order_quota_and_suppression_against_independent_rows(observer_binary, scenario):
    raw, _ = run_case(observer_binary, scenario)
    expected = independent_expected(empty=True)
    expected['site_rows'] = {site: [independent_row(site, cpsr=0xf00003cd) for _ in range(18)] for site in SITES}
    expected['minimum_suppressed'] = dict.fromkeys(SITES, 2)
    parser_module().assert_shutter_gate_trace_v2(raw, declaration(), expected)
    expected['minimum_suppressed']['final_entry'] = 3
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


@pytest.mark.parametrize('mutation', ('truncate', 'crlf', 'duplicate', 'reorder', 'extra', 'width',
                                    'optional_zero', 'prediction', 'end_count', 'claimed_retirement'))
def test_strict_raw_rejection_keeps_actual_lf_sha_and_offset(observer_binary, mutation):
    raw, _ = run_case(observer_binary, 'success')
    if mutation == 'truncate':
        changed = raw[:-1]
    elif mutation == 'crlf':
        changed = raw.replace(b'\n', b'\r\n')
    elif mutation == 'duplicate':
        changed = raw.replace(b' x0_raw=', b' ordinal=0x1 x0_raw=', 1)
    elif mutation == 'reorder':
        changed = raw.replace(b'site=final_entry vcpu=0x0', b'vcpu=0x0 site=final_entry', 1)
    elif mutation == 'extra':
        changed = raw.replace(b'kind=end ', b'kind=end invented=0x0 ', 1)
    elif mutation == 'width':
        changed = raw.replace(b'x0_raw=0x1122334455667788', b'x0_raw=0x55667788', 1)
    elif mutation == 'optional_zero':
        changed = raw.replace(b'sp_available=0x1', b'sp_available=0x0', 1)
    elif mutation == 'prediction':
        changed = raw.replace(b'loaded_w0=0x55667788', b'loaded_w0=0x00000000', 1)
    elif mutation == 'end_count':
        changed = raw.replace(b'site0_records=0x1', b'site0_records=0x2', 1)
    else:
        changed = raw.replace(b'retirement=0x0', b'retirement=0x1', 1)
    assert changed != raw
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace) as caught:
        parser.parse_trace(changed, declaration())
    evidence = caught.value.evidence
    assert evidence['trace_sha256'] == hashlib.sha256(changed).hexdigest()
    assert b''.join(bytes.fromhex(item['raw_hex']) for item in evidence['raw_ledger']) == changed


def test_schema_suffix_trap_and_keyset_disagreement_refuse(observer_binary):
    raw, _ = run_case(observer_binary, 'success')
    parser = parser_module()
    wrong = declaration()
    wrong['schema'] = 'readonly_scope_v2'
    with pytest.raises(parser.RejectedTrace):
        parser.parse_trace(raw, wrong)
    wrong = declaration()
    wrong['site_additional_fields']['final_entry'].append('invented')
    with pytest.raises(parser.RejectedTrace):
        parser.parse_trace(raw, wrong)


@pytest.mark.parametrize('invalid', (
    b'{"unused_extra":{"duplicate":0,"duplicate":1}}',
    b'{"unused_extra":[{"number":NaN}]}',
    b'{"unused_extra":[{"number":Infinity}]}',
    b'{"unused_extra":[{"number":-Infinity}]}',
    b'{"unused_extra":[{"number":1e999}]}'))
def test_strict_json_decoder_rejects_entire_unused_subtree(invalid):
    with pytest.raises(ValueError, match='duplicate JSON|nonfinite JSON'):
        parser_module().object_json(invalid)


@pytest.mark.parametrize('value', (float('nan'), float('inf'), float('-inf')))
def test_predecoded_declaration_cannot_hide_nonfinite_extra(observer_binary, value):
    raw, _ = run_case(observer_binary, 'success')
    wrong = declaration()
    wrong['unused_extra'] = {'nested': [value]}
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace, match='nonfinite JSON'):
        parser.parse_trace(raw, wrong)


def synthetic_trace(sequence, *, base=B):
    """Create self-owned v2 unit rows from explicit operands, never old raw bytes."""
    parser = parser_module()
    def line(kind, row, keys):
        ordered = [('kind', kind), *((key, row[key]) for key in keys), *parser.COMMON.items()]
        return (' '.join(key + '=' + value for key, value in ordered) + '\n').encode('ascii')
    raw = [line('begin', parser.BEGIN, list(parser.BEGIN))]
    counts = dict.fromkeys(SITES, 0)
    for index, (site, baseline) in enumerate(sequence, 1):
        registers, cpsr = baseline['registers'], baseline['cpsr']
        counts[site] += 1
        mode = cpsr & 0x1f
        row = dict(site=site, vcpu='0x0', ordinal=hex(counts[site]), gate_sequence=hex(index),
                   callback_phase='before_instruction', event_pc='0x%016x' % (base + EVENTS[site]),
                   gdb_pc_raw='0x%016x' % registers.get('pc', 0x123456789abcdef0),
                   candidate_base='0x%016x' % base, entry_anchor=baseline['entry_anchor'],
                   anchor_length='0x10' if baseline['entry_anchor'] == 'original16' else '0x8',
                   cpsr_raw='0x%08x' % cpsr, cpsr_m='0x%02x' % mode,
                   context_mode='EL0t' if mode == 0 else 'other_aarch64',
                   nzcv='0x%08x' % (cpsr & 0xf0000000), nzcv_mask='0xf0000000', api_ok='0x1')
        for name, value in registers.items():
            if name != 'pc':
                row[name + '_raw'] = '0x%016x' % value
        for name in ('gdb_pc', 'cpsr', *(name for name in registers if name != 'pc')):
            row[name + '_read_length'] = '0x4' if name == 'cpsr' else '0x8'
            row[name + '_api_ok'] = '0x1'
        for name in ('sp', 'ttbr0_el1', 'tpidr_el0'):
            value = baseline[name]
            row.update({name + '_available': '0x0' if value is None else '0x1',
                        name + '_raw': 'unknown' if value is None else '0x%016x' % value,
                        name + '_read_length': '0x0' if value is None else '0x8',
                        name + '_api_ok': 'unknown' if value is None else '0x1'})
        if site == 'final_entry':
            row['trigger_low32'] = '0x%08x' % (registers['x1'] & 0xffffffff)
        elif site == 'd570_cbnz_pre':
            low = registers['x0'] & 0xffffffff
            row.update(loaded_w0='0x%08x' % low, source_taken_prediction=hex(int(low != 0)),
                       source_next_pc='0x%016x' % (base + (0x1af1724 if low else 0x1af1838)),
                       source_next_basis='w0_low32')
        raw.append(line('shutter_gate', row, parser.GATE_FIELDS + parser.EXTRA[site]))
    end = dict(stop='none', ambiguous='0x0', candidate_found='0x1', candidate_base='0x%016x' % base,
               conflicting_base='0x0000000000000000', anchor_seen_mask='0x1f', gate_sequence=hex(len(sequence)),
               fault_lines='0x0', faults='0x0', suppressed_faults='0x0', close_result='unknown')
    for ordinal, site in enumerate(SITES):
        end.update({'site%d_records' % ordinal: hex(counts[site]),
                    'site%d_suppressed' % ordinal: '0x0', 'site%d_unbound_callbacks' % ordinal: '0x0'})
    raw.append(line('end', end, parser.END_FIELDS))
    return b''.join(raw)


def source_sequence():
    return [(site, independent_row(site)) for site in
            ('d570_ldr_pre', 'd570_cbnz_pre', 'successor_1724_pre', 'successor_1838_pre')]


def test_source_full64_and_lazy_pc_use_exact_internal_fields():
    parser = parser_module()
    raw = synthetic_trace(source_sequence())
    parsed = parser.parse_trace(raw, declaration())
    source = parsed['rows'][1]
    assert source['x0_raw'] == '0x1122334455667788'
    assert source['event_pc'] != source['gdb_pc_raw']
    assert list(source) == ['kind', *parser.GATE_FIELDS, *parser.INTERNAL_FIELDS, *parser.COMMON]
    assert not set(parser.PREDICTION_FIELDS).intersection(source)
    for name in parser.PREDICTION_FIELDS:
        changed = raw.replace(b'kind=shutter_gate site=d570_ldr_pre ',
                              b'kind=shutter_gate ' + name.encode('ascii') + b'=0x0 site=d570_ldr_pre ', 1)
        with pytest.raises(parser.RejectedTrace):
            parser.parse_trace(changed, declaration())


@pytest.mark.parametrize('value', (0, (1 << 64) - 1, 0xfeedface00000000))
def test_source_accepts_entire_uint64_range_without_pointer_normalization(value):
    parser = parser_module()
    baseline = independent_row('d570_ldr_pre', x0=value)
    raw = synthetic_trace([('d570_ldr_pre', baseline)])
    expected = independent_expected(empty=True)
    expected['site_rows']['d570_ldr_pre'] = [baseline]
    parsed = parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)
    assert parser.number(parsed['rows'][1], 'x0_raw') == value


@pytest.mark.parametrize('name', ('x0', 'x19', 'x22', 'x23', 'x29', 'x30', 'pc'))
@pytest.mark.parametrize('value', (True, False, -1, 1 << 64))
def test_source_independent_operands_require_uint64_not_bool(name, value):
    parser = parser_module()
    baseline = independent_row('d570_ldr_pre')
    baseline['registers']['pc'] = 0x123456789abcdef0
    raw = synthetic_trace([('d570_ldr_pre', baseline)])
    expected = independent_expected(empty=True)
    expected['site_rows']['d570_ldr_pre'] = [copy.deepcopy(baseline)]
    expected['site_rows']['d570_ldr_pre'][0]['registers'][name] = value
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


@pytest.mark.parametrize('field', ('event_pc', 'cpsr', 'sp', 'ttbr0_el1', 'tpidr_el0'))
@pytest.mark.parametrize('value', (True, False, -1, 1 << 64))
def test_source_independent_context_requires_typed_integers(field, value):
    parser = parser_module()
    baseline = independent_row('d570_ldr_pre')
    raw = synthetic_trace([('d570_ldr_pre', baseline)])
    expected = independent_expected(empty=True)
    expected['site_rows']['d570_ldr_pre'] = [copy.deepcopy(baseline)]
    expected['site_rows']['d570_ldr_pre'][0][field] = value
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


@pytest.mark.parametrize('mutation', ('missing_count', 'missing_suppressed', 'missing_unbound',
                                     'wrong_count', 'strong_unbound', 'mask_branch_only',
                                     'mask_source_only', 'mask_overflow', 'begin_four'))
def test_fifth_site_counters_mask_and_begin_are_required(mutation):
    parser = parser_module()
    raw = synthetic_trace(source_sequence())
    before, after = {
        'missing_count': (b' site4_records=0x1', b''),
        'missing_suppressed': (b' site4_suppressed=0x0', b''),
        'missing_unbound': (b' site4_unbound_callbacks=0x0', b''),
        'wrong_count': (b'site4_records=0x1', b'site4_records=0x0'),
        'strong_unbound': (b'site4_unbound_callbacks=0x0', b'site4_unbound_callbacks=0x1'),
        'mask_branch_only': (b'anchor_seen_mask=0x1f', b'anchor_seen_mask=0x2'),
        'mask_source_only': (b'anchor_seen_mask=0x1f', b'anchor_seen_mask=0x10'),
        'mask_overflow': (b'anchor_seen_mask=0x1f', b'anchor_seen_mask=0x3f'),
        'begin_four': (b'sites=0x5', b'sites=0x4')}[mutation]
    changed = raw.replace(before, after)
    assert changed != raw
    with pytest.raises(parser.RejectedTrace) as caught:
        parser.parse_trace(changed, declaration())
    assert caught.value.evidence['trace_sha256'] == hashlib.sha256(changed).hexdigest()
    assert b''.join(bytes.fromhex(item['raw_hex']) for item in caught.value.evidence['raw_ledger']) == changed


def test_five_site_80_success_limit_and_site4_quota():
    parser = parser_module()
    sequence = [(site, independent_row(site)) for site in SITES for _ in range(16)]
    raw = synthetic_trace(sequence)
    parsed = parser.parse_trace(raw, declaration())
    assert len(parsed['rows']) == 82 and parsed['end']['gate_sequence'] == '0x50'
    assert parsed['end']['site4_records'] == '0x10'
    assert parser.LIMITS == {'maximum_file_lines': 114, 'maximum_line_bytes_exclusive': 2048,
                             'maximum_file_bytes_conservative': 233472, 'quota_per_site': 16,
                             'maximum_success_rows': 80, 'maximum_fault_lines': 32}
    with pytest.raises(parser.RejectedTrace, match='quota'):
        parser.parse_trace(synthetic_trace(sequence + [('d570_ldr_pre', independent_row('d570_ldr_pre'))]), declaration())


def test_line_and_file_byte_limits_keep_complete_refusal_bytes():
    parser = parser_module()
    raw = synthetic_trace([])
    begin, end = raw.splitlines(keepends=True)
    oversized_lines = begin + begin * 113 + end
    assert len(oversized_lines.splitlines()) == 115
    for changed, message in ((oversized_lines, 'line count'), (b'x' * 233472 + b'\n', 'oversized'),
                             (b'x' * (233472 - len(end) - 1) + b'\n' + end, 'line bound'),
                             (b'x' * 2047 + b'\n' + end, 'line bound')):
        with pytest.raises(parser.RejectedTrace, match=message) as caught:
            parser.parse_trace(changed, declaration())
        assert bytes.fromhex(caught.value.evidence['raw_hex']) == changed
        assert caught.value.evidence['byte_length'] == len(changed)


def test_full114_line_group_preserves_all_faults_but_never_becomes_success():
    parser = parser_module()
    sequence = [(site, independent_row(site)) for site in SITES for _ in range(16)]
    lines = synthetic_trace(sequence).splitlines(keepends=True)
    fault = ('kind=fault reason=registers_not_ready ' +
             ' '.join(key + '=' + value for key, value in parser.COMMON.items()) + '\n').encode('ascii')
    end = lines[-1].replace(b' fault_lines=0x0 ', b' fault_lines=0x20 ').replace(b' faults=0x0 ', b' faults=0x20 ')
    raw = lines[0] + fault * 32 + b''.join(lines[1:-1]) + end
    assert len(raw.splitlines()) == 114 and len(raw) <= 233472
    with pytest.raises(parser.RejectedTrace, match='fault or stop') as caught:
        parser.parse_trace(raw, declaration())
    assert len(caught.value.evidence['raw_ledger']) == 114
    assert b''.join(bytes.fromhex(item['raw_hex']) for item in caught.value.evidence['raw_ledger']) == raw


@pytest.mark.parametrize('mutation', ('site_rows', 'minimum_suppressed', 'discriminator_bool'))
def test_independent_interface_rejects_old_four_site_map_or_integer_discriminator(mutation):
    parser = parser_module()
    expected = independent_expected(empty=True)
    expected['site_rows']['d570_ldr_pre'] = [independent_row('d570_ldr_pre')]
    raw = synthetic_trace([('d570_ldr_pre', independent_row('d570_ldr_pre'))])
    if mutation == 'discriminator_bool':
        expected['discriminator_expected'] = 1
    else:
        del expected[mutation]['d570_ldr_pre']
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v2(raw, declaration(), expected)


@pytest.mark.parametrize('field,value', (
    ('x0_raw', '0x55667788'), ('x0_raw', '0x10000000000000000'), ('x0_raw', 'true'),
    ('x0_read_length', '0x4'), ('x0_api_ok', 'true'), ('x0_api_ok', '0x0'),
    ('cpsr_read_length', '0x8'), ('ttbr0_el1_read_length', '0x4'),
    ('ttbr0_el1_api_ok', 'false'), ('sp_api_ok', '0x0')))
def test_source_raw_full64_and_exact_width_bool_failures_reject_entire_group(field, value):
    parser = parser_module()
    raw = synthetic_trace(source_sequence())
    source = raw.splitlines(keepends=True)[1]
    fields = dict(token.split('=', 1) for token in source.decode('ascii').strip().split(' '))
    changed = raw.replace(source, source.replace((field + '=' + fields[field]).encode('ascii'),
                                               (field + '=' + value).encode('ascii')), 1)
    assert changed != raw
    with pytest.raises(parser.RejectedTrace) as caught:
        parser.parse_trace(changed, declaration())
    assert caught.value.evidence['trace_sha256'] == hashlib.sha256(changed).hexdigest()


@pytest.mark.parametrize('schema', ('readonly_shutter_gate_v1', 'readonly_scope_v2'))
def test_v2_rejects_mixed_begin_or_declaration_schema(schema):
    parser = parser_module()
    raw = synthetic_trace(source_sequence())
    wrong = copy.deepcopy(declaration())
    wrong['schema'] = schema
    for changed, schema_value in ((raw, wrong),
                                  (raw.replace(b'schema=readonly_shutter_gate_v2',
                                               b'schema=' + schema.encode('ascii')), declaration())):
        with pytest.raises(parser.RejectedTrace):
            parser.parse_trace(changed, schema_value)


def test_v1_parser_refuses_v2_direct_raw_without_changing_v1():
    v1_root = ROOT.with_name('2026-10-31-qemu-shutter-gate-observer-v1')
    spec = importlib.util.spec_from_file_location('unchanged_gate_v1_reader',
                                                 v1_root / 'integration/shutter_gate_trace_checks_v1.py')
    v1 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v1)
    schema = v1.object_json((v1_root / 'log-schema-shutter-gate-v1.json').read_bytes())
    with pytest.raises(v1.RejectedTrace):
        v1.parse_trace(synthetic_trace(source_sequence()), schema)


@pytest.mark.parametrize('site', ('final_entry', 'd570_cbnz_pre'))
def test_schema_ordinals_refuse_bool_substitution(site):
    parser = parser_module()
    wrong = copy.deepcopy(declaration())
    wrong['sites'][site]['ordinal'] = site == 'd570_cbnz_pre'
    with pytest.raises(parser.RejectedTrace, match='sites differ'):
        parser.parse_trace(synthetic_trace(source_sequence()), wrong)

