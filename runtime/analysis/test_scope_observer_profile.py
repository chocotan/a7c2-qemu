"""Host staging trust-boundary cases; no QEMU or plugin is executed here."""
from pathlib import Path
import ast
import importlib.util
import json
import struct
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('scope_profile_cases', Path(__file__).with_name('scope_observer_profile.py'))
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class ScopeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.native = self.root / 'package'
        public_root = mock.patch.object(profile, 'PUBLIC_NATIVE_ROOT', self.native)
        public_root.start()
        self.addCleanup(public_root.stop)
        self.source = self.native / 'report/2026-10-30-qemu-readonly-scope-observer'
        self.source.mkdir(parents=True)
        for name in profile.SOURCE_NAMES:
            (self.source / name).write_bytes(b'owned source ' + name.encode())
        header = self.native / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
        header.parent.mkdir(parents=True)
        header.write_bytes(b'owned API7 header')
        self.binary = self.root / 'qemu-system-aarch64'
        self.binary.write_bytes(b'owned candidate, not executable')
        self.library = self.root / 'scope-observer.so'
        elf = bytearray(32)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<HH', elf, 16, 3, 62)
        self.library.write_bytes(elf)
        self.receipt = self.root / 'build.json'
        self.data = {'schema': profile.PROFILE, 'plugin_api': 7, 'readonly_imports_verified': True,
                     'source_sha256': {name: profile.sha(self.source / name) for name in profile.SOURCE_NAMES},
                     'qemu_header_sha256': profile.sha(header), 'qemu_sha256': profile.sha(self.binary),
                     'library': str(self.library), 'library_sha256': profile.sha(self.library)}
        self.write_receipt()
        self.env = {profile.BUILD_ENV: str(self.receipt), 'MENU_FUNCTIONAL_CAMERA': 'virtual-functional-camera-v1',
                    'QEMU_SYSTEM_DIR': str(self.root)}
        self.output = self.root / 'run'
        self.output.mkdir()

    def write_receipt(self):
        self.receipt.write_text(json.dumps(self.data))

    def use_v2_receipt(self):
        for name in profile.SOURCE_NAMES_V2:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'owned v2 source ' + name.encode())
        sources = {name: profile.sha(self.source / name) for name in profile.SOURCE_NAMES_V2}
        self.data.update(schema=profile.PROFILE_V2, source_sha256=sources,
            trace_schema='readonly_scope_v2', trace_schema_sha256=sources['log-schema-v2.json'],
            source_contract_sha256=sources['source-contract-v2.json'],
            runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
        self.write_receipt()

    def use_v3_receipt(self):
        self.source = profile.source_root(self.native, profile.PROFILE_V3)
        for name in profile.SOURCE_NAMES_V3:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'HOST_TEST v3 source ' + name.encode())
        schema = self.source / 'log-schema-v3.json'
        schema.write_text(json.dumps(dict(schema='readonly_scope_v3', profile=profile.PROFILE_V3)))
        (self.source / 'source-contract-v3.json').write_text(json.dumps(dict(
            schema='readonly_scope_source_contract_v3', profile=profile.PROFILE_V3,
            trace_schema='readonly_scope_v3', trace_schema_sha256=profile.sha(schema),
            actual_build_source_names_required=list(profile.SOURCE_NAMES_V3))))
        sources = {name: profile.sha(self.source / name) for name in profile.SOURCE_NAMES_V3}
        self.data.update(schema=profile.PROFILE_V3, source_sha256=sources,
            trace_schema='readonly_scope_v3', trace_schema_sha256=sources['log-schema-v3.json'],
            source_contract_sha256=sources['source-contract-v3.json'],
            runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
        for name, value in (('V3_QEMU_SHA256', self.data['qemu_sha256']),
                            ('V3_HEADER_SHA256', self.data['qemu_header_sha256'])):
            patcher = mock.patch.object(profile, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_receipt()

    def use_shutter_gate_receipt(self):
        self.source = profile.source_root(self.native, profile.PROFILE_SHUTTER_GATE_V1)
        for name in set(profile.SOURCE_NAMES_SHUTTER_GATE_V1 + profile.FIXTURE_NAMES_SHUTTER_GATE_V1):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'HOST_TEST shutter-gate source ' + name.encode())
        schema = self.source / profile.SHUTTER_GATE_SCHEMA_FILE
        schema.write_text(json.dumps(dict(schema='readonly_shutter_gate_v1', profile=profile.PROFILE_SHUTTER_GATE_V1)))
        self.contract = dict(schema='readonly_shutter_gate_source_contract_v1', profile=profile.PROFILE_SHUTTER_GATE_V1,
            trace_schema='readonly_shutter_gate_v1', trace_schema_sha256=profile.sha(schema),
            actual_build_source_names_required=list(profile.SOURCE_NAMES_SHUTTER_GATE_V1),
            actual_fixture_source_names_required=list(profile.FIXTURE_NAMES_SHUTTER_GATE_V1),
            actualAPI_cases=list(profile.SHUTTER_GATE_CASES), actualAPI_environment_names=list(profile.SHUTTER_GATE_API_ENV))
        (self.source / profile.SHUTTER_GATE_CONTRACT_FILE).write_text(json.dumps(self.contract))
        work = self.native / 'runtime/analysis/scratch/functional-shutter-gate-v1-readonly-plugin/build-HOST_TEST'
        work.mkdir(parents=True)
        self.library = self.library.rename(work / 'scope-observer.so')
        self.receipt.unlink()
        self.receipt = work / 'build-receipt.json'
        imports = profile.SHUTTER_GATE_IMPORTS | {'fwrite', 'g_byte_array_set_size'}
        self.import_audit = {
            'imports': dict(command=['nm', '-D', '--undefined-only', str(self.library)], returncode=0,
                            stdout='\n'.join(' U ' + name for name in sorted(imports)), stderr=''),
            'exports': dict(command=['nm', '-D', '--defined-only', str(self.binary)], returncode=0,
                            stdout='\n'.join(' T ' + name for name in sorted(profile.SHUTTER_GATE_IMPORTS)), stderr=''),
            'needed': dict(command=['readelf', '-d', str(self.library)], returncode=0,
                           stdout=' (NEEDED) Shared library: [libc.so.6]\n (NEEDED) Shared library: [libglib-2.0.so.0]\n', stderr=''),
            'qemu_plugin_imports': sorted(profile.SHUTTER_GATE_IMPORTS),
            'ordinary_imports': ['fwrite', 'g_byte_array_set_size'], 'dt_needed': ['libc.so.6', 'libglib-2.0.so.0']}
        (work / 'readonly-import-audit.json').write_text(json.dumps(self.import_audit))
        (work / 'plugin-build-command.json').write_text(json.dumps(dict(command=['sh', str(self.source / 'build-plugin.sh')],
            returncode=0, stdout=str(self.library) + '\n', stderr='')))
        (self.root / 'candidate-static-audit.json').write_text('{"HOST_TEST":"not actual evidence"}')
        sources = {name: profile.sha(self.source / name) for name in profile.SOURCE_NAMES_SHUTTER_GATE_V1}
        self.data.update(schema=profile.PROFILE_SHUTTER_GATE_V1, source_sha256=sources,
            fixture_source_sha256={name: profile.sha(self.source / name) for name in profile.FIXTURE_NAMES_SHUTTER_GATE_V1},
            trace_schema='readonly_shutter_gate_v1', trace_schema_sha256=profile.sha(schema),
            source_contract_sha256=profile.sha(self.source / profile.SHUTTER_GATE_CONTRACT_FILE),
            library=str(self.library), qemu=str(self.binary),
            plugin_build_command_sha256=profile.sha(work / 'plugin-build-command.json'),
            readonly_import_audit_sha256=profile.sha(work / 'readonly-import-audit.json'),
            candidate_static_audit_sha256=profile.sha(self.root / 'candidate-static-audit.json'),
            runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
        for name, value in (('V3_QEMU_SHA256', self.data['qemu_sha256']),
                            ('V3_HEADER_SHA256', self.data['qemu_header_sha256'])):
            patcher = mock.patch.object(profile, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_receipt()

    def rehash_shutter_contract(self):
        path = self.source / profile.SHUTTER_GATE_CONTRACT_FILE
        path.write_text(json.dumps(self.contract))
        self.data['source_sha256'][profile.SHUTTER_GATE_CONTRACT_FILE] = profile.sha(path)
        self.data['source_contract_sha256'] = profile.sha(path)
        self.write_receipt()

    def test_shutter_gate_json_rejects_duplicate_and_non_finite_extra_fields(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate shutter-gate JSON'):
            profile.shutter_gate_json('{"unused":1,"unused":2}')
        for value in ('NaN', 'Infinity', '-Infinity', '1e999'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Non-finite shutter-gate JSON'):
                profile.shutter_gate_json('{"unused":{"number":' + value + '}}')
        self.assertEqual(profile.shutter_gate_json('{"diagnostic":1.25}'), {'diagnostic': 1.25})

    def test_shutter_gate_uses_explicit_schema_and_new_fixed_root_with_legacy_closures_unchanged(self):
        self.assertEqual(profile.PROFILE_SHUTTER_GATE_V1, 'qemu-readonly-shutter-gate-v1')
        self.assertEqual(profile.source_root(self.native, profile.PROFILE_SHUTTER_GATE_V1),
                         self.native / 'report/2026-10-31-qemu-shutter-gate-observer-v1')
        self.assertEqual(profile.SHUTTER_GATE_SCHEMA_FILE, 'log-schema-shutter-gate-v1.json')
        self.assertEqual(len(profile.SOURCE_NAMES_SHUTTER_GATE_V1), 7)
        self.assertEqual(len(profile.FIXTURE_NAMES_SHUTTER_GATE_V1), 7)
        self.assertEqual(len(profile.SOURCE_NAMES), 3)
        self.assertEqual(len(profile.SOURCE_NAMES_V2), 9)
        self.assertEqual(len(profile.SOURCE_NAMES_V3), 9)
        for unknown in ('qemu-readonly-shutter-gate-v2', 'qemu-readonly-shutter-gate-v1/other'):
            with self.assertRaises(ValueError):
                profile.source_root(self.native, unknown)

    def test_shutter_gate_actual_staging_metadata_and_exit_preserve_raw_returncode(self):
        self.use_shutter_gate_receipt()
        for index, rc in enumerate((0, -15, 9, None)):
            output = self.root / ('shutter-run-' + str(index))
            output.mkdir()
            env = self.env.copy()
            env[profile.BUILD_ENV] = str(self.receipt)
            result = profile.prepare(self.native, env, output)
            self.assertEqual(result['profile'], profile.PROFILE_SHUTTER_GATE_V1)
            self.assertEqual(result['trace_schema'], 'readonly_shutter_gate_v1')
            self.assertEqual(result['trace_schema_sha256'], profile.sha(self.source / profile.SHUTTER_GATE_SCHEMA_FILE))
            self.assertEqual(result['source_sha256'], self.data['source_sha256'])
            self.assertEqual(result['fixture_source_sha256'], self.data['fixture_source_sha256'])
            self.assertEqual(len(result['source_sha256']), 7)
            self.assertEqual(len(result['fixture_source_sha256']), 7)
            self.assertEqual(result['readonly_import_audit_sha256'], self.data['readonly_import_audit_sha256'])
            self.assertEqual(Path(result['library']).read_bytes(), self.library.read_bytes())
            self.assertEqual(Path(result['library']).stat().st_mode & 0o777, 0o400)
            self.assertEqual(env[profile.CHILD_ENV[0]], result['library'])
            self.assertEqual(env[profile.CHILD_ENV[1]], result['library_sha256'])
            self.assertFalse(Path(result['log']).exists())
            profile.record_exit(output, result, SimpleNamespace(pid=12345, poll=lambda: rc))
            exited = json.loads((output / 'readonly-scope-exit.json').read_bytes())
            self.assertEqual(exited['profile'], profile.PROFILE_SHUTTER_GATE_V1)
            self.assertEqual(exited['returncode'], rc)
            self.assertIs(exited['capture_verified'], False)
            self.assertIs(exited['physical_asic_compatibility_verified'], False)
            self.assertEqual((output / 'readonly-scope-exit.json').stat().st_mode & 0o777, 0o600)
            self.assertIs(exited['log_available'], False)

    def test_shutter_gate_exit_trace_is_read_back_and_actual_change_rejects(self):
        self.use_shutter_gate_receipt()
        self.env[profile.BUILD_ENV] = str(self.receipt)
        result = profile.prepare(self.native, self.env, self.output)
        log = self.output / 'readonly-scope-trace.log'
        log.write_bytes(b'HOST_TEST immutable raw trace\n')
        original_sha = profile.sha
        reads = []
        def changing_sha(path):
            value = original_sha(path)
            if Path(path) == log:
                reads.append(value)
                if len(reads) == 1:
                    log.write_bytes(b'HOST_TEST changed raw trace\n')
            return value
        with mock.patch.object(profile, 'sha', side_effect=changing_sha), \
                self.assertRaisesRegex(ValueError, 'trace changed while recording'):
            profile.record_exit(self.output, result, SimpleNamespace(pid=12345, poll=lambda: 0))
        self.assertEqual(len(reads), 2)
        exited = json.loads((self.output / 'readonly-scope-exit.json').read_bytes())
        self.assertEqual(exited['log_sha256'], reads[0])
        self.assertNotEqual(exited['log_sha256'], original_sha(log))
        self.assertIs(exited['capture_verified'], False)

    def test_shutter_gate_original_functional_artifact_admission_keeps_explicit_receipt_and_default_pin(self):
        self.use_shutter_gate_receipt()
        tree = ast.parse(Path(__file__).with_name('functional_camera_runner.py').read_text())
        blocks = [node for node in ast.walk(tree) if isinstance(node, ast.If) and
                  ast.unparse(node.test) == 'scope_build_receipt is None']
        self.assertEqual(len(blocks), 1)
        code = compile(ast.Module(body=blocks, type_ignores=[]), '<HOST_TEST original artifact admission>', 'exec')
        pins = {node.targets[0].id: node.value.value for node in tree.body if isinstance(node, ast.Assign) and
                len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and
                isinstance(node.value, ast.Constant) and node.targets[0].id in
                ('QEMU_SHA256', 'READONLY_SCOPE_QEMU_SHA256')}
        self.assertEqual(pins['QEMU_SHA256'], 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02')
        self.assertEqual(pins['READONLY_SCOPE_QEMU_SHA256'],
                         '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4')
        def require(condition, message):
            if not condition:
                raise ValueError(message)
        namespace = dict(require=require, scope_build_receipt=None, qemu_sha256=self.data['qemu_sha256'],
            QEMU_SHA256=pins['QEMU_SHA256'], READONLY_SCOPE_QEMU_SHA256=self.data['qemu_sha256'],
            scope_observer_profile=profile, root=self.native, qemu_binary=self.binary)
        with mock.patch.object(profile, 'validate_build', wraps=profile.validate_build) as validate:
            with self.assertRaisesRegex(ValueError, 'accepted unchanged QEMU'):
                exec(code, namespace)
            validate.assert_not_called()
            namespace['qemu_sha256'] = pins['QEMU_SHA256']
            exec(code, namespace)
            validate.assert_not_called()
            namespace.update(scope_build_receipt=self.receipt, qemu_sha256=self.data['qemu_sha256'])
            exec(code, namespace)
            validate.assert_called_once_with(self.native, self.receipt, self.binary)
            self.data['source_sha256']['build-runtime.py'] = '0' * 64
            self.write_receipt()
            with self.assertRaisesRegex(ValueError, 'source identity changed'):
                exec(code, namespace)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_shutter_gate_default_off_and_raw_child_environment_no_fallback(self):
        self.use_shutter_gate_receipt()
        self.env[profile.BUILD_ENV] = str(self.receipt)
        env = {key: value for key, value in self.env.items() if key != profile.BUILD_ENV}
        self.assertIsNone(profile.prepare(self.native, env, self.output))
        for name in profile.CHILD_ENV:
            for value in ('unbound', ''):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    profile.prepare(self.native, dict(self.env, **{name: value}), self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_shutter_gate_aliases_mixed_maps_placeholder_and_promoted_claims_reject(self):
        self.use_shutter_gate_receipt()
        original = json.loads(json.dumps(self.data))
        mutations = [('trace_schema', 'readonly_scope_v1'), ('trace_schema_sha256', None),
            ('trace_schema_sha256', profile.LEGACY_SCHEMA_SHA256), ('source_contract_sha256', '0' * 64),
            ('readonly_imports_verified', False), ('plugin_api', 7.0), ('runtime_verified', True),
            ('capture_verified', True), ('physical_asic_compatibility_verified', 0),
            ('fixture_source_sha256', None), ('candidate_static_audit_sha256', None),
            ('source_sha256', {**original['source_sha256'], 'late-sites.inc': '0' * 64}),
            ('fixture_source_sha256', {**original['fixture_source_sha256'], 'integration/scope_trace_checks.py': '0' * 64})]
        mutations += [(name, str(self.source)) for name in profile.SHUTTER_GATE_ALIASES]
        for key, value in mutations:
            self.data = dict(original, **{key: value})
            self.write_receipt()
            with self.subTest(key=key), self.assertRaises(ValueError):
                profile.validate_build(self.native, self.receipt, self.binary)
        for field, names in (('source_sha256', profile.SOURCE_NAMES_SHUTTER_GATE_V1),
                             ('fixture_source_sha256', profile.FIXTURE_NAMES_SHUTTER_GATE_V1)):
            for name in names:
                self.data = json.loads(json.dumps(original))
                del self.data[field][name]
                self.write_receipt()
                with self.subTest(field=field, missing=name), self.assertRaises(ValueError):
                    profile.validate_build(self.native, self.receipt, self.binary)
        self.data = original
        self.write_receipt()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_shutter_gate_same_v1_suffix_old_schema_cannot_be_rehashed_into_new_receipt(self):
        self.use_shutter_gate_receipt()
        (self.source / 'log-schema-v1.json').write_text(json.dumps(dict(schema='readonly_shutter_gate_v1',
                                                                     profile=profile.PROFILE_SHUTTER_GATE_V1)))
        schema = self.source / profile.SHUTTER_GATE_SCHEMA_FILE
        schema.write_text(json.dumps(dict(schema='readonly_scope_v1', profile=profile.PROFILE_SHUTTER_GATE_V1)))
        self.data['source_sha256'][profile.SHUTTER_GATE_SCHEMA_FILE] = profile.sha(schema)
        self.data['trace_schema_sha256'] = profile.sha(schema)
        self.contract['trace_schema_sha256'] = profile.sha(schema)
        self.rehash_shutter_contract()
        with self.assertRaisesRegex(ValueError, 'actual schema/source-contract'):
            profile.validate_build(self.native, self.receipt, self.binary)

    def test_shutter_gate_source_contract_names_cases_environment_and_no_self_hash_are_exact(self):
        self.use_shutter_gate_receipt()
        original = dict(self.contract)
        mutations = [('schema', 'source-contract-shutter-gate-v1'), ('profile', profile.PROFILE),
            ('source_contract_sha256', None), ('actual_build_source_names_required', list(profile.SOURCE_NAMES_V3)),
            ('actual_fixture_source_names_required', list(profile.FIXTURE_NAMES_SHUTTER_GATE_V1[:-1])),
            ('actualAPI_cases', list(profile.SHUTTER_GATE_CASES) + ['anchor']),
            ('actualAPI_environment_names', list(profile.SHUTTER_GATE_API_ENV[:-1]))]
        for key, value in mutations:
            self.contract = dict(original, **{key: value})
            self.rehash_shutter_contract()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'actual schema/source-contract'):
                profile.validate_build(self.native, self.receipt, self.binary)
        self.contract = original
        self.rehash_shutter_contract()

    def test_shutter_gate_import_audit_requires_exact_eleven_and_real_zero_rc_even_when_rehashed(self):
        self.use_shutter_gate_receipt()
        original = json.loads(json.dumps(self.import_audit))
        for kind in ('missing', 'extra', 'unexported', 'rc', 'ordinary', 'needed'):
            audit = json.loads(json.dumps(original))
            if kind == 'missing':
                audit['imports']['stdout'] = audit['imports']['stdout'].replace(' U qemu_plugin_read_register', '')
            elif kind == 'extra':
                audit['imports']['stdout'] += '\n U qemu_plugin_read_memory_vaddr'
            elif kind == 'unexported':
                audit['exports']['stdout'] = ''
            elif kind == 'rc':
                audit['imports']['returncode'] = -15
            elif kind == 'ordinary':
                audit['ordinary_imports'] = []
            else:
                audit['dt_needed'] = []
            path = self.library.parent / 'readonly-import-audit.json'
            path.write_text(json.dumps(audit))
            self.data['readonly_import_audit_sha256'] = profile.sha(path)
            self.write_receipt()
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                profile.validate_build(self.native, self.receipt, self.binary)
        path.write_text(json.dumps(original))
        self.data['readonly_import_audit_sha256'] = profile.sha(path)
        self.write_receipt()
        self.assertEqual(profile.validate_build(self.native, self.receipt, self.binary)['profile'],
                         profile.PROFILE_SHUTTER_GATE_V1)

    def test_shutter_gate_every_source_fixture_and_audit_must_be_ordinary_single_link(self):
        self.use_shutter_gate_receipt()
        paths = [self.source / name for name in dict.fromkeys(profile.SOURCE_NAMES_SHUTTER_GATE_V1 +
                                                             profile.FIXTURE_NAMES_SHUTTER_GATE_V1)]
        paths += [self.receipt, self.library, self.library.parent / 'readonly-import-audit.json',
                  self.library.parent / 'plugin-build-command.json']
        for path in paths:
            saved = path.with_name(path.name + '.saved')
            path.rename(saved)
            with self.subTest(missing=path), self.assertRaises((OSError, ValueError)):
                profile.validate_build(self.native, self.receipt, self.binary)
            path.symlink_to(saved)
            with self.subTest(symlink=path), self.assertRaises(ValueError):
                profile.validate_build(self.native, self.receipt, self.binary)
            path.unlink()
            saved.rename(path)
            profile.os.link(path, saved)
            with self.subTest(hardlink=path), self.assertRaises(ValueError):
                profile.validate_build(self.native, self.receipt, self.binary)
            saved.unlink()

    def test_shutter_gate_old_exit_and_trace_symlinks_are_refused(self):
        self.use_shutter_gate_receipt()
        self.env[profile.BUILD_ENV] = str(self.receipt)
        exit_path = self.output / 'readonly-scope-exit.json'
        exit_path.symlink_to(self.root / 'absent')
        with self.assertRaisesRegex(ValueError, 'old exit receipt'):
            profile.prepare(self.native, self.env, self.output)
        exit_path.unlink()
        result = profile.prepare(self.native, self.env, self.output)
        (self.output / 'readonly-scope-trace.log').symlink_to(self.receipt)
        with self.assertRaises(ValueError):
            profile.record_exit(self.output, result, SimpleNamespace(pid=12345, poll=lambda: 0))
        self.assertFalse(exit_path.exists())

    def test_shutter_gate_fixture_or_audit_changed_during_staging_never_exports_child_env(self):
        self.use_shutter_gate_receipt()
        self.env[profile.BUILD_ENV] = str(self.receipt)
        original_sha = profile.sha
        def changing_sha(path):
            result = original_sha(path)
            if Path(path) == self.output / 'readonly-scope-observer.so':
                (self.source / 'integration/fixture.S').write_bytes(b'HOST_TEST changed during stage')
            return result
        with mock.patch.object(profile, 'sha', side_effect=changing_sha), self.assertRaises(ValueError):
            profile.prepare(self.native, self.env, self.output)
        self.assertTrue((self.output / 'readonly-scope-observer.so').exists())
        self.assertFalse(any(name in self.env for name in profile.CHILD_ENV))

    def test_actual_manifest_caller_hashes_every_version_source_from_its_fixed_root(self):
        tree = ast.parse(Path(__file__).with_name('qemu-menu-probe.py').read_text())
        blocks = [node for node in tree.body if isinstance(node, ast.If) and
                  ast.unparse(node.test) == 'scope_observer is not None']
        self.assertEqual(len(blocks), 1)
        code = compile(ast.Module(body=blocks, type_ignores=[]), '<HOST_TEST manifest caller>', 'exec')
        for version, names in profile.SOURCE_SETS.items():
            with self.subTest(version=version):
                root = profile.source_root(self.native, version)
                for name in names:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'HOST_TEST source ' + version.encode() + name.encode())
                sources = {name: profile.sha(root / name) for name in names}
                metadata = dict(profile=version, source_sha256=sources,
                                build_receipt=str(self.receipt), library=str(self.library))
                manifest = {'files': {}}
                exec(code, dict(Path=Path, base=self.native / 'runtime/analysis', manifest=manifest,
                                scope_observer=metadata, scope_source_root=profile.source_root,
                                sha256_file=profile.sha))
                expected = {str(path): profile.sha(path) for path in
                            (self.receipt, self.library, *(root / name for name in names))}
                self.assertEqual(manifest['files'], expected)
        manifest = {'files': {}}
        exec(code, dict(scope_observer=None, manifest=manifest))
        self.assertEqual(manifest['files'], {})

    def test_actual_cleanup_keeps_primary_error_when_close_geometry_is_rejected(self):
        tree = ast.parse(Path(__file__).with_name('check-natural-gtk-input.py').read_text())
        blocks = [node for node in ast.walk(tree) if isinstance(node, ast.Try) and
                  any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and
                      call.func.id == 'close_launcher' for stmt in node.body for call in ast.walk(stmt))]
        self.assertEqual(len(blocks), 1)
        code = compile(ast.Module(body=blocks, type_ignores=[]), '<HOST_TEST cleanup caller>', 'exec')
        primary = RuntimeError('HOST_TEST original control EOF')
        retained = []
        def reject_close(*args):
            raise ValueError('HOST_TEST missing run geometry')
        class TimeoutExpired(Exception):
            pass
        namespace = dict(close_launcher=reject_close, child=object(), geometry=object(), env={},
            FUNCTIONAL_CAMERA_PROFILE='HOST_TEST functional', retain_resources=retained.append,
            subprocess=SimpleNamespace(TimeoutExpired=TimeoutExpired))
        try:
            try:
                raise primary
            finally:
                exec(code, namespace)
        except RuntimeError as caught:
            self.assertIs(caught, primary)
        else:
            self.fail('primary startup exception was suppressed')
        self.assertEqual(len(retained), 1)
        self.assertIn('missing run geometry', retained[0])

    def test_actual_xvfb_keeps_displayfd_but_does_not_hold_parent_stdout_pipe(self):
        tree = ast.parse(Path(__file__).with_name('check-natural-gtk-input.py').read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and
                 ast.unparse(node.func) == 'subprocess.Popen' and node.args and
                 isinstance(node.args[0], ast.List) and node.args[0].elts and
                 isinstance(node.args[0].elts[0], ast.Constant) and node.args[0].elts[0].value == 'Xvfb']
        self.assertEqual(len(calls), 1)
        keywords = {key.arg: ast.unparse(key.value) for key in calls[0].keywords}
        self.assertEqual(keywords['stdout'], 'subprocess.DEVNULL')
        self.assertEqual(keywords['stderr'], 'subprocess.DEVNULL')
        self.assertEqual(keywords['pass_fds'], '(write_fd,)')
        self.assertEqual(keywords['start_new_session'], 'True')
        self.assertIn('-displayfd', [node.value for node in calls[0].args[0].elts
                                   if isinstance(node, ast.Constant)])

    def test_version_selects_only_fixed_roots_and_keeps_reviewed_v3_pins(self):
        for version in (profile.PROFILE, profile.PROFILE_V2):
            self.assertEqual(profile.source_root(self.native, version), self.source)
        self.assertEqual(profile.source_root(self.native, profile.PROFILE_V3),
            self.native / 'report/2026-10-31-qemu-M-writer-observer-v3')
        for version in ('qemu-readonly-scope-v4', [], None):
            with self.subTest(version=version), self.assertRaises(ValueError):
                profile.source_root(self.native, version)
        self.assertEqual(profile.V3_QEMU_SHA256, '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4')
        self.assertEqual(profile.V3_HEADER_SHA256, '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9')

    def test_v3_actual_selected_stage_metadata_comes_from_new_sources_and_preserves_raw_exit(self):
        self.use_v3_receipt()
        for index, rc in enumerate((0, -15, 9, None)):
            output = self.root / ('v3-run-' + str(index))
            output.mkdir()
            env = self.env.copy()
            result = profile.prepare(self.native, env, output)
            self.assertEqual(result['profile'], profile.PROFILE_V3)
            self.assertEqual(result['trace_schema'], json.loads((self.source / 'log-schema-v3.json').read_bytes())['schema'])
            self.assertEqual(result['source_sha256'],
                {name: profile.sha(self.source / name) for name in profile.SOURCE_NAMES_V3})
            self.assertEqual(len(result['source_sha256']), 9)
            self.assertEqual(result['trace_schema_sha256'], profile.sha(self.source / 'log-schema-v3.json'))
            self.assertEqual(result['source_contract_sha256'], profile.sha(self.source / 'source-contract-v3.json'))
            self.assertEqual(result['build_receipt_sha256'], profile.sha(self.receipt))
            self.assertEqual(Path(result['library']).read_bytes(), self.library.read_bytes())
            self.assertEqual(env[profile.CHILD_ENV[0]], result['library'])
            self.assertEqual(env[profile.CHILD_ENV[1]], result['library_sha256'])
            self.assertFalse(Path(result['log']).exists())
            profile.record_exit(output, result, SimpleNamespace(pid=12345, poll=lambda: rc))
            exited = json.loads((output / 'readonly-scope-exit.json').read_bytes())
            self.assertEqual(exited['profile'], profile.PROFILE_V3)
            self.assertEqual(exited['returncode'], rc)
            self.assertIs(exited['capture_verified'], False)
            self.assertIs(exited['physical_asic_compatibility_verified'], False)

    def test_v3_no_receipt_stays_off_even_with_an_available_new_build(self):
        self.use_v3_receipt()
        env = {key: value for key, value in self.env.items() if key != profile.BUILD_ENV}
        self.assertIsNone(profile.prepare(self.native, env, self.output))
        self.assertFalse(any(name in env for name in profile.CHILD_ENV))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_v3_profile_alias_old_schema_mixed_source_and_promoted_flags_fail_closed(self):
        self.use_v3_receipt()
        original = json.loads(json.dumps(self.data))
        mutations = [('schema', 'other'), ('trace_schema', 'readonly_scope_v2'),
            ('trace_schema_sha256', profile.LEGACY_SCHEMA_SHA256), ('source_contract_sha256', '0' * 64),
            ('readonly_imports_verified', False), ('plugin_api', 7.0), ('runtime_verified', True),
            ('capture_verified', True), ('physical_asic_compatibility_verified', 0),
            ('source_sha256', {**self.data['source_sha256'], 'integration/fixture.S': '0' * 64})]
        mutations += [(name, str(self.source)) for name in
                      ('source_root', 'Source_root', 'sourceDependencyFrozen', 'v3_schema_sha256',
                       'schema_sha256', 'log_schema_sha256')]
        for key, value in mutations:
            self.data = dict(original, **{key: value})
            self.write_receipt()
            with self.subTest(key=key), self.assertRaises(ValueError):
                profile.prepare(self.native, self.env.copy(), self.output)
            self.assertEqual(list(self.output.iterdir()), [])
        for name in profile.SOURCE_NAMES_V3:
            self.data = json.loads(json.dumps(original))
            del self.data['source_sha256'][name]
            self.write_receipt()
            with self.subTest(missing=name), self.assertRaises(ValueError):
                profile.prepare(self.native, self.env.copy(), self.output)
        self.data = original
        self.write_receipt()

    def test_v3_rehashed_old_schema_and_unrelated_contract_are_rejected(self):
        self.use_v3_receipt()
        schema = self.source / 'log-schema-v3.json'
        schema.write_text(json.dumps(dict(schema='readonly_scope_v2', profile=profile.PROFILE_V3)))
        self.data['source_sha256']['log-schema-v3.json'] = profile.sha(schema)
        self.data['trace_schema_sha256'] = profile.sha(schema)
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'actual schema/source-contract'):
            profile.prepare(self.native, self.env, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_v3_source_root_cannot_be_replaced_by_a_receipt_or_a_symlink(self):
        self.use_v3_receipt()
        alternate = self.root / 'unreviewed-source-root'
        self.source.rename(alternate)
        self.data['source_root'] = str(alternate)
        self.write_receipt()
        with self.assertRaises((OSError, ValueError)):
            profile.prepare(self.native, self.env, self.output)
        self.source.symlink_to(alternate, target_is_directory=True)
        self.data.pop('source_root')
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'canonical ordinary'):
            profile.prepare(self.native, self.env, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_v3_every_source_must_remain_canonical_and_present(self):
        self.use_v3_receipt()
        for name in profile.SOURCE_NAMES_V3:
            path = self.source / name
            saved = path.with_name(path.name + '.saved')
            path.rename(saved)
            with self.subTest(missing=name), self.assertRaises((OSError, ValueError)):
                profile.validate_build(self.native, self.receipt, self.binary)
            path.symlink_to(saved)
            with self.subTest(symlink=name), self.assertRaises(ValueError):
                profile.validate_build(self.native, self.receipt, self.binary)
            path.unlink()
            saved.rename(path)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_v3_reader_change_during_stage_retains_failed_copy_without_child_environment(self):
        self.use_v3_receipt()
        original_sha = profile.sha
        def changing_sha(path):
            result = original_sha(path)
            if Path(path) == self.output / 'readonly-scope-observer.so':
                (self.source / 'check_run_context_v3.py').write_bytes(b'HOST_TEST changed during stage')
            return result
        with mock.patch.object(profile, 'sha', side_effect=changing_sha), \
                self.assertRaisesRegex(ValueError, 'assets changed during staging'):
            profile.prepare(self.native, self.env, self.output)
        self.assertTrue((self.output / 'readonly-scope-observer.so').exists())
        self.assertFalse(any(name in self.env for name in profile.CHILD_ENV))

    def test_v2_explicit_schema_source_closure_and_exit_keep_actual_version(self):
        self.use_v2_receipt()
        result = profile.prepare(self.native, self.env, self.output)
        self.assertEqual(result['profile'], profile.PROFILE_V2)
        self.assertEqual(result['trace_schema'], 'readonly_scope_v2')
        self.assertEqual(set(result['source_sha256']), set(profile.SOURCE_NAMES_V2))
        self.assertEqual(result['trace_schema_sha256'], self.data['source_sha256']['log-schema-v2.json'])
        profile.record_exit(self.output, result, SimpleNamespace(pid=12345, poll=lambda: 0))
        exit_receipt = json.loads((self.output / 'readonly-scope-exit.json').read_bytes())
        self.assertEqual(exit_receipt['profile'], profile.PROFILE_V2)
        self.assertIs(exit_receipt['capture_verified'], False)
        self.assertFalse(Path(result['log']).exists())

    def test_v2_rejects_old_schema_pin_missing_reader_and_promoted_flags(self):
        self.use_v2_receipt()
        for key, value in (('schema', []), ('schema', 'qemu-readonly-scope-v4'),
                ('trace_schema', 'readonly_scope_v1'), ('trace_schema_sha256', profile.LEGACY_SCHEMA_SHA256),
                ('source_contract_sha256', '0' * 64), ('runtime_verified', True),
                ('capture_verified', True), ('physical_asic_compatibility_verified', True)):
            old = self.data[key]
            self.data[key] = value
            self.write_receipt()
            with self.subTest(key=key), self.assertRaises(ValueError):
                profile.prepare(self.native, self.env.copy(), self.output)
            self.assertEqual(list(self.output.iterdir()), [])
            self.data[key] = old
        for name in profile.SOURCE_NAMES_V2:
            digest = self.data['source_sha256'].pop(name)
            self.write_receipt()
            with self.subTest(missing=name), self.assertRaises(ValueError):
                profile.validate_build(self.native, self.receipt, self.binary)
            self.data['source_sha256'][name] = digest
        self.write_receipt()
        for alias in ('schema_sha256', 'log_schema_sha256'):
            self.data[alias] = self.data['trace_schema_sha256']
            self.write_receipt()
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, 'schema/source-contract binding'):
                profile.validate_build(self.native, self.receipt, self.binary)
            del self.data[alias]
        self.write_receipt()
        self.data['schema'] = profile.PROFILE
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'source identity changed'):
            profile.validate_build(self.native, self.receipt, self.binary)

    def test_v2_reader_change_during_stage_is_not_a_successful_profile(self):
        self.use_v2_receipt()
        original_sha = profile.sha
        def changing_sha(path):
            result = original_sha(path)
            if Path(path) == self.output / 'readonly-scope-observer.so':
                (self.source / 'check_run_context_v2.py').write_bytes(b'changed during stage')
            return result
        with mock.patch.object(profile, 'sha', side_effect=changing_sha), \
                self.assertRaisesRegex(ValueError, 'assets changed during staging'):
            profile.prepare(self.native, self.env, self.output)
        self.assertTrue((self.output / 'readonly-scope-observer.so').exists())
        self.assertFalse((self.output / 'readonly-scope-trace.log').exists())
        self.assertFalse(any(name in self.env for name in profile.CHILD_ENV))

    def test_default_off_has_no_assets_or_side_effects(self):
        self.assertIsNone(profile.prepare(self.native, {}, self.output))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_bound_copy_is_read_back_and_log_not_precreated(self):
        result = profile.prepare(self.native, self.env, self.output)
        copied = Path(result['library'])
        self.assertEqual(copied.read_bytes(), self.library.read_bytes())
        self.assertEqual(copied.stat().st_mode & 0o777, 0o400)
        self.assertFalse(Path(result['log']).exists())
        self.assertEqual(self.env['QEMU_SCOPE_OBSERVER_SHA256'], profile.sha(copied))
        self.assertEqual(result['identity_binding'], 'unverified')
        self.assertIs(result['capture_verified'], False)

    def test_build_validation_reads_assets_without_staging(self):
        result = profile.validate_build(self.native, self.receipt, self.binary)
        self.assertEqual(result['library'], str(self.library))
        self.assertEqual(result['qemu_sha256'], profile.sha(self.binary))
        self.assertEqual(result['source_sha256'], self.data['source_sha256'])
        self.assertNotIn('log', result)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(any(name in self.env for name in profile.CHILD_ENV))

    def test_receipt_change_between_validation_and_staging_is_rejected(self):
        validate = profile.validate_build
        def replace_receipt(*args):
            result = validate(*args)
            self.receipt.write_bytes(self.receipt.read_bytes() + b' ')
            return result
        with mock.patch.object(profile, 'validate_build', side_effect=replace_receipt), \
                self.assertRaisesRegex(ValueError, 'receipt changed before staging'):
            profile.prepare(self.native, self.env, self.output)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_receipt_corruption_cannot_stage_any_plugin(self):
        for key, value in (('schema', 'other'), ('plugin_api', 7.0), ('plugin_api', 8),
                           ('readonly_imports_verified', False), ('source_sha256', {}),
                           ('qemu_header_sha256', '0' * 64), ('qemu_sha256', '0' * 64),
                           ('library_sha256', '0' * 64)):
            with self.subTest(key=key, value=value):
                old = self.data[key]
                self.data[key] = value
                self.write_receipt()
                with self.assertRaises(ValueError):
                    profile.prepare(self.native, self.env.copy(), self.output)
                self.assertEqual(list(self.output.iterdir()), [])
                self.data[key] = old
        self.write_receipt()

    def test_raw_child_environment_cannot_enable_the_profile(self):
        for name in profile.CHILD_ENV:
            with self.subTest(name=name), self.assertRaises(ValueError):
                profile.prepare(self.native, {name: 'unbound'}, self.output)

    def test_profile_and_vcpu_must_be_explicit(self):
        for values in ({'MENU_FUNCTIONAL_CAMERA': ''}, {'QEMU_CPU_COUNT': '2'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                profile.prepare(self.native, dict(self.env, **values), self.output)

    def test_reused_or_symlink_log_is_never_overwritten(self):
        log = self.output / 'readonly-scope-trace.log'
        log.symlink_to(self.root / 'absent')
        with self.assertRaises(ValueError):
            profile.prepare(self.native, self.env, self.output)
        self.assertTrue(log.is_symlink())
        self.assertFalse((self.output / 'readonly-scope-observer.so').exists())

    def test_reused_staged_plugin_is_never_overwritten(self):
        old = self.output / 'readonly-scope-observer.so'
        old.write_bytes(b'old run')
        with self.assertRaises(ValueError):
            profile.prepare(self.native, self.env, self.output)
        self.assertEqual(old.read_bytes(), b'old run')

    def test_library_tamper_and_nonshared_elf_are_refused(self):
        self.library.write_bytes(b'changed after build')
        with self.assertRaises(ValueError):
            profile.prepare(self.native, self.env, self.output)
        self.data['library_sha256'] = profile.sha(self.library)
        self.write_receipt()
        with self.assertRaises(ValueError):
            profile.prepare(self.native, self.env, self.output)

    def test_exit_receipt_retains_actual_returncode_and_missing_log(self):
        result = profile.prepare(self.native, self.env, self.output)
        process = SimpleNamespace(pid=12345, poll=lambda: -15)
        profile.record_exit(self.output, result, process)
        receipt = json.loads((self.output / 'readonly-scope-exit.json').read_bytes())
        self.assertEqual(receipt['returncode'], -15)
        self.assertIs(receipt['log_available'], False)
        self.assertIsNone(receipt['log_sha256'])
        self.assertIs(receipt['capture_verified'], False)
        with self.assertRaises(FileExistsError):
            profile.record_exit(self.output, result, process)

    def test_exit_receipt_is_noop_when_profile_off(self):
        profile.record_exit(self.output, None, None)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_symlink_library_is_not_followed(self):
        link = self.root / 'link.so'
        link.symlink_to(self.library)
        self.data['library'] = str(link)
        self.write_receipt()
        with self.assertRaises(ValueError):
            profile.prepare(self.native, self.env, self.output)


if __name__ == '__main__':
    unittest.main()
