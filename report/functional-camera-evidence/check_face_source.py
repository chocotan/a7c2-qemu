#!/usr/bin/env python3
"""Offline AP-source content joins. Software read event only; never capture proof.

The capture checker supplies its bounded readers and validated same-run transport.
No runtime module is imported until OP11 is actually observed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

MODEL = 'paused-source-snapshot-v1'
STAGE = 'functional_AP_source_snapshot_consumed'
POLICY = 'original-owner-open-paused-CPU-AS-full-source-read-retained-readback-no-global-writer-claim'
FALSE_CLAIMS = ('strict_native_backend_verified', 'original_global_writer_exclusion_verified',
                'native_global_writer_exclusion_verified', 'source_writer_completion_verified',
                'native_source_atomicity_verified', 'physical_asic_compatibility_verified',
                'physical_ASIC', 'physicalBackingObjectVerified', 'original_CP_executed',
                'original_CP_RAM_verified', 'original_RTOS_verified', 'native172772_verified', 'capture_verified')


def empty(status='not_observed'):
    return dict(status=status, required=status != 'not_observed', verified=False, stage=STAGE,
                source_model=MODEL, transactions=[], missing=[], **dict.fromkeys(FALSE_CLAIMS, False))


def observed(rows, events):
    return any(r['tag'].startswith('FUNCTIONAL_FACE_SOURCE_') for r in rows) or any(
        e.get('kind') == 'ap_source_result' or e.get('kind') == 'request' and e.get('opcode') == 11 for e in events)


def paused_window(api, snapshot, packet, tx, request):
    """Bind actual stop/read/restore/continue receipts to this exact OP11."""
    need, check = api.needed, api.require
    window = snapshot.get('paused_window')
    need(type(window) is dict, 'OP11 actual paused_window receipt')
    required = ('sequence', 'model_instance', 'origin', 'request_header_sha256', 'request_payload_sha256',
                'observed_header_sha256', 'observed_payload_sha256', 'prior_status', 'prior_status_qmp_id',
                'stop_reply', 'stop_qmp_id', 'paused_status', 'paused_status_qmp_id', 'commands',
                'physical_mode_restored_before_exit', 'continuation', 'window_closed')
    need(all(k in window for k in required), 'OP11 paused_window fields missing: ' +
         ','.join(k for k in required if k not in window))
    header = bytes.fromhex(request['raw_header_hex'])
    payload = api.payload_read(tx['_run'], tx['request_payload'])
    check(api.uint(window['sequence']) == tx['first'] == request['sequence'] and
          api.uint(window['model_instance']) == tx['model_instance'] == int.from_bytes(header[16:24], 'little') and
          api.typed_equal(window['origin'], tx['origin']) and api.typed_equal(window['origin'], request['origin']) and
          tx['origin']['producer_tid'] == packet['tid'], 'paused_window sequence/nonce/origin differs')
    check(window['request_header_sha256'] == window['observed_header_sha256'] == request['raw_header_sha256'] == api.sha(header) and
          window['request_payload_sha256'] == window['observed_payload_sha256'] == request['request_sha256'] == api.sha(payload),
          'paused_window actual request/observed header or payload SHA differs')
    def qid(name):
        need(window.get(name) is not None, 'paused_window actual QMP serial missing: ' + name)
        value = window[name]
        check(type(value) is int and 0 < value < 2**64, 'paused_window invalid QMP serial: ' + name)
        return value
    def status(value, running):
        check(type(value) is dict and type(value.get('running')) is bool and value['running'] is running and
              value.get('status') == ('running' if running else 'paused') and
              ('singlestep' not in value or type(value['singlestep']) is bool), 'paused_window QMP status differs')
    prior = window['prior_status']
    check(type(prior) is dict and type(prior.get('running')) is bool, 'paused_window prior running is not bool')
    status(prior, prior['running'])
    status(window['paused_status'], False)
    first, stopped = qid('prior_status_qmp_id'), qid('paused_status_qmp_id')
    if prior['running']:
        check(api.typed_equal(window['stop_reply'], {}) and qid('stop_qmp_id') == first + 1 and
              stopped == first + 2, 'paused_window actual stop/requery IDs or reply differ')
    else:
        check(window['stop_reply'] is None and window['stop_qmp_id'] is None and stopped == first and
              api.typed_equal(prior, window['paused_status']), 'paused_window already-paused stop/requery fabricated')
    commands = window['commands']
    need(type(commands) is list and len(commands) == 4, 'paused_window exact CPU0/mtree/full-xp/full-xp command receipts')
    mapping, reads = snapshot['mapping'], snapshot['full_span_reads']
    xp = f'xp /{packet["length"]}bx 0x{packet["physical"]:x}'
    lines = ('cpu 0', 'info mtree -f -o', xp, xp)
    replies = [(0, api.sha(b'')), (mapping['mtree_bytes'], mapping['mtree_sha256'])] + [
        (r['bytes'], r['sha256']) for r in reads]
    for index, (command, line, (size, digest)) in enumerate(zip(commands, lines, replies), 1):
        check(type(command) is dict and command.get('command') == 'human-monitor-command' and
              api.typed_equal(command.get('arguments'), {'command-line': line}) and
              type(command.get('qmp_id')) is int and 0 < command['qmp_id'] < 2**64 and
              command['qmp_id'] == stopped + index and command.get('reply_type') == 'str' and
              type(command.get('reply_bytes')) is int and command['reply_bytes'] == size and
              command.get('reply_sha256') == digest, 'paused_window command/order/QMP ID/actual reply differs')
    check(window['physical_mode_restored_before_exit'] is True and window['window_closed'] is True,
          'paused_window physical mode not restored or window not closed')
    continuation = window['continuation']
    resume_keys = ('resume_reply', 'resume_qmp_id', 'resumed_status', 'resumed_status_qmp_id')
    last = stopped + 4
    if continuation == 'suppressed':
        need(False, 'paused_window suppressed continuation lacks an actual terminal status receipt')
    if prior['running']:
        check(continuation == 'resumed', 'running source window did not actually resume')
        need(all(k in window for k in resume_keys), 'paused_window actual resume/status receipt missing')
        check(api.typed_equal(window['resume_reply'], {}) and qid('resume_qmp_id') == last + 1 and
              qid('resumed_status_qmp_id') == last + 2, 'paused_window actual cont/requery IDs or reply differ')
        status(window['resumed_status'], True)
        last += 2
    else:
        check(continuation == 'kept_paused' and not any(k in window for k in resume_keys),
              'paused_window already-paused cont/resume metadata fabricated')
    return dict(paused_window_verified=True, copy_window_continuation=continuation,
                qmp_first_id=first, qmp_last_id=last)


def host_content(api, source, packet, tx, events, mailbox):
    """Reconstruct bytes, xp receipts and canonical ranges, not opaque hashes."""
    need, check = api.needed, api.require
    body = api.transfer_output(tx['_run'], tx)
    check(len(body) == packet['length'] and tx['token'] >= source.TOKEN_BASE and tx.get('frame') is None,
          'source bytes/token namespace/frame proof differs')
    selected = [e for e in events if tx['first'] <= e.get('sequence', 0) <= tx['last'] and
                e.get('kind') in ('ap_source_result', 'core_result', 'response', 'model_frame')]
    opened = [e for e in selected if e['kind'] == 'ap_source_result' and e['opcode'] == 11]
    need(len(opened) == 1, 'one actual ap_source_result OP11, never a C core/frame result')
    check(not any(e['kind'] in ('core_result', 'model_frame') for e in selected), 'source disguised as C core/frame')
    snapshot = opened[0].get('source_snapshot')
    need(type(snapshot) is dict, 'HostSourceClaim source_snapshot receipt')
    for key, value in source.CLAIMS.items():
        check(api.typed_equal(snapshot.get(key), value), 'source scope promoted/missing: ' + key)
    check(snapshot.get('exact_double_read_equal') is True and snapshot.get('bytes') == len(body) and
          snapshot.get('sha256') == api.sha(body), 'source whole-body receipt differs')
    reads = snapshot.get('full_span_reads')
    need(type(reads) is list and len(reads) == 2, 'two full-span xp receipts')
    # QEMU emits at least eight address digits; some protocol mocks use sixteen.
    # Derive that width from the original prefix, then bind every byte of the dump.
    prefix = re.match(r'([0-9a-f]{8,16}):', reads[0].get('raw_prefix', ''))
    check(prefix is not None, 'original xp first address/width missing')
    width = len(prefix[1])
    xp = ''.join(f'{packet["physical"] + n:0{width}x}:' + ''.join(f' 0x{v:02x}' for v in body[n:n + 8]) + '\r\n'
                 for n in range(0, len(body), 8))
    check(source.parse_xp(xp, packet['physical'], len(body)) == body, 'source xp reparse differs')
    for receipt in reads:
        check(type(receipt) is dict and receipt.get('kind') == 'xp' and
              receipt.get('bytes') == len(xp) and receipt.get('sha256') == api.sha(xp.encode()) and
              receipt.get('raw_prefix') == xp[:256] and receipt.get('raw_tail') == xp[-256:] and
              receipt.get('decoded_bytes') == len(body) and receipt.get('decoded_sha256') == api.sha(body),
              'full original xp dump hash/prefix/tail/content differs')
    cursor, chunks, value = 0, 0, api.writeback.FNV_INIT
    digest = hashlib.sha256()
    for seq in range(tx['first'], tx['last'] + 1):
        actual = [e for e in selected if e.get('sequence') == seq and e['kind'] == 'ap_source_result']
        replies = [e for e in selected if e.get('sequence') == seq and e['kind'] == 'response']
        need(len(actual) == len(replies) == 1, 'source result/response sequence missing/duplicate')
        event, reply = actual[0], replies[0]
        for key, claim in source.CLAIMS.items():
            check(api.typed_equal(event.get('source_snapshot', {}).get(key), claim),
                  'source chunk/release scope promoted/missing: ' + key)
        check(event.get('actual_c_result', 1) is None and type(event.get('actual_source_result')) is int and
              event['actual_source_result'] == 0 and event.get('source_provider_kind') == MODEL and
              reply.get('actual_c_result', 1) is None and type(reply.get('actual_source_result')) is int and
              reply['actual_source_result'] == 0 and reply.get('data_readback') is True,
              'source actual result/provider/staged readback differs')
        release = seq == tx['last']
        check(event.get('opcode') == (65 if release else 11 if seq == tx['first'] else 64),
              'source READ/RELEASE operation differs')
        if not release:
            part = api.payload_read(tx['_run'], event['output_payload'])
            check(event['offset'] == cursor and event['token'] == tx['token'] and
                  event['total'] == len(body) and part == body[cursor:cursor + len(part)] and part,
                  'source chunk offset/token/actual bytes differs')
            digest.update(part)
            value = api.fnv_update(value, part)
            cursor += len(part)
            chunks += 1
        else:
            check(api.payload_read(tx['_run'], event['request_payload']) == struct.pack('<2Q', tx['token'], value) and
                  cursor == len(body) and not api.payload_read(tx['_run'], event['output_payload']),
                  'source release whole FNV/body differs')
        transfer = event.get('result_transfer')
        expected = dict(status='released' if release else 'opened' if seq == tx['first'] else 'chunk',
                        token=tx['token'], total=len(body), reconstructed_bytes=cursor, fnv1a64=value,
                        sha256=digest.hexdigest(), chunk_count=chunks, first_sequence=tx['first'], sequence=seq,
                        provider_kind='source', source_provider_kind=MODEL, origin=tx['origin'], complete=cursor == len(body))
        check(api.typed_equal(transfer, expected) and api.typed_equal(reply.get('result_transfer'), transfer),
              'source actual retained reconstruction/provider/whole digest differs')
    mapping = snapshot.get('mapping')
    need(type(mapping) is dict, 'source mapping receipt')
    tree = mapping.get('mtree_raw')
    need(type(tree) is str and tree, 'retained original mtree_raw for actual CPU AS/winning RAM row')
    tree_bytes = tree.encode('utf-8')
    check(len(tree_bytes) <= 256 * 1024 and type(mapping.get('mtree_bytes')) is int and
          mapping['mtree_bytes'] == len(tree_bytes) and mapping.get('mtree_sha256') == api.sha(tree_bytes),
          'retained original mtree byte bound/size/SHA differs')
    check(type(mapping.get('monitor_cpu')) is int and mapping['monitor_cpu'] == 0 and
          mapping.get('monitor_selection_reply') == '', 'actual monitor CPU0 selection receipt differs')
    recomputed = source.disjoint(tree, packet, mailbox)
    check(api.typed_equal({key: mapping.get(key) for key in recomputed}, recomputed),
          'retained original mtree actual AS/winning row/canonical mapping differs')
    requests = [e for e in events if e.get('kind') == 'request' and e.get('sequence') == tx['first']]
    check(len(requests) == 1, 'paused_window original OP11 request missing/duplicate')
    window = paused_window(api, snapshot, packet, tx, requests[0])
    return dict(bytes=len(body), sha256=api.sha(body), fnv1a64=f'{api.fnv(body):016x}',
                full_xp_content_verified=True, retained_stream_verified=True,
                canonical_offsets_verified=True, exact_winning_RAM_row_verified=True,
                actual_CPU_AS_verified=True, monitor_cpu0_verified=True, **window), snapshot


def ticket(api, rows, pid, tid, observation, op, unit, handle, request=None, reply=None):
    check, need, num = api.require, api.needed, api.number
    group = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_DMM_AP_OBSERVATION' and
             r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
             num(r['fields']['observation']) == observation]
    need(len(group) == 4, f'original {op:#x} complete submit/send/receive/free0 ticket observation={observation}')
    check([num(r['fields']['event']) for r in group] == [1, 2, 3, 4], 'original AP ticket event sequence differs')
    first = group[0]['fields']
    request = request if request is not None else api.raw_hex(first, 'request_raw', 40)
    wire_reply = api.raw_hex(group[-1]['fields'], 'reply_raw', 40)
    check(int.from_bytes(request[:4], 'little') == op and
          struct.unpack_from('<Hh', wire_reply) == (op | 0x8000, 0), 'native raw opcode/signed kernel status differs')
    if op in (0x20, 0x21):
        check(struct.unpack_from('<I', request, 4)[0] == unit, 'native raw unit differs')
    if op != 0x20:
        check(struct.unpack_from('<I', request, 8)[0] == handle, 'native raw handle differs')
    else:
        check(struct.unpack_from('<I', wire_reply, 12)[0] == handle, 'birth full handle differs')
    check(reply is None or wire_reply == reply, 'retained native reply differs from original observer')
    request_pointer = num(first['request'])
    check(request_pointer != 0 and num(first['source']) not in (0, 0x61003c, 0xffffffff), 'native queue/request missing')
    for index, row in enumerate(group):
        f = row['fields']
        check(num(f['pid']) == pid and num(f['tid']) == num(f['sender_tid']) == tid and num(f['op']) == op and
              num(f['source']) == num(first['source']) and num(f['request']) == request_pointer and
              num(f['unit']) == (unit if op in (0x20, 0x21) else 0) and
              num(f['handle']) == (0 if op == 0x20 else handle) and num(f['dropped']) == 0 and
              api.raw_hex(f, 'request_raw', 40) == request and num(f['send_seen']) == int(index >= 1) and
              f['send_rc'] == '0' and num(f['received']) == int(index >= 2) and
              num(f['active']) == int(index != 3) and num(f['free_attempts']) == int(index == 3) and
              f['free_rc'] == '0' and f.get('capture_verified') == '0', 'original ticket transport/free state differs')
        if index >= 2:
            check(num(f['reply_source']) == 0x61003c and num(f['reply_bytes']) == 40 and num(f['reply']) != 0 and
                  f['reply'] == group[-1]['fields']['reply'] and api.raw_hex(f, 'reply_raw', 40) == wire_reply,
                  'original ticket source/reply bytes differs')
    return group[0]['line'], group[-1]['line']


def proc_pair(api, rows, end, pid, tid, birth, passes, packet):
    """Decode the actual retained raw row from both successful complete proc reads."""
    check, need, num = api.require, api.needed, api.number
    values, previous = [], end
    # Each successful READ is immediately followed by its own ordered row chunks.
    for phase in reversed(passes):
        reads = [r for r in rows if r['line'] < previous and r['tag'] == 'FUNCTIONAL_FACE_DMM_PROC_READ' and
                 r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
                 r['fields'].get('birth_observation') == str(birth) and r['fields'].get('pass') == str(phase)]
        need(bool(reads), f'original proc pass{phase} raw READ/ROW birth={birth}')
        read = reads[-1]
        f = read['fields']
        check(f.get('eof') == '1' and f.get('parse_rc') == '0' and num(f['unit']) == packet['unit'] and
              num(f['handle']) == packet['ap_handle'] and 0 < num(f['table_bytes']) <= 2 * 1024**2 and
              f.get('diagnostic_only') == '1' and f.get('atomic_snapshot_verified') == '0' and
              f.get('competing_readers_excluded') == '0', 'proc read failed/promoted/different identity')
        chunks = [r for r in rows if read['line'] < r['line'] < previous and r['tag'] == 'FUNCTIONAL_FACE_DMM_PROC_ROW']
        need(bool(chunks), 'retained actual proc row chunks')
        raw = b''
        length, offset = num(chunks[0]['fields']['row_bytes']), num(chunks[0]['fields']['row_offset'])
        check(0 < length <= 2048 and offset + length <= num(f['table_bytes']), 'proc row bounds differ')
        for chunk in chunks:
            c = chunk['fields']
            count = num(c['chunk_bytes'])
            check(c.get('pid') == str(pid) and c.get('tid') == str(tid) and c.get('pass') == str(phase) and
                  c.get('birth_observation') == str(birth) and num(c['chunk_offset']) == len(raw) and
                  num(c['row_bytes']) == length and num(c['row_offset']) == offset and 0 < count <= 128,
                  'proc row sequence/owner/bounds differs')
            raw += api.raw_hex(c, 'raw', count)
        check(len(raw) == length, 'proc row truncated')
        grammar = (rb'([0-9a-f]{4,})     ([0-9a-f]{8})  ([0-9a-f]{4})    ([0-9a-f]{2})     '
                   rb'([0-9a-f]{2})    ([0-9a-f]{2})    ([0-9a-f]{2})      ([0-9a-f]{8})  '
                   rb'([0-9a-f]{9,16})  ([0-9a-f]{8})  ([0-9a-f]{4})(?: < [0-9a-f]{4}){0,32}')
        match = re.fullmatch(grammar, raw)
        check(match is not None, 'actual proc row grammar/extent differs')
        fields = ('handle', 'unit', 'state', 'owners', 'opens', 'shares', 'generation', 'relation', 'address', 'bytes', 'extent_id')
        value = dict(zip(fields, (int(x, 16) for x in match.groups())))
        value['segments'] = 1
        check(value['handle'] == packet['ap_handle'] and value['unit'] == packet['unit'] and
              value['generation'] == packet['generation'] == value['handle'] >> 10 and
              value['relation'] == packet['relation'] and value['extent_id'] == packet['extent_id'] and
              value['address'] == packet['physical'] and value['bytes'] == packet['length'] and value['shares'] == 0,
              'actual proc allocation identity changed')
        values.append(value)
        previous = read['line']
    check(values[0] == values[1], 'two current proc rows differ')
    return values[0], previous


def guest_content(api, rows, tx, packet, digest):
    check, need, num = api.require, api.needed, api.number
    pid, tid = packet['pid'], packet['tid']
    unit, handle, birth = packet['unit'], packet['ap_handle'], packet['birth']
    allocation = packet['allocation_token']
    check(allocation >> 48 == 0xface and allocation & ((1 << 48) - 1), 'birth-minted face allocation token differs')
    birth_ticket = ticket(api, rows, pid, tid, birth, 0x20, unit, handle)
    born = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_DMM_PROC_BIRTH' and
            r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
            r['fields'].get('birth_observation') == str(birth)]
    need(len(born) == 1, 'one original PROC_BIRTH fact')
    b = born[0]
    need('software_allocation_token' in b['fields'], 'PROC_BIRTH birth-minted software_allocation_token')
    check(birth_ticket[1] < b['line'] and b['fields'].get('capture_rc') == '0' and
          b['fields'].get('observed_at_original_birth') == '1' and
          num(b['fields']['software_allocation_token']) == allocation, 'original birth capture/token failed/order differs')
    born_row, born_start = proc_pair(api, rows, b['line'], pid, tid, birth, (1, 2), packet)
    check(birth_ticket[1] < born_start and (born_row['owners'], born_row['opens'], born_row['state']) == (1, 0, 1),
          'birth proc order/owner/open/state differs')
    for field in born_row:
        if field in b['fields']:
            check(num(b['fields'][field]) == born_row[field], 'PROC_BIRTH summary differs from actual row: ' + field)
    metadata = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_SOURCE_CURRENT_METADATA' and
                r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
                num(r['fields']['unit']) == unit and num(r['fields']['software_allocation_token']) == allocation]
    need(len(metadata) == 6, 'six actual source current-metadata observations')
    observations, starts = [], []
    for row in metadata:
        f = row['fields']
        check(num(f['birth_observation']) == birth and num(f['handle']) == handle and f.get('rc') == '0' and
              f.get('diagnostic_only') == '1' and f.get('native_atomicity_verified') == '0' and
              f.get('original_global_writer_exclusion_verified') == '0' and f.get('capture_verified') == '0',
              'source current-metadata birth/token/status/scope differs')
        value, start = proc_pair(api, rows, row['line'], pid, tid, birth, (3, 4), packet)
        for field in ('relation', 'generation', 'owners', 'opens', 'state', 'address', 'bytes', 'extent_id', 'shares', 'segments'):
            need(field in f, 'CURRENT_METADATA actual allocation field ' + field)
            check(num(f[field]) == value[field], 'metadata summary differs from original row: ' + field)
        observations.append(value)
        starts.append(start)
    base = observations[0]['opens']
    check(base < 255 and [v['owners'] for v in observations] == [1, 2, 2, 2, 2, 1] and
          [v['opens'] for v in observations] == [base, base, base + 1, base + 1, base, base] and
          all(v['state'] == (2 if v['opens'] else 1) for v in observations) and
          b['line'] < starts[0] and all(metadata[i]['line'] < starts[i + 1] for i in range(5)),
          'actual metadata owner/open baseline or observation order differs')
    commands, intervals = [], []
    for index, op in enumerate((0x21, 0x24, 0x25, 0x23)):
        candidates = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_DMM_NATIVE_AP_COMMAND' and
                      r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
                      num(r['fields']['unit']) == unit and num(r['fields']['op']) == op and
                      num(r['fields']['birth_observation']) == birth]
        need(len(candidates) == 1, f'one original native {op:#x} helper capture')
        row, f = candidates[0], candidates[0]['fields']
        check(f.get('capture_rc') == f.get('helper_error') == '0' and f.get('original_api_invoked') == '1' and
              f.get('raw_ticket_capture_only') == '1' and num(f['handle']) == handle,
              'native helper is not successful raw ticket capture')
        observation = num(f['transaction'])
        if index < 2:
            check(observation == packet['share' if index == 0 else 'opened'], 'packet native observation differs')
        a, z = (128, 168) if op == 0x21 else (208, 248)
        request = tx['_packet'][a:a + 40] if index < 2 else None
        if index >= 2:
            actual = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_DMM_AP_OBSERVATION' and
                      r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
                      r['fields'].get('observation') == str(observation)]
            need(bool(actual), 'original native cleanup request bytes')
            queue = num(actual[0]['fields']['source'])
            request = bytearray(struct.pack('<3I', op, 0, handle) + bytes(28))
            if op == 0x23:
                struct.pack_into('<H', request, 20, queue & 0xffff)
            request = bytes(request)
        reply = tx['_packet'][z:z + 40] if index < 2 else None
        interval = ticket(api, rows, pid, tid, observation, op, unit, handle, request, reply)
        check(interval[1] < row['line'], 'native helper capture precedes actual free0')
        commands.append(row)
        intervals.append(interval)
    check(metadata[0]['line'] < intervals[0][0] < commands[0]['line'] < starts[1] and
          metadata[1]['line'] < intervals[1][0] < commands[1]['line'] < starts[2] and
          metadata[2]['line'] < tx['line'] < starts[3] and
          metadata[3]['line'] < intervals[2][0] < commands[2]['line'] < starts[4] and
          metadata[4]['line'] < intervals[3][0] < commands[3]['line'] < starts[5],
          'Share/Open/source bridge/Close/extra-owner Free order differs')
    expected_txn = [num(r['fields']['native_transaction']) for r in metadata]
    check(expected_txn == [packet['share'] - 1, packet['share'], packet['opened'], packet['opened'],
                           num(commands[2]['fields']['transaction']), num(commands[3]['fields']['transaction'])],
          'current metadata native transaction changed/replayed')
    origin = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_DMM_API40_ORIGIN' and
              r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(tid) and
              num(r['fields']['unit']) == unit and num(r['fields']['source_birth']) == birth]
    need(len(origin) == 1, 'one actual original API40 origin')
    f = origin[0]['fields']
    check(f.get('rc') == '0' and f.get('original_caller_bound') == f.get('native_metadata_observed') == '1' and
          num(f['frame']) == packet['frame'] and num(f['api']) == packet['api_pointer'] and
          b['line'] < origin[0]['line'] < starts[0], 'original API40 frame/birth/order differs')
    callback, context = struct.unpack_from('<2Q', tx['_packet'], 328)
    check(num(f['caller']) - callback == 0x35150c8 - 0x3514c88,
          'API40 caller/original callback library offsets differ')
    creators = [r for r in rows if r['line'] < origin[0]['line'] and r['tag'] == 'FUNCTIONAL_FACE_DMM_UNIT' and
                r['fields'].get('pid') == str(pid) and num(r['fields']['unit']) == unit and
                num(r['fields']['handle']) == packet['cp_handle'] and r['fields'].get('live_creator') == '1']
    need(bool(creators), 'actual registered CP creator descriptor')
    c = creators[-1]['fields']
    check(num(c['epoch']) == packet['cp_epoch'] and num(c['registration']) == packet['cp_registration'] and
          num(c['owner']) == packet['owner'] == (pid << 32 | 0x46414345) and num(c['reference']) == 0 and
          num(c['bytes']) == packet['length'] and num(c['mapped_bytes']) == (packet['length'] + 4095) // 4096 * 4096 and
          num(c['logical']) != 0 and num(c['host_view']) % 4096 == 0 and num(c['host_view']) != 0,
          'registered CP creator identity/whole mapped extent differs')
    selected = []
    for suffix in ('CALLBACK_ENTER', 'CALLBACK_RETURN', 'SNAPSHOT_RESULT'):
        candidates = [r for r in rows if r['tag'] == 'FUNCTIONAL_FACE_SOURCE_' + suffix and
                      r['fields'].get('pid') == str(pid) and num(r['fields']['unit']) == unit]
        need(len(candidates) == 1, 'exactly one actual source ' + suffix)
        row, f = candidates[0], candidates[0]['fields']
        check(num(f['tid']) == tid and num(f['allocation_token']) == allocation and
              num(f['model_instance']) == tx['model_instance'] and num(f['snapshot_token']) == tx['token'] and
              num(f['source_fnv']) == num(f['cp_fnv']) == int(digest, 16) and
              f.get('original_sender_started') == f.get('capture_verified') == '0',
              'actual callback/result allocation/model/token/FNV/scope differs')
        if suffix != 'SNAPSHOT_RESULT':
            check(num(f['callback']) == callback != 0 and num(f['context']) == context != 0 and
                  f.get('actual_original_callback') == f.get('content_readback_complete') == '1',
                  'actual original callback address/context/content differs')
            if suffix == 'CALLBACK_RETURN':
                check(f.get('actual_original_callback_returned') == '1', 'original callback did not actually return')
        else:
            check(f.get('rc') == '0' and all(f.get(k) == '1' for k in ('claimed', 'started',
                    'original_callback_invoked', 'original_callback_returned')) and
                  all(num(f[k]) == packet['length'] for k in ('source_bytes', 'cp_written', 'cp_readback')) and
                  f.get('original_global_writer_exclusion_verified') == f.get('physical_ASIC_verified') == '0',
                  'actual source/CP write/independent READ/callback result incomplete/promoted')
        selected.append(row)
    check(metadata[-1]['line'] < selected[0]['line'] < selected[1]['line'] < selected[2]['line'],
          'early/duplicate callback or result before return')
    return dict(original_tickets_verified=True, metadata_baseline_verified=True, baseline_opens=base,
                actual_CP_content_readback_verified=True, actual_original_callback_returned=True,
                callback=callback, context=context, birth_observation=birth)


def check(run, manifest, rows, events, transport, api):
    result = empty()
    if not observed(rows, events):
        return result
    result = empty('incomplete')
    try:
        api.needed(transport is not None and transport.get('verified') is True,
                   'same-run closed broker transport from current frozen batch')
        fields = ('functional_camera_cp_face_dmm_functional_source_snapshot_policy',
                  'functional_camera_cp_face_dmm_functional_source_snapshot_verified',
                  'functional_camera_cp_face_dmm_original_global_writer_exclusion_verified')
        for container in (manifest, manifest.get('backup_transport', {})):
            api.require(container.get(fields[0]) == POLICY and container.get(fields[1]) is False and
                        container.get(fields[2]) is False, 'explicit source software profile/scope differs')
        source = api.source_module(api.RUNTIME / 'functional_face_source_snapshot.py')
        api.require((source.OP, source.ORIGIN, source.BASE_BYTES, source.FRAME_BYTES) == (11, 1, 360, 224),
                    'source parser does not match fixed OP11/flag1/BASE360 ABI')
        mailbox = events[0]['mailbox']
        transfers = [tx for tx in transport['transfers'] if tx['opcode'] == 11]
        api.needed(bool(transfers), 'actual consumed OP11 source transfer')
        used_allocations, used_tokens = set(), set()
        for transfer in transfers:
            tx = dict(transfer, _run=run)
            request = [e for e in events if e.get('kind') == 'request' and e.get('sequence') == tx['first']]
            api.require(len(request) == 1, 'source request missing/duplicate')
            header = bytes.fromhex(request[0]['raw_header_hex'])
            raw = api.payload_read(run, tx['request_payload'])
            packet = source.packet(raw, header, mailbox)
            packet.update(pid=source.number(raw, 116), tid=source.number(raw, 120))
            tx['_packet'] = raw
            api.require(tx['origin'] == dict(producer_tid=packet['tid'], source=packet['ap_handle'],
                        destination=packet['cp_handle'], command=source.COMMAND, bytes=40, fnv1a64=packet['api_fnv']) and
                        packet['allocation_token'] not in used_allocations and tx['token'] not in used_tokens,
                        'same API40 origin or allocation/snapshot reuse differs')
            used_allocations.add(packet['allocation_token'])
            used_tokens.add(tx['token'])
            content, snapshot = host_content(api, source, packet, tx, events, mailbox)
            guest = guest_content(api, rows, tx, packet, content['fnv1a64'])
            result['transactions'].append(dict(unit=packet['unit'], allocation_token=packet['allocation_token'],
                snapshot_token=tx['token'], first=tx['first'], last=tx['last'], **content, **guest))
        result['content_joins_verified'] = True
        result['status'] = 'incomplete' if result['missing'] else 'complete'
        result['verified'] = not result['missing']
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, OverflowError, struct.error) as error:
        missing = isinstance(error, (api.MissingEvidence, FileNotFoundError))
        result['status'] = 'incomplete' if missing else 'invalid'
        result['missing'].append(dict(code='TRACE_MISSING' if missing else 'EVIDENCE_INVALID',
                                      detail=f'{type(error).__name__}: {error}'))
    return result


def evaluate(run, batch):
    import types
    path = Path(__file__).with_name('check_evidence.py')
    api = types.ModuleType('_face_source_capture_reader')
    api.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), api.__dict__)
    result = api.evaluate(run, batch)
    source = result['evidence'].get(STAGE)
    if source is None:
        source = empty('incomplete')
        source['missing'] = result.get('missing') or [dict(code='TRACE_MISSING', detail='source stage unavailable')]
    return dict(schema='functional-face-source-evidence-v1', **source, capture_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('batch', type=Path)
    args = parser.parse_args()
    result = evaluate(args.run, args.batch)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
