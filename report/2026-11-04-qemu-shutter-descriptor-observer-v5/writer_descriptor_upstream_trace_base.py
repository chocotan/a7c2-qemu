#!/usr/bin/env python3
"""Read bounded writer observations; never identify an AP or infer a completed store."""
from pathlib import Path
import hashlib
import json
import os
import re
import stat

PROFILE = 'qemu-readonly-shutter-writer-v1'
SCHEMA = 'readonly_shutter_writer_v1'
MAX_TRACE = 256 * 1024
LOW48_MAX = (1 << 48) - 1
SITES = ('setter_entry', 'store_pre', 'ret_pre')
OFFSETS = (0x2767978, 0x276797c, 0x2767980)
SCOPE = dict(status='native_unverified', identity='unknown', binding='unbound',
             pid='unknown', tid='unknown', capture='0x0', physical='0x0', retirement='0x0')
BEGIN = dict(kind='begin', schema=SCHEMA, plugin_api='0x7', max_vcpus='0x1', sites='0x3',
    site_quota='0x10', fault_quota='0x20', register_byte_order='little',
    identity_limit='raw_context_only_no_pid_tid_module_identity', **SCOPE)
REGISTERS = ('gdb_pc', 'x0', 'x1', 'x30', 'cpsr')
OPTIONALS = ('sp', 'ttbr0_el1', 'tpidr_el0')
EVENT_KEYS = set(('kind site vcpu ordinal writer_sequence callback_phase event_pc gdb_pc_raw '
    'candidate_base anchor_length x0_raw input_w0 x1_raw x30_raw cpsr_raw cpsr_m context_mode '
    'expected_destination destination_base_checked api_ok store_retirement_verified '
    'memory_readback_verified').split()) | SCOPE.keys()
for name in REGISTERS:
    EVENT_KEYS |= {name + '_read_length', name + '_api_ok'}
for name in OPTIONALS:
    EVENT_KEYS |= {name + '_available', name + '_raw', name + '_read_length', name + '_api_ok'}
END_KEYS = set(('kind stop ambiguous candidate_found candidate_base conflicting_base anchor_seen_mask '
    'writer_sequence fault_lines faults suppressed_faults close_result').split()) | SCOPE.keys()
for index in range(3):
    END_KEYS |= {'site' + str(index) + '_records', 'site' + str(index) + '_suppressed'}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_file(value, limit=MAX_TRACE, expected_sha256=None):
    path = Path(value)
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path,
         'writer input requires a canonical absolute path')
    need(not any(item.is_symlink() for item in (path, *path.parents)), 'symlinked writer input')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1 and
             not before.st_mode & 0o022 and before.st_size <= limit, 'untrusted or oversized writer input')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    need(stamp(before) == stamp(after) == stamp(path.stat()) and len(raw) == before.st_size,
         'writer input changed during read')
    if expected_sha256 is not None:
        need(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256) and
             digest(raw) == expected_sha256, 'writer input digest differs')
    return raw


def uint(row, key, bits=64):
    value = row[key]
    need(re.fullmatch(r'0x[0-9a-f]+', value) is not None, 'invalid hex field: ' + key)
    number = int(value, 16)
    need(number < 1 << bits, 'integer overflow: ' + key)
    return number


