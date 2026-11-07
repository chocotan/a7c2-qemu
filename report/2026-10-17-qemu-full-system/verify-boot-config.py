#!/usr/bin/env python3
"""Verify actual original callers received domain-tagged configuration replies."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def require(condition, why):
    if not condition:
        raise ValueError(why)


def fields(line):
    return dict(re.findall(r'(\w+)=([^\s]+)', line))


def num(value):
    return int(value, 0)


def exchange(records, request_tag, queue_tag, commit_tag, free_tag, request_bytes, reply_bytes):
    i, request = next((i, f) for i, line, f in records if line.startswith(request_tag)
                      and bytes.fromhex(f['raw'])[:8] == request_bytes)
    raw = bytes.fromhex(request['raw'])
    require(len(raw) == 10 and raw[:8] == request_bytes, 'Original request differs')
    tid, dst = num(request['tid']), num(request['source'])
    j, reply = next((j, f) for j, line, f in records if j > i and line.startswith(queue_tag)
                    and num(f['tid']) == tid and num(f['destination']) == dst)
    require(num(reply['source']) == 0x92840747, 'Raw reply source differs')
    require(bytes.fromhex(reply['raw']) == reply_bytes and num(reply['bytes']) == 12,
            'Raw reply did not retain its original status domain')
    cindex, commit = next((k, f) for k, line, f in records if k > j and line.startswith(commit_tag)
                          and f['reply'] == reply['reply'] and f['lease'] == reply['lease'])
    require(num(commit['tid']) == tid and num(commit['request_free_rc']) == 0,
            'Original request was not actually released')
    _, freed = next((k, f) for k, line, f in records if k > cindex and
                    line.startswith(free_tag) and f.get('reply') == reply['reply'] and
                    f.get('lease') == reply['lease'])
    require(num(freed['tid']) == tid and num(freed['sender']) == tid and num(freed['waiter']) == 1,
            'Reply was not freed by the original caller')
    require(num(freed['destination']) == dst and num(freed['rc']) == 0,
            'Native reply release failed or used a different destination')
    return raw, commit, {'caller_tid': tid, 'reply_destination': hex(dst),
                         'reply_pointer': reply['reply'], 'lease': num(reply['lease']),
                         'original_request_free_rc': 0, 'original_waiter_free_rc': 0}


def verify(run):
    console = (run / 'console.log').read_bytes()
    result = json.loads((run / 'result.json').read_text())
    identity = json.loads((run / 'inputs.json').read_text())
    require(identity['experiment'].get('audio_service') in ('volume', 'boot'), 'Volume profile was not enabled')
    require(identity['experiment'].get('vdf_service') == 'timecode', 'VDF profile was not enabled')
    require(result.get('terminal_evidence_checked') is True, 'Terminal evidence was not checked')
    digest = hashlib.sha256(console).hexdigest()
    require(result['terminal_console_sha256'] == digest, 'Terminal console changed')
    lines = list(dict.fromkeys(console.decode(errors='replace').splitlines()))
    require(not any(line.startswith(('OBS FULL_AUDIO_FAULT ', 'OBS FULL_VDF_FAULT '))
                    for line in lines), 'Configuration ownership fault')
    records = [(i, line, fields(line)) for i, line in enumerate(lines)]
    raw, commit, panel = exchange(records, 'OBS FULL_VDF_PANEL_REQUEST ',
        'OBS FULL_VDF_PANEL_REPLY_QUEUED ', 'OBS FULL_VDF_PANEL_COMMIT ',
        'OBS FULL_VDF_NATIVE_REPLY_FREE ', bytes.fromhex('0d2065010a000180'),
        bytes.fromhex('0d2065110c00018000005900'))
    require(raw[8:] == b'\x02\x00', 'Unexpected boot resolution selection')
    require(num(commit['service_status']) == 0 and num(commit['raw_status']) == 0x590000,
            'Panel status domain differs')
    require(num(commit['shadow_flags']) & 0x40 and num(commit['shadow_selector']) == 2 and
            num(commit['shadow_size']) == 0 and num(commit['cached_valid']) == 1 and
            num(commit['cached_size']) == 0, 'Panel control/cache was not consumed')
    raw, commit, audio = exchange(records, 'OBS FULL_AUDIO_REQUEST ',
        'OBS FULL_AUDIO_REPLY_QUEUED ', 'OBS FULL_AUDIO_COMMIT ',
        'OBS FULL_AUDIO_NATIVE_REPLY_FREE ', bytes.fromhex('0d2030030a000180'),
        bytes.fromhex('0d2030130c00018000005800'))
    wire = raw[8]
    level = 0 if wire == 0 else wire - 1 if wire <= 16 else 15
    require(num(commit['wire']) == wire and num(commit['level']) == level and
            num(commit['driver_readback']) == level and num(commit['control_op']) == 4 and
            num(commit['consumed']) >= 1, 'Virtual driver configuration/readback differs')
    audio.update(wire_volume=wire, driver_level=level)
    return {'boot_config_verified': True, 'panel': panel, 'volume': audio,
            'console_sha256': digest, 'original_run_state': result['state'],
            'pixels_switched_verified': False, 'audio_output_verified': False,
            'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        proof = {'boot_config_verified': False, 'error': str(error) or type(error).__name__,
                 'camera_startup_verified': False}
    (args.run / 'boot-config-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['boot_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
