# SPDX-License-Identifier: MIT
"""Direct shutter parser tests driven by actual new C formatter output."""
from pathlib import Path
import copy
import hashlib
import importlib.util

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('shutter_v1_host_test_support', ROOT / 'test_scope_observer.py')
HOST = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HOST)
observer_binary = HOST.observer_binary
run_case, declaration = HOST.run_case, HOST.schema
SITES = ('final_entry', 'd570_cbnz_pre', 'successor_1724_pre', 'successor_1838_pre')
B = 0x5500000000
EVENTS = dict(zip(SITES, (0x1af16dc, 0x1af1834, 0x1af1724, 0x1af1838)))


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
    parsed = parser.assert_shutter_gate_trace_v1(raw, declaration(), independent_expected(stub=stub))
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
        parser.assert_shutter_gate_trace_v1(raw, declaration(), expected)


@pytest.mark.parametrize('site', SITES)
@pytest.mark.parametrize('name', ('event_pc', 'cpsr', 'sp', 'ttbr0_el1', 'tpidr_el0', 'entry_anchor'))
def test_independent_context_and_event_mutations_reject(observer_binary, site, name):
    raw, _ = run_case(observer_binary, 'success')
    expected = independent_expected()
    wanted = expected['site_rows'][site][0]
    wanted[name] = 'unsupported' if name == 'entry_anchor' else wanted[name] ^ 1
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v1(raw, declaration(), expected)


@pytest.mark.parametrize('name', ('sp', 'ttbr0_el1', 'tpidr_el0'))
def test_present_optional_requires_real_independent_value(observer_binary, name):
    raw, _ = run_case(observer_binary, 'success')
    expected = independent_expected()
    expected['site_rows']['d570_cbnz_pre'][0][name] = None
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v1(raw, declaration(), expected)


def test_low32_condition_ignores_high32_and_contradictory_nzcv(observer_binary):
    raw, _ = run_case(observer_binary, 'low32')
    expected = independent_expected(empty=True)
    values = (0xfeedface00000000, 0xfeedface00000001, 0xfeedfaceffffffff, 0xfeedface80000000)
    expected['site_rows']['d570_cbnz_pre'] = [
        independent_row('d570_cbnz_pre', x0=value, cpsr=0x400003c0 if i % 2 else 0x800003c0)
        for i, value in enumerate(values)]
    parser_module().assert_shutter_gate_trace_v1(raw, declaration(), expected)
    wrong = copy.deepcopy(expected)
    wrong['site_rows']['d570_cbnz_pre'].reverse()
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v1(raw, declaration(), wrong)


@pytest.mark.parametrize('scenario,case', [('mutation', 'one_byte_gate_mutation'), ('short_tb', 'short_tb')])
def test_unbound_mutation_and_short_tb_allow_no_success_rows(observer_binary, scenario, case):
    raw, _ = run_case(observer_binary, scenario)
    expected = independent_expected(empty=True)
    expected.update(case=case, discriminator_expected=False)
    parsed = parser_module().assert_shutter_gate_trace_v1(raw, declaration(), expected)
    assert parsed['end']['candidate_found'] == '0x0'
    assert all(not row for row in expected['site_rows'].values())


@pytest.mark.parametrize('scenario', ('quotas', 'longest'))
def test_real_formatter_order_quota_and_suppression_against_independent_rows(observer_binary, scenario):
    raw, _ = run_case(observer_binary, scenario)
    expected = independent_expected(empty=True)
    expected['site_rows'] = {site: [independent_row(site, cpsr=0xf00003cd) for _ in range(18)] for site in SITES}
    expected['minimum_suppressed'] = dict.fromkeys(SITES, 2)
    parser_module().assert_shutter_gate_trace_v1(raw, declaration(), expected)
    expected['minimum_suppressed']['final_entry'] = 3
    parser = parser_module()
    with pytest.raises(parser.RejectedTrace):
        parser.assert_shutter_gate_trace_v1(raw, declaration(), expected)


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
    wrong['schema'] = 'readonly_scope_v1'
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
