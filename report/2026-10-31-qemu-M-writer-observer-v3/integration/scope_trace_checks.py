"""Strict content checks for the self-owned QEMU fixture, never Sony acceptance."""
import re

COMMON = {'status': 'native_unverified', 'identity': 'unknown', 'binding': 'unbound',
          'pid': 'unknown', 'tid': 'unknown', 'capture': '0x0', 'physical': '0x0'}
GPRS = ('x0', 'x19', 'x20', 'x21', 'x23', 'x24', 'x29', 'x30')
TOKENS = ('ttbr0_el1', 'tpidr_el0')


def require(condition, message):
    if not condition:
        raise ValueError('synthetic scope trace: ' + message)


def number(row, name):
    value = row.get(name, '')
    require(re.fullmatch(r'0x[0-9a-f]+', value) is not None, 'non-hex field ' + name)
    result = int(value, 16)
    require(result <= 0xffffffffffffffff, 'uint64 overflow ' + name)
    return result


def rows_from(raw):
    require(raw.endswith(b'\n') and b'\r' not in raw and len(raw) <= 131 * 2048, 'truncated or oversized log')
    rows = []
    for line in raw[:-1].split(b'\n'):
        require(line.startswith(b'kind=') and len(line) < 2048, 'unproved line prefix or size')
        row = {}
        for part in line.decode('ascii').split(' '):
            require(part.count('=') == 1, 'invalid token')
            key, value = part.split('=')
            require(re.fullmatch(r'[A-Za-z0-9_]+', key) is not None and value and key not in row, 'invalid or duplicate key')
            row[key] = value
        require(all(row.get(k) == v for k, v in COMMON.items()), 'promoted identity or success flag')
        rows.append(row)
    require(2 <= len(rows) <= 131 and rows[0]['kind'] == 'begin' and rows[-1]['kind'] == 'end', 'missing begin/end')
    require(all(row['kind'] in ('candidate', 'entry', 'poweron_context', 'late') for row in rows[1:-1]), 'fault or misplaced record')
    return rows


