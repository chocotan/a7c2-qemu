#!/usr/bin/env python3
"""Consume private cold/sequence/hot requests with explicit main-owned capabilities.

The fixed retained backend owns its source/target disk transaction. This module
never publishes capabilities, discovers instances or executes caller commands.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import runpy
import stat
import time
import traceback

HERE = Path(__file__).resolve().parent
DEV = runpy.run_path(str(HERE / 'firmware-development.py'))
SCHEMA = DEV['SCHEMA']
Blocked = DEV['Blocked']
refuse = DEV['refuse']
read_json = DEV['read_json']
write_json = DEV['write_json']
path_checked = DEV['path_checked']
STAGES = DEV['STAGES']


def sha(path):
    with path_checked(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def current(context, instance, fd=None):
    if DEV['bind_instance'](context) != instance:
        refuse('instance_changed', 'Instance identity changed')
    manifest = path_checked(instance['manifest'], private=True)
    directory = path_checked(manifest.parent, directory=True, private=True)
    if manifest != directory / 'instance.json' or Path(instance['disk']) != directory / 'camera.emmc':
        refuse('instance_layout', 'Expected instance/instance.json and instance/camera.emmc')
    path_checked(instance['disk'], private=True)
    state = read_json(manifest)
    geometry_path = path_checked(directory / 'geometry.json', private=True)
    geometry = read_json(geometry_path)
    if (state.get('schema') != 'a7c2-persistent-emmc-v1' or
            geometry.get('schema') != state['schema'] or
            type(state.get('generation')) is not int or state['generation'] != instance['generation'] or
            state.get('geometry_sha256') != instance['geometry_sha256'] or
            sha(geometry_path) != instance['geometry_sha256'] or
            geometry.get('backing_file') != 'camera.emmc' or geometry.get('backing_bytes') != instance['bytes']):
        refuse('instance_changed', 'Generation, geometry or backing capacity changed')
    if fd is not None:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                stat.S_IMODE(info.st_mode) != 0o600 or
                (info.st_dev, info.st_ino, info.st_size) != tuple(instance[k] for k in ('dev', 'ino', 'bytes'))):
            refuse('instance_changed', 'Leased FD differs from the bound disk')
    source_known = (state.get('source_class') in ('private-device-dump', 'official-bodydata-derived') and
                    bool(re.fullmatch('[0-9a-f]{64}', str(state.get('source_manifest_sha256', '')))))
    return directory, state, geometry, source_known


def unchanged(request, context):
    latest = DEV['load_context'](request['context_path'])
    if latest != context:
        refuse('context_changed', 'Main-owned context changed; refresh before retrying')
    current(latest, request['instance_identity'])


def envelope(request_path, request):
    context = DEV['load_context'](request.get('context_path'))
    directory = path_checked(request.get('output_dir'), directory=True, private=True)
    parent = Path(context['workspace'])
    for name in ('.a7c2', 'firmware-development', 'runs'):
        parent = path_checked(parent / name, directory=True, private=True)
    if (not re.fullmatch(r'job-[0-9a-f]{32}', directory.name) or directory.parent != parent or
            request.get('job_id') != directory.name or request.get('run_id') != directory.name or
            request_path != directory / 'request.json'):
        refuse('job_binding', 'Request/output/job/run must name the same private UI job')
    result_path = path_checked(request.get('controller_result'), missing=True)
    if result_path != directory / 'controller-result.json':
        refuse('result_scope', 'Controller receipt must be this job/controller-result.json')
    if os.path.lexists(result_path):
        refuse('result_exists', 'Retain previous controller receipt; do not overwrite it')
    return context, directory, result_path


def validate(request, context):
    if request.get('schema') != SCHEMA:
        refuse('request_schema', 'Unsupported firmware-development request schema')
    action = request.get('action')
    if not isinstance(action, str) or action not in STAGES:
        refuse('unknown_action', 'Unknown firmware-development action')
    if request.get('required_stages') != list(STAGES[action]) or request.get('target') != action:
        refuse('required_stages', 'Request must preserve the exact required stages and target')
    if request.get('profile') != 'official':
        refuse('unknown_profile', 'Only the official development request profile is connected')
    for flag in ('virtual_dev_update', 'cold_fallback_allowed', 'host_functional_fallback_allowed',
                 'source_mutation_allowed'):
        if request.get(flag) is not False:
            refuse('request_policy', flag + ' must be false')
    if request.get('signature_policy') != 'verify-official':
        refuse('request_policy', 'Official signature policy required')
    if action == 'hot' and not isinstance(context.get('available_capabilities', {}).get('hot'), dict):
        refuse('action_not_implemented', 'hot: no explicit live owner capability; no fallback')
    if action not in ('cold', 'sequence', 'hot'):
        refuse('action_not_implemented', action + ': live owned state/original execution is not connected; no fallback')
    allowed = {'schema', 'job_id', 'run_id', 'action', 'target', 'context_path', 'runtime', 'workspace',
               'output_dir', 'controller_result', 'instance_identity', 'required_stages', 'profile',
               'signature_policy', 'virtual_dev_update', 'cold_fallback_allowed',
               'host_functional_fallback_allowed', 'source_mutation_allowed', 'boot_profile', 'controller'}
    if set(request) - allowed:
        refuse('request_fields', 'Unexpected cold request fields: ' + ','.join(sorted(set(request) - allowed)))
    boot_profile = {'cold': 'original-init-cold', 'sequence': 'qemu-retained-roundtrip',
                    'hot': 'qemu-live-retained-roundtrip'}[action]
    if request.get('boot_profile') != boot_profile:
        refuse('unknown_boot_profile', 'Expected exactly ' + boot_profile)
    if request.get('controller') != str(HERE / 'boot-session.py'):
        refuse('controller_binding', 'Cold controller must be the fixed boot-session.py')
    if any(request.get(k) != context[k] for k in ('runtime', 'workspace', 'instance_identity')):
        refuse('context_changed', 'Request runtime/workspace/instance no longer match context')
    instance = DEV['bind_instance'](context)
    capability = context.get('available_capabilities', {}).get(action)
    if not isinstance(capability, dict) or capability.get('available') is not True:
        refuse('required_stage_unavailable', 'Main-owned cold capability is unavailable')
    if capability.get('contract') != SCHEMA or capability.get('instance_identity') != instance:
        refuse('capability_instance_mismatch', 'Cold capability contract/instance/generation mismatch')
    if action in ('sequence', 'hot'):
        DEV['sequence_capability'](context, instance) if action == 'sequence' else DEV['hot_capability'](context, instance)
        directory, _, _, source_known = current(context, instance)
        if not source_known:
            refuse('source_unknown', 'Persistent source provenance is unknown')
        return directory, None, None
    camera_profile = capability.get('camera_profile', 'strict')
    if camera_profile not in ('strict', 'virtual-functional-camera-v1'):
        refuse('unknown_camera_profile', 'Unknown persistent camera profile')
    qemu_build = capability.get('qemu_build')
    if qemu_build is not None:
        qemu_build = path_checked(qemu_build, directory=True)
        path_checked(qemu_build / 'qemu-system-aarch64')
        path_checked(qemu_build.parent / 'qemu-result.json')
    directory, _, _, source_known = current(context, instance)
    # Core debugfs commands accept path words; do not pass shell/debugfs syntax through them.
    for value in (context['runtime'], context['workspace'], str(directory), str(qemu_build or HERE)):
        if not re.fullmatch(r'/[A-Za-z0-9_./+\-]+', value):
            refuse('unsafe_core_path', 'Cold core paths must be literal ASCII path words')
    if not source_known:
        refuse('source_unknown', 'Persistent source provenance is unknown')
    return directory, camera_profile, qemu_build


def artifact(path, directory, snapshots, name, expected=None, limit=64 * 1024 ** 2):
    path = path_checked(path)
    if not path.is_relative_to(directory):
        refuse('evidence_scope', 'Evidence must belong to this job: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink != 1 or
                before.st_size > limit):
            refuse('evidence_file', 'Evidence is not a bounded owned regular file')
        target = snapshots / name
        digest = hashlib.sha256()
        with target.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            remaining = before.st_size
            while remaining:
                data = os.read(fd, min(remaining, 1024 ** 2))
                if not data:
                    refuse('evidence_changed', 'Evidence truncated during readback')
                stream.write(data)
                digest.update(data)
                remaining -= len(data)
            stream.flush()
            os.fsync(stream.fileno())
        if (DEV['_identity'](before) != DEV['_identity'](os.fstat(fd)) or
                DEV['_identity'](before) != DEV['_identity'](path.lstat())):
            refuse('evidence_changed', 'Evidence changed during readback')
        actual = digest.hexdigest()
        if expected is not None and expected != actual:
            refuse('evidence_hash', 'Original evidence SHA256 mismatch: ' + str(path))
        if sha(target) != actual:
            refuse('evidence_hash', 'Private evidence readback mismatch')
        return {'path': str(target), 'sha256': actual, 'bytes': before.st_size,
                'original_path': str(path)}
    finally:
        os.close(fd)


def lcd_pixels(path):
    raw = path.read_bytes()
    header = re.match(rb'P6\s+(?:#[^\r\n]*\r?\n\s*)*640\s+480\s+255(?:\r\n|\n|[ \t])', raw)
    if header is None or len(raw) - header.end() != 640 * 480 * 3:
        return False
    pixels = raw[header.end():]
    return any(pixels[i:i + 3] != pixels[:3] for i in range(3, len(pixels), 3))


def stage_evidence(directory, request, execution, cold, launch, executor, fd_binding, snapshots):
    output = directory / 'cold-session'
    raw = artifact(output / 'evidence/boot-flow.json', directory, snapshots, 'boot-flow.json')
    if read_json(raw['path']) != execution:
        refuse('execution_receipt', 'Executor result differs from its original durable receipt')
    console = artifact(output / 'evidence/console.log', directory, snapshots, 'console.log')
    owner = artifact(output / 'evidence/owner-exit.json', directory, snapshots, 'owner-exit.json')
    if read_json(owner['path']) != execution.get('owner'):
        refuse('owner_receipt', 'Owner result differs from original exit receipt')
    script = artifact(launch['script'], directory, snapshots, 'launch-script.txt', launch['script_sha256'])
    # Re-run the existing collector on the actual console, then check every raw reference.
    receipt = execution['receipt']
    for stage in receipt['stages']:
        for entry in stage.get('evidence', {}).get('artifacts', []):
            path = path_checked(entry.get('path'))
            if not path.is_relative_to(directory):
                refuse('evidence_scope', 'Original stage references evidence outside this job')
            if sha(path) != entry.get('sha256'):
                refuse('evidence_hash', 'Original stage artifact SHA256 mismatch')
    bindings = receipt['bindings']
    expected_bindings = {'run': 'evidence', 'source_class': cold['source'], 'ram0_sha256': cold['ram0_sha256'],
                         'script_identity': cold['script_identity'], 'launch_script_sha256': launch['script_sha256'],
                         'dtb_sha256': launch['dtb_sha256']}
    if (bindings != expected_bindings or receipt['profile'] != 'original-init-cold' or
            receipt.get('kernel_cmdline') != launch['cmdline']):
        refuse('execution_binding', 'Executor receipt is not bound to this launch/script/source')
    collected = executor['new_receipt']('original-init-cold', bindings=bindings, kernel_cmdline=launch['cmdline'])
    coverage = executor['collect'](Path(console['path']), collected)
    text = Path(console['path']).read_text(errors='replace').replace('\r', '')
    mapped = re.findall(r'(?:^|\n)COLD_AP_MAP pid=(\d+) sha256=' + executor['APPFW_SHA256'] + r'(?:\n|$)', text)
    observed = re.findall(r'OBS OBSERVER_READY pid=(\d+) base=0x[1-9a-f][0-9a-f]* ', text)
    osd = re.findall(r'OBS OSD_HEADLESS_PERSISTED seq=(\d+) pixel_source_seq=(\d+) [^\n]*geometry=640x480 bytes=614400 [^\n]*path=/dev/qemu-simulation/headless-osd-frame.bin(?:\n|$)', text)
    original_lcd_source = (any(pid in observed for pid in mapped) and
                           bool(re.search(r'OBS CREATE_SCREEN_ARGS [^\n]* id=0 count=565 ', text)) and
                           any(0 < int(source) <= int(seq) for seq, source in osd))
    ppm = None
    ppm_path = output / 'launch/run/cold-display.ppm'
    if ppm_path.exists():
        ppm = artifact(ppm_path, directory, snapshots, 'cold-display.ppm', limit=1024 ** 2)
    lcd = bool(ppm and lcd_pixels(Path(ppm['path'])) and original_lcd_source)
    terminal = execution.get('owner', {})
    shutdown = (terminal.get('qmp_quit_confirmed') is True and type(terminal.get('returncode')) is int and
                terminal['returncode'] == 0 and terminal.get('signals_sent') == [] and
                terminal.get('process_still_running') is False and 'cleanup_error' not in terminal and
                not terminal.get('close_errors'))
    root = collected.get('observed_mounts', {}).get('/', {})
    modules = re.findall(r'sony_persistent_flash: real durable MMIO DMA, major=(\d+) slices=19 base=0xb000000', text)
    root_verified = (root.get('fs') == 'ext2' and root.get('source') in ('/dev/nflasha7', '/dev/pnflasha7') and
                     'ro' in root.get('options', []) and any(root.get('device') == major + ':135' for major in modules))
    rows = re.findall(r'(?:^|\n)PERSISTENT_CAPACITY node=([A-Za-z0-9]+) expected=(\d+) actual=(\d+)(?=\n|$)', text)
    geometry = cold['instance_geometry']
    expected = {'pnflasha': geometry['user_bytes'] // 512,
                **{'cnflasha' + str(row['part']): row['bytes'] // 512 for row in geometry['partition_rows'] if row['bytes']},
                'nflashaB0': 8192, 'nflashaB1': 8192}
    capacities = (cold['capacity_checks'] == expected and len(expected) == 20 and len(rows) == 20 and len({r[0] for r in rows}) == 20 and
                  {node: int(count) for node, count, actual in rows if count == actual} == expected)
    persistent = (bool(re.search(r'(?:^|\n)PERSISTENT_FLASH_INSMOD rc=0(?:\n|$)', text)) and
                  capacities and root_verified and fd_binding.get('verified') is True and fd_binding.get('source_known') is True)
    clean = (execution.get('guest_started') is True and not collected.get('observed_failures') and
             not execution.get('error'))
    values = {'original_init_cold': execution.get('cold_guest_chain_verified') is True and coverage['cold_guest_chain_verified'] is True and clean,
              'system_runtime': execution.get('ap_verified') is True and coverage['ap_verified'] is True and lcd and shutdown and clean,
              'persistent_device': persistent and clean}
    details = {'original_init_cold': {'collector': coverage, 'script': script},
               'system_runtime': {'lcd': ppm, 'original_lcd_source_verified': original_lcd_source,
                                  'shutdown_verified': shutdown, 'owner': terminal},
               'persistent_device': {'bound_fd': fd_binding, 'capacities_verified': capacities,
                                     'expected_capacities': expected, 'guest_root': root, 'guest_root_device_verified': root_verified}}
    stages = {}
    for name in STAGES['cold']:
        path = snapshots / (name + '.json')
        write_json(path, {k: request[k] for k in ('schema', 'job_id', 'run_id', 'action', 'instance_identity')} |
                   {'stage': name, 'verified': bool(values[name]), 'execution': raw, 'console': console,
                    'owner_receipt': owner, **details[name]})
        stages[name] = {'verified': bool(values[name]), 'execution_kind': 'persistent_device' if name == 'persistent_device' else 'guest_original',
                        'path': str(path), 'sha256': sha(path)}
    return stages


def retained_check(condition, message):
    if not condition:
        refuse('retained_evidence', message)


def retained_reference(path, directory, backend, *, expected=None, record=None, limit=32 * 1024 ** 3):
    """Hash large private evidence in place; never duplicate a RAM stream."""
    path = path_checked(path, private=True)
    if not path.is_relative_to(directory):
        refuse('evidence_scope', 'Retained evidence must belong to this job')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = backend['DS']['_record'](fd)
        retained_check(0 < before['size'] <= limit and (record is None or before == record),
                       'Retained evidence size/inode/stamp differs')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        retained_check(before == backend['DS']['_record'](fd) and
                       DEV['_identity'](os.fstat(fd)) == DEV['_identity'](path.lstat()),
                       'Retained evidence changed during readback')
        if expected is not None and actual != expected:
            refuse('evidence_hash', 'Retained evidence SHA256 differs: ' + str(path))
        return {'path': str(path), 'sha256': actual, 'bytes': before['size'], 'file_record': before}
    finally:
        os.close(fd)


def retained_stage_evidence(directory, request, context, backend, execution, cold, snapshots, inputs):
    output = directory / 'retained'
    saved, refs = {}, []

    def copied(relative):
        if relative not in saved:
            path = path_checked(output / relative, private=True)
            saved[relative] = artifact(path, directory, snapshots, 'retained-' + relative.replace('/', '-'))
        return saved[relative]

    def data(relative):
        return read_json(copied(relative)['path'])

    def reference(path, **options):
        row = retained_reference(path, directory, backend, **options)
        refs.append(row)
        return row

    cap = DEV['sequence_capability'](context, request['instance_identity'])
    retained_check(data('result.json') == execution, 'Backend result differs from its durable result.json')
    retained_check(execution.get('schema') == 'a7c2-retained-camera-test-v1' and
                   execution.get('status') == 'passed' and execution.get('actual_content_verified') is True and
                   execution.get('owners_closed') is True, 'Backend did not complete actual content and normal close')
    retained_check(execution.get('profile') == DEV['RETAINED_PROFILE'] and
                   execution.get('qemu_sha256') == DEV['RETAINED_QEMU_SHA'] and
                   execution.get('source_tree_sha256') == DEV['RETAINED_SOURCE_SHA'] and
                   execution.get('whole_device_audit_scope') == DEV['RETAINED_SCOPE'] and
                   execution.get('runtime_analysis') == cap['runtime_analysis'], 'Backend profile/scope/runtime differs')
    for name in ('full_device_audit_complete', 'full_boot_verified', 'sony_wbi_verified',
                 'hardware_ram_hotboot_verified', 'capture_verified', 'ui_hot_enabled',
                 'state_and_qmp_images_zero_race_coherent', 'display_under_one_second_verified',
                 'free_return_code_verified'):
        retained_check(execution.get(name) is False, 'Backend exceeded its verified scope: ' + name)
    retained_check(execution.get('vm_signals_sent') == [], 'Backend sent VM signals')
    launch = data('launch/launch.json')
    preflight = data('preflight.json')
    core = backend['C']
    source_bindings = backend['SOURCE_BINDINGS']
    retained_check(execution.get('source_bindings') == source_bindings == preflight.get('source_bindings'),
                   'Executed source bindings differ from the loaded backend')
    backend['COLD']['recheck'](source_bindings + launch['template_inputs'] + launch['launch_inputs'])
    for row in (execution['cold_manifest'], launch['cold_manifest_binding'], preflight['cold_manifest']):
        retained_check(all(row.get(k) == cap['cold_manifest'][k] for k in ('path', 'sha256')),
                       'Backend consumed a different cold manifest')
    retained_check(launch.get('instance') == cold['instance'] and
                   launch.get('runtime_analysis') == str(output / 'launch/runtime/analysis') and
                   launch.get('profile') == DEV['RETAINED_PROFILE'] and launch.get('incoming') is False and
                   launch.get('disk_source_class') == cold['source'] and
                   launch.get('source_class') == 'diagnostic-derived-retained-camera' and
                   launch.get('qemu_sha256') == DEV['RETAINED_QEMU_SHA'], 'Retained launch identity differs')
    retained_check(launch['combo_binding']['manifest'] == cap['combo_manifest']['path'] and
                   launch['combo_binding']['declared_topology'] == backend['L']['COMBO']['UPSTREAM_TOPOLOGY'] and
                   launch['source_firmware_contract'] == backend['P']['firmware_contract'](cold),
                   'Launch combo/topology/current firmware contract differs')
    script = artifact(launch['script'], directory, snapshots, 'retained-launch-script.txt', launch['script_sha256'])
    source_log = Path(copied('transaction/source-console.log')['path'])
    target_log = Path(copied('transaction/target/console.log')['path'])
    source_text, target_text = backend['console'](source_log), backend['console'](target_log)
    retained_check(not re.search(r'^(?:Linux version |COLD_BEFORE_ORIGINAL_INIT)', target_text, re.M),
                   'Target cold booted instead of resuming retained RAM')
    states = {phase: backend['parse_state'](source_text if phase == 'source' else target_text, phase)
              for phase in ('source', 'restored', 'menu', 'shooting')}
    source_run, target_run = execution['source_run'], execution['target_run']
    token = states['source']['canary']
    retained_check(source_run == 'retained-source-' + token and target_run == 'retained-target-' + token,
                   'Source/target run labels do not bind the new RAM nonce')
    for phase, state in states.items():
        retained_check(data(phase + '-state.json') == state, 'State JSON differs from actual console: ' + phase)
        log = source_text if phase == 'source' else target_text
        retained_check(log.splitlines().count('RETAINED_DONE_' + phase + '=' + token) == 1,
                       'Missing unique actual guest completion marker')
    retained_check(data('frame-state-observations.json') == states, 'Combined state receipt differs from console')
    trace = Path(copied('source-cold-trace.log')['path']).read_bytes()
    retained_check(source_log.read_bytes().startswith(trace),
                   'Final source console does not retain the original cold proof snapshot prefix')
    proof = backend['decode_cold_proof'](trace, token)
    retained_check(Path(copied('source-cold-proof.txt')['path']).read_bytes() == proof,
                   'Cold proof file differs from independent raw snapshot decode')
    collector_log = Path(copied('source-cold-collector.log')['path'])
    retained_check(collector_log.read_bytes() == trace + b'\n' + proof and
                   data('source-cold-proof.json') == backend['cold_proof_binding'](output, token, trace, proof) and
                   trace.splitlines().count(('RETAINED_DONE_diag=' + token).encode('ascii')) == 1,
                   'Cold proof/trace/collector bindings or unique guest completion differ')
    receipt = backend['E']['new_receipt']('original-init-cold', bindings={'run': source_run, 'source_class': cold['source']},
                                        kernel_cmdline=launch['cmdline'])
    coverage = backend['E']['collect'](collector_log, receipt)
    retained_check(coverage == data('source-cold-evidence.json') and coverage.get('ap_verified') is True and
                   coverage.get('cold_guest_chain_verified') is True and not receipt.get('observed_failures'),
                   'Strong source cold/AP collector did not verify the original chain')
    root = receipt.get('observed_mounts', {}).get('/', {})
    majors = re.findall(r'sony_persistent_flash: real durable MMIO DMA, major=(\d+) slices=19 base=0xb000000', source_text)
    capacities = re.findall(r'^PERSISTENT_CAPACITY node=([A-Za-z0-9]+) expected=(\d+) actual=(\d+)$', source_text, re.M)
    expected_capacities = cold['capacity_checks']
    retained_check(root.get('fs') == 'ext2' and root.get('source') in ('/dev/nflasha7', '/dev/pnflasha7') and
                   'ro' in root.get('options', []) and any(root.get('device') == major + ':135' for major in majors) and
                   re.search(r'^PERSISTENT_FLASH_INSMOD rc=0$', source_text, re.M) is not None and
                   len(capacities) == len(expected_capacities) == 20 and len({r[0] for r in capacities}) == 20 and
                   {name: int(expected) for name, expected, actual in capacities if expected == actual} == expected_capacities,
                   'Original guest persistent root/module/capacity readback differs')
    collector_text = backend['console'](collector_log)
    mapped = re.findall(r'^COLD_AP_MAP pid=(\d+) sha256=' + backend['E']['APPFW_SHA256'] + r'$', collector_text, re.M)
    retained_check(states['source']['ap_pids'][0] in mapped, 'Retained AP PID differs from live original mapped AP')
    frames = {}
    for phase in states:
        base = output / ('launch/run' if phase == 'source' else 'transaction/target')
        ppm = reference(base / (phase + '.ppm'), limit=1024 ** 2)
        pool = reference(base / (phase + '-scanout-pool.bin'), limit=backend['SCAN_BYTES'])
        frames[phase] = backend['pixel_review'](Path(ppm['path']).read_bytes(), Path(pool['path']).read_bytes())
        retained_check(lcd_pixels(Path(ppm['path'])), 'Original LCD is uniform or malformed')
    retained_check(frames == execution['frames'] == data('frame-pixels.json'), 'Frame pixel receipts differ from RAM/QMP')
    headers = backend['review_states'](states, frames, token)
    retained_check(headers == execution['headers'], 'Claimed frame headers differ from actual retained state')
    edges = {phase: backend['review_input'](backend['section'](target_text,
                 'RETAINED_DONE_' + ('restored' if phase == 'menu' else 'menu') + '=' + token,
                 'RETAINED_DONE_' + phase + '=' + token), phase) for phase in ('menu', 'shooting')}
    for phase, review in edges.items():
        retained_check(review == data(phase + '-input.json'), 'Input receipt differs from original receive/free edges')
    retained_check(execution.get('normal_input_received_edges') == 4 and execution.get('normal_input_free_enter_edges') == 4 and
                   execution.get('same_kernel_ram_canary_ap_viewer_pid_and_flocks') is True, 'Retained/input summary differs')
    ds = backend['DS']
    binding = data('transaction/disk-binding.json')
    ds['_validate'](binding, ds['BINDING_SCHEMA'])
    identity = request['instance_identity']
    retained_check(all(binding['disk'][k] == identity[v] for k, v in (('dev', 'dev'), ('ino', 'ino'), ('size', 'bytes'))) and
                   binding['disk_generation'] == identity['generation'] and binding['geometry'] == cold['instance_geometry'] and
                   binding['metadata']['geometry']['sha256'] == identity['geometry_sha256'] and
                   binding['source_class'] == cold['source'] and
                   binding['source_manifest_sha256'] == cold['instance_source_manifest_sha256'] and
                   binding['canonical_wire']['sha256'] == cold['instance_wire_sha256'], 'Disk binding is another instance/generation')
    retained_check(binding['transaction']['parent_pid'] == os.getpid() and
                   binding['capture']['host_run'] == source_run and binding['capture']['migration_generation'] == 0,
                   'Disk transaction belongs to another source/controller')
    binding_sha = core['R']['_digest'](binding)
    phases = []
    for index, phase in enumerate(ds['PHASES']):
        row = data('transaction/disk-' + phase + '.json')
        expected_state = ds['STATES'][index]
        retained_check(row.get('phase') == phase and row.get('disk_binding_verified') is True and
                       row.get('binding_sha256') == binding_sha and row.get('disk_generation') == identity['generation'] and
                       row.get('host_run') == (source_run if index < 2 else target_run) and
                       row.get('migration_generation') == (0 if index < 2 else 1) and row.get('whole_machine_verified') is False,
                       'Missing/false/cross-run disk phase: ' + phase)
        statuses = [r['response'] for r in row['qmp'] if r['command'] == 'query-status']
        retained_check(len(statuses) >= 2 and all(r.get('running') is False and r.get('status') == expected_state for r in statuses),
                       'Disk phase actual paused/postmigrate/inmigrate state differs')
        if index == 1:
            migrations = [r['response'] for r in row['qmp'] if r['command'] == 'query-migrate']
            retained_check(len(migrations) >= 2 and all(r.get('status') == 'completed' for r in migrations),
                           'Outgoing source has not actually completed migration')
        phases.append(copied('transaction/disk-' + phase + '.json'))
    captured, restored = data('capture-result.json'), data('restore-paused-result.json')
    continued, closed = data('transaction/continued.json'), data('normal-close.json')
    retained_check(data('transaction/execution-closed.json') == closed and
                   data('transaction/restore-paused.json') == restored, 'Core execution receipts differ from durable copies')
    retained_check(captured['status'] == 'captured-source-postmigrate' and restored['status'] == 'restored-paused' and
                   continued['status'] == closed['status'] == 'continued-awaiting-new-guest-evidence' and
                   continued.get('retained_cpu_resumed') is True and closed.get('owners_closed') is True,
                   'Capture/paused restore/continue/normal close not completed')
    for row in (captured, restored, continued, closed):
        retained_check(row['schema'] == 'a7c2-retained-camera-execution-v1' and row['source_run'] == source_run and
                       row['disk_binding_sha256'] == binding_sha and row['source_identity'] == captured['source_identity'] and
                       row['device_audit'] == captured['device_audit'] and row['profile'] == DEV['RETAINED_PROFILE'] and
                       row['external_state'] == core['EXTERNAL'] and row.get('capture_verified') is False and
                       row.get('whole_machine_verified') is False and row.get('cold_fallback_allowed') is False,
                       'Core capture/restore binding drifted')
    retained_check(all(row['migration_outgoing']['status'] == 'completed' for row in (captured, restored, closed)) and
                   all(row['migration_incoming']['status'] == 'completed' for row in (restored, closed)), 'Migration did not complete both directions')
    audit = closed['device_audit']
    retained_check(audit['type_counts'] == core['SOURCE_COUNTS'] and audit['profile'] == DEV['RETAINED_PROFILE'] and
                   audit['qemu_sha256'] == DEV['RETAINED_QEMU_SHA'] and audit['source_tree_sha256'] == DEV['RETAINED_SOURCE_SHA'] and
                   audit['kind'] == core['AUDIT_KIND'] and audit['external_state'] == core['EXTERNAL'], 'Declared device audit differs')
    stream = reference(output / 'transaction/snapshot.partial', expected=closed['snapshot_sha256'], record=closed['snapshot_file_record'])
    retained_check(stream['bytes'] == closed['snapshot_bytes'] and all(
        all(row[k] == closed[k] for k in ('snapshot_sha256', 'snapshot_bytes', 'snapshot_file_record'))
        for row in (captured, restored, continued)), 'Completed RAM stream identities differ')
    sync = binding['capture']['guest_sync']
    sync_ref = reference(Path(sync['path']), expected=sync['evidence']['sha256'], record={k: v for k, v in sync['evidence'].items() if k != 'sha256'}, limit=1024 ** 2)
    retained_check(Path(sync['path']) == output / 'transaction/guest-sync.console' and
                   Path(sync_ref['path']).read_bytes().splitlines().count(sync['marker'].encode('ascii')) == 1 and
                   source_text.splitlines().count(sync['marker']) == 1 and
                   captured['guest_sync']['nonce'] == sync['nonce'], 'Actual guest sync/nonce is missing')
    owners = []
    for side in ('source', 'target'):
        proc = closed[side + '_identity']
        retained_check(side == 'source' or (proc == restored['target_identity'] == continued['target_identity'] and
                       restored['target_run'] == continued['target_run'] == closed['target_run'] == target_run), 'Target identity/run drift')
        retained_check(proc['owner']['parent_pid'] == os.getpid() and all(
            type(proc[k].get('pid')) is int and type(proc[k].get('start_ticks')) is int and
            proc[k]['pid'] > 0 and proc[k]['start_ticks'] > 0 and proc[k].get('uid') == os.getuid() for k in ('owner', 'peer')),
            'Source/target process identity is incomplete')
        retained_check(all(proc['environment'].get(k) == v for k, v in backend['L']['UPSTREAM_USB'].items()) and
                       proc['version']['qemu'] == {'major': 11, 'minor': 1, 'micro': 2} and
                       proc['memory']['base-memory'] == 24576 * 1024 ** 2,
                       'Actual process binary version/RAM/upstream-only USB contract differs')
        retained_check([row for row in proc['options'] if row[0] == '--bind' and row[2] == '/instance'] ==
                       [['--bind', cold['instance'], '/instance']], 'Actual process binds another instance')
        retained_check(all(proc['environment'].get(k) == str(v) for k, v in {
            'QEMU_A7PF_FD': binding['transaction']['fd'], 'QEMU_A7PF_DEV': identity['dev'],
            'QEMU_A7PF_INO': identity['ino'], 'QEMU_A7PF_RETAINED_STATE': 1}.items()) and
            proc['environment']['QEMU_A7PF_PROFILE'] == DEV['RETAINED_PROFILE'], 'Actual process inherited a different disk FD/profile')
        for kind in ('owner', 'peer'):
            saved_proc = proc[kind]
            try:
                now = core['_proc_identity'](saved_proc['pid'])
            except FileNotFoundError:
                continue
            retained_check(now['start_ticks'] != saved_proc['start_ticks'], 'Owned source/target process is still alive')
        owners.append(proc['owner']['pid'])
    retained_check(len({closed[s + '_identity'][k]['pid'] for s in ('source', 'target') for k in ('owner', 'peer')}) == 4,
                   'Target must be a new owner and QMP peer process')
    exits = closed['owners']
    retained_check([row['pid'] for row in exits] == owners and all(type(row.get('returncode')) is int and row['returncode'] == 0 and
                   row.get('signals_sent') == [] and row.get('quit_response') == {} for row in exits), 'Owners did not normally QMP quit')
    retained_check(captured['owners'] == restored['owners'] == [exits[0]], 'Source was not normally exited before target restore')
    admitted = data('transaction/target-admission.json')
    retained_check(admitted['transaction'] == binding['transaction'] and admitted['disk_binding_sha256'] == binding_sha and
                   admitted['snapshot_sha256'] == stream['sha256'] and admitted['run'] == target_run and
                   admitted['disk_generation'] == identity['generation'] and admitted['migration_generation'] == 1,
                   'Target admission is not bound to the current completed source')
    # Recheck in-place data after parsing/decoding; retain one private copy of small receipts only.
    for row in refs:
        retained_reference(row['path'], directory, backend, expected=row['sha256'], record=row['file_record'])
    unchanged(request, context)
    DEV['sequence_capability'](context, identity)
    stages = {}
    details = {'original_init_cold': {'collector': coverage, 'script': script},
               'system_runtime': {'headers': headers, 'frames': frames, 'original_input': edges},
               'persistent_device': {'disk_binding': copied('transaction/disk-binding.json'), 'four_phases': phases,
                                     'guest_root': root, 'capacity_checks': expected_capacities},
               'retained_device_audit': {'scope': DEV['RETAINED_SCOPE'], 'declared_topology_audit_verified': True,
                                         'full_device_audit_complete': False, 'audit': audit},
               'retained_restore': {'model': 'explicit QEMU RAM save/restore; original guest continues',
                                     'stream': stream, 'normal_close': copied('normal-close.json')}}
    for name in STAGES['sequence']:
        path = snapshots / (name + '.json')
        write_json(path, {k: request[k] for k in ('schema', 'job_id', 'run_id', 'action', 'instance_identity')} |
                   {'stage': name, 'verified': True, 'inputs': inputs, 'source_class': cold['source'],
                    'raw_receipts': saved, 'in_place_evidence': refs, 'sony_wbi_verified': False,
                    'hardware_hotboot_verified': False, 'capture_verified': False, **details[name]})
        stages[name] = {'verified': True, 'execution_kind': 'persistent_device' if name in DEV['PERSISTENT_STAGES'] else 'guest_original',
                        'path': str(path), 'sha256': sha(path)}
    return stages


def execute_sequence(directory, request, context, snapshots, result):
    cap = DEV['sequence_capability'](context, request['instance_identity'])
    backend = runpy.run_path(str(HERE / 'retained-camera-test.py'))
    cold = read_json(cap['cold_manifest']['path'])
    instance_dir, state, geometry, source_known = current(context, request['instance_identity'])
    retained_check(cold.get('profile') == backend['P']['PROFILE'] and cold.get('build_verified') is True and
                   cold.get('instance') == str(instance_dir) and cold.get('instance_generation') == request['instance_identity']['generation'] and
                   cold.get('instance_geometry') == geometry and cold.get('source') == state['source_class'] and
                   cold.get('instance_source_manifest_sha256') == state['source_manifest_sha256'] and
                   cold.get('prepared_runtime_analysis') == cap['runtime_analysis'] and cold.get('partition_images_in_ram0') == 0 and
                   cold.get('instance_wire') == str(instance_dir / 'persistent-geometry.bin') and
                   cold.get('instance_wire_sha256') == sha(instance_dir / 'persistent-geometry.bin'),
                   'Prepared cold manifest is not the current explicit instance/firmware/wire')
    backend['P']['firmware_contract'](cold)
    backend['P']['current_kernel_binding'](cold['actual_kernel'])
    retained_check(cold['block_module']['sha256'] == cap['persistent_module']['sha256'] == sha(cold['block_module']['path']),
                   'Cold guest module differs from the explicitly bound module')
    for name, expected in (('/bin/bootin.elf', backend['E']['BOOTIN_SHA256']), ('/lib/appFw.so', backend['E']['APPFW_SHA256'])):
        retained_check(cold['native_elf_identity'][name]['sha256'] == expected, 'Cold manifest does not bind stock bootin/AP')
    backend['metadata'](instance_dir)  # No chmod; the backend repeats this under its own transaction.
    output = directory / 'retained'
    if os.path.lexists(output):
        refuse('result_exists', 'Retain previous retained output; every sequence needs a new directory')
    bindings = {name: {'path': str(HERE / name), 'sha256': sha(HERE / name)} for name in
                ('firmware-boot-request.py', 'firmware-development.py', 'boot-session.py')}
    inputs_path = snapshots / 'sequence-inputs.json'
    write_json(inputs_path, {'request_sha256': sha(directory / 'request.json'), 'capability': cap,
                            'controller_sources': bindings, 'source_bindings': backend['SOURCE_BINDINGS'],
                            'reference_proof_sha256': sha(DEV['RETAINED_PROOF']), 'reference_report_sha256': sha(DEV['RETAINED_REPORT'])})
    inputs = {'path': str(inputs_path), 'sha256': sha(inputs_path)}
    unchanged(request, context)
    result.update(source_known=source_known, execution_started=True)
    execution = backend['run'](Path(cap['runtime_analysis']), Path(cap['cold_manifest']['path']), output,
                               combo_manifest=Path(cap['combo_manifest']['path']), origin_qemu_build=Path(cap['origin_qemu_build']))
    for binding in bindings.values():
        DEV['checked_binding'](binding)
    sealed_inputs = read_json(inputs_path)
    retained_check(sha(inputs_path) == inputs['sha256'] and
                   sha(path_checked(directory / 'request.json', private=True)) == sealed_inputs['request_sha256'],
                   'Current request/input receipt changed during execution')
    unchanged(request, context)
    result['stages'] = retained_stage_evidence(directory, request, context, backend, execution, cold, snapshots, inputs)
    if any(result['stages'].get(name, {}).get('verified') is not True for name in STAGES['sequence']):
        refuse('true_required_stage_unverified', 'Every required sequence stage must be verified')
    result.update(status='completed', message='Original cold init and fixed QEMU retained RAM roundtrip verified',
                  declared_topology_audit_verified=True, full_device_audit_complete=False,
                  sony_wbi_verified=False, hardware_hotboot_verified=False, full_boot_verified=False,
                  qemu_retained_roundtrip_verified=True)


def execute_hot(directory, request, context, snapshots, result):
    """Keep an explicitly attached frontend live; headless validation closes normally."""
    cap = DEV['hot_capability'](context, request['instance_identity'])
    backend = DEV['live_module']()
    descriptor = backend.inspect_owner(cap['live_owner'], request['instance_identity'])
    retained_check(type(descriptor.get('frontend_enabled')) is bool, 'Live frontend flag must be explicit bool')
    sources = {name: {'path': str(HERE / name), 'sha256': sha(HERE / name)} for name in
               ('firmware-boot-request.py', 'firmware-development.py', 'boot-session.py')}
    inputs = dict(request_sha256=sha(directory / 'request.json'), capability=cap,
                  controller_identity=descriptor['controller_identity'], frontend_enabled=descriptor['frontend_enabled'],
                  controller_sources=sources)
    inputs_path = snapshots / 'live-inputs.json'
    write_json(inputs_path, inputs)
    inputs_binding = dict(path=str(inputs_path), sha256=sha(inputs_path))
    unchanged(request, context)
    result.update(execution_started=True, source_known=True)
    def record_failure(action, error, state=None):
        state = error.state if isinstance(error, backend.LiveRequestRefused) else state
        write_json(snapshots / ('live-' + action + '-error.json'),
                   dict(type=type(error).__name__, error=str(error), state=state))
        result.update(owner_retained=bool(state['live_owner_pids']) if state is not None else None,
                      owner_state_confirmed=state is not None, live_state=state, live_owner=cap['live_owner'],
                      lease_retained_until_owner_exit=True, vm_signals_sent=[])
    try:
        hot = backend.request(cap['live_owner'], request['instance_identity'], 'hot')
        write_json(snapshots / 'live-hot-response.json', hot)
    except Exception as error:
        record_failure('hot', error)
        raise  # Preserve failed/uncertain RAM and owner; main explicitly closes after preservation.
    if descriptor['frontend_enabled']:
        try:
            reviewed = backend.verify_active_result(cap['live_owner'], request['instance_identity'], hot)
        except Exception as error:
            record_failure('active-review', error, hot['result']['state'])
            raise
        lifecycle = 'live-target-owned'
    else:
        try:
            close = backend.request(cap['live_owner'], request['instance_identity'], 'close')
            write_json(snapshots / 'live-close-response.json', close)
        except Exception as error:
            record_failure('close', error)
            raise
        reviewed = backend.verify_result(close['result']['artifact'], request['instance_identity'], descriptor['controller_identity'])
        lifecycle = 'closed'
    result.update(lifecycle=lifecycle, owners_closed=not descriptor['frontend_enabled'],
                  owner_retained=descriptor['frontend_enabled'], owner_state_confirmed=True,
                  live_state=hot['result']['state'] if descriptor['frontend_enabled'] else close['result']['state'],
                  live_owner=cap['live_owner'], lease_retained_until_owner_exit=descriptor['frontend_enabled'],
                  runtime_transport_verified=descriptor['frontend_enabled'], vm_signals_sent=[])
    for source in sources.values():
        DEV['checked_binding'](source)
    DEV['checked_binding'](inputs_binding, private=True)
    retained_check(sha(directory / 'request.json') == inputs['request_sha256'], 'Live request changed during execution')
    unchanged(request, context)
    for stage in STAGES['hot']:
        path = snapshots / (stage + '.json')
        contents = {key: request[key] for key in ('schema', 'job_id', 'run_id', 'instance_identity', 'action')}
        contents.update(stage=stage, verified=True, live_review=reviewed, inputs=inputs_binding,
                        lifecycle=lifecycle, owners_closed=result['owners_closed'],
                        runtime_transport_verified=result['runtime_transport_verified'],
                        lease_retained_until_owner_exit=result['lease_retained_until_owner_exit'],
                        live_owner=cap['live_owner'], controller_identity=descriptor['controller_identity'],
                        sony_wbi_verified=False, hardware_hotboot_verified=False, capture_verified=False,
                        gui_owner_switch_verified=False)
        write_json(path, contents)
        result['stages'][stage] = dict(verified=True, path=str(path), sha256=sha(path),
            execution_kind='persistent_device' if stage in DEV['PERSISTENT_STAGES'] else 'guest_original')
    result.update(status='completed', message=('Live original owner QEMU roundtrip verified; target retained for the same GUI'
                  if descriptor['frontend_enabled'] else 'Live original owner QEMU roundtrip and typed normal close verified'),
                  declared_topology_audit_verified=True, qemu_retained_roundtrip_verified=True,
                  gui_owner_switch_verified=False)


def selected_module(context):
    binding=context.get('available_capabilities',{}).get('cold',{}).get('persistent_module')
    if binding is None:return None
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'} or not re.fullmatch('[0-9a-f]{64}',str(binding.get('sha256',''))):
        refuse('module_binding','Cold capability needs an explicit module path/SHA256 binding')
    path=path_checked(binding['path'])
    if sha(path)!=binding['sha256']:refuse('module_changed','Selected persistent module differs from the capability')
    return {'path':path,'sha256':binding['sha256']}


def execute(request_path):
    """Return a bound receipt; only a validated fresh private job receives a file."""
    started = time.time_ns()
    request = {}
    result = {'schema': SCHEMA, 'status': 'blocked', 'stages': {}, 'physical_devices_used': False,
              'capture_verified': False, 'hot_verified': False, 'update_verified': False, 'source_known': False,
              'sony_wbi_verified': False, 'hardware_hotboot_verified': False, 'full_boot_verified': False,
              'full_device_audit_complete': False, 'declared_topology_audit_verified': False,
              'qemu_retained_roundtrip_verified': False, 'ui_hot_enabled': False,
              'started_ns': started}
    directory = result_path = snapshots = None
    claimed = None
    try:
        request_path = path_checked(request_path, private=True)
        request = read_json(request_path)
        result.update({key: request.get(key) for key in ('job_id', 'run_id', 'action', 'instance_identity', 'required_stages')})
        context, directory, result_path = envelope(request_path, request)
        fd = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        claimed = DEV['_identity'](os.fstat(fd))
        os.close(fd)
        action = request.get('action')
        names = STAGES.get(action, ()) if isinstance(action, str) else ()
        result['stages'] = {name: {'verified': False, 'execution_kind': 'persistent_device' if name in DEV['PERSISTENT_STAGES'] else 'guest_original'}
                            for name in names}
        instance_dir, camera_profile, qemu_build = validate(request, context)
        snapshots = directory / 'stage-evidence'
        snapshots.mkdir(mode=0o700)
        if action == 'sequence':
            execute_sequence(directory, request, context, snapshots, result)
            return finish_result(result, result_path, claimed)
        if action == 'hot':
            execute_hot(directory, request, context, snapshots, result)
            return finish_result(result, result_path, claimed)
        persistent = runpy.run_path(str(HERE / 'persistent-boot.py'))
        # This independently revalidates the real disk schema/label under its native lifecycle lock.
        with persistent['DISK']['lease'](instance_dir) as leased:
            _, _, _, source_known = current(context, request['instance_identity'], leased['fd'])
        result['source_known'] = source_known
        unchanged(request, context)
        boot = runpy.run_path(str(HERE / 'boot-session.py'))
        module=selected_module(context)
        args = argparse.Namespace(runtime=Path(request['runtime']), instance=instance_dir,
                                  output=directory / 'cold-session', profile='original-init-cold',
                                  camera_profile=camera_profile, qemu_build=qemu_build, seconds=120,
                                  dump=None, predicates=None, persistent_module=module['path'] if module else None, functional_install=False)
        output, state = boot['prepare'](args)
        if output != args.output or state.get('backend') != 'original-init-with-persistent-device' or state.get('state') != 'prepared':
            refuse('persistent_backend', 'Original persistent cold backend was not prepared')
        unchanged(request, context)
        cold = state['cold_chain']
        if module and cold.get('block_module',{}).get('sha256')!=module['sha256']:
            refuse('module_changed','Built guest module differs from the cold capability binding')
        _, state_now, geometry, _ = current(context, request['instance_identity'])
        if (cold.get('instance') != str(instance_dir) or cold.get('instance_generation') != request['instance_identity']['generation'] or
                cold.get('instance_geometry') != geometry or cold.get('source') != state_now['source_class'] or
                cold.get('instance_source_manifest_sha256') != state_now['source_manifest_sha256'] or
                cold.get('partition_images_in_ram0') != 0 or cold.get('build_verified') is not True):
            refuse('instance_changed', 'Persistent build identity does not match this instance/generation')
        options = {'camera_profile': camera_profile}
        if qemu_build is not None:
            options['qemu_build'] = qemu_build
        launch = persistent['prepare_launch'](Path(request['runtime']) / 'analysis', cold, output / 'launch', **options)
        executor = runpy.run_path(str(HERE / 'boot-execution.py'))
        state.update(state='running', launch=launch)
        write_json(output / 'session.json', state)
        with persistent['leased_launch'](launch) as bound:
            unchanged(request, context)
            _, _, _, source_known = current(context, request['instance_identity'], bound['fd'])
            info = os.fstat(bound['fd'])
            env = bound['env']
            if (bound.get('instance') != str(instance_dir) or bound['fd'] not in bound.get('pass_fds', ()) or
                    env.get('PERSISTENT_INSTANCE') != str(instance_dir) or
                    any(env.get('PERSISTENT_DISK_' + key) != str(value) for key, value in
                        (('FD', bound['fd']), ('DEV', info.st_dev), ('INO', info.st_ino)))):
                refuse('lease_binding', 'Launch does not inherit the same leased instance FD')
            fd_binding = {'verified': True, 'source_known': source_known, 'dev': info.st_dev, 'ino': info.st_ino,
                          'bytes': info.st_size, 'instance_identity': request['instance_identity'],
                          'guest_root_mapping': 'sony-persistent-flash selector7 minor135 on this inherited FD'}
            execution = executor['run'](bound, cold, output / 'evidence', seconds=120)
            current(context, request['instance_identity'], bound['fd'])
            unchanged(request, context)
        result['execution'] = execution
        state.update(state='finished', execution=execution)
        write_json(output / 'session.json', state)
        result['stages'] = stage_evidence(directory, request, execution, cold, launch, executor, fd_binding, snapshots)
        missing = [name for name in STAGES['cold'] if result['stages'][name]['verified'] is not True]
        if missing:
            result['first_blocking_reason'] = missing[0]
            refuse('true_required_stage_unverified', missing[0] + ': original required stage is unverified')
        result.update(status='completed', message='Original cold init, AP/LCD and same-instance persistent device verified')
    except Exception as error:
        result.update(status='blocked' if isinstance(error, Blocked) and not result.get('execution_started') else 'failed',
                      blocked_reason={'code': getattr(error, 'code', 'backend_error'), 'detail': str(error)},
                      error={'type': type(error).__name__, 'detail': str(error), 'traceback': traceback.format_exc()})
        result.setdefault('first_blocking_reason', str(error))
        if snapshots is not None:
            # Preserve executor's original rc/log/error even when run() raised after cleanup.
            if request.get('action') == 'sequence':
                for relative in ('failure.json', 'owner-retained.json', 'source-owner-start.json', 'normal-close.json',
                                 'result.json', 'source-cold-proof.json', 'source-cold-proof.txt', 'source-cold-trace.log',
                                 'source-cold-collector.log', 'source-cold-evidence.json',
                                 'transaction/source-console.log', 'transaction/target/console.log'):
                    path = directory / 'retained' / relative
                    if path.exists():
                        try:
                            saved = artifact(path, directory, snapshots, 'failed-retained-' + relative.replace('/', '-'))
                            result.setdefault('failure_evidence', []).append(saved)
                        except Exception as evidence_error:
                            result.setdefault('evidence_errors', []).append(str(evidence_error))
            for relative, name in (('evidence/boot-flow.json', 'failed-boot-flow.json'),
                                   ('evidence/console.log', 'failed-console.log'),
                                   ('evidence/owner-exit.json', 'failed-owner-exit.json'),
                                   ('session.json', 'failed-session.json')):
                path = directory / 'cold-session' / relative
                if path.exists():
                    try:
                        saved = artifact(path, directory, snapshots, name)
                        result.setdefault('failure_evidence', []).append(saved)
                    except Exception as evidence_error:
                        result.setdefault('evidence_errors', []).append(str(evidence_error))
    return finish_result(result, result_path, claimed)


def finish_result(result, result_path, claimed):
    result['finished_ns'] = time.time_ns()
    if claimed is not None:
        try:
            if DEV['_identity'](path_checked(result_path, private=True).stat()) != claimed:
                refuse('result_changed', 'Controller receipt reservation changed; refusing overwrite')
            write_json(result_path, result)
        except Exception as error:
            result.update(status='blocked', blocked_reason={'code': getattr(error, 'code', 'receipt_write_failed'),
                          'detail': str(error)}, first_blocking_reason=str(error))
    return result
