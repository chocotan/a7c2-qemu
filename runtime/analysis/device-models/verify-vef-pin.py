#!/usr/bin/env python3
"""Prove owned VEF metadata queries, not connections or pixel consumption."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import struct

HERE = Path(__file__).resolve().parent


def verify_registry(run, family, profile, owner, properties, keys, expected_slot, native=False, reply_sid=0):
    api = runpy.run_path(str(HERE / 'verify-system-sound-config.py'))
    require = api['require']
    console = (run / 'console.log').read_bytes()
    sha = hashlib.sha256(console).hexdigest()
    if native:
        inputs = json.loads((run / 'runtime-manifest.json').read_text())
        result = json.loads((run / 'summary.json').read_text())
        require(inputs.get('pin_registry_service') is True and
                inputs.get('original_libraries_unchanged') is True and result.get('probe_collected') is True,
                'Explicit native registry profile/completed capture missing')
        require(Path(result['run']).resolve() == run.resolve() and b'Entering exception monitor.' not in console,
                'Native run identity or terminal exception differs')
    else:
        inputs = json.loads((run / 'inputs.json').read_text())
        result = json.loads((run / 'result.json').read_text())
        require(inputs['experiment'].get(profile) == 'registry', 'Explicit pin owner missing')
        require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha, 'Terminal console differs')
    lines, recovered = api['observer_lines'](console, tuple(dict.fromkeys(('VEF', 'PINMEM', family))))
    prefix = 'OBS FULL_' + family + '_'
    require(not any(prefix + 'FAULT ' in line for line in lines), 'Pin ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    pins = [row for row in records if row[1].startswith(prefix + 'PIN_CREATED ')]
    require(len(pins) == len(properties), 'Owned registry constructor count differs')
    for slot, (_, _, pin) in enumerate(pins):
        expected = properties[slot]
        require(int(pin['slot']) == slot and tuple(int(pin[k]) for k in ('type', 'dir', 'index')) == expected and
                int(pin['owner'], 0) == owner and pin['state'] == '1' and pin['peer_type'] == pin['peer_dir'] == '255' and
                pin['peer_index'] == pin['peer_owner'] == '0', 'Actual registry object properties differ')
    index, _, req = next(row for row in records if row[1].startswith(prefix + 'REQUEST '))
    wire = bytes.fromhex(req['raw'])
    require(len(wire) == 48 and struct.unpack_from('<4H', wire, 24) == (0x1000, 0, 24, 2) and
            struct.unpack_from('<3I', wire, 32) == keys, 'Actual pin query differs')
    dst, tid = struct.unpack_from('<I', wire)[0], int(req['tid'])
    source = int(req['source'], 0)
    require(struct.unpack_from('<IHHII', wire, 4) == (0xa0a0a0a0, 1, 48, 24, 48) and
            int(req['destination'], 0) == owner and int(req['reply_destination'], 0) == dst and req['bytes'] == '48' and
            source >> 28 == 8 and source & 0xfffffff and dst >> 28 == 8 and dst & 0xfffffff,
            'Request owner/local destination or Dataflow envelope differs')
    qindex, _, queued = next(row for row in records if row[0] > index and row[1].startswith(prefix + 'REPLY_QUEUED ') and row[2]['tid'] == str(tid))
    reply = bytes.fromhex(queued['raw'])
    require(len(reply) == 56 and int(queued['source'], 0) == owner and int(queued['destination'], 0) == dst,
            'Reply source/dynamic destination/width differs')
    require(struct.unpack_from('<IIHHII', reply) == (reply_sid, 0xa0a0a0a0, 1, 56, 24, 56) and
            struct.unpack_from('<4H', reply, 24) == (0x1000, 0x8000, 32, 2) and
            struct.unpack_from('<6I', reply, 32) == keys + (1, owner, 0), 'Dataflow metadata reply differs')
    cindex, _, commit = next(row for row in records if row[0] > qindex and row[1].startswith(prefix + 'COMMIT ') and
                            row[2].get('reply') == queued['reply'] and row[2].get('lease') == queued['lease'])
    require(commit['tid'] == str(tid) and tuple(int(commit[k]) for k in ('type', 'dir', 'index')) == keys and
            int(commit['slot']) == expected_slot and commit['pin_state'] == '1' and
            int(commit['owner'], 0) == owner and commit['status'] == '0' and commit['request_free_rc'] == '0' and
            commit['connect_performed'] == commit['pixels_consumed'] == '0', 'Registry consumption differs')
    findex, _, freed = next(row for row in records if row[0] > cindex and row[1].startswith(prefix + 'NATIVE_REPLY_FREE ') and
                      row[2].get('reply') == queued['reply'] and row[2].get('lease') == queued['lease'])
    require(freed['tid'] == freed['sender'] == str(tid) and freed['waiter'] == '1' and freed['rc'] == '0' and
            int(freed['destination'], 0) == dst and freed['bytes'] == '56', 'Original AP waiter did not actually free reply')
    return {'pin_registry_query_verified': True, 'caller_tid': tid, 'pin_slot': expected_slot, 'pin_state': 1, 'pin_owner': hex(owner),
            'registry_objects': len(properties), 'observer_prefix_recoveries': recovered, 'console_sha256': sha,
            'request_observer_record': index, 'native_free_observer_record': findex,
            'evidence_kind': 'native' if native else 'full-system',
            'verification_scope': 'registry-query', 'whole_run_success_verified': False,
            'original_CP_task_running_verified': False, 'connection_verified': False,
            'pixels_consumed': False, 'camera_startup_verified': False}


def verify(run):
    properties = [(0, d, i) for d in (1, 2) for i in range(7)] + [(8, 1, 0), (8, 2, 0)]
    proof = verify_registry(run, 'VEF', 'vef_service', 0x905a0048, properties, (0, 2, 3), 10)
    proof['vef_pin_query_verified'] = True
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError) as error:
        proof = {'vef_pin_query_verified': False, 'error': str(error) or type(error).__name__,
                 'connection_verified': False, 'pixels_consumed': False, 'camera_startup_verified': False}
    (args.run / 'vef-pin-query-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['vef_pin_query_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
