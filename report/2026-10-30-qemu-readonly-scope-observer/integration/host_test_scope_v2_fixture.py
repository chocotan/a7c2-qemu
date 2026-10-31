"""HOST_TEST synthetic data only; never a Sony run, API replay or runtime receipt."""
from pathlib import Path
import copy
import hashlib
import json

HERE = Path(__file__).resolve().parent
BASE = 0x4000000000
TOKENS = {'ttbr0_el1': 0x1234000400100000, 'tpidr_el0': 0xabcd000040208000}
COMMON = {'status': 'native_unverified', 'identity': 'unknown', 'binding': 'unbound',
          'pid': 'unknown', 'tid': 'unknown', 'capture': '0x0', 'physical': '0x0'}
GPRS = ('x0', 'x19', 'x20', 'x21', 'x23', 'x24', 'x29', 'x30')


def h64(value):
    return '0x%016x' % value


def flags(mode=0):
    cpsr = 0xa00003c0 | mode
    return {'cpsr_raw': '0x%08x' % cpsr, 'cpsr_m': '0x%02x' % mode,
            'context_mode': 'EL0t' if mode == 0 else 'other_aarch64',
            'nzcv': '0xa0000000', 'nzcv_mask': '0xf0000000'}


def optionals(include_sp=True, individual_ok=True):
    result = {}
    values = dict(TOKENS, **({'sp': BASE + 0x200000} if include_sp else {}))
    for name, value in values.items():
        result.update({name + '_available': '0x1', name + '_raw': h64(value), name + '_read_length': '0x8'})
        if individual_ok:
            result[name + '_api_ok'] = '0x1'
    return result


def begin_row():
    schema = json.loads((HERE.parent / 'log-schema-v2.json').read_bytes())
    return dict(schema['kinds']['begin'], kind='begin', **COMMON)


def candidate_row():
    return dict(kind='candidate', candidate_base=h64(BASE), translated_entry_pc=h64(BASE + 0x2e068cc),
                anchor_length='0x18', **COMMON)


def scope_row():
    row = dict(kind='entry', vcpu='0x0', lr_slot='0x0', ordinal='0x1',
               actual_pc=h64(BASE + 0x2e068cc), translated_entry_pc=h64(BASE + 0x2e068cc),
               candidate_base=h64(BASE), lr=h64(BASE + 0x209ee80), sp=h64(BASE + 0x200000),
               sp_read_length='0x8', api_ok='0x1', **COMMON)
    row.update({name: h64(0x1234567800000000 + index) for index, name in enumerate(GPRS)})
    row['x30'] = row['lr']
    row.update({name + '_read_length': '0x8' for name in ('pc', 'lr', *GPRS)})
    row['cpsr_read_length'] = '0x4'
    row.update(flags())
    row.update(optionals(False, False))
    return row


def power_row():
    row = dict(kind='poweron_context', site='dispatch', vcpu='0x0', ordinal='0x1',
               actual_pc=h64(BASE + 0x1951844), translated_entry_pc=h64(BASE + 0x1951844),
               candidate_base=h64(BASE), anchor_length='0x8', controller=h64(0x40010000),
               raw_x2='0xaabbccdd01000090', raw_u32='0x01000090', caller_raw=h64(BASE + 0x1e79354),
               api_ok='0x1', cpsr_read_length='0x4', **COMMON)
    row.update({name + '_read_length': '0x8' for name in ('pc', 'x0', 'x2', 'x30')})
    row.update(flags())
    row.update(optionals(False))
    return row


def producer_row(site='entry', scope_seen=True):
    row = dict(kind='M_producer', site=site, vcpu='0x0', ordinal='0x1', producer_sequence='0x1',
               callback_phase='before_instruction', event_pc=h64(BASE + (0x276e710 if site == 'entry' else 0x276e71c)),
               gdb_pc_raw=h64(BASE + 0x276e710), candidate_base=h64(BASE),
               scope_anchor_seen='0x1' if scope_seen else '0x0', anchor_length='0x18', input_kind='u32_value',
               x0_raw='0xfedcba9800000007', raw_input_u32='0x00000007', proposed_u32='unknown',
               x30_raw='0xabcdfffffeeda004', caller_raw='0xabcdfffffeeda004', api_ok='0x1', **COMMON)
    row.update(flags())
    row.update(optionals())
    for name in ('gdb_pc', 'x0', 'x30', 'cpsr'):
        row[name + '_read_length'] = '0x4' if name == 'cpsr' else '0x8'
        row[name + '_api_ok'] = '0x1'
    if site == 'pre_M_store':
        row.update(proposed_u32=row['raw_input_u32'], x1_raw=h64(BASE + 0x7e6a4d8), x1_read_length='0x8',
                   x1_api_ok='0x1', effective_destination_raw=h64(BASE + 0x7e6a7c8), destination_match='0x1')
    return row


