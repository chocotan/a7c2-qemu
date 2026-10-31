"""Correlate read-only host observations with the same run's original Main record.

Correlation is not PID/ASID uniqueness, instruction retirement or media acceptance.
"""
from pathlib import Path
import hashlib
import json
import re
import runpy

HERE = Path(__file__).resolve().parent
FORMAT = runpy.run_path(str(HERE / 'integration/scope_trace_checks.py'))
number = FORMAT['number']
require = FORMAT['require']
TOKENS = FORMAT['TOKENS']
MAIN_KEYS = set(('site n pid tid base controller caller_raw caller_app raw_u32 raw_known numeric_route_match '
                 'vptr field300 field302 field303 current17c model_m model_k open_rc open_errno reads read_errno '
                 'close_rc close_errno quota observation_only atomic_snapshot phase original_branch_observed '
                 'original_store_observed original_return_observed event_id_unverified producer_unknown capture_verified').split())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main_dispatches(console):
    result = []
    prefix = b'OBS SHUTTER_DETAIL_POWERON '
    for line_number, raw in enumerate(console.split(b'\n'), 1):
        raw = raw.removesuffix(b'\r')
        if not raw.startswith(prefix):
            continue
        row = {}
        for field in raw[len(prefix):].decode('ascii').split(' '):
            require(field.count('=') == 1, 'malformed original Main record')
            key, value = field.split('=')
            require(key not in row and value, 'duplicate original Main field')
            row[key] = value
        require(set(row) == MAIN_KEYS, 'original Main fields differ from formatter')
        if row['site'] != 'dispatch':
            continue
        flags = {'raw_known': '1', 'numeric_route_match': '1', 'observation_only': '1',
                 'atomic_snapshot': '0', 'phase': 'entry', 'original_branch_observed': '0',
                 'original_store_observed': '0', 'original_return_observed': '0',
                 'capture_verified': '0', 'event_id_unverified': '1', 'producer_unknown': '1',
                 'quota': 'poweron_entry16', 'open_errno': '0',
                 'close_rc': '0', 'close_errno': '0', 'reads': '8/2/1/1/4/4/4',
                 'read_errno': '0/0/0/0/0/0/0'}
        require(all(row.get(k) == v for k, v in flags.items()), 'original Main record is incomplete')
        for name in ('n', 'pid', 'tid', 'open_rc'):
            require(re.fullmatch(r'0|[1-9][0-9]*', row[name]) is not None, 'noncanonical Main integer')
        require(1 <= int(row['n']) <= 16 and int(row['pid']) > 0 and int(row['tid']) > 0, 'Main quota or owner invalid')
        for name in ('base', 'controller', 'caller_raw', 'caller_app', 'raw_u32'):
            number(row, name)
        require(number(row, 'caller_raw') - number(row, 'base') == number(row, 'caller_app'), 'Main caller offset differs')
        row['raw_LF_line'] = line_number
        result.append(row)
    require(result, 'TRACE_MISSING original Main dispatch')
    return result


def token_context(row):
    values = []
    for token in TOKENS:
        available = number(row, token + '_available')
        require(available in (0, 1), 'invalid token availability')
        require(number(row, token + '_read_length') == (8 if available else 0), 'invalid token width')
        if not available:
            require(row.get(token + '_raw') == 'unknown', 'invented absent context token')
            return None
        value = row.get(token + '_raw', '')
        require(re.fullmatch(r'0x[0-9a-f]{16}', value) is not None, 'invalid raw context token')
        values.append(number(row, token + '_raw'))
    return (number(row, 'candidate_base'), *values)


