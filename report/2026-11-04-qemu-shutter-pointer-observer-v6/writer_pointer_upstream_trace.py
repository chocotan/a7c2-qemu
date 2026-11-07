#!/usr/bin/env python3
"""Read writer inputs and their raw dispatch registers; never infer call pairing."""
from pathlib import Path
import json
import re
import writer_pointer_upstream_trace_base as base

PROFILE = 'qemu-readonly-shutter-writer-v3'
SCHEMA = 'readonly_shutter_writer_v3'
MAX_TRACE = base.MAX_TRACE
SITES = base.SITES
read_file, digest, need, uint = base.read_file, base.digest, base.need, base.uint
ORIGINS = ('dispatch_entry', 'table_setter_entry', 'upstream_entry')
ORIGIN_OFFSETS = (0x2506220, 0x28bb120, 0x250646c)
ORIGIN_LENGTHS = (36, 32, 32)
BEGIN = dict(base.BEGIN, schema=SCHEMA, origin_sites='0x3', origin_selector='0x17c', origin_quota='0x10')
ORIGIN_REGISTERS = ('gdb_pc', 'x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x30', 'cpsr')
ORIGIN_KEYS = set(('kind site vcpu ordinal origin_sequence observation_sequence callback_phase event_pc '
                   'gdb_pc_raw candidate_base anchor_length selector_u32 x0_raw x1_raw x2_raw x3_raw '
                   'x4_raw x5_raw x30_raw cpsr_raw cpsr_m context_mode api_ok invocation_pairing_verified '
                   'store_retirement_verified memory_readback_verified').split()) | base.SCOPE.keys()
for name in ORIGIN_REGISTERS:
    ORIGIN_KEYS |= {name + '_read_length', name + '_api_ok'}
for name in base.OPTIONALS:
    ORIGIN_KEYS |= {name + '_available', name + '_raw', name + '_read_length', name + '_api_ok'}
ORIGIN_END = set(('origin_base origin_anchor_mask origin_sequence observation_sequence '
                  'origin0_records origin1_records origin0_suppressed origin1_suppressed '
                  'origin0_skipped origin1_skipped origin2_records origin2_suppressed origin2_skipped').split())


def fields(raw):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_TRACE and raw.endswith(b'\n'),
         'incomplete or oversized writer-v3 trace')
    rows = []
    for line in raw.splitlines(keepends=True):
        need(line.endswith(b'\n') and b'\r' not in line and len(line) < 2048, 'writer-v3 line framing differs')
        tokens = line[:-1].decode('ascii', 'strict').split(' ')
        need(all(re.fullmatch(r'[a-z][a-z0-9_]*=[^\s=]+', token) for token in tokens), 'invalid writer-v3 token')
        row = dict(token.split('=', 1) for token in tokens)
        need(len(row) == len(tokens) and all(row.get(k) == value for k, value in base.SCOPE.items()),
             'duplicate writer-v3 field or promoted scope')
        rows.append(row)
    return rows


def wire(rows):
    return b''.join((' '.join(key + '=' + value for key, value in row.items()) + '\n').encode('ascii') for row in rows)


