#!/usr/bin/env python3
"""Prove shared HDMI configuration consumption, never physical output."""
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
    result = json.loads((run / 'result.json').read_text())
    inputs = json.loads((run / 'inputs.json').read_text())
    require(inputs['experiment'].get('hdmi_service') in ('definition', 'boot'), 'Definition profile was not enabled')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha,
            'Terminal console differs')
    lines = list(dict.fromkeys(console.decode(errors='replace').splitlines()))
    require(not any('OBS FULL_HDMI_FAULT ' in line for line in lines), 'HDMI ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    index, _, req = next(row for row in records if row[1].startswith('OBS FULL_HDMI_REQUEST ') and
                         row[2]['command'] == '0x10a')
    require(bytes.fromhex(req['raw']) == bytes.fromhex('00250a010c00010000000000'), 'Original boot request differs')
    tid, destination = int(req['tid']), int(req['source'], 0)
    qindex, _, queued = next(row for row in records if row[0] > index and
        row[1].startswith('OBS FULL_HDMI_REPLY_QUEUED ') and int(row[2]['tid']) == tid and
        row[2]['command'] == '0x10a')
    require(int(queued['source'], 0) == 0x909a015a and int(queued['destination'], 0) == destination,
            'Reply source/dynamic destination differs')
    wire = bytes.fromhex(queued['raw'])
    require(len(wire) == 12 and struct.unpack('<4HI', wire) == (0x2500, 0x810a, 12, 1, 1),
            'Shared-state reply must carry native status1')
    cindex, _, commit = next(row for row in records if row[0] > qindex and
        row[1].startswith('OBS FULL_HDMI_COMMIT ') and row[2].get('reply') == queued['reply'] and
        row[2].get('lease') == queued['lease'])
    require(int(commit['tid']) == tid and commit['command'] == '0x10a' and commit['request_free_rc'] == '0' and
            commit['requested'] == '0' and commit['known_after'] == '1' and commit['readback'] == '0' and
            commit['status'] == '1', 'Configuration consumption/readback differs')
    findex, _, freed = next(row for row in records if row[0] > cindex and
        row[1].startswith('OBS FULL_HDMI_NATIVE_REPLY_FREE ') and row[2].get('reply') == queued['reply'] and
        row[2].get('lease') == queued['lease'])
    require(int(freed['tid']) == tid and int(freed['sender']) == tid and freed['waiter'] == '1' and
            freed['rc'] == '0' and int(freed['destination'], 0) == destination and
            freed['command'] == '0x10a', 'Original waiter did not actually release its reply')
    logged_success = any('Infra_HDMI hdmi_set_definition_hd[0] definition[0]' in row[1]
                         for row in records if row[0] > findex)
    continuation = next((row for row in records if row[0] > findex and
        (row[1].startswith('HDMI_PHOTO_REQUEST ') or row[1].startswith('OBS HDMI_PHOTO_REQUEST ')) and
        row[2].get('tid') == str(tid) and row[2].get('frame') == '0x2500' and
        row[2].get('command') == '0x101' and row[2].get('bytes') == '16' and
        row[2].get('flags') == '0x1'), None)
    modeled_next = next((row for row in records if row[0] > findex and
        row[1].startswith('OBS FULL_HDMI_REQUEST ') and row[2].get('tid') == str(tid) and
        row[2].get('command') == '0x101' and row[2].get('bytes') == '16'), None)
    evidence = 'original-service-log' if logged_success else None
    if continuation and continuation[1].startswith('OBS '):
        evidence = 'subsequent-original-HDMI0101-request'
    elif modeled_next:
        next_wire = bytes.fromhex(modeled_next[2]['raw'])
        require(len(next_wire) == 16 and struct.unpack_from('<4H', next_wire) == (0x2500, 0x101, 16, 1),
                'Subsequent original HDMI0101 envelope differs')
        evidence = 'subsequent-original-HDMI0101-request-to-explicit-owner'
    elif continuation and not logged_success:
        # Historical diagnostics retained the original transport log instead
        # of mirroring its events. Require independently checked frozen frames.
        census = json.loads((run / 'critical-census-proof.json').read_text())
        require(census.get('critical_census_verified') and census['console_sha256'] == sha,
                'Frozen continuation census is not verified')
        thread = next(item for item in census['threads'] if item['tid'] == tid)
        require(thread['name'] == 'SeqQueueCommon' and thread['rc'] == 0 and thread['frozen_frames'] and
                '0x305e0dc' in thread['app_return_offsets'] and '0x34f3fb4' in thread['app_return_offsets'] and
                '0x305e064' not in thread['app_return_offsets'], 'Original success-branch continuation differs')
        # Original AP305e060 calls010a;305e068 CBZ is the sole path to305e0d8
        # (0101), whose frozen return is305e0dc. This checks behavior, not a log.
        evidence = 'frozen-original-success-branch-and-HDMI0101-request'
    require(evidence, 'No original mapped-success or subsequent success-branch evidence')
    return {'schema': 2, 'hdmi_definition_config_verified': True, 'caller_tid': tid, 'reply_destination': hex(destination),
            'continuation_evidence': evidence,
            'native_status': 1, 'definition': 0, 'known': True, 'console_sha256': sha,
            'hdmi_output_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        proof = {'hdmi_definition_config_verified': False, 'error': str(error) or type(error).__name__,
                 'hdmi_output_verified': False, 'camera_startup_verified': False}
    # Keep the earlier log-only rejection intact in historical runs.
    (args.run / 'hdmi-definition-consumption-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['hdmi_definition_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
