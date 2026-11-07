#!/usr/bin/env python3
"""Explicit version-only 2.02 + original P1 virtual writer composition; host only.

attest_package() independently checks the existing diagnostic repack; it never
packages arbitrary payloads. authorize() binds it to the existing source/before/
clone receipt. configure()/preflight()/bindings() are the builder/runner API.
restore() makes a fresh virtual instance from before after the owner lease exits.
No API starts QEMU, opens USB or accepts a physical block device.
"""
import argparse
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import stat
import struct
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
PROFILE = 'original-p1-virtual-dev-install-v1'
MODE = 'virtual-dev-sd-update-v1'
SCHEMA = 'a7c2-p1-dev-install-authorization-v1'
FILE_PACKAGE_SCHEMA = 'a7c2-p1-dev-fixed-system-file-package-v1'
PACKAGE_SCHEMA = 'a7c2-p1-dev-version-only-package-v1'
STOCK_SHA = 'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
DERIVED_SHA = '54345cd3211172f011b5e492a85c48baee344f648facf83d264b7f0b06ef491a'
PACKAGE_BYTES = 1139929560
PLAIN_SHA = '03eee07301010ff644fae1073f7c7f6dd2d60278f18aa3e6053938d5f1426d1f'
MODEL, REGION = 0x20030014, 0
KEY_SHA = '8281413b5607446939613e07d020b2c7d8ee2371349099de56bc8288f7be0a43'
KEY_PROFILE = 'virtual-p1-pinned-key-trust-v1'
ENV = {'A7C2_FILE_MEDIA_TEST': '1', 'A7C2_P1_FILE_MEDIA_PROFILE': 'original-sd-v1',
       'A7C2_P1_DEV_INSTALL': 'version-only-2.02'}
RECEIVER = 'usr/lib/libsdfileinputupdaterapi.so'
CHUNK = 1024 * 1024


def api(name='update-boot.py'):
    return runpy.run_path(str(HERE / name))


def selection(profile, mode, allow_dev_signature_bypass):
    if profile != PROFILE or mode != MODE or allow_dev_signature_bypass is not True:
        raise ValueError('Explicit dev install profile/mode and allow_dev_signature_bypass=True required')


def admit(profile, *, mode, read_only, allow_updater_writes, media, sd, module,
          allow_dev_signature_bypass=False):
    selection(profile, mode, allow_dev_signature_bypass)
    if read_only is not False or allow_updater_writes is not True or not media or sd is None:
        raise ValueError('Dev install requires explicit media/SD/read_only=False/allow_updater_writes=True')
    api('newp1-virtual-install.py')['module_admission'](module)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]\.[0-9]{2}', value):
        raise ValueError('Explicit numeric current firmware version required')
    return tuple(map(int, value.split('.')))


def _plain_diff(before, after, expected_header):
    """Compare every decoded byte; input streams already validate encrypted blocks."""
    old_header, new_header = before.read(512), after.read(512)
    if new_header != expected_header or len(old_header) != 512:
        raise ValueError('Only the approved FDAT version/header CRC change is allowed')
    old_hash, new_hash = hashlib.sha256(old_header), hashlib.sha256(new_header)
    count = 512
    while True:
        old, new = before.read(CHUNK), after.read(CHUNK)
        if old != new:
            raise ValueError('Arbitrary decrypted payload difference refused')
        if not old:
            break
        count += len(old)
        if count > 2 * PACKAGE_BYTES:
            raise ValueError('Decoded payload exceeds explicit size bound')
        old_hash.update(old); new_hash.update(new)
    return dict(bytes=count, original_sha256=old_hash.hexdigest(), sha256=new_hash.hexdigest(),
                only_header_version_and_crc_changed=True, all_payload_bytes_identical=True,
                changed_plaintext_ranges=[dict(offset=8, bytes=4), dict(offset=32, bytes=2)])


def _encoded_diff(v, old, new, chunks):
    """Repack helper's exact envelope: only first ECB header and DEND CRC differ."""
    offset, size = chunks[b'FDAT']
    if old.info.st_size != new.info.st_size or size < 272 or (size - 272) % 1024:
        raise ValueError('Encrypted package size/geometry differs')
    end = chunks[b'DEND'][0]
    for start, length in ((0, offset), (offset + 512, end - offset - 512)):
        if v['_hash'](old.fd, start, length) != v['_hash'](new.fd, start, length):
            raise ValueError('Repack changed UFU prefix/chunks/IV/footer or encrypted payload')
    return dict(only_first_encrypted_header_and_dend_crc_changed=True,
                ufuprefix_chunks_iv_footer_preserved=True)


