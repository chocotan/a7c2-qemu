#!/usr/bin/env python3
"""Host-only exact binding contract and execution of the real guest shell guard."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SD = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
DEV = runpy.run_path(str(HERE / 'p1-dev-install.py'))
U = SD['api']()


def fixture(root, *, dev=False):
    base = ['usr/lib/libInfraMediaCommon.so', 'usr/bin/sdfileinput.elf',
            'usr/lib/libsdfileinputupdaterapi.so', 'usr/lib/libupdaterapi.so', 'usr/lib/libFsys.so']
    native = ['etc/VerificationKey.pem', 'usr/lib/libcrypto.so',
              'usr/lib/libosal_uipc.so', 'usr/lib/libSKD.so']
    if not dev:
        native.append('lib/libc-2.25.so')
    runtime = ['simulation/p1-trust-key/profile', 'simulation/p1-trust-key/sony-original.pem',
               'simulation/p1-trust-key/' + ('dev-contract.json' if dev else 'contract.json')]
    runtime += ['simulation/p1-dev-trust.so' if dev else 'simulation/p1-sd-observer.so']
    for name in dict.fromkeys(base + [SD['CORE'][0], 'simulation/file-media-config.so',
                                    'simulation/p1-sd-observer.so'] + native + runtime):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('source bytes for ' + name + '\n').encode('ascii'))
    (root / 'sbin').mkdir(exist_ok=True)
    contract = {'inputs': {str(i): {'path': name} for i, name in enumerate(base)}}
    trust = {'contract': {'files': native + [base[0]]}, 'runtime_files': runtime}
    model = {'original_bindings': {name: U['record'](root / name) for name in native},
             'assets': {name: U['record'](root / name) for name in runtime},
             'preload': SD['PRELOAD']}
    return contract, trust, model


def install_texts(root, rows):
    texts = SD['binding_texts'](root, rows)
    for name, text in texts.items():
        (root / name).write_text(text, encoding='ascii')
    return texts


def cpio_rows(root, names):
    return {name: {'mode': (root / name).stat().st_mode,
                   'bytes': (root / name).stat().st_size,
                   'sha256': hashlib.sha256((root / name).read_bytes()).hexdigest()}
            for name in names}


class HostContract(unittest.TestCase):
    def test_default_eight_and_final_sixteen_keep_native_and_trust_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract, trust, model = fixture(root)
            self.assertEqual(len(SD['binding_rows'](root, contract)), 8)
            rows = SD['binding_rows'](root, contract, trust_key=trust)
            self.assertEqual(len(rows), 16)
            texts = SD['binding_texts'](root, rows)
            self.assertEqual(texts['simulation/sd-read-binding-count'], '16\n')
            self.assertEqual(len(texts['simulation/sd-read-bindings'].splitlines()), 16)
            self.assertNotIn('/simulation/sd-read-binding-count ', texts['simulation/sd-read-bindings'])
            for name in trust['contract']['files'] + trust['runtime_files']:
                self.assertIn('/' + name + ' ', texts['simulation/sd-read-bindings'])
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                SD['binding_texts'](root, rows + rows[:1])
            for invalid in ([], rows * 257):
                with self.assertRaisesRegex(ValueError, 'count'):
                    SD['binding_texts'](root, invalid)

    def test_binding_order_survives_sorted_json_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            contract, trust, model = fixture(root)
            trust['contract']['files'] = {name: {} for name in reversed(trust['contract']['files'])}
            saved_contract, saved_trust, saved_model = json.loads(json.dumps(
                [contract, trust, model], sort_keys=True))
            for before, after in (({'trust_key': trust}, {'trust_key': saved_trust}),
                                  ({'trusted_key_model': model}, {'trusted_key_model': saved_model})):
                with self.subTest(kind=next(iter(before))):
                    original = SD['binding_rows'](root, contract, **before)
                    reloaded = SD['binding_rows'](root, saved_contract, **after)
                    self.assertEqual(SD['binding_texts'](root, original), SD['binding_texts'](root, reloaded))

    def test_host_rejects_self_consistent_truncation_and_noncanonical_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'root'; root.mkdir()
            contract, trust, _ = fixture(root)
            expected = SD['binding_rows'](root, contract, trust_key=trust)
            texts = install_texts(root, expected)
            value = {'bindings': expected, 'cpio_bindings': cpio_rows(root, texts)}
            self.assertEqual(SD['binding_preflight'](root, value, expected, root), texts)
            # The execution root is a copy; receipt paths still refer to the prepared root.
            copied = Path(td) / 'copy'; shutil.copytree(root, copied)
            current = SD['binding_rows'](copied, contract, trust_key=trust)
            self.assertEqual(SD['binding_preflight'](copied, value, current, root), texts)
            count = root / 'simulation/sd-read-binding-count'
            for invalid in (b'15\n', b'016\n', b'16', b'16\n\n', b'16\r\n', b'NaN\n', b'0\n', b'4097\n'):
                with self.subTest(count=invalid):
                    count.write_bytes(invalid)
                    changed = dict(value, cpio_bindings=cpio_rows(root, texts))
                    with self.assertRaisesRegex(ValueError, 'text/count'):
                        SD['binding_preflight'](root, changed, expected, root)
            install_texts(root, expected[:-1])
            shortened = {'bindings': expected[:-1], 'cpio_bindings': cpio_rows(root, texts)}
            with self.assertRaisesRegex(ValueError, 'verified sources'):
                SD['binding_preflight'](root, shortened, expected, root)
            install_texts(root, expected)
            missing = copy.deepcopy(value); missing['cpio_bindings'].pop('simulation/sd-read-binding-count')
            with self.assertRaisesRegex(ValueError, 'CPIO contract'):
                SD['binding_preflight'](root, missing, expected, root)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                SD['binding_preflight'](root, dict(value, bindings=expected + expected[:1]), expected, root)

    def test_cpio_exact_readback_includes_count_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'root'; root.mkdir()
            contract, trust, _ = fixture(root)
            rows = SD['binding_rows'](root, contract, trust_key=trust)
            texts = install_texts(root, rows)
            names = list(texts) + [str(Path(row['path']).relative_to(root)) for row in rows]
            expected = cpio_rows(root, names)
            archive = Path(td) / 'fixture.cpio.gz'
            U['archive'](root, archive)
            self.assertEqual(SD['cpio_readback'](archive, expected), expected)
            (root / 'simulation/sd-read-binding-count').write_text('8\n')
            changed_archive = Path(td) / 'changed.cpio.gz'
            U['archive'](root, changed_archive)
            with self.assertRaisesRegex(ValueError, 'sd-read-binding-count'):
                SD['cpio_readback'](changed_archive, expected)
            # bindings() must include it independently of the test's expected mapping.
            (root / 'init').write_text('fixture\n')
            (root / 'etc/ld.so.preload').write_text(SD['PRELOAD'])
            (root / 'sbin/sdfileinput.elf').symlink_to('/init')
            (root / 'simulation/sd-read-profile').write_text(SD['PROFILE'] + '\n')
            (root / 'simulation/sd-read-env').write_text('fixture\n')
            (root / 'simulation/sd-no-install').write_text('target-block-readonly-20\n')
            (root / 'simulation/p1-trust-key/contract.json').unlink()
            samples = {str(i): (row['path'], 0, '') for i, row in enumerate(contract['inputs'].values())}
            with patch.dict(SD['bindings'].__globals__, runpy=SimpleNamespace(run_path=lambda _: {'SAMPLES': samples})):
                actual = SD['bindings'](root, {'bytes': 1, 'sha256': 'a' * 64})
            self.assertIn('simulation/sd-read-binding-count', actual)

    def test_stock_and_readonly_configure_generate_final_count_without_build(self):
        for profile in (SD['PROFILE'], SD['INSTALL_PROFILE']):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as td:
                root = Path(td) / 'root'; root.mkdir()
                contract, trust, _ = fixture(root)
                source = Path(td) / 'p1-sd-observer.c'; source.write_text('host fixture\n')
                update = {'sd': {'fat_bits': 32, 'bodydata': {'size': 1, 'sha256': SD['STOCK_SHA']},
                                 'image': {'path': '/not-opened'}},
                          'sd_read_package': {'bytes': 1}, 'sd_read_package_source': {},
                          'file_media': {'source': {'sha256': SD['HOOK_SHA']},
                                         'output': {'sha256': U['record'](root / 'simulation/file-media-config.so')['sha256']}},
                          'virtual_install': {}}
                def load(name):
                    return ({'inspect': lambda _: contract} if name.endswith('p1-file-media-contract.py')
                            else {'authorization': lambda _: 'host fixture\n'})
                with patch.dict(SD['configure'].__globals__, api=lambda: U,
                        DSO_SHA=update['file_media']['output']['sha256'],
                        runpy=SimpleNamespace(run_path=load), single_body_fat=lambda *a: None,
                        initialize_contract=lambda _: {}, install=lambda *a, **k: trust):
                    value = SD['configure'](root, update, Path(td), profile=profile)
                self.assertEqual(len(value['bindings']), 16)
                self.assertEqual((root / 'simulation/sd-read-binding-count').read_bytes(), b'16\n')
                self.assertEqual(len((root / 'simulation/sd-read-bindings').read_text().splitlines()), 16)

    def test_dev_both_kinds_finalize_after_provider_without_build(self):
        identity = runpy.run_path(str(HERE / 'p1-dev-receiver-identity.py'))
        for kind in ('version-only-2.02', 'fixed-system-file-v1'):
            for selected in (False, True):
                with self.subTest(kind=kind, key=selected), tempfile.TemporaryDirectory() as td:
                    root = Path(td) / 'root'; root.mkdir()
                    contract, _, model = fixture(root, dev=True)
                    # DEV identity inputs are ordinary synthetic files; helper constants decide both paths and counts.
                    names = list(identity['RUNTIME_FILES']) + ['lib/' + name for name in identity['LIBRARIES']]
                    for name in names:
                        path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(('DEV identity fixture bytes for ' + name + '\n').encode('ascii'))
                    identity_rows = {name: U['record'](root / name) for name in names}
                    base_paths = {row['path'] for row in SD['binding_rows'](root, contract)}
                    full_paths = {row['path'] for row in SD['binding_rows'](root, contract, trusted_key_model=model)}
                    new_paths = {identity_rows[name]['path'] for name in names}
                    self.assertEqual(len(names), 6)
                    self.assertEqual(len(set(names)), 6)
                    self.assertEqual(len(new_paths), 6)
                    self.assertFalse(new_paths & full_paths)
                    expected_paths = (full_paths if selected else base_paths) | new_paths
                    # The production _stock_contract normally validates these six passive pins first.
                    pins = [dict(path='/usr/lib/libsdfileinputupdaterapi.so' if i < 3 else '/usr/lib/dev-fixture-%d.so' % i,
                                 sha256=identity['STOCK_RECEIVER'][1] if i < 3 else '0' * 64, code='01020304', va=i)
                            for i in range(6)]
                    initialization = dict(schema='p1-sd-initialize-passive-v1', pins=pins, core={'opaque': 1})
                    saved_pins = copy.deepcopy(pins)
                    package_value = dict(schema=DEV['PACKAGE_SCHEMA'], delta='version-only-2.02',
                                         profile=DEV['PROFILE'], mode=DEV['MODE'], original_version='2.01',
                                         new_version='2.02', current_version='2.01', virtual_only=True,
                                         derived={'sha256': 'a' * 64})
                    if kind == 'fixed-system-file-v1':
                        package_value.update(schema=DEV['FILE_PACKAGE_SCHEMA'], kind='p15-qemu-packaged-system-check-v1')
                    binding = {'package_contract': {'value': package_value}, 'receipt': {'sha256': 'b' * 64},
                               'value': {'clone': {'sha256': 'c' * 64}}}
                    update = {'mode': DEV['MODE'], 'read_only': False, 'allow_updater_writes': True,
                              'allow_dev_signature_bypass': True, 'original_resources': {}, 'module_contract': {},
                              'sd_read_package_source': {'path': '/not-opened'}, 'virtual_install': binding,
                              'p2': {'firmware_version': {'version': '2.01'}}, 'receiver': {}, 'sd_read_package': {},
                              'sd': {'fat_bits': 32, 'image': {'path': '/not-opened'},
                                     'bodydata': {'sha256': 'a' * 64, 'size': 1}},
                              'file_media': {'source': {'sha256': SD['HOOK_SHA']},
                                             'output': {'sha256': U['record'](root / 'simulation/file-media-config.so')['sha256']}},
                              'trusted_key_model_selection': {'fixture': True} if selected else None}
                    fake_sd = dict(SD, observer_source=lambda _: 'host fixture\n', single_body_fat=lambda *a: None,
                                   DSO_SHA=update['file_media']['output']['sha256'])
                    fake_u = dict(U, command=lambda *a: (root / 'simulation/p1-sd-observer.so').write_bytes(b'final observer'))
                    def load(name='update-boot.py'):
                        if name == 'p1-sd-read-probe.py': return fake_sd
                        if name == 'dev-update-profile.py': return {'verify_derived_receiver': lambda *a: {}}
                        if name == 'p1-dev-receiver-identity.py': return identity
                        return fake_u
                    def configure_provider(*a, **k):
                        self.assertFalse((root / 'simulation/sd-read-binding-count').exists())
                        return model
                    # file_media_preflight has dedicated identity tests; it is unrelated to this count finalization.
                    with patch.dict(DEV['configure'].__globals__, api=load, admit=lambda *a, **k: None,
                            resource_preflight=lambda *a: None, package=lambda *a, **k: None,
                            _stock_contract=lambda _: (contract, initialization), PACKAGE_BYTES=1,
                            file_media_preflight=lambda *a: None,
                            trusted_key_api=lambda _: {'configure': configure_provider} if selected else None,
                            key_model_contract=lambda *a: None):
                        value = DEV['configure'](root, update, Path(td))
                    expected = 22 if selected else 14
                    self.assertEqual(expected, len(expected_paths))
                    self.assertEqual(expected, len(value['bindings']))
                    self.assertEqual({row['path'] for row in value['bindings']}, expected_paths)
                    self.assertEqual((root / 'simulation/sd-read-binding-count').read_bytes(), f'{expected}\n'.encode())
                    text = (root / 'simulation/sd-read-bindings').read_text()
                    self.assertEqual(expected, len(text.splitlines()))
                    for name in names:
                        data = (root / name).read_bytes(); row = identity_rows[name]
                        self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (row['bytes'], row['sha256']))
                        self.assertEqual(U['record'](root / name), row)
                        self.assertIn(f'/{name} {row["bytes"]} {row["sha256"]}\n', text)
                    for pin in value['initialize_contract']['pins']:
                        self.assertEqual(pin['sha256'], identity['DEV_RECEIVER'][1]
                                         if pin['path'] == '/usr/lib/libsdfileinputupdaterapi.so' else '0' * 64)
                    self.assertEqual(saved_pins, initialization['pins'])
                    self.assertIn('A7C2_P1_DEV_INSTALL=' + kind, (root / 'init').read_text())
                    if selected:
                        for name in list(model['assets']) + list(model['original_bindings']):
                            self.assertIn('/' + name + ' ', text)


AUDIT = r'''import hashlib, os, pathlib, sys
op, source, target, count, digest, mode = sys.argv[1:]
try:
    data = pathlib.Path(source).read_bytes()
    if op != 'copy' or len(data) != int(count) or hashlib.sha256(data).hexdigest() != digest:
        sys.exit(91)
    pathlib.Path(target).write_bytes(data)
    os.chmod(target, int(mode, 8))
    if pathlib.Path(target).read_bytes() != data:
        sys.exit(92)
    print('REAL_BINDING_AUDIT source=' + source, flush=True)
except OSError:
    sys.exit(93)
'''


class GuestGuard(unittest.TestCase):
    def test_actual_shell_full_audit_and_rejections_for_all_profiles_and_dev_kinds(self):
        shells = [('/bin/sh',)]
        if shutil.which('busybox'):
            shells.append((shutil.which('busybox'), 'sh'))
        profiles = [(SD['PROFILE'], None), (SD['INSTALL_PROFILE'], None),
                    (DEV['PROFILE'], 'version-only-2.02'), (DEV['PROFILE'], 'fixed-system-file-v1')]
        for shell in shells:
            for profile, kind in profiles:
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td); sim = root / 'simulation'; sim.mkdir()
                    contract, trust, _ = fixture(root)
                    rows = SD['binding_rows'](root, contract, trust_key=trust)
                    self.assertEqual(len(rows), 16)
                    lines = ''.join(f'{r["path"]} {r["bytes"]} {r["sha256"]}\n' for r in rows).encode()
                    (root / 'image_mmca').touch()
                    (sim / 'sd-read-profile').write_text(profile + '\n')
                    env = {k: v for k, v in os.environ.items() if not k.startswith('A7C2_')}
                    env.update(SD['ENV'])
                    if kind:
                        env['A7C2_P1_DEV_INSTALL'] = kind
                        (sim / 'dev-authorization').write_text(profile + '\n')
                    if profile == SD['PROFILE']:
                        (sim / 'sd-no-install').write_text('target-block-readonly-20\n')
                        (sim / 'sd-read-env').write_text(''.join(f'{k}={v}\n' for k, v in SD['ENV'].items()))
                        (sim / 'read-only-probe').touch(); (sim / 'block-readonly-verified').touch()
                    else:
                        (sim / 'update-profile').write_text((DEV['MODE'] if kind else 'official') + '\n')
                        (sim / 'backup-trusted-file-load').write_text(profile + '\n')
                        (sim / 'install-authorization').write_text(profile + ' ' + 'a' * 64 + ' ' + 'b' * 64 + '\n')
                    for name in ('install-target', 'sd-target-ro'):
                        helper = sim / name
                        helper.write_text('#!/bin/sh\n[ "$*" = "/dev/pnflasha /dev/cnflasha[0-9]* /dev/nflashaB0 /dev/nflashaB1" ] || exit 125\n')
                        helper.chmod(0o755)
                    audit = sim / 'audit'; audit.write_text('#!' + sys.executable + '\n' + AUDIT); audit.chmod(0o755)
                    text = DEV['bootstrap_source'](install_kind=kind) if kind else (HERE / 'guest/update-storage-bootstrap').read_text()
                    text = text.split('receiver_snapshot()\n', 1)[0]
                    dispatcher = shell[0] if len(shell) == 2 else ''
                    text = text.replace('bb=/bin/busybox', 'bb=' + dispatcher)
                    text = text.replace('/simulation/', str(sim) + '/').replace('/image_mmca', str(root / 'image_mmca'))
                    script = root / 'guard.sh'; script.write_text(text + '\nsd_read_guard\nexit "$?"\n')
                    cases = [('sixteen', lines, b'16\n', 0, 16),
                             ('default-eight', b''.join(lines.splitlines(keepends=True)[:8]), b'8\n', 0, 8),
                             ('missing-row', b''.join(lines.splitlines(keepends=True)[:-1]), b'16\n', 125, 15),
                             ('wrong-count', lines, b'15\n', 125, 16),
                             ('nondigit', lines, b'NaN\n', 125, 0),
                             ('zero', lines, b'0\n', 125, 0),
                             ('leading-zero', lines, b'016\n', 125, 0),
                             ('above-bound', lines, b'4097\n', 125, 0),
                             ('overflow', lines, b'999999999999999999999999999999999\n', 125, 0),
                             ('missing-count-lf', lines, b'16', 125, 0),
                             ('extra-count-lf', lines, b'16\n\n', 125, 0),
                             ('crlf', lines, b'16\r\n', 125, 0),
                             ('duplicate', lines + lines.splitlines(keepends=True)[0], b'16\n', 125, 17),
                             ('unterminated-row', lines[:-1], b'16\n', 125, 15)]
                    for label, data, count, rc, audits in cases:
                        with self.subTest(shell=shell, profile=profile, kind=kind, case=label):
                            (sim / 'sd-read-bindings').write_bytes(data)
                            (sim / 'sd-read-binding-count').write_bytes(count)
                            result = subprocess.run([*shell, str(script)], env=env, capture_output=True, timeout=15)
                            self.assertEqual(result.returncode, rc, result.stdout + result.stderr)
                            self.assertEqual(result.stdout.count(b'REAL_BINDING_AUDIT '), audits, result.stdout + result.stderr)
                            self.assertFalse((sim / 'sd-binding-readback').exists())
                    for corruption in ('bytes-changed', 'asset-missing', 'count-missing', 'count-symlink'):
                        with self.subTest(shell=shell, profile=profile, kind=kind, case=corruption):
                            source = Path(rows[-1]['path']); original = source.read_bytes()
                            (sim / 'sd-read-bindings').write_bytes(lines)
                            count = sim / 'sd-read-binding-count'; count.unlink()
                            if corruption == 'count-symlink':
                                target = sim / 'independent-count'; target.write_bytes(b'16\n'); count.symlink_to(target)
                            elif corruption != 'count-missing':
                                count.write_bytes(b'16\n')
                            if corruption == 'bytes-changed': source.write_bytes(original[:-1] + b'!')
                            if corruption == 'asset-missing': source.unlink()
                            result = subprocess.run([*shell, str(script)], env=env, capture_output=True, timeout=15)
                            self.assertEqual(result.returncode, 125, result.stdout + result.stderr)
                            self.assertEqual(result.stdout.count(b'REAL_BINDING_AUDIT '), 15 if corruption.startswith(('bytes-', 'asset-')) else 0)
                            source.write_bytes(original)
                            if not count.exists() and not count.is_symlink(): count.touch()


if __name__ == '__main__':
    unittest.main(verbosity=2)
