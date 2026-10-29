"""Offline graph-batch verifier checks; no VM, /proc inspection or lock access."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tarfile
import tempfile
from unittest.mock import patch


def run_tests(m):
    checks = 0
    def accepts(call):
        nonlocal checks
        result = call(); checks += 1
        return result
    def rejects(call, message=None):
        nonlocal checks
        try:
            call()
        except (m.old.EvidenceError, OSError, KeyError, ValueError, TypeError, struct.error) as error:
            if message is not None:
                assert message in str(error), (message, str(error))
            checks += 1
        else:
            raise AssertionError('corrupt evidence accepted')
    host_fixture = {'/public/start-menu.py': 'a' * 64, '/public/menu_live.py': 'b' * 64}
    assert accepts(lambda: m.verify_host_baseline(host_fixture, host_fixture, host_fixture)) == []
    assert accepts(lambda: m.verify_host_baseline(host_fixture, {}, host_fixture)) == sorted(host_fixture)
    rejects(lambda: m.verify_host_baseline(host_fixture, {}, {**host_fixture, '/public/menu_live.py': 'c' * 64}))
    rejects(lambda: m.verify_host_baseline(host_fixture, {'/public/start-menu.py': 'c' * 64}, host_fixture))
    rejects(lambda: m.verify_host_baseline(host_fixture, {}, {'/public/start-menu.py': 'a' * 64}))
    rejects(lambda: m.verify_host_baseline(host_fixture, {}, {**host_fixture, '/extra.py': 'd' * 64}))
    intact_commit = (b'OBS FULL_INFRABB_VEF_CONNECT_COMMIT connections=1 source_state=0 peer_state=0 '
        b'source_pending=0 format_consumed=1 buffer_freed=1 unique_reply=1 prior_edges_'
        b'NoMem_AB_failure_S0_preserved=1 original_CP_executed=0 frames_verified=0 capture_verified=0\r\n')
    host_warning = b'qemu-system-aarch64: warning: vvfat: host directory commit pending\n'
    assert accepts(lambda: m.normalize_transport(intact_commit)) == (intact_commit, [])
    mixed_commit = intact_commit.replace(b'prior_edges_', b'prior_edges_' + host_warning)
    restored, recoveries = accepts(lambda: m.normalize_transport(mixed_commit))
    assert restored == intact_commit and len(recoveries) == 1 and recoveries[0]['guest_bytes_invented'] is False
    assert mixed_commit[recoveries[0]['raw_warning_start']:recoveries[0]['raw_warning_end']] == host_warning
    near_warning = mixed_commit.replace(b'commit pending\n', b'commit unknown\n')
    assert accepts(lambda: m.normalize_transport(near_warning)) == (near_warning, [])
    wrong_record = mixed_commit.replace(b'unique_reply=1', b'unique_reply=0')
    assert accepts(lambda: m.normalize_transport(wrong_record)) == (wrong_record, [])
    rejects(lambda: m.fields_equal(m.Log(near_warning).one('FULL_INFRABB_VEF_CONNECT_COMMIT'),
                                   prior_edges_NoMem_AB_failure_S0_preserved=1))
    records = []
    identity, caller = ('913', '1207'), 0x81cf619b
    def emit(tag, raw=None, **fields):
        if raw is not None:
            fields.update(raw=bytes(raw).hex(), bytes=len(raw))
        row = {'line': len(records) + 1, 'tag': tag, 'raw': 'offline-test-only',
               'fields': {k: str(v) for k, v in fields.items()}}
        records.append(row); return row
    def wire(tag, payload, src, dst, pointer):
        return emit(tag, raw=payload, pid=identity[0], tid=identity[1], source=hex(src),
                    destination=hex(dst), pointer=pointer)
    profiles = (m.NEW[0], m.NEW[1], m.NEW[-1])
    for prefix, _, profile, _, _ in profiles:
        fields = dict(requested=profile, enabled=1, first_missing='none', pid=identity[0], before_any_input=1)
        if profile == m.PEER_PROFILE:
            prefix = 'FULL_PINMEM_PEER_CONNECT'
            fields.update(owner_pids=','.join([identity[0]] * 3), initialized='1,1,1')
        else:
            fields.update(owner_pid=identity[0], initialized=1)
        emit(prefix + '_PROFILE', **fields)
    for prefix, *_ in m.NEW:
        emit(prefix + '_UNADMITTED', requests=0, faults_unchanged=1, owner_not_reset=1)
    first_graph_request = emit('OFFLINE_FIRST_GRAPH_REQUEST')['line']
    baseline_free = emit('OFFLINE_SIXTH_GRAPH_REPLY_FREE')['line']
    leases = {}
    def get(key):
        name = m.OWNERS[key[3]][0]; prefix = 'FULL_' + name
        lease = leases[name] = leases.get(name, 0) + 1
        data = m.frame_bytes(48, 0, 2, key[:3] + (0,), caller, b'\x7f\0\0\0')
        emit('PIN_QUERY', raw=data, tid=identity[1], source=hex(caller), destination=hex(key[3]))
        emit(prefix + '_REQUEST', raw=data, tid=identity[1], source=hex(caller),
             destination=hex(key[3]), reply_destination=hex(caller))
        # Reusing a fully retired allocation is intentional and valid.
        emit(prefix + '_REPLY_QUEUED', raw=m.frame_bytes(56, 0x8000, 2, key[:3] + (1, key[3], 0)),
             tid=identity[1], source=hex(key[3]), destination=hex(caller), reply='0x1100', lease=lease)
        emit(prefix + '_COMMIT', tid=identity[1], slot=m.SLOTS[key], type=key[0], dir=key[1], index=key[2],
             pin_state=1, owner=hex(key[3]), status=0, reply='0x1100', lease=lease, request_free_rc=0,
             connect_performed=0, pixels_consumed=0, camera_startup_verified=0)
        emit(prefix + '_NATIVE_REPLY_FREE', tid=identity[1], sender=identity[1], waiter=1,
             destination=hex(caller), expected=hex(caller), reply='0x1100', lease=lease, bytes=56, rc=0)
    def resource(prefix):
        emit(prefix + '_RESOURCE_DEPENDENCIES', pid=identity[0], tid=identity[1], accepted=1,
             proc_ap_consumed=1, input_ap_consumed=1, output_ap_consumed=1, output_faults=0)
        emit(prefix + '_RESOURCES_RESERVED', tid=identity[1], accepted=1, allocations=4, releases=4,
             control_live=0, control_faults=0, control_bound=1, dmm_domain=2, foreign_speech_kept=1,
             dmm_allocation_count=2, dmm_lifecycle_changed=0, dmm_slots='1/1', dmm_opens='1/1',
             dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
             format_consumed=1, buffer_released=1, connection_reply_frees=1, connection_faults=0,
             vef_pending=0, vef_live=0, vef_retained=0, vef_faults=0, pinmem_pending=0,
             pinmem_live=0, pinmem_retained=0, pinmem_faults=0)
    def seventh_effects(prefix):
        emit(prefix + '_EVENT8_ENQUEUED', producer_raw='0x5f99fe-0x5f9a4e', event=8, parameter_bytes=32,
            cleared_bytes=32, body_offset=24, token='0x56450001', token_policy='owned-answer-body-map',
            borrowed_reply_held=1, bounded_local_queue=1, original_CP_event_pointer_identity_verified=0,
            original_RTOS_scheduling_verified=0)
        emit(prefix + '_EVENT8_CONSUMED', consumer_raw='0x10cb3e-0x10cb6a', event=8, actual_parameter_read=1,
            token_body_binding_verified=1, saved_original_header_bytes=24, original_peer_type_dir_index_verified=1,
            strict_peer_owner_verified=1, status=0, tail=0, source_complete_raw='0x5839a6', consumed=1, pending=0,
            original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
        emit(prefix + '_POSTHOOK_NO_FORMAT', handler_raw='0x5f9a30', posthook_raw='0x10c89c', lookup_raw='0x5f8628',
            source_ordinal=15, owned_table_readback=1, selected_ordinals='1,2,3', selected=0, current_info_calls=0,
            f008_calls=0, DMM_allocations=0, notifications=0, cache_writes=0, marker_writes=0, clock_writes=0, MMIO_writes=0)
    def event6(prefix, source, peer, original):
        token = 0x504d0000 | (source[0] << 12) | source[2]
        parameter = struct.pack('<I', token) + bytes(8)
        emit(prefix + '_EVENT6_ENQUEUED', producer_raw='0x5d74ba', event=6, parameter_bytes=12, cleared_bytes=12,
            token=hex(token), raw=parameter, token_policy='owned-answer-plus24-map', saved_original_request_bytes=64,
            queue_phase=1, wait_primary=6, wait_secondary=0, keep_pending=1, context_kind=2,
            original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
        emit(prefix + '_EVENT6_CONSUMED', consumer_raw='0x5dd814', work_raw='0xf882c',
            context_getters_raw='0x5db244,0x5db25a,0x5db24a,0x5db39a', parameter_bytes=12,
            parameter_fnv=m.fnv(parameter), token=hex(token), actual_parameter_read=1, token_body_binding_verified=1,
            saved_dynamic_destination=hex(caller), saved_request_fnv=m.fnv(original),
            reply_peer=','.join([str(v) for v in peer[:3]] + [hex(peer[3])]), full_peer_u32_verified=4,
            source_complete_raw='0x5839a6', status=0, tail=0, consumed=1, pending=0,
            original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
        if source[0] == 0:
            emit(prefix + '_YC_DIRECTION_CHECK', command='0x8100', selected_group='source', type=0, dir=2,
                index=source[2], callback_raw='0x5d6bc2', return_raw='0x5d6bf6', format_published=0, buffer_allocated=0)
        else:
            emit(prefix + '_DRAWINFO_MANAGER', selected_group='source', type=6, dir=2, manager='DrawInfoRawManager',
                 method_offset='0xc', typed_callback_called=1, rc=0, YC_called=0, DMM=0, notifications=0, markers=0, MMIO=0)
    def unsupported():
        for pins in ((4, 2, 0, 0x90590818, 4, 1, 0, 0x909a015a),
                     (1, 3, 0, 0x90590818, 1, 3, 0, 0x9080003b)):
            wire('PIN_CONTROL_REQUEST', m.frame_bytes(64, 1, 2, pins, caller), caller, pins[3], '0x1000')
            emit('FULL_PINMEM_UNSUPPORTED', reason='no-supported-consumer')
    for index, spec in enumerate(m.NEW):
        if index == 4:
            unsupported()
        prefix, _, _, source, peer = spec
        get(source); get(peer); resource(prefix)
        original = m.frame_bytes(64, 1, 2, source + peer, caller, b'\x7f\0\0\0')
        wire(prefix + '_REQUEST', original, caller, source[3], '0x1000')
        wire(prefix + '_PEER_REQUEST', m.frame_bytes(64, 0x100, 1, source + peer), source[3], peer[3], '0x2000')
        if index == 0:
            emit(prefix + '_SINK_MANAGER', type=8, choice_raw='0xf7474', branch_raw='0xf74a2', manager_get_raw='0x5d6a78',
                manager_CP_VA='0x10f5008', vtable_CP_VA='0xd270f0', method_offset='0xc', method_raw='0x5d6a86',
                typed_callback_called=1, rc=0, DMM=0, markers=0, events=0, clocks=0, MMIO=0, original_CP_executed=0)
        wire(prefix + '_PEER_REPLY', m.frame_bytes(72, 0x8100, 1, source + peer + (0, 0)), peer[3], source[3], '0x3000')
        if index == 0:
            seventh_effects(prefix)
        elif index < 4:
            event6(prefix, source, peer, original)
        else:
            emit(prefix + '_HDMI_MARKER_READBACK', hook_raw='0x1297fe', Generic_tag_ADF_byte4=1, state_vtable_offset='0x34',
                old_known=0, connected=1, known=1, writes=1, readback=1, singleton_offset='0x60', next_state_null=1,
                state_identity_known=0, original_CP_memory_identity_verified=0, DMM=0, SSYN=0, clocks=0, PCM=0, MMIO=0)
            emit(prefix + '_SOURCE_COMPLETED', handler_raw='0x1976d8', method_CP_VA='0x68b9a6', source='5,2,0',
                complete_direct=1, event6=0, event8=0, postguard_raw='0x1977e0', selected_type5_dir1_index0=0,
                format_published=0, source_state=0)
        scalar = 0 < index < 4
        for pointer in ('0x2000', '0x3000'):
            emit(prefix + '_INTERNAL_FREE', pid=identity[0], tid=identity[1], pointer=pointer, rc=0,
                 **{'owner' if scalar else 'destination': hex(caller)})
        wire(prefix + '_REPLY_QUEUED', m.frame_bytes(56, 0x8001, 2, source + (0, 0)), source[3], caller, '0x2000')
        if scalar:
            emit(prefix + '_REQUEST_FREE', pid=identity[0], tid=identity[1], owner=hex(source[3]), pointer='0x1000', bytes=64, rc=0)
            emit(prefix + '_STATE_READBACK', source_type=source[0], source_slot=(4, 5, 10)[index - 1],
                peer_slot=(4, 0, 1)[index - 1], source_state=0, peer_state=0, source_pending=0,
                event6_consumed=1, parameter_bytes=12, yc_format_published=0, AP_reply_after_source_callback=1, pixels_consumed=0)
        elif index == 0:
            emit(prefix + '_COMMIT', connections=1, source_slot=15, peer_ordinal=12, source_state=0, peer_state=0, source_pending=0,
                manager_calls=1, manager_rc=0, event8_enqueued=1, event8_consumed=1, event8_pending=0,
                source_posthook_ordinal=15, selected=0, format_work=0, marker_writes=0,
                prior_six_edges_live_caches_DMM_NoMem_AB_failure_S0_preserved=1, unique_reply=1)
        else:
            emit(prefix + '_COMMIT', connections=1, source_slot=9, peer_ordinal=1, source_state=0, peer_state=0, source_pending=0,
                marker_known=1, marker=1, marker_writes=1, direct_source_handler=1, format_work=0,
                prior_ten_and_unrelated_HDMI_pins_preserved=1, original_RTOS_scheduling_verified=0)
        emit(prefix + ('_NATIVE_REPLY_FREE' if scalar else '_REPLY_FREE'), pid=identity[0], tid=identity[1], sender=identity[1],
            waiter=1, destination=hex(caller), expected=hex(caller), bytes=56, rc=0, faults=0, ap_consumed=1,
            **{'reply' if scalar else 'pointer': '0x2000'})
    emit('NATIVE_CP_BACKGROUND_UNHANDLED', opcode='0x302c')
    payload = b'\x01\x02\x03' * 60
    emit('FULL_HDMI_INPUT_AUDIT', pid=identity[0], tid=identity[1], sequence=1, destination='0x909a015a',
        bytes=len(payload), source=hex(caller), size_known=1, source_known=1, bytes_complete=1, complete=1, state_verified=0, capture_verified=0)
    for offset in (0, 128):
        emit('FULL_HDMI_INPUT_AUDIT_BYTES', raw=payload[offset:offset + 128], pid=identity[0], tid=identity[1], sequence=1, offset=offset)
    log = m.Log(b''); log.records = records
    def verify(candidate):
        added, last = [], baseline_free
        for spec in m.NEW:
            edge = m.verify_new_edge(candidate, spec, last, identity, first_graph_request)
            added.append(edge); last = edge['REPLY_FREE']['line']
        m.verify_new_effects(candidate, added, identity)
        m.verify_remaining(candidate, added[3], added[4], identity)
        m.verify_audits(candidate)
        return added
    added = accepts(lambda: verify(log))
    assert all(edge['early_unadmitted_requests']['unadmitted'] for edge in added)
    def mutate(tag, field, value, index=0):
        changed = copy.deepcopy(log)
        changed.rows(tag)[index]['fields'][field] = value
        rejects(lambda: verify(changed))
    for prefix, _, _, _, _ in m.NEW:
        mutate(prefix + '_PEER_REPLY', 'bytes', '71')
        mutate(prefix + '_PEER_REPLY', 'source', '0x90050004')
        row = log.one(prefix + '_PEER_REPLY')
        raw = bytearray.fromhex(row['fields']['raw']); raw[60] ^= 1
        mutate(prefix + '_PEER_REPLY', 'raw', raw.hex())
        mutate(prefix + '_RESOURCES_RESERVED', 'dmm_lifecycle_changed', '1')
        mutate(prefix + '_INTERNAL_FREE', 'pointer', '0x9999')
        scalar = prefix in ('FULL_SCALAR_CONNECT', 'FULL_ADF_CONNECT', 'FULL_PINMEM_DRAWINFO_CONNECT')
        free_tag = prefix + ('_NATIVE_REPLY_FREE' if scalar else '_REPLY_FREE')
        mutate(free_tag, 'tid', '1208')
        mutate(free_tag, 'reply' if scalar else 'pointer', '0x9999')
        mutate(free_tag, 'waiter', '0')
        mutate(free_tag, 'sender', '1208')
        for field in ('sender', 'waiter'):
            changed = copy.deepcopy(log)
            del changed.one(free_tag)['fields'][field]
            rejects(lambda: verify(changed), field)
        mutate(prefix + '_UNADMITTED', 'requests', '1')
        mutate(prefix + '_UNADMITTED', 'faults_unchanged', '0')
        mutate(prefix + '_UNADMITTED', 'owner_not_reset', '0')
        for position in (first_graph_request,
                         log.one(prefix + '_RESOURCES_RESERVED')['line'] - 0.5,
                         log.one(prefix + '_PEER_REPLY')['line'] + 0.5,
                         log.one(free_tag)['line'] + 0.5):
            changed = copy.deepcopy(log)
            changed.one(prefix + '_UNADMITTED')['line'] = position
            rejects(lambda: verify(changed), 'unexpected late unadmitted request')
        for suffix in ('FAULT', 'CLEANUP_FAULT', 'REQUEST_FREE_FAULT', 'UNSUPPORTED',
                       'RESOURCES_REFUSED', 'RESOURCES_FAULT'):
            for position in (log.one(prefix + '_PEER_REPLY')['line'] + 0.5,
                             log.one(free_tag)['line'] + 0.5):
                changed = copy.deepcopy(log)
                changed.records.append({'line': position, 'tag': prefix + '_' + suffix,
                                        'raw': 'offline-injected-failure', 'fields': {}})
                rejects(lambda: verify(changed), 'failed transaction')
    for prefix in ('FULL_VEF', 'FULL_SCALAR', 'FULL_ADF', 'FULL_DRAWINFO', 'FULL_HDMIPIN'):
        mutate(prefix + '_NATIVE_REPLY_FREE', 'waiter', '0')
        mutate(prefix + '_NATIVE_REPLY_FREE', 'sender', '1208')
        mutate(prefix + '_NATIVE_REPLY_FREE', 'reply', '0x9999')
    mutate('FULL_VEF_COMMIT', 'slot', '14')
    row = log.rows('FULL_VEF_REQUEST')[0]
    raw = bytearray.fromhex(row['fields']['raw']); raw[32] = 0
    mutate('FULL_VEF_REQUEST', 'raw', raw.hex())
    mutate('FULL_VEF_PINMEM_CONTROL_CONNECT_EVENT8_ENQUEUED', 'body_offset', '25')
    mutate('FULL_VEF_PINMEM_CONTROL_CONNECT_EVENT8_ENQUEUED', 'parameter_bytes', '12')
    mutate('FULL_VEF_PINMEM_CONTROL_CONNECT_EVENT8_CONSUMED', 'pending', '1')
    mutate('FULL_VEF_PINMEM_CONTROL_CONNECT_POSTHOOK_NO_FORMAT', 'cache_writes', '1')
    for prefix in ('FULL_SCALAR_CONNECT', 'FULL_ADF_CONNECT', 'FULL_PINMEM_DRAWINFO_CONNECT'):
        mutate(prefix + '_EVENT6_ENQUEUED', 'raw', '00' * 12)
        mutate(prefix + '_EVENT6_ENQUEUED', 'parameter_bytes', '32')
        mutate(prefix + '_EVENT6_ENQUEUED', 'wait_primary', '5')
        mutate(prefix + '_EVENT6_CONSUMED', 'saved_request_fnv', '0' * 16)
        mutate(prefix + '_EVENT6_CONSUMED', 'reply_peer', '0,1,0,0x90590818')
        mutate(prefix + '_EVENT6_CONSUMED', 'token_body_binding_verified', '0')
    mutate('FULL_ADF_HDMI_AUDIO_CONNECT_HDMI_MARKER_READBACK', 'readback', '0')
    mutate('FULL_ADF_HDMI_AUDIO_CONNECT_HDMI_MARKER_READBACK', 'old_known', '1')
    mutate('FULL_ADF_HDMI_AUDIO_CONNECT_SOURCE_COMPLETED', 'event6', '1')
    mutate('FULL_ADF_HDMI_AUDIO_CONNECT_COMMIT', 'prior_ten_and_unrelated_HDMI_pins_preserved', '0')
    mutate('FULL_HDMI_INPUT_AUDIT_BYTES', 'offset', '129', 1)
    mutate('FULL_HDMI_INPUT_AUDIT', 'complete', '0')
    mutate('FULL_HDMI_INPUT_AUDIT', 'state_verified', '1')
    mutate('FULL_HDMI_INPUT_AUDIT', 'destination', '0x90590818')
    mutate('FULL_HDMI_INPUT_AUDIT', 'source_known', '2')
    mutate('FULL_HDMI_INPUT_AUDIT_BYTES', 'raw', '00')
    changed = copy.deepcopy(log); r = changed.one('FULL_SCALAR_CONNECT_EVENT6_CONSUMED')
    changed.records.append({'line': r['line'], 'tag': 'FOREIGN_DMM_REQUEST', 'raw': 'test-only', 'fields': {}})
    rejects(lambda: verify(changed))
    changed = copy.deepcopy(log); changed.records.remove(changed.one('FULL_PINMEM_DRAWINFO_CONNECT_REQUEST_FREE'))
    rejects(lambda: verify(changed))
    tested = {'/example/one.c': m.sha(b'one'), '/example/two.h': m.sha(b'two')}
    sources = {p: {'sha256': h} for p, h in tested.items()}
    accepts(lambda: m.verify_source_baseline(sources, tested, tested))
    bad = dict(tested); bad['/example/two.h'] = m.sha(b'modified')
    rejects(lambda: m.verify_source_baseline(sources, tested, bad))
    rejects(lambda: m.verify_source_baseline(sources, bad, tested))
    rejects(lambda: m.verify_source_baseline(sources, tested, {'/example/one.c': tested['/example/one.c']}))
    with tempfile.TemporaryDirectory(prefix='graph-batch-archive-test-') as directory:
        path = Path(directory) / 'sources.tar.gz'
        index = {'/example/one.c': {'archive_path': 'source/one.c', 'sha256': m.sha(b'one')}}
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in [('source-inputs.json', json.dumps(index).encode()), ('source/one.c', b'one')]:
                member = tarfile.TarInfo(name); member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        inputs = {'sources': index, 'source_archive_sha256': m.sha(path.read_bytes())}
        accepts(lambda: m.read_archive(path, inputs))
        bad = copy.deepcopy(inputs); bad['sources']['/example/one.c']['sha256'] = m.sha(b'new')
        rejects(lambda: m.read_archive(path, bad))
        bad = copy.deepcopy(inputs); bad['source_archive_sha256'] = '0' * 64
        rejects(lambda: m.read_archive(path, bad))
        bad = copy.deepcopy(inputs); bad['sources']['/example/two.h'] = {'archive_path': 'source/two.h', 'sha256': m.sha(b'two')}
        rejects(lambda: m.read_archive(path, bad))
    # Real accepted run, pinned by console SHA; replay only pure read-only helpers.
    archived = m.BASE / 'menu-runs/run-4gqygshc/console.log'
    raw = archived.read_bytes()
    m.require(m.sha(raw) == 'f4566a8bc1e7b38ad9575148bfd420c9e790515c92aba9e5a1b3612e56c262b5', 'accepted six-edge replay baseline changed')
    real = m.Log(raw)
    first_six, real_id, *_ = accepts(lambda: m.six.verify_graph(real))
    accepts(lambda: m.verify_legacy(real, real_id, first_six[0]['REQUEST']['line']))
    for tag, field, value, index in (
        ('FULL_IMAGING_PIN_CONNECT_PEER_MARKER_WRITTEN', 'readback', '0', 0),
        ('FULL_VEF_PINMEM_INPUT_CONNECT_FORMAT_NOTIFY_CONSUMED', 'extra_share', '1', 1),
        ('FULL_INFRABB_VEF_FORWARD_VEF_FORMAT_CONSUMED', 'current_raw', '00' * 20, 0),
        ('FULL_IMAGING_PIN_CONNECT_FORWARD_FORMAT_CONSUMED', 'cache', '0,1,1920,1080,0', 0),
        ('FULL_VEF_PINMEM_INPUT_CONNECT_STATUS_READBACK', 'writer_generation', '0', 0),
        ('FULL_VEF_PINMEM_INPUT_CONNECT_BUFFER_RETIRED', 'opens', '1', 0)):
        bad = copy.deepcopy(real); bad.rows(tag)[index]['fields'][field] = value
        rejects(lambda bad=bad: m.six.verify_graph(bad))
    for tag, field, value in (
        ('FULL_PIN_FORMAT_PERSISTENT_READBACK', 'ordinal', '0'),
        ('FULL_ADF_SET_INPUT_APPLIED', 'AB_status', '0'),
        ('FULL_ADF_SET_INPUT_AIP_DISPATCH', 'task_rc', '0'),
        ('FULL_BB_MODE_OUTER_WORK', 'snapshot_fnv', '0' * 16),
        ('FULL_BB_SET_MODE_REPLY_FREE', 'pointer', '0x9999')):
        bad = copy.deepcopy(real); bad.rows(tag)[0]['fields'][field] = value
        rejects(lambda bad=bad: m.verify_legacy(bad, real_id, first_six[0]['REQUEST']['line']))
    # Original opaque request word is part of the saved request, not a zero field.
    key = m.SEVENTH[3]; after = first_six[-1]['REPLY_FREE']['line']; before = len(real.lines)
    accepts(lambda: m.verify_get(real, key, real_id, first_six[-1]['caller'], after, before))
    # Inspect the unfixed batch without accepting edge7 or invoking build/evaluate.
    raw = (m.BASE / 'menu-runs/run-wv99y4lx/console.log').read_bytes()
    m.require(m.sha(raw) == 'b4435f3d962a5bfd7e2534f54582dfb054a655d8a5cdd8dcc3ae06707a7e95fb',
              'unfixed batch diagnostic baseline changed')
    batch = m.Log(raw)
    old_edges, old_identity, *_ = accepts(lambda: m.six.verify_graph(batch))
    first = old_edges[0]['REQUEST']['line']; previous = old_edges[-1]['REPLY_FREE']['line']
    rejects(lambda: m.verify_new_edge(batch, m.NEW[0], previous, old_identity, first), 'sender')
    checked_later = []
    for index, spec in enumerate(m.NEW):
        request = batch.one(spec[0] + '_REQUEST')
        caller = int(request['fields']['source'], 0)
        for pin in spec[3:]:
            accepts(lambda pin=pin: m.verify_get(batch, pin, old_identity, caller, previous, request['line']))
        if index:
            checked_later.append(accepts(lambda: m.verify_new_edge(batch, spec, previous, old_identity, first)))
        free_tag = '_NATIVE_REPLY_FREE' if 0 < index < 4 else '_REPLY_FREE'
        previous = batch.one(spec[0] + free_tag)['line']
    accepts(lambda: m.verify_remaining(batch, checked_later[2], checked_later[3], old_identity))
    audits = accepts(lambda: m.verify_audits(batch))
    assert len(audits) == 40 and all(a['metadata']['fields']['complete'] == '1' for a in audits)
    with patch.object(m.old, 'exited_processes', side_effect=AssertionError('offline tests inspected /proc')), \
         patch.object(m.old, 'verify_locks', side_effect=AssertionError('offline tests attempted locks')):
        with tempfile.TemporaryDirectory(prefix='graph-batch-self-test-') as directory:
            with patch.object(m, 'EXPECTED_OBSERVER_SHA256', ''), patch.object(m, 'EXPECTED_ABI_SHA256', ''), \
                 patch.object(m, 'EXPECTED_SOURCE_COUNT', 0):
                rejects(lambda: m.evaluate(Path(directory)))
            m.require(not list(Path(directory).glob('*evaluation.json')), 'partial evidence wrote success')
            checks += 1
    print(json.dumps({'self_test_checks_passed': checks, 'real_archived_first_six_replayed': True,
        'synthetic_new_edge_fixture_only': True, 'unfixed_batch_edge7_rejected_for_missing_sender': True,
        'unfixed_batch_later_edges_replayed_for_diagnostics_only': 4,
        'VM_contacted': False, 'locks_attempted': False,
        'native_evidence_generated': False}, indent=2))


if __name__ == '__main__':
    path = Path(__file__).with_name('evaluate-graph-batch-native.py')
    spec = importlib.util.spec_from_file_location('graph_batch_evaluator', path)
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    run_tests(module)
