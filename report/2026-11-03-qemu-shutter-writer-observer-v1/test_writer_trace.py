import copy
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).with_name('writer_trace.py')
SPEC = importlib.util.spec_from_file_location('writer_trace_tests', PATH)
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


def fixture_rows():
    scope = dict(status='native_unverified', identity='unknown', binding='unbound', pid='unknown',
                 tid='unknown', capture='0x0', physical='0x0', retirement='0x0')
    begin = dict(kind='begin', schema='readonly_shutter_writer_v1', plugin_api='0x7', max_vcpus='0x1',
        sites='0x3', site_quota='0x10', fault_quota='0x20', register_byte_order='little',
        identity_limit='raw_context_only_no_pid_tid_module_identity', **scope)
    records = []
    for index, (site, offset) in enumerate((('setter_entry', 0x2767978), ('store_pre', 0x276797c),
                                          ('ret_pre', 0x2767980))):
        row = dict(kind='shutter_writer', site=site, vcpu='0x0', ordinal='0x1', writer_sequence=hex(index + 1),
            callback_phase='before_instruction', event_pc=hex(0x40000000 + offset), gdb_pc_raw='0x42767978',
            candidate_base='0x40000000', anchor_length='0xc', x0_raw='0x100000001', input_w0='0x1',
            x1_raw='0x47e5d000' if index else '0x0', x30_raw='0x40200014', cpsr_raw='0x400003c5',
            cpsr_m='0x5', context_mode='other_aarch64', expected_destination='0x47e5d570',
            destination_base_checked=hex(int(index != 0)), api_ok='0x1',
            store_retirement_verified='0x0', memory_readback_verified='0x0', **scope)
        for name in ('gdb_pc', 'x0', 'x1', 'x30', 'cpsr'):
            row.update({name + '_read_length': '0x4' if name == 'cpsr' else '0x8', name + '_api_ok': '0x1'})
        for name in ('sp', 'ttbr0_el1', 'tpidr_el0'):
            row.update({name + '_available': '0x1', name + '_raw': '0x47fff000' if name == 'sp' else '0x0',
                        name + '_read_length': '0x8', name + '_api_ok': '0x1'})
        records.append(row)
    end = dict(kind='end', stop='none', ambiguous='0x0', candidate_found='0x1', candidate_base='0x40000000',
        conflicting_base='0x0', anchor_seen_mask='0x7', site0_records='0x1', site1_records='0x1',
        site2_records='0x1', writer_sequence='0x3', site0_suppressed='0x0', site1_suppressed='0x0',
        site2_suppressed='0x0', fault_lines='0x0', faults='0x0', suppressed_faults='0x0',
        close_result='unknown', **scope)
    return [begin, *records, end]


def encode(rows):
    return ''.join(' '.join(k + '=' + value for k, value in row.items()) + '\n' for row in rows).encode()


def test_raw_context_includes_loaded_input_and_lr_without_claiming_store_or_ap():
    result = w.parse_trace(encode(fixture_rows()))
    assert result['status'] == 'observed_raw' and result['site_counts'] == dict.fromkeys(w.SITES, 1)
    assert [row['input_w0'] for row in result['events']] == [1, 1, 1]
    assert result['events'][1]['event_pc'] != result['events'][1]['gdb_pc_raw']
    assert result['events'][1]['link_register_raw'] == 0x40200014
    assert all(result[name] is False for name in ('absence_proven', 'AP_identity_verified',
        'invocation_pairing_verified', 'store_retirement_verified', 'memory_readback_verified',
        'capture_verified', 'physical_asic_compatibility_verified'))


def test_empty_and_quota_suppression_are_observation_limits():
    rows = fixture_rows()
    end = rows[-1]
    end.update(candidate_found='0x0', candidate_base='0x0', anchor_seen_mask='0x0', writer_sequence='0x0')
    for index in range(3):
        end['site' + str(index) + '_records'] = '0x0'
    result = w.parse_trace(encode([rows[0], end]))
    assert result['status'] == 'no_observed_calls' and result['absence_proven'] is False
    rows = fixture_rows()
    repeated = []
    for index in range(16):
        for site in range(3):
            row = dict(rows[site + 1], ordinal=hex(index + 1), writer_sequence=hex(len(repeated) + 1))
            repeated.append(row)
    end = rows[-1]
    end.update(writer_sequence='0x30')
    for index in range(3):
        end.update({'site' + str(index) + '_records': '0x10', 'site' + str(index) + '_suppressed': '0x2'})
    result = w.parse_trace(encode([rows[0], *repeated, end]))
    assert result['truncated_by_quota'] is True and len(result['events']) == 48