def attest_package(official, derived, output, *, fwtool_dir, current_version, profile, mode,
                   allow_dev_signature_bypass=False):
    """Offline readback of an existing repack; no packer, writer or runtime bypass."""
    selection(profile, mode, allow_dev_signature_bypass)
    if version('2.02') <= version(current_version):
        raise ValueError('New version must be strictly higher than current; UUD remains enabled')
    u = api(); v = api('virtual-update.py')
    official, derived, output = map(u['absolute'], (official, derived, output))
    if official == derived:
        raise ValueError('Official and derived input must be separate files')
    output.mkdir(mode=0o700)
    with ExitStack() as stack:
        sources = []
        reports = []
        for name, path, expected in (('official', official, STOCK_SHA), ('derived', derived, DERIVED_SHA)):
            source = v['_Source'](path); stack.callback(source.close); sources.append(source)
            if source.sha256 != expected or source.info.st_size != PACKAGE_BYTES:
                raise ValueError('Only the exact official 2.01 / version-only 2.02 pair is supported')
            scratch = output / name; scratch.mkdir(mode=0o700)
            fd = v['FAT'].secure_open(scratch, directory=True)
            try:
                reports.append(v['_inspect_package'](source, fd))
            finally:
                os.close(fd)
        if reports[0]['signature']['status'] != 'valid' or reports[1]['signature']['status'] != 'invalid':
            raise ValueError('Require valid official signature and explicitly invalid derived signature')
        dat, fdat = v['IMPORT'].vendor(u['absolute'](fwtool_dir))
        # Reuse the existing header implementation without reconfiguring its packer globals.
        builder = runpy.run_path(str(HERE.parents[1] / 'analysis/build_sony_info.py'))
        streams = [stack.enter_context(os.fdopen(os.dup(s.fd), 'rb')) for s in sources]
        layouts = [v['IMPORT'].chunks(s) for s in streams]
        if layouts[0] != layouts[1]:
            raise ValueError('UFU chunk layout differs')
        encoded = _encoded_diff(v, *sources, layouts[0][1])
        decoded = [fdat.decryptFdat(dat.readDat(s).firmwareData)[1] for s in streams]
        header = decoded[0].read(512); decoded[0].seek(0)
        expected = bytes(builder['version_header'](header, '2.02'))
        if (header[32:34] != b'\x01\x02' or header[16:17] != b'U' or header[20:21] != b'N'):
            raise ValueError('Original FDAT version/mode/LUW differs')
        plain = _plain_diff(*decoded, expected)
        if plain['original_sha256'] != PLAIN_SHA:
            raise ValueError('Decrypted official full-image SHA differs')
        for source in sources: source.verify()
        result = dict(schema=PACKAGE_SCHEMA, profile=PROFILE, mode=MODE, virtual_only=True,
            delta='version-only-2.02', supported_payload_changes=False,
            original=u['record'](official), derived=u['record'](derived),
            original_signature=reports[0]['signature'], signature=reports[1]['signature'],
            outer_crc_valid=True, all_decrypted_block_checks_valid=True, header_crc_valid=True,
            original_version='2.01', new_version='2.02', current_version=current_version,
            model=struct.unpack_from('<I', header, 36)[0], region=struct.unpack_from('<I', header, 40)[0],
            plain=plain, encoded=encoded, original_core_elfs_unchanged=True,
            installation_verified=False, guest_signature_verified=False, bypass_executed=False,
            physical_devices_used=False)
        u['DISK']['save'](output / 'dev-package.json', result)
        return result


