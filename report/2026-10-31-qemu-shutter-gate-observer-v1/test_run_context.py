# SPDX-License-Identifier: MIT
"""Strict reader metadata and raw-candidate tests, using actual new C trace bytes.

Synthetic metadata exercises reader rejection paths; it is never an actual-QEMU
build or run receipt. Integrated source7/fixture7 are copied byte-for-byte.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('shutter_v1_run_host_support', HERE / 'test_scope_observer.py')
HOST = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HOST)
observer_binary = HOST.observer_binary


def load_reader():
    spec = importlib.util.spec_from_file_location('shutter_v1_run_reader', HERE / 'check_shutter_gate_v1.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main_console(*, base=0x5500000000, tid=42, number=1):
    return ('OBS SHUTTER_DETAIL_POWERON site=dispatch n=%d pid=40 tid=%d base=%#x '
            'controller=0x1111 caller_raw=%#x caller_app=0x1234 raw_u32=0x1000090 raw_known=1 '
            'numeric_route_match=1 vptr=0x2222 field300=0 field302=0 field303=0 current17c=0x1 '
            'model_m=0 model_k=0 open_rc=3 open_errno=0 reads=8/2/1/1/4/4/4 read_errno=0/0/0/0/0/0/0 '
            'close_rc=0 close_errno=0 quota=poweron_entry16 observation_only=1 atomic_snapshot=0 '
            'phase=entry original_branch_observed=0 original_store_observed=0 original_return_observed=0 '
            'event_id_unverified=1 producer_unknown=1 capture_verified=0\n' %
            (number, tid, base, base + 0x1234)).encode('ascii')


def flow_console(*, tid=42, number=7):
    return ('OBS SHUTTER_FLOW site=final n=%d tid=%d a0=0x1122334455667788 a1=0xaabbccdd80000000 '
            'a2=0x9988776655443322 a3=0x8877665544332211 code=0x2070000 id=0 state_d428=0 '
            'state_d498=0 state_c408=0 reads=4/-1/4/4/4 press_local=0 transition_67fc8=0 '
            'inhibit_83337e3=0 duplicate_d570=0x1 gate_reads=4/4/1/4 observation_only=1 '
            'atomic_snapshot=0 original_branch_observed=0\n' % (number, tid)).encode('ascii')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unit_run(tmp_path, monkeypatch, trace, console):
    reader = load_reader()
    root = tmp_path.joinpath(*reader.SOURCE_SUFFIX)
    root.mkdir(parents=True)
    for name in dict.fromkeys(reader.BUILD_SOURCES + reader.FIXTURE_SOURCES):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((HERE / name).read_bytes())
    monkeypatch.setattr(reader, 'HERE', root)
    run = tmp_path / 'same-run'
    run.mkdir()
    plugin = b'self-owned reader unit-test staged plugin bytes; never a build admission'
    (run / 'readonly-scope-observer.so').write_bytes(plugin)
    (run / 'readonly-scope-trace.log').write_bytes(trace)
    (run / 'console.log').write_bytes(console)
    build = tmp_path / 'build'
    build.mkdir()
    audit_qemu = '/matched/candidate/qemu-system-aarch64'
    commands = {'imports': ['nm', '-D', '--undefined-only', str(build / 'scope-observer.so')],
                'exports': ['nm', '-D', '--defined-only', audit_qemu],
                'needed': ['readelf', '-d', str(build / 'scope-observer.so')]}
    audit = {role: {'command': commands[role], 'returncode': 0, 'stdout': output, 'stderr': ''}
             for role, output in (
                 ('imports', ''.join(' U ' + name + '\n' for name in sorted(reader.QEMU_IMPORTS)) + ' U fwrite\n'),
                 ('exports', ''.join(' T ' + name + '\n' for name in sorted(reader.QEMU_IMPORTS))),
                 ('needed', ' (NEEDED) Shared library: [libglib-2.0.so.0]\n'))}
    audit.update(qemu_plugin_imports=sorted(reader.QEMU_IMPORTS), ordinary_imports=['fwrite'],
                 dt_needed=['libglib-2.0.so.0'])
    audit_path = build / 'readonly-import-audit.json'
    dump(audit_path, audit)
    closure = {name: digest((root / name).read_bytes()) for name in reader.BUILD_SOURCES}
    fixtures = {name: digest((root / name).read_bytes()) for name in reader.FIXTURE_SOURCES}
    expected = {'source_sha256': closure, 'fixture_source_sha256': fixtures,
                'trace_schema_sha256': closure['log-schema-shutter-gate-v1.json'],
                'qemu_sha256': reader.QEMU_SHA256, 'qemu_header_sha256': reader.HEADER_SHA256,
                'library_sha256': digest(plugin), 'observer_sha256': 'a' * 64,
                'Main_source_sha256': 'b' * 64, 'original_appfw_sha256': 'c' * 64,
                'readonly_import_audit_sha256': digest(audit_path.read_bytes())}
    receipt = dict(schema=reader.PROFILE, plugin_api=7, trace_schema=reader.SCHEMA,
                   source_contract_sha256=closure['source-contract-shutter-gate-v1.json'],
                   trace_schema_sha256=expected['trace_schema_sha256'],
                   source_sha256=closure, fixture_source_sha256=fixtures,
                   qemu=audit_qemu, qemu_sha256=reader.QEMU_SHA256, qemu_header_sha256=reader.HEADER_SHA256,
                   library=str(build / 'scope-observer.so'), library_sha256=digest(plugin),
                   readonly_imports_verified=True, readonly_import_audit_sha256=expected['readonly_import_audit_sha256'],
                   runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
    receipt_path = build / 'build-receipt.json'
    dump(receipt_path, receipt)
    expected['build_receipt_sha256'] = digest(receipt_path.read_bytes())
    profile = {key: expected[key] for key in ('qemu_sha256', 'qemu_header_sha256', 'library_sha256', 'source_sha256')}
    profile.update(profile=reader.PROFILE, trace_schema=reader.SCHEMA,
                   trace_schema_sha256=expected['trace_schema_sha256'],
                   source_contract_sha256=closure['source-contract-shutter-gate-v1.json'],
                   build_receipt=str(receipt_path), build_receipt_sha256=expected['build_receipt_sha256'],
                   library=str(run / 'readonly-scope-observer.so'), log=str(run / 'readonly-scope-trace.log'),
                   identity_binding='unverified', capture_verified=False, physical_asic_compatibility_verified=False)
    files = {str(root / name): value for name, value in closure.items()}
    files.update({str(receipt_path): expected['build_receipt_sha256'],
                  str(run / 'readonly-scope-observer.so'): digest(plugin),
                  '/never-open-original/appFw.so': expected['original_appfw_sha256']})
    manifest = {'readonly_scope_observer': profile, 'files': files,
                'compiled_observer': {'observer_sha256': expected['observer_sha256'],
                                      'sources': {'/frozen/Main/menu-observe.c': {'sha256': expected['Main_source_sha256']}}}}
    dump(run / 'runtime-manifest.json', manifest)
    exit_record = {'profile': reader.PROFILE, 'run': str(run), 'owned_wrapper_pid': os.getpid(),
                   'returncode': 0, 'log_available': True, 'log_sha256': digest(trace),
                   'library_sha256': digest(plugin), 'capture_verified': False,
                   'physical_asic_compatibility_verified': False}
    dump(run / 'readonly-scope-exit.json', exit_record)
    return reader, run, expected, root, receipt_path


def test_complete_normal_owned_run_binding_retains_only_raw_candidates(observer_binary, tmp_path, monkeypatch):
    raw, errors = HOST.run_case(observer_binary, 'success')
    assert not errors
    reader, run, expected, _, _ = unit_run(tmp_path, monkeypatch, raw, main_console() + flow_console())
    original_open = Path.open
    def no_original_elf(path, *args, **kwargs):
        assert str(path) != '/never-open-original/appFw.so'
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', no_original_elf)
    result = reader.check_run(run, expected)
    assert result['runtime_receipt_bound'] is True and result['original_artifacts_unchanged'] is True
    assert result['Main_base_numeric_matches_only'][0]['tid'] == '42'
    assert result['FLOW_entry_candidates'][0]['correlation'] == 'FLOW_entry_raw_candidate_match'
    assert len(result['raw_context_candidates']) == 3
    assert all(result[key] is False for key in reader.FORMAT.FALSE_FLAGS)
    assert result['import_audit']['ordinary_libc_glib_imports'] == ['fwrite']


@pytest.mark.parametrize('console', (b'', main_console(base=0x5500100000),
                                    main_console() + flow_console() + flow_console(number=8)))
def test_missing_different_and_ambiguous_console_matches_stay_raw(observer_binary, console):
    raw, _ = HOST.run_case(observer_binary, 'success')
    reader = load_reader()
    result = reader.correlate(console, raw, HOST.schema())
    assert result['runtime_receipt_bound'] is False and result['Main_identity_verified'] is False
    if result['FLOW_entry_candidates']:
        assert result['FLOW_entry_candidates'][0]['correlation'] == 'raw_uncorrelated'


def test_console_records_count_only_physical_LF_and_ignore_embedded_CR_prefixes():
    reader = load_reader()
    ignored = b'opaque\r' + main_console() + b'opaque\r' + flow_console()
    prefix = ignored + b'noise\r\n'
    main = main_console().replace(b'\n', b'\r\n')
    mains, flows = reader.console_records(prefix + main + flow_console())
    assert len(mains) == len(flows) == 1
    assert mains[0]['raw_LF_line'] == 4 and mains[0]['byte_offset'] == len(prefix)
    assert bytes.fromhex(mains[0]['raw_hex']) == main
    assert flows[0]['raw_LF_line'] == 5 and flows[0]['byte_offset'] == len(prefix + main)


@pytest.mark.parametrize('mutation', ('argv', 'bool_rc', 'qemu_list', 'ordinary_list', 'needed_list', 'roles'))
def test_import_audit_rechecks_commands_and_derived_lists(tmp_path, monkeypatch, mutation):
    reader, _, _, _, receipt_path = unit_run(tmp_path, monkeypatch, b'', b'')
    receipt = reader.object_json(receipt_path.read_bytes())
    audit = reader.object_json(receipt_path.with_name('readonly-import-audit.json').read_bytes())
    reader.audit_imports(audit, receipt['library'], receipt['qemu'])
    if mutation == 'argv':
        audit['exports']['command'][-1] += '-different-candidate'
    elif mutation == 'bool_rc':
        audit['imports']['returncode'] = False
    elif mutation == 'qemu_list':
        audit['qemu_plugin_imports'].pop()
    elif mutation == 'ordinary_list':
        audit['ordinary_imports'] = []
    elif mutation == 'needed_list':
        audit['dt_needed'] = []
    else:
        del audit['ordinary_imports']
    with pytest.raises(ValueError):
        reader.audit_imports(audit, receipt['library'], receipt['qemu'])


def test_valid_Main_callback_is_not_misparsed_as_dispatch(observer_binary):
    raw, _ = HOST.run_case(observer_binary, 'success')
    callback = main_console().replace(b'site=dispatch', b'site=callback').replace(
        b'raw_known=1 numeric_route_match=1', b'raw_known=0 numeric_route_match=0')
    result = load_reader().correlate(callback + main_console(), raw, HOST.schema())
    assert len(result['Main_records']) == 1 and result['Main_records'][0]['raw_LF_line'] == 2


@pytest.mark.parametrize('name', ('ttbr0_el1', 'tpidr_el0', 'sp'))
def test_different_available_context_never_joins(observer_binary, name):
    raw, _ = HOST.run_case(observer_binary, 'success')
    before = {'ttbr0_el1': b'ttbr0_el1_raw=0x1234005500456000',
              'tpidr_el0': b'tpidr_el0_raw=0xfedcba9876543210', 'sp': b'sp_raw=0x0000007ffffffd00'}[name]
    after = {'ttbr0_el1': b'ttbr0_el1_raw=0x1234005500456001',
             'tpidr_el0': b'tpidr_el0_raw=0xfedcba9876543211', 'sp': b'sp_raw=0x0000007ffffffd01'}[name]
    changed = raw.replace(before, after, 1)
    assert changed != raw
    result = load_reader().correlate(main_console(), changed, HOST.schema())
    assert not result['raw_context_candidates']


def test_missing_tokens_never_join_absent_to_absent(observer_binary):
    raw, _ = HOST.run_case(observer_binary, 'absent')
    result = load_reader().correlate(main_console() + flow_console(), raw, HOST.schema())
    assert not result['raw_context_candidates']


def test_context_enumeration_preserves_all_combinations_without_time_pairing(observer_binary):
    raw, _ = HOST.run_case(observer_binary, 'quotas')
    # The C maximum-size case is other_aarch64: it remains raw despite reusable frames.
    result = load_reader().correlate(main_console(), raw, HOST.schema())
    assert not result['raw_context_candidates']
    raw, _ = HOST.run_case(observer_binary, 'reuse')
    result = load_reader().correlate(main_console(), raw, HOST.schema())
    assert len(result['raw_context_candidates']) == 8
    pairs = {(item['entry_trace_index'], item['internal_trace_index'])
             for item in result['raw_context_candidates']}
    assert len({entry for entry, _ in pairs}) == 2 and len({internal for _, internal in pairs}) == 4
    assert all(item['invocation_pairing'] == 'unknown' for item in result['raw_context_candidates'])


@pytest.mark.parametrize('mutation', ('returncode', 'bool_returncode', 'pid', 'wrong_run', 'trace_hash',
                                    'exit_flag', 'plugin', 'source', 'fixture', 'manifest_source', 'schema',
                                    'receipt', 'audit', 'profile_alias', 'symlink', 'hardlink', 'writable', 'host_close'))
def test_run_metadata_tamper_abnormal_exit_and_close_error_reject(
        observer_binary, tmp_path, monkeypatch, mutation):
    raw, _ = HOST.run_case(observer_binary, 'success')
    reader, run, expected, root, receipt_path = unit_run(tmp_path, monkeypatch, raw, main_console() + flow_console())
    if mutation in ('returncode', 'bool_returncode', 'pid', 'wrong_run', 'trace_hash', 'exit_flag'):
        path = run / 'readonly-scope-exit.json'
        record = reader.object_json(path.read_bytes())
        key, value = {'returncode': ('returncode', -15), 'bool_returncode': ('returncode', False),
                      'pid': ('owned_wrapper_pid', True), 'wrong_run': ('run', str(run.parent)),
                      'trace_hash': ('log_sha256', '0' * 64), 'exit_flag': ('capture_verified', True)}[mutation]
        record[key] = value
        dump(path, record)
    elif mutation == 'plugin':
        (run / 'readonly-scope-observer.so').write_bytes(b'changed')
    elif mutation in ('source', 'fixture', 'schema'):
        name = {'source': 'scope-observer.c', 'fixture': 'integration/fixture.S',
                'schema': 'log-schema-shutter-gate-v1.json'}[mutation]
        path = root / name
        path.write_bytes(path.read_bytes() + b'\n')
    elif mutation == 'manifest_source':
        path = run / 'runtime-manifest.json'
        manifest = reader.object_json(path.read_bytes())
        manifest['files'][str(root / 'scope-observer.c')] = '0' * 64
        dump(path, manifest)
    elif mutation == 'receipt':
        receipt_path.write_bytes(receipt_path.read_bytes() + b'\n')
    elif mutation == 'audit':
        (receipt_path.parent / 'readonly-import-audit.json').write_bytes(b'{}\n')
    elif mutation == 'profile_alias':
        path = run / 'runtime-manifest.json'
        manifest = reader.object_json(path.read_bytes())
        manifest['readonly_scope_observer']['source_root'] = str(root)
        dump(path, manifest)
    elif mutation == 'symlink':
        path = run / 'readonly-scope-trace.log'
        original = run / 'trace-original.log'
        path.rename(original)
        path.symlink_to(original)
    elif mutation == 'hardlink':
        os.link(run / 'readonly-scope-trace.log', run / 'trace-hardlink.log')
    elif mutation == 'writable':
        (run / 'readonly-scope-trace.log').chmod(0o666)
    else:
        (run / 'console.log').write_bytes(main_console() + b'scope_observer_host_error stage=close errno=0x5\n')
    with pytest.raises(reader.RejectedTrace):
        reader.check_run(run, expected)


def test_input_change_between_snapshots_rejects(observer_binary, tmp_path, monkeypatch):
    raw, _ = HOST.run_case(observer_binary, 'success')
    reader, run, expected, _, _ = unit_run(tmp_path, monkeypatch, raw, b'')
    original = reader.correlate
    def mutate_after_parse(*args):
        result = original(*args)
        (run / 'console.log').write_bytes(b'late modification\n')
        return result
    monkeypatch.setattr(reader, 'correlate', mutate_after_parse)
    with pytest.raises(reader.RejectedTrace, match='changed during'):
        reader.check_run(run, expected)


def test_wrong_schema_rehash_still_refuses_semantic_contract(observer_binary, tmp_path, monkeypatch):
    raw, _ = HOST.run_case(observer_binary, 'success')
    reader, run, expected, root, _ = unit_run(tmp_path, monkeypatch, raw, b'')
    path = root / 'log-schema-shutter-gate-v1.json'
    old = reader.object_json(path.read_bytes())
    old['schema'] = 'readonly_scope_v1'
    dump(path, old)
    expected = copy.deepcopy(expected)
    expected['trace_schema_sha256'] = expected['source_sha256'][path.name] = digest(path.read_bytes())
    with pytest.raises(reader.RejectedTrace, match='schema'):
        reader.check_run(run, expected)


@pytest.mark.parametrize('mutation', ('missing_schema_sha', 'wrong_schema_sha', 'self_sha'))
def test_contract_binds_real_schema_and_forbids_only_self_digest(mutation):
    reader = load_reader()
    schema_sha = digest((HERE / 'log-schema-shutter-gate-v1.json').read_bytes())
    contract = reader.object_json((HERE / 'source-contract-shutter-gate-v1.json').read_bytes())
    assert contract['trace_schema_sha256'] == schema_sha
    reader.check_contract(contract, schema_sha)
    if mutation == 'missing_schema_sha':
        del contract['trace_schema_sha256']
    elif mutation == 'wrong_schema_sha':
        contract['trace_schema_sha256'] = '0' * 64
    else:
        contract['source_contract_sha256'] = digest((HERE / 'source-contract-shutter-gate-v1.json').read_bytes())
    with pytest.raises(ValueError, match='contract differs'):
        reader.check_contract(contract, schema_sha)


def add_invalid_unused_json(raw, token):
    fragment = (b'"unused_extra":{"duplicate":0,"duplicate":1}' if token == 'duplicate' else
                b'"unused_extra":{"nested":[{"number":' + token.encode('ascii') + b'}]}')
    body = raw.rstrip()
    assert body.endswith(b'}')
    return body[:-1] + b',' + fragment + b'}\n'


@pytest.mark.parametrize('boundary', ('schema', 'contract', 'manifest', 'receipt', 'audit', 'exit'))
@pytest.mark.parametrize('token', ('duplicate', 'NaN', 'Infinity', '-Infinity', '1e999'))
def test_every_run_json_boundary_rejects_invalid_unused_extra_after_matching_pins(
        observer_binary, tmp_path, monkeypatch, boundary, token):
    raw, _ = HOST.run_case(observer_binary, 'success')
    reader, run, expected, root, receipt_path = unit_run(tmp_path, monkeypatch, raw, b'')
    manifest_path = run / 'runtime-manifest.json'
    manifest = reader.object_json(manifest_path.read_bytes())
    receipt = reader.object_json(receipt_path.read_bytes())
    audit_path = receipt_path.parent / 'readonly-import-audit.json'
    paths = {'schema': root / 'log-schema-shutter-gate-v1.json',
             'contract': root / 'source-contract-shutter-gate-v1.json', 'audit': audit_path}
    if boundary in paths:
        path = paths[boundary]
        path.write_bytes(add_invalid_unused_json(path.read_bytes(), token))
    closure = {name: digest((root / name).read_bytes()) for name in reader.BUILD_SOURCES}
    schema_sha = closure['log-schema-shutter-gate-v1.json']
    expected.update(source_sha256=closure, trace_schema_sha256=schema_sha,
                    readonly_import_audit_sha256=digest(audit_path.read_bytes()))
    receipt.update(source_sha256=closure, trace_schema_sha256=schema_sha,
                   source_contract_sha256=closure['source-contract-shutter-gate-v1.json'],
                   readonly_import_audit_sha256=expected['readonly_import_audit_sha256'])
    dump(receipt_path, receipt)
    if boundary == 'receipt':
        receipt_path.write_bytes(add_invalid_unused_json(receipt_path.read_bytes(), token))
    expected['build_receipt_sha256'] = digest(receipt_path.read_bytes())
    manifest['readonly_scope_observer'].update(
        source_sha256=closure, trace_schema_sha256=schema_sha,
        source_contract_sha256=closure['source-contract-shutter-gate-v1.json'],
        build_receipt_sha256=expected['build_receipt_sha256'])
    manifest['files'].update({str(root / name): value for name, value in closure.items()})
    manifest['files'][str(receipt_path)] = expected['build_receipt_sha256']
    dump(manifest_path, manifest)
    if boundary == 'manifest':
        manifest_path.write_bytes(add_invalid_unused_json(manifest_path.read_bytes(), token))
    if boundary == 'exit':
        path = run / 'readonly-scope-exit.json'
        path.write_bytes(add_invalid_unused_json(path.read_bytes(), token))
    with pytest.raises(reader.RejectedTrace, match='duplicate JSON|nonfinite JSON'):
        reader.check_run(run, expected)


@pytest.mark.parametrize('value', (float('nan'), float('inf'), float('-inf')))
def test_expected_pin_tree_rejects_nonfinite_even_in_unused_extra(observer_binary, tmp_path, monkeypatch, value):
    raw, _ = HOST.run_case(observer_binary, 'success')
    reader, run, expected, _, _ = unit_run(tmp_path, monkeypatch, raw, b'')
    expected['unused_extra'] = {'nested': [value]}
    with pytest.raises(reader.RejectedTrace, match='nonfinite JSON'):
        reader.check_run(run, expected)
