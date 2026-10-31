"""Host C effects and offline replay tests; never starts/accesses a VM or socket."""
# SPDX-License-Identifier: MIT
import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from types import SimpleNamespace

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_hdmi_edge as v
from test_pinmem_hdmi_video_connection import video_connection_binary, ENV
from test_adf_set_input_device import public_adf_input_seed
from initramfs_identity import verify_image


class Log:
    """Same record schema as the parent checker, without importing its build pins."""
    def __init__(self, text):
        self.records = []
        for line, text in enumerate(text.splitlines(), 1):
            match = re.search(r'(?:^|\bOBS )((?:FULL_|HDMI_|RCV_|PIN_)\w+) (.*)', text)
            if match:
                self.records.append(dict(line=line, tag=match[1], raw=text,
                    fields=dict(re.findall(r'(\w+)=([^\s]+)', match[2]))))

    def rows(self, tag):
        return [r for r in self.records if r['tag'] == tag]


def make_scope_binding(tmp_path, monkeypatch, version):
    """Synthetic provenance only: no real run, source archive, image, VM or AP transaction."""
    path = BASE.parents[1] / 'report/functional-graph-evidence/check_graph.py'
    spec = importlib.util.spec_from_file_location('_synthetic_binding_graph_reader', path)
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)
    native = tmp_path / 'synthetic-native'
    monkeypatch.setattr(graph, 'NATIVE', native)
    run, work = tmp_path / 'synthetic-run', tmp_path / 'synthetic-once'
    run.mkdir(); work.mkdir()
    write = lambda p, value: p.write_bytes(json.dumps(value, sort_keys=True).encode())
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    digest = 'a' * 64
    source_root = native / ('report/2026-10-31-qemu-M-writer-observer-v3' if version == 3 else
                           'report/2026-10-30-qemu-readonly-scope-observer')
    source_names = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh', f'log-schema-v{version}.json',
        f'source-contract-v{version}.json', f'check_run_context_v{version}.py', 'check_run_context.py',
        f'integration/scope_trace_checks_v{version}.py', 'integration/scope_trace_checks.py')
    sources = {}
    for name in source_names:
        source = source_root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(('synthetic source only: ' + name).encode())
        sources[name] = sha(source)
    metadata = dict(profile=f'qemu-readonly-scope-v{version}', trace_schema=f'readonly_scope_v{version}',
        build_receipt=str(work / 'synthetic-build-receipt.json'), build_receipt_sha256=digest,
        library_sha256=digest, qemu_sha256=digest, qemu_header_sha256=digest,
        trace_schema_sha256=digest, source_contract_sha256=digest,
        source_sha256=sources, identity_binding='unverified', capture_verified=False,
        physical_asic_compatibility_verified=False)
    expected = dict(metadata, build_metadata=metadata, source_root=str(source_root),
        original_appfw_sha256=digest, Main_source_sha256=digest,
        functional_runner_source_sha256=digest)
    reference = dict(path=str(work / 'synthetic-receipt.json'), sha256=digest)
    binding = dict(schema=f'functional-M-v{version}-run-v{version}', run=str(run), nonce=42,
        batch=str(tmp_path / 'synthetic-batch'), batch_ready_sha256=digest, observer_sha256=digest,
        guest_sha256=digest, candidate_qemu=dict(path=str(tmp_path / 'synthetic-qemu'), sha256=digest),
        card=dict(path=str(tmp_path / 'synthetic-card'), device=1, inode=2, initially_empty=True),
        runtime_ready=dict(reference), parent_readback=dict(reference), fresh_guest={},
        runtime_assets_sha256={}, scope_observer_expected=expected, synthetic_fixture_manifest=dict(reference),
        actual_api_contract=dict(reference), intent_sha256=digest, launch_binding_sha256=digest,
        claimed_fault_result='FAIL', popen_live_sha256=digest,
        **dict.fromkeys(v.SCOPE_FALSE_FIELDS, False))
    guest = work / 'synthetic-guest.cpio'
    compiled = {str(BASE / 'menu-observe.so'): digest}
    fresh_path = work / 'fresh-public-guest.json'
    write(fresh_path, dict(guest_image=str(guest), guest_sha256=digest, ready_sha256=digest,
        runtime_ready_sha256=digest, returncode=0, compiled3_unchanged=True, capture_verified=False,
        compiled_before=compiled, compiled_after=compiled))
    binding['fresh_guest'] = dict(path=str(fresh_path), sha256=sha(fresh_path))
    fields = v.SCOPE_PLAN_FIELDS + ('observer_sha256', 'guest_sha256', 'candidate_qemu', 'card')
    common = {key: copy.deepcopy(binding[key]) for key in fields}
    common.update(plan=str(work / 'plan.json'), plan_sha256=digest, claimed_fault_result='FAIL',
                  **dict.fromkeys(v.SCOPE_FALSE_FIELDS, False))
    write(work / 'intent.json', dict(common, schema=f'functional-M-v{version}-intent-v{version}', guest_image=str(guest)))
    binding['intent_sha256'] = sha(work / 'intent.json')
    write(work / 'launch-binding.json', dict(common, schema=f'functional-M-v{version}-launch-v{version}',
        intent_sha256=binding['intent_sha256']))
    binding['launch_binding_sha256'] = sha(work / 'launch-binding.json')
    plan_binding = {key: copy.deepcopy(binding[key]) for key in v.SCOPE_PLAN_FIELDS}
    scope = dict(metadata, library=str(run / 'readonly-scope-observer.so'),
        log=str(run / 'readonly-scope-trace.log'), plan_binding=plan_binding)
    manifest = dict(probe_args=dict(initramfs_file=str(guest)), readonly_scope_observer=scope,
        selected_initramfs_verified_files={'usr/lib/appFw.so': digest},
        files={str(guest): digest, binding['candidate_qemu']['path']: digest},
        backup_transport=dict(binary=binding['candidate_qemu']['path'], binary_sha256=digest))
    build = dict(sources={str(BASE / 'menu-observe.c'): dict(sha256=digest)})
    tested = dict(groups=dict(production={str(BASE / 'menu-observe.c'): digest},
        host={str(BASE / 'functional_camera_runner.py'): digest},
        observer={str(source_root / name): value for name, value in sources.items()}, test={}))
    info = run.stat()
    context = dict(schema=f'functional-M-v{version}-live-context-v{version}', run=str(run), run_device=info.st_dev,
        run_inode=info.st_ino, scope=plan_binding, **{key: copy.deepcopy(binding[key]) for key in
        ('nonce', 'batch', 'batch_ready_sha256', 'intent_sha256', 'launch_binding_sha256', 'candidate_qemu', 'card')})
    live_path = run / 'readonly-scope-popen-live.json'
    write(live_path, dict(schema=f'functional-M-v{version}-popen-live-v{version}', context=context,
        **dict.fromkeys(v.SCOPE_FALSE_FIELDS, False)))
    binding['popen_live_sha256'] = sha(live_path)
    write(run / 'readonly-scope-run-binding.json', binding)
    return SimpleNamespace(graph=graph, reader=SimpleNamespace(typed_equal=graph.profile_value_equal),
        run=run, work=work, binding=binding, observer=digest, manifest=manifest, build=build,
        tested=tested, guest=guest, write=write, sha=sha, version=version)


@pytest.fixture(params=(2, 3))
def synthetic_scope_binding(tmp_path, monkeypatch, request):
    return make_scope_binding(tmp_path, monkeypatch, request.param)