@pytest.mark.parametrize('field,value', [
    ('candidate_base', '0x40000001'), ('event_pc', '0x42767980'), ('expected_destination', '0x47e5d571'),
    ('ordinal', '0x2'), ('writer_sequence', '0x7'), ('anchor_length', '0x8'), ('input_w0', '0x0'),
    ('x0_raw', '0x10000000000000000'), ('cpsr_m', '0x0'), ('cpsr_raw', '0x1'), ('vcpu', '0x1'),
    ('callback_phase', 'after_instruction'), ('x1_api_ok', '0x0'), ('x30_read_length', '0x7'),
    ('cpsr_read_length', '0x8'), ('sp_read_length', '0x7'), ('ttbr0_el1_api_ok', '0x0'),
    ('identity', 'original_AP'), ('pid', '259'), ('capture', '0x1'), ('physical', '0x1'),
    ('store_retirement_verified', '0x1'), ('memory_readback_verified', '0x1')])
def test_bad_event_fields_are_refused(field, value):
    rows = fixture_rows()
    rows[1][field] = value
    with pytest.raises(ValueError):
        w.parse_trace(encode(rows))


@pytest.mark.parametrize('field,value', [('stop', 'base_conflict'), ('ambiguous', '0x1'), ('faults', '0x1'),
    ('fault_lines', '0x1'), ('candidate_found', '0x0'), ('site1_records', '0x0'), ('writer_sequence', '0x2'),
    ('anchor_seen_mask', '0x3'), ('site0_suppressed', '0x1'), ('close_result', 'success')])
def test_bad_or_incomplete_terminal_is_refused(field, value):
    rows = fixture_rows()
    rows[-1][field] = value
    with pytest.raises(ValueError):
        w.parse_trace(encode(rows))


def test_missing_duplicate_unknown_truncated_fields_and_wrong_x1_refused():
    raw = encode(fixture_rows())
    for value in (raw[:-1], raw.replace(b'kind=begin ', b'kind=begin kind=begin ', 1),
                  raw.replace(b'ordinal=0x1 ', b'', 1), raw.replace(b'anchor_length=0xc ', b'extra=1 ', 1),
                  raw.replace(b'\n', b'\r\n'), raw.replace(b'x1_raw=0x47e5d000', b'x1_raw=0x47e5d001', 1)):
        with pytest.raises(ValueError):
            w.parse_trace(value)


def test_optional_absence_requires_explicit_unknown_and_zero_read_length():
    rows = fixture_rows()
    for row in rows[1:-1]:
        row.update(tpidr_el0_available='0x0', tpidr_el0_raw='unknown', tpidr_el0_read_length='0x0',
                   tpidr_el0_api_ok='unknown')
    assert w.parse_trace(encode(rows))['events'][0]['context']['tpidr_el0'] is None
    rows[1]['tpidr_el0_raw'] = '0x0'
    with pytest.raises(ValueError):
        w.parse_trace(encode(rows))


def test_bounded_read_requires_expected_digest_and_safe_regular_file(tmp_path):
    path = tmp_path / 'trace.log'
    raw = encode(fixture_rows())
    path.write_bytes(raw)
    assert w.read_file(path, expected_sha256=w.digest(raw)) == raw
    with pytest.raises(ValueError, match='digest differs'):
        w.read_file(path, expected_sha256='0' * 64)
    with pytest.raises(ValueError, match='oversized'):
        w.read_file(path, limit=len(raw) - 1)
    link = tmp_path / 'alias.log'
    link.symlink_to(path)
    with pytest.raises(ValueError):
        w.read_file(link)
    path.chmod(0o666)
    with pytest.raises(ValueError, match='untrusted'):
        w.read_file(path)
