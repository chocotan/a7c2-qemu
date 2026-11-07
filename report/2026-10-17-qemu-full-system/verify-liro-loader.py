#!/usr/bin/env python3
"""Associate native loader observations without claiming LIRO initialized."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify(run):
    console = (run / 'console.log').read_bytes()
    sha = hashlib.sha256(console).hexdigest()
    inputs = json.loads((run / 'inputs.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    require(inputs['experiment'].get('observe_liro_loader') is True, 'Observer was not explicitly enabled')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha, 'Terminal console differs')
    require(b'FULL_LIRO_OBSERVE_FAILURE' not in console, 'Observer reported failure')
    text = console.decode(errors='replace')
    pid = int(re.search(r'OBS OBSERVER_READY pid=(\d+)', text)[1])
    rows = [(m[1], dict(re.findall(r'(\w+)=([^\s]+)', m[2]))) for m in
            re.finditer(r'FULL_LIRO_(BACKUP|ARGS) ([^\r\n]+)', text)]
    backups = [value for kind, value in rows if kind == 'BACKUP' and int(value['pid']) == pid]
    arguments = [value for kind, value in rows if kind == 'ARGS' and int(value['pid']) == pid]
    require(backups and arguments, 'No original im loader records')
    backup, formatted = backups[0], arguments[0]
    require(int(backup['caller'], 0) == 0x406178 and int(backup['key'], 0) == 0xfa007c and
            int(formatted['caller'], 0) == 0x4061c4, 'Original caller/key differs')
    slot = bytes.fromhex(backup['slot_hex'])
    require(len(slot) == 8 and formatted['complete'] == '1', 'Slot width or arguments truncated')
    raw = bytes.fromhex(formatted['args_hex'])
    args = raw.decode('ascii')
    require(int(formatted['original_rc']) == len(raw) == int(formatted['captured_bytes']) and
            int(formatted['capacity']) > len(raw), 'Original formatted length differs')
    addresses = re.findall(r'(?:^|\s)adr=0x([0-9a-fA-F]+)(?=\s|$)', args)
    require(len(addresses) == 1 and int(addresses[0], 16) == int.from_bytes(slot, 'little'),
            'Actual native arguments do not carry the observed caller slot')
    require(all(int(row[field]) == 0 for row in (backup, formatted) for field in ('flags_rc', 'argv_flags_rc')),
            'Native flags read failed')
    missing = ('dma330_mem_transfer_async', 'pciatu_map', 'pciatu_unmap', 'interchip_transfer_async')
    require(all('liro: Unknown symbol ' + name in text for name in missing), 'Expected original link-failure evidence missing')
    rc = int(backup['original_rc'])
    return {'schema': 2, 'liro_loader_observation_verified': True, 'pid': pid, 'native_backup_rc': rc,
            'native_backup_return_semantics': 'byte-count-on-success',
            'native_backup_return_matches_slot_length': rc == len(slot), 'caller_slot': hex(int.from_bytes(slot, 'little')),
            'flags_at_backup_sample': hex(int(backup['flags'], 0)),
            'flags_at_format_sample': hex(int(formatted['flags'], 0)),
            'argv_flags_at_format_sample': hex(int(formatted['argv_flags'], 0)),
            'actual_module_arguments': args, 'module_link_failed': True,
            'console_sha256': sha, 'LIRO_initialized_verified': False, 'MC_owner_verified': False,
            'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError) as error:
        proof = {'liro_loader_observation_verified': False, 'error': str(error) or type(error).__name__,
                 'LIRO_initialized_verified': False, 'MC_owner_verified': False, 'camera_startup_verified': False}
    (args.run / 'liro-loader-observation-proof-v2.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['liro_loader_observation_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
