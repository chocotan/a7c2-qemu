# SPDX-License-Identifier: MIT
"""Direct, bounded shutter-v1 raw parser and independent operand assertion."""
import hashlib
import json
import math
import re

PROFILE = 'qemu-readonly-shutter-gate-v1'
SCHEMA = 'readonly_shutter_gate_v1'
CONTRACT_SCHEMA = 'readonly_shutter_gate_source_contract_v1'
LOW48_MAX = (1 << 48) - 1
U64_MAX = (1 << 64) - 1
SITES = ('final_entry', 'd570_cbnz_pre', 'successor_1724_pre', 'successor_1838_pre')
OFFSETS = dict(zip(SITES, (0x1af16dc, 0x1af1834, 0x1af1724, 0x1af1838)))
ANCHOR_OFFSETS = (0x1af16dc, 0x1af1830, 0x1af1724, 0x1af1838)
CASES = ('original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb')
COMMON = {'status': 'native_unverified', 'identity': 'unknown', 'binding': 'unbound',
          'pid': 'unknown', 'tid': 'unknown', 'capture': '0x0', 'physical': '0x0', 'retirement': '0x0'}
BEGIN = {'schema': SCHEMA, 'plugin_api': '0x7', 'max_vcpus': '0x1', 'sites': '0x4',
         'site_quota': '0x10', 'fault_quota': '0x20', 'register_byte_order': 'little',
         'identity_limit': 'raw_context_only_no_pid_tid_module_identity'}
GATE_FIELDS = ('site vcpu ordinal gate_sequence callback_phase event_pc gdb_pc_raw candidate_base '
               'anchor_length entry_anchor x0_raw x30_raw cpsr_raw cpsr_m context_mode nzcv nzcv_mask '
               'sp_available sp_raw sp_read_length sp_api_ok ttbr0_el1_available ttbr0_el1_raw '
               'ttbr0_el1_read_length ttbr0_el1_api_ok tpidr_el0_available tpidr_el0_raw '
               'tpidr_el0_read_length tpidr_el0_api_ok gdb_pc_read_length gdb_pc_api_ok '
               'x0_read_length x0_api_ok x30_read_length x30_api_ok cpsr_read_length cpsr_api_ok api_ok').split()
ENTRY_FIELDS = ('x1_raw x1_read_length x1_api_ok x2_raw x2_read_length x2_api_ok '
                'x3_raw x3_read_length x3_api_ok trigger_low32').split()
INTERNAL_FIELDS = ('x19_raw x19_read_length x19_api_ok x22_raw x22_read_length x22_api_ok '
                   'x23_raw x23_read_length x23_api_ok x29_raw x29_read_length x29_api_ok').split()
PREDICTION_FIELDS = 'loaded_w0 source_taken_prediction source_next_pc source_next_basis'.split()
EXTRA = dict(zip(SITES, (ENTRY_FIELDS, INTERNAL_FIELDS + PREDICTION_FIELDS,
                         INTERNAL_FIELDS, INTERNAL_FIELDS)))
END_FIELDS = ('stop ambiguous candidate_found candidate_base conflicting_base anchor_seen_mask '
              'site0_records site1_records site2_records site3_records gate_sequence '
              'site0_suppressed site1_suppressed site2_suppressed site3_suppressed '
              'fault_lines faults suppressed_faults close_result site0_unbound_callbacks '
              'site1_unbound_callbacks site2_unbound_callbacks site3_unbound_callbacks').split()
