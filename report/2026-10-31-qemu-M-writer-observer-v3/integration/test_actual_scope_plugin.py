# SPDX-License-Identifier: MIT
"""NOT_RUN: one parent-owned API7 batch, seven cases and six explicit v3 inputs."""
import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('real_scope_v3_unified_fixture', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def test_real_qemu_readonly_scope_v3_plugin_content():
    # Missing any explicit input is a hard collection/execution failure, never a skip.
    paths = {name: Path(os.environ[name]) for name in fixture.API_ENV}
    frozen = json.loads(fixture.read_small(paths['A7C2_SCOPE_V3_TEST_FIXTURE_SOURCES']))
    output = paths['A7C2_SCOPE_V3_TEST_OUTPUT'].resolve()
    result = fixture.run_fixture(paths['A7C2_SCOPE_V3_TEST_QEMU'], paths['A7C2_SCOPE_V3_TEST_PLUGIN'], output,
        schema=paths['A7C2_SCOPE_V3_TEST_SCHEMA'], receipt=paths['A7C2_SCOPE_V3_TEST_RECEIPT'],
        fixture_source_sha256=frozen)
    assert result['status'] == 'PASS_SELF_OWNED_QEMU_SCOPE_V3_FIXTURE'
    assert result['profile'] == 'qemu-readonly-scope-v3' and result['trace_schema'] == 'readonly_scope_v3'
    assert result['trace_schema_sha256'] == fixture.sha256(paths['A7C2_SCOPE_V3_TEST_SCHEMA'])
    assert result['scope_observer_verified'] is True and result['producer_observer_verified'] is True
    for flag in ('capture_verified', 'sony_branch_verified', 'sony_store_verified', 'storecompletion',
                 'instruction_retirement_verified', 'physical_asic_verified', 'original_main_base_joined',
                 'physical_asic_compatibility_verified', 'branchretirement', 'cap', 'capture', 'physical'):
        assert result[flag] is False
    assert tuple(result['variants']) == fixture.API_CASES
    assert result['fixture_source_sha256'] == frozen
    assert set(result['fixture_source_snapshots']) == set(frozen) == fixture.FIXTURE_SOURCE_NAMES
    assert sum(name.startswith('source:') for name in result['inputs']) == 9
    assert sum(name.startswith('fixture-source:') for name in result['inputs']) == 8
    assert not {'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'} & result.keys()
    for name, item in result['fixture_source_snapshots'].items():
        assert item['sha256'] == frozen[name]
        assert fixture.sha256(item['source_path']) == fixture.sha256(item['snapshot_path']) == frozen[name]

    declaration = json.loads(fixture.read_small(paths['A7C2_SCOPE_V3_TEST_SCHEMA']))
    checks = fixture.load_v3_checks()
    for name, case in result['variants'].items():
        assert case['program_baseline_equal'] and case['guest_selfcheck_and_code_readback_exact']
        assert case['scope_schema_assertions'] == 'VERIFIED_SELF_OWNED_ONLY'
        assert case['trace_adapter'] == 'scope_trace_checks_v3.assert_scope_trace_v3'
        baseline = fixture.read_small(output / case['runs']['baseline']['console'])
        plugin_console = fixture.read_small(output / case['runs']['plugin']['console'])
        assert baseline == plugin_console
        raw = fixture.read_small(output / case['runs']['plugin']['plugin_log'])
        assert fixture.hashlib.sha256(raw).hexdigest() == case['trace_sha256']
        assert case['trace_schema_sha256'] == fixture.sha256(paths['A7C2_SCOPE_V3_TEST_SCHEMA'])
        parsed = checks.parse_trace(raw, declaration)
        rows, end = parsed['rows'], parsed['rows'][-1]
        assert parsed['trace_sha256'] == case['trace_sha256']
        producers = [row for row in rows if row['kind'] == 'M_producer']
        assert len(producers) == case['producer_success_rows']
        counts = {site: sum(row['site'] == site for row in producers)
                  for site in ('entry', 'pre_M_store', 'second_entry')}
        assert case['producer_site_counts'] == counts
        assert int(end['producer_sequence'], 16) == len(producers)
        for ordinal, site in enumerate(counts):
            assert int(end[f'producer{ordinal}_records'], 16) == counts[site]
        assert sum(row['scope_anchor_seen'] == '0x0' for row in producers) == case['producer_early_rows']
        assert all(row['context_mode'] == 'other_aarch64' and int(row['cpsr_m'], 16) == 5 for row in producers)
        assert all(int(row['x0_raw'], 16) >> 32 != 0 for row in producers)
        assert all(int(row['x30_raw'], 16) == int(row['caller_raw'], 16) for row in producers)
        if name in ('producer', 'producer_reverse_order'):
            assert counts == {'entry': 16, 'pre_M_store': 16, 'second_entry': 16}
            assert case['producer_early_rows'] == 3
            assert case['producer_calls_per_writer'] == [17, 17] and case['producer_calls'] == 34
            expected_order = ['second_entry', 'entry', 'pre_M_store'] if name.endswith('reverse_order') else [
                'entry', 'pre_M_store', 'second_entry']
            assert [row['site'] for row in producers[:3]] == expected_order
            assert case['producer_discovery_order'] == ([1, 0] if name.endswith('reverse_order') else [0, 1])
            candidate_index = next(index for index, row in enumerate(rows) if row['kind'] == 'candidate')
            assert all(rows.index(row) < candidate_index for row in producers[:3])
            assert int(end['producer_anchor_found'], 16) == int(end['producer2_anchor_found'], 16) == 1
            assert int(end['producer_base'], 16) == int(end['producer2_base'], 16) == fixture.BASE
            assert len(case['runs']['plugin']['actual_producer']['calls']) == 34
            assert case['runs']['plugin']['actual_producer']['low_va_actual_lr_high32_verified'] is False
            for site in counts:
                selected = [row for row in producers if row['site'] == site]
                assert [int(row['ordinal'], 16) for row in selected] == list(range(1, 17))
                assert [int(row['x0_raw'], 16) for row in selected] == list(fixture.PRODUCER_INPUTS[:16])
                assert [int(row['raw_input_u32'], 16) for row in selected] == [
                    value & 0xFFFFFFFF for value in fixture.PRODUCER_INPUTS[:16]]
        elif name == 'producer_corrupt':
            assert counts == {'entry': 16, 'pre_M_store': 16, 'second_entry': 0}
            assert case['producer_early_rows'] == 2
            assert case['producer_discovery_order'] == [0]
            assert int(end['producer_anchor_found'], 16) == 1
            assert int(end['producer2_anchor_found'], 16) == int(end['producer2_base'], 16) == 0
        else:
            assert not producers
        if name == 'producer_short_tb':
            assert all(int(end[field], 16) == 0 for field in
                       ('candidate_found', 'producer_anchor_found', 'producer2_anchor_found', 'producer_sequence'))
            assert result['variants']['producer']['elf_sha256'] == case['elf_sha256']

    # Recheck real raw against independently checked baseline guest values. Corrupt
    # each operand family in expectations so a PC-only adapter cannot pass here.
    for name in ('producer', 'producer_reverse_order'):
        case = result['variants'][name]
        console = fixture.read_small(output / case['runs']['baseline']['console'])
        sections = fixture.elf_layout(fixture.read_small(output / 'build' / name / 'fixture.elf'), False, True)
        expected_producers, _ = fixture.check_producer_console(console, sections, False,
                                                              reverse=name.endswith('reverse_order'))
        expected_entries = fixture.scope_expectations(console, producer=True)
        raw = fixture.read_small(output / case['runs']['plugin']['plugin_log'])
        parsed = checks.assert_scope_trace_v3(raw, expected_entries, fixture.BASE, 16,
            expected_producers=expected_producers, producer_base=fixture.BASE, producer2_base=fixture.BASE)
        assert len(parsed['rows']) > len(expected_producers)
        first_entry = next(row for row in parsed['rows'] if row['kind'] == 'M_producer' and row['site'] == 'entry')
        for field in ('sp', 'ttbr0_el1', 'tpidr_el0'):
            if int(first_entry[field + '_available'], 16):
                bad = copy.deepcopy(expected_producers)
                bad['entry', 1]['optional_raw'][field] ^= 1
                with pytest.raises(ValueError):
                    checks.assert_scope_trace_v3(raw, expected_entries, fixture.BASE, 16,
                        expected_producers=bad, producer_base=fixture.BASE, producer2_base=fixture.BASE)
        for site, field in (('entry', 'x0_raw'), ('entry', 'caller_raw'), ('entry', 'x30_raw'),
                            ('pre_M_store', 'x1_raw'), ('pre_M_store', 'proposed_u32'),
                            ('second_entry', 'x0_raw'), ('second_entry', 'caller_raw')):
            bad = copy.deepcopy(expected_producers)
            bad[site, 1][field] ^= 1
            with pytest.raises(ValueError):
                checks.assert_scope_trace_v3(raw, expected_entries, fixture.BASE, 16,
                    expected_producers=bad, producer_base=fixture.BASE, producer2_base=fixture.BASE)
        for field in (*fixture.GPRS, 'sp', 'nzcv'):
            bad = copy.deepcopy(expected_entries)
            bad[0, 1][field] ^= 1
            with pytest.raises(ValueError):
                checks.assert_scope_trace_v3(raw, bad, fixture.BASE, 16,
                    expected_producers=expected_producers, producer_base=fixture.BASE, producer2_base=fixture.BASE)
        with pytest.raises(ValueError):
            checks.assert_scope_trace_v3(raw, expected_entries, fixture.BASE, 16,
                expected_producers=expected_producers, producer_base=fixture.BASE, producer2_base=None)

    commands = {command['directory']: command for command in result['commands']}
    assert len(commands) == 22  # Six builds, fourteen baseline/plugin commands, two startup rejections.
    for name in fixture.API_CASES:
        pair = [commands[f'cases/{name}-{mode}']['command'] for mode in ('baseline', 'plugin')]
        for argv in pair:
            assert '--unshare-all' in argv and '--clearenv' in argv and '--ro-bind' in argv
            assert argv.count('--bind') == 1 and '-one-insn-per-tb' not in argv
            assert argv[argv.index('-smp') + 1] == 'cpus=1,maxcpus=1'
            if name.startswith('producer'):
                assert argv[argv.index('-m') + 1] == '128M'
            assert argv[argv.index('-accel') + 1] == ('tcg,thread=single,one-insn-per-tb=on'
                if name == 'producer_short_tb' else 'tcg,thread=single')
        assert '-plugin' not in pair[0] and pair[1][-2:] == ['-plugin', '/observer.so,log=/out/plugin.log']
    assert set(result['startup_negatives']) == {'missing_log_argument', 'existing_log'}
    for name, negative in result['startup_negatives'].items():
        assert negative['returncode'] > 0 and negative['guest_started'] is False
        assert negative['returncode'] not in (124, 125, 126, 127)
    assert fixture.read_small(output / 'cases/existing_log/plugin.log') == b'exclusive-log-sentinel\n'

    # Every ordinary artifact other than the manifest itself is hashed, including
    # source snapshots, complete argv logs, baseline dumps and the original raw.
    manifest_bytes = fixture.read_small(output / 'manifest.json')
    assert manifest_bytes == (json.dumps(result, indent=2, sort_keys=True) + '\n').encode('utf-8')
    all_files = {str(path.relative_to(output)) for path in output.rglob('*') if path.is_file()}
    assert all_files == set(result['artifacts']) | {'manifest.json'}
    for relative, item in result['artifacts'].items():
        path = output / relative
        assert not path.is_symlink() and path.resolve() == path
        assert fixture.sha256(path) == item['sha256'] and path.stat().st_size == item['bytes']
