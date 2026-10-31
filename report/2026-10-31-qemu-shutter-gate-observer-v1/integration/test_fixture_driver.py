# SPDX-License-Identifier: MIT
"""SOURCE_ONLY / NOT_RUN driver regressions for the parent's unified batch.

All fabricated bytes below are HOST_TEST vectors. No test vector is an actual
API7 observation, guest execution, source freeze, or successful build receipt.
The peer-owned direct reader is deliberately not imported by this unit module.
"""
import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('shutter_gate_v1_driver_unit', Path(__file__).with_name('run_fixture.py'))
fixture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture)


def host_console(case):
    """HOST_TEST model and deliberate corruption input; never saved as evidence."""
    sections = {name: (0, ('HOST_TEST ' + name).encode('ascii')) for name in fixture.CODE_SECTIONS}
    chunks = [fixture.HEADER]
    for number in range(fixture.ROUNDS):
        for phase in range(4):
            chunks.append(struct.pack('<51Q', *fixture.boundary_words(number, phase, case)))
    chunks += [fixture.RECORDS_MARKER,
               b''.join(sections[name][1] for name in fixture.CODE_SECTIONS), fixture.TRAILER]
    return b''.join(chunks), sections


def host_parsed(expected, metadata):
    """HOST_TEST counter vector; deliberately not a producer trace or receipt."""
    rows = []
    end = {'candidate_found': hex(int(expected['discriminator_expected'])), 'ambiguous': '0x0',
           'faults': '0x0', 'candidate_base': hex(fixture.BASE if expected['discriminator_expected'] else 0)}
    for index, site in enumerate(fixture.SITES):
        count = min(16, len(expected['site_rows'][site]))
        rows.extend({'kind': 'shutter_gate', 'site': site} for _ in range(count))
        callbacks = metadata['executed_site_counts'][site]
        if expected['case'] == 'short_tb' or (expected['case'] == 'one_byte_gate_mutation' and index == 1):
            callbacks = 0
        end[f'site{index}_records'] = hex(count)
        end[f'site{index}_suppressed'] = hex(expected['minimum_suppressed'][site])
        end[f'site{index}_unbound_callbacks'] = hex(0 if expected['discriminator_expected'] else callbacks)
    end['gate_sequence'] = hex(len(rows))
    return {'rows': rows, 'raw_ledger': [], 'begin': {}, 'end': end}


def host_assets(directory):
    """HOST_TEST fake binaries never executed; fixed digest constants are patched locally."""
    project = Path(directory).resolve()
    source = project / fixture.COMPONENT_RELATIVE / 'integration'
    source.mkdir(parents=True)
    for name in set(fixture.RUNTIME_SOURCES) | fixture.FIXTURE_SOURCE_NAMES:
        path = source.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('HOST_TEST ' + name + '\n').encode('ascii'))
    schema = source.parent / fixture.SCHEMA_FILE
    schema.write_text(json.dumps({'schema': fixture.SCHEMA, 'profile': fixture.PROFILE}), encoding='ascii')
    contract_path = source.parent / fixture.CONTRACT_FILE
    contract = {'schema': fixture.CONTRACT_SCHEMA, 'profile': fixture.PROFILE, 'trace_schema': fixture.SCHEMA,
        'trace_schema_sha256': fixture.sha256(schema), 'actual_build_source_names_required': list(fixture.RUNTIME_SOURCES),
        'actual_fixture_source_names_required': ['integration/' + name for name in fixture.FIXTURE_SOURCES],
        'actualAPI_cases': list(fixture.API_CASES), 'actualAPI_environment_names': list(fixture.API_ENV)}
    contract_path.write_text(json.dumps(contract), encoding='ascii')
    header = source.parent.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header.parent.mkdir(parents=True)
    header.write_bytes(b'#define QEMU_PLUGIN_VERSION 7\n')
    qemu, plugin = project / 'host-test-qemu', project / 'host-test-observer.so'
    qemu.write_bytes(b'HOST_TEST never executed')
    qemu.chmod(0o700)
    plugin.write_bytes(b'HOST_TEST never loaded')
    audit = project / 'readonly-import-audit.json'
    imported = '\n'.join(' U ' + name for name in sorted(fixture.QEMU_IMPORTS))
    exported = '\n'.join('0000 T ' + name for name in sorted(fixture.QEMU_IMPORTS))
    audit_data = {
        'imports': {'command': ['nm', '-D', '--undefined-only', str(plugin)], 'returncode': 0,
                    'stdout': imported, 'stderr': ''},
        'exports': {'command': ['nm', '-D', '--defined-only', str(qemu)], 'returncode': 0,
                    'stdout': exported, 'stderr': ''},
        'needed': {'command': ['readelf', '-d', str(plugin)], 'returncode': 0,
                   'stdout': ' (NEEDED) Shared library: [libglib-2.0.so.0]\n', 'stderr': ''},
        'qemu_plugin_imports': sorted(fixture.QEMU_IMPORTS),
        'ordinary_imports': [], 'dt_needed': ['libglib-2.0.so.0']}
    audit.write_text(json.dumps(audit_data), encoding='ascii')
    frozen = {name: fixture.sha256(source.parent / name) for name in fixture.FIXTURE_SOURCE_NAMES}
    receipt = project / 'build-receipt.json'
    build = {'schema': fixture.PROFILE, 'plugin_api': 7, 'trace_schema': fixture.SCHEMA,
        'trace_schema_sha256': fixture.sha256(schema), 'source_contract_sha256': fixture.sha256(contract_path),
        'qemu': str(qemu), 'qemu_sha256': fixture.sha256(qemu), 'library': str(plugin),
        'library_sha256': fixture.sha256(plugin), 'qemu_header_sha256': fixture.sha256(header),
        'source_sha256': {name: fixture.sha256(source.parent / name) for name in fixture.RUNTIME_SOURCES},
        'fixture_source_sha256': frozen, 'readonly_imports_verified': True,
        'readonly_import_audit_sha256': fixture.sha256(audit), 'runtime_verified': False,
        'capture_verified': False, 'physical_asic_compatibility_verified': False}
    receipt.write_text(json.dumps(build), encoding='ascii')
    return project, source, qemu, plugin, schema, receipt, frozen, header


