#!/usr/bin/env python3
"""Fail-closed verifier for R (OSD12), using the old checker's Log records.

verify_osd_effects(log[, oldbatchmodule]) also accepts actual C host-fixture
stdout wrapped in OBS by its test reader. It makes no native/VM claim.
verify_osd_edge(log, previous_free, identity, first_graph_request[, oldbatchmodule])
adds the actual constructor, guard and canonical Get retirement evidence.
The caller verifies build identity, the previous ten edges, SD and cleanup,
and normalizes transport before constructing Log. This helper repairs no bytes.
No function changes Log records, helper globals or files, or controls a VM.
"""
# SPDX-License-Identifier: MIT
import importlib.util
from pathlib import Path
import struct
from types import FunctionType

PREFIX = 'FULL_PINMEM_OSD_CONNECT'
PROFILE = 'virtual-pinmem-osd0-osdpin-if0-ssos-v1'
S = (1, 3, 0, 0x90590818)
P = (1, 3, 0, 0x9080003b)
UNIT = 0xe1700
DMM = 0x9059000e
TOKEN = 0x4f534406
OWNERS = {S[3]: ('PINMEM', None), P[3]: ('OSDPIN', 1)}
SLOTS = {S: 8, P: 0}
_BATCH = None


def _batch(module):
    global _BATCH
    if module is not None:
        return module
    if _BATCH is None:
        path = Path(__file__).with_name('evaluate-graph-batch-native.py')
        spec = importlib.util.spec_from_file_location('_osd_readonly_old_batch', path)
        _BATCH = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_BATCH)
    return _BATCH