def validate_late(rows, end):
    sites = {'M_cmp_pre': 0x209ee58, 'M_bne_pre': 0x209ee5c, 'request0_bl_pre': 0x209ee9c}
    counts = dict.fromkeys(sites, 0)
    selected = [row for row in rows if row['kind'] == 'late']
    for sequence, row in enumerate(selected, 1):
        site = row.get('site')
        require(site in sites and number(row, 'vcpu') == 0, 'unknown late site or vCPU')
        counts[site] += 1
        require(number(row, 'ordinal') == counts[site] <= 16 and number(row, 'late_sequence') == sequence, 'late quota/sequence differs')
        base = number(row, 'candidate_base')
        require(base == number(end, 'candidate_base') and number(row, 'event_pc') == base + sites[site], 'late eventPC differs')
        require(row.get('callback_phase') == 'before_instruction' and number(row, 'anchor_length') == 12, 'late phase/anchor differs')
        for reg in ('gdb_pc', 'x0', 'x19', 'x23', 'x30', 'cpsr'):
            require(number(row, reg + '_read_length') == (4 if reg == 'cpsr' else 8) and
                    number(row, reg + '_api_ok') == 1, 'late register read differs')
        require(number(row, 'api_ok') == 1, 'late API failure')
        for field in ('event_pc', 'gdb_pc_raw', 'candidate_base', 'x0', 'x19', 'x23', 'x30'):
            require(re.fullmatch(r'0x[0-9a-f]{16}', row.get(field, '')) is not None, 'late raw value truncated')
        cpsr = number(row, 'cpsr_raw')
        require(cpsr <= 0xffffffff and not cpsr & 0x10 and number(row, 'cpsr_m') == cpsr & 0x1f, 'late mode differs')
        require(number(row, 'nzcv_mask') == 0xf0000000 and number(row, 'nzcv') == cpsr & 0xf0000000, 'late NZCV differs')
        for field in ('sp', *TOKENS):
            available = number(row, field + '_available')
            require(available in (0, 1) and number(row, field + '_read_length') == (8 if available else 0), 'late optional width')
            if available:
                require(number(row, field + '_api_ok') == 1 and re.fullmatch(r'0x[0-9a-f]{16}', row.get(field + '_raw', '')) is not None, 'late optional read')
            else:
                require(row.get(field + '_raw') == row.get(field + '_api_ok') == 'unknown', 'invented late optional value')
        if site == 'request0_bl_pre':
            require(row.get('lr_phase') == 'before_bl' and number(row, 'x1_read_length') == 8 and
                    number(row, 'x1_api_ok') == 1 and number(row, 'w1') == number(row, 'x1') & 0xffffffff, 'late BL raw argument differs')
        else:
            require(number(row, 'loaded_M_u32') == number(row, 'x0') & 0xffffffff, 'loaded M was normalized')
            if site == 'M_cmp_pre':
                require(row.get('flags_phase') == 'before_cmp', 'CMP phase differs')
            else:
                z = (cpsr >> 30) & 1
                require(row.get('flags_phase') == 'after_cmp_before_bne' and number(row, 'z') == z and
                        row.get('source_next_basis') == 'cpsr_Z' and number(row, 'source_next_pc') == base +
                        (0x209ee60 if z else 0x209ee80), 'BNE source prediction differs')
    require(number(end, 'late_sequence') == len(selected) and all(number(end, 'late%d_records' % i) == counts[site]
            for i, site in enumerate(sites)), 'late end counters differ')


