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


def archived_receipt(variable):
    value = os.environ.get(variable)
    if not value:
        pytest.skip('historical original receipt and its exact dependency closure required: set ' + variable)
    return Path(value)


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
    """Reuse the old envelope builder; real fixed source7/fixture7 and build assets, synthetic receipts."""
    f = make_scope_binding(tmp_path, monkeypatch, 2)
    native = BASE.parents[1]
    monkeypatch.setattr(f.graph, 'NATIVE', native)
    f.reader.object_json = f.graph.object_json
    prototype = json.loads(archived_receipt('A7C2_SHUTTER_PARENT_RECEIPT').read_bytes())
    ref = prototype['gate_build_receipt']
    built = json.loads(Path(ref['path']).read_bytes())
    keys = ('build_receipt', 'build_receipt_sha256', 'library_sha256', 'qemu_sha256', 'qemu_header_sha256',
        'source_sha256', 'trace_schema', 'trace_schema_sha256', 'source_contract_sha256', 'fixture_source_sha256',
        'plugin_build_command_sha256', 'readonly_import_audit_sha256', 'candidate_static_audit_sha256')
    metadata = {key: copy.deepcopy(built[key]) for key in keys if key not in ('build_receipt', 'build_receipt_sha256')}
    metadata.update(profile=v.SHUTTER_GATE_PROFILE, library=built['library'], build_receipt=ref['path'],
        build_receipt_sha256=ref['sha256'], identity_binding='unverified', capture_verified=False,
        physical_asic_compatibility_verified=False)
    projection = copy.deepcopy(prototype['expected_original_run_assets'])
    expected = dict(projection, profile=v.SHUTTER_GATE_PROFILE, trace_schema='readonly_shutter_gate_v1',
        source_contract_sha256=built['source_contract_sha256'], build_receipt=ref['path'],
        library_source=built['library'], build_metadata=metadata,
        functional_runner_source_sha256=f.sha(BASE / 'functional_camera_runner.py'))
    baseline = Path(prototype['batch']) / 'inputs.json'
    f.tested = json.loads(baseline.read_bytes())
    for group in f.tested['groups'].values():
        for path in group:
            group[path] = f.sha(Path(path))
    b = f.binding
    b.update(schema=v.SHUTTER_GATE_RUN, observer_sha256=projection['observer_sha256'],
        scope_observer_expected=expected, shutter_gate_reader_expected=projection,
        candidate_qemu=dict(path=built['qemu'], sha256=built['qemu_sha256']),
        runtime_assets_sha256=dict(prototype['legacy_runtime_assets_sha256'], **prototype['gate_added_runtime_assets_sha256']),
        synthetic_fixture_manifest=copy.deepcopy(prototype['gate_actual_api']['manifest']),
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.observer = b['observer_sha256']
    f.build['sources'][str(BASE / 'menu-observe.c')]['sha256'] = projection['Main_source_sha256']
    f.manifest.update(backup_transport=dict(binary=built['qemu'], binary_sha256=built['qemu_sha256']))
    f.manifest['selected_initramfs_verified_files']['usr/lib/appFw.so'] = projection['original_appfw_sha256']
    f.manifest['files'][built['qemu']] = built['qemu_sha256']
    root = native / v.SHUTTER_GATE_COMPONENT
    f.manifest['files'].update({str(root / name): value for name, value in built['source_sha256'].items()})
    f.manifest['files'][ref['path']] = ref['sha256']
    (f.run / 'readonly-scope-observer.so').write_bytes(Path(built['library']).read_bytes())
    f.manifest['files'][str(f.run / 'readonly-scope-observer.so')] = built['library_sha256']
    batch = Path(b['batch']); batch.mkdir()
    parent_path = f.work / 'parent-readback.json'
    parent = copy.deepcopy(prototype)
    parent.update(batch=str(batch), ready_sha256=b['batch_ready_sha256'])
    f.write(parent_path, parent)
    b['parent_readback'] = dict(path=str(parent_path), sha256=f.sha(parent_path))
    b['actual_api_contract'] = copy.deepcopy(b['parent_readback'])
    runtime_path = batch / 'readonly-shutter-gate-v1-runtime-ready.json'
    runtime = dict(status='PASS_NEW_OFFLINE_SHUTTER_GATE_V1_SUPPLEMENT',
        generic_ready=dict(path=str(batch / 'ready.json'), sha256=b['batch_ready_sha256']),
        offline_readback=copy.deepcopy(b['parent_readback']), expected_original_run_assets=projection,
        gate_build_receipt=ref, launch_runtime_preflight=dict(passed=False, inspected=False, launch_authorized=False),
        **{key: False for key in ('runtime_verified', 'capture_verified', 'physical', 'physical_asic_compatibility_verified',
            'originalMain', 'retirement', 'instruction_retirement_verified', 'Main_identity_verified',
            'AP_identity_verified', 'branch_edge_verified', 'invocation_pairing_verified', 'original_camera_VM_started',
            'originalUI_onceplan_prepared', 'intent_published', 'card_prepared')})
    f.write(runtime_path, runtime)
    b['runtime_ready'] = dict(path=str(runtime_path), sha256=f.sha(runtime_path))
    fresh_path = Path(b['fresh_guest']['path'])
    fresh = json.loads(fresh_path.read_bytes())
    fresh.update(runtime_ready_sha256=b['runtime_ready']['sha256'],
        compiled_before={str(BASE / 'menu-observe.so'): f.observer}, compiled_after={str(BASE / 'menu-observe.so'): f.observer})
    f.write(fresh_path, fresh)
    b['fresh_guest']['sha256'] = f.sha(fresh_path)
    driver = BASE / 'scratch/run-functional-current-batch.py'
    plan = {key: copy.deepcopy(b[key]) for key in ('nonce', 'batch', 'batch_ready_sha256', 'runtime_ready',
        'parent_readback', 'fresh_guest', 'runtime_assets_sha256', 'actual_api_contract', 'candidate_qemu', 'card')}
    plan.update(schema='functional-shutter-gate-v1-plan-v1', guest_image=str(f.guest), scope_build=ref,
        actual_api_manifest=b['synthetic_fixture_manifest'], driver=str(driver), driver_sha256=f.sha(driver),
        claimed_fault_result='FAIL', **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.plan, f.parent, f.runtime = plan, parent, runtime
    f.metadata, f.expected, f.source_root = metadata, expected, root
    f.launch_owner = dict(pid=101, ppid=1, starttime=101, exe='/usr/bin/python3')
    refresh_shutter_binding(f)
    return f


def refresh_shutter_binding(f):
    """Rebind all synthetic hashes so a negative reaches its intended content guard."""
    b = f.binding
    generation = getattr(f, 'generation', 'functional-shutter-gate-v1')
    f.write(f.work / 'plan.json', f.plan)
    fields = v.SHUTTER_GATE_PLAN_FIELDS + ('observer_sha256', 'guest_sha256', 'candidate_qemu', 'card')
    common = {key: copy.deepcopy(b[key]) for key in fields}
    common.update(plan=str(f.work / 'plan.json'), plan_sha256=f.sha(f.work / 'plan.json'),
        driver=f.plan['driver'], driver_sha256=f.plan['driver_sha256'], claimed_fault_result='FAIL',
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.write(f.work / 'intent.json', dict(common, schema=generation + '-intent-v1', guest_image=str(f.guest)))
    b['intent_sha256'] = f.sha(f.work / 'intent.json')
    f.write(f.work / 'launch-binding.json', dict(common, schema=generation + '-launch-v1',
        intent_sha256=b['intent_sha256'], launch_owner=f.launch_owner))
    b['launch_binding_sha256'] = f.sha(f.work / 'launch-binding.json')
    plan_binding = {key: copy.deepcopy(b[key]) for key in v.SHUTTER_GATE_PLAN_FIELDS}
    f.manifest['readonly_scope_observer'] = dict(f.metadata, library=str(f.run / 'readonly-scope-observer.so'),
        log=str(f.run / 'readonly-scope-trace.log'), plan_binding=plan_binding)
    info = f.run.stat()
    context = dict(schema=generation + '-live-context-v1', run=str(f.run),
        run_device=info.st_dev, run_inode=info.st_ino, scope=plan_binding,
        **{key: copy.deepcopy(b[key]) for key in ('nonce', 'batch', 'batch_ready_sha256', 'intent_sha256',
                                               'launch_binding_sha256', 'candidate_qemu', 'card')})
    f.context = context
    live = dict(schema=generation + '-popen-live-v1', context=context,
        wrapper=dict(pid=202, ppid=201, starttime=202, exe='/usr/bin/bash'),
        owner=dict(pid=201, ppid=200, starttime=201, exe='/usr/bin/python3'),
        control=dict(pid=200, ppid=101, starttime=200, exe='/usr/bin/python3'),
        actual_Popen_pid=202, birth_sample={}, launch_policy={}, control_mode='probe-parent',
        probe_source_sha256=f.sha(v.BASE / 'qemu-menu-probe.py'), **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    live['birth_sample'] = dict(identity=copy.deepcopy(live['wrapper']))
    live['launch_policy'] = dict(model='approved-functional-shell-bwrap-v1')
    f.write(f.run / 'readonly-scope-popen-live.json', live)
    b['popen_live_sha256'] = f.sha(f.run / 'readonly-scope-popen-live.json')
    f.write(f.run / 'readonly-scope-run-binding.json', b)
    ancestry = dict(schema=generation + '-live-ancestry-v1', context=context,
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
    f.write(f.run / 'readonly-scope-exit.json', dict(profile=f.metadata['profile'], run=str(f.run),
        owned_wrapper_pid=202, returncode=0, library_sha256=f.metadata['library_sha256'],
        log_available=True, log_sha256=f.sha(f.run / 'readonly-scope-trace.log'), capture_verified=False,
        physical_asic_compatibility_verified=False))
    callback = dict(schema=generation + '-popen-exit-v1', context=context, wrapper=live['wrapper'],
        actual_Popen_pid=202, returncode=0, popen_live_sha256=b['popen_live_sha256'],
        ancestry_sha256=f.sha(f.run / 'readonly-scope-live-ancestry.json'),
        original_exit_sha256=f.sha(f.run / 'readonly-scope-exit.json'), **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.write(f.run / 'readonly-scope-popen-exit-binding.json', callback)


def scope_provenance(fixture, *, gate_v2_trust=None):
    name, binding, original = v._condition_binding(fixture.graph, fixture.run, fixture.observer)
    assert name == 'readonly-scope-run-binding.json'
    assert original == (fixture.run / name).read_bytes()
    return v._condition_scope_binding(fixture.graph, fixture.reader, fixture.run,
        binding, fixture.manifest, fixture.build, fixture.tested,
        **({} if gate_v2_trust is None else {'gate_v2_trust': gate_v2_trust}))


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


def make_gate_v2_binding(tmp_path, monkeypatch):
    """Synthetic graph closure. Strict trace/ELF adapters are byte-checking spies, never QEMU receipts."""
    f = make_scope_binding(tmp_path, monkeypatch, 2)
    native, base = f.graph.NATIVE, f.graph.NATIVE / 'runtime/analysis'
    monkeypatch.setattr(v, 'BASE', base)
    f.generation = 'functional-shutter-gate-v2'
    f.reader.object_json, f.reader.MAX_FILE = f.graph.object_json, 16 * 1024**2
    f.tested = dict(groups={key: {} for key in ('production', 'host', 'observer', 'test')}, modules=[], capture_verified=False)
    ref = lambda path: dict(path=str(path), sha256=f.sha(path))
    def source(path, raw, group='observer'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        f.tested['groups'][group][str(path)] = f.sha(path)
        return str(path)
    def archive_check(raw, wanted):
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            members = {row.name: hashlib.sha256(archive.extractfile(row).read()).hexdigest() for row in archive}
        assert members == wanted
    f.reader.archive = archive_check
    for name in ('functional_camera_runner.py', 'scope_observer_profile.py', 'hdmi_upm_watch.py',
                 'scratch/verify_hdmi_edge.py', 'scratch/validate-unified-camera.py',
                 'scratch/run-functional-current-batch.py', 'qemu-menu-probe.py'):
        source(base / name, ('synthetic host source ' + name).encode(), 'host')
    source(base / 'menu-observe.c', b'synthetic frozen Main source', 'production')
    for name in ('scratch/test_verify_hdmi_edge.py', 'test_second_module.py'):
        f.tested['modules'].append(source(base / name, b'# synthetic module\n', 'test'))
    for relative in f.graph.FROZEN_DEPENDENCIES:
        path = native / relative
        if str(path) not in {name for group in f.tested['groups'].values() for name in group}:
            source(path, ('synthetic frozen dependency ' + relative).encode())
    observer = hashlib.sha256(b'synthetic observer').hexdigest()
    f.binding.update(schema=v.SHUTTER_GATE_V2_RUN, observer_sha256=observer,
        **dict.fromkeys(v.SHUTTER_GATE_FALSE_FIELDS, False))
    f.observer = observer
    f.build = dict(sources={name: dict(sha256=value) for name, value in f.tested['groups']['production'].items()},
        source_archive_sha256=hashlib.sha256(b'synthetic observer source archive').hexdigest())
    qemu = tmp_path / 'candidate/build/qemu-system-aarch64'
    qemu.parent.mkdir(parents=True); qemu.write_bytes(b'synthetic candidate bytes')
    production = tmp_path / 'protected-production'; production.write_bytes(b'synthetic production bytes')
    legacy_default = tmp_path / 'protected-legacy-default'; legacy_default.write_bytes(b'synthetic legacy default bytes')
    monkeypatch.setattr(f.graph, 'PRODUCTION_QEMU_SHA256', f.sha(production))
    monkeypatch.setattr(v, 'SHUTTER_GATE_V2_LEGACY_DEFAULT_SHA', f.sha(legacy_default))
    f.binding['candidate_qemu'] = ref(qemu)
    audit_path = qemu.parents[1] / 'binary-static-audit.json'
    f.write(audit_path, dict(binary=str(qemu), binary_sha256=f.sha(qemu), missing_required_exports=[],
        protected_binaries_unchanged=dict(candidate=True, production=True),
        **dict.fromkeys(('runtime_library_closure_verified', 'plugin_runtime_verified',
                        'capture_verified', 'physical_asic_compatibility_verified'), False)))
    f.metas, f.api, f.roots, f.helpers, f.parsers, f.adapter_calls = {}, {}, {}, {}, {}, []
    specs = (('scope2', 'report/2026-10-30-qemu-readonly-scope-observer', 'qemu-readonly-scope-v2',
        'readonly_scope_v2', v.SCOPE_SOURCE_NAMES, 2),
        ('scope3', 'report/2026-10-31-qemu-M-writer-observer-v3', 'qemu-readonly-scope-v3',
         'readonly_scope_v3', v.SCOPE_SOURCE_NAMES_V3, 3),
        ('gate1', v.SHUTTER_GATE_COMPONENT, v.SHUTTER_GATE_PROFILE, 'readonly_shutter_gate_v1', v.SHUTTER_GATE_SOURCE_NAMES, 1),
        ('gate2', v.SHUTTER_GATE_V2_COMPONENT, v.SHUTTER_GATE_V2_PROFILE, 'readonly_shutter_gate_v2', v.SHUTTER_GATE_V2_SOURCE_NAMES, 2))
    for key, component, profile, schema, names, version in specs:
        root = native / component
        fixtures = (v.SHUTTER_GATE_V2_FIXTURE_NAMES if key == 'gate2' else v.SHUTTER_GATE_FIXTURE_NAMES
                    if key == 'gate1' else ('integration/fixture.S', 'integration/link.ld',
                        'integration/run_fixture.py', 'integration/test_fixture_driver.py',
                        'integration/test_actual_scope_plugin.py', 'integration/scope_trace_checks.py',
                        'integration/scope_trace_checks_v%d.py' % version, 'integration/test_scope_trace_checks_v%d.py' % version))
        for name in set(names) | set(fixtures):
            source(root / name, ('synthetic source ' + key + '/' + name).encode())
        schema_name = ('log-schema-shutter-gate-v%d.json' if key.startswith('gate') else 'log-schema-v%d.json') % version
        contract_name = ('source-contract-shutter-gate-v%d.json' if key.startswith('gate') else 'source-contract-v%d.json') % version
        source(root / schema_name, json.dumps(dict(profile=profile, schema=schema)).encode())
        source(root / contract_name, json.dumps(dict(profile=profile, trace_schema=schema)).encode())
        sources, fixture_sources = ({name: f.sha(root / name) for name in values} for values in (names, fixtures))
        pins = root / 'integration/fixture-source-pins.json'
        source(pins, json.dumps(fixture_sources, sort_keys=True).encode())
        plugin_work = tmp_path / ('plugin-' + key); plugin_work.mkdir()
        library = plugin_work / 'scope-observer.so'; library.write_bytes(('synthetic library ' + key).encode())
        for name in ('plugin-build-command.json', 'readonly-import-audit.json'):
            f.write(plugin_work / name, dict(synthetic=key))
        receipt_path = plugin_work / 'build-receipt.json'
        metadata = dict(profile=profile, trace_schema=schema, library=str(library), library_sha256=f.sha(library),
            build_receipt=str(receipt_path), qemu_sha256=f.sha(qemu), qemu_header_sha256=hashlib.sha256(b'header').hexdigest(),
            source_sha256=sources, fixture_source_sha256=fixture_sources, trace_schema_sha256=f.sha(root / schema_name),
            source_contract_sha256=f.sha(root / contract_name),
            plugin_build_command_sha256=f.sha(plugin_work / 'plugin-build-command.json'),
            readonly_import_audit_sha256=f.sha(plugin_work / 'readonly-import-audit.json'),
            candidate_static_audit_sha256=f.sha(audit_path), identity_binding='unverified', capture_verified=False,
            physical_asic_compatibility_verified=False)
        f.write(receipt_path, metadata)
        metadata['build_receipt_sha256'] = f.sha(receipt_path)
        f.metas[key], f.roots[key] = metadata, root
        folder = tmp_path / ('api-' + key); folder.mkdir()
        inputs = dict(qemu=ref(qemu), plugin=ref(library), receipt=ref(receipt_path), schema=ref(root / schema_name))
        inputs.update({'source:' + name: ref(root / name) for name in names})
        inputs.update({'fixture-source:' + name: ref(root / name) for name in fixtures})
        if key.startswith('gate'):
            inputs['fixture_sources_file'] = ref(pins)
        cases = v.SHUTTER_GATE_API_CASES if key.startswith('gate') else (
            'anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer', 'producer_corrupt', 'producer_short_tb')
        if key == 'scope3':
            cases = ('anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
                     'producer_reverse_order', 'producer_corrupt', 'producer_short_tb')
        actual = dict(profile=profile, trace_schema=schema,
            status=('PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V%d_FIXTURE' if key.startswith('gate')
                    else 'PASS_SELF_OWNED_QEMU_SCOPE_V%d_FIXTURE') % version,
            failure=None, inputs=inputs, variants={}, startup_negatives={}, commands=[], artifacts={},
            fixture_source_sha256=fixture_sources, fixture_source_snapshots={}, trace_schema_sha256=f.sha(root / schema_name),
            **dict.fromkeys(('capture_verified', 'physical_asic_compatibility_verified', 'Main_identity_verified',
                'AP_identity_verified', 'instruction_retirement_verified', 'branch_edge_verified', 'retirement'), False))
        summaries, expected_operands = {}, {}
        producer_path = BASE.parents[1] / component / 'integration/run_fixture.py'
        producer_spec = importlib.util.spec_from_file_location('_synthetic_command_oracle_' + key, producer_path)
        command_oracle = importlib.util.module_from_spec(producer_spec)
        producer_spec.loader.exec_module(command_oracle)
        producer_function = next(node for node in ast.parse(producer_path.read_bytes()).body
                                 if isinstance(node, ast.FunctionDef) and node.name == 'run_fixture')
        compile_values = [node.value for node in ast.walk(producer_function) if isinstance(node, ast.Assign)
                          and isinstance(node.value, ast.List) and any(isinstance(value, ast.Constant)
                          and value.value == '--target=aarch64-linux-gnu' for value in node.value.elts)]
        assert len(compile_values) == 1
        compile_payload = compile(ast.Expression(compile_values[0]), str(producer_path), 'eval')
        def command_receipt(directory, returncode):
            is_gate = key.startswith('gate')
            negative = directory in ('cases/missing_log_argument', 'cases/existing_log')
            case = directory.split('/', 1)[1] if directory.startswith('build/') else (
                ('original_entry' if is_gate else 'anchor') if negative else directory.split('/', 1)[1].rsplit('-', 1)[0])
            short = case in ('short_tb', 'producer_short_tb')
            built = ('original_entry' if is_gate else 'producer') if short else case
            seconds = 60 if directory.startswith('build/') else 30
            if directory.startswith('build/'):
                payload = eval(compile_payload, {'__builtins__': {'int': int}}, dict(clang=command_oracle.tool('clang'),
                    case=case, mutated=case == 'one_byte_mutation', wrong_only=case == 'wrong_lr_only',
                    producer=case.startswith('producer'), producer_mutated=case == 'producer_corrupt',
                    producer2_mutated=case == 'producer_corrupt', reverse=case == 'producer_reverse_order'))
                mounts = [(folder / 'inputs', '/src')]
            else:
                options = [] if directory == 'cases/missing_log_argument' else (
                    ['log=/out/plugin.log'] if directory.endswith('-plugin') or directory == 'cases/existing_log' else None)
                payload = command_oracle.vm_command(options, short) if is_gate else command_oracle.vm_command(
                    options, case.startswith('producer'), short)
                mounts = [(qemu, '/qemu'), (library, '/observer.so'), (folder / ('build/' + built + '/fixture.elf'), '/in/fixture.elf')]
            row = dict(command=command_oracle.sandbox(folder / directory, mounts) + [command_oracle.tool('timeout'),
                '--signal=TERM', '--verbose', str(seconds) + 's'] + payload,
                directory=directory, owned_pid_unreaped=None, returncode=returncode, limit_seconds=seconds)
            if is_gate:
                row.update(outer_timeout=False, payload_argv=payload)
            return row
        def artifact(name, raw, folder=folder, actual=actual):
            path = folder / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            actual['artifacts'][name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        for case in cases:
            gate = key.startswith('gate')
            build_case = ('original_entry' if gate else 'producer') if case in ('short_tb', 'producer_short_tb') else case
            elf_name = 'build/' + build_case + '/fixture.elf'
            artifact(elf_name, ('synthetic elf ' + build_case).encode())
            operands = dict(case=case)
            expected_operands[case] = operands
            raw = ('synthetic trace ' + key + ':' + case + '\n').encode()
            consoles = json.dumps(operands, sort_keys=True).encode()
            counters = dict(successful_callbacks=5 if key == 'gate2' else 4)
            runs = {}
            for mode in ('baseline', 'plugin'):
                directory = 'cases/' + case + '-' + mode
                artifact(directory + '/console.bin', consoles)
                runs[mode] = dict(console=directory + '/console.bin', returncode=0,
                    plugin_log=directory + '/plugin.log' if mode == 'plugin' else None)
            artifact('cases/' + case + '-plugin/plugin.log', raw)
            if gate:
                operand_name = 'cases/' + case + '-baseline/independent-operands.json'
                artifact(operand_name, consoles)
                artifact('cases/' + case + '-baseline/boundary-metadata.json', b'{}')
                summaries[case] = dict(trace_sha256=hashlib.sha256(raw).hexdigest(), rows=1,
                    actual_callback_counts=counters, independent_console_operands=True)
            else:
                summaries[case] = dict(independent_console_operands=True)
            actual['variants'][case] = dict(runs=runs, elf=elf_name, elf_sha256=f.sha(folder / elf_name),
                program_baseline_equal=True, guest_selfcheck_and_code_readback_exact=True,
                expected_operands='cases/' + case + '-baseline/independent-operands.json',
                expected_operands_sha256=hashlib.sha256(consoles).hexdigest(), boundary_metadata={},
                trace_adapter='shutter_gate_trace_checks_v%d.assert_shutter_gate_trace_v%d' % (version, version),
                actual_callback_counts=counters, trace_sha256=hashlib.sha256(raw).hexdigest())
            directories = ([] if case in ('short_tb', 'producer_short_tb') else ['build/' + case])
            directories += ['cases/' + case + '-' + mode for mode in ('baseline', 'plugin')]
            for directory in directories:
                actual['commands'].append(command_receipt(directory, 0))
                artifact(directory + '/stdout.bin', b'')
                artifact(directory + '/stderr.bin', b'')
        for name in ('missing_log_argument', 'existing_log'):
            directory = 'cases/' + name
            actual['commands'].append(command_receipt(directory, 1))
            artifact(directory + '/stdout.bin', b'')
            artifact(directory + '/stderr.bin', b'scope_observer_host_error')
            actual['startup_negatives'][name] = dict(returncode=1, guest_started=False)
            if key.startswith('gate'):
                actual['startup_negatives'][name].update(normal_non_timeout_rejection=True, sentinel_unchanged=name == 'existing_log')
        artifact('cases/existing_log/plugin.log', b'exclusive-shutter-gate-log-sentinel\n'
                 if key.startswith('gate') else b'exclusive-log-sentinel\n')
        api_path = folder / 'manifest.json'; f.write(api_path, actual)
        f.api[key] = dict(manifest=ref(api_path), cases=summaries)
        def validate(*args, inputs=copy.deepcopy(inputs), schema_path=root / schema_name, gate=key.startswith('gate'), **kwargs):
            value = copy.deepcopy(inputs)
            value.pop('fixture_sources_file', None)
            return (value, json.loads(schema_path.read_bytes())) if gate else value
        def parse(raw, declaration, key=key, schema=schema, expected_operands=expected_operands):
            assert declaration['schema'] == schema
            allowed = {('synthetic trace ' + key + ':' + case + '\n').encode() for case in expected_operands}
            if key == 'gate2':
                allowed.add(b'synthetic raw observer bytes; no UPM or AP claim\n')
            assert raw in allowed
            f.adapter_calls.append(('parse', key))
            return dict(rows=[dict(synthetic=key)])
        def assertion(raw, declaration, operands, parse=parse, key=key):
            assert raw == ('synthetic trace ' + key + ':' + operands['case'] + '\n').encode()
            return parse(raw, declaration)
        helper = SimpleNamespace(RUNTIME_SOURCES=names, FIXTURE_SOURCE_NAMES=fixtures, BASE=0x40000000,
            sandbox=command_oracle.sandbox, tool=command_oracle.tool, vm_command=command_oracle.vm_command,
            validate_assets=validate, validate_v2_assets=validate, validate_v3_assets=validate,
            verify_fixture_snapshots=lambda *args: {}, elf_layout=lambda *args: {},
            check_console=lambda raw, sections, case: (dict(case=case), {}),
            check_trace_counters=lambda *args, counters=counters: copy.deepcopy(counters),
            expected_console=lambda sections, mutated, wrong: json.dumps(dict(case='one_byte_mutation'
                if mutated else 'wrong_lr_only' if wrong else 'anchor'), sort_keys=True).encode(),
            check_producer_console=lambda *args: ({}, None), scope_expectations=lambda *args: {})
        checks = SimpleNamespace(parse_trace=parse, assert_shutter_gate_trace_v1=assertion, assert_shutter_gate_trace_v2=assertion,
            assert_scope_trace_v2=lambda *args, **kwargs: None, assert_scope_trace_v3=lambda *args, **kwargs: None)
        f.helpers[component + '/integration/run_fixture.py'] = helper
        parser_name = ('integration/shutter_gate_trace_checks_v%d.py' if key.startswith('gate')
                       else 'integration/scope_trace_checks_v%d.py') % version
        f.parsers[component + '/' + parser_name] = checks
        actual['_folder_for_test'] = str(folder)
        f.api[key]['actual'] = actual
    f.metadata, f.source_root = f.metas['gate2'], f.roots['gate2']
    projection = {key: f.metadata[key] for key in v.SHUTTER_GATE_READER_FIELDS if key in f.metadata}
    projection.update(observer_sha256=observer, Main_source_sha256=f.sha(base / 'menu-observe.c'),
        original_appfw_sha256=hashlib.sha256(b'synthetic original appfw').hexdigest())
    f.expected = dict(projection, profile=v.SHUTTER_GATE_V2_PROFILE, trace_schema='readonly_shutter_gate_v2',
        source_contract_sha256=f.metadata['source_contract_sha256'], build_receipt=f.metadata['build_receipt'],
        library_source=f.metadata['library'], build_metadata=f.metadata,
        functional_runner_source_sha256=f.sha(base / 'functional_camera_runner.py'))
    f.binding.update(scope_observer_expected=f.expected, shutter_gate_reader_expected=copy.deepcopy(projection))
    (f.run / 'readonly-scope-observer.so').write_bytes(Path(f.metadata['library']).read_bytes())
    f.manifest.update(backup_transport=dict(binary=str(qemu), binary_sha256=f.sha(qemu)))
    media_digest = hashlib.sha256(b'synthetic original media').hexdigest()
    f.manifest['selected_initramfs_verified_files'].update({'usr/lib/appFw.so': projection['original_appfw_sha256'],
        'simulation/file-media-config.so': media_digest})
    f.manifest['files'] = {str(f.guest): f.binding['guest_sha256'], str(qemu): f.sha(qemu),
        f.metadata['build_receipt']: f.metadata['build_receipt_sha256'],
        str(f.run / 'readonly-scope-observer.so'): f.metadata['library_sha256'],
        **{str(f.source_root / name): value for name, value in f.metadata['source_sha256'].items()}}
    flags = dict.fromkeys((*v.SHUTTER_GATE_FALSE_FIELDS, 'original_camera_VM_started', 'originalUI_onceplan_prepared',
        'intent_published', 'card_prepared', 'native_CP_verified', 'original_M_producer_runtime_verified'), False)
    parent_path = f.work / 'parent-readback.json'
    f.binding['parent_readback'] = dict(path=str(parent_path), sha256='0' * 64)
    f.binding['runtime_ready'] = dict(path=str(Path(f.binding['batch']) / 'readonly-shutter-gate-v2-runtime-ready.json'), sha256='0' * 64)
    Path(f.binding['batch']).mkdir()
    legacy = {str(qemu): f.sha(qemu), str(audit_path): f.sha(audit_path)}
    for key in ('scope2', 'scope3'):
        metadata = f.metas[key]
        legacy.update({metadata['build_receipt']: metadata['build_receipt_sha256'], metadata['library']: metadata['library_sha256'],
            str(Path(metadata['build_receipt']).with_name('readonly-import-audit.json')): metadata['readonly_import_audit_sha256']})
    for index in range(13 - len(legacy)):
        path = tmp_path / ('legacy-asset-%d' % index); path.write_bytes(str(index).encode()); legacy[str(path)] = f.sha(path)
    groups = dict(legacy_runtime_assets_sha256=legacy)
    for key, field in (('gate1', 'gate_added_runtime_assets_sha256'), ('gate2', 'gate_v2_added_runtime_assets_sha256')):
        metadata = f.metas[key]
        groups[field] = {metadata['build_receipt']: metadata['build_receipt_sha256'], metadata['library']: metadata['library_sha256'],
            str(Path(metadata['build_receipt']).with_name('readonly-import-audit.json')): metadata['readonly_import_audit_sha256'],
            str(Path(metadata['build_receipt']).with_name('plugin-build-command.json')): metadata['plugin_build_command_sha256']}
    f.binding['runtime_assets_sha256'] = {name: digest for values in groups.values() for name, digest in values.items()}
    common = dict(groups, protected_runtime_assets_sha256=copy.deepcopy(f.binding['runtime_assets_sha256']),
        protected_qemu=dict(readonly_candidate=ref(qemu), production=ref(production), legacy_default=ref(legacy_default)), observer_builds={key: ref(Path(value['build_receipt']))
            for key, value in f.metas.items()}, launch_runtime_preflight=dict(passed=False, inspected=False, launch_authorized=False), **flags)
    f.parent = dict(copy.deepcopy(common), schema='functional-shutter-gate-v2-cohort-readback-v1',
        status='PASS_OFFLINE_SHUTTER_GATE_V2_COHORT_READBACK', expected_original_run_assets=copy.deepcopy(projection),
        observer_sha256=observer, media_sha256=media_digest, observer_archive_members_verified=len(f.build['sources']) + 1,
        tests_passed=2, subtests_passed=1, full_inventory={})
    f.runtime = dict(copy.deepcopy(common), schema='functional-shutter-gate-v2-runtime-ready-v1',
        status='PASS_NEW_OFFLINE_SHUTTER_GATE_V2_SUPPLEMENT', expected_original_run_assets=copy.deepcopy(projection),
        actualAPI_cases=list(v.SHUTTER_GATE_API_CASES), v2_actualAPI_compatibility_verified=True,
        v3_actualAPI_compatibility_verified=True, synthetic_shutter_gate_API_verified=True, synthetic_shutter_gate_v2_API_verified=True)
    f.plan = dict(copy.deepcopy(common), schema='functional-shutter-gate-v2-plan-v1', driver=str(base / 'scratch/run-functional-current-batch.py'),
        driver_sha256=f.sha(base / 'scratch/run-functional-current-batch.py'), guest_image=str(f.guest),
        scope_build=ref(Path(f.metadata['build_receipt'])), claimed_fault_result='FAIL')
    f.launch_owner = dict(pid=101, ppid=1, starttime=101, exe='/usr/bin/python3')
    f.regression = dict(returncode=0, tests_passed=2, subtests_passed=1, changed={key: [] for key in f.tested['groups']}, capture_verified=False)
    marker = 'PASS: constructor thread and application-init wrapper preserved behavior'
    command = ['/synthetic/original-libc-loader', 'LD_PRELOAD=/synthetic/menu-observe.so', '/synthetic/original-shell']
    media_command = [arg.replace('LD_PRELOAD=', 'LD_PRELOAD=' + str(base / 'menu-root/simulation/file-media-config.so') + ':')
                     if arg.startswith('LD_PRELOAD=') else arg for arg in command]
    f.abi = dict(returncode=0, stdout=marker, command=command, capture_verified=False, observer_sha256=observer,
        source_archive_sha256=f.build['source_archive_sha256'], source_count=len(f.build['sources']),
        media_preload_sha256=media_digest, media_preload=dict(returncode=0, stdout=marker, command=media_command, bind_now=True))
    f.ready = dict(capture_verified=False)
    def refreeze():
        frozen = {name: digest for group in f.tested['groups'].values() for name, digest in group.items()}
        f.parent['full_inventory'] = dict(source_sha256=frozen, modules=copy.deepcopy(f.tested['modules']),
            groups={key: sorted(group) for key, group in f.tested['groups'].items()})
        for row in (f.parent, f.runtime, f.parent['full_inventory']):
            row.update(source_count=len(frozen), module_count=len(f.tested['modules']))
        f.parent['all_source_members_verified'] = len(frozen)
        f.parent['tests_passed'] = f.regression['tests_passed'] = len(f.tested['modules'])
        f.parent.pop('host_junit_coverage', None)
    f.refreeze = refreeze
    def refresh():
        b, batch = f.binding, Path(f.binding['batch'])
        f.write(batch / 'inputs.json', f.tested)
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name in f.parent['full_inventory']['source_sha256']:
                raw = Path(name).read_bytes()
                member = tarfile.TarInfo(str(Path(name).relative_to(native))); member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
        (batch / 'inputs.tar.gz').write_bytes(output.getvalue())
        (batch / 'host-regression.log').write_bytes(('%d passed, %d subtests passed\n' %
            (f.regression['tests_passed'], f.regression['subtests_passed'])).encode())
        f.regression.update(inputs_sha256=f.sha(batch / 'inputs.json'), log_sha256=f.sha(batch / 'host-regression.log'))
        f.write(batch / 'host-regression.json', f.regression)
        f.abi['regression_sha256'] = f.sha(batch / 'host-regression.json')
        f.write(batch / 'abi.json', f.abi)
        f.ready.update(inputs_sha256=f.sha(batch / 'inputs.json'), all_input_archive_sha256=f.sha(batch / 'inputs.tar.gz'),
            regression_sha256=f.sha(batch / 'host-regression.json'), abi_sha256=f.sha(batch / 'abi.json'))
        f.write(batch / 'ready.json', f.ready); b['batch_ready_sha256'] = f.sha(batch / 'ready.json')
        junit_path = batch / 'host-regression.junit.xml'
        junit_path.write_bytes(('<testsuites><testsuite>' + ''.join(
            '<testcase classname="synthetic.module%d" name="case%d"/>' % (index, index)
            for index in range(len(f.tested['modules']))) + '</testsuite></testsuites>').encode())
        coverage = dict(junit=ref(junit_path), modules={name: 1 for name in f.tested['modules']},
            module_classnames={name: 'synthetic.module%d' % index for index, name in enumerate(f.tested['modules'])},
            actual_testcases=len(f.tested['modules']), actual_pytest_tests_passed=f.parent['tests_passed'],
            actual_pytest_subtests_passed=f.parent['subtests_passed'])
        f.parent.setdefault('host_junit_coverage', coverage)
        f.parent['host_junit_coverage']['junit'] = ref(junit_path)
        f.runtime['host_junit'] = ref(junit_path)
        for key, api in f.api.items():
            actual = copy.deepcopy(api['actual']); actual.pop('_folder_for_test')
            f.write(Path(api['manifest']['path']), actual); api['manifest'] = ref(Path(api['manifest']['path']))
        f.parent['dual_actual_api'] = {str(version): {key: copy.deepcopy(f.api['scope%d' % version][key])
            for key in ('manifest', 'cases')} for version in (2, 3)}
        for key, field in (('gate1', 'gate_actual_api'), ('gate2', 'gate_v2_actual_api')):
            f.parent[field] = {name: copy.deepcopy(f.api[key][name]) for name in ('manifest', 'cases')}
        f.parent['gate_build_receipt'] = ref(Path(f.metas['gate1']['build_receipt']))
        f.parent['gate_v2_build_receipt'] = ref(Path(f.metas['gate2']['build_receipt']))
        f.runtime.update(gate_build_receipt=f.parent['gate_build_receipt'], gate_v2_build_receipt=f.parent['gate_v2_build_receipt'],
            cohort_actual_api_manifests={key: copy.deepcopy(api['manifest']) for key, api in f.api.items()})
        f.plan.update(cohort_actual_api_manifests=copy.deepcopy(f.runtime['cohort_actual_api_manifests']))
        f.parent.update(batch=str(batch), ready_sha256=b['batch_ready_sha256'], source_inventory_sha256=f.ready['inputs_sha256'],
            source_archive_sha256=f.ready['all_input_archive_sha256'])
        f.write(Path(b['parent_readback']['path']), f.parent)
        b['parent_readback'] = ref(Path(b['parent_readback']['path'])); b['actual_api_contract'] = copy.deepcopy(b['parent_readback'])
        f.runtime.update(batch=str(batch), generic_ready=ref(batch / 'ready.json'), offline_readback=copy.deepcopy(b['parent_readback']))
        f.write(Path(b['runtime_ready']['path']), f.runtime); b['runtime_ready'] = ref(Path(b['runtime_ready']['path']))
        fresh_path = Path(b['fresh_guest']['path'])
        f.write(fresh_path, dict(guest_image=str(f.guest), guest_sha256=b['guest_sha256'], ready_sha256=b['batch_ready_sha256'],
            runtime_ready_sha256=b['runtime_ready']['sha256'], returncode=0, compiled3_unchanged=True, capture_verified=False,
            compiled_before={str(base / 'menu-observe.so'): observer}, compiled_after={str(base / 'menu-observe.so'): observer}))
        b['fresh_guest'] = ref(fresh_path); b['synthetic_fixture_manifest'] = copy.deepcopy(f.api['gate2']['manifest'])
        f.plan.update({key: copy.deepcopy(b[key]) for key in v.SHUTTER_GATE_PLAN_FIELDS +
            ('observer_sha256', 'guest_sha256', 'candidate_qemu', 'card')})
        f.plan['actual_api_manifest'] = copy.deepcopy(b['synthetic_fixture_manifest'])
        refresh_shutter_binding(f)
        f.trust = dict(plan=ref(f.work / 'plan.json'), intent=ref(f.work / 'intent.json'), parent_readback=copy.deepcopy(b['parent_readback']))
    f.refresh = refresh
    def source_module(relative, frozen):
        assert frozen[str(native / relative)] == f.sha(native / relative)
        if relative == 'runtime/analysis/scope_observer_profile.py':
            def validate_build(native_arg, path, candidate):
                assert native_arg == native and candidate == str(qemu)
                selected = next(value for value in f.metas.values() if value['build_receipt'] == path)
                assert f.sha(Path(path)) == selected['build_receipt_sha256']
                return copy.deepcopy(selected)
            return SimpleNamespace(validate_build=validate_build)
        return f.helpers.get(relative) or f.parsers[relative]
    monkeypatch.setattr(f.graph, 'source_module', source_module)
    refreeze(); refresh()
    return f


@pytest.fixture
def synthetic_gate_v2_binding(tmp_path, monkeypatch):
    return make_gate_v2_binding(tmp_path, monkeypatch)


def test_gate_v2_reads_bound_dynamic_cohort_and_all_four_api_closures(synthetic_gate_v2_binding):
    f = synthetic_gate_v2_binding
    guest, snapshots = scope_provenance(f, gate_v2_trust=f.trust)
    assert guest == f.guest and f.work / 'plan.json' in snapshots
    assert f.parent['source_count'] == len(f.parent['full_inventory']['source_sha256']) != 1193
    assert f.parent['module_count'] == len(f.tested['modules']) != 242
    assert 'source_count' not in f.ready and 'module_count' not in f.ready
    assert set(f.parent['protected_qemu']) == {'production', 'legacy_default', 'readonly_candidate'}
    assert len(f.binding['runtime_assets_sha256']) == 21
    assert all(Path(api['manifest']['path']) in snapshots for api in f.api.values())
    assert ('parse', 'gate2') in f.adapter_calls
    assert f.binding['claimed_fault_result'] == 'FAIL' and all(f.binding[key] is False for key in v.SHUTTER_GATE_FALSE_FIELDS)


def test_gate_v2_can_enter_its_own_frozen_cohort_without_embedded_future_hashes(synthetic_gate_v2_binding):
    f = synthetic_gate_v2_binding
    first = copy.deepcopy(f.trust)
    scope_provenance(f, gate_v2_trust=first)
    source = v.BASE / 'scratch/verify_hdmi_edge.py'
    source.write_bytes(source.read_bytes() + b'# next synthetic approved cohort\n')
    f.tested['groups']['host'][str(source)] = f.sha(source)
    extra = v.BASE / 'test_third_module.py'; extra.write_bytes(b'# additional frozen module\n')
    f.tested['groups']['test'][str(extra)] = f.sha(extra)
    f.tested['modules'].append(str(extra))
    before_count = f.parent['source_count']
    f.refreeze(); f.refresh()
    assert f.parent['source_count'] == before_count + 1 and f.parent['module_count'] == 3
    assert f.trust != first
    scope_provenance(f, gate_v2_trust=f.trust)
    with pytest.raises(ValueError, match='trust|digest'):
        scope_provenance(f, gate_v2_trust=first)


@pytest.mark.parametrize('damage', ['missing-trust', 'extra-trust', 'plan-hash', 'intent-hash', 'parent-hash', 'foreign-plan', 'foreign-intent'])
def test_gate_v2_trust_must_be_explicit_exact_and_same_run(synthetic_gate_v2_binding, damage):
    f = synthetic_gate_v2_binding
    trust = copy.deepcopy(f.trust)
    if damage == 'missing-trust':
        trust = None
    elif damage == 'extra-trust':
        trust['ready'] = copy.deepcopy(f.binding['runtime_ready'])
    elif damage.endswith('-hash'):
        trust[damage.removesuffix('-hash') if damage != 'parent-hash' else 'parent_readback']['sha256'] = '0' * 64
    else:
        trust['plan' if damage == 'foreign-plan' else 'intent']['path'] = str(f.work / 'foreign.json')
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f, gate_v2_trust=trust)


@pytest.mark.parametrize('where', ['run', 'plan', 'intent', 'launch'])
def test_gate_v2_rejects_old_provenance_schemas_even_with_new_caller_hashes(synthetic_gate_v2_binding, where):
    f = synthetic_gate_v2_binding
    if where == 'run':
        f.binding['schema'] = v.SHUTTER_GATE_RUN
        f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
    elif where == 'plan':
        f.plan['schema'] = 'functional-shutter-gate-v1-plan-v1'
        f.refresh()
    else:
        path = f.work / ('intent.json' if where == 'intent' else 'launch-binding.json')
        data = json.loads(path.read_bytes())
        data['schema'] = 'functional-shutter-gate-v1-' + ('intent-v1' if where == 'intent' else 'launch-v1')
        f.write(path, data)
        f.binding['intent_sha256' if where == 'intent' else 'launch_binding_sha256'] = f.sha(path)
        f.write(f.run / 'readonly-scope-run-binding.json', f.binding)
        if where == 'intent':
            f.trust['intent']['sha256'] = f.sha(path)
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f, gate_v2_trust=f.trust)


def test_gate_v2_native_entry_forwards_trust_before_original_upm_content(synthetic_gate_v2_binding, monkeypatch):
    f = synthetic_gate_v2_binding
    scope = dict(f.metadata, staged_library=str(f.run / 'readonly-scope-observer.so'),
        qemu_binary=f.binding['candidate_qemu']['path'], plan_binding=copy.deepcopy(f.context['scope']))
    config = dict(readonly_scope_observer=scope, running_QEMU_sha256=f.metadata['qemu_sha256'],
                  scope_build_receipt=f.metadata['build_receipt'])
    class ReachedOriginalUPMRead(RuntimeError):
        pass
    def read(path, limit):
        if path.name == 'hdmi-upm-watch-result.json':
            raise ReachedOriginalUPMRead('v2 source/config join completed; original UPM content remains required')
        return path.read_bytes()
    calls = []
    def source_proof(log, run, *, gate_v2_trust):
        assert run == f.run and gate_v2_trust is f.trust
        scope_provenance(f, gate_v2_trust=gate_v2_trust)
        calls.append(gate_v2_trust)
        return dict(run_binding_schema=v.SHUTTER_GATE_V2_RUN, shutter_gate_config_scope=copy.deepcopy(scope))
    monkeypatch.setattr(v, '_condition_source_proof', source_proof)
    monkeypatch.setattr(v, '_WATCH', SimpleNamespace(read_receipts=lambda run: [None, None],
        validate_run=lambda run: (f.run, None), read_config=lambda path: copy.deepcopy(config),
        checked_read=read, read_result=lambda config: read(f.run / 'hdmi-upm-watch-result.json', 32768),
        parse_json=json.loads, json=json, PREFIX='hdmi-upm-watch',
        READONLY_SCOPE_QEMU_SHA=f.metadata['qemu_sha256']))
    with pytest.raises(ReachedOriginalUPMRead):
        v.verify_hdmi_upm(Log(''), f.run, gate_v2_trust=f.trust)
    assert calls == [f.trust]


@pytest.mark.parametrize('damage', ['ready-status', 'parent-status', 'ready-schema', 'parent-schema', 'old-ready-name',
    'scope-v2-profile', 'gate-v1-profile', 'old-trace', 'root-alias', 'reader-schema-alias', 'runtime-cap',
    'parent-cap', 'nested-cap', 'missing-source7', 'missing-fixture7', 'frozen-missing', 'full-frozen-missing',
    'full-groups', 'source-count', 'module-count', 'boolean-count', 'duplicate-module', 'junit-coverage',
    'junit-classnames', 'source-asset-loss', 'new-asset-loss', 'asset-role-mix', 'media-ABI', 'observer-ABI',
    'media-bind-now', 'media-command', 'API2-missing', 'API3-missing', 'API1-missing', 'API2-v3-mix', 'API-new-mixed',
    'new-source-ref-root', 'new-fixture-ref-root', 'api-case-loss', 'api-trace', 'api-operand', 'api-baseline',
    'api-ledger-loss', 'api-command-loss', 'api-timeout', 'api-manifest-schema', 'api-cap', 'abi-bool-rc',
    'legacy-command-extra', 'legacy-command-missing', 'gate-outer-missing', 'gate-payload-missing',
    'api-command-string', 'api-unreaped', 'api-command-argv', 'legacy-timeout-argv',
    'legacy-payload-argv', 'gate-payload-argv', 'api-budget-float'])
def test_gate_v2_rejects_mixed_missing_or_promoted_content(synthetic_gate_v2_binding, damage):
    f = synthetic_gate_v2_binding
    if damage == 'ready-status':
        f.runtime['status'] = 'PASS_NEW_OFFLINE_SHUTTER_GATE_V1_SUPPLEMENT'
    elif damage == 'parent-status':
        f.parent['status'] = 'PASS_OFFLINE_PIN_PEER_RELEASE_GENERATION_COHORT_READBACK'
    elif damage in ('ready-schema', 'parent-schema'):
        (f.runtime if damage == 'ready-schema' else f.parent)['schema'] = 'functional-shutter-gate-v1-plan-v1'
    elif damage == 'old-ready-name':
        f.binding['runtime_ready']['path'] = str(Path(f.binding['batch']) / 'readonly-shutter-gate-v1-runtime-ready.json')
    elif damage in ('scope-v2-profile', 'gate-v1-profile', 'old-trace'):
        field, value = {'scope-v2-profile': ('profile', 'qemu-readonly-scope-v2'),
            'gate-v1-profile': ('profile', v.SHUTTER_GATE_PROFILE), 'old-trace': ('trace_schema', 'readonly_shutter_gate_v1')}[damage]
        f.expected[field] = value
    elif damage in ('root-alias', 'reader-schema-alias'):
        (f.expected if damage == 'root-alias' else f.binding['shutter_gate_reader_expected'])[
            'source_root' if damage == 'root-alias' else 'schema_sha256'] = 'a' * 64
    elif damage in ('runtime-cap', 'parent-cap', 'nested-cap'):
        target = f.runtime if damage == 'runtime-cap' else f.parent
        if damage == 'nested-cap':
            target['unused'] = dict(cap=True)
        else:
            target['cap'] = True
    elif damage in ('missing-source7', 'missing-fixture7'):
        key = 'source_sha256' if damage == 'missing-source7' else 'fixture_source_sha256'
        f.expected[key].pop(next(iter(f.expected[key])))
    elif damage == 'frozen-missing':
        del f.tested['groups']['host'][str(v.BASE / 'scratch/verify_hdmi_edge.py')]
    elif damage == 'full-frozen-missing':
        f.parent['full_inventory']['source_sha256'].pop(next(iter(f.parent['full_inventory']['source_sha256'])))
    elif damage == 'full-groups':
        f.parent['full_inventory']['groups']['host'].pop()
    elif damage in ('source-count', 'module-count', 'boolean-count'):
        key = 'source_count' if damage != 'module-count' else 'module_count'
        f.runtime[key] = True if damage == 'boolean-count' else f.runtime[key] + 1
    elif damage == 'duplicate-module':
        f.tested['modules'].append(f.tested['modules'][0])
    elif damage == 'junit-coverage':
        f.parent['host_junit_coverage']['modules'][f.tested['modules'][0]] += 1
    elif damage == 'junit-classnames':
        f.parent['host_junit_coverage']['module_classnames'][f.tested['modules'][0]] += '.foreign'
    elif damage in ('source-asset-loss', 'new-asset-loss', 'asset-role-mix'):
        field = 'legacy_runtime_assets_sha256' if damage == 'source-asset-loss' else 'gate_v2_added_runtime_assets_sha256'
        path = next(iter(f.parent[field])); digest = f.parent[field].pop(path)
        if damage == 'asset-role-mix':
            f.parent[field][next(iter(f.parent['gate_added_runtime_assets_sha256']))] = digest
    elif damage in ('media-ABI', 'observer-ABI', 'media-bind-now', 'media-command', 'abi-bool-rc'):
        if damage == 'media-ABI':
            del f.abi['media_preload']
        elif damage == 'observer-ABI':
            f.abi['stdout'] = 'missing original marker'
        elif damage == 'media-command':
            f.abi['media_preload']['command'] = copy.deepcopy(f.abi['command'])
        elif damage == 'media-bind-now':
            f.abi['media_preload']['bind_now'] = False
        else:
            f.abi['returncode'] = False
    else:
        actual = f.api['gate2']['actual']
        if damage == 'API2-v3-mix':
            f.api['scope2']['actual']['profile'] = 'qemu-readonly-scope-v3'
        elif damage in ('API2-missing', 'API3-missing', 'API1-missing'):
            pass  # Rebind the deliberately incomplete parent below, without changing fixture refs.
        elif damage == 'API-new-mixed':
            f.api['gate2']['actual'] = copy.deepcopy(f.api['gate1']['actual'])
        elif damage in ('new-source-ref-root', 'new-fixture-ref-root'):
            prefix = 'source:' if damage == 'new-source-ref-root' else 'fixture-source:'
            name = next(name for name in actual['inputs'] if name.startswith(prefix))
            actual['inputs'][name]['path'] = actual['inputs'][name]['path'].replace(v.SHUTTER_GATE_V2_COMPONENT, v.SHUTTER_GATE_COMPONENT)
        elif damage == 'api-case-loss':
            actual['variants'].pop('short_tb')
        elif damage in ('api-trace', 'api-operand', 'api-baseline'):
            name = {'api-trace': 'cases/original_entry-plugin/plugin.log',
                'api-operand': 'cases/original_entry-baseline/independent-operands.json',
                'api-baseline': 'cases/original_entry-plugin/console.bin'}[damage]
            path = Path(actual['_folder_for_test']) / name
            raw = b'{"case":"foreign"}' if damage == 'api-operand' else b'changed raw bytes\n'
            path.write_bytes(raw)
            actual['artifacts'][name] = dict(bytes=len(raw), sha256=f.sha(path))
        elif damage == 'api-ledger-loss':
            actual['artifacts'].pop('cases/original_entry-plugin/plugin.log')
        elif damage == 'api-command-loss':
            actual['commands'].pop(0)
        elif damage == 'api-timeout':
            actual['commands'][0]['outer_timeout'] = True
        elif damage == 'legacy-command-extra':
            f.api['scope2']['actual']['commands'][0]['outer_timeout'] = False
        elif damage == 'legacy-command-missing':
            f.api['scope3']['actual']['commands'][0].pop('owned_pid_unreaped')
        elif damage == 'gate-outer-missing':
            actual['commands'][0].pop('outer_timeout')
        elif damage == 'gate-payload-missing':
            f.api['gate1']['actual']['commands'][0].pop('payload_argv')
        elif damage == 'api-command-string':
            actual['commands'][0]['command'] = 'not-an-argv-list'
        elif damage == 'api-unreaped':
            actual['commands'][0]['owned_pid_unreaped'] = 123
        elif damage == 'api-command-argv':
            actual['commands'][0]['command'][-1] = '/foreign/fixture.elf'
        elif damage == 'legacy-timeout-argv':
            command = f.api['scope2']['actual']['commands'][0]['command']
            command[command.index('--verbose') + 1] = '600s'
        elif damage == 'legacy-payload-argv':
            f.api['scope3']['actual']['commands'][0]['command'][-1] = '/foreign/fixture.elf'
        elif damage == 'gate-payload-argv':
            actual['commands'][0]['payload_argv'] = actual['commands'][0]['payload_argv'][:-1] + ['/foreign/fixture.elf']
        elif damage == 'api-budget-float':
            actual['commands'][0]['limit_seconds'] = 60.0
        elif damage == 'api-manifest-schema':
            actual['trace_schema'] = 'readonly_scope_v2'
        elif damage == 'api-cap':
            actual['cap'] = True
    if damage in ('API2-missing', 'API3-missing', 'API1-missing'):
        # Preserve the original refs and remove only the bound parent API entry after rebinding.
        missing = {'API2-missing': 'scope2', 'API3-missing': 'scope3', 'API1-missing': 'gate1'}[damage]
        if missing.startswith('scope'):
            del f.parent['dual_actual_api'][missing[-1]]
        else:
            del f.parent['gate_actual_api']
        refresh_shutter_parents(f)
        f.trust = dict(plan=dict(path=str(f.work / 'plan.json'), sha256=f.sha(f.work / 'plan.json')),
            intent=dict(path=str(f.work / 'intent.json'), sha256=f.sha(f.work / 'intent.json')),
            parent_readback=copy.deepcopy(f.binding['parent_readback']))
        with pytest.raises((ValueError, KeyError, OSError)):
            scope_provenance(f, gate_v2_trust=f.trust)
        return
    f.refresh()
    with pytest.raises((ValueError, KeyError, OSError, AssertionError)):
        scope_provenance(f, gate_v2_trust=f.trust)


def refresh_pin_peer_parents(f, monkeypatch):
    """Synthetic receipt hashes only; keep the real source19 approval/candidate trust pins."""
    refresh_shutter_parents(f)
    monkeypatch.setattr(v, 'PIN_PEER_RUNTIME_READY_SHA', f.binding['runtime_ready']['sha256'])
    monkeypatch.setattr(v, 'PIN_PEER_PARENT_READBACK_SHA', f.binding['parent_readback']['sha256'])


@pytest.fixture
def synthetic_pin_peer_binding(synthetic_shutter_binding, monkeypatch):
    """New immutable offline source19 receipts in the old synthetic run envelope; no VM/image IO."""
    f = synthetic_shutter_binding
    prototype = json.loads(archived_receipt('A7C2_PIN_PEER_PARENT_RECEIPT').read_bytes())
    source_batch = Path(prototype['batch'])
    f.tested = json.loads((source_batch / 'inputs.json').read_bytes())
    # Replay these historical host inputs from their reviewed cohort, independently
    # of the current consumer and its newer profile/teardown implementation.
    host_paths = tuple(BASE / name for name in ('scope_observer_profile.py', 'functional_camera_runner.py'))
    source_ready_raw = (source_batch / 'ready.json').read_bytes()
    assert hashlib.sha256(source_ready_raw).hexdigest() == prototype['ready_sha256']
    archive_raw = (source_batch / 'inputs.tar.gz').read_bytes()
    assert hashlib.sha256(archive_raw).hexdigest() == json.loads(source_ready_raw)['all_input_archive_sha256']
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as archive:
        frozen_hosts = {path: archive.extractfile('runtime/analysis/' + path.name).read() for path in host_paths}
    for path, raw in frozen_hosts.items():
        assert hashlib.sha256(raw).hexdigest() == f.tested['groups']['host'][str(path)]
    graph_read = f.graph.read
    def read_frozen_hosts(path, limit=f.graph.MAX_SOURCE):
        if Path(path) in frozen_hosts:
            raw = frozen_hosts[Path(path)]
            assert len(raw) <= limit
            return raw
        return graph_read(path, limit)
    monkeypatch.setattr(f.graph, 'read', read_frozen_hosts)
    f.parent = copy.deepcopy(prototype)
    f.runtime = json.loads((source_batch / 'pin-peer-release-generation-runtime-ready.json').read_bytes())
    b = f.binding
    batch = Path(b['batch'])
    f.write(batch / 'inputs.json', f.tested)
    f.write(batch / 'host-regression.json', json.loads((source_batch / 'host-regression.json').read_bytes()))
    ready = json.loads((source_batch / 'ready.json').read_bytes())
    ready.update(inputs_sha256=f.sha(batch / 'inputs.json'), regression_sha256=f.sha(batch / 'host-regression.json'))
    f.write(batch / 'ready.json', ready)
    b['batch_ready_sha256'] = f.sha(batch / 'ready.json')
    f.parent.update(batch=str(batch), ready_sha256=b['batch_ready_sha256'])
    f.runtime['generic_ready'] = dict(path=str(batch / 'ready.json'), sha256=b['batch_ready_sha256'])
    projection = copy.deepcopy(prototype['expected_original_run_assets'])
    f.expected.update(projection)
    f.expected['functional_runner_source_sha256'] = f.tested['groups']['host'][str(BASE / 'functional_camera_runner.py')]
    b.update(observer_sha256=projection['observer_sha256'], shutter_gate_reader_expected=projection,
        synthetic_fixture_manifest=copy.deepcopy(prototype['gate_actual_api']['manifest']),
        runtime_ready=dict(path=str(batch / 'pin-peer-release-generation-runtime-ready.json'), sha256='a' * 64),
        runtime_assets_sha256=dict(prototype['legacy_runtime_assets_sha256'], **prototype['gate_added_runtime_assets_sha256']))
    f.observer = b['observer_sha256']
    f.build['sources'] = {path: dict(sha256=digest) for path, digest in f.tested['groups']['production'].items()}
    f.plan.update(batch_ready_sha256=b['batch_ready_sha256'], source_approval=copy.deepcopy(prototype['parent_approval']),
        actual_api_manifest=copy.deepcopy(b['synthetic_fixture_manifest']))
    fresh_path = Path(b['fresh_guest']['path'])
    fresh = json.loads(fresh_path.read_bytes())
    fresh.update(ready_sha256=b['batch_ready_sha256'], compiled_before={str(BASE / 'menu-observe.so'): f.observer},
        compiled_after={str(BASE / 'menu-observe.so'): f.observer})
    f.write(fresh_path, fresh)
    refresh_pin_peer_parents(f, monkeypatch)
    return f


def test_pin_peer_reviewed_generation_pins_bind_actual_offline_receipts():
    parent_path = archived_receipt('A7C2_PIN_PEER_PARENT_RECEIPT')
    parent_raw = parent_path.read_bytes()
    parent = json.loads(parent_raw)
    runtime_raw = (Path(parent['batch']) / 'pin-peer-release-generation-runtime-ready.json').read_bytes()
    runtime = json.loads(runtime_raw)
    assert hashlib.sha256(parent_raw).hexdigest() == v.PIN_PEER_PARENT_READBACK_SHA
    assert hashlib.sha256(runtime_raw).hexdigest() == v.PIN_PEER_RUNTIME_READY_SHA
    assert runtime['offline_readback'] == dict(path=str(parent_path), sha256=v.PIN_PEER_PARENT_READBACK_SHA)
    for key, digest in (('parent_approval', v.PIN_PEER_SOURCE_APPROVAL_SHA), ('candidate_manifest', v.PIN_PEER_CANDIDATE_SHA)):
        assert runtime[key] == parent[key]
        assert runtime[key]['sha256'] == hashlib.sha256(Path(runtime[key]['path']).read_bytes()).hexdigest() == digest


def test_pin_peer_scope_joins_reviewed_source19_and_new_ready(synthetic_pin_peer_binding):
    f = synthetic_pin_peer_binding
    guest, snapshots = scope_provenance(f)
    assert guest == f.guest
    assert len(f.parent['source19']) == len(f.runtime['source19']) == 19
    for name in ('scope_observer_profile.py', 'functional_camera_runner.py'):
        path = BASE / name
        assert hashlib.sha256(snapshots[path]).hexdigest() == f.tested['groups']['host'][str(path)]
    assert f.parent['full_inventory']['source_count'] == 1193
    assert f.parent['full_inventory']['module_count'] == 242
    assert Path(f.binding['runtime_ready']['path']).name == 'pin-peer-release-generation-runtime-ready.json'
    assert all(Path(f.binding['batch']) / name in snapshots for name in ('ready.json', 'inputs.json', 'host-regression.json'))
    assert all(Path(f.runtime[key]['path']) in snapshots for key in ('parent_approval', 'candidate_manifest'))
    assert all(Path(row['manifest']['path']) in snapshots for row in f.parent['dual_actual_api'].values())
    assert f.binding['claimed_fault_result'] == 'FAIL'
    assert all(f.binding[key] is False for key in v.SHUTTER_GATE_FALSE_FIELDS)


@pytest.mark.parametrize('name', ['scope_observer_profile.py', 'functional_camera_runner.py'])
def test_pin_peer_historical_profile_replay_rejects_changed_source_bytes(synthetic_pin_peer_binding, monkeypatch, name):
    f = synthetic_pin_peer_binding
    source_path = BASE / name
    graph_read = f.graph.read
    def changed_source(path, limit=f.graph.MAX_SOURCE):
        raw = graph_read(path, limit)
        return raw + b'# changed source generation\n' if Path(path) == source_path else raw
    monkeypatch.setattr(f.graph, 'read', changed_source)
    with pytest.raises(ValueError, match='actual/frozen host source differs: ' + re.escape(name)):
        scope_provenance(f)


def test_pin_peer_historical_runner_operand_cannot_use_current_source(synthetic_pin_peer_binding, monkeypatch):
    f = synthetic_pin_peer_binding
    current = f.sha(BASE / 'functional_camera_runner.py')
    assert current != f.tested['groups']['host'][str(BASE / 'functional_camera_runner.py')]
    f.expected['functional_runner_source_sha256'] = current
    refresh_pin_peer_parents(f, monkeypatch)
    with pytest.raises(ValueError, match='shutter gate Main/runner/appFw operands differ'):
        scope_provenance(f)


@pytest.mark.parametrize('damage', ['old-runtime-status', 'old-parent-status', 'legacy-runtime-name',
    'old14', 'approval14', 'candidate-other', 'frozen-mixed', 'source19-mixed', 'full-source-mixed',
    'modules-mixed', 'groups-mixed', 'groups-count-only', 'parent-other-batch', 'parent-ready', 'wrong-generic-ready', 'ready-bytes',
    'regression-count', 'actual-api-cases', 'gate-actualapi-other', 'missing-v2', 'v3-false',
    'asset-change', 'runtime-cap', 'parent-cap', 'wrong-reader-schema', 'wrong-build-metadata',
    'guest-ready', 'boolean-nonce', 'unreviewed-runtime', 'unreviewed-parent'])
def test_pin_peer_generation_cannot_be_mixed_or_promoted(synthetic_pin_peer_binding, monkeypatch, damage):
    f = synthetic_pin_peer_binding
    b = f.binding
    if damage == 'old-runtime-status':
        f.runtime['status'] = 'PASS_NEW_OFFLINE_SHUTTER_GATE_V1_SUPPLEMENT'
    elif damage == 'old-parent-status':
        f.parent['status'] = 'PASS_OFFLINE_SHUTTER_GATE_V1_COHORT_READBACK'
    elif damage == 'legacy-runtime-name':
        b['runtime_ready']['path'] = str(Path(b['batch']) / 'readonly-shutter-gate-v1-runtime-ready.json')
    elif damage == 'old14':
        for row in (f.parent, f.runtime, f.parent['full_inventory']):
            row['source19'] = dict(list(row['source19'].items())[:14])
            row.update(changed_source_count=14, unchanged_source_count=1179)
    elif damage == 'approval14':
        ref = copy.deepcopy(f.parent['production_source_install_approval'])
        f.parent['parent_approval'] = f.runtime['parent_approval'] = f.plan['source_approval'] = ref
    elif damage == 'candidate-other':
        ref = copy.deepcopy(f.parent['production_candidate_manifest'])
        f.parent['candidate_manifest'] = f.runtime['candidate_manifest'] = ref
    elif damage == 'frozen-mixed':
        f.tested['groups']['production'][str(BASE / 'menu-observe.c')] = f.parent['source19']['runtime/analysis/menu-observe.c']['before_sha256']
    elif damage == 'source19-mixed':
        f.runtime['source19']['runtime/analysis/menu-observe.c']['after_sha256'] = '0' * 64
    elif damage == 'full-source-mixed':
        f.parent['full_inventory']['source_sha256'][str(BASE / 'menu-observe.c')] = '0' * 64
    elif damage == 'modules-mixed':
        f.parent['full_inventory']['modules'][0] += '-foreign'
    elif damage == 'groups-mixed':
        f.parent['full_inventory']['groups']['production'][0] += '-foreign'
    elif damage == 'groups-count-only':
        f.parent['full_inventory']['groups'] = {key: len(value) for key, value in f.tested['groups'].items()}
    elif damage == 'parent-other-batch':
        f.parent['batch'] += '-foreign'
    elif damage == 'parent-ready':
        f.parent['ready_sha256'] = '0' * 64
    elif damage == 'wrong-generic-ready':
        f.runtime['generic_ready']['path'] = str(Path(b['batch']) / 'foreign-ready.json')
    elif damage == 'ready-bytes':
        path = Path(b['batch']) / 'ready.json'
        row = json.loads(path.read_bytes()); row['capture_verified'] = True
        f.write(path, row)
    elif damage == 'regression-count':
        f.parent['tests_passed'] -= 1
    elif damage == 'actual-api-cases':
        f.runtime['actualAPI_cases'].pop()
    elif damage == 'gate-actualapi-other':
        ref = copy.deepcopy(f.parent['dual_actual_api']['2']['manifest'])
        f.parent['gate_actual_api']['manifest'] = b['synthetic_fixture_manifest'] = f.plan['actual_api_manifest'] = ref
    elif damage == 'missing-v2':
        del f.parent['dual_actual_api']['2']
    elif damage == 'v3-false':
        f.runtime['v3_actualAPI_compatibility_verified'] = False
    elif damage == 'asset-change':
        b['runtime_assets_sha256'][next(iter(b['runtime_assets_sha256']))] = '0' * 64
    elif damage == 'runtime-cap':
        f.runtime['cap'] = True
    elif damage == 'parent-cap':
        f.parent['cap'] = True
    elif damage == 'wrong-reader-schema':
        f.expected['trace_schema_sha256'] = '0' * 64
    elif damage == 'wrong-build-metadata':
        f.metadata['readonly_import_audit_sha256'] = '0' * 64
    elif damage == 'guest-ready':
        path = Path(b['fresh_guest']['path'])
        row = json.loads(path.read_bytes()); row['ready_sha256'] = '0' * 64
        f.write(path, row)
    elif damage == 'boolean-nonce':
        b['nonce'] = True
    refresh_pin_peer_parents(f, monkeypatch)
    if damage in ('unreviewed-runtime', 'unreviewed-parent'):
        monkeypatch.setattr(v, 'PIN_PEER_RUNTIME_READY_SHA' if damage == 'unreviewed-runtime' else 'PIN_PEER_PARENT_READBACK_SHA', '0' * 64)
    with pytest.raises((ValueError, KeyError, OSError)):
        scope_provenance(f)


def test_shutter_scope_uses_actual_fixed_source7_fixture7_and_independent_schemas(synthetic_shutter_binding):
    f = synthetic_shutter_binding
    guest, snapshots = scope_provenance(f)
    assert guest == f.guest
    assert set(f.expected['source_sha256']) == set(v.SHUTTER_GATE_SOURCE_NAMES)
    assert set(f.expected['fixture_source_sha256']) == set(v.SHUTTER_GATE_FIXTURE_NAMES)
    assert f.source_root == f.graph.NATIVE / v.SHUTTER_GATE_COMPONENT
    assert not v.SHUTTER_GATE_ALIASES & f.expected.keys()
    assert f.expected['trace_schema_sha256'] == f.sha(f.source_root / 'log-schema-shutter-gate-v1.json')
    assert f.binding['shutter_gate_reader_expected'] == f.parent['expected_original_run_assets']
    assert f.work / 'plan.json' in snapshots
    assert f.run / 'readonly-scope-popen-exit-binding.json' in snapshots
    assert f.run / 'readonly-scope-live-ancestry.json' in snapshots
    assert all(f.source_root / name in snapshots for name in v.SHUTTER_GATE_FIXTURE_NAMES)
    assert all(f.binding[k] is False for k in v.SHUTTER_GATE_FALSE_FIELDS)


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
    f.metadata[field] = '0' * 64
    refresh_shutter_parents(f)
    assert f.manifest['readonly_scope_observer'][field] == f.expected['build_metadata'][field]
    with pytest.raises(ValueError, match='complete actual build metadata differs'):
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


@pytest.fixture
def shutter_native_replay(native_replay, synthetic_shutter_binding, monkeypatch):
    """Real original UPM event/free bytes; source-envelope join tested independently above."""
    run, log = native_replay
    f = synthetic_shutter_binding
    scope = dict(f.metadata, staged_library=str(run / 'readonly-scope-observer.so'),
        qemu_binary=f.binding['candidate_qemu']['path'], plan_binding=f.context['scope'])
    path = run / 'hdmi-upm-watch-config.json'
    config = json.loads(path.read_bytes())
    bound_scope = copy.deepcopy(scope)
    config.update(running_QEMU_sha256=v._watch().READONLY_SCOPE_QEMU_SHA,
                  scope_build_receipt=scope['build_receipt'], readonly_scope_observer=copy.deepcopy(scope))
    config['padding'] = 'x' * max(0, 17465 - len(json.dumps(config).encode()))
    path.write_text(json.dumps(config))
    assert 16384 < len(path.read_bytes()) <= 32768
    calls = []
    def source_proof(actual_log, actual_run):
        assert actual_log is log and actual_run == run
        scope_provenance(f)
        calls.append((actual_log, actual_run))
        return dict(run_binding_schema=v.SHUTTER_GATE_RUN, shutter_gate_config_scope=copy.deepcopy(bound_scope))
    monkeypatch.setattr(v, '_condition_source_proof', source_proof)
    return run, log, config, calls


def test_actual_upm_consumer_reads_large_new_config_via_shared_reader(shutter_native_replay, monkeypatch):
    run, log, _, calls = shutter_native_replay
    watch = v._watch()
    original = watch.read_config
    loaded = []
    def record(path, *args, **kwargs):
        loaded.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(watch, 'read_config', record)
    proof = v.verify_hdmi_upm(log, run)
    assert proof['native_UPM_verified'] is True and proof['full_edge_verified'] is False
    assert len(proof['receipts']) == 2 and calls == [(log, run)]
    assert loaded.count(run / 'hdmi-upm-watch-config.json') == 2


@pytest.mark.parametrize('profile', [None, 'qemu-readonly-scope-v1', 'qemu-readonly-scope-v2', 'qemu-readonly-scope-v3'])
def test_actual_upm_consumer_retains_old_profile_config_limits(native_replay, profile):
    run, log = native_replay
    path = run / 'hdmi-upm-watch-config.json'
    config = json.loads(path.read_bytes())
    config['readonly_scope_observer'] = None if profile is None else dict(profile=profile)
    path.write_text(json.dumps(config))
    assert v.verify_hdmi_upm(log, run)['native_UPM_verified']
    config['padding'] = 'x' * 17000
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='profile byte bound'):
        v.verify_hdmi_upm(log, run)


@pytest.mark.parametrize('damage', ['no-actual-upm', 'no-original-free', 'mixed-config', 'old-config-profile', 'missing-config-profile'])
def test_shutter_observer_never_substitutes_for_native_upm_or_original_free(shutter_native_replay, damage):
    run, log, config, _ = shutter_native_replay
    if damage == 'no-actual-upm':
        path = run / 'hdmi-upm-watch-events.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines()]
        events.remove([row for row in events if row['kind'] == 'free_return'][-1])
        path.write_text(''.join(json.dumps(row) + '\n' for row in events))
    elif damage == 'no-original-free':
        log.records.remove(v._kind(log, 'KERNEL_RETIRED', 3)[0])
    else:
        if damage == 'mixed-config':
            config['readonly_scope_observer']['plan_binding']['nonce'] += 1
        else:
            (run / 'readonly-scope-run-binding.json').write_text(json.dumps(dict(schema=v.SHUTTER_GATE_RUN)))
            config.pop('padding', None)
            if damage == 'old-config-profile':
                config['readonly_scope_observer']['profile'] = 'qemu-readonly-scope-v3'
            else:
                config['readonly_scope_observer'] = None
        (run / 'hdmi-upm-watch-config.json').write_text(json.dumps(config))
    with pytest.raises((ValueError, KeyError, OSError)):
        v.verify_hdmi_upm(log, run)


def test_shutter_profile_never_excuses_missing_original_condition_free(host_log, synthetic_shutter_binding):
    f = synthetic_shutter_binding
    scope_provenance(f)
    log = copy.deepcopy(host_log)
    log.records.remove(v._kind(log, 'NATIVE_FREE', 2)[0])
    with pytest.raises(ValueError, match='incomplete message lifetimes'):
        v.verify_hdmi_effects(log, f.run)


def test_shutter_family_keeps_common_retained_image_byte_guard(condition_source_replay, synthetic_shutter_binding, monkeypatch):
    run, _, log = condition_source_replay
    f = synthetic_shutter_binding
    path = run / 'source-snapshot-run-binding.json'
    binding = json.loads(path.read_bytes()); binding['schema'] = v.SHUTTER_GATE_RUN
    path.unlink()
    f.write(run / 'readonly-scope-run-binding.json', binding)
    # Only isolate the independently exercised envelope; retain original ABI/archive/image reader and bytes.
    monkeypatch.setattr(v, '_condition_scope_binding', lambda *args: (BASE / 'menu-initramfs.cpio', {f.work / 'plan.json': (f.work / 'plan.json').read_bytes()}))
    image = run / 'selected-initramfs.cpio'
    with image.open('r+b') as stream:
        stream.seek(-1, 2); byte = stream.read(1); stream.seek(-1, 2); stream.write(bytes([byte[0] ^ 1]))
    with pytest.raises(ValueError, match='condition retained initramfs: SHA256 differs'):
        v._condition_source_proof(log, run)


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


@pytest.mark.parametrize('new_main', range(14))
@pytest.mark.parametrize('new_recipe', range(14))
def test_approved_source_sets_require_a_complete_tuple(new_main, new_recipe):
    selected = dict(v.CONDITION_LEDGER_SOURCES)
    selected['menu-observe.c'] = v.SOURCE_SETS[new_main]['menu-observe.c']
    selected['build-observers.sh'] = v.SOURCE_SETS[new_recipe]['build-observers.sh']
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    approved = {(0, 0), (1, 1)} | {(m, r) for m in (12, 13) for r in (11, 12, 13)} | {(m, r) for m in (9, 10, 11) for r in (9, 10, 11, 12)} | {(m, r) for m in (2, 3, 4, 5, 6, 7, 8) for r in (2, 3, 4, 5, 6)} | {(m, r) for m in (6, 7, 8) for r in (7, 8)}
    if (new_main, new_recipe) in approved:
        expected = (13 if new_recipe == 13 else 12) if new_main in (12, 13) else 11 if new_recipe == 12 else new_recipe if new_recipe in (7, 8, 9, 10, 11) else 6 if new_main in (7, 8) else new_main
        assert v._condition_source_set(sources) == v.SOURCE_SETS[expected]
    else:
        with pytest.raises(ValueError, match='unreviewed condition ledger/hook source set'):
            v._condition_source_set(sources)


def test_actual_current_sources_match_parent_approved_exact_set():
    sources = {str(BASE / name): {'sha256': hashlib.sha256((BASE / name).read_bytes()).hexdigest()}
               for name in v.PRODUCT_DEVELOPMENT_20261108_SOURCES}
    assert v._condition_source_set(sources) == v.PRODUCT_DEVELOPMENT_20261108_SOURCES


@pytest.mark.parametrize('version', ('FOCUS_RESET_CONDITION_SOURCES', 'FOCUS_RESET_ZERO_INIT_CONDITION_SOURCES', 'SCENE_FOCUS_MIRROR_CONDITION_SOURCES', 'HUTI_FOCUS_QUERY_CONDITION_SOURCES', 'PKNP_VDF163_DISPATCH_CONDITION_SOURCES', 'OV45_HDMI_SIGNAL_MODE_CONDITION_SOURCES', 'E6U_HDMI_INITIAL_PREFIX_CONDITION_SOURCES', 'GKH1_CP4073_ZERO_CONDITION_SOURCES', 'GKH1_CP4073_ZERO_RETIRE_CONDITION_SOURCES', 'VDF170_EFRAMING_CONDITION_SOURCES', 'ZQ6_CP_PARAMETER_BANK_CONDITION_SOURCES'))
@pytest.mark.parametrize('recipe', range(14))
def test_focus_reset_source_version_requires_its_exact_recipe(recipe, version):
    approved = getattr(v, version)
    selected = dict(approved)
    selected['build-observers.sh'] = v.SOURCE_SETS[recipe]['build-observers.sh']
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    if selected == approved:
        assert v._condition_source_set(sources) == selected
    else:
        with pytest.raises(ValueError, match='unreviewed condition ledger/hook source set'):
            v._condition_source_set(sources)


@pytest.mark.parametrize('version', ('FOCUS_RESET_CONDITION_SOURCES', 'FOCUS_RESET_ZERO_INIT_CONDITION_SOURCES', 'SCENE_FOCUS_MIRROR_CONDITION_SOURCES', 'HUTI_FOCUS_QUERY_CONDITION_SOURCES', 'PKNP_VDF163_DISPATCH_CONDITION_SOURCES', 'OV45_HDMI_SIGNAL_MODE_CONDITION_SOURCES', 'E6U_HDMI_INITIAL_PREFIX_CONDITION_SOURCES', 'GKH1_CP4073_ZERO_CONDITION_SOURCES', 'GKH1_CP4073_ZERO_RETIRE_CONDITION_SOURCES', 'VDF170_EFRAMING_CONDITION_SOURCES', 'ZQ6_CP_PARAMETER_BANK_CONDITION_SOURCES'))
@pytest.mark.parametrize('name', tuple(v.CONDITION_LEDGER_SOURCES))
def test_focus_reset_source_version_unknown_member_is_refused(name, version):
    selected = dict(getattr(v, version))
    selected[name] = '0' * 64
    sources = {str(BASE / key): {'sha256': digest} for key, digest in selected.items()}
    with pytest.raises(ValueError, match='unreviewed condition ledger/hook source set'):
        v._condition_source_set(sources)


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


@pytest.mark.parametrize('wrong_result_scope', [False, True])
def test_actual_gate2_upm_consumes_large_current_result_only(native_replay, synthetic_gate_v2_binding,
                                                            monkeypatch, wrong_result_scope):
    run, log = native_replay
    f = synthetic_gate_v2_binding
    scope = dict(f.metadata, staged_library=str(run / 'readonly-scope-observer.so'),
                 qemu_binary=f.binding['candidate_qemu']['path'], plan_binding=f.context['scope'])
    path = run / 'hdmi-upm-watch-config.json'
    config = json.loads(path.read_bytes())
    config.update(readonly_scope_observer=copy.deepcopy(scope), running_QEMU_sha256=v._watch().READONLY_SCOPE_QEMU_SHA,
                  scope_build_receipt=scope['build_receipt'])
    path.write_text(json.dumps(config))
    path = run / 'hdmi-upm-watch-result.json'
    result = json.loads(path.read_bytes())
    result.update(readonly_scope_observer=copy.deepcopy(scope), running_QEMU_sha256=config['running_QEMU_sha256'],
                  last_observation='x' * 4096)
    if wrong_result_scope:
        result['readonly_scope_observer']['plan_binding']['nonce'] += 1
    path.write_text(json.dumps(result))
    assert 16384 < path.stat().st_size <= 32768
    def source_proof(actual_log, actual_run, *, gate_v2_trust):
        assert actual_log is log and actual_run == run and gate_v2_trust is f.trust
        scope_provenance(f, gate_v2_trust=f.trust)
        return dict(run_binding_schema=v.SHUTTER_GATE_V2_RUN, shutter_gate_config_scope=copy.deepcopy(scope))
    monkeypatch.setattr(v, '_condition_source_proof', source_proof)
    if wrong_result_scope:
        with pytest.raises(ValueError, match='result scope differs'):
            v.verify_hdmi_upm(log, run, gate_v2_trust=f.trust)
    else:
        proof = v.verify_hdmi_upm(log, run, gate_v2_trust=f.trust)
        assert proof['native_UPM_verified'] and len(proof['receipts']) == 2 and not proof['full_edge_verified']


def test_verified_mailbox_prepare_is_returned_for_exact_content_repair_join(native_replay):
    run, log = native_replay
    proof = v.verify_hdmi_upm(log, run)
    prepared = v.one(log, 'FULL_HDMI_UPM_MAILBOX_PREPARE')
    assert proof['guest_prepared'] == prepared
    path = BASE.parents[1] / 'report/functional-graph-evidence/check_graph.py'
    spec = importlib.util.spec_from_file_location('_verified_upm_prepare_content_join', path)
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)
    repair = dict(kind='complete-HdmiUpmMailbox-UIPC-boundary', parsed_line=prepared['line'],
                  repaired_record=prepared['raw'], repaired_record_sha256=graph.sha(prepared['raw'].encode()))
    assert graph.bind_repairs(proof, [copy.deepcopy(repair)])[0]['content_verifier_joined'] is True
    for missing in ({}, {key: value for key, value in proof.items() if key != 'guest_prepared'}):
        with pytest.raises(graph.UnjoinedRepairs):
            graph.bind_repairs(missing, [copy.deepcopy(repair)])
    for key, value in (('nonce', '0x1'), ('lease', '0'), ('raw', '00' * 16)):
        with pytest.raises(ValueError):
            v.verify_hdmi_upm(change(log, 'FULL_HDMI_UPM_MAILBOX_PREPARE', key, value), run)


@pytest.mark.parametrize('warning_index', [None, 0, 1])
def test_actual_c_hdmi_request_kernel_repair_requires_full_effect_consumption(host_log, warning_index):
    path = BASE.parents[1] / 'report/functional-graph-evidence/check_graph.py'
    spec = importlib.util.spec_from_file_location('_host_only_hdmi_request_boundary', path)
    graph = importlib.util.module_from_spec(spec); spec.loader.exec_module(graph)
    def observed(row):
        raw = row['raw'].encode()
        return raw if raw.startswith(b'OBS ') else b'OBS ' + raw
    request = v.one(host_log, v.PREFIX + '_REQUEST')
    target = observed(request)
    raw = b''.join((observed(row) if row is request else row['raw'].encode()) + b'\r\n'
                   for row in host_log.records)
    assert raw.count(target + b'\r\n') == 1
    warning = b'' if warning_index is None else graph.WARNINGS[warning_index]
    kernel = b'[ 5650.897903] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
    changed = raw.replace(target + b'\r\n', target + warning + kernel + b'\r\n')
    parsed, repairs = graph.console_records(changed)
    assert len(repairs) == 1 + (warning_index is not None)
    log = Log(parsed.decode())
    with pytest.raises(graph.UnjoinedRepairs):
        graph.bind_repairs({}, repairs)
    rejected = change(log, v.PREFIX + '_STATE_READBACK', 'event6_consumed', '0')
    with pytest.raises(ValueError):
        v.verify_hdmi_effects(rejected)
    assert all('content_verifier_joined' not in item for item in repairs)
    proof = v.verify_hdmi_effects(log)
    graph.bind_repairs(proof, repairs)
    assert all(item['content_verifier_joined'] for item in repairs)
    assert proof['REQUEST'] is log.rows(v.PREFIX + '_REQUEST')[0]
    assert len(proof['condition_messages']) == 24 and not proof['capture_verified']
    assert not proof['frames_verified'] and not proof['native_UPM_join_required']


def test_qr5_native_source_revision_returns_the_full_dependency_tuple():
    selected = v.QR5_NATIVE_EVIDENCE_CONDITION_SOURCES
    assert set(v.CONDITION_LEDGER_SOURCES) < set(selected)
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    assert v._condition_source_set(sources) == selected


@pytest.mark.parametrize('member', tuple(v.QR5_NATIVE_EVIDENCE_CONDITION_SOURCES))
@pytest.mark.parametrize('damage', ('changed', 'missing'))
def test_qr5_native_source_revision_refuses_each_missing_or_changed_member(member, damage):
    selected = v.QR5_NATIVE_EVIDENCE_CONDITION_SOURCES
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    if damage == 'changed':
        sources[str(BASE / member)]['sha256'] = '0' * 64
    else:
        del sources[str(BASE / member)]
    with pytest.raises((ValueError, KeyError)):
        v._condition_source_set(sources)


def test_historical_zq6_bank_source_tuple_is_still_accepted():
    selected = v.ZQ6_CP_PARAMETER_BANK_CONDITION_SOURCES
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    assert v._condition_source_set(sources) == selected


def test_jky_movie_source_revision_returns_complete_dependency_tuple():
    selected = v.JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES
    assert len(selected) == 11 and set(v.CONDITION_LEDGER_SOURCES) < set(selected)
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    assert v._condition_source_set(sources) == selected


@pytest.mark.parametrize('member', tuple(v.JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES))
@pytest.mark.parametrize('damage', ('missing', 'changed'))
def test_jky_movie_source_revision_refuses_each_incomplete_or_changed_member(member, damage):
    sources = {str(BASE / name): {'sha256': digest}
               for name, digest in v.JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES.items()}
    if damage == 'missing':
        del sources[str(BASE / member)]
    else:
        sources[str(BASE / member)]['sha256'] = '0' * 64
    with pytest.raises((ValueError, KeyError)):
        v._condition_source_set(sources)


def test_jky_movie_source_revision_refuses_old_qr5_with_current_main_only():
    sources = {str(BASE / name): {'sha256': digest}
               for name, digest in v.QR5_NATIVE_EVIDENCE_CONDITION_SOURCES.items()}
    sources[str(BASE / 'menu-observe.c')]['sha256'] = v.JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES['menu-observe.c']
    with pytest.raises(ValueError):
        v._condition_source_set(sources)


def test_ehg_ou_source_revision_returns_complete_dependency_tuple():
    selected = v.EHG_CP_OU_CRANK_CONDITION_SOURCES
    assert len(selected) == 11 and set(v.CONDITION_LEDGER_SOURCES) < set(selected)
    sources = {str(BASE / name): {'sha256': digest} for name, digest in selected.items()}
    assert v._condition_source_set(sources) == selected


@pytest.mark.parametrize('member', tuple(v.EHG_CP_OU_CRANK_CONDITION_SOURCES))
@pytest.mark.parametrize('damage', ('missing', 'changed'))
def test_ehg_ou_source_revision_refuses_each_incomplete_or_changed_member(member, damage):
    sources = {str(BASE / name): {'sha256': digest}
               for name, digest in v.EHG_CP_OU_CRANK_CONDITION_SOURCES.items()}
    if damage == 'missing':
        del sources[str(BASE / member)]
    else:
        sources[str(BASE / member)]['sha256'] = '0' * 64
    with pytest.raises((ValueError, KeyError)):
        v._condition_source_set(sources)


def test_ehg_ou_source_revision_refuses_old_movie_tuple_with_current_main_only():
    sources = {str(BASE / name): {'sha256': digest}
               for name, digest in v.JKY_CP_MOVIE_FORMAT_CONDITION_SOURCES.items()}
    sources[str(BASE / 'menu-observe.c')]['sha256'] = v.EHG_CP_OU_CRANK_CONDITION_SOURCES['menu-observe.c']
    with pytest.raises(ValueError):
        v._condition_source_set(sources)


def test_mof_timecode_source_revision_returns_full_native_owner_tuple():
    selected = v.MOF_BB_TIMECODE_CONDITION_SOURCES
    assert len(selected) == 13 and set(v.EHG_CP_OU_CRANK_CONDITION_SOURCES) < set(selected)
    sources = {str(BASE / name): {'sha256': value} for name, value in selected.items()}
    assert v._condition_source_set(sources) == selected


@pytest.mark.parametrize('member', tuple(v.MOF_BB_TIMECODE_CONDITION_SOURCES))
@pytest.mark.parametrize('damage', ('missing', 'changed'))
def test_mof_timecode_source_revision_refuses_each_missing_or_changed_member(member, damage):
    sources = {str(BASE / name): {'sha256': value} for name, value in v.MOF_BB_TIMECODE_CONDITION_SOURCES.items()}
    if damage == 'missing':
        del sources[str(BASE / member)]
    else:
        sources[str(BASE / member)]['sha256'] = '0' * 64
    with pytest.raises((ValueError, KeyError)):
        v._condition_source_set(sources)


def test_mof_timecode_source_revision_refuses_predecessor_with_only_new_main():
    sources = {str(BASE / name): {'sha256': value} for name, value in v.EHG_CP_OU_CRANK_CONDITION_SOURCES.items()}
    sources[str(BASE / 'menu-observe.c')]['sha256'] = v.MOF_BB_TIMECODE_CONDITION_SOURCES['menu-observe.c']
    with pytest.raises(ValueError):
        v._condition_source_set(sources)


def test_yvo_preset_source_revision_returns_current_runtime_tuple():
    selected = v.YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES
    assert len(selected) == 13 and set(selected) == set(v.MOF_BB_TIMECODE_CONDITION_SOURCES)
    sources = {str((BASE / name).resolve()): {'sha256': digest} for name, digest in selected.items()}
    assert v._condition_source_set(sources) == selected


@pytest.mark.parametrize('member', tuple(v.YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES))
@pytest.mark.parametrize('damage', ('missing', 'changed'))
def test_yvo_preset_source_revision_refuses_each_incomplete_or_changed_member(member, damage):
    selected = v.YVO_BB_TIMECODE_PRESET_CONDITION_SOURCES
    sources = {str((BASE / name).resolve()): {'sha256': digest} for name, digest in selected.items()}
    key = str((BASE / member).resolve())
    if damage == 'missing':
        del sources[key]
    else:
        sources[key]['sha256'] = '0' * 64
    with pytest.raises((ValueError, KeyError)):
        v._condition_source_set(sources)
