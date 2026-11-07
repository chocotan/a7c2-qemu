#!/usr/bin/env python3
"""Host boundaries; set A7C2_P1_MODULE_TEST_STAGE to a real build receipt directory."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('p1_persistent_module', HERE / 'p1-persistent-module.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
REAL = os.environ.get('A7C2_P1_MODULE_TEST_STAGE')
PREVIOUS = os.environ.get('A7C2_P1_PREVIOUS_MODULE')


def sample_elf(*, vermagic=M.VERMAGIC, size=768, alignment=64, versions=False):
    names = ['.shstrtab', '.modinfo', '.gnu.linkonce.this_module']
    payloads = [b'', ('vermagic=' + vermagic + '\0license=GPL\0').encode(), bytes(size)]
    if versions:
        names.append('__versions'); payloads.append(bytes(8))
    strings = b'\0' + b'\0'.join(n.encode() for n in names) + b'\0'
    payloads[0] = strings
    result = bytearray(64)
    result[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', result, 16, 1, 183, 1)
    headers = [bytes(64)]
    for name, payload in zip(names, payloads):
        offset = len(result)
        result.extend(payload)
        headers.append(struct.pack('<IIQQQQIIQQ', strings.index(name.encode()), 1, 0, 0,
                                   offset, len(payload), 0, 0,
                                   alignment if name == '.gnu.linkonce.this_module' else 1, 0))
    struct.pack_into('<Q', result, 40, len(result))
    struct.pack_into('<HHH', result, 58, 64, len(headers), 1)
    result.extend(b''.join(headers))
    return bytes(result)


class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.kernel = self.root / 'kernel'
        self.kernel.write_bytes(b'unknown')
        self.modules = self.root / 'originals'
        self.modules.mkdir()

    def elf(self, **kwargs):
        path = self.root / 'sample.ko'
        path.write_bytes(sample_elf(**kwargs))
        return path

    def invoke(self, output=None):
        return M.build(self.source, output or self.root / 'out', original_p1_kernel=self.kernel,
                       original_module_directory=self.modules)

    def test_expected_elf_and_module_contract(self):
        info = M.module_info(self.elf())
        M.require_abi(info)
        self.assertEqual(info['license'], ['GPL'])
        self.assertEqual(info['struct_module_bytes'], 768)

    def test_unknown_module_abi_is_refused(self):
        for change in (dict(vermagic='4.9.337-scel+ SMP preempt mod_unload aarch64'),
                       dict(vermagic='4.9.186-scel aarch64'), dict(size=704),
                       dict(alignment=8), dict(versions=True)):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'Unknown/incompatible'):
                M.require_abi(M.module_info(self.elf(**change)))

    def test_malformed_and_wrong_architecture_elf_are_refused(self):
        raw = bytearray(sample_elf())
        for data in (b'', bytes(raw[:100]), b'not an ELF'):
            with self.assertRaises(ValueError):
                M.elf_sections(data)
        struct.pack_into('<H', raw, 18, 62)
        with self.assertRaises(ValueError):
            M.elf_sections(raw)

    def test_unknown_original_inventory_refused(self):
        with self.assertRaisesRegex(ValueError, 'exact 90'):
            M.original_modules(self.modules)

    def test_wrong_source_version_refused(self):
        makefile = self.source / 'Makefile'
        for value in ('337', '187', ''):
            makefile.write_text('VERSION = 4\nPATCHLEVEL = 9\nSUBLEVEL = ' + value + '\nEXTRAVERSION =\n')
            with self.assertRaisesRegex(ValueError, 'source kernel version'):
                M.verify_source(self.source)

    def test_wrong_source_config_pin_refused(self):
        (self.source / 'Makefile').write_text('VERSION = 4\nPATCHLEVEL = 9\nSUBLEVEL = 186\nEXTRAVERSION =\n')
        config = self.source / '.config'
        config.write_text('CONFIG_MODVERSIONS=y\n')
        with patch.object(M, 'SOURCE_PINS', {'.config': M.CONFIG_SHA}):
            with self.assertRaisesRegex(ValueError, 'source/config: .config'):
                M.verify_source(self.source)

    def test_other_source_tree_content_refused(self):
        (self.source / 'Makefile').write_text('VERSION = 4\nPATCHLEVEL = 9\nSUBLEVEL = 186\nEXTRAVERSION =\n')
        (self.source / 'untrusted-header.h').write_text('wrong\n')
        with patch.object(M, 'SOURCE_PINS', {}):
            with self.assertRaisesRegex(ValueError, 'source tree content'):
                M.verify_source(self.source)

    def test_source_outside_declared_tree_refused(self):
        outside = self.root / 'outside'
        outside.write_text('private\n')
        (self.source / 'header.h').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'outside declared tree'):
            M.tree_inventory(self.source)
        with self.assertRaisesRegex(ValueError, 'outside declared directory'):
            M.checked_path(str(self.source) + '/../outside')

    def test_file_and_parent_symlinks_refused(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.kernel)
        directory = self.root / 'directory'
        directory.symlink_to(self.source, target_is_directory=True)
        for path, kwargs in ((alias, {}), (directory, dict(directory=True)),
                             (directory / 'new', dict(missing=True))):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Symlink'):
                M.checked_path(path, **kwargs)

    def test_fresh_output_does_not_replace_existing_files(self):
        target = self.root / 'existing'
        target.mkdir()
        sentinel = target / 'keep'
        sentinel.write_bytes(b'keep me')
        with self.assertRaisesRegex(ValueError, 'Fresh output'):
            self.invoke(target)
        self.assertEqual(sentinel.read_bytes(), b'keep me')

    def test_output_must_not_overlap_source_or_original_modules(self):
        for target in (self.source / 'output', self.modules / 'output'):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'overlaps'):
                self.invoke(target)
            self.assertFalse(target.exists())

    def test_unknown_kernel_records_failure_without_running_tools(self):
        before = self.kernel.read_bytes()
        with patch.object(M, 'command', side_effect=AssertionError('compiler must not run')):
            receipt = self.invoke()
        self.assertEqual(receipt['status'], 'failed')
        self.assertIn('kernel identity', receipt['error'])
        self.assertEqual(self.kernel.read_bytes(), before)
        stored = json.loads((self.root / 'out/p1-persistent-module.json').read_text())
        self.assertEqual(stored, receipt)
        for key in ('guest_abi_verified', 'p1_installer_verified', 'installation_verified', 'capture_verified'):
            self.assertFalse(stored[key])

    def test_failed_command_keeps_raw_output_and_rc(self):
        receipt = dict(commands=[])
        with self.assertRaisesRegex(RuntimeError, 'rc=7'):
            M.command(['/bin/sh', '-c', 'echo preserved; echo problem >&2; exit 7'],
                      self.root, receipt, 'failure')
        self.assertEqual(receipt['commands'][0]['rc'], 7)
        self.assertEqual((self.root / 'failure.stdout').read_bytes(), b'preserved\n')
        self.assertEqual((self.root / 'failure.stderr').read_bytes(), b'problem\n')

    def test_config_disabled_values_are_compared_semantically(self):
        config = self.root / 'config'
        config.write_text('CONFIG_SMP=y\n# CONFIG_MODVERSIONS is not set\nCONFIG_LOCALVERSION=""\n')
        self.assertEqual(M.config_values(config), dict(CONFIG_SMP='y', CONFIG_MODVERSIONS='n', CONFIG_LOCALVERSION='""'))

    def test_current_driver_keeps_exact_source_pins(self):
        self.assertEqual(M.DRIVER_PINS['sony_persistent_flash.c'],
                         '15b6a84827a0d6e2925ea4fd6f9d17b6b820aedf0e6b790706b90ab4300b2b9f')
        for name, expected in M.DRIVER_PINS.items():
            self.assertEqual(M.record(HERE / 'persistent-flash' / name)['sha256'], expected)

    def test_unknown_image_never_gets_export_binding_from_strings(self):
        with self.assertRaisesRegex(ValueError, 'Unknown original p1 kernel'):
            M.original_exports(b'memcpy\0blk_queue_write_cache\0', ['memcpy'])


@unittest.skipUnless(REAL, 'set A7C2_P1_MODULE_TEST_STAGE for actual module checks')
class ActualBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stage = Path(REAL)
        cls.receipt = json.loads((cls.stage / 'p1-persistent-module.json').read_text())
        cls.module = Path(cls.receipt['module']['file']['path'])

    def test_real_kbuild_release_and_unchanged_reference_config(self):
        r = self.receipt
        self.assertEqual(r['status'], 'compiled')
        self.assertEqual((self.stage / 'kernel-build/include/config/kernel.release').read_text().strip(), M.RELEASE)
        self.assertIn(M.RELEASE, (self.stage / 'kernel-build/include/generated/utsrelease.h').read_text())
        self.assertEqual(M.record(self.stage / 'kernel-build/.config')['sha256'], M.CONFIG_SHA)
        self.assertEqual(r['config_derivation'][-1]['changes'], {})
        self.assertEqual(r['config_derivation'][-1]['release_argument'], 'LOCALVERSION=')

    def test_actual_module_modinfo_and_layout_match_readelf(self):
        info = M.module_info(self.module)
        M.require_abi(info)
        self.assertEqual(info, self.receipt['module'])
        self.assertEqual(M.record(self.module)['sha256'], self.receipt['module']['file']['sha256'])
        actual = subprocess.run(['aarch64-linux-gnu-readelf', '-p', '.modinfo', self.module],
                                capture_output=True, text=True, check=True).stdout
        self.assertIn('vermagic=' + M.VERMAGIC, actual)
        self.assertIn('license=GPL', actual)
        self.assertNotIn('4.9.337', actual)
        self.assertEqual(actual, (self.stage / 'module-modinfo.stdout').read_text())

    def test_real_undefined_symbols_are_actual_original_exports(self):
        r = self.receipt
        symbols = subprocess.run(['aarch64-linux-gnu-readelf', '-sW', self.module],
                                 capture_output=True, text=True, check=True).stdout
        self.assertEqual(symbols, (self.stage / 'module-symbols.stdout').read_text())
        required = sorted(set(M.re.findall(r'^\s*\d+:\s+\S+\s+\d+\s+\S+\s+GLOBAL\s+DEFAULT\s+UND\s+(\S+)\s*$', symbols, M.re.M)))
        self.assertEqual(required, r['undefined_symbols'])
        self.assertEqual(len(required), 34)
        self.assertEqual(len(r['exports']['required']), 34)
        self.assertIn('blk_queue_split', required)
        self.assertEqual(r['exports']['missing'], [])
        original = Path(r['original_kernel']['path']).read_bytes()
        self.assertEqual(M.original_exports(original, required), r['exports'])
        split = next(e for e in r['exports']['required'] if e['name'] == 'blk_queue_split')
        self.assertEqual(split['kind'], 'normal')
        self.assertEqual(split['entry_offset'], 0x5762b8)
        self.assertEqual(split['entry_hex'], 'f8cd220880ffffff0f53610880ffffff')
        gpl = [e['name'] for e in r['exports']['required'] if e['kind'] == 'GPL-only']
        self.assertEqual(gpl, ['blk_queue_write_cache'])
        self.assertEqual(r['module']['license'], ['GPL'])
        missing = M.original_exports(original, ['not_a_real_sony_export'])
        self.assertEqual(missing['status'], 'missing-exports')

    def test_original_ninety_modules_have_uniform_p1_abi(self):
        r = self.receipt['original_modules']
        self.assertEqual(r['count'], 90)
        self.assertEqual(r['inventory_sha256'], M.MODULES_SHA)
        for info in r['modules']:
            self.assertEqual(M.module_info(info['file']['path']), info)
            M.require_abi(info)
        self.assertIsNone(r['actual_kernel_config'])
        self.assertFalse(r['config_equivalence_verified'])

    def test_original_source_tree_rehash_and_driver_preservation(self):
        r = self.receipt
        source = Path(r['source']['path'])
        config_before = (source / '.config').stat()
        rows = M.verify_source(source)
        self.assertEqual(M.json_sha(rows), M.TREE_SHA)
        self.assertEqual(config_before, (source / '.config').stat())
        self.assertTrue(r['original_source_unchanged'])
        self.assertEqual(r['source_after_tree_sha256'], M.TREE_SHA)
        for name, expected in M.DRIVER_PINS.items():
            self.assertEqual(M.record(self.stage / 'module' / name)['sha256'], expected)
            self.assertEqual(M.record(HERE / 'persistent-flash' / name)['sha256'], expected)

    @unittest.skipUnless(PREVIOUS, 'set A7C2_P1_PREVIOUS_MODULE for the old 337 artifact comparison')
    def test_previous_337_artifact_is_preserved_and_has_distinct_abi(self):
        before = M.record(PREVIOUS)
        previous = M.module_info(PREVIOUS)
        self.assertEqual(previous['vermagic'], ['4.9.337-scel+ SMP preempt mod_unload aarch64'])
        self.assertNotEqual(previous['file']['sha256'], self.receipt['module']['file']['sha256'])
        with self.assertRaisesRegex(ValueError, 'Unknown/incompatible'):
            M.require_abi(previous)
        symbols = subprocess.run(['aarch64-linux-gnu-readelf', '-sW', PREVIOUS],
                                 capture_output=True, text=True, check=True).stdout
        required = sorted(set(M.re.findall(r'^\s*\d+:\s+\S+\s+\d+\s+\S+\s+GLOBAL\s+DEFAULT\s+UND\s+(\S+)\s*$', symbols, M.re.M)))
        self.assertEqual(len(required), 33)
        self.assertEqual(sorted(set(self.receipt['undefined_symbols']) - set(required)), ['blk_queue_split'])
        self.assertEqual(sorted(set(required) - set(self.receipt['undefined_symbols'])), [])
        self.assertEqual(M.record(PREVIOUS), before)

    def test_compilation_and_static_exports_keep_runtime_unknowns(self):
        r = self.receipt
        self.assertEqual(r['status'], 'compiled')
        self.assertEqual(r['exports']['status'], 'verified')
        for key in ('guest_abi_verified', 'p1_installer_verified', 'installation_verified', 'capture_verified',
                    'physical_devices_used', 'host_module_loaded', 'force_load_allowed'):
            self.assertFalse(r[key])
        self.assertIsNone(r['original_kernel_config'])
        self.assertFalse(r['exports']['full_abi_binding_verified'])
        self.assertEqual(r['exports']['function_signature_binding'], 'unknown')


if __name__ == '__main__':
    unittest.main()
