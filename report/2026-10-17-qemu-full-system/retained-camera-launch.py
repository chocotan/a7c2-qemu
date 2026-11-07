#!/usr/bin/env python3
"""Prepare the production-derived original-AP retained diagnostic candidate only.

    launch = prepare_launch(runtime_analysis, cold_manifest_path, fresh_output,
                            combo_manifest=combo_manifest_path,
                            origin_qemu_build=production_967b_build)
    target = prepare_launch(runtime_analysis, cold_manifest_path, fresh_target,
                            incoming=True, source_launch=fresh_output/'launch.json')

No build(), VM runner, RAM save/restore or UI registration is provided. Reuse an
independently prepared cold manifest; this code never installs a disk adapter or
regenerates RAM0/proof payloads. The old production receipt is origin proof, not
an assertion that the new binary is production ready. Source diagnostics can use
persistent-boot.leased_launch after the caller's audit. Incoming preparation is
blocked from execution and deliberately has no current disk firmware contract:
retained-disk-state must supply the real snapshot/lease/generation transaction.
The source's cold partition hashes are provenance, never restored target state.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
PERSISTENT = runpy.run_path(str(HERE/'persistent-boot.py'))
COLD = PERSISTENT['COLD']
COMBO = runpy.run_path(str(HERE/'retained-persistent-build.py'))
PROJECT = HERE.parents[1]
PROFILE = 'persistent-flash-retained-no-usb-v1'
UPSTREAM_PROFILE = COMBO['UPSTREAM_PROFILE']
UPSTREAM_USB = COMBO['UPSTREAM_USB']
UPSTREAM_COMBO = PROJECT/'analysis/scratch/a7c2-retained-upstream-host-20261106/combined/manifest.json'
SCHEMA = 'a7c2.retained-camera-launch.v1'
SCRATCH = PROJECT/'analysis/scratch/a7c2-retained-camera-launch-20261106'
DEFAULT_COMBO = PROJECT/'analysis/scratch/a7c2-retained-persistent-build-20261106/combined/manifest.json'
DEFAULT_ORIGIN = PROJECT/'analysis/scratch/a7c2-persistent-usb-gpio-20261106/production/build'
BINARY_SHA = 'a8fca8398684237f50ad206cb77235a48eb3e14214f3bb444f3691fedac102a5'
SOURCE_SHA = '0d2906d1655aedd1a07c861d4553e01d37de55dd2a859ebb10e1fdb3e18db9eb'
UPSTREAM_BINARY_SHA = 'b4c697056f316de7a1d313df0e5fff7bc027f7164e5291561b79e505a61708f4'
UPSTREAM_SOURCE_SHA = 'e5e664b1727a2cc5fe898fefa438f356a513a1677f70842aafe0a4ad565c0d95'
LEGACY_BUILDER_SHA = 'f962342671738e497b28fac7c9cd9f8f2749ccd05a83487000cb29fc53955e72'
LEGACY_TEST_SHA = '2f6e279788b7a5bc605078f1e358320f69b5ae36aa593689b3d1514fa306896f'
RECEIPTS = {
    'qemu-result.json': 'aa84e8ce7d78e6e46c2268d202e70a97599299e76c3da74d9d2adcf30352077e',
    'persistent-usb-source-delta.json': '5516ede7c58d254244858d6e3cba1030cac008462e2dbf8d182e619e03c7b184',
}
USB_PREFIXES = ('QEMU_SONY_USB', 'QEMU_SONY_DWC3')
USB_OFF = {'QEMU_FULL_USB_CONTROLLER': 'off', 'QEMU_FULL_USB_PLATFORM': 'off',
           'QEMU_FULL_USB_INIT': 'original'}
PROFILE_ANCHOR = '''    --setenv QEMU_A7PF_PROFILE persistent-flash-cold-v1 \\
    --setenv QEMU_A7PF_FD "$PERSISTENT_DISK_FD" \\
    --setenv QEMU_A7PF_DEV "$PERSISTENT_DISK_DEV" \\
    --setenv QEMU_A7PF_INO "$PERSISTENT_DISK_INO" \\
'''
USB_ANCHOR = '''if [[ "${QEMU_FULL_USB_CONTROLLER:-off}" == upstream-host ]]; then
  timer_environment+=(--setenv QEMU_SONY_USB_DWC3 1)
fi
'''
ARGV_ANCHOR = '"${fatal_debug_args[@]}" "${loader_args[@]}" -kernel /kernel.img'
GUARD = '''# RETAINED_CAMERA_DIAGNOSTIC: no USB instance, no implicit restore admission.
for retained_key in "${!QEMU_SONY_USB@}" "${!QEMU_SONY_DWC3@}"; do
  [[ -z "$retained_key" ]] || { echo 'Retained profile forbids every USB environment value' >&2; exit 2; }
done
[[ "${QEMU_A7PF_PROFILE:-}" == persistent-flash-retained-no-usb-v1 && "${QEMU_A7PF_RETAINED_STATE:-}" == 1 && "${QEMU_FULL_USB_CONTROLLER:-}" == off && "${QEMU_FULL_USB_PLATFORM:-}" == off && "${QEMU_FULL_USB_INIT:-}" == original ]] || { echo 'Invalid retained diagnostic environment' >&2; exit 2; }
retained_incoming_args=()
case "${QEMU_RETAINED_INCOMING-}" in
  0) ;;
  1) retained_incoming_args=(-S -incoming defer);;
  *) echo 'QEMU_RETAINED_INCOMING must be explicitly 0 or 1' >&2; exit 2;;
esac
if [[ "$QEMU_RETAINED_INCOMING" == 1 && "${QEMU_PREPARE_ONLY:-0}" != 1 ]]; then
  echo 'Incoming execution requires the external snapshot/lease transaction; preparation only' >&2; exit 2
fi
'''
UPSTREAM_GUARD = GUARD.replace('no USB instance', 'upstream host-only USB').replace(
    '  [[ -z "$retained_key" ]] ||',
    '  [[ -z "$retained_key" || ( "$retained_key" == QEMU_SONY_USB_DWC3 && "${!retained_key}" == 1 ) ]] ||').replace(
    PROFILE, UPSTREAM_PROFILE).replace(
    '"${QEMU_FULL_USB_CONTROLLER:-}" == off && "${QEMU_FULL_USB_PLATFORM:-}" == off',
    '"${QEMU_FULL_USB_CONTROLLER:-}" == upstream-host && "${QEMU_FULL_USB_PLATFORM:-}" == full').replace(
    'retained_incoming_args=()',
    '[[ "${QEMU_SONY_USB_DWC3:-}" == 1 ]] || { echo "Missing upstream host flag" >&2; exit 2; }\nretained_incoming_args=()')


def equal(label, expected, actual):
    if type(expected) is bool and actual is not expected:
        raise ValueError(label+' must be '+str(expected))
    PERSISTENT['identical'](label, expected, actual)


def reject_usb(env):
    if any(key.startswith(USB_PREFIXES) for key in env):
        raise ValueError('Retained launcher forbids every USB environment value')


def verify_combo(manifest_path=None, *, origin_qemu_build=DEFAULT_ORIGIN, upstream_host=False):
    """Read-only fixed-variant verification, including every source inventory entry."""
    if type(upstream_host) is not bool:
        raise ValueError('upstream_host must be bool')
    profile = UPSTREAM_PROFILE if upstream_host else PROFILE
    manifest_path = (UPSTREAM_COMBO if upstream_host else DEFAULT_COMBO) if manifest_path is None else manifest_path
    binary_sha = UPSTREAM_BINARY_SHA if upstream_host else BINARY_SHA
    source_sha = UPSTREAM_SOURCE_SHA if upstream_host else SOURCE_SHA
    rows = []

    def bound(path, role, expected=None):
        row = COLD['binding'](path, role)
        if expected is not None:
            equal(role+' SHA256', expected, row['sha256'])
        rows.append(row)
        return row

    path = COLD['plain'](manifest_path)
    bound(path, 'retained-combo-manifest')
    m = json.loads(path.read_text())
    for name, expected in {'schema': 'a7c2.retained-persistent-build.v1', 'profile': profile,
                           'status': 'compiled', 'compiled': True, 'compile_returncode': 0,
                           'production_sha256': COMBO['PRODUCTION_SHA'],
                           'original_source_and_build_unchanged': True,
                           'actual_combined_roundtrip_verified': True,
                           'qemu_binary_sha256': binary_sha, 'source_tree_sha256': source_sha}.items():
        equal('combo '+name, expected, m.get(name))
    for name in ('production_ready', 'full_device_audit_complete', 'original_ap_restore_verified',
                 'sony_wbi_verified', 'hardware_ram_hotboot_verified', 'ui_hot_enabled',
                 'usb_function_available', 'usb_state_saved_or_restored'):
        if m.get(name) is not False:
            raise ValueError('Diagnostic-only combo capability changed: '+name)
    equal('declared USB instantiation', upstream_host, m.get('usb_instantiated_allowed'))
    if upstream_host:
        equal('declared upstream topology', COMBO['UPSTREAM_TOPOLOGY'], m.get('declared_topology'))
        equal('actual upstream registers roundtrip', True, m.get('upstream_usb_actual_roundtrip_verified'))
        for name in ('physical_host_usb_devices', 'host_attach_verified', 'guest_gadget_verified'):
            equal(name, False, m.get(name))
    equal('incomplete combo device audit', False, m.get('device_migration', {}).get('complete'))
    root = path.parent
    binary = root/'build/qemu-system-aarch64'
    equal('combo binary path', str(binary), m.get('binary'))
    bound(binary, 'retained-qemu-binary', binary_sha)
    before, after = [], []
    for name, target in (('source-before.json', before), ('source-after.json', after)):
        bound(root/name, 'retained-source-inventory', m['source_inventory_sha256'][name])
        target.append(json.loads((root/name).read_text()))
    before, after = before[0], after[0]
    equal('origin source inventory', COMBO['SOURCE_TREE_SHA'], COMBO['tree_digest'](before))
    equal('combo complete source inventory', source_sha, COMBO['tree_digest'](after))
    names = set(COMBO['INPUTS']) | {'hw/block/a7c2-persistent/'+n for n in COMBO['FLASH']}
    equal('combo seven source files', sorted(names), sorted(m['files']))
    expected = dict(before)
    for name in names:
        equal('combo source delta '+name, {'original': before[name], 'new': after[name]}, m['files'][name])
        expected[name] = after[name]
        bound(root/'qemu-11.1.2'/name, 'retained-device-source', after[name])
    if expected != after:
        raise ValueError('Changes outside the seven reviewed source files')
    if after != COMBO['tree_files'](root/'qemu-11.1.2'):
        raise ValueError('Live complete source inventory differs')
    equal('origin receipts', RECEIPTS, m['source_receipts_sha256'])
    origin_build = COLD['plain'](origin_qemu_build, directory=True)
    for name, sha in RECEIPTS.items():
        bound(origin_build.parent/name, 'production-origin-receipt', sha)
    bound(origin_build/'qemu-system-aarch64', 'production-origin-binary', COMBO['PRODUCTION_SHA'])
    origin = json.loads((origin_build.parent/'qemu-result.json').read_text())
    equal('origin profile', PERSISTENT['PROFILE'], origin.get('board_profile'))
    equal('origin binary', COMBO['PRODUCTION_SHA'], origin.get('qemu_binary_sha256'))
    equal('origin source tree', COMBO['SOURCE_TREE_SHA'], origin.get('source_tree_sha256_after'))
    bound(m['builder_at_compile_path'], 'retained-builder-at-compile', m['builder_sha256'])
    if upstream_host:
        bound(HERE/'retained-persistent-build.py', 'retained-builder-at-handoff', m['builder_at_handoff_sha256'])
    else:
        equal('legacy builder at handoff identity', LEGACY_BUILDER_SHA, m['builder_at_handoff_sha256'])
        bound(HERE/'retained-persistent-build.py', 'retained-current-builder')
    bound(root/'build/retained-persistent.ninja', 'retained-frozen-ninja', m['frozen_ninja_sha256'])
    actual = m['actual_evidence']
    bound(actual['result'], 'retained-synthetic-qtest-result', actual['sha256'])
    if upstream_host:
        bound(HERE/'test-retained-persistent-build.py', 'retained-synthetic-qtest-source', actual['test_sha256'])
    else:
        equal('legacy qtest source identity', LEGACY_TEST_SHA, actual['test_sha256'])
    result = json.loads(Path(actual['result']).read_text())
    for name, expected in {'profile': profile, 'qemu_binary_sha256': binary_sha,
                           'actual_combined_roundtrip_verified': True, 'synthetic_disk': True,
                           'dma_ram_and_canary_exact': True, 'timer_count_compare_control_exact': True,
                           'input_held_release_consumed': True, 'usb_qdev_absent': not upstream_host,
                           'full_spacc_bytes': 262144, 'original_ap_restore_verified': False,
                           'usb_fields_saved_or_restored': False}.items():
        equal('synthetic qtest '+name, expected, result.get(name))
    if upstream_host:
        equal('upstream USB roundtrip result', True, result.get('upstream_usb_registers_exact'))
        equal('Sony gadget/provider absent', True, result.get('sony_usb_qdev_and_provider_absent'))
    COLD['recheck'](rows)
    return dict(manifest=str(path), binary=str(binary), qemu_sha256=binary_sha,
                profile=profile, declared_topology=m.get('declared_topology', {'usb': 'absent'}),
                source_tree_sha256=source_sha, inputs=rows)


def launch_script(text, *, upstream_host=False):
    """Derive ONLY an already prepared production script, with unique anchors."""
    profile = UPSTREAM_PROFILE if upstream_host else PROFILE
    guard = UPSTREAM_GUARD if upstream_host else GUARD
    if 'RETAINED_CAMERA_DIAGNOSTIC' in text:
        raise ValueError('Already derived retained script')
    for old, new in (
        (PROFILE_ANCHOR, PROFILE_ANCHOR.replace(PERSISTENT['PROFILE'], profile).replace(
            '    --setenv QEMU_A7PF_FD', '    --setenv QEMU_A7PF_RETAINED_STATE 1 \\\n    --setenv QEMU_A7PF_FD')),
        (USB_ANCHOR, USB_ANCHOR if upstream_host else '# Retained diagnostic: no USB controller environment enters bwrap.\n'),
        (ARGV_ANCHOR, '"${retained_incoming_args[@]}" '+ARGV_ANCHOR),
        ('set -euo pipefail\n', 'set -euo pipefail\n'+guard),
    ):
        if text.count(old) != 1:
            raise ValueError('Retained script anchor must occur once: '+old[:100])
        text = text.replace(old, new, 1)
    if upstream_host:
        retained_binding = '    --setenv QEMU_A7PF_RETAINED_STATE 1 \\\n'
        text = text.replace(retained_binding, retained_binding+
            '    --setenv QEMU_FULL_USB_CONTROLLER upstream-host \\\n'
            '    --setenv QEMU_FULL_USB_PLATFORM full \\\n'
            '    --setenv QEMU_FULL_USB_INIT original \\\n', 1)
    rest = text.replace(guard, '').replace(USB_ANCHOR, '') if upstream_host else text.replace(guard, '')
    if any(prefix in rest for prefix in USB_PREFIXES):
        raise ValueError('Unexpected remaining USB environment injection')
    return text


def verify_dtb(path, library, cmdline, *, upstream_host=False):
    """Check bootargs and the exact baseline full USB resource declarations."""
    fdt = ctypes.CDLL(str(library))
    raw = ctypes.create_string_buffer(Path(path).read_bytes())
    if fdt.fdt_check_header(raw):
        raise ValueError('Invalid retained DTB')
    fdt.fdt_get_name.restype = ctypes.c_char_p
    fdt.fdt_getprop.restype = ctypes.c_void_p
    chosen = fdt.fdt_path_offset(raw, b'/chosen')
    count = ctypes.c_int()
    ptr = fdt.fdt_getprop(raw, chosen, b'bootargs', ctypes.byref(count))
    equal('retained DTB bootargs', (cmdline.encode()+b'\0').hex(),
          ctypes.string_at(ptr, count.value).hex() if ptr and count.value > 0 else None)
    expected_usb = {b'fusb_dwc3regs@f10c0000': {
        b'compatible': b'snps,fusb_dwc3regs\0',
        b'reg': (0xf10c0000).to_bytes(8, 'big')+(0x11000).to_bytes(8, 'big'), b'status': b'okay\0'},
        b'fusb_otg': {b'compatible': b'linux,extcon-fusb_otg\0', b'status': b'okay\0'}} if upstream_host else {}
    seen = set()
    node = fdt.fdt_next_node(raw, -1, None)
    while node >= 0:
        name = fdt.fdt_get_name(raw, node, None) or b''
        ptr = fdt.fdt_getprop(raw, node, b'compatible', ctypes.byref(count))
        compatible = ctypes.string_at(ptr, count.value) if ptr and count.value > 0 else b''
        if any(word in (name+b' '+compatible).lower() for word in (b'usb', b'dwc3', b'xhci', b'ehci', b'ohci')):
            if name not in expected_usb or name in seen or fdt.fdt_path_offset(raw, b'/'+name) != node:
                raise ValueError('USB node in retained DTB: '+repr(name))
            seen.add(name)
            for key, expected in expected_usb[name].items():
                ptr = fdt.fdt_getprop(raw, node, key, ctypes.byref(count))
                actual = ctypes.string_at(ptr, count.value) if ptr and count.value > 0 else None
                equal('retained USB resource '+repr(key), expected, actual)
        node = fdt.fdt_next_node(raw, node, None)
    equal('retained USB resource nodes', sorted(expected_usb), sorted(seen))


def source_inputs(launch):
    """Stable guest inputs; output paths and incoming mode are per-run only."""
    return dict(profile=launch['profile'], qemu_sha256=launch['qemu_sha256'],
                source_tree_sha256=launch['combo_binding']['source_tree_sha256'],
                topology=launch['combo_binding']['declared_topology'],
                cold_manifest=launch['cold_manifest_binding'], ram0=launch['ram0_sha256'],
                kernel=launch['source_firmware_contract']['actual_kernel']['sha256'], dtb=launch['dtb_sha256'],
                cmdline=launch['cmdline'], extra_env=launch['extra_env'],
                environment={k: v for k, v in launch['env'].items()
                             if k not in ('QEMU_OUTPUT_DIR', 'QEMU_RETAINED_INCOMING')})


def prepare_launch(prepared_runtime_analysis, cold_manifest, output, *, combo_manifest=None,
                   origin_qemu_build=DEFAULT_ORIGIN, incoming=False, source_launch=None,
                   extra_env=None, inherited=None, upstream_host=False):
    """Prepare source/target without a VM; cold_manifest and source_launch are files."""
    if type(incoming) is not bool or type(upstream_host) is not bool:
        raise ValueError('incoming/upstream_host must be bool')
    profile = UPSTREAM_PROFILE if upstream_host else PROFILE
    usb_env = UPSTREAM_USB if upstream_host else USB_OFF
    inherited = dict(os.environ if inherited is None else inherited)
    reject_usb(inherited)
    extra_env = dict(extra_env or {})
    reject_usb(extra_env)
    if upstream_host:
        for env in (inherited, extra_env):
            for key, expected in UPSTREAM_USB.items():
                if key in env and env[key] != expected:
                    raise ValueError('Upstream host environment must be '+key+'='+expected)
    for key, value in extra_env.items():
        if (not isinstance(value, str) or '\0' in value or not key.startswith(('QEMU_', 'SONY_', 'MENU_')) or
                key.startswith(('QEMU_A7PF_', 'QEMU_SYSTEM_', 'QEMU_RETAINED_')) or key in (
                    'QEMU_PREPARE_ONLY', 'QEMU_OUTPUT_DIR', 'QEMU_FULL_ADAPTER_DIR', 'QEMU_UI_LIVE',
                    'QEMU_TIMEOUT_SECONDS', 'QEMU_ICOUNT_ARGS', 'QEMU_FULL_AVCAM_PRELOAD')):
            raise ValueError('Unsupported retained extra environment: '+key)
    if incoming != (source_launch is not None):
        raise ValueError('Incoming preparation requires exactly one source launch manifest')
    cold_row = COLD['binding'](cold_manifest, 'retained-cold-manifest')
    cold = json.loads(Path(cold_row['path']).read_text())
    if cold.get('profile') != PERSISTENT['PROFILE'] or cold.get('build_verified') is not True:
        raise ValueError('Expected independent completed persistent cold manifest')
    combo = verify_combo(combo_manifest, origin_qemu_build=origin_qemu_build, upstream_host=upstream_host)
    source = None
    inputs = [cold_row, COLD['binding'](Path(__file__), 'retained-launcher-source'), *combo['inputs']]
    if incoming:
        row = COLD['binding'](source_launch, 'retained-source-launch')
        inputs.append(row)
        source = json.loads(Path(row['path']).read_text())
        if source.get('schema') != SCHEMA or source.get('retained_candidate') is not True or source.get('incoming') is not False:
            raise ValueError('Expected retained diagnostic source launch')
        equal('same source cold manifest', source['cold_manifest_binding'], cold_row)
        COLD['recheck'](source['template_inputs']+source['launch_inputs'])
    else:
        # Existing lease/verification only reads the disk; no build or adapter write.
        with PERSISTENT['DISK']['lease'](cold['instance']) as leased:
            PERSISTENT['verify_firmware'](leased, cold)
    output = Path(output)
    origin = PERSISTENT['prepare_launch'](prepared_runtime_analysis, cold, output,
        qemu_build=origin_qemu_build, camera_profile='virtual-functional-camera-v1')
    try:
        output = Path(origin['identity_failure_dir'])
        (output/'launch.json').rename(output/'origin-launch.json')
        old_script = COLD['plain'](origin['script'])
        inputs.append(COLD['binding'](old_script, 'production-origin-prepared-script'))
        script = old_script.with_name('qemu-kernel-retained-camera.sh')
        with script.open('x') as stream:
            stream.write(launch_script(old_script.read_text(), upstream_host=upstream_host))
        script.chmod(0o700)
        reject_usb(origin['env'])
        env = {**origin['env'], **extra_env, **usb_env,
               'QEMU_A7PF_PROFILE': profile, 'QEMU_A7PF_RETAINED_STATE': '1',
               'QEMU_RETAINED_INCOMING': str(int(incoming)),
               'QEMU_SYSTEM_DIR': str(Path(combo['binary']).parent)}
        camera = origin['camera_profile_contract']
        for key, value in camera['environment'].items():
            if key not in usb_env and key in extra_env and extra_env[key] != value:
                raise ValueError('Cannot override functional camera environment: '+key)
        if 'QEMU_EXTRA_CMDLINE' in extra_env:
            env['QEMU_EXTRA_CMDLINE'] = (origin['env'].get('QEMU_EXTRA_CMDLINE', '')+' '+extra_env['QEMU_EXTRA_CMDLINE']).strip()
        if upstream_host:
            reject_usb({k: v for k, v in env.items() if k != 'QEMU_SONY_USB_DWC3'})
            for key, expected in UPSTREAM_USB.items():
                equal('final upstream host environment '+key, expected, env.get(key))
        else:
            reject_usb(env)
        library = (Path(origin['runtime_analysis']).parent/'sources/qemu-tools/usr/lib/libfdt.so.1').resolve(strict=True)
        inputs.append(COLD['binding'](library, 'retained-dtb-library'))
        command = list(origin['command'])
        command[1] = str(script)
        subprocess.run(['bash', '-n', str(script)], check=True, timeout=10)
        with (output/'retained-prepare.stdout').open('x') as out, (output/'retained-prepare.stderr').open('x') as err:
            prepared = subprocess.run(command, env={**env, 'QEMU_PREPARE_ONLY': '1'},
                stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=55)
        if prepared.returncode:
            raise RuntimeError('Retained preparation failed; inspect retained-prepare.stderr')
        cmdline = Path(origin['cmdline_file']).read_text().strip()
        if '__boottime_sony_usb_init' in cmdline or 'persistent.profile='+PERSISTENT['PROFILE'] not in cmdline.split():
            raise ValueError('Retained diagnostic must preserve original USB software init and cold profile')
        if upstream_host:
            equal('baseline full DTB unchanged', origin['dtb_sha256'], COLD['digest'](origin['dtb']))
        verify_dtb(origin['dtb'], library, cmdline, upstream_host=upstream_host)
        changed = {origin['dtb'], origin['cmdline_file']}
        assets = [r for r in origin['launch_inputs'] if r['path'] not in changed]
        assets.extend(COLD['binding'](p, 'prepared-launch-asset') for p in sorted(changed))
        inputs.extend(origin['template_inputs'])
        COLD['recheck'](inputs+assets)
        launch = dict(origin, schema=SCHEMA, profile=profile, source_class='diagnostic-derived-retained-camera',
            disk_source_class=cold['source'], retained_candidate=True, prepare_only=True, incoming=incoming,
            launch_allowed=not incoming, command=command, env=env, script=str(script), script_sha256=COLD['digest'](script),
            qemu_binary=combo['binary'], qemu_sha256=combo['qemu_sha256'], combo_binding=combo,
            cmdline=cmdline, dtb_sha256=COLD['digest'](origin['dtb']), ram0_sha256=cold['ram0_sha256'],
            cold_manifest_binding=cold_row, extra_env=extra_env, template_inputs=inputs, launch_inputs=assets,
            origin_template_inputs=origin['template_inputs'], origin_launch=str(output/'origin-launch.json'),
            origin_camera_profile_contract=camera,
            camera_profile_contract={**camera, 'environment': {**camera['environment'], **usb_env},
                                     'diagnostic_derived': True, 'original_usb_init_in_scope': True},
            guest_started=False, supports_hot=False, supports_actual_restore=False, production_ready=False,
            full_device_audit_complete=False, original_ap_restore_verified=False, qom_audit_complete=False,
            capture_verified=False, sony_wbi_verified=False, hardware_ram_hotboot_verified=False,
            external_transaction_implemented=False, cold_panel_allowed=False, qemu_initially_paused=incoming,
            usb_ever_instantiated=None if upstream_host else False, usb_instantiated_allowed=upstream_host,
            original_usb_init_in_scope=True,
            physical_host_usb_devices=False, host_attach_verified=False, guest_gadget_verified=False,
            source_firmware_contract=PERSISTENT['firmware_contract'](cold),
            prepare_inputs_same_as_source=None, target_disk_binding=None,
            blockers=['Complete original-AP source/QOM/provider audit pending',
                      'External snapshot/same-open-FD lease/disk-generation transaction pending'])
        launch['launch_adaptations'] = {**origin['launch_adaptations'], 'original_usb_aggregate_init': True,
            'usb_platform_resources': usb_env['QEMU_FULL_USB_PLATFORM'],
            'usb_controller': usb_env['QEMU_FULL_USB_CONTROLLER'], 'retained_state': True,
            'qemu_initially_paused': incoming, 'original_usb_init_scope':
                'original software services with upstream host/full resources' if upstream_host else
                'original software services; no virtual USB controller'}
        if incoming:
            equal('target prepared guest inputs equal source', source_inputs(source), source_inputs(launch))
            launch['prepare_inputs_same_as_source'] = True
            launch['source_launch'] = str(source_launch)
            launch['prepared_command'] = launch.pop('command')
            for key in PERSISTENT['IDENTITY_FIELDS']:
                launch.pop(key)
        PERSISTENT['save'](output/'launch.json', launch)
        return launch
    except BaseException as error:
        PERSISTENT['save'](output/'retained-failure.json', PERSISTENT['failure'](error, guest_started=False))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-analysis', type=Path, required=True)
    parser.add_argument('--cold-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--combo-manifest', type=Path)
    parser.add_argument('--origin-qemu-build', type=Path, default=DEFAULT_ORIGIN)
    parser.add_argument('--incoming', action='store_true')
    parser.add_argument('--source-launch', type=Path)
    parser.add_argument('--upstream-host', action='store_true', help='explicit pinned upstream-host-only retained candidate')
    args = parser.parse_args()
    print(json.dumps(prepare_launch(args.runtime_analysis, args.cold_manifest, args.output,
        combo_manifest=args.combo_manifest, origin_qemu_build=args.origin_qemu_build,
        incoming=args.incoming, source_launch=args.source_launch, upstream_host=args.upstream_host), indent=2))


if __name__ == '__main__':
    main()