FAULT_FIELDS = {
    'register_read': 'reason site reg required_length read_attempted read_length api_ok'.split(),
    'unknown_register': 'reason reg required_length read_attempted read_length api_ok'.split(),
    'duplicate_register': ['reason', 'reg'], 'register_list': ['reason', 'descriptor_count'],
    'vcpu_limit': ['reason', 'vcpu', 'reinitialized'],
    'invalid_callback_context': ['reason', 'packed_raw', 'vcpu'],
    'invalid_mode': ['reason', 'site', 'cpsr_raw', 'cpsr_m'],
    'base_conflict': ['reason', 'candidate_base', 'conflicting_base'],
    'anchor_changed': ['reason', 'site', 'translated_pc', 'remaining_insns'],
    **{name: ['reason'] for name in ('registers_not_ready', 'target_requires_aarch64_little_endian',
                                    'plugin_api_range', 'system_emulation_required', 'single_vcpu_required')},
}
REGISTERS = ('pc', 'x0', 'x1', 'x2', 'x3', 'x19', 'x22', 'x23', 'x29', 'x30',
             'cpsr', 'sp', 'TTBR0_EL1', 'TPIDR_EL0')
OPTIONALS = ('sp', 'ttbr0_el1', 'tpidr_el0')
LIMITS = {'maximum_file_lines': 98, 'maximum_line_bytes_exclusive': 2048,
          'maximum_file_bytes_conservative': 200704, 'quota_per_site': 16,
          'maximum_success_rows': 64, 'maximum_fault_lines': 32}
