#!/usr/bin/env python3
"""Build the original p1 updater for a leased, isolated persistent camera instance.

build(instance, runtime_analysis, output, *, bodydata=None, sd_image=None, mode=...,
      persistent_module=None, module_receipt=None, probe_receipt=None, original_resources=False)
returns update-boot.json (also on a failed build). `instance` is an instance path,
or the dictionary yielded by camera-disk.lease(); a caller-owned lease must remain
held through QMP shutdown. This module never launches QEMU or installs an update.
The required mode has no default. Official mode never derives a receiver.
"""
import argparse
from contextlib import nullcontext
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import re
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
FAT = runpy.run_path(str(HERE / 'fat_image.py'))
DISK = runpy.run_path(str(HERE / 'camera-disk.py'))
GEOMETRY = runpy.run_path(str(HERE / 'persistent-flash/geometry.py'))
MODES = ('official', 'virtual-dev-sd-update-v1')
KERNEL_SHA = '9812ab13f73e6a98d0113f9500853739edcd5bb06e2952c42295b9dae06c758e'
ROOT_SHA = '5c06d73623546939f864a74358ef8c103a99895d149c9af6c5cf10a0100007bd'
CHUNK = 1024 * 1024
PROTOCOL = 'project,a7c2-functional-persistent-flash-v1'
LEGACY_MODULE_SHA = 'cb602cc77e0d6bcac47b02844ff23edec86bd2b0a6abc8b118dfd15bbef39cb0'
LEGACY_PROBE_SHA = '582a690d9fee028c491553d1294a2cbe79fffb2d8626ce9159c9bdd146aa67bc'
CURRENT_MODULE_SHA = '5d069cd2c2eb5fbbd9d933e4768a65b0b71e3505fadcf245d5541a2e99a74383'
CURRENT_DRIVER_SHA = '15b6a84827a0d6e2925ea4fd6f9d17b6b820aedf0e6b790706b90ab4300b2b9f'
TRIM_STORAGE_PROFILE = 'virtual-p1-alfred-trim-zero-v1'
NEWDECRYPT_PROFILE = 'virtual-p1-cbc-scramble-v1'
TRIM_MODULE_SHA = '8aaea09a134293c7f5b498346abca60937c9fdffa27ff6fc579c65618a19f293'
TRIM_DRIVER_SHA = 'ba72f4d13dd12016868f55ac0c1a1fbcc9cd03df3a04e1e98ed6af690c81ec87'
TRIM_RECEIPT_SHA = '58d2af7234808a5d673b23d9a07bcb4ee2bd177c783463a8f1d4776649695805'
TRIM_SOURCE_SET_SHA = '7400ad52f7e0600a1ea66c8afdacb0e373c40fbd3c70bd9163ebf46de99f014b'
TRIM_ALIAS_SHA = '4490731995bc3a62dbd12fc6f113cce47bc060b2761e5c03d2b10975ae053537'
TRIM_INPUTS = {
    'build.py': '47625295a977b2f54fb786be52aac74a39cdc59b4f8326accd29207d4a8fcbe6',
    'module.patch': '6bff7baceaf0373ed48c53d8b1a2121fc7df7bd813d34e1a144661536ac353ab',
    'trim-zero.h': '8a8c8f7bf18727952d9323870378e75b54a9e226f69b0f64f3d738e24b3d8e02',
}
RESOURCE_MODULES = ('kmod/devno.ko', 'usr/kmod/osal_utm.ko', 'usr/kmod/osal_uipc.ko',
                    'usr/kmod/utimer.ko', 'usr/kmod/backup.ko', 'usr/kmod/osal_ulogio.ko', 'usr/kmod/dmm.ko')


def resource_symbols(path):
    from elftools.elf.elffile import ELFFile
    with Path(path).open('rb') as stream:
        elf = ELFFile(stream)
        symtab = elf.get_section_by_name('.symtab')
        if symtab is None:
            raise ValueError('Resource symbol table missing')
        undefined = sorted({s.name for s in symtab.iter_symbols() if s.name and s['st_shndx'] == 'SHN_UNDEF'})
        exports = []
        for section in ('__ksymtab', '__ksymtab_gpl'):
            table = elf.get_section_by_name(section)
            if table is None:
                continue
            relocs = elf.get_section_by_name('.rela' + section)
            if table['sh_size'] % 16 or relocs is None:
                raise ValueError('Resource export table/relocations missing')
            pointers = {r['r_offset']: r for r in relocs.iter_relocations()}
            if len(pointers) != table['sh_size'] // 8:
                raise ValueError('Resource export pointer count differs')
            for offset in range(0, table['sh_size'], 16):
                value, name = pointers[offset], pointers[offset + 8]
                target, string = (symtab.get_symbol(r['r_info_sym']) for r in (value, name))
                if (value['r_info_type'] != 257 or name['r_info_type'] != 257 or value['r_addend'] != 0
                        or target['st_shndx'] == 'SHN_UNDEF' or not isinstance(string['st_shndx'], int)):
                    raise ValueError('Resource export relocation differs')
                names = elf.get_section(string['st_shndx'])
                index = string['st_value'] + name['r_addend']
                raw = names.data()
                stop = raw.find(b'\0', index)
                if names.name != '__ksymtab_strings' or not 0 <= index < stop:
                    raise ValueError('Resource export string pointer differs')
                text = raw[index:stop].decode('ascii')
                if target.name != text or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', text):
                    raise ValueError('Resource export target/name differs')
                exports.append(dict(name=text, table=section, offset=offset, symbol_value=target['st_value'],
                                    string_offset=index))
        return undefined, exports


def original_resource_contract(root, kernel, media_receipt=None):
    """Original package identity supplies ABI; exports supply the load order."""
    api = runpy.run_path(str(HERE / 'p1-persistent-module.py'))
    media = media_row = None
    names = RESOURCE_MODULES
    if media_receipt is not None:
        media_api = runpy.run_path(str(HERE / 'p1-media-init-probe.py'))
        media, media_row = media_api['check'](root, kernel, media_receipt)
        names = RESOURCE_MODULES[:4] + ('usr/kmod/stream2.ko',) + RESOURCE_MODULES[4:] + tuple(
            'usr/kmod/' + name + '.ko' for name in media_api['EXTRA'] if name != 'stream2')
    inventory = api['original_modules'](root)
    providers, modules = {}, []
    raw = Path(kernel['path']).read_bytes()
    if sha(raw) != kernel['sha256']:
        raise ValueError('Resource kernel bytes differ')
    for name in names:
        path = root / name
        info = api['module_info'](path)
        api['require_abi'](info)
        imported, exported = resource_symbols(path)
        dependency = {n: providers[n] for n in imported if n in providers}
        kernel_exports = api['original_exports'](raw, sorted(set(imported) - dependency.keys()))
        if kernel_exports['missing']:
            raise ValueError('Original resource dependencies unavailable: ' + name + ' ' + str(kernel_exports['missing']))
        modules.append(dict(path='/' + name, file=info['file'], vermagic=info['vermagic'],
                            undefined_symbols=imported, exported_symbols=exported,
                            module_providers=dependency, kernel_exports=kernel_exports))
        providers.update({r['name']: '/' + name for r in exported})
    assets = {name: record(root / name) for name in ('etc/DmmConfig.bin', 'etc/ulogio.bin',
              'usr/lib/libosal_uipc.so', 'usr/bin/ud_get_power_ic_type.elf')}
    if media is not None:
        assets['usr/lib/libbackup.so'] = record(root / 'usr/lib/libbackup.so')
    result = dict(policy='original-p1-resources-v1', inventory_sha256=inventory['inventory_sha256'],
                inventory_count=inventory['count'], kernel_sha256=kernel['sha256'], modules=modules, assets=assets,
                force_load_allowed=False, original_arguments_preserved=True, guest_load_verified=False,
                physical_compatibility_verified=False)
    if media is not None:
        result.update(media_profile=media['profile'], media_receipt=media_row)
    return result


def checked_json(path):
    """Read the same ordinary FD whose hash is retained in the manifest."""
    path = absolute(path)
    fd = FAT['secure_open'](path)
    try:
        before = DISK['stamp'](fd)
        if before[2] > 16 * CHUNK:
            raise ValueError('Receipt exceeds input budget')
        raw = os.pread(fd, before[2], 0)
        if len(raw) != before[2] or DISK['stamp'](fd) != before:
            raise ValueError('Receipt changed while reading')
        return json.loads(raw), dict(path=str(path), bytes=len(raw), sha256=sha(raw))
    finally:
        os.close(fd)


