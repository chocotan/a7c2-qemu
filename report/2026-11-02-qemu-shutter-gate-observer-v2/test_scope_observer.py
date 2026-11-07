# SPDX-License-Identifier: MIT
"""Host-only strict and ASan+UBSan source tests; never launch QEMU.

All artifacts remain in dedicated scratch. This module and the C harness are
unexecuted drafts until the parent's single integrated verification batch.
"""
from pathlib import Path
import hashlib
import importlib.util
import itertools
import json
import os
import re
import shlex
import subprocess
import tempfile

import pytest

HERE = Path(__file__).resolve().parent
QEMU = HERE.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2'
SCRATCH = HERE.parents[5] / 'analysis/scratch/functional-shutter-gate-v2-host-tests'
HEADER_SHA = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
FLAGS = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g', '-DHOST_MOCK']
SITES = ('final_entry', 'd570_cbnz_pre', 'successor_1724_pre', 'successor_1838_pre', 'd570_ldr_pre')


def load_parser():
    spec = importlib.util.spec_from_file_location('host_shutter_parser_v2', HERE / 'integration/shutter_gate_trace_checks_v2.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture(scope='session', params=('strict', 'asan-ubsan'))
def observer_binary(request):
    header = QEMU / 'include/plugins/qemu-plugin.h'
    assert hashlib.sha256(header.read_bytes()).hexdigest() == HEADER_SHA
    SCRATCH.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=request.param + '-', dir=SCRATCH))
    flags = FLAGS + (['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                      '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'] if request.param == 'asan-ubsan' else [])
    pkg = subprocess.run(['pkg-config', '--cflags', '--libs', 'glib-2.0'], capture_output=True, text=True, timeout=20)
    assert pkg.returncode == 0, pkg.stderr
    binary = output / 'scope-observer-host-mock'
    command = shlex.split(os.environ.get('CC', 'cc')) + flags + [
        '-I', str(QEMU / 'include/plugins'), str(HERE / 'test-scope-observer.c'),
        '-o', str(binary), *shlex.split(pkg.stdout)]
    (output / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
    proc = subprocess.run(command, capture_output=True, timeout=90)
    (output / 'compile.stdout.log').write_bytes(proc.stdout)
    (output / 'compile.stderr.log').write_bytes(proc.stderr)
    assert proc.returncode == 0, proc.stderr.decode(errors='replace')
    return binary


def run_case(binary, scenario, *arguments):
    output = Path(tempfile.mkdtemp(prefix=scenario + '-', dir=binary.parent))
    log = output / 'trace.log'
    sentinel = b'unchanged-existing-host-log\n'
    if scenario == 'exclusive':
        log.write_bytes(sentinel)
    proc = subprocess.run([str(binary), scenario, str(log), *map(str, arguments)], capture_output=True,
                          env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                                   UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'), timeout=30)
    (output / 'stdout.log').write_bytes(proc.stdout)
    (output / 'stderr.log').write_bytes(proc.stderr)
    assert proc.returncode == 0, proc.stderr.decode(errors='replace')
    assert proc.stdout == b''
    assert b'Sanitizer' not in proc.stderr and b'runtime error:' not in proc.stderr
    if scenario == 'exclusive':
        assert log.read_bytes() == sentinel
        return sentinel, proc.stderr
    return log.read_bytes() if log.exists() else b'', proc.stderr


def rows(raw):
    return [dict(token.split('=', 1) for token in line.decode('ascii').split(' '))
            for line in raw.splitlines()]


def schema():
    return load_parser().object_json((HERE / 'log-schema-shutter-gate-v2.json').read_bytes())


@pytest.mark.parametrize('scenario', ('success', 'stub', 'absent', 'weak_first', 'weak_other', 'weak_other_original', 'transition',
                                    'low32', 'modes', 'quotas', 'longest', 'address', 'known_short',
                                    'mutation', 'short_tb', 'reuse'))
def test_real_c_formatter_passes_direct_schema_and_counter_parser(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario)
    assert errors == b''
    parsed = load_parser().parse_trace(raw, schema())
    assert b''.join(bytes.fromhex(item['raw_hex']) for item in parsed['raw_ledger']) == raw
    assert parsed['end']['close_result'] == 'unknown'
    assert parsed['begin']['sites'] == '0x5'
    assert parsed['end']['site1_unbound_callbacks'] == parsed['end']['site4_unbound_callbacks'] == '0x0'
    assert len(parsed['rows']) <= 114 and len(raw) <= 233472
    if parsed['end']['candidate_found'] == '0x1':
        assert int(parsed['end']['anchor_seen_mask'], 16) & 0x12 == 0x12
    if scenario in ('success', 'stub', 'absent'):
        assert len(parsed['rows']) == 7
        for row in parsed['rows'][1:-1]:
            assert row['gdb_pc_raw'] == '0x123456789abcdef0' and row['event_pc'] != row['gdb_pc_raw']
            assert row['x30_raw'] == '0xabcd005501af1830'
            assert row['context_mode'] == 'EL0t'
            for name in ('sp', 'ttbr0_el1', 'tpidr_el0'):
                assert row[name + '_available'] == ('0x0' if scenario == 'absent' else '0x1')
                if scenario == 'absent':
                    assert row[name + '_raw'] == row[name + '_api_ok'] == 'unknown'
                    assert row[name + '_read_length'] == '0x0'
        assert parsed['rows'][1]['entry_anchor'] == ('existing_main_stub8' if scenario == 'stub' else 'original16')
    if scenario in ('mutation', 'short_tb'):
        assert parsed['end']['candidate_found'] == '0x0'
        assert not any(row['kind'] == 'shutter_gate' for row in parsed['rows'])
    if scenario == 'weak_first':
        assert [parsed['end']['site%d_unbound_callbacks' % s] for s in range(5)] == ['0x1', '0x0', '0x1', '0x1', '0x0']
        assert parsed['end']['gate_sequence'] == '0x5'
    if scenario in ('weak_other', 'weak_other_original'):
        assert parsed['end']['candidate_base'] == '0x0000005500000000'
        assert parsed['end']['gate_sequence'] == '0x2' and parsed['end']['ambiguous'] == '0x0'
        assert parsed['end']['site0_unbound_callbacks'] == '0x2'
    if scenario == 'low32':
        branch_rows = parsed['rows'][1:-1]
        assert [row['x0_raw'] for row in branch_rows] == [
            '0xfeedface00000000', '0xfeedface00000001', '0xfeedfaceffffffff', '0xfeedface80000000']
        assert [row['loaded_w0'] for row in branch_rows] == ['0x00000000', '0x00000001', '0xffffffff', '0x80000000']
        assert [row['source_next_pc'] for row in branch_rows] == [
            '0x0000005501af1838', '0x0000005501af1724', '0x0000005501af1724', '0x0000005501af1724']
    if scenario in ('quotas', 'longest'):
        assert len(parsed['rows']) == 82
        assert [parsed['end']['site%d_suppressed' % i] for i in range(5)] == ['0x2'] * 5
        assert all(len(line) < 2048 for line in raw.splitlines(keepends=True))


@pytest.mark.parametrize('order', [''.join(order) for order in itertools.permutations('0123')])
def test_each_discovery_order_keeps_cached_unbound_callbacks(observer_binary, order):
    raw, errors = run_case(observer_binary, 'order_' + order)
    assert not errors
    parsed = load_parser().parse_trace(raw, schema())
    for s in (0, 2, 3):
        unbound = int(order.index(str(s)) < order.index('1'))
        assert int(parsed['end']['site%d_unbound_callbacks' % s], 16) == unbound
        assert int(parsed['end']['site%d_records' % s], 16) == 2 - unbound
    assert parsed['end']['site4_records'] == '0x2' and parsed['end']['site4_unbound_callbacks'] == '0x0'


ENTRY_REGS = ('pc', 'x0', 'x30', 'cpsr', 'x1', 'x2', 'x3', 'sp', 'TTBR0_EL1', 'TPIDR_EL0')
INTERNAL_REGS = ('pc', 'x0', 'x30', 'cpsr', 'x19', 'x22', 'x23', 'x29', 'sp', 'TTBR0_EL1', 'TPIDR_EL0')


@pytest.mark.parametrize('site,register', [(s, r) for s in range(5) for r in
                                         (ENTRY_REGS if s == 0 else INTERNAL_REGS)])
@pytest.mark.parametrize('failure', ('false', 'short', 'long', 'residue', 'empty'))
def test_each_present_read_rejects_whole_row_without_spending_ordinal(observer_binary, site, register, failure):
    raw, errors = run_case(observer_binary, 'read', site, register, failure)
    assert errors == b''
    evidence = rows(raw)
    fault, = [row for row in evidence if row['kind'] == 'fault']
    success, = [row for row in evidence if row['kind'] == 'shutter_gate']
    assert fault['reg'] == register and fault['reason'] == 'register_read'
    assert success['ordinal'] == success['gate_sequence'] == '0x1'
    assert int(fault['api_ok'], 16) == (0 if failure in ('false', 'residue') else 1)
    expected_length = 4 if register == 'cpsr' else 8
    assert int(fault['read_length'], 16) == (0 if failure == 'empty' else
                                           expected_length + (-1 if failure == 'short' else 1 if failure == 'long' else 0))
    parser = load_parser()
    with pytest.raises(parser.RejectedTrace) as caught:
        parser.parse_trace(raw, schema())
    assert bytes.fromhex(caught.value.evidence['raw_hex']) == raw


@pytest.mark.parametrize('site', range(5))
def test_true_with_exact8_cpsr_is_not_exact4(observer_binary, site):
    raw, errors = run_case(observer_binary, 'read', site, 'cpsr', 'cpsr8')
    assert not errors
    fault, = [row for row in rows(raw) if row['kind'] == 'fault']
    assert fault['api_ok'] == '0x1' and fault['read_length'] == '0x8' and fault['required_length'] == '0x4'


@pytest.mark.parametrize('scenario', ('target', 'api', 'api_min', 'user', 'smp', 'maxcpu', 'duplicate',
                                    'null_list', 'empty_list', 'huge_list', 'init_cpu', 'exec_cpu', 'metadata',
                                    'reinit', 'a32', 'reserved', 'conflict', 'changed', 'shape',
                                    'copy_short', 'copy_long', 'noncontinuous', 'fault_budget'))
def test_structural_failures_preserve_original_faults(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario)
    assert errors == b''
    parser = load_parser()
    with pytest.raises(parser.RejectedTrace) as caught:
        parser.parse_trace(raw, schema())
    assert caught.value.evidence['raw_ledger'] and caught.value.evidence['trace_sha256'] == hashlib.sha256(raw).hexdigest()
    if scenario == 'fault_budget':
        assert len(rows(raw)) == 114
        assert rows(raw)[-1]['fault_lines'] == '0x20' and rows(raw)[-1]['suppressed_faults'] == '0x30'
        assert rows(raw)[-1]['site4_records'] == '0x10' and rows(raw)[-1]['gate_sequence'] == '0x50'
        assert len(raw) <= 233472 and all(len(line) < 2048 for line in raw.splitlines(keepends=True))


@pytest.mark.parametrize('register', ('pc', 'x0', 'x1', 'x2', 'x3', 'x19', 'x22', 'x23', 'x29', 'x30', 'cpsr'))
def test_missing_union_descriptor_fails_closed(observer_binary, register):
    raw, errors = run_case(observer_binary, 'missing', register)
    assert not errors
    evidence = rows(raw)
    assert any(row.get('reg') == register and row.get('reason') == 'unknown_register' for row in evidence)
    assert evidence[-1]['gate_sequence'] == '0x0'


@pytest.mark.parametrize('site', range(5))
@pytest.mark.parametrize('scenario', ('changed', 'shape', 'copy_short', 'copy_long', 'noncontinuous', 'known_short'))
def test_complete_known_anchor_changes_but_short_tb_stays_unknown(observer_binary, scenario, site):
    raw, errors = run_case(observer_binary, scenario, site)
    assert not errors
    evidence = rows(raw)
    assert (evidence[-1]['stop'] == 'none') == (scenario == 'known_short')


@pytest.mark.parametrize('scenario', ('changed_stub2', 'entry_prefix2', 'entry_prefix3'))
def test_complete_stub_change_cannot_hide_behind_short_original_form(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario)
    assert not errors
    evidence = rows(raw)
    parser = load_parser()
    if scenario == 'changed_stub2':
        fault, = [row for row in evidence if row['kind'] == 'fault']
        assert fault['reason'] == 'anchor_changed' and fault['remaining_insns'] == '0x2'
        assert evidence[-1]['stop'] == 'anchor_changed' and evidence[-1]['site0_records'] == '0x1'
        with pytest.raises(parser.RejectedTrace):
            parser.parse_trace(raw, schema())
    else:
        assert parser.parse_trace(raw, schema())['end']['stop'] == 'none'


@pytest.mark.parametrize('scenario', ('write_failure', 'flush_failure', 'format_failure', 'close_failure',
                                    'duplicate_install', 'exclusive', 'badarg'))
def test_io_and_startup_failure_cannot_be_success(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario)
    assert b'scope_observer_host_error' in errors
    if scenario == 'close_failure':
        assert rows(raw)[-1]['close_result'] == 'unknown' and b'stage=close' in errors
    elif scenario in ('write_failure', 'flush_failure', 'format_failure'):
        assert not any(row['kind'] == 'end' for row in rows(raw))


@pytest.mark.parametrize('scenario', ('dual_tap', 'duplicate_gate'))
def test_shared_window_registers_source_then_branch_without_event_pc_bit2_loss(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario)
    assert not errors
    parsed = load_parser().parse_trace(raw, schema())
    source, branch = parsed['rows'][1:-1]
    assert [source['site'], branch['site']] == ['d570_ldr_pre', 'd570_cbnz_pre']
    assert source['event_pc'] == '0x0000005501af1830'
    assert branch['event_pc'] == '0x0000005501af1834'
    assert source['x0_raw'] == '0x1122334455667788'
    assert branch['x0_raw'] == '0xdeadbeef00000001' and branch['loaded_w0'] == '0x00000001'
    assert source['gate_sequence'] == '0x1' and branch['gate_sequence'] == '0x2'
    assert parsed['end']['site4_records'] == parsed['end']['site1_records'] == '0x1'


def test_source_keeps_full64_null_handle_pointer_and_internal_context_without_prediction(observer_binary):
    raw, errors = run_case(observer_binary, 'source_pointer')
    assert not errors
    parsed = load_parser().parse_trace(raw, schema())
    source_rows = parsed['rows'][1:-1]
    assert [row['x0_raw'] for row in source_rows] == [
        '0x0000000000000000', '0x1122334455667788', '0xfedcba9800000000', '0xffffffffffffffff']
    context = {'x19_raw': '0x0000007ffffffcf8', 'x22_raw': '0xabcdef0180000000',
               'x23_raw': '0x1122334455667788', 'x29_raw': '0x0000007ffffffcb0',
               'x30_raw': '0xabcd005501af1830', 'sp_raw': '0x0000007ffffffcb0',
               'ttbr0_el1_raw': '0x1234005500456000', 'tpidr_el0_raw': '0xfedcba9876543210'}
    for row in source_rows:
        assert row['site'] == 'd570_ldr_pre' and row['event_pc'] == '0x0000005501af1830'
        assert row['gdb_pc_raw'] == '0x123456789abcdef0'
        assert row['x0_read_length'] == '0x8' and row['x0_api_ok'] == '0x1'
        assert {key: row[key] for key in context} == context
        assert not any(key in row for key in ('loaded_w0', 'source_taken_prediction', 'source_next_pc',
                                               'source_next_basis', 'source_pointer_u64', 'source_pointer_raw'))
    assert parsed['end']['site0_records'] == parsed['end']['site1_records'] == '0x0'
    assert parsed['end']['site4_records'] == '0x4'


@pytest.mark.parametrize('packed', [
    ((0x5501af1830 | (1 << 49)) | low) for low in (1, 2, 3)
] + [
    0x5501af1830 | (1 << 49) | (1 << 48),
    0x5501af1834 | (1 << 48) | 1,
    (1 << 49),
    0x1af1830 | (1 << 49),
    0x5501af1838 | (1 << 49),
    ((1 << 48) - 4) | (1 << 49),
    0x5501bf1830 | (1 << 49),
    1,
] + [(0x5501af1830 | (1 << 49) | (1 << bit)) for bit in range(50, 64)])
def test_userdata_rejects_bad_site_stub_high_bits_or_base_before_register_reads(observer_binary, packed):
    raw, errors = run_case(observer_binary, 'userdata', hex(packed))
    assert not errors
    evidence = rows(raw)
    fault, = [row for row in evidence if row['kind'] == 'fault']
    assert fault['reason'] == 'invalid_callback_context' and int(fault['packed_raw'], 16) == packed
    assert evidence[-1]['gate_sequence'] == evidence[-1]['site4_records'] == '0x0'
    assert evidence[-1]['site4_unbound_callbacks'] == '0x0'
    parser = load_parser()
    with pytest.raises(parser.RejectedTrace):
        parser.parse_trace(raw, schema())


@pytest.mark.parametrize('site', (1, 4))
def test_both_strong_callbacks_require_previously_bound_base(observer_binary, site):
    raw, errors = run_case(observer_binary, 'unbound_strong', site)
    assert not errors
    evidence = rows(raw)
    fault, = [row for row in evidence if row['kind'] == 'fault']
    assert fault['reason'] == 'invalid_callback_context'
    assert evidence[-1]['candidate_found'] == evidence[-1]['gate_sequence'] == '0x0'
    assert evidence[-1]['site%d_unbound_callbacks' % site] == '0x0'
    parser = load_parser()
    with pytest.raises(parser.RejectedTrace):
        parser.parse_trace(raw, schema())


@pytest.mark.parametrize('scenario', ('modes', 'a32', 'reserved'))
def test_source_aarch64_modes_or_invalid_mode_fault_remain_raw(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario, 4)
    assert not errors
    parser = load_parser()
    if scenario == 'modes':
        parsed = parser.parse_trace(raw, schema())
        source_rows = parsed['rows'][1:-1]
        assert [row['cpsr_m'] for row in source_rows] == ['0x00', '0x04', '0x05', '0x08', '0x09', '0x0c', '0x0d']
        assert [row['context_mode'] for row in source_rows] == ['EL0t'] + ['other_aarch64'] * 6
    else:
        fault, = [row for row in rows(raw) if row['kind'] == 'fault']
        assert fault['reason'] == 'invalid_mode' and fault['site'] == 'd570_ldr_pre'
        assert rows(raw)[-1]['site4_records'] == '0x0'
        with pytest.raises(parser.RejectedTrace):
            parser.parse_trace(raw, schema())


@pytest.mark.parametrize('scenario', ('write_failure', 'flush_failure'))
def test_source_io_failure_never_commits_a_success_ordinal(observer_binary, scenario):
    raw, errors = run_case(observer_binary, scenario, 4)
    assert b'scope_observer_host_error' in errors
    assert not any(row['kind'] == 'end' for row in rows(raw))
    parser = load_parser()
    with pytest.raises(parser.RejectedTrace):
        parser.parse_trace(raw, schema())


def test_source_contract_binds_actual_schema_without_self_or_future_fixture_hashes():
    contract = json.loads((HERE / 'source-contract-shutter-gate-v2.json').read_bytes())
    assert contract['profile'] == 'qemu-readonly-shutter-gate-v2'
    assert contract['trace_schema'] == 'readonly_shutter_gate_v2'
    assert contract['trace_schema_sha256'] == hashlib.sha256((HERE / 'log-schema-shutter-gate-v2.json').read_bytes()).hexdigest()
    assert 'source_contract_sha256' not in contract and 'fixture_source_sha256' not in contract
    assert all(value is False for value in contract['flags'].values())
    assert [item['site'] for item in contract['sites']] == list(SITES)
    declaration = schema()
    assert declaration['site_additional_fields']['d570_ldr_pre'] == declaration['site_additional_fields']['successor_1724_pre']
    assert declaration['file_contract'] == {'maximum_file_lines': 114, 'maximum_line_bytes_exclusive': 2048,
                                           'maximum_file_bytes_conservative': 233472, 'quota_per_site': 16,
                                           'maximum_success_rows': 80, 'maximum_fault_lines': 32}


def test_source_surface_is_exact_readonly_api7():
    source = (HERE / 'scope-observer.c').read_text()
    calls = set(re.findall(r'\b(qemu_plugin_\w+)\s*\(', source)) - {'qemu_plugin_install'}
    assert calls == {'qemu_plugin_' + name for name in (
        'get_registers', 'read_register', 'register_vcpu_init_cb', 'register_vcpu_tb_trans_cb',
        'register_vcpu_insn_exec_cb', 'register_atexit_cb', 'tb_n_insns', 'tb_get_insn',
        'insn_vaddr', 'insn_size', 'insn_data')}
    for forbidden in ('QEMU_PLUGIN_CB_RW_REGS', 'qemu_plugin_write_', 'qemu_plugin_set_pc',
                      'qemu_plugin_read_memory_', 'qemu_plugin_translate_vaddr',
                      'qemu_plugin_register_vcpu_mem', 'qemu_plugin_register_vcpu_syscall', 'QEMU_PLUGIN_INLINE'):
        assert forbidden not in source
    assert 'QEMU_PLUGIN_CB_R_REGS' in source
