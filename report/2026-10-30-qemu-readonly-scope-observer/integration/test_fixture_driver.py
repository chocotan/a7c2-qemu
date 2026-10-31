# SPDX-License-Identifier: MIT
"""NOT_RUN standard-library regression sources for the parent's unified collector.

Import is inert. The layout test compiles five self-owned variants only when the
parent executes it. In-memory unit vectors below are not actualAPI receipts.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("readonly_scope_fixture_driver", Path(__file__).with_name("run_fixture.py"))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def model_producer_console(mutated=False):
    """In-memory unit vectors only; never write console/trace/receipt artifacts."""
    boot = fixture.BASE + 0x80000
    word = 0x94000000 | ((fixture.PRODUCER_ENTRY - boot) // 4)
    sections = {name: (0, b'unit-own-code') for name in fixture.CODE_SECTIONS}
    sections['.boot'] = (boot, struct.pack('<II', word, 0xD503201F))
    anchor = bytearray(fixture.PRODUCER_ANCHOR)
    if mutated:
        anchor[5] = 0x70
    sections['.producer'] = (fixture.PRODUCER_ENTRY, bytes(anchor))
    lr = boot + 4
    context = (0x900003C5, 0x1111222233334444, 0x5555666677778888)
    chunks = [fixture.PRODUCER_HEADER]
    for number in range(1, 18):
        if number == 2:
            chunks.append(b''.join(fixture.expected_record(n, lane, False)
                                   for n in range(1, 18) for lane in (0, 2, 1)))
        chunks += [struct.pack('<54Q', *fixture.producer_registers(number, lr, mutated, after), *context)
                   for after in (False, True)]
        chunks += [fixture.STORE_SEED, fixture.producer_stores(number, mutated)]
    chunks += [fixture.RECORDS_MARKER,
               b''.join(sections[name][1] for name in (*fixture.CODE_SECTIONS, '.producer')),
               fixture.PRODUCER_TRAILER]
    return b''.join(chunks), sections


def model_v2_assets(directory):
    """HOST_TEST fake files only; never a build receipt or an actualAPI invocation."""
    directory = Path(directory).resolve()
    source = directory / 'native/report/2026-10-30-qemu-readonly-scope-observer/integration'
    source.mkdir(parents=True)
    for name in set(fixture.RUNTIME_SOURCES) | fixture.FIXTURE_SOURCE_NAMES:
        path = source.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('HOST_TEST fake source ' + name + '\n').encode('ascii'))
    schema = source.parent / 'log-schema-v2.json'
    schema.write_text(json.dumps({'schema': fixture.SCHEMA, 'profile': fixture.PROFILE}), encoding='ascii')
    contract = source.parent / 'source-contract-v2.json'
    contract.write_text(json.dumps({'schema': 'readonly_scope_source_contract_v2', 'profile': fixture.PROFILE,
        'trace_schema': fixture.SCHEMA, 'v2_schema_sha256': fixture.sha256(schema)}), encoding='ascii')
    header = source.parent.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header.parent.mkdir(parents=True)
    header.write_bytes(b'#define QEMU_PLUGIN_VERSION 7\n')
    qemu, plugin = directory / 'qemu', directory / 'observer.so'
    qemu.write_bytes(b'HOST_TEST never executed QEMU')
    plugin.write_bytes(b'HOST_TEST never loaded plugin')
    audit = directory / 'readonly-import-audit.json'
    audit.write_bytes(b'HOST_TEST fake audit bytes')
    receipt = directory / 'build-receipt.json'
    build = {'schema': fixture.PROFILE, 'trace_schema': fixture.SCHEMA,
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
    def test_snapshot_keeps_full_x23_and_defined_stack_spills(self):
        words = struct.unpack("<51Q", fixture.expected_record(1, 0, False))
        self.assertEqual(words[23], 0x1122334455667701)
        self.assertNotEqual(words[23], words[23] & 0xFFFFFFFF)
        self.assertEqual(words[29], 0x292A2B2C2D2E2F30)
        self.assertEqual(words[30], 0x4209EE80)
        self.assertEqual(words[31:33], (0x40200000, 0xA0000000))
        stack = words[33:]
        self.assertEqual(stack[2:4], (0x292A2B2C2D2E2F30, 0x4209EE80))
        self.assertEqual(stack[8:10], (0x1122334455667701, 0x2425262728292A2B))
        for index in (0, 1, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17):
            self.assertEqual(stack[index], 0x6677889900000000 + index)

    def test_other_lr_interleaves_without_reducing_each_input_lane(self):
        sections = {name: (0, b"own-code") for name in fixture.CODE_SECTIONS}
        console = fixture.expected_console(sections, False, False)
        records = console[len(fixture.HEADER):len(fixture.HEADER) + 408 * 51]
        lrs = [struct.unpack_from("<Q", records, offset + 240)[0] for offset in range(0, len(records), 408)]
        self.assertEqual(lrs[:3], [0x4209EE80, 0x4209EEA4, 0x4209EE88])
        self.assertEqual([lrs.count(lr) for lr in fixture.LRS], [17, 17, 17])
        self.assertTrue(console.endswith(b"SCOPE_FIXTURE_OK calls=51 lanes=17,17,17\n"))

    def test_signature_mutation_changes_only_defined_x1_effect_in_snapshot(self):
        original = fixture.expected_record(17, 1, False)
        mutated = fixture.expected_record(17, 1, True)
        changed = [index for index, pair in enumerate(zip(original, mutated)) if pair[0] != pair[1]]
        self.assertEqual(changed, [8])
        self.assertEqual(struct.unpack_from("<Q", mutated, 8)[0], 0x488385F9)

    def test_code_and_snapshot_mismatch_are_failures(self):
        with self.assertRaisesRegex(fixture.FixtureError, "byte 0x1"):
            fixture.require_bytes(b"ab", b"ac", "own program readback")
        with self.assertRaisesRegex(fixture.FixtureError, "truncated ELF"):
            fixture.elf_layout(b"\x7fELF", False)
        self.assertEqual(fixture.branch_target(0x97FFFFFF, 0x1000, 0x25), 0xFFC)
        with self.assertRaises(fixture.FixtureError):
            fixture.branch_target(0xD503201F, 0x1000, 0x25)

    def test_vm_command_has_only_explicit_plugin_and_isolated_baremetal_devices(self):
        baseline = fixture.vm_command(None)
        observed = fixture.vm_command(["log=/out/plugin.log"])
        self.assertNotIn("-plugin", baseline)
        self.assertEqual(observed[-2:], ["-plugin", "/observer.so,log=/out/plugin.log"])
        self.assertEqual(observed[observed.index("-smp") + 1], "cpus=1,maxcpus=1")
        self.assertEqual(observed[observed.index("-nic") + 1], "none")
        self.assertEqual(observed[observed.index("-cpu") + 1], "cortex-a35")
        self.assertFalse(set(observed) & {"-drive", "-blockdev", "-qmp", "-qtest", "-gdb", "-S"})
        self.assertEqual(baseline[baseline.index('-accel') + 1], 'tcg,thread=single')
        self.assertEqual(observed[observed.index('-accel') + 1], 'tcg,thread=single')
        for arguments in (None, ['log=/out/plugin.log']):
            with self.subTest(plugin=arguments is not None):
                producer = fixture.vm_command(arguments, producer=True, short_tb=True)
                self.assertEqual(producer[producer.index('-m') + 1], '128M')
                self.assertEqual(producer[producer.index('-accel') + 1],
                                 'tcg,thread=single,one-insn-per-tb=on')
                self.assertEqual(producer.count('-accel'), 1)
                self.assertNotIn('-one-insn-per-tb', producer)
                producer[producer.index('-accel') + 1] = 'tcg,thread=single'
                self.assertEqual(producer, fixture.vm_command(arguments, producer=True))

    def test_output_is_exclusive_and_scoped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary, plugin = root / "qemu", root / "observer.so"
            binary.write_bytes(b"not executed")
            binary.chmod(0o700)
            plugin.write_bytes(b"not loaded")
            with mock.patch.object(fixture, "private_root", return_value=root):
                self.assertEqual(fixture.validate_paths(binary, plugin, root / "new")[2], root / "new")
                for invalid in (root, root.parent / "outside"):
                    with self.assertRaises(fixture.FixtureError):
                        fixture.validate_paths(binary, plugin, invalid)
                (root / "existing").mkdir()
                with self.assertRaisesRegex(fixture.FixtureError, "reuse"):
                    fixture.validate_paths(binary, plugin, root / "existing")
                with self.assertRaisesRegex(fixture.FixtureError, "plugin"):
                    fixture.validate_paths(binary, root / "absent.so", root / "new")

    def test_timeout_only_terms_owned_popen_and_retains_returncode(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = mock.Mock(pid=12345)
            process.wait.side_effect = [subprocess.TimeoutExpired("owned", 40), 0]
            process.poll.side_effect = [None, 0]
            commands = []
            with mock.patch.object(fixture, "tool", side_effect=lambda name: f"/usr/bin/{name}"), \
                 mock.patch.object(fixture.subprocess, "Popen", return_value=process) as popen:
                with self.assertRaises(subprocess.TimeoutExpired):
                    fixture.launch(Path(temporary), "owned", ["/qemu"], [], commands, 30)
            process.send_signal.assert_called_once_with(signal.SIGTERM)
            self.assertEqual(commands[0]["returncode"], 0)
            self.assertIsNone(commands[0]["owned_pid_unreaped"])
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            argv = popen.call_args.args[0]
            self.assertIn("--unshare-all", argv)
            self.assertIn("--clearenv", argv)
            self.assertIn("--signal=TERM", argv)
            self.assertNotIn("--kill-after", argv)
            self.assertNotIn("SIGKILL", argv)


    def test_producer_preserves_raw64_values_and_only_the_original_defined_effects(self):
        lr = 0x1234567840081004  # Unit width sentinel, not an actually mapped caller.
        before = fixture.producer_registers(1, lr, False, False)
        after = fixture.producer_registers(1, lr, False, True)
        other = fixture.producer_registers(2, lr, False, False)
        self.assertNotEqual(before[0] >> 32, 0)
        self.assertNotEqual(before[0] & 0xFFFFFFFF, other[0] & 0xFFFFFFFF)
        self.assertEqual(before[30], lr)
        self.assertEqual(before[30] >> 32, 0x12345678)
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], [1])
        self.assertEqual(after[1] + 0x2F0, fixture.BASE + 0x7E6A7C8)
        self.assertEqual(after[1] + 0x2F8, fixture.BASE + 0x7E6A7D0)
        expected = bytearray(fixture.STORE_SEED)
        struct.pack_into('<I', expected, 8, 0xDEAD0001)
        struct.pack_into('<I', expected, 16, 0xDEAD0001)
        self.assertEqual(fixture.producer_stores(1, False), expected)

    def test_producer_expectations_bind_actual_boundaries_and_keep_early_rows_raw(self):
        console, sections = model_producer_console()
        rows, metadata = fixture.check_producer_console(console, sections, False)
        self.assertEqual(len(rows), 32)
        self.assertEqual(len(metadata['calls']), 17)
        entry, pre = rows['entry', 1], rows['pre_M_store', 1]
        self.assertEqual((entry['scope_anchor_seen'], pre['scope_anchor_seen']), (0, 0))
        self.assertEqual(rows['entry', 2]['scope_anchor_seen'], 1)
        self.assertEqual(entry['proposed_u32'], 'unknown')
        self.assertNotIn('x1_raw', entry)
        self.assertNotIn('gdb_pc_raw', entry)  # Lazy PC must not replace actual operand validation.
        self.assertEqual(entry['event_pc'], fixture.PRODUCER_ENTRY)
        self.assertEqual(pre['event_pc'], fixture.PRODUCER_ENTRY + 12)
        self.assertEqual(pre['x1_raw'], fixture.PRODUCER_X1)
        self.assertEqual(pre['x0_raw'], entry['x0_raw'])
        self.assertEqual(pre['proposed_u32'], 0xDEAD0001)
        self.assertEqual(pre['caller_raw'], entry['x30_raw'])
        self.assertEqual(pre['context_mode'], 'other_aarch64')
        self.assertEqual(pre['cpsr_raw'], 0x900003C5)
        self.assertEqual(pre['optional_raw']['ttbr0_el1'], 0x1111222233334444)
        self.assertEqual(rows['pre_M_store', 16]['producer_sequence'], 32)
        self.assertNotIn(('entry', 17), rows)
        self.assertNotIn(('pre_M_store', 17), rows)
        self.assertEqual(metadata['calls'][-1]['round'], 17)
        self.assertEqual(metadata['calls'][0]['before_console_offset'], len(fixture.PRODUCER_HEADER))

    def test_wrong_actual_operands_context_store_guard_or_code_fail(self):
        console, sections = model_producer_console()
        header = len(fixture.PRODUCER_HEADER)
        corruptions = ((header, 'pre-call'), (header + 432 + 8, 'post-call'),
                       (header + 432 + 416, 'context'), (header + 896 + 16, 'result dump'),
                       (len(console) - len(fixture.PRODUCER_TRAILER) - 1, 'whole-code'))
        for offset, diagnostic in corruptions:
            with self.subTest(offset=offset):
                changed = bytearray(console)
                changed[offset] ^= 1
                with self.assertRaisesRegex(fixture.FixtureError, diagnostic):
                    fixture.check_producer_console(bytes(changed), sections, False)
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated'):
            fixture.check_producer_console(console[:header + 32], sections, False)

    def test_corrupt_candidate_and_short_tb_have_no_success_expectations(self):
        for mutated, short_tb in ((True, False), (False, True)):
            console, sections = model_producer_console(mutated)
            rows, metadata = fixture.check_producer_console(console, sections, mutated, short_tb)
            self.assertEqual(rows, {})
            self.assertEqual(len(metadata['calls']), 17)

    def test_v2_execution_requires_explicit_schema_and_receipt(self):
        with self.assertRaisesRegex(TypeError, 'schema'):
            fixture.run_fixture(Path('/unit/qemu'), Path('/unit/observer.so'), Path('/unit/new'))

    def test_scope_expectations_use_all_actual_dump_registers_and_interleaved_offset(self):
        console, _ = model_producer_console()
        expected = fixture.scope_expectations(console, producer=True)
        self.assertEqual(len(expected), 32)
        self.assertEqual(expected[0, 1]['x23'], 0x1122334455667701)
        self.assertEqual(expected[1, 16]['nzcv'], 0x60000000)
        self.assertEqual(expected[0, 1]['cpsr_m'], 5)
        self.assertEqual(expected[0, 1]['context_mode'], 'other_aarch64')
        changed = bytearray(console)
        offset = len(fixture.PRODUCER_HEADER) + fixture.PRODUCER_FRAME_BYTES
        struct.pack_into('<Q', changed, offset + 23 * 8, 0xABCDEF0100000007)
        self.assertEqual(fixture.scope_expectations(bytes(changed), producer=True)[0, 1]['x23'], 0xABCDEF0100000007)
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated'):
            fixture.scope_expectations(b'')

    def test_exact9_runtime_and_separate_frozen_fixture_maps_bind_actual_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, qemu, plugin, schema, receipt, frozen = model_v2_assets(temporary)
            with mock.patch.object(fixture, 'SOURCE', source):
                inputs = fixture.validate_v2_assets(qemu, plugin, schema, receipt, fixture_source_sha256=frozen)
            self.assertEqual(sum(name.startswith('source:') for name in inputs), 9)
            self.assertEqual(sum(name.startswith('fixture-source:') for name in inputs), len(fixture.FIXTURE_SOURCES))
            self.assertIn('qemu_header', inputs)
            self.assertIn('readonly_import_audit', inputs)
            self.assertNotIn('source:integration/fixture.S', inputs)
            self.assertIn('fixture-source:integration/fixture.S', inputs)
            self.assertEqual(json.loads(receipt.read_bytes())['source_sha256'].keys(), set(fixture.RUNTIME_SOURCES))

    def test_v2_receipt_rejects_alias_missing_old_profile_and_wrong_runtime_closure(self):
        for change in ('old_profile', 'old_trace_schema', 'bool_api', 'old_digest', 'missing_digest',
                       'schema_alias_only', 'log_schema_alias_only', 'extra_schema_alias', 'extra_log_schema_alias',
                       'source_contract', 'library', 'header', 'audit', 'capture', 'physical', 'runtime',
                       'missing_source', 'extra_fixture_source'):
            with tempfile.TemporaryDirectory() as temporary:
                source, qemu, plugin, schema, receipt, frozen = model_v2_assets(temporary)
                build = json.loads(receipt.read_bytes())
                if change == 'old_profile':
                    build['schema'] = 'qemu-readonly-scope-v1'
                elif change == 'old_trace_schema':
                    build['trace_schema'] = 'readonly_scope_v1'
                elif change == 'bool_api':
                    build['plugin_api'] = True
                elif change == 'old_digest':
                    build['trace_schema_sha256'] = fixture.V1_SCHEMA_SHA256
                elif change == 'missing_digest':
                    del build['trace_schema_sha256']
                elif change.endswith('alias_only'):
                    name = 'schema_sha256' if change == 'schema_alias_only' else 'log_schema_sha256'
                    build[name] = build.pop('trace_schema_sha256')
                elif change.startswith('extra_') and change.endswith('alias'):
                    name = 'schema_sha256' if change == 'extra_schema_alias' else 'log_schema_sha256'
                    build[name] = build['trace_schema_sha256']
                elif change == 'missing_source':
                    del build['source_sha256']['check_run_context.py']
                elif change == 'extra_fixture_source':
                    build['source_sha256']['integration/fixture.S'] = frozen['integration/fixture.S']
                elif change in ('capture', 'physical', 'runtime'):
                    key = {'capture': 'capture_verified', 'physical': 'physical_asic_compatibility_verified',
                           'runtime': 'runtime_verified'}[change]
                    build[key] = True
                else:
                    key = {'source_contract': 'source_contract_sha256', 'library': 'library_sha256',
                           'header': 'qemu_header_sha256', 'audit': 'readonly_import_audit_sha256'}[change]
                    build[key] = 'f' * 64
                receipt.write_text(json.dumps(build), encoding='ascii')
                with self.subTest(change=change), mock.patch.object(fixture, 'SOURCE', source), \
                     self.assertRaises(fixture.FixtureError):
                    fixture.validate_v2_assets(qemu, plugin, schema, receipt, fixture_source_sha256=frozen)

    def test_fixture_map_requires_parent_pins_and_rejects_path_or_content_drift(self):
        for change in ('missing', 'extra', 'unreviewed', 'source_drift', 'source_symlink', 'source_oversize'):
            with tempfile.TemporaryDirectory() as temporary:
                source, qemu, plugin, schema, receipt, frozen = model_v2_assets(temporary)
                original = source / 'fixture.S'
                if change == 'missing':
                    del frozen['integration/fixture.S']
                elif change == 'extra':
                    frozen['integration/../fixture.S'] = 'f' * 64
                elif change == 'unreviewed':
                    frozen['integration/fixture.S'] = 'f' * 64
                elif change == 'source_drift':
                    original.write_bytes(b'HOST_TEST changed after freeze')
                elif change == 'source_symlink':
                    other = source.parent / 'other-source'
                    original.rename(other)
                    original.symlink_to(other)
                else:
                    original.write_bytes(b'x' * (fixture.LIMIT + 1))
                with self.subTest(change=change), mock.patch.object(fixture, 'SOURCE', source), \
                     self.assertRaises(fixture.FixtureError):
                    fixture.validate_v2_assets(qemu, plugin, schema, receipt, fixture_source_sha256=frozen)

    def test_fixture_original_and_compiler_snapshot_are_rechecked_independently(self):
        for drift in ('original', 'copy'):
            with tempfile.TemporaryDirectory() as temporary:
                source, _, _, _, _, frozen = model_v2_assets(temporary)
                output = Path(temporary).resolve() / 'output'
                copies = output / 'inputs'
                copies.mkdir(parents=True)
                for name in fixture.FIXTURE_SOURCES:
                    (copies / name).write_bytes((source / name).read_bytes())
                with mock.patch.object(fixture, 'SOURCE', source):
                    snapshots = fixture.verify_fixture_snapshots(output, frozen)
                    self.assertEqual(set(snapshots), set(frozen))
                    self.assertTrue(all(item['sha256'] == frozen[name] for name, item in snapshots.items()))
                    target = (source if drift == 'original' else copies) / 'fixture.S'
                    target.write_bytes(b'HOST_TEST changed after staging')
                    with self.subTest(drift=drift), self.assertRaisesRegex(fixture.FixtureError, 'snapshot changed'):
                        fixture.verify_fixture_snapshots(output, frozen)

    def test_fixture_pins_are_a_required_execution_parameter(self):
        with self.assertRaisesRegex(TypeError, 'fixture_source_sha256'):
            fixture.run_fixture(Path('/unit/qemu'), Path('/unit/observer.so'), Path('/unit/new'),
                                schema=Path('/unit/log-schema-v2.json'), receipt=Path('/unit/receipt.json'))


if __name__ == "__main__":
    unittest.main()
