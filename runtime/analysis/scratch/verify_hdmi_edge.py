#!/usr/bin/env python3
"""Read-only HDMI11 content checks, using the existing checker's Log interface.

verify_hdmi_effects(log) checks actual virtual-owner effects (also host C traces).
verify_hdmi_upm(log, run) independently joins the two real kernel retirements;
it deliberately does not assert that conditions or the AP edge completed.
verify_hdmi_edge(log, previous_free, identity, first_graph_request, run) requires
both, plus constructor and canonical Get retirements. The outer verifier owns
build/source identity, prior edges, resource locks, SD, and whole-run cleanup.
No function writes an artifact, starts a process, or accesses a VM/socket.
"""
# SPDX-License-Identifier: MIT
import hashlib
import importlib.util
from pathlib import Path
import struct

BASE = Path(__file__).resolve().parents[1]
PREFIX = 'FULL_PINMEM_HDMI_VIDEO_CONNECT'
STATE = 'FULL_HDMI_VIDEO_STATE'
PROFILE = 'virtual-pinmem-video0-hdmi-video0-initializing-v1'
S = (4, 2, 0, 0x90590818)
P = (4, 1, 0, 0x909a015a)
TOKEN = 0x504d4000
UPM = 0x80920572
CONDITION_SOURCE = 0x91ca0816
CONDITION_SID = 0x802a0116
IDS = (0, 0x17, 0x16, 0x15, 0x14, 0x13, 0x12, 0x11, 0x23, 0x22, 0x21, 0x30)
_WATCH = None


def require(value, reason):
    if not value:
        raise ValueError('HDMI11: ' + str(reason))


def eq(record, **expected):
    for key, value in expected.items():
        require(record['fields'].get(key) == str(value),
                (record['tag'], record['line'], key, record['fields'].get(key), value))
    return record


def number(row, key):
    return int(row['fields'][key], 0)


def one(log, tag):
    rows = log.rows(tag)
    require(len(rows) == 1, (tag, 'expected exactly one record', len(rows)))
    return rows[0]


def raw(row, size):
    eq(row, bytes=size)
    data = bytes.fromhex(row['fields']['raw'])
    require(len(data) == size and data.hex() == row['fields']['raw'], 'noncanonical/incomplete raw bytes')
    return data


def frame(size, command, flags, words, caller=0, opaque=bytes(4)):
    result = bytearray(size)
    struct.pack_into('<IIHHII', result, 0, caller, 0xa0a0a0a0, 1, size, 24, size)
    result[20:24] = opaque
    struct.pack_into('<4H', result, 24, 0x1000, command, size - 24, flags)
    struct.pack_into('<' + 'I' * len(words), result, 32, *words)
    return bytes(result)


def fnv(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f'{value:016x}'


def _watch():
    global _WATCH
    if _WATCH is None:
        spec = importlib.util.spec_from_file_location('_hdmi11_receipt_reader', BASE / 'hdmi_upm_watch.py')
        _WATCH = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_WATCH)
    return _WATCH


def _kind(log, suffix, kind):
    return [r for r in log.rows(STATE + '_' + suffix) if r['fields'].get('kind') == str(kind)]


