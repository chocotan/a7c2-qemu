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
_spec = importlib.util.spec_from_file_location('shutter_v2_run_host_support', HERE / 'test_scope_observer.py')
HOST = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(HOST)
observer_binary = HOST.observer_binary


def load_reader():
    spec = importlib.util.spec_from_file_location('shutter_v2_run_reader', HERE / 'check_shutter_gate_v2.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def unit_support():
    spec = importlib.util.spec_from_file_location(
        'shutter_v2_unit_operand_support', HERE / 'integration/test_shutter_gate_trace_checks_v2.py')
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
                'trace_schema_sha256': closure['log-schema-shutter-gate-v2.json'],
                'qemu_sha256': reader.QEMU_SHA256, 'qemu_header_sha256': reader.HEADER_SHA256,
                'library_sha256': digest(plugin),
                'observer_sha256': digest(b'unit-only Main observer marker'),
                'Main_source_sha256': digest(b'unit-only Main formatter source marker'),
                'original_appfw_sha256': digest(b'unit-only appFw manifest marker; never original firmware'),
                'readonly_import_audit_sha256': digest(audit_path.read_bytes())}
    receipt = dict(schema=reader.PROFILE, plugin_api=7, trace_schema=reader.SCHEMA,
                   source_contract_sha256=closure['source-contract-shutter-gate-v2.json'],
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
                   source_contract_sha256=closure['source-contract-shutter-gate-v2.json'],
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
    assert len(result['raw_context_candidates']) == 4
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
    support = unit_support()
    sequence = [('final_entry', support.independent_row('final_entry'))] * 2 + support.source_sequence() * 2
    raw = support.synthetic_trace(sequence)
    result = load_reader().correlate(main_console(), raw, HOST.schema())
    assert len(result['raw_context_candidates']) == 16
    pairs = {(item['entry_trace_index'], item['internal_trace_index'])
             for item in result['raw_context_candidates']}
    assert len({entry for entry, _ in pairs}) == 2 and len({internal for _, internal in pairs}) == 8
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
                'schema': 'log-schema-shutter-gate-v2.json'}[mutation]
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
    path = root / 'log-schema-shutter-gate-v2.json'
    old = reader.object_json(path.read_bytes())
    old['schema'] = 'readonly_scope_v2'
    dump(path, old)
    expected = copy.deepcopy(expected)
    expected['trace_schema_sha256'] = expected['source_sha256'][path.name] = digest(path.read_bytes())
    with pytest.raises(reader.RejectedTrace, match='schema'):
        reader.check_run(run, expected)