def late_row(site='M_cmp_pre'):
    offsets = {'M_cmp_pre': 0x209ee58, 'M_bne_pre': 0x209ee5c, 'request0_bl_pre': 0x209ee9c}
    row = dict(kind='late', site=site, vcpu='0x0', ordinal='0x1', late_sequence='0x1',
               callback_phase='before_instruction', event_pc=h64(BASE + offsets[site]),
               gdb_pc_raw=h64(BASE + 0x209ee54), candidate_base=h64(BASE), anchor_length='0xc',
               x0='0x1234567800000000', x19=h64(BASE + 0x1000), x23='0x0000000000000000',
               x30='0xabcdfffffeeda004', api_ok='0x1', **COMMON)
    row.update(flags())
    row.update(optionals())
    for name in ('gdb_pc', 'x0', 'x19', 'x23', 'x30', 'cpsr'):
        row[name + '_read_length'] = '0x4' if name == 'cpsr' else '0x8'
        row[name + '_api_ok'] = '0x1'
    if site == 'request0_bl_pre':
        row.update(x1='0x1234567800000000', w1='0x00000000', x1_read_length='0x8', x1_api_ok='0x1', lr_phase='before_bl')
    else:
        row.update(loaded_M_u32='0x00000000', flags_phase='before_cmp')
        if site == 'M_bne_pre':
            row.update(flags_phase='after_cmp_before_bne', z='0x0', source_next_pc=h64(BASE + 0x209ee80), source_next_basis='cpsr_Z')
    return row


def end_row(rows):
    return dict(kind='end', stop='none', ambiguous='0x0', candidate_found='0x1', candidate_base=h64(BASE),
                conflicting_base=h64(0), producer_anchor_found='0x1', producer_base=h64(BASE),
                producer_conflicting_base=h64(0),
                lr0_records=hex(sum(row['kind'] == 'entry' and row['lr_slot'] == '0x0' for row in rows)),
                lr1_records=hex(sum(row['kind'] == 'entry' and row['lr_slot'] == '0x1' for row in rows)),
                poweron_records=hex(sum(row['kind'] == 'poweron_context' for row in rows)),
                producer0_records=hex(sum(row['kind'] == 'M_producer' and row['site'] == 'entry' for row in rows)),
                producer1_records=hex(sum(row['kind'] == 'M_producer' and row['site'] == 'pre_M_store' for row in rows)),
                producer_sequence=hex(sum(row['kind'] == 'M_producer' for row in rows)),
                late0_records=hex(sum(row['kind'] == 'late' and row['site'] == 'M_cmp_pre' for row in rows)),
                late1_records=hex(sum(row['kind'] == 'late' and row['site'] == 'M_bne_pre' for row in rows)),
                late2_records=hex(sum(row['kind'] == 'late' and row['site'] == 'request0_bl_pre' for row in rows)),
                late_sequence=hex(sum(row['kind'] == 'late' for row in rows)),
                fault_lines='0x0', faults=h64(0), suppressed_faults=h64(0), other_lr=h64(0), close_result='unknown', **COMMON)


def encode(rows):
    return ''.join('kind=' + row['kind'] + ' ' + ' '.join(key + '=' + value for key, value in row.items() if key != 'kind') + '\n'
                   for row in rows).encode('ascii')