def package_contract(receipt_path, receipt_sha256, *, output_root=None):
    u = api(); value, row = u['checked_json'](receipt_path)
    if value.get('schema') == FILE_PACKAGE_SCHEMA:
        options = {} if output_root is None else dict(output_root=output_root)
        return api('p1-dev-file-package.py')['contract'](receipt_path, receipt_sha256, **options)
    if (row['sha256'] != receipt_sha256 or value.get('schema') != PACKAGE_SCHEMA
            or value.get('profile') != PROFILE or value.get('mode') != MODE
            or value.get('virtual_only') is not True or value.get('delta') != 'version-only-2.02'
            or value.get('supported_payload_changes') is not False
            or value.get('signature', {}).get('status') != 'invalid'
            or value.get('original_signature', {}).get('status') != 'valid'
            or value.get('original_version') != '2.01' or value.get('new_version') != '2.02'
            or value.get('model') != MODEL or value.get('region') != REGION
            or value.get('physical_devices_used') is not False
            or value.get('installation_verified') is not False or value.get('guest_signature_verified') is not False
            or value.get('bypass_executed') is not False):
        raise ValueError('Dev package receipt hash/profile/invalid-signature policy differs')
    for flag in ('outer_crc_valid', 'all_decrypted_block_checks_valid', 'header_crc_valid', 'original_core_elfs_unchanged'):
        if value.get(flag) is not True: raise ValueError('Dev package validation missing: ' + flag)
    if (value.get('plain', {}).get('original_sha256') != PLAIN_SHA
            or value['plain'].get('all_payload_bytes_identical') is not True
            or value['plain'].get('only_header_version_and_crc_changed') is not True
            or value.get('encoded') != dict(only_first_encrypted_header_and_dend_crc_changed=True,
                                           ufuprefix_chunks_iv_footer_preserved=True)):
        raise ValueError('Dev package full-diff proof differs')
    for name, expected in (('original', STOCK_SHA), ('derived', DERIVED_SHA)):
        actual = u['record'](value[name]['path'])
        if actual['sha256'] != expected or actual['bytes'] != PACKAGE_BYTES or any(
                actual[k] != value[name][k] for k in ('device', 'inode', 'bytes', 'sha256')):
            raise ValueError('Dev package input identity/hash differs: ' + name)
    if version(value['new_version']) <= version(value['current_version']):
        raise ValueError('Dev package version is not strictly newer')
    return dict(receipt=row, value=value)


def authorize(instance, clone_receipt, clone_receipt_sha256, package_receipt, package_receipt_sha256,
              output, *, profile, mode, allow_dev_signature_bypass=False, output_root=None):
    selection(profile, mode, allow_dev_signature_bypass)
    u = api(); original = api('newp1-virtual-install.py')
    clone = original['clone_contract'](instance, clone_receipt, clone_receipt_sha256)
    options = {} if output_root is None else dict(output_root=output_root)
    package = package_contract(package_receipt, package_receipt_sha256, **options)
    value = dict(schema=SCHEMA, profile=PROFILE, mode=MODE, allow_dev_signature_bypass=True,
                 clone_receipt=clone['receipt'], package_receipt=package['receipt'],
                 physical_devices_used=False, installation_verified=False)
    output = u['absolute'](output)
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n'); stream.flush(); os.fsync(stream.fileno())
    return clone_contract(instance, output, u['record'](output)['sha256'], **options)


def clone_contract(instance, receipt_path, receipt_sha256, *, output_root=None):
    u = api(); value, row = u['checked_json'](receipt_path)
    if (row['sha256'] != receipt_sha256 or value.get('schema') != SCHEMA
            or value.get('physical_devices_used') is not False or value.get('installation_verified') is not False):
        raise ValueError('Dev authorization receipt hash/schema/policy differs')
    selection(value.get('profile'), value.get('mode'), value.get('allow_dev_signature_bypass'))
    c, p = value['clone_receipt'], value['package_receipt']
    clone = api('newp1-virtual-install.py')['clone_contract'](instance, c['path'], c['sha256'])
    package = package_contract(p['path'], p['sha256'],
                               **({} if output_root is None else dict(output_root=output_root)))
    return dict(receipt=row, profile=PROFILE, value=clone['value'], clone_contract=clone,
                package_contract=package, exclusive_clone_required=True, rollback=clone['rollback'])


def authorization(binding):
    return PROFILE + ' ' + binding['receipt']['sha256'] + ' ' + binding['value']['clone']['sha256'] + '\n'


def package(path, output, *, binding, output_root=None):
    """Builder counterpart of stock package(); invalid signatures never enter stock API."""
    u = api(); p = package_contract(binding['package_contract']['receipt']['path'],
                                binding['package_contract']['receipt']['sha256'],
                                **({} if output_root is None else dict(output_root=output_root)))
    if p != binding['package_contract']:
        raise ValueError('Dev package authorization changed')
    actual = u['record'](u['absolute'](path))
    if any(actual[k] != p['value']['derived'][k] for k in ('device', 'inode', 'bytes', 'sha256')):
        raise ValueError('Selected BODYDATA is not the authorized dev package')
    signature = (p['value']['proof']['signature'] if p['value'].get('schema') == FILE_PACKAGE_SCHEMA
                 else p['value']['signature'])
    return dict(bytes=actual['bytes'], sha256=actual['sha256'], signature=signature,
                outer_crc_valid=True, profile=PROFILE, version='2.02', receipt=p['receipt'])


