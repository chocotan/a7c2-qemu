#!/usr/bin/env python3
"""Host-only retained launcher checks; fixtures are not QEMU/AP evidence."""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE/'retained-camera-launch.py'))
G = API['prepare_launch'].__globals__
OLD_TEST = runpy.run_path(str(HERE/'test-persistent-boot.py'))
prepared_launch = OLD_TEST['prepared_launch']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True)+'\n')


@pytest.fixture
def combo(tmp_path, monkeypatch):
    """A tiny content-pinned source tree; only optional_existing uses the real combo."""
    builder = G['COMBO']
    root = tmp_path/'combo'
    source = root/'qemu-11.1.2'
    names = set(builder['INPUTS']) | {'hw/block/a7c2-persistent/'+n for n in builder['FLASH']}
    before = {}
    after = {}
    for name in sorted(names | {'README'}):
        old = ('before '+name).encode()
        new = ('after '+name).encode() if name in names else old
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new)
        before[name], after[name] = sha(old), sha(new)
    for name, value in [('source-before.json', before), ('source-after.json', after)]:
        save(root/name, value)
    binary = root/'build/qemu-system-aarch64'
    binary.parent.mkdir()
    binary.write_bytes(b'fixture-combo-never-executed')
    frozen = root/'build/retained-persistent.ninja'
    frozen.write_text('fixture frozen build\n')
    origin = tmp_path/'origin/build'
    origin.mkdir(parents=True)
    (origin/'qemu-system-aarch64').write_bytes(b'fixture-origin-never-executed')
    production_sha = sha((origin/'qemu-system-aarch64').read_bytes())
    save(origin.parent/'qemu-result.json', dict(board_profile=G['PERSISTENT']['PROFILE'],
        qemu_binary_sha256=production_sha, source_tree_sha256_after=builder['tree_digest'](before)))
    save(origin.parent/'persistent-usb-source-delta.json', {'fixture': 'origin delta'})
    receipts = {n: sha((origin.parent/n).read_bytes()) for n in G['RECEIPTS']}
    compile_builder = root/'builder-at-compile.py'
    compile_builder.write_text('# frozen builder has a different identity\n')
    evidence = root/'actual/result.json'
    save(evidence, dict(profile=G['PROFILE'], qemu_binary_sha256=sha(binary.read_bytes()),
        actual_combined_roundtrip_verified=True, synthetic_disk=True, dma_ram_and_canary_exact=True,
        timer_count_compare_control_exact=True, input_held_release_consumed=True, usb_qdev_absent=True,
        full_spacc_bytes=262144, original_ap_restore_verified=False, usb_fields_saved_or_restored=False))
    m = dict(schema='a7c2.retained-persistent-build.v1', profile=G['PROFILE'], status='compiled',
        compiled=True, compile_returncode=0, production_sha256=production_sha,
        original_source_and_build_unchanged=True, actual_combined_roundtrip_verified=True,
        qemu_binary_sha256=sha(binary.read_bytes()), source_tree_sha256=builder['tree_digest'](after),
        source_inventory_sha256={n: sha((root/n).read_bytes()) for n in ('source-before.json', 'source-after.json')},
        binary=str(binary), files={n: dict(original=before[n], new=after[n]) for n in names},
        source_receipts_sha256=receipts, builder_at_compile_path=str(compile_builder),
        builder_sha256=sha(compile_builder.read_bytes()),
        builder_at_handoff_sha256=sha((HERE/'retained-persistent-build.py').read_bytes()),
        frozen_ninja_sha256=sha(frozen.read_bytes()), device_migration={'complete': False},
        actual_evidence=dict(result=str(evidence), sha256=sha(evidence.read_bytes()),
            test_sha256=sha((HERE/'test-retained-persistent-build.py').read_bytes())))
    for name in ('production_ready', 'full_device_audit_complete', 'original_ap_restore_verified',
                 'sony_wbi_verified', 'hardware_ram_hotboot_verified', 'ui_hot_enabled',
                 'usb_instantiated_allowed', 'usb_function_available', 'usb_state_saved_or_restored'):
        m[name] = False
    save(root/'manifest.json', m)
    monkeypatch.setitem(builder, 'PRODUCTION_SHA', production_sha)
    monkeypatch.setitem(builder, 'SOURCE_TREE_SHA', builder['tree_digest'](before))
    monkeypatch.setitem(G, 'BINARY_SHA', m['qemu_binary_sha256'])
    monkeypatch.setitem(G, 'SOURCE_SHA', m['source_tree_sha256'])
    monkeypatch.setitem(G, 'LEGACY_BUILDER_SHA', m['builder_at_handoff_sha256'])
    monkeypatch.setitem(G, 'LEGACY_TEST_SHA', m['actual_evidence']['test_sha256'])
    monkeypatch.setitem(G, 'RECEIPTS', receipts)
    return SimpleNamespace(root=root, source=source, binary=binary, origin=origin,
        manifest=root/'manifest.json', data=m)