def assert_scope_trace(raw, expected_entries, candidate_base, other_lr):
    """Expected entries are {(slot, ordinal): exact pre-instruction numeric fields}."""
    rows = rows_from(raw)
    begin, end = rows[0], rows[-1]
    wanted_begin = {'schema': 'readonly_scope_v1', 'plugin_api': '0x7', 'max_vcpus': '0x1',
                    'lr_quota': '0x10', 'fault_quota': '0x20', 'anchor_length': '0x18',
                    'register_byte_order': 'little', 'identity_limit': 'raw_context_only_no_pid_tid_module_identity',
                    'poweron_quota': '0x10', 'poweron_anchor_length': '0x8'}
    common = set(COMMON) | {'kind'}
    entry_keys = {'vcpu', 'lr_slot', 'ordinal', 'actual_pc', 'translated_entry_pc', 'candidate_base',
                  'lr', 'sp', 'cpsr_raw', 'nzcv', 'nzcv_mask', 'cpsr_m', 'context_mode', 'api_ok', *GPRS}
    entry_keys |= {name + '_read_length' for name in ('pc', 'lr', *GPRS, 'sp', 'cpsr')}
    entry_keys |= {token + suffix for token in TOKENS for suffix in ('_available', '_raw', '_read_length')}
    keys = {'begin': set(wanted_begin), 'candidate': {'candidate_base', 'translated_entry_pc', 'anchor_length'},
            'entry': entry_keys, 'end': {'stop', 'ambiguous', 'candidate_found', 'candidate_base', 'conflicting_base',
            'lr0_records', 'lr1_records', 'poweron_records', 'late0_records', 'late1_records', 'late2_records',
            'late_sequence', 'fault_lines', 'faults', 'suppressed_faults', 'other_lr', 'close_result'}}
    require(all(row['kind'] in keys and set(row) == common | keys[row['kind']] for row in rows), 'unknown or missing fields')
    require(all(begin.get(k) == v for k, v in wanted_begin.items()), 'begin contract differs')
    candidates = [row for row in rows if row['kind'] == 'candidate']
    require(len(candidates) == int(candidate_base is not None), 'candidate count differs')
    if candidate_base is not None:
        candidate, = candidates
        require(number(candidate, 'candidate_base') == candidate_base and
                number(candidate, 'translated_entry_pc') == candidate_base + 0x2e068cc and
                number(candidate, 'anchor_length') == 24, 'candidate address differs')
    entries = [row for row in rows if row['kind'] == 'entry']
    require(len(entries) == len(expected_entries), 'entry count differs')
    seen = set()
    for row in entries:
        key = (number(row, 'lr_slot'), number(row, 'ordinal'))
        require(key in expected_entries and key not in seen, 'unexpected or duplicate quota entry')
        seen.add(key)
        require(key[0] in (0, 1) and 1 <= key[1] <= 16 and number(row, 'vcpu') == 0, 'quota or vCPU differs')
        require(all(number(row, name) == value for name, value in expected_entries[key].items()), 'pre-instruction value differs')
        require(number(row, 'lr') == number(row, 'x30'), 'LR and x30 differ')
        for name in ('actual_pc', 'translated_entry_pc', 'candidate_base', 'lr', *GPRS, 'sp'):
            require(re.fullmatch(r'0x[0-9a-f]{16}', row.get(name, '')) is not None, 'non-64-bit value ' + name)
        for name in ('pc', 'lr', *GPRS, 'sp'):
            require(number(row, name + '_read_length') == 8, 'non-exact register width ' + name)
        require(number(row, 'cpsr_read_length') == 4 and number(row, 'api_ok') == 1, 'CPSR width or API failure')
        require(all(re.fullmatch(r'0x[0-9a-f]{8}', row.get(name, '')) is not None
                    for name in ('cpsr_raw', 'nzcv')), 'non-32-bit flags')
        cpsr = number(row, 'cpsr_raw')
        require(cpsr <= 0xffffffff and not cpsr & 0x10, 'not AArch64 CPSR')
        mode = cpsr & 0x1f
        require(mode in (0, 4, 5, 8, 9, 12, 13), 'reserved AArch64 mode')
        require(number(row, 'cpsr_m') == mode and row.get('context_mode') == ('EL0t' if mode == 0 else 'other_aarch64'), 'mode was normalized')
        require(number(row, 'nzcv_mask') == 0xf0000000 and number(row, 'nzcv') == cpsr & 0xf0000000, 'NZCV differs')
        for token in TOKENS:
            available = number(row, token + '_available')
            require(available in (0, 1), 'invalid optional token availability')
            require(number(row, token + '_read_length') == (8 if available else 0), 'optional token width')
            if available:
                require(re.fullmatch(r'0x[0-9a-f]{16}', row.get(token + '_raw', '')) is not None, 'token was truncated')
            else:
                require(row.get(token + '_raw') == 'unknown', 'invented optional token')
    require(seen == set(expected_entries), 'missing quota entry')
    require(end.get('stop') == 'none' and end.get('close_result') == 'unknown', 'incomplete or falsely attested close')
    for field in ('ambiguous', 'conflicting_base', 'fault_lines', 'faults', 'suppressed_faults',
                  'poweron_records', 'late0_records', 'late1_records', 'late2_records', 'late_sequence'):
        require(number(end, field) == 0, 'fault or ambiguity ' + field)
    require(number(end, 'candidate_found') == int(candidate_base is not None) and
            number(end, 'candidate_base') == (candidate_base or 0) and
            number(end, 'other_lr') == other_lr, 'end candidate or otherLR count differs')
    for slot in (0, 1):
        require(number(end, 'lr%d_records' % slot) == sum(k[0] == slot for k in expected_entries), 'end success counter differs')
    return {'synthetic_scope_observer_verified': True, 'entries': len(entries),
            'candidate_count': len(candidates), 'capture_verified': False, 'original_Main_identity_verified': False}