def module_contract(module, kernel, module_receipt=None, probe_receipt=None):
    """Compilation, exercised read ABI and write eligibility are separate facts."""
    result = dict(protocol=PROTOCOL, build_bound=False, guest_read_path_verified=False,
                  large_io_fix_bound=False, updater_write_eligible=False, receipts=[])
    if module_receipt is None:
        if probe_receipt is not None:
            raise ValueError('Probe receipt requires module build receipt')
        return result
    receipt, source = checked_json(module_receipt)
    result['receipts'].append(source)
    if receipt.get('schema') == 'a7c2-p1-alfred-trim-zero-v1':
        if probe_receipt is not None:
            raise ValueError('Trim variant has no reviewed guest probe receipt')
        return alfred_trim_contract(module, kernel, receipt, source)
    if (receipt.get('schema') != 'a7c2-original-p1-persistent-module-v1'
            or receipt.get('status') != 'compiled' or receipt.get('force_load_allowed') is not False
            or receipt.get('exports', {}).get('status') != 'verified'
            or receipt.get('exports', {}).get('missing') != []):
        raise ValueError('Unverified original p1 module build receipt')
    for actual, expected in ((kernel, receipt['original_kernel']), (module, receipt['module']['file'])):
        if any(actual[k] != expected[k] for k in ('bytes', 'sha256')):
            raise ValueError('Module receipt does not bind actual kernel/module bytes')
    if (kernel['sha256'] != KERNEL_SHA or kernel['bytes'] != 6582280
            or receipt['module'].get('vermagic') != ['4.9.186-scel SMP preempt mod_unload aarch64']):
        raise ValueError('Module receipt original kernel/ABI differs')
    driver = receipt.get('driver_copies', {}).get('sony_persistent_flash.c')
    if not driver:
        raise ValueError('Module receipt lacks actual compiled driver source')
    actual_driver = record(driver['path'])
    if any(actual_driver[k] != driver[k] for k in ('bytes', 'sha256')):
        raise ValueError('Compiled driver source differs')
    # v4 has valid exercised reads but a known large-BIO write bug.
    fixed = driver['sha256'] == CURRENT_DRIVER_SHA and module['sha256'] == CURRENT_MODULE_SHA
    if not fixed and not (module['sha256'] == LEGACY_MODULE_SHA and driver['sha256'] ==
                          '850ec0d764a1cc3e1226318a82e82c9b8372390398623ee06b4214a999d9fd23'):
        raise ValueError('Unknown persistent protocol/driver implementation')
    result.update(build_bound=True, large_io_fix_bound=fixed, updater_write_eligible=fixed,
                  driver=actual_driver, module_sha256=module['sha256'], kernel_sha256=kernel['sha256'])
    if probe_receipt is not None:
        probe, source = checked_json(probe_receipt)
        result['receipts'].append(source)
        # Only the reviewed v1 receipt is trusted; a caller-authored true is not evidence.
        if source['sha256'] != LEGACY_PROBE_SHA or module['sha256'] != LEGACY_MODULE_SHA:
            raise ValueError('Probe receipt is not reviewed for these actual module bytes')
        probe_dir = absolute(probe_receipt).parent
        manifest, manifest_row = checked_json(probe_dir.parent / 'build/manifest.json')
        if (manifest_row['sha256'] != '9d4b72883879862a29df6f503138a5bc61e268f577236a4390f7270ba66766a2'
                or manifest['kernel']['sha256'] != kernel['sha256']
                or manifest['module']['sha256'] != module['sha256']):
            raise ValueError('Probe manifest/kernel/module binding differs')
        raw = (probe_dir / 'serial.log').read_bytes()
        probe_api = runpy.run_path(str(HERE / 'p1-module-probe.py'))
        replay = probe_api['collect'](raw, manifest)
        if (sha(raw) != probe.get('raw_serial_sha256') or not replay['guest_read_path_verified']
                or probe.get('verified') is not True or probe.get('disk_unchanged') is not True
                or probe.get('normal_exit_verified') is not True
                or probe.get('disk_before_sha256') != probe.get('disk_after_sha256')):
            raise ValueError('Probe raw evidence or clean read-only exit differs')
        result.update(guest_read_path_verified=True, probe_replay=replay)
    return result


def alfred_trim_contract(module, kernel, receipt, source):
    """Passive evidence contract; storage_selection separately authorizes activation."""
    if (source['sha256'] != TRIM_RECEIPT_SHA or receipt.get('status') != 'compiled'
            or receipt.get('profile') != 'virtual-storage-alfred-trim-zero-v1'
            or receipt.get('required_module_parameters') != {'functional_alfred_trim_zero': 1}
            or any(receipt.get(k) is not False for k in ('physical_compatibility', 'guest_verified',
                   'installation_verified', 'force_load_allowed', 'host_module_loaded', 'physical_devices_used'))
            or receipt.get('canonical_and_known_module_unchanged') is not True):
        raise ValueError('Unknown exact trim receipt/features/policy')
    native = runpy.run_path(str(HERE / 'p1-persistent-module.py'))
    inputs = [source]
    def bound(row):
        actual = record(row['path'])
        if any(actual[k] != row[k] for k in ('bytes', 'sha256')):
            raise ValueError('Trim source/module input differs: ' + row['path'])
        inputs.append(actual)
        return actual
    for name, digest in (('known_receipt', '36cec193d065b2aa3873d68a699980e5b04a8703a85aeb1a3ea3f679edbeff50'),
                         ('base_build_receipt', '46dc7febe8345ae810662917d0d1cc5549f9ec4147c37add0c5fda4ad95bd338')):
        if bound(receipt[name])['sha256'] != digest:
            raise ValueError('Trim native base receipt differs')
    known, _ = checked_json(receipt['known_receipt']['path'])
    base, _ = checked_json(receipt['base_build_receipt']['path'])
    old_module = bound(receipt['known_module'])
    old = module_contract(old_module, kernel, receipt['known_receipt']['path'])
    if not old['large_io_fix_bound'] or old_module['sha256'] != CURRENT_MODULE_SHA:
        raise ValueError('Trim known standard module contract differs')
    if (bound(receipt['canonical_base'])['sha256'] != CURRENT_DRIVER_SHA
            or record(HERE / 'persistent-flash/sony_persistent_flash.c')['sha256'] != CURRENT_DRIVER_SHA
            or set(receipt['inputs']) != set(TRIM_INPUTS)):
        raise ValueError('Trim canonical base/input set differs')
    for name, digest in TRIM_INPUTS.items():
        if (bound(receipt['inputs'][name])['sha256'] != digest
                or bound(dict(path=str(HERE / 'persistent-flash/alfred-trim' / name),
                              bytes=receipt['inputs'][name]['bytes'], sha256=digest))['sha256'] != digest):
            raise ValueError('Trim patch/header/builder differs')
    pins = dict(native['DRIVER_PINS'], **{'sony_persistent_flash.c': TRIM_DRIVER_SHA,
                                       'trim-zero.h': TRIM_INPUTS['trim-zero.h']})
    if set(receipt['variant_source']) != set(pins):
        raise ValueError('Trim generated source set differs')
    for name, digest in pins.items():
        if bound(receipt['variant_source'][name])['sha256'] != digest:
            raise ValueError('Trim generated source differs')
    if (native['json_sha'](pins) != TRIM_SOURCE_SET_SHA
            or receipt['variant_source_set_sha256'] != TRIM_SOURCE_SET_SHA):
        raise ValueError('Trim generated source-set hash differs')
    abi = dict(vermagic=[native['VERMAGIC']], struct_module_bytes=768, struct_module_alignment=64,
               versions_present=False, config_sha256=native['CONFIG_SHA'],
               source_tree_sha256=native['TREE_SHA'], original_modules_sha256=native['MODULES_SHA'])
    if (receipt['abi'] != abi or kernel['sha256'] != KERNEL_SHA or kernel['bytes'] != 6582280
            or receipt['kernel_sha256'] != KERNEL_SHA or base['status'] != 'compiled'
            or base['source']['tree_sha256'] != native['TREE_SHA']
            or base['original_modules']['inventory_sha256'] != native['MODULES_SHA']
            or base['generated_release']['value'] != native['RELEASE']):
        raise ValueError('Trim original native kernel/source/config ABI differs')
    for row in [base['builder'], base['original_kernel'], base['private_makefile'],
                base['generated_release']['file'], base['generated_release']['utsrelease'],
                *base['source']['pins'].values(), *base['driver'].values(), *base['driver_copies'].values(),
                base['config_derivation'][1]['output'], known['module']['file']]:
        bound(row)
    native['require_abi'](native['module_info'](bound(base['module']['file'])['path']))
    base_imports, _ = resource_symbols(base['module']['file']['path'])
    raw = Path(kernel['path']).read_bytes()
    if native['original_exports'](raw, base_imports) != base['exports']:
        raise ValueError('Trim native base kernel exports differ')
    actual_module = bound(receipt['module']['file'])
    if (actual_module['sha256'] != TRIM_MODULE_SHA or actual_module['bytes'] != 65112
            or any(module[k] != actual_module[k] for k in ('bytes', 'sha256'))):
        raise ValueError('Trim receipt does not bind exact actual module bytes')
    info = native['module_info'](module['path']); native['require_abi'](info)
    if ({k:v for k,v in info.items() if k != 'file'} != {k:v for k,v in receipt['module'].items() if k != 'file'}
            or 'functional_alfred_trim_zero:bool' not in info['modinfo'].get('parmtype', [])):
        raise ValueError('Trim actual module ABI/parameter differs')
    imports, _ = resource_symbols(module['path'])
    exports = native['original_exports'](raw, imports)
    if (len(imports) != 38 or imports != receipt['undefined_symbols']
            or exports != receipt['exports'] or exports['missing']):
        raise ValueError('Trim actual imports/original kernel exports differ')
    return dict(protocol=PROTOCOL, build_bound=True, guest_read_path_verified=False,
        large_io_fix_bound=True, updater_write_eligible=True, receipts=[source],
        driver=record(receipt['variant_source']['sony_persistent_flash.c']['path']),
        module_sha256=TRIM_MODULE_SHA, kernel_sha256=KERNEL_SHA, storage_profile=TRIM_STORAGE_PROFILE,
        storage_module=actual_module, storage_kernel=record(base['original_kernel']['path']),
        storage_inputs=list({r['path']: r for r in inputs}.values()), abi=abi, exports=exports,
        source_set_sha256=TRIM_SOURCE_SET_SHA, required_module_parameters={'functional_alfred_trim_zero': 1},
        physical_compatibility=False, guest_verified=False)