def correlate(console, trace, schema):
    require(b'scope_observer_host_error' not in console, 'observer reported a host I/O or close failure')
    rows = FORMAT['rows_from'](trace)
    common = set(schema['common_fields_every_line'])
    for row in rows:
        fields = schema['late_site_kinds'].get(row.get('site'), {}) if row['kind'] == 'late' else schema['kinds'].get(row['kind'], {})
        require(fields and set(row) == common | set(fields), 'trace schema keys differ')
    end = rows[-1]
    require(end.get('stop') == 'none' and end.get('close_result') == 'unknown', 'trace stopped or falsely attested close')
    for name in ('ambiguous', 'conflicting_base', 'faults', 'fault_lines', 'suppressed_faults'):
        require(number(end, name) == 0, 'fault invalidates trace')
    require(number(end, 'candidate_found') == 1, 'TRACE_MISSING scope code anchor')
    candidates = [row for row in rows if row['kind'] == 'candidate']
    require(len(candidates) == 1 and number(candidates[0], 'candidate_base') == number(end, 'candidate_base'), 'scope anchor count/base differs')
    scope_counts = [0, 0]
    for row in rows:
        if row['kind'] != 'entry':
            continue
        slot = number(row, 'lr_slot')
        require(slot in (0, 1) and number(row, 'vcpu') == 0, 'invalid scope lane/vCPU')
        scope_counts[slot] += 1
        require(number(row, 'ordinal') == scope_counts[slot] <= 16, 'scope quota/order differs')
        base = number(row, 'candidate_base')
        require(base == number(end, 'candidate_base') and number(row, 'actual_pc') == number(row, 'translated_entry_pc') == base + 0x2e068cc, 'scope PC differs')
        require(number(row, 'lr') == number(row, 'x30') == base + (0x209ee80, 0x209ee88)[slot], 'scope LR differs')
        for reg in ('actual_pc', 'translated_entry_pc', 'candidate_base', 'lr', *FORMAT['GPRS']):
            require(re.fullmatch(r'0x[0-9a-f]{16}', row.get(reg, '')) is not None, 'scope raw register was truncated')
        for reg in ('pc', 'lr', *FORMAT['GPRS']):
            require(number(row, reg + '_read_length') == 8, 'scope read width differs')
        require(number(row, 'cpsr_read_length') == 4 and number(row, 'api_ok') == 1, 'scope flags read differs')
        cpsr = number(row, 'cpsr_raw')
        require(cpsr <= 0xffffffff and not cpsr & 0x10 and number(row, 'cpsr_m') == cpsr & 0x1f, 'scope mode differs')
        require(number(row, 'nzcv_mask') == 0xf0000000 and number(row, 'nzcv') == cpsr & 0xf0000000, 'scope NZCV differs')
    require(all(number(end, 'lr%d_records' % slot) == scope_counts[slot] for slot in (0, 1)), 'scope end counters differ')
    validate_late(rows, end)
    mains = main_dispatches(console)
    powers = [(i, row) for i, row in enumerate(rows) if row['kind'] == 'poweron_context']
    require(len(powers) == number(end, 'poweron_records') <= 16, 'poweron counter differs')
    contexts = {}
    joins = []
    for ordinal, (index, row) in enumerate(powers, 1):
        require(number(row, 'ordinal') == ordinal and number(row, 'vcpu') == 0, 'poweron quota/order differs')
        require(row.get('context_mode') == 'EL0t' and number(row, 'cpsr_m') == 0 and number(row, 'cpsr_raw') & 0x1f == 0, 'poweron is not user EL0t')
        require(number(row, 'api_ok') == 1 and number(row, 'anchor_length') == 8, 'poweron read or anchor failure')
        for reg in ('pc', 'x0', 'x2', 'x30'):
            require(number(row, reg + '_read_length') == 8, 'poweron register width differs')
        require(number(row, 'cpsr_read_length') == 4, 'poweron flags width differs')
        base = number(row, 'candidate_base')
        require(number(row, 'actual_pc') == number(row, 'translated_entry_pc') == base + 0x1951844, 'poweron PC differs')
        require(number(row, 'raw_x2') & 0xffffffff == number(row, 'raw_u32') and number(row, 'raw_u32') & 0xff000fff == 0x01000090, 'poweron original argument differs')
        matched = [m for m in mains if all(number(m, a) == number(row, b) for a, b in
                   (('base', 'candidate_base'), ('controller', 'controller'), ('caller_raw', 'caller_raw'), ('raw_u32', 'raw_u32')))]
        if not matched:
            continue
        require(len(matched) == 1, 'ambiguous original Main correlation')
        context = token_context(row)
        if context is None:
            continue
        contexts.setdefault(context, []).append(index)
        joins.append({'poweron_trace_index': index, 'Main_raw_LF_line': matched[0]['raw_LF_line'],
                      'Main_reported_pid': int(matched[0]['pid']), 'Main_reported_tid': int(matched[0]['tid'])})
    require(joins, 'TRACE_MISSING poweron/Main raw-context correlation')
    correlated = []
    uncorrelated = []
    for index, row in enumerate(rows):
        if row['kind'] not in ('entry', 'late'):
            continue
        context = token_context(row)
        if (context not in contexts or row.get('context_mode') != 'EL0t' or number(row, 'cpsr_m') != 0 or
                number(row, 'cpsr_raw') & 0x1f != 0 or not any(i < index for i in contexts[context])):
            uncorrelated.append(index)
            continue
        correlated.append({'trace_index': index, 'kind': row['kind'], 'raw_fields': row.copy()})
    require(correlated, 'TRACE_MISSING later context-correlated observation')
    return {'context_correlated': True, 'poweron_Main_joins': joins, 'observations': correlated,
            'uncorrelated_observation_indices': uncorrelated, 'PID_TID_uniqueness_verified': False,
            'address_space_uniqueness_verified': False, 'instruction_retirement_verified': False,
            'original_store_or_return_verified': False, 'capture_verified': False,
            'physical_asic_compatibility_verified': False}


