# SPDX-License-Identifier: MIT
"""SOURCE_ONLY / NOT_RUN: four-case API7 batch, to run after parent integration.

Missing explicit inputs fail. This file never supplies fake trace rows, skips a
case, loads a legacy reader, or labels HOST_TEST vectors as actual API evidence.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('shutter_gate_v1_actual_batch', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def test_real_qemu_shutter_gate_v1_direct_raw_and_independent_operands():
    paths = fixture.environment_paths()
    key = 'A7C2_SHUTTER_GATE_V1_TEST_'
    frozen = fixture.object_json(fixture.read_small(paths[key + 'FIXTURE_SOURCES']))
    output = paths[key + 'OUTPUT']
    result = fixture.run_fixture(paths[key + 'QEMU'], paths[key + 'PLUGIN'], output,
        schema=paths[key + 'SCHEMA'], receipt=paths[key + 'RECEIPT'], fixture_source_sha256=frozen,
        fixture_sources_file=paths[key + 'FIXTURE_SOURCES'])
    assert result['status'] == 'PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V1_FIXTURE'
    assert result['profile'] == 'qemu-readonly-shutter-gate-v1'
    assert result['trace_schema'] == 'readonly_shutter_gate_v1'
    assert result['shutter_gate_observer_verified'] is True
    assert result['trace_schema_sha256'] == fixture.sha256(paths[key + 'SCHEMA'])
    for name in ('capture_verified', 'capture', 'physical', 'physical_asic_compatibility_verified',
                 'instruction_retirement_verified', 'retirement', 'branchretirement', 'Main_identity_verified',
                 'AP_identity_verified', 'invocation_pairing_verified', 'branch_edge_verified',
                 'api_fault_injection_verified', 'lr_high32_actual_coverage'):
        assert result[name] is False
    assert tuple(result['variants']) == fixture.API_CASES
    assert set(result['startup_negatives']) == {'missing_log_argument', 'existing_log'}
    assert result['fixture_source_sha256'] == frozen
    assert set(result['fixture_source_snapshots']) == fixture.FIXTURE_SOURCE_NAMES == set(frozen)
    assert sum(name.startswith('source:') for name in result['inputs']) == 7
    assert sum(name.startswith('fixture-source:') for name in result['inputs']) == 7
    for name, snapshot in result['fixture_source_snapshots'].items():
        assert fixture.sha256(snapshot['source_path']) == fixture.sha256(snapshot['snapshot_path']) == frozen[name]
    assert not fixture.FORBIDDEN_ALIASES & result.keys()

    declaration = fixture.object_json(fixture.read_small(paths[key + 'SCHEMA']))
    checks = fixture.load_checks()
    for case, item in result['variants'].items():
        baseline = fixture.read_small(output / item['runs']['baseline']['console'])
        observed = fixture.read_small(output / item['runs']['plugin']['console'])
        assert baseline == observed
        assert item['program_baseline_equal'] is True
        assert item['guest_selfcheck_and_code_readback_exact'] is True
        assert item['trace_adapter'] == 'shutter_gate_trace_checks_v1.assert_shutter_gate_trace_v1'
        sections = fixture.elf_layout(fixture.read_small(output / item['elf']), case)
        expected, metadata = fixture.check_console(baseline, sections, case)
        assert fixture.object_json(fixture.read_small(output / item['expected_operands'])) == expected
        assert metadata == item['boundary_metadata']
        raw = fixture.read_small(output / item['runs']['plugin']['plugin_log'])
        assert hashlib.sha256(raw).hexdigest() == item['trace_sha256']
        checks.assert_shutter_gate_trace_v1(raw, declaration, expected)
        parsed = checks.parse_trace(raw, declaration)
        assert all(name in parsed for name in ('rows', 'raw_ledger', 'begin', 'end'))
        assert fixture.check_trace_counters(parsed, expected, metadata) == item['actual_callback_counts']
        rows = [row for row in parsed['rows'] if row['kind'] == 'shutter_gate']
        assert all(row['context_mode'] == 'other_aarch64' and int(row['cpsr_m'], 16) == 5 for row in rows)
        assert all(row['identity'] == 'unknown' and row['binding'] == 'unbound' and
                   row['capture'] == row['physical'] == row['retirement'] == '0x0' for row in rows)
        if case in fixture.API_CASES[:2]:
            assert len(rows) == 64
            assert [len(expected['site_rows'][site]) for site in fixture.SITES] == [40, 41, 21, 20]
            assert list(expected['minimum_suppressed'].values()) == [24, 25, 5, 4]
            assert rows[0]['site'] == 'd570_cbnz_pre'  # Explicit gate warmup precedes measured entry.
            assert rows[1]['site'] == 'successor_1724_pre'
            assert expected['site_rows']['d570_cbnz_pre'][0]['registers']['x0'] == 1
            for site in fixture.SITES:
                selected = [row for row in rows if row['site'] == site]
                assert [int(row['ordinal'], 16) for row in selected] == list(range(1, 17))
                assert len(selected) == 16
                assert all(int(row['cpsr_raw'], 16) & 0x1F == 5 for row in selected)
            branches = [row for row in rows if row['site'] == 'd570_cbnz_pre']
            assert {int(row['loaded_w0'], 16) for row in branches} == {0, 1, 0xFFFFFFFF, 0x80000000}
            for row in branches:
                w0 = int(row['x0_raw'], 16) & 0xFFFFFFFF
                assert int(row['loaded_w0'], 16) == w0
                assert int(row['source_next_pc'], 16) == (fixture.TARGET if w0 else fixture.FALLTHROUGH)
                assert row['source_next_basis'] == 'w0_low32'
        else:
            assert expected['discriminator_expected'] is False
            assert all(not rows for rows in expected['site_rows'].values())
            assert not rows  # No exact strong discriminator exists in these owned runs.
            assert item['actual_callback_counts']['d570_cbnz_pre']['total_callbacks'] == 0
            if case == 'short_tb':
                assert all(count['total_callbacks'] == 0 for count in item['actual_callback_counts'].values())
                assert item['elf'] == result['variants']['original_entry']['elf']
                assert item['elf_sha256'] == result['variants']['original_entry']['elf_sha256']

        # The peer must compare every independently sampled operand family. Alter
        # full64 high bits as well as low32; lazy GDB PC is deliberately not paired.
        if expected['discriminator_expected']:
            for site in fixture.SITES:
                first = expected['site_rows'][site][0]
                for register in first['registers']:
                    for bit in (1, 1 << 32):
                        bad = copy.deepcopy(expected)
                        bad['site_rows'][site][0]['registers'][register] ^= bit
                        with pytest.raises(ValueError):
                            checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
                for field in ('event_pc', 'cpsr'):
                    bad = copy.deepcopy(expected)
                    bad['site_rows'][site][0][field] ^= 4 if field == 'event_pc' else 0x40000000
                    with pytest.raises(ValueError):
                        checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
                first_raw = next(row for row in rows if row['site'] == site)
                for field in ('sp', 'ttbr0_el1', 'tpidr_el0'):
                    if int(first_raw[field + '_available'], 16):
                        bad = copy.deepcopy(expected)
                        bad['site_rows'][site][0][field] ^= 1 << 32
                        with pytest.raises(ValueError):
                            checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
                        bad['site_rows'][site][0][field] = None
                        with pytest.raises(ValueError):
                            checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
                    else:
                        assert first_raw[field + '_raw'] == 'unknown'
                        assert first_raw[field + '_api_ok'] == 'unknown'
                        assert first_raw[field + '_read_length'] == '0x0'
                bad = copy.deepcopy(expected)
                register = next(iter(first['registers']))
                bad['site_rows'][site][0]['registers'][register] = True
                with pytest.raises(ValueError):
                    checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
                bad = copy.deepcopy(expected)
                bad['site_rows'][site].pop(0)
                with pytest.raises(ValueError):
                    checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
                bad = copy.deepcopy(expected)
                bad['site_rows'][site][0], bad['site_rows'][site][1] = (
                    bad['site_rows'][site][1], bad['site_rows'][site][0])
                with pytest.raises(ValueError):
                    checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
            bad = copy.deepcopy(expected)
            bad['site_rows']['final_entry'][0]['entry_anchor'] = (
                'original16' if case == 'existing_main_stub_entry' else 'existing_main_stub8')
            with pytest.raises(ValueError):
                checks.assert_shutter_gate_trace_v1(raw, declaration, bad)
            bad = copy.deepcopy(expected)
            bad['discriminator_expected'] = False
            with pytest.raises(ValueError):
                checks.assert_shutter_gate_trace_v1(raw, declaration, bad)

    commands = {item['directory']: item for item in result['commands']}
    assert len(commands) == 13  # Three compiles, eight guest runs, two independent refusals.
    for case in fixture.API_CASES:
        pair = [commands[f'cases/{case}-{mode}'] for mode in ('baseline', 'plugin')]
        for command in pair:
            argv = command['command']
            assert '--unshare-all' in argv and '--clearenv' in argv and argv.count('--bind') == 1
            assert argv[argv.index('-smp') + 1] == 'cpus=1,maxcpus=1'
            assert argv[argv.index('-accel') + 1] == (
                'tcg,thread=single,one-insn-per-tb=on' if case == 'short_tb' else 'tcg,thread=single')
            assert command['returncode'] == 0 and command['outer_timeout'] is False
            assert command['owned_pid_unreaped'] is None
            assert not {'-drive', '-blockdev', '-qmp', '-gdb', '-qtest', '-usb', '-S'} & set(argv)
        assert pair[1]['payload_argv'] == pair[0]['payload_argv'] + ['-plugin', '/observer.so,log=/out/plugin.log']
    for name, negative in result['startup_negatives'].items():
        assert 1 <= negative['returncode'] < 124 and negative['guest_started'] is False
        assert negative['normal_non_timeout_rejection'] is True
        assert commands['cases/' + name]['outer_timeout'] is False
    assert fixture.read_small(output / 'cases/existing_log/plugin.log') == b'exclusive-shutter-gate-log-sentinel\n'
    assert not (output / 'cases/missing_log_argument/plugin.log').exists()

    assert fixture.read_small(output / 'manifest.json') == (
        json.dumps(result, indent=2, sort_keys=True) + '\n').encode('utf-8')
    all_files = {str(path.relative_to(output)) for path in output.rglob('*') if path.is_file()}
    assert all_files == set(result['artifacts']) | {'manifest.json'}
    for relative, item in result['artifacts'].items():
        path = output / relative
        assert not path.is_symlink() and path.resolve() == path
        assert fixture.sha256(path) == item['sha256'] and path.stat().st_size == item['bytes']