def host_elf_with_empty_default_text():
    """HOST_TEST ELF only: no compiler, VM or retained failed artifact is needed."""
    def branch(pc, target):
        return struct.pack('<I', 0x14000000 | (((target - pc) // 4) & 0x03FFFFFF))
    boot = fixture.BASE + 0x80000
    boot_image = bytearray(0x3800)
    boot_image[:4] = bytes.fromhex('1f2003d5')
    struct.pack_into('<512Q', boot_image, 0x1000, 0, fixture.MMU_L2 + 3, *([0] * 510))
    struct.pack_into('<512Q', boot_image, 0x2000,
                     *(fixture.BASE + index * 0x200000 + 0x701 for index in range(32)), *([0] * 480))
    for index in range(16):
        offset = 0x3000 + index * 128
        boot_image[offset:offset + 4] = branch(boot + offset, boot)
    specs = [('.boot', boot, bytes(boot_image), 5, 1, None),
        ('.replay', fixture.BASE + 0x90000, fixture.ORIGINAL16 + branch(fixture.BASE + 0x90010, fixture.ENTRY_RETURN), 5, 1, None),
        ('.resume', fixture.ENTRY_RETURN, branch(fixture.ENTRY_RETURN, boot), 5, 1, None),
        ('.fixturedata', fixture.RECORD, bytes(16), 6, 1, None),
        ('.source', fixture.SOURCE_WORD, bytes(8), 6, 1, None),
        ('.stack', fixture.STACK - 0x4000, b'', 6, 8, 0x4010),
        ('.entry', fixture.ENTRY, fixture.ORIGINAL16 + branch(fixture.ENTRY + 16, fixture.ENTRY_RETURN), 5, 1, None),
        ('.target', fixture.TARGET, fixture.TARGET8 + branch(fixture.TARGET + 8, boot), 5, 1, None),
        ('.gate', fixture.GATE - 4, fixture.GATE8 + fixture.FALLTHROUGH8 + branch(fixture.BL_RETURN, boot), 5, 1, None),
        ('.sink', fixture.BASE + 0x251DD4C, branch(fixture.BASE + 0x251DD4C, boot), 5, 1, None)]
    blob = bytearray(64 + 10 * 56)
    names, headers = bytearray(b'\0'), [(0,) * 10]
    for index, (name, address, data, flags, kind, memory) in enumerate(specs):
        offset = ((len(blob) + 4095) & ~4095) + (address & 4095)
        blob.extend(bytes(offset - len(blob)) + data)
        struct.pack_into('<IIQQQQQQ', blob, 64 + index * 56, 1, flags, offset, address,
                         address, len(data), len(data) if memory is None else memory, 4096)
        name_offset = len(names)
        names.extend(name.encode('ascii') + b'\0')
        headers.append((name_offset, kind, 6 if flags == 5 else 3, address, offset,
                        len(data) if memory is None else memory, 0, 0, 4, 0))
    text_name = len(names)
    names.extend(b'.text\0')
    text_index = len(headers)
    headers.append((text_name, 1, 6, fixture.BASE + 0x251DD50, len(blob), 0, 0, 0, 4, 0))
    string_name = len(names)
    names.extend(b'.shstrtab\0')
    strings_offset = len(blob)
    blob.extend(names)
    headers.append((string_name, 3, 0, 0, strings_offset, len(names), 0, 0, 1, 0))
    blob.extend(bytes((-len(blob)) % 8))
    table_offset = len(blob)
    for row in headers:
        blob.extend(struct.pack('<IIQQQQIIQQ', *row))
    struct.pack_into('<16sHHIQQQIHHHHHH', blob, 0, b'\x7fELF\x02\x01\x01' + bytes(9),
        2, 183, 1, boot, 64, table_offset, 0, 64, 56, 10, 64, len(headers), len(headers) - 1)
    return bytes(blob), table_offset + text_index * 64, strings_offset + text_name


class FixtureDriverTests(unittest.TestCase):
    def test_frozen_four_cases_six_envs_and_seven_source_roles(self):
        self.assertEqual(fixture.API_CASES, ('original_entry', 'existing_main_stub_entry',
                                           'one_byte_gate_mutation', 'short_tb'))
        self.assertEqual(fixture.API_ENV, tuple('A7C2_SHUTTER_GATE_V1_TEST_' + suffix for suffix in
                         ('QEMU', 'PLUGIN', 'OUTPUT', 'SCHEMA', 'RECEIPT', 'FIXTURE_SOURCES')))
        self.assertEqual(set(fixture.RUNTIME_SOURCES), {'scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
            'log-schema-shutter-gate-v1.json', 'source-contract-shutter-gate-v1.json', 'check_shutter_gate_v1.py',
            'integration/shutter_gate_trace_checks_v1.py'})
        self.assertEqual(fixture.FIXTURE_SOURCE_NAMES, {'integration/' + name for name in
            ('fixture.S', 'link.ld', 'run_fixture.py', 'test_fixture_driver.py', 'test_actual_scope_plugin.py',
             'test_shutter_gate_trace_checks_v1.py', 'shutter_gate_trace_checks_v1.py')})
        self.assertEqual(len(fixture.RUNTIME_SOURCES), 7)
        self.assertEqual(len(fixture.FIXTURE_SOURCES), 7)
        self.assertEqual(len(fixture.QEMU_IMPORTS), 11)
        self.assertEqual(fixture.QEMU_SHA256, '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4')
        self.assertEqual(fixture.HEADER_SHA256, '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9')

    def test_missing_empty_or_extra_environment_is_a_hard_error(self):
        values = {key: '/HOST_TEST/' + key for key in fixture.API_ENV}
        with mock.patch.dict(os.environ, values, clear=True):
            self.assertEqual(set(fixture.environment_paths()), set(fixture.API_ENV))
        for key in fixture.API_ENV:
            for value in (None, ''):
                changed = dict(values)
                if value is None:
                    del changed[key]
                else:
                    changed[key] = value
                with self.subTest(key=key, value=value), mock.patch.dict(os.environ, changed, clear=True), \
                     self.assertRaises(fixture.FixtureError):
                    fixture.environment_paths()
        with mock.patch.dict(os.environ, {**values, 'A7C2_SHUTTER_GATE_V1_TEST_FALLBACK': '/wrong'}, clear=True), \
             self.assertRaises(fixture.FixtureError):
            fixture.environment_paths()

    def test_positive_baseline_has_warmup_full64_operands_both_paths_and_exact_quota(self):
        for case in fixture.API_CASES[:2]:
            console, sections = host_console(case)
            expected, metadata = fixture.check_console(console, sections, case)
            self.assertTrue(expected['discriminator_expected'])
            self.assertEqual([len(expected['site_rows'][site]) for site in fixture.SITES], [40, 41, 21, 20])
            self.assertEqual(list(expected['minimum_suppressed'].values()), [24, 25, 5, 4])
            gate = expected['site_rows']['d570_cbnz_pre']
            self.assertEqual([row['registers']['x0'] for row in gate[:9]], [1, 0, 1, 0, 0xFFFFFFFF, 0, 0x80000000, 0, 1])
            self.assertEqual(gate[0]['cpsr'], 0xA00003C5)
            entry = expected['site_rows']['final_entry'][0]
            self.assertEqual(entry['registers']['x1'], 0x1122334400000001)
            self.assertEqual(entry['registers']['x2'], 0x2233445566770001)
            self.assertEqual(entry['registers']['x3'], 0x3344556677880001)
            self.assertEqual(entry['sp'], fixture.STACK)
            self.assertEqual(gate[0]['sp'], fixture.STACK - 80)
            self.assertEqual(entry['ttbr0_el1'], fixture.TTBR)
            self.assertEqual(entry['tpidr_el0'], fixture.TPIDR)
            self.assertEqual(entry['entry_anchor'], 'existing_main_stub8' if case.endswith('stub_entry') else 'original16')
            internal = expected['site_rows']['successor_1724_pre'][0]
            self.assertEqual(internal['registers']['x19'], 0x191A1B1C1D1E0000)
            self.assertEqual(internal['registers']['x0'], 1)
            self.assertEqual(metadata['executed_site_counts'], dict(zip(fixture.SITES, (40, 41, 21, 20))))
            counters = fixture.check_trace_counters(host_parsed(expected, metadata), expected, metadata)
            self.assertEqual(sum(item['records'] for item in counters.values()), 64)
            self.assertEqual(sum(item['total_callbacks'] for item in counters.values()), 122)
            self.assertFalse(metadata['lr_high32_actual_coverage'])
            self.assertFalse(metadata['injected_api_fault_actual_coverage'])

    def test_negative_cases_keep_guest_baselines_but_do_not_invent_bound_rows(self):
        for case in fixture.API_CASES[2:]:
            console, sections = host_console(case)
            expected, metadata = fixture.check_console(console, sections, case)
            self.assertFalse(expected['discriminator_expected'])
            self.assertEqual(expected['site_rows'], {site: [] for site in fixture.SITES})
            counters = fixture.check_trace_counters(host_parsed(expected, metadata), expected, metadata)
            self.assertTrue(all(item['records'] == item['suppressed'] == 0 for item in counters.values()))
            if case == 'one_byte_gate_mutation':
                self.assertEqual(metadata['executed_site_counts'], dict(zip(fixture.SITES, (40, 41, 40, 1))))
                self.assertEqual([item['unbound_callbacks'] for item in counters.values()], [40, 0, 40, 1])
            else:
                self.assertTrue(all(item['total_callbacks'] == 0 for item in counters.values()))

    def test_whole_dump_mutations_reject_gprs_mode_tokens_source_stack_and_code(self):
        console, sections = host_console('original_entry')
        start = len(fixture.HEADER)
        offsets = [start + phase * fixture.RECORD_BYTES + index * 8 for phase in range(4)
                   for index in (0, 1, 2, 3, 19, 22, 23, 29, 30, 31, 32, 33, 34, 35, 36, 37, 50)]
        offsets += [len(console) - len(fixture.TRAILER) - 1]
        for offset in offsets:
            bad = bytearray(console)
            bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(fixture.FixtureError):
                fixture.check_console(bytes(bad), sections, 'original_entry')
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated'):
            fixture.check_console(console[:start + 30], sections, 'original_entry')
        # Data has to pass baseline checking before it can become an operand expectation.
        bad = bytearray(console)
        struct.pack_into('<Q', bad, start + fixture.RECORD_BYTES * 2, 0x1234000040102000)
        with self.assertRaises(fixture.FixtureError):
            fixture.check_console(bytes(bad), sections, 'original_entry')

    def test_stack_guards_and_original_prefix_and_successor_effects(self):
        before = fixture.boundary_words(1, 0, 'original_entry')
        after = fixture.boundary_words(1, 1, 'original_entry')
        self.assertEqual(after[29], fixture.STACK - 80)
        self.assertEqual(after[22], 1)
        self.assertEqual(after[37 + 2:37 + 4], before[29:31])
        self.assertEqual(after[37 + 6:37 + 8], before[21:23])
        for index in (0, 1, 4, 5, 8, 9, 10, 11, 12, 13):
            self.assertEqual(after[37 + index], before[37 + index])
        warm = fixture.boundary_words(0, 1, 'original_entry')
        self.assertEqual(warm[37:], tuple(0x6677889900000000 + i for i in range(14)))
        zero = fixture.boundary_words(1, 3, 'original_entry')
        nonzero = fixture.boundary_words(2, 3, 'original_entry')
        self.assertEqual(zero[0], 0x191A1B1C1D1E0001)
        self.assertEqual(zero[30], fixture.BL_RETURN)
        self.assertEqual(nonzero[0], fixture.STACK - 8)
        self.assertEqual(nonzero[19], fixture.STACK - 8)
        self.assertEqual(nonzero[30], fixture.ENTRY_RETURN)

    def test_no_pc_only_or_quota_only_counting_acceptance(self):
        console, sections = host_console('original_entry')
        expected, metadata = fixture.check_console(console, sections, 'original_entry')
        parsed = host_parsed(expected, metadata)
        for key in ('site0_records', 'site1_suppressed', 'site2_unbound_callbacks', 'gate_sequence', 'candidate_base'):
            bad = copy.deepcopy(parsed)
            bad['end'][key] = hex(int(bad['end'][key], 16) + 1)
            with self.subTest(key=key), self.assertRaises(fixture.FixtureError):
                fixture.check_trace_counters(bad, expected, metadata)
        parsed['rows'].append({'kind': 'fault'})
        with self.assertRaisesRegex(fixture.FixtureError, 'fault'):
            fixture.check_trace_counters(parsed, expected, metadata)

    def test_only_empty_default_text_is_allowed_and_still_requires_its_LOAD_mapping(self):
        raw, header, name = host_elf_with_empty_default_text()
        sections = fixture.elf_layout(raw, 'original_entry')
        self.assertEqual(sections['.text'], (fixture.BASE + 0x251DD50, b''))
        for mutation in ('nonempty', 'unknown_name', 'write_flags', 'nobits_type', 'outside_LOAD'):
            changed = bytearray(raw)
            if mutation == 'nonempty': struct.pack_into('<Q', changed, header + 32, 1)
            elif mutation == 'unknown_name': changed[name:name + 5] = b'.junk'
            elif mutation == 'write_flags': struct.pack_into('<Q', changed, header + 8, 7)
            elif mutation == 'nobits_type': struct.pack_into('<I', changed, header + 4, 8)
            else: struct.pack_into('<Q', changed, header + 16, fixture.BASE + 0x251DD51)
            with self.subTest(mutation=mutation), self.assertRaises(fixture.FixtureError):
                fixture.elf_layout(bytes(changed), 'original_entry')

    def test_private_normal_memory_tables_and_exception_vectors_are_closed_to_64MiB(self):
        raw, _, _ = host_elf_with_empty_default_text()
        fixture.elf_layout(raw, 'original_entry')
        boot_offset = struct.unpack_from('<IIQQQQQQ', raw, 64)[2]
        self.assertEqual(fixture.TTBR, (1 << 48) | fixture.MMU_L1)
        for mutation in ('L1_pointer', 'AF', 'Device_index', 'first_block', 'outside_64MiB', 'vector_target', 'vector_padding'):
            changed = bytearray(raw)
            if mutation == 'L1_pointer': struct.pack_into('<Q', changed, boot_offset + 0x1008, fixture.MMU_L2 + 0x1003)
            elif mutation == 'AF': struct.pack_into('<Q', changed, boot_offset + 0x2000, fixture.BASE + 0x301)
            elif mutation == 'Device_index': struct.pack_into('<Q', changed, boot_offset + 0x2000, fixture.BASE + 0x705)
            elif mutation == 'first_block': struct.pack_into('<Q', changed, boot_offset + 0x2000, fixture.BASE + 0x200000 + 0x701)
            elif mutation == 'outside_64MiB': struct.pack_into('<Q', changed, boot_offset + 0x2100, fixture.BASE + 0x4000000 + 0x701)
            elif mutation == 'vector_target': struct.pack_into('<I', changed, boot_offset + 0x3000, 0x17FFFFFF)
            else: changed[boot_offset + 0x3004] = 1
            with self.subTest(mutation=mutation), self.assertRaises(fixture.FixtureError):
                fixture.elf_layout(bytes(changed), 'original_entry')

    def test_elf_refuses_truncation_unknown_cases_and_wrong_branch(self):
        with self.assertRaisesRegex(fixture.FixtureError, 'truncated ELF'):
            fixture.elf_layout(b'\x7fELF', 'original_entry')
        with self.assertRaisesRegex(fixture.FixtureError, 'unknown'):
            fixture.elf_layout(b'\x7fELF', 'legacy')
        with self.assertRaises(fixture.FixtureError):
            fixture.branch_target(0xD503201F, 0x1000, 5)
        self.assertEqual(fixture.branch_target(0x97FFFFFF, 0x1000, 0x25), 0xFFC)
        self.assertEqual(fixture.branch_target(0x9428B144, fixture.FALLTHROUGH + 4, 0x25), fixture.BASE + 0x251DD4C)
        changed = bytearray(fixture.GATE8)
        changed[4] ^= 1
        self.assertEqual([i for i, pair in enumerate(zip(fixture.GATE8, changed)) if pair[0] != pair[1]], [4])
        self.assertEqual(int.from_bytes(changed[4:], 'little') & 31, 1)

    def test_vm_commands_keep_same_guest_and_single_cpu_tcg_no_external_devices(self):
        for short_tb in (False, True):
            baseline = fixture.vm_command(None, short_tb)
            observed = fixture.vm_command(['log=/out/plugin.log'], short_tb)
            self.assertEqual(observed, baseline + ['-plugin', '/observer.so,log=/out/plugin.log'])
            self.assertEqual(baseline[baseline.index('-smp') + 1], 'cpus=1,maxcpus=1')
            self.assertEqual(baseline[baseline.index('-m') + 1], '64M')
            self.assertEqual(baseline[baseline.index('-accel') + 1],
                             'tcg,thread=single' + (',one-insn-per-tb=on' if short_tb else ''))
            for key in ('-display', '-serial', '-monitor', '-nic'):
                self.assertEqual(baseline[baseline.index(key) + 1], 'none')
            self.assertFalse(set(baseline) & {'-qmp', '-gdb', '-qtest', '-drive', '-blockdev', '-usb', '-S'})
            self.assertNotIn('-one-insn-per-tb', baseline)
            self.assertNotIn('socket', ' '.join(baseline))

    def test_sandbox_has_exactly_one_persistent_writable_mount(self):
        with mock.patch.object(fixture, 'tool', side_effect=lambda name: '/usr/bin/' + name):
            argv = fixture.sandbox(Path('/HOST_TEST/owned'), [(Path('/HOST_TEST/qemu'), '/qemu')])
        self.assertEqual(argv.count('--bind'), 1)
        self.assertEqual(argv[argv.index('--bind') + 1:argv.index('--bind') + 3], ['/HOST_TEST/owned', '/out'])
        self.assertEqual(argv.count('--ro-bind'), 2)
        self.assertTrue({'--unshare-all', '--clearenv', '--cap-drop', '--new-session', '--die-with-parent'} <= set(argv))
        self.assertNotIn('--share-net', argv)
        self.assertNotIn('--dev-bind', argv)

    def test_launch_records_exact_owned_argv_raw_return_sentinel_and_timeout_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            process = mock.Mock(pid=54321)
            process.wait.return_value = 1
            commands = []
            with mock.patch.object(fixture, 'tool', side_effect=lambda name: '/usr/bin/' + name), \
                 mock.patch.object(fixture.subprocess, 'Popen', return_value=process) as popen:
                result = fixture.launch(Path(temporary), 'refused', ['/qemu'], [], commands, 30,
                                        existing_log=b'HOST_TEST sentinel\n')
            self.assertEqual(result['returncode'], 1)
            self.assertEqual(commands[0]['command'], popen.call_args.args[0])
            self.assertEqual(commands[0]['payload_argv'], ['/qemu'])
            self.assertEqual((Path(temporary) / 'refused/plugin.log').read_bytes(), b'HOST_TEST sentinel\n')
            self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertIn('--signal=TERM', result['command'])
            self.assertNotIn('--kill-after', result['command'])
            with self.assertRaises(FileExistsError):
                fixture.launch(Path(temporary), 'refused', ['/qemu'], [], commands, 30)
        with tempfile.TemporaryDirectory() as temporary:
            process = mock.Mock(pid=54321)
            process.wait.side_effect = [subprocess.TimeoutExpired('owned', 40), 0]
            process.poll.side_effect = [None, 0]
            commands = []
            with mock.patch.object(fixture, 'tool', side_effect=lambda name: '/usr/bin/' + name), \
                 mock.patch.object(fixture.subprocess, 'Popen', return_value=process), \
                 self.assertRaises(subprocess.TimeoutExpired):
                fixture.launch(Path(temporary), 'timeout', ['/qemu'], [], commands, 30)
            process.send_signal.assert_called_once_with(signal.SIGTERM)
            self.assertTrue(commands[0]['outer_timeout'])
            self.assertEqual(commands[0]['wait_error']['type'], 'TimeoutExpired')
            self.assertEqual(commands[0]['returncode'], 0)  # Raw return retained, timeout remains a failure.

    def test_startup_rejections_require_normal_non_timeout_and_unchanged_old_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            directory = root / 'negative'
            directory.mkdir()
            (directory / 'stderr.bin').write_bytes(b'scope_observer_host_error install rejected\n')
            sentinel = b'HOST_TEST sentinel\n'
            (directory / 'plugin.log').write_bytes(sentinel)
            result = {'returncode': 1, 'outer_timeout': False, 'owned_pid_unreaped': None}
            self.assertTrue(fixture.validate_startup_rejection(root, 'negative', result, sentinel)['sentinel_unchanged'])
            for rc in (0, -15, 124, 125, 126, 127, 137, None, True):
                with self.subTest(rc=rc), self.assertRaises(fixture.FixtureError):
                    fixture.validate_startup_rejection(root, 'negative', {**result, 'returncode': rc}, sentinel)
            (directory / 'plugin.log').write_bytes(sentinel + b'changed')
            with self.assertRaises(fixture.FixtureError):
                fixture.validate_startup_rejection(root, 'negative', result, sentinel)
            (directory / 'plugin.log').unlink()
            self.assertFalse(fixture.validate_startup_rejection(root, 'negative', result)['guest_started'])
            (directory / 'console.bin').write_bytes(b'guest started')
            with self.assertRaises(fixture.FixtureError):
                fixture.validate_startup_rejection(root, 'negative', result)

    def test_output_is_an_owned_new_canonical_private_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            qemu, plugin = root / 'qemu', root / 'plugin'
            qemu.write_bytes(b'HOST_TEST')
            qemu.chmod(0o700)
            plugin.write_bytes(b'HOST_TEST')
            with mock.patch.object(fixture, 'private_root', return_value=root):
                self.assertEqual(fixture.validate_paths(qemu, plugin, root / 'new')[2], root / 'new')
                for invalid in (root, root.parent / 'outside', Path('relative')):
                    with self.assertRaises(fixture.FixtureError):
                        fixture.validate_paths(qemu, plugin, invalid)
                existing = root / 'existing'
                existing.mkdir()
                with self.assertRaisesRegex(fixture.FixtureError, 'reuse'):
                    fixture.validate_paths(qemu, plugin, existing)
                alias = root / 'alias'
                alias.symlink_to(plugin)
                with self.assertRaises(fixture.FixtureError):
                    fixture.validate_paths(qemu, alias, root / 'new')

    def test_receipts_bind_exact_runtime7_fixture7_schema_header_and_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, source, qemu, plugin, schema, receipt, frozen, header = host_assets(temporary)
            with mock.patch.object(fixture, 'project_root', return_value=project), \
                 mock.patch.object(fixture, 'SOURCE', source), \
                 mock.patch.object(fixture, 'QEMU_SHA256', fixture.sha256(qemu)), \
                 mock.patch.object(fixture, 'HEADER_SHA256', fixture.sha256(header)):
                inputs, declaration = fixture.validate_assets(qemu, plugin, schema, receipt, frozen)
            self.assertEqual(sum(key.startswith('source:') for key in inputs), 7)
            self.assertEqual(sum(key.startswith('fixture-source:') for key in inputs), 7)
            self.assertEqual(declaration['schema'], fixture.SCHEMA)
            for item in inputs.values():
                self.assertEqual(fixture.sha256(item['path']), item['sha256'])

    def test_mixed_old_schema_aliases_bad_freezes_and_root_changes_reject(self):
        changes = ('profile', 'trace_schema', 'api_bool', 'alias', 'root_alias', 'source_missing',
                   'source_extra', 'fixture_missing', 'fixture_extra', 'fixture_build_drift', 'header',
                   'qemu', 'plugin', 'schema_digest', 'contract', 'runtime', 'capture', 'physical',
                   'contract_self_hash', 'contract_cases', 'contract_env', 'old_schema_rehash',
                   'extra_import', 'missing_import', 'missing_export', 'audit_argv', 'audit_bool_rc',
                   'qemu_derived', 'ordinary_derived', 'needed_derived', 'audit_roles',
                   'source_drift', 'source_symlink', 'source_hardlink')
        for change in changes:
            with tempfile.TemporaryDirectory() as temporary:
                project, source, qemu, plugin, schema, receipt, frozen, header = host_assets(temporary)
                build = json.loads(receipt.read_bytes())
                if change == 'profile': build['schema'] = 'qemu-readonly-scope-v3'
                elif change == 'trace_schema': build['trace_schema'] = 'readonly_scope_v1'
                elif change == 'api_bool': build['plugin_api'] = True
                elif change == 'alias': build['schema_sha256'] = build['trace_schema_sha256']
                elif change == 'root_alias': build['source_root'] = str(source.parent)
                elif change == 'source_missing': del build['source_sha256']['build-runtime.py']
                elif change == 'source_extra': build['source_sha256']['late-sites.inc'] = 'f' * 64
                elif change == 'fixture_missing': del frozen['integration/fixture.S']
                elif change == 'fixture_extra': frozen['integration/../fixture.S'] = 'f' * 64
                elif change == 'fixture_build_drift': build['fixture_source_sha256']['integration/fixture.S'] = 'f' * 64
                elif change in ('header', 'qemu', 'plugin', 'schema_digest', 'contract'):
                    key = {'header': 'qemu_header_sha256', 'qemu': 'qemu_sha256', 'plugin': 'library_sha256',
                           'schema_digest': 'trace_schema_sha256', 'contract': 'source_contract_sha256'}[change]
                    build[key] = 'f' * 64
                elif change in ('runtime', 'capture', 'physical'):
                    build[{'runtime': 'runtime_verified', 'capture': 'capture_verified',
                           'physical': 'physical_asic_compatibility_verified'}[change]] = True
                elif change.startswith('contract_'):
                    path = source.parent / fixture.CONTRACT_FILE
                    contract = json.loads(path.read_bytes())
                    if change == 'contract_self_hash': contract['source_contract_sha256'] = 'f' * 64
                    elif change == 'contract_cases': contract['actualAPI_cases'].append('legacy')
                    else: contract['actualAPI_environment_names'].pop()
                    path.write_text(json.dumps(contract), encoding='ascii')
                    build['source_contract_sha256'] = build['source_sha256'][fixture.CONTRACT_FILE] = fixture.sha256(path)
                elif change == 'old_schema_rehash':
                    schema.write_text(json.dumps({'schema': 'readonly_scope_v1', 'profile': fixture.PROFILE}), encoding='ascii')
                    build['trace_schema_sha256'] = build['source_sha256'][fixture.SCHEMA_FILE] = fixture.sha256(schema)
                elif change in ('extra_import', 'missing_import', 'missing_export', 'audit_argv', 'audit_bool_rc',
                                'qemu_derived', 'ordinary_derived', 'needed_derived', 'audit_roles'):
                    path = receipt.with_name('readonly-import-audit.json')
                    audit = json.loads(path.read_bytes())
                    if change == 'audit_argv': audit['exports']['command'][-1] += '-different-candidate'
                    elif change == 'audit_bool_rc': audit['imports']['returncode'] = False
                    elif change == 'qemu_derived': audit['qemu_plugin_imports'].pop()
                    elif change == 'ordinary_derived': audit['ordinary_imports'] = ['invented']
                    elif change == 'needed_derived': audit['dt_needed'] = []
                    elif change == 'audit_roles': del audit['ordinary_imports']
                    else:
                        key = 'exports' if change == 'missing_export' else 'imports'
                        if change == 'extra_import': audit[key]['stdout'] += '\n U qemu_plugin_read_memory_vaddr'
                        else: audit[key]['stdout'] = audit[key]['stdout'].split('\n', 1)[1]
                    path.write_text(json.dumps(audit), encoding='ascii')
                    build['readonly_import_audit_sha256'] = fixture.sha256(path)
                elif change == 'source_drift': (source / 'fixture.S').write_bytes(b'HOST_TEST changed')
                elif change == 'source_hardlink': os.link(source / 'fixture.S', source / 'extra-link')
                else:
                    original = source / 'fixture.S'
                    other = source / 'elsewhere'
                    original.rename(other)
                    original.symlink_to(other)
                receipt.write_text(json.dumps(build), encoding='ascii')
                with self.subTest(change=change), mock.patch.object(fixture, 'project_root', return_value=project), \
                     mock.patch.object(fixture, 'SOURCE', source), \
                     mock.patch.object(fixture, 'QEMU_SHA256', fixture.sha256(qemu)), \
                     mock.patch.object(fixture, 'HEADER_SHA256', fixture.sha256(header)), \
                     self.assertRaises(fixture.FixtureError):
                    fixture.validate_assets(qemu, plugin, schema, receipt, frozen)

    def test_source_snapshots_are_separately_rechecked_and_reader_is_lazy(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, source, _, _, _, _, frozen, _ = host_assets(temporary)
            output = project / 'output'
            (output / 'inputs').mkdir(parents=True)
            for name in fixture.FIXTURE_SOURCES:
                (output / 'inputs' / name).write_bytes((source / name).read_bytes())
            with mock.patch.object(fixture, 'SOURCE', source):
                self.assertEqual(set(fixture.verify_fixture_snapshots(output, frozen)), fixture.FIXTURE_SOURCE_NAMES)
                (output / 'inputs/fixture.S').write_bytes(b'HOST_TEST changed after copy')
                with self.assertRaisesRegex(fixture.FixtureError, 'snapshot changed'):
                    fixture.verify_fixture_snapshots(output, frozen)
        # This unit module does not load a peer file that the parent has not integrated.
        self.assertNotIn('trace_checks', fixture.__dict__)
        run_source = inspect.getsource(fixture.run_fixture)
        self.assertIn('checks.assert_shutter_gate_trace_v1(raw_log, declaration, expected)', run_source)
        self.assertIn('checks.parse_trace(raw_log, declaration)', run_source)
        self.assertNotIn('assert_scope_trace', run_source)
        self.assertNotIn('readonly_scope_v', run_source)
        self.assertIn("expected_operands", run_source)

    def test_failure_retains_real_argv_raw_bytes_and_a_failed_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            project, source, qemu, plugin, schema, receipt, frozen, _ = host_assets(temporary)
            pinfile = project / 'parent-fixture7.json'
            pinfile.write_text(json.dumps(frozen), encoding='ascii')
            output = project / 'failed'
            with mock.patch.object(fixture, 'validate_paths', return_value=(qemu, plugin, output)), \
                 mock.patch.object(fixture, 'validate_assets', side_effect=fixture.FixtureError('HOST_TEST refusal')), \
                 mock.patch.object(fixture.subprocess, 'Popen') as popen, \
                 self.assertRaisesRegex(fixture.FixtureError, 'refusal'):
                fixture.run_fixture(qemu, plugin, output, schema=schema, receipt=receipt,
                    fixture_source_sha256=frozen, fixture_sources_file=pinfile)
            popen.assert_not_called()
            manifest = json.loads((output / 'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'FAILED')
            self.assertEqual(manifest['commands'], [])
            self.assertEqual(manifest['failure']['message'], 'HOST_TEST refusal')
            self.assertFalse(manifest['capture_verified'])
            self.assertFalse(manifest['physical'])
            self.assertEqual((output / 'inputs/explicit-schema.json').read_bytes(), schema.read_bytes())
            self.assertEqual((output / 'inputs/explicit-receipt.json').read_bytes(), receipt.read_bytes())
            for name, item in manifest['artifacts'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), item['sha256'])

    def test_duplicate_json_keys_and_bool_operands_are_rejected(self):
        with self.assertRaisesRegex(fixture.FixtureError, 'duplicate'):
            fixture.object_json(b'{"schema":1,"schema":2}')
        for token in ('NaN', 'Infinity', '-Infinity', '1e999', '-1e999'):
            raw = ('{"unused_extra":{"nested":[{"number":' + token + '}]}}').encode('ascii')
            with self.subTest(token=token), self.assertRaisesRegex(fixture.FixtureError, 'nonfinite JSON'):
                fixture.object_json(raw)
        with self.assertRaises(fixture.FixtureError):
            fixture.boundary_words(True, 0, 'original_entry')


if __name__ == '__main__':
    unittest.main()
