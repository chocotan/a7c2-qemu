"""SOURCE_ONLY host reader tests for unchanged late rows; no C mock or guest driver."""
from pathlib import Path
import copy
import importlib.util
import unittest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('HOST_TEST_v3_late_reader_data',
                                               HERE / 'integration/test_scope_trace_checks.py')
case = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(case)
checks = case.checks


class V3LateReaderTests(unittest.TestCase):
    def test_all_old_late_sites_retain_exact_operands_and_lazy_pc(self):
        for site in ('M_cmp_pre', 'M_bne_pre', 'request0_bl_pre'):
            rows, _, schema = case.joined_case(sites=())
            rows[-2] = case.late_row(site)
            rows[-1] = case.end_row(rows[:-1])
            result = checks.parse_trace(case.encode(rows), schema)
            actual = next(row for row in result['rows'] if row['kind'] == 'late')
            self.assertEqual(actual, rows[-2])
            self.assertNotEqual(actual['event_pc'], actual['gdb_pc_raw'])
            if site == 'request0_bl_pre':
                self.assertEqual(actual['w1'], '0x00000000')
                self.assertEqual(actual['lr_phase'], 'before_bl')
            else:
                self.assertEqual(actual['loaded_M_u32'], '0x00000000')

    def test_late_exact_keys_phase_width_optional_and_source_prediction_stay_strict(self):
        changes = [('kind', 'M_committed'), ('site', 'M_store_post'), ('callback_phase', 'after_instruction'),
                   ('gdb_pc_api_ok', '0x0'), ('x23_read_length', '0x4'), ('cpsr_read_length', '0x8'),
                   ('sp_available', '0x0'), ('ttbr0_el1_api_ok', '0x0'), ('tpidr_el0_read_length', '0x7'),
                   ('ordinal', '0x01'), ('late_sequence', '0x01'), ('retired', '0x1')]
        for field, value in changes:
            rows, _, schema = case.joined_case(sites=())
            next(row for row in rows if row['kind'] == 'late')[field] = value
            with self.subTest(field=field), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(rows), schema)
        for field, value in (('flags_phase', 'after_bne'), ('z', '0x1'),
                             ('source_next_pc', case.h64(case.BASE + 0x209ee60)),
                             ('source_next_basis', 'retired_pc')):
            rows, _, schema = case.joined_case(sites=())
            rows[-2] = case.late_row('M_bne_pre')
            rows[-1] = case.end_row(rows[:-1])
            rows[-2][field] = value
            with self.subTest(field=field), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(rows), schema)

    def test_late_quota_order_and_end_counts_remain_independent_of_three_producers(self):
        rows, _, schema = case.joined_case(sites=('second_entry', 'entry', 'pre_M_store'))
        rows = [row for row in rows[:-1] if row['kind'] != 'late']
        sequence = 0
        for site in ('request0_bl_pre', 'M_cmp_pre', 'M_bne_pre'):
            for ordinal in range(1, 17):
                sequence += 1
                row = case.late_row(site)
                row.update(ordinal=hex(ordinal), late_sequence=hex(sequence))
                rows.append(row)
        rows.append(case.end_row(rows))
        checks.parse_trace(case.encode(rows), schema)
        self.assertEqual(rows[-1]['late_sequence'], '0x30')
        self.assertEqual(rows[-1]['producer_sequence'], '0x3')
        for key in ('late0_records', 'late1_records', 'late2_records', 'late_sequence'):
            changed = copy.deepcopy(rows)
            changed[-1][key] = '0x0'
            with self.subTest(key=key), self.assertRaises(checks.RejectedTrace):
                checks.parse_trace(case.encode(changed), schema)

    def test_raw_aarch64_modes_are_preserved_and_a32_rejected(self):
        rows, _, schema = case.joined_case(sites=())
        row = next(row for row in rows if row['kind'] == 'late')
        for mode in (0, 4, 5, 8, 9, 12, 13):
            row.update(case.flags(mode))
            checks.parse_trace(case.encode(rows), schema)
        row.update(case.flags(16))
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)

    def test_late_without_prior_scope_candidate_is_rejected(self):
        rows, _, schema = case.joined_case(sites=())
        candidate = rows.pop(1)
        rows.insert(-1, candidate)
        with self.assertRaises(checks.RejectedTrace):
            checks.parse_trace(case.encode(rows), schema)


if __name__ == '__main__':
    unittest.main()