def parse_trace(raw):
    rows = fields(raw)
    need(len(rows) >= 2 and rows[0] == BEGIN, 'writer-v3 exact begin required')
    end = rows[-1]
    need(set(end) == base.END_KEYS | ORIGIN_END and end['kind'] == 'end', 'writer-v3 exact terminal required')
    origin_base, mask = uint(end, 'origin_base'), uint(end, 'origin_anchor_mask', 3)
    need((mask and 0 < origin_base <= base.LOW48_MAX - 0x7e5d577 and origin_base & 0xfff == 0) or
         (not mask and origin_base == 0), 'writer-v3 origin base/mask differs')
    writer_rows, origins, order, counts = [], [], [], [0, 0, 0]
    for sequence, row in enumerate(rows[1:-1], 1):
        need(row.get('kind') in ('shutter_writer', 'writer_origin') and 'observation_sequence' in row,
             'writer-v3 fault or unsupported event')
        need(uint(row, 'observation_sequence') == sequence, 'writer-v3 global observation order differs')
        if row['kind'] == 'shutter_writer':
            need(set(row) == base.EVENT_KEYS | {'observation_sequence'}, 'writer-v3 setter fields differ')
            writer_rows.append({key: value for key, value in row.items() if key != 'observation_sequence'})
            order.append(dict(observation_sequence=sequence, kind='shutter_writer', site=row['site'],
                              local_sequence=uint(row, 'writer_sequence')))
            continue
        need(row['kind'] == 'writer_origin' and set(row) == ORIGIN_KEYS and row['site'] in ORIGINS,
             'writer-v3 unknown event or origin fields')
        site = ORIGINS.index(row['site'])
        counts[site] += 1
        need(mask & (1 << site) and counts[site] <= 16 and uint(row, 'ordinal') == counts[site] and
             uint(row, 'origin_sequence') == len(origins) + 1 and uint(row, 'candidate_base') == origin_base and
             uint(row, 'event_pc') == origin_base + ORIGIN_OFFSETS[site] and
             uint(row, 'anchor_length') == ORIGIN_LENGTHS[site] and uint(row, 'vcpu') == 0 and
             row['callback_phase'] == 'before_instruction', 'writer-v3 origin anchor/order differs')
        need(uint(row, 'selector_u32', 32) == uint(row, 'x1_raw' if site == 2 else 'x0_raw') & 0xffffffff == 0x17c,
             'writer-v3 selector filter differs')
        need(row['api_ok'] == '0x1' and all(row[key] == '0x0' for key in
             ('invocation_pairing_verified', 'store_retirement_verified', 'memory_readback_verified')),
             'writer-v3 origin completion claim differs')
        for name in ORIGIN_REGISTERS:
            uint(row, name + '_raw', 32 if name == 'cpsr' else 64)
            need(row[name + '_read_length'] == ('0x4' if name == 'cpsr' else '0x8') and
                 row[name + '_api_ok'] == '0x1', 'writer-v3 origin register read incomplete')
        mode = uint(row, 'cpsr_raw', 32) & 31
        need(mode in (0, 4, 5, 8, 9, 12, 13) and uint(row, 'cpsr_m') == mode and
             row['context_mode'] == ('EL0t' if mode == 0 else 'other_aarch64'), 'writer-v3 origin CPU mode differs')
        context = {}
        for name in base.OPTIONALS:
            available = uint(row, name + '_available', 1)
            if available:
                need(row[name + '_api_ok'] == '0x1' and row[name + '_read_length'] == '0x8',
                     'writer-v3 optional register read incomplete')
                context[name] = uint(row, name + '_raw')
            else:
                need(row[name + '_raw'] == row[name + '_api_ok'] == 'unknown' and row[name + '_read_length'] == '0x0',
                     'writer-v3 missing context fabricated')
                context[name] = None
        origins.append(dict(site=row['site'], sequence=len(origins) + 1, observation_sequence=sequence,
            candidate_base=origin_base, selector_u32=0x17c, value_u32=uint(row, 'x2_raw' if site == 2 else 'x1_raw') & 0xffffffff,
            registers={name: uint(row, name + '_raw') for name in ('x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x30')},
            event_pc=uint(row, 'event_pc'), gdb_pc_raw=uint(row, 'gdb_pc_raw'), context=context))
        order.append(dict(observation_sequence=sequence, kind='writer_origin', site=row['site'], local_sequence=len(origins)))
    need(uint(end, 'origin_sequence') == len(origins) and uint(end, 'observation_sequence') == len(order),
         'writer-v3 terminal global count differs')
    suppressed, skipped = [], []
    for site in range(3):
        need(uint(end, f'origin{site}_records') == counts[site], 'writer-v3 terminal origin count differs')
        omitted, other = uint(end, f'origin{site}_suppressed'), uint(end, f'origin{site}_skipped')
        need(not omitted or counts[site] == 16, 'writer-v3 origin quota suppressed early')
        need(mask & (1 << site) or counts[site] == omitted == other == 0, 'writer-v3 origin counters without anchor')
        suppressed.append(omitted)
        skipped.append(other)
    writer_end = {key: value for key, value in end.items() if key in base.END_KEYS}
    original = base.parse_trace(wire([base.BEGIN, *writer_rows, writer_end]))
    need(not (mask and original['candidate_found']) or original['candidate_base'] == origin_base,
         'writer-v3 setter/origin base mismatch')
    return dict(original, schema=SCHEMA, trace_sha256=digest(raw),
        status='observed_raw' if original['events'] or origins else 'no_observed_calls',
        origin_base=origin_base if mask else None, origin_anchor_mask=mask, origins=origins,
        observation_order=order, origin_site_counts=dict(zip(ORIGINS, counts)),
        origin_suppressed_counts=dict(zip(ORIGINS, suppressed)), origin_filtered_counts=dict(zip(ORIGINS, skipped)),
        truncated_by_quota=original['truncated_by_quota'] or any(suppressed),
        selector_filter=0x17c, original_predecessor_edge_verified=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(parse_trace(read_file(args.trace, expected_sha256=args.sha256)), indent=2))
