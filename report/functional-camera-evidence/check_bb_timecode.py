"""BB timecode software controls: exact native bytes and original receive/free.

Loaded by check_evidence only for this producer family or its explicit policy.
No Core opcode, frame, media, CP RAM, RTOS, or physical compatibility claim.
"""
import re
import struct

FAMILY = 'FUNCTIONAL_BB_TIMECODE_'
AUDIT = 'NATIVE_BB_TIMECODE_INPUT_AUDIT'
AUDIT_FAMILY = 'NATIVE_BB_TIMECODE_'
CP = 0x92840747
POLICY = {
    'bb_timecode_control_policy': 'virtual-bb-timecode-controls-v1',
    'bb_timecode_control_native_commands': [1024, 1025, 1026],
    'bb_timecode_control_request_bytes': 10,
    'bb_timecode_control_reply_bytes': 12,
    'bb_timecode_control_state_bytes': 48,
    'bb_timecode_control_input_policy': 'exact200d10-8001-bool0,1-byte9zero-original-local-source',
    'bb_timecode_control_state_policy': 'owned3bool-knownmask-generation-independent-State48-v1',
    'bb_timecode_control_reply_policy': 'independent200d-command-plus1000-plain0-after-state-readback-and-original-request-free',
    'bb_timecode_control_retirement_policy': 'actual-original-receive-and-same-sender-free-before-next-transaction',
    'bb_timecode_control_fifo_policy': 'explicit-single-pending-actual-source-sender-lease-no-original-RTOS-identity-claim',
    'bb_timecode_control_original_fifo_identity_verified': False,
    'bb_timecode_control_frame_production_supported': False,
    'bb_timecode_control_physical_semantics_verified': False,
}
EVENTS = ('BEGIN', 'STATE_WRITTEN', 'STATE_READBACK', 'REQUEST_FREE', 'REPLY_QUEUED',
          'RECEIVE', 'REPLY_FREE', 'COMMIT')
RESOURCE_SUFFIXES = ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')
EVENT_ORDER = (
    'event pid tid transaction command source request_pointer reply_pointer sender_tid receiver_tid '
    'generation known_mask tcmode dfmode run command_generation0 command_generation1 command_generation2 '
    'input_fnv state_fnv reply_fnv result rc allocate_rc send_rc request_free_rc reply_free_rc cleanup_rc '
    'request_free_count reply_free_count busy_count guard_failures requests applications initialized busy '
    'guard_held faults queued request_freed reply_received reply_freed ap_consumed inflight pending_commit '
    'retained_request live_reply retained_reply retained_cleanup software_model original_CP physical frames '
    'capture native_CP_verified original_RTOS_verified capture_verified physical_asic_compatibility_verified minimal_business_patch').split()
BYTES_ORDER = ('event kind total offset bytes raw whole_fnv pid tid transaction command source '
               'request_pointer reply_pointer sender_tid receiver_tid').split()
AUDIT_ORDER = ('pid tid sequence pointer source destination command bytes raw fnv1a64 producer_return '
               'appfw_base caller_raw original_sender_bound consumed state_verified diagnostic_only '
               'original_CP physical_ASIC_verified capture_verified').split()
SCOPE = dict(software_model='1', original_CP='0', physical='0', frames='0', capture='0',
             native_CP_verified='0', original_RTOS_verified='0', capture_verified='0',
             physical_asic_compatibility_verified='0', minimal_business_patch='null')
BITS = set(('initialized busy guard_held queued request_freed reply_received reply_freed ap_consumed '
            'inflight pending_commit retained_request live_reply retained_reply retained_cleanup').split())
SIGNED = set('rc allocate_rc send_rc request_free_rc reply_free_rc cleanup_rc'.split())
HASHES = {'input_fnv', 'state_fnv', 'reply_fnv', 'whole_fnv', 'fnv1a64'}
DEPENDENCIES = ('report/functional-camera-evidence/check_bb_timecode.py',
                'report/functional-camera-evidence/test_bb_timecode.py',
                'runtime/analysis/device-models/bb-timecode-control.c',
                'runtime/analysis/device-models/bb-timecode-control.h',
                'runtime/analysis/menu-observe.c', 'runtime/analysis/backup_profile.py')