def joined_case(early=False, sites=('entry', 'pre_M_store')):
    rows = [begin_row(), candidate_row(), power_row(), scope_row(), late_row()]
    producers = [producer_row(site, not early) for site in sites]
    for sequence, row in enumerate(producers, 1):
        row['producer_sequence'] = hex(sequence)
    if early:
        rows[1:1] = producers
    else:
        rows.extend(producers)
    rows.append(end_row(rows))
    main = dict.fromkeys(('site n pid tid base controller caller_raw caller_app raw_u32 raw_known numeric_route_match '
                         'vptr field300 field302 field303 current17c model_m model_k open_rc open_errno reads read_errno '
                         'close_rc close_errno quota observation_only atomic_snapshot phase original_branch_observed '
                         'original_store_observed original_return_observed event_id_unverified producer_unknown capture_verified').split(), '0')
    power = next(row for row in rows if row['kind'] == 'poweron_context')
    main.update(site='dispatch', n='1', pid='259', tid='345', base=h64(BASE), controller=power['controller'],
                caller_raw=power['caller_raw'], caller_app='0x1e79354', raw_u32='0x01000090', raw_known='1',
                numeric_route_match='1', observation_only='1', phase='entry', event_id_unverified='1', producer_unknown='1',
                quota='poweron_entry16', open_rc='7', reads='8/2/1/1/4/4/4', read_errno='0/0/0/0/0/0/0')
    console = ('HOST_TEST synthetic console\nOBS SHUTTER_DETAIL_POWERON ' +
               ' '.join(key + '=' + value for key, value in main.items()) + '\r\n').encode('ascii')
    schema = json.loads((HERE.parent / 'log-schema-v2.json').read_bytes())
    return rows, console, schema


def write_run(directory, checker):
    """Write only a caller-owned HOST_TEST tempdir; these are deliberately fake assets."""
    directory = Path(directory).resolve()
    run = directory / 'HOST_TEST-run'
    run.mkdir()
    rows, console, _ = joined_case()
    trace = encode(rows)
    library = b'HOST_TEST fake library, never loaded or built\n'
    digest = lambda raw: hashlib.sha256(raw).hexdigest()
    closure = {name: digest((checker.HERE / name).read_bytes()) for name in checker.BUILD_SOURCES}
    expected = {'schema_sha256': closure['log-schema-v2.json'], 'qemu_sha256': digest(b'HOST_TEST QEMU'),
                'library_sha256': digest(library), 'qemu_header_sha256': digest(b'HOST_TEST header'),
                'source_sha256': closure,
                'observer_sha256': digest(b'HOST_TEST Main library'), 'Main_source_sha256': digest(b'HOST_TEST Main source'),
                'original_appfw_sha256': digest(b'HOST_TEST appFw identity only'),
                'readonly_import_audit_sha256': digest(b'HOST_TEST import audit')}
    receipt = {key: copy.deepcopy(expected[key]) for key in checker.ASSET_FIELDS}
    receipt.update(schema=checker.PROFILE, trace_schema=checker.SCHEMA,
                   trace_schema_sha256=expected['schema_sha256'], source_contract_sha256=closure['source-contract-v2.json'],
                   plugin_api=7, readonly_imports_verified=True,
                   readonly_import_audit_sha256=expected['readonly_import_audit_sha256'],
                   runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
    receipt_path = directory / 'HOST_TEST-build-receipt.json'
    receipt_raw = (json.dumps(receipt, indent=2) + '\n').encode()
    receipt_path.write_bytes(receipt_raw)
    expected['build_receipt_sha256'] = digest(receipt_raw)
    profile = dict(receipt, profile=checker.PROFILE, identity_binding='unverified', build_receipt=str(receipt_path),
                   build_receipt_sha256=expected['build_receipt_sha256'], library=str(run / 'readonly-scope-observer.so'),
                   log=str(run / 'readonly-scope-trace.log'))
    manifest = {'readonly_scope_observer': profile,
                'compiled_observer': {'observer_sha256': expected['observer_sha256'],
                                      'sources': {'HOST_TEST/menu-observe.c': {'sha256': expected['Main_source_sha256']}}},
                'files': {'HOST_TEST/appFw.so': expected['original_appfw_sha256']}}
    exit_record = {'profile': checker.PROFILE, 'run': str(run), 'owned_wrapper_pid': 123,
                   'returncode': 0, 'log_available': True, 'log_sha256': digest(trace), 'library_sha256': digest(library),
                   'capture_verified': False, 'physical_asic_compatibility_verified': False}
    for name, raw in (('console.log', console), ('readonly-scope-trace.log', trace), ('readonly-scope-observer.so', library),
                      ('runtime-manifest.json', json.dumps(manifest).encode()),
                      ('readonly-scope-exit.json', json.dumps(exit_record).encode())):
        (run / name).write_bytes(raw)
    return run, expected