def parse_trace(raw):
    need(type(raw) is bytes and 0 < len(raw) <= MAX_TRACE and raw.endswith(b'\n'),
         'missing, oversized or incomplete writer trace')
    rows = []
    for line in raw.splitlines(keepends=True):
        need(line.endswith(b'\n') and b'\r' not in line and len(line) < 2048,
             'writer trace line framing or size differs')
        tokens = line[:-1].decode('ascii', 'strict').split(' ')
        need(all(re.fullmatch(r'[a-z][a-z0-9_]*=[^\s=]+', token) for token in tokens),
             'malformed writer trace field')
        row = dict(token.split('=', 1) for token in tokens)
        need(len(row) == len(tokens) and all(row.get(k) == v for k, v in SCOPE.items()),
             'duplicate field or unsupported writer identity/scope claim')
        rows.append(row)
    need(len(rows) >= 2 and rows[0] == BEGIN, 'writer begin schema differs')
    end = rows[-1]
    need(set(end) == END_KEYS and end['kind'] == 'end', 'writer terminal is missing or malformed')
    need(end['stop'] == 'none' and end['ambiguous'] == '0x0' and end['close_result'] == 'unknown' and
         uint(end, 'faults') == uint(end, 'fault_lines') == uint(end, 'suppressed_faults') == 0 and
         uint(end, 'conflicting_base') == 0, 'writer fault, ambiguity or unsupported completion claim')
    found = uint(end, 'candidate_found', 1)
    base = uint(end, 'candidate_base')
    if found:
        need(0 < base <= LOW48_MAX - 0x7e5d577 and base & 0xfff == 0,
             'writer candidate base is out of range or misaligned')
    else:
        need(base == 0 and uint(end, 'anchor_seen_mask') == 0, 'empty writer candidate has a base or anchor')
    counts = [0, 0, 0]
    events = []
    for sequence, row in enumerate(rows[1:-1], 1):
        need(set(row) == EVENT_KEYS and row['kind'] == 'shutter_writer' and row['site'] in SITES,
             'unsupported writer event or field set')
        site = SITES.index(row['site'])
        counts[site] += 1
        need(found and uint(row, 'candidate_base') == base and counts[site] <= 16 and
             uint(row, 'ordinal') == counts[site] and uint(row, 'writer_sequence') == sequence,
             'writer sequence, ordinal, quota or base differs')
        need(uint(row, 'vcpu') == 0 and row['callback_phase'] == 'before_instruction' and
             uint(row, 'anchor_length') == 12 and uint(row, 'event_pc') == base + OFFSETS[site] and
             uint(row, 'expected_destination') == base + 0x7e5d570,
             'writer site, PC or destination binding differs')
        need(uint(row, 'destination_base_checked', 1) == int(site != 0) and
             (site == 0 or uint(row, 'x1_raw') == base + 0x7e5d000),
             'writer ADRP destination base differs')
        cpsr = uint(row, 'cpsr_raw', 32)
        mode = cpsr & 31
        need(mode in (0, 4, 5, 8, 9, 12, 13) and uint(row, 'cpsr_m') == mode and
             row['context_mode'] == ('EL0t' if mode == 0 else 'other_aarch64'), 'writer CPU mode differs')
        need(uint(row, 'input_w0', 32) == uint(row, 'x0_raw') & 0xffffffff,
             'writer low32 input differs from raw X0')
        for name in REGISTERS:
            uint(row, name + '_raw', 32 if name == 'cpsr' else 64)
            need(row[name + '_api_ok'] == '0x1' and
                 uint(row, name + '_read_length') == (4 if name == 'cpsr' else 8),
                 'writer register read failed or wrong width')
        need(row['api_ok'] == '0x1' and row['store_retirement_verified'] ==
             row['memory_readback_verified'] == '0x0', 'writer API or store-completion claim differs')
        context = {}
        for name in OPTIONALS:
            available = uint(row, name + '_available', 1)
            if available:
                need(row[name + '_api_ok'] == '0x1' and uint(row, name + '_read_length') == 8,
                     'writer optional register read failed or wrong width')
                context[name] = uint(row, name + '_raw')
            else:
                need(row[name + '_raw'] == row[name + '_api_ok'] == 'unknown' and
                     row[name + '_read_length'] == '0x0', 'writer absent register has fabricated contents')
                context[name] = None
        events.append(dict(site=row['site'], sequence=sequence, candidate_base=base,
            input_w0=uint(row, 'input_w0', 32), link_register_raw=uint(row, 'x30_raw'),
            event_pc=uint(row, 'event_pc'), gdb_pc_raw=uint(row, 'gdb_pc_raw'), context=context))
    need(uint(end, 'writer_sequence') == len(events), 'writer terminal sequence differs')
    suppressed = []
    mask = 0
    for index, count in enumerate(counts):
        need(uint(end, 'site' + str(index) + '_records') == count,
             'writer terminal site counter differs')
        omitted = uint(end, 'site' + str(index) + '_suppressed')
        need(not omitted or count == 16, 'writer suppression before site quota')
        suppressed.append(omitted)
        if count:
            mask |= 1 << index
    need(uint(end, 'anchor_seen_mask') == mask, 'writer executed-anchor mask differs')
    return dict(schema=SCHEMA, trace_sha256=digest(raw), status='observed_raw' if events else 'no_observed_calls',
        candidate_found=bool(found), candidate_base=base if found else None, events=events,
        site_counts=dict(zip(SITES, counts)), suppressed_counts=dict(zip(SITES, suppressed)),
        truncated_by_quota=any(suppressed), absence_proven=False, AP_identity_verified=False,
        invocation_pairing_verified=False, store_retirement_verified=False, memory_readback_verified=False,
        original_CP_RAM_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(parse_trace(read_file(args.trace, expected_sha256=args.sha256)), indent=2))