def selected(manifest):
    return any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
               if type(target) is dict for key, value in target.items()
               if key.startswith('functional_camera_bb_timecode_control_'))


def policy(manifest, api, observed=False):
    if not observed and not selected(manifest):
        return False
    backup = manifest.get('backup_transport')
    keys = {'functional_camera_' + key for key in POLICY}
    api.require(type(backup) is dict and all(target.get('functional_camera_profile') == api.PROFILE and
        {key for key in target if key.startswith('functional_camera_bb_timecode_control_')} == keys and
        all(api.typed_equal(target.get('functional_camera_' + key), value) for key, value in POLICY.items())
        for target in (manifest, backup)), 'typed functional profile drift: BB timecode exact typed 13-key software policy differs')
    return True


def source_bindings(manifest, api, frozen=None):
    """Use the cohort's real production source index and original selected-image SHA."""
    sources = manifest.get('compiled_observer', {}).get('sources', {})
    files = manifest.get('files', {})
    for relative in DEPENDENCIES:
        path = api.NATIVE / relative
        actual = api.read_absolute(path, 16 * 1024**2)
        digest = api.sha(actual)
        if relative.startswith('runtime/analysis/device-models/') or relative.endswith('menu-observe.c'):
            entry = sources.get(str(path), {})
            api.require(entry.get('sha256') == digest, 'BB timecode production source not indexed: ' + relative)
        else:
            api.require(files.get(str(path)) == digest, 'BB timecode reader/profile source not indexed: ' + relative)
        if frozen is not None:
            api.require(frozen.get(str(path)) == digest, 'BB timecode dependency not cohort-frozen: ' + relative)
    name = 'usr/lib/appFw.so'
    expected = api.PUBLIC_LIBRARIES[name]
    api.require(manifest.get('original_libraries_unchanged') is True and
                manifest.get('selected_initramfs_verified_files', {}).get(name) == expected,
                'BB timecode original appFw selected-image SHA differs')
    actual = api.read(api.RUNTIME / 'menu-root', name)
    api.digest_binding(actual, expected, 'BB timecode actual original appFw')
    return len(actual)


def producer_fields(tag, fields, api):
    """Exact landed C formatters, including leading zeros emitted by %04x/%08x."""
    if tag.startswith(FAMILY) and tag[len(FAMILY):] in RESOURCE_SUFFIXES:
        alias = 'FUNCTIONAL_CP_OU_CRANK_CONTROL_' + tag[len(FAMILY):]
        payload = (alias + ' ' + ' '.join(key + '=' + value for key, value in fields.items())).encode('ascii')
        return fields if api.console_producer_fields(payload) == fields else None
    order = {FAMILY + 'EVENT': EVENT_ORDER, FAMILY + 'BYTES': BYTES_ORDER, AUDIT: AUDIT_ORDER}.get(tag)
    if order is None or list(fields) != order:
        return None
    for key, text in fields.items():
        if type(text) is not str:
            return None
        if key == 'event':
            valid = text in (*EVENTS, 'FAULT', 'REFUSED')
        elif key == 'kind':
            valid = text in ('request', 'state_before', 'state_after', 'reply')
        elif key == 'minimal_business_patch':
            valid = text == 'null'
        elif key in HASHES:
            valid = re.fullmatch(r'[0-9a-f]{16}', text)
        elif key == 'raw':
            valid = re.fullmatch(r'(?:[0-9a-f]{2})+', text)
        elif key == 'command':
            valid = re.fullmatch(r'0x0[0-9a-f]{3}' if tag != AUDIT else r'0x[1-9a-f][0-9a-f]{0,7}', text)
        elif key == 'source':
            valid = re.fullmatch(r'0x[0-9a-f]{8}' if tag != AUDIT else r'0x[1-9a-f][0-9a-f]{0,7}', text)
        elif key in ('pointer', 'producer_return'):
            valid = re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', text)
        elif key in ('request_pointer', 'reply_pointer'):
            valid = re.fullmatch(r'0x(?:0|[1-9a-f][0-9a-f]{0,15})', text)
        elif key in ('destination', 'appfw_base', 'caller_raw'):
            valid = re.fullmatch(r'(?:0|0x[1-9a-f][0-9a-f]{0,15})', text)
        elif key in SIGNED:
            valid = re.fullmatch(r'(?:0|-?[1-9][0-9]{0,9})', text) and -2**31 <= int(text) < 2**31
        elif key in BITS or key in SCOPE or key in ('original_sender_bound', 'consumed', 'state_verified',
                                                  'diagnostic_only', 'physical_ASIC_verified'):
            valid = text in ('0', '1')
        else:
            valid = re.fullmatch(r'(?:0|[1-9][0-9]{0,19})', text) and int(text) < 2**64
        if not valid:
            return None
    if tag == FAMILY + 'BYTES':
        total, event = {'request': (10, 'BEGIN'), 'state_before': (48, 'BEGIN'),
                        'state_after': (48, 'STATE_READBACK'), 'reply': (12, 'STATE_READBACK')}[fields['kind']]
        if not (fields['event'] == event and fields['total'] == fields['bytes'] == str(total) and
                fields['offset'] == '0' and len(fields['raw']) == 2 * total):
            return None
    if tag == AUDIT and (fields['bytes'] != '10' or len(fields['raw']) != 20):
        return None
    return fields