@pytest.fixture
def synthetic_shutter_binding(tmp_path, monkeypatch):
    """HOST_METADATA only: public source bytes and owned fake artifacts, never a QEMU/API result."""
    f = make_scope_binding(tmp_path, monkeypatch, 2)
    native = BASE.parents[1]
    monkeypatch.setattr(f.graph, 'NATIVE', native)
    f.reader.object_json = f.graph.object_json
    root = native / v.SHUTTER_GATE_COMPONENT
    sources = {name: f.sha(root / name) for name in v.SHUTTER_GATE_SOURCE_NAMES}
    fixtures = {name: f.sha(root / name) for name in v.SHUTTER_GATE_FIXTURE_NAMES}
    plugin = f.work / 'HOST_METADATA-plugin'
    candidate = f.work / 'HOST_METADATA-candidate'
    plugin.mkdir(); (candidate / 'build').mkdir(parents=True)
    library, binary = plugin / 'scope-observer.so', candidate / 'build/qemu-system-aarch64'
    library.write_bytes(b'HOST_METADATA raw library bytes; not an executable ELF or actual API build\n')
    binary.write_bytes(b'HOST_METADATA inert QEMU file bytes; never executed\n')
    command = plugin / 'plugin-build-command.json'
    import_audit = plugin / 'readonly-import-audit.json'
    static_audit = candidate / 'binary-static-audit.json'
    f.write(command, dict(evidence_kind='HOST_METADATA', command=[], executed=False))
    f.write(import_audit, dict(evidence_kind='HOST_METADATA', imports=[], executed=False))
    f.write(static_audit, dict(evidence_kind='HOST_METADATA', binary=str(binary), binary_sha256=f.sha(binary),
        missing_required_exports=[], protected_binaries_unchanged=dict(candidate=True, production=True),
        runtime_library_closure_verified=False, plugin_runtime_verified=False,
        capture_verified=False, physical_asic_compatibility_verified=False))
    header_sha = hashlib.sha256(b'HOST_METADATA no QEMU header imported').hexdigest()
    receipt_path = plugin / 'build-receipt.json'
    built = dict(schema=v.SHUTTER_GATE_PROFILE, evidence_kind='HOST_METADATA', library=str(library),
        library_sha256=f.sha(library), qemu=str(binary), qemu_sha256=f.sha(binary), qemu_header_sha256=header_sha,
        source_sha256=copy.deepcopy(sources), fixture_source_sha256=copy.deepcopy(fixtures),
        trace_schema='readonly_shutter_gate_v1', trace_schema_sha256=sources['log-schema-shutter-gate-v1.json'],
        source_contract_sha256=sources['source-contract-shutter-gate-v1.json'],
        plugin_build_command_sha256=f.sha(command), readonly_import_audit_sha256=f.sha(import_audit),
        candidate_static_audit_sha256=f.sha(static_audit))
    f.write(receipt_path, built)
    ref = dict(path=str(receipt_path), sha256=f.sha(receipt_path))
    metadata = {key: copy.deepcopy(value) for key, value in built.items()
                if key not in ('schema', 'evidence_kind', 'qemu')}
    metadata.update(profile=v.SHUTTER_GATE_PROFILE, build_receipt=ref['path'], build_receipt_sha256=ref['sha256'],
        identity_binding='unverified', capture_verified=False, physical_asic_compatibility_verified=False)
    # Only external artifact validation is substituted; metadata mutations cannot rewrite this operand.
    frozen_metadata = copy.deepcopy(metadata)
    validate_calls = []
    def validate_build(actual_native, actual_receipt, actual_qemu):
        assert actual_native == native == BASE.parents[1]
        assert actual_receipt == ref['path'] and actual_qemu == str(binary)
        validate_calls.append((actual_native, actual_receipt, actual_qemu))
        return copy.deepcopy(frozen_metadata)
    source_module = f.graph.source_module
    def scoped_source_module(relative, frozen):
        if relative == 'runtime/analysis/scope_observer_profile.py':
            path = native / relative
            assert frozen[str(path)] == f.sha(path)
            return SimpleNamespace(validate_build=validate_build)
        return source_module(relative, frozen)
    monkeypatch.setattr(f.graph, 'source_module', scoped_source_module)
    observer = hashlib.sha256(b'HOST_METADATA observer, never loaded').hexdigest()
    appfw = hashlib.sha256(b'HOST_METADATA original appFw operand, no Sony bytes').hexdigest()
    projection = {key: copy.deepcopy(metadata[key]) for key in v.SHUTTER_GATE_READER_FIELDS
                  if key not in ('observer_sha256', 'Main_source_sha256', 'original_appfw_sha256')}
    projection.update(observer_sha256=observer, Main_source_sha256=f.sha(BASE / 'menu-observe.c'),
        original_appfw_sha256=appfw)
    expected = dict(copy.deepcopy(projection), profile=v.SHUTTER_GATE_PROFILE, trace_schema='readonly_shutter_gate_v1',
        source_contract_sha256=built['source_contract_sha256'], build_receipt=ref['path'],
        library_source=str(library), build_metadata=metadata,
        functional_runner_source_sha256=f.sha(BASE / 'functional_camera_runner.py'))
    production = {str(BASE / 'menu-observe.c'): projection['Main_source_sha256']}
    host = {str(BASE / name): f.sha(BASE / name) for name in ('functional_camera_runner.py', 'scope_observer_profile.py')}
    observer_sources = {str(root / name): value for name, value in sources.items()}
    test_sources = {str(root / name): value for name, value in fixtures.items()}
    frozen_names = set(production) | set(host) | set(observer_sources) | set(test_sources)
    # Count-only HOST_METADATA members are not a claim that a real 1193-source batch ran.
    for index in range(1193 - len(frozen_names)):
        path = str(f.work / ('HOST_METADATA-source-%04d.py' % index))
        test_sources[path] = hashlib.sha256(('HOST_METADATA source count: ' + str(index)).encode()).hexdigest()
    f.tested = dict(groups=dict(production=production, host=host, observer=observer_sources, test=test_sources),
        modules=sorted(set(production) | set(host) | set(observer_sources) | set(test_sources))[:242])
    assets = {str(path): f.sha(path) for path in (binary, static_audit, command, import_audit, receipt_path, library)}
    fixture_path = f.work / 'HOST_METADATA-fixture-manifest.json'
    fixture = dict(evidence_kind='HOST_METADATA', status='PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V1_FIXTURE',
        failure=None, profile=v.SHUTTER_GATE_PROFILE, trace_schema='readonly_shutter_gate_v1',
        trace_schema_sha256=projection['trace_schema_sha256'], fixture_source_sha256=copy.deepcopy(fixtures),
        inputs={kind + name: dict(path=str(root / name), sha256=value)
                for kind, values in (('source:', sources), ('fixture-source:', fixtures)) for name, value in values.items()},
        variants={name: dict(evidence_kind='HOST_METADATA', executed=False) for name in
                  ('original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb')},
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.write(fixture_path, fixture)
    b = f.binding
    b.update(schema=v.SHUTTER_GATE_RUN, observer_sha256=observer,
        scope_observer_expected=expected, shutter_gate_reader_expected=copy.deepcopy(projection),
        candidate_qemu=dict(path=str(binary), sha256=f.sha(binary)), runtime_assets_sha256=assets,
        synthetic_fixture_manifest=dict(path=str(fixture_path), sha256=f.sha(fixture_path)),
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.observer = observer
    f.build['sources'][str(BASE / 'menu-observe.c')]['sha256'] = projection['Main_source_sha256']
    f.manifest.update(backup_transport=dict(binary=str(binary), binary_sha256=f.sha(binary)))
    f.manifest['selected_initramfs_verified_files']['usr/lib/appFw.so'] = appfw
    f.manifest['files'][str(binary)] = f.sha(binary)
    f.manifest['files'].update({str(root / name): value for name, value in sources.items()})
    f.manifest['files'][ref['path']] = ref['sha256']
    (f.run / 'readonly-scope-observer.so').write_bytes(library.read_bytes())
    f.manifest['files'][str(f.run / 'readonly-scope-observer.so')] = f.sha(library)
    batch = Path(b['batch']); batch.mkdir()
    offline_false = dict.fromkeys(('runtime_verified', 'capture_verified', 'physical', 'physical_asic_compatibility_verified',
        'originalMain', 'retirement', 'instruction_retirement_verified', 'Main_identity_verified',
        'AP_identity_verified', 'branch_edge_verified', 'invocation_pairing_verified', 'original_camera_VM_started',
        'originalUI_onceplan_prepared', 'intent_published', 'card_prepared'), False)
    parent_path = f.work / 'parent-readback.json'
    parent = dict(evidence_kind='HOST_METADATA', status='PASS_OFFLINE_SHUTTER_GATE_V1_COHORT_READBACK',
        batch=str(batch), ready_sha256=b['batch_ready_sha256'], expected_original_run_assets=copy.deepcopy(projection),
        gate_actual_api=dict(manifest=copy.deepcopy(b['synthetic_fixture_manifest'])), gate_build_receipt=copy.deepcopy(ref),
        all_source_members_verified=1193, legacy_runtime_assets_sha256={}, gate_added_runtime_assets_sha256=copy.deepcopy(assets),
        launch_runtime_preflight=dict(passed=False, inspected=False, launch_authorized=False), **offline_false)
    f.write(parent_path, parent)
    b['parent_readback'] = dict(path=str(parent_path), sha256=f.sha(parent_path))
    b['actual_api_contract'] = copy.deepcopy(b['parent_readback'])
    runtime_path = batch / 'readonly-shutter-gate-v1-runtime-ready.json'
    runtime = dict(evidence_kind='HOST_METADATA', status='PASS_NEW_OFFLINE_SHUTTER_GATE_V1_SUPPLEMENT',
        generic_ready=dict(path=str(batch / 'ready.json'), sha256=b['batch_ready_sha256']),
        offline_readback=copy.deepcopy(b['parent_readback']), expected_original_run_assets=copy.deepcopy(projection),
        gate_build_receipt=copy.deepcopy(ref), launch_runtime_preflight=dict(passed=False, inspected=False, launch_authorized=False),
        **offline_false)
    f.write(runtime_path, runtime)
    b['runtime_ready'] = dict(path=str(runtime_path), sha256=f.sha(runtime_path))
    fresh_path = Path(b['fresh_guest']['path'])
    fresh = json.loads(fresh_path.read_bytes())
    fresh.update(runtime_ready_sha256=b['runtime_ready']['sha256'],
        compiled_before={str(BASE / 'menu-observe.so'): observer}, compiled_after={str(BASE / 'menu-observe.so'): observer})
    f.write(fresh_path, fresh)
    b['fresh_guest']['sha256'] = f.sha(fresh_path)
    driver = BASE / 'scratch/run-functional-current-batch.py'
    plan = {key: copy.deepcopy(b[key]) for key in ('nonce', 'batch', 'batch_ready_sha256', 'runtime_ready',
        'parent_readback', 'fresh_guest', 'runtime_assets_sha256', 'actual_api_contract', 'candidate_qemu', 'card')}
    plan.update(schema='functional-shutter-gate-v1-plan-v1', guest_image=str(f.guest), scope_build=copy.deepcopy(ref),
        actual_api_manifest=copy.deepcopy(b['synthetic_fixture_manifest']), driver=str(driver), driver_sha256=f.sha(driver),
        claimed_fault_result='FAIL', **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.plan, f.parent, f.runtime = plan, parent, runtime
    f.metadata, f.expected, f.source_root = metadata, expected, root
    f.validate_calls = validate_calls
    f.launch_owner = dict(pid=101, ppid=1, starttime=101, exe='/usr/bin/python3')
    refresh_shutter_binding(f)
    return f


def refresh_shutter_binding(f):
    """Rebind all synthetic hashes so a negative reaches its intended content guard."""
    b = f.binding
    f.write(f.work / 'plan.json', f.plan)
    fields = v.SHUTTER_GATE_PLAN_FIELDS + ('observer_sha256', 'guest_sha256', 'candidate_qemu', 'card')
    common = {key: copy.deepcopy(b[key]) for key in fields}
    common.update(plan=str(f.work / 'plan.json'), plan_sha256=f.sha(f.work / 'plan.json'),
        driver=f.plan['driver'], driver_sha256=f.plan['driver_sha256'], claimed_fault_result='FAIL',
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.write(f.work / 'intent.json', dict(common, schema='functional-shutter-gate-v1-intent-v1', guest_image=str(f.guest)))
    b['intent_sha256'] = f.sha(f.work / 'intent.json')
    f.write(f.work / 'launch-binding.json', dict(common, schema='functional-shutter-gate-v1-launch-v1',
        intent_sha256=b['intent_sha256'], launch_owner=f.launch_owner))
    b['launch_binding_sha256'] = f.sha(f.work / 'launch-binding.json')
    plan_binding = {key: copy.deepcopy(b[key]) for key in v.SHUTTER_GATE_PLAN_FIELDS}
    f.manifest['readonly_scope_observer'] = dict(f.metadata, library=str(f.run / 'readonly-scope-observer.so'),
        log=str(f.run / 'readonly-scope-trace.log'), plan_binding=plan_binding)
    info = f.run.stat()
    context = dict(schema='functional-shutter-gate-v1-live-context-v1', run=str(f.run),
        run_device=info.st_dev, run_inode=info.st_ino, scope=plan_binding,
        **{key: copy.deepcopy(b[key]) for key in ('nonce', 'batch', 'batch_ready_sha256', 'intent_sha256',
                                               'launch_binding_sha256', 'candidate_qemu', 'card')})
    f.context = context
    live = dict(schema='functional-shutter-gate-v1-popen-live-v1', context=context,
        wrapper=dict(pid=202, ppid=201, starttime=202, exe='/usr/bin/bash'),
        owner=dict(pid=201, ppid=200, starttime=201, exe='/usr/bin/python3'),
        control=dict(pid=200, ppid=101, starttime=200, exe='/usr/bin/python3'),
        actual_Popen_pid=202, birth_sample={}, launch_policy={}, control_mode='probe-parent',
        probe_source_sha256=f.sha(BASE / 'qemu-menu-probe.py'), **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    live['birth_sample'] = dict(identity=copy.deepcopy(live['wrapper']))
    live['launch_policy'] = dict(model='approved-functional-shell-bwrap-v1')
    f.write(f.run / 'readonly-scope-popen-live.json', live)
    b['popen_live_sha256'] = f.sha(f.run / 'readonly-scope-popen-live.json')
    f.write(f.run / 'readonly-scope-run-binding.json', b)
    ancestry = dict(schema='functional-shutter-gate-v1-live-ancestry-v1', context=context,
        **{key: copy.deepcopy(live[key]) for key in ('wrapper', 'owner', 'control', 'control_mode')},
        launch_owner=f.launch_owner,
        chain=[dict(pid=204, ppid=203, starttime=204, exe='/tools/qemu-system-aarch64'),
               dict(pid=203, ppid=202, starttime=203, exe='/usr/bin/bwrap'),
               dict(live['wrapper'], exe='/usr/bin/bwrap'), live['owner'], live['control'], f.launch_owner],
        execution=dict(birth=copy.deepcopy(live['birth_sample']), policy=copy.deepcopy(live['launch_policy']),
                       actual_Popen_pid=live['actual_Popen_pid'], dual_read_stable=True),
        qemu=dict(pid=204, ppid=203, starttime=204, exe='/tools/qemu-system-aarch64'), captured_while_alive=True,
        popen_live_sha256=b['popen_live_sha256'], run_binding_sha256=f.sha(f.run / 'readonly-scope-run-binding.json'),
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.write(f.run / 'readonly-scope-live-ancestry.json', ancestry)
    (f.run / 'readonly-scope-trace.log').write_bytes(b'synthetic raw observer bytes; no UPM or AP claim\n')
    f.write(f.run / 'readonly-scope-exit.json', dict(profile=v.SHUTTER_GATE_PROFILE, run=str(f.run),
        owned_wrapper_pid=202, returncode=0, library_sha256=f.metadata['library_sha256'],
        log_available=True, log_sha256=f.sha(f.run / 'readonly-scope-trace.log'), capture_verified=False,
        physical_asic_compatibility_verified=False))
    callback = dict(schema='functional-shutter-gate-v1-popen-exit-v1', context=context, wrapper=live['wrapper'],
        actual_Popen_pid=202, returncode=0, popen_live_sha256=b['popen_live_sha256'],
        ancestry_sha256=f.sha(f.run / 'readonly-scope-live-ancestry.json'),
        original_exit_sha256=f.sha(f.run / 'readonly-scope-exit.json'), **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.write(f.run / 'readonly-scope-popen-exit-binding.json', callback)


def scope_provenance(fixture):
    name, binding, original = v._condition_binding(fixture.graph, fixture.run, fixture.observer)
    assert name == 'readonly-scope-run-binding.json'
    assert original == (fixture.run / name).read_bytes()
    return v._condition_scope_binding(fixture.graph, fixture.reader, fixture.run,
        binding, fixture.manifest, fixture.build, fixture.tested)


def refresh_shutter_parents(f):
    b = f.binding
    projection = b['shutter_gate_reader_expected']
    f.parent['expected_original_run_assets'] = copy.deepcopy(projection)
    f.runtime['expected_original_run_assets'] = copy.deepcopy(projection)
    parent_path = Path(b['parent_readback']['path'])
    f.write(parent_path, f.parent)
    b['parent_readback']['sha256'] = f.sha(parent_path)
    b['actual_api_contract'] = copy.deepcopy(b['parent_readback'])
    f.runtime['offline_readback'] = copy.deepcopy(b['parent_readback'])
    runtime_path = Path(b['runtime_ready']['path'])
    f.write(runtime_path, f.runtime)
    b['runtime_ready']['sha256'] = f.sha(runtime_path)
    fresh_path = Path(b['fresh_guest']['path'])
    fresh = json.loads(fresh_path.read_bytes())
    fresh['runtime_ready_sha256'] = b['runtime_ready']['sha256']
    f.write(fresh_path, fresh)
    b['fresh_guest']['sha256'] = f.sha(fresh_path)
    for key in ('parent_readback', 'actual_api_contract', 'runtime_ready', 'fresh_guest', 'runtime_assets_sha256'):
        f.plan[key] = copy.deepcopy(b[key])
    refresh_shutter_binding(f)


def test_shutter_scope_uses_actual_fixed_source7_fixture7_and_independent_schemas(synthetic_shutter_binding):
    f = synthetic_shutter_binding
    guest, snapshots = scope_provenance(f)
    assert guest == f.guest
    assert set(f.expected['source_sha256']) == set(v.SHUTTER_GATE_SOURCE_NAMES)
    assert set(f.expected['fixture_source_sha256']) == set(v.SHUTTER_GATE_FIXTURE_NAMES)
    assert f.source_root == f.graph.NATIVE / v.SHUTTER_GATE_COMPONENT == BASE.parents[1] / v.SHUTTER_GATE_COMPONENT
    assert not v.SHUTTER_GATE_ALIASES & f.expected.keys()
    assert f.expected['trace_schema_sha256'] == f.sha(f.source_root / 'log-schema-shutter-gate-v1.json')
    assert f.binding['shutter_gate_reader_expected'] == f.parent['expected_original_run_assets']
    assert f.work / 'plan.json' in snapshots
    assert f.run / 'readonly-scope-popen-exit-binding.json' in snapshots
    assert f.run / 'readonly-scope-live-ancestry.json' in snapshots
    assert all(f.source_root / name in snapshots for name in v.SHUTTER_GATE_FIXTURE_NAMES)
    assert all(f.binding[k] is False for k in v.SHUTTER_GATE_FALSE_FIELDS)
    assert f.validate_calls == [(BASE.parents[1], f.metadata['build_receipt'], f.binding['candidate_qemu']['path'])]


@pytest.mark.parametrize('alias', sorted(v.SHUTTER_GATE_ALIASES))
@pytest.mark.parametrize('where', ['expected', 'build-metadata', 'manifest', 'parent', 'plan', 'fixture'])
def test_shutter_schema_and_source_root_aliases_are_never_external_inputs(synthetic_shutter_binding, alias, where):
    f = synthetic_shutter_binding
    target = {'expected': f.expected, 'build-metadata': f.metadata, 'parent': f.parent, 'plan': f.plan}.get(where)
    if target is not None:
        target[alias] = str(f.source_root) if 'root' in alias.lower() else 'a' * 64
    if where == 'fixture':
        fixture = json.loads(Path(f.binding['synthetic_fixture_manifest']['path']).read_bytes())
        fixture[alias] = 'a' * 64
        path = f.work / 'synthetic-actualapi-manifest.json'
        f.write(path, fixture)
        reference = dict(path=str(path), sha256=f.sha(path))
        f.binding['synthetic_fixture_manifest'] = reference
        f.parent['gate_actual_api']['manifest'] = reference
        f.plan['actual_api_manifest'] = reference
    refresh_shutter_parents(f)
    if where == 'manifest':
        f.manifest['readonly_scope_observer'][alias] = 'a' * 64
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


@pytest.mark.parametrize('role', ['source_sha256', 'fixture_source_sha256'])
@pytest.mark.parametrize('damage', ['missing', 'extra', 'hash'])
def test_shutter_requires_exact_seven_actual_and_frozen_roles(synthetic_shutter_binding, role, damage):
    f = synthetic_shutter_binding
    values = f.expected[role]
    if damage == 'missing':
        values.pop(next(iter(values)))
    elif damage == 'extra':
        values['unreviewed-extra.c'] = 'a' * 64
    else:
        values[next(iter(values))] = '0' * 64
    f.metadata[role] = copy.deepcopy(values)
    f.binding['shutter_gate_reader_expected'][role] = copy.deepcopy(values)
    refresh_shutter_parents(f)
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


@pytest.mark.parametrize('damage', ['old-run-schema', 'old-intent-schema', 'old-launch-schema', 'old-plan-schema',
    'old-profile', 'old-trace', 'reader-extra', 'reader-missing', 'wrong-schema-hash', 'wrong-contract-hash',
    'manifest-extra', 'manifest-missing-fixture', 'manifest-missing-command', 'manifest-missing-audit',
    'manifest-missing-candidate', 'manifest-wrong-library', 'frozen-fixture', 'source1192', 'modules241',
    'runtime-other-parent', 'parent-other-batch', 'stale-nonce', 'boolean-nonce', 'driver', 'selected-guest'])
def test_shutter_never_coerces_old_or_incomplete_generation(synthetic_shutter_binding, damage):
    f = synthetic_shutter_binding
    if damage == 'old-run-schema':
        f.binding['schema'] = 'functional-M-v3-run-v3'
    elif damage in ('old-profile', 'old-trace', 'wrong-schema-hash', 'wrong-contract-hash'):
        key, value = {'old-profile': ('profile', 'qemu-readonly-scope-v3'),
            'old-trace': ('trace_schema', 'readonly_scope_v3'), 'wrong-schema-hash': ('trace_schema_sha256', '0' * 64),
            'wrong-contract-hash': ('source_contract_sha256', '0' * 64)}[damage]
        f.expected[key] = value
    elif damage in ('reader-extra', 'reader-missing'):
        if damage == 'reader-extra':
            f.binding['shutter_gate_reader_expected']['schema_sha256'] = 'a' * 64
        else:
            del f.binding['shutter_gate_reader_expected']['fixture_source_sha256']
    elif damage == 'frozen-fixture':
        f.tested['groups']['test'][str(f.source_root / 'integration/fixture.S')] = '0' * 64
    elif damage == 'source1192':
        path = next(p for p in f.tested['groups']['test'] if all(p not in group for name, group in
            f.tested['groups'].items() if name != 'test') and p not in f.tested['modules'])
        del f.tested['groups']['test'][path]
    elif damage == 'modules241':
        f.tested['modules'].pop()
    elif damage == 'parent-other-batch':
        f.parent['batch'] += '-foreign'
    elif damage == 'boolean-nonce':
        f.binding['nonce'] = True
    refresh_shutter_parents(f)
    if damage == 'stale-nonce':
        f.binding['nonce'] += 1
        f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    elif damage == 'selected-guest':
        f.manifest['files'][str(f.guest)] = '0' * 64
    elif damage == 'runtime-other-parent':
        path = Path(f.binding['runtime_ready']['path'])
        data = json.loads(path.read_bytes()); data['offline_readback']['sha256'] = '0' * 64
        f.write(path, data)
        f.binding['runtime_ready']['sha256'] = f.sha(path)
        refresh_shutter_binding(f)
    elif damage.startswith('old-') and damage.endswith('-schema') and damage != 'old-run-schema':
        name, schema = {'old-intent-schema': ('intent.json', 'functional-M-v3-intent-v3'),
            'old-launch-schema': ('launch-binding.json', 'functional-M-v3-launch-v3'),
            'old-plan-schema': ('plan.json', 'functional-M-v3-plan-v3')}[damage]
        path = f.work / name
        data = json.loads(path.read_bytes()); data['schema'] = schema
        f.write(path, data)
        if name != 'plan.json':
            f.binding['intent_sha256' if name == 'intent.json' else 'launch_binding_sha256'] = f.sha(path)
            f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    elif damage == 'driver':
        path = f.work / 'launch-binding.json'
        data = json.loads(path.read_bytes()); data['driver_sha256'] = '0' * 64
        f.write(path, data)
        f.binding['launch_binding_sha256'] = f.sha(path)
        f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    elif damage.startswith('manifest-'):
        scope = f.manifest['readonly_scope_observer']
        if damage == 'manifest-extra':
            scope['unreviewed_success'] = True
        elif damage == 'manifest-wrong-library':
            scope['library_sha256'] = '0' * 64
        else:
            del scope[{'manifest-missing-fixture': 'fixture_source_sha256',
                'manifest-missing-command': 'plugin_build_command_sha256',
                'manifest-missing-audit': 'readonly_import_audit_sha256',
                'manifest-missing-candidate': 'candidate_static_audit_sha256'}[damage]]
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


@pytest.mark.parametrize('name', ['readonly-scope-popen-live.json', 'readonly-scope-live-ancestry.json',
                                  'readonly-scope-popen-exit-binding.json'])
@pytest.mark.parametrize('damage', ['schema', 'nonce', 'scope', 'inode-bool', 'extra', 'missing', 'promote'])
def test_shutter_popen_receipts_bind_the_whole_generation(synthetic_shutter_binding, name, damage):
    f = synthetic_shutter_binding
    path = f.run / name
    data = json.loads(path.read_bytes())
    if damage == 'schema':
        data['schema'] = data['schema'].replace('functional-shutter-gate-v1', 'functional-M-v3')
    elif damage == 'nonce':
        data['context']['nonce'] += 1
    elif damage == 'scope':
        del data['context']['scope']['shutter_gate_reader_expected']
    elif damage == 'inode-bool':
        data['context']['run_inode'] = True
    elif damage == 'extra':
        data['source_root'] = str(f.source_root)
    elif damage == 'missing':
        data.pop('wrapper')
    else:
        data['branchretirement'] = True
    f.write(path, data)
    if name == 'readonly-scope-popen-live.json':
        f.binding['popen_live_sha256'] = f.sha(path)
        f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


@pytest.mark.parametrize('field', ['plugin_build_command_sha256', 'readonly_import_audit_sha256',
                                   'candidate_static_audit_sha256'])
def test_shutter_all_audit_metadata_must_match_actual_build_bytes(synthetic_shutter_binding, field):
    f = synthetic_shutter_binding
    original_digest = f.metadata[field]
    f.metadata[field] = '0' * 64
    refresh_shutter_parents(f)
    assert f.manifest['readonly_scope_observer'][field] == f.expected['build_metadata'][field]
    with pytest.raises(ValueError, match='complete actual build metadata differs'):
        scope_provenance(f)
    f.metadata[field] = original_digest
    refresh_shutter_parents(f)
    plugin = Path(f.metadata['build_receipt']).parent
    path = {'plugin_build_command_sha256': plugin / 'plugin-build-command.json',
        'readonly_import_audit_sha256': plugin / 'readonly-import-audit.json',
        'candidate_static_audit_sha256': Path(f.binding['candidate_qemu']['path']).parents[1] / 'binary-static-audit.json'}[field]
    path.write_bytes(path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='shutter gate receipt digest differs'):
        scope_provenance(f)


@pytest.mark.parametrize('name,field,value', [
    ('readonly-scope-popen-exit-binding.json', 'returncode', 1),
    ('readonly-scope-popen-exit-binding.json', 'actual_Popen_pid', True),
    ('readonly-scope-popen-exit-binding.json', 'popen_live_sha256', '0' * 64),
    ('readonly-scope-popen-exit-binding.json', 'ancestry_sha256', '0' * 64),
    ('readonly-scope-popen-exit-binding.json', 'original_exit_sha256', '0' * 64),
    ('readonly-scope-live-ancestry.json', 'captured_while_alive', False),
    ('readonly-scope-live-ancestry.json', 'run_binding_sha256', '0' * 64),
    ('readonly-scope-live-ancestry.json', 'chain', []),
    ('readonly-scope-live-ancestry.json', 'execution', {}),
    ('readonly-scope-popen-live.json', 'actual_Popen_pid', 203),
    ('readonly-scope-popen-live.json', 'probe_source_sha256', '0' * 64),
])
def test_shutter_popen_original_byte_and_generation_links_cannot_be_replaced(synthetic_shutter_binding, name, field, value):
    f = synthetic_shutter_binding
    path = f.run / name
    data = json.loads(path.read_bytes()); data[field] = value
    f.write(path, data)
    if name == 'readonly-scope-popen-live.json':
        f.binding['popen_live_sha256'] = f.sha(path)
        f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


def test_upm_consumer_routes_large_host_metadata_through_shared_reader(tmp_path):
    """Parser and source dispatch structure only; no original-process replay claim."""
    from test_hdmi_upm_watch import reader_config_fixture
    watch = v._watch()
    config = reader_config_fixture(v.SHUTTER_GATE_PROFILE)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    assert 16384 < len(path.read_bytes()) <= 32768
    assert watch.read_config(path) == config
    tree = ast.parse(Path(v.__file__).read_text())
    consumer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'verify_hdmi_upm')
    calls = [node for node in ast.walk(consumer) if isinstance(node, ast.Call)]
    reads = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == 'read_config']
    joins = [node for node in calls if isinstance(node.func, ast.Name) and node.func.id == '_condition_source_proof']
    assert len(reads) == len(joins) == 1 and reads[0].lineno < joins[0].lineno
    assert any(isinstance(node, ast.Constant) and node.value == 'shutter gate native config/source binding differs'
               for node in ast.walk(consumer))


@pytest.mark.parametrize('profile', [None, 'qemu-readonly-scope-v1', 'qemu-readonly-scope-v2', 'qemu-readonly-scope-v3'])
def test_shared_reader_retains_old_profile_config_limits(tmp_path, profile):
    from test_hdmi_upm_watch import reader_config_fixture
    watch = v._watch()
    config = reader_config_fixture(profile)
    if profile is not None:
        del config['readonly_scope_observer']['plan_binding']
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    assert watch.read_config(path) == config
    config['padding'] = 'x' * 17000
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='profile byte bound'):
        watch.read_config(path)


@pytest.mark.parametrize('damage', ['raw-body', 'effective-body', 'header-source', 'header-refcount', 'short-body'])
def test_shutter_metadata_never_excuses_changed_original_upm_bytes(synthetic_shutter_binding, damage):
    """HOST_METADATA bytes exercise the real snapshot decoder, without native opcode assets."""
    from test_hdmi_upm_watch import event, K
    f = synthetic_shutter_binding
    scope_provenance(f)
    watch = v._watch()
    sample = event('branch' if damage == 'effective-body' else 'bridge', 1)
    watch.snapshot(sample, K)
    if damage in ('raw-body', 'effective-body'):
        sample['memory']['body']['hex'] = '00' * 16
    elif damage == 'short-body':
        sample['memory']['body']['hex'] = sample['memory']['body']['hex'][:-2]
    else:
        header = bytearray.fromhex(sample['memory']['header']['hex'])
        offset, size = (12, 4) if damage == 'header-source' else (10, 2)
        header[offset:offset + size] = bytes(size)
        sample['memory']['header']['hex'] = header.hex()
    with pytest.raises(ValueError):
        watch.snapshot(sample, K)


def test_shutter_profile_never_excuses_missing_original_condition_free(synthetic_shutter_binding):
    f = synthetic_shutter_binding
    scope_provenance(f)
    log = Log(v.STATE + '_MESSAGE_PUBLISHED kind=2 lease=1\n' + v.STATE + '_MESSAGE_SENT kind=2 lease=1\n')
    with pytest.raises(ValueError, match='incomplete message lifetimes'):
        v.verify_conditions(log, f.run)


def test_shutter_family_keeps_common_retained_image_byte_guard(synthetic_shutter_binding):
    """Exercise the real byte digest guard and inspect its unchanged source-proof call site."""
    f = synthetic_shutter_binding
    scope_provenance(f)
    reader = f.graph.source_module('report/functional-camera-evidence/check_evidence.py',
        {str(BASE.parents[1] / 'report/functional-camera-evidence/check_evidence.py'):
         f.sha(BASE.parents[1] / 'report/functional-camera-evidence/check_evidence.py')})
    retained = f.work / 'HOST_METADATA-retained-image.cpio'
    retained.write_bytes(b'HOST_METADATA image bytes, no guest or Sony content')
    digest = f.sha(retained)
    reader.digest_binding(retained.read_bytes(), digest, 'condition retained initramfs')
    retained.write_bytes(retained.read_bytes()[:-1] + b'!')
    with pytest.raises(ValueError, match='condition retained initramfs: SHA256 differs'):
        reader.digest_binding(retained.read_bytes(), digest, 'condition retained initramfs')
    tree = ast.parse(Path(v.__file__).read_text())
    proof = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_condition_source_proof')
    calls = [node for node in ast.walk(proof) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert any(node.func.attr == 'digest_binding' and isinstance(node.args[0], ast.Name) and node.args[0].id == 'image_raw'
               for node in calls)
    assert any(node.func.attr == 'verify_image' for node in calls)


def test_scope_binding_consumes_exact_original_path_and_provenance(synthetic_scope_binding):
    f = synthetic_scope_binding
    guest, snapshots = scope_provenance(f)
    assert guest == f.guest
    assert f.run / 'readonly-scope-popen-live.json' in snapshots
    assert f.work / 'intent.json' in snapshots and f.work / 'launch-binding.json' in snapshots
    assert not (f.run / 'source-snapshot-run-binding.json').exists()
    assert len(snapshots) == 13  # Nine original scope sources and four provenance receipts.
    assert all(f.binding[k] is False for k in v.SCOPE_FALSE_FIELDS)


def test_scope_envelope_version_cannot_be_switched_without_its_original_provenance(synthetic_scope_binding):
    f = synthetic_scope_binding
    other = 3 if f.version == 2 else 2
    f.binding['schema'] = f'functional-M-v{other}-run-v{other}'
    f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    with pytest.raises(ValueError, match='condition scope intent/launch provenance differs'):
        scope_provenance(f)


@pytest.mark.parametrize('damage', ['missing', 'extra', 'empty'])
def test_scope_binding_requires_exact_nine_sources_despite_matching_metadata(synthetic_scope_binding, damage):
    f = synthetic_scope_binding
    expected = f.binding['scope_observer_expected']
    sources = dict(expected['source_sha256'])
    if damage == 'missing':
        del sources['scope-observer.c']
    elif damage == 'extra':
        path = Path(expected['source_root']) / 'unreviewed-extra.c'
        path.write_bytes(b'synthetic extra source only')
        sources[path.name] = f.sha(path)
        f.tested['groups']['observer'][str(path)] = f.sha(path)
    else:
        sources.clear()
    scope = f.manifest['readonly_scope_observer']
    for metadata in (expected, expected['build_metadata'], scope):
        metadata['source_sha256'] = dict(sources)
    assert expected['source_sha256'] == expected['build_metadata']['source_sha256'] == scope['source_sha256']
    assert len(sources) == {'missing': 8, 'extra': 10, 'empty': 0}[damage]
    scope['plan_binding']['scope_observer_expected'] = copy.deepcopy(expected)
    # Keep every synthetic receipt bound so an unrelated provenance mismatch cannot mask the source-set guard.
    for name, key in (('intent.json', 'intent_sha256'), ('launch-binding.json', 'launch_binding_sha256')):
        path = f.work / name
        receipt = json.loads(path.read_bytes())
        receipt['scope_observer_expected'] = copy.deepcopy(expected)
        if name == 'launch-binding.json':
            receipt['intent_sha256'] = f.binding['intent_sha256']
        f.write(path, receipt)
        f.binding[key] = f.sha(path)
    path = f.run / 'readonly-scope-popen-live.json'
    live = json.loads(path.read_bytes())
    live['context'].update(scope=copy.deepcopy(scope['plan_binding']),
        intent_sha256=f.binding['intent_sha256'], launch_binding_sha256=f.binding['launch_binding_sha256'])
    f.write(path, live)
    f.binding['popen_live_sha256'] = f.sha(path)
    f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    with pytest.raises(ValueError, match='condition scope source set differs'):
        scope_provenance(f)


def test_legacy_binding_remains_explicit(synthetic_scope_binding):
    f = synthetic_scope_binding
    (f.run / 'readonly-scope-run-binding.json').unlink()
    keys = ('nonce', 'batch', 'batch_ready_sha256', 'observer_sha256', 'guest_sha256',
            'candidate_qemu', 'card', 'run', 'intent_sha256', 'launch_binding_sha256', 'claimed_fault_result')
    binding = {key: f.binding[key] for key in keys + v.RUN_FALSE_FIELDS}
    binding['schema'] = 'functional-source-snapshot-run-v1'
    f.write(f.run / 'source-snapshot-run-binding.json', binding)
    name, actual, original = v._condition_binding(f.graph, f.run, f.observer)
    assert name == 'source-snapshot-run-binding.json'
    assert actual == binding and f.sha(f.run / name) == hashlib.sha256(original).hexdigest()


@pytest.mark.parametrize('alternate', ['valid', 'identical-content', 'corrupt', 'dangling-symlink'])
def test_both_named_bindings_are_always_ambiguous(synthetic_scope_binding, alternate):
    f = synthetic_scope_binding
    path = f.run / 'source-snapshot-run-binding.json'
    if alternate == 'valid':
        f.write(path, dict(f.binding, schema='functional-source-snapshot-run-v1'))
    elif alternate == 'identical-content':
        path.write_bytes((f.run / 'readonly-scope-run-binding.json').read_bytes())
    elif alternate == 'corrupt':
        path.write_bytes(b'{')
    else:
        path.symlink_to('absent-binding.json')
    with pytest.raises(ValueError, match='binding missing or ambiguous'):
        v._condition_binding(f.graph, f.run, f.observer)


def test_arbitrary_json_is_never_a_binding_fallback(synthetic_scope_binding):
    f = synthetic_scope_binding
    (f.run / 'readonly-scope-run-binding.json').rename(f.run / 'arbitrary.json')
    with pytest.raises(ValueError, match='binding missing or ambiguous'):
        v._condition_binding(f.graph, f.run, f.observer)


@pytest.mark.parametrize('field,value', [
    ('schema', 'functional-source-snapshot-run-v1'), ('schema', 'unreviewed-schema'),
    ('run', '/tmp/foreign-run'), ('nonce', True), ('nonce', 0), ('nonce', -1),
    ('nonce', 42.0), ('nonce', 2**64), ('observer_sha256', 'b' * 64),
    ('guest_sha256', 'A' * 64), ('batch_ready_sha256', ''), ('capture_verified', True),
    ('physical_asic_compatibility_verified', True), ('claimed_fault_result', 'PASS'),
])
def test_common_binding_schema_and_content_are_strict(synthetic_scope_binding, field, value):
    f = synthetic_scope_binding
    f.binding[field] = value
    f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    with pytest.raises(ValueError):
        v._condition_binding(f.graph, f.run, f.observer)


@pytest.mark.parametrize('damage', ['missing-field', 'extra-field', 'cap', 'store', 'retirement',
    'fresh-digest', 'intent-digest', 'launch-digest', 'popen-digest', 'selected-guest',
    'actual-guest-digest', 'appfw', 'Main', 'frozen-source', 'actual-source', 'foreign-nonce',
    'foreign-run', 'boolean-inode', 'missing-popen', 'wrong-fresh-observer', 'missing-metadata',
    'metadata-qemu'])
def test_scope_binding_never_invents_missing_or_foreign_facts(synthetic_scope_binding, damage):
    f = synthetic_scope_binding
    if damage == 'missing-field':
        del f.binding['actual_api_contract']
    elif damage == 'extra-field':
        f.binding['unreviewed_success'] = True
    elif damage in ('cap', 'store', 'retirement'):
        key = {'cap': 'cap', 'store': 'storecompletion', 'retirement': 'branchretirement'}[damage]
        f.binding[key] = True
    elif damage.endswith('-digest') and damage != 'actual-guest-digest':
        key = {'fresh-digest': 'fresh_guest', 'intent-digest': 'intent_sha256',
               'launch-digest': 'launch_binding_sha256', 'popen-digest': 'popen_live_sha256'}[damage]
        if key == 'fresh_guest':
            f.binding[key]['sha256'] = '0' * 64
        else:
            f.binding[key] = '0' * 64
    elif damage == 'selected-guest':
        f.manifest['probe_args']['initramfs_file'] = str(f.work / 'another-guest.cpio')
    elif damage == 'actual-guest-digest':
        f.manifest['files'][str(f.guest)] = '0' * 64
    elif damage == 'appfw':
        f.manifest['selected_initramfs_verified_files']['usr/lib/appFw.so'] = '0' * 64
    elif damage == 'Main':
        f.build['sources'][str(BASE / 'menu-observe.c')]['sha256'] = '0' * 64
    elif damage == 'frozen-source':
        key = next(iter(f.tested['groups']['observer']))
        f.tested['groups']['observer'][key] = '0' * 64
    elif damage == 'actual-source':
        Path(next(iter(f.tested['groups']['observer']))).write_bytes(b'changed original source')
    elif damage == 'missing-metadata':
        del f.manifest['readonly_scope_observer']['qemu_header_sha256']
    elif damage == 'metadata-qemu':
        f.manifest['readonly_scope_observer']['qemu_sha256'] = '0' * 64
    elif damage == 'missing-popen':
        (f.run / 'readonly-scope-popen-live.json').unlink()
    elif damage == 'wrong-fresh-observer':
        path = f.work / 'fresh-public-guest.json'
        fresh = json.loads(path.read_bytes())
        fresh['compiled_before'][str(BASE / 'menu-observe.so')] = '0' * 64
        f.write(path, fresh)  # Deliberately leave original receipt digest bound.
    else:
        path = f.run / 'readonly-scope-popen-live.json'
        live = json.loads(path.read_bytes())
        key, value = {'foreign-nonce': ('nonce', 43), 'foreign-run': ('run', str(f.run) + '-foreign'),
                      'boolean-inode': ('run_inode', True)}[damage]
        live['context'][key] = value
        f.write(path, live)
        f.binding['popen_live_sha256'] = f.sha(path)
    f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


@pytest.mark.parametrize('damage', ['duplicate-key', 'symlink', 'hardlink', 'non-object'])
def test_named_binding_keeps_original_safe_reader(synthetic_scope_binding, damage):
    f = synthetic_scope_binding
    path = f.run / 'readonly-scope-run-binding.json'
    if damage == 'duplicate-key':
        path.write_bytes(b'{"schema":"a","schema":"b"}')
    elif damage == 'non-object':
        path.write_bytes(b'[]')
    elif damage == 'symlink':
        original = f.run / 'untrusted-target.json'
        path.rename(original)
        path.symlink_to(original)
    else:
        os.link(path, f.run / 'untrusted-hardlink.json')
    with pytest.raises((ValueError, OSError)):
        v._condition_binding(f.graph, f.run, f.observer)


@pytest.mark.parametrize('new_main', range(6))
@pytest.mark.parametrize('new_recipe', range(6))
def test_approved_source_sets_require_a_complete_tuple(new_main, new_recipe):
    selected = dict(v.CONDITION_LEDGER_SOURCES)
    selected['menu-observe.c'] = v.SOURCE_SETS[new_main]['menu-observe.c']
    selected['build-observers.sh'] = v.SOURCE_SETS[new_recipe]['build-observers.sh']
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    approved = {(0, 0), (1, 1)} | {(m, r) for m in (2, 3, 4, 5) for r in (2, 3, 4, 5)}
    if (new_main, new_recipe) in approved:
        assert v._condition_source_set(sources) == v.SOURCE_SETS[new_main]
    else:
        with pytest.raises(ValueError, match='unreviewed condition ledger/hook source set'):
            v._condition_source_set(sources)


def test_actual_current_sources_match_parent_approved_exact_set():
    sources = {str(BASE / name): {'sha256': hashlib.sha256((BASE / name).read_bytes()).hexdigest()}
               for name in v.CONDITION_LEDGER_SOURCES}
    assert v._condition_source_set(sources) == v.SOURCE_SETS[-1]


@pytest.fixture(scope='module')
def host_log(video_connection_binary, public_adf_input_seed):
    if public_adf_input_seed is None:
        pytest.skip('pinned public ALLLANG seed unavailable')
    result = subprocess.run([str(video_connection_binary), 'normal', str(public_adf_input_seed)],
                            env=ENV, capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_HDMI_VIDEO_CONNECTION_HOST_TEST_PASS' in result.stdout
    return Log(result.stdout)


def change(log, tag, field, value, index=0):
    candidate = copy.deepcopy(log)
    candidate.rows(tag)[index]['fields'][field] = value
    return candidate


def test_actual_c_host_effects_remain_offline(host_log):
    result = v.verify_hdmi_effects(host_log)
    assert result['REQUEST'] is host_log.rows(v.PREFIX + '_REQUEST')[0]
    assert len(result['condition_messages']) == 24
    assert len(result['UPM_messages']) == 2
    assert not result['native_UPM_join_required']
    assert not result['condition_model_events_verified']
    assert not result['frames_verified'] and not result['capture_verified']


@pytest.mark.parametrize('suffix,field,value', [
    ('NATIVE_REPLY_FREE', 'sender', '999999'),
    ('NATIVE_REPLY_FREE', 'tid', '999999'),
    ('NATIVE_REPLY_FREE', 'waiter', '0'),
    ('NATIVE_REPLY_FREE', 'rc', '-1'),
    ('NATIVE_REPLY_FREE', 'faults', '1'),
    ('EVENT6_CONSUMED', 'saved_request_fnv', '0000000000000000'),
    ('EVENT6_CONSUMED', 'token', '0x504d4001'),
    ('VIDEO_MANAGER', 'gate', '1'),
    ('VIDEO_MANAGER', 'gate_reset_at_connect', '1'),
    ('STATE_READBACK', 'source_pending', '1'),
])
def test_bad_ap_sender_and_callback_effects_rejected(host_log, suffix, field, value):
    with pytest.raises(ValueError):
        v.verify_hdmi_effects(change(host_log, v.PREFIX + '_' + suffix, field, value))


@pytest.mark.parametrize('mutation', ['missing', 'source', 'sid', 'lease', 'receiver', 'unreceived', 'raw-hex-id'])
def test_condition_content_and_complete_leases_required(host_log, mutation):
    log = copy.deepcopy(host_log)
    published = v._kind(log, 'MESSAGE_PUBLISHED', 2)
    freed = v._kind(log, 'NATIVE_FREE', 2)
    if mutation == 'missing':
        log.records.remove(freed[-1])
    elif mutation == 'source':
        published[0]['fields']['source'] = hex(v.P[3])
    elif mutation == 'sid':
        published[0]['fields']['destination'] = '0x81cf618c'
    elif mutation == 'lease':
        published[1]['fields']['lease'] = published[0]['fields']['lease']
    elif mutation == 'receiver':
        freed[0]['fields']['receiver'] = '999999'
    elif mutation == 'unreceived':
        freed[0]['fields']['received'] = '0'
    else:
        # 0x17 is not decimal 17.
        published[1]['fields']['raw'] = published[1]['fields']['raw'].replace('17000000', '11000000', 1)
    with pytest.raises(ValueError):
        v.verify_hdmi_effects(log)


def test_late_fault_or_unsupported_never_passes(host_log):
    for tag in (v.PREFIX + '_FAULT', v.PREFIX + '_UNSUPPORTED', v.STATE + '_FREE_REJECTED'):
        log = copy.deepcopy(host_log)
        log.records.append(dict(line=1000000, tag=tag, fields={}, raw='offline adversarial record'))
        with pytest.raises(ValueError):
            v.verify_hdmi_effects(log)


@pytest.fixture(scope='module')
def delayed_native_log():
    run = BASE / 'menu-runs/run-xnodlttg'
    if not (run / 'console.log').is_file():
        pytest.skip('explicit completed delayed-free-note run unavailable')
    path = BASE.parents[1] / 'report/functional-graph-evidence/check_graph.py'
    spec = importlib.util.spec_from_file_location('_hdmi_test_source_reader', path)
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)
    relative = 'runtime/analysis/scratch/evaluate-five-edges-native.py'
    legacy = graph.source_module(relative, {str(graph.NATIVE / relative): graph.sha(graph.read(graph.NATIVE / relative))})
    original = graph.read(run / 'console.log', graph.MAX_LOG)
    assert len(original) == 2850791
    assert graph.sha(original) == '042d72dda0dcd45594ff5926900013e3966e79e95d09ed2df107ec63b0554931'
    parsed, repairs = graph.console_records(original)
    assert len(repairs) == 1 and repairs[0]['kind'] == 'exact-host-vvfat-diagnostic'
    log = legacy.Log(parsed)
    previous = v.one(log, 'FULL_PINMEM_DRAWINFO_CONNECT_NATIVE_REPLY_FREE')['line']
    first = v.one(log, 'FULL_IMAGING_PIN_CONNECT_REQUEST')['line']
    request = v.one(log, v.PREFIX + '_REQUEST')
    return run, log, previous, first, (request['fields']['pid'], request['fields']['producer_tid'])


def test_original_delayed_note_full_hdmi_stage_is_source_bound(delayed_native_log):
    run, log, previous, first, identity = delayed_native_log
    with pytest.raises(ValueError, match='live message address reused'):
        v.verify_conditions(log)
    with pytest.raises((TypeError, ValueError)):
        v.verify_conditions(log, True)
    result = v.verify_hdmi_edge(log, previous, identity, first, run)
    assert result['full_native_effects_verified'] and not result['capture_verified']
    assert len(result['condition_messages']) == 24 and len(result['prefix_reply_retirements']) == 3
    late = [(item, old) for item in result['condition_messages'] for old in item.get('late_free_note_predecessors', [])]
    assert len(late) == 1
    item, old = late[0]
    assert old['sent']['line'] < item['published']['line'] < old['free_note']['line']
    assert old['source_proof']['source_sha256'] == v.CONDITION_LEDGER_SOURCES
    assert old['source_proof']['observer_basis'] == 'image'
    assert old['source_proof']['observer_sha256'] == '9d7eee3fbcf2091172a4bed3f450bdf7e657e29db024404c31bb16f267786a3c'
    assert old['source_proof']['selected_initramfs_sha256'] == 'a660d798a36159b08fd337e1aca9d697d511fa6718602d4aec024a22d550d5f8'
    assert old['source_proof']['console_sha256'] == '042d72dda0dcd45594ff5926900013e3966e79e95d09ed2df107ec63b0554931'
    upm = result['native_UPM']['receipts']
    assert len(upm) == 2 and upm[0]['events']['free_return'] < upm[1]['bridge_seq']
    assert upm[0]['u'] == upm[1]['u'] == v.number(result['condition_messages'][0]['published'], 'pointer')
    assert result['UPM_messages'][-1]['freed']['line'] < result['condition_messages'][0]['published']['line']
    assert not result['condition_model_events_verified']


def test_strict_logged_pointer_reuse_needs_no_source_or_public_assets(delayed_native_log, monkeypatch):
    _, original, *_ = delayed_native_log
    log = copy.deepcopy(original)
    pubs, sends, frees = [v._kind(log, suffix, 2) for suffix in ('MESSAGE_PUBLISHED', 'MESSAGE_SENT', 'NATIVE_FREE')]
    pair = [row for p in (pubs[0], pubs[11]) for row in
            (p, next(r for r in sends if r['fields']['lease'] == p['fields']['lease']),
             next(r for r in frees if r['fields']['lease'] == p['fields']['lease']))]
    assert pair[0]['fields']['pointer'] == pair[3]['fields']['pointer']
    log.records = pair
    for line, row in enumerate(pair, 1):
        row['line'] = line
    def unexpected(*args):
        raise AssertionError('strict order must not read source evidence')
    monkeypatch.setattr(v, '_condition_source_proof', unexpected)
    assert len(v._leases(log, 2)) == 2


@pytest.mark.parametrize('mutation', ['missing-receive', 'missing-free', 'missing-send', 'receiver', 'pointer',
    'size', 'source', 'raw', 'serial', 'free-rc', 'unsent', 'alias-fault', 'other-run-trace'])
def test_delayed_conditions_never_excuse_incomplete_or_changed_lifetimes(delayed_native_log, mutation):
    run, original, *_ = delayed_native_log
    log = copy.deepcopy(original)
    p, s, f = [v._kind(log, suffix, 2)[0] for suffix in ('MESSAGE_PUBLISHED', 'MESSAGE_SENT', 'NATIVE_FREE')]
    if mutation in ('missing-free', 'missing-send'):
        log.records.remove(f if mutation == 'missing-free' else s)
    elif mutation == 'missing-receive':
        f['fields']['received'] = '0'
    elif mutation in ('receiver', 'pointer', 'size', 'free-rc'):
        key, value = {'receiver': ('receiver', '999999'), 'pointer': ('pointer', '0x1'),
                      'size': ('bytes', '19'), 'free-rc': ('rc', '-1')}[mutation]
        f['fields'][key] = value
    elif mutation in ('source', 'raw'):
        p['fields'][mutation] = '0x1' if mutation == 'source' else '00' * 20
    elif mutation == 'serial':
        v._kind(log, 'MESSAGE_PUBLISHED', 2)[1]['fields']['lease'] = p['fields']['lease']
    elif mutation == 'unsent':
        s['line'] = v._kind(log, 'MESSAGE_PUBLISHED', 2)[11]['line'] + 1
    elif mutation == 'alias-fault':
        log.records.append(dict(tag=v.STATE + '_FAULT', fields={}, raw='alias', line=1000000))
    else:
        # Still internally consistent content; a valid archive cannot bless another trace.
        p['fields']['tid'] = s['fields']['tid'] = f['fields']['sender'] = '999999'
    with pytest.raises(ValueError):
        v.verify_conditions(log, run)


@pytest.fixture
def condition_source_replay(delayed_native_log, tmp_path):
    original, log, *_ = delayed_native_log
    run, batch = tmp_path / 'source-run', tmp_path / 'source-batch'
    run.mkdir(); batch.mkdir()
    for name in ('console.log', 'observer-build-inputs.json', 'observer-build-sources.tar.gz',
                 'runtime-manifest.json', 'source-snapshot-run-binding.json'):
        (run / name).write_bytes((original / name).read_bytes())
    binding = json.loads((run / 'source-snapshot-run-binding.json').read_bytes())
    for name in ('ready.json', 'inputs.json', 'abi.json'):
        (batch / name).write_bytes((Path(binding['batch']) / name).read_bytes())
    binding.update(run=str(run), batch=str(batch))
    (run / 'source-snapshot-run-binding.json').write_text(json.dumps(binding))
    subprocess.run(['cp', '--reflink=auto', '--', str(original / 'selected-initramfs.cpio'),
                    str(run / 'selected-initramfs.cpio')], check=True, capture_output=True, timeout=30)
    retention = json.loads((original / 'selected-initramfs-retention.json').read_bytes())
    retention.update(retained_path=str(run / 'selected-initramfs.cpio'), batch=str(batch))
    (run / 'selected-initramfs-retention.json').write_text(json.dumps(retention))
    yield run, batch, log
    (run / 'selected-initramfs.cpio').unlink(missing_ok=True)


@pytest.fixture(scope='module')
def retained_observer(delayed_native_log):
    run, *_ = delayed_native_log
    with (run / 'selected-initramfs.cpio').open('rb') as stream:
        result = subprocess.run(['cpio', '-i', '--to-stdout', '--quiet', '*simulation/menu-observe.so'],
                                stdin=stream, capture_output=True, timeout=30, check=True)
    assert hashlib.sha256(result.stdout).hexdigest() == '9d7eee3fbcf2091172a4bed3f450bdf7e657e29db024404c31bb16f267786a3c'
    return result.stdout


def bind_test_image(run, raw):
    """Rebind only temporary image metadata; keep the original compiled build/ABI."""
    (run / 'selected-initramfs.cpio').write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    for name in ('runtime-manifest.json', 'source-snapshot-run-binding.json', 'selected-initramfs-retention.json'):
        path = run / name
        data = json.loads(path.read_bytes())
        if name == 'runtime-manifest.json':
            data['files'][str(BASE / 'menu-initramfs.cpio')] = digest
        elif name == 'source-snapshot-run-binding.json':
            data['guest_sha256'] = digest
        else:
            data.update(selected_initramfs_sha256=digest, bytes=len(raw))
        path.write_text(json.dumps(data))


@pytest.fixture
def condition_image_replay(condition_source_replay, retained_observer, tmp_path):
    run, batch, log = condition_source_replay
    tree = tmp_path / 'image-tree'
    (tree / 'simulation').mkdir(parents=True)
    (tree / 'simulation/menu-observe.so').write_bytes(retained_observer)
    return run, batch, log, tree


def newc_bytes(tree, names):
    result = subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--quiet'],
                            input=b''.join(name.encode() + b'\0' for name in names),
                            cwd=tree, capture_output=True, timeout=30, check=True)
    return result.stdout


@pytest.mark.parametrize('field,value', [
    ('selected_initramfs_sha256', '0' * 64), ('bytes', 552859647), ('bytes', True),
    ('retained_path', '/tmp/another-run/selected-initramfs.cpio'),
    ('source_path', '/tmp/another-initramfs.cpio'), ('batch', '/tmp/another-batch'),
    ('batch_ready_sha256', '0' * 64), ('capture_verified', True),
])
def test_retained_image_requires_exact_retention_bindings(condition_source_replay, field, value):
    run, _, log = condition_source_replay
    path = run / 'selected-initramfs-retention.json'
    data = json.loads(path.read_bytes()); data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='condition retained image'):
        v.verify_conditions(log, run)


@pytest.mark.parametrize('missing', ['selected-initramfs.cpio', 'selected-initramfs-retention.json'])
def test_incomplete_retained_pair_never_falls_back(condition_source_replay, missing):
    run, _, log = condition_source_replay
    (run / missing).unlink()
    with pytest.raises(FileNotFoundError):
        v.verify_conditions(log, run)


def test_retained_image_requires_actual_whole_bytes(condition_image_replay):
    run, _, log, tree = condition_image_replay
    original = newc_bytes(tree, ['simulation/menu-observe.so'])
    bind_test_image(run, original)
    assert v.verify_conditions(log, run)['receiver_tid']
    (run / 'selected-initramfs.cpio').write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ValueError, match='condition retained initramfs: SHA256 differs'):
        v.verify_conditions(log, run)


@pytest.mark.parametrize('damage', ['content', 'missing', 'duplicate', 'symlink', 'hardlink', 'path', 'ancestor', 'trailer'])
def test_retained_member_and_complete_newc_are_checked(condition_image_replay, damage):
    run, _, log, tree = condition_image_replay
    name = 'simulation/menu-observe.so'
    names = [name]
    if damage == 'content':
        (tree / name).write_bytes(b'observer different from original ABI')
    elif damage == 'missing':
        names = []
    elif damage == 'duplicate':
        names *= 2
    elif damage == 'symlink':
        (tree / name).unlink(); (tree / name).symlink_to('another-observer.so')
    elif damage == 'hardlink':
        os.link(tree / name, tree / 'another-observer.so')
    elif damage == 'ancestor':
        (tree / 'alias').symlink_to('simulation', target_is_directory=True)
        names = ['alias', 'alias/menu-observe.so', name]
    raw = newc_bytes(tree, names)
    if damage == 'path':
        raw = raw.replace(name.encode(), b'../' + b'x' * (len(name) - 3), 1)
    elif damage == 'trailer':
        raw += b'nonzero-after-trailer'
    bind_test_image(run, raw)
    with pytest.raises(ValueError, match='Selected initramfs'):
        v.verify_conditions(log, run)


def test_self_consistent_image_observer_metadata_cannot_replace_original_abi(condition_image_replay):
    run, batch, log, tree = condition_image_replay
    replacement = b'new observer never executed by the original ABI check'
    (tree / 'simulation/menu-observe.so').write_bytes(replacement)
    bind_test_image(run, newc_bytes(tree, ['simulation/menu-observe.so']))
    digest = hashlib.sha256(replacement).hexdigest()
    path = run / 'observer-build-inputs.json'
    build = json.loads(path.read_bytes()); build['observer_sha256'] = digest
    build_raw = json.dumps(build).encode(); path.write_bytes(build_raw)
    path = run / 'runtime-manifest.json'
    manifest = json.loads(path.read_bytes())
    manifest['compiled_observer'] = build
    manifest['files'][str(BASE / 'observer-build-inputs.json')] = hashlib.sha256(build_raw).hexdigest()
    manifest['files'][str(BASE / 'menu-observe.so')] = digest
    manifest['selected_initramfs_verified_files']['simulation/menu-observe.so'] = digest
    path.write_text(json.dumps(manifest))
    path = run / 'source-snapshot-run-binding.json'
    binding = json.loads(path.read_bytes()); binding['observer_sha256'] = digest
    path.write_text(json.dumps(binding))
    assert json.loads((batch / 'abi.json').read_bytes())['observer_sha256'] != digest
    with pytest.raises(ValueError, match='condition original ABI/source build differs'):
        v.verify_conditions(log, run)


def test_no_retained_image_keeps_actual_current_observer_check(condition_source_replay):
    run, _, log = condition_source_replay
    for name in ('selected-initramfs.cpio', 'selected-initramfs-retention.json'):
        (run / name).unlink()
    expected = json.loads((run / 'observer-build-inputs.json').read_bytes())['observer_sha256']
    assert hashlib.sha256((BASE / 'menu-observe.so').read_bytes()).hexdigest() != expected
    with pytest.raises(ValueError, match='condition actual observer: SHA256 differs'):
        v.verify_conditions(log, run)


def test_image_verifier_consumes_the_hashed_memory_snapshot(condition_image_replay):
    run, _, _, tree = condition_image_replay
    raw = newc_bytes(tree, ['simulation/menu-observe.so'])
    bind_test_image(run, raw)
    snapshot = v._ImageBytes(raw)
    (run / 'selected-initramfs.cpio').write_bytes(b'replacement after bounded read')
    expected = {'simulation/menu-observe.so': hashlib.sha256((tree / 'simulation/menu-observe.so').read_bytes()).hexdigest()}
    assert verify_image(snapshot, expected) == expected
    with pytest.raises(ValueError, match='newc header'):
        verify_image(run / 'selected-initramfs.cpio', expected)


@pytest.mark.parametrize('mutation', ['missing-archive', 'archive-bytes', 'manifest', 'run-binding',
    'observer-binding', 'batch-binding', 'selected-observer', 'abi-binding'])
def test_delayed_note_requires_original_archive_and_all_bindings(condition_source_replay, mutation):
    run, batch, log = condition_source_replay
    assert v.verify_conditions(log, run)['receiver_tid']
    if mutation in ('missing-archive', 'archive-bytes'):
        path = run / 'observer-build-sources.tar.gz'
        if mutation == 'missing-archive':
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b'tampered')
    elif mutation == 'abi-binding':
        path = batch / 'abi.json'
        data = json.loads(path.read_bytes()); data['observer_sha256'] = '0' * 64
        path.write_text(json.dumps(data))
    else:
        path = batch / 'ready.json' if mutation == 'batch-binding' else run / (
            'runtime-manifest.json' if mutation in ('manifest', 'selected-observer') else 'source-snapshot-run-binding.json')
        data = json.loads(path.read_bytes())
        if mutation == 'manifest':
            data['compiled_observer']['source_archive_sha256'] = '0' * 64
        elif mutation == 'selected-observer':
            data['selected_initramfs_verified_files']['simulation/menu-observe.so'] = '0' * 64
        elif mutation == 'run-binding':
            data['run'] += '-wrong'
        elif mutation == 'observer-binding':
            data['observer_sha256'] = '0' * 64
        else:
            data['inputs_sha256'] = '0' * 64
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        v.verify_conditions(log, run)


@pytest.mark.parametrize('relative', tuple(v.CONDITION_LEDGER_SOURCES))
def test_changed_archived_guard_is_not_approved_by_self_consistent_metadata(condition_source_replay, relative):
    run, batch, log = condition_source_replay
    build = json.loads((run / 'observer-build-inputs.json').read_bytes())
    path = run / 'observer-build-sources.tar.gz'
    with tarfile.open(fileobj=io.BytesIO(path.read_bytes())) as archive:
        members = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
    source = str(BASE / relative)
    entry = build['sources'][source]
    if relative == 'device-models/hdmi-video-state.c':
        members[entry['archive_path']] = members[entry['archive_path']].replace(
            b'pointer==state.retained_request || find(pointer)', b'pointer==state.retained_request')
    else:
        members[entry['archive_path']] += b'\n'
    entry['sha256'] = hashlib.sha256(members[entry['archive_path']]).hexdigest()
    assert entry['sha256'] != v.CONDITION_LEDGER_SOURCES[relative]
    members['source-inputs.json'] = json.dumps(build['sources']).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, value in members.items():
            member = tarfile.TarInfo(name); member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    path.write_bytes(output.getvalue())
    build['source_archive_sha256'] = hashlib.sha256(output.getvalue()).hexdigest()
    build_raw = json.dumps(build).encode()
    (run / 'observer-build-inputs.json').write_bytes(build_raw)
    manifest = json.loads((run / 'runtime-manifest.json').read_bytes())
    manifest['compiled_observer'] = build
    manifest['files'][str(BASE / 'observer-build-inputs.json')] = hashlib.sha256(build_raw).hexdigest()
    (run / 'runtime-manifest.json').write_text(json.dumps(manifest))
    tested = json.loads((batch / 'inputs.json').read_bytes())
    tested['groups']['production'][source] = entry['sha256']
    tested_raw = json.dumps(tested).encode(); (batch / 'inputs.json').write_bytes(tested_raw)
    ready = json.loads((batch / 'ready.json').read_bytes())
    ready['inputs_sha256'] = hashlib.sha256(tested_raw).hexdigest()
    ready_raw = json.dumps(ready).encode(); (batch / 'ready.json').write_bytes(ready_raw)
    binding = json.loads((run / 'source-snapshot-run-binding.json').read_bytes())
    binding['batch_ready_sha256'] = hashlib.sha256(ready_raw).hexdigest()
    (run / 'source-snapshot-run-binding.json').write_text(json.dumps(binding))
    with pytest.raises(ValueError, match='unreviewed condition ledger/hook source'):
        v.verify_conditions(log, run)


def test_native_upm_never_inherits_condition_delayed_note_rule(delayed_native_log):
    run, original, *_ = delayed_native_log
    log = copy.deepcopy(original)
    retired = v._kind(log, 'KERNEL_RETIRED', 3)
    retired[0]['line'] = v._kind(log, 'MESSAGE_PUBLISHED', 3)[1]['line'] + 1
    with pytest.raises(ValueError):
        v._leases(log, 3, native=True, run=run)
    log = copy.deepcopy(original)
    extra = copy.deepcopy(v._kind(log, 'KERNEL_RETIRED', 3)[0])
    extra['tag'] = v.STATE + '_NATIVE_FREE'; log.records.append(extra)
    with pytest.raises(ValueError, match='only two kernel retirements'):
        v.verify_hdmi_upm(log, run)


@pytest.fixture(scope='module')
def successful_native_log():
    run = BASE / 'menu-runs/run-xgs_bvga'
    if not (run / 'hdmi-upm-watch-events.jsonl').is_file():
        pytest.skip('explicit successful HDMI11 run is unavailable')
    log = Log((run / 'console.log').read_text())
    previous = v.one(log, 'FULL_PINMEM_DRAWINFO_CONNECT_NATIVE_REPLY_FREE')['line']
    first = v.one(log, 'FULL_IMAGING_PIN_CONNECT_REQUEST')['line']
    return run, log, previous, first


def test_successful_actual_hdmi11_full_content(successful_native_log):
    run, log, previous, first = successful_native_log
    result = v.verify_hdmi_edge(log, previous, ('258', '381'), first, run)
    assert result['full_native_effects_verified']
    assert len(result['condition_messages']) == 24
    assert len(result['prefix_reply_retirements']) == 3
    assert len(result['native_UPM']['receipts']) == 2
    assert result['condition_receiver_tid'] == '349'
    assert result['backup_inputs']['public_CP_bank_verified']
    assert not result['backup_inputs']['AP_runtime_bytes_independently_logged']
    assert not result['condition_model_events_verified']
    assert not result['condition_receive_site_runtime_logged']
    assert not result['capture_verified']
    # Repeated addresses are separate complete leases, never deduplicated.
    assert len({x['published']['fields']['pointer'] for x in result['condition_messages']}) < 24
    assert any(x['freed']['line'] < x['sent']['line'] for x in result['condition_messages'])


@pytest.mark.parametrize('tag,field,value,index', [
    ('FULL_PINMEM_NATIVE_REPLY_FREE', 'sender', '999999', -1),
    ('FULL_HDMIPIN_COMMIT', 'slot', '1', -1),
    ('FULL_HDMIPIN_COMMIT', 'type', '5', -1),
    ('HDMI_PHOTO_REQUEST', 'value', '0x81cf618c', 2),
    ('FULL_HDMI_VIDEO_BACKUP_READ', 'rc', '-1', 8),
    ('FULL_HDMI_VIDEO_BACKUP_READ', 'source', 'AP-runtime', 2),
    ('FULL_HDMI_VIDEO_STATE_DRIVER_CONSUMED', 'config', '00' * 36, 0),
])
def test_full_edge_get_subscription_and_backup_mutations(successful_native_log, tag, field, value, index):
    run, log, previous, first = successful_native_log
    candidate = copy.deepcopy(log)
    start = v.one(candidate, v.PREFIX + '_REQUEST')['line']
    rows = candidate.rows(tag)
    if tag in ('FULL_PINMEM_NATIVE_REPLY_FREE', 'FULL_HDMIPIN_COMMIT'):
        rows = [row for row in rows if previous < row['line'] < start]
        assert len(rows) == 1
        rows[0]['fields'][field] = value
    else:
        rows[index]['fields'][field] = value
    with pytest.raises(ValueError):
        v.verify_hdmi_edge(candidate, previous, ('258', '381'), first, run)


def test_host_trace_cannot_pass_without_native_receipts(host_log, tmp_path):
    with pytest.raises((ValueError, OSError)):
        v.verify_hdmi_upm(host_log, tmp_path / 'no-native-run')


@pytest.fixture
def native_replay(tmp_path, monkeypatch):
    # Explicitly supplied completed UPM-only run, never discover/poll another run.
    original = BASE / 'menu-runs/run-_vpkt22p'
    if not (original / 'hdmi-upm-watch-events.jsonl').is_file():
        pytest.skip('explicit actual native UPM replay run is unavailable')
    run = tmp_path / 'offline-replay'
    run.mkdir(mode=0o700)
    for name in ('hdmi-upm-watch-config.json', 'hdmi-upm-watch-events.jsonl',
                 'hdmi-upm-watch-result.json', 'hdmi-upm-coordinator.json'):
        (run / name).write_bytes((original / name).read_bytes())
    path = run / 'hdmi-upm-watch-config.json'
    config = json.loads(path.read_bytes())
    config.update(run=str(run), run_device=run.stat().st_dev, run_inode=run.stat().st_ino)
    path.write_text(json.dumps(config))
    monkeypatch.setattr(v._watch(), 'RUNS', tmp_path)
    return run, Log((original / 'console.log').read_text())


def test_actual_two_native_upm_receipts_join_without_full_edge_claim(native_replay):
    run, log = native_replay
    result = v.verify_hdmi_upm(log, run)
    assert result['native_UPM_verified'] and not result['full_edge_verified']
    assert [r['lease_serial'] for r in result['receipts']] == [4, 5]
    assert [r['tid'] for r in result['receipts']] == [205, 205]
    assert [r['raw_hex'] for r in result['receipts']] == [
        '170192000000000000009a0000000000', '170192000200000000009a0000000000']
    assert result['receipts'][1]['effective_hex'] == '170192000300000000009a0000000000'
    with pytest.raises(ValueError):
        v.verify_hdmi_edge(log, 1, ('258', '381'), 1, run)


@pytest.mark.parametrize('mutation', ['raw', 'effective', 'kernel-tid', 'mapping', 'branch', 'return-rc',
                                     'missing-free', 'missing-allocator', 'early-bridge'])
def test_independent_native_decoder_rejects_changed_events(native_replay, mutation):
    run, log = native_replay
    path = run / 'hdmi-upm-watch-events.jsonl'
    events = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == 'raw':
        row = next(e for e in events if e['kind'] == 'bridge')
        row['memory']['body']['hex'] = '170192000100000000009a0000000000'
    elif mutation == 'effective':
        row = [e for e in events if e['kind'] == 'branch'][-1]
        row['memory']['body']['hex'] = '170192000400000000009a0000000000'
    elif mutation == 'kernel-tid':
        next(e for e in events if e['kind'] == 'receive')['kernel_tid'] = 3
    elif mutation == 'mapping':
        row = next(e for e in events if e['kind'] == 'bridge')
        row['memory']['kernel_pool']['hex'] = '0000000000000000'
    elif mutation == 'branch':
        next(e for e in events if e['kind'] == 'branch')['registers']['x2'] = 0
    elif mutation == 'return-rc':
        next(e for e in events if e['kind'] == 'free_return')['registers']['x0'] = 1
    elif mutation == 'missing-free':
        events.remove(next(e for e in events if e['kind'] == 'free_return'))
    elif mutation == 'missing-allocator':
        events.remove(next(e for e in events if e['kind'] == 'vpool_fallback'))
    else:
        bridge = [e for e in events if e['kind'] == 'bridge'][1]
        events.remove(bridge)
        events.insert(next(i for i, e in enumerate(events) if e['kind'] == 'free_return'), bridge)
        for seq, row in enumerate(events, 1):
            row['seq'] = seq
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))
    with pytest.raises(ValueError):
        v.verify_hdmi_upm(log, run)