@pytest.fixture
def case(prepared_launch, combo, tmp_path, monkeypatch):
    f = prepared_launch
    persistent = OLD_TEST['API']
    monkeypatch.setitem(G, 'PERSISTENT', persistent)
    monkeypatch.setitem(G, 'COLD', persistent['COLD'])
    cold = tmp_path/'independent-cold.json'
    save(cold, f.built)
    library = f.runtime.parent/'sources/qemu-tools/usr/lib/libfdt.so.1'
    library.parent.mkdir(parents=True)
    library.write_bytes(b'fixture-library-not-loaded')
    calls = []

    def base(runtime, manifest, output, **options):
        calls.append((copy.deepcopy(manifest), options))
        assert options == dict(qemu_build=combo.origin, camera_profile='virtual-functional-camera-v1')
        output.mkdir()
        analysis = output/'runtime/analysis'
        analysis.mkdir(parents=True)
        (analysis.parent/'sources').symlink_to(f.runtime.parent/'sources', target_is_directory=True)
        installed = []
        for row in f.launch['launch_inputs']:
            if row['path'] in (f.launch['dtb'], f.launch['cmdline_file'], f.built['ram0_image']):
                continue
            path = Path(row['path'])
            target = analysis/path.relative_to(f.launch['runtime_analysis'])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            installed.append(persistent['COLD']['binding'](target, row['role']))
        script = analysis/'qemu-kernel-persistent.sh'
        script.write_text(Path(f.launch['script']).read_text())
        script.chmod(0o700)
        run = output/'run'
        run.mkdir()
        (run/'virt.dtb').write_bytes(b'origin-prepared-dtb')
        (run/'cold-cmdline.txt').write_text(manifest['cold_cmdline']+'\n')
        inputs = [r for r in f.launch['template_inputs'] if r['role'] != 'production-qemu-input']
        inputs.extend(persistent['COLD']['binding'](p, 'production-qemu-input') for p in (
            combo.origin/'qemu-system-aarch64', combo.origin.parent/'qemu-result.json'))
        installed.extend(persistent['COLD']['binding'](p, 'prepared-launch-asset') for p in (
            Path(manifest['ram0_image']), run/'virt.dtb', run/'cold-cmdline.txt'))
        result = dict(f.launch, script=str(script), script_sha256=sha(script.read_bytes()),
            runtime_analysis=str(analysis), dtb=str(run/'virt.dtb'), dtb_sha256=sha((run/'virt.dtb').read_bytes()),
            cmdline_file=str(run/'cold-cmdline.txt'), template_inputs=inputs, launch_inputs=installed,
            identity_failure_dir=str(output), qmp_socket=str(run/'qmp.sock'), qmp_parent=str(run),
            command=['bash', str(script), '4096', str(analysis/'boards/virt-four.dtb'), '1', '1', manifest['ram0_image']],
            camera_profile_contract={'environment': {'QEMU_TCG_THREAD': f.launch['env']['QEMU_TCG_THREAD'],
                'QEMU_FULL_USB_CONTROLLER': 'upstream-host'}, 'cmdline': ['fullsystem.sound-owner=1']},
            env={**f.launch['env'], 'QEMU_OUTPUT_DIR': str(run), 'QEMU_SYSTEM_DIR': str(combo.origin),
                'QEMU_EXTRA_CMDLINE': 'fullsystem.sound-owner=1 fullsystem.pin-control-memory=1 fullsystem.lcd-claim=ram'})
        save(output/'launch.json', result)
        return result

    original_run = subprocess.run
    prepares = []

    def prepare(command, **kwargs):
        env = kwargs.get('env', {})
        if env.get('QEMU_A7PF_RETAINED_STATE') == '1' and env.get('QEMU_PREPARE_ONLY') == '1':
            prepares.append((command, dict(env)))
            run = Path(env['QEMU_OUTPUT_DIR'])
            (run/'virt.dtb').write_bytes(b'origin-prepared-dtb' if env.get('QEMU_SONY_USB_DWC3') == '1' else b'retained-prepared-dtb')
            (run/'cold-cmdline.txt').write_text(f.built['cold_cmdline']+'\n')
            return subprocess.CompletedProcess(command, 0)
        return original_run(command, **kwargs)

    monkeypatch.setitem(persistent, 'prepare_launch', base)
    monkeypatch.setattr(subprocess, 'run', prepare)
    monkeypatch.setitem(G, 'verify_dtb', lambda *args, **kwargs: None)

    def prepare_new(name='source', **kwargs):
        return API['prepare_launch'](f.runtime, cold, tmp_path/name,
            combo_manifest=combo.manifest, origin_qemu_build=combo.origin, inherited={}, **kwargs)

    return SimpleNamespace(f=f, combo=combo, cold=cold, calls=calls, prepares=prepares, prepare=prepare_new)


