"""Static import-audit regressions; never compile or load a plugin here."""
from pathlib import Path
import importlib.util
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('scope_runtime_builder', Path(__file__).with_name('build-runtime.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ReadonlyImportAuditTests(unittest.TestCase):
    def fake_build(self, directory, *, change_reader=False):
        root = Path(directory)
        here = root / 'package with spaces/report/component'
        here.mkdir(parents=True)
        for name in builder.SOURCES:
            path = here / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'HOST_TEST source ' + name.encode())
        header = here.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
        header.parent.mkdir(parents=True)
        header.write_bytes(b'#define QEMU_PLUGIN_VERSION 7\n')
        qemu = root / 'qemu-system-aarch64'
        qemu.write_bytes(b'HOST_TEST candidate, never executed')
        audit = root / 'candidate.json'
        audit.write_text(json.dumps(dict(binary=str(qemu), binary_sha256=builder.sha(qemu),
            missing_required_exports=[], protected_binaries_unchanged={'production': True, 'legacy': True})))
        library = root / 'package with spaces/runtime/analysis/scratch/functional-M-v2-readonly-scope-plugin/build-HOST_TEST/scope-observer.so'
        library.parent.mkdir(parents=True)
        library.write_bytes(b'HOST_TEST plugin, never loaded')
        def run(command, **kwargs):
            if command[0] == 'sh':
                if change_reader:
                    (here / 'check_run_context_v2.py').write_bytes(b'changed while building')
                output = str(library) + '\n'
            elif '--undefined-only' in command:
                output = '\n'.join(' U ' + name for name in sorted(builder.ALLOWED_IMPORTS))
            elif '--defined-only' in command:
                output = '\n'.join(' T ' + name for name in sorted(builder.ALLOWED_IMPORTS))
            else:
                assert command[:2] == ['readelf', '-d']
                output = 'HOST_TEST dynamic section\n'
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        with mock.patch.object(builder, 'HERE', here), mock.patch.object(builder.subprocess, 'run', side_effect=run):
            return builder.build(audit)

    def test_v2_receipt_binds_all_readers_schema_and_new_artifact_directory(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_scope_v2_builder_') as directory:
            path = self.fake_build(directory)
            receipt = json.loads(path.read_bytes())
            self.assertEqual(receipt['schema'], 'qemu-readonly-scope-v2')
            self.assertEqual(receipt['trace_schema'], 'readonly_scope_v2')
            self.assertEqual(set(receipt['source_sha256']), set(builder.SOURCES))
            self.assertEqual(len(receipt['source_sha256']), 9)
            self.assertEqual(receipt['trace_schema_sha256'], receipt['source_sha256']['log-schema-v2.json'])
            self.assertEqual(receipt['source_contract_sha256'], receipt['source_sha256']['source-contract-v2.json'])
            self.assertIs(receipt['runtime_verified'], False)
            self.assertIs(receipt['capture_verified'], False)
            self.assertIn('functional-M-v2-readonly-scope-plugin', str(path))

    def test_v2_reader_change_during_build_cannot_publish_a_receipt(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_scope_v2_changed_reader_') as directory:
            with self.assertRaisesRegex(ValueError, 'Source/header/candidate changed'):
                self.fake_build(directory, change_reader=True)
            self.assertEqual(list(Path(directory).rglob('build-receipt.json')), [])

    def test_complete_readonly_surface_has_real_candidate_exports(self):
        builder.audit_readonly(builder.ALLOWED_IMPORTS | {'fwrite'}, builder.ALLOWED_IMPORTS | {'qemu_plugin_write_register'})

    def test_write_or_memory_access_or_missing_api_is_refused(self):
        for extra in ('qemu_plugin_write_register', 'qemu_plugin_set_pc', 'qemu_plugin_read_memory_vaddr'):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                builder.audit_readonly(builder.ALLOWED_IMPORTS | {extra}, builder.ALLOWED_IMPORTS | {extra})
        with self.assertRaises(ValueError):
            builder.audit_readonly(builder.ALLOWED_IMPORTS - {'qemu_plugin_read_register'}, builder.ALLOWED_IMPORTS)
        with self.assertRaises(ValueError):
            builder.audit_readonly(builder.ALLOWED_IMPORTS, builder.ALLOWED_IMPORTS - {'qemu_plugin_read_register'})

    def test_symbol_versions_do_not_hide_the_base_api(self):
        self.assertEqual(builder.symbols(' U qemu_plugin_read_register@VERSION\n U fwrite@GLIBC_2.2.5\n'),
                         {'qemu_plugin_read_register', 'fwrite'})


if __name__ == '__main__':
    unittest.main()
