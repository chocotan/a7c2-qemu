#!/usr/bin/env python3
"""UNRUN candidate tests. Host files/C only; no updater build, VM, QMP or USB.

Run after overlaying this candidate on an independent full source copy. The known
Sony pair is referenced read-only by an external JSON selected with
A7C2_P1_DEV_IDENTITY_INPUTS; no private fixture is defaulted or embedded here.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-dev-receiver-identity.py'))
D = runpy.run_path(str(HERE / 'p1-dev-install.py'))
U = D['api']()


def selected(kind='fixed-system-file-v1'):
    return M['selection'](profile=M['PROFILE'], mode=M['MODE'], install_kind=kind,
        environment={'A7C2_FILE_MEDIA_TEST': '1', 'A7C2_P1_FILE_MEDIA_PROFILE': 'original-sd-v1',
                     'A7C2_P1_DEV_INSTALL': kind},
        authorization=M['PROFILE'] + ' ' + '1' * 64 + ' ' + '2' * 64 + '\n')


class Selection(unittest.TestCase):
    def test_default_stock_source_and_static_guards_remain_exact(self):
        stock = (HERE / 'file-media-config.c').read_bytes()
        self.assertEqual((len(stock), hashlib.sha256(stock).hexdigest()), M['STOCK_C'])
        sd = D['api']('p1-sd-read-probe.py')
        self.assertEqual(sd['HOOK_SHA'], M['STOCK_C'][1])
        self.assertEqual(sd['DSO_SHA'], '30925f265910eded6d95e7e7d9635b2f8e17272763b861377786cbe0d1c4c72a')
        self.assertEqual(D['api']('p1-file-media-contract.py')['SAMPLES']['sd'][1:], M['STOCK_RECEIVER'])
        self.assertIn(b'"' + M['STOCK_RECEIVER'][1].encode() + b'",236,', stock)
        self.assertNotIn(b'P1_DEV_MEDIA_PROFILE_FAILED', stock)

    def test_only_exact_explicit_profiles_and_kinds(self):
        for kind in M['KINDS']:
            self.assertEqual(selected(kind)['install_kind'], kind)
        value = selected()
        for changes in ({'profile': 'original-p1-virtual-install-v1'}, {'mode': 'official'},
                        {'install_kind': 'future-v2'}, {'install_kind': None},
                        {'authorization': value['authorization'][:-1]}, {'authorization': 'env-only'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                M['selection'](**dict(value, **changes))
        for field, bad in (('A7C2_FILE_MEDIA_TEST', 'true'), ('A7C2_P1_FILE_MEDIA_PROFILE', 'foreign'),
                           ('A7C2_P1_DEV_INSTALL', 'version-only-2.02')):
            env = dict(value['environment'], **{field: bad})
            with self.subTest(field=field), self.assertRaises(ValueError):
                M['selection'](**dict(value, environment=env))
        with patch.dict(os.environ, value['environment']):
            with self.assertRaises(ValueError):
                M['selection'](**dict(value, profile=None))

    def test_unknown_source_version_and_guard_tamper_fail_closed(self):
        stock = (HERE / 'file-media-config.c').read_bytes()
        for offset in (0, len(stock) // 2, len(stock) - 1):
            bad = bytearray(stock); bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'Unknown frozen'):
                M['_render'](bytes(bad), selected())

    def test_entire_generated_c_is_only_exact_hash_and_additional_rejecting_guard(self):
        stock = (HERE / 'file-media-config.c').read_bytes()
        for kind in M['KINDS']:
            generated = M['_render'](stock, selected(kind))
            marker = b'    if (!test_mode()) { *__errno_location()=saved_errno; return; }\n'
            start = generated.index(marker) + len(marker)
            stop = generated.index(b'    struct media_dl_info info;\n', start)
            guard = generated[start:stop]
            self.assertIn(b'P1_DEV_MEDIA_PROFILE_FAILED', guard)
            self.assertIn(b'_exit(126)', guard)
            self.assertIn(kind.encode(), guard)
            for name, value in M['runtime_texts'](selected(kind)).items():
                self.assertIn(('/' + name).encode(), guard)
                self.assertIn(hashlib.sha256(value.encode('ascii')).hexdigest().encode(), guard)
            restored = generated[:start] + generated[stop:]
            restored = restored.replace(('"' + M['DEV_RECEIVER'][1] + '",236,').encode(),
                                        ('"' + M['STOCK_RECEIVER'][1] + '",236,').encode())
            self.assertEqual(restored, stock)
            self.assertIn(b'P1_BODY_IDENTITY_FAILED', generated)
            self.assertIn(b'if(p1 && (after || omit))', generated)

    def test_default_builder_uses_exact_stock_argv_and_never_imports_dev_adapter(self):
        tree = ast.parse((HERE / 'update-boot.py').read_text())
        block = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
            and ast.unparse(node.test) == "report['sd'] is not None"
            and any(isinstance(n, ast.Constant) and n.value == 'file-media-build' for n in ast.walk(node)))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'root'; (root / 'etc').mkdir(parents=True); sim = root / 'simulation'; sim.mkdir()
            calls = []
            def command(argv, output, name):
                calls.append([str(a) for a in argv]); return {'argv': calls[-1], 'rc': 0}
            values = dict(U, root=root, simulation=sim, output=Path(td), install_profile=None,
                report={'sd': {}, 'commands': [], 'p2': {'sd_dispatch_eligible': True}},
                command=command, record=lambda p: {'path': str(p)}, install_api={})
            exec(compile(ast.Module(body=[block], type_ignores=[]), '<stock-file-media-route>', 'exec'), values)
            expected = ['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
                '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC', str(HERE / 'file-media-config.c'),
                *[str(root / 'lib' / n) for n in M['LIBRARIES']], '-o', str(sim / 'file-media-config.so')]
            self.assertEqual(calls, [expected])
            self.assertNotIn('identity_adapter', values['report']['file_media'])
            self.assertEqual((root / 'etc/ld.so.preload').read_bytes(), b'/simulation/file-media-config.so\n')

    def test_unknown_package_schema_kind_and_versions_do_not_select_adapter(self):
        for value in ({'schema': 'future'}, {'schema': D['FILE_PACKAGE_SCHEMA'], 'kind': 'future'},
                      {'schema': D['PACKAGE_SCHEMA'], 'delta': 'version-only-2.03'}):
            with self.assertRaises(ValueError):
                D['install_environment']({'package_contract': {'value': value}})
        update = dict(install_profile=D['PROFILE'], mode=D['MODE'], allow_dev_signature_bypass=True,
            read_only=False, allow_updater_writes=True, bypass_configured=True,
            virtual_install={'profile': D['PROFILE'], 'receipt': {'sha256': '1' * 64},
                'value': {'clone': {'sha256': '2' * 64}},
                'package_contract': {'value': dict(schema=D['PACKAGE_SCHEMA'], delta='version-only-2.02',
                    profile=D['PROFILE'], mode=D['MODE'], original_version='2.01', new_version='2.02',
                    current_version='2.01', virtual_only=True)}})
        self.assertEqual(D['file_media_selection'](update), selected('version-only-2.02'))
        for key, value in (('new_version', '2.03'), ('current_version', '2.02'), ('original_version', '2.00')):
            bad = copy.deepcopy(update); bad['virtual_install']['package_contract']['value'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): D['file_media_selection'](bad)
        for key in ('tail_profile', 'newdecrypt_profile', 'pmbp_profile', 'pmbp'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                D['file_media_selection'](dict(update, **{key: 'selected'}))

    def test_source_output_is_fresh_and_never_follows_a_symlink_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); ordinary = root / 'ordinary'; ordinary.mkdir()
            target = ordinary / 'source.c'; M['_fresh'](target, b'candidate')
            with self.assertRaises(FileExistsError): M['_fresh'](target, b'overwrite')
            self.assertEqual(target.read_bytes(), b'candidate')
            alias = root / 'alias'; alias.symlink_to(ordinary, target_is_directory=True)
            with self.assertRaises(OSError): M['_fresh'](alias / 'escaped.c', b'candidate')
            self.assertFalse((ordinary / 'escaped.c').exists())
            with self.assertRaises(ValueError):
                M['prepare'](root / 'wrong', {'output': str(root)}, root, selected=selected())

    def test_private_fixture_selection_is_explicit(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'read_bytes', side_effect=AssertionError('private read without opt-in')):
            with self.assertRaisesRegex(unittest.SkipTest, 'never defaulted'):
                KnownReceiver.setUpClass()
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / 'absent.json'
            with patch.dict(os.environ, A7C2_P1_DEV_IDENTITY_INPUTS=str(missing)):
                with self.assertRaisesRegex(ValueError, 'missing or not valid JSON'):
                    KnownReceiver.setUpClass()

    def test_e_manifest_and_u_sources_route_is_explicit_and_preflighted(self):
        u = (HERE / 'update-boot.py').read_text(); e = (HERE / 'p1-update-execution.py').read_text()
        self.assertIn("'p1-dev-receiver-identity.py')", u)
        self.assertIn("report['sd_read_observation']['sources'].append(record(file_media_source))", u)
        self.assertIn("manifest['file_media'] = update['file_media']", e)
        self.assertIn("manifest.get('file_media') != update.get('file_media')", e)
        self.assertIn("file_media_preflight(root, update)", (HERE / 'p1-dev-install.py').read_text())


class KnownReceiver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get('A7C2_P1_DEV_IDENTITY_INPUTS')
        if not selected:
            raise unittest.SkipTest('A7C2_P1_DEV_IDENTITY_INPUTS not set; the known-pair fixture is external and never defaulted')
        try:
            fixture = json.loads(Path(selected).read_bytes())
        except (OSError, ValueError) as error:
            raise ValueError('A7C2_P1_DEV_IDENTITY_INPUTS is missing or not valid JSON: ' + str(error)) from error
        if (not isinstance(fixture, dict) or fixture.get('schema') != 'a7c2-p1-dev-receiver-identity-test-inputs-v1'
                or fixture.get('private_inputs_read_only') is not True
                or fixture.get('fixture_contains_firmware_bytes') is not False):
            raise ValueError('External identity fixture schema/read-only declaration differs')
        project = next((p for p in HERE.parents if (p / 'AGENTS.md').is_file() and (p / 'analysis/scratch').is_dir()), None)
        try:
            paths = [Path(fixture['original']['path']), Path(fixture['derived']['path']), Path(fixture['receiver_receipt'])]
            if any(not p.is_absolute() for p in paths) and project is None:
                raise ValueError('Relative external identity fixture path requires the project root')
            cls.original, cls.derived, receipt = [p if p.is_absolute() else project / p for p in paths]
            declared = [tuple(fixture[key][k] for k in ('bytes', 'sha256')) for key in ('original', 'derived')]
        except (KeyError, TypeError) as error:
            raise ValueError('External identity fixture layout differs: ' + str(error)) from error
        if declared != [M['STOCK_RECEIVER'], M['DEV_RECEIVER']]:
            raise ValueError('External identity fixture does not pin the known DEV receiver pair')
        if not all(p.is_file() for p in (cls.original, cls.derived, receipt)):
            raise ValueError('External identity fixture files are absent; keep this coverage unverified')
        cls.update = json.loads(receipt.read_bytes()); cls.receipt = cls.update['receiver']
        for key, path in (('original', cls.original), ('derived', cls.derived)):
            if M['facts'](path.read_bytes()) != {k: fixture[key][k] for k in ('bytes', 'sha256')}:
                raise ValueError('Private known-pair fixture drift: ' + key)

    def derive(self, *, derived=None, original=None, receipt=None):
        return M['derive'](HERE / 'file-media-config.c', original or self.original, derived or self.derived,
                           receipt or self.receipt, selected=selected())

    def test_exact_existing_pair_inverse_and_initialize_window(self):
        text, proof = self.derive()
        self.assertEqual(M['facts'](text), proof['generated_source'])
        self.assertEqual(proof['receiver']['sha256'], M['DEV_RECEIVER'][1])
        self.assertEqual(proof['inverse']['original_sha256'], M['STOCK_RECEIVER'][1])
        self.assertEqual(proof['initialize']['sha256'], M['INITIALIZE'][2])
        self.assertTrue(proof['inverse']['all_other_bytes_identical'])
        for flag in ('bypass_executed', 'installation_verified', 'coverage', 'source_coverage_complete'):
            self.assertIs(proof[flag], False)

    def test_offset_tamper_foreign_elf_original_and_receipt_rejected(self):
        data = self.derived.read_bytes()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'receiver'
            for offset in (0, 18, 0xa758, 0xae08, 0xae0c, len(data) - 1):
                bad = bytearray(data); bad[offset] ^= 1; path.write_bytes(bad)
                with self.subTest(offset=offset), self.assertRaises(ValueError): self.derive(derived=path)
            path.write_bytes(data[:-1])
            with self.assertRaises(ValueError): self.derive(derived=path)
            path.write_bytes(self.original.read_bytes())
            with self.assertRaises(ValueError): self.derive(derived=path)
            path.write_bytes(data)
            with self.assertRaises(ValueError): self.derive(original=path)
            for field, value in (('mode', 'official'), ('bypass_executed', True), ('virtual_only', False)):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    self.derive(receipt=dict(self.receipt, **{field: value}))
            path.unlink(); path.symlink_to(self.derived)
            with self.assertRaises(OSError): self.derive(derived=path)

    def test_abi_observer_keeps_code_and_labels_actual_receiver(self):
        # The production _stock_contract first validates all six native pins.
        pins = [dict(path='/usr/lib/libsdfileinputupdaterapi.so' if i < 3 else '/usr/lib/other.so',
                     sha256=M['STOCK_RECEIVER'][1] if i < 3 else '0' * 64, code='01020304', va=i)
                for i in range(6)]
        original = dict(schema='p1-sd-initialize-passive-v1', pins=pins, core={'opaque': 1})
        actual = M['observer_contract'](original)
        self.assertEqual(original['pins'], pins)
        for before, after in zip(original['pins'], actual['pins']):
            self.assertEqual({k: v for k, v in before.items() if k != 'sha256'},
                             {k: v for k, v in after.items() if k != 'sha256'})
            self.assertEqual(after['sha256'], M['DEV_RECEIVER'][1] if before['path'].endswith('libsdfileinputupdaterapi.so') else before['sha256'])

    @unittest.skipUnless(shutil.which('gcc'), 'host C compiler absent; keep full-C execution UNRUN')
    def test_full_generated_c_runtime_profile_guard_and_exact_receiver_symbol(self):
        text, _ = self.derive()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'p1-dev-file-media-config.c').write_bytes(text)
            (root / 'simulation').mkdir()
            for name, value in M['runtime_texts'](selected()).items():
                (root / name).write_text(value, encoding='ascii')
            executable = root / 'guard'
            subprocess.run(['gcc', '-O0', '-Wall', '-Wextra', '-Werror', '-pthread', '-I', str(root),
                str(HERE / 'test-support/p1-dev-receiver-identity.c'), '-ldl', '-o', str(executable)],
                check=True, capture_output=True, timeout=60)
            def run(mode, fixture_root=root):
                return subprocess.run([str(executable), str(fixture_root), str(self.derived), str(self.original), mode],
                                      capture_output=True, timeout=10)
            for mode in ('symbol', 'off'):
                result = run(mode); self.assertEqual(result.returncode, 0, result.stderr)
            result = run('correct')
            self.assertEqual(result.returncode, 126)
            self.assertIn(b'P1_BODY_IDENTITY_FAILED', result.stdout)
            self.assertNotIn(b'P1_DEV_MEDIA_PROFILE_FAILED', result.stdout)
            for mode in ('wrong-profile', 'wrong-kind'):
                result = run(mode); self.assertEqual(result.returncode, 126)
                self.assertIn(b'P1_DEV_MEDIA_PROFILE_FAILED', result.stdout)
            for name in M['runtime_texts'](selected()):
                path = root / name; saved = path.read_bytes(); path.write_bytes(saved + b'!')
                result = run('correct'); self.assertEqual(result.returncode, 126)
                self.assertIn(b'P1_DEV_MEDIA_PROFILE_FAILED', result.stdout); path.write_bytes(saved)
            empty = root / 'empty'; empty.mkdir()
            result = run('env-only', empty)
            self.assertEqual(result.returncode, 126)
            self.assertIn(b'P1_DEV_MEDIA_PROFILE_FAILED', result.stdout)


@unittest.skipUnless(os.environ.get('A7C2_P1_DEV_MEDIA_TEST_UPDATE'),
                     'fresh derived U build receipt required; producer/CPIO tests remain UNRUN')
class BuiltReadback(unittest.TestCase):
    def test_fresh_u_e_whole_c_dso_provenance_and_cpio_tamper(self):
        # This uses a fresh central build, never the failed v34 stock-hook artifacts.
        update = json.loads(Path(os.environ['A7C2_P1_DEV_MEDIA_TEST_UPDATE']).read_bytes())
        value = D['file_media_selection'](update); source_root = Path(update['output']) / 'root'
        M['verify'](source_root, update, selected=value)
        names = list(M['RUNTIME_FILES']) + list(M['runtime_texts'](value))
        names += ['simulation/file-media-config.so', 'usr/lib/libsdfileinputupdaterapi.so']
        names += ['lib/' + name for name in M['LIBRARIES']]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'root'; root.mkdir()
            for name in names:
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_root / name, target)
                target.chmod(source_root.joinpath(name).stat().st_mode & 0o777)
            self.assertEqual(M['verify'](root, update, selected=value), update['file_media']['identity_adapter'])
            for name in (M['SOURCE'], M['CONTRACT'], 'simulation/file-media-config.so',
                         'simulation/sd-read-env', 'usr/lib/libsdfileinputupdaterapi.so', 'lib/libc-2.25.so'):
                path = root / name; saved = path.read_bytes()
                path.write_bytes(saved + b'!')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    M['verify'](root, update, selected=value)
                path.write_bytes(saved)
            for key in ('source', 'output'):
                bad = copy.deepcopy(update); bad['file_media'][key]['sha256'] = '0' * 64
                with self.subTest(key=key), self.assertRaises(ValueError):
                    M['verify'](root, bad, selected=value)
            bad = copy.deepcopy(update)
            bad['file_media']['identity_adapter']['command']['argv'][0] = '/unknown/compiler'
            with self.assertRaises(ValueError): M['verify'](root, bad, selected=value)
            expected = {name: dict(M['facts']((root / name).read_bytes()), mode=(root / name).stat().st_mode)
                        for name in names}
            import gzip
            archive = Path(td) / 'readback.cpio.gz'
            with gzip.open(archive, 'wb') as stream:
                for name, row in expected.items():
                    U['cpio_entry'](stream, name, row['mode'], row['bytes'], root / name)
                U['cpio_entry'](stream, 'TRAILER!!!', 0)
            self.assertEqual(D['cpio_readback'](archive, expected), expected)
            broken = copy.deepcopy(expected); broken[M['SOURCE']]['sha256'] = '0' * 64
            with self.assertRaises(ValueError): D['cpio_readback'](archive, broken)
            with archive.open('ab') as raw, gzip.GzipFile(fileobj=raw, mode='wb') as stream:
                row = expected[M['CONTRACT']]
                U['cpio_entry'](stream, M['CONTRACT'], row['mode'], row['bytes'], root / M['CONTRACT'])
                U['cpio_entry'](stream, 'TRAILER!!!', 0)
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                D['cpio_readback'](archive, expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
