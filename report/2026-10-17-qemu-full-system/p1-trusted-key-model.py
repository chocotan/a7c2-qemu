#!/usr/bin/env python3
"""Explicit dev adapter for the pinned P1 key service; configure before CPIO.

provision(pinned_key, output) creates a fresh selection receipt. configure() and
preflight() keep strict stock admission separate from the known four-byte dev
receiver. No function starts a VM, changes a disk or claims guest verification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-p1-pinned-key-trust-v1'
SCHEMA = 'a7c2-p1-pinned-key-trust-selection-v1'
SERVICE_PROFILE = 'virtual-p1-pinned-key-v1'
SERVICE = 'simulation/p1-trust-key-service.so'
RUNTIME = 'simulation/p1-trust-key/'


def api(name='update-boot.py'):
    return runpy.run_path(str(HERE / name))


def provision(pinned_key, output):
    u = api(); sd = api('p1-sd-read-probe.py')
    pinned_key, output = map(u['absolute'], (pinned_key, output))
    row = u['record'](pinned_key)
    sd['_pinned_snapshot'](pinned_key)
    if u['record'](pinned_key) != row:
        raise ValueError('Pinned PEM changed while provisioning')
    value = dict(schema=SCHEMA, profile=PROFILE, service_profile=SERVICE_PROFILE,
                 pinned_key=row, signature_verified=False, physical_devices_used=False)
    with output.open('x', encoding='ascii') as stream:
        stream.write(json.dumps(value, sort_keys=True) + '\n'); stream.flush(); os.fsync(stream.fileno())
    return dict(profile=PROFILE, receipt=str(output), receipt_sha256=u['record'](output)['sha256'])


def selection_contract(selection):
    if (not isinstance(selection, dict) or set(selection) != {'profile', 'receipt', 'receipt_sha256'}
            or selection['profile'] != PROFILE or not isinstance(selection['receipt_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', selection['receipt_sha256'])):
        raise ValueError('Explicit dev trust selection and receipt hash required')
    u = api(); sd = api('p1-sd-read-probe.py')
    value, receipt = u['checked_json'](selection['receipt'])
    if (receipt['sha256'] != selection['receipt_sha256'] or value.get('schema') != SCHEMA
            or value.get('profile') != PROFILE or value.get('service_profile') != SERVICE_PROFILE
            or value.get('signature_verified') is not False or value.get('physical_devices_used') is not False):
        raise ValueError('Dev trust receipt identity/policy differs')
    row = u['record'](value['pinned_key']['path'])
    if row != value['pinned_key']:
        raise ValueError('Independent pinned PEM identity differs')
    data = sd['_pinned_snapshot'](row['path'])
    if u['record'](row['path']) != row:
        raise ValueError('Independent pinned PEM changed during readback')
    return value, receipt, data


def contract(root, update, selection):
    u = api(); sd = api('p1-sd-read-probe.py'); dev = api('p1-dev-install.py'); root = Path(root)
    if (update.get('install_profile') != dev['PROFILE'] or update.get('read_only') is not False
            or update.get('allow_updater_writes') is not True
            or update.get('trusted_key_model_selection') != selection):
        raise ValueError('Dev trust requires matching explicit dev install authorization')
    dev['selection'](update.get('install_profile'), update.get('mode'), update.get('allow_dev_signature_bypass'))
    value, receipt, data = selection_contract(selection)
    pinned = Path(value['pinned_key']['path'])
    if pinned.resolve().is_relative_to(root.resolve()) or os.path.samefile(pinned, root / sd['KEY'][0]):
        raise ValueError('Independent pinned PEM cannot be the caller PEM or inside prepared root')
    signature = sd['dev_trust_contract'](root, update['receiver'])
    initializer = dev['_stock_contract'](root)[1]
    environment = dict(dev['ENV'], **sd['effective_env'](SERVICE_PROFILE))
    runtime = dict(schema='p1-dev-trust-key-service-v1', profile=PROFILE, service_profile=SERVICE_PROFILE,
        selection=selection, contract=signature, initialize_contract=initializer, environment=environment,
        environment_activation='selected-service-constructor-after-native-pins',
        pinned_sha1=hashlib.sha1(data).hexdigest(), signature_verified=False, guest_verified=False,
        modeled_hardware_history_verified=False)
    return runtime, receipt, value['pinned_key'], data


def native_bindings(root, signature):
    root = Path(root)
    return {name: dict(row, mode=(root / name).stat().st_mode) for name,row in signature['files'].items()}


def configure(root, update, output, *, selection):
    u = api(); sd = api('p1-sd-read-probe.py'); root, output = Path(root), Path(output)
    runtime, receipt, pinned, data = contract(root, update, selection)
    preload = sd['PRELOAD'] + '/' + SERVICE + '\n'
    if (root / 'etc/ld.so.preload').read_text(encoding='ascii') != sd['PRELOAD']:
        raise ValueError('Dev trust requires the frozen observer/hook preload order')
    artifact = root / RUNTIME; artifact.mkdir(exist_ok=False)
    (artifact / 'profile').write_text(SERVICE_PROFILE + '\n', encoding='ascii')
    snapshot = artifact / 'sony-original.pem'; snapshot.write_bytes(data); snapshot.chmod(0o444)
    if sd['_pinned_snapshot'](snapshot) != data:
        raise ValueError('Dev trust provisioned PEM readback differs')
    (artifact / 'dev-contract.json').write_text(json.dumps(runtime, sort_keys=True) + '\n', encoding='ascii')
    source = output / 'p1-trust-key-service.c'
    source.write_text(sd['trust_service_source'](runtime['initialize_contract'], runtime['contract'],
                                               trust_profile=SERVICE_PROFILE), encoding='ascii')
    u['command'](['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
        '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-builtin', '-fexceptions', '-funwind-tables',
        '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC', '-I', HERE,
        source, HERE / 'p1-trust-key.c', root / 'lib/libc-2.25.so', root / 'lib/libdl-2.25.so',
        root / 'lib/ld-2.25.so', '-o', root / SERVICE], output, 'dev-trust-service-build')
    (root / 'etc/ld.so.preload').write_text(preload, encoding='ascii')
    assets = {}
    for name in (RUNTIME + 'profile', RUNTIME + 'sony-original.pem', RUNTIME + 'dev-contract.json', SERVICE):
        assets[name] = dict(u['record'](root / name), mode=(root / name).stat().st_mode)
    sources = [u['record'](HERE / name) for name in ('p1-trusted-key-model.py', 'p1-sd-read-probe.py',
        'p1-dev-install.py', 'dev-update-profile.py', 'p1-file-media-contract.py', *sd['TRUST_SOURCES'])]
    sources += [u['record'](source), receipt, pinned]
    return dict(profile=PROFILE, selection=selection, signature_verified=False, preload=preload,
                environment=runtime['environment'], contract=runtime, assets=assets, sources=sources,
                original_bindings=native_bindings(root, runtime['contract']))


def preflight(update, root, *, selection):
    u = api(); sd = api('p1-sd-read-probe.py'); root = Path(root)
    runtime, receipt, pinned, data = contract(root, update, selection)
    value = update.get('trusted_key_model')
    preload = sd['PRELOAD'] + '/' + SERVICE + '\n'
    expected_names = {RUNTIME + name for name in ('profile', 'sony-original.pem', 'dev-contract.json')} | {SERVICE}
    if (not isinstance(value, dict) or value.get('profile') != PROFILE or value.get('selection') != selection
            or value.get('signature_verified') is not False or value.get('contract') != runtime
            or value.get('environment') != runtime['environment'] or value.get('preload') != preload
            or value.get('original_bindings') != native_bindings(root, runtime['contract'])
            or set(value.get('assets', {})) != expected_names):
        raise ValueError('Dev trust model contract differs')
    texts = {'etc/ld.so.preload': preload, RUNTIME + 'profile': SERVICE_PROFILE + '\n',
             RUNTIME + 'dev-contract.json': json.dumps(runtime, sort_keys=True) + '\n'}
    for name, expected in texts.items():
        if (root / name).read_text(encoding='ascii') != expected:
            raise ValueError('Dev trust runtime text differs: ' + name)
    source = Path(update['output']) / 'p1-trust-key-service.c'
    if source.read_text(encoding='ascii') != sd['trust_service_source'](runtime['initialize_contract'], runtime['contract'], trust_profile=SERVICE_PROFILE):
        raise ValueError('Dev trust emitted code/activation differs')
    for name, row in value['assets'].items():
        now = u['record'](root / name)
        if any(now[k] != row[k] for k in ('bytes', 'sha256')) or (root / name).stat().st_mode != row['mode']:
            raise ValueError('Dev trust runtime asset differs: ' + name)
    if sd['_pinned_snapshot'](root / RUNTIME / 'sony-original.pem') != data:
        raise ValueError('Dev trust runtime PEM differs')
    required_sources = {str(HERE / name) for name in ('p1-trusted-key-model.py', 'p1-sd-read-probe.py',
        'p1-dev-install.py', 'dev-update-profile.py', 'p1-file-media-contract.py', *sd['TRUST_SOURCES'])}
    required_sources |= {receipt['path'], pinned['path'], str(Path(update['output']) / 'p1-trust-key-service.c')}
    if {r['path'] for r in value.get('sources', [])} != required_sources:
        raise ValueError('Dev trust source/receipt set differs')
    for row in value['sources']:
        now = u['record'](row['path'])
        if any(now[k] != row[k] for k in ('bytes', 'sha256')):
            raise ValueError('Dev trust source differs: ' + row['path'])
    if update.get('initrd'):
        sd['cpio_readback'](update['initrd']['path'], value['original_bindings'])
    return value


def configure_stock(root, update, output):
    """Activate the existing stock observer before receipts/CPIO are frozen."""
    u = api(); sd = api('p1-sd-read-probe.py'); root, output = Path(root), Path(output)
    selected = update.get('trust_selection')
    if (update.get('install_profile') != sd['INSTALL_PROFILE'] or update.get('mode') != 'official'
            or not selected or selected.get('profile') != SERVICE_PROFILE):
        raise ValueError('Stock activation requires explicit official install trust selection')
    value = update['sd_read_observation']; trust = value['trust_key']
    if trust.get('profile') != SERVICE_PROFILE:
        raise ValueError('Stock activation lacks selected trust contract')
    sd['trust_preflight'](root, trust)
    source = output / 'p1-sd-observer.c'
    original = sd['observer_source'](value['initialize_contract'], sd['trust_contract'](root), trust_profile=SERVICE_PROFILE)
    if source.read_text(encoding='ascii') != original:
        raise ValueError('Stock observer emission differs before explicit activation')
    source.write_text(original, encoding='ascii')
    u['command'](['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
        '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-builtin', '-fexceptions', '-funwind-tables',
        '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC', '-I', HERE,
        source, HERE / 'p1-trust-key.c', root / 'lib/libc-2.25.so', root / 'lib/libdl-2.25.so',
        root / 'lib/ld-2.25.so', '-o', root / 'simulation/p1-sd-observer.so'], output, 'stock-trust-observer-build')
    value['observer_source'] = u['record'](source)
    value['observer'] = u['record'](root / 'simulation/p1-sd-observer.so')
    value['bindings'] = [value['observer'] if row['path'] == value['observer']['path'] else row for row in value['bindings']]
    return dict(profile=SERVICE_PROFILE, environment=sd['effective_env'](SERVICE_PROFILE),
        environment_activation='selected-observer-constructor-after-native-pins',
        source=value['observer_source'], observer=value['observer'], signature_verified=False)


def preflight_stock(update, root):
    u = api(); sd = api('p1-sd-read-probe.py'); root = Path(root)
    value = update.get('trust_execution'); selected = update.get('trust_selection')
    if (update.get('install_profile') != sd['INSTALL_PROFILE'] or update.get('mode') != 'official'
            or not selected or selected.get('profile') != SERVICE_PROFILE or not isinstance(value, dict)
            or value.get('profile') != SERVICE_PROFILE or value.get('signature_verified') is not False
            or value.get('environment') != sd['effective_env'](SERVICE_PROFILE)
            or value.get('environment_activation') != 'selected-observer-constructor-after-native-pins'):
        raise ValueError('Stock trust activation contract differs')
    pinned = selected['pinned_key']
    if u['record'](pinned['path']) != pinned:
        raise ValueError('Stock independent pinned PEM identity differs')
    data = sd['_pinned_snapshot'](pinned['path'])
    trust = update['sd_read_observation']['trust_key']
    if trust.get('profile') != SERVICE_PROFILE or not any(row == pinned for row in trust['sources']):
        raise ValueError('Stock trust provisioning source differs')
    sd['trust_preflight'](root, trust)
    if sd['_pinned_snapshot'](root / RUNTIME / 'sony-original.pem') != data:
        raise ValueError('Stock pinned runtime asset differs')
    emitted = sd['observer_source'](sd['initialize_contract'](root), sd['trust_contract'](root), trust_profile=SERVICE_PROFILE)
    if Path(value['source']['path']).read_text(encoding='ascii') != emitted:
        raise ValueError('Stock trust activation source differs')
    for now, old in ((u['record'](value['source']['path']), value['source']),
                     (u['record'](root / 'simulation/p1-sd-observer.so'), value['observer'])):
        if any(now[k] != old[k] for k in ('bytes', 'sha256')):
            raise ValueError('Stock trust activation bytes differ')
    if (root / 'etc/ld.so.preload').read_text(encoding='ascii') != sd['PRELOAD']:
        raise ValueError('Stock trust preload order differs')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pinned-key', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='Fresh selection receipt path')
    args = parser.parse_args(); os.umask(0o077)
    print(json.dumps(provision(args.pinned_key, args.output), indent=2))


if __name__ == '__main__':
    main()