def _leases(log, kind, native=False):
    """Match serials, not addresses: reuse after a complete lifetime is legal."""
    published = _kind(log, 'MESSAGE_PUBLISHED', kind)
    sent = _kind(log, 'MESSAGE_SENT', kind)
    retired = _kind(log, 'KERNEL_RETIRED' if native else 'NATIVE_FREE', kind)
    require(len(published) <= {1: 3, 2: 24, 3: 2}[kind], ('message bound exceeded', kind))
    require(len(published) == len(sent) == len(retired), ('incomplete message lifetimes', kind))
    serials = [number(r, 'lease') for r in published]
    require(all(s > 0 for s in serials) and len(set(serials)) == len(serials), 'repeated message lease')
    require({number(r, 'lease') for r in sent} == set(serials) ==
            {number(r, 'lease') for r in retired}, 'sent/free lease set differs')
    result = []
    for p in published:
        serial = p['fields']['lease']
        ss = [r for r in sent if r['fields']['lease'] == serial]
        ff = [r for r in retired if r['fields']['lease'] == serial]
        require(len(ss) == len(ff) == 1, 'duplicate message send/free')
        s, f = ss[0], ff[0]
        for row in (p, s, f):
            eq(row, pointer=p['fields']['pointer'], destination=p['fields']['destination'],
               lease=serial, kind=kind, bytes=p['fields']['bytes'], rc=0)
        eq(s, source=p['fields']['source'], index=p['fields']['index'], raw=p['fields']['raw'], tid=p['fields']['tid'])
        require(number(p, 'pointer') > 0 and p['line'] < s['line'] and p['line'] < f['line'], 'message publish/send/free order')
        if native:
            eq(f, source=p['fields']['source'], index=p['fields']['index'], raw=p['fields']['raw'], tid=p['fields']['tid'])
            require(f['line'] < s['line'], 'native retirement must precede sent note')
        else:
            eq(f, sender=p['fields']['tid'], receiver=f['fields']['tid'], received=1, consumed=1)
        result.append({'published': p, 'sent': s, 'freed': f})
    for index, item in enumerate(result):
        p = item['published']
        for earlier in result[:index]:
            if number(p, 'pointer') == number(earlier['published'], 'pointer'):
                require(max(earlier['sent']['line'], earlier['freed']['line']) < p['line'], 'live message address reused')
    return result


def verify_conditions(log):
    """Require two exact batches and all 24 same-thread native frees, by serial."""
    for record in log.records:
        if record['tag'].startswith((PREFIX + '_', STATE + '_')):
            require(not any(word in record['tag'] for word in ('FAULT', 'REJECT', 'UNSUPPORTED', 'REFUSED')),
                    ('fault/rejection prevents condition acceptance', record))
    messages = _leases(log, 2)
    require(len(messages) == 24, 'requires all 24 condition receives/frees')
    tids = set()
    indices = tuple(range(11)) + (12,)
    for item, index, cid in zip(messages, indices + tuple(i + 13 for i in indices), IDS * 2):
        p, f = item['published'], item['freed']
        eq(p, source=hex(CONDITION_SOURCE), destination=hex(CONDITION_SID), index=index)
        require(raw(p, 20) == struct.pack('<5I', 2, cid, 1, 0, 0), 'condition ID/value/raw bytes differ')
        require(number(f, 'tid') > 1, 'invalid condition receiver TID')
        tids.add(f['fields']['tid'])
    require(len(tids) == 1, 'conditions not consumed by one actual receiver thread')
    return {'messages': messages, 'receiver_tid': next(iter(tids)),
            'condition_model_events_verified': False, 'scope': '24 received=1 same-thread native frees; no model-publication claim'}


