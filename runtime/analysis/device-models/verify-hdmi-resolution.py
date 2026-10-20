#!/usr/bin/env python3
"""Check original HDMI0101 configuration and native waiter ownership."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def require(value, message):
    if not value:
        raise ValueError(message)


def verify(run):
    console = (run / 'console.log').read_bytes()
    sha = hashlib.sha256(console).hexdigest()
    inputs = json.loads((run / 'inputs.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    require(inputs['experiment'].get('hdmi_service') == 'boot', 'Explicit HDMI boot profile was not enabled')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha, 'Terminal console differs')
    lines = list(dict.fromkeys(console.decode(errors='replace').splitlines()))
    require(not any('OBS FULL_HDMI_FAULT ' in line for line in lines), 'HDMI ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    index, _, request = next(row for row in records if row[1].startswith('OBS FULL_HDMI_REQUEST ') and
                            row[2]['command'] == '0x101')
    wire = bytes.fromhex(request['raw'])
    require(wire == bytes.fromhex('00250101100001000000000006050000'), 'Original init_resolution body differs')
    tid, dst = int(request['tid']), int(request['source'], 0)
    qindex, _, queued = next(row for row in records if row[0] > index and
        row[1].startswith('OBS FULL_HDMI_REPLY_QUEUED ') and row[2].get('tid') == str(tid) and
        row[2].get('command') == '0x101')
    reply = bytes.fromhex(queued['raw'])
    require(len(reply) == 12 and struct.unpack('<4HI', reply) == (0x2500, 0x8101, 12, 1, 0),
            'Original8101 requires status0, not010a status1')
    require(int(queued['source'], 0) == 0x909a015a and int(queued['destination'], 0) == dst,
            'Reply source/dynamic destination differs')
    cindex, _, commit = next(row for row in records if row[0] > qindex and
        row[1].startswith('OBS FULL_HDMI_COMMIT ') and row[2].get('reply') == queued['reply'] and
        row[2].get('lease') == queued['lease'])
    require(commit['tid'] == str(tid) and commit['command'] == '0x101' and commit['resolution'] == wire[8:14].hex() and
            commit['resolution_known'] == '1' and commit['status'] == '0' and commit['request_free_rc'] == '0',
            'Actual six-byte cache/request release differs')
    findex, _, freed = next(row for row in records if row[0] > cindex and
        row[1].startswith('OBS FULL_HDMI_NATIVE_REPLY_FREE ') and row[2].get('reply') == queued['reply'] and
        row[2].get('lease') == queued['lease'])
    require(freed['tid'] == str(tid) and freed['sender'] == str(tid) and freed['waiter'] == '1' and
            freed['rc'] == '0' and int(freed['destination'], 0) == dst and freed['command'] == '0x101',
            'Original waiter did not actually release8101')
    require(any(row[0] > findex and row[2].get('tid') == str(tid) and
                row[2].get('command') == '0x117' and row[2].get('bytes') == '12' and
                ((row[1].startswith('OBS HDMI_PHOTO_REQUEST ') and row[2].get('frame') == '0x2500' and row[2].get('flags') == '0x1') or
                 (row[1].startswith('OBS FULL_HDMI_REQUEST ') and row[2].get('raw', '').startswith('002517010c000100')))
                for row in records),
            'Original Common did not naturally continue to0117 after8101 release')
    return {'hdmi_resolution_config_verified': True, 'caller_tid': tid, 'reply_destination': hex(dst),
            'resolution': wire[8:14].hex(), 'native_status': 0, 'subsequent_original_command': '0x117',
            'console_sha256': sha,
            'hdmi_output_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        proof = {'hdmi_resolution_config_verified': False, 'error': str(error) or type(error).__name__,
                 'hdmi_output_verified': False, 'camera_startup_verified': False}
    (args.run / 'hdmi-resolution-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['hdmi_resolution_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
