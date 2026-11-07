#!/usr/bin/env python3
"""Public pure-host routing checks; synthetic files/AST stages never attest guest ABI or installation."""
import ast
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
U = runpy.run_path(str(HERE / 'update-boot.py'))
E = runpy.run_path(str(HERE / 'p1-update-execution.py'))
SD = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
CBC = runpy.run_path(str(HERE / 'p1-cbc-functional-provider.py'))
PROFILE = CBC['PROFILE']
STOCK = SD['INSTALL_PROFILE']
TRUST = SD['TRUST_PROFILE']
LEGACY_SOURCES = ('update-boot.py', 'p1-sd-read-probe.py', 'p1-file-media-contract.py',
                  'file-media-config.c', 'guest/update-storage-bootstrap', 'newp1-virtual-install.py')


def stage(file, predicate, environment):
    # Match one production AST stage, as in the existing DEV preservation regression.
    tree = ast.parse((HERE / file).read_text())
    nodes = [n for n in ast.walk(tree) if predicate(n)]
    if len(nodes) != 1:
        raise AssertionError((file, len(nodes)))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<synthetic-host-routing-stage>', 'exec'), environment)


class Routing(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='p1-cbc-routing-')
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name)
        self.root = self.out / 'root'
        (self.root / 'simulation').mkdir(parents=True)
        (self.root / 'etc').mkdir()
        (self.root / 'usr/lib').mkdir(parents=True)
        (self.root / 'lib').mkdir()
        self.base = (HERE / 'guest/update-storage-bootstrap').read_bytes()
        (self.root / 'init').write_bytes(self.base)
        (self.root / 'init').chmod(0o755)
        (self.root / 'etc/ld.so.preload').write_text(SD['PRELOAD'])
        for name in ('usr/lib/libcrypto.so.1.1', 'lib/libpthread-2.25.so'):
            (self.root / name).write_bytes(b'SYNTHETIC library input, no guest ABI claim\n')
        self.pin = self.out / 'independent.pem'
        self.pin.write_bytes(b'SYNTHETIC pinned PEM boundary fixture\n')
        self.pin.chmod(0o444)
        self.package = self.out / 'synthetic-package'
        self.package.write_bytes(b'SYNTHETIC package, not official BODYDATA\n')
        self.model = runpy.run_path(str(HERE / 'p1-cbc-functional-provider.py'))
        self.native = dict(schema='p1-trust-key-abi-v1', files={}, pins=[],
                           passive=dict(windows=[{}] * 4, log_budget=dict(total=128, pin_identity=32, observations=96)))
        self.initializer = dict(pins=[])
        self.model['prepare'].__globals__.update(
            package_contract=lambda p: dict(CBC['record'](p), synthetic=True),
            sd_api=lambda: dict(trust_contract=lambda r: self.native,
                               initialize_contract=lambda r: self.initializer,
                               binding_texts=SD['binding_texts'], cpio_readback=SD['cpio_readback']))
        self.calls = []
        self.preflights = []
        self.report = dict(mode='official', install_profile=STOCK, read_only=False,
            original_resources=dict(synthetic=True), bootstrap=U['record'](self.root / 'init'),
            sd=dict(image=dict(bytes=1, sha256='0' * 64)), sd_read_package_source=U['record'](self.package),
            trust_selection=dict(profile=TRUST, pinned_key=U['record'](self.pin)), output=str(self.out))
        self.names = ['init', 'etc/ld.so.preload', 'simulation/p1-sd-observer.so',
                      'simulation/sd-read-bindings', 'simulation/sd-read-binding-count']
        self.sd = dict(SD, configure=self.configure, bindings=self.bindings,
            trust_preflight=lambda root, value: value, newdecrypt_api=lambda: self.model,
            initialize_contract=lambda root: self.initializer, trust_contract=lambda root: self.native,
            observer_source=lambda *args, **kwargs: self.emitted(kwargs.get('newdecrypt')),
            _pinned_snapshot=lambda p: Path(p).read_bytes(), preflight=self.preflight)
        real_load = runpy.run_path
        def load(path, *args, **kwargs):
            if Path(path).name == 'p1-sd-read-probe.py':
                return self.sd
            if Path(path).name == 'p1-trusted-key-model.py':
                raise AssertionError('CBC must keep the SDK observer instead of emitting the legacy observer')
            return real_load(path, *args, **kwargs)
        self.loader = patch.object(runpy, 'run_path', side_effect=load)

    @staticmethod
    def emitted(decrypt):
        return 'SYNTHETIC generated observer; selected=' + str(decrypt is not None) + '\n'

    def configure(self, root, report, output, **options):
        self.calls.append(options)
        chosen = options.get('newdecrypt_profile')
        decrypt = self.model['prepare'](root, output, profile=chosen, package_source=self.package) if chosen else None
        if decrypt:
            self.names += list(CBC['RUNTIME'])
        source = output / 'p1-sd-observer.c'
        source.write_text(self.emitted(decrypt))
        (root / 'simulation/p1-sd-observer.so').write_bytes(b'SYNTHETIC compiler output\n')
        if decrypt:
            self.model['finish'](root, output, decrypt)
        trust = dict(profile=options.get('trust_profile'), contract=self.native,
                     sources=[U['record'](HERE / n) for n in SD['TRUST_SOURCES']],
                     environment=SD['effective_env'](options.get('trust_profile'), newdecrypt_profile=chosen))
        if options.get('trust_profile'):
            trust['sources'].append(U['record'](self.pin))
            runtime = root / 'simulation/p1-trust-key'
            runtime.mkdir()
            (runtime / 'sony-original.pem').write_bytes(self.pin.read_bytes())
        if decrypt:
            trust['newdecrypt'] = decrypt
        rows = sorted([U['record'](root / n) for n in list(CBC['RUNTIME']) + ['simulation/p1-sd-observer.so']]
                      if decrypt else [U['record'](root / 'simulation/p1-sd-observer.so')], key=lambda r: r['path'])
        for name, text in SD['binding_texts'](root, rows).items():
            (root / name).write_text(text)
        return dict(trust_key=trust, observer_source=U['record'](source),
                    observer=U['record'](root / 'simulation/p1-sd-observer.so'), bindings=rows,
                    initialize_contract=self.initializer)

    def bindings(self, root, card):
        return {n: dict(mode=(root / n).lstat().st_mode, **CBC['record'](root / n)) for n in self.names}

    def preflight(self, update, root, read_only, media, profile):
        self.preflights.append(update)
        value = update['sd_read_observation']
        rows = [dict(r, path=str(root / Path(r['path']).relative_to(Path(update['output']) / 'root')))
                for r in value['bindings']]
        self.model['preflight'](root, value['trust_key']['newdecrypt'], rows=rows,
                              cpio_path=update['initrd']['path'], cpio_bindings=value['cpio_bindings'])
        return value

    def configure_stage(self, selected):
        if selected:
            self.report['newdecrypt_profile'] = PROFILE
        env = dict(U, root=self.root, report=self.report, output=self.out, sd_api=self.sd,
                   sd_read_profile=None, install_profile=STOCK, trust_profile=TRUST if selected else None,
                   pinned_key=self.pin if selected else None, newdecrypt_profile=PROFILE if selected else None,
                   tail_profile=None, tail_body_root=None)
        with self.loader:
            stage('update-boot.py', lambda n: isinstance(n, ast.If) and n.body and
                  isinstance(n.body[0], ast.Assign) and
                  ast.unparse(n.body[0].targets[0]) == "report['sd_read_observation']", env)
        return env

    def sources_stage(self, env):
        archive = self.out / 'input.cpio.gz'
        U['archive'](self.root, archive)
        self.report['initrd'] = U['record'](archive)
        env['initrd'] = archive
        with self.loader:
            stage('update-boot.py', lambda n: isinstance(n, ast.If) and n.body and
                  isinstance(n.body[0], ast.Assign) and
                  ast.unparse(n.body[0].targets[0]) == "report['sd_read_observation']['cpio_readback']", env)

    def test_cli_default_none_and_explicit_forward_and_unknown_rejection(self):
        captured = []
        def build(*args, **kwargs):
            captured.append(kwargs)
            return dict(status='built', output='synthetic', blockers=[])
        args = ['update-boot.py', '--instance', 'unused', '--runtime-analysis', 'unused',
                '--output', 'unused', '--mode', 'official']
        with patch.dict(U['main'].__globals__, build=build), redirect_stdout(io.StringIO()):
            for tail, expected in (([], None), (['--newdecrypt-profile', PROFILE], PROFILE)):
                with patch('sys.argv', args + tail):
                    self.assertEqual(U['main'](), 0)
                    self.assertEqual(captured[-1]['newdecrypt_profile'], expected)
            with patch('sys.argv', args + ['--newdecrypt-profile', 'unknown']), redirect_stdout(io.StringIO()), \
                    patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                U['main']()
        self.assertEqual(len(captured), 2)

    def test_early_admission_rejects_mixed_profiles_without_output(self):
        options = dict(mode='official', original_resources=True, install_profile=STOCK, read_only=False,
                       allow_updater_writes=True, trust_profile=TRUST, pinned_key=self.pin,
                       newdecrypt_profile=PROFILE, media_resources=self.out / 'media.json', bodydata=self.package,
                       install_receipt=self.out / 'clone.json', install_receipt_sha256='0' * 64)
        for name, value in (('newdecrypt_profile', 'unknown'), ('install_profile', 'original-p1-virtual-dev-install-v1'),
                            ('install_profile', None), ('read_only', True), ('read_only', 0),
                            ('mode', 'virtual-dev-sd-update-v1'), ('original_resources', False),
                            ('trust_profile', None), ('trust_profile', 'unknown'), ('pinned_key', None),
                            ('trusted_key_model', dict(profile='unknown')), ('allow_updater_writes', False)):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                U['build'](self.out / 'unused-instance', self.out / 'runtime', self.out / 'not-created',
                           **dict(options, **{name: value}))
            self.assertFalse((self.out / 'not-created').exists())
        # Exercise real fixed-PEM validation before output, not a caller-authored trust boolean.
        with self.assertRaisesRegex(ValueError, '451B PEM'):
            U['build'](self.out / 'instance', self.out / 'runtime', self.out / 'not-created', **options)
        self.pin.chmod(0o600)
        self.pin.write_bytes(b'x' * 451)
        self.pin.chmod(0o444)
        with self.assertRaisesRegex(ValueError, 'content or identity'):
            U['build'](self.out / 'instance', self.out / 'runtime', self.out / 'not-created', **options)
        with self.assertRaisesRegex(ValueError, 'readable independent fixed pinned PEM'):
            U['build'](self.out / 'instance', self.out / 'runtime', self.out / 'not-created',
                       **dict(options, pinned_key=self.out / 'missing.pem'))
        self.assertFalse((self.out / 'not-created').exists())

    def test_legacy_trust_dispatch_and_missing_declared_contract(self):
        old = dict(sd_read_observation=dict(trust_key={}))
        calls = []
        legacy = dict(preflight_stock=lambda *args: calls.append(args) or 'legacy')
        with patch.object(runpy, 'run_path', side_effect=lambda p: self.sd if Path(p).name == 'p1-sd-read-probe.py' else legacy):
            self.assertEqual(U['stock_trust_preflight'](old, self.root), 'legacy')
            self.assertEqual(calls, [(old, self.root)])
            with self.assertRaisesRegex(ValueError, 'lacks its built observer'):
                U['stock_trust_preflight'](dict(old, newdecrypt_profile=PROFILE), self.root)

    def test_default_keeps_bootstrap_and_exact_legacy_source_rows(self):
        old = copy.deepcopy(self.report['bootstrap'])
        env = self.configure_stage(False)
        self.sources_stage(env)
        self.assertEqual(self.report['bootstrap'], old)
        self.assertEqual((self.root / 'init').read_bytes(), self.base)
        self.assertIsNone(self.calls[0]['newdecrypt_profile'])
        self.assertEqual(self.calls[0], dict(profile=STOCK, trust_profile=None, pinned_key=None, newdecrypt_profile=None))
        expected = [U['record'](HERE / n) for n in LEGACY_SOURCES]
        expected += self.report['sd_read_observation']['trust_key']['sources']
        expected += [U['record'](self.out / 'p1-sd-observer.c')]
        self.assertEqual(self.report['sd_read_observation']['sources'], expected)
        self.assertNotIn('newdecrypt_profile', self.report)
        self.assertFalse((self.root / 'simulation/p1-cbc-model').exists())

    def test_explicit_stock_updates_bootstrap_and_precise_compiler_inputs(self):
        old = copy.deepcopy(self.report['bootstrap'])
        env = self.configure_stage(True)
        self.assertEqual(self.calls[0], dict(profile=STOCK, trust_profile=TRUST, pinned_key=self.pin,
                                             newdecrypt_profile=PROFILE))
        self.assertEqual(self.report['bootstrap'], U['record'](self.root / 'init'))
        self.assertNotEqual(self.report['bootstrap']['sha256'], old['sha256'])
        self.assertEqual((self.root / 'init').read_text(),
                         CBC['bootstrap_source'](self.base.decode(), CBC['selection'](PROFILE)))
        self.sources_stage(env)
        value = self.report['sd_read_observation']
        paths = [r['path'] for r in value['sources']]
        expected = {str(HERE / n) for n in LEGACY_SOURCES + SD['TRUST_SOURCES'] + CBC['SOURCES']}
        expected |= {str(self.pin), str(self.out / 'p1-sd-observer.c'),
                     str(self.out / 'p1-cbc/p1_cbc_runtime_binding.h'),
                     str(self.root / 'usr/lib/libcrypto.so.1.1'), str(self.root / 'lib/libpthread-2.25.so')}
        self.assertEqual(set(paths), expected)
        self.assertEqual(len(paths), len(expected))
        for row in value['sources']:
            self.assertEqual(row, U['record'](row['path']))
        self.assertTrue(set(CBC['RUNTIME']).issubset(value['cpio_readback']))
        self.assertTrue(all(set(row) == {'path', 'bytes', 'sha256'} for row in value['bindings']))
        self.assertEqual([row['path'] for row in value['bindings']], sorted(row['path'] for row in value['bindings']))
        self.assertFalse(self.report['trust_execution']['signature_verified'])
        with self.loader:
            U['stock_trust_preflight'](self.report, self.root)
            source = self.out / 'p1-sd-observer.c'
            source.write_text('wrong generated source')
            with self.assertRaisesRegex(ValueError, 'source/environment'):
                U['stock_trust_preflight'](self.report, self.root)

        header = self.out / 'p1-cbc/p1_cbc_runtime_binding.h'
        header.write_bytes(header.read_bytes() + b'!')
        (self.out / 'input.cpio.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'compiled pin'):
            self.sources_stage(env)

    def test_clone_preserves_selection_and_reads_derived_cpio(self):
        env = self.configure_stage(True)
        self.sources_stage(env)
        update = self.report
        root = self.out / 'execution-root'
        shutil.copytree(self.root, root)
        value = update['sd_read_observation']
        state = dict(E, UPDATE=U, update=update, root=root, sd_api=self.sd, dev_install=False,
                     decrypt_profile=PROFILE, decrypt=value['trust_key']['newdecrypt'],
                     tail_profile=None, pmbp_contract=None)
        with self.loader:
            stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and ast.unparse(n.test) == 'dev_install'
                  and isinstance(n.body[0], ast.Assign) and ast.unparse(n.body[0].targets[0]) == 'environment', state)
            stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and ast.unparse(n.test) == 'decrypt_profile is not None'
                  and isinstance(n.body[0], ast.Assign) and ast.unparse(n.body[0].targets[0]) == 'expected_bootstrap', state)
            stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and
                  ast.unparse(n.test) == "(root / 'init').read_bytes() != expected_bootstrap", state)
        self.assertEqual(state['expected_bootstrap'], (root / 'init').read_bytes())
        for name in ('block-readonly', 'media-backup-query', 'media-profile', 'original-modules',
                     'backup-file-source', 'install-target', 'backup-trusted-file-load'):
            (root / 'simulation' / name).write_bytes(b'SYNTHETIC execution helper\n')
        archive = self.out / 'execution.cpio.gz'
        U['archive'](root, archive)
        state.update(initrd=archive, card=update['sd']['image'], install_profile=STOCK, sd_read_profile=None,
                     sd_observation=value, read_only=False, media=dict(synthetic=True), resources=dict(modules=[]))
        stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and n.body and
              isinstance(n.body[0], ast.Assign) and ast.unparse(n.body[0].targets[0]) == 'expected_cpio', state)
        derived = self.preflights[-1]
        self.assertEqual(derived['newdecrypt_profile'], PROFILE)
        self.assertEqual(derived['sd_read_observation']['trust_key'], value['trust_key'])
        self.assertEqual(derived['initrd']['path'], str(archive))
        self.assertNotEqual(derived['initrd']['path'], update['initrd']['path'])
        self.assertEqual(derived['sd_read_observation']['cpio_bindings'], state['sd_cpio'])
        self.assertEqual((root / 'simulation/sd-read-binding-count').read_text(), str(len(value['bindings'])) + '\n')
        for name in CBC['RUNTIME']:
            self.assertEqual((root / name).read_bytes(), (self.root / name).read_bytes())
        # The new archive is consumed: a damaged payload is rejected even though old U stays intact.
        path = root / CBC['RUNTIME'][1]
        original = path.read_bytes()
        path.write_bytes(original + b'!')
        corrupt = self.out / 'corrupt.cpio.gz'
        U['archive'](root, corrupt)
        path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'CPIO binding differs'):
            self.preflight(dict(derived, initrd=U['record'](corrupt)), root, False, {}, STOCK)
        # A missing declaration cannot infer the selected profile from installed files.
        selection = dict(state, install_profile=STOCK, trust_profile=TRUST, pinned_key=self.pin,
                         trusted_key_model=None, update=dict(update))
        selection['update'].pop('newdecrypt_profile')
        stage('p1-update-execution.py', lambda n: isinstance(n, ast.Assign) and
              any(ast.unparse(t) == 'decrypt_profile' for t in n.targets), selection)
        with self.assertRaisesRegex(ValueError, 'Declared CBC selection'):
            stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and
                  isinstance(n.test, ast.Compare) and ast.unparse(n.test).endswith('!= decrypt_profile'), selection)
        # actual() must rebase its SD preflight context to the execution archive as well.
        shutil.copyfile(archive, self.out / 'probe.cpio.gz')
        manifest = dict(output=str(self.out), sd_read_observation=state['sd_observation'])
        state['manifest'] = manifest
        stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and n.body and
              isinstance(n.body[0], ast.Assign) and
              ast.unparse(n.body[0].targets[0]) == "manifest['newdecrypt_profile']", state)
        self.assertEqual(manifest['newdecrypt_profile'], PROFILE)
        actual = dict(E, UPDATE=U, update=update, manifest=manifest)
        stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and
              ast.unparse(n.test) == "manifest.get('newdecrypt_profile') != update.get('newdecrypt_profile')", actual)
        stage('p1-update-execution.py', lambda n: isinstance(n, ast.If) and
              ast.unparse(n.test) == ("manifest.get('newdecrypt_profile') is not None or "
                                     "manifest.get('tail_profile') is not None or manifest.get('pmbp') is not None"), actual)
        self.assertEqual(actual['update']['initrd']['path'], str(self.out / 'probe.cpio.gz'))


# Keep the existing independent 60600-byte original / four-byte-only DEV stage regression.
DevStagePipeline = runpy.run_path(str(HERE / 'test-update-boot.py'))['DevStagePipeline']


if __name__ == '__main__':
    unittest.main(verbosity=2)
