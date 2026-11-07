#!/usr/bin/env python3
"""Verify virtual control handshake, real backing and the missing-format stop."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import struct

HERE = Path(__file__).resolve().parent
S = (0, 2, 3, 0x905a0048)
P = (0, 1, 1, 0x90590818)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify_control_prefix(run, native=False):
    inputs = json.loads((run / ('runtime-manifest.json' if native else 'inputs.json')).read_text())
    result = json.loads((run / ('summary.json' if native else 'result.json')).read_text())
    console = (run / 'console.log').read_bytes();sha = hashlib.sha256(console).hexdigest()
    if native:
        require(inputs.get('pin_connection_mode') == 'cold' and inputs.get('pin_control_memory') is True and
                inputs.get('pin_registry_service') is True and inputs.get('pin_buffer_selftest') is False and
                inputs.get('original_libraries_unchanged') is True and result.get('probe_collected') is True,
                'Explicit native control profile/completed capture missing')
        require(Path(result['run']).resolve() == run.resolve() and b'Entering exception monitor.' not in console,
                'Native run identity or terminal exception differs')
    else:
        require(inputs['experiment'].get('pin_connection') == 'control' and result.get('terminal_evidence_checked') and
                result['terminal_console_sha256'] == sha, 'Explicit control profile/terminal association missing')
        get_api = runpy.run_path(str(HERE / 'verify-pinmem-pin.py'))
        peer_get = get_api['verify'](run);tid = peer_get['caller_tid']
    # Exact repeated frees can be distinct leases at the same reused address.
    # Preserve ordering/multiplicity here; constructor-only verifiers retain
    # their established default deduplication for bounded log suffix replays.
    lines, recovered = runpy.run_path(str(HERE / 'verify-system-sound-config.py'))['observer_lines'](
        console, ('PIN_CONNECT', 'VEF', 'PINMEM', 'PIN'), deduplicate=False)
    require(not any('OBS FULL_PIN_CONNECT_FAULT ' in line for line in lines), 'Control ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    if native:
        connection = next(row for row in records if row[1].startswith('OBS FULL_PIN_CONNECT_REQUEST '))
        tid = int(connection[2]['tid'])
        # Native identity differs; keep the original pre-connection Get/free evidence requirement.
        for family, keys, count in (('VEF', S, 16), ('PINMEM', P, 13)):
            tag = 'OBS FULL_' + family + '_'
            require(len([r for r in records if r[0] < connection[0] and r[1].startswith(tag + 'PIN_CREATED ')]) == count,
                    'Native registry construction census differs')
            req = next(r for r in records if r[0] < connection[0] and r[1].startswith(tag + 'REQUEST ') and
                       r[2]['tid'] == str(tid) and struct.unpack_from('<3I', bytes.fromhex(r[2]['raw']), 32) == keys[:3])
            q = next(r for r in records if req[0] < r[0] < connection[0] and r[1].startswith(tag + 'REPLY_QUEUED ') and r[2]['tid'] == str(tid))
            c = next(r for r in records if q[0] < r[0] < connection[0] and r[1].startswith(tag + 'COMMIT ') and r[2]['lease'] == q[2]['lease'])
            f = next(r for r in records if c[0] < r[0] < connection[0] and r[1].startswith(tag + 'NATIVE_REPLY_FREE ') and r[2]['lease'] == q[2]['lease'])
            raw, reply = bytes.fromhex(req[2]['raw']), bytes.fromhex(q[2]['raw'])
            require(len(raw) == 48 and len(reply) == 56 and
                    struct.unpack_from('<IIHHII', raw) == (int(req[2]['reply_destination'], 0), 0xa0a0a0a0, 1, 48, 24, 48) and
                    struct.unpack_from('<4H', raw, 24) == (0x1000, 0, 24, 2) and
                    struct.unpack_from('<IIHHII', reply) == (0, 0xa0a0a0a0, 1, 56, 24, 56) and
                    struct.unpack_from('<4H', reply, 24) == (0x1000, 0x8000, 32, 2) and
                    struct.unpack_from('<6I', reply, 32) == keys[:3] + (1, keys[3], 0), 'Native Get wire differs')
            require(int(req[2]['destination'], 0) == int(q[2]['source'], 0) == keys[3] and
                    req[2]['reply_destination'] == q[2]['destination'] == f[2]['destination'], 'Native Get route differs')
            require(q[2]['reply'] == c[2]['reply'] == f[2]['reply'] and
                    c[2]['request_free_rc'] == f[2]['rc'] == '0' and
                    f[2]['tid'] == f[2]['sender'] == str(tid) and f[2]['waiter'] == '1', 'Native Get/free differs')

    def event(kind, after=-1, **matches):
        return next(row for row in records if row[0] > after and row[1].startswith('OBS FULL_PIN_CONNECT_' + kind + ' ') and
                    all(row[2].get(key) == value for key, value in matches.items()))

    def frame(row, command, size, inner_size, flags, source, destination):
        f = row[2];data = bytes.fromhex(f['raw'])
        require(int(f['tid']) == tid and int(f['source'], 0) == source and int(f['destination'], 0) == destination and
                len(data) == size and int(f['bytes']) == size, 'Control frame caller/route/size differs')
        outer = struct.unpack_from('<IIHHII', data)
        require(outer == (D if command == 1 else 0, 0xa0a0a0a0, 1, size, 24, size) and
                struct.unpack_from('<4H', data, 24) == (0x1000, command, inner_size, flags), 'Control envelope differs')
        return data

    request = event('REQUEST');D = int(request[2]['source'], 0)
    require(D >> 28 == 8 and D & 0xfffffff, 'No actual local dynamic caller')
    require(any(i < request[0] and line.startswith('OBS FULL_PINMEM_NATIVE_REPLY_FREE ') and
                f.get('tid') == f.get('sender') == str(tid) and f.get('waiter') == '1' and f.get('rc') == '0'
                for i, line, f in records), 'Connection was not issued after actual peer Get free')
    raw = frame(request, 1, 64, 40, 2, D, S[3]);require(struct.unpack_from('<8I', raw, 32) == S + P, 'Original S/P differs')
    forward = event('PEER_REQUEST', request[0]);raw = frame(forward, 0x100, 64, 40, 1, S[3], P[3])
    require(struct.unpack_from('<8I', raw, 32) == S + P, 'Peer request was not derived from original edge')
    answer = event('PEER_REPLY', forward[0]);raw = frame(answer, 0x8100, 72, 48, 1, P[3], S[3])
    require(struct.unpack_from('<10I', raw, 32) == S + P + (0, 0), 'Peer confirmation fields differ')
    freed_forward = event('INTERNAL_FREE', answer[0], pointer=forward[2]['pointer'], rc='0')
    freed_answer = event('INTERNAL_FREE', freed_forward[0], pointer=answer[2]['pointer'], rc='0')
    require(all(int(row[2]['owner'], 0) == D and int(row[2]['tid']) == tid for row in (freed_forward, freed_answer)), 'Internal CP message allocation leases differ')
    queued = event('REPLY_QUEUED', freed_answer[0]);raw = frame(queued, 0x8001, 56, 32, 2, S[3], D)
    require(struct.unpack_from('<6I', raw, 32) == S + (0, 0), 'AP reply did not carry actual source/status')
    freed_request = event('REQUEST_FREE', queued[0], pointer=request[2]['pointer'], rc='0')
    require(int(freed_request[2]['owner'], 0) == S[3] and int(freed_request[2]['tid']) == tid, 'Original request ownership differs')
    dmm_req = event('DMM_REQUEST', freed_request[0]);dmm_reply = event('DMM_REPLY', dmm_req[0])
    before = bytes.fromhex(dmm_req[2]['raw']);after = bytes.fromhex(dmm_reply[2]['raw'])
    require(len(before) == len(after) == 0x98 and struct.unpack_from('<H', before)[0] == 0x20 and
            struct.unpack_from('<I', before, 4)[0] == 0x404 and struct.unpack_from('<HH', before, 0x14) == (0, 1), 'Actual DMM input differs')
    require(int(dmm_req[2]['source'], 0) == 0x9059000e and int(dmm_req[2]['destination'], 0) == 0x61003c and
            int(dmm_reply[2]['source'], 0) == 0x61003c and int(dmm_reply[2]['destination'], 0) == 0x9059000e,
            'Virtual CP DMM route differs')
    require(struct.unpack_from('<HH', after) == (0x8020, 0) and struct.unpack_from('<HH', after, 8) == (1, 0) and
            struct.unpack_from('<I', after, 0x10)[0] == 0x404 and not any(after[0x28:]), 'DMM reply is not a valid one-extent success')
    handle = struct.unpack_from('<I', after, 0xc)[0];physical, size, zero = struct.unpack_from('<QII', after, 0x18)
    require(size == 512 and zero == 0 and physical == 0x500000000 + (handle & 0x3ff) * 512, 'Actual buffer descriptor differs')
    event('INTERNAL_FREE', dmm_reply[0], pointer=dmm_reply[2]['pointer'], rc='0')
    written = event('BUFFER_WRITTEN', dmm_reply[0]);f = written[2]
    require(int(f['tid']) == tid and int(f['handle'], 0) == handle and int(f['physical'], 0) == physical and
            int(f['bytes']) == size and f['format_pending'] == '1' and f['buffer_released'] == f['pixels_consumed'] == '0', 'Buffer was not consumed/retained')
    readback = event('STATE_READBACK', written[0]);state = readback[2]
    attrs = lambda key: tuple(int(item, 0) for item in state[key].split(','))
    require(int(state['tid']) == tid and state['source_state'] == state['peer_state'] == state['source_pending'] == '0' and
            attrs('source_self') == S and attrs('source_peer') == P and attrs('peer_self') == P and attrs('peer_peer') == S,
            'Owned registry state/peer readback differs')
    freed = event('NATIVE_REPLY_FREE', readback[0], reply=queued[2]['pointer'], rc='0')
    require(freed[2]['tid'] == freed[2]['sender'] == str(tid) and freed[2]['waiter'] == '1' and
            int(freed[2]['destination'], 0) == int(freed[2]['expected'], 0) == D and freed[2]['command'] == '0x8001', 'Original AP waiter did not consume/free8001')
    return {'caller_tid': tid, 'dynamic_sid': D, 'handle': handle, 'physical': physical, 'size': size,
            'event': event, 'records': records, 'native_free': freed, 'written': written, 'state_readback': readback,
            'console_sha256': sha, 'observer_prefix_recoveries': recovered, 'result': result, 'inputs': inputs}


def verify(run):
    prefix = verify_control_prefix(run)
    tid, D, handle, physical, size = (prefix[key] for key in ('caller_tid', 'dynamic_sid', 'handle', 'physical', 'size'))
    event, freed, f = prefix['event'], prefix['native_free'], prefix['written'][2]
    sha, recovered, result = (prefix[key] for key in ('console_sha256', 'observer_prefix_recoveries', 'result'))
    held = event('FORMAT_BLOCKED_REQUEST', freed[0]);data = bytes.fromhex(held[2]['raw'])
    require(int(held[2]['tid']) == tid and int(held[2]['destination'], 0) == P[3] and len(data) == 48 and
            struct.unpack_from('<4H', data, 24) == (0x1000, 0, 24, 2), 'Same original continuation was not queued at missing format')
    backing = (run / 'pin-control-memory.bin').read_bytes();offset = physical - 0x500000000
    expected = struct.pack('<II', 0x4e595353, 0x01000000) + bytes(24)
    require(len(backing) == 8192 and backing[offset:offset + 32] == expected and
            not any(backing[:offset]) and not any(backing[offset + 32:]) and result.get('pin_control_memory_exported'),
            'Independent reserved guest backing differs')
    control = runpy.run_path(str(HERE / 'verify-pin-control.py'));require(control['fnv'](expected) == f['header_fnv64'], 'Actual SSYN readback digest differs')
    command = control['verify_reservation'](run, runpy.run_path(str(HERE / 'pin-buffer-region.py')))
    require(command.split().count('fullsystem.pin-connect=control') == 1, 'Actual DTB control profile missing')
    return {'schema': 2, 'transport_event_multiplicity_preserved': True, 'virtual_control_connection_verified': True, 'caller_tid': tid, 'dynamic_sid': hex(D), 'source': list(S), 'peer': list(P),
            'actual_original_waiter_8001_free_verified': True, 'owned_registry_peer_state_readback_verified': True,
            'control_buffer_physical': hex(physical), 'control_buffer_bytes': size, 'control_buffer_lease_retained': True,
            'format_consumer_missing': True, 'subsequent_request_owned_and_blocked': True, 'console_sha256': sha,
            'backing_sha256': hashlib.sha256(backing).hexdigest(), 'observer_prefix_recoveries': recovered,
            'original_CP_task_running_verified': False, 'format_ready_verified': False, 'pixels_consumed': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__);parser.add_argument('run', type=Path);args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError, UnicodeError) as error:
        proof = {'virtual_control_connection_verified': False, 'error': str(error) or type(error).__name__,
                 'format_ready_verified': False, 'pixels_consumed': False, 'camera_startup_verified': False}
    (args.run / 'pin-control-connection-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True));return 0 if proof['virtual_control_connection_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