def _fnv(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return f'{value:016x}'


def _backing(bank, peer_handle=0, final=False):
    """Independent 256-byte SSOS/ETRY expectation, including unknown a5 bytes."""
    tag, size = ((0, 64), (0x101, 16), (0x100, 128), (0x102, 32))[bank]
    data, mask = bytearray([0xa5] * 256), bytearray(256)
    data[:64], mask[:64] = bytes(64), bytes([1] * 64)
    struct.pack_into('<5I', data, 0, 0x534f5353, 1 if bank == 0 else 0x01000000,
                     3 if bank == 0 else 0, 1, 32)
    struct.pack_into('<6I', data, 32, 0x59525445, tag, 0, 64, size, 0)
    if bank == 0:
        data[64:128], mask[64:128] = bytes(64), bytes([1] * 64)
    elif bank == 1:
        struct.pack_into('<IIH', data, 64, 0, peer_handle, 0)
        struct.pack_into('<I', data, 76, 0)
        mask[64:74], mask[76:80] = bytes([1] * 10), bytes([1] * 4)
    elif bank == 2:
        struct.pack_into('<I', data, 64, 0 if final else 1)
        struct.pack_into('<H', data, 72, 0)
        data[76] = 0
        mask[64:68], mask[72:74], mask[76] = bytes([1] * 4), bytes([1] * 2), 1
    else:
        struct.pack_into('<IH', data, 64, 0xffffffff, 0)
        data[72:92] = bytes([0xff] * 20)
        mask[64:70], mask[72:92] = bytes([1] * 6), bytes([1] * 20)
    return bytes(data), bytes(mask), 64 + size


def _plan():
    events = [('REQUEST', None)]
    def dmm(bank, index, op):
        key = (bank, index, op)
        events.extend((('DMM_REQUEST', key), ('DMM_REPLY', key)))
    def create(bank, index):
        dmm(bank, index, 0x20)
        events.append(('FORMAT_WRITTEN', (bank, index)))
    def notify(bank, index):
        dmm(bank, index, 0x21)
        events.append(('SOURCE_NOTIFY' if bank else 'PEER_NOTIFY', (bank, index)))
        dmm(bank, index, 0x24)
        events.append(('FORMAT_CONSUMED', (bank, index)))
    for i in range(4):
        create(0, i)
    events.extend((('PEER_REQUEST', None), ('PEER_REPLY', None)))
    for i in range(4):
        notify(0, i)
        create(1, i)
        notify(1, i)
    events.extend((('EVENT6_ENQUEUED', None), ('EVENT6_CONSUMED', None)))
    for bank in (2, 3):
        for i in range(4):
            create(bank, i)
            notify(bank, i)
    events.extend((tag, None) for tag in ('SOURCE_POST', 'RESOURCE_READBACK',
        'REPLY_QUEUED', 'REQUEST_FREE', 'COMMIT', 'NATIVE_REPLY_FREE'))
    return events


def verify_osd_effects(log, oldbatchmodule=None):
    """Verify actual R wire/data effects; native admission is a separate check.

    Returned message/resource/effect records are the original Log objects.
    Expected backing/known-mask hashes are calculations, not invented read logs.
    Aggregate final readback is attributed to the bound C implementation.
    """
    batch = _batch(oldbatchmodule)
    old = batch.old
    require, eq, raw = batch.require, batch.fields_equal, batch.raw_bytes
    scoped = [r for r in log.records if r['tag'].startswith(PREFIX + '_')]
    require(scoped, 'missing OSD12 evidence')
    plan = _plan()
    auxiliary = {'INTERNAL_FREE', 'UNADMITTED', 'PROFILE', 'RESOURCE_DEPENDENCIES',
                 'RESOURCES_RESERVED', 'RESOURCES_TTS_TABLE'}
    allowed = auxiliary | {tag for tag, _ in plan}
    false_flags = {'graphics_ready', 'GPE_ready', 'gpe_ready', 'hardware_verified',
        'frames_verified', 'capture_verified', 'original_CP_executed',
        'original_cp_executed', 'original_CP_pages_verified',
        'original_allocator_capacity_verified', 'original_RTOS_scheduling_verified',
        'connection_verified'}
    for row in scoped:
        suffix = row['tag'][len(PREFIX) + 1:]
        require(suffix in allowed, ('OSD12 failed/unsupported/unexpected record', row))
        for name in false_flags & row['fields'].keys():
            eq(row, **{name: 0})
    actual = [r for r in scoped if r['tag'][len(PREFIX) + 1:] not in auxiliary]
    require([r['tag'][len(PREFIX) + 1:] for r in actual] == [tag for tag, _ in plan],
            'OSD12 missing/extra/reordered actual effects')
    edge = {tag: log.one(PREFIX + '_' + tag) for tag in
        ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED', 'REQUEST_FREE',
         'COMMIT', 'NATIVE_REPLY_FREE', 'EVENT6_ENQUEUED', 'EVENT6_CONSUMED',
         'SOURCE_POST', 'RESOURCE_READBACK')}
    request, caller = old.request_bytes(edge['REQUEST'], S, P)
    identity = tuple(edge['REQUEST']['fields'][k] for k in ('pid', 'tid'))
    require(all(int(v) > 1 for v in identity), 'invalid OSD12 owner PID/TID')
    for tag in ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED', 'NATIVE_REPLY_FREE'):
        eq(edge[tag], pid=identity[0], tid=identity[1])
    batch.model_frame(edge['PEER_REQUEST'], 64, 0x100, 1, S[3], P[3], S + P)
    batch.model_frame(edge['PEER_REPLY'], 72, 0x8100, 1, P[3], S[3], S + P + (0, 0))
    batch.model_frame(edge['REPLY_QUEUED'], 56, 0x8001, 2, S[3], caller, S + (0, 0))
    eq(edge['REQUEST_FREE'], owner=hex(S[3]), pointer=edge['REQUEST']['fields']['pointer'], bytes=64, rc=0)
    freed = edge['NATIVE_REPLY_FREE']
    eq(freed, sender=identity[1], waiter=1, destination=hex(caller), expected=hex(caller),
       reply=edge['REPLY_QUEUED']['fields']['pointer'], bytes=56, command='0x8001',
       rc=0, faults=0, ap_consumed=1, capture_verified=0)
    enqueued, consumed = edge['EVENT6_ENQUEUED'], edge['EVENT6_CONSUMED']
    eq(enqueued, event=6, parameter_bytes=12, token=hex(TOKEN),
       token_policy='owned-answer-plus24-map', saved_original_request_bytes=64,
       queue_phase=1, wait_primary=6, keep_pending=1, context_kind=2,
       original_RTOS_scheduling_verified=0)
    eq(consumed, parameter_bytes=12, actual_parameter_read=1, token_body_binding_verified=1,
       saved_peer_u32_fields_verified=4, source_complete_raw='0x5839a6', source_state=0,
       status=0, tail=0, original_RTOS_scheduling_verified=0)
    parameter = struct.pack('<I', TOKEN) + bytes(8)
    # These fields are not currently logged by C; if supplied they must agree.
    for row in (enqueued, consumed):
        optional = {'raw': parameter.hex(), 'parameter_fnv': _fnv(parameter),
            'saved_request_fnv': _fnv(request), 'saved_original_request_bytes': 64,
            'saved_dynamic_destination': hex(caller), 'body_offset': 24,
            'token': hex(TOKEN), 'status': 0, 'tail': 0}
        eq(row, **{k: v for k, v in optional.items() if k in row['fields']})
    eq(edge['SOURCE_POST'], source_raw='0x5d61a2', inactive_rows=5,
       selected_tag100_backing_count=0, OSD_cached_count=1, repeated_notice=0,
       extra_share=0, extra_open=0, metadata_ready=1, graphics_ready=0, GPE_ready=0,
       optional_diagnostic_skipped=1)
    eq(edge['RESOURCE_READBACK'], live=16, owners_each=2, opens_each=2, DMM_requests=48,
       DMM_replies=48, reference_readbacks=48, peer_notices=4, source_notices=12,
       exact_backing_and_known_masks_verified=1, selected_backing_count=0, cached_count=1,
       original_allocator_capacity_verified=0, original_CP_pages_verified=0,
       frames_verified=0, capture_verified=0)
    eq(edge['COMMIT'], source_state=0, peer_state=0, pending=0, metadata_only=1,
       AP_reply_after_16_buffers_48_DMM_and_source_post=1, persistent_resources=16,
       graphics_ready=0, GPE_ready=0, frames_verified=0, capture_verified=0)

    resources, exchanges, notices = {}, [], []
    sequence = 0
    allocated = 0
    for row, (tag, key) in zip(actual, plan):
        if tag == 'DMM_REQUEST':
            bank, index, op = key
            producer = S[3] if bank else P[3]
            side = (P[3] if bank else S[3]) if op == 0x24 else producer
            n = 152 if side == S[3] else 40
            sequence += 1
            local, token = 0x61003c + (sequence - 1) * 4, 0x4f00 + sequence
            if op == 0x20:
                slot = allocated
                allocated += 1
                resources[bank, index] = {'bank': bank, 'ordinal': index,
                    'handle': 0xe1000010 | slot, 'generation': 1, 'unit': UNIT,
                    'extent': 256, 'physical': 0x500010000 + slot * 256,
                    'cp_alias': 0x81000000 + slot * 256,
                    'creator_sid': producer, 'consumer_sid': P[3] if bank else S[3]}
            resource = resources[bank, index]
            h = resource['handle']
            expected = bytearray([0xa5] * n)
            struct.pack_into('<H', expected, 0, op)
            if op != 0x24:
                struct.pack_into('<I', expected, 4, UNIT)
            if op != 0x20:
                struct.pack_into('<I', expected, 8, h)
            struct.pack_into('<IIHH', expected, 12, 0 if op == 0x24 else 0xffffffff,
                             local, token, 1 if op == 0x20 else 0)
            eq(row, pid=identity[0], tid=identity[1], source=hex(side), destination=hex(DMM))
            data = raw(row, n)
            require(data == expected, ('OSD12 complete DMM inner request mismatch', key, sequence))
            exchanges.append({'request': row, 'bank': bank, 'ordinal': index, 'operation': op,
                'requester_sid': side, 'reply_sid': local, 'token': token, 'handle': h,
                'owners_after': 1 if op == 0x20 else 2,
                'opens_after': 2 if op == 0x24 else 1,
                'creator_open_after': 1, 'consumer_open_after': int(op == 0x24)})
        elif tag == 'DMM_REPLY':
            exchange = exchanges[-1]
            resource = resources[key[:2]]
            op = key[2]
            n = 152 if exchange['requester_sid'] == S[3] else 40
            expected = bytearray([0xa5] * n)
            expected[:40] = bytes(40)
            struct.pack_into('<H', expected, 0, op | 0x8000)
            struct.pack_into('<HH', expected, 6, exchange['token'], 1)
            struct.pack_into('<I', expected, 12, resource['handle'])
            if op != 0x24:
                struct.pack_into('<I', expected, 16, UNIT)
            struct.pack_into('<QI', expected, 24, resource['physical'], 256)
            eq(row, pid=identity[0], tid=identity[1], source=hex(DMM), destination=hex(exchange['reply_sid']))
            data = raw(row, n)
            require(data == expected, ('OSD12 complete DMM reply/result/H/mapping mismatch', key))
            # Decode the known result/H/address fields separately from the builder.
            result, token, hflag = struct.unpack_from('<H2xHH', data, 2)
            handle = struct.unpack_from('<I', data, 12)[0]
            physical, extent = struct.unpack_from('<QI', data, 24)
            require((result, token, hflag, handle, physical, extent) ==
                (0, exchange['token'], 1, resource['handle'], resource['physical'], 256),
                'OSD12 independently decoded DMM reply differs')
            exchange.update(reply=row, result=result, H=hflag, physical=physical, extent=extent)
        elif tag == 'FORMAT_WRITTEN':
            bank, index = key
            resource = resources[key]
            peer_handle = resources[0, index]['handle'] if bank == 1 else 0
            data, known, used = _backing(bank, peer_handle)
            eq(row, bank=bank, ordinal=index, handle=hex(resource['handle']), unit=hex(UNIT),
               extent=256, physical=hex(resource['physical']), cp_alias=hex(resource['cp_alias']),
               used=used, known=sum(known), fnv=_fnv(data), known_fnv=_fnv(known), pixels=0)
            final, final_mask, _ = _backing(bank, peer_handle, final=bank == 2 and index == 0)
            resource.update(written=row, tag=(0, 0x101, 0x100, 0x102)[bank], used=used,
                known_bytes=sum(known), expected_initial_fnv=_fnv(data),
                expected_final_fnv=_fnv(final), expected_known_fnv=_fnv(final_mask),
                unknown_bytes=256 - sum(known), unknown_byte=0xa5,
                backing_raw_logged=False, final_readback=edge['RESOURCE_READBACK'])
        elif tag in ('PEER_NOTIFY', 'SOURCE_NOTIFY'):
            bank, index = key
            resource = resources[key]
            producer, receiver = resource['creator_sid'], resource['consumer_sid']
            expected = bytearray(old.frame_bytes(80, 0x102, 1,
                (1, 3, 0, receiver, 1, 3, 0, producer, UNIT, resource['handle'], 0, 0),
                opaque=bytes([0xa5] * 4)))
            eq(row, pid=identity[0], tid=identity[1], source=hex(producer), destination=hex(receiver))
            require(raw(row, 80) == expected, ('OSD12 notice descriptors/unit/handle differ', key))
            resource['notice'] = row
            notices.append(row)
        elif tag == 'FORMAT_CONSUMED':
            bank, index = key
            resource = resources[key]
            eq(row, bank=bank, ordinal=index, handle=hex(resource['handle']), actual_mapping_read=1,
               owners=2, opens=2, creator_open=1, consumer_open=1, retained=1,
               optional_diagnostic_does_not_gate=1, capture_verified=0)
            resource.update(consumed=row, owners=2, opens=2, creator_open=1, consumer_open=1)
    require(allocated == len(resources) == 16 and sequence == len(exchanges) == 48,
            'OSD12 requires exactly sixteen allocations/shares/opens')
    require(len({r['handle'] for r in resources.values()}) == 16 and
            len({r['physical'] for r in resources.values()}) == 16 and
            len({r['cp_alias'] for r in resources.values()}) == 16, 'OSD12 resource mappings alias')

    # Replay only allocations visible in these actual records; reuse after free is legal.
    wire_tags = {'REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'DMM_REQUEST', 'DMM_REPLY',
                 'PEER_NOTIFY', 'SOURCE_NOTIFY', 'REPLY_QUEUED'}
    live, internal_frees = {}, []
    for row in scoped:
        tag = row['tag'][len(PREFIX) + 1:]
        if tag in wire_tags:
            pointer = row['fields']['pointer']
            address = int(pointer, 0)
            require(address > 0 and address not in live, ('OSD12 live message allocation alias', row))
            live[address] = (row, S[3] if tag == 'REQUEST' else caller)
        elif tag in ('INTERNAL_FREE', 'REQUEST_FREE', 'NATIVE_REPLY_FREE'):
            pointer = row['fields']['reply' if tag == 'NATIVE_REPLY_FREE' else 'pointer']
            address = int(pointer, 0)
            require(address in live, ('OSD12 free lacks live owned allocation', row))
            allocation, owner = live.pop(address)
            eq(row, rc=0)
            eq(row, **{'destination' if tag == 'NATIVE_REPLY_FREE' else 'owner': hex(owner)})
            if tag == 'INTERNAL_FREE':
                eq(row, pool_references_released=0)
                require(allocation['tag'].split(PREFIX + '_')[1] not in ('REQUEST', 'REPLY_QUEUED'),
                        'OSD12 internal free retired AP storage')
                internal_frees.append(row)
            elif tag == 'REQUEST_FREE':
                require(allocation is edge['REQUEST'], 'OSD12 wrong original request freed')
            else:
                require(allocation is edge['REPLY_QUEUED'], 'OSD12 wrong AP reply freed')
    require(not live and len(internal_frees) == 114, 'OSD12 message storage leaked/missing free')
    for control in ('PEER_REQUEST', 'PEER_REPLY'):
        frees = [r for r in internal_frees if r['fields']['pointer'] == edge[control]['fields']['pointer']
                 and edge[control]['line'] < r['line'] < edge['RESOURCE_READBACK']['line']]
        require(len(frees) == 1 and edge['SOURCE_POST']['line'] < frees[0]['line'],
                'OSD12 peer control/borrow released before all effects')
    early = log.rows(PREFIX + '_UNADMITTED')
    for row in early:
        eq(row, requests=0, faults_unchanged=1)
        require(row['line'] < edge['REQUEST']['line'], 'OSD12 late unadmitted attempt')
    edge.update(prefix=PREFIX, source_pin=S, sink_pin=P, caller=caller, identity=identity,
        REPLY_FREE=freed, original_request_fnv=_fnv(request),
        resources=list(resources.values()), DMM_exchanges=exchanges,
        notices=notices, internal_frees=internal_frees, early_unadmitted_requests=early,
        event_parameter_expected_raw=parameter.hex(), event_parameter_raw_logged=False,
        event_parameter_basis='actual 12B consumption/owned +24 binding; source-byte identity is caller build-bound',
        pool={'unit': UNIT, 'slots': 16, 'extent': 256, 'bytes': 4096,
              'virtual': True, 'separate_from_404': True,
              'original_allocator_capacity_verified': False, 'original_CP_pages_verified': False},
        scope='OSD12 actual virtual metadata effects; no native admission/build proof',
        metadata_ready=True, GPE_ready=False, hardware_verified=False,
        frames_verified=False, capture_verified=False)
    return edge


