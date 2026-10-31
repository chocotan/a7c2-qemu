"""Content-level corruption cases for the self-owned plugin integration log."""
import importlib.util
from pathlib import Path
import struct
import unittest

SPEC = importlib.util.spec_from_file_location('scope_trace_fixture_cases', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)
checks = fixture.trace_checks


def log_case():
    rows = [{'kind': 'begin', 'schema': 'readonly_scope_v1', 'plugin_api': '0x7', 'max_vcpus': '0x1',
             'lr_quota': '0x10', 'fault_quota': '0x20', 'anchor_length': '0x18',
             'register_byte_order': 'little', 'identity_limit': 'raw_context_only_no_pid_tid_module_identity',
             'poweron_quota': '0x10', 'poweron_anchor_length': '0x8'},
            {'kind': 'candidate', 'candidate_base': hex(fixture.BASE),
             'translated_entry_pc': hex(fixture.ENTRY), 'anchor_length': '0x18'}]
    expected = {}
    for ordinal in range(1, 17):
        for slot in (0, 1):
            values = struct.unpack('<51Q', fixture.expected_record(ordinal, slot, False))
            wanted = {name: values[int(name[1:])] for name in checks.GPRS}
            wanted.update(actual_pc=fixture.ENTRY, translated_entry_pc=fixture.ENTRY,
                          candidate_base=fixture.BASE, lr=fixture.LRS[slot], sp=fixture.BASE + 0x200000,
                          nzcv=values[32], cpsr_m=5)
            expected[slot, ordinal] = wanted
            row = {name: '0x%016x' % value for name, value in wanted.items() if name not in ('nzcv', 'cpsr_m')}
            row.update(kind='entry', vcpu='0x0', lr_slot=hex(slot), ordinal=hex(ordinal),
                       cpsr_raw='0x%08x' % (values[32] | 0x3c5), nzcv='0x%08x' % values[32],
                       nzcv_mask='0xf0000000', cpsr_m='0x05', context_mode='other_aarch64', api_ok='0x1')
            row.update({name + '_read_length': '0x8' for name in ('pc', 'lr', *checks.GPRS, 'sp')})
            row['cpsr_read_length'] = '0x4'
            for token in checks.TOKENS:
                row.update({token + '_available': '0x0', token + '_raw': 'unknown', token + '_read_length': '0x0'})
            rows.append(row)
    rows.append({'kind': 'end', 'stop': 'none', 'ambiguous': '0x0', 'candidate_found': '0x1',
                 'candidate_base': hex(fixture.BASE), 'conflicting_base': '0x0',
                 'lr0_records': '0x10', 'lr1_records': '0x10', 'poweron_records': '0x0',
                 'late0_records': '0x0', 'late1_records': '0x0', 'late2_records': '0x0', 'late_sequence': '0x0',
                 'fault_lines': '0x0', 'faults': '0x0',
                 'suppressed_faults': '0x0', 'other_lr': '0x10', 'close_result': 'unknown'})
    for row in rows:
        row.update(checks.COMMON)
    return rows, expected


def encode(rows):
    return ''.join('kind=' + row['kind'] + ' ' + ' '.join(k + '=' + v for k, v in row.items() if k != 'kind') + '\n'
                   for row in rows).encode('ascii')


class ScopeTraceContentTests(unittest.TestCase):
    def test_full_64bit_values_and_both_complete_quotas(self):
        rows, expected = log_case()
        result = checks.assert_scope_trace(encode(rows), expected, fixture.BASE, 16)
        self.assertTrue(result['synthetic_scope_observer_verified'])
        self.assertEqual(result['entries'], 32)
        self.assertFalse(result['capture_verified'])
        self.assertFalse(result['original_Main_identity_verified'])

    def test_truncated_duplicate_and_unproved_prefix_are_refused(self):
        rows, expected = log_case()
        raw = encode(rows)
        for changed in (raw[:-1], b'0' + raw, raw.replace(b'kind=entry ', b'kind=entry x23=0x0000000000000001 ', 1)):
            with self.subTest(changed=changed[:32]), self.assertRaises(ValueError):
                checks.assert_scope_trace(changed, expected, fixture.BASE, 16)

    def test_corrupt_scope_fields_never_pass_as_observation(self):
        for key, value in (('x23', '0x0000000055667701'), ('lr_slot', '0x2'), ('ordinal', '0x11'),
                           ('sp_read_length', '0x0'), ('cpsr_read_length', '0x8'),
                           ('cpsr_m', '0x00'), ('context_mode', 'EL0t'), ('capture', '0x1'),
                           ('ttbr0_el1_raw', '0x0000000000000000'), ('unexpected', '0x1')):
            rows, expected = log_case()
            rows[2][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                checks.assert_scope_trace(encode(rows), expected, fixture.BASE, 16)

    def test_missing_entry_fault_counter_or_falsely_clean_close_is_refused(self):
        for variant in ('missing', 'counter', 'fault', 'close'):
            rows, expected = log_case()
            if variant == 'missing':
                del rows[2]
            else:
                key, value = {'counter': ('lr0_records', '0xf'), 'fault': ('faults', '0x1'),
                              'close': ('close_result', 'success')}[variant]
                rows[-1][key] = value
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                checks.assert_scope_trace(encode(rows), expected, fixture.BASE, 16)


if __name__ == '__main__':
    unittest.main()
