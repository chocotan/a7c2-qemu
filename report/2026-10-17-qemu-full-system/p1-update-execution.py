#!/usr/bin/env python3
"""Own the original p1 init/updater on an isolated virtual camera disk.

build(update_manifest, output, *, read_only=True, qemu_build=..., board_runtime=...)
actual(manifest, output, *, seconds=60)
collect(serial_bytes, manifest)

The default is an original-init-only, block-readonly experiment. Enabling writes
requires the large-BIO-fixed original-p1 module receipt. This is execution
infrastructure, never hostvirtualinstall or proof of BODYDATA installation.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import runpy
import secrets
import subprocess
import time

HERE = Path(__file__).resolve().parent
PROBE = runpy.run_path(str(HERE / 'p1-module-probe.py'))
UPDATE, DISK, COLD, PERSIST, OWNER = (PROBE[k] for k in ('UPDATE', 'DISK', 'COLD', 'PERSIST', 'OWNER'))
PMBP = runpy.run_path(str(HERE / 'pmbp-integration.py'))
PROFILE = 'original-p1-update-execution-v1'
DEFAULT_QEMU = PROBE['DEFAULT_QEMU']
# BLKROSET/BLKROGET are Linux's public block ioctl ABI; all 20 disks must confirm.
READONLY_SOURCE = r'''
extern int open(const char *, int, ...), close(int), ioctl(int, unsigned long, ...);
extern int printf(const char *, ...);
static int run(int argc, char **argv) {
    if (argc != 21) return 2;
    int failed=0;
    for (int i=1;i<argc;i++) {
        int fd=open(argv[i],0), one=1, actual=0;
        int set=fd<0 ? -1 : ioctl(fd,0x125dUL,&one);
        int get=fd<0 ? -1 : ioctl(fd,0x125eUL,&actual);
        printf("UPDATE_READONLY node=%s set_rc=%d get_rc=%d readonly=%d\n",argv[i],set,get,actual);
        if (fd>=0) close(fd);
        if (set || get || actual!=1) failed=1;
    }
    return failed;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
'''


UIPC_STATUS_SOURCE = r'''
extern int printf(const char *, ...), *__errno_location(void);
extern void *dlopen(const char *, int), *dlsym(void *, const char *);
static int run(int argc, char **argv) {
    (void)argv;
    if (argc != 1) return 2;
    void *lib=dlopen("/usr/lib/libosal_uipc.so",2);
    int (*init)(void)=lib ? (int (*)(void))dlsym(lib,"u_uipc_init") : 0;
    void (*stat)(unsigned *)=lib ? (void (*)(unsigned *))dlsym(lib,"osal_get_uipc_stat") : 0;
    if (!init || !stat) { printf("UPDATE_UIPC_NATIVE_GETSTATUS resolver_rc=1\n");return 1; }
    int rc=init(), error=*__errno_location();
    printf("UPDATE_UIPC_NATIVE_GETSTATUS function=u_uipc_init original_rc=%d errno=%d\n",rc,error);
    if (!rc) {
        unsigned words[5]={0};stat(words);
        printf("UPDATE_UIPC_NATIVE_STAT words=%u,%u,%u,%u,%u\n",words[0],words[1],words[2],words[3],words[4]);
    }
    return rc ? 1 : 0;
}
'''


def save(path, value):
    DISK['save'](Path(path), value)


def checked(row):
    actual = UPDATE['record'](row['path'])
    if any(actual[k] != row[k] for k in ('bytes', 'sha256')):
        raise ValueError('Input bytes differ: ' + row['path'])
    return actual


def clone_instance(source, output):
    """Clone only while exclusively leased; bind all bytes before/after reflink."""
    source = UPDATE['absolute'](source)
    output = PERSIST['fresh_output'](output, source)
    with DISK['lease'](source) as leased:
        before = DISK['stamp'](leased['fd'])
        digest = DISK['hashed'](leased['fd'])
        if leased['state'].get('state') != 'stopped':
            raise ValueError('Source instance is not stopped')
        # Copy from the leased FD, not a re-opened instance pathname.
        subprocess.run(['cp', '--reflink=auto', '--sparse=always', '/proc/self/fd/' + str(leased['fd']),
                        str(output / 'camera.emmc')], pass_fds=(leased['fd'],), check=True,
                       capture_output=True, timeout=60)
        (output / 'camera.emmc').chmod(0o600)
        for name in ('geometry.json', 'instance.json'):
            UPDATE['copy_input'](source / name, output / name)
        (output / '.disk.lock').touch(mode=0o600)
        if (UPDATE['record'](output / 'camera.emmc')['sha256'] != digest
                or DISK['stamp'](leased['fd']) != before or DISK['hashed'](leased['fd']) != digest):
            raise ValueError('Source changed during instance clone')
        save(output / 'update-clone.json', dict(source=str(source), source_sha256=digest,
             source_lease_held=True, readback_verified=True, physical_devices_used=False))
    return output


def resource_binding(root, update):
    contract = update.get('original_resources')
    if contract is None:
        if update.get('original_module_allowlist'):
            raise ValueError('Original module allowlist lacks a resource contract')
        if (root / 'simulation/original-modules').exists():
            raise ValueError('Unexpected original module policy file')
        return None
    media_receipt = contract.get('media_receipt')
    if media_receipt is None:
        actual = UPDATE['original_resource_contract'](root, update['p1']['kernel.img'])
    else:
        checked(media_receipt)
        actual = UPDATE['original_resource_contract'](root, update['p1']['kernel.img'], media_receipt['path'])
        for key in ('media_profile', 'media_receipt'):
            if actual.get(key) != contract.get(key):
                raise ValueError('Original media binding differs: ' + key)
    # Copied paths/inodes change; original bytes, exact module paths and ABI do not.
    for key in ('policy', 'inventory_sha256', 'inventory_count', 'kernel_sha256', 'force_load_allowed',
                'original_arguments_preserved', 'guest_load_verified', 'physical_compatibility_verified'):
        if actual[key] != contract[key]:
            raise ValueError('Original resource contract differs: ' + key)
    if update['original_module_allowlist'] != [r['path'] for r in actual['modules']]:
        raise ValueError('Original resource allowlist differs')
    if len(actual['modules']) != len(contract['modules']):
        raise ValueError('Original resource module count differs')
    for now, old in zip(actual['modules'], contract['modules']):
        if ({k:v for k,v in now.items() if k != 'file'} != {k:v for k,v in old.items() if k != 'file'}
                or any(now['file'][k] != old['file'][k] for k in ('bytes', 'sha256'))):
            raise ValueError('Original resource module identity differs')
    if set(actual['assets']) != set(contract['assets']) or any(
            actual['assets'][n][k] != contract['assets'][n][k] for n in actual['assets'] for k in ('bytes', 'sha256')):
        raise ValueError('Original resource asset identity differs')
    expected = ''.join(f'{r["path"]} {r["file"]["bytes"]} {r["file"]["sha256"]}\n' for r in actual['modules'])
    if (root / 'simulation/original-modules').read_text(encoding='ascii') != expected:
        raise ValueError('Original resource guest policy differs')
    return actual


def command_line(original):
    value = PROBE['command_line'](original)
    value = value.replace('init=/p1-probe', 'init=/init').replace('rdinit=/p1-probe', 'rdinit=/init')
    return value.replace('p1.probe=' + PROBE['PROFILE'], 'p1.execution=' + PROFILE)


def install_api_for(profile):
    if profile not in (None, 'original-p1-virtual-install-v1', 'original-p1-virtual-dev-install-v1'):
        raise ValueError('Unknown exact P1 install profile')
    return runpy.run_path(str(HERE / ('p1-dev-install.py' if profile ==
        'original-p1-virtual-dev-install-v1' else 'newp1-virtual-install.py')))


def install_options(profile, allow_updater_writes, allow_dev_signature_bypass):
    if type(allow_dev_signature_bypass) is not bool:
        raise ValueError('Explicit bool required for allow_dev_signature_bypass')
    options = dict(allow_updater_writes=allow_updater_writes)
    if profile == 'original-p1-virtual-dev-install-v1':
        options['allow_dev_signature_bypass'] = allow_dev_signature_bypass
    elif allow_dev_signature_bypass:
        raise ValueError('Dev signature authorization requires exact dev install profile')
    return options


def trust_selection(update, *, install_profile, trust_profile=None, pinned_key=None, trusted_key_model=None):
    if trusted_key_model != update.get('trusted_key_model_selection'):
        raise ValueError('Explicit dev trusted-key selection differs from update build')
    if trusted_key_model is not None and install_profile != 'original-p1-virtual-dev-install-v1':
        raise ValueError('Dev trusted-key selection requires exact dev install profile')
    selected = None
    if trust_profile is not None or pinned_key is not None:
        if install_profile != 'original-p1-virtual-install-v1' or trust_profile != 'virtual-p1-pinned-key-v1' or pinned_key is None:
            raise ValueError('Stock trust selection requires exact official install profile and independent pinned PEM')
        selected = dict(profile=trust_profile, pinned_key=UPDATE['record'](pinned_key))
    if selected != update.get('trust_selection'):
        raise ValueError('Explicit stock trust selection differs from update build')
    observed = (update.get('sd_read_observation') or {}).get('trust_key')
    if selected and (not observed or observed.get('profile') != trust_profile):
        raise ValueError('Stock trust selection lacks built service contract')
    if not selected and observed and observed.get('profile') is not None:
        raise ValueError('Unselected stock trust service')
    if (trusted_key_model is None) != (update.get('trusted_key_model') is None):
        raise ValueError('Dev trust selection lacks built adapter contract')
    return selected


def build(update_manifest, output, *, read_only=True, qemu_build=DEFAULT_QEMU,
          board_runtime=HERE / 'runtime', media_resources=None, sd_read_profile=None,
          install_profile=None, allow_updater_writes=False, allow_dev_signature_bypass=False,
          trust_profile=None, pinned_key=None, trusted_key_model=None, storage_profile=None, tail_profile=None,
          pmbp_profile=None, pmbp_core_source=None, pmbp_reviewed_sources=None):
    UPDATE['storage_selection'](storage_profile, install_profile=install_profile, read_only=read_only,
                                allow_updater_writes=allow_updater_writes)
    PMBP['selected'](pmbp_profile)
    if pmbp_profile is not None and (pmbp_core_source is None or pmbp_reviewed_sources is None or not install_profile or read_only or not allow_updater_writes):
        raise ValueError('PMBP requires explicit writable P1 install, reviewed core source and external source record')
    os.umask(0o077)
    update_manifest = UPDATE['absolute'](update_manifest)
    update, update_row = UPDATE['checked_json'](update_manifest)
    if update.get('tail_profile') != tail_profile:
        raise ValueError('Explicit execution tail selection differs from update build')
    UPDATE['tail_selection'](tail_profile, mode=update['mode'], install_profile=install_profile,
        signature_schema=((update.get('sd_read_observation') or {}).get('trust_key') or {}).get('contract', {}).get('schema'))
    instance = Path(update['instance']['path'])
    qemu_build, board_runtime = map(UPDATE['absolute'], (qemu_build, board_runtime))
    output = PERSIST['fresh_output'](output, instance, update_manifest.parent, qemu_build, board_runtime)
    try:
        if update.get('status') != 'built' or update.get('schema') != 'a7c2-p1-update-boot-v1':
            raise ValueError('Expected built original-p1 update manifest')
        if not isinstance(read_only, bool):
            raise ValueError('Explicit bool required for read_only')
        kernel = checked(update['p1']['kernel.img'])
        module = checked(update['persistent_module'])
        contract = update['module_contract']
        UPDATE['storage_selection'](storage_profile, install_profile=install_profile, read_only=read_only,
                                    allow_updater_writes=allow_updater_writes, module=contract)
        if update.get('storage_profile') != storage_profile:
            raise ValueError('Explicit execution storage selection differs from update build')
        if not contract.get('build_bound') or kernel['sha256'] != PROBE['KERNEL_SHA']:
            raise ValueError('Original-p1 kernel/module receipt required')
        receipts = contract['receipts']
        verified = UPDATE['module_contract'](module, kernel, receipts[0]['path'],
                                            receipts[1]['path'] if len(receipts) > 1 else None)
        if verified != contract:
            raise ValueError('Module contract changed after update build')
        if not read_only and not verified['updater_write_eligible']:
            raise ValueError('Original updater writes require the large-BIO-fixed module')
        install_api = install_api_for(install_profile)
        dev_install = install_profile == 'original-p1-virtual-dev-install-v1'
        options = install_options(install_profile, allow_updater_writes, allow_dev_signature_bypass)
        selected_trust = trust_selection(update, install_profile=install_profile, trust_profile=trust_profile,
                                         pinned_key=pinned_key, trusted_key_model=trusted_key_model)
        decrypt_profile = update.get('newdecrypt_profile')
        decrypt = ((update.get('sd_read_observation') or {}).get('trust_key') or {}).get('newdecrypt')
        UPDATE['newdecrypt_selection'](decrypt_profile, mode=update['mode'],
            original_resources=bool(update.get('original_resources')), install_profile=install_profile,
            read_only=read_only, trust_profile=trust_profile, pinned_key=pinned_key, trusted_key_model=trusted_key_model)
        if (decrypt['selection']['profile'] if decrypt is not None else None) != decrypt_profile:
            raise ValueError('Declared CBC selection differs from update observer contract')
        if install_profile is not None:
            install_api['admit'](install_profile, mode=update['mode'], read_only=read_only,
                media=media_resources, sd=update.get('sd'), module=verified, **options)
            if (sd_read_profile is not None or update.get('install_profile') != install_profile
                    or update.get('allow_dev_signature_bypass', False) is not allow_dev_signature_bypass):
                raise ValueError('Install/read-only execution profiles mixed or differ from update build')
        elif update.get('install_profile') or allow_updater_writes is not False:
            raise ValueError('Install authorization requires explicit execution profile')
        sd_api = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
        if sd_read_profile is not None:
            sd_api['admit'](sd_read_profile, mode=update['mode'], read_only=read_only,
                            media=media_resources, sd=update.get('sd'), module=verified)
        elif update.get('sd_read_observation') and install_profile is None:
            raise ValueError('SD input observation requires explicit execution profile')
        if read_only and update.get('sd') is not None and sd_read_profile is None:
            raise ValueError('Read-only init probe cannot run a BODYDATA receiver')
        inputs = [update_row, kernel, module, *receipts, *contract.get('storage_inputs', []), checked(update['initrd']),
                  checked(update['p1']['kemco.txt']), checked(update['instance']['wire'])]
        media = media_row = None
        if media_resources is not None:
            if ((not read_only and install_profile is None)
                    or (update.get('sd') is not None and not (sd_read_profile or install_profile))
                    or update['mode'] != ('virtual-dev-sd-update-v1' if dev_install else 'official')):
                raise ValueError('Media init experiment requires stock receiver and read-only/no-SD input')
            media_api = runpy.run_path(str(HERE / 'p1-media-init-probe.py'))
            media, media_row = media_api['check'](Path(update['output']) / 'root', kernel, media_resources)
            production_row = checked(media['qemu_receipt'])
            qemu = checked(media['qemu'])
            if Path(qemu['path']).parent != qemu_build:
                raise ValueError('Media QEMU path differs from admitted provider')
        else:
            production, production_row = UPDATE['checked_json'](qemu_build.parent / 'qemu-result.json')
            qemu = UPDATE['record'](qemu_build / 'qemu-system-aarch64')
            if (production.get('status') != 'compiled' or production.get('board_profile') != 'persistent-flash-cold-v1'
                    or production.get('test_fixture_only') is not False
                    or qemu['sha256'] != production.get('qemu_binary_sha256')):
                raise ValueError('Expected SHA-bound production persistent QEMU')
        inputs.extend((qemu, production_row, UPDATE['record'](Path(__file__)),
                       UPDATE['record'](HERE / 'guest/update-storage-bootstrap'),
                       UPDATE['record'](HERE / 'p1-module-probe.py')))
        root = output / 'root'
        UPDATE['command'](['cp', '-a', '--reflink=auto', Path(update['output']) / 'root', root], output, 'copy-root')
        originals = {}
        evidence, _ = UPDATE['checked_json'](HERE.parent / '2026-11-03-p1-update-flow/source-identities.json')
        expected_files = {row['path'].split('/updater-root/', 1)[1]: row
                          for key,row in evidence.items() if key.startswith('p1_')}
        if set(update['original_files']) != set(expected_files):
            raise ValueError('Original p1 evidence set differs')
        for name, row in update['original_files'].items():
            if any(row[k] != expected_files[name][k] for k in ('bytes', 'sha256')):
                raise ValueError('Original p1 source baseline differs: ' + name)
            actual = UPDATE['record'](root / name)
            if name == 'usr/lib/libsdfileinputupdaterapi.so' and update['mode'] == UPDATE['MODES'][1]:
                inputs.append(checked(row))
                dev = runpy.run_path(str(HERE / 'dev-update-profile.py'))
                dev['verify_derived_receiver'](root / name, update['receiver'])
            elif any(actual[k] != row[k] for k in ('bytes', 'sha256')):
                raise ValueError('Original business bytes differ: ' + name)
            originals['/' + name] = actual
        resources = resource_binding(root, update)
        if dev_install:
            environment = install_api['install_environment'](update['virtual_install'])
            expected_bootstrap = install_api['bootstrap_source'](
                install_kind=environment['A7C2_P1_DEV_INSTALL']).encode('ascii')
        else:
            expected_bootstrap = (HERE / 'guest/update-storage-bootstrap').read_bytes()
        if tail_profile is not None:
            expected_bootstrap = sd_api['tail_api']()['bootstrap_source'](
                expected_bootstrap.decode('ascii'), tail_profile).encode('ascii')
        if decrypt_profile is not None:
            expected_bootstrap = sd_api['newdecrypt_api']()['bootstrap_source'](
                expected_bootstrap.decode('ascii'), decrypt['selection']).encode('ascii')
        if (root / 'init').read_bytes() != expected_bootstrap:
            raise ValueError('Update bootstrap changed; rebuild update manifest')
        bootstrap = UPDATE['record'](root / 'init')
        storage_cpio = UPDATE['storage_preflight'](update, root, storage_profile,
            read_only=read_only, allow_updater_writes=allow_updater_writes)
        if storage_cpio != update.get('storage_cpio_bindings', {}):
            raise ValueError('Update storage CPIO/source binding drift')
        if any(bootstrap[k] != update['bootstrap'][k] for k in ('bytes', 'sha256')):
            raise ValueError('Update bootstrap receipt differs')
        simulation = root / 'simulation'
        sd_observation = None
        if sd_read_profile is not None or install_profile is not None:
            if qemu['sha256'] != sd_api['QEMU_SHA']:
                raise ValueError('SD read profile provider identity differs')
            if install_profile:
                sd_observation = install_api['preflight'](update, root, read_only, media, install_profile, **options)
            else:
                sd_observation = sd_api['preflight'](update, root, read_only, media, sd_read_profile)
            inputs.extend(sd_observation['sources'] + [update['sd_read_package_source']])
            if dev_install:
                hook = update['file_media']; prepared = hook['identity_adapter']['prepared']
                inputs.extend([prepared['compiler'], prepared['linker'], *prepared['link_inputs'],
                    hook['source'], hook['output'], hook['identity_adapter']['command']['stdout'],
                    hook['identity_adapter']['command']['stderr'],
                    UPDATE['record'](Path(update['output']) / 'file-media-build.json')])
            if selected_trust:
                UPDATE['stock_trust_preflight'](update, root)
            for name in ('observer_source', 'observer'):
                inputs.append(checked(sd_observation[name]))
        COLD['_compile_audit'](HERE / 'guest/cold-start-audit.c', root / 'lib/libc-2.25.so', simulation / 'audit')
        helper_source = output / 'block-readonly.c'
        helper_source.write_text(READONLY_SOURCE, encoding='ascii')
        COLD['_compile_audit'](helper_source, root / 'lib/libc-2.25.so', simulation / 'block-readonly')
        if sd_read_profile is not None:
            sd_guard = output / 'sd-target-ro.c'
            sd_guard.write_text(sd_api['RO_GUARD'] + READONLY_SOURCE[READONLY_SOURCE.index('extern int __libc_start_main'):], encoding='ascii')
            COLD['_compile_audit'](sd_guard, root / 'lib/libc-2.25.so', simulation / 'sd-target-ro')
        if install_profile:
            write_guard = output / 'install-target.c'
            write_guard.write_text(install_api['WRITE_GUARD'] + READONLY_SOURCE[READONLY_SOURCE.index('extern int __libc_start_main'):], encoding='ascii')
            UPDATE['command'](['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
                '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-stack-protector', '-Wl,--no-undefined', '-Wl,-e,_start',
                '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', write_guard, root / 'lib/libc-2.25.so',
                '-o', simulation / 'install-target'], output, 'install-target-build')
            (simulation / 'install-target').chmod(0o755)
            (simulation / 'backup-trusted-file-load').write_text(install_profile + '\n', encoding='ascii')
        (simulation / 'execution-observer').touch()
        if read_only:
            (simulation / 'read-only-probe').touch()
        backup_file_load = None
        if resources:
            status_source = output / 'uipc-native-status.c'
            status_source.write_text(UIPC_STATUS_SOURCE + READONLY_SOURCE[READONLY_SOURCE.index('extern int __libc_start_main'):], encoding='ascii')
            UPDATE['command'](['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
                '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-stack-protector', '-Wl,--no-undefined', '-Wl,-e,_start',
                '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', status_source,
                root / 'lib/libdl-2.25.so', root / 'lib/libc-2.25.so',
                '-o', simulation / 'uipc-native-status'], output, 'uipc-status-build')
            (simulation / 'uipc-native-status').chmod(0o755)
            if read_only or install_profile:
                backup = update['p2'].get('backup')
                if (not backup or backup.get('kind') != 'file' or not 0 < backup['size'] <= 16 * 1024**2
                        or not re.fullmatch('[0-9a-f]{64}', backup['sha256'])):
                    raise ValueError('Read-only resource probe requires actual original Backup.bin')
                if install_profile and (backup['size'] != media_api['BACKUP_BYTES'] or backup['sha256'] != media_api['BACKUP_SHA']):
                    raise ValueError('Install trusted Backup file differs')
                (simulation / 'backup-file-source').write_text(
                    f'/setting/Backup.bin {backup["size"]} {backup["sha256"]}\n', encoding='ascii')
                backup_file_load = dict(path='/setting/Backup.bin', bytes=backup['size'], sha256=backup['sha256'],
                    appended_parameter='Backup_load=1', original_argv_preserved=True, Backup_save=0,
                    only_after_block_readonly=read_only, trusted_file_load=bool(install_profile),
                    install_profile=install_profile, file_readback_required=True)
        if bool(resources and resources.get('media_profile')) != bool(media):
            raise ValueError('Media resources and provider must be explicitly enabled together')
        if media:
            if resources['media_receipt'] != media_row:
                raise ValueError('Update/execution media receipts differ')
            inputs.extend((media_row, media['helper_source'], *media['provider_inputs'],
                           media['previous_context'], media['previous_serial']))
            helper_source = output / 'media-backup-query.c'
            helper_source.write_text(media_api['QUERY_SOURCE'], encoding='ascii')
            UPDATE['command'](['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
                '-fuse-ld=lld', '-nostdlib', '-O2', '-fno-stack-protector', '-Wl,--no-undefined', '-Wl,-e,_start',
                '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', helper_source,
                root / 'usr/lib/libbackup.so', root / 'usr/lib/libosal_uipc.so', root / 'lib/libc-2.25.so',
                '-Wl,-rpath-link,' + str(root / 'usr/lib'), '-Wl,-rpath-link,' + str(root / 'lib'),
                '-o', simulation / 'media-backup-query'], output, 'media-backup-query-build')
            (simulation / 'media-backup-query').chmod(0o755)
        audit_names = ('/sbin/init', '/usr/bin/mkramdsk.sh', '/usr/bin/insmod.sh', '/usr/bin/UdtrMain.sh')
        if resources:
            for row in resources['modules']:
                originals[row['path']] = UPDATE['record'](root / row['path'].lstrip('/'))
            for name, row in resources['assets'].items():
                originals['/' + name] = row
            audit_names += tuple(row['path'] for row in resources['modules']) + tuple('/' + n for n in resources['assets'])
            inputs.append(UPDATE['record'](HERE / 'p1-persistent-module.py'))
        if install_profile:
            originals['/simulation/sony_persistent_flash.ko'] = UPDATE['record'](simulation / 'sony_persistent_flash.ko')
            audit_names += ('/simulation/sony_persistent_flash.ko',)
        (simulation / 'original-audit').write_text(''.join(
            f'{name} {originals[name]["bytes"]} {originals[name]["sha256"]}\n' for name in audit_names), encoding='ascii')
        UPDATE['copy_input'](update['instance']['wire']['path'], output / 'persistent-geometry.bin')
        UPDATE['copy_input'](kernel['path'], output / 'kernel.img')
        handoff = UPDATE['record'](board_runtime / 'analysis/boot-handoff.bin')
        inputs.append(handoff)
        UPDATE['copy_input'](handoff['path'], output / 'boot-handoff.bin')
        pmbp_contract = None
        if pmbp_profile is not None:
            provider = PMBP['provider']()
            source_context = provider.reviewed_sources(pmbp_reviewed_sources)
            driver_source = HERE / 'persistent-flash/sony_persistent_flash.c'
            pmbp_inputs = [UPDATE['record'](path) for path in (pmbp_core_source, driver_source)]
            pmbp_inputs += [qemu, checked(update['instance']['wire']), *receipts, source_context.record]
            # This receipt is independently read from the existing verified module build.
            module_receipt, _ = UPDATE['checked_json'](receipts[0]['path'])
            with DISK['lease'](instance) as build_leased, provider.p1_ofd_lease(build_leased) as build_lock:
                build_cap = provider.from_build_checked(root, leased=build_leased, lock=build_lock,
                    module_receipt=module_receipt, core_source=pmbp_core_source, driver_source=driver_source,
                    qemu=qemu, build_inputs=pmbp_inputs, reviewed_sources=source_context,
                    profile_contract=dict(profile=pmbp_profile, execution=PROFILE, install_profile=install_profile,
                                          storage_profile=storage_profile, qemu_sha256=qemu['sha256']),
                    instance_wire=checked(update['instance']['wire']))
                pmbp_contract = PMBP['prepare'](root, build_cap, output / 'pmbp-build', profile=pmbp_profile)
            (root / 'etc/ld.so.preload').write_text(pmbp_contract['preload'], encoding='ascii')
            inputs.extend(pmbp_inputs)
        if tail_profile is not None and pmbp_contract is not None:
            sd_observation = sd_api['derive_tail_pmbp'](update, root, pmbp_contract)
        elif pmbp_contract is not None:
            sd_observation = sd_api['derive_pmbp'](update, root, pmbp_contract)
        initrd = output / 'probe.cpio.gz'
        UPDATE['archive'](root, initrd)
        if update.get('sd') is not None:
            # The validated update initrd already contains the real FAT media member.
            import gzip, stat
            card = checked(update['sd']['image'])
            with initrd.open('ab') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=1) as stream:
                UPDATE['cpio_entry'](stream, 'image_mmca', stat.S_IFREG | 0o600, card['bytes'], Path(card['path']))
                UPDATE['cpio_entry'](stream, 'TRAILER!!!', 0)
            inputs.append(card)
        sd_cpio = None
        if sd_read_profile is not None or install_profile is not None:
            expected_cpio = (install_api['bindings'](root, card, trusted_key_model=update.get('trusted_key_model'))
                             if dev_install else sd_api['bindings'](root, card))
            if pmbp_contract is not None:
                expected_cpio.update(PMBP['cpio_rows'](root, pmbp_contract))
            if dev_install and update.get('trusted_key_model'):
                expected_cpio.update(update['trusted_key_model']['original_bindings'])
            extra = (('simulation/install-target', 'simulation/backup-trusted-file-load') if install_profile else
                     ('simulation/sd-target-ro', 'simulation/read-only-probe'))
            for name in ('simulation/block-readonly', 'simulation/media-backup-query',
                         'simulation/media-profile', 'simulation/original-modules', 'simulation/backup-file-source') + extra + tuple(r['path'].lstrip('/') for r in resources['modules']):
                path = root / name
                row = UPDATE['record'](path)
                expected_cpio[name] = dict(bytes=row['bytes'], sha256=row['sha256'], mode=path.stat().st_mode)
            sd_cpio = (install_api if dev_install else sd_api)['cpio_readback'](initrd, expected_cpio)
            if decrypt_profile is not None or tail_profile is not None or pmbp_contract is not None:
                sd_observation = dict(sd_observation, cpio_bindings=sd_cpio, cpio_readback=sd_cpio)
                derived = dict(update, initrd=UPDATE['record'](initrd), sd_read_observation=sd_observation)
                if pmbp_contract is not None:derived.update(pmbp_profile=pmbp_contract['profile'],pmbp=pmbp_contract)
                (install_api if dev_install else sd_api)['preflight'](derived, root, read_only, media, install_profile,
                    **options if dev_install else {})
        if storage_profile is not None:
            storage_cpio = sd_api['cpio_readback'](initrd, storage_cpio)
        if pmbp_contract is not None:
            pmbp_rows = PMBP['cpio_rows'](root, pmbp_contract)
            if sd_api['cpio_readback'](initrd, pmbp_rows) != pmbp_rows:
                raise ValueError('PMBP final CPIO readback differs')
            sd_api['tail_api']()['_cpio_owners'](initrd, set(pmbp_rows))
        cmdline = command_line(Path(update['p1']['kemco.txt']['path']).read_text())
        (output / 'cmdline.txt').write_text(cmdline + '\n', encoding='ascii')
        base = board_runtime / 'analysis/boards/virt-four.dtb'
        libfdt = (board_runtime / 'sources/qemu-tools/usr/lib/libfdt.so.1').resolve(strict=True)
        inputs.extend((UPDATE['record'](base), UPDATE['record'](libfdt)))
        PROBE['board'](base, libfdt, output / 'virt.dtb', cmdline, initrd.stat().st_size, mmc_iomap=bool(media))
        if media:
            runpy.run_path(str(HERE / 'p1-mmc-bootstrap.py'))['iomaps'](output / 'virt.dtb', libfdt)
        with DISK['lease'](instance) as leased:
            disk_sha = DISK['hashed'](leased['fd'])
            stamp = DISK['stamp'](leased['fd'])
            expected = update['instance']['disk']
            if (stamp[:3] != (expected['device'], expected['inode'], expected['bytes'])
                    or disk_sha != expected['sha256']):
                raise ValueError('Leased disk changed since update build')
            state = UPDATE['record'](instance / 'instance.json')
            geometry = checked(update['instance']['geometry'])
        artifacts = [UPDATE['record'](output / name) for name in (
            'persistent-geometry.bin', 'kernel.img', 'boot-handoff.bin', 'probe.cpio.gz', 'virt.dtb', 'cmdline.txt')]
        for row in inputs:
            checked(row)
        manifest = dict(schema=PROFILE, status='built', output=str(output), instance=str(instance),
            disk_sha256=disk_sha, disk_device=stamp[0], disk_inode=stamp[1], state=state, geometry=geometry,
            update_manifest=update_row, original_files=originals, original_audit=list(audit_names),
            inputs=inputs, artifacts=artifacts, qemu=qemu, cmdline=cmdline, p2=update['p2'],
            module_contract=verified, mode=update['mode'], read_only=read_only,
            storage_profile=storage_profile, storage_cpio_readback=storage_cpio,
            install_profile=install_profile, allow_updater_writes=allow_updater_writes,
            allow_dev_signature_bypass=allow_dev_signature_bypass, trust_selection=selected_trust,
            trusted_key_model_selection=trusted_key_model, trusted_key_model=update.get('trusted_key_model'),
            trust_execution=update.get('trust_execution'),
            virtual_install=update.get('virtual_install'),
            sd_read_profile=sd_read_profile, sd_read_observation=sd_observation, sd_cpio_readback=sd_cpio,
            no_install=False if install_profile else True if sd_read_profile else None,
            bodydata_installation_verified=False, normal_ap_frontend=False,
            board=dict(host_ram_mib=24576, ddr_base='0x400000000', gic_version=2,
                       cpu='cortex-a35', counter_hz=2000000, initcall_blacklist=list(PROBE['BLACKLIST'])),
            original_module_allowlist=update['original_module_allowlist'], original_resources=resources,
            backup_file_load=backup_file_load, media_resources=media_row,
            media_provider_profile='original-p1-mmc-identification-v1' if media else None,
            storage_replacements=update['storage_replacements'],
            full_hardware_boot_verified=False, physical_devices_used=False)
        if dev_install:
            manifest['file_media'] = update['file_media']
        if pmbp_contract is not None:
            manifest['pmbp'] = pmbp_contract
        if decrypt_profile is not None:
            manifest['newdecrypt_profile'] = decrypt_profile
        if tail_profile is not None:manifest['tail_profile'] = tail_profile
        save(output / 'manifest.json', manifest)
        return manifest
    except BaseException as error:
        save(output / 'failure.json', dict(error=type(error).__name__ + ': ' + str(error), guest_started=False))
        raise


def collect(raw, manifest):
    text = raw.decode('utf-8', errors='replace').replace('\r', '')
    credentials = re.findall(r'^UPDATE_CREDENTIAL kind=(Uid:|Gid:) values=(.*)$', text, re.M)
    modules = re.findall(r'^UPDATE_MODULES_BEGIN\n(.*?)^UPDATE_MODULES_END$', text, re.M | re.S)
    p2 = re.findall(r'^UPDATE_P2_ACTUAL base=(\d) mode5=(\d) comp=(\d) uincomp=(\d) selected=(\d+) frontend=notexecuted$', text, re.M)
    actual_p2 = dict(zip(('mode', 'mode5', 'comp', 'uincomp', 'selected'), map(int, p2[0]))) if len(p2) == 1 else None
    expected = manifest['p2']
    p2_bound = bool(actual_p2 and all(actual_p2[k] == int(expected['flags'][k]) for k in ('mode','mode5','comp','uincomp'))
                    and actual_p2['selected'] == expected['predicted_outer_mode'])
    ro = re.findall(r'^UPDATE_READONLY node=(\S+) set_rc=(-?\d+) get_rc=(-?\d+) readonly=(\d+)$', text, re.M)
    audit = {}
    for name in manifest['original_audit']:
        row = manifest['original_files'][name]
        audit[name] = text.count(f'UPDATE_ORIGINAL_BYTES path={name} bytes={row["bytes"]} sha256={row["sha256"]} rc=0\n') == 1
    process_blocks = re.findall(r'^UPDATE_PROCESS pid=(\d+) comm=([^\n]+)\n([^\n]*)\n', text, re.M)
    maps = re.findall(r'^UPDATE_MAPS_BEGIN pid=(\d+)\n(.*?)^UPDATE_MAPS_END pid=\1$', text, re.M | re.S)
    # Original BusyBox leaves $$ literal in PS4; /proc PID1 + mappings prove exec.
    init_process = ('/bin/sh\x00-x\x00/sbin/init\x00' in text
                    and any(pid == '1' and '/bin/busybox' in body for pid, body in maps))
    init = (all(audit.values()) and 'UPDATE_ORIGINAL_INIT_EXEC=/sbin/init ' in text and init_process
            and re.search(r'^\+UPDATE_TRACE pid=(?:1|\$\$) (?:export HOME=/|HOME=/)', text, re.M) is not None)
    dispatch = re.findall(r'^\[DETAIL\] MODE=(\d+)\s*$', text, re.M)
    errors = re.findall(r'^.*(?:Unhandled fault|Internal error:|Kernel panic|pc :|PC is at|Bus error|Segmentation fault|UPDATE_BOOT_BLOCKED|open /dev/uipc error:|Backup_read\(\) error|SENSER:-\d+|SKData_Core_Init error|SIO driver open failed|device_initialize\(\) failed|backup_init\(\) error|Unknown symbol|Abort \(PC=).*$' , text, re.M)
    exceptions = [dict(program=program, comm=comm, pid=int(pid), pc=pc) for program,comm,pid,pc in
        re.findall(r'^program: (\S+)\(([^)]+)\) \(pid: (\d+),.*?^Abort \(PC=(0x[0-9a-f]+)\)', text, re.M | re.S)]
    power_rc = re.findall(r'^Power IC type : (\d+)\s*$', text, re.M)
    queue_rc = re.findall(r'SKData_Core_Init osal_reg_sync_msg_queue_cb (-?\d+)', text)
    rejects = re.findall(r'UPDATE_MODULE_REJECT applet=(\S+) module=(\S+) adapter_rc=(\d+) original_module_rc=(\S+) reason=(\S+)', text)
    loads = [dict(path=path, rc=int(rc)) for path, rc in re.findall(
        r'^UPDATE_MODULE_RESULT module=(\S+) original_module_rc=(\d+)$', text, re.M)]
    attempts = [dict(path=path, bytes=int(size), sha256=digest, argc=int(argc)) for path,size,digest,argc in re.findall(
        r'^UPDATE_MODULE_BEGIN module=(\S+) bytes=(\d+) sha256=([0-9a-f]{64}) argc=(\d+)$', text, re.M)]
    live = re.findall(r'^UPDATE_RESOURCE_MODULES_BEGIN\n(.*?)^UPDATE_RESOURCE_MODULES_END$', text, re.M | re.S)
    devices = re.findall(r'^UPDATE_RESOURCE_DEVICES_BEGIN\n(.*?)^UPDATE_RESOURCE_DEVICES_END$', text, re.M | re.S)
    mounts = re.findall(r'^UPDATE_RESOURCE_MOUNTS_BEGIN\n(.*?)^UPDATE_RESOURCE_MOUNTS_END$', text, re.M | re.S)
    media_live = re.findall(r'^UPDATE_MEDIA_KERNEL_BEGIN\n(.*?)^UPDATE_MEDIA_KERNEL_END$', text, re.M | re.S)
    expected_resources = manifest.get('original_resources') or {}
    resource_results = []
    for row in expected_resources.get('modules', []):
        observed = [a for a in attempts if a['path'] == row['path']]
        returns = [a['rc'] for a in loads if a['path'] == row['path']]
        name = Path(row['path']).stem.replace('-', '_')
        resource_results.append(dict(path=row['path'], attempts=observed, returncodes=returns,
            source_bound=len(observed) == 1 and all(observed[0][k] == row['file'][k] for k in ('bytes','sha256')),
            live_observed=any(re.search(r'^' + re.escape(name) + r' \d+ \d+ .* Live ', body, re.M) for body in live + media_live),
            loaded=len(returns) == 1 and returns == [0]))
    udtr = (init and 'UPDATE_ORIGINAL_SCRIPT path=/usr/bin/UdtrMain.sh ' in text
            and any('/bin/sh\x00-x\x00/usr/bin/UdtrMain.sh\x00' in cmdline
                    and any(map_pid == pid and '/bin/busybox' in body for map_pid,body in maps)
                    for pid,comm,cmdline in process_blocks))
    receiver_names = ('mf', 'sen.elf', 'sdfileinput.elf', 'uudfileinput.elf', 'sauu')
    processes = [dict(pid=int(pid), comm=comm, cmdline=cmdline.replace('\x00',' ')) for pid,comm,cmdline in process_blocks]
    rw = re.findall(r'^UPDATE_INSTALL_TARGET node=(\S+) get_rc=(-?\d+) readonly=(\d+) project_backend=(\d+)$', text, re.M)
    expected_rw = {'/dev/' + n for n in runpy.run_path(str(HERE / 'newp1-virtual-install.py'))['NODES']}
    rw_verified = (len(rw) >= 20 and len(rw) % 20 == 0 and all(
        {r[0] for r in rw[i:i+20]} == expected_rw and all(r[1:] == ('0','0','1') for r in rw[i:i+20])
        for i in range(0,len(rw),20)))
    return dict(root_verified=credentials == [('Uid:', '0,0,0,0'), ('Gid:', '0,0,0,0')],
        kernel_release_verified=text.count('UPDATE_RELEASE value=4.9.186-scel\n') == 1,
        module_loaded=(text.count('UPDATE_PERSISTENT_INSMOD_RC=0\n') == 1 and len(modules) == 1
                       and re.search(r'^sony_persistent_flash \d+ \d+ .* Live ', modules[0], re.M) is not None),
        actual_p2=actual_p2, p2_matches_build=p2_bound, original_bytes_verified=audit,
        read_only_verified=(len(ro) == 20 and len({r[0] for r in ro}) == 20
                            and all(r[1:] == ('0','0','1') for r in ro)),
        writable_target_checks=rw, writable_targets_verified=rw_verified,
        storage_parameter_readbacks=re.findall(r'^UPDATE_STORAGE_PARAMETER profile=(\S+) name=functional_alfred_trim_zero value=(\S+)$', text, re.M),
        storage_profile_verified=(manifest.get('storage_profile') == UPDATE['TRIM_STORAGE_PROFILE']
            and re.findall(r'^UPDATE_STORAGE_PARAMETER profile=(\S+) name=functional_alfred_trim_zero value=(\S+)$', text, re.M)
                == [(UPDATE['TRIM_STORAGE_PROFILE'], 'Y')]
            and text.count('UPDATE_STORAGE_ALIAS nflasha4=cnflasha4 verified=1\n') == 1),
        original_init_executed=bool(init), udtrmain_executed=bool(udtr),
        actual_dispatch_modes=list(map(int, dispatch)), processes=processes,
        maps_observed=bool(maps), receivers_observed=[r for r in processes if r['comm'] in receiver_names],
        unsupported_modules=[dict(applet=r[0], module=r[1], rc=int(r[2]), original_rc=r[3], reason=r[4]) for r in rejects],
        original_error_lines=errors, first_guest_error=errors[0] if errors else None,
        exceptions=exceptions, first_exception_pc=exceptions[0]['pc'] if exceptions else None,
        power_ic_returncodes=list(map(int, power_rc)), receiver_queue_returncodes=list(map(int, queue_rc)),
        native_device_nodes=[dict(name=name, major=int(major), minor=int(minor)) for major,minor,name in re.findall(
            r'^c\S+\s+\d+\s+\d+\s+\d+\s+(\d+),\s*(\d+)\s+[^\n]+ (/dev/(?:uipc|backup|mcmn|stream2|mmc[^ /]*|nvme[^ /]*))$', text, re.M)],
        resource_parameters=dict(re.findall(r'^UPDATE_RESOURCE_PARAMETER path=(/[^\n]+)\n([^\n]+)\n', text, re.M)),
        original_module_init_returns=[dict(module=name, rc=int(rc)) for name,rc in re.findall(
            r'^.*initcall init_module\+\S+ \[([A-Za-z_0-9]+)\] returned (-?\d+) after .*$', text, re.M)],
        original_resource_attempts=attempts, original_resource_returns=loads, original_resources=resource_results,
        resource_modules_raw=live, resource_devices_raw=devices, resource_mounts_raw=mounts,
        native_uipc_getstatus_returncodes=[int(rc) for rc in re.findall(
            r'^UPDATE_UIPC_NATIVE_GETSTATUS function=u_uipc_init original_rc=(-?\d+) errno=\d+$', text, re.M)],
        native_uipc_stat_words=[list(map(int, words.split(','))) for words in re.findall(
            r'^UPDATE_UIPC_NATIVE_STAT words=([0-9,]+)$', text, re.M)],
        backup_file_readbacks=[dict(bytes=int(n), sha256=digest, rc=int(rc)) for n,digest,rc in re.findall(
            r'^UPDATE_BACKUP_FILE bytes=(\d+) sha256=([0-9a-f]{64}) rc=(\d+)$', text, re.M)],
        original_resource_chain_loaded=bool(resource_results) and all(
            r['source_bound'] and r['loaded'] and r['live_observed'] for r in resource_results),
        media_backup_query=runpy.run_path(str(HERE / 'p1-media-init-probe.py'))['query_evidence'](raw),
        media_kernel_snapshots=media_live,
        original_media_init_verified=False,
        receiver_completed=False, full_original_startup_verified=False,
        raw_serial_sha256=hashlib.sha256(raw).hexdigest(),
        bypass_configured=manifest['mode'] != 'official', bypass_executed=False,
        bodywriter_executed=False, installation_verified=False, normal_ap_frontend=False,
        sdfileinput_read_verified=False, physical_hardware_verified=False)


def owner_identity(pid):
    path = Path('/proc') / str(pid)
    raw = (path / 'stat').read_text()
    return dict(pid=pid, starttime=raw[raw.rindex(')') + 2:].split()[19],
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def launch_command(manifest, fd, output, name):
    # Reuse the proven p1 board, not the 4.9.337-only normal persistent launcher.
    argv = PROBE['launch_command'](manifest, fd, output)
    offset = argv.index('-accel')
    if manifest.get('media_resources'):
        insert = argv.index('/tools/' + Path(manifest['qemu']['path']).name)
        argv[insert:insert] = ['--setenv', 'QEMU_P1_MMC_BOOTSTRAP', manifest['media_provider_profile']]
        offset = argv.index('-accel')
    return argv[:offset] + ['-name', name] + argv[offset:]


def actual(manifest, output, *, seconds=60):
    if (manifest.get('schema') != PROFILE or manifest.get('status') != 'built'
            or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= 600):
        raise ValueError('Invalid original-p1 manifest/deadline')
    os.umask(0o077)
    stored, _ = UPDATE['checked_json'](Path(manifest['output']) / 'manifest.json')
    if stored != manifest:
        raise ValueError('Execution manifest differs from its built file')
    output = PERSIST['fresh_output'](output, manifest['instance'], manifest['output'])
    serial = output / 'serial.log'
    name = 'p1-update-' + secrets.token_hex(8)
    result = dict(schema=PROFILE, status='starting', guest_started=False, vm_signals=[], verified=False,
                  owner_name=name, installation_verified=False)
    process = connection = stream = pmbp_actual = None
    install_api = install_api_for(manifest.get('install_profile')) if manifest.get('install_profile') else None
    with DISK['lease'](manifest['instance']) as leased, (
            PMBP['provider']().p1_ofd_lease(leased) if manifest.get('pmbp') else nullcontext()) as pmbp_lock:
        try:
            for row in manifest['inputs'] + manifest['artifacts'] + [manifest['state'], manifest['geometry']]:
                checked(row)
            if manifest.get('tail_profile') is not None or ((manifest.get('sd_read_observation') or {}).get('trust_key') or {}).get('tail') is not None:
                tail_update, _ = UPDATE['checked_json'](manifest['update_manifest']['path'])
                if manifest['tail_profile'] != tail_update.get('tail_profile'):
                    raise ValueError('Execution tail declaration differs from update build')
                selected_tail = (manifest.get('sd_read_observation') or {}).get('trust_key', {}).get('tail')
                if not selected_tail or selected_tail['profile'] != manifest['tail_profile']:
                    raise ValueError('Execution tail contract missing')
                tail_api = runpy.run_path(str(HERE / 'p1-tail-source.py'))
                UPDATE['tail_selection'](manifest['tail_profile'], mode=manifest['mode'],
                    install_profile=manifest.get('install_profile'), signature_schema=selected_tail['signature_schema'])
                tail_api['recheck'](Path(manifest['output']) / 'root', selected_tail,
                    rows=[dict(row, path=str(Path(manifest['output']) / 'root' / Path(row['path']).relative_to(Path(manifest['sd_read_observation'].get('binding_root',Path(tail_update['output']) / 'root')))))
                          for row in manifest['sd_read_observation']['bindings']],
                    cpio_path=Path(manifest['output']) / 'probe.cpio.gz', cpio_bindings=manifest['sd_cpio_readback'])
            if manifest.get('install_profile'):
                update, _ = UPDATE['checked_json'](manifest['update_manifest']['path'])
                if manifest.get('newdecrypt_profile') != update.get('newdecrypt_profile'):
                    raise ValueError('Execution CBC declaration differs from update build')
                if manifest.get('newdecrypt_profile') is not None or manifest.get('tail_profile') is not None or manifest.get('pmbp') is not None:
                    update = dict(update, initrd=UPDATE['record'](Path(manifest['output']) / 'probe.cpio.gz'),
                                  sd_read_observation=manifest['sd_read_observation'])
                    if manifest.get('pmbp'):update.update(pmbp=manifest['pmbp'],pmbp_profile=manifest['pmbp']['profile'])
                if manifest.get('storage_profile') is not None or update.get('storage_profile') is not None:
                    storage_cpio = UPDATE['storage_preflight'](update, Path(manifest['output']) / 'root',
                        manifest.get('storage_profile'), read_only=manifest['read_only'],
                        allow_updater_writes=manifest.get('allow_updater_writes'))
                    if storage_cpio != manifest.get('storage_cpio_readback'):
                        raise ValueError('Execution storage CPIO contract drift')
                    runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))['cpio_readback'](
                        Path(manifest['output']) / 'probe.cpio.gz', storage_cpio)
                selected = manifest.get('trust_selection')
                trust_selection(update, install_profile=manifest['install_profile'],
                    trust_profile=selected['profile'] if selected else None,
                    pinned_key=selected['pinned_key']['path'] if selected else None,
                    trusted_key_model=manifest.get('trusted_key_model_selection'))
                if (manifest.get('trusted_key_model') != update.get('trusted_key_model')
                        or manifest.get('trust_execution') != update.get('trust_execution')
                        or manifest.get('allow_dev_signature_bypass', False) is not update.get('allow_dev_signature_bypass', False)):
                    raise ValueError('Execution dev authorization/trust contract differs')
                if (manifest.get('no_install') is not False or manifest['qemu']['sha256'] !=
                        runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))['QEMU_SHA']):
                    raise ValueError('Install provider/policy differs')
                if (manifest['install_profile'] == 'original-p1-virtual-dev-install-v1'
                        and manifest.get('file_media') != update.get('file_media')):
                    raise ValueError('Execution derived DEV file-media contract differs')
                install_api['preflight'](update, Path(manifest['output']) / 'root', manifest['read_only'],
                    manifest['media_resources'], manifest['install_profile'], **install_options(
                        manifest['install_profile'], manifest.get('allow_updater_writes'),
                        manifest.get('allow_dev_signature_bypass', False)))
                if selected:
                    UPDATE['stock_trust_preflight'](update, Path(manifest['output']) / 'root')
                cpio_api = install_api if manifest['install_profile'] == 'original-p1-virtual-dev-install-v1' else runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
                cpio_api['cpio_readback'](
                    Path(manifest['output']) / 'probe.cpio.gz', manifest['sd_cpio_readback'])
                result['partition_before'] = install_api['ranges'](leased['fd'], leased['geometry'])
            if manifest.get('sd_read_profile'):
                sd_api = runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))
                update, _ = UPDATE['checked_json'](manifest['update_manifest']['path'])
                if manifest.get('no_install') is not True or manifest['qemu']['sha256'] != sd_api['QEMU_SHA']:
                    raise ValueError('SD execution no-install/provider binding differs')
                sd_api['preflight'](update, Path(manifest['output']) / 'root', manifest['read_only'],
                                    manifest['media_resources'], manifest['sd_read_profile'])
                sd_api['cpio_readback'](Path(manifest['output']) / 'probe.cpio.gz', manifest['sd_cpio_readback'])
            before = DISK['hashed'](leased['fd'])
            st = os.fstat(leased['fd'])
            if (before != manifest['disk_sha256'] or st.st_dev != manifest['disk_device']
                    or st.st_ino != manifest['disk_inode']):
                raise ValueError('Leased instance identity/bytes changed before launch')
            argv = launch_command(manifest, leased['fd'], output, name)
            if manifest.get('pmbp'):
                index = argv.index('/tools/' + Path(manifest['qemu']['path']).name)
                argv.insert(index + 1, '-S')
                pmbp_actual = PMBP['prepare_actual'](manifest, leased=leased, lock=pmbp_lock, argv=argv,
                    cpio_readback=runpy.run_path(str(HERE / 'p1-sd-read-probe.py'))['cpio_readback'])
            with serial.open('xb') as log:
                process = subprocess.Popen(argv, env=runpy.run_path(str(HERE / 'p1-tail-source.py'))['launch_env'](
                    Path(manifest['output']) / 'root',
                    (manifest.get('sd_read_observation') or {}).get('trust_key', {}).get('tail'),
                    pmbp_contract=manifest.get('pmbp'), inherited=dict(PATH=os.defpath, LC_ALL='C'),
                    rows=[dict(row,path=str(Path(manifest['output']) / 'root' / Path(row['path']).relative_to(
                        Path(manifest['sd_read_observation'].get('binding_root', Path(tail_update['output']) / 'root')))))
                        for row in manifest['sd_read_observation']['bindings']] if manifest.get('tail_profile') else None,
                    cpio_path=Path(manifest['output']) / 'probe.cpio.gz' if manifest.get('tail_profile') else None,
                    cpio_bindings=manifest.get('sd_cpio_readback') if manifest.get('tail_profile') else None),
                    pass_fds=(leased['fd'],), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            identity = owner_identity(process.pid)
            result['owner_identity'] = identity
            if pmbp_actual is not None:
                connection, stream, command = PMBP['connect_verified'](pmbp_actual, leased=leased,
                    lock=pmbp_lock, owner=process, path=output / 'qmp.sock')
                result['pmbp_activation'] = PMBP['activate_paused'](pmbp_actual, leased=leased,
                    lock=pmbp_lock, owner=process, qmp=command, owner_name=name)
                stream.close(); connection.close(); stream = connection = None
            result.update(status='running', guest_started=True, owner_identity=identity, command=argv,
                          disk_before_sha256=before, pass_fds=[leased['fd']], deadline_seconds=seconds)
            save(output / 'result.json', result)
            deadline = time.monotonic() + seconds
            while True:
                raw = serial.read_bytes()
                if any(token in raw for token in (b'UPDATE_BOOT_BLOCKED ', b'Kernel panic', b'Internal error: Oops',
                                                   b'Entering exception monitor.')):
                    result['observation_stop'] = 'original-error'; break
                if (manifest.get('sd_read_profile') or manifest.get('install_profile')) and b'UPDATE_SD_RECEIVER_EXIT ' in raw:
                    if manifest.get('tail_profile') is None or runpy.run_path(str(HERE / 'p1-rawlog-collector.py'))['terminal'](raw):
                        result['observation_stop'] = 'receiver-exited'; break
                if process.poll() is not None:
                    result['first_host_error'] = 'Owner exited before observation ended'; break
                if time.monotonic() >= deadline:
                    result['observation_stop'] = 'deadline'
                    result['deadline_reached'] = True; break
                time.sleep(.1)
        except BaseException as error:
            result['first_host_error'] = type(error).__name__ + ': ' + str(error)
        finally:
            if process is not None and process.poll() is None:
                try:
                    if owner_identity(process.pid) != result['owner_identity']:
                        raise ValueError('Registered owner identity changed')
                    if stream: stream.close()
                    if connection: connection.close()
                    if manifest.get('pmbp'):
                        connection, stream, command = PMBP['connect_verified'](pmbp_actual, leased=leased,
                            lock=pmbp_lock, owner=process, path=output / 'qmp.sock')
                    else:
                        connection, stream, command = OWNER['qmp_connect'](output / 'qmp.sock')
                    result['qmp_name'] = command('query-name')
                    if result['qmp_name'] != {'return': {'name': name}}:
                        raise ValueError('QMP server is not this registered owner')
                    result['qmp_status'] = command('query-status')
                    descendants, pending = [], [process.pid]
                    while pending:
                        parent = pending.pop()
                        childfile = Path(f'/proc/{parent}/task/{parent}/children')
                        if childfile.exists():
                            for child in childfile.read_text().split():
                                pid = int(child)
                                descendants.append(owner_identity(pid))
                                pending.append(pid)
                    result['owner_descendants'] = descendants
                    result['registers'] = command('human-monitor-command', {'command-line': 'info registers'})
                    result['qmp_quit'] = command('quit')
                    process.wait(timeout=20)
                except BaseException as error:
                    result.update(shutdown_error=type(error).__name__ + ': ' + str(error),
                                  status='owner-retained', lease_held_until_exit=True)
                    save(output / 'result.json', result)
                    # Never release a writable instance to a second owner while QEMU lives.
                    process.wait()
                finally:
                    if stream: stream.close()
                    if connection: connection.close()
            if pmbp_actual is not None and (process is None or process.poll() is not None):
                PMBP['forget_actual'](pmbp_actual, owner=process)
            if process is not None:
                result['owner_returncode'] = process.returncode
                result['vm_signals'] = [process.returncode] if process.returncode is not None and process.returncode < 0 else []
                result['owner_absent_after_wait'] = not Path(f'/proc/{process.pid}').exists()
                result['descendants_absent_after_wait'] = all(not Path(f'/proc/{row["pid"]}').exists()
                    for row in result.get('owner_descendants', []))
            result.update(collect(serial.read_bytes() if serial.exists() else b'', manifest))
            if manifest.get('sd_read_profile'):
                try:
                    result['sd_read_observation'] = sd_api['observations'](serial.read_bytes(), manifest)
                except Exception as error:
                    result['sd_observation_error'] = type(error).__name__ + ': ' + str(error)
            if manifest.get('install_profile'):
                result['partition_after'] = install_api['ranges'](leased['fd'], leased['geometry'])
                result.update(official_validation_verified=False, writer_completion_verified=False,
                              upm_successor_verified=False, installation_verified=False, sdfileinput_read_verified=False,
                              original_writer_evidence='raw serial.log retained; independent main review required')
            if manifest.get('tail_profile') is not None:
                ledger = ({key: result[key] for key in ('partition_before', 'partition_after')}
                          if all(key in result for key in ('partition_before', 'partition_after')) else None)
                result['tail_observation'] = runpy.run_path(str(HERE / 'p1-rawlog-collector.py'))['collect_postrun'](
                    serial.read_bytes() if serial.exists() else b'', output / 'rawlogs',
                    tail_profile=manifest['tail_profile'], pmbp_profile=(manifest.get('pmbp') or {}).get('profile'),
                    ledger=ledger)
            result['disk_after_sha256'] = DISK['hashed'](leased['fd'])
            result['disk_unchanged'] = result['disk_after_sha256'] == result.get('disk_before_sha256')
            result['normal_exit_verified'] = (result.get('owner_returncode') == 0
                and result.get('qmp_quit') == {'return': {}} and not result['vm_signals'])
            result['verified'] = (all(result[k] for k in ('root_verified', 'kernel_release_verified', 'module_loaded',
                'p2_matches_build', 'original_init_executed', 'normal_exit_verified'))
                and (not manifest['read_only'] or (result['read_only_verified'] and result['disk_unchanged']))
                and (not manifest.get('install_profile') or (result['writable_targets_verified']
                    and result['original_resource_chain_loaded'] and result['media_backup_query']['original_readback_verified']))
                and (not manifest.get('storage_profile') or result['storage_profile_verified'])
                and not result.get('first_host_error') and not result.get('shutdown_error'))
            result['status'] = 'observed' if result['verified'] else 'failed'
            save(output / 'result.json', result)
    result['lease_released_after_owner_exit'] = True
    save(output / 'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--qemu-build', type=Path, default=DEFAULT_QEMU)
    parser.add_argument('--board-runtime', type=Path, default=HERE / 'runtime')
    parser.add_argument('--allow-updater-writes', action='store_true')
    parser.add_argument('--allow-dev-signature-bypass', action='store_true')
    parser.add_argument('--trust-profile', choices=('virtual-p1-pinned-key-v1',))
    parser.add_argument('--pinned-key', type=Path)
    parser.add_argument('--trusted-key-model', type=Path, help='JSON selection with profile/receipt/receipt_sha256')
    parser.add_argument('--media-resources', type=Path)
    parser.add_argument('--sd-read-profile', choices=('original-p1-sd-readonly-v1',))
    parser.add_argument('--install-profile', choices=('original-p1-virtual-install-v1', 'original-p1-virtual-dev-install-v1'))
    parser.add_argument('--storage-profile', choices=(UPDATE['TRIM_STORAGE_PROFILE'],))
    parser.add_argument('--actual', action='store_true')
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    output = PERSIST['fresh_output'](args.output, args.update_manifest.parent)
    manifest = build(args.update_manifest, output / 'build', read_only=not args.allow_updater_writes,
                     qemu_build=args.qemu_build, board_runtime=args.board_runtime, media_resources=args.media_resources,
                     sd_read_profile=args.sd_read_profile, install_profile=args.install_profile,
                     allow_updater_writes=args.allow_updater_writes,
                     allow_dev_signature_bypass=args.allow_dev_signature_bypass,
                     trust_profile=args.trust_profile, pinned_key=args.pinned_key, storage_profile=args.storage_profile,
                     trusted_key_model=UPDATE['checked_json'](args.trusted_key_model)[0] if args.trusted_key_model else None)
    result = actual(manifest, output / 'guest', seconds=args.seconds) if args.actual else manifest
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in ('built', 'observed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
