"""Synthetic host builder boundaries; never compile, load a plugin or run QEMU."""
from pathlib import Path
import importlib.util
import json
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('scope_v3_runtime_builder', Path(__file__).with_name('build-runtime.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ReadonlyImportAuditTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        here = root / 'package with spaces/report' / builder.COMPONENT
        here.mkdir(parents=True)
        for name in set(builder.SOURCES) | set(builder.FIXTURE_SOURCES):
            path = here / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'HOST_TEST source ' + name.encode())
        (here / 'log-schema-v3.json').write_text(json.dumps(dict(schema=builder.TRACE_SCHEMA, profile=builder.PROFILE)))
        contract = dict(schema='readonly_scope_source_contract_v3', profile=builder.PROFILE,
            trace_schema=builder.TRACE_SCHEMA, trace_schema_sha256=builder.sha(here / 'log-schema-v3.json'),
            actual_build_source_names_required=list(builder.SOURCES),
            actual_fixture_source_names_required=list(builder.FIXTURE_SOURCES),
            actualAPI_cases=list(builder.API_CASES), actualAPI_environment_names=list(builder.API_ENV))
        (here / 'source-contract-v3.json').write_text(json.dumps(contract))
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
        library = root / 'package with spaces/runtime/analysis/scratch/functional-M-writer-v3-readonly-scope-plugin/build-HOST_TEST/scope-observer.so'
        return SimpleNamespace(root=root, here=here, header=header, qemu=qemu, audit=audit,
                               candidate=candidate, contract=contract, library=library, commands=[])

    def build(self, fixture, *, mutate=None, imports=None, failure=None):
        f = fixture
        elf = bytearray(32)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', elf, 16, 3, 62)
        def run(command, **kwargs):
            f.commands.append(command)
            rc = 0
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
                output = '\n'.join(' U ' + name for name in sorted(builder.ALLOWED_IMPORTS if imports is None else imports))
            elif '--defined-only' in command:
                self.assertEqual(command, ['nm', '-D', '--defined-only', str(f.qemu)])
                output = '\n'.join(' T ' + name for name in sorted(builder.ALLOWED_IMPORTS))
            else:
                self.assertEqual(command, ['readelf', '-d', str(f.library)])
                output = 'HOST_TEST dynamic section\n'
            if failure and failure[0] in command:
                rc = failure[1]
            return SimpleNamespace(returncode=rc, stdout=output, stderr='HOST_TEST failure' if rc else '')
        with mock.patch.object(builder, 'HERE', f.here), \
                mock.patch.object(builder, 'QEMU_SHA256', builder.sha(f.qemu)), \
                mock.patch.object(builder, 'HEADER_SHA256', builder.sha(f.header)), \
                mock.patch.object(builder.subprocess, 'run', side_effect=run):
            return builder.build(f.audit)

    def test_actual_builder_command_and_receipt_bind_runtime9_fixture8_and_source_bytes(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_scope_v3_builder_') as directory:
            f = self.fixture(directory)
            path = self.build(f)
            receipt = json.loads(path.read_bytes())
            self.assertEqual(receipt['schema'], 'qemu-readonly-scope-v3')
            self.assertEqual(receipt['trace_schema'], 'readonly_scope_v3')
            self.assertEqual(receipt['source_sha256'], {name: builder.sha(f.here / name) for name in builder.SOURCES})
            self.assertEqual(len(receipt['source_sha256']), 9)
            self.assertEqual(receipt['fixture_source_sha256'], {name: builder.sha(f.here / name) for name in builder.FIXTURE_SOURCES})
            self.assertEqual(len(receipt['fixture_source_sha256']), 8)
            self.assertEqual(receipt['trace_schema_sha256'], builder.sha(f.here / 'log-schema-v3.json'))
            self.assertEqual(receipt['source_contract_sha256'], builder.sha(f.here / 'source-contract-v3.json'))
            self.assertEqual(receipt['candidate_static_audit_sha256'], builder.sha(f.audit))
            self.assertEqual(receipt['library_sha256'], builder.sha(f.library))
            command = json.loads((path.parent / 'plugin-build-command.json').read_bytes())
            self.assertEqual(command, dict(command=f.commands[0], returncode=0, stdout=str(f.library) + '\n', stderr=''))
            self.assertEqual(receipt['plugin_build_command_sha256'], builder.sha(path.parent / 'plugin-build-command.json'))
            self.assertEqual(receipt['readonly_import_audit_sha256'], builder.sha(path.parent / 'readonly-import-audit.json'))
            self.assertEqual(f.commands[0], ['sh', str(f.here / 'build-plugin.sh')])
            self.assertEqual(len(f.commands), 4)
            self.assertFalse({'schema_sha256', 'log_schema_sha256', 'source_root', 'sourceDependencyFrozen'} & receipt.keys())
            for flag in ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified'):
                self.assertIs(receipt[flag], False)
            self.assertEqual(path.parent.parent.name, 'functional-M-writer-v3-readonly-scope-plugin')
            self.assertFalse((f.root / 'package with spaces/runtime/analysis/scratch/functional-M-v2-readonly-scope-plugin').exists())

    def test_contract_profile_digest_names_cases_and_environment_are_not_advisory(self):
        mutations = [('schema', 'readonly_scope_source_contract_v2'), ('profile', 'qemu-readonly-scope-v2'),
            ('trace_schema', 'readonly_scope_v2'), ('trace_schema_sha256', '0' * 64),
            ('actual_build_source_names_required', list(builder.SOURCES[:-1])),
            ('actual_build_source_names_required', list(builder.SOURCES) + ['extra.c']),
            ('actual_fixture_source_names_required', list(builder.FIXTURE_SOURCES[:-1])),
            ('actual_fixture_source_names_required', list(builder.FIXTURE_SOURCES) + ['integration/extra.py']),
            ('actualAPI_cases', list(builder.API_CASES[:-1])), ('actualAPI_environment_names', list(builder.API_ENV[:-1])),
            ('sourceDependencyFrozen', {name: '0' * 64 for name in builder.SOURCES}),
            ('schema_sha256', '0' * 64), ('log_schema_sha256', '0' * 64)]
        for key, value in mutations:
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                f.contract[key] = value
                (f.here / 'source-contract-v3.json').write_text(json.dumps(f.contract))
                with self.assertRaisesRegex(ValueError, 'Actual v3 schema/source-contract'):
                    self.build(f)
                self.assertEqual(f.commands, [])
                self.assertFalse(f.library.exists())

    def test_rehashed_old_schema_is_still_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            schema = f.here / 'log-schema-v3.json'
            schema.write_text(json.dumps(dict(schema='readonly_scope_v2', profile=builder.PROFILE)))
            f.contract['trace_schema_sha256'] = builder.sha(schema)
            (f.here / 'source-contract-v3.json').write_text(json.dumps(f.contract))
            with self.assertRaisesRegex(ValueError, 'Actual v3 schema/source-contract'):
                self.build(f)
            self.assertEqual(f.commands, [])

    def test_fixed_root_and_every_source_or_fixture_must_be_canonical_ordinary(self):
        for name in tuple(dict.fromkeys(builder.SOURCES + builder.FIXTURE_SOURCES)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                path = f.here / name
                saved = f.root / 'saved-source'
                path.rename(saved)
                with self.assertRaises(OSError):
                    self.build(f)
                self.assertEqual(f.commands, [])
                path.symlink_to(saved)
                with self.assertRaisesRegex(ValueError, 'canonical absolute paths'):
                    self.build(f)
                self.assertEqual(f.commands, [])
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            f.here = f.here.with_name('unapproved-component')
            with self.assertRaisesRegex(ValueError, 'fixed v3 component'):
                self.build(f)
            self.assertEqual(f.commands, [])

    def test_all_runtime_fixture_and_header_candidate_mutations_during_build_are_rejected(self):
        targets = tuple(dict.fromkeys(builder.SOURCES + builder.FIXTURE_SOURCES)) + ('HEADER', 'QEMU', 'AUDIT')
        for name in targets:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                def change(current):
                    path = {'HEADER': current.header, 'QEMU': current.qemu, 'AUDIT': current.audit}.get(name, current.here / name)
                    path.write_bytes(path.read_bytes() + b' HOST_TEST mutation')
                with self.assertRaisesRegex(ValueError, 'Source/header/candidate/plugin changed'):
                    self.build(f, mutate=change)
                self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_old_artifact_directory_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            f.library.parent.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'reused v3 plugin'):
                self.build(f)
            self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_scratch_redirection_and_old_v2_output_cannot_publish_a_v3_receipt(self):
        for scenario in ('scratch-symlink', 'v2-output'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                if scenario == 'scratch-symlink':
                    scratch = f.library.parent.parent
                    scratch.parent.mkdir(parents=True)
                    alternate = f.root / 'alternate'
                    alternate.mkdir()
                    scratch.symlink_to(alternate, target_is_directory=True)
                    with self.assertRaisesRegex(ValueError, 'Untrusted v3 plugin scratch'):
                        self.build(f)
                    self.assertEqual(f.commands, [])
                else:
                    f.library = f.root / 'package with spaces/runtime/analysis/scratch/functional-M-v2-readonly-scope-plugin/build-HOST_TEST/scope-observer.so'
                    with self.assertRaisesRegex(ValueError, 'v3 plugin build artifact path'):
                        self.build(f)
                    self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_unknown_qemu_bad_static_audit_and_vacuous_protection_are_rejected(self):
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

    def test_failed_inspection_keeps_actual_returncode_without_a_receipt(self):
        for rc in (-15, 9):
            with self.subTest(rc=rc), tempfile.TemporaryDirectory() as directory:
                f = self.fixture(directory)
                with self.assertRaisesRegex(ValueError, 'Static plugin symbol inspection failed'):
                    self.build(f, failure=('--undefined-only', rc))
                audit = json.loads((f.library.parent / 'readonly-import-audit.json').read_bytes())
                self.assertEqual(audit['imports']['returncode'], rc)
                self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_complete_readonly_surface_has_real_candidate_exports(self):
        self.assertEqual(len(builder.ALLOWED_IMPORTS), 11)
        builder.audit_readonly(builder.ALLOWED_IMPORTS | {'fwrite'}, builder.ALLOWED_IMPORTS | {'qemu_plugin_write_register'})

    def test_write_or_memory_access_or_missing_api_is_refused(self):
        for extra in ('qemu_plugin_write_register', 'qemu_plugin_set_pc', 'qemu_plugin_read_memory_vaddr'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                builder.audit_readonly(builder.ALLOWED_IMPORTS | {extra}, builder.ALLOWED_IMPORTS | {extra})
        with self.assertRaises(ValueError):
            builder.audit_readonly(builder.ALLOWED_IMPORTS - {'qemu_plugin_read_register'}, builder.ALLOWED_IMPORTS)
        with self.assertRaises(ValueError):
            builder.audit_readonly(builder.ALLOWED_IMPORTS, builder.ALLOWED_IMPORTS - {'qemu_plugin_read_register'})
        with tempfile.TemporaryDirectory() as directory:
            f = self.fixture(directory)
            with self.assertRaisesRegex(ValueError, 'exact read-only API surface'):
                self.build(f, imports=builder.ALLOWED_IMPORTS | {'qemu_plugin_read_memory_vaddr'})
            self.assertTrue((f.library.parent / 'readonly-import-audit.json').is_file())
            self.assertFalse((f.library.parent / 'build-receipt.json').exists())

    def test_symbol_versions_do_not_hide_the_base_api(self):
        self.assertEqual(builder.symbols(' U qemu_plugin_read_register@VERSION\n U fwrite@GLIBC_2.2.5\n'),
                         {'qemu_plugin_read_register', 'fwrite'})


if __name__ == '__main__':
    unittest.main()