def _stock_contract(root):
    """Run unchanged stock validators on a private reconstructed, hash-pinned view."""
    root = Path(root); u = api(); sd = api('p1-sd-read-probe.py'); dev = api('dev-update-profile.py')
    samples = dict(api('p1-file-media-contract.py')['SAMPLES'], core=sd['CORE'])
    with tempfile.TemporaryDirectory(prefix='p1-dev-abi-', dir=root.parent) as temporary:
        view = Path(temporary)
        for name, size, digest in samples.values():
            data = (root / name).read_bytes()
            if name == RECEIVER:
                data = data[:dev['_PATCH_OFFSET']] + dev['_ORIGINAL'] + data[dev['_PATCH_OFFSET'] + 4:]
            if len(data) != size or u['sha'](data) != digest:
                raise ValueError('Dev source ABI differs: ' + name)
            target = view / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
        return (api('p1-file-media-contract.py')['inspect'](view), sd['initialize_contract'](view))


def install_environment(binding):
    value = binding['package_contract']['value']
    if value.get('schema') == FILE_PACKAGE_SCHEMA:
        if value.get('kind') != 'p15-qemu-packaged-system-check-v1':
            raise ValueError('Unknown fixed system-file kind')
        return dict(ENV, A7C2_P1_DEV_INSTALL='fixed-system-file-v1')
    elif value.get('schema') == PACKAGE_SCHEMA and value.get('delta') == 'version-only-2.02':
        return dict(ENV)
    else:
        raise ValueError('Unknown exact dev package schema/version kind')


def file_media_selection(update):
    """Only the existing explicitly authorized DEV install can derive its hook."""
    selection(update.get('install_profile'), update.get('mode'), update.get('allow_dev_signature_bypass'))
    if (update.get('read_only') is not False or update.get('allow_updater_writes') is not True
            or update.get('bypass_configured') is not True
            or any(update.get(k) is not None for k in ('tail_profile', 'newdecrypt_profile', 'pmbp_profile', 'pmbp'))):
        raise ValueError('DEV identity adapter requires writable authorized install with Tail/CBC/PMBP off')
    binding = update['virtual_install']; value = binding['package_contract']['value']
    if (binding.get('profile') != PROFILE or value.get('profile') != PROFILE or value.get('mode') != MODE
            or value.get('original_version') != '2.01' or value.get('new_version') != '2.02'
            or value.get('virtual_only') is not True or version('2.02') <= version(value.get('current_version'))):
        raise ValueError('DEV identity adapter package/profile/version differs')
    environment = install_environment(binding)
    return api('p1-dev-receiver-identity.py')['selection'](profile=PROFILE, mode=MODE,
        install_kind=environment['A7C2_P1_DEV_INSTALL'], environment=environment, authorization=authorization(binding))


def file_media_source(root, update, output):
    return api('p1-dev-receiver-identity.py')['prepare'](root, update, output, selected=file_media_selection(update))


def file_media_command(root, prepared):
    return api('p1-dev-receiver-identity.py')['compile_argv'](prepared['source']['path'], root,
        prepared['compiler']['path'], prepared['linker']['path'])


def file_media_seal(root, update, prepared, command):
    return api('p1-dev-receiver-identity.py')['seal'](root, update, prepared, command,
        selected=file_media_selection(update))


def file_media_preflight(root, update):
    return api('p1-dev-receiver-identity.py')['verify'](root, update, selected=file_media_selection(update))


def binding_rows(root, contract, *, trusted_key_model=None, pmbp=None):
    rows = api('p1-sd-read-probe.py')['binding_rows'](root, contract, trusted_key_model=trusted_key_model, pmbp=pmbp)
    identity = api('p1-dev-receiver-identity.py')
    names = list(identity['RUNTIME_FILES']) + ['lib/' + name for name in identity['LIBRARIES']]
    rows += [api()['record'](Path(root) / name) for name in names]
    return sorted({row['path']: row for row in rows}.values(), key=lambda row: row['path'])


