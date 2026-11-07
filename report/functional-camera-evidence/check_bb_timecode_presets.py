"""Exact preset content joins; explicit functional model, never physical CP proof.

Uses the unchanged TC reader for its formatter grammar, source closure and typed
resource37 validation. Only these two commands own the separate PresetState48.
"""
import re
import struct

FAMILY = 'FUNCTIONAL_BB_TIMECODE_PRESET_'
AUDIT = 'NATIVE_BB_TIMECODE_PRESET_INPUT_AUDIT'
AUDIT_FAMILY = 'NATIVE_BB_TIMECODE_PRESET_'
CP = 0x92840747
COMMAND_BYTES = {0x40a: 12, 0x409: 10}
PRESET_ORDER = ('preset_generation preset_known_mask preset_raw4 ubmode_wire '
                'preset_command_generation0 preset_command_generation1 preset_applications').split()
POLICY = {
    'bb_timecode_preset_policy': 'virtual-bb-timecode-presets-v1',
    'bb_timecode_preset_native_commands': [1034, 1033],
    'bb_timecode_preset_request_sizes': {'0x040a': 12, '0x0409': 10},
    'bb_timecode_preset_reply_bytes': 12,
    'bb_timecode_preset_state_bytes': 48,
    'bb_timecode_preset_input_policy': 'exact200d-040a12-raw4u8-040910-LE16enum0,1-8001-original-local-source',
    'bb_timecode_preset_state_policy': 'owned-raw4-wire-selector-knownmask-generation-independent-PresetState48-v1',
    'bb_timecode_preset_reply_policy': 'independent200d-140a,1409-plain0-after-state-readback-and-original-request-free',
    'bb_timecode_preset_retirement_policy': 'actual-original-receive-and-same-sender-free-before-next-transaction',
    'bb_timecode_preset_predecessor_policy': 'actual-three-TC-COMMITs-before040a-actual040a-COMMIT-before0409',
    'bb_timecode_preset_native_CP_verified': False,
    'bb_timecode_preset_frame_production_supported': False,
    'bb_timecode_preset_physical_semantics_verified': False,
}
DEPENDENCIES = ('report/functional-camera-evidence/check_bb_timecode_presets.py',
                'report/functional-camera-evidence/test_bb_timecode_presets.py',
                'report/functional-camera-evidence/check_evidence.py')


def selected(manifest):
    return any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
               if type(target) is dict for key, value in target.items()
               if key.startswith('functional_camera_bb_timecode_preset_'))


def policy(manifest, api, observed=False):
    if not observed and not selected(manifest):
        return False
    backup = manifest.get('backup_transport')
    keys = {'functional_camera_' + key for key in POLICY}
    api.require(type(backup) is dict and all(target.get('functional_camera_profile') == api.PROFILE and
        {key for key in target if key.startswith('functional_camera_bb_timecode_preset_')} == keys and
        all(api.typed_equal(target.get('functional_camera_' + key), value) for key, value in POLICY.items())
        for target in (manifest, backup)), 'typed functional profile drift: BB timecode preset exact typed 13-key policy differs')
    return True


def source_bindings(manifest, api, frozen=None):
    size = api.bb_timecode_module().source_bindings(manifest, api, frozen)
    for relative in DEPENDENCIES:
        path = api.NATIVE / relative
        digest = api.sha(api.read_absolute(path, 16 * 1024**2))
        api.require(manifest.get('files', {}).get(str(path)) == digest,
                    'BB preset reader source not indexed: ' + relative)
        if frozen is not None:
            api.require(frozen.get(str(path)) == digest, 'BB preset dependency not cohort-frozen: ' + relative)
    return size


