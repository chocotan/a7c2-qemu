#!/usr/bin/env python3
"""Verify five original boot rate configurations; enums are not physical Hz."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify(run):
    console = (run / 'console.log').read_bytes()
    sha = hashlib.sha256(console).hexdigest()
    result = json.loads((run / 'result.json').read_text())
    inputs = json.loads((run / 'inputs.json').read_text())
    require(inputs['experiment'].get('hdmi_service') == 'boot', 'Explicit boot profile missing')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha, 'Terminal console differs')
    lines = list(dict.fromkeys(console.decode(errors='replace').splitlines()))
    require(not any('OBS FULL_HDMI_FAULT ' in line for line in lines), 'HDMI ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    resolution = json.loads((run / 'hdmi-resolution-proof.json').read_text())
    require(resolution.get('hdmi_resolution_config_verified') and resolution['console_sha256'] == sha, 'Resolution proof missing')
    tid = resolution['caller_tid']
    calls = [row for row in records if row[1].startswith('OBS FULL_HDMI_REQUEST ') and
             row[2].get('command') == '0x117' and row[2].get('tid') == str(tid)]
    require(len(calls) == 5, f'Original boot rate count differs: {len(calls)}')
    first = bytes.fromhex(calls[0][2]['raw'])
    require(len(first) == 12 and first[9] in (0, 7), 'Unknown original boot rate branch')
    expected = [7] * 5 if first[9] == 7 else [0, 0, 17, 17, 0]
    saved = []
    for ordinal, (index, _, req) in enumerate(calls):
        wire = bytes.fromhex(req['raw'])
        require(len(wire) == 12 and struct.unpack_from('<4H', wire) == (0x2500, 0x117, 12, 1) and
                wire[8:] == bytes([ordinal, expected[ordinal], ordinal, expected[ordinal]]), 'Original four-byte rate request differs')
        qindex, _, queued = next(row for row in records if row[0] > index and
            row[1].startswith('OBS FULL_HDMI_REPLY_QUEUED ') and row[2].get('tid') == str(tid) and
            row[2].get('command') == '0x117')
        reply = bytes.fromhex(queued['raw'])
        require(len(reply) == 12 and struct.unpack('<4HI', reply) == (0x2500, 0x8117, 12, 1, 0) and
                int(queued['source'], 0) == 0x909a015a and queued['destination'] == req['source'], '8117 status/source/destination differs')
        cindex, _, commit = next(row for row in records if row[0] > qindex and row[1].startswith('OBS FULL_HDMI_COMMIT ') and
                                row[2].get('reply') == queued['reply'] and row[2].get('lease') == queued['lease'])
        require(commit['tid'] == str(tid) and commit['command'] == '0x117' and int(commit['selector']) == ordinal and
                int(commit['rate']) == expected[ordinal] and int(commit['readback']) == expected[ordinal] and
                commit['matched'] == '1' and commit['dp_applied'] == '0' and
                int(commit['dp_selector']) == ordinal and int(commit['dp_rate']) == expected[ordinal] and commit['status'] == '0' and
                int(commit['known_mask'], 0) == (1 << (ordinal + 1)) - 1 and commit['request_free_rc'] == '0' and
                bytes.fromhex(commit['rates'])[:ordinal + 1] == bytes(expected[:ordinal + 1]), 'Actual rate cache/readback differs')
        findex, _, freed = next(row for row in records if row[0] > cindex and row[1].startswith('OBS FULL_HDMI_NATIVE_REPLY_FREE ') and
                               row[2].get('reply') == queued['reply'] and row[2].get('lease') == queued['lease'])
        require(freed['tid'] == str(tid) and freed['sender'] == str(tid) and freed['waiter'] == '1' and freed['rc'] == '0' and
                freed['destination'] == queued['destination'] and freed['command'] == '0x117' and
                freed['bytes'] == '12' and freed['status'] == '0', 'Original rate waiter did not actually free reply')
        if ordinal + 1 < len(calls):
            require(findex < calls[ordinal + 1][0], 'Next original selector preceded actual waiter free')
        saved.append({'selector': ordinal, 'rate_enum': expected[ordinal]})
    return {'hdmi_rate_config_verified': True, 'caller_tid': tid, 'rates': saved, 'known_mask': 31,
            'dp_configuration_applied': False, 'wire_getter_verified': False, 'console_sha256': sha,
            'hdmi_output_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        proof = {'hdmi_rate_config_verified': False, 'error': str(error) or type(error).__name__,
                 'hdmi_output_verified': False, 'camera_startup_verified': False}
    (args.run / 'hdmi-rate-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['hdmi_rate_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