def storage_selection(profile, *, install_profile, read_only, allow_updater_writes, module=None):
    if profile is not None:
        if (profile != TRIM_STORAGE_PROFILE or install_profile not in
                ('original-p1-virtual-install-v1', 'original-p1-virtual-dev-install-v1')
                or read_only is not False or allow_updater_writes is not True):
            raise ValueError('Storage profile requires exact explicit P1 install/write selection')
    if module is not None and module.get('storage_profile') != profile:
        raise ValueError('Explicit storage profile and exact module contract differ')


def storage_parameter_text():
    return TRIM_STORAGE_PROFILE + ' ' + TRIM_MODULE_SHA + ' functional_alfred_trim_zero=1\n'


def storage_preflight(update, root, profile, *, read_only, allow_updater_writes):
    storage_selection(profile, install_profile=update.get('install_profile'), read_only=read_only,
                      allow_updater_writes=allow_updater_writes, module=update['module_contract'])
    if update.get('storage_profile') != profile:
        raise ValueError('Storage selection differs from update build')
    root = Path(root); parameter = root / 'simulation/storage-profile'
    if profile is None:
        if os.path.lexists(parameter):
            raise ValueError('Unexpected storage parameter file without explicit profile')
        return {}
    runpy.run_path(str(HERE / 'newp1-virtual-install.py'))['module_admission'](update['module_contract'])
    if any(os.path.lexists(root / 'simulation' / name) for name in
           ('read-only-probe', 'sd-no-install', 'block-readonly-verified')):
        raise ValueError('Trim storage mixed with read-only markers')
    if (parameter.is_symlink() or not parameter.is_file()
            or parameter.read_text(encoding='ascii') != storage_parameter_text()
            or stat.S_IMODE(parameter.stat().st_mode) != 0o600
            or record(root / 'simulation/sony_persistent_flash.ko')['sha256'] != TRIM_MODULE_SHA
            or record(root / 'simulation/create-aliases')['sha256'] != TRIM_ALIAS_SHA
            or record(HERE / 'persistent-flash/create-aliases.sh')['sha256'] != TRIM_ALIAS_SHA):
        raise ValueError('Trim actual parameter/module/nflasha4 alias mapping differs')
    result = {}
    for name in ('init', 'simulation/storage-profile', 'simulation/sony_persistent_flash.ko', 'simulation/create-aliases'):
        path = root / name; row = record(path)
        result[name] = dict(bytes=row['bytes'], sha256=row['sha256'], mode=path.stat().st_mode)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def absolute(path):
    raw = os.fspath(path)
    if any(p in ('.', '..') for p in raw.split('/')):
        raise ValueError('Dot components in host path')
    return Path(os.path.abspath(raw))


def record(path):
    fd = FAT['secure_open'](absolute(path))
    try:
        before = DISK['stamp'](fd)
        digest = DISK['hashed'](fd)
        if DISK['stamp'](fd) != before:
            raise ValueError('File changed while hashing: ' + str(path))
        return dict(path=str(path), bytes=before[2], sha256=digest,
                    device=before[0], inode=before[1])
    finally:
        os.close(fd)


def copy_range(fd, offset, size, destination):
    before = DISK['stamp'](fd)
    if offset < 0 or size < 0 or offset + size > before[2]:
        raise ValueError('Source range outside regular image')
    expected = DISK['hashed'](fd, offset, size)
    with destination.open('xb') as output:
        for pos in range(0, size, CHUNK):
            block = os.pread(fd, min(CHUNK, size - pos), offset + pos)
            if len(block) != min(CHUNK, size - pos):
                raise OSError('Short source range read')
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    result = record(destination)
    if (DISK['stamp'](fd) != before or result['sha256'] != expected
            or DISK['hashed'](fd, offset, size) != expected):
        raise ValueError('Source changed or destination readback differs')
    result.update(source_offset=offset, source_sha256=expected, readback_verified=True)
    return result


def copy_input(source, destination):
    fd = FAT['secure_open'](absolute(source))
    try:
        result = copy_range(fd, 0, os.fstat(fd).st_size, destination)
        result['source'] = record(absolute(source))
        if result['source']['sha256'] != result['sha256']:
            raise ValueError('Input path replaced during snapshot')
        result['source_opened_writable'] = False
        return result
    finally:
        os.close(fd)