def bootstrap_source(*, install_kind='version-only-2.02'):
    """A separate bootstrap; original official/RO bootstrap is never edited."""
    if install_kind not in ('version-only-2.02', 'fixed-system-file-v1'):
        raise ValueError('Unknown explicit dev package bootstrap kind')
    text = (HERE / 'guest/update-storage-bootstrap').read_text(encoding='ascii')
    text = text.replace('original-p1-virtual-install-v1', PROFILE)
    old = '[ "$($bb cat /simulation/update-profile)" = official ] || return 125'
    if text.count(old) != 1: raise ValueError('Unknown original install guard bootstrap')
    text = text.replace(old, '[ "$($bb cat /simulation/update-profile)" = ' + MODE + ' ] || return 125\n'
        '    [ "$A7C2_P1_DEV_INSTALL" = version-only-2.02 ] || return 125\n'
        '    [ "$($bb cat /simulation/dev-authorization)" = ' + PROFILE + ' ] || return 125')
    marker = '        export A7C2_P1_FILE_MEDIA_PROFILE=original-sd-v1\n'
    if text.count(marker) != 1: raise ValueError('Unknown original SD environment bootstrap')
    return text.replace(marker, marker + '        export A7C2_P1_DEV_INSTALL=version-only-2.02\n').replace(
        'version-only-2.02', install_kind)


def portable(value):
    if isinstance(value, dict):
        return {k: portable(v) for k,v in value.items() if k not in ('path', 'device', 'inode')}
    if isinstance(value, list): return [portable(v) for v in value]
    return value


def resource_preflight(update, root):
    """Same original resources, trusted Backup, fixed module and provider as stock."""
    u = api(); sd = api('p1-sd-read-probe.py'); media_api = api('p1-media-init-probe.py')
    contract = update['original_resources']; receipt = contract['media_receipt']['path']
    actual = u['original_resource_contract'](Path(root), update['p1']['kernel.img'], receipt)
    if portable(actual) != portable(contract) or [r['path'] for r in actual['modules']] != update['original_module_allowlist']:
        raise ValueError('Dev original module/assets/ABI/provider resources drift')
    media, _ = media_api['check'](Path(root), update['p1']['kernel.img'], receipt)
    qemu = u['record'](media['qemu']['path'])
    if qemu['sha256'] != sd['QEMU_SHA'] or any(qemu[k] != media['qemu'][k] for k in ('bytes', 'sha256')):
        raise ValueError('Dev install requires exact original-P1 MMC QEMU provider')
    backup = update['p2'].get('backup', {})
    if (not update['p2']['sd_dispatch_eligible'] or backup.get('sha256') != media_api['BACKUP_SHA']
            or backup.get('size') != media_api['BACKUP_BYTES']):
        raise ValueError('Dev install requires actual mode5 and unchanged trusted Backup')
    module = u['record'](Path(root) / 'simulation/sony_persistent_flash.ko')
    receipts = update['module_contract']['receipts']
    checked = u['module_contract'](module, update['p1']['kernel.img'], receipts[0]['path'],
                                  receipts[1]['path'] if len(receipts) > 1 else None)
    if checked != update['module_contract']: raise ValueError('Dev fixed persistent module contract drift')