def verify_hdmi_effects(log):
    """Actual C effects only; host UPM frees are explicitly not native proof."""
    allowed = {'PROFILE', 'UNADMITTED', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE',
        'RESOURCES_RESERVED', 'REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'EVENT6_ENQUEUED',
        'EVENT6_CONSUMED', 'VIDEO_MANAGER', 'INTERNAL_FREE', 'REPLY_QUEUED',
        'REQUEST_FREE', 'STATE_READBACK', 'NATIVE_REPLY_FREE'}
    state_allowed = {'MESSAGE_PUBLISHED', 'MESSAGE_SENT', 'NATIVE_FREE', 'KERNEL_RETIRED',
                     'DRIVER_CONSUMED', 'PENDING'}
    scoped = [r for r in log.records if r['tag'].startswith((PREFIX + '_', STATE + '_'))]
    require(scoped, 'missing edge evidence')
    for row in scoped:
        root = PREFIX if row['tag'].startswith(PREFIX + '_') else STATE
        require(row['tag'][len(root) + 1:] in (allowed if root == PREFIX else state_allowed),
                ('fault/reject/unsupported/unexpected effect', row))
        for key in ('original_CP_executed', 'original_cp_executed', 'hardware_verified',
                    'frames_verified', 'capture_verified', 'original_RTOS_scheduling_verified'):
            if key in row['fields']:
                eq(row, **{key: 0})
    tags = ('REQUEST', 'PEER_REQUEST', 'EVENT6_ENQUEUED', 'PEER_REPLY', 'EVENT6_CONSUMED',
            'VIDEO_MANAGER', 'REPLY_QUEUED', 'REQUEST_FREE', 'STATE_READBACK', 'NATIVE_REPLY_FREE')
    edge = {tag: one(log, PREFIX + '_' + tag) for tag in tags}
    req = raw(edge['REQUEST'], 64)
    caller = struct.unpack_from('<I', req)[0]
    require(caller >> 28 == 8 and caller & 0xfffffff, 'invalid dynamic AP sender SID')
    require(req == frame(64, 1, 2, S + P, caller, req[20:24]), 'original request differs')
    identity = (edge['REQUEST']['fields']['pid'], edge['REQUEST']['fields']['producer_tid'])
    require(all(int(v) > 1 for v in identity), 'invalid AP PID/TID')
    eq(edge['REQUEST'], source=hex(caller), destination=hex(S[3]))
    for tag, size, command, flags, source, destination, words in (
            ('PEER_REQUEST', 64, 0x100, 1, S[3], P[3], S + P),
            ('PEER_REPLY', 72, 0x8100, 1, P[3], S[3], S + P + (0, 0)),
            ('REPLY_QUEUED', 56, 0x8001, 2, S[3], caller, S + (0, 0))):
        row = edge[tag]
        eq(row, pid=identity[0], source=hex(source), destination=hex(destination))
        require(number(row, 'producer_tid') > 1, 'missing actual producer TID')
        require(raw(row, size) == frame(size, command, flags, words), ('wire differs', tag))
    final = edge['NATIVE_REPLY_FREE']
    eq(final, pid=identity[0], tid=identity[1], sender=identity[1], waiter=1,
       producer_tid=edge['REPLY_QUEUED']['fields']['producer_tid'], destination=hex(caller),
       expected=hex(caller), reply=edge['REPLY_QUEUED']['fields']['pointer'], bytes=56,
       command='0x8001', rc=0, faults=0, ap_consumed=1)
    eq(edge['REQUEST_FREE'], owner=hex(S[3]), pointer=edge['REQUEST']['fields']['pointer'], bytes=64, rc=0)
    pointers = [number(edge[tag], 'pointer') for tag in ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY')]
    require(all(p > 0 for p in pointers) and len(set(pointers)) == 3 and
            number(edge['REPLY_QUEUED'], 'pointer') > 0 and
            number(edge['REPLY_QUEUED'], 'pointer') != pointers[0], 'live handshake allocations alias')
    eq(edge['EVENT6_ENQUEUED'], event=6, parameter_bytes=12, token_policy='owned-answer-plus24-map',
       phase=1, wait_primary=6, keep_pending=1, peer_posthandler_pending=1,
       original_CP_event_pointer_identity_verified=0)
    eq(edge['EVENT6_CONSUMED'], consumer_raw='0x5dd814', source_complete_raw='0x5839a6',
       parameter_bytes=12, parameter_fnv=fnv(struct.pack('<I', TOKEN) + bytes(8)),
       saved_request_fnv=fnv(req), token=hex(TOKEN), actual_parameter_read=1,
       full_peer_u32_verified=4, status=0, tail=0, consumed=1, pending=0)
    eq(edge['VIDEO_MANAGER'], selector_raw='0xf749c', manager_raw='0x5d55c0', object_raw='0x10f5004',
       vptr_raw='0xd27080', method_offset='0xc', gate_load_raw='0x5d55ce', gate_offset='0x6a',
       gate_ctor_known=1, gate=0, gate_reset_at_connect=0, typed_callback_called=1,
       DMM=0, notifications=0, clocks=0, markers=0)
    eq(edge['STATE_READBACK'], source_slot=7, peer_slot=0, source_state=0, peer_state=0,
       source_pending=0, event6_consumed=1, source_gate=0, peer_state_ready=1,
       AP_reply_after_peer_and_source_callbacks=1, pixels_consumed=0)
    ordered = [edge[t]['line'] for t in tags[:-1]]
    require(ordered == sorted(set(ordered)), 'request/event/callback/publication order')
    # send() may wake the AP before its producer writes REPLY_QUEUED.
    require(edge['VIDEO_MANAGER']['line'] < final['line'], 'AP free preceded source callback')
    frees = log.rows(PREFIX + '_INTERNAL_FREE')
    require(len(frees) == 2, 'expected two peer storage frees')
    for tag, low, high in (('PEER_REQUEST', edge['EVENT6_ENQUEUED']['line'], edge['PEER_REPLY']['line']),
                           ('PEER_REPLY', edge['VIDEO_MANAGER']['line'], edge['REPLY_QUEUED']['line'])):
        matches = [r for r in frees if r['fields'].get('pointer') == edge[tag]['fields']['pointer'] and low < r['line'] < high]
        require(len(matches) == 1, ('peer lifetime differs', tag))
        eq(matches[0], owner=hex(caller), rc=0)
    conditions = verify_conditions(log)
    condition = conditions['messages']
    native = bool(_kind(log, 'KERNEL_RETIRED', 3))
    require(not (native and _kind(log, 'NATIVE_FREE', 3)), 'UPM has a second user-space owner/free')
    upm = _leases(log, 3, native)
    require(len(upm) == 2, 'requires two UPM retirements')
    for index, item in enumerate(upm):
        p = item['published']
        eq(p, source=hex(P[3]), destination=hex(UPM), index=index)
        require(raw(p, 16) == struct.pack('<4I', 0x00920117, index * 2, 0x009a0000, 0), 'UPM raw body differs')
    driver = one(log, STATE + '_DRIVER_CONSUMED')
    eq(driver, virtual_resource=1, job=6, slot=4, row=0, column=8, policy=0,
       completion='070000000000000000000000', same_owner_op1_read=1, node_freed=1,
       original_cp_executed=0, hardware_verified=0)
    require(len(bytes.fromhex(driver['fields']['initialization'])) == 18 and
            len(bytes.fromhex(driver['fields']['config'])) == 36, 'driver initialization/config size differs')
    require(edge['REQUEST']['line'] < driver['line'] < upm[0]['published']['line'] and
            (not native or upm[-1]['freed']['line'] < condition[0]['published']['line']) and
            max(max(x['sent']['line'], x['freed']['line']) for x in condition + upm) < edge['PEER_REPLY']['line'],
            'peer reply preceded actual A consumers')
    serials = [number(r, 'lease') for r in log.rows(STATE + '_MESSAGE_PUBLISHED')]
    require(len(serials) == len(set(serials)), 'lease reused across kinds')
    early = log.rows(PREFIX + '_UNADMITTED')
    for row in early:
        require(row['line'] < edge['REQUEST']['line'], 'late unadmitted request')
        eq(row, **{k: v for k, v in {'requests': 0, 'faults_unchanged': 1}.items() if k in row['fields']})
    edge.update(REQUEST=edge['REQUEST'], REPLY_FREE=final, identity=identity, caller=caller,
        source_pin=S, sink_pin=P, internal_frees=frees, condition_messages=condition, UPM_messages=upm,
        condition_receiver_tid=conditions['receiver_tid'], driver=driver, native_UPM_join_required=native,
        early_unadmitted_requests=early, scope='offline actual C effects; native admission/UPM proof not asserted',
        condition_model_events_verified=False, transition_order_runtime_logged=False,
        prior_cache_readback_runtime_logged=False, unknown_request_padding=req[20:24].hex(),
        original_CP_executed=False, original_RTOS_scheduling_verified=False,
        hardware_verified=False, frames_verified=False, capture_verified=False)
    return edge


def verify_hdmi_upm(log, run, identity=None, upm_effective_second=3):
    """Join actual native events and committed mailbox payloads; no full-edge claim."""
    w = _watch()
    receipts = w.read_receipts(run)
    require(len(receipts) == 2, 'requires exactly two validated native UPM receipts')
    root, _ = w.validate_run(run)
    config = w.parse_json(w.checked_read(root / (w.PREFIX + '-config.json'), 16384))
    result = w.parse_json(w.checked_read(root / (w.PREFIX + '-result.json'), 16384))
    coordinator = w.parse_json(w.checked_read(root / 'hdmi-upm-coordinator.json', 1024 * 1024))
    require(result.get('detached') is True and not result.get('error') and result.get('receipts') == 2 and
            result.get('dedicated_receipt_transport') is True and result.get('observations_only') is False,
            'native observer did not complete/detach cleanly')
    cleanup = coordinator.get('cleanup', {})
    require(coordinator.get('armed') is True and not coordinator.get('error') and not coordinator.get('cleanup_error') and
            cleanup.get('safe_to_close') is True and cleanup.get('detached') is True and
            cleanup.get('debugger_stopped') is True and not cleanup.get('errors'), 'native coordinator cleanup unsafe')
    deliveries = result.get('mailbox_deliveries', [])
    require(len(deliveries) == 2, 'requires both GDB mailbox commits')
    require(config['context']['module_sha256'] == w.SHAS, 'original module hashes differ')
    items = _leases(log, 3, native=True)
    require(len(items) == 2 and not _kind(log, 'NATIVE_FREE', 3), 'UPM requires only two kernel retirements')
    init = one(log, 'FULL_HDMI_UPM_MAILBOX_INIT')
    prepare = one(log, 'FULL_HDMI_UPM_MAILBOX_PREPARE')
    consumed = log.rows('FULL_HDMI_UPM_MAILBOX_CONSUMED')
    require(len(consumed) == 2 and not log.rows('FULL_HDMI_UPM_MAILBOX_REJECT'), 'guest did not consume both receipts')
    owner = str(identity[0]) if identity is not None else init['fields']['pid']
    mailbox = {'phys': number(init, 'physical'), 'nonce': number(init, 'nonce'), 'pid': int(owner)}
    w.mailbox_header(mailbox)
    require(config.get('mailbox') == mailbox, 'mailbox actual pagemap/nonce/PID differs from observer config')
    texts = {'upm': number(init, 'upm_text'), 'osal_uipc': number(init, 'osal_text')}
    require(texts == config['context']['module_texts'], 'actual module text bases differ')
    events = [w.parse_json(line) for line in w.checked_read(root / (w.PREFIX + '-events.jsonl'), 1024 * 1024).splitlines()]
    require(upm_effective_second in (2, 3), 'unknown UPM effective second ID')
    for index, (receipt, item, start, end, delivery) in enumerate(zip(receipts, items, (init, prepare), consumed, deliveries)):
        p, retired, sent = item['published'], item['freed'], item['sent']
        raw_body = struct.pack('<4I', 0x00920117, index * 2, 0x009a0000, 0).hex()
        effective = struct.pack('<4I', 0x00920117, upm_effective_second if index else 0, 0x009a0000, 0).hex()
        require(receipt['order'] == index + 1 and receipt['raw_hex'] == raw_body and receipt['effective_hex'] == effective and
                receipt['source'] == P[3] and receipt['u'] == number(p, 'pointer') and
                receipt['lease_serial'] == number(p, 'lease') and receipt['a_lease_binding_verified'] is True and
                receipt['native_allocation_retired'] is True, 'native receipt/A lease U/raw/order binding differs')
        require(receipt['producer_tid'] == number(p, 'tid') and receipt['tid'] != receipt['producer_tid'] and
                receipt['task'] != receipt['producer_task'], 'native task/actual producer binding differs')
        for row in (start, end):
            eq(row, pid=owner, tid=p['fields']['tid'], bytes=4096, version=1, record_bytes=256,
               lease=p['fields']['lease'], U=hex(receipt['u']), index=index, raw=raw_body, effective=effective,
               physical=init['fields']['physical'], nonce=init['fields']['nonce'], user_va=init['fields']['user_va'],
               upm_text=init['fields']['upm_text'], osal_text=init['fields']['osal_text'])
        require(p['line'] < start['line'] < end['line'] < retired['line'] < sent['line'], 'guest mailbox/retirement chronology differs')
        require(number(start, 'user_va') % 4096 == 0, 'mailbox user page not aligned')
        bridges = [e for e in events if e['kind'] == 'bridge' and e['seq'] == receipt['bridge_seq']]
        require(len(bridges) == 1, 'native receipt missing exact original bridge event')
        request = bytes.fromhex(bridges[0]['memory']['mailbox_record']['hex'])
        committed = w.mailbox_payload(mailbox, request, receipt)
        require(delivery == {'bridge_seq': receipt['bridge_seq'], 'lease_serial': receipt['lease_serial'],
                            'record_sha256': hashlib.sha256(committed).hexdigest()}, 'GDB mailbox commit/bridge/free sequence differs')
        if index:
            require(receipt['bridge_seq'] > receipts[0]['events']['free_return'] and
                    receipt['lease_serial'] > receipts[0]['lease_serial'] and
                    items[0]['sent']['line'] < p['line'], 'native lifetime reused before final retirement')
    return {'receipts': receipts, 'mailbox': init, 'guest_consumed': consumed,
            'GDB_result': result, 'coordinator': coordinator,
            'scope': 'two native UPM lifetimes only; no condition/AP completion claim',
            'native_UPM_verified': True, 'full_edge_verified': False}


def _get(log, key, identity, caller, after, before):
    owner, slot = ('PINMEM', 7) if key == S else ('HDMIPIN', 0)
    prefix = 'FULL_' + owner
    requests = [r for r in log.rows(prefix + '_REQUEST') if after < r['line'] < before and
                r['fields'].get('tid') == identity[1] and struct.unpack_from('<3I', raw(r, 48), 32) == key[:3]]
    require(len(requests) == 1, ('missing/duplicate canonical Get', key))
    request = requests[0]
    data = raw(request, 48)
    eq(request, source=hex(caller), destination=hex(key[3]), reply_destination=hex(caller))
    require(data == frame(48, 0, 2, key[:3] + (0,), caller, data[20:24]), 'canonical Get original bytes differ')
    replies = [r for r in log.rows(prefix + '_REPLY_QUEUED') if request['line'] < r['line'] < before and
               r['fields'].get('tid') == identity[1] and struct.unpack_from('<3I', raw(r, 56), 32) == key[:3]]
    require(len(replies) == 1, 'missing/duplicate canonical Get reply')
    reply = replies[0]
    eq(reply, source=hex(key[3]), destination=hex(caller))
    require(raw(reply, 56) == frame(56, 0x8000, 2, key[:3] + (1, key[3], 0)), 'canonical Get returned full key/state differs')
    pointer, lease = reply['fields']['reply'], reply['fields']['lease']
    require(int(pointer, 0) > 0 and int(lease) > 0, 'canonical Get lacks actual allocation/lease')
    commits = [r for r in log.rows(prefix + '_COMMIT') if r['fields'].get('lease') == lease]
    frees = [r for r in log.rows(prefix + '_NATIVE_REPLY_FREE') if r['fields'].get('lease') == lease]
    require(len(commits) == len(frees) == 1, 'canonical Get commit/free count differs')
    commit, freed = commits[0], frees[0]
    eq(commit, tid=identity[1], slot=slot, type=key[0], dir=key[1], index=key[2], pin_state=1,
       owner=hex(key[3]), status=0, reply=pointer, lease=lease, request_free_rc=0,
       connect_performed=0, pixels_consumed=0, camera_startup_verified=0)
    eq(freed, tid=identity[1], sender=identity[1], waiter=1, destination=hex(caller),
       expected=hex(caller), reply=pointer, lease=lease, bytes=56, rc=0)
    require(request['line'] < reply['line'] < commit['line'] < freed['line'] < before, 'Get not actually retired before connect')
    queries = [r for r in log.rows('PIN_QUERY') if after < r['line'] < request['line'] and
               r['fields'].get('tid') == identity[1] and r['fields'].get('raw') == data.hex()]
    require(len(queries) == 1, 'canonical Get lacks original AP query')
    eq(queries[0], source=hex(caller), destination=hex(key[3]), bytes=48)
    return {'key': key, 'original_AP_query': queries[0], 'request': request, 'reply': reply,
            'commit': commit, 'actual_same_sender_free': freed}


def _backup(log, edge):
    """Public CP bytes are reproducible; dynamic AP bytes remain runtime output."""
    keys = (0x010d008d, 0x003e0005, 0x009a0001, 0x009a0009, 0x009a000a,
            0x009a000b, 0x009a000c, 0x010704fd, 0x00920085)
    capacities = (1, 17, 28, 1, 1, 1, 4, 1, 8)
    records = [r for r in log.rows('FULL_HDMI_VIDEO_BACKUP_READ')
               if edge['REQUEST']['line'] < r['line'] < edge['driver']['line']]
    require(tuple(number(r, 'key') for r in records) == keys, 'actual Backup read keys/order/count differ')
    reader_path = BASE.parents[1] / 'report/cp3006-start/verify_public_seed.py'
    spec = importlib.util.spec_from_file_location('_hdmi11_public_seed_reader', reader_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    public = reader.verify(BASE / 'menu-root/seed-backup.bin', keys[2:8])
    bank = public['records'][1]
    require(bank['offset'] == 0xed000 and bank['checksum_verified'], 'public CP bank identity differs')
    for record, key, capacity in zip(records, keys, capacities):
        eq(record, pid=edge['identity'][0], tid=edge['UPM_messages'][0]['published']['fields']['tid'],
           capacity=capacity, capture_verified=0)
        stored, rc = number(record, 'stored_bytes'), number(record, 'rc')
        if key in keys[2:8]:
            value = bank['keys'][f'{key:08x}']
            eq(record, source='pinned-public-CP-bank', bank_offset='0xed000', AP_runtime_value_claimed=0,
               stored_bytes=value['bytes'] if value['present'] else 0,
               rc=0 if value['present'] else 1, verified_absent=0 if value['present'] else 1)
        else:
            eq(record, private_bytes_logged=0, verified_absent=0)
            require('source' not in record['fields'], 'AP runtime read mislabeled as CP seed')
            if rc == 0:
                require(stored >= 0, 'successful AP Backup read has negative size')
                copied = min(stored, capacity)
                eq(record, copy_bytes=copied,
                   reason='bounded-read-complete' if copied else 'present-no-copy')
                if copied:
                    eq(record, read_rc=copied)
            else:
                require(key != 0x00920085 and rc < 0, 'required UPM AP Backup read failed')
        if key == 0x00920085:
            require(rc == 0 and 5 <= stored <= 8, 'UPM second-ID source unavailable')
    config = bytes.fromhex(bank['keys']['009a0001']['data']).ljust(28, b'\0')
    require(bytes.fromhex(edge['driver']['fields']['config']) == bytes(8) + config,
            'driver config not derived from actual pinned public CP input')
    initialization = bytes.fromhex(edge['driver']['fields']['initialization'])
    require(initialization[0] in (5, 6), 'driver initialization enum differs')
    model = records[1]
    if number(model, 'rc') == 0:
        copied = min(number(model, 'stored_bytes'), 17)
        require(initialization[1 + copied:] == bytes(17 - copied), 'initialization model tail not zero-filled')
    return {'reads': records, 'public_CP_bank_verified': True,
            'AP_runtime_bytes_independently_logged': False,
            'AP_runtime_basis': 'actual size/read return metadata and driver-consumed bytes; outer frozen reader required'}


def verify_hdmi_edge(log, previous_free, identity, first_graph_request, run):
    """Require all virtual effects plus same-run native UPM/condition/AP proof."""
    edge = verify_hdmi_effects(log)
    identity = tuple(map(str, identity))
    require(edge['identity'] == identity, 'original AP PID/TID differs')
    start = edge['REQUEST']['line']
    require(first_graph_request <= previous_free < start, 'graph/predecessor bounds differ')
    for row in edge['early_unadmitted_requests']:
        require(row['line'] < first_graph_request, 'unadmitted request during/after graph phase')
    profiles = [r for r in log.rows(PREFIX + '_PROFILE') if r['fields'].get('pid') == identity[0]]
    require(len(profiles) == 1, 'missing/duplicate original AP constructor profile')
    profile = profiles[0]
    eq(profile, requested=PROFILE, enabled=1, first_missing='none', owner_pid=identity[0], initialized=1,
       hdmi_owner_pid=identity[0], hdmi_initialized=1, hdmi_state=1, initializing=1,
       hdmi_history_known=1, source_gate_known=1, source_gate=0, source_history_known=1, before_any_input=1)
    inputs = log.rows('HDMI_PHOTO_REQUEST')
    require(profile['line'] < first_graph_request and inputs and profile['line'] < min(r['line'] for r in inputs),
            'constructor was not before all HDMI input')
    gets = [_get(log, key, identity, edge['caller'], previous_free, start) for key in (S, P)]
    require(gets[0]['actual_same_sender_free']['line'] < gets[1]['request']['line'], 'source Get not retired before peer Get')
    require(edge['native_UPM_join_required'], 'host user-space UPM observations cannot prove native consumption')
    upm = verify_hdmi_upm(log, run, identity)
    backup = _backup(log, edge)
    prefix = _leases(log, 1)
    require(len(prefix) == 3, 'requires all three native prefix reply retirements')
    for item, command, value in zip(prefix, (0x102, 0x109, 0x127), (1, 0, CONDITION_SID)):
        p = item['published']
        requests = [r for r in inputs if r['fields'].get('command') == hex(command) and r['line'] < p['line']]
        require(len(requests) == 1, 'prefix lacks unique actual AP input')
        request = requests[0]
        eq(request, tid=identity[1], frame='0x2500', bytes=12, flags='0x1')
        require(number(request, 'value') == value, 'prefix input payload differs')
        eq(p, source=hex(P[3]), destination=request['fields']['source'], index=command)
        require(raw(p, 12) == struct.pack('<4HI', 0x2500, command | 0x8000, 12, 1, 0), 'prefix reply/status differs')
        require(max(item['sent']['line'], item['freed']['line']) < start, 'prefix not retired before connection')
    require(len(log.rows(STATE + '_MESSAGE_PUBLISHED')) == 29 and
            len(log.rows(STATE + '_MESSAGE_SENT')) == 29 and
            len(log.rows(STATE + '_NATIVE_FREE')) == 27 and
            len(log.rows(STATE + '_KERNEL_RETIRED')) == 2, 'full A lease census differs')
    subscriptions = [r for r in inputs if r['fields'].get('command') == '0x127' and r['line'] < start]
    require(len(subscriptions) == 1, 'requires actual single 0127 subscription')
    subscription = subscriptions[0]
    eq(subscription, tid=identity[1], frame='0x2500', bytes=12, flags='0x1', value=hex(CONDITION_SID))
    require(number(subscription, 'source') != CONDITION_SID, 'condition SID confused with original request source')
    receiver = edge['condition_receiver_tid']
    sites = [r for r in log.rows('RCV_SITE') if r['fields'].get('tid') == receiver and
             r['fields'].get('queue') == hex(CONDITION_SID)]
    # The production console filter omits RCV_*; received=1 is recorded by A's
    # frozen observe-after-real-receive hook before its same-thread real free.
    if sites:
        require(len(sites) == 1 and sites[0]['fields'].get('caller', '').endswith('/appFw.so+0x34e3fc4'),
                'condition receive site differs from original task_hdmi')
        eq(sites[0], timeout=-1)
    receives = [r for r in log.rows('RCV_MSG_TMO') if start < r['line'] < edge['PEER_REPLY']['line'] and
                r['fields'].get('queue') == hex(CONDITION_SID) and r['fields'].get('tid') == receiver]
    if receives:
        require(len(receives) == 24, 'incomplete optional original receive result trace')
        for received, item in zip(receives, sorted(edge['condition_messages'], key=lambda x: x['freed']['line'])):
            eq(received, result=0, bytes=20, timeout=-1, reply_code='0')
            require(item['published']['line'] < received['line'] < item['freed']['line'], 'condition receive/free lease chronology differs')
    edge.update(profile=profile, canonical_Get_retirements=gets, native_UPM=upm,
        backup_inputs=backup, prefix_reply_retirements=prefix,
        condition_subscription=subscription, condition_receiver_site=sites[0] if sites else None,
        actual_condition_receives=receives, condition_receive_site_runtime_logged=bool(sites),
        condition_receive_basis='received=1 and same receiver/TID in each original native free; outer frozen receive hook required',
        predecessor_free_line=previous_free, first_graph_request_line=first_graph_request,
        scope='same-run HDMI11 native consumers and AP retirement; outer build/locks/prior-edges/SD proof required',
        full_native_effects_verified=True)
    return edge
