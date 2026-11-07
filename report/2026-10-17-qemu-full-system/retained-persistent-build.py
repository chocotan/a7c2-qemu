#!/usr/bin/env python3
"""Build pinned production-derived retained QEMU variants in fresh scratch.

The default retains the historical no-USB topology. --upstream-host explicitly
admits only upstream usb_dwc3 with full platform/original software initialization.
Neither variant admits original AP restore or host USB passthrough.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import traceback

HERE = Path(__file__).resolve().parent
ORIGIN_PROFILE = 'persistent-flash-cold-v1'
PROFILE = 'persistent-flash-retained-no-usb-v1'
UPSTREAM_PROFILE = 'persistent-flash-retained-upstream-host-v1'
UPSTREAM_USB = {'QEMU_FULL_USB_CONTROLLER': 'upstream-host',
                'QEMU_FULL_USB_PLATFORM': 'full', 'QEMU_FULL_USB_INIT': 'original',
                'QEMU_SONY_USB_DWC3': '1'}
UPSTREAM_TOPOLOGY = {
    'controller': 'upstream usb_dwc3 (standard VMState; no host USB devices)',
    'environment_allowlist': UPSTREAM_USB,
    'physical_host_usb_devices': False, 'host_attach': False,
    'sony_gadget': False, 'sony_bridge': False, 'sony_usb_platform': False,
    'sony_usb_unmigratable_preserved': True,
}
PRODUCTION_SHA = '967b3be515c7ec29b11c557e2f5471a86f44937e89dd1cb4530a029eb87a7490'
SOURCE_TREE_SHA = '2d9ec4aea6f619d91fb41c2b7650e82c952a9122e303bbfd0a79fcee3b179475'
BUILD_TREE_SHA = 'd42129bdc6c8fec381daa577489b19f42e95fe2e5667f99a2358e340998a7906'
OVERLAY_SHA = '662d3e132f613c9eabc88f73635bfc718d6bffa9aa7cb7013e46da99aa78ea8e'
OLD_VIRT_SHA = '13943b9197eb232180d4a068a3351ae5b820665deb2cd5f638f19f9a9dd2e577'
INPUTS = {
    'hw/timer/sony_hwtimer.c': '050193cca7d211539430440f076d7edf15c70bb1275003369057e8d93b97c30b',
    'hw/misc/sony_spacc_stub.c': 'a99d1c98b620e401ca624504c2524688c63644f43faf7aa2e46c883aa90dbe06',
    'hw/input/sony-ui-input.c': 'd787ec495f9679b29f66678e0fd5314643f31fda19f3dd7704d46a41a474591a',
    'hw/arm/virt.c': 'a186ea5ebb76176a01fea70d90c3ca753a2f0703488c8415e6c75fbe5470bcad',
}
FLASH = {
    'flash-qemu.c': '62e2765d3996b76d2c4bc8ed9d6e421d32bce6c2635a959bd9ad9a2476b4df5f',
    'flash-core.h': '10d2bd3a0a71ac2834a46b2f0213021505e5a1c58607e97262608af2ae3c0ea8',
    'flash-core.c': 'e1439a456225412dbc78e58419ddfeb7b46959630bec543ced175d92c0a8c4bf',
}
OBJECTS = ('libsystem_arm.a.p/hw_arm_virt.c.o',
           'libsystem.a.p/hw_timer_sony_hwtimer.c.o',
           'libsystem.a.p/hw_misc_sony_spacc_stub.c.o',
           'libsystem.a.p/hw_input_sony-ui-input.c.o')
USB_PREFIXES = ('QEMU_SONY_USB', 'QEMU_SONY_DWC3')
GUARD = '''    /* First retained topology: no USB controller/provider/bridge ever exists. */
    const char *pf_retained=g_getenv("QEMU_A7PF_RETAINED_STATE");
    if (pf_retained) {
        if (strcmp(pf_retained,"1") || !pf_profile ||
            strcmp(pf_profile,"persistent-flash-retained-no-usb-v1")) {
            error_report("invalid retained-state flag/profile"); exit(1);
        }
        char **environment=g_get_environ();
        for (unsigned int i=0;environment[i];i++) {
            if (g_str_has_prefix(environment[i],"QEMU_SONY_USB") ||
                g_str_has_prefix(environment[i],"QEMU_SONY_DWC3")) {
                error_report("retained profile forbids every USB environment value");
                g_strfreev(environment); exit(1);
            }
        }
        g_strfreev(environment);
    }
'''
UPSTREAM_GUARD = '''    /* Explicit retained host-only topology; Sony gadget/provider remain absent. */
    const char *pf_retained=g_getenv("QEMU_A7PF_RETAINED_STATE");
    bool pf_upstream=pf_profile &&
        !strcmp(pf_profile,"persistent-flash-retained-upstream-host-v1");
    if (pf_retained || pf_upstream) {
        if (!pf_retained || strcmp(pf_retained,"1") || !pf_profile ||
            (!pf_upstream && strcmp(pf_profile,"persistent-flash-retained-no-usb-v1"))) {
            error_report("invalid retained-state flag/profile"); exit(1);
        }
        char **environment=g_get_environ();
        bool host_flag=false;
        for (unsigned int i=0;environment[i];i++) {
            if (g_str_has_prefix(environment[i],"QEMU_SONY_USB") ||
                g_str_has_prefix(environment[i],"QEMU_SONY_DWC3")) {
                if (pf_upstream && !strcmp(environment[i],"QEMU_SONY_USB_DWC3=1")) {
                    host_flag=true;
                } else {
                    error_report("retained profile forbids USB environment value");
                    g_strfreev(environment); exit(1);
                }
            }
        }
        g_strfreev(environment);
        const char *controller=g_getenv("QEMU_FULL_USB_CONTROLLER");
        const char *platform=g_getenv("QEMU_FULL_USB_PLATFORM");
        const char *init=g_getenv("QEMU_FULL_USB_INIT");
        if (pf_upstream && (!host_flag || !controller || strcmp(controller,"upstream-host") ||
            !platform || strcmp(platform,"full") || !init || strcmp(init,"original"))) {
            error_report("retained upstream host requires upstream-host/full/original and USB_DWC3=1"); exit(1);
        }
        if (!pf_upstream && controller && strcmp(controller,"off")) {
            error_report("retained no-USB controller must be off"); exit(1);
        }
    }
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def tree_files(root):
    result = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if '.git' in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            result[name] = 'symlink:' + os.readlink(path)
        elif path.is_file():
            result[name] = digest(path)
    return result


def tree_digest(files):
    return sha(json.dumps(files, sort_keys=True).encode())


def exact(path, expected):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Symlink pinned input: ' + str(path))
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError('Source SHA256 drift: ' + str(path))
    return data


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Source anchor drift: ' + repr(old[:100]))
    return text.replace(old, new)


def transformed(source, *, upstream_host=False):
    """Rebind ONLY this reviewed production virt SHA in a local runpy namespace."""
    if type(upstream_host) is not bool:
        raise ValueError('upstream_host must be bool')
    exact(HERE / 'device-snapshot-state.py', OVERLAY_SHA)
    overlay = runpy.run_path(str(HERE / 'device-snapshot-state.py'))
    historical = dict(INPUTS, **{'hw/arm/virt.c': OLD_VIRT_SHA})
    if overlay['INPUTS'] != historical:
        raise ValueError('Unexpected historical overlay inputs')
    overlay['INPUTS']['hw/arm/virt.c'] = INPUTS['hw/arm/virt.c']
    originals = {name: exact(source / name, expected) for name, expected in INPUTS.items()}
    patched = {name: overlay['transform'](name, data) for name, data in originals.items()}
    text = patched['hw/arm/virt.c'].decode()
    text = replace(text, '    /* Explicit persistent profile; launcher whitelists only these four values. */',
                   '    /* Production-derived cold profile plus explicit retained/no-USB profile. */')
    text = replace(text, '    const char *pf_profile=g_getenv("QEMU_A7PF_PROFILE");\n',
                   '    const char *pf_profile=g_getenv("QEMU_A7PF_PROFILE");\n' + GUARD)
    text = replace(text, '    bool pf_any=pf_profile!=NULL;',
                   '    bool pf_any=pf_profile!=NULL || pf_retained!=NULL;')
    text = replace(text, '        if (!pf_profile || strcmp(pf_profile,"persistent-flash-cold-v1")) {',
                   '        if (!pf_profile || (strcmp(pf_profile,"persistent-flash-cold-v1") &&\n'
                   '            !(pf_retained && !strcmp(pf_profile,"persistent-flash-retained-no-usb-v1")))) {')
    text = replace(text, '        qdev_prop_set_int32(pf,"backend-fd",pf_values[0]);',
                   '        if (pf_retained) {\n'
                   '            qdev_prop_set_bit(pf,"retained-state",true);\n'
                   '        } else {\n'
                   '            qdev_prop_set_bit(pf,"retained-state",false);\n'
                   '        }\n'
                   '        qdev_prop_set_int32(pf,"backend-fd",pf_values[0]);')
    if upstream_host:
        text = replace(text, GUARD, UPSTREAM_GUARD)
        text = replace(text,
            '            !(pf_retained && !strcmp(pf_profile,"persistent-flash-retained-no-usb-v1")))) {',
            '            !(pf_retained && (!strcmp(pf_profile,"persistent-flash-retained-no-usb-v1") ||\n'
            '                              !strcmp(pf_profile,"persistent-flash-retained-upstream-host-v1"))))) {')
    patched['hw/arm/virt.c'] = text.encode()
    for name, expected in FLASH.items():
        target = 'hw/block/a7c2-persistent/' + name
        originals[target] = (source / target).read_bytes()
        patched[target] = exact(HERE / 'persistent-flash' / name, expected)
    return originals, patched


def validate_environment(env):
    """Fail closed even for empty/zero USB flags; allow one exact explicit host profile."""
    profile = env.get('QEMU_A7PF_PROFILE')
    upstream = profile == UPSTREAM_PROFILE
    for key in env:
        if key.startswith(USB_PREFIXES) and not (upstream and key == 'QEMU_SONY_USB_DWC3' and env[key] == '1'):
            raise ValueError('Retained launcher forbids every USB environment value except explicit upstream USB_DWC3=1')
    if upstream:
        if any(env.get(key) != value for key, value in UPSTREAM_USB.items()):
            raise ValueError('Retained upstream host requires upstream-host/full/original and USB_DWC3=1')
    elif env.get('QEMU_FULL_USB_CONTROLLER', 'off') != 'off':
        raise ValueError('Final merged USB controller must be off')
    flag = env.get('QEMU_A7PF_RETAINED_STATE')
    if flag is not None and (flag != '1' or profile not in (PROFILE, UPSTREAM_PROFILE)):
        raise ValueError('Invalid retained-state flag/profile')
    if profile in (PROFILE, UPSTREAM_PROFILE) and flag != '1':
        raise ValueError('Retained profile requires explicit flag 1')
    if profile is not None and profile not in (ORIGIN_PROFILE, PROFILE, UPSTREAM_PROFILE):
        raise ValueError('Unknown persistent profile')
    keys = ('QEMU_A7PF_FD', 'QEMU_A7PF_DEV', 'QEMU_A7PF_INO')
    if profile is not None or any(key in env for key in keys):
        if profile is None:
            raise ValueError('Missing persistent profile')
        for key in keys:
            value = env.get(key, '')
            if not re.fullmatch('[0-9]+', value) or not 0 < int(value) < 2**64:
                raise ValueError('Invalid inherited FD identity: ' + key)
        if not 3 <= int(env[keys[0]]) <= 2**31 - 1:
            raise ValueError('Inherited FD must be >=3 and fit int32')
    unknown = {k for k in env if k.startswith('QEMU_A7PF_')} - set(keys) - {
        'QEMU_A7PF_PROFILE', 'QEMU_A7PF_RETAINED_STATE'}
    if unknown:
        raise ValueError('Unknown persistent environment: ' + ','.join(sorted(unknown)))


def profile_environment(fd, *, retained=False, inherited=None, upstream_host=False):
    """Small synthetic launcher environment; AP integration must bind its own assets."""
    if type(retained) is not bool or type(upstream_host) is not bool or (upstream_host and not retained):
        raise ValueError('retained/upstream_host must be bool; upstream host requires retained')
    inherited = dict(os.environ if inherited is None else inherited)
    validate_environment(inherited)
    if any(k.startswith('QEMU_A7PF_') for k in inherited):
        raise ValueError('Inherited persistent binding must not be overwritten')
    st = os.fstat(fd)
    env = {'PATH': os.defpath, 'LC_ALL': 'C', 'QEMU_FULL_USB_CONTROLLER': 'off', 'QEMU_SONY_TIMERS': '1',
           'QEMU_SONY_MEDIA_DETECT': '0x12345678', 'QEMU_SONY_MMC_TRACE': '0x89abcdef',
           'QEMU_A7PF_PROFILE': PROFILE if retained else ORIGIN_PROFILE,
           'QEMU_A7PF_FD': str(fd), 'QEMU_A7PF_DEV': str(st.st_dev), 'QEMU_A7PF_INO': str(st.st_ino)}
    if retained:
        env['QEMU_A7PF_RETAINED_STATE'] = '1'
    if upstream_host:
        env.update(UPSTREAM_USB, QEMU_A7PF_PROFILE=UPSTREAM_PROFILE)
    validate_environment(env)
    return env


def block(text, target):
    lines = text.splitlines(True)
    hits = [i for i, line in enumerate(lines) if line.startswith('build ' + target + ':')]
    if len(hits) != 1:
        raise ValueError('Unknown frozen build target: ' + target)
    begin = hits[0]
    end = begin + 1
    while end < len(lines) and (lines[end].startswith(' ') or not lines[end].strip()):
        end += 1
    return ''.join(lines[begin:end])


def frozen_ninja(template, stage):
    upstream = (template / 'build/build.ninja').read_text()
    production = (template / 'build/flash.ninja').read_text()
    header = production[:production.index('\nbuild ')]
    blocks = [block(production if i == 0 else upstream, name) for i, name in enumerate(OBJECTS)]
    # Compile changed units with the production flags plus fatal warnings.
    blocks = [replace(text, ' ARGS = ', ' ARGS = -Werror ') for text in blocks]
    link = block(production, 'qemu-system-aarch64')
    for obj in OBJECTS + ('libsystem.a.p/hw_usb_sony-dwc3.c.o',
                          'libsystem.a.p/hw_usb_sony-dwc3-bridge.c.o'):
        if obj not in link:
            raise ValueError('Production linker dropped required object: ' + obj)
    text = header + '\n' + '\n'.join(blocks) + '\n' + link
    text = text.replace(str(template), str(stage))
    for old in set(re.findall(r'/[^\s\'\"]+/qemu-11\.1\.2(?=/|\s|$)', text)):
        text = text.replace(old, str(stage / 'qemu-11.1.2'))
    return text


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def build(template, stage, *, upstream_host=False):
    if type(upstream_host) is not bool:
        raise ValueError('upstream_host must be bool')
    template, stage = Path(template).absolute(), Path(stage).absolute()
    if any(p.is_symlink() for p in (template, *template.parents, stage, *stage.parents)):
        raise ValueError('Symlink source/output forbidden')
    template, stage = template.resolve(), stage.resolve()
    if (stage == Path('/') or stage.is_relative_to(HERE.parents[1]) or
            stage.is_relative_to(template) or template.is_relative_to(stage)):
        raise ValueError('Separate scratch source/build required')
    if stage.exists():
        raise ValueError('Fresh stage required; failures are retained')
    before = {n: tree_files(template / n) for n in ('qemu-11.1.2', 'build')}
    for name, expected in (('qemu-11.1.2', SOURCE_TREE_SHA), ('build', BUILD_TREE_SHA)):
        if tree_digest(before[name]) != expected:
            raise ValueError('Unknown production tree: ' + name)
    exact(template / 'build/qemu-system-aarch64', PRODUCTION_SHA)
    origin = json.loads((template / 'qemu-result.json').read_text())
    delta = json.loads((template / 'persistent-usb-source-delta.json').read_text())
    if (origin['qemu_binary_sha256'] != PRODUCTION_SHA or
            origin['board_source_sha256'] != INPUTS['hw/arm/virt.c'] or
            delta['files']['hw/arm/virt.c']['after'] != INPUTS['hw/arm/virt.c'] or
            origin['source_tree_sha256_after'] != SOURCE_TREE_SHA or
            delta['source_tree_sha256_after'] != SOURCE_TREE_SHA or
            digest(template / 'persistent-usb-source-delta.json') != origin['all_source_delta_sha256']):
        raise ValueError('Production receipt/source-delta identity mismatch')
    originals, patched = transformed(template / 'qemu-11.1.2', upstream_host=upstream_host)
    ninja = frozen_ninja(template, stage)
    stage.mkdir(parents=True, mode=0o700)
    result = dict(schema='a7c2.retained-persistent-build.v1', profile=UPSTREAM_PROFILE if upstream_host else PROFILE,
                  status='started', compiled=False, production_sha256=PRODUCTION_SHA,
                  origin_profile=dict(name='production-967b3be5-persistent-flash-cold-v1',
                      board=ORIGIN_PROFILE, kernel_profile='functional-cold-v4',
                      kernel_assets_bound=False, kernel_or_ap_executed=False),
                  original_tree_sha256={n: tree_digest(v) for n, v in before.items()},
                  overlay_sha256=OVERLAY_SHA, overlay_original_inputs=dict(INPUTS, **{'hw/arm/virt.c': OLD_VIRT_SHA}),
                  overlay_reviewed_inputs=INPUTS, flash_bundle_sha256=FLASH,
                  source_receipts_sha256={n: digest(template / n) for n in
                      ('qemu-result.json', 'persistent-usb-source-delta.json')},
                  files={n: dict(original=sha(originals[n]), new=sha(data)) for n, data in patched.items()},
                  builder_sha256=digest(Path(__file__)), usb_instantiated_allowed=False,
                  usb_state_saved_or_restored=False, usb_function_available=False,
                  external_host_transaction_implemented=False, external_disk_generation_implemented=False,
                  actual_combined_roundtrip_verified=False, original_ap_restore_verified=False,
                  sony_wbi_verified=False, hardware_ram_hotboot_verified=False,
                  full_device_audit_complete=False, production_ready=False, ui_hot_enabled=False,
                  future_camera_launcher_admission=[
                      'After ALL camera environment merges explicitly force QEMU_FULL_USB_CONTROLLER=off',
                      'Validate final child environment has NO QEMU_SONY_USB* or QEMU_SONY_DWC3* keys, even empty/0',
                      'Validate final QEMU argv has no USB controller/device/backend/passthrough arguments',
                      'Require final QOM and memory-tree have no Sony/legacy USB qdev or shared provider',
                      'This topology has never instantiated USB or connected an external USB peer',
                      'No AP restore until remaining provider audit and external lease/generation transaction pass'],
                  device_migration=dict(complete=False, blockers=[
                      'Original AP/kernel and complete functional-camera topology not audited',
                      'External disk generation/lease snapshot transaction not implemented',
                      'Guest/host OSAL, sound, pin, input and display owners require separate audit',
                      'Any instantiated Sony USB remains unmigratable']),
                  topology_scope=dict(
                      qemu_devices=['upstream virt', '4 sony-hwtimer', 'sony-spacc-stub',
                                    'sony-cxd-bus-stub', 'sony-persistent-flash',
                                    'ramfb + disconnected sony-ui-input (synthetic test only)'],
                      non_qom_mutable=['SonyMediaDetectState value/reads/writes: explicit VMState',
                                       '3 SonyMmcTraceState reads/writes/reset/base: explicit VMState'],
                      usb_shared_provider='SonyUsbPlatform (C1/GPIO/clock/reset/PHY/CR) allocated only inside USB-device env branch; absent',
                      shared_provider_dependency='Non-USB QEMU timer/SPAcc/MMC/media/flash do not reference SonyUsbPlatform',
                      catch_all='sony-cxd-bus-stub reads constant all-ones and drops writes; no stored register state; not physical hardware',
                      osal_functional_sound_pin='No such QEMU provider in pinned hw/system source; guest/DSO RAM and external resources not audited here',
                      kernel_profile='functional-cold-v4 origin label only; no kernel asset bound or run'))
    if upstream_host:
        result.update(usb_instantiated_allowed=True, declared_topology=UPSTREAM_TOPOLOGY,
                      upstream_usb_actual_roundtrip_verified=False,
                      physical_host_usb_devices=False, host_attach_verified=False,
                      guest_gadget_verified=False)
        result['topology_scope']['qemu_devices'].append('upstream usb_dwc3 + embedded xhci (no attached devices)')
        result['future_camera_launcher_admission'] = [
            'After all merges require the exact upstream-host/full/original + USB_DWC3=1 allowlist',
            'Reject all other Sony USB/DWC3 environment keys even empty/0',
            'No host USB devices, backend, bridge or passthrough argv',
            'Require upstream usb_dwc3; no Sony gadget or SonyUsbPlatform',
            'No AP restore before remaining audit and external lease/generation transaction']
    frozen_builder = stage / 'builder-at-compile.py'
    frozen_builder.write_bytes(Path(__file__).read_bytes())
    result['builder_at_compile_path'] = str(frozen_builder)
    result['builder_at_handoff_sha256'] = result['builder_sha256']
    save_json(stage / 'manifest.json', result)
    save_json(stage / 'source-before.json', before['qemu-11.1.2'])
    try:
        for name in before:
            subprocess.run(['cp', '-a', '--reflink=auto', str(template / name), str(stage / name)], check=True)
            if tree_files(stage / name) != before[name]:
                raise ValueError('Clone identity drift: ' + name)
        patch = []
        for name, data in patched.items():
            path = stage / 'qemu-11.1.2' / name
            if path.is_symlink() or path.stat().st_nlink != 1:
                raise ValueError('Aliased patch destination: ' + name)
            path.write_bytes(data)
            patch.extend(difflib.unified_diff(originals[name].decode().splitlines(True), data.decode().splitlines(True),
                                            fromfile='a/' + name, tofile='b/' + name))
        (stage / 'combined-source.patch').write_text(''.join(patch))
        after = tree_files(stage / 'qemu-11.1.2')
        expected = dict(before['qemu-11.1.2'], **{n: sha(d) for n, d in patched.items()})
        if after != expected:
            raise ValueError('Unexpected combined source changes')
        save_json(stage / 'source-after.json', after)
        result['source_tree_sha256'] = tree_digest(after)
        result['source_inventory_sha256'] = {n: digest(stage / n) for n in ('source-before.json', 'source-after.json')}
        frozen = stage / 'build/retained-persistent.ninja'
        frozen.write_text(ninja)
        result['frozen_ninja_sha256'] = digest(frozen)
        for name in (*OBJECTS, 'qemu-system-aarch64'):
            (stage / 'build' / name).unlink()
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
                   '--dev-bind', '/dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp',
                   '--bind', str(stage), str(stage), '--chdir', str(stage / 'build'),
                   'ninja', '-f', frozen.name, '-j2', 'qemu-system-aarch64']
        result['compile_command'] = command
        with (stage / 'compile.log').open('xb') as log:
            compiled = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        result['compile_returncode'] = compiled.returncode
        if compiled.returncode:
            raise RuntimeError('Combined QEMU compilation failed; see compile.log')
        binary = stage / 'build/qemu-system-aarch64'
        result.update(status='compiled', compiled=True, binary=str(binary), qemu_binary_sha256=digest(binary),
                      object_sha256={name: digest(stage / 'build' / name) for name in OBJECTS})
    except BaseException as error:
        result.update(status='failed', error=str(error))
        raise
    finally:
        result['original_source_and_build_unchanged'] = all(tree_files(template / n) == v for n, v in before.items())
        result['original_tree_sha256_after'] = {n: tree_digest(tree_files(template / n)) for n in before}
        if not result['original_source_and_build_unchanged']:
            result.update(status='failed', compiled=False, error='Production source/build changed')
        save_json(stage / 'manifest.json', result)
    if result['status'] != 'compiled':
        raise RuntimeError(result['error'])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True, help='pinned production directory containing source and build')
    parser.add_argument('--stage', type=Path, required=True, help='new independent scratch directory')
    parser.add_argument('--upstream-host', action='store_true', help='explicit upstream-host-only retained candidate')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.template, args.stage, upstream_host=args.upstream_host), indent=2))
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
