"""Strict generation-2 raw reader. Legacy readers and original rows stay unchanged."""
from pathlib import Path
import hashlib
import json
import re
import runpy

LEGACY = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'check_run_context.py'))
V1 = LEGACY['FORMAT']
COMMON, GPRS, TOKENS = V1['COMMON'], V1['GPRS'], V1['TOKENS']
number, require = V1['number'], V1['require']
SCHEMA = 'readonly_scope_v2'
PROFILE = 'qemu-readonly-scope-v2'
V1_SCHEMA_SHA256 = '8b6e2bf3576e7e4e5566fa215d2758e088ae8867ed6b3c36ea7b90f38767e50c'
LOW48_MAX = (1 << 48) - 1
U64_MAX = (1 << 64) - 1
MAX_LINES = 163
MAX_LINE_BYTES = 2048
PRODUCER_SITES = {'entry': 0x276e710, 'pre_M_store': 0x276e71c}
BEGIN = {'schema': SCHEMA, 'plugin_api': '0x7', 'max_vcpus': '0x1',
         'lr_quota': '0x10', 'fault_quota': '0x20', 'anchor_length': '0x18',
         'register_byte_order': 'little',
         'identity_limit': 'raw_context_only_no_pid_tid_module_identity',
         'poweron_quota': '0x10', 'poweron_anchor_length': '0x8',
         'producer_sites': '0x2', 'producer_quota': '0x10', 'producer_anchor_length': '0x18'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fields_from_line(line):
    require(line.startswith(b'kind=') and len(line) < MAX_LINE_BYTES, 'v2 prefix or line size differs')
    row = {}
    for token in line.decode('ascii').split(' '):
        require(token.count('=') == 1, 'invalid v2 token')
        key, value = token.split('=')
        require(re.fullmatch(r'[A-Za-z0-9_]+', key) is not None and value and key not in row,
                'invalid or duplicate v2 key')
        row[key] = value
    require(' '.join(key + '=' + value for key, value in row.items()).encode('ascii') == line,
            'noncanonical v2 line')
    return row


def raw_records(raw):
    """Offsets and hashes cover original bytes including each actual LF, if present."""
    records, offset = [], 0
    pieces = raw.split(b'\n')
    lines = [piece + b'\n' for piece in pieces[:-1]]
    if pieces[-1]:
        lines.append(pieces[-1])
    for index, line in enumerate(lines):
        record = {'trace_index': index, 'line_number': index + 1,
                  'byte_offset': offset, 'byte_length': len(line),
                  'sha256': sha(line), 'raw_hex': line.hex(),
                  'raw_ascii': None, 'canonical_fields': None, 'canonical': False}
        try:
            record['raw_ascii'] = line.decode('ascii')
            row = fields_from_line(line.removesuffix(b'\n'))
            record.update(canonical_fields=list(row.items()), canonical=True)
        except (ValueError, UnicodeError) as error:
            record['canonical_error'] = str(error)
        records.append(record)
        offset += len(line)
    return records


class RejectedTrace(ValueError):
    """A refusal carries the original evidence; it never repairs or writes a log."""
    def __init__(self, message, raw):
        super().__init__(message)
        self.evidence = {'trace_sha256': sha(raw), 'raw_hex': raw.hex(),
                         'byte_length': len(raw), 'raw_records': raw_records(raw),
                         'group_claim_rejected': True}


def rows_from(raw):
    """Envelope only; parse_trace additionally checks exact keys and all content."""
    require(isinstance(raw, bytes) and raw.endswith(b'\n') and b'\r' not in raw and
            len(raw) <= MAX_LINES * MAX_LINE_BYTES, 'truncated or oversized v2 log')
    lines = raw[:-1].split(b'\n')
    require(2 <= len(lines) <= MAX_LINES, 'v2 line count differs')
    rows = []
    for line in lines:
        row = fields_from_line(line)
        require(all(row.get(key) == value for key, value in COMMON.items()), 'promoted raw identity or success')
        rows.append(row)
    require(rows[0]['kind'] == 'begin' and rows[-1]['kind'] == 'end', 'missing v2 begin/end')
    require(all(row['kind'] in ('candidate', 'entry', 'poweron_context', 'late', 'M_producer', 'fault')
                for row in rows[1:-1]), 'unknown or misplaced v2 record')
    return rows


def fixed(row, name, digits):
    require(re.fullmatch(r'0x[0-9a-f]{%d}' % digits, row.get(name, '')) is not None,
            'non-exact raw width ' + name)
    return number(row, name)


def count(row, name):
    require(re.fullmatch(r'0x(?:0|[1-9a-f][0-9a-f]*)', row.get(name, '')) is not None,
            'noncanonical count ' + name)
    return number(row, name)


def checked_add(value, offset, span=1):
    require(0 <= value <= U64_MAX - offset and span > 0, 'destination/address uint64 overflow')
    result = value + offset
    require(result <= LOW48_MAX - (span - 1), 'destination/address outside untagged low48')
    return result


def base_value(row, name='candidate_base', allow_zero=False):
    base = fixed(row, name, 16)
    require((allow_zero and base == 0) or (0 < base <= LOW48_MAX and base & 0xfff == 0),
            'invalid unbound base ' + name)
    return base


def mode_fields(row):
    cpsr = fixed(row, 'cpsr_raw', 8)
    mode = fixed(row, 'cpsr_m', 2)
    require(not cpsr & 0x10 and mode == cpsr & 0x1f and mode in (0, 4, 5, 8, 9, 12, 13),
            'AArch32, reserved or inconsistent mode')
    require(row['context_mode'] == ('EL0t' if mode == 0 else 'other_aarch64'), 'raw mode was normalized')
    require(row['nzcv_mask'] == '0xf0000000' and fixed(row, 'nzcv', 8) == cpsr & 0xf0000000,
            'raw NZCV differs')
    return mode


def read_fields(row, names, individual_ok=False):
    require(row['api_ok'] == '0x1', 'register API did not return bool true')
    for name in names:
        require(row[name + '_read_length'] == ('0x4' if name == 'cpsr' else '0x8'),
                'non-exact register read ' + name)
        if individual_ok:
            require(row[name + '_api_ok'] == '0x1', 'register API bool failure ' + name)


def optional(row, name, individual_ok=True):
    available = row[name + '_available']
    require(available in ('0x0', '0x1'), 'invalid optional availability ' + name)
    present = available == '0x1'
    require(row[name + '_read_length'] == ('0x8' if present else '0x0'), 'optional exact8 failure ' + name)
    if individual_ok:
        require(row[name + '_api_ok'] == ('0x1' if present else 'unknown'), 'optional bool failure ' + name)
    if present:
        return fixed(row, name + '_raw', 16)
    require(row[name + '_raw'] == 'unknown', 'invented absent optional value ' + name)
    return None


def context_key(row):
    """Numerical context only. Missing tokens never compare equal to missing tokens."""
    values = [optional(row, token, row['kind'] != 'entry') for token in TOKENS]
    if any(value is None for value in values) or mode_fields(row) != 0 or count(row, 'vcpu') != 0:
        return None
    return (number(row, 'candidate_base'), 0, 0, *values)


def validate_rows(rows, schema):
    require(schema.get('schema') == SCHEMA and schema.get('profile') == PROFILE and
            schema.get('inherited_v1_schema_sha256') == V1_SCHEMA_SHA256 and
            schema['file_contract']['maximum_file_lines'] == MAX_LINES and
            schema['file_contract']['maximum_line_bytes_exclusive'] == MAX_LINE_BYTES,
            'unknown or mismatched v2 schema/profile')
    common = set(COMMON) | {'kind'}
    for row in rows:
        kind = row['kind']
        require(kind != 'fault', 'fault invalidates whole evidence group')
        if kind == 'late':
            fields = schema['late_site_kinds'].get(row.get('site'))
        elif kind == 'M_producer':
            fields = schema['producer_site_kinds'].get(row.get('site'))
        else:
            fields = schema['kinds'].get(kind)
        require(fields and set(row) == common | set(fields), 'unknown/missing v2 kind/site/exact keys')
    require(all(rows[0].get(key) == value for key, value in BEGIN.items()), 'v2 begin contract differs')
    end = rows[-1]
    require(end['stop'] == 'none' and end['close_result'] == 'unknown', 'stopped or falsely attested close')
    for name in ('ambiguous', 'fault_lines'):
        require(count(end, name) == 0, 'fault or ambiguity invalidates group')
    for name in ('conflicting_base', 'producer_conflicting_base', 'faults', 'suppressed_faults'):
        require(fixed(end, name, 16) == 0, 'conflicting base/fault invalidates group')
    fixed(end, 'other_lr', 16)
    scope_found, producer_found = count(end, 'candidate_found'), count(end, 'producer_anchor_found')
    require(scope_found in (0, 1) and producer_found in (0, 1), 'invalid anchor-found flag')
    scope_base = base_value(end, allow_zero=not scope_found)
    producer_base = base_value(end, 'producer_base', allow_zero=not producer_found)
    require(bool(scope_base) == bool(scope_found) and bool(producer_base) == bool(producer_found), 'invented anchor base')
    if producer_found:
        checked_add(producer_base, 0x276e710, 24)
        checked_add(producer_base, 0x7e6a7d0, 4)
    require(not (scope_found and producer_found) or scope_base == producer_base, 'producer/scope base conflict')
    counts = {'entry': [0, 0], 'poweron_context': 0, 'M_producer': dict.fromkeys(PRODUCER_SITES, 0)}
    candidate_count = producer_sequence = 0
    for row in rows[1:-1]:
        kind = row['kind']
        base = base_value(row)
        if kind == 'candidate':
            candidate_count += 1
            require(candidate_count == 1 and scope_found and base == scope_base and row['anchor_length'] == '0x18' and
                    fixed(row, 'translated_entry_pc', 16) == checked_add(base, 0x2e068cc, 24), 'scope anchor differs')
            continue
        require(count(row, 'vcpu') == 0, 'nonzero vCPU invalidates group')
        mode = mode_fields(row)
        if kind in ('entry', 'late'):
            require(candidate_count == 1 and base == scope_base, 'scope/late lacks earlier same-base scope anchor')
        if kind == 'entry':
            slot = count(row, 'lr_slot')
            require(slot in (0, 1), 'invalid scope lane')
            counts[kind][slot] += 1
            require(count(row, 'ordinal') == counts[kind][slot] <= 16, 'scope ordinal/quota differs')
            require(fixed(row, 'actual_pc', 16) == fixed(row, 'translated_entry_pc', 16) == checked_add(base, 0x2e068cc, 24),
                    'scope raw/translation PC differs')
            require(fixed(row, 'lr', 16) == fixed(row, 'x30', 16) == checked_add(base, (0x209ee80, 0x209ee88)[slot]),
                    'scope LR differs')
            for name in GPRS:
                fixed(row, name, 16)
            read_fields(row, ('pc', 'lr', *GPRS, 'cpsr'))
            require(row['sp_read_length'] in ('0x0', '0x8'), 'scope optional SP width')
            if row['sp_read_length'] == '0x8':
                fixed(row, 'sp', 16)
            else:
                require(row['sp'] == 'unknown', 'invented absent SP')
            for token in TOKENS:
                optional(row, token, False)
        elif kind == 'poweron_context':
            counts[kind] += 1
            require(count(row, 'ordinal') == counts[kind] <= 16 and row['site'] == 'dispatch' and mode == 0,
                    'poweron quota/site/EL0t differs')
            require(row['anchor_length'] == '0x8' and fixed(row, 'actual_pc', 16) ==
                    fixed(row, 'translated_entry_pc', 16) == checked_add(base, 0x1951844, 8), 'poweron PC/anchor differs')
            read_fields(row, ('pc', 'x0', 'x2', 'x30', 'cpsr'))
            fixed(row, 'controller', 16)
            fixed(row, 'caller_raw', 16)
            raw = fixed(row, 'raw_x2', 16)
            require(fixed(row, 'raw_u32', 8) == raw & 0xffffffff and raw & 0xff000fff == 0x01000090,
                    'poweron raw argument differs')
            for token in TOKENS:
                optional(row, token)
        elif kind == 'late':
            for field in ('event_pc', 'gdb_pc_raw', 'x0', 'x19', 'x23', 'x30'):
                fixed(row, field, 16)
            read_fields(row, ('gdb_pc', 'x0', 'x19', 'x23', 'x30', 'cpsr'), True)
            for field in ('sp', *TOKENS):
                optional(row, field)
            if row['site'] == 'request0_bl_pre':
                fixed(row, 'x1', 16)
                fixed(row, 'w1', 8)
            else:
                fixed(row, 'loaded_M_u32', 8)
                if row['site'] == 'M_bne_pre':
                    fixed(row, 'source_next_pc', 16)
        elif kind == 'M_producer':
            site = row['site']
            counts[kind][site] += 1
            producer_sequence += 1
            require(producer_found and base == producer_base, 'second or inconsistent producer base')
            require(count(row, 'ordinal') == counts[kind][site] <= 16 and
                    count(row, 'producer_sequence') == producer_sequence, 'producer ordinal/quota/sequence differs')
            require(row['scope_anchor_seen'] == ('0x1' if candidate_count else '0x0'), 'rewritten scope-anchor history')
            require(row['callback_phase'] == 'before_instruction' and row['anchor_length'] == '0x18' and
                    row['input_kind'] == 'u32_value', 'producer phase/anchor/input kind differs')
            require(fixed(row, 'event_pc', 16) == checked_add(base, PRODUCER_SITES[site]), 'producer immutable eventPC differs')
            fixed(row, 'gdb_pc_raw', 16)
            x0, x30 = fixed(row, 'x0_raw', 16), fixed(row, 'x30_raw', 16)
            require(fixed(row, 'caller_raw', 16) == x30 and fixed(row, 'raw_input_u32', 8) == x0 & 0xffffffff,
                    'producer full64 caller or raw input differs')
            read_fields(row, ('gdb_pc', 'x0', 'x30', 'cpsr'), True)
            for field in ('sp', *TOKENS):
                optional(row, field)
            if site == 'entry':
                require(row['proposed_u32'] == 'unknown', 'entry cannot claim a proposed store')
            else:
                read_fields(row, ('x1',), True)
                destination = checked_add(fixed(row, 'x1_raw', 16), 0x2f0, 4)
                require(destination == checked_add(base, 0x7e6a7c8, 4) == fixed(row, 'effective_destination_raw', 16) and
                        fixed(row, 'x1_raw', 16) == checked_add(base, 0x7e6a4d8) and row['destination_match'] == '0x1',
                        'producer pre-store destination differs')
                require(fixed(row, 'proposed_u32', 8) == x0 & 0xffffffff, 'producer proposed operand differs')
    require(candidate_count == scope_found, 'scope candidate counter differs')
    for slot in (0, 1):
        require(count(end, 'lr%d_records' % slot) == counts['entry'][slot], 'scope end counter differs')
    require(count(end, 'poweron_records') == counts['poweron_context'], 'poweron end counter differs')
    for slot, site in enumerate(PRODUCER_SITES):
        require(count(end, 'producer%d_records' % slot) == counts['M_producer'][site], 'producer end counter differs')
    require(count(end, 'producer_sequence') == producer_sequence, 'producer end sequence differs')
    for name in ('late0_records', 'late1_records', 'late2_records', 'late_sequence'):
        count(end, name)
    # Reuse the unchanged late-site phase/operand/order checker on the actual rows.
    LEGACY['validate_late'](rows, end)


def parse_trace(raw, schema):
    try:
        rows = rows_from(raw)
        validate_rows(rows, schema)
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise RejectedTrace(str(error), raw) from error
    return {'rows': rows, 'raw_records': raw_records(raw), 'trace_sha256': sha(raw), 'byte_length': len(raw)}


def assert_scope_trace_v2(raw_log, expected_entries, candidate_base, other_lr, *, expected_producers, producer_base):
    """Compare strict v2 bytes with self-owned guest dump values; no Sony identity claim."""
    try:
        root = Path(__file__).resolve().parents[1]
        schema_raw = (root / 'log-schema-v2.json').read_bytes()
        contract = json.loads((root / 'source-contract-v2.json').read_bytes())
        require(sha(schema_raw) != V1_SCHEMA_SHA256 and
                contract['schema'] == 'readonly_scope_source_contract_v2' and
                contract['profile'] == PROFILE and contract['trace_schema'] == SCHEMA and
                contract['v2_schema_sha256'] == sha(schema_raw), 'fixture v2 schema/source-contract pin differs')
        parsed = parse_trace(raw_log, json.loads(schema_raw))
        rows, end = parsed['rows'], parsed['rows'][-1]
        require(number(end, 'candidate_found') == int(candidate_base is not None) and
                number(end, 'candidate_base') == (0 if candidate_base is None else candidate_base) and
                number(end, 'other_lr') == other_lr, 'fixture scope base/otherLR differs')
        require(number(end, 'producer_anchor_found') == int(producer_base is not None) and
                number(end, 'producer_base') == (0 if producer_base is None else producer_base),
                'fixture producer anchor/base differs')
        require(not any(row['kind'] in ('poweron_context', 'late') for row in rows),
                'unexpected fixture poweron/late observations')
        scope_required = set(GPRS) | {'actual_pc', 'translated_entry_pc', 'candidate_base', 'lr', 'sp', 'nzcv', 'cpsr_m'}
        producer_required = {'vcpu', 'producer_sequence', 'event_pc', 'candidate_base', 'scope_anchor_seen',
                             'x0_raw', 'raw_input_u32', 'proposed_u32', 'x30_raw', 'caller_raw',
                             'cpsr_raw', 'cpsr_m', 'context_mode', 'nzcv', 'nzcv_mask'}
        for kind, expected, required in (('entry', expected_entries, scope_required),
                                         ('M_producer', expected_producers, producer_required)):
            require(isinstance(expected, dict), 'fixture expectations must be explicit maps')
            selected = [row for row in rows if row['kind'] == kind]
            require(len(selected) == len(expected), 'fixture ' + kind + ' count differs')
            seen = set()
            for row in selected:
                key = (number(row, 'lr_slot') if kind == 'entry' else row['site'], number(row, 'ordinal'))
                require(key in expected and key not in seen, 'unexpected or duplicate fixture ' + kind)
                seen.add(key)
                wanted = expected[key]
                mandatory = required | ({'x1_raw', 'effective_destination_raw', 'destination_match'}
                                        if kind == 'M_producer' and row['site'] == 'pre_M_store' else set())
                require(isinstance(wanted, dict) and mandatory <= wanted.keys(),
                        'incomplete fixture operand/register expectations')
                for name, value in wanted.items():
                    if name == 'optional_raw':
                        require(isinstance(value, dict) and set(value) <= {'sp', *TOKENS},
                                'unknown fixture optional register')
                        for field, expected_value in value.items():
                            require(type(expected_value) is int and 0 <= expected_value <= U64_MAX,
                                    'invalid expected optional raw value')
                            if kind == 'entry' and field == 'sp':
                                actual = number(row, 'sp') if row['sp_read_length'] == '0x8' else None
                            else:
                                actual = optional(row, field, kind != 'entry')
                            if actual is not None:
                                require(actual == expected_value, 'fixture optional operand differs: ' + field)
                        continue
                    require(name in row and (type(value) is int or type(value) is str),
                            'unknown fixture expected field/type: ' + name)
                    actual = number(row, name) if type(value) is int else row[name]
                    require(actual == value, 'fixture ' + kind + ' operand/register differs: ' + name)
            require(seen == set(expected), 'missing fixture ' + kind + ' expectation')
        parsed.update(synthetic_scope_observer_verified=True,
                      synthetic_M_producer_observer_verified=bool(expected_producers),
                      entries=len(expected_entries), producer_records=len(expected_producers),
                      producer_observation_status='observed_raw' if expected_producers else 'unknown',
                      normal_M_producer_call='unknown', entry_pre_store_invocation_pairing='unknown',
                      original_Main_identity_verified=False, instruction_retirement_verified=False,
                      original_store_or_return_verified=False, cap=False, capture=False, physical=False,
                      branchretirement=False, storecompletion=False, capture_verified=False,
                      physical_asic_compatibility_verified=False)
        return parsed
    except RejectedTrace:
        raise
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as error:
        raise RejectedTrace(str(error), raw_log) from error
