#!/usr/bin/env python3
"""Build/bind the small passive 2.01 USB observer without rebuilding the AP observer."""
import hashlib
import json
from pathlib import Path
import runpy
import re
import struct
import subprocess

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-functional-camera-usb-service-v1'
SEN = dict(path='/usr/kmod/usbg_sen.ko', bytes=58080,
           sha256='cd85574e2cfa8dce40d61fde0f46c892df1c39203677cea51770d1963d6fa148',
           vermagic='4.9.337-scel+ SMP preempt mod_unload aarch64')
DSOS = {
    '/usr/lib/libInfraUsbCmn.so': dict(bytes=159504, sha256='6caefd0677ee01cc6cdd54555f4422b03a86d12304c60f5372de18315bdd4396'),
    '/usr/lib/libInfraMscServer.so': dict(bytes=64456, sha256='3802b00e6cd5961e703f03c2b6f2e3f08a35323dc019921f73f29b8f9c813938'),
    '/usr/lib/appFw.so': dict(bytes=99960744, sha256='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
    '/usr/lib/libUsbControl.so': dict(bytes=135424, sha256='2baa5ad90a468751e5a7c8e7db3221ac39b53427ed4360c35dce80ec3520c39c'),
}
PRELOAD = 'export LD_PRELOAD=/simulation/menu-observe.so\n'
RESOURCE_CONTRACT = dict(version=1, records=64, line_bytes=512, copy_bytes=112,
    taps=13, passive=True, osal_imports_added=False,
    storage_module=dict(path='/usr/kmod/usbg_storage.ko', bytes=104288,
        sha256='65755c15be728daa2f6889d72a0aa0db9efadfb48361390222ba7a0e568529fa',
        vermagic='4.9.337-scel+ SMP preempt mod_unload aarch64',
        source_build='obj-m', exact_builtin_status='unknown', admission='denied'))
EE_PROFILE = 'ee-zero-publication-passive-v1'
EE_DSO = {'/usr/lib/libosal_uipc.so': dict(bytes=43752, sha256='09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3')}
EE_CONTRACT = dict(profile=EE_PROFILE, queue='0x80020002', ee_can_publish=False,
                   publication_api=False, max_seconds=120, copy_limit=12, taps=7)
NATIVE_SNAPSHOT = 'f52bcbda4c15c2b238dc7bb88199af9ef95160b7722db9e2a0e94d006c19e441'
NATIVE_SOURCE_SHA = '98a0c3a77c324adbb514da470a8fc3343bc5b6455e0efc2d20c442a0c48704b2'
NATIVE_DERIVED_SHA = 'd3ea68ba1050fd171984c2f69d43e032373487d0d18aee7e70ca52efb9307378'
NATIVE_ELF = dict(bytes=306128, sha256='9ca437bca72a2f2713aedeaf4aecaa07f1aa3efed6b05fc29934f95b0e871fda')
EE_IMPORTS = ('osal_get_msg_src', 'osal_msg_size', 'osal_free_msg')


def native_forwarder_contract(analysis):
    analysis = Path(analysis)
    path = analysis / 'root/simulation/menu-observe.so'
    source = HERE / 'runtime/native-source-snapshots' / NATIVE_SNAPSHOT / 'runtime/analysis/menu-observe.c'
    manifest = json.loads((analysis / 'full-system.json').read_text())
    observer = manifest.get('imaging_observer', {})
    touch = runpy.run_path(str(HERE / 'usb-touch-scope.py'))['validate'](observer, PROFILE)
    if touch is not None:
        derived = Path(observer.get('derived_source_path', ''))
        if not derived.is_absolute():
            derived = analysis / 'usb-touch-observer/menu-observe.c'
        expected_elf = {'path': '/simulation/menu-observe.so', 'bytes': observer.get('observer_bytes'),
                        'sha256': observer.get('observer_sha256')}
        expected = {'path': str(source.absolute()), 'bytes': source.stat().st_size, 'sha256': NATIVE_SOURCE_SHA}
        if (manifest.get('native_dependency_snapshot') != NATIVE_SNAPSHOT or
                observer.get('observer_source_selection') != 'pinned-native-dependency' or
                observer.get('observer_source_sha256') != NATIVE_SOURCE_SHA or
                observer.get('baseline_sources', {}).get('menu-observe.c') != NATIVE_SOURCE_SHA or
                digest(source) != NATIVE_SOURCE_SHA or digest(path) != expected_elf['sha256'] or
                path.stat().st_size != expected_elf['bytes'] or not derived.is_file() or
                derived.is_symlink() or observer.get('derived_source_sha256') != digest(derived)):
            raise ValueError('USB touch native observer identity differs')
        image = path.read_bytes()
        exports = _native_forwarder_exports(path, image)
        return dict(schema='a7c2.ee-native-forwarder.v1', guest_path='/simulation/menu-observe.so', **expected_elf,
                    source_path=str(source.absolute()), source_sha256=NATIVE_SOURCE_SHA,
                    snapshot=NATIVE_SNAPSHOT, derived_source_path=str(derived),
                    derived_source_sha256=digest(derived), exports=exports,
                    usb_touch=touch)
    if (path.is_symlink() or not path.is_file() or source.is_symlink() or not source.is_file() or
            path.stat().st_size != NATIVE_ELF['bytes'] or digest(path) != NATIVE_ELF['sha256'] or
            digest(source) != NATIVE_SOURCE_SHA or manifest.get('native_dependency_snapshot') != NATIVE_SNAPSHOT or
            observer.get('observer_source_selection') != 'pinned-native-dependency' or
            observer.get('observer_source_sha256') != NATIVE_SOURCE_SHA or
            observer.get('derived_source_sha256') != NATIVE_DERIVED_SHA or
            observer.get('observer_sha256') != NATIVE_ELF['sha256']):
        raise ValueError('EE native forwarder requires the reviewed ELF/source version')
    image = path.read_bytes()
    exports = _native_forwarder_exports(path, image)
    return dict(schema='a7c2.ee-native-forwarder.v1', guest_path='/simulation/menu-observe.so', **NATIVE_ELF,
                source_path=str(source.absolute()), source_sha256=NATIVE_SOURCE_SHA, snapshot=NATIVE_SNAPSHOT,
                derived_source_sha256=NATIVE_DERIVED_SHA, exports=exports)


def native_forwarder_header(contract):
    rows = ',\n'.join('{"' + pin['name'] + '",' + hex(pin['va']) + ',' + hex(pin['cached_va']) + ',{' +
                       ','.join('0x' + pin['code_hex'][i:i+2] for i in range(0, 32, 2)) + '}}' for pin in contract['exports'])
    return ('static const struct ee_native_export ee_native_exports[]={\n' + rows + '\n};\n' +
            'static const struct ee_native_contract ee_native_pins={"' + contract['guest_path'] + '",' + str(contract['bytes']) +
            ',"' + contract['sha256'] + '",sizeof ee_native_exports/sizeof *ee_native_exports,ee_native_exports};\n')


def _native_forwarder_exports(path, image):
    if image[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', image, 18)[0] != 183:
        raise ValueError('EE native forwarder requires AArch64 ELF64 LE')
    phoff = struct.unpack_from('<Q', image, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', image, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', image, phoff + i * phsize) for i in range(phnum)]
    symbols = subprocess.run(['readelf', '-Ws', str(path)], capture_output=True, text=True, check=True, timeout=10).stdout
    rows = re.findall(r'^\s*\d+:\s+([0-9a-f]+)\s+(\d+)\s+(FUNC|OBJECT)\s+(GLOBAL|LOCAL)\s+DEFAULT\s+\d+\s+(\w+)\s*$', symbols, re.M)
    exports = []
    for name in EE_IMPORTS:
        found = {(int(va, 16), int(size)) for va, size, kind, bind, symbol in rows if symbol == name and kind == 'FUNC' and bind == 'GLOBAL'}
        if not found:
            continue
        if len(found) != 1:
            raise ValueError('EE native export is ambiguous: ' + name)
        va, size = found.pop()
        cache_name = {'osal_free_msg': 'real_free_msg', 'osal_get_msg_src': 'real_get_source', 'osal_msg_size': 'real_msg_size'}[name]
        caches = {int(value, 16) for value, count, kind, bind, symbol in rows if symbol == cache_name and kind == 'OBJECT' and bind == 'LOCAL' and int(count) == 8}
        windows = [offset + va - start for kind, flags, offset, start, _, count, _, _ in segments if kind == 1 and flags & 1 and start <= va and va + 16 <= start + count]
        if len(caches) != 1 or len(windows) != 1 or size < 16:
            raise ValueError('EE native export/cache/window missing: ' + name)
        cached_va = caches.pop()
        if not any(kind == 1 and flags & 2 and start <= cached_va and cached_va + 8 <= start + memory for kind, flags, _, start, _, _, memory, _ in segments):
            raise ValueError('EE native cached original is outside writable PT_LOAD')
        exports.append(dict(name=name, va=va, file_offset=windows[0], code_hex=image[windows[0]:windows[0]+16].hex(), cached_va=cached_va))
    if [pin['name'] for pin in exports] != ['osal_free_msg']:
        raise ValueError('EE native reviewed export set drift')
    return exports


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def wrapper(text):
    if text.count(PRELOAD) != 1:
        raise ValueError('USB observer requires the reviewed bootin preload anchor')
    return text.replace(PRELOAD, PRELOAD + '''case " $(cat /proc/cmdline) " in
    *" fullsystem.usb-service=original-sen-observe-v1 "*)
        export LD_PRELOAD=$LD_PRELOAD:/simulation/usb-start-observe.so
        echo FULLSYSTEM_USB_START_OBSERVER=passive-v1;;
esac
''', 1)


def resource_observer_enabled(private_contract):
    if private_contract is None:
        return False
    value = private_contract.get('diagnostic_checkpoints', False)
    if type(value) is not bool:
        raise ValueError('USB resource diagnostics requires a typed boolean')
    return value


def prepare(analysis, *, observe_ee=False, ee_normal_cold=None):
    if observe_ee and ee_normal_cold is not None:
        raise ValueError('Choose one explicit EE observer mode')
    analysis = Path(analysis)
    native = native_forwarder_contract(analysis) if observe_ee or ee_normal_cold is not None else None
    native_header = analysis / 'usb-ee-native-pins.h'
    if native is not None:
        native_header.write_text(native_forwarder_header(native), encoding='ascii')
    target = analysis / 'root/simulation/usb-start-observe.so'
    original = HERE / 'guest/bootin-wrapper'
    copied = analysis / 'usb-start-bootin-wrapper'
    copied.write_text(wrapper(original.read_text()), encoding='ascii')
    copied.chmod(0o700)
    source = HERE / 'usb-start-observe.c'
    loader_map = HERE / 'usb-start-observe.map'
    inputs = (source, loader_map, original, HERE / 'usb-start-observe.py', HERE / 'usb-msc-sender.inc', HERE / 'usb-sender-snapshot.c')
    functional = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py')) if ee_normal_cold is not None else None
    private_contract = functional['prepare'](analysis, ee_normal_cold) if functional else None
    resource_observe = resource_observer_enabled(private_contract)
    if resource_observe:
        inputs += (HERE / 'usb-resources-observe.inc',)
    if observe_ee or functional:
        inputs += (HERE / 'usb-ee-zero-observe.inc', HERE / 'usb-ee-native-got.h', native_header,
                   analysis / 'root/simulation/menu-observe.so', Path(native['source_path']))
    if functional:
        inputs += tuple(HERE / name for name in functional['PUBLIC'])
    libraries = [analysis / 'root/lib' / name for name in ('libc-2.25.so', 'libdl-2.25.so', *(['libpthread-2.25.so'] if functional else []))]
    before = {str(p): digest(p) for p in (*inputs, *libraries)}
    command = ['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu', '-fuse-ld=lld',
               '-nostdlib', '-shared', '-fPIC', '-O2', '-fno-stack-protector', '-fno-omit-frame-pointer', '-mno-omit-leaf-frame-pointer', '-mno-outline-atomics',
               '-Wl,--no-undefined', '-Wl,-z,now', '-Wl,--version-script=' + str(loader_map), '-Wall', '-Wextra',
               *(['-DUSB_RESOURCE_OBSERVE=1'] if resource_observe else []),
               *(['-DUSB_EE_ZERO_OBSERVER=1'] if observe_ee else []),
               *(['-DUSB_EE_NATIVE_INPUT="' + str(native_header.absolute()) + '"'] if native is not None else []),
               *(['-DUSB_EE_NORMAL_COLD=1', '-D_REENTRANT', '-DUSB_EE_NORMAL_COLD_INPUT="' + private_contract['private_header'] + '"', '-I', str(HERE)] if functional else []),
               str(source), *([str(HERE / 'ee-normal-wake-cold.c'), str(HERE / 'ee-capability-input.c')] if functional else []), *map(str, libraries), '-o', str(target)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=55)
    (analysis / 'usb-start-observe-build.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('USB observer build failed: ' + result.stderr)
    if functional:
        target.chmod(0o600)
        functional['validate'](analysis, private_contract)
    snapshot = analysis / 'root/simulation/usb-sender-snapshot'
    snapshot_command = ['aarch64-linux-gnu-gcc', '-static', '-O2', '-fno-omit-frame-pointer',
                        '-Wno-unused-function', '-Wno-unused-variable', str(HERE / 'usb-sender-snapshot.c'),
                        '-ldl', '-o', str(snapshot)]
    checked = subprocess.run(snapshot_command, capture_output=True, text=True, timeout=55)
    (analysis / 'usb-sender-snapshot-build.log').write_text(checked.stdout + checked.stderr)
    if checked.returncode:
        raise RuntimeError('USB sender snapshot build failed: ' + checked.stderr)
    if {str(p): digest(p) for p in (*inputs, *libraries)} != before:
        raise ValueError('USB observer source or linked library changed during build')
    contract = dict(schema='a7c2.usb-start-observe.v1', source_sha256=before[str(source)],
                loader_map_sha256=before[str(loader_map)],
                builder_sha256=before[str(HERE / 'usb-start-observe.py')], observer_sha256=digest(target),
                wrapper_source_sha256=before[str(original)], wrapper_sha256=digest(copied),
                sender_source_sha256=before[str(HERE / 'usb-msc-sender.inc')],
                snapshot_source_sha256=before[str(HERE / 'usb-sender-snapshot.c')],
                snapshot_sha256=digest(snapshot), snapshot_command=snapshot_command,
                libraries={p.name: digest(p) for p in libraries}, command=command,
                original_elf_changed=False, original_observer_rebuilt=False, sen=SEN,
                dsos={**DSOS, **(EE_DSO if observe_ee or functional else {})})
    if resource_observe:
        contract['resource_source_sha256'] = before[str(HERE / 'usb-resources-observe.inc')]
        contract['resource_contract'] = RESOURCE_CONTRACT
    if native is not None:
        contract['native_forwarder'] = native
        contract['native_adapter_source_sha256'] = before[str(HERE / 'usb-ee-native-got.h')]
        contract['native_header_sha256'] = before[str(native_header)]
    if functional:
        contract['ee_kernel_uipc'] = private_contract['kernel_uipc']
        contract['ee_normal_cold'] = private_contract
        contract['ee_observer'] = dict(functional['CONTRACT'], source_sha256=before[str(HERE / 'usb-ee-zero-observe.inc')])
        if not functional['allocation_log_commit_proven'](contract):
            raise ValueError('EE full-write allocation source/header/DSO binding failed')
    elif observe_ee:
        contract['ee_observer'] = dict(EE_CONTRACT, source_sha256=before[str(HERE / 'usb-ee-zero-observe.inc')])
    return contract


def validate(analysis):
    analysis = Path(analysis)
    manifest = json.loads((analysis / 'full-system.json').read_text())
    contract = manifest.get('usb_start_observe', {})
    expected = {
        'sender_source_sha256': HERE / 'usb-msc-sender.inc',
        'snapshot_source_sha256': HERE / 'usb-sender-snapshot.c',
        'snapshot_sha256': analysis / 'root/simulation/usb-sender-snapshot',
        'source_sha256': HERE / 'usb-start-observe.c',
        'loader_map_sha256': HERE / 'usb-start-observe.map',
        'builder_sha256': HERE / 'usb-start-observe.py',
        'observer_sha256': analysis / 'root/simulation/usb-start-observe.so',
        'wrapper_source_sha256': HERE / 'guest/bootin-wrapper',
        'wrapper_sha256': analysis / 'usb-start-bootin-wrapper',
    }
    loader_option = '-Wl,--version-script=' + str(HERE / 'usb-start-observe.map')
    if [arg for arg in contract.get('command', []) if '--version-script' in arg] != [loader_option]:
        raise ValueError('USB observer loader version-script linkage drift')
    ee = contract.get('ee_observer')
    functional = contract.get('ee_normal_cold')
    resource_observe = resource_observer_enabled(functional)
    extra_bindings = []
    if functional is not None:
        api = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
        extra_bindings = api['validate'](analysis, functional)
        if not api['allocation_log_commit_proven'](contract):
            raise ValueError('EE full-write allocation source/header/DSO identity drift')
        if contract.get('ee_kernel_uipc') != functional['kernel_uipc']:
            raise ValueError('EE original kernel UIPC identity drift')
        define = '-DUSB_EE_NORMAL_COLD_INPUT="' + functional['private_header'] + '"'
        if contract.get('command', []).count(define) != 1 or (analysis / 'root/simulation/usb-start-observe.so').stat().st_mode & 0o077:
            raise ValueError('EE functional private header linkage/observer permissions drift')
        if ee != dict(api['CONTRACT'], source_sha256=digest(HERE / 'usb-ee-zero-observe.inc')):
            raise ValueError('EE functional observer explicit source contract drift')
    if ee is not None:
        native = native_forwarder_contract(analysis)
        native_header = analysis / 'usb-ee-native-pins.h'
        define = '-DUSB_EE_NATIVE_INPUT="' + str(native_header.absolute()) + '"'
        if (contract.get('native_forwarder') != native or contract.get('command', []).count(define) != 1 or
                native_header.read_text() != native_forwarder_header(native)):
            raise ValueError('EE native forwarder contract/header linkage drift')
        expected.update(native_adapter_source_sha256=HERE / 'usb-ee-native-got.h', native_header_sha256=native_header)
        extra_bindings += [dict(role='usb-ee-native-' + role, path=str(path.absolute()), sha256=digest(path))
                           for role, path in (('elf', analysis / 'root/simulation/menu-observe.so'), ('source', Path(native['source_path'])))]
        if functional is None and ee != dict(EE_CONTRACT, source_sha256=digest(HERE / 'usb-ee-zero-observe.inc')):
            raise ValueError('EE observer explicit profile/source contract drift')
        expected['ee_source_sha256'] = HERE / 'usb-ee-zero-observe.inc'
        contract['ee_source_sha256'] = ee['source_sha256']
    enabled = '-DUSB_EE_ZERO_OBSERVER=1' in contract.get('command', [])
    cold_enabled = '-DUSB_EE_NORMAL_COLD=1' in contract.get('command', [])
    image = (analysis / 'root/simulation/usb-start-observe.so').read_bytes()
    defines = [arg for arg in contract.get('command', []) if arg.startswith('-DUSB_RESOURCE_OBSERVE')]
    if (defines != (['-DUSB_RESOURCE_OBSERVE=1'] if resource_observe else []) or
            (b'USB_START RESOURCE_' in image) != resource_observe):
        raise ValueError('USB resource diagnostics differs from the private typed selection')
    if resource_observe:
        expected['resource_source_sha256'] = HERE / 'usb-resources-observe.inc'
        if contract.get('resource_contract') != RESOURCE_CONTRACT or b'RPC_FREE_ENTER' not in image:
            raise ValueError('USB passive tail resource bounds/module contract drift')
    elif 'resource_source_sha256' in contract or 'resource_contract' in contract or b'RPC_FREE_ENTER' in image:
        raise ValueError('USB resource source requires explicit private diagnostics')
    embedded = EE_PROFILE.encode() in image
    cold_embedded = b'ee-normal-wake-cold-functional-v1' in image
    if (enabled != (ee is not None and functional is None) or embedded != enabled or
            cold_enabled != (functional is not None) or cold_embedded != cold_enabled):
        raise ValueError('EE observer compiled mode differs from explicit manifest')
    bindings = extra_bindings
    for field, path in expected.items():
        if path.is_symlink() or not path.is_file() or digest(path) != contract.get(field):
            raise ValueError('USB start observer identity drift: ' + field)
        bindings.append(dict(role='usb-start-' + field, path=str(path.absolute()), sha256=digest(path)))
    if ((analysis / 'usb-start-bootin-wrapper').read_text() != wrapper((HERE / 'guest/bootin-wrapper').read_text())
            or contract.get('sen') != SEN or contract.get('dsos') != {**DSOS, **(EE_DSO if ee is not None else {})}):
        raise ValueError('USB observer wrapper/module contract drift')
    library_names = {'libc-2.25.so', 'libdl-2.25.so'} | ({'libpthread-2.25.so'} if functional is not None else set())
    for name, sha in contract.get('libraries', {}).items():
        if name not in library_names or digest(analysis / 'root/lib' / name) != sha:
            raise ValueError('USB observer linked library drift')
    if set(contract.get('libraries', {})) != library_names:
        raise ValueError('USB observer linked libraries missing')
    return bindings


def verify_disk(persistent, instance, *, observe_ee=False, kernel_uipc=None):
    with persistent['DISK']['lease'](instance) as leased:
        dsos = {**DSOS, **(EE_DSO if observe_ee else {})}
        wanted = {'/kmod/usbg_sen.ko': SEN,
                  **{path.removeprefix('/usr'): spec for path, spec in dsos.items()}}
        if kernel_uipc is not None:
            wanted['/kmod/osal_uipc.ko'] = kernel_uipc
        identities = persistent['ext2_identities'](persistent['part'](leased, 'nflasha15'), list(wanted))
        for name, spec in wanted.items():
            if identities.get(name, {}).get('sha256') != spec['sha256'] or identities[name]['bytes'] != spec['bytes']:
                raise ValueError('Original USB disk identity drift: ' + name)
        return identities


def build_cold(persistent, instance, analysis, output, *, module):
    validate(analysis)
    manifest = json.loads((Path(analysis) / 'full-system.json').read_text())
    identities = verify_disk(persistent, instance, observe_ee=manifest['usb_start_observe'].get('ee_observer') is not None,
                             kernel_uipc=manifest['usb_start_observe'].get('ee_kernel_uipc'))
    cold_api = persistent['build'].__globals__['COLD']
    original = cold_api['BOOTIN_WRAPPER_SOURCE']
    try:
        cold_api['BOOTIN_WRAPPER_SOURCE'] = Path(analysis) / 'usb-start-bootin-wrapper'
        result = persistent['build'](instance, analysis, output, module=module)
    finally:
        cold_api['BOOTIN_WRAPPER_SOURCE'] = original
    result['usb_start_disk_identities'] = identities
    return result