@pytest.mark.parametrize('mutation', ('missing_schema_sha', 'wrong_schema_sha', 'self_sha'))
def test_contract_binds_real_schema_and_forbids_only_self_digest(mutation):
    reader = load_reader()
    schema_sha = digest((HERE / 'log-schema-shutter-gate-v2.json').read_bytes())
    contract = reader.object_json((HERE / 'source-contract-shutter-gate-v2.json').read_bytes())
    assert contract['trace_schema_sha256'] == schema_sha
    reader.check_contract(contract, schema_sha)
    if mutation == 'missing_schema_sha':
        del contract['trace_schema_sha256']
    elif mutation == 'wrong_schema_sha':
        contract['trace_schema_sha256'] = '0' * 64
    else:
        contract['source_contract_sha256'] = digest((HERE / 'source-contract-shutter-gate-v2.json').read_bytes())
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
    paths = {'schema': root / 'log-schema-shutter-gate-v2.json',
             'contract': root / 'source-contract-shutter-gate-v2.json', 'audit': audit_path}
    if boundary in paths:
        path = paths[boundary]
        path.write_bytes(add_invalid_unused_json(path.read_bytes(), token))
    closure = {name: digest((root / name).read_bytes()) for name in reader.BUILD_SOURCES}
    schema_sha = closure['log-schema-shutter-gate-v2.json']
    expected.update(source_sha256=closure, trace_schema_sha256=schema_sha,
                    readonly_import_audit_sha256=digest(audit_path.read_bytes()))
    receipt.update(source_sha256=closure, trace_schema_sha256=schema_sha,
                   source_contract_sha256=closure['source-contract-shutter-gate-v2.json'],
                   readonly_import_audit_sha256=expected['readonly_import_audit_sha256'])
    dump(receipt_path, receipt)
    if boundary == 'receipt':
        receipt_path.write_bytes(add_invalid_unused_json(receipt_path.read_bytes(), token))
    expected['build_receipt_sha256'] = digest(receipt_path.read_bytes())
    manifest['readonly_scope_observer'].update(
        source_sha256=closure, trace_schema_sha256=schema_sha,
        source_contract_sha256=closure['source-contract-shutter-gate-v2.json'],
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


@pytest.fixture
def source_units():
    return load_reader(), unit_support()


def test_missing_entry_keeps_source_and_does_not_backfill_identity(source_units):
    reader, support = source_units
    raw = support.synthetic_trace(support.source_sequence())
    result = reader.correlate(main_console() + flow_console(), raw, HOST.schema())
    assert len(result['source_callback_rows']) == 1
    assert not result['FLOW_entry_candidates'] and not result['raw_context_candidates']
    assert not any(row.get('site') == 'final_entry' for row in result['rows'])
    assert len(result['FLOW_source_numeric_candidates']) == 1
    assert len(result['source_branch_context_candidates']) == 1
    assert len(result['source_branch_successor_context_candidates']) == 2
    assert result['invocation_pairing'] == result['raw_identity'] == 'unknown'
    assert result['runtime_receipt_bound'] is False
    assert all(result[name] is False for name in reader.FORMAT.FALSE_FLAGS)
    source = result['source_callback_rows'][0]
    assert source['source_trace_index'] == 1 and source['row'] == result['rows'][1]
    assert source['raw_record'] == result['raw_ledger'][1]
    assert bytes.fromhex(source['raw_record']['raw_hex']) in raw


@pytest.mark.parametrize('pointer', (0, 0x1122334455667788, 0xffffffffffffffff, 0x5507e5d570))
def test_source_pointer_static_match_or_mismatch_preserves_all64_bits(source_units, pointer):
    reader, support = source_units
    baseline = support.independent_row('d570_ldr_pre', x0=pointer)
    raw = support.synthetic_trace([('d570_ldr_pre', baseline)])
    result = reader.correlate(b'', raw, HOST.schema())
    source = result['source_callback_rows'][0]
    assert source['source_pointer_u64'] == pointer
    assert source['static_current_address_available'] is True
    assert source['static_current_address_u64'] == support.B + 0x7e5d570
    assert source['static_current_address_numeric_match'] is (pointer == support.B + 0x7e5d570)
    assert source['row']['x0_raw'] == '0x%016x' % pointer
    assert not result['FLOW_entry_candidates'] and not result['raw_context_candidates']
    assert all(result[name] is False for name in reader.FORMAT.FALSE_FLAGS)


def test_static_current_checked_low48_overflow_is_unavailable_without_discarding_source(source_units):
    reader, support = source_units
    base = (reader.FORMAT.LOW48_MAX - 0x1af183f) & ~0xfff
    pointer = (base + 0x7e5d570) & reader.FORMAT.LOW48_MAX
    assert base + 0x1af183f <= reader.FORMAT.LOW48_MAX < base + 0x7e5d570
    sequence = [('d570_ldr_pre', support.independent_row('d570_ldr_pre', x0=pointer))]
    raw = support.synthetic_trace(sequence, base=base)
    result = reader.correlate(b'', raw, HOST.schema())
    source = result['source_callback_rows'][0]
    assert source['source_pointer_u64'] == pointer
    assert source['static_current_address_available'] is False
    assert source['static_current_address_numeric_match'] == source['static_current_address_u64'] == 'unknown'
    assert 'low48' in source['static_current_address_unavailable_reason']
    assert result['trace_sha256'] == digest(raw)


@pytest.mark.parametrize('console', (b'', main_console(base=0x5500100000),
                                     main_console().replace(b'raw_known=1', b'raw_known=0')))
def test_source_FLOW_requires_strict_same_base_Main_metadata(source_units, console):
    reader, support = source_units
    raw = support.synthetic_trace(support.source_sequence())
    if b'raw_known=0' in console:
        with pytest.raises(reader.RejectedTrace):
            reader.correlate(console + flow_console(), raw, HOST.schema())
    else:
        result = reader.correlate(console + flow_console(), raw, HOST.schema())
        assert not result['FLOW_source_numeric_candidates']
        assert len(result['source_callback_rows']) == 1


def test_source_FLOW_uses_X23_W22_not_source_X0_or_callee_arguments_and_keeps_all_matches(source_units):
    reader, support = source_units
    sequence = support.source_sequence()
    sequence[0][1]['registers']['x0'] = 0xdeadbeef01234567
    raw = support.synthetic_trace(sequence)
    result = reader.correlate(main_console() + flow_console() + flow_console(number=8), raw, HOST.schema())
    assert len(result['FLOW_source_numeric_candidates']) == 2
    assert len(result['source_branch_context_candidates']) == 1
    assert len(result['source_branch_successor_context_candidates']) == 2
    assert not result['FLOW_entry_candidates']
    for candidate in result['FLOW_source_numeric_candidates']:
        source = result['rows'][candidate['source_trace_index']]
        flow = candidate['FLOW_record']
        assert int(flow['a0'], 16) == int(source['x23_raw'], 16) != int(source['x0_raw'], 16)
        assert int(flow['a1'], 16) != int(source['x22_raw'], 16)
        assert int(flow['a1'], 16) & 0xffffffff == int(source['x22_raw'], 16) & 0xffffffff
        assert candidate['invocation_pairing'] == 'unknown'
        assert bytes.fromhex(flow['raw_hex']).startswith(b'OBS SHUTTER_FLOW site=final ')
        assert candidate['source_raw_record']['sha256'] == result['raw_ledger'][1]['sha256']
    assert result['Main_identity_verified'] is result['AP_identity_verified'] is False
    sequence[0][1]['registers']['x23'] ^= 1 << 32
    result = reader.correlate(main_console() + flow_console(), support.synthetic_trace(sequence), HOST.schema())
    assert not result['FLOW_source_numeric_candidates']


@pytest.mark.parametrize('name', ('ttbr0_el1', 'tpidr_el0'))
@pytest.mark.parametrize('missing_at', ('source', 'branch', 'both'))
def test_source_branch_missing_tokens_never_join_absent_to_absent(source_units, name, missing_at):
    reader, support = source_units
    sequence = support.source_sequence()
    for index, side in ((0, 'source'), (1, 'branch')):
        if missing_at in (side, 'both'):
            sequence[index][1][name] = None
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert len(result['source_callback_rows']) == 1
    assert not result['source_branch_context_candidates']
    assert not result['source_branch_successor_context_candidates']
    assert result['invocation_pairing_verified'] is False


@pytest.mark.parametrize('name', ('ttbr0_el1', 'tpidr_el0', 'sp', 'x19', 'x22', 'x23', 'x29', 'x30', 'cpsr'))
def test_source_branch_full64_frame_SP_token_and_raw_CPSR_mismatch_prevents_join(source_units, name):
    reader, support = source_units
    sequence = support.source_sequence()
    branch = sequence[1][1]
    if name in ('ttbr0_el1', 'tpidr_el0', 'sp'):
        branch[name] ^= 1 << 32
    elif name == 'cpsr':
        branch[name] ^= 1 << 28
    else:
        branch['registers'][name] ^= 1 << 32
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert not result['source_branch_context_candidates']
    assert not result['source_branch_successor_context_candidates']
    assert len(result['source_callback_rows']) == 1


@pytest.mark.parametrize('missing_at', ('source', 'branch', 'both'))
def test_source_branch_optional_SP_requires_both_when_one_available(source_units, missing_at):
    reader, support = source_units
    sequence = support.source_sequence()
    for index, side in ((0, 'source'), (1, 'branch')):
        if missing_at in (side, 'both'):
            sequence[index][1]['sp'] = None
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert bool(result['source_branch_context_candidates']) is (missing_at == 'both')
    if missing_at == 'both':
        assert result['source_branch_context_candidates'][0]['SP_frame_checked'] is False
        assert not result['source_branch_successor_context_candidates']


@pytest.mark.parametrize('value', (0xfeedface00000000, 0xfeedface00000001))
def test_source_and_branch_X0_have_distinct_meanings_and_both_real_successors_remain(source_units, value):
    reader, support = source_units
    sequence = support.source_sequence()
    sequence[0][1]['registers']['x0'] = 0xdeadbeef01234567
    sequence[1][1]['registers']['x0'] = value
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert len(result['source_branch_context_candidates']) == 1
    triples = result['source_branch_successor_context_candidates']
    assert len(triples) == 2
    predicted_site = 'successor_1724_pre' if value & 0xffffffff else 'successor_1838_pre'
    assert [item['observed_successor_site'] for item in triples if item['source_prediction_numeric_match']] == [predicted_site]
    assert all(result[name] is False for name in reader.FORMAT.FALSE_FLAGS)


def test_same_wrong_SP_cannot_substitute_for_raw_frame(source_units):
    reader, support = source_units
    sequence = support.source_sequence()
    for _, baseline in sequence:
        baseline['sp'] += 8
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert not result['source_branch_context_candidates']
    assert len(result['source_callback_rows']) == 1


def test_source_branch_checked_frame_addition_does_not_wrap(source_units):
    reader, support = source_units
    sequence = support.source_sequence()
    for _, baseline in sequence:
        baseline['registers'].update(x29=(1 << 64) - 0x48, x19=0)
        baseline['sp'] = (1 << 64) - 0x48
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert len(result['source_callback_rows']) == 1
    assert not result['source_branch_context_candidates']


def test_source_branch_other_A64_mode_remains_raw_without_EL0_candidates(source_units):
    reader, support = source_units
    sequence = support.source_sequence()
    for _, baseline in sequence:
        baseline['cpsr'] |= 5
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert len(result['source_callback_rows']) == 1
    assert not result['source_branch_context_candidates']
    assert result['source_callback_rows'][0]['row']['context_mode'] == 'other_aarch64'


def test_source_branch_successor_reentry_retains_every_ordered_combination_and_prediction_mismatch(source_units):
    reader, support = source_units
    sites = ('d570_ldr_pre', 'd570_ldr_pre', 'd570_cbnz_pre', 'd570_cbnz_pre',
             'successor_1724_pre', 'successor_1838_pre')
    raw = support.synthetic_trace([(site, support.independent_row(site)) for site in sites])
    result = reader.correlate(main_console() + flow_console(), raw, HOST.schema())
    assert len(result['source_callback_rows']) == len(result['FLOW_source_numeric_candidates']) == 2
    assert len(result['source_branch_context_candidates']) == 4
    triples = result['source_branch_successor_context_candidates']
    assert len(triples) == 8
    assert {(item['source_trace_index'], item['branch_trace_index'], item['successor_trace_index']) for item in triples} == {
        (source, branch, successor) for source in (1, 2) for branch in (3, 4) for successor in (5, 6)}
    assert sum(item['source_prediction_numeric_match'] for item in triples) == 4
    for item in triples:
        assert item['observed_successor_pc'] == support.B + support.EVENTS[item['observed_successor_site']]
        assert item['invocation_pairing'] == 'unknown'
        assert item['successor_raw_record']['sha256'] == result['raw_ledger'][item['successor_trace_index']]['sha256']
    assert result['invocation_pairing'] == 'unknown'
    assert all(result[name] is False for name in reader.FORMAT.FALSE_FLAGS)


@pytest.mark.parametrize('sites,pairs,triples', (
    (('d570_cbnz_pre', 'd570_ldr_pre', 'successor_1724_pre'), 0, 0),
    (('d570_ldr_pre', 'successor_1724_pre', 'd570_cbnz_pre'), 1, 0),
    (('d570_ldr_pre', 'd570_cbnz_pre', 'd570_ldr_pre', 'd570_cbnz_pre', 'successor_1724_pre'), 3, 3)))
def test_source_candidates_use_trace_order_without_nearest_pair_selection(source_units, sites, pairs, triples):
    reader, support = source_units
    raw = support.synthetic_trace([(site, support.independent_row(site)) for site in sites])
    result = reader.correlate(b'', raw, HOST.schema())
    assert len(result['source_branch_context_candidates']) == pairs
    assert len(result['source_branch_successor_context_candidates']) == triples


@pytest.mark.parametrize('name', ('ttbr0_el1', 'tpidr_el0', 'sp', 'x22', 'cpsr'))
def test_successor_context_is_checked_independently_and_mismatch_keeps_raw(source_units, name):
    reader, support = source_units
    sequence = support.source_sequence()
    successor = sequence[2][1]
    if name == 'x22':
        successor['registers'][name] ^= 1 << 32
    else:
        successor[name] ^= 1 << (28 if name == 'cpsr' else 32)
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert len(result['source_branch_context_candidates']) == 1
    assert len(result['source_branch_successor_context_candidates']) == 1
    assert result['source_branch_successor_context_candidates'][0]['observed_successor_site'] == 'successor_1838_pre'
    assert result['source_branch_successor_context_candidates'][0]['source_prediction_numeric_match'] is False
    assert any(row.get('site') == 'successor_1724_pre' for row in result['rows'])


def test_delayed_gdb_PC_does_not_replace_event_PC_or_break_context_candidates(source_units):
    reader, support = source_units
    sequence = support.source_sequence()
    for index, (_, baseline) in enumerate(sequence):
        baseline['registers']['pc'] = 0xfedcba9876543200 + index
    result = reader.correlate(b'', support.synthetic_trace(sequence), HOST.schema())
    assert len(result['source_branch_context_candidates']) == 1
    assert len(result['source_branch_successor_context_candidates']) == 2
    source = result['source_callback_rows'][0]['row']
    assert source['gdb_pc_raw'] == '0xfedcba9876543200'
    assert int(source['event_pc'], 16) == support.B + 0x1af1830


@pytest.mark.parametrize('role', ('source', 'fixture', 'root', 'manifest_v1', 'manifest_scope_v2'))
def test_v2_run_refuses_mixed_closure_and_root(source_units, tmp_path, monkeypatch, role):
    _, support = source_units
    raw = support.synthetic_trace(support.source_sequence())
    reader, run, expected, root, _ = unit_run(tmp_path, monkeypatch, raw, b'')
    if role in ('source', 'fixture'):
        field = 'source_sha256' if role == 'source' else 'fixture_source_sha256'
        name = ('integration/shutter_gate_trace_checks_v2.py' if role == 'fixture' else
                'log-schema-shutter-gate-v2.json')
        expected[field][name.replace('v2', 'v1')] = expected[field].pop(name)
    elif role == 'root':
        monkeypatch.setattr(reader, 'HERE', root.with_name('2026-10-31-qemu-shutter-gate-observer-v1'))
    else:
        path = run / 'runtime-manifest.json'
        value = reader.object_json(path.read_bytes())
        value['readonly_scope_observer']['profile'] = ('qemu-readonly-shutter-gate-v1' if role == 'manifest_v1'
                                                       else 'qemu-readonly-scope-v2')
        dump(path, value)
    with pytest.raises(reader.RejectedTrace):
        reader.check_run(run, expected)


@pytest.mark.parametrize('alias', ('source_root', 'Source_root', 'sourceDependencyFrozen',
                                   'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'))
@pytest.mark.parametrize('boundary', ('expected', 'manifest', 'receipt', 'contract'))
def test_v2_aliases_are_rejected_even_after_actual_rehash(source_units, tmp_path, monkeypatch, alias, boundary):
    _, support = source_units
    reader, run, expected, root, receipt_path = unit_run(
        tmp_path, monkeypatch, support.synthetic_trace(support.source_sequence()), b'')
    if boundary == 'contract':
        contract = reader.object_json((root / 'source-contract-shutter-gate-v2.json').read_bytes())
        contract[alias] = 'unaccepted alias'
        with pytest.raises(ValueError, match='contract differs'):
            reader.check_contract(contract, expected['trace_schema_sha256'])
        return
    manifest_path = run / 'runtime-manifest.json'
    manifest = reader.object_json(manifest_path.read_bytes())
    if boundary == 'expected':
        expected[alias] = 'unaccepted alias'
    elif boundary == 'manifest':
        manifest['readonly_scope_observer'][alias] = 'unaccepted alias'
    else:
        receipt = reader.object_json(receipt_path.read_bytes())
        receipt[alias] = 'unaccepted alias'
        dump(receipt_path, receipt)
        expected['build_receipt_sha256'] = digest(receipt_path.read_bytes())
        manifest['readonly_scope_observer']['build_receipt_sha256'] = expected['build_receipt_sha256']
        manifest['files'][str(receipt_path)] = expected['build_receipt_sha256']
    dump(manifest_path, manifest)
    with pytest.raises(reader.RejectedTrace):
        reader.check_run(run, expected)


@pytest.mark.parametrize('role', ('source', 'fixture', 'root', 'v1_schema', 'scope_v2_schema'))
def test_v2_semantic_contract_refuses_mixed_maps_or_root_after_matching_schema_pin(role):
    reader = load_reader()
    schema_sha = digest((HERE / 'log-schema-shutter-gate-v2.json').read_bytes())
    contract = reader.object_json((HERE / 'source-contract-shutter-gate-v2.json').read_bytes())
    if role in ('source', 'fixture'):
        key = ('actual_build_source_names_required' if role == 'source' else 'actual_fixture_source_names_required')
        contract[key][-1] = contract[key][-1].replace('v2', 'v1')
    elif role == 'root':
        contract['fixed_future_source_root'] = contract['fixed_future_source_root'].replace('2026-11-02', '2026-10-31')
    else:
        contract['trace_schema'] = 'readonly_shutter_gate_v1' if role == 'v1_schema' else 'readonly_scope_v2'
    with pytest.raises(ValueError, match='contract differs'):
        reader.check_contract(contract, schema_sha)