def test_prepare_rebinds_combo_and_preserves_camera_and_current_generation(case):
    launch = case.prepare(extra_env={'QEMU_NATIVE_INPUT': '1', 'QEMU_FULL_USB_CONTROLLER': 'upstream-host'})
    assert len(case.calls) == len(case.prepares) == 1
    assert case.calls[0][0] == case.f.built
    assert launch['qemu_binary'] == str(case.combo.binary)
    assert launch['env']['QEMU_SYSTEM_DIR'] == str(case.combo.binary.parent)
    assert launch['env']['QEMU_A7PF_PROFILE'] == G['PROFILE']
    assert launch['env']['QEMU_A7PF_RETAINED_STATE'] == '1'
    assert launch['env']['QEMU_RETAINED_INCOMING'] == '0'
    assert all(launch['env'][k] == v for k, v in G['USB_OFF'].items())
    assert launch['env']['QEMU_NATIVE_INPUT'] == '1'
    assert launch['env']['QEMU_FULL_USB_INIT'] == 'original'
    assert '__boottime_sony_usb_init' not in launch['cmdline']
    assert launch['original_usb_init_in_scope'] is True
    assert launch['launch_adaptations']['original_usb_aggregate_init'] is True
    assert 'fullsystem.sound-owner=1' in launch['env']['QEMU_EXTRA_CMDLINE']
    assert 'fullsystem.pin-control-memory=1' in launch['env']['QEMU_EXTRA_CMDLINE']
    assert launch['instance_generation'] == 7
    assert launch['partition_bindings'] == case.f.built['partition_bindings']
    assert launch['actual_kernel'] == case.f.built['actual_kernel']
    assert launch['source_class'] == 'diagnostic-derived-retained-camera'
    assert launch['retained_candidate'] is True
    for flag in ('supports_hot', 'supports_actual_restore', 'production_ready', 'full_device_audit_complete',
                 'original_ap_restore_verified', 'qom_audit_complete', 'guest_started'):
        assert launch[flag] is False
    assert Path(launch['origin_launch']).exists()
    assert launch['origin_template_inputs']
    assert launch['camera_profile_contract']['environment']['QEMU_FULL_USB_CONTROLLER'] == 'off'
    assert any(r['path'] == str(case.combo.binary) for r in launch['template_inputs'])
    G['COLD']['recheck'](launch['template_inputs']+launch['launch_inputs'])
    assert Path(launch['dtb']).read_bytes() == b'retained-prepared-dtb'
    with G['PERSISTENT']['leased_launch'](launch) as bound:
        assert bound['fd'] in bound['pass_fds']
        assert bound['env']['QEMU_A7PF_RETAINED_STATE'] == '1'


