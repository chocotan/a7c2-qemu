# SPDX-License-Identifier: MIT
"""NOT_RUN driver regressions; the parent executes this entire cohort together.

HOST_TEST vectors below never constitute API7 evidence. Only the separate actual
entry runs the seven cases; all source maps here are temporary unit fixtures.
"""
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('readonly_scope_v3_fixture_driver', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def model_producer_console(mutated=False, reverse=False):
    """HOST_TEST console model, never an actual guest dump or saved receipt."""
    boot = fixture.BASE + 0x80000
    branches = [0x94000000 | ((entry - (boot + 4 * writer)) // 4)
                for writer, entry in enumerate((fixture.PRODUCER_ENTRY, fixture.PRODUCER2_ENTRY))]
    sections = {name: (0, b'HOST_TEST own code') for name in fixture.CODE_SECTIONS}
    sections['.boot'] = (boot, struct.pack('<III', *branches, 0xD503201F))
    sections['.producer'] = (fixture.PRODUCER_ENTRY, fixture.PRODUCER_ANCHOR)
    second = bytearray(fixture.PRODUCER2_ANCHOR)
    if mutated:
        second[5] = 0x70
    sections['.producer2'] = (fixture.PRODUCER2_ENTRY, bytes(second))
    callers = fixture.producer_callers(sections)
    context = (0x900003C5, 0x1111222233334444, 0x5555666677778888)
    chunks = [fixture.PRODUCER_HEADER]
    for number in range(1, 18):
        if number == 2:
            chunks.append(b''.join(fixture.expected_record(n, lane, False)
                                   for n in range(1, 18) for lane in (0, 2, 1)))
        for writer in ((1, 0) if reverse else (0, 1)):
            lr = callers[writer][1]
            chunks += [struct.pack('<54Q', *fixture.producer_registers(number, writer, lr, mutated, after), *context)
                       for after in (False, True)]
            chunks += [fixture.STORE_SEED, fixture.producer_stores(number, writer, mutated)]
    chunks += [fixture.RECORDS_MARKER,
               b''.join(sections[name][1] for name in (*fixture.CODE_SECTIONS, '.producer', '.producer2')),
               fixture.PRODUCER_TRAILER]
    return b''.join(chunks), sections


def model_v3_assets(directory):
    """HOST_TEST ordinary input files only; their fake binaries are never run."""
    directory = Path(directory).resolve()
    source = directory / fixture.PACKAGE_COMPONENT / 'report' / fixture.COMPONENT / 'integration'
    source.mkdir(parents=True)
    for name in set(fixture.RUNTIME_SOURCES) | fixture.FIXTURE_SOURCE_NAMES:
        path = source.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('HOST_TEST source ' + name + '\n').encode('ascii'))
    schema = source.parent / 'log-schema-v3.json'
    schema.write_text(json.dumps({'schema': fixture.SCHEMA, 'profile': fixture.PROFILE}), encoding='ascii')
    contract = source.parent / 'source-contract-v3.json'
    contract.write_text(json.dumps({'schema': 'readonly_scope_source_contract_v3', 'profile': fixture.PROFILE,
        'trace_schema': fixture.SCHEMA, 'trace_schema_sha256': fixture.sha256(schema)}), encoding='ascii')
    header = source.parent.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header.parent.mkdir(parents=True)
    header.write_bytes(b'#define QEMU_PLUGIN_VERSION 7\n')
    qemu, plugin = directory / 'qemu', directory / 'observer.so'
    qemu.write_bytes(b'HOST_TEST never executed QEMU')
    plugin.write_bytes(b'HOST_TEST never loaded plugin')
    audit = directory / 'readonly-import-audit.json'
    audit.write_bytes(b'HOST_TEST import audit')
    receipt = directory / 'build-receipt.json'
    build = {'schema': fixture.PROFILE, 'trace_schema': fixture.SCHEMA, 'source_root': str(source.parent),
        'trace_schema_sha256': fixture.sha256(schema), 'source_contract_sha256': fixture.sha256(contract),
        'plugin_api': 7, 'readonly_imports_verified': True, 'readonly_import_audit_sha256': fixture.sha256(audit),
        'qemu': str(qemu), 'qemu_sha256': fixture.sha256(qemu), 'library': str(plugin),
        'library_sha256': fixture.sha256(plugin), 'qemu_header_sha256': fixture.sha256(header),
        'runtime_verified': False, 'capture_verified': False, 'physical_asic_compatibility_verified': False,
        'source_sha256': {name: fixture.sha256(source.parent / name) for name in fixture.RUNTIME_SOURCES}}
    receipt.write_text(json.dumps(build), encoding='ascii')
    frozen = {name: fixture.sha256(source.parent / name) for name in fixture.FIXTURE_SOURCE_NAMES}
    return source, qemu, plugin, schema, receipt, frozen


class DriverDraftTests(unittest.TestCase):
    def test_exact_seven_cases_six_environments_and_independent_roles(self):
        self.assertEqual(fixture.API_CASES, ('anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
            'producer_reverse_order', 'producer_corrupt', 'producer_short_tb'))
        self.assertEqual(fixture.API_ENV, tuple('A7C2_SCOPE_V3_TEST_' + suffix for suffix in
            ('QEMU', 'PLUGIN', 'OUTPUT', 'SCHEMA', 'RECEIPT', 'FIXTURE_SOURCES')))
        self.assertEqual(len(set(fixture.RUNTIME_SOURCES)), 9)
        self.assertEqual(len(set(fixture.FIXTURE_SOURCES)), 8)
        self.assertEqual(set(fixture.RUNTIME_SOURCES), {'scope-observer.c', 'late-sites.inc', 'build-plugin.sh',
            'log-schema-v3.json', 'source-contract-v3.json', 'check_run_context_v3.py', 'check_run_context.py',
            'integration/scope_trace_checks_v3.py', 'integration/scope_trace_checks.py'})
        self.assertEqual(fixture.FIXTURE_SOURCE_NAMES, {'integration/' + name for name in
            ('fixture.S', 'link.ld', 'run_fixture.py', 'test_fixture_driver.py', 'test_actual_scope_plugin.py',
             'scope_trace_checks.py', 'test_scope_trace_checks.py', 'scope_trace_checks_v3.py')})
        self.assertNotIn('integration/fixture.S', fixture.RUNTIME_SOURCES)
        self.assertEqual(fixture.trace_checks.__file__, str(fixture.SOURCE / 'scope_trace_checks.py'))

    def test_scope_snapshots_keep_full_gprs_sp_flags_and_stack_guards(self):
        words = struct.unpack('<51Q', fixture.expected_record(1, 0, False))
        self.assertEqual(words[23], 0x1122334455667701)
        self.assertEqual(words[30:33], (0x4209EE80, 0x40200000, 0xA0000000))
        stack = words[33:]
        self.assertEqual(stack[2:4], (0x292A2B2C2D2E2F30, 0x4209EE80))
        self.assertEqual(stack[8:10], (0x1122334455667701, 0x2425262728292A2B))
        for index in (0, 1, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17):
            self.assertEqual(stack[index], 0x6677889900000000 + index)
        sections = {name: (0, b'HOST_TEST code') for name in fixture.CODE_SECTIONS}
        console = fixture.expected_console(sections, False, False)
        records = console[len(fixture.HEADER):len(fixture.HEADER) + 408 * 51]
        lrs = [struct.unpack_from('<Q', records, offset + 240)[0] for offset in range(0, len(records), 408)]
        self.assertEqual(lrs[:3], [fixture.LRS[index] for index in (0, 2, 1)])
        self.assertEqual([lrs.count(lr) for lr in fixture.LRS], [17, 17, 17])
        mutated = fixture.expected_record(1, 0, True)
        self.assertEqual([i for i, pair in enumerate(zip(fixture.expected_record(1, 0, False), mutated))
                          if pair[0] != pair[1]], [8])

    def test_code_snapshot_and_branch_failures_are_hard_errors(self):
        with self.assertRaisesRegex(fixture.FixtureError, 'byte 0x1'):
            fixture.require_bytes(b'ab', b'ac', 'code')
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated ELF'):
            fixture.elf_layout(b'\x7fELF', False)
        self.assertEqual(fixture.branch_target(0x97FFFFFF, 0x1000, 0x25), 0xFFC)
        with self.assertRaises(fixture.FixtureError):
            fixture.branch_target(0xD503201F, 0x1000, 0x25)

    def test_vm_argv_pair_128m_single_vcpu_and_accel_short_tb_property(self):
        for short_tb in (False, True):
            pair = [fixture.vm_command(args, producer=True, short_tb=short_tb)
                    for args in (None, ['log=/out/plugin.log'])]
            self.assertEqual(pair[1], pair[0] + ['-plugin', '/observer.so,log=/out/plugin.log'])
            for argv in pair:
                self.assertEqual(argv[argv.index('-m') + 1], '128M')
                self.assertEqual(argv[argv.index('-smp') + 1], 'cpus=1,maxcpus=1')
                self.assertEqual(argv[argv.index('-accel') + 1],
                    'tcg,thread=single' + (',one-insn-per-tb=on' if short_tb else ''))
                self.assertEqual(argv.count('-accel'), 1)
                self.assertNotIn('-one-insn-per-tb', argv)
                self.assertEqual(argv[argv.index('-cpu') + 1], 'cortex-a35')
                for name in ('-nic', '-serial', '-monitor', '-display'):
                    self.assertEqual(argv[argv.index(name) + 1], 'none')
                self.assertFalse(set(argv) & {'-drive', '-blockdev', '-qmp', '-qtest', '-gdb', '-S', '-usb'})
                self.assertIn('file,id=semi,path=/out/console.bin', argv)
                self.assertNotIn('socket', ' '.join(argv))
        self.assertEqual(fixture.vm_command(None)[fixture.vm_command(None).index('-m') + 1], '64M')

    def test_readonly_sandbox_has_only_one_persistent_writable_mount(self):
        with mock.patch.object(fixture, 'tool', side_effect=lambda name: '/usr/bin/' + name):
            argv = fixture.sandbox(Path('/unit/owned'), [(Path('/unit/qemu'), '/qemu'),
                (Path('/unit/plugin'), '/observer.so'), (Path('/unit/fixture.elf'), '/in/fixture.elf')])
        for option in ('--unshare-all', '--die-with-parent', '--new-session', '--clearenv'):
            self.assertIn(option, argv)
        self.assertEqual(argv[argv.index('--cap-drop') + 1], 'ALL')
        self.assertEqual(argv.count('--bind'), 1)
        self.assertEqual(argv[argv.index('--bind') + 1:argv.index('--bind') + 3], ['/unit/owned', '/out'])
        self.assertEqual(argv.count('--ro-bind'), 4)
        self.assertNotIn('--share-net', argv)
        self.assertNotIn('--dev-bind', argv)
        self.assertIn('--tmpfs', argv)

    def test_launch_preserves_exclusive_sentinel_and_records_exact_owned_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = mock.Mock(pid=12345)
            process.wait.return_value = 1
            commands = []
            with mock.patch.object(fixture, 'tool', side_effect=lambda name: '/usr/bin/' + name), \
                 mock.patch.object(fixture.subprocess, 'Popen', return_value=process) as popen:
                result = fixture.launch(Path(temporary), 'negative', ['/qemu'], [], commands, 30,
                                        existing_log=b'exclusive-log-sentinel\n')
            self.assertEqual(result['returncode'], 1)
            self.assertEqual((Path(temporary) / 'negative/plugin.log').read_bytes(), b'exclusive-log-sentinel\n')
            self.assertEqual(commands[0]['command'], popen.call_args.args[0])
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertIn('--signal=TERM', commands[0]['command'])
            self.assertNotIn('--kill-after', commands[0]['command'])
            with self.assertRaises(FileExistsError):
                fixture.launch(Path(temporary), 'negative', ['/qemu'], [], commands, 30)

    def test_timeout_only_terms_owned_popen_and_keeps_original_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = mock.Mock(pid=12345)
            process.wait.side_effect = [subprocess.TimeoutExpired('owned', 40), 0]
            process.poll.side_effect = [None, 0]
            commands = []
            with mock.patch.object(fixture, 'tool', side_effect=lambda name: '/usr/bin/' + name), \
                 mock.patch.object(fixture.subprocess, 'Popen', return_value=process):
                with self.assertRaises(subprocess.TimeoutExpired):
                    fixture.launch(Path(temporary), 'owned', ['/qemu'], [], commands, 30)
            process.send_signal.assert_called_once_with(signal.SIGTERM)
            self.assertEqual(commands[0]['returncode'], 0)
            self.assertIsNone(commands[0]['owned_pid_unreaped'])

    def test_output_path_is_new_private_child_with_no_symlink_or_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            binary, plugin = root / 'qemu', root / 'observer.so'
            binary.write_bytes(b'HOST_TEST not executed')
            binary.chmod(0o700)
            plugin.write_bytes(b'HOST_TEST not loaded')
            with mock.patch.object(fixture, 'private_root', return_value=root):
                self.assertEqual(fixture.validate_paths(binary, plugin, root / 'new')[2], root / 'new')
                for invalid in (root, root.parent / 'outside'):
                    with self.assertRaises(fixture.FixtureError):
                        fixture.validate_paths(binary, plugin, invalid)
                (root / 'existing').mkdir()
                with self.assertRaisesRegex(fixture.FixtureError, 'reuse'):
                    fixture.validate_paths(binary, plugin, root / 'existing')
                alias = root / 'alias'
                alias.symlink_to(plugin)
                with self.assertRaises(fixture.FixtureError):
                    fixture.validate_paths(binary, alias, root / 'new')

    def test_both_writer_orders_keep_actual_full64_inputs_lr_modes_and_quota(self):
        for reverse in (False, True):
            console, sections = model_producer_console(reverse=reverse)
            rows, metadata = fixture.check_producer_console(console, sections, False, reverse=reverse)
            self.assertEqual(len(rows), 48)
            self.assertEqual(len(metadata['calls']), 34)
            self.assertEqual([call['writer'] for call in metadata['calls'][:2]], [1, 0] if reverse else [0, 1])
            self.assertEqual(sum(row['scope_anchor_seen'] == 0 for row in rows.values()), 3)
            for site in ('entry', 'pre_M_store', 'second_entry'):
                selected = [rows[site, ordinal] for ordinal in range(1, 17)]
                self.assertEqual([row['raw_input_u32'] for row in selected],
                                 [value & 0xFFFFFFFF for value in fixture.PRODUCER_INPUTS[:16]])
                self.assertTrue(all(row['x0_raw'] >> 32 for row in selected))
                self.assertNotIn((site, 17), rows)
                self.assertEqual(selected[0]['scope_anchor_seen'], 0)
                self.assertEqual(selected[1]['scope_anchor_seen'], 1)
                self.assertEqual(selected[0]['cpsr_raw'], 0x900003C5)
                self.assertEqual(selected[0]['context_mode'], 'other_aarch64')
                self.assertEqual(selected[0]['optional_raw']['ttbr0_el1'], 0x1111222233334444)
                self.assertNotIn('gdb_pc_raw', selected[0])
            self.assertEqual(sorted(row['producer_sequence'] for row in rows.values()), list(range(1, 49)))
            self.assertEqual(rows['second_entry', 1]['event_pc'], fixture.PRODUCER2_ENTRY)
            self.assertEqual(rows['second_entry', 1]['proposed_u32'], 'unknown')
            self.assertNotIn('x1_raw', rows['second_entry', 1])
            self.assertEqual(rows['pre_M_store', 1]['x1_raw'], fixture.PRODUCER_X1)
            self.assertEqual(rows['pre_M_store', 1]['effective_destination_raw'], fixture.BASE + 0x7E6A7C8)
            self.assertEqual(metadata['calls'][-1]['round'], 17)
            self.assertFalse(metadata['low_va_actual_lr_high32_verified'])
            self.assertEqual({row['raw_input_u32'] for row in rows.values()} & {0, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF},
                             {0, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF})

    def test_actual_boundaries_admit_original_x1_and_store_changes_only(self):
        for writer in (0, 1):
            before = fixture.producer_registers(2, writer, 0x40081004, False, False)
            after = fixture.producer_registers(2, writer, 0x40081004, False, True)
            self.assertEqual([i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]], [1])
            expected = bytearray(fixture.STORE_SEED)
            struct.pack_into('<I', expected, 8, 0xFFFFFFFF)
            struct.pack_into('<I', expected, 16, 0xFFFFFFFF)
            self.assertEqual(fixture.producer_stores(2, writer, False), expected)
        self.assertEqual(hashlib.sha256(fixture.PRODUCER2_ANCHOR).hexdigest(), fixture.PRODUCER2_SHA256)

    def test_corrupt_second_is_silent_without_hiding_exact_first_writer(self):
        console, sections = model_producer_console(mutated=True)
        rows, metadata = fixture.check_producer_console(console, sections, True)
        self.assertEqual(len(rows), 32)
        self.assertEqual({site for site, _ in rows}, {'entry', 'pre_M_store'})
        self.assertEqual(sum(row['scope_anchor_seen'] == 0 for row in rows.values()), 2)
        self.assertEqual(len(metadata['calls']), 34)
        self.assertEqual(metadata['calls'][1]['post_call_x1_raw'], f'{fixture.PRODUCER_X1 + 4:#018x}')
        self.assertEqual([i for i, pair in enumerate(zip(fixture.PRODUCER2_ANCHOR, sections['.producer2'][1]))
                          if pair[0] != pair[1]], [5])
        console, sections = model_producer_console()
        rows, metadata = fixture.check_producer_console(console, sections, False, short_tb=True)
        self.assertEqual(rows, {})
        self.assertEqual(len(metadata['calls']), 34)

    def test_corrupt_actual_operands_context_stack_guards_or_code_fail(self):
        console, sections = model_producer_console()
        header = len(fixture.PRODUCER_HEADER)
        offsets = (header, header + 30 * 8, header + 33 * 8,
                   header + 432 + 8, header + 432 + 416, header + 896 + 16,
                   header + fixture.PRODUCER_FRAME_BYTES,
                   len(console) - len(fixture.PRODUCER_TRAILER) - 1)
        for offset in offsets:
            changed = bytearray(console)
            changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(fixture.FixtureError):
                fixture.check_producer_console(bytes(changed), sections, False)
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated'):
            fixture.check_producer_console(console[:header + 32], sections, False)

    def test_scope_expectations_use_independent_actual_dumps_after_two_early_frames(self):
        console, _ = model_producer_console()
        expected = fixture.scope_expectations(console, producer=True)
        self.assertEqual(len(expected), 32)
        self.assertEqual(expected[0, 1]['x23'], 0x1122334455667701)
        self.assertEqual(expected[1, 16]['nzcv'], 0x60000000)
        self.assertEqual(expected[0, 1]['cpsr_m'], 5)
        changed = bytearray(console)
        offset = len(fixture.PRODUCER_HEADER) + 2 * fixture.PRODUCER_FRAME_BYTES
        struct.pack_into('<Q', changed, offset + 23 * 8, 0xABCDEF0100000007)
        self.assertEqual(fixture.scope_expectations(bytes(changed), producer=True)[0, 1]['x23'], 0xABCDEF0100000007)
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated'):
            fixture.scope_expectations(b'')

    def test_direct_v3_reader_is_required_and_legacy_export_remains_separate(self):
        checks = fixture.load_v3_checks()
        self.assertEqual(checks.assert_scope_trace_v3.__name__, 'assert_scope_trace_v3')
        self.assertEqual(tuple(inspect.signature(checks.assert_scope_trace_v3).parameters),
                         ('raw_log', 'expected_entries', 'candidate_base', 'other_lr',
                          'expected_producers', 'producer_base', 'producer2_base'))
        self.assertEqual(tuple(inspect.signature(checks.parse_trace).parameters), ('raw_log', 'declaration'))
        source = inspect.getsource(fixture.run_fixture)
        self.assertIn('checks.assert_scope_trace_v3(', source)
        self.assertIn('scope_expectations(baseline_console', source)
        self.assertIn('producer2_base=BASE if producer and not short_tb and not producer2_mutated else None', source)
        self.assertNotIn('assert_scope_trace_v2', source)
        self.assertNotIn('readonly_scope_v2', source)
        self.assertNotEqual(checks.__file__, fixture.trace_checks.__file__)

    def test_runtime9_fixture8_bind_actual_canonical_files_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, qemu, plugin, schema, receipt, frozen = model_v3_assets(temporary)
            with mock.patch.object(fixture, 'SOURCE', source):
                inputs = fixture.validate_v3_assets(qemu, plugin, schema, receipt, fixture_source_sha256=frozen)
            self.assertEqual(sum(name.startswith('source:') for name in inputs), 9)
            self.assertEqual(sum(name.startswith('fixture-source:') for name in inputs), 8)
            self.assertIn('qemu_header', inputs)
            self.assertIn('readonly_import_audit', inputs)
            self.assertNotIn('source:integration/fixture.S', inputs)
            for item in inputs.values():
                self.assertEqual(Path(item['path']).resolve(), Path(item['path']))
                self.assertEqual(fixture.sha256(item['path']), item['sha256'])

    def test_rejects_unknown_profiles_wrong_roots_aliases_and_bad_runtime_receipts(self):
        changes = ('old_profile', 'unknown_profile', 'old_trace_schema', 'bool_api', 'missing_digest',
                   'schema_alias_only', 'log_schema_alias_only', 'v3_alias_only', 'extra_schema_alias',
                   'source_contract', 'library', 'header', 'audit', 'capture', 'physical', 'runtime',
                   'missing_source', 'extra_fixture_source', 'source_root', 'schema_root', 'actual_root')
        for change in changes:
            with tempfile.TemporaryDirectory() as temporary:
                source, qemu, plugin, schema, receipt, frozen = model_v3_assets(temporary)
                build = json.loads(receipt.read_bytes())
                if change in ('old_profile', 'unknown_profile'):
                    build['schema'] = 'qemu-readonly-scope-v2' if change == 'old_profile' else 'unknown'
                elif change == 'old_trace_schema':
                    build['trace_schema'] = 'readonly_scope_v2'
                elif change == 'bool_api':
                    build['plugin_api'] = True
                elif change == 'missing_digest':
                    del build['trace_schema_sha256']
                elif change.endswith('alias_only'):
                    key = {'schema_alias_only': 'schema_sha256', 'log_schema_alias_only': 'log_schema_sha256',
                           'v3_alias_only': 'v3_schema_sha256'}[change]
                    build[key] = build.pop('trace_schema_sha256')
                elif change == 'extra_schema_alias':
                    build['schema_sha256'] = build['trace_schema_sha256']
                elif change == 'missing_source':
                    del build['source_sha256']['check_run_context.py']
                elif change == 'extra_fixture_source':
                    build['source_sha256']['integration/fixture.S'] = frozen['integration/fixture.S']
                elif change in ('capture', 'physical', 'runtime'):
                    build[{'capture': 'capture_verified', 'physical': 'physical_asic_compatibility_verified',
                           'runtime': 'runtime_verified'}[change]] = True
                elif change == 'source_root':
                    build['source_root'] = str(source.parent.parent / '2026-10-30-qemu-readonly-scope-observer')
                elif change == 'schema_root':
                    copied = Path(temporary).resolve() / schema.name
                    copied.write_bytes(schema.read_bytes())
                    schema = copied
                elif change == 'actual_root':
                    wrong = source.parent.parent / '2026-10-30-qemu-readonly-scope-observer'
                    source.parent.rename(wrong)
                    source = wrong / 'integration'
                else:
                    build[{'source_contract': 'source_contract_sha256', 'library': 'library_sha256',
                           'header': 'qemu_header_sha256', 'audit': 'readonly_import_audit_sha256'}[change]] = 'f' * 64
                receipt.write_text(json.dumps(build), encoding='ascii')
                with self.subTest(change=change), mock.patch.object(fixture, 'SOURCE', source), \
                     self.assertRaises(fixture.FixtureError):
                    fixture.validate_v3_assets(qemu, plugin, schema, receipt, fixture_source_sha256=frozen)

    def test_fixture_pins_require_parent_map_and_reject_path_or_content_drift(self):
        for change in ('missing', 'extra', 'unreviewed', 'source_drift', 'source_symlink', 'source_oversize'):
            with tempfile.TemporaryDirectory() as temporary:
                source, qemu, plugin, schema, receipt, frozen = model_v3_assets(temporary)
                original = source / 'fixture.S'
                if change == 'missing':
                    del frozen['integration/fixture.S']
                elif change == 'extra':
                    frozen['integration/../fixture.S'] = 'f' * 64
                elif change == 'unreviewed':
                    frozen['integration/fixture.S'] = 'f' * 64
                elif change == 'source_drift':
                    original.write_bytes(b'HOST_TEST changed')
                elif change == 'source_symlink':
                    other = source.parent / 'other-source'
                    original.rename(other)
                    original.symlink_to(other)
                else:
                    original.write_bytes(b'x' * (fixture.LIMIT + 1))
                with self.subTest(change=change), mock.patch.object(fixture, 'SOURCE', source), \
                     self.assertRaises(fixture.FixtureError):
                    fixture.validate_v3_assets(qemu, plugin, schema, receipt, fixture_source_sha256=frozen)

    def test_fixture_original_and_compiler_snapshot_rechecked_independently(self):
        for drift in ('original', 'copy'):
            with tempfile.TemporaryDirectory() as temporary:
                source, _, _, _, _, frozen = model_v3_assets(temporary)
                output = Path(temporary).resolve() / 'output'
                copies = output / 'inputs'
                copies.mkdir(parents=True)
                for name in fixture.FIXTURE_SOURCES:
                    (copies / name).write_bytes((source / name).read_bytes())
                with mock.patch.object(fixture, 'SOURCE', source):
                    snapshots = fixture.verify_fixture_snapshots(output, frozen)
                    self.assertEqual(set(snapshots), set(frozen))
                    target = (source if drift == 'original' else copies) / 'fixture.S'
                    target.write_bytes(b'HOST_TEST changed after staging')
                    with self.assertRaisesRegex(fixture.FixtureError, 'snapshot changed'):
                        fixture.verify_fixture_snapshots(output, frozen)

    def test_explicit_schema_receipt_and_separate_fixture_pin_parameter_are_mandatory(self):
        with self.assertRaisesRegex(TypeError, 'schema'):
            fixture.run_fixture(Path('/unit/qemu'), Path('/unit/observer.so'), Path('/unit/new'))
        with self.assertRaisesRegex(TypeError, 'fixture_source_sha256'):
            fixture.run_fixture(Path('/unit/qemu'), Path('/unit/observer.so'), Path('/unit/new'),
                                schema=Path('/unit/log-schema-v3.json'), receipt=Path('/unit/receipt.json'))


if __name__ == '__main__':
    unittest.main()