def producer_fields(tag, fields, api):
    """Reuse the old scalar grammar; validate the different request sizes first."""
    old = api.bb_timecode_module()
    if tag == FAMILY + 'EVENT':
        if list(fields) != old.EVENT_ORDER + PRESET_ORDER:
            return None
        base = {key: fields[key] for key in old.EVENT_ORDER}
        result = base['result']
        if type(result) is not str or re.fullmatch(r'(?:0|-?[1-9][0-9]{0,9})', result) is None or not -2**31 <= int(result) < 2**31:
            return None
        # The new C formatter uses signed %d and keeps -EINPROGRESS until readback.
        base['result'] = '0'
        if old.producer_fields(old.FAMILY + 'EVENT', base, api) != base:
            return None
        for key in PRESET_ORDER:
            text = fields[key]
            if type(text) is not str:
                return None
            if key == 'preset_raw4':
                valid = re.fullmatch(r'0x[0-9a-f]{8}', text)
            else:
                bits = 32 if key in ('preset_known_mask', 'ubmode_wire') else 64
                valid = re.fullmatch(r'(?:0|[1-9][0-9]{0,19})', text) and int(text) < 2**bits
            if not valid:
                return None
        return fields
    if tag == FAMILY + 'BYTES' or tag == AUDIT:
        order = old.BYTES_ORDER if tag != AUDIT else old.AUDIT_ORDER
        if list(fields) != order or any(type(value) is not str for value in fields.values()):
            return None
        try:
            request_size = COMMAND_BYTES[int(fields['command'], 16)]
        except (KeyError, ValueError):
            return None
        kind = fields.get('kind', 'request')
        if kind not in ('request', 'state_before', 'state_after', 'reply'):
            return None
        size = {'request': request_size, 'state_before': 48, 'state_after': 48, 'reply': 12}[kind]
        if fields['bytes'] != str(size) or re.fullmatch(r'[0-9a-f]{' + str(size * 2) + '}', fields['raw']) is None:
            return None
        copy = dict(fields)
        if tag != AUDIT:
            if fields['total'] != str(size) or fields['offset'] != '0':
                return None
            if kind == 'request':
                copy.update(total='10', bytes='10', raw=fields['raw'][:20])
            alias = old.FAMILY + 'BYTES'
        else:
            copy.update(bytes='10', raw=fields['raw'][:20])
            alias = old.AUDIT
        # The full raw object and exact original size were checked above; the
        # legacy call checks all unchanged scalar keys and event/kind binding.
        return fields if old.producer_fields(alias, copy, api) == copy else None
    if tag.startswith(FAMILY) and tag[len(FAMILY):] in old.RESOURCE_SUFFIXES:
        return old.producer_fields(old.FAMILY + tag[len(FAMILY):], fields, api)
    return None


def predecessors(rows, transport, begin, api):
    """Require the independently validated old reader, including every refusal."""
    old = api.bb_timecode_module()
    proof = transport.get('bb_timecode_control', {})
    done = proof.get('transactions', [])
    api.require(proof.get('verified') is True and proof.get('all_three_complete') is True and len(done) == 3 and
        {item['command'] for item in done} == {0x400, 0x401, 0x402} and
        all(item['complete_line'] < begin for item in done), 'BB preset lacks actual validated three-TC COMMIT prerequisite')
    commits = [row for row in rows if row['tag'] == old.FAMILY + 'EVENT' and
               row['fields'].get('event') == 'COMMIT' and row['line'] < begin]
    api.require([row['line'] for row in commits] == [item['complete_line'] for item in done],
                'BB preset old TC content/line identity differs')
    final = commits[-1]['fields']
    api.require(int(final['pid']) == transport['pid'] and final['generation'] == final['applications'] == '3' and
                final['known_mask'] == '7' and final['transaction'] == final['requests'] == '3' and
                final['request_free_count'] == final['reply_free_count'] == '3',
                'BB preset old TC state/counters are not the retired three-command epoch')
    return final, done[-1]