def verify_osd_edge(log, previous_free, identity, first_graph_request, oldbatchmodule=None):
    """Add same-run native constructor/guard/Get evidence and predecessor order.

    previous_free/first_graph_request are actual Log line numbers supplied by
    the outer verifier. Identity is its original AP (PID, TID) pair.
    """
    batch = _batch(oldbatchmodule)
    require, eq = batch.require, batch.fields_equal
    edge = verify_osd_effects(log, batch)
    identity = tuple(map(str, identity))
    require(edge['identity'] == identity, 'OSD12 original AP PID/TID differs')
    start = edge['REQUEST']['line']
    require(first_graph_request <= previous_free < start, 'OSD12 predecessor/graph bound differs')
    for row in edge['early_unadmitted_requests']:
        require(row['line'] < first_graph_request, 'OSD12 unadmitted attempt during/after graph phase')
    profiles = [r for r in log.rows(PREFIX + '_PROFILE') if r['fields'].get('pid') == identity[0]]
    require(len(profiles) == 1, 'OSD12 missing/duplicate actual AP constructor profile')
    profile = profiles[0]
    eq(profile, requested=PROFILE, enabled=1, first_missing='none', owner_pid=identity[0],
       initialized=1, before_any_input=1, original_cp_executed=0, hardware_verified=0,
       metadata_ready=0, gpe_ready=0, frames_verified=0, connection_verified=0, capture_verified=0)
    require(profile['line'] < first_graph_request, 'OSD12 constructor enabled after graph input')
    resources = log.one(PREFIX + '_RESOURCES_RESERVED', tid=identity[1], accepted=1,
        allocations=4, releases=4, control_live=0, control_faults=0, control_bound=1,
        dmm_enabled=1, dmm_bound=1, dmm_domain=2, foreign_speech_kept=1,
        dmm_allocation_count=2, dmm_lifecycle_changed=0, dmm_slots='1/1', dmm_opens='1/1',
        dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2',
        dmm_creators='1/1', format_consumed=1, buffer_released=1,
        connection_reply_frees=1, connection_faults=0, vef_pending=0, vef_live=0,
        vef_retained=0, vef_faults=0, pinmem_pending=0, pinmem_live=0,
        pinmem_retained=0, pinmem_faults=0)
    dependencies = log.one(PREFIX + '_RESOURCE_DEPENDENCIES', pid=identity[0], tid=identity[1],
        accepted=1, proc_ap_consumed=1, input_ap_consumed=1, output_ap_consumed=1,
        output_faults=0, current_request_retained_expected=1, capture_verified=0)
    table = log.one(PREFIX + '_RESOURCES_TTS_TABLE', pid=identity[0], tid=identity[1],
        table_va='0x5f66b08', bytes=144, reads='144/144', unchanged=1,
        atomic_snapshot=0, ownership_verified=0)
    table_before = bytes.fromhex(table['fields']['raw_before'])
    require(len(table_before) == 144 and table_before == bytes.fromhex(table['fields']['raw_after']),
            'OSD12 guarded prior Speech table changed/incomplete')
    require(int(table['fields']['address'], 0) == int(table['fields']['appfw_base'], 0) + 0x5f66b08,
            'OSD12 Speech table actual mapping differs')
    require(previous_free < dependencies['line'] < table['line'] < resources['line'] < start,
            'OSD12 prior-resource guarded readback order differs')
    # Extend only this function's isolated namespace; never mutate a caller's checker.
    def get_frame(length, opcode, kind, words, caller=0, opaque=bytes(4)):
        # OSDPIN's actual Get owner sets outer replySID; PinMem leaves it zero.
        if length == 56 and opcode == 0x8000 and words[4] == P[3]:
            caller = P[3]
        return batch.old.frame_bytes(length, opcode, kind, words, caller, opaque)
    namespace = dict(batch.verify_get.__globals__, frame_bytes=get_frame,
        OWNERS={**batch.OWNERS, **OWNERS}, SLOTS={**batch.SLOTS, **SLOTS})
    verify_get = FunctionType(batch.verify_get.__code__, namespace)
    gets = [verify_get(log, key, identity, edge['caller'], previous_free, start) for key in (S, P)]
    require(gets[0]['actual_same_sender_free']['line'] < gets[1]['request']['line'],
            'OSD12 source Get not retired before peer Get')
    require(gets[1]['actual_same_sender_free']['line'] < dependencies['line'],
            'OSD12 reservation preceded actual Get retirement')
    # Admitted dispatch records the actual request before returning; the generic
    # PIN_CONTROL_REQUEST observer is reached only by unhandled connections.
    edge.update(profile=profile, original_AP_send=edge['REQUEST'],
        canonical_Get_retirements=gets, prior_resources=resources,
        resource_dependencies=dependencies, prior_Speech_table=table,
        predecessor_free_line=previous_free, first_graph_request_line=first_graph_request,
        scope='OSD12 same-run virtual metadata edge with actual AP admission/retirement; outer build proof required')
    return edge