def resources(rows, begin, written, pid, sender, base, api):
    held = [row for row in rows if row['tag'].startswith(FAMILY + 'RESOURCE') and
            begin < row['line'] < written]
    api.require([row['tag'] for row in held] == [FAMILY + suffix for suffix in RESOURCE_SUFFIXES],
                'BB timecode resource37 missing/reordered/repeated')
    dep, table, reserved = (row['fields'] for row in held)
    api.require(int(dep['pid']) == int(table['pid']) == pid and
                all(int(row['fields']['tid']) == sender for row in held) and int(table['appfw_base'], 16) == base,
                'BB timecode resource37 original PID/TID/module base differs')
    fixed = dict(dmm_enabled='1', dmm_bound='1', dmm_slots='1/1', dmm_opens='1/1',
        dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
        dmm_allocation_count='2', dmm_lifecycle_changed='0', dmm_domain='2', foreign_speech_kept='1',
        control_bound='1', connection_started='1', connections='1', format_consumed='1', buffer_released='1',
        connection_reply_frees='1', vef_init='1', vef_owner='0x905a0048', pinmem_init='1', pinmem_owner='0x90590818')
    api.require(all(reserved[key] == value for key, value in fixed.items()) and
                int(reserved['allocations']) == int(reserved['releases']) > 0 and
                int(reserved['vef_objects']) > 0 and int(reserved['pinmem_objects']) > 0,
                'BB timecode resource37 quiet owner/DMM/registry predicate differs')
    speech = api.raw_hex(table, 'raw_before', 144)
    api.require(api.raw_hex(table, 'raw_after', 144) == speech, 'BB timecode TTS144 readback changed')
    for slot in range(2):
        offset = slot * 0x48
        api.require(struct.unpack_from('<I', speech, offset)[0] == 0x1a + slot and
                    struct.unpack_from('<2I', speech, offset + 0x18) == (0x8400 | slot, 0x80000) and
                    struct.unpack_from('<Q', speech, offset + 0x20)[0] == 0x1e000000 + slot * 0x80000,
                    'BB timecode TTS144 actual slot binding differs')
    return [row['line'] for row in held]