def command(argv, output, name, *, cwd=None, env=None):
    timed_out = False
    rc = None
    with (output / (name + '.stdout')).open('xb') as stdout, (output / (name + '.stderr')).open('xb') as stderr:
        try:
            result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                                    stdout=stdout, stderr=stderr, timeout=180)
            rc = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
    row = dict(argv=[str(a) for a in argv], rc=rc, timed_out=timed_out,
               stdout=record(output / (name + '.stdout')), stderr=record(output / (name + '.stderr')))
    (output / (name + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    if rc != 0:
        raise RuntimeError(name + ' failed, rc=' + str(rc) + ', timed_out=' + str(timed_out))
    return row


def fat_view(image, output, name):
    """Keep nonzero partition tails; parse only the declared filesystem extent."""
    fd = FAT['secure_open'](image)
    try:
        b = os.pread(fd, 512, 0)
        if len(b) != 512:
            raise ValueError('Truncated FAT boot sector')
        total = (int.from_bytes(b[19:21], 'little') or int.from_bytes(b[32:36], 'little'))
        size = total * int.from_bytes(b[11:13], 'little')
        if not 512 <= size <= os.fstat(fd).st_size:
            raise ValueError('Invalid FAT declared extent')
        tail = dict(offset=size, bytes=os.fstat(fd).st_size - size,
                    sha256=DISK['hashed'](fd, size), retained_in=str(image))
        view = output / (name + '-filesystem.fat')
        copy_range(fd, 0, size, view)
    finally:
        os.close(fd)
    fat = FAT['FatImage'](view, output, mtools_dir='/usr/bin', fmask=0, dmask=0,
                          max_file_bytes=2 * 1024**3, max_total_bytes=3 * 1024**3)
    try:
        inventory = fat.inventory()
    except BaseException:
        fat.close()
        raise
    return fat, inventory, tail


def fat_extract(fat, inventory, name, destination):
    node = inventory['entries'].get(name)
    if node is None or node['kind'] != 'file':
        raise ValueError('Missing ordinary FAT input: ' + name)
    raw = fat.locations[name][1]
    cluster = int.from_bytes(raw[26:28], 'little')
    if fat.bits == 32:
        cluster |= int.from_bytes(raw[20:22], 'little') << 16
    fat.used = set()
    remaining = node['size']
    with destination.open('xb') as stream:
        for value in fat.chain(cluster, name):
            data = fat.read(fat.cluster_offset(value), min(remaining, fat.cluster_bytes))
            stream.write(data)
            remaining -= len(data)
    result = record(destination)
    if remaining or result['sha256'] != node['sha256']:
        raise ValueError('FAT input extraction digest differs')
    return result


def setting_state(inventory, *, serial=False):
    entries = inventory['entries']
    def present(name):
        return entries.get('/updater/' + name, {}).get('kind') == 'file'
    names = ('mode', 'mode1', 'mode2', 'mode3', 'mode5', 'mode6', 'mode7', 'comp', 'uincomp')
    flags = {name: present(name) for name in names}
    selected = 1
    if not serial and flags['mode']:
        selected = next((n for n in (3, 2, 6, 1, 5, 7) if flags['mode' + str(n)]), 0)
    return dict(files={name: entries.get('/updater/' + name) for name in names}, flags=flags,
                predicted_outer_mode=selected, prediction_only=True,
                uincomp_blocks_receiver=flags['uincomp'] and not serial,
                comp_removes_modes_before_receiver=flags['comp'] and selected != 1,
                sd_dispatch_eligible=selected == 5 and not flags['uincomp'] and not serial,
                guest_checked=False, normal_ap_frontend='notexecuted')


def tools(runtime):
    for candidate in sorted(runtime.glob('mtools-*/extracted/usr/bin')):
        if all((candidate / name).is_file() for name in ('mformat', 'mcopy')):
            return candidate
    raise ValueError('No existing mtools in runtime_analysis; no fallback card format')


def prepare_sd(bodydata, sd_image, runtime, output):
    if bodydata is None and sd_image is None:
        return None
    card = output / 'card.fat'
    source = None
    if sd_image is not None:
        if not 512 <= record(absolute(sd_image))['bytes'] <= 3 * 1024**3:
            raise ValueError('SD image exceeds the explicit RAM input budget')
        source = copy_input(sd_image, card)
    else:
        # A superfloppy FAT32 volume; input bytes are never extracted as update files.
        original = record(absolute(bodydata))
        size = max(128 * CHUNK, ((original['bytes'] + 96 * CHUNK + CHUNK - 1) // CHUNK) * CHUNK)
        if size > 3 * 1024**3:
            raise ValueError('BODYDATA exceeds virtual SD memory budget')
        with card.open('xb') as stream:
            stream.truncate(size)
        mt = tools(runtime)
        env = dict(PATH='/usr/bin:/bin', MTOOLSRC='/dev/null', MTOOLS_SKIP_CHECK='1', TZ='UTC')
        command([mt / 'mformat', '-F', '-i', card, '-T', str(size // 512),
                 '-h', '64', '-s', '32', '-v', 'A7C2UPDATE', '-N', '0xA7C20005', '::'],
                output, 'sd-format', env=env)
        fd = FAT['secure_open'](absolute(bodydata))
        try:
            before = DISK['stamp'](fd)
            # mcopy inherits this exact read-only descriptor; no pathname re-open.
            rc = None
            with (output / 'sd-copy.stdout').open('xb') as stdout, (output / 'sd-copy.stderr').open('xb') as stderr:
                try:
                    proc = subprocess.run([str(mt / 'mcopy'), '-i', str(card), '/proc/self/fd/' + str(fd),
                                           '::/BODYDATA.DAT'], pass_fds=(fd,), env=env,
                                          stdout=stdout, stderr=stderr, timeout=180)
                    rc = proc.returncode
                except subprocess.TimeoutExpired:
                    pass
            (output / 'sd-copy.json').write_text(json.dumps(dict(rc=rc, timed_out=rc is None,
                argv=[str(mt / 'mcopy'), '-i', str(card), '<read-only-input-fd>', '::/BODYDATA.DAT'],
                stdout=record(output / 'sd-copy.stdout'), stderr=record(output / 'sd-copy.stderr')), indent=2) + '\n')
            if rc != 0 or DISK['stamp'](fd) != before or DISK['hashed'](fd) != original['sha256']:
                raise ValueError('mcopy failed or BODYDATA source changed; rc=' + str(rc))
        finally:
            os.close(fd)
        source = dict(bodydata=original, source_opened_writable=False)
    with FAT['FatImage'](card, output, mtools_dir='/usr/bin', fmask=0, dmask=0,
                         max_file_bytes=2 * 1024**3, max_total_bytes=3 * 1024**3) as fat:
        inv = fat.inventory()
        matches = [name for name in inv['entries'] if name.casefold() == '/bodydata.dat']
        if len(matches) != 1 or inv['entries'][matches[0]]['kind'] != 'file':
            raise ValueError('SD must contain one ordinary root BODYDATA.DAT')
        node = inv['entries'][matches[0]]
        if node['size'] < 8:
            raise ValueError('Truncated BODYDATA input')
        raw = fat.locations[matches[0]][1]
        cluster = int.from_bytes(raw[26:28], 'little')
        if fat.bits == 32:
            cluster |= int.from_bytes(raw[20:22], 'little') << 16
        if fat.read(fat.cluster_offset(cluster), 8) != b'\x89UFU\r\n\x1a\n':
            raise ValueError('SD input is not a Sony UFU BODYDATA')
        if bodydata is not None and record(absolute(bodydata))['sha256'] != node['sha256']:
            raise ValueError('SD BODYDATA differs from the selected input sample')
        result = dict(image=record(card), source=source, bodydata=node, fat_bits=fat.bits,
                      sector_bytes=fat.sector, ordinary_fat=True, guest_path='/image_mmca',
                      receiver_api='FsysFileHandler / Fsys_Open / Fsys_Read', guest_consumed=False,
                      transport='regular RAM file in separate CPIO member; no 9p/virtio in original kernel',
                      persistence='RAM SD input snapshot; updater target writes use persistent instance',
                      host_install_performed=False)
    return result


def cpio_entry(stream, name, mode, size=0, source=None, data=b'', *, ino=1, rdev=(0, 0)):
    encoded = name.encode('utf-8') + b'\0'
    if len(encoded) > 4096 or size > 0xffffffff:
        raise ValueError('CPIO name/size out of bounds')
    fields = (ino, mode, 0, 0, 1, 0, size, 0, 0, *rdev, len(encoded), 0)
    stream.write(b'070701' + b''.join(('%08x' % v).encode() for v in fields))
    stream.write(encoded)
    stream.write(b'\0' * ((-110 - len(encoded)) % 4))
    if source is None:
        if len(data) != size:
            raise ValueError('CPIO literal size differs')
        stream.write(data)
    else:
        fd = FAT['secure_open'](source)
        try:
            remaining = size
            while remaining:
                block = os.read(fd, min(CHUNK, remaining))
                if not block:
                    raise ValueError('Short CPIO source')
                stream.write(block)
                remaining -= len(block)
            if os.read(fd, 1):
                raise ValueError('CPIO source grew')
        finally:
            os.close(fd)
    stream.write(b'\0' * ((-size) % 4))


def archive(root, destination):
    with destination.open('xb') as out, gzip.GzipFile(fileobj=out, mode='wb', mtime=0, compresslevel=1) as stream:
        paths = sorted(root.rglob('*'))
        for index, path in enumerate(paths, 1):
            node = path.lstat()
            name = str(path.relative_to(root))
            if stat.S_ISREG(node.st_mode):
                cpio_entry(stream, name, node.st_mode, node.st_size, path, ino=index)
            elif stat.S_ISLNK(node.st_mode):
                target = os.readlink(path).encode()
                cpio_entry(stream, name, node.st_mode, len(target), data=target, ino=index)
            elif stat.S_ISDIR(node.st_mode):
                cpio_entry(stream, name, node.st_mode, ino=index)
            else:
                raise ValueError('Unexpected host special node in extracted root: ' + name)
        cpio_entry(stream, 'dev/console', stat.S_IFCHR | 0o600, rdev=(5, 1), ino=len(paths) + 1)
        cpio_entry(stream, 'TRAILER!!!', 0)
    return record(destination)


def newdecrypt_selection(profile, *, mode, original_resources, install_profile, read_only,
                         trust_profile, pinned_key, trusted_key_model):
    if profile is not None and (profile != NEWDECRYPT_PROFILE or mode != 'official'
            or original_resources is not True or install_profile != 'original-p1-virtual-install-v1'
            or read_only is not False or trust_profile != 'virtual-p1-pinned-key-v1'
            or pinned_key is None or trusted_key_model is not None):
        raise ValueError('CBC requires exact explicit official stock install/resources/write and pinned-key trust selection')


def tail_selection(profile=None, *, mode, install_profile, signature_schema):
    if profile is None:return None
    return runpy.run_path(str(HERE / 'p1-tail-source.py'))['selection'](profile, mode=mode,
        install_profile=install_profile, signature_schema=signature_schema)


def stock_trust_preflight(update, root):
    """The selected SDK observer already contains the stock trust activation."""
    sd = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
    observation = update['sd_read_observation']
    decrypt = observation['trust_key'].get('newdecrypt')
    profile = update.get('newdecrypt_profile')
    tail = observation['trust_key'].get('tail')
    tail_profile = tail['profile'] if tail else None
    if update.get('tail_profile') != tail_profile:
        raise ValueError('Declared tail selection differs from stock observer')
    if tail is not None:sd['tail_api']()['recheck'](root, tail)
    if decrypt is None and tail is None:
        if profile is not None:
            raise ValueError('Declared CBC selection lacks its built observer contract')
        return runpy.run_path(str(HERE / 'p1-trusted-key-model.py'))['preflight_stock'](update, root)
    selected = update.get('trust_selection') or {}
    newdecrypt_selection(profile, mode=update['mode'], original_resources=bool(update.get('original_resources')),
        install_profile=update.get('install_profile'), read_only=update.get('read_only'),
        trust_profile=selected.get('profile'), pinned_key=selected.get('pinned_key'),
        trusted_key_model=update.get('trusted_key_model_selection'))
    if decrypt is not None and (profile != NEWDECRYPT_PROFILE or decrypt['selection'] != dict(profile=profile)):
        raise ValueError('Declared CBC selection differs from its built observer contract')
    if decrypt is None and profile is not None:raise ValueError('Declared CBC selection lacks its built observer contract')
    tail_selection(tail_profile, mode=update['mode'], install_profile=update.get('install_profile'),
                   signature_schema=observation['trust_key']['contract']['schema'])
    trust = sd['trust_preflight'](root, observation['trust_key'])
    pinned = selected['pinned_key']
    if record(pinned['path']) != pinned or pinned not in trust['sources']:
        raise ValueError('Stock independent pinned PEM identity differs')
    if sd['_pinned_snapshot'](pinned['path']) != sd['_pinned_snapshot'](
            Path(root) / 'simulation/p1-trust-key/sony-original.pem'):
        raise ValueError('Stock pinned runtime asset differs')
    emitted = sd['observer_source'](sd['initialize_contract'](root), sd['trust_contract'](root),
                                   trust_profile=selected['profile'], newdecrypt=decrypt, **(dict(tail=tail) if tail is not None else {}))
    value = update.get('trust_execution') or {}
    if (value.get('profile') != selected['profile'] or value.get('signature_verified') is not False
            or value.get('environment') != trust['environment']
            or value.get('environment_activation') != 'selected-observer-constructor-after-native-pins'
            or Path(value['source']['path']).read_text(encoding='ascii') != emitted
            or (Path(root) / 'etc/ld.so.preload').read_text(encoding='ascii') != sd['PRELOAD']):
        raise ValueError('Stock CBC trust activation source/environment differs')
    for path, expected in ((Path(value['source']['path']), value['source']),
                           (Path(root) / 'simulation/p1-sd-observer.so', value['observer'])):
        actual = record(path)
        if any(actual[k] != expected[k] for k in ('bytes', 'sha256')):
            raise ValueError('Stock CBC trust activation bytes differ')
    return value


def build(instance, runtime_analysis, output, *, bodydata=None, sd_image=None, mode,
          persistent_module=None, module_receipt=None, probe_receipt=None, original_resources=False,
          media_resources=None, sd_read_profile=None, install_profile=None, install_receipt=None,
          install_receipt_sha256=None, read_only=True, allow_updater_writes=False,
          allow_dev_signature_bypass=False, trusted_key_model=None, trust_profile=None, pinned_key=None,
          storage_profile=None, newdecrypt_profile=None, tail_profile=None, tail_body_root=None):
    tail_selection(tail_profile, mode=mode, install_profile=install_profile,
                   signature_schema='p1-trust-key-abi-v1' if trust_profile=='virtual-p1-pinned-key-v1' else None)
    if tail_body_root is not None and tail_profile is None:
        raise ValueError('tail_body_root requires an explicit tail profile')
    newdecrypt_selection(newdecrypt_profile, mode=mode, original_resources=original_resources,
        install_profile=install_profile, read_only=read_only, trust_profile=trust_profile,
        pinned_key=pinned_key, trusted_key_model=trusted_key_model)
    storage_selection(storage_profile, install_profile=install_profile, read_only=read_only,
                      allow_updater_writes=allow_updater_writes)
    if not isinstance(original_resources, bool):
        raise ValueError('Explicit bool required for original_resources')
    if media_resources is not None and not original_resources:
        raise ValueError('Media receipt requires explicit original_resources')
    if trust_profile is not None or pinned_key is not None:
        if (install_profile != 'original-p1-virtual-install-v1' or mode != 'official'
                or trust_profile != 'virtual-p1-pinned-key-v1' or pinned_key is None
                or trusted_key_model is not None):
            raise ValueError('Stock trust requires exact official install profile and explicit pinned PEM')
        trust_api = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
        try:
            trust_api['_pinned_snapshot'](pinned_key)
        except OSError as error:
            if newdecrypt_profile is None:
                raise
            raise ValueError('CBC requires a readable independent fixed pinned PEM') from error
    if trusted_key_model is not None and install_profile != 'original-p1-virtual-dev-install-v1':
        raise ValueError('Trusted-key composition requires the explicit dev install profile')
    if install_profile is not None:
        dev_install = install_profile == 'original-p1-virtual-dev-install-v1'
        install_api = runpy.run_path(str(HERE / ('p1-dev-install.py' if dev_install else 'newp1-virtual-install.py')))
        if dev_install:
            install_api['selection'](install_profile, mode, allow_dev_signature_bypass)
        if (install_profile != install_api['PROFILE'] or sd_read_profile is not None
                or mode != ('virtual-dev-sd-update-v1' if dev_install else 'official')
                or (not dev_install and allow_dev_signature_bypass is not False)
                or read_only is not False or allow_updater_writes is not True or not original_resources
                or media_resources is None or bodydata is None or install_receipt is None or install_receipt_sha256 is None):
            raise ValueError('Install profile requires its exact mode/package, clone receipt and explicit write flags')
    elif (install_receipt is not None or install_receipt_sha256 is not None or read_only is not True
          or allow_updater_writes is not False or allow_dev_signature_bypass is not False):
        raise ValueError('Write flags/clone receipt require explicit install profile')
    if sd_read_profile is not None:
        sd_api = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
        if (sd_read_profile != sd_api['PROFILE'] or mode != 'official' or not original_resources
                or media_resources is None or (bodydata is None and sd_image is None)):
            raise ValueError('Explicit SD read profile requires official/media/resources/SD input')
    if mode not in MODES:
        raise ValueError('Explicit mode must be official or virtual-dev-sd-update-v1')
    runtime, output = absolute(runtime_analysis), absolute(output)
    path = absolute(instance['path'] if isinstance(instance, dict) else instance)
    protected_dump = HERE.parents[1] / 'analysis/output/system-dump'
    for original in (path, runtime, HERE, protected_dump):
        if output.is_relative_to(original) or original.is_relative_to(output):
            raise ValueError('Output overlaps instance/source/runtime')
    parent = FAT['secure_open'](output.parent, directory=True)
    os.close(parent)
    output.mkdir(mode=0o700)
    report = dict(schema='a7c2-p1-update-boot-v1', status='building', stage='instance', mode=mode,
                  storage_profile=storage_profile,
                  output=str(output), commands=[], blockers=[], source_dump_opened_writable=False,
                  physical_devices_used=False, installation_verified=False, menu_entry_verified=False,
                  normal_ap_frontend='notexecuted', original_init_executed=False,
                  udtrmain_executed=False, sdfileinput_executed=False, bodywriter_executed=False,
                  bypass_configured=False, bypass_executed=False, guest_execution_verified=False)
    if newdecrypt_profile is not None:
        report['newdecrypt_profile'] = newdecrypt_profile
    if tail_profile is not None:report['tail_profile'] = tail_profile
    try:
        context = nullcontext(instance) if isinstance(instance, dict) else DISK['lease'](path)
        with context as leased:
            fd, geometry = leased['fd'], leased['geometry']
            if (geometry.get('user_bytes') != GEOMETRY['CAPACITY'] or
                    geometry.get('backing_bytes') != GEOMETRY['CAPACITY'] + 2 * GEOMETRY['BOOT_BYTES']):
                raise ValueError('Exact 1864 MiB user area plus separate boot areas required')
            before = DISK['stamp'](fd)
            if install_profile is not None:
                report['virtual_install'] = install_api['clone_contract'](leased, install_receipt, install_receipt_sha256,
                                                                          output_root=output / 'dev-preflight')
                report.update(install_profile=install_profile, read_only=False, allow_updater_writes=True,
                              allow_dev_signature_bypass=allow_dev_signature_bypass)
                if trust_profile is not None:
                    report['trust_selection'] = dict(profile=trust_profile, pinned_key=record(absolute(pinned_key)))
                if dev_install:
                    install_api['trusted_key_api'](trusted_key_model)
                    report['trusted_key_model_selection'] = trusted_key_model
            disk_path = record(path / 'camera.emmc')
            if (disk_path['device'], disk_path['inode'], disk_path['bytes']) != before[:3]:
                raise ValueError('Caller lease does not refer to this instance file')
            g = record(path / 'geometry.json')
            if g['sha256'] != leased['state']['geometry_sha256']:
                raise ValueError('Leased geometry metadata changed')
            if json.loads((path / 'geometry.json').read_text()) != geometry:
                raise ValueError('Caller geometry differs from instance geometry')
            if os.pread(fd, 8, 0) != b'82462.00':
                raise ValueError('Invalid SDM2 label on leased instance')
            wire = output / 'persistent-geometry.bin'
            GEOMETRY['write_camera_wire'](geometry, wire)
            report['instance'] = dict(path=str(path), disk=disk_path, geometry=g,
                wire=record(wire), same_fd_for_all_flash_slices=True, boot_areas_separate=True,
                leased_fd=fd, lease_owned_by_caller=isinstance(instance, dict),
                fd_number_is_build_observation_only=True, runtime_fd_binding_verified=False,
                launch_requires_lease=True, expected_dev=before[0], expected_ino=before[1],
                container_bytes=before[2], user_bytes=geometry['user_bytes'])
            report['sources'] = {}
            for number in (1, 2):
                sl = next(s for s in geometry['slices'] if s['id'] == 'nflasha' + str(number))
                target = output / ('p' + str(number) + '.img')
                report['sources']['p' + str(number)] = copy_range(fd, sl['offset'], sl['bytes'], target)
            if DISK['stamp'](fd) != before or DISK['hashed'](fd) != disk_path['sha256']:
                raise ValueError('Instance changed while extracting p1/p2')
        report['stage'] = 'p1-extract'
        fat, inv, tail = fat_view(output / 'p1.img', output, 'p1')
        report['p1'] = dict(tail=tail, inventory=inv)
        try:
            for guest, name, expected in (('/boot/vmlinux.bin', 'kernel.img', KERNEL_SHA),
                                          ('/boot/initrd.img', 'p1-root.squashfs', ROOT_SHA)):
                row = fat_extract(fat, inv, guest, output / name)
                if row['sha256'] != expected:
                    raise ValueError('Unknown original p1 asset identity: ' + guest)
                report['p1'][name] = row
            for name in ('kemco.txt', 'loadaddr.txt', 'cxd90057.dtb'):
                report['p1'][name] = fat_extract(fat, inv, '/boot/' + name, output / name)
        finally:
            fat.close()
        report['stage'] = 'root-extract'
        root = output / 'root'
        report['commands'].append(command(['unsquashfs', '-no-progress', '-no-xattrs', '-processors', '2',
                                           '-d', root, output / 'p1-root.squashfs'], output, 'unsquashfs'))
        evidence = json.loads((HERE.parent / '2026-11-03-p1-update-flow/source-identities.json').read_text())
        report['original_files'] = {}
        for key, original in evidence.items():
            if not key.startswith('p1_'):
                continue
            relative = original['path'].split('/updater-root/', 1)[1]
            actual = record(root / relative)
            if actual['sha256'] != original['sha256'] or actual['bytes'] != original['bytes']:
                raise ValueError('Original business identity differs: ' + relative)
            report['original_files'][relative] = actual
        fat, inv, tail = fat_view(output / 'p2.img', output, 'p2')
        try:
            report['p2'] = setting_state(inv, serial=(root / 'root/IAMLDUDWRT').exists())
            report['p2']['backup'] = inv['entries'].get('/Backup.bin')
            report['p2']['tail'] = tail
            if install_profile == 'original-p1-virtual-dev-install-v1':
                row = fat_extract(fat, inv, '/updater/dat4', output / 'p2-current-version.bin')
                raw = Path(row['path']).read_bytes()
                if len(raw) != 2:
                    raise ValueError('Current p2 version must be the actual two-byte dat4 file')
                report['p2']['firmware_version'] = dict(version=f'{raw[1]:x}.{raw[0]:02x}', file=row)
        finally:
            fat.close()
        report['stage'] = 'storage-adapter'
        simulation = root / 'simulation'
        simulation.mkdir()
        module = (absolute(persistent_module) if persistent_module is not None else
                  runtime / 'persistent-flash/sony_persistent_flash.ko')
        report['persistent_module'] = copy_input(module, simulation / 'sony_persistent_flash.ko')
        report['module_contract'] = module_contract(report['persistent_module'], report['p1']['kernel.img'],
                                                    module_receipt, probe_receipt)
        storage_selection(storage_profile, install_profile=install_profile, read_only=read_only,
                          allow_updater_writes=allow_updater_writes, module=report['module_contract'])
        if storage_profile is not None:
            parameter = simulation / 'storage-profile'
            with parameter.open('x', encoding='ascii') as stream:
                stream.write(storage_parameter_text())
            parameter.chmod(0o600)
        kernel_release = re.search(rb'Linux version ([^ ]+)', (output / 'kernel.img').read_bytes())
        module_release = re.search(rb'\x00vermagic=([^ \x00]+)', (simulation / 'sony_persistent_flash.ko').read_bytes())
        if kernel_release is None or module_release is None:
            raise ValueError('Missing original kernel release or module vermagic')
        report['module_abi'] = dict(kernel_release=kernel_release[1].decode('ascii'),
            module_release=module_release[1].decode('ascii'),
            release_matches=kernel_release[1] == module_release[1], force_load_allowed=False,
            guest_verified=False)
        if not report['module_abi']['release_matches']:
            report['blockers'].append(dict(stage='persistent-module-abi',
                reason='Original p1 kernel and supplied module releases differ; rebuild against p1 sources/config, never force load',
                **report['module_abi']))
        report['aliases'] = copy_input(HERE / 'persistent-flash/create-aliases.sh', simulation / 'create-aliases')
        report['bootstrap'] = copy_input(HERE / 'guest/update-storage-bootstrap', root / 'init')
        for target in (root / 'init', simulation / 'create-aliases'):
            target.chmod(0o755)
        (simulation / 'update-profile').write_text(mode + '\n')
        (simulation / 'module-policy').write_text('project-storage-only-v1\n')
        report['original_module_allowlist'] = []
        if original_resources:
            contract = original_resource_contract(root, report['p1']['kernel.img'], media_resources)
            if media_resources is not None:
                media_api = runpy.run_path(str(HERE / 'p1-media-init-probe.py'))
                backup = report['p2'].get('backup') or {}
                if (report['p2']['predicted_outer_mode'] != 5 or report['p2']['flags']['uincomp']
                        or backup.get('sha256') != media_api['BACKUP_SHA'] or backup.get('size') != media_api['BACKUP_BYTES']):
                    raise ValueError('Media profile requires actual mode5 and reviewed original Backup.bin')
                (simulation / 'media-profile').write_text(media_api['PROFILE'] + '\n', encoding='ascii')
            report['original_resources'] = contract
            report['original_module_allowlist'] = [r['path'] for r in contract['modules']]
            (simulation / 'original-modules').write_text(''.join(
                f'{r["path"]} {r["file"]["bytes"]} {r["file"]["sha256"]}\n' for r in contract['modules']), encoding='ascii')
            cold = runpy.run_path(str(HERE / 'cold-init-chain.py'))
            cold['_compile_audit'](HERE / 'guest/cold-start-audit.c', root / 'lib/libc-2.25.so', simulation / 'audit')
        report['storage_replacements'] = []
        report['trace_adapters'] = []
        for name in ('mkramdsk.sh', 'insmod.sh', 'UdtrMain.sh', 'execute_prod.sh', 'execute_ufp.sh'):
            target = root / 'sbin' / name
            if os.path.lexists(target):
                raise ValueError('Trace adapter collides with original path: ' + name)
            target.symlink_to('/init')
            report['trace_adapters'].append(dict(path='/sbin/' + name, original='/usr/bin/' + name,
                                                action='external /bin/sh -x; original bytes retained'))
        report['loader_modes'] = []
        for target in sorted((root / 'lib').glob('*.so*')):
            if target.is_file() and not target.is_symlink():
                before_mode = stat.S_IMODE(target.stat().st_mode)
                target.chmod(0o755)
                report['loader_modes'].append(dict(file=record(target), original_mode=oct(before_mode), mode='0755'))
        report['module_adapters'] = []
        for name in ('insmod', 'rmmod'):
            target = root / 'sbin' / name
            if not target.is_symlink():
                raise ValueError('Expected original busybox module applet symlink: ' + str(target))
            old = os.readlink(target)
            target.unlink()
            target.symlink_to('/init')
            report['module_adapters'].append(dict(path='/sbin/' + name, original_target=old,
                                                 project_target='/init', unverified_requests_rc=125))
        report['blockers'].append(dict(stage='original-module-integration',
            reason='Modules outside the explicit source/ABI/export-bound allowlist return 125; no fabricated original module success'))
        report['stage'] = 'sd-input'
        if sd_read_profile is not None or install_profile is not None:
            sd_api = (install_api if install_profile == 'original-p1-virtual-dev-install-v1' else
                      runpy.run_path(str(HERE / 'p1-sd-read-probe.py')))
            if bodydata is None:
                raise ValueError('SD read profile requires explicit BODYDATA source')
            report['sd_read_package_source'] = record(absolute(bodydata))
            if install_profile == 'original-p1-virtual-dev-install-v1':
                report['sd_read_package'] = sd_api['package'](absolute(bodydata), output, binding=report['virtual_install'],
                                                             output_root=output / 'dev-preflight')
                sd_api['admit'](install_profile, mode=mode, read_only=read_only, allow_updater_writes=allow_updater_writes,
                    allow_dev_signature_bypass=allow_dev_signature_bypass, media=media_resources, sd=bodydata,
                    module=report['module_contract'])
            else:
                report['sd_read_package'] = sd_api['package'](absolute(bodydata), output)
                sd_api['admit'](sd_read_profile or install_profile, mode=mode, read_only=read_only, media=media_resources,
                                sd=bodydata, module=report['module_contract'])
        report['sd'] = prepare_sd(bodydata, sd_image, runtime, output)
        if mode == MODES[1]:
            if report['sd'] is None:
                raise ValueError('Explicit development SD update requires BODYDATA or a FAT SD image')
            receiver = root / 'usr/lib/libsdfileinputupdaterapi.so'
            dev = runpy.run_path(str(HERE / 'dev-update-profile.py'))
            original_receiver = output / 'original-libsdfileinputupdaterapi.so'
            copied = copy_input(receiver, original_receiver)
            if any(copied[k] != report['original_files']['usr/lib/libsdfileinputupdaterapi.so'][k]
                   for k in ('bytes', 'sha256')):
                raise ValueError('Original receiver snapshot differs')
            original_receiver.chmod(0o444)
            report['original_files']['usr/lib/libsdfileinputupdaterapi.so'] = record(original_receiver)
            receipt = dev['derive_receiver'](original_receiver, simulation / 'dev-receiver.so', mode=mode)
            replacement = simulation / 'dev-receiver.so'
            receiver.write_bytes(replacement.read_bytes())
            if record(receiver)['sha256'] != receipt['output']['sha256']:
                raise ValueError('Derived receiver integration readback failed')
            replacement.unlink()
            report['receiver'] = receipt
            report['receiver']['installed_guest_path'] = '/usr/lib/libsdfileinputupdaterapi.so'
            report['bypass_configured'] = True
        if report['sd'] is not None:
            report['stage'] = 'file-media-build'
            lib = root / 'lib'
            file_media_source = HERE / 'file-media-config.c'
            file_media_prepared = None
            if install_profile == 'original-p1-virtual-dev-install-v1':
                file_media_prepared = install_api['file_media_source'](root, report, output)
                file_media_source = Path(file_media_prepared['source']['path'])
            file_media_argv = ['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld',
                '-nostdlib', '-O2', '-mno-outline-atomics', '-Wl,--no-undefined', '-shared', '-fPIC',
                file_media_source, lib / 'libc-2.25.so', lib / 'libdl-2.25.so',
                lib / 'libpthread-2.25.so', lib / 'ld-2.25.so',
                '-o', simulation / 'file-media-config.so']
            if file_media_prepared is not None:
                file_media_argv = install_api['file_media_command'](root, file_media_prepared)
            report['commands'].append(command(file_media_argv, output, 'file-media-build'))
            report['file_media'] = dict(source=record(file_media_source),
                                       output=record(simulation / 'file-media-config.so'),
                                       enabled=True, executed=False)
            if file_media_prepared is not None:
                install_api['file_media_seal'](root, report, file_media_prepared, report['commands'][-1])
            preload = root / 'etc/ld.so.preload'
            if os.path.lexists(preload):
                raise ValueError('Unexpected original ld.so.preload; refuse overwriting')
            preload.write_text('/simulation/file-media-config.so\n')
            (simulation / 'sd-input-configured').write_text('Fsys /image_mmca\n')
            if not report['p2']['sd_dispatch_eligible']:
                report['blockers'].append(dict(stage='p2-mode', reason='Actual FAT mode selection does not admit SD receiver',
                                                state=report['p2']['flags']))
        if sd_read_profile is not None or install_profile is not None:
            report['sd_read_observation'] = sd_api['configure'](root, report, output, profile=sd_read_profile or install_profile,
                **(dict(trust_profile=trust_profile, pinned_key=pinned_key, newdecrypt_profile=newdecrypt_profile)
                   if install_profile == 'original-p1-virtual-install-v1' else {}),
                **(dict(tail_profile=tail_profile, tail_body_root=tail_body_root) if tail_profile is not None else {}))
            if newdecrypt_profile is not None or tail_profile is not None:
                report['bootstrap'] = record(root / 'init')
                # CBC audit rows describe content; host inode/device cannot survive the execution-root copy.
                report['sd_read_observation']['bindings'] = [
                    {key: row[key] for key in ('path', 'bytes', 'sha256')}
                    for row in report['sd_read_observation']['bindings']]
            if trust_profile is not None:
                trust_key = report['sd_read_observation'].get('trust_key')
                if not trust_key or trust_key.get('profile') != trust_profile:
                    raise ValueError('Stock trust service contract missing')
                sd_api['trust_preflight'](root, trust_key)
                if newdecrypt_profile is None and tail_profile is None:
                    report['trust_execution'] = runpy.run_path(str(HERE / 'p1-trusted-key-model.py'))['configure_stock'](
                        root, report, output)
                else:
                    observation = report['sd_read_observation']
                    report['trust_execution'] = dict(profile=trust_profile, environment=trust_key['environment'],
                        environment_activation='selected-observer-constructor-after-native-pins',
                        source=observation['observer_source'], observer=observation['observer'], signature_verified=False)
                    stock_trust_preflight(report, root)
            report['sd_read_observation']['cpio_bindings'] = (
                sd_api['bindings'](root, report['sd']['image'], trusted_key_model=report.get('trusted_key_model'))
                if install_profile == 'original-p1-virtual-dev-install-v1' else
                sd_api['bindings'](root, report['sd']['image']))
        report['storage_cpio_bindings'] = storage_preflight(report, root, storage_profile,
            read_only=read_only, allow_updater_writes=allow_updater_writes)
        for name, original in report['original_files'].items():
            if name == 'usr/lib/libsdfileinputupdaterapi.so' and mode == MODES[1]:
                dev['verify_derived_receiver'](root / name, report['receiver'])
                continue
            if record(root / name)['sha256'] != original['sha256']:
                raise ValueError('Business script/program changed: ' + name)
        for name in ('proc', 'sys', 'dev'):
            (root / name).mkdir(exist_ok=True)
        report['stage'] = 'cpio'
        report['bootstrap_cpio'] = archive(root, output / 'bootstrap.cpio.gz')
        initrd = output / 'update-initrd.cpio.gz'
        copy_input(output / 'bootstrap.cpio.gz', initrd)
        if report['sd'] is not None:
            card = output / 'card.fat'
            with initrd.open('ab') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=1) as stream:
                cpio_entry(stream, 'image_mmca', stat.S_IFREG | 0o600, card.stat().st_size, card)
                cpio_entry(stream, 'TRAILER!!!', 0)
            if record(card)['sha256'] != report['sd']['image']['sha256']:
                raise ValueError('SD input changed during CPIO assembly')
        report['initrd'] = record(initrd)
        if storage_profile is not None:
            report['storage_cpio_readback'] = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))['cpio_readback'](
                initrd, report['storage_cpio_bindings'])
            for row in report['module_contract']['storage_inputs']:
                if any(record(row['path'])[k] != row[k] for k in ('bytes', 'sha256')):
                    raise ValueError('Trim source/input changed after CPIO assembly')
        if sd_read_profile is not None or install_profile is not None:
            report['sd_read_observation']['cpio_readback'] = sd_api['cpio_readback'](
                initrd, report['sd_read_observation']['cpio_bindings'])
            report['sd_read_observation']['sources'] = [record(HERE / name) for name in (
                'update-boot.py', 'p1-sd-read-probe.py', 'p1-file-media-contract.py', 'file-media-config.c',
                'guest/update-storage-bootstrap', 'newp1-virtual-install.py')]
            trust_key = report['sd_read_observation'].get('trust_key')
            if trust_key:
                report['sd_read_observation']['sources'] += trust_key['sources']
                report['sd_read_observation']['sources'].append(record(output / 'p1-sd-observer.c'))
            if newdecrypt_profile is not None:
                decrypt = trust_key['newdecrypt']
                model = sd_api['newdecrypt_api']()
                model['validate'](decrypt)
                # Use the SDK's actual source receipt and the remaining compiled pin/library inputs.
                report['sd_read_observation']['sources'] += [record(HERE / name)
                    for name in decrypt['source_receipt']['sources']]
                report['sd_read_observation']['sources'] += [record(path) for path in (
                    Path(decrypt['build_directory']) / 'p1_cbc_runtime_binding.h',
                    root / 'usr/lib/libcrypto.so.1.1', root / 'lib/libpthread-2.25.so')]
                report['sd_read_observation']['sources'] = list({row['path']: row
                    for row in report['sd_read_observation']['sources']}.values())
            if report.get('trust_execution'):
                if newdecrypt_profile is None and tail_profile is None:
                    report['sd_read_observation']['sources'].append(record(HERE / 'p1-trusted-key-model.py'))
                stock_trust_preflight(report, root)
            if install_profile == 'original-p1-virtual-dev-install-v1':
                report['sd_read_observation']['sources'] += [record(HERE / name) for name in (
                    'p1-dev-install.py', 'dev-update-profile.py', 'p1-dev-file-package.py',
                    'p1-dev-receiver-identity.py')]
                report['sd_read_observation']['sources'].append(record(file_media_source))
                report['sd_read_observation']['sources'].append(record(HERE.parents[1] / 'analysis/build_sony_info.py'))
                report['bootstrap'] = record(root / 'init')
                if report.get('trusted_key_model'):
                    report['sd_read_observation']['sources'] += report['trusted_key_model']['sources']
            for row in report['sd_read_observation']['sources'] + [report['sd_read_package_source']]:
                if record(row['path'])['sha256'] != row['sha256']:
                    raise ValueError('SD read source changed after CPIO assembly')
        report['boot'] = dict(kernel=str(output / 'kernel.img'), initrd=str(initrd), entry='/init -> original /sbin/init',
            root_transport='CPIO RAM root unpacked from exact original p1 squashfs; original business files retained',
            root_mount_semantics_changed=True, kernel_unmodified=True, original_squashfs_retained=True,
            append='rdinit=/init console=ttyAMA0',
            required_device='sony-persistent-flash @ 0x0b000000, leased instance FD and generated geometry wire',
            launch_preflight_passed=(report['module_abi']['release_matches'] and
                                     report['module_contract']['build_bound'] and
                                     (report['sd'] is None or report['p2']['sd_dispatch_eligible'])),
            qemu_command=None, qemu_runner='p1-update-execution.py explicit original-p1 board/lease runner',
            minimum_ram_mib=8192 if report['sd'] else 4096)
        report['blockers'].append(dict(stage='production-qemu-runner',
            reason='No launch performed here; parent must bind the same leased instance FD to its production board'))
        report.update(status='built', stage='complete', original_business_scripts_unchanged=True,
                      original_receiver_unchanged=mode == 'official')
    except Exception as error:
        report.update(status='failed', error=type(error).__name__ + ': ' + str(error))
    finally:
        (output / 'update-boot.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('instance', 'runtime-analysis', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--bodydata', type=Path)
    parser.add_argument('--sd-image', type=Path)
    for name in ('persistent-module', 'module-receipt', 'probe-receipt'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--original-resources', action='store_true')
    parser.add_argument('--media-resources', type=Path)
    parser.add_argument('--sd-read-profile', choices=('original-p1-sd-readonly-v1',))
    parser.add_argument('--install-profile', choices=('original-p1-virtual-install-v1', 'original-p1-virtual-dev-install-v1'))
    parser.add_argument('--storage-profile', choices=(TRIM_STORAGE_PROFILE,))
    parser.add_argument('--newdecrypt-profile', choices=(NEWDECRYPT_PROFILE,))
    parser.add_argument('--install-receipt', type=Path)
    parser.add_argument('--install-receipt-sha256')
    parser.add_argument('--allow-updater-writes', action='store_true')
    parser.add_argument('--allow-dev-signature-bypass', action='store_true')
    parser.add_argument('--trust-profile', choices=('virtual-p1-pinned-key-v1',))
    parser.add_argument('--pinned-key', type=Path)
    parser.add_argument('--trusted-key-model', type=Path, help='JSON selection with profile/receipt/receipt_sha256')
    parser.add_argument('--mode', choices=MODES, required=True)
    args = parser.parse_args()
    result = build(args.instance, args.runtime_analysis, args.output,
                   bodydata=args.bodydata, sd_image=args.sd_image, mode=args.mode,
                   persistent_module=args.persistent_module, module_receipt=args.module_receipt,
                   probe_receipt=args.probe_receipt, original_resources=args.original_resources,
                   media_resources=args.media_resources, sd_read_profile=args.sd_read_profile,
                   install_profile=args.install_profile, install_receipt=args.install_receipt,
                   install_receipt_sha256=args.install_receipt_sha256, read_only=not args.allow_updater_writes,
                   allow_updater_writes=args.allow_updater_writes,
                   allow_dev_signature_bypass=args.allow_dev_signature_bypass,
                   trust_profile=args.trust_profile, pinned_key=args.pinned_key, storage_profile=args.storage_profile,
                   newdecrypt_profile=args.newdecrypt_profile,
                   trusted_key_model=checked_json(args.trusted_key_model)[0] if args.trusted_key_model else None)
    print(json.dumps(dict(status=result['status'], output=result['output'], error=result.get('error'),
                          blockers=result['blockers']), indent=2))
    return 0 if result['status'] == 'built' else 1


if __name__ == '__main__':
    raise SystemExit(main())
