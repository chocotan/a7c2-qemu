#!/usr/bin/env python3
"""Verify the explicit virtual inputless owner, not original microphone state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent


def verify(run):
    api = runpy.run_path(str(HERE / 'verify-system-sound-config.py'))
    require = api['require']
    console = (run / 'console.log').read_bytes()
    sha = hashlib.sha256(console).hexdigest()
    inputs = json.loads((run / 'inputs.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    require(inputs['experiment'].get('audio_capabilities') == 'inputless' and
            inputs['experiment'].get('audio_service') == 'boot', 'Explicit capability owner was not enabled')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha,
            'Terminal console differs')
    lines, recovered_prefixes = api['observer_lines'](console)
    require(not any('OBS FULL_AUDIO_FAULT ' in line for line in lines), 'Audio ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    query = next(row for row in records if row[1].startswith('OBS FULL_AUDIO_REQUEST ') and
                 row[2]['command'] == '0x327')
    require(bytes.fromhex(query[2]['raw']) == bytes.fromhex('0d20270308000180'), 'Original query differs')
    _, reply, commit = api['received'](records, query)
    expected = bytes([0x80] * 8 + [0x81] + [0x80] * 7)
    require(len(reply) == 28 and reply[12:] == expected, 'Capability projection differs')
    require(commit['owner'] == 'inputless' and commit['valid'] == '7' and commit['input_devices'] == '0' and
            all(commit[key] == '0' for key in ('pro', 'aip', 'znr', 'error', 'service_status')) and
            commit['cached_flags'] == expected.hex() and int(commit['queries']) >= 1,
            'Actual capability source/cache readback differs')
    return {'audio_capability_config_verified': True, 'owner': 'inputless', 'pro': 0, 'aip': 0, 'znr': 0,
            'observer_prefix_recoveries': recovered_prefixes,
            'caller_tid': int(query[2]['tid']), 'flags': expected.hex(), 'console_sha256': sha,
            'original_device_configuration_verified': False, 'audio_input_verified': False,
            'audio_output_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        proof = {'audio_capability_config_verified': False, 'error': str(error) or type(error).__name__,
                 'original_device_configuration_verified': False, 'audio_input_verified': False,
                 'audio_output_verified': False, 'camera_startup_verified': False}
    (args.run / 'audio-capabilities-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['audio_capability_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
