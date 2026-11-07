"""SOURCE_ONLY / NOT_RUN: synthetic v2 builder boundaries; no compile/plugin/QEMU."""
from pathlib import Path
import importlib.util
import json
import os
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('shutter_gate_v2_runtime_builder', Path(__file__).with_name('build-runtime.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ReadonlyImportAuditTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        here = root / 'report' / builder.COMPONENT
        here.mkdir(parents=True)
        for name in set(builder.SOURCES) | set(builder.FIXTURE_SOURCES):
            path = here / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'HOST_TEST source ' + name.encode())
        (here / builder.SCHEMA_FILE).write_text(json.dumps(dict(schema=builder.TRACE_SCHEMA, profile=builder.PROFILE)))
        contract = dict(schema='readonly_shutter_gate_source_contract_v2', profile=builder.PROFILE,
            trace_schema=builder.TRACE_SCHEMA, trace_schema_sha256=builder.sha(here / builder.SCHEMA_FILE),
            actual_build_source_names_required=list(builder.SOURCES),
            actual_fixture_source_names_required=list(builder.FIXTURE_SOURCES),
            actualAPI_cases=list(builder.API_CASES), actualAPI_environment_names=list(builder.API_ENV))
        (here / builder.CONTRACT_FILE).write_text(json.dumps(contract))
        header = here.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
        header.parent.mkdir(parents=True)
        header.write_bytes(b'#define QEMU_PLUGIN_VERSION 7\nHOST_TEST never compiled\n')
        qemu = root / 'qemu-system-aarch64'
        qemu.write_bytes(b'HOST_TEST candidate, never executed')
        audit = root / 'candidate.json'
        candidate = dict(binary=str(qemu), binary_sha256=builder.sha(qemu), missing_required_exports=[],
            protected_binaries_unchanged={'production': True, 'candidate': True},
            runtime_library_closure_verified=False, plugin_runtime_verified=False,
            capture_verified=False, physical_asic_compatibility_verified=False)
        audit.write_text(json.dumps(candidate))
        library = root / builder.SCRATCH / 'build-HOST_TEST/scope-observer.so'
        library.parent.parent.parent.mkdir(parents=True)
        return SimpleNamespace(root=root, here=here, header=header, qemu=qemu, audit=audit,
                               candidate=candidate, contract=contract, library=library, commands=[])

    def build(self, fixture, *, mutate=None, mutate_during_audit=None, imports=None, exports=None, failure=None):
        f = fixture
        elf = bytearray(32)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', elf, 16, 3, 62)
        def run(command, **kwargs):
            f.commands.append(command)
            rc = failure[1] if failure and failure[0] in command else 0
            if command[0] == 'sh':
                self.assertEqual(command, ['sh', str(f.here / 'build-plugin.sh')])
                f.library.parent.mkdir(parents=True, exist_ok=True)
                if not f.library.exists():
                    f.library.write_bytes(elf)
                if mutate:
                    mutate(f)
                output = str(f.library) + '\n'
            elif '--undefined-only' in command:
                self.assertEqual(command, ['nm', '-D', '--undefined-only', str(f.library)])
                if mutate_during_audit:
                    mutate_during_audit(f)
                surface = builder.ALLOWED_IMPORTS | {'fwrite', 'g_byte_array_set_size'} if imports is None else imports
                output = '\n'.join(' U ' + name for name in sorted(surface))
            elif '--defined-only' in command:
                self.assertEqual(command, ['nm', '-D', '--defined-only', str(f.qemu)])
                output = '\n'.join(' T ' + name for name in sorted(builder.ALLOWED_IMPORTS if exports is None else exports))
            else:
                self.assertEqual(command, ['readelf', '-d', str(f.library)])
                output = ' 0x00000001 (NEEDED) Shared library: [libc.so.6]\n 0x00000001 (NEEDED) Shared library: [libglib-2.0.so.0]\n'
            return SimpleNamespace(returncode=rc, stdout=output, stderr='HOST_TEST failure' if rc else '')
        with mock.patch.object(builder, 'HERE', f.here), \
                mock.patch.object(builder, 'QEMU_SHA256', builder.sha(f.qemu)), \
                mock.patch.object(builder, 'HEADER_SHA256', builder.sha(f.header)), \
                mock.patch.object(builder.subprocess, 'run', side_effect=run):
            return builder.build(f.audit)

    def test_receipt_computes_source7_fixture7_and_separate_qemu_and_ordinary_imports(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_shutter_gate_builder_') as directory:
            f = self.fixture(directory)
            path = self.build(f)
            receipt = json.loads(path.read_bytes())
            self.assertEqual(receipt['schema'], 'qemu-readonly-shutter-gate-v2')
            self.assertEqual(receipt['trace_schema'], 'readonly_shutter_gate_v2')
            self.assertEqual(receipt['source_sha256'], {name: builder.sha(f.here / name) for name in builder.SOURCES})
            self.assertEqual(len(receipt['source_sha256']), 7)
            self.assertIn('build-runtime.py', receipt['source_sha256'])
            self.assertEqual(receipt['fixture_source_sha256'], {name: builder.sha(f.here / name) for name in builder.FIXTURE_SOURCES})
            self.assertEqual(len(receipt['fixture_source_sha256']), 7)
            self.assertEqual(receipt['trace_schema_sha256'], builder.sha(f.here / builder.SCHEMA_FILE))
            self.assertEqual(receipt['source_contract_sha256'], builder.sha(f.here / builder.CONTRACT_FILE))
            self.assertEqual(receipt['candidate_static_audit_sha256'], builder.sha(f.audit))
            self.assertEqual(receipt['library_sha256'], builder.sha(f.library))
            command = json.loads((path.parent / 'plugin-build-command.json').read_bytes())
            self.assertEqual(command, dict(command=f.commands[0], returncode=0, stdout=str(f.library) + '\n', stderr=''))
            self.assertEqual(receipt['plugin_build_command_sha256'], builder.sha(path.parent / 'plugin-build-command.json'))
            self.assertEqual(receipt['readonly_import_audit_sha256'], builder.sha(path.parent / 'readonly-import-audit.json'))
            audit = json.loads((path.parent / 'readonly-import-audit.json').read_bytes())
            self.assertEqual(audit['qemu_plugin_imports'], sorted(builder.ALLOWED_IMPORTS))
            self.assertEqual(len(audit['qemu_plugin_imports']), 11)
            self.assertEqual(audit['ordinary_imports'], ['fwrite', 'g_byte_array_set_size'])
            self.assertEqual(audit['dt_needed'], ['libc.so.6', 'libglib-2.0.so.0'])
            self.assertEqual(len(f.commands), 4)
            self.assertFalse(builder.FORBIDDEN_ALIASES & receipt.keys())
            for flag in ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified'):
                self.assertIs(receipt[flag], False)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.parent, f.root / builder.SCRATCH)

    def test_real_builder_receipt_is_consumed_by_shared_prepare_without_running_qemu(self):
        path = Path(__file__).resolve().parents[2] / 'runtime/analysis/scope_observer_profile.py'
        spec = importlib.util.spec_from_file_location('HOST_TEST_shutter_profile', path)
        profile = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(profile)
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            receipt = self.build(f)
            output = f.root / 'run'
            output.mkdir()
            env = {profile.BUILD_ENV: str(receipt), 'MENU_FUNCTIONAL_CAMERA': 'virtual-functional-camera-v1',
                   'QEMU_SYSTEM_DIR': str(f.qemu.parent)}
            with mock.patch.object(profile, 'PUBLIC_NATIVE_ROOT', f.here.parents[1]), \
                    mock.patch.object(profile, 'V3_QEMU_SHA256', profile.sha(f.qemu)), \
                    mock.patch.object(profile, 'V3_HEADER_SHA256', profile.sha(f.header)):
                staged = profile.prepare(f.here.parents[1], env, output)
            self.assertEqual(staged['profile'], builder.PROFILE)
            self.assertEqual(staged['source_sha256'], {name: builder.sha(f.here / name) for name in builder.SOURCES})
            self.assertEqual(staged['fixture_source_sha256'], {name: builder.sha(f.here / name) for name in builder.FIXTURE_SOURCES})
            self.assertEqual(staged['library_sha256'], builder.sha(f.library))
            self.assertEqual(Path(staged['library']).read_bytes(), f.library.read_bytes())
            self.assertEqual(env[profile.CHILD_ENV[0]], staged['library'])
            self.assertIs(staged['capture_verified'], False)
            self.assertFalse(Path(staged['log']).exists())
            self.assertEqual(profile.SOURCE_SETS['qemu-readonly-scope-v1'], profile.SOURCE_NAMES)
            self.assertEqual(profile.SOURCE_SETS['qemu-readonly-scope-v2'], profile.SOURCE_NAMES_V2)
            self.assertEqual(profile.SOURCE_SETS['qemu-readonly-scope-v3'], profile.SOURCE_NAMES_V3)
            self.assertEqual(profile.SOURCE_SETS['qemu-readonly-shutter-gate-v1'],
                             profile.SOURCE_NAMES_SHUTTER_GATE_V1)
            self.assertEqual(profile.source_root(f.here.parents[1], 'qemu-readonly-shutter-gate-v1'),
                             f.here.with_name('2026-10-31-qemu-shutter-gate-observer-v1'))
            Path(staged['log']).write_bytes(b'HOST_TEST owned exit trace\n')
            process = SimpleNamespace(pid=54321, poll=lambda: 0)
            profile.record_exit(output, staged, process)
            exited = json.loads((output / 'readonly-scope-exit.json').read_bytes())
            self.assertEqual(exited['profile'], builder.PROFILE)
            self.assertEqual(exited['owned_wrapper_pid'], 54321)
            self.assertIs(type(exited['returncode']), int)
            self.assertEqual(exited['returncode'], 0)
            self.assertEqual(exited['log_sha256'], builder.sha(Path(staged['log'])))
            self.assertEqual(exited['library_sha256'], builder.sha(f.library))
            self.assertIs(exited['capture_verified'], False)
            self.assertIs(exited['physical_asic_compatibility_verified'], False)
            self.assertEqual((output / 'readonly-scope-exit.json').stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                profile.record_exit(output, staged, process)

    def test_contract_exact_names_cases_environment_and_schema_identity_are_required(self):
        mutations = [('schema', 'source-contract-shutter-gate-v2'),
            ('schema', 'readonly_shutter_gate_source_contract_v1'),
            ('schema', 'readonly_scope_source_contract_v1'), ('schema', 'readonly_scope_source_contract_v2'),
            ('profile', 'qemu-readonly-scope-v1'), ('profile', 'qemu-readonly-shutter-gate-v1'),
            ('profile', 'qemu-readonly-scope-v2'), ('trace_schema', 'readonly_scope_v1'),
            ('trace_schema', 'readonly_shutter_gate_v1'), ('trace_schema', 'readonly_scope_v2'),
            ('trace_schema_sha256', None), ('trace_schema_sha256', '0' * 64),
            ('source_contract_sha256', None),
            ('actual_build_source_names_required', list(builder.SOURCES[:-1])),
            ('actual_build_source_names_required', list(builder.SOURCES) + ['late-sites.inc']),
            ('actual_fixture_source_names_required', list(builder.FIXTURE_SOURCES[:-1])),
            ('actual_fixture_source_names_required', list(builder.FIXTURE_SOURCES) + ['integration/scope_trace_checks.py']),
            ('actualAPI_cases', list(builder.API_CASES[:-1])),
            ('actualAPI_cases', list(builder.API_CASES) + ['anchor']),
            ('actualAPI_environment_names', list(builder.API_ENV[:-1])),
            ('actualAPI_environment_names', list(builder.API_ENV) + ['A7C2_SCOPE_V3_TEST_QEMU'])]
        mutations += [(key, 'HOST_TEST forbidden alias') for key in builder.FORBIDDEN_ALIASES]
        for key, value in mutations:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                f.contract[key] = value
                (f.here / builder.CONTRACT_FILE).write_text(json.dumps(f.contract))
                with self.assertRaisesRegex(ValueError, 'Actual shutter-gate-v2 schema/source-contract'):
                    self.build(f)
                self.assertEqual(f.commands, [])
                self.assertFalse(f.library.exists())

    def test_suffix_v2_cannot_select_or_rehash_old_scope_or_gate_v1_schemas(self):
        legacy_schemas = (('readonly_scope_v1', 'log-schema-v1.json'),
                          ('readonly_scope_v2', 'log-schema-v2.json'),
                          ('readonly_shutter_gate_v1', 'log-schema-shutter-gate-v1.json'))
        for trace_schema, legacy_file in legacy_schemas:
            with self.subTest(trace_schema=trace_schema), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                schema = f.here / builder.SCHEMA_FILE
                schema.write_text(json.dumps(dict(schema=trace_schema, profile=builder.PROFILE)))
                (f.here / legacy_file).write_text(json.dumps(dict(schema=builder.TRACE_SCHEMA, profile=builder.PROFILE)))
                f.contract['trace_schema_sha256'] = builder.sha(schema)
                (f.here / builder.CONTRACT_FILE).write_text(json.dumps(f.contract))
                with self.assertRaisesRegex(ValueError, 'Actual shutter-gate-v2 schema/source-contract'):
                    self.build(f)
                self.assertEqual(f.commands, [])

    def test_missing_external_input_or_each_closure_file_hard_fails_without_compilation(self):
        for name in tuple(dict.fromkeys(builder.SOURCES + builder.FIXTURE_SOURCES)) + ('AUDIT',):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                path = f.audit if name == 'AUDIT' else f.here / name
                path.unlink()
                with self.assertRaises(OSError):
                    self.build(f)
                self.assertEqual(f.commands, [])

    def test_sources_fixtures_and_inputs_require_canonical_owned_single_link_files(self):
        for name in tuple(dict.fromkeys(builder.SOURCES + builder.FIXTURE_SOURCES)) + ('AUDIT', 'QEMU', 'HEADER'):
            for kind in ('symlink', 'hardlink', 'permissions'):
                with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                    f = self.fixture(directory)
                    path = {'AUDIT': f.audit, 'QEMU': f.qemu, 'HEADER': f.header}.get(name, f.here / name)
                    saved = f.root / 'saved-source'
                    if kind == 'symlink':
                        path.rename(saved)
                        path.symlink_to(saved)
                    elif kind == 'hardlink':
                        os.link(path, saved)
                    else:
                        path.chmod(0o666)
                    with self.assertRaises((OSError, ValueError)):
                        self.build(f)
                    self.assertEqual(f.commands, [])

    def test_all_pins_are_checked_again_after_build(self):
        targets = tuple(dict.fromkeys(builder.SOURCES + builder.FIXTURE_SOURCES)) + ('HEADER', 'QEMU', 'AUDIT')
        for name in targets:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                def change(current):
                    path = {'HEADER': current.header, 'QEMU': current.qemu, 'AUDIT': current.audit}.get(
                        name, current.here / name)
                    path.write_bytes(path.read_bytes() + b' HOST_TEST mutation')
                with self.assertRaisesRegex(ValueError, 'Source/header/candidate/plugin changed'):
                    self.build(f, mutate=change)
                self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_plugin_cannot_change_during_symbol_audit_after_its_initial_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            def change(current):
                self.assertEqual(len(current.commands), 2)
                self.assertEqual(current.commands[-1], ['nm', '-D', '--undefined-only', str(current.library)])
                self.assertEqual(len(current.library.read_bytes()), 32)
                current.library.write_bytes(current.library.read_bytes() + b' HOST_TEST mutation')
            # The plugin's first SHA is recorded after compilation, before symbol inspection.
            with self.assertRaisesRegex(ValueError, 'Source/header/candidate/plugin changed'):
                self.build(f, mutate_during_audit=change)
            self.assertEqual(len(f.commands), 4)
            self.assertTrue((f.library.parent / 'readonly-import-audit.json').is_file())
            self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_fixed_root_scratch_output_and_existing_artifacts_are_not_reused(self):
        for scenario in ('root', 'v1-root', 'scratch-symlink', 'old-work', 'v1-output', 'v3-output',
                         'library-symlink', 'library-hardlink', 'old-receipt'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                mutate = None
                if scenario == 'root':
                    f.here = f.here.with_name('unapproved-component')
                elif scenario == 'v1-root':
                    f.here = f.here.with_name('2026-10-31-qemu-shutter-gate-observer-v1')
                elif scenario == 'scratch-symlink':
                    alternate = f.root / 'alternate'
                    alternate.mkdir()
                    f.library.parent.parent.symlink_to(alternate, target_is_directory=True)
                elif scenario == 'old-work':
                    f.library.parent.mkdir(parents=True)
                elif scenario == 'v1-output':
                    f.library = f.root / 'runtime/analysis/scratch/functional-shutter-gate-v1-readonly-plugin/build-HOST_TEST/scope-observer.so'
                elif scenario == 'v3-output':
                    f.library = f.root / 'runtime/analysis/scratch/functional-M-writer-v3-readonly-scope-plugin/build-HOST_TEST/scope-observer.so'
                elif scenario == 'library-symlink':
                    def mutate(current):
                        saved = current.library.with_name('saved')
                        current.library.rename(saved)
                        current.library.symlink_to(saved)
                elif scenario == 'library-hardlink':
                    def mutate(current):
                        os.link(current.library, current.library.with_name('saved'))
                else:
                    def mutate(current):
                        (current.library.parent / 'build-receipt.json').write_text('HOST_TEST sentinel')
                with self.assertRaises((OSError, ValueError)):
                    self.build(f, mutate=mutate)
                receipt = f.library.parent / 'build-receipt.json'
                if scenario == 'old-receipt':
                    self.assertEqual(receipt.read_text(), 'HOST_TEST sentinel')
                else:
                    self.assertFalse(receipt.exists())

    def test_bad_qemu_and_static_audit_cannot_be_promoted(self):
        for key, value in (('binary_sha256', '0' * 64), ('missing_required_exports', ['qemu_plugin_read_register']),
                ('protected_binaries_unchanged', {}), ('protected_binaries_unchanged', {'candidate': True, 'production': 1}),
                ('plugin_runtime_verified', True), ('capture_verified', True), ('physical_asic_compatibility_verified', True)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                f.candidate[key] = value
                f.audit.write_text(json.dumps(f.candidate))
                with self.assertRaises(ValueError):
                    self.build(f)
                self.assertEqual(f.commands, [])

    def test_failures_keep_actual_returncode_without_a_success_receipt(self):
        for phase in ('sh', '--undefined-only', '--defined-only', '-d'):
            for rc in (-15, 9):
                with self.subTest(phase=phase, rc=rc), tempfile.TemporaryDirectory() as directory:
                    f = self.fixture(directory)
                    with self.assertRaises((RuntimeError, ValueError)):
                        self.build(f, failure=(phase, rc))
                    if phase == 'sh':
                        retained = json.loads((f.library.parent / 'plugin-build-command.json').read_bytes())
                    else:
                        audit = json.loads((f.library.parent / 'readonly-import-audit.json').read_bytes())
                        retained = audit[{'--undefined-only': 'imports', '--defined-only': 'exports', '-d': 'needed'}[phase]]
                    self.assertEqual(retained['returncode'], rc)
                    self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_missing_extra_or_unexported_qemu_api_is_rejected_but_ordinary_imports_are_separate(self):
        builder.audit_readonly(builder.ALLOWED_IMPORTS | {'fwrite', 'g_byte_array_set_size'}, builder.ALLOWED_IMPORTS)
        cases = [(builder.ALLOWED_IMPORTS - {'qemu_plugin_read_register'}, builder.ALLOWED_IMPORTS),
                 (builder.ALLOWED_IMPORTS, builder.ALLOWED_IMPORTS - {'qemu_plugin_read_register'})]
        cases += [(builder.ALLOWED_IMPORTS | {name}, builder.ALLOWED_IMPORTS | {name}) for name in
                  ('qemu_plugin_write_register', 'qemu_plugin_set_pc', 'qemu_plugin_read_memory_vaddr')]
        for imports, exports in cases:
            with self.subTest(imports=imports, exports=exports), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                with self.assertRaisesRegex(ValueError, 'exact read-only API surface'):
                    self.build(f, imports=imports, exports=exports)
                self.assertTrue((f.library.parent / 'readonly-import-audit.json').is_file())
                self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_json_duplicates_and_versioned_symbols(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate build JSON'):
            builder.object_json('{"schema":"x","schema":"y"}')
        for value in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Non-finite build JSON'):
                builder.object_json('{"unused":{"number":' + value + '}}')
        self.assertEqual(builder.object_json('{"diagnostic":1.25}'), {'diagnostic': 1.25})
        self.assertEqual(builder.symbols(' U qemu_plugin_read_register@VERSION\n U fwrite@GLIBC_2.2.5\n'),
                         {'qemu_plugin_read_register', 'fwrite'})

    def test_wrapper_text_has_strict_flags_exclusive_work_and_actual_rc(self):
        script = Path(__file__).with_name('build-plugin.sh').read_text()
        for required in ('umask 077', 'tempfile.mkdtemp(', '-std=c11 -Wall -Wextra -Werror -pedantic',
                         'build-compile-returncode.txt', 'exit "$rc"'):
            self.assertIn(required, script)
        self.assertEqual(builder.SCHEMA_FILE, 'log-schema-shutter-gate-v2.json')
        self.assertEqual(builder.CONTRACT_FILE, 'source-contract-shutter-gate-v2.json')
        self.assertEqual(builder.COMPONENT, '2026-11-02-qemu-shutter-gate-observer-v2')
        self.assertEqual(builder.SCRATCH, 'runtime/analysis/scratch/functional-shutter-gate-v2-readonly-plugin')
        self.assertEqual(builder.API_ENV, tuple('A7C2_SHUTTER_GATE_V2_TEST_' + suffix for suffix in
                         ('QEMU', 'PLUGIN', 'OUTPUT', 'SCHEMA', 'RECEIPT', 'FIXTURE_SOURCES')))
        self.assertEqual(len(builder.API_CASES), 4)
        self.assertEqual(len(builder.API_ENV), 6)


if __name__ == '__main__':
    unittest.main()