def test_target_same_inputs_and_snapshot_binding_stays_blocked(case):
    source = case.prepare(extra_env={'QEMU_NATIVE_INPUT': '1'})
    # Snapshot generation/partition state may have advanced; these are not target bindings.
    state = dict(case.f.state, generation=8)
    save(case.f.instance/'instance.json', state)
    with case.f.disk.open('r+b') as stream:
        stream.seek(512)
        stream.write(b'X')
    target = case.prepare('target', incoming=True,
        source_launch=Path(source['identity_failure_dir'])/'launch.json', extra_env=source['extra_env'])
    assert len(case.calls) == 2
    assert target['prepare_inputs_same_as_source'] is True
    assert target['env']['QEMU_RETAINED_INCOMING'] == '1'
    assert target['dtb_sha256'] == source['dtb_sha256']
    assert target['script_sha256'] == source['script_sha256']
    assert target['launch_allowed'] is False and 'command' not in target
    assert target['target_disk_binding'] is None
    assert 'partition_bindings' not in target and 'instance_generation' not in target
    assert target['source_firmware_contract']['partition_bindings'] == source['partition_bindings']
    assert API['source_inputs'](target) == API['source_inputs'](source)
    script = Path(target['script'])
    blocked = subprocess.run(['bash', str(script)], env=target['env'], capture_output=True, text=True)
    assert blocked.returncode == 2 and 'external snapshot/lease transaction' in blocked.stderr
    assert G['PERSISTENT']['leased_launch'] is not None


def test_target_rejects_changed_extra_inputs(case):
    source = case.prepare()
    with pytest.raises(ValueError, match='target prepared guest inputs equal source'):
        case.prepare('target-changed', incoming=True,
            source_launch=Path(source['identity_failure_dir'])/'launch.json', extra_env={'QEMU_NATIVE_INPUT': '1'})


@pytest.mark.parametrize('key', ['QEMU_SONY_USB', 'QEMU_SONY_USB_DWC3', 'QEMU_SONY_DWC3_BRIDGE'])
@pytest.mark.parametrize('value', ['', '0', '1'])
def test_reject_every_inherited_usb_value_before_prepare(case, key, value):
    with pytest.raises(ValueError, match='every USB environment value'):
        API['prepare_launch'](case.f.runtime, case.cold, case.cold.parent/'refused', inherited={key: value})
    with pytest.raises(ValueError, match='every USB environment value'):
        case.prepare(extra_env={key: value})
    assert case.calls == []


@pytest.mark.parametrize('key', ['QEMU_SYSTEM_BINARY', 'QEMU_SYSTEM_DIR', 'QEMU_ICOUNT_ARGS',
                               'QEMU_A7PF_RETAINED_STATE', 'QEMU_RETAINED_INCOMING'])
def test_reject_managed_overrides(case, key):
    with pytest.raises(ValueError, match='Unsupported retained extra environment'):
        case.prepare(extra_env={key: '1'})
    assert not case.calls


def test_rechecks_actual_new_source_hash_drift_and_per_run_assets(case):
    one = case.prepare()
    two = case.prepare('source-two')
    assert {r['path'] for r in one['launch_inputs']} != {r['path'] for r in two['launch_inputs']}
    changed = case.combo.source/'hw/arm/virt.c'
    changed.write_bytes(b'changed device source')
    with pytest.raises(ValueError, match='launch asset .*hw/arm/virt.c'):
        with G['PERSISTENT']['leased_launch'](two):
            pytest.fail('Drifted source yielded a launch binding')