def check(run, manifest, rows, transport, api):
    old = api.bb_timecode_module()
    native = [row for row in rows if row['tag'].startswith((FAMILY, AUDIT_FAMILY))]
    result = dict(status='not_observed', required=bool(native), verified=False, transactions=[],
        content_join_verified=False, native_completion_verified=False, native_virtual_controls_verified=False,
        commands_observed=[], all_two_complete=False, frame_consumed=False, capture_verified=False,
        physical_asic_compatibility_verified=False, original_CP_executed=False, original_CP_RAM_verified=False,
        original_RTOS_verified=False, original_fifo_identity_verified=False, minimal_business_patch=None)
    policy(manifest, api, bool(native))
    if not native:
        return result
    module_size = source_bindings(manifest, api)
    api.require(transport.get('verified') is True and 1 < transport['pid'] < 2**31 and
                0 < transport['model_instance'] < 2**64, 'BB preset requires validated same-run transport')
    for row in native:
        api.require('diagnostic' not in row and producer_fields(row['tag'], row['fields'], api) == row['fields'],
                    'BB preset failed/unknown/incomplete original formatter')
    api.require([row['line'] for row in native] == sorted({row['line'] for row in native}),
                'BB preset original line identity/order differs')
    events = [row for row in native if row['tag'] == FAMILY + 'EVENT']
    ids = sorted({int(row['fields']['transaction']) for row in events})
    api.require(ids and ids == list(range(4, 4 + len(ids))) and
        {int(row['fields']['transaction']) for row in native if row['tag'] == FAMILY + 'BYTES'} == set(ids),
        'BB preset shared transaction/event/bytes census differs')
    audits = [row for row in native if row['tag'] == AUDIT]
    sequences = [int(row['fields']['sequence']) for row in audits]
    api.require(len(audits) == len(ids) and sequences == sorted(set(sequences)) and min(sequences) > 0,
                'BB preset original audit missing/duplicate/replayed')
    prior = struct.pack('<4IQ4IQ', 1, 48, transport['pid'], 0, 0, 0, 0, 0, 0, 0)
    generations, covered = [0, 0], set()
    baseline, predecessor = predecessors(rows, transport, min(row['line'] for row in events), api)
    previous_end = predecessor['complete_line']
    previous_sequence = 0
    for ordinal, transaction in enumerate(ids, 1):
        group = [row for row in events if int(row['fields']['transaction']) == transaction]
        api.require(len(group) == len(old.EVENTS) and {row['fields']['event'] for row in group} == set(old.EVENTS),
                    'BB preset FAULT/refusal/missing/duplicate lifecycle')
        at = {row['fields']['event']: row for row in group}
        line = lambda name: at[name]['line']
        api.require(previous_end < line('BEGIN') < line('STATE_WRITTEN') < line('STATE_READBACK') <
            line('REQUEST_FREE') < min(line('REPLY_QUEUED'), line('RECEIVE')) and
            line('RECEIVE') < line('REPLY_FREE') < line('COMMIT') and line('REPLY_QUEUED') < line('COMMIT') and
            group[-1] is at['COMMIT'], 'BB preset actual work/receive/free/commit partial order differs')
        first, final = at['BEGIN']['fields'], at['COMMIT']['fields']
        pid, sender, command, source = (int(first[key], 0) for key in ('pid', 'sender_tid', 'command', 'source'))
        size = COMMAND_BYTES.get(command, 0)
        request_pointer, reply_pointer = int(first['request_pointer'], 16), int(final['reply_pointer'], 16)
        api.require(pid == transport['pid'] and 0 < sender < 2**31 and size and 0x80000001 <= source <= 0x8fffffff and
            0 < request_pointer <= 2**64 - size and 0 < reply_pointer <= 2**64 - 12 and
            (request_pointer + size <= reply_pointer or reply_pointer + 12 <= request_pointer),
            'BB preset owner/source/command or independent reply differs')
        chunks = [row for row in native if row['tag'] == FAMILY + 'BYTES' and
                  int(row['fields']['transaction']) == transaction]
        api.require(len(chunks) == 4 and {row['fields']['kind'] for row in chunks} ==
                    {'request', 'state_before', 'state_after', 'reply'}, 'BB preset needs four complete byte objects')
        data, chunk_lines = {}, {row['fields']['kind']: row['line'] for row in chunks}
        api.require(chunk_lines['request'] < chunk_lines['state_before'] and chunk_lines['state_after'] < chunk_lines['reply'],
                    'BB preset actual byte-object order differs')
        for row in chunks:
            f, kind = row['fields'], row['fields']['kind']
            raw = api.raw_hex(f, 'raw', {'request': size, 'state_before': 48, 'state_after': 48, 'reply': 12}[kind])
            api.require(int(f['pid']) == pid and int(f['tid']) == int(f['sender_tid']) == sender and
                int(f['receiver_tid']) == 0 and f['command'] == first['command'] and f['source'] == first['source'] and
                int(f['request_pointer'], 16) == request_pointer and int(f['reply_pointer'], 16) ==
                (0 if kind in ('request', 'state_before') else reply_pointer) and f['whole_fnv'] == f'{api.fnv(raw):016x}' and
                (line('BEGIN') < row['line'] < line('STATE_WRITTEN') if kind in ('request', 'state_before') else
                 line('STATE_READBACK') < row['line'] < line('REQUEST_FREE')), 'BB preset byte identity/phase/FNV differs')
            data[kind] = raw
        packet, before, after, reply = (data[key] for key in ('request', 'state_before', 'state_after', 'reply'))
        provisional_reply = struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 2**32 - 115)
        api.require(packet[:8] == struct.pack('<4H', 0x200d, command, size, 0x8001) and
            (command == 0x40a or struct.unpack_from('<H', packet, 8)[0] in (0, 1)) and
            reply == struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0),
            'BB preset exact raw4/LE16 request or plain result0 reply12 differs')
        api.require(before == prior, 'BB preset independent State48 history/initial known-mask-zero differs')
        state = list(struct.unpack('<4IQ4IQ', before))
        index = 0 if command == 0x40a else 1
        api.require(index == 0 or state[3] & 1 and generations[0] > 0,
                    'BB preset0409 lacks actual earlier040a COMMIT')
        state[3] |= 1 << index
        state[4] += 1
        state[5 + index] = int.from_bytes(packet[8:], 'little')
        state[9] += 1
        api.require(after == struct.pack('<4IQ4IQ', *state), 'BB preset all48 independent state bytes differ')
        found = [row for row in audits if previous_end < row['line'] < line('BEGIN') and
            row['fields']['pointer'] == hex(request_pointer) and row['fields']['raw'] == packet.hex() and
            int(row['fields']['pid']) == pid and int(row['fields']['tid']) == sender]
        api.require(len(found) == 1, 'BB preset unique original caller audit missing/cross-transaction')
        audit = found[0]; f = audit['fields']; base = int(f['appfw_base'], 16)
        api.require(int(f['source'], 16) == source and int(f['destination'], 16) == CP and
            int(f['command'], 16) == command and f['fnv1a64'] == f'{api.fnv(packet):016x}' and
            int(f['sequence']) > previous_sequence and base == predecessor['appfw_base'] and
            0x10000 <= base < 0x7ff0000000 and int(f['caller_raw'], 16) == 0x34e56e8 < module_size and
            int(f['producer_return'], 16) == base + 0x34e56e8 and
            all(f[key] == value for key, value in dict(original_sender_bound='1', consumed='0', state_verified='0',
                diagnostic_only='1', original_CP='0', physical_ASIC_verified='0', capture_verified='0').items()),
            'BB preset original sender/module/source/full request seal differs')
        covered.add(audit['line'])
        resource_rows = [dict(row, tag=old.FAMILY + row['tag'][len(FAMILY):]) for row in native if
                         row['tag'] in {FAMILY + suffix for suffix in old.RESOURCE_SUFFIXES}]
        resource_lines = old.resources(resource_rows, line('BEGIN'), line('STATE_WRITTEN'), pid, sender, base, api)
        api.require(chunk_lines['state_before'] < min(resource_lines), 'BB preset bytes follow resource reservation')
        covered.update(resource_lines)
        next_generations = generations.copy(); next_generations[index] = ordinal
        for row in group:
            f, name = row['fields'], row['fields']['event']
            begun, written = name == 'BEGIN', name != 'BEGIN'
            received, freed = line('RECEIVE') <= row['line'], line('REPLY_FREE') <= row['line']
            queued, request_freed = line('REPLY_QUEUED') <= row['line'], line('REQUEST_FREE') <= row['line']
            complete = name == 'COMMIT'
            current = struct.unpack('<4IQ4IQ', after if written else before)
            expected = dict(pid=pid, tid=sender, transaction=transaction, command=command, source=source,
                request_pointer=request_pointer, reply_pointer=0 if begun else reply_pointer, sender_tid=sender,
                receiver_tid=sender if received else 0, requests=transaction, rc=0,
                result=-115 if name in ('BEGIN', 'STATE_WRITTEN') else 0,
                allocate_rc=-115 if begun else 0, send_rc=0 if queued else -115,
                request_free_rc=0 if request_freed else -115, reply_free_rc=0 if freed else -115, cleanup_rc=-115,
                request_free_count=transaction if request_freed else transaction - 1,
                reply_free_count=transaction if freed else transaction - 1, busy_count=0, guard_failures=0,
                initialized=1, busy=int(not complete), faults=0, queued=int(queued), request_freed=int(request_freed),
                reply_received=int(received), reply_freed=int(freed), ap_consumed=int(complete),
                pending_commit=int(freed and not complete), retained_request=int(written and not request_freed),
                live_reply=int(name in ('RECEIVE', 'REPLY_QUEUED') and not freed),
                retained_reply=int(written and not freed), retained_cleanup=0,
                preset_generation=current[4], preset_known_mask=current[3], preset_raw4=current[5],
                ubmode_wire=current[6], preset_applications=current[9])
            expected.update({key: int(baseline[key], 0) for key in ('generation', 'known_mask', 'tcmode', 'dfmode', 'run',
                'command_generation0', 'command_generation1', 'command_generation2', 'applications')})
            expected.update({'preset_command_generation' + str(i): value for i, value in
                             enumerate(next_generations if written else generations)})
            api.require(all(int(f[key], 0) == value for key, value in expected.items()) and
                all(f[key] == value for key, value in old.SCOPE.items()) and f['input_fnv'] == f'{api.fnv(packet):016x}' and
                f['reply_fnv'] == ('0000000000000000' if begun else
                    f'{api.fnv(provisional_reply if name == "STATE_WRITTEN" else reply):016x}') and
                f['state_fnv'] == f'{api.fnv(before if name in ("BEGIN", "STATE_WRITTEN") else after):016x}',
                'BB preset actual event/state/flags/rc/hash differs: ' + name)
            guard, inflight = int(f['guard_held']), int(f['inflight'])
            allowed = ({(0, 0)} if begun or complete else {(1, 0)} if name in
                ('STATE_WRITTEN', 'STATE_READBACK', 'REQUEST_FREE') else {(1, 1)} if name == 'REPLY_QUEUED' else
                {(1, 1)} if not queued else {(1, 1), (0, 0)})
            api.require((guard, inflight) in allowed, 'BB preset inline/free send-inflight guard state differs')
        result['transactions'].append(dict(transaction=transaction, command=command, source=source, sender_tid=sender,
            preset_generation=ordinal, preset_known_mask=state[3], old_TC_generation=3,
            source_audit_sequence=int(audit['fields']['sequence']), original_return_raw=0x34e56e8, appfw_base=base,
            original_appfw_sha256=api.PUBLIC_LIBRARIES['usr/lib/appFw.so'], request_sha256=api.sha(packet),
            state_before_sha256=api.sha(before), state_after_sha256=api.sha(after), reply_sha256=api.sha(reply),
            receive_line=line('RECEIVE'), reply_free_line=line('REPLY_FREE'), complete_line=line('COMMIT'),
            inline_free=line('REPLY_FREE') < line('REPLY_QUEUED'), tc_complete_line=predecessor['complete_line']))
        prior, generations, previous_end = after, next_generations, line('COMMIT')
        previous_sequence = int(audit['fields']['sequence'])
    api.require(covered == {row['line'] for row in native if row['tag'] == AUDIT or
        row['tag'] in {FAMILY + suffix for suffix in old.RESOURCE_SUFFIXES}}, 'BB preset orphan/borrowed resource or audit')
    commands = sorted({item['command'] for item in result['transactions']})
    result.update(status='native_virtual_controls_verified', verified=True, content_join_verified=True,
        native_completion_verified=True, native_virtual_controls_verified=True, commands_observed=commands,
        all_two_complete=commands == [0x409, 0x40a])
    return result