def check_run(run, expected):
    """Expected hashes come from this run's frozen parent runtime-ready evidence."""
    run = Path(run).resolve()
    paths = {name: run / name for name in ('console.log', 'runtime-manifest.json', 'readonly-scope-trace.log',
                                          'readonly-scope-observer.so', 'readonly-scope-exit.json')}
    for name, path in paths.items():
        require(path.is_file() and not path.is_symlink(), 'missing ordinary run artifact ' + name)
    schema_raw = (HERE / 'log-schema.json').read_bytes()
    require(sha(schema_raw) == expected['schema_sha256'], 'unreviewed schema')
    original = {name: (path.stat().st_size, path.stat().st_mtime_ns, sha(path.read_bytes())) for name, path in paths.items()}
    manifest = json.loads(paths['runtime-manifest.json'].read_bytes())
    profile = manifest['readonly_scope_observer']
    require(profile['profile'] == 'qemu-readonly-scope-v1' and profile['identity_binding'] == 'unverified', 'profile mismatch')
    for field in ('qemu_sha256', 'library_sha256', 'qemu_header_sha256', 'source_sha256'):
        require(profile[field] == expected[field], 'runtime asset differs: ' + field)
    require(Path(profile['library']) == paths['readonly-scope-observer.so'] and Path(profile['log']) == paths['readonly-scope-trace.log'], 'trace belongs to another run')
    require(original['readonly-scope-observer.so'][2] == expected['library_sha256'], 'staged plugin changed')
    require(manifest['compiled_observer']['observer_sha256'] == expected['observer_sha256'], 'Main observer differs')
    sources = manifest['compiled_observer']['sources']
    main = [row['sha256'] for name, row in sources.items() if Path(name).name == 'menu-observe.c']
    require(main == [expected['Main_source_sha256']], 'Main source is not the frozen observer')
    appfw = [digest for name, digest in manifest['files'].items() if Path(name).name == 'appFw.so']
    require(appfw == [expected['original_appfw_sha256']], 'original appFw asset differs')
    exit_record = json.loads(paths['readonly-scope-exit.json'].read_bytes())
    require(exit_record['profile'] == profile['profile'] and exit_record['run'] == str(run) and
            type(exit_record['owned_wrapper_pid']) is int and exit_record['owned_wrapper_pid'] > 0 and
            type(exit_record['returncode']) is int and exit_record['returncode'] == 0 and
            exit_record['log_available'] is True and exit_record['log_sha256'] == original['readonly-scope-trace.log'][2] and
            exit_record['library_sha256'] == expected['library_sha256'], 'missing normal owned exit or log readback')
    result = correlate(paths['console.log'].read_bytes(), paths['readonly-scope-trace.log'].read_bytes(), json.loads(schema_raw))
    require(all((path.stat().st_size, path.stat().st_mtime_ns, sha(path.read_bytes())) == original[name]
                for name, path in paths.items()), 'run inputs changed during read-only check')
    result.update(run=str(run), artifact_signatures=original, original_artifacts_unchanged=True)
    return result
