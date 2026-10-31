"""The native join must never treat missing tokens or a different Main as equal."""
from pathlib import Path
import importlib.util
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('scope_context_content', HERE / 'check_run_context.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
FIXTURE_SPEC = importlib.util.spec_from_file_location('scope_context_log_fixture', HERE / 'integration/test_scope_trace_checks.py')
case = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(case)


def joined_case():
    rows, _ = case.log_case()
    base = case.fixture.BASE
    tokens = {'ttbr0_el1': '0x1234000400100000', 'tpidr_el0': '0x0000000040208000'}
    for row in rows:
        if row['kind'] == 'entry':
            row['cpsr_raw'] = '0x%08x' % (int(row['nzcv'], 16) | 0x3c0)
            row['cpsr_m'] = '0x00'
            row['context_mode'] = 'EL0t'
            for name, value in tokens.items():
                row[name + '_available'] = '0x1'
                row[name + '_raw'] = value
                row[name + '_read_length'] = '0x8'
    power = {'kind': 'poweron_context', 'site': 'dispatch', 'vcpu': '0x0', 'ordinal': '0x1',
             'actual_pc': hex(base + 0x1951844), 'translated_entry_pc': hex(base + 0x1951844),
             'candidate_base': hex(base), 'anchor_length': '0x8', 'controller': '0x40010000',
             'raw_x2': '0x0000000001000090', 'raw_u32': '0x01000090',
             'caller_raw': hex(base + 0x1e79354), 'cpsr_raw': '0xa00003c0',
             'cpsr_m': '0x00', 'context_mode': 'EL0t', 'api_ok': '0x1',
             'pc_read_length': '0x8', 'x0_read_length': '0x8', 'x2_read_length': '0x8',
             'x30_read_length': '0x8', 'cpsr_read_length': '0x4'}
    power.update(case.checks.COMMON)
    for name, value in tokens.items():
        power.update({name + '_available': '0x1', name + '_raw': value, name + '_read_length': '0x8'})
    rows.insert(2, power)
    rows[-1]['poweron_records'] = '0x1'
    main = dict.fromkeys(checker.MAIN_KEYS, '0')
    main.update(site='dispatch', n='1', pid='259', tid='345', base=hex(base),
                controller=power['controller'], caller_raw=power['caller_raw'], caller_app='0x1e79354',
                raw_u32='0x01000090', raw_known='1', numeric_route_match='1', observation_only='1',
                phase='entry', event_id_unverified='1', producer_unknown='1',
                quota='poweron_entry16', open_rc='7', reads='8/2/1/1/4/4/4',
                read_errno='0/0/0/0/0/0/0')
    console = ('OBS SHUTTER_DETAIL_POWERON ' + ' '.join(k + '=' + v for k, v in main.items()) + '\r\n').encode()
    schema = {'common_fields_every_line': dict(case.checks.COMMON, kind='all'),
              'kinds': {row['kind']: {k: 'field' for k in row if k not in case.checks.COMMON and k != 'kind'}
                        for row in rows}}
    return rows, console, schema


class NativeContextJoinTests(unittest.TestCase):
    def test_raw_context_join_keeps_pid_and_capture_limits(self):
        rows, console, schema = joined_case()
        result = checker.correlate(console, case.encode(rows), schema)
        self.assertTrue(result['context_correlated'])
        self.assertEqual(len(result['observations']), 32)
        self.assertEqual(result['poweron_Main_joins'][0]['Main_reported_tid'], 345)
        self.assertFalse(result['PID_TID_uniqueness_verified'])
        self.assertFalse(result['original_store_or_return_verified'])
        self.assertFalse(result['capture_verified'])

    def test_missing_or_different_tokens_do_not_fabricate_a_join(self):
        for mode in ('missing_both', 'different_scope', 'wrong_Main'):
            rows, console, schema = joined_case()
            if mode == 'wrong_Main':
                rows[2]['controller'] = '0x40010001'
            elif mode == 'different_scope':
                for row in rows:
                    if row['kind'] == 'entry':
                        row['tpidr_el0_raw'] = '0x0000000040208010'
            else:
                for row in rows:
                    if row['kind'] in ('entry', 'poweron_context'):
                        row['ttbr0_el1_available'] = '0x0'
                        row['ttbr0_el1_raw'] = 'unknown'
                        row['ttbr0_el1_read_length'] = '0x0'
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'TRACE_MISSING'):
                checker.correlate(console, case.encode(rows), schema)

    def test_original_Main_prefix_duplicate_or_failed_read_is_refused(self):
        rows, console, schema = joined_case()
        for bad in (b'0' + console, console.replace(b'pid=259', b'pid=259 pid=259'),
                    console.replace(b'reads=8/2/1/1/4/4/4', b'reads=8/2/1/1/3/4/4')):
            with self.subTest(console=bad[:48]), self.assertRaises(ValueError):
                checker.correlate(bad, case.encode(rows), schema)


if __name__ == '__main__':
    unittest.main()
