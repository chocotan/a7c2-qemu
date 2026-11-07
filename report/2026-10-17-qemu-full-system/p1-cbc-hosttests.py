#!/usr/bin/env python3
"""Public host-only tests. Synthetic fixtures never attest Sony package/ABI/crypto.

Optional actual stock compile: set BOTH A7C2_P1_CBC_PACKAGE and
A7C2_P1_CBC_GUEST_ROOT. No default private paths, VM, FAT or block devices.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-cbc-functional-provider.py'))
SD = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))


def invoke(argv, **kwargs):
    result = subprocess.run(list(map(str, argv)), capture_output=True, timeout=55, **kwargs)
    if result.returncode:
        raise AssertionError(dict(argv=list(map(str, argv)), rc=result.returncode,
                                  stdout=result.stdout.decode(errors='replace'), stderr=result.stderr.decode(errors='replace')))
    return result


def archive(root, destination, names, duplicate=None):
    data = bytearray()
    for name in list(names) + ([duplicate] if duplicate else []) + ['TRAILER!!!']:
        payload = b'' if name == 'TRAILER!!!' else (root / name).read_bytes()
        mode = stat.S_IFREG | 0o644 if name == 'TRAILER!!!' else (root / name).lstat().st_mode
        fields = [1, mode, 0, 0, 1, 0, len(payload), 0, 0, 0, 0, len(name.encode()) + 1, 0]
        data += b'070701' + ''.join(f'{n:08x}' for n in fields).encode() + name.encode() + b'\0'
        data += b'\0' * (-len(data) % 4)
        data += payload
        data += b'\0' * (-len(data) % 4)
    destination.write_bytes(gzip.compress(data))


class Host(unittest.TestCase):
    def test_default_and_legacy_generated_source(self):
        self.assertIsNone(M['selection']())
        self.assertEqual(SD['newdecrypt_source']('unchanged'), 'unchanged')
        self.assertEqual(M['bootstrap_source']('unchanged'), 'unchanged')
        self.assertEqual(SD['effective_env'](None, {M['ENV']: M['PROFILE'], 'KEEP': 'yes'}),
                         dict(SD['ENV'], KEEP='yes'))
        for value in ('unknown', {'profile': M['PROFILE']}):
            with self.assertRaises(ValueError):
                M['selection'](value)
        with self.assertRaises(ValueError):
            SD['install']('/absent', '/absent', newdecrypt_profile=M['PROFILE'])
        # Source generation itself must keep all old bytes for every old option.
        init = dict(pins=[])
        self.assertEqual(SD['observer_source'](init), SD['OBSERVER'].replace('/* __INIT_PINS__ */', ''))
        self.assertEqual(SD['observer_source'](init, trust_profile=None, newdecrypt=None), SD['observer_source'](init))

    def test_real_wrappers_strict_and_sanitized(self):
        if not shutil.which('cc') or not shutil.which('openssl'):
            self.skipTest('cc and host openssl/libcrypto are required')
        with tempfile.TemporaryDirectory(prefix='p1-cbc-host-') as directory:
            out = Path(directory)
            assets = out / 'assets'; assets.mkdir()
            bad = out / 'bad'; bad.mkdir()
            crypto = out / 'synthetic-crypto'; crypto.write_bytes(b'SYNTHETIC crypto receipt fixture\n')
            rows = {'manifest': M['encoded'](dict(schema='synthetic-p1-cbc-host-fixture', original_input=False)),
                    'source-receipt': M['encoded'](dict(schema='synthetic-source-receipt', original_abi=False)),
                    'code-receipt': M['encoded'](dict(schema='synthetic-native-wrapper-abi', helper_u64=5, original_abi=False))}
            records = {name: dict(bytes=len(data), sha256=M['sha'](data)) for name, data in rows.items()}
            (out / 'p1_cbc_runtime_binding.h').write_text(M['runtime_header'](records))
            rows['profile'] = (M['PROFILE'] + '\n' + records['manifest']['sha256'] + '\n').encode()
            for name, data in rows.items():
                (assets / name).write_bytes(data)
            for number, name in [(1, 'profile'), (2, 'manifest'), (3, 'manifest'), (5, 'source-receipt'), (6, 'code-receipt')]:
                (bad / f'bad-{number}').write_bytes(b'corrupted ' + rows[name])
            (bad / 'bad-4').write_bytes(b'corrupted crypto')
            template = (HERE / 'p1_cbc_provider.inc').read_text()
            anchor = 'p1_fc_hash_file("/usr/lib/libcrypto.so.1.1",2349584,P1_NS_CRYPTO_SHA)'
            self.assertEqual(template.count(anchor), 1)
            template = template.replace(anchor, 'p1_fc_hash_file("/usr/lib/libcrypto.so.1.1",' +
                                        str(crypto.stat().st_size) + ',"' + M['record'](crypto)['sha256'] + '")')
            # Only this private host copy substitutes the synthetic crypto receipt.
            (out / 'p1_cbc_provider.inc').write_text(template)
            wrapper = M['wrapper_source']((HERE / 'p1-trust-key.inc').read_text())
            (out / 'p1_cbc_host_generated.inc').write_text(wrapper)
            key_text = (HERE / 'p1_cbc_known_k8.inc').read_text()
            key = bytes(int(n, 0) for n in __import__('re').findall(r'0x[0-9a-f]+', key_text))
            self.assertEqual(hashlib.sha256(key).hexdigest(), M['KEY_SHA'])
            iv = bytes.fromhex('e516514bfa7c6103f909b6a8ae258774')
            plain = bytearray((i * 19 + i // 1024) & 255 for i in range(2 * 1024 * 1024))
            for start in range(0, len(plain), 1024):
                block = plain[start:start + 1024]
                checksum = sum(block[j] | block[j + 1] << 8 for j in range(2, 1024, 2)) & 0xffff
                plain[start:start + 2] = checksum.to_bytes(2, 'little')
            ciphertext = invoke(['openssl', 'enc', '-aes-256-cbc', '-nopad', '-K', key.hex(), '-iv', iv.hex()],
                                input=bytes(plain[512:])).stdout
            for name, data in [('encrypted.bin', bytes(512) + ciphertext), ('reference.bin', plain), ('iv.bin', iv)]:
                (out / name).write_bytes(data)
            common = ['cc', '-std=c11', '-fno-builtin', '-fexceptions', '-funwind-tables', '-Wall', '-Wextra', '-Werror',
                      '-Wno-misleading-indentation', '-Wno-sign-compare', '-Wno-type-limits', '-Wno-unused-function',
                      '-I', out, '-I', HERE, '-DTEST_ASSET_DIR="' + str(assets) + '"',
                      '-DTEST_BAD_DIR="' + str(bad) + '"', '-DTEST_CRYPTO="' + str(crypto) + '"',
                      HERE / 'p1_cbc_host_wrappers.c', HERE / 'p1-trust-key.c', '-Wl,--wrap=EVP_DecryptUpdate',
                      '-Wl,--no-as-needed', '-lcrypto', '-ldl', '-pthread']
            results = {}
            for name, flags in [('strict', ['-O2', '-fstrict-aliasing']),
                                ('asan-ubsan', ['-O1', '-g', '-fno-omit-frame-pointer', '-fsanitize=address,undefined', '-no-pie'])]:
                invoke(common + flags + ['-o', out / name])
                result = invoke([out / name, out / 'encrypted.bin', out / 'reference.bin', out / 'iv.bin'],
                                env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
                self.assertFalse(result.stderr)
                results[name] = json.loads(result.stdout)
                self.assertGreater(results[name]['checks'], 29000)
                self.assertEqual(results[name]['stream_bytes'], 2 * 1024 * 1024 - 512)
            receipt = os.environ.get('A7C2_P1_CBC_HOST_REPORT')
            if receipt:
                Path(receipt).write_text(json.dumps(dict(schema='synthetic-p1-cbc-host-tests', results=results,
                    original_input=False, original_abi=False, actual_guest_crypto=False, vm_started=False), indent=2) + '\n')

    def test_synthetic_production_install_and_actual_cpio_readback(self):
        # Exercise the production install/generator/compiler-argument route with labelled synthetic boundaries.
        with tempfile.TemporaryDirectory(prefix='p1-cbc-build-contract-') as directory:
            out = Path(directory); root = out / 'root'; root.mkdir()
            (root / 'init').write_text((HERE / 'guest/update-storage-bootstrap').read_text())
            (root / 'etc').mkdir(); (root / 'etc/VerificationKey.pem').write_bytes(b'fixture')
            pinned = out / 'pinned'; pinned.write_bytes(b'fixture')
            package = out / 'synthetic-package'; package.write_bytes(b'synthetic package, not BODYDATA')
            initializer = dict(pins=[dict(op='synthetic', symbol='synthetic', path='/synthetic', sha256='0'*64,
                va=i, slot=i, size=1, code='00') for i in range(6)])
            trust = dict(schema='p1-trust-key-abi-v1', files={}, pins=[], passive=dict(windows=[{}]*4,
                         log_budget=dict(total=128, pin_identity=32, observations=96)))
            # Empty passive rows generate empty fixed arrays in this mock build only.
            signature = dict(trust, passive=dict(trust['passive'], windows=[]))
            fake_package = dict(M['record'](package), cbc_bytes=1139928576, synthetic=True)
            calls = []
            def command(argv, output, label):
                calls.append(list(map(str, argv)))
                Path(argv[-1]).write_bytes(b'synthetic compiler output; no guest ABI claim')
            model = runpy.run_path(str(HERE / 'p1-cbc-functional-provider.py'))
            model['prepare'].__globals__['package_contract'] = lambda p: fake_package
            model['prepare'].__globals__['sd_api'] = lambda: dict(trust_contract=lambda p: trust,
                                                                initialize_contract=lambda p: initializer)
            old_source = SD['observer_source']
            def generated(c, s, **kwargs):
                return old_source(c, signature, **kwargs)
            with patch.dict(SD['install'].__globals__, newdecrypt_api=lambda: model,
                            trust_contract=lambda r: trust, initialize_contract=lambda r: initializer,
                            _pinned_snapshot=lambda p: b'fixture', observer_source=generated,
                            api=lambda: dict(record=lambda p: dict(path=str(p), **M['record'](p)), command=command)):
                value = SD['install'](root, out, trust_profile=SD['TRUST_PROFILE'], pinned_key=pinned,
                                      newdecrypt_profile=M['PROFILE'], package_source=package)
            self.assertEqual(len(calls), 1)
            for name in ('p1_cbc_core.c', 'p1_cbc_stream.c', 'libcrypto.so.1.1', 'libpthread-2.25.so'):
                self.assertTrue(any(a.endswith('/' + name) for a in calls[0]), name)
            self.assertIn('#include "p1_cbc_provider.inc"', (out / 'p1-sd-observer.c').read_text())
            self.assertIn('-I', calls[0])
            cbc = value['newdecrypt']
            self.assertEqual(cbc['selection'], M['selection'](M['PROFILE']))
            self.assertEqual(len(cbc['runtime_files']), 5)
            receipt = (root / 'simulation/p1-cbc-model/source-receipt').read_text()
            self.assertNotIn(str(out), receipt)
            self.assertNotIn('/home/', receipt)
            for target in ('profile', 'env'):
                bad_value = json.loads(json.dumps(cbc))
                bad_value['assets'][target]['sha256'] = '0'*64
                with self.assertRaisesRegex(ValueError, 'marker/environment'):
                    model['validate'](bad_value)
            header = Path(cbc['build_directory'])/'p1_cbc_runtime_binding.h'
            original_header = header.read_bytes(); header.write_bytes(original_header+b'!')
            with self.assertRaisesRegex(ValueError, 'compiled pin'):
                model['validate'](cbc)
            header.write_bytes(original_header)
            rows = model['extra_bindings'](root, cbc) + [dict(path=str(root / 'simulation/p1-sd-observer.so'), **cbc['observer'])]
            for name, text in SD['binding_texts'](root, rows).items():
                (root / name).write_text(text)
            names = list(M['RUNTIME']) + ['init', 'simulation/p1-sd-observer.so', 'simulation/sd-read-bindings', 'simulation/sd-read-binding-count']
            bindings = {n: dict(mode=(root/n).lstat().st_mode, **M['record'](root/n)) for n in names}
            cpio = out / 'actual-newc.gz'; archive(root, cpio, names)
            model['preflight'].__globals__['sd_api'] = lambda: dict(trust_contract=lambda p: trust,
                initialize_contract=lambda p: initializer, binding_texts=SD['binding_texts'], cpio_readback=SD['cpio_readback'])
            self.assertEqual(model['preflight'](root, cbc, rows=rows, cpio_path=cpio, cpio_bindings=bindings), cbc)
            # Actual archive bytes, rather than an expected dict, must be consumed.
            archive(root, cpio, names, duplicate=names[0])
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                model['preflight'](root, cbc, rows=rows, cpio_path=cpio, cpio_bindings=bindings)
            archive(root, cpio, names[:-1])
            with self.assertRaisesRegex(ValueError, 'Missing'):
                model['preflight'](root, cbc, rows=rows, cpio_path=cpio, cpio_bindings=bindings)
            archive(root, cpio, names)
            for name in names:
                p = root/name; original = p.read_bytes(); p.write_bytes(original + b'!')
                try:
                    with self.assertRaises(ValueError):
                        model['preflight'](root, cbc, rows=rows, cpio_path=cpio, cpio_bindings=bindings)
                finally:
                    p.write_bytes(original)

    def test_bootstrap_unsets_then_exact_env_then_export(self):
        original = (HERE / 'guest/update-storage-bootstrap').read_text()
        source = M['bootstrap_source'](original, M['selection'](M['PROFILE']))
        self.assertTrue(source.startswith('#!/bin/sh\nunset ' + M['ENV'] + '\n'))
        self.assertLess(source.index('done < /simulation/sd-read-bindings'), source.index('export ' + M['ENV']))
        start = source.index('    [ -f /simulation/p1-cbc-model/env ]')
        end = source.index('    if [ "$($bb cat /simulation/sd-read-profile)"', start)
        fragment = source[start:end]
        with tempfile.TemporaryDirectory(prefix='p1-cbc-env-') as directory:
            envfile = Path(directory)/'env'
            fragment = fragment.replace('/simulation/p1-cbc-model/env', str(envfile)).replace('/bin/busybox', '/usr/bin/env')
            script = 'unset ' + M['ENV'] + '\ncheck() {\n' + fragment + '}\ncheck || exit $?\ntest "$' + M['ENV'] + '" = ' + M['PROFILE'] + '\n'
            exact = (M['ENV']+'='+M['PROFILE']+'\n').encode()
            for content, passed in [(exact, True), (exact+b'\n', False), (exact[:-2]+b'X\n', False)]:
                envfile.write_bytes(content)
                result = subprocess.run(['sh', '-c', script], env=dict(os.environ, **{M['ENV']: 'inherited'}), capture_output=True)
                self.assertEqual(result.returncode == 0, passed)

    def test_optional_actual_stock_build(self):
        package, guest = os.environ.get('A7C2_P1_CBC_PACKAGE'), os.environ.get('A7C2_P1_CBC_GUEST_ROOT')
        if not package or not guest:
            self.skipTest('actual stock package/guest root not supplied via A7C2_P1_CBC_PACKAGE and A7C2_P1_CBC_GUEST_ROOT')
        with tempfile.TemporaryDirectory(prefix='p1-cbc-actual-') as directory:
            out = Path(directory); root = out/'root'; root.mkdir(); guest = Path(guest)
            contract = SD['trust_contract'](guest)
            init = SD['initialize_contract'](guest)
            names = set(contract['files']) | {p['path'].lstrip('/') for p in init['pins']}
            original = runpy.run_path(str(HERE/'p1-file-media-contract.py'))
            names |= {row[0] for row in original['SAMPLES'].values()}
            names |= {'lib/libc-2.25.so', 'lib/libdl-2.25.so', 'lib/libpthread-2.25.so', 'lib/ld-2.25.so'}
            for name in names:
                dst = root/name; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(guest/name, dst)
            (root/'init').write_text((HERE/'guest/update-storage-bootstrap').read_text())
            pinned = out/'pinned.pem'; shutil.copyfile(guest/SD['KEY'][0], pinned); pinned.chmod(0o444)
            value = SD['install'](root, out, trust_profile=SD['TRUST_PROFILE'], pinned_key=pinned,
                                  newdecrypt_profile=M['PROFILE'], package_source=package)
            symbols = invoke(['readelf', '-W', '--dyn-syms', root/'simulation/p1-sd-observer.so']).stdout.decode()
            self.assertIn('EVP_DecryptUpdate@OPENSSL_1_1_0', symbols)
            self.assertNotIn('OPENSSL_3', symbols)
            self.assertFalse(value['newdecrypt']['guest_executed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