@pytest.mark.parametrize('mutation', ['missing-commit', 'commit-sha', 'unsafe-cleanup', 'wrong-nonce', 'wrong-effective'])
def test_mailbox_and_cleanup_are_required(native_replay, mutation):
    run, log = native_replay
    if mutation in ('missing-commit', 'commit-sha'):
        path = run / 'hdmi-upm-watch-result.json'
        result = json.loads(path.read_bytes())
        if mutation == 'missing-commit':
            result['mailbox_deliveries'].pop()
        else:
            result['mailbox_deliveries'][0]['record_sha256'] = '0' * 64
        path.write_text(json.dumps(result))
    elif mutation == 'unsafe-cleanup':
        path = run / 'hdmi-upm-coordinator.json'
        result = json.loads(path.read_bytes())
        result['cleanup']['safe_to_close'] = False
        path.write_text(json.dumps(result))
    elif mutation == 'wrong-nonce':
        log = change(log, 'FULL_HDMI_UPM_MAILBOX_CONSUMED', 'nonce', '0x1')
    else:
        log = change(log, 'FULL_HDMI_UPM_MAILBOX_CONSUMED', 'effective', '170192000200000000009a0000000000', 1)
    with pytest.raises(ValueError):
        v.verify_hdmi_upm(log, run)