FALSE_FLAGS = {name: False for name in (
    'Main_identity_verified', 'AP_identity_verified', 'PID_TID_uniqueness_verified',
    'address_space_uniqueness_verified', 'branch_edge_verified', 'instruction_retirement_verified',
    'branchretirement', 'retirement', 'storecompletion', 'original_store_or_return_verified',
    'capture', 'capture_verified', 'physical', 'physical_asic_compatibility_verified')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_json_value(value):
    """Check the complete decoded tree, including fields not used by this profile."""
    if type(value) is dict:
        for key, item in value.items():
            require(type(key) is str, 'non-string JSON key')
            validate_json_value(item)
    elif type(value) is list:
        for item in value:
            validate_json_value(item)
    elif type(value) is float:
        require(math.isfinite(value), 'nonfinite JSON number')
    else:
        require(value is None or type(value) in (str, int, bool), 'non-JSON value')


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key ' + key)
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('nonfinite JSON constant ' + value)
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    require(type(result) is dict, 'JSON object required')
    validate_json_value(result)
    return result


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def number(row, name):
    return int(row[name], 16)


def uint(value, bits, name):
    require(type(value) is int and 0 <= value < 1 << bits, 'invalid independent integer ' + name)
    return value


def fixed(row, name, digits):
    require(re.fullmatch(r'0x[0-9a-f]{%d}' % digits, row.get(name, '')) is not None,
            'non-exact raw width ' + name)
    return number(row, name)


def count(row, name):
    require(re.fullmatch(r'0x(?:0|[1-9a-f][0-9a-f]*)', row.get(name, '')) is not None,
            'noncanonical count ' + name)
    value = number(row, name)
    require(value <= U64_MAX, 'count overflow ' + name)
    return value


def checked_add(base, offset, span=1):
    require(type(base) is int and type(offset) is int and base >= 0 and offset >= 0 and
            span > 0 and base <= U64_MAX - offset, 'address uint64 overflow')
    value = base + offset
    require(value <= LOW48_MAX - (span - 1), 'address outside zero-extended low48')
    return value


def base_value(row, name='candidate_base', allow_zero=False):
    value = fixed(row, name, 16)
    require((allow_zero and value == 0) or (0 < value <= LOW48_MAX and value & 0xfff == 0),
            'invalid candidate base ' + name)
    if value:
        checked_add(value, 0x1af1838, 8)
    return value


def fields_from_line(line):
    require(line.startswith(b'kind=') and len(line) + 1 < 2048 and b'\r' not in line,
            'invalid prefix, CR or line bound')
    row = {}
    for token in line.decode('ascii').split(' '):
        require(token.count('=') == 1, 'invalid raw token')
        key, value = token.split('=')
        require(re.fullmatch(r'[A-Za-z0-9_]+', key) is not None and
                re.fullmatch(r'[A-Za-z0-9_]+', value) is not None and key not in row,
                'duplicate or noncanonical raw token')
        row[key] = value
    return row


def raw_ledger(raw):
    """Retain original bytes including LF, even when the last record is truncated."""
    result, offset = [], 0
    pieces = raw.split(b'\n')
    lines = [piece + b'\n' for piece in pieces[:-1]]
    if pieces[-1]:
        lines.append(pieces[-1])
    for index, line in enumerate(lines):
        item = {'trace_index': index, 'line_number': index + 1, 'byte_offset': offset,
                'byte_length': len(line), 'sha256': sha(line), 'raw_hex': line.hex(),
                'raw_ascii': None, 'canonical_fields': None, 'canonical': False}
        try:
            item['raw_ascii'] = line.decode('ascii')
            fields = fields_from_line(line.removesuffix(b'\n'))
            item['canonical_fields'] = list(fields.items())
            item['canonical'] = line.endswith(b'\n')
        except (ValueError, UnicodeError) as error:
            item['canonical_error'] = str(error)
        result.append(item)
        offset += len(line)
    return result


class RejectedTrace(ValueError):
    def __init__(self, message, raw):
        super().__init__(message)
        evidence = raw if type(raw) is bytes else b''
        self.evidence = {'trace_sha256': sha(evidence), 'byte_length': len(evidence),
                         'raw_hex': evidence.hex(), 'raw_ledger': raw_ledger(evidence),
                         'group_claim_rejected': True}


def validate_declaration(declaration):
    validate_json_value(declaration)
    require(type(declaration) is dict and declaration.get('schema') == SCHEMA and
            declaration.get('profile') == PROFILE and
            declaration.get('common_fields_every_line') == COMMON and
            list(declaration['common_fields_every_line']) == list(COMMON) and
            declaration.get('begin_fixed') == BEGIN and
            declaration.get('kinds') == {'begin': list(BEGIN), 'end': END_FIELDS} and
            declaration.get('shutter_gate_common_fields') == GATE_FIELDS and
            declaration.get('site_additional_fields') == EXTRA and
            declaration.get('fault_kinds') == FAULT_FIELDS and
            declaration.get('file_contract') == LIMITS and
            declaration.get('raw_widths') == {'register64': 16, 'cpsr_and_low32': 8,
                                             'cpsr_m': 2, 'counts': 'minimal lowercase hexadecimal'},
            'wrong shutter schema, exact field sets/order or limits')
    wanted = {site: {'ordinal': i, 'event_offset': hex(OFFSETS[site]),
                     'anchor_offset': hex(ANCHOR_OFFSETS[i]),
                     'anchor_lengths': [16, 8] if i == 0 else [8]}
              for i, site in enumerate(SITES)}
    require(declaration.get('sites') == wanted, 'schema sites differ')


def ordered_keys(row):
    kind = row.get('kind')
    if kind == 'shutter_gate':
        require(row.get('site') in SITES, 'unknown shutter site')
        fields = GATE_FIELDS + EXTRA[row['site']]
    elif kind == 'fault':
        require(row.get('reason') in FAULT_FIELDS, 'unknown fault reason')
        fields = FAULT_FIELDS[row['reason']]
    else:
        require(kind in ('begin', 'end'), 'unknown raw kind')
        fields = list(BEGIN) if kind == 'begin' else END_FIELDS
    require(list(row) == ['kind', *fields, *COMMON], 'unknown/missing/reordered exact raw keys')
    require(all(row[key] == value for key, value in COMMON.items()), 'promoted raw evidence')


def mode_fields(row):
    cpsr, mode = fixed(row, 'cpsr_raw', 8), fixed(row, 'cpsr_m', 2)
    require(mode == cpsr & 0x1f and mode in (0, 4, 5, 8, 9, 12, 13),
            'A32/reserved/inconsistent mode')
    require(row['context_mode'] == ('EL0t' if mode == 0 else 'other_aarch64') and
            row['nzcv_mask'] == '0xf0000000' and fixed(row, 'nzcv', 8) == cpsr & 0xf0000000,
            'mode or NZCV normalized')
    return mode


def optional(row, name):
    require(row[name + '_available'] in ('0x0', '0x1'), 'optional availability differs')
    present = row[name + '_available'] == '0x1'
    require(row[name + '_read_length'] == ('0x8' if present else '0x0') and
            row[name + '_api_ok'] == ('0x1' if present else 'unknown'), 'optional width/bool differs')
    if present:
        return fixed(row, name + '_raw', 16)
    require(row[name + '_raw'] == 'unknown', 'absent optional was invented')
    return None


def validate_fault(row):
    reason = row['reason']
    if 'site' in row:
        require(row['site'] in SITES, 'invalid fault site')
    if reason in ('register_read', 'unknown_register', 'duplicate_register'):
        require(row['reg'] in REGISTERS, 'invalid fault register')
    if reason in ('register_read', 'unknown_register'):
        needed = 4 if row['reg'] == 'cpsr' else 8
        length, ok = count(row, 'read_length'), count(row, 'api_ok')
        require(count(row, 'required_length') == needed and ok in (0, 1), 'fault read fields differ')
        require(count(row, 'read_attempted') == int(reason == 'register_read'), 'fault attempt differs')
        require((not ok or length != needed) if reason == 'register_read' else length == ok == 0,
                'fault falsely labels a successful read')
    elif reason == 'invalid_mode':
        cpsr, mode = fixed(row, 'cpsr_raw', 8), fixed(row, 'cpsr_m', 2)
        require(mode == cpsr & 0x1f and mode not in (0, 4, 5, 8, 9, 12, 13), 'fault mode differs')
    elif reason == 'base_conflict':
        require(base_value(row) != base_value(row, 'conflicting_base'), 'invented base conflict')
    elif reason == 'anchor_changed':
        fixed(row, 'translated_pc', 16)
        require(count(row, 'remaining_insns') >= 2, 'short TB called a complete change')
    elif reason == 'vcpu_limit':
        require(count(row, 'reinitialized') in (0, 1), 'invalid reinit flag')
        count(row, 'vcpu')
    elif reason == 'invalid_callback_context':
        fixed(row, 'packed_raw', 16)
        count(row, 'vcpu')
    elif reason == 'register_list':
        n = count(row, 'descriptor_count')
        require(n == 0 or n > 4096, 'valid descriptor count called invalid')


def validate_rows(rows):
    require(rows[0]['kind'] == 'begin' and rows[-1]['kind'] == 'end', 'missing begin/end')
    require(all(rows[0][key] == value for key, value in BEGIN.items()), 'begin constants differ')
    require(all(row['kind'] in ('shutter_gate', 'fault') for row in rows[1:-1]), 'misplaced record')
    end = rows[-1]
    found, ambiguous = count(end, 'candidate_found'), count(end, 'ambiguous')
    require(found in (0, 1) and ambiguous in (0, 1), 'invalid found/ambiguous flag')
    base = base_value(end, allow_zero=not found)
    conflict = base_value(end, 'conflicting_base', allow_zero=True)
    require(bool(base) == bool(found) and bool(conflict) == bool(ambiguous), 'base state differs')
    require(not conflict or conflict != base, 'conflicting base equals candidate')
    mask = count(end, 'anchor_seen_mask')
    require(mask <= 15 and (bool(mask & 2) if found else mask == 0), 'sole discriminator mask differs')
    require(end['close_result'] == 'unknown', 'close falsely self-attested')
    counters = dict.fromkeys(SITES, 0)
    sequence = faults = 0
    for row in rows[1:-1]:
        if row['kind'] == 'fault':
            validate_fault(row)
            faults += 1
            continue
        site = row['site']
        require(found and base_value(row) == base and count(row, 'vcpu') == 0 and
                row['callback_phase'] == 'before_instruction', 'unbound success/context differs')
        counters[site] += 1
        sequence += 1
        require(count(row, 'ordinal') == counters[site] <= 16 and
                count(row, 'gate_sequence') == sequence <= 64, 'success quota/order differs')
        require(mask & (1 << SITES.index(site)), 'successful site lacks exact anchor')
        require(fixed(row, 'event_pc', 16) == checked_add(base, OFFSETS[site]), 'event PC differs')
        fixed(row, 'gdb_pc_raw', 16)
        mode_fields(row)
        names = ('gdb_pc', 'x0', 'x30', 'cpsr') + (
            ('x1', 'x2', 'x3') if site == SITES[0] else ('x19', 'x22', 'x23', 'x29'))
        require(row['api_ok'] == '0x1', 'failed aggregate API')
        for name in names:
            require(row[name + '_api_ok'] == '0x1' and
                    row[name + '_read_length'] == ('0x4' if name == 'cpsr' else '0x8'),
                    'bool/width read mismatch ' + name)
            if name not in ('gdb_pc', 'cpsr'):
                fixed(row, name + '_raw', 16)
        for name in OPTIONALS:
            optional(row, name)
        if site == SITES[0]:
            require(row['entry_anchor'] in ('original16', 'existing_main_stub8') and
                    row['anchor_length'] == ('0x10' if row['entry_anchor'] == 'original16' else '0x8'),
                    'unsupported entry form')
            require(fixed(row, 'trigger_low32', 8) == number(row, 'x1_raw') & 0xffffffff,
                    'entry trigger differs')
        else:
            require(row['entry_anchor'] == 'not_applicable' and row['anchor_length'] == '0x8',
                    'internal anchor differs')
        if site == SITES[1]:
            w0 = fixed(row, 'loaded_w0', 8)
            require(w0 == number(row, 'x0_raw') & 0xffffffff and
                    count(row, 'source_taken_prediction') == int(w0 != 0) and
                    fixed(row, 'source_next_pc', 16) == checked_add(base, 0x1af1724 if w0 else 0x1af1838) and
                    row['source_next_basis'] == 'w0_low32', 'W0 source prediction differs')
    require(count(end, 'gate_sequence') == sequence and count(end, 'fault_lines') == faults <= 32,
            'end successful/fault line counters differ')
    fault_count, suppressed_faults = count(end, 'faults'), count(end, 'suppressed_faults')
    require(fault_count == min(U64_MAX, faults + suppressed_faults) and
            (suppressed_faults == 0 or faults == 32), 'end fault counters differ')
    for i, site in enumerate(SITES):
        require(count(end, 'site%d_records' % i) == counters[site], 'end site count differs')
        suppressed = count(end, 'site%d_suppressed' % i)
        require(not suppressed or counters[site] == 16, 'suppression before quota')
        count(end, 'site%d_unbound_callbacks' % i)
    require(count(end, 'site1_unbound_callbacks') == 0, 'strong callback cannot be unbound')
    allowed_stops = {'none', 'host_io_failure', 'base_conflict', 'anchor_changed', 'vcpu_limit',
                     'invalid_callback_context', 'registers_not_ready', 'register_list',
                     'duplicate_register', 'unknown_register', 'target_requires_aarch64_little_endian',
                     'plugin_api_range', 'system_emulation_required', 'single_vcpu_required'}
    require(end['stop'] in allowed_stops, 'unknown stop reason')
    require(not faults and not ambiguous and end['stop'] == 'none' and not fault_count,
            'fault or stop invalidates the raw evidence group')


def parse_trace(raw_log, declaration):
    try:
        require(type(raw_log) is bytes and raw_log.endswith(b'\n') and b'\r' not in raw_log and
                len(raw_log) <= 200704, 'truncated/oversized/non-byte trace')
        validate_declaration(declaration)
        lines = raw_log[:-1].split(b'\n')
        require(2 <= len(lines) <= 98, 'line count outside fixed bound')
        rows = [fields_from_line(line) for line in lines]
        for row in rows:
            ordered_keys(row)
        validate_rows(rows)
        return {'rows': rows, 'raw_ledger': raw_ledger(raw_log), 'begin': rows[0], 'end': rows[-1],
                'trace_sha256': sha(raw_log), 'byte_length': len(raw_log)}
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
        raise RejectedTrace(str(error), raw_log) from error


def assert_shutter_gate_trace_v1(raw_log, declaration, expected):
    """Compare actual raw fields directly to independently checked guest dump rows.

    expected is the frozen parent OPERAND_INTERFACE object; no trace-to-legacy conversion.
    Per-site order is compared, never interpreted as invocation or branch-edge pairing.
    """
    try:
        parsed = parse_trace(raw_log, declaration)
        validate_json_value(expected)
        require(type(expected) is dict and set(expected) == {
            'case', 'site_rows', 'minimum_suppressed', 'discriminator_expected'}, 'operand interface keys differ')
        case = expected['case']
        require(case in CASES and type(expected['discriminator_expected']) is bool and
                expected['discriminator_expected'] == (case in CASES[:2]), 'case/discriminator differs')
        require(type(expected['site_rows']) is dict and set(expected['site_rows']) == set(SITES) and
                type(expected['minimum_suppressed']) is dict and set(expected['minimum_suppressed']) == set(SITES),
                'expected fixed four site maps differ')
        end = parsed['end']
        require(count(end, 'candidate_found') == int(expected['discriminator_expected']), 'discriminator not observed')
        for i, site in enumerate(SITES):
            wanted = expected['site_rows'][site]
            require(type(wanted) is list, 'independent per-site ordered rows required')
            actual = [row for row in parsed['rows'] if row['kind'] == 'shutter_gate' and row['site'] == site]
            require(len(actual) == min(16, len(wanted)), 'missing/extra fixture rows ' + site)
            minimum = uint(expected['minimum_suppressed'][site], 64, 'minimum_suppressed')
            require(count(end, 'site%d_suppressed' % i) >= max(minimum, len(wanted) - 16),
                    'fixture suppression lower bound differs')
            for row, baseline in zip(actual, wanted[:16]):
                require(type(baseline) is dict and set(baseline) == {
                    'event_pc', 'registers', 'cpsr', 'sp', 'ttbr0_el1', 'tpidr_el0', 'entry_anchor'},
                    'incomplete independent operand row')
                event = uint(baseline['event_pc'], 64, 'event_pc')
                require(number(row, 'event_pc') == event and row['entry_anchor'] == baseline['entry_anchor'],
                        'fixture event/form differs')
                gprs = ('x0', 'x1', 'x2', 'x3', 'x30') if i == 0 else ('x0', 'x19', 'x22', 'x23', 'x29', 'x30')
                registers = baseline['registers']
                require(type(registers) is dict and set(registers) in (set(gprs), set(gprs) | {'pc'}),
                        'independent full64 GPR family incomplete')
                for name, value in registers.items():
                    value = uint(value, 64, name)
                    field = 'gdb_pc_raw' if name == 'pc' else name + '_raw'
                    require(number(row, field) == value, 'fixture full64 operand differs ' + name)
                cpsr = uint(baseline['cpsr'], 32, 'cpsr')
                require(number(row, 'cpsr_raw') == cpsr and number(row, 'nzcv') == cpsr & 0xf0000000,
                        'fixture CPSR/NZCV differs')
                for name in OPTIONALS:
                    value = baseline[name]
                    if value is not None:
                        uint(value, 64, name)
                    actual_value = optional(row, name)
                    if actual_value is not None:
                        require(value is not None and actual_value == value,
                                'present optional lacks independent matching baseline ' + name)
                if i == 0:
                    require(number(row, 'trigger_low32') == registers['x1'] & 0xffffffff,
                            'independent trigger differs')
                if i == 1:
                    low = registers['x0'] & 0xffffffff
                    base = event - OFFSETS[site]
                    require(number(row, 'loaded_w0') == low and
                            number(row, 'source_taken_prediction') == int(low != 0) and
                            number(row, 'source_next_pc') == base + (0x1af1724 if low else 0x1af1838),
                            'independent low32 prediction differs')
        parsed.update(synthetic_shutter_gate_observer_verified=True,
                      invocation_pairing='unknown', raw_identity='unknown', raw_binding='unbound',
                      **FALSE_FLAGS)
        return parsed
    except RejectedTrace:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
        raise RejectedTrace(str(error), raw_log) from error
