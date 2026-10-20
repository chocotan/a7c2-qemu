#!/usr/bin/env python3
"""Verify a native VDF configuration exchange without changing the run result."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def fields(line):
    return dict(re.findall(r'(\w+)=([^\s]+)', line))


def number(value):
    return int(value, 0)


def verify(console):
    if not __debug__:
        raise ValueError('Verification must run without Python assertion optimization')
    # The bounded diagnostic may echo the same observer record once more.
    lines = list(dict.fromkeys(console.decode(errors='replace').splitlines()))
    assert not any(line.startswith('OBS FULL_VDF_FAULT ') for line in lines), 'VDF ownership fault'
    records = [(i, line, fields(line)) for i, line in enumerate(lines)]
    for index, line, request in records:
        if not line.startswith('OBS FULL_VDF_REQUEST '):
            continue
        raw = bytes.fromhex(request['raw'])
        if len(raw) != 52 or raw[24:32] != bytes.fromhex('012005021c000100'):
            continue
        tid, destination = number(request['tid']), number(request['source'])
        assert number(request['destination']) == 0x9059000e
        assert struct.unpack_from('<I', raw)[0] == destination
        assert raw[4:20] == bytes.fromhex('a0a0a0a0010034001800000034000000')
        assert raw[32] == 1 and raw[33] == 0 and raw[40] == 0 and raw[44] < 3
        queued = next((i, f) for i, text, f in records if i > index and
                      text.startswith('OBS FULL_VDF_REPLY_QUEUED ') and
                      number(f['tid']) == tid and number(f['destination']) == destination)
        qindex, reply = queued
        wire = bytes.fromhex(reply['raw'])
        assert len(wire) == 36 and number(reply['bytes']) == 36
        assert wire[:20] == bytes.fromhex('00000000a0a0a0a0010024001800000024000000')
        assert wire[24:] == bytes.fromhex('012005120c00010000000000')
        assert number(reply['source']) == 0x9059000e and number(reply['status']) == 0
        cindex, commit = next((i, f) for i, text, f in records if i > qindex and
                              text.startswith('OBS FULL_VDF_COMMIT ') and
                              f['reply'] == reply['reply'] and f['lease'] == reply['lease'])
        assert number(commit['tid']) == tid and number(commit['destination']) == destination
        assert number(commit['status']) == 0 and number(commit['request_free_rc']) == 0
        assert number(commit['cache_before']) == 1 and number(commit['cache_after']) == 0
        assert number(commit['internal_destination']) == 0x9059081b
        assert number(commit['hdmi_consumed']) >= 1
        assert bytes.fromhex(commit['internal']) == bytes.fromhex('012033f01c000100') + raw[32:]
        findex, freed = next((i, f) for i, text, f in records if i > cindex and
                            text.startswith('OBS FULL_VDF_NATIVE_REPLY_FREE ') and
                            f['reply'] == reply['reply'] and f['lease'] == reply['lease'])
        assert number(freed['tid']) == tid and number(freed['sender']) == tid
        assert number(freed['waiter']) == 1 and number(freed['rc']) == 0
        assert number(freed['destination']) == destination
        assert number(freed['expected_destination']) == destination
        advanced = any(i > findex and text.startswith('OBS FULL_VDF_REQUEST ') and
                       number(f['tid']) == tid for i, text, f in records)
        return {'vdf_timecode_config_verified': True, 'caller_tid': tid,
                'reply_destination': hex(destination), 'reply_pointer': reply['reply'],
                'lease': number(reply['lease']), 'cache_before': 1, 'cache_after': 0,
                'original_waiter_free_rc': 0,
                'subsequent_original_vdf_request_observed': advanced,
                'camera_startup_verified': False, 'hdmi_output_verified': False}
    raise AssertionError('No original VDF 0205 configuration request and completed exchange')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    console = (args.run / 'console.log').read_bytes()
    proof = {'console_sha256': hashlib.sha256(console).hexdigest(),
             'inputs_sha256': hashlib.sha256((args.run / 'inputs.json').read_bytes()).hexdigest(),
             'original_run_state': json.loads((args.run / 'result.json').read_text())['state'],
             'vdf_timecode_config_verified': False, 'camera_startup_verified': False}
    try:
        proof.update(verify(console))
    except (AssertionError, KeyError, ValueError, StopIteration) as error:
        proof['error'] = str(error) or type(error).__name__
    (args.run / 'vdf-timecode-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['vdf_timecode_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