def test_final_camera_merge_cannot_reintroduce_usb(case):
    case.f.launch['env']['QEMU_SONY_DWC3_SHARED'] = '0'
    with pytest.raises(ValueError, match='every USB environment value'):
        case.prepare()
    assert len(case.calls) == 1 and case.prepares == []


def test_source_refuses_stale_generation_before_origin_prepare(case):
    save(case.f.instance/'instance.json', dict(case.f.state, generation=8))
    with pytest.raises(ValueError, match='instance generation'):
        case.prepare()
    assert case.calls == []


def test_extra_cmdline_preserves_camera_claims_and_rejects_provider_override(case):
    launch = case.prepare(extra_env={'QEMU_EXTRA_CMDLINE': 'diagnostic.extra=1'})
    assert launch['env']['QEMU_EXTRA_CMDLINE'].endswith(' diagnostic.extra=1')
    assert 'fullsystem.sound-owner=1' in launch['env']['QEMU_EXTRA_CMDLINE']
    assert 'fullsystem.pin-control-memory=1' in launch['env']['QEMU_EXTRA_CMDLINE']
    with pytest.raises(ValueError, match='Cannot override functional camera environment'):
        case.prepare('provider-override', extra_env={'QEMU_TCG_THREAD': 'different'})


def test_real_script_syntax_unique_anchors_and_incoming_flags(tmp_path):
    base = G['PERSISTENT']['launch_script'](OLD_TEST['template'](), OLD_TEST['manifest']())
    text = API['launch_script'](base)
    path = tmp_path/'retained.sh'
    path.write_text(text)
    subprocess.run(['bash', '-n', str(path)], check=True)
    assert '--setenv QEMU_A7PF_RETAINED_STATE 1' in text
    assert '--setenv QEMU_A7PF_PROFILE '+G['PROFILE'] in text
    assert '--setenv QEMU_SONY_USB_DWC3' not in text
    assert 'retained_incoming_args=(-S -incoming defer)' in text
    assert '"${retained_incoming_args[@]}" '+G['ARGV_ANCHOR'] in text
    for anchor in (G['PROFILE_ANCHOR'], G['USB_ANCHOR'], G['ARGV_ANCHOR'], 'set -euo pipefail\n'):
        with pytest.raises(ValueError, match='anchor must occur once'):
            API['launch_script'](base.replace(anchor, ''))
        with pytest.raises(ValueError, match='anchor must occur once'):
            API['launch_script'](base+anchor)
    with pytest.raises(ValueError, match='Already derived'):
        API['launch_script'](text)
    guard = tmp_path/'guard.sh'
    guard.write_text('set -euo pipefail\n'+G['GUARD']+'\nprintf "<%s>" "${retained_incoming_args[@]}"\n')
    env = {**G['USB_OFF'], 'QEMU_A7PF_PROFILE': G['PROFILE'], 'QEMU_A7PF_RETAINED_STATE': '1', 'QEMU_PREPARE_ONLY': '1'}
    for value in ('', '2', 'true', '01'):
        r = subprocess.run(['bash', str(guard)], env={**env, 'QEMU_RETAINED_INCOMING': value}, capture_output=True)
        assert r.returncode == 2
    for value, expected in [('0', '<>'), ('1', '<-S><-incoming><defer>')]:
        r = subprocess.run(['bash', str(guard)], env={**env, 'QEMU_RETAINED_INCOMING': value}, capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout == expected
    r = subprocess.run(['bash', str(guard)], env={**env, 'QEMU_RETAINED_INCOMING': '0', 'QEMU_SONY_DWC3_X': ''}, capture_output=True)
    assert r.returncode == 2


def test_combo_content_verification_and_separate_builder_identities(combo):
    result = API['verify_combo'](combo.manifest, origin_qemu_build=combo.origin)
    assert result['binary'] == str(combo.binary)
    assert combo.data['builder_sha256'] != combo.data['builder_at_handoff_sha256']
    assert len([r for r in result['inputs'] if r['role'] == 'retained-device-source']) == 7


@pytest.mark.parametrize('drift', ['binary', 'changed-source', 'unchanged-source', 'inventory', 'origin', 'qtest', 'frozen-builder'])
def test_combo_rejects_content_drift(combo, drift):
    path = {'binary': combo.binary, 'changed-source': combo.source/'hw/arm/virt.c',
            'unchanged-source': combo.source/'README', 'inventory': combo.root/'source-after.json',
            'origin': combo.origin.parent/'qemu-result.json', 'qtest': combo.root/'actual/result.json',
            'frozen-builder': combo.root/'builder-at-compile.py'}[drift]
    path.write_bytes(path.read_bytes()+b'drift')
    with pytest.raises(ValueError):
        API['verify_combo'](combo.manifest, origin_qemu_build=combo.origin)


def test_dtb_checks_actual_bootargs_and_usb_nodes(tmp_path):
    library = HERE/'runtime/sources/qemu-tools/usr/lib/libfdt.so.1'
    if not library.exists():
        pytest.skip('optional prepared libfdt is unavailable')

    def dtb(cmdline, usb):
        strings = b'bootargs\0compatible\0'
        def pad(data):
            return data+b'\0'*((-len(data)) % 4)
        def begin(name):
            return struct.pack('>I', 1)+pad(name+b'\0')
        def prop(name_offset, data):
            return struct.pack('>III', 3, len(data), name_offset)+pad(data)
        end = struct.pack('>I', 2)
        nodes = begin(b'')+begin(b'chosen')+prop(0, cmdline.encode()+b'\0')+end
        if usb:
            nodes += begin(b'controller@1234')+prop(9, b'snps,dwc3\0')+end
        nodes += end+struct.pack('>I', 9)
        return struct.pack('>10I', 0xd00dfeed, 56+len(nodes)+len(strings), 56,
            56+len(nodes), 40, 17, 16, 0, len(strings), len(nodes))+b'\0'*16+nodes+strings

    path = tmp_path/'virt.dtb'
    path.write_bytes(dtb('retained.test=1', False))
    API['verify_dtb'](path, library.resolve(), 'retained.test=1')
    with pytest.raises(ValueError, match='DTB bootargs'):
        API['verify_dtb'](path, library.resolve(), 'changed=1')
    path.write_bytes(dtb('retained.test=1', True))
    with pytest.raises(ValueError, match='USB node'):
        API['verify_dtb'](path, library.resolve(), 'retained.test=1')


def test_upstream_explicit_source_target_and_legacy_profile_rejection(case, monkeypatch):
    combo = case.combo
    combo.data.update(profile=G['UPSTREAM_PROFILE'], usb_instantiated_allowed=True,
        declared_topology=G['COMBO']['UPSTREAM_TOPOLOGY'], upstream_usb_actual_roundtrip_verified=True,
        physical_host_usb_devices=False, host_attach_verified=False, guest_gadget_verified=False)
    evidence = combo.root/'actual/result.json'
    result = json.loads(evidence.read_text())
    result.update(profile=G['UPSTREAM_PROFILE'], usb_qdev_absent=False,
        upstream_usb_registers_exact=True, sony_usb_qdev_and_provider_absent=True)
    save(evidence, result)
    combo.data['actual_evidence']['sha256'] = sha(evidence.read_bytes())
    save(combo.manifest, combo.data)
    monkeypatch.setitem(G, 'UPSTREAM_BINARY_SHA', combo.data['qemu_binary_sha256'])
    monkeypatch.setitem(G, 'UPSTREAM_SOURCE_SHA', combo.data['source_tree_sha256'])
    with pytest.raises(ValueError, match='combo profile'):
        case.prepare()
    source = case.prepare('host-source', upstream_host=True)
    assert source['profile'] == G['UPSTREAM_PROFILE']
    assert all(source['env'][k] == v for k, v in G['UPSTREAM_USB'].items())
    text = Path(source['script']).read_text()
    assert text.count('--setenv QEMU_SONY_USB_DWC3 1') == 1
    assert G['USB_ANCHOR'] in text
    for key, value in G['UPSTREAM_USB'].items():
        assert text.count('--setenv '+key+' '+value) == 1
    assert '-device usb-host' not in text and '/dev/bus/usb' not in text
    assert source['physical_host_usb_devices'] is False
    assert source['host_attach_verified'] is False
    assert source['guest_gadget_verified'] is False
    assert source['original_usb_init_in_scope'] is True
    target = case.prepare('host-target', upstream_host=True, incoming=True,
        source_launch=Path(source['identity_failure_dir'])/'launch.json')
    assert target['prepare_inputs_same_as_source'] is True and target['launch_allowed'] is False
    assert 'command' not in target
    blocked = subprocess.run(['bash', target['script']], env=target['env'], capture_output=True)
    assert blocked.returncode == 2 and b'external snapshot/lease transaction' in blocked.stderr
    for key, value in [('QEMU_FULL_USB_CONTROLLER', 'off'), ('QEMU_FULL_USB_PLATFORM', ''),
                       ('QEMU_FULL_USB_INIT', 'skipped'), ('QEMU_SONY_USB_BACKEND_SOCKET', '0')]:
        with pytest.raises(ValueError):
            case.prepare('bad-host-'+key, upstream_host=True, extra_env={key: value})
    assert len(case.prepares) == 2


def test_upstream_shell_guard_rejects_missing_flag_wrong_values_and_foreign_keys(tmp_path):
    guard = tmp_path/'host-guard.sh'
    guard.write_text('set -euo pipefail\n'+G['UPSTREAM_GUARD'])
    env = {**G['UPSTREAM_USB'], 'QEMU_A7PF_PROFILE': G['UPSTREAM_PROFILE'],
           'QEMU_A7PF_RETAINED_STATE': '1', 'QEMU_RETAINED_INCOMING': '0'}
    assert subprocess.run(['bash', str(guard)], env=env, capture_output=True).returncode == 0
    cases = [{'QEMU_A7PF_PROFILE': G['PROFILE']}, {'QEMU_A7PF_RETAINED_STATE': ''},
             {'QEMU_A7PF_RETAINED_STATE': '0'}, {'QEMU_FULL_USB_PLATFORM': 'off'},
             {'QEMU_FULL_USB_CONTROLLER': 'off'}, {'QEMU_FULL_USB_INIT': 'skipped'},
             {'QEMU_SONY_USB_DWC3': ''}, {'QEMU_SONY_USB_DWC3': '0'}]
    cases += [{key: value} for key in ('QEMU_SONY_USB_BACKEND_SOCKET', 'QEMU_SONY_USB_RUN_ID',
        'QEMU_SONY_USB_LEASE', 'QEMU_SONY_DWC3_CORE_TEST', 'QEMU_SONY_DWC3_BRIDGE') for value in ('', '0', '1')]
    for change in cases:
        assert subprocess.run(['bash', str(guard)], env={**env, **change}, capture_output=True).returncode == 2
    missing = dict(env)
    missing.pop('QEMU_A7PF_RETAINED_STATE')
    assert subprocess.run(['bash', str(guard)], env=missing, capture_output=True).returncode == 2


def test_optional_existing_combo_content_only():
    if not API['DEFAULT_COMBO'].exists() or not API['DEFAULT_ORIGIN'].exists():
        pytest.skip('optional existing production-derived combo is unavailable')
    result = API['verify_combo'](API['DEFAULT_COMBO'], origin_qemu_build=API['DEFAULT_ORIGIN'])
    assert result['qemu_sha256'] == API['BINARY_SHA']
    assert result['source_tree_sha256'] == API['SOURCE_SHA']