def predecessors(rows, transport, begin, api):
    """Transport has already validated actual OP23 bytes and every old predecessor."""
    pid, instance = transport['pid'], transport['model_instance']
    proof = transport.get('ou_crank_control_content', {})
    completed = [item for item in proof.get('transactions', []) if item['complete_line'] < begin]
    api.require(proof.get('verified') is True and completed, 'BB timecode lacks validated original OP23 content')
    current = completed[-1]
    native = [row for row in rows if row['tag'] == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT' and row['line'] < begin]
    api.require(native and native[-1]['line'] == current['complete_line'], 'BB timecode newer/live OP23 predecessor')
    f = native[-1]['fields']
    api.require(f.get('event') == 'COMMIT' and int(f['transaction']) == current['transaction'] and
        int(f['pid']) == pid and int(f['model_instance']) == instance and
        all(f.get(key) == '1' for key in ('model_called', 'model_committed', 'verified', 'owned', 'complete', 'request_freed', 'oneway')) and
        all(f.get(key) == '0' for key in ('busy', 'guard', 'guard_fault', 'faults', 'error', 'before_rc',
            'model_rc', 'after_rc', 'validation_rc', 'free_rc', 'releasing', 'ACK_sent', 'notification_sent',
            'frame', 'capture', 'capture_verified')) and
        all(f.get(key) == f['transaction'] for key in ('requests', 'commits', 'verified_commits', 'completions', 'released')) and
        int(f['config_generation']) == int(f['before_config_generation']) + 1 and f.get('mode') == '0' and
        f.get('retained_request') == '(nil)' and int(f['free_tid']) == int(f['sender_tid']) > 0,
        'BB timecode original OP23 is not actually retired/oneway/clean')
    mode = api.cp_parameter_mode_retirement(rows, begin, pid, instance)
    queued = [row for row in rows if row['tag'] == 'FULL_BB_SET_MODE_REPLY_QUEUED' and row['line'] < begin]
    commits = [row for row in rows if row['tag'] == 'FULL_BB_SET_MODE_COMMIT' and row['line'] < begin]
    frees = [row for row in rows if row['tag'] == 'FULL_BB_SET_MODE_REPLY_FREE' and row['line'] < begin]
    api.require(len(queued) == len(commits) == len(frees) == 1 and not any(
        row['tag'] in ('FULL_BB_SET_MODE_FAULT', 'FULL_BB_SET_MODE_RECOVERY_FREE') for row in rows),
        'BB timecode original BB0110 retirement missing/faulted/replayed')
    q, c, freed = (group[0] for group in (queued, commits, frees))
    api.require(q['line'] < c['line'] < begin and q['line'] != freed['line'] and max(c['line'], freed['line']) < begin,
                'BB timecode BB0110 queue/commit/free order differs')
    heads = ('generation destination source reply bytes raw target operation_mode two_internal_completions unique_reply',
             'generation request request_free_rc retained_request clean_completion queued ap_consumed',
             'generation destination expected pointer kind rc faults retained ap_consumed metadata_completion_only')
    tail = ('pid tid original_cp_executed hardware_verified native_frequency_verified original_event_identity_verified '
            'pcm_verified frames_verified capture_verified')
    for row, head in zip((q, c, freed), heads):
        f = row['fields']
        api.require(list(f) == (head + ' ' + tail).split() and all(re.fullmatch(r'[1-9][0-9]*', f[key])
                    and int(f[key]) < 2**31 for key in ('pid', 'tid')), 'BB timecode BB0110 exact producer schema differs')
        api.require('diagnostic' not in row and int(f['pid']) == pid and f['generation'] == '1' and
                    all(f.get(key) == '0' for key in ('original_cp_executed', 'hardware_verified',
                        'native_frequency_verified', 'original_event_identity_verified', 'pcm_verified', 'frames_verified', 'capture_verified')),
                    'BB timecode original BB0110 source scope differs')
    api.require(q['fields']['raw'] == '0d2010110c00018000000000' and q['fields']['bytes'] == '12' and
                q['fields']['source'] == '0x92840747' and q['fields']['target'] == '3' and
                all(q['fields'][key] == '1' for key in ('two_internal_completions', 'unique_reply')) and
                q['fields']['operation_mode'] == '0' and
                all(c['fields'][key] == value for key, value in dict(request_free_rc='0', retained_request='0',
                    clean_completion='1', queued='1', ap_consumed='0').items()) and
                freed['fields']['pointer'] == q['fields']['reply'] and
                freed['fields']['destination'] == freed['fields']['expected'] == q['fields']['destination'] and
                all(freed['fields'][key] == value for key, value in dict(kind='queued-reply', rc='0', faults='0',
                    retained='0', ap_consumed='1', metadata_completion_only='1').items()),
                'BB timecode BB0110 actual independent reply/request free differs')
    return dict(ou_complete_line=current['complete_line'], current_mode_retired_line=mode['line'],
                bb0110_free_line=freed['line'])


def check(run, manifest, rows, transport, api):
    native = [row for row in rows if row['tag'].startswith((FAMILY, AUDIT_FAMILY))]
    result = dict(status='not_observed', required=bool(native), verified=False, transactions=[],
        content_join_verified=False, native_completion_verified=False, native_virtual_controls_verified=False,
        commands_observed=[], all_three_complete=False, frame_consumed=False, capture_verified=False,
        physical_asic_compatibility_verified=False, original_CP_executed=False, original_CP_RAM_verified=False,
        original_RTOS_verified=False, original_fifo_identity_verified=False, minimal_business_patch=None)
    policy(manifest, api, bool(native))
    if not native:
        return result
    module_size = source_bindings(manifest, api)
    api.require(transport.get('verified') is True and 1 < transport['pid'] < 2**31 and
                0 < transport['model_instance'] < 2**64, 'BB timecode requires validated same-run transport')
    for row in native:
        api.require('diagnostic' not in row and producer_fields(row['tag'], row['fields'], api) == row['fields'],
                    'BB timecode failed/unknown/incomplete original formatter')
    api.require([row['line'] for row in native] == sorted({row['line'] for row in native}),
                'BB timecode original line identity/order differs')
    events = [row for row in native if row['tag'] == FAMILY + 'EVENT']
    ids = sorted({int(row['fields']['transaction']) for row in events})
    api.require(ids and ids == list(range(1, len(ids) + 1)) and
                {int(row['fields']['transaction']) for row in native if row['tag'] == FAMILY + 'BYTES'} == set(ids),
                'BB timecode transaction/event/bytes census differs')
    audits = [row for row in native if row['tag'] == AUDIT]
    sequences = [int(row['fields']['sequence']) for row in audits]
    api.require(len(audits) == len(ids) and sequences == sorted(set(sequences)) and min(sequences) > 0,
                'BB timecode original audit missing/duplicate/replayed')
    prior = struct.pack('<4IQ4IQ', 1, 48, transport['pid'], 0, 0, 0, 0, 0, 0, 0)
    generations, previous_end, covered = [0, 0, 0], 0, set()
    for transaction in ids:
        group = [row for row in events if int(row['fields']['transaction']) == transaction]
        api.require(len(group) == len(EVENTS) and {row['fields']['event'] for row in group} == set(EVENTS),
                    'BB timecode FAULT/refusal/missing/duplicate lifecycle')
        at = {row['fields']['event']: row for row in group}
        line = lambda name: at[name]['line']
        api.require(previous_end < line('BEGIN') < line('STATE_WRITTEN') < line('STATE_READBACK') <
                    line('REQUEST_FREE') < min(line('REPLY_QUEUED'), line('RECEIVE')) and
                    line('RECEIVE') < line('REPLY_FREE') < line('COMMIT') and
                    line('REPLY_QUEUED') < line('COMMIT') and group[-1] is at['COMMIT'],
                    'BB timecode original work/receive/free/commit partial order differs')
        first, final = at['BEGIN']['fields'], at['COMMIT']['fields']
        pid, sender, command, source = (int(first[key], 0) for key in ('pid', 'sender_tid', 'command', 'source'))
        request_pointer, reply_pointer = int(first['request_pointer'], 16), int(final['reply_pointer'], 16)
        api.require(pid == transport['pid'] and 0 < sender < 2**31 and 0x400 <= command <= 0x402 and
                    0x80000001 <= source <= 0x8fffffff and 0 < request_pointer <= 2**64 - 10 and
                    0 < reply_pointer <= 2**64 - 12 and
                    (request_pointer + 10 <= reply_pointer or reply_pointer + 12 <= request_pointer),
                    'BB timecode original owner/source/command or independent reply differs')
        chunks = [row for row in native if row['tag'] == FAMILY + 'BYTES' and
                  int(row['fields']['transaction']) == transaction]
        api.require(len(chunks) == 4 and {row['fields']['kind'] for row in chunks} ==
                    {'request', 'state_before', 'state_after', 'reply'}, 'BB timecode requires four complete actual byte objects')
        data = {}
        chunk_lines = {row['fields']['kind']: row['line'] for row in chunks}
        api.require(chunk_lines['request'] < chunk_lines['state_before'] and
                    chunk_lines['state_after'] < chunk_lines['reply'], 'BB timecode original byte-object order differs')
        for row in chunks:
            f, kind = row['fields'], row['fields']['kind']
            raw = api.raw_hex(f, 'raw', {'request': 10, 'state_before': 48, 'state_after': 48, 'reply': 12}[kind])
            api.require(int(f['pid']) == pid and int(f['tid']) == int(f['sender_tid']) == sender and
                int(f['receiver_tid']) == 0 and f['command'] == first['command'] and f['source'] == first['source'] and
                int(f['request_pointer'], 16) == request_pointer and int(f['reply_pointer'], 16) ==
                (0 if kind in ('request', 'state_before') else reply_pointer) and
                f['whole_fnv'] == f'{api.fnv(raw):016x}' and
                (line('BEGIN') < row['line'] < line('STATE_WRITTEN') if kind in ('request', 'state_before') else
                 line('STATE_READBACK') < row['line'] < line('REQUEST_FREE')),
                'BB timecode actual byte identity/phase/FNV differs')
            data[kind] = raw
        packet, before, after, reply = (data[key] for key in ('request', 'state_before', 'state_after', 'reply'))
        api.require(packet == struct.pack('<4H2B', 0x200d, command, 10, 0x8001, packet[8], 0) and packet[8] in (0, 1) and
                    reply == struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0),
                    'BB timecode complete original bool10/source-compatible reply12 differs')
        api.require(before == prior, 'BB timecode State48 history/initial-known-mask-zero differs')
        state = list(struct.unpack('<4IQ4IQ', before))
        index = command - 0x400
        state[3] |= 1 << index
        state[4] += 1
        state[5 + index] = packet[8]
        state[9] += 1
        expected = struct.pack('<4IQ4IQ', *state)
        api.require(after == expected and state[:3] == [1, 48, pid] and state[8] == 0 and
                    all(value in (0, 1) for value in state[5:8]), 'BB timecode full independent State48 delta/schema differs')
        found = [row for row in audits if previous_end < row['line'] < line('BEGIN') and
                 row['fields']['pointer'] == hex(request_pointer) and row['fields']['raw'] == packet.hex() and
                 int(row['fields']['pid']) == pid and int(row['fields']['tid']) == sender]
        api.require(len(found) == 1, 'BB timecode unique original10B caller audit missing/cross-transaction')
        audit = found[0]; f = audit['fields']; base = int(f['appfw_base'], 16)
        api.require(int(f['source'], 16) == source and int(f['destination'], 16) == CP and
            int(f['command'], 16) == command and f['fnv1a64'] == f'{api.fnv(packet):016x}' and
            0x10000 <= base < 0x7ff0000000 and int(f['caller_raw'], 16) == 0x34e56e8 < module_size and
            int(f['producer_return'], 16) == base + 0x34e56e8 and
            all(f[key] == value for key, value in dict(original_sender_bound='1', consumed='0', state_verified='0',
                diagnostic_only='1', original_CP='0', physical_ASIC_verified='0', capture_verified='0').items()),
            'BB timecode original appFw actual return/module/source/full10 seal differs')
        covered.add(audit['line'])
        resource_lines = resources(native, line('BEGIN'), line('STATE_WRITTEN'), pid, sender, base, api)
        api.require(chunk_lines['state_before'] < min(resource_lines), 'BB timecode input bytes follow resource reservation')
        covered.update(resource_lines)
        parents = predecessors(rows, transport, line('BEGIN'), api)
        next_generations = generations.copy(); next_generations[index] = transaction
        for row in group:
            f, name = row['fields'], row['fields']['event']
            begun, written = name == 'BEGIN', name != 'BEGIN'
            received = line('RECEIVE') <= row['line']
            freed = line('REPLY_FREE') <= row['line']
            queued = line('REPLY_QUEUED') <= row['line']
            request_freed = line('REQUEST_FREE') <= row['line']
            complete = name == 'COMMIT'
            current = struct.unpack('<4IQ4IQ', after if written else before)
            expected_fields = dict(pid=pid, tid=sender, transaction=transaction, command=command, source=source,
                request_pointer=request_pointer, reply_pointer=0 if begun else reply_pointer,
                sender_tid=sender, receiver_tid=sender if received else 0, generation=current[4], known_mask=current[3],
                tcmode=current[5], dfmode=current[6], run=current[7], requests=transaction, applications=current[9],
                rc=0, result=0, allocate_rc=-115 if begun else 0, send_rc=0 if queued else -115,
                request_free_rc=0 if request_freed else -115, reply_free_rc=0 if freed else -115, cleanup_rc=-115,
                request_free_count=transaction if request_freed else transaction - 1,
                reply_free_count=transaction if freed else transaction - 1, busy_count=0, guard_failures=0,
                initialized=1, busy=int(not complete), faults=0, queued=int(queued), request_freed=int(request_freed),
                reply_received=int(received), reply_freed=int(freed), ap_consumed=int(complete),
                pending_commit=int(freed and not complete), retained_request=int(written and not request_freed),
                live_reply=int(name in ('RECEIVE', 'REPLY_QUEUED') and not freed),
                retained_reply=int(written and not freed), retained_cleanup=0)
            expected_fields.update({'command_generation' + str(i): value for i, value in
                                    enumerate(next_generations if written else generations)})
            api.require(all(int(f[key], 0) == value for key, value in expected_fields.items()) and
                all(f[key] == value for key, value in SCOPE.items()) and
                f['input_fnv'] == f'{api.fnv(packet):016x}' and
                f['reply_fnv'] == (f'{api.fnv(reply):016x}' if written else '0000000000000000') and
                f['state_fnv'] == f'{api.fnv(before if name in ("BEGIN", "STATE_WRITTEN") else after):016x}',
                'BB timecode actual event/state/flags/rc/retained/hash differs: ' + name)
            guard, inflight = int(f['guard_held']), int(f['inflight'])
            allowed = ({(0, 0)} if begun or complete else {(1, 0)} if name in
                ('STATE_WRITTEN', 'STATE_READBACK', 'REQUEST_FREE') else {(1, 1)} if name == 'REPLY_QUEUED' else
                {(1, 1)} if not queued else {(1, 1), (0, 0)})
            api.require((guard, inflight) in allowed, 'BB timecode inline/free send-inflight guard state differs')
        result['transactions'].append(dict(transaction=transaction, command=command, source=source, sender_tid=sender,
            generation=transaction, known_mask=state[3], source_audit_sequence=int(audit['fields']['sequence']),
            original_return_raw=0x34e56e8, appfw_base=base, original_appfw_sha256=api.PUBLIC_LIBRARIES['usr/lib/appFw.so'],
            request_sha256=api.sha(packet), state_before_sha256=api.sha(before), state_after_sha256=api.sha(after),
            reply_sha256=api.sha(reply), receive_line=line('RECEIVE'), reply_free_line=line('REPLY_FREE'),
            complete_line=line('COMMIT'), inline_free=line('REPLY_FREE') < line('REPLY_QUEUED'), **parents))
        prior, generations, previous_end = after, next_generations, line('COMMIT')
    api.require(covered == {row['line'] for row in native if row['tag'] == AUDIT or
                row['tag'].startswith(FAMILY + 'RESOURCE')}, 'BB timecode orphan/borrowed resource37 or original input audit')
    commands = sorted({item['command'] for item in result['transactions']})
    result.update(status='native_virtual_controls_verified', verified=True, content_join_verified=True,
                  native_completion_verified=True, native_virtual_controls_verified=True,
                  commands_observed=commands, all_three_complete=commands == [0x400, 0x401, 0x402])
    return result