def trusted_key_api(selection):
    """Main owns this separate provider; absence or implicit opt-in stays rejected."""
    if selection is None: return None
    if (not isinstance(selection, dict) or set(selection) != {'profile', 'receipt', 'receipt_sha256'}
            or selection['profile'] != KEY_PROFILE
            or not isinstance(selection['receipt_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', selection['receipt_sha256'])):
        raise ValueError('Explicit pinned-key profile and SHA-bound receipt required')
    _, row = api()['checked_json'](selection['receipt'])
    if row['sha256'] != selection['receipt_sha256']: raise ValueError('Pinned-key receipt hash differs')
    if not (HERE / 'p1-trusted-key-model.py').is_file():
        raise ValueError('Main pinned-key provider is not integrated; verifyKey remains unchanged')
    return api('p1-trusted-key-model.py')


def key_model_contract(root, selection, model):
    if selection is None:
        if model is not None: raise ValueError('Pinned-key model lacks explicit selection')
        return
    sd = api('p1-sd-read-probe.py'); u = api(); root = Path(root)
    if (not isinstance(model, dict) or model.get('profile') != KEY_PROFILE or model.get('selection') != selection
            or model.get('signature_verified') is not False or not model.get('sources') or not model.get('assets')
            or not isinstance(model.get('preload'), str) or not model['preload'].startswith(sd['PRELOAD'])):
        raise ValueError('Pinned-key model requires source/asset/preload contract; no signature pass claim')
    key = u['record'](root / 'etc/VerificationKey.pem')
    if key['bytes'] != 451 or key['sha256'] != KEY_SHA:
        raise ValueError('Pinned-key model changed original verification key')
    for name, row in model['assets'].items():
        if (not isinstance(name, str) or not name.startswith('simulation/')
                or any(p in ('', '.', '..') for p in name.split('/'))):
            raise ValueError('Pinned-key assets must stay in simulation/')
        actual = u['record'](root / name)
        if any(actual[k] != row[k] for k in ('bytes', 'sha256')):
            raise ValueError('Pinned-key model asset differs: ' + name)
    source = u['record'](HERE / 'p1-trusted-key-model.py')
    if not any(all(row.get(k) == source[k] for k in ('path', 'bytes', 'sha256')) for row in model['sources']):
        raise ValueError('Pinned-key provider source is not bound')


def configure(root, update, output, *, profile=PROFILE):
    u = api(); sd = api('p1-sd-read-probe.py'); root = Path(root); output = Path(output); sim = root / 'simulation'
    admit(profile, mode=update['mode'], read_only=update['read_only'], allow_updater_writes=update['allow_updater_writes'],
          allow_dev_signature_bypass=update['allow_dev_signature_bypass'], media=update['original_resources'],
          sd=update['sd'], module=update['module_contract'])
    resource_preflight(update, root)
    package(Path(update['sd_read_package_source']['path']), output, binding=update['virtual_install'],
            output_root=output / 'dev-preflight')
    environment = install_environment(update['virtual_install'])
    expected_package = update['virtual_install']['package_contract']['value']['derived']
    current = update['p2'].get('firmware_version', {})
    if version('2.02') <= version(current.get('version')):
        raise ValueError('Actual p2 current version is not below dev 2.02; UUD is not bypassed')
    sd['single_body_fat'](update['sd']['image']['path'], output)
    if (update['sd']['fat_bits'] != 32 or update['sd']['bodydata']['sha256'] != expected_package['sha256']
            or update['sd']['bodydata']['size'] != PACKAGE_BYTES):
        raise ValueError('Dev SD FAT32/package binding differs')
    receiver = api('dev-update-profile.py')['verify_derived_receiver'](root / RECEIVER, update['receiver'])
    contract, initialization = _stock_contract(root)
    initialization = api('p1-dev-receiver-identity.py')['observer_contract'](initialization)
    hook = update['file_media']
    source = output / 'p1-sd-observer.c'; source.write_text(sd['observer_source'](initialization), encoding='ascii')
    u['command'](['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
        '-fexceptions', '-funwind-tables', '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC',
        source, root / 'lib/libc-2.25.so', root / 'lib/libdl-2.25.so', root / 'lib/ld-2.25.so',
        '-o', sim / 'p1-sd-observer.so'], output, 'sd-observer-build')
    for name, text in {'sd-read-profile': PROFILE + '\n', 'sd-read-env': ''.join(f'{k}={v}\n' for k,v in environment.items()),
                       'install-authorization': authorization(update['virtual_install']),
                       'dev-authorization': PROFILE + '\n'}.items():
        (sim / name).write_text(text, encoding='ascii')
    (root / 'init').write_text(bootstrap_source(install_kind=environment['A7C2_P1_DEV_INSTALL']), encoding='ascii'); (root / 'init').chmod(0o755)
    (root / 'etc/ld.so.preload').write_text(sd['PRELOAD'], encoding='ascii')
    target = root / 'sbin/sdfileinput.elf'
    if os.path.lexists(target): raise ValueError('SD receiver adapter already exists')
    target.symlink_to('/init')
    selection = update.get('trusted_key_model_selection')
    provider = trusted_key_api(selection)
    model = provider['configure'](root, update, output, selection=selection) if provider else None
    key_model_contract(root, selection, model)
    if model and (root / 'etc/ld.so.preload').read_text(encoding='ascii') != model['preload']:
        raise ValueError('Pinned-key provider preload readback differs')
    update['trusted_key_model'] = model
    file_media_preflight(root, update)
    rows = binding_rows(root, contract, trusted_key_model=model)
    for name, text in sd['binding_texts'](root, rows).items():
        (root / name).write_text(text, encoding='ascii')
    return dict(profile=PROFILE, source_kind='functional-adapter', no_install=False, environment=environment,
        trusted_key_model=model,
        target_block_readonly_count=0, target_block_writable_count=20, source_contract=contract,
        initialize_contract=initialization, hook=hook, observer_source=u['record'](source),
        observer=u['record'](sim / 'p1-sd-observer.so'), bindings=rows, receiver=receiver,
        package=update['sd_read_package'], package_source=update['sd_read_package_source'],
        coverage=False, read_verified=False, bypass_configured=True, bypass_executed=False,
        bodywriter_completed=False, installation_verified=False)


def bindings(root, card, *, trusted_key_model=None, pmbp=None):
    root = Path(root); result = api('p1-sd-read-probe.py')['bindings'](root, card,pmbp=pmbp)
    names = ['simulation/update-profile', 'simulation/dev-authorization', 'simulation/sony_persistent_flash.ko',
             'simulation/media-profile', 'simulation/original-modules']
    identity = api('p1-dev-receiver-identity.py')
    names += list(identity['RUNTIME_FILES']) + ['lib/' + name for name in identity['LIBRARIES']]
    original = api()['RESOURCE_MODULES']
    media = api('p1-media-init-probe.py')
    names += list(original) + ['usr/kmod/' + name + '.ko' for name in media['EXTRA']]
    names += ['etc/DmmConfig.bin', 'etc/ulogio.bin', 'usr/lib/libosal_uipc.so',
              'usr/lib/libbackup.so', 'usr/bin/ud_get_power_ic_type.elf', 'etc/VerificationKey.pem']
    if trusted_key_model:
        if set(trusted_key_model['assets']) & set(names + list(result)):
            raise ValueError('Pinned-key asset collides with existing dev binding')
        names += list(trusted_key_model['assets'])
    for name in names:
        path = root / name; data = path.read_bytes()
        result[name] = dict(mode=path.stat().st_mode, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return result


def preflight(update, root, read_only, media, profile, *, allow_updater_writes, allow_dev_signature_bypass=False):
    u = api(); root = Path(root); sd = api('p1-sd-read-probe.py')
    admit(profile, mode=update['mode'], read_only=read_only, allow_updater_writes=allow_updater_writes,
          allow_dev_signature_bypass=allow_dev_signature_bypass, media=media, sd=update.get('sd'), module=update['module_contract'])
    resource_preflight(update, root)
    binding = update['virtual_install']
    environment = install_environment(binding)
    output_options = (dict(output_root=Path(update['output']) / 'dev-preflight')
                      if binding['package_contract']['value'].get('schema') == FILE_PACKAGE_SCHEMA else {})
    if clone_contract(update['instance']['path'], binding['receipt']['path'], binding['receipt']['sha256'],
                      **output_options) != binding:
        raise ValueError('Dev clone/package authorization differs')
    package(update['sd_read_package_source']['path'], update['output'], binding=binding, **output_options)
    value = update.get('sd_read_observation') or {}
    if (value.get('profile') != PROFILE or value.get('environment') != environment or value.get('no_install') is not False
            or value.get('target_block_writable_count') != 20 or value.get('target_block_readonly_count') != 0
            or update.get('bypass_configured') is not True or value.get('bypass_configured') is not True):
        raise ValueError('Dev source/environment/write binding differs')
    if any((root / 'simulation' / n).exists() for n in ('sd-no-install', 'read-only-probe', 'block-readonly-verified')):
        raise ValueError('Dev install mixed with RO markers')
    if len(update['original_module_allowlist']) != 12:
        raise ValueError('Dev install requires all twelve exact original modules')
    receiver = api('dev-update-profile.py')['verify_derived_receiver'](root / RECEIVER, update['receiver'])
    contract, initialization = _stock_contract(root)
    initialization = api('p1-dev-receiver-identity.py')['observer_contract'](initialization)
    file_media_preflight(root, update)
    if value.get('hook') != update['file_media']:
        raise ValueError('Dev observation hook contract differs')
    if receiver != value['receiver'] or (contract, initialization) != (value['source_contract'], value['initialize_contract']):
        raise ValueError('Dev receiver/original ABI drift')
    model, selection = update.get('trusted_key_model'), update.get('trusted_key_model_selection')
    key_model_contract(root, selection, model)
    provider = trusted_key_api(selection)
    if provider and provider['preflight'](update, root, selection=selection) != model:
        raise ValueError('Pinned-key provider preflight differs')
    if value.get('trusted_key_model') != model: raise ValueError('Pinned-key observation binding differs')
    pmbp=sd['selected_pmbp'](update,root)
    binding_root=Path(value.get('binding_root',Path(update['output'])/'root'))
    if pmbp is not None and binding_root.resolve()!=root.resolve():raise ValueError('Dev PMBP binding root differs')
    sd['binding_preflight'](root, value, binding_rows(root, contract, trusted_key_model=model,pmbp=pmbp),binding_root)
    expected = dict(bindings(root, update['sd']['image'], trusted_key_model=model,pmbp=pmbp))
    if pmbp is not None:
        names=('simulation/block-readonly','simulation/media-backup-query','simulation/media-profile',
               'simulation/original-modules','simulation/backup-file-source','simulation/install-target',
               'simulation/backup-trusted-file-load')+tuple(r['path'].lstrip('/') for r in update['original_resources']['modules'])
        for name in names:
            path=root/name;row=u['record'](path)
            expected[name]=dict(bytes=row['bytes'],sha256=row['sha256'],mode=path.lstat().st_mode)
    if expected != value['cpio_bindings']:
        raise ValueError('Dev prepared-root/CPIO binding drift')
    texts = {'init': bootstrap_source(install_kind=environment['A7C2_P1_DEV_INSTALL']), 'simulation/sd-read-profile': PROFILE + '\n',
        'simulation/update-profile': MODE + '\n', 'simulation/dev-authorization': PROFILE + '\n',
        'simulation/sd-read-env': ''.join(f'{k}={v}\n' for k,v in environment.items()),
        'simulation/install-authorization': authorization(binding),
        'etc/ld.so.preload': pmbp['preload'] if pmbp else model['preload'] if model else sd['PRELOAD']}
    for name, text in texts.items():
        if (root / name).read_text(encoding='ascii') != text: raise ValueError('Dev guard text differs: ' + name)
    rows = value['sources'] + value['bindings'] + [update['sd_read_package_source'], update['sd']['image'],
            update['p2']['firmware_version']['file']]
    if model: rows += model['sources']
    for row in rows:
        now = u['record'](row['path'])
        if any(now[k] != row[k] for k in ('bytes', 'sha256')): raise ValueError('Dev source/input changed: ' + row['path'])
    current = update['p2']['firmware_version']
    data = Path(current['file']['path']).read_bytes()
    if len(data) != 2 or f'{data[1]:x}.{data[0]:02x}' != current['version'] or version('2.02') <= version(current['version']):
        raise ValueError('Actual current firmware version proof differs')
    if u['record'](HERE / 'file-media-config.c')['sha256'] != sd['HOOK_SHA']:
        raise ValueError('Frozen hook source drift')
    sd['cpio_readback'](update['initrd']['path'], value['cpio_bindings'])
    if pmbp is not None:sd['tail_api']()['_cpio_owners'](update['initrd']['path'],set(api('pmbp-integration.py')['cpio_rows'](root,pmbp)))
    return value


def restore(receipt_path, receipt_sha256, output):
    """Restore current before, retaining user modifications; never a factory reseed."""
    u = api(); value, row = u['checked_json'](receipt_path)
    if row['sha256'] != receipt_sha256 or value.get('schema') != SCHEMA:
        raise ValueError('Unknown dev rollback receipt')
    selection(value.get('profile'), value.get('mode'), value.get('allow_dev_signature_bypass'))
    c = value['clone_receipt']
    return api('newp1-virtual-install.py')['restore'](c['path'], c['sha256'], output)


# The implementation and the twenty-node policy remain the stock guard verbatim.
_STOCK_INSTALL = api('newp1-virtual-install.py')
WRITE_GUARD, NODES, ranges = (_STOCK_INSTALL[k] for k in ('WRITE_GUARD', 'NODES', 'ranges'))
cpio_readback = api('p1-sd-read-probe.py')['cpio_readback']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    attest = commands.add_parser('attest-package')
    for name in ('official', 'derived', 'output', 'fwtool-dir'): attest.add_argument('--' + name, type=Path, required=True)
    attest.add_argument('--current-version', required=True)
    auth = commands.add_parser('authorize')
    for name in ('instance', 'clone-receipt', 'package-receipt', 'output'): auth.add_argument('--' + name, type=Path, required=True)
    for name in ('clone-receipt-sha256', 'package-receipt-sha256'): auth.add_argument('--' + name, required=True)
    auth.add_argument('--output-root', type=Path)
    for command in (attest, auth):
        command.add_argument('--profile', required=True, choices=(PROFILE,))
        command.add_argument('--mode', required=True, choices=(MODE,))
        command.add_argument('--allow-dev-signature-bypass', action='store_true', required=True)
    recovery = commands.add_parser('restore')
    recovery.add_argument('--receipt', type=Path, required=True); recovery.add_argument('--receipt-sha256', required=True)
    recovery.add_argument('--output', type=Path, required=True)
    args = vars(parser.parse_args()); action = args.pop('action'); os.umask(0o077)
    if action == 'restore': result = str(restore(args.pop('receipt'), args.pop('receipt_sha256'), **args))
    elif action == 'attest-package': result = attest_package(**args)
    else: result = authorize(**args)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
